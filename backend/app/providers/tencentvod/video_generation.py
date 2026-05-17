"""
腾讯云点播视频生成模块 (TencentVOD Video Generation)

通过腾讯云点播 AI 视频生成 API 生成视频，兼容 /v1/responses video_generation 工具。

流程：
1. 发起请求: POST vod.tencentcloudapi.com  Action=CreateAigcVideoTask
2. 轮询结果: POST vod.tencentcloudapi.com  Action=DescribeTaskDetail
   直到 Status == "FINISH"

认证方式：
腾讯云 VOD API 使用 TC3-HMAC-SHA256 签名。
api_key 字段应为 "SecretId:SecretKey" 格式。
SubAppId 存放于 extra_config["sub_app_id"]。

/v1/responses 工具请求示例:
{
    "type": "video_generation",
    "n": 1,
    "size": "720x1080",      # 视频尺寸，派生 AspectRatio
    "seconds": "5",           # 视频时长（秒），支持 5 或 15，默认 5
    "resolution": "720p"      # 分辨率
}

带参考图的请求示例:
{
    "type": "input_image",
    "image_url": "https://...",
    "file_id": "woman"        # 参考图别名，用于 Prompt 中的 {{woman}} 占位符
}

API 文档: https://cloud.tencent.com/document/product/266/
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
from app.abstraction.messages import Message, MessageRole, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id, json_loads

from app.providers.video_size_utils import resolve_video_size, derive_aspect_ratio

# Re-use shared auth/network helpers from image_generation to avoid duplication.
from .image_generation import (
    TENCENTVOD_API_HOST,
    TENCENTVOD_API_URL,
    _POLL_INTERVAL_S,
    _POLL_MAX_WAIT_S,
    _build_auth_headers,
    _describe_task_detail,
    _parse_api_key,
)


# =============================================================================
# 视频生成模型检测
# =============================================================================

# Known TencentVOD video generation model name prefixes (case-insensitive).
_TENCENTVOD_VIDEO_MODEL_PREFIXES = (
    "kling-",      # Kling video models (ModelName=Kling)
    "veo-",        # Veo video models routed via TencentVOD (ModelName=GV)
    "gv-",         # GV video models (ModelName=GV, short alias)
    "hy-video-",   # Hunyuan video models
    "viduq",       # Vidu video models (ModelName=Vidu)
    "pixverse-",   # Pixverse video models (ModelName=Pixverse)
)


def is_tencentvod_video_model(model: str) -> bool:
    """
    Check if the model is a TencentVOD video generation model.

    Matches model names whose prefix indicates a TencentVOD video generation
    model, e.g.:
      - kling-v3-omni        → Kling, 3.0-Omni
      - kling-v3             → Kling, 3.0
      - kling-v2.1-pro       → Kling, 2.1-Pro
      - veo-3.1-generate-001      → GV, 3.1
      - veo-3.1-fast-generate-001 → GV, 3.1-fast
      - gv-3.1-fast          → GV, 3.1-fast
      - hy-video-v1.0        → Hunyuan, 1.0
      - pixverse-v6          → Pixverse, V6.0
      - pixverse-c1          → Pixverse, C1

    Args:
        model: Model name (case-insensitive)

    Returns:
        True if the model is a TencentVOD video generation model
    """
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _TENCENTVOD_VIDEO_MODEL_PREFIXES)


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
# 辅助: 解析模型名称 / 版本
# =============================================================================

# Explicit lookup table: input model identifier (case-insensitive) →
# (TencentVOD ModelName, TencentVOD ModelVersion).
#
# ModelName conventions:
#   Kling    – 可灵 (Kling) video models
#   GV       – Google Veo models routed via TencentVOD
#   Hunyuan  – 混元视频 models
_VIDEO_MODEL_NAME_VERSION_MAP: Dict[str, Tuple[str, str]] = {
    # ── Kling video models (ModelName=Kling) ────────────────────────────────
    "kling-v3-omni":          ("Kling", "3.0-Omni"),
    "kling-v3-omini":         ("Kling", "3.0-Omini"),
    "kling-v3":               ("Kling", "3.0"),
    "kling-v2.1-pro":         ("Kling", "2.1-Pro"),
    "kling-v2.1-standard":    ("Kling", "2.1-Standard"),
    "kling-v1.6-pro":         ("Kling", "1.6-Pro"),
    "kling-v1.6-standard":    ("Kling", "1.6-Standard"),
    "kling-v1.5-pro":         ("Kling", "1.5-Pro"),
    "kling-v1.0-pro":         ("Kling", "1.0-Pro"),
    "kling-v1.0-standard":    ("Kling", "1.0-Standard"),
    # ── Veo video models routed via TencentVOD (ModelName=GV) ───────────────
    "veo-3.1-generate-001":         ("GV", "3.1"),
    "veo-3.1-fast-generate-001":    ("GV", "3.1-fast"),
    # ── Hunyuan video models ────────────────────────────────────────────────
    "hy-video-v1.0":          ("Hunyuan", "1.0"),
    # ── Vidu video models (ModelName=Vidu) ──────────────────────────────────
    "viduq3-mix":             ("Vidu", "q3-mix"),
    "viduq3-pro":             ("Vidu", "q3-pro"),
    "viduq3-turbo":           ("Vidu", "q3-turbo"),
    "viduq3":                 ("Vidu", "q3"),
    # ── Pixverse video models (ModelName=Pixverse) ─────────────────────────
    "pixverse-v6":            ("Pixverse", "V6.0"),
    "pixverse-c1":            ("Pixverse", "C1"),
    # ── Hunyuan 3D models (3d_generation with SceneType=3d_scene via video gen) ──
    "hunyuan-3d-2.0":         ("Hunyuan", "3d_2.0"),
}


def _parse_kling_version(suffix: str) -> str:
    """
    Convert the version suffix after ``kling-v`` into a TencentVOD ModelVersion.

    Rules:
      - Integer major version (no dot) gets ``.0`` appended: ``3`` → ``3.0``
      - Optional tag after the first ``-`` is title-cased:
          ``3-omni``   → ``3.0-Omni``
          ``2.1-pro``  → ``2.1-Pro``
          ``1.6``      → ``1.6``

    Args:
        suffix: Everything after ``kling-v`` (e.g. ``3-omni``, ``2.1-pro``)

    Returns:
        Formatted ModelVersion string
    """
    parts = suffix.split("-", 1)
    ver = parts[0]
    # Integer version → add .0
    if ver.isdigit():
        ver = f"{ver}.0"
    if len(parts) == 2:
        tag = parts[1].capitalize()
        return f"{ver}-{tag}"
    return ver


def _parse_veo_version(suffix: str) -> str:
    """
    Extract TencentVOD ModelVersion from the part after ``veo-``.

    Strips any trailing ``-generate-NNN`` / ``-preview-NNN`` segment that
    is used in the external model identifier but not passed to the API.

    Examples:
      "3.1-generate-001"       → "3.1"
      "3.1-fast-generate-001"  → "3.1-fast"

    Args:
        suffix: Everything after ``veo-``

    Returns:
        Cleaned ModelVersion string
    """
    import re
    # Remove trailing -generate-NNN / -preview-NNN suffixes
    cleaned = re.sub(r"-(generate|preview)-\d+$", "", suffix, flags=re.IGNORECASE)
    return cleaned


def _parse_video_model_name_version(model: str) -> Tuple[str, str]:
    """
    Derive TencentVOD ModelName and ModelVersion from a video model identifier.

    Priority:
    1. Explicit lookup in ``_VIDEO_MODEL_NAME_VERSION_MAP`` (case-insensitive)
    2. Heuristic rules by prefix:
       - ``kling-vX[.Y][-tag]`` → ("Kling", _parse_kling_version(...))
       - ``veo-X.Y[-qualifier]-generate-NNN`` → ("GV", _parse_veo_version(...))
       - ``gv-X.Y`` → ("GV", "X.Y")
       - ``hy-video-vX.Y`` → ("Hunyuan", "X.Y")
       - ``viduq*`` → ("Vidu", model)
    3. Generic split on last "-" when suffix is version-like
    4. Fallback: (model, "latest")

    Args:
        model: Model identifier string

    Returns:
        (model_name, model_version) tuple
    """
    key = model.lower().strip()

    # 1. Explicit lookup
    if key in _VIDEO_MODEL_NAME_VERSION_MAP:
        return _VIDEO_MODEL_NAME_VERSION_MAP[key]

    # 2a. kling-vX[.Y][-tag] → Kling
    if key.startswith("kling-v"):
        suffix = model[len("kling-v"):]   # preserve original case
        return "Kling", _parse_kling_version(suffix)

    # 2b. veo-* → GV
    if key.startswith("veo-"):
        suffix = model[len("veo-"):]
        return "GV", _parse_veo_version(suffix)

    # 2c. gv-X.Y → GV, X.Y
    if key.startswith("gv-"):
        return "GV", model[3:]

    # 2d. hy-video-vX.Y → Hunyuan, X.Y
    if key.startswith("hy-video-v"):
        return "Hunyuan", model[len("hy-video-v"):]

    # 2e. viduq* → Vidu
    if key.startswith("viduq"):
        return "Vidu", model

    # 2f. pixverse-vX / pixverse-cX → Pixverse
    if key.startswith("pixverse-"):
        suffix = model[len("pixverse-"):].lower()  # v6, c1
        if suffix.startswith("v"):
            ver = suffix[1:]
            return "Pixverse", f"V{ver}.0" if ver.isdigit() else f"V{ver}"
        return "Pixverse", suffix.upper()

    # 2g. hunyuan-3d-X.Y → Hunyuan
    if key.startswith("hunyuan-3d-"):
        return "Hunyuan", model[len("hunyuan-3d-"):]

    # 3. Legacy heuristic: split on last "-" when suffix is version-like
    parts = model.rsplit("-", 1)
    if len(parts) == 2 and parts[1].replace(".", "").isdigit():
        return parts[0], parts[1]

    # 4. Fallback
    return model, "latest"


# =============================================================================
# API 调用: CreateAigcVideoTask
# =============================================================================

def _create_aigc_video_task(
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
    seconds: str = "",
    audio_generation: str = "",
    person_generation: str = "",
    enhance_prompt: str = "",
    file_infos: Optional[List[Dict[str, Any]]] = None,
    last_frame_url: str = "",
    session_id: str = "",
    scene_type: str = "",
    tracer: Any = None,
) -> str:
    """
    Call CreateAigcVideoTask and return the TaskId.

    Args:
        client:             httpx client
        secret_id:          腾讯云 SecretId
        secret_key:         腾讯云 SecretKey
        sub_app_id:         点播子应用 ID（可选）
        model_name:         模型名称，如 "GV"
        model_version:      模型版本，如 "3.1-fast"
        prompt:             正向 Prompt
        negative_prompt:    负向 Prompt
        aspect_ratio:       输出宽高比，如 "9:16"、"16:9"
        resolution:         输出分辨率，如 "1920x1080"
        seconds:            视频时长（秒），如 "4"、"6"
        audio_generation:   是否生成音频 ("Enabled" | "Disabled" | "")
        person_generation:  人物生成策略 ("AllowAdult" | "Disallow" | "")
        enhance_prompt:     是否增强 Prompt ("Enabled" | "")
        file_infos:         参考图片/视频列表
        last_frame_url:     尾帧图片 URL
        session_id:         会话 ID（可选）
        scene_type:         3D 场景类型（"3d_scene" | ""）

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

    if scene_type:
        body["SceneType"] = scene_type

    # Last-frame image (尾帧)
    if last_frame_url:
        body["LastFrameUrl"] = last_frame_url

    # Reference images / videos
    if file_infos:
        body["FileInfos"] = file_infos

    # OutputConfig
    output_config: Dict[str, Any] = {"StorageMode": "Temporary"}
    if aspect_ratio:
        output_config["AspectRatio"] = aspect_ratio
    if resolution:
        output_config["Resolution"] = resolution
    if seconds:
        output_config["Duration"] = float(seconds)
    if audio_generation:
        output_config["AudioGeneration"] = audio_generation
    if person_generation:
        output_config["PersonGeneration"] = person_generation
    body["OutputConfig"] = output_config

    payload_str = json.dumps(body, ensure_ascii=False)

    headers = _build_auth_headers(secret_id, secret_key, "CreateAigcVideoTask", payload_str)

    _span = None
    if tracer:
        _span = tracer.start_child(model_name, model=model_name, provider_type="tencentvod", input_data=body, obs_type="span")
        if _span:
            _span.log_input(body)
    _error: Optional[Exception] = None

    try:
        response = client.post(TENCENTVOD_API_URL, content=payload_str, headers=headers)
        response.raise_for_status()
        data = response.json()

        resp = data.get("Response", {})
        if "Error" in resp:
            err = resp["Error"]
            raise RuntimeError(
                f"TencentVOD CreateAigcVideoTask error "
                f"(code={err.get('Code')}): {err.get('Message')}"
            )

        task_id = resp.get("TaskId")
        if not task_id:
            raise RuntimeError(
                f"TencentVOD CreateAigcVideoTask returned no TaskId: {data}"
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
# API 调用: DescribeTaskDetail (轮询视频任务)
# =============================================================================

def _poll_video_task(
    secret_id: str,
    secret_key: str,
    task_id: str,
    sub_app_id: Optional[int],
    poll_timeout: Optional[int] = None,
    tracer: Any = None,
) -> List[Dict[str, Any]]:
    """
    Poll DescribeTaskDetail until the video task finishes, then extract the video URL.

    Looks for the ``AigcVideoTask`` sub-object in the task detail response.
    The output ``FileUrl`` contains the generated video URL.

    Args:
        secret_id:  腾讯云 SecretId
        secret_key: 腾讯云 SecretKey
        task_id:    CreateAigcVideoTask 返回的 TaskId
        sub_app_id: 点播子应用 ID（可选）

    Returns:
        List of video_generation_call dicts (each with "type", "status", "result")

    Raises:
        RuntimeError: On task failure or timeout
    """
    max_wait = poll_timeout or _POLL_MAX_WAIT_S
    deadline = time.time() + max_wait

    _span = None
    if tracer:
        _span = tracer.start_child(task_id, model=task_id, provider_type="tencentvod", obs_type="span")
    _error: Optional[Exception] = None

    try:
        with httpx.Client(timeout=60) as client:
            poll_count = 0
            while time.time() < deadline:
                resp = _describe_task_detail(client, secret_id, secret_key, task_id, sub_app_id)

                # Extract the AigcVideoTask sub-object
                aigc_task = resp.get("AigcVideoTask") or {}
                status = resp.get("Status") or aigc_task.get("Status", "")
                poll_count += 1

                if _span:
                    _poll_output: Dict[str, Any] = {
                        "task_id": task_id,
                        "status": status,
                        "poll_count": poll_count,
                    }
                    _req_id = resp.get("RequestId", "")
                    if _req_id:
                        _poll_output["x-request-id"] = _req_id
                    _span.log_output(_poll_output)

                if status == "FINISH":
                    # Check for task-level error
                    err_code = aigc_task.get("ErrCode", 0)
                    if err_code != 0:
                        err_code_ext = aigc_task.get("ErrCodeExt", "")
                        raise RuntimeError(
                            f"TencentVOD video task failed "
                            f"(ErrCode={err_code}, ErrCodeExt={err_code_ext}): "
                            f"{aigc_task.get('Message', '')}"
                        )

                    output = aigc_task.get("Output") or {}
                    video_items: List[Dict[str, Any]] = []

                    # Pattern 1: single FileUrl (most common for video tasks)
                    file_url = output.get("FileUrl", "")
                    if file_url:
                        video_items.append({
                            "type": "video_generation_call",
                            "status": "completed",
                            "result": file_url,
                            "file_type": output.get("FileType", "mp4"),
                        })

                    # Pattern 2: FileInfos array (fallback, similar to image tasks)
                    if not video_items:
                        for fi in (output.get("FileInfos") or []):
                            url = fi.get("FileUrl", "")
                            if url:
                                video_items.append({
                                    "type": "video_generation_call",
                                    "status": "completed",
                                    "result": url,
                                    "file_type": fi.get("FileType", "mp4"),
                                })

                    if not video_items:
                        raise RuntimeError(
                            f"TencentVOD video task {task_id} finished but no FileUrl found in output: "
                            f"{json.dumps(output, ensure_ascii=False)}"
                        )

                    return video_items

                if status in ("FAIL", "ABORTED"):
                    err_code_ext = aigc_task.get("ErrCodeExt", "")
                    raise RuntimeError(
                        f"TencentVOD video task {task_id} failed with status={status}, "
                        f"ErrCodeExt={err_code_ext}"
                    )

                time.sleep(_POLL_INTERVAL_S)

        raise RuntimeError(
            f"TencentVOD video task {task_id} timed out after {_POLL_MAX_WAIT_S}s"
        )
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# 参考文件信息构建（role-aware）
# =============================================================================

def _build_file_infos_from_map(
    file_id_media_map: Dict[str, Any],
    model_name: str,
    prompt: str,
) -> Tuple[List[Dict[str, Any]], str, str]:
    """
    Build FileInfos, LastFrameUrl and determine prompt var usage from file_id_media_map.

    Role handling:
      - ``first_frame``   → FileInfos (first frame reference)
      - ``last_frame``    → LastFrameUrl (separate API field)
      - ``reference_image`` / ``reference_video`` / ``reference_audio``
                          → FileInfos with Usage="Reference"
      - No role (default):
          - 1 image only                 → FileInfos (first frame)
          - 2 images, both image type    → first image → FileInfos, second → LastFrameUrl
          - >2 or mixed types            → FileInfos

    If prompt contains ``{{file_id}}`` vars, all FileInfos items matching those vars
    get Usage="Reference".

    Args:
        file_id_media_map: {file_id: {type, url, role}} from responses_adapter
        model_name:       TencentVOD ModelName (Kling, GV, Vidu, Hunyuan)
        prompt:           User prompt text (to check for {{var}} usage)

    Returns:
        (file_infos, last_frame_url, updated_prompt)
    """
    file_infos: List[Dict[str, Any]] = []
    last_frame_url = ""
    seen_urls: set = set()

    # ── Classify media items ──
    first_frame_items: List[Dict[str, Any]] = []
    last_frame_item: Optional[Dict[str, Any]] = None
    reference_items: List[Dict[str, Any]] = []
    unclassified: List[Dict[str, Any]] = []

    for fid, info in (file_id_media_map or {}).items():
        url = info.get("url", "")
        media_type = info.get("type", "")  # image / video / audio
        role = info.get("role", "")
        if not url:
            continue

        item = {"file_id": fid, "url": url, "type": media_type, "role": role}

        if role == "first_frame":
            first_frame_items.append(item)
        elif role == "last_frame":
            last_frame_item = item
        elif role in ("reference_image", "reference_video", "reference_audio"):
            reference_items.append(item)
        else:
            unclassified.append(item)

    # ── Default rule: 2 images without roles → first=first_frame, second=last_frame ──
    if not first_frame_items and not last_frame_item and not reference_items:
        image_only = [u for u in unclassified if u["type"] == "image"]
        if len(image_only) == 2:
            first_frame_items.append(image_only[0])
            last_frame_item = image_only[1]
            unclassified = [u for u in unclassified if u["type"] != "image"]
        elif len(image_only) == 1:
            first_frame_items.append(image_only[0])
            unclassified = [u for u in unclassified if u["type"] != "image"]
        elif unclassified:
            # Mixed types: all go to FileInfos
            pass

    # Remaining unclassified → treat as reference
    reference_items.extend(unclassified)

    # ── Detect {{file_id}} vars in prompt ──
    import re as _re2
    var_fids: set = set(_re2.findall(r"\{\{([^}]+)\}\}", prompt))

    # ── Build FileInfos ──
    def _push_image(fid: str, url: str, usage: str = "") -> None:
        if url in seen_urls:
            return
        seen_urls.add(url)
        item: Dict[str, Any] = {"Type": "Url", "Category": "Image", "Url": url}
        if fid:
            item["ObjectId"] = fid
        if usage:
            item["Usage"] = usage
        file_infos.append(item)

    def _push_video(fid: str, url: str, usage: str = "") -> None:
        if url in seen_urls:
            return
        seen_urls.add(url)
        item: Dict[str, Any] = {"Type": "Url", "Category": "Video", "Url": url}
        if fid:
            item["ObjectId"] = fid
        if usage:
            item["Usage"] = usage
        file_infos.append(item)

    def _push_audio(fid: str, url: str, usage: str = "") -> None:
        if url in seen_urls:
            return
        seen_urls.add(url)
        item: Dict[str, Any] = {"Type": "Url", "Category": "Audio", "Url": url}
        if fid:
            item["ObjectId"] = fid
        if usage:
            item["Usage"] = usage
        file_infos.append(item)

    # First frame images → FileInfos
    for item in first_frame_items:
        _push_image(item["file_id"], item["url"],
                    usage="Reference" if item["file_id"] in var_fids else "FirstFrame")

    # Reference items → FileInfos with Usage=Reference
    for item in reference_items:
        fid = item["file_id"]
        usage = "Reference" if fid in var_fids else ""
        if item["type"] == "image":
            _push_image(fid, item["url"], usage)
        elif item["type"] == "video":
            _push_video(fid, item["url"], usage)
        elif item["type"] == "audio":
            _push_audio(fid, item["url"], usage)

    # Last frame → LastFrameUrl
    if last_frame_item:
        last_frame_url = last_frame_item["url"]

    # ── Variable format conversion per model ──
    if var_fids:
        if model_name == "Kling":
            prompt = _re2.sub(r"\{\{([^}]+)\}\}", r"<<<\1>>>", prompt)
        elif model_name == "Vidu":
            prompt = _re2.sub(r"\{\{([^}]+)\}\}", r"@\1", prompt)

    return file_infos, last_frame_url, prompt


# =============================================================================
# 主入口: 执行视频生成
# =============================================================================

def execute_tencentvod_video_generation(
    api_key: str,
    model: str,
    messages,
    metadata: Dict[str, Any],
    sub_app_id: Optional[int] = None,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute TencentVOD video generation and return a ChatResponse.

    Extracts the prompt from the last user message, derives ModelName/Version
    from the model identifier, calls CreateAigcVideoTask, polls until done,
    and returns the video URL as a video_generation_call item (JSON-encoded)
    in the message content — compatible with the Responses API adapter format.

    Args:
        api_key:    "SecretId:SecretKey" credential string
        model:      Model identifier, e.g. "kling-v3-omni" or "gv-3.1-fast"
        messages:   List of Message objects from the ChatRequest
        metadata:   ChatRequest.metadata dict (carries video generation params)
        sub_app_id: 点播子应用 ID（可选，也可通过 metadata["sub_app_id"] 传入）

    Returns:
        ChatResponse with video_generation_call items in message content

    Raises:
        RuntimeError: On API error or task failure
    """
    secret_id, secret_key = _parse_api_key(api_key)

    # Resolve sub_app_id: prefer metadata, then argument
    _sub_app = metadata.get("sub_app_id") or sub_app_id
    if _sub_app is not None:
        _sub_app = int(_sub_app)

    # Parse model name / version
    model_name, model_version = _parse_video_model_name_version(model)

    # Extract prompt from the last user message
    prompt = ""
    negative_prompt = str(metadata.get("negative_prompt") or "")
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
        raise RuntimeError("TencentVOD video generation: no prompt found in user messages")

    # ── Build FileInfos from file_id_media_map (role-aware) ──────────────────
    file_id_media_map: Dict[str, Any] = metadata.get("file_id_media_map") or {}
    file_infos, last_frame_url, prompt = _build_file_infos_from_map(
        file_id_media_map, model_name, prompt
    )

    # ── Fallback: scan message content blocks when file_id_media_map is empty ──
    # Handles the case where /v1/responses input blocks have no file_id set.
    if not file_id_media_map:
        fallback_map: Dict[str, Any] = {}
        idx = 0
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role != "user":
                continue
            if not isinstance(msg.content, list):
                continue
            for block in msg.content:
                if not hasattr(block, "type"):
                    continue
                if block.type == ContentType.IMAGE_URL and block.url:
                    fallback_map[f"_img_{idx}"] = {"type": "image", "url": block.url, "role": getattr(block, "role", "") or ""}
                    idx += 1
                elif block.type == ContentType.VIDEO_URL and block.url:
                    fallback_map[f"_vid_{idx}"] = {"type": "video", "url": block.url, "role": getattr(block, "role", "") or ""}
                    idx += 1
                elif block.type == ContentType.AUDIO_URL and block.url:
                    fallback_map[f"_aud_{idx}"] = {"type": "audio", "url": block.url, "role": getattr(block, "role", "") or ""}
                    idx += 1
        if fallback_map:
            file_infos, last_frame_url, prompt = _build_file_infos_from_map(
                fallback_map, model_name, prompt
            )

    # ── Video-specific parameters ──────────────────────────────────────────
    # Size → AspectRatio + Resolution
    # Priority: explicit metadata fields > derived from size string
    size = str(metadata.get("size") or "")
    aspect_ratio = str(metadata.get("aspect_ratio") or "")
    resolution = str(metadata.get("resolution") or "")

    if size and (not aspect_ratio or not resolution):
        derived_ar, derived_res = resolve_video_size(size)
        if not aspect_ratio:
            aspect_ratio = derived_ar
        if not resolution:
            resolution = derived_res

    # Pixverse: image-to-video does not support aspect_ratio.
    # C1 reference object editing keeps aspect_ratio+resolution; V6 clears aspect_ratio.
    if model_name == "Pixverse" and file_infos:
        usages = {fi.get("Usage", "") for fi in file_infos}
        if "Reference" not in usages or model_version != "C1":
            aspect_ratio = ""

    seconds = str(metadata.get("seconds") or "")

    # Parse generate_audio: True → Enabled, False → Disabled
    generate_audio = metadata.get("generate_audio")
    audio_generation = "Enabled" if generate_audio else "Disabled" if generate_audio is not None else ""

    person_generation = str(metadata.get("person_generation") or "")
    enhance_prompt = str(metadata.get("enhance_prompt") or "")
    session_id = str(metadata.get("session_id") or "")

    # Determine SceneType for 3D models
    scene_type = ""
    if model.lower().startswith("hunyuan-3d-"):
        scene_type = "3d_scene"

    # ── Tracing ────────────────────────────────────────────────────────────
    _request_data: Dict[str, Any] = {"model": model, "model_version": model_version, "prompt": prompt}
    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="tencentvod", input_data=_request_data)
        if _child_span:
            _child_span.log_input(_request_data)
    _trace_error: Optional[Exception] = None

    try:
        # Submit task
        with httpx.Client(timeout=60) as client:
            task_id = _create_aigc_video_task(
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
                seconds=seconds,
                audio_generation=audio_generation,
                person_generation=person_generation,
                enhance_prompt=enhance_prompt,
                file_infos=file_infos or None,
                last_frame_url=last_frame_url,
                session_id=session_id,
                scene_type=scene_type,
                tracer=_child_span,
            )

        # Poll for result
        video_items = _poll_video_task(secret_id, secret_key, task_id, _sub_app, poll_timeout=metadata.get("timeout"), tracer=_child_span)

        if _child_span:
            _child_span.log_output({"task_id": task_id, "video_count": len(video_items), "status": "succeeded"})
    except Exception as e:
        _trace_error = e
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)

    # For 3D models, rename item types and use 3d_ response ID prefix
    if scene_type == "3d_scene":
        for item in video_items:
            item["type"] = "3d_generation_call"
        response_id = gen_id("3d")
    else:
        response_id = gen_id("vid")

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(video_items, ensure_ascii=False),
    )

    video_count = max(len(video_items), 1)

    usage_extra: Dict[str, Any]
    if scene_type == "3d_scene":
        usage_extra = {
            'output_count': video_count,
        }
    else:
        usage_extra = {
            'output_video_number': video_count,
            'output_video_resolution': resolution or '720p',
            'output_video_aspect': aspect_ratio or '16:9',
            'output_video_seconds': float(seconds) if seconds else 5.0,
            'output_video_audio': audio_generation.lower() == 'enabled' if audio_generation else None,
        }

    return ChatResponse(
        id=response_id,
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
            extra=usage_extra,
        ),
        created=int(time.time()),
        provider="tencentvod",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

def stream_video_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    Execute TencentVOD video generation and yield StreamChunks.

    TencentVOD video generation is asynchronous (create task → poll result).
    This function wraps the synchronous call and emits the result as
    video_generation_call SSE events via raw_sse_passthrough — identical to
    the pattern used by the image generation providers.

    SSE event sequence:
    1. Role marker chunk (delta_role="assistant") → triggers format_stream_start
    2. response.output_item.added  (status=generating)
    3. response.output_item.done   (status=completed, result=<video_url>)
    4. response.completed

    Args:
        chat_fn: The non-streaming chat function (provider.chat)
        request: The chat request with video generation parameters
    """
    # Call the synchronous (polling) path to get the full result
    response = chat_fn(request)
    response_id = response.id
    model = response.model

    # Parse video items list from the response content
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

    # Role marker — triggers format_stream_start in the Responses adapter
    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    # Emit one item per result (video_generation_call or 3d_generation_call)
    for i, vid in enumerate(videos):
        result = vid.get("result", "")
        item_type = vid.get("type", "video_generation_call")
        call_id = f"{response_id}-{i}" if i > 0 else response_id
        output_index = i

        item_added = {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "type": item_type,
                "id": call_id,
                "status": "generating",
                "result": None,
            },
        }
        item_done = {
            "type": "response.output_item.done",
            "output_index": output_index,
            "item": {
                "type": item_type,
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
            "type": vid.get("type", "video_generation_call"),
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
