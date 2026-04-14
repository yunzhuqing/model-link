"""
OpenAI ChatCompletions 兼容供应商 (OpenAI ChatCompletions Compatible Provider)

用于对接任何兼容 OpenAI Chat Completions API (/v1/chat/completions) 的第三方服务。
与 OpenAIProvider 的区别：
  - PROVIDER_TYPE = "openai_chatcompletions_compt"
  - 无固定默认 Base URL，需用户自行填写
  - 不附加 reasoning_effort 等 OpenAI 特有参数（可按需在 metadata 透传）
  - API Key 可选（部分私有部署不需要鉴权）

典型使用场景
-----------
  - 私有部署的兼容服务（FastChat、LiteLLM、text-generation-webui 等）
  - 国内云厂商对外暴露的 OpenAI 兼容接口
  - 任何支持 /v1/chat/completions 的第三方 LLM 服务

配置说明
--------
  Base URL: 填写兼容服务的地址，例如 http://192.168.1.100:8080/v1
  API Key : 如果目标服务不需要鉴权，可留空
"""
from typing import Dict, Any, List, Optional

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest


class OpenAIChatCompletionsCompatProvider(OpenAIProvider):
    """
    OpenAI ChatCompletions 兼容供应商。

    直接继承 OpenAIProvider，所有请求均通过
    ``{base_url}/chat/completions`` 发送。

    主要定制点：
    1. ``PROVIDER_TYPE = "openai_chatcompletions_compt"`` — 注册标识符
    2. 无强制 DEFAULT_BASE_URL — 由用户在管理面板中配置
    3. API Key 可选 — 留空时省略 Authorization 头
    """

    PROVIDER_TYPE: str = "openai_chatcompletions_compt"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
    ]

    # 无默认 Base URL，必须由用户配置
    DEFAULT_BASE_URL: str = ""

    def __init__(self, config: ProviderConfig):
        # 不强制设置默认 base_url，直接调用 BaseProvider.__init__
        # 注意：绕过 OpenAIProvider.__init__ 中的 DEFAULT_BASE_URL 强制赋值
        from .base import BaseProvider
        BaseProvider.__init__(self, config)

    def get_headers(self) -> Dict[str, str]:
        """
        构建请求头。

        当 api_key 为空时省略 Authorization 头，
        兼容不需要鉴权的私有部署服务。
        """
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            if self.config.authorization and self.config.authorization != "Authorization":
                headers[self.config.authorization] = self.config.api_key
            else:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据。

        使用父类转换逻辑，并保留所有 metadata 中的额外参数透传给上游。
        父类已经处理了 _GATEWAY_INTERNAL_KEYS 的过滤。
        """
        return super().prepare_request(request)

    def supports_model(self, model: str) -> bool:
        """兼容服务支持任意模型名称。"""
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """返回通用模型信息占位。"""
        return {
            "description": f"OpenAI ChatCompletions compatible model: {model}",
            "context_size": 8192,
            "supports_vision": False,
        }
