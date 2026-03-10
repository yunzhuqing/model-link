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


# ============== 请求解析辅助函数 ==============

def parse_openai_request(data: dict) -> ChatRequest:
    """从 OpenAI 格式解析请求"""
    import json
    from app.abstraction.messages import ContentBlock, ContentType
    from app.abstraction.tools import ToolParameter, ToolType
    
    messages = []
    for msg_data in data.get('messages', []):
        role = MessageRole(msg_data.get('role', 'user'))
        content = msg_data.get('content')
        name = msg_data.get('name')
        tool_call_id = msg_data.get('tool_call_id')
        reasoning_content = msg_data.get('reasoning_content')
        
        blocks = []
        if 'tool_calls' in msg_data:
            for tc in msg_data['tool_calls']:
                tc_id = tc.get('id')
                func = tc.get('function', {})
                tc_name = func.get('name')
                tc_args = func.get('arguments')
                
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except:
                        pass
                
                blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_args if isinstance(tc_args, dict) else {}))
        
        if isinstance(content, list):
            for item in content:
                item_type = item.get('type', 'text')
                if item_type == 'text':
                    blocks.append(ContentBlock.from_text(item.get('text', '')))
                elif item_type == 'image_url':
                    image_url = item.get('image_url', {})
                    url = image_url.get('url', '')
                    if url.startswith('data:'):
                        parts = url.split(',')
                        media_type = parts[0].replace('data:', '').replace(';base64', '')
                        data_str = parts[1] if len(parts) > 1 else ''
                        blocks.append(ContentBlock.from_image_base64(data_str, media_type))
                    else:
                        blocks.append(ContentBlock.from_image_url(url))
            content = blocks if blocks else None
        elif blocks:
            if content:
                blocks.insert(0, ContentBlock.from_text(content))
            content = blocks
        
        messages.append(Message(
            role=role,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            reasoning_content=reasoning_content
        ))
    
    tools = []
    for tool_data in data.get('tools', []):
        func = tool_data.get('function', tool_data)
        name = func.get('name', '')
        description = func.get('description', '')
        params_schema = func.get('parameters', {})
        
        parameters = []
        properties = params_schema.get('properties', {})
        required = params_schema.get('required', [])
        
        for param_name, param_schema in properties.items():
            parameters.append(ToolParameter(
                name=param_name,
                type=param_schema.get('type', 'string'),
                description=param_schema.get('description'),
                required=param_name in required,
                enum=param_schema.get('enum'),
                default=param_schema.get('default')
            ))
        
        tools.append(ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            tool_type=ToolType.FUNCTION
        ))
    
    known_keys = {
        'model', 'messages', 'temperature', 'top_p', 'max_tokens',
        'stream', 'tools', 'tool_choice', 'stop', 'presence_penalty',
        'frequency_penalty', 'user'
    }
    metadata = {k: v for k, v in data.items() if k not in known_keys}
    
    return ChatRequest(
        messages=messages,
        model=data.get('model', ''),
        temperature=data.get('temperature'),
        top_p=data.get('top_p'),
        max_tokens=data.get('max_tokens'),
        stream=data.get('stream', False),
        tools=tools,
        tool_choice=data.get('tool_choice'),
        stop=data.get('stop'),
        presence_penalty=data.get('presence_penalty'),
        frequency_penalty=data.get('frequency_penalty'),
        user=data.get('user'),
        metadata=metadata
    )


def parse_anthropic_request(data: dict) -> ChatRequest:
    """从 Anthropic 格式解析请求"""
    from app.abstraction.messages import ContentBlock
    from app.abstraction.tools import ToolParameter, ToolType
    
    messages = []
    
    if 'system' in data:
        messages.append(Message(
            role=MessageRole.SYSTEM,
            content=data['system']
        ))
    
    for msg_data in data.get('messages', []):
        role = MessageRole(msg_data.get('role', 'user'))
        content = msg_data.get('content', '')
        
        if isinstance(content, list):
            blocks = []
            for item in content:
                item_type = item.get('type', 'text')
                
                if item_type == 'text':
                    blocks.append(ContentBlock.from_text(item.get('text', '')))
                elif item_type == 'image':
                    source = item.get('source', {})
                    source_type = source.get('type', 'url')
                    
                    if source_type == 'url':
                        blocks.append(ContentBlock.from_image_url(source.get('url', '')))
                    elif source_type == 'base64':
                        blocks.append(ContentBlock.from_image_base64(
                            source.get('data', ''),
                            source.get('media_type', 'image/jpeg')
                        ))
            
            content = blocks
        
        messages.append(Message(role=role, content=content))
    
    tools = []
    for tool_data in data.get('tools', []):
        name = tool_data.get('name', '')
        description = tool_data.get('description', '')
        input_schema = tool_data.get('input_schema', {})
        
        parameters = []
        properties = input_schema.get('properties', {})
        required = input_schema.get('required', [])
        
        for param_name, param_schema in properties.items():
            parameters.append(ToolParameter(
                name=param_name,
                type=param_schema.get('type', 'string'),
                description=param_schema.get('description'),
                required=param_name in required,
                enum=param_schema.get('enum'),
                default=param_schema.get('default')
            ))
        
        tools.append(ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            tool_type=ToolType.FUNCTION
        ))
    
    return ChatRequest(
        messages=messages,
        model=data.get('model', ''),
        temperature=data.get('temperature'),
        top_p=data.get('top_p'),
        max_tokens=data.get('max_tokens'),
        stream=data.get('stream', False),
        tools=tools,
        tool_choice=data.get('tool_choice', {}).get('type') if data.get('tool_choice') else None,
        stop=data.get('stop_sequences'),
        metadata=data.get('metadata', {})
    )


def response_to_openai(response: ChatResponse) -> dict:
    """将响应转换为 OpenAI 格式"""
    import json
    
    choices = []
    for choice in response.choices:
        choice_dict = {
            'index': choice.index,
            'finish_reason': choice.finish_reason.value
        }
        
        if choice.message:
            msg = choice.message
            content = msg.get_text_content()
            
            choice_dict['message'] = {
                'role': msg.role.value,
                'content': content
            }
            
            if choice.reasoning_content:
                choice_dict['message']['reasoning_content'] = choice.reasoning_content
            
            if choice.tool_calls:
                choice_dict['message']['tool_calls'] = [
                    {
                        'id': tc.id,
                        'type': tc.call_type,
                        'function': {
                            'name': tc.name,
                            'arguments': json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in choice.tool_calls
                ]
        
        choices.append(choice_dict)
    
    return {
        'id': response.id,
        'object': 'chat.completion',
        'created': response.created,
        'model': response.model,
        'choices': choices,
        'usage': {
            'prompt_tokens': response.usage.prompt_tokens,
            'completion_tokens': response.usage.completion_tokens,
            'total_tokens': response.usage.total_tokens
        }
    }


def response_to_anthropic(response: ChatResponse) -> dict:
    """将响应转换为 Anthropic 格式"""
    content = []
    for choice in response.choices:
        if choice.message:
            text = choice.message.get_text_content()
            if text:
                content.append({'type': 'text', 'text': text})
            
            if choice.tool_calls:
                for tc in choice.tool_calls:
                    content.append({
                        'type': 'tool_use',
                        'id': tc.id,
                        'name': tc.name,
                        'input': tc.arguments
                    })
    
    return {
        'id': response.id,
        'type': 'message',
        'role': 'assistant',
        'content': content,
        'model': response.model,
        'stop_reason': response.choices[0].finish_reason.value if response.choices else 'end_turn',
        'usage': {
            'input_tokens': response.usage.prompt_tokens,
            'output_tokens': response.usage.completion_tokens
        }
    }

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
    
    # 解析请求
    try:
        chat_request = parse_openai_request(data)
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
            return jsonify(response_to_openai(response))
    
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
    
    # 使用辅助函数解析 Anthropic 格式请求
    try:
        chat_request = parse_anthropic_request(data)
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
            return jsonify(response_to_anthropic(response))
    
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