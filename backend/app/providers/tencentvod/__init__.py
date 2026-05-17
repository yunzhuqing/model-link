"""
腾讯云点播 AI 供应商模块 (TencentVOD Provider Module)

包含以下子模块：
- base:             腾讯云点播 AI 基础实现（聊天、流式、图像/视频生成路由）
- image_generation: 腾讯云点播 AI 图像生成实现
                    (CreateAigcImageTask + DescribeTaskDetail，兼容 /v1/responses image_generation 工具)
- video_generation: 腾讯云点播 AI 视频生成实现
                    (CreateAigcVideoTask + DescribeTaskDetail，兼容 /v1/responses video_generation 工具)
- threed_generation: 腾讯云点播 AI 3D 生成实现
                    (CreateAigcVideoTask + DescribeTaskDetail，兼容 /v1/responses 3d_generation 工具)
"""

from .base import TencentVODProvider

__all__ = [
    "TencentVODProvider",
]
