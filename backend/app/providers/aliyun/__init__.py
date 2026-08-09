"""
阿里云供应商模块 (Aliyun Provider Module)

通过阿里云 OpenAPI (AK/SK 签名) 访问阿里云 AI 服务。

子模块:
- base: 阿里云供应商基类 (AliyunProvider)
- video_generation: 阿里云视频生成 (yike) 实现
  - SubmitVideoGenerationJob / GetVideoGenerationJob
"""

from .base import AliyunProvider
from .video_generation import (
    ALIYUN_VIDEO_MODELS,
    build_input_json,
    execute_video_generation,
    get_video_generation_job,
    has_video_generation_tool,
    infer_job_type,
    is_aliyun_video_model,
    parse_output_medias,
    stream_video_generation,
    submit_video_generation_job,
)

__all__ = [
    'AliyunProvider',
    'ALIYUN_VIDEO_MODELS',
    'build_input_json',
    'execute_video_generation',
    'get_video_generation_job',
    'has_video_generation_tool',
    'infer_job_type',
    'is_aliyun_video_model',
    'parse_output_medias',
    'stream_video_generation',
    'submit_video_generation_job',
]
