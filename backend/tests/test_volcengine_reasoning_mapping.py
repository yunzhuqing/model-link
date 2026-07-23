"""
Regression test: VolcengineProvider maps OpenAI reasoning_effort to Doubao
effort + drives the `thinking` switch for both /v3/responses and
/v3/chat/completions paths.

运行: cd backend && uv run python test_volcengine_reasoning_mapping.py
"""
from app.providers import ProviderConfig
from app.providers.volcengine.base import VolcengineProvider
from app.abstraction.chat import ChatRequest
from app.abstraction.messages import Message, MessageRole


def _provider() -> VolcengineProvider:
    return VolcengineProvider(ProviderConfig(name="volcengine", api_key="x", base_url=None))


def _request(model="doubao-seed-2-0-pro-260215", effort=None, support_thinking=False,
             reasoning_meta=None) -> ChatRequest:
    req = ChatRequest(model=model,
                      messages=[Message(role=MessageRole.USER, content="hi")])
    if effort is not None:
        req.reasoning_effort = effort
    req.metadata = {}
    if support_thinking:
        req.metadata["support_thinking"] = True
    if reasoning_meta is not None:
        req.metadata["reasoning"] = reasoning_meta
    return req


# ── _resolve_doubao_reasoning ───────────────────────────────────────────────

def test_resolve_off_when_none():
    p = _provider()
    t, e = p._resolve_doubao_reasoning(_request(effort="none"))
    assert t == "disabled", (t, e)
    assert e is None, (t, e)
    print("PASS: openai none -> thinking disabled, no effort")


def test_resolve_enabled_mapping():
    p = _provider()
    expected = {
        "minimal": "low", "low": "low", "medium": "medium",
        "high": "high", "xhigh": "xhigh", "max": "max",
    }
    for oai, doubao in expected.items():
        t, e = p._resolve_doubao_reasoning(_request(effort=oai), allow_xhigh=True)
        assert t == "enabled", (oai, t)
        assert e == doubao, (oai, e)
    print("PASS: openai minimal..max -> enabled + mapped effort (chat path)")


def test_resolve_responses_clamps_xhigh():
    p = _provider()
    t, e = p._resolve_doubao_reasoning(_request(effort="xhigh"), allow_xhigh=False)
    assert t == "enabled" and e == "high", (t, e)
    print("PASS: responses path clamps xhigh -> high")


def test_resolve_no_effort_support_thinking_auto():
    p = _provider()
    t, e = p._resolve_doubao_reasoning(_request(support_thinking=True))
    assert t == "auto" and e is None, (t, e)
    print("PASS: support_thinking + no effort -> thinking auto")


def test_resolve_no_effort_no_support():
    p = _provider()
    t, e = p._resolve_doubao_reasoning(_request())
    assert t is None and e is None, (t, e)
    print("PASS: no effort, no support -> nothing")


# ── responses path: _prepare_responses_request ─────────────────────────────

def test_responses_request_builds_thinking_and_reasoning():
    p = _provider()
    req = _request(effort="minimal")  # openai minimal -> doubao low, enabled
    data = p._prepare_responses_request(req)
    assert data.get("thinking") == {"type": "enabled"}, data.get("thinking")
    assert data.get("reasoning") == {"effort": "low"}, data.get("reasoning")
    print("PASS: /v3/responses builds thinking=enabled + reasoning.effort=low for openai minimal")


def test_responses_request_none_disables():
    p = _provider()
    data = p._prepare_responses_request(_request(effort="none"))
    assert data.get("thinking") == {"type": "disabled"}, data.get("thinking")
    assert "reasoning" not in data, data.get("reasoning")
    print("PASS: /v3/responses openai none -> thinking disabled, no reasoning")


def test_responses_request_max():
    p = _provider()
    data = p._prepare_responses_request(_request(effort="max"))
    assert data["thinking"] == {"type": "enabled"}
    assert data["reasoning"] == {"effort": "max"}, data["reasoning"]
    print("PASS: /v3/responses openai max -> enabled + effort=max")


# ── chat/completions path: prepare_request ──────────────────────────────────

def test_chatcompletions_request_builds_thinking_and_reasoning_effort():
    p = _provider()
    req = _request(effort="minimal")  # openai minimal -> doubao low
    data = p.prepare_request(req)
    assert data.get("thinking") == {"type": "enabled"}, data.get("thinking")
    assert data.get("reasoning_effort") == "low", data.get("reasoning_effort")
    # raw openai effort must not leak
    assert data.get("reasoning_effort") != "minimal"
    print("PASS: /v3/chat/completions builds thinking=enabled + reasoning_effort=low")


def test_chatcompletions_request_none_disables():
    p = _provider()
    data = p.prepare_request(_request(effort="none"))
    assert data.get("thinking") == {"type": "disabled"}, data.get("thinking")
    assert "reasoning_effort" not in data, data.get("reasoning_effort")
    print("PASS: /v3/chat/completions openai none -> thinking disabled")


def test_chatcompletions_request_max_and_xhigh():
    p = _provider()
    d_max = p.prepare_request(_request(effort="max"))
    assert d_max["thinking"] == {"type": "enabled"}
    assert d_max["reasoning_effort"] == "max", d_max
    d_xh = p.prepare_request(_request(effort="xhigh"))
    assert d_xh["thinking"] == {"type": "enabled"}
    assert d_xh["reasoning_effort"] == "xhigh", d_xh  # chat path keeps xhigh
    print("PASS: /v3/chat/completions max->max, xhigh->xhigh")


# ── reasoning input item in multi-turn ─────────────────────────────────────

def test_reasoning_only_message_emits_reasoning_input_item():
    """An ASSISTANT message with only reasoning_content (no text/tool_calls)
    must produce a ``{"type": "reasoning", ...}`` input item, not be dropped."""
    p = _provider()
    req = ChatRequest(
        model="doubao-seed-2-0-pro-260215",
        messages=[
            Message(role=MessageRole.USER, content="hello"),
            Message(role=MessageRole.ASSISTANT, reasoning_content="I thought about this."),
            Message(role=MessageRole.USER, content="continue"),
        ],
    )
    req.metadata = {}
    data = p._prepare_responses_request(req)
    input_items = data["input"]

    # Find the reasoning item
    reasoning_items = [it for it in input_items if it.get("type") == "reasoning"]
    assert len(reasoning_items) == 1, f"Expected 1 reasoning item, got {len(reasoning_items)}: {input_items}"
    r = reasoning_items[0]
    assert r["summary"][0]["type"] == "summary_text"
    assert r["summary"][0]["text"] == "I thought about this."
    print("PASS: reasoning-only assistant message → reasoning input item")


def test_reasoning_plus_text_message_emits_both_items():
    """An ASSISTANT message with reasoning_content AND text content must
    produce both a reasoning item and a message item."""
    p = _provider()
    req = ChatRequest(
        model="doubao-seed-2-0-pro-260215",
        messages=[
            Message(role=MessageRole.USER, content="hello"),
            Message(role=MessageRole.ASSISTANT, content="Here is my answer.",
                    reasoning_content="Let me think..."),
            Message(role=MessageRole.USER, content="thanks"),
        ],
    )
    req.metadata = {}
    data = p._prepare_responses_request(req)
    input_items = data["input"]

    reasoning_items = [it for it in input_items if it.get("type") == "reasoning"]
    message_items = [it for it in input_items
                     if it.get("type") == "message" and it.get("role") == "assistant"]
    assert len(reasoning_items) == 1, f"Expected 1 reasoning item: {input_items}"
    assert len(message_items) == 1, f"Expected 1 assistant message item: {input_items}"
    assert reasoning_items[0]["summary"][0]["text"] == "Let me think..."
    print("PASS: reasoning + text → reasoning item + message item")


def test_shared_responses_format_emits_reasoning_item():
    """The shared _message_to_responses_items must also emit reasoning items
    for providers that use build_responses_request (Azure, etc.)."""
    from app.providers._responses_format import _message_to_responses_items

    msg = Message(role=MessageRole.ASSISTANT, reasoning_content="Deep thought.")
    items = _message_to_responses_items(msg)
    reasoning_items = [it for it in items if it.get("type") == "reasoning"]
    assert len(reasoning_items) == 1, f"Expected 1 reasoning item: {items}"
    assert reasoning_items[0]["summary"][0]["text"] == "Deep thought."
    print("PASS: shared _message_to_responses_items emits reasoning item")


if __name__ == "__main__":
    test_resolve_off_when_none()
    test_resolve_enabled_mapping()
    test_resolve_responses_clamps_xhigh()
    test_resolve_no_effort_support_thinking_auto()
    test_resolve_no_effort_no_support()
    test_responses_request_builds_thinking_and_reasoning()
    test_responses_request_none_disables()
    test_responses_request_max()
    test_chatcompletions_request_builds_thinking_and_reasoning_effort()
    test_chatcompletions_request_none_disables()
    test_chatcompletions_request_max_and_xhigh()
    test_reasoning_only_message_emits_reasoning_input_item()
    test_reasoning_plus_text_message_emits_both_items()
    test_shared_responses_format_emits_reasoning_item()
    print("\nAll Volcengine reasoning mapping tests passed.")
