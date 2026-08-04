"""
Image size utility tests — shared table vs Z-Image Turbo dedicated table.

Verifies that GPT Image 2 (Vidu) 1K sizes (``1024x1536`` / ``1536x1024``)
resolve to the 1K tier in the shared table, while Z-Image Turbo resolves
through its own dedicated table (``Z_IMAGE_SIZE_MAP``) where both 1K size
groups (1024…1344 and 1280…1680) belong to the 1K tier.
"""
from __future__ import annotations

import pytest

from app.providers.image_size_utils import (
    IMAGE_SIZE_MAP,
    Z_IMAGE_SIZE_MAP,
    get_pixel_size,
    resolve_image_size,
    resolve_pixel_size,
)
from app.providers.bailian.image_generation import _resolve_z_image_size


# ── Shared table: GPT Image 2 (Vidu) mapping ────────────────────────────────

@pytest.mark.parametrize("size,expected", [
    # 1K tier (Vidu native sizes)
    ("1024x1024", ("1:1", "1K")),
    ("1024x1536", ("2:3", "1K")),   # must NOT resolve to Z-Image 1.5K
    ("1536x1024", ("3:2", "1K")),   # must NOT resolve to Z-Image 1.5K
    ("768x1024",  ("3:4", "1K")),
    ("1024x768",  ("4:3", "1K")),
    ("1024x576",  ("16:9", "1K")),
    ("576x1024",  ("9:16", "1K")),
    ("1024x439",  ("21:9", "1K")),
    ("439x1024",  ("9:21", "1K")),
    # 2K tier
    ("2048x2048", ("1:1", "2K")),
    ("2048x3072", ("2:3", "2K")),
    ("3072x2048", ("3:2", "2K")),
    ("1536x2048", ("3:4", "2K")),
    ("2048x1536", ("4:3", "2K")),
    ("2048x1152", ("16:9", "2K")),
    ("1152x2048", ("9:16", "2K")),
    ("2048x878",  ("21:9", "2K")),
    ("878x2048",  ("9:21", "2K")),
    # 4K tier
    ("3840x3840", ("1:1", "4K")),
    ("3840x2560", ("3:2", "4K")),
    ("2560x3840", ("2:3", "4K")),
    ("2880x3840", ("3:4", "4K")),
    ("3840x2880", ("4:3", "4K")),
    ("3840x2160", ("16:9", "4K")),
    ("2160x3840", ("9:16", "4K")),
    ("3840x1646", ("21:9", "4K")),
    ("1646x3840", ("9:21", "4K")),
])
def test_shared_table_gpt_image_2_sizes(size, expected):
    assert resolve_image_size(size=size) == expected


def test_shared_table_defaults():
    # aspect_ratio alone picks the lowest tier for that ratio
    assert resolve_image_size(aspect_ratio="2:3") == ("2:3", "512")
    assert resolve_image_size(aspect_ratio="16:9") == ("16:9", "512")
    # ratios absent from the 512 tier fall back to 1K
    assert resolve_image_size(aspect_ratio="9:21") == ("9:21", "1K")
    # tier label alone picks 1:1 at that tier
    assert resolve_image_size(size="1K") == ("1:1", "1K")
    assert resolve_image_size(size="4K") == ("1:1", "4K")


def test_shared_table_has_no_z_image_1_5k_tier():
    assert all(tier != "1.5K" for _, tier in IMAGE_SIZE_MAP.values())


# ── Z-Image Turbo dedicated table ───────────────────────────────────────────

@pytest.mark.parametrize("size,expected", [
    # 1K tier
    ("1024x1024", ("1:1", "1K")),
    # 1280…1680 group — merged into the 1K tier (was "1.5K")
    ("1280x1280", ("1:1", "1K")),
    ("832x1248",  ("2:3", "1K")),
    ("1024x1536", ("2:3", "1K")),
    ("1248x832",  ("3:2", "1K")),
    ("1536x1024", ("3:2", "1K")),
    ("864x1152",  ("3:4", "1K")),
    ("1104x1472", ("3:4", "1K")),
    ("1152x864",  ("4:3", "1K")),
    ("1472x1104", ("4:3", "1K")),
    ("896x1152",  ("7:9", "1K")),
    ("1120x1440", ("7:9", "1K")),
    ("1152x896",  ("9:7", "1K")),
    ("1440x1120", ("9:7", "1K")),
    ("720x1280",  ("9:16", "1K")),
    ("864x1536",  ("9:16", "1K")),
    ("576x1344",  ("9:21", "1K")),
    ("720x1680",  ("9:21", "1K")),
    ("1280x720",  ("16:9", "1K")),
    ("1536x864",  ("16:9", "1K")),
    ("1344x576",  ("21:9", "1K")),
    ("1680x720",  ("21:9", "1K")),
    # 2K tier
    ("1536x1536", ("1:1", "2K")),
    ("1248x1872", ("2:3", "2K")),
    ("1872x1248", ("3:2", "2K")),
    ("1296x1728", ("3:4", "2K")),
    ("1728x1296", ("4:3", "2K")),
    ("1344x1728", ("7:9", "2K")),
    ("1728x1344", ("9:7", "2K")),
    ("1152x2048", ("9:16", "2K")),
    ("864x2016",  ("9:21", "2K")),
    ("2048x1152", ("16:9", "2K")),
    ("2016x864",  ("21:9", "2K")),
])
def test_z_image_table_sizes(size, expected):
    assert resolve_image_size(size=size, table=Z_IMAGE_SIZE_MAP) == expected


def test_z_image_table_integrity():
    # 22 1K entries + 11 2K entries = 33, including the previously dropped 1536x1536
    assert len(Z_IMAGE_SIZE_MAP) == 33
    assert Z_IMAGE_SIZE_MAP["1536x1536"] == ("1:1", "2K")
    assert all(tier != "1.5K" for _, tier in Z_IMAGE_SIZE_MAP.values())


def test_z_image_pixel_resolution():
    assert resolve_pixel_size(size="1536x1536", sep="*", table=Z_IMAGE_SIZE_MAP) == "1536*1536"
    assert resolve_pixel_size(size="1024*1536", sep="*", table=Z_IMAGE_SIZE_MAP) == "1024*1536"
    # tier-based lookups resolve to the canonical 1K / 2K sizes
    assert (
        resolve_pixel_size(aspect_ratio="1:1", resolution="1K", sep="*", table=Z_IMAGE_SIZE_MAP)
        == "1024*1024"
    )
    assert resolve_pixel_size(size="1K", sep="*", table=Z_IMAGE_SIZE_MAP) == "1024*1024"
    assert resolve_pixel_size(size="2K", sep="*", table=Z_IMAGE_SIZE_MAP) == "1536*1536"
    assert (
        resolve_pixel_size(aspect_ratio="2:3", resolution="2K", sep="*", table=Z_IMAGE_SIZE_MAP)
        == "1248*1872"
    )
    assert get_pixel_size("2:3", "1K", table=Z_IMAGE_SIZE_MAP) == "832x1248"
    assert get_pixel_size("1:1", "2K", table=Z_IMAGE_SIZE_MAP) == "1536x1536"


def test_z_image_default():
    assert resolve_image_size(aspect_ratio="7:9", table=Z_IMAGE_SIZE_MAP) == ("7:9", "1K")
    assert resolve_image_size(size="2K", table=Z_IMAGE_SIZE_MAP) == ("1:1", "2K")


# ── Bailian _resolve_z_image_size integration ───────────────────────────────

def test_resolve_z_image_size_uses_dedicated_table():
    assert _resolve_z_image_size({"size": "1536x1536"}) == "1536*1536"
    assert _resolve_z_image_size({"size": "1024x1536"}) == "1024*1536"
    assert _resolve_z_image_size({"size": "1536x1024"}) == "1536*1024"
    assert _resolve_z_image_size({"size": "1280x1280"}) == "1280*1280"
    assert _resolve_z_image_size({"size": "1K"}) == "1024*1024"
    assert _resolve_z_image_size({"size": "2K"}) == "1536*1536"
    assert _resolve_z_image_size({"aspect_ratio": "1:1", "resolution": "1K"}) == "1024*1024"
    assert (
        _resolve_z_image_size({"aspect_ratio": "2:3", "resolution": "2K"})
        == "1248*1872"
    )
    assert _resolve_z_image_size({}) == "1024*1024"
