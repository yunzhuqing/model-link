"""
User service — cache-first user lookups and cache invalidation.

Keeps caching logic out of the ORM models layer.
"""
from app import db
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

    def _get_orm(self):
        if self._orm is None:
            self._orm = db.session.get(Group, self.id)
        return self._orm

    @property
    def users(self):
        orm = self._get_orm()
        return orm.users if orm else []

    @property
    def api_keys(self):
        orm = self._get_orm()
        return orm.api_keys if orm else []

    def to_dict(self):
        orm = self._get_orm()
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

def get_user_by_id(user_id: int) -> CachedUser | None:
    """Get user by ID with cache-first lookup. Returns CachedUser or None."""
    try:
        from app.cache import get_cache
        cached = get_cache().get_user_info(user_id)
        if cached:
            return cached_user_from_dict(cached)
    except Exception:
        pass

    orm_user = db.session.get(User, user_id)
    if orm_user is None:
        return None

    cache_dict = user_to_cache_dict(orm_user)
    try:
        from app.cache import get_cache
        get_cache().set_user_info(user_id, cache_dict)
    except Exception:
        pass

    return cached_user_from_dict(cache_dict)


def invalidate_user_cache(user_id: int) -> None:
    """Remove cached user info. Safe to call even if cache is unavailable."""
    try:
        from app.cache import get_cache
        get_cache().invalidate_user_info(user_id)
    except Exception:
        pass