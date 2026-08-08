"""
Audio API route module.

Provides the OpenAI-compatible /v1/audio/speech text-to-speech endpoint.
"""
from quart import Blueprint, jsonify, Response, request, g
import asyncio
import logging
import os
import time

logger = logging.getLogger("gateway")

from app import get_db_session
from app.abstraction.tts import TTSRequest
from app.abstraction.transcription import TranscriptionRequest
from app.monitoring import create_tracer
from app.group_service import get_group_monitoring_config
from app.middleware.gateway_service import (
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)

from app.routes.gateway_helpers import (
    _gateway_service,
    get_current_user_or_api_key,
    _parse_json_body,
    _log_error,
    _check_allowed_models,
    _build_error_context,
)
from app.http_client import get_shared_redirect_client

audio_bp = Blueprint('audio', __name__)


# Common audio MIME types → file extension (used to name data-URI sources).
_MIME_EXT = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "audio/amr": "amr",
    "audio/3gpp": "3gp",
    "audio/basic": "au",
}


class _TranscriptionInputError(ValueError):
    """Raised when a transcription request body is malformed.

    Carries the API ``param`` name so the handler can build a precise
    ``invalid_request`` error response.
    """

    def __init__(self, message: str, param: str = ""):
        super().__init__(message)
        self.param = param


def _guess_audio_filename(mime_type: str) -> str:
    """Derive a sensible ``audio.<ext>`` name from a MIME type."""
    ext = _MIME_EXT.get((mime_type or "").split(";")[0].strip().lower())
    return f"audio.{ext}" if ext else "audio"


def _decode_base64_payload(payload: str) -> bytes:
    """Strictly decode a base64 payload into bytes.

    Tolerates URL-safe alphabet (``-``/``_``) and missing padding; rejects
    garbage input instead of silently ignoring invalid characters.
    """
    import base64 as _b64
    payload = payload.strip()
    payload += "=" * (-len(payload) % 4)
    normalized = payload.replace("-", "+").replace("_", "/")
    try:
        return _b64.b64decode(normalized, validate=True)
    except Exception:
        raise ValueError("file_url contains invalid base64 data")


def _looks_like_base64(value: str) -> bool:
    """Heuristic: is this a bare base64 payload (not a URL / data URI)?"""
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9+/_-]+={0,2}", value))


async def _resolve_audio_source(file_url: str) -> tuple:
    """Resolve a ``file_url`` JSON parameter to in-memory audio bytes.

    Supported forms:
      - ``http(s)://...`` — downloaded with the shared redirect client.
      - ``data:<mime>;base64,<payload>`` — base64 data URI.
      - bare base64 payload (e.g. ``/9j/4AAQ...``).

    Returns ``(file_bytes, filename, mime_type)``. Raises ``ValueError`` with
    a client-facing message for unsupported or invalid input.
    """
    value = (file_url or "").strip()
    if not value:
        raise ValueError("file_url must not be empty")

    if value.startswith("data:"):
        try:
            header, payload = value.split(",", 1)
        except ValueError:
            raise ValueError("file_url must be a data: URI of the form data:<mime>;base64,<payload>")
        mime_type = header[5:].split(";")[0].strip() or "application/octet-stream"
        if ";base64" not in header.lower():
            raise ValueError("file_url data URI must be base64 encoded (data:<mime>;base64,<payload>)")
        file_bytes = await asyncio.to_thread(_decode_base64_payload, payload)
        if not file_bytes:
            raise ValueError("file_url decoded to an empty file")
        return file_bytes, _guess_audio_filename(mime_type), mime_type

    if value.startswith(("http://", "https://")):
        from urllib.parse import unquote, urlparse
        try:
            client = await get_shared_redirect_client()
            response = await client.get(value)
        except Exception as e:
            raise ValueError(f"Failed to download file_url: {e}")
        if response.status_code >= 400:
            raise ValueError(f"Failed to download file_url ({response.status_code})")
        if not response.content:
            raise ValueError("file_url downloaded an empty file")
        mime_type = (
            response.headers.get("content-type") or "application/octet-stream"
        ).split(";")[0].strip() or "application/octet-stream"
        path = unquote(urlparse(value).path)
        filename = os.path.basename(path) or _guess_audio_filename(mime_type)
        return response.content, filename, mime_type

    if _looks_like_base64(value):
        file_bytes = await asyncio.to_thread(_decode_base64_payload, value)
        if not file_bytes:
            raise ValueError("file_url decoded to an empty file")
        return file_bytes, "audio", "application/octet-stream"

    raise ValueError(
        "file_url must be an http(s) URL, a data:<mime>;base64,... URI, "
        "or a base64 string"
    )


def _coerce_optional_float(value, param: str):
    """JSON helper: accept a number or numeric string for an optional field."""
    if value is None or value == "":
        return None, None
    if isinstance(value, bool):
        return None, f"{param} must be a number"
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, str):
        try:
            return float(value), None
        except (TypeError, ValueError):
            return None, f"{param} must be a number"
    return None, f"{param} must be a number"


def _coerce_str_list(value, param: str):
    """JSON helper: accept a single string or a list of strings for an array field."""
    if value is None or value == "":
        return None, None
    if isinstance(value, str):
        return [value], None
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value or None, None
    return None, f"{param} must be a string or a list of strings"


async def _parse_multipart_transcription_input() -> dict:
    """Parse the OpenAI-compatible multipart form body (``file=`` + fields)."""
    files = await request.files
    form = await request.form

    file_obj = files.get("file")
    if not file_obj:
        raise _TranscriptionInputError(
            "An audio file is required. Use the 'file' field for multipart upload.",
            "file",
        )

    model_name = form.get("model")
    if not model_name:
        raise _TranscriptionInputError("Model is required", "model")

    temperature_raw = form.get("temperature")
    temperature = None
    if temperature_raw is not None and temperature_raw != "":
        try:
            temperature = float(temperature_raw)
        except (TypeError, ValueError):
            raise _TranscriptionInputError("temperature must be a number", "temperature")

    return {
        "model": model_name,
        "response_format": form.get("response_format", "json"),
        "language": form.get("language"),
        "prompt": form.get("prompt"),
        "temperature": temperature,
        "timestamp_granularities": form.getlist("timestamp_granularities[]") or None,
        "chunking_strategy": form.get("chunking_strategy"),
        "known_speaker_names": form.getlist("known_speaker_names[]") or None,
        "known_speaker_references": form.getlist("known_speaker_references[]") or None,
        "user": form.get("user"),
        "provider_options": _parse_provider_options(form),
        # Read the uploaded audio bytes once (short-lived, in-memory).
        "file_bytes": file_obj.read(),
        "filename": file_obj.filename or "audio",
        "mime_type": file_obj.content_type or "application/octet-stream",
    }


def _parse_provider_options(form) -> dict:
    """Collect optional provider-specific transcription fields."""
    names = (
        "enable_itn", "enable_punc", "enable_ddc", "enable_speaker_info",
        "ssd_version", "ssd_mode", "show_utterances", "enable_auto_lang",
        "enable_lid", "enable_gender_detection", "enable_emotion_detection", "sensitive_words_filter",
    )
    return {name: form.get(name) for name in names if form.get(name) is not None}


async def _parse_json_transcription_input() -> dict:
    """Parse a JSON transcription body (``file_url`` + optional fields)."""
    data = await _parse_json_body()
    if not data or not isinstance(data, dict):
        raise _TranscriptionInputError("Invalid or empty JSON request body")

    model_name = data.get("model")
    if not model_name:
        raise _TranscriptionInputError("Model is required", "model")

    file_url = data.get("file_url")
    if not file_url or not isinstance(file_url, str):
        raise _TranscriptionInputError(
            "file_url is required and must be an http(s) URL, a data URI, or base64",
            "file_url",
        )

    temperature, error = _coerce_optional_float(data.get("temperature"), "temperature")
    if error:
        raise _TranscriptionInputError(error, "temperature")
    granularities, error = _coerce_str_list(
        data.get("timestamp_granularities"), "timestamp_granularities"
    )
    if error:
        raise _TranscriptionInputError(error, "timestamp_granularities")
    speaker_names, error = _coerce_str_list(
        data.get("known_speaker_names"), "known_speaker_names"
    )
    if error:
        raise _TranscriptionInputError(error, "known_speaker_names")
    speaker_refs, error = _coerce_str_list(
        data.get("known_speaker_references"), "known_speaker_references"
    )
    if error:
        raise _TranscriptionInputError(error, "known_speaker_references")

    response_format = data.get("response_format") or "json"
    if not isinstance(response_format, str):
        raise _TranscriptionInputError("response_format must be a string", "response_format")

    file_bytes, resolved_filename, resolved_mime = await _resolve_audio_source(file_url)

    return {
        "model": model_name,
        "response_format": response_format,
        "language": data.get("language"),
        "prompt": data.get("prompt"),
        "temperature": temperature,
        "timestamp_granularities": granularities,
        "chunking_strategy": data.get("chunking_strategy"),
        "known_speaker_names": speaker_names,
        "known_speaker_references": speaker_refs,
        "user": data.get("user"),
        "provider_options": {
            name: data[name] for name in (
                "enable_itn", "enable_punc", "enable_ddc", "enable_speaker_info",
                "ssd_version", "ssd_mode", "show_utterances", "enable_auto_lang",
                "enable_lid", "enable_gender_detection", "enable_emotion_detection", "sensitive_words_filter",
            ) if name in data
        },
        "file_bytes": file_bytes,
        "source_url": file_url,
        # Explicit overrides win; otherwise derive from the resolved source.
        "filename": data.get("filename") or resolved_filename,
        "mime_type": data.get("mime_type") or resolved_mime,
    }


def _error_response(message, code="request_failed", param="", status_code=500):
    return jsonify({
        "error": {
            "message": message,
            "type": "one_api_error",
            "param": param,
            "code": code,
        }
    }), status_code


async def _record_tts_usage(*, tts_response, auth_ctx, resolved, model_name, duration_ms) -> None:
    """Fire-and-forget usage recording for a TTS request."""
    try:
        from app.usagerecord.usage_service import record_usage
        await record_usage(
            response=tts_response,
            user_name=auth_ctx.user_name if auth_ctx else None,
            user_id=auth_ctx.user_id if auth_ctx else None,
            api_key_raw=auth_ctx.api_key_raw if auth_ctx else None,
            api_key_name=auth_ctx.api_key_name if auth_ctx else None,
            api_key_group_id=auth_ctx.api_key_group_id if auth_ctx else None,
            api_key_group_name=auth_ctx.api_key_group_name if auth_ctx else None,
            model_name=model_name,
            provider_id=resolved.provider_id,
            provider_name=resolved.provider_name,
            input_price_unit=resolved.input_price,
            output_price_unit=resolved.output_price,
            cache_creation_price_unit=resolved.cache_creation_price,
            cache_5m_creation_price_unit=resolved.cache_5m_creation_price,
            cache_1h_creation_price_unit=resolved.cache_1h_creation_price,
            cache_token_price_unit=resolved.cache_hit_price,
            pricing_tiers=resolved.pricing_tiers,
            output_pricing=resolved.output_pricing,
            currency=resolved.currency,
            discount=resolved.discount,
            duration_ms=duration_ms,
            service_tier=resolved.service_tier,
        )
    except Exception as _ue:
        logger.warning(f"[usage] Failed to trigger usage recording for tts: {_ue}")


@audio_bp.route('/v1/audio/speech', methods=['POST'])
async def create_speech():
    """
    OpenAI-compatible text-to-speech endpoint.

    Accepts JSON `{model, input, voice, response_format, speed, instructions,
    loudness, pitch, sample}` and returns raw audio bytes
    (``audio/{response_format}``).
    """
    # ── Phase 1: auth (own short session inside) ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("audio_speech", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    data = await _parse_json_body()
    if not data:
        _log_error("audio_speech", 400, "Invalid or empty JSON request body")
        return _error_response('Invalid or empty JSON request body', code="invalid_request", status_code=400)

    model_name = data.get('model')
    if not model_name:
        _log_error("audio_speech", 400, "Model is required")
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    input_text = data.get('input')
    if input_text is None or (isinstance(input_text, str) and input_text == "") or (isinstance(input_text, (list, dict)) and not input_text):
        _log_error("audio_speech", 400, "Input is required (string or content-block array)")
        return _error_response('Input is required (string or content-block array)', code="invalid_request", param="input", status_code=400)

    voice = data.get('voice')

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("audio_speech", 403, acl_error['detail'])
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    tts_request = TTSRequest(
        model=model_name,
        input=input_text,
        voice=voice,
        response_format=data.get('response_format', 'mp3'),
        speed=data.get('speed'),
        instructions=data.get('instructions'),
        user=data.get('user'),
        loudness=data.get('loudness'),
        pitch=data.get('pitch'),
        sample=data.get('sample'),
        enable_subtitle=bool(data.get('enable_subtitle', False)),
        enable_url=bool(data.get('enable_url', False)),
    )

    service_tier = data.get('service_tier')
    if service_tier is not None and not isinstance(service_tier, str):
        _log_error("audio_speech", 400, "service_tier must be a string")
        return _error_response('service_tier must be a string', code="invalid_request", param="service_tier", status_code=400)

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ── Phase 2: resolve model (short session) ──
    monitoring_config = None
    try:
        async with get_db_session() as session:
            resolved = await _gateway_service.resolve_model(
                session, model_name, group_id, provider_id=provider_id,
                service_tier=service_tier,
            )
            if group_id:
                try:
                    monitoring_config = await get_group_monitoring_config(group_id, session=session)
                except Exception as _e:
                    logger.debug(f"[monitoring] fetch config failed: {_e}")
    except ModelNotFoundError as e:
        _log_error("audio_speech", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("audio_speech", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    tracer = create_tracer(monitoring_config)

    # ── Phase 3: upstream call (no DB session) ──
    try:
        _start_time = time.time()
        if tracer:
            tracer.start(model_name, input_data=data)
            tracer.log_input(data)
            tracer.set_metadata({
                "request_id": g.request_id,
                "group_id": group_id,
                "user": auth_ctx.user_name if auth_ctx else None,
                "model_name": model_name,
                "api_key_name": auth_ctx.api_key_name if auth_ctx else None,
            })
        tts_response = await _gateway_service.speech(resolved, tts_request, tracer=tracer)
        _duration_ms = int((time.time() - _start_time) * 1000)
        if tracer:
            tracer.log_output(tts_response.to_dict())
            tracer.set_metadata({"duration_ms": _duration_ms})
            tracer.end()
        # Attach computed price to the usage object (single source of truth).
        if tts_response.usage is not None:
            from app.usagerecord.usage_service import calculate_price
            tts_response.usage.price = calculate_price(
                usage=tts_response.usage,
                input_price_unit=resolved.input_price,
                output_price_unit=resolved.output_price,
                cache_creation_price_unit=resolved.cache_creation_price,
                cache_5m_creation_price_unit=resolved.cache_5m_creation_price,
                cache_1h_creation_price_unit=resolved.cache_1h_creation_price,
                cache_token_price_unit=resolved.cache_hit_price,
                pricing_tiers=resolved.pricing_tiers,
                output_pricing=resolved.output_pricing,
                currency=resolved.currency,
                discount=resolved.discount,
                            service_tier=resolved.service_tier,
            )
        # ── Phase 4: usage record (fire-and-forget) ──
        await _record_tts_usage(
            tts_response=tts_response, auth_ctx=auth_ctx, resolved=resolved,
            model_name=model_name, duration_ms=_duration_ms,
        )

        # ── Normalize output: URL vs. audio stream ──
        #  enable_url=true  → return a file URL JSON.
        #    - provider gave audio_url (e.g. doubao) → use it directly.
        #    - provider gave only audio_bytes (e.g. openai stream) → persist to
        #      storage and synthesize a /v1/files/<key> URL.
        #  enable_url=false → return the raw audio stream.
        #    - provider gave audio_bytes → stream directly.
        #    - provider gave only audio_url → download then stream.
        if tts_request.enable_url:
            audio_url = tts_response.audio_url
            if not audio_url and tts_response.audio_bytes:
                from app.storage import get_storage_backend
                fmt = (tts_request.response_format or 'mp3').lower()
                key = f"tts_{g.request_id}.{fmt}"
                try:
                    storage = get_storage_backend()
                    audio_url = storage.write_binary(key, tts_response.audio_bytes, tts_response.content_type)
                except NotImplementedError:
                    return _error_response(
                        "Configured storage backend does not support returning a URL",
                        code="request_failed", status_code=501,
                    )
            if not audio_url:
                return _error_response(
                    "TTS provider produced neither audio bytes nor a URL",
                    code="provider_error", status_code=502,
                )
            data_item: dict = {
                "url": audio_url,
                "model": model_name,
                "content_type": tts_response.content_type,
            }
            if tts_response.subtitle is not None:
                data_item["subtitle"] = tts_response.subtitle

            # Seed TTS 不支持 token —— 按音频秒数计费,usage 只放 price。
            usage_out: dict = {}
            if tts_response.usage is not None:
                seconds = tts_response.usage.get("output_audio_seconds", 0.0)
                if seconds:
                    data_item["duration"] = seconds
                price = getattr(tts_response.usage, "price", None)
                if price is not None and getattr(price, "actual_amount", None) is not None:
                    usage_out["price"] = price.to_dict()

            return jsonify({
                "created": int(time.time()),
                "data": [data_item],
                "usage": usage_out,
            })

        # Stream mode: ensure we have bytes.
        audio_bytes = tts_response.audio_bytes
        if audio_bytes is None and tts_response.audio_url:
            # Provider returned only a URL — download it. Uses the
            # follow_redirects client because signed audio URLs typically
            # 302 to the actual storage location.
            from app.http_client import get_shared_redirect_client
            try:
                client = await get_shared_redirect_client()
                dl = await client.get(tts_response.audio_url)
                if dl.status_code >= 400:
                    return _error_response(
                        f"Failed to download generated audio ({dl.status_code})",
                        code="provider_error", status_code=502,
                    )
                # Use the real content-type from the download response.
                downloaded_ct = (dl.headers.get("content-type") or "").split(";")[0].strip().lower()
                if downloaded_ct.startswith("audio/"):
                    tts_response.content_type = downloaded_ct
                elif downloaded_ct in ("text/html", "application/json", "text/plain"):
                    return _error_response(
                        f"Failed to download generated audio: unexpected content-type '{downloaded_ct}'",
                        code="provider_error", status_code=502,
                    )
                audio_bytes = dl.content
            except Exception as _e:
                return _error_response(
                    f"Failed to download generated audio: {_e}",
                    code="provider_error", status_code=502,
                )
        if not audio_bytes:
            return _error_response(
                "TTS provider produced no audio data",
                code="provider_error", status_code=502,
            )

        # Surface billing/size metadata via headers (binary body has no JSON).
        headers = {
            "Content-Type": tts_response.content_type,
            "Content-Length": str(len(audio_bytes)),
        }
        if tts_response.usage:
            seconds = tts_response.usage.get("output_audio_seconds", 0.0)
            if seconds:
                headers["X-Audio-Seconds"] = str(seconds)
            price = getattr(tts_response.usage, "price", None)
            if price is not None and getattr(price, "actual_amount", None) is not None:
                headers["X-Price"] = str(price.actual_amount)
                headers["X-Price-Currency"] = str(getattr(price, "currency", "USD"))

        return Response(audio_bytes, headers=headers)
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("audio_speech", e.status_code, e.message, _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("audio_speech", e.status_code, e.message, _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("audio_speech", e.status_code, e.message, _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="provider_error", status_code=e.status_code)


async def _record_transcription_usage(*, trx_response, auth_ctx, resolved, model_name, duration_ms) -> None:
    """Fire-and-forget usage recording for an audio transcription request."""
    try:
        from app.usagerecord.usage_service import record_usage
        await record_usage(
            response=trx_response,
            user_name=auth_ctx.user_name if auth_ctx else None,
            user_id=auth_ctx.user_id if auth_ctx else None,
            api_key_raw=auth_ctx.api_key_raw if auth_ctx else None,
            api_key_name=auth_ctx.api_key_name if auth_ctx else None,
            api_key_group_id=auth_ctx.api_key_group_id if auth_ctx else None,
            api_key_group_name=auth_ctx.api_key_group_name if auth_ctx else None,
            model_name=model_name,
            provider_id=resolved.provider_id,
            provider_name=resolved.provider_name,
            input_price_unit=resolved.input_price,
            output_price_unit=resolved.output_price,
            cache_creation_price_unit=resolved.cache_creation_price,
            cache_5m_creation_price_unit=resolved.cache_5m_creation_price,
            cache_1h_creation_price_unit=resolved.cache_1h_creation_price,
            cache_token_price_unit=resolved.cache_hit_price,
            pricing_tiers=resolved.pricing_tiers,
            output_pricing=resolved.output_pricing,
            currency=resolved.currency,
            discount=resolved.discount,
            duration_ms=duration_ms,
            service_tier=resolved.service_tier,
        )
    except Exception as _ue:
        logger.warning(f"[usage] Failed to trigger usage recording for transcription: {_ue}")


def _apply_usage_headers(headers, trx_response) -> None:
    """Surface billing/duration metadata via response headers."""
    if not trx_response.usage:
        return
    seconds = trx_response.usage.get("output_audio_seconds", 0.0)
    if seconds:
        headers["X-Audio-Seconds"] = str(seconds)
    price = getattr(trx_response.usage, "price", None)
    if price is not None and getattr(price, "actual_amount", None) is not None:
        headers["X-Price"] = str(price.actual_amount)
        headers["X-Price-Currency"] = str(getattr(price, "currency", "USD"))


@audio_bp.route('/v1/audio/transcriptions', methods=['POST'])
async def create_transcription():
    """
    OpenAI-compatible audio transcription endpoint.

    Accepts two input styles:

    1. ``multipart/form-data`` (OpenAI-compatible): ``file`` (audio file),
       ``model``, and optional parameters (``response_format``, ``language``,
       ``prompt``, ``temperature``, ``timestamp_granularities[]``,
       ``chunking_strategy``, ``known_speaker_names[]``,
       ``known_speaker_references[]``).
    2. ``application/json``: ``file_url`` (http(s) URL, ``data:<mime>;base64,...``
       URI, or bare base64) plus the same optional parameters as JSON fields
       (``timestamp_granularities``/``known_speaker_names``/
       ``known_speaker_references`` as arrays; optional ``filename`` and
       ``mime_type`` overrides).

    Returns the transcript in the requested ``response_format``
    (``json``/``text``/``srt``/``verbose_json``/``diarized_json``).
    """
    # ── Phase 1: auth (own short session inside) ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("audio_transcription", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    # ── Parse input: multipart (file=) or JSON (file_url=) ──
    is_json = "application/json" in (request.content_type or "").lower()
    try:
        parsed = (
            await _parse_json_transcription_input()
            if is_json
            else await _parse_multipart_transcription_input()
        )
    except _TranscriptionInputError as e:
        _log_error("audio_transcription", 400, str(e))
        return _error_response(str(e), code="invalid_request", param=e.param, status_code=400)

    model_name = parsed["model"]
    response_format = parsed["response_format"]
    language = parsed["language"]
    prompt = parsed["prompt"]
    temperature = parsed["temperature"]
    timestamp_granularities = parsed["timestamp_granularities"]
    chunking_strategy = parsed["chunking_strategy"]
    known_speaker_names = parsed["known_speaker_names"]
    known_speaker_references = parsed["known_speaker_references"]
    user = parsed["user"]
    file_bytes = parsed["file_bytes"]
    filename = parsed["filename"]
    mime_type = parsed["mime_type"]

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("audio_transcription", 403, acl_error['detail'])
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    trx_request = TranscriptionRequest(
        model=model_name,
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
        language=language,
        prompt=prompt,
        response_format=response_format,
        temperature=temperature,
        timestamp_granularities=timestamp_granularities,
        chunking_strategy=chunking_strategy,
        known_speaker_names=known_speaker_names,
        known_speaker_references=known_speaker_references,
        user=user,
        source_url=parsed.get("source_url"),
        provider_options=parsed.get("provider_options") or {},
    )

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ── Phase 2: resolve model (short session) ──
    monitoring_config = None
    try:
        async with get_db_session() as session:
            resolved = await _gateway_service.resolve_model(
                session, model_name, group_id, provider_id=provider_id,
            )
            if group_id:
                try:
                    monitoring_config = await get_group_monitoring_config(group_id, session=session)
                except Exception as _e:
                    logger.debug(f"[monitoring] fetch config failed: {_e}")
    except ModelNotFoundError as e:
        _log_error("audio_transcription", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("audio_transcription", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    tracer = create_tracer(monitoring_config)

    # ── Phase 3: upstream call (no DB session) ──
    try:
        _start_time = time.time()
        # Log metadata only — never the raw audio payload.
        input_meta = {
            "model": model_name,
            "response_format": response_format,
            "filename": filename,
            "file_size": len(file_bytes),
            "mime_type": mime_type,
            "language": trx_request.language,
            "chunking_strategy": chunking_strategy,
            "known_speaker_names": known_speaker_names,
        }
        if tracer:
            tracer.start(model_name, input_data=input_meta)
            tracer.log_input(input_meta)
            tracer.set_metadata({
                "request_id": g.request_id,
                "group_id": group_id,
                "user": auth_ctx.user_name if auth_ctx else None,
                "model_name": model_name,
                "api_key_name": auth_ctx.api_key_name if auth_ctx else None,
            })
        trx_response = await _gateway_service.transcribe(resolved, trx_request, tracer=tracer)
        _duration_ms = int((time.time() - _start_time) * 1000)
        if tracer:
            tracer.log_output(trx_response.to_dict())
            tracer.set_metadata({"duration_ms": _duration_ms})
            tracer.end()
        # Attach computed price to the usage object (single source of truth).
        if trx_response.usage is not None:
            from app.usagerecord.usage_service import calculate_price
            trx_response.usage.price = calculate_price(
                usage=trx_response.usage,
                input_price_unit=resolved.input_price,
                output_price_unit=resolved.output_price,
                cache_creation_price_unit=resolved.cache_creation_price,
                cache_5m_creation_price_unit=resolved.cache_5m_creation_price,
                cache_1h_creation_price_unit=resolved.cache_1h_creation_price,
                cache_token_price_unit=resolved.cache_hit_price,
                pricing_tiers=resolved.pricing_tiers,
                output_pricing=resolved.output_pricing,
                currency=resolved.currency,
                discount=resolved.discount,
                service_tier=resolved.service_tier,
            )
        # ── Phase 4: usage record (fire-and-forget) ──
        await _record_transcription_usage(
            trx_response=trx_response, auth_ctx=auth_ctx, resolved=resolved,
            model_name=model_name, duration_ms=_duration_ms,
        )

        fmt = response_format
        # ── Normalize output ──
        #  json / verbose_json / diarized_json → JSON body.
        #  text / srt → plain text body.
        if fmt in ("json", "verbose_json", "diarized_json"):
            data = trx_response.data if trx_response.data is not None else {"text": trx_response.text or ""}
            headers = {"Content-Type": "application/json"}
            _apply_usage_headers(headers, trx_response)
            return jsonify(data), 200, headers

        # text / srt → raw text stream.
        body = trx_response.text or ""
        headers = {"Content-Type": trx_response.content_type or "text/plain"}
        _apply_usage_headers(headers, trx_response)
        return Response(body, headers=headers)
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("audio_transcription", e.status_code, e.message, _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("audio_transcription", e.status_code, e.message, _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("audio_transcription", e.status_code, e.message, _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="provider_error", status_code=e.status_code)
