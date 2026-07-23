"""
Unit tests: verify that requests entering via /v1/chat/completions (OpenAI),
/v1/responses (OpenAI Responses), and /v1/messages (Anthropic) are transformed
into the correct upstream payload for Doubao (Volcengine/ARK).

Volcengine supports two upstream formats, selected by the model's api_type:
  - default ("" or contains "responses") → /v3/responses
  - api_type contains "chat_completions" and not "responses" → /v3/chat/completions (OpenAI)

The gateway sets `provider._model_api_type` based on the model configuration
before calling provider.chat(); we simulate that here to test both paths for
each incoming endpoint.

Run:
  cd backend && uv run pytest tests/test_volcengine_request_transform.py -v
"""
from __future__ import annotations

from typing import Any, Dict

from app.adapters.openai_adapter import OpenAIChatAdapter
from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter
from app.providers import ProviderConfig
from app.providers.volcengine.base import VolcengineProvider


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

DOUBAO_MODEL = "doubao-seed-2-0-pro-260215"

CHAT_COMPLETIONS_PAYLOAD: Dict[str, Any] = {
    "model": DOUBAO_MODEL,
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
}

RESPONSES_PAYLOAD: Dict[str, Any] = {
    "model": DOUBAO_MODEL,
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
    "model": DOUBAO_MODEL,
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

def _provider() -> VolcengineProvider:
    return VolcengineProvider(ProviderConfig(name="volcengine", api_key="sk-test", base_url=None))


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


def _collect_user_texts(input_items):
    """Pull user-facing text strings from a Responses-API input list."""
    texts = []
    for it in input_items:
        c = it.get("content")
        if isinstance(c, str) and it.get("role") == "user":
            texts.append(c)
        elif isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") in ("input_text", "output_text"):
                    texts.append(p.get("text"))
    return texts


def _chat_body(payload: Dict[str, Any], adapter) -> Dict[str, Any]:
    """Build an upstream body as if the model were routed to /v3/chat/completions."""
    p = _provider()
    p._model_api_type = "chat_completions"
    req = adapter.parse_request(payload)
    return p.prepare_request(req)


def _responses_body(payload: Dict[str, Any], adapter) -> Dict[str, Any]:
    """Build an upstream body as if the model were routed to /v3/responses (default)."""
    p = _provider()
    p._model_api_type = ""
    req = adapter.parse_request(payload)
    req.metadata = req.metadata or {}
    return p._prepare_responses_request(req)


# ---------------------------------------------------------------------------
# /v1/chat/completions  →  upstream
# ---------------------------------------------------------------------------

def test_chat_completions_upstream_chat_mode():
    """chat/completions endpoint + chat_completions api_type → OpenAI body."""
    body = _chat_body(CHAT_COMPLETIONS_PAYLOAD, OpenAIChatAdapter())
    assert body["model"] == DOUBAO_MODEL
    assert body["stream"] is False
    assert body["temperature"] == 0.7
    assert body["top_p"] == 0.9
    assert body["max_tokens"] == 512
    assert body["tool_choice"] == "auto"
    assert body["stop"] == ["\n\n"]
    assert _system_text(body["messages"]) == "You are a helpful assistant."
    assert _first_user_text(body["messages"]) == "What is the weather in Hangzhou?"

    tools = body.get("tools", [])
    assert len(tools) == 1 and tools[0]["function"]["name"] == "get_weather"
    for bad in ("input", "instructions"):
        assert bad not in body


def test_chat_completions_upstream_responses_mode():
    """chat/completions endpoint + default (responses) api_type → Responses body."""
    body = _responses_body(CHAT_COMPLETIONS_PAYLOAD, OpenAIChatAdapter())
    assert "input" in body
    assert "messages" not in body
    assert body.get("stream") is False
    # OpenAI adapter doesn't set instructions; only user text is present.
    user_texts = _collect_user_texts(body["input"])
    assert any("weather in Hangzhou" in (t or "") for t in user_texts), body["input"]


# ---------------------------------------------------------------------------
# /v1/responses  →  upstream
# ---------------------------------------------------------------------------

def test_responses_upstream_responses_mode():
    """responses endpoint + default (responses) api_type → Responses body."""
    body = _responses_body(RESPONSES_PAYLOAD, OpenAIResponsesAdapter())
    assert "input" in body
    assert "messages" not in body
    assert body.get("stream") is False
    # instructions stay as the top-level "instructions" field
    assert "helpful assistant" in (body.get("instructions") or ""), body
    user_texts = _collect_user_texts(body["input"])
    assert any("weather in Hangzhou" in (t or "") for t in user_texts), body["input"]

    tools = body.get("tools", [])
    assert len(tools) == 1
    tool_name = tools[0].get("name") or tools[0].get("function", {}).get("name")
    assert tool_name == "get_weather", tools


def test_responses_upstream_chat_mode():
    """responses endpoint + chat_completions api_type → OpenAI body."""
    p = _provider()
    p._model_api_type = "chat_completions"
    req = OpenAIResponsesAdapter().parse_request(RESPONSES_PAYLOAD)
    body = p.prepare_request(req)

    assert "messages" in body
    assert "input" not in body
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 512
    assert _system_text(body["messages"]) == "You are a helpful assistant."
    assert _first_user_text(body["messages"]) == "What is the weather in Hangzhou?"


# ---------------------------------------------------------------------------
# /v1/messages  →  upstream
# ---------------------------------------------------------------------------

def test_messages_upstream_responses_mode():
    """messages endpoint + default (responses) api_type → Responses body."""
    body = _responses_body(MESSAGES_PAYLOAD, AnthropicMessagesAdapter())
    assert "input" in body
    assert "messages" not in body
    # Anthropic system → top-level "instructions"
    assert "helpful assistant" in (body.get("instructions") or ""), body
    user_texts = _collect_user_texts(body["input"])
    assert any("weather in Hangzhou" in (t or "") for t in user_texts), body["input"]

    tools = body.get("tools", [])
    assert len(tools) == 1
    tool_name = tools[0].get("name") or tools[0].get("function", {}).get("name")
    assert tool_name == "get_weather", tools
    # Volcengine Responses API does not support stop; filtered out by allowed-key set.
    assert "stop" not in body


def test_messages_upstream_chat_mode():
    """messages endpoint + chat_completions api_type → OpenAI body."""
    body = _chat_body(MESSAGES_PAYLOAD, AnthropicMessagesAdapter())
    assert "messages" in body
    assert "input" not in body
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 512
    assert _system_text(body["messages"]) == "You are a helpful assistant."
    assert _first_user_text(body["messages"]) == "What is the weather in Hangzhou?"

    tools = body.get("tools", [])
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "get_weather"
    assert "parameters" in tools[0]["function"]
    assert body.get("stop") == ["\n\n"]


# ---------------------------------------------------------------------------
# Reasoning effort mapping
# ---------------------------------------------------------------------------

def test_reasoning_effort_mapping_chat_mode():
    """chat path: openai minimal → thinking.enabled + reasoning_effort=low."""
    p = _provider()
    p._model_api_type = "chat_completions"
    payload = {**CHAT_COMPLETIONS_PAYLOAD, "reasoning_effort": "minimal", "tools": None}
    req = OpenAIChatAdapter().parse_request(payload)
    body = p.prepare_request(req)
    assert body.get("thinking") == {"type": "enabled"}, body
    assert body.get("reasoning_effort") == "low", body


def test_reasoning_effort_mapping_responses_mode():
    """responses path: reasoning.effort=max → thinking.enabled + reasoning.effort=max,
    and xhigh is clamped to high on /v3/responses."""
    p = _provider()
    p._model_api_type = ""
    payload = {**RESPONSES_PAYLOAD, "reasoning": {"effort": "max"}}
    req = OpenAIResponsesAdapter().parse_request(payload)
    req.metadata = req.metadata or {}
    body = p._prepare_responses_request(req)
    assert body.get("thinking") == {"type": "enabled"}, body
    assert body.get("reasoning") == {"effort": "max"}, body


def test_reasoning_effort_responses_clamps_xhigh():
    """xhigh is clamped to high on /v3/responses (no xhigh support there)."""
    p = _provider()
    p._model_api_type = ""
    payload = {**RESPONSES_PAYLOAD, "reasoning": {"effort": "xhigh"}}
    req = OpenAIResponsesAdapter().parse_request(payload)
    req.metadata = req.metadata or {}
    body = p._prepare_responses_request(req)
    assert body.get("thinking") == {"type": "enabled"}
    assert body.get("reasoning") == {"effort": "high"}, body


if __name__ == "__main__":
    import traceback
    tests = [
        test_chat_completions_upstream_chat_mode,
        test_chat_completions_upstream_responses_mode,
        test_responses_upstream_responses_mode,
        test_responses_upstream_chat_mode,
        test_messages_upstream_responses_mode,
        test_messages_upstream_chat_mode,
        test_reasoning_effort_mapping_chat_mode,
        test_reasoning_effort_mapping_responses_mode,
        test_reasoning_effort_responses_clamps_xhigh,
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
