"""
Files API route module.

Provides an OpenAI-compatible /v1/files endpoint that supports:
- Standard multipart/form-data file upload (OpenAI-compatible)
- JSON body with `input_image`, `input_audio`, `input_video`, or `input_file`
- File retrieval (GET /v1/files/<file_id>) with live upstream asset status

Uploaded files are registered into the video-generation provider's asset
library chosen from the API key's video models: Volcengine ARK (CreateAsset,
for seedance models) or Aliyun yike (ImportMedia, for wonder/wan models).
"""
from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from typing import Any, Dict, Optional

from quart import Blueprint, request, jsonify, g

from app import get_db_session
from app.routes.gateway_helpers import (
    get_current_user_or_api_key,
    _parse_json_body,
    _log_error,
    _build_error_context,
    _check_allowed_models,
)
from app.providers.volcengine.asset import (
    create_asset,
    upload_and_create_asset,
    delete_asset,
    get_asset,
    poll_asset_status,
    batch_delete_assets,
)
from app.providers.aliyun.video_generation import (
    delete_medias as aliyun_delete_medias,
    import_media as aliyun_import_media,
    get_media as aliyun_get_media,
    is_aliyun_video_model,
)
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


def _seedance_asset_vendor(provider) -> Optional[str]:
    """Resolve the asset protocol used by a Seedance-capable provider."""
    provider_type = str(getattr(provider, "type", "") or "").lower()
    if provider_type in ("volcengine", "aliyun"):
        return provider_type
    extra = getattr(provider, "extra_config", None) or {}
    vendor = str(extra.get("seedance_asset_vendor") or "").strip().lower()
    return vendor if vendor in ("volcengine", "aliyun") else None


def _volcengine_credentials_from_provider(provider) -> dict:
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
            f"Provider {provider.id} is missing Volcengine asset credentials."
        )
    return creds


def _aliyun_credentials_from_provider(provider) -> dict:
    extra = provider.extra_config or {}
    access_key_id = str(extra.get("access_key_id") or "").strip()
    access_key_secret = str(extra.get("access_key_secret") or "").strip()
    if (not access_key_id or not access_key_secret) and provider.api_key:
        raw_key = str(provider.api_key).strip()
        if ":" in raw_key:
            key_id, key_secret = raw_key.split(":", 1)
            access_key_id = access_key_id or key_id.strip()
            access_key_secret = access_key_secret or key_secret.strip()
    if not access_key_id or not access_key_secret:
        raise RuntimeError(
            f"Provider {provider.id} is missing Aliyun asset credentials."
        )
    return {
        "vendor": "aliyun",
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "region": str(extra.get("region") or "cn-shanghai").strip(),
        "endpoint": str(extra.get("endpoint") or "").strip() or None,
        "api_version": str(extra.get("api_version") or "").strip() or None,
        "provider_id": provider.id,
        "provider_name": provider.name,
    }


async def _resolve_video_ref_credentials(session, auth_ctx, provider_id: Optional[int] = None):
    """
    Resolve the upload provider for a ``seedance-ref`` (video-generation
    reference) upload.

    Every active provider exposing Seedance 2.x+ through ``Model.name`` or
    ``Model.alias`` is selected, subject to the API key's ``allowed_models``.
    Volcengine uses ARK CreateAsset and Aliyun uses yike ImportMedia. Other
    provider types must declare ``extra_config.seedance_asset_vendor`` as
    ``volcengine`` or ``aliyun`` to select a supported asset protocol.

    Selection order:
      1. Explicit provider pin (``sk-xxx-{providerId}`` suffix) → that provider
         directly, routed by its ``type``.
      2. Otherwise, gather every eligible provider and upload the same logical
         file to all of them so Responses routing remains unconstrained.

    Returns a creds dict shaped like ``_get_volcengine_credentials`` (Volcengine)
    or ``_get_aliyun_credentials`` (Aliyun, carrying ``vendor="aliyun"``).
    """
    from sqlalchemy import select as sa_select
    from app.models import Provider, Model

    # Explicit pin → fetch that provider directly, routing by its configured
    # Seedance asset protocol.
    if provider_id:
        result = await session.execute(
            sa_select(Provider).where(
                Provider.id == provider_id,
                Provider.is_active == True,
            )
        )
        provider = result.scalars().first()
        if not provider:
            raise RuntimeError(f"Provider {provider_id} not found or inactive.")
        group_id = auth_ctx.api_key_group_id if auth_ctx else None
        vendor = _seedance_asset_vendor(provider)
        if vendor == "aliyun":
            return [_aliyun_credentials_from_provider(provider)]
        if vendor == "volcengine":
            return [_volcengine_credentials_from_provider(provider)]
        raise RuntimeError(
            f"Provider {provider_id} has no supported Seedance asset protocol. "
            "Set extra_config.seedance_asset_vendor to volcengine or aliyun."
        )

    group_id = auth_ctx.api_key_group_id if auth_ctx else None
    allowed = auth_ctx.allowed_models if auth_ctx else None
    allowed_set = set(allowed) if allowed else None

    # Include native providers plus compatible providers that explicitly map
    # their asset protocol through extra_config.seedance_asset_vendor.
    providers_result = await session.execute(
        sa_select(Provider).where(
            Provider.group_id == group_id,
            Provider.is_active == True,
        )
    )
    providers = providers_result.scalars().all()
    if not providers:
        raise RuntimeError(
            "No active provider found for this API key group."
        )

    provider_by_id = {
        provider.id: provider for provider in providers
        if _seedance_asset_vendor(provider) is not None
    }
    if not provider_by_id:
        raise RuntimeError(
            "No active provider has a supported Seedance asset protocol."
        )

    # Gather every provider exposing Seedance 2.x+ (Volcengine) or a known
    # yike video model (Aliyun) through either its real model name or its
    # configured API alias.
    models_result = await session.execute(
        sa_select(Model).where(
            Model.provider_id.in_(list(provider_by_id.keys())),
            Model.is_active == True,
        )
    )
    candidates = [
        m for m in models_result.scalars().all()
        if not m.is_retired and _is_video_ref_eligible_model(
            m, _seedance_asset_vendor(provider_by_id[m.provider_id])
        )
    ]
    if allowed_set is not None:
        candidates = [
            m for m in candidates
            if (m.name or "") in allowed_set or (m.alias or "") in allowed_set
        ]

    if not candidates:
        raise RuntimeError(
            "No active video-generation model (seedance / wonder) found for this "
            "group or API key. Configure a Volcengine seedance or Aliyun yike model first."
        )

    target_ids = sorted({m.provider_id for m in candidates})
    credentials = []
    for target_id in target_ids:
        provider = provider_by_id[target_id]
        if _seedance_asset_vendor(provider) == "aliyun":
            credentials.append(_aliyun_credentials_from_provider(provider))
        else:
            credentials.append(_volcengine_credentials_from_provider(provider))
    return credentials


_SEEDANCE_VERSION_RE = re.compile(
    r"seedance(?:[^0-9]|_)*([0-9]+)(?:\.([0-9]+))?",
    re.IGNORECASE,
)


def _is_seedance_2_or_newer_name(value: Optional[str]) -> bool:
    """Return whether a model name/alias identifies Seedance major version 2+."""
    match = _SEEDANCE_VERSION_RE.search(value or "")
    return bool(match and int(match.group(1)) >= 2)


def _is_seedance_2_or_newer_model(model) -> bool:
    return (
        _is_seedance_2_or_newer_name(getattr(model, "name", None))
        or _is_seedance_2_or_newer_name(getattr(model, "alias", None))
    )


def _is_video_ref_eligible_model(model, vendor: Optional[str]) -> bool:
    """Whether ``model`` qualifies its provider for the seedance-ref upload fan-out.

    Volcengine models are matched by the ``seedance`` name/alias pattern.
    Aliyun yike models use their own naming (wonder-pro, wan2.7, ...), which
    never matches that pattern, so they're checked against the real yike
    model list instead. An explicit ``seedance``-style alias still works as
    an override for either vendor.
    """
    if vendor == "aliyun":
        return (
            is_aliyun_video_model(getattr(model, "name", None) or "")
            or is_aliyun_video_model(getattr(model, "alias", None) or "")
            or _is_seedance_2_or_newer_model(model)
        )
    return _is_seedance_2_or_newer_model(model)

async def _get_aliyun_credentials(session, group_id: int, provider_id: Optional[int] = None):
    """
    Look up the Aliyun provider belonging to the API key's group.

    Returns a dict with:
        vendor:             "aliyun"
        access_key_id:      Alibaba Cloud AccessKey ID
        access_key_secret:  Alibaba Cloud AccessKey Secret
        region:             Region (default cn-shanghai)
        endpoint:           Custom endpoint override (optional)
        api_version:        yike API version override (optional)
        provider_id:        Provider.id holding the account
    """
    from sqlalchemy import select as sa_select
    from app.models import Provider

    query = sa_select(Provider).where(
        Provider.type == "aliyun",
        Provider.group_id == group_id,
        Provider.is_active == True,
    )
    if provider_id:
        query = query.where(Provider.id == provider_id)

    result = await session.execute(query)
    provider = result.scalars().first()

    if not provider:
        raise RuntimeError(
            "No active Aliyun provider found. "
            "Please configure an Aliyun provider first."
        )

    extra = provider.extra_config or {}
    creds = {
        "vendor": "aliyun",
        "access_key_id": str(extra.get("access_key_id") or "").strip(),
        "access_key_secret": str(extra.get("access_key_secret") or "").strip(),
        "region": str(extra.get("region") or "cn-shanghai").strip(),
        "endpoint": str(extra.get("endpoint") or "").strip() or None,
        "api_version": str(extra.get("api_version") or "").strip() or None,
        "provider_id": provider.id,
        "provider_name": provider.name,
    }

    # 兼容 "AK:SK" 格式的 api_key
    if (not creds["access_key_id"] or not creds["access_key_secret"]) and provider.api_key:
        api_key = (provider.api_key or "").strip()
        if ":" in api_key:
            parts = api_key.split(":", 1)
            if not creds["access_key_id"]:
                creds["access_key_id"] = parts[0].strip()
            if not creds["access_key_secret"]:
                creds["access_key_secret"] = parts[1].strip()

    if not creds["access_key_id"] or not creds["access_key_secret"]:
        raise RuntimeError(
            "Aliyun provider is missing credentials. "
            "Set extra_config.access_key_id + access_key_secret, "
            "or api_key in 'AccessKeyId:AccessKeySecret' format."
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


_SUPPORTED_PURPOSES = frozenset({"seedance-ref"})


def _validate_purpose(purpose: str, auth_ctx):
    """Return an error response if ``purpose`` is unsupported, else None."""
    if purpose not in _SUPPORTED_PURPOSES:
        _log_error("files_upload", 400, f"Unsupported purpose: {purpose}", _build_error_context(auth_ctx))
        return _error_response(
            f"Unsupported purpose '{purpose}'. Supported: {', '.join(sorted(_SUPPORTED_PURPOSES))}.",
            code="invalid_request", param="purpose", status_code=400)
    return None


def _mime_to_media_type(content_type: str) -> str:
    """Map a MIME type to a yike MediaType (image / video / audio)."""
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "audio"
    return ""


_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus")
_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".ts")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic", ".avif")


def _infer_media_type_from_url(url: str) -> str:
    """Infer the yike MediaType (image / video / audio) from a URL extension."""
    path = (url or "").split("?", 1)[0].split("#", 1)[0].lower()
    if path.endswith(_AUDIO_EXTS):
        return "audio"
    if path.endswith(_VIDEO_EXTS):
        return "video"
    if path.endswith(_IMAGE_EXTS):
        return "image"
    return ""


def _parse_register_config(value) -> Optional[str]:
    """
    Normalize RegisterConfig for ImportMedia.

    Accepts a dict (serialized to JSON), a JSON string, or ``None``. The
    ``NeedThirdPartyAsset`` flag may also be provided as a JSON string.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    if not text:
        return None
    return text


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
    file_type: str = "volcengine",
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
        type=file_type,
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


async def _handle_multipart_upload(auth_ctx, creds_list):
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

    file_data = file_obj.read()
    filename = file_obj.filename or "upload"
    mime_type = file_obj.content_type or "application/octet-stream"
    media_type = (form.get("media_type") or _mime_to_media_type(mime_type) or "").strip().lower()
    if any(creds.get("vendor") == "aliyun" for creds in creds_list):
        if media_type not in ("image", "video", "audio"):
            return _error_response(
                f"Unsupported media_type '{media_type}'. Use image / video / audio.",
                code="invalid_request", param="media_type", status_code=400,
            )
    register_config = form.get("register_config") or None
    if register_config is None and form.get("need_third_party_asset", "").lower() in ("1", "true", "yes"):
        register_config = json.dumps({"NeedThirdPartyAsset": True})
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

    file_id = _gen_file_id()
    project_name = await _resolve_project_name(auth_ctx)

    async def _upload_one(creds):
        if creds.get("vendor") == "aliyun":
            result = await _aliyun_import(
                creds, public_url, media_type, register_config
            )
            media_id = result.get("MediaId", "")
            if not media_id:
                raise RuntimeError("ImportMedia returned no MediaId")
            return creds, media_id, "aliyun"

        group_id = form.get("group_id") or creds.get("ark_group_id", "")
        if not group_id:
            raise RuntimeError(
                f"Provider {creds.get('provider_id')} is missing ark_group_id"
            )
        ark = _ark_credentials(creds)
        result = await upload_and_create_asset(
            group_id=group_id, image_url=public_url,
            name=filename.rsplit(".", 1)[0], project_name=project_name, **ark,
        )
        asset_id = result.get("Result", {}).get("Id", "")
        if not asset_id:
            raise RuntimeError("CreateAsset returned no asset ID")
        try:
            await poll_asset_status(
                asset_ids=[asset_id], project_name=project_name, **ark
            )
        except Exception:
            try:
                await delete_asset(
                    asset_id=asset_id, project_name=project_name, **ark
                )
            except Exception as cleanup_err:
                logger.warning("files: failed to clean up asset %s: %s", asset_id, cleanup_err)
            raise
        return creds, asset_id, "volcengine"

    outcomes = await asyncio.gather(
        *(_upload_one(creds) for creds in creds_list), return_exceptions=True
    )
    successes = [item for item in outcomes if not isinstance(item, Exception)]
    errors = [str(item) for item in outcomes if isinstance(item, Exception)]
    if not successes:
        message = errors[0] if errors else "No eligible upload provider"
        return _error_response(message, code="upstream_error", status_code=502)

    for creds, object_key, file_type in successes:
        await _persist_upload_record(_build_uploaded_file_record(
            file_id, object_key, purpose, auth_ctx, form.get("user"), storage_key,
            creds.get("provider_id"), file_type=file_type,
        ))

    return jsonify({
        "id": file_id,
        "object": "file",
        "bytes": len(file_data),
        "created_at": int(time.time()),
        "filename": filename,
        "purpose": purpose,
        "provider_count": len(successes),
        "failed_provider_count": len(errors),
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


def _json_media_type(data: dict, media_url: str, explicit_type: str = "") -> str:
    """Resolve Aliyun media type while preserving input_* field semantics."""
    for key, media_type in (
        ("input_image", "image"),
        ("input_audio", "audio"),
        ("input_video", "video"),
    ):
        value = data.get(key)
        values = value if isinstance(value, list) else [value]
        if media_url in values:
            return media_type
    return explicit_type or _infer_media_type_from_url(media_url) or "image"


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


async def _handle_json_upload(auth_ctx, creds_list):
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

    filename = data.get("filename")
    explicit_type = str(data.get("media_type") or "").strip().lower()
    if explicit_type and explicit_type not in ("image", "video", "audio"):
        return _error_response(
            f"Unsupported media_type '{explicit_type}'. Use image / video / audio.",
            code="invalid_request", param="media_type", status_code=400,
        )
    register_config = _parse_register_config(
        data.get("register_config") or data.get("RegisterConfig")
    )
    if register_config is None and data.get("need_third_party_asset", False):
        register_config = json.dumps({"NeedThirdPartyAsset": True})
    logger.info("files: JSON mode keys=%s urls=%d purpose=%s providers=%d",
                ",".join(media_keys), len(media_urls), purpose, len(creds_list))

    project_name = await _resolve_project_name(auth_ctx)
    # One logical file_id per input URL, replicated to every provider.
    logical_inputs = [(_gen_file_id(), url) for url in media_urls]
    results, errors = [], []
    multiple = len(media_urls) > 1
    async def _upload_one(file_id, idx, media_url, creds):
        if creds.get("vendor") == "aliyun":
            media_type = _json_media_type(data, media_url, explicit_type)
            result = await _aliyun_import(
                creds, media_url, media_type, register_config
            )
            media_id = result.get("MediaId", "")
            if not media_id:
                raise RuntimeError("ImportMedia returned no MediaId")
            return file_id, media_url, creds, media_id, "aliyun"

        group_id = data.get("group_id") or creds.get("ark_group_id", "")
        if not group_id:
            raise RuntimeError(f"Provider {creds.get('provider_id')} is missing ark_group_id")
        ark = _ark_credentials(creds)
        result = await upload_and_create_asset(
            group_id=group_id, image_url=media_url,
            name=_asset_name(filename, media_url, idx, multiple),
            project_name=project_name, **ark,
        )
        asset_id = result.get("Result", {}).get("Id", "")
        if not asset_id:
            raise RuntimeError("CreateAsset returned no asset ID")
        await poll_asset_status(asset_ids=[asset_id], project_name=project_name, **ark)
        return file_id, media_url, creds, asset_id, "volcengine"

    pending = [
        _upload_one(file_id, idx, media_url, creds)
        for idx, (file_id, media_url) in enumerate(logical_inputs)
        for creds in creds_list
    ]
    outcomes = await asyncio.gather(*pending, return_exceptions=True)
    for item in outcomes:
        if isinstance(item, Exception):
            errors.append({"error": str(item)})
        else:
            results.append(item)

    if not results and errors:
        _log_error("files_upload", 502, f"All assets failed: {errors[0]['error']}", _build_error_context(auth_ctx))
        return _error_response(f"Failed to create assets: {errors[0]['error']}", code="upstream_error", status_code=502)

    # Persist rows and build the response.
    uploaded_files = []
    client_user_id = data.get("user")
    success_ids = set()
    for file_id, media_url, creds, object_key, file_type in results:
        await _persist_upload_record(_build_uploaded_file_record(
            file_id, object_key, purpose, auth_ctx, client_user_id, media_url,
            creds.get("provider_id"), file_type=file_type,
        ))
        success_ids.add(file_id)

    for file_id, _media_url in logical_inputs:
        if file_id not in success_ids:
            continue
        uploaded_files.append({
            "id": file_id,
            "object": "file",
            "bytes": 0,
            "created_at": int(time.time()),
        })

    successful_provider_ids = {
        creds.get("provider_id") for _, _, creds, _, _ in results
    }
    response = {
        "object": "list",
        "data": uploaded_files,
        "purpose": purpose,
        "provider_count": len(successful_provider_ids),
        "failed_provider_count": len(errors),
    }
    if errors:
        response["errors"] = errors
    return jsonify(response)


async def _aliyun_import(
    creds: dict, input_url: str, media_type: str, register_config: Optional[str],
) -> Dict[str, Any]:
    """Call yike ImportMedia and return the parsed response dict."""
    from app.http_client import get_shared_client

    client = await get_shared_client()
    return await aliyun_import_media(
        client,
        access_key_id=creds["access_key_id"],
        access_key_secret=creds["access_key_secret"],
        input_url=input_url,
        media_type=media_type,
        register_config=register_config,
        region=creds.get("region"),
        endpoint=creds.get("endpoint"),
        version=creds.get("api_version"),
    )


async def _handle_multipart_upload_aliyun(auth_ctx, creds):
    """Handle a multipart/form-data upload via Aliyun yike ImportMedia."""
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

    file_data = file_obj.read()
    filename = file_obj.filename or "upload"
    mime_type = file_obj.content_type or "application/octet-stream"

    media_type = (form.get("media_type") or _mime_to_media_type(mime_type) or "").strip().lower()
    if media_type not in ("image", "video", "audio"):
        _log_error("files_upload", 400,
                   f"Unsupported media_type: {media_type!r}. Use image / video / audio or a recognizable MIME type.",
                   _build_error_context(auth_ctx))
        return _error_response(
            f"Unsupported media_type '{media_type}'. Use image / video / audio.",
            code="invalid_request", param="media_type", status_code=400)

    register_config = form.get("register_config") or None
    if register_config is None and form.get("need_third_party_asset", "").lower() in ("1", "true", "yes"):
        register_config = json.dumps({"NeedThirdPartyAsset": True})

    # Save to storage and get a public URL for ImportMedia.
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

    try:
        result = await _aliyun_import(creds, public_url, media_type, register_config)
    except RuntimeError as e:
        _log_error("files_upload", 502, str(e), _build_error_context(auth_ctx))
        return _error_response(str(e), code="upstream_error", status_code=502)

    media_id = result.get("MediaId", "")
    if not media_id:
        _log_error("files_upload", 502, "ImportMedia returned no MediaId", _build_error_context(auth_ctx))
        return _error_response("ImportMedia returned no MediaId.", code="upstream_error", status_code=502)

    file_id = _gen_file_id()
    await _persist_upload_record(_build_uploaded_file_record(
        file_id, media_id, purpose, auth_ctx, form.get("user"), storage_key,
        creds.get("provider_id"), file_type="aliyun",
    ))

    return jsonify({
        "id": file_id,
        "object": "file",
        "bytes": len(file_data),
        "created_at": int(time.time()),
        "filename": filename,
        "purpose": purpose,
        "media_id": media_id,
    })


async def _handle_json_upload_aliyun(auth_ctx, creds):
    """Handle an application/json upload via Aliyun yike ImportMedia.

    Accepts ``input_image`` / ``input_audio`` / ``input_video`` /
    ``input_file`` URL strings (or arrays), plus optional ``media_type``,
    ``register_config`` and ``need_third_party_asset``. For
    ``input_file`` / ``input_url`` the media type is inferred from the URL
    extension (image / video / audio), falling back to the explicit
    ``media_type`` (default image).
    """
    data = await _parse_json_body()
    if not data:
        _log_error("files_upload", 400, "Invalid or empty JSON request body")
        return _error_response("Invalid or empty JSON request body", code="invalid_request", status_code=400)

    explicit_type = (str(data.get("media_type") or "").strip().lower())
    if explicit_type and explicit_type not in ("image", "video", "audio"):
        _log_error("files_upload", 400, f"Unsupported media_type: {explicit_type}",
                   _build_error_context(auth_ctx))
        return _error_response(
            f"Unsupported media_type '{explicit_type}'. Use image / video / audio.",
            code="invalid_request", param="media_type", status_code=400)

    # Collect (url, media_type) entries. input_image / input_audio /
    # input_video imply the media type; input_file / input_url infer it from
    # the URL extension, falling back to the explicit media_type (default image).
    key_type_map = {
        "input_image": "image",
        "input_audio": "audio",
        "input_video": "video",
    }
    media_entries: list = []
    for key in ("input_image", "input_audio", "input_video", "input_file", "input_url", "inputUrl"):
        val = data.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            urls = [val]
        elif isinstance(val, list) and all(isinstance(v, str) for v in val):
            urls = val
        else:
            _log_error("files_upload", 400, f"'{key}' must be a URL string or array of URL strings.",
                       _build_error_context(auth_ctx))
            return _error_response(
                f"'{key}' must be a URL string or array of URL strings.",
                code="invalid_request", param=key, status_code=400)
        base_mtype = key_type_map.get(key, "")
        for url in urls:
            url = (url or "").strip()
            if url:
                mtype = base_mtype or explicit_type or _infer_media_type_from_url(url) or "image"
                media_entries.append((url, mtype))

    if not media_entries:
        _log_error("files_upload", 400,
                   "input_image, input_audio, input_video, input_file, or input_url is required for JSON mode",
                   _build_error_context(auth_ctx))
        return _error_response(
            "input_image, input_audio, input_video, input_file, or input_url is required when using JSON mode.",
            code="invalid_request", param="input_url", status_code=400)

    purpose = data.get("purpose", "seedance-ref")
    err = _validate_purpose(purpose, auth_ctx)
    if err:
        return err

    register_config = _parse_register_config(
        data.get("register_config") or data.get("RegisterConfig")
    )
    if register_config is None and data.get("need_third_party_asset", False):
        register_config = json.dumps({"NeedThirdPartyAsset": True})

    logger.info("files: Aliyun JSON mode urls=%d purpose=%s", len(media_entries), purpose)

    results, errors = [], []
    for media_url, media_type in media_entries:
        try:
            result = await _aliyun_import(creds, media_url, media_type, register_config)
            results.append({"result": result, "url": media_url})
        except RuntimeError as e:
            logger.error("files: Aliyun import failed for url %s: %s", media_url[:80], e)
            errors.append({"url": media_url, "error": str(e)})

    if not results and errors:
        _log_error("files_upload", 502, f"All imports failed: {errors[0]['error']}", _build_error_context(auth_ctx))
        return _error_response(f"Failed to import media: {errors[0]['error']}", code="upstream_error", status_code=502)

    uploaded_files = []
    client_user_id = data.get("user")
    provider_id = creds.get("provider_id")
    for item in results:
        media_id = item["result"].get("MediaId", "")
        file_id = _gen_file_id()
        await _persist_upload_record(_build_uploaded_file_record(
            file_id, media_id, purpose, auth_ctx, client_user_id,
            item.get("url"), provider_id, file_type="aliyun",
        ))
        uploaded_files.append({
            "id": file_id,
            "object": "file",
            "bytes": 0,
            "created_at": int(time.time()),
            "media_id": media_id,
        })

    response = {"object": "list", "data": uploaded_files, "purpose": purpose}
    if errors:
        response["errors"] = errors
    return jsonify(response)


# =============================================================================
# POST /v1/files — Upload files to Volcengine / Aliyun asset library
# =============================================================================

@files_bp.route('/v1/files', methods=['POST', 'HEAD', 'OPTIONS'])
async def upload_file():
    """
    OpenAI-compatible file upload endpoint.

    Supports two modes:

    1. multipart/form-data (standard OpenAI format):
       - ``purpose``: "seedance-ref" — the video-generation reference purpose;
         the target provider (Volcengine ARK / Aliyun yike) is chosen from the
         API key's video models.
       - ``file``:    Binary file data
       - ``group_id``: (optional) Volcengine ARK AssetGroup ID
       - Aliyun mode: ``media_type`` (image/video/audio), ``register_config``
         or ``need_third_party_asset=true`` (Wonder 模型需注册第三方素材)

    2. application/json (extended format):
       - ``input_image`` / ``input_audio`` / ``input_video`` / ``input_file``: URL string or array of URL strings (at least one must be provided); ``input_file`` / ``input_url`` 的 media_type 按 URL 扩展名推断 (image/video/audio)
       - ``input_url``: (Aliyun) single URL shorthand
       - ``purpose``:     "seedance-ref"
       - ``group_id``:    Volcengine ARK AssetGroup ID (required or from provider config)
       - ``filename``:    (optional) Asset name
       - ``media_type`` / ``register_config`` / ``need_third_party_asset``: (Aliyun) ImportMedia options
    """
    if request.method == 'HEAD' or request.method == 'OPTIONS':
        return '', 200

    # ── Phase 1: Auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("files_upload", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    # ── Phase 1b: read purpose (single canonical value: seedance-ref) ──
    content_type = request.content_type or ""
    if "multipart/form-data" in content_type:
        form = await request.form
        purpose = form.get("purpose", "seedance-ref")
    elif "application/json" in content_type:
        body = await _parse_json_body()
        purpose = (body or {}).get("purpose", "seedance-ref")
    else:
        purpose = "seedance-ref"

    if purpose not in _SUPPORTED_PURPOSES:
        _log_error("files_upload", 400, f"Unsupported purpose: {purpose}", _build_error_context(auth_ctx))
        return _error_response(
            f"Unsupported purpose '{purpose}'. Supported: {', '.join(sorted(_SUPPORTED_PURPOSES))}.",
            code="invalid_request", param="purpose", status_code=400)

    # ── Phase 2: Resolve all Seedance 2.x+ providers visible to the API key ──
    # Each successful provider gets one UploadedFile row under the same
    # logical file_id, allowing generation to retain normal provider routing.
    provider_id = auth_ctx.provider_id_override if auth_ctx else None
    try:
        async with get_db_session() as session:
            creds_list = await _resolve_video_ref_credentials(session, auth_ctx, provider_id)
    except RuntimeError as e:
        _log_error("files_upload", 500, str(e), _build_error_context(auth_ctx))
        return _error_response(str(e), code="provider_error", status_code=500)

    # ── Phase 3: Upload to every eligible Seedance provider ──
    if "multipart/form-data" in content_type:
        return await _handle_multipart_upload(auth_ctx, creds_list)
    if "application/json" in content_type:
        return await _handle_json_upload(auth_ctx, creds_list)
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
    Deletes the upstream asset too: Volcengine ARK DeleteAsset (volcengine
    rows) or Aliyun yike DeleteMedias (aliyun rows), keyed on the recorded
    file ``type``. Then deletes the local database record.

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
        records = result.scalars().all()

        if not records:
            _log_error("files_delete", 404, f"File not found: {file_id}", _build_error_context(auth_ctx))
            return _error_response(f"File not found: {file_id}", code="not_found", param="file_id", status_code=404)

        has_volcengine = any(record.type == "volcengine" for record in records)
        project_name = "default"
        if has_volcengine and auth_ctx and auth_ctx.api_key_group_id:
            project_name = await _get_group_project_name(
                session, auth_ctx.api_key_group_id
            )
        for record in records:
            object_key = record.object_key
            asset_provider_id = record.provider_id or (
                auth_ctx.provider_id_override if auth_ctx else None
            )
            if (record.purpose == "seedance-ref"
                    and record.type == "volcengine"
                    and object_key.lower().startswith("asset-")):
                try:
                    creds = await _get_volcengine_credentials(
                        session, auth_ctx.api_key_group_id, asset_provider_id
                    )
                    await delete_asset(
                        asset_id=object_key, project_name=project_name,
                        **_ark_credentials(creds),
                    )
                except RuntimeError as e:
                    return _error_response(
                        f"Failed to delete upstream asset: {e}",
                        code="upstream_error", status_code=502,
                    )
            elif record.type == "aliyun" and object_key:
                try:
                    creds = await _get_aliyun_credentials(
                        session, auth_ctx.api_key_group_id, asset_provider_id
                    )
                    from app.http_client import get_shared_client
                    client = await get_shared_client()
                    await aliyun_delete_medias(
                        client, access_key_id=creds["access_key_id"],
                        access_key_secret=creds["access_key_secret"],
                        media_ids=[object_key], delete_physical_files=True,
                        region=creds.get("region"), endpoint=creds.get("endpoint"),
                        version=creds.get("api_version"),
                    )
                except RuntimeError as e:
                    return _error_response(
                        f"Failed to delete upstream media: {e}",
                        code="upstream_error", status_code=502,
                    )

        storage_key = records[0].storage_key
        if storage_key and not storage_key.startswith(("http://", "https://")):
            try:
                from app.storage.factory import get_storage_backend
                get_storage_backend().delete_binary(storage_key)
            except Exception as e:
                logger.warning("files: failed to delete storage copy %s: %s", storage_key, e)

        for record in records:
            await session.delete(record)
        await session.commit()

    return jsonify({
        "id": file_id,
        "object": "file",
        "deleted": True,
    })

# =============================================================================
# GET /v1/files/<file_id> — Get an uploaded file
# =============================================================================

def _derive_filename(record) -> Optional[str]:
    """Best-effort filename from the storage key (upload path or original URL)."""
    storage_key = record.storage_key
    if not storage_key:
        return None
    if storage_key.startswith(("http://", "https://")):
        path = storage_key.split("?", 1)[0].rstrip("/")
        name = path.rsplit("/", 1)[-1]
        return name or None
    name = storage_key.rsplit("/", 1)[-1]
    return name or None


def _all_scalar_rows(result) -> list:
    """Return all ORM rows, tolerating lightweight test result doubles."""
    scalars = result.scalars()
    if hasattr(scalars, "all"):
        return scalars.all()
    first = scalars.first()
    return [first] if first is not None else []


@files_bp.route('/v1/files/<file_id>', methods=['GET'])
async def get_file(file_id: str):
    """OpenAI-compatible file retrieval endpoint.

    Returns the OpenAI file object plus a ``status`` field reflecting the
    live upstream asset state:
      - Aliyun yike: GetMedia → MediaBasicInfo.Status
      - Volcengine ARK: GetAsset → Result.Status

    Example::

        {
          "id": "file-abc123",
          "object": "file",
          "bytes": 0,
          "created_at": 1677610602,
          "filename": "mydata.png",
          "purpose": "seedance-ref",
          "status": "Normal"
        }
    """
    # ── Phase 1: Auth ──
    auth_ctx, error, status = await get_current_user_or_api_key()
    if error:
        _log_error("files_get", status, error.get('detail', 'Not authenticated'))
        return _error_response(error.get('detail', 'Not authenticated'), code="unauthorized", status_code=status)

    # ── Phase 2: Look up file record ──
    from sqlalchemy import select as sa_select

    async with get_db_session() as session:
        result = await session.execute(
            sa_select(UploadedFile).where(UploadedFile.file_id == file_id)
        )
        records = _all_scalar_rows(result)

        if not records:
            _log_error("files_get", 404, f"File not found: {file_id}", _build_error_context(auth_ctx))
            return _error_response(f"File not found: {file_id}", code="not_found", param="file_id", status_code=404)

        has_volcengine = any(record.type == "volcengine" for record in records)
        project_name = "default"
        if has_volcengine and auth_ctx and auth_ctx.api_key_group_id:
            project_name = await _get_group_project_name(
                session, auth_ctx.api_key_group_id
            )
        provider_statuses = []
        media_basic = {}
        for record in records:
            asset_provider_id = record.provider_id or (
                auth_ctx.provider_id_override if auth_ctx else None
            )
            upstream_status = ""
            try:
                if record.type == "aliyun" and record.object_key:
                    creds = await _get_aliyun_credentials(
                        session, auth_ctx.api_key_group_id, asset_provider_id
                    )
                    from app.http_client import get_shared_client
                    client = await get_shared_client()
                    media_info = await aliyun_get_media(
                        client, access_key_id=creds["access_key_id"],
                        access_key_secret=creds["access_key_secret"],
                        media_id=record.object_key, region=creds.get("region"),
                        endpoint=creds.get("endpoint"),
                        version=creds.get("api_version"),
                    )
                    media_basic = ((media_info.get("MediaInfo") or {})
                                   .get("MediaBasicInfo") or {})
                    upstream_status = media_basic.get("Status") or ""
                elif (record.type == "volcengine"
                      and record.object_key.lower().startswith("asset-")):
                    creds = await _get_volcengine_credentials(
                        session, auth_ctx.api_key_group_id, asset_provider_id
                    )
                    asset_info = await get_asset(
                        asset_id=record.object_key, project_name=project_name,
                        **_ark_credentials(creds),
                    )
                    upstream_status = ((asset_info.get("Result") or {})
                                       .get("Status") or "")
                provider_statuses.append({
                    "provider_id": asset_provider_id,
                    "type": record.type,
                    "status": upstream_status,
                })
            except RuntimeError as e:
                provider_statuses.append({
                    "provider_id": asset_provider_id,
                    "type": record.type,
                    "status": "failed",
                    "error": str(e),
                })

        record = records[0]
        statuses = [item["status"] for item in provider_statuses]
        healthy = {"active", "normal", "success", "completed"}
        aggregate_status = (
            statuses[0] if len(statuses) == 1 else
            "active" if statuses and all(s.lower() in healthy for s in statuses) else
            "partial"
        )
        created_at = int(record.created_at.timestamp()) if record.created_at else 0
        response = {
            "id": file_id,
            "object": "file",
            "bytes": 0,
            "created_at": created_at,
            "filename": _derive_filename(record),
            "purpose": record.purpose,
            "status": aggregate_status,
            "providers": provider_statuses,
        }
        if record.type == "aliyun" and media_basic:
            if media_basic.get("MediaType"):
                response["media_type"] = media_basic["MediaType"]
            if media_basic.get("InputURL"):
                response["input_url"] = media_basic["InputURL"]
        return jsonify(response)


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
