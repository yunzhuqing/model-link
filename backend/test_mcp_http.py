"""
MCP HTTP integration tests.

Verifies the /mcp routing in the composite ASGI and the apikey guard on the
MCP HTTP handler, without booting the full Quart lifespan (which needs
redis/etcd for leader election) and without touching the network or DB.

The guard delegates key validation to ``_verify_apikey`` (cache + DB). These
tests monkeypatch that function so no cache/DB is required.

Run: cd backend && uv run pytest test_mcp_http.py -q
"""
import asyncio

import pytest

from app.mcp import server as mcp_server
from app.mcp.server import MCP_HTTP_PATH, make_guarded_asgi
from app.mcp.asgi import CompositeASGI


class _CapturedCall:
    def __init__(self):
        self.scope = None
        self.received = []

    async def __call__(self, scope, receive, send):
        self.scope = scope
        async for msg in self._drain(receive):
            self.received.append(msg)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def _drain(self, receive):
        while True:
            msg = await receive()
            if msg.get("type") == "http.request":
                if not msg.get("more_body", False):
                    yield msg
                    return
                yield msg


async def _invoke(asgi, path, headers=None, method="POST", body=b""):
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "headers": headers or [],
        "query_string": b"",
        "http_version": "1.1",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("1.2.3.4", 5),
    }
    await asgi(scope, receive, send)
    return sent


def _status(sent) -> int:
    return sent[0]["status"]


def _body(sent) -> str:
    return sent[1]["body"].decode()


def _patch_verify(monkeypatch, ok: bool, detail: str = "", group_id: int = 7):
    """Replace _verify_apikey with a stub returning (ok, detail, group_id, api_key)."""
    captured = {}

    async def _stub(raw_token):
        captured["token"] = raw_token
        return ok, detail, group_id if ok else None, raw_token if ok else None

    monkeypatch.setattr(mcp_server, "_verify_apikey", _stub)
    return captured


# ---------------------------------------------------------------------------
# apikey guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guard_rejects_missing_header(monkeypatch):
    # No Authorization header → token is empty → real _verify_apikey short-circuits
    # to (False, "missing api key") before touching cache/DB, so no patch needed.
    guard = make_guarded_asgi(_CapturedCall())
    sent = await _invoke(guard, MCP_HTTP_PATH)
    assert _status(sent) == 401
    assert "unauthorized" in _body(sent)


@pytest.mark.asyncio
async def test_guard_rejects_bad_or_inactive_key(monkeypatch):
    _patch_verify(monkeypatch, ok=False, detail="api key is inactive")
    guard = make_guarded_asgi(_CapturedCall())
    sent = await _invoke(guard, MCP_HTTP_PATH,
                         headers=[(b"authorization", b"Bearer sk-bad")])
    assert _status(sent) == 401
    assert "unauthorized" in _body(sent)


@pytest.mark.asyncio
async def test_guard_accepts_valid_key_and_delegates(monkeypatch):
    captured = _patch_verify(monkeypatch, ok=True, group_id=42)
    inner = _CapturedCall()
    guard = make_guarded_asgi(inner)
    sent = await _invoke(
        guard, MCP_HTTP_PATH,
        headers=[(b"authorization", b"Bearer sk-valid-1")],
    )
    assert _status(sent) == 200
    assert inner.scope is not None  # underlying handler was reached
    # Bearer prefix stripped before passing to _verify_apikey.
    assert captured["token"] == "sk-valid-1"
    # group_id from the verified apikey is injected into the ASGI scope so that
    # MCP tools can scope provider lookups to the caller's group.
    assert inner.scope.get("mcp_group_id") == 42


@pytest.mark.asyncio
async def test_guard_rejects_non_mcp_path(monkeypatch):
    _patch_verify(monkeypatch, ok=True)
    guard = make_guarded_asgi(_CapturedCall())
    sent = await _invoke(guard, "/other", headers=[(b"authorization", b"Bearer sk-valid")])
    assert _status(sent) == 404


# ---------------------------------------------------------------------------
# Composite ASGI routing
# ---------------------------------------------------------------------------

def _import_composite():
    # Side-effect-free import (does not construct the Quart app).
    return CompositeASGI


@pytest.mark.asyncio
async def test_composite_routes_mcp_to_handler(monkeypatch):
    _patch_verify(monkeypatch, ok=True)
    _CompositeASGI = _import_composite()

    class _FakeQuart:
        async def __call__(self, scope, receive, send):
            await send({"type": "http.response.start", "status": 418, "headers": []})
            await send({"type": "http.response.body", "body": b"quart"})

    captured = _CapturedCall()
    composite = _CompositeASGI(_FakeQuart(), make_guarded_asgi(captured))

    # /mcp with valid key → MCP handler reached (200).
    sent = await _invoke(
        composite, MCP_HTTP_PATH,
        headers=[(b"authorization", b"Bearer sk-valid")],
    )
    assert _status(sent) == 200
    assert captured.scope is not None

    # /api/foo → Quart (418), MCP handler untouched.
    captured2 = _CapturedCall()
    composite2 = _CompositeASGI(_FakeQuart(), make_guarded_asgi(captured2))
    sent = await _invoke(composite2, "/api/foo")
    assert _status(sent) == 418
    assert captured2.scope is None


@pytest.mark.asyncio
async def test_composite_forwards_lifespan_to_quart():
    _CompositeASGI = _import_composite()

    class _FakeQuart:
        def __init__(self):
            self.events = []

        async def __call__(self, scope, receive, send):
            assert scope["type"] == "lifespan"
            msg = await receive()
            self.events.append(msg["type"])
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            else:
                await send({"type": "lifespan.shutdown.complete"})

    quart = _FakeQuart()
    composite = _CompositeASGI(quart, make_guarded_asgi(_CapturedCall()))

    inbox = asyncio.Queue()

    async def receive():
        return await inbox.get()

    sent = []

    async def send(msg):
        sent.append(msg)

    await inbox.put({"type": "lifespan.startup"})
    await composite({"type": "lifespan"}, receive, send)
    await inbox.put({"type": "lifespan.shutdown"})
    await composite({"type": "lifespan"}, receive, send)

    assert quart.events == ["lifespan.startup", "lifespan.shutdown"]
    assert sent[0]["type"] == "lifespan.startup.complete"
    assert sent[1]["type"] == "lifespan.shutdown.complete"
