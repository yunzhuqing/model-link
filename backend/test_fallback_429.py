"""
Tests for 429 rate-limit fallback across multiple provider candidates.
"""
import asyncio
import pytest

from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.messages import Message, MessageRole
from app.abstraction.streaming import StreamChunk
from app.middleware.gateway_service import GatewayService, ProviderError, GatewayServiceError
from app.providers.base import UpstreamProviderError
from app.request_context import ResolvedModelData
from app.rate_limiter import RateLimitResult


def _resolved(provider_id, provider_name, model_name="m1", provider_instance=None):
    return ResolvedModelData(
        provider_id=provider_id,
        provider_name=provider_name,
        provider_type="openai",
        model_id=provider_id,
        model_alias=model_name,
        model_real_name=model_name,
        provider_instance=provider_instance,
    )


class _FakeProvider:
    """Minimal stand-in for a BaseProvider used only by these tests."""

    def __init__(self, name, *, chat_exc=None, chat_resp=None, stream_exc=None, stream_chunks=None):
        self.name = name
        self._chat_exc = chat_exc
        self._chat_resp = chat_resp
        self._stream_exc = stream_exc
        self._stream_chunks = stream_chunks
        self.tracer = None
        self._model_api_type = None

    async def chat(self, request):
        if self._chat_exc:
            raise self._chat_exc
        return self._chat_resp

    async def stream_chat(self, request):
        for c in (self._stream_chunks or []):
            yield c
        if self._stream_exc:
            raise self._stream_exc


def _resp(model="m1"):
    return ChatResponse(
        id="r1", model=model, choices=[],
        usage=UsageInfo(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


def _request(stream=False):
    return ChatRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="m1", stream=stream)


def _make_service():
    svc = GatewayService.__new__(GatewayService)
    return svc


def _patch_url_conversion(svc, monkeypatch):
    monkeypatch.setattr(svc, "_convert_image_urls_to_base64", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(svc, "_convert_video_urls_to_base64", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(svc, "_resolve_file_ids", lambda *a, **k: asyncio.sleep(0))


@pytest.mark.asyncio
async def test_chat_falls_back_on_429(monkeypatch):
    svc = _make_service()
    _patch_url_conversion(svc, monkeypatch)

    p1 = _FakeProvider("A", chat_exc=UpstreamProviderError("rl", status_code=429))
    p2 = _FakeProvider("B", chat_resp=_resp())
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    resp = await svc.chat(primary, _request())
    assert resp.model == "m1"
    # resolved should now reflect the successful candidate
    assert primary.provider_name == "B"
    assert primary.provider_id == 2


@pytest.mark.asyncio
async def test_chat_exhausts_after_three_attempts(monkeypatch):
    svc = _make_service()
    _patch_url_conversion(svc, monkeypatch)

    p1 = _FakeProvider("A", chat_exc=UpstreamProviderError("rl", status_code=429))
    p2 = _FakeProvider("B", chat_exc=UpstreamProviderError("rl", status_code=429))
    p3 = _FakeProvider("C", chat_exc=UpstreamProviderError("rl", status_code=429))
    p4 = _FakeProvider("D", chat_resp=_resp())  # 4th — should NOT be reached (max 3)
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [
        _resolved(2, "B", provider_instance=p2),
        _resolved(3, "C", provider_instance=p3),
        _resolved(4, "D", provider_instance=p4),
    ]

    with pytest.raises(ProviderError) as ei:
        await svc.chat(primary, _request())
    assert ei.value.status_code == 429


@pytest.mark.asyncio
async def test_chat_non_429_not_retried(monkeypatch):
    svc = _make_service()
    _patch_url_conversion(svc, monkeypatch)

    p1 = _FakeProvider("A", chat_exc=UpstreamProviderError("bad", status_code=500))
    p2 = _FakeProvider("B", chat_resp=_resp())
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    with pytest.raises(ProviderError) as ei:
        await svc.chat(primary, _request())
    assert ei.value.status_code == 500
    assert ei.value.provider_name == "A"


@pytest.mark.asyncio
async def test_stream_falls_back_on_429_before_first_chunk(monkeypatch):
    svc = _make_service()
    _patch_url_conversion(svc, monkeypatch)

    p1 = _FakeProvider("A", stream_exc=UpstreamProviderError("rl", status_code=429))
    p2 = _FakeProvider("B", stream_chunks=[StreamChunk(id="c1", model="m1", delta_content="hi")])
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    gen = await svc.stream_chat(primary, _request(stream=True))
    chunks = [c async for c in gen]
    assert any(c.delta_content == "hi" for c in chunks)
    assert primary.provider_name == "B"


@pytest.mark.asyncio
async def test_stream_does_not_retry_after_chunks_sent(monkeypatch):
    svc = _make_service()
    _patch_url_conversion(svc, monkeypatch)

    p1 = _FakeProvider("A", stream_chunks=[StreamChunk(id="c1", model="m1", delta_content="x")],
                       stream_exc=UpstreamProviderError("rl", status_code=429))
    p2 = _FakeProvider("B", stream_chunks=[StreamChunk(id="c2", model="m1", delta_content="y")])
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    gen = await svc.stream_chat(primary, _request(stream=True))
    with pytest.raises(ProviderError) as ei:
        async for _ in gen:
            pass
    assert ei.value.status_code == 429
    assert ei.value.provider_name == "A"


# ── Rate-limit pre-check fallback tests ──────────────────────────────────────

class _FakeRateLimiter:
    """Stand-in for AsyncRateLimiter that returns scripted results per candidate."""

    def __init__(self, results_by_model_id):
        # results_by_model_id: {model_id: RateLimitResult}
        self._results = results_by_model_id
        self.calls = []

    async def check_and_reserve(self, *, model_id, **kwargs):
        self.calls.append(model_id)
        return self._results.get(model_id, RateLimitResult(allowed=True))


class _FakeWsRL:
    """Stand-in for a WorkspaceRateLimit ORM row."""
    def __init__(self, rpm=None, tpm=None, provider_type="openai", provider_id=None):
        self.rpm = rpm
        self.tpm = tpm
        self.provider_type = provider_type
        self.provider_id = provider_id


@pytest.mark.asyncio
async def test_rate_limit_falls_back_on_provider_scoped_ws_limit(monkeypatch):
    """When the provider-scoped workspace rate limit (供应商模型限流) is hit,
    the next candidate should be tried."""
    svc = _make_service()

    p1 = _FakeProvider("A")
    p2 = _FakeProvider("B")
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    # Stub _lookup_workspace_rate_limit: provider 1 has a scoped limit (hit),
    # provider 2 has a scoped limit (passes).
    async def fake_lookup(ws_id, cand, model_name):
        if cand.provider_id == 1:
            return _FakeWsRL(rpm=10, provider_id=1)
        return _FakeWsRL(rpm=10, provider_id=2)
    monkeypatch.setattr(svc, "_lookup_workspace_rate_limit", fake_lookup)

    limiter = _FakeRateLimiter({
        1: RateLimitResult(allowed=False, detail="Workspace RPM limit exceeded", limit_level="workspace"),
        2: RateLimitResult(allowed=True),
    })

    chosen, info, err = await svc.check_rate_limit_with_fallback(
        primary, limiter, estimated_input_tokens=100,
        workspace_id=99, model_name="m1",
    )
    assert err is None
    assert chosen.provider_id == 2
    assert limiter.calls == [1, 2]


@pytest.mark.asyncio
async def test_rate_limit_no_retry_on_apikey_limit(monkeypatch):
    """API-key level limit is shared — must NOT retry."""
    svc = _make_service()

    p1 = _FakeProvider("A")
    p2 = _FakeProvider("B")
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    async def fake_lookup(ws_id, cand, model_name):
        return _FakeWsRL(rpm=10, provider_id=cand.provider_id)
    monkeypatch.setattr(svc, "_lookup_workspace_rate_limit", fake_lookup)

    limiter = _FakeRateLimiter({
        1: RateLimitResult(allowed=False, detail="API key RPM limit exceeded", limit_level="apikey"),
    })

    chosen, info, err = await svc.check_rate_limit_with_fallback(
        primary, limiter, estimated_input_tokens=100,
        workspace_id=99, model_name="m1", api_key_id=5,
    )
    assert err is not None
    assert "API key" in err
    # Must not have tried candidate 2
    assert 2 not in limiter.calls


@pytest.mark.asyncio
async def test_rate_limit_no_retry_on_shared_ws_limit(monkeypatch):
    """Workspace rate limit with provider_id=None (shared) must NOT retry."""
    svc = _make_service()

    p1 = _FakeProvider("A")
    p2 = _FakeProvider("B")
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    async def fake_lookup(ws_id, cand, model_name):
        # Shared limit (provider_id=None)
        return _FakeWsRL(rpm=10, provider_id=None)
    monkeypatch.setattr(svc, "_lookup_workspace_rate_limit", fake_lookup)

    limiter = _FakeRateLimiter({
        1: RateLimitResult(allowed=False, detail="Workspace RPM limit exceeded", limit_level="workspace"),
    })

    chosen, info, err = await svc.check_rate_limit_with_fallback(
        primary, limiter, estimated_input_tokens=100,
        workspace_id=99, model_name="m1",
    )
    assert err is not None
    assert 2 not in limiter.calls


@pytest.mark.asyncio
async def test_rate_limit_all_candidates_exhausted(monkeypatch):
    """When all candidates hit the provider-scoped limit, return the last error."""
    svc = _make_service()

    p1 = _FakeProvider("A")
    p2 = _FakeProvider("B")
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    async def fake_lookup(ws_id, cand, model_name):
        return _FakeWsRL(rpm=10, provider_id=cand.provider_id)
    monkeypatch.setattr(svc, "_lookup_workspace_rate_limit", fake_lookup)

    limiter = _FakeRateLimiter({
        1: RateLimitResult(allowed=False, detail="Provider A limit", limit_level="workspace"),
        2: RateLimitResult(allowed=False, detail="Provider B limit", limit_level="workspace"),
    })

    chosen, info, err = await svc.check_rate_limit_with_fallback(
        primary, limiter, estimated_input_tokens=100,
        workspace_id=99, model_name="m1",
    )
    assert err is not None
    assert "Provider B" in err
    assert limiter.calls == [1, 2]


@pytest.mark.asyncio
async def test_rate_limit_falls_back_on_model_level_limit(monkeypatch):
    """Model-level RPM limit (limit_level="model") is per model_id, so each
    provider candidate has its own counter — hitting it on one candidate
    should allow trying the next."""
    svc = _make_service()

    p1 = _FakeProvider("A")
    p2 = _FakeProvider("B")
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    async def fake_lookup(ws_id, cand, model_name):
        return None  # no workspace limits
    monkeypatch.setattr(svc, "_lookup_workspace_rate_limit", fake_lookup)

    limiter = _FakeRateLimiter({
        1: RateLimitResult(allowed=False, detail="RPM limit exceeded (limit: 1/min). Retry after 44s.", limit_level="model"),
        2: RateLimitResult(allowed=True),
    })

    chosen, info, err = await svc.check_rate_limit_with_fallback(
        primary, limiter, estimated_input_tokens=100,
        group_id=12, model_name="deepseek-v4-flash",
    )
    assert err is None
    assert chosen.provider_id == 2
    assert limiter.calls == [1, 2]


@pytest.mark.asyncio
async def test_rate_limit_model_level_all_exhausted(monkeypatch):
    """All candidates hit their model-level RPM limit — return last error."""
    svc = _make_service()

    p1 = _FakeProvider("A")
    p2 = _FakeProvider("B")
    primary = _resolved(1, "A", provider_instance=p1)
    primary.fallback_candidates = [_resolved(2, "B", provider_instance=p2)]

    async def fake_lookup(ws_id, cand, model_name):
        return None
    monkeypatch.setattr(svc, "_lookup_workspace_rate_limit", fake_lookup)

    limiter = _FakeRateLimiter({
        1: RateLimitResult(allowed=False, detail="RPM limit exceeded (limit: 1/min).", limit_level="model"),
        2: RateLimitResult(allowed=False, detail="RPM limit exceeded (limit: 1/min).", limit_level="model"),
    })

    chosen, info, err = await svc.check_rate_limit_with_fallback(
        primary, limiter, estimated_input_tokens=100,
        group_id=12, model_name="deepseek-v4-flash",
    )
    assert err is not None
    assert "RPM limit exceeded" in err
    assert limiter.calls == [1, 2]
