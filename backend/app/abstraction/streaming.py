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
    anthropic_index: int = 0  # Anthropic 格式的内容块索引（由适配器设置）
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: Optional[FinishReason] = None
    usage: Optional[Dict[str, int]] = None
    event_type: StreamEventType = StreamEventType.CONTENT_DELTA
    created: int = field(default_factory=lambda: int(time.time()))
    # Pre-formatted SSE event strings that adapters should pass through verbatim.
    # Used by providers (e.g. Azure) to forward Responses API events that have no
    # equivalent in the StreamChunk data model (e.g. reasoning_summary events).
    raw_sse_passthrough: List[str] = field(default_factory=list)
    
    # Standard role values that are valid in OpenAI Chat Completions delta chunks.
    # Non-standard values (e.g. Azure internal msg_xxx IDs encoded in delta_role) are
    # silently dropped so they never leak into the client-facing /v1/chat/completions
    # stream output.
    _STANDARD_ROLES = frozenset({"assistant", "user", "system", "tool", "function"})

    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        delta = {}

        # Only emit delta_role when it is a genuine chat role.
        # Azure Responses API streaming encodes internal message IDs (e.g. "msg_xxx")
        # in delta_role as marker chunks; those must not appear in Chat Completions output.
        if self.delta_role and self.delta_role in self._STANDARD_ROLES:
            delta["role"] = self.delta_role

        # When finish_reason is set, delta_content may contain the FULL assembled text
        # (Azure Responses API convention: the completed event carries the whole text so
        # the Responses adapter can emit response.output_text.done).
        # This is NOT a new incremental delta, so we skip it here to avoid re-sending
        # all content in the final Chat Completions chunk.
        if self.delta_content and not self.finish_reason:
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
            # Strip internal implementation keys (e.g. _azure_completed_response) that
            # are only meaningful to the Responses API adapter and must never be sent to
            # clients via the Chat Completions stream.
            clean_usage = {k: v for k, v in self.usage.items() if not k.startswith('_')}
            if clean_usage:
                result["usage"] = self._format_openai_usage(clean_usage)

        return result

    @staticmethod
    def _format_openai_usage(usage: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format a flat usage dict into the OpenAI Chat Completions nested structure.

        OpenAI standard:
        {
            "prompt_tokens": N,
            "completion_tokens": N,
            "total_tokens": N,
            "prompt_tokens_details": {"cached_tokens": N, ...},
            "completion_tokens_details": {"reasoning_tokens": N, ...}
        }

        Our internal flat representation uses top-level "reasoning_tokens" and
        "cached_tokens" keys which must be moved into the nested detail dicts.
        """
        formatted: Dict[str, Any] = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        # Build completion_tokens_details
        completion_details: Dict[str, Any] = {}
        if "reasoning_tokens" in usage:
            completion_details["reasoning_tokens"] = usage["reasoning_tokens"]
        # Pass through any pre-nested completion details from upstream
        for k, v in usage.get("completion_tokens_details", {}).items():
            completion_details.setdefault(k, v)
        if completion_details:
            formatted["completion_tokens_details"] = completion_details

        # Build prompt_tokens_details
        prompt_details: Dict[str, Any] = {}
        if "cached_tokens" in usage:
            prompt_details["cached_tokens"] = usage["cached_tokens"]
        # Pass through any pre-nested prompt details from upstream
        for k, v in usage.get("prompt_tokens_details", {}).items():
            prompt_details.setdefault(k, v)
        if prompt_details:
            formatted["prompt_tokens_details"] = prompt_details

        return formatted
    
    def _build_anthropic_usage(self) -> Dict[str, int]:
        """
        构建 Anthropic 格式的 usage 字典。
        
        将 OpenAI 格式的 usage 字段映射为 Anthropic 格式：
        - prompt_tokens → input_tokens
        - completion_tokens → output_tokens
        - 同时支持 cache_read_input_tokens, cache_creation_input_tokens
        """
        usage = {}
        if self.usage:
            # input_tokens: 优先使用 input_tokens，其次 prompt_tokens
            usage["input_tokens"] = self.usage.get("input_tokens",
                                    self.usage.get("prompt_tokens", 0))
            # output_tokens: 优先使用 output_tokens，其次 completion_tokens
            usage["output_tokens"] = self.usage.get("output_tokens",
                                     self.usage.get("completion_tokens", 0))
            # cache tokens
            cache_read = self.usage.get("cache_read_input_tokens",
                         self.usage.get("cache_read_tokens", 0))
            if cache_read:
                usage["cache_read_input_tokens"] = cache_read
            cache_creation = self.usage.get("cache_creation_input_tokens",
                             self.usage.get("cache_write_tokens", 0))
            if cache_creation:
                usage["cache_creation_input_tokens"] = cache_creation
        else:
            usage["input_tokens"] = 0
            usage["output_tokens"] = 0
        return usage

    def _map_finish_reason_to_anthropic(self) -> Optional[str]:
        """将 finish_reason 映射为 Anthropic stop_reason"""
        if not self.finish_reason:
            return None
        mapping = {
            FinishReason.STOP: "end_turn",
            FinishReason.LENGTH: "max_tokens",
            FinishReason.TOOL_CALLS: "tool_use",
            FinishReason.CONTENT_FILTER: "end_turn",
            FinishReason.ERROR: "end_turn",
        }
        return mapping.get(self.finish_reason, "end_turn")

    def to_anthropic_events(self) -> List[Dict[str, Any]]:
        """
        转换为 Anthropic 格式的事件列表。
        
        一个 StreamChunk 可能需要输出多个 Anthropic SSE 事件，例如：
        当 finish_reason 存在时需要输出 content_block_stop + message_delta。
        """
        events = []

        if self.event_type == StreamEventType.DONE:
            # message_stop 由 adapter 的 format_stream_end() 处理
            return events

        if self.event_type == StreamEventType.USAGE:
            # message_delta with stop_reason and usage
            stop_reason = self._map_finish_reason_to_anthropic()
            usage = self._build_anthropic_usage()
            event = {
                "type": "message_delta",
                "delta": {
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": usage.get("output_tokens", 0)},
            }
            return [event]

        idx = self.anthropic_index

        # 处理 thinking/reasoning 内容
        if self.delta_reasoning_content:
            events.append({
                "type": "content_block_delta",
                "index": idx,
                "delta": {
                    "type": "thinking_delta",
                    "thinking": self.delta_reasoning_content
                }
            })

        # 处理文本内容
        # When finish_reason is set, delta_content may contain the FULL assembled text
        # (e.g. from Volcengine/Azure response.completed event), not a new incremental
        # delta. Skip it to avoid re-sending all content in the final Anthropic chunk.
        if self.delta_content and not self.finish_reason:
            events.append({
                "type": "content_block_delta",
                "index": idx,
                "delta": {
                    "type": "text_delta",
                    "text": self.delta_content
                }
            })

        # 处理工具调用
        if self.tool_calls:
            tc = self.tool_calls[0]
            tc_id = tc.get("id", "")
            tc_func = tc.get("function", {})
            tc_name = tc_func.get("name", "")
            tc_arguments = tc_func.get("arguments", "")

            if tc_id:
                events.append({
                    "type": "content_block_start",
                    "index": idx,
                    "content_block": {
                        "type": "tool_use",
                        "id": tc_id,
                        "name": tc_name,
                        "input": {}
                    }
                })

            if tc_arguments:
                events.append({
                    "type": "content_block_delta",
                    "index": idx,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": tc_arguments
                    }
                })

        # 当有 finish_reason 时，追加 content_block_stop + message_delta
        if self.finish_reason:
            events.append({
                "type": "content_block_stop",
                "index": idx,
            })
            stop_reason = self._map_finish_reason_to_anthropic()
            usage = self._build_anthropic_usage()
            message_delta = {
                "type": "message_delta",
                "delta": {
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                },
                # Anthropic SDK's MessageDeltaUsage only expects output_tokens
                "usage": {"output_tokens": usage.get("output_tokens", 0)},
            }
            events.append(message_delta)

        # 如果没有任何有意义的事件（如 role-only chunk），返回空
        if not events and self.delta_role:
            # role chunk 不需要单独的 anthropic 事件
            # message_start 由 adapter 的 format_stream_start() 处理
            pass

        return events

    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式（返回单个事件，向后兼容）"""
        events = self.to_anthropic_events()
        if events:
            return events[0]
        return {"type": "content_block_delta", "index": 0, "delta": {}}
    
    def to_sse(self, provider_format: str = "openai") -> str:
        """转换为 SSE 格式字符串"""
        if provider_format == "anthropic":
            events = self.to_anthropic_events()
            if not events:
                return ""
            parts = []
            for event in events:
                event_type = event.get("type", "")
                parts.append(f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")
            return "".join(parts)
        else:
            # OpenAI Chat Completions SSE format.
            #
            # When a chunk carries BOTH finish_reason and usage (which happens when Azure's
            # response.completed event is translated to a StreamChunk), OpenAI's protocol
            # requires TWO separate SSE events:
            #   1. A finish chunk:  choices=[{finish_reason: "stop", delta: {}}], no usage
            #   2. A usage chunk:   choices=[] with the usage dict (stream_options behavior)
            #
            # This keeps compatibility with OpenAI clients that expect usage in a trailing
            # empty-choices chunk.
            clean_usage = None
            if self.usage:
                clean_usage = {k: v for k, v in self.usage.items() if not k.startswith('_')}

            if self.finish_reason and clean_usage:
                # Emit finish chunk without usage
                finish_data = self.to_openai_format()
                finish_data.pop("usage", None)
                parts = [f"data: {json.dumps(finish_data, ensure_ascii=False)}\n\n"]

                # Emit trailing usage-only chunk with empty choices (standard OpenAI behavior)
                usage_data = {
                    "id": self.id,
                    "object": "chat.completion.chunk",
                    "created": self.created,
                    "model": self.model,
                    "choices": [],
                    "usage": self._format_openai_usage(clean_usage),
                }
                parts.append(f"data: {json.dumps(usage_data, ensure_ascii=False)}\n\n")
                return "".join(parts)

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