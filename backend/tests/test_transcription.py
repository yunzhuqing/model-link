"""
Audio transcription helper tests.

Covers the shared OpenAI-compatible ``_transcription`` module: multipart form
field construction (including repeated ``field[]`` array values), audio
duration → usage extraction, and request validation.

Run: cd backend && uv run pytest tests/test_transcription.py -q
"""
from __future__ import annotations

import json

import pytest

from app.abstraction.transcription import (
    TranscriptionRequest,
    TranscriptionResponse,
    DEFAULT_TRANSCRIPTION_FORMAT,
    TRANSCRIPTION_FORMATS,
)
from app.providers._transcription import (
    _build_form_fields,
    _build_usage,
    openai_transcribe,
)
from app.providers.base import UpstreamProviderError
from app.routes.audio import (
    _TranscriptionInputError,
    _guess_audio_filename,
    _parse_json_transcription_input,
    _resolve_audio_source,
)


class _FakeProvider:
    """Minimal duck-typed provider for validation-path tests."""

    def __init__(self, base_url="https://api.openai.com/v1"):
        class _Cfg:
            def __init__(self, base_url):
                self.base_url = base_url
                self.api_key = "sk-test"
                self.authorization = "Authorization"

        self.config = _Cfg(base_url)

    async def _http(self):
        # Should never be reached: validation must fail before the HTTP call.
        raise AssertionError("HTTP client should not be called in validation tests")


class _MockResp:
    def __init__(self, body: str, status: int = 200):
        self._body = body
        self.status_code = status
        self.text = body

    def json(self):
        return json.loads(self._body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"upstream {self.status_code}")


def _base_request(**overrides) -> TranscriptionRequest:
    defaults = dict(
        model="gpt-4o-transcribe-diarize",
        file_bytes=b"\x00\x01\x02",
        filename="meeting.wav",
        mime_type="audio/wav",
        response_format="diarized_json",
        chunking_strategy="auto",
        known_speaker_names=["agent", "customer"],
        known_speaker_references=[
            "data:audio/wav;base64,AAA...",
            "data:audio/wav;base64,BBB...",
        ],
        timestamp_granularities=["segment", "word"],
        language="en",
        prompt="Hello",
        temperature=0.0,
        user="u1",
    )
    defaults.update(overrides)
    return TranscriptionRequest(**defaults)


# ─── Abstraction defaults ────────────────────────────────────────────────


def test_transcription_request_defaults():
    req = TranscriptionRequest(model="whisper-1")
    assert req.model == "whisper-1"
    assert req.response_format == DEFAULT_TRANSCRIPTION_FORMAT == "json"
    assert req.file_bytes == b""
    assert req.metadata == {}


def test_transcription_response_to_dict_excludes_payload():
    resp = TranscriptionResponse(text="hello", data={"text": "hello"}, model="m")
    d = resp.to_dict()
    assert d["model"] == "m"
    assert d["has_data"] is True
    assert d["text_len"] == 5
    assert "usage" in d


# ─── Multipart form field construction ───────────────────────────────────


def test_build_form_fields_scalars():
    req = _base_request()
    fields = dict(_build_form_fields(req))
    assert fields["model"] == "gpt-4o-transcribe-diarize"
    assert fields["response_format"] == "diarized_json"
    assert fields["language"] == "en"
    assert fields["prompt"] == "Hello"
    assert fields["temperature"] == "0.0"
    assert fields["chunking_strategy"] == "auto"
    assert fields["user"] == "u1"


def test_build_form_fields_repeated_arrays():
    """Array fields survive as list values under their ``field[]`` key.

    httpx expands a list value into repeated multipart form parts, which is
    the correct way to express repeated ``field[]`` keys with a Mapping
    ``data=`` argument (a list-of-tuples would be misread as raw content).
    """
    req = _base_request()
    fields = _build_form_fields(req)
    assert fields["known_speaker_names[]"] == ["agent", "customer"]
    assert fields["known_speaker_references[]"] == [
        "data:audio/wav;base64,AAA...",
        "data:audio/wav;base64,BBB...",
    ]
    assert fields["timestamp_granularities[]"] == ["segment", "word"]


def test_build_form_fields_omits_empty_optionals():
    req = TranscriptionRequest(model="whisper-1", file_bytes=b"x")
    fields = dict(_build_form_fields(req))
    assert fields["model"] == "whisper-1"
    assert "language" not in fields
    assert "chunking_strategy" not in fields
    assert not any(k.endswith("[]") for k in fields)


# ─── Usage / billing extraction ──────────────────────────────────────────


def test_build_usage_verbose_json_duration():
    resp = _MockResp('{"text":"hi","duration":42.5}')
    usage = _build_usage(None, resp, "verbose_json")
    assert usage is not None
    assert usage.get("output_audio_seconds") == 42.5
    assert usage.prompt_tokens == 0


def test_build_usage_diarized_json_duration():
    resp = _MockResp('{"duration":10,"segments":[]}')
    usage = _build_usage(None, resp, "diarized_json")
    assert usage.get("output_audio_seconds") == 10.0


def test_build_usage_text_format_returns_none():
    usage = _build_usage(None, _MockResp("plain text body"), "text")
    assert usage is None


def test_build_usage_missing_duration_returns_none():
    resp = _MockResp('{"text":"hi"}')
    assert _build_usage(None, resp, "verbose_json") is None


# ─── Validation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_transcribe_rejects_unknown_format():
    req = TranscriptionRequest(
        model="whisper-1", file_bytes=b"x", response_format="bogus"
    )
    with pytest.raises(UpstreamProviderError) as exc:
        await openai_transcribe(_FakeProvider(), req)
    assert exc.value.status_code == 400
    assert "response_format" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_transcribe_requires_audio_file():
    req = TranscriptionRequest(
        model="whisper-1", file_bytes=b"", response_format="json"
    )
    with pytest.raises(UpstreamProviderError) as exc:
        await openai_transcribe(_FakeProvider(), req)
    assert exc.value.status_code == 400
    assert "audio file" in str(exc.value).lower()


def test_supported_formats_set():
    assert TRANSCRIPTION_FORMATS == {
        "json", "text", "srt", "verbose_json", "diarized_json",
    }


# ─── JSON input: file_url resolution ─────────────────────────────────────


def test_guess_audio_filename():
    assert _guess_audio_filename("audio/wav") == "audio.wav"
    assert _guess_audio_filename("audio/mpeg") == "audio.mp3"
    assert _guess_audio_filename("video/mp4") == "audio"
    assert _guess_audio_filename("audio/mp4; codecs=mp4a") == "audio.m4a"


@pytest.mark.asyncio
async def test_resolve_audio_source_data_uri():
    import base64

    payload = base64.b64encode(b"\x00\x01\x02").decode("ascii")
    file_bytes, filename, mime_type = await _resolve_audio_source(
        f"data:audio/wav;base64,{payload}"
    )
    assert file_bytes == b"\x00\x01\x02"
    assert filename == "audio.wav"
    assert mime_type == "audio/wav"


@pytest.mark.asyncio
async def test_resolve_audio_source_bare_base64():
    # Unpadded base64 exercises the missing-padding tolerance.
    file_bytes, filename, mime_type = await _resolve_audio_source("AAEC")
    assert file_bytes == b"\x00\x01\x02"
    assert filename == "audio"
    assert mime_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_resolve_audio_source_http_url(monkeypatch):
    from unittest.mock import AsyncMock

    class _FakeResp:
        def __init__(self, content, status=200, content_type="audio/mpeg"):
            self.content = content
            self.status_code = status
            self.headers = {"content-type": content_type}

    class _FakeClient:
        def __init__(self, response):
            self._response = response
            self.requested_url = None

        async def get(self, url):
            self.requested_url = url
            return self._response

    client = _FakeClient(_FakeResp(b"\xff\xfb audio"))
    monkeypatch.setattr("app.routes.audio.get_shared_redirect_client", AsyncMock(return_value=client))

    file_bytes, filename, mime_type = await _resolve_audio_source(
        "https://example.com/meeting.wav?token=abc"
    )
    assert client.requested_url == "https://example.com/meeting.wav?token=abc"
    assert file_bytes == b"\xff\xfb audio"
    assert filename == "meeting.wav"
    assert mime_type == "audio/mpeg"


@pytest.mark.asyncio
async def test_resolve_audio_source_http_error(monkeypatch):
    from unittest.mock import AsyncMock

    class _FakeResp:
        status_code = 404
        content = b""
        headers = {}

    class _FakeClient:
        async def get(self, url):
            return _FakeResp()

    monkeypatch.setattr("app.routes.audio.get_shared_redirect_client", AsyncMock(return_value=_FakeClient()))

    with pytest.raises(ValueError) as exc:
        await _resolve_audio_source("https://example.com/missing.wav")
    assert "404" in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_audio_source_rejects_garbage():
    with pytest.raises(ValueError) as exc:
        await _resolve_audio_source("not-a-url-or-base64!!")
    assert "file_url" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        await _resolve_audio_source("data:audio/wav;base64,!!!invalid")
    assert "base64" in str(exc.value)


# ─── JSON input: request body parsing ────────────────────────────────────


def _json_request_context(payload: dict):
    from quart import Quart

    app = Quart(__name__)
    return app.test_request_context(
        "/v1/audio/transcriptions",
        method="POST",
        json=payload,
    )


@pytest.mark.asyncio
async def test_parse_json_transcription_input_data_uri():
    import base64

    payload = base64.b64encode(b"\x00\x01\x02").decode("ascii")
    async with _json_request_context({
        "model": "whisper-1",
        "file_url": f"data:audio/wav;base64,{payload}",
        "response_format": "verbose_json",
        "language": "en",
        "temperature": 0.5,
        "timestamp_granularities": ["segment", "word"],
        "known_speaker_names": ["agent"],
        "chunking_strategy": "auto",
        "prompt": "Hello",
        "user": "u1",
        "filename": "custom.wav",
    }):
        parsed = await _parse_json_transcription_input()

    assert parsed["model"] == "whisper-1"
    assert parsed["response_format"] == "verbose_json"
    assert parsed["file_bytes"] == b"\x00\x01\x02"
    assert parsed["filename"] == "custom.wav"
    assert parsed["mime_type"] == "audio/wav"
    assert parsed["temperature"] == 0.5
    assert parsed["timestamp_granularities"] == ["segment", "word"]
    assert parsed["known_speaker_names"] == ["agent"]
    assert parsed["chunking_strategy"] == "auto"
    assert parsed["language"] == "en"
    assert parsed["prompt"] == "Hello"
    assert parsed["user"] == "u1"


@pytest.mark.asyncio
async def test_parse_json_transcription_input_requires_file_url():
    async with _json_request_context({"model": "whisper-1"}):
        with pytest.raises(_TranscriptionInputError) as exc:
            await _parse_json_transcription_input()
    assert "file_url" in str(exc.value)


@pytest.mark.asyncio
async def test_parse_json_transcription_input_rejects_bad_array():
    async with _json_request_context({
        "model": "whisper-1",
        "file_url": "data:audio/wav;base64,AAEC",
        "timestamp_granularities": 42,
    }):
        with pytest.raises(_TranscriptionInputError) as exc:
            await _parse_json_transcription_input()
    assert "timestamp_granularities" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_transcribe_builds_async_multipart_request():
    """Regression: the upstream POST must reach the transport as a real async
    multipart request. Previously ``data=`` was a list-of-tuples, which httpx
    mistook for raw *content*, dropping ``files=`` and producing a sync-only
    stream that an AsyncClient refuses to send ("Attempted to send an sync
    request with an AsyncClient instance.").
    """
    import httpx

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = await request.aread()
        captured["content_type"] = request.headers.get("content-type")
        return httpx.Response(200, json={"text": "hello world"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    class _Provider:
        class config:
            base_url = "https://api.openai.com/v1"
            api_key = "sk-test"
            authorization = "Authorization"

        async def _http(self):
            return client

    req = _base_request(response_format="json")
    resp = await openai_transcribe(_Provider(), req)

    # The request reached the transport (no sync-stream RuntimeError).
    assert captured.get("request") is not None
    # Multipart content type with a boundary, not urlencoded or raw bytes.
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    # The audio file part is present in the encoded body.
    assert b'filename="meeting.wav"' in captured["body"]
    # Scalar and repeated form fields are all encoded.
    body = captured["body"]
    assert b'name="model"' in body
    assert b'name="response_format"' in body
    # Repeated array key → one multipart part per value.
    assert body.count(b'name="known_speaker_names[]"') == 2
    assert body.count(b'name="timestamp_granularities[]"') == 2
    # Parsed transcript + content type surfaced to the caller.
    assert resp.text == "hello world"
    assert resp.content_type == "application/json"

    await client.aclose()
