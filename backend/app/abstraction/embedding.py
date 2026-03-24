"""
Embedding abstraction module.
Defines the unified embedding request and response models.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union


@dataclass
class EmbeddingRequest:
    """
    Unified embedding request model.
    
    Compatible with OpenAI embedding API format.
    Supports both text-only input and multimodal input (text + images).
    
    Text-only format:
        {"model": "...", "input": "text to embed"}
    
    Multimodal format:
        {"model": "...", "messages": [{"role": "user", "content": [...]}]}
    """
    model: str
    input: Optional[Union[str, List[str]]] = None  # Text(s) to embed (text-only mode)
    messages: Optional[List[Dict[str, Any]]] = None  # Multimodal messages (text + images)
    encoding_format: str = "float"  # "float", "base64"
    dimensions: Optional[int] = None  # Output dimensions (optional)
    user: Optional[str] = None  # User identifier
    metadata: Dict[str, Any] = field(default_factory=dict)  # Extra metadata

    @property
    def is_multimodal(self) -> bool:
        """Check if this is a multimodal embedding request."""
        return self.messages is not None


@dataclass
class EmbeddingData:
    """Single embedding result."""
    index: int
    embedding: Union[List[float], str]  # Vector or base64-encoded string
    object: str = "embedding"


@dataclass
class EmbeddingUsage:
    """Token usage info for embedding request."""
    prompt_tokens: int
    total_tokens: int


@dataclass
class EmbeddingResponse:
    """
    Unified embedding response model.
    
    Compatible with OpenAI embedding API format.
    """
    object: str = "list"
    data: List[EmbeddingData] = field(default_factory=list)
    model: str = ""
    usage: Optional[EmbeddingUsage] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "object": self.object,
            "data": [
                {
                    "object": d.object,
                    "index": d.index,
                    "embedding": d.embedding
                }
                for d in self.data
            ],
            "model": self.model,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens if self.usage else 0,
                "total_tokens": self.usage.total_tokens if self.usage else 0
            }
        }