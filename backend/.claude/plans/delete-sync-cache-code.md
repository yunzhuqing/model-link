# Plan: Fix TOCTOU + Delete Sync Cache Code

## Overview

1. Fix the TOCTOU race condition in `incr_float_scalar` (both sync and async)
2. Delete all sync `CacheService`, `RedisCacheBackend`, `MemoryCacheBackend`, `BudgetManager` code
3. Migrate all callers to async equivalents
4. Provide minimal `SyncRedisHelper` for background daemon threads

---

## Step 1: Fix TOCTOU in `incr_float_scalar`

**File:** `app/cache.py`

Replace the `EXISTS` + `INCRBYFLOAT` pattern with a Lua script that atomically increments AND ensures TTL is preserved/set.

### 1a: Fix sync `RedisCacheBackend.incr_float_scalar` (line 290-297)

```python
def incr_float_scalar(self, key: str, amount: float) -> Optional[float]:
    """Atomically increment a scalar float key. Preserves TTL; auto-creates with TTL if expired."""
    rk = self._key(key)
    lua = """
    local val = redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
    local current_ttl = redis.call('TTL', KEYS[1])
    if current_ttl < 0 then
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
    end
    return tostring(val)
    """
    result = self._client.eval(lua, 1, rk, str(amount), self._default_ttl)
    return float(result) if result is not None else None
```

### 1b: Fix async `AsyncRedisCacheBackend.incr_float_scalar` (line 843-848)

Same Lua script, using `await self.client.eval(...)`.

---

## Step 2: Delete sync code in `app/cache.py`

**Delete these classes (and their full method bodies):**
- `CacheBackend` (abstract base, ~line 51-98) — NOT used by async backends (they inherit from `AsyncCacheBackend`)
- `MemoryCacheBackend` (~line 101-199) — zero external importers
- `RedisCacheBackend` (~line 203-318) — zero external importers  
- `CacheService` (~line 320-604) — zero external class importers

**Delete these module-level items:**
- `_cache: Optional[CacheService]` (~line 584)
- `_cache_lock` (~line 585)
- `init_cache()` (~line 588-603)
- `get_cache()` (~line 606-613)

**Add a minimal `SyncRedisHelper` for background threads** (placed after the deleted code):

```python
class SyncRedisHelper:
    """Minimal sync Redis helper for background daemon threads.
    
    Only provides key_lock + basic get/set for apikey/group cache keys.
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
        """Distributed lock context manager (SET NX EX ... DEL)."""
        rk = f"{self._prefix}lock:{key}"
        token = os.urandom(16).hex()
        acquired = bool(self._client.set(rk, token, nx=True, ex=ttl))
        if not acquired:
            raise RuntimeError(f"Failed to acquire lock for key: {key}")
        try:
            yield
        finally:
            # Best-effort release
            self._client.delete(rk)
    
    def get_api_key_info(self, api_key: str) -> Optional[Dict[str, Any]]:
        raw = self._client.get(self._key(f"{self._API_KEY_PREFIX}{api_key}"))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    
    def set_api_key_info(self, api_key: str, info: Dict[str, Any]) -> None:
        self._client.setex(
            self._key(f"{self._API_KEY_PREFIX}{api_key}"),
            self._default_ttl,
            json.dumps(info, default=_json_default),
        )
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    
    def set(self, key: str, value: Dict[str, Any], ttl: int) -> None:
        self._client.setex(self._key(key), ttl, json.dumps(value, default=_json_default))
    
    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))
```

**Update module docstring** — remove sync usage examples.

---

## Step 3: Delete sync code in `app/budget_manager.py`

**Delete:**
- `BudgetManager` class (~line 37-143)
- `_manager` singleton (~line 147)
- `_manager_lock` (~line 148)
- `get_budget_manager()` (~line 150-155)

**Update module docstring** — change `get_budget_manager` to `get_async_budget_manager`.

---

## Step 4: Migrate `app/routes/apikeys.py`

All routes are `async def`. Replace every `get_cache()` → `get_async_cache()` and `get_budget_manager()` → `get_async_budget_manager()`, adding `await`.

**Affected locations (8 cache sites + 5 budget sites):**

| Lines | Pattern | Replacement |
|-------|---------|-------------|
| 585-587 | `cache = get_cache()` | `cache = get_async_cache()` |
| 597 | `cache.invalidate_api_key_by_id(...)` | `await cache.invalidate_api_key_by_id(...)` |
| 772-773 | `cache = get_cache()` | `cache = get_async_cache()` |
| 774 | `cache.get_api_key_info(...)` | `await cache.get_api_key_info(...)` |
| 782 | `cache.set_api_key_info(...)` | `await cache.set_api_key_info(...)` |
| 784 | `cache.invalidate_api_key_by_id(...)` | `await cache.invalidate_api_key_by_id(...)` |
| 787-788 | `bm = get_budget_manager()` | `bm = get_async_budget_manager()` |
| 790 | `bm.set_remaining(...)` | `await bm.set_remaining(...)` |
| 793 | `bm.invalidate(...)` | `await bm.invalidate(...)` |
| 886 | `cache = get_cache()` | `cache = get_async_cache()` |
| 887 | `cache.get_api_key_info(...)` | `await cache.get_api_key_info(...)` |
| 1117-1120 | `get_cache().invalidate_api_key(...)` + `get_budget_manager().invalidate(...)` | `await get_async_cache().invalidate_api_key(...)` + `await get_async_budget_manager().invalidate(...)` |
| 1161-1164 | Same pattern as above | Same replacement |
| 1250-1251 | `cache = get_cache()` | `cache = get_async_cache()` |
| 1252 | `cache.get_api_key_info(...)` | `await cache.get_api_key_info(...)` |
| 1255 | `cache.set_api_key_info(...)` | `await cache.set_api_key_info(...)` |
| 1258 | `cache.invalidate_api_key_by_id(...)` | `await cache.invalidate_api_key_by_id(...)` |
| 1262-1263 | `get_budget_manager().set_remaining(...)` | `await get_async_budget_manager().set_remaining(...)` |
| 1303-1304 | `cache = get_cache()` | `cache = get_async_cache()` |
| 1305 | `cache.get_api_key_info(...)` | `await cache.get_api_key_info(...)` |
| 1308 | `cache.set_api_key_info(...)` | `await cache.set_api_key_info(...)` |
| 1310 | `cache.invalidate_api_key_by_id(...)` | `await cache.invalidate_api_key_by_id(...)` |
| 1314-1315 | `get_budget_manager().set_remaining(...)` | `await get_async_budget_manager().set_remaining(...)` |

---

## Step 5: Migrate `app/group_service.py`

| Lines | Current | Replacement |
|-------|---------|-------------|
| 74-75 | `from app.cache import get_cache` / `cache = get_cache()` | `from app.cache import get_async_cache` / `cache = get_async_cache()` |
| 77 | `cache._backend.get(key)` | `await cache._backend.get(key)` |
| 93 | `cache._backend.set(key, data, _GROUP_CACHE_TTL)` | `await cache._backend.set(key, data, _GROUP_CACHE_TTL)` |
| 147-153 | `def invalidate_group_cache` (sync) | make `async def`, use `get_async_cache()` |
| 149 | `from app.cache import get_cache` | `from app.cache import get_async_cache` |
| 151 | `get_cache()._backend.delete(...)` | `await get_async_cache()._backend.delete(...)` |
| 236 | `invalidate_group_cache(group_id)` | `await invalidate_group_cache(group_id)` |
| 248 | `invalidate_group_cache(group_id)` | `await invalidate_group_cache(group_id)` |

---

## Step 6: Migrate `app/usagerecord/sync_service.py`

Replace `get_cache()` usage with `SyncRedisHelper`.

**Line 123:** `from app.cache import get_cache` → `from app.cache import SyncRedisHelper`
**Line 132:** `cache = get_cache()` → `cache = _get_sync_redis_helper()`
**Line 159:** `with get_cache().key_lock(key_hash):` → `with cache.key_lock(key_hash):`

Add a module-level lazy singleton:

```python
_sync_redis: Optional[SyncRedisHelper] = None

def _get_sync_redis_helper() -> SyncRedisHelper:
    global _sync_redis
    if _sync_redis is None:
        redis_url = os.getenv("CACHE_REDIS_URL", "redis://localhost:6379/0")
        _sync_redis = SyncRedisHelper(redis_url)
    return _sync_redis
```

---

## Step 7: Migrate `app/usagerecord/compress_service.py`

**Lines 179, 191:** Same replacement pattern as sync_service.

---

## Step 8: Fix `app/routes/usage.py` (pre-existing bug)

**Line 815:** `result = _compress_key_for_api_key(current_app, int(api_key_id))` — this calls sync code directly from `async def run_compress()`, blocking the event loop.

Wrap in `asyncio.to_thread()`:
```python
result = await asyncio.to_thread(_compress_key_for_api_key, current_app, int(api_key_id))
```

**Line 818:** Same:
```python
deleted = await asyncio.to_thread(_do_compress, current_app)
```

---

## Files NOT modified

- `app/__init__.py` — only references async variants, no changes needed
- `app/rate_limiter.py` — only imports `AsyncCacheBackend` and `get_async_cache`
- `app/user_service.py` — only imports `get_async_cache`
- `app/usagerecord/usage_service.py` — only imports `get_async_cache` and `get_async_budget_manager`
- `app/routes/gateway_helpers.py` — only imports `get_async_cache` and `get_async_budget_manager`

---

## Rollback safety

- The sync code has zero external class importers — no other module depends on the class symbols
- All external consumers use `get_cache()` / `get_budget_manager()` which are being replaced
- The `SyncRedisHelper` provides backward-compatible API for background threads
- If rollback is needed: restore the sync classes, revert `await` additions
