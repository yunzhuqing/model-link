"""
Message abstraction layer - provides a unified message format
that can be converted to/from different provider formats.
"""
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Message role enum"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ContentType(str, Enum):
    """Content type enum for multimodal messages"""
    TEXT = "text"
    IMAGE_URL = "image_url"
    IMAGE_BASE64 = "image_base64"
    AUDIO_URL = "audio_url"
    AUDIO_BASE64 = "audio_base64"
    VIDEO_URL = "video_url"
    VIDEO_BASE64 = "video_base64"
    FILE_URL = "file_url"
    FILE_BASE64 = "file_base64"


class ContentPart(BaseModel):
    """
    A single content part in a multimodal message.
    Supports text, images, audio, video, and files.
    """
    type: ContentType
    
    # Text content
    text: Optional[str] = None
    
    # URL-based content
    url: Optional[str] = None
    
    # Base64 encoded content
    media: Optional[str] = None
    mime_type: Optional[str] = None
    
    # Image specific
    detail: Optional[str] = None  # "low", "high", "auto" for OpenAI
    
    # File specific
    filename: Optional[str] = None
    
    model_config = {
        "use_enum_values": True
    }


class Message(BaseModel):
    """
    Unified message format for all providers.
    Supports both simple text and multimodal content.
    """
    role: MessageRole
    content: Union[str, List[ContentPart], None] = None
    name: Optional[str] = None
    
    # For assistant messages with tool calls
    tool_calls: Optional[List["ToolCall"]] = None
    
    # For tool response messages
    tool_call_id: Optional[str] = None
    
    # Metadata for internal use
    metadata: Optional[Dict[str, Any]] = None
    
    model_config = {
        "use_enum_values": True
    }
    
    def get_text_content(self) -> str:
        """Extract text content from the message"""
        if isinstance(self.content, str):
            return self.content
        elif isinstance(self.content, list):
            texts = []
            for part in self.content:
                if part.type == ContentType.TEXT and part.text:
                    texts.append(part.text)
            return "\n".join(texts)
        return ""
    
    def is_multimodal(self) -> bool:
        """Check if message contains multimodal content"""
        if isinstance(self.content, list):
            return any(part.type != ContentType.TEXT for part in self.content)
        return False
    
    def get_content_types(self) -> List[ContentType]:
        """Get all content types in the message"""
        if isinstance(self.content, list):
            return [part.type for part in self.content]
        elif isinstance(self.content, str) and self.content:
            return [ContentType.TEXT]
        return []


# Import ToolCall at the end to avoid circular import
from .tools import ToolCall

# Update model config to resolve forward references
Message.model_rebuild()