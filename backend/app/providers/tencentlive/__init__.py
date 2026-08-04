"""
腾讯云 TencentLive (AIGC Model Hub) 供应商模块 (TencentLive Provider Module)

通过腾讯云 AIGC Model Hub 的 Gemini 兼容接口提供 nano 生图能力：

    POST {base_url}/v1/wand/gem-image/generation/flex
    Headers: X-Api-Key: <key>

入参/出参均兼容 Gemini generateContent 格式（文生图、图生图 base64、
图生图 URL），模型名直接透传（如 gemini-2.5-flash-image、
gemini-3.1-flash-image）。

配置:
- base_url: AIGC Model Hub 域名（如 https://aigc-model-hub.example.com）
- api_key:  X-Api-Key 密钥
"""

from .base import TencentLiveProvider

__all__ = [
    "TencentLiveProvider",
]
