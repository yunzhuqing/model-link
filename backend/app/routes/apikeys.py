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
from app.models import Group, ApiKey, ApiKeyBudget
from app.routes.users import token_required

apikeys_bp = Blueprint('apikeys', __name__)


def generate_api_key():
    """Generate a secure random API key with sk- prefix (OpenAI compatible)."""
    return f"sk-{secrets.token_hex(24)}"


# ============== Group Management ==============

@apikeys_bp.route('/groups/', methods=['GET'])
@token_required
async def list_groups(current_user):
    """List all groups the current user belongs to."""
    return jsonify([g.to_dict() for g in current_user.groups])


@apikeys_bp.route('/groups/', methods=['POST'])
@token_required
async def create_group(current_user):
    """Create a new group."""
    from app.models import UserGroup
    
    data = await request.get_json()
    
    # Check if group name already exists
    existing = db.session.query(Group).filter(Group.name == data.get('name')).first()
    if existing:
        return jsonify({'detail': 'Group with this name already exists'}), 400
    
    group = Group(
        name=data.get('name'),
        description=data.get('description')
    )
    db.session.add(group)
    db.session.flush()  # Get the group ID
    
    # Creator is automatically a root member
    user_group = UserGroup(
        user_id=current_user.id,
        group_id=group.id,
        role='root'
    )
    db.session.add(user_group)
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict()), 201


@apikeys_bp.route('/groups/<int:group_id>', methods=['GET'])
@token_required
async def get_group(current_user, group_id):
    """Get a specific group."""
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>', methods=['PUT'])
@token_required
async def update_group(current_user, group_id):
    """Update a group."""
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    data = await request.get_json()
    if 'name' in data:
        # Check if new name already exists
        existing = db.session.query(Group).filter(
            Group.name == data['name'],
            Group.id != group_id
        ).first()
        if existing:
            return jsonify({'detail': 'Group with this name already exists'}), 400
        group.name = data['name']
    
    if 'description' in data:
        group.description = data['description']
    
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@token_required
async def delete_group(current_user, group_id):
    """Delete a group."""
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    db.session.delete(group)
    db.session.commit()
    
    return '', 204


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>', methods=['POST'])
@token_required
async def add_user_to_group(current_user, group_id, user_id):
    """Add a user to a group."""
    from app.models import User
    
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
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
async def remove_user_from_group(current_user, group_id, user_id):
    """Remove a user from a group."""
    from app.models import User
    
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
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
async def invite_member(current_user, group_id):
    """Invite a member to a group by email."""
    from app.models import User, UserGroup
    
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
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
async def update_member_role(current_user, group_id, user_id):
    """Update a member's role in a group."""
    from app.models import User, UserGroup
    
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    # Check if current user is in group
    current_user_group = db.session.query(UserGroup).filter(
        UserGroup.group_id == group_id,
        UserGroup.user_id == current_user.id
    ).first()
    
    if not current_user_group:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    # Only root or admin can change roles
    if current_user_group.role not in ['root', 'admin']:
        return jsonify({'detail': 'Only root or admin can change member roles'}), 403
    
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
    
    # Only root can change another root's role
    if user_group.role == 'root' and current_user_group.role != 'root':
        return jsonify({'detail': 'Only root can change another root\'s role'}), 403
    
    user_group.role = new_role
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


# ============== API Key Management ==============

@apikeys_bp.route('/apikeys/', methods=['GET'])
@token_required
async def list_api_keys(current_user):
    """List all API keys for groups the user belongs to."""
    api_keys = []
    for group in current_user.groups:
        api_keys.extend([k.to_dict_with_group() for k in group.api_keys])
    return jsonify(api_keys)


@apikeys_bp.route('/apikeys/group/<int:group_id>', methods=['GET'])
@token_required
async def list_api_keys_by_group(current_user, group_id):
    """List all API keys for a specific group."""
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    return jsonify([k.to_dict() for k in group.api_keys])


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
        return jsonify(api_key.to_dict_with_group())

    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    return jsonify(api_key.to_dict_with_group())


@apikeys_bp.route('/apikeys/', methods=['POST'])
@token_required
async def create_api_key(current_user):
    """Create a new API key."""
    data = await request.get_json()
    
    # Check if the group exists and user is a member
    group = db.session.query(Group).filter(Group.id == data.get('group_id')).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    # Convert empty string to None for expires_at (empty string is not valid for timestamp)
    expires_at = data.get('expires_at')
    if expires_at == '':
        expires_at = None
    
    api_key = ApiKey(
        key=generate_api_key(),
        name=data.get('name'),
        group_id=data.get('group_id'),
        user_id=current_user.id,
        expires_at=expires_at,
        allowed_models=data.get('allowed_models') or None
    )
    db.session.add(api_key)
    db.session.commit()
    db.session.refresh(api_key)
    
    return jsonify(api_key.to_dict()), 201


@apikeys_bp.route('/apikeys/<int:api_key_id>', methods=['PUT'])
@token_required
async def update_api_key(current_user, api_key_id):
    """Update an API key. Invalidates cache after update."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    data = await request.get_json()
    if 'name' in data:
        api_key.name = data['name']
    if 'is_active' in data:
        api_key.is_active = data['is_active']
    if 'allowed_models' in data:
        val = data['allowed_models']
        api_key.allowed_models = val if val else None
    if 'expires_at' in data:
        # Convert empty string to None for expires_at (empty string is not valid for timestamp)
        expires_at = data['expires_at']
        api_key.expires_at = None if expires_at == '' else expires_at
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
    except Exception:
        pass
    
    return jsonify(api_key.to_dict())


@apikeys_bp.route('/apikeys/<int:api_key_id>/models', methods=['GET'])
@token_required
async def get_api_key_models(current_user, api_key_id):
    """Get the list of models available to this API key, with per-model usage stats."""
    from app.models import UsageRecord, Provider, Model as MLModel
    import hashlib

    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404

    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

    # Get all active models in the same group
    all_models = (
        db.session.query(MLModel)
        .join(Provider, MLModel.provider_id == Provider.id)
        .filter(Provider.group_id == api_key.group_id)
        .filter(Provider.is_active == True)
        .filter(MLModel.is_active == True)
        .all()
    )

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
    from app.models import UsageRecord, Provider, Model as MLModel
    from app.cache import get_cache
    import hashlib

    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404

    if current_user not in api_key.group.users:
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
    all_models = (
        db.session.query(MLModel)
        .join(Provider, MLModel.provider_id == Provider.id)
        .filter(Provider.group_id == api_key.group_id)
        .filter(Provider.is_active == True)
        .filter(MLModel.is_active == True)
        .all()
    )

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
    total_remaining = sum(b.remaining for b in budget_records if b.remaining > 0)

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
    """Delete an API key. Invalidates cache."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    # Invalidate cache before deleting (need the raw key for cache lookup)
    try:
        from app.cache import get_cache
        get_cache().invalidate_api_key(api_key.key)
    except Exception:
        pass
    
    db.session.delete(api_key)
    db.session.commit()
    
    return '', 204


@apikeys_bp.route('/apikeys/<int:api_key_id>/regenerate', methods=['POST'])
@token_required
async def regenerate_api_key(current_user, api_key_id):
    """Regenerate an API key (revokes the old one). Invalidates cache for old key."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    # Invalidate cache for the old key before regenerating
    old_key = api_key.key
    try:
        from app.cache import get_cache
        get_cache().invalidate_api_key(old_key)
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
async def add_budget(current_user, api_key_id):
    """
    Add a new budget entry to an API key.

    Request body: { "amount": 100.0 }

    Creates a new budget record and also updates the ApiKey.budget field
    (total remaining) for backward compatibility.
    """
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

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
    except Exception:
        pass

    return jsonify(budget_entry.to_dict()), 201


@apikeys_bp.route('/apikeys/<int:api_key_id>/budgets/<int:budget_id>', methods=['DELETE'])
@token_required
async def delete_budget(current_user, api_key_id, budget_id):
    """Delete a budget entry. Only allowed if budget has remaining > 0 (refund scenario)."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403

    budget_entry = db.session.query(ApiKeyBudget).filter(
        ApiKeyBudget.id == budget_id,
        ApiKeyBudget.api_key_id == api_key_id,
    ).first()
    if not budget_entry:
        return jsonify({'detail': 'Budget entry not found'}), 404

    # Subtract the remaining amount from ApiKey.budget for backward compat
    if api_key.budget is not None:
        api_key.budget = max((api_key.budget or 0.0) - budget_entry.remaining, 0.0)

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
    except Exception:
        pass

    return '', 204
