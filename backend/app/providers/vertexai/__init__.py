"""
Google Vertex AI 供应商模块 (VertexAI Provider Module)

包含以下子模块：
- base: Vertex AI 基础实现（支持多种模型发布者）

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

__all__ = [
    'VertexAIProvider',
    'VertexAIClaudeProvider',
    'ModelPublisher',
    'MODEL_PUBLISHER_MAP',
    'detect_publisher',
    '_thought_signature_cache',
    '_log_to_file',
]
