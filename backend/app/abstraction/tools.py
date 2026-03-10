"""
工具抽象模块 (Tool Abstraction)
提供统一的工具定义和工具调用格式。
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field


class ToolType(Enum):
    """工具类型枚举"""
    FUNCTION = "function"
    CODE_INTERPRETER = "code_interpreter"
    RETRIEVAL = "retrieval"
    WEB_SEARCH = "web_search"


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str = "string"
    description: Optional[str] = None
    required: bool = False
    enum: Optional[List[str]] = None
    default: Optional[Any] = None
    
    def to_json_schema(self) -> Dict[str, Any]:
        """转换为 JSON Schema 格式"""
        schema = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.enum:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass
class ToolDefinition:
    """
    工具定义 - 描述一个可调用的工具
    
    支持不同供应商的工具定义格式转换。
    """
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)
    tool_type: ToolType = ToolType.FUNCTION
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        """获取 JSON Schema 格式的参数定义"""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }


@dataclass
class ToolCall:
    """
    工具调用 - 表示一个工具调用请求
    
    包含工具名称、参数和调用 ID。
    """
    id: str
    name: str
    arguments: Dict[str, Any]
    call_type: str = "function"


@dataclass
class ToolResult:
    """
    工具结果 - 表示工具调用的结果
    
    用于在对话中传递工具执行结果。
    """
    tool_call_id: str
    content: str
    is_error: bool = False
    name: Optional[str] = None