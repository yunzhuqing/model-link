"""
豆包 Seedance 视频生成模块 (Volcengine Seedance Video Generation)

通过火山引擎 ARK API 生成视频，兼容 /v1/responses video_generation 工具。

流程：
1. 创建任务: POST /api/v3/contents/generations/tasks
2. 轮询结果: GET  /api/v3/contents/generations/tasks/{task_id}
   直到 status == "succeeded"

认证方式：Authorization: Bearer <ARK_API_KEY>

支持的模型:
  doubao-seedance-pro          → 豆包可灵 Pro
  doubao-seedance-1.5-pro      → 豆包 Seedance 1.5 Pro
  doubao-seedance-2.0-fast     → 豆包 Seedance 2.0 Fast
  doubao-seedance-2.0          → 豆包 Seedance 2.0
  seedance-pro                 → Seedance Pro (无 doubao 前缀)
  seedance-1.5-pro             → Seedance 1.5 Pro
  seedance-2.0-fast            → Seedance 2.0 Fast
  seedance-2.0                 → Seedance 2.0

API 文档: https://www.volcengine.com/docs/82379/
"""
from __future__ import annotations

import json
import re
import sys
import time
import asyncio
from typing import Any, Dict, AsyncGenerator, List, Optional, Tuple

import httpx

from app.http_client import shared_client

from app.abstraction.chat import (
    ChatChoice,
    ChatRequest,
    ChatResponse,
    FinishReason,
    UsageInfo,
)
from app.abstraction.messages import ContentType, Message, MessageRole
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.providers.video_size_utils import resolve_seedance_size, resolve_video_size
from app.utils import gen_id, json_loads


# =============================================================================
# 常量
# =============================================================================

_POLL_INTERVAL_S: float = 3.0
_POLL_MAX_WAIT_S: int = 600   # 10 分钟

# 视频任务终止状态
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class SeedanceTaskError(RuntimeError):
    """Raised when a Seedance task ends in a failed/cancelled state.

    Carries a normalized, client-facing error dict (``error_info``) so the
    background response handler can persist the structured error (code +
    message) for the GET /v1/responses/<id> endpoint, instead of a generic
    ``server_error`` placeholder. It is still a ``RuntimeError`` subclass so
    the gateway's existing ``except RuntimeError`` handling applies unchanged.
    """

    def __init__(self, message: str, error_info: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.error_info = error_info


def _normalize_seedance_error(upstream_error: Dict[str, Any]) -> Dict[str, str]:
    """Build a client-facing error dict from an upstream Seedance task error.

    Content / sensitive / policy / copyright violations are mapped to the
    gateway's ``content_policy_violation`` code (one of the GET-endpoint's
    allowlisted codes); other failures fall back to ``server_error``. The
    ``message`` carries the full upstream error info — upstream code plus the
    upstream message (which already embeds the Volcengine request id).
    """
    code = str(upstream_error.get("code") or "").strip()
    message = str(upstream_error.get("message") or "").strip()
    full = f"{code}: {message}" if (code and message) else (code or message or "")

    lowered = code.lower()
    is_policy = any(kw in lowered for kw in ("sensitive", "policy", "copyright"))
    return {
        "code": "content_policy_violation" if is_policy else "server_error",
        "message": full,
    }


# Shared async HTTP client for Volcengine ARK control-plane calls.
# Per-call ``httpx.Client`` creates a new TLS handshake + connection pool every
# time and is sync (blocks the event loop). The shared AsyncClient eliminates
# both costs.
_ark_client: Optional[httpx.AsyncClient] = None
_ark_client_lock = asyncio.Lock()


async def _get_ark_client() -> httpx.AsyncClient:
    global _ark_client
    if _ark_client is None:
        async with _ark_client_lock:
            if _ark_client is None:
                from app.http_client import make_async_client
                _ark_client = make_async_client(scope="ARK")
    return _ark_client


# =============================================================================
# 模型检测
# =============================================================================

# Seedance 视频模型名称前缀 (小写)
_SEEDANCE_MODEL_PREFIXES = (
    "doubao-seedance",
    "seedance",
)

# omni_reference_task_type 接受的枚举值（对应 tool 的 task_type 参数）
_SEEDANCE_TASK_TYPES = ("auto", "reference", "edit", "extend")

def is_seedance_video_model(model: str) -> bool:
    """
    检查模型是否为 Seedance 视频生成模型。

    Args:
        model: 模型名称

    Returns:
        True 表示 Seedance 视频生成模型
    """
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _SEEDANCE_MODEL_PREFIXES)


def _seedance_version(model_id: str) -> Optional[Tuple[int, int]]:
    """
    从模型 ID 中提取 Seedance 主版本号 (major, minor)。

    匹配 seedance-X-Y 或 seedance-X.Y 形式，例如：
      doubao-seedance-2-5-pro-xxx → (2, 5)
      doubao-seedance-1-5-pro-251215 → (1, 5)
      seedance-2.0 → (2, 0)

    Args:
        model_id: 实际 API 模型 ID

    Returns:
        (major, minor) 元组；无法识别版本号（如 seedance-pro）时为 None
    """
    match = re.search(r'seedance[- ]?(\d+)[.\-](\d+)', model_id.lower())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


def _model_supports_audio(model_id: str) -> bool:
    """
    检查模型是否支持 generate_audio 参数。

    Seedance 1.5 及之后的版本支持 generate_audio，1.5 之前的版本（1.0、pro）不支持。

    Args:
        model_id: 实际 API 模型 ID（如 "doubao-seedance-1-5-pro-251215"）

    Returns:
        True 表示支持 generate_audio 参数
    """
    version = _seedance_version(model_id)
    if version is None:
        # For "seedance-pro" (no version number) — older model, no audio support
        return False
    return version >= (1, 5)


def _model_supports_task_type(model_id: str) -> bool:
    """
    检查模型是否支持 task_type（omni_reference_task_type）参数。

    Seedance 2.5 及之后的版本支持 task_type，2.5 之前的版本不支持。

    Args:
        model_id: 实际 API 模型 ID（如 "doubao-seedance-2-5-pro-260620"）

    Returns:
        True 表示支持 task_type 参数
    """
    version = _seedance_version(model_id)
    if version is None:
        return False
    return version >= (2, 5)


# =============================================================================
# file_id → Seedance 变量别名构建
# =============================================================================

# Roles that receive a Seedance-numbered variable alias (图片n / 视频n / 音频n).
# Special frame roles are excluded from numbering.
_REFERENCE_ROLES = {"reference_image", "reference_video", "reference_audio", ""}

# Role values that Seedance API accepts directly as content item roles.
# Empty role ("") defaults to the media-type-specific reference role below.
_SEEDANCE_ROLE_MAP: Dict[str, str] = {
    "first_frame":       "first_frame",
    "last_frame":        "last_frame",
    "reference_image":   "reference_image",
    "reference_video":   "reference_video",
    "reference_audio":   "reference_audio",
}
# Default content role when role is empty, keyed by media type
_DEFAULT_MEDIA_ROLE: Dict[str, str] = {
    "image": "reference_image",
    "video": "reference_video",
    "audio": "reference_audio",
}


def _build_seedance_file_id_aliases(
    file_id_media_map: Dict[str, Any],
) -> Tuple[Dict[str, str], List[str], List[str], List[str], List[Dict[str, str]]]:
    """
    从 file_id_media_map 构建 Seedance 变量替换表、参考媒体 URL 列表及特殊帧列表。

    Seedance 使用中文序号引用普通参考媒体，按出现顺序分配序号：
      图片1, 图片2, …  （role: reference_image 或空）
      视频1, 视频2, …  （role: reference_video 或空）
      音频1, 音频2, …  （role: reference_audio 或空）

    具有 first_frame / last_frame role 的图片不参与序号分配，而是作为特殊帧
    直接写入 content 数组（role: first_frame_image / last_frame_image）。

    Args:
        file_id_media_map:
            { file_id: {'type': 'image'|'video'|'audio', 'url': str, 'role': str} }
            来自 responses_adapter 收集的 input 块 file_id 映射。

    Returns:
        (sub_map, ref_images, ref_videos, ref_audios, special_frames)
          sub_map:       { file_id: "图片1" | "视频1" | "音频1" | … }（普通参考）
          ref_images:    参考图片 URL 列表（按出现顺序）
          ref_videos:    参考视频 URL 列表（按出现顺序）
          ref_audios:    参考音频 URL 列表（按出现顺序）
          special_frames: [{'url': str, 'seedance_role': str}]
                          first_frame / last_frame 等特殊帧，直接写入 content
    """
    sub_map: Dict[str, str] = {}
    ref_images: List[str] = []
    ref_videos: List[str] = []
    ref_audios: List[str] = []
    special_frames: List[Dict[str, str]] = []

    img_idx = 1
    vid_idx = 1
    aud_idx = 1

    for fid, info in (file_id_media_map or {}).items():
        media_type = info.get("type", "")
        url = info.get("url", "")
        role = info.get("role", "")  # first_frame | last_frame | reference_image | … | ""

        if not url:
            continue

        # Special frame roles (first_frame / last_frame): write directly to content.
        # Also add to sub_map so {{file-xxx}} → asset-xxx in text (bare id, no asset:// prefix).
        if role in ("first_frame", "last_frame"):
            seedance_role = _SEEDANCE_ROLE_MAP.get(role, role)
            special_frames.append({"url": url, "seedance_role": seedance_role, "media_type": media_type})
            # Strip asset:// prefix for template substitution: {{file-xxx}} → {{asset-xxx}}
            obj_key = url.replace("asset://", "") if url.startswith("asset://") else url
            sub_map[fid] = obj_key
            continue

        # Regular reference media: assign numbered alias
        if media_type == "image":
            sub_map[fid] = f"图片{img_idx}"
            img_idx += 1
            ref_images.append(url)
        elif media_type == "video":
            sub_map[fid] = f"视频{vid_idx}"
            vid_idx += 1
            ref_videos.append(url)
        elif media_type == "audio":
            sub_map[fid] = f"音频{aud_idx}"
            aud_idx += 1
            ref_audios.append(url)

    return sub_map, ref_images, ref_videos, ref_audios, special_frames


def _apply_file_id_substitution(text: str, sub_map: Dict[str, str]) -> str:
    """
    将文本中的 {{file_id}} 占位符替换为对应的 Seedance 变量名（如 图片1, 视频1）。

    未在 sub_map 中命中的占位符保持原样不做替换。

    Args:
        text:    原始提示词文本
        sub_map: { file_id: "图片1" | "视频1" | "音频1" | … }

    Returns:
        替换后的文本
    """
    if not sub_map or not text:
        return text
    import re
    def _replace(match: "re.Match") -> str:
        fid = match.group(1)
        return sub_map.get(fid, match.group(0))
    return re.sub(r"\{\{([^}]+)\}\}", _replace, text)


# =============================================================================
# 内容块构建
# =============================================================================

def _build_content(
    messages: List[Message],
    reference_images: Optional[List[str]] = None,
    reference_videos: Optional[List[str]] = None,
    reference_audios: Optional[List[str]] = None,
    file_id_sub_map: Optional[Dict[str, str]] = None,
    special_frames: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    从 ChatRequest 消息列表构建 Seedance API 的 (prompt_text, content) 对。

    Seedance API 使用一个统一的 ``content`` 数组：
      - 文本项:  {"type": "text", "text": "..."}
      - 图片项:  {"type": "image_url", "image_url": {"url": "..."}, "role": "reference_image"}
      - 视频项:  {"type": "video_url", "video_url": {"url": "..."}, "role": "reference_video"}
      - 音频项:  {"type": "audio_url", "audio_url": {"url": "..."}, "role": "reference_audio"}
      - 首帧图:  {"type": "image_url", "image_url": {"url": "..."}, "role": "first_frame_image"}
      - 尾帧图:  {"type": "image_url", "image_url": {"url": "..."}, "role": "last_frame_image"}

    若提供 ``file_id_sub_map``，则文本块中的 ``{{file_id}}`` 占位符将被替换为
    对应的 Seedance 变量名（如 图片1, 视频1, 音频1）。

    Args:
        messages:          ChatRequest 消息列表
        reference_images:  额外的参考图片 URL 列表（来自 metadata）
        reference_videos:  额外的参考视频 URL 列表（来自 metadata）
        reference_audios:  额外的参考音频 URL 列表（来自 metadata）
        file_id_sub_map:   file_id → Seedance 变量名替换表（可选）
        special_frames:    特殊帧列表，如 first_frame / last_frame（可选）
                           每项: {'url': str, 'seedance_role': str, 'media_type': str}

    Returns:
        (prompt_text, content_array) — prompt_text 为最后一条用户文本（已替换占位符）；
        content_array 为完整的 content 列表（含文本和媒体）。
    """
    content: List[Dict[str, Any]] = []
    seen_urls: set = set()
    prompt_text = ""
    # Whether the user explicitly assigned a role to any image. When True, the
    # user is taking control of frame roles and we must respect their input
    # verbatim (even if every image is "reference_image") instead of
    # auto-assigning first_frame / last_frame.
    has_explicit_image_role = False

    # 从用户消息中提取内容
    for msg in messages:
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role != "user":
            continue

        if isinstance(msg.content, str):
            if msg.content.strip():
                text = _apply_file_id_substitution(msg.content, file_id_sub_map)
                content.append({"type": "text", "text": text})
                prompt_text = text
        elif isinstance(msg.content, list):
            for block in msg.content:
                if not hasattr(block, "type"):
                    continue

                if block.type == ContentType.TEXT and block.text:
                    text = _apply_file_id_substitution(block.text, file_id_sub_map)
                    content.append({"type": "text", "text": text})
                    prompt_text = text

                elif block.type == ContentType.IMAGE_URL and block.url:
                    url = block.url
                    if url not in seen_urls:
                        seen_urls.add(url)
                        # Respect the user-specified role (e.g. first_frame /
                        # last_frame / reference_image); default to
                        # reference_image when none was given.
                        block_role = getattr(block, "role", None)
                        if block_role:
                            has_explicit_image_role = True
                            img_role = _SEEDANCE_ROLE_MAP.get(block_role, block_role)
                        else:
                            img_role = "reference_image"
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": url},
                            "role": img_role,
                        })

                elif block.type == ContentType.VIDEO_URL and block.url:
                    url = block.url
                    if url not in seen_urls:
                        seen_urls.add(url)
                        content.append({
                            "type": "video_url",
                            "video_url": {"url": url},
                            "role": "reference_video",
                        })

                elif block.type == ContentType.AUDIO_URL and block.url:
                    url = block.url
                    if url not in seen_urls:
                        seen_urls.add(url)
                        content.append({
                            "type": "audio_url",
                            "audio_url": {"url": url},
                            "role": "reference_audio",
                        })

    # 追加 metadata 中的额外参考媒体
    for url in (reference_images or []):
        if url and url not in seen_urls:
            seen_urls.add(url)
            content.append({
                "type": "image_url",
                "image_url": {"url": url},
                "role": "reference_image",
            })

    for url in (reference_videos or []):
        if url and url not in seen_urls:
            seen_urls.add(url)
            content.append({
                "type": "video_url",
                "video_url": {"url": url},
                "role": "reference_video",
            })

    for url in (reference_audios or []):
        if url and url not in seen_urls:
            seen_urls.add(url)
            content.append({
                "type": "audio_url",
                "audio_url": {"url": url},
                "role": "reference_audio",
            })

    # 追加特殊帧（first_frame / last_frame）
    for frame in (special_frames or []):
        url = frame.get("url", "")
        seedance_role = frame.get("seedance_role", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            content.append({
                "type": "image_url",
                "image_url": {"url": url},
                "role": seedance_role,
            })

    # 自动帧角色分配：
    # 仅当用户完全没有为图片显式指定 role 时才介入——即没有 special_frames（来自
    # file_id_media_map 中显式的 first_frame/last_frame）且消息内容块中也没有任何
    # 带 role 的图片。此时按位置自动分配首尾帧：
    #   第一张 → first_frame
    #   最后一张 → last_frame
    #   中间张 → reference_image（保持不变）
    # 只要用户给任何一张图显式设置了 role（哪怕全是 reference_image），就视为用户要
    # 自行控制角色，原样下发、不做任何修改。
    #
    # 注意：当 content 中同时包含 reference_video 或 reference_audio 时，跳过自动
    # 帧分配。Seedance API 不允许 first_frame / last_frame 与 reference_video /
    # reference_audio 混用（会报 InvalidParameter: cannot be mixed）。
    has_explicit_special_frames = bool(special_frames)
    has_ref_video_or_audio = any(
        item.get("type") in ("video_url", "audio_url")
        for item in content
    )
    if not has_explicit_special_frames and not has_explicit_image_role and not has_ref_video_or_audio:
        # 找出所有 reference_image 类型的图片项（保留 index）
        img_indices = [
            i for i, item in enumerate(content)
            if item.get("type") == "image_url" and item.get("role") == "reference_image"
        ]
        if len(img_indices) >= 2:
            content[img_indices[0]]["role"] = "first_frame"
            content[img_indices[-1]]["role"] = "last_frame"
        elif len(img_indices) == 1:
            # 只有一张图：作为 first_frame
            content[img_indices[0]]["role"] = "first_frame"

    return prompt_text, content


# =============================================================================
# API 调用: 创建视频生成任务
# =============================================================================

async def _create_video_task(
    api_key: str,
    base_url: str,
    model_id: str,
    content: List[Dict[str, Any]],
    ratio: str = "",
    duration: Optional[int] = None,
    resolution: str = "",
    generate_audio: Optional[bool] = True,
    watermark: bool = False,
    seed: Optional[int] = None,
    omni_reference_task_type: Optional[str] = None,
    tracer: Any = None,
) -> str:
    """
    调用 POST /contents/generations/tasks 创建视频生成任务，返回 task_id。

    Args:
        api_key:        ARK API Key
        base_url:       API 基础 URL（含 /v3）
        model_id:       实际 API 模型 ID
        content:        内容数组（文本 + 媒体）
        ratio:          宽高比，如 "16:9"、"9:16"
        duration:       视频时长（秒，整数）
        resolution:     分辨率档位，如 "720p"、"1080p"
        generate_audio: 是否生成音频（默认 True；None 表示不发送该参数）
        watermark:      是否添加水印（默认 False）
        seed:           随机种子
        omni_reference_task_type: 全模态参考任务类型
                        (auto | reference | edit | extend)，None 表示不发送
        tracer:         可选的 tracer 实例

    Returns:
        task_id 字符串

    Raises:
        RuntimeError: API 返回错误时
    """
    body: Dict[str, Any] = {
        "model": model_id,
        "content": content,
        "watermark": watermark,
    }

    # Only include generate_audio for models that support it (1.5+)
    if generate_audio is not None:
        body["generate_audio"] = generate_audio

    if ratio:
        body["ratio"] = ratio
    if duration is not None:
        body["duration"] = int(duration)
    if resolution:
        body["resolution"] = resolution
    if seed is not None:
        body["seed"] = seed
    if omni_reference_task_type:
        body["omni_reference_task_type"] = omni_reference_task_type

    url = f"{base_url.rstrip('/')}/contents/generations/tasks"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    _span = None
    if tracer:
        _span = tracer.start_child(model_id, model=model_id, provider_type="volcengine", input_data=body, obs_type="span")
        if _span:
            _span.log_input(body)
    _error: Optional[Exception] = None

    try:
        payload_str = json.dumps(body, ensure_ascii=False)
        async with shared_client() as client:
            response = await client.post(url, content=payload_str, headers=headers)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Seedance CreateVideoTask error ({response.status_code}): {response.text}"
            )

        data = response.json()
        task_id = data.get("id", "")
        if not task_id:
            raise RuntimeError(f"Seedance CreateVideoTask returned no task id: {data}")

        if _span:
            _output: Dict[str, Any] = {"task_id": task_id}
            _x_req_id = response.headers.get("x-request-id", "")
            if _x_req_id:
                _output["x-request-id"] = _x_req_id
            _span.log_output(_output)
        return task_id
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# API 调用: 查询任务状态 (单次, 供轮询和 resync 共用)
# =============================================================================

async def check_seedance_task_status(
    api_key: str,
    base_url: str,
    task_id: str,
) -> Dict[str, Any]:
    """
    单次查询 Seedance 视频任务状态。

    Args:
        api_key:   ARK API Key
        base_url:  API 基础 URL（含 /v3）
        task_id:   任务 ID

    Returns:
        {
            "status": "succeeded" | "failed" | "cancelled" | "running",
            "data": {...},           # 完整的 API 响应 JSON
            "video_url": "...",      # succeeded 时有值
            "usage": {...},          # succeeded 时有值
        }
    """
    url = f"{base_url.rstrip('/')}/contents/generations/tasks/{task_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    client = await _get_ark_client()
    response = await client.get(url, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Seedance DescribeVideoTask error ({response.status_code}): {response.text}"
        )
    data = response.json()
    status = data.get("status", "")
    result: Dict[str, Any] = {"status": status if status in _TERMINAL_STATUSES else "running", "data": data}

    if status == "succeeded":
        content = data.get("content") or {}
        video_url = content.get("video_url", "")
        result["video_url"] = video_url
        raw_usage = data.get("usage") or {}
        completion_tokens = int(raw_usage.get("completion_tokens", 0))
        total_tokens = int(raw_usage.get("total_tokens", completion_tokens))
        prompt_tokens = total_tokens - completion_tokens
        result["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
    elif status in ("failed", "cancelled"):
        # Carry the upstream error (code + message) so callers can surface the
        # real failure reason (e.g. content-policy / copyright violations)
        # instead of a generic "task failed" string. Normalize to the gateway's
        # client-facing codes (content_policy_violation / server_error).
        error = data.get("error")
        if isinstance(error, dict) and error:
            result["error"] = _normalize_seedance_error(error)
    return result


# =============================================================================
# API 调用: 轮询任务结果
# =============================================================================

async def _poll_video_task(
    api_key: str,
    base_url: str,
    task_id: str,
    tracer: Any = None,
    poll_timeout: Optional[int] = None,
) -> Tuple[str, Dict[str, int], int]:
    """
    轮询 GET /contents/generations/tasks/{task_id} 直到任务完成。

    Args:
        api_key:   ARK API Key
        base_url:  API 基础 URL（含 /v3）
        task_id:   CreateVideoTask 返回的任务 ID
        tracer:    可选的 tracer 实例，用于创建 poll span
        poll_timeout: 轮询超时时间（秒）

    Returns:
        (video_url, usage_dict, poll_count)
        video_url:  生成的视频地址
        usage_dict: 包含 prompt_tokens / completion_tokens / total_tokens
        poll_count: 轮询次数

    Raises:
        RuntimeError: 任务失败或超时
    """
    max_wait = poll_timeout or _POLL_MAX_WAIT_S
    deadline = time.time() + max_wait
    poll_count = 0

    _span = None
    if tracer:
        _span = tracer.start_child(task_id, model=task_id, provider_type="volcengine", obs_type="span")
        if _span:
            _span.log_input({"task_id": task_id})
    _error: Optional[Exception] = None

    try:
        while time.time() < deadline:
            poll_count += 1
            result = await check_seedance_task_status(api_key, base_url, task_id)
            status = result["status"]

            if _span:
                _poll_output: Dict[str, Any] = {
                    "task_id": task_id,
                    "status": status,
                    "poll_count": poll_count,
                }
                _span.log_output(_poll_output)

            if status == "succeeded":
                video_url = result.get("video_url", "")
                if not video_url:
                    raise RuntimeError(
                        f"Seedance task {task_id} succeeded but no video_url found"
                    )
                return video_url, result["usage"], poll_count

            if status in ("failed", "cancelled"):
                err = result.get("error")
                if err:
                    raise SeedanceTaskError(
                        f"Seedance video task {task_id} ended with status={status}: "
                        f"{err.get('message', '')}".strip(),
                        error_info=err,
                    )
                raise RuntimeError(
                    f"Seedance video task {task_id} ended with status={status}"
                )

            await asyncio.sleep(_POLL_INTERVAL_S)

        raise RuntimeError(
            f"Seedance video task {task_id} timed out after {max_wait}s"
        )
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# 主入口: 执行视频生成
# =============================================================================

async def execute_seedance_video_generation(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Message],
    metadata: Dict[str, Any],
    tracer: Any = None,
) -> ChatResponse:
    """
    执行 Seedance 视频生成并返回 ChatResponse。

    Args:
        api_key:   ARK API Key
        base_url:  API 基础 URL（含 /v3）
        model:     已解析的真实模型 ID（来自网关 DB，如 "doubao-seedance-2-0-260128"）
        messages:  消息列表
        metadata:  请求 metadata（视频生成参数）
        tracer:    可选的 tracer 实例，用于追踪 API 调用

    Returns:
        ChatResponse，message.content 为 JSON 格式的 video_generation_call 列表

    Raises:
        RuntimeError: API 错误或任务失败
    """

    # ── 参数提取 ──────────────────────────────────────────────────────────
    # AspectRatio / Resolution
    # Priority: explicit fields > derived from size string
    size = str(metadata.get("size") or "")
    ratio = str(metadata.get("aspect_ratio") or "")
    resolution = str(metadata.get("resolution") or "")

    if size and (not ratio or not resolution):
        # Use Seedance-specific size table (per-model pixel dimension mapping)
        derived_ratio, derived_res, _pixel = resolve_seedance_size(size, model)
        if not ratio:
            ratio = derived_ratio
        if not resolution:
            resolution = derived_res

    # Apply defaults when no aspect_ratio / resolution / size is specified
    if not ratio:
        ratio = "16:9"
    if not resolution:
        resolution = "720p"

    resolution = resolution.lower()

    # Duration (seconds, int)
    seconds_raw = metadata.get("seconds")
    duration: Optional[int] = int(float(seconds_raw)) if seconds_raw is not None else None

    # Audio / watermark / seed
    # generate_audio is only supported by Seedance 1.5+ models.
    # For earlier versions (1.0, pro), it should not be sent to the API.
    supports_audio = _model_supports_audio(model)
    generate_audio_raw = metadata.get("generate_audio")
    if supports_audio:
        generate_audio: Optional[bool] = bool(generate_audio_raw) if generate_audio_raw is not None else True
    else:
        generate_audio: Optional[bool] = None  # Don't send to API

    watermark_raw = metadata.get("watermark")
    watermark: bool = bool(watermark_raw) if watermark_raw is not None else False

    seed_raw = metadata.get("seed")
    seed: Optional[int] = int(seed_raw) if seed_raw is not None else None

    # Omni-reference task type (auto | reference | edit | extend).
    # task_type is only supported by Seedance 2.5+ models; for earlier versions
    # it is silently dropped (not sent to the API), like generate_audio.
    task_type = str(metadata.get("task_type") or "").strip()
    if task_type:
        if task_type not in _SEEDANCE_TASK_TYPES:
            raise RuntimeError(
                f"Seedance video generation: invalid task_type '{task_type}', "
                f"expected one of {', '.join(_SEEDANCE_TASK_TYPES)}"
            )
        if not _model_supports_task_type(model):
            task_type = None  # Don't send to API for pre-2.5 models
    else:
        task_type = None

    # Build file_id → Seedance variable alias map (图片1, 视频1, 音频1, …)
    # Media references come exclusively from file_id_media_map (input content blocks),
    # NOT from video_generation tool fields.
    file_id_media_map: Dict[str, Any] = metadata.get("file_id_media_map") or {}
    file_id_sub_map: Dict[str, str] = {}
    special_frames: List[Dict[str, str]] = []
    if file_id_media_map:
        file_id_sub_map, reference_images, reference_videos, reference_audios, special_frames = \
            _build_seedance_file_id_aliases(file_id_media_map)
    else:
        reference_images: List[str] = []
        reference_videos: List[str] = []
        reference_audios: List[str] = []

    # ── 构建 content 数组 ────────────────────────────────────────────────
    prompt_text, content = _build_content(
        messages,
        reference_images=reference_images,
        reference_videos=reference_videos,
        reference_audios=reference_audios,
        file_id_sub_map=file_id_sub_map,
        special_frames=special_frames,
    )

    if not prompt_text:
        raise RuntimeError("Seedance video generation: no text prompt found in user messages")

    # ── task_type-specific constraints (edit / extend) ─────────────────────
    # edit/extend operate on a reference video: content must contain at least
    # one reference_video. Both modes require ratio=adaptive; edit additionally
    # requires duration=-1 (the reference video itself must be 4–30s long, a
    # constraint validated upstream by the API).
    has_reference_video = any(
        item.get("type") == "video_url" and item.get("role") == "reference_video"
        for item in content
    )
    if task_type in ("edit", "extend"):
        if not has_reference_video:
            raise RuntimeError(
                f"Seedance video generation: task_type '{task_type}' requires "
                f"at least one reference_video in content"
            )
        ratio = "adaptive"
        if task_type == "edit":
            duration = -1

    # ── Tracing ────────────────────────────────────────────────────────────
    _request_data: Dict[str, Any] = {"model": model, "content": content, "ratio": ratio, "resolution": resolution}
    if duration is not None:
        _request_data["duration"] = duration
    if task_type is not None:
        _request_data["task_type"] = task_type
    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type="volcengine", input_data=_request_data)
        if _child_span:
            _child_span.log_input(_request_data)
    _trace_error: Optional[Exception] = None

    try:
        # ── 创建任务 ─────────────────────────────────────────────────────────
        task_id = await _create_video_task(
            api_key=api_key,
            base_url=base_url,
            model_id=model,
            content=content,
            ratio=ratio,
            duration=duration,
            resolution=resolution,
            generate_audio=generate_audio,
            watermark=watermark,
            seed=seed,
            omni_reference_task_type=task_type,
            tracer=_child_span,
        )

        hook = metadata.get('_on_task_created')
        if hook:
            hook(task_id)

        # ── 轮询结果 ─────────────────────────────────────────────────────────
        video_url, usage_dict, poll_count = await _poll_video_task(
            api_key, base_url, task_id, tracer=_child_span, poll_timeout=metadata.get('timeout')
        )

        if _child_span:
            _child_span.log_output({
                "video_url": video_url,
                "usage": usage_dict,
                "task_id": task_id,
                "poll_count": poll_count,
                "status": "succeeded",
            })
    except Exception as e:
        _trace_error = e
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)


    video_items = [{
        "type": "video_generation_call",
        "status": "completed",
        "result": video_url,
        "file_type": "mp4",
    }]

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(video_items, ensure_ascii=False),
    )

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
                '_task_id': task_id,
                'output_video_number': 1,
                'output_video_resolution': resolution or '',
                'output_video_aspect': ratio or '',
                'output_video_seconds': float(duration) if duration is not None else 0.0,
                'output_video_audio': generate_audio,
                'output_video_reference_video': has_reference_video,
            },
        ),
        created=int(time.time()),
        provider="volcengine",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

async def stream_seedance_video_generation(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    """
    执行 Seedance 视频生成并以 StreamChunk 格式 yield 结果。

    Seedance 视频生成是异步任务（创建 → 轮询），此函数将同步调用结果
    转换为兼容 Responses API 适配器的 SSE 事件序列：

    1. role marker  (delta_role="assistant")  → 触发 format_stream_start
    2. response.output_item.added  (generating)
    3. response.output_item.done   (completed, result=<video_url>)
    4. response.completed

    Args:
        chat_fn: provider.chat 非流式方法
        request: ChatRequest
    """
    response = await chat_fn(request)
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
            videos = json_loads(raw) if isinstance(raw, str) else []
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
