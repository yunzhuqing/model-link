"""
Usage Service - Records request consumption details to ml_usage_records.

This module provides a single public function `record_usage()` that is called
from the gateway routes after every successful API request. It runs in a
background thread so it never blocks the response path.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.abstraction.chat import ChatResponse, UsageInfo
    from app.models import ApiKey, User, Provider, Model as DbModel

logger = logging.getLogger("usage")


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
) -> None:
    """
    Persist one UsageRecord row for a completed streaming request.

    Called after the stream finishes with the accumulated UsageInfo from
    the final usage chunk.  Runs in a daemon background thread.

    Args:
        app:               The Flask application instance.
        usage_info:        UsageInfo dataclass from the last stream chunk.
        user_name:         Caller's username (from JWT), or None.
        api_key_raw:       Raw API key string, or None.
        api_key_name:      API key display name, or None.
        api_key_group_id:  Group ID from the API key, or None.
        api_key_group_name: Group name from the API key, or None.
        model_name:        Model name as sent by the caller.
        provider_id:       Provider DB ID.
        provider_name:     Provider display name.
        input_price_unit:  Price per 1M input tokens.
        output_price_unit: Price per 1M output tokens.
        cache_creation_price_unit: Price per 1M cache-write tokens.
        cache_token_price_unit:    Price per 1M cache-read tokens.
    """
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
        ),
        daemon=True,
    )
    thread.start()


class _UsageOnlyResponse:
    """Minimal response-like object wrapping a UsageInfo for _build_record compatibility."""
    def __init__(self, usage_info):
        self.usage = usage_info


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

    This call is fire-and-forget: it spawns a daemon thread so the gateway
    response is never delayed by the DB write.

    All data needed from SQLAlchemy ORM objects is extracted eagerly here
    (in the request thread, while the session is still alive) and passed as
    plain Python values to the background thread.  This avoids cross-thread
    lazy-loading on a closed/detached session.

    Args:
        app:               The Flask application instance (for app context).
        response:          The ChatResponse returned by the provider.
        db_model:          The resolved Model ORM object.
        db_provider:       The resolved Provider ORM object.
        api_key:           The authenticated ApiKey ORM object (or None for JWT auth).
        user:              The authenticated User ORM object (or None for API-key auth).
        request_model_name: The model name as sent by the caller (alias or real name).
    """
    # ── Eagerly extract all primitive values from ORM objects ─────────────────
    # ORM objects must NOT be passed to the background thread: the SQLAlchemy
    # session they are attached to belongs to the current request thread, and
    # accessing any un-loaded relationship across that boundary triggers a lazy
    # load on a closed/detached connection, raising "read of closed file".

    user_name: Optional[str] = user.username if user else None

    api_key_raw: Optional[str] = None
    api_key_name: Optional[str] = None
    api_key_group_id: Optional[int] = None
    api_key_group_name: Optional[str] = None

    if api_key:
        api_key_raw = api_key.key
        api_key_name = api_key.name
        api_key_group_id = api_key.group_id
        # Eagerly access the group relationship while the session is open.
        try:
            if api_key.group:
                api_key_group_name = api_key.group.name
        except Exception:
            pass  # group not loaded — group_name stays None

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

    thread = threading.Thread(
        target=_persist_usage,
        kwargs=dict(
            app=app,
            response=response,
            # Identity
            user_name=user_name,
            api_key_raw=api_key_raw,
            api_key_name=api_key_name,
            api_key_group_id=api_key_group_id,
            api_key_group_name=api_key_group_name,
            # Model / provider
            model_name=model_name,
            provider_id=provider_id,
            provider_name=provider_name,
            # Pricing
            input_price_unit=input_price_unit,
            output_price_unit=output_price_unit,
            cache_creation_price_unit=cache_creation_price_unit,
            cache_token_price_unit=cache_token_price_unit,
        ),
        daemon=True,
    )
    thread.start()


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
    )
