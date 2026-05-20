"""
Usage Record Compression Service — Leader-node periodic compression of ml_usage_records.

Compresses high-traffic API keys by merging excess records within time windows
(per minute / per hour), grouping by (provider_id, model_name, time_bucket).
Original records are archived to storage before deletion.

Configuration:
  USAGE_COMPRESS_INTERVAL = 300  (seconds between compress runs, default: 300)
"""
from __future__ import annotations

import json
import logging
import os
import threading

logger = logging.getLogger("usage_compress")

_stop_event = threading.Event()
_compress_thread = None
_compress_lock = threading.Lock()


def start_compress_service(app) -> None:
    global _compress_thread
    with _compress_lock:
        if _compress_thread is not None and _compress_thread.is_alive():
            return
        _stop_event.clear()

    interval = float(os.getenv("USAGE_COMPRESS_INTERVAL", "600"))
    logger.info(f"[compress] Starting compress service (interval={interval}s)")

    _compress_thread = threading.Thread(
        target=_compress_loop,
        args=(app, interval),
        daemon=True,
        name="usage-compress",
    )
    _compress_thread.start()


def stop_compress_service() -> None:
    logger.info("[compress] Stopping compress service.")
    _stop_event.set()


def _compress_loop(app, interval: float) -> None:
    _stop_event.wait(timeout=min(interval, 30))

    while not _stop_event.is_set():
        try:
            from app.election_service import is_leader
            if not is_leader():
                logger.info("[compress] Not leader, stopping.")
                break
            _do_compress(app)
        except Exception as exc:
            logger.error(f"[compress] Error: {exc}")

        _stop_event.wait(timeout=interval)

    logger.info("[compress] Compress loop terminated.")


def _do_compress(app) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    db_url = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not db_url:
        return 0

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with Session(engine) as session:
            from app.models import ApiKey, ApiKeyPolicy
            from app.storage import get_storage_backend

            storage = get_storage_backend()

            # Load compress policies
            policies = (
                session.query(ApiKeyPolicy)
                .filter(ApiKeyPolicy.policy_type == "compress", ApiKeyPolicy.enabled == True)
                .all()
            )
            if not policies:
                return 0

            # Build api_key_id → config map and load ApiKeys
            policy_map = {p.api_key_id: p.config for p in policies}
            api_keys = {
                ak.id: ak
                for ak in session.query(ApiKey).filter(ApiKey.id.in_(policy_map.keys())).all()
            }

            total_compressed = 0

            for api_key_id, config in policy_map.items():
                ak = api_keys.get(api_key_id)
                if ak is None:
                    continue

                result = _compress_single_key(session, storage, ak, config)
                if result:
                    total_compressed += result["total_deleted"]

            if total_compressed > 0:
                session.commit()
                logger.info(f"[compress] Compressed {total_compressed} record(s) total")

    except Exception as exc:
        logger.error(f"[compress] DB error: {exc}", exc_info=True)
    finally:
        engine.dispose()

    return total_compressed


def _compress_key_for_api_key(app, api_key_id: int) -> dict:
    """Compress a single API key by id. Returns stats dict for the HTTP response."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    db_url = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not db_url:
        return {"detail": "No database URL configured"}

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with Session(engine) as session:
            from app.models import ApiKey, ApiKeyPolicy
            from app.storage import get_storage_backend

            storage = get_storage_backend()

            policy = (
                session.query(ApiKeyPolicy)
                .filter(
                    ApiKeyPolicy.api_key_id == api_key_id,
                    ApiKeyPolicy.policy_type == "compress",
                    ApiKeyPolicy.enabled == True,
                )
                .first()
            )
            if not policy:
                return {"detail": "No enabled compress policy for this API key"}

            ak = session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
            if not ak:
                return {"detail": "API key not found"}

            last_stat = ak.last_stat_id or 0
            if last_stat <= 0:
                return {"detail": "No synced records yet"}

            last_compress = ak.last_compress_id or 0
            if last_compress >= last_stat:
                return {"detail": "Nothing new to compress", "last_compress_id": last_compress, "last_stat_id": last_stat}

            result = _compress_single_key(session, storage, ak, policy.config)
            session.commit()
            return result

    except Exception as exc:
        logger.error(f"[compress] Error for key_id={api_key_id}: {exc}", exc_info=True)
        return {"detail": str(exc)}
    finally:
        engine.dispose()


def _compress_single_key(session, storage, ak, config: dict) -> dict:
    """Compress a single API key (ak is ORM object). Returns stats dict or None if skipped."""
    import hashlib
    from app.cache import get_cache

    last_stat = ak.last_stat_id or 0
    last_compress = ak.last_compress_id or 0

    if last_stat <= 0 or last_compress >= last_stat:
        return None

    key_hash = hashlib.sha256(ak.key.encode()).hexdigest()
    per_minute = int(config.get("per_minute", 1))
    per_hour = int(config.get("per_hour", 60))

    with get_cache().key_lock(key_hash):
        minute_deleted, minute_last_id = _compress_by_granularity(
            session, storage, key_hash, last_compress, last_stat, per_minute, "minute"
        )
        hour_deleted, hour_last_id = _compress_by_granularity(
            session, storage, key_hash, last_compress, last_stat, per_hour, "hour"
        )
        new_compress_id = max(minute_last_id, hour_last_id)
        if new_compress_id > last_compress:
            ak.last_compress_id = new_compress_id

    total_deleted = minute_deleted + hour_deleted
    if total_deleted > 0:
        logger.info(
            f"[compress] key_hash={key_hash[:12]}... "
            f"last_compress_id={last_compress}→{ak.last_compress_id} "
            f"last_stat_id={last_stat} "
            f"per_minute={per_minute} per_hour={per_hour} "
            f"minute_compressed={minute_deleted} hour_compressed={hour_deleted} "
            f"total_compressed={total_deleted}"
        )

    return {
        "key_hash": key_hash[:12],
        "last_compress_id": ak.last_compress_id,
        "last_stat_id": last_stat,
        "per_minute": per_minute,
        "per_hour": per_hour,
        "minute_compressed": minute_deleted,
        "hour_compressed": hour_deleted,
        "total_deleted": total_deleted,
    }


def _compress_by_granularity(session, storage, key_hash: str, last_compress_id: int,
                              last_stat_id: int, limit: int, granularity: str):
    """Compress records grouped by (provider_id, model_name, time_bucket).

    Only touches records in (last_compress_id, last_stat_id] (synced but not yet compressed).
    Merges excess records into the first record of each batch via UPDATE (no new rows),
    ensuring the bucket ends up with at most *limit* records.

    Returns (total_deleted, last_processed_id) — last_processed_id is the max
    UsageRecord.id that was part of any processed batch.
    """
    from app.models import UsageRecord
    from sqlalchemy import func

    BATCH_SIZE = 100

    if limit <= 0:
        return 0

    # Build DB-appropriate time-bucket expression
    db_url = str(session.get_bind().engine.url)
    if 'postgresql' in db_url:
        bucket_expr = func.date_trunc(granularity, UsageRecord.created_at)
    elif 'sqlite' in db_url:
        if granularity == 'minute':
            bucket_expr = func.strftime('%Y-%m-%dT%H:%M:00', UsageRecord.created_at)
        else:
            bucket_expr = func.strftime('%Y-%m-%dT%H:00:00', UsageRecord.created_at)
    else:
        # MySQL / MariaDB
        if granularity == 'minute':
            bucket_expr = func.date_format(UsageRecord.created_at, '%Y-%m-%dT%H:%i:00')
        else:
            bucket_expr = func.date_format(UsageRecord.created_at, '%Y-%m-%dT%H:00:00')

    # Find bucket groups with excess records, grouped by provider_id + model_name
    subq = (
        session.query(
            UsageRecord.provider_id,
            UsageRecord.model_name,
            bucket_expr.label("bucket"),
            func.count(UsageRecord.id).label("cnt"),
            func.min(UsageRecord.id).label("min_id"),
        )
        .filter(
            UsageRecord.api_key_hash == key_hash,
            UsageRecord.compressed_count == 1,
            UsageRecord.id > last_compress_id,
            UsageRecord.id <= last_stat_id,
        )
        .group_by(UsageRecord.provider_id, UsageRecord.model_name, bucket_expr)
        .having(func.count(UsageRecord.id) > limit)
        .all()
    )

    total_deleted = 0
    last_processed_id = 0

    for row in subq:
        provider_id = row.provider_id
        model_name = row.model_name
        bucket = row.bucket
        excess = row.cnt - limit  # Number of oldest records to compress

        while excess > 0:
            batch_size = min(BATCH_SIZE, excess)

            # Fetch a batch of the oldest records in this bucket
            batch = (
                session.query(UsageRecord)
                .filter(
                    UsageRecord.api_key_hash == key_hash,
                    UsageRecord.compressed_count == 1,
                    UsageRecord.id > last_compress_id,
                    UsageRecord.id <= last_stat_id,
                    UsageRecord.provider_id == provider_id,
                    UsageRecord.model_name == model_name,
                    bucket_expr == bucket,
                )
                .order_by(UsageRecord.id.asc())
                .limit(batch_size)
                .all()
            )

            if not batch:
                break

            last_processed_id = max(last_processed_id, batch[-1].id)

            # ── Archive originals before mutation ──
            originals_json = json.dumps(
                [r.to_dict() for r in batch], default=str
            )
            target_id = batch[0].id
            try:
                storage.write(f"usage/{target_id}/records.json", originals_json)
            except Exception as exc:
                logger.warning(f"[compress] Storage write failed for target_id={target_id}: {exc}")

            # ── Merge batch into the first record (UPDATE in-place) ──
            _merge_into_record(batch[0], batch[1:])

            # ── Delete the other records (NOT batch[0]) ──
            ids_to_delete = [r.id for r in batch[1:]]
            if ids_to_delete:
                session.query(UsageRecord).filter(
                    UsageRecord.id.in_(ids_to_delete)
                ).delete(synchronize_session=False)

            total_deleted += len(ids_to_delete)
            excess -= batch_size

    return total_deleted, last_processed_id


def _merge_into_record(target, others: list) -> None:
    """Merge *others* into *target* in-place. Target is mutated, others are not.

    Numeric fields are summed. compressed_count accumulates. Bucket identity fields
    (provider, model, time) are preserved from target.
    """
    all_records = [target] + others
    latest = others[-1] if others else target

    # Sum numeric fields
    target.input_tokens = sum(r.input_tokens or 0 for r in all_records)
    target.output_tokens = sum(r.output_tokens or 0 for r in all_records)
    target.reasoning_tokens = sum(r.reasoning_tokens or 0 for r in all_records)
    target.cache_creation_tokens = sum(r.cache_creation_tokens or 0 for r in all_records)
    target.cache_5m_creation_tokens = sum(r.cache_5m_creation_tokens or 0 for r in all_records)
    target.cache_1h_creation_tokens = sum(r.cache_1h_creation_tokens or 0 for r in all_records)
    target.cache_tokens = sum(r.cache_tokens or 0 for r in all_records)
    target.output_image_number = sum(r.output_image_number or 0 for r in all_records)
    target.output_image_tokens = sum(r.output_image_tokens or 0 for r in all_records)
    target.output_video_number = sum(r.output_video_number or 0 for r in all_records)
    target.output_video_tokens = sum(r.output_video_tokens or 0 for r in all_records)
    target.output_video_seconds = sum(r.output_video_seconds or 0 for r in all_records)
    target.output_audio_tokens = sum(r.output_audio_tokens or 0 for r in all_records)
    target.output_audio_seconds = sum(r.output_audio_seconds or 0 for r in all_records)
    target.web_search_requests = sum(r.web_search_requests or 0 for r in all_records)
    target.credits = sum(r.credits or 0 for r in all_records)
    target.payable_amount = sum(float(r.payable_amount or 0) for r in all_records)
    target.actual_amount = sum(float(r.actual_amount or 0) for r in all_records)
    target.actual_amount_usd = sum(float(r.actual_amount_usd or 0) for r in all_records)
    target.compressed_count = (target.compressed_count or 1) + sum(
        r.compressed_count or 1 for r in others
    )
    # Use latest record's price/currency fields
    target.input_price_unit = latest.input_price_unit
    target.output_price_unit = latest.output_price_unit
    target.cache_creation_price_unit = latest.cache_creation_price_unit
    target.cache_5m_creation_price_unit = latest.cache_5m_creation_price_unit
    target.cache_1h_creation_price_unit = latest.cache_1h_creation_price_unit
    target.cache_token_price_unit = latest.cache_token_price_unit
    target.output_image_price_unit = latest.output_image_price_unit
    target.output_video_price_unit = latest.output_video_price_unit
    target.output_audio_price_unit = latest.output_audio_price_unit
    target.web_search_price_unit = latest.web_search_price_unit
    target.credit_price_unit = latest.credit_price_unit
    target.currency = latest.currency
    target.exchange_rate = latest.exchange_rate
    target.discount = latest.discount
    target.duration_ms = None
    target.output_image_resolution = None
    target.output_image_aspect = None
    target.output_video_resolution = None
    target.output_video_aspect = None