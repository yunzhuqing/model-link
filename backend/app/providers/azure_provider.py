"""
Azure OpenAI 供应商实现 (Azure OpenAI Provider)
实现 Azure OpenAI API 的调用。
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid

from .base import BaseProvider, ProviderConfig, ProviderCapability
from .openai_provider import OpenAIProvider, parse_openai_request
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk


class AzureProvider(OpenAIProvider):
    """
    Azure OpenAI 供应商实现
    
    提供 Azure OpenAI API 的调用能力。
    Azure OpenAI 使用与 OpenAI 兼容的 API，但有以下不同：
    1. 认证方式：使用 api-key 头而不是 Bearer token
    2. URL 结构：需要包含部署名称和 API 版本
    3. 基础 URL 格式：https://{resource-name}.openai.azure.com
    """
    
    PROVIDER_TYPE: str = "azure"
    
    # Azure OpenAI 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
    ]
    
    # Azure API 版本
    DEFAULT_API_VERSION = "2025-01-01-preview"
    
    # Azure OpenAI 支持的模型列表（部署名称由用户自定义）
    SUPPORTED_MODELS = {
        "gpt-4o": {
            "description": "GPT-4o - 最先进的多模态模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4o-mini": {
            "description": "GPT-4o mini - 快速且经济的多模态模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4-turbo": {
            "description": "GPT-4 Turbo - 更快的 GPT-4",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4": {
            "description": "GPT-4 - 高级推理能力",
            "context_size": 8192,
            "supports_vision": False,
        },
        "gpt-35-turbo": {
            "description": "GPT-3.5 Turbo - 快速且经济",
            "context_size": 16385,
            "supports_vision": False,
        },
    }
    
    def __init__(self, config: ProviderConfig):
        """
        初始化 Azure OpenAI 供应商
        
        Args:
            config: 供应商配置
                - base_url: Azure 资源 URL (e.g., https://your-resource.openai.azure.com)
                - api_key: Azure API 密钥
                - extra_config: 可包含 'api_version' 和 'deployment_name'
        """
        # 设置默认 API 版本
        if not config.extra_config:
            config.extra_config = {}
        
        if 'api_version' not in config.extra_config:
            config.extra_config['api_version'] = self.DEFAULT_API_VERSION
        
        # 不设置默认 base_url，用户必须提供
        super().__init__(config)
    
    # Azure 使用与 OpenAI 相同的 get_headers (Bearer token)
    # 继承自 OpenAIProvider，无需重写
    
    @property
    def api_version(self) -> str:
        """获取 API 版本"""
        return self.config.extra_config.get('api_version', self.DEFAULT_API_VERSION)
    
    # Models that must use the Responses API (/v1/responses) instead of Chat Completions
    RESPONSES_API_MODELS = {
        "gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.4-pro", "gpt-5.4",
        "gpt-5.3-chat", "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2",
        "gpt-5.2-chat", "gpt-5.1-codex-max", "gpt-5.1", "gpt-5.1-chat",
        "gpt-5.1-codex", "gpt-5.1-codex-mini", "gpt-5-pro", "gpt-5-codex",
        "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-chat", "gpt-4o",
        "gpt-4o-mini", "computer-use-preview", "gpt-4.1", "gpt-4.1-nano",
        "gpt-4.1-mini", "gpt-image-1", "gpt-image-1-mini", "gpt-image-1.5",
        "o1", "o3-mini", "o3", "o4-mini"
    }

    def _uses_responses_api(self, model: str) -> bool:
        """Check if the given model requires the Responses API."""
        return model in self.RESPONSES_API_MODELS

    def get_chat_url(self, deployment_name: str) -> str:
        """
        获取聊天 API URL
        
        Args:
            deployment_name: Azure 部署名称
        
        Returns:
            完整的 API URL
        """
        base_url = self.config.base_url.rstrip('/')
        
        if self._uses_responses_api(deployment_name):
            return f"{base_url}/v1/responses?api-version={self.api_version}"

        return f"{base_url}/openai/deployments/{deployment_name}/chat/completions?api-version={self.api_version}"

    def _prepare_responses_api_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        Convert a ChatRequest to the OpenAI Responses API request body format.

        Responses API differences from Chat Completions:
        - Uses `input` instead of `messages`
        - Uses `instructions` instead of system message
        - Uses `max_output_tokens` instead of `max_tokens`
        """
        messages = request.messages

        # Separate system messages (become `instructions`) from the rest
        system_parts = []
        non_system_messages = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                if isinstance(msg.content, str):
                    system_parts.append(msg.content)
                elif isinstance(msg.content, list):
                    system_parts.append(" ".join(b.text or "" for b in msg.content if hasattr(b, "text")))
            else:
                non_system_messages.append(msg)

        # Build `input` array
        input_items = []
        for msg in non_system_messages:
            item: Dict[str, Any] = {"role": msg.role.value}

            if isinstance(msg.content, str):
                item["content"] = [{"type": "input_text", "text": msg.content}]
            elif isinstance(msg.content, list):
                content_parts = []
                for block in msg.content:
                    if block.type == ContentType.TEXT:
                        content_parts.append({"type": "input_text", "text": block.text or ""})
                    elif block.type == ContentType.IMAGE_URL:
                        content_parts.append({
                            "type": "input_image",
                            "image_url": {"url": block.url}
                        })
                    elif block.type == ContentType.IMAGE_BASE64:
                        content_parts.append({
                            "type": "input_image",
                            "source": {
                                "type": "base64",
                                "media_type": block.media_type or "image/jpeg",
                                "data": block.data
                            }
                        })
                    elif block.type == ContentType.TOOL_CALL:
                        # Tool calls go as top-level function_call items, handled separately
                        pass
                if content_parts:
                    item["content"] = content_parts
            else:
                item["content"] = []

            # Handle tool call results (tool role)
            if msg.tool_call_id:
                item["call_id"] = msg.tool_call_id

            input_items.append(item)

        result: Dict[str, Any] = {
            "model": request.model,
            "input": input_items,
        }

        if system_parts:
            result["instructions"] = "\n".join(system_parts)

        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.max_tokens is not None:
            result["max_output_tokens"] = request.max_tokens
        if request.tools:
            result["tools"] = [self._tool_to_openai(t) for t in request.tools]
        if request.tool_choice:
            result["tool_choice"] = request.tool_choice
        if request.stop:
            result["stop"] = request.stop
        if request.presence_penalty is not None:
            result["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            result["frequency_penalty"] = request.frequency_penalty
        if request.user:
            result["user"] = request.user

        return result

    def _parse_responses_api_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        Parse an OpenAI Responses API response body into a ChatResponse.
        """
        text_parts = []
        tool_calls = []

        for item in response_data.get("output", []):
            item_type = item.get("type")
            if item_type == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
            elif item_type == "function_call":
                from app.abstraction.tools import ToolCall as TC
                args_str = item.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=item.get("call_id") or item.get("id", ""),
                    name=item.get("name", ""),
                    arguments=args,
                    call_type="function"
                ))

        full_text = "".join(text_parts)
        message = Message(role=MessageRole.ASSISTANT, content=full_text)

        finish_reason = FinishReason.STOP
        status = response_data.get("status", "completed")
        if status == "incomplete":
            finish_reason = FinishReason.LENGTH
        elif tool_calls:
            finish_reason = FinishReason.TOOL_CALLS

        choice = ChatChoice(
            index=0,
            message=message,
            finish_reason=finish_reason,
            tool_calls=tool_calls
        )

        usage_data = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0)
        )

        resp_id = response_data.get("id", f"resp_{uuid.uuid4().hex[:8]}")
        # Normalise to chatcmpl- prefix for internal consistency
        if resp_id.startswith("resp_"):
            resp_id = resp_id.replace("resp_", "chatcmpl-", 1)

        return ChatResponse(
            id=resp_id,
            model=model,
            choices=[choice],
            usage=usage,
            created=response_data.get("created_at", int(time.time())),
            provider=self.PROVIDER_TYPE
        )

    def _parse_responses_api_stream(
        self, response, response_id: str, model: str
    ) -> Generator[StreamChunk, None, None]:
        """
        Parse Server-Sent Events from the Responses API streaming endpoint
        into StreamChunk objects.
        """
        for line in response.iter_lines():
            if not line:
                continue

            if line.startswith("event:"):
                # SSE event name line — skip, we read the data on the next line
                continue

            if line.startswith("data:"):
                data_str = line[5:].strip()

                if data_str == "[DONE]":
                    break

                try:
                    event_data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event_data.get("type", "")

                if event_type == "response.output_text.delta":
                    delta = event_data.get("delta", "")
                    yield StreamChunk(
                        id=response_id,
                        model=model,
                        delta_content=delta,
                        created=int(time.time())
                    )

                elif event_type == "response.function_call_arguments.delta":
                    delta = event_data.get("delta", "")
                    index = event_data.get("output_index", 0)
                    yield StreamChunk(
                        id=response_id,
                        model=model,
                        tool_calls=[{
                            "index": index,
                            "function": {"arguments": delta}
                        }],
                        created=int(time.time())
                    )

                elif event_type == "response.completed":
                    resp = event_data.get("response", {})
                    usage_data = resp.get("usage", {})
                    usage = {
                        "prompt_tokens": usage_data.get("input_tokens", 0),
                        "completion_tokens": usage_data.get("output_tokens", 0),
                        "total_tokens": usage_data.get("total_tokens", 0),
                    } if usage_data else None
                    yield StreamChunk(
                        id=response_id,
                        model=model,
                        finish_reason=FinishReason.STOP,
                        usage=usage,
                        created=int(time.time())
                    )
                    break

                elif event_type == "error":
                    error_info = event_data.get("error", {})
                    raise RuntimeError(
                        f"Azure Responses API error: {json.dumps(error_info, ensure_ascii=False)}"
                    )
    
    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型（部署名称）"""
        return True  # Azure 支持用户自定义部署名称
    
    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """获取模型信息"""
        # Azure 部署名称由用户自定义，所以总是返回基本信息
        return {
            "description": f"Azure deployment: {model}",
            "context_size": 8192,
            "supports_vision": True,  # 假设支持
        }
    
    def chat(self, request: ChatRequest) -> ChatResponse:
        """执行对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        deployment_name = request.model
        url = self.get_chat_url(deployment_name)

        if self._uses_responses_api(deployment_name):
            # Build Responses API request body
            request_data = self._prepare_responses_api_request(request)
        else:
            request_data = self.prepare_request(request)
            request_data["stream"] = False

        # Debug: print request details
        print(f"[Azure Debug] URL: {url}")
        print(f"[Azure Debug] Headers: {self.get_headers()}")
        print(f"[Azure Debug] Request Data: {json.dumps(request_data, ensure_ascii=False, indent=2)}")

        try:
            response = self.client.post(url, json=request_data)
            print(f"[Azure Debug] Response Status: {response.status_code}")

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    print(f"[Azure Debug] Error Response: {json.dumps(error_data, ensure_ascii=False, indent=2)}")
                    raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    raise RuntimeError(f"Azure API error ({response.status_code}): {response.text}")

            response.raise_for_status()
            response_data = response.json()

            if self._uses_responses_api(deployment_name):
                return self._parse_responses_api_response(response_data, request.model)
            return self.parse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            print(f"[Azure Debug] Error: {str(e)}")
            raise RuntimeError(f"Azure OpenAI API error: {str(e)}")

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        deployment_name = request.model
        url = self.get_chat_url(deployment_name)
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        if self._uses_responses_api(deployment_name):
            request_data = self._prepare_responses_api_request(request)
            request_data["stream"] = True

            try:
                with self.client.stream("POST", url, json=request_data) as response:
                    if response.status_code >= 400:
                        error_text = ""
                        for chunk in response.iter_bytes():
                            if chunk:
                                error_text += chunk.decode('utf-8')
                        print(f"[Azure Debug] Stream Error Response: {error_text}")
                        try:
                            error_data = json.loads(error_text)
                            raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                        except json.JSONDecodeError:
                            raise RuntimeError(f"Azure API error ({response.status_code}): {error_text}")

                    yield from self._parse_responses_api_stream(response, response_id, request.model)

            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"Azure Responses API streaming error: {str(e)}")
        else:
            request_data = self.prepare_request(request)
            request_data["stream"] = True

            try:
                with self.client.stream("POST", url, json=request_data) as response:
                    if response.status_code >= 400:
                        error_text = ""
                        for chunk in response.iter_bytes():
                            if chunk:
                                error_text += chunk.decode('utf-8')
                        print(f"[Azure Debug] Stream Error Response: {error_text}")
                        try:
                            error_data = json.loads(error_text)
                            raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                        except json.JSONDecodeError:
                            raise RuntimeError(f"Azure API error ({response.status_code}): {error_text}")

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
                raise RuntimeError(f"Azure OpenAI streaming API error: {str(e)}")
    
    def list_models(self) -> List[Dict[str, Any]]:
        """列出支持的模型（Azure 需要用户自己配置部署）"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "azure",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
            })
        return models


# 导出解析函数（与 OpenAI 格式相同）
__all__ = ['AzureProvider', 'parse_openai_request']