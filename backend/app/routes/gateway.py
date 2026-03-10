"""
AI Gateway API router.
Provides OpenAI-compatible and Anthropic-compatible endpoints.
使用三层架构：API层 -> 抽象层 -> 供应商层
"""
from flask import Blueprint, request, jsonify, Response
from datetime import datetime
import json
import time
import os
from typing import Generator

from app import db
from app.models import Provider, Model, ApiKey, User
from app.routes.users import token_required
from jose import JWTError, jwt

# 导入抽象层
from app.abstraction.messages import Message, MessageRole
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamManager, create_stream_response_generator

# 导入供应商层
from app.providers import get_provider_class, list_providers
from app.providers.base import ProviderConfig, ProviderCapability

gateway_bp = Blueprint('gateway', __name__)

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"


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


def resolve_model(model_name: str):
    """
    Resolve a model name to its provider and model configuration.
    
    Args:
        model_name: 模型名称
    
    Returns:
        (provider_model, db_provider, db_model) 或 (None, None, None)
    """
    db_model = db.session.query(Model).filter(Model.name == model_name).first()
    
    if db_model:
        db_provider = db.session.query(Provider).filter(
            Provider.id == db_model.provider_id
        ).first()
        if db_provider:
            # 创建供应商实例
            provider_instance = create_provider_instance(db_provider)
            return provider_instance, db_provider, db_model
    
    return None, None, None


def create_provider_instance(db_provider: Provider):
    """
    根据数据库供应商配置创建供应商实例
    
    Args:
        db_provider: 数据库供应商对象
    
    Returns:
        供应商实例，如果创建失败返回 None
    """
    # 从供应商名称推断供应商类型
    provider_type = infer_provider_type(db_provider.name, db_provider.base_url)
    
    # 获取供应商类
    provider_class = get_provider_class(provider_type)
    
    if not provider_class:
        # 如果没有找到对应的供应商类，使用通用 OpenAI 兼容实现
        from app.providers.bailian_provider import BailianProvider
        provider_class = BailianProvider
    
    # 创建供应商配置
    config = ProviderConfig(
        name=db_provider.name,
        api_key=db_provider.api_key or "",
        base_url=db_provider.base_url,
        timeout=60,
    )
    
    try:
        return provider_class(config)
    except Exception as e:
        print(f"Error creating provider instance: {e}")
        return None


def infer_provider_type(provider_name: str, base_url: str = None) -> str:
    """
    从供应商名称或 URL 推断供应商类型
    
    Args:
        provider_name: 供应商名称
        base_url: API 基础 URL
    
    Returns:
        供应商类型字符串
    """
    name_lower = provider_name.lower()
    
    # 根据名称推断
    if 'bailian' in name_lower or '百炼' in name_lower or 'dashscope' in name_lower:
        return 'bailian'
    if 'openai' in name_lower:
        return 'openai'
    if 'anthropic' in name_lower or 'claude' in name_lower:
        return 'anthropic'
    if 'deepseek' in name_lower:
        return 'bailian'  # DeepSeek 在百炼上可用
    if 'qwen' in name_lower or '通义' in name_lower:
        return 'bailian'
    
    # 根据 URL 推断
    if base_url:
        if 'dashscope' in base_url or 'aliyun' in base_url:
            return 'bailian'
        if 'openai' in base_url:
            return 'openai'
        if 'anthropic' in base_url:
            return 'anthropic'
        if 'deepseek' in base_url:
            return 'bailian'
    
    # 默认使用百炼（OpenAI 兼容）
    return 'bailian'


# ============== OpenAI Compatible Endpoints ==============

@gateway_bp.route('/v1/models', methods=['GET'])
def list_models():
    """List all available models (OpenAI compatible)."""
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify(error), status
    
    providers = db.session.query(Provider).all()
    
    models_list = []
    for provider in providers:
        for model in provider.models:
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


@gateway_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """
    OpenAI-compatible chat completions endpoint.
    使用三层架构处理请求：
    1. API层：解析请求
    2. 抽象层：转换消息和工具格式
    3. 供应商层：调用具体 API
    """
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify(error), status
    
    data = request.get_json()
    
    model_name = data.get('model')
    if not model_name:
        return jsonify({'detail': 'Model is required'}), 400
    
    messages = data.get('messages', [])
    if not messages:
        return jsonify({'detail': 'Messages are required'}), 400
    
    # 解析模型
    provider_instance, db_provider, db_model = resolve_model(model_name)
    if not provider_instance:
        return jsonify({
            'detail': f"Model '{model_name}' not found. Please configure it in the providers section."
        }), 404
    
    # 使用抽象层创建请求对象
    try:
        chat_request = ChatRequest.from_openai_format(data)
    except Exception as e:
        return jsonify({'detail': f'Invalid request format: {str(e)}'}), 400
    
    # 检查是否流式请求
    stream = data.get('stream', False)
    
    try:
        if stream:
            return stream_chat_response(provider_instance, chat_request, model_name)
        else:
            # 非流式请求
            response = provider_instance.chat(chat_request)
            return jsonify(response.to_openai_format())
    
    except ValueError as e:
        return jsonify({'detail': str(e)}), 400
    except Exception as e:
        return jsonify({'detail': f'Provider error: {str(e)}'}), 500


def stream_chat_response(provider_instance, chat_request: ChatRequest, model_name: str) -> Response:
    """
    流式聊天响应
    
    Args:
        provider_instance: 供应商实例
        chat_request: 聊天请求对象
        model_name: 模型名称
    
    Returns:
        Flask Response 对象
    """
    def generate() -> Generator[str, None, None]:
        try:
            for chunk in provider_instance.stream_chat(chat_request):
                yield chunk.to_sse("openai")
            
            # 发送结束标记
            yield "data: [DONE]\n\n"
        
        except Exception as e:
            error_chunk = StreamChunk(
                id="error",
                model=model_name,
                delta_content=f"Error: {str(e)}"
            )
            yield error_chunk.to_sse("openai")
            yield "data: [DONE]\n\n"
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


# ============== Anthropic Compatible Endpoints ==============

@gateway_bp.route('/v1/messages', methods=['POST'])
def anthropic_messages():
    """
    Anthropic-compatible messages endpoint.
    支持将 Anthropic 格式转换为内部抽象格式，然后调用供应商 API。
    """
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify(error), status
    
    data = request.get_json()
    
    model_name = data.get('model')
    if not model_name:
        return jsonify({'detail': 'Model is required'}), 400
    
    max_tokens = data.get('max_tokens', 4096)
    
    # 解析模型
    provider_instance, db_provider, db_model = resolve_model(model_name)
    if not provider_instance:
        return jsonify({
            'detail': f"Model '{model_name}' not found. Please configure it in the providers section."
        }), 404
    
    # 使用抽象层创建请求对象（从 Anthropic 格式）
    try:
        chat_request = ChatRequest.from_anthropic_format(data)
        chat_request.max_tokens = max_tokens
    except Exception as e:
        return jsonify({'detail': f'Invalid request format: {str(e)}'}), 400
    
    # 检查是否流式请求
    stream = data.get('stream', False)
    
    try:
        if stream:
            return stream_anthropic_response(provider_instance, chat_request, model_name)
        else:
            # 非流式请求
            response = provider_instance.chat(chat_request)
            return jsonify(response.to_anthropic_format())
    
    except ValueError as e:
        return jsonify({'detail': str(e)}), 400
    except Exception as e:
        return jsonify({'detail': f'Provider error: {str(e)}'}), 500


def stream_anthropic_response(provider_instance, chat_request: ChatRequest, model_name: str) -> Response:
    """
    流式 Anthropic 响应
    
    Args:
        provider_instance: 供应商实例
        chat_request: 聊天请求对象
        model_name: 模型名称
    
    Returns:
        Flask Response 对象
    """
    def generate() -> Generator[str, None, None]:
        try:
            # 发送消息开始事件
            yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': 'msg_' + str(int(time.time())), 'type': 'message', 'role': 'assistant', 'model': model_name}})}\n\n"
            
            for chunk in provider_instance.stream_chat(chat_request):
                yield chunk.to_sse("anthropic")
            
            # 发送消息结束事件
            yield "event: message_stop\ndata: {}\n\n"
        
        except Exception as e:
            error_event = {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": str(e)
                }
            }
            yield f"event: error\ndata: {json.dumps(error_event)}\n\n"
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


# ============== Provider Management Endpoints ==============

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