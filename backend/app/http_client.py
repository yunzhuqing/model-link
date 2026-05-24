"""
HTTPX 客户端工厂 (HTTP Client Factory)

统一所有 httpx.AsyncClient 的连接池/超时配置,避免散落在各 provider 的硬编码。
默认值在 _DEFAULTS 中维护,所有 HTTPX_* 环境变量可覆盖。

典型用法:
    from app.http_client import make_async_client, get_shared_client

    # 长连接 provider client(每个 provider 实例一份,需绑 headers)
    self._client = make_async_client(headers=self.config.get_headers())

    # 一次性短调用(推荐:共享全局 client,timeout 传给单次请求)
    client = await get_shared_client()
    resp = await client.post(url, json=data, headers=headers, timeout=60)

    # 需要 follow_redirects 的下载场景
    client = await get_shared_redirect_client()
    resp = await client.get(url, timeout=300)

    # 模块级共享 client,使用专用 env override
    _media_client = make_async_client(scope="MEDIA")  # 读 HTTPX_MEDIA_*
"""
import asyncio
import os
from typing import Optional, Union

import httpx


_DEFAULTS = {
    "MAX_CONNECTIONS": 10000,
    "MAX_KEEPALIVE": 200,
    "KEEPALIVE_EXPIRY": 30.0,
    "CONNECT_TIMEOUT": 10.0,
    "READ_TIMEOUT": 1200.0,
    "WRITE_TIMEOUT": 1200.0,
    "POOL_TIMEOUT": 10.0,
}


def _env(scope: Optional[str], key: str, default):
    """按 scope 读 env,scope 优先于全局。

    scope="MEDIA", key="MAX_CONNECTIONS" → 先读 HTTPX_MEDIA_MAX_CONNECTIONS,
    再读 HTTPX_MAX_CONNECTIONS,最后回落到 default。
    """
    if scope:
        scoped = os.getenv(f"HTTPX_{scope}_{key}")
        if scoped is not None:
            return scoped
    return os.getenv(f"HTTPX_{key}", default)


def get_default_limits(scope: Optional[str] = None) -> httpx.Limits:
    return httpx.Limits(
        max_connections=int(_env(scope, "MAX_CONNECTIONS", _DEFAULTS["MAX_CONNECTIONS"])),
        max_keepalive_connections=int(_env(scope, "MAX_KEEPALIVE", _DEFAULTS["MAX_KEEPALIVE"])),
        keepalive_expiry=float(_env(scope, "KEEPALIVE_EXPIRY", _DEFAULTS["KEEPALIVE_EXPIRY"])),
    )


def get_default_timeout(scope: Optional[str] = None) -> httpx.Timeout:
    return httpx.Timeout(
        connect=float(_env(scope, "CONNECT_TIMEOUT", _DEFAULTS["CONNECT_TIMEOUT"])),
        read=float(_env(scope, "READ_TIMEOUT", _DEFAULTS["READ_TIMEOUT"])),
        write=float(_env(scope, "WRITE_TIMEOUT", _DEFAULTS["WRITE_TIMEOUT"])),
        pool=float(_env(scope, "POOL_TIMEOUT", _DEFAULTS["POOL_TIMEOUT"])),
    )


def make_async_client(
    *,
    timeout: Optional[Union[httpx.Timeout, float, int]] = None,
    limits: Optional[httpx.Limits] = None,
    scope: Optional[str] = None,
    **kwargs,
) -> httpx.AsyncClient:
    """构造一个统一配置的 httpx.AsyncClient。

    Args:
        timeout: 显式 timeout(httpx.Timeout / 秒数);为 None 时使用 scope 默认值。
        limits: 显式 limits;为 None 时使用 scope 默认值。
        scope: 配置作用域(如 "MEDIA"、"POLL"),影响 env 查找前缀。
        **kwargs: 透传给 httpx.AsyncClient(如 headers / follow_redirects / verify)。
    """
    if timeout is None:
        timeout = get_default_timeout(scope)
    elif isinstance(timeout, (int, float)):
        # 兼容旧调用 httpx.AsyncClient(timeout=60) 的写法:仅设置 read,其它保留 scope 默认
        base = get_default_timeout(scope)
        timeout = httpx.Timeout(
            connect=base.connect,
            read=float(timeout),
            write=base.write,
            pool=base.pool,
        )

    if limits is None:
        limits = get_default_limits(scope)

    return httpx.AsyncClient(timeout=timeout, limits=limits, **kwargs)


def log_effective_config(logger) -> None:
    """启动时打印当前生效的默认 limits/timeout,便于运维确认。"""
    limits = get_default_limits()
    timeout = get_default_timeout()
    logger.info(
        "httpx defaults: max_connections=%s max_keepalive=%s keepalive_expiry=%s "
        "connect=%.1fs read=%.1fs write=%.1fs pool=%.1fs",
        limits.max_connections,
        limits.max_keepalive_connections,
        limits.keepalive_expiry,
        timeout.connect,
        timeout.read,
        timeout.write,
        timeout.pool,
    )


# =============================================================================
# 全局共享 client (Shared Singletons)
#
# 用于一次性短调用场景:避免每次 async with 都新建 client/TLS handshake/连接池。
# httpx.AsyncClient 内部按 (scheme, host, port) 分桶管理连接,跨域名共享安全。
# 调用方应在 .post/.get 时传 timeout,而不是绑在 client 上。
# 进程退出前必须调用 close_all_shared_clients() 释放连接。
# =============================================================================

_shared_client: Optional[httpx.AsyncClient] = None
_shared_redirect_client: Optional[httpx.AsyncClient] = None
_shared_client_lock = asyncio.Lock()


async def get_shared_client() -> httpx.AsyncClient:
    """全局共享 AsyncClient(不跟随重定向)。

    用于绝大多数 API 调用 —— LLM 上游、控制平面、轮询。
    headers 在每次 .post(...)/.get(...) 时传入,client 本身不绑 header。
    """
    global _shared_client
    if _shared_client is None:
        async with _shared_client_lock:
            if _shared_client is None:
                _shared_client = make_async_client()
    return _shared_client


async def get_shared_redirect_client() -> httpx.AsyncClient:
    """全局共享 AsyncClient(follow_redirects=True)。

    用于需要跟随 302 的场景:下载用户媒体、视频文件、外部 OEM 服务等。
    与 get_shared_client 分开,避免误把重定向行为带给 API 调用。
    """
    global _shared_redirect_client
    if _shared_redirect_client is None:
        async with _shared_client_lock:
            if _shared_redirect_client is None:
                _shared_redirect_client = make_async_client(follow_redirects=True)
    return _shared_redirect_client


async def close_all_shared_clients() -> None:
    """关闭所有共享 client。应在 app shutdown hook 中调用。"""
    global _shared_client, _shared_redirect_client
    async with _shared_client_lock:
        if _shared_client is not None:
            await _shared_client.aclose()
            _shared_client = None
        if _shared_redirect_client is not None:
            await _shared_redirect_client.aclose()
            _shared_redirect_client = None


class _SharedClientContext:
    """async context manager that yields a shared client without closing it.

    用于把现有的 ``async with make_async_client(...) as client:`` 调用平滑迁移到
    共享 client,而不必 dedent 大段代码 —— ``__aexit__`` 不调用 ``aclose()``。
    """

    __slots__ = ("_factory", "_client")

    def __init__(self, factory):
        self._factory = factory
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> httpx.AsyncClient:
        self._client = await self._factory()
        return self._client

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        # Intentionally do not aclose — the client is shared and lifetime-managed
        # by close_all_shared_clients() at app shutdown.
        self._client = None


def shared_client() -> _SharedClientContext:
    """``async with shared_client() as client:`` —— 借用全局共享 client,退出时不关闭。"""
    return _SharedClientContext(get_shared_client)


def shared_redirect_client() -> _SharedClientContext:
    """``async with shared_redirect_client() as client:`` —— follow_redirects 版,退出时不关闭。"""
    return _SharedClientContext(get_shared_redirect_client)
