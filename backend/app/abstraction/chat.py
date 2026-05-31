"""
对话抽象模块 (Chat Abstraction)
提供统一的对话请求和响应格式。
"""
from enum import Enum
from typing import Optional, List, Dict, Any, Union
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
class PriceInfo:
    """Price information for a usage response."""
    payable_amount: float = 0.0
    discount: float = 1.0
    actual_amount: float = 0.0
    currency: str = 'USD'
    exchange_rate: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payable_amount": self.payable_amount,
            "discount": self.discount,
            "actual_amount": self.actual_amount,
            "currency": self.currency,
            "exchange_rate": self.exchange_rate,
        }


@dataclass
class UsageInfo:
    """使用量信息"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Detailed token breakdown
    reasoning_tokens: int = 0          # output tokens used for reasoning
    cached_tokens: int = 0             # cached prompt tokens (OpenAI / Azure)
    # Price information
    price: Optional['PriceInfo'] = None
    # Arbitrary extra key-value pairs for provider-specific data
    # (e.g. "_azure_completed_response", "cache_creation", …)
    extra: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-compatible .get() for backward compatibility."""
        # Check known dataclass fields first, then fall back to extra dict
        _FIELDS = {
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "cached_tokens",
        }
        if key in _FIELDS:
            return getattr(self, key, default)
        return self.extra.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Dict-compatible [] access for backward compatibility."""
        result = self.get(key)
        if result is None and key not in self:
            raise KeyError(key)
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a plain dict (excludes empty extra keys prefixed with '_')."""
        d: Dict[str, Any] = {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.cache_read_tokens:
            d["cache_read_tokens"] = self.cache_read_tokens
        if self.cache_write_tokens:
            d["cache_write_tokens"] = self.cache_write_tokens
        if self.reasoning_tokens:
            d["reasoning_tokens"] = self.reasoning_tokens
        if self.cached_tokens:
            d["cached_tokens"] = self.cached_tokens
        if self.price is not None:
            d["price"] = self.price.to_dict()
        d.update(self.extra)
        return d

    def items(self):
        """Dict-compatible .items() — iterates over to_dict()."""
        return self.to_dict().items()

    def __contains__(self, key: str) -> bool:
        """Support `key in usage` syntax."""
        _FIELDS = {
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "cached_tokens",
        }
        return key in _FIELDS or key in self.extra


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
    system: Optional[Union[str, List[Dict[str, Any]]]] = None  # 系统指令：文本或内容块数组
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
    session_id: Optional[str] = None  # 会话 ID，用于 tracer 追踪整个会话
    reasoning_effort: Optional[str] = None  # 推理力度: "none"(默认), "minimal", "low", "medium", "high", "xhigh"
    parallel_tool_calls: Optional[bool] = None  # 是否允许并行工具调用
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外参数
    
    def get_system_message(self) -> Optional[str]:
        """获取系统消息文本（从 system 字段提取）"""
        if self.system is None:
            return None
        if isinstance(self.system, str):
            return self.system
        texts = [b.get("text", "") for b in self.system if b.get("type") == "text"]
        return "\n".join(texts) if texts else None

    def get_conversation_messages(self) -> List[Message]:
        """获取对话消息（排除系统消息，安全兜底）"""
        return [msg for msg in self.messages if not msg.role.is_system_like()]


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