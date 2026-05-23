"""
Azure OpenAI 供应商实现 (Azure OpenAI Provider)
实现 Azure OpenAI API 的调用。
"""
from typing import Optional, List, Dict, Any, AsyncGenerator
import json
import time
import uuid

from .base import BaseProvider, ProviderConfig, ProviderCapability
from .openai_provider import OpenAIProvider, parse_openai_request
from app.utils import json_loads
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk


class AzureProvider(OpenAIProvider):
    """
    Azure OpenAI 供应商实现
    
    提供 Azure OpenAI API 的调用能力。
    Azure OpenAI 使用与 OpenAI 兼容的 API，但有以下不同：
    1. 认证方式：使用 api-key 头而不是 Bearer token
    2. URL 结构：需要包含部署名称和 API 版本
    3. 基础 URL 格式：https://{resource-name}.openai.azure.com
    """
    
    PROVIDER_TYPE: str = "azure"
    
    # Azure OpenAI 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
    ]
    
    # Azure API 版本
    DEFAULT_API_VERSION = "2025-04-01-preview"
    
    # Azure OpenAI 支持的模型列表（部署名称由用户自定义）
    SUPPORTED_MODELS = {
        "gpt-4o": {
            "description": "GPT-4o - 最先进的多模态模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4o-mini": {
            "description": "GPT-4o mini - 快速且经济的多模态模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4-turbo": {
            "description": "GPT-4 Turbo - 更快的 GPT-4",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4": {
            "description": "GPT-4 - 高级推理能力",
            "context_size": 8192,
            "supports_vision": False,
        },
        "gpt-35-turbo": {
            "description": "GPT-3.5 Turbo - 快速且经济",
            "context_size": 16385,
            "supports_vision": False,
        },
    }
    
    def __init__(self, config: ProviderConfig):
        """
        初始化 Azure OpenAI 供应商
        
        Args:
            config: 供应商配置
                - base_url: Azure 资源 URL (e.g., https://your-resource.openai.azure.com)
                - api_key: Azure API 密钥
                - extra_config: 可包含 'api_version' 和 'deployment_name'
        """
        # 设置默认 API 版本
        if not config.extra_config:
            config.extra_config = {}
        
        if 'api_version' not in config.extra_config:
            config.extra_config['api_version'] = self.DEFAULT_API_VERSION
        
        # 不设置默认 base_url，用户必须提供
        super().__init__(config)
    
    # Azure 使用与 OpenAI 相同的 get_headers (Bearer token)
    # 继承自 OpenAIProvider，无需重写
    
    @property
    def api_version(self) -> str:
        """获取 API 版本"""
        return self.config.extra_config.get('api_version', self.DEFAULT_API_VERSION)
    
    # Models that must use the Responses API (/v1/responses) instead of Chat Completions
    RESPONSES_API_MODELS = {
        "gpt-5.5", "gpt-5.5-pro",
        "gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.4-pro", "gpt-5.4",
        "gpt-5.3-chat", "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2",
        "gpt-5.2-chat", "gpt-5.1-codex-max", "gpt-5.1", "gpt-5.1-chat",
        "gpt-5.1-codex", "gpt-5.1-codex-mini", "gpt-5-pro", "gpt-5-codex",
        "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-chat", "gpt-4o",
        "gpt-4o-mini", "computer-use-preview", "gpt-4.1", "gpt-4.1-nano",
        "gpt-4.1-mini", "gpt-image-1", "gpt-image-1-mini", "gpt-image-1.5",
        "o1", "o3-mini", "o3", "o4-mini"
    }

    def _uses_responses_api(self, model: str) -> bool:
        """Check if the given model requires the Responses API."""
        return model in self.RESPONSES_API_MODELS

    def _tool_to_responses_api(self, tool: ToolDefinition) -> Dict[str, Any]:
        """
        Convert a ToolDefinition to the Responses API flat tool format.

        Responses API format (flat, no 'function' wrapper):
        {
            "type": "function",
            "name": "...",
            "description": "...",
            "parameters": {...}
        }

        This differs from Chat Completions format which wraps in a 'function' key.
        """
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.get_parameters_schema()
        }

    def get_chat_url(self, deployment_name: str) -> str:
        """
        获取聊天 API URL
        
        Args:
            deployment_name: Azure 部署名称
        
        Returns:
            完整的 API URL
        """
        base_url = self.config.base_url.rstrip('/')
        
        if self._uses_responses_api(deployment_name):
            return f"{base_url}/openai/responses?api-version={self.api_version}"

        return f"{base_url}/openai/deployments/{deployment_name}/chat/completions?api-version={self.api_version}"

    def _prepare_responses_api_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        Convert a ChatRequest to the OpenAI Responses API request body format.

        Responses API differences from Chat Completions:
        - Uses `input` instead of `messages`
        - Uses `instructions` instead of system message
        - Uses `max_output_tokens` instead of `max_tokens`
        """
        messages = request.messages

        # System instructions: Azure Responses API only accepts string
        if request.system is None:
            instructions = None
        elif isinstance(request.system, list):
            instructions = " ".join(
                b.get("text", "") for b in request.system
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            instructions = request.system

        # Build `input` array
        input_items = []
        for msg in messages:
            # Developer messages → {"role": "developer"} items in input
            if msg.role == MessageRole.DEVELOPER:
                content = msg.get_text_content() or ''
                if content:
                    input_items.append({"role": "developer", "content": content})
                continue
            # System messages are already in the instructions field (safety skip)
            if msg.role == MessageRole.SYSTEM:
                continue
            # Handle tool role messages → function_call_output
            # OpenAI Chat Completions uses role=tool with tool_call_id;
            # Responses API uses {"type": "function_call_output", "call_id": ..., "output": ...}
            if msg.role == MessageRole.TOOL:
                call_id = msg.tool_call_id or ""
                # Extract text content from the message
                if isinstance(msg.content, str):
                    output_text = msg.content
                elif isinstance(msg.content, list):
                    # Content may be text blocks or tool_result blocks
                    text_parts = []
                    for b in msg.content:
                        if hasattr(b, 'type'):
                            if b.type == ContentType.TOOL_RESULT and b.tool_result:
                                text_parts.append(b.tool_result)
                            elif b.type == ContentType.TEXT and b.text:
                                text_parts.append(b.text)
                        elif isinstance(b, dict):
                            # Handle raw dict blocks (e.g. from input_text format)
                            text_parts.append(b.get("text", ""))
                    output_text = " ".join(text_parts)
                else:
                    output_text = str(msg.content) if msg.content else ""

                input_items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output_text,
                })
                continue

            if isinstance(msg.content, list):
                # Check for tool_call blocks → becomes function_call top-level item
                tool_call_blocks = [b for b in msg.content if b.type == ContentType.TOOL_CALL]
                # Check for tool_result blocks → becomes function_call_output top-level item
                tool_result_blocks = [b for b in msg.content if b.type == ContentType.TOOL_RESULT]

                if tool_call_blocks:
                    # Emit each tool call as a separate function_call input item
                    for block in tool_call_blocks:
                        args = block.tool_arguments or {}
                        args_str = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
                        input_items.append({
                            "type": "function_call",
                            "call_id": block.tool_call_id or "",
                            "name": block.tool_name or "",
                            "arguments": args_str,
                            "status": "completed"
                        })
                    continue

                if tool_result_blocks:
                    # Emit each tool result as a function_call_output input item
                    for block in tool_result_blocks:
                        input_items.append({
                            "type": "function_call_output",
                            "call_id": block.tool_call_id or "",
                            "output": block.tool_result or ""
                        })
                    # Also include non-tool-result content (e.g. text) as a regular message
                    other_blocks = [
                        b for b in msg.content
                        if b.type != ContentType.TOOL_RESULT
                    ]
                    if other_blocks:
                        text_type = "output_text" if msg.role == MessageRole.ASSISTANT else "input_text"
                        content_parts = []
                        for block in other_blocks:
                            if block.type == ContentType.TEXT:
                                content_parts.append({"type": text_type, "text": block.text or ""})
                            elif block.type == ContentType.IMAGE_URL:
                                content_parts.append({
                                    "type": "input_image",
                                    "image_url": block.url
                                })
                            elif block.type == ContentType.IMAGE_BASE64:
                                media_type = block.media_type or "image/jpeg"
                                content_parts.append({
                                    "type": "input_image",
                                    "image_url": f"data:{media_type};base64,{block.data or ''}"
                                })
                        if content_parts:
                            remaining_item: Dict[str, Any] = {
                                "role": msg.role.value,
                                "content": content_parts,
                            }
                            if msg.role == MessageRole.ASSISTANT:
                                remaining_item["type"] = "message"
                                remaining_item["status"] = "completed"
                            input_items.append(remaining_item)
                    continue

            # Regular message item
            item: Dict[str, Any] = {"role": msg.role.value}

            # Use "output_text" for assistant messages, "input_text" for others
            text_type = "output_text" if msg.role == MessageRole.ASSISTANT else "input_text"

            if msg.role == MessageRole.ASSISTANT:
                item["type"] = "message"
                item["status"] = "completed"

            if isinstance(msg.content, str):
                item["content"] = [{"type": text_type, "text": msg.content}]
            elif isinstance(msg.content, list):
                content_parts = []
                for block in msg.content:
                    if block.type == ContentType.TEXT:
                        content_parts.append({"type": text_type, "text": block.text or ""})
                    elif block.type == ContentType.IMAGE_URL:
                        # Azure Responses API uses image_url as a plain string
                        content_parts.append({
                            "type": "input_image",
                            "image_url": block.url
                        })
                    elif block.type == ContentType.IMAGE_BASE64:
                        media_type = block.media_type or "image/jpeg"
                        content_parts.append({
                            "type": "input_image",
                            "image_url": f"data:{media_type};base64,{block.data or ''}"
                        })
                if content_parts:
                    item["content"] = content_parts
            else:
                item["content"] = []

            # Handle tool call results (tool role)
            if msg.tool_call_id:
                item["call_id"] = msg.tool_call_id

            input_items.append(item)

        result: Dict[str, Any] = {
            "model": request.model,
            "input": input_items,
            "stream": request.stream,
        }

        if instructions:
            result["instructions"] = instructions

        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.max_tokens is not None:
            result["max_output_tokens"] = request.max_tokens
        if request.tools:
            result["tools"] = [self._tool_to_responses_api(t) for t in request.tools]
        if request.tool_choice:
            result["tool_choice"] = request.tool_choice
        if request.stop:
            result["stop"] = request.stop
        if request.presence_penalty is not None:
            result["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            result["frequency_penalty"] = request.frequency_penalty
        if request.user:
            result["user"] = request.user

        # Add reasoning parameter for models that support it.
        # Always include "summary": "auto" so Azure emits reasoning_summary streaming events
        # (response.reasoning_summary_part.added / text.delta / text.done / part.done).
        # The caller can override this by providing a full reasoning dict in metadata.
        if request.reasoning_effort:
            # Use full reasoning config from metadata if available (includes summary field)
            reasoning_config = request.metadata.get('reasoning') if request.metadata else None
            if reasoning_config and isinstance(reasoning_config, dict):
                # Ensure summary is present; default to "auto" if not specified
                if 'summary' not in reasoning_config:
                    reasoning_config = dict(reasoning_config, summary="auto")
                result["reasoning"] = reasoning_config
            else:
                result["reasoning"] = {
                    "effort": request.reasoning_effort,
                    "summary": "auto",
                }
        
        return result

    def _parse_responses_api_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        Parse an OpenAI Responses API response body into a ChatResponse.
        """
        text_parts = []
        tool_calls = []
        reasoning_summary_parts = []


        for item in response_data.get("output", []):
            item_type = item.get("type")
            if item_type == "reasoning":
                # Extract summary_text from reasoning output item
                for summary_item in item.get("summary", []):
                    if summary_item.get("type") == "summary_text":
                        reasoning_summary_parts.append(summary_item.get("text", ""))
            elif item_type == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
            elif item_type == "function_call":
                from app.abstraction.tools import ToolCall as TC
                args_str = item.get("arguments", "{}")
                try:
                    args = json_loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=item.get("call_id") or item.get("id", ""),
                    name=item.get("name", ""),
                    arguments=args,
                    call_type="function"
                ))

        full_text = "".join(text_parts)
        message = Message(role=MessageRole.ASSISTANT, content=full_text)

        finish_reason = FinishReason.STOP
        status = response_data.get("status", "completed")
        if status == "incomplete":
            finish_reason = FinishReason.LENGTH
        elif tool_calls:
            finish_reason = FinishReason.TOOL_CALLS

        reasoning_content = "\n".join(reasoning_summary_parts) if reasoning_summary_parts else None

        choice = ChatChoice(
            index=0,
            message=message,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content
        )

        usage_data = response_data.get("usage", {})
        input_token_details = usage_data.get("input_tokens_details", {})
        output_token_details = usage_data.get("output_tokens_details", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            cached_tokens=input_token_details.get("cached_tokens", 0),
            reasoning_tokens=output_token_details.get("reasoning_tokens", 0),
        )

        # Keep Azure's original resp_ ID as-is so the caller receives the exact same ID
        resp_id = response_data.get("id", f"resp_{uuid.uuid4().hex[:12]}")

        return ChatResponse(
            id=resp_id,
            model=model,
            choices=[choice],
            usage=usage,
            created=response_data.get("created_at", int(time.time())),
            provider=self.PROVIDER_TYPE
        )

    async def _parse_responses_api_stream(
        self, response, response_id: str, model: str
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Parse Server-Sent Events from the Responses API streaming endpoint
        into StreamChunk objects.

        The real response ID is taken from Azure's `response.completed` event,
        which carries the full response object including the authoritative `id`.
        Delta chunks do not need a meaningful ID because the Responses API adapter
        does not include the ID in delta SSE events.
        """
        # Accumulate the real ID from response.completed; use fallback until then
        current_id = response_id
        # Full text captured from response.output_text.done (sent with the finish chunk)
        full_text: str = ""

        async for line in response.aiter_lines():
            if not line:
                continue

            if line.startswith("event:"):
                # SSE event name line — skip, data follows on the next line
                continue

            if line.startswith("data:"):
                data_str = line[5:].strip()

                if data_str == "[DONE]":
                    break

                try:
                    event_data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event_data.get("type", "")

                if event_type == "response.created":
                    # Capture Azure's real response ID from the first SSE event and yield a
                    # marker chunk so the adapter can use it for the response.created event
                    # it sends to the client.
                    resp = event_data.get("response", {})
                    real_id = resp.get("id")
                    if real_id:
                        current_id = real_id
                    # Yield a role-only chunk (no content) to propagate the real ID upstream.
                    # The Responses API adapter ignores role-only chunks in format_stream_chunk.
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        delta_role="assistant",
                        created=int(time.time())
                    )

                elif event_type == "response.in_progress":
                    # Azure sends this immediately after response.created; it also carries
                    # the real response ID. Capture it as a belt-and-suspenders measure.
                    # We do NOT yield a chunk — the adapter already emitted response.created.
                    resp = event_data.get("response", {})
                    real_id = resp.get("id")
                    if real_id:
                        current_id = real_id

                elif event_type == "response.output_item.added":
                    item = event_data.get("item", {})
                    item_type = item.get("type", "")
                    msg_id = item.get("id", "")

                    if item_type == "message" and msg_id.startswith("msg_"):
                        # Capture Azure's real message item ID so the adapter can use it in
                        # the response.output_item.added event it sends to the client.
                        # We encode the message ID in delta_role using the convention "msg_xxx".
                        yield StreamChunk(
                            id=current_id,
                            model=model,
                            delta_role=msg_id,  # encodes the real message ID
                            created=int(time.time())
                        )

                    elif item_type == "function_call":
                        # Function call start — emit tool_calls with id + name.
                        # This triggers content_block_start (tool_use) in the Anthropic adapter.
                        call_id = item.get("call_id", "")
                        name = item.get("name", "")
                        fc_output_index = event_data.get("output_index", 0)
                        if call_id:
                            tc: Dict[str, Any] = {
                                "index": fc_output_index,
                                "id": call_id,
                                "function": {
                                    "name": name,
                                    "arguments": ""
                                }
                            }
                            yield StreamChunk(
                                id=current_id,
                                model=model,
                                tool_calls=[tc],
                                created=int(time.time())
                            )

                elif event_type == "response.output_text.done":
                    # Capture the full assembled text; pass it with the finish chunk so
                    # the adapter can emit response.output_text.done / content_part.done /
                    # output_item.done events to the client.
                    full_text = event_data.get("text", "")

                elif event_type in (
                    "response.reasoning_summary_part.added",
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_summary_text.done",
                    "response.reasoning_summary_part.done",
                ):
                    # Forward reasoning summary events verbatim to the Responses API adapter.
                    # These events are Azure-specific and have no equivalent in the generic
                    # StreamChunk model, so we encode them as raw SSE passthrough strings.
                    raw_sse = (
                        f"event: {event_type}\n"
                        f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                    )
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        raw_sse_passthrough=[raw_sse],
                        created=int(time.time())
                    )

                elif event_type == "response.output_text.delta":
                    delta = event_data.get("delta", "")
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        delta_content=delta,
                        created=int(time.time())
                    )

                elif event_type == "response.function_call_arguments.delta":
                    delta = event_data.get("delta", "")
                    index = event_data.get("output_index", 0)
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        tool_calls=[{
                            "index": index,
                            "function": {"arguments": delta}
                        }],
                        created=int(time.time())
                    )

                elif event_type == "response.completed":
                    resp = event_data.get("response", {})
                    # Use the authoritative ID that Azure assigns in the completed event
                    real_id = resp.get("id")
                    if real_id:
                        current_id = real_id
                    usage_data = resp.get("usage", {})
                    if usage_data:
                        input_details = usage_data.get("input_tokens_details", {})
                        output_details = usage_data.get("output_tokens_details", {})
                        # Carry the full Azure response object in extra so the adapter can emit it
                        # verbatim in the response.completed SSE event.
                        usage: Optional['UsageInfo'] = UsageInfo(
                            prompt_tokens=usage_data.get("input_tokens", 0),
                            completion_tokens=usage_data.get("output_tokens", 0),
                            total_tokens=usage_data.get("total_tokens", 0),
                            cached_tokens=input_details.get("cached_tokens", 0),
                            reasoning_tokens=output_details.get("reasoning_tokens", 0),
                            extra={"_azure_completed_response": resp},
                        )
                    else:
                        usage = UsageInfo(extra={"_azure_completed_response": resp}) if resp else None

                    # Determine finish_reason: TOOL_CALLS if the response output
                    # contains any function_call items, otherwise STOP.
                    has_tool_calls = any(
                        item.get("type") == "function_call"
                        for item in resp.get("output", [])
                    )
                    finish = FinishReason.TOOL_CALLS if has_tool_calls else FinishReason.STOP

                    # Pass full_text in delta_content so the adapter can emit the three
                    # "done" events (output_text.done, content_part.done, output_item.done)
                    # before the response.completed event.
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        delta_content=full_text if full_text else None,
                        finish_reason=finish,
                        usage=usage,
                        created=int(time.time())
                    )
                    break

                elif event_type == "error":
                    error_info = event_data.get("error", {})
                    raise RuntimeError(
                        f"Azure Responses API error: {json.dumps(error_info, ensure_ascii=False)}"
                    )
    
    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型（部署名称）"""
        return True  # Azure 支持用户自定义部署名称
    
    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """获取模型信息"""
        # Azure 部署名称由用户自定义，所以总是返回基本信息
        return {
            "description": f"Azure deployment: {model}",
            "context_size": 8192,
            "supports_vision": True,  # 假设支持
        }
    
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """执行对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        deployment_name = request.model
        url = self.get_chat_url(deployment_name)

        if self._uses_responses_api(deployment_name):
            # Build Responses API request body
            request_data = self._prepare_responses_api_request(request)
            request_data["stream"] = False
        else:
            request_data = self.prepare_request(request)
            request_data["stream"] = False

        try:
            async with self._trace_call(request.model, input_data=request_data) as child_span:
                response = await self.client.post(url, json=request_data)

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        raise RuntimeError(f"Azure API error ({response.status_code}): {response.text}")

                response.raise_for_status()
                response_data = response.json()
                if child_span:
                    child_span.log_output(response_data)

                if self._uses_responses_api(deployment_name):
                    return self._parse_responses_api_response(response_data, request.model)
                return self.parse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Azure OpenAI API error: {str(e)}")

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        deployment_name = request.model
        url = self.get_chat_url(deployment_name)
        # For Chat Completions models, generate a local ID (Azure doesn't return one upfront).
        # For Responses API models, Azure provides the real ID in the response.completed event;
        # we start with an empty string and fill it in from the SSE stream.
        if self._uses_responses_api(deployment_name):
            response_id = ""
        else:
            response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        if self._uses_responses_api(deployment_name):
            request_data = self._prepare_responses_api_request(request)
            request_data["stream"] = True

            try:
                async with self._trace_call(request.model, input_data=request_data) as child_span:
                    async with self.client.stream("POST", url, json=request_data) as response:
                        if response.status_code >= 400:
                            error_text = ""
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    error_text += chunk.decode('utf-8')
                            try:
                                error_data = json.loads(error_text)
                                raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                            except json.JSONDecodeError:
                                raise RuntimeError(f"Azure API error ({response.status_code}): {error_text}")

                        async for chunk in self._parse_responses_api_stream(response, response_id, request.model):
                            yield chunk

            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"Azure Responses API streaming error: {str(e)}")
        else:
            request_data = self.prepare_request(request)
            request_data["stream"] = True

            try:
                async with self._trace_call(request.model, input_data=request_data) as child_span:
                    async with self.client.stream("POST", url, json=request_data) as response:
                        if response.status_code >= 400:
                            error_text = ""
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    error_text += chunk.decode('utf-8')
                            try:
                                error_data = json.loads(error_text)
                                raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                            except json.JSONDecodeError:
                                raise RuntimeError(f"Azure API error ({response.status_code}): {error_text}")

                        async for line in response.aiter_lines():
                            if not line:
                                continue

                            if line.startswith("data:"):
                                data_str = line[5:].strip()

                                if data_str == "[DONE]":
                                    break

                                try:
                                    chunk_data = json.loads(data_str)
                                    chunk = self._parse_stream_chunk(chunk_data, response_id, request.model)
                                    if chunk:
                                        yield chunk
                                except json.JSONDecodeError:
                                    continue

            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"Azure OpenAI streaming API error: {str(e)}")
    
    def list_models(self) -> List[Dict[str, Any]]:
        """列出支持的模型（Azure 需要用户自己配置部署）"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "azure",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
            })
        return models


    def get_embedding_url(self, deployment_name: str) -> str:
        """
        获取嵌入 API URL
        
        Azure embedding URL format:
        {base_url}/openai/deployments/{deployment_name}/embeddings?api-version={api_version}
        
        Args:
            deployment_name: Azure 部署名称 (e.g., text-embedding-3-large)
        
        Returns:
            完整的嵌入 API URL
        """
        base_url = self.config.base_url.rstrip('/')
        return f"{base_url}/openai/deployments/{deployment_name}/embeddings?api-version={self.api_version}"

    async def embed(self, request: 'EmbeddingRequest') -> 'EmbeddingResponse':
        """
        执行嵌入请求（Azure 版本）

        使用 Azure 特定的 URL 格式：
        {base_url}/openai/deployments/{model}/embeddings?api-version={api_version}

        Args:
            request: 嵌入请求对象

        Returns:
            嵌入响应对象
        """
        from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse

        # 准备请求数据 - Azure 不需要 model 字段（在 URL 中指定）
        request_data = {
            "encoding_format": request.encoding_format,
        }

        # Multimodal embedding uses "messages" instead of "input"
        if request.is_multimodal:
            request_data["messages"] = request.messages
        else:
            request_data["input"] = request.input

        if request.dimensions is not None:
            request_data["dimensions"] = request.dimensions

        if request.user:
            request_data["user"] = request.user

        url = self.get_embedding_url(request.model)

        try:
            response = await self.client.post(url, json=request_data)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    raise RuntimeError(f"Azure API error ({response.status_code}): {response.text}")

            response.raise_for_status()

            response_data = response.json()
            return self._parse_embedding_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Azure embedding API error: {str(e)}")


# 导出解析函数（与 OpenAI 格式相同）
__all__ = ['AzureProvider', 'parse_openai_request']
