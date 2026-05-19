"""
腾讯云 MPS 智能擦除供应商实现 (MPS Smart Erase Provider)

通过腾讯云 MPS ProcessMedia API 实现视频智能擦除功能，
兼容 /v1/responses video_erase 工具。

配置说明:
- api_key: "SecretId:SecretKey" 格式（腾讯云主账号/子账号密钥）
- extra_config.cos_bucket: COS 输出 Bucket（必填）
- extra_config.cos_region: COS 区域（默认 ap-guangzhou）
- extra_config.cos_output_dir: COS 输出目录（默认 /）
- extra_config.mps_definition: MPS 模板 Definition ID（默认 303）

API 文档:
  https://cloud.tencent.com/document/product/862/
"""
import time
from typing import Any, Dict, Generator, List, Optional

from ...base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from .video_erase import (
    is_mps_video_erase_model,
    has_video_erase_tool,
    execute_mps_video_erase,
    stream_video_erase,
)


class MPSProvider(BaseProvider):
    """
    腾讯云 MPS 供应商实现

    目前主要支持智能擦除功能：
    - 通过 MPS ProcessMedia 提交 SmartEraseTask
    - 通过 DescribeTaskDetail 轮询结果
    - 兼容 /v1/responses video_erase 工具

    配置:
        api_key: "SecretId:SecretKey" 格式
        extra_config.cos_bucket: COS 输出 Bucket（必填）
        extra_config.cos_region: COS 区域
        extra_config.cos_output_dir: COS 输出目录
    """

    PROVIDER_TYPE: str = "tencentmps"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
    ]

    SUPPORTED_MODELS = {
        "erase_subtitle_standard": {
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

    # ── Model / Tool detection ──────────────────────────────────────

    def is_video_erase_model(self, model: str) -> bool:
        return is_mps_video_erase_model(model)

    def _has_video_erase_tool(self, request: ChatRequest) -> bool:
        return has_video_erase_tool(request)

    # ── Credential helpers ─────────────────────────────────────────

    def _get_api_key(self) -> str:
        """Return 'SecretId:SecretKey' credential string."""
        extra = self.config.extra_config or {}
        secret_id = extra.get("secret_id", "").strip()
        secret_key = extra.get("secret_key", "").strip()
        if secret_id and secret_key:
            return f"{secret_id}:{secret_key}"
        return self.config.api_key or ""

    # ── Non-streaming ──────────────────────────────────────────────

    def chat(self, request: ChatRequest) -> ChatResponse:
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_video_erase_model(request.model) or self._has_video_erase_tool(request):
            return execute_mps_video_erase(
                api_key=self._get_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                extra_config=self.config.extra_config,
                tracer=self.tracer,
            )

        raise ValueError(
            f"MPSProvider: model '{request.model}' is not a supported video erase model. "
            f"Use one of: {list(self.SUPPORTED_MODELS.keys())}"
        )

    # ── Streaming ──────────────────────────────────────────────────

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_video_erase_model(request.model) or self._has_video_erase_tool(request):
            yield from stream_video_erase(self.chat, request)
            return

        raise ValueError(
            f"MPSProvider: model '{request.model}' is not a supported video erase model. "
            f"Use one of: {list(self.SUPPORTED_MODELS.keys())}"
        )

    # ── Model info ─────────────────────────────────────────────────

    def supports_model(self, model: str) -> bool:
        return is_mps_video_erase_model(model)

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        return {
            "description": f"腾讯云 MPS 智能擦除模型: {model}",
            "context_size": 0,
            "supports_vision": True,
            "is_video_erase_model": True,
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