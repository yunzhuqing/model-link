"""
TencentLive (AIGC Model Hub) image generation provider tests.

Verifies the Gemini-compatible request body construction (text-to-image,
image-to-image via base64 / URL), response parsing (camelCase and snake_case),
error handling, provider routing, and streaming output without touching the
network or database.

Run: cd backend && uv run pytest tests/test_tencentlive_image_generation.py -q
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.abstraction.chat import ChatRequest
from app.abstraction.messages import ContentBlock, Message, MessageRole
from app.providers import TencentLiveProvider
from app.providers.base import ProviderConfig, UpstreamProviderError
from app.providers.tencentlive.image_generation import (
    TENCENTLIVE_GEM_IMAGE_PATH,
    TENCENTLIVE_DEFAULT_BASE_URL,
    TENCENTLIVE_IMAGE_MODELS,
    _build_request_body,
    _parse_gemini_image_response,
    execute_tencentlive_image_generation,
    is_tencentlive_image_model,
    stream_image_generation,
)


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
        self.requests.append({"method": "POST", "url": url, "json": json, "headers": headers, "kwargs": kwargs})
        return self._responses.pop(0)


def _gemini_response(
    data: str = "iVBORw0KGgoAAAANSUhEUgAA...",
    mime_type: str = "image/png",
    snake_case: bool = False,
) -> Dict[str, Any]:
    """Build a Gemini-compatible image generation response."""
    if snake_case:
        part = {"inline_data": {"mime_type": mime_type, "data": data}}
        usage = {
            "prompt_token_count": 10,
            "candidates_token_count": 20,
            "total_token_count": 30,
        }
    else:
        part = {"inlineData": {"mimeType": mime_type, "data": data}}
        usage = {
            "promptTokenCount": 10,
            "candidatesTokenCount": 20,
            "totalTokenCount": 30,
        }
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "here is your image"},
                        part,
                    ],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": usage,
    }


def _chat_request(model: str, prompt: str = "a cat", metadata: Dict[str, Any] | None = None, messages: List[Message] | None = None) -> ChatRequest:
    return ChatRequest(
        messages=messages or [Message(role=MessageRole.USER, content=prompt)],
        model=model,
        metadata=metadata or {},
    )


@pytest.mark.asyncio
async def test_model_detection():
    for model in TENCENTLIVE_IMAGE_MODELS:
        assert is_tencentlive_image_model(model)
    # New nano-banana models are passed through
    assert is_tencentlive_image_model("gemini-3.1-flash-image")
    assert is_tencentlive_image_model("GEMINI-2.5-FLASH-IMAGE")
    assert not is_tencentlive_image_model("gpt-4o")
    assert not is_tencentlive_image_model("gpt-image-2")


@pytest.mark.asyncio
async def test_build_request_body_text_to_image():
    body = _build_request_body(
        model="gemini-3.1-flash-image",
        prompt="A cinematic photo of a red panda",
        reference_images=[],
        metadata={"size": "1024x1024"},
    )

    assert body["model"] == "gemini-3.1-flash-image"
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "A cinematic photo of a red panda"}]}
    ]
    assert body["generationConfig"] == {
        "imageConfig": {"aspectRatio": "1:1", "imageSize": "1K"}
    }

    # Explicit aspect ratio + resolution
    body = _build_request_body(
        model="gemini-3.1-flash-image",
        prompt="a red panda",
        reference_images=[],
        metadata={"aspect_ratio": "16:9", "resolution": "2K"},
    )
    assert body["generationConfig"]["imageConfig"] == {
        "aspectRatio": "16:9",
        "imageSize": "2K",
    }

    # No size info → no generationConfig
    body = _build_request_body(
        model="gemini-3.1-flash-image",
        prompt="a red panda",
        reference_images=[],
        metadata={},
    )
    assert "generationConfig" not in body


@pytest.mark.asyncio
async def test_build_request_body_image_to_image_base64():
    body = _build_request_body(
        model="gemini-3.1-flash-image",
        prompt="change background to a beach at sunset",
        reference_images=["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."],
        metadata={"aspect_ratio": "1:1"},
    )

    assert body["contents"][0]["parts"] == [
        {"inline_data": {"mime_type": "image/png", "data": "iVBORw0KGgoAAAANSUhEUgAA..."}},
        {"text": "change background to a beach at sunset"},
    ]
    assert body["generationConfig"]["imageConfig"]["aspectRatio"] == "1:1"


@pytest.mark.asyncio
async def test_build_request_body_image_to_image_url():
    body = _build_request_body(
        model="gemini-3.1-flash-image",
        prompt="make it a watercolor painting",
        reference_images=["https://cdn.example.com/input.jpg"],
        metadata={},
    )

    assert body["contents"][0]["parts"] == [
        {"file_data": {"mime_type": "image/jpeg", "file_uri": "https://cdn.example.com/input.jpg"}},
        {"text": "make it a watercolor painting"},
    ]


@pytest.mark.asyncio
async def test_execute_tencentlive_image_generation_success(monkeypatch):
    fake = _FakeClient([_FakeResponse(200, _gemini_response())])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    response = await execute_tencentlive_image_generation(
        api_key="tl_test_key",
        base_url="https://aigc.example.com",
        model="gemini-3.1-flash-image",
        messages=[Message(role=MessageRole.USER, content="a red panda in Tokyo")],
        metadata={"size": "1024x1024"},
    )

    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert req["url"] == f"https://aigc.example.com{TENCENTLIVE_GEM_IMAGE_PATH}"
    assert req["headers"]["X-Api-Key"] == "tl_test_key"
    assert req["headers"]["Content-Type"] == "application/json"
    assert req["json"]["model"] == "gemini-3.1-flash-image"
    assert req["json"]["contents"][0]["parts"][0]["text"] == "a red panda in Tokyo"

    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["type"] == "image_generation_call"
    assert items[0]["status"] == "completed"
    assert items[0]["result"] == "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 20
    assert response.usage.total_tokens == 30
    assert response.usage.extra["output_image_number"] == 1
    assert response.provider == "tencentlive"


@pytest.mark.asyncio
async def test_execute_snake_case_response(monkeypatch):
    fake = _FakeClient([_FakeResponse(200, _gemini_response(snake_case=True))])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    response = await execute_tencentlive_image_generation(
        api_key="tl_test_key",
        base_url="https://aigc.example.com",
        model="gemini-3.1-flash-image",
        messages=[Message(role=MessageRole.USER, content="a cat")],
        metadata={},
    )

    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["result"] == "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."


@pytest.mark.asyncio
async def test_execute_file_data_response(monkeypatch):
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"file_data": {"mime_type": "image/png", "file_uri": "https://cdn.example.com/out.png"}},
                    ]
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 30},
    }
    fake = _FakeClient([_FakeResponse(200, payload)])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    response = await execute_tencentlive_image_generation(
        api_key="tl_test_key",
        base_url="https://aigc.example.com",
        model="gemini-3.1-flash-image",
        messages=[Message(role=MessageRole.USER, content="a cat")],
        metadata={},
    )

    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["result"] == "https://cdn.example.com/out.png"


@pytest.mark.asyncio
async def test_execute_upstream_error(monkeypatch):
    err_payload = {
        "error": {
            "code": "invalid_argument",
            "message": "bad request",
            "request_id": "req-123",
        }
    }
    fake = _FakeClient([_FakeResponse(400, err_payload)])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    with pytest.raises(UpstreamProviderError) as exc_info:
        await execute_tencentlive_image_generation(
            api_key="tl_test_key",
            base_url="https://aigc.example.com",
            model="gemini-3.1-flash-image",
            messages=[Message(role=MessageRole.USER, content="a cat")],
            metadata={},
        )

    err = exc_info.value
    assert err.status_code == 400
    assert err.error_type == "invalid_argument"
    assert err.request_id == "req-123"
    assert "bad request" in str(err)


@pytest.mark.asyncio
async def test_execute_unknown_model(monkeypatch):
    fake = _FakeClient([])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    with pytest.raises(ValueError, match="Unknown TencentLive image generation model"):
        await execute_tencentlive_image_generation(
            api_key="tl_test_key",
            base_url="https://aigc.example.com",
            model="gpt-4o",
            messages=[Message(role=MessageRole.USER, content="a cat")],
            metadata={},
        )
    assert fake.requests == []


@pytest.mark.asyncio
async def test_execute_default_base_url(monkeypatch):
    fake = _FakeClient([_FakeResponse(200, _gemini_response())])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    await execute_tencentlive_image_generation(
        api_key="tl_test_key",
        base_url="",
        model="gemini-3.1-flash-image",
        messages=[Message(role=MessageRole.USER, content="a cat")],
        metadata={},
    )
    assert fake.requests[0]["url"] == (
        f"{TENCENTLIVE_DEFAULT_BASE_URL}{TENCENTLIVE_GEM_IMAGE_PATH}"
    )


@pytest.mark.asyncio
async def test_provider_default_base_url():
    provider = TencentLiveProvider(ProviderConfig(name="TencentLive", api_key="tl_test_key"))
    assert provider.config.base_url == TENCENTLIVE_DEFAULT_BASE_URL


@pytest.mark.asyncio
async def test_provider_chat_routes_image_models(monkeypatch):
    fake = _FakeClient([_FakeResponse(200, _gemini_response())])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    provider = TencentLiveProvider(ProviderConfig(name="TencentLive", api_key="tl_test_key", base_url="https://aigc.example.com"))

    response = await provider.chat(_chat_request("gemini-3.1-flash-image"))

    assert fake.requests[0]["json"]["model"] == "gemini-3.1-flash-image"
    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["result"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_provider_chat_with_reference_images(monkeypatch):
    fake = _FakeClient([_FakeResponse(200, _gemini_response())])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    provider = TencentLiveProvider(ProviderConfig(name="TencentLive", api_key="tl_test_key", base_url="https://aigc.example.com"))
    messages = [
        Message(role=MessageRole.USER, content=[
            ContentBlock.from_image_url("https://cdn.example.com/input.jpg"),
            ContentBlock.from_text("make it a watercolor painting"),
        ])
    ]

    response = await provider.chat(_chat_request("gemini-3.1-flash-image", messages=messages))

    parts = fake.requests[0]["json"]["contents"][0]["parts"]
    assert parts[0] == {"file_data": {"mime_type": "image/jpeg", "file_uri": "https://cdn.example.com/input.jpg"}}
    assert parts[1] == {"text": "make it a watercolor painting"}
    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_provider_rejects_non_image_models(monkeypatch):
    fake = _FakeClient([])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    provider = TencentLiveProvider(ProviderConfig(name="TencentLive", api_key="tl_test_key", base_url="https://aigc.example.com"))

    with pytest.raises(ValueError, match="only supports image generation"):
        await provider.chat(_chat_request("gpt-4o"))
    assert fake.requests == []


@pytest.mark.asyncio
async def test_parse_gemini_response_skips_thought_parts():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "thinking", "thought": True},
                        {"inlineData": {"mimeType": "image/jpeg", "data": "AAAA"}},
                    ]
                }
            }
        ],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 6, "totalTokenCount": 11},
    }
    parsed = _parse_gemini_image_response(payload)

    assert len(parsed["images"]) == 1
    assert parsed["images"][0]["result"] == "data:image/jpeg;base64,AAAA"
    assert parsed["usage"].prompt_tokens == 5
    assert parsed["usage"].total_tokens == 11


@pytest.mark.asyncio
async def test_provider_stream_chat_emits_image_events(monkeypatch):
    fake = _FakeClient([_FakeResponse(200, _gemini_response())])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    provider = TencentLiveProvider(ProviderConfig(name="TencentLive", api_key="tl_test_key", base_url="https://aigc.example.com"))

    chunks = []
    async for chunk in provider.stream_chat(_chat_request("gemini-3.1-flash-image")):
        chunks.append(chunk)

    assert len(chunks) == 3
    # Role marker
    assert chunks[0].delta_role == "assistant"
    # Image item events
    assert chunks[1].raw_sse_passthrough[0].startswith("event: response.output_item.added")
    assert chunks[1].raw_sse_passthrough[1].startswith("event: response.output_item.done")
    assert "image_generation_call" in chunks[1].raw_sse_passthrough[0]
    # Completed event
    assert chunks[2].raw_sse_passthrough[0].startswith("event: response.completed")


@pytest.mark.asyncio
async def test_stream_image_generation_direct(monkeypatch):
    """stream_image_generation() must emit the full SSE sequence."""
    fake = _FakeClient([_FakeResponse(200, _gemini_response())])
    monkeypatch.setattr("app.providers.tencentlive.image_generation.shared_client", lambda: fake)

    provider = TencentLiveProvider(ProviderConfig(name="TencentLive", api_key="tl_test_key", base_url="https://aigc.example.com"))
    chunks = []
    async for chunk in stream_image_generation(provider.chat, _chat_request("gemini-3.1-flash-image")):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[1].raw_sse_passthrough[1].startswith("event: response.output_item.done")
    assert "result" in chunks[1].raw_sse_passthrough[1]
