"""
Vertex AI Veo 视频生成模块 (Vertex AI Veo Video Generation)

通过 Vertex AI 的 predictLongRunning 端点异步生成视频。
与 Gemini API 的 Veo 实现不同，Vertex AI 使用 OAuth2 Bearer token 认证，
并通过 fetchPredictOperation 端点轮询任务状态。

支持的模型:
  veo-3.1-generate-preview      → 高质量视频生成
  veo-3.1-fast-generate-preview → 快速视频生成
  veo-3.1-lite-generate-preview → 轻量级视频生成

流程:
  1. 创建任务: POST {base_url}/publishers/google/models/{model}:predictLongRunning
  2. 轮询结果: POST {base_url}/publishers/google/models/{model}:fetchPredictOperation
     直到 done == true

认证方式: OAuth2 Bearer token (Google Cloud IAM)

API 文档: https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/veo
"""
from __future__ import annotations

import base64 as _base64
import json
import re as _re
import sys
import time
from typing import Any, Dict, Generator, List, Optional, Tuple

import httpx as _httpx

from app.abstraction.chat import (
    ChatChoice,
    ChatRequest,
    ChatResponse,
    FinishReason,
    UsageInfo,
)
from app.abstraction.messages import Message, MessageRole
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.providers.gemini.video_generation import (
    is_veo_video_model,
    _build_veo_request,
    stream_veo_video_generation,
)
from app.utils import gen_id


# =============================================================================
# 模型检测
# =============================================================================

def is_vertexai_video_model(model: str) -> bool:
    """
    Check if the model is a Veo video generation model.

    Delegates to the shared Gemini Veo model detection logic.

    Args:
        model: Model name

    Returns:
        True if the model is a Veo video generation model
    """
    return is_veo_video_model(model)


def has_vertexai_video_generation_tool(request: ChatRequest) -> bool:
    """
    Check if the request carries a video_generation tool flag.

    Args:
        request: The chat request to check

    Returns:
        True if the request has the _video_generation metadata flag
    """
    return bool(request.metadata.get("_video_generation"))


# =============================================================================
# URL 构建辅助
# =============================================================================

_GLOBAL_HOST_RE = _re.compile(r"^https://aiplatform\.googleapis\.com")
_REGIONAL_HOST_RE = _re.compile(
    r"^https://(?P<region>[^.]+)-aiplatform\.googleapis\.com"
    r"(?:/v\d+)?/projects/(?P<project>[^/]+)/locations/[^/]+"
)


def _resolve_veo_base_url(base_url: str, project_id: Optional[str]) -> str:
    """
    Resolve the Vertex AI Veo base URL from the provider's base_url.

    Veo only supports regional endpoints. If base_url is the global endpoint,
    extract project_id and fall back to us-central1.

    Args:
        base_url: Provider base URL
        project_id: Project ID from credentials (fallback)

    Returns:
        Regional Vertex AI base URL for Veo operations
    """
    base_url = base_url.rstrip('/')

    if _GLOBAL_HOST_RE.match(base_url):
        # Global endpoint — no region info available, default to us-central1
        pid = project_id or ""
        veo_region = "us-central1"
        return (
            f"https://{veo_region}-aiplatform.googleapis.com/v1"
            f"/projects/{pid}/locations/{veo_region}"
        )

    # Regional endpoint — extract region and project_id from the URL
    m = _REGIONAL_HOST_RE.match(base_url)
    if m:
        veo_region = m.group("region")
        pid = m.group("project")
    else:
        # Fallback: use defaults if pattern doesn't match
        veo_region = "us-central1"
        pid = project_id or ""

    return (
        f"https://{veo_region}-aiplatform.googleapis.com/v1"
        f"/projects/{pid}/locations/{veo_region}"
    )


# =============================================================================
# 主入口: 执行视频生成
# =============================================================================

def execute_vertexai_veo_generation(
    request: ChatRequest,
    get_headers_fn,
    base_url: str,
    project_id: Optional[str],
    provider_type: str = "vertexai",
    tracer: Any = None,
) -> ChatResponse:
    """
    Execute Veo video generation via Vertex AI predictLongRunning endpoint.

    Flow:
      1. POST {base_url}/publishers/google/models/{model}:predictLongRunning
         Returns: {"name": "projects/.../publishers/google/models/.../operations/OPERATION_ID"}

      2. Poll via POST {base_url}/publishers/google/models/{model}:fetchPredictOperation
         Body: {"operationName": "<full operation name>"}
         Returns: {"done": true, "response": {"videos": [{"gcsUri": "gs://...", "mimeType": "video/mp4"}]}}
         OR (when no outputStorageUri is set):
         Returns: {"done": true, "response": {"videos": [{"bytesBase64Encoded": "...", "mimeType": "video/mp4"}]}}

    Authentication: OAuth2 Bearer token (same as other Vertex AI calls).
    Videos are downloaded from GCS (using Bearer token) or decoded from base64,
    then saved to the configured storage backend.

    Args:
        request: ChatRequest with video generation parameters
        get_headers_fn: Callable that returns auth headers dict
        base_url: Provider base URL
        project_id: GCP project ID
        provider_type: Provider type string (default "vertexai")

    Returns:
        ChatResponse with video generation results

    Raises:
        RuntimeError: API errors, task failure, or timeout
    """
    model = request.model

    # ── Build Veo request body ─────────────────────────────────────────
    request_body = _build_veo_request(request.messages, request.metadata)

    # ── Vertex AI specific: generateAudio parameter ────────────────────
    # Vertex AI Veo supports generateAudio (Gemini API does not).
    # Veo defaults to generating audio (with sound).
    # Only set if explicitly provided by the user.
    generate_audio_raw = request.metadata.get("generate_audio")
    if generate_audio_raw is None:
        generate_audio_raw = request.metadata.get("generateAudio")
    if generate_audio_raw is not None:
        if "parameters" not in request_body:
            request_body["parameters"] = {}
        request_body["parameters"]["generateAudio"] = bool(generate_audio_raw)

    # ── Tracing ────────────────────────────────────────────────────────────
    _child_span = None
    if tracer:
        _child_span = tracer.start_child(model, model=model, provider_type=provider_type, input_data=request_body)
        if _child_span:
            _child_span.log_input(request_body)
    _trace_error: Optional[Exception] = None

    try:
        # ── Create long-running operation ──────────────────────────────────
        # IMPORTANT: call get_headers_fn() BEFORE reading base_url.
        # get_headers_fn() triggers _get_credentials() which sets base_url
        # from the service account project_id when no explicit base_url is configured.
        headers = get_headers_fn()

        veo_base_url = _resolve_veo_base_url(base_url, project_id)
        create_url = f"{veo_base_url}/publishers/google/models/{model}:predictLongRunning"

        payload_str = json.dumps(request_body, ensure_ascii=False)

        _create_span = None
        if _child_span:
            _create_span = _child_span.start_child(model, model=model, provider_type=provider_type, input_data=request_body, obs_type="span")
            if _create_span:
                _create_span.log_input(request_body)
        _create_error: Optional[Exception] = None

        operation_name = ""
        try:
            with _httpx.Client(timeout=60) as client:
                resp = client.post(create_url, content=payload_str, headers=headers)

            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Vertex AI Veo CreateOperation error ({resp.status_code}): {resp.text}"
                )

            op_data = resp.json()
            operation_name = op_data.get("name", "")
            if not operation_name:
                raise RuntimeError(
                    f"Vertex AI Veo CreateOperation returned no operation name: {op_data}"
                )

            if _create_span:
                _create_span.log_output({"operation_name": operation_name})
        except Exception as e:
            _create_error = e
            raise
        finally:
            if _create_span:
                _create_span.end(error=_create_error)

        # ── Poll via fetchPredictOperation ─────────────────────────────────
        fetch_url = f"{veo_base_url}/publishers/google/models/{model}:fetchPredictOperation"
        fetch_body = {"operationName": operation_name}

        # Collected video info
        raw_videos: List[Dict[str, str]] = []
        poll_timeout = request.metadata.get('timeout')
        max_wait = poll_timeout or 600  # 10 min
        deadline = time.time() + max_wait

        _poll_span = None
        if _child_span:
            _poll_span = _child_span.start_child(operation_name, model=operation_name, provider_type=provider_type, obs_type="span")
        _poll_error: Optional[Exception] = None

        try:
            with _httpx.Client(timeout=60) as client:
                poll_count = 0
                while time.time() < deadline:
                    poll_headers = get_headers_fn()
                    poll_resp = client.post(
                        fetch_url,
                        json=fetch_body,
                        headers=poll_headers,
                    )
                    if poll_resp.status_code >= 400:
                        raise RuntimeError(
                            f"Vertex AI Veo fetchPredictOperation error "
                            f"({poll_resp.status_code}): {poll_resp.text}"
                        )
                    poll_data = poll_resp.json()
                    is_done = poll_data.get("done", False)
                    poll_count += 1

                    if _poll_span:
                        _poll_span.log_output({
                            "operation_name": operation_name,
                            "done": is_done,
                            "poll_count": poll_count,
                        })

                    if is_done:
                        error = poll_data.get("error")
                        if error:
                            raise RuntimeError(
                                f"Vertex AI Veo operation failed: "
                                f"{json.dumps(error, ensure_ascii=False)}"
                            )
                        response_data = poll_data.get("response", {})
                        for video_entry in response_data.get("videos", []):
                            raw_videos.append({
                                "gcsUri": video_entry.get("gcsUri", ""),
                                "bytesBase64Encoded": video_entry.get("bytesBase64Encoded", ""),
                                "mimeType": video_entry.get("mimeType", "video/mp4"),
                            })
                        break

                    time.sleep(5.0)

                # Timeout error
                if not raw_videos:
                    raise TimeoutError(
                        f"Vertex AI Veo operation {operation_name} timed out after {max_wait}s"
                    )
        except Exception as e:
            _poll_error = e
            raise
        finally:
            if _poll_span:
                _poll_span.end(error=_poll_error)

        if _child_span:
            _child_span.log_output({"operation_name": operation_name, "video_count": len(raw_videos), "status": "succeeded"})
    except Exception as e:
        _trace_error = e
        raise
    finally:
        if _child_span:
            _child_span.end(error=_trace_error)

    if not raw_videos:
        raise RuntimeError(
            f"Vertex AI Veo operation completed but no videos found in response"
        )

    # ── Download / decode videos and save to storage ───────────────────
    stored_urls = _download_and_store_videos(
        raw_videos, operation_name, get_headers_fn
    )

    video_items = [
        {
            "type": "video_generation_call",
            "status": "completed",
            "result": url,
            "file_type": "mp4",
        }
        for url in stored_urls
    ]
    video_message = Message(
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
    video_resolution = request.metadata.get("resolution", "") or "720p"
    # Determine audio flag: Veo generates audio by default (True),
    # only False when user explicitly sets generate_audio=false / generateAudio=false
    video_has_audio = parameters.get("generateAudio", True)

    return ChatResponse(
        id=gen_id("vid"),
        model=model,
        choices=[ChatChoice(
            index=0,
            message=video_message,
            finish_reason=FinishReason.STOP,
        )],
        usage=UsageInfo(
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            extra={
                'output_video_number': len(stored_urls) if stored_urls else 1,
                'output_video_resolution': video_resolution,
                'output_video_aspect': video_aspect_ratio,
                'output_video_seconds': float(video_seconds),
                'output_video_audio': bool(video_has_audio),
            },
        ),
        created=int(time.time()),
        provider=provider_type,
    )


# =============================================================================
# 视频下载与存储
# =============================================================================

def _download_and_store_videos(
    raw_videos: List[Dict[str, str]],
    operation_name: str,
    get_headers_fn,
) -> List[str]:
    """
    Download or decode videos from Vertex AI response and save to storage.

    Handles two formats:
    - GCS URI: downloads using Bearer token
    - Base64 encoded: decodes inline data

    Args:
        raw_videos: List of video info dicts with gcsUri/bytesBase64Encoded/mimeType
        operation_name: Operation name (used for generating filenames)
        get_headers_fn: Callable that returns auth headers dict

    Returns:
        List of stored video URLs
    """
    from app.storage.factory import get_storage_backend
    storage = get_storage_backend()
    stored_urls: List[str] = []

    for idx, video_info in enumerate(raw_videos):
        safe_op = operation_name.replace("/", "_").replace(":", "_")
        video_id = f"{safe_op}_{idx}" if idx > 0 else safe_op
        if len(video_id) > 80:
            video_id = video_id[-80:]

        mime_type = video_info.get("mimeType", "video/mp4")
        ext = "webm" if "webm" in mime_type else "mp4"
        filename = f"{video_id}.{ext}"

        try:
            gcs_uri = video_info.get("gcsUri", "")
            b64_data = video_info.get("bytesBase64Encoded", "")

            if b64_data:
                # Video bytes returned inline as base64
                video_bytes = _base64.b64decode(b64_data)
            elif gcs_uri:
                # Video stored in GCS — download using Bearer token
                if gcs_uri.startswith("gs://"):
                    gcs_path = gcs_uri[5:]
                    download_url = f"https://storage.googleapis.com/{gcs_path}"
                else:
                    download_url = gcs_uri

                dl_headers = get_headers_fn()
                with _httpx.Client(timeout=300, follow_redirects=True) as dl_client:
                    dl_resp = dl_client.get(download_url, headers=dl_headers)

                if dl_resp.status_code >= 400:
                    raise RuntimeError(
                        f"Video download error ({dl_resp.status_code}): "
                        f"{dl_resp.text[:200]}"
                    )
                video_bytes = dl_resp.content
            else:
                raise RuntimeError(
                    f"Video entry has neither gcsUri nor bytesBase64Encoded: {video_info}"
                )

            stored_url = storage.write_binary(filename, video_bytes, mime_type)
            stored_urls.append(stored_url)
        except Exception as exc:
            # Fall back to GCS URI if download/decode fails
            fallback = video_info.get("gcsUri", "")
            stored_urls.append(fallback if fallback else f"error:{exc}")

    return stored_urls


# =============================================================================
# 流式视频生成
# =============================================================================

def stream_vertexai_veo_generation(
    chat_fn,
    request: ChatRequest,
) -> Generator[StreamChunk, None, None]:
    """
    Stream Veo video generation results on Vertex AI.

    Veo video generation is an async long-running operation.
    This delegates to the shared Gemini stream_veo_video_generation function
    which calls the non-streaming API and emits results as SSE events.

    Args:
        chat_fn: The non-streaming chat function to call (provider.chat)
        request: The chat request with video generation parameters
    """
    yield from stream_veo_video_generation(chat_fn, request)
