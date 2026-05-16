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
from app.routes.permissions import (
    _get_role,
    _is_root,
    _is_member,
    _is_admin_or_above_inner,
    check_permission,
    require_provider_permission,
)


def _maybe_create_tencentvod_api_token(provider: Provider) -> None:
    """
    For TencentVOD providers, auto-fetch or create an ApiToken.

    First checks for existing tokens via DescribeAigcApiTokens — if any exist,
    uses the first one. Otherwise creates a new token via CreateAigcApiToken.

    Reads secret_id (AK), secret_key (SK), and optionally app_id from
    provider.extra_config. The resulting ApiToken is stored in provider.api_key.

    Does nothing if api_key is already set.
    """
    if provider.type != 'tencentvod':
        return

    if provider.api_key:
        return

    extra = provider.extra_config or {}
    secret_id = extra.get('secret_id', '').strip()
    secret_key = extra.get('secret_key', '').strip()
    app_id = extra.get('app_id')

    if not secret_id or not secret_key:
        return

    try:
        from app.providers.tencentvod.image_generation import (
            create_aigc_api_token,
            describe_aigc_api_tokens,
        )
        sub_app_id = int(app_id) if app_id else None

        # Check for existing tokens first
        existing_tokens = describe_aigc_api_tokens(secret_id, secret_key, sub_app_id)
        if existing_tokens:
            provider.api_key = existing_tokens[0]
        else:
            provider.api_key = create_aigc_api_token(secret_id, secret_key, sub_app_id)
    except Exception as e:
        import sys
        print(f"[TencentVOD] Failed to get or create ApiToken: {e}", file=sys.stderr)

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
    """Create a new provider in a group. Root only."""
    data = await request.get_json()
    
    group_id = data.get('group_id')
    if not group_id:
        return jsonify({'detail': 'group_id is required'}), 400
    
    # Permission: requires provider.manage (default: root only)
    user_role = _get_role(group_id, current_user.id)
    if not check_permission(user_role, 'provider.manage'):
        return jsonify({'detail': 'Provider management is disabled for this group'}), 403
    
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
@require_provider_permission('provider.manage')
async def update_provider(current_user, provider_id):
    """Update a provider. Root only (controlled by provider.manage permission)."""
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
    if 'api_key' in data and data['api_key'] != Provider._mask_api_key(provider.api_key):
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


@providers_bp.route('/providers/<int:provider_id>/reveal-key', methods=['GET'])
@token_required
@require_provider_permission('provider.manage')
async def reveal_provider_key(current_user, provider_id):
    """Return the full (unmasked) api_key for a provider. Requires provider.manage."""
    provider = db.session.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        return jsonify({'detail': 'Provider not found'}), 404
    return jsonify({'api_key': provider.api_key or ''})


@providers_bp.route('/providers/<int:provider_id>', methods=['DELETE'])
@token_required
@require_provider_permission('provider.manage')
async def delete_provider(current_user, provider_id):
    """Delete a provider. Root only (controlled by provider.manage permission)."""
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
    """Create a new model. Root only."""
    data = await request.get_json()
    
    # Resolve group_id from provider_id for permission check
    provider_id = data.get('provider_id')
    if provider_id:
        provider = db.session.query(Provider).filter(Provider.id == provider_id).first()
        if provider:
            group_id = provider.group_id
            user_role = _get_role(group_id, current_user.id)
            if not check_permission(user_role, 'provider.manage'):
                return jsonify({'detail': 'Model management is disabled for this group'}), 403
    
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
        priority=data.get('priority', 0),
        traffic_ratio=data.get('traffic_ratio', 0),
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
    """Update a model.
    
    Root can update all fields (requires root.provider.manage).
    Admin can only update priority and traffic_ratio.
    Member cannot update anything.
    """
    model = db.session.query(Model).filter(Model.id == model_id).first()
    if not model:
        return jsonify({'detail': 'Model not found'}), 404
    
    # Resolve group_id from model's provider
    group_id = model.provider.group_id if model.provider else None
    if not group_id or not _is_member(group_id, current_user.id):
        return jsonify({'detail': 'You do not have access to this model'}), 403
    
    data = await request.get_json()

    # Strip read-only / computed fields that the frontend may accidentally send
    # id is the primary key; is_retired is a computed property from retirement_time
    for ro_field in ('id', 'is_retired'):
        data.pop(ro_field, None)

    # Determine allowed fields based on role
    admin_fields = {'priority', 'traffic_ratio'}
    all_fields = {'name', 'alias', 'provider_id', 'context_size', 'input_size', 'output_size',
                  'input_price', 'output_price', 'cache_creation_price', 'cache_5m_creation_price', 'cache_1h_creation_price', 'cache_hit_price',
                  'currency', 'rpm', 'tpm', 'discount', 'timeout',
                  'reasoning_effort', 'supported_image_formats', 'pricing_tiers', 'output_pricing',
                  'support_kvcache', 'support_image', 'support_audio', 'support_video',
                  'support_file', 'support_web_search', 'support_tool_search', 'support_thinking',
                  'support_online_image', 'support_online_video', 'support_embedding',
                  'is_active', 'priority', 'traffic_ratio', 'retirement_time'}
    
    is_root = _is_root(group_id, current_user.id)
    is_admin = _is_admin_or_above_inner(group_id, current_user.id)
    
    if is_root:
        user_role = _get_role(group_id, current_user.id)
        if not check_permission(user_role, 'provider.manage'):
            return jsonify({'detail': 'Model management is disabled for this group'}), 403
        allowed_fields = all_fields
    elif is_admin:
        user_role = _get_role(group_id, current_user.id)
        if not check_permission(user_role, 'model.priority') and not check_permission(user_role, 'model.traffic_ratio'):
            return jsonify({'detail': 'Model priority and traffic ratio management is disabled for this group'}), 403
        allowed_fields = set()
        if check_permission(user_role, 'model.priority'):
            allowed_fields.add('priority')
        if check_permission(user_role, 'model.traffic_ratio'):
            allowed_fields.add('traffic_ratio')
    else:
        return jsonify({'detail': 'Only admins and root can update models'}), 403
    
    # Reject if any non-allowed field is in the request
    requested_fields = set(data.keys())
    if not requested_fields.issubset(allowed_fields):
        forbidden = requested_fields - allowed_fields
        return jsonify({'detail': f'You cannot modify these fields: {", ".join(sorted(forbidden))}'}), 403
    
    for field in allowed_fields:
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
    """Delete a model. Root only (requires root.provider.manage)."""
    model = db.session.query(Model).filter(Model.id == model_id).first()
    if not model:
        return jsonify({'detail': 'Model not found'}), 404
    
    # Resolve group_id from model's provider
    group_id = model.provider.group_id if model.provider else None
    if not group_id or not _is_member(group_id, current_user.id):
        return jsonify({'detail': 'You do not have access to this model'}), 403
    
    user_role = _get_role(group_id, current_user.id)
    if not check_permission(user_role, 'provider.manage'):
        return jsonify({'detail': 'Model management is disabled for this group'}), 403
    
    db.session.delete(model)
    db.session.commit()
    
    return '', 204


# ============== Rate Limit Status API ==============

@providers_bp.route('/providers/rate-limits', methods=['GET'])
@token_required
async def get_all_rate_limits(current_user):
    """Get rate limit status for all models across all groups the user has access to."""
    from app.rate_limiter import get_rate_limiter

    limiter = get_rate_limiter()
    if limiter is None:
        return jsonify({'models': [], 'note': 'Rate limiter not initialized (in-memory mode)'})

    models = db.session.query(Model).filter(
        Model.is_active == True,
        db.or_(Model.rpm.isnot(None), Model.tpm.isnot(None))
    ).all()

    result = []
    for model in models:
        status = limiter.get_status(model.id, model.provider.group_id)
        if status is not None:
            rpm_limit = model.rpm
            tpm_limit = model.tpm
            rpm_remaining = status['rpm']['remaining']
            tpm_remaining = status['tpm']['remaining']

            status['model_id'] = model.id
            status['model_name'] = model.name
            status['alias'] = model.alias
            status['provider_id'] = model.provider_id
            status['provider_name'] = model.provider.name if model.provider else None
            status['group_id'] = model.provider.group_id
            status['rpm_limit'] = rpm_limit
            status['tpm_limit'] = tpm_limit
            status['rpm_remaining'] = rpm_remaining
            status['tpm_remaining'] = tpm_remaining
            status['rpm_used'] = (rpm_limit - rpm_remaining) if (rpm_limit is not None and rpm_remaining is not None) else 0
            status['tpm_used'] = (tpm_limit - tpm_remaining) if (tpm_limit is not None and tpm_remaining is not None) else 0
            status['rpm_pct'] = round(status['rpm_used'] / rpm_limit * 100, 1) if rpm_limit else 0
            status['tpm_pct'] = round(status['tpm_used'] / tpm_limit * 100, 1) if tpm_limit else 0
            result.append(status)

    return jsonify({'models': result})


@providers_bp.route('/providers/rate-limits/<int:model_id>', methods=['GET'])
@token_required
async def get_model_rate_limit(current_user, model_id):
    """Get rate limit status for a specific model."""
    from app.rate_limiter import get_rate_limiter

    model = db.session.query(Model).filter(Model.id == model_id).first()
    if not model:
        return jsonify({'detail': 'Model not found'}), 404

    limiter = get_rate_limiter()
    if limiter is None:
        return jsonify({'model_id': model.id, 'model_name': model.name,
                       'rpm': model.rpm, 'tpm': model.tpm,
                       'note': 'Rate limiter not initialized (in-memory mode)'})

    status = limiter.get_status(model.id, model.provider.group_id)
    if status is None:
        return jsonify({
            'model_id': model.id,
            'model_name': model.name,
            'rpm': model.rpm,
            'tpm': model.tpm,
            'current_rpm_count': 0,
            'current_tpm_count': 0,
            'rpm_remaining': model.rpm,
            'tpm_remaining': model.tpm,
            'api_keys': [],
            'note': 'No active rate limiting for this model'
        })

    return jsonify(status)


# ============== Workspace Rate Limit CRUD + Status API ==============

@providers_bp.route('/workspaces', methods=['GET'])
@token_required
async def list_workspaces(current_user):
    """List all workspaces."""
    from app.models import Workspace
    workspaces = db.session.query(Workspace).order_by(Workspace.id).all()
    return jsonify([ws.to_dict() for ws in workspaces])


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits', methods=['GET'])
@token_required
async def get_workspace_rate_limits(current_user, workspace_id):
    """List all workspace-level rate limit configurations and their live status."""
    from app.rate_limiter import get_rate_limiter
    from app.models import Workspace, WorkspaceRateLimit, Model, Provider, Group

    ws = db.session.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        return jsonify({'detail': 'Workspace not found'}), 404

    limits = db.session.query(WorkspaceRateLimit).filter(
        WorkspaceRateLimit.workspace_id == workspace_id
    ).all()

    limiter = get_rate_limiter()

    # Collect all model names for per-provider lookup
    model_names = list(set(rl.model_name for rl in limits))

    # Find group-level models matching these model names (alias or name)
    # to show per-provider breakdown
    provider_models = {}  # model_name -> [{provider_name, group_name, ...}]
    if model_names:
        matching_models = db.session.query(Model).join(Provider).join(Group).filter(
            Model.is_active == True,
            Provider.is_active == True,
            db.or_(
                Model.name.in_(model_names),
                Model.alias.in_(model_names),
            )
        ).all()
        for m in matching_models:
            key = m.alias or m.name
            if key not in provider_models:
                provider_models[key] = []
            # Get group-level status for this specific model
            grp_status = limiter.get_status(m.id, m.provider.group_id)
            rpm_limit_g = m.rpm
            tpm_limit_g = m.tpm
            rpm_remaining = grp_status['rpm'].get('remaining')
            tpm_remaining = grp_status['tpm'].get('remaining')
            rpm_used_g = max(0, rpm_limit_g - int(rpm_remaining)) if rpm_limit_g and rpm_remaining is not None else 0
            tpm_used_g = max(0, tpm_limit_g - int(tpm_remaining)) if tpm_limit_g and tpm_remaining is not None else 0
            provider_models[key].append({
                'provider_name': m.provider.name if m.provider else None,
                'provider_type': m.provider.type if m.provider else None,
                'provider_id': m.provider_id,
                'group_name': m.provider.group.name if m.provider and m.provider.group else None,
                'model_id': m.id,
                'rpm_limit': rpm_limit_g,
                'tpm_limit': tpm_limit_g,
                'rpm_used': rpm_used_g,
                'tpm_used': tpm_used_g,
            })

    # Build API key lookup: preview -> {name, group_name}
    # API keys belong to this workspace (via workspace_id or group.workspace_id)
    from app.models import ApiKey
    ws_api_keys = db.session.query(ApiKey).filter(
        db.or_(
            ApiKey.workspace_id == workspace_id,
            ApiKey.group_id.in_(
                db.session.query(Group.id).filter(Group.workspace_id == workspace_id)
            ),
        )
    ).all()
    apikey_info_map = {}  # preview_prefix -> {name, group_name}
    for ak in ws_api_keys:
        if ak.key:
            preview = ak.key[:8] + '...'
            apikey_info_map[preview] = {
                'name': ak.name,
                'group_name': ak.group.name if ak.group else None,
            }

    result = []
    for rl in limits:
        status = limiter.get_ws_status(
            workspace_id, rl.model_name,
            ws_rpm_limit=rl.rpm, ws_tpm_limit=rl.tpm,
            provider_type=rl.provider_type, provider_id=rl.provider_id,
        )
        # Add historical usage (1m, 5m, 10m)
        history = limiter.get_ws_history(
            workspace_id, rl.model_name,
            ws_rpm_limit=rl.rpm, ws_tpm_limit=rl.tpm,
            provider_type=rl.provider_type, provider_id=rl.provider_id,
        )
        status['history'] = history
        status['id'] = rl.id
        status['workspace_id'] = workspace_id
        status['workspace_name'] = ws.name
        status['provider_type'] = rl.provider_type
        status['provider_id'] = rl.provider_id
        status['provider_name'] = rl.provider.name if rl.provider else None
        status['rpm_limit'] = rl.rpm
        status['tpm_limit'] = rl.tpm
        # Enrich apikeys with name and group info
        enriched_apikeys = []
        for ak_usage in status.get('apikeys', []):
            preview = ak_usage.get('preview', '')
            info = apikey_info_map.get(preview, {})
            enriched_apikeys.append({
                **ak_usage,
                'api_key_name': info.get('name'),
                'group_name': info.get('group_name'),
            })
        status['apikeys'] = enriched_apikeys
        # Add per-provider breakdown (group-level models for this model_name)
        status['providers'] = provider_models.get(rl.model_name, [])
        result.append(status)

    return jsonify({'workspace': ws.to_dict(), 'rate_limits': result})


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits', methods=['POST'])
@token_required
async def create_workspace_rate_limit(current_user, workspace_id):
    """Create a new workspace-level rate limit for a model + provider_type (+ optional provider_id)."""
    from app.models import Workspace, WorkspaceRateLimit

    ws = db.session.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        return jsonify({'detail': 'Workspace not found'}), 404

    try:
        data = await request.get_json(force=True, silent=True)
    except UnicodeDecodeError:
        data = None
    if not data:
        return jsonify({'detail': 'Invalid JSON'}), 400

    model_name = data.get('model_name')
    if not model_name:
        return jsonify({'detail': 'model_name is required'}), 400

    provider_type = data.get('provider_type')
    if not provider_type:
        return jsonify({'detail': 'provider_type is required'}), 400

    provider_id = data.get('provider_id')  # optional — NULL means shared for all accounts of this type

    # Check for duplicate (workspace_id, model_name, provider_type, provider_id)
    q = db.session.query(WorkspaceRateLimit).filter(
        WorkspaceRateLimit.workspace_id == workspace_id,
        WorkspaceRateLimit.model_name == model_name,
        WorkspaceRateLimit.provider_type == provider_type,
    )
    if provider_id is not None:
        q = q.filter(WorkspaceRateLimit.provider_id == provider_id)
    else:
        q = q.filter(WorkspaceRateLimit.provider_id.is_(None))
    existing = q.first()
    if existing:
        label = f'{provider_type}' + (f' (provider #{provider_id})' if provider_id else ' (shared)')
        return jsonify({'detail': f'Rate limit for model "{model_name}" / {label} already exists'}), 409

    rl = WorkspaceRateLimit(
        workspace_id=workspace_id,
        model_name=model_name,
        provider_type=provider_type,
        provider_id=provider_id,
        rpm=data.get('rpm'),
        tpm=data.get('tpm'),
    )
    db.session.add(rl)
    db.session.commit()
    return jsonify(rl.to_dict()), 201


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits/<int:rate_limit_id>', methods=['PUT'])
@token_required
async def update_workspace_rate_limit(current_user, workspace_id, rate_limit_id):
    """Update a workspace-level rate limit."""
    from app.models import WorkspaceRateLimit

    rl = db.session.query(WorkspaceRateLimit).filter(
        WorkspaceRateLimit.id == rate_limit_id,
        WorkspaceRateLimit.workspace_id == workspace_id,
    ).first()
    if not rl:
        return jsonify({'detail': 'Rate limit not found'}), 404

    try:
        data = await request.get_json(force=True, silent=True)
    except UnicodeDecodeError:
        data = None
    if not data:
        return jsonify({'detail': 'Invalid JSON'}), 400

    if 'rpm' in data:
        rl.rpm = data['rpm']
    if 'tpm' in data:
        rl.tpm = data['tpm']
    if 'model_name' in data:
        rl.model_name = data['model_name']
    if 'provider_type' in data:
        rl.provider_type = data['provider_type']
    if 'provider_id' in data:
        rl.provider_id = data['provider_id']

    db.session.commit()
    return jsonify(rl.to_dict())


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits/<int:rate_limit_id>', methods=['DELETE'])
@token_required
async def delete_workspace_rate_limit(current_user, workspace_id, rate_limit_id):
    """Delete a workspace-level rate limit."""
    from app.models import WorkspaceRateLimit

    rl = db.session.query(WorkspaceRateLimit).filter(
        WorkspaceRateLimit.id == rate_limit_id,
        WorkspaceRateLimit.workspace_id == workspace_id,
    ).first()
    if not rl:
        return jsonify({'detail': 'Rate limit not found'}), 404

    db.session.delete(rl)
    db.session.commit()
    return '', 204


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits/status', methods=['GET'])
@token_required
async def get_workspace_rate_limit_status(current_user, workspace_id):
    """Get live rate limit status for a specific model in a workspace."""
    from app.rate_limiter import get_rate_limiter
    from app.models import Workspace, WorkspaceRateLimit

    ws = db.session.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        return jsonify({'detail': 'Workspace not found'}), 404

    model_name = request.args.get('model_name')
    if not model_name:
        return jsonify({'detail': 'model_name query parameter is required'}), 400

    rl = db.session.query(WorkspaceRateLimit).filter(
        WorkspaceRateLimit.workspace_id == workspace_id,
        WorkspaceRateLimit.model_name == model_name,
    ).first()

    limiter = get_rate_limiter()
    ws_rpm = rl.rpm if rl else None
    ws_tpm = rl.tpm if rl else None
    status = limiter.get_ws_status(workspace_id, model_name, ws_rpm_limit=ws_rpm, ws_tpm_limit=ws_tpm)
    status['workspace_id'] = workspace_id
    status['workspace_name'] = ws.name
    return jsonify(status)
