"""
AI Gateway API router.
Provides OpenAI-compatible and Anthropic-compatible endpoints.
"""
from flask import Blueprint, request, jsonify, Response
from datetime import datetime
import json
import time
import os

from app import db
from app.models import Provider, Model, ApiKey, User
from app.routes.users import token_required
from jose import JWTError, jwt

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


def resolve_model(model_name):
    """Resolve a model name to its provider and model configuration."""
    db_model = db.session.query(Model).filter(Model.name == model_name).first()
    
    if db_model:
        db_provider = db.session.query(Provider).filter(
            Provider.id == db_model.provider_id
        ).first()
        if db_provider:
            return db_provider, db_model
    
    return None, None


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
    
    # Resolve model
    provider, db_model = resolve_model(model_name)
    if not provider:
        return jsonify({
            'detail': f"Model '{model_name}' not found. Please configure it in the providers section."
        }), 404
    
    # For now, return a placeholder response
    # In a real implementation, you would call the provider's API
    stream = data.get('stream', False)
    
    if stream:
        return stream_response_placeholder(model_name, messages)
    else:
        return jsonify({
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"This is a placeholder response. Provider: {provider.name}, Model: {model_name}. Please implement the actual provider integration."
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        })


def stream_response_placeholder(model_name, messages):
    """Placeholder for streaming response."""
    def generate():
        response_text = f"This is a streaming placeholder response for model {model_name}."
        words = response_text.split()
        
        for i, word in enumerate(words):
            chunk = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "content": word + " "
                    } if i < len(words) - 1 else {"content": word},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(chunk)}\n\n"
        
        # Send final chunk
        final_chunk = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
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
    """
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        return jsonify(error), status
    
    data = request.get_json()
    
    model_name = data.get('model')
    if not model_name:
        return jsonify({'detail': 'Model is required'}), 400
    
    # Resolve model
    provider, db_model = resolve_model(model_name)
    if not provider:
        return jsonify({
            'detail': f"Model '{model_name}' not found. Please configure it in the providers section."
        }), 404
    
    # Return placeholder response
    return jsonify({
        "id": f"msg_{int(time.time())}",
        "type": "message",
        "role": "assistant",
        "content": [{
            "type": "text",
            "text": f"This is a placeholder Anthropic response. Provider: {provider.name}, Model: {model_name}."
        }],
        "model": model_name,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0
        }
    })