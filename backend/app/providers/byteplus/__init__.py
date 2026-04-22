"""
BytePlus 供应商模块 (BytePlus Provider Module)

BytePlus 是火山引擎 (Volcengine) 的海外版本，API 格式完全兼容，
仅域名和模型名称不同。

域名: https://ark.ap-southeast.bytepluses.com/api/v3

包含以下子模块：
- base: BytePlus Responses API 基础实现（继承自 Volcengine）
"""

from .base import BytePlusProvider

__all__ = [
    'BytePlusProvider',
]
