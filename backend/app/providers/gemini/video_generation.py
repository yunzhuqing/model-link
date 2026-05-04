"""
Gemini Veo 视频生成模块 (Gemini Veo Video Generation)

通过 Google Generative AI API 的 predictLongRunning 端点异步生成视频。

支持的模型:
  veo-3.1-generate-preview      → 高质量视频生成
  veo-3.1-fast-generate-preview → 快速视频生成
  veo-3.1-lite-generate-preview → 轻量级视频生成

流程:
  1. 创建任务: POST /v1beta/models/{model}:predictLongRunning
  2. 轮询结果: GET  /v1beta/{operation_name}
     直到 done == true

认证方式: x-goog-api-key: <GEMINI_API_KEY>

响应解析:
  response.generateVideoResponse.generatedSamples[0].video.uri

API 文档: https://ai.google.dev/api/veo
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
from app.abstraction.messages import ContentBlock, ContentType, Message, MessageRole
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id


# =============================================================================
# 常量
# =============================================================================

_POLL_INTERVAL_S: float = 5.0
_POLL_MAX_WAIT_S: int = 600   # 10 分钟


# =============================================================================
# 模型检测
# =============================================================================

# Veo 视频模型名称前缀 (小写)
_VEO_MODEL_PREFIXES = (
    "veo-",
    "veo3",
)


def is_veo_video_model(model: str) -> bool:
    """
    检查模型是否为 Gemini Veo 视频生成模型。

    Args:
        model: 模型名称

    Returns:
        True 表示 Veo 视频生成模型
    """
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _VEO_MODEL_PREFIXES)


# =============================================================================
# 请求构建
# =============================================================================

def _build_veo_request(
    messages: List[Message],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """
    从 ChatRequest 消息列表和 metadata 构建 Veo predictLongRunning 请求体。

    Veo API 格式:
    {
      "instances": [{
        "prompt": "...",
        "image": {"inlineData": {"mimeType": "image/png", "data": "..."}},  // 可选
        "lastFrame": {"inlineData": {"mimeType": "image/png", "data": "..."}}  // 可选
      }],
      "parameters": {
        "aspectRatio": "16:9",
        "durationSeconds": 8,
        ...
      }
    }

    Args:
        messages: ChatRequest 消息列表
        metadata: 请求 metadata（视频生成参数）

    Returns:
        Veo predictLongRunning 请求体
    """
    prompt = ""
    first_frame_b64: Optional[str] = None
    first_frame_mime: str = "image/png"
    last_frame_b64: Optional[str] = None
    last_frame_mime: str = "image/png"

    # 从用户消息中提取 prompt 和图像帧
    for msg in messages:
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role != "user":
            continue

        if isinstance(msg.content, str):
            if msg.content.strip():
                prompt = msg.content.strip()
        elif isinstance(msg.content, list):
            for block in msg.content:
                if not hasattr(block, "type"):
                    continue

                if block.type == ContentType.TEXT and block.text:
                    prompt = block.text.strip()

                elif block.type == ContentType.IMAGE_BASE64 and block.data:
                    # 第一张 base64 图片作为首帧
                    if first_frame_b64 is None:
                        first_frame_b64 = block.data
                        first_frame_mime = block.media_type or "image/png"
                    else:
                        # 第二张 base64 图片作为尾帧
                        last_frame_b64 = block.data
                        last_frame_mime = block.media_type or "image/png"

    # 构建 instance
    instance: Dict[str, Any] = {"prompt": prompt}
    if first_frame_b64:
        instance["image"] = {
            "inlineData": {
                "mimeType": first_frame_mime,
                "data": first_frame_b64,
            }
        }
    if last_frame_b64:
        instance["lastFrame"] = {
            "inlineData": {
                "mimeType": last_frame_mime,
                "data": last_frame_b64,
            }
        }

    # 构建 parameters（可选参数）
    # Start with values from the 'parameters' dict passed verbatim in the tool definition.
    # Individual top-level metadata keys (aspect_ratio, seconds, …) take precedence.
    raw_parameters: Dict[str, Any] = {}
    if isinstance(metadata.get("parameters"), dict):
        raw_parameters = dict(metadata["parameters"])

    parameters: Dict[str, Any] = dict(raw_parameters)

    # 宽高比 — top-level field overrides parameters.aspectRatio
    aspect_ratio = metadata.get("aspect_ratio") or metadata.get("aspectRatio")
    if not aspect_ratio:
        # 尝试从 size 解析
        size = str(metadata.get("size") or "")
        if size:
            aspect_ratio = _derive_aspect_ratio_from_size(size)
    if aspect_ratio:
        parameters["aspectRatio"] = aspect_ratio

    # 视频时长（秒）— top-level field overrides parameters.durationSeconds
    seconds_raw = metadata.get("seconds") or metadata.get("durationSeconds")
    if seconds_raw is not None:
        try:
            parameters["durationSeconds"] = int(float(seconds_raw))
        except (ValueError, TypeError):
            pass

    # 生成数量 — top-level field overrides parameters.sampleCount
    n_raw = metadata.get("sampleCount")
    if n_raw is not None:
        try:
            parameters["sampleCount"] = int(n_raw)
        except (ValueError, TypeError):
            pass

    # personGeneration — top-level field overrides parameters.personGeneration
    person_generation = metadata.get("person_generation") or metadata.get("personGeneration")
    if person_generation:
        parameters["personGeneration"] = person_generation

    # resolution — top-level field overrides parameters.resolution
    resolution = metadata.get("resolution")
    if resolution:
        parameters["resolution"] = resolution

    body: Dict[str, Any] = {
        "instances": [instance],
    }
    if parameters:
        body["parameters"] = parameters

    return body


def _derive_aspect_ratio_from_size(size: str) -> str:
    """
    从 WxH 格式的尺寸字符串推导宽高比。

    Args:
        size: 尺寸字符串，如 "1920x1080"

    Returns:
        宽高比字符串，如 "16:9"；无法解析时返回空字符串
    """
    from math import gcd
    _ASPECT_RATIO_MAP = {
        (16, 9): "16:9",
        (9, 16): "9:16",
        (1, 1): "1:1",
        (4, 3): "4:3",
        (3, 4): "3:4",
        (3, 2): "3:2",
        (2, 3): "2:3",
        (21, 9): "21:9",
        (9, 21): "9:21",
    }
    try:
        normalized = size.strip().lower()
        if "x" in normalized:
            parts = normalized.split("x", 1)
            w, h = int(parts[0].strip()), int(parts[1].strip())
            if w > 0 and h > 0:
                g = gcd(w, h)
                ratio = (w // g, h // g)
                return _ASPECT_RATIO_MAP.get(ratio, "")
    except (ValueError, TypeError):
        pass
    return ""


# =============================================================================
# API 调用: 创建视频生成任务
# =============================================================================

def _create_veo_operation(
    api_key: str,
    base_url: str,
    model: str,
    request_body: Dict[str, Any],
) -> str:
    """
    调用 POST /v1beta/models/{model}:predictLongRunning 创建视频生成任务。

    Args:
        api_key:      Gemini API Key
        base_url:     API 基础 URL（不含 /v1beta）
        model:        模型名称，如 "veo-3.1-generate-preview"
        request_body: Veo 请求体

    Returns:
        operation_name 字符串（如 "operations/xxx"）

    Raises:
        RuntimeError: API 返回错误时
    """
    url = f"{base_url.rstrip('/')}/v1beta/models/{model}:predictLongRunning"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    payload_str = json.dumps(request_body, ensure_ascii=False)

    with httpx.Client(timeout=60) as client:
        response = client.post(url, content=payload_str, headers=headers)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Gemini Veo CreateOperation error ({response.status_code}): {response.text}"
        )

    data = response.json()
    operation_name = data.get("name", "")
    if not operation_name:
        raise RuntimeError(
            f"Gemini Veo CreateOperation returned no operation name: {data}"
        )
    return operation_name


# =============================================================================
# 视频下载并保存到 storage
# =============================================================================

def _download_and_store_video(uri: str, api_key: str, video_id: str) -> str:
    """
    从 Gemini 视频 URI 下载视频内容（需要附加 API Key），
    将视频保存到配置的 storage backend，并返回可访问的 URL。

    Gemini 视频 URI 格式：
      https://generativelanguage.googleapis.com/v1beta/files/{file_id}
    下载需要附加 &key={api_key} 查询参数（或 ?key=...）。

    Args:
        uri:      Gemini 返回的视频 URI（不含 key 参数）
        api_key:  Gemini API Key
        video_id: 视频唯一标识（用于生成存储文件名）

    Returns:
        可访问的视频 URL（本地: /v1/files/xxx.mp4；S3: presigned URL 或公开 URL）

    Raises:
        RuntimeError: 下载失败时
    """
    from app.storage.factory import get_storage_backend

    # 拼接下载 URL：在查询参数中加入 API Key
    separator = "&" if "?" in uri else "?"
    download_url = f"{uri}{separator}key={api_key}"

    with httpx.Client(timeout=300, follow_redirects=True) as client:
        response = client.get(download_url)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Gemini Veo video download error ({response.status_code}): {response.text[:500]}"
        )

    video_bytes = response.content
    content_type = response.headers.get("content-type", "video/mp4")

    # 根据 Content-Type 决定文件扩展名
    ext = "mp4"
    if "webm" in content_type:
        ext = "webm"
    elif "quicktime" in content_type or "mov" in content_type:
        ext = "mov"

    filename = f"{video_id}.{ext}"

    storage = get_storage_backend()
    stored_url = storage.write_binary(filename, video_bytes, content_type)

    return stored_url


# =============================================================================
# API 调用: 轮询操作结果
# =============================================================================

def _poll_veo_operation(
    api_key: str,
    base_url: str,
    operation_name: str,
    poll_timeout: Optional[int] = None,
) -> Tuple[List[str], Dict[str, int]]:
    """
    轮询 GET /v1beta/{operation_name} 直到视频生成完成。
    完成后下载视频并保存到 storage，返回可访问的 URL 列表。

    Args:
        api_key:        Gemini API Key
        base_url:       API 基础 URL（不含 /v1beta）
        operation_name: CreateOperation 返回的操作名称

    Returns:
        (video_urls, usage_dict)
          video_urls: 保存到 storage 后的可访问 URL 列表
          usage_dict: 包含 prompt_tokens / completion_tokens / total_tokens

    Raises:
        RuntimeError: 任务失败或超时
    """
    # operation_name 格式：可能是 "operations/xxx" 或完整路径
    # 直接拼接到 /v1beta/ 下
    if operation_name.startswith("operations/"):
        poll_url = f"{base_url.rstrip('/')}/v1beta/{operation_name}"
    else:
        # 如果已经是完整路径，直接使用
        poll_url = f"{base_url.rstrip('/')}/v1beta/{operation_name}"

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    max_wait = poll_timeout or _POLL_MAX_WAIT_S
    deadline = time.time() + max_wait

    with httpx.Client(timeout=60) as client:
        while time.time() < deadline:
            response = client.get(poll_url, headers=headers)

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Gemini Veo PollOperation error ({response.status_code}): {response.text}"
                )

            data = response.json()
            is_done = data.get("done", False)

            if is_done:
                # 检查是否有错误
                error = data.get("error")
                if error:
                    raise RuntimeError(
                        f"Gemini Veo operation failed: {json.dumps(error, ensure_ascii=False)}"
                    )

                # 解析生成的视频 URI
                response_data = data.get("response", {})
                generated_samples = response_data.get("generateVideoResponse", {}).get(
                    "generatedSamples", []
                )

                video_uris: List[str] = []
                for sample in generated_samples:
                    uri = sample.get("video", {}).get("uri", "")
                    if uri:
                        video_uris.append(uri)

                if not video_uris:
                    raise RuntimeError(
                        f"Gemini Veo operation succeeded but no video URIs found: {data}"
                    )

                # 下载视频并保存到 storage，用存储后的 URL 替换原始 Gemini URI
                stored_urls: List[str] = []
                for idx, uri in enumerate(video_uris):
                    # 生成唯一文件名（基于 operation_name + 索引）
                    safe_op = operation_name.replace("/", "_").replace(":", "_")
                    video_id = f"{safe_op}_{idx}" if idx > 0 else safe_op
                    # 截断过长的名称
                    if len(video_id) > 80:
                        video_id = video_id[-80:]

                    try:
                        stored_url = _download_and_store_video(uri, api_key, video_id)
                        stored_urls.append(stored_url)
                    except Exception as exc:
                        # 下载失败时回退到原始 Gemini URI（加上 API Key 供客户端访问）
                        separator = "&" if "?" in uri else "?"
                        stored_urls.append(f"{uri}{separator}key={api_key}")

                usage_dict = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
                return stored_urls, usage_dict

            time.sleep(_POLL_INTERVAL_S)

    raise RuntimeError(
        f"Gemini Veo operation {operation_name} timed out after {_POLL_MAX_WAIT_S}s"
    )


# =============================================================================
# 主入口: 执行视频生成
# =============================================================================

def execute_veo_video_generation(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Message],
    metadata: Dict[str, Any],
) -> ChatResponse:
    """
    执行 Gemini Veo 视频生成并返回 ChatResponse。

    Args:
        api_key:   Gemini API Key
        base_url:  API 基础 URL（不含 /v1beta，如 https://generativelanguage.googleapis.com）
        model:     模型名称（如 "veo-3.1-generate-preview"）
        messages:  消息列表
        metadata:  请求 metadata（视频生成参数）

    Returns:
        ChatResponse，message.content 为 JSON 格式的 video_generation_call 列表

    Raises:
        RuntimeError: API 错误或任务失败
    """
    # 构建请求体
    request_body = _build_veo_request(messages, metadata)

    # 创建异步操作
    operation_name = _create_veo_operation(
        api_key=api_key,
        base_url=base_url,
        model=model,
        request_body=request_body,
    )

    # 轮询结果
    video_uris, usage_dict = _poll_veo_operation(
        api_key=api_key,
        base_url=base_url,
        operation_name=operation_name,
        poll_timeout=metadata.get('timeout'),
    )

    video_items = [
        {
            "type": "video_generation_call",
            "status": "completed",
            "result": uri,
            "file_type": "mp4",
        }
        for uri in video_uris
    ]

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(video_items, ensure_ascii=False),
    )

    # Extract video metadata from request parameters for usage tracking
    # Apply defaults when the user didn't specify values:
    #   aspect_ratio → 16:9, resolution → 720p, seconds → 8
    parameters = request_body.get("parameters", {})
    video_aspect_ratio = parameters.get("aspectRatio", "") or "16:9"
    video_seconds = parameters.get("durationSeconds", 0) or 8
    # Derive resolution tier from metadata if available
    video_resolution = metadata.get("resolution", "") or "720p"
    # Determine audio flag: Veo generates audio by default (True),
    # only False when user explicitly sets generate_audio=false / generateAudio=false
    video_has_audio = parameters.get("generateAudio", True)

    return ChatResponse(
        id=gen_id("vid"),
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
            extra={
                'output_video_number': len(video_uris) if video_uris else 1,
                'output_video_resolution': video_resolution,
                'output_video_aspect': video_aspect_ratio,
                'output_video_seconds': float(video_seconds),
                'output_video_audio': bool(video_has_audio),
            },
        ),
        created=int(time.time()),
        provider="gemini",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

def stream_veo_video_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    执行 Gemini Veo 视频生成并以 StreamChunk 格式 yield 结果。

    Veo 视频生成是异步长运行操作（创建 → 轮询），此函数将同步调用结果
    转换为兼容 Responses API 适配器的 SSE 事件序列：

    1. role marker  (delta_role="assistant")  → 触发 format_stream_start
    2. response.output_item.added  (generating)
    3. response.output_item.done   (completed, result=<video_uri>)
    4. response.completed

    Args:
        chat_fn: provider.chat 非流式方法
        request: ChatRequest
    """
    response = chat_fn(request)
    response_id = response.id
    model = response.model

    # 解析视频列表
    videos: List[Dict[str, Any]] = []
    if response.choices and response.choices[0].message:
        msg = response.choices[0].message
        raw = (
            msg.content
            if isinstance(msg.content, str)
            else (msg.get_text_content() or "[]")
        )
        try:
            videos = json.loads(raw) if isinstance(raw, str) else []
        except (json.JSONDecodeError, TypeError):
            videos = []

    # Role marker
    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    # 每个视频一个 output item
    for i, vid in enumerate(videos):
        result = vid.get("result", "")
        call_id = f"{response_id}-{i}" if i > 0 else response_id
        output_index = i

        item_added = {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "type": "video_generation_call",
                "id": call_id,
                "status": "generating",
                "result": None,
            },
        }
        item_done = {
            "type": "response.output_item.done",
            "output_index": output_index,
            "item": {
                "type": "video_generation_call",
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

    # response.completed
    usage_dict: Dict[str, Any] = {}
    if response.usage:
        usage_dict = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    output_items = [
        {
            "type": "video_generation_call",
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
