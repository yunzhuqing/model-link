"""
Credit-consumption billing tests for image / video / audio generation models.

Verifies that output_pricing configs with ``type: "per_credit"`` are resolved
into credits consumed (积分消耗) and persisted on UsageRecord, while the
money-based pricing paths remain unchanged.

Run: cd backend && uv run pytest tests/test_usage_credits.py -q
"""
from __future__ import annotations

import pytest

from app.abstraction.chat import UsageInfo
from app.usagerecord.usage_service import _build_record, _compute_price_details


class _FakeResponse:
    def __init__(self, usage):
        self.usage = usage


def _usage(**extra) -> UsageInfo:
    return UsageInfo(
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        extra=extra,
    )


def _details(output_pricing, extra, **kwargs):
    return _compute_price_details(
        usage=_usage(**extra),
        output_pricing=output_pricing,
        currency='USD',
        discount=1.0,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_image_per_credit_resolution_quality():
    output_pricing = {
        'image': {
            'type': 'per_credit',
            'price': 0.1,  # $ per credit
            'credits': {
                'base': 5,
                'resolution': {'1K': 0, '4K': 15},
                'quality': {'low': 0, 'high': 10},
            },
        },
    }
    d = _details(
        output_pricing,
        {
            'output_image_number': 2,
            'output_image_resolution': '4K',
            'output_image_quality': 'high',
        },
    )
    assert d['credits'] == pytest.approx(2 * (5 + 15 + 10))
    assert d['credit_price_unit'] == pytest.approx(0.1)
    assert d['payable_amount'] == pytest.approx(2 * (5 + 15 + 10) * 0.1)
    # per_credit mode must not set a money price per image
    assert d['output_image_price_unit'] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_image_per_credit_case_insensitive_resolution():
    output_pricing = {
        'image': {
            'type': 'per_credit',
            'credits': {'base': 3, 'resolution': {'4K': 12}},
        },
    }
    d = _details(output_pricing, {'output_image_number': 1, 'output_image_resolution': '4k'})
    assert d['credits'] == pytest.approx(3 + 12)


@pytest.mark.asyncio
async def test_video_per_credit_seconds_and_flags():
    output_pricing = {
        'video': {
            'type': 'per_credit',
            'price': 0.2,
            'credits': {
                'base': 5,
                'per_second': 1,
                'resolution': {'1080p': 10},
                'audio': 3,
                'reference_video': 2,
            },
        },
    }
    d = _details(
        output_pricing,
        {
            'output_video_number': 1,
            'output_video_resolution': '1080p',
            'output_video_seconds': 5,
            'output_video_audio': True,
            'output_video_reference_video': True,
        },
    )
    per_item = 5 + 10 + 3 + 2
    assert d['credits'] == pytest.approx(per_item + 5 * 1)
    assert d['credit_price_unit'] == pytest.approx(0.2)
    assert d['payable_amount'] == pytest.approx((per_item + 5) * 0.2)
    assert d['output_video_price_unit'] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_audio_per_credit_duration():
    output_pricing = {
        'audio': {
            'type': 'per_credit',
            'credits': {'base': 2, 'per_second': 1},
        },
    }
    d = _details(output_pricing, {'output_audio_seconds': 30})
    assert d['credits'] == pytest.approx(2 + 30)
    # No price -> credits only, no money billed
    assert d['credit_price_unit'] == pytest.approx(0.0)
    assert d['payable_amount'] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_money_pricing_unchanged_without_per_credit():
    output_pricing = {
        'image': {'type': 'per_image', 'price': 0.04},
        'video': {'type': 'per_second', 'price': 0.02},
        'audio': {'type': 'per_second', 'price': 0.006},
    }
    d = _details(
        output_pricing,
        {
            'output_image_number': 1,
            'output_video_number': 1,
            'output_video_seconds': 5,
            'output_audio_seconds': 30,
        },
    )
    assert d['credits'] == pytest.approx(0.0)
    assert d['output_image_price_unit'] == pytest.approx(0.04)
    assert d['output_video_price_unit'] == pytest.approx(0.02)
    assert d['output_audio_price_unit'] == pytest.approx(0.006)
    # Existing money behavior: video is billed per generated video, audio per second
    assert d['payable_amount'] == pytest.approx(0.04 + 1 * 0.02 + 30 * 0.006)


@pytest.mark.asyncio
async def test_3d_credits_from_provider_extra_still_works():
    output_pricing = {
        '3d': {'type': 'per_credit', 'price': 0.12, 'credits': {'base': 15}},
    }
    d = _details(output_pricing, {'credits': 25, 'credit_price_unit': 0.12})
    assert d['credits'] == pytest.approx(25)
    assert d['credit_price_unit'] == pytest.approx(0.12)
    assert d['payable_amount'] == pytest.approx(25 * 0.12)


@pytest.mark.asyncio
async def test_record_persists_credits():
    output_pricing = {
        'video': {
            'type': 'per_credit',
            'price': 0.5,
            'credits': {'base': 10},
        },
    }
    record = _build_record(
        response=_FakeResponse(_usage(output_video_number=2)),
        user_name=None,
        api_key_raw=None,
        api_key_name=None,
        api_key_group_id=None,
        api_key_group_name=None,
        model_name='vidu-test',
        provider_id=None,
        provider_name='vidu',
        input_price_unit=0.0,
        output_price_unit=0.0,
        cache_creation_price_unit=0.0,
        cache_5m_creation_price_unit=0.0,
        cache_1h_creation_price_unit=0.0,
        cache_token_price_unit=0.0,
        pricing_tiers=None,
        output_pricing=output_pricing,
        currency='USD',
        discount=1.0,
        duration_ms=1000,
        exchange_rate=1.0,
    )
    assert float(record.credits) == pytest.approx(20)
    assert float(record.credit_price_unit) == pytest.approx(0.5)
    assert float(record.payable_amount) == pytest.approx(10.0)
    assert float(record.actual_amount_usd) == pytest.approx(10.0)
