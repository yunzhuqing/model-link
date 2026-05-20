"""
Images API route module.

Provides OpenAI-compatible image generation, image editing, and file serving
endpoints.
"""
from quart import Blueprint, request, jsonify, current_app, g, send_file
import logging
import mimetypes
import os
import time

logger = logging.getLogger("gateway")

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
    _check_allowed_models,
    G_API_KEY_PROVIDER_ID,
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


# ============== Images Generations API ==============

@images_bp.route('/v1/images/generations', methods=['POST'])
async def create_images():
    """
    OpenAI-compatible image generation endpoint.

    Request body:
    {
        "model": "seedream-5.0",
        "prompt": "A cute cat",
        "n": 1,
        "size": "1024x1024",
        "response_format": "url",
        "output_format": "png",
        "quality": "standard",
        "style": "vivid",
        "user": "user-id"
    }

    Response:
    {
        "created": 1234567890,
        "data": [
            {"url": "https://...", "revised_prompt": "..."},
            // or {"b64_json": "data:image/png;base64,..."}
        ],
        "output_format": "png"
    }
    """
    # 1. 认证
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        _log_error("images_generations", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    # 2. 获取请求数据
    data = await _parse_json_body()
    if not data:
        _log_error("images_generations", 400, "Invalid or empty JSON request body")
        return _error_response('Invalid or empty JSON request body', code="invalid_request", status_code=400)

    model_name = data.get('model')
    if not model_name:
        _log_error("images_generations", 400, "Model is required")
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    prompt = data.get('prompt')
    if not prompt:
        _log_error("images_generations", 400, "Prompt is required")
        return _error_response('Prompt is required', code="invalid_request", param="prompt", status_code=400)

    # 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        _log_error("images_generations", 403, acl_error['detail'])
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    # 3. 提取参数
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

    # 4. 获取组 ID（用于访问控制）
    group_id = api_key.group_id if api_key else None
    provider_id = g.get(G_API_KEY_PROVIDER_ID, None) if api_key else None

    # 5. 设置 tracer
    monitoring_config = get_group_monitoring_config(group_id) if group_id else None
    tracer = create_tracer(monitoring_config)

    # 6. 调用中间层
    _request_start_time = time.monotonic()
    try:
        if tracer:
            tracer.start(model_name, input_data=data)
            tracer.log_input(data)
            tracer.set_metadata({
                "request_id": g.request_id,
                "group_id": group_id,
                "user": user.username if user else None,
                "model_name": model_name,
                "api_key_name": api_key.name if api_key else None,
            })
        result, chat_response, resolved = _gateway_service.generate_images(
            model_name=model_name,
            prompt=prompt,
            images=images,
            n=n,
            size=size,
            response_format=response_format,
            output_format=output_format,
            quality=quality,
            style=style,
            user=user_id,
            group_id=group_id,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            provider_id=provider_id,
            tracer=tracer,
        )
        _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
        if tracer:
            tracer.log_output(result)
            tracer.set_metadata({
                "duration_ms": _duration_ms,
            })
            tracer.end()
        try:
            from app.usagerecord.usage_service import record_usage
            record_usage(
                app=current_app._get_current_object(),
                response=chat_response,
                db_model=resolved.db_model,
                db_provider=resolved.db_provider,
                api_key=api_key,
                user=user,
                request_model_name=model_name,
                duration_ms=_duration_ms,
            )
        except Exception as _ue:
            logger.warning(f"[usage] Failed to trigger usage recording for image generation: {_ue}")
        return jsonify(result)
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("images_generations", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("images_generations", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("images_generations", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="provider_error", status_code=e.status_code)


# ============== Images Edits API ==============

@images_bp.route('/v1/images/edits', methods=['POST'])
async def edit_images():
    """
    OpenAI-compatible image editing endpoint.

    Request body:
    {
        "model": "gpt-image-1",
        "prompt": "Add a red hat to the person",
        "images": [{"image_url": "https://..."}],
        "n": 1,
        "size": "1024x1024",
        "response_format": "url",
        "output_format": "png",
        "quality": "auto",
        "background": "auto",
        "input_fidelity": "high",
        "mask": {"image_url": "https://..."},
        "moderation": "auto",
        "user": "user-id"
    }

    Response:
    {
        "created": 1234567890,
        "data": [
            {"url": "https://...", "revised_prompt": "..."}
        ],
        "output_format": "png",
        "size": "1024x1024",
        "quality": "auto",
        "background": "opaque"
    }
    """
    # 1. 认证
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        _log_error("images_edits", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    # 2. 获取请求数据
    data = await _parse_json_body()
    if not data:
        _log_error("images_edits", 400, "Invalid or empty JSON request body")
        return _error_response('Invalid or empty JSON request body', code="invalid_request", status_code=400)

    model_name = data.get('model')
    if not model_name:
        _log_error("images_edits", 400, "Model is required")
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    prompt = data.get('prompt')
    if not prompt:
        _log_error("images_edits", 400, "Prompt is required")
        return _error_response('Prompt is required', code="invalid_request", param="prompt", status_code=400)

    # 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        _log_error("images_edits", 403, acl_error['detail'])
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    # 3. 提取参数
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

    # 4. 获取组 ID（用于访问控制）
    group_id = api_key.group_id if api_key else None
    provider_id = g.get(G_API_KEY_PROVIDER_ID, None) if api_key else None

    # 5. 设置 tracer
    monitoring_config = get_group_monitoring_config(group_id) if group_id else None
    tracer = create_tracer(monitoring_config)

    # 6. 调用中间层
    _request_start_time = time.monotonic()
    try:
        if tracer:
            tracer.start(model_name, input_data=data)
            tracer.log_input(data)
            tracer.set_metadata({
                "request_id": g.request_id,
                "group_id": group_id,
                "user": user.username if user else None,
                "model_name": model_name,
                "api_key_name": api_key.name if api_key else None,
            })
        result, chat_response, resolved = _gateway_service.edit_images(
            model_name=model_name,
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
            group_id=group_id,
            provider_id=provider_id,
            tracer=tracer,
        )
        _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
        if tracer:
            tracer.log_output(result)
            tracer.set_metadata({
                "duration_ms": _duration_ms,
            })
            tracer.end()
        try:
            from app.usagerecord.usage_service import record_usage
            record_usage(
                app=current_app._get_current_object(),
                response=chat_response,
                db_model=resolved.db_model,
                db_provider=resolved.db_provider,
                api_key=api_key,
                user=user,
                request_model_name=model_name,
                duration_ms=_duration_ms,
            )
        except Exception as _ue:
            logger.warning(f"[usage] Failed to trigger usage recording for image editing: {_ue}")
        return jsonify(result)
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("images_edits", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("images_edits", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("images_edits", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="provider_error", status_code=e.status_code)


# ============== File Serving API ==============

@images_bp.route('/v1/files/<path:filename>', methods=['GET'])
async def serve_file(filename: str):
    """
    Serve a binary file (e.g. generated video) stored by the local storage backend.

    Files are stored under ``{BACKGROUND_RESPONSE_STORAGE_DIR}/files/{filename}``.
    No authentication is required — the filename itself acts as an unguessable
    token.
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