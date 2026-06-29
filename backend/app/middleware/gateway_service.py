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
        self._provider_db_fingerprint: dict[int, tuple[str, str | None, str]] = {}
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

        # Order candidates: selected model first, then the remaining active
        # models (by descending priority) as fallback candidates for 429 retry.
        ordered_models = [db_model]
        remaining = [m for m in active_models if m.id != db_model.id]
        remaining.sort(key=lambda m: getattr(m, 'priority', 0) or 0, reverse=True)
        ordered_models.extend(remaining)

        resolved_candidates: List[ResolvedModelData] = []
        for m in ordered_models:
            db_provider = m.provider
            if not db_provider:
                continue
            provider_instance = await self._create_provider_instance(db_provider)
            if not provider_instance:
                continue
            resolved_candidates.append(self._build_resolved(m, db_provider, provider_instance))

        if not resolved_candidates:
            raise GatewayServiceError(
                f"Failed to create provider instance for '{model_name}'",
                status_code=500
            )

        primary = resolved_candidates[0]
        primary.fallback_candidates = resolved_candidates[1:]
        return primary

    @staticmethod
    def _build_resolved(db_model: Model, db_provider: Provider, provider_instance: BaseProvider) -> ResolvedModelData:
        """Eagerly extract all primitive fields to a plain dataclass so callers
        can close the DB session before the (potentially minute-long) LLM call.
        """
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
            api_type=getattr(db_model, 'api_type', None),
            rpm=getattr(db_model, 'rpm', None),
            tpm=getattr(db_model, 'tpm', None),
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


    @staticmethod
    async def _resolve_file_ids(request, session) -> None:
        """
        Scan all messages and metadata in the request for file_id references
        (file-xxx format) and replace them with the real object_key from
        ml_uploaded_files, prefixed with ``asset://`` for ARK asset references.

        Handles:
        - Text content: ``{{file-xxx}}`` → ``{{asset-xxx}}``
        - ContentBlock.url for IMAGE_URL / VIDEO_URL / AUDIO_URL / FILE_URL types
        - Metadata file_id_media_map: resolves URLs keyed by file_id
        """
        import re
        from sqlalchemy import select as sa_select
        from app.models import UploadedFile

        fid_pattern = re.compile(r'\bfile-[a-f0-9]{24}\b')
        template_pattern = re.compile(r'\{\{file-[a-f0-9]{24}\}\}')

        # Collect all file_ids from message content (text + block urls)
        all_file_ids = set()

        def _collect(text: str) -> None:
            if text:
                all_file_ids.update(fid_pattern.findall(text))

        for msg in request.messages:
            if msg.content:
                if isinstance(msg.content, str):
                    _collect(msg.content)
                elif isinstance(msg.content, list):
                    for block in msg.content:
                        if hasattr(block, 'text') and block.text:
                            _collect(block.text)
                        if hasattr(block, 'url') and block.url:
                            _collect(block.url)

        # Also collect from metadata file_id_media_map keys
        fid_map = request.metadata.get('file_id_media_map', {})
        if isinstance(fid_map, dict):
            all_file_ids.update(fid_map.keys())

        if not all_file_ids:
            return

        # Look up mappings from the database
        result = await session.execute(
            sa_select(UploadedFile).where(UploadedFile.file_id.in_(list(all_file_ids)))
        )
        mappings = {uf.file_id: uf.object_key for uf in result.scalars().all()}

        if not mappings:
            return

        # 1. Replace in message content
        for msg in request.messages:
            if msg.content:
                if isinstance(msg.content, str):
                    # Template patterns ({{file-xxx}}) are left as-is —
                    # the video_generation module handles them with its own
                    # numbering scheme (图片1, 视频1, etc.).
                    pass
                elif isinstance(msg.content, list):
                    for block in msg.content:
                        # Template patterns ({{file-xxx}}) in block.text
                        # are left as-is for the video_generation module.
                        # Replace in block.url (IMAGE_URL / VIDEO_URL / AUDIO_URL / FILE_URL)
                        if hasattr(block, 'url') and block.url:
                            for fid, okey in mappings.items():
                                if block.url == fid or block.url.startswith(fid):
                                    block.url = f"asset://{okey}"

        # 2. Resolve file_id_media_map in metadata
        if isinstance(fid_map, dict):
            for fid, info in list(fid_map.items()):
                if fid in mappings:
                    okey = mappings[fid]
                    # Update the URL if it's empty or matches the file_id
                    url = info.get('url', '')
                    if not url or url == fid or fid_pattern.match(url):
                        info['url'] = f"asset://{okey}"


    # ── 429 fallback helpers ──────────────────────────────────────────────

    # Maximum total attempts (primary + fallbacks) when a provider returns 429.
    MAX_RATE_LIMIT_ATTEMPTS = 3

    @staticmethod
    def _ordered_candidates(resolved: ResolvedModelData) -> List[ResolvedModelData]:
        """Return the primary candidate followed by its fallbacks, capped at
        ``MAX_RATE_LIMIT_ATTEMPTS`` total attempts."""
        candidates = [resolved]
        if resolved.fallback_candidates:
            candidates.extend(resolved.fallback_candidates)
        return candidates[:GatewayService.MAX_RATE_LIMIT_ATTEMPTS]

    @staticmethod
    def _is_rate_limit_error(exc: BaseException) -> bool:
        """Whether *exc* represents an upstream 429 (rate-limited) response."""
        if isinstance(exc, UpstreamProviderError):
            return exc.status_code == 429
        if isinstance(exc, ProviderError):
            return exc.status_code == 429
        if isinstance(exc, RuntimeError):
            status_code, _ = GatewayService._parse_provider_error(exc)
            return status_code == 429
        return False

    @staticmethod
    def _apply_candidate(resolved: ResolvedModelData, cand: ResolvedModelData) -> None:
        """Mutate *resolved* in place to reflect the candidate that actually
        served the request, so downstream usage recording uses the correct
        provider/pricing. No-op when *cand* is *resolved* itself."""
        resolved.provider_id = cand.provider_id
        resolved.provider_name = cand.provider_name
        resolved.provider_type = cand.provider_type
        resolved.model_id = cand.model_id
        resolved.model_real_name = cand.model_real_name
        resolved.input_price = cand.input_price
        resolved.output_price = cand.output_price
        resolved.cache_creation_price = cand.cache_creation_price
        resolved.cache_5m_creation_price = cand.cache_5m_creation_price
        resolved.cache_1h_creation_price = cand.cache_1h_creation_price
        resolved.cache_hit_price = cand.cache_hit_price
        resolved.currency = cand.currency
        resolved.discount = cand.discount
        resolved.pricing_tiers = cand.pricing_tiers
        resolved.output_pricing = cand.output_pricing
        resolved.api_type = cand.api_type
        resolved.support_thinking = cand.support_thinking
        resolved.support_online_image = cand.support_online_image
        resolved.support_online_video = cand.support_online_video
        resolved.support_image = cand.support_image
        resolved.support_audio = cand.support_audio
        resolved.support_video = cand.support_video
        resolved.support_embedding = cand.support_embedding
        resolved.timeout = cand.timeout
        resolved.rpm = cand.rpm
        resolved.tpm = cand.tpm
        resolved.provider_instance = cand.provider_instance

    @staticmethod
    def _convert_to_provider_error(exc: BaseException, cand: ResolvedModelData) -> ProviderError:
        """Convert a raw provider exception into a canonical ProviderError,
        tagged with the candidate that raised it."""
        if isinstance(exc, ValueError):
            raise GatewayServiceError(str(exc), status_code=400)
        if isinstance(exc, UpstreamProviderError):
            canonical_data: dict = {
                'type': exc.error_type,
                'message': str(exc),
            }
            if exc.request_id:
                canonical_data['request_id'] = exc.request_id
            return ProviderError(str(exc), status_code=exc.status_code, error_data=canonical_data,
                                 provider_id=cand.provider_id,
                                 provider_name=cand.provider_name)
        if isinstance(exc, RuntimeError):
            status_code, error_data = GatewayService._parse_provider_error(exc)
            return ProviderError(str(exc), status_code=status_code, error_data=error_data,
                                 provider_id=cand.provider_id,
                                 provider_name=cand.provider_name)
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
            return ProviderError(f"Connection to upstream provider failed: {str(exc)}", status_code=502,
                                 provider_id=cand.provider_id,
                                 provider_name=cand.provider_name)
        if isinstance(exc, httpx.HTTPError):
            return ProviderError(f"HTTP error from upstream provider: {str(exc)}", status_code=502,
                                 provider_id=cand.provider_id,
                                 provider_name=cand.provider_name)
        return ProviderError(f"Provider error: {str(exc)}", status_code=500,
                             provider_id=cand.provider_id,
                             provider_name=cand.provider_name)

    async def check_rate_limit_with_fallback(
        self,
        resolved: ResolvedModelData,
        rate_limiter,
        estimated_input_tokens: int,
        *,
        group_id: int = 0,
        workspace_id: Optional[int] = None,
        model_name: str = "",
        apikey_preview: str = "",
        apikey_rpm: Optional[int] = None,
        apikey_tpm: Optional[int] = None,
        api_key_id: Optional[int] = None,
    ) -> Tuple[ResolvedModelData, Optional[tuple], Optional[str]]:
        """Run the gateway rate-limit pre-check with 429 fallback across
        provider candidates.

        Iterates through the primary candidate and its fallbacks (capped at
        ``MAX_RATE_LIMIT_ATTEMPTS``).  For each candidate the per-provider
        model-level limits (``rpm``/``tpm``) and the provider-scoped workspace
        rate limit are looked up, then ``check_and_reserve`` is called.

        When a candidate is rejected by a **provider-scoped** rate limit
        (the workspace rate limit tied to a specific provider account —
        "供应商模型限流"), the next candidate is tried.  Rejections from
        shared limits (workspace-wide or API-key level) are returned
        immediately because switching providers cannot bypass them.

        Returns ``(chosen_candidate, rate_limit_info, None)`` on success, or
        ``(resolved, None, error_detail)`` when every applicable candidate is
        rejected.  ``rate_limit_info`` is the tuple expected by
        ``_reconcile_tpm``.
        """
        from app.models import WorkspaceRateLimit

        candidates = self._ordered_candidates(resolved)
        last_detail: Optional[str] = None

        for cand in candidates:
            # Resolve the workspace rate limit for this candidate's provider.
            ws_rpm = ws_tpm = None
            ws_provider_type = ""
            ws_provider_id = None
            ws_rl = None
            if workspace_id:
                ws_rl = await self._lookup_workspace_rate_limit(
                    workspace_id, cand, model_name,
                )
                if ws_rl:
                    ws_rpm = ws_rl.rpm
                    ws_tpm = ws_rl.tpm
                    ws_provider_type = ws_rl.provider_type or ""
                    ws_provider_id = ws_rl.provider_id

            result = await rate_limiter.check_and_reserve(
                model_id=cand.model_id,
                group_id=group_id,
                rpm_limit=cand.rpm,
                tpm_limit=cand.tpm,
                estimated_input_tokens=estimated_input_tokens,
                apikey_preview=apikey_preview,
                workspace_id=workspace_id,
                model_name=model_name,
                workspace_rpm=ws_rpm,
                workspace_tpm=ws_tpm,
                ws_provider_type=ws_provider_type,
                ws_provider_id=ws_provider_id,
                apikey_rpm=apikey_rpm,
                apikey_tpm=apikey_tpm,
                api_key_id=api_key_id,
            )

            if result.allowed:
                rate_limit_info = (
                    cand.model_id, group_id, cand.rpm, cand.tpm,
                    estimated_input_tokens, apikey_preview,
                    workspace_id, model_name, ws_tpm,
                    ws_provider_type, ws_provider_id,
                    apikey_rpm, apikey_tpm, api_key_id,
                )
                self._apply_candidate(resolved, cand)
                return resolved, rate_limit_info, None

            last_detail = result.detail or 'Rate limit exceeded'

            # Determine whether this rejection is bypassable by switching
            # providers.  Two levels are per-provider and thus bypassable:
            #
            #   1. Model-level limit (limit_level="model") — each candidate
            #      has a distinct model_id with its own RPM/TPM counter.
            #   2. Provider-scoped workspace limit (limit_level="workspace"
            #      with ws_rl.provider_id set) — "供应商模型限流", tied to a
            #      specific provider account.
            #
            # Shared limits that cannot be bypassed:
            #   - Workspace limit with provider_id=None (shared across all
            #     accounts of the same provider_type — "空间级别限流").
            #   - API-key level limit (shared regardless of provider).
            is_model_level = result.limit_level == "model"
            is_provider_scoped_ws = (
                result.limit_level == "workspace"
                and ws_rl is not None
                and ws_rl.provider_id is not None
            )
            if not (is_model_level or is_provider_scoped_ws):
                # Shared limit (workspace-wide or API-key) — cannot bypass
                # by switching providers.
                return resolved, None, last_detail

            logger.info(
                "[fallback] %s rate limit hit for provider '%s' "
                "(model_id=%s); trying next candidate...",
                result.limit_level, cand.provider_name, cand.model_id,
            )

        return resolved, None, last_detail

    async def _lookup_workspace_rate_limit(
        self, workspace_id: int, cand: ResolvedModelData, model_name: str,
    ):
        """Look up the WorkspaceRateLimit row for *cand*'s provider.

        Priority: exact provider_id match, then provider_type-wide (NULL id).
        """
        from app import get_db_session
        from app.models import WorkspaceRateLimit
        from sqlalchemy import select as sa_select

        provider_type_val = cand.provider_type
        alt_name = cand.model_alias or cand.model_real_name
        candidates_names = [model_name]
        if alt_name and alt_name != model_name:
            candidates_names.append(alt_name)

        async with get_db_session() as session:
            for try_name in candidates_names:
                result = await session.execute(
                    sa_select(WorkspaceRateLimit).where(
                        WorkspaceRateLimit.workspace_id == workspace_id,
                        WorkspaceRateLimit.model_name == try_name,
                        WorkspaceRateLimit.provider_type == provider_type_val,
                        WorkspaceRateLimit.provider_id == cand.provider_id,
                    )
                )
                ws_rl = result.scalars().first()
                if ws_rl:
                    return ws_rl
                result = await session.execute(
                    sa_select(WorkspaceRateLimit).where(
                        WorkspaceRateLimit.workspace_id == workspace_id,
                        WorkspaceRateLimit.model_name == try_name,
                        WorkspaceRateLimit.provider_type == provider_type_val,
                        WorkspaceRateLimit.provider_id.is_(None),
                    )
                )
                ws_rl = result.scalars().first()
                if ws_rl:
                    return ws_rl
        return None

    @staticmethod
    def _prepare_chat_request(cand: ResolvedModelData, request: ChatRequest, tracer: Any) -> None:
        """Update per-candidate fields on a ChatRequest before dispatch."""
        request.model = cand.model_real_name
        request.metadata['support_thinking'] = cand.support_thinking
        if cand.timeout:
            request.metadata['timeout'] = cand.timeout
        request.metadata['output_pricing'] = cand.output_pricing
        cand.provider_instance.tracer = tracer
        cand.provider_instance._model_api_type = cand.api_type
        if tracer:
            tracer.set_metadata({
                "provider_id": cand.provider_id,
                "provider": cand.provider_name,
            })

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

        # 3.5 Resolve file_id → object_key references from uploaded files
        from app import get_db_session
        try:
            async with get_db_session() as session:
                await self._resolve_file_ids(request, session)
        except Exception as e:
            import logging
            logging.getLogger("gateway").warning(
                "gateway_service: failed to resolve file_ids: %s", e
            )

        # 4. 调用供应商 API（429 时按候选顺序最多重试 MAX_RATE_LIMIT_ATTEMPTS 次）
        candidates = self._ordered_candidates(resolved)
        last_exc: Optional[BaseException] = None
        for attempt, cand in enumerate(candidates):
            self._prepare_chat_request(cand, request, tracer)
            try:
                response = await cand.provider_instance.chat(request)

                if not self._should_include_reasoning(request):
                    for choice in response.choices:
                        choice.reasoning_content = None
                        if choice.message:
                            choice.message.reasoning_content = None

                self._apply_candidate(resolved, cand)
                return response
            except ValueError as e:
                raise GatewayServiceError(str(e), status_code=400)
            except (UpstreamProviderError, RuntimeError, httpx.HTTPError) as e:
                if self._is_rate_limit_error(e) and attempt < len(candidates) - 1:
                    logger.warning(
                        "[fallback] 429 from provider '%s' (model_id=%s); "
                        "trying next candidate (%d/%d)...",
                        cand.provider_name, cand.model_id,
                        attempt + 2, len(candidates),
                    )
                    last_exc = e
                    continue
                raise self._convert_to_provider_error(e, cand)
            except Exception as e:
                raise self._convert_to_provider_error(e, cand)

        # All candidates exhausted with rate-limit errors
        if last_exc is not None:
            raise self._convert_to_provider_error(last_exc, candidates[-1])
        raise ProviderError("All provider candidates exhausted", status_code=502,
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

        # Resolve file_id → object_key references from uploaded files
        from app import get_db_session
        try:
            async with get_db_session() as session:
                await self._resolve_file_ids(request, session)
        except Exception as e:
            import logging
            logging.getLogger("gateway").warning(
                "gateway_service: failed to resolve file_ids in stream_chat: %s", e
            )

        # 4. Determine reasoning flag
        include_reasoning = self._should_include_reasoning(request)

        # 5. Return lazy async generator with 429 fallback across candidates.
        candidates = self._ordered_candidates(resolved)

        async def _stream():
            last_exc: Optional[BaseException] = None
            for attempt, cand in enumerate(candidates):
                self._prepare_chat_request(cand, request, tracer)
                yielded_any = False
                try:
                    async for chunk in cand.provider_instance.stream_chat(request):
                        yielded_any = True
                        if not include_reasoning:
                            chunk.delta_reasoning_content = None
                        yield chunk
                    # Stream completed successfully on this candidate.
                    self._apply_candidate(resolved, cand)
                    return
                except ValueError as e:
                    raise GatewayServiceError(str(e), status_code=400)
                except (UpstreamProviderError, RuntimeError, httpx.HTTPError) as e:
                    # Only retry if nothing has been streamed yet — once bytes
                    # have been sent to the client we cannot switch providers.
                    if not yielded_any and self._is_rate_limit_error(e) and attempt < len(candidates) - 1:
                        logger.warning(
                            "[fallback] 429 from provider '%s' (model_id=%s) during stream; "
                            "trying next candidate (%d/%d)...",
                            cand.provider_name, cand.model_id,
                            attempt + 2, len(candidates),
                        )
                        last_exc = e
                        continue
                    raise self._convert_to_provider_error(e, cand)
                except Exception as e:
                    raise self._convert_to_provider_error(e, cand)

            if last_exc is not None:
                raise self._convert_to_provider_error(last_exc, candidates[-1])

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
        raw_type = db_provider.type or ""

        # Fast path: cache hit with unchanged credentials AND type.
        if cache_key in self._provider_cache:
            cached = self._provider_cache[cache_key]
            prev_key, prev_url, prev_type = self._provider_db_fingerprint.get(cache_key, ("", None, ""))
            if raw_api_key == prev_key and raw_base_url == prev_url and raw_type == prev_type:
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
                prev_key, prev_url, prev_type = self._provider_db_fingerprint.get(cache_key, ("", None, ""))
                if raw_api_key != prev_key or raw_base_url != prev_url or raw_type != prev_type:
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
                self._provider_db_fingerprint[cache_key] = (raw_api_key, raw_base_url, raw_type)
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

        # Collect every IMAGE_URL block (including those nested inside
        # tool_result content), then download them all in parallel.
        # Each target is (parent_list, index, block) — the parent list is
        # either a message.content list or a ContentBlock.tool_result list.
        targets: List[tuple[list, int, ContentBlock]] = []

        def _collect(container: list) -> None:
            for i, block in enumerate(container):
                if not isinstance(block, ContentBlock):
                    continue
                if block.type == ContentType.IMAGE_URL and block.url:
                    targets.append((container, i, block))
                elif block.type == ContentType.TOOL_RESULT:
                    tr = block.tool_result
                    if isinstance(tr, list):
                        _collect(tr)

        for message in request.messages:
            if isinstance(message.content, list):
                _collect(message.content)

        if not targets:
            return

        results = await asyncio.gather(*(_download_and_encode(b) for _, _, b in targets))
        for (parent_list, idx, _), new_block in zip(targets, results):
            parent_list[idx] = new_block

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

        targets: List[tuple[list, int, ContentBlock]] = []

        def _collect(container: list) -> None:
            for i, block in enumerate(container):
                if not isinstance(block, ContentBlock):
                    continue
                if block.type == ContentType.VIDEO_URL and block.url:
                    targets.append((container, i, block))
                elif block.type == ContentType.TOOL_RESULT:
                    tr = block.tool_result
                    if isinstance(tr, list):
                        _collect(tr)

        for message in request.messages:
            if isinstance(message.content, list):
                _collect(message.content)

        if not targets:
            return

        results = await asyncio.gather(*(_download_and_encode(b) for _, _, b in targets))
        for (parent_list, idx, _), new_block in zip(targets, results):
            parent_list[idx] = new_block

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
        # 429 时按候选顺序最多重试 MAX_RATE_LIMIT_ATTEMPTS 次
        candidates = self._ordered_candidates(resolved)
        last_exc: Optional[BaseException] = None
        for attempt, cand in enumerate(candidates):
            request.model = cand.model_real_name
            if not hasattr(cand.provider_instance, 'rerank'):
                if attempt < len(candidates) - 1:
                    continue
                raise GatewayServiceError(
                    f"Provider '{cand.provider_name}' does not support rerank",
                    status_code=400
                )

            try:
                response = await cand.provider_instance.rerank(request)
                self._apply_candidate(resolved, cand)
                return response
            except ValueError as e:
                raise GatewayServiceError(str(e), status_code=400)
            except (UpstreamProviderError, RuntimeError, httpx.HTTPError) as e:
                if self._is_rate_limit_error(e) and attempt < len(candidates) - 1:
                    logger.warning(
                        "[fallback] 429 from provider '%s' (model_id=%s) during rerank; "
                        "trying next candidate (%d/%d)...",
                        cand.provider_name, cand.model_id,
                        attempt + 2, len(candidates),
                    )
                    last_exc = e
                    continue
                raise self._convert_to_provider_error(e, cand)
            except Exception as e:
                raise self._convert_to_provider_error(e, cand)

        if last_exc is not None:
            raise self._convert_to_provider_error(last_exc, candidates[-1])
        raise ProviderError("All provider candidates exhausted", status_code=502,
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

        # 429 时按候选顺序最多重试 MAX_RATE_LIMIT_ATTEMPTS 次
        candidates = self._ordered_candidates(resolved)
        last_exc: Optional[BaseException] = None
        for attempt, cand in enumerate(candidates):
            if not cand.support_embedding:
                if attempt < len(candidates) - 1:
                    continue
                raise GatewayServiceError(
                    f"Model '{cand.model_alias or cand.model_real_name}' is not an embedding model. "
                    f"Set support_embedding=true for this model in the admin panel.",
                    status_code=400
                )
            if not hasattr(cand.provider_instance, 'embed'):
                if attempt < len(candidates) - 1:
                    continue
                raise GatewayServiceError(
                    f"Provider '{cand.provider_name}' does not support embedding",
                    status_code=400
                )
            request.model = cand.model_real_name
            request.metadata['support_image'] = cand.support_image
            request.metadata['support_video'] = cand.support_video
            request.metadata['support_audio'] = cand.support_audio
            cand.provider_instance.tracer = tracer
            if tracer:
                tracer.set_metadata({
                    "provider_id": cand.provider_id,
                    "provider": cand.provider_name,
                })
            try:
                response = await cand.provider_instance.embed(request)
                self._apply_candidate(resolved, cand)
                return response
            except ValueError as e:
                raise GatewayServiceError(str(e), status_code=400)
            except (UpstreamProviderError, RuntimeError, httpx.HTTPError) as e:
                if self._is_rate_limit_error(e) and attempt < len(candidates) - 1:
                    logger.warning(
                        "[fallback] 429 from provider '%s' (model_id=%s) during embed; "
                        "trying next candidate (%d/%d)...",
                        cand.provider_name, cand.model_id,
                        attempt + 2, len(candidates),
                    )
                    last_exc = e
                    continue
                raise self._convert_to_provider_error(e, cand)
            except Exception as e:
                raise self._convert_to_provider_error(e, cand)

        if last_exc is not None:
            raise self._convert_to_provider_error(last_exc, candidates[-1])
        raise ProviderError("All provider candidates exhausted", status_code=502,
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
