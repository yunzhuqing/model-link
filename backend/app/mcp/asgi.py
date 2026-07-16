"""
ASGI composite for mounting the MCP HTTP handler alongside the Quart app.

Kept in a side-effect-free module (no Quart app construction at import time)
so it can be imported and unit-tested in isolation.
"""
from __future__ import annotations

from typing import Callable

from app.mcp.server import MCP_HTTP_PATH


class CompositeASGI:
    """
    ASGI dispatcher: ``/mcp`` → MCP HTTP handler, everything else → Quart.

    Lifespan events are forwarded to the Quart app (Quart owns
    before_serving/after_serving, which start/stop the MCP session manager).
    """

    def __init__(self, quart_app, mcp_http: Callable):
        self._quart = quart_app
        self._mcp = mcp_http

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path") or ""
            if path == MCP_HTTP_PATH or path.startswith(MCP_HTTP_PATH + "/"):
                await self._mcp(scope, receive, send)
                return
        await self._quart(scope, receive, send)

    def __getattr__(self, name):
        # 让 app.run / app.config 等仍可用 (dev 启动、外部自省)。
        return getattr(self._quart, name)
