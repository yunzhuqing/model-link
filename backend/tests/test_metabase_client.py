"""Unit tests for the Metabase stats client helpers.

Covers the pure functions only — period expression construction and period
normalization. The HTTP path is not exercised here.

Run: cd backend && uv run pytest tests/test_metabase_client.py -q
"""
from __future__ import annotations

import json

from app.stats import metabase_client as mb


def test_normalize_period_hour():
    # Expression output is unpadded ("2026-8-9 13"); re-zero into DB shape.
    assert mb._normalize_period("2026-8-9 13", "hour") == "2026-08-09T13:00:00"


def test_normalize_period_hour_t_delimited():
    assert mb._normalize_period("2026-8-9T13", "hour") == "2026-08-09T13:00:00"


def test_normalize_period_month():
    assert mb._normalize_period("2026-8", "month") == "2026-08-01T00:00:00"


def test_normalize_period_day_via_iso_period():
    # day keeps the existing ``ds`` partition normalization.
    assert mb._normalize_period("20260713", "day") == "2026-07-13"
    assert mb._normalize_period("2026-07-13", "day") == "2026-07-13"


def test_normalize_period_none():
    assert mb._normalize_period(None, "hour") is None


def test_period_expression_day(monkeypatch):
    monkeypatch.setenv("METABASE_FIELD_DS_UUID", "test-ds-uuid")
    breakout, expressions = mb._period_expression("day")
    assert expressions == []
    assert breakout[0][0] == "field"
    assert breakout[0][2] == "ds"


def test_period_expression_hour():
    breakout, expressions = mb._period_expression("hour")
    assert breakout[0][0] == "expression"
    assert breakout[0][1]["lib/uuid"]
    assert breakout[0][2] == "hour_of_day"
    assert len(expressions) == 1
    expr = expressions[0]
    assert expr[0] == "concat"
    assert expr[1]["lib/expression-name"] == "hour_of_day"
    flat = json.dumps(expr)
    for fn in ("get-year", "get-month", "get-day", "get-hour"):
        assert fn in flat
    assert "_time" in flat


def test_period_expression_month():
    breakout, expressions = mb._period_expression("month")
    assert breakout[0][0] == "expression"
    assert breakout[0][1]["lib/uuid"]
    assert breakout[0][2] == "year_month"
    assert len(expressions) == 1
    expr = expressions[0]
    assert expr[1]["lib/expression-name"] == "year_month"
    flat = json.dumps(expr)
    assert "get-year" in flat and "get-month" in flat
    assert "get-hour" not in flat
