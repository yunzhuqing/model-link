"""
Vidu 图像生成模块 (Vidu Image Generation)

通过 Vidu 开放平台 API (api.vidu.cn) 的 reference2image 接口异步生成图像。

支持的模型列表（Vidu API 模型名）：
  viduq2、viduq1、viduimage-2、q3-fast、q2-pro、q2-fast

网关标准模型名 → Vidu API 模型名 对应关系：
┌─────────────────────────────────┬───────────────┐
│ Gateway model                   │ Vidu model    │
├─────────────────────────────────┼───────────────┤
│ gpt-image-2                     │ viduimage-2   │
│ gemini-2.5-flash-image          │ q2-fast       │
│ gemini-3-pro-image-preview      │ q2-pro        │
│ gemini-3.1-flash-image-preview  │ q3-fast       │
└─────────────────────────────────┴───────────────┘

Vidu 原生模型名（viduq2 / viduq1 / viduimage-2 / q3-fast / q2-pro / q2-fast）
同样被接受，请求到达时直接透传，不经过翻译。

流程（两步）：
1. 提交任务:  POST https://api.vidu.cn/ent/v2/reference2image
   请求体:  {"model": "viduq2", "prompt": "...", "resolution": "4K",
             "aspect_ratio": "1:1", "quality": "low"}
   响应:    {"task_id": "...", "state": "created", ...}
2. 轮询结果: GET https://api.vidu.cn/ent/v2/tasks/{task_id}/creations
   响应:    {"state": "success", "creations": [{"url": "https://..."}], ...}
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any, Dict, List, Optional, AsyncGenerator

from app.abstraction.chat import (
    ChatChoice,
    ChatRequest,
    ChatResponse,
    FinishReason,
    UsageInfo,
)
from app.abstraction.messages import ContentBlock, ContentType, Message, MessageRole
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.http_client import shared_client
from app.providers.image_size_utils import resolve_image_size
from app.utils import gen_id, json_loads

logger = logging.getLogger("model_link.vidu")

# 轮询配置
_POLL_INTERVAL_S = 2.0   # 每次轮询间隔（秒）
_POLL_MAX_WAIT_S = 300   # 最大等待时间（秒）


# =============================================================================
# 图像生成模型 → Vidu API 模型映射
# =============================================================================

VIDU_MODEL_MAP: Dict[str, str] = {
    # 网关标准模型名 → Vidu API 模型名
    "gpt-image-2":                    "viduimage-2",
    "gemini-2.5-flash-image":         "q2-fast",
    "gemini-3-pro-image-preview":     "q2-pro",
    "gemini-3.1-flash-image-preview": "q3-fast",
    # Vidu 原生模型名直接透传
    "viduq1":                         "viduq1",
    "viduq2":                         "viduq2",
    "viduimage-2":                    "viduimage-2",
    "q2-fast":                        "q2-fast",
    "q2-pro":                         "q2-pro",
    "q3-fast":                        "q3-fast",
}

# 所有支持的图像生成模型（从映射的 keys 自动生成）
VIDU_IMAGE_MODELS: List[str] = list(VIDU_MODEL_MAP.keys())


def is_vidu_image_model(model: str) -> bool:
    """
    Check if the model is a Vidu image generation model.

    Args:
        model: Model name (case-insensitive)

    Returns:
        True if the model is a Vidu image generation model
    """
    return model.lower() in VIDU_MODEL_MAP


def has_image_generation_tool(request: ChatRequest) -> bool:
    """Check if the request contains an ``image_generation`` tool."""
    from app.abstraction.tools import has_image_generation_tool as _check
    return _check(request.tools)


# =============================================================================
# 请求构建
# =============================================================================

def _extract_prompt_from_messages(messages: List[Message]) -> str:
    """
    Extract the text prompt from ChatRequest messages.

    Args:
        messages: List of Message objects

    Returns:
        Combined prompt string
    """
    parts = []
    for msg in messages:
        if msg.role != MessageRole.USER:
            continue
        text = msg.get_text_content()
        if text:
            parts.append(text)
    return " ".join(parts) if parts else ""


def _collect_reference_images(messages: List[Message]) -> List[str]:
    """
    Collect reference images (image-to-image) from user messages.

    URL images are passed through as-is; base64 images are passed as data URIs.

    Args:
        messages: List of Message objects

    Returns:
        List of image URLs / data URIs
    """
    reference_images: List[str] = []
    for msg in messages:
        if msg.role != MessageRole.USER:
            continue
        if isinstance(msg.content, list):
            for block in msg.content:
                if not isinstance(block, ContentBlock):
                    continue
                if block.type == ContentType.IMAGE_URL and block.url:
                    reference_images.append(block.url)
                elif block.type == ContentType.IMAGE_BASE64 and block.data:
                    mime = block.media_type or "image/jpeg"
                    reference_images.append(f"data:{mime};base64,{block.data}")
    return reference_images


def _build_vidu_request(
    vidu_model: str,
    prompt: str,
    metadata: Dict[str, Any],
    reference_images: List[str],
) -> Dict[str, Any]:
    """
    Build the Vidu reference2image request body.

    Vidu API format:
    {
        "model": "viduq2",
        "prompt": "...",
        "resolution": "4K",
        "aspect_ratio": "1:1",
        "quality": "low",
        "images": ["https://..."]   // 可选，图生图参考图
    }

    Args:
        vidu_model: Vidu API model name
        prompt: Text prompt
        metadata: Request metadata (size / aspect_ratio / resolution / quality)
        reference_images: Optional reference image URLs / data URIs

    Returns:
        Vidu request body
    """
    request_body: Dict[str, Any] = {
        "model": vidu_model,
        "prompt": prompt,
    }

    size = metadata.get("size")
    aspect_ratio = metadata.get("aspect_ratio")
    resolution = metadata.get("resolution")

    # Map ``size`` to Vidu-compatible aspect_ratio/resolution via the shared table
    if size or aspect_ratio or resolution:
        mapped_ar, mapped_res = resolve_image_size(
            size=size or "",
            aspect_ratio=aspect_ratio or "",
            resolution=resolution or "",
        )
        aspect_ratio = mapped_ar or aspect_ratio
        resolution = mapped_res or resolution

    if aspect_ratio:
        request_body["aspect_ratio"] = aspect_ratio

    if resolution:
        request_body["resolution"] = resolution

    quality = metadata.get("quality")
    if quality:
        request_body["quality"] = quality

    if reference_images:
        request_body["images"] = reference_images

    return request_body


# =============================================================================
# API 调用与响应解析
# =============================================================================

async def _submit_vidu_task(
    api_key: str,
    base_url: str,
    request_body: Dict[str, Any],
    tracer: Any = None,
) -> str:
    """
    Submit a Vidu reference2image task.

    Args:
        api_key: Vidu API key
        base_url: Vidu API base URL (e.g. https://api.vidu.cn)
        request_body: Vidu request body
        tracer: Optional tracer

    Returns:
        task_id string

    Raises:
        RuntimeError: On API error
    """
    url = f"{base_url.rstrip('/')}/ent/v2/reference2image"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    async with shared_client() as client:
        response = await client.post(url, json=request_body, headers=headers, timeout=60)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Vidu image generation API error ({response.status_code}): {response.text}"
        )

    data = response.json()
    task_id = data.get("task_id", "")
    if not task_id:
        raise RuntimeError(
            f"Vidu image generation: no task_id in response: "
            f"{json.dumps(data, ensure_ascii=False)}"
        )
    return task_id


async def _poll_vidu_task(
    api_key: str,
    base_url: str,
    task_id: str,
    poll_timeout: Optional[int] = None,
    tracer: Any = None,
) -> List[str]:
    """
    Poll the Vidu task detail endpoint until the task succeeds.

    Args:
        api_key: Vidu API key
        base_url: Vidu API base URL (e.g. https://api.vidu.cn)
        task_id: Task ID from the submission response
        poll_timeout: Optional timeout override (seconds)
        tracer: Optional tracer

    Returns:
        List of generated image URLs

    Raises:
        RuntimeError: On task failure or timeout
    """
    poll_url = f"{base_url.rstrip('/')}/ent/v2/tasks/{task_id}/creations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    max_wait = poll_timeout or _POLL_MAX_WAIT_S
    start_time = time.monotonic()
    poll_count = 0

    async with shared_client() as client:
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > max_wait:
                raise RuntimeError(
                    f"Vidu image generation timed out after {max_wait}s for task {task_id}"
                )

            await asyncio.sleep(_POLL_INTERVAL_S)
            poll_count += 1

            response = await client.get(poll_url, headers=headers, timeout=60)
            if response.status_code >= 400:
                logger.warning(
                    "Vidu poll error (%s) for task %s, retrying...",
                    response.status_code, task_id,
                )
                continue

            data = response.json()
            state = str(data.get("state", "")).lower()
            logger.debug(
                "Vidu image generation: task %s state=%s progress=%s, elapsed=%.1fs",
                task_id, state, data.get("progress", ""), elapsed,
            )

            if state == "success":
                creations = data.get("creations") or []
                urls: List[str] = []
                for creation in creations:
                    url = creation.get("url", "") if isinstance(creation, dict) else ""
                    if url:
                        urls.append(url)
                if not urls:
                    raise RuntimeError(
                        f"Vidu image generation task {task_id} succeeded but no image URLs found: "
                        f"{json.dumps(data, ensure_ascii=False)}"
                    )
                return urls

            if state in ("failed", "error", "cancelled", "canceled"):
                error_msg = data.get("err_msg") or data.get("err_code") or "Unknown error"
                raise RuntimeError(
                    f"Vidu image generation failed for task {task_id}: {error_msg}"
                )


async def execute_vidu_image_generation(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Message],
    metadata: dict,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute image generation via the Vidu reference2image API.

    Uses an async polling pattern:
    1. POST {base}/ent/v2/reference2image → get task_id
    2. Poll GET {base}/ent/v2/tasks/{task_id}/creations until state == "success"

    Args:
        api_key: Vidu API key
        base_url: Vidu API base URL (e.g. https://api.vidu.cn)
        model: Gateway model name (e.g. "gpt-image-2", "gemini-2.5-flash-image")
        messages: List of Message objects
        metadata: Request metadata (carries image generation parameters)
        tracer: Optional tracer for span tracking

    Returns:
        ChatResponse with image_generation_call items in the message content

    Raises:
        ValueError: Unknown model or missing prompt
        RuntimeError: On API error or timeout
    """
    model_lower = model.lower()
    vidu_model = VIDU_MODEL_MAP.get(model_lower)
    if not vidu_model:
        raise ValueError(
            f"Unknown Vidu image generation model: {model}. "
            f"Supported models: {', '.join(VIDU_IMAGE_MODELS)}"
        )

    prompt = _extract_prompt_from_messages(messages)
    if not prompt:
        raise ValueError("Vidu image generation requires a text prompt")

    reference_images = _collect_reference_images(messages)
    request_body = _build_vidu_request(vidu_model, prompt, metadata, reference_images)

    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="vidu", input_data=request_body)
        if _child_span:
            _child_span.log_input(request_body)
    _trace_error: Optional[Exception] = None

    try:
        timeout = int(metadata.get("timeout", _POLL_MAX_WAIT_S) or _POLL_MAX_WAIT_S)
        task_id = await _submit_vidu_task(api_key, base_url, request_body, tracer=_child_span)
        logger.info("Vidu image generation: task submitted, task_id=%s", task_id)

        image_urls = await _poll_vidu_task(
            api_key,
            base_url,
            task_id,
            poll_timeout=timeout,
            tracer=_child_span,
        )

        if _child_span:
            _child_span.log_output({"task_id": task_id, "image_count": len(image_urls), "status": "succeeded"})

        return _parse_vidu_image_response(image_urls, model, metadata, task_id=task_id)

    except RuntimeError:
        _trace_error = sys.exc_info()[1]
        raise
    except Exception as e:
        _trace_error = e
        raise RuntimeError(f"Vidu image generation API error: {str(e)}")
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)


def _parse_vidu_image_response(
    image_urls: List[str],
    model: str,
    metadata: Optional[dict] = None,
    task_id: str = "",
) -> ChatResponse:
    """
    Parse Vidu image URLs into a ChatResponse.

    Packs image_generation_call items (JSON-encoded) into the message content,
    compatible with the Responses API adapter format.

    Args:
        image_urls: Generated image URLs
        model: Gateway model name
        metadata: Request metadata (carries response_format / size for usage)
        task_id: Task ID for tracking

    Returns:
        ChatResponse with image_generation_call items
    """
    metadata = metadata or {}
    image_call_items: List[Dict[str, Any]] = [
        {
            "type": "image_generation_call",
            "status": "completed",
            "result": url,
        }
        for url in image_urls
        if url
    ]
    image_count = len(image_call_items)

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(image_call_items, ensure_ascii=False),
    )

    extra: Dict[str, Any] = {
        'output_image_number': image_count,
        '_response_format': metadata.get('response_format', 'url'),
        '_task_id': task_id,
    }

    # Enrich usage with resolution/aspect so pricing can use image tiers
    resolved_aspect, resolved_tier = resolve_image_size(
        size=str(metadata.get('size', '')),
        aspect_ratio=str(metadata.get('aspect_ratio', '')),
        resolution=str(metadata.get('resolution', '')),
    )
    if resolved_tier:
        extra['output_image_resolution'] = resolved_tier
    if resolved_aspect:
        extra['output_image_aspect'] = resolved_aspect

    return ChatResponse(
        id=gen_id("img"),
        model=model,
        choices=[ChatChoice(
            index=0,
            message=message,
            finish_reason=FinishReason.STOP,
        )],
        usage=UsageInfo(
            prompt_tokens=0,
            completion_tokens=image_count,
            total_tokens=image_count,
            extra=extra,
        ),
        created=int(time.time()),
        provider="vidu",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

async def stream_image_generation(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    """
    Execute Vidu image generation and yield the result as StreamChunks.

    Vidu image generation is asynchronous (polling-based); this function calls
    the non-streaming API, collects all images, then emits them as
    image_generation_call SSE events via raw_sse_passthrough.

    SSE event sequence:
    1. Role marker chunk (delta_role="assistant") → triggers format_stream_start
    2. response.output_item.added  (image_generation_call, status=generating)
    3. response.output_item.done   (image_generation_call, status=completed)
    4. response.completed          (emitted by finish chunk)

    Args:
        chat_fn: The non-streaming chat function (provider.chat)
        request: The chat request with image generation parameters
    """
    response = await chat_fn(request)
    response_id = response.id
    model = response.model

    images: List[Dict[str, Any]] = []
    if response.choices and response.choices[0].message:
        msg = response.choices[0].message
        raw = (
            msg.content
            if isinstance(msg.content, str)
            else (msg.get_text_content() or "[]")
        )
        try:
            images = json_loads(raw) if isinstance(raw, str) else []
        except (json.JSONDecodeError, TypeError):
            images = []

    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    for i, img in enumerate(images):
        result = img.get("result", "")
        call_id = f"{response_id}-{i}" if i > 0 else response_id
        output_index = i

        item_added = {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "type": "image_generation_call",
                "id": call_id,
                "status": "generating",
                "result": None,
            },
        }
        item_done = {
            "type": "response.output_item.done",
            "output_index": output_index,
            "item": {
                "type": "image_generation_call",
                "id": call_id,
                "status": "completed",
                "result": result,
            },
        }

        chunk = StreamChunk(
            id=response_id,
            model=model,
            event_type=StreamEventType.CONTENT_DELTA,
        )
        chunk.raw_sse_passthrough = [
            f"event: response.output_item.added\ndata: {json.dumps(item_added, ensure_ascii=False)}\n\n",
            f"event: response.output_item.done\ndata: {json.dumps(item_done, ensure_ascii=False)}\n\n",
        ]
        yield chunk

    usage_dict: Dict[str, Any] = {}
    if response.usage:
        usage_dict = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    output_items = [
        {
            "type": "image_generation_call",
            "id": (f"{response_id}-{i}" if i > 0 else response_id),
            "status": "completed",
            "result": img.get("result", ""),
        }
        for i, img in enumerate(images)
    ]
    completed_response = {
        "id": response_id,
        "object": "response",
        "status": "completed",
        "model": model,
        "output": output_items,
        "usage": {
            "input_tokens": usage_dict.get("prompt_tokens", 0),
            "output_tokens": usage_dict.get("completion_tokens", 0),
            "total_tokens": usage_dict.get("total_tokens", 0),
        },
    }
    completed_event = {
        "type": "response.completed",
        "response": completed_response,
    }

    finish_chunk = StreamChunk(
        id=response_id,
        model=model,
        event_type=StreamEventType.CONTENT_DELTA,
        created=response.created,
    )
    finish_chunk.raw_sse_passthrough = [
        f"event: response.completed\ndata: {json.dumps(completed_event, ensure_ascii=False)}\n\n",
    ]
    yield finish_chunk
