"""
OpenAI Responses API 适配器
处理 /v1/responses 格式的请求和响应转换。

OpenAI Responses API 是 OpenAI 的新一代 API 格式，
与 Chat Completions 相比有以下不同：
- 使用 `input` 替代 `messages`
- 使用 `instructions` 替代 system message
- 使用 `max_output_tokens` 替代 `max_tokens`
- 响应使用 `output` 替代 `choices`
- 流式事件使用更细粒度的事件类型
"""
import json
import time
import uuid
from typing import Optional

from .base import BaseAdapter
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.messages import Message, MessageRole, ContentBlock
from app.abstraction.tools import ToolDefinition, ToolParameter, ToolType


class OpenAIResponsesAdapter(BaseAdapter):
    """
    OpenAI Responses API 适配器

    负责：
    - 将 OpenAI /v1/responses 请求格式解析为 ChatRequest
    - 将 ChatResponse 转换为 OpenAI Responses 格式
    - 处理 OpenAI Responses 格式的流式响应
    """

    def parse_request(self, data: dict) -> ChatRequest:
        """
        解析 OpenAI Responses 格式的请求。

        请求格式:
        {
            "model": "gpt-4o",
            "input": "Tell me a joke",
            // 或者数组格式:
            "input": [
                {"role": "user", "content": "Tell me a joke"}
            ],
            "instructions": "You are a helpful assistant.",
            "temperature": 0.7,
            "max_output_tokens": 1000,
            "stream": false,
            "tools": [...]
        }
        """
        messages = []

        # 处理 instructions（系统提示）
        if 'instructions' in data:
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content=data['instructions']
            ))

        # 处理 input
        input_data = data.get('input', '')

        if isinstance(input_data, str):
            # 简单字符串输入
            messages.append(Message(
                role=MessageRole.USER,
                content=input_data
            ))
        elif isinstance(input_data, list):
            # 数组格式输入（类似 messages）
            for item in input_data:
                if isinstance(item, str):
                    messages.append(Message(
                        role=MessageRole.USER,
                        content=item
                    ))
                elif isinstance(item, dict):
                    role_str = item.get('role', 'user')
                    role = MessageRole(role_str)
                    content = item.get('content', '')

                    if isinstance(content, list):
                        blocks = []
                        for block in content:
                            block_type = block.get('type', 'input_text')

                            if block_type in ('input_text', 'text'):
                                blocks.append(ContentBlock.from_text(block.get('text', '')))
                            elif block_type in ('input_image', 'image'):
                                # Handle image content
                                if 'image_url' in block:
                                    url = block['image_url'].get('url', '')
                                    if url.startswith('data:'):
                                        parts = url.split(',')
                                        media_type = parts[0].replace('data:', '').replace(';base64', '')
                                        data_str = parts[1] if len(parts) > 1 else ''
                                        blocks.append(ContentBlock.from_image_base64(data_str, media_type))
                                    else:
                                        blocks.append(ContentBlock.from_image_url(url))
                                elif 'source' in block:
                                    source = block['source']
                                    if source.get('type') == 'base64':
                                        blocks.append(ContentBlock.from_image_base64(
                                            source.get('data', ''),
                                            source.get('media_type', 'image/jpeg')
                                        ))
                                    elif source.get('type') == 'url':
                                        blocks.append(ContentBlock.from_image_url(source.get('url', '')))
                            elif block_type == 'input_audio':
                                if 'input_audio' in block:
                                    audio_data = block['input_audio']
                                    blocks.append(ContentBlock.from_audio_base64(
                                        audio_data.get('data', ''),
                                        f"audio/{audio_data.get('format', 'wav')}"
                                    ))
                            elif block_type == 'input_file':
                                if 'file_url' in block:
                                    blocks.append(ContentBlock.from_file_url(block['file_url'].get('url', '')))

                        content = blocks if blocks else content
                    
                    # Handle tool result messages
                    tool_call_id = item.get('call_id') or item.get('tool_call_id')
                    name = item.get('name')

                    messages.append(Message(
                        role=role,
                        content=content,
                        name=name,
                        tool_call_id=tool_call_id
                    ))

        # 处理工具定义
        tools = []
        for tool_data in data.get('tools', []):
            tool_type = tool_data.get('type', 'function')

            if tool_type == 'function':
                func = tool_data.get('function', tool_data)
                name = func.get('name', '')
                description = func.get('description', '')
                params_schema = func.get('parameters', {})

                parameters = []
                properties = params_schema.get('properties', {})
                required = params_schema.get('required', [])

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
            elif tool_type == 'web_search_preview':
                # Web search tool - pass through as metadata
                pass

        # 收集额外参数
        known_keys = {
            'model', 'input', 'instructions', 'temperature', 'top_p',
            'max_output_tokens', 'stream', 'tools', 'tool_choice',
            'stop', 'presence_penalty', 'frequency_penalty', 'user',
            'metadata', 'store', 'truncation'
        }
        metadata = {k: v for k, v in data.items() if k not in known_keys}

        return ChatRequest(
            messages=messages,
            model=data.get('model', ''),
            temperature=data.get('temperature'),
            top_p=data.get('top_p'),
            max_tokens=data.get('max_output_tokens'),
            stream=data.get('stream', False),
            tools=tools,
            tool_choice=data.get('tool_choice'),
            stop=data.get('stop'),
            presence_penalty=data.get('presence_penalty'),
            frequency_penalty=data.get('frequency_penalty'),
            user=data.get('user'),
            metadata=metadata
        )

    def format_response(self, response: ChatResponse) -> dict:
        """
        将 ChatResponse 转换为 OpenAI Responses API 格式。

        响应格式:
        {
            "id": "resp_xxx",
            "object": "response",
            "created_at": 1234567890,
            "model": "gpt-4o",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_xxx",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "Hello!"}
                    ]
                }
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30
            }
        }
        """
        output = []

        for choice in response.choices:
            if choice.message:
                content_items = []
                text = choice.message.get_text_content()

                if text:
                    content_items.append({
                        'type': 'output_text',
                        'text': text,
                        'annotations': []
                    })

                if choice.tool_calls:
                    for tc in choice.tool_calls:
                        output.append({
                            'type': 'function_call',
                            'id': tc.id,
                            'call_id': tc.id,
                            'name': tc.name,
                            'arguments': json.dumps(tc.arguments, ensure_ascii=False),
                            'status': 'completed'
                        })

                if content_items:
                    output.append({
                        'type': 'message',
                        'id': f"msg_{uuid.uuid4().hex[:12]}",
                        'role': 'assistant',
                        'status': 'completed',
                        'content': content_items
                    })

        # Map finish_reason to status
        status = 'completed'
        if response.choices:
            fr = response.choices[0].finish_reason.value
            status_map = {
                'stop': 'completed',
                'length': 'incomplete',
                'tool_calls': 'completed',
                'content_filter': 'failed',
            }
            status = status_map.get(fr, 'completed')

        return {
            'id': response.id.replace('chatcmpl-', 'resp_') if response.id.startswith('chatcmpl-') else response.id,
            'object': 'response',
            'created_at': response.created,
            'model': response.model,
            'status': status,
            'output': output,
            'usage': {
                'input_tokens': response.usage.prompt_tokens,
                'output_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            }
        }

    def format_stream_chunk(self, chunk: StreamChunk) -> str:
        """
        将 StreamChunk 转换为 OpenAI Responses 流式事件格式。

        事件类型:
        - response.output_text.delta: 文本增量
        - response.function_call_arguments.delta: 工具调用参数增量
        - response.completed: 完成事件
        """
        events = []

        if chunk.delta_content:
            event_data = {
                'type': 'response.output_text.delta',
                'output_index': 0,
                'content_index': 0,
                'delta': chunk.delta_content
            }
            events.append(f"event: response.output_text.delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n")

        if chunk.tool_calls:
            for tc in chunk.tool_calls:
                func = tc.get('function', {})
                args = func.get('arguments', '')
                if args:
                    event_data = {
                        'type': 'response.function_call_arguments.delta',
                        'output_index': 0,
                        'delta': args
                    }
                    events.append(f"event: response.function_call_arguments.delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n")

        if chunk.finish_reason:
            event_data = {
                'type': 'response.completed',
                'response': {
                    'id': chunk.id.replace('chatcmpl-', 'resp_') if chunk.id.startswith('chatcmpl-') else chunk.id,
                    'object': 'response',
                    'status': 'completed',
                    'model': chunk.model
                }
            }
            events.append(f"event: response.completed\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n")

        return ''.join(events) if events else ''

    def format_stream_start(self, model_name: str) -> Optional[str]:
        """发送 Responses API 流式开始事件"""
        response_id = f"resp_{uuid.uuid4().hex[:12]}"
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"

        events = []

        # response.created
        created_data = {
            'type': 'response.created',
            'response': {
                'id': response_id,
                'object': 'response',
                'created_at': int(time.time()),
                'model': model_name,
                'status': 'in_progress',
                'output': []
            }
        }
        events.append(f"event: response.created\ndata: {json.dumps(created_data)}\n\n")

        # response.output_item.added
        item_data = {
            'type': 'response.output_item.added',
            'output_index': 0,
            'item': {
                'type': 'message',
                'id': msg_id,
                'role': 'assistant',
                'status': 'in_progress',
                'content': []
            }
        }
        events.append(f"event: response.output_item.added\ndata: {json.dumps(item_data)}\n\n")

        # response.content_part.added
        part_data = {
            'type': 'response.content_part.added',
            'output_index': 0,
            'content_index': 0,
            'part': {
                'type': 'output_text',
                'text': '',
                'annotations': []
            }
        }
        events.append(f"event: response.content_part.added\ndata: {json.dumps(part_data)}\n\n")

        return ''.join(events)

    def format_stream_end(self) -> str:
        """Responses API 流式结束标记"""
        return "data: [DONE]\n\n"

    def format_stream_error(self, error: Exception) -> str:
        """将错误转换为 Responses API 格式的流式错误事件"""
        from app.middleware.gateway_service import ProviderError

        if isinstance(error, ProviderError) and error.error_data:
            error_event = {
                'type': 'error',
                'error': error.error_data
            }
        else:
            error_event = {
                'type': 'error',
                'error': {
                    'type': 'server_error',
                    'message': str(error)
                }
            }

        return f"event: error\ndata: {json.dumps(error_event)}\n\n"
