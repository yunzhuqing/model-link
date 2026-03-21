"""
Moonshot 供应商实现 (Moonshot Provider)
实现 Moonshot AI (月之暗面 / Kimi) 模型的 API 调用。

Moonshot API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。
Moonshot API 文档: https://platform.moonshot.cn/docs
"""
from typing import Optional, List, Dict, Any
import json
import time
import sys

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk


class MoonshotProvider(OpenAIProvider):
    """
    Moonshot 供应商实现

    Moonshot AI（月之暗面）提供 Kimi 系列大模型服务。
    其 API 与 OpenAI 兼容，可直接复用 OpenAI 的请求/响应处理逻辑。
    """

    PROVIDER_TYPE: str = "moonshot"

    # Moonshot 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
    ]

    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"

    # Moonshot 支持的模型列表
    SUPPORTED_MODELS = {
        "moonshot-v1-8k": {
            "description": "Moonshot v1 8K - 8K 上下文窗口",
            "context_size": 8192,
            "supports_vision": False,
        },
        "moonshot-v1-32k": {
            "description": "Moonshot v1 32K - 32K 上下文窗口",
            "context_size": 32768,
            "supports_vision": False,
        },
        "moonshot-v1-128k": {
            "description": "Moonshot v1 128K - 128K 上下文窗口",
            "context_size": 131072,
            "supports_vision": False,
        },
        "kimi-latest": {
            "description": "Kimi 最新模型",
            "context_size": 131072,
            "supports_vision": False,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化 Moonshot 供应商

        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        super().__init__(config)

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据

        复用 OpenAI 格式，添加 Moonshot 特有的 thinking 参数。
        当模型支持思维且 reasoning_effort 不为 'none' 时，
        向 Moonshot API 发送 thinking 参数以启用推理模式。

        Moonshot API 文档: https://platform.moonshot.cn/docs/guide/thinking
        """
        result = super().prepare_request(request)

        # Moonshot 特有：根据模型是否支持思维和 reasoning_effort 设置 thinking 参数
        if request.metadata.get('support_thinking', False):
            reasoning_effort = request.reasoning_effort or 'none'
            if reasoning_effort != 'none':
                result["thinking"] = {"type": "enabled"}
            else:
                result["thinking"] = {"type": "disabled"}

        # 打印请求体到控制台（调试用）
        print("\n" + "=" * 50, file=sys.stderr)
        print("[Moonshot Request Body]", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        print("=" * 50 + "\n", file=sys.stderr)

        return result

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析 Moonshot 响应数据

        复用 OpenAI 格式解析，处理 Moonshot 特有的 reasoning_content 字段。
        """
        response = super().parse_response(response_data, model)
        response.provider = self.PROVIDER_TYPE

        # 处理 Moonshot 的 reasoning_content（思考过程）
        for i, choice_data in enumerate(response_data.get("choices", [])):
            message_data = choice_data.get("message", {})
            if "reasoning_content" in message_data:
                response.choices[i].reasoning_content = message_data["reasoning_content"]

        return response

    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """
        解析流式响应块

        复用 OpenAI 格式，处理 Moonshot 特有的 reasoning_content 字段。
        """
        chunk = super()._parse_stream_chunk(data, response_id, model)

        if chunk:
            # 处理 Moonshot 的 reasoning_content（思考过程）
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "reasoning_content" in delta:
                    chunk.delta_reasoning_content = delta["reasoning_content"]

        return chunk

    def list_models(self) -> List[Dict[str, Any]]:
        """列出可用模型"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "moonshot",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
