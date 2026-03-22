"""
Anthropic 供应商实现 (Anthropic Provider)
实现 Anthropic Messages API 的原生调用。

Anthropic API 特点：
- 使用 x-api-key 头部认证（不是 Bearer token）
- 需要 anthropic-version 头部
- system 消息是顶级字段，不在 messages 数组中
- 工具定义使用 input_schema（不是 parameters）
- 流式响应使用 Anthropic 特有的 SSE 事件格式
- 支持 extended thinking（思维链）

API 文档: https://docs.anthropic.com/en/api/messages
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

# Internal metadata keys set by the gateway service.
# These must be filtered out before sending requests to upstream provider APIs.
_GATEWAY_INTERNAL_KEYS = frozenset({'support_thinking'})


class AnthropicProvider(BaseProvider):
    """
    Anthropic 供应商实现

    通过 Anthropic Messages API 调用 Claude 模型。
    """

    PROVIDER_TYPE: str = "anthropic"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.CACHE,
    ]

    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://api.anthropic.com"

    # Anthropic API 版本
    ANTHROPIC_VERSION = "2023-06-01"

    # 支持的模型列表
    SUPPORTED_MODELS = {
        "claude-sonnet-4-20250514": {
            "description": "Claude Sonnet 4 - Anthropic's latest balanced model",
            "context_size": 200000,
            "supports_vision": True,
        },
        "claude-3-7-sonnet-20250219": {
            "description": "Claude 3.7 Sonnet - Extended thinking with hybrid reasoning",
            "context_size": 200000,
            "supports_vision": True,
        },
        "claude-3-5-sonnet-20241022": {
            "description": "Claude 3.5 Sonnet v2 - Most intelligent Claude model",
            "context_size": 200000,
            "supports_vision": True,
        },
        "claude-3-5-sonnet-20240620": {
            "description": "Claude 3.5 Sonnet - Balanced intelligence and speed",
            "context_size": 200000,
            "supports_vision": True,
        },
        "claude-3-5-haiku-20241022": {
            "description": "Claude 3.5 Haiku - Fastest and most compact Claude",
            "context_size": 200000,
            "supports_vision": True,
        },
        "claude-3-opus-20240229": {
            "description": "Claude 3 Opus - Powerful model for complex tasks",
            "context_size": 200000,
            "supports_vision": True,
        },
        "claude-3-haiku-20240307": {
            "description": "Claude 3 Haiku - Fast and efficient",
            "context_size": 200000,
            "supports_vision": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化 Anthropic 供应商

        Args:
            config: 供应商配置
                - api_key: Anthropic API 密钥
                - base_url: API 基础 URL（默认 https://api.anthropic.com）
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        super().__init__(config)

    def get_headers(self) -> Dict[str, str]:
        """
        获取请求头

        Anthropic 使用 x-api-key 认证，而非 Authorization: Bearer
        """
        return {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
        }

    @property
    def client(self) -> Any:
        """获取 HTTP 客户端"""
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                timeout=self.config.timeout,
                headers=self.get_headers()
            )
        return self._client

    def supports_model(self, model: str) -> bool:
        """Anthropic 支持自定义模型名"""
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """获取模型信息"""
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        return {
            "description": f"Anthropic Model: {model}",
            "context_size": 200000,
            "supports_vision": True,
        }

    # ==================== 请求准备 ====================

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        将 ChatRequest 转换为 Anthropic Messages API 格式。

        Anthropic 格式:
        {
            "model": "claude-3-opus-20240229",
            "max_tokens": 4096,
            "system": "You are a helpful assistant.",
            "messages": [{"role": "user", "content": "Hello!"}],
            "tools": [...],
            "stream": false
        }
        """
        result = {
            "model": request.model,
            "max_tokens": request.max_tokens or 4096,
        }

        # system 消息是顶级字段
        system_content = request.get_system_message()
        if system_content:
            result["system"] = system_content

        # 转换对话消息（排除 system）
        messages = []
        for msg in request.messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            anthropic_msg = self._message_to_anthropic(msg)
            if anthropic_msg:
                messages.append(anthropic_msg)
        result["messages"] = messages

        # 可选参数
        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.stop:
            result["stop_sequences"] = request.stop

        # 工具定义
        if request.tools:
            result["tools"] = [self._tool_to_anthropic(t) for t in request.tools]
        if request.tool_choice:
            if isinstance(request.tool_choice, str):
                if request.tool_choice == "auto":
                    result["tool_choice"] = {"type": "auto"}
                elif request.tool_choice == "required":
                    result["tool_choice"] = {"type": "any"}
                elif request.tool_choice == "none":
                    # Anthropic doesn't have a "none" tool_choice; omit tools instead
                    result.pop("tools", None)
                else:
                    result["tool_choice"] = {"type": "tool", "name": request.tool_choice}
            elif isinstance(request.tool_choice, dict):
                result["tool_choice"] = request.tool_choice

        # 处理 thinking（extended thinking）
        # reasoning_effort: "high" → enable thinking, "none" → disable
        if request.reasoning_effort and request.reasoning_effort != 'none':
            # Anthropic thinking 需要设置 budget_tokens
            # 使用 max_tokens 的一定比例作为 budget，或使用合理默认值
            budget_tokens = min(request.max_tokens or 4096, 32000)
            result["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget_tokens,
            }

        # 处理 metadata 中的 response_format（如果由 Anthropic adapter 映射过来）
        if 'response_format' in request.metadata:
            rf = request.metadata['response_format']
            rf_type = rf.get('type', 'text')
            if rf_type == 'json_schema':
                json_schema = rf.get('json_schema', {})
                output_format = {
                    'type': 'json_schema',
                    'name': json_schema.get('name', 'response'),
                    'schema': json_schema.get('schema', {}),
                }
                if 'description' in json_schema:
                    output_format['description'] = json_schema['description']
                result['output_config'] = {'format': output_format}
            elif rf_type == 'json_object':
                result['output_config'] = {'format': {'type': 'json'}}

        if request.stream:
            result["stream"] = True

        return result

    def _message_to_anthropic(self, message: Message) -> Optional[Dict[str, Any]]:
        """将 Message 转换为 Anthropic 格式"""
        # Tool result messages → Anthropic user message with tool_result content
        if message.role == MessageRole.TOOL:
            content_text = ""
            if isinstance(message.content, str):
                content_text = message.content
            elif isinstance(message.content, list):
                texts = [b.text or "" for b in message.content if b.type == ContentType.TEXT]
                content_text = " ".join(texts)

            return {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": content_text,
                }]
            }

        result = {"role": message.role.value}

        if isinstance(message.content, str):
            result["content"] = message.content
        elif isinstance(message.content, list):
            content_blocks = []
            for block in message.content:
                anthropic_block = self._content_block_to_anthropic(block)
                if anthropic_block:
                    content_blocks.append(anthropic_block)
            result["content"] = content_blocks if content_blocks else ""
        else:
            result["content"] = ""

        return result

    def _content_block_to_anthropic(self, block: ContentBlock) -> Optional[Dict[str, Any]]:
        """将 ContentBlock 转换为 Anthropic 格式"""
        if block.type == ContentType.TEXT:
            return {"type": "text", "text": block.text or ""}
        elif block.type == ContentType.IMAGE_URL:
            return {
                "type": "image",
                "source": {"type": "url", "url": block.url}
            }
        elif block.type == ContentType.IMAGE_BASE64:
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": block.media_type or "image/jpeg",
                    "data": block.data,
                }
            }
        elif block.type == ContentType.TOOL_CALL:
            return {
                "type": "tool_use",
                "id": block.tool_call_id or "",
                "name": block.tool_name or "",
                "input": block.tool_arguments if isinstance(block.tool_arguments, dict) else {},
            }
        elif block.type == ContentType.TOOL_RESULT:
            return {
                "type": "tool_result",
                "tool_use_id": block.tool_call_id or "",
                "content": block.tool_result or "",
                "is_error": getattr(block, 'is_error', False),
            }
        elif block.type in (ContentType.FILE_URL, ContentType.FILE_BASE64):
            # Anthropic supports document content blocks
            if block.type == ContentType.FILE_URL:
                return {
                    "type": "document",
                    "source": {"type": "url", "url": block.url}
                }
            else:
                return {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": block.media_type or "application/pdf",
                        "data": block.data,
                    }
                }
        else:
            # Fallback: try to extract text
            if block.text:
                return {"type": "text", "text": block.text}
            return None

    def _tool_to_anthropic(self, tool: ToolDefinition) -> Dict[str, Any]:
        """将 ToolDefinition 转换为 Anthropic 格式"""
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.get_parameters_schema(),
        }

    # ==================== 响应解析 ====================

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析 Anthropic Messages API 响应。

        Anthropic 响应格式:
        {
            "id": "msg_xxx",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "Hello!"},
                {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
            ],
            "model": "claude-3-opus-20240229",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 20}
        }
        """
        content_blocks = response_data.get("content", [])
        tool_calls = []
        message_blocks = []
        thinking_parts = []

        for block in content_blocks:
            block_type = block.get("type", "")
            if block_type == "thinking":
                thinking_text = block.get("thinking", "")
                if thinking_text:
                    thinking_parts.append(thinking_text)
            elif block_type == "text":
                message_blocks.append(ContentBlock.from_text(block.get("text", "")))
            elif block_type == "tool_use":
                tc_id = block.get("id", "")
                tc_name = block.get("name", "")
                tc_input = block.get("input", {})
                tool_calls.append(ToolCall(
                    id=tc_id, name=tc_name,
                    arguments=tc_input, call_type="function"
                ))
                message_blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_input))

        message = Message(
            role=MessageRole.ASSISTANT,
            content=message_blocks if message_blocks else None
        )

        # Combine thinking parts
        reasoning_content = "\n\n".join(thinking_parts) if thinking_parts else None

        # Map stop_reason → FinishReason
        stop_reason = response_data.get("stop_reason", "end_turn")
        finish_reason_map = {
            "end_turn": FinishReason.STOP,
            "max_tokens": FinishReason.LENGTH,
            "tool_use": FinishReason.TOOL_CALLS,
            "stop_sequence": FinishReason.STOP,
        }
        finish_reason = finish_reason_map.get(stop_reason, FinishReason.STOP)

        # Parse usage
        usage_data = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            cache_read_tokens=usage_data.get("cache_read_input_tokens", 0),
            cache_write_tokens=usage_data.get("cache_creation_input_tokens", 0),
        )

        return ChatResponse(
            id=response_data.get("id", f"msg_{uuid.uuid4().hex[:12]}"),
            model=response_data.get("model", model),
            choices=[ChatChoice(
                index=0,
                message=message,
                finish_reason=finish_reason,
                tool_calls=tool_calls,
                reasoning_content=reasoning_content,
            )],
            usage=usage,
            created=int(time.time()),
            provider=self.PROVIDER_TYPE,
        )

    # ==================== 非流式请求 ====================

    def chat(self, request: ChatRequest) -> ChatResponse:
        """执行非流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        request_data = self.prepare_request(request)
        request_data["stream"] = False

        url = f"{self.config.base_url.rstrip('/')}/v1/messages"

        try:
            response = self.client.post(url, json=request_data)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(
                        f"Anthropic API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"Anthropic API error ({response.status_code}): {response.text}"
                    )

            response_data = response.json()
            return self.parse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Anthropic API error: {str(e)}")

    # ==================== 流式请求 ====================

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        request_data = self.prepare_request(request)
        request_data["stream"] = True

        url = f"{self.config.base_url.rstrip('/')}/v1/messages"
        response_id = f"msg_{uuid.uuid4().hex[:12]}"

        try:
            with self.client.stream("POST", url, json=request_data) as response:
                # Check for error status before streaming
                if response.status_code >= 400:
                    error_text = ""
                    for chunk in response.iter_bytes():
                        if chunk:
                            error_text += chunk.decode('utf-8')
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(
                            f"Anthropic API error ({response.status_code}): "
                            f"{json.dumps(error_data, ensure_ascii=False)}"
                        )
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"Anthropic API error ({response.status_code}): {error_text}"
                        )

                for line in response.iter_lines():
                    if not line:
                        continue

                    # Skip event type lines
                    if line.startswith("event:"):
                        continue

                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue

                        try:
                            event_data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        chunk = self._parse_stream_event(event_data, response_id, request.model)
                        if chunk:
                            yield chunk

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Anthropic streaming API error: {str(e)}")

    def _parse_stream_event(
        self,
        event_data: Dict[str, Any],
        response_id: str,
        model: str
    ) -> Optional[StreamChunk]:
        """
        解析 Anthropic SSE 流式事件，转换为统一的 StreamChunk。

        Anthropic 流式事件类型：
        - message_start: 消息开始（包含 usage.input_tokens）
        - content_block_start: 内容块开始（text / tool_use / thinking）
        - content_block_delta: 内容块增量（text_delta / input_json_delta / thinking_delta）
        - content_block_stop: 内容块结束
        - message_delta: 消息增量（包含 stop_reason 和 output_tokens）
        - message_stop: 消息结束
        - error: 错误
        """
        event_type = event_data.get("type", "")

        if event_type == "message_start":
            message = event_data.get("message", {})
            usage = message.get("usage", {})
            return StreamChunk(
                id=message.get("id", response_id),
                model=message.get("model", model),
                delta_role="assistant",
                event_type=StreamEventType.CONTENT_DELTA,
                usage={
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": 0,
                    "total_tokens": usage.get("input_tokens", 0),
                } if usage else None,
            )

        elif event_type == "content_block_start":
            content_block = event_data.get("content_block", {})
            block_type = content_block.get("type", "")

            if block_type == "tool_use":
                return StreamChunk(
                    id=response_id,
                    model=model,
                    tool_calls=[{
                        "index": event_data.get("index", 0),
                        "id": content_block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": content_block.get("name", ""),
                            "arguments": "",
                        }
                    }],
                    event_type=StreamEventType.TOOL_CALL,
                )
            # thinking and text content_block_start don't need to emit a chunk;
            # the actual content comes via content_block_delta
            return None

        elif event_type == "content_block_delta":
            delta = event_data.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                return StreamChunk(
                    id=response_id,
                    model=model,
                    delta_content=delta.get("text", ""),
                    event_type=StreamEventType.CONTENT_DELTA,
                )
            elif delta_type == "thinking_delta":
                return StreamChunk(
                    id=response_id,
                    model=model,
                    delta_reasoning_content=delta.get("thinking", ""),
                    event_type=StreamEventType.CONTENT_DELTA,
                )
            elif delta_type == "input_json_delta":
                return StreamChunk(
                    id=response_id,
                    model=model,
                    tool_calls=[{
                        "index": event_data.get("index", 0),
                        "function": {
                            "arguments": delta.get("partial_json", ""),
                        }
                    }],
                    event_type=StreamEventType.TOOL_CALL,
                )
            return None

        elif event_type == "message_delta":
            delta = event_data.get("delta", {})
            usage = event_data.get("usage", {})
            stop_reason = delta.get("stop_reason")

            finish_reason = None
            if stop_reason:
                finish_reason_map = {
                    "end_turn": FinishReason.STOP,
                    "max_tokens": FinishReason.LENGTH,
                    "tool_use": FinishReason.TOOL_CALLS,
                    "stop_sequence": FinishReason.STOP,
                }
                finish_reason = finish_reason_map.get(stop_reason, FinishReason.STOP)

            return StreamChunk(
                id=response_id,
                model=model,
                finish_reason=finish_reason,
                usage={
                    "prompt_tokens": 0,
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("output_tokens", 0),
                } if usage else None,
                event_type=StreamEventType.USAGE,
            )

        elif event_type == "error":
            error_info = event_data.get("error", {})
            raise RuntimeError(
                f"Anthropic stream error: {error_info.get('type', 'unknown')}: "
                f"{error_info.get('message', 'Unknown error')}"
            )

        # ping, message_stop, content_block_stop - no action needed
        return None

    # ==================== 模型列表 ====================

    def list_models(self) -> List[Dict[str, Any]]:
        """列出可用模型"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "anthropic",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 200000),
                "supports_vision": info.get("supports_vision", True),
            })
        return models
