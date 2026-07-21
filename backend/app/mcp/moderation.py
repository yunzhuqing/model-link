"""
火山引擎 Seedance 内容封控原因查询 (GetModerationResult)。

通过火山引擎 ``open.volcengineapi.com`` 上的 ``GetModerationResult`` 接口，
根据素材库 ID / 任务 ID / 推理请求 ID 查询内容被风控封控的原因
(``block_reasons``)。认证使用 Volcengine Signature V4 (HMAC-SHA256)，
复用 ``app.providers.volcengine.asset._build_ark_auth_headers``。

凭证来自数据库中 Volcengine Provider 行的 ``extra_config``：
  - ark_access_key: Access Key ID
  - ark_secret_key: Secret Access Key
  - ark_region:     区域 (默认 cn-beijing)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.http_client import shared_client
from app.models import Provider
from app.providers.volcengine.asset import _build_ark_auth_headers

logger = logging.getLogger("gateway")

# GetModerationResult 接口常量
MODERATION_API_HOST = "open.volcengineapi.com"
MODERATION_API_URL = f"https://{MODERATION_API_HOST}/"
MODERATION_API_SERVICE = "ark"
MODERATION_API_VERSION = "2024-01-01"
MODERATION_API_REGION = "cn-beijing"

# Type 取值白名单
VALID_TYPES = ("asset_id", "task_id", "request_id")


async def resolve_volcengine_creds(
    *,
    provider_id: Optional[int] = None,
    provider_name: Optional[str] = None,
    group_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    从数据库解析火山引擎 Provider 的 AK/SK 凭证。

    选择优先级：
      1. 显式传入的 ``provider_id``
      2. 显式传入的 ``provider_name``
      3. 环境变量 ``MCP_VOLCENGINE_PROVIDER_ID``
      4. 第一条启用的 volcengine Provider (按 id 升序)

    Args:
        group_id: 若提供 (非 None)，则只在该分组内解析凭证——显式指定的
            ``provider_id`` / ``provider_name`` 与环境变量指定的 provider 都
            必须属于该分组，否则视为不存在。用于把 MCP 工具调用限定在
            apikey 所属分组内。

    Returns:
        ``{access_key, secret_key, region, provider_id, provider_name}``

    Raises:
        RuntimeError: 找不到 Provider 或缺少 AK/SK。
    """
    from app import get_db_session

    query = select(Provider).where(
        Provider.type == "volcengine",
        Provider.is_active.is_(True),
    )
    if group_id is not None:
        query = query.where(Provider.group_id == group_id)

    env_provider_id = os.getenv("MCP_VOLCENGINE_PROVIDER_ID")
    if provider_id:
        query = query.where(Provider.id == provider_id)
    elif provider_name:
        query = query.where(Provider.name == provider_name)
    elif env_provider_id:
        try:
            query = query.where(Provider.id == int(env_provider_id))
        except (TypeError, ValueError):
            raise RuntimeError(
                f"Invalid MCP_VOLCENGINE_PROVIDER_ID: {env_provider_id!r}"
            )
    else:
        query = query.order_by(Provider.id.asc())

    async with get_db_session() as session:
        result = await session.execute(query)
        provider = result.scalars().first()

    if not provider:
        scope_hint = f" in group {group_id}" if group_id is not None else ""
        raise RuntimeError(
            f"No active Volcengine provider found{scope_hint}. "
            "Please configure a Volcengine provider first."
        )

    extra = provider.extra_config or {}
    access_key = extra.get("ark_access_key", "") or ""
    secret_key = extra.get("ark_secret_key", "") or ""
    region = extra.get("ark_region", MODERATION_API_REGION) or MODERATION_API_REGION

    if not (access_key and secret_key):
        raise RuntimeError(
            f"Volcengine provider '{provider.name}' (id={provider.id}) is missing "
            "AK/SK. Set extra_config.ark_access_key + extra_config.ark_secret_key "
            "in the admin panel to enable moderation queries."
        )

    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "region": region,
        "provider_id": provider.id,
        "provider_name": provider.name,
    }


async def get_moderation_result(
    *,
    id: str,
    type: str,
    access_key: str,
    secret_key: str,
    region: str = MODERATION_API_REGION,
) -> Dict[str, Any]:
    """
    调用火山引擎 GetModerationResult 接口。

    Args:
        id:          火山引擎任务 ID / 素材库 ID / 推理请求 ID
        type:        asset_id | task_id | request_id
        access_key:  Volcengine Access Key ID
        secret_key:  Volcengine Secret Access Key
        region:      区域 (默认 cn-beijing)

    Returns:
        API 响应的完整 JSON 字典 (含 ResponseMetadata 与 Result)。

    Raises:
        ValueError: ``type`` 非法。
        RuntimeError: 接口返回错误状态码或网络异常。
    """
    if type not in VALID_TYPES:
        raise ValueError(
            f"Invalid type {type!r}; expected one of {list(VALID_TYPES)}"
        )
    if not id:
        raise ValueError("id must be a non-empty string")

    payload: Dict[str, Any] = {"Id": id, "Type": type}
    payload_str = json.dumps(payload, ensure_ascii=False)

    headers = _build_ark_auth_headers(
        access_key=access_key,
        secret_key=secret_key,
        action="GetModerationResult",
        payload_str=payload_str,
        region=region,
        service=MODERATION_API_SERVICE,
        host=MODERATION_API_HOST,
    )

    request_url = (
        f"{MODERATION_API_URL}?Action=GetModerationResult&Version={MODERATION_API_VERSION}"
    )

    logger.info(
        "Volcengine GetModerationResult request: type=%s id=%.60s",
        type, id,
    )

    try:
        async with shared_client() as client:
            response = await client.post(
                request_url,
                content=payload_str,
                headers=headers,
            )

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                except json.JSONDecodeError:
                    error_data = {"raw": response.text}
                logger.error(
                    "Volcengine GetModerationResult error (status=%d): %s",
                    response.status_code,
                    json.dumps(error_data, ensure_ascii=False),
                )
                raise RuntimeError(
                    f"Volcengine GetModerationResult error ({response.status_code}): "
                    f"{json.dumps(error_data, ensure_ascii=False)}"
                )

            result = response.json()
            logger.info(
                "Volcengine GetModerationResult success: id=%s block_reasons=%d",
                id,
                len((result.get("Result") or {}).get("block_reasons") or []),
            )
            return result

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Volcengine GetModerationResult error: {str(e)}")


async def fetch_block_reasons(
    id: str,
    type: str,
    *,
    provider_id: Optional[int] = None,
    provider_name: Optional[str] = None,
    group_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    端到端查询：解析凭证 → 调用 GetModerationResult → 提取 block_reasons。

    Args:
        group_id: 若提供 (非 None)，凭证解析限定在该分组内 (见
            ``resolve_volcengine_creds``)。

    Returns:
        ``{
            "provider": {"id":..., "name":...},
            "block_reasons": [{"label","sub_label","detail"}, ...],
            "raw": <完整响应>,
            "has_block": bool,
        }``
    """
    creds = await resolve_volcengine_creds(
        provider_id=provider_id,
        provider_name=provider_name,
        group_id=group_id,
    )
    raw = await get_moderation_result(
        id=id,
        type=type,
        access_key=creds["access_key"],
        secret_key=creds["secret_key"],
        region=creds["region"],
    )
    block_reasons: List[Dict[str, Any]] = (
        (raw.get("Result") or {}).get("block_reasons") or []
    )
    return {
        "provider": {"id": creds["provider_id"], "name": creds["provider_name"]},
        "block_reasons": block_reasons,
        "raw": raw,
        "has_block": bool(block_reasons),
    }
