"""
AI Gateway API 路由层
提供 OpenAI、Anthropic 兼容的聊天补全端点，以及模型列表、供应商管理端点。
Embeddings、Images、Rerank、Responses API 端点已拆分至独立模块。

三层架构：
  API 层 (Routes/Adapters) → 中间层 (GatewayService) → 供应商层 (Providers)

路由层职责：
  1. 认证 - 验证用户身份或 API Key
  2. 格式转换 - 使用 Adapter 在 API 格式和内部格式之间转换
  3. HTTP 响应 - 构建正确的 HTTP 响应（包括流式响应）

路由层不关心：
  - 具体使用哪个供应商（由中间层决定）
  - 供应商 API 的差异（由供应商层处理）
"""
from quart import Blueprint, request, jsonify, current_app, g
import logging
import time

# Configure logger for gateway
logger = logging.getLogger("gateway")

from sqlalchemy import select as sa_select

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
    G_API_KEY_PROVIDER_ID,
)

gateway_bp = Blueprint('gateway', __name__)




async def _resolve_for_rate_limit(model_name, group_id, provider_id, api_key):
    """Resolve model + query workspace rate limits."""
    from app.models import WorkspaceRateLimit
    from sqlalchemy import select as sa_select

    resolved = await _gateway_service.resolve_model(model_name, group_id, provider_id=provider_id)
    db_model = resolved.db_model

    workspace_id = None
    ws_rl = None
    model_name_for_ws = model_name

    if api_key:
        workspace_id = getattr(api_key, 'workspace_id', None)
        if not workspace_id and api_key.group:
            workspace_id = getattr(api_key.group, 'workspace_id', None)

    if workspace_id and db_model and db_model.provider:
        session = g.db_session
        provider_type_val = db_model.provider.type
        provider_id_val = db_model.provider_id
        alt_name = db_model.alias or db_model.name
        for try_name in ([model_name] + ([alt_name] if alt_name != model_name else [])):
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
                model_name_for_ws = try_name
                break
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
                model_name_for_ws = try_name
                break

    return resolved, db_model, workspace_id, ws_rl, model_name_for_ws


async def _reconcile_tpm(rate_limiter, rate_limit_info, actual_input_tokens: int = 0) -> None:
    """Reconcile pre-estimated TPM with actual input tokens after the request.

    rate_limit_info = (model_id, group_id, rpm_limit, tpm_limit, estimated_tokens, apikey_preview,
                       workspace_id, model_name, workspace_tpm, ws_provider_type, ws_provider_id,
                       apikey_rpm, apikey_tpm, api_key_id)
    """
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
    统一的请求处理函数。

    所有 API 端点共用此函数，只需传入不同的适配器：
    - OpenAIChatAdapter: /v1/chat/completions
    - AnthropicMessagesAdapter: /v1/messages
    - OpenAIResponsesAdapter: /v1/responses

    流程：
    1. 认证
    2. 解析请求（Adapter: 外部格式 → ChatRequest）
    3. 调用中间层（GatewayService: ChatRequest → ChatResponse）
    4. 格式化响应（Adapter: ChatResponse → 外部格式）
    """
    # 1. 认证
    user, api_key, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("handle_request", status, error.get('detail', 'Not authenticated'), exc_info=True)
        return jsonify(adapter.format_error_response(error.get('detail', 'Not authenticated'), status)), status

    # 2. 获取请求数据
    data = await _parse_json_body()

    if not data:
        _log_error("handle_request", 400, "Invalid or empty JSON request body", _build_error_context(api_key), exc_info=True)
        return jsonify(adapter.format_error_response('Invalid or empty JSON request body', 400)), 400

    model_name = data.get('model')
    if not model_name:
        _log_error("handle_request", 400, "Model is required", _build_error_context(api_key), exc_info=True)
        return jsonify(adapter.format_error_response('Model is required', 400)), 400

    # 2.5. 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        _log_error("handle_request", 403, acl_error['detail'], _build_error_context(api_key, model_name), exc_info=True)
        return jsonify(adapter.format_error_response(acl_error['detail'], 403)), 403

    # 3. 使用适配器解析请求
    try:
        chat_request = adapter.parse_request(data)
    except Exception as e:
        _log_error("handle_request", 400, f"Invalid request format: {e}", _build_error_context(api_key, model_name), exc_info=True)
        return jsonify(adapter.format_error_response(f'Invalid request format: {str(e)}', 400)), 400

    # 4. 获取组 ID（用于访问控制）
    group_id = api_key.group_id if api_key else None

    # 4.1. 获取 API Key 指定的供应商 ID（通过 sk-xxx-{providerId} 后缀）
    provider_id = g.get(G_API_KEY_PROVIDER_ID, None) if api_key else None

    # 4.5. 限流检查 — RPM / TPM 预扣 (group-level + workspace-level)
    rate_limiter = None
    rate_limit_info = None  # (model_id, group_id, rpm_limit, tpm_limit, estimated_tokens, apikey_preview, workspace_id, model_name_for_ws, workspace_tpm)
    try:
        from app.rate_limiter import get_async_rate_limiter, estimate_input_tokens
        rate_limiter = get_async_rate_limiter()
        # Resolve model + workspace rate limits
        _, db_model_rl, workspace_id, _ws_rl, model_name_for_ws = (
            await _resolve_for_rate_limit(
                model_name, group_id, provider_id, api_key,
            )
        )
        rpm_limit = getattr(db_model_rl, 'rpm', None)
        tpm_limit = getattr(db_model_rl, 'tpm', None)

        workspace_rpm = None
        workspace_tpm = None
        ws_provider_type = ""
        ws_provider_id_val = None
        if _ws_rl:
            workspace_rpm = _ws_rl.rpm
            workspace_tpm = _ws_rl.tpm
            ws_provider_type = _ws_rl.provider_type
            ws_provider_id_val = _ws_rl.provider_id

        # API-key-level rate limits
        apikey_rpm = getattr(api_key, 'rpm', None) if api_key else None
        apikey_tpm = getattr(api_key, 'tpm', None) if api_key else None
        api_key_id = api_key.id if api_key else None

        has_any_limit = rpm_limit or tpm_limit or workspace_rpm or workspace_tpm or apikey_rpm or apikey_tpm
        if has_any_limit:
            # Estimate input tokens
            messages_list = data.get('messages', [])
            system_prompt = None
            for msg in messages_list:
                if isinstance(msg, dict) and msg.get('role') == 'system':
                    system_prompt = msg.get('content', '')
                    break
            if not system_prompt:
                system_prompt = data.get('system')  # Anthropic format
            tools = data.get('tools')
            estimated_tokens = estimate_input_tokens(messages_list, system_prompt, tools)

            apikey_preview = (api_key.key[:8] + '...') if api_key and api_key.key else ''

            result = await rate_limiter.check_and_reserve(
                model_id=db_model_rl.id,
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
                rate_limit_extra = _build_error_context(api_key, model_name)
                rate_limit_extra["rate_limit_detail"] = result.detail
                _log_error("handle_request", 429, result.detail or 'Rate limit exceeded', rate_limit_extra)
                return jsonify(adapter.format_error_response(
                    result.detail or 'Rate limit exceeded', 429
                )), 429

            rate_limit_info = (
                db_model_rl.id, group_id or 0, rpm_limit, tpm_limit,
                estimated_tokens, apikey_preview,
                workspace_id, model_name_for_ws, workspace_tpm,
                ws_provider_type, ws_provider_id_val,
                apikey_rpm, apikey_tpm, api_key_id,
            )
    except ModelNotFoundError:
        # Model not resolved for rate-limiting — skip rate limiting and let
        # the actual request flow produce the proper ModelNotFoundError.
        pass
    except Exception as e:
        logger.error(f"[rate_limiter] Pre-check failed, skipping: {e}", exc_info=True)

    # 4.6. Get monitoring config from group (cache-first)
    monitoring_config = await get_group_monitoring_config(group_id) if group_id else None
    tracer = create_tracer(monitoring_config)

    # 5. 调用中间层
    _request_start_time = time.monotonic()
    _app = current_app._get_current_object()
    try:
        if chat_request.stream:
            # ── Streaming path ────────────────────────────────────────────────
            # Eagerly extract all identity info from ORM objects BEFORE
            # stream_chat() removes the DB session.
            _user_name = user.username if user else (api_key.user.username if api_key and api_key.user else None)
            _api_key_raw = api_key.key if api_key else None
            _api_key_name = api_key.name if api_key else None
            _api_key_group_id = api_key.group_id if api_key else None
            _api_key_user_id = api_key.user_id if api_key else None
            _api_key_group_name: Optional[str] = None
            if api_key:
                try:
                    if api_key.group:
                        _api_key_group_name = api_key.group.name
                except Exception:
                    pass
            _request_id = g.request_id

            if tracer:
                tracer.start(model_name, input_data=data, session_id=chat_request.session_id)
                tracer.log_input(data)
                tracer.set_metadata({
                    "request_id": _request_id,
                    "group_id": group_id,
                    "user": _user_name,
                    "model_name": model_name,
                    "api_key_name": _api_key_name,
                })

            chunks_gen, model_meta = await _gateway_service.stream_chat(
                chat_request, group_id, tracer=tracer, provider_id=provider_id
            )

            async def _chunks_with_usage_recording():
                last_usage = None
                _accumulated_extra = {}
                _content_parts: list[str] = []
                try:
                    async for chunk in chunks_gen:
                        if chunk.usage is not None:
                            if hasattr(chunk.usage, 'extra') and chunk.usage.extra:
                                _accumulated_extra.update(chunk.usage.extra)
                            last_usage = chunk.usage
                        if chunk.delta_content:
                            _content_parts.append(chunk.delta_content)
                        yield chunk
                    if last_usage is not None and _accumulated_extra:
                        if hasattr(last_usage, 'extra'):
                            for k, v in _accumulated_extra.items():
                                if k not in last_usage.extra:
                                    last_usage.extra[k] = v
                        else:
                            last_usage.extra = _accumulated_extra
                    if tracer:
                        tracer.log_output({
                            "content": "".join(_content_parts) if _content_parts else None,
                            "usage": last_usage.to_dict() if last_usage else None,
                        })
                except Exception as e:
                    _log_error("handle_request", 500, f"Stream processing error: {e}",
                               {"model": model_name, "group_id": _api_key_group_id}, exc_info=True)
                    if tracer:
                        tracer.set_metadata({"request_id": _request_id, "model_name": model_name, "api_key_name": _api_key_name})
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
                                app=_app,
                                usage_info=last_usage,
                                user_name=_user_name,
                                user_id=_api_key_user_id,
                                api_key_raw=_api_key_raw,
                                api_key_name=_api_key_name,
                                api_key_group_id=_api_key_group_id,
                                api_key_group_name=_api_key_group_name,
                                model_name=model_name,
                                provider_id=model_meta.get('provider_id'),
                                provider_name=model_meta.get('provider_name'),
                                input_price_unit=model_meta.get('input_price_unit', 0.0),
                                output_price_unit=model_meta.get('output_price_unit', 0.0),
                                cache_creation_price_unit=model_meta.get('cache_creation_price_unit', 0.0),
                                cache_5m_creation_price_unit=model_meta.get('cache_5m_creation_price_unit', 0.0),
                                cache_1h_creation_price_unit=model_meta.get('cache_1h_creation_price_unit', 0.0),
                                cache_token_price_unit=model_meta.get('cache_token_price_unit', 0.0),
                                pricing_tiers=model_meta.get('pricing_tiers'),
                                output_pricing=model_meta.get('output_pricing'),
                                currency=model_meta.get('currency', 'USD'),
                                discount=model_meta.get('discount', 1.0),
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
                    "request_id": g.request_id,
                    "group_id": group_id,
                    "user": user.username if user else None,
                    "model_name": model_name,
                    "api_key_name": api_key.name if api_key else None,
                })

            response, resolved = await _gateway_service.chat(
                chat_request, group_id, tracer=tracer, provider_id=provider_id
            )
            _duration_ms = int((time.monotonic() - _request_start_time) * 1000)

            if tracer:
                tracer.log_output(adapter.format_response(response))
                tracer.set_metadata({
                    "duration_ms": _duration_ms,
                })
                tracer.end()

            await _reconcile_tpm(rate_limiter, rate_limit_info, response.usage.prompt_tokens if response and response.usage else 0)

            try:
                from app.usagerecord.usage_service import record_usage
                await record_usage(
                    response=response,
                    db_model=resolved.db_model,
                    db_provider=resolved.db_provider,
                    api_key=api_key,
                    user=user,
                    request_model_name=model_name,
                    duration_ms=_duration_ms,
                )
            except Exception as _ue:
                logger.warning(f"[usage] Failed to trigger usage recording: {_ue}")
            return jsonify(adapter.format_response(response))

    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        error_extra = _build_error_context(api_key, model_name,
                                           provider_id=e.provider_id,
                                           provider_name=e.provider_name)
        if e.error_data:
            error_extra["error_data"] = e.error_data
        _log_error("handle_request", e.status_code, e.message, error_extra, exc_info=True)
        return jsonify(adapter.format_error_response(e.message, e.status_code, e.error_data)), e.status_code
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("handle_request", e.status_code, e.message, _build_error_context(api_key, model_name), exc_info=True)
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id, "model_name": model_name, "api_key_name": api_key.name if api_key else None})
            tracer.end(error=e)
        _log_error("handle_request", e.status_code, e.message, _build_error_context(api_key, model_name), exc_info=True)
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code


# ============== API 端点 ==============

@gateway_bp.route('/v1/chat/completions', methods=['POST', 'HEAD', 'OPTIONS'])
async def chat_completions():
    """
    OpenAI-compatible chat completions endpoint.

    支持任意供应商（OpenAI、Claude、Gemini 等），
    中间层自动根据模型名称路由到正确的供应商。
    """
    if request.method == 'HEAD' or request.method == 'OPTIONS':
        return '', 200
    return await _handle_request(OpenAIChatAdapter())


@gateway_bp.route('/v1/messages', methods=['POST', 'HEAD', 'OPTIONS'])
async def anthropic_messages():
    """
    Anthropic-compatible messages endpoint.

    支持任意供应商（OpenAI、Claude、Gemini 等），
    中间层自动根据模型名称路由到正确的供应商。
    """
    if request.method == 'HEAD' or request.method == 'OPTIONS':
        return '', 200
    return await _handle_request(AnthropicMessagesAdapter())


# ============== 模型列表 ==============

@gateway_bp.route('/v1/models', methods=['GET'])
async def list_models():
    """List all available models (OpenAI compatible)."""
    from sqlalchemy.orm import selectinload

    user, api_key, error, status = await get_current_user_or_api_key()
    if error:
        return jsonify(error), status

    session = g.db_session

    # Get all models for this group (including shared models)
    if api_key:
        from app.models import get_group_models_with_shares
        model_provider_pairs = await get_group_models_with_shares(api_key.group_id, session=session)
    else:
        # No API key — return all active models from all active providers
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

    # Get allowed_models restriction from API key (if any)
    allowed_models = None
    if api_key:
        allowed_models = getattr(api_key, 'allowed_models', None) or None

    seen_ids = set()
    models_list = []
    for model, provider in model_provider_pairs:
        # Skip models not in allowed_models (if restriction is set)
        if allowed_models:
            if model.name not in allowed_models and (not model.alias or model.alias not in allowed_models):
                continue
        # Use alias as id if available, otherwise use name
        model_id = model.alias if model.alias else model.name
        # Skip duplicate model IDs
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

    # 创建临时实例获取模型列表
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
