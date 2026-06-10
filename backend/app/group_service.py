"""
Group service — cache-first group queries, CRUD, and cache invalidation.

Cache strategy:
  - Cache key: ``group:{group_id}`` → group dict (id, name, monitoring_config)
  - On read: check cache first, fall back to DB + populate cache
  - On create / update / delete: invalidate cache entry
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models import Group, UserGroup, ApiKey

logger = logging.getLogger("group_service")

_GROUP_CACHE_PREFIX = "group:"
_GROUP_CACHE_TTL = 300


def _require_session(session):
    """All callers must pass an explicit session."""
    if session is None:
        raise RuntimeError(
            "group_service: session is required. "
            "Open one via `async with get_db_session() as s:` and pass it explicitly."
        )
    return session


def _cache_key(group_id: int) -> str:
    return f"{_GROUP_CACHE_PREFIX}{group_id}"


def _validate_monitoring_config_item(config: dict) -> str | None:
    """Validate a single monitoring config dict. Returns error string or None."""
    if not isinstance(config, dict):
        return "monitoring_config item must be an object"
    tracer_type = config.get("type")
    if not tracer_type:
        return "monitoring_config.type is required"
    if tracer_type == "langfuse":
        if not config.get("public_key"):
            return "monitoring_config.public_key is required for langfuse"
        if not config.get("secret_key"):
            return "monitoring_config.secret_key is required for langfuse"
    else:
        return f"Unknown monitoring type: {tracer_type}"
    return None


def _validate_monitoring_config(config: list | dict | None) -> str | None:
    """Validate monitoring_config. Accepts list, legacy dict, or None."""
    if config is None:
        return None
    if isinstance(config, dict):
        return _validate_monitoring_config_item(config)
    if not isinstance(config, list):
        return "monitoring_config must be a list, object, or null"
    for i, item in enumerate(config):
        err = _validate_monitoring_config_item(item)
        if err:
            return f"monitoring_config[{i}]: {err}"
    return None


async def get_group_config(group_id: int, session=None) -> dict | None:
    """Get group config dict (id, name, monitoring_config), cache-first.

    Used by gateway routes to look up monitoring_config without hitting DB
    on every request.
    """
    from app.cache import get_async_cache
    cache = get_async_cache()
    key = _cache_key(group_id)
    data = await cache._backend.get(key)
    if data is not None:
        return data

    # Cache miss — load from DB
    session = _require_session(session)
    try:
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalars().first()
    except Exception:
        return None
    if group is None:
        return None

    data = {
        "id": group.id,
        "name": group.name,
        "monitoring_config": group.monitoring_config,
    }
    try:
        await cache._backend.set(key, data, _GROUP_CACHE_TTL)
    except Exception as e:
        logger.warning(f"Failed to cache group {group_id}: {e}")
    return data


async def get_group_monitoring_config(group_id: int, session=None) -> list[dict] | None:
    """Return monitoring_config for a group as a list, or None.

    Normalizes legacy single-dict configs to a single-element list.
    """
    config = await get_group_config(group_id, session=session)
    if config is None:
        return None
    mc = config.get("monitoring_config")
    if mc is None:
        return None
    if isinstance(mc, dict):
        return [mc]
    if isinstance(mc, list):
        return mc
    return None


async def get_group_by_id(group_id: int, session=None) -> Group | None:
    """Get Group ORM object from DB with all commonly-walked relationships
    eager-loaded so callers can safely access .users, .user_associations,
    .api_keys, .providers and serialize via .to_dict() without triggering
    async-incompatible lazy loads.
    """
    session = _require_session(session)
    try:
        result = await session.execute(
            select(Group)
            .options(
                selectinload(Group.users),
                selectinload(Group.user_associations).selectinload(UserGroup.user),
                selectinload(Group.api_keys).selectinload(ApiKey.user),
                selectinload(Group.api_keys).selectinload(ApiKey.policies),
                selectinload(Group.providers),
            )
            .where(Group.id == group_id)
        )
        return result.scalars().first()
    except Exception:
        return None


async def invalidate_group_cache(group_id: int) -> None:
    """Remove cached entry for a group."""
    from app.cache import get_async_cache
    try:
        await get_async_cache()._backend.delete(_cache_key(group_id))
    except Exception as e:
        logger.warning(f"Failed to invalidate group cache {group_id}: {e}")


async def create_group(name: str, description: str | None = None, workspace_id: int | None = None, session=None) -> tuple[Group | None, str | None]:
    """Create a new group. Returns (group, error)."""
    session = _require_session(session)
    result = await session.execute(select(Group).where(Group.name == name))
    existing = result.scalars().first()
    if existing:
        return None, "Group with this name already exists"

    group = Group(name=name, description=description, workspace_id=workspace_id)
    session.add(group)
    try:
        await session.flush()
    except Exception as e:
        await session.rollback()
        return None, str(e)

    return group, None


async def update_group(group_id: int, session=None, **kwargs) -> tuple[Group | None, str | None]:
    """Update group fields. Returns (group, error).

    Accepted kwargs: name, description, monitoring_config, tags, workspace_id
    """
    session = _require_session(session)
    group = await get_group_by_id(group_id, session=session)
    if not group:
        return None, "Group not found"

    if "name" in kwargs and kwargs["name"] is not None:
        new_name = kwargs["name"]
        result = await session.execute(
            select(Group).where(
                Group.name == new_name,
                Group.id != group_id,
            )
        )
        existing = result.scalars().first()
        if existing:
            return None, "Group with this name already exists"
        group.name = new_name

    if "description" in kwargs:
        group.description = kwargs["description"]

    if "monitoring_config" in kwargs:
        mc = kwargs["monitoring_config"]
        if mc is None:
            group.monitoring_config = None
        elif isinstance(mc, dict):
            # Legacy single-object config
            mc = [mc]
        elif isinstance(mc, list):
            pass  # keep as-is
        else:
            return None, "monitoring_config must be a list, object, or null"

        if mc is not None:
            # Merge existing secret_key for items that don't provide one
            existing = group.monitoring_config
            if isinstance(existing, dict):
                existing = [existing]
            existing = existing or []
            for i, item in enumerate(mc):
                if not item.get('secret_key') and i < len(existing):
                    old_item = existing[i] if isinstance(existing[i], dict) else {}
                    if old_item.get('secret_key'):
                        item['secret_key'] = old_item['secret_key']

            err = _validate_monitoring_config(mc)
            if err:
                return None, err
            group.monitoring_config = mc

    if "tags" in kwargs:
        group.tags = kwargs["tags"]

    if "workspace_id" in kwargs:
        group.workspace_id = kwargs["workspace_id"]

    await invalidate_group_cache(group_id)
    return group, None


async def delete_group(group_id: int, session=None) -> tuple[bool, str | None]:
    """Delete a group. Returns (success, error)."""
    session = _require_session(session)
    group = await get_group_by_id(group_id, session=session)
    if not group:
        return False, "Group not found"

    await session.delete(group)
    await invalidate_group_cache(group_id)
    return True, None
