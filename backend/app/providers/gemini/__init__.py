"""
Google Gemini 供应商模块 (Gemini Provider Module)

包含以下子模块：
- base: Gemini API 基础实现（聊天、流式、嵌入）
- image_generation: Gemini 原生图像生成实现
- video_generation: Gemini Veo 视频生成实现
"""

from .base import GeminiProvider
from .image_generation import (
    GeminiImageConfig,
    GEMINI_IMAGE_MODELS,
    is_gemini_image_model,
    has_image_generation_tool,
    stream_image_generation,
    parse_inline_images,
    build_image_chat_response,
)
from .video_generation import (
    is_veo_video_model,
    execute_veo_video_generation,
    stream_veo_video_generation,
)

__all__ = [
    # Main provider
    'GeminiProvider',
    # Image generation config
    'GeminiImageConfig',
    'GEMINI_IMAGE_MODELS',
    # Image generation utilities
    'is_gemini_image_model',
    'has_image_generation_tool',
    'stream_image_generation',
    'parse_inline_images',
    'build_image_chat_response',
    # Video generation utilities
    'is_veo_video_model',
    'execute_veo_video_generation',
    'stream_veo_video_generation',
]
