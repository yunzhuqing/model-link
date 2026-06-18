"""
火山引擎 ARK 素材库管理模块 (Volcengine ARK Asset Management)

通过火山引擎 ARK 控制面 API 管理素材库资产 (CreateAsset)。
素材上传后可用于 Seedance 视频生成等场景的参考图像。

API 文档:
- CreateAsset: 创建素材库资产，将图片 URL 注册到指定的 AssetGroup

认证方式:
支持两种认证方式，按优先级自动选择：
1. HMAC-SHA256 签名 (AccessKey + SecretKey) — 推荐，需要 AK/SK
2. Bearer Token (API Key) — 作为后备

配置说明:
extra_config:
  ark_access_key: ARK Access Key ID (用于 HMAC-SHA256 签名)
  ark_secret_key: ARK Secret Access Key
  ark_region:     区域 (默认 cn-beijing)
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from app.http_client import shared_client

logger = logging.getLogger("gateway")


# =============================================================================
# 常量
# =============================================================================

ARK_API_HOST = "ark.cn-beijing.volcengineapi.com"
ARK_API_URL = f"https://{ARK_API_HOST}/"
ARK_API_SERVICE = "ark"
ARK_API_VERSION = "2024-01-01"
ARK_API_REGION = "cn-beijing"


# =============================================================================
# HMAC-SHA256 签名 (Volcengine Signature V4)
# =============================================================================

def _build_ark_auth_headers(
    access_key: str,
    secret_key: str,
    action: str,
    payload_str: str,
    region: str = ARK_API_REGION,
    service: str = ARK_API_SERVICE,
) -> Dict[str, str]:
    """
    构建火山引擎 ARK API 的 HMAC-SHA256 签名请求头。

    参考 AWS Signature V4 流程，适配火山引擎 ARK 控制面 API。

    Args:
        access_key:  ARK Access Key ID (如 AKLT...)
        secret_key:  ARK Secret Access Key
        action:      API 动作名称 (如 "CreateAsset")
        payload_str: JSON 序列化后的请求体字符串
        region:      区域 (默认 cn-beijing)
        service:     服务名称 (默认 ark)

    Returns:
        包含 Authorization、X-Date、X-Content-Sha256 等认证头的字典
    """
    algorithm = "HMAC-SHA256"
    host = ARK_API_HOST
    content_type = "application/json"

    # 使用 UTC 时间
    now = datetime.now(tz=timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_str = now.strftime("%Y%m%d")

    # 计算请求体的 SHA256
    x_content_sha256 = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    # ── Step 1: Canonical Request ──────────────────────────────────────
    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-content-sha256:{x_content_sha256}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"

    # Canonical query string: action + version
    canonical_query = f"Action={action}&Version={ARK_API_VERSION}"

    hashed_payload = x_content_sha256
    canonical_request = "\n".join([
        "POST",
        "/",
        canonical_query,
        canonical_headers,
        signed_headers,
        hashed_payload,
    ])

    # ── Step 2: String to Sign ────────────────────────────────────────
    credential_scope = f"{date_str}/{region}/{service}/request"
    hashed_canonical = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "\n".join([
        algorithm,
        x_date,
        credential_scope,
        hashed_canonical,
    ])

    # ── Step 3: Derived Signing Key ───────────────────────────────────
    def _sign(key: bytes, msg: str) -> bytes:
        return _hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = _sign(secret_key.encode("utf-8"), date_str)
    secret_region = _sign(secret_date, region)
    secret_service = _sign(secret_region, service)
    secret_signing = _sign(secret_service, "request")
    signature = _hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # ── Step 4: Authorization Header ──────────────────────────────────
    authorization = (
        f"{algorithm} "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    return {
        "Content-Type": content_type,
        "Host": host,
        "X-Date": x_date,
        "X-Content-Sha256": x_content_sha256,
        "Authorization": authorization,
    }


# =============================================================================
# CreateAsset API
# =============================================================================

async def create_asset(
    *,
    group_id: str,
    url: str,
    name: str,
    asset_type: str = "Image",
    project_name: str = "default",
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    api_key: Optional[str] = None,
    region: str = ARK_API_REGION,
) -> Dict[str, Any]:
    """
    调用火山引擎 ARK CreateAsset API，将图片注册到指定的素材组。

    Args:
        group_id:     素材组 ID (如 "group-2026...")
        url:          图片的公开可访问 URL
        name:         资产名称
        asset_type:   资产类型 ("Image", "Video" 等)
        project_name: 项目名称 (默认 "default")
        access_key:   ARK Access Key ID (HMAC-SHA256 签名用)
        secret_key:   ARK Secret Access Key (HMAC-SHA256 签名用)
        api_key:      ARK API Key (Bearer Token 认证用，作为后备)
        region:       区域

    Returns:
        API 响应的完整 JSON 字典

    Raises:
        RuntimeError: API 调用失败
    """
    payload: Dict[str, Any] = {
        "GroupId": group_id,
        "URL": url,
        "Name": name,
        "AssetType": asset_type,
        "ProjectName": project_name,
    }
    payload_str = json.dumps(payload, ensure_ascii=False)

    headers: Dict[str, str]

    if access_key and secret_key:
        headers = _build_ark_auth_headers(
            access_key=access_key,
            secret_key=secret_key,
            action="CreateAsset",
            payload_str=payload_str,
            region=region,
        )
    elif api_key:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
    else:
        raise RuntimeError(
            "Volcengine ARK CreateAsset requires either "
            "(access_key + secret_key) or api_key for authentication."
        )

    request_url = f"{ARK_API_URL}?Action=CreateAsset&Version={ARK_API_VERSION}"

    logger.info(
        "Volcengine ARK CreateAsset request: group=%s name=%s url=%.80s...",
        group_id, name, url
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
                    "Volcengine ARK CreateAsset error (status=%d): %s",
                    response.status_code,
                    json.dumps(error_data, ensure_ascii=False),
                )
                raise RuntimeError(
                    f"Volcengine ARK CreateAsset error ({response.status_code}): "
                    f"{json.dumps(error_data, ensure_ascii=False)}"
                )

            result = response.json()
            logger.info(
                "Volcengine ARK CreateAsset success: id=%s",
                result.get("Result", {}).get("Id", "unknown"),
            )
            return result

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Volcengine ARK CreateAsset error: {str(e)}")


async def upload_and_create_asset(
    *,
    group_id: str,
    image_url: str,
    name: Optional[str] = None,
    asset_type: str = "Image",
    project_name: str = "default",
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    api_key: Optional[str] = None,
    region: str = ARK_API_REGION,
) -> Dict[str, Any]:
    """
    上传图片到火山引擎素材库的便捷方法。

    从已有的公开 URL 创建素材资产。如果 name 未提供，从 URL 末尾提取文件名。

    Args:
        group_id:     素材组 ID
        image_url:    图片的公开 URL (http/https)
        name:         资产名称 (可选，默认从 URL 提取)
        asset_type:   资产类型
        project_name: 项目名称
        access_key:   ARK Access Key ID
        secret_key:   ARK Secret Access Key
        api_key:      ARK API Key (后备)
        region:       区域

    Returns:
        API 响应的完整 JSON 字典，包含 asset ID
    """
    if not name:
        url_path = image_url.split("?")[0]
        name = url_path.rsplit("/", 1)[-1] or "asset"
        if "." in name:
            name = name.rsplit(".", 1)[0]

    return await create_asset(
        group_id=group_id,
        url=image_url,
        name=name,
        asset_type=asset_type,
        project_name=project_name,
        access_key=access_key,
        secret_key=secret_key,
        api_key=api_key,
        region=region,
    )

async def delete_asset(
    *,
    asset_id: str,
    project_name: str = "default",
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    api_key: Optional[str] = None,
    region: str = ARK_API_REGION,
) -> Dict[str, Any]:
    """
    调用火山引擎 ARK DeleteAsset API，从素材组中删除资产。

    Args:
        asset_id:     资产 ID (如 "Asset-2026...")
        project_name: 项目名称 (默认 "default")
        access_key:   ARK Access Key ID (HMAC-SHA256 签名用)
        secret_key:   ARK Secret Access Key (HMAC-SHA256 签名用)
        api_key:      ARK API Key (Bearer Token 认证用，作为后备)
        region:       区域

    Returns:
        API 响应的完整 JSON 字典

    Raises:
        RuntimeError: API 调用失败
    """
    payload: Dict[str, Any] = {
        "Id": asset_id,
        "ProjectName": project_name,
    }
    payload_str = json.dumps(payload, ensure_ascii=False)

    headers: Dict[str, str]

    if access_key and secret_key:
        headers = _build_ark_auth_headers(
            access_key=access_key,
            secret_key=secret_key,
            action="DeleteAsset",
            payload_str=payload_str,
            region=region,
        )
    elif api_key:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
    else:
        raise RuntimeError(
            "Volcengine ARK DeleteAsset requires either "
            "(access_key + secret_key) or api_key for authentication."
        )

    request_url = f"{ARK_API_URL}?Action=DeleteAsset&Version={ARK_API_VERSION}"

    logger.info(
        "Volcengine ARK DeleteAsset request: id=%s project=%s",
        asset_id, project_name,
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
                    "Volcengine ARK DeleteAsset error (status=%d): %s",
                    response.status_code,
                    json.dumps(error_data, ensure_ascii=False),
                )
                raise RuntimeError(
                    f"Volcengine ARK DeleteAsset error ({response.status_code}): "
                    f"{json.dumps(error_data, ensure_ascii=False)}"
                )

            result = response.json()
            logger.info(
                "Volcengine ARK DeleteAsset success: id=%s request_id=%s",
                asset_id,
                result.get("ResponseMetadata", {}).get("RequestId", ""),
            )
            return result

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Volcengine ARK DeleteAsset error: {str(e)}")

