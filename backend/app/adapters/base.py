"""
适配器基类 (Base Adapter)
定义所有 API 格式适配器必须实现的接口。
"""
from abc import ABC, abstractmethod
from typing import Generator, Optional
import json

from flask import Response

from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.middleware.gateway_service import GatewayServiceError, ProviderError


class BaseAdapter(ABC):
    """
    API 格式适配器基类

    每个适配器负责一种 API 格式的转换：
    - parse_request: 外部格式 → ChatRequest
    - format_response: ChatResponse → 外部格式
    - create_stream_response: StreamChunk 生成器 → HTTP 流式响应
    """

    @abstractmethod
    def parse_request(self, data: dict) -> ChatRequest:
        """
        将外部 API 格式解析为统一的 ChatRequest。

        Args:
            data: 请求 JSON 数据

        Returns:
            ChatRequest 对象
        """
        pass

    @abstractmethod
    def format_response(self, response: ChatResponse) -> dict:
        """
        将统一的 ChatResponse 转换为外部 API 格式。

        Args:
            response: 统一的响应对象

        Returns:
            外部 API 格式的响应字典
        """
        pass

    @abstractmethod
    def format_stream_chunk(self, chunk: StreamChunk) -> str:
        """
        将 StreamChunk 转换为 SSE 格式字符串。

        Args:
            chunk: 流式响应块

        Returns:
            SSE 格式字符串
        """
        pass

    @abstractmethod
    def format_stream_end(self) -> str:
        """
        生成流式结束标记。

        Returns:
            SSE 格式的结束标记字符串
        """
        pass

    @abstractmethod
    def format_stream_error(self, error: Exception) -> str:
        """
        将错误转换为流式错误事件。

        Args:
            error: 异常对象

        Returns:
            SSE 格式的错误事件字符串
        """
        pass

    def create_stream_response(
        self,
        chunks: Generator[StreamChunk, None, None],
        model_name: str
    ) -> Response:
        """
        从 StreamChunk 生成器创建 HTTP 流式响应。

        Args:
            chunks: StreamChunk 生成器
            model_name: 模型名称（用于错误处理）

        Returns:
            Flask Response 对象
        """
        def generate():
            try:
                # 发送流式开始事件（子类可覆盖）
                start_event = self.format_stream_start(model_name)
                if start_event:
                    yield start_event

                for chunk in chunks:
                    yield self.format_stream_chunk(chunk)

                # 发送结束标记
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

    def format_stream_start(self, model_name: str) -> Optional[str]:
        """
        生成流式开始事件（可选）。
        默认返回 None，子类可覆盖。

        Args:
            model_name: 模型名称

        Returns:
            SSE 格式字符串或 None
        """
        return None
