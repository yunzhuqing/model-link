"""
API Key and Group management routes.

Cache integration:
  - API key detail/info endpoints read from cache first (cache.get_api_key_info_by_id).
  - Create / update / delete / regenerate operations invalidate the cache
    (cache.invalidate_api_key_by_id) so stale data is never served.
"""
from quart import Blueprint, request, jsonify, current_app
from datetime import datetime, timezone, timedelta
import logging
import secrets

from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from app import get_db_session
from app.models import ApiKey, ApiKeyBudget, ApiKeyPolicy, Group
from app.auth import token_required
from app.models import check_permission
from app.stats import metabase_client
from app.routes.permissions import (
    _get_role,
    _is_admin_or_above_inner,
    check_group_permission,
    require_permission,
    require_apikey_permission,
    require_global_permission,
    require_api_key_access,
)
from app.group_service import (
    get_group_by_id,
    create_group as _svc_create_group,
    update_group as _svc_update_group,
    delete_group as _svc_delete_group,
)

apikeys_bp = Blueprint('apikeys', __name__)

logger = logging.getLogger("apikeys")

ROLE_RANK = {'root': 3, 'admin': 2, 'member': 1}


def _role_rank(role: str) -> int:
    """Return numeric rank for role comparison. Higher = more privileged."""
    return ROLE_RANK.get(role, 0)


def generate_api_key():
    """Generate a secure random API key with sk- prefix (OpenAI compatible)."""
    return f"sk-{secrets.token_hex(24)}"



def _parse_expires_at(value):
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


# ============== Group Management ==============

@apikeys_bp.route('/groups/', methods=['GET'])
@token_required
async def list_groups(current_user):
    """List all groups the current user belongs to, including the user's role.

    Query params:
        search: Filter groups by name (case-insensitive partial match).
    """
    from app.models import UserGroup

    search = request.args.get('search', '').strip().lower()

    async with get_db_session() as session:
        result = []
        for grp in current_user.groups:
            if search and search not in grp.name.lower():
                continue
            group_dict = await grp.to_dict(session=session)
            # Include the current user's role in this group
            ug = (await session.execute(
                select(UserGroup).where(
                    UserGroup.group_id == grp.id,
                    UserGroup.user_id == current_user.id,
                )
            )).scalars().first()
            group_dict['my_role'] = ug.role if ug else None
            result.append(group_dict)

        return jsonify(result)


@apikeys_bp.route('/groups/', methods=['POST'])
@token_required
@require_global_permission('group.manage')
async def create_group(current_user):
    """Create a new group."""
    from app.models import UserGroup

    data = await request.get_json()

    if not data.get('name'):
        return jsonify({'detail': 'Group name is required'}), 400

    async with get_db_session() as session:
        group, err = await _svc_create_group(
            name=data.get('name'),
            description=data.get('description'),
            workspace_id=data.get('workspace_id'),
            session=session,
        )
        if err:
            return jsonify({'detail': err}), 400

        # Creator is automatically a root member
        user_group = UserGroup(
            user_id=current_user.id,
            group_id=group.id,
            role='root',
        )
        session.add(user_group)
        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            return jsonify({'detail': str(e)}), 400

        from app.user_service import invalidate_user_cache
        await invalidate_user_cache(current_user.id)

        # Re-fetch with eager-loaded relationships so to_dict()
        # won't trigger async-incompatible lazy loads.
        group = await get_group_by_id(group.id, session=session)

        return jsonify(group.to_dict()), 201


@apikeys_bp.route('/groups/<int:group_id>', methods=['GET'])
@token_required
async def get_group(current_user, group_id):
    """Get a specific group."""
    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
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

    from app.models import UserGroup
    async with get_db_session() as session:
        # Get all users in the group to invalidate their caches
        user_ids_result = await session.execute(
            select(UserGroup.user_id).where(UserGroup.group_id == group_id)
        )
        user_ids = [r[0] for r in user_ids_result.all()]

        group, err = await _svc_update_group(group_id, session=session, **kwargs)
        if err:
            return jsonify({'detail': err}), 404 if err == 'Group not found' else 400

        await session.commit()
        await session.refresh(group)

        from app.user_service import invalidate_user_cache
        for uid in user_ids:
            await invalidate_user_cache(uid)

        return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@token_required
@require_permission('group.manage')
async def delete_group(current_user, group_id):
    """Delete a group. Root only (controlled by group.manage permission)."""
    from app.models import UserGroup
    async with get_db_session() as session:
        # Get users before deleting the group
        user_ids_result = await session.execute(
            select(UserGroup.user_id).where(UserGroup.group_id == group_id)
        )
        user_ids = [r[0] for r in user_ids_result.all()]

        ok, err = await _svc_delete_group(group_id, session=session)
        if err:
            return jsonify({'detail': err}), 404

        await session.commit()

        from app.user_service import invalidate_user_cache
        for uid in user_ids:
            await invalidate_user_cache(uid)

        return '', 204


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>', methods=['POST'])
@token_required
@require_permission('member.manage')
async def add_user_to_group(current_user, group_id, user_id):
    """Add a user to a group. Admin or above only (controlled by member.manage permission)."""
    from app.models import User

    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        user = await session.get(User, user_id)
        if not user:
            return jsonify({'detail': 'User not found'}), 404

        if user in group.users:
            return jsonify({'detail': 'User is already a member of this group'}), 400

        group.users.append(user)
        await session.commit()
        await session.refresh(group)

        from app.user_service import invalidate_user_cache
        await invalidate_user_cache(user_id)

        return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>', methods=['DELETE'])
@token_required
@require_permission('member.manage')
async def remove_user_from_group(current_user, group_id, user_id):
    """Remove a user from a group. Admin or above only (controlled by member.manage permission)."""
    from app.models import User, UserGroup

    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        user = await session.get(User, user_id)
        if not user:
            return jsonify({'detail': 'User not found'}), 404

        if user not in group.users:
            return jsonify({'detail': 'User is not a member of this group'}), 400

        target_membership = (await session.execute(
            select(UserGroup).where(
                UserGroup.group_id == group_id,
                UserGroup.user_id == user_id
            )
        )).scalars().first()
        current_role = await _get_role(group_id, current_user.id, session=session)
        if _role_rank(target_membership.role) > _role_rank(current_role):
            return jsonify({'detail': 'Cannot remove a member with a higher role than your own'}), 403

        group.users.remove(user)
        await session.commit()
        await session.refresh(group)

        from app.user_service import invalidate_user_cache
        await invalidate_user_cache(user_id)

        return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/invite', methods=['POST'])
@token_required
@require_permission('member.invite')
async def invite_member(current_user, group_id):
    """Invite a member to a group by email. Admin or above only (controlled by member.invite permission)."""
    from app.models import User, UserGroup

    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        data = await request.get_json()
        email = data.get('email')
        role = data.get('role', 'member')  # Default to member role

        # Validate role
        if role not in ['root', 'admin', 'member']:
            return jsonify({'detail': 'Invalid role. Must be root, admin, or member'}), 400

        current_role = await _get_role(group_id, current_user.id, session=session)
        if _role_rank(role) > _role_rank(current_role):
            return jsonify({'detail': 'Cannot assign a role higher than your own'}), 403

        if not email:
            return jsonify({'detail': 'Email is required'}), 400

        # Find user by email
        user = (await session.execute(
            select(User).where(User.email == email)
        )).scalars().first()
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
        session.add(user_group)
        await session.commit()
        await session.refresh(group)

        from app.user_service import invalidate_user_cache
        await invalidate_user_cache(user.id)

        return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>/role', methods=['PUT'])
@token_required
@require_permission('member.manage')
async def update_member_role(current_user, group_id, user_id):
    """Update a member's role in a group. Root and admin (with permission) can change roles."""
    from app.models import User, UserGroup

    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        data = await request.get_json()
        new_role = data.get('role')

        # Validate role
        if new_role not in ['root', 'admin', 'member']:
            return jsonify({'detail': 'Invalid role. Must be root, admin, or member'}), 400

        # Find the user's membership
        user_group = (await session.execute(
            select(UserGroup).where(
                UserGroup.group_id == group_id,
                UserGroup.user_id == user_id
            )
        )).scalars().first()

        if not user_group:
            return jsonify({'detail': 'User is not a member of this group'}), 400

        current_role = await _get_role(group_id, current_user.id, session=session)

        # Cannot modify someone with a higher role
        if _role_rank(user_group.role) > _role_rank(current_role):
            return jsonify({'detail': 'Cannot modify a member with a higher role than your own'}), 403

        # Cannot assign a role higher than your own
        if _role_rank(new_role) > _role_rank(current_role):
            return jsonify({'detail': 'Cannot assign a role higher than your own'}), 403

        user_group.role = new_role
        await session.commit()
        await session.refresh(group)

        from app.user_service import invalidate_user_cache
        await invalidate_user_cache(user_id)

        return jsonify(group.to_dict())


# ============== Model Share Management ==============

@apikeys_bp.route('/groups/<int:group_id>/model-shares', methods=['GET'])
@token_required
async def list_model_shares(current_user, group_id):
    """List models shared to this group from other groups."""
    from app.models import Group, ModelShare, Model as MLModel, Provider

    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        if current_user not in group.users:
            return jsonify({'detail': 'You do not have access to this group'}), 403

        shares = (
            (await session.execute(
                select(ModelShare, MLModel, Provider, Group)
                .join(MLModel, ModelShare.model_id == MLModel.id)
                .join(Provider, MLModel.provider_id == Provider.id)
                .join(Group, ModelShare.source_group_id == Group.id)
                .where(ModelShare.target_group_id == group_id)
            )).all()
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

    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        if current_user not in group.users:
            return jsonify({'detail': 'You do not have access to this group'}), 403

        data = await request.get_json()
        model_id = data.get('model_id')
        if not model_id:
            return jsonify({'detail': 'model_id is required'}), 400

        model = await session.get(MLModel, model_id, options=[selectinload(MLModel.provider)])
        if not model:
            return jsonify({'detail': 'Model not found'}), 404

        # Determine source group from the model's provider
        if not model.provider or not model.provider.group_id:
            return jsonify({'detail': 'Model has no source group'}), 400

        source_group_id = model.provider.group_id
        if source_group_id == group_id:
            return jsonify({'detail': 'Cannot share a model to its own group'}), 400

        # Check if already shared
        existing = (await session.execute(
            select(ModelShare).where(
                ModelShare.model_id == model_id,
                ModelShare.target_group_id == group_id,
            )
        )).scalars().first()
        if existing:
            return jsonify({'detail': 'Model is already shared to this group'}), 409

        share = ModelShare(
            model_id=model_id,
            source_group_id=source_group_id,
            target_group_id=group_id,
            created_by=current_user.id,
        )
        session.add(share)
        await session.commit()

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

    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        if current_user not in group.users:
            return jsonify({'detail': 'You do not have access to this group'}), 403

        share = (await session.execute(
            select(ModelShare).where(
                ModelShare.id == share_id,
                ModelShare.target_group_id == group_id,
            )
        )).scalars().first()
        if not share:
            return jsonify({'detail': 'Model share not found'}), 404

        await session.delete(share)
        await session.commit()

        return jsonify({'detail': 'Model share removed'})


# ============== API Key Management ==============

@apikeys_bp.route('/apikeys/', methods=['GET'])
@token_required
async def list_api_keys(current_user):
    """List the current user's own API keys only."""
    async with get_db_session() as session:
        api_keys = []
        for group in current_user.groups:
            group_keys = await group.get_api_keys(session=session)
            api_keys.extend([k.to_dict_with_group() for k in group_keys if k.user_id == current_user.id])
        return jsonify(api_keys)


@apikeys_bp.route('/apikeys/group/<int:group_id>', methods=['GET'])
@token_required
async def list_api_keys_by_group(current_user, group_id):
    """List all API keys for a specific group."""
    async with get_db_session() as session:
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        if current_user not in group.users:
            return jsonify({'detail': 'You are not a member of this group'}), 403

        # Members can only see their own API keys; admins/root see all
        if await _is_admin_or_above_inner(group_id, current_user.id, session=session):
            return jsonify([k.to_dict() for k in group.api_keys])
        else:
            return jsonify([k.to_dict() for k in group.api_keys if k.user_id == current_user.id])


@apikeys_bp.route('/apikeys/<int:api_key_id>', methods=['GET'])
@token_required
async def get_api_key(current_user, api_key_id):
    """Get a specific API key. Tries cache first for basic info."""
    # Try cache first for a quick response
    from app.cache import get_async_cache
    cache = get_async_cache()
    cached = await cache.get_api_key_info_by_id(api_key_id)
    async with get_db_session() as session:
        if cached is not None:
            # Still need to verify group membership from DB
            api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
            if not api_key:
                await cache.invalidate_api_key_by_id(api_key_id)
                return jsonify({'detail': 'API key not found'}), 404
            if current_user not in api_key.group.users:
                return jsonify({'detail': 'You do not have access to this API key'}), 403
            if not await _is_admin_or_above_inner(api_key.group_id, current_user.id, session=session) and api_key.user_id != current_user.id:
                return jsonify({'detail': 'You do not have access to this API key'}), 403
            return jsonify(api_key.to_dict_with_group())

        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404

        if current_user not in api_key.group.users:
            return jsonify({'detail': 'You do not have access to this API key'}), 403

        if not await _is_admin_or_above_inner(api_key.group_id, current_user.id, session=session) and api_key.user_id != current_user.id:
            return jsonify({'detail': 'You do not have access to this API key'}), 403

        return jsonify(api_key.to_dict_with_group())


@apikeys_bp.route('/groups/<int:group_id>/apikeys', methods=['POST'])
@token_required
@require_permission('apikey.create')
async def create_api_key(current_user, group_id):
    """Create a new API key in the given group. Requires apikey.create permission."""
    data = await request.get_json()

    async with get_db_session() as session:
        # Load group for workspace_id
        group = await get_group_by_id(group_id, session=session)
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        # Resolve role for additional permission checks
        user_role = await _get_role(group_id, current_user.id, session=session)

        # Permission: non-root users need apikey.edit_models to restrict allowed_models
        if data.get('allowed_models') and not await check_permission(user_role, 'apikey.edit_models', session=session):
            return jsonify({'detail': 'You do not have permission to restrict allowed models'}), 403

        # Determine target user_id: admins can create keys for other group members
        target_user_id = current_user.id
        requested_user_id = data.get('user_id')
        if requested_user_id is not None and requested_user_id != current_user.id:
            # Only admin/root can create keys for other users
            if _role_rank(user_role) < _role_rank('admin'):
                return jsonify({'detail': 'Only admins can create API keys for other users'}), 403
            # Verify the target user is a member of the group
            from app.models import UserGroup
            target_ug = (await session.execute(
                select(UserGroup).where(
                    UserGroup.group_id == group_id,
                    UserGroup.user_id == requested_user_id,
                )
            )).scalars().first()
            if not target_ug:
                return jsonify({'detail': 'Target user is not a member of this group'}), 400
            target_user_id = requested_user_id

        # Convert empty string to None for expires_at (empty string is not valid for timestamp)
        expires_at = data.get('expires_at')
        expires_at = _parse_expires_at(expires_at)

        api_key = ApiKey(
            key=generate_api_key(),
            name=data.get('name'),
            description=data.get('description'),
            group_id=group_id,
            user_id=target_user_id,
            expires_at=expires_at,
            allowed_models=data.get('allowed_models') or None,
            tags=data.get('tags') or None,
            workspace_id=group.workspace_id,
            unlimited_budget=False,
            budget=100.0,
            rpm=data.get('rpm') or None,
            tpm=data.get('tpm') or None,
        )
        session.add(api_key)
        await session.flush()

        # Create default budget record
        budget_entry = ApiKeyBudget(
            api_key_id=api_key.id,
            amount=100.0,
            remaining=100.0,
        )
        session.add(budget_entry)
        await session.commit()
        await session.refresh(api_key)

        return jsonify(api_key.to_dict()), 201


@apikeys_bp.route('/apikeys/<int:api_key_id>', methods=['PUT'])
@token_required
@require_api_key_access
async def update_api_key(current_user, api_key_id):
    """Update an API key. Invalidates cache after update.
    Members can only edit their own keys if member.apikey.edit_own is enabled.
    Admins/root can edit any key in the group."""
    data = await request.get_json()

    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404

        # check_permission returns True for root, so no separate root guard needed
        group_id = api_key.group_id
        user_role = await _get_role(group_id, current_user.id, session=session)
        is_owner = api_key.user_id == current_user.id
        if not is_owner and not await check_permission(user_role, 'apikey.manage', session=session):
            return jsonify({'detail': 'You do not have permission to manage other users\' API keys'}), 403
        if is_owner and not await check_permission(user_role, 'apikey.edit_own', session=session):
            return jsonify({'detail': 'Editing own API keys is disabled for your role'}), 403

        # Check field-specific permissions (check_permission handles root)
        if 'unlimited_budget' in data and not await check_permission(user_role, 'apikey.unlimited_budget', session=session):
            return jsonify({'detail': 'You do not have permission to toggle unlimited budget'}), 403
        if 'budget' in data and not await check_permission(user_role, 'apikey.add_budget', session=session):
            return jsonify({'detail': 'You do not have permission to add budget'}), 403
        if 'allowed_models' in data and not await check_permission(user_role, 'apikey.edit_models', session=session):
            return jsonify({'detail': 'You do not have permission to edit allowed models'}), 403

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
            api_key.expires_at = _parse_expires_at(expires_at)
        if 'tags' in data:
            api_key.tags = data['tags'] if data['tags'] else None
        if 'unlimited_budget' in data:
            new_unlimited = bool(data['unlimited_budget'])
            if new_unlimited and not api_key.unlimited_budget:
                # Turning ON unlimited budget: zero out all active budget records
                await session.execute(
                    update(ApiKeyBudget)
                    .where(
                        ApiKeyBudget.api_key_id == api_key_id,
                        ApiKeyBudget.remaining > 0,
                    )
                    .values(remaining=0.0)
                )
                api_key.last_synced_remaining = 0.0
            api_key.unlimited_budget = new_unlimited
            # Reset budget to 0 when toggling unlimited_budget (both on and off)
            api_key.budget = 0.0
        if 'budget' in data:
            val = data['budget']
            if val is not None and val != '':
                add_amount = float(val)
                # Budget is additive: append to current remaining budget
                current_budget = api_key.budget or 0.0
                api_key.budget = current_budget + add_amount
            # If val is None or '', don't change the budget (use unlimited_budget flag instead)
        if 'rpm' in data:
            val = data['rpm']
            api_key.rpm = int(val) if val is not None and val != '' else None
        if 'tpm' in data:
            val = data['tpm']
            api_key.tpm = int(val) if val is not None and val != '' else None

        await session.commit()
        await session.refresh(api_key)

        # Update cache with new values so budget/unlimited checks see them immediately
        try:
            from app.cache import get_async_cache
            cache = get_async_cache()
            cached_info = await cache.get_api_key_info(api_key.key)
            if cached_info is not None:
                cached_info['budget'] = api_key.budget
                cached_info['unlimited_budget'] = api_key.unlimited_budget
                cached_info['is_active'] = api_key.is_active
                cached_info['allowed_models'] = api_key.allowed_models or []
                cached_info['rpm'] = api_key.rpm
                cached_info['tpm'] = api_key.tpm
                await cache.set_api_key_info(api_key.key, cached_info)
            else:
                await cache.invalidate_api_key_by_id(api_key_id)
            # Update the dedicated budget remaining key so gateway budget checks
            # see the new value immediately.
            from app.budget_manager import get_async_budget_manager
            bm = get_async_budget_manager()
            if not api_key.unlimited_budget and api_key.budget is not None:
                await bm.set_remaining(api_key.key, float(api_key.budget))
            elif api_key.unlimited_budget:
                # Unlimited budget — remove the dedicated remaining key
                await bm.invalidate(api_key.key)
        except Exception:
            pass

        return jsonify(api_key.to_dict())


@apikeys_bp.route('/apikeys/<int:api_key_id>/models', methods=['GET'])
@token_required
async def get_api_key_models(current_user, api_key_id):
    """Get the list of models available to this API key, with per-model usage stats."""
    from app.models import UsageRecord, get_group_models_with_shares
    import hashlib

    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404

        if current_user not in api_key.group.users:
            return jsonify({'detail': 'You do not have access to this API key'}), 403

        # Get all active models in the group (including shared models)
        pairs = await get_group_models_with_shares(api_key.group_id, session=session)
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
            (await session.execute(
                select(
                    UsageRecord.model_name,
                    func.count(UsageRecord.id).label('requests'),
                    func.coalesce(func.sum(UsageRecord.input_tokens), 0).label('input_tokens'),
                    func.coalesce(func.sum(UsageRecord.output_tokens), 0).label('output_tokens'),
                    func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label('reasoning_tokens'),
                )
                .where(UsageRecord.api_key_hash == key_hash)
                .group_by(UsageRecord.model_name)
            )).all()
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
    from app.cache import get_async_cache
    import hashlib

    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404

        if current_user not in api_key.group.users:
            return jsonify({'detail': 'You do not have access to this API key'}), 403

        if not await _is_admin_or_above_inner(api_key.group_id, current_user.id, session=session) and api_key.user_id != current_user.id:
            return jsonify({'detail': 'You do not have access to this API key'}), 403

        key_hash = hashlib.sha256(api_key.key.encode()).hexdigest()
        cache = get_async_cache()

        # ── Usage stats: Metabase when enabled, otherwise cache only (updated by sync job) ──
        if metabase_client.is_enabled():
            try:
                # Fetch all-time totals from Metabase
                all_time_filters = {"api_key_hash": key_hash}
                totals = await metabase_client.fetch_totals(all_time_filters)

                now = datetime.now(timezone.utc)
                start_of_year = datetime(now.year, 1, 1, tzinfo=timezone.utc)
                start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

                # Fetch year-to-date totals
                ytd_filters = {
                    "api_key_hash": key_hash,
                    "start": start_of_year.date(),
                }
                ytd_totals = await metabase_client.fetch_totals(ytd_filters)

                # Fetch month-to-date totals
                mtd_filters = {
                    "api_key_hash": key_hash,
                    "start": start_of_month.date(),
                }
                mtd_totals = await metabase_client.fetch_totals(mtd_filters)

                usage_totals = {
                    'requests': totals['requests'],
                    'input_tokens': totals['input_tokens'],
                    'output_tokens': totals['output_tokens'],
                    'reasoning_tokens': totals['reasoning_tokens'],
                    'estimated_cost': round(float(totals['total_cost'] or 0), 6),
                    'ytd_cost': round(float(ytd_totals['total_cost'] or 0), 6),
                    'mtd_cost': round(float(mtd_totals['total_cost'] or 0), 6),
                    'ytd_input_tokens': ytd_totals['input_tokens'],
                    'ytd_output_tokens': ytd_totals['output_tokens'],
                    'ytd_reasoning_tokens': ytd_totals['reasoning_tokens'],
                    'mtd_input_tokens': mtd_totals['input_tokens'],
                    'mtd_output_tokens': mtd_totals['output_tokens'],
                    'mtd_reasoning_tokens': mtd_totals['reasoning_tokens'],
                    'total_image_count': totals.get('output_image_number', 0),
                    'total_video_count': totals.get('output_video_number', 0),
                    'total_audio_seconds': round(float(totals.get('output_audio_seconds', 0) or 0), 4),
                }
            except Exception as exc:
                logger.error("metabase fetch_totals failed for apikey detail, falling back to cache: %s", exc)
                # Fall back to cache on Metabase error
                cached_info = await cache.get_api_key_info(api_key.key) or {}
                usage_totals = {
                    'requests': int(cached_info.get('request_count', 0) or 0),
                    'input_tokens': int(cached_info.get('total_input_tokens', 0) or 0),
                    'output_tokens': int(cached_info.get('total_output_tokens', 0) or 0),
                    'reasoning_tokens': int(cached_info.get('total_reasoning_tokens', 0) or 0),
                    'estimated_cost': round(float(cached_info.get('total_cost_usd', 0) or 0), 6),
                    'ytd_cost': round(float(cached_info.get('ytd_cost_usd', 0) or 0), 6),
                    'mtd_cost': round(float(cached_info.get('mtd_cost_usd', 0) or 0), 6),
                    'ytd_input_tokens': int(cached_info.get('ytd_input_tokens', 0) or 0),
                    'ytd_output_tokens': int(cached_info.get('ytd_output_tokens', 0) or 0),
                    'ytd_reasoning_tokens': int(cached_info.get('ytd_reasoning_tokens', 0) or 0),
                    'mtd_input_tokens': int(cached_info.get('mtd_input_tokens', 0) or 0),
                    'mtd_output_tokens': int(cached_info.get('mtd_output_tokens', 0) or 0),
                    'mtd_reasoning_tokens': int(cached_info.get('mtd_reasoning_tokens', 0) or 0),
                    'total_image_count': int(cached_info.get('total_image_count', 0) or 0),
                    'total_video_count': int(cached_info.get('total_video_count', 0) or 0),
                    'total_audio_seconds': round(float(cached_info.get('total_audio_seconds', 0) or 0), 4),
                }
        else:
            # Read from cache only — no DB queries; stats are synced to cache by background jobs
            cached_info = await cache.get_api_key_info(api_key.key) or {}
            usage_totals = {
                'requests': int(cached_info.get('request_count', 0) or 0),
                'input_tokens': int(cached_info.get('total_input_tokens', 0) or 0),
                'output_tokens': int(cached_info.get('total_output_tokens', 0) or 0),
                'reasoning_tokens': int(cached_info.get('total_reasoning_tokens', 0) or 0),
                'estimated_cost': round(float(cached_info.get('total_cost_usd', 0) or 0), 6),
                'ytd_cost': round(float(cached_info.get('ytd_cost_usd', 0) or 0), 6),
                'mtd_cost': round(float(cached_info.get('mtd_cost_usd', 0) or 0), 6),
                'ytd_input_tokens': int(cached_info.get('ytd_input_tokens', 0) or 0),
                'ytd_output_tokens': int(cached_info.get('ytd_output_tokens', 0) or 0),
                'ytd_reasoning_tokens': int(cached_info.get('ytd_reasoning_tokens', 0) or 0),
                'mtd_input_tokens': int(cached_info.get('mtd_input_tokens', 0) or 0),
                'mtd_output_tokens': int(cached_info.get('mtd_output_tokens', 0) or 0),
                'mtd_reasoning_tokens': int(cached_info.get('mtd_reasoning_tokens', 0) or 0),
                'total_image_count': int(cached_info.get('total_image_count', 0) or 0),
                'total_video_count': int(cached_info.get('total_video_count', 0) or 0),
                'total_audio_seconds': round(float(cached_info.get('total_audio_seconds', 0) or 0), 4),
            }

        # ── By model usage (Metabase when enabled, otherwise DB) ──────────────
        if metabase_client.is_enabled():
            try:
                metabase_result = await metabase_client.fetch_by_model({"api_key_hash": key_hash})
                by_model = [
                    {
                        'model_name': r['model_name'],
                        'requests': r['requests'],
                        'input_tokens': r['input_tokens'],
                        'output_tokens': r['output_tokens'],
                        'reasoning_tokens': r.get('reasoning_tokens', 0),
                        'estimated_cost': round(float(r.get('total_cost_usd', 0) or 0), 6),
                    }
                    for r in metabase_result
                ]
            except Exception as exc:
                logger.error("metabase fetch_by_model failed for apikey detail: %s", exc)
                by_model = []  # graceful fallback — empty list instead of 502
        else:
            by_model_rows = (
                await session.execute(
                    select(
                        UsageRecord.model_name,
                        func.count(UsageRecord.id).label('requests'),
                        func.coalesce(func.sum(UsageRecord.input_tokens), 0).label('input_tokens'),
                        func.coalesce(func.sum(UsageRecord.output_tokens), 0).label('output_tokens'),
                        func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0).label('reasoning_tokens'),
                        func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).label('estimated_cost'),
                    )
                    .where(UsageRecord.api_key_hash == key_hash)
                    .group_by(UsageRecord.model_name)
                    .order_by(func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0).desc())
                    .limit(50)
                )
            ).all()

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
        pairs = await get_group_models_with_shares(api_key.group_id, session=session)
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
                'discount': float(m.discount) if m.discount is not None else 1.0,
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
            await session.execute(
                select(ApiKeyBudget)
                .where(ApiKeyBudget.api_key_id == api_key_id)
                .order_by(ApiKeyBudget.created_at.asc())
            )
        ).scalars().all()
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
    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404

        if current_user not in api_key.group.users:
            return jsonify({'detail': 'You do not have access to this API key'}), 403

        # Permission: root can do anything; admin/member need apikey.manage for others, apikey.edit_own for own
        group_id = api_key.group_id
        user_role = await _get_role(group_id, current_user.id, session=session)
        is_owner = api_key.user_id == current_user.id
        if user_role != 'root':
            if not is_owner and not await check_permission(user_role, 'apikey.manage', session=session):
                return jsonify({'detail': 'You do not have permission to manage other users\' API keys'}), 403
            if is_owner and not await check_permission(user_role, 'apikey.edit_own', session=session):
                return jsonify({'detail': 'Deleting own API keys is disabled for your role'}), 403

        # Invalidate cache before deleting (need the raw key for cache lookup)
        try:
            from app.cache import get_async_cache
            from app.budget_manager import get_async_budget_manager
            await get_async_cache().invalidate_api_key(api_key.key)
            await get_async_budget_manager().invalidate(api_key.key)
        except Exception:
            pass

        await session.delete(api_key)
        await session.commit()

        return '', 204


@apikeys_bp.route('/apikeys/<int:api_key_id>/regenerate', methods=['POST'])
@token_required
async def regenerate_api_key(current_user, api_key_id):
    """Regenerate an API key (revokes the old one). Invalidates cache for old key.
    Members can only regenerate their own keys if member.apikey.edit_own is enabled.
    Admins/root can regenerate any key in the group."""
    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404

        if current_user not in api_key.group.users:
            return jsonify({'detail': 'You do not have access to this API key'}), 403

        # Permission: root can do anything; admin/member need apikey.manage for others, apikey.edit_own for own
        group_id = api_key.group_id
        user_role = await _get_role(group_id, current_user.id, session=session)
        is_owner = api_key.user_id == current_user.id
        if user_role != 'root':
            if not is_owner and not await check_permission(user_role, 'apikey.manage', session=session):
                return jsonify({'detail': 'You do not have permission to manage other users\' API keys'}), 403
            if is_owner and not await check_permission(user_role, 'apikey.edit_own', session=session):
                return jsonify({'detail': 'Regenerating own API keys is disabled for your role'}), 403

        # Invalidate cache for the old key before regenerating
        old_key = api_key.key
        try:
            from app.cache import get_async_cache
            from app.budget_manager import get_async_budget_manager
            await get_async_cache().invalidate_api_key(old_key)
            await get_async_budget_manager().invalidate(old_key)
        except Exception:
            pass

        api_key.key = generate_api_key()
        api_key.request_count = 0
        api_key.token_count = 0
        await session.commit()
        await session.refresh(api_key)

        return jsonify(api_key.to_dict())


# ============== Budget Management ==============

@apikeys_bp.route('/apikeys/<int:api_key_id>/budgets', methods=['GET'])
@token_required
async def list_budgets(current_user, api_key_id):
    """List all budget records for an API key."""
    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404
        if current_user not in api_key.group.users:
            return jsonify({'detail': 'You do not have access to this API key'}), 403

        budgets = (
            (await session.execute(
                select(ApiKeyBudget)
                .where(ApiKeyBudget.api_key_id == api_key_id)
                .order_by(ApiKeyBudget.created_at.asc())
            )).scalars().all()
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
    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
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
        session.add(budget_entry)

        # Also update ApiKey.budget for backward compatibility
        current_budget = api_key.budget or 0.0
        api_key.budget = current_budget + amount

        await session.commit()
        await session.refresh(budget_entry)
        await session.refresh(api_key)

        # Update cache with new budget value so budget checks see it immediately
        try:
            from app.cache import get_async_cache
            cache = get_async_cache()
            cached_info = await cache.get_api_key_info(api_key.key)
            if cached_info is not None:
                cached_info['budget'] = api_key.budget
                await cache.set_api_key_info(api_key.key, cached_info)
            else:
                # Cache miss — populate from scratch
                await cache.invalidate_api_key_by_id(api_key_id)
            # Update the dedicated budget remaining key so gateway budget checks
            # see the new value immediately.
            if not api_key.unlimited_budget and api_key.budget is not None:
                from app.budget_manager import get_async_budget_manager
                await get_async_budget_manager().set_remaining(api_key.key, float(api_key.budget))
        except Exception:
            pass

        return jsonify(budget_entry.to_dict()), 201


@apikeys_bp.route('/apikeys/<int:api_key_id>/budgets/<int:budget_id>', methods=['DELETE'])
@token_required
@require_apikey_permission('apikey.add_budget')
async def delete_budget(current_user, api_key_id, budget_id):
    """Delete a budget entry. Requires apikey.add_budget permission."""
    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
                selectinload(ApiKey.group).selectinload(Group.users),
                selectinload(ApiKey.policies),
                selectinload(ApiKey.user),
            ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404

        budget_entry = (await session.execute(
            select(ApiKeyBudget).where(
                ApiKeyBudget.id == budget_id,
                ApiKeyBudget.api_key_id == api_key_id,
            )
        )).scalars().first()
        if not budget_entry:
            return jsonify({'detail': 'Budget entry not found'}), 404

        # Subtract the remaining amount from ApiKey.budget for backward compat
        if api_key.budget is not None:
            api_key.budget = max((api_key.budget or 0.0) - float(budget_entry.remaining or 0), 0.0)

        await session.delete(budget_entry)
        await session.commit()
        await session.refresh(api_key)

        # Update cache with new budget value so budget checks see it immediately
        try:
            from app.cache import get_async_cache
            cache = get_async_cache()
            cached_info = await cache.get_api_key_info(api_key.key)
            if cached_info is not None:
                cached_info['budget'] = api_key.budget
                await cache.set_api_key_info(api_key.key, cached_info)
            else:
                await cache.invalidate_api_key_by_id(api_key_id)
            # Update the dedicated budget remaining key so gateway budget checks
            # see the new value immediately.
            if not api_key.unlimited_budget and api_key.budget is not None:
                from app.budget_manager import get_async_budget_manager
                await get_async_budget_manager().set_remaining(api_key.key, float(api_key.budget))
        except Exception:
            pass

        return '', 204


# ── Auto-refill (bulk budget top-up for tagged keys) ─────────────────────────

def _parse_refill_tags(raw):
    """Normalize the ``tags`` request parameter into a list of {name, value} dicts.

    Accepts either a list of objects (``[{"name": "dept", "value": "a"}]``) or a
    list of ``"name:value"`` strings. Returns ``[]`` when nothing usable is given.
    """
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    parsed = []
    for item in raw:
        if isinstance(item, dict):
            name = (item.get("name") or "").strip()
            value = (item.get("value") or "").strip()
            if name:
                parsed.append({"name": name, "value": value})
        elif isinstance(item, str):
            # Allow "name:value" shorthand.
            if ":" in item:
                name, value = item.split(":", 1)
                name, value = name.strip(), value.strip()
            else:
                name, value = item.strip(), ""
            if name:
                parsed.append({"name": name, "value": value})
    return parsed


def _tags_match(key_tags, required_tags, mode: str = "all") -> bool:
    """Return True if an API key's tags satisfy the required tag filter.

    A required tag pair matches when the key has a tag with the same ``name``
    and ``value``. With ``mode='all'`` (default) the key must contain *every*
    required pair; with ``mode='any'`` at least one is enough.
    """
    if not required_tags:
        return True
    if not key_tags:
        return False

    key_pairs = {
        (t.get("name"), t.get("value"))
        for t in key_tags
        if isinstance(t, dict) and t.get("name")
    }

    def _hit(req):
        return (req["name"], req["value"]) in key_pairs

    if mode == "any":
        return any(_hit(r) for r in required_tags)
    return all(_hit(r) for r in required_tags)


@apikeys_bp.route('/apikeys/auto-refill', methods=['POST'])
async def auto_refill_api_keys():
    """Bulk top-up budget for recently-used, tagged API keys.

    Scans API keys that were used within the lookback window (default 30 days),
    keeps only those carrying the requested tags, and — for every key whose
    real-time remaining budget is below ``threshold`` — adds a budget entry so
    its remaining is restored to exactly ``target``.

    Request body (JSON):
        tags       — list of {"name","value"} pairs (or "name:value" strings)
                     a key must match to be eligible. Required.
        threshold  — float (USD). Keys with remaining < threshold are refilled.
        target     — float (USD). Remaining is set to this value. Must be > 0.
        days       — int, optional. Lookback window in days (default 30).
        tags_match — "all" (default) or "any". How ``tags`` is combined.
        dry_run    — bool, optional. When true, preview without writing.

    Response:
        summary of scanned / matched / eligible / refilled counts, plus a
        per-key breakdown.
    """
    data = await request.get_json() or {}

    required_tags = _parse_refill_tags(data.get("tags"))
    if not required_tags:
        logger.warning("auto-refill: rejected, no usable tags provided")
        return jsonify({'detail': 'tags is required (non-empty list of name/value pairs)'}), 400

    threshold = data.get("threshold")
    target = data.get("target")
    if threshold is None or target is None:
        logger.warning("auto-refill: rejected, missing threshold/target")
        return jsonify({'detail': 'threshold and target are required'}), 400
    try:
        threshold = float(threshold)
        target = float(target)
    except (TypeError, ValueError):
        logger.warning("auto-refill: rejected, non-numeric threshold/target")
        return jsonify({'detail': 'threshold and target must be numbers'}), 400
    if threshold < 0 or target <= 0:
        logger.warning("auto-refill: rejected, threshold=%s target=%s out of range", threshold, target)
        return jsonify({'detail': 'threshold must be >= 0 and target must be > 0'}), 400

    days = data.get("days", 30)
    try:
        days = int(days)
    except (TypeError, ValueError):
        return jsonify({'detail': 'days must be an integer'}), 400
    if days <= 0:
        return jsonify({'detail': 'days must be positive'}), 400

    tags_match_mode = (data.get("tags_match") or "all").strip().lower()
    if tags_match_mode not in ("all", "any"):
        return jsonify({'detail': "tags_match must be 'all' or 'any'"}), 400

    dry_run = bool(data.get("dry_run", False))

    cutoff = datetime.utcnow() - timedelta(days=days)

    logger.info(
        "auto-refill: starting (tags=%s match=%s threshold=%s target=%s days=%s cutoff=%s dry_run=%s)",
        required_tags, tags_match_mode, threshold, target, days, cutoff.isoformat(), dry_run,
    )

    from app.budget_manager import get_async_budget_manager
    bm = get_async_budget_manager()

    scanned = 0
    matched = 0
    eligible = 0
    refilled = []
    skipped = []

    async with get_db_session() as session:
        # 1. Keys used within the lookback window.
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.last_used_at.isnot(None),
                ApiKey.last_used_at >= cutoff,
            ).options(selectinload(ApiKey.budgets))
        )
        keys = result.scalars().all()
        logger.info("auto-refill: scanned %d key(s) used since cutoff", len(keys))

        for ak in keys:
            scanned += 1

            # 2. Tag filter.
            if not _tags_match(ak.tags or [], required_tags, mode=tags_match_mode):
                continue
            matched += 1

            # Unlimited-budget keys have no spendable quota to refill.
            if ak.unlimited_budget:
                logger.debug("auto-refill: skip key id=%d name=%s (unlimited_budget)", ak.id, ak.name)
                skipped.append({
                    "api_key_id": ak.id,
                    "name": ak.name,
                    "key": ak.key,
                    "reason": "unlimited_budget",
                })
                continue

            # 3. Real-time remaining (cache-first, DB fallback). None == unknown.
            remaining = await bm.get_remaining(ak.key, db_session=session)
            if remaining is None:
                remaining = 0.0 if ak.budget is None else float(ak.budget)

            if remaining >= threshold:
                logger.debug(
                    "auto-refill: skip key id=%d name=%s (remaining=%.6f >= threshold=%.6f)",
                    ak.id, ak.name, remaining, threshold,
                )
                skipped.append({
                    "api_key_id": ak.id,
                    "name": ak.name,
                    "key": ak.key,
                    "remaining": round(remaining, 6),
                    "reason": "above_threshold",
                })
                continue

            # 4. Top up to target.
            top_up = target - remaining
            if top_up <= 0:
                # target not higher than current remaining — nothing to add.
                logger.debug(
                    "auto-refill: skip key id=%d name=%s (target=%.6f not higher than remaining=%.6f)",
                    ak.id, ak.name, target, remaining,
                )
                skipped.append({
                    "api_key_id": ak.id,
                    "name": ak.name,
                    "key": ak.key,
                    "remaining": round(remaining, 6),
                    "reason": "target_not_higher",
                })
                continue

            eligible += 1
            entry = {
                "api_key_id": ak.id,
                "name": ak.name,
                "key": ak.key,
                "before": round(remaining, 6),
                "after": round(target, 6),
                "top_up": round(top_up, 6),
            }

            if dry_run:
                logger.info(
                    "auto-refill: [dry-run] would top up key id=%d name=%s before=%.6f after=%.6f top_up=%.6f",
                    ak.id, ak.name, remaining, target, top_up,
                )
                refilled.append({**entry, "dry_run": True})
                continue

            # Append a budget record (same pattern as add_budget) and update
            # the ApiKey.budget summary to the new remaining total.
            budget_entry = ApiKeyBudget(
                api_key_id=ak.id,
                amount=top_up,
                remaining=top_up,
            )
            session.add(budget_entry)
            ak.budget = target

            # Push the new remaining into the budget cache immediately so the
            # gateway's real-time budget checks observe it without a cache miss.
            try:
                await bm.set_remaining(ak.key, float(target))
            except Exception as exc:
                logger.warning(
                    "auto-refill: failed to update budget cache for key id=%d: %s",
                    ak.id, exc, exc_info=True,
                )

            logger.info(
                "auto-refill: topped up key id=%d name=%s before=%.6f after=%.6f top_up=%.6f",
                ak.id, ak.name, remaining, target, top_up,
            )
            refilled.append(entry)

        if not dry_run and refilled:
            await session.commit()
            logger.info("auto-refill: committed %d budget record(s)", len(refilled))

    logger.info(
        "auto-refill: done scanned=%d matched=%d eligible=%d refilled=%d skipped=%d (dry_run=%s)",
        scanned, matched, eligible, len(refilled), len(skipped), dry_run,
    )

    return jsonify({
        "dry_run": dry_run,
        "days": days,
        "tags": required_tags,
        "tags_match": tags_match_mode,
        "threshold": threshold,
        "target": target,
        "summary": {
            "scanned": scanned,
            "matched": matched,
            "eligible": eligible,
            "refilled": len(refilled),
            "skipped": len(skipped),
        },
        "refilled": refilled,
        "skipped": skipped,
    }), 200


# ── API Key Policy CRUD ──────────────────────────────────────────────────────

@apikeys_bp.route('/apikeys/<int:api_key_id>/policies', methods=['GET'])
@token_required
@require_api_key_access
async def list_policies(current_user, api_key_id):
    """List all policies for an API key."""
    async with get_db_session() as session:
        policies = (
            (await session.execute(
                select(ApiKeyPolicy).where(
                    ApiKeyPolicy.api_key_id == api_key_id
                )
            )).scalars().all()
        )
        return jsonify([p.to_dict() for p in policies])


@apikeys_bp.route('/apikeys/<int:api_key_id>/policies/<policy_type>', methods=['PUT'])
@token_required
@require_api_key_access
async def upsert_policy(current_user, api_key_id, policy_type):
    """Create or update a policy for an API key."""
    data = await request.get_json()
    if not data:
        return jsonify({'detail': 'Request body is required'}), 400

    async with get_db_session() as session:
        policy = (await session.execute(
            select(ApiKeyPolicy).where(
                ApiKeyPolicy.api_key_id == api_key_id,
                ApiKeyPolicy.policy_type == policy_type,
            )
        )).scalars().first()

        if policy:
            if 'enabled' in data:
                policy.enabled = bool(data['enabled'])
            if 'config' in data:
                policy.config = data['config']
        else:
            policy = ApiKeyPolicy(
                api_key_id=api_key_id,
                policy_type=policy_type,
                enabled=data.get('enabled', True),
                config=data.get('config', {}),
            )
            session.add(policy)

        await session.commit()
        return jsonify(policy.to_dict())


@apikeys_bp.route('/apikeys/<int:api_key_id>/policies/<policy_type>', methods=['DELETE'])
@token_required
@require_api_key_access
async def delete_policy(current_user, api_key_id, policy_type):
    """Delete a policy for an API key."""
    async with get_db_session() as session:
        policy = (await session.execute(
            select(ApiKeyPolicy).where(
                ApiKeyPolicy.api_key_id == api_key_id,
                ApiKeyPolicy.policy_type == policy_type,
            )
        )).scalars().first()

        if not policy:
            return jsonify({'detail': 'Policy not found'}), 404

        await session.delete(policy)
        await session.commit()
        return '', 204

# ═══════════════════════════════════════════════════════════════════════════════
# API Key Management (workspace-scoped, admin-facing)
# ═══════════════════════════════════════════════════════════════════════════════

@apikeys_bp.route('/apikeys/manage', methods=['GET'])
@token_required
async def manage_api_keys(current_user):
    """List all API keys in the current workspace with pagination and search.

    Query params:
        page     — page number (1-based, default 1)
        per_page — items per page (default 20, max 100)
        search   — filter by API key name or user name (case-insensitive)
        group_id — filter by group ID (optional)

    Requires: admin/root in at least one group, or apikey.manage permission.
    """
    from app.models import UserGroup, User

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search = (request.args.get('search', '') or '').strip()
    group_filter = request.args.get('group_id', None, type=int)

    async with get_db_session() as session:
        from sqlalchemy.orm import joinedload

        # Find groups where the current user is admin/root so they can view all keys
        manageable_group_ids = set()
        for grp in current_user.groups:
            ug_result = await session.execute(
                select(UserGroup).where(
                    UserGroup.group_id == grp.id,
                    UserGroup.user_id == current_user.id,
                )
            )
            ug = ug_result.scalars().first()
            if ug and _role_rank(ug.role) >= _role_rank('admin'):
                manageable_group_ids.add(grp.id)
            elif ug and await check_permission(ug.role, 'apikey.manage', session=session):
                manageable_group_ids.add(grp.id)

        if not manageable_group_ids:
            return jsonify({'data': [], 'total': 0, 'page': page, 'per_page': per_page}), 200

        # Build search conditions
        conditions = [ApiKey.group_id.in_(manageable_group_ids)]
        if group_filter is not None:
            if group_filter not in manageable_group_ids:
                return jsonify({'detail': 'You do not have access to this group'}), 403
            conditions.append(ApiKey.group_id == group_filter)

        if search:
            from sqlalchemy import or_
            conditions.append(
                or_(
                    ApiKey.name.ilike(f'%{search}%'),
                    ApiKey.key.ilike(f'%{search}%'),
                    ApiKey.user.has(User.username.ilike(f'%{search}%')),
                )
            )

        # Count total
        count_q = select(func.count(ApiKey.id)).where(*conditions)
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        # Fetch page
        offset = (page - 1) * per_page
        data_q = (
            select(ApiKey)
            .options(
                joinedload(ApiKey.group),
                joinedload(ApiKey.user),
                joinedload(ApiKey.budgets),
            )
            .where(*conditions)
            .order_by(ApiKey.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )

        result = await session.execute(data_q)
        api_keys = result.unique().scalars().all()

        items = []
        for k in api_keys:
            d = k.to_dict()
            d['group_name'] = k.group.name if k.group else None
            d['user_name'] = k.user.username if k.user else None
            if k.unlimited_budget:
                d['remaining_budget'] = None  # unlimited
            elif k.budgets:
                remaining = sum(float(b.remaining or 0) for b in k.budgets)
                d['remaining_budget'] = round(remaining, 4)
            elif k.budget is not None:
                d['remaining_budget'] = round(float(k.budget), 4)
            else:
                d['remaining_budget'] = 0.0
            d['unlimited_budget'] = k.unlimited_budget
            items.append(d)

        return jsonify({
            'data': items,
            'total': total,
            'page': page,
            'per_page': per_page,
        })


@apikeys_bp.route('/apikeys/<int:api_key_id>/assign', methods=['PUT'])
@token_required
async def assign_api_key(current_user, api_key_id):
    """Reassign an API key to a different user and/or group, or update RPM/TPM/tags.

    Request body:
        user_id  — new user ID (optional)
        group_id — new group ID (optional)
        rpm      — requests per minute limit (optional, null to clear)
        tpm      — tokens per minute limit (optional, null to clear)
        tags     — tag list (optional, null/empty to clear)

    Requires: admin/root in both the source and target groups.
    """
    from app.models import UserGroup, User

    data = await request.get_json()
    if not data:
        return jsonify({'detail': 'Request body is required'}), 400

    new_user_id = data.get('user_id')
    new_group_id = data.get('group_id')
    new_rpm = data.get('rpm')
    new_tpm = data.get('tpm')

    has_rpm = 'rpm' in data
    has_tpm = 'tpm' in data
    has_tags = 'tags' in data

    if new_user_id is None and new_group_id is None and not has_rpm and not has_tpm and not has_tags:
        return jsonify({'detail': 'At least one of user_id, group_id, rpm, tpm, or tags is required'}), 400

    async with get_db_session() as session:
        api_key = await session.get(ApiKey, api_key_id, options=[
            selectinload(ApiKey.group).selectinload(Group.users),
            selectinload(ApiKey.user),
        ])
        if not api_key:
            return jsonify({'detail': 'API key not found'}), 404

        source_group_id = api_key.group_id

        # Check source group permission: must be admin/root
        source_ug = (await session.execute(
            select(UserGroup).where(
                UserGroup.group_id == source_group_id,
                UserGroup.user_id == current_user.id,
            )
        )).scalars().first()
        if not source_ug or (_role_rank(source_ug.role) < _role_rank('admin') and not await check_permission(source_ug.role, 'apikey.manage', session=session)):
            return jsonify({'detail': 'You do not have permission to manage API keys in the source group'}), 403

        # If changing group, check target group permission
        if new_group_id is not None and new_group_id != source_group_id:
            target_ug = (await session.execute(
                select(UserGroup).where(
                    UserGroup.group_id == new_group_id,
                    UserGroup.user_id == current_user.id,
                )
            )).scalars().first()
            if not target_ug or _role_rank(target_ug.role) < _role_rank('admin'):
                return jsonify({'detail': 'You do not have permission to assign API keys to the target group'}), 403

            target_group = await session.get(Group, new_group_id)
            if not target_group:
                return jsonify({'detail': 'Target group not found'}), 404

            api_key.group_id = new_group_id

        # If changing user, verify user exists and is in the (new) group
        if new_user_id is not None:
            effective_group_id = new_group_id if new_group_id is not None else source_group_id
            target_user = await session.get(User, new_user_id)
            if not target_user:
                return jsonify({'detail': 'User not found'}), 404

            user_in_group = (await session.execute(
                select(UserGroup).where(
                    UserGroup.group_id == effective_group_id,
                    UserGroup.user_id == new_user_id,
                )
            )).scalars().first()
            if not user_in_group:
                return jsonify({'detail': 'User is not a member of the target group'}), 400

            api_key.user_id = new_user_id

        # Update RPM/TPM if provided
        if has_rpm:
            val = data['rpm']
            api_key.rpm = int(val) if val is not None and val != '' else None
        if has_tpm:
            val = data['tpm']
            api_key.tpm = int(val) if val is not None and val != '' else None

        # Update tags if provided
        if has_tags:
            api_key.tags = data['tags'] if data['tags'] else None

        await session.commit()
        await session.refresh(api_key)

        # Invalidate cache
        try:
            from app.cache import get_async_cache
            cache = get_async_cache()
            await cache.invalidate_api_key_by_id(api_key_id)
        except Exception:
            pass

        result = api_key.to_dict()
        result['group_name'] = api_key.group.name if api_key.group else None
        result['user_name'] = api_key.user.username if api_key.user else None
        result['rpm'] = api_key.rpm
        result['tpm'] = api_key.tpm
        return jsonify(result)
