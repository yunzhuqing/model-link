"""
Rerank abstraction module.
Defines the unified rerank request and response models.

Compatible with the vLLM /v1/rerank API format.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union


@dataclass
class RerankRequest:
    """
    Unified rerank request model.

    Compatible with the vLLM rerank API format:
        {"model": "...", "query": "...", "documents": [...], "top_n": 2}

    Supports both text-only and multimodal inputs:
    - Text query/documents: plain strings
    - Multimodal query:     {"text": "..."} | {"image": "..."} | {"video": "..."}
    - Multimodal documents: [{"text": "..."}, {"image": "..."}, {"video": "..."}]
    """
    model: str
    query: Union[str, Dict[str, Any]]                    # text string or multimodal dict
    documents: List[Union[str, Dict[str, Any]]]          # list of texts or multimodal dicts
    top_n: Optional[int] = None                          # number of results to return
    return_documents: bool = True                        # whether to return document content
    instruct: Optional[str] = None                       # optional instruction for the rerank model
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_multimodal(self) -> bool:
        """
        True if the query or any document is a dict (multimodal).
        """
        if isinstance(self.query, dict):
            return True
        return any(isinstance(d, dict) for d in self.documents)


@dataclass
class RerankDocument:
    """Single document in a rerank result."""
    text: Optional[str] = None
    image: Optional[str] = None
    video: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.text is not None:
            d["text"] = self.text
        if self.image is not None:
            d["image"] = self.image
        if self.video is not None:
            d["video"] = self.video
        return d


@dataclass
class RerankResult:
    """Single ranked result."""
    index: int
    relevance_score: float
    document: Optional[RerankDocument] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "index": self.index,
            "relevance_score": self.relevance_score,
        }
        if self.document is not None:
            d["document"] = self.document.to_dict()
        return d


@dataclass
class RerankUsage:
    """Token usage info for a rerank request."""
    total_tokens: int

    def to_dict(self) -> Dict[str, Any]:
        return {"total_tokens": self.total_tokens}


@dataclass
class RerankResponse:
    """
    Unified rerank response model.

    Compatible with the vLLM rerank API format:
    {
        "id": "rerank-xxx",
        "model": "...",
        "usage": {"total_tokens": 56},
        "results": [
            {"index": 1, "document": {"text": "..."}, "relevance_score": 0.99}
        ]
    }
    """
    id: str
    model: str
    results: List[RerankResult] = field(default_factory=list)
    usage: Optional[RerankUsage] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "model": self.model,
            "results": [r.to_dict() for r in self.results],
            "usage": self.usage.to_dict() if self.usage else {"total_tokens": 0},
        }
