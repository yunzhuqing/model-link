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
    from app.budget_manager import get_budget_manager
    bm = get_budget_manager()
    remaining = bm.get_remaining("sk-abc123")
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("budget")

# Default TTL for the budget remaining cache key (seconds).
# Configurable via CACHE_BUDGET_TTL environment variable.
_DEFAULT_BUDGET_TTL = int(os.getenv("CACHE_BUDGET_TTL", "600"))  # 10 minutes


class BudgetManager:
    """
    Manages real-time API key budget tracking with cache + DB fallback.

    The budget remaining value is stored as a plain scalar float in the cache.
    On a cache miss, it is loaded from the database.
    """

    def __init__(self, ttl: int = _DEFAULT_BUDGET_TTL):
        self._ttl = ttl

    def get_remaining(self, api_key_raw: str, db_session=None) -> Optional[float]:
        """
        Get the real-time remaining budget for an API key.

        1. Try the dedicated cache key first.
        2. On cache miss, load from DB and populate cache.
        3. Returns None if the key has unlimited budget or no budget set.

        Args:
            api_key_raw: The raw API key string.
            db_session: Optional SQLAlchemy session. If not provided,
                        uses the app-level db.session.
        """
        from app.cache import get_cache
        cache = get_cache()

        # 1. Try cache
        remaining = cache.get_budget_remaining(api_key_raw)
        if remaining is not None:
            return remaining

        # 2. Cache miss — load from DB
        return self._load_from_db(api_key_raw, cache, db_session)

    def deduct(self, api_key_raw: str, amount_usd: float) -> Optional[float]:
        """
        Atomically deduct spending from the cached budget remaining.

        If the cache key doesn't exist, loads from DB first, then deducts.

        Returns the new remaining value, or None if the key is not budgeted.
        """
        if amount_usd <= 0:
            return None

        from app.cache import get_cache
        cache = get_cache()

        # Try atomic deduction first
        new_remaining = cache.deduct_budget(api_key_raw, amount_usd)
        if new_remaining is not None:
            return new_remaining

        # Cache miss — load from DB, then deduct
        loaded = self._load_from_db(api_key_raw, cache)
        if loaded is None:
            return None  # unlimited or no budget

        # Now deduct (key should be in cache after _load_from_db)
        return cache.deduct_budget(api_key_raw, amount_usd)

    def set_remaining(self, api_key_raw: str, remaining: float) -> None:
        """
        Set the budget remaining value in cache.

        Called when budget is modified via admin routes.
        """
        from app.cache import get_cache
        get_cache().set_budget_remaining(api_key_raw, remaining, ttl=self._ttl)

    def invalidate(self, api_key_raw: str) -> None:
        """Remove the budget remaining cache key."""
        from app.cache import get_cache
        get_cache().invalidate_budget_remaining(api_key_raw)

    def _load_from_db(self, api_key_raw: str, cache, db_session=None) -> Optional[float]:
        """
        Load the budget remaining from the database and populate the cache.

        Returns the remaining value, or None if the key is unlimited/no budget.
        """
        try:
            if db_session is None:
                from app import db
                db_session = db.session

            from app.models import ApiKey
            ak = db_session.query(ApiKey).filter(ApiKey.key == api_key_raw).first()
            if not ak:
                return None

            # Unlimited budget — no remaining to track
            if ak.unlimited_budget:
                return None

            # No budget set
            if ak.budget is None:
                return None

            remaining = float(ak.budget)
            cache.set_budget_remaining(api_key_raw, remaining, ttl=self._ttl)
            return remaining
        except Exception as exc:
            logger.debug(f"[budget] Failed to load budget from DB for key: {exc}")
            return None


# ── Module-level singleton ────────────────────────────────────────────────────

_manager: Optional[BudgetManager] = None


def get_budget_manager() -> BudgetManager:
    """Return the global BudgetManager singleton."""
    global _manager
    if _manager is None:
        _manager = BudgetManager()
    return _manager
