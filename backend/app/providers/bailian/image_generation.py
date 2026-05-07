"""
阿里云百炼图像生成模块 (Qwen Image Generation & Z-Image)

通义千问图像生成/编辑模型和 Z-Image 模型支持通过 Dashscope 多模态生成 API 进行图像生成和编辑。

支持的模型包括：
- qwen-image-2.0-pro: 通义千问图像生成与编辑模型（支持文生图和图生图）
- z-image-turbo: 快速文生图模型（仅支持文本输入，支持 aspect_ratio 尺寸参数）

API 文档:
https://help.aliyun.com/document_detail/2712195.html

请求格式：
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
{
    "model": "qwen-image-2.0-pro",
    "input": {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"image": "https://..."},
                    {"text": "编辑指令"}
                ]
            }
        ]
    },
    "parameters": {
        "n": 1,
        "watermark": false,
        "size": "1024*1024"
    }
}

响应格式（成功）：
{
    "output": {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": [{"image": "https://result-url.png"}],
                    "role": "assistant"
                }
            }
        ]
    },
    "usage": {"height": 1024, "image_count": 1, "width": 1024},
    "request_id": "..."
}

响应格式（失败）：
{
    "request_id": "...",
    "code": "InvalidApiKey",
    "message": "Invalid API-key provided."
}
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Generator
import json
import time
import base64
import logging
from urllib.request import urlopen

from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id, json_loads


# =============================================================================
# 图像生成模型配置
# =============================================================================

@dataclass
class QwenImageConfig:
    """Qwen 图像生成模型配置"""
    model_name: str      # 模型名称
    display_name: str    # 显示名称
    description: str     # 模型描述


# Qwen 图像生成模型列表
QWEN_IMAGE_MODELS: List[QwenImageConfig] = [
    QwenImageConfig(
        model_name="qwen-image-2.0-pro",
        display_name="Qwen Image 2.0 Pro",
        description="通义千问图像生成与编辑模型，支持文生图和图生图编辑",
    ),
    QwenImageConfig(
        model_name="qwen-image-2.0",
        display_name="Qwen Image 2.0",
        description="通义千问图像生成模型，支持文生图和图生图编辑",
    ),
    QwenImageConfig(
        model_name="z-image-turbo",
        display_name="Z-Image Turbo",
        description="快速文生图模型，仅支持文本输入，使用 aspect_ratio 尺寸参数",
    ),
]

# ── Z-Image Turbo aspect_ratio → size 映射表 ──────────────────────────
# 三档分辨率：1K, 1.5K, 2K（命名取 max dimension 概值）
Z_IMAGE_SIZE_TABLE: Dict[str, Dict[str, str]] = {
    # ── 1K 档 ──────────────────────────────────────────────────
    '1K': {
        '1:1':  '1024*1024',
        '2:3':  '832*1248',
        '3:2':  '1248*832',
        '3:4':  '864*1152',
        '4:3':  '1152*864',
        '7:9':  '896*1152',
        '9:7':  '1152*896',
        '9:16': '720*1280',
        '9:21': '576*1344',
        '16:9': '1280*720',
        '21:9': '1344*576',
    },
    # ── 1.5K 档 ───────────────────────────────────────────────
    '1.5K': {
        '1:1':  '1280*1280',
        '2:3':  '1024*1536',
        '3:2':  '1536*1024',
        '3:4':  '1104*1472',
        '4:3':  '1472*1104',
        '7:9':  '1120*1440',
        '9:7':  '1440*1120',
        '9:16': '864*1536',
        '9:21': '720*1680',
        '16:9': '1536*864',
        '21:9': '1680*720',
    },
    # ── 2K 档 ──────────────────────────────────────────────────
    '2K': {
        '1:1':  '1536*1536',
        '2:3':  '1248*1872',
        '3:2':  '1872*1248',
        '3:4':  '1296*1728',
        '4:3':  '1728*1296',
        '7:9':  '1344*1728',
        '9:7':  '1728*1344',
        '9:16': '1152*2048',
        '9:21': '864*2016',
        '16:9': '2048*1152',
        '21:9': '2016*864',
    },
}

# Dashscope 多模态生成 API 端点
QWEN_IMAGE_API_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
    "multimodal-generation/generation"
)


# =============================================================================
# 图像生成模型检测
# =============================================================================

def is_qwen_image_model(model: str) -> bool:
    """
    Check if the model is a Bailian image generation model.

    Matches model names containing 'qwen-image', 'qwen_image' (case-insensitive),
    or exactly 'z-image-turbo' (Z-Image Turbo model).

    Args:
        model: Model name

    Returns:
        True if the model supports Bailian image generation
    """
    model_lower = model.lower()
    return any(kw in model_lower for kw in ('qwen-image', 'qwen_image')) or model_lower == 'z-image-turbo'


def is_z_image_model(model: str) -> bool:
    """Check if the model is a Z-Image Turbo model."""
    return model.lower() == 'z-image-turbo'


def _resolve_z_image_size(metadata: dict) -> Optional[str]:
    """
    Resolve the Dashscope size parameter for z-image-turbo from request metadata.

    Z-Image Turbo uses aspect_ratio + resolution tier to determine the exact
    pixel size. The resolution tiers are: 1K, 1.5K, 2K.

    Resolution logic:
    1. If 'size' is an exact pixel value (e.g. "1536*1536") → use directly
    2. If 'size' is a tier label (e.g. "2K") + 'aspect_ratio' → look up table
    3. If 'size' is a tier label without aspect_ratio → use 1:1 at that tier
    4. If only 'aspect_ratio' is set → use 1K at that ratio
    5. Default → "1024*1024" (1K, 1:1)

    Args:
        metadata: Request metadata dict

    Returns:
        Dashscope-format size string (WxH with * separator), or None if
        no z-image size resolution applies
    """
    size = str(metadata.get('size', '') or '').strip()
    # 'resolution' is an alias for tier label (e.g. "1K", "1.5K", "2K")
    resolution = str(metadata.get('resolution', '') or '').strip()
    if resolution and not size:
        size = resolution
    aspect_ratio = str(metadata.get('aspect_ratio', '') or '').strip()

    # 1. If size is already an exact pixel value → normalize format
    if size and ('*' in size or 'x' in size.lower()):
        return size.replace('x', '*').replace('X', '*')

    # 2. size is a tier label + aspect_ratio → look up
    if size and aspect_ratio:
        tier = size.upper()
        # Normalize tier naming
        if tier == '1.5K' or tier == '1K+':
            tier = '1.5K'
        table = Z_IMAGE_SIZE_TABLE.get(tier)
        if table and aspect_ratio in table:
            return table[aspect_ratio]
        # Fallback: try 1K, 1.5K, 2K in order
        for t in ('1K', '1.5K', '2K'):
            t_table = Z_IMAGE_SIZE_TABLE.get(t)
            if t_table and aspect_ratio in t_table:
                return t_table[aspect_ratio]

    # 3. size is a tier label only → default to 1:1 at that tier
    if size:
        tier = size.upper()
        if tier == '1.5K' or tier == '1K+':
            tier = '1.5K'
        table = Z_IMAGE_SIZE_TABLE.get(tier)
        if table and '1:1' in table:
            return table['1:1']

    # 4. aspect_ratio only → default 1K at that ratio
    if aspect_ratio:
        table = Z_IMAGE_SIZE_TABLE.get('1K', {})
        if aspect_ratio in table:
            return table[aspect_ratio]

    # 5. Default → 1K 1:1
    return '1024*1024'


def has_image_generation_tool(request: ChatRequest) -> bool:
    """Check if the request contains an ``image_generation`` tool."""
    from app.abstraction.tools import has_image_generation_tool as _check
    return _check(request.tools)


# =============================================================================
# 消息转换 - ChatRequest → Dashscope 格式
# =============================================================================

def _convert_messages_to_dashscope(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Convert ChatRequest messages to Dashscope multimodal generation format.

    Each message content block is converted:
    - TEXT          → {"text": "..."}
    - IMAGE_URL     → {"image": "https://..."}
    - IMAGE_BASE64  → {"image": "data:<mime>;base64,<data>"}

    System messages are skipped (handled separately via BailianProvider).

    Args:
        messages: List of Message objects

    Returns:
        Dashscope format messages list
    """
    dashscope_messages = []

    for msg in messages:
        if msg.role.is_system_like():
            continue  # System messages are handled separately

        content_list: List[Dict[str, Any]] = []

        if isinstance(msg.content, str):
            if msg.content.strip():
                content_list.append({"text": msg.content})
        elif isinstance(msg.content, list):
            for block in msg.content:
                if not isinstance(block, ContentBlock):
                    continue
                if block.type == ContentType.TEXT:
                    text = block.text or ""
                    if text:
                        content_list.append({"text": text})
                elif block.type == ContentType.IMAGE_URL:
                    if block.url:
                        content_list.append({"image": block.url})
                elif block.type == ContentType.IMAGE_BASE64:
                    if block.data:
                        mime = block.media_type or "image/jpeg"
                        data_uri = f"data:{mime};base64,{block.data}"
                        content_list.append({"image": data_uri})

        if content_list:
            dashscope_messages.append({
                "role": msg.role.value if hasattr(msg.role, 'value') else str(msg.role),
                "content": content_list,
            })

    return dashscope_messages


# =============================================================================
# API 调用与响应解析
# =============================================================================

def _download_image_as_b64(url: str, fallback_mime: str = "image/png") -> Optional[str]:
    """Download an image URL and return it as a base64 data URI.

    Returns ``None`` if the download fails, so the caller can fall back
    to the raw URL.
    """
    try:
        with urlopen(url, timeout=30) as resp:  # noqa: S310 – URL is provider-generated
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()
            mime = content_type.split(";")[0].strip() or fallback_mime
            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{b64}"
    except Exception as exc:
        logging.getLogger("model_link.bailian").warning(
            "Failed to convert image URL to base64: %s – %s", url, exc
        )
        return None


def execute_qwen_image_generation(
    api_key: str,
    model: str,
    messages: List[Message],
    metadata: dict,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute Qwen image generation/editing via the Dashscope API.

    Builds the Dashscope multimodal generation request from the ChatRequest
    messages and metadata, calls the API, and returns the result as a
    ChatResponse with image_generation_call items stored in the message content
    (JSON-encoded list, compatible with the Responses API adapter format).

    Args:
        api_key: Dashscope API key
        model: Model name (e.g. "qwen-image-2.0-pro")
        messages: List of Message objects
        metadata: Request metadata (carries image generation parameters)

    Returns:
        ChatResponse with image_generation_call items in the message content

    Raises:
        RuntimeError: On API error
    """
    import httpx
    import sys

    # Convert messages to Dashscope format
    dashscope_messages = _convert_messages_to_dashscope(messages)

    # Build parameters from metadata
    parameters: Dict[str, Any] = {}

    # Z-Image Turbo uses aspect_ratio + tier to resolve exact pixel size
    if is_z_image_model(model):
        resolved_size = _resolve_z_image_size(metadata)
        if resolved_size:
            parameters['size'] = resolved_size
    else:
        size = metadata.get('size')
        if size:
            # Accept "1024x1024" and "1024*1024" formats; Dashscope uses "*"
            parameters['size'] = str(size).replace('x', '*')

    n = metadata.get('number') or metadata.get('n')
    if n is not None:
        parameters['n'] = int(n)
    else:
        parameters['n'] = 1

    watermark = metadata.get('watermark')
    if watermark is not None:
        parameters['watermark'] = bool(watermark)
    else:
        parameters['watermark'] = False

    seed = metadata.get('seed')
    if seed is not None:
        parameters['seed'] = seed

    # Build request body
    request_body: Dict[str, Any] = {
        "model": model,
        "input": {
            "messages": dashscope_messages,
        },
        "parameters": parameters,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="bailian", input_data=request_body)
        if _child_span:
            _child_span.log_input(request_body)
    _trace_error: Optional[Exception] = None

    try:
        with httpx.Client(timeout=300) as client:
            response = client.post(
                QWEN_IMAGE_API_URL,
                json=request_body,
                headers=headers,
            )
            response_data = response.json()

        if _child_span:
            _output = dict(response_data)
            _x_req_id = response.headers.get("x-request-id", "")
            if _x_req_id:
                _output["x-request-id"] = _x_req_id
            _child_span.log_output(_output)

        # Dashscope signals errors via top-level 'code' field (not HTTP status code alone)
        if 'code' in response_data and response_data['code'] not in ('Success', ''):
            code = response_data.get('code', '')
            message = response_data.get('message', 'Unknown error')
            raise RuntimeError(
                f"Qwen Image API error (code={code}): {message}"
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Qwen Image API error ({response.status_code}): "
                f"{json.dumps(response_data, ensure_ascii=False)}"
            )

        return _parse_qwen_image_response(response_data, model, metadata)

    except RuntimeError:
        _trace_error = sys.exc_info()[1]
        raise
    except Exception as e:
        _trace_error = e
        raise RuntimeError(f"Qwen Image API error: {str(e)}")
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)


def _resolution_tier(width: int, height: int) -> str:
    """
    Derive a resolution tier label from pixel dimensions.

    Tier labels follow the convention used across image generation providers
    (TencentVOD, Gemini, etc.):

        max dimension ≤  640  →  "512"
        max dimension ≤ 1536  →  "1K"
        max dimension ≤ 3072  →  "2K"
        otherwise             →  "4K"

    Args:
        width:  Image width in pixels
        height: Image height in pixels

    Returns:
        Resolution tier label, e.g. "1K", "2K", "4K"
    """
    max_dim = max(width, height)
    if max_dim <= 640:
        return "512"
    elif max_dim <= 1536:
        return "1K"
    elif max_dim <= 3072:
        return "2K"
    else:
        return "4K"


def _parse_qwen_image_response(data: Dict[str, Any], model: str, metadata: Optional[dict] = None) -> ChatResponse:
    """
    Parse Dashscope multimodal generation response into ChatResponse.

    Extracts image URLs from the response and packs them as
    image_generation_call items (JSON-encoded) in the message content,
    compatible with the Volcengine / Gemini provider format.

    Args:
        data: Dashscope API response data
        model: Model name
        metadata: Request metadata (carries response_format for b64_json signal)

    Returns:
        ChatResponse with image_generation_call items
    """
    output = data.get("output", {})
    choices = output.get("choices", [])

    image_call_items: List[Dict[str, Any]] = []
    for choice in choices:
        msg = choice.get("message", {})
        for item in msg.get("content", []):
            if "image" in item:
                image_call_items.append({
                    "type": "image_generation_call",
                    "status": "completed",
                    "result": item["image"],
                })

    usage_data = data.get("usage", {})
    image_count = usage_data.get("image_count", max(len(image_call_items), 1))
    # Extract resolution tier from usage data (e.g. "1K", "2K", "4K")
    img_width = usage_data.get("width", 0)
    img_height = usage_data.get("height", 0)
    img_resolution = _resolution_tier(img_width, img_height) if img_width and img_height else None

    # Derive aspect ratio from width/height (e.g. "1:1", "16:9")
    img_aspect = None
    if img_width and img_height:
        from math import gcd
        g = gcd(img_width, img_height)
        img_aspect = f"{img_width // g}:{img_height // g}"

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
                'output_image_resolution': img_resolution,
                'output_image_aspect': img_aspect,
                '_response_format': (metadata or {}).get('response_format', 'url'),
            },
        ),
        created=int(time.time()),
        provider="bailian",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

def stream_image_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    Execute Qwen image generation and yield the result as StreamChunks.

    Qwen image generation is synchronous (no true streaming); this function
    calls the non-streaming API, collects all images, then emits them as
    image_generation_call SSE events via raw_sse_passthrough.

    SSE event sequence (matching the Volcengine / Gemini pattern):
    1. Role marker chunk (delta_role="assistant") → triggers format_stream_start
    2. response.output_item.added  (image_generation_call, status=generating)
    3. response.output_item.done   (image_generation_call, status=completed)
    4. response.completed          (emitted by finish chunk)

    Args:
        chat_fn: The non-streaming chat function (provider.chat)
        request: The chat request with image generation parameters
    """
    # Call the non-streaming API to get the full image result
    response = chat_fn(request)
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

    # b64_json conversion for streaming: convert image URLs to base64
    # data URIs before constructing SSE events. This mirrors what
    # _apply_b64_json_to_image_output() does for the non-streaming sync
    # and async GET paths in gateway_responses.py.
    convert_to_b64 = response.usage.extra.get('_response_format') == 'b64_json'
    if convert_to_b64:
        for img in images:
            url = img.get("result", "")
            if url and not url.startswith("data:"):
                b64_data_uri = _download_image_as_b64(url)
                if b64_data_uri:
                    img["result"] = b64_data_uri

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
