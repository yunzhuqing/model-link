"""
Usage Sync Service — Leader-node periodic synchronisation of API key usage stats.

The leader node periodically:
  1. Queries the database for aggregated usage stats per API key (from ml_usage_records).
  2. Compares with the cached values.
  3. If they differ, updates the cache with the DB-authoritative values.
  4. Also persists the aggregated stats back to the ml_api_keys table so the
     data survives cache eviction / restarts.

This ensures that:
  - The cache always has accurate usage data (corrected by DB ground truth).
  - The ApiKey table has up-to-date cumulative stats for quick reads.
  - Only the leader node performs these potentially heavy DB queries.

Configuration (environment variables):
  USAGE_SYNC_INTERVAL  = 60   (seconds between sync runs, default: 60)
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("usage_sync")

_stop_event = threading.Event()
_sync_thread = None
_sync_lock = threading.Lock()


def start_usage_sync(app) -> None:
    """
    Start the periodic usage-sync daemon thread.

    Called by the election service's on_leader callback when this node
    becomes the leader.  If the sync thread is already running, this is
    a no-op.  If a previous thread exited (e.g. because leadership was
    lost), a new one is started.
    """
    global _sync_thread
    with _sync_lock:
        if _sync_thread is not None and _sync_thread.is_alive():
            return  # Already running
        _stop_event.clear()

    interval = float(os.getenv("USAGE_SYNC_INTERVAL", "60"))
    logger.info(f"[usage_sync] Starting usage sync service (interval={interval}s)")

    _sync_thread = threading.Thread(
        target=_sync_loop,
        args=(app, interval),
        daemon=True,
        name="usage-sync",
    )
    _sync_thread.start()


def stop_usage_sync() -> None:
    """
    Signal the sync loop to stop.

    Called by the election service's on_lost_leader callback when this node
    loses leadership.  The sync thread will exit on its next iteration.
    """
    logger.info("[usage_sync] Stopping usage sync service (leadership lost).")
    _stop_event.set()


def _sync_loop(app, interval: float) -> None:
    """
    Main sync loop — only started on the leader node (via register_on_leader).

    If this node loses leadership, the loop stops itself.
    """
    # Wait a bit before first run to let the app fully start
    _stop_event.wait(timeout=min(interval, 15))

    while not _stop_event.is_set():
        try:
            from app.election_service import is_leader
            if not is_leader():
                logger.info("[usage_sync] This node is no longer the leader. Stopping sync loop.")
                break
            _do_sync(app)
        except Exception as exc:
            logger.error(f"[usage_sync] Sync error: {exc}")

        _stop_event.wait(timeout=interval)

    logger.info("[usage_sync] Sync loop terminated.")


def _do_sync(app) -> None:
    """
    Perform one sync cycle:
      1. Query DB for per-API-key aggregated usage.
      2. Compare with cache and correct if needed.
      3. Write back to ApiKey table.
    """
    from sqlalchemy import create_engine, func
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    db_url = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not db_url:
        return

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with Session(engine) as session:
            from app.models import UsageRecord, ApiKey
            from app.cache import get_cache

            cache = get_cache()

            # Query aggregated usage per api_key_hash
            rows = session.query(
                UsageRecord.api_key_hash,
                func.count(UsageRecord.id).label("requests"),
                func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
                func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
                func.coalesce(func.sum(UsageRecord.output_image_number), 0).label("total_image_count"),
                func.coalesce(func.sum(UsageRecord.output_video_number), 0).label("total_video_count"),
                func.coalesce(func.sum(UsageRecord.output_audio_seconds), 0).label("total_audio_seconds"),
            ).filter(
                UsageRecord.api_key_hash.isnot(None)
            ).group_by(
                UsageRecord.api_key_hash
            ).all()

            if not rows:
                return

            # Build a hash → stats map
            import hashlib
            db_stats = {}
            for r in rows:
                db_stats[r.api_key_hash] = {
                    'request_count': r.requests or 0,
                    'total_input_tokens': int(r.input_tokens or 0),
                    'total_output_tokens': int(r.output_tokens or 0),
                    'total_reasoning_tokens': int(r.reasoning_tokens or 0),
                    'total_cost_usd': round(float(r.total_cost_usd or 0), 6),
                    'total_image_count': int(r.total_image_count or 0),
                    'total_video_count': int(r.total_video_count or 0),
                    'total_audio_seconds': round(float(r.total_audio_seconds or 0), 4),
                }

            # Get all API keys and update both cache and DB
            api_keys = session.query(ApiKey).all()
            updated_count = 0

            for ak in api_keys:
                key_hash = hashlib.sha256(ak.key.encode()).hexdigest()
                stats = db_stats.get(key_hash)
                if not stats:
                    continue

                # Update the ApiKey DB record with authoritative stats
                changed = False
                if ak.request_count != stats['request_count']:
                    ak.request_count = stats['request_count']
                    changed = True
                total_tokens = stats['total_input_tokens'] + stats['total_output_tokens']
                if ak.token_count != total_tokens:
                    ak.token_count = total_tokens
                    changed = True
                if (ak.total_input_tokens or 0) != stats['total_input_tokens']:
                    ak.total_input_tokens = stats['total_input_tokens']
                    changed = True
                if (ak.total_output_tokens or 0) != stats['total_output_tokens']:
                    ak.total_output_tokens = stats['total_output_tokens']
                    changed = True
                if (ak.total_reasoning_tokens or 0) != stats['total_reasoning_tokens']:
                    ak.total_reasoning_tokens = stats['total_reasoning_tokens']
                    changed = True
                if round(ak.total_cost_usd or 0, 6) != stats['total_cost_usd']:
                    ak.total_cost_usd = stats['total_cost_usd']
                    changed = True
                if (ak.total_image_count or 0) != stats['total_image_count']:
                    ak.total_image_count = stats['total_image_count']
                    changed = True
                if (ak.total_video_count or 0) != stats['total_video_count']:
                    ak.total_video_count = stats['total_video_count']
                    changed = True
                if round(ak.total_audio_seconds or 0, 4) != stats['total_audio_seconds']:
                    ak.total_audio_seconds = stats['total_audio_seconds']
                    changed = True

                if changed:
                    updated_count += 1

                # Also correct the cache if it exists
                cached = cache.get_api_key_info(ak.key)
                if cached is not None:
                    cache_dirty = False
                    for field, db_val in stats.items():
                        cached_val = cached.get(field, 0)
                        # Allow small float tolerance
                        if isinstance(db_val, float):
                            if abs((cached_val or 0) - db_val) > 0.001:
                                cached[field] = db_val
                                cache_dirty = True
                        else:
                            if (cached_val or 0) != db_val:
                                cached[field] = db_val
                                cache_dirty = True

                    # Also sync budget_used (= total_cost_usd)
                    if abs((cached.get('budget_used', 0) or 0) - stats['total_cost_usd']) > 0.001:
                        cached['budget_used'] = stats['total_cost_usd']
                        cache_dirty = True

                    # Sync token_count
                    if (cached.get('token_count', 0) or 0) != total_tokens:
                        cached['token_count'] = total_tokens
                        cache_dirty = True

                    if cache_dirty:
                        cache.set_api_key_info(ak.key, cached)

            if updated_count > 0:
                session.commit()
                logger.info(f"[usage_sync] Synced {updated_count} API key(s) usage stats to DB")

    except Exception as exc:
        logger.error(f"[usage_sync] DB sync error: {exc}")
    finally:
        engine.dispose()
