"""Per-task duration tracing and long-running task watchdog.

Activated via env vars (both optional):

    TASK_TRACE_SLOW=1.0         # seconds; tasks finishing slower than this
                                #   get a "slow task" log on completion.
    TASK_TRACE_WATCHDOG=1.0     # seconds; if set, a background coroutine
                                #   scans every interval and, for tasks
                                #   alive longer than TASK_TRACE_SLOW,
                                #   prints their current await stack
                                #   once (so we see where they are stuck).

Both are no-ops in production unless enabled.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback

logger = logging.getLogger("task_trace")

_THRESHOLD = 1.0
_WATCHDOG_TASK_NAME = "task_trace_watchdog"


def _pool_status() -> str:
    """Snapshot of the async DB pool — useful when a slow task is suspected
    of being blocked on `async with get_db_session()`."""
    try:
        import app as _app_pkg
        engine = getattr(_app_pkg, "_async_engine", None)
        if engine is None:
            return "<engine not initialised>"
        pool = engine.pool
        # SQLAlchemy's QueuePool exposes these; AsyncAdaptedQueuePool inherits.
        return (
            f"pool size={pool.size()} checked_out={pool.checkedout()} "
            f"overflow={pool.overflow()} checked_in={pool.checkedin()}"
        )
    except Exception as e:
        return f"<pool inspect failed: {e!r}>"


class _TracedTask(asyncio.Task):
    """Asyncio Task subclass that records creation time and origin stack."""

    def __init__(self, coro, *args, **kwargs):
        super().__init__(coro, *args, **kwargs)
        self._t0 = time.perf_counter()
        # Skip the last two frames: this __init__ and the factory lambda.
        self._origin = "".join(traceback.format_stack(limit=15)[:-2])
        self._alerted = False
        self.add_done_callback(_on_task_done)


def _on_task_done(task: asyncio.Task) -> None:
    dt = time.perf_counter() - getattr(task, "_t0", time.perf_counter())
    if dt < _THRESHOLD:
        return
    if task.get_name() == _WATCHDOG_TASK_NAME:
        return  # the watchdog is intentionally long-lived
    coro = task.get_coro()
    qual = getattr(coro, "__qualname__", repr(coro))
    if task.cancelled():
        exc_repr = "<cancelled>"
    else:
        exc = task.exception()
        exc_repr = repr(exc) if exc else "None"
    origin = getattr(task, "_origin", "<unknown>")
    logger.warning(
        "slow task %.3fs name=%s coro=%s exc=%s\n--- created at ---\n%s",
        dt,
        task.get_name(),
        qual,
        exc_repr,
        origin,
    )


async def _watchdog(interval: float) -> None:
    """Periodically dump stacks of tasks running longer than _THRESHOLD."""
    self_task = asyncio.current_task()
    while True:
        try:
            await asyncio.sleep(interval)
            now = time.perf_counter()
            for t in asyncio.all_tasks():
                if t is self_task or t.done():
                    continue
                t0 = getattr(t, "_t0", None)
                if t0 is None:
                    continue
                age = now - t0
                if age < _THRESHOLD or getattr(t, "_alerted", False):
                    continue
                t._alerted = True  # only alert once per task
                frames = t.get_stack(limit=20)
                if frames:
                    rendered = "".join(traceback.format_stack(frames[0]))
                else:
                    rendered = "<no Python frame — likely in C-level await>\n"
                coro = t.get_coro()
                logger.warning(
                    "long-running task age=%.3fs name=%s coro=%s db_pool=[%s]\n"
                    "--- current stack ---\n%s",
                    age,
                    t.get_name(),
                    getattr(coro, "__qualname__", repr(coro)),
                    _pool_status(),
                    rendered,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("task_trace watchdog error")


def enable(threshold: float, watchdog_interval: float | None = None) -> None:
    """Install the task factory and optionally start the watchdog.

    Must be called from inside a running event loop (e.g. an `app.before_serving`
    hook), because `asyncio.get_running_loop()` requires one.
    """
    global _THRESHOLD
    _THRESHOLD = threshold
    loop = asyncio.get_running_loop()
    loop.set_task_factory(
        lambda loop, coro, **kw: _TracedTask(coro, loop=loop, **kw)
    )
    if watchdog_interval and watchdog_interval > 0:
        loop.create_task(_watchdog(watchdog_interval), name=_WATCHDOG_TASK_NAME)
    logger.info(
        "task tracing enabled (threshold=%.3fs, watchdog=%s)",
        threshold,
        f"{watchdog_interval:.3f}s" if watchdog_interval else "off",
    )
