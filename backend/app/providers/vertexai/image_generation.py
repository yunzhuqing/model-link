"""
Vertex AI 图像生成模块 (Vertex AI Image Generation)

通过 Vertex AI 的 Gemini 模型进行原生图像生成。
复用 Gemini 图像生成模块的核心逻辑，适配 Vertex AI 认证和端点。

支持的模型:
- gemini-2.0-flash-preview-image-generation
- 任何包含 'image-generation'、'imagen' 或 'native-image' 的模型名

API 文档: https://cloud.google.com/vertex-ai/generative-ai/docs/image/generate-images
"""
from typing import Optional, Dict, Any, List, Generator

from app.abstraction.chat import ChatRequest, ChatResponse, UsageInfo, FinishReason
from app.abstraction.messages import ContentBlock
from app.abstraction.streaming import StreamChunk
from app.providers.gemini.image_generation import (
    is_gemini_image_model,
    has_image_generation_tool,
    parse_inline_images,
    build_image_chat_response,
    stream_image_generation,
)


# =============================================================================
# 模型检测
# =============================================================================

def is_vertexai_image_model(model: str) -> bool:
    """
    Check if the model is a Gemini image generation model on Vertex AI.

    Delegates to the shared Gemini image model detection logic.

    Args:
        model: Model name

    Returns:
        True if the model supports native image generation
    """
    return is_gemini_image_model(model)


def has_vertexai_image_generation_tool(request: ChatRequest) -> bool:
    """
    Check if the request contains an image_generation tool.

    Delegates to the shared Gemini image generation tool detection.

    Args:
        request: The chat request to check

    Returns:
        True if the request was sent with an image_generation tool.
    """
    return has_image_generation_tool(request)


# =============================================================================
# 请求配置注入
# =============================================================================

def inject_image_generation_config(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inject responseModalities for image generation into Gemini request data.

    Sets responseModalities to ["TEXT", "IMAGE"] in the generationConfig
    so that the Gemini model returns inline image data.

    Args:
        request_data: The prepared Gemini request body

    Returns:
        Modified request_data with responseModalities set
    """
    gen_config = request_data.setdefault("generationConfig", {})
    gen_config["responseModalities"] = ["TEXT", "IMAGE"]
    return request_data


# =============================================================================
# 响应处理
# =============================================================================

def handle_image_generation_response(
    response_data: Dict[str, Any],
    model: str,
    provider_type: str,
    response_format: str = "b64_json",
) -> Optional[ChatResponse]:
    """
    Handle Gemini image generation response on Vertex AI.

    Parses inline images from the Gemini API response and builds a
    ChatResponse compatible with the Responses API adapter format.

    Args:
        response_data: Raw Gemini API response data
        model: Model name
        provider_type: Provider type string (e.g., "vertexai")

    Returns:
        ChatResponse with image generation results if inline images found,
        None otherwise (caller should fall through to normal response parsing)
    """
    candidates = response_data.get("candidates", [])
    inline_images: List[Dict[str, Any]] = []
    message_blocks: List[ContentBlock] = []
    finish_reason = FinishReason.STOP

    if candidates:
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        inline_images = parse_inline_images(parts)
        for part in parts:
            if "text" in part and not part.get("thought", False):
                message_blocks.append(ContentBlock.from_text(part["text"]))
        gemini_finish = candidate.get("finishReason", "STOP")
        finish_map = {
            "STOP": FinishReason.STOP,
            "MAX_TOKENS": FinishReason.LENGTH,
            "SAFETY": FinishReason.CONTENT_FILTER,
        }
        finish_reason = finish_map.get(gemini_finish, FinishReason.STOP)

    usage_metadata = response_data.get("usageMetadata", {})
    image_count = len(inline_images) if inline_images else 0
    usage = UsageInfo(
        prompt_tokens=usage_metadata.get("promptTokenCount", 0),
        completion_tokens=usage_metadata.get("candidatesTokenCount", 0),
        total_tokens=usage_metadata.get("totalTokenCount", 0),
        extra={
            'output_image_number': image_count,
        } if image_count > 0 else {},
    )

    if inline_images:
        return build_image_chat_response(
            inline_images, message_blocks, model,
            usage, finish_reason, provider_type,
            response_format=response_format,
        )
    return None


# =============================================================================
# 流式图像生成
# =============================================================================

def stream_vertexai_image_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    Stream image generation results on Vertex AI.

    Gemini's native image generation doesn't truly stream images.
    This delegates to the shared Gemini stream_image_generation function
    which calls the non-streaming API and emits results as SSE events.

    Args:
        chat_fn: The non-streaming chat function to call (provider.chat)
        request: The chat request with image generation parameters
    """
    yield from stream_image_generation(chat_fn, request)
