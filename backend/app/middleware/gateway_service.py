"""
网关服务 (Gateway Service) - 中间层核心
隐藏供应商 API 细节，提供统一的请求处理接口。

架构：
  API 层 (Adapters) → 中间层 (GatewayService) → 供应商层 (Providers)

中间层职责：
  1. 模型解析 - 将模型名称/别名解析为具体的供应商和模型
  2. 供应商路由 - 根据模型自动选择正确的供应商实例
  3. 请求执行 - 调用供应商 API 并返回统一格式的响应
  4. 错误处理 - 统一处理供应商层的错误
"""
from typing import Any, Optional, AsyncGenerator, Tuple, Callable, List
from dataclasses import dataclass
import hashlib
import logging
import random
import time
import asyncio
import httpx
from sqlalchemy import select, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload

from app.utils import json_loads
from app.models import Provider, Model
from app.providers import get_provider_class
from app.providers.base import BaseProvider, ProviderConfig, UpstreamProviderError
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse
from app.abstraction.rerank import RerankRequest, RerankResponse
from app.request_context import ResolvedModelData


# Shared httpx.AsyncClient for in-request image/video URL → base64 conversion.
# Per-request clients caused a TLS handshake + new pool per request; this
# singleton keeps a small bounded keepalive pool and reuses connections.
_media_fetch_client: Optional[httpx.AsyncClient] = None
_media_fetch_client_lock = asyncio.Lock()


async def _get_media_fetch_client() -> httpx.AsyncClient:
    global _media_fetch_client
    if _media_fetch_client is None:
        async with _media_fetch_client_lock:
            if _media_fetch_client is None:
                from app.http_client import make_async_client
                _media_fetch_client = make_async_client(
                    scope="MEDIA",
                    follow_redirects=True,
                )
    return _media_fetch_client


class GatewayServiceError(Exception):
    """网关服务错误基类"""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class ModelNotFoundError(GatewayServiceError):
    """模型未找到错误"""
    def __init__(self, model_name: str):
        super().__init__(
            f"Model '{model_name}' not found or not accessible with your API key.",
            status_code=404
        )


class ProviderError(GatewayServiceError):
    """供应商错误"""
    def __init__(self, message: str, status_code: int = 500, error_data: Optional[dict] = None,
                 provider_id: Optional[int] = None, provider_name: Optional[str] = None):
        self.error_data = error_data
        self.provider_id = provider_id
        self.provider_name = provider_name
        super().__init__(message, status_code)


# Internal metadata keys set by the gateway service.
# These are used for internal logic and should NOT be sent to upstream provider APIs.
INTERNAL_METADATA_KEYS = frozenset({'support_thinking', 'support_online_image', 'support_online_video', 'reasoning', 'timeout'})

logger = logging.getLogger(__name__)

# Error codes that indicate a transient database error worth retrying.
_TRANSIENT_DB_ERROR_CODES = frozenset({2013})  # 2013 = Lost connection during query


async def _retry_db_query(session, query_fn, max_retries=2):
    """Execute an async database query with retries on transient connection errors.

    On OperationalError with a transient code, the broken session is rolled back
    and a fresh connection is obtained on the next attempt.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await query_fn(session)
        except OperationalError as exc:
            last_exc = exc
            code = getattr(exc.orig, 'args', None)
            if code:
                code = code[0] if isinstance(code, (list, tuple)) else code
                if code not in _TRANSIENT_DB_ERROR_CODES:
                    raise
            elif not _is_connection_lost(exc):
                raise
            logger.warning(
                "Transient DB error (attempt %d/%d): %s. Retrying...",
                attempt + 1, max_retries + 1, exc
            )
            try:
                await session.rollback()
            except Exception:
                pass
            if attempt < max_retries:
                await asyncio.sleep(0.1 * (attempt + 1))
        except Exception:
            raise
    raise last_exc


def _is_connection_lost(exc: OperationalError) -> bool:
    """Check if an OperationalError looks like a lost-connection error."""
    msg = str(exc).lower()
    return any(phrase in msg for phrase in (
        'lost connection', 'server has gone away',
        'connection refused', 'connection reset',
        'broken pipe', 'connection timed out',
    ))


class GatewayService:
    """
    网关服务 - 中间层核心

    隐藏供应商 API 的细节，API 用户可以使用任何 API 格式
    (/v1/chat/completions, /v1/messages, /v1/responses)
    而不需要关心底层供应商的差异。

    用法:
        service = GatewayService()

        # 非流式请求
        response = service.chat(chat_request, group_id=1)

        # 流式请求
        for chunk in service.stream_chat(chat_request, group_id=1):
            yield chunk.to_sse("openai")
    """

    # Default timeout (seconds) when no model-level timeout is configured.
    DEFAULT_TIMEOUT = 300

    def __init__(self):
        self._provider_cache: dict[int, BaseProvider] = {}
        # Track raw DB values at cache time so we can detect real config changes.
        # Provider.__init__ may mutate config (e.g. set default base_url), so
        # we can't compare cached.config against db_provider directly.
        self._provider_db_fingerprint: dict[int, tuple[str, str | None]] = {}
        # Strong refs to in-flight aclose() tasks for evicted providers, so the
        # event loop doesn't GC them mid-close (which would leak the underlying
        # httpx.AsyncClient connection pool — the very thing we're trying to free).
        self._pending_closes: set[asyncio.Task] = set()
        # Per-provider-id locks to serialize concurrent first-time construction
        # so two parallel requests don't both build a VertexAIProvider (each
        # with its own 100-socket httpx pool) and leak the loser.
        self._provider_build_locks: dict[int, asyncio.Lock] = {}
        # Guards mutation of _provider_build_locks itself.
        self._build_locks_mutex = asyncio.Lock()

    async def resolve_model(self, session, model_name: str, group_id: Optional[int] = None, user_id: Optional[str] = None, provider_id: Optional[int] = None) -> ResolvedModelData:
        """
        解析模型名称/别名，返回供应商实例和模型信息（plain dataclass）。

        当同一模型名称/别名存在于多个启用的供应商中时，
        从启用的供应商中随机选择一个进行路由（负载分散）。

        Args:
            session: caller-managed AsyncSession — must be alive for the duration of this call.
        Returns:
            ResolvedModelData (plain data — safe to use after session is closed).

        Args:
            model_name: 模型名称或别名
            group_id: 可选的组 ID（用于访问控制）
            provider_id: 可选的供应商 ID（用于 API Key 限定供应商）

        Returns:
            ResolvedModelData 对象（plain dataclass — 不再持有 ORM 引用）

        Raises:
            ModelNotFoundError: 如果模型未找到或不可访问
        """
        async def _query_all(s):
            result = await s.execute(
                select(Model)
                .options(selectinload(Model.provider))
                .join(Provider, Model.provider_id == Provider.id)
                .where((Model.alias == model_name) | (Model.name == model_name))
            )
            return result.scalars().all()

        all_models: List[Model] = await _retry_db_query(session, _query_all)

        # Filter by group_id
        if group_id is not None:
            from app.models import ModelShare
            shared_result = await session.execute(
                select(ModelShare.model_id)
                .where(ModelShare.target_group_id == group_id)
            )
            shared_ids = {row[0] for row in shared_result}
            all_models = [
                m for m in all_models
                if m.provider.group_id == group_id or m.id in shared_ids
            ]

        if provider_id is not None:
            all_models = [m for m in all_models if m.provider_id == provider_id]

        if not all_models:
            raise ModelNotFoundError(model_name)

        # Filter out retired models
        non_retired = [m for m in all_models if not m.is_retired]
        if not non_retired:
            m = all_models[0]
            raise GatewayServiceError(
                f"Model '{model_name}' was retired on {m.retirement_time.strftime('%Y-%m-%d')} "
                f"and can no longer be used.",
                status_code=410  # 410 Gone
            )

        # Filter to only models that are themselves enabled AND whose provider is active
        active_models = [
            m for m in non_retired
            if m.is_active and m.provider and m.provider.is_active
        ]

        if not active_models:
            disabled_models = [m for m in non_retired if not m.is_active]
            disabled_providers = [m for m in non_retired if m.is_active and m.provider and not m.provider.is_active]
            if disabled_models and not disabled_providers:
                raise GatewayServiceError(
                    f"Model '{model_name}' exists but is disabled.",
                    status_code=403
                )
            elif disabled_providers and not disabled_models:
                raise GatewayServiceError(
                    f"Model '{model_name}' exists but all its providers are disabled.",
                    status_code=403
                )
            else:
                raise GatewayServiceError(
                    f"Model '{model_name}' exists but all its instances are disabled (model or provider).",
                    status_code=403
                )

        # Priority + Traffic-ratio based routing
        db_model = self._select_model_by_priority(active_models, user_id=user_id)

        provider_result = await session.execute(
            select(Provider).where(Provider.id == db_model.provider_id)
        )
        db_provider = provider_result.scalars().first()

        if not db_provider:
            raise ModelNotFoundError(model_name)

        # 创建供应商实例
        provider_instance = await self._create_provider_instance(db_provider)
        if not provider_instance:
            raise GatewayServiceError(
                f"Failed to create provider instance for '{db_provider.name}'",
                status_code=500
            )

        # Eagerly extract all primitive fields to a plain dataclass so callers
        # can close the DB session before the (potentially minute-long) LLM call.
        return ResolvedModelData(
            provider_id=db_provider.id,
            provider_name=db_provider.name,
            provider_type=db_provider.type or "",
            model_id=db_model.id,
            model_alias=db_model.alias,
            model_real_name=db_model.name,
            input_price=float(getattr(db_model, 'input_price', 0) or 0),
            output_price=float(getattr(db_model, 'output_price', 0) or 0),
            cache_creation_price=float(getattr(db_model, 'cache_creation_price', 0) or 0),
            cache_5m_creation_price=float(getattr(db_model, 'cache_5m_creation_price', 0) or 0),
            cache_1h_creation_price=float(getattr(db_model, 'cache_1h_creation_price', 0) or 0),
            cache_hit_price=float(getattr(db_model, 'cache_hit_price', 0) or 0),
            currency=getattr(db_model, 'currency', 'USD') or 'USD',
            discount=float(getattr(db_model, 'discount', 1) or 1),
            pricing_tiers=getattr(db_model, 'pricing_tiers', None),
            output_pricing=getattr(db_model, 'output_pricing', None),
            support_thinking=bool(getattr(db_model, 'support_thinking', False)),
            support_online_image=bool(getattr(db_model, 'support_online_image', True)),
            support_online_video=bool(getattr(db_model, 'support_online_video', True)),
            support_image=bool(getattr(db_model, 'support_image', False)),
            support_audio=bool(getattr(db_model, 'support_audio', False)),
            support_video=bool(getattr(db_model, 'support_video', False)),
            support_embedding=bool(getattr(db_model, 'support_embedding', False)),
            timeout=getattr(db_model, 'timeout', None),
            provider_instance=provider_instance,
        )

    @staticmethod
    def _select_model_by_priority(active_models: List[Model], user_id: Optional[str] = None) -> Model:
        """
        Select a model from active candidates using priority + traffic_ratio.

        Algorithm:
        1. Group models by priority (higher number = more preferred).
        2. Pick the group with the highest priority.
        3. Within that group:
           a. If user_id is provided, use hash(user_id) % 100 to determine
              which provider to use based on cumulative traffic_ratio ranges.
           b. If no user_id, perform weighted random selection.
           c. If all traffic_ratios are 0, fall back to uniform random.

        Args:
            active_models: List of active, non-retired Model ORM instances.
            user_id: Optional user identifier for deterministic routing.

        Returns:
            The selected Model instance.
        """
        if len(active_models) == 1:
            return active_models[0]

        # Group by priority
        priority_groups: dict[int, List[Model]] = {}
        for m in active_models:
            prio = max(m.priority or 0, 0)
            priority_groups.setdefault(prio, []).append(m)

        # Pick the group with the highest priority
        top_priority = max(priority_groups.keys())
        candidates = priority_groups[top_priority]

        if len(candidates) == 1:
            return candidates[0]

        # Collect traffic ratios
        ratios: List[int] = []
        for m in candidates:
            ratio = max(m.traffic_ratio or 0, 0)
            ratios.append(ratio)

        total_ratio = sum(ratios)

        if total_ratio > 0:
            if user_id:
                # Deterministic selection based on user_id hash
                # hash(user_id) % 100 maps the user into a bucket [0, 99]
                bucket = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 100

                # Walk cumulative traffic_ratio ranges to find the matching provider
                # traffic_ratios are scaled to sum to 100 for percentage-based selection
                cumulative = 0
                for i, ratio in enumerate(ratios):
                    # Scale ratio to percentage within the 0-99 range
                    scaled_ratio = int(round(ratio / total_ratio * 100))
                    cumulative += scaled_ratio
                    if bucket < cumulative:
                        return candidates[i]

                # Fallback: return the last candidate (shouldn't normally reach here)
                return candidates[-1]
            else:
                # No user_id — weighted random selection
                weights = [float(r) for r in ratios]
                return random.choices(candidates, weights=weights, k=1)[0]
        else:
            # All traffic_ratios are 0 — fall back to uniform random
            return random.choice(candidates)

    async def chat(
        self, resolved: ResolvedModelData, request: ChatRequest, tracer: Any = None,
    ) -> ChatResponse:
        """
        执行非流式对话请求，返回 ChatResponse。

        模型必须由调用方使用 `resolve_model()` 预先解析。本方法不再持有 DB
        会话 —— 上游 LLM 调用期间 DB 连接已被释放。

        Args:
            resolved: 调用方在 DB session 内预先解析得到的模型/供应商信息
            request: 统一的对话请求对象（由 Adapter 从任意 API 格式解析而来）

        Returns:
            ChatResponse

        Raises:
            GatewayServiceError: 请求验证失败
            ProviderError: 供应商 API 调用失败
        """
        # Record provider info on tracer
        if tracer:
            tracer.set_metadata({
                "provider_id": resolved.provider_id,
                "provider": resolved.provider_name,
            })

        # 1. Replace with real model name
        request.model = resolved.model_real_name

        # 2. Pass model capability flags / overrides to request metadata
        request.metadata['support_thinking'] = resolved.support_thinking
        if resolved.timeout:
            request.metadata['timeout'] = resolved.timeout
        request.metadata['output_pricing'] = resolved.output_pricing

        # 3. Convert image/video URLs if the model doesn't support online URLs
        if not resolved.support_online_image:
            await self._convert_image_urls_to_base64(request)
        if not resolved.support_online_video:
            await self._convert_video_urls_to_base64(request)

        # 4. 调用供应商 API
        resolved.provider_instance.tracer = tracer
        try:
            response = await resolved.provider_instance.chat(request)

            if not self._should_include_reasoning(request):
                for choice in response.choices:
                    choice.reasoning_content = None
                    if choice.message:
                        choice.message.reasoning_content = None

            return response
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except UpstreamProviderError as e:
            canonical_data: dict = {
                'type': e.error_type,
                'message': str(e),
            }
            if e.request_id:
                canonical_data['request_id'] = e.request_id
            raise ProviderError(str(e), status_code=e.status_code, error_data=canonical_data,
                                     provider_id=resolved.provider_id,
                                     provider_name=resolved.provider_name)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data,
                                     provider_id=resolved.provider_id,
                                     provider_name=resolved.provider_name)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
            raise ProviderError(f"Connection to upstream provider failed: {str(e)}", status_code=502,
                                provider_id=resolved.provider_id,
                                provider_name=resolved.provider_name)
        except httpx.HTTPError as e:
            raise ProviderError(f"HTTP error from upstream provider: {str(e)}", status_code=502,
                                provider_id=resolved.provider_id,
                                provider_name=resolved.provider_name)
        except Exception as e:
            raise ProviderError(f"Provider error: {str(e)}", status_code=500,
                                provider_id=resolved.provider_id,
                                provider_name=resolved.provider_name)

    async def stream_chat(
        self, resolved: ResolvedModelData, request: ChatRequest, tracer: Any = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        执行流式对话请求，返回 StreamChunk 异步生成器。

        模型必须由调用方使用 `resolve_model()` 预先解析。本方法不持有 DB 会话。

        Args:
            resolved: 调用方在 DB session 内预先解析得到的模型/供应商信息
            request: 统一的对话请求对象

        Returns:
            StreamChunk 异步生成器

        Raises:
            GatewayServiceError: 请求验证失败
            ProviderError: 供应商 API 调用失败
        """
        # Record provider info on tracer
        if tracer:
            tracer.set_metadata({
                "provider_id": resolved.provider_id,
                "provider": resolved.provider_name,
            })

        # 1. Replace with real model name
        request.model = resolved.model_real_name

        # 2. Pass model capability flags / overrides to request metadata
        request.metadata['support_thinking'] = resolved.support_thinking
        if resolved.timeout:
            request.metadata['timeout'] = resolved.timeout

        # 3. Convert image/video URLs if the model doesn't support online URLs
        if not resolved.support_online_image:
            await self._convert_image_urls_to_base64(request)
        if not resolved.support_online_video:
            await self._convert_video_urls_to_base64(request)

        # 4. Determine reasoning flag
        include_reasoning = self._should_include_reasoning(request)

        # 5. Attach tracer to provider so it can create child spans internally.
        resolved.provider_instance.tracer = tracer

        # 6. Return lazy async generator
        async def _stream():
            try:
                async for chunk in resolved.provider_instance.stream_chat(request):
                    if not include_reasoning:
                        chunk.delta_reasoning_content = None
                    yield chunk
            except ValueError as e:
                raise GatewayServiceError(str(e), status_code=400)
            except RuntimeError as e:
                status_code, error_data = self._parse_provider_error(e)
                raise ProviderError(str(e), status_code=status_code, error_data=error_data,
                                    provider_id=resolved.provider_id,
                                    provider_name=resolved.provider_name)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                raise ProviderError(f"Connection to upstream provider failed: {str(e)}", status_code=502,
                                    provider_id=resolved.provider_id,
                                    provider_name=resolved.provider_name)
            except httpx.HTTPError as e:
                raise ProviderError(f"HTTP error from upstream provider: {str(e)}", status_code=502,
                                    provider_id=resolved.provider_id,
                                    provider_name=resolved.provider_name)
            except Exception as e:
                raise ProviderError(f"Provider error: {str(e)}", status_code=500,
                                    provider_id=resolved.provider_id,
                                    provider_name=resolved.provider_name)

        return _stream()

    @staticmethod
    def _should_include_reasoning(request: ChatRequest) -> bool:
        """
        判断是否应在响应中包含推理内容 (reasoning_content)。

        返回 True 的条件（满足其一即可）：
        1. 模型支持思维/推理 (support_thinking 标志在数据库中为 True)
           且请求中 reasoning_effort 参数不为 'none'
        2. 请求中明确设置了 reasoning_effort（非 None 且非 'none'），
           例如通过 Responses API 的 reasoning.effort 字段传入

        Args:
            request: 对话请求对象

        Returns:
            是否应包含推理内容
        """
        reasoning_effort = request.reasoning_effort or 'none'

        # If reasoning_effort is explicitly set in the request (e.g. via Responses API),
        # always include reasoning content regardless of DB support_thinking flag
        if reasoning_effort != 'none':
            return True

        # Fall back to DB-based support_thinking flag
        support_thinking = request.metadata.get('support_thinking', False)
        return bool(support_thinking)

    def _schedule_provider_close(self, provider: BaseProvider) -> None:
        """Fire-and-forget aclose() for an evicted provider, with a strong ref."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(provider.close())
        self._pending_closes.add(task)
        task.add_done_callback(self._pending_closes.discard)

    async def _create_provider_instance(self, db_provider: Provider) -> Optional[BaseProvider]:
        """
        根据数据库供应商配置创建或返回缓存的供应商实例。

        Provider instances (and their httpx.AsyncClient connection pools) are
        cached by provider_id so that concurrent requests reuse a single
        managed connection pool instead of creating a new client per request.

        Concurrent first-time construction is serialized via a per-provider
        asyncio.Lock so two parallel requests don't both build a fresh
        provider (each with its own 100-socket httpx pool) and orphan the
        loser. Cache invalidation on credential change schedules an aclose()
        on the evicted instance so its pool is actually freed.

        Args:
            db_provider: 数据库供应商对象

        Returns:
            供应商实例，如果创建失败返回 None
        """
        cache_key = db_provider.id
        raw_api_key = db_provider.api_key or ""
        raw_base_url = db_provider.base_url

        # Fast path: cache hit with unchanged credentials.
        if cache_key in self._provider_cache:
            cached = self._provider_cache[cache_key]
            prev_key, prev_url = self._provider_db_fingerprint.get(cache_key, ("", None))
            if raw_api_key == prev_key and raw_base_url == prev_url:
                return cached

        # Acquire (or create) the per-id build lock.
        async with self._build_locks_mutex:
            build_lock = self._provider_build_locks.get(cache_key)
            if build_lock is None:
                build_lock = asyncio.Lock()
                self._provider_build_locks[cache_key] = build_lock

        async with build_lock:
            # Re-check under the per-id lock — another coroutine may have
            # already constructed the instance while we were waiting.
            if cache_key in self._provider_cache:
                cached = self._provider_cache[cache_key]
                prev_key, prev_url = self._provider_db_fingerprint.get(cache_key, ("", None))
                if raw_api_key != prev_key or raw_base_url != prev_url:
                    # DB values changed — invalidate cached instance so the next
                    # call recreates the provider with new config. Schedule an
                    # aclose() so the evicted provider's httpx.AsyncClient pool
                    # (up to 100 sockets) is released instead of leaked.
                    self._schedule_provider_close(cached)
                    del self._provider_cache[cache_key]
                    self._provider_db_fingerprint.pop(cache_key, None)
                else:
                    return cached

            provider_type = db_provider.type
            provider_class = get_provider_class(provider_type)

            if not provider_class:
                # 如果没有找到对应的供应商类，使用通用 OpenAI 兼容实现
                from app.providers.bailian import BailianProvider
                provider_class = BailianProvider

            config = ProviderConfig(
                name=db_provider.name,
                api_key=raw_api_key,
                base_url=raw_base_url,
                authorization=db_provider.authorization or "Authorization",
                extra_config=db_provider.extra_config or {},
            )

            try:
                instance = provider_class(config)
                self._provider_cache[cache_key] = instance
                self._provider_db_fingerprint[cache_key] = (raw_api_key, raw_base_url)
                return instance
            except Exception as e:
                return None

    @staticmethod
    async def _convert_image_urls_to_base64(request: ChatRequest) -> None:
        """
        Convert all IMAGE_URL content blocks in the request to IMAGE_BASE64.

        Some providers (e.g. Kimi/Moonshot) do not support online image URLs in
        their API.  This method downloads each image and converts it to a base64
        data URI so the provider receives the raw image data instead.

        The conversion happens in-place on the request's messages. Downloads
        across all messages run concurrently via asyncio.gather, and the
        (potentially large) base64 encoding is off-loaded to a worker thread
        so we don't freeze the event loop on multi-megabyte payloads.
        """
        import base64
        import logging
        from app.abstraction.messages import ContentBlock, ContentType

        logger = logging.getLogger("gateway")

        _EXT_MIME = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
        }

        def _guess_mime(url: str, content_type: str = '') -> str:
            if content_type:
                mime = content_type.split(';')[0].strip().lower()
                if mime.startswith('image/'):
                    return mime
            from urllib.parse import urlparse
            import os
            path = urlparse(url).path
            ext = os.path.splitext(path)[1].lower()
            return _EXT_MIME.get(ext, 'image/jpeg')

        client = await _get_media_fetch_client()

        async def _download_and_encode(block: ContentBlock) -> ContentBlock:
            try:
                resp = await client.get(block.url)
                resp.raise_for_status()
                ct = resp.headers.get('content-type', '')
                mime = _guess_mime(block.url, ct)
                # base64 encode on a worker thread — multi-MB images would
                # otherwise block the event loop (and /health with it).
                b64_data = await asyncio.to_thread(
                    lambda data: base64.b64encode(data).decode('ascii'),
                    resp.content,
                )
                logger.info(
                    f"Converted image URL to base64: {block.url[:80]}... "
                    f"({len(resp.content)} bytes, {mime})"
                )
                return ContentBlock.from_image_base64(b64_data, mime)
            except Exception as exc:
                logger.warning(
                    f"Failed to download image URL {block.url[:120]}: {exc}. "
                    f"Keeping original URL block."
                )
                return block

        # Collect (message_index, block_index, block) for every IMAGE_URL block,
        # then download them all in parallel.
        targets: List[tuple[int, int, ContentBlock]] = []
        for mi, message in enumerate(request.messages):
            if not isinstance(message.content, list):
                continue
            for bi, block in enumerate(message.content):
                if (isinstance(block, ContentBlock)
                        and block.type == ContentType.IMAGE_URL
                        and block.url):
                    targets.append((mi, bi, block))

        if not targets:
            return

        results = await asyncio.gather(*(_download_and_encode(b) for _, _, b in targets))
        for (mi, bi, _), new_block in zip(targets, results):
            request.messages[mi].content[bi] = new_block

    @staticmethod
    async def _convert_video_urls_to_base64(request: ChatRequest) -> None:
        """
        Convert all VIDEO_URL content blocks in the request to VIDEO_BASE64.

        Same shape as _convert_image_urls_to_base64: parallel downloads via
        the shared httpx client and base64 encoding off-loaded to a worker
        thread (videos can be tens of MB).
        """
        import base64
        import logging
        from app.abstraction.messages import ContentBlock, ContentType

        logger = logging.getLogger("gateway")

        _EXT_MIME = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.ogg': 'video/ogg',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.mkv': 'video/x-matroska',
            '.flv': 'video/x-flv',
            '.wmv': 'video/x-ms-wmv',
        }

        def _guess_mime(url: str, content_type: str = '') -> str:
            if content_type:
                mime = content_type.split(';')[0].strip().lower()
                if mime.startswith('video/'):
                    return mime
            from urllib.parse import urlparse
            import os
            path = urlparse(url).path
            ext = os.path.splitext(path)[1].lower()
            return _EXT_MIME.get(ext, 'video/mp4')

        client = await _get_media_fetch_client()

        async def _download_and_encode(block: ContentBlock) -> ContentBlock:
            try:
                resp = await client.get(block.url)
                resp.raise_for_status()
                ct = resp.headers.get('content-type', '')
                mime = _guess_mime(block.url, ct)
                b64_data = await asyncio.to_thread(
                    lambda data: base64.b64encode(data).decode('ascii'),
                    resp.content,
                )
                logger.info(
                    f"Converted video URL to base64: {block.url[:80]}... "
                    f"({len(resp.content)} bytes, {mime})"
                )
                return ContentBlock.from_video_base64(b64_data, mime)
            except Exception as exc:
                logger.warning(
                    f"Failed to download video URL {block.url[:120]}: {exc}. "
                    f"Keeping original URL block."
                )
                return block

        targets: List[tuple[int, int, ContentBlock]] = []
        for mi, message in enumerate(request.messages):
            if not isinstance(message.content, list):
                continue
            for bi, block in enumerate(message.content):
                if (isinstance(block, ContentBlock)
                        and block.type == ContentType.VIDEO_URL
                        and block.url):
                    targets.append((mi, bi, block))

        if not targets:
            return

        results = await asyncio.gather(*(_download_and_encode(b) for _, _, b in targets))
        for (mi, bi, _), new_block in zip(targets, results):
            request.messages[mi].content[bi] = new_block

    async def rerank(self, resolved: ResolvedModelData, request: RerankRequest) -> RerankResponse:
        """
        执行 Rerank 请求（模型由调用方预先解析）。

        Args:
            resolved: 调用方在 DB session 内预先解析得到的模型/供应商信息
            request: Rerank 请求对象

        Returns:
            Rerank 响应对象

        Raises:
            GatewayServiceError: 供应商不支持 rerank
            ProviderError: 供应商 API 调用失败
        """
        # Replace with real model name
        request.model = resolved.model_real_name

        # Check that the provider supports rerank
        if not hasattr(resolved.provider_instance, 'rerank'):
            raise GatewayServiceError(
                f"Provider '{resolved.provider_name}' does not support rerank",
                status_code=400
            )

        try:
            return await resolved.provider_instance.rerank(request)
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except UpstreamProviderError as e:
            canonical_data: dict = {
                'type': e.error_type,
                'message': str(e),
            }
            if e.request_id:
                canonical_data['request_id'] = e.request_id
            raise ProviderError(str(e), status_code=e.status_code, error_data=canonical_data,
                                     provider_id=resolved.provider_id,
                                     provider_name=resolved.provider_name)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data,
                                provider_id=resolved.provider_id,
                                provider_name=resolved.provider_name)
        except Exception as e:
            raise ProviderError(f"Provider error: {str(e)}", status_code=500,
                                provider_id=resolved.provider_id,
                                provider_name=resolved.provider_name)

    async def embed(self, resolved: ResolvedModelData, request: EmbeddingRequest, tracer: Any = None) -> EmbeddingResponse:
        """
        执行嵌入请求（模型由调用方预先解析）。

        Args:
            resolved: 调用方在 DB session 内预先解析得到的模型/供应商信息
            request: 嵌入请求对象

        Returns:
            嵌入响应对象

        Raises:
            GatewayServiceError: 请求验证失败
            ProviderError: 供应商 API 调用失败
        """
        # Record provider info on tracer immediately
        if tracer:
            tracer.set_metadata({
                "provider_id": resolved.provider_id,
                "provider": resolved.provider_name,
            })

        # Replace with real model name
        request.model = resolved.model_real_name

        # Pass model multimodal capability flags into request metadata so
        # the provider can decide whether to use a multimodal API path.
        request.metadata['support_image'] = resolved.support_image
        request.metadata['support_video'] = resolved.support_video
        request.metadata['support_audio'] = resolved.support_audio

        # Attach tracer so providers can create child spans
        resolved.provider_instance.tracer = tracer

        # Check that the model is flagged as an embedding model
        if not resolved.support_embedding:
            raise GatewayServiceError(
                f"Model '{resolved.model_alias or resolved.model_real_name}' is not an embedding model. "
                f"Set support_embedding=true for this model in the admin panel.",
                status_code=400
            )

        # Check that the provider supports embeddings
        if not hasattr(resolved.provider_instance, 'embed'):
            raise GatewayServiceError(
                f"Provider '{resolved.provider_name}' does not support embedding",
                status_code=400
            )

        try:
            response = await resolved.provider_instance.embed(request)
            return response
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except UpstreamProviderError as e:
            canonical_data: dict = {
                'type': e.error_type,
                'message': str(e),
            }
            if e.request_id:
                canonical_data['request_id'] = e.request_id
            raise ProviderError(str(e), status_code=e.status_code, error_data=canonical_data,
                                     provider_id=resolved.provider_id,
                                     provider_name=resolved.provider_name)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data,
                                provider_id=resolved.provider_id,
                                provider_name=resolved.provider_name)
        except Exception as e:
            raise ProviderError(f"Provider error: {str(e)}", status_code=500,
                                provider_id=resolved.provider_id,
                                provider_name=resolved.provider_name)

    async def generate_images(
        self,
        resolved: ResolvedModelData,
        prompt: str,
        images: Optional[list] = None,
        n: int = 1,
        size: str = "1024x1024",
        response_format: str = "url",
        output_format: str = "png",
        quality: Optional[str] = None,
        style: Optional[str] = None,
        user: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        resolution: Optional[str] = None,
        tracer: Any = None,
    ) -> Tuple[dict, ChatResponse]:
        """
        Execute image generation and return an OpenAI-compatible response.

        Builds a ``ChatRequest`` with image-generation metadata, routes it
        through the standard provider pipeline (which already knows how to
        detect image-generation models and metadata), then converts the
        ``ChatResponse`` to OpenAI ``/v1/images/generations`` format.

        Args:
            resolved: caller-resolved ResolvedModelData (no internal DB access).
            prompt: Text description for the image to generate.
            ...
        """
        import json as _json
        from app.abstraction.messages import Message, MessageRole, ContentBlock

        # Build message content: text prompt + optional reference images
        if images:
            content_blocks: list = [ContentBlock.from_text(prompt)]
            for img in images:
                img_url = img.get("image_url") or img.get("url")
                if img_url:
                    content_blocks.append(ContentBlock.from_image_url(img_url))
            messages = [Message(role=MessageRole.USER, content=content_blocks)]
        else:
            messages = [Message(role=MessageRole.USER, content=prompt)]

        metadata: dict = {
            "size": size,
            "number": n,
            "response_format": response_format,
            "image_format": output_format,
        }
        if aspect_ratio:
            metadata["aspect_ratio"] = aspect_ratio
        if resolution:
            metadata["resolution"] = resolution
        if quality:
            metadata["quality"] = quality

        chat_request = ChatRequest(
            messages=messages,
            model=resolved.model_real_name,
            metadata=metadata,
            user=user,
        )

        try:
            chat_response = await self.chat(resolved, chat_request, tracer=tracer)
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data)

        # ── Convert ChatResponse → OpenAI images format ──────────────
        data: list = []
        if chat_response.choices and chat_response.choices[0].message:
            msg = chat_response.choices[0].message
            text_content = msg.get_text_content()
            if text_content:
                try:
                    items = json_loads(text_content)
                    if not isinstance(items, list):
                        items = [items]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        result = item.get("result", "")
                        img_entry: dict = {}
                        if result.startswith("data:"):
                            img_entry["b64_json"] = result
                        elif result:
                            img_entry["url"] = result
                        revised = item.get("revised_prompt")
                        if revised:
                            img_entry["revised_prompt"] = revised
                        if img_entry:
                            data.append(img_entry)
                except (_json.JSONDecodeError, TypeError):
                    pass

        result_dict = {
            "created": chat_response.created,
            "data": data,
            "output_format": output_format,
        }
        return result_dict, chat_response

    async def edit_images(
        self,
        resolved: ResolvedModelData,
        prompt: str,
        images: Optional[list] = None,
        mask: Optional[dict] = None,
        n: int = 1,
        size: str = "1024x1024",
        response_format: str = "url",
        output_format: str = "png",
        quality: Optional[str] = None,
        background: Optional[str] = None,
        input_fidelity: Optional[str] = None,
        moderation: Optional[str] = None,
        user: Optional[str] = None,
        tracer: Any = None,
    ) -> Tuple[dict, ChatResponse]:
        """
        Execute image editing and return an OpenAI-compatible response.

        Args:
            resolved: caller-resolved ResolvedModelData (no internal DB access).
            ...
        """
        import json as _json
        from app.abstraction.messages import Message, MessageRole, ContentBlock

        content_blocks: list = [ContentBlock.from_text(prompt)]
        if images:
            for img in images:
                img_url = img.get("image_url") or img.get("url")
                if img_url:
                    content_blocks.append(ContentBlock.from_image_url(img_url))
        messages = [Message(role=MessageRole.USER, content=content_blocks)]

        metadata: dict = {
            "size": size,
            "number": n,
            "response_format": response_format,
            "image_format": output_format,
        }
        if quality:
            metadata["quality"] = quality
        if background:
            metadata["background"] = background
        if input_fidelity:
            metadata["input_fidelity"] = input_fidelity
        if moderation:
            metadata["moderation"] = moderation
        if mask:
            metadata["mask"] = mask

        chat_request = ChatRequest(
            messages=messages,
            model=resolved.model_real_name,
            metadata=metadata,
            user=user,
        )

        try:
            chat_response = await self.chat(resolved, chat_request, tracer=tracer)
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data)

        data: list = []
        if chat_response.choices and chat_response.choices[0].message:
            msg = chat_response.choices[0].message
            text_content = msg.get_text_content()
            if text_content:
                try:
                    items = json_loads(text_content)
                    if not isinstance(items, list):
                        items = [items]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        result = item.get("result", "")
                        img_entry: dict = {}
                        if result.startswith("data:"):
                            img_entry["b64_json"] = result
                        elif result:
                            img_entry["url"] = result
                        revised = item.get("revised_prompt")
                        if revised:
                            img_entry["revised_prompt"] = revised
                        if img_entry:
                            data.append(img_entry)
                except (_json.JSONDecodeError, TypeError):
                    pass

        result_dict: dict = {
            "created": chat_response.created,
            "data": data,
            "output_format": output_format,
            "size": size,
        }
        if quality:
            result_dict["quality"] = quality
        if background and background != "auto":
            result_dict["background"] = background

        return result_dict, chat_response

    @staticmethod
    def _parse_provider_error(error: RuntimeError) -> Tuple[int, Optional[dict]]:
        """
        解析供应商错误，提取状态码和错误数据。

        Args:
            error: 供应商抛出的 RuntimeError

        Returns:
            (status_code, error_data) 元组
        """
        import re
        import json

        error_msg = str(error)
        match = re.search(r'API error \((\d+)\)', error_msg)

        if match:
            status_code = int(match.group(1))
            try:
                json_start = error_msg.find('): ') + 3
                if json_start > 2:
                    json_str = error_msg[json_start:]
                    error_data = json_loads(json_str)
                    return status_code, error_data
            except (json.JSONDecodeError, ValueError):
                pass
            return status_code, None

        return 500, None
