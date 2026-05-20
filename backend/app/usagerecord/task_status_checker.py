"""
Provider task status checker for background response resync.

Routes stale background response records to the appropriate provider's
"check once" function (defined alongside each provider's polling logic).
The HTTP request logic lives in the provider modules — this module is a
thin routing layer.
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


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


# ── Credential lookup ────────────────────────────────────────────────────────

def _lookup_provider_credentials(db_url: str, provider_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Look up provider credentials from ml_providers table."""
    if not provider_id:
        return None
    from sqlalchemy import create_engine as _create_engine
    engine = None
    try:
        engine = _create_engine(db_url, poolclass=NullPool)
        sql = sa_text(
            "SELECT id, type, api_key, base_url, extra_config "
            "FROM ml_providers WHERE id = :pid"
        )
        with engine.connect() as conn:
            row = conn.execute(sql, {"pid": provider_id}).mappings().first()
            return dict(row) if row else None
    except Exception as exc:
        logger.error(f"[task_status] Failed to lookup provider {provider_id}: {exc}", exc_info=True)
        return None
    finally:
        if engine is not None:
            engine.dispose()


# =============================================================================
# Provider routing (driven by ml_providers.type)
# =============================================================================


def resolve_and_check_task_status(
    db_url: str,
    record: Dict[str, Any],
) -> TaskStatus:
    """
    Given a stale background response record, determine the provider and
    check the upstream task status.

    Uses ``ml_providers.type`` (looked up via provider_id) for routing.
    For "tencent" providers the model prefix distinguishes VOD from Hunyuan3D.

    Args:
        db_url: Database connection URL
        record: Background response record dict with task_id, model, provider_id

    Returns:
        Current TaskStatus (RUNNING, COMPLETED, FAILED, or UNKNOWN)
    """
    task_id = record.get("task_id")
    provider_id = record.get("provider_id")

    if not task_id:
        return TaskStatus.UNKNOWN

    creds = _lookup_provider_credentials(db_url, provider_id)
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
            result = check_seedance_task_status(api_key, base_url or "https://ark.cn-beijing.volces.com/api/v3", task_id)
            return _map_volcengine_status(result["status"])
        except Exception as exc:
            logger.error(f"[task_status] Volcengine check error for {task_id}: {exc}", exc_info=True)
            return TaskStatus.UNKNOWN

    # ── Bailian — Dashscope video generation ────────────────────────────
    elif provider_type == "bailian":
        try:
            from app.providers.bailian.video_generation import check_happyhorse_task_status
            domain = extra_config.get("domain")
            result = check_happyhorse_task_status(api_key, task_id, domain=domain)
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
            resp = check_tencentvod_task_status(secret_id, secret_key, task_id, sub_app_id=sub_app_id)
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
            resp = check_any_hunyuan3d_job_status(secret_id, secret_key, task_id, model=model, region=region)
            if not resp:
                return TaskStatus.UNKNOWN
            return _map_hunyuan3d_status(resp.get("Status", ""), resp.get("ErrorCode", ""))
        except Exception as exc:
            logger.error(f"[task_status] Hunyuan3D check error for {task_id}: {exc}", exc_info=True)
            return TaskStatus.UNKNOWN

    # ── OpenAI-compatible Responses API upstream ────────────────────────
    elif provider_type == "openai":
        try:
            import httpx as _httpx
            url = f"{base_url.rstrip('/')}/v1/responses/{task_id}"
            with _httpx.Client(timeout=30) as client:
                resp = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
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