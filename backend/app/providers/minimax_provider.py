"""
MiniMax 供应商实现 (MiniMax Provider)
实现 MiniMax 系列模型的 API 调用。

MiniMax API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。
MiniMax API 文档: https://platform.minimaxi.com/document/
"""
from typing import Optional, List, Dict, Any
import json
import re
import time
import sys

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk


class MiniMaxProvider(OpenAIProvider):
    """
    MiniMax 供应商实现

    MiniMax 提供大模型服务（MiniMax-M 系列等）。
    其 API 与 OpenAI 兼容，可直接复用 OpenAI 的请求/响应处理逻辑。
    """

    PROVIDER_TYPE: str = "minimax"

    # MiniMax 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
    ]

    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://api.minimax.chat/v1"

    # MiniMax 支持的模型列表
    SUPPORTED_MODELS = {
        "MiniMax-M2.5": {
            "description": "MiniMax M2.5 - 高性能多模态模型",
            "context_size": 1000000,
            "supports_vision": True,
        },
        "MiniMax-M2.7": {
            "description": "MiniMax M2.7 - 最新旗舰模型",
            "context_size": 1000000,
            "supports_vision": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化 MiniMax 供应商

        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        super().__init__(config)

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据

        复用 OpenAI 格式，添加 MiniMax 特有的参数处理。

        M3+ 使用 thinking: {type: "adaptive" | "disabled"}
        M2.x 使用 thinking: {type: "enabled" | "disabled"}
        """
        result = super().prepare_request(request)

        # MiniMax 特有：根据模型版本和 reasoning_effort 设置 thinking 参数
        # M3+ 支持关闭 thinking，M2.x 必须强制开启
        if request.metadata.get('support_thinking', False):
            m = re.search(r'-m(\d+)', request.model.lower())
            minimax_major = int(m.group(1)) if m else 0
            if minimax_major >= 3:
                # M3+: can disable thinking
                reasoning_effort = request.reasoning_effort or 'none'
                if reasoning_effort != 'none':
                    result["thinking"] = {"type": "adaptive"}
                else:
                    result["thinking"] = {"type": "disabled"}
            else:
                # M2.x and older: thinking is mandatory
                result["thinking"] = {"type": "enabled"}

        # 打印请求体到控制台（调试用）
        return result

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析 MiniMax 响应数据

        复用 OpenAI 格式解析，处理 MiniMax 特有的 reasoning_content 字段。
        """
        response = super().parse_response(response_data, model)
        response.provider = self.PROVIDER_TYPE

        # 处理 MiniMax 的 reasoning_content（思考过程）
        for i, choice_data in enumerate(response_data.get("choices", [])):
            message_data = choice_data.get("message", {})
            if "reasoning_content" in message_data:
                response.choices[i].reasoning_content = message_data["reasoning_content"]

        return response

    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """
        解析流式响应块

        复用 OpenAI 格式，处理 MiniMax 特有的 reasoning_content 字段。
        """
        chunk = super()._parse_stream_chunk(data, response_id, model)

        if chunk:
            # 处理 MiniMax 的 reasoning_content（思考过程）
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
                "owned_by": "minimax",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
