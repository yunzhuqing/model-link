"""
对话抽象模块 (Chat Abstraction)
提供统一的对话请求和响应格式。
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import time
import uuid

from .messages import Message, MessageRole
from .tools import ToolDefinition, ToolCall


class FinishReason(Enum):
    """完成原因枚举"""
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


@dataclass
class UsageInfo:
    """使用量信息"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ChatChoice:
    """对话选择项"""
    index: int = 0
    message: Optional[Message] = None
    finish_reason: FinishReason = FinishReason.STOP
    tool_calls: List[ToolCall] = field(default_factory=list)
    reasoning_content: Optional[str] = None  # 推理内容（如 DeepSeek R1）


@dataclass
class ChatRequest:
    """
    对话请求 - 统一的对话请求格式
    
    支持多种参数配置。
    """
    messages: List[Message]
    model: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False
    tools: List[ToolDefinition] = field(default_factory=list)
    tool_choice: Optional[str] = None  # "auto", "none", "required", or specific tool name
    stop: Optional[List[str]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    user: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外参数
    
    def get_system_message(self) -> Optional[str]:
        """获取系统消息"""
        for msg in self.messages:
            if msg.role == MessageRole.SYSTEM:
                return msg.get_text_content()
        return None
    
    def get_conversation_messages(self) -> List[Message]:
        """获取对话消息（排除系统消息）"""
        return [msg for msg in self.messages if msg.role != MessageRole.SYSTEM]


@dataclass
class ChatResponse:
    """
    对话响应 - 统一的对话响应格式
    """
    id: str
    model: str
    choices: List[ChatChoice]
    usage: UsageInfo
    created: int = field(default_factory=lambda: int(time.time()))
    provider: str = "unknown"  # 供应商名称
    
    @classmethod
    def create_simple_response(
        cls,
        model: str,
        content: str,
        provider: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0
    ) -> 'ChatResponse':
        """创建简单文本响应"""
        message = Message(
            role=MessageRole.ASSISTANT,
            content=content
        )
        choice = ChatChoice(
            index=0,
            message=message,
            finish_reason=FinishReason.STOP
        )
        usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens
        )
        
        return cls(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            model=model,
            choices=[choice],
            usage=usage,
            provider=provider
        )
    
    @classmethod
    def create_tool_call_response(
        cls,
        model: str,
        tool_calls: List[ToolCall],
        provider: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0
    ) -> 'ChatResponse':
        """创建工具调用响应"""
        message = Message(
            role=MessageRole.ASSISTANT,
            content=""  # 工具调用时内容可能为空
        )
        choice = ChatChoice(
            index=0,
            message=message,
            finish_reason=FinishReason.TOOL_CALLS,
            tool_calls=tool_calls
        )
        usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens
        )
        
        return cls(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            model=model,
            choices=[choice],
            usage=usage,
            provider=provider
        )