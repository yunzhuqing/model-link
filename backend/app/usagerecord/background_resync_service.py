"""
Background Response Resync Service — Leader-node periodic scan.

Scans ml_background_responses for stale in_progress records,
queries upstream provider task status, and syncs completed/failed results to DB.

Configuration (environment variables):
  BG_RESYNC_INTERVAL = 600  (seconds between scan runs, default: 600 = 10 minutes)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger("bg_resync")

_stop_event = threading.Event()
_resync_thread = None
_resync_lock = threading.Lock()


def start_background_resync(app) -> None:
    """
    Start the periodic background-resync daemon thread.

    Called by the election service's on_leader callback when this node
    becomes the leader.
    """
    global _resync_thread
    with _resync_lock:
        if _resync_thread is not None and _resync_thread.is_alive():
            return
        _stop_event.clear()

    interval = float(os.getenv("BG_RESYNC_INTERVAL", "600"))
    logger.info(f"[bg_resync] Starting background resync service (interval={interval}s)")

    _resync_thread = threading.Thread(
        target=_resync_loop,
        args=(app, interval),
        daemon=True,
        name="bg-resync",
    )
    _resync_thread.start()


def stop_background_resync() -> None:
    """
    Signal the resync loop to stop.

    Called by the election service's on_lost_leader callback.
    """
    logger.info("[bg_resync] Stopping background resync service (leadership lost).")
    _stop_event.set()


def _resync_loop(app, interval: float) -> None:
    """Main resync loop — runs only on the leader node."""
    _stop_event.wait(timeout=min(interval, 15))

    while not _stop_event.is_set():
        try:
            from app.election_service import is_leader
            if not is_leader():
                logger.info("[bg_resync] This node is no longer the leader. Stopping resync loop.")
                break
            _do_resync(app)
        except Exception as exc:
            logger.error(f"[bg_resync] Resync error: {exc}", exc_info=True)

        _stop_event.wait(timeout=interval)

    logger.info("[bg_resync] Resync loop terminated.")


def _do_resync(app) -> None:
    """
    Perform one resync cycle:

    1. Query stale in_progress records (created > 10 min ago)
    2. For each record, classify model and check age threshold
    3. Query provider task status if threshold met
    4. Update DB if status is terminal
    """
    import app.background_response_dao as _bg_dao
    from app.usagerecord.model_classifier import (
        classify_model,
        CATEGORY_MIN_AGE_MINUTES,
        ModelCategory,
    )
    from app.usagerecord.task_status_checker import (
        resolve_and_check_task_status,
        TaskStatus,
    )

    db_url = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not db_url:
        return

    stale_records = _bg_dao.find_stale_in_progress_records(db_url, min_age_minutes=10)
    if not stale_records:
        return

    now = datetime.now(timezone.utc)
    resolved_count = 0
    skip_count = 0

    for record in stale_records:
        model = record.get("model", "")
        category = classify_model(model)

        if category == ModelCategory.TEXT:
            # Text models shouldn't be stuck; skip
            skip_count += 1
            continue

        min_age = CATEGORY_MIN_AGE_MINUTES.get(category, 9999)
        if min_age >= 9999:
            skip_count += 1
            continue

        created_at = record.get("created_at")
        if created_at is None:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_minutes = (now - created_at).total_seconds() / 60.0

        # Hard cutoff: records stuck for > 48 hours are unrecoverable
        if age_minutes > 48 * 60:
            _bg_dao.mark_failed(db_url, record["response_id"], f"Record stuck in_progress for {age_minutes:.0f}m (>{48 * 60}m limit)")
            logger.warning(
                f"[bg_resync] Record {record['response_id']!r} (model={model}) "
                f"has been stuck for {age_minutes:.1f}m, marked as failed (48h limit)"
            )
            resolved_count += 1
            continue

        if age_minutes < min_age:
            continue

        task_id = record.get("task_id")
        if not task_id:
            _bg_dao.mark_failed(db_url, record["response_id"], "No task_id recorded — provider may have crashed before persisting task metadata")
            logger.warning(
                f"[bg_resync] Record {record['response_id']!r} (model={model}) "
                f"has no task_id after {age_minutes:.1f}m, marked as failed"
            )
            resolved_count += 1
            continue

        response_id = record["response_id"]
        provider_id = record.get("provider_id")
        if not provider_id:
            _bg_dao.mark_failed(db_url, response_id, "No provider_id recorded — model resolution may have failed")
            logger.warning(
                f"[bg_resync] Record {response_id!r} has no provider_id after {age_minutes:.1f}m, marked as failed"
            )
            resolved_count += 1
            continue

        logger.info(
            f"[bg_resync] Checking stale record {response_id!r} "
            f"model={model} category={category.value} age={age_minutes:.1f}m"
        )

        status = resolve_and_check_task_status(db_url, record)

        if status == TaskStatus.RUNNING:
            continue

        if status == TaskStatus.COMPLETED:
            _bg_dao.mark_completed(db_url, response_id)
            logger.info(f"[bg_resync] Record {response_id!r} synced to completed")
            resolved_count += 1
        elif status == TaskStatus.FAILED:
            _bg_dao.mark_failed(db_url, response_id, "Task failed at upstream provider")
            logger.info(f"[bg_resync] Record {response_id!r} synced to failed")
            resolved_count += 1
        else:
            # UNKNOWN — skip, try again next cycle
            pass

        # Small delay between provider API calls to avoid rate limiting
        time.sleep(0.5)

    if resolved_count > 0 or skip_count > 0:
        logger.info(
            f"[bg_resync] Cycle complete: {resolved_count} resolved, "
            f"{skip_count} skipped (non-media or text)"
        )