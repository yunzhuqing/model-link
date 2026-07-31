"""
Audio API route module.

Provides the OpenAI-compatible /v1/audio/speech text-to-speech endpoint.
"""
from quart import Blueprint, jsonify, Response, g
import logging
import time

logger = logging.getLogger("gateway")

from app import get_db_session
from app.abstraction.tts import TTSRequest
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

audio_bp = Blueprint('audio', __name__)


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
        )
    except Exception as _ue:
        logger.warning(f"[usage] Failed to trigger usage recording for tts: {_ue}")


@audio_bp.route('/v1/audio/speech', methods=['POST'])
async def create_speech():
    """
    OpenAI-compatible text-to-speech endpoint.

    Accepts JSON `{model, input, voice, response_format, speed, instructions}`
    and returns raw audio bytes (``audio/{response_format}``).
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
    if not voice:
        _log_error("audio_speech", 400, "Voice is required")
        return _error_response('Voice is required', code="invalid_request", param="voice", status_code=400)

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
        enable_subtitle=bool(data.get('enable_subtitle', False)),
        enable_url=bool(data.get('enable_url', False)),
    )

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ── Phase 2: resolve model (short session) ──
    monitoring_config = None
    try:
        async with get_db_session() as session:
            resolved = await _gateway_service.resolve_model(
                session, model_name, group_id, provider_id=provider_id
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
            # Provider returned only a URL (e.g. doubao with enable_url) — download it.
            from app.http_client import get_shared_client
            try:
                client = await get_shared_client()
                dl = await client.get(tts_response.audio_url)
                if dl.status_code >= 400:
                    return _error_response(
                        f"Failed to download generated audio ({dl.status_code})",
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
