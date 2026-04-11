"""
混元 3D 生成模块 (Hunyuan 3D Generation)

通过混元 3D 生成 API 从图片或文本生成 3D 模型，兼容 /v1/responses 3d_generation 工具。

流程：
1. 发起请求:
   - Rapid 模型: POST ai3d.tencentcloudapi.com  X-TC-Action: SubmitHunyuanTo3DRapidJob
   - Pro   模型: POST ai3d.tencentcloudapi.com  X-TC-Action: SubmitHunyuanTo3DProJob
2. 轮询结果:
   - Rapid 模型: POST ai3d.tencentcloudapi.com  X-TC-Action: QueryHunyuanTo3DRapidJob
   - Pro   模型: POST ai3d.tencentcloudapi.com  X-TC-Action: QueryHunyuanTo3DProJob
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
from typing import Any, Dict, Generator, List, Optional, Tuple

import httpx

from app.abstraction.chat import (
    ChatChoice,
    ChatRequest,
    ChatResponse,
    FinishReason,
    UsageInfo,
)
from app.abstraction.messages import Message, MessageRole, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id


# =============================================================================
# 常量
# =============================================================================

HUNYUAN3D_API_HOST = "ai3d.tencentcloudapi.com"
HUNYUAN3D_API_URL = f"https://{HUNYUAN3D_API_HOST}/"
HUNYUAN3D_API_VERSION = "2025-05-13"
HUNYUAN3D_API_REGION = "ap-guangzhou"

# 轮询配置
_POLL_INTERVAL_S = 3.0   # 每次轮询间隔（秒）
_POLL_MAX_WAIT_S = 600   # 最大等待时间（秒）

# Rapid 模型标识
_RAPID_MODELS = {"hunyuan-3d-rapid", "hy-3d-express"}

# Pro 模型与 API Model 参数的映射
# key: 模型名前缀（小写），value: API 中 Model 字段的值（None 表示不传）
_PRO_MODEL_MAP: Dict[str, Optional[str]] = {
    "hunyuan-3d-3.1-pro": "3.1",
    "hunyuan-3d-3.0-pro": "3.0",
    "hy-3d-3.0":          "3.1",   # hy-3d-3.0 → API Model=3.1
    "hy-3d-3.1":          "3.0",   # hy-3d-3.1 → API Model=3.0
    "hunyuan-3d-pro":     None,    # 旧 Pro 模型，不传 Model 字段
}


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

    A model is Pro if it is NOT in the known Rapid set.
    All new hy-3d-* models (except hy-3d-express) default to Pro.
    """
    return model.lower() not in _RAPID_MODELS


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

def _submit_3d_job(
    client: httpx.Client,
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
    region: str = HUNYUAN3D_API_REGION,
) -> str:
    """
    Submit a Hunyuan 3D generation job and return the JobId.

    API Version: 2025-05-13
    For Rapid models: SubmitHunyuanTo3DRapidJob
    For Pro models:   SubmitHunyuanTo3DProJob

    Args:
        client:            httpx client
        secret_id:         腾讯云 SecretId
        secret_key:        腾讯云 SecretKey
        model:             模型名称，用于区分 Rapid / Pro
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
        region:            API 区域

    Returns:
        JobId string

    Raises:
        RuntimeError: On API error
    """
    is_pro = _is_pro_model(model)
    action = "SubmitHunyuanTo3DProJob" if is_pro else "SubmitHunyuanTo3DRapidJob"

    body: Dict[str, Any] = {}

    # Pro-only: Model version field (3.0 / 3.1)
    if is_pro:
        api_model_version = _get_api_model_version(model)
        if api_model_version:
            body["Model"] = api_model_version

    # Input handling:
    # - Pro + multi_view_images: set MultiViewImages for angle views.
    #   Additionally, if a primary image (without view) is provided, set ImageUrl/ImageBase64.
    # - Otherwise: exactly one of ImageUrl, ImageBase64, or Prompt.
    if is_pro and multi_view_images:
        mv_list = []
        for img in multi_view_images:
            entry: Dict[str, str] = {}
            view = img.get("view_type") or img.get("ViewType") or img.get("view") or ""
            if view:
                entry["ViewType"] = view
            img_url = img.get("image_url") or img.get("ViewImageUrl") or img.get("url") or ""
            if img_url:
                entry["ViewImageUrl"] = img_url
            img_b64 = img.get("image_base64") or img.get("ViewImageBase64") or ""
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
    if result_format:
        body["ResultFormat"] = result_format
    if enable_pbr:
        body["EnablePBR"] = True
    if enable_geometry:
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

    print("\n" + "=" * 50, file=sys.stderr)
    print(f"[Hunyuan3D {action} Request]", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print(payload_str, file=sys.stderr)
    print("=" * 50 + "\n", file=sys.stderr)

    headers = _build_auth_headers(secret_id, secret_key, action, payload_str, region=region)
    response = client.post(HUNYUAN3D_API_URL, content=payload_str, headers=headers)
    response.raise_for_status()
    data = response.json()

    print("\n" + "=" * 50, file=sys.stderr)
    print(f"[Hunyuan3D {action} Response]", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)
    print("=" * 50 + "\n", file=sys.stderr)

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
    return job_id


# =============================================================================
# API 调用: Query 3D Job (轮询)
# =============================================================================

def _poll_3d_job(
    secret_id: str,
    secret_key: str,
    job_id: str,
    model: str,
    region: str = HUNYUAN3D_API_REGION,
) -> List[Dict[str, Any]]:
    """
    Poll the 3D job until it finishes, then extract result files.

    For Rapid models: QueryHunyuanTo3DRapidJob
    For Pro models:   QueryHunyuanTo3DProJob

    Args:
        secret_id:  腾讯云 SecretId
        secret_key: 腾讯云 SecretKey
        job_id:     Submit 返回的 JobId
        model:      模型名称

    Returns:
        List of 3d_generation_call content items, each with
        {"type": file_type, "url": ..., "preview_url": ...}

    Raises:
        RuntimeError: On task failure or timeout
    """
    is_pro = _is_pro_model(model)
    action = "QueryHunyuanTo3DProJob" if is_pro else "QueryHunyuanTo3DRapidJob"
    deadline = time.time() + _POLL_MAX_WAIT_S

    with httpx.Client(timeout=60) as client:
        while time.time() < deadline:
            body = {"JobId": job_id}
            payload_str = json.dumps(body, ensure_ascii=False)
            headers = _build_auth_headers(secret_id, secret_key, action, payload_str, region=region)

            response = client.post(HUNYUAN3D_API_URL, content=payload_str, headers=headers)
            response.raise_for_status()
            data = response.json()

            resp = data.get("Response", {})
            if "Error" in resp:
                err = resp["Error"]
                raise RuntimeError(
                    f"Hunyuan3D {action} error "
                    f"(code={err.get('Code')}): {err.get('Message')}"
                )

            status = resp.get("Status", "")
            print(
                f"[Hunyuan3D] Job {job_id} status={status}",
                file=sys.stderr,
            )

            if status == "DONE":
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

                return items

            if status in ("FAILED", "FAIL", "ERROR"):
                raise RuntimeError(
                    f"Hunyuan3D job {job_id} failed with status={status}: "
                    f"ErrorCode={resp.get('ErrorCode', '')}, "
                    f"ErrorMessage={resp.get('ErrorMessage', '')}"
                )

            time.sleep(_POLL_INTERVAL_S)

    raise RuntimeError(
        f"Hunyuan3D job {job_id} timed out after {_POLL_MAX_WAIT_S}s"
    )


# =============================================================================
# 辅助: 从消息中提取图片 URL / Base64 和文本
# =============================================================================

def _extract_inputs(messages) -> Tuple[Optional[str], Optional[str], str]:
    """
    Extract image URL, image base64, and text prompt from the last user message.

    API Version: 2025-05-13
    ImageBase64、ImageUrl and Prompt are mutually exclusive — exactly one
    must be provided.

    Returns:
        (image_url, image_base64, text_prompt)
        Only one of image_url / image_base64 will be non-None.
        text_prompt is returned (non-empty) only when neither image field is set.
    """
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    text_prompt = ""

    for msg in reversed(messages):
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role != "user":
            continue

        if isinstance(msg.content, list):
            text_parts = []
            for block in msg.content:
                if not hasattr(block, "type"):
                    continue
                if block.type == ContentType.IMAGE_URL and block.url and not image_url:
                    image_url = block.url
                elif block.type == ContentType.IMAGE_BASE64 and block.data and not image_base64:
                    image_base64 = block.data
                elif hasattr(block, "text") and block.text:
                    text_parts.append(block.text)
            text_prompt = " ".join(text_parts).strip()
        elif isinstance(msg.content, str):
            text_prompt = msg.content.strip()
        break

    return image_url, image_base64, text_prompt


# =============================================================================
# 主入口: 执行 3D 生成
# =============================================================================

def execute_hunyuan3d_generation(
    api_key: str,
    model: str,
    messages,
    metadata: Dict[str, Any],
    region: str = HUNYUAN3D_API_REGION,
) -> ChatResponse:
    """
    Execute Hunyuan 3D generation and return a ChatResponse.

    API Version: 2025-05-13

    Extracts image URL / base64 / text prompt from the last user message,
    submits the 3D generation job, polls until done, and returns the result as a
    JSON-encoded list of 3d_generation_call content items in the message
    content — compatible with the Responses API adapter format.

    Args:
        api_key:  "SecretId:SecretKey" credential string
        model:    Model identifier, e.g. "hunyuan-3d-rapid" or "hunyuan-3d-pro"
        messages: List of Message objects from the ChatRequest
        metadata: ChatRequest.metadata dict (carries 3d generation params)
        region:   Tencent Cloud region

    Returns:
        ChatResponse with 3d_generation_call items in message content

    Raises:
        RuntimeError: On API error or task failure
    """
    secret_id, secret_key = _parse_api_key(api_key)

    # Extract generation parameters from metadata
    enable_pbr: bool = bool(metadata.get("enable_pbr", metadata.get("pbr", False)))
    result_format: str = str(metadata.get("result_format", metadata.get("output_format") or "OBJ"))
    enable_geometry: bool = bool(metadata.get("enable_geometry", False))

    # Pro-only params
    multi_view_images: Optional[List[Dict[str, str]]] = metadata.get("multi_view_images") or None
    face_count_raw = metadata.get("face_count")
    face_count: Optional[int] = int(face_count_raw) if face_count_raw is not None else None
    generate_type: Optional[str] = metadata.get("generate_type") or None
    polygon_type: Optional[str] = metadata.get("polygon_type") or None

    # Extract inputs from messages (single image URL/base64 or text prompt)
    image_url, image_base64, text_prompt = _extract_inputs(messages)

    if not multi_view_images and not image_url and not image_base64 and not text_prompt:
        raise RuntimeError(
            "Hunyuan 3D generation: no image URL, image base64, multi-view images, "
            "or text prompt found in user messages / tool parameters"
        )

    # Submit 3D job
    with httpx.Client(timeout=60) as client:
        job_id = _submit_3d_job(
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
            region=region,
        )

    # Poll for result
    result_items = _poll_3d_job(secret_id, secret_key, job_id, model, region=region)

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
        ),
        created=int(time.time()),
        provider="hunyuan",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

def stream_3d_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
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
    response = chat_fn(request)
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
            items = json.loads(raw) if isinstance(raw, str) else []
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
