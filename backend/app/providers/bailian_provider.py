"""
百炼供应商实现 (Bailian Provider)
实现阿里云百炼模型的 API 调用。

百炼 API 文档：https://help.aliyun.com/document_detail/2712195.html
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid

from .base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.messages import Message, MessageRole
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamEventType


class BailianProvider(BaseProvider):
    """
    百炼供应商实现
    
    阿里云百炼是一个 AI 模型服务平台，提供多种大语言模型的 API 调用。
    百炼 API 采用 OpenAI 兼容格式，但有一些细微差异。
    """
    
    PROVIDER_TYPE: str = "bailian"
    
    # 百炼支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
        ProviderCapability.CACHE,
    ]
    
    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # 百炼支持的模型列表
    SUPPORTED_MODELS = {
        # Qwen 系列模型
        "qwen-turbo": {
            "description": "通义千问超大规模语言模型，快速响应",
            "context_size": 8192,
            "supports_vision": False,
        },
        "qwen-plus": {
            "description": "通义千问超大规模语言模型，能力更强",
            "context_size": 32768,
            "supports_vision": False,
        },
        "qwen-max": {
            "description": "通义千问超大规模语言模型，能力最强",
            "context_size": 32768,
            "supports_vision": False,
        },
        "qwen-long": {
            "description": "通义千问长文本模型",
            "context_size": 10000,
            "supports_vision": False,
        },
        "qwen-vl-plus": {
            "description": "通义千问视觉模型",
            "context_size": 8192,
            "supports_vision": True,
        },
        "qwen-vl-max": {
            "description": "通义千问视觉模型，能力更强",
            "context_size": 8192,
            "supports_vision": True,
        },
        "qwen-audio-turbo": {
            "description": "通义千问音频模型",
            "context_size": 8192,
            "supports_audio": True,
        },
        # DeepSeek 系列
        "deepseek-v3": {
            "description": "DeepSeek V3 模型",
            "context_size": 64000,
            "supports_vision": False,
        },
        "deepseek-r1": {
            "description": "DeepSeek R1 推理模型",
            "context_size": 64000,
            "supports_vision": False,
        },
    }
    
    def __init__(self, config: ProviderConfig):
        """
        初始化百炼供应商
        
        Args:
            config: 供应商配置
        """
        # 设置默认 base_url
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        
        super().__init__(config)
    
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
    
    @property
    def client(self) -> Any:
        """获取 HTTP 客户端"""
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                timeout=self.config.timeout,
                headers=self.get_headers()
            )
        return self._client
    
    def supports_model(self, model: str) -> bool:
        """
        检查是否支持某个模型
        
        Args:
            model: 模型名称
        
        Returns:
            是否支持该模型
        """
        # 百炼支持自定义模型，所以默认返回 True
        return True
    
    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """
        获取模型信息
        
        Args:
            model: 模型名称
        
        Returns:
            模型信息字典
        """
        # 首先检查预定义模型
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        
        # 返回默认信息
        return {
            "description": f"Custom model: {model}",
            "context_size": 8192,
            "supports_vision": False,
        }
    
    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备百炼请求数据
        
        百炼 API 采用 OpenAI 兼容格式，但有一些特殊参数：
        - enable_search: 启用搜索增强
        - incremental_output: 流式增量输出
        
        Args:
            request: 对话请求对象
        
        Returns:
            百炼请求字典
        """
        # 基础请求结构
        data = {
            "model": request.model,
            "messages": [msg.to_bailian_format() for msg in request.messages],
            "stream": request.stream,
        }
        
        # 添加可选参数
        if request.temperature is not None:
            data["temperature"] = request.temperature
        if request.top_p is not None:
            data["top_p"] = request.top_p
        if request.max_tokens is not None:
            data["max_tokens"] = request.max_tokens
        if request.stop:
            data["stop"] = request.stop
        if request.presence_penalty is not None:
            data["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            data["frequency_penalty"] = request.frequency_penalty
        
        # 工具调用
        if request.tools:
            data["tools"] = [t.to_bailian_format() for t in request.tools]
        if request.tool_choice:
            data["tool_choice"] = request.tool_choice
        
        # 百炼特有参数
        if "enable_search" in request.metadata:
            data["enable_search"] = request.metadata["enable_search"]
        
        # 添加额外参数
        for key, value in request.metadata.items():
            if key not in ["enable_search"]:
                data[key] = value
        
        return data
    
    def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行对话请求
        
        Args:
            request: 对话请求对象
        
        Returns:
            对话响应对象
        """
        # 验证请求
        error = self.validate_request(request)
        if error:
            raise ValueError(error)
        
        # 准备请求数据
        request_data = self.prepare_request(request)
        request_data["stream"] = False
        
        print(f"Bailian Request Body: {json.dumps(request_data, ensure_ascii=False)}")
        
        # 发送请求
        url = f"{self.config.base_url}/chat/completions"
        
        try:
            response = self.client.post(url, json=request_data)
            response.raise_for_status()
            
            response_data = response.json()
            return self.parse_response(response_data, request.model)
        
        except Exception as e:
            raise RuntimeError(f"Bailian API error: {str(e)}")
    
    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """
        执行流式对话请求
        
        Args:
            request: 对话请求对象
        
        Yields:
            流式响应块
        """
        # 验证请求
        error = self.validate_request(request)
        if error:
            raise ValueError(error)
        
        # 准备请求数据
        request_data = self.prepare_request(request)
        request_data["stream"] = True
        
        # 百炼特有：增量输出
        request_data["incremental_output"] = True
        
        print(f"Bailian Stream Request Body: {json.dumps(request_data, ensure_ascii=False)}")
        
        # 发送请求
        url = f"{self.config.base_url}/chat/completions"
        
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        
        try:
            with self.client.stream("POST", url, json=request_data) as response:
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if not line:
                        continue
                    
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk_data = json.loads(data_str)
                            chunk = self._parse_stream_chunk(chunk_data, response_id, request.model)
                            if chunk:
                                yield chunk
                        except json.JSONDecodeError:
                            continue
        
        except Exception as e:
            raise RuntimeError(f"Bailian streaming API error: {str(e)}")
    
    def _parse_stream_chunk(
        self, 
        data: Dict[str, Any], 
        response_id: str, 
        model: str
    ) -> Optional[StreamChunk]:
        """
        解析流式响应块
        
        Args:
            data: 响应数据
            response_id: 响应 ID
            model: 模型名称
        
        Returns:
            流式响应块，如果无效返回 None
        """
        choices = data.get("choices", [])
        if not choices:
            return None
        
        choice = choices[0]
        delta = choice.get("delta", {})
        
        # 提取内容
        content = delta.get("content")
        role = delta.get("role")
        reasoning_content = delta.get("reasoning_content")
        
        # 提取完成原因
        finish_reason_str = choice.get("finish_reason")
        finish_reason = None
        if finish_reason_str:
            try:
                finish_reason = FinishReason(finish_reason_str)
            except ValueError:
                finish_reason = FinishReason.STOP
        
        # 提取工具调用
        tool_calls = delta.get("tool_calls", [])
        
        return StreamChunk(
            id=data.get("id", response_id),
            model=data.get("model", model),
            delta_content=content,
            delta_role=role,
            delta_reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            created=data.get("created", int(time.time()))
        )
    
    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析百炼响应数据
        
        百炼响应格式与 OpenAI 类似，但可能包含额外的使用量信息。
        
        Args:
            response_data: 响应数据
            model: 模型名称
        
        Returns:
            对话响应对象
        """
        choices = []
        for choice_data in response_data.get("choices", []):
            message_data = choice_data.get("message", {})
            
            # 解析消息
            message = None
            reasoning_content = message_data.get("reasoning_content")
            if message_data:
                message = Message(
                    role=MessageRole(message_data.get("role", "assistant")),
                    content=message_data.get("content", ""),
                    reasoning_content=reasoning_content
                )
            
            # 解析完成原因
            finish_reason_str = choice_data.get("finish_reason")
            finish_reason = FinishReason.STOP
            if finish_reason_str:
                try:
                    finish_reason = FinishReason(finish_reason_str)
                except ValueError:
                    pass
            
            # 解析工具调用
            tool_calls = []
            if "tool_calls" in message_data:
                for tc_data in message_data["tool_calls"]:
                    tool_calls.append(ToolCall.from_bailian_format(tc_data))
            
            choices.append(ChatChoice(
                index=choice_data.get("index", 0),
                message=message,
                finish_reason=finish_reason,
                tool_calls=tool_calls,
                reasoning_content=reasoning_content
            ))
        
        # 解析使用量信息
        usage_data = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            cache_read_tokens=usage_data.get("cache_read_tokens", 0),
            cache_write_tokens=usage_data.get("cache_write_tokens", 0),
        )
        
        return ChatResponse(
            id=response_data.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
            model=model,
            choices=choices,
            usage=usage,
            created=response_data.get("created", int(time.time())),
            provider=self.PROVIDER_TYPE
        )
    
    def list_models(self) -> List[Dict[str, Any]]:
        """
        列出可用模型
        
        Returns:
            模型列表
        """
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "bailian",
                "permission": [],
                "root": model_name,
                "parent": None,
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
                "supports_audio": info.get("supports_audio", False),
            })
        return models


class BailianAsyncProvider:
    """
    百炼异步供应商实现
    
    提供异步 API 调用支持。
    """
    
    PROVIDER_TYPE: str = "bailian"
    
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
        ProviderCapability.CACHE,
    ]
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        if not self.config.base_url:
            self.config.base_url = BailianProvider.DEFAULT_BASE_URL
        self._async_client = None
    
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
    
    @property
    def async_client(self) -> Any:
        """获取异步 HTTP 客户端"""
        if self._async_client is None:
            import httpx
            self._async_client = httpx.AsyncClient(
                timeout=self.config.timeout,
                headers=self.get_headers()
            )
        return self._async_client
    
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        异步执行对话请求
        
        Args:
            request: 对话请求对象
        
        Returns:
            对话响应对象
        """
        # 使用同步版本的实现
        sync_provider = BailianProvider(self.config)
        return sync_provider.chat(request)
    
    async def stream_chat(self, request: ChatRequest):
        """
        异步执行流式对话请求
        
        Args:
            request: 对话请求对象
        
        Yields:
            流式响应块
        """
        # 使用同步版本的实现
        sync_provider = BailianProvider(self.config)
        for chunk in sync_provider.stream_chat(request):
            yield chunk
    
    async def close(self):
        """关闭异步客户端连接"""
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None