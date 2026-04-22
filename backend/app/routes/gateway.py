"""
AI Gateway API 路由层
提供 OpenAI、Anthropic 兼容的端点，以及嵌入、图像生成、Rerank 等 API。
Responses API 端点已拆分至 gateway_responses 模块。

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
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from typing import Optional
import json
import logging
import time
import os

# Configure logger for gateway
logger = logging.getLogger("gateway")

from app import db
from app.models import Provider, Model, ApiKey, User
from jose import JWTError, jwt

# 导入中间层
from app.middleware.gateway_service import (
    GatewayService,
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)

# 导入嵌入/Rerank 抽象
from app.abstraction.embedding import EmbeddingRequest
from app.abstraction.rerank import RerankRequest

# 导入适配器
from app.adapters.openai_adapter import OpenAIChatAdapter
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter

# 导入供应商注册信息（仅用于管理端点）
from app.providers import get_provider_class, list_providers
from app.providers.base import ProviderConfig
from app.storage import get_storage_backend

gateway_bp = Blueprint('gateway', __name__)

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"

# 创建全局服务实例
_gateway_service = GatewayService()


def _check_allowed_models(api_key, model_name: str) -> Optional[dict]:
    """Check if the API key's allowed_models list permits access to this model.

    Returns None if access is allowed, or a (error_dict, status_code) tuple
    if the model is not in the allowed list.
    """
    if api_key is None:
        return None
    allowed = getattr(api_key, 'allowed_models', None)
    if not allowed:
        # No restriction — all models allowed
        return None
    if model_name in allowed:
        return None
    return {
        'detail': f"Model '{model_name}' is not allowed for this API key. "
                  f"Allowed models: {', '.join(allowed)}"
    }


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

    # 2.5. 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        return jsonify(adapter.format_error_response(acl_error['detail'], 403)), 403

    # 3. 使用适配器解析请求
    try:
        chat_request = adapter.parse_request(data)
    except Exception as e:
        return jsonify(adapter.format_error_response(f'Invalid request format: {str(e)}', 400)), 400

    # 4. 获取组 ID（用于访问控制）
    group_id = api_key.group_id if api_key else None

    # 4.5. 记录原始请求数据
    logger.debug(f"Original request logged to: {json.dumps(data, ensure_ascii=False)}")

    # 5. 调用中间层
    _request_start_time = time.monotonic()
    try:
        if chat_request.stream:
            # ── Streaming path ────────────────────────────────────────────────
            # Eagerly extract all identity info from ORM objects BEFORE
            # stream_chat_ex() removes the DB session.
            _user_name = user.username if user else (api_key.user.username if api_key and api_key.user else None)
            _api_key_raw = api_key.key if api_key else None
            _api_key_name = api_key.name if api_key else None
            _api_key_group_id = api_key.group_id if api_key else None
            _api_key_user_id = api_key.user_id if api_key else None
            _api_key_group_name: Optional[str] = None
            if api_key:
                try:
                    if api_key.group:
                        _api_key_group_name = api_key.group.name
                except Exception:
                    pass

            # stream_chat_ex returns (generator, model_meta) and releases the DB
            # session before any streaming begins.
            chunks, model_meta = _gateway_service.stream_chat_ex(chat_request, group_id)

            # Wrap the chunks to accumulate the final UsageInfo and record it
            # after the stream finishes (fire-and-forget background thread).
            _app = current_app._get_current_object()

            def _chunks_with_usage_recording():
                last_usage = None
                # Preserve extra data (e.g. cache_creation with ephemeral_5m/1h tokens)
                # from earlier usage chunks, since the final usage chunk (message_delta)
                # may not carry them.
                _accumulated_extra = {}
                try:
                    for chunk in chunks:
                        if chunk.usage is not None:
                            # Accumulate extra from all usage-bearing chunks
                            if hasattr(chunk.usage, 'extra') and chunk.usage.extra:
                                _accumulated_extra.update(chunk.usage.extra)
                            last_usage = chunk.usage
                        yield chunk
                    # Merge accumulated extra into the final usage
                    if last_usage is not None and _accumulated_extra:
                        if hasattr(last_usage, 'extra'):
                            # Only add keys not already present in last_usage.extra
                            for k, v in _accumulated_extra.items():
                                if k not in last_usage.extra:
                                    last_usage.extra[k] = v
                        else:
                            last_usage.extra = _accumulated_extra
                finally:
                    if last_usage is not None:
                        try:
                            from app.usage_service import record_stream_usage
                            _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
                            record_stream_usage(
                                app=_app,
                                usage_info=last_usage,
                                user_name=_user_name,
                                user_id=_api_key_user_id,
                                api_key_raw=_api_key_raw,
                                api_key_name=_api_key_name,
                                api_key_group_id=_api_key_group_id,
                                api_key_group_name=_api_key_group_name,
                                model_name=model_name,
                                provider_id=model_meta.get('provider_id'),
                                provider_name=model_meta.get('provider_name'),
                                input_price_unit=model_meta.get('input_price_unit', 0.0),
                                output_price_unit=model_meta.get('output_price_unit', 0.0),
                                cache_creation_price_unit=model_meta.get('cache_creation_price_unit', 0.0),
                                cache_5m_creation_price_unit=model_meta.get('cache_5m_creation_price_unit', 0.0),
                                cache_1h_creation_price_unit=model_meta.get('cache_1h_creation_price_unit', 0.0),
                                cache_token_price_unit=model_meta.get('cache_token_price_unit', 0.0),
                                pricing_tiers=model_meta.get('pricing_tiers'),
                                output_pricing=model_meta.get('output_pricing'),
                                currency=model_meta.get('currency', 'USD'),
                                discount=model_meta.get('discount', 1.0),
                                duration_ms=_duration_ms,
                            )
                        except Exception as _ue:
                            logger.warning(f"[usage] Failed to trigger stream usage recording: {_ue}")

            return adapter.create_stream_response(_chunks_with_usage_recording(), model_name)

        else:
            # 非流式请求 — use chat_ex() to get resolved model for usage recording
            response, resolved = _gateway_service.chat_ex(chat_request, group_id)
            _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
            # Record usage asynchronously (fire-and-forget)
            try:
                from app.usage_service import record_usage
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
                logger.warning(f"[usage] Failed to trigger usage recording: {_ue}")
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


# ============== 模型列表 ==============

@gateway_bp.route('/v1/models', methods=['GET'])
def list_models():
    """List all available models (OpenAI compatible)."""
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify(error), status

    # Filter providers by group if using API key, and exclude disabled providers
    if api_key:
        providers = db.session.query(Provider).filter(
            Provider.group_id == api_key.group_id,
            Provider.is_active == True
        ).all()
    else:
        providers = db.session.query(Provider).filter(Provider.is_active == True).all()

    # Get allowed_models restriction from API key (if any)
    allowed_models = None
    if api_key:
        allowed_models = getattr(api_key, 'allowed_models', None) or None

    models_list = []
    for provider in providers:
        for model in provider.models:
            # Skip disabled models
            if not model.is_active:
                continue
            # Skip models not in allowed_models (if restriction is set)
            if allowed_models:
                if model.name not in allowed_models and (not model.alias or model.alias not in allowed_models):
                    continue
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

    # 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        return jsonify({'detail': acl_error['detail']}), 403

    input_data = data.get('input')
    messages = data.get('messages')

    if input_data is None and messages is None:
        return jsonify({'detail': 'Either "input" or "messages" is required'}), 400

    # Normalize multimodal input formats into the messages format for unified downstream handling.
    #
    # Format 1: input is an object with "content" key (content block array)
    #   {"input": {"content": [{"type": "text", "text": "..."}, {"type": "image_url", ...}]}}
    #
    # Format 2: input is an array of content blocks (OpenAI-style)
    #   {"input": [{"type": "text", "text": "..."}, {"type": "image_url", ...}]}
    #
    # Both are converted to messages format:
    #   messages = [{"role": "user", "content": [...content blocks...]}]
    if input_data is not None and messages is None:
        content_blocks = None
        messages_from_input = None

        if isinstance(input_data, dict) and ('content' in input_data or 'contents' in input_data):
            # Format 1: {"input": {"content": [...]}} or {"input": {"contents": [...]}}
            # e.g. {"input": {"content": [{"type": "text", ...}, {"type": "image_url", ...}]}}
            content_blocks = input_data.get('content') or input_data.get('contents')

        elif isinstance(input_data, list) and len(input_data) > 0 and isinstance(input_data[0], dict):
            first = input_data[0]

            if 'content' in first:
                # Format 3: input is an array of message-like objects with "content" key (no role)
                # e.g. {"input": [{"content": [{"type": "text", ...}, {"type": "image_url", ...}]}]}
                # Treat each item as a message (role defaults to "user")
                messages_from_input = [
                    {"role": item.get("role", "user"), "content": item["content"]}
                    for item in input_data
                    if "content" in item
                ]
            elif 'type' in first:
                # Format 2: {"input": [{"type": ..., ...}, ...]}  — flat content block array
                content_blocks = input_data

        if content_blocks is not None:
            messages = [{"role": "user", "content": content_blocks}]
            input_data = None  # moved to messages
        elif messages_from_input is not None:
            messages = messages_from_input
            input_data = None  # moved to messages

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


# ============== Images Generations API ==============

@gateway_bp.route('/v1/images/generations', methods=['POST'])
def create_images():
    """
    OpenAI-compatible image generation endpoint.

    Request body:
    {
        "model": "seedream-5.0",
        "prompt": "A cute cat",
        "n": 1,
        "size": "1024x1024",
        "response_format": "url",        // "url" or "b64_json"
        "output_format": "png",           // "png", "jpeg", "webp"
        "quality": "standard",            // optional
        "style": "vivid",                 // optional
        "user": "user-id"                 // optional
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
        return jsonify({'detail': error.get('detail', 'Not authenticated')}), status

    # 2. 获取请求数据
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'detail': 'Invalid or empty JSON request body'}), 400

    model_name = data.get('model')
    if not model_name:
        return jsonify({'detail': 'Model is required'}), 400

    prompt = data.get('prompt')
    if not prompt:
        return jsonify({'detail': 'Prompt is required'}), 400

    # 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        return jsonify({'detail': acl_error['detail']}), 403

    # 3. 提取参数
    images = data.get('images')  # optional list of {"image_url": "..."}
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

    # 5. 调用中间层
    _request_start_time = time.monotonic()
    try:
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
        )
        _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
        # Record usage asynchronously (fire-and-forget)
        try:
            from app.usage_service import record_usage
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
        return jsonify({'detail': e.message}), e.status_code
    except GatewayServiceError as e:
        return jsonify({'detail': e.message}), e.status_code
    except ProviderError as e:
        return jsonify({'detail': e.message, 'error': e.error_data}), e.status_code


# ============== Images Edits API ==============

@gateway_bp.route('/v1/images/edits', methods=['POST'])
def edit_images():
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
        return jsonify({'detail': error.get('detail', 'Not authenticated')}), status

    # 2. 获取请求数据
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'detail': 'Invalid or empty JSON request body'}), 400

    model_name = data.get('model')
    if not model_name:
        return jsonify({'detail': 'Model is required'}), 400

    prompt = data.get('prompt')
    if not prompt:
        return jsonify({'detail': 'Prompt is required'}), 400

    # 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        return jsonify({'detail': acl_error['detail']}), 403

    # 3. 提取参数
    images = data.get('images')  # list of {"image_url": "...", "file_id": "..."}
    mask = data.get('mask')      # {"image_url": "...", "file_id": "..."}
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

    # 5. 调用中间层
    _request_start_time = time.monotonic()
    try:
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
        )
        _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
        # Record usage asynchronously (fire-and-forget)
        try:
            from app.usage_service import record_usage
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
        return jsonify({'detail': e.message}), e.status_code
    except GatewayServiceError as e:
        return jsonify({'detail': e.message}), e.status_code
    except ProviderError as e:
        return jsonify({'detail': e.message, 'error': e.error_data}), e.status_code


# ============== File Serving API ==============

@gateway_bp.route('/v1/files/<path:filename>', methods=['GET'])
def serve_file(filename: str):
    """
    Serve a binary file (e.g. generated video) stored by the local storage backend.

    Files are stored under ``{BACKGROUND_RESPONSE_STORAGE_DIR}/files/{filename}``.
    This endpoint is only meaningful for the local storage backend; when S3 is
    configured the provider returns a direct S3 (pre-signed) URL instead.

    No authentication is required — the filename itself acts as an unguessable
    token (it is derived from a securely generated response ID).
    """
    import mimetypes
    from flask import send_file

    storage = get_storage_backend()

    # Only LocalStorageBackend has a base_dir attribute; for S3 the video URL
    # is a direct S3/CDN link so this endpoint is never called.
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

    return send_file(file_path, mimetype=mime_type)


# ============== Rerank API ==============

@gateway_bp.route('/v1/rerank', methods=['POST'])
def create_rerank():
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
        return jsonify({'detail': error.get('detail', 'Not authenticated')}), status

    # 2. 获取请求数据
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'detail': 'Invalid or empty JSON request body'}), 400

    model_name = data.get('model')
    if not model_name:
        return jsonify({'detail': 'Model is required'}), 400

    query = data.get('query')
    if not query:
        return jsonify({'detail': '"query" is required'}), 400

    documents = data.get('documents')
    if not documents or not isinstance(documents, list):
        return jsonify({'detail': '"documents" must be a non-empty list'}), 400

    # 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
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
        return jsonify({'detail': e.message}), e.status_code
    except GatewayServiceError as e:
        return jsonify({'detail': e.message}), e.status_code
    except ProviderError as e:
        return jsonify({'detail': e.message, 'error': e.error_data}), e.status_code
