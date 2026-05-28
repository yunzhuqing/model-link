"""
Background Response Resync Service — Leader-node periodic scan.

Scans ml_background_responses for stale in_progress records,
queries upstream provider task status, and syncs completed/failed results to DB.

Implementation note:
  The resync loop runs as an asyncio task on the main event loop (where the
  shared async SQLAlchemy engine lives). Because the election service fires
  on_leader / on_lost_leader callbacks from its own daemon thread, this
  module schedules the coroutine onto the main loop via
  ``asyncio.run_coroutine_threadsafe``. Provider SDKs that are sync-only
  are isolated with ``asyncio.to_thread`` inside ``task_status_checker``.

Configuration (environment variables):
  BG_RESYNC_INTERVAL = 600  (seconds between scan runs, default: 600 = 10 minutes)
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("bg_resync")

_lock = threading.Lock()
_resync_future: Optional[concurrent.futures.Future] = None
_stop_event: Optional[asyncio.Event] = None


def start_background_resync(app) -> None:
    """
    Launch the periodic background-resync task on the main event loop.

    Safe to call from the election service's daemon thread — the coroutine
    is scheduled onto the main loop with ``run_coroutine_threadsafe``.
    """
    from app import get_main_event_loop

    global _resync_future, _stop_event

    with _lock:
        if _resync_future is not None and not _resync_future.done():
            return

        loop = get_main_event_loop()
        if loop is None or not loop.is_running():
            logger.error("[bg_resync] Cannot start: main event loop is not available yet.")
            return

        interval = float(os.getenv("BG_RESYNC_INTERVAL", "600"))
        logger.info(f"[bg_resync] Starting background resync task (interval={interval}s)")

        # Create the stop event on the main loop so set()/wait() share that loop.
        async def _make_event() -> asyncio.Event:
            return asyncio.Event()

        _stop_event = asyncio.run_coroutine_threadsafe(_make_event(), loop).result(timeout=5)
        _resync_future = asyncio.run_coroutine_threadsafe(_resync_loop(app, interval), loop)


def stop_background_resync() -> None:
    """
    Signal the resync loop to stop.

    Safe to call from the election service's daemon thread.
    """
    from app import get_main_event_loop

    global _resync_future, _stop_event
    logger.info("[bg_resync] Stopping background resync task (leadership lost).")

    loop = get_main_event_loop()
    with _lock:
        ev = _stop_event
        fut = _resync_future

    if ev is not None and loop is not None and loop.is_running():
        loop.call_soon_threadsafe(ev.set)
    if fut is not None and not fut.done():
        fut.cancel()


async def _resync_loop(app, interval: float) -> None:
    """Main resync loop — runs only on the leader node."""
    assert _stop_event is not None

    # Initial delay before first scan
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=min(interval, 15))
        return  # stop requested during initial delay
    except asyncio.TimeoutError:
        pass

    try:
        while not _stop_event.is_set():
            try:
                from app.election_service import is_leader
                if not is_leader():
                    logger.info("[bg_resync] This node is no longer the leader. Stopping resync loop.")
                    break
                await _do_resync(app)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"[bg_resync] Resync error: {exc}", exc_info=True)

            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=interval)
                break  # stop requested
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        logger.info("[bg_resync] Resync loop cancelled.")
    finally:
        logger.info("[bg_resync] Resync loop terminated.")

async def _do_resync(app, min_age_minutes: int = 10) -> None:
    """
    Perform one resync cycle:

    1. Query stale in_progress records (created > min_age_minutes ago)
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
        resolve_and_check_task_status_async,
        TaskStatus,
    )

    stale_records = await _bg_dao.find_stale_in_progress_records_async(min_age_minutes=min_age_minutes)
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
            await _bg_dao.mark_failed_async(
                record["response_id"],
                f"Record stuck in_progress for {age_minutes:.0f}m (>{48 * 60}m limit)",
            )
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
            await _bg_dao.mark_failed_async(
                record["response_id"],
                "No task_id recorded — provider may have crashed before persisting task metadata",
            )
            logger.warning(
                f"[bg_resync] Record {record['response_id']!r} (model={model}) "
                f"has no task_id after {age_minutes:.1f}m, marked as failed"
            )
            resolved_count += 1
            continue

        response_id = record["response_id"]
        provider_id = record.get("provider_id")
        if not provider_id:
            await _bg_dao.mark_failed_async(
                response_id,
                "No provider_id recorded — model resolution may have failed",
            )
            logger.warning(
                f"[bg_resync] Record {response_id!r} has no provider_id after {age_minutes:.1f}m, marked as failed"
            )
            resolved_count += 1
            continue

        logger.info(
            f"[bg_resync] Checking stale record {response_id!r} "
            f"model={model} category={category.value} age={age_minutes:.1f}m"
        )

        status = await resolve_and_check_task_status_async(record)

        if status == TaskStatus.RUNNING:
            continue

        if status == TaskStatus.COMPLETED:
            await _bg_dao.mark_completed_async(response_id)
            logger.info(f"[bg_resync] Record {response_id!r} synced to completed")
            resolved_count += 1
        elif status == TaskStatus.FAILED:
            await _bg_dao.mark_failed_async(response_id, "Task failed at upstream provider")
            logger.info(f"[bg_resync] Record {response_id!r} synced to failed")
            resolved_count += 1
        else:
            # UNKNOWN — skip, try again next cycle
            pass

        # Small delay between provider API calls to avoid rate limiting
        await asyncio.sleep(0.5)

    if resolved_count > 0 or skip_count > 0:
        logger.info(
            f"[bg_resync] Cycle complete: {resolved_count} resolved, "
            f"{skip_count} skipped (non-media or text)"
        )
