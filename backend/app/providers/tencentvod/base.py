"""
腾讯云点播 AI 供应商基础实现 (TencentVOD Base Provider)
实现腾讯云点播 (VOD) AI 大模型的 API 调用。

腾讯云点播 AI API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。

配置说明:
- base_url: API 基础 URL（默认 https://text-aigc.vod-qcloud.com/v1）
- api_key:  聊天模型使用点播 AI API Key；
            图像/视频生成模型使用 "SecretId:SecretKey" 格式（腾讯云主账号/子账号密钥）

图像生成说明:
- 通过腾讯云点播 CreateAigcImageTask + DescribeTaskDetail API 实现
- 兼容 /v1/responses image_generation 工具
- extra_config["sub_app_id"]: 点播子应用 ID（可选）

视频生成说明:
- 通过腾讯云点播 CreateAigcVideoTask + DescribeTaskDetail API 实现
- 兼容 /v1/responses video_generation 工具
- 支持 Kling（GV）、HunyuanVideo 等模型

API 文档：
  聊天: https://text-aigc.vod-qcloud.com
  图像: https://cloud.tencent.com/document/product/266/73185
  视频: https://cloud.tencent.com/document/product/266/
"""
import json
import time
import uuid
from typing import Any, Dict, Generator, List, Optional

from ..openai_provider import OpenAIProvider
from ..base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from .image_generation import (
    is_tencentvod_image_model,
    has_image_generation_tool,
    execute_tencentvod_image_generation,
    stream_image_generation,
)
from .video_generation import (
    is_tencentvod_video_model,
    has_video_generation_tool,
    execute_tencentvod_video_generation,
    stream_video_generation,
)


class TencentVODProvider(OpenAIProvider):
    """
    腾讯云点播 AI 供应商实现

    腾讯云点播 AI 提供兼容 OpenAI chat/completions 格式的接口，
    继承 OpenAIProvider 直接复用其请求/响应逻辑。

    额外支持:
    - 腾讯云点播 AI 图像生成（GEM / Mingmou 等模型）
      通过 CreateAigcImageTask + DescribeTaskDetail API 实现，
      兼容 /v1/responses image_generation 工具。
    - 腾讯云点播 AI 视频生成（Kling / HunyuanVideo 等模型）
      通过 CreateAigcVideoTask + DescribeTaskDetail API 实现，
      兼容 /v1/responses video_generation 工具。

    配置:
        base_url:               https://text-aigc.vod-qcloud.com/v1（默认）
        api_key（聊天模型）:     腾讯云点播 AI API Key
        api_key（图像/视频生成）: "SecretId:SecretKey" 格式
        extra_config.sub_app_id: 点播子应用 ID（图像/视频生成可选）
    """

    PROVIDER_TYPE: str = "tencentvod"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
    ]

    # 腾讯云点播 AI 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://text-aigc.vod-qcloud.com/v1"

    # 腾讯云点播 AI 支持的模型列表
    SUPPORTED_MODELS = {
        "hunyuan-turbos-latest": {
            "description": "混元 Turbos Latest - 腾讯最新旗舰大模型",
            "context_size": 256000,
            "supports_vision": True,
        },
        "hunyuan-turbos-20250416": {
            "description": "混元 Turbos 20250416 - 腾讯旗舰大模型（固定版本）",
            "context_size": 256000,
            "supports_vision": True,
        },
        "hunyuan-turbo-latest": {
            "description": "混元 Turbo Latest - 高性能推理模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "hunyuan-pro": {
            "description": "混元 Pro - 高质量对话模型",
            "context_size": 128000,
            "supports_vision": False,
        },
        "hunyuan-lite": {
            "description": "混元 Lite - 轻量高速对话模型",
            "context_size": 256000,
            "supports_vision": False,
        },
        "hunyuan-standard": {
            "description": "混元 Standard - 标准对话模型",
            "context_size": 32000,
            "supports_vision": False,
        },
        "hunyuan-standard-256k": {
            "description": "混元 Standard 256K - 超长上下文对话模型",
            "context_size": 256000,
            "supports_vision": False,
        },
        "hunyuan-vision": {
            "description": "混元 Vision - 多模态视觉理解模型",
            "context_size": 8000,
            "supports_vision": True,
        },
        # 图像生成模型
        "GEM-2.5": {
            "description": "腾讯云点播 GEM 2.5 图像生成模型",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        "Mingmou-4.0": {
            "description": "腾讯云点播明眸 4.0 图像生成模型",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        # 视频生成模型 — 可灵 Kling (ModelName=Kling)
        "kling-v3-omni": {
            "description": "可灵 v3 旗舰版 Omni 视频生成模型（Kling 3.0-Omni）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v3-omini": {
            "description": "可灵 v3 Omini 视频生成模型（Kling 3.0-Omini）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v3": {
            "description": "可灵 v3 标准版视频生成模型（Kling 3.0）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v2.1-pro": {
            "description": "可灵 v2.1 Pro 视频生成模型（Kling 2.1-Pro）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v2.1-standard": {
            "description": "可灵 v2.1 Standard 视频生成模型（Kling 2.1-Standard）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v1.6-pro": {
            "description": "可灵 v1.6 Pro 视频生成模型（Kling 1.6-Pro）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v1.6-standard": {
            "description": "可灵 v1.6 Standard 视频生成模型（Kling 1.6-Standard）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v1.5-pro": {
            "description": "可灵 v1.5 Pro 视频生成模型（Kling 1.5-Pro）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        # 视频生成模型 — Google Veo (ModelName=GV)
        "veo-3.1-generate-001": {
            "description": "Google Veo 3.1 视频生成模型（GV 3.1）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "veo-3.1-fast-generate-001": {
            "description": "Google Veo 3.1 Fast 视频生成模型（GV 3.1-fast）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        # 视频生成模型 — 混元视频 Hunyuan
        "hy-video-v1.0": {
            "description": "混元视频 v1.0 视频生成模型（Hunyuan 1.0）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化腾讯云点播 AI 供应商

        Args:
            config: 供应商配置
        """
        # 如果未指定 base_url，使用默认值
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        super().__init__(config)

    # ==================== 图像/视频生成检测 ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model is a TencentVOD image generation model."""
        return is_tencentvod_image_model(model)

    def is_video_generation_model(self, model: str) -> bool:
        """Check if the model is a TencentVOD video generation model."""
        return is_tencentvod_video_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_image_generation_tool(request)

    def _has_video_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains a video_generation tool."""
        return has_video_generation_tool(request)

    def _get_sub_app_id(self, request: ChatRequest) -> Optional[int]:
        """
        Resolve SubAppId from request metadata or provider extra_config.

        Priority: request.metadata["sub_app_id"] > extra_config["sub_app_id"]
        """
        val = (
            request.metadata.get("sub_app_id")
            or self.config.extra_config.get("sub_app_id")
            or self.config.extra_config.get("app_id")
        )
        return int(val) if val is not None else None

    def _get_image_api_key(self) -> str:
        """
        Build the "SecretId:SecretKey" credential string used by image generation.

        Prefers secret_id / secret_key stored in extra_config (the new canonical
        location).  Falls back to the raw api_key value so that existing
        providers that stored the combined string there still work.
        """
        extra = self.config.extra_config or {}
        secret_id = extra.get("secret_id", "").strip()
        secret_key = extra.get("secret_key", "").strip()
        if secret_id and secret_key:
            return f"{secret_id}:{secret_key}"
        # Fallback: api_key may already contain "SecretId:SecretKey"
        return self.config.api_key or ""

    # ==================== 非流式接口 ====================

    def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行对话/图像生成/视频生成请求

        优先级:
        1. 如果模型是视频生成模型或请求包含 video_generation 工具 → 视频生成路径
        2. 如果模型是图像生成模型或请求包含 image_generation 工具 → 图像生成路径
        3. 否则走 OpenAI 兼容格式的对话路径

        Args:
            request: 对话请求对象

        Returns:
            对话/图像/视频生成响应对象
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_video_generation_model(request.model) or self._has_video_generation_tool(request):
            return execute_tencentvod_video_generation(
                api_key=self._get_image_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                sub_app_id=self._get_sub_app_id(request),
            )

        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            return execute_tencentvod_image_generation(
                api_key=self._get_image_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                sub_app_id=self._get_sub_app_id(request),
            )

        # 标准对话路径 (OpenAI 兼容)
        return super().chat(request)

    # ==================== 流式接口 ====================

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """
        执行流式对话/图像生成/视频生成请求

        优先级:
        1. 如果模型是视频生成模型或请求包含 video_generation 工具 → 视频生成路径
        2. 如果模型是图像生成模型或请求包含 image_generation 工具 → 图像生成路径
        3. 否则走 OpenAI 兼容格式的流式对话路径

        Args:
            request: 对话请求对象

        Yields:
            流式响应块
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_video_generation_model(request.model) or self._has_video_generation_tool(request):
            yield from stream_video_generation(self.chat, request)
            return

        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            yield from stream_image_generation(self.chat, request)
            return

        # 标准流式对话路径 (OpenAI 兼容)
        yield from super().stream_chat(request)

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
            "description": f"腾讯云点播 AI 模型: {model}",
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
                "owned_by": "tencent",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 128000),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
