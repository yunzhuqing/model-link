"""
Entry point for Quart application.

Run via uvicorn (ASGI mode)::

    uvicorn app.main:app --host 0.0.0.0 --port 8000

Or run directly (``python app/main.py``) for development.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Disable uvloop — it raises RuntimeError on closed TCP transports
# (e.g. stale DB connections) instead of buffering writes lazily.
# AIOMySQL never gets a chance to convert the error to DBAPIError,
# so SQLAlchemy's _do_ping_w_event can't catch it.
import sys


class _BlockUVLoopFinder:
    def find_spec(self, fullname, path, target=None):
        if fullname == "uvloop":
            raise ModuleNotFoundError("uvloop is blocked", name="uvloop")
        return None


sys.meta_path.insert(0, _BlockUVLoopFinder())

from app import create_app, db

app = create_app()

# Create tables if they don't exist (sync context, before server starts).
#
# Quart 0.20's app_context() is async-only, but Flask-SQLAlchemy's db.create_all()
# needs Flask's synchronous current_app proxy (via werkzeug's ContextVar).
# We set the ContextVar directly to bridge the gap.
from flask.globals import _cv_app
from flask.ctx import AppContext

_token = _cv_app.set(AppContext(app))
try:
    db.create_all()
finally:
    _cv_app.reset(_token)


# ---------------------------------------------------------------------------
# MCP server (HTTP transport) — 挂载到 /mcp，随网关上线。
#
# 由 ASGI composite 在网关根 app 之上按路径分发：/mcp → MCP handler，
# 其余 → Quart。Quart 仍独占 lifespan（before/after_serving），MCP 的会话
# 管理器通过 Quart 的 before_serving/after_serving 启停。鉴权见
# app/mcp/server.py 的 build_mcp_http()。
# ---------------------------------------------------------------------------
from app.mcp.server import build_mcp_http  # noqa: E402
from app.mcp.asgi import CompositeASGI  # noqa: E402

logger = logging.getLogger("gateway")

_mcp_http_handler, _mcp_session_manager = build_mcp_http()
_mcp_session_task: asyncio.Task | None = None
_mcp_session_started: asyncio.Event | None = None


async def _mcp_session_runner():
    """Run the MCP session manager for the whole app lifetime (single task).

    ``session_manager.run()`` uses an anyio task group whose cancel scope is bound
    to the task that enters it. Quart runs ``before_serving`` / ``after_serving``
    as separate tasks, so the context manager must be entered AND exited within
    one dedicated long-lived task — spawned at startup, cancelled at shutdown.
    """
    global _mcp_session_started
    try:
        async with _mcp_session_manager.run():
            _mcp_session_started.set()
            # Keep the context open until after_serving cancels this task.
            await asyncio.Event().wait()
    except asyncio.CancelledError:
        # Expected on shutdown — propagates out of the `async with`, which exits
        # the session manager's task group cleanly (same task).
        raise


@app.before_serving
async def _start_mcp_session():
    global _mcp_session_task, _mcp_session_started
    if _mcp_session_manager is None:
        return
    _mcp_session_started = asyncio.Event()
    _mcp_session_task = asyncio.create_task(_mcp_session_runner())
    # Wait until the session manager has actually started, or surface an early
    # failure from the runner (so startup fails fast instead of hanging).
    ready = asyncio.create_task(_mcp_session_started.wait())
    done, _ = await asyncio.wait(
        {_mcp_session_task, ready}, return_when=asyncio.FIRST_COMPLETED
    )
    if _mcp_session_task in done:
        ready.cancel()
        if (exc := _mcp_session_task.exception()):
            raise exc
    else:
        ready.cancel()


@app.after_serving
async def _stop_mcp_session():
    global _mcp_session_task
    if _mcp_session_task is None:
        return
    _mcp_session_task.cancel()
    try:
        await _mcp_session_task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("MCP session manager shutdown error")
    _mcp_session_task = None


# 覆盖模块级 ``app``：对外仍是 ``app.main:app``，uvicorn 直接调用此 ASGI。
# Quart 应用实例保留在 ``_quart_app``，生命周期与蓝图注册不变。
_quart_app = app
app = CompositeASGI(_quart_app, _mcp_http_handler)


if __name__ == '__main__':
    # Run development server
    _quart_app.run(
        host=os.getenv('HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', 8000)),
        debug=os.getenv('DEBUG', 'true').lower() == 'true'
    )
