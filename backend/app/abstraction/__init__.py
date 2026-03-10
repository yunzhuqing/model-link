"""
中间抽象层 (Abstraction Layer)
提供消息、工具、对话和流式响应的统一抽象接口。
"""

from .messages import Message, MessageRole, ContentBlock, ContentType
from .tools import Tool, ToolCall, ToolResult, ToolDefinition
from .chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo
from .streaming import StreamChunk, StreamManager

__all__ = [
    'Message', 'MessageRole', 'ContentBlock', 'ContentType',
    'Tool', 'ToolCall', 'ToolResult', 'ToolDefinition',
    'ChatRequest', 'ChatResponse', 'ChatChoice', 'UsageInfo',
    'StreamChunk', 'StreamManager'
]