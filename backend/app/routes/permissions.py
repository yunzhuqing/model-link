"""
System-level permission management routes.

Root users can create, edit, delete and toggle system-level permission points.
Each permission point defines:
  - key:           globally unique identifier (e.g. "provider.manage")
  - label:         human-readable display name
  - description:   optional explanation
  - allowed_roles: JSON list of roles that are permitted
  - is_enabled:    master toggle

Permissions are system-global — they apply uniformly across all groups.
"""

import functools
from quart import Blueprint, request, jsonify
from sqlalchemy import select, func as sa_func

from app import get_db_session
from app.models import (
    Group,
    UserGroup,
    Permission,
    seed_default_permissions,
    check_permission,
    ApiKey,
    Provider,
)
from app.routes.users import token_required

permissions_bp = Blueprint("permissions", __name__)


# ── Helpers ────────────────────────────────────────────────────────────
# All helpers accept an optional ``session`` parameter. When omitted they open
# their own short-lived session so callers in decorators don't have to plumb a
# session through.

async def _get_role(group_id: int, user_id: int, session=None) -> str | None:
    if session is None:
        async with get_db_session() as _s:
            return await _get_role(group_id, user_id, session=_s)
    result = await session.execute(
        select(UserGroup).where(
            UserGroup.group_id == group_id,
            UserGroup.user_id == user_id,
        )
    )
    ug = result.scalars().first()
    return ug.role if ug else None


async def _is_root_in_any_group(user_id: int, session=None) -> bool:
    """Check if the user is 'root' in at least one group."""
    if session is None:
        async with get_db_session() as _s:
            return await _is_root_in_any_group(user_id, session=_s)
    result = await session.execute(
        select(sa_func.count()).select_from(UserGroup).where(
            UserGroup.user_id == user_id,
            UserGroup.role == "root",
        )
    )
    count = result.scalar()
    return count > 0


async def _is_member(group_id: int, user_id: int, session=None) -> bool:
    return await _get_role(group_id, user_id, session=session) is not None


async def _is_root(group_id: int, user_id: int, session=None) -> bool:
    """Check if user is root in a specific group. (Used by providers.py)"""
    return await _get_role(group_id, user_id, session=session) == "root"


async def _is_admin_or_above(group_id: int, user_id: int, session=None) -> bool:
    """Check if user is admin or root in the given group."""
    role = await _get_role(group_id, user_id, session=session)
    return role in ('admin', 'root')


def require_api_key_access(f):
    """Decorator: verify the current user can access the API key (owner or admin+ in group).

    Usage::

        @apikeys_bp.route('/apikeys/<int:api_key_id>/policies', methods=['GET'])
        @token_required
        @require_api_key_access
        async def list_policies(current_user, api_key_id):
            ...
    """
    @functools.wraps(f)
    async def wrapper(current_user, api_key_id, *args, **kwargs):
        async with get_db_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.id == api_key_id)
            )
            api_key = result.scalars().first()
            if not api_key:
                return jsonify({"detail": "API key not found"}), 404

            if api_key.user_id != current_user.id and (
                not api_key.group_id or not await _is_admin_or_above(api_key.group_id, current_user.id, session=session)
            ):
                return jsonify({"detail": "Access denied"}), 403

        return await f(current_user, api_key_id, *args, **kwargs)
    return wrapper


async def _is_admin_or_above_inner(group_id: int, user_id: int, session=None) -> bool:
    """Check if user is admin or root in a specific group. (Used by providers.py)"""
    role = await _get_role(group_id, user_id, session=session)
    return role in ("admin", "root")


# ── Root check helper ──────────────────────────────────────────────────

async def _require_root(current_user):
    if not await _is_root_in_any_group(current_user.id):
        return jsonify({"detail": "Only root members can manage system permissions"}), 403
    return None


# ── Backward-compatible wrappers for existing route modules ────────────
# Old signatures accepted (current_user, group_id); new helpers are global.
# These wrappers bridge the gap so existing route code continues to compile.

async def _get_user_role_in_group(current_user, group_id: int, session=None) -> str | None:
    return await _get_role(group_id, current_user.id, session=session)


async def _is_root_in_group(current_user, group_id: int, session=None) -> bool:
    return await _get_role(group_id, current_user.id, session=session) == "root"


async def _is_member_of_group(current_user, group_id: int, session=None) -> bool:
    return await _is_member(group_id, current_user.id, session=session)


async def _is_admin_or_above(current_user, group_id: int, session=None) -> bool:
    """Return True if user is admin or root in the group."""
    role = await _get_role(group_id, current_user.id, session=session)
    return role in ("admin", "root")


# ── Bridge for old 2-arg check_permission calls ────────────────────────
async def check_group_permission(current_user, group_id: int, permission_key: str, session=None) -> bool:
    """Backward-compatible wrapper: derive role from current_user + group_id,
    then call check_permission(role, permission_key)."""
    role = await _get_role(group_id, current_user.id, session=session)
    if role is None:
        return False
    return await check_permission(role, permission_key, session=session)


# ── Permission Decorators ──────────────────────────────────────────────
# These decorators encapsulate the common pattern:
#   1. Look up group_id (from URL param, API key, or provider)
#   2. Verify the user is a member of that group
#   3. Check if the user has the required system-level permission
#   4. Return 403 JSON if any check fails

def require_permission(permission_key: str):
    """Decorator for routes that have a ``group_id`` URL parameter.

    Verifies the current user is a member of the group, resolves their role,
    and checks whether the given system-level permission is enabled for that role.

    Usage::

        @apikeys_bp.route('/groups/<int:group_id>', methods=['PUT'])
        @token_required
        @require_permission('group.manage')
        async def update_group(current_user, group_id):
            ...
    """
    def decorator(f):
        @functools.wraps(f)
        async def wrapper(current_user, group_id, *args, **kwargs):
            async with get_db_session() as session:
                # Verify group exists and user is a member
                if not await _is_member(group_id, current_user.id, session=session):
                    return jsonify({"detail": "You are not a member of this group"}), 403

                # Resolve role and check system-level permission
                role = await _get_role(group_id, current_user.id, session=session)
                if not await check_permission(role, permission_key, session=session):
                    return jsonify({"detail": f"Permission '{permission_key}' is not granted for your role"}), 403

            return await f(current_user, group_id, *args, **kwargs)
        return wrapper
    return decorator


def require_apikey_permission(permission_key: str):
    """Decorator for routes that have an ``api_key_id`` URL parameter.

    Auto-resolves the group via the API key, verifies membership, and checks
    the given system-level permission.

    Usage::

        @apikeys_bp.route('/apikeys/<int:api_key_id>', methods=['DELETE'])
        @token_required
        @require_apikey_permission('apikey.manage')
        async def delete_api_key(current_user, api_key_id):
            ...
    """
    def decorator(f):
        @functools.wraps(f)
        async def wrapper(current_user, api_key_id, *args, **kwargs):
            async with get_db_session() as session:
                result = await session.execute(
                    select(ApiKey).where(ApiKey.id == api_key_id)
                )
                api_key = result.scalars().first()
                if not api_key:
                    return jsonify({"detail": "API key not found"}), 404

                group_id = api_key.group_id

                # Verify membership
                if not await _is_member(group_id, current_user.id, session=session):
                    return jsonify({"detail": "You do not have access to this API key"}), 403

                # Check system-level permission
                role = await _get_role(group_id, current_user.id, session=session)
                if not await check_permission(role, permission_key, session=session):
                    return jsonify({"detail": f"Permission '{permission_key}' is not granted for your role"}), 403

            return await f(current_user, api_key_id, *args, **kwargs)
        return wrapper
    return decorator


def require_provider_permission(permission_key: str):
    """Decorator for routes that have a ``provider_id`` URL parameter.

    Auto-resolves the group via the provider, verifies membership, and checks
    the given system-level permission.

    Usage::

        @providers_bp.route('/providers/<int:provider_id>', methods=['PUT'])
        @token_required
        @require_provider_permission('provider.manage')
        async def update_provider(current_user, provider_id):
            ...
    """
    def decorator(f):
        @functools.wraps(f)
        async def wrapper(current_user, provider_id, *args, **kwargs):
            async with get_db_session() as session:
                result = await session.execute(
                    select(Provider).where(Provider.id == provider_id)
                )
                provider = result.scalars().first()
                if not provider:
                    return jsonify({"detail": "Provider not found"}), 404

                group_id = provider.group_id

                # Verify membership
                if not await _is_member(group_id, current_user.id, session=session):
                    return jsonify({"detail": "You do not have access to this provider"}), 403

                # Check system-level permission
                role = await _get_role(group_id, current_user.id, session=session)
                if not await check_permission(role, permission_key, session=session):
                    return jsonify({"detail": f"Permission '{permission_key}' is not granted for your role"}), 403

            return await f(current_user, provider_id, *args, **kwargs)
        return wrapper
    return decorator


def require_template_manage():
    """Decorator for model-template routes that are not group-scoped.

    Verifies the user is root in at least one group AND that the
    system-level ``template.manage`` permission is enabled.

    Usage::

        @model_templates_bp.route('/model-templates/', methods=['POST'])
        @token_required
        @require_template_manage()
        async def create_model_template(current_user):
            ...
    """
    def decorator(f):
        @functools.wraps(f)
        async def wrapper(current_user, *args, **kwargs):
            async with get_db_session() as session:
                if not await _is_root_in_any_group(current_user.id, session=session):
                    return jsonify({"detail": "Only root members can manage templates"}), 403

                if not await check_permission("root", "template.manage", session=session):
                    return jsonify({"detail": "Template management is disabled"}), 403

            return await f(current_user, *args, **kwargs)
        return wrapper
    return decorator


def require_global_permission(permission_key: str):
    """Decorator for routes that are not group-scoped (e.g. create group).

    Resolves the user's best role across all groups (root > admin) and
    checks the given system-level permission.

    Usage::

        @apikeys_bp.route('/groups/', methods=['POST'])
        @token_required
        @require_global_permission('group.manage')
        async def create_group(current_user):
            ...
    """
    def decorator(f):
        @functools.wraps(f)
        async def wrapper(current_user, *args, **kwargs):
            best_role = None
            for ug in current_user.group_associations:
                if ug.role == "root":
                    best_role = "root"
                    break
                if ug.role == "admin":
                    best_role = "admin"

            if best_role is None:
                return jsonify({"detail": f"Permission '{permission_key}' is not granted for your role"}), 403

            if not await check_permission(best_role, permission_key):
                return jsonify({"detail": f"Permission '{permission_key}' is not granted for your role"}), 403

            return await f(current_user, *args, **kwargs)
        return wrapper
    return decorator


# ── List all permissions (system-level) ────────────────────────────────

@permissions_bp.route("/permissions", methods=["GET"])
@token_required
async def list_permissions(current_user):
    """List all system-level permission points."""
    async with get_db_session() as session:
        # Auto-seed defaults if none exist
        await seed_default_permissions(session=session)
        await session.commit()

        result = await session.execute(select(Permission).order_by(Permission.key))
        perms = result.scalars().all()
        is_root = await _is_root_in_any_group(current_user.id, session=session)

        return jsonify({
            "permissions": [p.to_dict() for p in perms],
            "is_root": is_root,
        })


# ── Create a new permission ────────────────────────────────────────────

@permissions_bp.route("/permissions", methods=["POST"])
@token_required
async def create_permission(current_user):
    """Create a new system-level permission point. Only root."""
    err = await _require_root(current_user)
    if err:
        return err

    data = await request.get_json()
    key = (data.get("key") or "").strip()
    label = (data.get("label") or "").strip()
    if not key or not label:
        return jsonify({"detail": "key and label are required"}), 400

    async with get_db_session() as session:
        # Check uniqueness
        result = await session.execute(select(Permission).where(Permission.key == key))
        existing = result.scalars().first()
        if existing:
            return jsonify({"detail": f"Permission key '{key}' already exists"}), 409

        perm = Permission(
            key=key,
            label=label,
            description=data.get("description", ""),
            allowed_roles=data.get("allowed_roles", ["root"]),
            is_enabled=data.get("is_enabled", True),
        )
        session.add(perm)
        await session.commit()
        await session.refresh(perm)

        return jsonify(perm.to_dict()), 201


# ── Update a permission ────────────────────────────────────────────────

@permissions_bp.route(
    "/permissions/<permission_key>", methods=["PUT"]
)
@token_required
async def update_permission(current_user, permission_key):
    """Update a permission point (label, description, allowed_roles, is_enabled). Only root."""
    err = await _require_root(current_user)
    if err:
        return err

    async with get_db_session() as session:
        result = await session.execute(select(Permission).where(Permission.key == permission_key))
        perm = result.scalars().first()
        if not perm:
            return jsonify({"detail": "Permission not found"}), 404

        data = await request.get_json()

        if "label" in data:
            label = (data["label"] or "").strip()
            if not label:
                return jsonify({"detail": "label cannot be empty"}), 400
            perm.label = label
        if "description" in data:
            perm.description = data["description"]
        if "allowed_roles" in data:
            roles = data["allowed_roles"]
            if not isinstance(roles, list):
                return jsonify({"detail": "allowed_roles must be a list"}), 400
            perm.allowed_roles = roles
        if "is_enabled" in data:
            if not isinstance(data["is_enabled"], bool):
                return jsonify({"detail": "is_enabled must be a boolean"}), 400
            perm.is_enabled = data["is_enabled"]

        await session.commit()
        await session.refresh(perm)

        return jsonify(perm.to_dict())


# ── Delete a permission ────────────────────────────────────────────────

@permissions_bp.route(
    "/permissions/<permission_key>", methods=["DELETE"]
)
@token_required
async def delete_permission(current_user, permission_key):
    """Delete a system-level permission point. Only root."""
    err = await _require_root(current_user)
    if err:
        return err

    async with get_db_session() as session:
        result = await session.execute(select(Permission).where(Permission.key == permission_key))
        perm = result.scalars().first()
        if not perm:
            return jsonify({"detail": "Permission not found"}), 404

        await session.delete(perm)
        await session.commit()

        return jsonify({"detail": f"Permission '{permission_key}' deleted"})


# ── Get my role in a group (returns permissions for a specific group context) ──

@permissions_bp.route("/permissions/groups/<int:group_id>/my-role", methods=["GET"])
@token_required
async def get_my_role(current_user, group_id):
    """Return the current user's role and effective system-level permissions in the group."""
    async with get_db_session() as session:
        result = await session.execute(select(Group).where(Group.id == group_id))
        group = result.scalars().first()
        if not group:
            return jsonify({"detail": "Group not found"}), 404

        role = await _get_role(group_id, current_user.id, session=session)
        if role is None:
            return jsonify({"detail": "You are not a member of this group"}), 403

        # Build permissions map: key → True/False
        perms_result = await session.execute(select(Permission))
        perms = perms_result.scalars().all()
        perm_map = {}
        for p in perms:
            perm_map[p.key] = await check_permission(role, p.key, session=session)

        return jsonify({
            "group_id": group_id,
            "user_id": current_user.id,
            "role": role,
            "permissions": perm_map,
        })


# ── Get my global permissions (highest role across all groups) ──

@permissions_bp.route("/permissions/my-permissions", methods=["GET"])
@token_required
async def get_my_global_permissions(current_user):
    """Return the current user's permissions based on their highest role across all groups."""
    best_role = None
    for ug in current_user.group_associations:
        if ug.role == "root":
            best_role = "root"
            break
        if ug.role == "admin":
            best_role = "admin"

    if not best_role:
        return jsonify({"permissions": {}, "role": None})

    async with get_db_session() as session:
        result = await session.execute(select(Permission))
        perms = result.scalars().all()
        perm_map = {}
        for p in perms:
            perm_map[p.key] = await check_permission(best_role, p.key, session=session)

        return jsonify({
            "role": best_role,
            "permissions": perm_map,
        })
