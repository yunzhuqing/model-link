"""
Admin management routes — on-demand triggers for background services.

All endpoints require an X-Admin-Secret header matching the SECRET_KEY env var.
SECRET_KEY must be explicitly configured (not the default dev value).

Endpoints:
  POST /api/admin/cleanup?retention=24h        — Delete ml_usage_records older than retention
  POST /api/admin/cleanup-files?before=<time>  — Delete uploaded files created before given time
  POST /api/admin/compress                     — Trigger usage record compression
  POST /api/admin/resync                       — Trigger background response resync
"""

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from quart import Blueprint, current_app, request, jsonify
from sqlalchemy import delete

from app import get_db_session
from app.models import UsageRecord, UploadedFile

admin_bp = Blueprint("admin", __name__)
logger = logging.getLogger("admin")

_SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
_DEV_SECRET_KEY = "dev-secret-key-change-in-production"

_RETENTION_PATTERN = re.compile(r"^(\d+)(h|d|s)?$")

_RETENTION_MAP = {
    "h": lambda v: timedelta(hours=v),
    "d": lambda v: timedelta(days=v),
    "s": lambda v: timedelta(seconds=v),
}


def _require_admin_secret(f):
    """Decorator: validate X-Admin-Secret header against SECRET_KEY env var.

    Rejects the request if SECRET_KEY is still the default dev value, since
    that means the admin has not configured a real secret.
    """

    @wraps(f)
    async def wrapper(*args, **kwargs):
        if _SECRET_KEY == _DEV_SECRET_KEY:
            return jsonify({"detail": "SECRET_KEY is not configured. Set a non-default SECRET_KEY to use admin endpoints."}), 500

        secret = request.headers.get("X-Admin-Secret", "")
        if not secret or secret != _SECRET_KEY:
            return jsonify({"detail": "Invalid or missing X-Admin-Secret header"}), 403

        return await f(*args, **kwargs)

    return wrapper


def _parse_retention(value: str) -> timedelta | None:
    m = _RETENTION_PATTERN.match(value.strip())
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2) or "s"  # default to seconds if no suffix
    return _RETENTION_MAP[unit](amount)


# ── Cleanup ────────────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/cleanup", methods=["POST"])
@_require_admin_secret
async def trigger_cleanup():
    """
    Delete ml_usage_records older than the given retention period.

    Query params:
        retention  str  (required) e.g. "12h", "24h", "2d"
    """
    retention_str = request.args.get("retention", "").strip()
    if not retention_str:
        return jsonify({"detail": "retention parameter is required (e.g. 12h, 24h, 2d)"}), 400

    retention = _parse_retention(retention_str)
    if retention is None:
        return jsonify({"detail": f"Invalid retention format: '{retention_str}'. Use like '12h', '24h', '2d'"}), 400

    cutoff = (datetime.now(timezone.utc) - retention).replace(tzinfo=None)

    async with get_db_session() as session:
        result = await session.execute(
            delete(UsageRecord).where(UsageRecord.created_at < cutoff)
        )
        await session.commit()
        deleted_count = result.rowcount

    logger.info("[admin] Cleanup: deleted %d ml_usage_records older than %s (cutoff=%s)",
                deleted_count, retention_str, cutoff.isoformat())

    return jsonify({
        "detail": f"Deleted {deleted_count} records older than {retention_str}",
        "deleted_count": deleted_count,
        "retention": retention_str,
        "cutoff": cutoff.isoformat(),
    })


# ── Compress ───────────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/compress", methods=["POST"])
@_require_admin_secret
async def trigger_compress():
    """
    Trigger a usage-record compression run on demand.

    Optional JSON body:
        api_key_id  int  — compress a single API key; omit to compress all keys with policies
    """
    body = await request.get_json(silent=True) or {}
    api_key_id = body.get("api_key_id")

    try:
        if api_key_id is not None:
            from app.usagerecord.compress_service import _compress_key_for_api_key
            result = await asyncio.to_thread(_compress_key_for_api_key, current_app, int(api_key_id))
        else:
            from app.usagerecord.compress_service import _do_compress
            total = await asyncio.to_thread(_do_compress, current_app)
            result = {"total_deleted": total}

        logger.info("[admin] Compress triggered: %s", result)
        return jsonify({"detail": "Compression completed", "result": result})
    except Exception as exc:
        logger.error("[admin] Compress error: %s", exc, exc_info=True)
        return jsonify({"detail": f"Compression failed: {exc}"}), 500


# ── Cleanup Files ───────────────────────────────────────────────────────────────

# In-memory registry of background cleanup jobs, keyed by job_id.
#
# Each entry is a dict with the public progress fields plus a private "_task"
# holding the asyncio.Task (a strong reference so the task isn't GC'd mid-run).
# Progress is updated per page inside _run_cleanup. The registry lives only on
# the instance that runs the job and is lost on process restart — acceptable
# for an idempotent, per-page-committed maintenance task (just call again).
_cleanup_jobs: dict[str, dict] = {}


def _cleanup_job_view(state: dict) -> dict:
    """Return the public view of a cleanup job's state (strips private keys)."""
    return {k: v for k, v in state.items() if not k.startswith("_")}


async def _run_cleanup(job_id: str, cutoff: datetime, limit: int) -> None:
    """
    Background coroutine that performs the actual file cleanup.

    Walks UploadedFile rows created before ``cutoff`` in keyset pages
    (id > last_id), deletes the Volcengine ARK asset for seedance-ref rows,
    then deletes the DB record. Per-page commits make progress durable and
    keep memory bounded. Updates ``_cleanup_jobs[job_id]`` as it goes.
    """
    page_size = 500
    state = _cleanup_jobs[job_id]
    state["status"] = "in_progress"
    state["started_at"] = datetime.utcnow().isoformat()

    deleted_count = 0
    failed_count = 0
    processed_count = 0
    last_id = 0
    has_more = False

    logger.info(
        "[admin] Cleanup-files %s: started (cutoff=%s, limit=%s, page_size=%d)",
        job_id, cutoff.isoformat(), limit or "unlimited", page_size,
    )

    try:
        while True:
            # Respect the per-call limit if set; stop and report whether more
            # rows remain so the caller can page through large backlogs.
            if limit:
                remaining = limit - processed_count
                if remaining <= 0:
                    async with get_db_session() as s:
                        from sqlalchemy import select as sa_select
                        more = await s.execute(
                            sa_select(UploadedFile.id)
                            .where(UploadedFile.created_at < cutoff, UploadedFile.id > last_id)
                            .limit(1)
                        )
                        has_more = more.first() is not None
                    break
                fetch_size = min(page_size, remaining)
            else:
                fetch_size = page_size

            # Fetch one page with a short-lived session, then release it
            # before any upstream call (per the "no DB connection across
            # upstream call" guideline).
            async with get_db_session() as session:
                from sqlalchemy import select as sa_select
                result = await session.execute(
                    sa_select(UploadedFile)
                    .where(UploadedFile.created_at < cutoff, UploadedFile.id > last_id)
                    .order_by(UploadedFile.id)
                    .limit(fetch_size)
                )
                page = result.scalars().all()

            if not page:
                has_more = False
                break

            logger.info(
                "[admin] Cleanup-files %s: page fetched — %d records (after_id=%d, processed=%d)",
                job_id, len(page), last_id, processed_count,
            )

            # Split this page into volcengine (needs upstream deletion) and others.
            volcengine_records = [
                r for r in page
                if r.purpose == "seedance-ref" and r.type == "volcengine" and r.object_key and r.group_id
            ]
            volcengine_ids = {r.id for r in volcengine_records}
            deletable_ids: set[int] = {r.id for r in page if r.id not in volcengine_ids}
            page_errors = 0

            # Group this page's volcengine records by group_id.
            by_group: dict[int, list] = {}
            for rec in volcengine_records:
                by_group.setdefault(rec.group_id, []).append(rec)

            # Resolve credentials for every group in this page (short DB
            # session), then close it before the upstream calls.
            group_creds: dict[int, tuple] = {}
            if by_group:
                async with get_db_session() as s:
                    from app.routes.files import (
                        _get_volcengine_credentials, _get_group_project_name,
                    )
                    for gid in by_group:
                        group_creds[gid] = (
                            await _get_volcengine_credentials(s, gid),
                            await _get_group_project_name(s, gid),
                        )

            # Delete upstream assets group by group (no DB session held here).
            for gid, grecs in by_group.items():
                creds, project_name = group_creds[gid]
                asset_ids = [r.object_key for r in grecs]
                try:
                    from app.providers.volcengine.asset import batch_delete_assets
                    result_map = await batch_delete_assets(
                        asset_ids=asset_ids,
                        project_name=project_name,
                        access_key=creds.get("access_key"),
                        secret_key=creds.get("secret_key"),
                        api_key=creds.get("api_key"),
                        region=creds.get("ark_region", "cn-beijing"),
                    )
                    ok = 0
                    for rec in grecs:
                        if result_map.get(rec.object_key, False):
                            deletable_ids.add(rec.id)
                            ok += 1
                        else:
                            page_errors += 1
                            logger.warning(
                                "[admin] Cleanup-files %s: skipped DB deletion for %s — upstream DeleteAsset failed",
                                job_id, rec.file_id,
                            )
                    logger.info(
                        "[admin] Cleanup-files %s: group_id=%d — %d/%d assets deleted",
                        job_id, gid, ok, len(grecs),
                    )
                except Exception as e:
                    logger.error(
                        "[admin] Cleanup-files %s: group_id=%d errored: %s",
                        job_id, gid, e,
                    )
                    page_errors += len(grecs)

            # Commit this page's deletable DB records (short session).
            if deletable_ids:
                async with get_db_session() as session:
                    from sqlalchemy import delete as sa_delete
                    await session.execute(
                        sa_delete(UploadedFile).where(UploadedFile.id.in_(list(deletable_ids)))
                    )
                    await session.commit()

            deleted_count += len(deletable_ids)
            failed_count += page_errors
            processed_count += len(page)
            last_id = page[-1].id

            # Publish live progress so callers polling the status endpoint
            # see the run advance page by page.
            state.update(
                deleted_count=deleted_count,
                failed_count=failed_count,
                processed_count=processed_count,
                last_id=last_id,
                has_more=has_more,
            )

            logger.info(
                "[admin] Cleanup-files %s: page done — deleted=%d failed=%d (processed=%d, last_id=%d)",
                job_id, len(deletable_ids), page_errors, processed_count, last_id,
            )

        state.update(
            status="completed",
            deleted_count=deleted_count,
            failed_count=failed_count,
            processed_count=processed_count,
            last_id=last_id,
            has_more=has_more,
            completed_at=datetime.utcnow().isoformat(),
        )
        logger.info(
            "[admin] Cleanup-files %s: completed — deleted=%d failed=%d processed=%d has_more=%s (cutoff=%s)",
            job_id, deleted_count, failed_count, processed_count, has_more, cutoff.isoformat(),
        )

    except Exception as e:
        logger.exception("[admin] Cleanup-files %s: failed", job_id)
        state.update(
            status="failed",
            error=str(e),
            deleted_count=deleted_count,
            failed_count=failed_count,
            processed_count=processed_count,
            last_id=last_id,
            completed_at=datetime.utcnow().isoformat(),
        )
    finally:
        # Drop the strong task reference so the Task object can be collected
        # once complete; the progress fields remain for status polling.
        state.pop("_task", None)


@admin_bp.route("/api/admin/cleanup-files", methods=["POST"])
@_require_admin_secret
async def cleanup_files():
    """
    Start a background cleanup that deletes uploaded files created before a
    specified time. Returns immediately with a job_id; the cleanup runs as a
    background asyncio task on the same event loop and does not block the
    HTTP response. Poll GET /api/admin/cleanup-files/jobs/<job_id> for progress.

    Query params:
        before  str  (required)  Duration before now. Supports:
                                 - "7d"   → 7 days ago
                                 - "12h"  → 12 hours ago
                                 - "3600" or "3600s" → 3600 seconds ago
        limit   int  (optional)  Max records to process per call (0 = all).
                                 When set and the backlog exceeds it, the
                                 job's final state carries has_more=true;
                                 start another job to continue.

    For each matching file, deletes the Volcengine ARK asset (seedance-ref
    type) and the database record. Processing is keyset-paginated internally
    (500 rows/page) with a per-page commit, so a large backlog won't exhaust
    memory and progress survives interruption.
    """
    raw = request.args.get("before", "").strip()
    if not raw:
        return jsonify({"detail": "before parameter is required (e.g. 7d, 12h, 3600, 3600s)"}), 400

    retention = _parse_retention(raw)
    if retention is None:
        return jsonify({
            "detail": f"Invalid before format: '{raw}'. Use like '7d', '12h', '3600', '3600s'."
        }), 400

    cutoff = (datetime.now(timezone.utc) - retention).replace(tzinfo=None)

    try:
        limit = max(0, int(request.args.get("limit", "0")))
    except (TypeError, ValueError):
        return jsonify({"detail": "limit must be a non-negative integer"}), 400

    job_id = f"cleanup_{uuid.uuid4().hex[:12]}"
    _cleanup_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "before": cutoff.isoformat(),
        "limit": limit,
        "deleted_count": 0,
        "failed_count": 0,
        "processed_count": 0,
        "last_id": 0,
        "has_more": False,
        "started_at": None,
        "completed_at": None,
        "error": None,
    }

    # Strong reference to the task lives in the registry so it isn't GC'd.
    task = asyncio.create_task(_run_cleanup(job_id, cutoff, limit))
    _cleanup_jobs[job_id]["_task"] = task

    logger.info(
        "[admin] Cleanup-files %s: enqueued (cutoff=%s, limit=%s)",
        job_id, cutoff.isoformat(), limit or "unlimited",
    )
    return jsonify({
        "detail": "Cleanup started in background",
        "job_id": job_id,
        "status": "queued",
        "before": cutoff.isoformat(),
    }), 202


@admin_bp.route("/api/admin/cleanup-files/jobs/<job_id>", methods=["GET"])
@_require_admin_secret
async def cleanup_job_status(job_id: str):
    """Return the current progress of a background cleanup job."""
    state = _cleanup_jobs.get(job_id)
    if state is None:
        return jsonify({"detail": f"Unknown cleanup job: {job_id}"}), 404
    return jsonify(_cleanup_job_view(state))


@admin_bp.route("/api/admin/cleanup-files/jobs", methods=["GET"])
@_require_admin_secret
async def cleanup_jobs_list():
    """List all known background cleanup jobs (most recent first)."""
    jobs = [_cleanup_job_view(s) for s in _cleanup_jobs.values()]
    # Newest job_ids last; show latest first.
    jobs.reverse()
    return jsonify({"jobs": jobs, "count": len(jobs)})


# ── Resync ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/resync", methods=["POST"])
@_require_admin_secret
async def trigger_resync():
    """
    Trigger a background-response resync scan on demand.

    Optional JSON body:
        min_age_minutes  int  — minimum age of in-progress records to check (default 10)
    """
    body = await request.get_json(silent=True) or {}
    min_age_minutes = max(1, int(body.get("min_age_minutes", 10)))

    try:
        from app.usagerecord.background_resync_service import _do_resync
        await _do_resync(current_app, min_age_minutes=min_age_minutes)

        logger.info("[admin] Resync triggered (min_age_minutes=%d)", min_age_minutes)
        return jsonify({"detail": "Resync scan completed", "min_age_minutes": min_age_minutes})
    except Exception as exc:
        logger.error("[admin] Resync error: %s", exc, exc_info=True)
        return jsonify({"detail": f"Resync failed: {exc}"}), 500