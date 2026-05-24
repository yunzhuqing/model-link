"""
Provider task status checker for background response resync.

Routes stale background response records to the appropriate provider's
"check once" function (defined alongside each provider's polling logic).
The HTTP request logic lives in the provider modules — this module is a
thin routing layer.

All public entry points are async. Provider-side SDK calls that are still
sync (Tencent / Volcengine SDKs use the ``requests`` library internally)
are isolated with ``asyncio.to_thread`` so they do not block the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import text as sa_text

logger = logging.getLogger(__name__)


# Shared httpx.AsyncClient for the resync poller. Per-record clients caused a
# fresh TLS handshake + pool per stale record (leader scans hundreds per tick).
_poll_client: Optional[httpx.AsyncClient] = None
_poll_client_lock = asyncio.Lock()


async def _get_poll_client() -> httpx.AsyncClient:
    global _poll_client
    if _poll_client is None:
        async with _poll_client_lock:
            if _poll_client is None:
                from app.http_client import make_async_client
                _poll_client = make_async_client(scope="POLL")
    return _poll_client


class TaskStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


# ── Reusable status helpers ──────────────────────────────────────────────────

def _map_volcengine_status(status: str) -> TaskStatus:
    if status == "succeeded":
        return TaskStatus.COMPLETED
    if status in ("failed", "cancelled"):
        return TaskStatus.FAILED
    return TaskStatus.RUNNING


def _map_bailian_status(task_status: str) -> TaskStatus:
    if task_status == "SUCCEEDED":
        return TaskStatus.COMPLETED
    if task_status in ("FAILED", "CANCELED", "UNKNOWN"):
        return TaskStatus.FAILED
    return TaskStatus.RUNNING


def _map_tencent_status(task_status: str, err_code: int = 0) -> TaskStatus:
    if task_status == "FINISH":
        return TaskStatus.COMPLETED if err_code == 0 else TaskStatus.FAILED
    if task_status in ("FAIL", "ABORTED"):
        return TaskStatus.FAILED
    return TaskStatus.RUNNING


def _map_hunyuan3d_status(status: str, error_code: str = "") -> TaskStatus:
    if status == "DONE":
        return TaskStatus.COMPLETED if not error_code else TaskStatus.FAILED
    if status == "FAIL":
        return TaskStatus.FAILED
    return TaskStatus.RUNNING


# ── Credential lookup (async, shared engine) ─────────────────────────────────

async def _lookup_provider_credentials_async(provider_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Look up provider credentials from ml_providers table via the shared async engine."""
    if not provider_id:
        return None

    from app import get_db_session

    sql = sa_text(
        "SELECT id, type, api_key, base_url, extra_config "
        "FROM ml_providers WHERE id = :pid"
    )
    try:
        async with get_db_session() as session:
            row = (await session.execute(sql, {"pid": provider_id})).mappings().first()
            return dict(row) if row else None
    except Exception as exc:
        logger.error(f"[task_status] Failed to lookup provider {provider_id}: {exc}", exc_info=True)
        return None


# =============================================================================
# Provider routing (driven by ml_providers.type)
# =============================================================================


async def resolve_and_check_task_status_async(
    record: Dict[str, Any],
) -> TaskStatus:
    """
    Given a stale background response record, determine the provider and
    check the upstream task status.

    Uses ``ml_providers.type`` (looked up via provider_id) for routing.
    For "tencent" providers the model prefix distinguishes VOD from Hunyuan3D.

    HTTP calls use ``httpx.AsyncClient``. Provider SDKs that are sync-only
    (Tencent / Volcengine) are isolated with ``asyncio.to_thread`` so the
    event loop is not blocked.

    Args:
        record: Background response record dict with task_id, model, provider_id

    Returns:
        Current TaskStatus (RUNNING, COMPLETED, FAILED, or UNKNOWN)
    """
    task_id = record.get("task_id")
    provider_id = record.get("provider_id")

    if not task_id:
        return TaskStatus.UNKNOWN

    creds = await _lookup_provider_credentials_async(provider_id)
    if not creds:
        return TaskStatus.UNKNOWN

    provider_type = (creds.get("type") or "").lower()
    if not provider_type:
        return TaskStatus.UNKNOWN

    api_key = creds["api_key"]
    base_url = creds.get("base_url") or ""
    extra_config = creds.get("extra_config") or {}
    if isinstance(extra_config, str):
        try:
            extra_config = json.loads(extra_config)
        except json.JSONDecodeError:
            extra_config = {}

    # ── Volcengine — shared ARK API for Seedance / Seed3D / Seedream ─────
    if provider_type == "volcengine":
        try:
            from app.providers.volcengine.video_generation import check_seedance_task_status
            result = await check_seedance_task_status(
                api_key,
                base_url or "https://ark.cn-beijing.volces.com/api/v3",
                task_id,
            )
            return _map_volcengine_status(result["status"])
        except Exception as exc:
            logger.error(f"[task_status] Volcengine check error for {task_id}: {exc}", exc_info=True)
            return TaskStatus.UNKNOWN

    # ── Bailian — Dashscope video generation ────────────────────────────
    elif provider_type == "bailian":
        try:
            from app.providers.bailian.video_generation import _resolve_task_query_url
            domain = extra_config.get("domain")
            if domain:
                task_query_url = f"{domain.rstrip('/')}/api/v1/tasks"
            else:
                task_query_url = _resolve_task_query_url(None)
            url = f"{task_query_url}/{task_id}"
            client = await _get_poll_client()
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            if resp.status_code >= 400:
                return TaskStatus.UNKNOWN
            result = resp.json()
            task_status = result.get("output", {}).get("task_status", "")
            return _map_bailian_status(task_status)
        except Exception as exc:
            logger.error(f"[task_status] Bailian check error for {task_id}: {exc}", exc_info=True)
            return TaskStatus.UNKNOWN

    # ── TencentVOD — shared DescribeTaskDetail API ──────────────────────
    elif provider_type == "tencentvod":
        try:
            from app.providers.tencent.vod.image_generation import check_tencentvod_task_status
            secret_id = (extra_config.get("secret_id") or "").strip()
            secret_key = (extra_config.get("secret_key") or "").strip()
            if not secret_id or not secret_key:
                parts = api_key.split(":", 1)
                if len(parts) != 2:
                    return TaskStatus.UNKNOWN
                secret_id, secret_key = parts[0], parts[1]
            sub_app_id = extra_config.get("sub_app_id") or extra_config.get("app_id")
            try:
                sub_app_id = int(sub_app_id) if sub_app_id else None
            except (ValueError, TypeError):
                sub_app_id = None
            resp = await check_tencentvod_task_status(
                secret_id, secret_key, task_id, sub_app_id=sub_app_id,
            )
            if not resp:
                return TaskStatus.UNKNOWN
            status = resp.get("Status") or ""
            aigc_task = resp.get("AigcVideoTask") or resp.get("AigcImageTask") or {}
            task_status = aigc_task.get("Status", "") if aigc_task else status
            err_code = aigc_task.get("ErrCode", 0) if aigc_task else 0
            return _map_tencent_status(task_status, err_code)
        except Exception as exc:
            logger.error(f"[task_status] TencentVOD check error for {task_id}: {exc}", exc_info=True)
            return TaskStatus.UNKNOWN

    # ── Hunyuan3D — tries both Rapid and Pro actions ────────────────────
    elif provider_type == "hunyuan":
        try:
            from app.providers.tencent.hunyuan.threed_generation import check_any_hunyuan3d_job_status
            secret_id = (extra_config.get("secret_id") or "").strip()
            secret_key = (extra_config.get("secret_key") or "").strip()
            if not secret_id or not secret_key:
                parts = api_key.split(":", 1)
                if len(parts) != 2:
                    return TaskStatus.UNKNOWN
                secret_id, secret_key = parts[0], parts[1]
            region = extra_config.get("region", "ap-guangzhou")
            model = record.get("model", "")
            # check_any_hunyuan3d_job_status is async — must be awaited
            # directly. (It was previously wrapped in asyncio.to_thread,
            # which silently returned an un-awaited coroutine and made
            # every poll fall through to the except branch.)
            resp = await check_any_hunyuan3d_job_status(
                secret_id, secret_key, task_id, model=model, region=region,
            )
            if not resp:
                return TaskStatus.UNKNOWN
            return _map_hunyuan3d_status(resp.get("Status", ""), resp.get("ErrorCode", ""))
        except Exception as exc:
            logger.error(f"[task_status] Hunyuan3D check error for {task_id}: {exc}", exc_info=True)
            return TaskStatus.UNKNOWN

    # ── OpenAI-compatible Responses API upstream ────────────────────────
    elif provider_type == "openai":
        try:
            url = f"{base_url.rstrip('/')}/v1/responses/{task_id}"
            client = await _get_poll_client()
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            if resp.status_code >= 400:
                return TaskStatus.UNKNOWN
            data = resp.json()
            status = data.get("status", "")
            if status == "completed":
                return TaskStatus.COMPLETED
            if status == "failed":
                return TaskStatus.FAILED
            return TaskStatus.RUNNING if status in ("queued", "in_progress") else TaskStatus.UNKNOWN
        except Exception as exc:
            logger.error(f"[task_status] OpenAI Responses check error for {task_id}: {exc}", exc_info=True)
            return TaskStatus.UNKNOWN

    return TaskStatus.UNKNOWN
