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


def _convert_cost_to_usd(rows_with_currency_and_cost, exchange_rate):
    """
    Convert a list of (currency, native_cost, cny_cost) tuples to USD.
    Returns total USD amount.
    """
    total_usd = 0.0
    for currency, native, cny in rows_with_currency_and_cost:
        currency = (currency or 'USD').upper()
        if currency == 'USD':
            total_usd += native
        elif currency == 'CNY':
            total_usd += cny / exchange_rate if exchange_rate > 0 else native / 7.0
        else:
            total_usd += cny / exchange_rate if exchange_rate > 0 else 0.0
    return total_usd


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


# ── Summary helpers ──────────────────────────────────────────────────────────

def _get_summary_filters():
    """Parse common filter parameters from request args."""
    return {
        'start': _parse_datetime(request.args.get("start")),
        'end': _parse_datetime(request.args.get("end")),
        'group_id': request.args.get("group_id"),
        'api_key_hash': request.args.get("api_key_hash"),
        'model_name': request.args.get("model_name"),
        'provider_id': request.args.get("provider_id"),
        'user_name': request.args.get("user_name"),
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
def get_summary_totals():
    """
    Return aggregated totals for the filtered usage records.

    Query parameters (all optional):
        start, end, group_id, api_key_hash, model_name, provider_id
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters()

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
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost"),
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
        "total_cost": round(float(row.total_cost or 0), 6),
    })


@usage_bp.route('/api/usage/summary/by_model', methods=['GET'])
def get_summary_by_model():
    """
    Return usage aggregated by model name (top 20).

    Now includes total_cost_usd which properly converts all currencies to USD.
    total_cost remains as the raw sum of actual_amount (native currency, may mix currencies).
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func
    from app.exchange_rate_service import get_exchange_rate

    filters = _get_summary_filters()

    rows = _apply_filters(
        db.session.query(
            UsageRecord.model_name,
            UsageRecord.currency,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost"),
            func.coalesce(func.sum(UsageRecord.exchange_rate_to_cny * UsageRecord.actual_amount), 0).label("total_cost_cny"),
        ),
        filters,
    ).group_by(UsageRecord.model_name, UsageRecord.currency).order_by(func.sum(UsageRecord.actual_amount).desc()).limit(50).all()

    exchange_rate = get_exchange_rate()

    # Merge rows by model_name (a model may have records in different currencies)
    model_map = {}
    for r in rows:
        name = r.model_name
        if name not in model_map:
            model_map[name] = {
                "model_name": name,
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_cost": 0.0,
                "total_cost_usd": 0.0,
            }
        m = model_map[name]
        m["requests"] += r.requests
        m["input_tokens"] += int(r.input_tokens)
        m["output_tokens"] += int(r.output_tokens)
        m["reasoning_tokens"] += int(r.reasoning_tokens)
        m["total_cost"] += float(r.total_cost or 0)

        # Convert to USD
        currency = (r.currency or 'USD').upper()
        native = float(r.total_cost or 0)
        cny = float(r.total_cost_cny or 0)
        if currency == 'USD':
            m["total_cost_usd"] += native
        elif currency == 'CNY':
            m["total_cost_usd"] += cny / exchange_rate if exchange_rate > 0 else native / 7.0
        else:
            m["total_cost_usd"] += cny / exchange_rate if exchange_rate > 0 else 0.0

    result = sorted(model_map.values(), key=lambda x: x["total_cost_usd"], reverse=True)[:20]
    for item in result:
        item["total_cost"] = round(item["total_cost"], 6)
        item["total_cost_usd"] = round(item["total_cost_usd"], 6)

    return jsonify(result)


@usage_bp.route('/api/usage/summary/by_group', methods=['GET'])
def get_summary_by_group():
    """Return usage aggregated by group (top 20)."""
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters()

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
def get_summary_by_currency():
    """
    Return usage cost aggregated by pricing currency.

    For each currency, returns:
      - total_cost_native: sum of actual_amount in that currency
      - total_cost_usd: converted to USD (CNY amounts ÷ exchange_rate, USD amounts unchanged)
      - total_cost_cny: converted to CNY (USD amounts × exchange_rate, CNY amounts unchanged)

    Also returns the current USD→CNY exchange rate and the total across all currencies in USD.
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func
    from app.exchange_rate_service import get_exchange_rate

    filters = _get_summary_filters()

    rows = _apply_filters(
        db.session.query(
            UsageRecord.currency,
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost_native"),
            func.coalesce(func.sum(UsageRecord.exchange_rate_to_cny * UsageRecord.actual_amount), 0).label("total_cost_cny"),
        ),
        filters,
    ).group_by(UsageRecord.currency).all()

    exchange_rate = get_exchange_rate()

    currency_items = []
    total_usd = 0.0

    for r in rows:
        currency = (r.currency or 'USD').upper()
        native = float(r.total_cost_native or 0)
        cny = float(r.total_cost_cny or 0)

        if currency == 'USD':
            usd = native
        elif currency == 'CNY':
            usd = cny / exchange_rate if exchange_rate > 0 else native / 7.0
        else:
            # For other currencies, assume they're already in CNY via exchange_rate_to_cny
            usd = cny / exchange_rate if exchange_rate > 0 else 0.0

        total_usd += usd
        currency_items.append({
            "currency": currency,
            "total_cost_native": round(native, 6),
            "total_cost_cny": round(cny, 6),
            "total_cost_usd": round(usd, 6),
        })

    return jsonify({
        "exchange_rate_usd_to_cny": exchange_rate,
        "currencies": currency_items,
        "total_cost_usd": round(total_usd, 6),
    })


@usage_bp.route('/api/usage/summary/by_api_key', methods=['GET'])
def get_summary_by_api_key():
    """
    Return usage aggregated by API key (top 20).

    Now includes total_cost_usd which properly converts all currencies to USD.
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func
    from app.exchange_rate_service import get_exchange_rate

    filters = _get_summary_filters()

    rows = _apply_filters(
        db.session.query(
            UsageRecord.api_key_hash,
            UsageRecord.api_key_preview,
            UsageRecord.api_key_name,
            UsageRecord.currency,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost"),
            func.coalesce(func.sum(UsageRecord.exchange_rate_to_cny * UsageRecord.actual_amount), 0).label("total_cost_cny"),
        ),
        filters,
    ).group_by(
        UsageRecord.api_key_hash, UsageRecord.api_key_preview, UsageRecord.api_key_name, UsageRecord.currency
    ).order_by(func.sum(UsageRecord.actual_amount).desc()).limit(50).all()

    exchange_rate = get_exchange_rate()

    # Merge rows by api_key_hash (an api key may have records in different currencies)
    key_map = {}
    for r in rows:
        key = r.api_key_hash
        if key not in key_map:
            key_map[key] = {
                "api_key_hash": r.api_key_hash,
                "api_key_preview": r.api_key_preview,
                "api_key_name": r.api_key_name,
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_cost": 0.0,
                "total_cost_usd": 0.0,
            }
        m = key_map[key]
        m["requests"] += r.requests
        m["input_tokens"] += int(r.input_tokens)
        m["output_tokens"] += int(r.output_tokens)
        m["total_cost"] += float(r.total_cost or 0)

        # Convert to USD
        currency = (r.currency or 'USD').upper()
        native = float(r.total_cost or 0)
        cny = float(r.total_cost_cny or 0)
        if currency == 'USD':
            m["total_cost_usd"] += native
        elif currency == 'CNY':
            m["total_cost_usd"] += cny / exchange_rate if exchange_rate > 0 else native / 7.0
        else:
            m["total_cost_usd"] += cny / exchange_rate if exchange_rate > 0 else 0.0

    result = sorted(key_map.values(), key=lambda x: x["total_cost_usd"], reverse=True)[:20]
    for item in result:
        item["total_cost"] = round(item["total_cost"], 6)
        item["total_cost_usd"] = round(item["total_cost_usd"], 6)

    return jsonify(result)


@usage_bp.route('/api/usage/summary/time_series', methods=['GET'])
def get_summary_time_series():
    """
    Return time-series usage data.

    Additional query parameter:
        granularity   hour | day | month  (default: day)
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters()
    granularity = request.args.get("granularity", "day")

    period_col = _granularity_trunc(granularity, UsageRecord.created_at)
    rows = _apply_filters(
        db.session.query(
            period_col.label("period"),
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost"),
        ),
        filters,
    ).group_by("period").order_by("period").all()

    return jsonify([
        {
            "period": str(r.period),
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "total_cost": round(float(r.total_cost or 0), 6),
        }
        for r in rows
    ])


# ── Legacy combined summary endpoint (kept for backward compatibility) ────────

@usage_bp.route('/api/usage/summary', methods=['GET'])
def get_summary():
    """
    Return aggregated usage statistics (combined endpoint).

    This is the legacy endpoint that runs all 4 queries in a single request.
    For better performance, use the individual endpoints:
      - /api/usage/summary/totals
      - /api/usage/summary/by_model
      - /api/usage/summary/by_group
      - /api/usage/summary/by_api_key
      - /api/usage/summary/time_series
    """
    try:
        _require_jwt()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 401

    from sqlalchemy import func

    filters = _get_summary_filters()
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
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost"),
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
        "total_cost": round(float(row.total_cost or 0), 6),
    }

    # ── By model ──────────────────────────────────────────────────────────
    by_model_rows = _apply_filters(
        db.session.query(
            UsageRecord.model_name,
            func.count(UsageRecord.id).label("requests"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label("reasoning_tokens"),
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost"),
        ),
        filters,
    ).group_by(UsageRecord.model_name).order_by(func.count(UsageRecord.id).desc()).limit(20).all()

    by_model = [
        {
            "model_name": r.model_name,
            "requests": r.requests,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "reasoning_tokens": int(r.reasoning_tokens),
            "total_cost": round(float(r.total_cost or 0), 6),
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
            func.coalesce(func.sum(UsageRecord.actual_amount), 0).label("total_cost"),
        ),
        filters,
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
            "total_cost": round(float(r.total_cost or 0), 6),
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
        ),
        filters,
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