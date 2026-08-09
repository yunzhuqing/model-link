"""
供应商实现层 (Provider Layer)
提供不同 AI 供应商的具体实现。
"""

from .base import BaseProvider, ProviderConfig, ProviderCapability
from .openai_provider import OpenAIProvider
from .azure_provider import AzureProvider
from .anthropic_provider import AnthropicProvider
from .bailian import BailianProvider
from .volcengine import VolcengineProvider
from .vertexai import VertexAIProvider
from .moonshot_provider import MoonshotProvider
from .glm_provider import GLMProvider
from .minimax_provider import MiniMaxProvider
from .gemini import GeminiProvider
from .tencent import TencentProvider, HunyuanProvider, MPSProvider
from .tencent.vod import TencentVODProvider
from .vllm_provider import VLLMProvider
from .byteplus import BytePlusProvider
from .deepseek_provider import DeepSeekProvider
from .openai_chatcompletions_compt_provider import OpenAIChatCompletionsCompatProvider
from .openai_responses_compt_provider import OpenAIResponsesCompatProvider
from .mulerun import MulerunProvider
from .openspeech_provider import VolcengineOpenspeechProvider
from .vidu import ViduProvider
from .aliyun import AliyunProvider
from .tencentlive import TencentLiveProvider

__all__ = [
    'BaseProvider', 'ProviderConfig', 'ProviderCapability',
    'OpenAIProvider', 'AzureProvider', 'AnthropicProvider', 'BailianProvider',
    'VolcengineProvider', 'VertexAIProvider', 'MoonshotProvider', 'GLMProvider',
    'MiniMaxProvider', 'GeminiProvider', 'TencentVODProvider', 'VLLMProvider',
    'TencentProvider', 'HunyuanProvider', 'MPSProvider', 'BytePlusProvider', 'DeepSeekProvider',
    'OpenAIChatCompletionsCompatProvider', 'OpenAIResponsesCompatProvider',
    'MulerunProvider', 'VolcengineOpenspeechProvider',
    'ViduProvider',
    'AliyunProvider',
    'TencentLiveProvider',
]

# 供应商注册表
PROVIDER_REGISTRY = {
    'openai': OpenAIProvider,
    'azure': AzureProvider,
    'anthropic': AnthropicProvider,
    'bailian': BailianProvider,
    'volcengine': VolcengineProvider,
    'vertexai': VertexAIProvider,
    'moonshot': MoonshotProvider,
    'glm': GLMProvider,
    'minimax': MiniMaxProvider,
    'gemini': GeminiProvider,
    'tencentvod': TencentVODProvider,
    'vllm': VLLMProvider,
    'hunyuan': TencentProvider,
    'tencentmps': TencentProvider,
    'tencent': TencentProvider,
    'byteplus': BytePlusProvider,
    'deepseek': DeepSeekProvider,
    'openai_chatcompletions_compt': OpenAIChatCompletionsCompatProvider,
    'openai_responses_compt': OpenAIResponsesCompatProvider,
    'mulerun': MulerunProvider,
    'volcengine_openspeech': VolcengineOpenspeechProvider,
    # 旧类型别名：历史配置的 seed_tts 供应商继续指向 openspeech 实现（无数据迁移）。
    'seed_tts': VolcengineOpenspeechProvider,
    'vidu': ViduProvider,
    'aliyun': AliyunProvider,
    'tencentlive': TencentLiveProvider,
}


def get_provider_class(provider_type: str):
    """
    获取供应商类
    
    Args:
        provider_type: 供应商类型
    
    Returns:
        供应商类，如果不存在返回 None
    """
    return PROVIDER_REGISTRY.get(provider_type)


def register_provider(provider_type: str, provider_class):
    """
    注册新的供应商
    
    Args:
        provider_type: 供应商类型
        provider_class: 供应商类
    """
    PROVIDER_REGISTRY[provider_type] = provider_class


def list_providers():
    """列出所有已注册的供应商"""
    return list(PROVIDER_REGISTRY.keys())
