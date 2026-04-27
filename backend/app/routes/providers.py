"""
Provider and Model management routes.
"""
from datetime import datetime
from quart import Blueprint, request, jsonify
from functools import wraps
import os

from app import db
from app.models import Provider, Model, Group
from app.routes.users import token_required


def _maybe_create_tencentvod_api_token(provider: Provider) -> None:
    """
    For TencentVOD providers, auto-create an ApiToken via CreateAigcApiToken API
    if one hasn't been stored yet.

    Reads secret_id (AK), secret_key (SK), and optionally app_id from
    provider.extra_config and calls the TencentVOD API to get a permanent
    ApiToken, which is then stored in provider.api_key.

    Does nothing if api_key is already set.
    """
    if provider.type != 'tencentvod':
        return

    # Skip if api_key already exists
    if provider.api_key:
        return

    extra = provider.extra_config or {}
    secret_id = extra.get('secret_id', '').strip()
    secret_key = extra.get('secret_key', '').strip()
    app_id = extra.get('app_id')

    if not secret_id or not secret_key:
        return  # Cannot create token without credentials

    try:
        from app.providers.tencentvod.image_generation import create_aigc_api_token
        sub_app_id = int(app_id) if app_id else None
        api_token = create_aigc_api_token(secret_id, secret_key, sub_app_id)
        provider.api_key = api_token
    except Exception as e:
        # Log error but don't fail the provider save
        import sys
        print(f"[TencentVOD] Failed to create ApiToken: {e}", file=sys.stderr)

providers_bp = Blueprint('providers', __name__)


# ============== Provider Endpoints ==============

@providers_bp.route('/providers/', methods=['GET'])
@token_required
async def list_providers(current_user):
    """List all providers, optionally filtered by group_id."""
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 100, type=int)
    group_id = request.args.get('group_id', type=int)
    
    query = db.session.query(Provider)
    if group_id:
        query = query.filter(Provider.group_id == group_id)
    
    providers = query.offset(skip).limit(limit).all()
    return jsonify([p.to_dict() for p in providers])


@providers_bp.route('/providers/', methods=['POST'])
@token_required
async def create_provider(current_user):
    """Create a new provider in a group."""
    data = await request.get_json()
    
    group_id = data.get('group_id')
    if not group_id:
        return jsonify({'detail': 'group_id is required'}), 400
    
    # Verify group exists
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    # Check for duplicate name within the same group
    name = data.get('name')
    existing = db.session.query(Provider).filter(
        Provider.name == name,
        Provider.group_id == group_id
    ).first()
    if existing:
        return jsonify({'detail': f'A provider with name "{name}" already exists in this group'}), 409
    
    provider = Provider(
        name=name,
        type=data.get('type', 'openai'),
        description=data.get('description'),
        api_key=data.get('api_key'),
        base_url=data.get('base_url'),
        group_id=group_id,
        authorization=data.get('authorization', 'Authorization'),
        tags=data.get('tags') or [],
        extra_config=data.get('extra_config'),
        is_active=data.get('is_active', True)
    )
    db.session.add(provider)
    db.session.flush()  # Get provider.id without committing

    # Auto-create ApiToken for TencentVOD providers
    _maybe_create_tencentvod_api_token(provider)

    db.session.commit()
    db.session.refresh(provider)
    
    return jsonify(provider.to_dict()), 201


@providers_bp.route('/providers/<int:provider_id>', methods=['GET'])
@token_required
async def get_provider(current_user, provider_id):
    """Get a specific provider."""
    provider = db.session.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        return jsonify({'detail': 'Provider not found'}), 404
    return jsonify(provider.to_dict())


@providers_bp.route('/providers/<int:provider_id>', methods=['PUT'])
@token_required
async def update_provider(current_user, provider_id):
    """Update a provider."""
    provider = db.session.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        return jsonify({'detail': 'Provider not found'}), 404
    
    data = await request.get_json()
    if 'name' in data and data['name'] != provider.name:
        # Check for duplicate name within the same group
        existing = db.session.query(Provider).filter(
            Provider.name == data['name'],
            Provider.group_id == provider.group_id,
            Provider.id != provider_id
        ).first()
        if existing:
            return jsonify({'detail': f'A provider with name "{data["name"]}" already exists in this group'}), 409
        provider.name = data['name']
    if 'type' in data:
        provider.type = data['type']
    if 'description' in data:
        provider.description = data['description']
    if 'api_key' in data and data['api_key'] != '***':
        provider.api_key = data['api_key']
    if 'base_url' in data:
        provider.base_url = data['base_url']
    if 'authorization' in data:
        provider.authorization = data['authorization'] or 'Authorization'
    if 'is_active' in data:
        provider.is_active = bool(data['is_active'])
    if 'tags' in data:
        provider.tags = data['tags'] or []
    if 'extra_config' in data:
        # For tencentvod: if credentials changed, clear api_key so it gets regenerated
        if provider.type == 'tencentvod' and 'extra_config' in data:
            old_extra = provider.extra_config or {}
            new_extra = data['extra_config'] or {}
            if (old_extra.get('secret_id') != new_extra.get('secret_id') or
                    old_extra.get('secret_key') != new_extra.get('secret_key') or
                    old_extra.get('app_id') != new_extra.get('app_id')):
                provider.api_key = None  # Clear so it gets regenerated
        provider.extra_config = data['extra_config']

    # Auto-create ApiToken for TencentVOD providers if not already set
    _maybe_create_tencentvod_api_token(provider)

    db.session.commit()
    db.session.refresh(provider)
    
    return jsonify(provider.to_dict())


@providers_bp.route('/providers/<int:provider_id>', methods=['DELETE'])
@token_required
async def delete_provider(current_user, provider_id):
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
async def list_models(current_user):
    """List all models."""
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 100, type=int)
    models = db.session.query(Model).offset(skip).limit(limit).all()
    return jsonify([m.to_dict() for m in models])


@providers_bp.route('/models/', methods=['POST'])
@token_required
async def create_model(current_user):
    """Create a new model."""
    data = await request.get_json()
    
    # Parse retirement_time if provided as ISO string
    retirement_time = None
    if data.get('retirement_time'):
        try:
            retirement_time = datetime.fromisoformat(data['retirement_time'].replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return jsonify({'detail': 'Invalid retirement_time format. Use ISO 8601 (e.g. 2025-01-01T00:00:00)'}), 400

    model = Model(
        name=data.get('name'),
        alias=data.get('alias') if data.get('alias') else None,  # Alias for API access
        provider_id=data.get('provider_id'),
        context_size=data.get('context_size', 4096),
        input_size=data.get('input_size', 4096),
        output_size=data.get('output_size', 4096),
        reasoning_effort=data.get('reasoning_effort') or None,
        supported_image_formats=data.get('supported_image_formats') or None,
        pricing_tiers=data.get('pricing_tiers') or None,
        output_pricing=data.get('output_pricing') or None,
        input_price=data.get('input_price', 0.0),
        output_price=data.get('output_price', 0.0),
        cache_creation_price=data.get('cache_creation_price', 0.0),
        cache_5m_creation_price=data.get('cache_5m_creation_price', 0.0),
        cache_1h_creation_price=data.get('cache_1h_creation_price', 0.0),
        cache_hit_price=data.get('cache_hit_price', 0.0),
        currency=data.get('currency') or 'USD',
        retirement_time=retirement_time,
        rpm=data.get('rpm') or None,
        tpm=data.get('tpm') or None,
        discount=data.get('discount') if data.get('discount') is not None else 1.0,
        timeout=data.get('timeout') or None,
        support_kvcache=data.get('support_kvcache', False),
        support_image=data.get('support_image', False),
        support_audio=data.get('support_audio', False),
        support_video=data.get('support_video', False),
        support_file=data.get('support_file', False),
        support_web_search=data.get('support_web_search', False),
        support_tool_search=data.get('support_tool_search', False),
        support_thinking=data.get('support_thinking', False),
        support_online_image=data.get('support_online_image', True),
        support_online_video=data.get('support_online_video', True),
        support_embedding=data.get('support_embedding', False),
        is_active=data.get('is_active', True)
    )
    db.session.add(model)
    db.session.commit()
    db.session.refresh(model)
    
    return jsonify(model.to_dict()), 201


@providers_bp.route('/models/<int:model_id>', methods=['PUT'])
@token_required
async def update_model(current_user, model_id):
    """Update a model."""
    model = db.session.query(Model).filter(Model.id == model_id).first()
    if not model:
        return jsonify({'detail': 'Model not found'}), 404
    
    data = await request.get_json()
    for field in ['name', 'alias', 'provider_id', 'context_size', 'input_size', 'output_size',
                  'input_price', 'output_price', 'cache_creation_price', 'cache_5m_creation_price', 'cache_1h_creation_price', 'cache_hit_price',
                  'currency', 'rpm', 'tpm', 'discount', 'timeout',
                   'reasoning_effort', 'supported_image_formats', 'pricing_tiers', 'output_pricing',
                  'support_kvcache', 'support_image', 'support_audio', 'support_video',
                  'support_file', 'support_web_search', 'support_tool_search', 'support_thinking',
                  'support_online_image', 'support_online_video', 'support_embedding',
                  'is_active']:
        if field in data:
            # Handle alias/nullable strings - convert empty string to None
            if field in ('alias', 'reasoning_effort', 'supported_image_formats') and data[field] == '':
                setattr(model, field, None)
            else:
                setattr(model, field, data[field])

    # Handle retirement_time separately (ISO string → datetime)
    if 'retirement_time' in data:
        rt = data['retirement_time']
        if rt:
            try:
                model.retirement_time = datetime.fromisoformat(rt.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                return jsonify({'detail': 'Invalid retirement_time format. Use ISO 8601 (e.g. 2025-01-01T00:00:00)'}), 400
        else:
            model.retirement_time = None

    if not model.currency:
        model.currency = 'USD'

    db.session.commit()
    db.session.refresh(model)
    
    return jsonify(model.to_dict())


@providers_bp.route('/models/<int:model_id>', methods=['DELETE'])
@token_required
async def delete_model(current_user, model_id):
    """Delete a model."""
    model = db.session.query(Model).filter(Model.id == model_id).first()
    if not model:
        return jsonify({'detail': 'Model not found'}), 404
    
    db.session.delete(model)
    db.session.commit()
    
    return '', 204
