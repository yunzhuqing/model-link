"""
Anthropic provider implementation.
Implements the Anthropic Claude API format.
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
from ..abstraction.streaming import StreamChunk, StreamChoice


class AnthropicProvider(BaseProvider):
    """
    Anthropic API provider implementation.
    Supports Claude models.
    """
    
    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    
    # Known Anthropic models
    MODELS = {
        "claude-sonnet-4-20250514": ModelInfo(
            id="claude-sonnet-4-20250514",
            name="Claude Sonnet 4",
            provider="anthropic",
            context_size=200000,
            max_output_tokens=16384,
            input_price=3.0,
            output_price=15.0,
            cache_creation_price=3.75,
            cache_hit_price=0.30,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "claude-3-5-sonnet-20241022": ModelInfo(
            id="claude-3-5-sonnet-20241022",
            name="Claude 3.5 Sonnet",
            provider="anthropic",
            context_size=200000,
            max_output_tokens=8192,
            input_price=3.0,
            output_price=15.0,
            cache_creation_price=3.75,
            cache_hit_price=0.30,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "claude-3-5-haiku-20241022": ModelInfo(
            id="claude-3-5-haiku-20241022",
            name="Claude 3.5 Haiku",
            provider="anthropic",
            context_size=200000,
            max_output_tokens=8192,
            input_price=0.80,
            output_price=4.0,
            cache_creation_price=1.0,
            cache_hit_price=0.08,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "claude-3-opus-20240229": ModelInfo(
            id="claude-3-opus-20240229",
            name="Claude 3 Opus",
            provider="anthropic",
            context_size=200000,
            max_output_tokens=4096,
            input_price=15.0,
            output_price=75.0,
            cache_creation_price=18.75,
            cache_hit_price=1.50,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "claude-3-sonnet-20240229": ModelInfo(
            id="claude-3-sonnet-20240229",
            name="Claude 3 Sonnet",
            provider="anthropic",
            context_size=200000,
            max_output_tokens=4096,
            input_price=3.0,
            output_price=15.0,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
        "claude-3-haiku-20240307": ModelInfo(
            id="claude-3-haiku-20240307",
            name="Claude 3 Haiku",
            provider="anthropic",
            context_size=200000,
            max_output_tokens=4096,
            input_price=0.25,
            output_price=1.25,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        ),
    }
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.base_url = config.base_url or self.DEFAULT_BASE_URL
    
    @property
    def name(self) -> str:
        return "anthropic"
    
    @property
    def supported_features(self) -> List[str]:
        return [
            "chat_completions",
            "streaming",
            "tools",
            "vision",
            "function_calling",
            "caching",
            "pdf_input"
        ]
    
    def _get_default_headers(self) -> Dict[str, str]:
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers
    
    def convert_messages(self, messages: List[Message]) -> tuple:
        """
        Convert unified messages to Anthropic format.
        Returns (system_prompt, messages) tuple.
        """
        anthropic_messages = []
        system_prompt = None
        
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                # Anthropic uses a separate system parameter
                if isinstance(msg.content, str):
                    system_prompt = msg.content
                continue
            
            anthropic_msg = {"role": msg.role}
            
            if isinstance(msg.content, str):
                anthropic_msg["content"] = msg.content
            elif isinstance(msg.content, list):
                # Multimodal content
                content_parts = []
                for part in msg.content:
                    if part.type == ContentType.TEXT:
                        content_parts.append({"type": "text", "text": part.text})
                    elif part.type == ContentType.IMAGE_URL:
                        # Anthropic requires base64 images
                        content_parts.append({
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": part.url
                            }
                        })
                    elif part.type == ContentType.IMAGE_BASE64:
                        content_parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": part.mime_type or "image/jpeg",
                                "data": part.media
                            }
                        })
                    elif part.type == ContentType.FILE_URL:
                        content_parts.append({
                            "type": "document",
                            "source": {
                                "type": "url",
                                "url": part.url
                            }
                        })
                    elif part.type == ContentType.FILE_BASE64:
                        content_parts.append({
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": part.mime_type or "application/pdf",
                                "data": part.media
                            }
                        })
                anthropic_msg["content"] = content_parts
            
            if msg.tool_calls:
                # Assistant message with tool calls
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": json.loads(tc.function.arguments) if tc.function.arguments else {}
                    })
                anthropic_msg["content"] = content
            
            if msg.tool_call_id:
                # Tool result message
                anthropic_msg = {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content
                    }]
                }
            
            anthropic_messages.append(anthropic_msg)
        
        return system_prompt, anthropic_messages
    
    def convert_tools(self, tools: List[Tool]) -> List[Dict[str, Any]]:
        """Convert unified tools to Anthropic format"""
        anthropic_tools = []
        
        for tool in tools:
            if tool.type == ToolType.FUNCTION:
                anthropic_tool = {
                    "name": tool.function.name,
                    "description": tool.function.description or "",
                    "input_schema": tool.function.parameters or {"type": "object", "properties": {}}
                }
                anthropic_tools.append(anthropic_tool)
        
        return anthropic_tools
    
    def convert_request(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Convert unified request to Anthropic format"""
        system_prompt, messages = self.convert_messages(request.messages)
        
        body: Dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096
        }
        
        if system_prompt:
            body["system"] = system_prompt
        
        # Optional parameters
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.stop:
            body["stop_sequences"] = request.stop if isinstance(request.stop, list) else [request.stop]
        
        # Tools
        if request.tools:
            body["tools"] = self.convert_tools(request.tools)
            if request.tool_choice:
                if request.tool_choice == "auto":
                    body["tool_choice"] = {"type": "auto"}
                elif request.tool_choice == "required":
                    body["tool_choice"] = {"type": "any"}
                elif isinstance(request.tool_choice, dict):
                    body["tool_choice"] = request.tool_choice
        
        # Response format
        if request.response_format:
            if request.response_format.get("type") == "json_object":
                body["system"] = (body.get("system", "") + "\n\nYou must respond with valid JSON.").strip()
        
        # Metadata
        if request.user:
            body["metadata"] = {"user_id": request.user}
        
        return body
    
    def convert_response(self, response: Dict[str, Any]) -> ChatCompletionResponse:
        """Convert Anthropic response to unified format"""
        choices = []
        
        content = response.get("content", [])
        text_content = ""
        tool_calls = []
        
        for block in content:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    type=ToolType.FUNCTION,
                    function=FunctionCall(
                        name=block.get("name", ""),
                        arguments=json.dumps(block.get("input", {}))
                    )
                ))
        
        message = Message(
            role="assistant",
            content=text_content if text_content else None,
            tool_calls=tool_calls if tool_calls else None
        )
        
        finish_reason = FinishReason.STOP
        if response.get("stop_reason"):
            if response["stop_reason"] == "end_turn":
                finish_reason = FinishReason.STOP
            elif response["stop_reason"] == "max_tokens":
                finish_reason = FinishReason.LENGTH
            elif response["stop_reason"] == "tool_use":
                finish_reason = FinishReason.TOOL_CALLS
        
        choices.append(ChatChoice(
            index=0,
            message=message,
            finish_reason=finish_reason
        ))
        
        usage = Usage()
        if "usage" in response:
            usage = Usage(
                prompt_tokens=response["usage"].get("input_tokens", 0),
                completion_tokens=response["usage"].get("output_tokens", 0),
                total_tokens=response["usage"].get("input_tokens", 0) + response["usage"].get("output_tokens", 0),
                cached_prompt_tokens=response["usage"].get("cache_read_input_tokens", 0),
                cache_creation_price=response["usage"].get("cache_creation_input_tokens", 0)
            )
        
        return ChatCompletionResponse(
            id=response.get("id", ""),
            created=int(time.time()),
            model=response.get("model", ""),
            choices=choices,
            usage=usage,
            provider="anthropic"
        )
    
    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Execute a chat completion request"""
        body = self.convert_request(request)
        
        response = await self.client.post(
            f"{self.base_url}/messages",
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
        
        chunk_id = f"chatcmpl-{int(time.time() * 1000)}"
        
        async with self.client.stream(
            "POST",
            f"{self.base_url}/messages",
            json=body
        ) as response:
            response.raise_for_status()
            
            current_content = ""
            tool_calls_buffer = {}
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    
                    try:
                        event = json.loads(data)
                        event_type = event.get("type")
                        
                        if event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                current_content += text
                                
                                yield StreamChunk(
                                    id=chunk_id,
                                    model=request.model,
                                    choices=[
                                        StreamChoice(
                                            delta=Message(
                                                role=MessageRole.ASSISTANT,
                                                content=text
                                            )
                                        )
                                    ]
                                )
                            elif delta.get("type") == "input_json_delta":
                                # Tool call arguments streaming
                                tool_index = event.get("index", 0)
                                if tool_index not in tool_calls_buffer:
                                    tool_calls_buffer[tool_index] = {"id": "", "name": "", "arguments": ""}
                                tool_calls_buffer[tool_index]["arguments"] += delta.get("partial_json", "")
                        
                        elif event_type == "content_block_start":
                            block = event.get("content_block", {})
                            if block.get("type") == "tool_use":
                                tool_index = event.get("index", 0)
                                tool_calls_buffer[tool_index] = {
                                    "id": block.get("id", ""),
                                    "name": block.get("name", ""),
                                    "arguments": ""
                                }
                        
                        elif event_type == "content_block_stop":
                            tool_index = event.get("index", 0)
                            if tool_index in tool_calls_buffer:
                                tc_data = tool_calls_buffer[tool_index]
                                yield StreamChunk(
                                    id=chunk_id,
                                    model=request.model,
                                    choices=[
                                        StreamChoice(
                                            delta=Message(
                                                role=MessageRole.ASSISTANT,
                                                tool_calls=[
                                                    ToolCall(
                                                        id=tc_data["id"],
                                                        type=ToolType.FUNCTION,
                                                        function=FunctionCall(
                                                            name=tc_data["name"],
                                                            arguments=tc_data["arguments"]
                                                        )
                                                    )
                                                ]
                                            )
                                        )
                                    ]
                                )
                        
                        elif event_type == "message_delta":
                            finish_reason = None
                            if event.get("delta", {}).get("stop_reason"):
                                sr = event["delta"]["stop_reason"]
                                if sr == "end_turn":
                                    finish_reason = FinishReason.STOP
                                elif sr == "max_tokens":
                                    finish_reason = FinishReason.LENGTH
                                elif sr == "tool_use":
                                    finish_reason = FinishReason.TOOL_CALLS
                            
                            usage = None
                            if "usage" in event:
                                usage = Usage(
                                    output_tokens=event["usage"].get("output_tokens", 0)
                                )
                            
                            if finish_reason or usage:
                                yield StreamChunk(
                                    id=chunk_id,
                                    model=request.model,
                                    choices=[
                                        StreamChoice(
                                            delta=Message(),
                                            finish_reason=finish_reason
                                        )
                                    ],
                                    usage=usage
                                )
                        
                        elif event_type == "message_start":
                            chunk_id = event.get("message", {}).get("id", chunk_id)
                    
                    except json.JSONDecodeError:
                        continue
    
    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """Get information about a specific model"""
        # Check exact match
        if model_name in self.MODELS:
            return self.MODELS[model_name]
        
        # Check for model family match
        for model_id, info in self.MODELS.items():
            if model_name.startswith(model_id.split("-20")[0]) or model_id.split("-20")[0] in model_name:
                return info
        
        # Return generic info for unknown models
        return ModelInfo(
            id=model_name,
            name=model_name,
            provider="anthropic",
            context_size=200000,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_tools=True,
            supports_streaming=True
        )
    
    async def list_models(self) -> List[ModelInfo]:
        """List available models"""
        # Anthropic doesn't have a models endpoint, return known models
        return list(self.MODELS.values())