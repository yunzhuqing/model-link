"""
Group service — cache-first group queries, CRUD, and cache invalidation.

Cache strategy:
  - Cache key: ``group:{group_id}`` → group dict (id, name, monitoring_config)
  - On read: check cache first, fall back to DB + populate cache
  - On create / update / delete: invalidate cache entry
"""
import logging
from typing import Any, Dict, Optional

from app import db
from app.models import Group

logger = logging.getLogger("group_service")

_GROUP_CACHE_PREFIX = "group:"
_GROUP_CACHE_TTL = 300


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


def get_group_config(group_id: int) -> dict | None:
    """Get group config dict (id, name, monitoring_config), cache-first.

    Used by gateway routes to look up monitoring_config without hitting DB
    on every request.
    """
    from app.cache import get_cache
    cache = get_cache()
    key = _cache_key(group_id)
    data = cache._backend.get(key)
    if data is not None:
        return data

    # Cache miss — load from DB
    try:
        group = db.session.query(Group).filter(Group.id == group_id).first()
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
        cache._backend.set(key, data, _GROUP_CACHE_TTL)
    except Exception as e:
        logger.warning(f"Failed to cache group {group_id}: {e}")
    return data


def get_group_monitoring_config(group_id: int) -> list[dict] | None:
    """Return monitoring_config for a group as a list, or None.

    Normalizes legacy single-dict configs to a single-element list.
    """
    config = get_group_config(group_id)
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


def get_group_by_id(group_id: int) -> Group | None:
    """Get Group ORM object directly from DB (for mutations needing relationships)."""
    try:
        return db.session.query(Group).filter(Group.id == group_id).first()
    except Exception:
        return None


def invalidate_group_cache(group_id: int) -> None:
    """Remove cached entry for a group."""
    from app.cache import get_cache
    try:
        get_cache()._backend.delete(_cache_key(group_id))
    except Exception as e:
        logger.warning(f"Failed to invalidate group cache {group_id}: {e}")


def create_group(name: str, description: str | None = None, workspace_id: int | None = None) -> tuple[Group | None, str | None]:
    """Create a new group. Returns (group, error)."""
    existing = db.session.query(Group).filter(Group.name == name).first()
    if existing:
        return None, "Group with this name already exists"

    group = Group(name=name, description=description, workspace_id=workspace_id)
    db.session.add(group)
    try:
        db.session.flush()
    except Exception as e:
        db.session.rollback()
        return None, str(e)

    return group, None


def update_group(group_id: int, **kwargs) -> tuple[Group | None, str | None]:
    """Update group fields. Returns (group, error).

    Accepted kwargs: name, description, monitoring_config, tags, workspace_id
    """
    group = get_group_by_id(group_id)
    if not group:
        return None, "Group not found"

    if "name" in kwargs and kwargs["name"] is not None:
        new_name = kwargs["name"]
        existing = db.session.query(Group).filter(
            Group.name == new_name,
            Group.id != group_id,
        ).first()
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

    invalidate_group_cache(group_id)
    return group, None


def delete_group(group_id: int) -> tuple[bool, str | None]:
    """Delete a group. Returns (success, error)."""
    group = get_group_by_id(group_id)
    if not group:
        return False, "Group not found"

    db.session.delete(group)
    invalidate_group_cache(group_id)
    return True, None
