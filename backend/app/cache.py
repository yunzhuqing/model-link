"""
Cache Middleware for API Key information and budget tracking.

Supports two backends:
  - memory: In-process dictionary with TTL (default, no external dependencies)
  - redis:  Redis-backed cache for multi-instance deployments

Usage:
  from app.cache import cache

  # Get/set API key info
  info = cache.get_api_key_info("sk-abc123")
  cache.set_api_key_info("sk-abc123", {...})

  # Budget deduction (for USD-currency keys with budget)
  cache.deduct_budget("sk-abc123", amount_usd=0.005)

  # Invalidate on update
  cache.invalidate_api_key("sk-abc123")

Configuration (environment variables):
  CACHE_BACKEND       = memory | redis   (default: memory)
  CACHE_TTL           = 300              (seconds, default: 300 = 5 minutes)
  CACHE_REDIS_URL     = redis://localhost:6379/0
  CACHE_KEY_PREFIX    = ml:              (Redis key prefix, default: ml:)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger("cache")


# ── Abstract base ─────────────────────────────────────────────────────────────

class CacheBackend(ABC):
    """Abstract cache backend interface."""

    @abstractmethod
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Return cached dict or None if missing/expired."""

    @abstractmethod
    def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store a dict with optional TTL in seconds."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove a key from the cache."""

    @abstractmethod
    def incr_float(self, key: str, field: str, amount: float) -> Optional[float]:
        """
        Atomically increment a float field inside a cached dict.
        Returns the new value, or None if the key doesn't exist.
        """

    # ── Scalar float operations (for simple numeric keys) ─────────────────

    @abstractmethod
    def get_float(self, key: str) -> Optional[float]:
        """Return a cached scalar float value, or None if missing/expired."""

    @abstractmethod
    def set_float(self, key: str, value: float, ttl: Optional[int] = None) -> None:
        """Store a scalar float value with optional TTL in seconds."""

    @abstractmethod
    def incr_float_scalar(self, key: str, amount: float) -> Optional[float]:
        """
        Atomically increment a scalar float key by the given amount.
        Returns the new value, or None if the key doesn't exist.
        """


# ── Memory backend ───────────────────────────────────────────────────────────

class MemoryCacheBackend(CacheBackend):
    """
    Thread-safe in-process dictionary cache with per-key TTL.

    Suitable for single-instance deployments or development.
    """

    def __init__(self, default_ttl: int = 300):
        self._store: Dict[str, tuple] = {}  # key → (value_dict, expire_timestamp)
        self._lock = threading.Lock()
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + effective_ttl if effective_ttl > 0 else None
        with self._lock:
            self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def incr_float(self, key: str, field: str, amount: float) -> Optional[float]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            current = value.get(field, 0.0)
            new_val = current + amount
            value[field] = new_val
            return new_val

    # ── Scalar float operations ───────────────────────────────────────────

    def get_float(self, key: str) -> Optional[float]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            return float(value) if value is not None else None

    def set_float(self, key: str, value: float, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + effective_ttl if effective_ttl > 0 else None
        with self._lock:
            self._store[key] = (value, expires_at)

    def incr_float_scalar(self, key: str, amount: float) -> Optional[float]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            new_val = float(value or 0) + amount
            self._store[key] = (new_val, expires_at)
            return new_val


# ── Redis backend ─────────────────────────────────────────────────────────────

class RedisCacheBackend(CacheBackend):
    """
    Redis-backed cache using hash + JSON serialisation.

    Suitable for multi-instance / production deployments.
    Requires ``redis`` package (``pip install redis``).
    """

    def __init__(self, redis_url: str, default_ttl: int = 300, key_prefix: str = "ml:"):
        import redis as _redis
        self._client = _redis.Redis.from_url(redis_url, decode_responses=True)
        self._default_ttl = default_ttl
        self._prefix = key_prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        rk = self._key(key)
        raw = json.dumps(value)
        if effective_ttl > 0:
            self._client.setex(rk, effective_ttl, raw)
        else:
            self._client.set(rk, raw)

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def incr_float(self, key: str, field: str, amount: float) -> Optional[float]:
        """
        Atomically increment a float field inside a cached JSON dict.

        Uses a Lua script for atomicity on Redis.
        """
        lua_script = """
        local raw = redis.call('GET', KEYS[1])
        if not raw then
            return nil
        end
        local obj = cjson.decode(raw)
        local current = tonumber(obj[ARGV[1]] or 0)
        local new_val = current + tonumber(ARGV[2])
        obj[ARGV[1]] = new_val
        local ttl = redis.call('TTL', KEYS[1])
        local encoded = cjson.encode(obj)
        if ttl > 0 then
            redis.call('SETEX', KEYS[1], ttl, encoded)
        else
            redis.call('SET', KEYS[1], encoded)
        end
        return tostring(new_val)
        """
        rk = self._key(key)
        result = self._client.eval(lua_script, 1, rk, field, str(amount))
        if result is None:
            return None
        return float(result)

    # ── Scalar float operations ───────────────────────────────────────────

    def get_float(self, key: str) -> Optional[float]:
        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    def set_float(self, key: str, value: float, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        rk = self._key(key)
        if effective_ttl > 0:
            self._client.setex(rk, effective_ttl, str(value))
        else:
            self._client.set(rk, str(value))

    def incr_float_scalar(self, key: str, amount: float) -> Optional[float]:
        """Atomically increment a scalar float key using Redis INCRBYFLOAT."""
        rk = self._key(key)
        # INCRBYFLOAT returns an error if key doesn't exist; check first.
        if not self._client.exists(rk):
            return None
        result = self._client.incrbyfloat(rk, amount)
        return float(result)


# ── Cache service (high-level API) ────────────────────────────────────────────

class CacheService:
    """
    High-level cache service for API key information and budget tracking.

    Wraps a CacheBackend and provides domain-specific methods.
    """

    # Cache key prefixes
    _API_KEY_PREFIX = "apikey:"
    _API_KEY_ID_PREFIX = "apikey_id:"
    _BUDGET_REMAINING_PREFIX = "budget_remaining:"

    def __init__(self, backend: CacheBackend, api_key_ttl: Optional[int] = None):
        self._backend = backend
        # Dedicated TTL for API key cache entries (default: 24 hours = 86400s).
        # Configurable via CACHE_APIKEY_TTL environment variable.
        self._api_key_ttl = api_key_ttl

    # ── API Key info ──────────────────────────────────────────────────────

    def get_api_key_info(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Get cached API key information by the raw API key string.

        Returns a dict with keys:
            id, key, name, group_id, user_id, is_active, budget,
            allowed_models, expires_at, request_count, token_count,
            user_name, group_name, budget_used
        or None if not cached.
        """
        return self._backend.get(f"{self._API_KEY_PREFIX}{api_key}")

    def set_api_key_info(self, api_key: str, info: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Cache API key information keyed by the raw API key string.
        
        Uses the dedicated API key TTL (default 24h) unless an explicit ttl is provided.
        """
        effective_ttl = ttl if ttl is not None else self._api_key_ttl
        self._backend.set(f"{self._API_KEY_PREFIX}{api_key}", info, effective_ttl)
        # Also index by ID for invalidation from admin routes
        api_key_id = info.get('id')
        if api_key_id is not None:
            self._backend.set(f"{self._API_KEY_ID_PREFIX}{api_key_id}", {"key": api_key}, effective_ttl)

    def get_api_key_info_by_id(self, api_key_id: int) -> Optional[Dict[str, Any]]:
        """
        Get cached API key information by the API key's database ID.

        First looks up the raw key from the ID index, then fetches the full info.
        """
        mapping = self._backend.get(f"{self._API_KEY_ID_PREFIX}{api_key_id}")
        if mapping and 'key' in mapping:
            return self.get_api_key_info(mapping['key'])
        return None

    def invalidate_api_key(self, api_key: str) -> None:
        """Remove cached API key info by raw key string."""
        # First try to find the ID mapping to clean up
        info = self._backend.get(f"{self._API_KEY_PREFIX}{api_key}")
        if info and 'id' in info:
            self._backend.delete(f"{self._API_KEY_ID_PREFIX}{info['id']}")
        self._backend.delete(f"{self._API_KEY_PREFIX}{api_key}")

    def invalidate_api_key_by_id(self, api_key_id: int) -> None:
        """Remove cached API key info by database ID."""
        mapping = self._backend.get(f"{self._API_KEY_ID_PREFIX}{api_key_id}")
        if mapping and 'key' in mapping:
            self._backend.delete(f"{self._API_KEY_PREFIX}{mapping['key']}")
        self._backend.delete(f"{self._API_KEY_ID_PREFIX}{api_key_id}")

    # ── Budget tracking (dedicated key) ───────────────────────────────────

    def set_budget_remaining(self, api_key: str, remaining: float, ttl: Optional[int] = None) -> None:
        """
        Set the real-time remaining budget for an API key in a dedicated cache key.

        Stores a plain float value (not a dict). This key is the single source
        of truth for budget checks in the gateway. It is updated:
          - When the API key cache is first populated (from DB)
          - After each request (decremented by actual_amount_usd)
          - When budget is added/deleted via admin routes

        Args:
            api_key: The raw API key string.
            remaining: The remaining budget in USD.
            ttl: Optional TTL in seconds. If None, uses the default TTL from
                 the BudgetManager (typically 600s / 10 minutes).
        """
        self._backend.set_float(
            f"{self._BUDGET_REMAINING_PREFIX}{api_key}",
            remaining,
            ttl=ttl,
        )

    def get_budget_remaining(self, api_key: str) -> Optional[float]:
        """
        Get the real-time remaining budget for an API key from the dedicated cache key.

        Returns None if not cached (caller should fall back to DB).
        Returns the remaining amount in USD.
        """
        return self._backend.get_float(f"{self._BUDGET_REMAINING_PREFIX}{api_key}")

    def deduct_budget(self, api_key: str, amount_usd: float) -> Optional[float]:
        """
        Atomically deduct an amount (in USD) from the dedicated budget remaining key.

        This is called AFTER the database write succeeds, to keep the cache
        in sync with the authoritative database.

        The amount is *subtracted* from the remaining balance (negative increment).

        Returns the new remaining value, or None if the key doesn't exist in cache.
        """
        if amount_usd <= 0:
            return None
        return self._backend.incr_float_scalar(
            f"{self._BUDGET_REMAINING_PREFIX}{api_key}",
            -amount_usd,  # subtract from remaining
        )

    def invalidate_budget_remaining(self, api_key: str) -> None:
        """Remove the dedicated budget remaining cache key."""
        self._backend.delete(f"{self._BUDGET_REMAINING_PREFIX}{api_key}")

    # ── Usage stats tracking ──────────────────────────────────────────────

    def increment_usage_stats(
        self,
        api_key: str,
        *,
        request_count: int = 1,
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        cost_usd: float = 0.0,
        image_count: int = 0,
        video_count: int = 0,
        audio_seconds: float = 0.0,
    ) -> None:
        """
        Atomically increment usage stats fields in the cached API key info.

        Called after each request to keep cache up-to-date in real time.
        """
        cache_key = f"{self._API_KEY_PREFIX}{api_key}"
        if request_count > 0:
            self._backend.incr_float(cache_key, "request_count", float(request_count))
        if input_tokens > 0:
            self._backend.incr_float(cache_key, "total_input_tokens", float(input_tokens))
        if output_tokens > 0:
            self._backend.incr_float(cache_key, "total_output_tokens", float(output_tokens))
        if reasoning_tokens > 0:
            self._backend.incr_float(cache_key, "total_reasoning_tokens", float(reasoning_tokens))
        total_tokens = input_tokens + output_tokens
        if total_tokens > 0:
            self._backend.incr_float(cache_key, "token_count", float(total_tokens))
        if cost_usd > 0:
            self._backend.incr_float(cache_key, "total_cost_usd", cost_usd)
        if image_count > 0:
            self._backend.incr_float(cache_key, "total_image_count", float(image_count))
        if video_count > 0:
            self._backend.incr_float(cache_key, "total_video_count", float(video_count))
        if audio_seconds > 0:
            self._backend.incr_float(cache_key, "total_audio_seconds", audio_seconds)

    # ── Utility ───────────────────────────────────────────────────────────

    def build_api_key_cache_info(
        self,
        api_key_obj,
        budget_used: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Build a cache-friendly dict from an ApiKey ORM object.

        Args:
            api_key_obj: The ApiKey SQLAlchemy model instance.
            budget_used: Pre-computed total usage in USD for this key.

        Returns:
            A plain dict suitable for caching.
        """
        user_name = None
        try:
            if api_key_obj.user:
                user_name = api_key_obj.user.username
        except Exception:
            pass

        group_name = None
        try:
            if api_key_obj.group:
                group_name = api_key_obj.group.name
        except Exception:
            pass

        return {
            'id': api_key_obj.id,
            'key': api_key_obj.key,
            'name': api_key_obj.name,
            'group_id': api_key_obj.group_id,
            'user_id': api_key_obj.user_id,
            'is_active': api_key_obj.is_active,
            'budget': api_key_obj.budget,
            'allowed_models': api_key_obj.allowed_models or [],
            'expires_at': api_key_obj.expires_at.isoformat() if api_key_obj.expires_at else None,
            'request_count': api_key_obj.request_count or 0,
            'token_count': api_key_obj.token_count or 0,
            'user_name': user_name,
            'group_name': group_name,
            'unlimited_budget': getattr(api_key_obj, 'unlimited_budget', True),
            'budget_used': budget_used,
            # Historical cumulative usage stats
            'total_input_tokens': getattr(api_key_obj, 'total_input_tokens', 0) or 0,
            'total_output_tokens': getattr(api_key_obj, 'total_output_tokens', 0) or 0,
            'total_reasoning_tokens': getattr(api_key_obj, 'total_reasoning_tokens', 0) or 0,
            'total_cost_usd': getattr(api_key_obj, 'total_cost_usd', 0.0) or 0.0,
            'total_image_count': getattr(api_key_obj, 'total_image_count', 0) or 0,
            'total_video_count': getattr(api_key_obj, 'total_video_count', 0) or 0,
            'total_audio_seconds': getattr(api_key_obj, 'total_audio_seconds', 0.0) or 0.0,
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_cache: Optional[CacheService] = None
_cache_lock = threading.Lock()


def init_cache() -> CacheService:
    """
    Initialise the global CacheService singleton based on environment config.

    Called once at app startup from create_app().
    """
    global _cache

    backend_type = os.getenv("CACHE_BACKEND", "memory").lower().strip()
    default_ttl = int(os.getenv("CACHE_TTL", "300"))
    # Dedicated TTL for API key cache entries (default: 24 hours = 86400s).
    # API key data changes infrequently but is read on every request,
    # so a long TTL reduces DB load while budget/usage updates keep it fresh.
    api_key_ttl = int(os.getenv("CACHE_APIKEY_TTL", "86400"))

    if backend_type == "redis":
        redis_url = os.getenv("CACHE_REDIS_URL", "redis://localhost:6379/0")
        key_prefix = os.getenv("CACHE_KEY_PREFIX", "ml:")
        backend = RedisCacheBackend(
            redis_url=redis_url,
            default_ttl=default_ttl,
            key_prefix=key_prefix,
        )
        logger.info(f"Cache initialised: Redis backend ({redis_url}), TTL={default_ttl}s, API key TTL={api_key_ttl}s")
    else:
        backend = MemoryCacheBackend(default_ttl=default_ttl)
        logger.info(f"Cache initialised: Memory backend, TTL={default_ttl}s, API key TTL={api_key_ttl}s")

    _cache = CacheService(backend, api_key_ttl=api_key_ttl)
    return _cache


def get_cache() -> CacheService:
    """Return the global CacheService singleton. Initialises if needed."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                init_cache()
    return _cache
