"""
阿里云百炼视频生成模块 (Bailian Happyhorse Video Generation)

通过 Dashscope 异步视频生成 API 生成视频，兼容 /v1/responses video_generation 工具。

支持的模型：
- happyhorse-1.0-t2v: 文生视频 (Text-to-Video)
- happyhorse-1.0-i2v: 图生视频 (Image-to-Video, first_frame)
- happyhorse-1.0-r2v: 参考对象生视频 (Reference-to-Video)
- happyhorse-1.0-video-edit: 视频编辑 (Video Edit)

流程：
1. 发起请求: POST dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis
   Header: X-DashScope-Async: enable
2. 获取 task_id
3. 轮询结果: GET dashscope.aliyuncs.com/api/v1/tasks/{task_id}
   直到 task_status 为 SUCCEEDED, FAILED, CANCELED 或 UNKNOWN

/v1/responses 工具请求示例:
{
    "type": "video_generation",
    "prompt": "一座微型城市在夜晚焕发生机",
    "resolution": "720P",
    "ratio": "16:9",
    "duration": 5,
    "reference_images": [{"url": "https://...", "type": "first_frame"}]
}

API 文档:
https://help.aliyun.com/document_detail/2866784.html
"""
from __future__ import annotations

import json
import time
import logging
from typing import Any, Dict, Generator, List, Optional

import httpx

from app.abstraction.chat import (
    ChatChoice,
    ChatRequest,
    ChatResponse,
    FinishReason,
    UsageInfo,
)
from app.abstraction.messages import ContentBlock, Message, MessageRole
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.providers.video_size_utils import resolve_video_size
from app.utils import gen_id

logger = logging.getLogger(__name__)

# =============================================================================
# 视频生成 API 端点
# =============================================================================

DASHSCOPE_DOMAIN = "https://dashscope.aliyuncs.com"
VIDEO_SYNTHESIS_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"
TASK_QUERY_PATH = "/api/v1/tasks"

# 默认轮询参数
_POLL_INTERVAL_S = 5       # 轮询间隔（秒）
_POLL_MAX_WAIT_S = 600     # 最大等待时间（秒）

# =============================================================================
# 任务状态常量
# =============================================================================

TASK_STATUS_PENDING = "PENDING"
TASK_STATUS_RUNNING = "RUNNING"
TASK_STATUS_SUCCEEDED = "SUCCEEDED"
TASK_STATUS_FAILED = "FAILED"
TASK_STATUS_CANCELED = "CANCELED"
TASK_STATUS_UNKNOWN = "UNKNOWN"

# 终态集合（任务不会再变动的状态）
TASK_TERMINAL_STATUSES = frozenset({
    TASK_STATUS_SUCCEEDED,
    TASK_STATUS_FAILED,
    TASK_STATUS_CANCELED,
    TASK_STATUS_UNKNOWN,
})

# 状态 → 图标映射（流式输出用）
TASK_STATUS_EMOJI = {
    TASK_STATUS_PENDING: "⏳",
    TASK_STATUS_RUNNING: "🔄",
    TASK_STATUS_SUCCEEDED: "✅",
    TASK_STATUS_FAILED: "❌",
    TASK_STATUS_CANCELED: "🚫",
    TASK_STATUS_UNKNOWN: "❓",
}


def _resolve_video_api_url(domain: Optional[str] = None) -> str:
    """Resolve the video synthesis API URL from domain or use default."""
    base = (domain or DASHSCOPE_DOMAIN).rstrip("/")
    return f"{base}{VIDEO_SYNTHESIS_PATH}"


def _resolve_task_query_url(domain: Optional[str] = None) -> str:
    """Resolve the task query API base URL from domain or use default."""
    base = (domain or DASHSCOPE_DOMAIN).rstrip("/")
    return f"{base}{TASK_QUERY_PATH}"


# =============================================================================
# 视频生成模型检测
# =============================================================================

# Known Happyhorse video generation model name prefixes (case-insensitive).
_HAPPYHORSE_MODEL_PREFIXES = (
    "happyhorse-",
)


def is_happyhorse_video_model(model: str) -> bool:
    """
    Check if the model is a Happyhorse video generation model.

    Matches model names whose prefix starts with 'happyhorse-', e.g.:
      - happyhorse-1.0-t2v
      - happyhorse-1.0-i2v
      - happyhorse-1.0-r2v
      - happyhorse-1.0-video-edit

    Args:
        model: Model name (case-insensitive)

    Returns:
        True if the model is a Happyhorse video generation model
    """
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _HAPPYHORSE_MODEL_PREFIXES)


def has_video_generation_tool(request: ChatRequest) -> bool:
    """
    Check if the request was sent with a ``video_generation`` tool.

    When the Responses API adapter parses a ``video_generation`` tool entry,
    it stores ``_video_generation=True`` in ``request.metadata``.

    Args:
        request: The chat request to check

    Returns:
        True if the request was sent with a ``video_generation`` tool.
    """
    return bool(request.metadata.get("_video_generation"))


# =============================================================================
# 辅助函数: 构建 Dashscope 请求体
# =============================================================================

def _build_happyhorse_file_id_aliases(
    file_id_media_map: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Build ``{file_id: "[Image N]"}`` / ``{file_id: "[Video N]"}`` / ``{file_id: "[Audio N]"}``
    substitution map from the ``file_id_media_map`` built by the Responses adapter.

    Insertion order of ``file_id_media_map`` (a Python 3.7+ ordered dict) is preserved,
    so the numbering (Image 1, Image 2, …) matches the order in which the blocks appeared
    in the original ``input`` array.

    Args:
        file_id_media_map: Adapter-built mapping.  Each value is a dict like
            ``{'type': 'image', 'url': '...', 'role': '...'}``.

    Returns:
        ``{file_id: "[Image 1]", file_id2: "[Image 2]", …}`` with consistent numbering
        across all media types.
    """
    sub_map: Dict[str, str] = {}
    if not file_id_media_map:
        return sub_map

    img_n, vid_n, aud_n = 1, 1, 1

    for fid, info in file_id_media_map.items():
        if not isinstance(info, dict):
            continue
        mtype = info.get("type", "")
        if mtype == "image":
            sub_map[fid] = f"[Image {img_n}]"
            img_n += 1
        elif mtype in ("video", "input_video"):
            sub_map[fid] = f"[Video {vid_n}]"
            vid_n += 1
        elif mtype in ("audio", "input_audio"):
            sub_map[fid] = f"[Audio {aud_n}]"
            aud_n += 1
        # Unknown types are intentionally skipped ─ no alias is generated.

    return sub_map


def _apply_happyhorse_file_sub(text: str, sub_map: Dict[str, str]) -> str:
    """
    Replace ``{{file_id}}`` placeholders with their Happyhorse alias
    (e.g. ``[Image 1]``, ``[Video 2]``).

    Unmatched placeholders are left unchanged.

    Args:
        text:    Raw prompt text (may contain ``{{image_1}}``, ``{{vid}}``, …).
        sub_map: ``{file_id: "[Image N]"}`` map from :func:`_build_happyhorse_file_id_aliases`.

    Returns:
        Substituted text.
    """
    if not sub_map or not text:
        return text
    import re
    def _replace(m: "re.Match") -> str:
        return sub_map.get(m.group(1), m.group(0))
    return re.sub(r"\{\{([^}]+)\}\}", _replace, text)


def _extract_text_prompt(
    messages: List[Message],
    sub_map: Optional[Dict[str, str]] = None,
) -> str:
    """
    Extract the text prompt from messages list.

    Concatenates all text content blocks from user messages into a single prompt.
    When ``sub_map`` is provided, ``{{file_id}}`` placeholders in each text block
    are replaced with their Happyhorse alias (e.g. ``[Image 1]``).

    Args:
        messages: List of messages
        sub_map:  Optional ``{file_id: "[Image N]"}`` substitution map

    Returns:
        Combined prompt text
    """
    prompt_parts: List[str] = []
    for msg in messages:
        if msg.role == MessageRole.USER:
            if isinstance(msg.content, str):
                text = msg.content
                if sub_map:
                    text = _apply_happyhorse_file_sub(text, sub_map)
                prompt_parts.append(text)
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if sub_map:
                                text = _apply_happyhorse_file_sub(text, sub_map)
                            prompt_parts.append(text)
                    elif hasattr(block, "type"):
                        # ContentBlock.type may be a ContentType enum or a plain string
                        block_type = block.type
                        if isinstance(block_type, str):
                            is_text = (block_type == "text")
                        else:
                            is_text = (getattr(block_type, 'value', None) == "text")
                        if is_text:
                            text = block.text or ""
                            if sub_map:
                                text = _apply_happyhorse_file_sub(text, sub_map)
                            prompt_parts.append(text)
    return "".join(prompt_parts).strip()


def _build_media_list(
    messages: List[Message],
    metadata: dict,
    model: str,
) -> Optional[List[Dict[str, str]]]:
    """
    Build the media list from request messages and metadata.

    Extracts video and image URLs from message content blocks (e.g. ``input_video``,
    ``input_image`` blocks in Responses API format) and from metadata fields
    (``reference_images``, ``reference_videos``, ``first_frame_url``, ``file_id_media_map``),
    then builds the Dashscope ``media`` array with the correct ``type`` per model.

    Dashscope media type mapping per model
    ---------------------------------------
    - happyhorse-1.0-t2v:     no media
    - happyhorse-1.0-i2v:     first image → "first_frame"
    - happyhorse-1.0-r2v:     all images → "reference_image" (max 9)
    - happyhorse-1.0-video-edit: video → "video", images → "reference_image"

    Media already present in the list (by URL) is not duplicated.

    Args:
        messages: Request messages (may contain VIDEO_URL / IMAGE_URL content blocks)
        metadata: Request metadata dict
        model: Model name (used to determine the Dashscope ``type`` for each media entry)

    Returns:
        List of media dicts or None if no media specified
    """
    media_list: List[Dict[str, str]] = []
    _seen_urls: set = set()

    def _add(type_: str, url_: str) -> None:
        """Add a media entry if its URL hasn't been seen yet."""
        if url_ and url_ not in _seen_urls:
            _seen_urls.add(url_)
            media_list.append({"type": type_, "url": url_})

    # ── 1. Extract media from message content blocks ──────────────────────────
    # When the Responses API adapter parses ``input_video`` / ``input_image``
    # blocks inside a user message, they become ContentBlock objects with
    # type=ContentType.VIDEO_URL / IMAGE_URL on the Message content list.
    #
    # Model → Dashscope type mapping
    model_lower = model.lower()
    if model_lower.startswith("happyhorse-1.0-i2v"):
        _image_ds_type = "first_frame"
        _video_ds_type = "first_frame"  # Should not happen, but handle cleanly
    elif model_lower.startswith("happyhorse-1.0-r2v"):
        _image_ds_type = "reference_image"
        _video_ds_type = "reference_image"  # Should not happen
    elif model_lower.startswith("happyhorse-1.0-video-edit"):
        _image_ds_type = "reference_image"
        _video_ds_type = "video"
    else:
        _image_ds_type = "reference_image"
        _video_ds_type = "video"

    for msg in messages:
        if msg.role != MessageRole.USER:
            continue
        content = msg.content
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                blk_type = block.get("type", "")
                blk_url = block.get("url", "")
                if blk_type in ("video_url", "input_video") and blk_url:
                    _add(_video_ds_type, blk_url)
                elif blk_type in ("image_url", "input_image") and blk_url:
                    _add(_image_ds_type, blk_url)
                elif blk_type in ("video_base64",):
                    continue  # Dashscope async API expects URLs, not base64
                elif blk_type in ("image_base64",):
                    continue
            elif isinstance(block, ContentBlock):
                import app.abstraction.messages as _msg_mod
                # Read role from ContentBlock.role attribute (set by adapter from block dict)
                block_role = getattr(block, 'role', None) or ''
                if block.type == _msg_mod.ContentType.VIDEO_URL and block.url:
                    if block_role == 'first_frame':
                        _add('first_frame', block.url)
                    else:
                        _add(_video_ds_type, block.url)
                elif block.type == _msg_mod.ContentType.IMAGE_URL and block.url:
                    if block_role == 'first_frame':
                        _add('first_frame', block.url)
                    elif block_role == 'reference_image':
                        _add('reference_image', block.url)
                    else:
                        _add(_image_ds_type, block.url)

    # ── 2. file_id_media_map (adapter-built mapping from FileId-bearing blocks) ──
    file_id_media_map = metadata.get("file_id_media_map")
    if isinstance(file_id_media_map, dict):
        for fid, info in file_id_media_map.items():
            if not isinstance(info, dict):
                continue
            media_type = info.get("type", "")
            url = info.get("url", "")
            if not url:
                continue
            role = info.get("role", "")

            if media_type == "image":
                if role == "first_frame":
                    _add("first_frame", url)
                else:
                    _add("reference_image", url)
            elif media_type in ("video", "input_video"):
                if role == "first_frame":
                    _add("first_frame", url)
                else:
                    _add("video", url)

    return media_list if media_list else None


def _build_video_request_body(
    model: str,
    messages: List[Message],
    metadata: dict,
) -> Dict[str, Any]:
    """
    Build the Dashscope video-synthesis request body.

    Args:
        model: Model name
        messages: Messages list (for extracting prompt)
        metadata: Request metadata with video generation parameters

    Returns:
        Dashscope-compatible request body dict
    """
    # Build {{file_id}} → [Image N] / [Video N] / [Audio N] substitution map
    # from the file_id_media_map built by the Responses adapter.
    file_id_media_map = metadata.get("file_id_media_map")
    sub_map = _build_happyhorse_file_id_aliases(file_id_media_map)

    prompt = _extract_text_prompt(messages, sub_map=sub_map if sub_map else None)

    body: Dict[str, Any] = {
        "model": model,
        "input": {
            "prompt": prompt,
        },
    }

    # Build media list from input content blocks and file_id_media_map
    media = _build_media_list(messages, metadata, model)
    if media:
        body["input"]["media"] = media

    # Parameter mapping with "size" support
    # "size" is a unified field that maps to both resolution and aspect_ratio
    # via resolve_video_size().  Explicit resolution / aspect_ratio take priority.
    parameters: Dict[str, Any] = {}

    resolution = metadata.get("resolution")
    ratio = metadata.get("aspect_ratio")
    size = metadata.get("size")

    # Derive resolution / ratio from size when not explicitly set
    if size and (not resolution or not ratio):
        derived_ar, derived_tier = resolve_video_size(str(size))
        if not ratio and derived_ar:
            ratio = derived_ar
        if not resolution and derived_tier:
            resolution = derived_tier

    # Happyhorse defaults: resolution=1080P, ratio=16:9
    if not resolution and not size:
        resolution = "1080P"
    if not ratio and not size:
        ratio = "16:9"

    if resolution:
        # Normalize resolution to uppercase, supporting both "720p" → "720P" and "720P"
        parameters["resolution"] = str(resolution).upper()

    # aspect_ratio → Dashscope "ratio" (e.g. "16:9", "9:16")
    if ratio:
        parameters["ratio"] = str(ratio)

    # seconds → Dashscope "duration"
    seconds = metadata.get("seconds")
    if seconds is not None:
        try:
            parameters["duration"] = int(seconds)
        except (ValueError, TypeError):
            pass

    # watermark 默认为 false
    parameters.setdefault("watermark", False)

    if parameters:
        body["parameters"] = parameters

    return body


# =============================================================================
# 任务轮询
# =============================================================================

def _poll_task(
    api_key: str,
    task_id: str,
    task_query_url: str,
    timeout: int = _POLL_MAX_WAIT_S,
    poll_interval: int = _POLL_INTERVAL_S,
    tracer: Any = None,
) -> Dict[str, Any]:
    """
    Poll the Dashscope task API until completion or timeout.

    Args:
        api_key: API key for Authorization header
        task_id: Task ID to poll
        task_query_url: Base URL for task query endpoint
        timeout: Maximum time to wait in seconds
        poll_interval: Interval between polls in seconds
        tracer: Tracer for creating poll span

    Returns:
        Final task result dict

    Raises:
        TimeoutError: If polling exceeds timeout
        RuntimeError: If API returns an unexpected error
    """
    start_time = time.time()
    url = f"{task_query_url}/{task_id}"

    _span = None
    if tracer:
        _span = tracer.start_child(task_id, model=task_id, provider_type="bailian", obs_type="span")
    _error: Optional[Exception] = None

    try:
        with httpx.Client(timeout=30) as client:
            poll_count = 0
            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise TimeoutError(
                        f"Video generation task {task_id} timed out after {timeout}s"
                    )

                try:
                    response = client.get(
                        url,
                        headers={"Authorization": f"Bearer {api_key}"},
                    )

                    if response.status_code >= 400:
                        logger.warning(
                            "Task query error (status=%s): %s",
                            response.status_code,
                            response.text,
                        )
                        time.sleep(poll_interval)
                        continue

                    result = response.json()
                    output = result.get("output", {})
                    task_status = output.get("task_status", TASK_STATUS_UNKNOWN)
                    poll_count += 1

                    if _span:
                        _poll_output: Dict[str, Any] = {
                            "task_id": task_id,
                            "task_status": task_status,
                            "elapsed": elapsed,
                            "poll_count": poll_count,
                        }
                        _x_req_id = response.headers.get("x-request-id", "")
                        if _x_req_id:
                            _poll_output["x-request-id"] = _x_req_id
                        _span.log_output(_poll_output)

                    if task_status in TASK_TERMINAL_STATUSES:
                        return result

                    # Still PENDING or RUNNING, continue polling
                    logger.debug(
                        "Task %s status: %s, elapsed: %.1fs",
                        task_id,
                        task_status,
                        elapsed,
                    )
                    time.sleep(poll_interval)

                except httpx.RequestError as e:
                    logger.warning("Task query network error: %s", e)
                    time.sleep(poll_interval)
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# 非流式视频生成
# =============================================================================

def execute_happyhorse_video_generation(
    api_key: str,
    model: str,
    messages: List[Message],
    metadata: dict,
    domain: Optional[str] = None,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute a Happyhorse video generation request (non-streaming).

    1. POST video-synthesis → get task_id
    2. Poll GET tasks/{task_id} until SUCCEEDED/FAILED/CANCELED/UNKNOWN
    3. Return ChatResponse with video URL or error

    Args:
        api_key: Bailian/Dashscope API key
        model: Model name (e.g. "happyhorse-1.0-t2v")
        messages: Request messages
        metadata: Request metadata
        domain: Optional Dashscope domain override

    Returns:
        ChatResponse with video URL or error information

    Raises:
        RuntimeError: If API call or polling fails
    """
    video_url = _resolve_video_api_url(domain)
    task_query_url = _resolve_task_query_url(domain)
    request_body = _build_video_request_body(model, messages, metadata)

    # Determine timeout from model config (default 600s)
    timeout = metadata.get("timeout", _POLL_MAX_WAIT_S)

    logger.info(
        "Initiating Happyhorse video generation: model=%s, prompt_len=%d",
        model,
        len(request_body.get("input", {}).get("prompt", "")),
    )

    # ── Tracing ────────────────────────────────────────────────────────────
    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="bailian", obs_type="generation",input_data=request_body)
        if _child_span:
            _child_span.log_input(request_body)
    _trace_error: Optional[Exception] = None

    try:
        with httpx.Client(timeout=60) as client:
            try:
                response = client.post(
                    video_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "X-DashScope-Async": "enable",
                    },
                    json=request_body,
                )

                if response.status_code >= 400:
                    error_msg = f"Dashscope video-synthesis error ({response.status_code})"
                    try:
                        error_body = response.json()
                        error_msg += f": {json.dumps(error_body, ensure_ascii=False)}"
                    except json.JSONDecodeError:
                        error_msg += f": {response.text}"
                    raise RuntimeError(error_msg)

                result = response.json()
                output = result.get("output", {})
                task_id = output.get("task_id")

                if not task_id:
                    raise RuntimeError(
                        f"No task_id in response: {json.dumps(result, ensure_ascii=False)}"
                    )

                task_status = output.get("task_status", TASK_STATUS_UNKNOWN)
                logger.info(
                    "Video task created: task_id=%s, initial_status=%s",
                    task_id,
                    task_status,
                )

                # If task is already completed synchronously (rare but possible)
                if task_status == TASK_STATUS_SUCCEEDED:
                    video_output_url = output.get("video_url", "")
                    return _build_success_response(
                        model, video_output_url, output, task_id, metadata=metadata, tracer=_child_span
                    )
                elif task_status == TASK_STATUS_FAILED:
                    return _build_failure_response(
                        model, output, task_id, tracer=_child_span
                    )
                elif task_status in (TASK_STATUS_CANCELED, TASK_STATUS_UNKNOWN):
                    return _build_canceled_response(model, task_id, task_status, tracer=_child_span)

            except httpx.RequestError as e:
                raise RuntimeError(f"Dashscope video-synthesis network error: {e}")

        # Poll for completion (run outside the with block since polling uses its own client)
        try:
            final_result = _poll_task(
                api_key=api_key,
                task_id=task_id,
                task_query_url=task_query_url,
                timeout=timeout,
                tracer=_child_span,
            )
        except TimeoutError:
            # Return a response indicating timeout
            return _build_timeout_response(model, task_id, tracer=_child_span)

        final_output = final_result.get("output", {})
        final_status = final_output.get("task_status", TASK_STATUS_UNKNOWN)

        if final_status == TASK_STATUS_SUCCEEDED:
            video_output_url = final_output.get("video_url", "")
            return _build_success_response(
                model, video_output_url, final_output, task_id, metadata=metadata, tracer=_child_span
            )
        elif final_status == TASK_STATUS_FAILED:
            return _build_failure_response(model, final_output, task_id, tracer=_child_span)
        else:
            return _build_canceled_response(model, task_id, final_status, tracer=_child_span)
    except Exception as e:
        _trace_error = e
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)


def _build_video_usage_extra(
    output: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the UsageInfo.extra dict for video generation billing."""
    # Resolution: from metadata first, fall back to happyhorse default
    resolution = metadata.get("resolution")
    if not resolution:
        size = metadata.get("size")
        if size:
            _, derived_tier = resolve_video_size(str(size))
            if derived_tier:
                resolution = derived_tier
    if not resolution:
        resolution = "1080P"
    resolution = str(resolution).upper()

    # Aspect ratio
    ratio = metadata.get("aspect_ratio")
    if not ratio:
        size = metadata.get("size")
        if size:
            derived_ar, _ = resolve_video_size(str(size))
            if derived_ar:
                ratio = derived_ar
    if not ratio:
        ratio = "16:9"
    ratio = str(ratio)

    # Duration
    duration = output.get("output_video_duration") or output.get("duration") or 0
    try:
        dur = float(duration) if duration else 0.0
    except (ValueError, TypeError):
        dur = 0.0

    # Video count from API output
    video_count = output.get("video_count", 1)
    try:
        video_count = int(video_count) if video_count else 1
    except (ValueError, TypeError):
        video_count = 1

    # Determine if audio was generated (SR field in usage indicates resolution,
    # happyhorse doesn't expose audio flag; assume no audio for now)
    has_audio = False

    # Determine if reference video was used
    has_reference_video = _model_uses_reference_video(metadata, model=None)

    return {
        "output_video_number": video_count,
        "output_video_tokens": 0,
        "output_video_resolution": resolution,
        "output_video_aspect": ratio,
        "output_video_seconds": dur,
        "output_video_audio": has_audio,
        "output_video_reference_video": has_reference_video,
    }


def _model_uses_reference_video(metadata: Dict[str, Any], model: Optional[str] = None) -> bool:
    """Check whether the request uses a reference video for tiered pricing."""
    # Check messages content for video blocks
    messages = metadata.get("_messages")
    if messages:
        for msg in messages:
            if isinstance(msg, Message):
                for block in getattr(msg, "content", []) or []:
                    if isinstance(block, dict):
                        if block.get("type") == "input_video":
                            return True
            elif isinstance(msg, dict):
                for block in msg.get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "input_video":
                        return True

    # Check file_id_media_map for video type
    file_id_media_map = metadata.get("file_id_media_map")
    if isinstance(file_id_media_map, dict):
        for info in file_id_media_map.values():
            if isinstance(info, dict) and info.get("type") in ("video", "input_video"):
                return True

    return False


def _build_success_response(
    model: str,
    video_url: str,
    output: Dict[str, Any],
    task_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    tracer: Any = None,
) -> ChatResponse:
    """Build a successful ChatResponse with video URL."""
    if tracer:
        tracer.log_output({"task_id": task_id, "status": "succeeded", "video_url": video_url})

    if metadata is None:
        metadata = {}

    response_id = gen_id("vid-")

    # Resolve output video duration for usage tracking
    duration = output.get("output_video_duration") or output.get("duration")
    try:
        dur = float(duration) if duration else 0.0
    except (ValueError, TypeError):
        dur = 0.0

    extra = _build_video_usage_extra(output, metadata)
    # Override duration from extra (already normalized)
    dur = float(extra.get("output_video_seconds", dur) or 0.0)

    usage = UsageInfo(
        prompt_tokens=0,
        completion_tokens=int(dur) if dur > 0 else 1,
        total_tokens=int(dur) if dur > 0 else 1,
        extra=extra,
    )

    # Build video_generation_call item compatible with Responses API adapter
    video_call_items = [
        {
            "type": "video_generation_call",
            "status": "completed",
            "result": video_url,
        }
    ]
    content = json.dumps(video_call_items, ensure_ascii=False)

    choice = ChatChoice(
        index=0,
        message=Message(role=MessageRole.ASSISTANT, content=content),
        finish_reason=FinishReason.STOP,
    )

    return ChatResponse(
        id=response_id,
        created=int(time.time()),
        model=model,
        choices=[choice],
        usage=usage,
        provider="bailian",
    )


def _build_failure_response(
    model: str,
    output: Dict[str, Any],
    task_id: str,
    tracer: Any = None,
) -> ChatResponse:
    """Build a ChatResponse for a failed video generation task."""
    if tracer:
        tracer.log_output({"task_id": task_id, "status": "failed", "code": output.get("code", "UnknownError"), "message": output.get("message", "Video generation failed")})

    response_id = gen_id("vid-")
    code = output.get("code", "UnknownError")
    message = output.get("message", "Video generation failed")

    video_call_items = [
        {
            "type": "video_generation_call",
            "status": "failed",
            "result": "",
            "error": {"code": code, "message": message, "task_id": task_id},
        }
    ]
    content = json.dumps(video_call_items, ensure_ascii=False)

    choice = ChatChoice(
        index=0,
        message=Message(role=MessageRole.ASSISTANT, content=content),
        finish_reason=FinishReason.ERROR,
    )

    return ChatResponse(
        id=response_id,
        created=int(time.time()),
        model=model,
        choices=[choice],
        usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        provider="bailian",
    )


def _build_canceled_response(
    model: str,
    task_id: str,
    task_status: str,
    tracer: Any = None,
) -> ChatResponse:
    """Build a ChatResponse for a canceled/unknown video generation task."""
    if tracer:
        tracer.log_output({"task_id": task_id, "status": task_status.lower()})

    response_id = gen_id("vid-")

    status_texts = {
        TASK_STATUS_CANCELED: "任务已取消",
        TASK_STATUS_UNKNOWN: "任务状态未知",
    }
    status_text = status_texts.get(task_status, f"任务状态: {task_status}")

    video_call_items = [
        {
            "type": "video_generation_call",
            "status": task_status.lower(),
            "result": "",
            "error": {"message": status_text, "task_id": task_id},
        }
    ]
    content = json.dumps(video_call_items, ensure_ascii=False)

    choice = ChatChoice(
        index=0,
        message=Message(role=MessageRole.ASSISTANT, content=content),
        finish_reason=FinishReason.ERROR,
    )

    return ChatResponse(
        id=response_id,
        created=int(time.time()),
        model=model,
        choices=[choice],
        usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        provider="bailian",
    )


def _build_timeout_response(
    model: str,
    task_id: str,
    tracer: Any = None,
) -> ChatResponse:
    """Build a ChatResponse for a timed-out video generation task."""
    if tracer:
        tracer.log_output({"task_id": task_id, "status": "timeout"})

    response_id = gen_id("vid-")

    video_call_items = [
        {
            "type": "video_generation_call",
            "status": "timeout",
            "result": "",
            "error": {
                "message": "视频生成超时，请稍后使用任务ID查询结果",
                "task_id": task_id,
            },
        }
    ]
    content = json.dumps(video_call_items, ensure_ascii=False)

    choice = ChatChoice(
        index=0,
        message=Message(role=MessageRole.ASSISTANT, content=content),
        finish_reason=FinishReason.ERROR,
    )

    return ChatResponse(
        id=response_id,
        created=int(time.time()),
        model=model,
        choices=[choice],
        usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        provider="bailian",
    )


def _format_video_markdown(video_url: str) -> str:
    """Format video URL as markdown for display."""
    if not video_url:
        return "(视频URL未返回)"
    return f"[点击查看视频]({video_url})"


# =============================================================================
# 流式视频生成
# =============================================================================

def stream_video_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    Stream video generation progress as SSE events.

    This wraps the non-streaming ``execute_happyhorse_video_generation`` call
    and yields status updates as streaming chunks.

    Args:
        chat_fn: The provider's ``chat`` method (for executing the actual request)
        request: The chat request

    Yields:
        StreamChunk objects with progress updates and final result
    """
    response_id = gen_id("vid-")
    model = request.model

    # Step 1: Build the request body and initiate the async job
    video_url = _resolve_video_api_url(request.metadata.get("_domain"))
    task_query_url = _resolve_task_query_url(request.metadata.get("_domain"))

    # Extract api_key from metadata (set by base.py before calling)
    api_key = request.metadata.get("_api_key", "")
    timeout = request.metadata.get("timeout", _POLL_MAX_WAIT_S)

    request_body = _build_video_request_body(
        model, request.messages, request.metadata
    )

    # Yield initial progress
    yield StreamChunk(
        event=StreamEventType.DELTA,
        id=response_id,
        model=model,
        delta_content="🎬 正在提交视频生成任务...\n",
    )

    with httpx.Client(timeout=60) as client:
        try:
            response = client.post(
                video_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                },
                json=request_body,
            )

            if response.status_code >= 400:
                error_msg = f"Dashscope API error ({response.status_code})"
                try:
                    error_body = response.json()
                    error_msg += f": {json.dumps(error_body, ensure_ascii=False)}"
                except json.JSONDecodeError:
                    error_msg += f": {response.text}"
                yield StreamChunk(
                    event=StreamEventType.DELTA,
                    id=response_id,
                    model=model,
                    delta_content=f"\n❌ {error_msg}\n",
                )
                yield StreamChunk(
                    event=StreamEventType.DONE,
                    id=response_id,
                    model=model,
                    finish_reason=FinishReason.ERROR,
                    usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                )
                return

            result = response.json()
            output = result.get("output", {})
            task_id = output.get("task_id")

            if not task_id:
                yield StreamChunk(
                    event=StreamEventType.DELTA,
                    id=response_id,
                    model=model,
                    delta_content="\n❌ 未获取到任务ID\n",
                )
                yield StreamChunk(
                    event=StreamEventType.DONE,
                    id=response_id,
                    model=model,
                    finish_reason=FinishReason.ERROR,
                    usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                )
                return

            task_status = output.get("task_status", TASK_STATUS_UNKNOWN)

        except httpx.RequestError as e:
            yield StreamChunk(
                event=StreamEventType.DELTA,
                id=response_id,
                model=model,
                delta_content=f"\n❌ 网络错误: {e}\n",
            )
            yield StreamChunk(
                event=StreamEventType.DONE,
                id=response_id,
                model=model,
                finish_reason=FinishReason.ERROR,
                usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )
            return

    yield StreamChunk(
        event=StreamEventType.DELTA,
        id=response_id,
        model=model,
        delta_content=f"✅ 任务已提交 (ID: {task_id})\n⏳ 正在生成视频...\n",
    )

    # Step 2: Poll for completion with progress updates
    start_time = time.time()
    last_status = task_status
    url = f"{task_query_url}/{task_id}"

    with httpx.Client(timeout=30) as poll_client:
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                yield StreamChunk(
                    event=StreamEventType.DELTA,
                    id=response_id,
                    model=model,
                    delta_content=(
                        f"\n⏰ 视频生成超时\n任务ID: {task_id}\n"
                        f"请稍后使用任务ID查询结果\n"
                    ),
                )
                yield StreamChunk(
                    event=StreamEventType.DONE,
                    id=response_id,
                    model=model,
                    finish_reason=FinishReason.ERROR,
                    usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                )
                return

            try:
                poll_response = poll_client.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                )

                if poll_response.status_code >= 400:
                    time.sleep(_POLL_INTERVAL_S)
                    continue

                poll_result = poll_response.json()
                poll_output = poll_result.get("output", {})
                current_status = poll_output.get("task_status", TASK_STATUS_UNKNOWN)

                # Yield status change updates
                if current_status != last_status:
                    emoji = TASK_STATUS_EMOJI.get(current_status, "ℹ️")
                    yield StreamChunk(
                        event=StreamEventType.DELTA,
                        id=response_id,
                        model=model,
                        delta_content=f"\n{emoji} 状态: {current_status} ({elapsed:.0f}s)\n",
                    )
                    last_status = current_status

                if current_status == TASK_STATUS_SUCCEEDED:
                    video_output_url = poll_output.get("video_url", "")

                    # Build the extra dict for billing using metadata from request
                    extra = _build_video_usage_extra(poll_output, request.metadata)
                    dur = float(extra.get("output_video_seconds", 0) or 0)

                    yield StreamChunk(
                        event=StreamEventType.DELTA,
                        id=response_id,
                        model=model,
                        delta_content=(
                            f"\n🎉 视频生成完成！\n"
                            f"时长: {dur}s\n\n"
                            f"{_format_video_markdown(video_output_url)}\n"
                        ),
                    )
                    yield StreamChunk(
                        event=StreamEventType.DONE,
                        id=response_id,
                        model=model,
                        finish_reason=FinishReason.STOP,
                        usage=UsageInfo(
                            prompt_tokens=0,
                            completion_tokens=int(dur) if dur > 0 else 1,
                            total_tokens=int(dur) if dur > 0 else 1,
                            extra=extra,
                        ),
                    )
                    return

                elif current_status == TASK_STATUS_FAILED:
                    code = poll_output.get("code", "UnknownError")
                    message = poll_output.get("message", "Video generation failed")
                    yield StreamChunk(
                        event=StreamEventType.DELTA,
                        id=response_id,
                        model=model,
                        delta_content=f"\n错误码: {code}\n错误信息: {message}\n",
                    )
                    yield StreamChunk(
                        event=StreamEventType.DONE,
                        id=response_id,
                        model=model,
                        finish_reason=FinishReason.ERROR,
                        usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                    )
                    return

                elif current_status in (TASK_STATUS_CANCELED, TASK_STATUS_UNKNOWN):
                    yield StreamChunk(
                        event=StreamEventType.DELTA,
                        id=response_id,
                        model=model,
                        delta_content=f"\n任务状态: {current_status}\n任务ID: {task_id}\n",
                    )
                    yield StreamChunk(
                        event=StreamEventType.DONE,
                        id=response_id,
                        model=model,
                        finish_reason=FinishReason.ERROR,
                        usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                    )
                    return

                # Still pending/running, wait and continue
                time.sleep(_POLL_INTERVAL_S)

            except httpx.RequestError as e:
                logger.warning("Polling network error: %s", e)
                time.sleep(_POLL_INTERVAL_S)