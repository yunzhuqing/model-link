"""
Google Gemini 供应商基础实现 (Gemini Base Provider)
实现 Google Gemini API 的直接调用（使用 API Key 认证）。

与 VertexAI Provider 不同，此供应商直接调用 Google Generative AI API，
使用简单的 API Key 认证，无需 Google Cloud 服务账号。

Gemini API 文档:
https://ai.google.dev/gemini-api/docs

配置说明:
- base_url: API 基础 URL（默认 https://generativelanguage.googleapis.com）
- api_key: Google AI API Key
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import sys

from ..base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall, ToolType
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse, EmbeddingData, EmbeddingUsage
from app.utils import gen_id
from .image_generation import is_gemini_image_model, has_image_generation_tool, stream_image_generation
from .video_generation import (
    is_veo_video_model,
    execute_veo_video_generation,
    stream_veo_video_generation,
)


# Internal metadata keys set by the gateway service.
_GATEWAY_INTERNAL_KEYS = frozenset({'support_thinking', 'support_online_image', 'support_online_video', 'reasoning'})

# In-memory cache for thoughtSignature mapping: tool_call_id -> thoughtSignature
# This is needed because Gemini requires thoughtSignature to be passed back with functionCall
_thought_signature_cache: Dict[str, str] = {}


class GeminiProvider(BaseProvider):
    """
    Google Gemini 供应商实现

    通过 Google Generative AI API 直接调用 Gemini 模型。
    使用 API Key 认证，无需 Google Cloud 服务账号。

    配置:
        - base_url: https://generativelanguage.googleapis.com（默认）
        - api_key: Google AI API Key
    """

    PROVIDER_TYPE: str = "gemini"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
        ProviderCapability.VIDEO,
    ]

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

    SUPPORTED_MODELS = {
        "gemini-2.5-pro": {
            "description": "Gemini 2.5 Pro - Google's most capable thinking model",
            "context_size": 1048576,
            "supports_vision": True,
        },
        "gemini-2.5-flash": {
            "description": "Gemini 2.5 Flash - Fast thinking model",
            "context_size": 1048576,
            "supports_vision": True,
        },
        "gemini-2.5-flash-lite": {
            "description": "Gemini 2.5 Flash Lite - Cost-efficient and low-latency",
            "context_size": 1048576,
            "supports_vision": True,
        },
        "gemini-2.0-flash": {
            "description": "Gemini 2.0 Flash - Next-gen fast model",
            "context_size": 1048576,
            "supports_vision": True,
        },
        "gemini-2.0-flash-lite": {
            "description": "Gemini 2.0 Flash Lite - Cost-efficient",
            "context_size": 1048576,
            "supports_vision": True,
        },
        "gemini-1.5-pro": {
            "description": "Gemini 1.5 Pro - Advanced model with long context",
            "context_size": 2097152,
            "supports_vision": True,
        },
        "gemini-1.5-flash": {
            "description": "Gemini 1.5 Flash - Fast and versatile",
            "context_size": 1048576,
            "supports_vision": True,
        },
        "gemini-embedding-exp": {
            "description": "Gemini Embedding - Text embedding model",
            "context_size": 8192,
            "supports_vision": False,
        },
        "text-embedding-004": {
            "description": "Text Embedding 004 - Text embedding model",
            "context_size": 2048,
            "supports_vision": False,
        },
    }

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        # Normalize: strip /v1beta or /v1beta/ suffix if present.
        # The /v1beta prefix is added internally in _get_api_url.
        if config.base_url:
            config.base_url = config.base_url.rstrip('/')
            if config.base_url.endswith('/v1beta'):
                config.base_url = config.base_url[:-len('/v1beta')]
        super().__init__(config)

    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                timeout=self.config.timeout,
                headers=self._get_headers()
            )
        return self._client

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Gemini API requests.
        
        Gemini uses x-goog-api-key header instead of Authorization: Bearer.
        """
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.config.api_key,
        }

    def supports_model(self, model: str) -> bool:
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        return {
            "description": f"Gemini model: {model}",
            "context_size": 1048576,
            "supports_vision": True,
        }

    # ==================== URL 构建 ====================

    def _get_api_url(self, model: str, streaming: bool = False) -> str:
        """
        构建 Gemini API URL

        base_url 格式为 https://xxxx（不含 /v1beta），
        /v1beta 前缀在此方法内自动添加。

        Args:
            model: 模型名称
            streaming: 是否流式请求

        Returns:
            完整的 API URL
        """
        base_url = self.config.base_url.rstrip('/')
        if streaming:
            return f"{base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse"
        else:
            return f"{base_url}/v1beta/models/{model}:generateContent"

    def _get_embed_url(self, model: str) -> str:
        """构建嵌入 API URL"""
        base_url = self.config.base_url.rstrip('/')
        return f"{base_url}/v1beta/models/{model}:embedContent"

    def _get_batch_embed_url(self, model: str) -> str:
        """构建批量嵌入 API URL"""
        base_url = self.config.base_url.rstrip('/')
        return f"{base_url}/v1beta/models/{model}:batchEmbedContents"

    # ==================== Image Generation ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model supports native image generation."""
        return is_gemini_image_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_image_generation_tool(request)

    # ==================== Video Generation ====================

    def is_video_generation_model(self, model: str) -> bool:
        """Check if the model is a Veo video generation model."""
        return is_veo_video_model(model)

    def _has_video_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request carries a video_generation tool flag."""
        return bool(request.metadata.get("_video_generation"))

    # ==================== 请求准备 ====================

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """准备 Gemini generateContent 格式的请求体"""
        result = {}

        # System instruction
        system_content = request.get_system_message()
        if system_content:
            result["system_instruction"] = {
                "parts": [{"text": system_content}]
            }

        # Convert messages to Gemini contents.
        # Build a call_id → name mapping so functionResponse can include the
        # function name even when the TOOL_RESULT ContentBlock doesn't carry it.
        call_id_to_name: Dict[str, str] = {}
        for msg in request.messages:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ContentBlock) and block.type == ContentType.TOOL_CALL:
                        if block.tool_call_id and block.tool_name:
                            call_id_to_name[block.tool_call_id] = block.tool_name

        contents = []
        for msg in request.messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            gemini_msg = self._message_to_gemini(msg, call_id_to_name)
            if gemini_msg:
                # Merge consecutive same-role messages.
                # Gemini requires alternating user/model roles. When the
                # Responses adapter creates separate ASSISTANT messages for each
                # function_call or separate TOOL messages for each
                # function_call_output, we must merge them into single messages.
                if contents and contents[-1].get("role") == gemini_msg.get("role"):
                    contents[-1]["parts"].extend(gemini_msg["parts"])
                else:
                    contents.append(gemini_msg)
        result["contents"] = contents

        # Generation config
        gen_config = {}
        if request.temperature is not None:
            gen_config["temperature"] = request.temperature
        if request.top_p is not None:
            gen_config["topP"] = request.top_p
        if request.max_tokens is not None:
            gen_config["maxOutputTokens"] = request.max_tokens
        if request.stop:
            gen_config["stopSequences"] = request.stop

        # Enable thinking based on model's support_thinking flag and reasoning_effort
        if request.metadata.get('support_thinking', False):
            reasoning_effort = request.reasoning_effort or 'none'
            gen_config["thinkingConfig"] = {
                "includeThoughts": reasoning_effort != 'none'
            }
        elif request.reasoning_effort and request.reasoning_effort != 'none':
            gen_config["thinkingConfig"] = {
                "includeThoughts": True
            }

        # Enable image generation output modality for image generation models
        # or when the request contains an image_generation tool.
        # Gemini native image generation requires responseModalities: ["TEXT", "IMAGE"]
        if self.is_image_generation_model(request.model) or self._has_image_generation_tool(request):
            gen_config["responseModalities"] = ["TEXT", "IMAGE"]

        if gen_config:
            result["generationConfig"] = gen_config

        # Tools
        if request.tools:
            result["tools"] = [{
                "functionDeclarations": [self._tool_to_gemini(t) for t in request.tools]
            }]
        if request.tool_choice:
            if isinstance(request.tool_choice, str):
                mode_map = {"auto": "AUTO", "none": "NONE", "required": "ANY"}
                mode = mode_map.get(request.tool_choice, "AUTO")
                result["toolConfig"] = {"functionCallingConfig": {"mode": mode}}

        # Debug logging
        print("\n" + "=" * 50, file=sys.stderr)
        print("[Gemini Request Body]", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        print("=" * 50 + "\n", file=sys.stderr)

        return result

    def _message_to_gemini(self, message: Message, call_id_to_name: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """将 Message 转换为 Gemini 格式

        Args:
            message: 消息对象
            call_id_to_name: tool_call_id → function name 映射表，
                用于在 functionResponse 中补全缺失的 name 字段。
        """
        if call_id_to_name is None:
            call_id_to_name = {}

        # Gemini uses "user" and "model" roles
        role = "model" if message.role == MessageRole.ASSISTANT else "user"

        # Handle tool role - Gemini uses functionResponse parts
        if message.role == MessageRole.TOOL:
            parts = []
            call_id = message.tool_call_id or ""
            if isinstance(message.content, list):
                for block in message.content:
                    if block.type == ContentType.TOOL_RESULT:
                        bid = block.tool_call_id or call_id
                        name = block.tool_name or message.name or call_id_to_name.get(bid, "")
                        fr: Dict[str, Any] = {
                            "name": name,
                            "response": {"output": block.tool_result or ""}
                        }
                        if bid:
                            fr["id"] = bid
                        parts.append({"functionResponse": fr})
                    elif block.type == ContentType.TEXT:
                        name = message.name or call_id_to_name.get(call_id, "")
                        fr = {
                            "name": name,
                            "response": {"output": block.text or ""}
                        }
                        if call_id:
                            fr["id"] = call_id
                        parts.append({"functionResponse": fr})
            elif isinstance(message.content, str):
                name = message.name or call_id_to_name.get(call_id, "")
                fr = {
                    "name": name,
                    "response": {"output": message.content}
                }
                if call_id:
                    fr["id"] = call_id
                parts.append({"functionResponse": fr})
            return {"role": "user", "parts": parts} if parts else None

        parts = []
        if isinstance(message.content, str):
            parts.append({"text": message.content})
        elif isinstance(message.content, list):
            for block in message.content:
                part = self._content_block_to_gemini(block, call_id_to_name)
                if part:
                    parts.append(part)
        else:
            parts.append({"text": ""})

        return {"role": role, "parts": parts} if parts else None

    def _content_block_to_gemini(self, block: ContentBlock, call_id_to_name: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """将 ContentBlock 转换为 Gemini parts 格式

        Args:
            block: 内容块
            call_id_to_name: tool_call_id → function name 映射表
        """
        if call_id_to_name is None:
            call_id_to_name = {}

        if block.type == ContentType.TEXT:
            return {"text": block.text or ""}
        elif block.type == ContentType.IMAGE_URL:
            return {"fileData": {"fileUri": block.url, "mimeType": block.media_type or "image/jpeg"}}
        elif block.type == ContentType.IMAGE_BASE64:
            return {"inlineData": {"data": block.data, "mimeType": block.media_type or "image/jpeg"}}
        elif block.type == ContentType.VIDEO_URL:
            return {"fileData": {"fileUri": block.url, "mimeType": block.media_type or "video/mp4"}}
        elif block.type == ContentType.VIDEO_BASE64:
            return {"inlineData": {"data": block.data, "mimeType": block.media_type or "video/mp4"}}
        elif block.type == ContentType.AUDIO_URL:
            return {"fileData": {"fileUri": block.url, "mimeType": block.media_type or "audio/mp3"}}
        elif block.type == ContentType.AUDIO_BASE64:
            return {"inlineData": {"data": block.data, "mimeType": block.media_type or "audio/mp3"}}
        elif block.type == ContentType.FILE_URL:
            return {"fileData": {"fileUri": block.url, "mimeType": block.media_type or "application/octet-stream"}}
        elif block.type == ContentType.FILE_BASE64:
            return {"inlineData": {"data": block.data, "mimeType": block.media_type or "application/octet-stream"}}
        elif block.type == ContentType.TOOL_CALL:
            fc: Dict[str, Any] = {"name": block.tool_name or "", "args": block.tool_arguments or {}}
            if block.tool_call_id:
                fc["id"] = block.tool_call_id
            part: Dict[str, Any] = {"functionCall": fc}
            # Include thoughtSignature from cache if available (required for multi-turn tool calls)
            if block.tool_call_id and block.tool_call_id in _thought_signature_cache:
                part["thoughtSignature"] = _thought_signature_cache[block.tool_call_id]
            return part
        elif block.type == ContentType.TOOL_RESULT:
            bid = block.tool_call_id or ""
            name = block.tool_name or call_id_to_name.get(bid, "")
            fr: Dict[str, Any] = {"name": name, "response": {"output": block.tool_result or ""}}
            if bid:
                fr["id"] = bid
            return {"functionResponse": fr}
        else:
            return {"text": block.text or ""}

    def _tool_to_gemini(self, tool: ToolDefinition) -> Dict[str, Any]:
        """将 ToolDefinition 转换为 Gemini 格式
        
        Note: Gemini API 不支持 JSON Schema 的 $ref 引用，
        需要移除所有 ref 属性，确保 schema 是完全内联的。
        """
        schema = tool.get_parameters_schema()
        # Remove 'ref' attributes recursively since Gemini doesn't support $ref
        schema = self._remove_ref_from_schema(schema)
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema
        }
    
    def _remove_ref_from_schema(self, schema: Any) -> Any:
        """递归移除 schema 中的 ref 和 additionalProperties 属性
        
        Gemini API 不支持 JSON Schema 的 $ref 引用和 additionalProperties，
        此方法递归遍历 schema 并移除这些不支持的键。
        
        Args:
            schema: JSON Schema 对象或值
            
        Returns:
            清理后的 schema
        """
        if isinstance(schema, dict):
            result = {}
            for key, value in schema.items():
                if key in ("ref", "additionalProperties"):
                    # Skip keys not supported by Gemini API
                    continue
                result[key] = self._remove_ref_from_schema(value)
            return result
        elif isinstance(schema, list):
            return [self._remove_ref_from_schema(item) for item in schema]
        else:
            return schema

    # ==================== 响应解析 ====================

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """解析 Gemini generateContent 格式的响应"""
        candidates = response_data.get("candidates", [])
        message_blocks = []
        tool_calls = []
        thinking_parts = []
        inline_images: List[Dict[str, Any]] = []  # Collected inline image data
        finish_reason = FinishReason.STOP

        if candidates:
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            for part in parts:
                if "text" in part:
                    if part.get("thought", False):
                        thinking_parts.append(part["text"])
                    else:
                        message_blocks.append(ContentBlock.from_text(part["text"]))
                elif "inlineData" in part:
                    # Gemini native image generation returns images as inlineData
                    inline_data = part["inlineData"]
                    mime_type = inline_data.get("mimeType", "image/png")
                    b64_data = inline_data.get("data", "")
                    if b64_data:
                        # Build a data URI: data:<mime>;base64,<data>
                        data_uri = f"data:{mime_type};base64,{b64_data}"
                        inline_images.append({
                            "type": "image_generation_call",
                            "status": "completed",
                            "result": data_uri,
                        })
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tc_id = gen_id("call")
                    tc_name = fc.get("name", "")
                    tc_args = fc.get("args", {})
                    # Capture thoughtSignature if present (required for multi-turn tool calls)
                    # Store in cache for later retrieval when building functionCall
                    thought_sig = part.get("thoughtSignature")
                    if thought_sig:
                        _thought_signature_cache[tc_id] = thought_sig
                    tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=tc_args, call_type="function"))
                    message_blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_args))

            gemini_finish = candidate.get("finishReason", "STOP")
            finish_map = {
                "STOP": FinishReason.STOP,
                "MAX_TOKENS": FinishReason.LENGTH,
                "SAFETY": FinishReason.CONTENT_FILTER,
                "RECITATION": FinishReason.STOP,
            }
            finish_reason = finish_map.get(gemini_finish, FinishReason.STOP)
            if tool_calls:
                finish_reason = FinishReason.TOOL_CALLS

        usage_metadata = response_data.get("usageMetadata", {})
        usage = UsageInfo(
            prompt_tokens=usage_metadata.get("promptTokenCount", 0),
            completion_tokens=usage_metadata.get("candidatesTokenCount", 0),
            total_tokens=usage_metadata.get("totalTokenCount", 0),
        )

        # If the response contains inline images, return an image generation response
        # compatible with the Responses API image_generation_call format.
        if inline_images:
            # Include any text content along with images
            text_parts = [b.text for b in message_blocks
                          if isinstance(b, ContentBlock) and b.type == ContentType.TEXT and b.text]

            # Store image_generation_call items as JSON in the message content,
            # same format as Volcengine provider. The Responses adapter will parse
            # and emit them as image_generation_call output items.
            message = Message(
                role=MessageRole.ASSISTANT,
                content=json.dumps(inline_images, ensure_ascii=False)
            )

            return ChatResponse(
                id=gen_id("img"),
                model=model,
                choices=[ChatChoice(
                    index=0,
                    message=message,
                    finish_reason=finish_reason,
                )],
                usage=usage,
                created=int(time.time()),
                provider=self.PROVIDER_TYPE,
            )

        # Standard (non-image) response
        message = Message(role=MessageRole.ASSISTANT, content=message_blocks if message_blocks else None)
        reasoning_content = "\n\n".join(thinking_parts) if thinking_parts else None

        return ChatResponse(
            id=gen_id("gemini"),
            model=model,
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

    # ==================== 主接口 ====================

    def chat(self, request: ChatRequest) -> ChatResponse:
        """执行非流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        # Veo video generation models → dedicated video generation path
        if self.is_video_generation_model(request.model) or self._has_video_generation_tool(request):
            return execute_veo_video_generation(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                model=request.model,
                messages=request.messages,
                metadata=request.metadata,
            )

        request_data = self.prepare_request(request)
        url = self._get_api_url(request.model, streaming=False)

        try:
            response = self.client.post(url, json=request_data)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(
                        f"Gemini API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"Gemini API error ({response.status_code}): {response.text}"
                    )

            response_data = response.json()
            return self.parse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Gemini API error: {str(e)}")

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        # Veo video generation models → dedicated video generation path
        if self.is_video_generation_model(request.model) or self._has_video_generation_tool(request):
            yield from stream_veo_video_generation(self.chat, request)
            return

        # For image generation models, use the dedicated streaming path.
        # Gemini's native image generation doesn't truly stream images; it returns
        # the full image in one SSE chunk. We call the API, collect all images,
        # then emit them as image_generation_call SSE events via raw_sse_passthrough.
        is_img_gen = (
            self.is_image_generation_model(request.model)
            or self._has_image_generation_tool(request)
        )
        if is_img_gen:
            yield from stream_image_generation(self.chat, request)
            return

        request_data = self.prepare_request(request)
        url = self._get_api_url(request.model, streaming=True)
        response_id = gen_id("gemini")

        # Track whether any tool calls were seen so we can fix the trailing
        # end-of-stream STOP marker (Gemini emits finishReason=STOP on the
        # final empty chunk even when the response was actually tool_calls).
        gemini_saw_tool_calls = False

        try:
            with self.client.stream("POST", url, json=request_data) as response:
                if response.status_code >= 400:
                    error_text = ""
                    for chunk_bytes in response.iter_bytes():
                        if chunk_bytes:
                            error_text += chunk_bytes.decode('utf-8')
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(
                            f"Gemini API error ({response.status_code}): "
                            f"{json.dumps(error_data, ensure_ascii=False)}"
                        )
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"Gemini API error ({response.status_code}): {error_text}"
                        )

                for line in response.iter_lines():
                    if not line:
                        continue

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

                        chunk = self._parse_stream_chunk(event_data, response_id, request.model)
                        if chunk:
                            if chunk.tool_calls:
                                gemini_saw_tool_calls = True
                            # The trailing end-of-stream chunk has finish_reason=STOP but no
                            # content.  If we already saw tool calls earlier, upgrade it.
                            if (gemini_saw_tool_calls and
                                    chunk.finish_reason == FinishReason.STOP and
                                    not chunk.tool_calls and
                                    not chunk.delta_content and
                                    not chunk.delta_reasoning_content):
                                chunk.finish_reason = FinishReason.TOOL_CALLS
                            yield chunk

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Gemini streaming API error: {str(e)}")

    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """解析 Gemini SSE 流式响应块"""
        candidates = data.get("candidates", [])
        if not candidates:
            usage_metadata = data.get("usageMetadata")
            if usage_metadata:
                return StreamChunk(
                    id=response_id, model=model,
                    usage={
                        "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                        "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                        "total_tokens": usage_metadata.get("totalTokenCount", 0),
                    },
                    event_type=StreamEventType.USAGE,
                )
            return None

        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        gemini_finish = candidate.get("finishReason")
        finish_reason = None
        if gemini_finish:
            finish_map = {
                "STOP": FinishReason.STOP,
                "MAX_TOKENS": FinishReason.LENGTH,
                "SAFETY": FinishReason.CONTENT_FILTER,
            }
            finish_reason = finish_map.get(gemini_finish, FinishReason.STOP)

        delta_content = None
        delta_reasoning_content = None
        tool_calls_data = []

        for part in parts:
            if "text" in part:
                if part.get("thought", False):
                    delta_reasoning_content = (delta_reasoning_content or "") + part["text"]
                else:
                    delta_content = (delta_content or "") + part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tc_id = gen_id("call")
                # Capture thoughtSignature if present (required for multi-turn tool calls)
                # Store in cache for later retrieval when building functionCall
                thought_sig = part.get("thoughtSignature")
                if thought_sig:
                    _thought_signature_cache[tc_id] = thought_sig
                tool_calls_data.append({
                    "index": 0, "id": tc_id, "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {}), ensure_ascii=False),
                    }
                })

        # When tool calls are present, correct the finish_reason:
        # - If Gemini set a finish reason (e.g. "STOP"), override it to TOOL_CALLS.
        # - If Gemini did NOT set a finish reason (intermediate chunk), leave it as None
        #   so we don't emit a premature finish_reason on non-final tool-call chunks.
        if tool_calls_data and finish_reason is not None:
            finish_reason = FinishReason.TOOL_CALLS

        delta_role = content.get("role")
        if delta_role == "model":
            delta_role = "assistant"

        # Parse usage if present
        usage = None
        usage_metadata = data.get("usageMetadata")
        if usage_metadata:
            pt = usage_metadata.get("promptTokenCount", 0)
            ct = usage_metadata.get("candidatesTokenCount", 0)
            tt = usage_metadata.get("totalTokenCount", 0)
            if pt or ct or tt:
                usage = {
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "total_tokens": tt,
                }

        # When there are no content parts and finish_reason is STOP, Gemini is sending
        # an end-of-stream marker.  Use falsy check so empty-string text ("") is also
        # caught.  Always return the chunk so stream_chat() can override STOP→TOOL_CALLS.
        if (not delta_content and not delta_reasoning_content and
                not tool_calls_data and finish_reason == FinishReason.STOP):
            return StreamChunk(
                id=response_id, model=model,
                finish_reason=finish_reason,  # preserved; stream_chat may override
                usage=usage,
                event_type=StreamEventType.USAGE,
            )

        return StreamChunk(
            id=response_id, model=model,
            delta_content=delta_content,
            delta_role=delta_role,
            delta_reasoning_content=delta_reasoning_content,
            tool_calls=tool_calls_data if tool_calls_data else [],
            finish_reason=finish_reason,
            usage=usage,
            event_type=StreamEventType.CONTENT_DELTA,
        )

    # ==================== Embedding ====================

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        执行嵌入请求

        Gemini Embedding API 格式:
        POST /v1beta/models/{model}:embedContent
        Header: x-goog-api-key: {API_KEY}
        {
            "model": "models/{model}",
            "content": {
                "parts": [{"text": "..."}]
            }
        }

        批量嵌入:
        POST /v1beta/models/{model}:batchEmbedContents
        {
            "model": "models/{model}",
            "requests": [
                {"model": "models/{model}", "content": {"parts": [{"text": "..."}]}}
            ]
        }
        """
        if request.is_multimodal:
            # Multimodal embedding - convert messages to Gemini content parts
            parts = self._convert_messages_to_gemini_parts(request.messages)
            return self._embed_single(request.model, parts, request.dimensions)
        elif isinstance(request.input, list):
            # Batch text embedding
            return self._embed_batch(request.model, request.input, request.dimensions)
        else:
            # Single text embedding
            parts = [{"text": request.input or ""}]
            return self._embed_single(request.model, parts, request.dimensions)

    def _embed_single(self, model: str, parts: List[Dict[str, Any]], dimensions: Optional[int] = None) -> EmbeddingResponse:
        """执行单个嵌入请求"""
        request_data = {
            "model": f"models/{model}",
            "content": {
                "parts": parts
            }
        }
        if dimensions is not None:
            request_data["outputDimensionality"] = dimensions

        url = self._get_embed_url(model)

        try:
            response = self.client.post(url, json=request_data)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(
                        f"Gemini embedding API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"Gemini embedding API error ({response.status_code}): {response.text}"
                    )

            response_data = response.json()
            embedding = response_data.get("embedding", {})
            values = embedding.get("values", [])

            return EmbeddingResponse(
                object="list",
                data=[EmbeddingData(index=0, embedding=values)],
                model=model,
                usage=EmbeddingUsage(prompt_tokens=0, total_tokens=0),
            )

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Gemini embedding API error: {str(e)}")

    def _embed_batch(self, model: str, texts: List[str], dimensions: Optional[int] = None) -> EmbeddingResponse:
        """执行批量文本嵌入请求"""
        requests = []
        for text in texts:
            req = {
                "model": f"models/{model}",
                "content": {
                    "parts": [{"text": text}]
                }
            }
            if dimensions is not None:
                req["outputDimensionality"] = dimensions
            requests.append(req)

        request_data = {
            "requests": requests
        }

        url = self._get_batch_embed_url(model)

        try:
            response = self.client.post(url, json=request_data)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(
                        f"Gemini batch embedding API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"Gemini batch embedding API error ({response.status_code}): {response.text}"
                    )

            response_data = response.json()
            embeddings = response_data.get("embeddings", [])

            embedding_data = []
            for i, emb in enumerate(embeddings):
                embedding_data.append(EmbeddingData(
                    index=i,
                    embedding=emb.get("values", []),
                ))

            return EmbeddingResponse(
                object="list",
                data=embedding_data,
                model=model,
                usage=EmbeddingUsage(prompt_tokens=0, total_tokens=0),
            )

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Gemini batch embedding API error: {str(e)}")

    def _convert_messages_to_gemini_parts(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将 OpenAI 格式的 messages 转换为 Gemini embedding 的 parts 格式。

        Args:
            messages: OpenAI 格式的消息列表

        Returns:
            Gemini 格式的 parts 列表
        """
        parts = []

        for message in messages:
            content = message.get("content", [])

            if isinstance(content, str):
                parts.append({"text": content})
                continue

            if isinstance(content, list):
                for item in content:
                    item_type = item.get("type", "text")

                    if item_type == "text":
                        text = item.get("text", "")
                        if text:
                            parts.append({"text": text})
                    elif item_type == "image_url":
                        image_url = item.get("image_url", {})
                        url = image_url.get("url", "")
                        if url:
                            if url.startswith("data:"):
                                # base64 data URI
                                header, data = url.split(",", 1)
                                mime_type = header.replace("data:", "").replace(";base64", "")
                                parts.append({"inlineData": {"data": data, "mimeType": mime_type}})
                            else:
                                parts.append({"fileData": {"fileUri": url, "mimeType": "image/jpeg"}})
                    elif item_type == "video_url":
                        video_url = item.get("video_url", {})
                        url = video_url.get("url", "")
                        if url:
                            parts.append({"fileData": {"fileUri": url, "mimeType": "video/mp4"}})

        return parts

    # ==================== 模型列表 ====================

    def list_models(self) -> List[Dict[str, Any]]:
        """列出支持的模型"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "google",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 1048576),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
