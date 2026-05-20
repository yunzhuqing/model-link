"""
火山引擎 Seedream 图像尺寸工具 (Volcengine Seedream Image Size Utilities)

DEPRECATED: This module is kept for backwards compatibility. All image size
resolution is now handled by the unified ``app.providers.image_size_utils``.
"""

from app.providers.image_size_utils import (
    IMAGE_SIZE_MAP,
    resolve_image_size,
    resolve_pixel_size,
    get_pixel_size,
    get_supported_sizes,
    get_supported_aspect_ratios,
    get_sizes_for_aspect_ratio,
)

# Legacy compatibility — prefer resolve_image_size(size=...) instead.
def resolve_seedream_size(size: str):
    return resolve_image_size(size=size)