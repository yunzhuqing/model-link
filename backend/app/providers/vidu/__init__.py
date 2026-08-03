"""
Vidu 供应商基础实现 (Vidu Provider)

Vidu 开放平台 (api.vidu.cn) 图像生成供应商。

通过两步异步任务 API (reference2image → tasks/{id}/creations) 生成图像，
网关模型名与 Vidu API 模型名通过 ``VIDU_MODEL_MAP`` 映射。

支持的模型列表（Vidu API 模型名）：viduq2、viduq1、viduimage-2、q3-fast、q2-pro、q2-fast

网关标准模型名对应关系：
- gpt-image-2                    → viduimage-2
- gemini-2.5-flash-image         → q2-fast
- gemini-3-pro-image-preview     → q2-pro
- gemini-3.1-flash-image-preview → q3-fast
"""
from typing import Optional, List, Dict, Any, AsyncGenerator
import time

from ..base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from .image_generation import (
    VIDU_IMAGE_MODELS,
    is_vidu_image_model,
    has_image_generation_tool,
    execute_vidu_image_generation,
    stream_image_generation,
)


class ViduProvider(BaseProvider):
    """
    Vidu 供应商实现

    仅支持图片生成（/v1/images/generations 与 /v1/images/edits），
    通过 Vidu reference2image 异步任务 API 完成。
    """

    PROVIDER_TYPE: str = "vidu"

    # Vidu 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.VISION,
    ]

    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://api.vidu.cn"

    # Vidu 支持的模型列表（网关别名 + Vidu 原生名）
    SUPPORTED_MODELS = {
        "gpt-image-2": {
            "description": "Vidu image generation model (maps to viduimage-2)",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "gemini-2.5-flash-image": {
            "description": "Vidu image generation model (maps to q2-fast)",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "gemini-3-pro-image-preview": {
            "description": "Vidu image generation model (maps to q2-pro)",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "gemini-3.1-flash-image-preview": {
            "description": "Vidu image generation model (maps to q3-fast)",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "viduq1": {
            "description": "Vidu native image generation model",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "viduq2": {
            "description": "Vidu native image generation model",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "viduimage-2": {
            "description": "Vidu native image generation model",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "q2-fast": {
            "description": "Vidu native image generation model",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "q2-pro": {
            "description": "Vidu native image generation model",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
        "q3-fast": {
            "description": "Vidu native image generation model",
            "context_size": 0, "supports_vision": True, "is_image_model": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化 Vidu 供应商

        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        super().__init__(config)

    # ==================== 图像生成检测 ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model is a Vidu image generation model."""
        return is_vidu_image_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_image_generation_tool(request)

    # ==================== 非流式接口 ====================

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行图片生成请求

        如果模型是 Vidu 图像生成模型或请求包含 image_generation 工具，
        则走 reference2image 异步任务 API 路径。

        Args:
            request: 对话请求对象

        Returns:
            图片生成响应对象

        Raises:
            ValueError: 请求验证失败或模型不受支持
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if not (self.is_image_generation_model(request.model) or self._has_image_generation_tool(request)):
            raise ValueError(
                f"Vidu provider only supports image generation models: "
                f"{', '.join(VIDU_IMAGE_MODELS)}"
            )

        return await execute_vidu_image_generation(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            model=request.model,
            messages=request.messages,
            metadata=request.metadata,
            tracer=self.tracer,
        )

    # ==================== 流式接口 ====================

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """
        执行流式图片生成请求

        Vidu 图片生成为异步轮询，本方法将结果转换为
        image_generation_call SSE 事件序列。

        Args:
            request: 对话请求对象

        Yields:
            流式响应块
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if not (self.is_image_generation_model(request.model) or self._has_image_generation_tool(request)):
            raise ValueError(
                f"Vidu provider only supports image generation models: "
                f"{', '.join(VIDU_IMAGE_MODELS)}"
            )

        async for chunk in stream_image_generation(self.chat, request):
            yield chunk

    # ==================== 模型信息 ====================

    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型"""
        return is_vidu_image_model(model)

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
            "description": f"Vidu 模型: {model}",
            "context_size": 0,
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
                "owned_by": "vidu",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 0),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
