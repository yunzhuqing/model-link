"""
OpenAI Chat Completions 适配器
处理 /v1/chat/completions 格式的请求和响应转换。
"""
import json
from typing import Optional

from .base import BaseAdapter
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.providers.openai_provider import parse_openai_request


class OpenAIChatAdapter(BaseAdapter):
    """
    OpenAI Chat Completions API 适配器

    负责：
    - 将 OpenAI /v1/chat/completions 请求格式解析为 ChatRequest
    - 将 ChatResponse 转换为 OpenAI 响应格式
    - 处理 OpenAI 格式的流式响应
    """

    def parse_request(self, data: dict) -> ChatRequest:
        """
        解析 OpenAI Chat Completions 格式的请求。

        请求格式:
        {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello!"}
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
            "stream": false,
            "tools": [...],
            ...
        }
        """
        return parse_openai_request(data)

    def format_response(self, response: ChatResponse) -> dict:
        """
        将 ChatResponse 转换为 OpenAI Chat Completions 响应格式。

        响应格式:
        {
            "id": "chatcmpl-xxx",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4o",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "..."},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30
            }
        }
        """
        choices = []
        for choice in response.choices:
            choice_dict = {
                'index': choice.index,
                'finish_reason': choice.finish_reason.value
            }

            if choice.message:
                msg = choice.message
                content = msg.get_text_content()

                choice_dict['message'] = {
                    'role': msg.role.value,
                    'content': content
                }

                if choice.reasoning_content:
                    choice_dict['message']['reasoning_content'] = choice.reasoning_content

                if choice.tool_calls:
                    choice_dict['message']['tool_calls'] = [
                        {
                            'id': tc.id,
                            'type': tc.call_type,
                            'function': {
                                'name': tc.name,
                                'arguments': json.dumps(tc.arguments, ensure_ascii=False)
                            }
                        }
                        for tc in choice.tool_calls
                    ]

            choices.append(choice_dict)

        return {
            'id': response.id,
            'object': 'chat.completion',
            'created': response.created,
            'model': response.model,
            'choices': choices,
            'usage': {
                'prompt_tokens': response.usage.prompt_tokens,
                'completion_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            }
        }

    def format_stream_chunk(self, chunk: StreamChunk) -> str:
        """将 StreamChunk 转换为 OpenAI SSE 格式"""
        return chunk.to_sse("openai")

    def format_stream_end(self) -> str:
        """OpenAI 流式结束标记"""
        return "data: [DONE]\n\n"

    def format_stream_error(self, error: Exception) -> str:
        """将错误转换为 OpenAI 格式的流式错误事件"""
        from app.middleware.gateway_service import ProviderError

        if isinstance(error, ProviderError) and error.error_data:
            return f"event: error\ndata: {json.dumps(error.error_data)}\n\n"

        error_data = {'error': {'message': str(error), 'type': 'server_error'}}
        return f"event: error\ndata: {json.dumps(error_data)}\n\n"
