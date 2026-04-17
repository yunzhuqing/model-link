"""
Image Size / Resolution Utility (shared)
=========================================

Provides ``WxH → (aspect_ratio, resolution_tier)`` lookup tables for TencentVOD
image generation models, and a ``resolve_image_size()`` helper that turns
a user-supplied ``size``, ``aspect_ratio``, or ``resolution`` parameter into
the ``(aspect_ratio, resolution_tier)`` pair expected by the TencentVOD
CreateAigcImageTask API.

Key distinction
---------------
``resolution`` in the TencentVOD API is a **quality tier label** ("512", "1K",
"2K", "4K"), NOT a pixel string.  This module's tables encode that:

    WxH pixel string  →  (aspect_ratio, resolution_tier)

Examples
    "512x512"    →  ("1:1",  "512")   [gemini-3.1-flash-image-preview]
    "1024x1024"  →  ("1:1",  "1K")   [gemini-3-pro-image-preview]
    "2048x2048"  →  ("1:1",  "2K")   [gemini-3-pro-image-preview]
    "1024x1024"  →  ("1:1",  "")     [gemini-2.5-flash-image — single-res, no tier]

Usage
-----
    from app.providers.image_size_utils import resolve_image_size

    aspect_ratio, resolution_tier = resolve_image_size(
        model="gemini-2.5-flash-image",
        size=metadata.get("size", ""),
        aspect_ratio=metadata.get("aspect_ratio", ""),
        resolution=metadata.get("resolution", ""),
    )
    # Pass aspect_ratio and (optionally) resolution_tier to CreateAigcImageTask

Priority (highest → lowest)
----------------------------
1. ``resolution`` set to a WxH string  → table lookup → (aspect_ratio, tier)
2. ``resolution`` set to a tier label ("1K", "2K", …) + ``aspect_ratio``  →
   use both as-is; look up matching WxH to confirm (optional).
3. ``aspect_ratio`` explicitly set (no resolution) → use as-is, pick default
   (lowest-res / first) tier entry for that ratio.
4. ``size`` provided:
   a. Looks like "WxH"  → primary table lookup → (aspect_ratio, tier)
   b. Looks like "W:H" ratio → treat as aspect_ratio, pick default entry
   c. Tier label ("1K", "2K", …) → pick "1:1" entry at that tier
5. Nothing provided → return ("", "")
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# (aspect_ratio, resolution_tier)
# resolution_tier: "512" | "1K" | "2K" | "4K" | ""   (empty = no tier needed)
SizeEntry = Tuple[str, str]
# WxH string → SizeEntry
SizeTable = Dict[str, SizeEntry]

_TIER_LABELS = {"512", "1K", "2K", "3K", "4K", "0.5K"}


# ---------------------------------------------------------------------------
# Size tables   WxH  →  (aspect_ratio, resolution_tier)
# ---------------------------------------------------------------------------

# ── Gemini 2.5 Flash Image (GG 2.5) ─────────────────────────────────────────
# Single resolution per aspect ratio — no tier label needed.
_GG_25_SIZES: SizeTable = {
    "1024x1024": ("1:1",  ""),
    "832x1248":  ("2:3",  ""),
    "1248x832":  ("3:2",  ""),
    "864x1184":  ("3:4",  ""),
    "1184x864":  ("4:3",  ""),
    "896x1152":  ("4:5",  ""),
    "1152x896":  ("5:4",  ""),
    "768x1344":  ("9:16", ""),
    "1344x768":  ("16:9", ""),
    "1536x672":  ("21:9", ""),
}

# ── Gemini 3 Pro Image Preview (GG 3.0) ──────────────────────────────────────
# Three quality tiers: 1K / 2K / 4K.
_GG_30_SIZES: SizeTable = {
    # 1:1
    "1024x1024":  ("1:1",  "1K"),
    "2048x2048":  ("1:1",  "2K"),
    "4096x4096":  ("1:1",  "4K"),
    # 2:3
    "848x1264":   ("2:3",  "1K"),
    "1696x2528":  ("2:3",  "2K"),
    "3392x5056":  ("2:3",  "4K"),
    # 3:2
    "1264x848":   ("3:2",  "1K"),
    "2528x1696":  ("3:2",  "2K"),
    "5056x3392":  ("3:2",  "4K"),
    # 3:4
    "896x1200":   ("3:4",  "1K"),
    "1792x2400":  ("3:4",  "2K"),
    "3584x4800":  ("3:4",  "4K"),
    # 4:3
    "1200x896":   ("4:3",  "1K"),
    "2400x1792":  ("4:3",  "2K"),
    "4800x3584":  ("4:3",  "4K"),
    # 4:5
    "928x1152":   ("4:5",  "1K"),
    "1856x2304":  ("4:5",  "2K"),
    "3712x4608":  ("4:5",  "4K"),
    # 5:4
    "1152x928":   ("5:4",  "1K"),
    "2304x1856":  ("5:4",  "2K"),
    "4608x3712":  ("5:4",  "4K"),
    # 9:16
    "768x1376":   ("9:16", "1K"),
    "1536x2752":  ("9:16", "2K"),
    "3072x5504":  ("9:16", "4K"),
    # 16:9
    "1376x768":   ("16:9", "1K"),
    "2752x1536":  ("16:9", "2K"),
    "5504x3072":  ("16:9", "4K"),
    # 21:9
    "1584x672":   ("21:9", "1K"),
    "3168x1344":  ("21:9", "2K"),
    "6336x2688":  ("21:9", "4K"),
}

# ── Gemini 3.1 Flash Image Preview (GG 3.1) ───────────────────────────────────
# Four quality tiers: 512 / 1K / 2K / 4K.
_GG_31_SIZES: SizeTable = {
    # 1:1
    "512x512":    ("1:1",  "512"),
    "1024x1024":  ("1:1",  "1K"),
    "2048x2048":  ("1:1",  "2K"),
    "4096x4096":  ("1:1",  "4K"),
    # 1:4
    "256x1024":   ("1:4",  "512"),
    "512x2048":   ("1:4",  "1K"),
    "1024x4096":  ("1:4",  "2K"),
    "2048x8192":  ("1:4",  "4K"),
    # 1:8
    "192x1536":   ("1:8",  "512"),
    "384x3072":   ("1:8",  "1K"),
    "768x6144":   ("1:8",  "2K"),
    "1536x12288": ("1:8",  "4K"),
    # 2:3
    "424x632":    ("2:3",  "512"),
    "848x1264":   ("2:3",  "1K"),
    "1696x2528":  ("2:3",  "2K"),
    "3392x5056":  ("2:3",  "4K"),
    # 3:2
    "632x424":    ("3:2",  "512"),
    "1264x848":   ("3:2",  "1K"),
    "2528x1696":  ("3:2",  "2K"),
    "5056x3392":  ("3:2",  "4K"),
    # 3:4
    "448x600":    ("3:4",  "512"),
    "896x1200":   ("3:4",  "1K"),
    "1792x2400":  ("3:4",  "2K"),
    "3584x4800":  ("3:4",  "4K"),
    # 4:1
    "1024x256":   ("4:1",  "512"),
    "2048x512":   ("4:1",  "1K"),
    "4096x1024":  ("4:1",  "2K"),
    "8192x2048":  ("4:1",  "4K"),
    # 4:3
    "600x448":    ("4:3",  "512"),
    "1200x896":   ("4:3",  "1K"),
    "2400x1792":  ("4:3",  "2K"),
    "4800x3584":  ("4:3",  "4K"),
    # 4:5
    "464x576":    ("4:5",  "512"),
    "928x1152":   ("4:5",  "1K"),
    "1856x2304":  ("4:5",  "2K"),
    "3712x4608":  ("4:5",  "4K"),
    # 5:4
    "576x464":    ("5:4",  "512"),
    "1152x928":   ("5:4",  "1K"),
    "2304x1856":  ("5:4",  "2K"),
    "4608x3712":  ("5:4",  "4K"),
    # 8:1
    "1536x192":   ("8:1",  "512"),
    "3072x384":   ("8:1",  "1K"),
    "6144x768":   ("8:1",  "2K"),
    "12288x1536": ("8:1",  "4K"),
    # 9:16
    "384x688":    ("9:16", "512"),
    "768x1376":   ("9:16", "1K"),
    "1536x2752":  ("9:16", "2K"),
    "3072x5504":  ("9:16", "4K"),
    # 16:9
    "688x384":    ("16:9", "512"),
    "1376x768":   ("16:9", "1K"),
    "2752x1536":  ("16:9", "2K"),
    "5504x3072":  ("16:9", "4K"),
    # 21:9
    "792x168":    ("21:9", "512"),
    "1584x672":   ("21:9", "1K"),
    "3168x1344":  ("21:9", "2K"),
    "6336x2688":  ("21:9", "4K"),
}


# ---------------------------------------------------------------------------
# Model → size table
# ---------------------------------------------------------------------------

_MODEL_SIZE_TABLES: Dict[str, SizeTable] = {
    "gemini-2.5-flash-image":         _GG_25_SIZES,
    "gemini-3-pro-image-preview":     _GG_30_SIZES,
    "gemini-3.1-flash-image-preview": _GG_31_SIZES,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_table(model: str) -> Optional[SizeTable]:
    return _MODEL_SIZE_TABLES.get(model.lower().strip())


def _norm(s: str) -> str:
    return s.lower().replace(" ", "")


def _lookup_wh(table: SizeTable, wh: str) -> Optional[SizeEntry]:
    """Exact WxH lookup → (aspect_ratio, resolution_tier)."""
    key = _norm(wh)
    for k, entry in table.items():
        if _norm(k) == key:
            return entry
    return None


def _default_for_ratio(table: SizeTable, aspect_ratio: str) -> Optional[SizeEntry]:
    """First (lowest-tier) entry whose aspect_ratio matches."""
    for entry in table.values():
        if entry[0] == aspect_ratio:
            return entry
    return None


def _entry_for_ratio_and_tier(table: SizeTable, aspect_ratio: str, tier: str) -> Optional[SizeEntry]:
    """Entry matching both aspect_ratio and resolution_tier."""
    tier_u = tier.upper()
    for entry in table.values():
        if entry[0] == aspect_ratio and entry[1].upper() == tier_u:
            return entry
    return None


def _default_for_tier(table: SizeTable, tier: str) -> Optional[SizeEntry]:
    """First "1:1" entry at the given tier; fallback: first entry at that tier."""
    tier_u = tier.upper()
    for entry in table.values():
        if entry[0] == "1:1" and entry[1].upper() == tier_u:
            return entry
    for entry in table.values():
        if entry[1].upper() == tier_u:
            return entry
    return None


def _looks_like_wh(s: str) -> bool:
    parts = s.lower().split("x")
    return len(parts) == 2 and all(p.strip().isdigit() for p in parts)


def _looks_like_ratio(s: str) -> bool:
    parts = s.split(":")
    if len(parts) != 2:
        return False
    try:
        float(parts[0].strip())
        float(parts[1].strip())
        return True
    except ValueError:
        return False


def _looks_like_tier(s: str) -> bool:
    return s.upper() in _TIER_LABELS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_image_size(
    model: str,
    size: str = "",
    aspect_ratio: str = "",
    resolution: str = "",
) -> Tuple[str, str]:
    """
    Resolve user inputs into ``(aspect_ratio, resolution_tier)`` for TencentVOD.

    ``resolution_tier`` is a label like "512", "1K", "2K", "4K" (or "" for
    models with only one resolution per aspect ratio like gemini-2.5-flash-image).

    Priority:
    1. ``resolution`` is a WxH string (e.g. "1024x1024") → table lookup
    2. ``resolution`` is a tier label (e.g. "1K") AND ``aspect_ratio`` set →
       return (aspect_ratio, tier), confirm via table if possible
    3. ``resolution`` is a tier label alone → pick "1:1" entry for that tier
    4. ``aspect_ratio`` set (no resolution) → pick default (lowest) tier for ratio
    5. ``size``:
       a. WxH  → table lookup
       b. W:H ratio → pick default entry for ratio
       c. Tier label → pick "1:1" entry for tier
    6. Nothing → ("", "")

    Returns:
        (aspect_ratio, resolution_tier)
    """
    table = _get_table(model)
    size = (size or "").strip()
    aspect_ratio = (aspect_ratio or "").strip()
    resolution = (resolution or "").strip()

    # ------------------------------------------------------------------
    # 1 & 2 & 3. User supplied an explicit resolution
    # ------------------------------------------------------------------
    if resolution:
        if _looks_like_wh(resolution):
            # It's a WxH pixel string — look it up
            if table:
                entry = _lookup_wh(table, resolution)
                if entry:
                    ar = aspect_ratio if aspect_ratio else entry[0]
                    return ar, entry[1]
            return aspect_ratio, ""

        if _looks_like_tier(resolution):
            # It's a tier label like "1K"
            tier = resolution.upper()
            if aspect_ratio:
                # Both aspect_ratio and tier known
                if table:
                    entry = _entry_for_ratio_and_tier(table, aspect_ratio, tier)
                    if entry:
                        return entry
                return aspect_ratio, tier
            else:
                # Only tier known — pick 1:1 default
                if table:
                    entry = _default_for_tier(table, tier)
                    if entry:
                        return entry
                return "1:1", tier

        # Unknown format — pass through
        return aspect_ratio, resolution

    # ------------------------------------------------------------------
    # 4. Explicit aspect_ratio (no resolution)
    # ------------------------------------------------------------------
    if aspect_ratio:
        if table:
            entry = _default_for_ratio(table, aspect_ratio)
            if entry:
                return entry
        return aspect_ratio, ""

    # ------------------------------------------------------------------
    # 5. Parse size
    # ------------------------------------------------------------------
    if not size:
        return "", ""

    # 5a. WxH pixel string
    if _looks_like_wh(size):
        if table:
            entry = _lookup_wh(table, size)
            if entry:
                return entry
        return "", ""

    # 5b. Aspect ratio string
    if _looks_like_ratio(size):
        ar = size
        if table:
            entry = _default_for_ratio(table, ar)
            if entry:
                return entry
        return ar, ""

    # 5c. Tier label
    if _looks_like_tier(size):
        tier = size.upper()
        if table:
            entry = _default_for_tier(table, tier)
            if entry:
                return entry
        return "1:1", tier

    # Fallback: treat as aspect_ratio
    if table:
        entry = _default_for_ratio(table, size)
        if entry:
            return entry
    return size, ""


# ---------------------------------------------------------------------------
# Utility accessors
# ---------------------------------------------------------------------------

def get_supported_sizes(model: str) -> List[Tuple[str, str, str]]:
    """
    Return all (wh, aspect_ratio, resolution_tier) triples for *model*.

    Useful for displaying the full size catalogue to users.
    """
    table = _get_table(model)
    if table is None:
        return []
    return [(wh, ar, tier) for wh, (ar, tier) in table.items()]


def get_supported_aspect_ratios(model: str) -> List[str]:
    """Return deduplicated list of aspect ratios for *model*."""
    table = _get_table(model)
    if table is None:
        return []
    seen: List[str] = []
    for ar, _ in table.values():
        if ar not in seen:
            seen.append(ar)
    return seen


def get_sizes_for_aspect_ratio(model: str, aspect_ratio: str) -> List[Tuple[str, str]]:
    """
    Return all (wh, resolution_tier) pairs for *model* + *aspect_ratio*,
    ordered from lowest to highest resolution.
    """
    table = _get_table(model)
    if table is None:
        return []
    results = [(wh, tier) for wh, (ar, tier) in table.items() if ar == aspect_ratio]

    def _pixels(pair: Tuple[str, str]) -> int:
        try:
            w, h = pair[0].lower().split("x")
            return int(w) * int(h)
        except Exception:
            return 0

    return sorted(results, key=_pixels)
