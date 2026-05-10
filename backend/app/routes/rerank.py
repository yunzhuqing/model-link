"""
Rerank API route module.

Provides the /v1/rerank endpoint compatible with the vLLM rerank API format.
Supports both text-only and multimodal rerank models.
"""
from quart import Blueprint, request, jsonify, g
import logging

logger = logging.getLogger("gateway")

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


@rerank_bp.route('/v1/rerank', methods=['POST'])
async def create_rerank():
    """
    Rerank endpoint (compatible with vLLM /v1/rerank API format).

    Supports both text-only and multimodal rerank models.
    Routes to the appropriate provider API based on the model.

    Request body (text rerank):
    {
        "model": "qwen3-rerank",
        "query": "什么是文本排序模型",
        "documents": ["文本一", "文本二", "文本三"],
        "top_n": 2,
        "return_documents": true,
        "instruct": "Given a web search query, retrieve relevant passages that answer the query."
    }

    Request body (multimodal rerank):
    {
        "model": "qwen3-vl-rerank",
        "query": {"text": "什么是文本排序模型"},
        "documents": [
            {"text": "文本一"},
            {"image": "https://..."},
            {"video": "https://..."}
        ],
        "top_n": 2,
        "return_documents": true
    }

    Response (vLLM compatible format):
    {
        "id": "rerank-xxx",
        "model": "qwen3-rerank",
        "usage": {"total_tokens": 79},
        "results": [
            {"index": 0, "document": {"text": "..."}, "relevance_score": 0.93}
        ]
    }
    """
    # 1. 认证
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        _log_error("rerank", status, error.get('detail', 'Not authenticated'))
        return jsonify({'detail': error.get('detail', 'Not authenticated')}), status

    # 2. 获取请求数据
    data = await _parse_json_body()
    if not data:
        _log_error("rerank", 400, "Invalid or empty JSON request body")
        return jsonify({'detail': 'Invalid or empty JSON request body'}), 400

    model_name = data.get('model')
    if not model_name:
        _log_error("rerank", 400, "Model is required")
        return jsonify({'detail': 'Model is required'}), 400

    query = data.get('query')
    if not query:
        _log_error("rerank", 400, '"query" is required')
        return jsonify({'detail': '"query" is required'}), 400

    documents = data.get('documents')
    if not documents or not isinstance(documents, list):
        _log_error("rerank", 400, '"documents" must be a non-empty list')
        return jsonify({'detail': '"documents" must be a non-empty list'}), 400

    # 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        _log_error("rerank", 403, acl_error['detail'])
        return jsonify({'detail': acl_error['detail']}), 403

    # 3. 构建 Rerank 请求
    rerank_request = RerankRequest(
        model=model_name,
        query=query,
        documents=documents,
        top_n=data.get('top_n'),
        return_documents=data.get('return_documents', True),
        instruct=data.get('instruct'),
    )

    # 4. 获取组 ID（用于访问控制）
    group_id = api_key.group_id if api_key else None

    # 5. 调用中间层
    try:
        response = _gateway_service.rerank(rerank_request, group_id)
        return jsonify(response.to_dict())
    except ModelNotFoundError as e:
        _log_error("rerank", e.status_code, e.message, {"model": model_name})
        return jsonify({'detail': e.message}), e.status_code
    except GatewayServiceError as e:
        _log_error("rerank", e.status_code, e.message, {"model": model_name})
        return jsonify({'detail': e.message}), e.status_code
    except ProviderError as e:
        _log_error("rerank", e.status_code, e.message, {"model": model_name})
        return jsonify({'detail': e.message, 'error': e.error_data}), e.status_code