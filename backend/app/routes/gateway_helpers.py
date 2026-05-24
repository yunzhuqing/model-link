"""
Shared helper functions and singletons for gateway route modules.

Extracted from gateway.py to be reusable by embeddings, images, rerank, and
other gateway sub-modules.
"""
import asyncio
from datetime import datetime
from typing import Optional, Tuple
import logging
import re
import os

from quart import request, g
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from jose import JWTError, jwt

from app import get_db_session
from app.models import ApiKey, User
from app.middleware.gateway_service import GatewayService
from app.request_context import AuthContext
from app.utils import json_loads

logger = logging.getLogger("gateway")

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"

# Key on `flask.g` carrying the provider_id parsed from `sk-xxx-{providerId}`.
G_API_KEY_PROVIDER_ID = "api_key_provider_id"

# Global service instance shared across all gateway modules
_gateway_service = GatewayService()


async def _parse_json_body():
    """Parse Quart request body as JSON, tolerating non-standard client input.

    Tries standard json.loads first, falls back to demjson3 for:
    - Python-style \\xNN hex escapes
    - Raw control characters in strings
    """
    raw = await request.get_data()
    text = raw.decode("utf-8", errors="replace")
    try:
        return json_loads(text)
    except Exception as e:
        logger.warning(
            "_parse_json_body failed: %s | body preview: %.200r",
            e, text[:200],
        )
        return None


def _log_error(endpoint: str, status_code: int, detail: str, extra: Optional[dict] = None, exc_info: bool = False) -> None:
    """Log gateway errors with consistent format."""
    log_data = {
        "endpoint": endpoint,
        "status_code": status_code,
        "detail": detail,
    }
    if extra:
        log_data.update(extra)

    extra_str = " ".join(f"{k}={v}" for k, v in log_data.items())

    if 500 <= status_code < 600:
        logger.error(f"[gateway] {endpoint} error: {detail} | {extra_str}", exc_info=exc_info)
    elif 400 <= status_code < 500:
        logger.error(f"[gateway] {endpoint} client error: {detail} | {extra_str}", exc_info=exc_info)


def _build_error_context(auth_ctx: Optional[AuthContext], model_name: Optional[str] = None,
                        provider_id: Optional[int] = None,
                        provider_name: Optional[str] = None) -> dict:
    """Build a consistent error context dict with api_key and model info.

    The API key value is truncated for security (first 8 chars only).
    """
    ctx: dict = {}
    if model_name:
        ctx["model"] = model_name
    if auth_ctx and auth_ctx.api_key_id is not None:
        if auth_ctx.api_key_raw:
            ctx["apikey_preview"] = auth_ctx.api_key_raw[:8] + "..."
        ctx["apikey_name"] = auth_ctx.api_key_name or "N/A"
        ctx["apikey_id"] = auth_ctx.api_key_id
        if auth_ctx.user_id:
            ctx["user_id"] = auth_ctx.user_id
        if auth_ctx.api_key_group_id:
            ctx["group_id"] = auth_ctx.api_key_group_id
    # Resolved provider (explicit) takes precedence over API-key-suffix override
    if provider_id is not None:
        ctx["provider_id"] = provider_id
        if provider_name:
            ctx["provider_name"] = provider_name
    else:
        g_provider_id = g.get(G_API_KEY_PROVIDER_ID, None)
        if g_provider_id is not None:
            ctx["provider_id"] = g_provider_id
    return ctx


def _check_allowed_models(auth_ctx: Optional[AuthContext], model_name: str) -> Optional[dict]:
    """Check if the API key's allowed_models list permits access to this model.

    Returns None if access is allowed, or an error dict if the model is not in
    the allowed list.
    """
    if auth_ctx is None or auth_ctx.api_key_id is None:
        return None
    allowed = auth_ctx.allowed_models
    if not allowed:
        return None
    if model_name in allowed:
        return None
    return {
        'detail': f"Model '{model_name}' is not allowed for this API key. "
                  f"Allowed models: {', '.join(allowed)}"
    }


def _build_auth_context_from_api_key(api_key: ApiKey, provider_id_override: Optional[int]) -> AuthContext:
    """Extract plain primitives from an ApiKey ORM row into AuthContext."""
    user_name: Optional[str] = None
    user_id: Optional[int] = None
    group_name: Optional[str] = None
    if api_key.user:
        user_name = api_key.user.username
        user_id = api_key.user.id
    if api_key.group:
        group_name = api_key.group.name

    return AuthContext(
        user_id=user_id or api_key.user_id,
        user_name=user_name,
        api_key_id=api_key.id,
        api_key_raw=api_key.key,
        api_key_name=api_key.name,
        api_key_group_id=api_key.group_id,
        api_key_group_name=group_name,
        api_key_workspace_id=getattr(api_key, 'workspace_id', None) or (
            getattr(api_key.group, 'workspace_id', None) if api_key.group else None
        ),
        api_key_rpm=getattr(api_key, 'rpm', None),
        api_key_tpm=getattr(api_key, 'tpm', None),
        unlimited_budget=bool(api_key.unlimited_budget),
        allowed_models=list(api_key.allowed_models) if api_key.allowed_models else None,
        expires_at=api_key.expires_at,
        is_active=bool(api_key.is_active),
        provider_id_override=provider_id_override,
    )


async def _async_update_apikey_usage(api_key_id: int) -> None:
    """Fire-and-forget background task: bump last_used_at + request_count.

    Runs in its own short-lived DB session so the request path never blocks on
    this write. Failures are logged but never surface to the caller.
    """
    try:
        async with get_db_session() as s:
            await s.execute(
                update(ApiKey)
                .where(ApiKey.id == api_key_id)
                .values(
                    last_used_at=datetime.utcnow(),
                    request_count=ApiKey.request_count + 1,
                )
            )
            await s.commit()
    except Exception as e:
        logger.warning(f"[auth] async last_used_at/request_count update failed: {e}")


async def get_current_user_or_api_key() -> Tuple[Optional[AuthContext], Optional[dict], int]:
    """Authenticate via either JWT token, API key, or Anthropic x-api-key header.

    Returns:
        (auth_ctx, error_dict, status_code)

    On success: (AuthContext, None, 200).
    On failure: (None, {'detail': ...}, 4xx).

    No DB session is held across this call's lifetime. last_used_at /
    request_count updates are dispatched as fire-and-forget background tasks.
    """
    auth_header = request.headers.get('Authorization')
    x_api_key = request.headers.get('x-api-key')

    if not auth_header and not x_api_key:
        return None, {'detail': 'Not authenticated'}, 401

    token = x_api_key or auth_header

    if token and token.lower().startswith('bearer '):
        token = token[7:].strip()

    # Parse provider ID suffix from API key (sk-xxxxxxxxx-{providerId})
    provider_id_override = None
    _m = re.fullmatch(r'(.+)-(\d+)$', token)
    if _m:
        token = _m.group(1)
        provider_id_override = int(_m.group(2))
        setattr(g, G_API_KEY_PROVIDER_ID, provider_id_override)

    from app.cache import get_async_cache
    cache = get_async_cache()
    cached_info = await cache.get_api_key_info(token)

    # ── Cache hit: validate cached info, then do a single read-only DB lookup ──
    if cached_info is not None:
        if not cached_info.get('is_active', True):
            return None, {'detail': 'API key is inactive'}, 401

        expires_at_str = cached_info.get('expires_at')
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at < datetime.utcnow():
                    return None, {'detail': 'API key has expired'}, 401
            except (ValueError, TypeError):
                pass

        is_unlimited = cached_info.get('unlimited_budget', False)
        if not is_unlimited:
            from app.budget_manager import get_async_budget_manager
            # Budget manager will open its own short session if it has to load from DB.
            budget_remaining = await get_async_budget_manager().get_remaining(token)
            if budget_remaining is None:
                logger.warning("Budget remaining is None for API key with unlimited_budget=False, blocking request")
                return None, {'detail': 'API key budget exceeded. Please add more budget to continue.'}, 403
            if float(budget_remaining) <= 0:
                return None, {'detail': 'API key budget exceeded. Please add more budget to continue.'}, 403

        # Read the full ORM row in a short-lived session, then extract.
        async with get_db_session() as session:
            result = await session.execute(
                select(ApiKey)
                .options(selectinload(ApiKey.user), selectinload(ApiKey.group))
                .where(ApiKey.key == token)
            )
            api_key = result.scalars().first()
            if api_key is None:
                # Cache stale: key was removed
                await cache.invalidate_api_key(token)
            else:
                auth_ctx = _build_auth_context_from_api_key(api_key, provider_id_override)

        if cached_info is not None and api_key is not None:
            # Fire-and-forget last_used_at / request_count update
            asyncio.create_task(_async_update_apikey_usage(auth_ctx.api_key_id))
            return auth_ctx, None, 200
        # Otherwise fall through to cache-miss path

    # ── Cache miss: full lookup + populate cache ──
    api_key = None
    async with get_db_session() as session:
        result = await session.execute(
            select(ApiKey)
            .options(selectinload(ApiKey.user), selectinload(ApiKey.group))
            .where(ApiKey.key == token)
        )
        api_key = result.scalars().first()

        if api_key is not None:
            if not api_key.is_active:
                return None, {'detail': 'API key is inactive'}, 401

            if api_key.expires_at and api_key.expires_at < datetime.utcnow():
                return None, {'detail': 'API key has expired'}, 401

            if not api_key.unlimited_budget:
                budget_val = api_key.budget
                if budget_val is not None and budget_val <= 0:
                    return None, {'detail': 'API key budget exceeded. Please add more budget to continue.'}, 403

            auth_ctx = _build_auth_context_from_api_key(api_key, provider_id_override)

            # Populate cache while session is open (reads UsageRecord sum)
            try:
                await _populate_api_key_cache(session, api_key, cache)
            except Exception as _ce:
                logger.debug(f"[cache] Failed to populate API key cache: {_ce}")

    if api_key is not None:
        asyncio.create_task(_async_update_apikey_usage(auth_ctx.api_key_id))
        return auth_ctx, None, 200

    # ── JWT path ──
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get('sub')
        if not username:
            logger.warning(f"Invalid token (no sub)")
            return None, {'detail': 'Invalid token'}, 401
    except JWTError:
        logger.warning("Invalid token or API key")
        return None, {'detail': 'Invalid token or API key'}, 401

    async with get_db_session() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalars().first()
        if not user:
            return None, {'detail': 'User not found'}, 401
        return AuthContext(
            user_id=user.id,
            user_name=user.username,
            provider_id_override=provider_id_override,
        ), None, 200


async def _populate_api_key_cache(session, api_key: ApiKey, cache) -> None:
    """Compute the current budget_used from UsageRecord and populate the cache.

    Runs inside the provided session.
    """
    import hashlib
    from app.models import UsageRecord
    from sqlalchemy import func as db_func

    budget_used = 0.0
    if api_key.budget is not None:
        key_hash = hashlib.sha256(api_key.key.encode()).hexdigest()
        result = await session.execute(
            select(db_func.coalesce(db_func.sum(UsageRecord.actual_amount_usd), 0))
            .where(UsageRecord.api_key_hash == key_hash)
        )
        row = result.scalar()
        budget_used = float(row or 0)

    info = cache.build_api_key_cache_info(api_key, budget_used=budget_used)
    await cache.set_api_key_info(api_key.key, info)

    if not api_key.unlimited_budget and api_key.budget is not None:
        from app.budget_manager import get_async_budget_manager
        await get_async_budget_manager().set_remaining(api_key.key, float(api_key.budget))
