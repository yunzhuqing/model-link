"""
OpenAI provider implementation.
Implements the official OpenAI API format.
"""
import json
from typing import Optional, List, Dict, Any, AsyncIterator
import httpx
import time

from .base import BaseProvider, ProviderConfig
from ..abstraction.messages import Message, MessageRole, ContentPart, ContentType
from ..abstraction.tools import Tool, ToolCall, ToolType, FunctionCall
from ..abstraction.chat import (
    ChatCompletionRequest, ChatCompletionResponse, ChatChoice, Usage, ModelInfo, FinishReason
)
from ..abstraction.streaming import StreamChunk, StreamManager


class OpenAIProvider(BaseProvider):
    """
    OpenAI API provider implementation.
    Supports GPT-4, GPT-3.5, and other OpenAI models.
    """
    
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    
    # Known OpenAI models and their capabilities
    MODELS = {
        "gpt-4o": ModelInfo(
            id="gpt-4o",
            name="GPT-4o",
            provider="openai",
            context_size=128000,
            max_output_tokens=16384,
            input_price=2.5,
            output_price=10.0,
            cache_creation_price=1.25,
            cache_hit_price=0.3125,
            supports_vision=True,
            supports_audio=True,
            supports_video=True,
            supports_tools=True,
            supports_streaming=True
        ),
        "gpt-4o-mini": ModelInfo(
            id="gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openai",
            context_size=128000,
            max_output_tokens=16384,
            input_price=0.15,
            output_price=0.60,
            cache_creation_price=0.075,
            cache_hit_price=0.01875,
            supports_vision=True,
            supports_audio=True,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "gpt-4-turbo": ModelInfo(
            id="gpt-4-turbo",
            name="GPT-4 Turbo",
            provider="openai",
            context_size=128000,
            max_output_tokens=4096,
            input_price=10.0,
            output_price=30.0,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "gpt-4": ModelInfo(
            id="gpt-4",
            name="GPT-4",
            provider="openai",
            context_size=8192,
            input_price=30.0,
            output_price=60.0,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "gpt-3.5-turbo": ModelInfo(
            id="gpt-3.5-turbo",
            name="GPT-3.5 Turbo",
            provider="openai",
            context_size=16385,
            max_output_tokens=4096,
            input_price=0.50,
            output_price=1.50,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "o1-preview": ModelInfo(
            id="o1-preview",
            name="O1 Preview",
            provider="openai",
            context_size=128000,
            max_output_tokens=32768,
            input_price=15.0,
            output_price=60.0,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=False,
            supports_streaming=False
        ),
        "o1-mini": ModelInfo(
            id="o1-mini",
            name="O1 Mini",
            provider="openai",
            context_size=128000,
            max_output_tokens=65536,
            input_price=3.0,
            output_price=12.0,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=False,
            supports_streaming=False
        ),
    }
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.base_url = config.base_url or self.DEFAULT_BASE_URL
    
    @property
    def name(self) -> str:
        return "openai"
    
    @property
    def supported_features(self) -> List[str]:
        return [
            "chat_completions",
            "streaming",
            "tools",
            "vision",
            "audio_input",
            "video_input",
            "logprobs",
            "function_calling",
            "json_mode",
            "seed",
            "caching"
        ]
    
    def _get_default_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        if self.config.organization:
            headers["OpenAI-Organization"] = self.config.organization
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers
    
    def convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert unified messages to OpenAI format"""
        openai_messages = []
        
        for msg in messages:
            openai_msg = {"role": msg.role}
            
            if isinstance(msg.content, str):
                openai_msg["content"] = msg.content
            elif isinstance(msg.content, list):
                # Multimodal content
                content_parts = []
                for part in msg.content:
                    if part.type == ContentType.TEXT:
                        content_parts.append({"type": "text", "text": part.text})
                    elif part.type == ContentType.IMAGE_URL:
                        image_data = {"type": "image_url", "image_url": {"url": part.url}}
                        if part.detail:
                            image_data["image_url"]["detail"] = part.detail
                        content_parts.append(image_data)
                    elif part.type == ContentType.IMAGE_BASE64:
                        image_url = f"data:{part.mime_type or 'image/jpeg'};base64,{part.media}"
                        content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
                    elif part.type == ContentType.AUDIO_URL:
                        # OpenAI uses input_audio format
                        content_parts.append({
                            "type": "input_audio",
                            "input_audio": {"url": part.url}
                        })
                    elif part.type == ContentType.AUDIO_BASE64:
                        content_parts.append({
                            "type": "input_audio",
                            "input_audio": {
                                "data": part.media,
                                "format": part.mime_type or "mp3"
                            }
                        })
                openai_msg["content"] = content_parts
            
            if msg.name:
                openai_msg["name"] = msg.name
            
            if msg.tool_calls:
                openai_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in msg.tool_calls
                ]
            
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            
            openai_messages.append(openai_msg)
        
        return openai_messages
    
    def convert_tools(self, tools: List[Tool]) -> List[Dict[str, Any]]:
        """Convert unified tools to OpenAI format"""
        openai_tools = []
        
        for tool in tools:
            if tool.type == ToolType.FUNCTION:
                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": tool.function.name,
                        "description": tool.function.description or "",
                        "parameters": tool.function.parameters or {}
                    }
                }
                openai_tools.append(openai_tool)
            elif tool.type == ToolType.WEB_SEARCH:
                # OpenAI's web search is a built-in tool
                openai_tools.append({"type": "web_search"})
        
        return openai_tools
    
    def convert_request(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Convert unified request to OpenAI format"""
        body: Dict[str, Any] = {
            "model": request.model,
            "messages": self.convert_messages(request.messages)
        }
        
        # Optional parameters
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.max_completion_tokens is not None:
            body["max_completion_tokens"] = request.max_completion_tokens
        if request.stop:
            body["stop"] = request.stop
        if request.frequency_penalty is not None:
            body["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty is not None:
            body["presence_penalty"] = request.presence_penalty
        if request.logit_bias:
            body["logit_bias"] = request.logit_bias
        if request.logprobs:
            body["logprobs"] = request.logprobs
        if request.top_logprobs:
            body["top_logprobs"] = request.top_logprobs
        if request.user:
            body["user"] = request.user
        if request.seed is not None:
            body["seed"] = request.seed
        
        # Tools
        if request.tools:
            body["tools"] = self.convert_tools(request.tools)
            if request.tool_choice:
                body["tool_choice"] = request.tool_choice
            if request.parallel_tool_calls is not None:
                body["parallel_tool_calls"] = request.parallel_tool_calls
        
        # Response format
        if request.response_format:
            body["response_format"] = request.response_format
        
        # Streaming
        if request.stream:
            body["stream"] = True
            if request.stream_options:
                body["stream_options"] = request.stream_options
        
        return body
    
    def convert_response(self, response: Dict[str, Any]) -> ChatCompletionResponse:
        """Convert OpenAI response to unified format"""
        choices = []
        
        for choice in response.get("choices", []):
            message_data = choice.get("message", {})
            
            tool_calls = None
            if "tool_calls" in message_data:
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        type=tc.get("type", "function"),
                        function=FunctionCall(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"]
                        )
                    )
                    for tc in message_data["tool_calls"]
                ]
            
            message = Message(
                role=message_data.get("role", "assistant"),
                content=message_data.get("content"),
                tool_calls=tool_calls
            )
            
            finish_reason = None
            if choice.get("finish_reason"):
                try:
                    finish_reason = FinishReason(choice["finish_reason"])
                except ValueError:
                    finish_reason = FinishReason.STOP
            
            choices.append(ChatChoice(
                index=choice.get("index", 0),
                message=message,
                finish_reason=finish_reason
            ))
        
        usage = Usage()
        if "usage" in response:
            usage = Usage(
                prompt_tokens=response["usage"].get("prompt_tokens", 0),
                completion_tokens=response["usage"].get("completion_tokens", 0),
                total_tokens=response["usage"].get("total_tokens", 0),
                cached_prompt_tokens=response["usage"].get("prompt_tokens_details", {}).get("cached_tokens", 0)
            )
        
        return ChatCompletionResponse(
            id=response.get("id", ""),
            created=response.get("created", int(time.time())),
            model=response.get("model", ""),
            choices=choices,
            usage=usage,
            system_fingerprint=response.get("system_fingerprint"),
            provider="openai"
        )
    
    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Execute a chat completion request"""
        body = self.convert_request(request)
        
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json=body
        )
        
        response.raise_for_status()
        data = response.json()
        
        return self.convert_response(data)
    
    async def stream_chat_completion(
        self, 
        request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """Execute a streaming chat completion request"""
        body = self.convert_request(request)
        body["stream"] = True
        
        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=body
        ) as response:
            response.raise_for_status()
            
            chunk_id = f"chatcmpl-{int(time.time() * 1000)}"
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    
                    try:
                        chunk_data = json.loads(data)
                        
                        choices = []
                        for choice in chunk_data.get("choices", []):
                            delta = choice.get("delta", {})
                            
                            tool_calls = None
                            if "tool_calls" in delta:
                                tool_calls = [
                                    ToolCall(
                                        id=tc.get("id", ""),
                                        type=tc.get("type", "function"),
                                        function=FunctionCall(
                                            name=tc.get("function", {}).get("name", ""),
                                            arguments=tc.get("function", {}).get("arguments", "")
                                        )
                                    )
                                    for tc in delta["tool_calls"]
                                ]
                            
                            message = Message(
                                role=delta.get("role"),
                                content=delta.get("content"),
                                tool_calls=tool_calls
                            )
                            
                            finish_reason = None
                            if choice.get("finish_reason"):
                                try:
                                    finish_reason = FinishReason(choice["finish_reason"])
                                except ValueError:
                                    finish_reason = None
                            
                            choices.append(StreamChoice(
                                index=choice.get("index", 0),
                                delta=message,
                                finish_reason=finish_reason
                            ))
                        
                        usage = None
                        if "usage" in chunk_data:
                            usage = Usage(
                                prompt_tokens=chunk_data["usage"].get("prompt_tokens", 0),
                                completion_tokens=chunk_data["usage"].get("completion_tokens", 0),
                                total_tokens=chunk_data["usage"].get("total_tokens", 0)
                            )
                        
                        yield StreamChunk(
                            id=chunk_data.get("id", chunk_id),
                            created=chunk_data.get("created", int(time.time())),
                            model=chunk_data.get("model", request.model),
                            choices=choices,
                            usage=usage
                        )
                    except json.JSONDecodeError:
                        continue
    
    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """Get information about a specific model"""
        # Check exact match first
        if model_name in self.MODELS:
            return self.MODELS[model_name]
        
        # Check for model family match (e.g., gpt-4-1106-preview)
        for model_id, info in self.MODELS.items():
            if model_name.startswith(model_id) or model_id in model_name:
                return info
        
        # Return generic info for unknown models
        return ModelInfo(
            id=model_name,
            name=model_name,
            provider="openai",
            context_size=8192,
            supports_vision=False,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        )
    
    async def list_models(self) -> List[ModelInfo]:
        """List available models from OpenAI API"""
        try:
            response = await self.client.get(f"{self.base_url}/models")
            response.raise_for_status()
            data = response.json()
            
            models = []
            for model_data in data.get("data", []):
                model_id = model_data.get("id", "")
                info = self.get_model_info(model_id)
                if info:
                    models.append(info)
            
            return models
        except Exception:
            # Fall back to known models
            return list(self.MODELS.values())