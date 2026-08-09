"""
Model classification utility for background response resync.

Classifies model names into IMAGE, VIDEO, THREED, or TEXT categories,
with associated minimum age thresholds for resync timing.
"""
from __future__ import annotations

from enum import Enum


class ModelCategory(Enum):
    IMAGE = "image"
    VIDEO = "video"
    THREED = "3d"
    TEXT = "text"


CATEGORY_MIN_AGE_MINUTES = {
    ModelCategory.IMAGE: 10,
    ModelCategory.VIDEO: 30,
    ModelCategory.THREED: 40,
    ModelCategory.TEXT: 9999,  # never sync
}

# Vidu image generation models (exact names, case-insensitive).
# ``viduq1`` / ``viduq2`` must be checked before the ``viduq3`` video prefix,
# and ``q2-fast`` / ``q2-pro`` / ``q3-fast`` have no "image" keyword.
_VIDU_IMAGE_MODELS = (
    "viduq1", "viduq2", "viduimage-2", "q2-fast", "q2-pro", "q3-fast",
)

# Video model prefixes (case-insensitive)
_VIDEO_PREFIXES = (
    "doubao-seedance", "seedance", "happyhorse-", "kling-", "veo-", "veo3",
    "gv-", "hy-video-", "viduq3", "pixverse-", "minimax-h3", "wonder-",
)

# Aliyun (yike) video models that don't share a safe prefix (exact names).
_VIDEO_EXACT = ("wan3.0-video", "wan2.7")

# 3D model prefixes
_THREED_PREFIXES = (
    "doubao-seed3d", "seed3d", "hunyuan-3d-", "hy-3d-",
)

# Image model keywords (substrings to match)
_IMAGE_KEYWORDS = (
    "image", "imagen", "seedream", "qwen-image", "gpt-image",
    "hy-image-", "z-image-turbo",
)

# Image model prefixes
_IMAGE_PREFIXES = ("gem-", "mingmou-")


def classify_model(model_name: str | None) -> ModelCategory:
    """
    Classify a model name into IMAGE, VIDEO, THREED, or TEXT.

    Returns TEXT for None or empty input.
    """
    if not model_name:
        return ModelCategory.TEXT

    lower = model_name.lower()

    # Check most specific (3D) first, then video, then image
    for prefix in _THREED_PREFIXES:
        if lower.startswith(prefix):
            return ModelCategory.THREED

    for name in _VIDU_IMAGE_MODELS:
        if lower == name:
            return ModelCategory.IMAGE

    for prefix in _VIDEO_PREFIXES:
        if lower.startswith(prefix):
            return ModelCategory.VIDEO

    if lower in _VIDEO_EXACT:
        return ModelCategory.VIDEO

    for keyword in _IMAGE_KEYWORDS:
        if keyword in lower:
            return ModelCategory.IMAGE

    for prefix in _IMAGE_PREFIXES:
        if lower.startswith(prefix):
            return ModelCategory.IMAGE

    return ModelCategory.TEXT
