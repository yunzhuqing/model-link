"""
Videos API route module.

提供异步视频生成端点:
- POST /v1/videos/generations            提交视频生成任务
- GET  /v1/videos/generations/<job_id>   查询视频生成任务

任务通过供应商的异步任务 API (如阿里云 yike SubmitVideoGenerationJob /
GetVideoGenerationJob) 执行, 客户端提交后轮询查询接口获取结果。
"""
import json
import logging

from quart import Blueprint, g, jsonify, request

from app import get_db_session
from app.group_service import get_group_monitoring_config
from app.middleware.gateway_service import (
    GatewayServiceError,
    ModelNotFoundError,
    ProviderError,
)
from app.monitoring import create_tracer
from app.providers.aliyun.video_generation import (
    _substitute_prompt_vars,
    build_input_json,
    infer_job_type,
    parse_output_medias,
)

from app.routes.gateway_helpers import (
    _gateway_service,
    get_current_user_or_api_key,
    _parse_json_body,
    _log_error,
    _build_error_context,
    _check_allowed_models,
)

logger = logging.getLogger("gateway")

videos_bp = Blueprint('videos', __name__)


def _error_response(message, code="request_failed", param="", status_code=500):
    """Return a standardized error response for video endpoints."""
    return jsonify({
        "error": {
            "message": message,
            "type": "one_api_error",
            "param": param,
            "code": code,
        }
    }), status_code


def _normalize_input(prompt: str = "", media: list = None, raw_input=None,
                     var_map: dict = None, file_var_map: dict = None):
    """
    Build the yike ``Input`` JSON string.

    Priority: explicit ``input`` (dict or JSON string) > prompt + media list.

    ``{{var_id}}`` / ``{{file-xxx}}`` placeholders in the prompt are
    substituted with the Aliyun variable names ("图片1" / "Image 1") using
    ``var_map`` / ``file_var_map``. Raw ``input`` JSON keeps its
    Prompt/Medias verbatim except that user-defined ``var_id`` keys on Medias
    items are stripped (yike does not accept them).

    Args:
        prompt: Prompt text
        media: Optional media list
        raw_input: Optional pre-built input (dict or JSON string)
        var_map: Optional var_id → (media_type, index) map
        file_var_map: Optional file_id → (media_type, index) map

    Returns:
        JSON string
    """
    if raw_input is not None:
        obj = None
        if isinstance(raw_input, str):
            try:
                obj = json.loads(raw_input)
            except json.JSONDecodeError:
                obj = None
        elif isinstance(raw_input, dict):
            obj = raw_input

        if obj is None:
            return json.dumps({"Prompt": raw_input}, ensure_ascii=False)

        if isinstance(obj, dict):
            obj = dict(obj)
            # Collect var_id from raw Medias items and strip the field.
            counters = {"image": 0, "video": 0, "audio": 0}
            medias = obj.get("Medias")
            if isinstance(medias, list):
                obj["Medias"] = list(medias)
                merged_map = dict(var_map or {})
                for item in obj["Medias"]:
                    if not isinstance(item, dict):
                        continue
                    mtype = str(item.get("Type") or "").lower()
                    if mtype not in counters:
                        continue
                    counters[mtype] += 1
                    var_id = str(item.get("var_id") or item.get("VarId") or "").strip()
                    if var_id:
                        merged_map[var_id] = (mtype, counters[mtype])
                    item.pop("var_id", None)
                    item.pop("VarId", None)
                var_map = merged_map
            raw_prompt = obj.get("Prompt")
            if isinstance(raw_prompt, str):
                obj["Prompt"] = _substitute_prompt_vars(raw_prompt, var_map, file_var_map)
            return json.dumps(obj, ensure_ascii=False)

    prompt = _substitute_prompt_vars(prompt or "", var_map, file_var_map)
    return build_input_json(prompt=prompt, media=media)


async def _collect_media(data: dict) -> tuple:
    """
    Collect reference media from the request body.

    Accepts ``images`` / ``videos`` / ``audios`` arrays of URL strings, file
    IDs (``file-xxx``, resolved from ml_uploaded_files), or objects with
    ``url`` / ``media_id`` / ``file_id`` / ``var_id`` keys, plus
    ``first_frame_url`` / ``last_frame_url``.

    Aliyun yike assets (type="aliyun") resolve to their upstream ``MediaId``;
    Volcengine ARK assets resolve to ``asset://{asset_id}``.

    Returns:
        ``(media_list, var_map, file_var_map)`` where media_list items are
        ``[{"Type": "image", "Url": "..."}]`` or
        ``[{"Type": "image", "MediaId": "..."}]``, var_map maps user
        ``var_id`` → ``(media_type, index)`` and file_var_map maps
        ``file_id`` → ``(media_type, index)`` for prompt substitution.

    Raises:
        ValueError: When a referenced file_id does not exist.
    """
    media = []
    file_refs: list = []

    def _add(type_: str, url_: str = "", media_id: str = "", var_id: str = "",
             file_id: str = "") -> None:
        if not media_id and url_.startswith("yike://"):
            media_id = url_[len("yike://"):]
            url_ = ""
        if media_id:
            if any(m.get("MediaId") == media_id for m in media):
                return
            item = {"Type": type_, "MediaId": media_id}
        elif url_:
            if any(m.get("Url") == url_ for m in media):
                return
            item = {"Type": type_, "Url": url_}
        else:
            return
        if file_id:
            item["_file_id"] = file_id
        if var_id:
            item["_var_id"] = var_id
        media.append(item)

    def _handle_item(type_: str, item) -> None:
        if isinstance(item, str):
            if item.startswith("file-"):
                file_refs.append((type_, item, ""))
            else:
                _add(type_, item)
        elif isinstance(item, dict):
            media_id = str(item.get("media_id") or item.get("MediaId") or "").strip()
            file_id = str(item.get("file_id") or "").strip()
            var_id = str(item.get("var_id") or "").strip()
            url = item.get("url") or item.get("image_url") or ""
            if media_id:
                _add(type_, media_id=media_id, var_id=var_id)
            elif file_id:
                file_refs.append((type_, file_id, var_id))
            elif url:
                _add(type_, url, var_id=var_id)

    for key, mtype in (("images", "image"), ("videos", "video"), ("audios", "audio")):
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                _handle_item(mtype, item)

    for key in ("first_frame_url", "last_frame_url"):
        value = data.get(key)
        if isinstance(value, dict):
            _handle_item("image", value)
        elif isinstance(value, str) and value:
            _handle_item("image", value)

    if file_refs:
        from sqlalchemy import select as sa_select
        from app.models import UploadedFile

        file_ids = list({fid for _, fid, _ in file_refs})
        async with get_db_session() as session:
            result = await session.execute(
                sa_select(UploadedFile).where(UploadedFile.file_id.in_(file_ids))
            )
            records = {uf.file_id: uf for uf in result.scalars().all()}
        for mtype, fid, var_id in file_refs:
            rec = records.get(fid)
            if rec is None:
                raise ValueError(f"File not found: {fid}")
            if rec.type == "aliyun":
                _add(mtype, media_id=rec.object_key, var_id=var_id, file_id=fid)
            elif rec.storage_key and rec.storage_key.startswith(("http://", "https://")):
                _add(mtype, rec.storage_key, var_id=var_id, file_id=fid)
            else:
                _add(mtype, f"asset://{rec.object_key}", var_id=var_id, file_id=fid)

    # Build var_id / file_id → (media_type, index) maps (type-wise numbering)
    # and strip internal markers.
    var_map: dict = {}
    file_var_map: dict = {}
    counters = {"image": 0, "video": 0, "audio": 0}
    for item in media:
        mtype = item["Type"]
        counters[mtype] += 1
        file_id = item.pop("_file_id", None)
        if file_id:
            file_var_map[file_id] = (mtype, counters[mtype])
        var_id = item.pop("_var_id", None)
        if var_id:
            var_map[var_id] = (mtype, counters[mtype])

    return media, var_map, file_var_map


# ============== Videos Generations API ==============

@videos_bp.route('/v1/videos/generations', methods=['POST'])
async def create_video_generation():
    """Submit a video generation job (async)."""
    # ── Phase 1: auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("videos_generations", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    data = await _parse_json_body()
    if not data:
        _log_error("videos_generations", 400, "Invalid or empty JSON request body")
        return _error_response('Invalid or empty JSON request body', code="invalid_request", status_code=400)

    model_name = data.get('model')
    if not model_name:
        _log_error("videos_generations", 400, "Model is required", _build_error_context(auth_ctx))
        return _error_response('Model is required', code="invalid_request", param="model", status_code=400)

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("videos_generations", 403, acl_error['detail'], _build_error_context(auth_ctx, model_name))
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    prompt = data.get('prompt', '')
    try:
        media, var_map, file_var_map = await _collect_media(data)
    except ValueError as e:
        _log_error("videos_generations", 404, str(e), _build_error_context(auth_ctx, model_name))
        return _error_response(str(e), code="file_not_found", status_code=404)
    input_json = _normalize_input(prompt=prompt, media=media,
                                  raw_input=data.get('input'), var_map=var_map,
                                  file_var_map=file_var_map)

    job_type = data.get('job_type') or infer_job_type(media)
    n = data.get('n', 1)
    try:
        n = int(n)
    except (ValueError, TypeError):
        n = 1

    service_tier = data.get('service_tier')
    if service_tier is not None and not isinstance(service_tier, str):
        _log_error("videos_generations", 400, "service_tier must be a string", _build_error_context(auth_ctx))
        return _error_response('service_tier must be a string', code="invalid_request", param="service_tier", status_code=400)

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ── Phase 2: resolve model ──
    monitoring_config = None
    try:
        async with get_db_session() as session:
            resolved = await _gateway_service.resolve_model(
                session, model_name, group_id, provider_id=provider_id,
                service_tier=service_tier,
            )
            if group_id:
                try:
                    monitoring_config = await get_group_monitoring_config(group_id, session=session)
                except Exception as _e:
                    logger.debug(f"[monitoring] fetch config failed: {_e}")
    except ModelNotFoundError as e:
        _log_error("videos_generations", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("videos_generations", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    tracer = create_tracer(monitoring_config)

    # ── Phase 3: submit job (no DB session) ──
    params = {
        "job_type": job_type,
        "model": resolved.model_real_name,
        "input": input_json,
        "resolution": data.get('resolution'),
        "aspect_ratio": data.get('aspect_ratio'),
        "duration": data.get('duration'),
        "n": n,
        "scene": data.get('scene'),
        "client_token": data.get('client_token'),
        "user_data": data.get('user_data'),
        "job_parameters": data.get('job_parameters'),
    }
    try:
        if tracer:
            tracer.start(model_name, input_data=data)
            tracer.log_input(data)
            tracer.set_metadata({
                "request_id": g.request_id,
                "group_id": group_id,
                "user": auth_ctx.user_name if auth_ctx else None,
                "model_name": model_name,
                "api_key_name": auth_ctx.api_key_name if auth_ctx else None,
            })
        result = await _gateway_service.submit_video_generation(
            resolved=resolved, data=params, tracer=tracer,
        )
        if tracer:
            tracer.log_output(result)
            tracer.end()
        return jsonify({
            "id": result.get("JobId", ""),
            "object": "video_generation",
            "request_id": result.get("RequestId", ""),
            "model": model_name,
            "status": "submitted",
        })
    except ModelNotFoundError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_generations", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_generations", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_generations", e.status_code, e.message,
                   _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="provider_error", status_code=e.status_code)


# ============== Videos Generations Query API ==============

@videos_bp.route('/v1/videos/generations/<job_id>', methods=['GET'])
async def get_video_generation(job_id: str):
    """Query a video generation job by its JobId."""
    # ── Phase 1: auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("videos_get", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    model_name = request.args.get('model')
    if not model_name:
        _log_error("videos_get", 400, "Model is required (query param)", _build_error_context(auth_ctx))
        return _error_response('Model is required (query param)', code="invalid_request", param="model", status_code=400)

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("videos_get", 403, acl_error['detail'], _build_error_context(auth_ctx, model_name))
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    request_id = request.args.get('request_id')

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ── Phase 2: resolve model ──
    monitoring_config = None
    try:
        async with get_db_session() as session:
            resolved = await _gateway_service.resolve_model(
                session, model_name, group_id, provider_id=provider_id,
            )
            if group_id:
                try:
                    monitoring_config = await get_group_monitoring_config(group_id, session=session)
                except Exception as _e:
                    logger.debug(f"[monitoring] fetch config failed: {_e}")
    except ModelNotFoundError as e:
        _log_error("videos_get", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("videos_get", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    tracer = create_tracer(monitoring_config)

    # ── Phase 3: query job (no DB session) ──
    try:
        if tracer:
            tracer.start(model_name, input_data={"job_id": job_id, "request_id": request_id})
            tracer.set_metadata({
                "request_id": g.request_id,
                "group_id": group_id,
                "user": auth_ctx.user_name if auth_ctx else None,
                "model_name": model_name,
                "api_key_name": auth_ctx.api_key_name if auth_ctx else None,
            })
        result = await _gateway_service.get_video_generation(
            resolved=resolved, job_id=job_id, request_id=request_id, tracer=tracer,
        )
        if tracer:
            tracer.log_output(result)
            tracer.end()

        job = result.get("VideoGenerationJob") or {}
        if not isinstance(job, dict):
            job = {}
        status = job.get("Status") or "Created"
        response = {
            "id": job_id,
            "object": "video_generation",
            "request_id": result.get("RequestId", ""),
            "model": model_name,
            "status": status,
        }
        if status == "Failed":
            response["error"] = {
                "message": job.get("ErrorMessage", "Video generation failed"),
            }
        else:
            medias = parse_output_medias(job.get("Output"))
            if medias:
                response["data"] = [
                    {"media_id": m.get("MediaId", ""), "url": m.get("OutputUrl", "")}
                    for m in medias
                ]
        return jsonify(response)
    except ModelNotFoundError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_get", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_get", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_get", e.status_code, e.message,
                   _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="provider_error", status_code=e.status_code)


# ============== Videos Generation Credit Query API ==============

@videos_bp.route('/v1/videos/generations/<job_id>/credit', methods=['GET'])
async def get_video_generation_credit(job_id: str):
    """Query the credit cost consumed by a finished video generation job."""
    # ── Phase 1: auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("videos_credit_get", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    model_name = request.args.get('model')
    if not model_name:
        _log_error("videos_credit_get", 400, "Model is required (query param)", _build_error_context(auth_ctx))
        return _error_response('Model is required (query param)', code="invalid_request", param="model", status_code=400)

    acl_error = _check_allowed_models(auth_ctx, model_name)
    if acl_error:
        _log_error("videos_credit_get", 403, acl_error['detail'], _build_error_context(auth_ctx, model_name))
        return _error_response(acl_error['detail'], code="model_not_allowed", status_code=403)

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    provider_id = auth_ctx.provider_id_override if auth_ctx else None

    # ── Phase 2: resolve model ──
    monitoring_config = None
    try:
        async with get_db_session() as session:
            resolved = await _gateway_service.resolve_model(
                session, model_name, group_id, provider_id=provider_id,
            )
            if group_id:
                try:
                    monitoring_config = await get_group_monitoring_config(group_id, session=session)
                except Exception as _e:
                    logger.debug(f"[monitoring] fetch config failed: {_e}")
    except ModelNotFoundError as e:
        _log_error("videos_credit_get", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        _log_error("videos_credit_get", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)

    tracer = create_tracer(monitoring_config)

    # ── Phase 3: query credit (no DB session) ──
    try:
        if tracer:
            tracer.start(model_name, input_data={"job_id": job_id})
            tracer.set_metadata({
                "request_id": g.request_id,
                "group_id": group_id,
                "user": auth_ctx.user_name if auth_ctx else None,
                "model_name": model_name,
                "api_key_name": auth_ctx.api_key_name if auth_ctx else None,
            })
        result = await _gateway_service.get_video_job_credit(
            resolved=resolved, job_id=job_id, tracer=tracer,
        )
        if tracer:
            tracer.log_output(result)
            tracer.end()

        response = {
            "id": job_id,
            "object": "video_generation_credit",
            "model": model_name,
            "request_id": result.get("RequestId", ""),
            "job_id": result.get("JobId", job_id),
            "job_credit_cost": result.get("JobCreditCost", 0),
            "credit_status": result.get("CreditStatus", ""),
        }
        return jsonify(response)
    except ModelNotFoundError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_credit_get", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="model_not_found", param="model", status_code=e.status_code)
    except GatewayServiceError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_credit_get", e.status_code, e.message, _build_error_context(auth_ctx, model_name))
        return _error_response(e.message, code="request_failed", status_code=e.status_code)
    except ProviderError as e:
        if tracer:
            tracer.end(error=e)
        _log_error("videos_credit_get", e.status_code, e.message,
                   _build_error_context(auth_ctx, model_name, provider_id=resolved.provider_id, provider_name=resolved.provider_name))
        return _error_response(e.message, code="provider_error", status_code=e.status_code)
