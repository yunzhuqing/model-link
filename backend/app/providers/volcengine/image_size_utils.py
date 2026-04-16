"""
火山引擎 Seedream 图像尺寸工具 (Volcengine Seedream Image Size Utilities)

Seedream 图像尺寸 → (aspect_ratio, resolution_tier) 反向查表。
Based on the official Seedream size table for 4.0 / 4.5 / 5.0 lite models.
"""
from typing import Dict, Tuple


# Maps "WxH" pixel dimensions → (aspect_ratio, tier).
SEEDREAM_SIZE_MAP: Dict[str, Tuple[str, str]] = {
    # ── 1K tier (Seedream 4.0 only) ──────────────────────────────────────
    "1024x1024": ("1:1",  "1K"),
    "864x1152":  ("3:4",  "1K"),
    "1152x864":  ("4:3",  "1K"),
    "1312x736":  ("16:9", "1K"),
    "736x1312":  ("9:16", "1K"),
    "832x1248":  ("2:3",  "1K"),
    "1248x832":  ("3:2",  "1K"),
    "1568x672":  ("21:9", "1K"),
    # ── 2K tier (shared across 4.0 / 4.5 / 5.0 lite) ────────────────────
    "2048x2048": ("1:1",  "2K"),
    "1728x2304": ("3:4",  "2K"),
    "2304x1728": ("4:3",  "2K"),
    "2848x1600": ("16:9", "2K"),
    "1600x2848": ("9:16", "2K"),
    "2496x1664": ("3:2",  "2K"),
    "1664x2496": ("2:3",  "2K"),
    "3136x1344": ("21:9", "2K"),
    # ── 3K tier (Seedream 5.0 lite only) ─────────────────────────────────
    "3072x3072": ("1:1",  "3K"),
    "2592x3456": ("3:4",  "3K"),
    "3456x2592": ("4:3",  "3K"),
    "4096x2304": ("16:9", "3K"),
    "2304x4096": ("9:16", "3K"),
    "2496x3744": ("2:3",  "3K"),
    "3744x2496": ("3:2",  "3K"),
    "4704x2016": ("21:9", "3K"),
    # ── 4K tier (Seedream 4.0 / 4.5) ────────────────────────────────────
    "4096x4096": ("1:1",  "4K"),
    "3520x4704": ("3:4",  "4K"),
    "4704x3520": ("4:3",  "4K"),
    "5504x3040": ("16:9", "4K"),
    "3040x5504": ("9:16", "4K"),
    "3328x4992": ("2:3",  "4K"),
    "4992x3328": ("3:2",  "4K"),
    "6240x2656": ("21:9", "4K"),
}

# Tier shorthands
_SEEDREAM_TIER_NAMES = {"1K", "2K", "3K", "4K"}


def resolve_seedream_size(size: str) -> Tuple[str, str]:
    """
    Resolve a Seedream image size string to (aspect_ratio, resolution_tier).

    Handles:
    - Pixel dimensions: "1024x1024" → ("1:1", "1K")
    - Tier shorthands: "2K" → ("", "2K")
    - Unknown sizes: falls back to GCD-based aspect ratio derivation

    Args:
        size: Size string from the image generation request

    Returns:
        (aspect_ratio, resolution_tier) tuple. Either value may be empty string
        if it cannot be determined.
    """
    if not size:
        return ("", "")

    normalized = size.strip().upper()

    # Check tier shorthands first
    if normalized in _SEEDREAM_TIER_NAMES:
        return ("", normalized)

    # Normalize to lowercase for pixel dimension lookup
    pixel_key = size.strip().lower().replace(" ", "")
    # Ensure "WxH" format
    if "x" in pixel_key:
        parts = pixel_key.split("x", 1)
        pixel_key = f"{parts[0].strip()}x{parts[1].strip()}"

    # Exact match in the lookup table
    if pixel_key in SEEDREAM_SIZE_MAP:
        return SEEDREAM_SIZE_MAP[pixel_key]

    # Fallback: derive aspect ratio via GCD
    if "x" in pixel_key:
        try:
            from math import gcd
            parts = pixel_key.split("x", 1)
            w, h = int(parts[0]), int(parts[1])
            if w > 0 and h > 0:
                g = gcd(w, h)
                return (f"{w // g}:{h // g}", "")
        except (ValueError, TypeError):
            pass

    return ("", "")
