"""
视频尺寸工具模块 (Video Size Utilities)

提供视频尺寸字符串到宽高比 (AspectRatio) 和分辨率档位 (Resolution Tier) 的解析功能。

支持的输入格式:
  1. 命名档位 (case-insensitive): "480p", "720p", "1080p", "2K", "4K", "8K"
  2. 像素尺寸 "WxH": "1920x1080", "1080x1920", "2560x1440" 等
  3. 任意自定义 WxH: 按 GCD 推导宽高比，无标准档位名称

返回值:
  (aspect_ratio, resolution_tier)
  - aspect_ratio:     宽高比字符串，如 "16:9"、"9:16"、"1:1"
  - resolution_tier:  标准档位名称，如 "720p"、"1080p"、"4K"；
                      自定义尺寸时为空字符串

典型用途:
  - TencentVOD CreateAigcVideoTask → OutputConfig.AspectRatio / OutputConfig.Resolution
"""
from __future__ import annotations

from math import gcd
from typing import Dict, Tuple


# =============================================================================
# 宽高比速查表
# =============================================================================

_ASPECT_RATIO_MAP: Dict[Tuple[int, int], str] = {
    (16, 9):  "16:9",
    (9, 16):  "9:16",
    (1, 1):   "1:1",
    (4, 3):   "4:3",
    (3, 4):   "3:4",
    (3, 2):   "3:2",
    (2, 3):   "2:3",
    (21, 9):  "21:9",
    (9, 21):  "9:21",
    (17, 9):  "17:9",
    (9, 17):  "9:17",
}


# =============================================================================
# 标准视频尺寸查找表
# =============================================================================

# Keys:   "WxH" (lowercase)
# Values: (aspect_ratio, resolution_tier)
#
# resolution_tier 是 TencentVOD API 使用的标准档位名称
# (e.g. "480p", "720p", "1080p", "2K", "4K", "8K")
#
# 横屏 (Landscape) 和竖屏 (Portrait) 均已收录。

VIDEO_SIZE_TABLE: Dict[str, Tuple[str, str]] = {
    # ── SD (480p) ─────────────────────────────────────────────────────────
    "854x480":   ("16:9",  "480p"),
    "480x854":   ("9:16",  "480p"),
    "640x480":   ("4:3",   "480p"),
    "480x640":   ("3:4",   "480p"),
    # ── HD (720p) ────────────────────────────────────────────────────────
    "1280x720":  ("16:9",  "720p"),
    "720x1280":  ("9:16",  "720p"),
    # ── Full HD (1080p) ──────────────────────────────────────────────────
    "1920x1080": ("16:9",  "1080p"),
    "1080x1920": ("9:16",  "1080p"),
    # ── QHD / 2K ──────────────────────────────────────────────────────────
    "2560x1440": ("16:9",  "2K"),
    "1440x2560": ("9:16",  "2K"),
    # ── DCI 2K ────────────────────────────────────────────────────────────
    "2048x1080": ("17:9",  "2K"),
    "1080x2048": ("9:17",  "2K"),
    # ── 4K UHD ────────────────────────────────────────────────────────────
    "3840x2160": ("16:9",  "4K"),
    "2160x3840": ("9:16",  "4K"),
    # ── DCI 4K ────────────────────────────────────────────────────────────
    "4096x2160": ("17:9",  "4K"),
    "2160x4096": ("9:17",  "4K"),
    # ── 8K ────────────────────────────────────────────────────────────────
    "7680x4320": ("16:9",  "8K"),
    "4320x7680": ("9:16",  "8K"),
    # ── Square ────────────────────────────────────────────────────────────
    "1080x1080": ("1:1",   "1080p"),
    "720x720":   ("1:1",   "720p"),
}

# 命名档位 → 对应的标准 WxH (用于通过名称查找表)
VIDEO_NAME_TO_SIZE: Dict[str, str] = {
    "480p":  "854x480",
    "720p":  "1280x720",
    "1080p": "1920x1080",
    "2k":    "2560x1440",
    "qhd":   "2560x1440",
    "4k":    "3840x2160",
    "uhd":   "3840x2160",
    "8k":    "7680x4320",
}

# 命名档位 → resolution_tier
VIDEO_NAME_TO_TIER: Dict[str, str] = {
    "480p":  "480p",
    "720p":  "720p",
    "1080p": "1080p",
    "2k":    "2K",
    "qhd":   "2K",
    "4k":    "4K",
    "uhd":   "4K",
    "8k":    "8K",
}


# =============================================================================
# 公共 API
# =============================================================================

def resolve_video_size(size: str) -> Tuple[str, str]:
    """
    将视频尺寸字符串解析为 (aspect_ratio, resolution_tier)。

    ``resolution_tier`` 为 TencentVOD API 使用的标准档位名称，
    例如 "480p"、"720p"、"1080p"、"2K"、"4K"、"8K"。

    支持的输入格式:
      1. 命名档位 (大小写无关): "1080p"、"4K"、"720p"
         → 通过 VIDEO_NAME_TO_SIZE 解析为 WxH，再查询 VIDEO_SIZE_TABLE。
      2. WxH 像素尺寸: "1920x1080"、"1080x1920"
         → 精确匹配 VIDEO_SIZE_TABLE 获取档位名称；
           未命中时按 GCD 推导宽高比，resolution_tier 留空。
      3. 其他值 → 返回 ("", "")。

    Args:
        size: 用户传入的尺寸字符串。

    Returns:
        (aspect_ratio, resolution_tier) 元组；
        无法解析时两者均为空字符串。

    Examples:
        >>> resolve_video_size("1920x1080")
        ('16:9', '1080p')
        >>> resolve_video_size("1080x1920")
        ('9:16', '1080p')
        >>> resolve_video_size("4K")
        ('16:9', '4K')
        >>> resolve_video_size("2560x1440")
        ('16:9', '2K')
        >>> resolve_video_size("1600x900")
        ('16:9', '')
        >>> resolve_video_size("")
        ('', '')
    """
    if not size:
        return "", ""

    normalized = size.strip().lower().replace(" ", "")

    # 1. 命名档位 (e.g. "1080p", "4K")
    if normalized in VIDEO_NAME_TO_SIZE:
        canonical_wxh = VIDEO_NAME_TO_SIZE[normalized]
        if canonical_wxh in VIDEO_SIZE_TABLE:
            ar, _ = VIDEO_SIZE_TABLE[canonical_wxh]
            return ar, VIDEO_NAME_TO_TIER.get(normalized, "")
        return "", VIDEO_NAME_TO_TIER.get(normalized, "")

    # 2. 精确 WxH 查找
    if normalized in VIDEO_SIZE_TABLE:
        return VIDEO_SIZE_TABLE[normalized]

    # 3. 自定义 WxH → 按 GCD 推导宽高比，无标准档位
    if "x" in normalized:
        try:
            parts = normalized.split("x", 1)
            w, h = int(parts[0].strip()), int(parts[1].strip())
            if w > 0 and h > 0:
                g = gcd(w, h)
                ratio = (w // g, h // g)
                ar = _ASPECT_RATIO_MAP.get(ratio, f"{ratio[0]}:{ratio[1]}")
                return ar, ""
        except (ValueError, TypeError):
            pass

    return "", ""


def derive_aspect_ratio(size: str) -> str:
    """
    仅返回宽高比字符串（``resolve_video_size`` 的便捷包装）。

    Args:
        size: 尺寸字符串，如 "1920x1080"、"720p"

    Returns:
        宽高比字符串，如 "16:9"；无法解析时返回空字符串。
    """
    ar, _ = resolve_video_size(size)
    return ar


# =============================================================================
# Seedance 视频尺寸映射表
# =============================================================================
# Seedance 系列按 "WxH" → (resolution_tier, aspect_ratio) 正向映射。
# 分为两套：
#   - SEEDANCE_V1_SIZE_TABLE:     Seedance 1.0 系列
#   - SEEDANCE_V15_V2_SIZE_TABLE: Seedance 1.5 Pro / 2.0 / 2.0 Fast

# Seedance 1.0 系列
# Key: "WxH"  Value: (resolution_tier, aspect_ratio)
SEEDANCE_V1_SIZE_TABLE: Dict[str, Tuple[str, str]] = {
    # ── 480p ──────────────────────────────────
    "864x480":   ("480p", "16:9"),
    "736x544":   ("480p", "4:3"),
    "640x640":   ("480p", "1:1"),
    "544x736":   ("480p", "3:4"),
    "480x864":   ("480p", "9:16"),
    "960x416":   ("480p", "21:9"),
    # ── 720p ──────────────────────────────────
    "1248x704":  ("720p", "16:9"),
    "1120x832":  ("720p", "4:3"),
    "960x960":   ("720p", "1:1"),
    "832x1120":  ("720p", "3:4"),
    "704x1248":  ("720p", "9:16"),
    "1504x640":  ("720p", "21:9"),
    # ── 1080p ─────────────────────────────────
    "1920x1088": ("1080p", "16:9"),
    "1664x1248": ("1080p", "4:3"),
    "1440x1440": ("1080p", "1:1"),
    "1248x1664": ("1080p", "3:4"),
    "1088x1920": ("1080p", "9:16"),
    "2176x928":  ("1080p", "21:9"),
}

# Seedance 1.5 Pro / 2.0 / 2.0 Fast 系列
# Key: "WxH"  Value: (resolution_tier, aspect_ratio)
SEEDANCE_V15_V2_SIZE_TABLE: Dict[str, Tuple[str, str]] = {
    # ── 480p ──────────────────────────────────
    "864x496":   ("480p", "16:9"),
    "752x560":   ("480p", "4:3"),
    "640x640":   ("480p", "1:1"),
    "560x752":   ("480p", "3:4"),
    "496x864":   ("480p", "9:16"),
    "992x432":   ("480p", "21:9"),
    # ── 720p ──────────────────────────────────
    "1280x720":  ("720p", "16:9"),
    "1112x834":  ("720p", "4:3"),
    "960x960":   ("720p", "1:1"),
    "834x1112":  ("720p", "3:4"),
    "720x1280":  ("720p", "9:16"),
    "1470x630":  ("720p", "21:9"),
    # ── 1080p ─────────────────────────────────
    "1920x1080": ("1080p", "16:9"),
    "1664x1248": ("1080p", "4:3"),
    "1440x1440": ("1080p", "1:1"),
    "1248x1664": ("1080p", "3:4"),
    "1080x1920": ("1080p", "9:16"),
    "2206x946":  ("1080p", "21:9"),
}

# 合并反查表: 像素尺寸 → (resolution_tier, aspect_ratio)
# 先合并两套，V15_V2 优先（覆盖相同 WxH 的 V1 条目）
_SEEDANCE_PIXEL_TO_TIER_RATIO: Dict[str, Tuple[str, str]] = {}
_SEEDANCE_PIXEL_TO_TIER_RATIO.update(SEEDANCE_V1_SIZE_TABLE)
_SEEDANCE_PIXEL_TO_TIER_RATIO.update(SEEDANCE_V15_V2_SIZE_TABLE)

# 各套的反查表: (resolution_tier, aspect_ratio) → "WxH"（用于按档位+比例查像素）
_SEEDANCE_V1_TIER_RATIO_TO_PIXEL: Dict[Tuple[str, str], str] = {
    v: k for k, v in SEEDANCE_V1_SIZE_TABLE.items()
}
_SEEDANCE_V15_V2_TIER_RATIO_TO_PIXEL: Dict[Tuple[str, str], str] = {
    v: k for k, v in SEEDANCE_V15_V2_SIZE_TABLE.items()
}


def resolve_seedance_size(
    size: str,
    model: str = "",
) -> Tuple[str, str, str]:
    """
    将尺寸字符串解析为 Seedance API 所需的 (ratio, resolution, pixel_size)。

    ``ratio``      — 宽高比字符串，如 "16:9"（对应 API 参数 ratio）
    ``resolution`` — 分辨率档位，如 "720p"（对应 API 参数 resolution）
    ``pixel_size`` — 实际像素尺寸，如 "1280x720"（仅供参考/日志）

    解析优先级:
      1. 精确像素尺寸 (WxH) → 查询 Seedance 反查表，得到 (tier, ratio)，
         再根据模型系列查询对应的标准像素尺寸
      2. 命名档位 + 宽高比 (如 "720p") → ratio 未知，返回 ("", "720p", "")
      3. 通用 resolve_video_size() 兜底

    Args:
        size:  用户传入的尺寸字符串
        model: 模型名称（用于判断使用哪套像素表，默认使用 1.5/2.0 系列）

    Returns:
        (ratio, resolution, pixel_size) 三元组，无法解析时返回 ("", "", "")
    """
    if not size:
        return "", "", ""

    normalized = size.strip().lower().replace(" ", "")

    # 判断使用哪套尺寸表（1.0 系列 vs 1.5/2.0 系列）
    # 本函数仅对 Seedance 模型调用，直接按版本号区分：
    #   doubao-seedance-1-0-pro-250528      → V1 表（含 "1-0"）
    #   doubao-seedance-1-0-pro-fast-251015 → V1 表（含 "1-0"）
    #   doubao-seedance-1-5-pro-251215      → V1.5/V2 表
    #   doubao-seedance-2-0-260128          → V1.5/V2 表
    #   doubao-seedance-2-0-fast-260128     → V1.5/V2 表
    model_lower = model.lower()
    use_v1 = "1-0" in model_lower or "1.0" in model_lower

    # 各套的 (tier, ratio) → WxH 反查表
    reverse_table = (
        _SEEDANCE_V1_TIER_RATIO_TO_PIXEL
        if use_v1
        else _SEEDANCE_V15_V2_TIER_RATIO_TO_PIXEL
    )

    # 1. 精确像素尺寸查找
    if normalized in _SEEDANCE_PIXEL_TO_TIER_RATIO:
        tier, ratio = _SEEDANCE_PIXEL_TO_TIER_RATIO[normalized]
        # 取当前模型系列对应的标准像素尺寸
        pixel_size = reverse_table.get((tier, ratio), normalized)
        return ratio, tier, pixel_size

    # 2. 命名档位 (e.g. "720p", "1080p")
    if normalized in VIDEO_NAME_TO_TIER:
        tier = VIDEO_NAME_TO_TIER[normalized]
        return "", tier, ""

    # 3. 通用解析兜底
    ar, tier = resolve_video_size(size)
    return ar, tier, ""


def get_seedance_pixel_size(
    resolution: str,
    ratio: str,
    model: str = "",
) -> str:
    """
    根据分辨率档位和宽高比查询 Seedance 实际像素尺寸。

    Args:
        resolution: 分辨率档位，如 "720p"、"1080p"
        ratio:      宽高比，如 "16:9"、"9:16"
        model:      模型名称（用于选择尺寸表）

    Returns:
        像素尺寸字符串，如 "1280x720"；未命中时返回空字符串。
    """
    # 本函数仅对 Seedance 模型调用，直接按版本号区分 V1/V1.5 表
    model_lower = model.lower()
    use_v1 = "1-0" in model_lower or "1.0" in model_lower
    reverse_table = (
        _SEEDANCE_V1_TIER_RATIO_TO_PIXEL
        if use_v1
        else _SEEDANCE_V15_V2_TIER_RATIO_TO_PIXEL
    )
    return reverse_table.get((resolution, ratio), "")
