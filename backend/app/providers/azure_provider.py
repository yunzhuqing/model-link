"""
Azure OpenAI 供应商实现 (Azure OpenAI Provider)
实现 Azure OpenAI API 的调用。
"""
from typing import Optional, List, Dict, Any, AsyncGenerator
import json
import time
import uuid

from .base import BaseProvider, ProviderConfig, ProviderCapability
from .openai_provider import OpenAIProvider, parse_openai_request
from ._responses_format import build_responses_request, parse_responses_response, tool_to_responses_api
from app.utils import json_loads
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
    DEFAULT_API_VERSION = "2025-04-01-preview"
    
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
        "gpt-5.5", "gpt-5.5-pro",
        "gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.4-pro", "gpt-5.4",
        "gpt-5.3-chat", "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2",
        "gpt-5.2-chat", "gpt-5.1-codex-max", "gpt-5.1", "gpt-5.1-chat",
        "gpt-5.1-codex", "gpt-5.1-codex-mini", "gpt-5-pro", "gpt-5-codex",
        "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-chat", "computer-use-preview", "gpt-image-1", "gpt-image-1-mini", "gpt-image-1.5",
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
            return f"{base_url}/openai/responses?api-version={self.api_version}"

        return f"{base_url}/openai/deployments/{deployment_name}/chat/completions?api-version={self.api_version}"

    async def _download_file_to_base64(self, url: str) -> tuple:
        """Download a file from URL and return (base64_data, media_type, filename)."""
        import base64
        import os

        client = await self._http()
        response = await client.get(url)
        response.raise_for_status()

        content_type = response.headers.get('content-type', 'application/octet-stream')
        filename = os.path.basename(url.split('?')[0]) or 'file'
        b64_data = base64.b64encode(response.content).decode('utf-8')
        return b64_data, content_type, filename

    @staticmethod
    def _normalize_tool_choice_for_responses(tool_choice):
        """Convert tool_choice to Responses API format.

        Chat Completions uses:
          - strings: "auto", "none", "required", or a function name
          - dict:   {"type": "function", "function": {"name": "..."}}

        Responses API uses:
          - strings: "auto", "none", "required"
          - dict:    {"type": "function", "name": "..."}
        """
        if isinstance(tool_choice, str):
            if tool_choice in ("auto", "none", "required"):
                return tool_choice
            # specific function name
            return {"type": "function", "name": tool_choice}
        if isinstance(tool_choice, dict):
            tc_type = tool_choice.get("type", "")
            if tc_type == "function":
                name = ""
                if "function" in tool_choice and isinstance(tool_choice["function"], dict):
                    name = tool_choice["function"].get("name", "")
                elif "name" in tool_choice:
                    name = tool_choice["name"]
                return {"type": "function", "name": name}
            return tool_choice
        return tool_choice

    async def _prepare_responses_api_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        Convert a ChatRequest to the OpenAI Responses API request body format.
    
        委托给共享的 Responses API 请求构建器，前置 Azure 特有的文件下载预处理。
        """
        # 预处理：下载 FILE_URL 内容块为 base64（Azure 不支持 file_url）
        for msg in request.messages:
            content = getattr(msg, 'content', None)
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, 'type') and block.type == ContentType.FILE_URL:
                        b64_data, content_type, filename = await self._download_file_to_base64(block.url)
                        block.type = ContentType.FILE_BASE64
                        block.data = b64_data
                        block.media_type = content_type
                        block.filename = filename
    
        # 委托给共享实现构建基础请求体
        result = build_responses_request(request)
    
        # Azure 特有：覆盖 tools 为 Responses API flat 格式
        if request.tools:
            result["tools"] = [tool_to_responses_api(t) for t in request.tools]
        if request.tool_choice:
            result["tool_choice"] = self._normalize_tool_choice_for_responses(request.tool_choice)
    
        return result

    def _parse_responses_api_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """委托给共享的 Responses API 响应解析器。"""
        return parse_responses_response(response_data, model)

    async def _parse_responses_api_stream(
        self, response, response_id: str, model: str
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Parse Server-Sent Events from the Responses API streaming endpoint
        into StreamChunk objects.

        The real response ID is taken from Azure's `response.completed` event,
        which carries the full response object including the authoritative `id`.
        Delta chunks do not need a meaningful ID because the Responses API adapter
        does not include the ID in delta SSE events.
        """
        # Accumulate the real ID from response.completed; use fallback until then
        current_id = response_id
        # Full text captured from response.output_text.done (sent with the finish chunk)
        full_text: str = ""

        async for line in response.aiter_lines():
            if not line:
                continue

            if line.startswith("event:"):
                # SSE event name line — skip, data follows on the next line
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

                if event_type == "response.created":
                    # Capture Azure's real response ID from the first SSE event and yield a
                    # marker chunk so the adapter can use it for the response.created event
                    # it sends to the client.
                    resp = event_data.get("response", {})
                    real_id = resp.get("id")
                    if real_id:
                        current_id = real_id
                    # Yield a role-only chunk (no content) to propagate the real ID upstream.
                    # The Responses API adapter ignores role-only chunks in format_stream_chunk.
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        delta_role="assistant",
                        created=int(time.time())
                    )

                elif event_type == "response.in_progress":
                    # Azure sends this immediately after response.created; it also carries
                    # the real response ID. Capture it as a belt-and-suspenders measure.
                    # We do NOT yield a chunk — the adapter already emitted response.created.
                    resp = event_data.get("response", {})
                    real_id = resp.get("id")
                    if real_id:
                        current_id = real_id

                elif event_type == "response.output_item.added":
                    item = event_data.get("item", {})
                    item_type = item.get("type", "")
                    msg_id = item.get("id", "")

                    if item_type == "message" and msg_id.startswith("msg_"):
                        # Capture Azure's real message item ID so the adapter can use it in
                        # the response.output_item.added event it sends to the client.
                        # We encode the message ID in delta_role using the convention "msg_xxx".
                        yield StreamChunk(
                            id=current_id,
                            model=model,
                            delta_role=msg_id,  # encodes the real message ID
                            created=int(time.time())
                        )

                    elif item_type == "function_call":
                        # Function call start — emit tool_calls with id + name.
                        # This triggers content_block_start (tool_use) in the Anthropic adapter.
                        call_id = item.get("call_id", "")
                        name = item.get("name", "")
                        fc_output_index = event_data.get("output_index", 0)
                        if call_id:
                            tc: Dict[str, Any] = {
                                "index": fc_output_index,
                                "id": call_id,
                                "function": {
                                    "name": name,
                                    "arguments": ""
                                }
                            }
                            yield StreamChunk(
                                id=current_id,
                                model=model,
                                tool_calls=[tc],
                                created=int(time.time())
                            )

                elif event_type == "response.output_text.done":
                    # Capture the full assembled text; pass it with the finish chunk so
                    # the adapter can emit response.output_text.done / content_part.done /
                    # output_item.done events to the client.
                    full_text = event_data.get("text", "")

                elif event_type in (
                    "response.reasoning_summary_part.added",
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_summary_text.done",
                    "response.reasoning_summary_part.done",
                ):
                    # Forward reasoning summary events verbatim to the Responses API adapter.
                    # These events are Azure-specific and have no equivalent in the generic
                    # StreamChunk model, so we encode them as raw SSE passthrough strings.
                    raw_sse = (
                        f"event: {event_type}\n"
                        f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                    )
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        raw_sse_passthrough=[raw_sse],
                        created=int(time.time())
                    )

                elif event_type == "response.output_text.delta":
                    delta = event_data.get("delta", "")
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        delta_content=delta,
                        created=int(time.time())
                    )

                elif event_type == "response.function_call_arguments.delta":
                    delta = event_data.get("delta", "")
                    index = event_data.get("output_index", 0)
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        tool_calls=[{
                            "index": index,
                            "function": {"arguments": delta}
                        }],
                        created=int(time.time())
                    )

                elif event_type == "response.completed":
                    resp = event_data.get("response", {})
                    # Use the authoritative ID that Azure assigns in the completed event
                    real_id = resp.get("id")
                    if real_id:
                        current_id = real_id
                    usage_data = resp.get("usage", {})
                    if usage_data:
                        input_details = usage_data.get("input_tokens_details", {})
                        output_details = usage_data.get("output_tokens_details", {})
                        # Carry the full Azure response object in extra so the adapter can emit it
                        # verbatim in the response.completed SSE event.
                        usage: Optional['UsageInfo'] = UsageInfo(
                            prompt_tokens=usage_data.get("input_tokens", 0),
                            completion_tokens=usage_data.get("output_tokens", 0),
                            total_tokens=usage_data.get("total_tokens", 0),
                            cached_tokens=input_details.get("cached_tokens", 0),
                            reasoning_tokens=output_details.get("reasoning_tokens", 0),
                            extra={"_azure_completed_response": resp},
                        )
                    else:
                        usage = UsageInfo(extra={"_azure_completed_response": resp}) if resp else None

                    # Determine finish_reason: TOOL_CALLS if the response output
                    # contains any function_call items, otherwise STOP.
                    has_tool_calls = any(
                        item.get("type") == "function_call"
                        for item in resp.get("output", [])
                    )
                    finish = FinishReason.TOOL_CALLS if has_tool_calls else FinishReason.STOP

                    # Pass full_text in delta_content so the adapter can emit the three
                    # "done" events (output_text.done, content_part.done, output_item.done)
                    # before the response.completed event.
                    # Set _skip_content_on_finish_reason=True so that to_openai_format
                    # skips the duplicate full text in the final Chat Completions chunk
                    # (it was already sent incrementally via response.output_text.delta events).
                    yield StreamChunk(
                        id=current_id,
                        model=model,
                        delta_content=full_text if full_text else None,
                        finish_reason=finish,
                        usage=usage,
                        created=int(time.time()),
                        _skip_content_on_finish_reason=True,
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
    
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """执行对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        deployment_name = request.model
        url = self.get_chat_url(deployment_name)

        if self._uses_responses_api(deployment_name):
            # Build Responses API request body
            request_data = await self._prepare_responses_api_request(request)
            request_data["stream"] = False
        else:
            request_data = await self.aprepare_request(request)
            request_data["stream"] = False

        try:
            async with self._trace_call(request.model, input_data=request_data) as child_span:
                response = await (await self._http()).post(url, json=request_data, headers=self.get_headers())

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        raise RuntimeError(f"Azure API error ({response.status_code}): {response.text}")

                response.raise_for_status()
                response_data = response.json()
                if child_span:
                    child_span.log_output(response_data)

                if self._uses_responses_api(deployment_name):
                    return self._parse_responses_api_response(response_data, request.model)
                return await self.aparse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Azure OpenAI API error: {str(e)}")

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        deployment_name = request.model
        url = self.get_chat_url(deployment_name)
        # For Chat Completions models, generate a local ID (Azure doesn't return one upfront).
        # For Responses API models, Azure provides the real ID in the response.completed event;
        # we start with an empty string and fill it in from the SSE stream.
        if self._uses_responses_api(deployment_name):
            response_id = ""
        else:
            response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        if self._uses_responses_api(deployment_name):
            request_data = await self._prepare_responses_api_request(request)
            request_data["stream"] = True

            try:
                async with self._trace_call(request.model, input_data=request_data) as child_span:
                    async with (await self._http()).stream("POST", url, json=request_data, headers=self.get_headers()) as response:
                        if response.status_code >= 400:
                            error_text = ""
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    error_text += chunk.decode('utf-8')
                            try:
                                error_data = json.loads(error_text)
                                raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                            except json.JSONDecodeError:
                                raise RuntimeError(f"Azure API error ({response.status_code}): {error_text}")

                        async for chunk in self._parse_responses_api_stream(response, response_id, request.model):
                            yield chunk

            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"Azure Responses API streaming error: {str(e)}")
        else:
            request_data = await self.aprepare_request(request)
            request_data["stream"] = True

            try:
                async with self._trace_call(request.model, input_data=request_data) as child_span:
                    async with (await self._http()).stream("POST", url, json=request_data, headers=self.get_headers()) as response:
                        if response.status_code >= 400:
                            error_text = ""
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    error_text += chunk.decode('utf-8')
                            try:
                                error_data = json.loads(error_text)
                                raise RuntimeError(f"Azure API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                            except json.JSONDecodeError:
                                raise RuntimeError(f"Azure API error ({response.status_code}): {error_text}")

                        async for line in response.aiter_lines():
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


    def get_embedding_url(self, deployment_name: str) -> str:
        """
        获取嵌入 API URL
        
        Azure embedding URL format:
        {base_url}/openai/deployments/{deployment_name}/embeddings?api-version={api_version}
        
        Args:
            deployment_name: Azure 部署名称 (e.g., text-embedding-3-large)
        
        Returns:
            完整的嵌入 API URL
        """
        base_url = self.config.base_url.rstrip('/')
        return f"{base_url}/openai/deployments/{deployment_name}/embeddings?api-version={self.api_version}"

    async def embed(self, request: 'EmbeddingRequest') -> 'EmbeddingResponse':
        """
        执行嵌入请求（Azure 版本）

        使用 Azure 特定的 URL 格式：
        {base_url}/openai/deployments/{model}/embeddings?api-version={api_version}

        Args:
            request: 嵌入请求对象

        Returns:
            嵌入响应对象
        """
        from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse

        # 准备请求数据 - Azure 不需要 model 字段（在 URL 中指定）
        request_data = {
            "encoding_format": request.encoding_format,
        }

        # Multimodal embedding uses "messages" instead of "input"
        if request.is_multimodal:
            request_data["messages"] = request.messages
        else:
            request_data["input"] = request.input

        if request.dimensions is not None:
            request_data["dimensions"] = request.dimensions

        if request.user:
            request_data["user"] = request.user

        url = self.get_embedding_url(request.model)

        try:
            response = await (await self._http()).post(url, json=request_data, headers=self.get_headers())

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(f"Azure embedding API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    raise RuntimeError(f"Azure embedding API error ({response.status_code}): {response.text}")

            response_data = response.json()
            return self._parse_embedding_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            model = request.model if request else "unknown"
            context = f"model={model} url={url}"
            resp_info = ""
            try:
                if 'response' in locals():
                    resp_info = f" status={response.status_code} body={response.text[:500]}"
            except Exception:
                pass
            raise RuntimeError(f"Azure embedding API error: {str(e)} [{context}{resp_info}]")


# 导出解析函数（与 OpenAI 格式相同）
__all__ = ['AzureProvider', 'parse_openai_request']
