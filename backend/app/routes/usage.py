"""
Usage API Routes - Query usage records and aggregated statistics.

Endpoints:
  GET /api/usage/records  - Paginated list of raw usage records with filters
  GET /api/usage/summary  - Aggregated statistics (by time / group / model / api-key)
"""
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from typing import Optional
import os
import logging

from app import db
from app.models import UsageRecord
from jose import JWTError, jwt

usage_bp = Blueprint('usage', __name__)
logger = logging.getLogger("usage")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"


# ── Auth helper (JWT only for admin pages) ───────────────────────────────────

def _require_jwt():
    """
    Validate the Bearer JWT token from the Authorization header.

    Returns the username string on success, or raises ValueError with a
    user-facing error message.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    else:
        token = auth_header

    if not token:
        raise ValueError("Not authenticated")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise ValueError("Invalid token")
        return username
    except JWTError:
        raise ValueError("Invalid token")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO-8601 datetime string; return None if blank."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _granularity_trunc(granularity: str, dt_col):
    """
    Return a SQLAlchemy expression that truncates a datetime column to the
    requested granularity (hour / day / month).

    Falls back to day for unknown values.
    """
    from sqlalchemy import func, text
    from app import db

    db_url = str(db.engine.url)

    if 'sqlite' in db_url:
        # SQLite date/time truncation via strftime
        if granularity == 'hour':
            return func.strftime('%Y-%m-%dT%H:00:00', dt_col)
        elif granularity == 'month':
            return func.strftime('%Y-%m-01T00:00:00', dt_col)
        else:  # day
            return func.strftime('%Y-%m-%dT00:00:00', dt_col)
    else:
        # PostgreSQL / MySQL: use date_trunc / DATE_FORMAT
        if 'postgresql' in db_url:
            trunc_val = {'hour': 'hour', 'day': 'day', 'month': 'month'}.get(granularity, 'day')
            return func.date_trunc(trunc_val, dt_col)
        else:
            # MySQL
            fmt = {'hour': '%Y-%m-%dT%H:00:00', 'day': '%Y-%m-%dT00:00:00', 'month': '%Y-%m-01T00:00:00'}.get(
                granularity, '%Y-%m-%dT00:00:00'
            )
            return func.date_format(dt_col, fmt)


# ── Records endpoint ─────────────────────────────────────────────────────────

@usage_bp.route('/api/usage/records', methods=['GET'])
def list_records():
    """
    Return a paginated list of raw usage records.

    Query parameters:
        page        int   (default 1)
        page_size   int   (default 20, max 200)
        start       ISO datetime  (inclusive)
        end         ISO datetime  (inclusive)
        group_id    int
        api_key_hash  str  (SHA-256 hex, exact match)
        model_name  str   (partial match)
        provider_id int
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    page = max(1, int(request.args.get("page", 1)))
    page_size = min(200, max(1, int(request.args.get("page_size", 20))))

    start = _parse_datetime(request.args.get("start"))
    end = _parse_datetime(request.args.get("end"))
    group_id = request.args.get("group_id")
    api_key_hash = request.args.get("api_key_hash")
    model_name = request.args.get("model_name")
    provider_id = request.args.get("provider_id")

    q = db.session.query(UsageRecord)

    if start:
        q = q.filter(UsageRecord.created_at >= start)
    if end:
        q = q.filter(UsageRecord.created_at <= end)
    if group_id:
        q = q.filter(UsageRecord.group_id == int(group_id))
    if api_key_hash:
        q = q.filter(UsageRecord.api_key_hash == api_key_hash)
    if model_name:
        q = q.filter(UsageRecord.model_name.ilike(f"%{model_name}%"))
    if provider_id:
        q = q.filter(UsageRecord.provider_id == int(provider_id))

    total = q.count()
    records = (
        q.order_by(UsageRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return jsonify({
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "records": [r.to_dict() for r in records],
    })


# ── Summary endpoint ─────────────────────────────────────────────────────────

@usage_bp.route('/api/usage/summary', methods=['GET'])
def get_summary():
    """
    Return aggregated usage statistics.

    Query parameters (all optional):
        start         ISO datetime
        end           ISO datetime
        group_id      int
        api_key_hash  str
        model_name    str (partial)
        provider_id   int
        granularity   hour | day | month  (default: day)
                      When set, also returns time-series data in 'time_series'.

    Response structure:
    {
        "totals": {
            "requests": N,
            "input_tokens": N,
            "output_tokens": N,
            "cache_creation_tokens": N,
            "cache_tokens": N,
            "reasoning_tokens": N,
            "output_image_number": N,
            "output_video_number": N,
            "output_audio_seconds": N,
            "web_search_requests": N,
            "estimated_cost": N   // rough estimate based on price units
        },
        "by_model": [{"model_name": ..., "requests": ..., "input_tokens": ..., ...}],
        "by_group": [{"group_name": ..., ...}],
        "by_api_key": [{"api_key_name": ..., "api_key_preview": ..., ...}],
        "time_series": [{"period": "2024-01-01T00:00:00", "requests": ..., ...}]
    }
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    start = _parse_datetime(request.args.get("start"))
    end = _parse_datetime(request.args.get("end"))
    group_id = request.args.get("group_id")
    api_key_hash = request.args.get("api_key_hash")
    model_name_filter = request.args.get("model_name")
    provider_id = request.args.get("provider_id")
    granularity = request.args.get("granularity", "day")

    def _apply_filters(q):
        if start:
            q = q.filter(UsageRecord.created_at >= start)
        if end:
            q = q.filter(UsageRecord.created_at <= end)
        if group_id:
            q = q.filter(UsageRecord.group_id == int(group_id))
        if api_key_hash:
            q = q.filter(UsageRecord.api_key_hash == api_key_hash)
        if model_name_filter:
            q = q.filter(UsageRecord.model_name.ilike(f"%{model_name_filter}%"))
        if provider_id:
            q = q.filter(UsageRecord.provider_id == int(provider_id))
        return q

    # ── Cost expression (reusable across queries) ─────────────────────────
    # Estimated cost per record in native currency ($ per 1M tokens for text)
    _cost_expr = (
        UsageRecord.input_tokens * UsageRecord.input_price_unit / 1000000.0
        + UsageRecord.output_tokens * UsageRecord.output_price_unit / 1000000.0
        + UsageRecord.cache_creation_tokens * UsageRecord.cache_creation_price_unit / 1000000.0
        + UsageRecord.cache_tokens * UsageRecord.cache_token_price_unit / 1000000.0
        + UsageRecord.output_image_number * UsageRecord.output_image_price_unit
        + UsageRecord.output_video_number * UsageRecord.output_video_price_unit
        + UsageRecord.output_audio_seconds * UsageRecord.output_audio_price_unit
        + UsageRecord.web_search_requests * UsageRecord.web_search_price_unit
    )

    # ── Totals ────────────────────────────────────────────────────────────
    totals_q = _apply_filters(
        db.session.query(
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.cache_creation_tokens), 0).label("cache_creation_tokens"),
            func.coalesce(func.sum(UsageRecord.cache_tokens), 0).label("cache_tokens"),
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(UsageRecord.output_image_number), 0).label("output_image_number"),
            func.coalesce(func.sum(UsageRecord.output_video_number), 0).label("output_video_number"),
            func.coalesce(func.sum(UsageRecord.output_audio_seconds), 0).label("output_audio_seconds"),
            func.coalesce(func.sum(UsageRecord.web_search_requests), 0).label("web_search_requests"),
            func.coalesce(func.sum(_cost_expr), 0).label("estimated_cost"),
        )
    )
    row = totals_q.one()
    totals = {
        "requests": row.requests or 0,
        "input_tokens": int(row.input_tokens or 0),
        "output_tokens": int(row.output_tokens or 0),
        "cache_creation_tokens": int(row.cache_creation_tokens or 0),
        "cache_tokens": int(row.cache_tokens or 0),
        "reasoning_tokens": int(row.reasoning_tokens or 0),
        "output_image_number": int(row.output_image_number or 0),
        "output_video_number": int(row.output_video_number or 0),
        "output_audio_seconds": float(row.output_audio_seconds or 0),
        "web_search_requests": int(row.web_search_requests or 0),
        "estimated_cost": round(float(row.estimated_cost or 0), 6),
    }

    # ── By model ──────────────────────────────────────────────────────────
    by_model_rows = _apply_filters(
        db.session.query(
            UsageRecord.model_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(_cost_expr), 0).label("estimated_cost"),
        )
    ).group_by(UsageRecord.model_name).order_by(func.count(UsageRecord.id).desc()).limit(20).all()

    by_model = [
        {
            "model_name": r.model_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "reasoning_tokens": int(r.reasoning_tokens),
            "estimated_cost": round(float(r.estimated_cost or 0), 6),
        }
        for r in by_model_rows
    ]

    # ── By group ──────────────────────────────────────────────────────────
    by_group_rows = _apply_filters(
        db.session.query(
            UsageRecord.group_id,
            UsageRecord.group_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
        )
    ).group_by(UsageRecord.group_id, UsageRecord.group_name).order_by(
        func.count(UsageRecord.id).desc()
    ).limit(20).all()

    by_group = [
        {
            "group_id": r.group_id,
            "group_name": r.group_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
        }
        for r in by_group_rows
    ]

    # ── By API key ────────────────────────────────────────────────────────
    by_api_key_rows = _apply_filters(
        db.session.query(
            UsageRecord.api_key_hash,
            UsageRecord.api_key_preview,
            UsageRecord.api_key_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(_cost_expr), 0).label("estimated_cost"),
        )
    ).group_by(
        UsageRecord.api_key_hash, UsageRecord.api_key_preview, UsageRecord.api_key_name
    ).order_by(func.count(UsageRecord.id).desc()).limit(20).all()

    by_api_key = [
        {
            "api_key_hash": r.api_key_hash,
            "api_key_preview": r.api_key_preview,
            "api_key_name": r.api_key_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "estimated_cost": round(float(r.estimated_cost or 0), 6),
        }
        for r in by_api_key_rows
    ]

    # ── Time series ───────────────────────────────────────────────────────
    period_col = _granularity_trunc(granularity, UsageRecord.created_at)
    time_series_rows = _apply_filters(
        db.session.query(
            period_col.label("period"),
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
        )
    ).group_by("period").order_by("period").all()

    time_series = [
        {
            "period": str(r.period),
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
        }
        for r in time_series_rows
    ]

    return jsonify({
        "totals": totals,
        "by_model": by_model,
        "by_group": by_group,
        "by_api_key": by_api_key,
        "time_series": time_series,
    })
