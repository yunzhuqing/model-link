"""ThinkingRecord 数据库操作模块 — 全异步实现。

用于持久化 reasoning_content（如 DeepSeek R1 的思考过程），并在后续
tool_result 续接时根据 tool_call_id 回填。

存储/查询失败均吞掉异常并打点日志,不阻塞主流程（思考内容缺失只会
影响推理质量,而不应让请求整体失败）。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def save_thinking(
    thinking_id: str,
    thinking_content: Optional[str],
    thinking_signature: Optional[str] = None,
) -> None:
    """Upsert a thinking record keyed by thinking_id (= tool_call_id)."""
    if not thinking_id or not thinking_content:
        return
    try:
        from app import get_db_session
        from app.models import ThinkingRecord

        async with get_db_session() as session:
            existing = await session.execute(
                select(ThinkingRecord).where(ThinkingRecord.thinking_id == thinking_id)
            )
            row = existing.scalars().first()
            if row is None:
                session.add(ThinkingRecord(
                    thinking_id=thinking_id,
                    thinking_signature=thinking_signature,
                    thinking_content=thinking_content,
                ))
            else:
                row.thinking_content = thinking_content
                if thinking_signature is not None:
                    row.thinking_signature = thinking_signature
            await session.commit()
    except Exception as exc:
        logger.warning("[thinking_record_dao] save failed for %s: %s", thinking_id, exc)


async def get_thinking(thinking_id: str) -> Optional[dict]:
    """Return {'thinking_content': str, 'thinking_signature': str|None} or None."""
    if not thinking_id:
        return None
    try:
        from app import get_db_session
        from app.models import ThinkingRecord

        async with get_db_session() as session:
            result = await session.execute(
                select(ThinkingRecord).where(ThinkingRecord.thinking_id == thinking_id)
            )
            row = result.scalars().first()
            if row is None:
                return None
            return {
                "thinking_content": row.thinking_content,
                "thinking_signature": row.thinking_signature,
            }
    except Exception as exc:
        logger.warning("[thinking_record_dao] get failed for %s: %s", thinking_id, exc)
        return None
