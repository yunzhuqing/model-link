"""
混元 AI 供应商模块 (Hunyuan Provider Module)

包含以下子模块：
- base:              混元 AI 基础实现（3D 生成路由）
- threed_generation: 混元 3D 生成实现
                     (SubmitHunyuanTo3DRapidJob / SubmitHunyuanTo3DProJob + 轮询，
                      兼容 /v1/responses 3d_generation 工具)
"""

from .base import HunyuanProvider

__all__ = [
    "HunyuanProvider",
]
