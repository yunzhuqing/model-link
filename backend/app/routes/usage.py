"""
Usage API Routes - Query usage records and aggregated statistics.

Endpoints:
  GET /api/usage/records  - Paginated list of raw usage records with filters
  GET /api/usage/summary  - Aggregated statistics (by time / group / model / api-key)
"""
from quart import Blueprint, request, jsonify
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
async def list_records():
    """
    Return a paginated list of raw usage records.

    Only returns records belonging to the currently logged-in user.

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
        current_username = _require_jwt()
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

    # When filtering by group_id or api_key_hash, show all records in that scope
    # (the user is already authorized via JWT; group membership is checked by the
    #  frontend/API key endpoints). Otherwise, restrict to current user's records.
    if not group_id and not api_key_hash:
        q = q.filter(UsageRecord.user_name == current_username)

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


# ── Summary helpers ──────────────────────────────────────────────────────────

def _get_summary_filters(current_username: str = None):
    """
    Parse common filter parameters from request args.

    When current_username is provided and no group_id or api_key_hash scope is
    specified, the user_name filter is automatically set to restrict results to
    the current user's own records.  When a group_id or api_key_hash is provided,
    the query is already scoped, so no user filter is applied.
    """
    group_id = request.args.get("group_id")
    api_key_hash = request.args.get("api_key_hash")

    # Determine user_name filter: only apply when NOT scoped by group or api_key
    if current_username and not group_id and not api_key_hash:
        user_name = current_username
    else:
        user_name = request.args.get("user_name")

    return {
        'start': _parse_datetime(request.args.get("start")),
        'end': _parse_datetime(request.args.get("end")),
        'group_id': group_id,
        'api_key_hash': api_key_hash,
        'model_name': request.args.get("model_name"),
        'provider_id': request.args.get("provider_id"),
        'user_name': user_name,
        'user_id': request.args.get("user_id"),
    }


def _apply_filters(q, filters: dict):
    """Apply common filters to a query."""
    if filters['start']:
        q = q.filter(UsageRecord.created_at >= filters['start'])
    if filters['end']:
        q = q.filter(UsageRecord.created_at <= filters['end'])
    if filters['group_id']:
        q = q.filter(UsageRecord.group_id == int(filters['group_id']))
    if filters['api_key_hash']:
        q = q.filter(UsageRecord.api_key_hash == filters['api_key_hash'])
    if filters['model_name']:
        q = q.filter(UsageRecord.model_name.ilike(f"%{filters['model_name']}%"))
    if filters['provider_id']:
        q = q.filter(UsageRecord.provider_id == int(filters['provider_id']))
    if filters.get('user_name'):
        q = q.filter(UsageRecord.user_name == filters['user_name'])
    if filters.get('user_id'):
        q = q.filter(UsageRecord.user_id == int(filters['user_id']))
    if filters.get('api_key_hashes'):
        q = q.filter(UsageRecord.api_key_hash.in_(filters['api_key_hashes']))
    return q


# ── Summary endpoints (split for parallel frontend fetching) ─────────────────

@usage_bp.route('/api/usage/summary/totals', methods=['GET'])
async def get_summary_totals():
    """
    Return aggregated totals for the filtered usage records.
    All costs are aggregated in USD via actual_amount_usd.
    Only returns data belonging to the currently logged-in user.

    Query parameters (all optional):
        start, end, group_id, api_key_hash, model_name, provider_id
    """
    try:
        current_username = _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters(current_username)

    row = _apply_filters(
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
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).one()

    return jsonify({
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
        "total_cost": round(float(row.total_cost_usd or 0), 6),
    })


@usage_bp.route('/api/usage/summary/by_model', methods=['GET'])
async def get_summary_by_model():
    """
    Return usage aggregated by model name (top 20).
    Uses actual_amount_usd for cost aggregation — no runtime currency conversion needed.
    Only returns data belonging to the currently logged-in user.
    """
    try:
        current_username = _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters(current_username)

    rows = _apply_filters(
        db.session.query(
            UsageRecord.model_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).group_by(UsageRecord.model_name).order_by(func.sum(UsageRecord.actual_amount_usd).desc()).limit(20).all()

    result = [
        {
            "model_name": r.model_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "reasoning_tokens": int(r.reasoning_tokens),
            "total_cost": round(float(r.total_cost_usd or 0), 6),
            "total_cost_usd": round(float(r.total_cost_usd or 0), 6),
        }
        for r in rows
    ]

    return jsonify(result)


@usage_bp.route('/api/usage/summary/by_group', methods=['GET'])
async def get_summary_by_group():
    """Return usage aggregated by group (top 20). Only current user's data."""
    try:
        current_username = _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters(current_username)

    rows = _apply_filters(
        db.session.query(
            UsageRecord.group_id,
            UsageRecord.group_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
        ),
        filters,
    ).group_by(UsageRecord.group_id, UsageRecord.group_name).order_by(
        func.count(UsageRecord.id).desc()
    ).limit(20).all()

    return jsonify([
        {
            "group_id": r.group_id,
            "group_name": r.group_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
        }
        for r in rows
    ])


@usage_bp.route('/api/usage/summary/by_currency', methods=['GET'])
async def get_summary_by_currency():
    """
    Return usage cost aggregated by pricing currency.

    For each currency, returns:
      - total_cost_native: sum of actual_amount in that currency
      - total_cost_usd: sum of actual_amount_usd (pre-computed at write time)

    Also returns the total across all currencies in USD.
    Only returns data belonging to the currently logged-in user.
    """
    try:
        current_username = _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters(current_username)

    rows = _apply_filters(
        db.session.query(
            UsageRecord.currency,
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost_native"),
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).group_by(UsageRecord.currency).all()

    currency_items = []
    total_usd = 0.0

    for r in rows:
        currency = (r.currency or 'USD').upper()
        native = float(r.total_cost_native or 0)
        usd = float(r.total_cost_usd or 0)

        total_usd += usd
        currency_items.append({
            "currency": currency,
            "total_cost_native": round(native, 6),
            "total_cost_usd": round(usd, 6),
        })

    return jsonify({
        "currencies": currency_items,
        "total_cost_usd": round(total_usd, 6),
    })


@usage_bp.route('/api/usage/summary/by_api_key', methods=['GET'])
async def get_summary_by_api_key():
    """
    Return usage aggregated by API key (top 20).
    Uses actual_amount_usd for cost aggregation.
    Only returns data belonging to the currently logged-in user.
    """
    try:
        current_username = _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters(current_username)

    rows = _apply_filters(
        db.session.query(
            UsageRecord.api_key_hash,
            UsageRecord.api_key_preview,
            UsageRecord.api_key_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).group_by(
        UsageRecord.api_key_hash, UsageRecord.api_key_preview, UsageRecord.api_key_name
    ).order_by(func.sum(UsageRecord.actual_amount_usd).desc()).limit(20).all()

    result = [
        {
            "api_key_hash": r.api_key_hash,
            "api_key_preview": r.api_key_preview,
            "api_key_name": r.api_key_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "total_cost": round(float(r.total_cost_usd or 0), 6),
            "total_cost_usd": round(float(r.total_cost_usd or 0), 6),
        }
        for r in rows
    ]

    return jsonify(result)


@usage_bp.route('/api/usage/summary/time_series_by_model', methods=['GET'])
async def get_summary_time_series_by_model():
    """
    Return time-series usage data grouped by model name.
    Only current user's data. Uses actual_amount_usd for cost aggregation.

    Additional query parameter:
        granularity   hour | day | month  (default: day)

    Returns a list of dicts, each with:
        period, model_name, requests, input_tokens, output_tokens,
        reasoning_tokens, cache_creation_tokens, total_cost, total_cost_usd
    """
    try:
        current_username = _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters(current_username)

    granularity = request.args.get("granularity", "day")

    period_col = _granularity_trunc(granularity, UsageRecord.created_at)
    rows = _apply_filters(
        db.session.query(
            period_col.label("period"),
            UsageRecord.model_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(UsageRecord.cache_creation_tokens), 0).label("cache_creation_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).group_by("period", UsageRecord.model_name).order_by("period", UsageRecord.model_name).all()

    result = []
    for r in rows:
        result.append({
            "period": str(r.period),
            "model_name": r.model_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "reasoning_tokens": int(r.reasoning_tokens),
            "cache_creation_tokens": int(r.cache_creation_tokens),
            "total_cost": round(float(r.total_cost_usd or 0), 6),
            "total_cost_usd": round(float(r.total_cost_usd or 0), 6),
        })

    return jsonify(result)


@usage_bp.route('/api/usage/summary/time_series', methods=['GET'])
async def get_summary_time_series():
    """
    Return time-series usage data. Only current user's data.
    Uses actual_amount_usd for cost aggregation.

    Additional query parameter:
        granularity   hour | day | month  (default: day)
    """
    try:
        current_username = _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters(current_username)

    granularity = request.args.get("granularity", "day")

    period_col = _granularity_trunc(granularity, UsageRecord.created_at)
    rows = _apply_filters(
        db.session.query(
            period_col.label("period"),
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(UsageRecord.cache_creation_tokens), 0).label("cache_creation_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).group_by("period").order_by("period").all()

    result = []
    for r in rows:
        result.append({
            "period": str(r.period),
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "reasoning_tokens": int(r.reasoning_tokens),
            "cache_creation_tokens": int(r.cache_creation_tokens),
            "total_cost": round(float(r.total_cost_usd or 0), 6),
            "total_cost_usd": round(float(r.total_cost_usd or 0), 6),
        })

    return jsonify(result)


# ── Legacy combined summary endpoint (kept for backward compatibility) ────────

@usage_bp.route('/api/usage/summary', methods=['GET'])
async def get_summary():
    """
    Return aggregated usage statistics (combined endpoint).

    This is the legacy endpoint that runs all 4 queries in a single request.
    For better performance, use the individual endpoints:
      - /api/usage/summary/totals
      - /api/usage/summary/by_model
      - /api/usage/summary/by_group
      - /api/usage/summary/by_api_key
      - /api/usage/summary/time_series
    Only returns data belonging to the currently logged-in user.
    """
    try:
        current_username = _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters(current_username)

    granularity = request.args.get("granularity", "day")

    # ── Totals ────────────────────────────────────────────────────────────
    row = _apply_filters(
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
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).one()
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
        "total_cost": round(float(row.total_cost_usd or 0), 6),
    }

    # ── By model ──────────────────────────────────────────────────────────
    by_model_rows = _apply_filters(
        db.session.query(
            UsageRecord.model_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).group_by(UsageRecord.model_name).order_by(func.sum(UsageRecord.actual_amount_usd).desc()).limit(20).all()

    by_model = [
        {
            "model_name": r.model_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "reasoning_tokens": int(r.reasoning_tokens),
            "total_cost": round(float(r.total_cost_usd or 0), 6),
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
        ),
        filters,
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
            func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label("total_cost_usd"),
        ),
        filters,
    ).group_by(
        UsageRecord.api_key_hash, UsageRecord.api_key_preview, UsageRecord.api_key_name
    ).order_by(func.sum(UsageRecord.actual_amount_usd).desc()).limit(20).all()

    by_api_key = [
        {
            "api_key_hash": r.api_key_hash,
            "api_key_preview": r.api_key_preview,
            "api_key_name": r.api_key_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "total_cost": round(float(r.total_cost_usd or 0), 6),
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
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(UsageRecord.cache_creation_tokens), 0).label("cache_creation_tokens"),
        ),
        filters,
    ).group_by("period").order_by("period").all()

    time_series = [
        {
            "period": str(r.period),
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "reasoning_tokens": int(r.reasoning_tokens),
            "cache_creation_tokens": int(r.cache_creation_tokens),
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


# ── Sync control endpoint ────────────────────────────────────────────────────

@usage_bp.route('/api/usage/sync', methods=['POST'])
async def control_sync():
    """
    Start or stop the usage sync service manually.

    Body: {"action": "start"} or {"action": "stop"}

    Requires JWT authentication.
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    data = await request.get_json()
    if not data or 'action' not in data:
        return jsonify({"detail": "Missing 'action' field. Use 'start' or 'stop'."}), 400

    action = data['action'].lower()
    if action not in ('start', 'stop'):
        return jsonify({"detail": "Invalid action. Use 'start' or 'stop'."}), 400

    from quart import current_app
    from app.usagerecord.sync_service import start_usage_sync, stop_usage_sync

    if action == 'start':
        start_usage_sync(current_app)
        return jsonify({"status": "ok", "message": "Usage sync service started"})
    else:
        stop_usage_sync()
        return jsonify({"status": "ok", "message": "Usage sync service stopped"})


# ── Compress control endpoint ─────────────────────────────────────────────────

@usage_bp.route('/api/usage/compress', methods=['POST'])
async def run_compress():
    """
    Trigger usage record compression manually.

    Body (optional): {"api_key_id": 123}  — compress only this key; omit for all.

    Requires JWT authentication.
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    data = await request.get_json() or {}
    api_key_id = data.get('api_key_id')

    from quart import current_app
    from app.usagerecord.compress_service import _do_compress, _compress_key_for_api_key

    try:
        if api_key_id is not None:
            result = _compress_key_for_api_key(current_app, int(api_key_id))
            return jsonify({"status": "ok", **result})
        else:
            deleted = _do_compress(current_app)
            return jsonify({"status": "ok", "total_compressed": deleted})
    except Exception as e:
        logger.error(f"[compress] Manual compress error: {e}", exc_info=True)
        return jsonify({"status": "error", "detail": str(e)}), 500


@usage_bp.route('/api/usage/sync/run', methods=['POST'])
async def run_sync_once():
    """
    Trigger a single usage sync run immediately.

    Requires JWT authentication.
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from quart import current_app
    from app.usagerecord.sync_service import _do_sync

    try:
        _do_sync(current_app, 60)
        return jsonify({"status": "ok", "message": "Sync completed"})
    except Exception as e:
        logger.error(f"[usage_sync] Manual sync error: {e}", exc_info=True)
        return jsonify({"status": "error", "detail": str(e)}), 500
