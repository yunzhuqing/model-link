"""
Tests for service_tier-aware model resolution.

Covers:
- Routing: requests carrying a service_tier only match model instances that
  declare that tier, so the same model name can be served by different
  providers per tier.
- Pricing: per-tier prices override flat model prices; keys missing from the
  tier entry fall back to the flat prices.
- "auto"/"default" never constrain routing (OpenAI semantics).
- Admin payload validation (_validate_service_tiers).

Run: cd backend && uv run pytest tests/test_service_tier_routing.py -q
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import db
from app.middleware.gateway_service import (
    GatewayService,
    GatewayServiceError,
    _normalize_service_tier,
)
from app.models import Group, Model, Provider
from app.routes.providers import _validate_service_tiers


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(db.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def _seed_two_tiered_models(session: AsyncSession):
    """Seed one model alias served by two providers, one per tier."""
    group = Group(name="tier-test-group")
    session.add(group)
    await session.flush()

    flex_provider = Provider(
        name="flex-provider", type="openai", group_id=group.id,
        api_key="sk-test", base_url="https://api.openai.com/v1",
    )
    priority_provider = Provider(
        name="priority-provider", type="openai", group_id=group.id,
        api_key="sk-test", base_url="https://api.openai.com/v1",
    )
    session.add_all([flex_provider, priority_provider])
    await session.flush()

    flex_model = Model(
        provider_id=flex_provider.id, name="gpt-5", alias="gpt5",
        input_price=2.0, output_price=10.0,
        cache_hit_price=0.5,
        service_tiers=[{"tier": "flex", "input_price": 1.25}],
        priority=10,
    )
    priority_model = Model(
        provider_id=priority_provider.id, name="gpt-5", alias="gpt5",
        input_price=5.0, output_price=20.0,
        service_tiers=[{"tier": "priority"}],
        priority=10,
    )
    session.add_all([flex_model, priority_model])
    await session.commit()
    return group, flex_provider, priority_provider


@pytest.mark.asyncio
async def test_tier_routes_to_declaring_provider(db_session):
    await _seed_two_tiered_models(db_session)
    service = GatewayService()

    resolved = await service.resolve_model(db_session, "gpt5", service_tier="flex")
    assert resolved.provider_name == "flex-provider"
    assert resolved.service_tier == "flex"

    resolved = await service.resolve_model(db_session, "gpt5", service_tier="priority")
    assert resolved.provider_name == "priority-provider"
    assert resolved.service_tier == "priority"


@pytest.mark.asyncio
async def test_tier_price_override_and_fallback(db_session):
    await _seed_two_tiered_models(db_session)
    service = GatewayService()

    # flex entry overrides input_price; output_price/cache_hit_price fall
    # back to the flat model prices because the entry omits them.
    resolved = await service.resolve_model(db_session, "gpt5", service_tier="flex")
    assert resolved.input_price == pytest.approx(1.25)
    assert resolved.output_price == pytest.approx(10.0)
    assert resolved.cache_hit_price == pytest.approx(0.5)

    # priority entry declares no prices at all → flat prices apply.
    resolved = await service.resolve_model(db_session, "gpt5", service_tier="priority")
    assert resolved.input_price == pytest.approx(5.0)
    assert resolved.output_price == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_unsupported_tier_raises_400(db_session):
    await _seed_two_tiered_models(db_session)
    service = GatewayService()

    with pytest.raises(GatewayServiceError) as exc_info:
        await service.resolve_model(db_session, "gpt5", service_tier="scale")
    assert exc_info.value.status_code == 400
    assert "service_tier" in str(exc_info.value)


@pytest.mark.asyncio
async def test_auto_and_default_do_not_constrain_routing(db_session):
    await _seed_two_tiered_models(db_session)
    service = GatewayService()

    for tier in ("auto", "default", None, "  "):
        resolved = await service.resolve_model(db_session, "gpt5", service_tier=tier)
        # Both instances are eligible; prices stay flat either way.
        assert resolved.input_price in (pytest.approx(2.0), pytest.approx(5.0))
        assert resolved.output_price in (pytest.approx(10.0), pytest.approx(20.0))


@pytest.mark.asyncio
async def test_tier_matching_is_case_insensitive(db_session):
    await _seed_two_tiered_models(db_session)
    service = GatewayService()

    resolved = await service.resolve_model(db_session, "gpt5", service_tier="FLEX")
    assert resolved.provider_name == "flex-provider"
    assert resolved.service_tier == "flex"


def test_normalize_service_tier():
    assert _normalize_service_tier(None) is None
    assert _normalize_service_tier("") is None
    assert _normalize_service_tier("  ") is None
    assert _normalize_service_tier("Flex") == "flex"
    assert _normalize_service_tier(" PRIORITY ") == "priority"


def test_model_service_tier_helpers():
    model = Model(
        name="m",
        service_tiers=[
            {"tier": "Flex", "input_price": 1.0},
            {"tier": "priority"},
        ],
    )
    assert model.service_tier_names == ["flex", "priority"]
    assert model.get_service_tier_config("FLEX")["input_price"] == 1.0
    assert model.get_service_tier_config("priority") == {"tier": "priority"}
    assert model.get_service_tier_config("scale") is None

    empty = Model(name="m")
    assert empty.service_tier_names == []
    assert empty.get_service_tier_config("flex") is None


def test_validate_service_tiers_accepts_valid_payload():
    normalized, error = _validate_service_tiers([
        {"tier": " Flex ", "input_price": "1.25", "output_price": 10},
        {"tier": "priority"},
    ])
    assert error is None
    assert normalized == [
        {"tier": "flex", "input_price": 1.25, "output_price": 10.0},
        {"tier": "priority"},
    ]


def test_validate_service_tiers_rejects_bad_payloads():
    cases = [
        {"service_tiers": "flex"},                                   # not a list
        {"service_tiers": ["flex"]},                                 # not an object
        {"service_tiers": [{"input_price": 1}]},                     # missing tier name
        {"service_tiers": [{"tier": "auto"}]},                       # reserved name
        {"service_tiers": [{"tier": "flex"}, {"tier": "FLEX"}]},     # duplicate
        {"service_tiers": [{"tier": "flex", "input_price": -1}]},    # negative price
        {"service_tiers": [{"tier": "flex", "input_price": "abc"}]}, # non-numeric price
    ]
    for data in cases:
        normalized, error = _validate_service_tiers(data["service_tiers"])
        assert error is not None, f"expected rejection for {data}"
        assert normalized is None


def test_validate_service_tiers_empty_values():
    for value in (None, "", []):
        normalized, error = _validate_service_tiers(value)
        assert normalized is None
        assert error is None


@pytest.mark.asyncio
async def test_tier_pricing_tiers_override_model_tiers(db_session):
    """A service tier may carry its own context-size pricing_tiers which
    fully replace the model-level pricing_tiers when that tier is used."""
    group = Group(name="nested-tier-group")
    db_session.add(group)
    await db_session.flush()

    provider = Provider(
        name="nested-provider", type="openai", group_id=group.id,
        api_key="sk-test", base_url="https://api.openai.com/v1",
    )
    db_session.add(provider)
    await db_session.flush()

    model_tiers = [
        {"label": "<=272k", "context_size": 272000, "input_price": 1.25, "output_price": 10.0},
        {"label": ">272k", "context_size": 1000000, "input_price": 2.5, "output_price": 20.0},
    ]
    priority_tiers = [
        {"label": "<=272k", "context_size": 272000, "input_price": 5.0, "output_price": 40.0},
    ]
    model = Model(
        provider_id=provider.id, name="gpt-5", alias="gpt5n",
        input_price=1.25, output_price=10.0,
        pricing_tiers=model_tiers,
        service_tiers=[
            {"tier": "flex"},  # no pricing_tiers → inherits model-level tiers
            {"tier": "priority", "input_price": 5.0, "pricing_tiers": priority_tiers},
        ],
    )
    db_session.add(model)
    await db_session.commit()

    service = GatewayService()

    # flex: model-level pricing_tiers are kept; flat prices fall back too.
    resolved = await service.resolve_model(db_session, "gpt5n", service_tier="flex")
    assert resolved.pricing_tiers == model_tiers
    assert resolved.input_price == pytest.approx(1.25)

    # priority: the tier's own pricing_tiers replace the model-level ones.
    resolved = await service.resolve_model(db_session, "gpt5n", service_tier="priority")
    assert resolved.pricing_tiers == priority_tiers
    assert resolved.input_price == pytest.approx(5.0)

    # No service_tier: model-level pricing_tiers apply.
    resolved = await service.resolve_model(db_session, "gpt5n")
    assert resolved.pricing_tiers == model_tiers


def test_validate_service_tiers_with_nested_pricing_tiers():
    normalized, error = _validate_service_tiers([
        {
            "tier": "priority",
            "input_price": 5,
            "pricing_tiers": [
                {"label": "<=272k", "context_size": "272000", "input_price": 5, "output_price": 40.0},
                {"context_size": 1000000},
            ],
        },
    ])
    assert error is None
    assert normalized[0]["pricing_tiers"] == [
        {"label": "<=272k", "context_size": 272000.0, "input_price": 5.0, "output_price": 40.0},
        {"context_size": 1000000.0},
    ]


def test_validate_service_tiers_rejects_bad_nested_pricing_tiers():
    cases = [
        {"tier": "flex", "pricing_tiers": "nope"},                     # not a list
        {"tier": "flex", "pricing_tiers": ["<=272k"]},                 # not an object
        {"tier": "flex", "pricing_tiers": [{"input_price": -5}]},      # negative
        {"tier": "flex", "pricing_tiers": [{"context_size": "big"}]},  # non-numeric
    ]
    for entry in cases:
        normalized, error = _validate_service_tiers([entry])
        assert error is not None, f"expected rejection for {entry}"
        assert normalized is None



def test_output_pricing_service_tier_prices():
    """output_pricing categories carry per-service_tier unit prices which
    billing applies when the request was resolved with that tier."""
    from app.abstraction.chat import UsageInfo
    from app.usagerecord.usage_service import _compute_price_details

    output_pricing = {
        "image": {
            "type": "per_image",
            "price": 0.04,
            "service_tiers": {"flex": 0.02, "priority": 0.06},
        }
    }

    def usage():
        return UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0,
                         extra={'output_image_number': 1})

    base = _compute_price_details(usage=usage(), output_pricing=output_pricing)
    assert base['output_image_price_unit'] == pytest.approx(0.04)

    flex = _compute_price_details(usage=usage(), output_pricing=output_pricing, service_tier='flex')
    assert flex['output_image_price_unit'] == pytest.approx(0.02)
    assert flex['payable_amount'] == pytest.approx(0.02)

    prio = _compute_price_details(usage=usage(), output_pricing=output_pricing, service_tier='PRIORITY')
    assert prio['output_image_price_unit'] == pytest.approx(0.06)

    # Tier not configured in output_pricing → base price.
    unknown = _compute_price_details(usage=usage(), output_pricing=output_pricing, service_tier='scale')
    assert unknown['output_image_price_unit'] == pytest.approx(0.04)


def test_apply_output_pricing_service_tier_forms():
    from app.usagerecord.usage_service import _apply_output_pricing_service_tier

    cfg = {"type": "per_image", "price": 0.04, "service_tiers": {"flex": 0.02}}
    assert _apply_output_pricing_service_tier(cfg, 'flex') == {"type": "per_image", "price": 0.02}
    assert _apply_output_pricing_service_tier(cfg, None) is cfg
    assert _apply_output_pricing_service_tier(cfg, 'scale') is cfg

    # Object-form overrides merge into the category config.
    cfg2 = {"type": "per_second", "price": 1.0,
            "service_tiers": {"flex": {"price": 0.5, "tiers": [{"resolution": "720p", "price": 0.4}]}}}
    merged = _apply_output_pricing_service_tier(cfg2, 'flex')
    assert merged['price'] == 0.5
    assert merged['tiers'] == [{"resolution": "720p", "price": 0.4}]
    assert 'service_tiers' not in merged

    # Non-numeric override keeps the base config.
    cfg3 = {"type": "per_image", "price": 0.04, "service_tiers": {"flex": "oops"}}
    assert _apply_output_pricing_service_tier(cfg3, 'flex') is cfg3


def test_output_pricing_service_tier_resolution_tiers():
    """A service tier override may define its own resolution tiers; within
    the tier, unmatched resolutions fall back to the tier's base price."""
    from app.abstraction.chat import UsageInfo
    from app.usagerecord.usage_service import _compute_price_details

    output_pricing = {
        "video": {
            "type": "per_second",
            "price": 1.0,
            "tiers": [
                {"resolution": "720p", "price": 0.8},
                {"resolution": "1080p", "price": 1.2},
            ],
            "service_tiers": {
                "flex": {
                    "price": 0.5,
                    "tiers": [{"resolution": "720p", "price": 0.4}],
                },
            },
        }
    }

    def usage(resolution):
        return UsageInfo(
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            extra={'output_video_number': 1, 'output_video_seconds': 2,
                   'output_video_resolution': resolution},
        )

    # No tier: model-level resolution schedule applies.
    base = _compute_price_details(usage=usage('720p'), output_pricing=output_pricing)
    assert base['output_video_price_unit'] == pytest.approx(0.8)
    base_1080 = _compute_price_details(usage=usage('1080p'), output_pricing=output_pricing)
    assert base_1080['output_video_price_unit'] == pytest.approx(1.2)

    # flex tier: its own resolution tiers replace the model-level ones.
    flex_720 = _compute_price_details(usage=usage('720p'), output_pricing=output_pricing, service_tier='flex')
    assert flex_720['output_video_price_unit'] == pytest.approx(0.4)

    # flex tier, resolution not in the tier's list → tier base price.
    flex_1080 = _compute_price_details(usage=usage('1080p'), output_pricing=output_pricing, service_tier='flex')
    assert flex_1080['output_video_price_unit'] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_tier_declared_only_in_output_pricing_routes(db_session):
    """Regression: a tier declared only inside output_pricing (the place
    where generation pricing is configured) must still make the model
    eligible for routing — no duplicate top-level service_tiers entry
    should be required."""
    group = Group(name="gen-only-tier-group")
    db_session.add(group)
    await db_session.flush()

    provider = Provider(
        name="gen-only-provider", type="openai", group_id=group.id,
        api_key="sk-test", base_url="https://api.openai.com/v1",
    )
    db_session.add(provider)
    await db_session.flush()

    output_pricing = {
        "image": {
            "type": "per_image",
            "price": 0.04,
            "service_tiers": {"flex": 0.02},
        }
    }
    model = Model(
        provider_id=provider.id, name="gemini-3.1-flash-image-preview",
        input_price=0, output_price=0,
        output_pricing=output_pricing,
    )
    db_session.add(model)
    await db_session.commit()

    assert model.service_tier_names == ["flex"]

    service = GatewayService()
    resolved = await service.resolve_model(
        db_session, "gemini-3.1-flash-image-preview", service_tier="flex")
    assert resolved.service_tier == "flex"
    assert resolved.output_pricing == output_pricing
