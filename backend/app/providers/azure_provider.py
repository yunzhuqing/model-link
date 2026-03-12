"""
Azure OpenAI 供应商实现 (Azure OpenAI Provider)
实现 Azure OpenAI API 的调用。
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid

from .base import BaseProvider, ProviderConfig, ProviderCapability
from .openai_provider import OpenAIProvider, parse_openai_request
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk


class AzureProvider(OpenAIProvider):
    """
    Azure OpenAI 供应商实现
    
    提供 Azure OpenAI API 的调用能力。
    Azure OpenAI 使用与 OpenAI 兼容的 API，但有以下不同：
    1. 认证方式：使用 api-key 头而不是 Bearer token
    2. URL 结构：需要包含部署名称和 API 版本
    3. 基础 URL 格式：https://{resource-name}.openai.azure.com
    """
    
    PROVIDER_TYPE: str = "azure"
    
    # Azure OpenAI 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
    ]
    
    # Azure API 版本
    DEFAULT_API_VERSION = "2025-01-01-preview"
    
    # Azure OpenAI 支持的模型列表（部署名称由用户自定义）
    SUPPORTED_MODELS = {
        "gpt-4o": {
            "description": "GPT-4o - 最先进的多模态模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4o-mini": {
            "description": "GPT-4o mini - 快速且经济的多模态模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4-turbo": {
            "description": "GPT-4 Turbo - 更快的 GPT-4",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4": {
            "description": "GPT-4 - 高级推理能力",
            "context_size": 8192,
            "supports_vision": False,
        },
        "gpt-35-turbo": {
            "description": "GPT-3.5 Turbo - 快速且经济",
            "context_size": 16385,
            "supports_vision": False,
        },
    }
    
    def __init__(self, config: ProviderConfig):
        """
        初始化 Azure OpenAI 供应商
        
        Args:
            config: 供应商配置
                - base_url: Azure 资源 URL (e.g., https://your-resource.openai.azure.com)
                - api_key: Azure API 密钥
                - extra_config: 可包含 'api_version' 和 'deployment_name'
        """
        # 设置默认 API 版本
        if not config.extra_config:
            config.extra_config = {}
        
        if 'api_version' not in config.extra_config:
            config.extra_config['api_version'] = self.DEFAULT_API_VERSION
        
        # 不设置默认 base_url，用户必须提供
        super().__init__(config)
    
    # Azure 使用与 OpenAI 相同的 get_headers (Bearer token)
    # 继承自 OpenAIProvider，无需重写
    
    @property
    def api_version(self) -> str:
        """获取 API 版本"""
        return self.config.extra_config.get('api_version', self.DEFAULT_API_VERSION)
    
    def get_chat_url(self, deployment_name: str) -> str:
        """
        获取聊天 API URL
        
        Args:
            deployment_name: Azure 部署名称
        
        Returns:
            完整的 API URL
        """
        base_url = self.config.base_url.rstrip('/')
        return f"{base_url}/openai/deployments/{deployment_name}/chat/completions?api-version={self.api_version}"
    
    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型（部署名称）"""
        return True  # Azure 支持用户自定义部署名称
    
    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """获取模型信息"""
        # Azure 部署名称由用户自定义，所以总是返回基本信息
        return {
            "description": f"Azure deployment: {model}",
            "context_size": 8192,
            "supports_vision": True,  # 假设支持
        }
    
    def chat(self, request: ChatRequest) -> ChatResponse:
        """执行对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)
        
        request_data = self.prepare_request(request)
        request_data["stream"] = False
        
        # 使用模型名称作为部署名称
        deployment_name = request.model
        url = self.get_chat_url(deployment_name)
        
        # Debug: print request details
        print(f"[Azure Debug] URL: {url}")
        print(f"[Azure Debug] Headers: {self.get_headers()}")
        print(f"[Azure Debug] Request Data: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
        
        try:
            response = self.client.post(url, json=request_data)
            print(f"[Azure Debug] Response Status: {response.status_code}")
            
            if response.status_code >= 400:
                # Try to parse error response
                try:
                    error_data = response.json()
                    print(f"[Azure Debug] Error Response: {json.dumps(error_data, ensure_ascii=False, indent=2)}")
                    raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    raise RuntimeError(f"Azure API error ({response.status_code}): {response.text}")
            
            response.raise_for_status()
            
            response_data = response.json()
            return self.parse_response(response_data, request.model)
        
        except RuntimeError:
            raise
        except Exception as e:
            print(f"[Azure Debug] Error: {str(e)}")
            raise RuntimeError(f"Azure OpenAI API error: {str(e)}")
    
    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)
        
        request_data = self.prepare_request(request)
        request_data["stream"] = True
        
        # 使用模型名称作为部署名称
        deployment_name = request.model
        url = self.get_chat_url(deployment_name)
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
                    print(f"[Azure Debug] Stream Error Response: {error_text}")
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        raise RuntimeError(f"Azure API error ({response.status_code}): {error_text}")
                
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
            raise RuntimeError(f"Azure OpenAI streaming API error: {str(e)}")
    
    def list_models(self) -> List[Dict[str, Any]]:
        """列出支持的模型（Azure 需要用户自己配置部署）"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "azure",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
            })
        return models


# 导出解析函数（与 OpenAI 格式相同）
__all__ = ['AzureProvider', 'parse_openai_request']