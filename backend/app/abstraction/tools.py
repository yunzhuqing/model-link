"""
Tool abstraction layer - provides unified tool/function calling format
compatible with OpenAI function calling and other providers.
"""
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
import uuid


class ToolType(str, Enum):
    """Tool type enum"""
    FUNCTION = "function"
    WEB_SEARCH = "web_search"
    TOOL_SEARCH = "tool_search"


class FunctionDefinition(BaseModel):
    """Function definition for tool calling"""
    name: str = Field(..., description="Function name")
    description: Optional[str] = Field(None, description="Function description")
    parameters: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema for function parameters"
    )
    strict: Optional[bool] = Field(None, description="Whether to use strict mode for schema validation")


class Tool(BaseModel):
    """
    Unified tool format for all providers.
    Represents a tool that can be called by the AI model.
    """
    type: ToolType = ToolType.FUNCTION
    function: Optional[FunctionDefinition] = None
    
    # For built-in tools like web search
    builtin: Optional[bool] = False
    
    model_config = {
        "use_enum_values": True
    }


class ToolCall(BaseModel):
    """
    Represents a tool call from the AI model.
    """
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:24]}")
    type: ToolType = ToolType.FUNCTION
    function: "FunctionCall"
    
    model_config = {
        "use_enum_values": True
    }


class FunctionCall(BaseModel):
    """
    Function call details.
    """
    name: str
    arguments: str  # JSON string of arguments


class ToolResult(BaseModel):
    """
    Result of a tool call to be passed back to the model.
    """
    tool_call_id: str
    content: str
    status: Optional[str] = "success"  # "success" or "error"
    
    def to_message(self) -> "Message":
        """Convert to a tool response message"""
        from .messages import Message, MessageRole
        return Message(
            role=MessageRole.TOOL,
            content=self.content,
            tool_call_id=self.tool_call_id,
            metadata={"status": self.status}
        )


class ToolChoice(str, Enum):
    """Tool choice options"""
    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"
    # Or a specific tool name


# Update forward references
ToolCall.model_rebuild()