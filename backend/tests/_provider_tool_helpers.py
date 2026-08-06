"""Shared helpers for live provider tool-calling integration tests.

The same calculator prompt and expected answer (13,286,025) are exercised
through three OpenAI/Anthropic-compatible surfaces exposed by Model Link:

  * /v1/chat/completions  (OpenAI Chat Completions tool_calls)
  * /v1/responses         (OpenAI Responses API function_call items)
  * /v1/messages          (Anthropic Messages tool_use blocks)

Each request is pinned to a provider through Model Link's derived API-key
format ``<MODEL_LINK_API_KEY>-<provider_id>``.

Configuration is read from ``tests/provider_tool_test.yaml``. Set ``base_url``,
``api_key``, and add one entry per model with its provider IDs. The tests
skip automatically when the configuration or live server is unavailable, so
ordinary unit-test runs do not call external providers.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml


CONFIG_PATH = Path(__file__).with_name("provider_tool_test.yaml")


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    if not isinstance(config, dict):
        raise ValueError(f"{CONFIG_PATH} must contain a YAML mapping")
    return config


CONFIG = _load_config()
BASE_URL = str(CONFIG.get("base_url", "http://localhost:8000")).rstrip("/")
API_KEY = str(CONFIG.get("api_key", "")).strip()
MAX_ROUNDS = int(CONFIG.get("max_rounds", 8))

PROMPT = (
    "Take 3 to the fifth power and multiply that by the sum of twelve and "
    "three, then square the whole result"
)
EXPECTED_RESULT = Decimal("13286025")


def _parse_targets(models: Any) -> list[tuple[str, int]]:
    """Expand YAML model entries into model/provider test cases."""
    if models is None:
        return []
    if not isinstance(models, list):
        raise ValueError(f"{CONFIG_PATH}: models must be a list")
    targets: list[tuple[str, int]] = []
    for entry in models:
        if not isinstance(entry, dict):
            raise ValueError(f"{CONFIG_PATH}: each model entry must be a mapping")
        model = str(entry.get("name", "")).strip()
        provider_ids = entry.get("provider_ids")
        if not model or not isinstance(provider_ids, list) or not provider_ids:
            raise ValueError(
                f"{CONFIG_PATH}: each model needs a name and non-empty provider_ids list"
            )
        for provider_id in provider_ids:
            if not isinstance(provider_id, int) or isinstance(provider_id, bool) or provider_id <= 0:
                raise ValueError(
                    f"{CONFIG_PATH}: provider IDs must be positive integers; "
                    f"got {provider_id!r}"
                )
            targets.append((model, provider_id))
    return targets


TARGETS = _parse_targets(CONFIG.get("models"))
_MISSING_CONFIG = [
    name
    for name, value in (
        ("api_key", API_KEY),
        ("models", TARGETS),
    )
    if not value
]
_SKIP_REASON = (
    f"Set {', '.join(_MISSING_CONFIG)} in {CONFIG_PATH} to run live provider tool tests."
)


# ── Calculator tool definitions (one per API surface) ────────────────────

CALCULATOR_DESCRIPTION = (
    "Perform exactly one arithmetic operation. Always use this tool for every "
    "calculation; do not calculate arithmetic mentally. Use previous tool results "
    "as inputs when multiple operations are needed."
)

CALCULATOR_PARAMETERS = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["add", "subtract", "multiply", "divide", "power"],
        },
        "left": {"type": "number"},
        "right": {"type": "number"},
    },
    "required": ["operation", "left", "right"],
    "additionalProperties": False,
}

# OpenAI Chat Completions: nested ``function`` wrapper.
CALCULATOR_TOOL_CHAT = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": CALCULATOR_DESCRIPTION,
        "parameters": CALCULATOR_PARAMETERS,
    },
}

# OpenAI Responses API: flat ``function`` tool (name/description/parameters
# on the tool object itself).
CALCULATOR_TOOL_RESPONSES = {
    "type": "function",
    "name": "calculator",
    "description": CALCULATOR_DESCRIPTION,
    "parameters": CALCULATOR_PARAMETERS,
}

# Anthropic Messages: ``input_schema`` instead of ``parameters``.
CALCULATOR_TOOL_ANTHROPIC = {
    "name": "calculator",
    "description": CALCULATOR_DESCRIPTION,
    "input_schema": CALCULATOR_PARAMETERS,
}


# ── Auth + reachability ──────────────────────────────────────────────────

def auth_headers(provider_id: int) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}-{provider_id}",
    }


async def server_reachable(client: httpx.AsyncClient, probe_path: str = "/v1/chat/completions") -> bool:
    if _MISSING_CONFIG:
        return False
    try:
        response = await client.head(probe_path, timeout=5.0)
        return response.status_code in (200, 400, 401, 405)
    except httpx.HTTPError:
        return False


# ── Calculator execution + answer extraction ──────────────────────────────

def execute_calculator(arguments_json: str) -> str:
    try:
        arguments = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        pytest.fail(f"calculator returned invalid JSON arguments: {arguments_json!r}: {exc}")

    operation = arguments.get("operation")
    try:
        left = Decimal(str(arguments["left"]))
        right = Decimal(str(arguments["right"]))
    except (KeyError, InvalidOperation) as exc:
        pytest.fail(f"calculator returned invalid numeric arguments: {arguments!r}: {exc}")

    if operation == "add":
        result = left + right
    elif operation == "subtract":
        result = left - right
    elif operation == "multiply":
        result = left * right
    elif operation == "divide":
        if right == 0:
            pytest.fail("calculator attempted division by zero")
        result = left / right
    elif operation == "power":
        if right != right.to_integral_value():
            pytest.fail(f"calculator only supports integer exponents, got {right}")
        result = left ** int(right)
    else:
        pytest.fail(f"calculator returned unsupported operation: {operation!r}")

    return format(result, "f")


def extract_numeric_answers(content: Any) -> list[Decimal]:
    if not isinstance(content, str):
        return []
    # Models commonly insert LaTeX negative-thin-space markers after grouping
    # commas, e.g. ``13,\!286,\!025``, or wrap commas as ``13{,}286``.
    normalized_content = content.replace("\\!", "").replace("{,}", ",")
    candidates = re.findall(
        r"(?<![\w.])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w)",
        normalized_content,
    )
    answers: list[Decimal] = []
    for candidate in candidates:
        try:
            answers.append(Decimal(candidate.replace(",", "")))
        except InvalidOperation:
            continue
    return answers


def assert_final_answer(
    assistant: dict[str, Any],
    tool_trace: list[dict[str, Any]],
    provider_id: int,
) -> None:
    """Shared assertion: calculator was used and the final answer is correct."""
    assert tool_trace, (
        f"provider {provider_id} answered without calling calculator; "
        f"assistant message: {assistant}"
    )
    numeric_answers = extract_numeric_answers(assistant.get("content"))
    assert EXPECTED_RESULT in numeric_answers, (
        f"provider {provider_id} returned the wrong final answer. "
        f"Expected {EXPECTED_RESULT}, found {numeric_answers}; "
        f"content={assistant.get('content')!r}; tool trace={tool_trace}"
    )
    assert all(math.isfinite(float(step["result"])) for step in tool_trace)
