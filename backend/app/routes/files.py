"""
Files API route module.

Provides an OpenAI-compatible /v1/files endpoint that supports:
- Standard multipart/form-data file upload (OpenAI-compatible)
- JSON body with `input_image`, `input_audio`, `input_video`, or `input_file`

Uploaded files are registered in the Volcengine ARK asset library via
CreateAsset API, assigned to the specified AssetGroup for use with
Seedance video generation and other ARK services.
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import time
import uuid
from typing import Optional

from quart import Blueprint, request, jsonify, g

from app import get_db_session
from app.routes.gateway_helpers import (
    get_current_user_or_api_key,
    _parse_json_body,
    _log_error,
    _build_error_context,
    _check_allowed_models,
)
from app.providers.volcengine.asset import create_asset, upload_and_create_asset, delete_asset, poll_asset_status, batch_delete_assets
from app.models import UploadedFile

logger = logging.getLogger("gateway")

files_bp = Blueprint('files', __name__)


def _error_response(message, code="request_failed", param="", status_code=500):
    return jsonify({
        "error": {
            "message": message,
            "type": "one_api_error",
            "param": param,
            "code": code,
        }
    }), status_code


def _gen_file_id() -> str:
    """Generate a unique file ID (OpenAI-compatible format)."""
    return f"file-{uuid.uuid4().hex[:24]}"


def _mime_to_ext(content_type: str) -> str:
    """Guess a file extension from a MIME type."""
    ext_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
    }
    ext = ext_map.get((content_type or "").lower())
    if ext:
        return ext
    guess = mimetypes.guess_extension(content_type or "")
    return guess or ".bin"


async def _get_volcengine_credentials(session, group_id: int, provider_id: Optional[int] = None):
    """
    Look up the Volcengine provider belonging to the API key's group.

    Returns a dict with:
        api_key:        Bearer token / API key
        access_key:     ARK Access Key ID (from extra_config)
        secret_key:     ARK Secret Access Key (from extra_config)
        ark_region:     ARK region (from extra_config or default)
    """
    from sqlalchemy import select as sa_select
    from app.models import Provider

    query = sa_select(Provider).where(
        Provider.type == "volcengine",
        Provider.group_id == group_id,
        Provider.is_active == True,
    )
    if provider_id:
        query = query.where(Provider.id == provider_id)

    result = await session.execute(query)
    provider = result.scalars().first()

    if not provider:
        raise RuntimeError(
            "No active Volcengine provider found. "
            "Please configure a Volcengine provider first."
        )

    extra = provider.extra_config or {}

    creds = {
        "api_key": provider.api_key or "",
        "access_key": extra.get("ark_access_key", ""),
        "ark_group_id": extra.get("ark_group_id", ""),
        "secret_key": extra.get("ark_secret_key", ""),
        "ark_region": extra.get("ark_region", "cn-beijing"),
        "provider_id": provider.id,
        "provider_name": provider.name,
    }

    if not creds["api_key"] and not (creds["access_key"] and creds["secret_key"]):
        raise RuntimeError(
            "Volcengine provider is missing credentials. "
            "Set api_key (Bearer token) or extra_config.ark_access_key + "
            "extra_config.ark_secret_key for HMAC-SHA256 signing."
        )

    return creds


async def _get_volcengine_credentials_for_upload(
    session, group_id: int, user_id: Optional[str], provider_id: Optional[int] = None,
):
    """
    Resolve Volcengine credentials for a seedance-ref upload.

    When ``provider_id`` is given (caller pinned via the ``-{providerId}`` API
    key suffix), that provider is used directly. Otherwise the upload provider
    is chosen by the same load balancer that routes seedance video generation:
    among the group's active Volcengine providers, pick the one whose seedance
    models win priority/traffic_ratio selection. This makes an unpinned upload
    land on the same account that generation would route to for the same user,
    so the asset and the later generation call share an account by default.

    Returns the same creds dict shape as ``_get_volcengine_credentials``.
    """
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import selectinload
    from app.models import Provider, Model
    from app.providers.volcengine.video_generation import is_seedance_video_model
    from app.middleware.gateway_service import GatewayService

    # Explicit pin → fetch that provider directly.
    if provider_id:
        return await _get_volcengine_credentials(session, group_id, provider_id)

    # Active Volcengine providers in the group.
    providers_result = await session.execute(
        sa_select(Provider).where(
            Provider.type == "volcengine",
            Provider.group_id == group_id,
            Provider.is_active == True,
        )
    )
    providers = providers_result.scalars().all()
    if not providers:
        raise RuntimeError(
            "No active Volcengine provider found. "
            "Please configure a Volcengine provider first."
        )
    if len(providers) == 1:
        return await _get_volcengine_credentials(session, group_id, providers[0].id)

    provider_ids = [p.id for p in providers]

    # Seedance models on those providers — reuse the gen-side routing weights.
    models_result = await session.execute(
        sa_select(Model).where(
            Model.provider_id.in_(provider_ids),
            Model.is_active == True,
        ).options(selectinload(Model.provider))
    )
    seedance_models = [
        m for m in models_result.scalars().all()
        if not m.is_retired
        and m.provider and m.provider.is_active
        and (is_seedance_video_model(m.name) if m.name else False)
    ]

    if seedance_models:
        chosen_model = GatewayService._select_model_by_priority(seedance_models, user_id=user_id)
        return await _get_volcengine_credentials(session, group_id, chosen_model.provider_id)

    # No seedance model configured yet — fall back to first-active so upload
    # still works; the recorded provider_id lets generation follow it later.
    return await _get_volcengine_credentials(session, group_id, providers[0].id)

async def _get_group_project_name(session, group_id: int) -> str:
    """
    Look up the API key's group and extract the 'dept' tag value
    to use as project_name for Volcengine ARK CreateAsset.

    Args:
        session:   Open async DB session
        group_id:  The API key's group ID

    Returns:
        The dept tag value, or "default" if not found.
    """
    from sqlalchemy import select as sa_select
    from app.models import Group

    result = await session.execute(
        sa_select(Group).where(Group.id == group_id)
    )
    group = result.scalars().first()

    if not group or not group.tags:
        return "default"

    for tag in group.tags:
        if isinstance(tag, dict) and tag.get("name") == "dept":
            dept_value = tag.get("value", "").strip()
            if dept_value:
                return dept_value

    return "default"


async def _save_uploaded_file(file_data: bytes, filename: str, content_type: str) -> tuple[str, str]:
    """
    Save uploaded file to local/S3 storage.

    Returns a ``(storage_key, public_url)`` tuple:
    - ``storage_key``: the key used with the storage backend (e.g.
      ``uploads/xxx.png``). Persisted on the UploadedFile row so the hosted
      copy can be retrieved or cleaned up later.
    - ``public_url``: an absolute, publicly reachable URL for the file,
      derived from the storage backend and ``PUBLIC_BASE_URL``. Handed to the
      Volcengine ARK CreateAsset API so ARK can fetch the bytes.
    """
    ext = _mime_to_ext(content_type)
    if not filename or filename == "file":
        safe_name = f"{uuid.uuid4().hex[:12]}{ext}"
    else:
        safe_name = filename
        if not safe_name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")):
            safe_name = f"{safe_name}{ext}"

    # Use the storage backend to persist the file
    from app.storage.factory import get_storage_backend

    storage = get_storage_backend()
    file_key = f"uploads/{safe_name}"
    url = storage.write_binary(file_key, file_data, content_type or "application/octet-stream")

    # Convert relative URL to absolute if needed
    if url.startswith("http://") or url.startswith("https://"):
        return file_key, url

    public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base:
        logger.warning(
            "files: storage returned relative URL %r but PUBLIC_BASE_URL is not set. "
            "Volcengine ARK cannot fetch relative URLs."
        )
    else:
        url = f"{public_base}{url if url.startswith('/') else '/' + url}"

    return file_key, url


# -----------------------------------------------------------------------------
# Shared upload helpers
# -----------------------------------------------------------------------------

def _ark_credentials(creds: dict) -> dict:
    """Common ARK auth kwargs shared by all asset API calls."""
    return {
        "access_key": creds.get("access_key"),
        "secret_key": creds.get("secret_key"),
        "api_key": creds.get("api_key"),
        "region": creds.get("ark_region", "cn-beijing"),
    }


def _validate_purpose(purpose: str, auth_ctx):
    """Return an error response if ``purpose`` is unsupported, else None."""
    if purpose != "seedance-ref":
        _log_error("files_upload", 400, f"Unsupported purpose: {purpose}", _build_error_context(auth_ctx))
        return _error_response(
            f"Unsupported purpose '{purpose}'. Only 'seedance-ref' is currently supported.",
            code="invalid_request", param="purpose", status_code=400)
    return None


def _require_group_id(group_id: str, auth_ctx):
    """Return an error response if ``group_id`` is missing, else None."""
    if group_id:
        return None
    _log_error("files_upload", 400,
               "group_id is required. Provide it in the request or in provider extra_config.ark_group_id.",
               _build_error_context(auth_ctx))
    return _error_response(
        "group_id is required. Provide it in the request or configure extra_config.ark_group_id on the Volcengine provider.",
        code="invalid_request", param="group_id", status_code=400)


async def _resolve_project_name(auth_ctx) -> str:
    """Resolve the ARK project_name from the API key group's 'dept' tag."""
    if not auth_ctx or not auth_ctx.api_key_group_id:
        return "default"
    try:
        async with get_db_session() as session:
            return await _get_group_project_name(session, auth_ctx.api_key_group_id)
    except Exception as e:
        logger.warning("files: failed to get group dept tag: %s, using default", e)
        return "default"


def _build_uploaded_file_record(
    file_id: str, object_key: str, purpose: str, auth_ctx,
    client_user_id, storage_key: Optional[str], provider_id: Optional[int],
) -> UploadedFile:
    """Construct an UploadedFile row with the common fields filled in."""
    raw_key = auth_ctx.api_key_raw if auth_ctx else None
    # Store the SHA-256 hash of the raw key (same scheme as
    # UsageRecord.api_key_hash), not a truncated "sk-xxx..." preview, so the
    # row can be joined back to an API key / usage records for querying.
    api_key = hashlib.sha256(raw_key.encode()).hexdigest() if raw_key else None
    return UploadedFile(
        file_id=file_id,
        object_key=object_key,
        purpose=purpose,
        group_id=auth_ctx.api_key_group_id if auth_ctx else None,
        api_key=api_key,
        user_id=auth_ctx.user_id if auth_ctx else None,
        client_user_id=client_user_id,
        type="volcengine",
        storage_key=storage_key,
        provider_id=provider_id,
    )


async def _persist_upload_record(record: UploadedFile) -> bool:
    """Persist a single UploadedFile row. Returns True on success."""
    try:
        async with get_db_session() as session:
            session.add(record)
            await session.commit()
        return True
    except Exception as e:
        logger.warning("files: failed to persist upload record: %s", e)
        return False


async def _handle_multipart_upload(auth_ctx, creds):
    """Handle a multipart/form-data file upload (single file)."""
    files_uploaded = await request.files
    form = await request.form

    file_obj = files_uploaded.get("file")
    if not file_obj:
        _log_error("files_upload", 400, "No file provided", _build_error_context(auth_ctx))
        return _error_response("No file provided. Use 'file' field for multipart upload.", code="invalid_request", param="file", status_code=400)

    purpose = form.get("purpose", "seedance-ref")
    err = _validate_purpose(purpose, auth_ctx)
    if err:
        return err

    group_id = form.get("group_id") or creds.get("ark_group_id", "")
    err = _require_group_id(group_id, auth_ctx)
    if err:
        return err

    file_data = file_obj.read()
    filename = file_obj.filename or "upload"
    mime_type = file_obj.content_type or "application/octet-stream"
    logger.info("files: multipart upload filename=%s size=%d purpose=%s", filename, len(file_data), purpose)

    # Save to storage and get a public URL.
    try:
        storage_key, public_url = await _save_uploaded_file(file_data, filename, mime_type)
    except Exception as e:
        logger.exception("files: failed to save uploaded file")
        _log_error("files_upload", 500, f"Failed to save file: {e}", _build_error_context(auth_ctx))
        return _error_response(f"Failed to save uploaded file: {e}", code="storage_error", status_code=500)

    if not public_url.startswith(("http://", "https://")):
        _log_error("files_upload", 500,
                   f"Could not generate public URL for uploaded file: {public_url}. Set PUBLIC_BASE_URL environment variable.",
                   _build_error_context(auth_ctx))
        return _error_response("Could not generate public URL. Set PUBLIC_BASE_URL to make uploads accessible.", code="storage_error", status_code=500)

    project_name = await _resolve_project_name(auth_ctx)
    ark = _ark_credentials(creds)

    # Register the asset and poll until Active.
    try:
        result = await upload_and_create_asset(
            group_id=group_id, image_url=public_url,
            name=filename.rsplit(".", 1)[0], project_name=project_name, **ark,
        )
    except RuntimeError as e:
        _log_error("files_upload", 502, str(e), _build_error_context(auth_ctx))
        return _error_response(str(e), code="upstream_error", status_code=502)

    asset_id = result.get("Result", {}).get("Id", _gen_file_id())

    try:
        await poll_asset_status(asset_ids=[asset_id], project_name=project_name, **ark)
    except RuntimeError as e:
        # Clean up the failed/pending asset (best-effort).
        try:
            await delete_asset(asset_id=asset_id, project_name=project_name, **ark)
        except Exception as cleanup_err:
            logger.warning("files: failed to clean up asset %s: %s", asset_id, cleanup_err)
        _log_error("files_upload", 502, str(e), _build_error_context(auth_ctx))
        return _error_response(str(e), code="upstream_error", status_code=502)

    file_id = _gen_file_id()
    await _persist_upload_record(_build_uploaded_file_record(
        file_id, asset_id, purpose, auth_ctx, form.get("user"), storage_key, creds.get("provider_id"),
    ))

    return jsonify({
        "id": file_id,
        "object": "file",
        "bytes": len(file_data),
        "created_at": int(time.time()),
        "filename": filename,
        "purpose": purpose,
    })


_MEDIA_KEYS = frozenset({"input_image", "input_audio", "input_video", "input_file"})


def _collect_json_media_urls(data):
    """
    Collect media URLs from a JSON upload body.

    Each of the ``_MEDIA_KEYS`` fields may be a URL string or an array of URL
    strings; all fields may be present simultaneously. Insertion order is
    preserved.

    Returns ``(media_urls, media_keys, error_response_or_None)``.
    """
    media_urls: list[str] = []
    media_keys: list[str] = []
    for key, val in data.items():
        if key not in _MEDIA_KEYS:
            continue
        if isinstance(val, str):
            media_urls.append(val)
            media_keys.append(key)
        elif isinstance(val, list):
            for v in val:
                if not isinstance(v, str):
                    return None, None, _error_response(
                        f"Each item in '{key}' must be a URL string.",
                        code="invalid_request", param=key, status_code=400)
            media_urls.extend(val)
            media_keys.append(key)
        else:
            return None, None, _error_response(
                f"'{key}' must be a string (URL) or array of URL strings.",
                code="invalid_request", param=key, status_code=400)
    return media_urls, media_keys, None


def _asset_name(filename: Optional[str], media_url: str, idx: int, multiple: bool) -> Optional[str]:
    """Derive the asset name for a JSON-mode upload."""
    if filename:
        return filename
    if not multiple:
        return None
    url_path = media_url.split("?")[0]
    name = url_path.rsplit("/", 1)[-1] or f"media_{idx}"
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name


async def _handle_json_upload(auth_ctx, creds):
    """Handle an application/json upload (one or more remote media URLs)."""
    data = await _parse_json_body()
    if not data:
        _log_error("files_upload", 400, "Invalid or empty JSON request body")
        return _error_response("Invalid or empty JSON request body", code="invalid_request", status_code=400)

    media_urls, media_keys, err = _collect_json_media_urls(data)
    if err:
        return err
    if not media_urls:
        _log_error("files_upload", 400,
                   "input_image, input_audio, input_video, or input_file is required for JSON mode",
                   _build_error_context(auth_ctx))
        return _error_response(
            "input_image, input_audio, input_video, or input_file is required when using JSON mode.",
            code="invalid_request", param="input_image", status_code=400)

    purpose = data.get("purpose", "seedance-ref")
    err = _validate_purpose(purpose, auth_ctx)
    if err:
        return err

    group_id = data.get("group_id") or creds.get("ark_group_id", "")
    err = _require_group_id(group_id, auth_ctx)
    if err:
        return err

    filename = data.get("filename")
    logger.info("files: JSON mode keys=%s urls=%d purpose=%s group=%s",
                ",".join(media_keys), len(media_urls), purpose, group_id)

    project_name = await _resolve_project_name(auth_ctx)
    ark = _ark_credentials(creds)

    # Register each remote URL directly with ARK (no download). The original
    # URL is recorded as storage_key for later retrieval / re-registration.
    results, errors = [], []
    multiple = len(media_urls) > 1
    for idx, media_url in enumerate(media_urls):
        name = _asset_name(filename, media_url, idx, multiple)
        try:
            result = await upload_and_create_asset(
                group_id=group_id, image_url=media_url, name=name,
                project_name=project_name, **ark,
            )
            results.append({"result": result, "storage_key": media_url})
        except RuntimeError as e:
            logger.error("files: failed to create asset for url %s: %s", media_url[:80], e)
            errors.append({"url": media_url, "error": str(e)})

    # Poll all created assets to Active.
    asset_ids_to_poll = [
        r["result"].get("Result", {}).get("Id", "")
        for r in results if r["result"].get("Result", {}).get("Id")
    ]
    if asset_ids_to_poll:
        try:
            await poll_asset_status(asset_ids=asset_ids_to_poll, project_name=project_name, **ark)
        except RuntimeError as e:
            try:
                await batch_delete_assets(asset_ids=asset_ids_to_poll, project_name=project_name, **ark)
            except Exception as cleanup_err:
                logger.warning("files: failed to clean up assets: %s", cleanup_err)
            _log_error("files_upload", 502, str(e), _build_error_context(auth_ctx))
            return _error_response(str(e), code="upstream_error", status_code=502)

    if not results and errors:
        _log_error("files_upload", 502, f"All assets failed: {errors[0]['error']}", _build_error_context(auth_ctx))
        return _error_response(f"Failed to create assets: {errors[0]['error']}", code="upstream_error", status_code=502)

    # Persist rows and build the response.
    uploaded_files = []
    client_user_id = data.get("user")
    provider_id = creds.get("provider_id")
    for item in results:
        asset_id = item["result"].get("Result", {}).get("Id", "")
        file_id = _gen_file_id()
        await _persist_upload_record(_build_uploaded_file_record(
            file_id, asset_id, purpose, auth_ctx, client_user_id, item.get("storage_key"), provider_id,
        ))
        uploaded_files.append({
            "id": file_id,
            "object": "file",
            "bytes": item.get("bytes", 0),
            "created_at": int(time.time()),
        })

    response = {"object": "list", "data": uploaded_files, "purpose": purpose}
    if errors:
        response["errors"] = errors
    return jsonify(response)


# =============================================================================
# POST /v1/files — Upload files to Volcengine asset library
# =============================================================================

@files_bp.route('/v1/files', methods=['POST', 'HEAD', 'OPTIONS'])
async def upload_file():
    """
    OpenAI-compatible file upload endpoint.

    Supports two modes:

    1. multipart/form-data (standard OpenAI format):
       - ``purpose``: File purpose (e.g. "vision", "seedance-ref")
       - ``file``:    Binary file data
       - ``group_id``: (optional) Volcengine ARK AssetGroup ID

    2. application/json (extended format):
       - ``input_image`` / ``input_audio`` / ``input_video`` / ``input_file``: URL string or array of URL strings (at least one must be provided)
       - ``purpose``:     File purpose
       - ``group_id``:    Volcengine ARK AssetGroup ID (required or from provider config)
       - ``filename``:    (optional) Asset name
    """
    if request.method == 'HEAD' or request.method == 'OPTIONS':
        return '', 200

    # ── Phase 1: Auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("files_upload", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    # ── Get Volcengine credentials ──
    # The chosen provider is recorded on the UploadedFile row so that seedance
    # generation can be routed to the same account that holds the asset.
    provider_id = auth_ctx.provider_id_override if auth_ctx else None
    try:
        async with get_db_session() as session:
            creds = await _get_volcengine_credentials_for_upload(
                session,
                auth_ctx.api_key_group_id,
                auth_ctx.user_id if auth_ctx else None,
                provider_id,
            )
    except RuntimeError as e:
        _log_error("files_upload", 500, str(e), _build_error_context(auth_ctx))
        return _error_response(str(e), code="provider_error", status_code=500)

    # ── Dispatch by content type ──
    content_type = request.content_type or ""
    if "multipart/form-data" in content_type:
        return await _handle_multipart_upload(auth_ctx, creds)
    if "application/json" in content_type:
        return await _handle_json_upload(auth_ctx, creds)
    _log_error("files_upload", 415, f"Unsupported content type: {content_type}")
    return _error_response(
        f"Unsupported content type: {content_type}. Use multipart/form-data or application/json.",
        code="invalid_request", status_code=415)




# =============================================================================
# DELETE /v1/files/<file_id> — Delete an uploaded file
# =============================================================================

@files_bp.route('/v1/files/<file_id>', methods=['DELETE'])
async def delete_file(file_id: str):
    """OpenAI-compatible file deletion endpoint.

    Looks up the file by file_id (file-xxx format) in ml_uploaded_files.
    If the purpose is seedance-ref, also calls Volcengine ARK DeleteAsset
    to remove the asset from the material library. Then deletes the local
    database record.

    Returns:
        {"id": "file-xxx", "object": "file", "deleted": true}
    """
    # ── Phase 1: Auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("files_delete", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    # ── Phase 2: Look up file record ──
    from sqlalchemy import select as sa_select

    async with get_db_session() as session:
        result = await session.execute(
            sa_select(UploadedFile).where(UploadedFile.file_id == file_id)
        )
        record = result.scalars().first()

        if not record:
            _log_error("files_delete", 404, f"File not found: {file_id}", _build_error_context(auth_ctx))
            return _error_response(f"File not found: {file_id}", code="not_found", param="file_id", status_code=404)

        object_key = record.object_key
        purpose = record.purpose
        file_type = record.type
        # Prefer the provider that actually holds the asset (recorded at upload
        # time) so DeleteAsset hits the right account. Fall back to the API
        # key's pinned provider for legacy rows without a recorded provider_id.
        asset_provider_id = record.provider_id or (auth_ctx.provider_id_override if auth_ctx else None)
        storage_key = record.storage_key

        # ── Phase 3: Delete from upstream if seedance-ref ──
        # Asset IDs use an "asset-" prefix; match case-insensitively to be
        # robust against either "asset-..." or "Asset-..." forms.
        if purpose == "seedance-ref" and file_type == "volcengine" and object_key.lower().startswith("asset-"):
            try:
                creds = await _get_volcengine_credentials(session, auth_ctx.api_key_group_id, asset_provider_id)
                # Resolve project_name from group's dept tag
                project_name = "default"
                if auth_ctx and auth_ctx.api_key_group_id:
                    project_name = await _get_group_project_name(session, auth_ctx.api_key_group_id)

                await delete_asset(
                    asset_id=object_key,
                    project_name=project_name,
                    access_key=creds.get("access_key"),
                    secret_key=creds.get("secret_key"),
                    api_key=creds.get("api_key"),
                    region=creds.get("ark_region", "cn-beijing"),
                )
                logger.info(
                    "files: deleted asset %s from Volcengine ARK (provider_id=%s)",
                    object_key, asset_provider_id,
                )
            except RuntimeError as e:
                logger.error("files: failed to delete asset %s from Volcengine: %s", object_key, e)
                _log_error("files_delete", 502, f"Failed to delete upstream asset: {e}", _build_error_context(auth_ctx))
                return _error_response(f"Failed to delete upstream asset: {e}", code="upstream_error", status_code=502)

        # ── Phase 3.5: Delete the hosted storage copy ──
        # Only multipart uploads leave a local storage copy (storage_key is a
        # backend key like "uploads/xxx.png"). JSON-mode uploads store the
        # original remote URL in storage_key instead — there's nothing of
        # ours to delete there, so skip it.
        if storage_key and not storage_key.startswith(("http://", "https://")):
            try:
                from app.storage.factory import get_storage_backend
                get_storage_backend().delete_binary(storage_key)
            except Exception as e:
                # Best-effort: the upstream asset and DB row are the source of
                # truth; don't fail the delete over a stale local copy.
                logger.warning("files: failed to delete storage copy %s: %s", storage_key, e)

        # ── Phase 4: Delete DB record ──
        await session.delete(record)
        await session.commit()

    return jsonify({
        "id": file_id,
        "object": "file",
        "deleted": True,
    })

# =============================================================================
# GET /v1/files — List uploaded files (stub)
# =============================================================================

@files_bp.route('/v1/files', methods=['GET'])
async def list_files():
    """List uploaded files (stub)."""
    return jsonify({
        "object": "list",
        "data": [],
    })
