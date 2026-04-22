"""
BytePlus 供应商基础实现 (BytePlus Base Provider)

BytePlus 是火山引擎 (Volcengine) 的海外版本，API 格式完全兼容。
继承自 VolcengineProvider，仅覆盖域名和 provider 类型标识。

域名: https://ark.ap-southeast.bytepluses.com/api/v3

API 文档: https://docs.byteplus.com/
"""
import sys
from typing import List

from app.providers.volcengine.base import VolcengineProvider
from app.providers.base import ProviderConfig, ProviderCapability


class BytePlusProvider(VolcengineProvider):
    """
    BytePlus 供应商实现 (Responses API)

    继承自 VolcengineProvider，仅覆盖：
    - PROVIDER_TYPE: "byteplus"
    - DEFAULT_BASE_URL: BytePlus 海外域名

    所有 API 调用逻辑（chat、stream_chat、image/video/3D 生成等）
    完全复用 Volcengine 实现。
    """

    PROVIDER_TYPE: str = "byteplus"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
    ]

    DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        # Ensure base_url ends with /v3
        if config.base_url and not config.base_url.endswith("/v3") and "/v3/" not in config.base_url:
            config.base_url = config.base_url.rstrip("/") + "/v3"

        # Call BaseProvider.__init__ directly (skip VolcengineProvider.__init__
        # to avoid overwriting base_url with Volcengine's default)
        super(VolcengineProvider, self).__init__(config)
