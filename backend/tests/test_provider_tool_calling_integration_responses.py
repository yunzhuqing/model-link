"""Live integration test for tool calling via the OpenAI Responses API.

Mirrors ``test_provider_tool_calling_integration.py`` but drives the
``/v1/responses`` endpoint instead of ``/v1/chat/completions``. The
conversation is expressed with Responses-API input/output items:

  * assistant tool calls are returned as ``function_call`` output items, and
    fed back as ``function_call`` input items (``call_id`` / ``arguments``);
  * tool results are sent back as ``function_call_output`` input items
    (``call_id`` / ``output``).

Every target is tested both with default reasoning and with thinking enabled
through ``reasoning={"effort": "medium"}``. The expected final answer is
13,286,025.

Example::

    cd backend && uv run pytest tests/test_provider_tool_calling_integration_responses.py -v -s

Skips automatically when the configuration or live server is unavailable.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import pytest_asyncio

from tests._provider_tool_helpers import (
    BASE_URL,
    CALCULATOR_TOOL_RESPONSES,
    MAX_ROUNDS,
    PROMPT,
    TARGETS,
    _MISSING_CONFIG,
    _SKIP_REASON,
    assert_final_answer,
    auth_headers,
    execute_calculator,
    server_reachable,
)


def _extract_output_text(output: list[dict[str, Any]]) -> str:
    """Concatenate ``output_text`` content from ``message`` output items."""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
    return "\n".join(parts)


async def _run_tool_conversation(
    client: httpx.AsyncClient,
    model: str,
    provider_id: int,
    reasoning_effort: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    input_items: list[dict[str, Any]] = [{"role": "user", "content": PROMPT}]
    tool_trace: list[dict[str, Any]] = []

    for round_number in range(1, MAX_ROUNDS + 1):
        payload: dict[str, Any] = {
            "model": model,
            "input": input_items,
            "tools": [CALCULATOR_TOOL_RESPONSES],
            "tool_choice": "auto",
            "stream": False,
        }
        if reasoning_effort is not None:
            payload["reasoning"] = {"effort": reasoning_effort}
        response = await client.post(
            "/v1/responses",
            json=payload,
            headers=auth_headers(provider_id),
        )
        assert response.status_code == 200, (
            f"provider {provider_id}, round {round_number} failed: "
            f"{response.status_code} {response.text}"
        )

        body = response.json()
        output = body.get("output") or []
        assert output, f"provider {provider_id} returned no output items: {body}"

        function_calls = [
            item for item in output if isinstance(item, dict) and item.get("type") == "function_call"
        ]

        if not function_calls:
            return {"content": _extract_output_text(output)}, tool_trace

        for call in function_calls:
            assert call.get("name") == "calculator", (
                f"provider {provider_id} called an unexpected tool: {call}"
            )
            call_id = call.get("call_id") or call.get("id")
            assert call_id, (
                f"provider {provider_id} returned a function call without call_id: {call}"
            )
            arguments_json = call.get("arguments", "{}")
            result = execute_calculator(arguments_json)
            tool_trace.append(
                {
                    "round": round_number,
                    "arguments": json.loads(arguments_json),
                    "result": result,
                }
            )
            # Echo the assistant tool call back as a ``function_call`` input item.
            input_items.append(
                {
                    "type": "function_call",
                    "id": call.get("id", call_id),
                    "call_id": call_id,
                    "name": "calculator",
                    "arguments": arguments_json,
                }
            )
            # Provide the executed result as a ``function_call_output`` input item.
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result,
                }
            )

    pytest.fail(
        f"provider {provider_id} did not produce a final answer after {MAX_ROUNDS} rounds; "
        f"tool trace: {tool_trace}"
    )


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=httpx.Timeout(60.0, connect=10.0),
    ) as http_client:
        if not await server_reachable(http_client, "/v1/responses"):
            pytest.skip(f"Server at {BASE_URL} is not reachable or configuration is missing.")
        yield http_client


@pytest.mark.skipif(bool(_MISSING_CONFIG), reason=_SKIP_REASON)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "provider_id"),
    TARGETS or [("missing-model", 0)],
    ids=[f"{model}-provider-{provider_id}" for model, provider_id in TARGETS]
    or ["missing-target"],
)
@pytest.mark.parametrize(
    "reasoning_effort",
    [None, "medium"],
    ids=["default-reasoning", "thinking-enabled"],
)
async def test_responses_tool_calling_for_provider(
    client: httpx.AsyncClient,
    model: str,
    provider_id: int,
    reasoning_effort: str | None,
):
    assistant, tool_trace = await _run_tool_conversation(
        client,
        model,
        provider_id,
        reasoning_effort=reasoning_effort,
    )

    assert_final_answer(assistant, tool_trace, provider_id)
    mode = reasoning_effort or "default"
    print(f"\n[provider {provider_id}] model={model} reasoning={mode} tool_trace={tool_trace}")
    print(f"[provider {provider_id}] final={assistant.get('content')}")
