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

import asyncio
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
from app.qps_rate_limiter import QPSRateLimiter

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
    host: str = ARK_API_HOST,
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
        host:        签名所用主机名 (默认 ARK_API_HOST；调用 open.volcengineapi.com
                     上的 GetModerationResult 等接口时需显式传入该主机)

    Returns:
        包含 Authorization、X-Date、X-Content-Sha256 等认证头的字典
    """
    algorithm = "HMAC-SHA256"
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



# =============================================================================
# 类型检测
# =============================================================================

_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tiff", ".tif"})
_VIDEO_EXTS = frozenset({".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg"})
_AUDIO_EXTS = frozenset({".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma", ".opus", ".aiff"})


def _detect_asset_type(url: str) -> str:
    """
    Detect Volcengine ARK asset type from a URL's file extension.

    Returns one of "Image", "Video", or "Audio".
    Falls back to "Image" when the extension is unrecognized.
    """
    path = url.split("?")[0].lower()
    # Find the last '.' and extract extension
    dot = path.rfind(".")
    if dot == -1:
        return "Image"

    ext = path[dot:]

    if ext in _IMAGE_EXTS:
        return "Image"
    elif ext in _VIDEO_EXTS:
        return "Video"
    elif ext in _AUDIO_EXTS:
        return "Audio"

    # Fallback: check MIME-like patterns in URL path
    return "Image"


async def upload_and_create_asset(
    *,
    group_id: str,
    image_url: str,
    name: Optional[str] = None,
    asset_type: Optional[str] = None,
    project_name: str = "default",
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    api_key: Optional[str] = None,
    region: str = ARK_API_REGION,
) -> Dict[str, Any]:
    """
    上传文件到火山引擎素材库的便捷方法。

    从已有的公开 URL 创建素材资产。
    AssetType 会根据 URL 文件扩展名自动检测（Image / Video / Audio），
    也可通过 asset_type 参数显式指定。
    如果 name 未提供，从 URL 末尾提取文件名。

    Args:
        group_id:     素材组 ID
        image_url:    文件的公开 URL (http/https)
        name:         资产名称 (可选，默认从 URL 提取)
        asset_type:   资产类型 ("Image"/"Video"/"Audio"，None 则自动检测)
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

    final_asset_type = asset_type or _detect_asset_type(image_url)

    return await create_asset(
        group_id=group_id,
        url=image_url,
        name=name,
        asset_type=final_asset_type,
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
        asset_id:     资产 ID (如 "asset-2026...")
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



# =============================================================================
# GetAsset API
# =============================================================================

async def get_asset(
    *,
    asset_id: str,
    project_name: str = "default",
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    api_key: Optional[str] = None,
    region: str = ARK_API_REGION,
) -> Dict[str, Any]:
    """
    调用火山引擎 ARK GetAsset API，查询素材库资产的详细信息。

    返回的 Result.Status 字段可能的值：
    - "Processing": 资产正在处理中
    - "Active":     资产已就绪（成功）
    - "Failed":     资产处理失败

    Args:
        asset_id:     资产 ID (如 "asset-2026...")
        project_name: 项目名称 (默认 "default")
        access_key:   ARK Access Key ID (HMAC-SHA256 签名用)
        secret_key:   ARK Secret Access Key (HMAC-SHA256 签名用)
        api_key:      ARK API Key (Bearer Token 认证用，作为后备)
        region:       区域

    Returns:
        API 响应的完整 JSON 字典，包含 Result.Status 字段

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
            action="GetAsset",
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
            "Volcengine ARK GetAsset requires either "
            "(access_key + secret_key) or api_key for authentication."
        )

    request_url = f"{ARK_API_URL}?Action=GetAsset&Version={ARK_API_VERSION}"

    logger.info(
        "Volcengine ARK GetAsset request: id=%s project=%s",
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
                    "Volcengine ARK GetAsset error (status=%d): %s",
                    response.status_code,
                    json.dumps(error_data, ensure_ascii=False),
                )
                raise RuntimeError(
                    f"Volcengine ARK GetAsset error ({response.status_code}): "
                    f"{json.dumps(error_data, ensure_ascii=False)}"
                )

            result = response.json()
            logger.info(
                "Volcengine ARK GetAsset success: id=%s status=%s request_id=%s",
                asset_id,
                result.get("Result", {}).get("Status", "unknown"),
                result.get("ResponseMetadata", {}).get("RequestId", ""),
            )
            return result

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Volcengine ARK GetAsset error: {str(e)}")


# =============================================================================
# Asset polling helper
# =============================================================================

# Polling constants for asset status check
_ASSET_POLL_INTERVAL_S: float = 2.0
_ASSET_POLL_TIMEOUT_S: int = 180  # 3 minutes
_ASSET_TERMINAL_STATUSES = frozenset({"Active", "Failed"})


async def poll_asset_status(
    asset_ids: list,
    project_name: str = "default",
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    api_key: Optional[str] = None,
    region: str = ARK_API_REGION,
    timeout: int = _ASSET_POLL_TIMEOUT_S,
) -> Dict[str, str]:
    """
    轮询多个资产的 GetAsset 状态，直到全部变为 Active 或任何变为 Failed。

    资产状态转换：Processing → Active / Failed。

    如果任一资产的 Status 为 Failed，则整个请求视为失败并抛出 RuntimeError。
    如果所有资产都变为 Active，返回每个资产 ID 到其最终状态 ("Active") 的映射。
    如果超过 timeout 秒后仍有资产处于 Processing，则抛出 RuntimeError。

    Args:
        asset_ids:    资产 ID 列表（如 ["asset-2026...", ...]）
        project_name: 项目名称
        access_key:   ARK Access Key ID
        secret_key:   ARK Secret Access Key
        api_key:      ARK API Key (后备)
        region:       区域
        timeout:      轮询超时时间（秒），默认 180 秒（3 分钟）

    Returns:
        字典，key 为 asset_id，value 为最终状态 ("Active")

    Raises:
        RuntimeError: 任一资产失败或轮询超时
    """
    if not asset_ids:
        return {}

    deadline = time.time() + timeout
    pending_ids = set(asset_ids)
    final_statuses: Dict[str, str] = {}
    failed_assets: Dict[str, str] = {}

    logger.info(
        "Volcengine ARK polling asset status: ids=%s timeout=%ds",
        list(asset_ids), timeout,
    )

    try:
        while pending_ids and time.time() < deadline:
            # Poll all pending assets concurrently
            ids_snapshot = list(pending_ids)
            tasks = [
                get_asset(
                    asset_id=aid,
                    project_name=project_name,
                    access_key=access_key,
                    secret_key=secret_key,
                    api_key=api_key,
                    region=region,
                )
                for aid in ids_snapshot
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_pending: set = set()
            for aid, res in zip(ids_snapshot, results):
                if isinstance(res, Exception):
                    logger.warning(
                        "Volcengine ARK poll asset %s error: %s", aid, res
                    )
                    new_pending.add(aid)
                    continue

                status = res.get("Result", {}).get("Status", "")
                if status == "Active":
                    final_statuses[aid] = "Active"
                    logger.info(
                        "Volcengine ARK asset %s: Active", aid
                    )
                elif status == "Failed":
                    error_info = res.get("Result", {}).get("Error", {})
                    error_code = error_info.get("Code", "")
                    error_msg = error_info.get("Message", "")
                    failed_assets[aid] = f"Failed: code={error_code}, msg={error_msg}"
                    logger.error(
                        "Volcengine ARK asset %s: Failed (code=%s, msg=%s)",
                        aid, error_code, error_msg,
                    )
                else:
                    # Still Processing or unknown — wait
                    new_pending.add(aid)
                    logger.debug(
                        "Volcengine ARK asset %s: %s (still polling)",
                        aid, status,
                    )

            pending_ids = new_pending

            # If any asset failed, fail the whole request
            if failed_assets:
                failed_details = "; ".join(
                    f"{aid}: {reason}" for aid, reason in failed_assets.items()
                )
                raise RuntimeError(
                    f"Volcengine ARK asset upload failed: {failed_details}"
                )

            # Wait before next poll if still pending
            if pending_ids:
                await asyncio.sleep(_ASSET_POLL_INTERVAL_S)

        # Timeout: some assets still Processing
        if pending_ids:
            pending_list = ", ".join(sorted(pending_ids))
            raise RuntimeError(
                f"Volcengine ARK asset polling timed out after {timeout}s. "
                f"Still processing: {pending_list}"
            )

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Volcengine ARK asset polling error: {str(e)}")

    return final_statuses


# =============================================================================
# Batch delete assets helper
# =============================================================================

async def batch_delete_assets(
    asset_ids: list,
    project_name: str = "default",
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    api_key: Optional[str] = None,
    region: str = ARK_API_REGION,
    max_concurrency: int = 5,
    max_qps: int = 8,
) -> Dict[str, bool]:
    """
    批量删除多个资产（并发调用 DeleteAsset，尽力而为）。

    使用 asyncio.Semaphore 控制并发数 + RateLimiter 控制每秒请求数，
    确保不超过 DeleteAsset QPS 限制（默认 10，这里用 8 留余地）。

    如果某个资产删除失败，记录错误日志但继续尝试删除其他资产。

    Args:
        asset_ids:        资产 ID 列表
        project_name:     项目名称
        access_key:       ARK Access Key ID
        secret_key:       ARK Secret Access Key
        api_key:          ARK API Key (后备)
        region:           区域
        max_concurrency:  最大并发删除数（默认 5）
        max_qps:          最大每秒请求数（默认 8，安全低于 QPS=10 限制）

    Returns:
        字典，key 为 asset_id，value 为 True(成功)/False(失败)
    """
    if not asset_ids:
        return {}

    semaphore = asyncio.Semaphore(max_concurrency)
    rate_limiter = QPSRateLimiter(max_qps)

    async def _delete_one(aid: str) -> tuple:
        async with semaphore:
            await rate_limiter.acquire()
            try:
                await delete_asset(
                    asset_id=aid,
                    project_name=project_name,
                    access_key=access_key,
                    secret_key=secret_key,
                    api_key=api_key,
                    region=region,
                )
                return aid, True
            except Exception as e:
                logger.warning(
                    "Volcengine ARK batch delete: failed to delete asset %s: %s",
                    aid, e,
                )
                return aid, False

    tasks = [_delete_one(aid) for aid in asset_ids]
    results_list = await asyncio.gather(*tasks)

    result_map: Dict[str, bool] = {}
    for aid, success in results_list:
        result_map[aid] = success

    success_count = sum(1 for v in result_map.values() if v)
    logger.info(
        "Volcengine ARK batch delete: %d/%d assets deleted successfully",
        success_count, len(asset_ids),
    )

    return result_map
