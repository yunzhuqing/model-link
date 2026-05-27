"""
Rerank API route module.

Provides the /v1/rerank endpoint compatible with the vLLM rerank API format.
Supports both text-only and multimodal rerank models.
"""
from quart import Blueprint, request, jsonify, current_app, g
import asyncio
import logging
import time
import uuid

logger = logging.getLogger("gateway")

from app import get_db_session
from app.abstraction.rerank import RerankRequest
from app.middleware.gateway_service import (
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)
from app.monitoring import create_tracer
from app.group_service import get_group_monitoring_config

from app.routes.gateway_helpers import (
    _gateway_service,
    get_current_user_or_api_key,
    _parse_json_body,
    _log_error,
    _build_error_context,
    _check_allowed_models,
)

rerank_bp = Blueprint('rerank', __name__)


def _error_response(message, code="request_failed", param="", status_code=500):
    return jsonify({
        "error": {
            "message": message,
            "type": "one_api_error",
            "param": param,
            "code": code,
        }
    }), status_code


@rerank_bp.route('/v1/rerank', methods=['POST'])
async def create_rerank():
    """
    Rerank endpoint (compatible with vLLM /v1/rerank API format).
    """
    # ── Phase 1: auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("rerank", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    data = await _parse_json_body()
    if not data:
        _log_error("rerank", 400, "Invalid or empty JSON request body")
        return _error_response('Invalid or empty JSON request body', code="invalid_request", status_code=400)

    model_name = data.get('model')
    if not model_name:
        _log_error("rerank", 400, "Model is required", _build_error_context(auth_ctx))
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    query = data.get('query')
    if not query:
        _log_error("rerank", 400, '"query" is required', _build_error_context(auth_ctx, model_name))
        return _error_response('"query" is required', code="invalid_request", param="query", status_code=400)

    documents = data.get('documents')
    if not documents or not isinstance(documents, list):
        _log_error("rerank", 400, '"documents" must be a non-empty list', _build_error_context(auth_ctx, model_name))
        return _error_response('"documents" must be a non-empty list', code="invalid_request", param="documents", status_code=400)

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("rerank", 403, acl_error['detail'], _build_error_context(auth_ctx, model_name))
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    rerank_request = RerankRequest(
        model=model_name,
        query=query,
        documents=documents,
        top_n=data.get('top_n'),
        return_documents=data.get('return_documents', True),
        instruct=data.get('instruct'),
    )

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
                except Exception:
                    pass
    except ModelNotFoundError as e:
        _log_error("rerank", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("rerank", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    tracer = create_tracer(monitoring_config)

    # ── Phase 3: LLM call (no DB session) ──
    _request_id = g.request_id

    try:
        _start_time = time.time()
        if tracer:
            tracer.start(model_name, input_data=data)
            tracer.log_input(data)
            tracer.set_metadata({
                "request_id": _request_id,
                "group_id": group_id,
                "user": auth_ctx.user_name if auth_ctx else None,
                "model_name": model_name,
                "api_key_name": auth_ctx.api_key_name if auth_ctx else None,
            })

        response = await _gateway_service.rerank(resolved, rerank_request)
        _duration_ms = int((time.time() - _start_time) * 1000)

        if tracer:
            tracer.log_output(response.to_dict())
            tracer.set_metadata({"duration_ms": _duration_ms})
            tracer.end()

        # ── Phase 4: usage record ──
        try:
            from app.usagerecord.usage_service import record_usage
            await record_usage(
                response=response,
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
                duration_ms=_duration_ms,
            )
        except Exception as _ue:
            logger.warning(f"[usage] Failed to trigger usage recording for rerank: {_ue}")

        return jsonify(response.to_dict())
    except ModelNotFoundError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("rerank", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("rerank", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("rerank", e.status_code, e.message,
                   _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="provider_error", status_code=e.status_code)
