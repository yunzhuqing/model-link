"""
Budget Manager — Real-time API key budget tracking with cache + DB fallback.

This module provides a high-level API for budget operations:
  - get_remaining(api_key_raw) → float or None
  - deduct(api_key_raw, amount_usd) → float or None
  - set_remaining(api_key_raw, remaining) → None
  - invalidate(api_key_raw) → None

The budget remaining value is stored in a dedicated cache key
(``budget_remaining:{api_key}``).  On a cache miss, the value is
loaded from the DB's ``ApiKey.budget`` field and cached.

This ensures:
  - Real-time accuracy: each request atomically decrements the cached value.
  - No staleness: cache misses transparently reload from the DB.
  - Reasonable TTL: the key expires and is refreshed periodically.

Usage:
    from app.budget_manager import get_async_budget_manager
    bm = get_async_budget_manager()
    remaining = await bm.get_remaining("sk-abc123")
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("budget")

# Default TTL for the budget remaining cache key (seconds).
# Configurable via CACHE_BUDGET_TTL environment variable.
_DEFAULT_BUDGET_TTL = int(os.getenv("CACHE_BUDGET_TTL", "600"))  # 10 minutes


# ═══════════════════════════════════════════════════════════════════════════════
# ── Async Budget Manager ──────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class AsyncBudgetManager:
    """Async real-time API key budget tracking with cache + DB fallback."""

    def __init__(self, ttl: int = _DEFAULT_BUDGET_TTL):
        self._ttl = ttl

    async def get_remaining(self, api_key_raw: str, db_session=None) -> Optional[float]:
        """Get the real-time remaining budget for an API key (async)."""
        from app.cache import get_async_cache
        cache = get_async_cache()
        remaining = await cache.get_budget_remaining(api_key_raw)
        if remaining is not None:
            return remaining
        return await self._load_from_db(api_key_raw, cache, db_session)

    async def deduct(self, api_key_raw: str, amount_usd: float) -> Optional[float]:
        """Atomically deduct spending from the cached budget remaining (async)."""
        if amount_usd <= 0:
            return None
        from app.cache import get_async_cache
        cache = get_async_cache()
        new_remaining = await cache.deduct_budget(api_key_raw, amount_usd)
        if new_remaining is not None:
            return new_remaining
        loaded = await self._load_from_db(api_key_raw, cache)
        if loaded is None:
            return None
        return await cache.deduct_budget(api_key_raw, amount_usd)

    async def set_remaining(self, api_key_raw: str, remaining: float) -> None:
        """Set the budget remaining value in cache (async)."""
        from app.cache import get_async_cache
        await get_async_cache().set_budget_remaining(api_key_raw, remaining, ttl=self._ttl)

    async def invalidate(self, api_key_raw: str) -> None:
        """Remove the budget remaining cache key (async)."""
        from app.cache import get_async_cache
        await get_async_cache().invalidate_budget_remaining(api_key_raw)

    async def _load_from_db(self, api_key_raw: str, cache, db_session=None) -> Optional[float]:
        """Load the budget remaining from DB and populate cache (async).

        If ``db_session`` is None, opens its own short-lived session via the
        shared async engine. Pass a session explicitly when the caller already
        holds one to avoid an extra connection round-trip.
        """
        from sqlalchemy import select as _sel
        from app.models import ApiKey

        async def _query(session) -> Optional[float]:
            result = await session.execute(_sel(ApiKey).where(ApiKey.key == api_key_raw))
            ak = result.scalars().first()
            if not ak:
                return None
            if ak.unlimited_budget:
                return None
            remaining = 0.0 if ak.budget is None else float(ak.budget)
            await cache.set_budget_remaining(api_key_raw, remaining, ttl=self._ttl)
            return remaining

        try:
            if db_session is not None:
                return await _query(db_session)
            from app import get_db_session
            async with get_db_session() as session:
                return await _query(session)
        except Exception as exc:
            logger.error(f"[budget] Failed to load budget from DB: {exc}", exc_info=True)
            return None


# ── Async singleton ───────────────────────────────────────────────────────────

_async_manager: Optional[AsyncBudgetManager] = None


def get_async_budget_manager() -> AsyncBudgetManager:
    """Return the global AsyncBudgetManager singleton."""
    global _async_manager
    if _async_manager is None:
        _async_manager = AsyncBudgetManager()
    return _async_manager
