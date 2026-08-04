"""
TencentLive 图像生成模块 (TencentLive Image Generation)

通过腾讯云 AIGC Model Hub 的 Gemini 兼容接口生成图像:

    POST {base_url}/v1/wand/gem-image/generation/flex
    Headers: X-Api-Key: <key>

入参和出参均兼容 Gemini generateContent 格式：

文生图:
    {
      "model": "gemini-3.1-flash-image",
      "contents": [
        {"role": "user", "parts": [{"text": "A cinematic photo of ..."}]}
      ],
      "generationConfig": {
        "imageConfig": {"imageSize": "1K", "aspectRatio": "16:9"}
      }
    }

图生图（base64）:
    parts: [{"inline_data": {"mime_type": "image/png", "data": "<base64>"}},
            {"text": "change background to a beach at sunset"}]

图生图（URL）:
    parts: [{"file_data": {"mime_type": "image/jpeg", "file_uri": "https://..."}},
            {"text": "make it a watercolor painting"}]

响应解析兼容 Gemini 标准 camelCase 键（inlineData / usageMetadata）以及
TencentLive 文档中的 snake_case 键（inline_data / usage_metadata）。
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

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
from app.providers.base import UpstreamProviderError
from app.providers.image_size_utils import resolve_image_size
from app.utils import gen_id, json_loads

logger = logging.getLogger("model_link.tencentlive")

# TencentLive AIGC Model Hub Gemini 图像生成接口路径
TENCENTLIVE_GEM_IMAGE_PATH = "/v1/wand/gem-image/generation/flex"

# TencentLive AIGC Model Hub 默认域名
TENCENTLIVE_DEFAULT_BASE_URL = "https://platform.wand-aigc.com"

# 已知支持的 Gemini 图像生成模型（nano-banana 系列）
TENCENTLIVE_IMAGE_MODELS: List[str] = [
    "gemini-2.5-flash-image",
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
    "gemini-3.1-flash-image",
]


def is_tencentlive_image_model(model: str) -> bool:
    """
    Check if the model is a TencentLive image generation model.

    TencentLive 透传 Gemini 图像模型名，因此接受已知的 nano-banana 系列
    （gemini-2.5-flash-image / gemini-3-pro-image-preview /
    gemini-3.1-flash-image-preview / gemini-3.1-flash-image）以及任何
    ``gemini-*-image*`` 命名的模型。

    Args:
        model: Model name (case-insensitive)

    Returns:
        True if the model is a TencentLive image generation model
    """
    model_lower = model.lower()
    if model_lower in TENCENTLIVE_IMAGE_MODELS:
        return True
    return model_lower.startswith("gemini-") and "image" in model_lower


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

    URL images are passed through as-is; base64 images are emitted as
    data URIs (``data:<mime>;base64,<data>``).

    Args:
        messages: List of Message objects

    Returns:
        List of image URLs / data URIs
    """
    reference_images: List[str] = []
    for msg in messages:
        if msg.role != MessageRole.USER:
            continue
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if not isinstance(block, ContentBlock):
                continue
            if block.type == ContentType.IMAGE_URL and block.url:
                reference_images.append(block.url)
            elif block.type == ContentType.IMAGE_BASE64 and block.data:
                mime = block.media_type or "image/jpeg"
                reference_images.append(f"data:{mime};base64,{block.data}")
    return reference_images


def _build_image_part(image: str) -> Dict[str, Any]:
    """
    Convert a reference image (URL or data URI) into a Gemini part.

    Data URIs are sent as ``inline_data`` (base64), everything else as
    ``file_data`` (URL), matching the TencentLive curl examples.

    Args:
        image: Image URL or ``data:<mime>;base64,<data>`` URI

    Returns:
        Gemini-compatible image part dict
    """
    if image.startswith("data:"):
        try:
            header, _, b64_data = image.partition(",")
            mime = header.split(":")[1].split(";")[0].strip() or "image/jpeg"
        except Exception:
            mime, b64_data = "image/jpeg", image
        return {"inline_data": {"mime_type": mime, "data": b64_data}}
    return {"file_data": {"mime_type": "image/jpeg", "file_uri": image}}


def _build_request_body(
    model: str,
    prompt: str,
    reference_images: List[str],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the TencentLive Gemini-compatible request body.

    Args:
        model: Model name (passed through to the upstream API)
        prompt: Text prompt
        reference_images: Optional reference image URLs / data URIs
        metadata: Request metadata (size / aspect_ratio / resolution / number)

    Returns:
        Request body with ``contents`` and ``generationConfig.imageConfig``
    """
    parts: List[Dict[str, Any]] = []
    # Reference images come before the text instruction, as in the TencentLive
    # image-to-image curl examples.
    for image in reference_images:
        parts.append(_build_image_part(image))
    if prompt:
        parts.append({"text": prompt})

    contents: List[Dict[str, Any]] = [{"role": "user", "parts": parts}]
    request_body: Dict[str, Any] = {
        "model": model,
        "contents": contents,
    }

    # Map size / aspect_ratio / resolution to Gemini imageConfig via the
    # shared resolution table: (aspect_ratio, resolution_tier).
    size = metadata.get("size")
    aspect_ratio = metadata.get("aspect_ratio")
    resolution = metadata.get("resolution")
    image_config: Dict[str, Any] = {}
    if size or aspect_ratio or resolution:
        mapped_ar, mapped_tier = resolve_image_size(
            size=size or "",
            aspect_ratio=aspect_ratio or "",
            resolution=resolution or "",
        )
        aspect_ratio = mapped_ar or aspect_ratio
        resolution = mapped_tier or resolution

    if aspect_ratio:
        image_config["aspectRatio"] = aspect_ratio
    if resolution:
        image_config["imageSize"] = resolution

    number = metadata.get("number")
    if number and int(number) > 1:
        image_config["numberOfImages"] = int(number)

    if image_config:
        request_body["generationConfig"] = {"imageConfig": image_config}

    return request_body


# =============================================================================
# 响应解析
# =============================================================================

def _parse_image_parts(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Parse Gemini-compatible response parts and extract images.

    Supports both camelCase (``inlineData`` / ``fileData``) and snake_case
    (``inline_data`` / ``file_data``) keys.

    Args:
        parts: List of Gemini response parts

    Returns:
        List of image_generation_call items, each containing:
        - type: "image_generation_call"
        - status: "completed"
        - result: data URI or file URI
    """
    images: List[Dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        # Skip thinking/reasoning images — only include final result images
        if part.get("thought", False):
            continue

        inline = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline, dict) and inline.get("data"):
            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
            images.append({
                "type": "image_generation_call",
                "status": "completed",
                "result": f"data:{mime};base64,{inline['data']}",
            })
            continue

        file_data = part.get("fileData") or part.get("file_data")
        if isinstance(file_data, dict) and (file_data.get("fileUri") or file_data.get("file_uri")):
            images.append({
                "type": "image_generation_call",
                "status": "completed",
                "result": file_data.get("fileUri") or file_data.get("file_uri"),
            })
    return images


def _parse_gemini_image_response(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a Gemini-compatible image generation response.

    Args:
        response_data: Raw upstream response JSON

    Returns:
        Dict with ``images`` (list of image_generation_call items),
        ``usage`` (UsageInfo), ``finish_reason`` (FinishReason)
    """
    parts: List[Dict[str, Any]] = []
    candidates = response_data.get("candidates") or []
    finish_reason = FinishReason.STOP
    if candidates:
        candidate = candidates[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        gemini_finish = candidate.get("finishReason") or candidate.get("finish_reason")
        finish_map = {
            "STOP": FinishReason.STOP,
            "MAX_TOKENS": FinishReason.LENGTH,
            "SAFETY": FinishReason.CONTENT_FILTER,
            "RECITATION": FinishReason.STOP,
        }
        finish_reason = finish_map.get(str(gemini_finish).upper(), FinishReason.STOP)

    images = _parse_image_parts(parts)

    usage_meta = response_data.get("usageMetadata") or response_data.get("usage_metadata") or {}
    usage = UsageInfo(
        prompt_tokens=usage_meta.get("promptTokenCount") or usage_meta.get("prompt_token_count") or 0,
        completion_tokens=usage_meta.get("candidatesTokenCount") or usage_meta.get("candidates_token_count") or 0,
        total_tokens=usage_meta.get("totalTokenCount") or usage_meta.get("total_token_count") or 0,
    )

    return {
        "images": images,
        "usage": usage,
        "finish_reason": finish_reason,
    }


def _build_image_chat_response(
    images: List[Dict[str, Any]],
    model: str,
    usage: UsageInfo,
    finish_reason: FinishReason,
    metadata: Optional[Dict[str, Any]] = None,
) -> ChatResponse:
    """
    Build a ChatResponse for TencentLive image generation results.

    Stores image_generation_call items as JSON in the message content,
    compatible with the Responses API adapter format used by other providers.

    Args:
        images: List of image_generation_call items
        model: Model name
        usage: Token usage info
        finish_reason: Finish reason from the response
        metadata: Request metadata (carries response_format / size for usage)

    Returns:
        ChatResponse with image generation results
    """
    image_count = len(images)
    metadata = metadata or {}
    extra: Dict[str, Any] = {
        "output_image_number": image_count,
        "_response_format": metadata.get("response_format", "url"),
    }

    # Enrich usage with resolution/aspect so pricing can use image tiers
    resolved_aspect, resolved_tier = resolve_image_size(
        size=str(metadata.get("size", "")),
        aspect_ratio=str(metadata.get("aspect_ratio", "")),
        resolution=str(metadata.get("resolution", "")),
    )
    if resolved_tier:
        extra["output_image_resolution"] = resolved_tier
    if resolved_aspect:
        extra["output_image_aspect"] = resolved_aspect
    usage.extra = extra

    return ChatResponse(
        id=gen_id("img"),
        model=model,
        choices=[ChatChoice(
            index=0,
            message=Message(
                role=MessageRole.ASSISTANT,
                content=json.dumps(images, ensure_ascii=False),
            ),
            finish_reason=finish_reason,
        )],
        usage=usage,
        created=int(time.time()),
        provider="tencentlive",
    )


# =============================================================================
# API 调用
# =============================================================================

async def execute_tencentlive_image_generation(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Message],
    metadata: dict,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute image generation via the TencentLive Gemini-compatible API.

    Sends a single POST to ``{base_url}/v1/wand/gem-image/generation/flex``
    with the ``X-Api-Key`` header and a Gemini-format request body.

    Args:
        api_key: TencentLive API key
        base_url: TencentLive AIGC Model Hub base URL
        model: Model name (e.g. "gemini-3.1-flash-image")
        messages: List of Message objects
        metadata: Request metadata (carries image generation parameters)
        tracer: Optional tracer for span tracking

    Returns:
        ChatResponse with image_generation_call items in the message content

    Raises:
        ValueError: On unsupported model or missing prompt
        UpstreamProviderError: On upstream API error
        RuntimeError: On missing images in the response
    """
    if not is_tencentlive_image_model(model):
        raise ValueError(
            f"Unknown TencentLive image generation model: {model}. "
            f"Supported models: {', '.join(TENCENTLIVE_IMAGE_MODELS)}"
        )
    base_url = base_url or TENCENTLIVE_DEFAULT_BASE_URL

    prompt = _extract_prompt_from_messages(messages)
    reference_images = _collect_reference_images(messages)
    if not prompt and not reference_images:
        raise ValueError("TencentLive image generation requires a text prompt or a reference image")

    request_body = _build_request_body(model, prompt, reference_images, metadata)

    url = f"{base_url.rstrip('/')}{TENCENTLIVE_GEM_IMAGE_PATH}"
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }

    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="tencentlive", input_data=request_body)
        if _child_span:
            _child_span.log_input(request_body)
    _trace_error: Optional[Exception] = None

    try:
        timeout = int(metadata.get("timeout") or 600)
        async with shared_client() as client:
            response = await client.post(url, json=request_body, headers=headers, timeout=timeout)

        if response.status_code >= 400:
            body_text = response.text
            error_type = "api_error"
            request_id = None
            try:
                err_data = response.json()
                if isinstance(err_data, dict):
                    error = err_data.get("error")
                    if isinstance(error, dict):
                        error_type = error.get("code") or error.get("status") or error_type
                        request_id = error.get("requestId") or error.get("request_id")
                    request_id = request_id or err_data.get("requestId") or err_data.get("request_id")
            except Exception:
                pass
            raise UpstreamProviderError(
                f"TencentLive image generation API error ({response.status_code}): {body_text}",
                status_code=response.status_code,
                error_type=error_type,
                request_id=request_id,
            )

        response_data = response.json()
        if _child_span:
            _child_span.log_output(response_data)

        parsed = _parse_gemini_image_response(response_data)
        images = parsed["images"]
        if not images:
            raise RuntimeError(
                f"TencentLive image generation: no images in response: "
                f"{json.dumps(response_data, ensure_ascii=False)}"
            )

        logger.info(
            "TencentLive image generation: model=%s images=%d prompt=%s...",
            model, len(images), prompt[:80],
        )

        return _build_image_chat_response(
            images=images,
            model=model,
            usage=parsed["usage"],
            finish_reason=parsed["finish_reason"],
            metadata=metadata,
        )

    except Exception:
        _trace_error = sys.exc_info()[1]
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)


# =============================================================================
# 流式响应生成
# =============================================================================

async def stream_image_generation(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    """
    Execute TencentLive image generation and yield the result as StreamChunks.

    The upstream API is non-streaming; this function calls the non-streaming
    API, collects all images, then emits them as image_generation_call SSE
    events via raw_sse_passthrough (same pattern as Vidu / Mulerun).

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
