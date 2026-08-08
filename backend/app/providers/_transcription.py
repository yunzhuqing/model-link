"""
Shared audio transcription implementation for OpenAI-compatible providers.

Both ``OpenAIProvider`` (Chat Completions compatible) and
``OpenAIResponsesCompatProvider`` (Responses API compatible) expose the same
``/audio/transcriptions`` surface, so the transcription call lives here and is
delegated to by each provider's ``transcribe()`` method.

The request is ``multipart/form-data`` — the audio file plus scalar/array
form fields such as ``model``, ``response_format``, ``chunking_strategy``,
``known_speaker_names[]`` and ``known_speaker_references[]``. The helper
forwards every provided field to the upstream verbatim.

Billing: the upstream reports the processed audio ``duration`` (in seconds)
inside ``verbose_json`` / ``diarized_json`` responses. That duration is
surfaced through the ``UsageInfo.extra["output_audio_seconds"]`` slot so the
existing per-second audio billing path applies. For ``json`` / ``text`` /
``srt`` formats the upstream does not report duration, so billing is
best-effort (zero seconds — no charge) unless the model is configured with a
flat per-request price.
"""
import json
from typing import Any, Dict, Optional

from .base import UpstreamProviderError
from app.abstraction.transcription import (
    TranscriptionResponse,
    TRANSCRIPTION_FORMATS,
    DEFAULT_TRANSCRIPTION_FORMAT,
)


def _auth_headers(provider) -> Dict[str, str]:
    """Auth headers only — httpx sets the multipart Content-Type boundary."""
    headers: Dict[str, str] = {}
    auth = getattr(provider.config, "authorization", "Authorization")
    if auth == "Authorization":
        headers["Authorization"] = f"Bearer {provider.config.api_key}"
    else:
        headers[auth] = provider.config.api_key
    return headers


def _build_form_fields(request) -> Dict[str, Any]:
    """Build the multipart form fields (excluding the file) as a dict.

    httpx's ``data=`` parameter must be a Mapping for form data. A list of
    ``(name, value)`` tuples is instead treated as raw request *content* (see
    ``httpx.encode_request``), which both drops the ``files=`` payload and
    yields a sync-only ``IteratorByteStream`` that an ``AsyncClient`` refuses
    to send ("Attempted to send an sync request with an AsyncClient
    instance."). Repeated keys (``known_speaker_names[]`` etc.) are therefore
    expressed as list values, which httpx expands into repeated multipart
    form parts.
    """
    fmt = (request.response_format or DEFAULT_TRANSCRIPTION_FORMAT).lower()
    fields: Dict[str, Any] = {
        "model": request.model,
        "response_format": fmt,
    }

    if request.language:
        fields["language"] = request.language
    if request.prompt is not None:
        fields["prompt"] = request.prompt
    if request.temperature is not None:
        fields["temperature"] = str(request.temperature)
    if request.chunking_strategy:
        fields["chunking_strategy"] = request.chunking_strategy
    if request.user:
        fields["user"] = request.user

    # Array form fields. OpenAI uses the ``field[]`` convention; a list value
    # makes httpx emit one repeated form part per entry.
    if request.timestamp_granularities:
        fields["timestamp_granularities[]"] = list(request.timestamp_granularities)
    if request.known_speaker_names:
        fields["known_speaker_names[]"] = list(request.known_speaker_names)
    if request.known_speaker_references:
        fields["known_speaker_references[]"] = list(request.known_speaker_references)

    return fields


async def openai_transcribe(provider, request) -> TranscriptionResponse:
    """
    POST ``{base_url}/audio/transcriptions`` (multipart/form-data) and return
    the parsed transcript.

    ``provider`` is duck-typed: it must expose ``config`` (with ``base_url``),
    ``get_headers()``, and ``_http()`` — i.e. any ``BaseProvider`` subclass.
    """
    fmt = (request.response_format or DEFAULT_TRANSCRIPTION_FORMAT).lower()
    if fmt not in TRANSCRIPTION_FORMATS:
        raise UpstreamProviderError(
            f"Unsupported response_format '{fmt}'. "
            f"Must be one of: {', '.join(sorted(TRANSCRIPTION_FORMATS))}",
            status_code=400,
            error_type="invalid_request",
        )

    if not request.file_bytes:
        raise UpstreamProviderError(
            "An audio file is required",
            status_code=400,
            error_type="invalid_request",
        )

    url = f"{provider.config.base_url}/audio/transcriptions"

    files = {
        "file": (
            request.filename or "audio",
            request.file_bytes,
            request.mime_type or "application/octet-stream",
        ),
    }
    data = _build_form_fields(request)

    try:
        response = await (await provider._http()).post(
            url, data=data, files=files, headers=_auth_headers(provider),
        )

        if response.status_code >= 400:
            try:
                error_data = response.json()
                error_message = (
                    error_data.get("error", {}).get("message")
                    or error_data.get("message")
                    or json.dumps(error_data, ensure_ascii=False)
                )
            except (json.JSONDecodeError, ValueError):
                error_message = response.text
            raise UpstreamProviderError(
                error_message,
                status_code=response.status_code,
                error_type="api_error",
            )

        response.raise_for_status()

        usage = _build_usage(request, response, fmt)

        # JSON formats → parse the upstream body. Text formats → raw string.
        if fmt in ("json", "verbose_json", "diarized_json"):
            try:
                parsed = response.json()
            except (json.JSONDecodeError, ValueError):
                parsed = {"text": response.text}
            text = parsed.get("text") if isinstance(parsed, dict) else None
            return TranscriptionResponse(
                text=text,
                data=parsed,
                content_type="application/json",
                model=request.model,
                usage=usage,
            )

        # text / srt → plain text body.
        return TranscriptionResponse(
            text=response.text,
            content_type="text/plain",
            model=request.model,
            usage=usage,
        )

    except UpstreamProviderError:
        raise
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"OpenAI transcription API error: {str(e)}")


def _build_usage(request, response, fmt: str) -> Optional[Any]:
    """Extract audio duration (seconds) for billing when the upstream reports it."""
    duration = None
    if fmt in ("verbose_json", "diarized_json"):
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                duration = parsed.get("duration")
        except (json.JSONDecodeError, ValueError):
            pass
    elif fmt == "json":
        # Standard json: some upstreams include a ``duration`` field; use it
        # opportunistically when present.
        try:
            parsed = response.json()
            if isinstance(parsed, dict) and parsed.get("duration") is not None:
                duration = parsed.get("duration")
        except (json.JSONDecodeError, ValueError):
            pass

    seconds = 0.0
    try:
        if duration is not None:
            seconds = float(duration)
    except (TypeError, ValueError):
        seconds = 0.0

    if seconds <= 0:
        return None

    # Imported here to avoid a circular import at module load time.
    from app.abstraction.chat import UsageInfo
    return UsageInfo(
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        extra={
            "output_audio_seconds": seconds,
        },
    )
