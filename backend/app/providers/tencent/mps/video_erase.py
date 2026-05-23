"""
腾讯云 MPS 智能擦除模块 (Smart Erase / Video Erase)

通过腾讯云 MPS ProcessMedia API 实现视频智能擦除（去字幕、去水印等），
兼容 /v1/responses video_erase 工具。

流程：
1. 发起请求: POST mps.tencentcloudapi.com  Action=ProcessMedia
2. 轮询结果: POST mps.tencentcloudapi.com  Action=DescribeTaskDetail
   直到 Status == "FINISH"

认证方式：
腾讯云 MPS API 使用 TC3-HMAC-SHA256 签名。
api_key 字段应为 "SecretId:SecretKey" 格式。

/v1/responses 工具请求示例:
{
    "type": "video_erase",
    "template_id": "",
    "model": "mps-erase-subtitle-standard",
    "erase_type": "subtitle",
    "erase_method": "auto|custom",
    "area": [
        {"begin": 0, "end": 500, "unit": 1, "left_top_x": 0, "left_top_y": 0, "right_bottom_x": 0.9999, "right_bottom_y": 0.9999}
    ]
}

API 文档: https://cloud.tencent.com/document/product/862/
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, AsyncGenerator, List, Optional, Tuple
import asyncio

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
from app.storage import get_storage_backend
from app.utils import gen_id, json_loads

# =============================================================================
# MPS API 常量
# =============================================================================

MPS_API_HOST = "mps.tencentcloudapi.com"
MPS_API_URL = f"https://{MPS_API_HOST}/"
MPS_API_VERSION = "2019-06-12"
MPS_API_REGION = "ap-guangzhou"
MPS_SERVICE = "mps"

_POLL_INTERVAL_S = 2.0
_POLL_MAX_WAIT_S = 600  # MPS tasks can take longer than VOD


# =============================================================================
# 模型检测
# =============================================================================

# Models that are handled by the MPS video erase provider.
_TENCENT_MPS_VIDEO_ERASE_MODELS = (
    "erase_",
    "mps-erase-",
    "mps-smarterase",
)


def is_mps_video_erase_model(model: str) -> bool:
    """Check if the model is an MPS video erase model."""
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _TENCENT_MPS_VIDEO_ERASE_MODELS)


def has_video_erase_tool(request: ChatRequest) -> bool:
    """Check if the request was sent with a ``video_erase`` tool."""
    return bool(request.metadata.get("_video_erase"))


# =============================================================================
# 模型名称解析
# =============================================================================

def _parse_erase_model(model: str) -> Dict[str, str]:
    """
    Parse the erase model identifier into its components.

    Example:
        "mps-erase-subtitle-standard" → {"erase_type": "subtitle", "subtitle_model": "standard"}

    Returns a dict with keys matching MPS API parameter names.
    """
    result: Dict[str, str] = {}

    key = model.lower().strip()
    # New format: mps-erase-<erase_type>-<subtitle_model>
    if key.startswith("mps-erase-"):
        rest = key[len("mps-erase-"):]
        parts = rest.split("-", 1)
        if len(parts) >= 1:
            result["erase_type"] = parts[0]
        if len(parts) >= 2:
            result["subtitle_model"] = parts[1]
    elif key.startswith("erase_"):
        parts = key.split("_")
        # Format: erase_<erase_type>_<model>
        if len(parts) >= 3:
            result["erase_type"] = parts[1]
            result["subtitle_model"] = "_".join(parts[2:])

    return result


# =============================================================================
# TC3-HMAC-SHA256 认证 (MPS)
# =============================================================================

def _build_mps_auth_headers(
    secret_id: str,
    secret_key: str,
    action: str,
    payload_str: str,
    region: str = MPS_API_REGION,
) -> Dict[str, str]:
    """Build TC3-HMAC-SHA256 signed headers for MPS API calls."""
    algorithm = "TC3-HMAC-SHA256"
    service = MPS_SERVICE
    host = MPS_API_HOST
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
        "X-TC-Version": MPS_API_VERSION,
        "X-TC-Region": region,
        "X-TC-Action": action,
    }


def _parse_api_key(api_key: str) -> Tuple[str, str]:
    """Parse SecretId and SecretKey from api_key string (format: SecretId:SecretKey)."""
    if ":" not in api_key:
        raise ValueError(
            "MPS video erase api_key must be in 'SecretId:SecretKey' format"
        )
    secret_id, secret_key = api_key.split(":", 1)
    return secret_id.strip(), secret_key.strip()


# =============================================================================
# API: ProcessMedia (create erase task)
# =============================================================================

async def _create_process_media_task(
    client: httpx.AsyncClient,
    secret_id: str,
    secret_key: str,
    input_url: str,
    output_bucket: str,
    output_region: str,
    output_dir: str,
    erase_type: str,
    subtitle_model: str,
    erase_method: str,
    custom_areas: Optional[List[Dict[str, Any]]],
    definition: int = 303,
    tracer: Any = None,
) -> str:
    """Call MPS ProcessMedia and return the TaskId."""
    body: Dict[str, Any] = {
        "InputInfo": {
            "Type": "URL",
            "UrlInputInfo": {
                "Url": input_url,
            },
        },
        "OutputStorage": {
            "Type": "COS",
            "CosOutputStorage": {
                "Bucket": output_bucket,
                "Region": output_region,
            },
        },
        "OutputDir": output_dir,
        "SmartEraseTask": {
            "Definition": definition,
            "OverrideParameter": {
                "EraseType": erase_type,
            },
        },
    }

    # Build erase config based on erase_type
    erase_config: Dict[str, Any] = {}
    if erase_type == "subtitle":
        erase_config["SubtitleEraseMethod"] = erase_method or "auto"
        erase_config["SubtitleModel"] = subtitle_model or "standard"
        if custom_areas and erase_method == "custom":
            # Convert tool area format to MPS CustomAreas format
            mps_custom_areas = []
            for area in custom_areas:
                mps_area = {
                    "Areas": [{
                        "LeftTopX": area.get("left_top_x", 0),
                        "LeftTopY": area.get("left_top_y", 0),
                        "RightBottomX": area.get("right_bottom_x", 0),
                        "RightBottomY": area.get("right_bottom_y", 0),
                        "Unit": area.get("unit", 1),
                    }],
                }
                if area.get("begin") is not None:
                    mps_area["BeginMs"] = int(area["begin"])
                if area.get("end") is not None:
                    mps_area["EndMs"] = int(area["end"])
                mps_custom_areas.append(mps_area)
            erase_config["CustomAreas"] = mps_custom_areas

    if erase_type == "subtitle":
        body["SmartEraseTask"]["OverrideParameter"]["EraseSubtitleConfig"] = erase_config

    payload_str = json.dumps(body, ensure_ascii=False)

    headers = _build_mps_auth_headers(secret_id, secret_key, "ProcessMedia", payload_str)

    _span = None
    if tracer:
        _span = tracer.start_child("ProcessMedia", model="mps-smarterase", provider_type="tencentmps", input_data=body, obs_type="span")
        if _span:
            _span.log_input(body)
    _error: Optional[Exception] = None

    try:
        response = await client.post(MPS_API_URL, content=payload_str, headers=headers)
        response.raise_for_status()
        data = response.json()

        resp = data.get("Response", {})
        if "Error" in resp:
            err = resp["Error"]
            raise RuntimeError(
                f"MPS ProcessMedia error (code={err.get('Code')}): {err.get('Message')}"
            )

        task_id = resp.get("TaskId")
        if not task_id:
            raise RuntimeError(f"MPS ProcessMedia returned no TaskId: {data}")

        if _span:
            _span.log_output({"task_id": task_id, "x-request-id": resp.get("RequestId", "")})
        return task_id
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# API: DescribeTaskDetail (poll task result)
# =============================================================================

async def _describe_mps_task_detail(
    client: httpx.AsyncClient,
    secret_id: str,
    secret_key: str,
    task_id: str,
) -> Dict[str, Any]:
    """Call MPS DescribeTaskDetail and return the Response dict."""
    body = {"TaskId": task_id}
    payload_str = json.dumps(body, ensure_ascii=False)
    headers = _build_mps_auth_headers(secret_id, secret_key, "DescribeTaskDetail", payload_str)

    response = await client.post(MPS_API_URL, content=payload_str, headers=headers)
    response.raise_for_status()
    data = response.json()

    resp = data.get("Response", {})
    if "Error" in resp:
        err = resp["Error"]
        raise RuntimeError(
            f"MPS DescribeTaskDetail error (code={err.get('Code')}): {err.get('Message')}"
        )
    return resp


async def _poll_mps_task(
    secret_id: str,
    secret_key: str,
    task_id: str,
    poll_timeout: Optional[int] = None,
    tracer: Any = None,
) -> List[Dict[str, Any]]:
    """Poll DescribeTaskDetail until the MPS task finishes, extract output URLs."""
    max_wait = poll_timeout or _POLL_MAX_WAIT_S
    deadline = time.time() + max_wait

    _span = None
    if tracer:
        _span = tracer.start_child(task_id, model=task_id, provider_type="tencentmps", obs_type="span")
    _error: Optional[Exception] = None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            poll_count = 0
            while time.time() < deadline:
                resp = await _describe_mps_task_detail(client, secret_id, secret_key, task_id)
                status = resp.get("Status", "")
                poll_count += 1

                if _span:
                    _span.log_output({
                        "task_id": task_id,
                        "status": status,
                        "poll_count": poll_count,
                        "x-request-id": resp.get("RequestId", ""),
                    })

                if status == "FINISH":
                    workflow_task = resp.get("WorkflowTask", {})
                    video_items: List[Dict[str, Any]] = []

                    # Parse SmartEraseTaskResult: WorkflowTask.SmartEraseTaskResult.Output.Path
                    smart_erase_result = workflow_task.get("SmartEraseTaskResult", {})
                    output = smart_erase_result.get("Output", {})
                    path = output.get("Path", "")
                    if path:
                        cos_key = path.lstrip("/")
                        storage = get_storage_backend()
                        url = storage.url_for(cos_key)
                        video_items.append({
                            "type": "video_erase_call",
                            "status": "completed",
                            "result": url,
                        })

                    if not video_items:
                        raise RuntimeError(
                            f"MPS task {task_id} finished but no output found: "
                            f"{json.dumps(resp, ensure_ascii=False)}"
                        )

                    return video_items

                if status in ("FAIL", "ABORTED"):
                    err_msg = resp.get("Message", f"status={status}")
                    raise RuntimeError(f"MPS task {task_id} failed: {err_msg}")

                await asyncio.sleep(_POLL_INTERVAL_S)

        raise RuntimeError(f"MPS task {task_id} timed out after {max_wait}s")
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# 视频输入提取
# =============================================================================

def _extract_input_video_url(messages, metadata: Dict[str, Any]) -> str:
    """Extract the input video URL from messages or file_id_media_map."""
    # Priority 1: file_id_media_map
    file_map: Dict[str, Any] = metadata.get("file_id_media_map") or {}
    for _fid, info in file_map.items():
        if info.get("type") == "video":
            url = info.get("url", "")
            if url:
                return url

    # Priority 2: scan message content blocks
    for msg in reversed(messages):
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role != "user":
            continue
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if hasattr(block, "type"):
                if block.type == ContentType.VIDEO_URL and getattr(block, "url", ""):
                    return block.url

    raise RuntimeError("MPS video erase: no input video URL found in request")


# =============================================================================
# 主入口: 执行视频擦除
# =============================================================================

async def execute_mps_video_erase(
    api_key: str,
    model: str,
    messages,
    metadata: Dict[str, Any],
    extra_config: Optional[Dict[str, Any]] = None,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute MPS Smart Erase and return a ChatResponse.

    Args:
        api_key:      "SecretId:SecretKey" credential string
        model:        Model identifier, e.g. "mps-erase-subtitle-standard"
        messages:     List of Message objects from the ChatRequest
        metadata:     ChatRequest.metadata dict (carries video_erase params)
        extra_config: Provider extra_config (COS bucket, region, etc.)
        tracer:       Optional tracing span

    Returns:
        ChatResponse with video_erase_call items in message content
    """
    secret_id, secret_key = _parse_api_key(api_key)
    extra = extra_config or {}

    # ── Resolve COS output config ────────────────────────────────────
    output_bucket = str(
        metadata.get("output_bucket")
        or extra.get("cos_bucket")
        or extra.get("output_bucket")
        or os.environ.get("STORAGE_S3_BUCKET")
        or ""
    )
    output_region = str(
        metadata.get("output_region")
        or extra.get("cos_region")
        or extra.get("output_region")
        or extra.get("region")
        or os.environ.get("STORAGE_S3_REGION")
        or MPS_API_REGION
    )
    output_dir = str(
        metadata.get("output_dir")
        or extra.get("output_dir")
        or extra.get("cos_output_dir")
        or ""
    )
    # Default to {storage.prefix}/{request_id}/
    if not output_dir:
        storage = get_storage_backend()
        prefix = getattr(storage, 'prefix', 'background_responses')
        request_id = metadata.get("request_id") or gen_id("vid")
        output_dir = f"{prefix}/{request_id}/"
    if not output_bucket:
        raise RuntimeError(
            "MPS video erase: COS bucket must be configured in extra_config.cos_bucket"
        )

    # ── Parse erase params from tool metadata or model name ──────────
    erase_type = str(metadata.get("erase_type") or "")
    erase_method = str(metadata.get("erase_method") or "auto")
    template_id = metadata.get("template_id")
    if template_id is not None:
        definition = int(template_id)
    else:
        definition = int(extra.get("mps_definition", 303))

    # Resolve subtitle_model: prefer explicit metadata, then parse from model name
    subtitle_model = str(metadata.get("erase_model") or "")
    if not subtitle_model:
        parsed = _parse_erase_model(model)
        subtitle_model = parsed.get("subtitle_model", "standard")
    if not erase_type:
        parsed = _parse_erase_model(model)
        erase_type = parsed.get("erase_type", "subtitle")

    # Parse custom areas
    custom_areas: Optional[List[Dict[str, Any]]] = None
    raw_areas = metadata.get("area") or metadata.get("areas")
    if raw_areas:
        if isinstance(raw_areas, str):
            try:
                custom_areas = json_loads(raw_areas)
            except (json.JSONDecodeError, TypeError):
                custom_areas = []
        elif isinstance(raw_areas, list):
            custom_areas = raw_areas

    # ── Extract input video URL ──────────────────────────────────────
    input_url = _extract_input_video_url(messages, metadata)

    # ── Tracing ──────────────────────────────────────────────────────
    _request_data: Dict[str, Any] = {
        "model": model,
        "erase_type": erase_type,
        "subtitle_model": subtitle_model,
        "erase_method": erase_method,
        "input_url": input_url,
    }
    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="tencentmps", input_data=_request_data)
        if _child_span:
            _child_span.log_input(_request_data)
    _trace_error: Optional[Exception] = None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            task_id = await _create_process_media_task(
                client=client,
                secret_id=secret_id,
                secret_key=secret_key,
                input_url=input_url,
                output_bucket=output_bucket,
                output_region=output_region,
                output_dir=output_dir,
                erase_type=erase_type,
                subtitle_model=subtitle_model,
                erase_method=erase_method,
                custom_areas=custom_areas,
                definition=definition,
                tracer=_child_span,
            )

        video_items = await _poll_mps_task(
            secret_id, secret_key, task_id,
            poll_timeout=metadata.get("timeout"),
            tracer=_child_span,
        )

        if _child_span:
            _child_span.log_output({"task_id": task_id, "video_count": len(video_items), "status": "succeeded"})
    except Exception as e:
        _trace_error = e
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(video_items, ensure_ascii=False),
    )

    video_count = max(len(video_items), 1)

    return ChatResponse(
        id=gen_id("vid"),
        model=model,
        choices=[ChatChoice(
            index=0,
            message=message,
            finish_reason=FinishReason.STOP,
        )],
        usage=UsageInfo(
            prompt_tokens=0,
            completion_tokens=video_count,
            total_tokens=video_count,
            extra={
                'output_video_number': video_count,
                'output_video_erase_type': erase_type,
            },
        ),
        created=int(time.time()),
        provider="tencentmps",
    )


# =============================================================================
# 流式响应
# =============================================================================

async def stream_video_erase(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    response = await chat_fn(request)
    response_id = response.id
    model = response.model

    videos: List[Dict[str, Any]] = []
    if response.choices and response.choices[0].message:
        msg = response.choices[0].message
        raw = (
            msg.content
            if isinstance(msg.content, str)
            else (msg.get_text_content() or "[]")
        )
        try:
            videos = json_loads(raw) if isinstance(raw, str) else []
        except (json.JSONDecodeError, TypeError):
            videos = []

    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    for i, vid in enumerate(videos):
        result = vid.get("result", "")
        call_id = f"{response_id}-{i}" if i > 0 else response_id
        output_index = i

        item_added = {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "type": "video_erase_call",
                "id": call_id,
                "status": "generating",
                "result": None,
            },
        }
        item_done = {
            "type": "response.output_item.done",
            "output_index": output_index,
            "item": {
                "type": "video_erase_call",
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

    usage_dict: Dict[str, Any] = {}
    if response.usage:
        usage_dict = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    output_items = [
        {
            "type": "video_erase_call",
            "id": (f"{response_id}-{i}" if i > 0 else response_id),
            "status": "completed",
            "result": vid.get("result", ""),
        }
        for i, vid in enumerate(videos)
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