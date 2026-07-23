"""
Unit tests: verify that requests entering via /v1/chat/completions (OpenAI),
/v1/responses (OpenAI Responses), and /v1/messages (Anthropic) are transformed
into the correct upstream payload for Qwen (Bailian/DashScope).

Bailian always speaks the OpenAI-compatible /chat/completions upstream,
regardless of which public endpoint is hit. The adapters normalise each wire
format into a ChatRequest, and BailianProvider.prepare_request serialises it
to the DashScope OpenAI-compatible body.

Run:
  cd backend && uv run pytest tests/test_bailian_request_transform.py -v
"""
from __future__ import annotations

from typing import Any, Dict

from app.adapters.openai_adapter import OpenAIChatAdapter
from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter
from app.providers import ProviderConfig
from app.providers.bailian.base import BailianProvider


# ---------------------------------------------------------------------------
# Sample requests (one per incoming API surface)
# ---------------------------------------------------------------------------

SAMPLE_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]

CHAT_COMPLETIONS_PAYLOAD: Dict[str, Any] = {
    "model": "qwen-plus",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the weather in Hangzhou?"},
    ],
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 512,
    "stream": False,
    "tools": SAMPLE_TOOLS_OPENAI,
    "tool_choice": "auto",
    "stop": ["\n\n"],
    "user": "test-user",
}

RESPONSES_PAYLOAD: Dict[str, Any] = {
    "model": "qwen-plus",
    "input": [
        {
            "role": "user",
            "type": "message",
            "content": [{"type": "input_text", "text": "What is the weather in Hangzhou?"}],
        }
    ],
    "instructions": "You are a helpful assistant.",
    "temperature": 0.7,
    "top_p": 0.9,
    "max_output_tokens": 512,
    "tools": [
        {
            "type": "function",
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ],
    "stream": False,
}

MESSAGES_PAYLOAD: Dict[str, Any] = {
    "model": "qwen-plus",
    "system": [{"type": "text", "text": "You are a helpful assistant."}],
    "messages": [{"role": "user", "content": "What is the weather in Hangzhou?"}],
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 512,
    "stream": False,
    "tools": [
        {
            "name": "get_weather",
            "description": "Get current weather",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ],
    "tool_choice": {"type": "auto"},
    "stop_sequences": ["\n\n"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider() -> BailianProvider:
    return BailianProvider(ProviderConfig(name="bailian", api_key="sk-test", base_url=None))


def _first_user_text(messages):
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                        return part.get("text")
    return None


def _system_text(messages):
    for m in messages:
        if m.get("role") == "system":
            return m.get("content")
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_chat_completions_upstream_body():
    """/v1/chat/completions → OpenAI chat/completions body."""
    req = OpenAIChatAdapter().parse_request({**CHAT_COMPLETIONS_PAYLOAD})
    body = _provider().prepare_request(req)

    assert body["model"] == "qwen-plus"
    assert body["stream"] is False
    assert body["temperature"] == 0.7
    assert body["top_p"] == 0.9
    assert body["max_tokens"] == 512
    assert body["tool_choice"] == "auto"
    assert body["stop"] == ["\n\n"]
    assert body["user"] == "test-user"
    assert _system_text(body["messages"]) == "You are a helpful assistant."
    assert _first_user_text(body["messages"]) == "What is the weather in Hangzhou?"

    tools = body.get("tools", [])
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "get_weather"

    for bad in ("input", "instructions", "max_output_tokens"):
        assert bad not in body


def test_responses_upstream_body():
    """/v1/responses → OpenAI chat/completions body (instructions → system)."""
    req = OpenAIResponsesAdapter().parse_request({**RESPONSES_PAYLOAD})
    body = _provider().prepare_request(req)

    assert body["model"] == "qwen-plus"
    assert body["stream"] is False
    assert body["temperature"] == 0.7
    assert body["top_p"] == 0.9
    assert body["max_tokens"] == 512
    assert _system_text(body["messages"]) == "You are a helpful assistant."
    assert _first_user_text(body["messages"]) == "What is the weather in Hangzhou?"

    tools = body.get("tools", [])
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "get_weather"

    for bad in ("input", "instructions", "max_output_tokens"):
        assert bad not in body


def test_messages_upstream_body():
    """/v1/messages → OpenAI chat/completions body (Anthropic tools/stop → OpenAI)."""
    req = AnthropicMessagesAdapter().parse_request({**MESSAGES_PAYLOAD})
    body = _provider().prepare_request(req)

    assert body["model"] == "qwen-plus"
    assert body["stream"] is False
    assert body["temperature"] == 0.7
    assert body["top_p"] == 0.9
    assert body["max_tokens"] == 512
    assert _system_text(body["messages"]) == "You are a helpful assistant."
    assert _first_user_text(body["messages"]) == "What is the weather in Hangzhou?"

    tools = body.get("tools", [])
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "get_weather"
    assert "parameters" in tools[0]["function"]
    assert body.get("stop") == ["\n\n"]

    for bad in ("input", "instructions", "system", "stop_sequences",
                "max_output_tokens", "input_schema"):
        assert bad not in body


def test_stream_flag_propagates():
    req = OpenAIChatAdapter().parse_request({**CHAT_COMPLETIONS_PAYLOAD, "stream": True})
    body = _provider().prepare_request(req)
    assert body["stream"] is True


if __name__ == "__main__":
    import traceback
    tests = [
        test_chat_completions_upstream_body,
        test_responses_upstream_body,
        test_messages_upstream_body,
        test_stream_flag_propagates,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{'All' if failed == 0 else f'{failed} failed'} tests done.")
