"""Metabase stats backend.

When ``STATS_DATA_SOURCE=metabase`` (see ``app.__init__``), the summary stat
endpoints in ``routes/usage.py`` delegate to this module instead of running
SQLAlchemy aggregations against the local ``UsageRecord`` table. Each
``fetch_*`` method builds an MBQL query against the configured source card,
POSTs it to ``/api/dataset``, and maps the rows into the **exact same response
shape** the DB path produces — so endpoints and frontend are unchanged.

MBQL bodies mirror the working ``/api/dataset`` curls (new ``lib/type:
mbql/query`` format). Field references carry a stable ``lib/uuid`` (env-driven,
identifies a card column); clause-level ``lib/uuid`` values are generated per
request (the Metabase query processor treats them as tracking identifiers).

Coverage notes (card schema vs. endpoint fields):
  - ``requests``        → Metabase ``count`` aggregation (row count)
  - ``api_key_preview`` → derived from ``apikeyhash`` (column not on card)
  - ``group_name``       → not on card; ``/by_group`` stays on DB
  - native currency amt  → not on card (only USD ``actualamountusd``); ``/by_currency``
                           stays on DB
  - ``granularity``      → card ``ds`` is per-day; only ``day`` is served here,
                           ``hour``/``month`` fall back to DB
"""
import os
import uuid
import json
import logging
from typing import Optional

import httpx
from quart import current_app

logger = logging.getLogger("stats.metabase")


# ── Card column metadata ─────────────────────────────────────────────────────
# (effective-type, base-type). Fixed properties of the card schema, not
# env-driven. New columns added later go here.
_FIELD_TYPES = {
    "ds": ("type/Text", "type/Text"),
    "actualamountusd": ("type/Float", "type/Float"),
    "apikeyname": ("type/Text", "type/Text"),
    "apikeyhash": ("type/Text", "type/Text"),
    "groupid": ("type/BigInteger", "type/BigInteger"),
    "username": ("type/Text", "type/Text"),
    "modelname": ("type/Text", "type/Text"),
    "inputtokens": ("type/BigInteger", "type/BigInteger"),
    "outputtokens": ("type/BigInteger", "type/BigInteger"),
    "reasoningtokens": ("type/BigInteger", "type/BigInteger"),
    "cachedtokens": ("type/BigInteger", "type/BigInteger"),
    "cachecreationtokens": ("type/BigInteger", "type/BigInteger"),
    "currency": ("type/Text", "type/Text"),
    "outputimagenumber": ("type/BigInteger", "type/BigInteger"),
    "outputvideonumber": ("type/BigInteger", "type/BigInteger"),
    "outputaudioseconds": ("type/BigInteger", "type/BigInteger"),
    "websearchrequests": ("type/BigInteger", "type/BigInteger"),
    "ds_time": ("type/Date", "type/Date"),
}


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)


def _clause_uuid() -> dict:
    """A freshly-generated ``lib/uuid`` for a query clause (filter/aggregation)."""
    return {"lib/uuid": str(uuid.uuid4())}


def _field_ref(name: str) -> list:
    """``["field", {"lib/uuid": <stable field uuid>, types}, <name>]``."""
    if name not in _FIELD_TYPES:
        raise ValueError(f"Unknown Metabase field: {name!r}")
    eff, base = _FIELD_TYPES[name]
    field_uuid = _env(f"METABASE_FIELD_{name.upper()}_UUID")
    if not field_uuid:
        raise RuntimeError(
            f"Metabase field UUID for {name!r} is not configured "
            f"(METABASE_FIELD_{name.upper()}_UUID)"
        )
    return ["field", {"lib/uuid": field_uuid, "effective-type": eff, "base-type": base}, name]


# ── Clause builders ───────────────────────────────────────────────────────────

def _agg_count() -> list:
    return ["count", _clause_uuid()]


def _agg_sum(field_name: str) -> list:
    return ["sum", _clause_uuid(), _field_ref(field_name)]


def _eq(field_name: str, value) -> list:
    """Equality filter (used for groupid / apikeyhash / username — exact match,
    matching the DB path's ``==`` semantics)."""
    return ["=", _clause_uuid(), _field_ref(field_name), value]


def _date_str(dt) -> Optional[str]:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d")


def _filter_clauses(filters: dict) -> list:
    """Build the dimension + date-range MBQL filter clauses from the filters
    dict produced by ``routes/usage._get_summary_filters``.

    Dimension mapping (mutually exclusive in practice via auto-scoping):
      group_ids → groupid (in/eq), group_id → groupid (eq),
      api_key_hash → apikeyhash (eq), user_name → username (eq).
      Date range filters on the ``ds`` day-string.
    """
    clauses: list = []
    group_ids = filters.get("group_ids") or []
    if len(group_ids) > 1:
        clauses.append(["in", _clause_uuid(), _field_ref("groupid"), [int(g) for g in group_ids]])
    elif len(group_ids) == 1:
        clauses.append(_eq("groupid", int(group_ids[0])))
    elif filters.get("group_id"):
        clauses.append(_eq("groupid", int(filters["group_id"])))
    if filters.get("api_key_hash"):
        clauses.append(_eq("apikeyhash", filters["api_key_hash"]))
    if filters.get("user_name"):
        clauses.append(_eq("username", filters["user_name"]))
    # model_name (ilike) / provider_id / user_id are not supported by the card;
    # the three target pages do not pass them, so they are intentionally ignored.
    start_date = _date_str(filters.get("start"))
    end_date = _date_str(filters.get("end"))
    # Date range uses the ``ds_time`` (type/Date) column with ``between`` — the
    # ``ds`` column is type/Text and does not support comparison operators.
    if start_date and end_date:
        clauses.append(["between", _clause_uuid(), _field_ref("ds_time"), start_date, end_date])
    elif start_date:
        clauses.append([">=", _clause_uuid(), _field_ref("ds_time"), start_date])
    elif end_date:
        clauses.append(["<=", _clause_uuid(), _field_ref("ds_time"), end_date])
    return clauses


def _build_query(breakout: list, aggregations: list, filters: dict) -> dict:
    card_id = _env("METABASE_CARD_ID")
    database_id = _env("METABASE_DATABASE_ID")
    if not card_id or not database_id:
        raise RuntimeError(
            "Metabase card/database id not configured "
            "(METABASE_CARD_ID / METABASE_DATABASE_ID)"
        )
    stage = {
        "lib/type": "mbql.stage/mbql",
        "source-card": int(card_id),
        "aggregation": aggregations,
        "filters": _filter_clauses(filters),
    }
    # Metabase rejects an empty ``breakout: []`` ("should have at least 1
    # elements"); only include the key when there is a real breakout.
    if breakout:
        stage["breakout"] = breakout
    return {
        "lib/type": "mbql/query",
        "stages": [stage],
        "database": int(database_id),
        "parameters": [],
    }


# ── HTTP + row extraction ────────────────────────────────────────────────────

def _rows(payload: dict) -> list[list]:
    data = payload.get("data") or {}
    return data.get("rows") or []


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(v) -> int:
    return int(_num(v))


async def _run(mbql: dict) -> list[list]:
    """POST an MBQL query to Metabase and return the raw rows."""
    base_url = (_env("METABASE_BASE_URL") or "").rstrip("/")
    api_key = _env("METABASE_API_KEY")
    if not base_url or not api_key:
        raise RuntimeError("Metabase not configured (METABASE_BASE_URL / METABASE_API_KEY)")

    from app.http_client import get_shared_client

    client: httpx.AsyncClient = await get_shared_client()
    timeout = float(_env("METABASE_TIMEOUT", "30"))
    resp = await client.post(
        f"{base_url}/api/dataset",
        json=mbql,
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        timeout=timeout,
    )
    if resp.status_code >= 400:
        body = resp.text
        logger.error(
            "Metabase /api/dataset %s\nMBQL: %s\nResponse: %s",
            resp.status_code,
            json.dumps(mbql, ensure_ascii=False)[:3000],
            body[:3000],
        )
        raise RuntimeError(f"Metabase {resp.status_code}: {body[:1000]}")
    return _rows(resp.json())


# ── Switch ────────────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """True when the Metabase backend is the active stats data source."""
    return (current_app.config.get("STATS_DATA_SOURCE", "db") or "db").lower() == "metabase"


# ── Per-endpoint fetchers (build → run → map to DB response shape) ───────────
# Column order in each row follows the query structure: breakout fields first
# (in order), then aggregations (in order).

async def fetch_totals(filters: dict) -> dict:
    mbql = _build_query(
        breakout=[],
        aggregations=[
            _agg_count(),
            _agg_sum("inputtokens"),
            _agg_sum("outputtokens"),
            _agg_sum("reasoningtokens"),
            _agg_sum("cachecreationtokens"),
            _agg_sum("cachedtokens"),
            _agg_sum("outputimagenumber"),
            _agg_sum("outputvideonumber"),
            _agg_sum("outputaudioseconds"),
            _agg_sum("websearchrequests"),
            _agg_sum("actualamountusd"),
        ],
        filters=filters,
    )
    print("mbql:", json.dumps(mbql, ensure_ascii=False))
    rows = await _run(mbql)
    r = rows[0] if rows else [0] * 11
    # [count, in, out, reasoning, cache_creation, cache, image, video, audio, web, amount]
    total_cost = round(_num(r[10]), 6)
    return {
        "requests": _int(r[0]),
        "input_tokens": _int(r[1]),
        "output_tokens": _int(r[2]),
        "reasoning_tokens": _int(r[3]),
        "cache_creation_tokens": _int(r[4]),
        "cache_tokens": _int(r[5]),
        "output_image_number": _int(r[6]),
        "output_video_number": _int(r[7]),
        "output_audio_seconds": _num(r[8]),
        "web_search_requests": _int(r[9]),
        "total_cost": total_cost,
    }


async def fetch_by_model(filters: dict) -> list[dict]:
    mbql = _build_query(
        breakout=[_field_ref("modelname")],
        aggregations=[
            _agg_count(),
            _agg_sum("inputtokens"),
            _agg_sum("outputtokens"),
            _agg_sum("reasoningtokens"),
            _agg_sum("actualamountusd"),
        ],
        filters=filters,
    )
    rows = await _run(mbql)
    # [modelname, count, in, out, reasoning, amount]
    items = [
        {
            "model_name": r[0],
            "requests": _int(r[1]),
            "input_tokens": _int(r[2]),
            "output_tokens": _int(r[3]),
            "reasoning_tokens": _int(r[4]),
            "total_cost": round(_num(r[5]), 6),
            "total_cost_usd": round(_num(r[5]), 6),
        }
        for r in rows
    ]
    items.sort(key=lambda x: x["total_cost_usd"], reverse=True)
    return items[:20]


async def fetch_by_api_key(filters: dict) -> list[dict]:
    mbql = _build_query(
        breakout=[_field_ref("apikeyhash"), _field_ref("apikeyname")],
        aggregations=[
            _agg_count(),
            _agg_sum("inputtokens"),
            _agg_sum("outputtokens"),
            _agg_sum("actualamountusd"),
        ],
        filters=filters,
    )
    rows = await _run(mbql)
    # [apikeyhash, apikeyname, count, in, out, amount]
    items = []
    for r in rows:
        key_hash = r[0] or ""
        items.append({
            "api_key_hash": key_hash,
            # preview column not on card — derive a short hint from the hash
            "api_key_preview": (key_hash[:8] + "…") if key_hash else None,
            "api_key_name": r[1],
            "requests": _int(r[2]),
            "input_tokens": _int(r[3]),
            "output_tokens": _int(r[4]),
            "total_cost": round(_num(r[5]), 6),
            "total_cost_usd": round(_num(r[5]), 6),
        })
    items.sort(key=lambda x: x["total_cost_usd"], reverse=True)
    return items[:20]


async def fetch_time_series(filters: dict) -> list[dict]:
    mbql = _build_query(
        breakout=[_field_ref("ds")],
        aggregations=[
            _agg_count(),
            _agg_sum("inputtokens"),
            _agg_sum("outputtokens"),
            _agg_sum("reasoningtokens"),
            _agg_sum("cachecreationtokens"),
            _agg_sum("actualamountusd"),
        ],
        filters=filters,
    )
    rows = await _run(mbql)
    # [ds, count, in, out, reasoning, cache_creation, amount]
    items = [
        {
            "period": (str(r[0])[:10] if r[0] is not None else None),
            "requests": _int(r[1]),
            "input_tokens": _int(r[2]),
            "output_tokens": _int(r[3]),
            "reasoning_tokens": _int(r[4]),
            "cache_creation_tokens": _int(r[5]),
            "total_cost": round(_num(r[6]), 6),
            "total_cost_usd": round(_num(r[6]), 6),
        }
        for r in rows
    ]
    items.sort(key=lambda x: x["period"] or "")
    return items


async def fetch_time_series_by_model(filters: dict) -> list[dict]:
    mbql = _build_query(
        breakout=[_field_ref("ds"), _field_ref("modelname")],
        aggregations=[
            _agg_count(),
            _agg_sum("inputtokens"),
            _agg_sum("outputtokens"),
            _agg_sum("reasoningtokens"),
            _agg_sum("cachecreationtokens"),
            _agg_sum("actualamountusd"),
        ],
        filters=filters,
    )
    rows = await _run(mbql)
    # [ds, modelname, count, in, out, reasoning, cache_creation, amount]
    items = [
        {
            "period": (str(r[0])[:10] if r[0] is not None else None),
            "model_name": r[1],
            "requests": _int(r[2]),
            "input_tokens": _int(r[3]),
            "output_tokens": _int(r[4]),
            "reasoning_tokens": _int(r[5]),
            "cache_creation_tokens": _int(r[6]),
            "total_cost": round(_num(r[7]), 6),
            "total_cost_usd": round(_num(r[7]), 6),
        }
        for r in rows
    ]
    items.sort(key=lambda x: (x["period"] or "", x["model_name"] or ""))
    return items


__all__ = [
    "is_enabled",
    "fetch_totals",
    "fetch_by_model",
    "fetch_by_api_key",
    "fetch_time_series",
    "fetch_time_series_by_model",
]
