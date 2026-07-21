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

@admin_bp.route("/api/admin/cleanup-files", methods=["POST"])
@_require_admin_secret
async def cleanup_files():
    """
    Delete uploaded files created before a specified time.

    Query params:
        before  str  (required)  Duration before now. Supports:
                                 - "7d"   → 7 days ago
                                 - "12h"  → 12 hours ago
                                 - "3600" or "3600s" → 3600 seconds ago

    For each matching file, deletes the Volcengine ARK asset (seedance-ref type)
    and the database record.
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

    logger.info("[admin] Cleanup-files: deleting files created before %s (retention=%s)", cutoff.isoformat(), raw)

    async with get_db_session() as session:
        from sqlalchemy import select as sa_select, delete as sa_delete

        result = await session.execute(
            sa_select(UploadedFile).where(UploadedFile.created_at < cutoff)
        )
        records = result.scalars().all()

        if not records:
            return jsonify({
                "detail": "No files found before the given time",
                "deleted_count": 0,
                "failed_count": 0,
                "before": cutoff.isoformat(),
            })

        # Split records into volcengine (needs upstream deletion) and others
        volcengine_records = [
            r for r in records
            if r.purpose == "seedance-ref" and r.type == "volcengine" and r.object_key and r.group_id
        ]
        non_volcengine_ids = {r.id for r in records if r not in volcengine_records}

        # Track which DB record IDs can be safely deleted
        deletable_ids: set[int] = set(non_volcengine_ids)
        volcengine_delete_errors = 0

        # Group volcengine/seedance-ref records by group_id for batch deletion
        volcengine_by_group: dict[int, list] = {}
        for rec in volcengine_records:
            volcengine_by_group.setdefault(rec.group_id, []).append(rec)

        for group_id, group_records in volcengine_by_group.items():
            try:
                from app.routes.files import _get_volcengine_credentials, _get_group_project_name
                from app.providers.volcengine.asset import batch_delete_assets

                creds = await _get_volcengine_credentials(session, group_id)
                project_name = await _get_group_project_name(session, group_id)
                asset_ids = [r.object_key for r in group_records]
                result_map = await batch_delete_assets(
                    asset_ids=asset_ids,
                    project_name=project_name,
                    access_key=creds.get("access_key"),
                    secret_key=creds.get("secret_key"),
                    api_key=creds.get("api_key"),
                    region=creds.get("ark_region", "cn-beijing"),
                )

                # Only mark DB records as deletable if the upstream asset was deleted
                for rec in group_records:
                    if result_map.get(rec.object_key, False):
                        deletable_ids.add(rec.id)
                    else:
                        volcengine_delete_errors += 1
                        logger.warning(
                            "[admin] Cleanup-files: skipped DB deletion for %s — upstream DeleteAsset failed",
                            rec.file_id,
                        )

            except Exception as e:
                logger.error(
                    "[admin] Cleanup-files: failed to delete Volcengine assets for group %d: %s",
                    group_id, e,
                )
                volcengine_delete_errors += len(group_records)

        # Delete only DB records whose upstream assets were successfully removed
        if deletable_ids:
            await session.execute(
                sa_delete(UploadedFile).where(UploadedFile.id.in_(list(deletable_ids)))
            )
        await session.commit()

    total_errors = volcengine_delete_errors
    deleted_count = len(deletable_ids)

    logger.info(
        "[admin] Cleanup-files: completed — %d deleted, %d DB records kept due to upstream failures (cutoff=%s)",
        deleted_count, total_errors, cutoff.isoformat(),
    )

    return jsonify({
        "detail": f"Deleted {deleted_count} files, {total_errors} failed (DB records kept)",
        "deleted_count": deleted_count,
        "failed_count": total_errors,
        "before": cutoff.isoformat(),
    })


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