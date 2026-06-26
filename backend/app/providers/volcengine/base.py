"""
火山引擎供应商基础实现 (Volcengine Base Provider)
使用火山引擎 Ark Responses API (/v3/responses)。

火山引擎 Responses API 与 OpenAI Responses API 格式兼容，
支持 reasoning/summary、多模态输入等功能。

API 文档: https://www.volcengine.com/docs/82379/1263482

图像生成支持：
豆包图像生成模型可以通过 Responses API 作为 image_generation 类型的工具进行调用。
"""
from typing import Optional, List, Dict, Any, AsyncGenerator
import json
import time
import uuid
import sys
import base64
import logging
from ..base import BaseProvider, ProviderConfig, ProviderCapability
from .._responses_format import build_responses_request, _tool_result_to_responses_output

# Volcengine Responses API 仅接受白名单内的字段，不允许传入额外字段。
# 参考: https://www.volcengine.com/docs/82379/1263482
_VOLCENGINE_RESPONSES_ALLOWED_KEYS = frozenset({
    "model",
    "input",
    "instructions",
    "previous_response_id",
    "expire_at",
    "max_output_tokens",
    "thinking",
    "reasoning",
    "include",
    "caching",
    "store",
    "stream",
    "temperature",
    "top_p",
    "text",
    "tools",
    "tool_choice",
    "max_tool_calls",
    "context_management",
    "service_tier",
})

from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse
from app.utils import gen_id, json_loads, REASONING_EFFORT_MINIMAL
from .embedding import execute_volcengine_multimodal_embed
from .image_generation import (
    DoubaoImageProvider,
    get_support_output_format,
)
from app.providers.image_size_utils import resolve_image_size
from .video_generation import (
    is_seedance_video_model,
    execute_seedance_video_generation,
    stream_seedance_video_generation,
)
from .threed_generation import (
    is_seed3d_model,
    has_threed_generation_tool,
    execute_seed3d_generation,
    stream_seed3d_generation,
)

# Internal metadata keys that must NOT be forwarded to the upstream API.
_INTERNAL_KEYS = frozenset({'support_thinking', 'support_online_image', 'support_online_video', 'reasoning'})


class VolcengineProvider(BaseProvider):
    """
    火山引擎供应商实现 (Responses API)

    使用 /v3/responses 端点，支持：
    - reasoning with summary
    - 多模态输入 (图片、视频等)
    - 工具调用
    - 流式响应
    """

    PROVIDER_TYPE: str = "volcengine"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
    ]

    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        # Ensure base_url ends with /v3
        if config.base_url and not config.base_url.endswith("/v3") and "/v3/" not in config.base_url:
            config.base_url = config.base_url.rstrip("/") + "/v3"

        super().__init__(config)

    def get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }

    def supports_model(self, model: str) -> bool:
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        return {"description": f"Volcengine model: {model}", "context_size": 128000}

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    # ----------------------------------------------------------------
    # Request preparation
    # ----------------------------------------------------------------

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        Convert ChatRequest into Volcengine Responses API format.

        Builds on the shared ``build_responses_request``, then applies
        Volcengine-specific customizations:
        - input conversion via ``_message_to_input_item`` (partial, empty fallback)
        - reasoning without ``summary`` (Volcengine doesn't support it)
        """
        result = build_responses_request(request)

        # ── Override input: use Volcengine-specific message conversion ──
        input_items = []
        for msg in request.messages:
            if msg.role == MessageRole.DEVELOPER:
                content = msg.get_text_content() or ''
                if content:
                    input_items.append({"role": "developer", "content": content})
                continue
            if msg.role == MessageRole.SYSTEM:
                continue
            item = self._message_to_input_item(msg)
            if item is not None:
                if isinstance(item, list):
                    input_items.extend(item)
                else:
                    input_items.append(item)

        # Partial assistant continuation (Volcengine-specific)
        if input_items and isinstance(input_items[-1], dict) and input_items[-1].get("role") == "assistant":
            last_content = input_items[-1].get("content")
            has_meaningful_content = False
            if isinstance(last_content, str) and last_content.strip():
                has_meaningful_content = True
            elif isinstance(last_content, list):
                for part in last_content:
                    if isinstance(part, dict):
                        text = part.get("text", "")
                        if text and text.strip():
                            has_meaningful_content = True
                            break
                        if part.get("type", "") not in ("input_text", "output_text"):
                            has_meaningful_content = True
                            break
            if has_meaningful_content:
                input_items[-1]["partial"] = True
            else:
                input_items.pop()

        result["input"] = input_items

        # ── Override reasoning: Volcengine does NOT support "summary" ──
        result.pop("reasoning", None)
        reasoning_config = request.metadata.get('reasoning')
        support_thinking = request.metadata.get('support_thinking', False)

        if reasoning_config and isinstance(reasoning_config, dict):
            result["reasoning"] = {"effort": reasoning_config.get("effort", "medium")}
        elif support_thinking:
            effort = request.reasoning_effort
            if not effort or effort == 'none':
                result["reasoning"] = {"effort": REASONING_EFFORT_MINIMAL}
            else:
                result["reasoning"] = {"effort": effort or "medium"}
        elif request.reasoning_effort and request.reasoning_effort != 'none':
            result["reasoning"] = {"effort": request.reasoning_effort}
        
        # ── 过滤掉 Volcengine Responses API 不支持的额外字段 ──
        result = {k: v for k, v in result.items() if k in _VOLCENGINE_RESPONSES_ALLOWED_KEYS}
        
        # Volcengine 不支持 text.verbosity，仅支持 text.format
        if isinstance(result.get("text"), dict):
            result["text"].pop("verbosity", None)
            if not result["text"]:
                result.pop("text", None)

        return result

    def _message_to_input_item(self, message: Message) -> Any:
        """Convert a Message to Responses API input item(s)."""
        role = message.role.value

        # Handle tool result messages (preserve multi-modal output: text, images, files)
        if message.role == MessageRole.TOOL:
            tool_call_id = message.tool_call_id or ""
            blocks = message.get_content_blocks()
            for block in blocks:
                if block.type == ContentType.TOOL_RESULT:
                    return {
                        "type": "function_call_output",
                        "call_id": block.tool_call_id or tool_call_id,
                        "output": _tool_result_to_responses_output(block.tool_result)
                    }
            output_text = message.get_text_content() if message.content else ""
            return {
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": output_text
            }

        # Handle user messages containing TOOL_RESULT content blocks (Anthropic format)
        # Convert each tool_result block to a function_call_output item
        if isinstance(message.content, list):
            tool_result_blocks = [
                b for b in message.content
                if isinstance(b, ContentBlock) and b.type == ContentType.TOOL_RESULT
            ]
            if tool_result_blocks:
                items = []
                for block in tool_result_blocks:
                    items.append({
                        "type": "function_call_output",
                        "call_id": block.tool_call_id or "",
                        "output": _tool_result_to_responses_output(block.tool_result)
                    })
                # Also include non-tool-result content as a regular message
                other_blocks = [
                    b for b in message.content
                    if not (isinstance(b, ContentBlock) and b.type == ContentType.TOOL_RESULT)
                ]
                if other_blocks:
                    remaining_msg = Message(
                        role=message.role,
                        content=other_blocks,
                        name=message.name,
                    )
                    remaining_content = self._convert_content(remaining_msg)
                    items.append({"role": role, "content": remaining_content})
                return items

        # Handle assistant messages with tool calls
        if message.role == MessageRole.ASSISTANT and isinstance(message.content, list):
            items = []
            has_tool_calls = any(
                isinstance(b, ContentBlock) and b.type == ContentType.TOOL_CALL
                for b in message.content
            )

            if has_tool_calls:
                # Emit function_call items for tool calls
                for block in message.content:
                    if isinstance(block, ContentBlock) and block.type == ContentType.TOOL_CALL:
                        args = block.tool_arguments
                        if isinstance(args, dict):
                            args = json.dumps(args, ensure_ascii=False)
                        items.append({
                            "type": "function_call",
                            "call_id": block.tool_call_id or "",
                            "name": block.tool_name or "",
                            "arguments": args or "{}"
                        })

                # Also include text content as a regular message if present
                text_blocks = [b for b in message.content
                               if isinstance(b, ContentBlock) and b.type == ContentType.TEXT and b.text]
                if text_blocks:
                    content_parts = [{"type": "output_text", "text": b.text} for b in text_blocks]
                    items.insert(0, {
                        "type": "message",
                        "role": "assistant",
                        "content": content_parts,
                        "status": "completed"
                    })
                return items

        # Regular message
        content = self._convert_content(message)
        item: Dict[str, Any] = {"role": role, "content": content}
        if message.role == MessageRole.ASSISTANT:
            item["type"] = "message"
            item["status"] = "completed"
        return item

    def _convert_content(self, message: Message) -> Any:
        """Convert message content to Responses API format."""
        if isinstance(message.content, str):
            if message.content:
                return message.content
            if message.role == MessageRole.ASSISTANT:
                return [{"type": "output_text", "text": "(empty)"}]
            return "(empty)"

        # Use "output_text" for assistant messages, "input_text" for others
        text_type = "output_text" if message.role == MessageRole.ASSISTANT else "input_text"

        if isinstance(message.content, list):
            parts = []
            for block in message.content:
                if not isinstance(block, ContentBlock):
                    continue

                if block.type == ContentType.TEXT:
                    parts.append({"type": text_type, "text": block.text or ""})
                elif block.type == ContentType.IMAGE_URL:
                    parts.append({"type": "input_image", "image_url": block.url})
                elif block.type == ContentType.IMAGE_BASE64:
                    data_uri = f"data:{block.media_type or 'image/jpeg'};base64,{block.data}"
                    parts.append({"type": "input_image", "image_url": data_uri})
                elif block.type == ContentType.VIDEO_URL:
                    item = {"type": "input_video", "video_url": block.url}
                    if block.video_fps is not None:
                        item["fps"] = int(block.video_fps)
                    parts.append(item)
                elif block.type == ContentType.AUDIO_URL:
                    parts.append({"type": "input_audio", "audio_url": block.url})
                elif block.type == ContentType.FILE_URL:
                    parts.append({"type": "input_file", "file_url": block.url})
                elif block.type == ContentType.TOOL_CALL:
                    pass  # Handled separately
                else:
                    parts.append({"type": "input_text", "text": str(block.text or block.data or "")})

            if parts:
                return parts
            if message.role == MessageRole.ASSISTANT:
                return [{"type": "output_text", "text": "(empty)"}]
            return "(empty)"

        if message.content:
            return message.content
        if message.role == MessageRole.ASSISTANT:
            return [{"type": "output_text", "text": "(empty)"}]
        return "(empty)"

    # ----------------------------------------------------------------
    # Non-streaming
    # ----------------------------------------------------------------

    def _has_video_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request carries a video_generation tool flag."""
        return bool(request.metadata.get("_video_generation"))

    def _has_3d_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request carries a 3d_generation tool flag."""
        return has_threed_generation_tool(request)

    def is_3d_generation_model(self, model: str) -> bool:
        """Check if the model is a Seed3D 3D generation model."""
        return is_seed3d_model(model)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Execute non-streaming request via /responses."""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        # Seed3D 3D generation models → dedicated 3D generation path
        if is_seed3d_model(request.model) or self._has_3d_generation_tool(request):
            return await execute_seed3d_generation(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                tracer=self.tracer,
            )

        # Seedance video generation models → dedicated video generation path
        if is_seedance_video_model(request.model) or self._has_video_generation_tool(request):
            return await execute_seedance_video_generation(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                tracer=self.tracer,
            )

        # For image generation models (e.g. Seedream), bypass the Responses API
        # and call the image generation API directly.
        if self.is_image_generation_model(request.model):
            return await self._execute_image_generation_direct(request)

        request_data = await self.aprepare_request(request)
        request_data["stream"] = False

        url = f"{self.config.base_url}/responses"

        try:
            req_timeout = self._get_request_timeout(request)
            async with self._trace_call(request.model, input_data=request_data) as child_span:
                response = await (await self._http()).post(url, json=request_data, headers=self.get_headers(), **({"timeout": req_timeout} if req_timeout else {}))

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        raise RuntimeError(
                            f"Volcengine API error ({response.status_code}): "
                            f"{json.dumps(error_data, ensure_ascii=False)}"
                        )
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"Volcengine API error ({response.status_code}): {response.text}"
                        )

                response_data = response.json()
                if child_span:
                    _x_req_id = response.headers.get("x-request-id", "")
                    _output = dict(response_data)
                    if _x_req_id:
                        _output["x-request-id"] = _x_req_id
                    child_span.log_output(_output)
                return self._parse_responses_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Volcengine API error: {str(e)}")

    def _parse_responses_response(self, data: Dict[str, Any], model: str) -> ChatResponse:
        """Parse Responses API response into ChatResponse."""
        output_items = data.get("output", [])

        text_content = ""
        reasoning_content = ""
        tool_calls = []

        for item in output_items:
            item_type = item.get("type", "")

            if item_type == "reasoning":
                # Extract reasoning summary text
                for summary in item.get("summary", []):
                    if summary.get("type") == "summary_text":
                        reasoning_content += summary.get("text", "")

            elif item_type == "message":
                for content_part in item.get("content", []):
                    if content_part.get("type") == "output_text":
                        text_content += content_part.get("text", "")

            elif item_type == "function_call":
                tc = ToolCall(
                    id=item.get("call_id", item.get("id", "")),
                    name=item.get("name", ""),
                    arguments=json_loads(item.get("arguments", "{}")) if isinstance(item.get("arguments"), str) else item.get("arguments", {}),
                    call_type="function"
                )
                tool_calls.append(tc)

        # Build ChatResponse
        message = Message(
            role=MessageRole.ASSISTANT,
            content=text_content or None,
            reasoning_content=reasoning_content or None
        )

        finish_reason = FinishReason.TOOL_CALLS if tool_calls else FinishReason.STOP
        status = data.get("status", "completed")
        if status == "incomplete":
            finish_reason = FinishReason.LENGTH

        choice = ChatChoice(
            index=0,
            message=message,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content or None
        )

        usage_data = data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            reasoning_tokens=usage_data.get("output_tokens_details", {}).get("reasoning_tokens", 0),
            cached_tokens=usage_data.get("input_tokens_details", {}).get("cached_tokens", 0),
        )

        return ChatResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
            model=data.get("model", model),
            choices=[choice],
            usage=usage,
            created=data.get("created_at", int(time.time())),
            provider=self.PROVIDER_TYPE
        )

    # ----------------------------------------------------------------
    # Streaming
    # ----------------------------------------------------------------

    async def _execute_image_generation_direct(self, request: ChatRequest) -> ChatResponse:
        """
        Execute image generation directly from a ChatRequest.

        Extracts the prompt and reference images from the last user message,
        plus any optional image generation parameters from the request metadata,
        then calls the image generation API directly.

        Args:
            request: ChatRequest with the image generation prompt

        Returns:
            ChatResponse with generated image(s)
        """
        # Extract prompt and reference images from the last user message
        prompt = ""
        reference_images: List[str] = []

        for msg in reversed(request.messages):
            if msg.role == MessageRole.USER:
                if isinstance(msg.content, str):
                    prompt = msg.content
                elif isinstance(msg.content, list):
                    for block in msg.content:
                        if isinstance(block, ContentBlock):
                            if block.type == ContentType.TEXT and block.text and not prompt:
                                prompt = block.text
                            elif block.type == ContentType.IMAGE_URL and block.url:
                                reference_images.append(block.url)
                            elif block.type == ContentType.IMAGE_BASE64 and block.data:
                                # Convert base64 to data URI for the API
                                mime = block.media_type or "image/jpeg"
                                data_uri = f"data:{mime};base64,{block.data}"
                                reference_images.append(data_uri)
                if prompt:
                    break

        if not prompt:
            raise ValueError("No prompt found for image generation. Please provide a text prompt.")

        # Extract optional parameters from metadata or use defaults
        # Metadata keys mirror the real API fields for easy pass-through
        size = request.metadata.get('size', '1024x1024')
        number = request.metadata.get('number', 1)
        response_format = request.metadata.get('response_format', 'url')
        image_format = request.metadata.get('image_format', 'png')
        seed = request.metadata.get('seed')
        watermark = request.metadata.get('watermark', False)
        req_timeout = request.metadata.get('timeout')

        return await self.execute_image_generation(
            model=request.model,
            prompt=prompt,
            size=size,
            number=number,
            response_format=response_format,
            image_format=image_format,
            seed=seed,
            watermark=watermark,
            reference_images=reference_images if reference_images else None,
            timeout=req_timeout,
        )

    async def _download_image_as_b64(self, url: str, fallback_mime: str = "image/png") -> Optional[str]:
        """Download an image URL and return it as a base64 data URI.

        Returns ``None`` if the download fails, so the caller can fall back
        to the raw URL.
        """
        try:
            resp = await (await self._http()).get(url, headers=self.get_headers(), timeout=30)
            if resp.status_code >= 400:
                return None
            content_type = resp.headers.get("Content-Type", "")
            data = resp.content
            mime = content_type.split(";")[0].strip() or fallback_mime
            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{b64}"
        except Exception as exc:
            logging.getLogger("model_link.volcengine").warning(
                "Failed to convert image URL to base64: %s – %s", url, exc
            )
            return None

    async def _stream_image_generation(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """
        Execute image generation and yield the result as StreamChunks.

        Emits `image_generation_call` SSE items directly via raw_sse_passthrough so
        that the Responses API adapter passes them through verbatim instead of wrapping
        them in output_text events.

        SSE event sequence:
        1. response.created / response.in_progress   (emitted by format_stream_start)
        2. response.output_item.added  (image_generation_call, status=generating)
        3. image_generation_call done  (status=completed, one per image)
        4. response.output_item.done
        5. response.completed          (emitted by finish chunk)
        """
        response = await self._execute_image_generation_direct(request)
        response_id = response.id
        model = response.model

        # Parse the images list from the response content
        images = []
        if response.choices and response.choices[0].message:
            raw = response.choices[0].message.content or "[]"
            try:
                images = json_loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                images = []

        # b64_json conversion for streaming: convert image URLs to base64
        # data URIs before constructing SSE events. This mirrors what
        # _apply_b64_json_to_image_output() does for the non-streaming sync
        # and async GET paths in gateway_responses.py.
        # images are parsed from image_call_items JSON, so each item has
        # keys: type, status, result (not url).
        convert_to_b64 = response.usage.extra.get('_response_format') == 'b64_json'
        if convert_to_b64:
            for img in images:
                url = img.get("result", "")
                if url and not url.startswith("data:"):
                    b64_data_uri = self._download_image_as_b64(url)
                    if b64_data_uri:
                        img["result"] = b64_data_uri

        # Emit the stream start events (response.created + response.in_progress) with the
        # real response ID via raw_sse_passthrough on the role-marker chunk.
        # The role marker (delta_role="assistant") is consumed by create_stream_response to
        # capture the real response ID so format_stream_start uses it.
        # The raw_sse_passthrough overrides format_stream_start: the Responses adapter detects
        # a non-marker first chunk (has raw_sse_passthrough) → buffers it → calls
        # format_stream_start with the captured ID → but we emit our own start events here,
        # so we mark this with a special flag to suppress the default message/content_part items.
        #
        # Since we can't easily suppress format_stream_start, we instead emit a pure marker
        # first so format_stream_start fires (with the real ID), then immediately override its
        # message/content_part items by emitting a "cancel" via raw_sse_passthrough on the
        # first real chunk.
        #
        # Simplest approach: yield the role marker (marker only → consumed, no output),
        # then have create_stream_response emit format_stream_start normally.
        # The extra empty message item from format_stream_start is harmless for image gen.
        yield StreamChunk(
            id=response_id,
            model=model,
            delta_role="assistant",
            event_type=StreamEventType.CONTENT_DELTA
        )

        # Emit one image_generation_call item per image via raw SSE passthrough
        for i, img in enumerate(images):
            result = img.get("result") or img.get("url") or img.get("base64") or ""
            call_id = f"{response_id}-{i}" if i > 0 else response_id
            output_index = i

            # response.output_item.added (generating)
            item_added = {
                "type": "response.output_item.added",
                "output_index": output_index,
                "item": {
                    "type": "image_generation_call",
                    "id": call_id,
                    "status": "generating",
                    "result": None,
                }
            }
            # response.output_item.done (completed with result)
            item_done = {
                "type": "response.output_item.done",
                "output_index": output_index,
                "item": {
                    "type": "image_generation_call",
                    "id": call_id,
                    "status": "completed",
                    "result": result,
                }
            }

            chunk = StreamChunk(
                id=response_id,
                model=model,
                event_type=StreamEventType.CONTENT_DELTA
            )
            chunk.raw_sse_passthrough = [
                f"event: response.output_item.added\ndata: {json.dumps(item_added, ensure_ascii=False)}\n\n",
                f"event: response.output_item.done\ndata: {json.dumps(item_done, ensure_ascii=False)}\n\n",
            ]
            yield chunk

        # Yield finish chunk with usage so the adapter emits response.completed
        finish_usage = UsageInfo()
        if response.usage:
            finish_usage = response.usage

        # Build the completed response output with all image_generation_call items
        output_items = [
            {
                "type": "image_generation_call",
                "id": (f"{response_id}-{i}" if i > 0 else response_id),
                "status": "completed",
                "result": (img.get("result") or img.get("url") or img.get("base64") or ""),
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
                "input_tokens": finish_usage.prompt_tokens,
                "output_tokens": finish_usage.completion_tokens,
                "total_tokens": finish_usage.total_tokens,
            }
        }
        completed_event = {
            "type": "response.completed",
            "response": completed_response,
        }

        finish_chunk = StreamChunk(
            id=response_id,
            model=model,
            event_type=StreamEventType.CONTENT_DELTA,
            created=response.created
        )
        finish_chunk.raw_sse_passthrough = [
            f"event: response.completed\ndata: {json.dumps(completed_event, ensure_ascii=False)}\n\n"
        ]
        yield finish_chunk

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """Execute streaming request via /responses."""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        # Seed3D 3D generation models → dedicated 3D generation path
        if is_seed3d_model(request.model) or self._has_3d_generation_tool(request):
            async for chunk in stream_seed3d_generation(self.chat, request):
                yield chunk
            return

        # Seedance video generation models → dedicated video generation path
        if is_seedance_video_model(request.model) or self._has_video_generation_tool(request):
            async for chunk in stream_seedance_video_generation(self.chat, request):
                yield chunk
            return

        # For image generation models (e.g. Seedream), bypass the Responses API
        # and emit the result as stream chunks.
        if self.is_image_generation_model(request.model):
            async for chunk in self._stream_image_generation(request):
                yield chunk
            return

        request_data = await self.aprepare_request(request)
        request_data["stream"] = True

        url = f"{self.config.base_url}/responses"
        # Use a full-length placeholder ID; will be replaced by the real ID
        # from the response.created event as soon as it arrives.
        response_id = f"chatcmpl-{uuid.uuid4().hex}"

        # Track which function call IDs we've already emitted the initial chunk for.
        # Volcengine sends call_id on every delta event, but we only want to include
        # the `id` field on the FIRST chunk so the Anthropic adapter emits exactly one
        # content_block_start per tool_use.
        seen_call_ids: set = set()

        try:
            req_timeout = self._get_request_timeout(request)
            async with self._trace_call(request.model, input_data=request_data) as child_span:
                async with (await self._http()).stream("POST", url, json=request_data, headers=self.get_headers(), **({"timeout": req_timeout} if req_timeout else {})) as response:
                    if child_span:
                        _x_req_id = response.headers.get("x-request-id", "")
                        if _x_req_id:
                            child_span.log_output({"x-request-id": _x_req_id})

                    if response.status_code >= 400:
                        error_text = ""
                        async for chunk_bytes in response.aiter_bytes():
                            if chunk_bytes:
                                error_text += chunk_bytes.decode('utf-8')
                        try:
                            error_data = json.loads(error_text)
                            raise RuntimeError(
                                f"Volcengine API error ({response.status_code}): "
                                f"{json.dumps(error_data, ensure_ascii=False)}"
                            )
                        except json.JSONDecodeError:
                            raise RuntimeError(
                                f"Volcengine API error ({response.status_code}): {error_text}"
                            )

                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        # Parse SSE: "event: xxx\ndata: {...}" or "data: {...}"
                        event_type = None
                        data_str = None

                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                            continue
                        elif line.startswith("data:"):
                            data_str = line[5:].strip()
                        else:
                            continue

                        if not data_str or data_str == "[DONE]":
                            continue

                        try:
                            event_data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Determine event type from data if not from SSE event line
                        if not event_type:
                            event_type = event_data.get("type", "")

                        # Capture the real response ID from early events so all
                        # subsequent chunks (and the Anthropic message_start event)
                        # use the authoritative ID instead of the placeholder.
                        if event_type in ("response.created", "response.in_progress"):
                            resp_obj = event_data.get("response", {})
                            real_id = resp_obj.get("id")
                            if real_id:
                                response_id = real_id

                        chunk = self._parse_responses_stream_event(
                            event_type, event_data, response_id, request.model,
                            seen_call_ids=seen_call_ids
                        )
                        if chunk:
                            yield chunk

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Volcengine streaming API error: {str(e)}")

    def _parse_responses_stream_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        response_id: str,
        model: str,
        seen_call_ids: Optional[set] = None
    ) -> Optional[StreamChunk]:
        """Parse a single Responses API SSE event into a StreamChunk.

        Volcengine Responses API event sequence:    
        1. response.created
        2. response.in_progress
        3. response.output_item.added (type=message, role=assistant)
        4. response.reasoning_summary_part.added
        5. response.reasoning_summary_text.delta (reasoning content)
        6. response.reasoning_summary_text.done
        7. response.reasoning_summary_part.done
        8. response.output_item.done
        9. response.output_item.added (type=function_call, with call_id + name)
        10. response.function_call_arguments.delta (arguments chunks)
        11. response.function_call_arguments.done
        12. response.output_item.done
        13. response.completed

        Args:
            seen_call_ids: Tracks which function call IDs have already been emitted
                via response.output_item.added. Used to avoid duplicate emissions.
        """
        if seen_call_ids is None:
            seen_call_ids = set()

        # ---- Text content ----
        if event_type == "response.output_text.delta":
            delta_text = data.get("delta", "")
            if delta_text:
                return StreamChunk(
                    id=response_id,
                    model=model,
                    delta_content=delta_text,
                    event_type=StreamEventType.CONTENT_DELTA
                )

        # ---- Reasoning/thinking content ----
        elif event_type == "response.reasoning_summary_text.delta":
            delta_text = data.get("delta", "")
            if delta_text:
                return StreamChunk(
                    id=response_id,
                    model=model,
                    delta_reasoning_content=delta_text,
                    event_type=StreamEventType.CONTENT_DELTA
                )

        # Reasoning summary done events — contain the full assembled reasoning text.
        # Pass through as raw SSE events for the Responses adapter (/v1/responses).
        # For Anthropic/OpenAI format, the content was already streamed via deltas.
        elif event_type == "response.reasoning_summary_text.done":
            raw_event = {
                "type": event_type,
                "summary_index": data.get("summary_index", 0),
                "item_id": data.get("item_id", ""),
                "output_index": data.get("output_index", 0),
                "text": data.get("text", ""),
                "sequence_number": data.get("sequence_number", 0),
            }
            chunk = StreamChunk(
                id=response_id,
                model=model,
                event_type=StreamEventType.CONTENT_DELTA
            )
            chunk.raw_sse_passthrough = [
                f"event: {event_type}\ndata: {json.dumps(raw_event, ensure_ascii=False)}\n\n"
            ]
            return chunk

        elif event_type == "response.reasoning_summary_part.done":
            raw_event = {
                "type": event_type,
                "item_id": data.get("item_id", ""),
                "output_index": data.get("output_index", 0),
                "summary_index": data.get("summary_index", 0),
                "part": data.get("part", {}),
                "sequence_number": data.get("sequence_number", 0),
            }
            chunk = StreamChunk(
                id=response_id,
                model=model,
                event_type=StreamEventType.CONTENT_DELTA
            )
            chunk.raw_sse_passthrough = [
                f"event: {event_type}\ndata: {json.dumps(raw_event, ensure_ascii=False)}\n\n"
            ]
            return chunk

        # ---- Output item added (role marker OR function_call start) ----
        elif event_type == "response.output_item.added":
            item = data.get("item", {})
            item_type = item.get("type", "")

            if item_type == "message" and item.get("role") == "assistant":
                # Role marker — emit as role chunk
                return StreamChunk(
                    id=response_id,
                    model=model,
                    delta_role="assistant",
                    event_type=StreamEventType.CONTENT_DELTA
                )

            elif item_type == "function_call":
                # Function call start — emit tool_calls with id + name.
                # This triggers content_block_start (tool_use) in the Anthropic adapter.
                call_id = item.get("call_id", "")
                name = item.get("name", "")

                if call_id and call_id not in seen_call_ids:
                    seen_call_ids.add(call_id)
                    tc: Dict[str, Any] = {
                        "id": call_id,
                        "function": {
                            "name": name,
                            "arguments": ""
                        }
                    }
                    return StreamChunk(
                        id=response_id,
                        model=model,
                        tool_calls=[tc],
                        event_type=StreamEventType.TOOL_CALL
                    )

        # ---- Function call arguments delta ----
        elif event_type == "response.function_call_arguments.delta":
            delta_args = data.get("delta", "")
            if delta_args:
                # Only emit arguments delta — the id/name was already emitted
                # via response.output_item.added
                tc = {
                    "function": {"arguments": delta_args}
                }
                return StreamChunk(
                    id=response_id,
                    model=model,
                    tool_calls=[tc],
                    event_type=StreamEventType.TOOL_CALL
                )

        # Function call arguments done — no action needed
        elif event_type == "response.function_call_arguments.done":
            return None

        # ---- Response completed ----
        elif event_type == "response.completed":
            resp = data.get("response", {})
            usage_data = resp.get("usage", {})

            input_tokens = usage_data.get("input_tokens", 0)
            output_tokens = usage_data.get("output_tokens", 0)
            total_tokens = usage_data.get("total_tokens", 0)
            input_details = usage_data.get("input_tokens_details", {})
            output_details = usage_data.get("output_tokens_details", {})
            usage_info = UsageInfo(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=total_tokens,
                cached_tokens=input_details.get("cached_tokens", 0),
                reasoning_tokens=output_details.get("reasoning_tokens", 0),
            )

            status = resp.get("status", "completed")
            finish = FinishReason.STOP
            if status == "incomplete":
                finish = FinishReason.LENGTH

            # Check if output contains function_call items → set TOOL_CALLS finish reason
            has_function_calls = any(
                item.get("type") == "function_call"
                for item in resp.get("output", [])
            )
            if has_function_calls:
                finish = FinishReason.TOOL_CALLS

            # Extract full text from completed response for the done-event sequence
            full_text = ""
            for item in resp.get("output", []):
                if item.get("type") == "message":
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            full_text += part.get("text", "")

            return StreamChunk(
                id=resp.get("id", response_id),
                model=resp.get("model", model),
                delta_content=full_text,
                finish_reason=finish,
                usage=usage_info,
                event_type=StreamEventType.CONTENT_DELTA,
                created=resp.get("created_at", int(time.time()))
            )

        # Ignore other events (response.created, response.in_progress,
        # response.content_part.added, response.output_text.done,
        # response.output_item.done, response.reasoning_summary_part.added, etc.)
        return None

    def list_models(self) -> List[Dict[str, Any]]:
        return []

    # ----------------------------------------------------------------
    # Embedding Support
    # ----------------------------------------------------------------

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        执行嵌入请求。

        doubao-embedding-vision 系列模型通过 /embeddings/multimodal 端点
        支持文本、图片、视频的多模态嵌入。纯文本输入同样走该端点。
        """
        return await execute_volcengine_multimodal_embed(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            request=request,
            tracer=self.tracer,
        )

    # ----------------------------------------------------------------
    # Image Generation Support
    # ----------------------------------------------------------------

    def is_image_generation_model(self, model: str) -> bool:
        """
        Check if the model is an image generation model.

        A model is treated as an image generation model when its name
        contains 'seedream' (case-insensitive), which covers all
        Doubao Seedream variants (doubao-seedream-*, seedream-*, etc.).

        Args:
            model: Model name

        Returns:
            True if the model name contains 'seedream'
        """
        return "seedream" in model.lower()

    async def execute_image_generation(
        self,
        model: str,
        prompt: str,
        size: str = "1024x1024",
        number: int = 1,
        response_format: str = "url",
        image_format: str = "png",
        seed: Optional[int] = None,
        watermark: bool = False,
        reference_images: Optional[List[str]] = None,
        timeout: Optional[int] = None,
    ) -> ChatResponse:
        """
        Execute image generation request directly.

        Calls the Doubao image generation API (/v3/images/generations) with
        the given model name and parameters.

        Args:
            model: Model name (any name containing 'seedream')
            prompt: Image description
            size: Output image size (e.g. "1024x1024", "2K")
            number: Number of images to generate
            response_format: Return format ('url' or 'b64_json')
            image_format: Image file format ('png' or 'jpg')
            seed: Random seed for reproducibility
            watermark: Whether to add a watermark
            reference_images: List of reference image URLs (for image-to-image)

        Returns:
            ChatResponse with generated image(s)
        """
        image_provider = DoubaoImageProvider(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            tracer=self.tracer,
        )

        try:
            # Volcengine image generation API always returns URLs.
            # We pass "url" explicitly and return URLs to the upper layer.
            # If the caller requested b64_json, the conversion happens at the
            # final return point (format_response for sync, GET /v1/responses for async).
            response_data = await image_provider.generate_image(
                model_name=model,
                prompt=prompt,
                size=size,
                number=number,
                response_format="url",
                image_format=image_format,
                seed=seed,
                watermark=watermark,
                reference_images=reference_images,
                support_output_format=get_support_output_format(model),
                timeout=timeout,
            )
            
            images = image_provider.parse_image_response(response_data)

            # Build image_generation_call items — one per generated image.
            # Always store URLs; b64_json conversion is done downstream.
            image_call_items = [
                {
                    "type": "image_generation_call",
                    "status": "completed",
                    "result": img.get("url", ""),
                }
                for img in images
            ]

            message = Message(
                role=MessageRole.ASSISTANT,
                content=json.dumps(image_call_items, ensure_ascii=False)
            )
            
            choice = ChatChoice(
                index=0,
                message=message,
                finish_reason=FinishReason.STOP,
                tool_calls=[],
            )
            
            # Extract token usage from the API response
            api_usage = response_data.get("usage", {})
            output_tokens = api_usage.get("output_tokens", 0)
            total_tokens = api_usage.get("total_tokens", 0)
            generated_images = api_usage.get("generated_images", len(image_call_items) if image_call_items else 1)

            # Derive aspect ratio and resolution tier from size string
            img_aspect, img_tier = resolve_image_size(size=size)
            img_extra: Dict[str, Any] = {
                'output_image_number': generated_images,
                'output_image_resolution': img_tier or size,
                '_response_format': response_format,
            }
            if img_aspect:
                img_extra['output_image_aspect'] = img_aspect

            # Use gen_id to generate a unique response ID
            response_id = gen_id("img")

            return ChatResponse(
                id=response_id,
                model=model,
                choices=[choice],
                usage=UsageInfo(
                    prompt_tokens=0,
                    completion_tokens=output_tokens,
                    total_tokens=total_tokens,
                    extra=img_extra,
                ),
                created=response_data.get("created", int(time.time())),
                provider=self.PROVIDER_TYPE
            )
            
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Image generation error: {str(e)}")
