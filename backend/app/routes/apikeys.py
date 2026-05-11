"""
API Key and Group management routes.

Cache integration:
  - API key detail/info endpoints read from cache first (cache.get_api_key_info_by_id).
  - Create / update / delete / regenerate operations invalidate the cache
    (cache.invalidate_api_key_by_id) so stale data is never served.
"""
from quart import Blueprint, request, jsonify
from datetime import datetime
import secrets

from app import db
from app.models import ApiKey, ApiKeyBudget
from app.routes.users import token_required
from app.models import check_permission
from app.routes.permissions import (
    _get_role,
    _is_admin_or_above_inner,
    check_group_permission,
    require_permission,
    require_apikey_permission,
)
from app.group_service import (
    get_group_by_id,
    create_group as _svc_create_group,
    update_group as _svc_update_group,
    delete_group as _svc_delete_group,
)

apikeys_bp = Blueprint('apikeys', __name__)


def generate_api_key():
    """Generate a secure random API key with sk- prefix (OpenAI compatible)."""
    return f"sk-{secrets.token_hex(24)}"


# ============== Group Management ==============

@apikeys_bp.route('/groups/', methods=['GET'])
@token_required
async def list_groups(current_user):
    """List all groups the current user belongs to, including the user's role."""
    from app.models import UserGroup

    result = []
    for g in current_user.groups:
        group_dict = g.to_dict()
        # Include the current user's role in this group
        ug = db.session.query(UserGroup).filter(
            UserGroup.group_id == g.id,
            UserGroup.user_id == current_user.id,
        ).first()
        group_dict['my_role'] = ug.role if ug else None
        result.append(group_dict)

    return jsonify(result)


@apikeys_bp.route('/groups/', methods=['POST'])
@token_required
async def create_group(current_user):
    """Create a new group."""
    from app.models import UserGroup

    data = await request.get_json()

    group, err = _svc_create_group(
        name=data.get('name'),
        description=data.get('description'),
    )
    if err:
        return jsonify({'detail': err}), 400

    # Creator is automatically a root member
    user_group = UserGroup(
        user_id=current_user.id,
        group_id=group.id,
        role='root',
    )
    db.session.add(user_group)
    db.session.commit()
    db.session.refresh(group)

    return jsonify(group.to_dict()), 201


@apikeys_bp.route('/groups/<int:group_id>', methods=['GET'])
@token_required
async def get_group(current_user, group_id):
    """Get a specific group."""
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404

    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403

    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>', methods=['PUT'])
@token_required
@require_permission('group.manage')
async def update_group(current_user, group_id):
    """Update a group. Root only (controlled by group.manage permission)."""
    data = await request.get_json()
    kwargs = {}
    if 'name' in data:
        kwargs['name'] = data['name']
    if 'description' in data:
        kwargs['description'] = data['description']
    if 'monitoring_config' in data:
        kwargs['monitoring_config'] = data['monitoring_config']
    if 'tags' in data:
        kwargs['tags'] = data['tags']

    group, err = _svc_update_group(group_id, **kwargs)
    if err:
        return jsonify({'detail': err}), 404 if err == 'Group not found' else 400

    db.session.commit()
    db.session.refresh(group)
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@token_required
@require_permission('group.manage')
async def delete_group(current_user, group_id):
    """Delete a group. Root only (controlled by group.manage permission)."""
    ok, err = _svc_delete_group(group_id)
    if err:
        return jsonify({'detail': err}), 404

    db.session.commit()
    return '', 204


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>', methods=['POST'])
@token_required
@require_permission('member.manage')
async def add_user_to_group(current_user, group_id, user_id):
    """Add a user to a group. Admin or above only (controlled by member.manage permission)."""
    from app.models import User

    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404

    user = db.session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({'detail': 'User not found'}), 404

    if user in group.users:
        return jsonify({'detail': 'User is already a member of this group'}), 400

    group.users.append(user)
    db.session.commit()
    db.session.refresh(group)

    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>', methods=['DELETE'])
@token_required
@require_permission('member.manage')
async def remove_user_from_group(current_user, group_id, user_id):
    """Remove a user from a group. Admin or above only (controlled by member.manage permission)."""
    from app.models import User

    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404

    user = db.session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({'detail': 'User not found'}), 404

    if user not in group.users:
        return jsonify({'detail': 'User is not a member of this group'}), 400

    group.users.remove(user)
    db.session.commit()
    db.session.refresh(group)

    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/invite', methods=['POST'])
@token_required
@require_permission('member.invite')
async def invite_member(current_user, group_id):
    """Invite a member to a group by email. Admin or above only (controlled by member.invite permission)."""
    from app.models import User, UserGroup

    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    data = await request.get_json()
    email = data.get('email')
    role = data.get('role', 'member')  # Default to member role
    
    # Validate role
    if role not in ['root', 'admin', 'member']:
        return jsonify({'detail': 'Invalid role. Must be root, admin, or member'}), 400
    
    if not email:
        return jsonify({'detail': 'Email is required'}), 400
    
    # Find user by email
    user = db.session.query(User).filter(User.email == email).first()
    if not user:
        return jsonify({'detail': 'User with this email not found'}), 404
    
    if user in group.users:
        return jsonify({'detail': 'User is already a member of this group'}), 400
    
    # Add user with specified role
    user_group = UserGroup(
        user_id=user.id,
        group_id=group.id,
        role=role
    )
    db.session.add(user_group)
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>/role', methods=['PUT'])
@token_required
@require_permission('member.manage')
async def update_member_role(current_user, group_id, user_id):
    """Update a member's role in a group. Root and admin (with permission) can change roles."""
    from app.models import User, UserGroup
    
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    data = await request.get_json()
    new_role = data.get('role')
    
    # Validate role
    if new_role not in ['root', 'admin', 'member']:
        return jsonify({'detail': 'Invalid role. Must be root, admin, or member'}), 400
    
    # Find the user's membership
    user_group = db.session.query(UserGroup).filter(
        UserGroup.group_id == group_id,
        UserGroup.user_id == user_id
    ).first()
    
    if not user_group:
        return jsonify({'detail': 'User is not a member of this group'}), 400
    
    current_role = _get_role(group_id, current_user.id)
    
    # Only root can change another root's role
    if user_group.role == 'root' and current_role != 'root':
        return jsonify({'detail': 'Only root can change another root\'s role'}), 403
    
    # Admin cannot promote a member to root (only root can)
    if new_role == 'root' and current_role != 'root':
        return jsonify({'detail': 'Only root can promote members to root'}), 403
    
    user_group.role = new_role
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


# ============== Model Share Management ==============

@apikeys_bp.route('/groups/<int:group_id>/model-shares', methods=['GET'])
@token_required
async def list_model_shares(current_user, group_id):
    """List models shared to this group from other groups."""
    from app.models import Group, ModelShare, Model as MLModel, Provider

    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404

    if current_user not in group.users:
        return jsonify({'detail': 'You do not have access to this group'}), 403

    shares = (
        db.session.query(ModelShare, MLModel, Provider, Group)
        .join(MLModel, ModelShare.model_id == MLModel.id)
        .join(Provider, MLModel.provider_id == Provider.id)
        .join(Group, ModelShare.source_group_id == Group.id)
        .filter(ModelShare.target_group_id == group_id)
        .all()
    )

    result = []
    for share, model, provider, source_group in shares:
        result.append({
            'id': share.id,
            'model_id': model.id,
            'model_name': model.name,
            'model_alias': model.alias,
            'provider_name': provider.name,
            'provider_type': provider.type,
            'source_group_id': source_group.id,
            'source_group_name': source_group.name,
            'created_at': share.created_at.isoformat() if share.created_at else None,
            # Full model details for display
            'context_size': model.context_size,
            'input_size': model.input_size,
            'output_size': model.output_size,
            'input_price': float(model.input_price) if model.input_price else 0,
            'output_price': float(model.output_price) if model.output_price else 0,
            'currency': model.currency or 'USD',
            'is_active': model.is_active,
            'support_image': model.support_image,
            'support_audio': model.support_audio,
            'support_video': model.support_video,
            'support_file': model.support_file,
            'support_web_search': model.support_web_search,
            'support_thinking': model.support_thinking,
            'support_embedding': model.support_embedding,
            'rpm': model.rpm,
            'tpm': model.tpm,
        })

    return jsonify({'shares': result})


@apikeys_bp.route('/groups/<int:group_id>/model-shares', methods=['POST'])
@token_required
@require_permission('member.manage')
async def add_model_share(current_user, group_id):
    """Share a model from another group to this group."""
    from app.models import ModelShare, Model as MLModel

    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404

    if current_user not in group.users:
        return jsonify({'detail': 'You do not have access to this group'}), 403

    data = await request.get_json()
    model_id = data.get('model_id')
    if not model_id:
        return jsonify({'detail': 'model_id is required'}), 400

    model = db.session.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        return jsonify({'detail': 'Model not found'}), 404

    # Determine source group from the model's provider
    if not model.provider or not model.provider.group_id:
        return jsonify({'detail': 'Model has no source group'}), 400

    source_group_id = model.provider.group_id
    if source_group_id == group_id:
        return jsonify({'detail': 'Cannot share a model to its own group'}), 400

    # Check if already shared
    existing = db.session.query(ModelShare).filter(
        ModelShare.model_id == model_id,
        ModelShare.target_group_id == group_id,
    ).first()
    if existing:
        return jsonify({'detail': 'Model is already shared to this group'}), 409

    share = ModelShare(
        model_id=model_id,
        source_group_id=source_group_id,
        target_group_id=group_id,
        created_by=current_user.id,
    )
    db.session.add(share)
    db.session.commit()

    return jsonify({
        'id': share.id,
        'model_id': share.model_id,
        'source_group_id': share.source_group_id,
        'target_group_id': share.target_group_id,
        'created_at': share.created_at.isoformat() if share.created_at else None,
    }), 201


@apikeys_bp.route('/groups/<int:group_id>/model-shares/<int:share_id>', methods=['DELETE'])
@token_required
@require_permission('member.manage')
async def remove_model_share(current_user, group_id, share_id):
    """Remove a model share from this group."""
    from app.models import ModelShare

    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404

    if current_user not in group.users:
        return jsonify({'detail': 'You do not have access to this group'}), 403

    share = db.session.query(ModelShare).filter(
        ModelShare.id == share_id,
        ModelShare.target_group_id == group_id,
    ).first()
    if not share:
        return jsonify({'detail': 'Model share not found'}), 404

    db.session.delete(share)
    db.session.commit()

    return jsonify({'detail': 'Model share removed'})


# ============== API Key Management ==============

@apikeys_bp.route('/apikeys/', methods=['GET'])
@token_required
async def list_api_keys(current_user):
    """List the current user's own API keys only."""
    api_keys = []
    for group in current_user.groups:
        api_keys.extend([k.to_dict_with_group() for k in group.api_keys if k.user_id == current_user.id])
    return jsonify(api_keys)


@apikeys_bp.route('/apikeys/group/<int:group_id>', methods=['GET'])
@token_required
async def list_api_keys_by_group(current_user, group_id):
    """List all API keys for a specific group."""
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    # Members can only see their own API keys; admins/root see all
    if _is_admin_or_above_inner(group_id, current_user.id):
        return jsonify([k.to_dict() for k in group.api_keys])
    else:
        return jsonify([k.to_dict() for k in group.api_keys if k.user_id == current_user.id])


@apikeys_bp.route('/apikeys/<int:api_key_id>', methods=['GET'])
@token_required
async def get_api_key(current_user, api_key_id):
    """Get a specific API key. Tries cache first for basic info."""
    # Try cache first for a quick response
    from app.cache import get_cache
    cache = get_cache()
    cached = cache.get_api_key_info_by_id(api_key_id)
    if cached is not None:
        # Still need to verify group membership from DB
        api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
        if not api_key:
            cache.invalidate_api_key_by_id(api_key_id)
            return jsonify({'detail': 'API key not found'}), 404
        if current_user not in api_key.group.users:
            return jsonify({'detail': 'You do not have access to this API key'}), 403
        if not _is_admin_or_above_inner(api_key.group_id, current_user.id) and api_key.user_id != current_user.id:
            return jsonify({'detail': 'You do not have access to this API key'}), 403
        return jsonify(api_key.to_dict_with_group())

    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404

    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

    if not _is_admin_or_above_inner(api_key.group_id, current_user.id) and api_key.user_id != current_user.id:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

    return jsonify(api_key.to_dict_with_group())


@apikeys_bp.route('/apikeys/', methods=['POST'])
@token_required
async def create_api_key(current_user):
    """Create a new API key. Members can only create if member.apikey.create is enabled."""
    data = await request.get_json()
    
    # Check if the group exists and user is a member
    group = get_group_by_id(data.get('group_id'))
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    # Permission: non-root users need apikey.create permission
    group_id = group.id
    user_role = _get_role(group_id, current_user.id)
    if user_role != 'root' and not check_permission(user_role, 'apikey.create'):
        return jsonify({'detail': 'Creating API keys is disabled for your role'}), 403
    
    # Convert empty string to None for expires_at (empty string is not valid for timestamp)
    expires_at = data.get('expires_at')
    if expires_at == '':
        expires_at = None
    
    api_key = ApiKey(
        key=generate_api_key(),
        name=data.get('name'),
        description=data.get('description'),
        group_id=data.get('group_id'),
        user_id=current_user.id,
        expires_at=expires_at,
        allowed_models=data.get('allowed_models') or None,
        tags=data.get('tags') or None,
        workspace_id=group.workspace_id,
        unlimited_budget=False,
        budget=100.0,
    )
    db.session.add(api_key)
    db.session.flush()

    # Create default budget record
    budget_entry = ApiKeyBudget(
        api_key_id=api_key.id,
        amount=100.0,
        remaining=100.0,
    )
    db.session.add(budget_entry)
    db.session.commit()
    db.session.refresh(api_key)
    
    return jsonify(api_key.to_dict()), 201


@apikeys_bp.route('/apikeys/<int:api_key_id>', methods=['PUT'])
@token_required
async def update_api_key(current_user, api_key_id):
    """Update an API key. Invalidates cache after update.
    Members can only edit their own keys if member.apikey.edit_own is enabled.
    Admins/root can edit any key in the group."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    # Permission: root can do anything; admin/member need apikey.manage for others, apikey.edit_own for own
    group_id = api_key.group_id
    user_role = _get_role(group_id, current_user.id)
    is_owner = api_key.user_id == current_user.id
    if user_role != 'root':
        if not is_owner and not check_permission(user_role, 'apikey.manage'):
            return jsonify({'detail': 'You do not have permission to manage other users\' API keys'}), 403
        if is_owner and not check_permission(user_role, 'apikey.edit_own'):
            return jsonify({'detail': 'Editing own API keys is disabled for your role'}), 403
    
    data = await request.get_json()

    # Check field-specific permissions for budget operations
    if user_role != 'root':
        if 'unlimited_budget' in data and not check_permission(user_role, 'apikey.unlimited_budget'):
            return jsonify({'detail': 'You do not have permission to toggle unlimited budget'}), 403
        if 'budget' in data and not check_permission(user_role, 'apikey.add_budget'):
            return jsonify({'detail': 'You do not have permission to add budget'}), 403

    if 'name' in data:
        api_key.name = data['name']
    if 'description' in data:
        api_key.description = data['description'] if data['description'] else None
    if 'is_active' in data:
        api_key.is_active = data['is_active']
    if 'allowed_models' in data:
        val = data['allowed_models']
        api_key.allowed_models = val if val else None
    if 'expires_at' in data:
        # Convert empty string to None for expires_at (empty string is not valid for timestamp)
        expires_at = data['expires_at']
        api_key.expires_at = None if expires_at == '' else expires_at
    if 'tags' in data:
        api_key.tags = data['tags'] if data['tags'] else None
    if 'unlimited_budget' in data:
        api_key.unlimited_budget = bool(data['unlimited_budget'])
    if 'budget' in data:
        val = data['budget']
        if val is not None and val != '':
            add_amount = float(val)
            # Budget is additive: append to current remaining budget
            current_budget = api_key.budget or 0.0
            api_key.budget = current_budget + add_amount
        # If val is None or '', don't change the budget (use unlimited_budget flag instead)
    
    db.session.commit()
    db.session.refresh(api_key)
    
    # Update cache with new values so budget/unlimited checks see them immediately
    try:
        from app.cache import get_cache
        cache = get_cache()
        cached_info = cache.get_api_key_info(api_key.key)
        if cached_info is not None:
            cached_info['budget'] = api_key.budget
            cached_info['unlimited_budget'] = api_key.unlimited_budget
            cached_info['is_active'] = api_key.is_active
            cached_info['allowed_models'] = api_key.allowed_models or []
            cache.set_api_key_info(api_key.key, cached_info)
        else:
            cache.invalidate_api_key_by_id(api_key_id)
        # Update the dedicated budget remaining key so gateway budget checks
        # see the new value immediately.
        from app.budget_manager import get_budget_manager
        bm = get_budget_manager()
        if not api_key.unlimited_budget and api_key.budget is not None:
            bm.set_remaining(api_key.key, float(api_key.budget))
        elif api_key.unlimited_budget:
            # Unlimited budget — remove the dedicated remaining key
            bm.invalidate(api_key.key)
    except Exception:
        pass
    
    return jsonify(api_key.to_dict())


@apikeys_bp.route('/apikeys/<int:api_key_id>/models', methods=['GET'])
@token_required
async def get_api_key_models(current_user, api_key_id):
    """Get the list of models available to this API key, with per-model usage stats."""
    from app.models import UsageRecord, get_group_models_with_shares
    import hashlib

    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404

    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

    # Get all active models in the group (including shared models)
    pairs = get_group_models_with_shares(api_key.group_id)
    all_models = [m for m, _ in pairs]

    allowed = api_key.allowed_models or []
    # Filter by allowed_models if set
    if allowed:
        models = [m for m in all_models if m.name in allowed or (m.alias and m.alias in allowed)]
    else:
        models = all_models

    # Collect unique model names
    model_names = list(set(m.name for m in models))

    # Get per-model usage stats for this API key
    key_hash = hashlib.sha256(api_key.key.encode()).hexdigest()
    usage_rows = (
        db.session.query(
            UsageRecord.model_name,
            db.func.count(UsageRecord.id).label('requests'),
            db.func.coalesce(db.func.sum(UsageRecord.input_tokens), 0).label('input_tokens'),
            db.func.coalesce(db.func.sum(UsageRecord.output_tokens), 0).label('output_tokens'),
            db.func.coalesce(db.func.sum(UsageRecord.reasoning_tokens), 0).label('reasoning_tokens'),
        )
        .filter(UsageRecord.api_key_hash == key_hash)
        .group_by(UsageRecord.model_name)
        .all()
    )
    usage_map = {r.model_name: {
        'requests': r.requests,
        'input_tokens': int(r.input_tokens),
        'output_tokens': int(r.output_tokens),
        'reasoning_tokens': int(r.reasoning_tokens),
    } for r in usage_rows}

    result = []
    seen_names = set()
    for m in models:
        if m.name in seen_names:
            continue
        seen_names.add(m.name)
        usage = usage_map.get(m.name, {'requests': 0, 'input_tokens': 0, 'output_tokens': 0, 'reasoning_tokens': 0})
        result.append({
            'name': m.name,
            'alias': m.alias,
            'provider_name': m.provider.name if m.provider else None,
            **usage,
        })

    return jsonify({
        'allowed_models': allowed,
        'models': result,
    })


@apikeys_bp.route('/apikeys/<int:api_key_id>/detail', methods=['GET'])
@token_required
async def get_api_key_detail(current_user, api_key_id):
    """
    Get comprehensive detail for a single API key:
    - Basic info + budget (separated from usage stats)
    - Usage stats from cache (real-time) with DB fallback
    - Available models (with rpm/tpm)
    - By-model breakdown (from DB)
    """
    from app.models import UsageRecord, get_group_models_with_shares
    from app.cache import get_cache
    import hashlib

    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404

    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

    if not _is_admin_or_above_inner(api_key.group_id, current_user.id) and api_key.user_id != current_user.id:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

    key_hash = hashlib.sha256(api_key.key.encode()).hexdigest()
    cache = get_cache()

    # ── Try reading usage stats from cache first ─────────────────────────
    cached_info = cache.get_api_key_info(api_key.key)
    if cached_info is not None:
        # Use cached usage stats (updated in real-time by each request)
        usage_totals = {
            'requests': int(cached_info.get('request_count', 0) or 0),
            'input_tokens': int(cached_info.get('total_input_tokens', 0) or 0),
            'output_tokens': int(cached_info.get('total_output_tokens', 0) or 0),
            'reasoning_tokens': int(cached_info.get('total_reasoning_tokens', 0) or 0),
            'estimated_cost': round(float(cached_info.get('total_cost_usd', 0) or 0), 6),
            'total_image_count': int(cached_info.get('total_image_count', 0) or 0),
            'total_video_count': int(cached_info.get('total_video_count', 0) or 0),
            'total_audio_seconds': round(float(cached_info.get('total_audio_seconds', 0) or 0), 4),
        }
    else:
        # Cache miss — fall back to DB aggregation and populate cache
        _cost_expr = (
            UsageRecord.input_tokens * UsageRecord.input_price_unit / 1000000.0
            + UsageRecord.output_tokens * UsageRecord.output_price_unit / 1000000.0
            + UsageRecord.cache_creation_tokens * UsageRecord.cache_creation_price_unit / 1000000.0
            + UsageRecord.cache_tokens * UsageRecord.cache_token_price_unit / 1000000.0
            + UsageRecord.output_image_number * UsageRecord.output_image_price_unit
            + UsageRecord.output_video_number * UsageRecord.output_video_price_unit
            + UsageRecord.output_audio_seconds * UsageRecord.output_audio_price_unit
            + UsageRecord.web_search_requests * UsageRecord.web_search_price_unit
        )

        totals_row = (
            db.session.query(
                db.func.count(UsageRecord.id).label('requests'),
                db.func.coalesce(db.func.sum(UsageRecord.input_tokens), 0).label('input_tokens'),
                db.func.coalesce(db.func.sum(UsageRecord.output_tokens), 0).label('output_tokens'),
                db.func.coalesce(db.func.sum(UsageRecord.reasoning_tokens), 0).label('reasoning_tokens'),
                db.func.coalesce(db.func.sum(UsageRecord.actual_amount_usd), 0).label('total_cost_usd'),
                db.func.coalesce(db.func.sum(UsageRecord.output_image_number), 0).label('total_image_count'),
                db.func.coalesce(db.func.sum(UsageRecord.output_video_number), 0).label('total_video_count'),
                db.func.coalesce(db.func.sum(UsageRecord.output_audio_seconds), 0).label('total_audio_seconds'),
            )
            .filter(UsageRecord.api_key_hash == key_hash)
            .one()
        )

        usage_totals = {
            'requests': totals_row.requests or 0,
            'input_tokens': int(totals_row.input_tokens or 0),
            'output_tokens': int(totals_row.output_tokens or 0),
            'reasoning_tokens': int(totals_row.reasoning_tokens or 0),
            'estimated_cost': round(float(totals_row.total_cost_usd or 0), 6),
            'total_image_count': int(totals_row.total_image_count or 0),
            'total_video_count': int(totals_row.total_video_count or 0),
            'total_audio_seconds': round(float(totals_row.total_audio_seconds or 0), 4),
        }

        # Populate cache with DB data for future reads
        cache_info = cache.build_api_key_cache_info(api_key, budget_used=usage_totals['estimated_cost'])
        cache_info['total_input_tokens'] = usage_totals['input_tokens']
        cache_info['total_output_tokens'] = usage_totals['output_tokens']
        cache_info['total_reasoning_tokens'] = usage_totals['reasoning_tokens']
        cache_info['total_cost_usd'] = usage_totals['estimated_cost']
        cache_info['total_image_count'] = usage_totals['total_image_count']
        cache_info['total_video_count'] = usage_totals['total_video_count']
        cache_info['total_audio_seconds'] = usage_totals['total_audio_seconds']
        cache.set_api_key_info(api_key.key, cache_info)

    # ── By model usage (always from DB for accuracy) ──────────────────────
    _cost_expr_model = (
        UsageRecord.input_tokens * UsageRecord.input_price_unit / 1000000.0
        + UsageRecord.output_tokens * UsageRecord.output_price_unit / 1000000.0
        + UsageRecord.cache_creation_tokens * UsageRecord.cache_creation_price_unit / 1000000.0
        + UsageRecord.cache_tokens * UsageRecord.cache_token_price_unit / 1000000.0
        + UsageRecord.output_image_number * UsageRecord.output_image_price_unit
        + UsageRecord.output_video_number * UsageRecord.output_video_price_unit
        + UsageRecord.output_audio_seconds * UsageRecord.output_audio_price_unit
        + UsageRecord.web_search_requests * UsageRecord.web_search_price_unit
    )

    by_model_rows = (
        db.session.query(
            UsageRecord.model_name,
            db.func.count(UsageRecord.id).label('requests'),
            db.func.coalesce(db.func.sum(UsageRecord.input_tokens), 0).label('input_tokens'),
            db.func.coalesce(db.func.sum(UsageRecord.output_tokens), 0).label('output_tokens'),
            db.func.coalesce(db.func.sum(UsageRecord.reasoning_tokens), 0).label('reasoning_tokens'),
            db.func.coalesce(db.func.sum(_cost_expr_model), 0).label('estimated_cost'),
        )
        .filter(UsageRecord.api_key_hash == key_hash)
        .group_by(UsageRecord.model_name)
        .order_by(db.func.coalesce(db.func.sum(_cost_expr_model), 0).desc())
        .limit(50)
        .all()
    )

    by_model = [
        {
            'model_name': r.model_name,
            'requests': r.requests,
            'input_tokens': int(r.input_tokens),
            'output_tokens': int(r.output_tokens),
            'reasoning_tokens': int(r.reasoning_tokens),
            'estimated_cost': round(float(r.estimated_cost or 0), 6),
        }
        for r in by_model_rows
    ]

    # ── Available models with rpm/tpm ─────────────────────────────────────
    pairs = get_group_models_with_shares(api_key.group_id)
    all_models = [m for m, _ in pairs]

    allowed = api_key.allowed_models or []
    if allowed:
        models = [m for m in all_models if m.name in allowed or (m.alias and m.alias in allowed)]
    else:
        models = all_models

    seen_names = set()
    available_models = []
    for m in models:
        if m.name in seen_names:
            continue
        seen_names.add(m.name)
        available_models.append({
            'name': m.name,
            'alias': m.alias,
            'provider_name': m.provider.name if m.provider else None,
            'rpm': m.rpm,
            'tpm': m.tpm,
            'input_price': m.input_price,
            'output_price': m.output_price,
            'currency': m.currency or 'USD',
        })

    # ── Budget info (separate from usage stats) ───────────────────────────
    # budget field is the remaining allowance (additive model).
    # unlimited_budget flag determines whether budget deduction is enforced.
    #
    # Since budget is additive and never decremented in DB, budget = remaining.
    # "used" represents spending from the budget (budget_total - remaining).
    # We track total_budget_allocated separately to compute used correctly.
    is_unlimited = api_key.unlimited_budget
    budget_remaining = api_key.budget  # This IS the remaining amount

    # Compute the total budget ever allocated and the used portion.
    # total_budget_allocated = remaining + cumulative spending against budget.
    # We compute cumulative spending from cache.budget_used, but budget_used
    # tracks ALL historical spending (even before budget was set).
    # To get only the spending AGAINST budget, we compare with what was seeded:
    #   When cache is populated, budget_used = SUM(actual_amount_usd) at that moment.
    #   After that, each request increments budget_used by actual_usd.
    #   So budget_consumed_since_cache = current_budget_used - initial_budget_used.
    # But we don't track initial_budget_used separately.
    #
    # Simpler approach: budget = remaining, total = remaining (they're the same
    # since budget is never decremented). Show used = 0 for display.
    # The real budget enforcement happens in the gateway via cache.
    #
    # For a correct display, we show:
    #   budget (total) = remaining (same value, since DB never decrements)
    #   used = 0 (no deduction tracked in DB)
    #   remaining = budget
    # This makes the bucket always show 100% when budget > 0, which correctly
    # reflects "you have $X remaining" without misleading "used" data.

    # ── Budget records from ml_api_key_budgets ────────────────────────────
    budget_records = (
        db.session.query(ApiKeyBudget)
        .filter(ApiKeyBudget.api_key_id == api_key_id)
        .order_by(ApiKeyBudget.created_at.asc())
        .all()
    )
    budgets_list = [b.to_dict() for b in budget_records]
    # Total remaining across all budget records
    total_remaining = float(sum(float(b.remaining or 0) for b in budget_records if b.remaining and b.remaining > 0))

    result = api_key.to_dict_with_group()
    result['api_key_hash'] = key_hash
    result['usage'] = usage_totals
    result['by_model'] = by_model
    result['available_models'] = available_models
    result['budget_info'] = {
        'unlimited_budget': is_unlimited,
        'budget': round(budget_remaining, 6) if budget_remaining is not None else None,
        'used': round(usage_totals['estimated_cost'], 6),
        'remaining': round(budget_remaining, 6) if budget_remaining is not None else None,
    }
    result['budgets'] = budgets_list
    result['total_budget_remaining'] = round(total_remaining, 6)

    return jsonify(result)


@apikeys_bp.route('/apikeys/<int:api_key_id>', methods=['DELETE'])
@token_required
async def delete_api_key(current_user, api_key_id):
    """Delete an API key. Invalidates cache.
    Members can only delete their own keys if member.apikey.edit_own is enabled.
    Admins/root can delete any key in the group."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    # Permission: root can do anything; admin/member need apikey.manage for others, apikey.edit_own for own
    group_id = api_key.group_id
    user_role = _get_role(group_id, current_user.id)
    is_owner = api_key.user_id == current_user.id
    if user_role != 'root':
        if not is_owner and not check_permission(user_role, 'apikey.manage'):
            return jsonify({'detail': 'You do not have permission to manage other users\' API keys'}), 403
        if is_owner and not check_permission(user_role, 'apikey.edit_own'):
            return jsonify({'detail': 'Deleting own API keys is disabled for your role'}), 403
    
    # Invalidate cache before deleting (need the raw key for cache lookup)
    try:
        from app.cache import get_cache
        from app.budget_manager import get_budget_manager
        get_cache().invalidate_api_key(api_key.key)
        get_budget_manager().invalidate(api_key.key)
    except Exception:
        pass
    
    db.session.delete(api_key)
    db.session.commit()
    
    return '', 204


@apikeys_bp.route('/apikeys/<int:api_key_id>/regenerate', methods=['POST'])
@token_required
async def regenerate_api_key(current_user, api_key_id):
    """Regenerate an API key (revokes the old one). Invalidates cache for old key.
    Members can only regenerate their own keys if member.apikey.edit_own is enabled.
    Admins/root can regenerate any key in the group."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    # Permission: root can do anything; admin/member need apikey.manage for others, apikey.edit_own for own
    group_id = api_key.group_id
    user_role = _get_role(group_id, current_user.id)
    is_owner = api_key.user_id == current_user.id
    if user_role != 'root':
        if not is_owner and not check_permission(user_role, 'apikey.manage'):
            return jsonify({'detail': 'You do not have permission to manage other users\' API keys'}), 403
        if is_owner and not check_permission(user_role, 'apikey.edit_own'):
            return jsonify({'detail': 'Regenerating own API keys is disabled for your role'}), 403
    
    # Invalidate cache for the old key before regenerating
    old_key = api_key.key
    try:
        from app.cache import get_cache
        from app.budget_manager import get_budget_manager
        get_cache().invalidate_api_key(old_key)
        get_budget_manager().invalidate(old_key)
    except Exception:
        pass
    
    api_key.key = generate_api_key()
    api_key.request_count = 0
    api_key.token_count = 0
    db.session.commit()
    db.session.refresh(api_key)
    
    return jsonify(api_key.to_dict())


# ============== Budget Management ==============

@apikeys_bp.route('/apikeys/<int:api_key_id>/budgets', methods=['GET'])
@token_required
async def list_budgets(current_user, api_key_id):
    """List all budget records for an API key."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

    budgets = (
        db.session.query(ApiKeyBudget)
        .filter(ApiKeyBudget.api_key_id == api_key_id)
        .order_by(ApiKeyBudget.created_at.asc())
        .all()
    )
    return jsonify([b.to_dict() for b in budgets])


@apikeys_bp.route('/apikeys/<int:api_key_id>/budgets', methods=['POST'])
@token_required
@require_apikey_permission('apikey.add_budget')
async def add_budget(current_user, api_key_id):
    """
    Add a new budget entry to an API key. Root only.

    Request body: { "amount": 100.0 }

    Creates a new budget record and also updates the ApiKey.budget field
    (total remaining) for backward compatibility.
    """
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    data = await request.get_json()
    amount = data.get('amount')
    if amount is None or amount == '':
        return jsonify({'detail': 'amount is required'}), 400
    amount = float(amount)
    if amount <= 0:
        return jsonify({'detail': 'amount must be positive'}), 400

    budget_entry = ApiKeyBudget(
        api_key_id=api_key_id,
        amount=amount,
        remaining=amount,
    )
    db.session.add(budget_entry)

    # Also update ApiKey.budget for backward compatibility
    current_budget = api_key.budget or 0.0
    api_key.budget = current_budget + amount

    db.session.commit()
    db.session.refresh(budget_entry)
    db.session.refresh(api_key)

    # Update cache with new budget value so budget checks see it immediately
    try:
        from app.cache import get_cache
        cache = get_cache()
        cached_info = cache.get_api_key_info(api_key.key)
        if cached_info is not None:
            cached_info['budget'] = api_key.budget
            cache.set_api_key_info(api_key.key, cached_info)
        else:
            # Cache miss — populate from scratch
            cache.invalidate_api_key_by_id(api_key_id)
        # Update the dedicated budget remaining key so gateway budget checks
        # see the new value immediately.
        if not api_key.unlimited_budget and api_key.budget is not None:
            from app.budget_manager import get_budget_manager
            get_budget_manager().set_remaining(api_key.key, float(api_key.budget))
    except Exception:
        pass

    return jsonify(budget_entry.to_dict()), 201


@apikeys_bp.route('/apikeys/<int:api_key_id>/budgets/<int:budget_id>', methods=['DELETE'])
@token_required
@require_apikey_permission('apikey.add_budget')
async def delete_budget(current_user, api_key_id, budget_id):
    """Delete a budget entry. Requires apikey.add_budget permission."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    budget_entry = db.session.query(ApiKeyBudget).filter(
        ApiKeyBudget.id == budget_id,
        ApiKeyBudget.api_key_id == api_key_id,
    ).first()
    if not budget_entry:
        return jsonify({'detail': 'Budget entry not found'}), 404

    # Subtract the remaining amount from ApiKey.budget for backward compat
    if api_key.budget is not None:
        api_key.budget = max((api_key.budget or 0.0) - float(budget_entry.remaining or 0), 0.0)

    db.session.delete(budget_entry)
    db.session.commit()
    db.session.refresh(api_key)

    # Update cache with new budget value so budget checks see it immediately
    try:
        from app.cache import get_cache
        cache = get_cache()
        cached_info = cache.get_api_key_info(api_key.key)
        if cached_info is not None:
            cached_info['budget'] = api_key.budget
            cache.set_api_key_info(api_key.key, cached_info)
        else:
            cache.invalidate_api_key_by_id(api_key_id)
        # Update the dedicated budget remaining key so gateway budget checks
        # see the new value immediately.
        if not api_key.unlimited_budget and api_key.budget is not None:
            from app.budget_manager import get_budget_manager
            get_budget_manager().set_remaining(api_key.key, float(api_key.budget))
    except Exception:
        pass

    return '', 204
