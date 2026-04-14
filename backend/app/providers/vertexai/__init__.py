"""
Google Vertex AI 供应商模块 (VertexAI Provider Module)

包含以下子模块：
- base: Vertex AI 基础实现（支持多种模型发布者）
- image_generation: Vertex AI 图像生成实现（基于 Gemini 原生图像生成）
- video_generation: Vertex AI Veo 视频生成实现

支持的模型发布者：
- Anthropic Claude 系列（使用 Anthropic Messages API 格式）
- Google Gemini 系列（使用 Google generateContent API 格式）
- DeepSeek 系列（使用 OpenAI 兼容格式）
- Meta Llama 系列（使用 OpenAI 兼容格式）
- Mistral 系列（使用 OpenAI 兼容格式）
- Zhipu GLM 系列（使用 OpenAI 兼容格式）

所有模型通过 Google Cloud OAuth2 认证访问。
"""

from .base import (
    VertexAIProvider,
    VertexAIClaudeProvider,
    ModelPublisher,
    MODEL_PUBLISHER_MAP,
    detect_publisher,
    _thought_signature_cache,
    _log_to_file,
)
from .image_generation import (
    is_vertexai_image_model,
    has_vertexai_image_generation_tool,
    inject_image_generation_config,
    handle_image_generation_response,
    stream_vertexai_image_generation,
)
from .video_generation import (
    is_vertexai_video_model,
    has_vertexai_video_generation_tool,
    execute_vertexai_veo_generation,
    stream_vertexai_veo_generation,
)

__all__ = [
    # Main provider
    'VertexAIProvider',
    'VertexAIClaudeProvider',
    'ModelPublisher',
    'MODEL_PUBLISHER_MAP',
    'detect_publisher',
    '_thought_signature_cache',
    '_log_to_file',
    # Image generation
    'is_vertexai_image_model',
    'has_vertexai_image_generation_tool',
    'inject_image_generation_config',
    'handle_image_generation_response',
    'stream_vertexai_image_generation',
    # Video generation
    'is_vertexai_video_model',
    'has_vertexai_video_generation_tool',
    'execute_vertexai_veo_generation',
    'stream_vertexai_veo_generation',
]
