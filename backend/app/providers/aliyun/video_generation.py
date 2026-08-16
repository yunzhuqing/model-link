"""
阿里云视频生成模块 (Aliyun Yike Video Generation)

通过阿里云 OpenAPI (RPC 风格, AK/SK 签名) 调用视频生成服务:

- SubmitVideoGenerationJob: 提交视频生成任务
- GetVideoGenerationJob:    查询视频生成任务

产品: yike, API 版本: 2026-03-19, 端点: yike.{region}.aliyuncs.com
(cn-shanghai / ap-southeast-1)

支持的 JobType:
- text_to_video:       文生视频
- image_to_video:      图生视频 (Input.Medias 1 个 image)
- first_last_frame:    首尾帧生视频 (Input.Medias 2 个 image)
- reference_to_video:  参考对象生视频 (Input.Medias 最多 9 个)

支持的模型 (Model): wonder-pro, wonder-standard, wan3.0-video,
happyhorse-1.1, wan2.7

支持的 Scene: general
Resolution: 720P / 1080P
AspectRatio: 16:9, 9:16, 4:3, 3:4, 1:1, 21:9
Duration: 4~15 秒, 默认 "5" (纯秒数字符串, 如 "6")
N: 1~4, 默认 1

API 文档: 阿里云 OpenAPI 门户 yike (2026-03-19)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional
from urllib.parse import quote, quote_plus

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

logger = logging.getLogger(__name__)

# =============================================================================
# 阿里云 yike 视频生成 API 常量
# =============================================================================

# 默认 API 版本 (用户账号实测可用)。新版接口为 2026-07-07,
# 可通过供应商 extra_config["api_version"] 覆盖。
YIKE_API_VERSION = "2026-07-07"

# 区域端点映射 (regional endpoint rule)
YIKE_ENDPOINT_MAP = {
    "cn-shanghai": "yike.cn-shanghai.aliyuncs.com",
    "ap-southeast-1": "yike.ap-southeast-1.aliyuncs.com",
}

DEFAULT_REGION = "cn-shanghai"
DEFAULT_ENDPOINT = YIKE_ENDPOINT_MAP[DEFAULT_REGION]

# 默认轮询参数
_POLL_INTERVAL_S = 5       # 轮询间隔(秒)
_POLL_MAX_WAIT_S = 900     # 最大等待时间(秒)

# =============================================================================
# 任务状态常量
# =============================================================================

STATUS_CREATED = "Created"
STATUS_QUEUING = "Queuing"
STATUS_EXECUTING = "Executing"
STATUS_FINISHED = "Finished"
STATUS_FAILED = "Failed"

# 终态集合(任务不会再变动的状态)
TERMINAL_STATUSES = frozenset({STATUS_FINISHED, STATUS_FAILED})

# 状态 → 图标映射(流式输出用)
STATUS_EMOJI = {
    STATUS_CREATED: "📝",
    STATUS_QUEUING: "⏳",
    STATUS_EXECUTING: "🔄",
    STATUS_FINISHED: "✅",
    STATUS_FAILED: "❌",
}

# =============================================================================
# 视频生成模型检测
# =============================================================================

# 阿里云视频生成支持的模型(小写比较)
ALIYUN_VIDEO_MODELS = (
    "wonder-pro",
    "wonder-standard",
    "wan3.0-video",
    "happyhorse-1.1",
    "wan2.7",
)


def is_aliyun_video_model(model: str) -> bool:
    """
    Check if the model is an Aliyun video generation model.

    Matches model names case-insensitively (with or without an ``aliyun/``
    prefix, e.g. ``aliyun/wonder-pro``).

    Args:
        model: Model name

    Returns:
        True if the model is an Aliyun video generation model
    """
    lower = model.lower()
    if lower.startswith("aliyun/"):
        lower = lower[len("aliyun/"):]
    return lower in ALIYUN_VIDEO_MODELS


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
# RPC 签名与请求构造
# =============================================================================

def _percent_encode(value: Any) -> str:
    """
    Percent-encode a string for Alibaba Cloud RPC signatures.

    Uses RFC 3986 encoding (urllib quote with safe="~"), matching the official
    tea-openapi SDK: unreserved characters (A-Za-z0-9-_.~) are left as-is.

    Args:
        value: Value to encode (converted to str)

    Returns:
        Encoded string
    """
    return quote(str(value), safe="~")


def _compute_rpc_signature(access_key_secret: str, string_to_sign: str) -> str:
    """
    Compute the RPC HMAC-SHA1 signature, base64-encoded.

    The HMAC key is ``AccessKeySecret + "&"``.

    Args:
        access_key_secret: Alibaba Cloud AccessKey Secret
        string_to_sign: StringToSign (``POST&%2F&<encoded canonical>``)

    Returns:
        base64 signature string
    """
    digest = hmac.new(
        (access_key_secret + "&").encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_rpc_params(
    *,
    action: str,
    version: str,
    access_key_id: str,
    access_key_secret: str,
    params: Dict[str, Any],
    timestamp: Optional[str] = None,
    signature_nonce: Optional[str] = None,
    security_token: Optional[str] = None,
) -> Dict[str, str]:
    """
    Build the RPC query parameters including the computed Signature.

    Follows the official Alibaba Cloud RPC signature v1 (HMAC-SHA1):

    1. Merge common params (Action/Version/Format/Timestamp/SignatureNonce/
       AccessKeyId/SignatureMethod/SignatureVersion) with the action params.
    2. Sort keys; percent-encode ``key=value`` pairs joined by ``&``.
    3. ``StringToSign = POST&%2F&percentEncode(canonical)`` where the second
       percent-encoding uses quote_plus (space → "+"), matching tea-openapi.
    4. ``Signature = base64(hmac_sha1(AccessKeySecret + "&", StringToSign))``.

    Args:
        action: RPC action name, e.g. "SubmitVideoGenerationJob"
        version: API version, e.g. "2026-03-19"
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        params: Action-specific parameters (values converted to str)
        timestamp: Optional ISO8601 UTC timestamp (defaults to now)
        signature_nonce: Optional nonce (defaults to a random UUID hex)
        security_token: Optional STS security token

    Returns:
        Query dict including the computed "Signature"
    """
    common: Dict[str, Any] = {
        "AccessKeyId": access_key_id,
        "Action": action,
        "Format": "json",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": signature_nonce or uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "Timestamp": timestamp
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": version,
    }
    if security_token:
        common["SecurityToken"] = security_token

    signed_params = dict(common)
    for k, v in params.items():
        if v is not None:
            signed_params[k] = v

    def _rpc_value(v: Any) -> Any:
        # Aliyun RPC 规范: 布尔值在签名与请求体中都使用小写 true/false。
        if isinstance(v, bool):
            return "true" if v else "false"
        return v

    canonical_pairs = []
    for key in sorted(signed_params):
        value = signed_params[key]
        if value is None:
            continue
        canonical_pairs.append(f"{_percent_encode(key)}={_percent_encode(_rpc_value(value))}")
    canonicalized_query_string = "&".join(canonical_pairs)
    string_to_sign = f"POST&%2F&{quote_plus(canonicalized_query_string, safe='~')}"
    common["Signature"] = _compute_rpc_signature(access_key_secret, string_to_sign)
    return common


def _rpc_request_url(endpoint: str, query: Dict[str, str]) -> str:
    """Build the RPC request URL with the sorted query string."""
    query_string = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted(query.items())
    )
    return f"https://{endpoint}/?{query_string}"


def _rpc_form_body(params: Dict[str, Any]) -> str:
    """Encode the action params as an application/x-www-form-urlencoded body.

    Boolean values are encoded as lowercase ``true`` / ``false`` per the
    Aliyun RPC convention.
    """
    def _value(v: Any) -> Any:
        if isinstance(v, bool):
            return "true" if v else "false"
        return v

    return "&".join(
        f"{_percent_encode(k)}={_percent_encode(_value(v))}"
        for k, v in params.items()
        if v is not None
    )


def _rpc_headers(version: str, action: str) -> Dict[str, str]:
    """Build the RPC request headers (content-type set for form bodies)."""
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "x-acs-version": version,
        "x-acs-action": action,
        "User-Agent": "model-link/aliyun-yike",
    }


def resolve_yike_endpoint(region: Optional[str], endpoint: Optional[str]) -> str:
    """
    Resolve the yike API endpoint.

    Priority: explicit endpoint > region endpoint map > default endpoint.

    Args:
        region: Optional region id (e.g. "cn-shanghai")
        endpoint: Optional explicit endpoint override

    Returns:
        Endpoint host, e.g. "yike.cn-shanghai.aliyuncs.com"
    """
    if endpoint:
        host = endpoint.strip().rstrip("/")
        if "://" in host:
            host = host.split("://", 1)[1]
        return host
    if region and region in YIKE_ENDPOINT_MAP:
        return YIKE_ENDPOINT_MAP[region]
    return DEFAULT_ENDPOINT


# =============================================================================
# 请求参数构造
# =============================================================================

def _normalize_duration(seconds: Any) -> str:
    """
    Normalize a duration value to the yike seconds string format.

    The yike API expects a plain seconds string (e.g. "5", "6"); the trailing
    "s" unit suffix is NOT accepted (upstream rejects "6s" with
    ``InvalidParameter.Duration``). Accepts "5s", "5", 5; returns "5".
    Default is "5".
    """
    if seconds is None:
        return "5"
    if isinstance(seconds, str):
        s = seconds.strip().lower()
        if s.endswith("s"):
            s = s[:-1]
        if s.isdigit():
            return s
        try:
            return str(int(float(s)))
        except (ValueError, TypeError):
            return s or "5"
    try:
        return str(int(seconds))
    except (ValueError, TypeError):
        return "5"


def _normalize_resolution(resolution: Any) -> str:
    """Normalize resolution to 720P / 1080P (case-insensitive input)."""
    if not resolution:
        return "720P"
    return str(resolution).strip().upper()


def _normalize_aspect_ratio(ratio: Any) -> str:
    """Normalize aspect ratio; supports 16:9, 9:16, 4:3, 3:4, 1:1, 21:9."""
    if not ratio:
        return "16:9"
    return str(ratio).strip()


def _resolve_size_params(metadata: dict) -> tuple:
    """
    Resolve resolution / aspect_ratio from metadata, supporting the unified
    ``size`` field (e.g. "1280x720" / "720p") via ``resolve_video_size``.

    Explicit ``resolution`` / ``aspect_ratio`` take priority over ``size``.

    Returns:
        (resolution, aspect_ratio) with size-derived values when available
    """
    from app.providers.video_size_utils import resolve_video_size

    resolution = metadata.get("resolution")
    ratio = metadata.get("aspect_ratio")
    size = metadata.get("size")

    if size and (not resolution or not ratio):
        derived_ar, derived_tier = resolve_video_size(str(size))
        if not ratio and derived_ar:
            ratio = derived_ar
        if not resolution and derived_tier:
            resolution = derived_tier

    return resolution, ratio


# =============================================================================
# 辅助函数: 提取 Prompt 与媒体列表
# =============================================================================

def _extract_text_prompt(messages: List[Message]) -> str:
    """
    Extract the text prompt from messages.

    Concatenates all text content blocks from user messages into a single
    prompt string. ``{{file-xxx}}`` / ``{{var_id}}`` placeholders are left
    intact; they are substituted later with Aliyun variable names
    (图片N / 视频N / 音频N) based on the Medias list.

    Args:
        messages: List of messages

    Returns:
        Combined prompt text
    """
    prompt_parts: List[str] = []
    for msg in messages:
        if msg.role != MessageRole.USER:
            continue
        if isinstance(msg.content, str):
            prompt_parts.append(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        prompt_parts.append(block.get("text", ""))
                elif hasattr(block, "type"):
                    block_type = block.type
                    if isinstance(block_type, str):
                        is_text = block_type == "text"
                    else:
                        is_text = getattr(block_type, "value", None) == "text"
                    if is_text:
                        prompt_parts.append(block.text or "")
    return "".join(prompt_parts).strip()


def _content_block_media_type(block: Any) -> Optional[str]:
    """Map a ContentBlock to the yike media type ("image"/"video"/"audio")."""
    if isinstance(block, dict):
        btype = block.get("type", "")
        if btype in ("input_image", "image_url", "image"):
            return "image"
        if btype in ("input_video", "video_url", "video"):
            return "video"
        if btype in ("input_audio", "audio_url", "audio"):
            return "audio"
        return None
    if not hasattr(block, "type"):
        return None
    block_type = block.type
    if isinstance(block_type, str):
        tname = block_type
    else:
        tname = getattr(block_type, "value", "") or ""
    if tname in (ContentType.IMAGE_URL.value, "image"):
        return "image"
    if tname in (ContentType.VIDEO_URL.value, "video"):
        return "video"
    if tname in (ContentType.AUDIO_URL.value, "audio"):
        return "audio"
    return None


def _block_url(block: Any) -> str:
    """Extract the URL from a ContentBlock (dict or object)."""
    if isinstance(block, dict):
        url = block.get("url", "")
        if url:
            return url
        inner = block.get("image_url") or block.get("video_url") or {}
        if isinstance(inner, dict):
            return inner.get("url", "") or ""
        return ""
    return getattr(block, "url", "") or ""


_YIKE_MEDIA_PREFIX = "yike://"


def _block_media_id(block: Any) -> str:
    """Extract a media_id from a ContentBlock (dict or object)."""
    if isinstance(block, dict):
        return str(block.get("media_id", "") or "")
    return str(getattr(block, "media_id", "") or "")


def _block_var_id(block: Any) -> str:
    """Extract a user-defined var_id from a ContentBlock (dict or object)."""
    if isinstance(block, dict):
        return str(block.get("var_id", "") or "")
    return str(getattr(block, "var_id", "") or "")


def _split_media_ref(ref: str) -> str:
    """Strip the ``yike://`` prefix (resolved uploaded-asset reference)."""
    if ref.startswith(_YIKE_MEDIA_PREFIX):
        return ref[len(_YIKE_MEDIA_PREFIX):]
    return ""


# 阿里云万相/Wonder 提示词中的素材变量名 (按媒体数组顺序、类型分别计数)
_VAR_NAMES_ZH = {"image": "图片{n}", "video": "视频{n}", "audio": "音频{n}"}
_VAR_NAMES_EN = {"image": "Image {n}", "video": "Video {n}", "audio": "Audio {n}"}


def _aliyun_var_name(media_type: str, index: int, language: str = "zh") -> str:
    """Build the Aliyun prompt variable name for a media item, e.g. "图片1"."""
    table = _VAR_NAMES_EN if language == "en" else _VAR_NAMES_ZH
    return table.get(str(media_type), "图片{n}").format(n=max(1, int(index)))


def _substitute_prompt_vars(
    prompt: str,
    var_map: Dict[str, Any],
    file_var_map: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Replace ``{{var_id}}`` / ``{{file-xxx}}`` placeholders in the prompt with
    Aliyun variable names (e.g. "图片1" / "Image 1"), one per referenced media
    item.

    ``var_map`` maps var_id → ``(media_type, index)`` and ``file_var_map``
    maps file_id → ``(media_type, index)``; index is the 1-based position of
    the media item among items of the same type (图片/视频/音频分别计数, 与
    Input.Medias 数组顺序一致).

    Placeholders not present in either map are left untouched.

    Args:
        prompt:       Raw prompt text
        var_map:      var_id → (media_type, index)
        file_var_map: file_id → (media_type, index) (optional)

    Returns:
        Prompt with ``{{var_id}}`` placeholders substituted.
    """
    if not prompt or (not var_map and not file_var_map):
        return prompt
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", prompt))
    language = "zh" if has_cjk else "en"

    def _replace(match: "re.Match") -> str:
        name = match.group(1)
        info = var_map.get(name)
        if info is None and file_var_map:
            info = file_var_map.get(name)
        if info is None:
            return match.group(0)
        media_type, index = info
        return _aliyun_var_name(media_type, index, language)

    return re.sub(r"\{\{([^}]+)\}\}", _replace, prompt)


def _build_file_var_map(metadata: dict, media_list: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Build file_id → ``(media_type, index)`` for ``{{file-xxx}}`` placeholders.

    Indexes are the per-type 1-based positions of each file's media item in
    the yike ``Medias`` list (图片/视频/音频分别计数), so prompt placeholders
    line up with the numbering used in Input.Medias.

    Files whose media item is not present in ``media_list`` are skipped and
    their placeholders are left untouched by ``_substitute_prompt_vars``.
    """
    fid_map = metadata.get("file_id_media_map")
    if not isinstance(fid_map, dict) or not fid_map:
        return {}

    counters = {"image": 0, "video": 0, "audio": 0}
    index_by_media: Dict[str, Any] = {}
    for item in media_list:
        mtype = item.get("Type")
        if mtype not in counters:
            continue
        counters[mtype] += 1
        key = item.get("MediaId") or item.get("Url") or ""
        if key:
            index_by_media[key] = (mtype, counters[mtype])

    result: Dict[str, Any] = {}
    for fid, info in fid_map.items():
        if not isinstance(info, dict):
            continue
        mtype = str(info.get("type") or "").replace("input_", "")
        if mtype not in counters:
            continue
        media_id = str(info.get("media_id") or "")
        url = str(info.get("url") or "")
        if not media_id and url.startswith(_YIKE_MEDIA_PREFIX):
            media_id = _split_media_ref(url)
        key = media_id or url
        if key in index_by_media:
            result[fid] = index_by_media[key]
    return result


def _build_media_list(
    messages: List[Message],
    metadata: dict,
    return_vars: bool = False,
) -> Any:
    """
    Build the yike ``Medias`` list from request messages and metadata.

    Extracts image/video/audio references from message content blocks
    (``input_image`` / ``input_video`` / ``input_audio`` in Responses API
    format) and from metadata fields (``reference_images``,
    ``reference_videos``, ``first_frame_url``, ``last_frame_url``,
    ``file_id_media_map``), then builds the yike media array with
    ``Type`` plus either ``Url`` or ``MediaId`` (assets imported via
    ImportMedia are referenced by MediaId).

    Media items may carry a user-defined ``var_id`` (content block attribute,
    ``file_id_media_map`` entry or reference dict key); when ``return_vars``
    is True the var_id → ``(media_type, index)`` map is returned alongside so
    ``{{var_id}}`` placeholders in the prompt can be substituted with the
    Aliyun variable names ("图 1" / "Image 1", 图片和视频分别计数).

    Media already present in the list (by URL or MediaId) is not duplicated.

    Args:
        messages: Request messages (may contain URL / media_id content blocks)
        metadata: Request metadata dict
        return_vars: When True, return ``(media_list, var_map)``

    Returns:
        List of media dicts ``[{"Type": "image", "Url": "..."}]`` or
        ``[{"Type": "image", "MediaId": "..."}]``; with ``return_vars``,
        a ``(media_list, var_map)`` tuple.
    """
    media_list: List[Dict[str, str]] = []
    seen: set = set()

    def _add(type_: str, url_: str = "", media_id: str = "", var_id: str = "") -> None:
        # Normalize resolved uploaded-asset refs: yike://{MediaId} → MediaId.
        if not media_id and url_.startswith(_YIKE_MEDIA_PREFIX):
            media_id = _split_media_ref(url_)
            url_ = ""
        if not url_ and not media_id:
            return
        key = media_id or url_
        if key in seen:
            return
        seen.add(key)
        item: Dict[str, str] = {"Type": type_}
        if media_id:
            item["MediaId"] = media_id
        else:
            item["Url"] = url_
        if var_id:
            item["_var_id"] = var_id
        media_list.append(item)

    def _entry_ref(info: dict) -> tuple:
        """Extract (media_id, url, var_id) from a metadata/ref dict."""
        media_id = str(info.get("media_id") or "")
        url = info.get("url") or info.get("image_url") or ""
        if not media_id and url.startswith(_YIKE_MEDIA_PREFIX):
            media_id = _split_media_ref(url)
            url = ""
        return media_id, url, str(info.get("var_id") or "")

    # 1. Extract media from message content blocks
    for msg in messages:
        if msg.role != MessageRole.USER:
            continue
        content = msg.content
        if isinstance(content, list):
            for block in content:
                mtype = _content_block_media_type(block)
                if mtype:
                    _add(mtype, _block_url(block), _block_media_id(block),
                         _block_var_id(block))

    # 2. Extract media from metadata
    file_id_media_map = metadata.get("file_id_media_map")
    if isinstance(file_id_media_map, dict):
        for info in file_id_media_map.values():
            if isinstance(info, dict):
                mtype = info.get("type", "")
                if mtype not in ("image", "input_image", "video", "input_video", "audio", "input_audio"):
                    continue
                yike_type = mtype.replace("input_", "")
                media_id, url, var_id = _entry_ref(info)
                _add(yike_type, url, media_id, var_id)

    for ref_key, ref_type in (
        ("reference_images", "image"),
        ("reference_videos", "video"),
        ("reference_audios", "audio"),
    ):
        refs = metadata.get(ref_key)
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, str):
                    _add(ref_type, ref)
                elif isinstance(ref, dict):
                    media_id, url, var_id = _entry_ref(ref)
                    _add(ref_type, url, media_id, var_id)

    for key in ("first_frame_url", "last_frame_url"):
        value = metadata.get(key)
        if isinstance(value, dict):
            media_id, url, var_id = _entry_ref(value)
            _add("image", url, media_id, var_id)
        elif isinstance(value, str) and value:
            _add("image", value)

    # Build var_id → (media_type, index) map and strip internal markers.
    var_map: Dict[str, Any] = {}
    counters = {"image": 0, "video": 0, "audio": 0}
    for item in media_list:
        mtype = item["Type"]
        counters[mtype] += 1
        var_id = item.pop("_var_id", None)
        if var_id:
            var_map[var_id] = (mtype, counters[mtype])

    if return_vars:
        return media_list, var_map
    return media_list


def infer_job_type(media: List[Dict[str, str]]) -> str:
    """
    Infer the yike JobType from the media list.

    - No media          → text_to_video
    - Exactly 2 images  → first_last_frame
    - Single image      → image_to_video
    - Otherwise         → reference_to_video
    """
    if not media:
        return "text_to_video"
    images = [m for m in media if m.get("Type") == "image"]
    if len(images) == 2 and len(media) == 2:
        return "first_last_frame"
    if len(images) == 1 and len(media) == 1:
        return "image_to_video"
    return "reference_to_video"


def build_input_json(
    *,
    prompt: str = "",
    media: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Build the yike ``Input`` JSON string.

    The Input field is a JSON string containing:
    - Prompt: String. Required. The prompt text.
    - Medias: Optional media list ``[{"Type": "image|video|audio", "Url": "..."}]``

    Args:
        prompt: Prompt text
        media: Optional media list

    Returns:
        JSON string
    """
    obj: Dict[str, Any] = {}
    if prompt:
        obj["Prompt"] = prompt
    if media:
        obj["Medias"] = media
    return json.dumps(obj, ensure_ascii=False)


def parse_output_medias(output_json: Optional[str]) -> List[Dict[str, Any]]:
    """
    Parse the yike ``Output`` JSON string into a media list.

    Output format: ``{"Medias": [{"MediaId": "", "OutputUrl": "https://..."}]}``
    (also tolerates ``OuputUrl`` / ``outputUrl`` / ``url`` key spellings).

    Args:
        output_json: The Output JSON string from GetVideoGenerationJob

    Returns:
        List of ``{"MediaId": ..., "OutputUrl": ...}`` dicts
    """
    if not output_json:
        return []
    try:
        data = json.loads(output_json)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    medias = data.get("Medias") or data.get("medias") or []
    if not isinstance(medias, list):
        return []
    result = []
    for m in medias:
        if not isinstance(m, dict):
            continue
        url = (
            m.get("OutputUrl")
            or m.get("OuputUrl")
            or m.get("outputUrl")
            or m.get("url")
            or ""
        )
        result.append({
            "MediaId": m.get("MediaId") or m.get("mediaId") or "",
            "OutputUrl": url,
        })
    return result


# =============================================================================
# API 调用: SubmitVideoGenerationJob
# =============================================================================

async def submit_video_generation_job(
    client,
    *,
    access_key_id: str,
    access_key_secret: str,
    job_type: str,
    model: str,
    input_json: str,
    resolution: str = "720P",
    aspect_ratio: str = "16:9",
    duration: str = "5s",
    n: int = 1,
    scene: str = "general",
    client_token: Optional[str] = None,
    user_data: Optional[str] = None,
    job_parameters: Optional[str] = None,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    version: Optional[str] = None,
    tracer: Any = None,
) -> Dict[str, Any]:
    """
    Call SubmitVideoGenerationJob and return the parsed response.

    Args:
        client: httpx.AsyncClient
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        job_type: text_to_video / image_to_video / first_last_frame /
            reference_to_video
        model: Model name (e.g. wonder-pro)
        input_json: Input JSON string (Prompt + Medias)
        resolution: 720P or 1080P
        aspect_ratio: 16:9 / 9:16 / 4:3 / 3:4 / 1:1 / 21:9
        duration: Output duration in seconds, e.g. "5" (4~15s)
        n: Number of outputs (1~4)
        scene: Scene type (general)
        client_token: Idempotency token
        user_data: User business data (JSON)
        job_parameters: Task feature parameters (JSON string)
        region: Optional region id
        endpoint: Optional endpoint override
        security_token: Optional STS security token
        version: Optional API version override (defaults to YIKE_API_VERSION)
        tracer: Optional tracer for child span

    Returns:
        ``{"RequestId": str, "JobId": str}``

    Raises:
        RuntimeError: On API error
    """
    api_version = version or YIKE_API_VERSION
    params: Dict[str, Any] = {
        "JobType": job_type,
        "Model": model,
        "Input": input_json,
        "Resolution": _normalize_resolution(resolution),
        "AspectRatio": _normalize_aspect_ratio(aspect_ratio),
        "Duration": _normalize_duration(duration),
        "N": int(n or 1),
        "Scene": scene or "general",
    }
    if client_token:
        params["ClientToken"] = client_token
    if user_data:
        params["UserData"] = user_data
    if job_parameters:
        params["JobParameters"] = job_parameters

    host = resolve_yike_endpoint(region, endpoint)
    query = build_rpc_params(
        action="SubmitVideoGenerationJob",
        version=api_version,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        params=params,
        security_token=security_token,
    )
    url = _rpc_request_url(host, query)

    _span = None
    if tracer:
        _span = tracer.start_child(
            model, model=model, provider_type="aliyun",
            input_data=params, obs_type="span",
        )
        if _span:
            _span.log_input(params)
    _error: Optional[Exception] = None

    try:
        response = await client.post(
            url,
            content=_rpc_form_body(params),
            headers=_rpc_headers(api_version, "SubmitVideoGenerationJob"),
        )
        if response.status_code >= 400:
            error_msg = f"Aliyun SubmitVideoGenerationJob error ({response.status_code})"
            try:
                error_body = response.json()
                code = error_body.get("Code") or error_body.get("code") or ""
                message = error_body.get("Message") or error_body.get("message") or ""
                request_id = error_body.get("RequestId") or error_body.get("requestId") or ""
                error_msg += f": [{code}] {message} (RequestId: {request_id})"
            except Exception:
                error_msg += f": {response.text}"
            raise RuntimeError(error_msg)

        result = response.json()
        job_id = result.get("JobId") or result.get("jobId")
        if not job_id:
            raise RuntimeError(
                f"No JobId in response: {json.dumps(result, ensure_ascii=False)}"
            )
        if _span:
            _span.log_output(result)
        return {
            "RequestId": result.get("RequestId") or result.get("requestId") or "",
            "JobId": job_id,
        }
    except httpx.RequestError as e:
        raise RuntimeError(f"Aliyun video-synthesis network error: {e}")
    except Exception:
        _error = sys.exc_info()[1]
        raise
    finally:
        if _span:
            _span.end(error=_error)


# =============================================================================
# API 调用: GetVideoGenerationJob
# =============================================================================

async def get_video_generation_job(
    client,
    *,
    access_key_id: str,
    access_key_secret: str,
    job_id: str,
    request_id: Optional[str] = None,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    version: Optional[str] = None,
    tracer: Any = None,
) -> Dict[str, Any]:
    """
    Call GetVideoGenerationJob and return the parsed response.

    Args:
        client: httpx.AsyncClient
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        job_id: Job ID returned by SubmitVideoGenerationJob
        request_id: Optional RequestId (accepted for compatibility; the
            official yike API only requires JobId)
        region: Optional region id
        endpoint: Optional endpoint override
        security_token: Optional STS security token
        version: Optional API version override (defaults to YIKE_API_VERSION)
        tracer: Optional tracer for child span

    Returns:
        ``{"RequestId": str, "VideoGenerationJob": {...}}``

    Raises:
        RuntimeError: On API error
    """
    api_version = version or YIKE_API_VERSION
    params: Dict[str, Any] = {"JobId": job_id or request_id or ""}

    host = resolve_yike_endpoint(region, endpoint)
    query = build_rpc_params(
        action="GetVideoGenerationJob",
        version=api_version,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        params=params,
        security_token=security_token,
    )
    url = _rpc_request_url(host, query)

    _span = None
    if tracer:
        _span = tracer.start_child(
            job_id, model=job_id, provider_type="aliyun",
            input_data=params, obs_type="span",
        )
        if _span:
            _span.log_input(params)
    _error: Optional[Exception] = None

    try:
        response = await client.post(
            url,
            content=_rpc_form_body(params),
            headers=_rpc_headers(api_version, "GetVideoGenerationJob"),
        )
        if response.status_code >= 400:
            error_msg = f"Aliyun GetVideoGenerationJob error ({response.status_code})"
            try:
                error_body = response.json()
                code = error_body.get("Code") or error_body.get("code") or ""
                message = error_body.get("Message") or error_body.get("message") or ""
                request_id = error_body.get("RequestId") or error_body.get("requestId") or ""
                error_msg += f": [{code}] {message} (RequestId: {request_id})"
            except Exception:
                error_msg += f": {response.text}"
            raise RuntimeError(error_msg)

        result = response.json()
        if _span:
            _span.log_output(result)
        return result
    except httpx.RequestError as e:
        raise RuntimeError(f"Aliyun video task query network error: {e}")
    except Exception:
        _error = sys.exc_info()[1]
        raise
    finally:
        if _span:
            _span.end(error=_error)


async def delete_medias(
    client,
    *,
    access_key_id: str,
    access_key_secret: str,
    media_ids,
    delete_physical_files: bool = True,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    version: Optional[str] = None,
    tracer: Any = None,
) -> Dict[str, Any]:
    """
    Call the yike media deletion API and return the parsed response.

    Accepts one or more MediaIds (comma-separated string or iterable).
    ``delete_physical_files=True`` (default) also deletes the physical files.

    The action/params adapt to the API version:
    - ``2026-07-07`` and newer: ``DeleteMedias`` with ``DeletePhysicalFiles``
    - older versions: ``DeleteYikeAssetMediaInfos`` with ``LogicDelete``
      (``False`` = delete media info and files, i.e. physical deletion)

    Args:
        client: httpx.AsyncClient
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        media_ids: MediaId or list of MediaIds (joined by commas)
        delete_physical_files: Whether to delete the physical files too
            (default True)
        region: Optional region id
        endpoint: Optional endpoint override
        security_token: Optional STS security token
        version: Optional API version override (defaults to YIKE_API_VERSION)
        tracer: Optional tracer for child span

    Returns:
        Parsed deletion response dict (``{"RequestId": ..., ...}``).

    Raises:
        RuntimeError: On API error
    """
    api_version = version or YIKE_API_VERSION

    if isinstance(media_ids, str):
        media_ids = [media_ids]
    normalized_ids = [str(x).strip() for x in (media_ids or []) if str(x).strip()]
    if not normalized_ids:
        raise ValueError("MediaIds is required for media deletion")

    use_new_action = str(api_version) >= "2026-07-07"
    action = "DeleteMedias" if use_new_action else "DeleteYikeAssetMediaInfos"
    params: Dict[str, Any] = {"MediaIds": ",".join(normalized_ids)}
    if use_new_action:
        params["DeletePhysicalFiles"] = bool(delete_physical_files)
    else:
        params["LogicDelete"] = not bool(delete_physical_files)

    host = resolve_yike_endpoint(region, endpoint)
    query = build_rpc_params(
        action=action,
        version=api_version,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        params=params,
        security_token=security_token,
    )
    url = _rpc_request_url(host, query)

    _span = None
    if tracer:
        _span = tracer.start_child(
            ",".join(normalized_ids), model="delete-medias", provider_type="aliyun",
            input_data=params, obs_type="span",
        )
        if _span:
            _span.log_input(params)
    _error: Optional[Exception] = None

    try:
        response = await client.post(
            url,
            content=_rpc_form_body(params),
            headers=_rpc_headers(api_version, action),
        )
        if response.status_code >= 400:
            error_msg = f"Aliyun {action} error ({response.status_code})"
            try:
                error_body = response.json()
                code = error_body.get("Code") or error_body.get("code") or ""
                message = error_body.get("Message") or error_body.get("message") or ""
                request_id = error_body.get("RequestId") or error_body.get("requestId") or ""
                error_msg += f": [{code}] {message} (RequestId: {request_id})"
            except Exception:
                error_msg += f": {response.text}"
            raise RuntimeError(error_msg)

        result = response.json()
        if _span:
            _span.log_output(result)
        return result
    except httpx.RequestError as e:
        raise RuntimeError(f"Aliyun media deletion network error: {e}")
    except Exception:
        _error = sys.exc_info()[1]
        raise
    finally:
        if _span:
            _span.end(error=_error)


async def import_media(
    client,
    *,
    access_key_id: str,
    access_key_secret: str,
    input_url: str,
    media_type: str = "image",
    register_config: Any = None,
    need_third_party_asset: bool = False,
    import_source: str = "url",
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    version: Optional[str] = None,
    tracer: Any = None,
) -> Dict[str, Any]:
    """
    Call ImportMedia and return the parsed response.

    Registers a publicly reachable URL (``ImportSource="url"``) in the yike
    media library and returns a ``MediaId`` usable in video generation
    ``Input.Medias``.

    Returns ``{"RequestId": str, "MediaId": str}``.

    Args:
        client: httpx.AsyncClient
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        input_url: Publicly reachable media URL
        media_type: image / video / audio
        register_config: Optional RegisterConfig (dict or JSON string).
            Wonder 模型需要 ``{"NeedThirdPartyAsset": true}`` 才能在视频生成中
            直接使用 MediaId, 也可通过 ``need_third_party_asset=True`` 快捷设置。
        need_third_party_asset: Shorthand for
            ``register_config={"NeedThirdPartyAsset": true}``
        import_source: Import source, fixed to "url" for now
        region: Optional region id
        endpoint: Optional endpoint override
        security_token: Optional STS security token
        version: Optional API version override (defaults to YIKE_API_VERSION)
        tracer: Optional tracer for child span

    Returns:
        Parsed import response dict.

    Raises:
        RuntimeError: On API error
    """
    api_version = version or YIKE_API_VERSION
    media_type = str(media_type or "image").strip().lower()
    if media_type not in ("image", "video", "audio"):
        raise ValueError(
            f"Unsupported MediaType: {media_type!r}. Use image / video / audio."
        )

    params: Dict[str, Any] = {
        "ImportSource": str(import_source or "url").strip() or "url",
        "InputURL": str(input_url or "").strip(),
        "MediaType": media_type,
        # Required by yike ImportMedia — omitting it causes the call to fail.
        "Overwrite": True,
    }
    if not params["InputURL"]:
        raise ValueError("InputURL is required for ImportMedia")

    rc = register_config
    if rc is None and need_third_party_asset:
        rc = {"NeedThirdPartyAsset": True}
    if isinstance(rc, dict):
        rc = json.dumps(rc, ensure_ascii=False)
    if rc:
        params["RegisterConfig"] = rc

    host = resolve_yike_endpoint(region, endpoint)
    query = build_rpc_params(
        action="ImportMedia",
        version=api_version,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        params=params,
        security_token=security_token,
    )
    url = _rpc_request_url(host, query)

    _span = None
    if tracer:
        _span = tracer.start_child(
            input_url, model="import-media", provider_type="aliyun",
            input_data=params, obs_type="span",
        )
        if _span:
            _span.log_input(params)
    _error: Optional[Exception] = None

    try:
        response = await client.post(
            url,
            content=_rpc_form_body(params),
            headers=_rpc_headers(api_version, "ImportMedia"),
        )
        if response.status_code >= 400:
            error_msg = f"Aliyun ImportMedia error ({response.status_code})"
            try:
                error_body = response.json()
                code = error_body.get("Code") or error_body.get("code") or ""
                message = error_body.get("Message") or error_body.get("message") or ""
                request_id = error_body.get("RequestId") or error_body.get("requestId") or ""
                error_msg += f": [{code}] {message} (RequestId: {request_id})"
            except Exception:
                error_msg += f": {response.text}"
            raise RuntimeError(error_msg)

        result = response.json()
        if _span:
            _span.log_output(result)
        return result
    except httpx.RequestError as e:
        raise RuntimeError(f"Aliyun media import network error: {e}")
    except Exception:
        _error = sys.exc_info()[1]
        raise
    finally:
        if _span:
            _span.end(error=_error)


async def get_media(
    client,
    *,
    access_key_id: str,
    access_key_secret: str,
    media_id: str,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    version: Optional[str] = None,
    tracer: Any = None,
) -> Dict[str, Any]:
    """
    Call GetMedia and return the parsed response.

    Returns the yike media detail::

        {
          "RequestId": str,
          "MediaInfo": {
            "MediaId": str,
            "MediaBasicInfo": {
              "MediaId": str,
              "InputURL": str,
              "MediaType": str,
              "Status": str
            }
          }
        }

    Args:
        client: httpx.AsyncClient
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        media_id: yike MediaId (as returned by ImportMedia)
        region: Optional region id
        endpoint: Optional endpoint override
        security_token: Optional STS security token
        version: Optional API version override (defaults to YIKE_API_VERSION)
        tracer: Optional tracer for child span

    Returns:
        Parsed GetMedia response dict.

    Raises:
        RuntimeError: On API error
    """
    api_version = version or YIKE_API_VERSION
    media_id = str(media_id or "").strip()
    if not media_id:
        raise ValueError("MediaId is required for GetMedia")

    params: Dict[str, Any] = {"MediaId": media_id}
    host = resolve_yike_endpoint(region, endpoint)
    query = build_rpc_params(
        action="GetMedia",
        version=api_version,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        params=params,
        security_token=security_token,
    )
    url = _rpc_request_url(host, query)

    _span = None
    if tracer:
        _span = tracer.start_child(
            media_id, model="get-media", provider_type="aliyun",
            input_data=params, obs_type="span",
        )
        if _span:
            _span.log_input(params)
    _error: Optional[Exception] = None

    try:
        response = await client.post(
            url,
            content=_rpc_form_body(params),
            headers=_rpc_headers(api_version, "GetMedia"),
        )
        if response.status_code >= 400:
            error_msg = f"Aliyun GetMedia error ({response.status_code})"
            try:
                error_body = response.json()
                code = error_body.get("Code") or error_body.get("code") or ""
                message = error_body.get("Message") or error_body.get("message") or ""
                request_id = error_body.get("RequestId") or error_body.get("requestId") or ""
                error_msg += f": [{code}] {message} (RequestId: {request_id})"
            except Exception:
                error_msg += f": {response.text}"
            raise RuntimeError(error_msg)

        result = response.json()
        if _span:
            _span.log_output(result)
        return result
    except httpx.RequestError as e:
        raise RuntimeError(f"Aliyun media query network error: {e}")
    except Exception:
        _error = sys.exc_info()[1]
        raise
    finally:
        if _span:
            _span.end(error=_error)


async def get_yike_job_credit(
    client,
    *,
    access_key_id: str,
    access_key_secret: str,
    job_id: str,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    version: Optional[str] = None,
    tracer: Any = None,
) -> Dict[str, Any]:
    """
    Call GetYikeJobCredit and return the parsed response.

    Returns the credit cost consumed by a finished video generation job:
    ``{"RequestId": str, "JobId": str, "JobCreditCost": float,
    "CreditStatus": str}``.

    Args:
        client: httpx.AsyncClient
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        job_id: Job ID returned by SubmitVideoGenerationJob
        region: Optional region id
        endpoint: Optional endpoint override
        security_token: Optional STS security token
        version: Optional API version override (defaults to YIKE_API_VERSION)
        tracer: Optional tracer for child span

    Returns:
        Parsed credit response dict.

    Raises:
        RuntimeError: On API error
    """
    api_version = version or YIKE_API_VERSION
    params: Dict[str, Any] = {"JobId": job_id}

    host = resolve_yike_endpoint(region, endpoint)
    query = build_rpc_params(
        action="GetYikeJobCredit",
        version=api_version,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        params=params,
        security_token=security_token,
    )
    url = _rpc_request_url(host, query)

    _span = None
    if tracer:
        _span = tracer.start_child(
            job_id, model=job_id, provider_type="aliyun",
            input_data=params, obs_type="span",
        )
        if _span:
            _span.log_input(params)
    _error: Optional[Exception] = None

    try:
        response = await client.post(
            url,
            content=_rpc_form_body(params),
            headers=_rpc_headers(api_version, "GetYikeJobCredit"),
        )
        if response.status_code >= 400:
            error_msg = f"Aliyun GetYikeJobCredit error ({response.status_code})"
            try:
                error_body = response.json()
                code = error_body.get("Code") or error_body.get("code") or ""
                message = error_body.get("Message") or error_body.get("message") or ""
                request_id = error_body.get("RequestId") or error_body.get("requestId") or ""
                error_msg += f": [{code}] {message} (RequestId: {request_id})"
            except Exception:
                error_msg += f": {response.text}"
            raise RuntimeError(error_msg)

        result = response.json()
        if _span:
            _span.log_output(result)
        return result
    except httpx.RequestError as e:
        raise RuntimeError(f"Aliyun video task credit query network error: {e}")
    except Exception:
        _error = sys.exc_info()[1]
        raise
    finally:
        if _span:
            _span.end(error=_error)


# GetYikeJobCredit 的结算状态: 任务 Finished 后积分异步结算,
# 结算完成前 CreditStatus 为 "init" 且 JobCreditCost=0。
_CREDIT_SETTLED_STATUS = "success"
_CREDIT_POLL_TIMEOUT_S = 20
_CREDIT_POLL_INTERVAL_S = 3


async def _fetch_job_credit(
    *,
    access_key_id: str,
    access_key_secret: str,
    job_id: str,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    version: Optional[str] = None,
    tracer: Any = None,
    credit_timeout: int = _CREDIT_POLL_TIMEOUT_S,
    poll_interval: int = _CREDIT_POLL_INTERVAL_S,
) -> Optional[Dict[str, Any]]:
    """
    Best-effort fetch of the credit cost consumed by a finished job.

    Aliyun settles job credits asynchronously: right after the job reaches
    Finished, GetYikeJobCredit returns ``CreditStatus="init"`` with
    ``JobCreditCost=0``. This polls until the credit is settled
    (``CreditStatus == "success"``), bounded by ``credit_timeout``. On
    timeout the last response is returned as-is (status/cost may still be
    init/0); a failed credit query must never fail the video generation
    itself, so errors are logged and None is returned.

    Credit info is a bonus for usage reporting; a failed credit query must
    never fail the video generation itself, so errors are logged and None is
    returned.

    Args:
        credit_timeout: Max seconds to wait for credit settlement (default 20)
        poll_interval: Seconds between credit polls (default 3)

    Returns:
        Parsed credit response dict, or None when the query fails.
    """
    try:
        from app.http_client import get_shared_client

        client = await get_shared_client()
        deadline = time.time() + max(0, int(credit_timeout))
        last: Optional[Dict[str, Any]] = None
        while True:
            try:
                last = await get_yike_job_credit(
                    client,
                    access_key_id=access_key_id,
                    access_key_secret=access_key_secret,
                    job_id=job_id,
                    region=region,
                    endpoint=endpoint,
                    security_token=security_token,
                    version=version,
                    tracer=tracer,
                )
            except Exception as e:
                logger.warning("Failed to fetch yike job credit for %s: %s", job_id, e)
                return None
            if (last.get("CreditStatus") or "") == _CREDIT_SETTLED_STATUS:
                return last
            if time.time() >= deadline:
                return last
            await asyncio.sleep(max(0, int(poll_interval)))
    except Exception as e:
        logger.warning("Failed to fetch yike job credit for %s: %s", job_id, e)
        return None


# =============================================================================
# 任务轮询
# =============================================================================

async def _poll_video_job(
    *,
    access_key_id: str,
    access_key_secret: str,
    job_id: str,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    version: Optional[str] = None,
    timeout: int = _POLL_MAX_WAIT_S,
    poll_interval: int = _POLL_INTERVAL_S,
    tracer: Any = None,
    on_progress: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Poll GetVideoGenerationJob until the task reaches a terminal state.

    Args:
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        job_id: Job ID to poll
        region: Optional region id
        endpoint: Optional endpoint override
        security_token: Optional STS security token
        timeout: Maximum time to wait in seconds
        poll_interval: Interval between polls in seconds
        tracer: Tracer for creating poll span
        on_progress: Optional async callback ``(status) -> None``

    Returns:
        The final VideoGenerationJob dict

    Raises:
        TimeoutError: If polling exceeds timeout
        RuntimeError: If the API returns an unexpected error
    """
    from app.http_client import get_shared_client

    client = await get_shared_client()
    start_time = time.time()
    last_status = STATUS_CREATED

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise TimeoutError(
                f"Video generation task {job_id} timed out after {timeout}s"
            )

        result = await get_video_generation_job(
            client,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            job_id=job_id,
            region=region,
            endpoint=endpoint,
            security_token=security_token,
            version=version,
            tracer=tracer,
        )
        job = result.get("VideoGenerationJob") or {}
        if not isinstance(job, dict):
            job = {}
        status = job.get("Status") or STATUS_CREATED
        if status != last_status:
            logger.debug(
                "Video task %s status: %s (elapsed %.1fs)", job_id, status, elapsed
            )
            last_status = status
        if on_progress is not None:
            try:
                await on_progress(status)
            except Exception as _pe:
                logger.debug("on_progress callback error: %s", _pe)

        if status in TERMINAL_STATUSES:
            return job

        await asyncio.sleep(poll_interval)


# =============================================================================
# 非流式视频生成
# =============================================================================

def _build_video_usage_extra(
    job: Dict[str, Any],
    metadata: dict,
    model: str,
    credit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the usage ``extra`` dict for video generation pricing/statistics.

    ``credit`` (optional) is the GetYikeJobCredit response; its
    ``JobCreditCost`` is exposed as ``credits`` (the standard usage field)
    together with ``CreditStatus``.
    """
    resolution = job.get("Resolution") or _normalize_resolution(metadata.get("resolution"))
    ratio = job.get("AspectRatio") or metadata.get("aspect_ratio") or "16:9"
    duration = job.get("Duration") or ""
    try:
        dur = float(str(duration).rstrip("sS")) if duration else 0.0
    except (ValueError, TypeError):
        dur = 0.0
    try:
        video_count = int(job.get("N") or 1)
    except (ValueError, TypeError):
        video_count = 1
    if video_count < 1:
        video_count = 1

    file_id_media_map = metadata.get("file_id_media_map")
    has_reference_video = False
    if isinstance(file_id_media_map, dict):
        for info in file_id_media_map.values():
            if isinstance(info, dict) and info.get("type") in ("video", "input_video"):
                has_reference_video = True
                break

    extra = {
        "output_video_number": video_count,
        "output_video_tokens": 0,
        "output_video_resolution": str(resolution).upper(),
        "output_video_aspect": str(ratio),
        "output_video_seconds": dur,
        "output_video_audio": False,
        "output_video_reference_video": has_reference_video,
        "model": model,
    }

    if credit:
        try:
            cost = float(credit.get("JobCreditCost") or 0)
        except (ValueError, TypeError):
            cost = 0.0
        extra["credits"] = cost
        status = str(credit.get("CreditStatus") or "").strip()
        if status:
            extra["credit_status"] = status
    return extra


def _build_success_response(
    model: str,
    job: Dict[str, Any],
    job_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    credit: Optional[Dict[str, Any]] = None,
    tracer: Any = None,
) -> ChatResponse:
    """
    Build a successful ChatResponse with video URLs.

    The message content is a JSON list of ``video_generation_call`` items
    (compatible with the Responses API adapter), one per output media.
    """
    if metadata is None:
        metadata = {}
    medias = parse_output_medias(job.get("Output"))

    response_id = gen_id("vid")
    video_call_items = []
    for i, media in enumerate(medias):
        video_call_items.append({
            "id": f"{response_id}-{i}" if i > 0 else response_id,
            "type": "video_generation_call",
            "status": "completed",
            "result": media.get("OutputUrl", ""),
        })
    if not video_call_items:
        video_call_items.append({
            "id": response_id,
            "type": "video_generation_call",
            "status": "completed",
            "result": "",
        })

    if tracer:
        tracer.log_output({
            "task_id": job_id,
            "status": "finished",
            "video_urls": [m.get("OutputUrl", "") for m in medias],
        })

    extra = _build_video_usage_extra(job, metadata, model, credit=credit)
    extra["_task_id"] = job_id
    duration = extra.get("output_video_seconds") or 0.0
    usage = UsageInfo(
        prompt_tokens=0,
        completion_tokens=int(duration) if duration > 0 else 1,
        total_tokens=int(duration) if duration > 0 else 1,
        extra=extra,
    )

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
        provider="aliyun",
    )


async def execute_video_generation(
    access_key_id: str,
    access_key_secret: str,
    model: str,
    messages: List[Message],
    metadata: dict,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
    security_token: Optional[str] = None,
    api_version: Optional[str] = None,
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute an Aliyun video generation request (non-streaming).

    1. POST SubmitVideoGenerationJob → get JobId
    2. Poll GetVideoGenerationJob until Finished/Failed
    3. Return ChatResponse with video URL or error

    Args:
        access_key_id: Alibaba Cloud AccessKey ID
        access_key_secret: Alibaba Cloud AccessKey Secret
        model: Model name (e.g. "wonder-pro")
        messages: Request messages
        metadata: Request metadata (resolution / aspect_ratio / seconds / n /
            job_type / media references …)
        region: Optional region id
        endpoint: Optional endpoint override
        security_token: Optional STS security token
        tracer: Tracer for creating child spans

    Returns:
        ChatResponse with video URL or error information

    Raises:
        RuntimeError: If API call or polling fails
    """
    from app.http_client import get_shared_client

    prompt = _extract_text_prompt(messages)
    media, var_map = _build_media_list(messages, metadata, return_vars=True)
    file_var_map = _build_file_var_map(metadata, media)
    prompt = _substitute_prompt_vars(prompt, var_map, file_var_map)
    job_type = metadata.get("job_type") or infer_job_type(media)
    input_json = metadata.get("input")
    if not input_json:
        input_json = build_input_json(prompt=prompt, media=media)

    resolution, aspect_ratio = _resolve_size_params(metadata)
    seconds = metadata.get("seconds") or metadata.get("duration")
    n = metadata.get("n") or 1
    scene = metadata.get("scene") or "general"
    client_token = metadata.get("client_token")
    user_data = metadata.get("user_data")
    job_parameters = metadata.get("job_parameters")

    # Determine timeout from model config (default 900s)
    timeout = metadata.get("timeout", _POLL_MAX_WAIT_S)

    logger.info(
        "Initiating Aliyun video generation: model=%s, job_type=%s, prompt_len=%d",
        model, job_type, len(prompt),
    )

    _child_span = None
    if tracer:
        _child_span = tracer.start_child(
            model, model=model, provider_type="aliyun",
            input_data={
                "model": model,
                "job_type": job_type,
                "input": input_json,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "duration": seconds,
                "n": n,
            },
            obs_type="generation",
        )
        if _child_span:
            _child_span.log_input({"input": input_json})
    _trace_error: Optional[Exception] = None

    try:
        client = await get_shared_client()
        result = await submit_video_generation_job(
            client,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            job_type=job_type,
            model=model,
            input_json=input_json,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            duration=seconds,
            n=n,
            scene=scene,
            client_token=client_token,
            user_data=user_data,
            job_parameters=job_parameters,
            region=region,
            endpoint=endpoint,
            security_token=security_token,
            version=api_version,
            tracer=_child_span,
        )
        job_id = result["JobId"]
        logger.info("Video task created: job_id=%s", job_id)

        hook = metadata.get("_on_task_created")
        if hook:
            hook(job_id)

        job = await _poll_video_job(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            job_id=job_id,
            region=region,
            endpoint=endpoint,
            security_token=security_token,
            version=api_version,
            timeout=timeout,
            tracer=_child_span,
        )
        status = job.get("Status") or ""
        if status == STATUS_FAILED:
            error_message = job.get("ErrorMessage") or "Video generation failed"
            raise RuntimeError(
                f"Video generation task {job_id} failed: {error_message}"
            )
        credit = await _fetch_job_credit(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            job_id=job_id,
            region=region,
            endpoint=endpoint,
            security_token=security_token,
            version=api_version,
            tracer=_child_span,
        )
        return _build_success_response(
            model, job, job_id, metadata=metadata, credit=credit,
            tracer=_child_span,
        )
    except TimeoutError:
        raise RuntimeError(f"Video generation task timed out after {timeout}s")
    except Exception as e:
        _trace_error = e
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)


# =============================================================================
# 流式视频生成
# =============================================================================

async def stream_video_generation(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    """
    Stream video generation progress as SSE events.

    This wraps the non-streaming :func:`execute_video_generation` call and
    yields status updates as streaming chunks. The credentials, region and
    endpoint are read from ``request.metadata`` (set by the provider before
    calling).

    Args:
        chat_fn: The provider's ``chat`` method (for executing the actual request)
        request: The chat request

    Yields:
        StreamChunk objects with progress updates and final result
    """
    from app.http_client import get_shared_client

    response_id = gen_id("vid")
    model = request.model
    metadata = request.metadata

    access_key_id = metadata.get("_access_key_id", "")
    access_key_secret = metadata.get("_access_key_secret", "")
    region = metadata.get("_region")
    endpoint = metadata.get("_endpoint")
    security_token = metadata.get("_security_token")
    api_version = metadata.get("_api_version")
    timeout = metadata.get("timeout", _POLL_MAX_WAIT_S)

    def _emit_error(message: str) -> StreamChunk:
        return StreamChunk(
            event_type=StreamEventType.CONTENT_DELTA,
            id=response_id,
            model=model,
            delta_content=f"\n❌ {message}\n",
        )

    def _emit_done(reason: FinishReason, usage: Optional[UsageInfo] = None) -> StreamChunk:
        return StreamChunk(
            event_type=StreamEventType.DONE,
            id=response_id,
            model=model,
            finish_reason=reason,
            usage=usage or UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )

    yield StreamChunk(
        event_type=StreamEventType.CONTENT_DELTA,
        id=response_id,
        model=model,
        delta_content="🎬 正在提交阿里云视频生成任务...\n",
    )

    prompt = _extract_text_prompt(request.messages)
    media, var_map = _build_media_list(request.messages, metadata, return_vars=True)
    file_var_map = _build_file_var_map(metadata, media)
    prompt = _substitute_prompt_vars(prompt, var_map, file_var_map)
    job_type = metadata.get("job_type") or infer_job_type(media)
    input_json = metadata.get("input")
    if not input_json:
        input_json = build_input_json(prompt=prompt, media=media)
    resolution, aspect_ratio = _resolve_size_params(metadata)

    try:
        client = await get_shared_client()
        result = await submit_video_generation_job(
            client,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            job_type=job_type,
            model=model,
            input_json=input_json,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            duration=metadata.get("seconds") or metadata.get("duration"),
            n=metadata.get("n") or 1,
            scene=metadata.get("scene") or "general",
            client_token=metadata.get("client_token"),
            user_data=metadata.get("user_data"),
            job_parameters=metadata.get("job_parameters"),
            region=region,
            endpoint=endpoint,
            security_token=security_token,
            version=api_version,
        )
        job_id = result["JobId"]
    except Exception as e:
        yield _emit_error(str(e))
        yield _emit_done(FinishReason.ERROR)
        return

    yield StreamChunk(
        event_type=StreamEventType.CONTENT_DELTA,
        id=response_id,
        model=model,
        delta_content=f"✅ 任务已提交 (JobId: {job_id})\n⏳ 正在生成视频...\n",
    )

    # ── Poll with inline progress emission ─────────────────────────────
    job: Dict[str, Any] = {}
    last_status = STATUS_CREATED
    start_time = time.time()
    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                yield _emit_error(f"任务 {job_id} 超时 ({timeout}s)")
                yield _emit_done(FinishReason.ERROR)
                return

            client = await get_shared_client()
            result = await get_video_generation_job(
                client,
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
                job_id=job_id,
                region=region,
                endpoint=endpoint,
                security_token=security_token,
                version=api_version,
            )
            job = result.get("VideoGenerationJob") or {}
            if not isinstance(job, dict):
                job = {}
            status = job.get("Status") or STATUS_CREATED

            if status != last_status:
                last_status = status
                emoji = STATUS_EMOJI.get(status, "⏳")
                yield StreamChunk(
                    event_type=StreamEventType.CONTENT_DELTA,
                    id=response_id,
                    model=model,
                    delta_content=f"{emoji} 状态: {status}\n",
                )

            if status in TERMINAL_STATUSES:
                break
            await asyncio.sleep(_POLL_INTERVAL_S)
    except TimeoutError:
        yield _emit_error(f"任务 {job_id} 超时 ({timeout}s)")
        yield _emit_done(FinishReason.ERROR)
        return
    except Exception as e:
        yield _emit_error(str(e))
        yield _emit_done(FinishReason.ERROR)
        return

    if (job.get("Status") or "") == STATUS_FAILED:
        error_message = job.get("ErrorMessage") or "Video generation failed"
        yield _emit_error(error_message)
        yield _emit_done(FinishReason.ERROR)
        return

    medias = parse_output_medias(job.get("Output"))
    for i, media in enumerate(medias):
        url = media.get("OutputUrl", "")
        call_id = f"{response_id}-{i}" if i > 0 else response_id
        delta_content = f"\n🎬 视频 {i + 1}: {url}\n" if url else "\n🎬 视频生成完成\n"
        yield StreamChunk(
            event_type=StreamEventType.CONTENT_DELTA,
            id=call_id,
            model=model,
            delta_content=delta_content,
            tool_calls=[{
                "id": call_id,
                "type": "video_generation_call",
                "status": "completed",
                "result": url,
            }],
        )

    duration = job.get("Duration") or ""
    try:
        dur = float(str(duration).rstrip("sS")) if duration else 0.0
    except (ValueError, TypeError):
        dur = 0.0
    credit = await _fetch_job_credit(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        job_id=job_id,
        region=region,
        endpoint=endpoint,
        security_token=security_token,
        version=api_version,
    )
    usage = UsageInfo(
        prompt_tokens=0,
        completion_tokens=int(dur) if dur > 0 else 1,
        total_tokens=int(dur) if dur > 0 else 1,
        extra=_build_video_usage_extra(job, metadata, model, credit=credit),
    )
    yield _emit_done(FinishReason.STOP, usage)
