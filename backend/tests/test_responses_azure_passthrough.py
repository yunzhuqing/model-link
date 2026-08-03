"""
Regression test: /v1/responses → Azure Responses API must round-trip the
fields Codex-style clients rely on for prompt caching / turn tracking:

  1. ``prompt_cache_key``      — top-level, references a cached prompt
  2. ``client_metadata``       — top-level, turn/session tracking
  3. ``text``                  — top-level (``verbosity`` / ``format``)
  4. per-input-block ``id``    — content-part ids anchor prompt-cache keys

The conversion chain is:
  OpenAIResponsesAdapter.parse_request() → ChatRequest
  → build_responses_request() → upstream body (Azure / OpenAI / Volcengine)

Run: cd backend && uv run pytest test_responses_azure_passthrough.py -q
"""
import json

from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.providers._responses_format import build_responses_request


def _build(data: dict) -> dict:
    req = OpenAIResponsesAdapter().parse_request(data)
    return build_responses_request(req)


def test_top_level_prompt_cache_key_and_client_metadata_passthrough():
    """prompt_cache_key / client_metadata must reach the upstream body verbatim."""
    body = _build({
        "model": "gpt-5",
        "prompt_cache_key": "019fc285-5294-73d1-99a2-ad93e4d195f7",
        "client_metadata": {
            "thread_id": "019fc285-5294-73d1-99a2-ad93e4d195f7",
            "turn_id": "019fc287-064f-7533-8b58-4c12b3e6478f",
        },
        "input": [{"role": "user", "content": "hi"}],
    })
    assert body["prompt_cache_key"] == "019fc285-5294-73d1-99a2-ad93e4d195f7"
    assert body["client_metadata"] == {
        "thread_id": "019fc285-5294-73d1-99a2-ad93e4d195f7",
        "turn_id": "019fc287-064f-7533-8b58-4c12b3e6478f",
    }


def test_store_and_truncation_passthrough():
    """``store`` / ``truncation`` (whitelisted top-level fields) must reach upstream.

    Regression: both were in the adapter's _KNOWN exclusion set, so they never
    entered ChatRequest.metadata and were silently dropped.
    """
    body = _build({
        "model": "gpt-5",
        "store": True,
        "truncation": "auto",
        "input": [{"role": "user", "content": "hi"}],
    })
    assert body["store"] is True
    assert body["truncation"] == "auto"


def test_text_passthrough_with_verbosity():
    """Top-level ``text`` (e.g. {"verbosity": "low"}) must reach the upstream body."""
    body = _build({
        "model": "gpt-5",
        "text": {"verbosity": "low"},
        "input": [{"role": "user", "content": "hi"}],
    })
    assert body["text"] == {"verbosity": "low"}


def test_text_format_passthrough():
    """Client-sent ``text.format`` (Responses API structured outputs) passes through."""
    body = _build({
        "model": "gpt-5",
        "text": {"format": {"type": "json_schema", "name": "x",
                            "schema": {"type": "object"}}},
        "input": [{"role": "user", "content": "hi"}],
    })
    assert body["text"] == {"format": {"type": "json_schema", "name": "x",
                                       "schema": {"type": "object"}}}


def test_text_merges_with_response_format():
    """Client-sent ``text`` must merge with (not clobber) response_format-derived text.

    ``response_format`` is only set on the ChatRequest by chat-completions
    adapters converting to the Responses API; ``text`` in metadata comes from
    the /v1/responses request. Construct both directly to assert the merge.
    """
    from app.abstraction.chat import ChatRequest
    from app.abstraction.messages import Message, MessageRole
    req = ChatRequest(
        messages=[Message(role=MessageRole.USER, content="hi")],
        model="gpt-5",
        response_format={"type": "json_schema", "json_schema": {
            "name": "x", "schema": {"type": "object"}
        }},
        metadata={"text": {"verbosity": "medium"}},
    )
    body = build_responses_request(req)
    assert body["text"]["verbosity"] == "medium"
    assert body["text"]["format"]["type"] == "json_schema"


def test_input_block_id_round_trips():
    """Content-part ``id`` on input blocks must survive to the upstream body."""
    body = _build({
        "model": "gpt-5",
        "input": [
            {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "hello", "id": "block_1",
                 "prompt_cache_breakpoint": {"mode": "explicit"}},
                {"type": "input_text", "text": "world", "id": "block_2"},
            ]},
        ],
    })
    content = body["input"][0]["content"]
    assert content == [
        {"type": "input_text", "text": "hello",
         "prompt_cache_breakpoint": {"mode": "explicit"}, "id": "block_1"},
        {"type": "input_text", "text": "world", "id": "block_2"},
    ]


def test_input_message_id_round_trips():
    """The ``id`` on top-level input ``message`` items must also survive."""
    body = _build({
        "model": "gpt-5",
        "input": [
            {"type": "message", "id": "msg_1", "role": "user", "content": [
                {"type": "input_text", "text": "hello", "id": "block_1"},
            ]},
            {"type": "message", "id": "msg_2", "role": "assistant", "content": [
                {"type": "output_text", "text": "hi", "id": "block_2"},
            ]},
        ],
    })
    assert body["input"][0] == {
        "type": "message", "role": "user",
        "content": [{"type": "input_text", "text": "hello", "id": "block_1"}],
        "id": "msg_1",
    }
    assert body["input"][1] == {
        "type": "message", "role": "assistant",
        "content": [{"type": "output_text", "text": "hi", "id": "block_2"}],
        "id": "msg_2",
    }


def test_assistant_output_text_id_round_trips():
    """assistant ``output_text`` blocks also carry their id (multi-turn round-trip)."""
    body = _build({
        "model": "gpt-5",
        "input": [
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "thinking...", "id": "msg_a_0"},
            ]},
        ],
    })
    assert body["input"][0]["content"] == [
        {"type": "output_text", "text": "thinking...", "id": "msg_a_0"},
    ]


def test_tool_output_block_id_round_trips():
    """function_call_output content blocks keep id / prompt_cache_breakpoint."""
    body = _build({
        "model": "gpt-5",
        "input": [
            {"type": "function_call_output", "call_id": "call_1", "output": [
                {"type": "input_image",
                 "image_url": "data:image/png;base64,AAAA",
                 "id": "img_1", "prompt_cache_breakpoint": {"mode": "explicit"}},
            ]},
        ],
    })
    assert body["input"][0]["output"] == [
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA",
         "prompt_cache_breakpoint": {"mode": "explicit"}, "id": "img_1"},
    ]
