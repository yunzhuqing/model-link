"""
Tier-matching regression tests for ``_resolve_output_price``.

Covers the Seedance 2.5 pricing bug: a text-only request (no reference video)
at 720p must resolve to the non-ref-video price even though the model generates
audio by default while every configured tier carries ``audio: false``.

Before the fix, strict flag matching excluded every tier (audio mismatch), so
the price collapsed to the base price (¥42, the "+ref_video" price) instead of
the correct ¥70 non-ref tier.

Run: cd backend && uv run pytest tests/test_output_price_tier_matching.py -q
"""
from __future__ import annotations

import pytest

from app.usagerecord.usage_service import _resolve_output_price


# Model doubao-seedance-2-5-260628 output_pricing (from DB):
#   base ¥42/M tokens; 480p/720p split by reference_video;
#   every tier carries ``audio: false`` (UI default), but the model
#   generates audio by default (audio=True in the request).
SEEDANCE_25 = {
    'type': 'per_token',
    'price': 42,
    'tiers': [
        {'audio': False, 'price': 42, 'resolution': '480p', 'reference_video': True},
        {'audio': False, 'price': 70, 'resolution': '480p'},
        {'audio': False, 'price': 42, 'resolution': '720p', 'reference_video': True},
        {'audio': False, 'price': 70, 'resolution': '720p'},
    ],
}


@pytest.mark.parametrize('audio', [True, False, None])
def test_seedance_25_text_only_720p_uses_non_ref_price(audio):
    """Text-only input (reference_video=False) at 720p must cost ¥70, never ¥42."""
    assert _resolve_output_price(
        SEEDANCE_25, '720p', audio=audio, reference_video=False,
    ) == pytest.approx(70.0)


def test_seedance_25_with_ref_video_720p_uses_ref_price():
    assert _resolve_output_price(
        SEEDANCE_25, '720p', audio=True, reference_video=True,
    ) == pytest.approx(42.0)


def test_seedance_25_480p_split_respected():
    assert _resolve_output_price(
        SEEDANCE_25, '480p', audio=True, reference_video=False,
    ) == pytest.approx(70.0)
    assert _resolve_output_price(
        SEEDANCE_25, '480p', audio=True, reference_video=True,
    ) == pytest.approx(42.0)


# Model doubao-seedance-1-5-pro-251215: audio differentiates price.
SEEDANCE_15 = {
    'type': 'per_token',
    'price': 8,
    'tiers': [
        {'audio': False, 'price': 8, 'resolution': '480p'},
        {'audio': False, 'price': 8, 'resolution': '720p'},
        {'audio': False, 'price': 8, 'resolution': '1080p'},
        {'audio': True, 'price': 16, 'resolution': '480p'},
        {'audio': True, 'price': 16, 'resolution': '720p'},
        {'audio': True, 'price': 16, 'resolution': '1080p'},
    ],
}


def test_seedance_15_audio_tiering_preserved():
    """Models that genuinely differentiate on audio must keep strict matching."""
    assert _resolve_output_price(
        SEEDANCE_15, '720p', audio=True,
    ) == pytest.approx(16.0)
    assert _resolve_output_price(
        SEEDANCE_15, '720p', audio=False,
    ) == pytest.approx(8.0)


# Model doubao-seedance-2-0-260128: reference_video differentiates price, no audio.
SEEDANCE_20 = {
    'type': 'per_token',
    'price': 28,
    'tiers': [
        {'price': 46, 'resolution': '480p', 'reference_video': False},
        {'price': 46, 'resolution': '720p', 'reference_video': False},
        {'price': 51, 'resolution': '1080p', 'reference_video': False},
        {'price': 28, 'resolution': '480p', 'reference_video': True},
        {'price': 28, 'resolution': '720p', 'reference_video': True},
        {'price': 31, 'resolution': '1080p', 'reference_video': True},
    ],
}


def test_seedance_20_ref_split_preserved():
    assert _resolve_output_price(
        SEEDANCE_20, '720p', reference_video=False,
    ) == pytest.approx(46.0)
    assert _resolve_output_price(
        SEEDANCE_20, '720p', reference_video=True,
    ) == pytest.approx(28.0)


def test_resolution_mismatch_falls_back_to_base_price():
    """Relaxed flag matching must never bypass resolution matching."""
    assert _resolve_output_price(
        SEEDANCE_25, '4k', audio=True, reference_video=False,
    ) == pytest.approx(42.0)  # base price


def test_tier_price_override_and_wildcard_flags():
    """Tiers without a flag field are wildcards and still match under relaxation."""
    cfg = {
        'type': 'per_token',
        'price': 50,
        'tiers': [
            {'resolution': '720p', 'reference_video': True, 'price': 30},
            {'resolution': '720p', 'price': 90},
        ],
    }
    assert _resolve_output_price(
        cfg, '720p', audio=True, reference_video=False,
    ) == pytest.approx(90.0)
    assert _resolve_output_price(
        cfg, '720p', audio=True, reference_video=True,
    ) == pytest.approx(30.0)
