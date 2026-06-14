"""
Mulerun 供应商基础实现 (Mulerun Provider)

Mulerun 是一个 AI 模型聚合网关，提供 OpenAI/Claude 等模型的 API 访问。

支持的模型：
- Chat: 所有 OpenAI/Claude 兼容模型（通过 /v1/chat/completions）
- Image Generation: gpt-image-2（通过专用异步轮询 API）

API:
- Chat:        POST {base_url}/chat/completions  (OpenAI 兼容格式)
- Image Gen:   POST {base_url}/gpt-image-2/generation  →  GET poll
"""
from typing import Optional, List, Dict, Any, AsyncGenerator
import json
import time
import logging

from ..base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.providers.openai_provider import OpenAIProvider
from .image_generation import (
    MULERUN_IMAGE_MODELS,
    is_mulerun_image_model,
    has_image_generation_tool,
    execute_mulerun_image_generation,
    stream_image_generation,
)


class MulerunProvider(OpenAIProvider):
    """
    Mulerun 供应商实现

    Mulerun 提供 OpenAI 兼容的 API 接口，继承 OpenAIProvider 复用代码。

    额外支持：
    - gpt-image-2 图像生成模型（通过异步轮询 API）
    """

    PROVIDER_TYPE: str = "mulerun"

    # Mulerun 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
    ]

    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://api.mulerun.com/vendors/openai/v1"

    # Mulerun 支持的模型列表
    SUPPORTED_MODELS = {
        # GPT Image 模型
        "gpt-image-2": {
            "description": "GPT Image 2 — 图像生成模型（OpenAI vendor）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        # Gemini Image 模型
        "gemini-2.5-flash-image": {
            "description": "Gemini 2.5 Flash Image — 图像生成模型（Google vendor, nano-banana）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        "gemini-3-pro-image-preview": {
            "description": "Gemini 3 Pro Image Preview — 图像生成模型（Google vendor, nano-banana-pro）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        "gemini-3.1-flash-image-preview": {
            "description": "Gemini 3.1 Flash Image Preview — 图像生成模型（Google vendor, nano-banana-2）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化 Mulerun 供应商

        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        super().__init__(config)

    # ==================== 图像生成检测 ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model is a Mulerun image generation model."""
        return is_mulerun_image_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_image_generation_tool(request)

    # ==================== 非流式接口 ====================

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行对话/图像生成请求

        如果模型是图像生成模型（gpt-image-2），则走专用异步轮询 API 路径。
        否则走 OpenAI 兼容格式的对话路径。

        Args:
            request: 对话请求对象

        Returns:
            对话/图像生成响应对象
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            return await execute_mulerun_image_generation(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                tracer=self.tracer,
            )

        # 标准对话路径
        return await super().chat(request)

    # ==================== 流式接口 ====================

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """
        执行流式对话/图像生成请求

        如果模型是图像生成模型或请求包含 image_generation 工具，则走图像生成流式路径。
        否则走 OpenAI 兼容格式的流式对话路径。

        Args:
            request: 对话请求对象

        Yields:
            流式响应块
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            async for chunk in stream_image_generation(self.chat, request):
                yield chunk
            return

        # 标准流式对话路径 (OpenAI 兼容)
        async for chunk in super().stream_chat(request):
            yield chunk

    # ==================== 模型信息 ====================

    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型（始终返回 True 以支持新模型）"""
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """
        获取模型信息

        Args:
            model: 模型名称

        Returns:
            模型信息字典
        """
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        return {
            "description": f"Mulerun 模型: {model}",
            "context_size": 128000,
            "supports_vision": False,
        }

    # ==================== 模型列表 ====================

    def list_models(self) -> List[Dict[str, Any]]:
        """列出支持的模型"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mulerun",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 0),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
