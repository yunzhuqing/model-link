"""
Vidu image generation provider tests.

Verifies the two-step task flow (submit → poll), model mapping, request body
construction, response parsing, and failure handling without touching the
network or database.

Run: cd backend && uv run pytest tests/test_vidu_image_generation.py -q
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.abstraction.chat import ChatRequest
from app.abstraction.messages import Message, MessageRole
from app.providers import ViduProvider
from app.providers.base import ProviderConfig, UpstreamProviderError
from app.providers.vidu.image_generation import (
    VIDU_MODEL_MAP,
    execute_vidu_image_generation,
    is_vidu_image_model,
)
from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.abstraction.chat import ChatChoice, ChatResponse, FinishReason, UsageInfo


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload, ensure_ascii=False)


class _FakeClient:
    """Stand-in for the shared httpx async client context manager."""

    def __init__(self, responses: List[Any]):
        self._responses = list(responses)
        self.requests: List[Dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, **kwargs):
        self.requests.append({"method": "POST", "url": url, "json": json, "headers": headers})
        return self._responses.pop(0)

    async def get(self, url, headers=None, **kwargs):
        self.requests.append({"method": "GET", "url": url, "headers": headers})
        return self._responses.pop(0)


def _submit_response(task_id: str = "973115155577610240") -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "state": "created",
        "model": "viduq2",
        "images": [],
        "prompt": "a cat",
        "seed": 0,
        "aspect_ratio": "1:1",
        "resolution": "4K",
        "payload": "",
        "credits": 12,
        "created_at": "2025-08-07T09:53:22.083033428Z",
    }


def _poll_response(state: str, urls: Optional[List[str]] = None) -> Dict[str, Any]:
    creations = []
    for url in urls or []:
        creations.append({
            "id": "973115584755580928",
            "url": url,
            "cover_url": url.replace(".png", "-cover.png"),
            "video": {"duration": 0, "fps": 0, "resolution": None},
            "attachments": [],
        })
    return {
        "state": state,
        "err_code": "" if state == "success" else "E1001",
        "err_msg": "" if state == "success" else "task failed",
        "creations": creations,
        "id": "973115155577610240",
        "progress": 100 if state == "success" else 50,
        "type": "reference2image",
        "model": "viduq2",
    }


def _chat_request(model: str, prompt: str = "a cat", metadata: Optional[dict] = None) -> ChatRequest:
    return ChatRequest(
        messages=[Message(role=MessageRole.USER, content=prompt)],
        model=model,
        metadata=metadata or {},
    )


@pytest.mark.asyncio
async def test_model_mapping_table():
    assert VIDU_MODEL_MAP == {
        "gpt-image-2": "viduimage-2",
        "gemini-2.5-flash-image": "q2-fast",
        "gemini-3-pro-image-preview": "q2-pro",
        "gemini-3.1-flash-image-preview": "q3-fast",
        "viduq1": "viduq1",
        "viduq2": "viduq2",
        "viduimage-2": "viduimage-2",
        "q2-fast": "q2-fast",
        "q2-pro": "q2-pro",
        "q3-fast": "q3-fast",
    }
    assert is_vidu_image_model("gpt-image-2")
    assert is_vidu_image_model("GEMINI-2.5-FLASH-IMAGE")
    assert is_vidu_image_model("viduq2")
    assert is_vidu_image_model("viduq1")
    assert is_vidu_image_model("q2-fast")
    assert is_vidu_image_model("q3-fast")
    assert is_vidu_image_model("viduimage-2")
    assert not is_vidu_image_model("gpt-4o")


@pytest.mark.asyncio
async def test_execute_vidu_image_generation_success(monkeypatch):
    image_url = "https://prod-ss-vidu.s3.cn-northwest-1.amazonaws.com.cn/image.png"
    fake = _FakeClient([
        _FakeResponse(200, _submit_response()),
        _FakeResponse(200, _poll_response("processing", [])),
        _FakeResponse(200, _poll_response("success", [image_url])),
    ])
    monkeypatch.setattr("app.providers.vidu.image_generation.shared_client", lambda: fake)

    response = await execute_vidu_image_generation(
        api_key="vda_test_key",
        base_url="https://api.vidu.cn",
        model="gpt-image-2",
        messages=[Message(role=MessageRole.USER, content="a cat")],
        metadata={
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "resolution": "4K",
            "quality": "low",
            "response_format": "url",
        },
    )

    # Submit request: correct URL, model mapping, and request body
    submit = fake.requests[0]
    assert submit["method"] == "POST"
    assert submit["url"] == "https://api.vidu.cn/ent/v2/reference2image"
    assert submit["json"]["model"] == "viduimage-2"
    assert submit["json"]["prompt"] == "a cat"
    assert submit["json"]["aspect_ratio"] == "1:1"
    assert submit["json"]["resolution"] == "4K"
    assert submit["json"]["quality"] == "low"
    assert submit["headers"]["Authorization"] == "Bearer vda_test_key"

    # Poll requests hit the task detail endpoint
    assert fake.requests[1]["method"] == "GET"
    assert fake.requests[1]["url"] == "https://api.vidu.cn/ent/v2/tasks/973115155577610240/creations"
    assert fake.requests[2]["method"] == "GET"

    # Parsed response contains image_generation_call items
    items = json.loads(response.choices[0].message.get_text_content())
    assert items == [
        {"type": "image_generation_call", "status": "completed", "result": image_url}
    ]
    assert response.usage.extra["output_image_number"] == 1
    assert response.usage.extra["output_image_resolution"] == "4K"
    assert response.usage.extra["output_image_aspect"] == "1:1"
    assert response.usage.extra["_task_id"] == "973115155577610240"


@pytest.mark.asyncio
async def test_execute_vidu_image_generation_failure(monkeypatch):
    fake = _FakeClient([
        _FakeResponse(200, _submit_response()),
        _FakeResponse(200, _poll_response("failed", [])),
    ])
    monkeypatch.setattr("app.providers.vidu.image_generation.shared_client", lambda: fake)

    with pytest.raises(UpstreamProviderError) as exc_info:
        await execute_vidu_image_generation(
            api_key="vda_test_key",
            base_url="https://api.vidu.cn",
            model="gemini-2.5-flash-image",
            messages=[Message(role=MessageRole.USER, content="a cat")],
            metadata={},
        )
    # 完整 Vidu 返回信息都放入 message，err_code 作为 error_type
    err = exc_info.value
    assert err.error_type == "E1001"
    assert "task failed" in str(err)
    assert '"state": "failed"' in str(err)
    assert '"err_code": "E1001"' in str(err)


@pytest.mark.asyncio
async def test_execute_vidu_submit_http_error_includes_full_body(monkeypatch):
    vidu_error_body = {
        "code": "CreditInsufficient",
        "message": "insufficient credits",
        "metadata": {"trace_id": "af80f3aa9ff1d74e9a0d6aa2af923ffe"},
        "reason": "CreditInsufficient",
    }
    fake = _FakeClient([_FakeResponse(402, vidu_error_body)])
    monkeypatch.setattr("app.providers.vidu.image_generation.shared_client", lambda: fake)

    with pytest.raises(UpstreamProviderError) as exc_info:
        await execute_vidu_image_generation(
            api_key="vda_test_key",
            base_url="https://api.vidu.cn",
            model="gemini-3.1-flash-image-preview",
            messages=[Message(role=MessageRole.USER, content="a cat")],
            metadata={},
        )

    err = exc_info.value
    assert err.status_code == 402
    assert err.error_type == "CreditInsufficient"
    assert err.request_id == "af80f3aa9ff1d74e9a0d6aa2af923ffe"
    # 完整 Vidu 响应体都放在 message 中
    assert "insufficient credits" in str(err)
    assert "CreditInsufficient" in str(err)
    assert "af80f3aa9ff1d74e9a0d6aa2af923ffe" in str(err)


@pytest.mark.asyncio
async def test_execute_vidu_image_generation_unknown_model(monkeypatch):
    fake = _FakeClient([_FakeResponse(200, _submit_response())])
    monkeypatch.setattr("app.providers.vidu.image_generation.shared_client", lambda: fake)

    with pytest.raises(ValueError, match="Unknown Vidu image generation model"):
        await execute_vidu_image_generation(
            api_key="vda_test_key",
            base_url="https://api.vidu.cn",
            model="gpt-4o",
            messages=[Message(role=MessageRole.USER, content="a cat")],
            metadata={},
        )
    assert fake.requests == []


@pytest.mark.asyncio
async def test_vidu_provider_chat_routes_image_models(monkeypatch):
    image_url = "https://prod-ss-vidu.s3.cn-northwest-1.amazonaws.com.cn/image.png"
    fake = _FakeClient([
        _FakeResponse(200, _submit_response()),
        _FakeResponse(200, _poll_response("success", [image_url])),
    ])
    monkeypatch.setattr("app.providers.vidu.image_generation.shared_client", lambda: fake)

    provider = ViduProvider(ProviderConfig(name="Vidu", api_key="vda_test_key"))

    response = await provider.chat(_chat_request("gemini-3-pro-image-preview"))

    assert fake.requests[0]["json"]["model"] == "q2-pro"
    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["result"] == image_url


@pytest.mark.asyncio
async def test_vidu_native_model_name_passthrough(monkeypatch):
    image_url = "https://prod-ss-vidu.s3.cn-northwest-1.amazonaws.com.cn/image.png"
    fake = _FakeClient([
        _FakeResponse(200, _submit_response()),
        _FakeResponse(200, _poll_response("success", [image_url])),
    ])
    monkeypatch.setattr("app.providers.vidu.image_generation.shared_client", lambda: fake)

    provider = ViduProvider(ProviderConfig(name="Vidu", api_key="vda_test_key"))

    response = await provider.chat(_chat_request("viduq2"))

    # 原生模型名直接透传，不经过翻译
    assert fake.requests[0]["json"]["model"] == "viduq2"
    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["result"] == image_url


@pytest.mark.asyncio
async def test_vidu_provider_rejects_non_image_models(monkeypatch):
    fake = _FakeClient([])
    monkeypatch.setattr("app.providers.vidu.image_generation.shared_client", lambda: fake)

    provider = ViduProvider(ProviderConfig(name="Vidu", api_key="vda_test_key"))

    with pytest.raises(ValueError, match="only supports image generation"):
        await provider.chat(_chat_request("gpt-4o"))
    assert fake.requests == []


def _vidu_chat_response(model: str, image_url: str) -> ChatResponse:
    """Build the ChatResponse shape produced by _parse_vidu_image_response."""
    items = json.dumps(
        [{"type": "image_generation_call", "status": "completed", "result": image_url}],
        ensure_ascii=False,
    )
    return ChatResponse(
        id="img_test",
        model=model,
        choices=[ChatChoice(
            index=0,
            message=Message(role=MessageRole.ASSISTANT, content=items),
            finish_reason=FinishReason.STOP,
        )],
        usage=UsageInfo(
            prompt_tokens=0,
            completion_tokens=1,
            total_tokens=1,
            extra={"output_image_number": 1, "_response_format": "url"},
        ),
        provider="vidu",
    )


@pytest.mark.parametrize("model", ["q3-fast", "q2-fast", "q2-pro", "viduq1", "viduq2", "viduimage-2"])
def test_vidu_image_generation_adapter_output_format(model):
    """Vidu image responses must render image_generation_call output items,
    not the raw JSON string as output_text."""
    image_url = "https://prod-ss-vidu.s3.cn-northwest-1.amazonaws.com.cn/image.png"
    result = OpenAIResponsesAdapter().format_response(
        _vidu_chat_response(model, image_url)
    )

    assert result["model"] == model
    assert result["status"] == "completed"
    assert len(result["output"]) == 1
    item = result["output"][0]
    assert item["type"] == "image_generation_call"
    assert item["status"] == "completed"
    assert item["result"] == image_url
    assert result["response_format"] == "url"
