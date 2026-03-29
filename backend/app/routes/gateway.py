"""
AI Gateway API 路由层
提供 OpenAI、Anthropic 和 Responses API 兼容的端点。

三层架构：
  API 层 (Routes/Adapters) → 中间层 (GatewayService) → 供应商层 (Providers)

路由层职责：
  1. 认证 - 验证用户身份或 API Key
  2. 格式转换 - 使用 Adapter 在 API 格式和内部格式之间转换
  3. HTTP 响应 - 构建正确的 HTTP 响应（包括流式响应）

路由层不关心：
  - 具体使用哪个供应商（由中间层决定）
  - 供应商 API 的差异（由供应商层处理）
"""
from flask import Blueprint, request, jsonify, Response
from datetime import datetime
from typing import Optional
import json
import logging
import time
import os
import uuid

# Configure logger for gateway
logger = logging.getLogger("gateway")

from app import db
from app.models import Provider, Model, ApiKey, User, BackgroundResponse
from jose import JWTError, jwt

# 导入中间层
from app.middleware.gateway_service import (
    GatewayService,
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)

# 导入嵌入抽象
from app.abstraction.embedding import EmbeddingRequest

# 导入适配器
from app.adapters.openai_adapter import OpenAIChatAdapter
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter
from app.adapters.responses_adapter import OpenAIResponsesAdapter

# 导入供应商注册信息（仅用于管理端点）
from app.providers import get_provider_class, list_providers
from app.providers.base import ProviderConfig
from app.storage import get_storage_backend
from app.utils import gen_id

gateway_bp = Blueprint('gateway', __name__)

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"

# 创建全局服务实例
_gateway_service = GatewayService()


# ============== 认证 ==============

def get_current_user_or_api_key():
    """Authenticate via either JWT token, API key, or Anthropic x-api-key header.

    Supported authentication methods:
    1. Authorization: Bearer <token>  (JWT or API key)
    2. Authorization: <token>         (API key without Bearer prefix)
    3. x-api-key: <key>              (Anthropic SDK compatible)
    """
    auth_header = request.headers.get('Authorization')
    x_api_key = request.headers.get('x-api-key')

    if not auth_header and not x_api_key:
        return None, None, {'detail': 'Not authenticated'}, 401

    token = None
    if x_api_key:
        # Anthropic SDK sends credentials via x-api-key header
        token = x_api_key
    elif auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
    else:
        token = auth_header

    # First, try to find as API key
    api_key = db.session.query(ApiKey).filter(ApiKey.key == token).first()

    if api_key:
        if not api_key.is_active:
            return None, None, {'detail': 'API key is inactive'}, 401

        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return None, None, {'detail': 'API key has expired'}, 401

        # Update last used time
        api_key.last_used_at = datetime.utcnow()
        api_key.request_count += 1
        db.session.commit()

        return None, api_key, None, 200

    # Try JWT token authentication
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get('sub')
        if not username:
            return None, None, {'detail': 'Invalid token'}, 401
    except JWTError:
        return None, None, {'detail': 'Invalid token or API key'}, 401

    user = db.session.query(User).filter(User.username == username).first()
    if not user:
        return None, None, {'detail': 'User not found'}, 401

    return user, None, None, 200


# ============== 统一请求处理 ==============

def _handle_request(adapter):
    """
    统一的请求处理函数。

    所有 API 端点共用此函数，只需传入不同的适配器：
    - OpenAIChatAdapter: /v1/chat/completions
    - AnthropicMessagesAdapter: /v1/messages
    - OpenAIResponsesAdapter: /v1/responses

    流程：
    1. 认证
    2. 解析请求（Adapter: 外部格式 → ChatRequest）
    3. 调用中间层（GatewayService: ChatRequest → ChatResponse）
    4. 格式化响应（Adapter: ChatResponse → 外部格式）
    """
    # 1. 认证
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify(adapter.format_error_response(error.get('detail', 'Not authenticated'), status)), status

    # 2. 获取请求数据 (force=True to accept any Content-Type)
    data = request.get_json(force=True, silent=True)

    if not data:
        return jsonify(adapter.format_error_response('Invalid or empty JSON request body', 400)), 400

    model_name = data.get('model')
    if not model_name:
        return jsonify(adapter.format_error_response('Model is required', 400)), 400

    # 3. 使用适配器解析请求
    try:
        chat_request = adapter.parse_request(data)
    except Exception as e:
        return jsonify(adapter.format_error_response(f'Invalid request format: {str(e)}', 400)), 400

    # 4. 获取组 ID（用于访问控制）
    group_id = api_key.group_id if api_key else None

    # 4.5. 记录原始请求数据
    logger.info(f"Original request logged to: {json.dumps(data, ensure_ascii=False, indent=4)}")

    # 5. 调用中间层
    try:
        if chat_request.stream:
            # 流式请求
            chunks = _gateway_service.stream_chat(chat_request, group_id)
            return adapter.create_stream_response(chunks, model_name)
        else:
            # 非流式请求
            response = _gateway_service.chat(chat_request, group_id)
            return jsonify(adapter.format_response(response))

    except ProviderError as e:
        return jsonify(adapter.format_error_response(e.message, e.status_code, e.error_data)), e.status_code
    except ModelNotFoundError as e:
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code
    except GatewayServiceError as e:
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code


# ============== API 端点 ==============

@gateway_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """
    OpenAI-compatible chat completions endpoint.

    支持任意供应商（OpenAI、Claude、Gemini 等），
    中间层自动根据模型名称路由到正确的供应商。
    """
    return _handle_request(OpenAIChatAdapter())


@gateway_bp.route('/v1/messages', methods=['POST'])
def anthropic_messages():
    """
    Anthropic-compatible messages endpoint.

    支持任意供应商（OpenAI、Claude、Gemini 等），
    中间层自动根据模型名称路由到正确的供应商。
    """
    return _handle_request(AnthropicMessagesAdapter())


def _run_background_response(app, response_id: str, input_key: str, group_id: Optional[int]):
    """
    Worker function executed in a background thread.

    Reads the request payload via the storage backend using input_key, calls the
    GatewayService synchronously inside the Flask application context, then writes
    the formatted response to output_key and updates the BackgroundResponse DB record.

    Args:
        app:         The Flask application instance (needed for app context).
        response_id: The BackgroundResponse.response_id to update when done.
        input_key:   Storage key for the JSON request payload.
        group_id:    Group ID for access control (from the API key, or None for JWT users).
    """
    with app.app_context():
        bg_record = db.session.query(BackgroundResponse).filter_by(response_id=response_id).first()
        if bg_record is None:
            logger.error(f"[background] BackgroundResponse {response_id!r} not found in DB")
            return

        storage = get_storage_backend()

        try:
            # Read request payload via storage backend
            raw = storage.read(input_key)
            if raw is None:
                raise RuntimeError(f"Input not found at storage key: {input_key}")
            data = json.loads(raw)

            adapter = OpenAIResponsesAdapter()
            chat_request = adapter.parse_request(data)

            response = _gateway_service.chat(chat_request, group_id)
            formatted = adapter.format_response(response)

            # Write output via storage backend
            output_key = bg_record.output_key
            storage.write(output_key, json.dumps(formatted, ensure_ascii=False))

            bg_record.status = "completed"
            bg_record.completed_at = datetime.utcnow()
        except Exception as exc:
            logger.exception(f"[background] Error processing background response {response_id!r}: {exc}")
            bg_record.status = "failed"
            bg_record.error = str(exc)
            bg_record.completed_at = datetime.utcnow()
        finally:
            db.session.commit()


@gateway_bp.route('/v1/responses', methods=['POST'])
def openai_responses():
    """
    OpenAI Responses API endpoint.

    支持任意供应商（OpenAI、Claude、Gemini 等），
    中间层自动根据模型名称路由到正确的供应商。

    When the request body contains ``"background": true``, the endpoint:
    1. Immediately returns a ``202 Accepted`` JSON response containing the
       ``response_id`` and ``status: "in_progress"``.
    2. Spawns a background thread that calls the provider and stores the
       result in the ``ml_background_responses`` table.
    3. The client can later retrieve the result via
       ``GET /v1/responses/{response_id}``.
    """
    from flask import current_app
    import threading

    adapter = OpenAIResponsesAdapter()

    # 1. 先读取请求体，检查是否为 background 请求（无需先认证）
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify(adapter.format_error_response('Invalid or empty JSON request body', 400)), 400

    model_name = data.get('model')
    if not model_name:
        return jsonify(adapter.format_error_response('Model is required', 400)), 400

    is_background = bool(data.get('background', False))

    # 2. 认证（只做一次）
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify(adapter.format_error_response(error.get('detail', 'Not authenticated'), status)), status

    # 3. Background 异步路径
    if is_background:
        group_id = api_key.group_id if api_key else None
        apikey_value = api_key.key if api_key else None

        # Generate a stable response ID: "resp_" + 48 hex chars
        response_id = gen_id("resp")

        # Build input/output storage keys via the configured backend
        storage = get_storage_backend()
        input_key = storage.make_key(response_id, "input")
        output_key = storage.make_key(response_id, "output")

        # Write the request payload via the storage backend
        storage.write(input_key, json.dumps(data, ensure_ascii=False))

        # Persist the initial "in_progress" record (no payload stored in DB)
        bg_record = BackgroundResponse(
            response_id=response_id,
            apikey=apikey_value,
            status="in_progress",
            input_key=input_key,
            output_key=output_key,
            model=model_name,
        )
        db.session.add(bg_record)
        db.session.commit()

        # Launch the background worker thread
        app = current_app._get_current_object()
        thread = threading.Thread(
            target=_run_background_response,
            args=(app, response_id, input_key, group_id),
            daemon=True,
        )
        thread.start()

        # Return 202 immediately with the response ID and current status
        return jsonify({
            "id": response_id,
            "object": "response",
            "status": "in_progress",
            "model": model_name,
            "background": True,
        }), 202

    # 4. 同步路径：直接处理（不再重新认证，复用已读取的数据）
    group_id = api_key.group_id if api_key else None

    try:
        chat_request = adapter.parse_request(data)
    except Exception as e:
        return jsonify(adapter.format_error_response(f'Invalid request format: {str(e)}', 400)), 400

    logger.info(f"Original request logged to: {json.dumps(data, ensure_ascii=False, indent=4)}")

    try:
        if chat_request.stream:
            chunks = _gateway_service.stream_chat(chat_request, group_id)
            return adapter.create_stream_response(chunks, model_name)
        else:
            response = _gateway_service.chat(chat_request, group_id)
            return jsonify(adapter.format_response(response))
    except ProviderError as e:
        return jsonify(adapter.format_error_response(e.message, e.status_code, e.error_data)), e.status_code
    except ModelNotFoundError as e:
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code
    except GatewayServiceError as e:
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code


@gateway_bp.route('/v1/responses/<response_id>', methods=['GET'])
def get_response(response_id: str):
    """
    Retrieve a background response by ID.

    Used to poll the status and retrieve the result of a previously submitted
    background request (``POST /v1/responses`` with ``background=true``).

    Returns:
        - 200 with the full formatted response when status is "completed".
        - 200 with ``{"id": ..., "status": "in_progress", ...}`` while still running.
        - 200 with ``{"id": ..., "status": "failed", "error": "..."}`` on failure.
        - 404 if the response_id is not found.
        - 403 if the caller is not authorised to access this response.
    """
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify({'detail': error.get('detail', 'Not authenticated')}), status

    # Look up by the string response_id field, not the BigInteger pk
    bg_record = db.session.query(BackgroundResponse).filter_by(response_id=response_id).first()
    if bg_record is None:
        return jsonify({'detail': f'Response {response_id!r} not found'}), 404

    # Authorisation: API-key callers may only retrieve their own responses.
    # JWT-authenticated users (admin) may retrieve any response.
    if api_key and bg_record.apikey and bg_record.apikey != api_key.key:
        return jsonify({'detail': 'Not authorised to access this response'}), 403

    if bg_record.status == "completed":
        # Read the output via the configured storage backend
        storage = get_storage_backend()
        raw = storage.read(bg_record.output_key) if bg_record.output_key else None
        if raw:
            try:
                result = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                result = {"error": "Failed to parse stored response"}
        else:
            result = {"error": "Output not found in storage"}
        return jsonify(result), 200

    if bg_record.status == "failed":
        return jsonify({
            "id": bg_record.response_id,
            "object": "response",
            "status": "failed",
            "model": bg_record.model,
            "error": bg_record.error,
            "created_at": int(bg_record.created_at.timestamp()) if bg_record.created_at else None,
        }), 200

    # Still in_progress (or queued)
    return jsonify({
        "id": bg_record.response_id,
        "object": "response",
        "status": bg_record.status,
        "model": bg_record.model,
        "background": True,
        "created_at": int(bg_record.created_at.timestamp()) if bg_record.created_at else None,
    }), 200


# ============== 模型列表 ==============

@gateway_bp.route('/v1/models', methods=['GET'])
def list_models():
    """List all available models (OpenAI compatible)."""
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify(error), status

    # Filter providers by group if using API key
    if api_key:
        providers = db.session.query(Provider).filter(Provider.group_id == api_key.group_id).all()
    else:
        providers = db.session.query(Provider).all()

    models_list = []
    for provider in providers:
        for model in provider.models:
            # Use alias as id if available, otherwise use name
            model_id = model.alias if model.alias else model.name
            models_list.append({
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": provider.name,
                "permission": [],
                "root": model.name,
                "parent": None,
            })
            # If alias exists, also add an entry with the original name
            if model.alias and model.alias != model.name:
                models_list.append({
                    "id": model.name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": provider.name,
                    "permission": [],
                    "root": model.name,
                    "parent": None,
                })

    return jsonify({
        "object": "list",
        "data": models_list
    })


# ============== 供应商管理端点 ==============

@gateway_bp.route('/v1/providers', methods=['GET'])
def list_providers_api():
    """列出所有已注册的供应商类型"""
    providers = list_providers()
    return jsonify({
        "providers": providers
    })


@gateway_bp.route('/v1/providers/<provider_type>/models', methods=['GET'])
def list_provider_models(provider_type: str):
    """列出供应商支持的模型"""
    provider_class = get_provider_class(provider_type)

    if not provider_class:
        return jsonify({'detail': f'Provider type {provider_type} not found'}), 404

    # 创建临时实例获取模型列表
    config = ProviderConfig(
        name=provider_type,
        api_key="",
        base_url=None
    )

    try:
        instance = provider_class(config)
        if hasattr(instance, 'list_models'):
            models = instance.list_models()
            return jsonify({
                "object": "list",
                "data": models
            })
        else:
            return jsonify({
                "object": "list",
                "data": []
            })
    except Exception as e:
        return jsonify({'detail': f'Error listing models: {str(e)}'}), 500


# ============== Embeddings API ==============

@gateway_bp.route('/v1/embeddings', methods=['POST'])
def create_embeddings():
    """
    OpenAI-compatible embeddings endpoint.
    
    Supports embedding models from various providers (OpenAI, Gemini, Qwen, Doubao, etc.)
    that are compatible with OpenAI's embedding API format.
    
    Request body (standard):
    {
        "model": "text-embedding-3-small",
        "input": "The food was delicious and the waiter...",
        "encoding_format": "float",  // optional, "float" or "base64"
        "dimensions": 1536,  // optional, output dimensions
        "user": "user-id"  // optional
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
        "encoding_format": "float",  // optional
        "dimensions": 1536,  // optional
        "user": "user-id"  // optional
    }
    
    Request body (multimodal via input content blocks):
    {
        "model": "multimodal-embedding-model",
        "input": [
            {"type": "text", "text": "describe this image"},
            {"type": "image_url", "image_url": {"url": "https://..."}},
            {"type": "video_url", "video_url": {"url": "https://..."}}
        ],
        "encoding_format": "float",  // optional
        "dimensions": 1536,  // optional
        "user": "user-id"  // optional
    }
    """
    # 1. 认证
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify({'detail': error.get('detail', 'Not authenticated')}), status

    # 2. 获取请求数据
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'detail': 'Invalid or empty JSON request body'}), 400

    model_name = data.get('model')
    if not model_name:
        return jsonify({'detail': 'Model is required'}), 400

    input_data = data.get('input')
    messages = data.get('messages')

    if input_data is None and messages is None:
        return jsonify({'detail': 'Either "input" or "messages" is required'}), 400

    # Detect multimodal input: if input is a list of dicts with "type" keys,
    # normalize it into the messages format for unified downstream handling.
    # e.g. "input": [{"type":"text","text":"..."}, {"type":"image_url","image_url":{"url":"..."}}]
    if input_data is not None and isinstance(input_data, list) and len(input_data) > 0 and isinstance(input_data[0], dict) and 'type' in input_data[0]:
        # Convert content blocks array into messages format
        messages = [{"role": "user", "content": input_data}]
        input_data = None  # Clear input since we moved it to messages

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

    # 5. 调用中间层
    try:
        response = _gateway_service.embed(embedding_request, group_id)
        return jsonify(response.to_dict())
    except ModelNotFoundError as e:
        return jsonify({'detail': e.message}), e.status_code
    except GatewayServiceError as e:
        return jsonify({'detail': e.message}), e.status_code
    except ProviderError as e:
        return jsonify({'detail': e.message, 'error': e.error_data}), e.status_code
