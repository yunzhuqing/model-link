"""
流式响应抽象模块 (Streaming Abstraction)
提供统一的流式响应处理接口。
"""
from enum import Enum
from typing import Optional, List, Dict, Any, Generator, Callable, AsyncGenerator
from dataclasses import dataclass, field
import json
import time
import uuid

from .messages import Message, MessageRole
from .tools import ToolCall
from .chat import FinishReason


class StreamEventType(Enum):
    """流式事件类型"""
    CONTENT_DELTA = "content_delta"
    TOOL_CALL = "tool_call"
    USAGE = "usage"
    ERROR = "error"
    DONE = "done"


@dataclass
class StreamChunk:
    """
    流式响应块 - 表示流式响应中的单个数据块
    
    支持不同供应商的流式格式转换。
    """
    id: str
    model: str
    delta_content: Optional[str] = None
    delta_role: Optional[str] = None
    delta_reasoning_content: Optional[str] = None  # 推理内容（如 DeepSeek R1）
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: Optional[FinishReason] = None
    usage: Optional[Dict[str, int]] = None
    event_type: StreamEventType = StreamEventType.CONTENT_DELTA
    created: int = field(default_factory=lambda: int(time.time()))
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        delta = {}
        
        if self.delta_role:
            delta["role"] = self.delta_role
        if self.delta_content:
            delta["content"] = self.delta_content
        if self.delta_reasoning_content:
            delta["reasoning_content"] = self.delta_reasoning_content
        if self.tool_calls:
            delta["tool_calls"] = self.tool_calls
        
        result = {
            "id": self.id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": self.finish_reason.value if self.finish_reason else None
            }]
        }
        
        if self.usage:
            result["usage"] = self.usage
        
        return result
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        if self.event_type == StreamEventType.DONE:
            return {
                "type": "message_stop"
            }
        
        if self.event_type == StreamEventType.USAGE:
            return {
                "type": "message_delta",
                "usage": self.usage
            }
        
        result = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {}
        }
        
        if self.delta_content:
            result["delta"] = {
                "type": "text_delta",
                "text": self.delta_content
            }
        
        if self.tool_calls:
            return {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": self.tool_calls[0].get("id", ""),
                    "name": self.tool_calls[0].get("function", {}).get("name", "")
                }
            }
        
        return result
    
    def to_sse(self, provider_format: str = "openai") -> str:
        """转换为 SSE 格式字符串"""
        if provider_format == "anthropic":
            data = self.to_anthropic_format()
        else:
            data = self.to_openai_format()
        
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    
    @classmethod
    def create_text_chunk(cls, id: str, model: str, text: str) -> 'StreamChunk':
        """创建文本块"""
        return cls(
            id=id,
            model=model,
            delta_content=text,
            event_type=StreamEventType.CONTENT_DELTA
        )
    
    @classmethod
    def create_role_chunk(cls, id: str, model: str, role: str = "assistant") -> 'StreamChunk':
        """创建角色块"""
        return cls(
            id=id,
            model=model,
            delta_role=role,
            event_type=StreamEventType.CONTENT_DELTA
        )
    
    @classmethod
    def create_tool_call_chunk(cls, id: str, model: str, tool_call: Dict[str, Any]) -> 'StreamChunk':
        """创建工具调用块"""
        return cls(
            id=id,
            model=model,
            tool_calls=[tool_call],
            event_type=StreamEventType.TOOL_CALL
        )
    
    @classmethod
    def create_usage_chunk(cls, id: str, model: str, usage: Dict[str, int]) -> 'StreamChunk':
        """创建使用量块"""
        return cls(
            id=id,
            model=model,
            usage=usage,
            event_type=StreamEventType.USAGE
        )
    
    @classmethod
    def create_finish_chunk(cls, id: str, model: str, finish_reason: FinishReason = FinishReason.STOP) -> 'StreamChunk':
        """创建完成块"""
        return cls(
            id=id,
            model=model,
            finish_reason=finish_reason,
            event_type=StreamEventType.DONE
        )


class StreamManager:
    """
    流式响应管理器 - 管理流式响应的生成和转换
    
    提供:
    - 流式响应生成器
    - 格式转换
    - 流式响应处理
    """
    
    def __init__(
        self,
        response_id: str = None,
        model: str = "",
        provider_format: str = "openai"
    ):
        self.response_id = response_id or f"chatcmpl-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.provider_format = provider_format
        self.created = int(time.time())
    
    def create_start_chunk(self) -> StreamChunk:
        """创建起始块"""
        return StreamChunk.create_role_chunk(
            id=self.response_id,
            model=self.model,
            role="assistant"
        )
    
    def create_text_chunk(self, text: str) -> StreamChunk:
        """创建文本块"""
        return StreamChunk.create_text_chunk(
            id=self.response_id,
            model=self.model,
            text=text
        )
    
    def create_tool_call_chunk(self, tool_call: Dict[str, Any]) -> StreamChunk:
        """创建工具调用块"""
        return StreamChunk.create_tool_call_chunk(
            id=self.response_id,
            model=self.model,
            tool_call=tool_call
        )
    
    def create_usage_chunk(self, usage: Dict[str, int]) -> StreamChunk:
        """创建使用量块"""
        return StreamChunk.create_usage_chunk(
            id=self.response_id,
            model=self.model,
            usage=usage
        )
    
    def create_finish_chunk(self, finish_reason: FinishReason = FinishReason.STOP) -> StreamChunk:
        """创建完成块"""
        return StreamChunk.create_finish_chunk(
            id=self.response_id,
            model=self.model,
            finish_reason=finish_reason
        )
    
    def text_to_stream(self, text: str, chunk_size: int = 10) -> Generator[StreamChunk, None, None]:
        """
        将文本转换为流式块
        
        Args:
            text: 要流式输出的文本
            chunk_size: 每个块包含的字符数
        
        Yields:
            StreamChunk 对象
        """
        # 首先发送角色块
        yield self.create_start_chunk()
        
        # 按字符数分割文本
        for i in range(0, len(text), chunk_size):
            chunk_text = text[i:i + chunk_size]
            yield self.create_text_chunk(chunk_text)
        
        # 发送完成块
        yield self.create_finish_chunk()
    
    def format_sse(self, chunk: StreamChunk) -> str:
        """将块格式化为 SSE 字符串"""
        return chunk.to_sse(self.provider_format)
    
    def generate_sse_stream(
        self,
        text: str,
        chunk_size: int = 10,
        include_usage: bool = False,
        usage: Optional[Dict[str, int]] = None
    ) -> Generator[str, None, None]:
        """
        生成 SSE 格式的流式响应
        
        Args:
            text: 要流式输出的文本
            chunk_size: 每个块包含的字符数
            include_usage: 是否包含使用量信息
            usage: 使用量信息
        
        Yields:
            SSE 格式的字符串
        """
        for chunk in self.text_to_stream(text, chunk_size):
            yield self.format_sse(chunk)
        
        # 发送使用量信息
        if include_usage and usage:
            yield self.format_sse(self.create_usage_chunk(usage))
        
        # 发送完成信号
        yield "data: [DONE]\n\n"
    
    @staticmethod
    def parse_openai_stream_chunk(data: Dict[str, Any]) -> StreamChunk:
        """解析 OpenAI 格式的流式块"""
        chunk_id = data.get("id", "")
        model = data.get("model", "")
        choices = data.get("choices", [])
        
        delta_content = None
        delta_role = None
        delta_reasoning_content = None
        tool_calls = []
        finish_reason = None
        
        if choices:
            choice = choices[0]
            delta = choice.get("delta", {})
            delta_content = delta.get("content")
            delta_role = delta.get("role")
            delta_reasoning_content = delta.get("reasoning_content")
            tool_calls = delta.get("tool_calls", [])
            finish_reason_value = choice.get("finish_reason")
            if finish_reason_value:
                finish_reason = FinishReason(finish_reason_value)
        
        usage = data.get("usage")
        
        return StreamChunk(
            id=chunk_id,
            model=model,
            delta_content=delta_content,
            delta_role=delta_role,
            delta_reasoning_content=delta_reasoning_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            created=data.get("created", int(time.time()))
        )
    
    @staticmethod
    def parse_anthropic_stream_event(event: Dict[str, Any]) -> StreamChunk:
        """解析 Anthropic 格式的流式事件"""
        event_type = event.get("type", "")
        
        if event_type == "message_start":
            message = event.get("message", {})
            return StreamChunk(
                id=message.get("id", ""),
                model=message.get("model", ""),
                delta_role="assistant",
                event_type=StreamEventType.CONTENT_DELTA
            )
        
        elif event_type == "content_block_delta":
            delta = event.get("delta", {})
            text = delta.get("text", "") if delta.get("type") == "text_delta" else ""
            return StreamChunk(
                id="",
                model="",
                delta_content=text,
                event_type=StreamEventType.CONTENT_DELTA
            )
        
        elif event_type == "content_block_start":
            content_block = event.get("content_block", {})
            if content_block.get("type") == "tool_use":
                return StreamChunk(
                    id="",
                    model="",
                    tool_calls=[{
                        "id": content_block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": content_block.get("name", ""),
                            "arguments": ""
                        }
                    }],
                    event_type=StreamEventType.TOOL_CALL
                )
        
        elif event_type == "message_delta":
            usage = event.get("usage", {})
            stop_reason = event.get("delta", {}).get("stop_reason")
            finish_reason = FinishReason(stop_reason) if stop_reason else None
            
            return StreamChunk(
                id="",
                model="",
                usage=usage,
                finish_reason=finish_reason,
                event_type=StreamEventType.USAGE
            )
        
        elif event_type == "message_stop":
            return StreamChunk(
                id="",
                model="",
                event_type=StreamEventType.DONE
            )
        
        # 默认返回空块
        return StreamChunk(
            id="",
            model="",
            event_type=StreamEventType.CONTENT_DELTA
        )


def create_stream_response_generator(
    text: str,
    model: str,
    provider_format: str = "openai",
    chunk_size: int = 10,
    usage: Optional[Dict[str, int]] = None
) -> Generator[str, None, None]:
    """
    创建流式响应生成器的便捷函数
    
    Args:
        text: 要流式输出的文本
        model: 模型名称
        provider_format: 供应商格式 ("openai", "anthropic", "bailian")
        chunk_size: 每个块包含的字符数
        usage: 使用量信息
    
    Yields:
        SSE 格式的字符串
    """
    manager = StreamManager(model=model, provider_format=provider_format)
    yield from manager.generate_sse_stream(
        text=text,
        chunk_size=chunk_size,
        include_usage=usage is not None,
        usage=usage
    )