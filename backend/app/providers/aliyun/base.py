"""
阿里云供应商基础实现 (Aliyun Provider)

通过阿里云 OpenAPI (AK/SK 签名) 访问阿里云 AI 服务。

当前支持的产品:
- 视频生成 (yike, API 版本 2026-03-19):
  - SubmitVideoGenerationJob / GetVideoGenerationJob

配置方式 (extra_config):
- access_key_id:     阿里云 AccessKey ID
- access_key_secret: 阿里云 AccessKey Secret
- region:            区域 (默认 cn-shanghai; 支持 ap-southeast-1)
- endpoint:          自定义端点 (可选, 默认 yike.{region}.aliyuncs.com)
- security_token:    STS 临时凭证 (可选)
- api_version:       API 版本覆盖 (可选, 默认 "2026-03-19")

兼容方式: 也可把 API Key 填成 "AccessKeyId:AccessKeySecret" 格式。
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from ..base import BaseProvider, ProviderCapability, ProviderConfig
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from .video_generation import (
    DEFAULT_ENDPOINT,
    DEFAULT_REGION,
    execute_video_generation,
    get_video_generation_job,
    get_yike_job_credit,
    has_video_generation_tool,
    is_aliyun_video_model,
    stream_video_generation,
    submit_video_generation_job,
)


class AliyunProvider(BaseProvider):
    """
    阿里云供应商实现

    目前仅支持视频生成 (yike):
    - chat/stream_chat 走视频生成模型检测 + video_generation 工具
    - submit_video_generation / get_video_generation 提供 REST 路由使用
    """

    PROVIDER_TYPE: str = "aliyun"

    # 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.VIDEO,
    ]

    # 默认端点
    DEFAULT_BASE_URL = f"https://{DEFAULT_ENDPOINT}"

    # 支持的模型列表(网关别名 + 阿里云原生名)
    SUPPORTED_MODELS = {
        "wonder-pro": {
            "description": "Aliyun video generation model (Wonder-Pro)",
            "context_size": 0, "supports_vision": True, "is_video_model": True,
        },
        "wonder-standard": {
            "description": "Aliyun video generation model (Wonder-Standard)",
            "context_size": 0, "supports_vision": True, "is_video_model": True,
        },
        "wan3.0-video": {
            "description": "Aliyun video generation model (Wan 3.0)",
            "context_size": 0, "supports_vision": True, "is_video_model": True,
        },
        "happyhorse-1.1": {
            "description": "Aliyun video generation model (Happyhorse 1.1)",
            "context_size": 0, "supports_vision": True, "is_video_model": True,
        },
        "wan2.7": {
            "description": "Aliyun video generation model (Wan 2.7)",
            "context_size": 0, "supports_vision": True, "is_video_model": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化阿里云供应商

        Args:
            config: 供应商配置
                - api_key: 兼容格式 "AccessKeyId:AccessKeySecret"
                - extra_config:
                    - access_key_id / access_key_secret (推荐)
                    - region / endpoint / security_token (可选)
        """
        super().__init__(config)
        extra = config.extra_config or {}

        access_key_id = str(extra.get("access_key_id") or "").strip()
        access_key_secret = str(extra.get("access_key_secret") or "").strip()

        # 兼容 "AK:SK" 格式的 api_key
        if (not access_key_id or not access_key_secret) and config.api_key:
            api_key = (config.api_key or "").strip()
            if ":" in api_key:
                parts = api_key.split(":", 1)
                if not access_key_id:
                    access_key_id = parts[0].strip()
                if not access_key_secret:
                    access_key_secret = parts[1].strip()
            elif not access_key_id:
                access_key_id = api_key

        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.region = str(extra.get("region") or DEFAULT_REGION).strip()
        # 优先级: extra_config.endpoint > config.base_url > 区域默认端点
        self.endpoint = str(extra.get("endpoint") or "").strip() or None
        if not self.endpoint and getattr(config, "base_url", None):
            self.endpoint = str(config.base_url).strip() or None
        self.security_token = str(extra.get("security_token") or "").strip() or None
        self.api_version = str(extra.get("api_version") or "").strip() or None

        if not self.access_key_id or not self.access_key_secret:
            raise ValueError(
                "Aliyun provider requires access_key_id and access_key_secret "
                "(extra_config) or api_key in 'AccessKeyId:AccessKeySecret' format"
            )

    # ==================== 视频生成检测 ====================

    def is_video_generation_model(self, model: str) -> bool:
        """Check if the model is an Aliyun video generation model."""
        return is_aliyun_video_model(model)

    def _has_video_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains a video_generation tool."""
        return has_video_generation_tool(request)

    def supports_model(self, model: str) -> bool:
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        info = self.SUPPORTED_MODELS.get(model.lower())
        if info:
            return dict(info)
        return None

    # ==================== 非流式接口 ====================

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行视频生成请求

        仅支持视频生成模型 (wonder-pro / wan2.7 / ...) 或带
        video_generation 工具的请求; 其余请求直接报错。

        Args:
            request: 对话请求对象

        Returns:
            视频生成响应对象
        """
        if not (self.is_video_generation_model(request.model) or self._has_video_generation_tool(request)):
            raise RuntimeError(
                f"Aliyun provider only supports video generation; "
                f"unsupported model: {request.model}"
            )
        return await execute_video_generation(
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret,
            model=request.model,
            messages=request.messages,
            metadata=request.metadata,
            region=self.region,
            endpoint=self.endpoint,
            security_token=self.security_token,
            api_version=self.api_version,
            tracer=self.tracer,
        )

    # ==================== 流式接口 ====================

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """
        流式视频生成(进度事件 + 最终结果)

        将凭证注入 request.metadata, 由 stream_video_generation 读取。
        """
        if not (self.is_video_generation_model(request.model) or self._has_video_generation_tool(request)):
            raise RuntimeError(
                f"Aliyun provider only supports video generation; "
                f"unsupported model: {request.model}"
            )
        request.metadata["_access_key_id"] = self.access_key_id
        request.metadata["_access_key_secret"] = self.access_key_secret
        request.metadata["_region"] = self.region
        request.metadata["_endpoint"] = self.endpoint
        request.metadata["_security_token"] = self.security_token
        request.metadata["_api_version"] = self.api_version
        async for chunk in stream_video_generation(self.chat, request):
            yield chunk

    # ==================== 提交/查询任务 (REST 路由使用) ====================

    async def submit_video_generation(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        提交视频生成任务, 返回 ``{"RequestId": ..., "JobId": ...}``。

        供 /v1/videos/generations 路由通过 GatewayService 调用。
        """
        missing = [k for k in ("job_type", "model", "input") if not params.get(k)]
        if missing:
            raise ValueError(
                f"Missing required video generation parameter(s): "
                f"{', '.join(missing)}"
            )
        from app.http_client import get_shared_client

        client = await get_shared_client()
        return await submit_video_generation_job(
            client,
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret,
            job_type=params["job_type"],
            model=params["model"],
            input_json=params["input"],
            resolution=params.get("resolution"),
            aspect_ratio=params.get("aspect_ratio"),
            duration=params.get("duration"),
            n=params.get("n", 1),
            scene=params.get("scene"),
            client_token=params.get("client_token"),
            user_data=params.get("user_data"),
            job_parameters=params.get("job_parameters"),
            region=self.region,
            endpoint=self.endpoint,
            security_token=self.security_token,
            version=self.api_version,
            tracer=self.tracer,
        )

    async def get_video_generation(self, job_id: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        """
        查询视频生成任务, 返回 ``{"RequestId": ..., "VideoGenerationJob": {...}}``。

        供 /v1/videos/generations/<job_id> 路由通过 GatewayService 调用。
        """
        from app.http_client import get_shared_client

        client = await get_shared_client()
        return await get_video_generation_job(
            client,
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret,
            job_id=job_id,
            request_id=request_id,
            region=self.region,
            endpoint=self.endpoint,
            security_token=self.security_token,
            version=self.api_version,
            tracer=self.tracer,
        )

    async def get_job_credit(self, job_id: str) -> Dict[str, Any]:
        """
        查询已完成视频生成任务消耗的积分, 返回 ``{"RequestId", "JobId",
        "JobCreditCost", "CreditStatus"}``。

        供 /v1/videos/generations/<job_id>/credit 路由通过 GatewayService 调用。
        """
        from app.http_client import get_shared_client

        client = await get_shared_client()
        return await get_yike_job_credit(
            client,
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret,
            job_id=job_id,
            region=self.region,
            endpoint=self.endpoint,
            security_token=self.security_token,
            version=self.api_version,
            tracer=self.tracer,
        )
