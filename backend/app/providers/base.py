"""
供应商基础接口模块 (Base Provider)
定义所有供应商必须实现的基础接口。
"""
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from enum import Enum
from typing import Optional, List, Dict, Any, AsyncGenerator
from dataclasses import dataclass, field
import httpx

from app.abstraction.messages import Message
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk
from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse
from app.utils import json_loads


class ProviderCapability(Enum):
    """供应商能力枚举"""
    CHAT = "chat"
    STREAMING = "streaming"
    TOOLS = "tools"
    VISION = "vision"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    WEB_SEARCH = "web_search"
    CACHE = "cache"


@dataclass
class ProviderConfig:
    """
    供应商配置
    包含连接到供应商 API 所需的所有配置信息。
    """
    name: str
    api_key: str
    base_url: Optional[str] = None
    max_retries: int = 3
    authorization: str = "Authorization"
    extra_config: Dict[str, Any] = field(default_factory=dict)

    def get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.authorization == "Authorization":
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers[self.authorization] = self.api_key
        return headers


class BaseProvider(ABC):
    """
    异步供应商基类
    所有供应商实现必须继承此类并实现其抽象方法。
    使用 httpx.AsyncClient 进行异步 HTTP 调用。
    """

    PROVIDER_TYPE: str = "base"
    CAPABILITIES: List[ProviderCapability] = [ProviderCapability.CHAT]
    DEFAULT_TIMEOUT: int = 600  # Default HTTP timeout (seconds)

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client = None
        self.tracer: Any = None  # Set by GatewayService before calling chat/stream_chat

    @property
    def client(self) -> httpx.AsyncClient:
        """获取异步 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=600.0, write=600.0, pool=10.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100, keepalive_expiry=30),
                headers=self.config.get_headers(),
            )
        return self._client

    @asynccontextmanager
    async def _trace_call(self, model_name: str, input_data: dict | None = None):
        """Async context manager wrapping a provider API call in a child span."""
        if self.tracer is None:
            yield None
            return
        child_span = self.tracer.start_child(model_name, model=model_name, provider_type=self.PROVIDER_TYPE, input_data=input_data)
        if child_span is not None and input_data is not None:
            child_span.log_input(input_data)
        _error: Optional[Exception] = None
        try:
            yield child_span
        except Exception as e:
            _error = e
            raise
        finally:
            if child_span is not None:
                child_span.end(error=_error)

    def has_capability(self, capability: ProviderCapability) -> bool:
        return capability in self.CAPABILITIES

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """异步执行对话请求"""
        pass

    @abstractmethod
    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """异步执行流式对话请求"""
        pass

    def supports_model(self, model: str) -> bool:
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        return None

    @staticmethod
    def _get_request_timeout(request: ChatRequest) -> Optional[int]:
        return request.metadata.get('timeout') if request.metadata else None

    def validate_request(self, request: ChatRequest) -> Optional[str]:
        if not request.messages and not request.system:
            return "Messages are required"
        if not request.model:
            return "Model is required"
        return None

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        return {"model": request.model, "messages": []}

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        return self._parse_openai_response(response_data, model)

    def _parse_openai_response(self, data: Dict[str, Any], model: str) -> ChatResponse:
        from app.abstraction.messages import MessageRole, ContentBlock
        choices = []
        for choice_data in data.get("choices", []):
            message_data = choice_data.get("message", {})
            message = None
            if message_data:
                role_str = message_data.get("role", "assistant")
                role = MessageRole(role_str)
                content = message_data.get("content")
                blocks = []
                if "tool_calls" in message_data:
                    for tc in message_data["tool_calls"]:
                        tc_id = tc.get("id")
                        func = tc.get("function", {})
                        tc_name = func.get("name")
                        tc_args = func.get("arguments")
                        import json
                        if isinstance(tc_args, str):
                            try:
                                tc_args = json_loads(tc_args)
                            except Exception:
                                tc_args = {}
                        blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_args if isinstance(tc_args, dict) else {}))
                if content:
                    blocks.insert(0, ContentBlock.from_text(content))
                message = Message(role=role, content=blocks if blocks else content)
            finish_reason_str = choice_data.get("finish_reason")
            finish_reason = FinishReason(finish_reason_str) if finish_reason_str else FinishReason.STOP
            tool_calls = []
            if message_data and "tool_calls" in message_data:
                for tc in message_data["tool_calls"]:
                    import json
                    tc_id = tc.get("id")
                    func = tc.get("function", {})
                    tc_name = func.get("name")
                    tc_args = func.get("arguments")
                    if isinstance(tc_args, str):
                        try:
                            tc_args = json_loads(tc_args)
                        except Exception:
                            tc_args = {}
                    tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=tc_args if isinstance(tc_args, dict) else {}))
            choices.append(ChatChoice(index=choice_data.get("index", 0), message=message, finish_reason=finish_reason, tool_calls=tool_calls))
        usage_data = data.get("usage", {})
        usage = UsageInfo(prompt_tokens=usage_data.get("prompt_tokens", 0), completion_tokens=usage_data.get("completion_tokens", 0), total_tokens=usage_data.get("total_tokens", 0))
        return ChatResponse(id=data.get("id", ""), model=model, choices=choices, usage=usage, created=data.get("created", 0), provider=self.PROVIDER_TYPE)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(type={self.PROVIDER_TYPE}, capabilities={[c.value for c in self.CAPABILITIES]})"