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
from datetime import datetime, timedelta, timezone

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

    interval = float(os.getenv("USAGE_SYNC_INTERVAL", "600"))
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
            _do_sync(app, interval)
        except Exception as exc:
            logger.error(f"[usage_sync] Sync error: {exc}")

        _stop_event.wait(timeout=interval)

    logger.info("[usage_sync] Sync loop terminated.")


def _do_sync(app, interval: float = 60) -> None:
    """
    Perform one sync cycle with incremental aggregation:

      1. Find API keys that have usage records within the lookback window
         (now - interval).
      2. For each active key, aggregate ONLY new records since its last sync
         position (id > last_stat_id), not the entire history.
      3. ADD incremental values to the existing cumulative counters.
      4. Update last_stat_id to the latest record id so the next cycle
         picks up where this one left off.
      5. Reconcile budget records against actual usage since last sync.

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
            now = datetime.now(timezone.utc)
            since = now - timedelta(seconds=interval)

            # ── Step 1: find active api_key_hashes within the lookback window ──
            hash_max_id = get_active_key_hashes(session, since=since)
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

                with get_cache().key_lock(key_hash):
                    # Re-read last_stat in case compress updated it while we waited
                    delta = compute_delta(session, key_hash, last_stat, current_max)
                    if delta is None:
                        continue

                    # ── Step 4: ADD incremental values to cumulative counters ──
                    last_remaining_before = ak.last_synced_remaining
                    apply_delta_to_apikey(ak, delta)
                    ak.last_stat_id = current_max
                    updated_count += 1

                    # ── Update cache with new cumulative values ──
                    apply_delta_to_cache(cache, ak.key, ak)

                    # ── Step 5: reconcile budget records ──
                    _reconcile_budget_for_key(session, ak, key_hash, delta)

                    logger.info(
                        f"[usage_sync] key={ak.name}(id={ak.id}) "
                        f"last_stat_id={last_stat}→{current_max} "
                        f"Δreq={delta['request_count']} "
                        f"Δin={delta['input_tokens']} Δout={delta['output_tokens']} "
                        f"Δreason={delta['reasoning_tokens']} "
                        f"Δcost=${delta['total_cost_usd']:.6f} "
                        f"Δimg={delta['total_image_count']} Δvid={delta['total_video_count']} "
                        f"Δaudio={delta['total_audio_seconds']:.2f}s "
                        f"Δweb={delta['total_web_search_requests']} "
                        f"Δcredits={delta['total_credits']:.4f} "
                        f"total_cost=${ak.total_cost_usd:.6f} "
                        f"budget_rem(last_sync)={last_remaining_before}→{ak.last_synced_remaining}"
                    )

            if updated_count > 0:
                session.commit()
                logger.info(f"[usage_sync] Incrementally synced {updated_count} API key(s) usage stats to DB")

    except Exception as exc:
        logger.error(f"[usage_sync] DB sync error: {exc}", exc_info=True)
    finally:
        engine.dispose()


def _reconcile_budget_for_key(session, ak, key_hash: str, delta: dict) -> None:
    """
    Reconcile budget records for a single API key against actual usage.

    - Skips keys with unlimited budget.
    - Normal case (last_synced_remaining is set):
        calculated = last_synced_remaining - delta_cost.
        If DB remaining > calculated + $0.01, deduct the discrepancy from
        budget records FIFO.
    - Initial case (last_synced_remaining is None, e.g. first sync or after
      unlimited-budget was toggled):
        Full reconciliation using all-time usage since each active budget
        record's creation time.
    """
    if ak.unlimited_budget:
        return

    from app.models import ApiKeyBudget, UsageRecord
    from sqlalchemy import func

    # Get active budget records (remaining > 0), oldest first
    budgets = (
        session.query(ApiKeyBudget)
        .filter(ApiKeyBudget.api_key_id == ak.id, ApiKeyBudget.remaining > 0)
        .order_by(ApiKeyBudget.created_at.asc())
        .all()
    )

    if not budgets:
        return

    db_remaining = sum(float(b.remaining or 0) for b in budgets)
    delta_cost = delta.get('total_cost_usd', 0.0)

    if ak.last_synced_remaining is not None and ak.last_synced_remaining > 0 and db_remaining <= ak.last_synced_remaining:
        # ── Normal incremental case ──
        # Only valid when last_synced_remaining is a meaningful baseline and
        # no budget was added since the last sync (db_remaining <= last_synced_remaining).
        calculated_remaining = ak.last_synced_remaining - delta_cost
        if calculated_remaining < 0:
            calculated_remaining = 0.0

        discrepancy = db_remaining - calculated_remaining
        if discrepancy > 0.01:
            _deduct_budget_records_fifo(budgets, discrepancy)
            logger.info(
                f"[usage_sync] Budget reconciliation: key={ak.id} "
                f"db_remaining={db_remaining:.4f} expected={calculated_remaining:.4f} "
                f"deducted={discrepancy:.4f}"
            )
            # Re-read remaining after deduction
            ak.last_synced_remaining = sum(float(b.remaining or 0) for b in budgets)
        else:
            ak.last_synced_remaining = calculated_remaining
    else:
        # ── Initial / full reconciliation ──
        # Reconcile each budget record: usage since its creation time vs its amount.
        # Walk budgets FIFO: older budgets absorb usage first.
        carry_usage = 0.0
        for budget in budgets:
            since = budget.created_at
            total_cost_since = (
                session.query(func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0))
                .filter(
                    UsageRecord.api_key_hash == key_hash,
                    UsageRecord.created_at >= since,
                )
                .scalar()
            )
            total_cost_since = float(total_cost_since or 0) + carry_usage

            budget_amount = float(budget.amount or 0)
            budget_remaining = float(budget.remaining or 0)

            if total_cost_since >= budget_amount:
                corrected_remaining = 0.0
                carry_usage = total_cost_since - budget_amount
            else:
                corrected_remaining = budget_amount - total_cost_since
                carry_usage = 0.0

            if budget_remaining - corrected_remaining > 0.01:
                logger.info(
                    f"[usage_sync] Budget init reconciliation: key={ak.id} "
                    f"budget_id={budget.id} amount={budget_amount:.4f} "
                    f"db_remaining={budget_remaining:.4f} corrected={corrected_remaining:.4f}"
                )
                budget.remaining = round(corrected_remaining, 6)

        ak.last_synced_remaining = sum(float(b.remaining or 0) for b in budgets)


def _deduct_budget_records_fifo(budgets, amount_usd: float) -> None:
    """Deduct *amount_usd* from budget records FIFO (oldest first), updating remaining in-place."""
    amount_usd = float(amount_usd)
    if amount_usd <= 0:
        return
    for budget in budgets:
        if amount_usd <= 0:
            break
        budget_remaining = float(budget.remaining or 0)
        if budget_remaining >= amount_usd:
            budget.remaining = round(budget_remaining - amount_usd, 6)
            amount_usd = 0
        else:
            amount_usd = round(amount_usd - budget_remaining, 6)
            budget.remaining = 0.0
