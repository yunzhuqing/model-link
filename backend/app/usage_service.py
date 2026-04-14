"""
Usage Service - Records request consumption details to ml_usage_records.

This module provides two public functions:
  - record_usage()        – for completed non-streaming requests
  - record_stream_usage() – for completed streaming requests

Both are fire-and-forget: they spawn a daemon thread so the gateway response
is never delayed by the DB write.

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
from typing import Optional, TYPE_CHECKING

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

    input_price_unit: float = getattr(db_model, 'input_price', 0.0) or 0.0
    output_price_unit: float = getattr(db_model, 'output_price', 0.0) or 0.0
    cache_creation_price_unit: float = getattr(db_model, 'cache_creation_price', 0.0) or 0.0
    cache_token_price_unit: float = getattr(db_model, 'cache_hit_price', 0.0) or 0.0
    currency: str = getattr(db_model, 'currency', 'USD') or 'USD'

    # ── Determine exchange rate ────────────────────────────────────────────────
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
            currency=currency,
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
    # Currency (from model_meta dict)
    currency: str = 'USD',
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
            currency=currency,
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
    currency='USD',
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
                currency=currency,
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
    currency='USD',
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
        # Currency / exchange rate
        currency=currency,
        exchange_rate_to_cny=exchange_rate_to_cny,
    )
