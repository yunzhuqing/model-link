"""
阿里云百炼图像生成模块 (Qwen Image Generation)

通义千问图像生成/编辑模型支持通过 Dashscope 多模态生成 API 进行图像生成和编辑。

支持的模型包括：
- qwen-image-2.0-pro: 通义千问图像生成与编辑模型（支持文生图和图生图）

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

from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id


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
]

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
    Check if the model is a Qwen image generation/editing model.

    Matches model names containing 'qwen-image' or 'qwen_image' (case-insensitive).

    Args:
        model: Model name

    Returns:
        True if the model supports Qwen image generation
    """
    model_lower = model.lower()
    return any(kw in model_lower for kw in ('qwen-image', 'qwen_image'))


def has_image_generation_tool(request: ChatRequest) -> bool:
    """
    Check if the request contains an ``image_generation`` tool.

    When the Responses API adapter parses an ``image_generation`` tool entry,
    it stores the parameters in ``request.metadata``.  The presence of
    image-generation metadata keys (set by the adapter) is the reliable signal.

    Args:
        request: The chat request to check

    Returns:
        True if the request was sent with an ``image_generation`` tool.
    """
    meta = request.metadata
    return any(k in meta for k in (
        'size', 'number', 'image_format', 'response_format',
        'seed', 'watermark',
    ))


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

def execute_qwen_image_generation(
    api_key: str,
    model: str,
    messages: List[Message],
    metadata: dict,
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

    # Debug logging
    print("\n" + "=" * 50, file=sys.stderr)
    print("[Qwen Image Request Body]", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print(json.dumps(request_body, ensure_ascii=False, indent=2), file=sys.stderr)
    print("=" * 50 + "\n", file=sys.stderr)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        with httpx.Client(timeout=300) as client:
            response = client.post(
                QWEN_IMAGE_API_URL,
                json=request_body,
                headers=headers,
            )
            response_data = response.json()

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

        return _parse_qwen_image_response(response_data, model)

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Qwen Image API error: {str(e)}")


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


def _parse_qwen_image_response(data: Dict[str, Any], model: str) -> ChatResponse:
    """
    Parse Dashscope multimodal generation response into ChatResponse.

    Extracts image URLs from the response and packs them as
    image_generation_call items (JSON-encoded) in the message content,
    compatible with the Volcengine / Gemini provider format.

    Args:
        data: Dashscope API response data
        model: Model name

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
            images = json.loads(raw) if isinstance(raw, str) else []
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
