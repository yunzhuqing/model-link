"""
腾讯云 TencentLive (AIGC Model Hub) 供应商基础实现 (TencentLive Provider)

仅支持图像生成（/v1/images/generations 与 /v1/images/edits），通过腾讯云
AIGC Model Hub 的 Gemini 兼容接口 ``/v1/wand/gem-image/generation/flex``
完成，兼容文生图、图生图（base64 / URL）。
"""
from typing import Optional, List, Dict, Any, AsyncGenerator
import time

from ..base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from .image_generation import (
    TENCENTLIVE_IMAGE_MODELS,
    TENCENTLIVE_DEFAULT_BASE_URL,
    is_tencentlive_image_model,
    has_image_generation_tool,
    execute_tencentlive_image_generation,
    stream_image_generation,
)


class TencentLiveProvider(BaseProvider):
    """
    腾讯云 TencentLive (AIGC Model Hub) 供应商实现

    使用 Gemini 兼容接口进行 nano 图像生成，支持：
    - 文生图（text → image）
    - 图生图（base64 / URL 参考图 → 编辑）

    配置:
        base_url: AIGC Model Hub 域名
        api_key: X-Api-Key 密钥
    """

    PROVIDER_TYPE: str = "tencentlive"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.VISION,
    ]

    # 默认 API 基础 URL（腾讯云 AIGC Model Hub）
    DEFAULT_BASE_URL = TENCENTLIVE_DEFAULT_BASE_URL

    # 支持的模型列表（nano-banana 系列，模型名直接透传）
    SUPPORTED_MODELS = {
        "gemini-2.5-flash-image": {
            "description": "Gemini 2.5 Flash Image — 图像生成模型（Google nano-banana）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        "gemini-3-pro-image-preview": {
            "description": "Gemini 3 Pro Image Preview — 图像生成模型（Google nano-banana-pro）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        "gemini-3.1-flash-image-preview": {
            "description": "Gemini 3.1 Flash Image Preview — 图像生成模型（Google nano-banana-2）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        "gemini-3.1-flash-image": {
            "description": "Gemini 3.1 Flash Image — 图像生成模型（Google nano-banana-2）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化 TencentLive 供应商

        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        super().__init__(config)

    # ==================== 图像生成检测 ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model is a TencentLive image generation model."""
        return is_tencentlive_image_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_image_generation_tool(request)

    # ==================== 非流式接口 ====================

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行图像生成请求

        如果模型是图像生成模型或请求包含 image_generation 工具，
        则走 TencentLive Gemini 兼容接口路径。

        Args:
            request: 对话请求对象

        Returns:
            图像生成响应对象

        Raises:
            ValueError: 请求验证失败或模型不受支持
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if not (self.is_image_generation_model(request.model) or self._has_image_generation_tool(request)):
            raise ValueError(
                f"TencentLive provider only supports image generation models: "
                f"{', '.join(TENCENTLIVE_IMAGE_MODELS)}"
            )

        return await execute_tencentlive_image_generation(
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
        执行流式图像生成请求

        TencentLive 接口本身非流式，本方法将完整结果转换为
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
                f"TencentLive provider only supports image generation models: "
                f"{', '.join(TENCENTLIVE_IMAGE_MODELS)}"
            )

        async for chunk in stream_image_generation(self.chat, request):
            yield chunk

    # ==================== 模型信息 ====================

    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型"""
        return is_tencentlive_image_model(model)

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
            "description": f"TencentLive image generation model: {model}",
            "context_size": 0,
            "supports_vision": True,
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
                "owned_by": "tencentlive",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 0),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
