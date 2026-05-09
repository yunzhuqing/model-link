"""
Anthropic Messages 适配器
处理 /v1/messages 格式的请求和响应转换。
"""
import itertools
import json
import re
import time
from typing import Optional, Generator

from quart import Response

from .base import BaseAdapter
from app.abstraction.chat import ChatRequest, ChatResponse, UsageInfo
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolParameter, ToolType
from app.middleware.gateway_service import GatewayServiceError, ProviderError
from app.utils import REASONING_EFFORT_HIGH, REASONING_EFFORT_MEDIUM, REASONING_EFFORT_NONE, REASONING_EFFORT_DEFAULT_FOR_THINKING, json_loads


class AnthropicMessagesAdapter(BaseAdapter):
    """
    Anthropic Messages API 适配器

    负责：
    - 将 Anthropic /v1/messages 请求格式解析为 ChatRequest
    - 将 ChatResponse 转换为 Anthropic 响应格式
    - 处理 Anthropic 格式的流式响应
    """

    def parse_request(self, data: dict) -> ChatRequest:
        """
        解析 Anthropic Messages 格式的请求。

        请求格式:
        {
            "model": "claude-3-opus-20240229",
            "max_tokens": 1024,
            "system": "You are a helpful assistant.",
            "messages": [
                {"role": "user", "content": "Hello!"}
            ],
            "tools": [...],
            "stream": false
        }
        """
        messages = []

        # 处理 system —— 存储到 ChatRequest.system 而不是创建 Message
        # Anthropic system 可以是字符串或内容块数组（支持 cache_control）
        model_name = data.get('model', '')
        is_claude_model = model_name.startswith('claude-')

        system_val = data.get('system')
        if isinstance(system_val, str) and not is_claude_model:
            system_val = re.sub(r'cch=[a-zA-Z0-9]+;\s*', '', system_val)
        elif isinstance(system_val, list) and not is_claude_model:
            for item in system_val:
                if 'text' in item:
                    item['text'] = re.sub(r'cch=[a-zA-Z0-9]+;\s*', '', item['text'])

        # 处理对话消息
        for msg_data in data.get('messages', []):
            role = MessageRole(msg_data.get('role', 'user'))
            content = msg_data.get('content', '')

            if isinstance(content, list):
                blocks = []
                thinking_parts = []  # 收集 thinking 内容，转换为 reasoning_content

                for item in content:
                    item_type = item.get('type', 'text')

                    # Extract cache_control if present on this content block
                    item_cache_control = item.get('cache_control')

                    if item_type == 'thinking':
                        # Anthropic thinking 块 → 赋值给 Message.reasoning_content
                        # 下游 OpenAI/Moonshot prepare_request 会将其放入消息的 reasoning_content 字段
                        thinking_text = item.get('thinking', '')
                        if thinking_text:
                            thinking_parts.append(thinking_text)
                    elif item_type == 'text':
                        block = ContentBlock.from_text(item.get('text', ''))
                        if item_cache_control:
                            block.cache_control = item_cache_control
                        blocks.append(block)
                    elif item_type == 'image':
                        source = item.get('source', {})
                        source_type = source.get('type', 'url')

                        if source_type == 'url':
                            block = ContentBlock.from_image_url(source.get('url', ''))
                        elif source_type == 'base64':
                            raw_data = source.get('data', '')
                            media_type = source.get('media_type', 'image/jpeg')
                            # Strip data URI prefix if accidentally included
                            # e.g. "data:image/jpeg;base64,/9j/..." → "/9j/..."
                            if raw_data.startswith('data:'):
                                parts = raw_data.split(',', 1)
                                if len(parts) > 1:
                                    # Extract media_type from prefix if not explicitly set
                                    prefix = parts[0]  # "data:image/jpeg;base64"
                                    extracted_type = prefix.replace('data:', '').replace(';base64', '')
                                    if extracted_type:
                                        media_type = extracted_type
                                    raw_data = parts[1]
                            block = ContentBlock.from_image_base64(raw_data, media_type)
                        else:
                            block = None
                        if block:
                            if item_cache_control:
                                block.cache_control = item_cache_control
                            blocks.append(block)
                    elif item_type == 'document':
                        # Anthropic document content block (PDF, etc.)
                        source = item.get('source', {})
                        source_type = source.get('type', 'url')
                        if source_type == 'url':
                            block = ContentBlock.from_file_url(source.get('url', ''))
                        elif source_type == 'base64':
                            block = ContentBlock.from_file_base64(
                                source.get('data', ''),
                                source.get('media_type', 'application/pdf')
                            )
                        else:
                            block = None
                        if block:
                            if item_cache_control:
                                block.cache_control = item_cache_control
                            blocks.append(block)
                    elif item_type == 'tool_use':
                        block = ContentBlock.from_tool_call(
                            item.get('id', ''),
                            item.get('name', ''),
                            item.get('input', {})
                        )
                        if item_cache_control:
                            block.cache_control = item_cache_control
                        blocks.append(block)
                    elif item_type == 'tool_result':
                        result_content = item.get('content', '')
                        if isinstance(result_content, list):
                            # Extract text from content blocks
                            texts = [c.get('text', '') for c in result_content if c.get('type') == 'text']
                            result_content = ' '.join(texts)
                        # 将 tool_result 作为 ContentBlock 添加到 blocks 列表中
                        # 这样可以保持与原始 Anthropic 格式一致，tool_result 和 text 在同一消息中
                        block = ContentBlock(
                            type=ContentType.TOOL_RESULT,
                            tool_call_id=item.get('tool_use_id', ''),
                            tool_result=result_content,
                            is_error=item.get('is_error', False),
                            cache_control=item_cache_control,
                        )
                        blocks.append(block)

                # 合并所有 thinking 块为 reasoning_content 字符串
                reasoning_content = '\n'.join(thinking_parts) if thinking_parts else None

                # 添加消息（包含 text、tool_use、tool_result 等所有内容块）
                if blocks:
                    messages.append(Message(
                        role=role,
                        content=blocks,
                        reasoning_content=reasoning_content
                    ))
                elif reasoning_content:
                    # 消息中只有 thinking 块（无其他内容），用空字符串占位内容
                    messages.append(Message(
                        role=role,
                        content='',
                        reasoning_content=reasoning_content
                    ))
                else:
                    # 如果没有任何内容块，添加空消息
                    messages.append(Message(role=role, content=''))
            else:
                # Handle tool_call_id for tool results
                tool_call_id = None
                if role == MessageRole.TOOL:
                    tool_call_id = msg_data.get('tool_use_id')

                messages.append(Message(
                    role=role,
                    content=content,
                    tool_call_id=tool_call_id
                ))

        # 处理工具定义
        tools = []
        for tool_data in data.get('tools', []):
            name = tool_data.get('name', '')
            description = tool_data.get('description', '')
            input_schema = tool_data.get('input_schema', {})

            parameters = []
            properties = input_schema.get('properties', {})
            required = input_schema.get('required', [])

            for param_name, param_schema in properties.items():
                parameters.append(ToolParameter(
                    name=param_name,
                    type=param_schema.get('type', 'string'),
                    description=param_schema.get('description'),
                    required=param_name in required,
                    enum=param_schema.get('enum'),
                    default=param_schema.get('default'),
                    items=param_schema.get('items')
                ))

            tool_def = ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                tool_type=ToolType.FUNCTION
            )
            # Preserve cache_control on tool definitions for Anthropic prompt caching
            if 'cache_control' in tool_data:
                tool_def.cache_control = tool_data['cache_control']
            tools.append(tool_def)

        # 处理 thinking 参数 → 映射为 reasoning_effort
        # Anthropic 格式: {"thinking": {"type": "enabled", "budget_tokens": 10000}}
        # 映射为 ChatRequest.reasoning_effort: "high" (enabled) / "none" (disabled)
        reasoning_effort = None
        thinking_config = data.get('thinking')
        if isinstance(thinking_config, dict):
            if thinking_config.get('type') == 'enabled':
                reasoning_effort = REASONING_EFFORT_HIGH
            else:
                reasoning_effort = REASONING_EFFORT_NONE

        # 如果模型名包含 "thinking" 但没有设置任何 reasoning_effort/thinking 参数，
        # 将 reasoning_effort 设置为默认值 "medium"
        if 'thinking' in model_name.lower() and reasoning_effort is None:
            reasoning_effort = REASONING_EFFORT_DEFAULT_FOR_THINKING

        # 处理 output_config → 映射为 OpenAI 兼容的 response_format
        # Anthropic 格式:
        #   {"output_config": {"format": {"type": "json_schema", "name": "...", "schema": {...}}}}
        # OpenAI 格式:
        #   {"response_format": {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}}
        metadata = data.get('metadata') or {}
        output_config = data.get('output_config')

        # 从 metadata.user_id 中解析 session_id
        # 格式: {"user_id": "{\"device_id\":\"...\",\"session_id\":\"...\"}"}
        session_id = data.get('session_id')
        user_id_raw = metadata.get('user_id')
        user_id = None
        if isinstance(user_id_raw, str):
            try:
                user_id_data = json_loads(user_id_raw)
                session_id = session_id if session_id else user_id_data.get('session_id')
                user_id = user_id_data.get('account_uuid') or user_id_data.get('device_id')
            except (json.JSONDecodeError, TypeError):
                pass
        
        if isinstance(output_config, dict):
            fmt = output_config.get('format', {})
            fmt_type = fmt.get('type', 'text')
            if fmt_type == 'json_schema':
                # Anthropic puts name/schema directly on format object;
                # OpenAI nests them under response_format.json_schema
                openai_json_schema = {}
                # 'name' is required by OpenAI; default to 'response' if absent
                openai_json_schema['name'] = fmt.get('name', 'response')
                if 'description' in fmt:
                    openai_json_schema['description'] = fmt['description']
                if 'schema' in fmt:
                    openai_json_schema['schema'] = fmt['schema']
                # OpenAI recommends strict mode for structured outputs
                openai_json_schema.setdefault('strict', True)
                metadata['response_format'] = {
                    'type': 'json_schema',
                    'json_schema': openai_json_schema
                }
            elif fmt_type == 'json':
                metadata['response_format'] = {'type': 'json_object'}

        return ChatRequest(
            messages=messages,
            model=data.get('model', ''),
            system=system_val,
            temperature=data.get('temperature'),
            top_p=data.get('top_p'),
            max_tokens=data.get('max_tokens', 4096),
            stream=data.get('stream', False),
            tools=tools,
            tool_choice=data.get('tool_choice', {}).get('type') if isinstance(data.get('tool_choice'), dict) else data.get('tool_choice'),
            stop=data.get('stop_sequences'),
            user=user_id,
            session_id=session_id,
            reasoning_effort=reasoning_effort,
            metadata=metadata,
        )

    def format_response(self, response: ChatResponse) -> dict:
        """
        将 ChatResponse 转换为 Anthropic Messages 响应格式。

        响应格式:
        {
            "id": "msg_xxx",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "Hello!"}
            ],
            "model": "claude-3-opus-20240229",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20
            }
        }
        """
        content = []
        for choice in response.choices:
            # 添加 thinking/reasoning 内容（来自 DeepSeek R1、Qwen 等模型）
            reasoning = choice.reasoning_content
            if not reasoning and choice.message and choice.message.reasoning_content:
                reasoning = choice.message.reasoning_content
            if reasoning:
                content.append({'type': 'thinking', 'thinking': reasoning})

            if choice.message:
                text = choice.message.get_text_content()
                if text:
                    content.append({'type': 'text', 'text': text})

                if choice.tool_calls:
                    for tc in choice.tool_calls:
                        content.append({
                            'type': 'tool_use',
                            'id': tc.id,
                            'name': tc.name,
                            'input': tc.arguments
                        })

        # Map finish_reason to Anthropic stop_reason
        stop_reason = 'end_turn'
        if response.choices:
            fr = response.choices[0].finish_reason.value
            stop_reason_map = {
                'stop': 'end_turn',
                'length': 'max_tokens',
                'tool_calls': 'tool_use',
                'content_filter': 'end_turn',
            }
            stop_reason = stop_reason_map.get(fr, 'end_turn')

        # Normalize ID to msg_ prefix for Anthropic format compatibility.
        # Non-Claude providers return IDs like "chatcmpl-xxx", "gemini-xxx",
        # or "resp_xxx" (Azure/OpenAI Responses API),
        # but Anthropic SDK clients expect "msg_xxx".
        response_id = response.id
        if not response_id.startswith('msg_'):
            # Strip known provider prefixes and re-prefix with msg_
            clean_id = response_id
            for prefix in ('chatcmpl-', 'gemini-', 'resp_'):
                if clean_id.startswith(prefix):
                    clean_id = clean_id[len(prefix):]
                    break
            response_id = f'msg_{clean_id}'

        # Anthropic convention: input_tokens EXCLUDES both
        # cache_creation_input_tokens and cache_read_input_tokens.
        # Internally prompt_tokens INCLUDES both (OpenAI convention)
        # for unified billing.  Subtract both here to restore
        # Anthropic-compatible output.
        cache_read = response.usage.cache_read_tokens or 0
        cache_write = response.usage.cache_write_tokens or 0
        anthropic_input_tokens = max(response.usage.prompt_tokens - cache_read - cache_write, 0)

        usage_dict = {
            'input_tokens': anthropic_input_tokens,
            'output_tokens': response.usage.completion_tokens,
        }
        # Include cache fields when present
        if cache_read:
            usage_dict['cache_read_input_tokens'] = cache_read
        cache_write = response.usage.cache_write_tokens or 0
        if cache_write:
            usage_dict['cache_creation_input_tokens'] = cache_write

        return {
            'id': response_id,
            'type': 'message',
            'role': 'assistant',
            'content': content,
            'model': response.model,
            'stop_reason': stop_reason,
            'stop_sequence': None,
            'usage': usage_dict,
        }

    def format_stream_start(self, model_name: str, message_id: Optional[str] = None,
                            usage: Optional[UsageInfo] = None) -> Optional[str]:
        """
        发送 Anthropic 消息开始事件。

        Anthropic SDK (pydantic) 要求 message_start 事件中的 message 对象
        包含完整的 Message 字段，否则客户端会抛出验证错误。
        必须包含: id, type, role, content, model, stop_reason, stop_sequence, usage

        Args:
            model_name: 模型名称
            message_id: 消息 ID（可选）
            usage: UsageInfo（从 is_first_chunk 的 chunk 中获取）
        """
        # 构建 message_start 的 usage，始终包含 output_tokens: 0
        # Anthropic convention: input_tokens EXCLUDES both
        # cache_creation_input_tokens and cache_read_input_tokens.
        # Internally prompt_tokens INCLUDES both (OpenAI convention).
        # Subtract both here to restore Anthropic-compatible output.
        start_usage: dict = {
            'input_tokens': 0,
            'cache_creation_input_tokens': 0,
            'cache_read_input_tokens': 0,
            'output_tokens': 0,
        }
        if usage:
            cache_read = usage.cache_read_tokens or 0
            cache_write = usage.cache_write_tokens or 0
            start_usage['input_tokens'] = max(usage.prompt_tokens - cache_read - cache_write, 0)
            start_usage['output_tokens'] = usage.completion_tokens
            start_usage['cache_creation_input_tokens'] = usage.cache_write_tokens
            start_usage['cache_read_input_tokens'] = cache_read
            # 透传 cache_creation 嵌套对象（存储在 extra 中）
            if 'cache_creation' in usage.extra:
                start_usage['cache_creation'] = usage.extra['cache_creation']

        msg_id = message_id or ('msg_' + str(int(time.time())))
        # Normalize ID to msg_ prefix
        if not msg_id.startswith('msg_'):
            for prefix in ('chatcmpl-', 'gemini-', 'resp_'):
                if msg_id.startswith(prefix):
                    msg_id = msg_id[len(prefix):]
                    break
            msg_id = f'msg_{msg_id}'

        start_data = {
            'type': 'message_start',
            'message': {
                'id': msg_id,
                'type': 'message',
                'role': 'assistant',
                'content': [],
                'model': model_name,
                'stop_reason': None,
                'stop_sequence': None,
                'usage': start_usage,
            }
        }
        return f"event: message_start\ndata: {json.dumps(start_data)}\n\n"

    def format_stream_chunk(self, chunk: StreamChunk) -> str:
        """将 StreamChunk 转换为 Anthropic SSE 格式"""
        return chunk.to_sse("anthropic")

    def format_stream_end(self) -> str:
        """Anthropic 流式结束标记"""
        end_data = {"type": "message_stop"}
        return f"event: message_stop\ndata: {json.dumps(end_data)}\n\n"

    def format_stream_error(self, error: Exception) -> str:
        """将错误转换为 Anthropic 格式的流式错误事件"""

        if isinstance(error, ProviderError) and error.error_data:
            error_event = {
                "type": "error",
                "error": error.error_data
            }
        else:
            error_event = {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": str(error)
                }
            }

        return f"event: error\ndata: {json.dumps(error_event)}\n\n"

    def format_error_response(self, message: str, status_code: int, error_data: Optional[dict] = None) -> dict:
        """
        Format errors in Anthropic-compatible structure.

        Anthropic error format:
        {
            "type": "error",
            "error": {
                "type": "not_found_error",
                "message": "Model not found"
            }
        }
        """
        if error_data:
            # If upstream already returned Anthropic-format error, pass through
            if 'type' in error_data and 'error' in error_data:
                return error_data
            # Wrap raw error data
            return {
                'type': 'error',
                'error': error_data
            }

        # Map HTTP status codes to Anthropic error types
        error_type_map = {
            400: 'invalid_request_error',
            401: 'authentication_error',
            403: 'permission_error',
            404: 'not_found_error',
            429: 'rate_limit_error',
            500: 'api_error',
            529: 'overloaded_error',
        }
        error_type = error_type_map.get(status_code, 'api_error')

        return {
            'type': 'error',
            'error': {
                'type': error_type,
                'message': message,
            }
        }

    def create_stream_response(
        self,
        chunks: Generator[StreamChunk, None, None],
        model_name: str
    ) -> Response:
        """
        从 StreamChunk 生成器创建 Anthropic 格式的 HTTP 流式响应。

        重写父类方法，实现用量（usage）累积：
        - 在 OpenAI 兼容的流式 API 中，usage 通常在 finish_reason 之后的
          独立 chunk 中发送（需要 stream_options.include_usage=true）。
        - 为了在 Anthropic 格式的 message_delta 中包含完整的 usage，
          需要缓冲 finish chunk，等待 usage chunk 到达后合并。

        Error handling: we eagerly consume the first chunk *before* committing
        to an SSE stream.  Most provider errors (authentication, invalid
        parameters, unsupported models, etc.) surface on the very first
        iteration of the upstream generator.  By catching them here we return a
        proper JSON error response with ``content-type: application/json``
        instead of an SSE event.

        流程：
        1. 流式输出 content_block_delta 等事件（实时）
        2. 遇到 finish_reason chunk 时缓冲，不立即输出
        3. 继续消费剩余 chunk，累积 usage
        4. 流结束后，将累积的 usage 注入 finish chunk 并输出
        """
        from quart import jsonify

        # ------------------------------------------------------------------
        # Eagerly consume the first chunk to surface provider errors early.
        # ------------------------------------------------------------------
        chunk_iter = iter(chunks)
        first_chunk = None
        try:
            first_chunk = next(chunk_iter)
        except StopIteration:
            pass
        except ProviderError as e:
            return jsonify(self.format_error_response(e.message, e.status_code, e.error_data)), e.status_code
        except GatewayServiceError as e:
            return jsonify(self.format_error_response(e.message, e.status_code)), e.status_code
        except Exception as e:
            return jsonify(self.format_error_response(str(e), 500)), 500

        # Capture for use inside generate()
        _first_chunk = first_chunk
        _chunk_iter = chunk_iter

        def generate():
            # 发送 message_start。
            # 如果第一个 chunk 携带 is_first_chunk=True（Anthropic 原生 provider 的 message_start 事件），
            # 则直接使用其中的 usage（含真实 input_tokens、cache tokens 等）。
            # 否则（非 Claude 供应商，usage 在流末尾才到达），先填 0，
            # 真实的 input_tokens 将在最后的 message_delta 里和 output_tokens 一起上报。
            message_id = _first_chunk.id if _first_chunk else None
            first_chunk_usage = None
            if _first_chunk and _first_chunk.is_first_chunk and _first_chunk.usage:
                first_chunk_usage = _first_chunk.usage
            start_event = self.format_stream_start(model_name, message_id=message_id, usage=first_chunk_usage)
            if start_event:
                yield start_event

            # Accumulated UsageInfo — updated as usage chunks arrive.
            # UsageInfo fields are summed/overwritten: later chunks override earlier ones
            # for token counts (typically one consolidated usage chunk arrives at stream end).
            accumulated_usage: Optional[UsageInfo] = None
            pending_finish_chunk = None
            text_block_started = False  # 跟踪是否已发送 text 的 content_block_start
            thinking_block_started = False  # 跟踪是否已发送 thinking 的 content_block_start
            block_open = False  # 是否有内容块处于打开状态
            content_block_index = 0  # 当前内容块索引

            # 实时流式处理所有 chunk（包含第一个已预取的 chunk）
            all_chunks = itertools.chain([_first_chunk], _chunk_iter) if _first_chunk else iter(_chunk_iter)

            try:
                for chunk in all_chunks:
                    # 从每个 chunk 累积 usage 信息（后续 chunk 覆盖前面的值）
                    if chunk.usage:
                        accumulated_usage = chunk.usage

                    if chunk.finish_reason:
                        # 缓冲 finish chunk，等待可能的 usage chunk
                        pending_finish_chunk = chunk
                        continue

                    # 跳过纯 usage chunk（其数据已累积，将合并到 finish chunk）
                    if chunk.event_type == StreamEventType.USAGE:
                        continue

                    # 检测内容块类型转换，管理 content_block_start/stop
                    new_block_type = None
                    if chunk.delta_reasoning_content and not thinking_block_started:
                        new_block_type = "thinking"
                    elif chunk.delta_content and not text_block_started:
                        new_block_type = "text"
                    elif chunk.tool_calls and chunk.tool_calls[0].get("id"):
                        new_block_type = "tool_use"

                    # 如果有新的内容块类型，先关闭前一个块，再打开新块
                    if new_block_type:
                        # 关闭前一个块（如果有打开的块）
                        if block_open:
                            yield f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": {content_block_index}}}\n\n"
                            content_block_index += 1

                        block_open = True
                        if new_block_type == "thinking":
                            thinking_block_started = True
                            block_start_event = {
                                "type": "content_block_start",
                                "index": content_block_index,
                                "content_block": {"type": "thinking", "thinking": ""}
                            }
                            yield f"event: content_block_start\ndata: {json.dumps(block_start_event)}\n\n"
                        elif new_block_type == "text":
                            text_block_started = True
                            block_start_event = {
                                "type": "content_block_start",
                                "index": content_block_index,
                                "content_block": {"type": "text", "text": ""}
                            }
                            yield f"event: content_block_start\ndata: {json.dumps(block_start_event)}\n\n"
                        # tool_use content_block_start 由 to_anthropic_events() 生成

                    # 设置当前内容块索引，确保 to_anthropic_events() 使用正确的索引
                    chunk.anthropic_index = content_block_index

                    # 输出内容 chunk
                    formatted = self.format_stream_chunk(chunk)
                    if formatted:
                        yield formatted

                # 关闭最后一个打开的内容块（Anthropic 协议要求每个 content_block_start 必须有对应的 content_block_stop）
                if block_open:
                    yield f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": {content_block_index}}}\n\n"

                # 流结束，输出缓冲的 finish chunk（带累积 usage）
                if pending_finish_chunk:
                    if accumulated_usage:
                        pending_finish_chunk.usage = accumulated_usage
                    # Use to_anthropic_events() but filter out content_block_stop
                    # only if we already emitted it above (when block_open is True).
                    # If block_open is False, we need the content_block_stop from
                    # to_anthropic_events() to maintain proper event sequence.
                    events = pending_finish_chunk.to_anthropic_events()
                    for event in events:
                        if event.get("type") == "content_block_stop" and block_open:
                            # Already emitted above at line 562-563, skip to avoid duplicate
                            continue
                        event_type = event.get("type", "")
                        yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                else:
                    # Fallback: always emit message_delta before message_stop.
                    # Anthropic SDK clients expect a message_delta event with
                    # stop_reason and usage before the final message_stop.
                    # Build the Anthropic-format usage from the accumulated UsageInfo.
                    if accumulated_usage:
                        # Anthropic convention: input_tokens EXCLUDES both
                        # cache_creation_input_tokens and cache_read_input_tokens.
                        # Internally prompt_tokens INCLUDES both (OpenAI convention).
                        # Subtract both here to restore Anthropic-compatible output.
                        fb_cache_read = accumulated_usage.cache_read_tokens or 0
                        fb_cache_write = accumulated_usage.cache_write_tokens or 0
                        fallback_usage = {
                            "input_tokens": max(accumulated_usage.prompt_tokens - fb_cache_read - fb_cache_write, 0),
                            "cache_creation_input_tokens": accumulated_usage.cache_write_tokens,
                            "cache_read_input_tokens": fb_cache_read,
                            "output_tokens": accumulated_usage.completion_tokens,
                        }
                        # 透传 cache_creation 嵌套对象（如果存在于 extra 中）
                        if "cache_creation" in accumulated_usage.extra:
                            fallback_usage["cache_creation"] = accumulated_usage.extra["cache_creation"]
                    else:
                        fallback_usage = {
                            "input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "output_tokens": 0,
                        }
                    fallback_delta = {
                        "type": "message_delta",
                        "delta": {
                            "stop_reason": "end_turn",
                            "stop_sequence": None,
                        },
                        "usage": fallback_usage,
                    }
                    yield f"event: message_delta\ndata: {json.dumps(fallback_delta)}\n\n"

                # 发送 message_stop
                yield self.format_stream_end()

            except (GatewayServiceError, ProviderError) as e:
                yield self.format_stream_error(e)
                yield self.format_stream_end()

            except Exception as e:
                yield self.format_stream_error(e)
                yield self.format_stream_end()

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )
