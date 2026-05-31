"""
OpenAI Responses API 路由层

提供 /v1/responses 端点，支持同步和异步（background）模式。

三层架构：
  API 层 (Routes/Adapters) → 中间层 (GatewayService) → 供应商层 (Providers)

请求生命周期 (no DB connection held across LLM call):
  Phase 1: auth + acl (short session)
  Phase 2: resolve model (short session, then closed)
  Phase 3: LLM call (NO session)
  Phase 4: usage record (fire-and-forget)
"""
from quart import Blueprint, request, jsonify, current_app, g
from typing import Any, Dict, Optional
import asyncio
import json
import logging
import time

logger = logging.getLogger("gateway")

from app import get_db_session
import app.background_response_dao as _bg_dao
from app.monitoring import create_tracer
from app.group_service import get_group_monitoring_config

from app.utils import json_loads


async def _parse_json_body():
    """Parse Quart request body as JSON, tolerating non-standard client input.

    Delegates to the shared helper which off-loads decode + parse to a worker
    thread so multi-MB image payloads don't stall the event loop.
    """
    from app.routes.gateway_helpers import _parse_json_body as _shared
    return await _shared()


from app.middleware.gateway_service import (
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)

from app.adapters.responses_adapter import (
    OpenAIResponsesAdapter,
    _apply_b64_json_to_image_output,
    _save_image_data_uris_to_storage,
    _strip_internal_fields,
)

from app.storage import get_storage_backend
from app.utils import gen_id

from app.routes.gateway import (
    get_current_user_or_api_key,
    _check_allowed_models,
    _gateway_service,
    _log_error,
    _build_error_context,
)

gateway_responses_bp = Blueprint('gateway_responses', __name__)


# ============== Background worker ==============

# Hold strong references to fire-and-forget background tasks. Without this,
# asyncio.create_task returns a weakly-referenced task that the GC can collect
# mid-flight, silently killing long-running background work.
_background_tasks: set = set()


def _track_background_task(task: asyncio.Task) -> None:
    """Keep ``task`` alive until it finishes, then drop the reference."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _run_background_response(
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
    Background coroutine scheduled on the main event loop.

    Runs as ``asyncio.create_task(_run_background_response(...))`` from the
    request handler. Shares the loop (and therefore the shared async
    SQLAlchemy engine) with all request handlers, so DB calls work natively.
    Sync provider SDKs are isolated with ``asyncio.to_thread``.
    """
    async with app.app_context():
        # Propagate request_id ContextVar
        _rid_token = None
        if request_id:
            try:
                from app import request_id_var
                _rid_token = request_id_var.set(request_id)
            except Exception:
                pass

        storage = get_storage_backend()

        final_error: Optional[str] = None
        formatted_output: Optional[str] = None
        _bg_start_time = time.monotonic()

        try:
            # Read request payload
            raw = await asyncio.to_thread(storage.read, input_key)
            if raw is None:
                raise RuntimeError(f"Input not found at storage key: {input_key}")
            data = json_loads(raw)

            model = data.get('model', '')
            logger.info(
                f"[background] Start processing response_id={response_id!r} "
                f"request_id={request_id} model={model}"
            )

            adapter = OpenAIResponsesAdapter()
            chat_request = adapter.parse_request(data)

            def _on_task_created(task_id: str) -> None:
                try:
                    asyncio.create_task(_bg_dao.update_task_metadata_async(
                        response_id=response_id,
                        task_id=task_id,
                    ))
                except Exception:
                    pass

            def _on_model_resolved(resolved) -> None:
                """Persist provider_id immediately after model resolution."""
                try:
                    asyncio.create_task(_bg_dao.update_task_metadata_async(
                        response_id=response_id,
                        provider_id=resolved.provider_id,
                    ))
                except Exception:
                    pass

            chat_request.metadata['_on_task_created'] = _on_task_created
            chat_request.metadata['_on_model_resolved'] = _on_model_resolved

            # ─── Phase 2: resolve model (short DB session) ───
            async with get_db_session() as session:
                resolved = await _gateway_service.resolve_model(
                    session, chat_request.model, group_id, provider_id=provider_id
                )
            # ← session closed; DB connection returned to pool

            # Persist provider_id immediately so resync can find this row
            try:
                await _bg_dao.update_task_metadata_async(
                    response_id=response_id,
                    provider_id=resolved.provider_id,
                    session_id=chat_request.session_id,
                    request_id=request_id,
                )
            except Exception as _meta_exc:
                logger.warning(f"[background] Failed to update provider_id for {response_id!r} (request_id={request_id}): {_meta_exc}")

            # ─── Phase 3: LLM call (NO DB session) ───
            if tracer:
                tracer.start(model_name or data.get('model', ''), input_data=request_data or data, session_id=chat_request.session_id)
                tracer.log_input(request_data or data)
                tracer.set_metadata({
                    "request_id": request_id,
                    "group_id": group_id,
                    "user": user_name,
                    "model_name": model_name,
                    "api_key_name": api_key_name,
                })

            try:
                response = await _gateway_service.chat(resolved, chat_request, tracer=tracer)
                if tracer:
                    tracer.log_output(adapter.format_response(response))
            except Exception:
                if tracer:
                    tracer.set_metadata({"request_id": request_id, "model_name": model_name, "api_key_name": api_key_name})
                    tracer.end(error=Exception("background generation error"))
                raise

            # Persist task metadata after first chat() returns
            try:
                _provider_task_id = None
                if response.usage and response.usage.extra:
                    _provider_task_id = response.usage.extra.get('_task_id')
                await _bg_dao.update_task_metadata_async(
                    response_id=response_id,
                    task_id=_provider_task_id,
                    provider_id=resolved.provider_id,
                    session_id=chat_request.session_id,
                    request_id=request_id,
                )
            except Exception as _meta_exc:
                logger.warning(f"[background] Failed to update task metadata for {response_id!r} (request_id={request_id}): {_meta_exc}")

            # ─── Async upstream polling (NO DB) ───
            upstream_status = response.usage.extra.get('_upstream_status', 'completed')
            _PENDING_STATUSES = {'queued', 'in_progress'}

            if upstream_status in _PENDING_STATUSES:
                upstream_response_id = response.id
                upstream_model = response.model

                try:
                    await _bg_dao.update_task_metadata_async(
                        response_id=response_id,
                        task_id=upstream_response_id,
                    )
                except Exception as _meta_exc:
                    logger.warning(f"[background] Failed to store upstream task_id for {response_id!r} (request_id={request_id}): {_meta_exc}")

                # We already have provider_instance from `resolved`. Use it directly.
                provider_instance = resolved.provider_instance

                if not hasattr(provider_instance, 'get_response'):
                    raise RuntimeError(
                        f"Upstream returned async status {upstream_status!r} but provider "
                        f"'{type(provider_instance).__name__}' does not support polling "
                        f"(missing get_response method)."
                    )

                _POLL_INTERVALS = [2, 4, 8, 16, 30]
                _MAX_POLL_SECONDS = 7200
                elapsed = 0
                poll_idx = 0

                while upstream_status in _PENDING_STATUSES and elapsed < _MAX_POLL_SECONDS:
                    wait = _POLL_INTERVALS[min(poll_idx, len(_POLL_INTERVALS) - 1)]
                    logger.info(
                        f"[background] Upstream response {upstream_response_id!r} is "
                        f"{upstream_status!r}; waiting {wait}s before next poll "
                        f"(elapsed={elapsed}s, response_id={response_id!r}, request_id={request_id})"
                    )
                    await asyncio.sleep(wait)
                    elapsed += wait
                    poll_idx += 1

                    # provider_instance.get_response is sync (uses requests); offload.
                    response = await asyncio.to_thread(
                        provider_instance.get_response, upstream_response_id, upstream_model
                    )
                    upstream_status = response.usage.extra.get('_upstream_status', 'completed')

                if upstream_status in _PENDING_STATUSES:
                    raise RuntimeError(
                        f"Upstream response {upstream_response_id!r} did not complete "
                        f"within {_MAX_POLL_SECONDS}s (last status: {upstream_status!r})"
                    )

                if upstream_status == 'failed':
                    upstream_error = response.usage.extra.get('_upstream_error')
                    if upstream_error:
                        raise RuntimeError(json.dumps(upstream_error, ensure_ascii=False))
                    raise RuntimeError(
                        f"Upstream response {upstream_response_id!r} failed "
                        f"(upstream status: {upstream_status!r})"
                    )

            formatted = adapter.format_response(
                response,
                parallel_tool_calls=chat_request.parallel_tool_calls,
                metadata=chat_request.metadata.get('_user_metadata'),
            )
            await _save_image_data_uris_to_storage(formatted.get('output', []), storage, formatted.get('id', ''))
            _strip_internal_fields(formatted.get('output', []))
            # Attach price info to formatted response usage
            if response and response.usage:
                from app.usagerecord.usage_service import calculate_price
                formatted['usage']['price'] = calculate_price(
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
                ).to_dict()
            formatted_output = json.dumps(formatted, ensure_ascii=False)

            # ─── Phase 4: usage recording (fire-and-forget) ───
            _bg_duration_ms = int((time.monotonic() - _bg_start_time) * 1000)
            try:
                from app.usagerecord.usage_service import record_stream_usage
                await record_stream_usage(
                    usage_info=response.usage,
                    user_name=user_name,
                    user_id=user_id,
                    api_key_raw=api_key_raw,
                    api_key_name=api_key_name,
                    api_key_group_id=api_key_group_id,
                    api_key_group_name=api_key_group_name,
                    model_name=data.get('model', ''),
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
                    duration_ms=_bg_duration_ms,
                )
            except Exception as _ue:
                logger.warning(f"[usage] Failed to record usage for background response {response_id!r} (request_id={request_id}): {_ue}")

            if tracer:
                tracer.set_metadata({
                    "duration_ms": _bg_duration_ms,
                    "response_id": response.id if response else None,
                })
                tracer.end()

            _bg_duration_ms = int((time.monotonic() - _bg_start_time) * 1000)
            logger.info(
                f"[background] Completed response_id={response_id!r} "
                f"request_id={request_id} duration_ms={_bg_duration_ms}"
            )

        except Exception as exc:
            if tracer:
                try:
                    tracer.set_metadata({"request_id": request_id, "model_name": model_name, "api_key_name": api_key_name})
                    tracer.end(error=exc)
                except Exception:
                    pass
            _bg_duration_ms = int((time.monotonic() - _bg_start_time) * 1000)
            logger.exception(
                f"[background] Failed response_id={response_id!r} "
                f"request_id={request_id} duration_ms={_bg_duration_ms}: {exc}"
            )
            final_error = str(exc)

        # Write output to storage (outside any DB transaction)
        if formatted_output is not None:
            try:
                await asyncio.to_thread(storage.write, output_key, formatted_output)
            except Exception as write_exc:
                logger.exception(f"[background] Failed to write output for {response_id!r} (request_id={request_id}): {write_exc}")
                final_error = str(write_exc)
                formatted_output = None

        # Update DB via shared async engine (reuses pool, no per-call TCP)
        if final_error:
            await _bg_dao.mark_failed_async(response_id, final_error)
        else:
            await _bg_dao.mark_completed_async(response_id)

        if _rid_token is not None:
            try:
                from app import request_id_var
                request_id_var.reset(_rid_token)
            except Exception:
                pass


# ============== Responses API 端点 ==============

@gateway_responses_bp.route('/v1/responses', methods=['POST', 'HEAD', 'OPTIONS'])
async def openai_responses():
    """OpenAI Responses API endpoint (sync + background)."""
    if request.method == 'HEAD' or request.method == 'OPTIONS':
        return '', 200

    adapter = OpenAIResponsesAdapter()

    # Parse request body first
    data = await _parse_json_body()
    if not data:
        _log_error("responses", 400, "Invalid or empty JSON request body")
        return jsonify(adapter.format_error_response('Invalid or empty JSON request body', 400)), 400

    model_name = data.get('model')
    if not model_name:
        _log_error("responses", 400, "Model is required")
        return jsonify(adapter.format_error_response('Model is required', 400)), 400

    is_background = bool(data.get('background', False))

    # 3D generation must use background mode
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

    # ─── Phase 1: auth ───
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("responses", status, error.get('detail', 'Not authenticated'))
        return jsonify(adapter.format_error_response(error.get('detail', 'Not authenticated'), status)), status

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("responses", 403, acl_error['detail'], _build_error_context(auth_ctx, model_name))
        return jsonify(adapter.format_error_response(acl_error['detail'], 403)), 403

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id_override = auth_ctx.provider_id_override if auth_ctx else None

    # ─── Background path ───
    if is_background:
        monitoring_config = None
        if group_id:
            try:
                async with get_db_session() as _mon_session:
                    monitoring_config = await get_group_monitoring_config(group_id, session=_mon_session)
            except Exception as _e:
                logger.debug(f"[monitoring] fetch config failed: {_e}")
        tracer = create_tracer(monitoring_config)

        _bg_request_id = g.request_id

        response_id = gen_id("resp")
        storage = get_storage_backend()
        input_key = storage.make_key(response_id, "input")
        output_key = storage.make_key(response_id, "output")

        await asyncio.to_thread(storage.write, input_key, json.dumps(data, ensure_ascii=False))

        await _bg_dao.create_record_async(
            response_id=response_id,
            apikey=auth_ctx.api_key_raw if auth_ctx else None,
            model=model_name,
            input_key=input_key,
            output_key=output_key,
            request_id=_bg_request_id,
            provider_id=provider_id_override,
        )

        app = current_app._get_current_object()
        # Schedule the background coroutine on the main event loop so it
        # shares the loop (and thus the async SQLAlchemy engine) with the
        # rest of the application. Keep a reference to prevent GC.
        _bg_task = asyncio.create_task(
            _run_background_response(
                app, response_id, input_key, output_key, group_id,
                user_name=auth_ctx.user_name if auth_ctx else None,
                user_id=auth_ctx.user_id if auth_ctx else None,
                api_key_raw=auth_ctx.api_key_raw if auth_ctx else None,
                api_key_name=auth_ctx.api_key_name if auth_ctx else None,
                api_key_group_id=auth_ctx.api_key_group_id if auth_ctx else None,
                api_key_group_name=auth_ctx.api_key_group_name if auth_ctx else None,
                tracer=tracer,
                model_name=model_name,
                request_data=data,
                request_id=_bg_request_id,
                provider_id=provider_id_override,
            ),
            name=f"bg-response-{response_id}",
        )
        _track_background_task(_bg_task)

        user_metadata = data.get('metadata')
        if not isinstance(user_metadata, dict):
            user_metadata = None
        return jsonify({
            "id": response_id,
            "object": "response",
            "created_at": int(time.time()),
            "model": model_name,
            "status": "in_progress",
            "parallel_tool_calls": bool(data.get('parallel_tool_calls', False)),
            "metadata": user_metadata,
            "background": True,
        }), 200

    # ─── Sync path ───
    try:
        chat_request = adapter.parse_request(data)
    except Exception as e:
        _log_error("responses", 400, f"Invalid request format: {e}", _build_error_context(auth_ctx, model_name))
        return jsonify(adapter.format_error_response(f'Invalid request format: {str(e)}', 400)), 400

    logger.debug(f"Original request logged to: {json.dumps(data, ensure_ascii=False)}")

    # ─── Phase 2: resolve model (short session) ───
    monitoring_config = None
    try:
        async with get_db_session() as session:
            try:
                resolved = await _gateway_service.resolve_model(
                    session, model_name, group_id, provider_id=provider_id_override
                )
            except ModelNotFoundError as e:
                _log_error("responses", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
                return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code
            except GatewayServiceError as e:
                _log_error("responses", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
                return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code

            if group_id:
                try:
                    monitoring_config = await get_group_monitoring_config(group_id, session=session)
                except Exception:
                    pass
        # ← session closes
    except Exception as e:
        logger.error(f"[responses] Phase-2 (resolve) error: {e}", exc_info=True)
        return jsonify(adapter.format_error_response(f'Internal error: {e}', 500)), 500

    tracer = create_tracer(monitoring_config)
    _resp_start_time = time.monotonic()
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

            async def _resp_chunks_with_usage():
                last_usage = None
                _accumulated_extra = {}
                _content_parts: list[str] = []
                _last_chunk_meta = {}
                try:
                    async for chunk in chunks_gen:
                        if chunk.usage is not None:
                            if hasattr(chunk.usage, 'extra') and chunk.usage.extra:
                                _accumulated_extra.update(chunk.usage.extra)
                            last_usage = chunk.usage
                        if chunk.delta_content:
                            _content_parts.append(chunk.delta_content)
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
                except Exception:
                    if tracer:
                        tracer.set_metadata({"request_id": _request_id, "model_name": model_name,
                                             "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
                        tracer.end(error=Exception("stream error"))
                    raise
                finally:
                    if last_usage is not None:
                        try:
                            from app.usagerecord.usage_service import record_stream_usage
                            _resp_duration_ms = int((time.monotonic() - _resp_start_time) * 1000)
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
                                duration_ms=_resp_duration_ms,
                            )
                        except Exception as _ue:
                            logger.warning(f"[usage] Failed to trigger stream usage recording: {_ue}")
                    if tracer:
                        tracer.end()

            return adapter.create_stream_response(_resp_chunks_with_usage(), model_name)
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
            _resp_duration_ms = int((time.monotonic() - _resp_start_time) * 1000)

            if tracer:
                tracer.log_output(adapter.format_response(response))
                tracer.set_metadata({
                    "duration_ms": _resp_duration_ms,
                    "response_id": response.id if response else None,
                })
                tracer.end()

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
                    duration_ms=_resp_duration_ms,
                )
            except Exception as _ue:
                logger.warning(f"[usage] Failed to trigger usage recording for responses: {_ue}")
            formatted = adapter.format_response(
                response,
                parallel_tool_calls=chat_request.parallel_tool_calls,
                metadata=chat_request.metadata.get('_user_metadata'),
            )
            await _save_image_data_uris_to_storage(formatted.get('output', []), get_storage_backend(), formatted.get('id', ''))
            if formatted.get('response_format') == 'b64_json':
                await _apply_b64_json_to_image_output(formatted.get('output', []), storage=get_storage_backend())
            _strip_internal_fields(formatted.get('output', []))
            return jsonify(formatted)
    except ProviderError as e:
        if tracer:
            tracer.set_metadata({"request_id": _request_id, "model_name": model_name,
                                 "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("responses", e.status_code, e.message,
                 _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name) | {"error_data": e.error_data})
        return jsonify(adapter.format_error_response(e.message, e.status_code, e.error_data)), e.status_code
    except ModelNotFoundError as e:
        if tracer:
            tracer.set_metadata({"request_id": _request_id, "model_name": model_name,
                                 "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("responses", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code
    except GatewayServiceError as e:
        if tracer:
            tracer.set_metadata({"request_id": _request_id, "model_name": model_name,
                                 "api_key_name": auth_ctx.api_key_name if auth_ctx else None})
            tracer.end(error=e)
        _log_error("responses", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return jsonify(adapter.format_error_response(e.message, e.status_code)), e.status_code


@gateway_responses_bp.route('/v1/responses/<response_id>', methods=['GET'])
async def get_response(response_id: str):
    """
    Retrieve a background response by ID.
    """
    adapter = OpenAIResponsesAdapter()

    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("get_response", status, error.get('detail', 'Not authenticated'))
        return jsonify(adapter.format_error_response(error.get('detail', 'Not authenticated'), status)), status

    bg_record = await _bg_dao.get_record_async(response_id)
    if bg_record is None:
        _log_error("get_response", 404, f"Response {response_id!r} not found", _build_error_context(auth_ctx))
        return jsonify(adapter.format_error_response(f'Response {response_id!r} not found', 404)), 404

    # API-key callers may only retrieve their own responses. JWT users (admin) may retrieve any.
    caller_api_key = auth_ctx.api_key_raw if auth_ctx else None
    if caller_api_key and bg_record.get("apikey") and bg_record["apikey"] != caller_api_key:
        _log_error("get_response", 403, f"Unauthorised access to response {response_id!r}", _build_error_context(auth_ctx))
        return jsonify(adapter.format_error_response('Not authorised to access this response', 403)), 403

    record_status = bg_record.get("status", "")

    async def _extract_response_fields() -> tuple:
        try:
            storage = get_storage_backend()
            raw = await asyncio.to_thread(storage.read, bg_record.get("input_key")) if bg_record.get("input_key") else None
            if raw:
                data = json_loads(raw)
                ptc = bool(data.get('parallel_tool_calls', False))
                um = data.get('metadata')
                return ptc, um if isinstance(um, dict) else None
        except Exception:
            pass
        return False, None

    if record_status == "completed":
        storage = get_storage_backend()
        raw = await asyncio.to_thread(storage.read, bg_record["output_key"]) if bg_record.get("output_key") else None
        if raw:
            try:
                result = json_loads(raw)
            except (json.JSONDecodeError, TypeError):
                result = {"error": {"code": "server_error", "message": "Failed to parse stored response"}}
        else:
            result = {"error": {"code": "server_error", "message": "Output not found in storage"}}
        if isinstance(result, dict) and result.get('response_format') == 'b64_json':
            await _apply_b64_json_to_image_output(result.get('output', []), storage=storage)
        _strip_internal_fields(result.get('output', []) if isinstance(result, dict) else [])
        return jsonify(result), 200

    if record_status == "failed":
        created_at = bg_record.get("created_at")
        error_raw = bg_record.get("error")

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
            if obj.get("code") not in _VALID_ERROR_CODES:
                obj = dict(obj)
                obj["code"] = "server_error"
            return obj

        error_obj = _normalise_error(error_raw)
        ptc, um = await _extract_response_fields()
        return jsonify({
            "id": bg_record["response_id"],
            "object": "response",
            "created_at": int(created_at.timestamp()) if created_at else None,
            "model": bg_record.get("model", ""),
            "status": "failed",
            "parallel_tool_calls": ptc,
            "metadata": um,
            "error": error_obj,
        }), 200

    # Still in_progress (or queued)
    created_at = bg_record.get("created_at")
    ptc, um = await _extract_response_fields()
    return jsonify({
        "id": bg_record["response_id"],
        "object": "response",
        "created_at": int(created_at.timestamp()) if created_at else None,
        "model": bg_record.get("model", ""),
        "status": record_status,
        "parallel_tool_calls": ptc,
        "metadata": um,
        "background": True,
    }), 200


@gateway_responses_bp.route('/v1/test/background-resync', methods=['POST'])
async def test_background_resync():
    """Manually trigger one background resync cycle.

    Optional JSON body: {"min_age_minutes": 5} to override the default (10).
    """
    from app.usagerecord.background_resync_service import _do_resync

    data = await request.get_json(silent=True) or {}
    min_age_minutes = int(data.get("min_age_minutes", 10))

    t0 = time.time()
    try:
        await _do_resync(current_app, min_age_minutes=min_age_minutes)
        elapsed = round(time.time() - t0, 3)
        return jsonify({
            "status": "ok",
            "message": f"Resync cycle completed in {elapsed}s — check logs for details",
            "min_age_minutes": min_age_minutes,
        }), 200
    except Exception as exc:
        elapsed = round(time.time() - t0, 3)
        logger.error(f"[test_resync] Resync failed after {elapsed}s: {exc}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(exc),
            "min_age_minutes": min_age_minutes,
            "elapsed_s": elapsed,
        }), 500
