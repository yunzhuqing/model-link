"""
Images API route module.

Provides OpenAI-compatible image generation, image editing, and file serving
endpoints.
"""
from quart import Blueprint, request, jsonify, current_app, g, send_file
import asyncio
import logging
import mimetypes
import os
import time

logger = logging.getLogger("gateway")

from app import get_db_session
from app.monitoring import create_tracer
from app.group_service import get_group_monitoring_config
from app.middleware.gateway_service import (
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)
from app.storage import get_storage_backend

from app.routes.gateway_helpers import (
    _gateway_service,
    get_current_user_or_api_key,
    _parse_json_body,
    _log_error,
    _build_error_context,
    _check_allowed_models,
)

images_bp = Blueprint('images', __name__)


def _error_response(message, code="request_failed", param="", status_code=500):
    """Return a standardized error response for image endpoints."""
    return jsonify({
        "error": {
            "message": message,
            "type": "one_api_error",
            "param": param,
            "code": code,
        }
    }), status_code


async def _record_image_usage(
    *, chat_response, auth_ctx, resolved, model_name: str, duration_ms: int, kind: str,
) -> None:
    try:
        from app.usagerecord.usage_service import record_usage
        await record_usage(
            response=chat_response,
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
        logger.warning(f"[usage] Failed to trigger usage recording for {kind}: {_ue}")


# ============== Images Generations API ==============

@images_bp.route('/v1/images/generations', methods=['POST'])
async def create_images():
    """OpenAI-compatible image generation endpoint."""
    # ── Phase 1: auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("images_generations", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    data = await _parse_json_body()
    if not data:
        _log_error("images_generations", 400, "Invalid or empty JSON request body")
        return _error_response('Invalid or empty JSON request body', code="invalid_request", status_code=400)

    model_name = data.get('model')
    if not model_name:
        _log_error("images_generations", 400, "Model is required", _build_error_context(auth_ctx))
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    prompt = data.get('prompt')
    if not prompt:
        _log_error("images_generations", 400, "Prompt is required", _build_error_context(auth_ctx, model_name))
        return _error_response('Prompt is required', code="invalid_request", param="prompt", status_code=400)

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("images_generations", 403, acl_error['detail'], _build_error_context(auth_ctx, model_name))
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    images = data.get('images')
    n = data.get('n', 1)
    size = data.get('size', '1024x1024')
    response_format = data.get('response_format', 'url')
    output_format = data.get('output_format', 'png')
    quality = data.get('quality')
    style = data.get('style')
    user_id = data.get('user')
    aspect_ratio = data.get('aspect_ratio')
    resolution = data.get('resolution')

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ── Phase 2: resolve model ──
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
        _log_error("images_generations", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("images_generations", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    tracer = create_tracer(monitoring_config)

    # ── Phase 3: LLM call (no DB session) ──
    _request_start_time = time.monotonic()
    try:
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
        result, chat_response = await _gateway_service.generate_images(
            resolved=resolved,
            prompt=prompt,
            images=images,
            n=n,
            size=size,
            response_format=response_format,
            output_format=output_format,
            quality=quality,
            style=style,
            user=user_id,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            tracer=tracer,
        )
        _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
        if tracer:
            tracer.log_output(result)
            tracer.set_metadata({"duration_ms": _duration_ms})
            tracer.end()
        await _record_image_usage(
            chat_response=chat_response, auth_ctx=auth_ctx, resolved=resolved,
            model_name=model_name, duration_ms=_duration_ms, kind="image generation",
        )
        # Attach price info to response
        if chat_response and chat_response.usage:
            from app.usagerecord.usage_service import calculate_price
            result["price"] = calculate_price(
                usage=chat_response.usage,
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
            ).to_dict()
        return jsonify(result)
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("images_generations", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("images_generations", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("images_generations", e.status_code, e.message,
                   _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="provider_error", status_code=e.status_code)


# ============== Images Edits API ==============

@images_bp.route('/v1/images/edits', methods=['POST'])
async def edit_images():
    """OpenAI-compatible image editing endpoint."""
    # ── Phase 1: auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("images_edits", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    data = await _parse_json_body()
    if not data:
        _log_error("images_edits", 400, "Invalid or empty JSON request body")
        return _error_response('Invalid or empty JSON request body', code="invalid_request", status_code=400)

    model_name = data.get('model')
    if not model_name:
        _log_error("images_edits", 400, "Model is required", _build_error_context(auth_ctx))
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    prompt = data.get('prompt')
    if not prompt:
        _log_error("images_edits", 400, "Prompt is required", _build_error_context(auth_ctx, model_name))
        return _error_response('Prompt is required', code="invalid_request", param="prompt", status_code=400)

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("images_edits", 403, acl_error['detail'], _build_error_context(auth_ctx, model_name))
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    images = data.get('images')
    mask = data.get('mask')
    n = data.get('n', 1)
    size = data.get('size', '1024x1024')
    response_format = data.get('response_format', 'url')
    output_format = data.get('output_format', 'png')
    quality = data.get('quality')
    background = data.get('background')
    input_fidelity = data.get('input_fidelity')
    moderation = data.get('moderation')
    user_id = data.get('user')

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ── Phase 2: resolve model ──
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
        _log_error("images_edits", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("images_edits", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    tracer = create_tracer(monitoring_config)

    # ── Phase 3: LLM call (no DB session) ──
    _request_start_time = time.monotonic()
    try:
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
        result, chat_response = await _gateway_service.edit_images(
            resolved=resolved,
            prompt=prompt,
            images=images,
            mask=mask,
            n=n,
            size=size,
            response_format=response_format,
            output_format=output_format,
            quality=quality,
            background=background,
            input_fidelity=input_fidelity,
            moderation=moderation,
            user=user_id,
            tracer=tracer,
        )
        _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
        if tracer:
            tracer.log_output(result)
            tracer.set_metadata({"duration_ms": _duration_ms})
            tracer.end()
        await _record_image_usage(
            chat_response=chat_response, auth_ctx=auth_ctx, resolved=resolved,
            model_name=model_name, duration_ms=_duration_ms, kind="image editing",
        )
        # Attach price info to response
        if chat_response and chat_response.usage:
            from app.usagerecord.usage_service import calculate_price
            result["price"] = calculate_price(
                usage=chat_response.usage,
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
            ).to_dict()
        return jsonify(result)
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("images_edits", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("images_edits", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("images_edits", e.status_code, e.message,
                   _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="provider_error", status_code=e.status_code)


# ============== File Serving API ==============

@images_bp.route('/v1/files/<path:filename>', methods=['GET'])
async def serve_file(filename: str):
    """
    Serve a binary file (e.g. generated video) stored by the local storage backend.
    """
    storage = get_storage_backend()

    base_dir = getattr(storage, "base_dir", None)
    if base_dir is None:
        return jsonify({"detail": "File serving is only supported for local storage backend"}), 404

    # Prevent directory traversal
    safe_filename = os.path.normpath(filename).lstrip("/").lstrip("\\")
    if ".." in safe_filename:
        return jsonify({"detail": "Invalid filename"}), 400

    file_path = os.path.join(base_dir, "files", safe_filename)
    if not os.path.isfile(file_path):
        return jsonify({"detail": f"File not found: {filename}"}), 404

    mime_type, _ = mimetypes.guess_type(file_path)
    mime_type = mime_type or "application/octet-stream"

    return await send_file(file_path, mimetype=mime_type)
