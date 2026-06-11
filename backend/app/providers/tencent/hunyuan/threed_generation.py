"""
混元 3D 生成模块 (Hunyuan 3D Generation)

通过混元 3D 生成 API 从图片、文本或 3D 文件生成 3D 模型，兼容 /v1/responses 3d_generation 工具。

流程：
1. 发起请求:
   - Rapid 模型: POST ai3d.tencentcloudapi.com  X-TC-Action: SubmitHunyuanTo3DRapidJob
   - Pro   模型: POST ai3d.tencentcloudapi.com  X-TC-Action: SubmitHunyuanTo3DProJob
   - Part  模型: POST ai3d.tencentcloudapi.com  X-TC-Action: SubmitHunyuan3DPartJob  (Model=1.5, File 输入)
   - ReduceFace 模型: POST ai3d.tencentcloudapi.com  X-TC-Action: SubmitReduceFaceJob  (File3D 输入)
2. 轮询结果:
   - Rapid 模型: POST ai3d.tencentcloudapi.com  X-TC-Action: QueryHunyuanTo3DRapidJob
   - Pro   模型: POST ai3d.tencentcloudapi.com  X-TC-Action: QueryHunyuanTo3DProJob
   - Part  模型: POST ai3d.tencentcloudapi.com  X-TC-Action: QueryHunyuan3DPartJob
   - ReduceFace 模型: POST ai3d.tencentcloudapi.com  X-TC-Action: QueryReduceFaceJob
   直到 Status == "DONE"

认证方式：
腾讯云 API 使用 TC3-HMAC-SHA256 签名。
api_key 字段应为 "SecretId:SecretKey" 格式。

/v1/responses 工具请求示例 (多视角图片):
{
    "type": "3d_generation",
    "pbr": true,
    "face_count": 1000000,
    "generate_type": "Normal",       // hunyuan-3d-pro 专用，默认 Normal
    "polygon_type": "triangle",      // hunyuan-3d-pro 专用，仅 generate_type=LowPoly 生效
    "output_format": "OBJ"           // OBJ | GLB | STL | USDZ | FBX | MP4
}

API 文档:
  https://cloud.tencent.com/document/product/1684/
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, AsyncGenerator, List, Optional, Tuple
import asyncio

import httpx

from app.http_client import shared_client

from app.abstraction.chat import (
    ChatChoice,
    ChatRequest,
    ChatResponse,
    FinishReason,
    UsageInfo,
)
from app.abstraction.messages import Message, MessageRole, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id, json_loads


# =============================================================================
# 常量
# =============================================================================

HUNYUAN3D_API_HOST = "ai3d.tencentcloudapi.com"
HUNYUAN3D_API_URL = f"https://{HUNYUAN3D_API_HOST}/"
HUNYUAN3D_API_VERSION = "2025-05-13"
HUNYUAN3D_API_REGION = "ap-guangzhou"

# Job 状态枚举
STATUS_WAIT = "WAIT"
STATUS_RUN = "RUN"
STATUS_FAIL = "FAIL"
STATUS_DONE = "DONE"

# 轮询配置
_POLL_INTERVAL_S = 3.0   # 每次轮询间隔（秒）
_POLL_MAX_WAIT_S = 600   # 最大等待时间（秒）

# Rapid 模型标识
_RAPID_MODELS = {"hunyuan-3d-rapid", "hy-3d-express"}

# Part 模型标识 (3D 部件分割 / 拆分)
_PART_MODELS = {"hunyuan-3d-1.5-part"}

# ReduceFace 模型标识 (3D 减面)
_REDUCE_FACE_MODELS = {"hunyuan-3d-reduce-face"}

# Pro 模型与 API Model 参数的映射
# key: 模型名前缀（小写），value: API 中 Model 字段的值（None 表示不传）
_PRO_MODEL_MAP: Dict[str, Optional[str]] = {
    "hunyuan-3d-3.1-pro": "3.1",
    "hunyuan-3d-3.0-pro": "3.0",
    "hy-3d-3.0":          "3.1",   # hy-3d-3.0 → API Model=3.1
    "hy-3d-3.1":          "3.0",   # hy-3d-3.1 → API Model=3.0
    "hunyuan-3d-pro":     None,    # 旧 Pro 模型，不传 Model 字段
}

# ── 积分消耗规则 ─────────────────────────────────────────────────────────
# Pro 版本: 各参数积分叠加
_PRO_GENERATE_TYPE_CREDITS = {
    "Normal": 20,
    "LowPoly": 25,
    "Geometry": 15,
    "Sketch": 25,
}
_PRO_MULTI_VIEW_CREDITS = 10       # MultiViewImages
_PRO_PBR_CREDITS = 10              # EnablePBR
_PRO_FACE_COUNT_CREDITS = 10       # FaceCount
_PRO_RESULT_FORMAT_CREDITS = 5     # ResultFormat (non-OBJ)

# Rapid 版本: 基础 + 可选 PBR
_RAPID_BASE_CREDITS = 15           # 文本或图片输入
_RAPID_PBR_CREDITS = 10            # EnablePBR

# Part 版本: 基础积分
_PART_BASE_CREDITS = 15            # 文件输入 (FBX)

# ReduceFace 版本: 基础积分
_REDUCE_FACE_BASE_CREDITS = 15   # 文件输入 (3D 减面)


def _calculate_credits(
    model: str,
    *,
    enable_pbr: bool = False,
    result_format: str = "OBJ",
    generate_type: Optional[str] = None,
    multi_view_images: Optional[List[Dict[str, Any]]] = None,
    face_count: Optional[int] = None,
    credit_rules: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Calculate credit consumption for a Hunyuan 3D request.

    Credit rules are read from ``credit_rules`` (the ``output_pricing['3d']['credits']``
    dict from the model config).  Falls back to hardcoded defaults when no rules are
    provided.

    Returns (total_credits, breakdown_dict) suitable for tracing.
    """
    is_pro = _is_pro_model(model)
    is_part = _is_part_model(model)
    is_reduce_face = _is_reduce_face_model(model)
    model_type = "reduce_face" if is_reduce_face else ("part" if is_part else ("pro" if is_pro else "rapid"))
    breakdown: Dict[str, Any] = {"model": model, "model_type": model_type}
    total = 0

    rules = credit_rules or {}

    if is_reduce_face:
        # ReduceFace: base credits for file input (3D face reduction)
        base_credits = rules.get("base", _REDUCE_FACE_BASE_CREDITS)
        breakdown["base"] = {"credits": base_credits}
        total += base_credits
    elif is_part:
        # Part: base credits for file input (FBX or other 3D format)
        base_credits = rules.get("base", _PART_BASE_CREDITS)
        breakdown["base"] = {"credits": base_credits}
        total += base_credits
    elif is_pro:
        # GenerateType
        gt = generate_type or "Normal"
        gt_map = rules.get("generate_type", _PRO_GENERATE_TYPE_CREDITS)
        gt_credits = gt_map.get(gt, 20) if isinstance(gt_map, dict) else 20
        breakdown["generate_type"] = {"type": gt, "credits": gt_credits}
        total += gt_credits

        # MultiViewImages
        if multi_view_images:
            mv_credits = rules.get("multi_view_images", _PRO_MULTI_VIEW_CREDITS)
            breakdown["multi_view_images"] = {"count": len(multi_view_images), "credits": mv_credits}
            total += mv_credits

        # EnablePBR
        if enable_pbr:
            pbr_credits = rules.get("enable_pbr", _PRO_PBR_CREDITS)
            breakdown["enable_pbr"] = {"credits": pbr_credits}
            total += pbr_credits

        # FaceCount
        if face_count is not None:
            fc_credits = rules.get("face_count", _PRO_FACE_COUNT_CREDITS)
            breakdown["face_count"] = {"value": face_count, "credits": fc_credits}
            total += fc_credits

        # ResultFormat (OBJ and GLB are free, other formats cost credits)
        fmt = result_format.upper() if result_format else "OBJ"
        if fmt not in ("OBJ", "GLB"):
            rf_credits = rules.get("result_format_non_obj", _PRO_RESULT_FORMAT_CREDITS)
            breakdown["result_format"] = {"format": fmt, "credits": rf_credits}
            total += rf_credits
        else:
            breakdown["result_format"] = {"format": fmt, "credits": 0}
    else:
        # Rapid: base credits for input (text or image)
        base_credits = rules.get("base", _RAPID_BASE_CREDITS)
        breakdown["base"] = {"credits": base_credits}
        total += base_credits

        # EnablePBR
        if enable_pbr:
            pbr_credits = rules.get("enable_pbr", _RAPID_PBR_CREDITS)
            breakdown["enable_pbr"] = {"credits": pbr_credits}
            total += pbr_credits

    breakdown["total"] = total
    return total, breakdown


# =============================================================================
# 模型检测
# =============================================================================

def is_hunyuan3d_model(model: str) -> bool:
    """
    Check if the model is a Hunyuan 3D generation model.

    Recognized model identifiers:
      Rapid: hunyuan-3d-rapid, hy-3d-express
      Pro:   hunyuan-3d-pro, hunyuan-3d-3.0-pro, hunyuan-3d-3.1-pro,
             hy-3d-3.0, hy-3d-3.1
      Part:  hunyuan-3d-1.5-part
      ReduceFace: hunyuan-3d-reduce-face

    Args:
        model: Model name (case-insensitive)

    Returns:
        True if the model is a Hunyuan 3D generation model
    """
    lower = model.lower()
    return (
        lower.startswith("hunyuan-3d-")
        or lower.startswith("hy-3d-")
    )


def has_threed_generation_tool(request: ChatRequest) -> bool:
    """
    Check if the request was sent with a ``3d_generation`` tool.

    When the Responses API adapter parses a ``3d_generation`` tool entry,
    it stores ``_3d_generation=True`` in ``request.metadata``.

    Args:
        request: The chat request to check

    Returns:
        True if the request was sent with a ``3d_generation`` tool.
    """
    return bool(request.metadata.get("_3d_generation"))


def _is_pro_model(model: str) -> bool:
    """Check whether the given model identifier is a Pro variant.

    A model is Pro if it is NOT in the known Rapid or Part set.
    All new hy-3d-* models (except hy-3d-express) default to Pro.
    """
    lower = model.lower()
    return lower not in _RAPID_MODELS and lower not in _PART_MODELS and lower not in _REDUCE_FACE_MODELS


def _is_part_model(model: str) -> bool:
    """Check whether the given model identifier is a Part variant (3D part segmentation).

    Part models use SubmitHunyuan3DPartJob / QueryHunyuan3DPartJob actions
    and take a 3D file (FBX) as input instead of images or text prompts.
    """
    return model.lower() in _PART_MODELS


def _is_reduce_face_model(model: str) -> bool:
    """Check whether the given model identifier is a ReduceFace variant (3D face reduction).

    ReduceFace models use SubmitReduceFaceJob / QueryReduceFaceJob actions
    and take a 3D file as input with PolygonType and FaceLevel parameters.
    """
    return model.lower() in _REDUCE_FACE_MODELS


def _get_api_model_version(model: str) -> Optional[str]:
    """Return the API ``Model`` field value for SubmitHunyuanTo3DProJob.

    Returns None if the model does not require an explicit Model parameter.
    """
    return _PRO_MODEL_MAP.get(model.lower())


# =============================================================================
# TC3-HMAC-SHA256 认证
# =============================================================================

def _build_auth_headers(
    secret_id: str,
    secret_key: str,
    action: str,
    payload_str: str,
    region: str = HUNYUAN3D_API_REGION,
) -> Dict[str, str]:
    """
    Build TC3-HMAC-SHA256 signed request headers for a Hunyuan 3D API call.

    Args:
        secret_id:   腾讯云 SecretId
        secret_key:  腾讯云 SecretKey
        action:      API 动作名称
        payload_str: JSON 序列化后的请求体字符串
        region:      区域，默认 ap-guangzhou

    Returns:
        包含认证信息的请求头字典
    """
    algorithm = "TC3-HMAC-SHA256"
    service = "ai3d"
    host = HUNYUAN3D_API_HOST
    content_type = "application/json; charset=utf-8"

    timestamp = int(time.time())
    date_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

    # Step 1 — Canonical Request
    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-tc-action:{action.lower()}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
    canonical_request = "\n".join([
        "POST",
        "/",
        "",
        canonical_headers,
        signed_headers,
        hashed_payload,
    ])

    # Step 2 — String to Sign
    credential_scope = f"{date_str}/{service}/tc3_request"
    hashed_canonical = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "\n".join([
        algorithm,
        str(timestamp),
        credential_scope,
        hashed_canonical,
    ])

    # Step 3 — Derived Signing Key
    def _sign(key: bytes, msg: str) -> bytes:
        return _hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = _sign(("TC3" + secret_key).encode("utf-8"), date_str)
    secret_service = _sign(secret_date, service)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = _hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # Step 4 — Authorization Header
    authorization = (
        f"{algorithm} "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    return {
        "Content-Type": content_type,
        "Host": host,
        "Authorization": authorization,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": HUNYUAN3D_API_VERSION,
        "X-TC-Region": region,
        "X-TC-Action": action,
    }


def _parse_api_key(api_key: str) -> Tuple[str, str]:
    """
    Parse SecretId and SecretKey from api_key string.

    Expected format: "SecretId:SecretKey"

    Args:
        api_key: Combined credential string

    Returns:
        (secret_id, secret_key) tuple

    Raises:
        ValueError: If the format is invalid
    """
    if ":" not in api_key:
        raise ValueError(
            "Hunyuan 3D api_key must be in 'SecretId:SecretKey' format"
        )
    secret_id, secret_key = api_key.split(":", 1)
    return secret_id.strip(), secret_key.strip()


# =============================================================================
# API 调用: Submit 3D Job
# =============================================================================

async def _submit_3d_job(
    client: httpx.AsyncClient,
    secret_id: str,
    secret_key: str,
    model: str,
    image_url: Optional[str],
    image_base64: Optional[str],
    prompt: Optional[str],
    enable_pbr: bool = False,
    result_format: str = "OBJ",
    enable_geometry: bool = False,
    # Pro-only params
    multi_view_images: Optional[List[Dict[str, str]]] = None,
    face_count: Optional[int] = None,
    generate_type: Optional[str] = None,
    polygon_type: Optional[str] = None,
    # Part-only params
    file_url: Optional[str] = None,
    file_type: str = "FBX",
    # ReduceFace-only params
    face_level: Optional[str] = None,
    region: str = HUNYUAN3D_API_REGION,
    credit_rules: Optional[Dict[str, Any]] = None,
    tracer: Any = None,
) -> Tuple[str, int, Dict[str, Any]]:
    """
    Submit a Hunyuan 3D generation job and return (JobId, estimated_credits, credit_breakdown).

    API Version: 2025-05-13
    For Rapid models: SubmitHunyuanTo3DRapidJob
    For Pro models:   SubmitHunyuanTo3DProJob
    For Part models:  SubmitHunyuan3DPartJob
    For ReduceFace models: SubmitReduceFaceJob

    Args:
        client:            httpx client
        secret_id:         腾讯云 SecretId
        secret_key:        腾讯云 SecretKey
        model:             模型名称，用于区分 Rapid / Pro / Part
        image_url:         输入图 URL（可选，与 image_base64/prompt 互斥）
        image_base64:      输入图 Base64（可选，与 image_url/prompt 互斥）
        prompt:            文本提示词（可选，与 image_url/image_base64 互斥）
        enable_pbr:        是否开启 PBR 材质生成，默认 false
        result_format:     生成模型格式: OBJ | GLB | STL | USDZ | FBX | MP4
        enable_geometry:   是否开启单几何生成（白模），开启后不支持 OBJ 格式
        multi_view_images: 多视角图片列表（Pro 专用），每项:
                           {"view_type": "front|back|left|right|up|down|left_front|right_front",
                            "image_url": "...", "image_base64": "..."}
        face_count:        生成面数（Pro 专用，LowPoly 时无效）: 3000–1500000
        generate_type:     生成类型（Pro 专用）: Normal|LowPoly|Geometry|Sketch
        polygon_type:      多边形类型（Pro+LowPoly 专用）: triangle|quadrilateral
        file_url:          输入 3D 文件 URL（Part 专用），如 FBX 文件地址
        file_type:         输入 3D 文件类型（Part 专用），默认 "FBX"
        face_level:       面数级别（ReduceFace 专用）: high|medium|low
        region:            API 区域

    Returns:
        Tuple of (JobId, estimated_credits, credit_breakdown_dict)

    Raises:
        RuntimeError: On API error
    """
    is_pro = _is_pro_model(model)
    is_part = _is_part_model(model)
    is_reduce_face = _is_reduce_face_model(model)

    if is_reduce_face:
        action = "SubmitReduceFaceJob"
    elif is_part:
        action = "SubmitHunyuan3DPartJob"
    elif is_pro:
        action = "SubmitHunyuanTo3DProJob"
    else:
        action = "SubmitHunyuanTo3DRapidJob"

    # Calculate estimated credits based on input parameters
    estimated_credits, credit_breakdown = _calculate_credits(
        model,
        enable_pbr=enable_pbr,
        result_format=result_format,
        generate_type=generate_type,
        multi_view_images=multi_view_images,
        face_count=face_count,
        credit_rules=credit_rules,
    )

    body: Dict[str, Any] = {}

    # Part model: always set Model=1.5
    if is_part:
        body["Model"] = "1.5"

    # Pro-only: Model version field (3.0 / 3.1)
    if is_pro:
        api_model_version = _get_api_model_version(model)
        if api_model_version:
            body["Model"] = api_model_version

    # Input handling:
    # - Part models: set File parameter with file URL and type
    # - Pro + multi_view_images: set MultiViewImages for angle views.
    #   Additionally, if a primary image (without view) is provided, set ImageUrl/ImageBase64.
    # - Otherwise: exactly one of ImageUrl, ImageBase64, or Prompt.
    if is_reduce_face:
        if file_url:
            body["File3D"] = {
                "Type": file_type,
                "Url": file_url,
            }
        if polygon_type:
            body["PolygonType"] = polygon_type
        if face_level:
            body["FaceLevel"] = face_level
    elif is_part:
        if file_url:
            body["File"] = {
                "Type": file_type,
                "Url": file_url,
            }
    elif is_pro and multi_view_images:
        mv_list = []
        for img in multi_view_images:
            entry: Dict[str, str] = {}
            view = img.get("view_type", "")
            if view:
                entry["ViewType"] = view
            img_url = img.get("image_url", "")
            if img_url:
                entry["ViewImageUrl"] = img_url
            img_b64 = img.get("image_base64", "")
            if img_b64:
                entry["ViewImageBase64"] = img_b64
            if entry:
                mv_list.append(entry)
        if mv_list:
            body["MultiViewImages"] = mv_list
        # Primary image (no view angle) goes to ImageUrl / ImageBase64
        if image_url:
            body["ImageUrl"] = image_url
        elif image_base64:
            body["ImageBase64"] = image_base64
    elif image_url:
        body["ImageUrl"] = image_url
    elif image_base64:
        body["ImageBase64"] = image_base64
    elif prompt:
        body["Prompt"] = prompt

    # Common optional params
    if result_format and not is_part and not is_reduce_face:
        body["ResultFormat"] = result_format
    if enable_pbr and not is_part and not is_reduce_face:
        body["EnablePBR"] = True
    if enable_geometry and not is_part and not is_reduce_face:
        body["EnableGeometry"] = True

    # Pro-only optional params
    if is_pro:
        if face_count is not None:
            body["FaceCount"] = face_count
        if generate_type:
            body["GenerateType"] = generate_type
        if polygon_type and generate_type == "LowPoly":
            body["PolygonType"] = polygon_type

    payload_str = json.dumps(body, ensure_ascii=False)

    headers = _build_auth_headers(secret_id, secret_key, action, payload_str, region=region)

    _span = None
    if tracer:
        _span = tracer.start_child("submit-" + model, model=model, provider_type="hunyuan", input_data=body, obs_type="span")
        if _span:
            _span.log_input({**body, "credit_breakdown": credit_breakdown})
    _error: Optional[Exception] = None

    try:
        response = await client.post(HUNYUAN3D_API_URL, content=payload_str, headers=headers)
        response.raise_for_status()
        data = response.json()
        resp = data.get("Response", {})
        if "Error" in resp:
            err = resp["Error"]
            raise RuntimeError(
                f"Hunyuan3D {action} error "
                f"(code={err.get('Code')}): {err.get('Message')}"
            )

        job_id = resp.get("JobId")
        if not job_id:
            raise RuntimeError(
                f"Hunyuan3D {action} returned no JobId: {data}"
            )

        if _span:
            _output: Dict[str, Any] = {
                "job_id": job_id,
                "estimated_credits": estimated_credits,
                "credit_breakdown": credit_breakdown,
            }
            _req_id = resp.get("RequestId", "")
            if _req_id:
                _output["x-request-id"] = _req_id
            _span.log_output(_output)
        return job_id, estimated_credits, credit_breakdown
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# API 调用: Query 3D Job 状态查询 (单次, 供轮询和 resync 共用)
# =============================================================================

async def check_hunyuan3d_job_status(
    secret_id: str,
    secret_key: str,
    job_id: str,
    action: str,
    region: str = HUNYUAN3D_API_REGION,
) -> Dict[str, Any]:
    """
    单次查询 Hunyuan3D 任务状态。

    Args:
        secret_id:  腾讯云 SecretId
        secret_key: 腾讯云 SecretKey
        job_id:     Submit 返回的 JobId
        action:     API 动作（QueryHunyuanTo3DProJob 或 QueryHunyuanTo3DRapidJob）
        region:     区域，默认 ap-guangzhou

    Returns:
        Response dict (包含 Status, ResultFile3Ds, Error 等字段)
        HTTP 错误或非匹配的 JobId 返回空 dict {}
    """
    body = {"JobId": job_id}
    payload_str = json.dumps(body, ensure_ascii=False)
    headers = _build_auth_headers(secret_id, secret_key, action, payload_str, region=region)
    try:
        async with shared_client() as client:
            response = await client.post(HUNYUAN3D_API_URL, content=payload_str, headers=headers)
            response.raise_for_status()
            data = response.json()
            resp = data.get("Response", {})
            if "Error" in resp:
                err = resp["Error"]
                raise RuntimeError(
                    f"Hunyuan3D {action} error "
                    f"(code={err.get('Code')}): {err.get('Message')}"
                )
            return resp
    except Exception as exc:
        logger.warning(f"Hunyuan3D {action} query error for {job_id}: {exc}")
        return {}


async def check_any_hunyuan3d_job_status(
    secret_id: str,
    secret_key: str,
    job_id: str,
    model: str = "",
    region: str = HUNYUAN3D_API_REGION,
) -> Dict[str, Any]:
    """
    查询 Hunyuan3D Job 状态。

    如果提供了 model 参数，直接使用对应的 action 查询。
    否则依次尝试 Rapid、Pro、Part。

    返回匹配到的 Response dict，匹配不到返回空 dict。
    """
    if model:
        if _is_reduce_face_model(model):
            action = "QueryReduceFaceJob"
        elif _is_part_model(model):
            action = "QueryHunyuan3DPartJob"
        elif _is_pro_model(model):
            action = "QueryHunyuanTo3DProJob"
        else:
            action = "QueryHunyuanTo3DRapidJob"
        resp = await check_hunyuan3d_job_status(secret_id, secret_key, job_id, action, region=region)
        if resp:
            return resp

    for action in ("QueryHunyuanTo3DRapidJob", "QueryHunyuanTo3DProJob", "QueryHunyuan3DPartJob", "QueryReduceFaceJob"):
        resp = await check_hunyuan3d_job_status(secret_id, secret_key, job_id, action, region=region)
        if resp:
            return resp
    return {}


# =============================================================================
# API 调用: Query 3D Job (轮询)
# =============================================================================

async def _poll_3d_job(
    secret_id: str,
    secret_key: str,
    job_id: str,
    model: str,
    estimated_credits: int = 0,
    region: str = HUNYUAN3D_API_REGION,
    poll_timeout: Optional[int] = None,
    tracer: Any = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Poll the 3D job until it finishes, then extract result files and credits.

    For Rapid models: QueryHunyuanTo3DRapidJob
    For Pro models:   QueryHunyuanTo3DProJob
    For Part models:  QueryHunyuan3DPartJob
    For ReduceFace models: QueryReduceFaceJob

    Args:
        secret_id:        腾讯云 SecretId
        secret_key:       腾讯云 SecretKey
        job_id:           Submit 返回的 JobId
        model:            模型名称
        estimated_credits: 预估积分消耗（Rapid/Part 模型无 API 返回值时使用）

    Returns:
        Tuple of (result_items, credits_consumed). For Pro models credits_consumed
        comes from ResultCreditConsumed; for Rapid/Part models falls back to
        estimated_credits.
        {"type": file_type, "url": ..., "preview_url": ...}

    Raises:
        RuntimeError: On task failure or timeout
    """
    is_pro = _is_pro_model(model)
    is_part = _is_part_model(model)
    is_reduce_face = _is_reduce_face_model(model)

    if is_reduce_face:
        action = "QueryReduceFaceJob"
    elif is_part:
        action = "QueryHunyuan3DPartJob"
    elif is_pro:
        action = "QueryHunyuanTo3DProJob"
    else:
        action = "QueryHunyuanTo3DRapidJob"
    max_wait = poll_timeout or _POLL_MAX_WAIT_S
    deadline = time.time() + max_wait

    _span = None
    if tracer:
        _span = tracer.start_child(job_id, model=job_id, provider_type="hunyuan", obs_type="span")
    _error: Optional[Exception] = None

    try:
        poll_count = 0
        while time.time() < deadline:
            resp = await check_hunyuan3d_job_status(secret_id, secret_key, job_id, action, region=region)
            if not resp:
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            status = resp.get("Status", "")
            poll_count += 1

            if _span:
                _span.log_output({"job_id": job_id, "status": status, "poll_count": poll_count})

            if status == STATUS_DONE:
                if tracer:
                    _done_span = tracer.start_child(
                        f"{job_id}-done", model=job_id,
                        provider_type="hunyuan", input_data=resp, obs_type="span",
                    )
                    if _done_span:
                        _done_span.log_input(resp)
                        _done_span.end()
                error_code = resp.get("ErrorCode", "")
                if error_code:
                    raise RuntimeError(
                        f"Hunyuan3D job {job_id} failed: "
                        f"ErrorCode={error_code}, "
                        f"ErrorMessage={resp.get('ErrorMessage', '')}"
                    )

                result_files = resp.get("ResultFile3Ds") or []
                items: List[Dict[str, Any]] = []
                for f in result_files:
                    items.append({
                        "type": f.get("Type", "OBJ"),
                        "url": f.get("Url", ""),
                        "preview_url": f.get("PreviewImageUrl", ""),
                    })

                if not items:
                    raise RuntimeError(
                        f"Hunyuan3D job {job_id} finished but no ResultFile3Ds found: "
                        f"{json.dumps(resp, ensure_ascii=False)}"
                    )

                api_credits = int(resp.get("ResultCreditConsumed", 0) or 0)
                final_credits = api_credits if api_credits > 0 else estimated_credits
                return items, final_credits

            if status == STATUS_FAIL:
                if tracer:
                    _fail_span = tracer.start_child(
                        f"{job_id}-fail", model=job_id,
                        provider_type="hunyuan", input_data=resp, obs_type="span",
                    )
                    if _fail_span:
                        _fail_span.log_input(resp)
                        _fail_span.end(error=RuntimeError(
                            f"Hunyuan3D job {job_id} failed with status={status}: "
                            f"ErrorCode={resp.get('ErrorCode', '')}, "
                            f"ErrorMessage={resp.get('ErrorMessage', '')}"
                        ))
                raise RuntimeError(
                    f"Hunyuan3D job {job_id} failed with status={status}: "
                    f"ErrorCode={resp.get('ErrorCode', '')}, "
                    f"ErrorMessage={resp.get('ErrorMessage', '')}"
                )

            await asyncio.sleep(_POLL_INTERVAL_S)

        raise RuntimeError(
            f"Hunyuan3D job {job_id} timed out after {max_wait}s"
        )
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# 辅助: 从消息中提取图片 URL / Base64 和文本
# =============================================================================

def _extract_inputs(
    messages,
) -> Tuple[Optional[str], Optional[str], str, List[Dict[str, str]], Optional[str]]:
    """Extract image URL, image base64, text prompt, multi-view images, and file URL.

    Examines the last user message for image and file content blocks.  Blocks with a
    ``view`` attribute are classified as 3D multi-view images: ``front`` becomes
    the primary image, ``up`` / ``down`` are mapped to ``top`` / ``bottom``,
    and remaining views become multi-view entries.

    Returns:
        (image_url, image_base64, text_prompt, multi_view_images, file_url)
    """
    VIEW_MAP = {"up": "top", "down": "bottom"}

    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    file_url: Optional[str] = None
    text_prompt = ""
    multi_view_images: List[Dict[str, str]] = []

    for msg in reversed(messages):
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role != "user":
            continue

        if isinstance(msg.content, list):
            text_parts = []
            for block in msg.content:
                if not hasattr(block, "type"):
                    continue

                view = getattr(block, "view", None) or ""

                if block.type == ContentType.IMAGE_URL and block.url:
                    if view:
                        mapped = VIEW_MAP.get(view, view)
                        if view == "front":
                            if not image_url:
                                image_url = block.url
                        elif mapped:
                            multi_view_images.append({"image_url": block.url, "view_type": mapped})
                    elif not image_url:
                        image_url = block.url
                elif block.type == ContentType.IMAGE_BASE64 and block.data:
                    if view:
                        mapped = VIEW_MAP.get(view, view)
                        if view == "front":
                            if not image_base64 and not image_url:
                                image_base64 = block.data
                        elif mapped:
                            multi_view_images.append({"image_base64": block.data, "view_type": mapped})
                    elif not image_base64 and not image_url:
                        image_base64 = block.data
                elif block.type == ContentType.FILE_URL and block.url:
                    if not file_url:
                        file_url = block.url
                elif hasattr(block, "text") and block.text:
                    text_parts.append(block.text)
            text_prompt = " ".join(text_parts).strip()
        elif isinstance(msg.content, str):
            text_prompt = msg.content.strip()
        break

    return image_url, image_base64, text_prompt, multi_view_images, file_url


def _extract_file_type_from_url(url: str) -> Optional[str]:
    """Extract a 3D file type from a URL by inspecting its file extension.

    Recognised extensions: OBJ, FBX, GLB, STL, USDZ, MP4, GLTF, PLY, ABC, BLEND.

    Returns the uppercased extension (e.g. ``"FBX"``) or ``None`` when no
    recognisable 3D extension is found.
    """
    _KNOWN = frozenset({"OBJ", "FBX", "GLB", "STL", "USDZ", "MP4", "GLTF", "PLY", "ABC", "BLEND"})

    # Strip query string and fragment
    path = url.split("?")[0].split("#")[0]
    # Get the last path segment
    filename = path.rstrip("/").rsplit("/", 1)[-1]
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].upper()
        if ext in _KNOWN:
            return ext
    return None


# =============================================================================
# 主入口: 执行 3D 生成
# =============================================================================

async def execute_hunyuan3d_generation(
    api_key: str,
    model: str,
    messages,
    metadata: Dict[str, Any],
    region: str = HUNYUAN3D_API_REGION,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute Hunyuan 3D generation and return a ChatResponse.

    API Version: 2025-05-13

    Extracts image URL / base64 / text prompt from the last user message
    (or file URL / type for Part / ReduceFace models),
    submits the 3D generation job, polls until done, and returns the result as a
    JSON-encoded list of 3d_generation_call content items in the message
    content — compatible with the Responses API adapter format.

    Args:
        api_key:  "SecretId:SecretKey" credential string
        model:    Model identifier, e.g. "hunyuan-3d-rapid", "hunyuan-3d-pro",
                  or "hunyuan-3d-1.5-part"
        messages: List of Message objects from the ChatRequest
        metadata: ChatRequest.metadata dict (carries 3d generation params)
        region:   Tencent Cloud region

    Returns:
        ChatResponse with 3d_generation_call items in message content

    Raises:
        RuntimeError: On API error or task failure
    """
    secret_id, secret_key = _parse_api_key(api_key)
    is_part = _is_part_model(model)
    is_reduce_face = _is_reduce_face_model(model)

    # Extract generation parameters from metadata
    enable_pbr: bool = bool(metadata.get("enable_pbr", metadata.get("pbr", False)))
    result_format: str = str(metadata.get("result_format", metadata.get("output_format") or "OBJ"))
    enable_geometry: bool = bool(metadata.get("enable_geometry", False))

    # Pro-only params
    face_count_raw = metadata.get("face_count")
    face_count: Optional[int] = int(face_count_raw) if face_count_raw is not None else None
    generate_type: Optional[str] = metadata.get("generate_type") or None
    polygon_type: Optional[str] = metadata.get("polygon_type") or None

    # ReduceFace-only params
    face_level: Optional[str] = metadata.get("face_level") or None

    # Geometry 不支持 OBJ 格式，默认改为 GLB
    if generate_type == "Geometry" and result_format.upper() == "OBJ":
        result_format = "GLB"

    if is_reduce_face:
        # ReduceFace models take a 3D file as input.  The file URL is
        # extracted from FILE_URL content blocks in the last user message.
        _, _, text_prompt, _, file_url = _extract_inputs(messages)

        if not file_url:
            raise RuntimeError(
                "Hunyuan 3D ReduceFace: no file URL found in messages"
            )

        # Determine file_type from URL extension, defaulting to "OBJ"
        file_type = _extract_file_type_from_url(file_url) or "OBJ"

        image_url = None
        image_base64 = None
        multi_view_images = None
    elif is_part:
        # Part models take a 3D file (e.g. FBX) as input.  The file URL is
        # extracted from FILE_URL content blocks in the last user message.
        _, _, text_prompt, _, file_url = _extract_inputs(messages)

        if not file_url:
            raise RuntimeError(
                "Hunyuan 3D Part generation: no file URL found in messages"
            )

        # Determine file_type from URL extension, defaulting to "FBX"
        file_type = _extract_file_type_from_url(file_url) or "FBX"

        image_url = None
        image_base64 = None
        multi_view_images = None
    else:
        # Extract all inputs (images, text, multi-view) from messages
        image_url, image_base64, text_prompt, multi_view_images, _ = _extract_inputs(messages)

        if not multi_view_images and not image_url and not image_base64 and not text_prompt:
            raise RuntimeError(
                "Hunyuan 3D generation: no image URL, image base64, multi-view images, "
                "or text prompt found in user messages / tool parameters"
            )
        file_url = None
        file_type = "FBX"

    # ── Tracing ────────────────────────────────────────────────────────────
    _request_data: Dict[str, Any] = {"model": model, "prompt": text_prompt}
    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="hunyuan", input_data=_request_data)
        if _child_span:
            _child_span.log_input(_request_data)
    _trace_error: Optional[Exception] = None

    # Extract credit rules from model's output_pricing config
    _credit_rules = (
        metadata.get("output_pricing", {}).get("3d", {}).get("credits")
        if isinstance(metadata.get("output_pricing"), dict) else None
    )

    try:
        # Submit 3D job
        async with shared_client() as client:
            job_id, estimated_credits, _credit_breakdown = await _submit_3d_job(
                client=client,
                secret_id=secret_id,
                secret_key=secret_key,
                model=model,
                image_url=image_url,
                image_base64=image_base64,
                prompt=text_prompt if not image_url and not image_base64 and not multi_view_images else None,
                enable_pbr=enable_pbr,
                result_format=result_format,
                enable_geometry=enable_geometry,
                multi_view_images=multi_view_images,
                face_count=face_count,
                generate_type=generate_type,
                polygon_type=polygon_type,
                file_url=file_url,
                file_type=file_type,
                face_level=face_level,
                region=region,
                credit_rules=_credit_rules,
                tracer=_child_span,
            )

        hook = metadata.get('_on_task_created')
        if hook:
            hook(job_id)

        # Poll for result
        result_items, credits_consumed = await _poll_3d_job(
            secret_id, secret_key, job_id, model,
            estimated_credits=estimated_credits,
            region=region, poll_timeout=metadata.get("timeout"), tracer=_child_span,
        )

        if _child_span:
            _child_span.log_output({
                "job_id": job_id,
                "result_count": len(result_items),
                "credits_consumed": credits_consumed,
                "estimated_credits": estimated_credits,
                "credit_breakdown": _credit_breakdown,
                "status": "succeeded",
            })
    except Exception as e:
        _trace_error = e
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)

    # Wrap in the 3d_generation_call response structure
    output_items = [
        {
            "type": "3d_generation_call",
            "id": f"{job_id}-{i}" if i > 0 else job_id,
            "status": "completed",
            "content": [
                {
                    "type": item["type"],
                    "url": item["url"],
                    "preview_url": item.get("preview_url", ""),
                }
            ],
        }
        for i, item in enumerate(result_items)
    ]

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(output_items, ensure_ascii=False),
    )

    return ChatResponse(
        id=gen_id("3d"),
        model=model,
        choices=[ChatChoice(
            index=0,
            message=message,
            finish_reason=FinishReason.STOP,
        )],
        usage=UsageInfo(
            prompt_tokens=0,
            completion_tokens=len(result_items),
            total_tokens=len(result_items),
            extra={"_task_id": job_id, "credits": credits_consumed, "credit_breakdown": _credit_breakdown},
        ),
        created=int(time.time()),
        provider="hunyuan",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

async def stream_3d_generation(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    """
    Execute Hunyuan 3D generation and yield StreamChunks.

    Hunyuan 3D generation is asynchronous (submit job → poll result).
    This function wraps the synchronous call and emits the result as
    3d_generation_call SSE events via raw_sse_passthrough — identical to
    the pattern used by image/video generation providers.

    SSE event sequence:
    1. Role marker chunk (delta_role="assistant") → triggers format_stream_start
    2. response.output_item.added  (status=generating)
    3. response.output_item.done   (status=completed, content=[...])
    4. response.completed

    Args:
        chat_fn: The non-streaming chat function (provider.chat)
        request: The chat request with 3D generation parameters
    """
    # Call the synchronous (polling) path to get the full result
    response = await chat_fn(request)
    response_id = response.id
    model = response.model

    # Parse 3D items list from the response content
    items: List[Dict[str, Any]] = []
    if response.choices and response.choices[0].message:
        msg = response.choices[0].message
        raw = (
            msg.content
            if isinstance(msg.content, str)
            else (msg.get_text_content() or "[]")
        )
        try:
            items = json_loads(raw) if isinstance(raw, str) else []
        except (json.JSONDecodeError, TypeError):
            items = []

    # Role marker — triggers format_stream_start in the Responses adapter
    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    # Emit one 3d_generation_call item per result
    for i, item in enumerate(items):
        call_id = item.get("id", f"{response_id}-{i}" if i > 0 else response_id)
        content = item.get("content", [])
        output_index = i

        item_added = {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "type": "3d_generation_call",
                "id": call_id,
                "status": "generating",
                "content": [],
            },
        }
        item_done = {
            "type": "response.output_item.done",
            "output_index": output_index,
            "item": {
                "type": "3d_generation_call",
                "id": call_id,
                "status": "completed",
                "content": content,
            },
        }

        chunk = StreamChunk(
            id=response_id,
            model=model,
            event_type=StreamEventType.CONTENT_DELTA,
        )
        chunk.raw_sse_passthrough = [
            f"event: response.output_item.added\ndata: {json.dumps(item_added, ensure_ascii=False)}\n\n",
            f"event: response.output_item.done\ndata: {json.dumps(item_done, ensure_ascii=False)}\n\n",
        ]
        yield chunk

    # Build the completed response payload
    usage_dict: Dict[str, Any] = {}
    if response.usage:
        usage_dict = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    output_items_summary = [
        {
            "type": "3d_generation_call",
            "id": item.get("id", f"{response_id}-{i}" if i > 0 else response_id),
            "status": "completed",
            "content": item.get("content", []),
        }
        for i, item in enumerate(items)
    ]
    completed_response = {
        "id": response_id,
        "object": "response",
        "status": "completed",
        "model": model,
        "output": output_items_summary,
        "usage": {
            "input_tokens": usage_dict.get("prompt_tokens", 0),
            "output_tokens": usage_dict.get("completion_tokens", 0),
            "total_tokens": usage_dict.get("total_tokens", 0),
        },
    }
    completed_event = {
        "type": "response.completed",
        "response": completed_response,
    }

    finish_chunk = StreamChunk(
        id=response_id,
        model=model,
        event_type=StreamEventType.CONTENT_DELTA,
        created=response.created,
    )
    finish_chunk.raw_sse_passthrough = [
        f"event: response.completed\ndata: {json.dumps(completed_event, ensure_ascii=False)}\n\n",
    ]
    yield finish_chunk
