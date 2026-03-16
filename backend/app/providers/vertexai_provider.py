"""
Google Vertex AI 供应商实现 (Vertex AI Provider)
实现通过 Google Vertex AI 调用多种模型的 API。

Vertex AI 提供多种模型的托管服务，包括：
- Anthropic Claude 系列（使用 Anthropic Messages API 格式）
- Google Gemini 系列（使用 Google generateContent API 格式）
- DeepSeek 系列（使用 OpenAI 兼容格式）
- GLM / ChatGLM 系列（使用 OpenAI 兼容格式）
- Meta Llama 系列（使用 OpenAI 兼容格式）
- Mistral 系列（使用 OpenAI 兼容格式）

所有模型通过 Google Cloud OAuth2 认证访问。

Vertex AI API 文档:
https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/use-claude
https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/gemini

配置说明:
- base_url: Vertex AI 端点 URL，格式为:
    https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}
- api_key: Google Cloud 服务账号 JSON 密钥内容（完整 JSON 字符串）
    如果为空，将尝试使用 Application Default Credentials (ADC)
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid
import sys

from .base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall, ToolParameter, ToolType
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamEventType


class ModelPublisher:
    """模型发布者信息"""
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    DEEPSEEK = "deepseek"
    META = "meta"
    MISTRAL = "mistral"
    ZHIPU = "zhipu"  # GLM / ChatGLM


# 模型前缀到发布者的映射
MODEL_PUBLISHER_MAP = {
    "claude": ModelPublisher.ANTHROPIC,
    "gemini": ModelPublisher.GOOGLE,
    "deepseek": ModelPublisher.DEEPSEEK,
    "llama": ModelPublisher.META,
    "mistral": ModelPublisher.MISTRAL,
    "glm": ModelPublisher.ZHIPU,
    "chatglm": ModelPublisher.ZHIPU,
}


def detect_publisher(model_name: str) -> str:
    """
    根据模型名称检测发布者

    Args:
        model_name: 模型名称

    Returns:
        发布者标识
    """
    model_lower = model_name.lower()
    for prefix, publisher in MODEL_PUBLISHER_MAP.items():
        if model_lower.startswith(prefix):
            return publisher
    # 默认使用 Google (Gemini) 格式
    return ModelPublisher.GOOGLE


class VertexAIProvider(BaseProvider):
    """
    Google Vertex AI 供应商实现

    通过 Google Vertex AI 调用多种模型，自动检测模型类型并使用对应的 API 格式：
    - Claude → Anthropic Messages API 格式 (rawPredict)
    - Gemini → Google generateContent API 格式
    - DeepSeek/GLM/Llama/Mistral → OpenAI 兼容格式 (rawPredict)

    配置:
        - base_url: https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}
        - api_key: 服务账号 JSON 密钥内容（完整 JSON 字符串），或留空使用 ADC
    """

    PROVIDER_TYPE: str = "vertexai"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.CACHE,
    ]

    # Anthropic version for Vertex AI Claude
    ANTHROPIC_VERSION = "vertex-2023-10-16"

    # Vertex AI 上可用的模型
    SUPPORTED_MODELS = {
        # Claude 系列 (Anthropic)
        "claude-sonnet-4-20250514": {
            "description": "Claude Sonnet 4 - Anthropic's latest balanced model",
            "context_size": 200000,
            "supports_vision": True,
            "publisher": ModelPublisher.ANTHROPIC,
        },
        "claude-3-7-sonnet@20250219": {
            "description": "Claude 3.7 Sonnet - Extended thinking with hybrid reasoning",
            "context_size": 200000,
            "supports_vision": True,
            "publisher": ModelPublisher.ANTHROPIC,
        },
        "claude-3-5-sonnet-v2@20241022": {
            "description": "Claude 3.5 Sonnet v2 - Most intelligent Claude model",
            "context_size": 200000,
            "supports_vision": True,
            "publisher": ModelPublisher.ANTHROPIC,
        },
        "claude-3-5-sonnet@20240620": {
            "description": "Claude 3.5 Sonnet - Balanced intelligence and speed",
            "context_size": 200000,
            "supports_vision": True,
            "publisher": ModelPublisher.ANTHROPIC,
        },
        "claude-3-5-haiku@20241022": {
            "description": "Claude 3.5 Haiku - Fastest and most compact Claude",
            "context_size": 200000,
            "supports_vision": True,
            "publisher": ModelPublisher.ANTHROPIC,
        },
        "claude-3-opus@20240229": {
            "description": "Claude 3 Opus - Powerful model for complex tasks",
            "context_size": 200000,
            "supports_vision": True,
            "publisher": ModelPublisher.ANTHROPIC,
        },
        "claude-3-haiku@20240307": {
            "description": "Claude 3 Haiku - Fast and efficient",
            "context_size": 200000,
            "supports_vision": True,
            "publisher": ModelPublisher.ANTHROPIC,
        },
        # Gemini 系列 (Google)
        "gemini-2.5-pro": {
            "description": "Gemini 2.5 Pro - Google's most capable model",
            "context_size": 1048576,
            "supports_vision": True,
            "publisher": ModelPublisher.GOOGLE,
        },
        "gemini-2.5-flash": {
            "description": "Gemini 2.5 Flash - Fast and efficient",
            "context_size": 1048576,
            "supports_vision": True,
            "publisher": ModelPublisher.GOOGLE,
        },
        "gemini-2.0-flash": {
            "description": "Gemini 2.0 Flash - Next-gen fast model",
            "context_size": 1048576,
            "supports_vision": True,
            "publisher": ModelPublisher.GOOGLE,
        },
        "gemini-1.5-pro": {
            "description": "Gemini 1.5 Pro - Advanced model with long context",
            "context_size": 2097152,
            "supports_vision": True,
            "publisher": ModelPublisher.GOOGLE,
        },
        "gemini-1.5-flash": {
            "description": "Gemini 1.5 Flash - Fast and versatile",
            "context_size": 1048576,
            "supports_vision": True,
            "publisher": ModelPublisher.GOOGLE,
        },
        # DeepSeek 系列
        "deepseek-r1": {
            "description": "DeepSeek R1 - Reasoning model",
            "context_size": 64000,
            "supports_vision": False,
            "publisher": ModelPublisher.DEEPSEEK,
        },
        "deepseek-v3": {
            "description": "DeepSeek V3 - Advanced general model",
            "context_size": 64000,
            "supports_vision": False,
            "publisher": ModelPublisher.DEEPSEEK,
        },
        # Llama 系列 (Meta)
        "llama-3.3-70b-instruct-maas": {
            "description": "Llama 3.3 70B Instruct",
            "context_size": 128000,
            "supports_vision": False,
            "publisher": ModelPublisher.META,
        },
        "llama-4-maverick-17b-128e-instruct-maas": {
            "description": "Llama 4 Maverick 17B",
            "context_size": 1048576,
            "supports_vision": True,
            "publisher": ModelPublisher.META,
        },
        "llama-4-scout-17b-16e-instruct-maas": {
            "description": "Llama 4 Scout 17B",
            "context_size": 1048576,
            "supports_vision": True,
            "publisher": ModelPublisher.META,
        },
        # Mistral 系列
        "mistral-large-2411": {
            "description": "Mistral Large - High-performance model",
            "context_size": 128000,
            "supports_vision": False,
            "publisher": ModelPublisher.MISTRAL,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化 Vertex AI 供应商

        Args:
            config: 供应商配置
                - base_url: Vertex AI 端点 URL
                - api_key: 服务账号 JSON 密钥内容（或留空使用 ADC）
        """
        super().__init__(config)
        self._credentials = None

    # ==================== 认证 ====================

    def _get_credentials(self):
        """获取 Google Cloud 凭证"""
        if self._credentials is not None:
            return self._credentials

        from google.oauth2 import service_account
        import google.auth

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]

        if self.config.api_key:
            try:
                service_account_info = json.loads(self.config.api_key)
                self._credentials = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=scopes
                )
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(
                    f"Invalid service account JSON in api_key: {e}. "
                    "Please provide the full JSON content of the service account key file."
                )
        else:
            self._credentials, _ = google.auth.default(scopes=scopes)

        return self._credentials

    def _get_access_token(self) -> str:
        """获取有效的 OAuth2 访问令牌，自动刷新过期令牌"""
        import google.auth.transport.requests

        credentials = self._get_credentials()

        if not credentials.token or (
            credentials.expiry and credentials.expiry.timestamp() < time.time() + 60
        ):
            request = google.auth.transport.requests.Request()
            credentials.refresh(request)

        return credentials.token

    def get_headers(self) -> Dict[str, str]:
        """获取请求头（包含 OAuth2 Bearer token）"""
        access_token = self._get_access_token()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

    @property
    def client(self) -> Any:
        """获取 HTTP 客户端"""
        import httpx
        if self._client is None:
            self._client = httpx.Client(timeout=self.config.timeout)
        return self._client

    # ==================== URL 构建 ====================

    def _get_publisher_for_model(self, model: str) -> str:
        """获取模型对应的发布者"""
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model].get("publisher", detect_publisher(model))
        return detect_publisher(model)

    def _get_api_url(self, model: str, streaming: bool = False) -> str:
        """
        根据模型类型获取 API URL

        Args:
            model: 模型名称
            streaming: 是否流式请求

        Returns:
            完整的 API URL
        """
        base_url = self.config.base_url.rstrip('/')
        publisher = self._get_publisher_for_model(model)

        if publisher == ModelPublisher.GOOGLE:
            # Gemini 使用 generateContent / streamGenerateContent
            if streaming:
                return f"{base_url}/publishers/google/models/{model}:streamGenerateContent?alt=sse"
            else:
                return f"{base_url}/publishers/google/models/{model}:generateContent"
        elif publisher == ModelPublisher.ANTHROPIC:
            # Claude 使用 rawPredict / streamRawPredict
            if streaming:
                return f"{base_url}/publishers/anthropic/models/{model}:streamRawPredict"
            else:
                return f"{base_url}/publishers/anthropic/models/{model}:rawPredict"
        else:
            # 其他模型（DeepSeek, Meta, Mistral, GLM）使用 rawPredict / streamRawPredict
            if streaming:
                return f"{base_url}/publishers/{publisher}/models/{model}:streamRawPredict"
            else:
                return f"{base_url}/publishers/{publisher}/models/{model}:rawPredict"

    def supports_model(self, model: str) -> bool:
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        publisher = detect_publisher(model)
        return {
            "description": f"Model on Vertex AI ({publisher}): {model}",
            "context_size": 128000,
            "supports_vision": False,
            "publisher": publisher,
        }

    # ==================== 请求准备（分发） ====================

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """根据模型类型准备不同格式的请求"""
        publisher = self._get_publisher_for_model(request.model)

        if publisher == ModelPublisher.ANTHROPIC:
            return self._prepare_anthropic_request(request)
        elif publisher == ModelPublisher.GOOGLE:
            return self._prepare_gemini_request(request)
        else:
            return self._prepare_openai_request(request)

    # ==================== Anthropic (Claude) 格式 ====================

    def _prepare_anthropic_request(self, request: ChatRequest) -> Dict[str, Any]:
        """准备 Anthropic Messages API 格式的请求体"""
        result = {
            "anthropic_version": self.ANTHROPIC_VERSION,
            "max_tokens": request.max_tokens or 4096,
        }

        system_content = request.get_system_message()
        if system_content:
            result["system"] = system_content

        messages = []
        for msg in request.messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            messages.append(self._message_to_anthropic(msg))
        result["messages"] = messages

        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.stop:
            result["stop_sequences"] = request.stop

        if request.tools:
            result["tools"] = [self._tool_to_anthropic(t) for t in request.tools]
        if request.tool_choice:
            if isinstance(request.tool_choice, str):
                if request.tool_choice == "auto":
                    result["tool_choice"] = {"type": "auto"}
                elif request.tool_choice == "required":
                    result["tool_choice"] = {"type": "any"}
                elif request.tool_choice != "none":
                    result["tool_choice"] = {"type": "tool", "name": request.tool_choice}
            elif isinstance(request.tool_choice, dict):
                result["tool_choice"] = request.tool_choice

        if request.stream:
            result["stream"] = True

        return result

    def _message_to_anthropic(self, message: Message) -> Dict[str, Any]:
        result = {"role": message.role.value}
        if isinstance(message.content, str):
            result["content"] = message.content
        elif isinstance(message.content, list):
            result["content"] = [self._content_block_to_anthropic(b) for b in message.content]
        else:
            result["content"] = ""
        return result

    def _content_block_to_anthropic(self, block: ContentBlock) -> Dict[str, Any]:
        if block.type == ContentType.TEXT:
            return {"type": "text", "text": block.text or ""}
        elif block.type == ContentType.IMAGE_URL:
            return {"type": "image", "source": {"type": "url", "url": block.url}}
        elif block.type == ContentType.IMAGE_BASE64:
            return {"type": "image", "source": {"type": "base64", "media_type": block.media_type or "image/jpeg", "data": block.data}}
        elif block.type == ContentType.TOOL_CALL:
            return {"type": "tool_use", "id": block.tool_call_id, "name": block.tool_name, "input": block.tool_arguments or {}}
        elif block.type == ContentType.TOOL_RESULT:
            return {"type": "tool_result", "tool_use_id": block.tool_call_id, "content": block.tool_result or "", "is_error": block.is_error}
        else:
            return {"type": "text", "text": block.text or ""}

    def _tool_to_anthropic(self, tool: ToolDefinition) -> Dict[str, Any]:
        return {"name": tool.name, "description": tool.description, "input_schema": tool.get_parameters_schema()}

    def _parse_anthropic_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """解析 Anthropic Messages API 格式的响应"""
        content_blocks = response_data.get("content", [])
        tool_calls = []
        message_blocks = []

        for block in content_blocks:
            block_type = block.get("type", "")
            if block_type == "text":
                message_blocks.append(ContentBlock.from_text(block.get("text", "")))
            elif block_type == "tool_use":
                tc_id, tc_name, tc_input = block.get("id", ""), block.get("name", ""), block.get("input", {})
                tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=tc_input, call_type="function"))
                message_blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_input))

        message = Message(role=MessageRole.ASSISTANT, content=message_blocks if message_blocks else None)

        stop_reason = response_data.get("stop_reason", "end_turn")
        finish_reason_map = {"end_turn": FinishReason.STOP, "max_tokens": FinishReason.LENGTH, "tool_use": FinishReason.TOOL_CALLS, "stop_sequence": FinishReason.STOP}
        finish_reason = finish_reason_map.get(stop_reason, FinishReason.STOP)

        usage_data = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            cache_read_tokens=usage_data.get("cache_read_input_tokens", 0),
            cache_write_tokens=usage_data.get("cache_creation_input_tokens", 0),
        )

        return ChatResponse(
            id=response_data.get("id", f"msg_{uuid.uuid4().hex[:12]}"),
            model=response_data.get("model", model),
            choices=[ChatChoice(index=0, message=message, finish_reason=finish_reason, tool_calls=tool_calls)],
            usage=usage, created=int(time.time()), provider=self.PROVIDER_TYPE
        )

    def _parse_anthropic_stream_event(self, event_data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """解析 Anthropic 格式的流式事件"""
        event_type = event_data.get("type", "")

        if event_type == "message_start":
            message = event_data.get("message", {})
            usage = message.get("usage", {})
            return StreamChunk(
                id=message.get("id", response_id), model=message.get("model", model),
                delta_role="assistant", event_type=StreamEventType.CONTENT_DELTA,
                usage={"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": 0, "total_tokens": usage.get("input_tokens", 0)} if usage else None
            )

        elif event_type == "content_block_start":
            content_block = event_data.get("content_block", {})
            if content_block.get("type") == "tool_use":
                return StreamChunk(id=response_id, model=model, tool_calls=[{
                    "index": event_data.get("index", 0), "id": content_block.get("id", ""),
                    "type": "function", "function": {"name": content_block.get("name", ""), "arguments": ""}
                }], event_type=StreamEventType.TOOL_CALL)
            return None

        elif event_type == "content_block_delta":
            delta = event_data.get("delta", {})
            delta_type = delta.get("type", "")
            if delta_type == "text_delta":
                return StreamChunk(id=response_id, model=model, delta_content=delta.get("text", ""), event_type=StreamEventType.CONTENT_DELTA)
            elif delta_type == "thinking_delta":
                return StreamChunk(id=response_id, model=model, delta_reasoning_content=delta.get("thinking", ""), event_type=StreamEventType.CONTENT_DELTA)
            elif delta_type == "input_json_delta":
                return StreamChunk(id=response_id, model=model, tool_calls=[{
                    "index": event_data.get("index", 0), "function": {"arguments": delta.get("partial_json", "")}
                }], event_type=StreamEventType.TOOL_CALL)
            return None

        elif event_type == "message_delta":
            delta = event_data.get("delta", {})
            usage = event_data.get("usage", {})
            stop_reason = delta.get("stop_reason")
            finish_reason = None
            if stop_reason:
                finish_reason = {"end_turn": FinishReason.STOP, "max_tokens": FinishReason.LENGTH, "tool_use": FinishReason.TOOL_CALLS, "stop_sequence": FinishReason.STOP}.get(stop_reason, FinishReason.STOP)
            return StreamChunk(id=response_id, model=model, finish_reason=finish_reason,
                usage={"prompt_tokens": 0, "completion_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("output_tokens", 0)} if usage else None,
                event_type=StreamEventType.USAGE)

        elif event_type == "error":
            error_info = event_data.get("error", {})
            raise RuntimeError(f"Vertex AI Claude stream error: {error_info.get('type', 'unknown')}: {error_info.get('message', 'Unknown error')}")

        return None  # ping, message_stop, content_block_stop, etc.

    # ==================== Gemini (Google) 格式 ====================

    def _prepare_gemini_request(self, request: ChatRequest) -> Dict[str, Any]:
        """准备 Google Gemini generateContent 格式的请求体"""
        result = {}

        # System instruction
        system_content = request.get_system_message()
        if system_content:
            result["system_instruction"] = {
                "parts": [{"text": system_content}]
            }

        # Convert messages to Gemini contents
        contents = []
        for msg in request.messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            contents.append(self._message_to_gemini(msg))
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
        if gen_config:
            result["generationConfig"] = gen_config

        # Tools
        if request.tools:
            result["tools"] = [{"functionDeclarations": [self._tool_to_gemini(t) for t in request.tools]}]
        if request.tool_choice:
            if isinstance(request.tool_choice, str):
                mode_map = {"auto": "AUTO", "none": "NONE", "required": "ANY"}
                mode = mode_map.get(request.tool_choice, "AUTO")
                result["toolConfig"] = {"functionCallingConfig": {"mode": mode}}

        return result

    def _message_to_gemini(self, message: Message) -> Dict[str, Any]:
        """将 Message 转换为 Gemini 格式"""
        # Gemini uses "user" and "model" roles
        role = "model" if message.role == MessageRole.ASSISTANT else "user"

        # Handle tool role - Gemini uses functionResponse parts
        if message.role == MessageRole.TOOL:
            parts = []
            if isinstance(message.content, list):
                for block in message.content:
                    if block.type == ContentType.TOOL_RESULT:
                        parts.append({
                            "functionResponse": {
                                "name": block.tool_name or message.name or "",
                                "response": {"result": block.tool_result or ""}
                            }
                        })
                    elif block.type == ContentType.TEXT:
                        parts.append({
                            "functionResponse": {
                                "name": message.name or "",
                                "response": {"result": block.text or ""}
                            }
                        })
            elif isinstance(message.content, str):
                parts.append({
                    "functionResponse": {
                        "name": message.name or "",
                        "response": {"result": message.content}
                    }
                })
            return {"role": "user", "parts": parts}

        parts = []
        if isinstance(message.content, str):
            parts.append({"text": message.content})
        elif isinstance(message.content, list):
            for block in message.content:
                parts.append(self._content_block_to_gemini(block))
        else:
            parts.append({"text": ""})

        return {"role": role, "parts": parts}

    def _content_block_to_gemini(self, block: ContentBlock) -> Dict[str, Any]:
        """将 ContentBlock 转换为 Gemini parts 格式"""
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
            return {"functionCall": {"name": block.tool_name or "", "args": block.tool_arguments or {}}}
        elif block.type == ContentType.TOOL_RESULT:
            return {"functionResponse": {"name": block.tool_name or "", "response": {"result": block.tool_result or ""}}}
        else:
            return {"text": block.text or ""}

    def _tool_to_gemini(self, tool: ToolDefinition) -> Dict[str, Any]:
        """将 ToolDefinition 转换为 Gemini 格式"""
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.get_parameters_schema()
        }

    def _parse_gemini_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """解析 Gemini generateContent 格式的响应"""
        candidates = response_data.get("candidates", [])
        message_blocks = []
        tool_calls = []
        finish_reason = FinishReason.STOP

        if candidates:
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            for part in parts:
                if "text" in part:
                    message_blocks.append(ContentBlock.from_text(part["text"]))
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tc_id = f"call_{uuid.uuid4().hex[:8]}"
                    tc_name = fc.get("name", "")
                    tc_args = fc.get("args", {})
                    tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=tc_args, call_type="function"))
                    message_blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_args))

            # Map Gemini finish reason
            gemini_finish = candidate.get("finishReason", "STOP")
            finish_map = {"STOP": FinishReason.STOP, "MAX_TOKENS": FinishReason.LENGTH, "SAFETY": FinishReason.CONTENT_FILTER, "RECITATION": FinishReason.STOP}
            finish_reason = finish_map.get(gemini_finish, FinishReason.STOP)
            # If there are function calls, set finish reason to tool_calls
            if tool_calls:
                finish_reason = FinishReason.TOOL_CALLS

        message = Message(role=MessageRole.ASSISTANT, content=message_blocks if message_blocks else None)

        # Parse usage
        usage_metadata = response_data.get("usageMetadata", {})
        usage = UsageInfo(
            prompt_tokens=usage_metadata.get("promptTokenCount", 0),
            completion_tokens=usage_metadata.get("candidatesTokenCount", 0),
            total_tokens=usage_metadata.get("totalTokenCount", 0),
        )

        return ChatResponse(
            id=f"gemini-{uuid.uuid4().hex[:12]}",
            model=model,
            choices=[ChatChoice(index=0, message=message, finish_reason=finish_reason, tool_calls=tool_calls)],
            usage=usage, created=int(time.time()), provider=self.PROVIDER_TYPE
        )

    def _parse_gemini_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """解析 Gemini SSE 流式响应块"""
        candidates = data.get("candidates", [])
        if not candidates:
            # Could be a usage-only chunk
            usage_metadata = data.get("usageMetadata")
            if usage_metadata:
                return StreamChunk(
                    id=response_id, model=model,
                    usage={"prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                           "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                           "total_tokens": usage_metadata.get("totalTokenCount", 0)},
                    event_type=StreamEventType.USAGE
                )
            return None

        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        # Check finish reason
        gemini_finish = candidate.get("finishReason")
        finish_reason = None
        if gemini_finish:
            finish_map = {"STOP": FinishReason.STOP, "MAX_TOKENS": FinishReason.LENGTH, "SAFETY": FinishReason.CONTENT_FILTER}
            finish_reason = finish_map.get(gemini_finish, FinishReason.STOP)

        delta_content = None
        tool_calls_data = []

        for part in parts:
            if "text" in part:
                delta_content = (delta_content or "") + part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tc_id = f"call_{uuid.uuid4().hex[:8]}"
                tool_calls_data.append({
                    "index": 0, "id": tc_id, "type": "function",
                    "function": {"name": fc.get("name", ""), "arguments": json.dumps(fc.get("args", {}), ensure_ascii=False)}
                })
                if not finish_reason:
                    finish_reason = FinishReason.TOOL_CALLS

        # Determine role from content
        delta_role = content.get("role")
        if delta_role == "model":
            delta_role = "assistant"

        return StreamChunk(
            id=response_id, model=model,
            delta_content=delta_content, delta_role=delta_role,
            tool_calls=tool_calls_data if tool_calls_data else [],
            finish_reason=finish_reason,
            event_type=StreamEventType.CONTENT_DELTA
        )

    # ==================== OpenAI 兼容格式 (DeepSeek, GLM, Meta, Mistral) ====================

    def _prepare_openai_request(self, request: ChatRequest) -> Dict[str, Any]:
        """准备 OpenAI 兼容格式的请求体（用于 DeepSeek, GLM, Meta, Mistral 等）"""
        result = {
            "model": request.model,
            "messages": [self._message_to_openai(msg) for msg in request.messages],
            "stream": request.stream,
        }

        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.max_tokens is not None:
            result["max_tokens"] = request.max_tokens
        if request.tools:
            result["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.get_parameters_schema()}} for t in request.tools]
        if request.tool_choice:
            result["tool_choice"] = request.tool_choice
        if request.stop:
            result["stop"] = request.stop

        return result

    def _message_to_openai(self, message: Message) -> Dict[str, Any]:
        """将 Message 转换为 OpenAI 格式"""
        result = {"role": message.role.value}

        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id
        if message.name:
            result["name"] = message.name

        if isinstance(message.content, str):
            result["content"] = message.content
        elif isinstance(message.content, list):
            text_blocks = [b for b in message.content if b.type == ContentType.TEXT]
            tool_call_blocks = [b for b in message.content if b.type == ContentType.TOOL_CALL]
            other_blocks = [b for b in message.content if b.type not in (ContentType.TEXT, ContentType.TOOL_CALL, ContentType.TOOL_RESULT)]

            # For tool result blocks, extract text content
            tool_result_blocks = [b for b in message.content if b.type == ContentType.TOOL_RESULT]
            if tool_result_blocks and not text_blocks and not other_blocks:
                result["content"] = " ".join(b.tool_result or "" for b in tool_result_blocks)
            elif text_blocks and not other_blocks:
                result["content"] = " ".join(b.text or "" for b in text_blocks)
            elif text_blocks or other_blocks:
                content_parts = []
                for b in text_blocks:
                    content_parts.append({"type": "text", "text": b.text or ""})
                for b in other_blocks:
                    if b.type == ContentType.IMAGE_URL:
                        content_parts.append({"type": "image_url", "image_url": {"url": b.url}})
                    elif b.type == ContentType.IMAGE_BASE64:
                        content_parts.append({"type": "image_url", "image_url": {"url": f"data:{b.media_type or 'image/jpeg'};base64,{b.data}"}})
                    else:
                        content_parts.append({"type": "text", "text": b.text or ""})
                result["content"] = content_parts

            if tool_call_blocks:
                result["tool_calls"] = [{
                    "id": b.tool_call_id, "type": "function",
                    "function": {"name": b.tool_name, "arguments": b.tool_arguments if isinstance(b.tool_arguments, str) else json.dumps(b.tool_arguments or {}, ensure_ascii=False)}
                } for b in tool_call_blocks]
        else:
            result["content"] = ""

        return result

    def _parse_openai_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """解析 OpenAI 兼容格式的响应"""
        choices = []
        for choice_data in response_data.get("choices", []):
            message_data = choice_data.get("message", {})
            message_blocks = []
            tool_calls = []

            content = message_data.get("content")
            if content:
                message_blocks.append(ContentBlock.from_text(content))

            if "tool_calls" in message_data:
                for tc in message_data["tool_calls"]:
                    tc_id = tc.get("id", "")
                    func = tc.get("function", {})
                    tc_name = func.get("name", "")
                    tc_args = func.get("arguments", "{}")
                    if isinstance(tc_args, str):
                        try:
                            tc_args = json.loads(tc_args)
                        except json.JSONDecodeError:
                            tc_args = {}
                    tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=tc_args, call_type="function"))
                    message_blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_args))

            message = Message(role=MessageRole.ASSISTANT, content=message_blocks if message_blocks else content)

            fr_str = choice_data.get("finish_reason")
            finish_reason = FinishReason(fr_str) if fr_str else FinishReason.STOP

            choices.append(ChatChoice(index=choice_data.get("index", 0), message=message, finish_reason=finish_reason, tool_calls=tool_calls))

        usage_data = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatResponse(
            id=response_data.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
            model=model, choices=choices, usage=usage,
            created=response_data.get("created", int(time.time())),
            provider=self.PROVIDER_TYPE
        )

    def _parse_openai_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """解析 OpenAI 兼容格式的流式响应块"""
        choices = data.get("choices", [])
        usage = data.get("usage")

        if not choices:
            # Handle usage-only chunks
            if usage:
                return StreamChunk(
                    id=data.get("id", response_id), model=data.get("model", model),
                    usage=usage, event_type=StreamEventType.USAGE,
                    created=data.get("created", int(time.time()))
                )
            return None

        choice = choices[0]
        delta = choice.get("delta", {})

        content = delta.get("content")
        role = delta.get("role")
        reasoning_content = delta.get("reasoning_content")

        fr_str = choice.get("finish_reason")
        finish_reason = None
        if fr_str:
            try:
                finish_reason = FinishReason(fr_str)
            except ValueError:
                finish_reason = FinishReason.STOP

        tool_calls = delta.get("tool_calls", [])

        return StreamChunk(
            id=data.get("id", response_id), model=data.get("model", model),
            delta_content=content, delta_role=role,
            delta_reasoning_content=reasoning_content,
            tool_calls=tool_calls, finish_reason=finish_reason,
            usage=usage,
            created=data.get("created", int(time.time()))
        )

    # ==================== 响应解析（分发） ====================

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """根据模型类型解析不同格式的响应"""
        publisher = self._get_publisher_for_model(model)
        if publisher == ModelPublisher.ANTHROPIC:
            return self._parse_anthropic_response(response_data, model)
        elif publisher == ModelPublisher.GOOGLE:
            return self._parse_gemini_response(response_data, model)
        else:
            return self._parse_openai_response(response_data, model)

    # ==================== 主接口 ====================

    def chat(self, request: ChatRequest) -> ChatResponse:
        """执行非流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        publisher = self._get_publisher_for_model(request.model)
        request_data = self.prepare_request(request)

        # Anthropic rawPredict 不需要 stream 参数
        if publisher == ModelPublisher.ANTHROPIC:
            request_data.pop("stream", None)

        url = self._get_api_url(request.model, streaming=False)
        headers = self.get_headers()

        print(f"[VertexAI {publisher}] URL: {url}", file=sys.stderr)
        print(f"[VertexAI {publisher}] Request: {json.dumps(request_data, ensure_ascii=False, indent=2)}", file=sys.stderr)

        try:
            response = self.client.post(url, json=request_data, headers=headers)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    print(f"[VertexAI {publisher}] Error: {json.dumps(error_data, ensure_ascii=False)}", file=sys.stderr)
                    raise RuntimeError(f"Vertex AI API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    raise RuntimeError(f"Vertex AI API error ({response.status_code}): {response.text}")

            response_data = response.json()
            print(f"[VertexAI {publisher}] Response: {json.dumps(response_data, ensure_ascii=False, indent=2)}", file=sys.stderr)

            return self.parse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Vertex AI API error ({publisher}): {str(e)}")

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        publisher = self._get_publisher_for_model(request.model)
        request_data = self.prepare_request(request)

        # Ensure stream flag is set appropriately
        if publisher == ModelPublisher.ANTHROPIC:
            request_data["stream"] = True
        elif publisher != ModelPublisher.GOOGLE:
            # OpenAI-compatible models
            request_data["stream"] = True

        url = self._get_api_url(request.model, streaming=True)
        headers = self.get_headers()
        response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        print(f"[VertexAI {publisher} Stream] URL: {url}", file=sys.stderr)
        print(f"[VertexAI {publisher} Stream] Request: {json.dumps(request_data, ensure_ascii=False, indent=2)}", file=sys.stderr)

        try:
            with self.client.stream("POST", url, json=request_data, headers=headers) as response:
                if response.status_code >= 400:
                    error_text = ""
                    for chunk in response.iter_bytes():
                        if chunk:
                            error_text += chunk.decode('utf-8')
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(f"Vertex AI API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        raise RuntimeError(f"Vertex AI API error ({response.status_code}): {error_text}")

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

                        chunk = self._dispatch_stream_parse(publisher, event_data, response_id, request.model)
                        if chunk:
                            yield chunk

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Vertex AI streaming API error ({publisher}): {str(e)}")

    def _dispatch_stream_parse(self, publisher: str, event_data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """根据发布者类型分发流式解析"""
        if publisher == ModelPublisher.ANTHROPIC:
            return self._parse_anthropic_stream_event(event_data, response_id, model)
        elif publisher == ModelPublisher.GOOGLE:
            return self._parse_gemini_stream_chunk(event_data, response_id, model)
        else:
            return self._parse_openai_stream_chunk(event_data, response_id, model)

    def list_models(self) -> List[Dict[str, Any]]:
        """列出支持的模型"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": f"vertexai-{info.get('publisher', 'unknown')}",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 128000),
                "supports_vision": info.get("supports_vision", False),
            })
        return models


# Keep backward-compatible alias
VertexAIClaudeProvider = VertexAIProvider
