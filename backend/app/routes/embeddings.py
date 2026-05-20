"""
Embeddings API route module.

Provides the OpenAI-compatible /v1/embeddings endpoint, supporting both
text-only and multimodal embedding models.
"""
from quart import Blueprint, request, jsonify, current_app, g
import logging
import time

logger = logging.getLogger("gateway")

from app.abstraction.embedding import EmbeddingRequest
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
    G_API_KEY_PROVIDER_ID,
)

embeddings_bp = Blueprint('embeddings', __name__)


def _error_response(message, code="request_failed", param="", status_code=500):
    return jsonify({
        "error": {
            "message": message,
            "type": "one_api_error",
            "param": param,
            "code": code,
        }
    }), status_code


@embeddings_bp.route('/v1/embeddings', methods=['POST'])
async def create_embeddings():
    """
    OpenAI-compatible embeddings endpoint.

    Supports embedding models from various providers (OpenAI, Gemini, Qwen, Doubao, etc.)
    that are compatible with OpenAI's embedding API format.

    Request body (standard):
    {
        "model": "text-embedding-3-small",
        "input": "The food was delicious and the waiter...",
        "encoding_format": "float",
        "dimensions": 1536,
        "user": "user-id"
    }

    Request body (multimodal via messages):
    {
        "model": "multimodal-embedding-model",
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "describe this image"},
                {"type": "image_url", "image_url": {"url": "https://..."}}
            ]}
        ],
        "encoding_format": "float",
        "dimensions": 1536,
        "user": "user-id"
    }

    Request body (multimodal via input content blocks):
    {
        "model": "multimodal-embedding-model",
        "input": [
            {"type": "text", "text": "describe this image"},
            {"type": "image_url", "image_url": {"url": "https://..."}},
            {"type": "video_url", "video_url": {"url": "https://..."}}
        ],
        "encoding_format": "float",
        "dimensions": 1536,
        "user": "user-id"
    }
    """
    # 1. 认证
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        _log_error("embeddings", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    # 2. 获取请求数据
    data = await _parse_json_body()
    if not data:
        _log_error("embeddings", 400, "Invalid or empty JSON request body")
        return _error_response('Invalid or empty JSON request body', code="invalid_request", status_code=400)

    model_name = data.get('model')
    if not model_name:
        _log_error("embeddings", 400, "Model is required")
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    # 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        _log_error("embeddings", 403, acl_error['detail'])
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    input_data = data.get('input')
    messages = data.get('messages')

    if input_data is None and messages is None:
        _log_error("embeddings", 400, 'Either "input" or "messages" is required')
        return _error_response('Either "input" or "messages" is required', code="invalid_request", status_code=400)

    # Normalize multimodal input formats into the messages format for unified downstream handling.
    if input_data is not None and messages is None:
        content_blocks = None
        messages_from_input = None

        if isinstance(input_data, dict) and ('content' in input_data or 'contents' in input_data):
            content_blocks = input_data.get('content') or input_data.get('contents')

        elif isinstance(input_data, list) and len(input_data) > 0 and isinstance(input_data[0], dict):
            first = input_data[0]

            if 'content' in first:
                messages_from_input = [
                    {"role": item.get("role", "user"), "content": item["content"]}
                    for item in input_data
                    if "content" in item
                ]
            elif 'type' in first:
                content_blocks = input_data

        if content_blocks is not None:
            messages = [{"role": "user", "content": content_blocks}]
            input_data = None
        elif messages_from_input is not None:
            messages = messages_from_input
            input_data = None

    # 3. 构建嵌入请求
    embedding_request = EmbeddingRequest(
        model=model_name,
        input=input_data,
        messages=messages,
        encoding_format=data.get('encoding_format', 'float'),
        dimensions=data.get('dimensions'),
        user=data.get('user'),
    )

    # 4. 获取组 ID（用于访问控制）
    group_id = api_key.group_id if api_key else None
    provider_id = g.get(G_API_KEY_PROVIDER_ID, None) if api_key else None

    # 5. 设置 tracer
    monitoring_config = get_group_monitoring_config(group_id) if group_id else None
    tracer = create_tracer(monitoring_config)

    # 6. 调用中间层
    try:
        _start_time = time.time()
        # Resolve model to capture provider info before the API call
        resolved = _gateway_service.resolve_model(model_name, group_id, provider_id=provider_id)

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
        resolved.provider_instance.tracer = tracer
        response = _gateway_service.embed(embedding_request, group_id, provider_id=provider_id, tracer=tracer)
        _duration_ms = int((time.time() - _start_time) * 1000)
        if tracer:
            tracer.log_output(response.to_dict())
            tracer.set_metadata({
                "duration_ms": _duration_ms,
            })
            tracer.end()
        # Record usage
        try:
            from app.usagerecord.usage_service import record_usage
            record_usage(
                app=current_app._get_current_object(),
                response=response,
                db_model=resolved.db_model,
                db_provider=resolved.db_provider,
                api_key=api_key,
                user=user,
                request_model_name=model_name,
                duration_ms=_duration_ms,
            )
        except Exception as _ue:
            logger.warning(f"[usage] Failed to trigger usage recording for embeddings: {_ue}")
        return jsonify(response.to_dict())
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("embeddings", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("embeddings", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("embeddings", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="provider_error", status_code=e.status_code)