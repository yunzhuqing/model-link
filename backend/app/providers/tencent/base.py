"""
腾讯 AI 供应商基础实现 (Tencent Provider)

合并了混元 3D 生成 (Hunyuan) 和 MPS 智能擦除 (MPS) 两个子模块，
根据模型名称或工具调用自动路由。

配置说明:
- api_key: "SecretId:SecretKey" 格式（腾讯云主账号/子账号密钥）

子模块:
- hunyuan/threed_generation: 混元 3D 生成（SubmitHunyuanTo3DRapidJob /
  SubmitHunyuanTo3DProJob + 轮询，兼容 /v1/responses 3d_generation 工具）
- mps/video_erase:          MPS 智能擦除（ProcessMedia + DescribeTaskDetail
  轮询，兼容 /v1/responses video_erase 工具）
"""
import time
from typing import Any, Dict, Generator, List, Optional

from ..base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk

from .hunyuan.threed_generation import (
    HUNYUAN3D_API_REGION,
    is_hunyuan3d_model,
    has_threed_generation_tool,
    execute_hunyuan3d_generation,
    stream_3d_generation,
)
from .mps.video_erase import (
    is_mps_video_erase_model,
    has_video_erase_tool,
    execute_mps_video_erase,
    stream_video_erase,
)


class TencentProvider(BaseProvider):
    """
    腾讯 AI 供应商实现

    根据模型名称或工具调用自动路由:
    - 混元 3D 模型或 3d_generation 工具 → 混元 3D 生成
    - MPS 擦除模型或 video_erase 工具   → MPS 智能擦除

    配置:
        api_key: "SecretId:SecretKey" 格式
        extra_config.secret_id / secret_key: 也可分别提供 SecretId 和 SecretKey
    """

    PROVIDER_TYPE: str = "tencent"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
    ]

    SUPPORTED_MODELS = {
        # ── 混元 3D Rapid 系列 ─────────────────────────────────
        "hunyuan-3d-rapid": {
            "description": "混元 3D Rapid - 快速 3D 生成（从图片或文本生成 3D 模型）",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": False,
        },
        "hy-3d-express": {
            "description": "混元 3D Express - 快速 3D 生成（Rapid 系列）",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": False,
        },
        # ── 混元 3D Pro 系列 ───────────────────────────────────
        "hunyuan-3d-pro": {
            "description": "混元 3D Pro - 高质量 3D 生成",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": True,
            "api_model": None,
        },
        "hunyuan-3d-3.0-pro": {
            "description": "混元 3D 3.0 Pro - Pro 系列，API Model=3.0",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": True,
            "api_model": "3.0",
        },
        "hunyuan-3d-3.1-pro": {
            "description": "混元 3D 3.1 Pro - Pro 系列，API Model=3.1",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": True,
            "api_model": "3.1",
        },
        "hy-3d-3.0": {
            "description": "混元 3D hy-3d-3.0 - Pro 系列",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": True,
            "api_model": "3.1",
        },
        "hy-3d-3.1": {
            "description": "混元 3D hy-3d-3.1 - Pro 系列",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": True,
            "api_model": "3.0",
        },
        # ── MPS 智能擦除 ──────────────────────────────────────
        "mps-erase-subtitle-standard": {
            "description": "MPS 智能擦除 - 标准字幕擦除模型",
            "context_size": 0,
            "supports_vision": True,
            "is_video_erase_model": True,
        },
        "mps-smarterase": {
            "description": "MPS 智能擦除 - 通用擦除模型",
            "context_size": 0,
            "supports_vision": True,
            "is_video_erase_model": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

    # ── 3D 生成检测 ────────────────────────────────────────────

    def is_3d_generation_model(self, model: str) -> bool:
        return is_hunyuan3d_model(model)

    def _has_3d_generation_tool(self, request: ChatRequest) -> bool:
        return has_threed_generation_tool(request)

    # ── 视频擦除检测 ──────────────────────────────────────────

    def is_video_erase_model(self, model: str) -> bool:
        return is_mps_video_erase_model(model)

    def _has_video_erase_tool(self, request: ChatRequest) -> bool:
        return has_video_erase_tool(request)

    # ── Credential helpers ─────────────────────────────────────

    def _get_api_key(self) -> str:
        """Return 'SecretId:SecretKey' credential string."""
        extra = self.config.extra_config or {}
        secret_id = extra.get("secret_id", "").strip()
        secret_key = extra.get("secret_key", "").strip()
        if secret_id and secret_key:
            return f"{secret_id}:{secret_key}"
        return self.config.api_key or ""

    def _get_region(self) -> str:
        """Return the region for the Hunyuan 3D API."""
        extra = self.config.extra_config or {}
        return extra.get("region", "").strip() or HUNYUAN3D_API_REGION

    # ── 路由分发 ──────────────────────────────────────────────

    def _dispatch_route(self, request: ChatRequest) -> str:
        """Determine which sub-module handles this request."""
        if self.is_3d_generation_model(request.model) or self._has_3d_generation_tool(request):
            return "hunyuan3d"
        if self.is_video_erase_model(request.model) or self._has_video_erase_tool(request):
            return "mps_video_erase"
        raise ValueError(
            f"TencentProvider: model '{request.model}' is not supported. "
            f"Supported models: {list(self.SUPPORTED_MODELS.keys())}"
        )

    # ── Non-streaming ──────────────────────────────────────────

    def chat(self, request: ChatRequest) -> ChatResponse:
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        route = self._dispatch_route(request)

        if route == "hunyuan3d":
            return execute_hunyuan3d_generation(
                api_key=self._get_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                region=self._get_region(),
                tracer=self.tracer,
            )

        if route == "mps_video_erase":
            return execute_mps_video_erase(
                api_key=self._get_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                extra_config=self.config.extra_config,
                tracer=self.tracer,
            )

        raise ValueError(f"TencentProvider: unknown route '{route}'")

    # ── Streaming ──────────────────────────────────────────────

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        route = self._dispatch_route(request)

        if route == "hunyuan3d":
            yield from stream_3d_generation(self.chat, request)
            return

        if route == "mps_video_erase":
            yield from stream_video_erase(self.chat, request)
            return

        raise ValueError(f"TencentProvider: unknown route '{route}'")

    # ── 模型信息 ──────────────────────────────────────────────

    def supports_model(self, model: str) -> bool:
        return is_hunyuan3d_model(model) or is_mps_video_erase_model(model)

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        return {
            "description": f"腾讯 AI 模型: {model}",
            "context_size": 0,
            "supports_vision": True,
        }

    def list_models(self) -> List[Dict[str, Any]]:
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "tencent",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 0),
                "supports_vision": info.get("supports_vision", False),
            })
        return models


# Backward compatibility aliases
HunyuanProvider = TencentProvider
MPSProvider = TencentProvider