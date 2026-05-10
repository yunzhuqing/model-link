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
    Perform one sync cycle with incremental aggregation:

      1. Find API keys that have recent usage (active keys only).
      2. For each active key, aggregate ONLY new records since its last sync
         position (id > last_stat_id), not the entire history.
      3. ADD incremental values to the existing cumulative counters.
      4. Update last_stat_id to the latest record id so the next cycle
         picks up where this one left off.

    This avoids full-table scans over ml_usage_records — only keys with
    new activity are touched, and only new rows are summed.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    db_url = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not db_url:
        return

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with Session(engine) as session:
            from app.models import ApiKey
            from app.cache import get_cache
            from app.usagerecord.stat import (
                get_active_key_hashes,
                compute_delta,
                apply_delta_to_apikey,
                apply_delta_to_cache,
            )
            import hashlib

            cache = get_cache()

            # ── Step 1: find active api_key_hashes and their max record id ──
            hash_max_id = get_active_key_hashes(session)
            if not hash_max_id:
                return

            # ── Step 2: load all API keys ──
            api_keys = session.query(ApiKey).all()
            updated_count = 0

            for ak in api_keys:
                key_hash = hashlib.sha256(ak.key.encode()).hexdigest()

                # Only sync keys that actually have usage records
                if key_hash not in hash_max_id:
                    continue

                last_stat = ak.last_stat_id or 0
                current_max = hash_max_id[key_hash]

                # No new records since last sync
                if last_stat >= current_max:
                    continue

                # ── Step 3: aggregate ONLY new records ──
                delta = compute_delta(session, key_hash, last_stat, current_max)
                if delta is None:
                    continue

                # ── Step 4: ADD incremental values to cumulative counters ──
                apply_delta_to_apikey(ak, delta)
                ak.last_stat_id = current_max
                updated_count += 1

                # ── Update cache with new cumulative values ──
                apply_delta_to_cache(cache, ak.key, ak)

                # Sync budget_remaining from DB's authoritative budget value
                if not ak.unlimited_budget and ak.budget is not None:
                    from app.budget_manager import get_budget_manager
                    get_budget_manager().set_remaining(ak.key, float(ak.budget))

            if updated_count > 0:
                session.commit()
                logger.info(f"[usage_sync] Incrementally synced {updated_count} API key(s) usage stats to DB")

    except Exception as exc:
        logger.error(f"[usage_sync] DB sync error: {exc}")
    finally:
        engine.dispose()
