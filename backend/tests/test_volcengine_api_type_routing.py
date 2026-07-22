"""
Regression test: VolcengineProvider routes chat/stream_chat to
/v3/chat/completions or /v3/responses based on the model's api_type.

运行: cd backend && uv run python test_volcengine_api_type_routing.py
"""
import asyncio
from typing import Any

from app.providers import ProviderConfig
from app.providers.volcengine.base import VolcengineProvider
from app.abstraction.chat import ChatRequest, ChatResponse, UsageInfo, FinishReason
from app.abstraction.messages import Message, MessageRole
from app.abstraction.streaming import StreamChunk, FinishReason as SFR


def _make_provider(api_type: str | None) -> VolcengineProvider:
    cfg = ProviderConfig(name="volcengine", api_key="sk-test", base_url=None)
    p = VolcengineProvider(cfg)
    p._model_api_type = api_type
    return p


def _make_request() -> ChatRequest:
    return ChatRequest(
        model="doubao-seed-2-0-pro-260215",
        messages=[Message(role=MessageRole.USER, content="hi")],
    )


def test_routing_decision():
    cases = {
        None: False,                       # default doubao models → responses
        "": False,
        "responses": False,                # explicit responses → responses
        "chat_completions": True,          # opt-in chat/completions
        "chat_completions,messages": True,
        "chat_completions,responses": False,  # responses takes precedence
        "messages": False,
    }
    for api_type, expected in cases.items():
        p = _make_provider(api_type)
        got = p._uses_chat_completions_api()
        assert got is expected, (
            f"api_type={api_type!r}: expected {expected}, got {got}"
        )
    print("PASS: _uses_chat_completions_api routing decisions correct")


def _stub_super_chat(self, request):
    """Fake OpenAIProvider.chat — records the call and returns a marker."""
    self._super_chat_called = True
    self._super_chat_request_model = request.model
    return ChatResponse(
        id="chatcmpl-openai", model=request.model, choices=[], usage=UsageInfo(),
    )


async def _stub_super_chat_async(self, request):
    return _stub_super_chat(self, request)


async def _stub_chat_responses(self, request):
    self._responses_chat_called = True
    return ChatResponse(
        id="resp-volc", model=request.model, choices=[], usage=UsageInfo(),
    )


async def _stub_stream_chat_responses(self, request):
    self._responses_stream_called = True
    yield StreamChunk(id="resp-stream", model=request.model, delta_content="x",
                     finish_reason=SFR.STOP)


async def _stub_super_stream_chat(self, request):
    self._super_stream_called = True
    yield StreamChunk(id="openai-stream", model=request.model, delta_content="y",
                      finish_reason=SFR.STOP)


def test_chat_routes_to_responses_by_default(monkeypatch=None):
    p = _make_provider(None)  # default → responses
    # Force both stubs so we can detect which path was taken.
    p._super_chat_called = False
    p._responses_chat_called = False
    VolcengineProvider._chat_responses = _stub_chat_responses
    # super().chat is OpenAIProvider.chat; monkeypatch on OpenAIProvider
    from app.providers.openai_provider import OpenAIProvider
    OpenAIProvider.chat = _stub_super_chat_async
    try:
        resp = asyncio.run(p.chat(_make_request()))
        assert p._responses_chat_called, "default should route to _chat_responses"
        assert not p._super_chat_called, "default must NOT use super().chat()"
        assert resp.id == "resp-volc"
    finally:
        pass
    print("PASS: default (api_type=None) → /v3/responses")


def test_chat_routes_to_completions_when_opt_in():
    p = _make_provider("chat_completions")  # opt-in → chat/completions
    p._super_chat_called = False
    p._responses_chat_called = False
    from app.providers.openai_provider import OpenAIProvider
    OpenAIProvider.chat = _stub_super_chat_async
    resp = asyncio.run(p.chat(_make_request()))
    assert p._super_chat_called, "opt-in should route to super().chat()"
    assert not p._responses_chat_called, "opt-in must NOT use _chat_responses"
    assert resp.id == "chatcmpl-openai"
    print("PASS: api_type=chat_completions → /v3/chat/completions")


def test_stream_routes_correctly():
    from app.providers.openai_provider import OpenAIProvider
    OpenAIProvider.stream_chat = _stub_super_stream_chat
    VolcengineProvider._stream_chat_responses = _stub_stream_chat_responses

    # default → responses stream
    p = _make_provider(None)
    p._super_stream_called = False
    p._responses_stream_called = False
    async def _run_default():
        async for _ in p.stream_chat(_make_request()):
            pass
    asyncio.run(_run_default())
    assert p._responses_stream_called and not p._super_stream_called

    # opt-in → openai stream
    p = _make_provider("chat_completions")
    p._super_stream_called = False
    p._responses_stream_called = False
    async def _run_optin():
        async for _ in p.stream_chat(_make_request()):
            pass
    asyncio.run(_run_optin())
    assert p._super_stream_called and not p._responses_stream_called
    print("PASS: stream_chat routes by api_type")


def test_base_url_normalized_to_v3():
    p = _make_provider(None)
    assert p.config.base_url.endswith("/v3"), p.config.base_url
    # chat/completions URL would be base_url + /chat/completions
    assert p.config.base_url.rstrip("/").endswith("/api/v3") or "/v3" in p.config.base_url
    print("PASS: base_url normalized to /v3 ->", p.config.base_url)


if __name__ == "__main__":
    test_routing_decision()
    test_chat_routes_to_responses_by_default()
    test_chat_routes_to_completions_when_opt_in()
    test_stream_routes_correctly()
    test_base_url_normalized_to_v3()
    print("\nAll Volcengine api_type routing tests passed.")
