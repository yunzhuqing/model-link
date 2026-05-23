"""
User service — cache-first user lookups and cache invalidation.

Keeps caching logic out of the ORM models layer.
"""
from app.models import User, Group


# ── Cached model proxies (lightweight, DB-independent) ────────────────────

class CachedUserGroup:
    """Lightweight proxy for UserGroup association row."""
    __slots__ = ('user_id', 'group_id', 'role')

    def __init__(self, user_id: int, group_id: int, role: str):
        self.user_id = user_id
        self.group_id = group_id
        self.role = role


class CachedGroup:
    """Lightweight proxy for Group; lazy-loads ORM on first full-data access."""

    def __init__(self, id: int, name: str, description: str = None):
        self.id = id
        self.name = name
        self.description = description
        self._orm = None

    async def _get_orm(self, session=None):
        if self._orm is None:
            if session is None:
                from flask import g
                session = g.db_session
            self._orm = await session.get(Group, self.id)
        return self._orm

    async def get_users(self, session=None):
        orm = await self._get_orm(session=session)
        return orm.users if orm else []

    async def get_api_keys(self, session=None):
        orm = await self._get_orm(session=session)
        return orm.api_keys if orm else []

    async def to_dict(self, session=None):
        orm = await self._get_orm(session=session)
        if orm:
            return orm.to_dict()
        return {'id': self.id, 'name': self.name, 'description': self.description}

    def __eq__(self, other):
        if hasattr(other, 'id'):
            return self.id == other.id
        return NotImplemented

    def __hash__(self):
        return hash(self.id)


class CachedUser:
    """Lightweight proxy for User; eager-loads groups/roles from cache dict."""

    def __init__(self, id: int, username: str, email: str = None,
                 groups: list = None, group_associations: list = None):
        self.id = id
        self.username = username
        self.email = email
        self.groups = groups or []
        self.group_associations = group_associations or []
        self.hashed_password = None  # never cached

    def to_dict(self):
        return {'id': self.id, 'username': self.username, 'email': self.email}

    def __eq__(self, other):
        if hasattr(other, 'id'):
            return self.id == other.id
        return NotImplemented

    def __hash__(self):
        return hash(self.id)


# ── Serialization helpers ─────────────────────────────────────────────────

def user_to_cache_dict(user: User) -> dict:
    """Build a cache-friendly dict from a User ORM object."""
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'groups': [
            {'id': g.id, 'name': g.name, 'description': g.description}
            for g in user.groups
        ],
        'group_associations': [
            {'user_id': ug.user_id, 'group_id': ug.group_id, 'role': ug.role}
            for ug in user.group_associations
        ],
    }


def cached_user_from_dict(cached: dict) -> CachedUser:
    """Build a CachedUser from a dict previously returned by user_to_cache_dict()."""
    return CachedUser(
        id=cached['id'],
        username=cached['username'],
        email=cached.get('email'),
        groups=[CachedGroup(**g) for g in cached.get('groups', [])],
        group_associations=[CachedUserGroup(**ug) for ug in cached.get('group_associations', [])],
    )


# ── Public API ────────────────────────────────────────────────────────────

async def get_user_by_id(user_id: int, session=None) -> CachedUser | None:
    """Get user by ID with cache-first lookup. Returns CachedUser or None."""
    try:
        from app.cache import get_async_cache
        cached = await get_async_cache().get_user_info(user_id)
        if cached:
            return cached_user_from_dict(cached)
    except Exception:
        pass

    if session is None:
        from flask import g
        session = g.db_session
    orm_user = await session.get(User, user_id)
    if orm_user is None:
        return None

    cache_dict = user_to_cache_dict(orm_user)
    try:
        from app.cache import get_async_cache
        await get_async_cache().set_user_info(user_id, cache_dict)
    except Exception:
        pass

    return cached_user_from_dict(cache_dict)


async def invalidate_user_cache(user_id: int) -> None:
    """Remove cached user info. Safe to call even if cache is unavailable."""
    try:
        from app.cache import get_async_cache
        await get_async_cache().invalidate_user_info(user_id)
    except Exception:
        pass