"""
AI Gateway API 路由层
提供 OpenAI、Anthropic 兼容的聊天补全端点，以及模型列表、供应商管理端点。
Embeddings、Images、Rerank、Responses API 端点已拆分至独立模块。

三层架构：
  API 层 (Routes/Adapters) → 中间层 (GatewayService) → 供应商层 (Providers)

请求生命周期 (no DB connection held across LLM call):
  Phase 1: auth (short DB session, closes immediately)
  Phase 2: resolve model + rate-limit pre-check (short DB session, closes immediately)
  Phase 3: LLM upstream call (NO DB session)
  Phase 4: usage record (fire-and-forget background task, own short session)
"""
from quart import Blueprint, request, jsonify, g
import logging
import time
from typing import Optional

# Configure logger for gateway
logger = logging.getLogger("gateway")

from sqlalchemy import select as sa_select
from sqlalchemy.orm import selectinload

from app import get_db_session
from app.models import Provider, Model
from app.monitoring import create_tracer
from app.group_service import get_group_monitoring_config

# 导入中间层
from app.middleware.gateway_service import (
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)

# 导入适配器
from app.adapters.openai_adapter import OpenAIChatAdapter
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter

# 导入供应商注册信息（仅用于管理端点）
from app.providers import get_provider_class, list_providers
from app.providers.base import ProviderConfig

# 导入共享的认证/解析/日志工具
from app.routes.gateway_helpers import (
    _gateway_service,
    get_current_user_or_api_key,
    _parse_json_body,
    _log_error,
    _check_allowed_models,
    _build_error_context,
)

gateway_bp = Blueprint('gateway', __name__)


async def _resolve_workspace_rate_limit(
    session,
    resolved,
    model_name: str,
    workspace_id: Optional[int],
):
    """Look up the WorkspaceRateLimit row that applies to (workspace, model, provider).

    Returns (ws_rl, model_name_for_ws). Caller must pass an open async session.
    """
    from app.models import WorkspaceRateLimit

    if not workspace_id or not resolved:
        return None, model_name

    provider_type_val = resolved.provider_type
    provider_id_val = resolved.provider_id
    alt_name = resolved.model_alias or resolved.model_real_name
    candidates = [model_name]
    if alt_name and alt_name != model_name:
        candidates.append(alt_name)

    for try_name in candidates:
        # Priority 1: exact provider_id match
        result = await session.execute(
            sa_select(WorkspaceRateLimit).where(
                WorkspaceRateLimit.workspace_id == workspace_id,
                WorkspaceRateLimit.model_name == try_name,
                WorkspaceRateLimit.provider_type == provider_type_val,
                WorkspaceRateLimit.provider_id == provider_id_val,
            )
        )
        ws_rl = result.scalars().first()
        if ws_rl:
            return ws_rl, try_name
        # Priority 2: shared provider_type (provider_id=NULL)
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
            return ws_rl, try_name

    return None, model_name


async def _reconcile_tpm(rate_limiter, rate_limit_info, actual_input_tokens: int = 0) -> None:
    """Reconcile pre-estimated TPM with actual input tokens after the request."""
    if rate_limiter is None or rate_limit_info is None:
        return
    if actual_input_tokens <= 0:
        return
    try:
        model_id, group_id, rpm_limit, tpm_limit, estimated_tokens, apikey_preview, \
            workspace_id, model_name, workspace_tpm, ws_provider_type, ws_provider_id, \
            apikey_rpm, apikey_tpm, api_key_id = rate_limit_info
        await rate_limiter.reconcile(
            model_id=model_id,
            group_id=group_id,
            tpm_limit=tpm_limit,
            pre_estimated_tokens=estimated_tokens,
            actual_input_tokens=actual_input_tokens,
            apikey_preview=apikey_preview,
            workspace_id=workspace_id,
            model_name=model_name,
            workspace_tpm=workspace_tpm,
            ws_provider_type=ws_provider_type,
            ws_provider_id=ws_provider_id,
            apikey_tpm=apikey_tpm,
            api_key_id=api_key_id,
        )
    except Exception as e:
        logger.warning(f"[rate_limiter] TPM reconciliation failed: {e}")


# ============== 统一请求处理 ==============

async def _handle_request(adapter):
    """
    统一的请求处理函数（phased DB session lifecycle —— LLM 调用期间不持有 DB 连接）。
    """
    # ─── Phase 1: 认证 (short session, closes inside) ───
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("handle_request", status, error.get('detail', 'Not authenticated'), exc_info=True)
        return jsonify(adapter.format_error_response(error.get('detail', 'Not authenticated'), status)), status

    # Parse request body
    data = await _parse_json_body()
    if not data:
        _log_error("handle_request", 400, "Invalid or empty JSON request body", _build_error_context(auth_ctx), exc_info=True)
        return jsonify(adapter.format_error_response('Invalid or empty JSON request body', 400)), 400

    model_name = data.get('model')
    if not model_name:
        _log_error("handle_request", 400, "Model is required", _build_error_context(auth_ctx), exc_info=True)
        return jsonify(adapter.format_error_response('Model is required', 400)), 400

    # ACL check
    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("handle_request", 403, acl_error['detail'], _build_error_context(auth_ctx, model_name), exc_info=True)
        return jsonify(adapter.format_error_response(acl_error['detail'], 403)), 403

    try:
        chat_request = adapter.parse_request(data)
    except Exception as e:
        _log_error("handle_request", 400, f"Invalid request format: {e}", _build_error_context(auth_ctx, model_name), exc_info=True)
        return jsonify(adapter.format_error_response(f'Invalid request format: {str(e)}', 400)), 400

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ─── Phase 2: resolve model + rate-limit pre-check (single short session) ───
    resolved = None
    rate_limiter = None
    rate_limit_info = None
    monitoring_config = None
    try:
        async with get_db_session() as session:
            try:
                resolved = await _gateway_service.resolve_model(
                    session, model_name, group_id, provider_id=provider_id
                )
            except ModelNotFoundError as e:
                _log_error("handle_request", e.status_code, e.message, _build_error_context(auth_ctx, model_name), exc_info=True)
                return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code
            except GatewayServiceError as e:
                _log_error("handle_request", e.status_code, e.message, _build_error_context(auth_ctx, model_name), exc_info=True)
                return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code

            # Pass the model's configured API type to the provider for upstream routing
            resolved.provider_instance._model_api_type = resolved.api_type

            # Rate-limit pre-check
            try:
                from app.rate_limiter import get_async_rate_limiter, estimate_input_tokens
                rate_limiter = get_async_rate_limiter()

                workspace_id = auth_ctx.api_key_workspace_id if auth_ctx else None
                ws_rl, model_name_for_ws = await _resolve_workspace_rate_limit(
                    session, resolved, model_name, workspace_id,
                )

                # Model-level rpm/tpm — already in ResolvedModelData? No, query directly.
                # The per-model rpm/tpm are on the Model row; resolve_model didn't snapshot them.
                # Fetch them here while session is open.
                from app.models import Model as ModelOrm
                model_row = (await session.execute(
                    sa_select(ModelOrm.rpm, ModelOrm.tpm).where(ModelOrm.id == resolved.model_id)
                )).first()
                rpm_limit = model_row[0] if model_row else None
                tpm_limit = model_row[1] if model_row else None

                workspace_rpm = ws_rl.rpm if ws_rl else None
                workspace_tpm = ws_rl.tpm if ws_rl else None
                ws_provider_type = ws_rl.provider_type if ws_rl else ""
                ws_provider_id_val = ws_rl.provider_id if ws_rl else None

                apikey_rpm = auth_ctx.api_key_rpm if auth_ctx else None
                apikey_tpm = auth_ctx.api_key_tpm if auth_ctx else None
                api_key_id = auth_ctx.api_key_id if auth_ctx else None

                has_any_limit = rpm_limit or tpm_limit or workspace_rpm or workspace_tpm or apikey_rpm or apikey_tpm
                if has_any_limit:
                    messages_list = data.get('messages', [])
                    system_prompt = None
                    for msg in messages_list:
                        if isinstance(msg, dict) and msg.get('role') == 'system':
                            system_prompt = msg.get('content', '')
                            break
                    if not system_prompt:
                        system_prompt = data.get('system')
                    tools = data.get('tools')
                    estimated_tokens = estimate_input_tokens(messages_list, system_prompt, tools)

                    apikey_preview = ''
                    if auth_ctx and auth_ctx.api_key_raw:
                        apikey_preview = auth_ctx.api_key_raw[:8] + '...'

                    result = await rate_limiter.check_and_reserve(
                        model_id=resolved.model_id,
                        group_id=group_id or 0,
                        rpm_limit=rpm_limit,
                        tpm_limit=tpm_limit,
                        estimated_input_tokens=estimated_tokens,
                        apikey_preview=apikey_preview,
                        workspace_id=workspace_id,
                        model_name=model_name_for_ws,
                        workspace_rpm=workspace_rpm,
                        workspace_tpm=workspace_tpm,
                        ws_provider_type=ws_provider_type,
                        ws_provider_id=ws_provider_id_val,
                        apikey_rpm=apikey_rpm,
                        apikey_tpm=apikey_tpm,
                        api_key_id=api_key_id,
                    )
                    if not result.allowed:
                        rate_limit_extra = _build_error_context(auth_ctx, model_name)
                        rate_limit_extra["rate_limit_detail"] = result.detail
                        _log_error("handle_request", 429, result.detail or 'Rate limit exceeded', rate_limit_extra)
                        return jsonify(adapter.format_error_response(
                            result.detail or 'Rate limit exceeded', 429
                        )), 429

                    rate_limit_info = (
                        resolved.model_id, group_id or 0, rpm_limit, tpm_limit,
                        estimated_tokens, apikey_preview,
                        workspace_id, model_name_for_ws, workspace_tpm,
                        ws_provider_type, ws_provider_id_val,
                        apikey_rpm, apikey_tpm, api_key_id,
                    )
            except ModelNotFoundError:
                pass
            except Exception as e:
                logger.error(f"[rate_limiter] Pre-check failed, skipping: {e}", exc_info=True)

            # Fetch monitoring config while session is still open
            if group_id:
                try:
                    monitoring_config = await get_group_monitoring_config(group_id, session=session)
                except Exception as _e:
                    logger.debug(f"[monitoring] fetch config failed: {_e}")
        # ← session closes here. DB connection returned to pool.
    except Exception as e:
        logger.error(f"[handle_request] Phase-2 (resolve/rate-limit) error: {e}", exc_info=True)
        return jsonify(adapter.format_error_response(f'Internal error: {e}', 500)), 500

    tracer = create_tracer(monitoring_config)

    # ─── Phase 3: LLM upstream call (NO DB session held) ───
    _request_start_time = time.monotonic()
    _request_id = g.request_id

    try:
        if chat_request.stream:
            if tracer:
                tracer.start(model_name, input_data=data, session_id=chat_request.session_id)
                tracer.log_input(data)
                tracer.set_metadata({
                    "request_id": _request_id,
                    "group_id": group_id,
                    "user": auth_ctx.user_name if auth_ctx else None,
                    "model_name": model_name,
                    "api_key_name": auth_ctx.api_key_name if auth_ctx else None,
                })

            chunks_gen = await _gateway_service.stream_chat(resolved, chat_request, tracer=tracer)

            async def _chunks_with_usage_recording():
                last_usage = None
                _accumulated_extra = {}
                _content_parts: list[str] = []
                _last_chunk_meta = {}  # track id/model/created for price chunk
                try:
                    async for chunk in chunks_gen:
                        if chunk.usage is not None:
                            if hasattr(chunk.usage, 'extra') and chunk.usage.extra:
                                _accumulated_extra.update(chunk.usage.extra)
                            last_usage = chunk.usage
                        if chunk.delta_content:
                            _content_parts.append(chunk.delta_content)
                        # Track metadata from the last chunk for price
                        if chunk.id:
                            _last_chunk_meta['id'] = chunk.id
                        if chunk.model:
                            _last_chunk_meta['model'] = chunk.model
                        if chunk.created:
                            _last_chunk_meta['created'] = chunk.created
                        yield chunk
                    if last_usage is not None and _accumulated_extra:
                        if hasattr(last_usage, 'extra'):
                            for k, v in _accumulated_extra.items():
                                if k not in last_usage.extra:
                                    last_usage.extra[k] = v
                        else:
                            last_usage.extra = _accumulated_extra
                    # Calculate and yield price chunk after stream completes
                    if last_usage is not None:
                        from app.usagerecord.usage_service import calculate_price
                        from app.abstraction.streaming import StreamChunk
                        last_usage.price = calculate_price(
                            usage=last_usage,
                            input_price_unit=resolved.input_price,
                            output_price_unit=resolved.output_price,
                            cache_creation_price_unit=resolved.cache_creation_price,
                            cache_5m_creation_price_unit=resolved.cache_5m_creation_price,
                            cache_1h_creation_price_unit=resolved.cache_1h_creation_price,
                            cache_token_price_unit=resolved.cache_hit_price,
                            pricing_tiers=resolved.pricing_tiers,
                            output_pricing=resolved.output_pricing,
                            currency=resolved.currency,
                            discount=resolved.discount,
                        )
                        price_chunk = StreamChunk(
                            id=_last_chunk_meta.get('id', ''),
                            model=_last_chunk_meta.get('model', model_name),
                            created=_last_chunk_meta.get('created', int(time.time())),
                            usage=last_usage,
                        )
                        yield price_chunk
                    if tracer:
                        tracer.log_output({
                            "content": "".join(_content_parts) if _content_parts else None,
                            "usage": last_usage.to_dict() if last_usage else None,
                        })
                except Exception as e:
                    _log_error("handle_request", 500, f"Stream processing error: {e}",
                               {"model": model_name, "group_id": group_id}, exc_info=True)
                    if tracer:
                        tracer.set_metadata({"request_id": _request_id, "model_name": model_name,
                                             "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
                        tracer.end(error=e)
                    raise
                finally:
                    if last_usage is not None:
                        try:
                            await _reconcile_tpm(rate_limiter, rate_limit_info, last_usage.prompt_tokens if last_usage else 0)
                        except Exception as _e:
                            logger.warning(f"[rate_limiter] Stream TPM reconciliation failed: {_e}")
                        try:
                            from app.usagerecord.usage_service import record_stream_usage
                            _duration_ms = int((time.monotonic() - _request_start_time) * 1000)
                            await record_stream_usage(
                                usage_info=last_usage,
                                user_name=auth_ctx.user_name if auth_ctx else None,
                                user_id=auth_ctx.user_id if auth_ctx else None,
                                api_key_raw=auth_ctx.api_key_raw if auth_ctx else None,
                                api_key_name=auth_ctx.api_key_name if auth_ctx else None,
                                api_key_group_id=auth_ctx.api_key_group_id if auth_ctx else None,
                                api_key_group_name=auth_ctx.api_key_group_name if auth_ctx else None,
                                model_name=model_name,
                                provider_id=resolved.provider_id,
                                provider_name=resolved.provider_name,
                                input_price_unit=resolved.input_price,
                                output_price_unit=resolved.output_price,
                                cache_creation_price_unit=resolved.cache_creation_price,
                                cache_5m_creation_price_unit=resolved.cache_5m_creation_price,
                                cache_1h_creation_price_unit=resolved.cache_1h_creation_price,
                                cache_token_price_unit=resolved.cache_hit_price,
                                pricing_tiers=resolved.pricing_tiers,
                                output_pricing=resolved.output_pricing,
                                currency=resolved.currency,
                                discount=resolved.discount,
                                duration_ms=_duration_ms,
                            )
                        except Exception as _ue:
                            logger.warning(f"[usage] Failed to trigger stream usage recording: {_ue}")
                    if tracer:
                        tracer.end()

            return adapter.create_stream_response(_chunks_with_usage_recording(), model_name)

        else:
            if tracer:
                tracer.start(model_name, input_data=data, session_id=chat_request.session_id)
                tracer.log_input(data)
                tracer.set_metadata({
                    "request_id": _request_id,
                    "group_id": group_id,
                    "user": auth_ctx.user_name if auth_ctx else None,
                    "model_name": model_name,
                    "api_key_name": auth_ctx.api_key_name if auth_ctx else None,
                })

            response = await _gateway_service.chat(resolved, chat_request, tracer=tracer)
            _duration_ms = int((time.monotonic() - _request_start_time) * 1000)

            if tracer:
                tracer.log_output(adapter.format_response(response))
                tracer.set_metadata({"duration_ms": _duration_ms})
                tracer.end()

            await _reconcile_tpm(rate_limiter, rate_limit_info, response.usage.prompt_tokens if response and response.usage else 0)

            # ─── Phase 4: usage record (fire-and-forget, own short session) ───
            try:
                from app.usagerecord.usage_service import record_usage, calculate_price
                # Attach price info to usage for API response
                response.usage.price = calculate_price(
                    usage=response.usage,
                    input_price_unit=resolved.input_price,
                    output_price_unit=resolved.output_price,
                    cache_creation_price_unit=resolved.cache_creation_price,
                    cache_5m_creation_price_unit=resolved.cache_5m_creation_price,
                    cache_1h_creation_price_unit=resolved.cache_1h_creation_price,
                    cache_token_price_unit=resolved.cache_hit_price,
                    pricing_tiers=resolved.pricing_tiers,
                    output_pricing=resolved.output_pricing,
                    currency=resolved.currency,
                    discount=resolved.discount,
                )
                await record_usage(
                    response=response,
                    user_name=auth_ctx.user_name if auth_ctx else None,
                    user_id=auth_ctx.user_id if auth_ctx else None,
                    api_key_raw=auth_ctx.api_key_raw if auth_ctx else None,
                    api_key_name=auth_ctx.api_key_name if auth_ctx else None,
                    api_key_group_id=auth_ctx.api_key_group_id if auth_ctx else None,
                    api_key_group_name=auth_ctx.api_key_group_name if auth_ctx else None,
                    model_name=model_name,
                    provider_id=resolved.provider_id,
                    provider_name=resolved.provider_name,
                    input_price_unit=resolved.input_price,
                    output_price_unit=resolved.output_price,
                    cache_creation_price_unit=resolved.cache_creation_price,
                    cache_5m_creation_price_unit=resolved.cache_5m_creation_price,
                    cache_1h_creation_price_unit=resolved.cache_1h_creation_price,
                    cache_token_price_unit=resolved.cache_hit_price,
                    pricing_tiers=resolved.pricing_tiers,
                    output_pricing=resolved.output_pricing,
                    currency=resolved.currency,
                    discount=resolved.discount,
                    duration_ms=_duration_ms,
                )
            except Exception as _ue:
                logger.warning(f"[usage] Failed to trigger usage recording: {_ue}")
            return jsonify(adapter.format_response(response))

    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": _request_id, "model_name": model_name,
                                 "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        error_extra = _build_error_context(auth_ctx, model_name,
                                           provider_id=e.provider_id,
                                           provider_name=e.provider_name)
        if e.error_data:
            error_extra["error_data"] = e.error_data
        _log_error("handle_request", e.status_code, e.message, error_extra, exc_info=True)
        return jsonify(adapter.format_error_response(e.message, e.status_code, e.error_data)), e.status_code
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": _request_id, "model_name": model_name,
                                 "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("handle_request", e.status_code, e.message, _build_error_context(auth_ctx, model_name), exc_info=True)
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": _request_id, "model_name": model_name,
                                 "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("handle_request", e.status_code, e.message, _build_error_context(auth_ctx, model_name), exc_info=True)
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code


# ============== API 端点 ==============

@gateway_bp.route('/v1/chat/completions', methods=['POST', 'HEAD', 'OPTIONS'])
async def chat_completions():
    """OpenAI-compatible chat completions endpoint."""
    if request.method == 'HEAD' or request.method == 'OPTIONS':
        return '', 200
    return await _handle_request(OpenAIChatAdapter())


@gateway_bp.route('/v1/messages', methods=['POST', 'HEAD', 'OPTIONS'])
async def anthropic_messages():
    """Anthropic-compatible messages endpoint."""
    if request.method == 'HEAD' or request.method == 'OPTIONS':
        return '', 200
    return await _handle_request(AnthropicMessagesAdapter())


# ============== 模型列表 ==============

@gateway_bp.route('/v1/models', methods=['GET'])
async def list_models():
    """List all available models (OpenAI compatible)."""
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        return jsonify(error), status

    async with get_db_session() as session:
        if auth_ctx and auth_ctx.api_key_id is not None:
            from app.models import get_group_models_with_shares
            model_provider_pairs = await get_group_models_with_shares(auth_ctx.api_key_group_id, session=session)
        else:
            result = await session.execute(
                sa_select(Provider).options(selectinload(Provider.models)).where(Provider.is_active == True)
            )
            providers = result.scalars().all()
            model_provider_pairs = []
            seen = set()
            for provider in providers:
                for model in provider.models:
                    if model.is_active and model.id not in seen:
                        seen.add(model.id)
                        model_provider_pairs.append((model, provider))

        allowed_models = auth_ctx.allowed_models if auth_ctx else None

        seen_ids = set()
        models_list = []
        for model, provider in model_provider_pairs:
            if allowed_models:
                if model.name not in allowed_models and (not model.alias or model.alias not in allowed_models):
                    continue
            model_id = model.alias if model.alias else model.name
            if model_id in seen_ids:
                continue
            seen_ids.add(model_id)
            models_list.append({
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": provider.name,
                "permission": [],
                "root": model.name,
                "parent": None,
            })

    return jsonify({
        "object": "list",
        "data": models_list
    })


# ============== 供应商管理端点 ==============

@gateway_bp.route('/v1/providers', methods=['GET'])
async def list_providers_api():
    """列出所有已注册的供应商类型"""
    providers = list_providers()
    return jsonify({
        "providers": providers
    })


@gateway_bp.route('/v1/providers/<provider_type>/models', methods=['GET'])
async def list_provider_models(provider_type: str):
    """列出供应商支持的模型"""
    provider_class = get_provider_class(provider_type)

    if not provider_class:
        return jsonify({'detail': f'Provider type {provider_type} not found'}), 404

    config = ProviderConfig(
        name=provider_type,
        api_key="",
        base_url=None
    )

    try:
        instance = provider_class(config)
        if hasattr(instance, 'list_models'):
            models = instance.list_models()
            return jsonify({
                "object": "list",
                "data": models
            })
        else:
            return jsonify({
                "object": "list",
                "data": []
            })
    except Exception as e:
        return jsonify({'detail': f'Error listing models: {str(e)}'}), 500
