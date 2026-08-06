"""Live integration test for tool calling across pinned model providers.

The test sends the same prompt to the same model while pinning each request to
a provider through Model Link's derived API-key format::

    <MODEL_LINK_API_KEY>-<provider_id>

It executes every calculator tool call returned by the model, sends the tool
results back, and verifies that the final answer is 13,286,025. Every target is
tested both with default reasoning and with thinking enabled through
``reasoning_effort=medium``.

This is the OpenAI Chat Completions surface (``/v1/chat/completions``). The
sibling ``/v1/responses`` and ``/v1/messages`` surfaces are covered by
``test_provider_tool_calling_integration_responses.py`` and
``test_provider_tool_calling_integration_messages.py``. Shared configuration,
calculator logic and tool definitions live in ``_provider_tool_helpers.py``.

Example::

    cd backend && uv run pytest tests/test_provider_tool_calling_integration.py -v -s

The test skips automatically when the required configuration or live server is
unavailable, so ordinary unit-test runs do not call external providers.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import pytest_asyncio

from tests._provider_tool_helpers import (
    BASE_URL,
    CALCULATOR_TOOL_CHAT,
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


async def _run_tool_conversation(
    client: httpx.AsyncClient,
    model: str,
    provider_id: int,
    reasoning_effort: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": PROMPT}]
    tool_trace: list[dict[str, Any]] = []

    for round_number in range(1, MAX_ROUNDS + 1):
        payload = {
            "model": model,
            "messages": messages,
            "tools": [CALCULATOR_TOOL_CHAT],
            "tool_choice": "auto",
            "stream": False,
        }
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        response = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers=auth_headers(provider_id),
        )
        assert response.status_code == 200, (
            f"provider {provider_id}, round {round_number} failed: "
            f"{response.status_code} {response.text}"
        )

        body = response.json()
        choices = body.get("choices") or []
        assert choices, f"provider {provider_id} returned no choices: {body}"
        assistant = choices[0].get("message") or {}
        tool_calls = assistant.get("tool_calls") or []

        if not tool_calls:
            return assistant, tool_trace

        messages.append(
            {
                "role": "assistant",
                "content": assistant.get("content"),
                "tool_calls": tool_calls,
            }
        )
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            assert function.get("name") == "calculator", (
                f"provider {provider_id} called an unexpected tool: {tool_call}"
            )
            call_id = tool_call.get("id")
            assert call_id, f"provider {provider_id} returned a tool call without id: {tool_call}"
            result = execute_calculator(function.get("arguments", ""))
            tool_trace.append(
                {
                    "round": round_number,
                    "arguments": json.loads(function["arguments"]),
                    "result": result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
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
        if not await server_reachable(http_client):
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
async def test_model_tool_calling_for_provider(
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
