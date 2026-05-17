"""
OpenAI Responses API 路由层

提供 /v1/responses 端点，支持同步和异步（background）模式。

三层架构：
  API 层 (Routes/Adapters) → 中间层 (GatewayService) → 供应商层 (Providers)

此模块从 gateway.py 拆分而来，专门处理 Responses API 相关的路由。
"""
from quart import Blueprint, request, jsonify, current_app, g
from typing import Any, Dict, Optional
import json
import logging
import time
import threading

logger = logging.getLogger("gateway")

from app import db
import app.background_response_dao as _bg_dao
from app.monitoring import create_tracer
from app.group_service import get_group_monitoring_config

# 导入中间层
from app.utils import json_loads


async def _parse_json_body():
    """Parse Quart request body as JSON, tolerating non-standard client input."""
    raw = await request.get_data()
    text = raw.decode("utf-8", errors="replace")
    try:
        return json_loads(text)
    except Exception:
        return None


from app.middleware.gateway_service import (
    GatewayService,
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)

# 导入适配器
from app.adapters.responses_adapter import OpenAIResponsesAdapter, _apply_b64_json_to_image_output, _save_image_data_uris_to_storage, _strip_internal_fields

from app.storage import get_storage_backend
from app.utils import gen_id

# 从 gateway 模块导入共享的认证和工具函数
from app.routes.gateway import (
    get_current_user_or_api_key,
    _check_allowed_models,
    _gateway_service,
    _log_error,
)
from app.routes.gateway_helpers import G_API_KEY_PROVIDER_ID

gateway_responses_bp = Blueprint('gateway_responses', __name__)


# ============== Background worker ==============

def _run_background_response(
    app,
    response_id: str,
    input_key: str,
    output_key: str,
    group_id: Optional[int],
    *,
    user_name: Optional[str] = None,
    user_id: Optional[int] = None,
    api_key_raw: Optional[str] = None,
    api_key_name: Optional[str] = None,
    api_key_group_id: Optional[int] = None,
    api_key_group_name: Optional[str] = None,
    tracer: Any = None,
    model_name: Optional[str] = None,
    request_data: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    provider_id: Optional[int] = None,
):
    """
    Worker function executed in a background thread.

    Reads the request payload via the storage backend, calls the GatewayService,
    writes the result to storage, then updates the BackgroundResponse DB record.

    All DB operations are performed via background_response_dao (NullPool engine),
    so no long-lived DB connection is held during the LLM/video generation work.

    Async-within-async handling
    ---------------------------
    The upstream provider itself may be an async Responses API service (e.g. an
    OpenAI-compatible service that accepts ``background=true``).  In that case the
    first ``POST /v1/responses`` call returns immediately with
    ``status: "queued"`` or ``"in_progress"`` instead of a finished result.

    When this happens, this function polls ``GET /v1/responses/{id}`` on the
    upstream provider until the status changes to ``"completed"`` or ``"failed"``,
    then saves the final result as normal.  The upstream status is propagated via
    ``ChatResponse.usage.extra['_upstream_status']``.

    Args:
        app:         The Flask application instance (needed for app context).
        response_id: The BackgroundResponse.response_id to update when done.
        input_key:   Storage key for the JSON request payload.
        output_key:  Storage key for the JSON response output.
        group_id:    Group ID for access control (from the API key, or None for JWT users).
        user_name:   Human-readable user name (from JWT); extracted eagerly from the
                     request thread before the session closes.
        api_key_raw: Raw API key string (for hashing/masking in usage records).
        api_key_name: Display name of the API key.
        api_key_group_id: Group ID of the API key.
        api_key_group_name: Group name of the API key.
    """
    import os

    # Quart's app_context() is async-only; in this sync background thread
    # we set Flask's _cv_app ContextVar directly so Flask-SQLAlchemy works.
    from flask.globals import _cv_app
    from flask.ctx import AppContext
    _token = _cv_app.set(AppContext(app))

    # Propagate the originating request_id into the ContextVar so downstream
    # helpers (logging filters, storage key namespacing, etc.) can read it
    # even though Quart's `g` is unavailable in this thread.
    _rid_token = None
    if request_id:
        try:
            from app import request_id_var
            _rid_token = request_id_var.set(request_id)
        except Exception:
            pass
    try:
        db_url = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        storage = get_storage_backend()

        final_error: Optional[str] = None
        formatted_output: Optional[str] = None

        try:
            # Read request payload — no DB connection held during this
            raw = storage.read(input_key)
            if raw is None:
                raise RuntimeError(f"Input not found at storage key: {input_key}")
            data = json_loads(raw)

            adapter = OpenAIResponsesAdapter()
            chat_request = adapter.parse_request(data)

            # ── LLM / video generation call ────────────────────────────────
            # chat() uses db.session for model resolution; the actual
            # provider API call may be long-running.
            if tracer:
                tracer.start(model_name or data.get('model', ''), input_data=request_data or data, session_id=chat_request.session_id)
                tracer.log_input(request_data or data)
            _bg_start_time = time.monotonic()
            try:
                response, resolved = _gateway_service.chat(chat_request, group_id, tracer=tracer, provider_id=provider_id)
                if tracer:
                    tracer.log_output(adapter.format_response(response))
            except Exception:
                if tracer:
                    tracer.set_metadata({"request_id": request_id})
                    tracer.end(error=Exception("background generation error"))
                raise

            # Eagerly extract all ORM data we need for usage recording,
            # then release the DB session so the connection returns to the
            # pool immediately — before any long-running polling begins.
            _db_model = resolved.db_model
            _db_provider = resolved.db_provider
            _provider_instance = resolved.provider_instance
            # Pre-extract primitive pricing fields from ORM objects
            _pricing_snapshot = {
                'provider_id': _db_provider.id if _db_provider else None,
                'provider_name': _db_provider.name if _db_provider else None,
                'input_price': float(getattr(_db_model, 'input_price', 0) or 0),
                'output_price': float(getattr(_db_model, 'output_price', 0) or 0),
                'cache_creation_price': float(getattr(_db_model, 'cache_creation_price', 0) or 0),
                'cache_5m_creation_price': float(getattr(_db_model, 'cache_5m_creation_price', 0) or 0),
                'cache_1h_creation_price': float(getattr(_db_model, 'cache_1h_creation_price', 0) or 0),
                'cache_hit_price': float(getattr(_db_model, 'cache_hit_price', 0) or 0),
                'pricing_tiers': getattr(_db_model, 'pricing_tiers', None),
                'output_pricing': getattr(_db_model, 'output_pricing', None),
                'currency': getattr(_db_model, 'currency', 'USD') or 'USD',
                'discount': float(getattr(_db_model, 'discount', 1) or 1),
            }
            # Release the DB session — return the connection to the pool
            try:
                db.session.remove()
            except Exception:
                pass

            # ── Check if upstream is itself async ─────────────────────────
            # Some upstream Responses API providers (e.g. OpenAI-compatible
            # services with background=true) may return status "queued" or
            # "in_progress" immediately.  In that case we must poll
            # GET /v1/responses/{id} until the upstream finishes.
            upstream_status = response.usage.extra.get('_upstream_status', 'completed')
            _PENDING_STATUSES = {'queued', 'in_progress'}

            if upstream_status in _PENDING_STATUSES:
                upstream_response_id = response.id
                upstream_model = response.model

                # Re-resolve the provider so we can call get_response() on it.
                # At this point chat_request.model has already been mutated by
                # GatewayService.chat() to the real (non-alias) model name, so
                # resolve_model() will find it by name.
                resolved = _gateway_service.resolve_model(chat_request.model, group_id, provider_id=provider_id)
                provider_instance = resolved.provider_instance
                # Update pricing snapshot with re-resolved model data
                _pricing_snapshot['provider_id'] = resolved.db_provider.id if resolved.db_provider else None
                _pricing_snapshot['provider_name'] = resolved.db_provider.name if resolved.db_provider else None
                # Release the DB session again before the long-running polling loop
                try:
                    db.session.remove()
                except Exception:
                    pass

                if not hasattr(provider_instance, 'get_response'):
                    raise RuntimeError(
                        f"Upstream returned async status {upstream_status!r} but provider "
                        f"'{type(provider_instance).__name__}' does not support polling "
                        f"(missing get_response method)."
                    )

                # Poll with exponential back-off, capped at 30 s, up to 2 h total.
                _POLL_INTERVALS = [2, 4, 8, 16, 30]  # seconds between polls
                _MAX_POLL_SECONDS = 7200              # 2 hours hard limit
                elapsed = 0
                poll_idx = 0

                while upstream_status in _PENDING_STATUSES and elapsed < _MAX_POLL_SECONDS:
                    wait = _POLL_INTERVALS[min(poll_idx, len(_POLL_INTERVALS) - 1)]
                    logger.info(
                        f"[background] Upstream response {upstream_response_id!r} is "
                        f"{upstream_status!r}; waiting {wait}s before next poll "
                        f"(elapsed={elapsed}s, our_response_id={response_id!r})"
                    )
                    time.sleep(wait)
                    elapsed += wait
                    poll_idx += 1

                    response = provider_instance.get_response(upstream_response_id, upstream_model)
                    upstream_status = response.usage.extra.get('_upstream_status', 'completed')

                if upstream_status in _PENDING_STATUSES:
                    raise RuntimeError(
                        f"Upstream response {upstream_response_id!r} did not complete "
                        f"within {_MAX_POLL_SECONDS}s (last status: {upstream_status!r})"
                    )

                if upstream_status == 'failed':
                    # Surface the real upstream error if available
                    upstream_error = response.usage.extra.get('_upstream_error')
                    if upstream_error:
                        raise RuntimeError(json.dumps(upstream_error, ensure_ascii=False))
                    raise RuntimeError(
                        f"Upstream response {upstream_response_id!r} failed "
                        f"(upstream status: {upstream_status!r})"
                    )

            formatted = adapter.format_response(response)
            # Save any data URIs from image generation to storage,
            # replacing them with storage URLs in the stored output.
            _save_image_data_uris_to_storage(formatted.get('output', []), storage, formatted.get('id', ''))
            _strip_internal_fields(formatted.get('output', []))
            formatted_output = json.dumps(formatted, ensure_ascii=False)

            # Record usage for background response.
            # All pricing info comes from _pricing_snapshot (plain primitives
            # eagerly extracted before db.session.remove()).
            _bg_duration_ms = int((time.monotonic() - _bg_start_time) * 1000)
            try:
                from app.usagerecord.usage_service import record_stream_usage
                record_stream_usage(
                    app=app,
                    usage_info=response.usage,
                    user_name=user_name,
                    user_id=user_id,
                    api_key_raw=api_key_raw,
                    api_key_name=api_key_name,
                    api_key_group_id=api_key_group_id,
                    api_key_group_name=api_key_group_name,
                    model_name=data.get('model', ''),
                    provider_id=_pricing_snapshot['provider_id'],
                    provider_name=_pricing_snapshot['provider_name'],
                    input_price_unit=_pricing_snapshot['input_price'],
                    output_price_unit=_pricing_snapshot['output_price'],
                    cache_creation_price_unit=_pricing_snapshot['cache_creation_price'],
                    cache_5m_creation_price_unit=_pricing_snapshot['cache_5m_creation_price'],
                    cache_1h_creation_price_unit=_pricing_snapshot['cache_1h_creation_price'],
                    cache_token_price_unit=_pricing_snapshot['cache_hit_price'],
                    pricing_tiers=_pricing_snapshot['pricing_tiers'],
                    output_pricing=_pricing_snapshot['output_pricing'],
                    currency=_pricing_snapshot['currency'],
                    discount=_pricing_snapshot['discount'],
                    duration_ms=_bg_duration_ms,
                )
            except Exception as _ue:
                logger.warning(f"[usage] Failed to record usage for background response {response_id!r}: {_ue}")

            if tracer:
                tracer.set_metadata({
                    "request_id": request_id,
                    "group_id": group_id,
                    "user": user_name,
                    "provider": _pricing_snapshot.get('provider_name'),
                    "duration_ms": _bg_duration_ms,
                })
                tracer.end()

        except Exception as exc:
            if tracer:
                try:
                    tracer.set_metadata({"request_id": request_id})
                    tracer.end(error=exc)
                except Exception:
                    pass
            logger.exception(f"[background] Error processing {response_id!r}: {exc}")
            final_error = str(exc)

        # Write output to storage (outside any DB transaction)
        if formatted_output is not None:
            try:
                storage.write(output_key, formatted_output)
            except Exception as write_exc:
                logger.exception(f"[background] Failed to write output for {response_id!r}: {write_exc}")
                final_error = str(write_exc)
                formatted_output = None

        # Update DB — each call opens a brand-new NullPool connection
        if final_error:
            _bg_dao.mark_failed(db_url, response_id, final_error)
        else:
            _bg_dao.mark_completed(db_url, response_id)
    finally:
        _cv_app.reset(_token)
        if _rid_token is not None:
            try:
                from app import request_id_var
                request_id_var.reset(_rid_token)
            except Exception:
                pass


# ============== Responses API 端点 ==============

@gateway_responses_bp.route('/v1/responses', methods=['POST', 'HEAD', 'OPTIONS'])
async def openai_responses():
    """
    OpenAI Responses API endpoint.

    支持任意供应商（OpenAI、Claude、Gemini 等），
    中间层自动根据模型名称路由到正确的供应商。

    When the request body contains ``"background": true``, the endpoint:
    1. Immediately returns a ``202 Accepted`` JSON response containing the
       ``response_id`` and ``status: "in_progress"``.
    2. Spawns a background thread that calls the provider and stores the
       result in the ``ml_background_responses`` table.
    3. The client can later retrieve the result via
       ``GET /v1/responses/{response_id}``.
    """
    if request.method == 'HEAD' or request.method == 'OPTIONS':
        return '', 200

    adapter = OpenAIResponsesAdapter()

    # 1. 先读取请求体，检查是否为 background 请求（无需先认证）
    data = await _parse_json_body()
    if not data:
        _log_error("responses", 400, "Invalid or empty JSON request body")
        return jsonify(adapter.format_error_response('Invalid or empty JSON request body', 400)), 400

    model_name = data.get('model')
    if not model_name:
        _log_error("responses", 400, "Model is required")
        return jsonify(adapter.format_error_response('Model is required', 400)), 400

    is_background = bool(data.get('background', False))

    # Check if this is a 3D generation request (3d_generation tool present).
    # 3D generation is a long-running async task and ONLY supports background=true.
    _tools = data.get('tools', [])
    _has_3d_tool = any(
        isinstance(t, dict) and t.get('type') == '3d_generation'
        for t in _tools
    )
    if _has_3d_tool and not is_background:
        _log_error("responses", 400, "3D generation requires background=true")
        return jsonify(adapter.format_error_response(
            '3D generation only supports asynchronous mode. '
            'Please set "background": true in your request and poll '
            'GET /v1/responses/:response_id for the result.',
            400
        )), 400

    # 2. 认证（只做一次）
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        _log_error("responses", status, error.get('detail', 'Not authenticated'))
        return jsonify(adapter.format_error_response(error.get('detail', 'Not authenticated'), status)), status

    # 2.5. 检查 API Key 的 allowed_models 限制
    acl_error = _check_allowed_models(api_key, model_name)
    if acl_error:
        _log_error("responses", 403, acl_error['detail'])
        return jsonify(adapter.format_error_response(acl_error['detail'], 403)), 403

    # 3. Background 异步路径
    if is_background:
        group_id = api_key.group_id if api_key else None
        apikey_value = api_key.key if api_key else None
        provider_id_override = g.get(G_API_KEY_PROVIDER_ID, None) if api_key else None

        # Create tracer for background request
        monitoring_config = get_group_monitoring_config(group_id) if group_id else None
        tracer = create_tracer(monitoring_config)

        # Eagerly extract identity primitives while the DB session is alive.
        # These will be passed to the background thread for usage recording.
        _bg_user_name = user.username if user else (api_key.user.username if api_key and api_key.user else None)
        _bg_api_key_raw = api_key.key if api_key else None
        _bg_api_key_name = api_key.name if api_key else None
        _bg_api_key_group_id = api_key.group_id if api_key else None
        _bg_api_key_user_id = api_key.user_id if api_key else None
        _bg_api_key_group_name: Optional[str] = None
        if api_key:
            try:
                if api_key.group:
                    _bg_api_key_group_name = api_key.group.name
            except Exception:
                pass
        _bg_request_id = g.request_id

        # Generate a stable response ID: "resp_" + 48 hex chars
        response_id = gen_id("resp")

        # Build input/output storage keys via the configured backend
        storage = get_storage_backend()
        input_key = storage.make_key(response_id, "input")
        output_key = storage.make_key(response_id, "output")

        # Write the request payload via the storage backend
        storage.write(input_key, json.dumps(data, ensure_ascii=False))

        # Persist the initial "in_progress" record via DAO (NullPool — short-lived connection)
        db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
        _bg_dao.create_record(
            db_url=db_url,
            response_id=response_id,
            apikey=apikey_value,
            model=model_name,
            input_key=input_key,
            output_key=output_key,
        )

        # Launch the background worker thread
        app = current_app._get_current_object()
        thread = threading.Thread(
            target=_run_background_response,
            args=(app, response_id, input_key, output_key, group_id),
            kwargs=dict(
                user_name=_bg_user_name,
                user_id=_bg_api_key_user_id,
                api_key_raw=_bg_api_key_raw,
                api_key_name=_bg_api_key_name,
                api_key_group_id=_bg_api_key_group_id,
                api_key_group_name=_bg_api_key_group_name,
                tracer=tracer,
                model_name=model_name,
                request_data=data,
                request_id=_bg_request_id,
                provider_id=provider_id_override,
            ),
            daemon=True,
        )
        thread.start()

        # Return 202 immediately with the response ID and current status
        return jsonify({
            "id": response_id,
            "object": "response",
            "status": "in_progress",
            "model": model_name,
            "background": True,
        }), 202

    # 4. 同步路径：直接处理（不再重新认证，复用已读取的数据）
    group_id = api_key.group_id if api_key else None
    provider_id_override = g.get(G_API_KEY_PROVIDER_ID, None) if api_key else None

    try:
        chat_request = adapter.parse_request(data)
    except Exception as e:
        _log_error("responses", 400, f"Invalid request format: {e}")
        return jsonify(adapter.format_error_response(f'Invalid request format: {str(e)}', 400)), 400

    logger.debug(f"Original request logged to: {json.dumps(data, ensure_ascii=False)}")

    monitoring_config = get_group_monitoring_config(group_id) if group_id else None
    tracer = create_tracer(monitoring_config)

    _resp_start_time = time.monotonic()
    try:
        if chat_request.stream:
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

            chunks, model_meta = _gateway_service.stream_chat(chat_request, group_id, tracer=tracer, provider_id=provider_id_override)
            _app = current_app._get_current_object()

            def _resp_chunks_with_usage():
                last_usage = None
                _accumulated_extra = {}
                _content_parts: list[str] = []
                try:
                    for chunk in chunks:
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
                except Exception:
                    if tracer:
                        tracer.set_metadata({"request_id": _request_id})
                        tracer.end(error=Exception("stream error"))
                    raise
                finally:
                    if last_usage is not None:
                        try:
                            from app.usagerecord.usage_service import record_stream_usage
                            _resp_duration_ms = int((time.monotonic() - _resp_start_time) * 1000)
                            record_stream_usage(
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
                                duration_ms=_resp_duration_ms,
                            )
                        except Exception as _ue:
                            logger.warning(f"[usage] Failed to trigger stream usage recording: {_ue}")
                    if tracer:
                        tracer.set_metadata({
                            "request_id": _request_id,
                            "group_id": group_id,
                            "user": _user_name,
                            "provider": model_meta.get('provider_name'),
                        })
                        tracer.end()

            return adapter.create_stream_response(_resp_chunks_with_usage(), model_name)
        else:
            if tracer:
                tracer.start(model_name, input_data=data, session_id=chat_request.session_id)
                tracer.log_input(data)

            response, resolved = _gateway_service.chat(chat_request, group_id, tracer=tracer, provider_id=provider_id_override)
            _resp_duration_ms = int((time.monotonic() - _resp_start_time) * 1000)

            if tracer:
                tracer.log_output(adapter.format_response(response))
                tracer.set_metadata({
                    "request_id": g.request_id,
                    "group_id": group_id,
                    "user": user.username if user else None,
                    "provider": resolved.db_provider.name,
                    "duration_ms": _resp_duration_ms,
                })
                tracer.end()

            try:
                from app.usagerecord.usage_service import record_usage
                record_usage(
                    app=current_app._get_current_object(),
                    response=response,
                    db_model=resolved.db_model,
                    db_provider=resolved.db_provider,
                    api_key=api_key,
                    user=user,
                    request_model_name=model_name,
                    duration_ms=_resp_duration_ms,
                )
            except Exception as _ue:
                logger.warning(f"[usage] Failed to trigger usage recording for responses: {_ue}")
            formatted = adapter.format_response(response)
            _save_image_data_uris_to_storage(formatted.get('output', []), get_storage_backend(), formatted.get('id', ''))
            if formatted.get('response_format') == 'b64_json':
                _apply_b64_json_to_image_output(formatted.get('output', []), storage=get_storage_backend())
            _strip_internal_fields(formatted.get('output', []))
            return jsonify(formatted)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id})
            tracer.end(error=e)
        _log_error("responses", e.status_code, e.message, {"model": model_name, "error_data": e.error_data})
        return jsonify(adapter.format_error_response(e.message, e.status_code, e.error_data)), e.status_code
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id})
            tracer.end(error=e)
        _log_error("responses", e.status_code, e.message, {"model": model_name})
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": g.request_id})
            tracer.end(error=e)
        _log_error("responses", e.status_code, e.message, {"model": model_name})
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code


@gateway_responses_bp.route('/v1/responses/<response_id>', methods=['GET'])
async def get_response(response_id: str):
    """
    Retrieve a background response by ID.

    Used to poll the status and retrieve the result of a previously submitted
    background request (``POST /v1/responses`` with ``background=true``).

    Returns:
        - 200 with the full formatted response when status is "completed".
        - 200 with ``{"id": ..., "status": "in_progress", ...}`` while still running.
        - 200 with ``{"id": ..., "status": "failed", "error": "..."}`` on failure.
        - 404 if the response_id is not found.
        - 403 if the caller is not authorised to access this response.
    """
    user, api_key, error, status = get_current_user_or_api_key()
    if error:
        _log_error("get_response", status, error.get('detail', 'Not authenticated'))
        return jsonify({'detail': error.get('detail', 'Not authenticated')}), status

    # Look up by the string response_id field, not the BigInteger pk
    db_url = db.engine.url.render_as_string(hide_password=False)
    bg_record = _bg_dao.get_record(db_url, response_id)
    if bg_record is None:
        _log_error("get_response", 404, f"Response {response_id!r} not found")
        return jsonify({'detail': f'Response {response_id!r} not found'}), 404

    # Authorisation: API-key callers may only retrieve their own responses.
    # JWT-authenticated users (admin) may retrieve any response.
    if api_key and bg_record.get("apikey") and bg_record["apikey"] != api_key.key:
        _log_error("get_response", 403, f"Unauthorised access to response {response_id!r}")
        return jsonify({'detail': 'Not authorised to access this response'}), 403

    record_status = bg_record.get("status", "")

    if record_status == "completed":
        # Read the output via the configured storage backend
        storage = get_storage_backend()
        raw = storage.read(bg_record["output_key"]) if bg_record.get("output_key") else None
        if raw:
            try:
                result = json_loads(raw)
            except (json.JSONDecodeError, TypeError):
                result = {"error": {"code": "server_error", "message": "Failed to parse stored response"}}
        else:
            result = {"error": {"code": "server_error", "message": "Output not found in storage"}}
        # If the user originally requested b64_json for image generation,
        # convert stored image URLs to base64 data URIs at poll time.
        if isinstance(result, dict) and result.get('response_format') == 'b64_json':
            _apply_b64_json_to_image_output(result.get('output', []), storage=storage)
        _strip_internal_fields(result.get('output', []) if isinstance(result, dict) else [])
        return jsonify(result), 200

    if record_status == "failed":
        created_at = bg_record.get("created_at")
        error_raw = bg_record.get("error")

        # Valid error code values for the Responses API.
        _VALID_ERROR_CODES = frozenset({
            "server_error", "rate_limit_exceeded", "invalid_prompt",
            "vector_store_timeout", "invalid_image", "invalid_image_format",
            "invalid_base64_image", "invalid_image_url", "image_too_large",
            "image_too_small", "image_parse_error",
            "image_content_policy_violation", "invalid_image_mode",
            "image_file_too_large", "unsupported_image_media_type",
            "empty_image_file", "failed_to_download_image", "image_file_not_found",
        })

        def _normalise_error(raw) -> dict:
            """Parse the stored error and normalise its code to a valid enum value."""
            if isinstance(raw, dict):
                obj = raw
            elif isinstance(raw, str):
                try:
                    parsed = json_loads(raw)
                    obj = parsed if isinstance(parsed, dict) else {"code": "server_error", "message": raw}
                except (json.JSONDecodeError, TypeError):
                    obj = {"code": "server_error", "message": raw}
            else:
                obj = {"code": "server_error", "message": str(raw) if raw else ""}

            # Normalise code: if not a recognised enum value, fall back to server_error
            if obj.get("code") not in _VALID_ERROR_CODES:
                obj = dict(obj)  # make a mutable copy
                obj["code"] = "server_error"

            return obj

        error_obj = _normalise_error(error_raw)
        return jsonify({
            "id": bg_record["response_id"],
            "object": "response",
            "status": "failed",
            "model": bg_record.get("model", ""),
            "error": error_obj,
            "created_at": int(created_at.timestamp()) if created_at else None,
        }), 200

    # Still in_progress (or queued)
    created_at = bg_record.get("created_at")
    return jsonify({
        "id": bg_record["response_id"],
        "object": "response",
        "status": record_status,
        "model": bg_record.get("model", ""),
        "background": True,
        "created_at": int(created_at.timestamp()) if created_at else None,
    }), 200
