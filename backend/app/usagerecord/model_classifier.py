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

# Video model prefixes (case-insensitive)
_VIDEO_PREFIXES = (
    "doubao-seedance", "seedance", "happyhorse-", "kling-", "veo-", "veo3",
    "gv-", "hy-video-", "viduq", "pixverse-",
)

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

    for prefix in _VIDEO_PREFIXES:
        if lower.startswith(prefix):
            return ModelCategory.VIDEO

    for keyword in _IMAGE_KEYWORDS:
        if keyword in lower:
            return ModelCategory.IMAGE

    for prefix in _IMAGE_PREFIXES:
        if lower.startswith(prefix):
            return ModelCategory.IMAGE

    return ModelCategory.TEXT