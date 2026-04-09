"""
阿里云百炼供应商基础实现 (Bailian Base Provider)
实现阿里云百炼模型的 API 调用。

百炼 API 采用 OpenAI 兼容格式。
百炼 API 文档：https://help.aliyun.com/document_detail/2712195.html

图像生成支持：
通义千问图像生成模型（qwen-image-2.0-pro）通过专用 Dashscope API
进行图像生成和编辑，兼容 /v1/responses image_generation 工具。
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid
import sys

from ..base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse, EmbeddingData, EmbeddingUsage
from app.providers.openai_provider import OpenAIProvider
from .image_generation import (
    is_qwen_image_model,
    has_image_generation_tool,
    execute_qwen_image_generation,
    stream_image_generation,
)


class BailianProvider(OpenAIProvider):
    """
    阿里云百炼供应商实现

    阿里云百炼是一个 AI 模型服务平台，提供多种大语言模型的 API 调用。
    百炼 API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。

    额外支持：
    - 通义千问图像生成/编辑模型（qwen-image-2.0-pro）
    - 百炼特有的 reasoning_content 字段
    - 百炼特有的 cache tokens 字段
    - 多模态嵌入 API
    """

    PROVIDER_TYPE: str = "bailian"

    # 百炼支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
        ProviderCapability.CACHE,
    ]

    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 百炼多模态嵌入 API 的基础 URL（非 OpenAI 兼容格式）
    BAILIAN_MULTIMODAL_EMBEDDING_URL = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    )

    # 百炼支持的模型列表
    SUPPORTED_MODELS = {
        # Qwen 系列模型
        "qwen-turbo": {
            "description": "通义千问超大规模语言模型，快速响应",
            "context_size": 8192,
            "supports_vision": False,
        },
        "qwen-plus": {
            "description": "通义千问超大规模语言模型，能力更强",
            "context_size": 32768,
            "supports_vision": False,
        },
        "qwen-max": {
            "description": "通义千问超大规模语言模型，能力最强",
            "context_size": 32768,
            "supports_vision": False,
        },
        "qwen-long": {
            "description": "通义千问长文本模型",
            "context_size": 10000,
            "supports_vision": False,
        },
        "qwen-vl-plus": {
            "description": "通义千问视觉模型",
            "context_size": 8192,
            "supports_vision": True,
        },
        "qwen-vl-max": {
            "description": "通义千问视觉模型，能力更强",
            "context_size": 8192,
            "supports_vision": True,
        },
        "qwen-audio-turbo": {
            "description": "通义千问音频模型",
            "context_size": 8192,
            "supports_audio": True,
        },
        "qwen-image-2.0-pro": {
            "description": "通义千问图像生成与编辑模型，支持文生图和图生图",
            "context_size": 0,
            "supports_vision": True,
        },
        # DeepSeek 系列
        "deepseek-v3": {
            "description": "DeepSeek V3 模型",
            "context_size": 64000,
            "supports_vision": False,
        },
        "deepseek-r1": {
            "description": "DeepSeek R1 推理模型",
            "context_size": 64000,
            "supports_vision": False,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化百炼供应商

        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        super().__init__(config)

    # ==================== 图像生成检测 ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model is a Qwen image generation/editing model."""
        return is_qwen_image_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_image_generation_tool(request)

    # ==================== 请求准备 ====================

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备百炼请求数据

        复用 OpenAI 格式，添加百炼特有参数。

        Args:
            request: 对话请求对象

        Returns:
            百炼请求字典
        """
        # 复用父类 OpenAI 格式
        data = super().prepare_request(request)

        # 百炼特有参数从 metadata 中提取
        if "enable_search" in request.metadata:
            data["enable_search"] = request.metadata["enable_search"]

        # 百炼特有：根据模型是否支持思维和 reasoning_effort 设置 enable_thinking
        reasoning_effort = request.reasoning_effort or 'none'
        if request.metadata.get('support_thinking', False):
            data["enable_thinking"] = reasoning_effort != 'none'
        elif reasoning_effort != 'none':
            data["enable_thinking"] = True

        # 打印请求体到控制台
        print("\n" + "=" * 50, file=sys.stderr)
        print("[Bailian Request Body]", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)
        print("=" * 50 + "\n", file=sys.stderr)

        return data

    # ==================== 非流式接口 ====================

    def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行对话/图像生成请求

        如果模型是图像生成模型（qwen-image-2.0-pro），则走专用 API 路径。
        否则走 OpenAI 兼容格式的对话路径。

        Args:
            request: 对话请求对象

        Returns:
            对话/图像生成响应对象
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            return execute_qwen_image_generation(
                api_key=self.config.api_key,
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
            )

        # 标准对话路径
        request_data = self.prepare_request(request)
        request_data["stream"] = False

        url = f"{self.config.base_url}/chat/completions"

        try:
            response = self.client.post(url, json=request_data)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(
                        f"Bailian API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"Bailian API error ({response.status_code}): {response.text}"
                    )

            response_data = response.json()
            return self.parse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Bailian API error: {str(e)}")

    # ==================== 响应解析 ====================

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析百炼响应数据

        复用 OpenAI 格式解析，处理百炼特有字段。

        Args:
            response_data: 响应数据
            model: 模型名称

        Returns:
            对话响应对象
        """
        # 复用父类 OpenAI 格式解析
        response = super().parse_response(response_data, model)
        response.provider = self.PROVIDER_TYPE

        # 处理百炼特有的 reasoning_content
        for i, choice_data in enumerate(response_data.get("choices", [])):
            message_data = choice_data.get("message", {})
            if "reasoning_content" in message_data:
                response.choices[i].reasoning_content = message_data["reasoning_content"]

        # 处理百炼特有的 cache tokens
        usage_data = response_data.get("usage", {})
        if "cache_read_tokens" in usage_data:
            response.usage.cache_read_tokens = usage_data["cache_read_tokens"]
        if "cache_write_tokens" in usage_data:
            response.usage.cache_write_tokens = usage_data["cache_write_tokens"]

        return response

    # ==================== 流式接口 ====================

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """
        执行流式对话/图像生成请求

        如果模型是图像生成模型，则使用专用流式图像生成路径（模拟 SSE 事件流）。
        否则走 OpenAI 兼容格式的流式对话路径。

        Args:
            request: 对话请求对象

        Yields:
            流式响应块
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            yield from stream_image_generation(self.chat, request)
            return

        # 准备请求数据
        request_data = self.prepare_request(request)
        request_data["stream"] = True
        # Request usage info in the final streaming chunk
        request_data["stream_options"] = {"include_usage": True}

        # 百炼特有：增量输出
        request_data["incremental_output"] = True

        url = f"{self.config.base_url}/chat/completions"
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        try:
            with self.client.stream("POST", url, json=request_data) as response:
                if response.status_code >= 400:
                    error_text = ""
                    for chunk in response.iter_bytes():
                        if chunk:
                            error_text += chunk.decode('utf-8')
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(
                            f"Bailian API error ({response.status_code}): "
                            f"{json.dumps(error_data, ensure_ascii=False)}"
                        )
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"Bailian API error ({response.status_code}): {error_text}"
                        )

                for line in response.iter_lines():
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
            raise RuntimeError(f"Bailian streaming API error: {str(e)}")

    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """
        解析流式响应块

        复用 OpenAI 格式，处理百炼特有字段。

        Args:
            data: 响应数据
            response_id: 响应 ID
            model: 模型名称

        Returns:
            流式响应块，如果无效返回 None
        """
        chunk = super()._parse_stream_chunk(data, response_id, model)

        if chunk:
            # 处理百炼特有的 reasoning_content
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "reasoning_content" in delta:
                    chunk.delta_reasoning_content = delta["reasoning_content"]

        return chunk

    # ==================== 嵌入接口 ====================

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        执行嵌入请求

        对于文本嵌入，使用 OpenAI 兼容格式（继承父类）。
        对于多模态嵌入，使用百炼专用 API 格式。

        百炼多模态嵌入 API 格式：
        POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding
        {
            "model": "tongyi-embedding-vision-plus",
            "input": {
                "contents": [
                    {"text": "文本内容"},
                    {"image": "https://..."},
                    {"video": "https://..."},
                    {"multi_images": ["https://...", "https://..."]}
                ]
            }
        }

        Args:
            request: 嵌入请求对象

        Returns:
            嵌入响应对象
        """
        if not request.is_multimodal:
            return super().embed(request)

        # 多模态嵌入使用百炼专用 API
        contents = self._convert_messages_to_bailian_contents(request.messages)

        request_data = {
            "model": request.model,
            "input": {
                "contents": contents
            },
            "parameters": {
                "enable_fusion": True
            }
        }

        print("\n" + "=" * 50, file=sys.stderr)
        print("[Bailian Multimodal Embedding Request Body]", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print(json.dumps(request_data, ensure_ascii=False, indent=2), file=sys.stderr)
        print("=" * 50 + "\n", file=sys.stderr)

        url = self.BAILIAN_MULTIMODAL_EMBEDDING_URL

        try:
            response = self.client.post(url, json=request_data)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(
                        f"Bailian multimodal embedding API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"Bailian multimodal embedding API error ({response.status_code}): "
                        f"{response.text}"
                    )

            response.raise_for_status()
            response_data = response.json()
            return self._parse_bailian_multimodal_embedding_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Bailian multimodal embedding API error: {str(e)}")

    def _convert_messages_to_bailian_contents(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将 OpenAI 格式的 messages 转换为百炼多模态嵌入的 contents 格式。

        输入格式 (OpenAI messages):
        [{"role": "user", "content": [
            {"type": "text", "text": "描述"},
            {"type": "image_url", "image_url": {"url": "https://..."}},
            {"type": "video_url", "video_url": {"url": "https://..."}}
        ]}]

        输出格式 (百炼 contents):
        [
            {"text": "描述"},
            {"image": "https://..."},
            {"video": "https://..."}
        ]

        Args:
            messages: OpenAI 格式的消息列表

        Returns:
            百炼格式的 contents 列表
        """
        contents = []

        for message in messages:
            content = message.get("content", [])

            if isinstance(content, str):
                contents.append({"text": content})
                continue

            if isinstance(content, list):
                image_urls = []
                for item in content:
                    item_type = item.get("type", "text")

                    if item_type == "text":
                        text = item.get("text", "")
                        if text:
                            contents.append({"text": text})
                    elif item_type == "image_url":
                        image_url = item.get("image_url", {})
                        url = image_url.get("url", "")
                        if url:
                            image_urls.append(url)
                    elif item_type == "video_url":
                        video_url = item.get("video_url", {})
                        url = video_url.get("url", "")
                        if url:
                            contents.append({"video": url})

                # 多张图片使用 multi_images，单张使用 image
                if len(image_urls) > 1:
                    contents.append({"multi_images": image_urls})
                elif len(image_urls) == 1:
                    contents.append({"image": image_urls[0]})

        return contents

    def _parse_bailian_multimodal_embedding_response(
        self, data: Dict[str, Any], model: str
    ) -> EmbeddingResponse:
        """
        解析百炼多模态嵌入响应。

        百炼响应格式:
        {
            "output": {
                "embeddings": [
                    {"index": 0, "embedding": [...], "type": "text"},
                    {"index": 1, "embedding": [...], "type": "image"}
                ]
            },
            "usage": {
                "input_tokens": 10,
                "image_tokens": 896
            }
        }

        Args:
            data: 百炼响应数据
            model: 模型名称

        Returns:
            统一的嵌入响应对象
        """
        embedding_data = []
        output = data.get("output", {})

        for item in output.get("embeddings", []):
            embedding_data.append(EmbeddingData(
                index=item.get("index", 0),
                embedding=item.get("embedding", []),
                object="embedding"
            ))

        usage_data = data.get("usage", {})
        input_tokens = usage_data.get("input_tokens", 0)
        image_tokens = usage_data.get("image_tokens", 0)
        video_tokens = usage_data.get("video_tokens", 0)
        total_tokens = input_tokens + image_tokens + video_tokens

        usage = EmbeddingUsage(
            prompt_tokens=total_tokens,
            total_tokens=total_tokens
        )

        return EmbeddingResponse(
            object="list",
            data=embedding_data,
            model=model,
            usage=usage
        )

    # ==================== 模型列表 ====================

    def list_models(self) -> List[Dict[str, Any]]:
        """
        列出可用模型

        Returns:
            模型列表
        """
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "bailian",
                "permission": [],
                "root": model_name,
                "parent": None,
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
                "supports_audio": info.get("supports_audio", False),
            })
        return models
