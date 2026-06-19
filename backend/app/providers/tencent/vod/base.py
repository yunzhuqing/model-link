"""
腾讯云点播 AI 供应商基础实现 (TencentVOD Base Provider)
实现腾讯云点播 (VOD) AI 大模型的 API 调用。

腾讯云点播 AI API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。

配置说明:
- base_url: API 基础 URL（默认 https://text-aigc.vod-qcloud.com/v1）
- api_key:  聊天模型使用点播 AI API Key；
            图像/视频生成模型使用 "SecretId:SecretKey" 格式（腾讯云主账号/子账号密钥）

图像生成说明:
- 通过腾讯云点播 CreateAigcImageTask + DescribeTaskDetail API 实现
- 兼容 /v1/responses image_generation 工具
- extra_config["sub_app_id"]: 点播子应用 ID（可选）

视频生成说明:
- 通过腾讯云点播 CreateAigcVideoTask + DescribeTaskDetail API 实现
- 兼容 /v1/responses video_generation 工具
- 支持 Kling（GV）、HunyuanVideo 等模型

API 文档：
  聊天: https://text-aigc.vod-qcloud.com
  图像: https://cloud.tencent.com/document/product/266/73185
  视频: https://cloud.tencent.com/document/product/266/
"""
import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from ...openai_provider import OpenAIProvider
from ...base import ProviderConfig, ProviderCapability
from app.utils import REASONING_EFFORT_LOW, json_loads
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.messages import MessageRole, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from .image_generation import (
    is_tencentvod_image_model,
    has_image_generation_tool,
    execute_tencentvod_image_generation,
    stream_image_generation,
)
from .video_generation import (
    is_tencentvod_video_model,
    has_video_generation_tool,
    execute_tencentvod_video_generation,
    stream_video_generation,
)
from .threed_generation import (
    is_tencentvod_3d_model,
    has_3d_generation_tool,
    execute_tencentvod_3d_generation,
    stream_3d_generation,
)


import base64

def _safe_b64decode(s: str) -> bytes:
    """Decode a base64 string, stripping data URI prefix if present."""
    # Strip data URI prefix: "data:mime/type;base64,XXXX"
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    s = s.replace('-', '+').replace('_', '/')
    s += '=' * ((4 - len(s) % 4) % 4)
    return base64.b64decode(s)


class TencentVODProvider(OpenAIProvider):
    """
    腾讯云点播 AI 供应商实现

    腾讯云点播 AI 提供兼容 OpenAI chat/completions 格式的接口，
    继承 OpenAIProvider 直接复用其请求/响应逻辑。

    额外支持:
    - 腾讯云点播 AI 图像生成（GEM / Mingmou 等模型）
      通过 CreateAigcImageTask + DescribeTaskDetail API 实现，
      兼容 /v1/responses image_generation 工具。
    - 腾讯云点播 AI 视频生成（Kling / HunyuanVideo 等模型）
      通过 CreateAigcVideoTask + DescribeTaskDetail API 实现，
      兼容 /v1/responses video_generation 工具。

    配置:
        base_url:               https://text-aigc.vod-qcloud.com/v1（默认）
        api_key（聊天模型）:     腾讯云点播 AI API Key
        api_key（图像/视频生成）: "SecretId:SecretKey" 格式
        extra_config.sub_app_id: 点播子应用 ID（图像/视频生成可选）
    """

    PROVIDER_TYPE: str = "tencentvod"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
    ]

    # 腾讯云点播 AI 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://text-aigc.vod-qcloud.com/v1"

    # 腾讯云点播 AI 支持的模型列表
    SUPPORTED_MODELS = {
        "hunyuan-turbos-latest": {
            "description": "混元 Turbos Latest - 腾讯最新旗舰大模型",
            "context_size": 256000,
            "supports_vision": True,
        },
        "hunyuan-turbos-20250416": {
            "description": "混元 Turbos 20250416 - 腾讯旗舰大模型（固定版本）",
            "context_size": 256000,
            "supports_vision": True,
        },
        "hunyuan-turbo-latest": {
            "description": "混元 Turbo Latest - 高性能推理模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "hunyuan-pro": {
            "description": "混元 Pro - 高质量对话模型",
            "context_size": 128000,
            "supports_vision": False,
        },
        "hunyuan-lite": {
            "description": "混元 Lite - 轻量高速对话模型",
            "context_size": 256000,
            "supports_vision": False,
        },
        "hunyuan-standard": {
            "description": "混元 Standard - 标准对话模型",
            "context_size": 32000,
            "supports_vision": False,
        },
        "hunyuan-standard-256k": {
            "description": "混元 Standard 256K - 超长上下文对话模型",
            "context_size": 256000,
            "supports_vision": False,
        },
        "hunyuan-vision": {
            "description": "混元 Vision - 多模态视觉理解模型",
            "context_size": 8000,
            "supports_vision": True,
        },
        # 图像生成模型
        "GEM-2.5": {
            "description": "腾讯云点播 GEM 2.5 图像生成模型",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        "Mingmou-4.0": {
            "description": "腾讯云点播明眸 4.0 图像生成模型",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        "gpt-image-2": {
            "description": "GPT Image 2 图像生成模型（OG image2，支持 low/medium/high 质量）",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
        },
        # 视频生成模型 — 可灵 Kling (ModelName=Kling)
        "kling-v3-omni": {
            "description": "可灵 v3 旗舰版 Omni 视频生成模型（Kling 3.0-Omni）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v3-omini": {
            "description": "可灵 v3 Omini 视频生成模型（Kling 3.0-Omini）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v3": {
            "description": "可灵 v3 标准版视频生成模型（Kling 3.0）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v2.1-pro": {
            "description": "可灵 v2.1 Pro 视频生成模型（Kling 2.1-Pro）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v2.1-standard": {
            "description": "可灵 v2.1 Standard 视频生成模型（Kling 2.1-Standard）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v1.6-pro": {
            "description": "可灵 v1.6 Pro 视频生成模型（Kling 1.6-Pro）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v1.6-standard": {
            "description": "可灵 v1.6 Standard 视频生成模型（Kling 1.6-Standard）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "kling-v1.5-pro": {
            "description": "可灵 v1.5 Pro 视频生成模型（Kling 1.5-Pro）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        # 视频生成模型 — Google Veo (ModelName=GV)
        "veo-3.1-generate-001": {
            "description": "Google Veo 3.1 视频生成模型（GV 3.1）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "veo-3.1-fast-generate-001": {
            "description": "Google Veo 3.1 Fast 视频生成模型（GV 3.1-fast）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        # 视频生成模型 — 混元视频 Hunyuan
        "hy-video-v1.0": {
            "description": "混元视频 v1.0 视频生成模型（Hunyuan 1.0）",
            "context_size": 0,
            "supports_vision": True,
            "is_video_model": True,
        },
        "hunyuan-3d-2.0": {
            "description": "混元 3D 2.0 — image_generation(3d_panorama) / 3d_generation(3d_scene)",
            "context_size": 0,
            "supports_vision": True,
            "is_image_model": True,
            "is_3d_model": True,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化腾讯云点播 AI 供应商

        Args:
            config: 供应商配置
        """
        # 如果未指定 base_url，使用默认值
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        super().__init__(config)

    # ==================== 请求预处理 ====================

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据，针对 Gemini 模型默认设置 reasoning_effort 为 REASONING_EFFORT_LOW。

        腾讯云点播转发 Gemini 模型时，若用户未显式指定 reasoning_effort，
        默认设为 'low' 以降低推理成本。

        Args:
            request: 对话请求对象

        Returns:
            OpenAI 格式的请求字典
        """
        # 如果是 Gemini 对话模型且用户未指定 reasoning_effort，默认设为 low
        if (
            request.model.lower().startswith("gemini-")
            and not request.reasoning_effort
        ):
            request.reasoning_effort = REASONING_EFFORT_LOW

        return super().prepare_request(request)

    def _content_block_to_openai(self, block) -> Dict[str, Any]:
        """
        将 ContentBlock 转换为腾讯云点播 AI 格式。

        腾讯云点播 AI 对话模型对视频和文件数据使用 ``file`` 类型格式：
            {"type": "file", "file_url": "url_or_data_uri"}

        而非 OpenAI 标准的 ``video_url`` / ``file_url`` 嵌套格式。
        图片数据仍使用 OpenAI 标准格式。

        Tencent VOD 只支持真实 URL，不支持 data URI。因此 base64 数据
        需要先上传到 storage 获取 URL。
        """
        from app.abstraction.messages import ContentType

        if block.type == ContentType.VIDEO_URL:
            return {"type": "file", "file_url": block.url or ""}
        elif block.type == ContentType.VIDEO_BASE64:
            return {
                "type": "file",
                "file_url": self._upload_base64_to_storage(
                    block.data, block.media_type or "video/mp4"
                )
            }
        elif block.type == ContentType.FILE_URL:
            return {"type": "file", "file_url": block.url or ""}
        elif block.type == ContentType.FILE_BASE64:
            return {
                "type": "file",
                "file_url": self._upload_base64_to_storage(
                    block.data, block.media_type or "application/octet-stream"
                )
            }
        # 其他类型（图片、音频、文本等）使用标准 OpenAI 格式
        return super()._content_block_to_openai(block)

    def _upload_base64_to_storage(self, data: str, media_type: str) -> str:
        """将 base64 数据上传到 storage 并返回可访问的 URL。

        Tencent VOD 只支持真实 URL，不支持 data URI，因此 base64 数据
        必须先上传到配置的 storage backend 获取 URL。
        """
        import uuid
        from app.storage.factory import get_storage_backend

        raw = _safe_b64decode(data)
        ext = media_type.split("/")[-1] if "/" in media_type else "bin"
        key = f"tencent_vod/{uuid.uuid4().hex}.{ext}"
        storage = get_storage_backend()
        return storage.write_binary(key, raw, media_type)

    # ==================== 图像/视频生成检测 ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model is a TencentVOD image generation model."""
        return is_tencentvod_image_model(model)

    def is_video_generation_model(self, model: str) -> bool:
        """Check if the model is a TencentVOD video generation model."""
        return is_tencentvod_video_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_image_generation_tool(request)

    def _has_video_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains a video_generation tool."""
        return has_video_generation_tool(request)

    def _has_3d_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains a 3d_generation tool."""
        return has_3d_generation_tool(request)

    def _get_sub_app_id(self, request: ChatRequest) -> Optional[int]:
        """
        Resolve SubAppId from request metadata or provider extra_config.

        Priority: request.metadata["sub_app_id"] > extra_config["sub_app_id"]
        """
        val = (
            request.metadata.get("sub_app_id")
            or self.config.extra_config.get("sub_app_id")
            or self.config.extra_config.get("app_id")
        )
        return int(val) if val is not None else None

    def _get_image_api_key(self) -> str:
        """
        Build the "SecretId:SecretKey" credential string used by image generation.

        Prefers secret_id / secret_key stored in extra_config (the new canonical
        location).  Falls back to the raw api_key value so that existing
        providers that stored the combined string there still work.
        """
        extra = self.config.extra_config or {}
        secret_id = extra.get("secret_id", "").strip()
        secret_key = extra.get("secret_key", "").strip()
        if secret_id and secret_key:
            return f"{secret_id}:{secret_key}"
        # Fallback: api_key may already contain "SecretId:SecretKey"
        return self.config.api_key or ""

    # ==================== 非流式接口 ====================

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        执行对话/图像生成/视频生成请求

        优先级:
        1. 如果请求包含 3d_generation 工具 → 视频生成路径 (3d_scene)
        2. 如果模型是视频生成模型或请求包含 video_generation 工具 → 视频生成路径
        3. 如果模型是图像生成模型或请求包含 image_generation 工具 → 图像生成路径
        4. 否则走 OpenAI 兼容格式的对话路径

        Args:
            request: 对话请求对象

        Returns:
            对话/图像/视频生成响应对象
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self._has_3d_generation_tool(request):
            return await execute_tencentvod_3d_generation(
                api_key=self._get_image_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                sub_app_id=self._get_sub_app_id(request),
                tracer=self.tracer,
            )

        if self.is_video_generation_model(request.model) or self._has_video_generation_tool(request):
            return await execute_tencentvod_video_generation(
                api_key=self._get_image_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                sub_app_id=self._get_sub_app_id(request),
                tracer=self.tracer,
            )

        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            return await execute_tencentvod_image_generation(
                api_key=self._get_image_api_key(),
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
                sub_app_id=self._get_sub_app_id(request),
                tracer=self.tracer,
            )

        # 标准对话路径 — 根据模型配置的 api_type 路由到不同上游端点
        model_api_type = getattr(self, '_model_api_type', None) or ''
        if 'responses' in model_api_type:
            return await self._chat_responses(request)
        else:
            return await super().chat(request)

    # ==================== 流式接口 ====================

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """
        执行流式对话/图像生成/视频生成请求

        优先级:
        1. 如果请求包含 3d_generation 工具 → 视频生成路径 (3d_scene)
        2. 如果模型是视频生成模型或请求包含 video_generation 工具 → 视频生成路径
        3. 如果模型是图像生成模型或请求包含 image_generation 工具 → 图像生成路径
        4. 否则走 OpenAI 兼容格式的流式对话路径

        Args:
            request: 对话请求对象

        Yields:
            流式响应块
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        if self._has_3d_generation_tool(request):
            async for chunk in stream_3d_generation(self.chat, request):
                yield chunk
            return

        if self.is_video_generation_model(request.model) or self._has_video_generation_tool(request):
            async for chunk in stream_video_generation(self.chat, request):
                yield chunk
            return

        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            async for chunk in stream_image_generation(self.chat, request):
                yield chunk
            return

        # 标准流式对话路径 — 根据模型配置的 api_type 路由到不同上游端点
        model_api_type = getattr(self, '_model_api_type', None) or ''
        if 'responses' in model_api_type:
            async for chunk in self._stream_chat_responses(request):
                yield chunk
        else:
            async for chunk in super().stream_chat(request):
                yield chunk

    # ==================== Responses API 路径 ====================

    # 网关内部元数据键，不向上游透传
    _RESPONSES_INTERNAL_KEYS = frozenset({
        'support_thinking', 'support_online_image', 'support_online_video', 'reasoning',
        '_raw_tools', 'timeout', 'output_pricing', '_on_task_created', '_on_model_resolved',
    })

    def _prepare_responses_request(self, request: ChatRequest) -> dict:
        """将 ChatRequest 转换为 OpenAI Responses API 请求格式。"""
        input_array = self._messages_to_responses_input(request.messages)

        result = {
            "model": request.model,
            "input": input_array,
            "stream": request.stream,
        }

        if request.system is not None:
            result["instructions"] = request.system

        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.max_tokens is not None:
            result["max_output_tokens"] = request.max_tokens

        raw_tools = request.metadata.get('_raw_tools')
        if raw_tools:
            result["tools"] = raw_tools
        elif request.tools:
            result["tools"] = [self._tool_to_openai(t) for t in request.tools]
        if request.tool_choice:
            result["tool_choice"] = request.tool_choice

        if request.reasoning_effort and request.reasoning_effort != 'none':
            result["reasoning"] = {"effort": request.reasoning_effort}

        # 透传额外 metadata（过滤网关内部键）
        for key, value in request.metadata.items():
            if key not in self._RESPONSES_INTERNAL_KEYS:
                result[key] = value

        return result

    def _messages_to_responses_input(self, messages) -> list:
        """将内部 Message 列表转换为 Responses API input 数组。"""
        result = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                continue  # system handled separately as instructions
            items = self._message_to_responses_items(msg)
            result.extend(items)
        return result

    def _message_to_responses_items(self, msg) -> list:
        """将单条 Message 转换为 Responses API input 条目列表。"""
        from app.abstraction.messages import Message
        if msg.role == MessageRole.USER:
            content_list = []
            for block in msg.content:
                content_list.append(self._content_block_to_responses_input(block))
            if content_list:
                return [{"role": "user", "content": content_list}]
            return [{"role": "user", "content": msg.get_text_content() or ""}]

        if msg.role == MessageRole.ASSISTANT:
            items = []
            # tool calls as separate function_call items
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json_loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                    except Exception:
                        args = {}
                    items.append({
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    })
            # text content
            text = msg.get_text_content()
            if text:
                items.append({"role": "assistant", "content": [{"type": "output_text", "text": text}]})
            elif not msg.tool_calls:
                items.append({"role": "assistant", "content": ""})
            return items

        if msg.role == MessageRole.TOOL:
            text = msg.get_text_content() or ""
            return [{
                "type": "function_call_output",
                "call_id": msg.tool_call_id or "",
                "output": text,
            }]

        return []

    def _content_block_to_responses_input(self, block) -> dict:
        """将 ContentBlock 转换为 Responses API input 格式。"""
        if block.type == ContentType.TEXT:
            return {"type": "input_text", "text": block.text or ""}
        if block.type == ContentType.IMAGE:
            if block.image_url:
                return {"type": "input_image", "image_url": block.image_url}
            if block.data:
                return {"type": "input_image", "image_url": f"data:{block.mime_type or 'image/png'};base64,{block.data}"}
        if block.type == ContentType.AUDIO:
            if block.data:
                return {"type": "input_audio", "data": block.data, "format": block.format or "wav"}
        if block.type == ContentType.FILE:
            if block.file_url:
                return {"type": "input_file", "file_url": block.file_url}
            if block.data:
                return {"type": "input_file", "data": block.data, "filename": block.filename or "file"}
        return {"type": "input_text", "text": ""}

    def _parse_responses_response(self, response_data: dict, model: str) -> ChatResponse:
        """将 Responses API 响应解析为 ChatResponse。"""
        from app.abstraction.chat import ChatResponse, ChatChoice, UsageInfo, FinishReason
        from app.abstraction.messages import Message, ContentBlock

        output = response_data.get("output", [])
        # Collect text/refusal from message items
        texts = []
        tool_calls = []
        for item in output:
            if item.get("type") == "message":
                for content_item in item.get("content", []):
                    if content_item.get("type") == "output_text":
                        texts.append(content_item.get("text", ""))
        if item.get("type") == "function_call":
            tool_calls.append(item)

        content_blocks = []
        if texts:
            content_blocks.append(ContentBlock(type=ContentType.TEXT, text="".join(texts)))

        finish_reason = FinishReason.STOP
        if response_data.get("status") == "incomplete":
            finish_reason = FinishReason.LENGTH

        message = Message(role=MessageRole.ASSISTANT, content=content_blocks)
        if tool_calls:
            from app.abstraction.tools import ToolCall
            message.tool_calls = [
                ToolCall(id=tc.get("call_id", ""), name=tc.get("name", ""),
                         arguments=json.dumps(tc.get("arguments", {}), ensure_ascii=False))
                for tc in tool_calls
            ]

        usage_raw = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_raw.get("input_tokens", 0),
            completion_tokens=usage_raw.get("output_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return ChatResponse(
            id=response_data.get("id", ""),
            object="response",
            model=model,
            choices=[ChatChoice(index=0, message=message, finish_reason=finish_reason)],
            usage=usage,
        )

    async def _chat_responses(self, request: ChatRequest) -> ChatResponse:
        """向 /v1/responses 发送非流式请求。"""
        request_data = self._prepare_responses_request(request)
        request_data["stream"] = False

        url = f"{self.config.base_url}/responses"

        client = await self._http()
        headers = self.get_headers()
        async with self._trace_call(request.model, input_data=request_data) as child_span:
            response = await client.post(url, json=request_data, headers=headers)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                except Exception:
                    error_data = None
                raise RuntimeError(
                    f"TencentVOD Responses API error ({response.status_code}): "
                    f"{json.dumps(error_data, ensure_ascii=False) if error_data else response.text}"
                )

            response_data = response.json()
            if child_span:
                child_span.log_output(response_data)
            return self._parse_responses_response(response_data, request.model)

    async def _stream_chat_responses(self, request: ChatRequest):
        """向 /v1/responses 发送流式请求，yield StreamChunk。"""
        request_data = self._prepare_responses_request(request)
        request_data["stream"] = True

        url = f"{self.config.base_url}/responses"

        client = await self._http()
        headers = self.get_headers()
        async with self._trace_call(request.model, input_data=request_data) as child_span:
            async with client.stream("POST", url, json=request_data, headers=headers) as response:
                if response.status_code >= 400:
                    try:
                        error_data = await response.aread()
                        error_data = json_loads(error_data)
                    except Exception:
                        error_data = None
                    raise RuntimeError(
                        f"TencentVOD Responses API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False) if error_data else ''}"
                    )

                buffer = ""
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            event = json_loads(data_str)
                            event_type = event.get("type", "")

                            if event_type == "response.output_text.delta":
                                delta_text = event.get("delta", "")
                                yield StreamChunk(
                                    id=event.get("response_id", ""),
                                    model=event.get("model", request.model),
                                    event_type=StreamEventType.CONTENT_DELTA,
                                    delta_content=delta_text,
                                )

                            elif event_type == "response.completed":
                                resp = event.get("response", {})
                                usage_raw = resp.get("usage", {})
                                from app.abstraction.chat import UsageInfo
                                yield StreamChunk(
                                    id=resp.get("id", ""),
                                    model=resp.get("model", request.model),
                                    event_type=StreamEventType.DONE,
                                    usage=UsageInfo(
                                        prompt_tokens=usage_raw.get("input_tokens", 0),
                                        completion_tokens=usage_raw.get("output_tokens", 0),
                                        total_tokens=usage_raw.get("total_tokens", 0),
                                    ),
                                )

                            elif event_type == "error":
                                raise RuntimeError(
                                    f"TencentVOD Responses API stream error: {event.get('message', 'unknown')}"
                                )

                        except Exception:
                            pass

    # ==================== 模型信息 ====================

    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型（始终返回 True 以支持新模型）"""
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """
        获取模型信息

        Args:
            model: 模型名称

        Returns:
            模型信息字典
        """
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        return {
            "description": f"腾讯云点播 AI 模型: {model}",
            "context_size": 128000,
            "supports_vision": False,
        }

    # ==================== 模型列表 ====================

    def list_models(self) -> List[Dict[str, Any]]:
        """列出支持的模型"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "tencent",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 128000),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
