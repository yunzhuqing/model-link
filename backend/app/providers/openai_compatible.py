"""
OpenAI-compatible provider implementation.
For providers that implement the OpenAI API format (vLLM, Ollama, local LLMs, etc.)
"""
import json
from typing import Optional, List, Dict, Any, AsyncIterator
import httpx
import time

from .base import BaseProvider, ProviderConfig
from .openai_provider import OpenAIProvider
from ..abstraction.messages import Message
from ..abstraction.tools import Tool
from ..abstraction.chat import (
    ChatCompletionRequest, ChatCompletionResponse, ChatChoice, Usage, ModelInfo, FinishReason
)
from ..abstraction.streaming import StreamChunk


class OpenAICompatibleProvider(OpenAIProvider):
    """
    OpenAI-compatible provider for self-hosted models.
    Works with vLLM, Ollama, LM Studio, and other OpenAI-compatible APIs.
    """
    
    def __init__(self, config: ProviderConfig, provider_name: str = "openai_compatible"):
        # Don't call super().__init__ because we need custom initialization
        self.config = config
        self.provider_name = provider_name
        self.base_url = config.base_url or "http://localhost:8000/v1"
        self.client = httpx.AsyncClient(
            timeout=config.timeout,
            headers=self._get_default_headers()
        )
        self._models_cache: Optional[List[ModelInfo]] = None
    
    @property
    def name(self) -> str:
        return self.provider_name
    
    @property
    def supported_features(self) -> List[str]:
        return [
            "chat_completions",
            "streaming",
            "tools",
            "vision",
            "function_calling"
        ]
    
    def _get_default_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json"
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers
    
    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """Get information about a specific model"""
        # For self-hosted models, return generic info
        return ModelInfo(
            id=model_name,
            name=model_name,
            provider=self.provider_name,
            context_size=4096,  # Default, should be configured
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        )
    
    async def list_models(self) -> List[ModelInfo]:
        """List available models from the API"""
        if self._models_cache:
            return self._models_cache
        
        try:
            response = await self.client.get(f"{self.base_url}/models")
            response.raise_for_status()
            data = response.json()
            
            models = []
            for model_data in data.get("data", []):
                model_id = model_data.get("id", "")
                models.append(ModelInfo(
                    id=model_id,
                    name=model_id,
                    provider=self.provider_name,
                    context_size=4096,
                    supports_vision=False,
                    supports_audio=False,
                    supports_video=False,
                    supports_tools=True,
                    supports_streaming=True
                ))
            
            self._models_cache = models
            return models
        except Exception:
            return []


class OllamaProvider(OpenAICompatibleProvider):
    """
    Ollama-specific provider.
    Ollama has an OpenAI-compatible API at /v1 endpoint.
    """
    
    DEFAULT_BASE_URL = "http://localhost:11434/v1"
    
    def __init__(self, config: ProviderConfig):
        config.base_url = config.base_url or self.DEFAULT_BASE_URL
        super().__init__(config, "ollama")
    
    async def list_models(self) -> List[ModelInfo]:
        """List available models from Ollama"""
        try:
            # Ollama has its own API for listing models
            response = await self.client.get(
                f"{self.base_url.replace('/v1', '')}/api/tags"
            )
            response.raise_for_status()
            data = response.json()
            
            models = []
            for model_data in data.get("models", []):
                model_id = model_data.get("name", "")
                # Parse model info
                size = model_data.get("size", 0)
                detail = model_data.get("details", {})
                
                models.append(ModelInfo(
                    id=model_id,
                    name=model_id,
                    provider="ollama",
                    context_size=detail.get("parameter_size", "unknown"),
                    supports_vision="vision" in model_id.lower(),
                    supports_audio=False,
                    supports_video=False,
                    supports_tools=True,
                    supports_streaming=True
                ))
            
            return models
        except Exception:
            return []


class VLLMProvider(OpenAICompatibleProvider):
    """
    vLLM-specific provider.
    vLLM provides an OpenAI-compatible API.
    """
    
    def __init__(self, config: ProviderConfig):
        config.base_url = config.base_url or "http://localhost:8000/v1"
        super().__init__(config, "vllm")
    
    async def list_models(self) -> List[ModelInfo]:
        """List available models from vLLM"""
        try:
            response = await self.client.get(f"{self.base_url}/models")
            response.raise_for_status()
            data = response.json()
            
            models = []
            for model_data in data.get("data", []):
                model_id = model_data.get("id", "")
                models.append(ModelInfo(
                    id=model_id,
                    name=model_id,
                    provider="vllm",
                    context_size=4096,
                    supports_vision=False,
                    supports_audio=False,
                    supports_video=False,
                    supports_tools=True,
                    supports_streaming=True
                ))
            
            return models
        except Exception:
            return []


class DeepSeekProvider(OpenAICompatibleProvider):
    """
    DeepSeek API provider.
    Uses OpenAI-compatible API format.
    """
    
    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
    
    MODELS = {
        "deepseek-chat": ModelInfo(
            id="deepseek-chat",
            name="DeepSeek Chat",
            provider="deepseek",
            context_size=64000,
            input_price=0.14,
            output_price=0.28,
            cache_creation_price=0.014,
            cache_hit_price=0.014,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "deepseek-reasoner": ModelInfo(
            id="deepseek-reasoner",
            name="DeepSeek Reasoner",
            provider="deepseek",
            context_size=64000,
            input_price=0.55,
            output_price=2.19,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=False,
            supports_streaming=True
        ),
    }
    
    def __init__(self, config: ProviderConfig):
        config.base_url = config.base_url or self.DEFAULT_BASE_URL
        super().__init__(config, "deepseek")
    
    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """Get information about a specific model"""
        if model_name in self.MODELS:
            return self.MODELS[model_name]
        return super().get_model_info(model_name)


class MoonshotProvider(OpenAICompatibleProvider):
    """
    Moonshot (Kimi) API provider.
    Uses OpenAI-compatible API format.
    """
    
    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
    
    MODELS = {
        "moonshot-v1-8k": ModelInfo(
            id="moonshot-v1-8k",
            name="Moonshot V1 8K",
            provider="moonshot",
            context_size=8192,
            input_price=12.0,
            output_price=12.0,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "moonshot-v1-32k": ModelInfo(
            id="moonshot-v1-32k",
            name="Moonshot V1 32K",
            provider="moonshot",
            context_size=32768,
            input_price=24.0,
            output_price=24.0,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "moonshot-v1-128k": ModelInfo(
            id="moonshot-v1-128k",
            name="Moonshot V1 128K",
            provider="moonshot",
            context_size=131072,
            input_price=60.0,
            output_price=60.0,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
    }
    
    def __init__(self, config: ProviderConfig):
        config.base_url = config.base_url or self.DEFAULT_BASE_URL
        super().__init__(config, "moonshot")
    
    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """Get information about a specific model"""
        if model_name in self.MODELS:
            return self.MODELS[model_name]
        return super().get_model_info(model_name)


class ZhipuProvider(OpenAICompatibleProvider):
    """
    Zhipu AI (GLM) API provider.
    Uses OpenAI-compatible API format.
    """
    
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    
    MODELS = {
        "glm-4": ModelInfo(
            id="glm-4",
            name="GLM-4",
            provider="zhipu",
            context_size=128000,
            input_price=100.0,
            output_price=100.0,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "glm-4-flash": ModelInfo(
            id="glm-4-flash",
            name="GLM-4 Flash",
            provider="zhipu",
            context_size=128000,
            input_price=1.0,
            output_price=1.0,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "glm-4v": ModelInfo(
            id="glm-4v",
            name="GLM-4V",
            provider="zhipu",
            context_size=2000,
            input_price=50.0,
            output_price=50.0,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=False,
            supports_streaming=True
        ),
    }
    
    def __init__(self, config: ProviderConfig):
        config.base_url = config.base_url or self.DEFAULT_BASE_URL
        super().__init__(config, "zhipu")
    
    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """Get information about a specific model"""
        if model_name in self.MODELS:
            return self.MODELS[model_name]
        return super().get_model_info(model_name)