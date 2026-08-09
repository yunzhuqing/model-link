"""
阿里云百炼图像生成模块 (Qwen Image Generation & Z-Image & Vidu)

通义千问图像生成/编辑模型、Z-Image 模型以及 Vidu 图像生成模型支持通过
Dashscope 图像生成 API 进行图像生成和编辑。

支持的模型包括：
- qwen-image-2.0-pro: 通义千问图像生成与编辑模型（支持文生图和图生图）
- z-image-turbo: 快速文生图模型（仅支持文本输入，支持 aspect_ratio 尺寸参数）
- vidu/vidu-image_reference2image: Vidu Image 图生图模型
- vidu/viduq3-fast_reference2image / vidu/viduq2-pro_reference2image /
  vidu/viduq2-fast_reference2image: Vidu Q 系列图生图模型

API 文档:
https://help.aliyun.com/document_detail/2712195.html

请求格式（多模态生成，qwen-image / z-image）：
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
{
    "model": "qwen-image-2.0-pro",
    "input": {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"image": "https://..."},
                    {"text": "编辑指令"}
                ]
            }
        ]
    },
    "parameters": {
        "n": 1,
        "watermark": false,
        "size": "1024*1024"
    }
}

请求格式（图像生成，Vidu 系列）：
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation
{
    "model": "vidu/vidu-image_reference2image",
    "input": {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"text": "..."},
                    {"image": "https://..."}
                ]
            }
        ]
    },
    "parameters": {
        "size": "1024*1024"
    }
}

响应格式（成功）：
{
    "output": {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": [{"image": "https://result-url.png"}],
                    "role": "assistant"
                }
            }
        ]
    },
    "usage": {"height": 1024, "image_count": 1, "width": 1024},
    "request_id": "..."
}

响应格式（失败）：
{
    "request_id": "...",
    "code": "InvalidApiKey",
    "message": "Invalid API-key provided."
}
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, AsyncGenerator
import asyncio
import json
import time
import base64
import logging
from urllib.request import urlopen

import httpx

from app.http_client import shared_client

from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.providers.image_size_utils import (
    BAILIAN_VIDU_IMAGE_SIZE_MAP,
    Z_IMAGE_SIZE_MAP,
    resolve_pixel_size,
)
from app.utils import gen_id, json_loads


logger = logging.getLogger("model_link.bailian")


# =============================================================================
# 异步任务 API 配置
# =============================================================================

# Dashscope 任务查询 API 路径
TASK_QUERY_PATH = "/api/v1/tasks"

# 任务状态常量
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

# 轮询配置
_POLL_INTERVAL_S = 5.0   # 每次轮询间隔（秒）
_POLL_MAX_WAIT_S = 600   # 最大等待时间（秒）


# =============================================================================
# 图像生成模型配置
# =============================================================================

@dataclass
class QwenImageConfig:
    """Qwen 图像生成模型配置"""
    model_name: str      # 模型名称
    display_name: str    # 显示名称
    description: str     # 模型描述


# Qwen 图像生成模型列表
QWEN_IMAGE_MODELS: List[QwenImageConfig] = [
    QwenImageConfig(
        model_name="qwen-image-2.0-pro",
        display_name="Qwen Image 2.0 Pro",
        description="通义千问图像生成与编辑模型，支持文生图和图生图编辑",
    ),
    QwenImageConfig(
        model_name="qwen-image-2.0",
        display_name="Qwen Image 2.0",
        description="通义千问图像生成模型，支持文生图和图生图编辑",
    ),
    QwenImageConfig(
        model_name="z-image-turbo",
        display_name="Z-Image Turbo",
        description="快速文生图模型，仅支持文本输入，使用 aspect_ratio 尺寸参数",
    ),
]

# Dashscope 多模态生成 API 端点
QWEN_IMAGE_API_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
    "multimodal-generation/generation"
)

# Dashscope 图像生成 API 路径（Vidu 图像生成模型专用）
BAILIAN_IMAGE_GENERATION_PATH = "/api/v1/services/aigc/image-generation/generation"

# Dashscope 图像生成 API 端点（Vidu 图像生成模型专用）
BAILIAN_IMAGE_GENERATION_API_URL = (
    "https://dashscope.aliyuncs.com" + BAILIAN_IMAGE_GENERATION_PATH
)

# 百炼托管的 Vidu 图像生成模型列表
BAILIAN_VIDU_IMAGE_MODELS: List[str] = [
    "vidu/vidu-image_reference2image",
    "vidu/viduq3-fast_reference2image",
    "vidu/viduq2-pro_reference2image",
    "vidu/viduq2-fast_reference2image",
]


# =============================================================================
# 图像生成模型检测
# =============================================================================

def is_qwen_image_model(model: str) -> bool:
    """
    Check if the model is a Bailian image generation model.

    Matches model names containing 'qwen-image', 'qwen_image' (case-insensitive),
    or exactly 'z-image-turbo' (Z-Image Turbo model).

    Args:
        model: Model name

    Returns:
        True if the model supports Bailian image generation
    """
    model_lower = model.lower()
    return any(kw in model_lower for kw in ('qwen-image', 'qwen_image')) or model_lower == 'z-image-turbo'


def is_bailian_vidu_image_model(model: str) -> bool:
    """
    Check if the model is a Bailian-hosted Vidu image generation model.

    Matches the exact Dashscope model names served through the
    image-generation/generation API, e.g.:
      - vidu/vidu-image_reference2image
      - vidu/viduq3-fast_reference2image
      - vidu/viduq2-pro_reference2image
      - vidu/viduq2-fast_reference2image

    Args:
        model: Model name (case-insensitive)

    Returns:
        True if the model is a Bailian Vidu image generation model
    """
    return model.lower() in BAILIAN_VIDU_IMAGE_MODELS


def is_z_image_model(model: str) -> bool:
    """Check if the model is a Z-Image Turbo model."""
    return model.lower() == 'z-image-turbo'


def _resolve_bailian_vidu_size(model: str, metadata: dict) -> str:
    """
    Resolve and validate the Dashscope ``size`` parameter for a Vidu model.

    阿里云百炼托管的 Vidu 图像生成模型仅支持固定尺寸集合
    （见 ``BAILIAN_VIDU_IMAGE_SIZE_MAP``，按模型分 1K/2K/4K 档），
    且上游要求 ``W*H`` 格式。用户侧通常以 ``WxH`` 传入（大小写不敏感），
    这里统一归一化为 ``W*H`` 并校验是否在该模型支持的尺寸集合内。

    Args:
        model: Bailian Vidu model name
        metadata: Request metadata (size / resolution / aspect_ratio)

    Returns:
        Dashscope-format size string (e.g. "1024*1024")

    Raises:
        ValueError: 请求的尺寸不在该模型支持的固定尺寸集合内
    """
    table = BAILIAN_VIDU_IMAGE_SIZE_MAP.get(model.lower())
    if not table:
        return "1024*1024"

    supported = ", ".join(sorted(wh.replace("x", "*") for wh in table))

    size = str(metadata.get('size', '') or '').strip()
    resolution = str(metadata.get('resolution', '') or '').strip()
    aspect_ratio = str(metadata.get('aspect_ratio', '') or '').strip()

    # 用户直接传像素尺寸 (WxH / W*H) → 归一化并精确校验
    if size:
        key = size.lower().replace(" ", "").replace("*", "x")
        if key in table:
            return key.replace("x", "*")
        raise ValueError(
            f"Bailian Vidu model '{model}' does not support size '{size}'. "
            f"Supported sizes: {supported}"
        )

    # 无 size：通过 resolution / aspect_ratio 解析（tier 标签如 1K/2K/4K）
    resolved = resolve_pixel_size(
        size="",
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        sep="*",
        table=table,
    )
    if resolved:
        return resolved

    if not resolution and not aspect_ratio:
        return "1024*1024"

    raise ValueError(
        f"Bailian Vidu model '{model}' could not resolve size "
        f"(resolution={resolution!r}, aspect_ratio={aspect_ratio!r}). "
        f"Supported sizes: {supported}"
    )


def _resolve_bailian_image_api_url(domain: Optional[str] = None) -> str:
    """
    Resolve the Dashscope image-generation API URL.

    Uses the provider's Dashscope domain (for custom domains) or falls back
    to the default dashscope.aliyuncs.com host.

    Args:
        domain: Dashscope domain, e.g. "https://dashscope.aliyuncs.com"

    Returns:
        Full image-generation API URL
    """
    base = (domain or "https://dashscope.aliyuncs.com").rstrip("/")
    return base + BAILIAN_IMAGE_GENERATION_PATH


def _resolve_task_query_url(domain: Optional[str] = None) -> str:
    """
    Resolve the Dashscope task query API base URL.

    Args:
        domain: Dashscope domain, e.g. "https://dashscope.aliyuncs.com"

    Returns:
        Task query API base URL (e.g. "https://dashscope.aliyuncs.com/api/v1/tasks")
    """
    base = (domain or "https://dashscope.aliyuncs.com").rstrip("/")
    return base + TASK_QUERY_PATH


async def check_bailian_image_task_status(
    api_key: str,
    task_id: str,
    domain: Optional[str] = None,
) -> Dict[str, Any]:
    """
    单次查询百炼 Vidu 图片生成任务状态。

    Args:
        api_key: Dashscope API Key
        task_id: 任务 ID
        domain:  可选的 Dashscope 域名覆盖

    Returns:
        完整的 API 响应 JSON dict，包含 output.task_status 等字段；
        网络/HTTP 错误时返回 {"output": {"task_status": "UNKNOWN"}}
    """
    task_query_url = _resolve_task_query_url(domain)
    url = f"{task_query_url}/{task_id}"
    try:
        async with shared_client() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if response.status_code >= 400:
                logger.warning(
                    "Task query error (status=%s): %s",
                    response.status_code,
                    response.text,
                )
                return {"output": {"task_status": TASK_STATUS_UNKNOWN}}
            return response.json()
    except httpx.RequestError as e:
        logger.warning("Task query network error: %s", e)
        return {"output": {"task_status": TASK_STATUS_UNKNOWN}}


async def _poll_bailian_image_task(
    api_key: str,
    task_id: str,
    domain: Optional[str] = None,
    timeout: int = _POLL_MAX_WAIT_S,
    poll_interval: float = _POLL_INTERVAL_S,
    tracer: Any = None,
) -> Dict[str, Any]:
    """
    轮询 Dashscope 任务 API 直到图片任务进入终态或超时。

    Args:
        api_key: Dashscope API Key
        task_id: 任务 ID
        domain:  可选的 Dashscope 域名覆盖
        timeout: 最大等待时间（秒）
        poll_interval: 轮询间隔（秒）
        tracer: 可选 tracer（记录每次轮询状态）

    Returns:
        终态任务响应 dict（含 output.choices 等）

    Raises:
        TimeoutError: 超过 timeout 任务仍未结束
    """
    _span = None
    if tracer:
        _span = tracer.start_child(
            task_id,
            model=task_id,
            provider_type="bailian",
            obs_type="span",
        )
    _error: Optional[Exception] = None

    start_time = time.time()
    try:
        poll_count = 0
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TimeoutError(
                    f"Image generation task {task_id} timed out after {timeout}s"
                )

            result = await check_bailian_image_task_status(api_key, task_id, domain)
            output = result.get("output", {})
            task_status = output.get("task_status", TASK_STATUS_UNKNOWN)
            poll_count += 1

            if _span:
                _span.log_output({
                    "task_id": task_id,
                    "task_status": task_status,
                    "elapsed": elapsed,
                    "poll_count": poll_count,
                })

            if task_status in TASK_TERMINAL_STATUSES:
                return result

            logger.debug(
                "Task %s status: %s, elapsed: %.1fs",
                task_id,
                task_status,
                elapsed,
            )
            await asyncio.sleep(poll_interval)
    except Exception as e:
        _error = e
        raise
    finally:
        if _span:
            _span.end(error=_error)


def _resolve_z_image_size(metadata: dict) -> Optional[str]:
    """
    Resolve the Dashscope size parameter for z-image-turbo from request metadata.

    Uses the dedicated Z-Image size table (Z_IMAGE_SIZE_MAP) via
    resolve_pixel_size(), because Z-Image's size set (two 1K groups plus a
    2K group) differs from the shared GPT Image 2 (Vidu) table.

    Args:
        metadata: Request metadata dict

    Returns:
        Dashscope-format size string (WxH with * separator), or default "1024*1024".
    """
    size = str(metadata.get('size', '') or '').strip()
    resolution = str(metadata.get('resolution', '') or '').strip()
    aspect_ratio = str(metadata.get('aspect_ratio', '') or '').strip()

    # If resolution is set but size is not, treat resolution as the size/tier
    if resolution and not size:
        size = resolution

    resolved = resolve_pixel_size(
        size=size,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        sep="*",
        table=Z_IMAGE_SIZE_MAP,
    )
    return resolved or "1024*1024"


def has_image_generation_tool(request: ChatRequest) -> bool:
    """Check if the request contains an ``image_generation`` tool."""
    from app.abstraction.tools import has_image_generation_tool as _check
    return _check(request.tools)


# =============================================================================
# 消息转换 - ChatRequest → Dashscope 格式
# =============================================================================

def _convert_messages_to_dashscope(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Convert ChatRequest messages to Dashscope multimodal generation format.

    Each message content block is converted:
    - TEXT          → {"text": "..."}
    - IMAGE_URL     → {"image": "https://..."}
    - IMAGE_BASE64  → {"image": "data:<mime>;base64,<data>"}

    System messages are skipped (handled separately via BailianProvider).

    Args:
        messages: List of Message objects

    Returns:
        Dashscope format messages list
    """
    dashscope_messages = []

    for msg in messages:
        if msg.role.is_system_like():
            continue  # System messages are handled separately

        content_list: List[Dict[str, Any]] = []

        if isinstance(msg.content, str):
            if msg.content.strip():
                content_list.append({"text": msg.content})
        elif isinstance(msg.content, list):
            for block in msg.content:
                if not isinstance(block, ContentBlock):
                    continue
                if block.type == ContentType.TEXT:
                    text = block.text or ""
                    if text:
                        content_list.append({"text": text})
                elif block.type == ContentType.IMAGE_URL:
                    if block.url:
                        content_list.append({"image": block.url})
                elif block.type == ContentType.IMAGE_BASE64:
                    if block.data:
                        mime = block.media_type or "image/jpeg"
                        data_uri = f"data:{mime};base64,{block.data}"
                        content_list.append({"image": data_uri})

        if content_list:
            dashscope_messages.append({
                "role": msg.role.value if hasattr(msg.role, 'value') else str(msg.role),
                "content": content_list,
            })

    return dashscope_messages


# =============================================================================
# API 调用与响应解析
# =============================================================================

async def _download_image_as_b64(url: str, fallback_mime: str = "image/png") -> Optional[str]:
    """Download an image URL and return it as a base64 data URI.

    Returns ``None`` if the download fails, so the caller can fall back
    to the raw URL.
    """
    try:
        with urlopen(url, timeout=30) as resp:  # noqa: S310 – URL is provider-generated
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()
            mime = content_type.split(";")[0].strip() or fallback_mime
            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{b64}"
    except Exception as exc:
        logging.getLogger("model_link.bailian").warning(
            "Failed to convert image URL to base64: %s – %s", url, exc
        )
        return None


async def execute_qwen_image_generation(
    api_key: str,
    model: str,
    messages: List[Message],
    metadata: dict,
    tracer: Any = None,
    domain: Optional[str] = None,
) -> ChatResponse:
    """
    Execute Qwen / Vidu image generation via the Dashscope API.

    Builds the Dashscope image generation request from the ChatRequest
    messages and metadata, calls the API, and returns the result as a
    ChatResponse with image_generation_call items stored in the message
    content (JSON-encoded list, compatible with the Responses API adapter
    format).

    Routing:
    - qwen-image / z-image models → multimodal-generation/generation API（同步）
    - vidu/vidu-*_reference2image models → image-generation/generation API
      （X-DashScope-Async: enable 异步任务，提交后轮询 /api/v1/tasks/{task_id}）

    Args:
        api_key: Dashscope API key
        model: Model name (e.g. "qwen-image-2.0-pro" or "vidu/vidu-image_reference2image")
        messages: List of Message objects
        metadata: Request metadata (carries image generation parameters)
        domain: Optional Dashscope domain (e.g. "https://dashscope.aliyuncs.com")

    Returns:
        ChatResponse with image_generation_call items in the message content

    Raises:
        RuntimeError: On API error
    """
    import sys

    # Convert messages to Dashscope format
    dashscope_messages = _convert_messages_to_dashscope(messages)
    is_vidu = is_bailian_vidu_image_model(model)

    # Build parameters from metadata
    parameters: Dict[str, Any] = {}

    if is_vidu:
        # Vidu 图像生成 API 仅支持 size 参数（图生图），且只支持固定尺寸
        parameters['size'] = _resolve_bailian_vidu_size(model, metadata)
    elif is_z_image_model(model):
        # Z-Image Turbo uses aspect_ratio + tier to resolve exact pixel size
        resolved_size = _resolve_z_image_size(metadata)
        if resolved_size:
            parameters['size'] = resolved_size
    else:
        # Qwen Image：size 直接透传（同时接受 "1024x1024" 与 "1024*1024"）
        size = metadata.get('size')
        if size:
            parameters['size'] = str(size).replace('x', '*')

    if not is_vidu:
        n = metadata.get('number') or metadata.get('n')
        if n is not None:
            parameters['n'] = int(n)
        else:
            parameters['n'] = 1

        watermark = metadata.get('watermark')
        if watermark is not None:
            parameters['watermark'] = bool(watermark)
        else:
            parameters['watermark'] = False

        seed = metadata.get('seed')
        if seed is not None:
            parameters['seed'] = seed

    # Build request body
    request_body: Dict[str, Any] = {
        "model": model,
        "input": {
            "messages": dashscope_messages,
        },
        "parameters": parameters,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    _child_span = None
    if tracer:
        _child_span = tracer.start_child(
            model,
            model=model,
            provider_type="bailian",
            obs_type="generation",
            input_data=request_body,
        )
        if _child_span:
            _child_span.log_input(request_body)
    _trace_error: Optional[Exception] = None

    try:
        http_timeout = int(metadata.get("timeout", _POLL_MAX_WAIT_S) or _POLL_MAX_WAIT_S)
        api_url = (
            _resolve_bailian_image_api_url(domain)
            if is_vidu
            else QWEN_IMAGE_API_URL
        )

        request_headers = dict(headers)
        if is_vidu:
            # 阿里云百炼 Vidu 图片生成仅支持异步任务，需开启 async 模式
            request_headers["X-DashScope-Async"] = "enable"

        async with shared_client() as client:
            response = await client.post(
                api_url,
                json=request_body,
                headers=request_headers,
            )
            response_data = response.json()

        if _child_span:
            _output = dict(response_data)
            _x_req_id = response.headers.get("x-request-id", "")
            if _x_req_id:
                _output["x-request-id"] = _x_req_id
            _child_span.log_output(_output)

        # Dashscope signals errors via top-level 'code' field (not HTTP status code alone)
        if 'code' in response_data and response_data['code'] not in ('Success', ''):
            code = response_data.get('code', '')
            message = response_data.get('message', 'Unknown error')
            raise RuntimeError(
                f"Bailian Image API error (code={code}): {message}"
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Bailian Image API error ({response.status_code}): "
                f"{json.dumps(response_data, ensure_ascii=False)}"
            )

        if is_vidu:
            return await _execute_bailian_vidu_async(
                api_key=api_key,
                model=model,
                metadata=metadata,
                domain=domain,
                response_data=response_data,
                poll_timeout=http_timeout,
                tracer=tracer,
            )

        return _parse_qwen_image_response(response_data, model, metadata,
                                       request_id=response_data.get('request_id')
                                                 or response.headers.get('x-request-id', ''))

    except RuntimeError:
        _trace_error = sys.exc_info()[1]
        raise
    except Exception as e:
        _trace_error = e
        raise RuntimeError(f"Bailian Image API error: {str(e)}")
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)


async def _execute_bailian_vidu_async(
    api_key: str,
    model: str,
    metadata: dict,
    domain: Optional[str],
    response_data: Dict[str, Any],
    poll_timeout: int,
    tracer: Any = None,
) -> ChatResponse:
    """
    处理百炼 Vidu 图片生成的异步任务流程。

    提交响应只包含 ``task_id`` 与 ``task_status``；随后轮询
    ``GET /api/v1/tasks/{task_id}`` 直到终态，再解析最终输出中的图片结果。

    Args:
        api_key: Dashscope API Key
        model: Vidu 模型名
        metadata: 请求元数据（携带 _on_task_created hook 等）
        domain: 可选的 Dashscope 域名覆盖
        response_data: 提交任务的响应 JSON
        poll_timeout: 轮询最大等待时间（秒）
        tracer: 可选 tracer（用于记录轮询明细）

    Returns:
        ChatResponse with image_generation_call items

    Raises:
        RuntimeError: 任务失败 / 取消 / 超时 / 响应缺少 task_id
    """
    output = response_data.get("output", {})
    task_id = output.get("task_id")
    if not task_id:
        raise RuntimeError(
            f"No task_id in image generation response: "
            f"{json.dumps(response_data, ensure_ascii=False)}"
        )

    task_status = output.get("task_status", TASK_STATUS_UNKNOWN)

    # 通知后台响应记录任务 ID（用于 usage resync）
    hook = metadata.get('_on_task_created')
    if hook:
        hook(task_id)

    # 任务已同步完成（罕见但可能）
    if task_status == TASK_STATUS_SUCCEEDED:
        return _parse_qwen_image_response(
            response_data, model, metadata,
            request_id=response_data.get('request_id', ''),
        )

    if task_status in (TASK_STATUS_FAILED, TASK_STATUS_CANCELED):
        code = output.get("code", "UnknownError")
        message = output.get("message", "Image generation failed")
        raise RuntimeError(
            f"Image generation task {task_id} failed: [{code}] {message}"
        )

    # 轮询直到终态
    try:
        final_result = await _poll_bailian_image_task(
            api_key=api_key,
            task_id=task_id,
            domain=domain,
            timeout=poll_timeout,
            tracer=tracer,
        )
    except TimeoutError:
        raise RuntimeError(
            f"Image generation task {task_id} timed out after {poll_timeout}s"
        )

    final_output = final_result.get("output", {})
    final_status = final_output.get("task_status", TASK_STATUS_UNKNOWN)

    if final_status == TASK_STATUS_SUCCEEDED:
        return _parse_qwen_image_response(
            final_result, model, metadata,
            request_id=final_result.get('request_id', ''),
        )

    if final_status in (TASK_STATUS_FAILED, TASK_STATUS_CANCELED):
        code = final_output.get("code", "UnknownError")
        message = final_output.get("message", "Image generation failed")
        raise RuntimeError(
            f"Image generation task {task_id} failed: [{code}] {message}"
        )

    raise RuntimeError(
        f"Image generation task {task_id} ended with status={final_status}"
    )


def _resolution_tier(width: int, height: int) -> str:
    """
    Derive a resolution tier label from pixel dimensions.

    Tier labels follow the convention used across image generation providers
    (TencentVOD, Gemini, etc.):

        max dimension ≤  640  →  "512"
        max dimension ≤ 1536  →  "1K"
        max dimension ≤ 3072  →  "2K"
        otherwise             →  "4K"

    Args:
        width:  Image width in pixels
        height: Image height in pixels

    Returns:
        Resolution tier label, e.g. "1K", "2K", "4K"
    """
    max_dim = max(width, height)
    if max_dim <= 640:
        return "512"
    elif max_dim <= 1536:
        return "1K"
    elif max_dim <= 3072:
        return "2K"
    else:
        return "4K"


def _parse_qwen_image_response(data: Dict[str, Any], model: str, metadata: Optional[dict] = None, request_id: str = "") -> ChatResponse:
    """
    Parse Dashscope multimodal generation response into ChatResponse.

    Extracts image URLs from the response and packs them as
    image_generation_call items (JSON-encoded) in the message content,
    compatible with the Volcengine / Gemini provider format.

    Args:
        data: Dashscope API response data
        model: Model name
        metadata: Request metadata (carries response_format for b64_json signal)

    Returns:
        ChatResponse with image_generation_call items
    """
    output = data.get("output", {})
    choices = output.get("choices", [])

    image_call_items: List[Dict[str, Any]] = []
    for choice in choices:
        msg = choice.get("message", {})
        for item in msg.get("content", []):
            if "image" in item:
                image_call_items.append({
                    "type": "image_generation_call",
                    "status": "completed",
                    "result": item["image"],
                })

    usage_data = data.get("usage", {})
    image_count = usage_data.get("image_count", max(len(image_call_items), 1))

    # 同步响应：从 width/height 推导 resolution tier 与 aspect ratio
    img_width = usage_data.get("width", 0)
    img_height = usage_data.get("height", 0)
    if img_width and img_height:
        img_resolution = _resolution_tier(img_width, img_height)
        from math import gcd
        g = gcd(img_width, img_height)
        img_aspect = f"{img_width // g}:{img_height // g}"
    else:
        # 异步任务响应无 width/height：使用 SR（如 "2K"）与 size（如 "2048*2048"）
        img_resolution = None
        img_aspect = None
        sr = usage_data.get("SR") or usage_data.get("resolution")
        if sr:
            img_resolution = str(sr)
        size_str = usage_data.get("size", "")
        if size_str:
            parts = str(size_str).lower().replace("x", "*").split("*")
            if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                w, h = int(parts[0]), int(parts[1])
                if w and h:
                    from math import gcd
                    g = gcd(w, h)
                    img_aspect = f"{w // g}:{h // g}"

    message = Message(
        role=MessageRole.ASSISTANT,
        content=json.dumps(image_call_items, ensure_ascii=False),
    )

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
                'output_image_resolution': img_resolution,
                'output_image_aspect': img_aspect,
                '_response_format': (metadata or {}).get('response_format', 'url'),
                '_task_id': request_id,
            },
        ),
        created=int(time.time()),
        provider="bailian",
    )


# =============================================================================
# 流式响应生成
# =============================================================================

async def stream_image_generation(
    chat_fn,
    request: ChatRequest,
) -> AsyncGenerator[StreamChunk, None]:
    """
    Execute Qwen image generation and yield the result as StreamChunks.

    Qwen image generation is synchronous (no true streaming); this function
    calls the non-streaming API, collects all images, then emits them as
    image_generation_call SSE events via raw_sse_passthrough.

    SSE event sequence (matching the Volcengine / Gemini pattern):
    1. Role marker chunk (delta_role="assistant") → triggers format_stream_start
    2. response.output_item.added  (image_generation_call, status=generating)
    3. response.output_item.done   (image_generation_call, status=completed)
    4. response.completed          (emitted by finish chunk)

    Args:
        chat_fn: The non-streaming chat function (provider.chat)
        request: The chat request with image generation parameters
    """
    # Call the non-streaming API to get the full image result
    response = await chat_fn(request)
    response_id = response.id
    model = response.model

    # Parse the images list from the response content
    images: List[Dict[str, Any]] = []
    if response.choices and response.choices[0].message:
        msg = response.choices[0].message
        raw = (
            msg.content
            if isinstance(msg.content, str)
            else (msg.get_text_content() or "[]")
        )
        try:
            images = json_loads(raw) if isinstance(raw, str) else []
        except (json.JSONDecodeError, TypeError):
            images = []

    # Role marker — triggers format_stream_start in the Responses adapter
    yield StreamChunk(
        id=response_id,
        model=model,
        delta_role="assistant",
        event_type=StreamEventType.CONTENT_DELTA,
    )

    # b64_json conversion for streaming: convert image URLs to base64
    # data URIs before constructing SSE events. This mirrors what
    # _apply_b64_json_to_image_output() does for the non-streaming sync
    # and async GET paths in gateway_responses.py.
    convert_to_b64 = response.usage.extra.get('_response_format') == 'b64_json'
    if convert_to_b64:
        for img in images:
            url = img.get("result", "")
            if url and not url.startswith("data:"):
                b64_data_uri = _download_image_as_b64(url)
                if b64_data_uri:
                    img["result"] = b64_data_uri

    # Emit one image_generation_call item per image via raw SSE passthrough
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

    # Build the completed response with all image_generation_call items
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
