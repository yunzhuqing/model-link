"""
BackgroundResponse 数据库操作模块 — 全异步实现。

所有 DB 操作均通过项目共享的 async 引擎 (``get_db_session``) 执行,
复用连接池,不阻塞事件循环。

典型使用场景:
  1. 创建 in_progress 记录 (请求收到时)
  2. 更新 completed / failed 状态 (任务结束时)
  3. 查询记录状态 (GET 轮询时)
  4. resync 守护任务批量扫描 stale 记录
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import text as _sa_text

logger = logging.getLogger(__name__)


async def _async_execute_with_retry(sql, params: dict, retries: int = 3) -> None:
    """Async write helper. Failures are retried up to ``retries`` times."""
    from app import get_db_session

    for attempt in range(retries):
        try:
            async with get_db_session() as session:
                await session.execute(sql, params)
                await session.commit()
            return
        except Exception as exc:
            logger.warning(
                f"[background_response_dao] async DB write attempt {attempt + 1}/{retries} failed: {exc}"
            )
            if attempt == retries - 1:
                logger.exception(
                    f"[background_response_dao] All {retries} async DB write attempts failed"
                )
                return
            await asyncio.sleep(0.1 * (attempt + 1))


async def create_record_async(
    response_id: str,
    apikey: Optional[str],
    model: str,
    input_key: str,
    output_key: str,
    status: str = "in_progress",
    task_id: Optional[str] = None,
    provider_id: Optional[int] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """插入一条新的 BackgroundResponse 记录。"""
    sql = _sa_text(
        "INSERT INTO ml_background_responses "
        "(response_id, apikey, model, status, input_key, output_key, "
        "task_id, provider_id, session_id, request_id, created_at) "
        "VALUES (:response_id, :apikey, :model, :status, :input_key, :output_key, "
        ":task_id, :provider_id, :session_id, :request_id, :created_at)"
    )
    await _async_execute_with_retry(sql, {
        "response_id": response_id,
        "apikey": apikey,
        "model": model,
        "status": status,
        "input_key": input_key,
        "output_key": output_key,
        "task_id": task_id,
        "provider_id": provider_id,
        "session_id": session_id,
        "request_id": request_id,
        "created_at": datetime.utcnow(),
    })


async def mark_completed_async(response_id: str) -> None:
    """将记录标记为 completed (仅当前状态仍为 in_progress)。"""
    sql = _sa_text(
        "UPDATE ml_background_responses "
        "SET status='completed', completed_at=:completed_at "
        "WHERE response_id=:response_id AND status = 'in_progress'"
    )
    await _async_execute_with_retry(sql, {
        "completed_at": datetime.utcnow(),
        "response_id": response_id,
    })


async def mark_failed_async(response_id: str, error: str) -> None:
    """将记录标记为 failed 并记录错误信息 (仅当前状态仍为 in_progress)。"""
    sql = _sa_text(
        "UPDATE ml_background_responses "
        "SET status='failed', completed_at=:completed_at, error=:error "
        "WHERE response_id=:response_id AND status = 'in_progress'"
    )
    await _async_execute_with_retry(sql, {
        "completed_at": datetime.utcnow(),
        "response_id": response_id,
        "error": (error or "")[:4096],
    })


async def get_record_async(response_id: str) -> Optional[Dict[str, Any]]:
    """查询记录。未找到时返回 None。"""
    from app import get_db_session

    sql = _sa_text(
        "SELECT response_id, apikey, model, status, input_key, output_key, "
        "error, task_id, provider_id, session_id, request_id, created_at, completed_at "
        "FROM ml_background_responses "
        "WHERE response_id=:response_id"
    )
    try:
        async with get_db_session() as session:
            row = (await session.execute(sql, {"response_id": response_id})).mappings().first()
            return dict(row) if row else None
    except Exception as exc:
        logger.warning(f"[background_response_dao] async get_record failed: {exc}")
        return None


async def update_task_metadata_async(
    response_id: str,
    task_id: Optional[str] = None,
    provider_id: Optional[int] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """更新供应商任务元数据 (COALESCE,只覆盖非空字段)。"""
    sql = _sa_text(
        "UPDATE ml_background_responses "
        "SET task_id = COALESCE(:task_id, task_id), "
        "    provider_id = COALESCE(:provider_id, provider_id), "
        "    session_id = COALESCE(:session_id, session_id), "
        "    request_id = COALESCE(:request_id, request_id) "
        "WHERE response_id = :response_id"
    )
    await _async_execute_with_retry(sql, {
        "response_id": response_id,
        "task_id": task_id,
        "provider_id": provider_id,
        "session_id": session_id,
        "request_id": request_id,
    })


async def find_stale_in_progress_records_async(
    min_age_minutes: int = 10,
    limit: int = 100,
):
    """查询所有超过 min_age_minutes 分钟仍处于 in_progress 状态的记录。"""
    from app import get_db_session

    cutoff = datetime.utcnow() - timedelta(minutes=min_age_minutes)
    sql = _sa_text(
        "SELECT response_id, task_id, model, apikey, status, "
        "provider_id, session_id, request_id, created_at, completed_at, error, "
        "output_key "
        "FROM ml_background_responses "
        "WHERE status = 'in_progress' AND created_at < :cutoff "
        "ORDER BY created_at ASC "
        "LIMIT :limit"
    )
    count_sql = _sa_text(
        "SELECT COUNT(*) AS total, "
        "MIN(created_at) AS oldest, MAX(created_at) AS newest "
        "FROM ml_background_responses WHERE status = 'in_progress'"
    )
    try:
        async with get_db_session() as session:
            rows = (await session.execute(sql, {"cutoff": cutoff, "limit": limit})).mappings().all()
            result = [dict(row) for row in rows]

            # Diagnostic: when no results, show total in_progress state
            if not result:
                diag = (await session.execute(count_sql)).mappings().first()
                if diag:
                    logger.info(
                        f"[background_response_dao] find_stale: 0 rows matched "
                        f"(cutoff < {cutoff.isoformat()}, min_age={min_age_minutes}m). "
                        f"In-progress total: {diag['total']}, "
                        f"oldest_created_at: {diag['oldest']}, "
                        f"newest_created_at: {diag['newest']}"
                    )
            else:
                logger.info(
                    f"[background_response_dao] find_stale: {len(result)} rows matched "
                    f"(cutoff < {cutoff.isoformat()}, min_age={min_age_minutes}m)"
                )
            return result
    except Exception as exc:
        logger.warning(f"[background_response_dao] async find_stale failed: {exc}")
        return []
