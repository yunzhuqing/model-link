"""
工具抽象模块 (Tool Abstraction)
提供统一的工具定义和工具调用格式。
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import json


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
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema()
            }
        }
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.get_parameters_schema()
        }
    
    def to_bailian_format(self) -> Dict[str, Any]:
        """转换为百炼格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema()
            }
        }
    
    @classmethod
    def from_openai_format(cls, data: Dict[str, Any]) -> 'ToolDefinition':
        """从 OpenAI 格式创建工具定义"""
        func = data.get("function", data)
        name = func.get("name", "")
        description = func.get("description", "")
        params_schema = func.get("parameters", {})
        
        parameters = []
        properties = params_schema.get("properties", {})
        required = params_schema.get("required", [])
        
        for param_name, param_schema in properties.items():
            parameters.append(ToolParameter(
                name=param_name,
                type=param_schema.get("type", "string"),
                description=param_schema.get("description"),
                required=param_name in required,
                enum=param_schema.get("enum"),
                default=param_schema.get("default")
            ))
        
        return cls(
            name=name,
            description=description,
            parameters=parameters,
            tool_type=ToolType.FUNCTION
        )
    
    @classmethod
    def from_anthropic_format(cls, data: Dict[str, Any]) -> 'ToolDefinition':
        """从 Anthropic 格式创建工具定义"""
        name = data.get("name", "")
        description = data.get("description", "")
        input_schema = data.get("input_schema", {})
        
        parameters = []
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])
        
        for param_name, param_schema in properties.items():
            parameters.append(ToolParameter(
                name=param_name,
                type=param_schema.get("type", "string"),
                description=param_schema.get("description"),
                required=param_name in required,
                enum=param_schema.get("enum"),
                default=param_schema.get("default")
            ))
        
        return cls(
            name=name,
            description=description,
            parameters=parameters,
            tool_type=ToolType.FUNCTION
        )
    
    @classmethod
    def from_bailian_format(cls, data: Dict[str, Any]) -> 'ToolDefinition':
        """从百炼格式创建工具定义"""
        func = data.get("function", data)
        name = func.get("name", "")
        description = func.get("description", "")
        params_schema = func.get("parameters", {})
        
        parameters = []
        properties = params_schema.get("properties", {})
        required = params_schema.get("required", [])
        
        for param_name, param_schema in properties.items():
            parameters.append(ToolParameter(
                name=param_name,
                type=param_schema.get("type", "string"),
                description=param_schema.get("description"),
                required=param_name in required,
                enum=param_schema.get("enum"),
                default=param_schema.get("default")
            ))
        
        return cls(
            name=name,
            description=description,
            parameters=parameters,
            tool_type=ToolType.FUNCTION
        )


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
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        return {
            "id": self.id,
            "type": self.call_type,
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False)
            }
        }
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        return {
            "type": "tool_use",
            "id": self.id,
            "name": self.name,
            "input": self.arguments
        }
    
    def to_bailian_format(self) -> Dict[str, Any]:
        """转换为百炼格式"""
        return {
            "id": self.id,
            "type": self.call_type,
            "function": {
                "name": self.name,
                "arguments": self.arguments
            }
        }
    
    @classmethod
    def from_openai_format(cls, data: Dict[str, Any]) -> 'ToolCall':
        """从 OpenAI 格式创建工具调用"""
        tool_id = data.get("id", "")
        call_type = data.get("type", "function")
        func = data.get("function", {})
        name = func.get("name", "")
        arguments_str = func.get("arguments", "{}")
        
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            arguments = {}
        
        return cls(
            id=tool_id,
            name=name,
            arguments=arguments,
            call_type=call_type
        )
    
    @classmethod
    def from_anthropic_format(cls, data: Dict[str, Any]) -> 'ToolCall':
        """从 Anthropic 格式创建工具调用"""
        tool_id = data.get("id", "")
        name = data.get("name", "")
        arguments = data.get("input", {})
        call_type = data.get("type", "function")
        
        return cls(
            id=tool_id,
            name=name,
            arguments=arguments,
            call_type=call_type
        )
    
    @classmethod
    def from_bailian_format(cls, data: Dict[str, Any]) -> 'ToolCall':
        """从百炼格式创建工具调用"""
        tool_id = data.get("id", "")
        call_type = data.get("type", "function")
        func = data.get("function", {})
        name = func.get("name", "")
        arguments = func.get("arguments", {})
        
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        
        return cls(
            id=tool_id,
            name=name,
            arguments=arguments,
            call_type=call_type
        )


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
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        result = {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content
        }
        return result
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        return {
            "type": "tool_result",
            "tool_use_id": self.tool_call_id,
            "content": self.content,
            "is_error": self.is_error
        }
    
    def to_bailian_format(self) -> Dict[str, Any]:
        """转换为百炼格式"""
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
            "is_error": self.is_error
        }
    
    @classmethod
    def from_openai_format(cls, data: Dict[str, Any]) -> 'ToolResult':
        """从 OpenAI 格式创建工具结果"""
        return cls(
            tool_call_id=data.get("tool_call_id", ""),
            content=data.get("content", ""),
            is_error=False,
            name=data.get("name")
        )
    
    @classmethod
    def from_anthropic_format(cls, data: Dict[str, Any]) -> 'ToolResult':
        """从 Anthropic 格式创建工具结果"""
        return cls(
            tool_call_id=data.get("tool_use_id", ""),
            content=data.get("content", ""),
            is_error=data.get("is_error", False)
        )
    
    @classmethod
    def from_bailian_format(cls, data: Dict[str, Any]) -> 'ToolResult':
        """从百炼格式创建工具结果"""
        return cls(
            tool_call_id=data.get("tool_call_id", ""),
            content=data.get("content", ""),
            is_error=data.get("is_error", False),
            name=data.get("name")
        )


class Tool:
    """
    工具 - 工具定义、调用和结果的容器类
    
    提供工具相关的静态方法和工厂方法。
    """
    
    @staticmethod
    def parse_tools_from_openai(tools: List[Dict[str, Any]]) -> List[ToolDefinition]:
        """从 OpenAI 格式解析工具列表"""
        return [ToolDefinition.from_openai_format(t) for t in tools]
    
    @staticmethod
    def parse_tools_from_anthropic(tools: List[Dict[str, Any]]) -> List[ToolDefinition]:
        """从 Anthropic 格式解析工具列表"""
        return [ToolDefinition.from_anthropic_format(t) for t in tools]
    
    @staticmethod
    def parse_tools_from_bailian(tools: List[Dict[str, Any]]) -> List[ToolDefinition]:
        """从百炼格式解析工具列表"""
        return [ToolDefinition.from_bailian_format(t) for t in tools]
    
    @staticmethod
    def parse_tool_calls_from_openai(tool_calls: List[Dict[str, Any]]) -> List[ToolCall]:
        """从 OpenAI 格式解析工具调用列表"""
        return [ToolCall.from_openai_format(tc) for tc in tool_calls]
    
    @staticmethod
    def parse_tool_calls_from_anthropic(tool_calls: List[Dict[str, Any]]) -> List[ToolCall]:
        """从 Anthropic 格式解析工具调用列表"""
        return [ToolCall.from_anthropic_format(tc) for tc in tool_calls]
    
    @staticmethod
    def parse_tool_calls_from_bailian(tool_calls: List[Dict[str, Any]]) -> List[ToolCall]:
        """从百炼格式解析工具调用列表"""
        return [ToolCall.from_bailian_format(tc) for tc in tool_calls]
    
    @staticmethod
    def convert_tools_to_openai(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """将工具定义列表转换为 OpenAI 格式"""
        return [t.to_openai_format() for t in tools]
    
    @staticmethod
    def convert_tools_to_anthropic(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """将工具定义列表转换为 Anthropic 格式"""
        return [t.to_anthropic_format() for t in tools]
    
    @staticmethod
    def convert_tools_to_bailian(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """将工具定义列表转换为百炼格式"""
        return [t.to_bailian_format() for t in tools]
    
    @staticmethod
    def convert_tool_calls_to_openai(tool_calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """将工具调用列表转换为 OpenAI 格式"""
        return [tc.to_openai_format() for tc in tool_calls]
    
    @staticmethod
    def convert_tool_calls_to_anthropic(tool_calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """将工具调用列表转换为 Anthropic 格式"""
        return [tc.to_anthropic_format() for tc in tool_calls]
    
    @staticmethod
    def convert_tool_calls_to_bailian(tool_calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """将工具调用列表转换为百炼格式"""
        return [tc.to_bailian_format() for tc in tool_calls]