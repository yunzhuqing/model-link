"""
豆包 Seed3D 3D 生成模块 (Volcengine Seed3D 3D Generation)

通过火山引擎 ARK API 从图片生成 3D 模型，兼容 /v1/responses 3d_generation 工具。

流程：
1. 创建任务: POST /api/v3/contents/generations/tasks
2. 轮询结果: GET  /api/v3/contents/generations/tasks/{task_id}
   直到 status == "succeeded"

认证方式：Authorization: Bearer <ARK_API_KEY>

支持的模型:
  doubao-seed3d-2-0-260328    → 豆包 Seed3D 2.0
  doubao-seed3d               → 豆包 Seed3D (alias)
  seed3d-2.0                  → Seed3D 2.0 (alias)

API 请求示例:
curl -X POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $ARK_API_KEY" \\
  -d '{
    "model": "doubao-seed3d-2-0-260328",
    "content": [
        {
            "type": "text",
            "text": "--subdivisionlevel medium --fileformat glb"
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "https://example.com/input.png"
            }
        }
    ]
}'

返回值:
{
  "id": "cgt-2025******-****"
}

查询结果:
{
    "id": "cgt-2025******-****",
    "model": "doubao-seed3d-2-0-260328",
    "status": "succeeded",
    "created_at": "1718049470",
    "updated_at": "1718049470",
    "content": {
        "file_url": "https://xxx"
    },
    "subdivisionlevel": "medium",
    "fileformat": "glb",
    "usage": {
        "total_tokens": 30000,
        "completion_tokens": 30000
    }
}

任务状态: queued, running, succeeded, failed, cancelled

API 文档: https://www.volcengine.com/docs/82379/
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, Generator, List, Optional, Tuple

import httpx

from app.abstraction.chat import (
    ChatChoice,
    ChatRequest,
    ChatResponse,
    FinishReason,
    UsageInfo,
)
from app.abstraction.messages import ContentType, Message, MessageRole
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id


# =============================================================================
# 常量
# =============================================================================

_POLL_INTERVAL_S: float = 3.0
_POLL_MAX_WAIT_S: int = 600   # 10 分钟

# 3D 任务终止状态
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

# Seed3D 默认参数
_DEFAULT_SUBDIVISION_LEVEL = "medium"    # low | medium | high
_DEFAULT_FILE_FORMAT = "glb"              # glb | obj | fbx | stl


# =============================================================================
# 模型检测
# =============================================================================

# Seed3D 模型名称前缀 (小写)
_SEED3D_MODEL_PREFIXES = (
    "doubao-seed3d",
    "seed3d",
)


def is_seed3d_model(model: str) -> bool:
    """
    检查模型是否为 Seed3D 3D 生成模型。

    Args:
        model: 模型名称

    Returns:
        True 表示 Seed3D 3D 生成模型
    """
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _SEED3D_MODEL_PREFIXES)


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


# =============================================================================
# 用户友好名称 → 实际 API 模型 ID 映射
# =============================================================================

_SEED3D_MODEL_ID_MAP: Dict[str, str] = {
    "doubao-seed3d-2-0-260328":   "doubao-seed3d-2-0-260328",
    "doubao-seed3d-2.0":          "doubao-seed3d-2-0-260328",
    "doubao-seed3d":              "doubao-seed3d-2-0-260328",
    "seed3d-2.0":                 "doubao-seed3d-2-0-260328",
    "seed3d":                     "doubao-seed3d-2-0-260328",
}


def _resolve_seed3d_model_id(model: str) -> str:
    """
    将用户友好的模型名称解析为 API 实际使用的模型 ID。

    Args:
        model: 用户传入的模型名称

    Returns:
        API 模型 ID（若未命中映射表则原样返回）
    """
    return _SEED3D_MODEL_ID_MAP.get(model.lower(), model)


def _face_count_to_subdivision_level(face_count: int) -> str:
    """
    将 face_count（面数）映射到 Seed3D 的 subdivision_level 参数。

    映射规则：
      0 ~ 100,000       → "low"
      100,000 ~ 500,000 → "medium"
      > 500,000         → "high"

    Args:
        face_count: 面数（整数）

    Returns:
        对应的 subdivision_level 字符串
    """
    if face_count <= 100000:
        return "low"
    elif face_count <= 500000:
        return "medium"
    else:
        return "high"


# =============================================================================
# 内容块构建
# =============================================================================

def _build_content(
    messages: List[Message],
    subdivision_level: str = _DEFAULT_SUBDIVISION_LEVEL,
    file_format: str = _DEFAULT_FILE_FORMAT,
) -> List[Dict[str, Any]]:
    """
    从 ChatRequest 消息列表构建 Seed3D API 的 content 数组。

    Seed3D API 使用一个统一的 ``content`` 数组：
      - 文本项:  {"type": "text", "text": "--subdivisionlevel medium --fileformat glb"}
      - 图片项:  {"type": "image_url", "image_url": {"url": "..."}}

    文本项中的参数通过 ``--key value`` 格式传递，包含：
      --subdivisionlevel: low | medium | high （细分层级）
      --fileformat:       glb | obj | fbx | stl （输出文件格式）

    Args:
        messages:           ChatRequest 消息列表
        subdivision_level:  细分层级（low/medium/high）
        file_format:        输出文件格式（glb/obj/fbx/stl）

    Returns:
        content 列表（包含文本项和图片项）
    """
    content: List[Dict[str, Any]] = []
    image_url: Optional[str] = None
    text_prompt = ""

    # 从最后一条用户消息中提取图片和文本
    for msg in reversed(messages):
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role != "user":
            continue

        if isinstance(msg.content, str):
            text_prompt = msg.content.strip()
        elif isinstance(msg.content, list):
            text_parts = []
            for block in msg.content:
                if not hasattr(block, "type"):
                    continue
                if block.type == ContentType.IMAGE_URL and block.url and not image_url:
                    image_url = block.url
                elif block.type == ContentType.IMAGE_BASE64 and block.data and not image_url:
                    # Convert base64 to data URI
                    mime = block.media_type or "image/png"
                    image_url = f"data:{mime};base64,{block.data}"
                elif hasattr(block, "text") and block.text:
                    text_parts.append(block.text)
            if text_parts:
                text_prompt = " ".join(text_parts).strip()
        break

    # 构建参数文本
    # 如果用户已经在文本中包含了 --subdivisionlevel 或 --fileformat，则使用用户的值
    params_text = text_prompt
    if not params_text:
        params_text = f"--subdivisionlevel {subdivision_level} --fileformat {file_format}"
    else:
        if "--subdivisionlevel" not in params_text.lower():
            params_text += f" --subdivisionlevel {subdivision_level}"
        if "--fileformat" not in params_text.lower():
            params_text += f" --fileformat {file_format}"

    content.append({"type": "text", "text": params_text})

    if image_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url},
        })

    return content


# =============================================================================
# API 调用: 创建 3D 生成任务
# =============================================================================

def _create_3d_task(
    api_key: str,
    base_url: str,
    model_id: str,
    content: List[Dict[str, Any]],
) -> str:
    """
    调用 POST /contents/generations/tasks 创建 3D 生成任务，返回 task_id。

    Args:
        api_key:   ARK API Key
        base_url:  API 基础 URL（含 /v3）
        model_id:  实际 API 模型 ID
        content:   内容数组（文本参数 + 图片）

    Returns:
        task_id 字符串

    Raises:
        RuntimeError: API 返回错误时
    """
    body: Dict[str, Any] = {
        "model": model_id,
        "content": content,
    }

    url = f"{base_url.rstrip('/')}/contents/generations/tasks"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload_str = json.dumps(body, ensure_ascii=False)

    print("\n" + "=" * 50, file=sys.stderr)
    print("[Seed3D Create3DTask Request]", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print(payload_str, file=sys.stderr)
    print("=" * 50 + "\n", file=sys.stderr)

    with httpx.Client(timeout=60) as client:
        response = client.post(url, content=payload_str, headers=headers)

    print("\n" + "=" * 50, file=sys.stderr)
    print("[Seed3D Create3DTask Response]", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print(response.text, file=sys.stderr)
    print("=" * 50 + "\n", file=sys.stderr)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Seed3D Create3DTask error ({response.status_code}): {response.text}"
        )

    data = response.json()
    task_id = data.get("id", "")
    if not task_id:
        raise RuntimeError(f"Seed3D Create3DTask returned no task id: {data}")
    return task_id


# =============================================================================
# API 调用: 轮询任务结果
# =============================================================================

def _poll_3d_task(
    api_key: str,
    base_url: str,
    task_id: str,
    poll_timeout: Optional[int] = None,
) -> Tuple[str, str, str, Dict[str, int]]:
    """
    轮询 GET /contents/generations/tasks/{task_id} 直到任务完成。

    Args:
        api_key:   ARK API Key
        base_url:  API 基础 URL（含 /v3）
        task_id:   Create3DTask 返回的任务 ID

    Returns:
        (file_url, file_format, subdivision_level, usage_dict)
        file_url:          生成的 3D 模型文件地址
        file_format:       输出文件格式 (如 glb)
        subdivision_level: 细分层级 (如 medium)
        usage_dict:        包含 prompt_tokens / completion_tokens / total_tokens

    Raises:
        RuntimeError: 任务失败或超时
    """
    url = f"{base_url.rstrip('/')}/contents/generations/tasks/{task_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    max_wait = poll_timeout or _POLL_MAX_WAIT_S
    deadline = time.time() + max_wait

    with httpx.Client(timeout=60) as client:
        while time.time() < deadline:
            response = client.get(url, headers=headers)

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Seed3D Query3DTask error ({response.status_code}): {response.text}"
                )

            data = response.json()
            status = data.get("status", "")

            print(
                f"[Seed3D 3D] Task {task_id} status={status}",
                file=sys.stderr,
            )

            if status == "succeeded":
                print(
                    f"[Seed3D 3D] Task FINISH detail: "
                    f"{json.dumps(data, ensure_ascii=False)}",
                    file=sys.stderr,
                )
                content = data.get("content") or {}
                file_url = content.get("file_url", "")
                if not file_url:
                    raise RuntimeError(
                        f"Seed3D task {task_id} succeeded but no file_url found: {data}"
                    )

                # Extract metadata from response
                file_format = data.get("fileformat", _DEFAULT_FILE_FORMAT)
                subdivision_level = data.get("subdivisionlevel", _DEFAULT_SUBDIVISION_LEVEL)

                # 提取 API 返回的真实用量
                raw_usage = data.get("usage") or {}
                completion_tokens = int(raw_usage.get("completion_tokens", 0))
                total_tokens = int(raw_usage.get("total_tokens", completion_tokens))
                prompt_tokens = total_tokens - completion_tokens
                usage_dict = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
                return file_url, file_format, subdivision_level, usage_dict

            if status in ("failed", "cancelled"):
                raise RuntimeError(
                    f"Seed3D 3D task {task_id} ended with status={status}: {data}"
                )

            time.sleep(_POLL_INTERVAL_S)

    raise RuntimeError(
        f"Seed3D 3D task {task_id} timed out after {_POLL_MAX_WAIT_S}s"
    )


# =============================================================================
# 主入口: 执行 3D 生成
# =============================================================================

def execute_seed3d_generation(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Message],
    metadata: Dict[str, Any],
) -> ChatResponse:
    """
    执行 Seed3D 3D 生成并返回 ChatResponse。

    Args:
        api_key:   ARK API Key
        base_url:  API 基础 URL（含 /v3）
        model:     模型名称（用户传入，如 "doubao-seed3d-2-0-260328"）
        messages:  消息列表
        metadata:  请求 metadata（3D 生成参数）

    Returns:
        ChatResponse，message.content 为 JSON 格式的 3d_generation_call 列表

    Raises:
        RuntimeError: API 错误或任务失败
    """
    model_id = _resolve_seed3d_model_id(model)

    # ── 参数提取 ──────────────────────────────────────────────────────────
    # subdivision_level: derived from face_count.
    #   face_count mapping:
    #     0 ~ 100,000       → "low"
    #     100,000 ~ 500,000 → "medium"
    #     > 500,000         → "high"
    face_count_raw = metadata.get("face_count")
    if face_count_raw is not None:
        subdivision_level = _face_count_to_subdivision_level(int(face_count_raw))
    else:
        subdivision_level = _DEFAULT_SUBDIVISION_LEVEL

    # file_format: accept file_format / fileformat,
    # or map from output_format / result_format (Hunyuan 3D compatibility).
    # output_format values like "OBJ", "GLB", "STL", "FBX" map directly to
    # Seed3D's fileformat parameter (lowercased).
    file_format = str(
        metadata.get("file_format")
        or metadata.get("fileformat")
        or metadata.get("output_format")
        or metadata.get("result_format")
        or _DEFAULT_FILE_FORMAT
    ).lower()

    # ── 构建 content 数组 ────────────────────────────────────────────────
    content = _build_content(
        messages,
        subdivision_level=subdivision_level,
        file_format=file_format,
    )

    if not any(item.get("type") == "image_url" for item in content):
        raise RuntimeError(
            "Seed3D 3D generation: no image found in user messages. "
            "Please provide an input image for 3D model generation."
        )

    # ── 创建任务 ─────────────────────────────────────────────────────────
    task_id = _create_3d_task(
        api_key=api_key,
        base_url=base_url,
        model_id=model_id,
        content=content,
    )

    # ── 轮询结果 ─────────────────────────────────────────────────────────
    file_url, result_format, result_subdivision, usage_dict = _poll_3d_task(
        api_key, base_url, task_id, poll_timeout=metadata.get('timeout')
    )

    # Wrap in the 3d_generation_call response structure
    threed_items = [{
        "type": "3d_generation_call",
        "id": task_id,
        "status": "completed",
        "content": [{
            "type": result_format.upper(),
            "url": file_url,
        }],
    }]

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(threed_items, ensure_ascii=False),
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
            prompt_tokens=usage_dict["prompt_tokens"],
            completion_tokens=usage_dict["completion_tokens"],
            total_tokens=usage_dict["total_tokens"],
        ),
        created=int(time.time()),
        provider="volcengine",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

def stream_seed3d_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    执行 Seed3D 3D 生成并以 StreamChunk 格式 yield 结果。

    Seed3D 3D 生成是异步任务（创建 → 轮询），此函数将同步调用结果
    转换为兼容 Responses API 适配器的 SSE 事件序列：

    1. role marker  (delta_role="assistant")  → 触发 format_stream_start
    2. response.output_item.added  (generating)
    3. response.output_item.done   (completed, content=[...])
    4. response.completed

    Args:
        chat_fn: provider.chat 非流式方法
        request: ChatRequest
    """
    response = chat_fn(request)
    response_id = response.id
    model = response.model

    # 解析 3D 生成结果列表
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

    # Role marker
    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    # 每个 3D 结果一个 output item
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

    # response.completed
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
