"""
火山引擎供应商实现 (Volcengine Provider)
实现火山引擎 (Volcengine Ark) 模型的 API 调用。

火山引擎 API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。
火山引擎 API 文档: https://www.volcengine.com/docs/82379/1263482
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse, UsageInfo
from app.abstraction.streaming import StreamChunk


class VolcengineProvider(OpenAIProvider):
    """
    火山引擎供应商实现
    
    火山引擎 Ark 是字节跳动旗下的大模型服务平台。
    其 API 与 OpenAI 兼容，但 URL 路径包含 /v3。
    """
    
    PROVIDER_TYPE: str = "volcengine"
    
    # 火山引擎支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
    ]
    
    # 默认 API 基础 URL (通常需要用户提供完整的包含 region 的 URL)
    # 格式通常为: https://ark.cn-beijing.volces.com/api/v3
    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    
    def __init__(self, config: ProviderConfig):
        """
        初始化火山引擎供应商
        
        Args:
            config: 供应商配置
        """
        # 设置默认 base_url
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        
        # 确保 base_url 以 /v3 结尾 (如果用户只提供了域名)
        if config.base_url and not config.base_url.endswith("/v3") and "/v3/" not in config.base_url:
            if config.base_url.endswith("/"):
                config.base_url = f"{config.base_url}v3"
            else:
                config.base_url = f"{config.base_url}/v3"
        
        super().__init__(config)

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析火山引擎响应数据
        
        复用 OpenAI 格式解析，处理火山引擎特有字段。
        """
        response = super().parse_response(response_data, model)
        response.provider = self.PROVIDER_TYPE
        
        # 处理火山引擎特有的 reasoning_content
        for i, choice_data in enumerate(response_data.get("choices", [])):
            message_data = choice_data.get("message", {})
            if "reasoning_content" in message_data:
                response.choices[i].reasoning_content = message_data["reasoning_content"]
        
        return response
    
    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """
        解析流式响应块
        
        复用 OpenAI 格式，处理火山引擎特有字段。
        """
        # 复用父类解析
        chunk = super()._parse_stream_chunk(data, response_id, model)
        
        if chunk:
            # 处理火山引擎特有的 reasoning_content
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "reasoning_content" in delta:
                    chunk.delta_reasoning_content = delta["reasoning_content"]
        
        return chunk
