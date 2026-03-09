"""
Streaming abstraction layer - provides unified streaming response format.
"""
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
import time
import json

from .messages import Message, MessageRole
from .tools import ToolCall
from .chat import FinishReason, Usage


class StreamChoice(BaseModel):
    """A single streaming choice delta"""
    index: int = 0
    delta: Message
    finish_reason: Optional[FinishReason] = None
    
    model_config = {
        "use_enum_values": True
    }


class StreamChunk(BaseModel):
    """
    A single chunk in a streaming response.
    Compatible with OpenAI's streaming format.
    """
    id: str
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[StreamChoice]
    
    # Usage information (usually in the last chunk)
    usage: Optional[Usage] = None
    
    model_config = {
        "use_enum_values": True
    }
    
    def to_sse(self) -> str:
        """Convert to Server-Sent Events format"""
        return f"data: {self.model_dump_json()}\n\n"
    
    @staticmethod
    def create_done_chunk() -> str:
        """Create the final [DONE] chunk"""
        return "data: [DONE]\n\n"


class StreamManager:
    """
    Helper class to manage streaming responses.
    """
    def __init__(self, chunk_id: str, model: str):
        self.chunk_id = chunk_id
        self.model = model
        self.created = int(time.time())
        self.content_chunks: List[str] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self.finish_reason: Optional[FinishReason] = None
        self.usage: Optional[Usage] = None
    
    def add_content(self, content: str) -> StreamChunk:
        """Add content to the stream"""
        self.content_chunks.append(content)
        
        return StreamChunk(
            id=self.chunk_id,
            model=self.model,
            choices=[
                StreamChoice(
                    delta=Message(
                        role=MessageRole.ASSISTANT,
                        content=content
                    )
                )
            ]
        )
    
    def add_tool_call(self, tool_call: ToolCall) -> StreamChunk:
        """Add a tool call to the stream"""
        return StreamChunk(
            id=self.chunk_id,
            model=self.model,
            choices=[
                StreamChoice(
                    delta=Message(
                        role=MessageRole.ASSISTANT,
                        tool_calls=[tool_call]
                    )
                )
            ]
        )
    
    def set_finish(self, finish_reason: FinishReason) -> StreamChunk:
        """Set the finish reason"""
        self.finish_reason = finish_reason
        return StreamChunk(
            id=self.chunk_id,
            model=self.model,
            choices=[
                StreamChoice(
                    delta=Message(),
                    finish_reason=finish_reason
                )
            ]
        )
    
    def set_usage(self, usage: Usage) -> StreamChunk:
        """Set usage information (usually in the final chunk)"""
        self.usage = usage
        return StreamChunk(
            id=self.chunk_id,
            model=self.model,
            choices=[
                StreamChoice(
                    delta=Message(),
                    finish_reason=self.finish_reason
                )
            ],
            usage=usage
        )