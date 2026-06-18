"""
Files API route module.

Provides an OpenAI-compatible /v1/files endpoint that supports:
- Standard multipart/form-data file upload (OpenAI-compatible)
- JSON body with `input_image` parameter (string URL or array of URL strings)

Uploaded files are registered in the Volcengine ARK asset library via
CreateAsset API, assigned to the specified AssetGroup for use with
Seedance video generation and other ARK services.
"""
from __future__ import annotations

import asyncio
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
from app.providers.volcengine.asset import create_asset, upload_and_create_asset, delete_asset
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


async def _get_volcengine_credentials(session, provider_id: Optional[int] = None):
    """
    Look up Volcengine provider credentials from the database.

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


async def _save_uploaded_file(file_data: bytes, filename: str, content_type: str) -> str:
    """
    Save uploaded file to local storage and return a publicly accessible URL.

    Uses the existing storage backend to write the file, then converts the
    relative path to an absolute URL using PUBLIC_BASE_URL env variable.
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
        return url

    public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base:
        logger.warning(
            "files: storage returned relative URL %r but PUBLIC_BASE_URL is not set. "
            "Volcengine ARK cannot fetch relative URLs."
        )
    else:
        url = f"{public_base}{url if url.startswith('/') else '/' + url}"

    return url


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
       - ``input_image``: Image URL string or array of URL strings
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
    provider_id = auth_ctx.provider_id_override if auth_ctx else None
    try:
        async with get_db_session() as session:
            creds = await _get_volcengine_credentials(session, provider_id)
    except RuntimeError as e:
        _log_error("files_upload", 500, str(e), _build_error_context(auth_ctx))
        return _error_response(str(e), code="provider_error", status_code=500)

    # ── Determine content type ──
    content_type = request.content_type or ""

    # ── Extract group_id from request or provider config ──
    group_id: Optional[str] = None

    if "multipart/form-data" in content_type:
        # ── Multipart mode ──
        files_uploaded = await request.files
        form = await request.form

        file_obj = files_uploaded.get("file")
        if not file_obj:
            _log_error("files_upload", 400, "No file provided", _build_error_context(auth_ctx))
            return _error_response("No file provided. Use 'file' field for multipart upload.", code="invalid_request", param="file", status_code=400)

        purpose = form.get("purpose", "seedance-ref")
        group_id = form.get("group_id") or creds.get("ark_group_id", "")

        file_data = file_obj.read()
        filename = file_obj.filename or "upload"
        mime_type = file_obj.content_type or "application/octet-stream"

        logger.info(
            "files: multipart upload filename=%s size=%d purpose=%s",
            filename, len(file_data), purpose,
        )

        if not group_id:
            _log_error("files_upload", 400,
                       "group_id is required. Provide it as a form field or in provider extra_config.ark_group_id.",
                       _build_error_context(auth_ctx))
            return _error_response(
                "group_id is required. Provide it in the request or configure extra_config.ark_group_id on the Volcengine provider.",
                code="invalid_request", param="group_id", status_code=400)

        # Save file and get public URL
        try:
            public_url = await _save_uploaded_file(file_data, filename, mime_type)
        except Exception as e:
            logger.exception("files: failed to save uploaded file")
            _log_error("files_upload", 500, f"Failed to save file: {e}", _build_error_context(auth_ctx))
            return _error_response(f"Failed to save uploaded file: {e}", code="storage_error", status_code=500)

        if not public_url.startswith("http://") and not public_url.startswith("https://"):
            _log_error("files_upload", 500,
                       f"Could not generate public URL for uploaded file: {public_url}. "
                       "Set PUBLIC_BASE_URL environment variable.",
                       _build_error_context(auth_ctx))
            return _error_response(
                "Could not generate public URL. Set PUBLIC_BASE_URL to make uploads accessible.",
                code="storage_error", status_code=500)

        # Register asset in Volcengine ARK
        # Resolve project_name from group's dept tag
        project_name = "default"
        if auth_ctx and auth_ctx.api_key_group_id:
            try:
                async with get_db_session() as session:
                    project_name = await _get_group_project_name(session, auth_ctx.api_key_group_id)
            except Exception as e:
                logger.warning("files: failed to get group dept tag: %s, using default", e)

        try:
            result = await upload_and_create_asset(
                group_id=group_id,
                image_url=public_url,
                name=filename.rsplit(".", 1)[0],
                project_name=project_name,
                access_key=creds.get("access_key"),
                secret_key=creds.get("secret_key"),
                api_key=creds.get("api_key"),
                region=creds.get("ark_region", "cn-beijing"),
            )
        except RuntimeError as e:
            _log_error("files_upload", 502, str(e), _build_error_context(auth_ctx))
            return _error_response(str(e), code="upstream_error", status_code=502)

        asset_id = result.get("Result", {}).get("Id", _gen_file_id())
        request_id = result.get("ResponseMetadata", {}).get("RequestId", "")
        file_id = _gen_file_id()

        # Persist to ml_uploaded_files
        try:
            async with get_db_session() as session:
                record = UploadedFile(
                    file_id=file_id,
                    object_key=asset_id,
                    purpose=purpose,
                    group_id=auth_ctx.api_key_group_id if auth_ctx else None,
                    api_key=(auth_ctx.api_key_raw[:50] + "..." if auth_ctx and auth_ctx.api_key_raw else None),
                    user_id=auth_ctx.user_id if auth_ctx else None,
                    client_user_id=data.get("user") if data else None,
                    type="volcengine",
                )
                session.add(record)
                await session.commit()
        except Exception as e:
            logger.warning("files: failed to persist upload record: %s", e)

        return jsonify({
            "id": file_id,
            "object": "file",
            "bytes": len(file_data),
            "created_at": int(time.time()),
            "filename": filename,
            "purpose": purpose,
            "asset_group_id": group_id,
            "ark_request_id": request_id,
            "object_key": asset_id,
        })

    elif "application/json" in content_type:
        # ── JSON mode (input_image) ──
        data = await _parse_json_body()
        if not data:
            _log_error("files_upload", 400, "Invalid or empty JSON request body")
            return _error_response("Invalid or empty JSON request body", code="invalid_request", status_code=400)

        input_image = data.get("input_image")
        if not input_image:
            _log_error("files_upload", 400, "input_image is required for JSON mode", _build_error_context(auth_ctx))
            return _error_response("input_image is required when using JSON mode.", code="invalid_request", param="input_image", status_code=400)

        # Normalize to list
        if isinstance(input_image, str):
            image_urls = [input_image]
        elif isinstance(input_image, list):
            image_urls = input_image
        else:
            return _error_response(
                "input_image must be a string (URL) or array of URL strings.",
                code="invalid_request", param="input_image", status_code=400)

        purpose = data.get("purpose", "seedance-ref")
        group_id = data.get("group_id") or creds.get("ark_group_id", "")
        filename = data.get("filename")

        if not group_id:
            _log_error("files_upload", 400,
                       "group_id is required. Provide it in the request body or in provider extra_config.ark_group_id.",
                       _build_error_context(auth_ctx))
            return _error_response(
                "group_id is required. Provide it in the request or configure extra_config.ark_group_id on the Volcengine provider.",
                code="invalid_request", param="group_id", status_code=400)

        logger.info(
            "files: JSON input_image mode urls=%d purpose=%s group=%s",
            len(image_urls), purpose, group_id,
        )

        # Resolve project_name from group's dept tag
        project_name = "default"
        if auth_ctx and auth_ctx.api_key_group_id:
            try:
                async with get_db_session() as session:
                    project_name = await _get_group_project_name(session, auth_ctx.api_key_group_id)
            except Exception as e:
                logger.warning("files: failed to get group dept tag: %s, using default", e)

        # Process all image URLs
        results = []
        errors = []
        for idx, img_url in enumerate(image_urls):
            try:
                name = filename or None
                if not name and len(image_urls) > 1:
                    url_path = img_url.split("?")[0]
                    name = url_path.rsplit("/", 1)[-1] or f"image_{idx}"
                    if "." in name:
                        name = name.rsplit(".", 1)[0]

                result = await upload_and_create_asset(
                    group_id=group_id,
                    image_url=img_url,
                    name=name,
                    project_name=project_name,
                    access_key=creds.get("access_key"),
                    secret_key=creds.get("secret_key"),
                    api_key=creds.get("api_key"),
                    region=creds.get("ark_region", "cn-beijing"),
                )
                results.append(result)
            except RuntimeError as e:
                logger.error("files: failed to create asset for url %s: %s", img_url[:80], e)
                errors.append({"url": img_url, "error": str(e)})

        if not results and errors:
            _log_error("files_upload", 502, f"All assets failed: {errors[0]['error']}", _build_error_context(auth_ctx))
            return _error_response(
                f"Failed to create assets: {errors[0]['error']}",
                code="upstream_error", status_code=502)

        # Build response
        uploaded_files = []
        persist_session = None
        try:
            persist_session = get_db_session()
            async with persist_session as session:
                for result in results:
                    asset_id = result.get("Result", {}).get("Id", "")
                    file_id = _gen_file_id()
                    record = UploadedFile(
                        file_id=file_id,
                        object_key=asset_id,
                        purpose=purpose,
                        group_id=auth_ctx.api_key_group_id if auth_ctx else None,
                        api_key=(auth_ctx.api_key_raw[:50] + "..." if auth_ctx and auth_ctx.api_key_raw else None),
                        user_id=auth_ctx.user_id if auth_ctx else None,
                        client_user_id=data.get("user"),
                        type="volcengine",
                    )
                    session.add(record)
                    await session.commit()
                    uploaded_files.append({
                        "id": file_id,
                        "object": "file",
                        "bytes": 0,
                        "created_at": int(time.time()),
                        "object_key": asset_id,
                    })
        except Exception as e:
            logger.warning("files: failed to persist upload record: %s", e)
            # Fallback: still return results without DB persistence
            if not uploaded_files:
                for result in results:
                    asset_id = result.get("Result", {}).get("Id", "")
                    uploaded_files.append({
                        "id": asset_id,
                        "object": "file",
                        "bytes": 0,
                        "created_at": int(time.time()),
                        "object_key": asset_id,
                    })

        response = {
            "object": "list",
            "data": uploaded_files,
            "purpose": purpose,
            "asset_group_id": group_id,
        }
        if errors:
            response["errors"] = errors

        return jsonify(response)

    else:
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

        # ── Phase 3: Delete from upstream if seedance-ref ──
        if purpose == "seedance-ref" and file_type == "volcengine" and object_key.startswith("Asset-"):
            try:
                creds = await _get_volcengine_credentials(session, auth_ctx.provider_id_override if auth_ctx else None)
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
                logger.info("files: deleted asset %s from Volcengine ARK", object_key)
            except RuntimeError as e:
                logger.error("files: failed to delete asset %s from Volcengine: %s", object_key, e)
                _log_error("files_delete", 502, f"Failed to delete upstream asset: {e}", _build_error_context(auth_ctx))
                return _error_response(f"Failed to delete upstream asset: {e}", code="upstream_error", status_code=502)

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
