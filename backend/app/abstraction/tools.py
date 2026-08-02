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
    IMAGE_GENERATION = "image_generation"
    CUSTOM = "custom"


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str = "string"
    description: Optional[str] = None
    required: bool = False
    enum: Optional[List[str]] = None
    default: Optional[Any] = None
    items: Optional[Dict[str, Any]] = None
    
    def to_json_schema(self) -> Dict[str, Any]:
        """转换为 JSON Schema 格式"""
        schema = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.enum:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        if self.items is not None:
            schema["items"] = self.items
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
    cache_control: Optional[Dict[str, Any]] = None  # Anthropic prompt caching: e.g. {"type": "ephemeral"}
    # 原始参数 JSON Schema 透传字段。
    # 当上游传入的工具参数包含 $defs/$ref/definitions/anyOf/oneOf/allOf/
    # 嵌套对象/format 等无法用扁平 ToolParameter 列表表达的结构时，
    # 直接保存原始 schema，避免在 ToolParameter 转换过程中丢失信息。
    # get_parameters_schema() 优先返回此字段。
    parameters_schema: Optional[Dict[str, Any]] = None
    # 工具来源标记。None 表示来自顶层 ``tools`` 字段；``"additional_tools"``
    # 表示来自 Responses API ``input`` 中的 ``additional_tools`` 条目。
    # Responses-API 上游（build_responses_request）会把这些工具从全局
    # ``tools`` 数组中排除（它们已随原始 additional_tools 条目透传）；
    # Chat-Completions 上游则把它们放入全局 ``tools`` 数组。
    source: Optional[str] = None
    # 原始工具定义透传。用于无法用 function 抽象忠实表达的工具类型
    # （如 Responses API ``additional_tools`` 里的 ``custom`` 工具,它带
    # ``format`` / ``defer_loading`` / ``allowed_callers`` 等专属字段）。
    # 序列化时若该字段非空,优先原样输出,避免字段丢失或类型降级。
    raw: Optional[Dict[str, Any]] = None

    def get_parameters_schema(self) -> Dict[str, Any]:
        """获取 JSON Schema 格式的参数定义

        优先返回原始透传的 parameters_schema（完整保留 $defs/$ref 等高级结构），
        否则回退到由 ToolParameter 列表重建的扁平 schema，保持向后兼容。
        """
        if self.parameters_schema:
            return self.parameters_schema

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
    # Custom tool (custom_tool_call) 专属字段，仅当 call_type == "custom" 时设置。
    # 用于在 Responses API 上无损还原 custom_tool_call 输出项。
    namespace: Optional[str] = None          # custom 工具命名空间
    caller: Optional[Dict[str, Any]] = None  # {"type": "direct"} | {"type": "program", "caller_id": ...}
    item_id: Optional[str] = None            # custom_tool_call 条目自身的 id（与 call id 不同）
    input_raw: Optional[str] = None          # 原始 "input" JSON 字符串（无损透传）


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


def has_image_generation_tool(tools: List[ToolDefinition]) -> bool:
    """Return True if any tool in *tools* has tool_type IMAGE_GENERATION."""
    return any(t.tool_type == ToolType.IMAGE_GENERATION for t in tools)