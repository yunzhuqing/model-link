"""
百炼供应商实现 (Bailian Provider)
实现阿里云百炼模型的 API 调用。

百炼 API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。
百炼 API 文档：https://help.aliyun.com/document_detail/2712195.html
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability
from app.abstraction.messages import Message, MessageRole
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk


class BailianProvider(OpenAIProvider):
    """
    百炼供应商实现
    
    阿里云百炼是一个 AI 模型服务平台，提供多种大语言模型的 API 调用。
    百炼 API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。
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
    
    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备百炼请求数据
        
        复用 OpenAI 格式，添加百炼特有参数。
        
        Args:
            request: 对话请求对象
        
        Returns:
            百炼请求字典
        """
        # 复用父类 OpenAI 格式
        data = super().prepare_request(request)
        
        # 百炼特有参数从 metadata 中提取
        if "enable_search" in request.metadata:
            data["enable_search"] = request.metadata["enable_search"]
        
        return data
    
    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析百炼响应数据
        
        复用 OpenAI 格式解析，处理百炼特有字段。
        
        Args:
            response_data: 响应数据
            model: 模型名称
        
        Returns:
            对话响应对象
        """
        # 复用父类 OpenAI 格式解析
        response = super().parse_response(response_data, model)
        response.provider = self.PROVIDER_TYPE
        
        # 处理百炼特有的 reasoning_content
        for i, choice_data in enumerate(response_data.get("choices", [])):
            message_data = choice_data.get("message", {})
            if "reasoning_content" in message_data:
                response.choices[i].reasoning_content = message_data["reasoning_content"]
        
        # 处理百炼特有的 cache tokens
        usage_data = response_data.get("usage", {})
        if "cache_read_tokens" in usage_data:
            response.usage.cache_read_tokens = usage_data["cache_read_tokens"]
        if "cache_write_tokens" in usage_data:
            response.usage.cache_write_tokens = usage_data["cache_write_tokens"]
        
        return response
    
    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """
        执行流式对话请求
        
        复用 OpenAI 流式处理，添加百炼特有参数。
        
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
        
        url = f"{self.config.base_url}/chat/completions"
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        
        try:
            with self.client.stream("POST", url, json=request_data) as response:
                # Check for error status before streaming
                if response.status_code >= 400:
                    # Read the error response and raise with details
                    error_text = ""
                    for chunk in response.iter_bytes():
                        if chunk:
                            error_text += chunk.decode('utf-8')
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(f"Bailian API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        raise RuntimeError(f"Bailian API error ({response.status_code}): {error_text}")
                
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
        
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Bailian streaming API error: {str(e)}")
    
    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """
        解析流式响应块
        
        复用 OpenAI 格式，处理百炼特有字段。
        
        Args:
            data: 响应数据
            response_id: 响应 ID
            model: 模型名称
        
        Returns:
            流式响应块，如果无效返回 None
        """
        # 复用父类解析
        chunk = super()._parse_stream_chunk(data, response_id, model)
        
        if chunk:
            # 处理百炼特有的 reasoning_content
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "reasoning_content" in delta:
                    chunk.delta_reasoning_content = delta["reasoning_content"]
        
        return chunk
    
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
        self._sync_provider = None
    
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
    
    @property
    def sync_provider(self) -> BailianProvider:
        """获取同步供应商实例"""
        if self._sync_provider is None:
            self._sync_provider = BailianProvider(self.config)
        return self._sync_provider
    
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        异步执行对话请求
        
        Args:
            request: 对话请求对象
        
        Returns:
            对话响应对象
        """
        return self.sync_provider.chat(request)
    
    async def stream_chat(self, request: ChatRequest):
        """
        异步执行流式对话请求
        
        Args:
            request: 对话请求对象
        
        Yields:
            流式响应块
        """
        for chunk in self.sync_provider.stream_chat(request):
            yield chunk
    
    async def close(self):
        """关闭异步客户端连接"""
        if self._sync_provider:
            self._sync_provider.close()
            self._sync_provider = None