"""
腾讯云点播 AI 供应商实现 (Tencent VOD Provider)
实现腾讯云点播 (VOD) AI 大模型的 API 调用。

腾讯云点播 AI API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。
API 文档：https://text-aigc.vod-qcloud.com
"""
from typing import List

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability


class TencentVODProvider(OpenAIProvider):
    """
    腾讯云点播 AI 供应商实现

    腾讯云点播 AI 提供兼容 OpenAI chat/completions 格式的接口，
    继承 OpenAIProvider 直接复用其请求/响应逻辑。
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
