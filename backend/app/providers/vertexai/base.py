"""
Google Vertex AI 供应商基础实现 (Vertex AI Base Provider)
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
import logging
import os
import sys
import traceback

from ..base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall, ToolParameter, ToolType
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.utils import gen_id, json_loads
from app.providers.vertexai.image_generation import (
    is_vertexai_image_model,
    has_vertexai_image_generation_tool,
    inject_image_generation_config,
    handle_image_generation_response,
    stream_vertexai_image_generation,
)
from app.providers.vertexai.video_generation import (
    is_vertexai_video_model,
    has_vertexai_video_generation_tool,
    execute_vertexai_veo_generation,
    stream_vertexai_veo_generation,
)

# Configure logger for VertexAI provider
logger = logging.getLogger("vertexai")


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


# Log directory for large request/response data
LOG_DIR = "/tmp/vertexai_logs"

def _log_to_file(data: Any, prefix: str, publisher: str) -> str:
    """
    Log large data to a file instead of console
    
    Args:
        data: Data to log (will be JSON serialized)
        prefix: Prefix for the log filename (e.g., "request", "response")
        publisher: Publisher name for logging
    
    Returns:
        Path to the log file
    """
    # Create log directory if it doesn't exist
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    
    # Generate filename with timestamp
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{publisher}_{timestamp}_{uuid.uuid4().hex[:8]}.json"
    filepath = os.path.join(LOG_DIR, filename)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filepath
    except Exception as e:
        logger.error(f"Failed to write log file: {e}")
        return ""


# In-memory cache for thoughtSignature mapping: tool_call_id -> thoughtSignature
# This is needed because Vertex AI requires thoughtSignature to be passed back with functionResponse
_thought_signature_cache: Dict[str, str] = {}


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

    # Default Vertex AI base URL template (requires PROJECT_ID)
    DEFAULT_BASE_URL_TEMPLATE = "https://aiplatform.googleapis.com/v1/projects/{project_id}/locations/global"

    def __init__(self, config: ProviderConfig):
        """
        初始化 Vertex AI 供应商

        Args:
            config: 供应商配置
                - base_url: Vertex AI 端点 URL (格式: https://aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/global)
                - api_key: 服务账号 JSON 密钥内容（或留空使用 ADC）
        """
        # Will set base_url after getting project_id from credentials
        self._project_id = None
        self._pending_base_url = config.base_url
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
                # Extract project_id from service account
                self._project_id = service_account_info.get("project_id")
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(
                    f"Invalid service account JSON in api_key: {e}. "
                    "Please provide the full JSON content of the service account key file."
                )
        else:
            self._credentials, project_id = google.auth.default(scopes=scopes)
            self._project_id = project_id

        # Set default base_url if not provided
        if not self._pending_base_url and self._project_id:
            self.config.base_url = self.DEFAULT_BASE_URL_TEMPLATE.format(project_id=self._project_id)
        elif self._pending_base_url:
            self.config.base_url = self._pending_base_url

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
        logger.debug(f"Obtained access token for Vertex AI")
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

    @property
    def client(self) -> Any:
        """获取 HTTP 客户端"""
        import httpx
        if self._client is None:
            self._client = httpx.Client(timeout=self.DEFAULT_TIMEOUT)
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

        # system 消息直接透传（支持 string 或 List[Dict] 含 cache_control）
        if request.system is not None:
            result["system"] = request.system

        messages = []
        for msg in request.messages:
            if msg.role.is_system_like():
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
        """将 Message 转换为 Anthropic 格式"""
        result = {"role": message.role.value}
        
        if isinstance(message.content, str):
            result["content"] = message.content
        elif isinstance(message.content, list):
            result["content"] = [self._content_block_to_anthropic(b) for b in message.content]
        else:
            result["content"] = ""
        return result

    def _content_block_to_anthropic(self, block: ContentBlock) -> Dict[str, Any]:
        """将 ContentBlock 转换为 Anthropic 格式，保留 cache_control"""
        result: Dict[str, Any]
        if block.type == ContentType.TEXT:
            result = {"type": "text", "text": block.text or ""}
        elif block.type == ContentType.IMAGE_URL:
            result = {"type": "image", "source": {"type": "url", "url": block.url}}
        elif block.type == ContentType.IMAGE_BASE64:
            result = {"type": "image", "source": {"type": "base64", "media_type": block.media_type or "image/jpeg", "data": block.data}}
        elif block.type == ContentType.TOOL_CALL:
            result = {"type": "tool_use", "id": block.tool_call_id, "name": block.tool_name, "input": block.tool_arguments or {}}
        elif block.type == ContentType.TOOL_RESULT:
            result = {"type": "tool_result", "tool_use_id": block.tool_call_id, "content": block.tool_result or "", "is_error": block.is_error}
        elif block.type in (ContentType.FILE_URL, ContentType.FILE_BASE64):
            if block.type == ContentType.FILE_URL:
                result = {"type": "document", "source": {"type": "url", "url": block.url}}
            else:
                result = {"type": "document", "source": {"type": "base64", "media_type": block.media_type or "application/pdf", "data": block.data}}
        else:
            result = {"type": "text", "text": block.text or ""}
        # Attach cache_control if present
        if block.cache_control:
            result["cache_control"] = block.cache_control
        return result

    def _tool_to_anthropic(self, tool: ToolDefinition) -> Dict[str, Any]:
        """将 ToolDefinition 转换为 Anthropic 格式，保留 cache_control"""
        result = {"name": tool.name, "description": tool.description, "input_schema": tool.get_parameters_schema()}
        if tool.cache_control:
            result["cache_control"] = tool.cache_control
        return result

    def _parse_anthropic_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """解析 Anthropic Messages API 格式的响应"""
        content_blocks = response_data.get("content", [])
        tool_calls = []
        message_blocks = []
        thinking_parts = []

        for block in content_blocks:
            block_type = block.get("type", "")
            if block_type == "thinking":
                # Claude extended thinking block - collect thinking summary
                thinking_text = block.get("thinking", "")
                if thinking_text:
                    thinking_parts.append(thinking_text)
            elif block_type == "text":
                message_blocks.append(ContentBlock.from_text(block.get("text", "")))
            elif block_type == "tool_use":
                tc_id, tc_name, tc_input = block.get("id", ""), block.get("name", ""), block.get("input", {})
                tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=tc_input, call_type="function"))
                message_blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_input))

        message = Message(role=MessageRole.ASSISTANT, content=message_blocks if message_blocks else None)

        # Combine all thinking parts into reasoning_content
        reasoning_content = "\n\n".join(thinking_parts) if thinking_parts else None

        stop_reason = response_data.get("stop_reason", "end_turn")
        finish_reason_map = {"end_turn": FinishReason.STOP, "max_tokens": FinishReason.LENGTH, "tool_use": FinishReason.TOOL_CALLS, "stop_sequence": FinishReason.STOP}
        finish_reason = finish_reason_map.get(stop_reason, FinishReason.STOP)

        # Anthropic returns input_tokens that EXCLUDES both
        # cache_creation_input_tokens and cache_read_input_tokens.
        # Add both into prompt_tokens to unify with OpenAI convention
        # (prompt_tokens INCLUDES all cached tokens) for correct billing.
        usage_data = response_data.get("usage", {})
        raw_input_tokens = usage_data.get("input_tokens", 0)
        cache_creation = usage_data.get("cache_creation_input_tokens", 0)
        cache_read = usage_data.get("cache_read_input_tokens", 0)
        output_tokens_val = usage_data.get("output_tokens", 0)
        prompt_tokens_val = raw_input_tokens + cache_creation + cache_read
        extra: Dict[str, Any] = {}
        # 透传 cache_creation 嵌套对象（包含 ephemeral_5m_input_tokens 等）
        if "cache_creation" in usage_data:
            extra["cache_creation"] = usage_data["cache_creation"]
        usage = UsageInfo(
            prompt_tokens=prompt_tokens_val,
            completion_tokens=output_tokens_val,
            total_tokens=prompt_tokens_val + output_tokens_val,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_creation,
            extra=extra,
        )

        return ChatResponse(
            id=response_data.get("id", gen_id("msg")),
            model=response_data.get("model", model),
            choices=[ChatChoice(index=0, message=message, finish_reason=finish_reason, tool_calls=tool_calls, reasoning_content=reasoning_content)],
            usage=usage, created=int(time.time()), provider=self.PROVIDER_TYPE
        )

    def _parse_anthropic_stream_event(self, event_data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """解析 Anthropic 格式的流式事件"""
        event_type = event_data.get("type", "")

        if event_type == "message_start":
            message = event_data.get("message", {})
            usage = message.get("usage", {})
            usage_info = None
            if usage:
                extra: Dict[str, Any] = {}
                # 透传 cache_creation 嵌套对象（包含 ephemeral_5m_input_tokens 等）
                if "cache_creation" in usage:
                    extra["cache_creation"] = usage["cache_creation"]
                raw_input_tokens = usage.get("input_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                # Anthropic input_tokens EXCLUDES both cache_creation_input_tokens
                # and cache_read_input_tokens.  Add both into prompt_tokens to
                # unify with OpenAI convention (prompt_tokens INCLUDES all cached
                # tokens) for correct billing.
                prompt_tokens = raw_input_tokens + cache_creation + cache_read
                usage_info = UsageInfo(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=prompt_tokens + output_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_creation,
                    extra=extra,
                )
            return StreamChunk(
                id=message.get("id", response_id), model=message.get("model", model),
                delta_role="assistant", event_type=StreamEventType.CONTENT_DELTA,
                is_first_chunk=True,
                usage=usage_info
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
            usage_info = None
            if usage:
                raw_input_tokens = usage.get("input_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                # Anthropic input_tokens EXCLUDES both cache_creation_input_tokens
                # and cache_read_input_tokens.  Add both into prompt_tokens to
                # unify with OpenAI convention (prompt_tokens INCLUDES all cached
                # tokens) for correct billing.
                prompt_tokens = raw_input_tokens + cache_creation + cache_read
                usage_info = UsageInfo(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=prompt_tokens + output_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_creation,
                )
            return StreamChunk(id=response_id, model=model, finish_reason=finish_reason,
                usage=usage_info,
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
            if msg.role.is_system_like():
                continue
            gemini_msg = self._message_to_gemini(msg, call_id_to_name)
            if gemini_msg:
                # Merge consecutive same-role messages (Gemini requires alternating roles)
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
        # Only enable when model supports thinking AND reasoning_effort is not 'none'
        if request.metadata.get('support_thinking', False):
            reasoning_effort = request.reasoning_effort or 'none'
            gen_config["thinkingConfig"] = {
                "includeThoughts": reasoning_effort != 'none'
            }
        elif request.reasoning_effort and request.reasoning_effort != 'none':
            gen_config["thinkingConfig"] = {
                "includeThoughts": True
            }

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

    def _message_to_gemini(self, message: Message, call_id_to_name: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """将 Message 转换为 Gemini 格式

        Args:
            message: 消息对象
            call_id_to_name: tool_call_id → function name 映射表
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
                        # Use block's tool_call_id, or fall back to message's tool_call_id
                        bid = block.tool_call_id or call_id
                        # Get function name from block, message, or lookup by id
                        name = block.tool_name or message.name or call_id_to_name.get(bid, "")
                        # Note: Vertex AI does not accept "id" in functionResponse
                        # response must be an object with "result" key
                        fr: Dict[str, Any] = {
                            "name": name,
                            "response": {"result": block.tool_result or ""}
                        }
                        parts.append({"functionResponse": fr})
                    elif block.type == ContentType.TEXT:
                        name = message.name or call_id_to_name.get(call_id, "")
                        # Note: Vertex AI does not accept "id" in functionResponse
                        # response must be an object with "result" key
                        fr = {
                            "name": name,
                            "response": {"result": block.text or ""}
                        }
                        parts.append({"functionResponse": fr})
            elif isinstance(message.content, str):
                name = message.name or call_id_to_name.get(call_id, "")
                # Note: Vertex AI does not accept "id" in functionResponse
                # response must be an object with "result" key
                fr = {
                    "name": name,
                    "response": {"result": message.content}
                }
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
        """将 ContentBlock 转换为 Gemini parts 格式"""
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
            # Note: Vertex AI does not accept "id" in functionCall when sending request
            fc: Dict[str, Any] = {"name": block.tool_name or "", "args": block.tool_arguments or {}}
            part: Dict[str, Any] = {"functionCall": fc}
            # Include thoughtSignature from cache if available (required for multi-turn tool calls)
            if block.tool_call_id and block.tool_call_id in _thought_signature_cache:
                part["thoughtSignature"] = _thought_signature_cache[block.tool_call_id]
            return part
        elif block.type == ContentType.TOOL_RESULT:
            bid = block.tool_call_id or ""
            name = block.tool_name or call_id_to_name.get(bid, "")
            # Note: Vertex AI does not accept "id" in functionResponse
            # response must be an object with "result" key
            fr: Dict[str, Any] = {"name": name, "response": {"result": block.tool_result or ""}}
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

    def _parse_gemini_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """解析 Gemini generateContent 格式的响应"""
        candidates = response_data.get("candidates", [])
        message_blocks = []
        tool_calls = []
        thinking_parts = []
        finish_reason = FinishReason.STOP

        if candidates:
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            for part in parts:
                if "text" in part:
                    # Gemini 2.5 models return thought parts with "thought": true
                    if part.get("thought", False):
                        thinking_parts.append(part["text"])
                    else:
                        message_blocks.append(ContentBlock.from_text(part["text"]))
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    # Use the id from the functionCall if provided, otherwise generate one
                    tc_id = fc.get("id") or gen_id("call")
                    tc_name = fc.get("name", "")
                    tc_args = fc.get("args", {})
                    # Capture thoughtSignature if present (required for multi-turn tool calls)
                    # Store in cache for later retrieval when building functionResponse
                    thought_sig = part.get("thoughtSignature")
                    if thought_sig:
                        _thought_signature_cache[tc_id] = thought_sig
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

        # Combine all thinking parts into reasoning_content
        reasoning_content = "\n\n".join(thinking_parts) if thinking_parts else None

        # Parse usage
        usage_metadata = response_data.get("usageMetadata", {})
        usage = UsageInfo(
            prompt_tokens=usage_metadata.get("promptTokenCount", 0),
            completion_tokens=usage_metadata.get("candidatesTokenCount", 0),
            total_tokens=usage_metadata.get("totalTokenCount", 0),
        )

        return ChatResponse(
            id=gen_id("resp"),
            model=model,
            choices=[ChatChoice(index=0, message=message, finish_reason=finish_reason, tool_calls=tool_calls, reasoning_content=reasoning_content)],
            usage=usage, created=int(time.time()), provider=self.PROVIDER_TYPE
        )

    def _parse_gemini_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """解析 Gemini SSE 流式响应块"""
        candidates = data.get("candidates", [])
        if not candidates:
            # Could be a usage-only chunk (no candidates)
            usage_metadata = data.get("usageMetadata")
            if usage_metadata:
                pt = usage_metadata.get("promptTokenCount", 0)
                ct = usage_metadata.get("candidatesTokenCount", 0)
                tt = usage_metadata.get("totalTokenCount", 0)
                # Skip intermediate acknowledgment chunks where all usage values are zero;
                # these are empty ACK frames Vertex AI inserts between tool-call turns.
                if pt == 0 and ct == 0 and tt == 0:
                    return None
                return StreamChunk(
                    id=response_id, model=model,
                    usage=UsageInfo(prompt_tokens=pt, completion_tokens=ct, total_tokens=tt),
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
        delta_reasoning_content = None
        tool_calls_data = []

        for part in parts:
            if "text" in part:
                # Gemini 2.5 models return thought parts with "thought": true
                if part.get("thought", False):
                    delta_reasoning_content = (delta_reasoning_content or "") + part["text"]
                else:
                    delta_content = (delta_content or "") + part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tc_id = gen_id("call")
                # Capture thoughtSignature if present (required for multi-turn tool calls)
                # Store in cache for later retrieval when building functionResponse
                thought_sig = part.get("thoughtSignature")
                if thought_sig:
                    _thought_signature_cache[tc_id] = thought_sig
                tool_calls_data.append({
                    "index": 0, "id": tc_id, "type": "function",
                    "function": {"name": fc.get("name", ""), "arguments": json.dumps(fc.get("args", {}), ensure_ascii=False)}
                })

        # When tool calls are present, correct the finish_reason:
        # - If Gemini set a finish reason (e.g. "STOP"), override it to TOOL_CALLS.
        # - If Gemini did NOT set a finish reason (intermediate chunk), leave it as None
        #   so we don't emit a premature finish_reason on non-final tool-call chunks.
        if tool_calls_data and finish_reason is not None:
            finish_reason = FinishReason.TOOL_CALLS

        # Parse usage if present in this chunk.
        # Only include non-zero usage to avoid the to_sse split-logic generating a
        # spurious empty-choices usage chunk for tool-call ACK frames (which carry
        # all-zero usageMetadata as acknowledgment, not real token counts).
        usage_info: Optional[UsageInfo] = None
        usage_metadata = data.get("usageMetadata")
        if usage_metadata:
            pt = usage_metadata.get("promptTokenCount", 0)
            ct = usage_metadata.get("candidatesTokenCount", 0)
            tt = usage_metadata.get("totalTokenCount", 0)
            if pt or ct or tt:
                usage_info = UsageInfo(prompt_tokens=pt, completion_tokens=ct, total_tokens=tt)

        # When there are no content parts and finish_reason is STOP, Vertex AI Gemini is
        # sending an end-of-stream marker.  Use "not delta_content" (falsy check) so that
        # an empty-string text part emitted by Gemini ({"text": ""}) is treated the same
        # as a missing text part.
        #
        # We always return a StreamChunk so that stream_chat() can:
        #   a) override finish_reason STOP→TOOL_CALLS when tool calls were seen earlier
        #   b) split finish + usage into two SSE events via to_sse()
        if (not delta_content and not delta_reasoning_content and
                not tool_calls_data and finish_reason == FinishReason.STOP):
            return StreamChunk(
                id=response_id, model=model,
                finish_reason=finish_reason,  # preserved; stream_chat may override
                usage=usage_info,  # may be None if separate usage frame follows
                event_type=StreamEventType.USAGE
            )

        # Determine role from content
        delta_role = content.get("role")
        if delta_role == "model":
            delta_role = "assistant"

        return StreamChunk(
            id=response_id, model=model,
            delta_content=delta_content, delta_role=delta_role,
            delta_reasoning_content=delta_reasoning_content,
            tool_calls=tool_calls_data if tool_calls_data else [],
            finish_reason=finish_reason,
            usage=usage_info,
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
                            tc_args = json_loads(tc_args)
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
            id=response_data.get("id", gen_id("chatcmpl")),
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

    # ==================== Image / Video Generation 检测 ====================

    def is_image_generation_model(self, model: str) -> bool:
        """Check if the model is a Gemini image generation model."""
        return is_vertexai_image_model(model)

    def _has_image_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request contains an image_generation tool."""
        return has_vertexai_image_generation_tool(request)

    def is_video_generation_model(self, model: str) -> bool:
        """Check if the model is a Veo video generation model."""
        return is_vertexai_video_model(model)

    def _has_video_generation_tool(self, request: ChatRequest) -> bool:
        """Check if the request carries a video_generation tool flag."""
        return has_vertexai_video_generation_tool(request)

    # ==================== Video Generation (Veo on Vertex AI) ====================

    def _execute_vertexai_veo_generation(self, request: ChatRequest) -> ChatResponse:
        """
        Execute Veo video generation via Vertex AI predictLongRunning endpoint.
        Delegates to the vertexai.video_generation module.
        """
        # IMPORTANT: call get_headers() BEFORE reading self.config.base_url.
        # get_headers() triggers _get_credentials() which sets self.config.base_url
        # from the service account project_id when no explicit base_url is configured.
        self.get_headers()
        return execute_vertexai_veo_generation(
            request=request,
            get_headers_fn=self.get_headers,
            base_url=self.config.base_url,
            project_id=self._project_id,
            provider_type=self.PROVIDER_TYPE,
            tracer=self.tracer,
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

        # ── Video generation (Veo) via Vertex AI ──────────────────────────
        if publisher == ModelPublisher.GOOGLE and (
            self.is_video_generation_model(request.model)
            or self._has_video_generation_tool(request)
        ):
            return self._execute_vertexai_veo_generation(request)

        try:
            request_data = self.prepare_request(request)
        except Exception as e:
            logger.error(f"[VertexAI {publisher}] Request preparation error: {type(e).__name__}: {e}")
            raise

        # ── Image generation: inject responseModalities ───────────────────
        if publisher == ModelPublisher.GOOGLE and (
            self.is_image_generation_model(request.model)
            or self._has_image_generation_tool(request)
        ):
            inject_image_generation_config(request_data)

        # Anthropic rawPredict 不需要 stream 参数
        if publisher == ModelPublisher.ANTHROPIC:
            request_data.pop("stream", None)

        headers = self.get_headers()
        url = self._get_api_url(request.model, streaming=False)

        logger.debug(f"[VertexAI {publisher}] URL: {url}")

        try:
            req_timeout = self._get_request_timeout(request)
            with self._trace_call(request.model, input_data=request_data) as child_span:
                response = self.client.post(url, json=request_data, headers=headers, **({"timeout": req_timeout} if req_timeout else {}))

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        raise RuntimeError(f"Vertex AI API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        raise RuntimeError(f"Vertex AI API error ({response.status_code}): {error_text[:500]}")

                try:
                    response_data = response.json()
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"Vertex AI API response parse error: {e}, raw response: {response.text[:500]}")

                if child_span:
                    child_span.log_output(response_data)

                # ── Intercept Gemini image generation responses ────────────────
                if publisher == ModelPublisher.GOOGLE and (
                    self.is_image_generation_model(request.model)
                    or self._has_image_generation_tool(request)
                ):
                    img_response = handle_image_generation_response(
                        response_data, request.model, self.PROVIDER_TYPE,
                        response_format=request.metadata.get('response_format', 'b64_json'),
                    )
                    if img_response:
                        # Enrich image generation usage with resolution/aspect from request metadata
                        if img_response.usage and img_response.usage.extra:
                            meta = request.metadata
                            size = str(meta.get('size', ''))
                            ar = str(meta.get('aspect_ratio', ''))
                            res = str(meta.get('resolution', ''))
                            from app.providers.image_size_utils import resolve_image_size
                            resolved_aspect, resolved_tier = resolve_image_size(
                                size=size, aspect_ratio=ar,
                                resolution=res,
                            )
                            if resolved_tier:
                                img_response.usage.extra['output_image_resolution'] = resolved_tier
                            if resolved_aspect:
                                img_response.usage.extra['output_image_aspect'] = resolved_aspect
                            # Propagate the requested response_format so the Responses API
                            # adapter can decide between url / b64_json output.
                            img_response.usage.extra['_response_format'] = (
                                meta.get('response_format', 'b64_json')
                            )
                        return img_response

                return self.parse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[VertexAI {publisher}] Unexpected error: {type(e).__name__}: {e}")
            raise RuntimeError(f"Vertex AI API error ({publisher}): {str(e)}")

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        publisher = self._get_publisher_for_model(request.model)

        # ── Video generation (Veo) via Vertex AI ──────────────────────────
        if publisher == ModelPublisher.GOOGLE and (
            self.is_video_generation_model(request.model)
            or self._has_video_generation_tool(request)
        ):
            yield from stream_vertexai_veo_generation(self.chat, request)
            return

        # ── Image generation via Vertex AI Gemini ─────────────────────────
        if publisher == ModelPublisher.GOOGLE and (
            self.is_image_generation_model(request.model)
            or self._has_image_generation_tool(request)
        ):
            yield from stream_vertexai_image_generation(self.chat, request)
            return

        try:
            request_data = self.prepare_request(request)
        except Exception as e:
            logger.error(f"[VertexAI {publisher}] Request preparation error: {type(e).__name__}: {e}")
            raise

        # Ensure stream flag is set appropriately
        if publisher == ModelPublisher.ANTHROPIC:
            request_data["stream"] = True
        elif publisher != ModelPublisher.GOOGLE:
            # OpenAI-compatible models
            request_data["stream"] = True

        headers = self.get_headers()
        url = self._get_api_url(request.model, streaming=True)
        response_id = gen_id("resp")

        logger.debug(f"[VertexAI {publisher} Stream] URL: {url}")

        # Track whether any tool calls were seen during this Gemini stream so we can fix
        # the trailing end-of-stream STOP marker (Gemini emits finishReason=STOP on the
        # final empty chunk even when the response was actually tool_calls).
        gemini_saw_tool_calls = False

        try:
            req_timeout = self._get_request_timeout(request)
            with self._trace_call(request.model, input_data=request_data), \
                 self.client.stream("POST", url, json=request_data, headers=headers, **({"timeout": req_timeout} if req_timeout else {})) as response:
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
                        except json.JSONDecodeError as e:
                            logger.warning(f"[VertexAI {publisher} Stream] Failed to parse SSE data: {e}")
                            continue

                        try:
                            chunk = self._dispatch_stream_parse(publisher, event_data, response_id, request.model)
                            if chunk:
                                # For Gemini: track tool calls and fix trailing STOP→TOOL_CALLS.
                                if publisher == ModelPublisher.GOOGLE:
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
                        except Exception as e:
                            logger.error(f"[VertexAI {publisher} Stream] Stream chunk parse error: {type(e).__name__}: {e}")
                            raise

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[VertexAI {publisher} Stream] Unexpected error: {type(e).__name__}: {e}")
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
