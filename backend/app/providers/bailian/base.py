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
import logging

from ..base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse
from app.providers.openai_provider import OpenAIProvider
from .image_generation import (
    is_qwen_image_model,
    has_image_generation_tool,
    execute_qwen_image_generation,
    stream_image_generation,
)
from .video_generation import (
    is_happyhorse_video_model,
    has_video_generation_tool,
    execute_happyhorse_video_generation,
    stream_video_generation,
)
from .embedding import execute_bailian_multimodal_embed
from .rerank import execute_bailian_text_rerank, execute_bailian_multimodal_rerank
from app.abstraction.rerank import RerankRequest, RerankResponse


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

    # 百炼文本 Rerank API 的默认 URL（compatible-api 模式，注意与 compatible-mode 不同）
    BAILIAN_TEXT_RERANK_URL = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"

    # 百炼多模态 Rerank API 的默认 URL（Dashscope 专用格式）
    BAILIAN_MULTIMODAL_RERANK_URL = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/"
        "text-rerank/text-rerank"
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
        "z-image-turbo": {
            "description": "快速文生图模型，仅支持文本输入，使用 aspect_ratio 尺寸参数",
            "context_size": 0,
            "supports_vision": False,
        },
        # Happyhorse 视频生成系列
        "happyhorse-1.0-t2v": {
            "description": "文生视频模型，根据文本描述生成视频",
            "context_size": 0,
            "supports_vision": False,
        },
        "happyhorse-1.0-i2v": {
            "description": "图生视频模型，根据首帧图片和文本描述生成视频",
            "context_size": 0,
            "supports_vision": True,
        },
        "happyhorse-1.0-r2v": {
            "description": "参考对象生视频模型，根据参考图片和文本描述生成视频",
            "context_size": 0,
            "supports_vision": True,
        },
        "happyhorse-1.0-video-edit": {
            "description": "视频编辑模型，根据文本描述对视频进行编辑",
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
            self._multimodal_embedding_url = self.BAILIAN_MULTIMODAL_EMBEDDING_URL
            self._text_rerank_url = self.BAILIAN_TEXT_RERANK_URL
            self._multimodal_rerank_url = self.BAILIAN_MULTIMODAL_RERANK_URL
        else:
            base = config.base_url.rstrip("/")
            # 提取基础域名（去掉 /compatible-mode/v1 后缀，如果有的话）
            if base.endswith("/compatible-mode/v1"):
                domain = base[: -len("/compatible-mode/v1")]
            else:
                domain = base
                # 如果用户提供了基础域名（如 https://xxxx），自动追加 /compatible-mode/v1 后缀
                config.base_url = base + "/compatible-mode/v1"
            # 多模态嵌入/Rerank URL 根据基础域名动态生成
            self._multimodal_embedding_url = (
                f"{domain}/api/v1/services/embeddings/"
                "multimodal-embedding/multimodal-embedding"
            )
            # 文本 Rerank 走 compatible-api 路径（非 compatible-mode）
            self._text_rerank_url = f"{domain}/compatible-api/v1/reranks"
            self._multimodal_rerank_url = (
                f"{domain}/api/v1/services/rerank/text-rerank/text-rerank"
            )
        super().__init__(config)

    # ==================== 图像/视频生成检测 ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model is a Qwen image generation/editing model."""
        return is_qwen_image_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_image_generation_tool(request)

    def is_video_generation_model(self, model: str) -> bool:
        """Check if the model is a Happyhorse video generation model."""
        return is_happyhorse_video_model(model)

    def _has_video_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains a video_generation tool."""
        return has_video_generation_tool(request)

    def _get_dashscope_domain(self) -> Optional[str]:
        """Extract the Dashscope domain from base_url for video generation API calls."""
        base_url = getattr(self.config, 'base_url', '') or ''
        if 'dashscope.aliyuncs.com' in base_url:
            if '://' in base_url:
                protocol, rest = base_url.split('://', 1)
                host = rest.split('/', 1)[0]
                return f"{protocol}://{host}"
        return None

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

        model_has_thinking = 'thinking' in request.model.lower()
        has_reasoning_effort = bool(request.reasoning_effort)

        if model_has_thinking or has_reasoning_effort:
            data["enable_thinking"] = True
            if not has_reasoning_effort:
                data["reasoning_effort"] = "medium"
        else:
            data["enable_thinking"] = False

        # 打印请求体到控制台
        logging.debug("Prepared Bailian request data: %s", json.dumps(data, ensure_ascii=False))

        return data

    def _content_block_to_openai(self, block) -> Dict[str, Any]:
        from app.abstraction.messages import ContentType

        if block.type == ContentType.VIDEO_URL and block.video_fps is not None:
            item = {"type": "video_url", "video_url": {"url": block.url}}
            item["fps"] = int(block.video_fps)
            return item
        return super()._content_block_to_openai(block)

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

        if self.is_video_generation_model(request.model) or self._has_video_generation_tool(request):
            return execute_happyhorse_video_generation(
                api_key=self.config.api_key,
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                domain=self._get_dashscope_domain(),
            )

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
            with self._trace_call(request.model, input_data=request_data) as child_span:
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
                if child_span:
                    child_span.log_output(response_data)
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

        # Extract cached_tokens from prompt_tokens_details (OpenAI-compatible format)
        # Some models (e.g. GLM) return cached tokens here instead of cache_read_tokens
        prompt_details = usage_data.get("prompt_tokens_details")
        if isinstance(prompt_details, dict):
            cached = prompt_details.get("cached_tokens", 0) or 0
            if cached and not response.usage.cached_tokens and not response.usage.cache_read_tokens:
                response.usage.cached_tokens = cached

        # Extract reasoning_tokens from completion_tokens_details
        completion_details = usage_data.get("completion_tokens_details")
        if isinstance(completion_details, dict):
            reasoning = completion_details.get("reasoning_tokens", 0) or 0
            if reasoning and not response.usage.reasoning_tokens:
                response.usage.reasoning_tokens = reasoning

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

        if self.is_video_generation_model(request.model) or self._has_video_generation_tool(request):
            # Inject api_key and domain into metadata for the streaming function
            request.metadata["_api_key"] = self.config.api_key
            request.metadata["_domain"] = self._get_dashscope_domain()
            yield from stream_video_generation(self.chat, request)
            return

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
            with self._trace_call(request.model, input_data=request_data), \
                 self.client.stream("POST", url, json=request_data) as response:
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

        根据模型配置中的能力标志（support_image / support_video / support_audio）
        决定是否走多模态嵌入 API：
        - 若模型支持图片/视频/音频输入（由管理员在模型配置中勾选），则走百炼专用多模态嵌入 API
        - 否则走 OpenAI 兼容格式的纯文本嵌入 API（继承父类）

        能力标志由 GatewayService 从数据库读取后注入 request.metadata：
            metadata['support_image'], metadata['support_video'], metadata['support_audio']

        Args:
            request: 嵌入请求对象

        Returns:
            嵌入响应对象
        """
        is_multimodal_model = (
            request.metadata.get('support_image', False)
            or request.metadata.get('support_video', False)
            or request.metadata.get('support_audio', False)
        )

        if not is_multimodal_model:
            return super().embed(request)

        return execute_bailian_multimodal_embed(
            api_key=self.config.api_key,
            multimodal_embedding_url=self._multimodal_embedding_url,
            request=request,
        )

    # ==================== Rerank 接口 ====================

    def rerank(self, request: RerankRequest) -> RerankResponse:
        """
        执行 Rerank 请求。

        - 非多模态（纯文本）：走 /compatible-mode/v1/reranks（兼容模式）
        - 多模态（含图片/视频）：走 Dashscope 专用 API

        Args:
            request: Rerank 请求对象

        Returns:
            Rerank 响应对象
        """
        if request.is_multimodal:
            return execute_bailian_multimodal_rerank(
                api_key=self.config.api_key,
                multimodal_rerank_url=self._multimodal_rerank_url,
                request=request,
            )

        # 文本 Rerank：使用 compatible-api 模式 URL（https://xxx/compatible-api/v1/reranks）
        return execute_bailian_text_rerank(
            api_key=self.config.api_key,
            rerank_url=self._text_rerank_url,
            request=request,
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
