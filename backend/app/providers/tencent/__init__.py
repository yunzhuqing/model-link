"""
腾讯 AI 供应商模块 (Tencent Provider Module)

包含以下子模块：
- vod:    腾讯云点播 AI（原 TencentVOD）
- hunyuan: 混元 AI 3D 生成
- mps:    腾讯云 MPS 智能擦除
"""

from .vod import TencentVODProvider
from .hunyuan import HunyuanProvider
from .mps import MPSProvider

__all__ = [
    "TencentVODProvider",
    "HunyuanProvider",
    "MPSProvider",
]