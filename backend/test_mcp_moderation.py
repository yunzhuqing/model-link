"""
MCP moderation module tests.

Verifies the GetModerationResult request shape (URL/host/payload/signing)
and error handling without touching the network or database.

Run: cd backend && uv run pytest test_mcp_moderation.py -q
"""
import json

import pytest

from app.mcp.moderation import (
    MODERATION_API_HOST,
    VALID_TYPES,
    get_moderation_result,
)


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload, ensure_ascii=False)


class _FakeClient:
    """Stand-in for the shared httpx async client context manager."""

    def __init__(self, response):
        self._response = response
        self.last_request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None, **kwargs):
        self.last_request = {"url": url, "content": content, "headers": headers}
        return self._response


@pytest.mark.asyncio
async def test_get_moderation_result_success(monkeypatch):
    api_response = {
        "ResponseMetadata": {
            "RequestId": "202605071749433C22773B66621153AABB",
            "Action": "GetModerationResult",
            "Version": "2024-01-01",
            "Service": "ark",
            "Region": "cn-beijing",
        },
        "Result": {
            "block_reasons": [
                {
                    "label": "Copyright",
                    "sub_label": "IP",
                    "detail": "可能涉及版权限制，疑似相关内容：猪猪侠-猪猪侠",
                }
            ]
        },
    }
    fake = _FakeClient(_FakeResponse(200, api_response))
    monkeypatch.setattr("app.mcp.moderation.shared_client", lambda: fake)

    result = await get_moderation_result(
        id="t-123",
        type="task_id",
        access_key="AKLTfake",
        secret_key="sk-fake",
    )

    # Response content returned intact.
    assert result["Result"]["block_reasons"][0]["label"] == "Copyright"

    # Request shape: correct Action/Version/host, JSON body sent as raw bytes.
    req = fake.last_request
    assert "Action=GetModerationResult" in req["url"]
    assert "Version=2024-01-01" in req["url"]
    assert MODERATION_API_HOST in req["url"]
    assert json.loads(req["content"]) == {"Id": "t-123", "Type": "task_id"}

    # Signing headers: HMAC-SHA256 against the moderation host.
    headers = req["headers"]
    assert headers["Host"] == MODERATION_API_HOST
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"].startswith("HMAC-SHA256 ")
    assert "Credential=AKLTfake/" in headers["Authorization"]
    assert "X-Content-Sha256" in headers
    assert "X-Date" in headers


@pytest.mark.asyncio
async def test_get_moderation_result_invalid_type():
    with pytest.raises(ValueError, match="Invalid type"):
        await get_moderation_result(
            id="t-123", type="nope", access_key="a", secret_key="b"
        )


@pytest.mark.asyncio
async def test_get_moderation_result_empty_id():
    with pytest.raises(ValueError, match="non-empty"):
        await get_moderation_result(
            id="", type="task_id", access_key="a", secret_key="b"
        )


@pytest.mark.asyncio
async def test_get_moderation_result_error_status(monkeypatch):
    err_body = {"Error": {"Code": "SignatureDoesNotMatch", "Message": "bad sig"}}
    fake = _FakeClient(_FakeResponse(403, err_body))
    monkeypatch.setattr("app.mcp.moderation.shared_client", lambda: fake)

    with pytest.raises(RuntimeError, match="403"):
        await get_moderation_result(
            id="t-123", type="task_id", access_key="a", secret_key="b"
        )


def test_valid_types():
    assert set(VALID_TYPES) == {"asset_id", "task_id", "request_id"}


@pytest.mark.asyncio
async def test_resolve_creds_filters_by_group(monkeypatch):
    """group_id scopes the provider query: a provider in another group is invisible."""
    from app.mcp.moderation import resolve_volcengine_creds

    captured = {}

    class _Result:
        def scalars(self):
            class _S:
                def first(self):
                    return None

            return _S()

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _Result()

    # Strip the real DB session so we can inspect the compiled SQL.
    monkeypatch.setattr("app.get_db_session", lambda: _Session())
    # No env override — ensures the group filter, not env-provider branch, is taken.
    monkeypatch.setenv("MCP_VOLCENGINE_PROVIDER_ID", "")

    with pytest.raises(RuntimeError, match="group 9"):
        await resolve_volcengine_creds(group_id=9)

    compiled = str(captured["stmt"].compile(compile_kwargs={"literal_bindings": True}))
    assert "ml_providers.group_id" in compiled or "group_id" in compiled


@pytest.mark.asyncio
async def test_resolve_creds_rejects_provider_outside_group(monkeypatch):
    """provider_id pointing at another group's provider resolves to nothing."""
    from app.mcp.moderation import resolve_volcengine_creds

    class _Result:
        def scalars(self):
            class _S:
                def first(self):
                    return None

            return _S()

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, stmt):
            return _Result()

    monkeypatch.setattr("app.get_db_session", lambda: _Session())

    with pytest.raises(RuntimeError, match="group 5"):
        await resolve_volcengine_creds(provider_id=99, group_id=5)
