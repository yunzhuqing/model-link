"""
User service — cache-first user lookups and cache invalidation.

Keeps caching logic out of the ORM models layer.
"""
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import User, Group, ApiKey, UserGroup


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

    async def get_users(self, session=None):
        """Return list of Users in this group, eager-loaded via the given session."""
        if session is None:
            from app import get_db_session
            async with get_db_session() as _s:
                return await self.get_users(session=_s)
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.users))
            .where(Group.id == self.id)
        )
        group = result.scalars().first()
        return list(group.users) if group else []

    async def get_api_keys(self, session=None):
        """Return list of ApiKeys in this group, eager-loaded via the given session.

        Eager-loads the relationships that ApiKey.to_dict_with_group() touches
        (.group, .user, .policies) so callers can serialize without triggering
        additional lazy loads outside the session.
        """
        if session is None:
            from app import get_db_session
            async with get_db_session() as _s:
                return await self.get_api_keys(session=_s)
        result = await session.execute(
            select(ApiKey)
            .options(
                selectinload(ApiKey.group),
                selectinload(ApiKey.user),
                selectinload(ApiKey.policies),
            )
            .where(ApiKey.group_id == self.id)
        )
        return list(result.scalars().all())

    async def to_dict(self, session=None):
        if session is None:
            from app import get_db_session
            async with get_db_session() as _s:
                return await self.to_dict(session=_s)
        # Group.to_dict() walks user_associations (+ug.user), api_keys (+k.user),
        # and providers. Eager-load everything it touches so it can serialize
        # without firing async-incompatible lazy loads.
        result = await session.execute(
            select(Group)
            .options(
                selectinload(Group.user_associations).selectinload(UserGroup.user),
                selectinload(Group.api_keys).selectinload(ApiKey.user),
                selectinload(Group.providers),
            )
            .where(Group.id == self.id)
        )
        orm = result.scalars().first()
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
        from app import get_db_session
        async with get_db_session() as _s:
            return await get_user_by_id(user_id, session=_s)
    # Eager-load groups + group_associations so user_to_cache_dict() can walk
    # them without triggering lazy loads (which would crash under async).
    result = await session.execute(
        select(User)
        .options(
            selectinload(User.groups),
            selectinload(User.group_associations),
        )
        .where(User.id == user_id)
    )
    orm_user = result.scalars().first()
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