"""
API 适配器层 (Adapter Layer)
负责在不同 API 格式和统一内部格式之间进行转换。

支持的 API 格式：
  - OpenAI Chat Completions (/v1/chat/completions)
  - Anthropic Messages (/v1/messages)
  - OpenAI Responses (/v1/responses)

每个适配器实现：
  - parse_request: 将外部 API 格式转换为统一的 ChatRequest
  - format_response: 将统一的 ChatResponse 转换为外部 API 格式
  - create_stream_response: 创建流式 HTTP 响应
"""

from .base import BaseAdapter
from .openai_adapter import OpenAIChatAdapter
from .anthropic_adapter import AnthropicMessagesAdapter
from .responses_adapter import OpenAIResponsesAdapter

__all__ = [
    'BaseAdapter',
    'OpenAIChatAdapter',
    'AnthropicMessagesAdapter',
    'OpenAIResponsesAdapter',
]
