"""
Provider and Model management routes.
"""
from flask import Blueprint, request, jsonify
from functools import wraps
import os

from app import db
from app.models import Provider, Model
from app.routes.users import token_required

providers_bp = Blueprint('providers', __name__)


# ============== Provider Endpoints ==============

@providers_bp.route('/providers/', methods=['GET'])
@token_required
def list_providers(current_user):
    """List all providers."""
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 100, type=int)
    providers = db.session.query(Provider).offset(skip).limit(limit).all()
    return jsonify([p.to_dict() for p in providers])


@providers_bp.route('/providers/', methods=['POST'])
@token_required
def create_provider(current_user):
    """Create a new provider."""
    data = request.get_json()
    
    provider = Provider(
        name=data.get('name'),
        description=data.get('description'),
        api_key=data.get('api_key'),
        base_url=data.get('base_url')
    )
    db.session.add(provider)
    db.session.commit()
    db.session.refresh(provider)
    
    return jsonify(provider.to_dict()), 201


@providers_bp.route('/providers/<int:provider_id>', methods=['GET'])
@token_required
def get_provider(current_user, provider_id):
    """Get a specific provider."""
    provider = db.session.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        return jsonify({'detail': 'Provider not found'}), 404
    return jsonify(provider.to_dict())


@providers_bp.route('/providers/<int:provider_id>', methods=['PUT'])
@token_required
def update_provider(current_user, provider_id):
    """Update a provider."""
    provider = db.session.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        return jsonify({'detail': 'Provider not found'}), 404
    
    data = request.get_json()
    if 'name' in data:
        provider.name = data['name']
    if 'description' in data:
        provider.description = data['description']
    if 'api_key' in data:
        provider.api_key = data['api_key']
    if 'base_url' in data:
        provider.base_url = data['base_url']
    
    db.session.commit()
    db.session.refresh(provider)
    
    return jsonify(provider.to_dict())


@providers_bp.route('/providers/<int:provider_id>', methods=['DELETE'])
@token_required
def delete_provider(current_user, provider_id):
    """Delete a provider."""
    provider = db.session.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        return jsonify({'detail': 'Provider not found'}), 404
    
    db.session.delete(provider)
    db.session.commit()
    
    return '', 204


# ============== Model Endpoints ==============

@providers_bp.route('/models/', methods=['GET'])
@token_required
def list_models(current_user):
    """List all models."""
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 100, type=int)
    models = db.session.query(Model).offset(skip).limit(limit).all()
    return jsonify([m.to_dict() for m in models])


@providers_bp.route('/models/', methods=['POST'])
@token_required
def create_model(current_user):
    """Create a new model."""
    data = request.get_json()
    
    model = Model(
        name=data.get('name'),
        provider_id=data.get('provider_id'),
        context_size=data.get('context_size', 4096),
        input_size=data.get('input_size', 4096),
        input_price=data.get('input_price', 0.0),
        output_price=data.get('output_price', 0.0),
        cache_creation_price=data.get('cache_creation_price', 0.0),
        cache_hit_price=data.get('cache_hit_price', 0.0),
        support_kvcache=data.get('support_kvcache', False),
        support_image=data.get('support_image', False),
        support_audio=data.get('support_audio', False),
        support_video=data.get('support_video', False),
        support_file=data.get('support_file', False),
        support_web_search=data.get('support_web_search', False),
        support_tool_search=data.get('support_tool_search', False)
    )
    db.session.add(model)
    db.session.commit()
    db.session.refresh(model)
    
    return jsonify(model.to_dict()), 201


@providers_bp.route('/models/<int:model_id>', methods=['PUT'])
@token_required
def update_model(current_user, model_id):
    """Update a model."""
    model = db.session.query(Model).filter(Model.id == model_id).first()
    if not model:
        return jsonify({'detail': 'Model not found'}), 404
    
    data = request.get_json()
    for field in ['name', 'provider_id', 'context_size', 'input_size', 
                  'input_price', 'output_price', 'cache_creation_price', 'cache_hit_price',
                  'support_kvcache', 'support_image', 'support_audio', 'support_video',
                  'support_file', 'support_web_search', 'support_tool_search']:
        if field in data:
            setattr(model, field, data[field])
    
    db.session.commit()
    db.session.refresh(model)
    
    return jsonify(model.to_dict())


@providers_bp.route('/models/<int:model_id>', methods=['DELETE'])
@token_required
def delete_model(current_user, model_id):
    """Delete a model."""
    model = db.session.query(Model).filter(Model.id == model_id).first()
    if not model:
        return jsonify({'detail': 'Model not found'}), 404
    
    db.session.delete(model)
    db.session.commit()
    
    return '', 204