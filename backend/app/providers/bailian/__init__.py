"""
阿里云百炼供应商模块 (Bailian Provider Module)

包含以下子模块：
- base: 百炼 API 基础实现（聊天、流式、嵌入）
- image_generation: 通义千问图像生成/编辑实现（qwen-image-2.0-pro）

图像生成说明：
通义千问 qwen-image-2.0-pro 模型通过 Dashscope 多模态生成 API 提供图像生成
和编辑能力，兼容 /v1/responses 的 image_generation 工具格式。
"""

from .base import BailianProvider
from .image_generation import (
    QwenImageConfig,
    QWEN_IMAGE_MODELS,
    is_qwen_image_model,
    has_image_generation_tool,
    execute_qwen_image_generation,
    stream_image_generation,
)

__all__ = [
    # Main provider
    'BailianProvider',
    # Image generation config
    'QwenImageConfig',
    'QWEN_IMAGE_MODELS',
    # Image generation utilities
    'is_qwen_image_model',
    'has_image_generation_tool',
    'execute_qwen_image_generation',
    'stream_image_generation',
]
