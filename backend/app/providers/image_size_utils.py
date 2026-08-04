"""
Image Size / Resolution Utility (shared)
=========================================

Provides a unified ``WxH → (aspect_ratio, resolution_tier)`` lookup table
spanning all image-generation providers (TencentVOD, Volcengine Seedream,
Bailian Z-Image, Gemini, GPT Image 2), and a ``resolve_image_size()`` helper
that turns a user-supplied ``size``, ``aspect_ratio``, or ``resolution``
parameter into the ``(aspect_ratio, resolution_tier)`` pair.

Z-Image Turbo (Bailian) uses its own dedicated table (``Z_IMAGE_SIZE_MAP``):
its size set (two 1K groups plus a 2K group, incl. ``1280x1280`` and the
``1024x1536`` / ``1536x1024`` pair) must not be merged into the shared
table, which serves GPT Image 2 (Vidu) 1K sizes of the same pixel
dimensions.

Key distinction
---------------
``resolution`` in the TencentVOD API is a **quality tier label** ("512", "1K",
"1.5K", "2K", "3K", "4K"), NOT a pixel string.  This module's tables encode:

    WxH pixel string  →  (aspect_ratio, resolution_tier)

Examples
    "512x512"    →  ("1:1",  "512")
    "1280x1280"  →  ("1:1",  "1.5K")
    "5504x3072"  →  ("16:9", "4K")

Usage
-----
    from app.providers.image_size_utils import resolve_image_size

    aspect_ratio, resolution_tier = resolve_image_size(
        size=metadata.get("size", ""),
        aspect_ratio=metadata.get("aspect_ratio", ""),
        resolution=metadata.get("resolution", ""),
    )
    # Pass aspect_ratio and (optionally) resolution_tier to downstream APIs

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
# resolution_tier: "512" | "1K" | "1.5K" | "2K" | "3K" | "4K" | ""
SizeEntry = Tuple[str, str]
# WxH string → SizeEntry
SizeTable = Dict[str, SizeEntry]

_TIER_LABELS = {"512", "1K", "1.5K", "2K", "3K", "4K", "0.5K"}


# ---------------------------------------------------------------------------
# Unified image size table  —  WxH  →  (aspect_ratio, resolution_tier)
# ---------------------------------------------------------------------------
#
# Merged from: Gemini 2.5 Flash / 3 Pro / 3.1 Flash, GPT Image 2 (Vidu),
# Volcengine Seedream 4.0/4.5/5.0.  Z-Image Turbo has its own dedicated
# table (``Z_IMAGE_SIZE_MAP`` below): its ``1024x1536`` / ``1536x1024``
# sizes belong to a different size group there, so the tables stay separate.
#
# Entries are ordered by increasing tier so that _default_for_ratio()
# returns the lowest-resolution entry for each aspect ratio.

IMAGE_SIZE_MAP: SizeTable = {
    # ═══════════════════════════════════════════════════════════════════════
    # 512 tier (Gemini 3.1 Flash — ultra-low resolution)
    # ═══════════════════════════════════════════════════════════════════════
    "512x512":    ("1:1",  "512"),
    "256x1024":   ("1:4",  "512"),
    "192x1536":   ("1:8",  "512"),
    "424x632":    ("2:3",  "512"),
    "632x424":    ("3:2",  "512"),
    "448x600":    ("3:4",  "512"),
    "1024x256":   ("4:1",  "512"),
    "600x448":    ("4:3",  "512"),
    "464x576":    ("4:5",  "512"),
    "576x464":    ("5:4",  "512"),
    "1536x192":   ("8:1",  "512"),
    "384x688":    ("9:16", "512"),
    "688x384":    ("16:9", "512"),
    "792x168":    ("21:9", "512"),

    # ═══════════════════════════════════════════════════════════════════════
    # 1K tier
    # Sources: GG 2.5 Flash, GG 3 Pro, GG 3.1 Flash, GPT Image 2,
    #          Seedream 4.0 / 5.0 pro, Z-Image Turbo
    # ═══════════════════════════════════════════════════════════════════════
    # 1:1
    "1024x1024":  ("1:1",  "1K"),
    # 1:4
    "512x2048":   ("1:4",  "1K"),
    # 1:8
    "384x3072":   ("1:8",  "1K"),
    # 2:3
    "832x1248":   ("2:3",  "1K"),
    "848x1264":   ("2:3",  "1K"),
    # GPT Image 2 (Vidu) — 1K 2:3 (also present in Z_IMAGE_SIZE_MAP).
    "1024x1536":  ("2:3",  "1K"),
    # 3:2
    "1248x832":   ("3:2",  "1K"),
    "1264x848":   ("3:2",  "1K"),
    "1536x1024":  ("3:2",  "1K"),
    # 3:4
    "864x1152":   ("3:4",  "1K"),
    "864x1184":   ("3:4",  "1K"),
    "896x1200":   ("3:4",  "1K"),
    "768x1024":   ("3:4",  "1K"),
    # 4:1
    "2048x512":   ("4:1",  "1K"),
    # 4:3
    "1152x864":   ("4:3",  "1K"),
    "1184x864":   ("4:3",  "1K"),
    "1200x896":   ("4:3",  "1K"),
    "1024x768":   ("4:3",  "1K"),
    # 4:5
    "928x1152":   ("4:5",  "1K"),
    # 5:4
    "1152x928":   ("5:4",  "1K"),
    # 7:9 (Z-Image unique ratio)
    "896x1152":   ("7:9",  "1K"),
    # 9:7 (Z-Image unique ratio)
    "1152x896":   ("9:7",  "1K"),
    # 8:1
    "3072x384":   ("8:1",  "1K"),
    # 9:16
    "800x1424":   ("9:16", "1K"),
    "720x1280":   ("9:16", "1K"),
    "736x1312":   ("9:16", "1K"),
    "768x1344":   ("9:16", "1K"),
    "768x1376":   ("9:16", "1K"),
    "576x1024":   ("9:16", "1K"),
    # 9:21
    "576x1344":   ("9:21", "1K"),
    "439x1024":   ("9:21", "1K"),
    # 16:9
    "1424x800":   ("16:9", "1K"),
    "1280x720":   ("16:9", "1K"),
    "1312x736":   ("16:9", "1K"),
    "1344x768":   ("16:9", "1K"),
    "1376x768":   ("16:9", "1K"),
    "1024x576":   ("16:9", "1K"),
    # 21:9
    "1344x576":   ("21:9", "1K"),
    "1536x672":   ("21:9", "1K"),
    "1568x672":   ("21:9", "1K"),
    "1584x672":   ("21:9", "1K"),
    "1024x439":   ("21:9", "1K"),

    # ═══════════════════════════════════════════════════════════════════════
    # 2K tier
    # Sources: GG 3 Pro, GG 3.1 Flash, GPT Image 2, Seedream, Z-Image
    # ═══════════════════════════════════════════════════════════════════════
    # 1:1
    "2048x2048":  ("1:1",  "2K"),
    # 1:4
    "1024x4096":  ("1:4",  "2K"),
    # 1:8
    "768x6144":   ("1:8",  "2K"),
    # 2:3
    "1248x1872":  ("2:3",  "2K"),
    "1664x2496":  ("2:3",  "2K"),
    "1696x2528":  ("2:3",  "2K"),
    "2048x3072":  ("2:3",  "2K"),
    # 3:2
    "1872x1248":  ("3:2",  "2K"),
    "2496x1664":  ("3:2",  "2K"),
    "2528x1696":  ("3:2",  "2K"),
    "3072x2048":  ("3:2",  "2K"),
    # 3:4
    "1776x2368":  ("3:4",  "2K"),
    "1296x1728":  ("3:4",  "2K"),
    "1536x2048":  ("3:4",  "2K"),
    "1728x2304":  ("3:4",  "2K"),
    "1792x2400":  ("3:4",  "2K"),
    # 4:1
    "4096x1024":  ("4:1",  "2K"),
    # 4:3
    "2368x1776":  ("4:3",  "2K"),
    "1728x1296":  ("4:3",  "2K"),
    "2048x1536":  ("4:3",  "2K"),
    "2304x1728":  ("4:3",  "2K"),
    "2400x1792":  ("4:3",  "2K"),
    # 4:5
    "1856x2304":  ("4:5",  "2K"),
    # 5:4
    "2304x1856":  ("5:4",  "2K"),
    # 7:9
    "1344x1728":  ("7:9",  "2K"),
    # 9:7
    "1728x1344":  ("9:7",  "2K"),
    # 8:1
    "6144x768":   ("8:1",  "2K"),
    # 9:16
    "1584x2816":  ("9:16", "2K"),
    "1152x2048":  ("9:16", "2K"),
    "1536x2752":  ("9:16", "2K"),
    "1600x2848":  ("9:16", "2K"),
    # 9:21
    "864x2016":   ("9:21", "2K"),
    "878x2048":   ("9:21", "2K"),
    # 16:9
    "2816x1584":  ("16:9", "2K"),
    "2048x1152":  ("16:9", "2K"),
    "2752x1536":  ("16:9", "2K"),
    "2848x1600":  ("16:9", "2K"),
    # 21:9
    "2016x864":   ("21:9", "2K"),
    "2048x878":   ("21:9", "2K"),
    "3136x1344":  ("21:9", "2K"),
    "3168x1344":  ("21:9", "2K"),

    # ═══════════════════════════════════════════════════════════════════════
    # 3K tier (Seedream 5.0 lite only)
    # ═══════════════════════════════════════════════════════════════════════
    "3072x3072":  ("1:1",  "3K"),
    "2496x3744":  ("2:3",  "3K"),
    "3744x2496":  ("3:2",  "3K"),
    "2592x3456":  ("3:4",  "3K"),
    "3456x2592":  ("4:3",  "3K"),
    "2304x4096":  ("9:16", "3K"),
    "4096x2304":  ("16:9", "3K"),
    "4704x2016":  ("21:9", "3K"),

    # ═══════════════════════════════════════════════════════════════════════
    # 4K tier
    # Sources: GG 3 Pro, GG 3.1 Flash, GPT Image 2, Seedream 4.0/4.5
    # ═══════════════════════════════════════════════════════════════════════
    # 1:1
    "3840x3840":  ("1:1",  "4K"),
    "4096x4096":  ("1:1",  "4K"),
    # 1:4
    "2048x8192":  ("1:4",  "4K"),
    # 1:8
    "1536x12288": ("1:8",  "4K"),
    # 2:3
    "2560x3840":  ("2:3",  "4K"),
    "3328x4992":  ("2:3",  "4K"),
    "3392x5056":  ("2:3",  "4K"),
    # 3:2
    "3840x2560":  ("3:2",  "4K"),
    "4992x3328":  ("3:2",  "4K"),
    "5056x3392":  ("3:2",  "4K"),
    # 3:4
    "2880x3840":  ("3:4",  "4K"),
    "3520x4704":  ("3:4",  "4K"),
    "3584x4800":  ("3:4",  "4K"),
    # 4:1
    "8192x2048":  ("4:1",  "4K"),
    # 4:3
    "3840x2880":  ("4:3",  "4K"),
    "4704x3520":  ("4:3",  "4K"),
    "4800x3584":  ("4:3",  "4K"),
    # 4:5
    "3712x4608":  ("4:5",  "4K"),
    # 5:4
    "4608x3712":  ("5:4",  "4K"),
    # 8:1
    "12288x1536": ("8:1",  "4K"),
    # 9:16
    "2160x3840":  ("9:16", "4K"),
    "3040x5504":  ("9:16", "4K"),
    "3072x5504":  ("9:16", "4K"),
    # 9:21
    "1646x3840":  ("9:21", "4K"),
    # 16:9
    "3840x2160":  ("16:9", "4K"),
    "5504x3072":  ("16:9", "4K"),
    "5504x3040":  ("16:9", "4K"),
    # 21:9
    "3840x1646":  ("21:9", "4K"),
    "6240x2656":  ("21:9", "4K"),
    "6336x2688":  ("21:9", "4K"),
}

# ---------------------------------------------------------------------------
# Z-Image Turbo dedicated table  —  WxH  →  (aspect_ratio, resolution_tier)
# ---------------------------------------------------------------------------
#
# Bailian Z-Image Turbo exposes its own size set in two tiers (1K / 2K).
# The upstream "larger 1K" group (1280x1280 … 1680x720) is merged into the
# 1K tier — its ``1024x1536`` / ``1536x1024`` entries would otherwise
# collide with GPT Image 2 (Vidu) 1K entries in the shared table.
#
# This must stay separate from IMAGE_SIZE_MAP: Z-Image has unique ratios
# (7:9 / 9:7) and sizes (1280x1280, 1104x1472, …) that belong to its own
# 1K group, while the shared table serves GPT Image 2 (Vidu).
#
# Within the 1K tier, the 1280…1680 group is listed FIRST so the reverse
# lookup (last entry wins per (tier, ratio)) returns the canonical
# 1024…1344 group for tier-based "1K" resolutions.
Z_IMAGE_SIZE_MAP: SizeTable = {
    # ── 1K 档（两档尺寸组均归属 1K）────────────────────────────────────
    # 1280…1680 组（原 1.5K 命名，现归入 1K）
    "1280x1280": ("1:1",  "1K"),
    "1024x1536": ("2:3",  "1K"),
    "1536x1024": ("3:2",  "1K"),
    "1104x1472": ("3:4",  "1K"),
    "1472x1104": ("4:3",  "1K"),
    "1120x1440": ("7:9",  "1K"),
    "1440x1120": ("9:7",  "1K"),
    "864x1536":  ("9:16", "1K"),
    "720x1680":  ("9:21", "1K"),
    "1536x864":  ("16:9", "1K"),
    "1680x720":  ("21:9", "1K"),
    # 1024…1344 组（标准 1K）
    "1024x1024": ("1:1",  "1K"),
    "832x1248":  ("2:3",  "1K"),
    "1248x832":  ("3:2",  "1K"),
    "864x1152":  ("3:4",  "1K"),
    "1152x864":  ("4:3",  "1K"),
    "896x1152":  ("7:9",  "1K"),
    "1152x896":  ("9:7",  "1K"),
    "720x1280":  ("9:16", "1K"),
    "576x1344":  ("9:21", "1K"),
    "1280x720":  ("16:9", "1K"),
    "1344x576":  ("21:9", "1K"),
    # ── 2K 档 ──────────────────────────────────────────────────────────
    "1536x1536": ("1:1",  "2K"),
    "1248x1872": ("2:3",  "2K"),
    "1872x1248": ("3:2",  "2K"),
    "1296x1728": ("3:4",  "2K"),
    "1728x1296": ("4:3",  "2K"),
    "1344x1728": ("7:9",  "2K"),
    "1728x1344": ("9:7",  "2K"),
    "1152x2048": ("9:16", "2K"),
    "864x2016":  ("9:21", "2K"),
    "2048x1152": ("16:9", "2K"),
    "2016x864":  ("21:9", "2K"),
}

# ── Reverse lookup: (tier, aspect_ratio) → WxH ─────────────────────────
# Used by providers that need to reconstruct exact pixel dimensions from
# resolved (aspect_ratio, tier).  Built from IMAGE_SIZE_MAP; later (higher
# tier) entries override earlier ones for the same (tier, ratio) key.

_TIER_RATIO_TO_WH: Dict[Tuple[str, str], str] = {}
for _wh, (_ar, _tier) in IMAGE_SIZE_MAP.items():
    _TIER_RATIO_TO_WH[(_tier, _ar)] = _wh


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return s.lower().replace(" ", "")


def _lookup_wh(wh: str, table: SizeTable = IMAGE_SIZE_MAP) -> Optional[SizeEntry]:
    """Exact WxH lookup → (aspect_ratio, resolution_tier)."""
    key = _norm(wh).replace("*", "x")
    for k, entry in table.items():
        if _norm(k) == key:
            return entry
    return None


def _default_for_ratio(aspect_ratio: str, table: SizeTable = IMAGE_SIZE_MAP) -> Optional[SizeEntry]:
    """First (lowest-tier) entry whose aspect_ratio matches."""
    for entry in table.values():
        if entry[0] == aspect_ratio:
            return entry
    return None


def _entry_for_ratio_and_tier(aspect_ratio: str, tier: str, table: SizeTable = IMAGE_SIZE_MAP) -> Optional[SizeEntry]:
    """Entry matching both aspect_ratio and resolution_tier."""
    tier_u = tier.upper()
    for entry in table.values():
        if entry[0] == aspect_ratio and entry[1].upper() == tier_u:
            return entry
    return None


def _default_for_tier(tier: str, table: SizeTable = IMAGE_SIZE_MAP) -> Optional[SizeEntry]:
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
    # Accept both "WxH" and "W*H" (used by Dashscope/Bailian)
    sep = "x" if "x" in s.lower() else ("*" if "*" in s else None)
    if sep is None:
        return False
    parts = s.lower().split(sep)
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
    size: str = "",
    aspect_ratio: str = "",
    resolution: str = "",
    table: SizeTable = IMAGE_SIZE_MAP,
) -> Tuple[str, str]:
    """
    Resolve user inputs into ``(aspect_ratio, resolution_tier)``.

    ``resolution_tier`` is a quality label like "512", "1K", "1.5K", "2K",
    "3K", "4K" (or "" if unresolvable).

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
        (aspect_ratio, resolution_tier) — both empty strings if unresolvable.

    ``table`` selects the lookup table; providers with provider-specific size
    sets (e.g. Bailian Z-Image Turbo → ``Z_IMAGE_SIZE_MAP``) pass their own.
    """
    size = (size or "").strip()
    aspect_ratio = (aspect_ratio or "").strip()
    resolution = (resolution or "").strip()

    # ------------------------------------------------------------------
    # 1 & 2 & 3. User supplied an explicit resolution
    # ------------------------------------------------------------------
    if resolution:
        if _looks_like_wh(resolution):
            entry = _lookup_wh(resolution, table)
            if entry:
                ar = aspect_ratio if aspect_ratio else entry[0]
                return ar, entry[1]
            return aspect_ratio, ""

        if _looks_like_tier(resolution):
            tier = resolution.upper()
            if aspect_ratio:
                entry = _entry_for_ratio_and_tier(aspect_ratio, tier, table)
                if entry:
                    return entry
                return aspect_ratio, tier
            else:
                entry = _default_for_tier(tier, table)
                if entry:
                    return entry
                return "1:1", tier

        return aspect_ratio, resolution

    # ------------------------------------------------------------------
    # 4. Explicit aspect_ratio (no resolution)
    # ------------------------------------------------------------------
    if aspect_ratio:
        # If size looks like a tier label, combine tier + aspect_ratio
        if _looks_like_tier(size):
            tier = size.upper()
            entry = _entry_for_ratio_and_tier(aspect_ratio, tier, table)
            if entry:
                return entry
            return aspect_ratio, tier
        entry = _default_for_ratio(aspect_ratio, table)
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
        entry = _lookup_wh(size, table)
        if entry:
            return entry
        return "", ""

    # 5b. Aspect ratio string
    if _looks_like_ratio(size):
        ar = size
        entry = _default_for_ratio(ar, table)
        if entry:
            return entry
        return ar, ""

    # 5c. Tier label
    if _looks_like_tier(size):
        tier = size.upper()
        entry = _default_for_tier(tier, table)
        if entry:
            return entry
        return "1:1", tier

    # Fallback: treat as aspect_ratio
    entry = _default_for_ratio(size, table)
    if entry:
        return entry
    return size, ""


def get_pixel_size(aspect_ratio: str, tier: str, table: SizeTable = IMAGE_SIZE_MAP) -> str:
    """
    Reverse lookup: given (aspect_ratio, tier), return the WxH pixel string.

    Returns empty string if no matching entry exists.
    """
    if table is IMAGE_SIZE_MAP:
        reverse = _TIER_RATIO_TO_WH
    else:
        reverse = {}
        for wh, (ar, t) in table.items():
            reverse[(t, ar)] = wh
    return reverse.get((tier, aspect_ratio), "")


def resolve_pixel_size(
    size: str = "",
    aspect_ratio: str = "",
    resolution: str = "",
    sep: str = "x",
    table: SizeTable = IMAGE_SIZE_MAP,
) -> str:
    """
    Resolve size/aspect_ratio/resolution to a concrete WxH pixel string.

    This is a convenience wrapper around ``resolve_image_size()`` +
    ``get_pixel_size()`` for providers (e.g. Bailian/Dashscope) that need
    an exact pixel dimension rather than a (ratio, tier) tuple.

    Args:
        size: User-supplied size string (WxH, W:H, or tier label).
        aspect_ratio: User-supplied aspect ratio (e.g. "16:9").
        resolution: User-supplied resolution (tier label or WxH).
        sep: Separator for the output WxH string ("x" or "*").

    Returns:
        Resolved WxH string (e.g. "1024x1024"), or "" if unresolvable.
    """
    # If size is already a pixel value, normalise and return
    size_str = (size or "").strip()
    if size_str:
        # Accept both "WxH" and "W*H" as direct pixel input
        normalized = size_str.lower().replace("*", "x")
        if _looks_like_wh(normalized):
            return normalized.replace("x", sep)

    ar, tier = resolve_image_size(
        size=size, aspect_ratio=aspect_ratio, resolution=resolution, table=table
    )
    if ar and tier:
        wh = get_pixel_size(ar, tier, table=table)
        if wh:
            return wh.replace("x", sep)
    return ""


# ---------------------------------------------------------------------------
# Utility accessors
# ---------------------------------------------------------------------------

def get_supported_sizes() -> List[Tuple[str, str, str]]:
    """Return all (wh, aspect_ratio, resolution_tier) triples."""
    return [(wh, ar, tier) for wh, (ar, tier) in IMAGE_SIZE_MAP.items()]


def get_supported_aspect_ratios() -> List[str]:
    """Return deduplicated list of all supported aspect ratios."""
    seen: List[str] = []
    for ar, _ in IMAGE_SIZE_MAP.values():
        if ar not in seen:
            seen.append(ar)
    return seen


def get_sizes_for_aspect_ratio(aspect_ratio: str) -> List[Tuple[str, str]]:
    """
    Return all (wh, resolution_tier) pairs for *aspect_ratio*,
    ordered from lowest to highest resolution.
    """
    results = [(wh, tier) for wh, (ar, tier) in IMAGE_SIZE_MAP.items() if ar == aspect_ratio]

    def _pixels(pair: Tuple[str, str]) -> int:
        try:
            w, h = pair[0].lower().split("x")
            return int(w) * int(h)
        except Exception:
            return 0

    return sorted(results, key=_pixels)
