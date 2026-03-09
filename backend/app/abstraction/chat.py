"""
Chat completion abstraction layer - provides unified chat completion
request and response formats.
"""
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime
import time

from .messages import Message
from .tools import Tool, ToolChoice


class FinishReason(str, Enum):
    """Finish reason enum"""
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


class Usage(BaseModel):
    """Token usage information"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    # Cached tokens (for providers that support it)
    cached_prompt_tokens: int = 0
    cached_completion_tokens: int = 0
    
    # Audio/video tokens (for multimodal)
    audio_tokens: int = 0
    image_tokens: int = 0


class ChatChoice(BaseModel):
    """A single chat completion choice"""
    index: int = 0
    message: Message
    finish_reason: Optional[FinishReason] = None
    
    # For streaming
    delta: Optional[Message] = None
    
    model_config = {
        "use_enum_values": True
    }


class ChatCompletionRequest(BaseModel):
    """
    Unified chat completion request format.
    Compatible with OpenAI's chat completion API.
    """
    model: str = Field(..., description="Model ID to use")
    messages: List[Message] = Field(..., description="List of messages in the conversation")
    
    # Generation parameters
    temperature: Optional[float] = Field(1.0, ge=0, le=2, description="Sampling temperature")
    top_p: Optional[float] = Field(1.0, ge=0, le=1, description="Nucleus sampling probability")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens to generate")
    max_completion_tokens: Optional[int] = Field(None, description="Maximum completion tokens")
    
    # Stop sequences
    stop: Optional[Union[str, List[str]]] = Field(None, description="Stop sequences")
    
    # Frequency and presence penalties
    frequency_penalty: Optional[float] = Field(0, ge=-2, le=2)
    presence_penalty: Optional[float] = Field(0, ge=-2, le=2)
    
    # Repetition penalty (for some providers)
    repetition_penalty: Optional[float] = Field(None, ge=0)
    
    # Logit bias
    logit_bias: Optional[Dict[str, float]] = Field(None)
    logprobs: Optional[bool] = Field(None)
    top_logprobs: Optional[int] = Field(None)
    
    # Tools
    tools: Optional[List[Tool]] = Field(None, description="List of tools available")
    tool_choice: Optional[Union[ToolChoice, str]] = Field(None, description="Tool choice mode")
    parallel_tool_calls: Optional[bool] = Field(None)
    
    # Response format
    response_format: Optional[Dict[str, Any]] = Field(None)
    
    # Streaming
    stream: Optional[bool] = Field(False, description="Whether to stream the response")
    stream_options: Optional[Dict[str, Any]] = Field(None)
    
    # User identification
    user: Optional[str] = Field(None)
    
    # Seed for deterministic outputs
    seed: Optional[int] = Field(None)
    
    # Provider-specific options
    provider_options: Optional[Dict[str, Any]] = Field(None, description="Provider-specific options")
    
    # Internal routing options
    routing_options: Optional[Dict[str, Any]] = Field(None, description="Internal routing options")
    
    model_config = {
        "use_enum_values": True
    }
    
    def get_context_size_estimate(self) -> int:
        """Estimate the context size needed for this request"""
        total = 0
        for msg in self.messages:
            text = msg.get_text_content()
            total += len(text.split()) * 1.3  # Rough estimate: 1.3 tokens per word
        return int(total)


class ChatCompletionResponse(BaseModel):
    """
    Unified chat completion response format.
    Compatible with OpenAI's chat completion API.
    """
    id: str = Field(default_factory=lambda: f"chatcmpl-{int(time.time() * 1000)}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    
    choices: List[ChatChoice]
    usage: Usage
    
    # System fingerprint for caching
    system_fingerprint: Optional[str] = None
    
    # Provider information
    provider: Optional[str] = None
    provider_model: Optional[str] = None
    
    # Timing information
    latency_ms: Optional[float] = None
    
    model_config = {
        "use_enum_values": True
    }


class ModelInfo(BaseModel):
    """Model information"""
    id: str
    name: str
    provider: str
    context_size: int
    max_output_tokens: Optional[int] = None
    
    # Pricing (per million tokens)
    input_price: float = 0
    output_price: float = 0
    cache_creation_price: float = 0
    cache_hit_price: float = 0
    
    # Capabilities
    supports_vision: bool = False
    supports_audio: bool = False
    supports_video: bool = False
    supports_tools: bool = False
    supports_streaming: bool = True
    
    # Status
    status: str = "active"