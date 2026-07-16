"""
Model Context Protocol server — 火山引擎 Seedance 封控原因查询。

以 HTTP transport 随网关上线：作为 ASGI 子应用挂载进 Quart 网关，端点
``/mcp``，网关启动即上线，无需单独进程。由 ``app.main`` 的 CompositeASGI
按路径分发并管理 session manager 生命周期。

暴露两个工具：
  - ``get_seedance_block_reasons``: 根据 id/type 查询封控原因。
  - ``list_volcengine_providers``: 列出可用的火山引擎 Provider (供定位 provider_id)。

鉴权：复用网关的用户 API Key（``ml_api_keys``）。客户端以
``Authorization: Bearer <用户申请的 apikey>`` 携带，服务端只校验 key 是否
启用 (``is_active``) 且未过期 (``expires_at``)，**不**扣 budget、**不**记
request_count / last_used_at（MCP 是运维/调试用的内部工具调用，不消耗 LLM
token）。鉴权失败返回 401。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Awaitable, Callable, Optional, Tuple

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import (
    StreamableHTTPSessionManager,
)

from app.mcp.moderation import (
    fetch_block_reasons,
    VALID_TYPES,
)

logger = logging.getLogger("gateway")

mcp = FastMCP("model-link-seedance")

# HTTP transport 端点路径（由 app.main 的 ASGI composite 按此路径分发）。
MCP_HTTP_PATH = "/mcp"

# DB 引擎由网关在 before_serving 中初始化 (app._async_engine)，此处复用，
# 仅在尚未初始化时兜底初始化一次（正常 HTTP 模式下不会走到兜底分支）。
_db_initialized = False


async def _ensure_db() -> None:
    """确保异步 DB 引擎已初始化。

    HTTP 模式下网关已在 ``before_serving`` 中初始化引擎 (``app._async_engine``
    非 None)，此处直接复用；仅在尚未初始化时兜底初始化一次（正常流程不会走到）。
    """
    global _db_initialized
    if _db_initialized:
        return
    from app import _async_engine, _init_async_engine

    if _async_engine is None:
        await _init_async_engine()
    _db_initialized = True


def _group_id_from_ctx(ctx: Context) -> Optional[int]:
    """从 MCP 请求上下文取出 apikey 所属分组的 id。

    ``make_guarded_asgi`` 在校验 apikey 通过后，把 key 所属 ``group_id`` 写入
    ASGI ``scope["mcp_group_id"]``；FastMCP 的 streamable HTTP transport 会把
    当前 POST 对应的 Starlette ``Request`` 挂到 ``RequestContext.request``，
    故工具内可经 ``ctx`` 取回该分组 id，从而将 Provider 查询/凭证解析限定在
    apikey 所属分组内。

    非 HTTP 调用 (stdio / 测试) 下取不到 → 返回 ``None``，调用方回退到不按
    分组过滤的行为。
    """
    try:
        request_context = ctx.request_context
    except (ValueError, LookupError):
        return None
    request = getattr(request_context, "request", None)
    scope = getattr(request, "scope", None)
    if not isinstance(scope, dict):
        return None
    return scope.get("mcp_group_id")


@mcp.tool()
async def get_seedance_block_reasons(
    id: str,
    type: str,
    provider_id: Optional[int] = None,
    provider_name: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """
    查询火山引擎 Seedance 内容被风控封控的原因。

    Args:
        id: 火山引擎任务 ID / 素材库 ID / 推理请求 ID。
        type: ID 的类型，取值：asset_id | task_id | request_id。
        provider_id: 可选，指定使用哪个火山引擎 Provider 的 AK/SK。
            必须属于当前 apikey 所属分组，否则视为不存在。
        provider_name: 可选，按名称指定 Provider (与 provider_id 二选一)。
            同样受分组约束。若两者都不传，则在当前分组内使用环境变量
            MCP_VOLCENGINE_PROVIDER_ID 或第一条已配置 AK/SK 的火山引擎 Provider。

    Returns:
        封控原因的可读文本；无封控时返回 "未检测到封控"。
    """
    await _ensure_db()

    group_id = _group_id_from_ctx(ctx)

    result = await fetch_block_reasons(
        id=id,
        type=type,
        provider_id=provider_id,
        provider_name=provider_name,
        group_id=group_id,
    )

    block_reasons = result["block_reasons"]
    provider = result["provider"]

    lines = [
        f"Provider: {provider['name']} (id={provider['id']})",
        f"Query: type={type} id={id}",
    ]
    if not block_reasons:
        lines.append("结果: 未检测到封控 (block_reasons 为空)。")
    else:
        lines.append(f"结果: 检测到 {len(block_reasons)} 条封控原因：")
        for i, item in enumerate(block_reasons, 1):
            label = item.get("label", "")
            sub_label = item.get("sub_label", "")
            detail = item.get("detail", "")
            lines.append(f"  {i}. [{label}/{sub_label}] {detail}")

    # 附带原始 JSON，便于需要时查看完整字段。
    lines.append("")
    lines.append("原始响应:")
    lines.append(json.dumps(result["raw"], ensure_ascii=False, indent=2))

    return "\n".join(lines)


@mcp.tool()
async def list_volcengine_providers(ctx: Context = None) -> str:
    """
    列出数据库中可用的火山引擎 Provider，便于定位 provider_id / provider_name。

    只列出当前 apikey 所属分组下的 Provider。标注每个 Provider 是否已配置
    AK/SK (能否用于封控查询)。
    """
    from sqlalchemy import select
    from app import get_db_session
    from app.models import Provider

    await _ensure_db()

    group_id = _group_id_from_ctx(ctx)

    async with get_db_session() as session:
        stmt = (
            select(Provider)
            .where(Provider.type == "volcengine", Provider.is_active.is_(True))
        )
        if group_id is not None:
            stmt = stmt.where(Provider.group_id == group_id)
        stmt = stmt.order_by(Provider.id.asc())
        result = await session.execute(stmt)
        providers = result.scalars().all()

    if not providers:
        scope_hint = (
            f"当前 apikey 所属分组 (id={group_id}) 下"
            if group_id is not None
            else ""
        )
        return f"未找到{scope_hint}启用的火山引擎 Provider。请先在管理后台配置。"

    lines = ["可用的火山引擎 Provider:"]
    for p in providers:
        extra = p.extra_config or {}
        has_ak = bool(extra.get("ark_access_key")) and bool(extra.get("ark_secret_key"))
        region = extra.get("ark_region", "cn-beijing")
        flag = "✓ 可用于封控查询" if has_ak else "✗ 缺少 AK/SK"
        lines.append(f"  - id={p.id} name={p.name} region={region} [{flag}]")
    return "\n".join(lines)


# =============================================================================
# HTTP transport — 随网关上线
# =============================================================================

def _get_header(scope: dict, name: str) -> str:
    """从 ASGI scope 的 headers 中读取指定 header（小写匹配）。"""
    for key, value in scope.get("headers", []):
        if key.decode("latin-1").lower() == name.lower():
            return value.decode("latin-1")
    return ""


async def _send_json(send: Callable[[dict], Awaitable[None]], status: int, body: dict) -> None:
    """直接通过 ASGI send 输出一个 JSON 响应（用于鉴权失败 / 端点禁用）。"""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                             (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})


# apikey 末尾的 ``-{providerId}`` 后缀（网关用于 provider 覆盖），鉴权时需剥离
# 后再查 ``ml_api_keys.key``，否则带后缀的 key 查不到。
_PROVIDER_ID_SUFFIX_RE = re.compile(r"(.+)-(\d+)$")


async def _verify_apikey(raw_token: str) -> Tuple[bool, str, Optional[int]]:
    """校验用户 API Key 是否启用且未过期。

    复用网关的 apikey 缓存 (``get_async_cache().get_api_key_info``)，cache miss
    时回落 DB 查 ``ml_api_keys``。**只**做 active / expires_at 校验，不扣 budget、
    不 enqueue_apikey_usage、不更新 last_used_at / request_count（MCP 是内部
    工具调用，不消耗 LLM token）。

    Returns:
        ``(ok, detail, group_id)``：``ok=True`` 表示鉴权通过，``group_id`` 为该
        apikey 所属分组 id (用于把 MCP 工具内的 Provider 查询限定在该分组)；
        鉴权失败时 ``group_id`` 为 ``None``，``detail`` 为失败原因。
    """
    token = raw_token.strip()
    if not token:
        return False, "missing api key", None

    # 剥离 ``-{providerId}`` 后缀，与网关 get_current_user_or_api_key 一致。
    m = _PROVIDER_ID_SUFFIX_RE.fullmatch(token)
    if m:
        token = m.group(1)

    await _ensure_db()

    from app.cache import get_async_cache
    from app.models import ApiKey
    from sqlalchemy import select
    from app import get_db_session

    cache = get_async_cache()
    cached_info = await cache.get_api_key_info(token)

    # ── Cache hit：仅校验 active / expires_at ──
    if cached_info is not None:
        if not cached_info.get("is_active", True):
            return False, "api key is inactive", None
        expires_at_str = cached_info.get("expires_at")
        if expires_at_str:
            try:
                if datetime.fromisoformat(expires_at_str) < datetime.utcnow():
                    return False, "api key has expired", None
            except (ValueError, TypeError):
                pass
        return True, "", cached_info.get("group_id")

    # ── Cache miss：DB 兜底查询 ──
    async with get_db_session() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.key == token))
        api_key = result.scalars().first()
        if api_key is None:
            return False, "invalid api key", None
        if not api_key.is_active:
            return False, "api key is inactive", None
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return False, "api key has expired", None
        group_id = api_key.group_id

    # 不填充缓存：避免触发 UsageRecord 聚合查询等副作用；网关的 LLM 请求会在
    # 使用同一 key 时自行填充。MCP 为低频内部调用，DB 直查可接受。
    return True, "", group_id


def make_guarded_asgi(handler: Callable) -> Callable:
    """
    用网关用户 API Key 包装 MCP HTTP ASGI handler。

    - 路径非 ``/mcp`` → 404（保护性校验，正常流量由 app.main composite 已分发）。
    - 无 ``Authorization: Bearer <apikey>`` 或 key 无效/过期 → 401。
    - 鉴权通过 → 将 apikey 所属 ``group_id`` 注入 ASGI ``scope["mcp_group_id"]``，
      供工具经 MCP ``Context`` 取回以限定分组范围，再转发给底层 handler。

    只校验 key 是否启用且未过期，不计费、不计 request_count / last_used_at。
    """

    async def guarded_asgi(scope, receive, send):
        path = (scope.get("path") or "").rstrip("/")
        if path != MCP_HTTP_PATH:
            await _send_json(send, 404, {"error": "not found"})
            return

        auth = _get_header(scope, "authorization")
        token = ""
        if auth.startswith("Bearer "):
            token = auth[len("Bearer "):]

        ok, detail, group_id = await _verify_apikey(token)
        if not ok:
            # 不打印原始 key，仅记录长度与失败原因，便于排障。
            logger.warning(
                "MCP /mcp auth failed: detail=%s token_len=%d has_header=%s",
                detail, len(token), bool(auth),
            )
            await _send_json(send, 401, {"error": "unauthorized", "detail": detail})
            return

        # 把 apikey 所属分组 id 注入 scope，工具内经 Context 取回，用以把
        # Provider 查询/凭证解析限定在该分组。group_id 为 None (理论上不会)
        # 时不写入，工具回退到不按分组过滤的行为。
        if group_id is not None:
            scope["mcp_group_id"] = group_id

        await handler(scope, receive, send)

    return guarded_asgi


def build_mcp_http() -> Tuple[Callable, StreamableHTTPSessionManager]:
    """
    构建随网关上线的 MCP HTTP transport。

    返回 ``(asgi_app, session_manager)``：
      - ``asgi_app``: 处理 ``/mcp`` 的 ASGI app（已套上 apikey 鉴权）。
      - ``session_manager``: 需在 Quart 的 ``before_serving`` / ``after_serving``
        中通过 ``session_manager.run()`` 启停（由 app.main 负责）。

    鉴权：复用网关用户 API Key (``ml_api_keys``)，客户端以
    ``Authorization: Bearer <用户申请的 apikey>`` 携带。只校验启用 + 未过期，
    不计费、不计 request_count / last_used_at。
    """
    # 调用一次 streamable_http_app() 以懒初始化 session_manager。
    mcp.streamable_http_app()
    session_manager = mcp.session_manager
    handler = StreamableHTTPASGIApp(session_manager)
    guarded = make_guarded_asgi(handler)
    return guarded, session_manager
