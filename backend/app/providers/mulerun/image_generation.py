"""
Mulerun 图像生成模块 (Mulerun Image Generation)

通过 Mulerun API 的图像生成模型生成图像。不同模型对应不同的 vendor 和 API 路径。

支持的模型与 API 路径：
┌─────────────────────────────────┬──────────────────────────────────────────┐
│ Model                           │ API path (relative to api.mulerun.com)  │
├─────────────────────────────────┼──────────────────────────────────────────┤
│ gpt-image-2                     │ /vendors/openai/v1/gpt-image-2           │
│ gemini-2.5-flash-image          │ /vendors/google/v1/nano-banana          │
│ gemini-3-pro-image-preview      │ /vendors/google/v1/nano-banana-pro      │
│ gemini-3.1-flash-image-preview  │ /vendors/google/v1/nano-banana-2        │
└─────────────────────────────────┴──────────────────────────────────────────┘

流程：
1. 提交任务:  POST https://api.mulerun.com{path}/generation
   请求体:  {"prompt": "..."}
   响应:    {"task_info": {"id": "...", "status": "pending", ...}}

2. 轮询结果: GET https://api.mulerun.com{path}/generation/{task_id}
   响应:    {"task_info": {"id": "...", "status": "completed", ...},
             "images": ["https://..."]}

API 文档参考: https://api.mulerun.com
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any, Dict, List, Optional, AsyncGenerator
from urllib.parse import urlparse

import httpx

from app.http_client import shared_client
from app.abstraction.chat import (
    ChatChoice,
    ChatRequest,
    ChatResponse,
    FinishReason,
    UsageInfo,
)
from app.abstraction.messages import Message, MessageRole
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id, json_loads

logger = logging.getLogger("model_link.mulerun")

# 轮询配置
_POLL_INTERVAL_S = 2.0   # 每次轮询间隔（秒）
_POLL_MAX_WAIT_S = 300   # 最大等待时间（秒）


# =============================================================================
# 图像生成模型 → API 路径映射
# =============================================================================

# 不同模型在 Mulerun 中使用不同的 vendor 路径
MULERUN_IMAGE_GENERATION_PATHS: Dict[str, str] = {
    "gpt-image-2":                    "/vendors/openai/v1/gpt-image-2",
    "gemini-2.5-flash-image":         "/vendors/google/v1/nano-banana",
    "gemini-3-pro-image-preview":     "/vendors/google/v1/nano-banana-pro",
    "gemini-3.1-flash-image-preview": "/vendors/google/v1/nano-banana-2",
}

# 所有支持的图像生成模型（从 PATHS 的 keys 自动生成）
MULERUN_IMAGE_MODELS: List[str] = list(MULERUN_IMAGE_GENERATION_PATHS.keys())


def is_mulerun_image_model(model: str) -> bool:
    """
    Check if the model is a Mulerun image generation model.

    Looks up the model (case-insensitive) in ``MULERUN_IMAGE_GENERATION_PATHS``.

    Args:
        model: Model name (case-insensitive)

    Returns:
        True if the model is a Mulerun image generation model
    """
    return model.lower() in MULERUN_IMAGE_GENERATION_PATHS


def _get_mulerun_api_root(base_url: str) -> str:
    """
    Extract the API root (scheme + host) from the provider's base_url.

    Args:
        base_url: Provider base URL, e.g. ``https://api.mulerun.com/vendors/openai/v1``

    Returns:
        API root URL, e.g. ``https://api.mulerun.com``
    """
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def has_image_generation_tool(request: ChatRequest) -> bool:
    """Check if the request contains an ``image_generation`` tool."""
    from app.abstraction.tools import has_image_generation_tool as _check
    return _check(request.tools)


# =============================================================================
# API 调用与响应解析
# =============================================================================

def _extract_prompt_from_messages(messages: List[Message]) -> str:
    """
    Extract the text prompt from ChatRequest messages.

    Joins all text content from user-role messages into a single prompt string.

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


async def execute_mulerun_image_generation(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Message],
    metadata: dict,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute image generation via the Mulerun image generation API.

    Uses an async polling pattern:
    1. Look up the model's API path from ``MULERUN_IMAGE_GENERATION_PATHS``
    2. POST https://api.mulerun.com{path}/generation → get task_info.id
    3. Poll GET https://api.mulerun.com{path}/generation/{task_id}
    4. When status == "completed", extract images

    Args:
        api_key: Mulerun API key
        base_url: Mulerun API base URL (e.g. https://api.mulerun.com/vendors/openai/v1)
        model: Model name (e.g. "gpt-image-2", "gemini-2.5-flash-image")
        messages: List of Message objects
        metadata: Request metadata (carries image generation parameters)
        tracer: Optional tracer for span tracking

    Returns:
        ChatResponse with image_generation_call items in the message content

    Raises:
        RuntimeError: On API error or timeout
    """
    # Look up the API path for this model
    model_lower = model.lower()
    api_path = MULERUN_IMAGE_GENERATION_PATHS.get(model_lower)
    if not api_path:
        raise ValueError(
            f"Unknown Mulerun image generation model: {model}. "
            f"Supported models: {', '.join(MULERUN_IMAGE_MODELS)}"
        )

    # Extract prompt from messages
    prompt = _extract_prompt_from_messages(messages)
    if not prompt:
        raise ValueError("Mulerun image generation requires a text prompt")

    # Build submission request
    request_body: Dict[str, Any] = {
        "prompt": prompt,
    }

    # Optional parameters from metadata (passed via /v1/images/generations API)
    quality = metadata.get("quality")
    if quality:
        request_body["quality"] = quality

    size = metadata.get("size")
    if size:
        request_body["size"] = size

    # format / output_format → "format" in request body
    output_format = metadata.get("image_format") or metadata.get("output_format")
    if output_format:
        request_body["format"] = output_format

    # Gemini image model parameters
    aspect_ratio = metadata.get("aspect_ratio")
    if aspect_ratio:
        request_body["aspect_ratio"] = aspect_ratio

    resolution = metadata.get("resolution")
    if resolution:
        request_body["resolution"] = resolution

    # Optional: include reference images from messages (image-to-image)
    reference_images: List[str] = []
    for msg in messages:
        if msg.role != MessageRole.USER:
            continue
        if isinstance(msg.content, list):
            from app.abstraction.messages import ContentBlock, ContentType
            for block in msg.content:
                if isinstance(block, ContentBlock):
                    if block.type == ContentType.IMAGE_URL and block.url:
                        reference_images.append(block.url)
                    elif block.type == ContentType.IMAGE_BASE64 and block.data:
                        mime = block.media_type or "image/jpeg"
                        reference_images.append(f"data:{mime};base64,{block.data}")

    if reference_images:
        request_body["images"] = reference_images

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    # Build the full API URL: extract host from base_url + model-specific path
    api_root = _get_mulerun_api_root(base_url)
    submit_url = f"{api_root}{api_path}/generation"

    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="mulerun", input_data=request_body)
        if _child_span:
            _child_span.log_input(request_body)
    _trace_error: Optional[Exception] = None

    try:
        timeout = int(metadata.get("timeout", _POLL_MAX_WAIT_S) or _POLL_MAX_WAIT_S)
        async with shared_client() as client:
            # Step 1: Submit the generation task
            logger.info("Mulerun image generation: submitting task to %s, prompt=%s...",
                        submit_url, prompt[:80])

            response = await client.post(
                submit_url,
                json=request_body,
                headers=headers,
            )

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(
                        f"Mulerun image generation API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False)}"
                    )
                except (json.JSONDecodeError, ValueError):
                    raise RuntimeError(
                        f"Mulerun image generation API error ({response.status_code}): {response.text}"
                    )

            submit_data = response.json()
            task_info = submit_data.get("task_info", {})
            task_id = task_info.get("id")

            if not task_id:
                raise RuntimeError(
                    f"Mulerun image generation: no task_id in response: "
                    f"{json.dumps(submit_data, ensure_ascii=False)}"
                )

            logger.info("Mulerun image generation: task submitted, task_id=%s", task_id)

            # Step 2: Poll for results
            poll_url = f"{api_root}{api_path}/generation/{task_id}"
            start_time = time.monotonic()
            result_data: Optional[Dict[str, Any]] = None

            while True:
                elapsed = time.monotonic() - start_time
                if elapsed > timeout:
                    raise RuntimeError(
                        f"Mulerun image generation timed out after {timeout}s for task {task_id}"
                    )

                await asyncio.sleep(_POLL_INTERVAL_S)

                poll_response = await client.get(
                    poll_url,
                    headers=headers,
                )

                if poll_response.status_code >= 400:
                    logger.warning(
                        "Mulerun poll error (%s) for task %s, retrying...",
                        poll_response.status_code, task_id,
                    )
                    continue

                poll_data = poll_response.json()
                task_status = poll_data.get("task_info", {}).get("status")

                if task_status == "completed":
                    result_data = poll_data
                    logger.info("Mulerun image generation: task %s completed", task_id)
                    break
                elif task_status == "failed":
                    error_msg = poll_data.get("task_info", {}).get("error", "Unknown error")
                    raise RuntimeError(
                        f"Mulerun image generation failed for task {task_id}: {error_msg}"
                    )
                else:
                    logger.debug(
                        "Mulerun image generation: task %s status=%s, elapsed=%.1fs",
                        task_id, task_status, elapsed,
                    )

        if _child_span and result_data:
            _child_span.log_output(result_data)

        return _parse_mulerun_image_response(result_data, model, metadata, task_id=task_id)

    except RuntimeError:
        _trace_error = sys.exc_info()[1]
        raise
    except Exception as e:
        _trace_error = e
        raise RuntimeError(f"Mulerun image generation API error: {str(e)}")
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)


def _parse_mulerun_image_response(
    data: Dict[str, Any],
    model: str,
    metadata: Optional[dict] = None,
    task_id: str = "",
) -> ChatResponse:
    """
    Parse Mulerun image generation response into ChatResponse.

    Extracts image URLs from the response and packs them as
    image_generation_call items (JSON-encoded) in the message content,
    compatible with the Responses API adapter format.

    Args:
        data: Mulerun API response data
        model: Model name
        metadata: Request metadata (carries response_format for b64_json signal)
        task_id: Task ID for tracking

    Returns:
        ChatResponse with image_generation_call items
    """
    images = data.get("images", [])

    image_call_items: List[Dict[str, Any]] = []
    for img_url in images:
        if img_url:
            image_call_items.append({
                "type": "image_generation_call",
                "status": "completed",
                "result": img_url,
            })

    image_count = len(image_call_items)

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(image_call_items, ensure_ascii=False),
    )

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
            extra={
                'output_image_number': image_count,
                '_response_format': (metadata or {}).get('response_format', 'url'),
                '_task_id': task_id,
            },
        ),
        created=int(time.time()),
        provider="mulerun",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

async def stream_image_generation(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    """
    Execute Mulerun image generation and yield the result as StreamChunks.

    Mulerun image generation is asynchronous (polling-based); this function
    calls the non-streaming API, collects all images, then emits them as
    image_generation_call SSE events via raw_sse_passthrough.

    SSE event sequence (matching the Bailian / Volcengine pattern):
    1. Role marker chunk (delta_role="assistant") → triggers format_stream_start
    2. response.output_item.added  (image_generation_call, status=generating)
    3. response.output_item.done   (image_generation_call, status=completed)
    4. response.completed          (emitted by finish chunk)

    Args:
        chat_fn: The non-streaming chat function (provider.chat)
        request: The chat request with image generation parameters
    """
    # Call the non-streaming API to get the full image result
    response = await chat_fn(request)
    response_id = response.id
    model = response.model

    # Parse the images list from the response content
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

    # Role marker — triggers format_stream_start in the Responses adapter
    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    # Emit one image_generation_call item per image via raw SSE passthrough
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

    # Build the completed response with all image_generation_call items
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
