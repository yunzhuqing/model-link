"""
Async cache layer for API Key information and budget tracking.

Supports two backends:
  - memory: In-process dictionary with TTL (default, no external dependencies)
  - redis:  Redis-backed cache for multi-instance deployments

Usage:
  from app.cache import get_async_cache

  # Get/set API key info
  info = await get_async_cache().get_api_key_info("sk-abc123")
  await get_async_cache().set_api_key_info("sk-abc123", {...})

  # Budget deduction (for USD-currency keys with budget)
  await get_async_cache().deduct_budget("sk-abc123", amount_usd=0.005)

  # Invalidate on update
  await get_async_cache().invalidate_api_key("sk-abc123")

Configuration (environment variables):
  CACHE_BACKEND       = memory | redis   (default: memory)
  CACHE_TTL           = 300              (seconds, default: 300 = 5 minutes)
  CACHE_REDIS_URL     = redis://localhost:6379/0
  CACHE_KEY_PREFIX    = ml:              (Redis key prefix, default: ml:)
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, Optional


def _json_default(obj):
    """Handle non-JSON-serializable types like Decimal from DB drivers."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


logger = logging.getLogger("cache")


# ── Sync Redis helper for background daemon threads ──────────────────────────

class SyncRedisHelper:
    """Minimal sync Redis helper for background daemon threads.

    Provides key_lock + basic get/set for apikey/group cache keys.
    NOT a general-purpose cache — async code must use AsyncCacheService.
    """

    _API_KEY_PREFIX = "apikey:"

    def __init__(self, redis_url: str, key_prefix: str = "ml:"):
        import redis as _redis
        self._client = _redis.Redis.from_url(redis_url, decode_responses=True)
        self._prefix = key_prefix
        self._default_ttl = int(os.getenv("CACHE_TTL", "300"))

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    @contextlib.contextmanager
    def key_lock(self, key: str, ttl: int = 30):
        """Distributed lock context manager for background thread coordination."""
        rk = f"{self._prefix}lock:key_sync:{key}"
        token = os.urandom(16).hex()
        while not bool(self._client.set(rk, token, nx=True, ex=ttl)):
            time.sleep(0.1)
        try:
            yield
        finally:
            self._client.delete(rk)

    def get_api_key_info(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Get cached API key info by raw key string."""
        raw = self._client.get(self._key(f"{self._API_KEY_PREFIX}{api_key}"))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_api_key_info(self, api_key: str, info: Dict[str, Any]) -> None:
        """Cache API key info with default TTL."""
        self._client.setex(
            self._key(f"{self._API_KEY_PREFIX}{api_key}"),
            self._default_ttl,
            json.dumps(info, default=_json_default),
        )

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a cached dict by key."""
        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set(self, key: str, value: Dict[str, Any], ttl: int) -> None:
        """Store a dict with TTL."""
        self._client.setex(self._key(key), ttl, json.dumps(value, default=_json_default))

    def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        self._client.delete(self._key(key))


import asyncio as _asyncio

# ── Async Abstract base ───────────────────────────────────────────────────────

class AsyncCacheBackend(ABC):
    """Abstract async cache backend interface."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Return cached dict or None if missing/expired."""

    @abstractmethod
    async def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store a dict with optional TTL in seconds."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a key from the cache."""

    @abstractmethod
    async def incr_float(self, key: str, field: str, amount: float) -> Optional[float]:
        """Atomically increment a float field. Returns new value or None."""

    @abstractmethod
    async def get_float(self, key: str) -> Optional[float]:
        """Return a cached scalar float, or None."""

    @abstractmethod
    async def set_float(self, key: str, value: float, ttl: Optional[int] = None) -> None:
        """Store a scalar float with optional TTL."""

    @abstractmethod
    async def incr_float_scalar(self, key: str, amount: float) -> Optional[float]:
        """Atomically increment a scalar float. Returns new value or None."""

    @abstractmethod
    async def acquire_lock(self, key: str, ttl: int = 30) -> bool:
        """Acquire a distributed lock. Returns True if acquired."""

    @abstractmethod
    async def release_lock(self, key: str) -> None:
        """Release a distributed lock."""


# ── Async Memory backend ──────────────────────────────────────────────────────

class AsyncMemoryCacheBackend(AsyncCacheBackend):
    """Async in-process dictionary cache with per-key TTL."""

    def __init__(self, default_ttl: int = 300):
        self._store: Dict[str, tuple] = {}
        self._locks: Dict[str, _asyncio.Lock] = {}
        self._lock = _asyncio.Lock()
        self._default_ttl = default_ttl

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + effective_ttl if effective_ttl > 0 else None
        async with self._lock:
            self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def incr_float(self, key: str, field: str, amount: float) -> Optional[float]:
        async with self._lock:
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

    async def get_float(self, key: str) -> Optional[float]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            return float(value) if value is not None else None

    async def set_float(self, key: str, value: float, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + effective_ttl if effective_ttl > 0 else None
        async with self._lock:
            self._store[key] = (value, expires_at)

    async def incr_float_scalar(self, key: str, amount: float) -> Optional[float]:
        async with self._lock:
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

    async def acquire_lock(self, key: str, ttl: int = 30) -> bool:
        del ttl  # unused in memory backend, kept for API compatibility
        async with self._lock:
            if key in self._locks:
                return False
            lock = _asyncio.Lock()
            acquired = lock.locked() is False  # new lock is unlocked
            if acquired:
                await lock.acquire()
                self._locks[key] = lock
                return True
            return False

    async def release_lock(self, key: str) -> None:
        async with self._lock:
            lock = self._locks.pop(key, None)
            if lock is not None:
                lock.release()


# ── Async Redis backend ───────────────────────────────────────────────────────

class AsyncRedisCacheBackend(AsyncCacheBackend):
    """Redis-backed async cache using redis.asyncio."""

    def __init__(self, redis_url: str, default_ttl: int = 300, key_prefix: str = "ml:"):
        self._default_ttl = default_ttl
        self._prefix = key_prefix
        self._redis_url = redis_url
        self._client = None

    @property
    def client(self):
        """Lazy-initialise and return the async Redis client."""
        if self._client is None:
            import redis.asyncio as _aioredis
            self._client = _aioredis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        raw = await self.client.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        rk = self._key(key)
        raw = json.dumps(value, default=_json_default)
        if effective_ttl > 0:
            await self.client.setex(rk, effective_ttl, raw)
        else:
            await self.client.set(rk, raw)

    async def delete(self, key: str) -> None:
        await self.client.delete(self._key(key))

    async def incr_float(self, key: str, field: str, amount: float) -> Optional[float]:
        lua_script = """
        local raw = redis.call('GET', KEYS[1])
        if not raw then return nil end
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
        result = await self.client.eval(lua_script, 1, rk, field, str(amount))
        if result is None:
            return None
        return float(result)

    async def get_float(self, key: str) -> Optional[float]:
        raw = await self.client.get(self._key(key))
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    async def set_float(self, key: str, value: float, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        rk = self._key(key)
        if effective_ttl > 0:
            await self.client.setex(rk, effective_ttl, str(value))
        else:
            await self.client.set(rk, str(value))

    async def incr_float_scalar(self, key: str, amount: float) -> Optional[float]:
        """Atomically increment a scalar float key. Returns None if the key
        doesn't exist (caller should load from DB and populate cache).

        Uses a Lua script to avoid the TOCTOU race where the key expires
        between an EXISTS check and INCRBYFLOAT, which would create a
        permanent key (TTL=-1) with a wrong value."""
        rk = self._key(key)
        lua = """
        if redis.call('EXISTS', KEYS[1]) == 0 then
            return nil
        end
        local val = redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
        local current_ttl = redis.call('TTL', KEYS[1])
        if current_ttl < 0 then
            redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
        end
        return tostring(val)
        """
        result = await self.client.eval(lua, 1, rk, str(amount), self._default_ttl)
        if result is None:
            return None
        return float(result)

    _LOCK_PREFIX = "lock:"

    def _lock_key(self, key: str) -> str:
        return f"{self._prefix}{self._LOCK_PREFIX}{key}"

    async def acquire_lock(self, key: str, ttl: int = 30) -> bool:
        rk = self._lock_key(key)
        token = os.urandom(16).hex()
        return bool(await self.client.set(rk, token, nx=True, ex=ttl))

    async def release_lock(self, key: str) -> None:
        rk = self._lock_key(key)
        await self.client.delete(rk)

    async def close(self) -> None:
        """Close the async Redis client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ── Async Cache service ──────────────────────────────────────────────────────

class AsyncCacheService:
    """Async high-level cache service for API key info and budget tracking."""

    _API_KEY_PREFIX = "apikey:"
    _API_KEY_ID_PREFIX = "apikey_id:"
    _BUDGET_REMAINING_PREFIX = "budget_remaining:"
    _USER_PREFIX = "user:"
    _THOUGHT_SIG_PREFIX = "thoughtsig:"
    _THOUGHT_SIG_TTL = 24 * 3600  # 24 hours

    def __init__(self, backend: AsyncCacheBackend, api_key_ttl: Optional[int] = None):
        self._backend = backend
        self._api_key_ttl = api_key_ttl

    # ── API Key info ──────────────────────────────────────────────────────

    async def get_api_key_info(self, api_key: str) -> Optional[Dict[str, Any]]:
        return await self._backend.get(f"{self._API_KEY_PREFIX}{api_key}")

    async def set_api_key_info(self, api_key: str, info: Dict[str, Any], ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._api_key_ttl
        await self._backend.set(f"{self._API_KEY_PREFIX}{api_key}", info, effective_ttl)
        api_key_id = info.get('id')
        if api_key_id is not None:
            await self._backend.set(f"{self._API_KEY_ID_PREFIX}{api_key_id}", {"key": api_key}, effective_ttl)

    async def get_api_key_info_by_id(self, api_key_id: int) -> Optional[Dict[str, Any]]:
        mapping = await self._backend.get(f"{self._API_KEY_ID_PREFIX}{api_key_id}")
        if mapping and 'key' in mapping:
            return await self.get_api_key_info(mapping['key'])
        return None

    async def invalidate_api_key(self, api_key: str) -> None:
        info = await self._backend.get(f"{self._API_KEY_PREFIX}{api_key}")
        if info and 'id' in info:
            await self._backend.delete(f"{self._API_KEY_ID_PREFIX}{info['id']}")
        await self._backend.delete(f"{self._API_KEY_PREFIX}{api_key}")

    async def invalidate_api_key_by_id(self, api_key_id: int) -> None:
        mapping = await self._backend.get(f"{self._API_KEY_ID_PREFIX}{api_key_id}")
        if mapping and 'key' in mapping:
            await self._backend.delete(f"{self._API_KEY_PREFIX}{mapping['key']}")
        await self._backend.delete(f"{self._API_KEY_ID_PREFIX}{api_key_id}")

    # ── Budget tracking ───────────────────────────────────────────────────

    async def set_budget_remaining(self, api_key: str, remaining: float, ttl: Optional[int] = None) -> None:
        await self._backend.set_float(f"{self._BUDGET_REMAINING_PREFIX}{api_key}", remaining, ttl=ttl)

    async def get_budget_remaining(self, api_key: str) -> Optional[float]:
        return await self._backend.get_float(f"{self._BUDGET_REMAINING_PREFIX}{api_key}")

    async def deduct_budget(self, api_key: str, amount_usd: float) -> Optional[float]:
        if amount_usd <= 0:
            return None
        return await self._backend.incr_float_scalar(
            f"{self._BUDGET_REMAINING_PREFIX}{api_key}", -amount_usd,
        )

    async def invalidate_budget_remaining(self, api_key: str) -> None:
        await self._backend.delete(f"{self._BUDGET_REMAINING_PREFIX}{api_key}")

    # ── User info ─────────────────────────────────────────────────────────

    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        return await self._backend.get(f"{self._USER_PREFIX}{user_id}")

    async def set_user_info(self, user_id: int, info: Dict[str, Any], ttl: Optional[int] = None) -> None:
        await self._backend.set(f"{self._USER_PREFIX}{user_id}", info, ttl)

    async def invalidate_user_info(self, user_id: int) -> None:
        await self._backend.delete(f"{self._USER_PREFIX}{user_id}")

    # ── Gemini/Vertex thoughtSignature cache ──────────────────────────────
    # tool_call_id → thoughtSignature(base64 string)。Gemini/Vertex 在 tool_call
    # 续接里需要回传同一签名。后端失败时回退到本地 dict,保证不阻断主流程。

    async def get_thought_signature(self, tool_call_id: str) -> Optional[str]:
        try:
            data = await self._backend.get(f"{self._THOUGHT_SIG_PREFIX}{tool_call_id}")
        except Exception:
            data = None
        if data and isinstance(data, dict):
            return data.get("sig")
        return _thought_sig_local_fallback.get(tool_call_id)

    async def set_thought_signature(self, tool_call_id: str, signature: str) -> None:
        try:
            await self._backend.set(
                f"{self._THOUGHT_SIG_PREFIX}{tool_call_id}",
                {"sig": signature},
                self._THOUGHT_SIG_TTL,
            )
        except Exception:
            _thought_sig_local_fallback[tool_call_id] = signature

    # ── Usage stats ───────────────────────────────────────────────────────

    async def increment_usage_stats(
        self, api_key: str, *, request_count: int = 1, input_tokens: int = 0,
        output_tokens: int = 0, reasoning_tokens: int = 0, cost_usd: float = 0.0,
        image_count: int = 0, video_count: int = 0, audio_seconds: float = 0.0,
        web_search_requests: int = 0, credits: float = 0.0,
    ) -> None:
        cache_key = f"{self._API_KEY_PREFIX}{api_key}"
        if request_count > 0:
            await self._backend.incr_float(cache_key, "request_count", float(request_count))
        if input_tokens > 0:
            await self._backend.incr_float(cache_key, "total_input_tokens", float(input_tokens))
        if output_tokens > 0:
            await self._backend.incr_float(cache_key, "total_output_tokens", float(output_tokens))
        if reasoning_tokens > 0:
            await self._backend.incr_float(cache_key, "total_reasoning_tokens", float(reasoning_tokens))
        total_tokens = input_tokens + output_tokens
        if total_tokens > 0:
            await self._backend.incr_float(cache_key, "token_count", float(total_tokens))
        if cost_usd > 0:
            await self._backend.incr_float(cache_key, "total_cost_usd", cost_usd)
        if image_count > 0:
            await self._backend.incr_float(cache_key, "total_image_count", float(image_count))
        if video_count > 0:
            await self._backend.incr_float(cache_key, "total_video_count", float(video_count))
        if audio_seconds > 0:
            await self._backend.incr_float(cache_key, "total_audio_seconds", audio_seconds)
        if web_search_requests > 0:
            await self._backend.incr_float(cache_key, "total_web_search_requests", float(web_search_requests))
        if credits > 0:
            await self._backend.incr_float(cache_key, "total_credits", credits)

    # ── Utility ───────────────────────────────────────────────────────────

    def build_api_key_cache_info(self, api_key_obj, budget_used: float = 0.0) -> Dict[str, Any]:
        """Build a cache-friendly dict from an ApiKey ORM object (sync — pure data)."""
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
            'id': api_key_obj.id, 'key': api_key_obj.key, 'name': api_key_obj.name,
            'description': getattr(api_key_obj, 'description', None),
            'group_id': api_key_obj.group_id, 'user_id': api_key_obj.user_id,
            'is_active': api_key_obj.is_active, 'budget': api_key_obj.budget,
            'allowed_models': api_key_obj.allowed_models or [],
            'expires_at': api_key_obj.expires_at.isoformat() if api_key_obj.expires_at else None,
            'request_count': api_key_obj.request_count or 0,
            'token_count': api_key_obj.token_count or 0,
            'user_name': user_name, 'group_name': group_name,
            'unlimited_budget': getattr(api_key_obj, 'unlimited_budget', True),
            'budget_used': budget_used,
            'total_input_tokens': getattr(api_key_obj, 'total_input_tokens', 0) or 0,
            'total_output_tokens': getattr(api_key_obj, 'total_output_tokens', 0) or 0,
            'total_reasoning_tokens': getattr(api_key_obj, 'total_reasoning_tokens', 0) or 0,
            'total_cost_usd': getattr(api_key_obj, 'total_cost_usd', 0.0) or 0.0,
            'total_image_count': getattr(api_key_obj, 'total_image_count', 0) or 0,
            'total_video_count': getattr(api_key_obj, 'total_video_count', 0) or 0,
            'total_audio_seconds': getattr(api_key_obj, 'total_audio_seconds', 0.0) or 0.0,
            'total_web_search_requests': getattr(api_key_obj, 'total_web_search_requests', 0) or 0,
            'total_credits': getattr(api_key_obj, 'total_credits', 0.0) or 0.0,
        }

    # ── Distributed key lock ──────────────────────────────────────────────

    @contextlib.asynccontextmanager
    async def key_lock(self, key: str, ttl: int = 30):
        lock_name = f"key_sync:{key}"
        while not await self._backend.acquire_lock(lock_name, ttl):
            await _asyncio.sleep(0.1)
        try:
            yield
        finally:
            await self._backend.release_lock(lock_name)


# ── Async module-level singleton ──────────────────────────────────────────────

_async_cache: Optional[AsyncCacheService] = None

# In-process fallback for thoughtSignature when Redis is unreachable.
# Capped to avoid unbounded growth; capacity chosen to comfortably hold a
# typical session's tool_call ids.
from collections import OrderedDict as _OrderedDict_for_fallback


class _ThoughtSigLocalFallback:
    __slots__ = ("_data", "_capacity")

    def __init__(self, capacity: int = 4096):
        self._data: "_OrderedDict_for_fallback[str, str]" = _OrderedDict_for_fallback()
        self._capacity = capacity

    def get(self, key: str) -> Optional[str]:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def __setitem__(self, key: str, value: str) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self._capacity:
            self._data.popitem(last=False)


_thought_sig_local_fallback = _ThoughtSigLocalFallback(capacity=4096)


def init_async_cache() -> AsyncCacheService:
    """Initialise the global AsyncCacheService singleton based on environment config.

    Called once at app startup from create_app().
    """
    global _async_cache
    backend_type = os.getenv("CACHE_BACKEND", "memory").lower().strip()
    default_ttl = int(os.getenv("CACHE_TTL", "300"))
    api_key_ttl = int(os.getenv("CACHE_APIKEY_TTL", "86400"))
    if backend_type == "redis":
        redis_url = os.getenv("CACHE_REDIS_URL", "redis://localhost:6379/0")
        key_prefix = os.getenv("CACHE_KEY_PREFIX", "ml:")
        backend = AsyncRedisCacheBackend(redis_url=redis_url, default_ttl=default_ttl, key_prefix=key_prefix)
        logger.info(f"Async cache initialised: Redis backend ({redis_url}), TTL={default_ttl}s")
    else:
        backend = AsyncMemoryCacheBackend(default_ttl=default_ttl)
        logger.info(f"Async cache initialised: Memory backend, TTL={default_ttl}s")
    _async_cache = AsyncCacheService(backend, api_key_ttl=api_key_ttl)
    return _async_cache


def get_async_cache() -> AsyncCacheService:
    """Return the global AsyncCacheService singleton. Initialises if needed."""
    global _async_cache
    if _async_cache is None:
        init_async_cache()
    return _async_cache


async def close_async_cache() -> None:
    """Close async cache connections (e.g. Redis client). Called on shutdown."""
    global _async_cache
    if _async_cache is not None:
        backend = _async_cache._backend
        if isinstance(backend, AsyncRedisCacheBackend):
            await backend.close()
        _async_cache = None
