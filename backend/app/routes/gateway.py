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
import json
import time
import os

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

# 导入适配器
from app.adapters.openai_adapter import OpenAIChatAdapter
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter
from app.adapters.responses_adapter import OpenAIResponsesAdapter

# 导入供应商注册信息（仅用于管理端点）
from app.providers import get_provider_class, list_providers
from app.providers.base import ProviderConfig

gateway_bp = Blueprint('gateway', __name__)

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"

# 创建全局服务实例
_gateway_service = GatewayService()


# ============== 认证 ==============

def get_current_user_or_api_key():
    """Authenticate via either JWT token or API key."""
    auth_header = request.headers.get('Authorization')

    if not auth_header:
        return None, None, {'detail': 'Not authenticated'}, 401

    token = None
    if auth_header.startswith('Bearer '):
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
        return jsonify(error), status

    # 2. 获取请求数据
    data = request.get_json()

    model_name = data.get('model')
    if not model_name:
        return jsonify({'detail': 'Model is required'}), 400

    # 3. 使用适配器解析请求
    try:
        chat_request = adapter.parse_request(data)
    except Exception as e:
        return jsonify({'detail': f'Invalid request format: {str(e)}'}), 400

    # 4. 获取组 ID（用于访问控制）
    group_id = api_key.group_id if api_key else None

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
        if e.error_data:
            return jsonify(e.error_data), e.status_code
        return jsonify({'detail': e.message}), e.status_code
    except ModelNotFoundError as e:
        return jsonify({'detail': e.message}), e.status_code
    except GatewayServiceError as e:
        return jsonify({'detail': e.message}), e.status_code


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


@gateway_bp.route('/v1/responses', methods=['POST'])
def openai_responses():
    """
    OpenAI Responses API endpoint.

    支持任意供应商（OpenAI、Claude、Gemini 等），
    中间层自动根据模型名称路由到正确的供应商。
    """
    return _handle_request(OpenAIResponsesAdapter())


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
