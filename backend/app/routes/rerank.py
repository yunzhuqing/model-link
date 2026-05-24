"""
Rerank API route module.

Provides the /v1/rerank endpoint compatible with the vLLM rerank API format.
Supports both text-only and multimodal rerank models.
"""
from quart import Blueprint, request, jsonify, current_app, g
import asyncio
import logging

logger = logging.getLogger("gateway")

from app import get_db_session
from app.abstraction.rerank import RerankRequest
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
        _log_error("rerank", 400, "Model is required")
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    query = data.get('query')
    if not query:
        _log_error("rerank", 400, '"query" is required')
        return _error_response('"query" is required', code="invalid_request", param="query", status_code=400)

    documents = data.get('documents')
    if not documents or not isinstance(documents, list):
        _log_error("rerank", 400, '"documents" must be a non-empty list')
        return _error_response('"documents" must be a non-empty list', code="invalid_request", param="documents", status_code=400)

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("rerank", 403, acl_error['detail'])
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
    try:
        async with get_db_session() as session:
            resolved = await _gateway_service.resolve_model(
                session, model_name, group_id, provider_id=provider_id
            )
    except ModelNotFoundError as e:
        _log_error("rerank", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("rerank", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    # ── Phase 3: LLM call (no DB session) ──
    try:
        response = await _gateway_service.rerank(resolved, rerank_request)
        return jsonify(response.to_dict())
    except ModelNotFoundError as e:
        _log_error("rerank", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("rerank", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        _log_error("rerank", e.status_code, e.message, {"model": model_name})
        return _error_response(e.message, code="provider_error", status_code=e.status_code)
