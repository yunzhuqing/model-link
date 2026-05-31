"""
ARQ client: enqueues jobs from the Quart web process into the ARQ Redis queue.

Provides debounced enqueuing for API key usage updates so that multiple
requests for the same key within a time window coalesce into a single DB write.
"""

import logging
import os
import time
from typing import Optional

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

logger = logging.getLogger("arq.client")

# ── Singleton ────────────────────────────────────────────────────────────────

_arq_pool: Optional[ArqRedis] = None

# Debounce window in seconds. Requests for the same API key within this
# window are coalesced into a single DB update.
DEBOUNCE_SECONDS = int(os.getenv("ARQ_DEBOUNCE_SECONDS", "5"))


def _get_redis_url() -> str:
    return os.getenv(
        "ARQ_REDIS_URL",
        os.getenv("CACHE_REDIS_URL", "redis://localhost:6379/0"),
    )


async def init_arq() -> None:
    """Create the ARQ Redis connection pool. Called once at app startup."""
    global _arq_pool
    url = _get_redis_url()
    settings = RedisSettings.from_dsn(url)
    _arq_pool = await create_pool(settings)
    logger.info("ARQ client pool created: %s", url)


async def close_arq() -> None:
    """Close the ARQ Redis connection pool. Called at app shutdown."""
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
        logger.info("ARQ client pool closed")


def get_arq() -> Optional[ArqRedis]:
    """Return the current ARQ pool, or None if not yet initialised."""
    return _arq_pool


# ── Enqueue helpers ──────────────────────────────────────────────────────────


async def enqueue_apikey_usage(api_key_id: int) -> None:
    """Enqueue an API key usage update job with time-bucket deduplication.

    Uses ARQ's ``_job_id`` with a time-bucketed key so that multiple requests
    for the same API key within DEBOUNCE_SECONDS result in at most one DB write.
    The job is also deferred by DEBOUNCE_SECONDS to give subsequent requests
    time to land in the same bucket.

    If the ARQ pool is unavailable or the job already exists (duplicate
    ``_job_id``), this function silently returns — the usage-sync leader
    service periodically reconciles these stats anyway.
    """
    pool = _arq_pool
    if pool is None:
        logger.debug("[arq] Pool not initialised, skipping apikey_usage enqueue")
        return

    bucket = int(time.time() / DEBOUNCE_SECONDS)
    job_id = f"apikey_usage:{api_key_id}:{bucket}"

    try:
        result = await pool.enqueue_job(
            "update_apikey_usage",
            api_key_id,
            _job_id=job_id,
            _defer_by=DEBOUNCE_SECONDS,
        )
        if result is None:
            # Job with this ID already exists in the queue — dedup in action
            return
    except Exception as e:
        logger.warning(
            "[arq] Failed to enqueue update_apikey_usage for api_key_id=%s: %s",
            api_key_id, e,
        )
