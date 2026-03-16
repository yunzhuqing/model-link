"""
Anthropic Messages 适配器
处理 /v1/messages 格式的请求和响应转换。
"""
import json
import time
from typing import Optional, Generator

from flask import Response

from .base import BaseAdapter
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.abstraction.messages import Message, MessageRole, ContentBlock
from app.abstraction.tools import ToolDefinition, ToolParameter, ToolType
from app.middleware.gateway_service import GatewayServiceError, ProviderError


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

        # 处理 system 消息
        if 'system' in data:
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content=data['system']
            ))

        # 处理对话消息
        for msg_data in data.get('messages', []):
            role = MessageRole(msg_data.get('role', 'user'))
            content = msg_data.get('content', '')

            if isinstance(content, list):
                blocks = []
                for item in content:
                    item_type = item.get('type', 'text')

                    if item_type == 'text':
                        blocks.append(ContentBlock.from_text(item.get('text', '')))
                    elif item_type == 'image':
                        source = item.get('source', {})
                        source_type = source.get('type', 'url')

                        if source_type == 'url':
                            blocks.append(ContentBlock.from_image_url(source.get('url', '')))
                        elif source_type == 'base64':
                            blocks.append(ContentBlock.from_image_base64(
                                source.get('data', ''),
                                source.get('media_type', 'image/jpeg')
                            ))
                    elif item_type == 'tool_use':
                        blocks.append(ContentBlock.from_tool_call(
                            item.get('id', ''),
                            item.get('name', ''),
                            item.get('input', {})
                        ))
                    elif item_type == 'tool_result':
                        result_content = item.get('content', '')
                        if isinstance(result_content, list):
                            # Extract text from content blocks
                            texts = [c.get('text', '') for c in result_content if c.get('type') == 'text']
                            result_content = ' '.join(texts)
                        blocks.append(ContentBlock.from_tool_result(
                            item.get('tool_use_id', ''),
                            result_content,
                            item.get('is_error', False)
                        ))

                content = blocks
            
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
                    default=param_schema.get('default')
                ))

            tools.append(ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                tool_type=ToolType.FUNCTION
            ))

        return ChatRequest(
            messages=messages,
            model=data.get('model', ''),
            temperature=data.get('temperature'),
            top_p=data.get('top_p'),
            max_tokens=data.get('max_tokens', 4096),
            stream=data.get('stream', False),
            tools=tools,
            tool_choice=data.get('tool_choice', {}).get('type') if isinstance(data.get('tool_choice'), dict) else data.get('tool_choice'),
            stop=data.get('stop_sequences'),
            metadata=data.get('metadata', {})
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

        return {
            'id': response.id,
            'type': 'message',
            'role': 'assistant',
            'content': content,
            'model': response.model,
            'stop_reason': stop_reason,
            'usage': {
                'input_tokens': response.usage.prompt_tokens,
                'output_tokens': response.usage.completion_tokens
            }
        }

    def format_stream_start(self, model_name: str) -> Optional[str]:
        """发送 Anthropic 消息开始事件"""
        start_data = {
            'type': 'message_start',
            'message': {
                'id': 'msg_' + str(int(time.time())),
                'type': 'message',
                'role': 'assistant',
                'model': model_name
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

        流程：
        1. 流式输出 content_block_delta 等事件（实时）
        2. 遇到 finish_reason chunk 时缓冲，不立即输出
        3. 继续消费剩余 chunk，累积 usage
        4. 流结束后，将累积的 usage 注入 finish chunk 并输出
        """
        def generate():
            accumulated_usage = {}
            pending_finish_chunk = None

            try:
                # 发送 message_start
                start_event = self.format_stream_start(model_name)
                if start_event:
                    yield start_event

                for chunk in chunks:
                    # 从每个 chunk 累积 usage 信息
                    if chunk.usage:
                        for k, v in chunk.usage.items():
                            accumulated_usage[k] = v

                    if chunk.finish_reason:
                        # 缓冲 finish chunk，等待可能的 usage chunk
                        pending_finish_chunk = chunk
                        continue

                    # 跳过纯 usage chunk（其数据已累积，将合并到 finish chunk）
                    if chunk.event_type == StreamEventType.USAGE:
                        continue

                    # 实时输出内容 chunk
                    formatted = self.format_stream_chunk(chunk)
                    if formatted:
                        yield formatted

                # 流结束，输出缓冲的 finish chunk（带累积 usage）
                if pending_finish_chunk:
                    if accumulated_usage:
                        pending_finish_chunk.usage = accumulated_usage
                    formatted = self.format_stream_chunk(pending_finish_chunk)
                    if formatted:
                        yield formatted

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
