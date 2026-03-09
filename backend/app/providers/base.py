"""
Base provider adapter interface.
All provider implementations must inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncIterator, Union
from pydantic import BaseModel
import httpx

from ..abstraction.messages import Message
from ..abstraction.tools import Tool
from ..abstraction.chat import (
    ChatCompletionRequest, ChatCompletionResponse, ChatChoice, Usage, ModelInfo, FinishReason
)
from ..abstraction.streaming import StreamChunk


class ProviderConfig(BaseModel):
    """Configuration for a provider"""
    api_key: str
    base_url: Optional[str] = None
    organization: Optional[str] = None
    timeout: int = 60
    max_retries: int = 3
    extra_headers: Optional[Dict[str, str]] = None


class BaseProvider(ABC):
    """
    Abstract base class for all provider implementations.
    Defines the interface that all providers must implement.
    """
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self.client = httpx.AsyncClient(
            timeout=config.timeout,
            headers=self._get_default_headers()
        )
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name"""
        pass
    
    @property
    @abstractmethod
    def supported_features(self) -> List[str]:
        """List of supported features"""
        pass
    
    @abstractmethod
    def _get_default_headers(self) -> Dict[str, str]:
        """Get default headers for API requests"""
        pass
    
    @abstractmethod
    async def chat_completion(
        self, 
        request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """
        Execute a chat completion request.
        
        Args:
            request: The unified chat completion request
            
        Returns:
            ChatCompletionResponse in unified format
        """
        pass
    
    @abstractmethod
    async def stream_chat_completion(
        self, 
        request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """
        Execute a streaming chat completion request.
        
        Args:
            request: The unified chat completion request
            
        Yields:
            StreamChunk objects
        """
        pass
    
    @abstractmethod
    def convert_request(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """
        Convert unified request to provider-specific format.
        
        Args:
            request: The unified chat completion request
            
        Returns:
            Provider-specific request body
        """
        pass
    
    @abstractmethod
    def convert_response(self, response: Dict[str, Any]) -> ChatCompletionResponse:
        """
        Convert provider-specific response to unified format.
        
        Args:
            response: Provider-specific response
            
        Returns:
            Unified ChatCompletionResponse
        """
        pass
    
    @abstractmethod
    def convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """
        Convert unified messages to provider-specific format.
        
        Args:
            messages: List of unified Message objects
            
        Returns:
            Provider-specific message format
        """
        pass
    
    @abstractmethod
    def convert_tools(self, tools: List[Tool]) -> List[Dict[str, Any]]:
        """
        Convert unified tools to provider-specific format.
        
        Args:
            tools: List of unified Tool objects
            
        Returns:
            Provider-specific tool format
        """
        pass
    
    @abstractmethod
    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """
        Get information about a specific model.
        
        Args:
            model_name: The model name
            
        Returns:
            ModelInfo if available, None otherwise
        """
        pass
    
    @abstractmethod
    async def list_models(self) -> List[ModelInfo]:
        """
        List available models from this provider.
        
        Returns:
            List of ModelInfo objects
        """
        pass
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    def supports_feature(self, feature: str) -> bool:
        """Check if provider supports a specific feature"""
        return feature in self.supported_features
    
    def validate_request(self, request: ChatCompletionRequest) -> Optional[str]:
        """
        Validate a request before sending.
        
        Args:
            request: The request to validate
            
        Returns:
            Error message if validation fails, None otherwise
        """
        if not request.model:
            return "Model is required"
        
        if not request.messages:
            return "Messages are required"
        
        return None


class ProviderAdapter:
    """
    Factory class for creating provider instances.
    Routes requests to the appropriate provider.
    """
    
    _providers: Dict[str, type] = {}
    
    @classmethod
    def register(cls, name: str, provider_class: type):
        """Register a provider class"""
        cls._providers[name.lower()] = provider_class
    
    @classmethod
    def create(cls, name: str, config: ProviderConfig) -> BaseProvider:
        """Create a provider instance"""
        name_lower = name.lower()
        if name_lower not in cls._providers:
            raise ValueError(f"Unknown provider: {name}")
        return cls._providers[name_lower](config)
    
    @classmethod
    def list_providers(cls) -> List[str]:
        """List registered providers"""
        return list(cls._providers.keys())
    
    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Check if a provider is registered"""
        return name.lower() in cls._providers