"""
Shared helper functions and singletons for gateway route modules.

Extracted from gateway.py to be reusable by embeddings, images, rerank, and
other gateway sub-modules.
"""
from quart import request, g
from datetime import datetime
from typing import Optional
import logging
import re
import os

logger = logging.getLogger("gateway")

from app import db
from app.models import ApiKey, User
from jose import JWTError, jwt

from app.middleware.gateway_service import GatewayService
from app.utils import json_loads

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
    """Log gateway errors with consistent format.

    Args:
        endpoint: The API endpoint name (e.g. 'chat_completions', 'embeddings')
        status_code: HTTP status code of the error response
        detail: Error detail message
        extra: Optional additional context (e.g. model name, api key info, user)
        exc_info: If True, include exception stack trace in the log
    """
    log_data = {
        "endpoint": endpoint,
        "status_code": status_code,
        "detail": detail,
        "request_id": g.get('request_id', '-'),
    }
    if extra:
        log_data.update(extra)

    extra_str = " ".join(f"{k}={v}" for k, v in log_data.items())

    if 500 <= status_code < 600:
        logger.error(f"[gateway] {endpoint} error: {detail} | {extra_str}", exc_info=exc_info)
    elif 400 <= status_code < 500:
        logger.error(f"[gateway] {endpoint} client error: {detail} | {extra_str}", exc_info=exc_info)


def _build_error_context(api_key, model_name: Optional[str] = None,
                        provider_id: Optional[int] = None,
                        provider_name: Optional[str] = None) -> dict:
    """Build a consistent error context dict with api_key and model info.

    The API key value is truncated for security (first 8 chars only).

    provider_id and provider_name, if given, represent the dynamically resolved
    provider. If omitted, falls back to the API-key-suffix override from g.
    """
    ctx: dict = {}
    if model_name:
        ctx["model"] = model_name
    if api_key:
        ctx["apikey_preview"] = (api_key.key[:8] + "...") if api_key.key else "N/A"
        ctx["apikey_name"] = api_key.name or "N/A"
        ctx["apikey_id"] = api_key.id
        if api_key.user_id:
            ctx["user_id"] = api_key.user_id
        if api_key.group_id:
            ctx["group_id"] = api_key.group_id
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


def _check_allowed_models(api_key, model_name: str) -> Optional[dict]:
    """Check if the API key's allowed_models list permits access to this model.

    Returns None if access is allowed, or a (error_dict, status_code) tuple
    if the model is not in the allowed list.
    """
    if api_key is None:
        return None
    allowed = getattr(api_key, 'allowed_models', None)
    if not allowed:
        return None
    if model_name in allowed:
        return None
    return {
        'detail': f"Model '{model_name}' is not allowed for this API key. "
                  f"Allowed models: {', '.join(allowed)}"
    }


def get_current_user_or_api_key():
    """Authenticate via either JWT token, API key, or Anthropic x-api-key header.

    Supported authentication methods:
    1. Authorization: Bearer <token>  (JWT or API key)
    2. Authorization: <token>         (API key without Bearer prefix)
    3. x-api-key: <key>              (Anthropic SDK compatible)

    API key lookups are accelerated by the cache middleware:
    - On cache hit: validates is_active / expires_at from cached data,
      then updates last_used_at / request_count in DB asynchronously.
    - On cache miss: falls back to a DB query and populates the cache.
    """
    auth_header = request.headers.get('Authorization')
    x_api_key = request.headers.get('x-api-key')

    if not auth_header and not x_api_key:
        return None, None, {'detail': 'Not authenticated'}, 401

    token = None
    if x_api_key:
        token = x_api_key
    else:
        token = auth_header

    if token and token.lower().startswith('bearer '):
        token = token[7:].strip()

    # Parse provider ID suffix from API key
    # Format: sk-xxxxxxxxx-{providerId}
    provider_id_override = None
    _m = re.fullmatch(r'(.+)-(\d+)$', token)
    if _m:
        token = _m.group(1)
        provider_id_override = int(_m.group(2))
        setattr(g, G_API_KEY_PROVIDER_ID, provider_id_override)

    # Try cache first for API key authentication
    from app.cache import get_cache
    cache = get_cache()
    cached_info = cache.get_api_key_info(token)

    if cached_info is not None:
        if not cached_info.get('is_active', True):
            return None, None, {'detail': 'API key is inactive'}, 401

        expires_at_str = cached_info.get('expires_at')
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at < datetime.utcnow():
                    return None, None, {'detail': 'API key has expired'}, 401
            except (ValueError, TypeError):
                pass

        is_unlimited = cached_info.get('unlimited_budget', False)
        if not is_unlimited:
            from app.budget_manager import get_budget_manager
            budget_remaining = get_budget_manager().get_remaining(token)
            if budget_remaining is None:
                logger.warning(f"Budget remaining is None for API key with unlimited_budget=False, blocking request")
                return None, None, {'detail': 'API key budget exceeded. Please add more budget to continue.'}, 403
            if float(budget_remaining) <= 0:
                return None, None, {'detail': 'API key budget exceeded. Please add more budget to continue.'}, 403

        api_key = db.session.query(ApiKey).filter(ApiKey.key == token).first()
        if api_key:
            api_key.last_used_at = datetime.utcnow()
            api_key.request_count += 1
            db.session.commit()

            _ = api_key.user
            _ = api_key.group

            return None, api_key, None, 200
        else:
            cache.invalidate_api_key(token)

    # Cache miss — fall back to DB query
    api_key = db.session.query(ApiKey).filter(ApiKey.key == token).first()

    if api_key:
        if not api_key.is_active:
            return None, None, {'detail': 'API key is inactive'}, 401

        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return None, None, {'detail': 'API key has expired'}, 401

        if not api_key.unlimited_budget:
            budget_val = api_key.budget
            if budget_val is not None and budget_val <= 0:
                return None, None, {'detail': 'API key budget exceeded. Please add more budget to continue.'}, 403

        api_key.last_used_at = datetime.utcnow()
        api_key.request_count += 1
        db.session.commit()

        _ = api_key.user
        _ = api_key.group

        try:
            _populate_api_key_cache(api_key, cache)
        except Exception as _ce:
            logger.debug(f"[cache] Failed to populate API key cache: {_ce}")

        return None, api_key, None, 200

    # Try JWT token authentication
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get('sub')
        if not username:
            logger.warning(f"Invalid token (no sub): {token}")
            return None, None, {'detail': 'Invalid token'}, 401
    except JWTError:
        logger.warning(f"Invalid token or API key: {token}")
        return None, None, {'detail': 'Invalid token or API key'}, 401

    user = db.session.query(User).filter(User.username == username).first()
    if not user:
        return None, None, {'detail': 'User not found'}, 401

    return user, None, None, 200


def _populate_api_key_cache(api_key, cache):
    """Compute the current budget_used from UsageRecord and populate the cache."""
    import hashlib
    from app.models import UsageRecord

    budget_used = 0.0
    if api_key.budget is not None:
        key_hash = hashlib.sha256(api_key.key.encode()).hexdigest()
        row = (
            db.session.query(
                db.func.coalesce(db.func.sum(UsageRecord.actual_amount_usd), 0)
            )
            .filter(UsageRecord.api_key_hash == key_hash)
            .scalar()
        )
        budget_used = float(row or 0)

    info = cache.build_api_key_cache_info(api_key, budget_used=budget_used)
    cache.set_api_key_info(api_key.key, info)

    if not api_key.unlimited_budget and api_key.budget is not None:
        from app.budget_manager import get_budget_manager
        get_budget_manager().set_remaining(api_key.key, float(api_key.budget))


def _call_in_app_ctx(app, fn, *args, **kwargs):
    """Call *fn(*args, **kwargs)* inside Flask's application context.

    We explicitly use Flask's ``_cv_app`` ContextVar (the same bridging
    mechanism used by ``create_app()``) because Quart's ``app.app_context()``
    does not interoperate with Flask-SQLAlchemy's ``db.session``.
    """
    from flask.globals import _cv_app
    from flask.ctx import AppContext as FlaskAppContext

    token = _cv_app.set(FlaskAppContext(app))
    try:
        return fn(*args, **kwargs)
    finally:
        _cv_app.reset(token)