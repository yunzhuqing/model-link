"""
供应商实现层 (Provider Layer)
提供不同 AI 供应商的具体实现。
"""

from .base import BaseProvider, ProviderConfig, ProviderCapability
from .bailian_provider import BailianProvider

__all__ = [
    'BaseProvider', 'ProviderConfig', 'ProviderCapability',
    'BailianProvider'
]

# 供应商注册表
PROVIDER_REGISTRY = {
    'bailian': BailianProvider,
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