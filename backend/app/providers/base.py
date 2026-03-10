"""
供应商基础接口模块 (Base Provider)
定义所有供应商必须实现的基础接口。
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, List, Dict, Any, Generator, AsyncGenerator
from dataclasses import dataclass, field
import httpx

from app.abstraction.messages import Message
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk


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
    name: str  # 供应商名称
    api_key: str  # API 密钥
    base_url: Optional[str] = None  # API 基础 URL
    timeout: int = 60  # 请求超时时间（秒）
    max_retries: int = 3  # 最大重试次数
    extra_config: Dict[str, Any] = field(default_factory=dict)  # 额外配置
    
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }


class BaseProvider(ABC):
    """
    供应商基类
    
    所有供应商实现必须继承此类并实现其抽象方法。
    """
    
    # 供应商类型标识
    PROVIDER_TYPE: str = "base"
    
    # 供应商能力
    CAPABILITIES: List[ProviderCapability] = [ProviderCapability.CHAT]
    
    def __init__(self, config: ProviderConfig):
        """
        初始化供应商
        
        Args:
            config: 供应商配置
        """
        self.config = config
        self._client = None
    
    @property
    def client(self) -> httpx.Client:
        """获取 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.config.timeout,
                headers=self.config.get_headers()
            )
        return self._client
    
    def has_capability(self, capability: ProviderCapability) -> bool:
        """
        检查供应商是否支持某项能力
        
        Args:
            capability: 能力类型
        
        Returns:
            是否支持该能力
        """
        return capability in self.CAPABILITIES
    
    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行对话请求
        
        Args:
            request: 对话请求对象
        
        Returns:
            对话响应对象
        """
        pass
    
    @abstractmethod
    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """
        执行流式对话请求
        
        Args:
            request: 对话请求对象
        
        Yields:
            流式响应块
        """
        pass
    
    def supports_model(self, model: str) -> bool:
        """
        检查是否支持某个模型
        
        Args:
            model: 模型名称
        
        Returns:
            是否支持该模型
        """
        return True  # 默认支持所有模型，子类可以覆盖
    
    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """
        获取模型信息
        
        Args:
            model: 模型名称
        
        Returns:
            模型信息字典，如果模型不存在返回 None
        """
        return None  # 默认返回 None，子类可以覆盖
    
    def validate_request(self, request: ChatRequest) -> Optional[str]:
        """
        验证请求参数
        
        Args:
            request: 对话请求对象
        
        Returns:
            错误信息，如果验证通过返回 None
        """
        if not request.messages:
            return "Messages are required"
        
        if not request.model:
            return "Model is required"
        
        return None
    
    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据
        
        将统一的 ChatRequest 转换为供应商特定的请求格式。
        子类应该覆盖此方法以实现特定的转换逻辑。
        
        Args:
            request: 对话请求对象
        
        Returns:
            供应商特定的请求字典
        """
        # 默认返回基本格式，子类应覆盖
        return {
            "model": request.model,
            "messages": [],  # 子类应实现消息转换
        }
    
    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析响应数据
        
        将供应商特定的响应格式转换为统一的 ChatResponse。
        子类应该覆盖此方法以实现特定的解析逻辑。
        
        Args:
            response_data: 供应商响应数据
            model: 模型名称
        
        Returns:
            对话响应对象
        """
        # 默认使用 OpenAI 格式解析
        return self._parse_openai_response(response_data, model)
    
    def _parse_openai_response(self, data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析 OpenAI 格式的响应
        
        Args:
            data: 响应数据
            model: 模型名称
        
        Returns:
            对话响应对象
        """
        from app.abstraction.messages import MessageRole, ContentBlock
        
        choices = []
        for choice_data in data.get("choices", []):
            message_data = choice_data.get("message", {})
            
            # 解析消息
            message = None
            if message_data:
                role_str = message_data.get("role", "assistant")
                role = MessageRole(role_str)
                content = message_data.get("content")
                
                # 解析工具调用
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
                                tc_args = json.loads(tc_args)
                            except:
                                tc_args = {}
                        
                        blocks.append(ContentBlock.from_tool_call(
                            tc_id, tc_name, tc_args if isinstance(tc_args, dict) else {}
                        ))
                
                if content:
                    blocks.insert(0, ContentBlock.from_text(content))
                
                message = Message(
                    role=role,
                    content=blocks if blocks else content
                )
            
            finish_reason_str = choice_data.get("finish_reason")
            finish_reason = FinishReason(finish_reason_str) if finish_reason_str else FinishReason.STOP
            
            # 解析工具调用
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
                            tc_args = json.loads(tc_args)
                        except:
                            tc_args = {}
                    
                    tool_calls.append(ToolCall(
                        id=tc_id,
                        name=tc_name,
                        arguments=tc_args if isinstance(tc_args, dict) else {}
                    ))
            
            choices.append(ChatChoice(
                index=choice_data.get("index", 0),
                message=message,
                finish_reason=finish_reason,
                tool_calls=tool_calls
            ))
        
        usage_data = data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0)
        )
        
        return ChatResponse(
            id=data.get("id", ""),
            model=model,
            choices=choices,
            usage=usage,
            created=data.get("created", 0),
            provider=self.PROVIDER_TYPE
        )
    
    def close(self):
        """关闭客户端连接"""
        if self._client:
            self._client.close()
            self._client = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(type={self.PROVIDER_TYPE}, capabilities={[c.value for c in self.CAPABILITIES]})"


class AsyncBaseProvider(ABC):
    """
    异步供应商基类
    
    提供异步 API 调用支持。
    """
    
    PROVIDER_TYPE: str = "async_base"
    CAPABILITIES: List[ProviderCapability] = [ProviderCapability.CHAT]
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._async_client = None
    
    @property
    def async_client(self) -> httpx.AsyncClient:
        """获取异步 HTTP 客户端"""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                timeout=self.config.timeout,
                headers=self.config.get_headers()
            )
        return self._async_client
    
    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """异步执行对话请求"""
        pass
    
    @abstractmethod
    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """异步执行流式对话请求"""
        pass
    
    async def close(self):
        """关闭异步客户端连接"""
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()