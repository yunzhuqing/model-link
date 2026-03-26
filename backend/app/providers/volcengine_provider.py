"""
火山引擎供应商实现 (Volcengine Provider)
使用火山引擎 Ark Responses API (/v3/responses)。

火山引擎 Responses API 与 OpenAI Responses API 格式兼容，
支持 reasoning/summary、多模态输入等功能。

API 文档: https://www.volcengine.com/docs/82379/1263482
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid
import sys

from .base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall, ToolParameter, ToolType
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamEventType

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

    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                timeout=self.config.timeout,
                headers=self.get_headers()
            )
        return self._client

    def supports_model(self, model: str) -> bool:
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        return {"description": f"Volcengine model: {model}", "context_size": 128000}

    # ----------------------------------------------------------------
    # Request preparation
    # ----------------------------------------------------------------

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        Convert ChatRequest into Volcengine Responses API format.

        Responses API uses:
        - `input` instead of `messages`
        - `instructions` for system message
        - `max_output_tokens` instead of `max_tokens`
        - `reasoning` for thinking control
        """
        result: Dict[str, Any] = {"model": request.model}

        # Extract system message as instructions
        system_text = request.get_system_message()
        if system_text:
            result["instructions"] = system_text

        # Convert messages to input array
        input_items = []
        for msg in request.messages:
            if msg.role == MessageRole.SYSTEM:
                continue  # Already handled as instructions

            item = self._message_to_input_item(msg)
            if item is not None:
                if isinstance(item, list):
                    input_items.extend(item)
                else:
                    input_items.append(item)

        # If the last input item is an assistant message, set partial=true
        # so the Volcengine Responses API continues from that prefix.
        # However, skip empty assistant messages (e.g. from Anthropic's {"role": "assistant", "content": []})
        if input_items and isinstance(input_items[-1], dict) and input_items[-1].get("role") == "assistant":
            last_content = input_items[-1].get("content")
            # Check if content is empty or only contains empty text
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
                        # Non-text content (images, etc.) is always meaningful
                        if part.get("type", "") not in ("input_text", "output_text"):
                            has_meaningful_content = True
                            break

            if has_meaningful_content:
                input_items[-1]["partial"] = True
            else:
                # Remove empty assistant message — Volcengine doesn't accept it
                input_items.pop()

        result["input"] = input_items

        # Stream
        result["stream"] = request.stream

        # Optional parameters
        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.max_tokens is not None:
            result["max_output_tokens"] = request.max_tokens
        if request.stop:
            result["stop"] = request.stop

        # Tools
        if request.tools:
            result["tools"] = [self._tool_to_responses(t) for t in request.tools]
        if request.tool_choice:
            result["tool_choice"] = request.tool_choice

        # Reasoning
        # NOTE: Volcengine Responses API does NOT support the "summary" parameter.
        # Only "effort" is supported, so we strip "summary" from any reasoning config.
        reasoning_config = request.metadata.get('reasoning')
        support_thinking = request.metadata.get('support_thinking', False)

        if reasoning_config and isinstance(reasoning_config, dict):
            # Use reasoning config from the Responses API request, but strip unsupported keys
            volcengine_reasoning = {"effort": reasoning_config.get("effort", "medium")}
            result["reasoning"] = volcengine_reasoning
        elif support_thinking:
            # Model supports thinking; build reasoning config
            effort = request.reasoning_effort
            if effort == 'none':
                # Explicitly disable
                pass
            else:
                result["reasoning"] = {"effort": effort or "medium"}
        elif request.reasoning_effort and request.reasoning_effort != 'none':
            # User explicitly requested reasoning
            result["reasoning"] = {"effort": request.reasoning_effort}

        # Pass through extra metadata (excluding internal keys)
        for key, value in request.metadata.items():
            if key not in _INTERNAL_KEYS and key not in result:
                result[key] = value

        # Debug logging
        print("\n" + "=" * 50, file=sys.stderr)
        print("[Volcengine Responses API Request]", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        print("=" * 50 + "\n", file=sys.stderr)

        return result

    def _message_to_input_item(self, message: Message) -> Any:
        """Convert a Message to Responses API input item(s)."""
        role = message.role.value

        # Handle tool result messages
        if message.role == MessageRole.TOOL:
            tool_call_id = message.tool_call_id or ""
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
                        "output": block.tool_result or ""
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
            return message.content

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
                    parts.append({"type": "input_video", "video_url": block.url})
                elif block.type == ContentType.AUDIO_URL:
                    parts.append({"type": "input_audio", "audio_url": block.url})
                elif block.type == ContentType.FILE_URL:
                    parts.append({"type": "input_file", "file_url": block.url})
                elif block.type == ContentType.TOOL_CALL:
                    pass  # Handled separately
                else:
                    parts.append({"type": "input_text", "text": str(block.text or block.data or "")})

            return parts if parts else ""

        return message.content or ""

    def _tool_to_responses(self, tool: ToolDefinition) -> Dict[str, Any]:
        """Convert ToolDefinition to Responses API format.

        Responses API uses a flat structure (not nested under 'function'):
        {
            "type": "function",
            "name": "...",
            "description": "...",
            "parameters": {...}
        }
        """
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.get_parameters_schema(),
        }

    # ----------------------------------------------------------------
    # Non-streaming
    # ----------------------------------------------------------------

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Execute non-streaming request via /responses."""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        request_data = self.prepare_request(request)
        request_data["stream"] = False

        url = f"{self.config.base_url}/responses"

        try:
            response = self.client.post(url, json=request_data)

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
                    arguments=json.loads(item.get("arguments", "{}")) if isinstance(item.get("arguments"), str) else item.get("arguments", {}),
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

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """Execute streaming request via /responses."""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        request_data = self.prepare_request(request)
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
            with self.client.stream("POST", url, json=request_data) as response:
                if response.status_code >= 400:
                    error_text = ""
                    for chunk_bytes in response.iter_bytes():
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

                for line in response.iter_lines():
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

            usage = {
                "prompt_tokens": usage_data.get("input_tokens", 0),
                "completion_tokens": usage_data.get("output_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
            }
            # Include detailed breakdowns
            input_details = usage_data.get("input_tokens_details", {})
            if input_details.get("cached_tokens"):
                usage["cached_tokens"] = input_details["cached_tokens"]
            output_details = usage_data.get("output_tokens_details", {})
            if output_details.get("reasoning_tokens"):
                usage["reasoning_tokens"] = output_details["reasoning_tokens"]

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
                usage=usage,
                event_type=StreamEventType.CONTENT_DELTA,
                created=resp.get("created_at", int(time.time()))
            )

        # Ignore other events (response.created, response.in_progress,
        # response.content_part.added, response.output_text.done,
        # response.output_item.done, response.reasoning_summary_part.added, etc.)
        return None

    def list_models(self) -> List[Dict[str, Any]]:
        return []
