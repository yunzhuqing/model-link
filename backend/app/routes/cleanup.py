"""
Cleanup routes — delete old usage records based on retention period.

Endpoint:
  DELETE /api/cleanup/ml-usage-records?retention=24h
"""

import re
import logging
from datetime import datetime, timedelta, timezone

from quart import Blueprint, request, jsonify
from sqlalchemy import select, delete, func as sa_func

from app import get_db_session
from app.models import UsageRecord, UserGroup
from app.routes.users import token_required

cleanup_bp = Blueprint("cleanup", __name__)
logger = logging.getLogger("cleanup")

_RETENTION_PATTERN = re.compile(r"^(\d+)(h|d)$")

_RETENTION_MAP = {
    "h": lambda v: timedelta(hours=v),
    "d": lambda v: timedelta(days=v),
}


def _parse_retention(value: str) -> timedelta | None:
    m = _RETENTION_PATTERN.match(value.strip())
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2)
    return _RETENTION_MAP[unit](amount)


async def _is_root_in_any_group(user_id: int) -> bool:
    async with get_db_session() as session:
        result = await session.execute(
            select(sa_func.count()).select_from(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.role == "root",
            )
        )
        return result.scalar() > 0


@cleanup_bp.route("/api/cleanup/ml-usage-records", methods=["DELETE"])
@token_required
async def cleanup_ml_usage_records(current_user):
    """
    Delete ml_usage_records older than the given retention period.

    Query parameters:
        retention   str  (required) e.g. "12h", "24h", "2d"

    Only root users can perform this operation.
    """
    if not await _is_root_in_any_group(current_user.id):
        return jsonify({"detail": "Only root members can perform cleanup operations"}), 403

    retention_str = request.args.get("retention", "").strip()
    if not retention_str:
        return jsonify({"detail": "retention parameter is required (e.g. 12h, 24h, 2d)"}), 400

    retention = _parse_retention(retention_str)
    if retention is None:
        return jsonify({"detail": f"Invalid retention format: '{retention_str}'. Use like '12h', '24h', '2d'"}), 400

    cutoff = datetime.now(timezone.utc) - retention

    async with get_db_session() as session:
        result = await session.execute(
            delete(UsageRecord).where(UsageRecord.created_at < cutoff)
        )
        await session.commit()
        deleted_count = result.rowcount

    logger.info("Cleanup completed: deleted %d ml_usage_records older than %s (cutoff=%s)",
                deleted_count, retention_str, cutoff.isoformat())

    return jsonify({
        "detail": f"Deleted {deleted_count} records older than {retention_str}",
        "deleted_count": deleted_count,
        "retention": retention_str,
        "cutoff": cutoff.isoformat(),
    })