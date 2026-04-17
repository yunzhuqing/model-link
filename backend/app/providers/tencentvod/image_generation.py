"""
腾讯云点播图像生成模块 (TencentVOD Image Generation)

通过腾讯云点播 AI 图像生成 API 生成图像，兼容 /v1/responses image_generation 工具。

流程：
1. 发起请求: POST vod.tencentcloudapi.com  Action=CreateAigcImageTask
2. 轮询结果: POST vod.tencentcloudapi.com  Action=DescribeTaskDetail
   直到 Status == "FINISH"

认证方式：
腾讯云 VOD API 使用 TC3-HMAC-SHA256 签名。
api_key 字段应为 "SecretId:SecretKey" 格式。
SubAppId 存放于 extra_config["sub_app_id"]。

API 文档: https://cloud.tencent.com/document/product/266/73185
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
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id
from app.providers.image_size_utils import resolve_image_size


# =============================================================================
# 常量
# =============================================================================

TENCENTVOD_API_HOST = "vod.tencentcloudapi.com"
TENCENTVOD_API_URL = f"https://{TENCENTVOD_API_HOST}/"
TENCENTVOD_API_VERSION = "2018-07-17"
# VOD 是全球服务，但 TC3 签名仍需 region 字段，传 ap-guangzhou 即可
TENCENTVOD_API_REGION = "ap-guangzhou"

# 轮询配置
_POLL_INTERVAL_S = 2.0   # 每次轮询间隔（秒）
_POLL_MAX_WAIT_S = 300   # 最大等待时间（秒）


# =============================================================================
# 图像生成模型检测
# =============================================================================

# Known TencentVOD image generation model name prefixes (case-insensitive).
# Add new prefixes here when TencentVOD releases additional image models.
_TENCENTVOD_IMAGE_MODEL_PREFIXES = (
    "gem-",
    "mingmou-",
    "gemini-",   # Gemini image models routed via TencentVOD (model_name=GG)
    "hy-image-", # Hunyuan image models
)


def is_tencentvod_image_model(model: str) -> bool:
    """
    Check if the model is a TencentVOD image generation model.

    Matches model names whose prefix indicates a TencentVOD image generation
    model, e.g.:
      - GEM-2.5
      - GEM-3.0
      - Mingmou-4.0
      - Mingmou-5.0
      - gemini-2.5-flash-image
      - gemini-3-pro-image-preview
      - hy-image-v3.0

    Args:
        model: Model name (case-insensitive)

    Returns:
        True if the model is a TencentVOD image generation model
    """
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _TENCENTVOD_IMAGE_MODEL_PREFIXES)


def has_image_generation_tool(request: ChatRequest) -> bool:
    """
    Check if the request contains an ``image_generation`` tool via metadata.

    When the Responses API adapter parses an ``image_generation`` tool entry,
    it stores the parameters in ``request.metadata``.  The presence of
    image-generation metadata keys is the reliable signal.

    Args:
        request: The chat request to check

    Returns:
        True if the request was sent with an ``image_generation`` tool.
    """
    meta = request.metadata
    return any(k in meta for k in (
        "size", "number", "image_format", "response_format",
        "seed", "watermark", "aspect_ratio", "resolution",
    ))


# =============================================================================
# 辅助: 解析模型名称 / 版本
# =============================================================================

# Explicit lookup table: input model identifier (case-insensitive) →
# (TencentVOD ModelName, TencentVOD ModelVersion).
#
# Models with complex names (e.g. gemini-2.5-flash-image) cannot be parsed
# reliably by splitting on "-", so they are listed here explicitly.
# For models not in this table the legacy split-on-"-" heuristic is used as
# a fallback (suitable for simple names like "GEM-2.5", "Mingmou-4.0").
_MODEL_NAME_VERSION_MAP: Dict[str, Tuple[str, str]] = {
    # ── Gemini image models routed via TencentVOD ──────────────────────────
    "gemini-2.5-flash-image":          ("GG", "2.5"),
    "gemini-3-pro-image-preview":      ("GG", "3.0"),
    "gemini-3.1-flash-image-preview":  ("GG", "3.1"),
    # ── Hunyuan image models ───────────────────────────────────────────────
    "hy-image-v3.0":                   ("Hunyuan", "3.0"),
}


def _parse_model_name_version(model: str) -> Tuple[str, str]:
    """
    Derive TencentVOD ModelName and ModelVersion from a model identifier.

    First checks the explicit ``_MODEL_NAME_VERSION_MAP`` lookup table
    (case-insensitive).  If the model is not listed there, falls back to the
    legacy convention of splitting on the last "-" when the trailing segment
    looks like a version number (digits and dots only), e.g.:
      - "GEM-2.5"     → ("GEM", "2.5")
      - "Mingmou-4.0" → ("Mingmou", "4.0")

    If neither rule matches the whole string becomes ModelName and
    ModelVersion defaults to "latest".

    Explicit mappings:
      - gemini-2.5-flash-image         → ("GG", "2.5")
      - gemini-3-pro-image-preview      → ("GG", "3.0")
      - gemini-3.1-flash-image-preview  → ("GG", "3.1")
      - hy-image-v3.0                   → ("Hunyuan", "3.0")

    Args:
        model: Model identifier string

    Returns:
        (model_name, model_version) tuple
    """
    # 1. Explicit lookup (case-insensitive)
    key = model.lower().strip()
    if key in _MODEL_NAME_VERSION_MAP:
        return _MODEL_NAME_VERSION_MAP[key]

    # 2. Legacy heuristic: split on last "-" when suffix is a version number
    parts = model.rsplit("-", 1)
    if len(parts) == 2 and parts[1].replace(".", "").isdigit():
        return parts[0], parts[1]

    # 3. Fallback: treat the whole string as ModelName
    return model, "latest"


# =============================================================================
# TC3-HMAC-SHA256 认证
# =============================================================================

def _build_auth_headers(
    secret_id: str,
    secret_key: str,
    action: str,
    payload_str: str,
    region: str = TENCENTVOD_API_REGION,
) -> Dict[str, str]:
    """
    Build TC3-HMAC-SHA256 signed request headers for a TencentCloud API call.

    Reference:
    https://cloud.tencent.com/document/product/266/31754 (TC3 签名方法)

    Args:
        secret_id:   腾讯云 SecretId
        secret_key:  腾讯云 SecretKey
        action:      API 动作名称，如 "CreateAigcImageTask"
        payload_str: JSON 序列化后的请求体字符串
        region:      区域，默认 ap-guangzhou

    Returns:
        包含认证信息的请求头字典
    """
    algorithm = "TC3-HMAC-SHA256"
    service = "vod"
    host = TENCENTVOD_API_HOST
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
        "POST",          # HTTP method
        "/",             # Canonical URI
        "",              # Canonical query string (empty)
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
        "X-TC-Version": TENCENTVOD_API_VERSION,
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
            "TencentVOD image generation api_key must be in 'SecretId:SecretKey' format"
        )
    secret_id, secret_key = api_key.split(":", 1)
    return secret_id.strip(), secret_key.strip()


# =============================================================================
# API 调用: CreateAigcApiToken
# =============================================================================

def create_aigc_api_token(
    secret_id: str,
    secret_key: str,
    sub_app_id: Optional[int] = None,
) -> str:
    """
    Call CreateAigcApiToken and return the ApiToken.

    The ApiToken is a permanent key (no expiry) used to authenticate
    chat / completion requests to the TencentVOD AI text API.

    Args:
        secret_id:  腾讯云 SecretId (AK)
        secret_key: 腾讯云 SecretKey (SK)
        sub_app_id: 点播子应用 ID（可选）

    Returns:
        ApiToken string

    Raises:
        RuntimeError: On API error
    """
    body: Dict[str, Any] = {}
    if sub_app_id is not None:
        body["SubAppId"] = sub_app_id

    payload_str = json.dumps(body, ensure_ascii=False)
    headers = _build_auth_headers(secret_id, secret_key, "CreateAigcApiToken", payload_str)

    with httpx.Client(timeout=60) as client:
        response = client.post(TENCENTVOD_API_URL, content=payload_str, headers=headers)
        response.raise_for_status()
        data = response.json()

    resp = data.get("Response", {})
    if "Error" in resp:
        err = resp["Error"]
        raise RuntimeError(
            f"TencentVOD CreateAigcApiToken error "
            f"(code={err.get('Code')}): {err.get('Message')}"
        )

    api_token = resp.get("ApiToken")
    if not api_token:
        raise RuntimeError(
            f"TencentVOD CreateAigcApiToken returned no ApiToken: {data}"
        )
    return api_token


# =============================================================================
# API 调用: CreateAigcImageTask
# =============================================================================

def _create_aigc_image_task(
    client: httpx.Client,
    secret_id: str,
    secret_key: str,
    sub_app_id: Optional[int],
    model_name: str,
    model_version: str,
    prompt: str,
    negative_prompt: str = "",
    aspect_ratio: str = "",
    resolution: str = "",
    file_ids: Optional[List[str]] = None,
    file_urls: Optional[List[str]] = None,
    session_id: str = "",
    enhance_prompt: str = "",
) -> str:
    """
    Call CreateAigcImageTask and return the TaskId.

    Args:
        client:          httpx client
        secret_id:       腾讯云 SecretId
        secret_key:      腾讯云 SecretKey
        sub_app_id:      点播子应用 ID（可选）
        model_name:      模型名称，如 "GEM"
        model_version:   模型版本，如 "2.5"
        prompt:          正向 Prompt
        negative_prompt: 负向 Prompt
        aspect_ratio:    输出宽高比，如 "16:9"、"1:1"
        resolution:      输出分辨率，如 "1024x1024"
        file_ids:        参考图片的 FileId 列表
        file_urls:       参考图片的 URL 列表
        session_id:      会话 ID（可选）
        enhance_prompt:  是否增强 Prompt（"Enabled" | ""）

    Returns:
        TaskId string

    Raises:
        RuntimeError: On API error
    """
    body: Dict[str, Any] = {
        "ModelName": model_name,
        "ModelVersion": model_version,
        "Prompt": prompt,
    }

    if sub_app_id is not None:
        body["SubAppId"] = sub_app_id

    if negative_prompt:
        body["NegativePrompt"] = negative_prompt

    if enhance_prompt:
        body["EnhancePrompt"] = enhance_prompt

    if session_id:
        body["SessionId"] = session_id

    # 参考图片
    file_infos: List[Dict[str, Any]] = []
    for fid in (file_ids or []):
        file_infos.append({"FileId": fid})
    for url in (file_urls or []):
        file_infos.append({"Type": "Url", "Url": url})
    if file_infos:
        body["FileInfos"] = file_infos

    # 输出配置
    output_config: Dict[str, Any] = {
        "StorageMode": "Temporary",
    }
    if aspect_ratio:
        output_config["AspectRatio"] = aspect_ratio
    if resolution:
        output_config["Resolution"] = resolution
    body["OutputConfig"] = output_config

    payload_str = json.dumps(body, ensure_ascii=False)

    print("\n" + "=" * 50, file=sys.stderr)
    print("[TencentVOD CreateAigcImageTask Request]", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print(payload_str, file=sys.stderr)
    print("=" * 50 + "\n", file=sys.stderr)

    headers = _build_auth_headers(secret_id, secret_key, "CreateAigcImageTask", payload_str)

    response = client.post(TENCENTVOD_API_URL, content=payload_str, headers=headers)
    response.raise_for_status()
    data = response.json()

    print("\n" + "=" * 50, file=sys.stderr)
    print("[TencentVOD CreateAigcImageTask Response]", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)
    print("=" * 50 + "\n", file=sys.stderr)

    resp = data.get("Response", {})
    if "Error" in resp:
        err = resp["Error"]
        raise RuntimeError(
            f"TencentVOD CreateAigcImageTask error "
            f"(code={err.get('Code')}): {err.get('Message')}"
        )

    task_id = resp.get("TaskId")
    if not task_id:
        raise RuntimeError(
            f"TencentVOD CreateAigcImageTask returned no TaskId: {data}"
        )
    return task_id


# =============================================================================
# API 调用: DescribeTaskDetail (轮询)
# =============================================================================

def _describe_task_detail(
    client: httpx.Client,
    secret_id: str,
    secret_key: str,
    task_id: str,
    sub_app_id: Optional[int],
) -> Dict[str, Any]:
    """
    Call DescribeTaskDetail for the given TaskId.

    Args:
        client:     httpx client
        secret_id:  腾讯云 SecretId
        secret_key: 腾讯云 SecretKey
        task_id:    任务 ID
        sub_app_id: 点播子应用 ID（可选）

    Returns:
        Full Response dict from the API

    Raises:
        RuntimeError: On API error
    """
    body: Dict[str, Any] = {"TaskId": task_id}
    if sub_app_id is not None:
        body["SubAppId"] = sub_app_id

    payload_str = json.dumps(body, ensure_ascii=False)
    headers = _build_auth_headers(secret_id, secret_key, "DescribeTaskDetail", payload_str)

    response = client.post(TENCENTVOD_API_URL, content=payload_str, headers=headers)
    response.raise_for_status()
    data = response.json()

    resp = data.get("Response", {})
    if "Error" in resp:
        err = resp["Error"]
        raise RuntimeError(
            f"TencentVOD DescribeTaskDetail error "
            f"(code={err.get('Code')}): {err.get('Message')}"
        )
    return resp


def _poll_task(
    secret_id: str,
    secret_key: str,
    task_id: str,
    sub_app_id: Optional[int],
) -> List[Dict[str, Any]]:
    """
    Poll DescribeTaskDetail until the task finishes, then extract image URLs.

    Returns a list of image_generation_call items compatible with the
    Responses API adapter format.

    Args:
        secret_id:  腾讯云 SecretId
        secret_key: 腾讯云 SecretKey
        task_id:    CreateAigcImageTask 返回的 TaskId
        sub_app_id: 点播子应用 ID（可选）

    Returns:
        List of image_generation_call dicts

    Raises:
        RuntimeError: On task failure or timeout
    """
    deadline = time.time() + _POLL_MAX_WAIT_S

    with httpx.Client(timeout=60) as client:
        while time.time() < deadline:
            resp = _describe_task_detail(client, secret_id, secret_key, task_id, sub_app_id)

            # Extract the AigcImageTask sub-object
            aigc_task = resp.get("AigcImageTask") or {}
            status = resp.get("Status") or aigc_task.get("Status", "")

            print(
                f"[TencentVOD] Task {task_id} status={status}",
                file=sys.stderr,
            )

            if status == "FINISH":
                # Check for task-level error
                err_code = aigc_task.get("ErrCode", 0)
                if err_code != 0:
                    raise RuntimeError(
                        f"TencentVOD image task failed "
                        f"(ErrCode={err_code}): {aigc_task.get('Message', '')}"
                    )

                output = aigc_task.get("Output") or {}
                file_infos = output.get("FileInfos") or []
                image_items: List[Dict[str, Any]] = []
                for fi in file_infos:
                    url = fi.get("FileUrl", "")
                    if url:
                        image_items.append({
                            "type": "image_generation_call",
                            "status": "completed",
                            "result": url,
                        })
                return image_items

            if status in ("FAIL", "ABORTED"):
                raise RuntimeError(
                    f"TencentVOD image task {task_id} failed with status={status}"
                )

            time.sleep(_POLL_INTERVAL_S)

    raise RuntimeError(
        f"TencentVOD image task {task_id} timed out after {_POLL_MAX_WAIT_S}s"
    )


# =============================================================================
# 主入口: 执行图像生成
# =============================================================================

def execute_tencentvod_image_generation(
    api_key: str,
    model: str,
    messages,
    metadata: Dict[str, Any],
    sub_app_id: Optional[int] = None,
) -> ChatResponse:
    """
    Execute TencentVOD image generation and return a ChatResponse.

    Extracts the prompt from the last user message, derives ModelName/Version
    from the model identifier, calls CreateAigcImageTask, polls until done,
    and returns image URLs as image_generation_call items (JSON-encoded) in the
    message content — compatible with the Responses API adapter format used by
    Volcengine / Gemini / Bailian providers.

    Args:
        api_key:    "SecretId:SecretKey" credential string
        model:      Model identifier, e.g. "GEM-2.5" or "Mingmou-4.0"
        messages:   List of Message objects from the ChatRequest
        metadata:   ChatRequest.metadata dict (carries image generation params)
        sub_app_id: 点播子应用 ID（可选，也可通过 metadata["sub_app_id"] 传入）

    Returns:
        ChatResponse with image_generation_call items in message content

    Raises:
        RuntimeError: On API error or task failure
    """
    secret_id, secret_key = _parse_api_key(api_key)

    # Resolve sub_app_id: prefer metadata, then argument
    _sub_app = metadata.get("sub_app_id") or sub_app_id
    if _sub_app is not None:
        _sub_app = int(_sub_app)

    # Parse model name / version
    model_name, model_version = _parse_model_name_version(model)

    # Extract prompt and reference images from the last user message.
    # Reference images are passed as IMAGE_URL / IMAGE_BASE64 content blocks.
    prompt = ""
    negative_prompt = metadata.get("negative_prompt", "")
    msg_file_urls: List[str] = []   # image URLs extracted from message content
    msg_file_ids: List[str] = []    # file IDs (non-URL strings) from message content

    for msg in reversed(messages):
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role == "user":
            if isinstance(msg.content, str):
                prompt = msg.content
            elif isinstance(msg.content, list):
                text_parts = []
                for block in msg.content:
                    if isinstance(block, ContentBlock):
                        if block.type == ContentType.TEXT and block.text:
                            text_parts.append(block.text)
                        elif block.type == ContentType.IMAGE_URL and block.url:
                            if block.url.startswith("http"):
                                msg_file_urls.append(block.url)
                            else:
                                msg_file_ids.append(block.url)
                        elif block.type == ContentType.IMAGE_BASE64 and block.data:
                            # Base64 images cannot be sent as FileId/Url to TencentVOD;
                            # skip silently (or could upload to VOD first if needed).
                            pass
                    elif hasattr(block, "text") and block.text:
                        text_parts.append(block.text)
                prompt = " ".join(text_parts)
            break

    if not prompt:
        raise RuntimeError("TencentVOD image generation: no prompt found in user messages")

    # Resolve aspect_ratio and resolution from user-supplied metadata.
    # Priority (handled by resolve_image_size):
    #   1. metadata["resolution"] explicitly set (e.g. "1024x1024")
    #   2. metadata["aspect_ratio"] explicitly set (e.g. "16:9")
    #   3. metadata["size"]:
    #      a. "WxH"  → used as resolution, aspect_ratio derived from table
    #      b. "W:H"  → used as aspect_ratio, resolution derived from table
    #      c. "1K" / "2K" / "4K" / "512" → quality tier, look up resolution
    aspect_ratio, resolution = resolve_image_size(
        model=model,
        size=str(metadata.get("size", "") or ""),
        aspect_ratio=str(metadata.get("aspect_ratio", "") or ""),
        resolution=str(metadata.get("resolution", "") or ""),
    )

    # Reference images: merge from message content blocks (primary source)
    # and any legacy metadata entries.
    file_urls: List[str] = msg_file_urls[:]
    file_ids: List[str] = msg_file_ids[:]

    # Session id
    session_id = metadata.get("session_id", "")
    enhance_prompt = metadata.get("enhance_prompt", "")

    # Submit task
    with httpx.Client(timeout=60) as client:
        task_id = _create_aigc_image_task(
            client=client,
            secret_id=secret_id,
            secret_key=secret_key,
            sub_app_id=_sub_app,
            model_name=model_name,
            model_version=model_version,
            prompt=prompt,
            negative_prompt=negative_prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            file_ids=file_ids or None,
            file_urls=file_urls or None,
            session_id=session_id,
            enhance_prompt=enhance_prompt,
        )

    # Poll for result
    image_items = _poll_task(secret_id, secret_key, task_id, _sub_app)

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(image_items, ensure_ascii=False),
    )

    image_count = max(len(image_items), 1)

    return ChatResponse(
        id=gen_id("img"),
        model=model,
        choices=[ChatChoice(
            index=0,
            message=message,
            finish_reason=FinishReason.STOP,
        )],
        usage=UsageInfo(
            prompt_tokens=0,
            completion_tokens=image_count,
            total_tokens=image_count,
            extra={
                'output_image_number': image_count,
                'output_image_resolution': resolution or None,
                'output_image_aspect': aspect_ratio or None,
            },
        ),
        created=int(time.time()),
        provider="tencentvod",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

def stream_image_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    Execute TencentVOD image generation and yield StreamChunks.

    TencentVOD image generation is asynchronous (create task → poll result).
    This function wraps the synchronous call and emits the result as
    image_generation_call SSE events via raw_sse_passthrough — identical to
    the pattern used by Volcengine / Gemini / Bailian providers.

    SSE event sequence:
    1. Role marker chunk (delta_role="assistant") → triggers format_stream_start
    2. response.output_item.added  (status=generating)
    3. response.output_item.done   (status=completed, result=<image_url>)
    4. response.completed

    Args:
        chat_fn: The non-streaming chat function (provider.chat)
        request: The chat request with image generation parameters
    """
    # Call the synchronous (polling) path to get the full result
    response = chat_fn(request)
    response_id = response.id
    model = response.model

    # Parse images list from the response content
    images: List[Dict[str, Any]] = []
    if response.choices and response.choices[0].message:
        msg = response.choices[0].message
        raw = (
            msg.content
            if isinstance(msg.content, str)
            else (msg.get_text_content() or "[]")
        )
        try:
            images = json.loads(raw) if isinstance(raw, str) else []
        except (json.JSONDecodeError, TypeError):
            images = []

    # Role marker — triggers format_stream_start in the Responses adapter
    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    # Emit one image_generation_call item per image
    for i, img in enumerate(images):
        result = img.get("result", "")
        call_id = f"{response_id}-{i}" if i > 0 else response_id
        output_index = i

        item_added = {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "type": "image_generation_call",
                "id": call_id,
                "status": "generating",
                "result": None,
            },
        }
        item_done = {
            "type": "response.output_item.done",
            "output_index": output_index,
            "item": {
                "type": "image_generation_call",
                "id": call_id,
                "status": "completed",
                "result": result,
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

    output_items = [
        {
            "type": "image_generation_call",
            "id": (f"{response_id}-{i}" if i > 0 else response_id),
            "status": "completed",
            "result": img.get("result", ""),
        }
        for i, img in enumerate(images)
    ]
    completed_response = {
        "id": response_id,
        "object": "response",
        "status": "completed",
        "model": model,
        "output": output_items,
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
