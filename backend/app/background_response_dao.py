"""
BackgroundResponse 数据库操作模块

所有 BackgroundResponse 相关的 DB 操作均使用 NullPool 引擎，
每次操作独立建立一个全新的物理连接，用完立即关闭。

这样做的好处：
- LLM 对话、视频生成等长耗时任务无需在整个处理过程中保持 DB 连接
- 彻底消除 "MySQL server has gone away" 问题
- 线程安全：每次调用均使用独立连接，无连接共享

典型使用场景：
  1. 创建 in_progress 记录 (请求收到时)
  2. 更新 completed / failed 状态 (任务结束时)
  3. 查询记录状态 (GET 轮询时)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, text as _sa_text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


# =============================================================================
# 内部辅助：获取一次性引擎
# =============================================================================

def _make_engine(db_url: str):
    """
    创建一个使用 NullPool 的 SQLAlchemy 引擎。

    NullPool 完全禁用连接池，connect() 每次都建立全新的物理 TCP 连接，
    close() / dispose() 后立即关闭，不保留连接供复用。

    Args:
        db_url: SQLAlchemy 数据库 URL

    Returns:
        SQLAlchemy Engine（NullPool）
    """
    return create_engine(db_url, poolclass=NullPool)


def _execute_with_retry(db_url: str, sql, params: dict, retries: int = 3) -> None:
    """
    用 NullPool 引擎执行一条 SQL（写操作），失败时最多重试 ``retries`` 次。

    每次重试都建立全新连接，彻底规避连接断开问题。

    Args:
        db_url: 数据库 URL
        sql:    SQLAlchemy text() SQL 对象
        params: 绑定参数字典
        retries: 最大重试次数（默认 3）

    Raises:
        最后一次重试失败时，记录 exception 日志并静默返回。
    """
    for attempt in range(retries):
        engine = None
        try:
            engine = _make_engine(db_url)
            with engine.connect() as conn:
                conn.execute(sql, params)
                conn.commit()
            return
        except Exception as exc:
            logger.warning(
                f"[background_response_dao] DB write attempt {attempt + 1}/{retries} failed: {exc}"
            )
            if attempt == retries - 1:
                logger.exception(
                    f"[background_response_dao] All {retries} DB write attempts failed"
                )
        finally:
            if engine is not None:
                engine.dispose()


def _query_one(db_url: str, sql, params: dict) -> Optional[Dict[str, Any]]:
    """
    用 NullPool 引擎查询一行记录，返回字典或 None。

    Args:
        db_url: 数据库 URL
        sql:    SQLAlchemy text() SQL 对象
        params: 绑定参数字典

    Returns:
        行字典（列名→值），未找到时返回 None
    """
    engine = None
    try:
        engine = _make_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(sql, params).mappings().first()
            return dict(row) if row else None
    finally:
        if engine is not None:
            engine.dispose()


# =============================================================================
# 公共 API
# =============================================================================

def create_record(
    db_url: str,
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
    """
    插入一条新的 BackgroundResponse 记录。

    Args:
        db_url:      数据库 URL
        response_id: 响应唯一 ID
        apikey:      调用者的 API Key（可为 None）
        model:       模型名称
        input_key:   存储输入 payload 的 key
        output_key:  存储输出结果的 key
        status:      初始状态，默认 "in_progress"
        task_id:     供应商任务 ID（可为 None）
        provider_id: 供应商 ID（可为 None）
        session_id:  会话 ID（可为 None）
        request_id:  请求 ID（可为 None）
    """
    sql = _sa_text(
        "INSERT INTO ml_background_responses "
        "(response_id, apikey, model, status, input_key, output_key, "
        "task_id, provider_id, session_id, request_id, created_at) "
        "VALUES (:response_id, :apikey, :model, :status, :input_key, :output_key, "
        ":task_id, :provider_id, :session_id, :request_id, :created_at)"
    )
    _execute_with_retry(db_url, sql, {
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


def mark_completed(db_url: str, response_id: str) -> None:
    """
    将 BackgroundResponse 记录标记为 completed。

    只在状态仍为 in_progress 时更新，避免覆盖已完成的记录。

    Args:
        db_url:      数据库 URL
        response_id: 响应唯一 ID
    """
    sql = _sa_text(
        "UPDATE ml_background_responses "
        "SET status='completed', completed_at=:completed_at "
        "WHERE response_id=:response_id AND status = 'in_progress'"
    )
    _execute_with_retry(db_url, sql, {
        "completed_at": datetime.utcnow(),
        "response_id": response_id,
    })


def mark_failed(db_url: str, response_id: str, error: str) -> None:
    """
    将 BackgroundResponse 记录标记为 failed 并记录错误信息。

    只在状态仍为 in_progress 时更新，避免覆盖已完成的记录。

    Args:
        db_url:      数据库 URL
        response_id: 响应唯一 ID
        error:       错误描述（自动截断至 4096 字符）
    """
    sql = _sa_text(
        "UPDATE ml_background_responses "
        "SET status='failed', completed_at=:completed_at, error=:error "
        "WHERE response_id=:response_id AND status = 'in_progress'"
    )
    _execute_with_retry(db_url, sql, {
        "completed_at": datetime.utcnow(),
        "response_id": response_id,
        "error": (error or "")[:4096],
    })


def get_record(db_url: str, response_id: str) -> Optional[Dict[str, Any]]:
    """
    查询 BackgroundResponse 记录。

    Args:
        db_url:      数据库 URL
        response_id: 响应唯一 ID

    Returns:
        包含所有字段的字典，未找到时返回 None
    """
    sql = _sa_text(
        "SELECT response_id, apikey, model, status, input_key, output_key, "
        "error, task_id, provider_id, session_id, request_id, created_at, completed_at "
        "FROM ml_background_responses "
        "WHERE response_id=:response_id"
    )
    return _query_one(db_url, sql, {"response_id": response_id})


def update_task_metadata(
    db_url: str,
    response_id: str,
    task_id: Optional[str] = None,
    provider_id: Optional[int] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """
    更新 BackgroundResponse 记录的供应商任务元数据。

    用于在后台线程获取到 task_id 后立即持久化，即使后续处理崩溃，
    resync 服务也能用 task_id 去供应商查询状态。

    Args:
        db_url:      数据库 URL
        response_id: 响应唯一 ID
        task_id:     供应商任务 ID
        provider_id: 供应商 ID
        session_id:  会话 ID
        request_id:  请求 ID
    """
    sql = _sa_text(
        "UPDATE ml_background_responses "
        "SET task_id = COALESCE(:task_id, task_id), "
        "    provider_id = COALESCE(:provider_id, provider_id), "
        "    session_id = COALESCE(:session_id, session_id), "
        "    request_id = COALESCE(:request_id, request_id) "
        "WHERE response_id = :response_id"
    )
    _execute_with_retry(db_url, sql, {
        "response_id": response_id,
        "task_id": task_id,
        "provider_id": provider_id,
        "session_id": session_id,
        "request_id": request_id,
    })


def find_stale_in_progress_records(
    db_url: str,
    min_age_minutes: int = 10,
    limit: int = 100,
):
    """
    查询所有超过 min_age_minutes 分钟仍处于 in_progress 状态的记录。

    Args:
        db_url:          数据库 URL
        min_age_minutes: 最小超时时间（分钟）
        limit:           最大返回条数

    Returns:
        记录字典列表，按 created_at 升序排列
    """
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(minutes=min_age_minutes)
    sql = _sa_text(
        "SELECT response_id, task_id, model, apikey, status, "
        "provider_id, session_id, request_id, created_at, completed_at, error "
        "FROM ml_background_responses "
        "WHERE status = 'in_progress' AND created_at < :cutoff "
        "ORDER BY created_at ASC "
        "LIMIT :limit"
    )
    engine = None
    try:
        engine = _make_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(sql, {"cutoff": cutoff, "limit": limit}).mappings().all()
            return [dict(row) for row in rows]
    finally:
        if engine is not None:
            engine.dispose()
