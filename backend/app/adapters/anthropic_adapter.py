"""
Anthropic Messages 适配器
处理 /v1/messages 格式的请求和响应转换。
"""
import json
import time
from typing import Optional

from .base import BaseAdapter
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.messages import Message, MessageRole, ContentBlock
from app.abstraction.tools import ToolDefinition, ToolParameter, ToolType


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
        return "event: message_stop\ndata: {}\n\n"

    def format_stream_error(self, error: Exception) -> str:
        """将错误转换为 Anthropic 格式的流式错误事件"""
        from app.middleware.gateway_service import ProviderError

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
