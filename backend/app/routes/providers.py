"""
Provider and Model management routes.
"""
from datetime import datetime, timezone
from quart import Blueprint, request, jsonify
from functools import wraps
import os

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app import get_db_session
from app.models import Provider, Model, Group
from app.auth import token_required
from app.routes.permissions import (
    _get_role,
    _is_root,
    _is_member,
    _is_admin_or_above_inner,
    check_permission,
    require_provider_permission,
)


async def _maybe_create_tencentvod_api_token(provider: Provider) -> None:
    """
    For TencentVOD providers, auto-fetch or create an ApiToken.

    First checks for existing tokens via DescribeAigcApiTokens — if any exist,
    uses the first one. Otherwise creates a new token via CreateAigcApiToken.

    Reads secret_id (AK), secret_key (SK), and optionally app_id from
    provider.extra_config. The resulting ApiToken is stored in provider.api_key.

    Does nothing if api_key is already set.

    The TencentVOD SDK calls are native async (httpx.AsyncClient), so they
    do not block the event loop.
    """
    if provider.type != 'tencentvod':
        return

    extra = provider.extra_config or {}
    secret_id = extra.get('secret_id', '').strip()
    secret_key = extra.get('secret_key', '').strip()
    app_id = extra.get('app_id')

    if not secret_id or not secret_key:
        return

    try:
        from app.providers.tencent.vod.image_generation import (
            create_aigc_api_token,
            describe_aigc_api_tokens,
        )
        sub_app_id = int(app_id) if app_id else None

        # Check for existing tokens first
        existing_tokens = await describe_aigc_api_tokens(
            secret_id, secret_key, sub_app_id
        )
        if existing_tokens:
            provider.api_key = existing_tokens[0]
        else:
            provider.api_key = await create_aigc_api_token(
                secret_id, secret_key, sub_app_id
            )
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

    stmt = select(Provider).options(selectinload(Provider.models))
    if group_id:
        stmt = stmt.where(Provider.group_id == group_id)

    stmt = stmt.offset(skip).limit(limit)
    async with get_db_session() as session:
        result = await session.execute(stmt)
        providers = result.scalars().all()
        return jsonify([p.to_dict() for p in providers])


@providers_bp.route('/providers/', methods=['POST'])
@token_required
async def create_provider(current_user):
    """Create a new provider in a group. Root only."""
    data = await request.get_json()

    group_id = data.get('group_id')
    if not group_id:
        return jsonify({'detail': 'group_id is required'}), 400

    async with get_db_session() as session:
        # Permission: requires provider.manage (default: root only)
        user_role = await _get_role(group_id, current_user.id, session=session)
        if not await check_permission(user_role, 'provider.manage', session=session):
            return jsonify({'detail': 'Provider management is disabled for this group'}), 403

        # Verify group exists
        result = await session.execute(select(Group).where(Group.id == group_id))
        group = result.scalars().first()
        if not group:
            return jsonify({'detail': 'Group not found'}), 404

        # Check for duplicate name within the same group
        name = data.get('name')
        result = await session.execute(
            select(Provider).where(
                Provider.name == name,
                Provider.group_id == group_id
            )
        )
        existing = result.scalars().first()
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
        session.add(provider)
        await session.flush()  # Get provider.id without committing

        # Auto-create ApiToken for TencentVOD providers
        await _maybe_create_tencentvod_api_token(provider)

        await session.commit()
        provider = await session.get(Provider, provider.id, options=[selectinload(Provider.models)])

        return jsonify(provider.to_dict()), 201


@providers_bp.route('/providers/<int:provider_id>', methods=['GET'])
@token_required
async def get_provider(current_user, provider_id):
    """Get a specific provider."""
    async with get_db_session() as session:
        provider = await session.get(Provider, provider_id, options=[selectinload(Provider.models)])
        if not provider:
            return jsonify({'detail': 'Provider not found'}), 404
        return jsonify(provider.to_dict())


@providers_bp.route('/providers/<int:provider_id>', methods=['PUT'])
@token_required
@require_provider_permission('provider.manage')
async def update_provider(current_user, provider_id):
    """Update a provider. Root only (controlled by provider.manage permission)."""
    async with get_db_session() as session:
        provider = await session.get(Provider, provider_id, options=[selectinload(Provider.models)])
        if not provider:
            return jsonify({'detail': 'Provider not found'}), 404

        data = await request.get_json()
        if 'name' in data and data['name'] != provider.name:
            # Check for duplicate name within the same group
            result = await session.execute(
                select(Provider).where(
                    Provider.name == data['name'],
                    Provider.group_id == provider.group_id,
                    Provider.id != provider_id
                )
            )
            existing = result.scalars().first()
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
        await _maybe_create_tencentvod_api_token(provider)

        await session.commit()
        await session.refresh(provider)

        return jsonify(provider.to_dict())


@providers_bp.route('/providers/<int:provider_id>/reveal-key', methods=['GET'])
@token_required
@require_provider_permission('provider.manage')
async def reveal_provider_key(current_user, provider_id):
    """Return the full (unmasked) api_key for a provider. Requires provider.manage."""
    async with get_db_session() as session:
        provider = await session.get(Provider, provider_id, options=[selectinload(Provider.models)])
        if not provider:
            return jsonify({'detail': 'Provider not found'}), 404
        return jsonify({'api_key': provider.api_key or ''})


@providers_bp.route('/providers/<int:provider_id>', methods=['DELETE'])
@token_required
@require_provider_permission('provider.manage')
async def delete_provider(current_user, provider_id):
    """Delete a provider. Root only (controlled by provider.manage permission)."""
    async with get_db_session() as session:
        provider = await session.get(Provider, provider_id, options=[selectinload(Provider.models)])
        if not provider:
            return jsonify({'detail': 'Provider not found'}), 404

        await session.delete(provider)
        await session.commit()

        return '', 204


# ============== Model Endpoints ==============

@providers_bp.route('/models/', methods=['GET'])
@token_required
async def list_models(current_user):
    """List all models."""
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 100, type=int)
    async with get_db_session() as session:
        result = await session.execute(select(Model).options(selectinload(Model.provider)).offset(skip).limit(limit))
        models = result.scalars().all()
        return jsonify([m.to_dict() for m in models])


@providers_bp.route('/models/', methods=['POST'])
@token_required
async def create_model(current_user):
    """Create a new model. Root only."""
    data = await request.get_json()

    async with get_db_session() as session:
        # Resolve group_id from provider_id for permission check
        provider_id = data.get('provider_id')
        if provider_id:
            result = await session.execute(select(Provider).where(Provider.id == provider_id))
            provider = result.scalars().first()
            if provider:
                group_id = provider.group_id
                user_role = await _get_role(group_id, current_user.id, session=session)
                if not await check_permission(user_role, 'provider.manage', session=session):
                    return jsonify({'detail': 'Model management is disabled for this group'}), 403

        # Parse retirement_time if provided as ISO string
        retirement_time = None
        if data.get('retirement_time'):
            try:
                rt_dt = datetime.fromisoformat(data['retirement_time'].replace('Z', '+00:00'))
                if rt_dt.tzinfo is not None:
                    rt_dt = rt_dt.astimezone(timezone.utc).replace(tzinfo=None)
                retirement_time = rt_dt
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
        session.add(model)
        await session.commit()
        await session.refresh(model)

        return jsonify(model.to_dict()), 201


@providers_bp.route('/models/<int:model_id>', methods=['PUT'])
@token_required
async def update_model(current_user, model_id):
    """Update a model.

    Root can update all fields (requires root.provider.manage).
    Admin can only update priority and traffic_ratio.
    Member cannot update anything.
    """
    async with get_db_session() as session:
        result = await session.execute(select(Model).options(selectinload(Model.provider)).where(Model.id == model_id))
        model = result.scalars().first()
        if not model:
            return jsonify({'detail': 'Model not found'}), 404

        # Resolve group_id from model's provider
        group_id = model.provider.group_id if model.provider else None
        if not group_id or not await _is_member(group_id, current_user.id, session=session):
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

        is_root = await _is_root(group_id, current_user.id, session=session)
        is_admin = await _is_admin_or_above_inner(group_id, current_user.id, session=session)

        if is_root:
            user_role = await _get_role(group_id, current_user.id, session=session)
            if not await check_permission(user_role, 'provider.manage', session=session):
                return jsonify({'detail': 'Model management is disabled for this group'}), 403
            allowed_fields = all_fields
        elif is_admin:
            user_role = await _get_role(group_id, current_user.id, session=session)
            if not await check_permission(user_role, 'model.priority', session=session) and not await check_permission(user_role, 'model.traffic_ratio', session=session):
                return jsonify({'detail': 'Model priority and traffic ratio management is disabled for this group'}), 403
            allowed_fields = set()
            if await check_permission(user_role, 'model.priority', session=session):
                allowed_fields.add('priority')
            if await check_permission(user_role, 'model.traffic_ratio', session=session):
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
                    rt_dt = datetime.fromisoformat(rt.replace('Z', '+00:00'))
                    if rt_dt.tzinfo is not None:
                        rt_dt = rt_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    model.retirement_time = rt_dt
                except (ValueError, AttributeError):
                    return jsonify({'detail': 'Invalid retirement_time format. Use ISO 8601 (e.g. 2025-01-01T00:00:00)'}), 400
            else:
                model.retirement_time = None

        if not model.currency:
            model.currency = 'USD'

        await session.commit()
        await session.refresh(model)

        return jsonify(model.to_dict())


@providers_bp.route('/models/<int:model_id>', methods=['DELETE'])
@token_required
async def delete_model(current_user, model_id):
    """Delete a model. Root only (requires root.provider.manage)."""
    async with get_db_session() as session:
        result = await session.execute(select(Model).options(selectinload(Model.provider)).where(Model.id == model_id))
        model = result.scalars().first()
        if not model:
            return jsonify({'detail': 'Model not found'}), 404

        # Resolve group_id from model's provider
        group_id = model.provider.group_id if model.provider else None
        if not group_id or not await _is_member(group_id, current_user.id, session=session):
            return jsonify({'detail': 'You do not have access to this model'}), 403

        user_role = await _get_role(group_id, current_user.id, session=session)
        if not await check_permission(user_role, 'provider.manage', session=session):
            return jsonify({'detail': 'Model management is disabled for this group'}), 403

        await session.delete(model)
        await session.commit()

        return '', 204


# ============== Rate Limit Status API ==============

@providers_bp.route('/providers/rate-limits', methods=['GET'])
@token_required
async def get_all_rate_limits(current_user):
    """Get rate limit status for all models across all groups the user has access to."""
    from app.rate_limiter import get_async_rate_limiter

    limiter = get_async_rate_limiter()
    if limiter is None:
        return jsonify({'models': [], 'note': 'Rate limiter not initialized (in-memory mode)'})

    async with get_db_session() as session:
        result = await session.execute(
            select(Model).options(selectinload(Model.provider)).where(
                Model.is_active == True,
                (Model.rpm.isnot(None)) | (Model.tpm.isnot(None))
            )
        )
        models = result.scalars().all()

        result_list = []
        for model in models:
            status = await limiter.get_status(model.id, model.provider.group_id)
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
                result_list.append(status)

        return jsonify({'models': result_list})


@providers_bp.route('/providers/rate-limits/<int:model_id>', methods=['GET'])
@token_required
async def get_model_rate_limit(current_user, model_id):
    """Get rate limit status for a specific model."""
    from app.rate_limiter import get_async_rate_limiter

    async with get_db_session() as session:
        result = await session.execute(select(Model).options(selectinload(Model.provider)).where(Model.id == model_id))
        model = result.scalars().first()
        if not model:
            return jsonify({'detail': 'Model not found'}), 404

        limiter = get_async_rate_limiter()
        if limiter is None:
            return jsonify({'model_id': model.id, 'model_name': model.name,
                           'rpm': model.rpm, 'tpm': model.tpm,
                           'note': 'Rate limiter not initialized (in-memory mode)'})

        status = await limiter.get_status(model.id, model.provider.group_id)
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
    async with get_db_session() as session:
        result = await session.execute(select(Workspace).order_by(Workspace.id))
        workspaces = result.scalars().all()
        return jsonify([ws.to_dict() for ws in workspaces])


@providers_bp.route('/workspaces/<int:workspace_id>/users', methods=['GET'])
@token_required
async def list_workspace_users(current_user, workspace_id):
    """List users in a workspace (members of any group within the workspace). Supports ?search= query."""
    from app.models import Workspace, User, UserGroup, Group as GroupModel

    async with get_db_session() as session:
        result = await session.execute(select(Workspace).where(Workspace.id == workspace_id))
        ws = result.scalars().first()
        if not ws:
            return jsonify({'detail': 'Workspace not found'}), 404

        search = request.args.get('search', '').strip()

        stmt = (
            select(User)
            .join(UserGroup, UserGroup.user_id == User.id)
            .join(GroupModel, GroupModel.id == UserGroup.group_id)
            .where(GroupModel.workspace_id == workspace_id)
            .distinct()
        )

        if search:
            pattern = f'%{search}%'
            stmt = stmt.where(
                (User.username.ilike(pattern)) | (User.email.ilike(pattern))
            )

        stmt = stmt.limit(20)
        result = await session.execute(stmt)
        users = result.scalars().all()
        return jsonify([{'id': u.id, 'username': u.username, 'email': u.email} for u in users])


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits', methods=['GET'])
@token_required
async def get_workspace_rate_limits(current_user, workspace_id):
    """List all workspace-level rate limit configurations and their live status."""
    from app.rate_limiter import get_async_rate_limiter
    from app.models import Workspace, WorkspaceRateLimit, Model as ModelModel, Provider as ProviderModel, Group as GroupModel

    async with get_db_session() as session:
        result = await session.execute(select(Workspace).where(Workspace.id == workspace_id))
        ws = result.scalars().first()
        if not ws:
           return jsonify({'detail': 'Workspace not found'}), 404

        result = await session.execute(
           select(WorkspaceRateLimit).options(selectinload(WorkspaceRateLimit.provider)).where(
               WorkspaceRateLimit.workspace_id == workspace_id
           )
        )
        limits = result.scalars().all()

        limiter = get_async_rate_limiter()

        # Collect all model names for per-provider lookup
        model_names = list(set(rl.model_name for rl in limits))

        # Find group-level models matching these model names (alias or name)
        # to show per-provider breakdown
        provider_models = {}  # model_name -> [{provider_name, group_name, ...}]
        if model_names:
            result = await session.execute(
                select(ModelModel).options(
                    selectinload(ModelModel.provider).selectinload(ProviderModel.group)
                ).join(ProviderModel).join(GroupModel).where(
                    ModelModel.is_active == True,
                    ProviderModel.is_active == True,
                    (ModelModel.name.in_(model_names)) | (ModelModel.alias.in_(model_names)),
                )
            )
            matching_models = result.scalars().all()
            for m in matching_models:
                key = m.alias or m.name
                if key not in provider_models:
                    provider_models[key] = []
                # Get group-level status for this specific model
                grp_status = await limiter.get_status(m.id, m.provider.group_id)
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

        # Subquery for group IDs in this workspace
        group_ids_subq = select(GroupModel.id).where(GroupModel.workspace_id == workspace_id).subquery()

        result = await session.execute(
            select(ApiKey).options(selectinload(ApiKey.group)).where(
                (ApiKey.workspace_id == workspace_id) |
                (ApiKey.group_id.in_(group_ids_subq))
            )
        )
        ws_api_keys = result.scalars().all()
        apikey_info_map = {}  # preview_prefix -> {name, group_name}
        for ak in ws_api_keys:
            if ak.key:
                preview = ak.key[:8] + '...'
                apikey_info_map[preview] = {
                    'name': ak.name,
                    'group_name': ak.group.name if ak.group else None,
                }

        result_list = []
        for rl in limits:
            status = await limiter.get_ws_status(
                workspace_id, rl.model_name,
                ws_rpm_limit=rl.rpm, ws_tpm_limit=rl.tpm,
                provider_type=rl.provider_type, provider_id=rl.provider_id,
            )
            # Add historical usage (1m, 5m, 10m)
            history = await limiter.get_ws_history(
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
            result_list.append(status)

        return jsonify({'workspace': ws.to_dict(), 'rate_limits': result_list})


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits', methods=['POST'])
@token_required
async def create_workspace_rate_limit(current_user, workspace_id):
    """Create a new workspace-level rate limit for a model + provider_type (+ optional provider_id)."""
    from app.models import Workspace, WorkspaceRateLimit

    async with get_db_session() as session:
        result = await session.execute(select(Workspace).where(Workspace.id == workspace_id))
        ws = result.scalars().first()
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
        stmt = select(WorkspaceRateLimit).where(
            WorkspaceRateLimit.workspace_id == workspace_id,
            WorkspaceRateLimit.model_name == model_name,
            WorkspaceRateLimit.provider_type == provider_type,
        )
        if provider_id is not None:
            stmt = stmt.where(WorkspaceRateLimit.provider_id == provider_id)
        else:
            stmt = stmt.where(WorkspaceRateLimit.provider_id.is_(None))

        result = await session.execute(stmt)
        existing = result.scalars().first()
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
        session.add(rl)
        await session.commit()
        return jsonify(rl.to_dict()), 201


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits/<int:rate_limit_id>', methods=['PUT'])
@token_required
async def update_workspace_rate_limit(current_user, workspace_id, rate_limit_id):
    """Update a workspace-level rate limit."""
    from app.models import WorkspaceRateLimit

    async with get_db_session() as session:
        result = await session.execute(
            select(WorkspaceRateLimit).where(
                WorkspaceRateLimit.id == rate_limit_id,
                WorkspaceRateLimit.workspace_id == workspace_id,
            )
        )
        rl = result.scalars().first()
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

        await session.commit()
        return jsonify(rl.to_dict())


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits/<int:rate_limit_id>', methods=['DELETE'])
@token_required
async def delete_workspace_rate_limit(current_user, workspace_id, rate_limit_id):
    """Delete a workspace-level rate limit."""
    from app.models import WorkspaceRateLimit

    async with get_db_session() as session:
        result = await session.execute(
            select(WorkspaceRateLimit).where(
                WorkspaceRateLimit.id == rate_limit_id,
                WorkspaceRateLimit.workspace_id == workspace_id,
            )
        )
        rl = result.scalars().first()
        if not rl:
            return jsonify({'detail': 'Rate limit not found'}), 404

        await session.delete(rl)
        await session.commit()
        return '', 204


@providers_bp.route('/workspaces/<int:workspace_id>/rate-limits/status', methods=['GET'])
@token_required
async def get_workspace_rate_limit_status(current_user, workspace_id):
    """Get live rate limit status for a specific model in a workspace."""
    from app.rate_limiter import get_async_rate_limiter
    from app.models import Workspace, WorkspaceRateLimit

    async with get_db_session() as session:
        result = await session.execute(select(Workspace).where(Workspace.id == workspace_id))
        ws = result.scalars().first()
        if not ws:
            return jsonify({'detail': 'Workspace not found'}), 404

        model_name = request.args.get('model_name')
        if not model_name:
            return jsonify({'detail': 'model_name query parameter is required'}), 400

        result = await session.execute(
            select(WorkspaceRateLimit).where(
                WorkspaceRateLimit.workspace_id == workspace_id,
                WorkspaceRateLimit.model_name == model_name,
            )
        )
        rl = result.scalars().first()

        limiter = get_async_rate_limiter()
        ws_rpm = rl.rpm if rl else None
        ws_tpm = rl.tpm if rl else None
        status = await limiter.get_ws_status(workspace_id, model_name, ws_rpm_limit=ws_rpm, ws_tpm_limit=ws_tpm)
        status['workspace_id'] = workspace_id
        status['workspace_name'] = ws.name
        return jsonify(status)