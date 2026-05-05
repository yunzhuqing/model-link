"""
Gemini 原生图像生成模块 (Gemini Native Image Generation)

Gemini 模型支持原生图像生成，通过在 generationConfig 中设置
responseModalities: ["TEXT", "IMAGE"] 来启用。

支持的模型包括：
- gemini-2.0-flash-preview-image-generation
- 任何包含 'image-generation'、'imagen' 或 'native-image' 的模型名

API 文档: https://ai.google.dev/gemini-api/docs/image-generation

图像生成响应格式：
Gemini 返回的图像数据以 inlineData 形式嵌入在 response parts 中：
{
    "candidates": [{
        "content": {
            "parts": [
                {"text": "描述文字"},
                {"inlineData": {"mimeType": "image/png", "data": "<base64>"}}
            ]
        }
    }]
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
class GeminiImageConfig:
    """Gemini 图像生成模型配置"""
    model_name: str       # 模型名称
    display_name: str     # 显示名称
    description: str      # 模型描述


# Gemini 图像生成模型列表
GEMINI_IMAGE_MODELS: List[GeminiImageConfig] = [
    GeminiImageConfig(
        model_name="gemini-2.0-flash-preview-image-generation",
        display_name="Gemini 2.0 Flash Image Generation",
        description="Gemini 2.0 Flash with native image generation support",
    ),
]


# =============================================================================
# 图像生成模型检测
# =============================================================================

def is_gemini_image_model(model: str) -> bool:
    """
    Check if the model supports native image generation.

    Gemini models with native image generation include:
    - gemini-2.0-flash-preview-image-generation
    - Any model name containing 'image-generation', 'imagen', or 'native-image'
    - Any model name containing 'image' keyword

    The ``image_generation`` tool in the Responses API request also triggers
    image generation mode for compatible models.

    Args:
        model: Model name

    Returns:
        True if the model supports native image generation
    """
    model_lower = model.lower()
    return any(kw in model_lower for kw in (
        "image",
        "image-generation",
        "imagen",
        "native-image",
    ))


def has_image_generation_tool(request: ChatRequest) -> bool:
    """
    Check if the request contains an ``image_generation`` tool.

    When the Responses API adapter parses an ``image_generation`` tool entry,
    it stores the parameters in ``request.metadata`` and does NOT create a
    ``ToolDefinition`` (the tool type is not ``function``).  The presence of
    image-generation metadata keys (set by the adapter) is the reliable signal.

    Args:
        request: The chat request to check

    Returns:
        True if the request was sent with an ``image_generation`` tool.
    """
    meta = request.metadata
    return any(k in meta for k in (
        'size', 'number', 'image_format', 'response_format',
        'seed', 'watermark', 'reference_images',
    ))


# =============================================================================
# 图像生成响应解析
# =============================================================================

def parse_inline_images(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Parse Gemini response parts and extract inline image data.

    Gemini native image generation returns images as inlineData parts
    with base64-encoded data.

    Args:
        parts: List of Gemini response parts

    Returns:
        List of image_generation_call items, each containing:
        - type: "image_generation_call"
        - status: "completed"
        - result: data URI (data:<mime>;base64,<data>)
    """
    inline_images: List[Dict[str, Any]] = []
    for part in parts:
        # Skip thinking/reasoning images — only include final result images
        if part.get("thought", False):
            continue
        if "inlineData" in part:
            inline_data = part["inlineData"]
            mime_type = inline_data.get("mimeType", "image/png")
            b64_data = inline_data.get("data", "")
            if b64_data:
                data_uri = f"data:{mime_type};base64,{b64_data}"
                inline_images.append({
                    "type": "image_generation_call",
                    "status": "completed",
                    "result": data_uri,
                })
    return inline_images


def build_image_chat_response(
    inline_images: List[Dict[str, Any]],
    message_blocks: List[ContentBlock],
    model: str,
    usage: UsageInfo,
    finish_reason: FinishReason,
    provider_type: str,
    response_format: str = "b64_json",
) -> ChatResponse:
    """
    Build a ChatResponse for image generation results.

    Stores image_generation_call items as JSON in the message content,
    compatible with the Responses API adapter format used by Volcengine.

    Args:
        inline_images: List of image_generation_call items
        message_blocks: Any text content blocks from the response
        model: Model name
        usage: Token usage info
        finish_reason: Finish reason from the response
        provider_type: Provider type string
        response_format: The requested response format ("url" or "b64_json")

    Returns:
        ChatResponse with image generation results
    """
    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(inline_images, ensure_ascii=False)
    )

    # Propagate the requested response_format so the Responses API adapter
    # can decide between url / b64_json output.
    if not usage.extra:
        usage.extra = {}
    usage.extra['output_image_number'] = len(inline_images)
    usage.extra['_response_format'] = response_format

    return ChatResponse(
        id=gen_id("img"),
        model=model,
        choices=[ChatChoice(
            index=0,
            message=message,
            finish_reason=finish_reason,
        )],
        usage=usage,
        created=int(time.time()),
        provider=provider_type,
    )


def stream_image_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    Execute image generation and yield the result as StreamChunks.

    Gemini's native image generation doesn't truly stream images; it returns
    the full image in one response. This function calls the non-streaming API,
    collects all images, then emits them as image_generation_call SSE events
    via raw_sse_passthrough.

    SSE event sequence (matching the Volcengine pattern):
    1. response.created / response.in_progress   (emitted by format_stream_start)
    2. response.output_item.added  (image_generation_call, status=generating)
    3. response.output_item.done   (image_generation_call, status=completed)
    4. response.completed          (emitted by finish chunk)

    Args:
        chat_fn: The non-streaming chat function to call (provider.chat)
        request: The chat request with image generation parameters
    """
    # Use the non-streaming API to get the full image result
    response = chat_fn(request)
    response_id = response.id
    model = response.model

    # Parse the images list from the response content
    images: List[Dict[str, Any]] = []
    if response.choices and response.choices[0].message:
        msg = response.choices[0].message
        raw = msg.content if isinstance(msg.content, str) else (msg.get_text_content() or "[]")
        try:
            images = json.loads(raw) if isinstance(raw, str) else []
        except (json.JSONDecodeError, TypeError):
            images = []

    # Emit role marker so create_stream_response captures the real response ID
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

        # response.output_item.added (generating)
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
        # response.output_item.done (completed with result)
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
