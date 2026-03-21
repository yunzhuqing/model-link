"""
智谱 AI 供应商实现 (Zhipu AI / Z.AI Provider)
实现智谱 AI GLM 系列模型的 API 调用。

智谱 AI API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。
智谱 AI API 文档: https://open.bigmodel.cn/dev/api/
"""
from typing import Optional, List, Dict, Any
import json
import time
import sys

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk


class GLMProvider(OpenAIProvider):
    """
    智谱 AI (Z.AI) 供应商实现

    智谱 AI 提供 GLM 系列大模型服务（ChatGLM、GLM-4 等）。
    其 API 与 OpenAI 兼容，可直接复用 OpenAI 的请求/响应处理逻辑。
    """

    PROVIDER_TYPE: str = "glm"

    # 智谱 AI 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.WEB_SEARCH,
    ]

    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

    # 智谱 AI 支持的模型列表
    SUPPORTED_MODELS = {
        "glm-4-plus": {
            "description": "GLM-4 Plus - 高性能旗舰模型",
            "context_size": 128000,
            "supports_vision": False,
        },
        "glm-4-air": {
            "description": "GLM-4 Air - 高性价比模型",
            "context_size": 128000,
            "supports_vision": False,
        },
        "glm-4-airx": {
            "description": "GLM-4 AirX - 极速推理模型",
            "context_size": 8192,
            "supports_vision": False,
        },
        "glm-4-flash": {
            "description": "GLM-4 Flash - 免费高速模型",
            "context_size": 128000,
            "supports_vision": False,
        },
        "glm-4-flashx": {
            "description": "GLM-4 FlashX - 免费极速模型",
            "context_size": 128000,
            "supports_vision": False,
        },
        "glm-4v-plus": {
            "description": "GLM-4V Plus - 多模态旗舰模型",
            "context_size": 8192,
            "supports_vision": True,
        },
        "glm-4v": {
            "description": "GLM-4V - 多模态模型",
            "context_size": 2048,
            "supports_vision": True,
        },
        "glm-4-long": {
            "description": "GLM-4 Long - 超长上下文模型",
            "context_size": 1000000,
            "supports_vision": False,
        },
        "glm-z1-air": {
            "description": "GLM-Z1 Air - 推理模型",
            "context_size": 16384,
            "supports_vision": False,
        },
        "glm-z1-airx": {
            "description": "GLM-Z1 AirX - 极速推理模型",
            "context_size": 16384,
            "supports_vision": False,
        },
        "glm-z1-flash": {
            "description": "GLM-Z1 Flash - 免费推理模型",
            "context_size": 16384,
            "supports_vision": False,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化智谱 AI 供应商

        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        super().__init__(config)

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据

        复用 OpenAI 格式，添加智谱 AI 特有的参数处理。
        """
        result = super().prepare_request(request)

        # 智谱 AI 特有：根据模型是否支持思维和 reasoning_effort 设置 thinking 参数
        if request.metadata.get('support_thinking', False):
            reasoning_effort = request.reasoning_effort or 'none'
            if reasoning_effort != 'none':
                result["thinking"] = {"type": "enabled"}
            else:
                result["thinking"] = {"type": "disabled"}

        # 打印请求体到控制台（调试用）
        print("\n" + "=" * 50, file=sys.stderr)
        print("[GLM/Zhipu AI Request Body]", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        print("=" * 50 + "\n", file=sys.stderr)

        return result

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析智谱 AI 响应数据

        复用 OpenAI 格式解析，处理智谱 AI 特有的 reasoning_content 字段。
        """
        response = super().parse_response(response_data, model)
        response.provider = self.PROVIDER_TYPE

        # 处理智谱 AI 的 reasoning_content（思考过程）
        for i, choice_data in enumerate(response_data.get("choices", [])):
            message_data = choice_data.get("message", {})
            if "reasoning_content" in message_data:
                response.choices[i].reasoning_content = message_data["reasoning_content"]

        return response

    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """
        解析流式响应块

        复用 OpenAI 格式，处理智谱 AI 特有的 reasoning_content 字段。
        """
        chunk = super()._parse_stream_chunk(data, response_id, model)

        if chunk:
            # 处理智谱 AI 的 reasoning_content（思考过程）
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
                "owned_by": "zhipuai",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
