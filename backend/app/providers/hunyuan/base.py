"""
混元 AI 供应商基础实现 (Hunyuan Base Provider)

实现混元 3D 生成 API 调用。

配置说明:
- api_key: "SecretId:SecretKey" 格式（腾讯云主账号/子账号密钥）

3D 生成说明:
- 通过腾讯云混元 3D API SubmitHunyuanTo3DRapidJob / SubmitHunyuanTo3DProJob
  + QueryHunyuanTo3DRapidJob / QueryHunyuanTo3DProJob 实现
- 兼容 /v1/responses 3d_generation 工具
- Rapid 模型: hunyuan-3d-rapid
- Pro   模型: hunyuan-3d-pro

API 文档:
  https://cloud.tencent.com/document/product/1684/
"""
import time
from typing import Any, Dict, Generator, List, Optional

from ..base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from .threed_generation import (
    HUNYUAN3D_API_REGION,
    is_hunyuan3d_model,
    has_threed_generation_tool,
    execute_hunyuan3d_generation,
    stream_3d_generation,
)


class HunyuanProvider(BaseProvider):
    """
    混元 AI 供应商实现

    目前主要支持混元 3D 生成功能：
    - 通过 SubmitHunyuanTo3DRapidJob / SubmitHunyuanTo3DProJob 提交任务
    - 通过 QueryHunyuanTo3DRapidJob / QueryHunyuanTo3DProJob 轮询结果
    - 兼容 /v1/responses 3d_generation 工具

    配置:
        api_key: "SecretId:SecretKey" 格式
    """

    PROVIDER_TYPE: str = "hunyuan"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
    ]

    # 混元 3D 支持的模型列表
    SUPPORTED_MODELS = {
        # ── Rapid 系列 ──────────────────────────────────────────────────────
        "hunyuan-3d-rapid": {
            "description": "混元 3D Rapid - 快速 3D 生成（从图片或文本生成 3D 模型）",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": False,
        },
        "hy-3d-express": {
            "description": "混元 3D Express - 快速 3D 生成（Rapid 系列，API action: SubmitHunyuanTo3DRapidJob）",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": False,
        },
        # ── Pro 系列 ────────────────────────────────────────────────────────
        "hunyuan-3d-pro": {
            "description": "混元 3D Pro - 高质量 3D 生成（支持 LowPoly / Geometry / Sketch 等生成类型）",
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
            "description": "混元 3D hy-3d-3.0 - Pro 系列，API Model=3.1（注意：model 名与 API Model 字段有差异）",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": True,
            "api_model": "3.1",
        },
        "hy-3d-3.1": {
            "description": "混元 3D hy-3d-3.1 - Pro 系列，API Model=3.0（注意：model 名与 API Model 字段有差异）",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
            "is_pro": True,
            "api_model": "3.0",
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化混元 AI 供应商

        Args:
            config: 供应商配置
        """
        super().__init__(config)

    # ==================== 3D 生成检测 ====================

    def is_3d_generation_model(self, model: str) -> bool:
        """Check if the model is a Hunyuan 3D generation model."""
        return is_hunyuan3d_model(model)

    def _has_3d_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains a 3d_generation tool."""
        return has_threed_generation_tool(request)

    def _get_api_key(self) -> str:
        """
        Return 'SecretId:SecretKey' credential string.

        Prefers secret_id / secret_key stored in extra_config.
        Falls back to the raw api_key value.
        """
        extra = self.config.extra_config or {}
        secret_id = extra.get("secret_id", "").strip()
        secret_key = extra.get("secret_key", "").strip()
        if secret_id and secret_key:
            return f"{secret_id}:{secret_key}"
        return self.config.api_key or ""

    def _get_region(self) -> str:
        """
        Return the region for the Hunyuan 3D API.

        Reads 'region' from extra_config, falls back to default ap-guangzhou.
        """
        extra = self.config.extra_config or {}
        return extra.get("region", "").strip() or HUNYUAN3D_API_REGION

    # ==================== 非流式接口 ====================

    def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行 3D 生成请求。

        如果模型是 3D 生成模型或请求包含 3d_generation 工具 → 3D 生成路径。

        Args:
            request: 对话请求对象

        Returns:
            3D 生成响应对象
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_3d_generation_model(request.model) or self._has_3d_generation_tool(request):
            return execute_hunyuan3d_generation(
                api_key=self._get_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                region=self._get_region(),
            )

        raise ValueError(
            f"HunyuanProvider: model '{request.model}' is not a supported 3D generation model. "
            f"Use one of: {list(self.SUPPORTED_MODELS.keys())}"
        )

    # ==================== 流式接口 ====================

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """
        执行流式 3D 生成请求。

        Args:
            request: 对话请求对象

        Yields:
            流式响应块
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_3d_generation_model(request.model) or self._has_3d_generation_tool(request):
            yield from stream_3d_generation(self.chat, request)
            return

        raise ValueError(
            f"HunyuanProvider: model '{request.model}' is not a supported 3D generation model. "
            f"Use one of: {list(self.SUPPORTED_MODELS.keys())}"
        )

    # ==================== 模型信息 ====================

    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型"""
        return is_hunyuan3d_model(model)

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
            "description": f"混元 3D 模型: {model}",
            "context_size": 0,
            "supports_vision": True,
            "is_3d_model": True,
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
                "context_size": info.get("context_size", 0),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
