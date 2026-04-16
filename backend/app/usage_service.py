"""
Usage Service - Records request consumption details to ml_usage_records.

This module provides two public functions:
  - record_usage()        – for completed non-streaming requests
  - record_stream_usage() – for completed streaming requests

Both are fire-and-forget: they spawn a daemon thread so the gateway response
is never delayed by the DB write.

Tiered pricing
--------------
Models may define a ``pricing_tiers`` JSON list (same schema as
``Model.pricing_tiers``).  Each tier has a ``context_size`` (token threshold)
and per-tier price overrides.  When recording usage we pick the first tier
whose ``context_size >= input_tokens``; if none qualifies we fall back to the
flat model prices.

Example tiers ($ per 1M tokens):
  [
    {"label": "<=128k", "context_size": 128000, "input_price": 2.5,  "output_price": 10},
    {"label": ">128k",  "context_size": 1000000,"input_price": 5.0,  "output_price": 20}
  ]

Currency / exchange-rate handling
----------------------------------
Each usage record stores:
  - currency            – pricing currency of the model ("USD", "CNY", …)
  - exchange_rate_to_cny – USD→CNY rate at the time of the request
                           (1.0 when currency is already CNY, so callers can
                           always compute cost_cny = native_cost * exchange_rate)

The exchange rate is read from the in-memory cache maintained by
exchange_rate_service (refreshed daily from frankfurter.app).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.abstraction.chat import ChatResponse, UsageInfo
    from app.models import ApiKey, User, Provider, Model as DbModel

logger = logging.getLogger("usage")


# ── Public API ────────────────────────────────────────────────────────────────

def record_usage(
    *,
    app,
    response: "ChatResponse",
    db_model: "DbModel",
    db_provider: "Provider",
    api_key: Optional["ApiKey"] = None,
    user: Optional["User"] = None,
    request_model_name: str = "",
    duration_ms: Optional[int] = None,
) -> None:
    """
    Persist one UsageRecord row for a completed (non-streaming) request.

    All data needed from SQLAlchemy ORM objects is extracted eagerly here
    (in the request thread, while the session is still alive) and passed as
    plain Python values to the background thread.  This avoids cross-thread
    lazy-loading on a closed/detached session.
    """
    # ── Eagerly extract all primitive values from ORM objects ─────────────────
    user_name: Optional[str] = user.username if user else None

    api_key_raw: Optional[str] = None
    api_key_name: Optional[str] = None
    api_key_group_id: Optional[int] = None
    api_key_group_name: Optional[str] = None

    if api_key:
        api_key_raw = api_key.key
        api_key_name = api_key.name
        api_key_group_id = api_key.group_id
        try:
            if api_key.group:
                api_key_group_name = api_key.group.name
        except Exception:
            pass

    provider_id: Optional[int] = db_provider.id if db_provider else None
    provider_name: Optional[str] = db_provider.name if db_provider else None

    model_name: Optional[str] = (
        request_model_name
        or (db_model.alias or db_model.name if db_model else None)
    )

    # Flat (base) prices — used when no tier matches
    input_price_unit: float = getattr(db_model, 'input_price', 0.0) or 0.0
    output_price_unit: float = getattr(db_model, 'output_price', 0.0) or 0.0
    cache_creation_price_unit: float = getattr(db_model, 'cache_creation_price', 0.0) or 0.0
    cache_token_price_unit: float = getattr(db_model, 'cache_hit_price', 0.0) or 0.0
    currency: str = getattr(db_model, 'currency', 'USD') or 'USD'
    # Tiered pricing — serialised as a plain list so it's safe to pass to a thread
    pricing_tiers: Optional[list] = getattr(db_model, 'pricing_tiers', None)
    # Output pricing strategies for image/video/audio — plain dict
    output_pricing: Optional[dict] = getattr(db_model, 'output_pricing', None)

    exchange_rate_to_cny = _get_exchange_rate_for_currency(currency)

    thread = threading.Thread(
        target=_persist_usage,
        kwargs=dict(
            app=app,
            response=response,
            user_name=user_name,
            api_key_raw=api_key_raw,
            api_key_name=api_key_name,
            api_key_group_id=api_key_group_id,
            api_key_group_name=api_key_group_name,
            model_name=model_name,
            provider_id=provider_id,
            provider_name=provider_name,
            input_price_unit=input_price_unit,
            output_price_unit=output_price_unit,
            cache_creation_price_unit=cache_creation_price_unit,
            cache_token_price_unit=cache_token_price_unit,
            pricing_tiers=pricing_tiers,
            output_pricing=output_pricing,
            currency=currency,
            duration_ms=duration_ms,
            exchange_rate_to_cny=exchange_rate_to_cny,
        ),
        daemon=True,
    )
    thread.start()


def record_stream_usage(
    *,
    app,
    usage_info,
    # Identity (plain Python primitives — no ORM objects)
    user_name: Optional[str] = None,
    api_key_raw: Optional[str] = None,
    api_key_name: Optional[str] = None,
    api_key_group_id: Optional[int] = None,
    api_key_group_name: Optional[str] = None,
    # Model / provider (from model_meta dict)
    model_name: Optional[str] = None,
    provider_id: Optional[int] = None,
    provider_name: Optional[str] = None,
    input_price_unit: float = 0.0,
    output_price_unit: float = 0.0,
    cache_creation_price_unit: float = 0.0,
    cache_token_price_unit: float = 0.0,
    pricing_tiers: Optional[list] = None,
    output_pricing: Optional[dict] = None,
    # Currency (from model_meta dict)
    currency: str = 'USD',
    # Duration
    duration_ms: Optional[int] = None,
) -> None:
    """
    Persist one UsageRecord row for a completed streaming request.

    Called after the stream finishes with the accumulated UsageInfo from
    the final usage chunk.  Runs in a daemon background thread.

    All arguments must be plain Python primitives (no ORM objects), since
    the SQLAlchemy session is already closed by the time the stream ends.
    """
    exchange_rate_to_cny = _get_exchange_rate_for_currency(currency)

    thread = threading.Thread(
        target=_persist_usage,
        kwargs=dict(
            app=app,
            response=_UsageOnlyResponse(usage_info),
            user_name=user_name,
            api_key_raw=api_key_raw,
            api_key_name=api_key_name,
            api_key_group_id=api_key_group_id,
            api_key_group_name=api_key_group_name,
            model_name=model_name,
            provider_id=provider_id,
            provider_name=provider_name,
            input_price_unit=input_price_unit,
            output_price_unit=output_price_unit,
            cache_creation_price_unit=cache_creation_price_unit,
            cache_token_price_unit=cache_token_price_unit,
            pricing_tiers=pricing_tiers,
            output_pricing=output_pricing,
            currency=currency,
            duration_ms=duration_ms,
            exchange_rate_to_cny=exchange_rate_to_cny,
        ),
        daemon=True,
    )
    thread.start()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_exchange_rate_for_currency(currency: str) -> float:
    """
    Return the effective USD→CNY exchange rate for the given pricing currency.

    - If currency is 'CNY', cost is already in CNY → rate = 1.0
    - If currency is 'USD' (or anything else), return the live USD→CNY rate
      from the in-memory cache maintained by exchange_rate_service.
    """
    if (currency or 'USD').upper() == 'CNY':
        return 1.0
    try:
        from app.exchange_rate_service import get_exchange_rate
        return get_exchange_rate()
    except Exception:
        return 7.0  # safe fallback


def _resolve_price_tier(
    pricing_tiers: Optional[list],
    input_tokens: int,
    default_input_price: float,
    default_output_price: float,
    default_cache_creation_price: float,
    default_cache_hit_price: float,
) -> tuple:
    """
    Return ``(input_price, output_price, cache_creation_price, cache_hit_price)``
    for the tier that matches ``input_tokens``.

    Tier selection rule:
      - Sort tiers ascending by ``context_size``.
      - Pick the **first** tier whose ``context_size >= input_tokens`` (i.e., the
        smallest tier that can accommodate the request).
      - If no tier's ``context_size`` is large enough, fall back to the last
        (largest) tier.
      - If ``pricing_tiers`` is empty or None, use the flat default prices.

    Each tier dict may contain any subset of the price keys; missing keys fall
    back to the corresponding flat model price.
    """
    if not pricing_tiers:
        return (
            default_input_price,
            default_output_price,
            default_cache_creation_price,
            default_cache_hit_price,
        )

    # Sort ascending by context_size
    try:
        sorted_tiers = sorted(pricing_tiers, key=lambda t: t.get('context_size', 0))
    except Exception:
        return (
            default_input_price,
            default_output_price,
            default_cache_creation_price,
            default_cache_hit_price,
        )

    # Default to the last (largest) tier
    selected = sorted_tiers[-1]
    for tier in sorted_tiers:
        if input_tokens <= tier.get('context_size', 0):
            selected = tier
            break

    return (
        float(selected.get('input_price', default_input_price) or default_input_price),
        float(selected.get('output_price', default_output_price) or default_output_price),
        float(selected.get('cache_creation_price', default_cache_creation_price) or default_cache_creation_price),
        float(selected.get('cache_hit_price', default_cache_hit_price) or default_cache_hit_price),
    )


def _resolve_output_price(
    pricing_config: Optional[dict],
    resolution: Optional[str],
) -> float:
    """
    Resolve the per-unit price from an output_pricing sub-config.

    Args:
        pricing_config: One of output_pricing["image"], output_pricing["video"],
                        or output_pricing["audio"].  Structure:
                        {"type": "per_image"|"per_second"|"per_token",
                         "price": <float>,
                         "tiers": [{"resolution": "1K", "price": <float>}, ...]}
        resolution:     The actual resolution string from the request (e.g. "1K", "720p").
                        Used for tier matching when tiers are present.

    Returns:
        The resolved price (float). Returns 0.0 if pricing_config is None.
    """
    if not pricing_config or not isinstance(pricing_config, dict):
        return 0.0

    base_price: float = float(pricing_config.get('price', 0.0) or 0.0)

    # If tiers exist and we have a resolution, try to match
    tiers = pricing_config.get('tiers')
    if tiers and isinstance(tiers, list) and resolution:
        norm_res = resolution.strip().lower()
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            tier_res = (tier.get('resolution') or '').strip().lower()
            if tier_res and tier_res == norm_res:
                return float(tier.get('price', base_price) or base_price)

    return base_price


class _UsageOnlyResponse:
    """Minimal response-like object wrapping a UsageInfo for _persist_usage compatibility."""
    def __init__(self, usage_info):
        self.usage = usage_info


def _persist_usage(
    *,
    app,
    response,
    user_name,
    api_key_raw,
    api_key_name,
    api_key_group_id,
    api_key_group_name,
    model_name,
    provider_id,
    provider_name,
    input_price_unit,
    output_price_unit,
    cache_creation_price_unit,
    cache_token_price_unit,
    pricing_tiers=None,
    output_pricing=None,
    currency='USD',
    duration_ms=None,
    exchange_rate_to_cny=None,
) -> None:
    """Worker that actually writes the UsageRecord to the database."""
    try:
        with app.app_context():
            from app import db
            from app.models import UsageRecord

            record = _build_record(
                response=response,
                user_name=user_name,
                api_key_raw=api_key_raw,
                api_key_name=api_key_name,
                api_key_group_id=api_key_group_id,
                api_key_group_name=api_key_group_name,
                model_name=model_name,
                provider_id=provider_id,
                provider_name=provider_name,
                input_price_unit=input_price_unit,
                output_price_unit=output_price_unit,
                cache_creation_price_unit=cache_creation_price_unit,
                cache_token_price_unit=cache_token_price_unit,
                pricing_tiers=pricing_tiers,
                output_pricing=output_pricing,
                currency=currency,
                duration_ms=duration_ms,
                exchange_rate_to_cny=exchange_rate_to_cny,
            )
            db.session.add(record)
            db.session.commit()
    except Exception as exc:
        logger.exception(f"[usage] Failed to persist usage record: {exc}")


def _build_record(
    *,
    response,
    user_name,
    api_key_raw,
    api_key_name,
    api_key_group_id,
    api_key_group_name,
    model_name,
    provider_id,
    provider_name,
    input_price_unit,
    output_price_unit,
    cache_creation_price_unit,
    cache_token_price_unit,
    pricing_tiers=None,
    output_pricing=None,
    currency='USD',
    duration_ms=None,
    exchange_rate_to_cny=None,
):
    """Build a UsageRecord ORM object from the pre-extracted primitive values."""
    from app.models import UsageRecord

    usage = response.usage  # UsageInfo instance

    # ── API key identity ───────────────────────────────────────────────────
    api_key_hash: Optional[str] = None
    api_key_preview: Optional[str] = None
    if api_key_raw:
        api_key_hash = UsageRecord._hash_key(api_key_raw)
        api_key_preview = UsageRecord._mask_key(api_key_raw)

    # ── Token counts from UsageInfo ─────────────────────────────────────────
    input_tokens: int = usage.prompt_tokens or 0
    output_tokens: int = usage.completion_tokens or 0
    cache_creation_tokens: int = usage.cache_write_tokens or 0
    cache_tokens: int = usage.cache_read_tokens or usage.cached_tokens or 0
    reasoning_tokens: int = usage.reasoning_tokens or 0

    # ── Tier-aware pricing ─────────────────────────────────────────────────
    # Select the appropriate price tier based on actual input_tokens.
    # Falls back to flat model prices when no tiers are configured.
    (
        input_price_unit,
        output_price_unit,
        cache_creation_price_unit,
        cache_token_price_unit,
    ) = _resolve_price_tier(
        pricing_tiers=pricing_tiers,
        input_tokens=input_tokens,
        default_input_price=input_price_unit,
        default_output_price=output_price_unit,
        default_cache_creation_price=cache_creation_price_unit,
        default_cache_hit_price=cache_token_price_unit,
    )

    # ── Image / Video / Audio / Web search from usage.extra ────────────────
    extra = usage.extra if usage else {}

    output_image_number: int = extra.get('output_image_number', 0) or 0
    output_image_tokens: int = extra.get('output_image_tokens', 0) or 0
    output_image_resolution: Optional[str] = extra.get('output_image_resolution')
    output_image_aspect: Optional[str] = extra.get('output_image_aspect')
    output_image_price_unit: float = extra.get('output_image_price_unit', 0.0) or 0.0

    output_video_number: int = extra.get('output_video_number', 0) or 0
    output_video_tokens: int = extra.get('output_video_tokens', 0) or 0
    output_video_resolution: Optional[str] = extra.get('output_video_resolution')
    output_video_aspect: Optional[str] = extra.get('output_video_aspect')
    output_video_seconds: float = extra.get('output_video_seconds', 0.0) or 0.0
    output_video_price_unit: float = extra.get('output_video_price_unit', 0.0) or 0.0

    output_audio_tokens: int = extra.get('output_audio_tokens', 0) or 0
    output_audio_seconds: float = extra.get('output_audio_seconds', 0.0) or 0.0
    output_audio_price_unit: float = extra.get('output_audio_price_unit', 0.0) or 0.0

    web_search_requests: int = extra.get('web_search_requests', 0) or 0
    web_search_price_unit: float = extra.get('web_search_price_unit', 0.0) or 0.0

    # ── Resolve output pricing from model config ──────────────────────────
    # If the model defines output_pricing, use it to set the price_unit
    # fields unless the provider already supplied a non-zero value via extra.
    if output_pricing and isinstance(output_pricing, dict):
        if output_image_price_unit == 0.0:
            output_image_price_unit = _resolve_output_price(
                output_pricing.get('image'), output_image_resolution)
        if output_video_price_unit == 0.0:
            output_video_price_unit = _resolve_output_price(
                output_pricing.get('video'), output_video_resolution)
        if output_audio_price_unit == 0.0:
            output_audio_price_unit = _resolve_output_price(
                output_pricing.get('audio'), None)

    return UsageRecord(
        user_name=user_name,
        group_id=api_key_group_id,
        group_name=api_key_group_name,
        api_key_hash=api_key_hash,
        api_key_preview=api_key_preview,
        api_key_name=api_key_name,
        model_name=model_name,
        provider_id=provider_id,
        provider_name=provider_name,
        # Text tokens
        input_tokens=input_tokens,
        input_price_unit=input_price_unit,
        output_tokens=output_tokens,
        output_price_unit=output_price_unit,
        cache_creation_tokens=cache_creation_tokens,
        cache_creation_price_unit=cache_creation_price_unit,
        cache_tokens=cache_tokens,
        cache_token_price_unit=cache_token_price_unit,
        reasoning_tokens=reasoning_tokens,
        # Image
        output_image_number=output_image_number,
        output_image_tokens=output_image_tokens,
        output_image_resolution=output_image_resolution,
        output_image_aspect=output_image_aspect,
        output_image_price_unit=output_image_price_unit,
        # Video
        output_video_number=output_video_number,
        output_video_tokens=output_video_tokens,
        output_video_resolution=output_video_resolution,
        output_video_aspect=output_video_aspect,
        output_video_seconds=output_video_seconds,
        output_video_price_unit=output_video_price_unit,
        # Audio
        output_audio_tokens=output_audio_tokens,
        output_audio_seconds=output_audio_seconds,
        output_audio_price_unit=output_audio_price_unit,
        # Web search
        web_search_requests=web_search_requests,
        web_search_price_unit=web_search_price_unit,
        # Duration
        duration_ms=duration_ms,
        # Currency / exchange rate
        currency=currency,
        exchange_rate_to_cny=exchange_rate_to_cny,
    )
