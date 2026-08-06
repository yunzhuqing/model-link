"""Live integration test for tool calling via the Anthropic Messages API.

Mirrors ``test_provider_tool_calling_integration.py`` but drives the
``/v1/messages`` endpoint instead of ``/v1/chat/completions``. The
conversation is expressed with Anthropic Messages content blocks:

  * assistant tool calls are returned as ``tool_use`` content blocks and fed
    back inside an ``assistant`` message (``id`` / ``name`` / ``input``);
  * tool results are sent back as ``tool_result`` content blocks inside a
    ``user`` message (``tool_use_id`` / ``content``).

Every target is tested both with default reasoning and with thinking enabled
through ``thinking={"type": "enabled"}`` (mapped internally to
``reasoning_effort=medium``). The expected final answer is 13,286,025.

Example::

    cd backend && uv run pytest tests/test_provider_tool_calling_integration_messages.py -v -s

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
    CALCULATOR_TOOL_ANTHROPIC,
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


def _extract_text_blocks(content: list[dict[str, Any]]) -> str:
    """Concatenate ``text`` content blocks from the response."""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
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
    messages: list[dict[str, Any]] = [{"role": "user", "content": PROMPT}]
    tool_trace: list[dict[str, Any]] = []

    for round_number in range(1, MAX_ROUNDS + 1):
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": [CALCULATOR_TOOL_ANTHROPIC],
            "tool_choice": {"type": "auto"},
            "max_tokens": 8192,
            "stream": False,
        }
        if reasoning_effort is not None:
            payload["thinking"] = {"type": "enabled", "budget_tokens": 4096}
        response = await client.post(
            "/v1/messages",
            json=payload,
            headers=auth_headers(provider_id),
        )
        assert response.status_code == 200, (
            f"provider {provider_id}, round {round_number} failed: "
            f"{response.status_code} {response.text}"
        )

        body = response.json()
        content_blocks = body.get("content") or []
        assert content_blocks, f"provider {provider_id} returned no content: {body}"

        tool_use_blocks = [
            block
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]

        if not tool_use_blocks:
            return {"content": _extract_text_blocks(content_blocks)}, tool_trace

        # Re-send the assistant turn carrying only the tool_use blocks; the
        # gateway pairs them with the tool results that follow.
        messages.append({"role": "assistant", "content": tool_use_blocks})

        tool_results: list[dict[str, Any]] = []
        for block in tool_use_blocks:
            assert block.get("name") == "calculator", (
                f"provider {provider_id} called an unexpected tool: {block}"
            )
            call_id = block.get("id")
            assert call_id, (
                f"provider {provider_id} returned a tool_use block without id: {block}"
            )
            input_obj = block.get("input", {})
            arguments_json = json.dumps(input_obj)
            result = execute_calculator(arguments_json)
            tool_trace.append(
                {
                    "round": round_number,
                    "arguments": input_obj,
                    "result": result,
                }
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": result,
                }
            )
        # Anthropic convention: all tool results for a turn travel together
        # in a single user message.
        messages.append({"role": "user", "content": tool_results})

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
        if not await server_reachable(http_client, "/v1/messages"):
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
async def test_messages_tool_calling_for_provider(
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
