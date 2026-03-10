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
    
    def to_openai_format(self) -> Dict[str, int]:
        """转换为 OpenAI 格式"""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens
        }
    
    def to_anthropic_format(self) -> Dict[str, int]:
        """转换为 Anthropic 格式"""
        return {
            "input_tokens": self.prompt_tokens,
            "output_tokens": self.completion_tokens
        }
    
    def to_bailian_format(self) -> Dict[str, int]:
        """转换为百炼格式"""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens
        }


@dataclass
class ChatChoice:
    """对话选择项"""
    index: int = 0
    message: Optional[Message] = None
    finish_reason: FinishReason = FinishReason.STOP
    tool_calls: List[ToolCall] = field(default_factory=list)
    reasoning_content: Optional[str] = None  # 推理内容（如 DeepSeek R1）
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        result = {
            "index": self.index,
            "finish_reason": self.finish_reason.value
        }
        
        if self.message:
            msg_format = self.message.to_openai_format()
            result["message"] = {
                "role": msg_format.get("role", "assistant"),
                "content": msg_format.get("content")
            }
            
            if self.reasoning_content:
                result["message"]["reasoning_content"] = self.reasoning_content
            
            if self.tool_calls:
                result["message"]["tool_calls"] = [
                    tc.to_openai_format() for tc in self.tool_calls
                ]
        
        return result
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        content = []
        
        if self.message:
            text = self.message.get_text_content()
            if text:
                content.append({"type": "text", "text": text})
        
        if self.tool_calls:
            for tc in self.tool_calls:
                content.append(tc.to_anthropic_format())
        
        return {
            "index": self.index,
            "content": content,
            "finish_reason": self.finish_reason.value
        }
    
    def to_bailian_format(self) -> Dict[str, Any]:
        """转换为百炼格式"""
        result = {
            "index": self.index,
            "finish_reason": self.finish_reason.value
        }
        
        if self.message:
            msg_format = self.message.to_bailian_format()
            result["message"] = {
                "role": msg_format.get("role", "assistant"),
                "content": msg_format.get("content")
            }
            
            if self.reasoning_content:
                result["message"]["reasoning_content"] = self.reasoning_content
            
            if self.tool_calls:
                result["message"]["tool_calls"] = [
                    tc.to_bailian_format() for tc in self.tool_calls
                ]
        
        return result


@dataclass
class ChatRequest:
    """
    对话请求 - 统一的对话请求格式
    
    支持多种参数配置和格式转换。
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
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        result = {
            "model": self.model,
            "messages": [msg.to_openai_format() for msg in self.messages],
            "stream": self.stream
        }
        
        if self.temperature is not None:
            result["temperature"] = self.temperature
        if self.top_p is not None:
            result["top_p"] = self.top_p
        if self.max_tokens is not None:
            result["max_tokens"] = self.max_tokens
        if self.tools:
            result["tools"] = [t.to_openai_format() for t in self.tools]
        if self.tool_choice:
            result["tool_choice"] = self.tool_choice
        if self.stop:
            result["stop"] = self.stop
        if self.presence_penalty is not None:
            result["presence_penalty"] = self.presence_penalty
        if self.frequency_penalty is not None:
            result["frequency_penalty"] = self.frequency_penalty
        if self.user:
            result["user"] = self.user
        
        # 添加额外参数
        result.update(self.metadata)
        
        return result
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        # Anthropic 分离系统消息
        system = self.get_system_message()
        conversation = self.get_conversation_messages()
        
        result = {
            "model": self.model,
            "messages": [msg.to_anthropic_format() for msg in conversation],
            "max_tokens": self.max_tokens or 4096
        }
        
        if system:
            result["system"] = system
        if self.temperature is not None:
            result["temperature"] = self.temperature
        if self.top_p is not None:
            result["top_p"] = self.top_p
        if self.stream:
            result["stream"] = self.stream
        if self.tools:
            result["tools"] = [t.to_anthropic_format() for t in self.tools]
        if self.tool_choice:
            result["tool_choice"] = {"type": self.tool_choice}
        if self.stop:
            result["stop_sequences"] = self.stop
        if self.metadata:
            result["metadata"] = self.metadata
        
        return result
    
    def to_bailian_format(self) -> Dict[str, Any]:
        """转换为百炼格式"""
        result = {
            "model": self.model,
            "messages": [msg.to_bailian_format() for msg in self.messages],
            "stream": self.stream
        }
        
        if self.temperature is not None:
            result["temperature"] = self.temperature
        if self.top_p is not None:
            result["top_p"] = self.top_p
        if self.max_tokens is not None:
            result["max_tokens"] = self.max_tokens
        if self.tools:
            result["tools"] = [t.to_bailian_format() for t in self.tools]
        if self.tool_choice:
            result["tool_choice"] = self.tool_choice
        if self.stop:
            result["stop"] = self.stop
        if self.presence_penalty is not None:
            result["presence_penalty"] = self.presence_penalty
        if self.frequency_penalty is not None:
            result["frequency_penalty"] = self.frequency_penalty
        if self.user:
            result["user"] = self.user
        
        # 添加额外参数
        result.update(self.metadata)
        
        return result
    
    @classmethod
    def from_openai_format(cls, data: Dict[str, Any]) -> 'ChatRequest':
        """从 OpenAI 格式创建请求"""
        messages = [Message.from_openai_format(m) for m in data.get("messages", [])]
        tools = [ToolDefinition.from_openai_format(t) for t in data.get("tools", [])]
        
        # 提取额外参数
        known_keys = {
            "model", "messages", "temperature", "top_p", "max_tokens",
            "stream", "tools", "tool_choice", "stop", "presence_penalty",
            "frequency_penalty", "user"
        }
        metadata = {k: v for k, v in data.items() if k not in known_keys}
        
        return cls(
            messages=messages,
            model=data.get("model", ""),
            temperature=data.get("temperature"),
            top_p=data.get("top_p"),
            max_tokens=data.get("max_tokens"),
            stream=data.get("stream", False),
            tools=tools,
            tool_choice=data.get("tool_choice"),
            stop=data.get("stop"),
            presence_penalty=data.get("presence_penalty"),
            frequency_penalty=data.get("frequency_penalty"),
            user=data.get("user"),
            metadata=metadata
        )
    
    @classmethod
    def from_anthropic_format(cls, data: Dict[str, Any]) -> 'ChatRequest':
        """从 Anthropic 格式创建请求"""
        messages = []
        
        # 处理系统消息
        if "system" in data:
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content=data["system"]
            ))
        
        # 处理对话消息
        for msg in data.get("messages", []):
            messages.append(Message.from_anthropic_format(msg))
        
        tools = [ToolDefinition.from_anthropic_format(t) for t in data.get("tools", [])]
        
        return cls(
            messages=messages,
            model=data.get("model", ""),
            temperature=data.get("temperature"),
            top_p=data.get("top_p"),
            max_tokens=data.get("max_tokens"),
            stream=data.get("stream", False),
            tools=tools,
            tool_choice=data.get("tool_choice", {}).get("type") if data.get("tool_choice") else None,
            stop=data.get("stop_sequences"),
            metadata=data.get("metadata", {})
        )
    
    @classmethod
    def from_bailian_format(cls, data: Dict[str, Any]) -> 'ChatRequest':
        """从百炼格式创建请求"""
        messages = [Message.from_bailian_format(m) for m in data.get("messages", [])]
        tools = [ToolDefinition.from_bailian_format(t) for t in data.get("tools", [])]
        
        # 提取额外参数
        known_keys = {
            "model", "messages", "temperature", "top_p", "max_tokens",
            "stream", "tools", "tool_choice", "stop", "presence_penalty",
            "frequency_penalty", "user"
        }
        metadata = {k: v for k, v in data.items() if k not in known_keys}
        
        return cls(
            messages=messages,
            model=data.get("model", ""),
            temperature=data.get("temperature"),
            top_p=data.get("top_p"),
            max_tokens=data.get("max_tokens"),
            stream=data.get("stream", False),
            tools=tools,
            tool_choice=data.get("tool_choice"),
            stop=data.get("stop"),
            presence_penalty=data.get("presence_penalty"),
            frequency_penalty=data.get("frequency_penalty"),
            user=data.get("user"),
            metadata=metadata
        )


@dataclass
class ChatResponse:
    """
    对话响应 - 统一的对话响应格式
    
    支持多种格式转换。
    """
    id: str
    model: str
    choices: List[ChatChoice]
    usage: UsageInfo
    created: int = field(default_factory=lambda: int(time.time()))
    provider: str = "unknown"  # 供应商名称
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        return {
            "id": self.id,
            "object": "chat.completion",
            "created": self.created,
            "model": self.model,
            "choices": [c.to_openai_format() for c in self.choices],
            "usage": self.usage.to_openai_format()
        }
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        # 合并所有选择项的内容
        content = []
        for choice in self.choices:
            content.extend(choice.to_anthropic_format().get("content", []))
        
        return {
            "id": self.id,
            "type": "message",
            "role": "assistant",
            "content": content,
            "model": self.model,
            "stop_reason": self.choices[0].finish_reason.value if self.choices else "end_turn",
            "usage": self.usage.to_anthropic_format()
        }
    
    def to_bailian_format(self) -> Dict[str, Any]:
        """转换为百炼格式"""
        return {
            "id": self.id,
            "object": "chat.completion",
            "created": self.created,
            "model": self.model,
            "choices": [c.to_bailian_format() for c in self.choices],
            "usage": self.usage.to_bailian_format(),
            "provider": self.provider
        }
    
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