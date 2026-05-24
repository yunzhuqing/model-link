"""
Usage Service - Records request consumption details to ml_usage_records.

This module provides two public functions:
  - record_usage()        – for completed non-streaming requests
  - record_stream_usage() – for completed streaming requests

Both are fire-and-forget: they spawn a background asyncio task so the
gateway response is never delayed by the DB write.

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
  - currency          – pricing currency of the model ("USD", "CNY", …)
  - exchange_rate     – USD→{currency} rate at the time of the request
                        (1.0 when currency is USD)
  - actual_amount_usd – cost converted to USD = actual_amount / exchange_rate

The exchange rate is read from the in-memory cache maintained by
exchange_rate_service (refreshed daily from frankfurter.app).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.abstraction.chat import ChatResponse, UsageInfo

logger = logging.getLogger("usage")


# Per-segment timing for _persist_record. Set USAGE_PERSIST_TRACE=<seconds>
# (e.g. "0.5") to log any segment slower than the threshold. Disabled when
# the env var is unset or non-positive.
_PERSIST_TRACE_THRESHOLD = float(os.getenv("USAGE_PERSIST_TRACE", "0") or 0)


@contextlib.asynccontextmanager
async def _timed(label: str):
    if _PERSIST_TRACE_THRESHOLD <= 0:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        if dt >= _PERSIST_TRACE_THRESHOLD:
            logger.warning("[persist_trace] %s took %.3fs", label, dt)


# ── Public API ────────────────────────────────────────────────────────────────

async def record_usage(
    *,
    response: "ChatResponse",
    # Identity (plain Python primitives — no ORM objects)
    user_name: Optional[str] = None,
    user_id: Optional[int] = None,
    api_key_raw: Optional[str] = None,
    api_key_name: Optional[str] = None,
    api_key_group_id: Optional[int] = None,
    api_key_group_name: Optional[str] = None,
    # Model / provider (extracted from ResolvedModelData)
    model_name: Optional[str] = None,
    provider_id: Optional[int] = None,
    provider_name: Optional[str] = None,
    # Pricing (plain floats — extracted upstream from ORM)
    input_price_unit: float = 0.0,
    output_price_unit: float = 0.0,
    cache_creation_price_unit: float = 0.0,
    cache_5m_creation_price_unit: float = 0.0,
    cache_1h_creation_price_unit: float = 0.0,
    cache_token_price_unit: float = 0.0,
    pricing_tiers: Optional[list] = None,
    output_pricing: Optional[dict] = None,
    currency: str = 'USD',
    discount: float = 1.0,
    duration_ms: Optional[int] = None,
) -> None:
    """
    Persist one UsageRecord row for a completed (non-streaming) request.

    All arguments are plain Python primitives — the SQLAlchemy session that
    produced these values is typically already closed by the time this is
    called (the gateway eagerly extracts everything to a dataclass in the
    short-lived resolve session).
    """
    exchange_rate = _get_exchange_rate_for_currency(currency)

    asyncio.create_task(_persist_usage_async(
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
        cache_5m_creation_price_unit=cache_5m_creation_price_unit,
        cache_1h_creation_price_unit=cache_1h_creation_price_unit,
        cache_token_price_unit=cache_token_price_unit,
        pricing_tiers=pricing_tiers,
        output_pricing=output_pricing,
        currency=currency,
        duration_ms=duration_ms,
        exchange_rate=exchange_rate,
        discount=discount,
        user_id=user_id,
    ))


async def record_stream_usage(
    *,
    usage_info,
    # Identity (plain Python primitives — no ORM objects)
    user_name: Optional[str] = None,
    user_id: Optional[int] = None,
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
    cache_5m_creation_price_unit: float = 0.0,
    cache_1h_creation_price_unit: float = 0.0,
    cache_token_price_unit: float = 0.0,
    pricing_tiers: Optional[list] = None,
    output_pricing: Optional[dict] = None,
    # Currency (from model_meta dict)
    currency: str = 'USD',
    # Discount
    discount: float = 1.0,
    # Duration
    duration_ms: Optional[int] = None,
) -> None:
    """
    Persist one UsageRecord row for a completed streaming request.

    Called after the stream finishes with the accumulated UsageInfo from
    the final usage chunk.  Runs as a fire-and-forget background asyncio task.

    All arguments must be plain Python primitives (no ORM objects), since
    the SQLAlchemy session is already closed by the time the stream ends.
    """
    exchange_rate = _get_exchange_rate_for_currency(currency)

    asyncio.create_task(_persist_usage_async(
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
        cache_5m_creation_price_unit=cache_5m_creation_price_unit,
        cache_1h_creation_price_unit=cache_1h_creation_price_unit,
        cache_token_price_unit=cache_token_price_unit,
        pricing_tiers=pricing_tiers,
        output_pricing=output_pricing,
        currency=currency,
        duration_ms=duration_ms,
        exchange_rate=exchange_rate,
        discount=discount,
        user_id=user_id,
    ))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_exchange_rate_for_currency(currency: str) -> float:
    """
    Return the exchange rate from USD to the model's pricing currency.

    - If currency is 'USD', rate = 1.0 (no conversion needed).
    - If currency is 'CNY', return the live USD→CNY rate from the in-memory
      cache maintained by exchange_rate_service.
    - For other currencies, return the USD→CNY rate as fallback.

    This rate is stored in UsageRecord.exchange_rate and used to compute
    actual_amount_usd = actual_amount / exchange_rate.
    """
    if (currency or 'USD').upper() == 'USD':
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
    audio: Optional[bool] = None,
    reference_video: Optional[bool] = None,
    quality: Optional[str] = None,
) -> float:
    """
    Resolve the per-unit price from an output_pricing sub-config.

    Args:
        pricing_config: One of output_pricing["image"], output_pricing["video"],
                        or output_pricing["audio"].  Structure:
                        {"type": "per_image"|"per_second"|"per_token",
                         "price": <float>,
                         "tiers": [{"resolution": "1K", "audio": bool,
                                    "reference_video": bool, "quality": "low",
                                    "price": <float>}, ...]}
        resolution:     The actual resolution string from the request (e.g. "1K", "720p").
                        Used for tier matching when tiers are present.
        audio:          Whether the output includes audio (for video tiers).
        reference_video: Whether a reference video was used (for video tiers).
        quality:        Quality tier (e.g. "low", "medium", "high") for image models
                        like GPT Image 2 whose pricing varies by quality.

    Returns:
        The resolved price (float). Returns 0.0 if pricing_config is None.

    Tier matching logic:
      1. Filter tiers by resolution (case-insensitive).
      2. Among matching tiers, find the best match by ``audio``,
         ``reference_video``, and ``quality`` flags. A tier matches a flag when:
           - the tier does not define the flag (treated as wildcard), OR
           - the tier's flag value equals the request's flag value.
         Tiers with more explicit flag matches are preferred.
      3. If no tier matches, fall back to base_price.
    """
    if not pricing_config or not isinstance(pricing_config, dict):
        return 0.0

    base_price: float = float(pricing_config.get('price', 0.0) or 0.0)

    # If tiers exist, try to match by resolution / audio / reference_video / quality flags.
    # Resolution is optional — tiers without a resolution field match any resolution.
    tiers = pricing_config.get('tiers')
    if tiers and isinstance(tiers, list):
        norm_res = resolution.strip().lower() if resolution else ''
        norm_quality = quality.strip().lower() if quality else ''

        # Collect candidate tiers
        candidates: list = []
        for tier in tiers:
            if not isinstance(tier, dict):
                continue

            # Resolution matching: tier without resolution → wildcard (matches any)
            tier_res = (tier.get('resolution') or '').strip().lower()
            if tier_res and norm_res and tier_res != norm_res:
                continue  # Resolution mismatch

            # Quality matching: tier without quality → wildcard (matches any)
            tier_quality = (tier.get('quality') or '').strip().lower()
            if tier_quality and norm_quality and tier_quality != norm_quality:
                continue  # Quality mismatch

            # Check audio and reference_video flags
            tier_audio = tier.get('audio')            # None means wildcard
            tier_ref = tier.get('reference_video')    # None means wildcard

            # Compute match score (higher = more specific match)
            score = 0
            match = True

            # Resolution specificity bonus
            if tier_res and norm_res and tier_res == norm_res:
                score += 1  # Exact resolution match is preferred

            # Quality specificity bonus
            if tier_quality and norm_quality and tier_quality == norm_quality:
                score += 1  # Exact quality match is preferred

            # Audio flag matching
            if tier_audio is not None and audio is not None:
                if bool(tier_audio) != bool(audio):
                    match = False
                else:
                    score += 1
            elif tier_audio is not None:
                # Tier specifies audio but request doesn't — prefer non-audio
                if bool(tier_audio):
                    score -= 1

            # Reference video flag matching
            if tier_ref is not None and reference_video is not None:
                if bool(tier_ref) != bool(reference_video):
                    match = False
                else:
                    score += 1
            elif tier_ref is not None:
                # Tier specifies ref_video but request doesn't — prefer non-ref
                if bool(tier_ref):
                    score -= 1

            if match:
                candidates.append((score, tier))

        if candidates:
            # Pick the best matching tier (highest score)
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_tier = candidates[0][1]
            return float(best_tier.get('price', base_price) or base_price)

    return base_price


async def _deduct_budget_records(session, api_key_raw: str, amount_usd: float) -> None:
    """
    Deduct spending from budget records in the ml_api_key_budgets table.

    Deducts from the oldest budget with remaining > 0 first. If a budget
    is exhausted, continues to the next one. Also updates ApiKey.budget
    (total remaining) for backward compatibility.

    Args:
        session: The active async SQLAlchemy Session.
        api_key_raw: The raw API key string.
        amount_usd: Amount in USD to deduct.
    """
    from sqlalchemy import select

    # Coerce to float in case amount_usd is a Decimal (e.g. from UsageRecord.actual_amount_usd)
    amount_usd = float(amount_usd)
    if amount_usd <= 0:
        return

    try:
        from app.models import ApiKey as AK, ApiKeyBudget as AKB

        # Find the API key by raw key
        result = await session.execute(select(AK).where(AK.key == api_key_raw))
        ak = result.scalars().first()
        if not ak:
            return

        # Get budget records with remaining > 0, ordered by created_at (oldest first)
        result = await session.execute(
            select(AKB)
            .where(AKB.api_key_id == ak.id, AKB.remaining > 0)
            .order_by(AKB.created_at.asc())
        )
        budgets = result.scalars().all()

        if not budgets:
            return

        remaining_to_deduct = amount_usd
        for budget in budgets:
            if remaining_to_deduct <= 0:
                break
            # Coerce Decimal → float to avoid mixed-type arithmetic errors
            budget_remaining = float(budget.remaining or 0)
            if budget_remaining >= remaining_to_deduct:
                budget.remaining = round(budget_remaining - remaining_to_deduct, 6)
                remaining_to_deduct = 0
            else:
                remaining_to_deduct = round(remaining_to_deduct - budget_remaining, 6)
                budget.remaining = 0.0

        # Sync ApiKey.budget to match the sum of remaining amounts across all
        # budget records, so it always reflects the authoritative total.
        total_remaining = sum(float(b.remaining or 0) for b in budgets)
        ak.budget = max(round(total_remaining, 6), 0.0)
    except Exception as exc:
        logger.warning(f"[budget] Failed to deduct budget records, rolling back: {exc}")
        try:
            await session.rollback()
        except Exception:
            pass
        raise


class _UsageOnlyResponse:
    """Minimal response-like object wrapping a UsageInfo for _persist_usage_async compatibility."""
    def __init__(self, usage_info):
        self.usage = usage_info


async def _persist_usage_async(
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
    cache_5m_creation_price_unit,
    cache_1h_creation_price_unit,
    cache_token_price_unit,
    pricing_tiers=None,
    output_pricing=None,
    currency='USD',
    duration_ms=None,
    exchange_rate=None,
    discount=1.0,
    user_id=None,
) -> None:
    """Worker that actually writes the UsageRecord to the database.

    Runs as a fire-and-forget background asyncio task, using the main app's
    async session factory for DB access.
    """
    try:
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
            cache_5m_creation_price_unit=cache_5m_creation_price_unit,
            cache_1h_creation_price_unit=cache_1h_creation_price_unit,
            cache_token_price_unit=cache_token_price_unit,
            pricing_tiers=pricing_tiers,
            output_pricing=output_pricing,
            currency=currency,
            duration_ms=duration_ms,
            exchange_rate=exchange_rate,
            discount=discount,
            user_id=user_id,
        )

        await _persist_record(record, api_key_raw=api_key_raw)
    except Exception as exc:
        logger.exception(f"[usage] Failed to persist usage record: {exc}")


async def _persist_record(record, api_key_raw: str = None) -> None:
    """Insert a UsageRecord row using the main async session factory.

    After a successful DB write, if the API key has a budget set, the
    actual_amount_usd is deducted from the cache so that budget checks
    remain accurate without waiting for the cache to expire.

    Also increments the cached usage stats (tokens, cost, image/video/audio
    counts) so that the API key detail page can show real-time data from
    cache without querying the database.
    """
    from app import get_db_session

    async with _timed("acquire_db_session_and_body"), get_db_session() as session:
        session.add(record)
        # Don't commit yet — budget deduction must be in the same transaction

        # ── Async budget deduction + usage stats to cache ────────────
        if api_key_raw:
            try:
                from app.cache import get_async_cache
                cache = get_async_cache()

                # Capture all record values before commit — after commit,
                # the session expires all ORM objects and accessing any
                # attribute would trigger a lazy-load, which fails for
                # background tasks without a greenlet context.
                actual_usd = float(getattr(record, 'actual_amount_usd', None) or 0)
                _input_tokens = int(getattr(record, 'input_tokens', 0) or 0)
                _output_tokens = int(getattr(record, 'output_tokens', 0) or 0)
                _reasoning_tokens = int(getattr(record, 'reasoning_tokens', 0) or 0)
                _image_count = int(getattr(record, 'output_image_number', 0) or 0)
                _video_count = int(getattr(record, 'output_video_number', 0) or 0)
                _audio_seconds = float(getattr(record, 'output_audio_seconds', 0.0) or 0.0)
                _web_search_requests = int(getattr(record, 'web_search_requests', 0) or 0)
                _credits = float(getattr(record, 'credits', 0.0) or 0.0)

                # Only deduct budget if the key is NOT unlimited
                async with _timed("cache.get_api_key_info"):
                    cached_info = await cache.get_api_key_info(api_key_raw)
                is_unlimited = cached_info.get('unlimited_budget', True) if cached_info else True
                if actual_usd > 0 and not is_unlimited:
                    # Deduct from DB budget records first (oldest first),
                    # then sync the cache so cache and DB stay consistent.
                    async with _timed("deduct_budget_records"):
                        await _deduct_budget_records(session, api_key_raw, actual_usd)
                    from app.budget_manager import get_async_budget_manager
                    async with _timed("budget_manager.deduct"):
                        await get_async_budget_manager().deduct(api_key_raw, actual_usd)

                # Commit both the usage record and budget deduction atomically
                async with _timed("session.commit (with budget)"):
                    await session.commit()

                # Increment real-time usage stats in cache (uses local vars,
                # not record attributes — record is expired after commit)
                async with _timed("cache.increment_usage_stats"):
                    await cache.increment_usage_stats(
                        api_key_raw,
                        request_count=1,
                        input_tokens=_input_tokens,
                        output_tokens=_output_tokens,
                        reasoning_tokens=_reasoning_tokens,
                        cost_usd=actual_usd,
                        image_count=_image_count,
                        video_count=_video_count,
                        audio_seconds=_audio_seconds,
                        web_search_requests=_web_search_requests,
                        credits=_credits,
                    )
            except Exception as _ce:
                logger.error(f"[cache] Failed to update cache after usage record: {_ce}", exc_info=True)
        else:
            async with _timed("session.commit (no budget)"):
                await session.commit()


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
    cache_5m_creation_price_unit,
    cache_1h_creation_price_unit,
    cache_token_price_unit,
    pricing_tiers=None,
    output_pricing=None,
    currency='USD',
    duration_ms=None,
    exchange_rate=None,
    discount=1.0,
    user_id=None,
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
    raw_prompt_tokens: int = usage.prompt_tokens or 0
    output_tokens: int = usage.completion_tokens or 0
    cache_creation_tokens: int = usage.cache_write_tokens or 0
    cache_tokens: int = usage.cache_read_tokens or usage.cached_tokens or 0

    # Extract 5m and 1h cache creation tokens from Anthropic's cache_creation nested object
    cache_creation_detail = usage.extra.get('cache_creation', {}) if usage.extra else {}
    cache_5m_creation_tokens: int = 0
    cache_1h_creation_tokens: int = 0
    if isinstance(cache_creation_detail, dict):
        # Anthropic format: ephemeral_5m_input_tokens, ephemeral_1h_input_tokens
        cache_5m_creation_tokens = int(cache_creation_detail.get('ephemeral_5m_input_tokens', 0) or 0)
        cache_1h_creation_tokens = int(cache_creation_detail.get('ephemeral_1h_input_tokens', 0) or 0)
    reasoning_tokens: int = usage.reasoning_tokens or 0

    # prompt_tokens includes cache_read and cache_creation tokens.
    # For billing: input_tokens = raw_input + cache_creation (both billed at
    # input_price_unit).  Only cache_read tokens are billed separately at
    # cache_token_price_unit (cache_hit price).  So we only subtract
    # cache_tokens (cache_read) from prompt_tokens to get input_tokens.
    input_tokens: int = max(raw_prompt_tokens - cache_tokens, 0)

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
    output_image_quality: Optional[str] = extra.get('output_image_quality')
    output_image_price_unit: float = extra.get('output_image_price_unit', 0.0) or 0.0

    output_video_number: int = extra.get('output_video_number', 0) or 0
    output_video_tokens: int = extra.get('output_video_tokens', 0) or 0
    output_video_resolution: Optional[str] = extra.get('output_video_resolution')
    output_video_aspect: Optional[str] = extra.get('output_video_aspect')
    output_video_seconds: float = extra.get('output_video_seconds', 0.0) or 0.0
    output_video_price_unit: float = extra.get('output_video_price_unit', 0.0) or 0.0
    output_video_audio: Optional[bool] = extra.get('output_video_audio')
    output_video_reference_video: Optional[bool] = extra.get('output_video_reference_video')

    output_audio_tokens: int = extra.get('output_audio_tokens', 0) or 0
    output_audio_seconds: float = extra.get('output_audio_seconds', 0.0) or 0.0
    output_audio_price_unit: float = extra.get('output_audio_price_unit', 0.0) or 0.0

    web_search_requests: int = extra.get('web_search_requests', 0) or 0
    web_search_price_unit: float = extra.get('web_search_price_unit', 0.0) or 0.0

    credits: float = float(extra.get('credits', 0) or 0)
    credit_price_unit: float = float(extra.get('credit_price_unit', 0.0) or 0.0)

    # ── Resolve output pricing from model config ──────────────────────────
    # If the model defines output_pricing, use it to set the price_unit
    # fields unless the provider already supplied a non-zero value via extra.
    if output_pricing and isinstance(output_pricing, dict):
        if output_image_price_unit == 0.0:
            output_image_price_unit = _resolve_output_price(
                output_pricing.get('image'), output_image_resolution,
                quality=output_image_quality)
        # For video: per_token pricing uses output_price_unit (per M tokens),
        # while per_second/per_video pricing uses output_video_price_unit.
        video_pricing_config = output_pricing.get('video')
        if video_pricing_config and isinstance(video_pricing_config, dict):
            video_pricing_type = video_pricing_config.get('type', '')
            resolved_video_price = _resolve_output_price(
                video_pricing_config, output_video_resolution,
                audio=output_video_audio,
                reference_video=output_video_reference_video)
            if video_pricing_type == 'per_token' and resolved_video_price > 0:
                # per_token: price is ¥/M output tokens → override output_price_unit
                output_price_unit = resolved_video_price
            elif output_video_price_unit == 0.0:
                # per_second / per_video: use output_video_price_unit
                output_video_price_unit = resolved_video_price
        if output_audio_price_unit == 0.0:
            output_audio_price_unit = _resolve_output_price(
                output_pricing.get('audio'), None)

        # 3D generation: resolve credit price from model config if not set by provider
        if credit_price_unit == 0.0:
            td_config = output_pricing.get('3d')
            if td_config and isinstance(td_config, dict):
                credit_price_unit = float(td_config.get('price', 0.0) or 0.0)

    # ── Billing amounts ───────────────────────────────────────────────────
    # payable_amount = total cost before discount (in native currency)
    # Prices are per 1M tokens for text; per unit for image/video/audio/search.
    # Note: input_tokens already includes cache_creation_tokens; both are
    # billed at input_price_unit.  cache_tokens (cache_read) are billed
    # separately at cache_token_price_unit.
    # Cache creation cost calculation:
    # - If the response includes 5m/1h ephemeral cache creation tokens (Anthropic),
    #   use the respective 5m/1h prices for those tokens.
    # - Remaining cache_creation_tokens (not accounted by 5m/1h) use cache_creation_price_unit.
    # - If no 5m/1h tokens, use simple cache_creation_price_unit for all cache_creation_tokens.
    cache_creation_cost: float = 0.0
    if cache_5m_creation_tokens > 0 or cache_1h_creation_tokens > 0:
        # Anthropic ephemeral cache pricing: 5m and 1h tokens billed at their respective prices
        cache_creation_cost = (
            cache_5m_creation_tokens * cache_5m_creation_price_unit / 1_000_000
            + cache_1h_creation_tokens * cache_1h_creation_price_unit / 1_000_000
        )
        # Remaining tokens (cache_creation_tokens - 5m - 1h) use simple price
        remaining_tokens = max(cache_creation_tokens - cache_5m_creation_tokens - cache_1h_creation_tokens, 0)
        cache_creation_cost += remaining_tokens * cache_creation_price_unit / 1_000_000
    elif cache_creation_price_unit > 0:
        # Simple per-token cache creation pricing (legacy / other models)
        cache_creation_cost = cache_creation_tokens * cache_creation_price_unit / 1_000_000

    payable_amount: float = float(
        input_tokens * input_price_unit / 1_000_000
        + output_tokens * output_price_unit / 1_000_000
        + cache_creation_cost
        + cache_tokens * cache_token_price_unit / 1_000_000
        + output_image_number * output_image_price_unit
        + output_video_number * output_video_price_unit
        + output_audio_seconds * output_audio_price_unit
        + web_search_requests * web_search_price_unit
        + credits * credit_price_unit
    )
    # Ensure discount is valid (coerce to float to handle decimal.Decimal from DB)
    effective_discount: float = float(discount) if discount and discount > 0 else 1.0
    actual_amount: float = payable_amount * effective_discount
    # Convert to USD: actual_amount is in native currency, exchange_rate is USD→native
    effective_exchange_rate: float = float(exchange_rate) if exchange_rate and exchange_rate > 0 else 1.0
    actual_amount_usd: float = actual_amount / effective_exchange_rate

    return UsageRecord(
        user_name=user_name,
        user_id=user_id,
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
        cache_5m_creation_tokens=cache_5m_creation_tokens,
        cache_5m_creation_price_unit=cache_5m_creation_price_unit,
        cache_1h_creation_tokens=cache_1h_creation_tokens,
        cache_1h_creation_price_unit=cache_1h_creation_price_unit,
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
        # 3D credits
        credits=credits,
        credit_price_unit=credit_price_unit,
        # Duration
        duration_ms=duration_ms,
        # Currency / exchange rate
        currency=currency,
        exchange_rate=effective_exchange_rate,
        # Billing
        payable_amount=payable_amount,
        discount=effective_discount,
        actual_amount=actual_amount,
        actual_amount_usd=actual_amount_usd,
    )
