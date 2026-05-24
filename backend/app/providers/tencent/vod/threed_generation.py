"""
腾讯云点播 3D 生成模块 (TencentVOD 3D Generation)

通过腾讯云点播 AI 视频生成 API (CreateAigcVideoTask) 生成 3D 内容，
兼容 /v1/responses 3d_generation 工具。

流程：
1. 发起请求: POST vod.tencentcloudapi.com  Action=CreateAigcVideoTask
   ModelName=Hunyuan, ModelVersion=3d_2.0, SceneType=3d_scene
2. 轮询结果: POST vod.tencentcloudapi.com  Action=DescribeTaskDetail
   直到 Status == "FINISH"

认证方式：
腾讯云 VOD API 使用 TC3-HMAC-SHA256 签名。
api_key 字段应为 "SecretId:SecretKey" 格式。
SubAppId 存放于 extra_config["sub_app_id"]。

API 文档: https://cloud.tencent.com/document/product/266/
"""
from __future__ import annotations

import json
import sys
import time
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
from app.abstraction.messages import Message, MessageRole
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id, json_loads

# Re-use shared auth/network helpers from image_generation.
from .image_generation import (
    TENCENTVOD_API_HOST,
    TENCENTVOD_API_URL,
    _POLL_INTERVAL_S,
    _POLL_MAX_WAIT_S,
    _build_auth_headers,
    _parse_api_key,
    check_tencentvod_task_status,
)


# =============================================================================
# 3D 生成模型检测
# =============================================================================

# Known TencentVOD 3D generation model name prefixes (case-insensitive).
_TENCENTVOD_3D_MODEL_PREFIXES = (
    "hunyuan-3d-",
)

# Explicit lookup table: input model identifier (case-insensitive) →
# (TencentVOD ModelName, TencentVOD ModelVersion).
_3D_MODEL_NAME_VERSION_MAP: Dict[str, Tuple[str, str]] = {
    "hunyuan-3d-2.0": ("Hunyuan", "3d_2.0"),
}


def is_tencentvod_3d_model(model: str) -> bool:
    """Check if the model is a TencentVOD 3D generation model."""
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _TENCENTVOD_3D_MODEL_PREFIXES)


def has_3d_generation_tool(request: ChatRequest) -> bool:
    """Check if the request was sent with a ``3d_generation`` tool."""
    return bool(request.metadata.get("_3d_generation"))


# =============================================================================
# 辅助: 解析模型名称 / 版本
# =============================================================================

def _parse_3d_model_name_version(model: str) -> Tuple[str, str]:
    """Derive TencentVOD ModelName and ModelVersion from a 3D model identifier."""
    key = model.lower().strip()
    if key in _3D_MODEL_NAME_VERSION_MAP:
        return _3D_MODEL_NAME_VERSION_MAP[key]
    if key.startswith("hunyuan-3d-"):
        return "Hunyuan", model[len("hunyuan-3d-"):]
    return model, "latest"


# =============================================================================
# API 调用: CreateAigcVideoTask (for 3D scene)
# =============================================================================

async def _create_3d_task(
    client: httpx.AsyncClient,
    secret_id: str,
    secret_key: str,
    sub_app_id: Optional[int],
    model_name: str,
    model_version: str,
    prompt: str,
    scene_type: str = "3d_scene",
    session_id: str = "",
    tracer: Any = None,
) -> str:
    """Call CreateAigcVideoTask for 3D generation and return the TaskId."""
    body: Dict[str, Any] = {
        "ModelName": model_name,
        "ModelVersion": model_version,
        "Prompt": prompt,
        "SceneType": scene_type,
    }

    if sub_app_id is not None:
        body["SubAppId"] = sub_app_id

    if session_id:
        body["SessionId"] = session_id

    payload_str = json.dumps(body, ensure_ascii=False)
    headers = _build_auth_headers(secret_id, secret_key, "CreateAigcVideoTask", payload_str)

    _span = None
    if tracer:
        _span = tracer.start_child(model_name, model=model_name, provider_type="tencentvod", input_data=body, obs_type="span")
        if _span:
            _span.log_input(body)
    _error: Optional[Exception] = None

    try:
        response = await client.post(TENCENTVOD_API_URL, content=payload_str, headers=headers)
        response.raise_for_status()
        data = response.json()

        resp = data.get("Response", {})
        if "Error" in resp:
            err = resp["Error"]
            raise RuntimeError(
                f"TencentVOD 3D CreateAigcVideoTask error "
                f"(code={err.get('Code')}): {err.get('Message')}"
            )

        task_id = resp.get("TaskId")
        if not task_id:
            raise RuntimeError(
                f"TencentVOD 3D CreateAigcVideoTask returned no TaskId: {data}"
            )

        if _span:
            _output: Dict[str, Any] = {"task_id": task_id}
            _req_id = resp.get("RequestId", "")
            if _req_id:
                _output["x-request-id"] = _req_id
            _span.log_output(_output)
        return task_id
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# API 调用: 轮询任务结果
# =============================================================================

async def _poll_3d_task(
    secret_id: str,
    secret_key: str,
    task_id: str,
    sub_app_id: Optional[int],
    poll_timeout: Optional[int] = None,
    tracer: Any = None,
) -> List[Dict[str, Any]]:
    """Poll DescribeTaskDetail until the 3D task finishes, then extract the output URL."""
    max_wait = poll_timeout or _POLL_MAX_WAIT_S
    deadline = time.time() + max_wait

    _span = None
    if tracer:
        _span = tracer.start_child(task_id, model=task_id, provider_type="tencentvod", obs_type="span")
    _error: Optional[Exception] = None

    try:
        while time.time() < deadline:
            resp = await check_tencentvod_task_status(
                secret_id, secret_key, task_id, sub_app_id
            )
            if not resp:
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            aigc_task = resp.get("AigcVideoTask") or {}
            status = resp.get("Status") or aigc_task.get("Status", "")

            if status == "FINISH":
                err_code = aigc_task.get("ErrCode", 0)
                if err_code != 0:
                    raise RuntimeError(
                        f"TencentVOD 3D task failed "
                        f"(ErrCode={err_code}): {aigc_task.get('Message', '')}"
                    )

                output = aigc_task.get("Output") or {}
                items: List[Dict[str, Any]] = []

                # Pattern 1: single FileUrl
                file_url = output.get("FileUrl", "")
                if file_url:
                    items.append({
                        "type": "3d_generation_call",
                        "status": "completed",
                        "content": [{"url": file_url}],
                    })

                # Pattern 2: FileInfos array
                for fi in (output.get("FileInfos") or []):
                    url = fi.get("FileUrl", "")
                    if url:
                        items.append({
                            "type": "3d_generation_call",
                            "status": "completed",
                            "content": [{"url": url}],
                        })

                if not items:
                    raise RuntimeError(
                        f"TencentVOD 3D task {task_id} finished but no FileUrl found"
                    )

                return items

            if status in ("FAIL", "ABORTED"):
                raise RuntimeError(
                    f"TencentVOD 3D task {task_id} failed with status={status}"
                )

            await asyncio.sleep(_POLL_INTERVAL_S)

        raise RuntimeError(
            f"TencentVOD 3D task {task_id} timed out after {max_wait}s"
        )
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# 主入口: 执行 3D 生成
# =============================================================================

async def execute_tencentvod_3d_generation(
    api_key: str,
    model: str,
    messages,
    metadata: Dict[str, Any],
    sub_app_id: Optional[int] = None,
    tracer: Any = None,
) -> ChatResponse:
    """Execute TencentVOD 3D generation and return a ChatResponse."""
    secret_id, secret_key = _parse_api_key(api_key)

    _sub_app = metadata.get("sub_app_id") or sub_app_id
    if _sub_app is not None:
        _sub_app = int(_sub_app)

    model_name, model_version = _parse_3d_model_name_version(model)

    # Extract prompt from the last user message
    prompt = ""
    for msg in reversed(messages):
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role == "user":
            if isinstance(msg.content, list):
                text_parts = []
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        text_parts.append(block.text)
                prompt = " ".join(text_parts)
            elif isinstance(msg.content, str):
                prompt = msg.content
            break

    if not prompt:
        raise RuntimeError("TencentVOD 3D generation: no prompt found in user messages")

    session_id = str(metadata.get("session_id") or "")
    scene_type = "3d_scene"

    _request_data: Dict[str, Any] = {"model": model, "model_version": model_version, "prompt": prompt}
    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="tencentvod", input_data=_request_data)
        if _child_span:
            _child_span.log_input(_request_data)
    _trace_error: Optional[Exception] = None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            task_id = await _create_3d_task(
                client=client,
                secret_id=secret_id,
                secret_key=secret_key,
                sub_app_id=_sub_app,
                model_name=model_name,
                model_version=model_version,
                prompt=prompt,
                scene_type=scene_type,
                session_id=session_id,
                tracer=_child_span,
            )

        hook = metadata.get('_on_task_created')
        if hook:
            hook(task_id)

        items = await _poll_3d_task(secret_id, secret_key, task_id, _sub_app, poll_timeout=metadata.get("timeout"), tracer=_child_span)

        if _child_span:
            _child_span.log_output({"task_id": task_id, "status": "succeeded"})
    except Exception as e:
        _trace_error = e
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(items, ensure_ascii=False),
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
            completion_tokens=1,
            total_tokens=1,
            extra={'_task_id': task_id, 'output_count': 1},
        ),
        created=int(time.time()),
        provider="tencentvod",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

async def stream_3d_generation(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    """Execute TencentVOD 3D generation and yield StreamChunks."""
    response = await chat_fn(request)
    response_id = response.id
    model = response.model

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

    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    for i, item in enumerate(items):
        content_val = item.get("content", [])
        item_type = item.get("type", "3d_generation_call")
        call_id = f"{response_id}-{i}" if i > 0 else response_id
        output_index = i

        item_added = {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "type": item_type,
                "id": call_id,
                "status": "generating",
                "content": None,
            },
        }
        item_done = {
            "type": "response.output_item.done",
            "output_index": output_index,
            "item": {
                "type": item_type,
                "id": call_id,
                "status": "completed",
                "content": content_val,
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
            "type": item.get("type", "3d_generation_call"),
            "id": (f"{response_id}-{i}" if i > 0 else response_id),
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