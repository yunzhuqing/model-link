"""
ARQ worker: background job processor for offloaded DB writes.

Two modes of operation:

1. **Standalone** (separate process):
   ``uv run arq app.arq_worker.WorkerSettings``
   The worker creates its own async DB engine and event loop.

2. **Embedded** (in-process, alongside Quart):
   Set ``ARQ_EMBEDDED_WORKER=true`` and the Quart app will run the worker
   as a background asyncio task, sharing the app's DB session factory.
   This means the service is both producer AND consumer — a job enqueued
   by one instance can be consumed by any instance (including the same one).
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from arq.connections import RedisSettings
from arq.worker import Worker, create_worker
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models import ApiKey

logger = logging.getLogger("arq.worker")

# ── Standalone DB engine (only used when running as a separate process) ─────

_worker_engine = None


def _build_async_db_url() -> str:
    """Build an async database URL from the DATABASE_URL env var."""
    database_url = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db")
    if "+aiomysql" in database_url or "+asyncpg" in database_url or "+aiosqlite" in database_url:
        return database_url
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("mysql+pymysql://"):
        return database_url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    if database_url.startswith("mysql://"):
        return database_url.replace("mysql://", "mysql+aiomysql://", 1)
    if database_url.startswith("sqlite://"):
        return database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return database_url


async def _standalone_startup(ctx: dict) -> None:
    """Standalone mode: create the worker's own async DB engine.

    Populates ``ctx['get_db_session']`` so that job functions can open
    short-lived DB sessions regardless of mode.
    """
    global _worker_engine
    async_url = _build_async_db_url()
    _worker_engine = create_async_engine(
        async_url,
        pool_size=int(os.getenv("SQLALCHEMY_POOL_SIZE", 10)),
        max_overflow=int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", 20)),
        pool_timeout=int(os.getenv("SQLALCHEMY_POOL_TIMEOUT", 30)),
        pool_recycle=int(os.getenv("SQLALCHEMY_POOL_RECYCLE", 600)),
        pool_pre_ping=os.getenv("SQLALCHEMY_POOL_PRE_PING", "true").lower() == "true",
    )
    session_factory = async_sessionmaker(
        _worker_engine, class_=AsyncSession, expire_on_commit=False,
    )
    ctx["get_db_session"] = session_factory
    logger.info("ARQ worker DB engine initialised (standalone): %s", async_url)


async def _standalone_shutdown(_ctx: dict) -> None:
    """Standalone mode: dispose the worker's own async DB engine."""
    global _worker_engine
    if _worker_engine is not None:
        await _worker_engine.dispose()
        _worker_engine = None
        logger.info("ARQ worker DB engine disposed (standalone)")


# ── Job functions ───────────────────────────────────────────────────────────


async def update_apikey_usage(ctx: dict, api_key_id: int) -> None:
    """Update last_used_at and request_count for an API key.

    Retrieves a DB session factory from ``ctx['get_db_session']``, which is
    injected by either the standalone ``startup`` callback or the embedded
    worker setup.  Opens its own short-lived DB session.

    Failures are logged but never re-raised (the job is not retried — these
    stats are eventually reconciled by the usage-sync leader service).
    """
    get_db = ctx.get("get_db_session")
    if get_db is None:
        logger.error(
            "[arq] No get_db_session in worker ctx — cannot process job"
        )
        return

    try:
        async with get_db() as session:
            await session.execute(
                update(ApiKey)
                .where(ApiKey.id == api_key_id)
                .values(
                    last_used_at=datetime.utcnow(),
                    request_count=ApiKey.request_count + 1,
                )
            )
            await session.commit()
    except Exception as e:
        logger.warning(
            "[arq] update_apikey_usage failed for api_key_id=%s: %s",
            api_key_id, e,
        )


# ── Shared helpers ──────────────────────────────────────────────────────────


def _redis_settings() -> RedisSettings:
    url = os.getenv(
        "ARQ_REDIS_URL",
        os.getenv("CACHE_REDIS_URL", "redis://localhost:6379/0"),
    )
    return RedisSettings.from_dsn(url)


# ── Standalone worker settings (for ``arq`` CLI) ────────────────────────────


class WorkerSettings:
    """Settings for the ARQ worker CLI (standalone process).

    Usage: ``uv run arq app.arq_worker.WorkerSettings``

    The worker creates its own async DB engine and runs independently
    from the Quart web process.
    """

    functions = [update_apikey_usage]
    redis_settings = _redis_settings()
    on_startup = _standalone_startup
    on_shutdown = _standalone_shutdown
    queue_name = os.getenv("ARQ_QUEUE_NAME", "arq:queue")
    keep_result = False
    max_jobs = int(os.getenv("ARQ_MAX_JOBS", "10"))
    health_check_key = os.getenv("ARQ_HEALTH_CHECK_KEY", "arq:health")
    health_check_interval = int(os.getenv("ARQ_HEALTH_CHECK_INTERVAL", "30"))
    log_results = False
    poll_delay = float(os.getenv("ARQ_POLL_DELAY", "0.5"))


# ── Embedded worker (in-process, alongside Quart) ───────────────────────────

# Hold a reference to the embedded worker and its asyncio Task so we can
# cancel it cleanly on shutdown.
_embedded_worker: Optional[Worker] = None
_embedded_task: Optional["asyncio.Task[None]"] = None


async def start_embedded_worker(get_db_session) -> Worker:
    """Create and start an ARQ worker embedded in the Quart event loop.

    The worker shares the app's async DB session factory (injected via
    ``ctx['get_db_session']``) so it does NOT create its own engine.

    Returns the :class:`Worker` instance.  Call :func:`stop_embedded_worker`
    on shutdown to cancel the background task and close connections.
    """
    global _embedded_worker, _embedded_task

    _embedded_worker = create_worker(
        WorkerSettings,
        on_startup=None,       # embedded: DB lifecycle managed by the app
        on_shutdown=None,
        ctx={"get_db_session": get_db_session},
        handle_signals=False,  # Quart manages OS signals
    )

    _embedded_task = asyncio.create_task(_embedded_worker.async_run())
    logger.info(
        "ARQ embedded worker started (queue=%s, max_jobs=%s)",
        WorkerSettings.queue_name, WorkerSettings.max_jobs,
    )
    return _embedded_worker


async def stop_embedded_worker() -> None:
    """Stop the embedded ARQ worker and cancel its background task."""
    global _embedded_worker, _embedded_task

    if _embedded_task is not None:
        _embedded_task.cancel()
        try:
            await _embedded_task
        except asyncio.CancelledError:
            pass
        _embedded_task = None

    if _embedded_worker is not None:
        await _embedded_worker.close()
        _embedded_worker = None
        logger.info("ARQ embedded worker stopped")
