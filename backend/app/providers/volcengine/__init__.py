"""
火山引擎供应商模块 (Volcengine Provider Module)

包含以下子模块：
- base: 火山引擎 Responses API 基础实现
- image_generation: 豆包图像生成工具实现
"""

from .base import VolcengineProvider
from .image_generation import (
    DoubaoImageProvider,
    DoubaoImageModel,
    get_doubao_image_model,
    list_doubao_image_models,
    create_image_generation_tool,
    get_image_generation_tools,
    get_image_generation_tool_definition,
    is_doubao_image_model,
    get_tool_name_for_model,
)

__all__ = [
    'VolcengineProvider',
    'DoubaoImageProvider',
    'DoubaoImageModel',
    'get_doubao_image_model',
    'list_doubao_image_models',
    'create_image_generation_tool',
    'get_image_generation_tools',
    'get_image_generation_tool_definition',
    'is_doubao_image_model',
    'get_tool_name_for_model',
]
