"""
消息抽象模块 (Message Abstraction)
提供统一的消息格式，支持多模态内容（文本、图片、音频、视频、文件等）。
"""
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field


class MessageRole(Enum):
    """消息角色枚举"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ContentType(Enum):
    """内容类型枚举"""
    TEXT = "text"
    IMAGE_URL = "image_url"
    IMAGE_BASE64 = "image_base64"
    AUDIO_URL = "audio_url"
    AUDIO_BASE64 = "audio_base64"
    VIDEO_URL = "video_url"
    VIDEO_BASE64 = "video_base64"
    FILE_URL = "file_url"
    FILE_BASE64 = "file_base64"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


@dataclass
class ContentBlock:
    """
    内容块 - 表示消息中的单个内容单元
    
    支持多种类型的内容：
    - 文本
    - 图片 (URL 或 Base64)
    - 音频 (URL 或 Base64)
    - 视频 (URL 或 Base64)
    - 文件 (URL 或 Base64)
    - 工具调用
    - 工具结果
    """
    type: ContentType
    text: Optional[str] = None
    url: Optional[str] = None
    media_type: Optional[str] = None  # MIME type: image/jpeg, audio/mp3, etc.
    data: Optional[str] = None  # Base64 data
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None
    tool_result: Optional[str] = None
    is_error: bool = False
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        if self.type == ContentType.TEXT:
            return {"type": "text", "text": self.text}
        
        elif self.type == ContentType.IMAGE_URL:
            return {
                "type": "image_url",
                "image_url": {"url": self.url}
            }
        
        elif self.type == ContentType.IMAGE_BASE64:
            return {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{self.media_type or 'image/jpeg'};base64,{self.data}"
                }
            }
        
        elif self.type == ContentType.AUDIO_URL:
            # OpenAI 格式可能需要调整
            return {
                "type": "input_audio",
                "input_audio": {"url": self.url}
            }
        
        elif self.type == ContentType.AUDIO_BASE64:
            return {
                "type": "input_audio",
                "input_audio": {
                    "data": self.data,
                    "format": self.media_type or "mp3"
                }
            }
        
        elif self.type == ContentType.TOOL_CALL:
            return {
                "type": "tool_use",
                "id": self.tool_call_id,
                "name": self.tool_name,
                "arguments": self.tool_arguments
            }
        
        elif self.type == ContentType.TOOL_RESULT:
            return {
                "type": "tool_result",
                "tool_use_id": self.tool_call_id,
                "content": self.tool_result,
                "is_error": self.is_error
            }
        
        # 默认返回字典格式
        return {
            "type": self.type.value,
            "url": self.url,
            "data": self.data,
            "media_type": self.media_type
        }
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        if self.type == ContentType.TEXT:
            return {"type": "text", "text": self.text}
        
        elif self.type == ContentType.IMAGE_URL:
            return {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": self.url
                }
            }
        
        elif self.type == ContentType.IMAGE_BASE64:
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": self.media_type or "image/jpeg",
                    "data": self.data
                }
            }
        
        elif self.type == ContentType.TOOL_CALL:
            return {
                "type": "tool_use",
                "id": self.tool_call_id,
                "name": self.tool_name,
                "input": self.tool_arguments
            }
        
        elif self.type == ContentType.TOOL_RESULT:
            return {
                "type": "tool_result",
                "tool_use_id": self.tool_call_id,
                "content": self.tool_result,
                "is_error": self.is_error
            }
        
        return self.to_openai_format()
    
    def to_bailian_format(self) -> Dict[str, Any]:
        """转换为百炼格式"""
        if self.type == ContentType.TEXT:
            return {"text": self.text}
        
        elif self.type == ContentType.IMAGE_URL:
            return {
                "image": self.url
            }
        
        elif self.type == ContentType.IMAGE_BASE64:
            return {
                "image": f"data:{self.media_type or 'image/jpeg'};base64,{self.data}"
            }
        
        elif self.type == ContentType.TOOL_CALL:
            return {
                "tool_call_id": self.tool_call_id,
                "name": self.tool_name,
                "arguments": self.tool_arguments
            }
        
        elif self.type == ContentType.TOOL_RESULT:
            return {
                "tool_call_id": self.tool_call_id,
                "content": self.tool_result,
                "is_error": self.is_error
            }
        
        return self.to_openai_format()
    
    @classmethod
    def from_text(cls, text: str) -> 'ContentBlock':
        """从文本创建内容块"""
        return cls(type=ContentType.TEXT, text=text)
    
    @classmethod
    def from_image_url(cls, url: str) -> 'ContentBlock':
        """从图片 URL 创建内容块"""
        return cls(type=ContentType.IMAGE_URL, url=url)
    
    @classmethod
    def from_image_base64(cls, data: str, media_type: str = "image/jpeg") -> 'ContentBlock':
        """从 Base64 图片创建内容块"""
        return cls(type=ContentType.IMAGE_BASE64, data=data, media_type=media_type)
    
    @classmethod
    def from_tool_call(cls, tool_call_id: str, tool_name: str, arguments: Dict[str, Any]) -> 'ContentBlock':
        """从工具调用创建内容块"""
        return cls(
            type=ContentType.TOOL_CALL,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments=arguments
        )
    
    @classmethod
    def from_tool_result(cls, tool_call_id: str, result: str, is_error: bool = False) -> 'ContentBlock':
        """从工具结果创建内容块"""
        return cls(
            type=ContentType.TOOL_RESULT,
            tool_call_id=tool_call_id,
            tool_result=result,
            is_error=is_error
        )


@dataclass
class Message:
    """
    消息 - 表示对话中的一条消息
    
    支持多种角色的消息，内容可以是单个文本或多个内容块。
    """
    role: MessageRole
    content: Union[str, List[ContentBlock], None] = None
    name: Optional[str] = None  # 用于工具调用时标识工具名称
    tool_call_id: Optional[str] = None  # 用于工具结果消息
    reasoning_content: Optional[str] = None  # 推理内容（如 DeepSeek R1）
    
    def __post_init__(self):
        """初始化后处理，自动转换字符串内容"""
        if isinstance(self.content, str):
            self.content = [ContentBlock.from_text(self.content)]
    
    def get_text_content(self) -> Optional[str]:
        """获取文本内容"""
        if isinstance(self.content, str):
            return self.content
        elif isinstance(self.content, list):
            texts = [block.text for block in self.content if block.type == ContentType.TEXT and block.text]
            return " ".join(texts) if texts else None
        return None
    
    def get_content_blocks(self) -> List[ContentBlock]:
        """获取内容块列表"""
        if isinstance(self.content, str):
            return [ContentBlock.from_text(self.content)]
        elif isinstance(self.content, list):
            return self.content
        return []
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        result = {"role": self.role.value}
        
        if self.name:
            result["name"] = self.name
        
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        
        if self.reasoning_content:
            result["reasoning_content"] = self.reasoning_content
        
        if isinstance(self.content, str):
            result["content"] = self.content
        elif isinstance(self.content, list):
            # 检查是否只有文本内容
            text_blocks = [b for b in self.content if b.type == ContentType.TEXT]
            tool_call_blocks = [b for b in self.content if b.type == ContentType.TOOL_CALL]
            
            if len(text_blocks) == len(self.content) and len(tool_call_blocks) == 0:
                # 只有文本，简化输出
                result["content"] = " ".join(b.text or "" for b in text_blocks)
            else:
                # 混合内容
                result["content"] = [b.to_openai_format() for b in self.content]
                
                # 如果有工具调用，添加到消息中
                if tool_call_blocks:
                    result["tool_calls"] = [
                        {
                            "id": b.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": b.tool_name,
                                "arguments": b.tool_arguments
                            }
                        }
                        for b in tool_call_blocks
                    ]
        
        return result
    
    def to_anthropic_format(self) -> Dict[str, Any]:
        """转换为 Anthropic 格式"""
        result = {"role": self.role.value}
        
        if self.role == MessageRole.SYSTEM:
            # Anthropic system 消息单独处理
            return {"type": "system", "content": self.get_text_content()}
        
        if isinstance(self.content, str):
            result["content"] = self.content
        elif isinstance(self.content, list):
            result["content"] = [b.to_anthropic_format() for b in self.content]
        
        return result
    
    def to_bailian_format(self) -> Dict[str, Any]:
        """转换为百炼格式"""
        result = {"role": self.role.value}
        
        if self.name:
            result["name"] = self.name
        
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        
        if self.reasoning_content:
            result["reasoning_content"] = self.reasoning_content
        
        if isinstance(self.content, str):
            result["content"] = self.content
        elif isinstance(self.content, list):
            # 检查是否包含工具调用
            text_blocks = [b for b in self.content if b.type == ContentType.TEXT]
            tool_call_blocks = [b for b in self.content if b.type == ContentType.TOOL_CALL]
            
            if tool_call_blocks:
                # 如果有工具调用，按照 OpenAI 兼容格式放在顶层
                result["tool_calls"] = [
                    {
                        "id": b.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": b.tool_name,
                            "arguments": b.tool_arguments if isinstance(b.tool_arguments, str) else json.dumps(b.tool_arguments, ensure_ascii=False)
                        }
                    }
                    for b in tool_call_blocks
                ]
                
                # content 设置为所有文本块的合并，如果没有则为 None 或 ""
                if text_blocks:
                    result["content"] = " ".join(b.text or "" for b in text_blocks)
                else:
                    result["content"] = None
            else:
                # 普通多模态或纯文本内容
                text_parts = []
                other_parts = []
                
                for block in self.content:
                    if block.type == ContentType.TEXT:
                        text_parts.append(block.text or "")
                    else:
                        other_parts.append(block.to_bailian_format())
                
                if text_parts and not other_parts:
                    result["content"] = " ".join(text_parts)
                else:
                    result["content"] = [b.to_bailian_format() for b in self.content]
        
        return result
    
    @classmethod
    def from_openai_format(cls, data: Dict[str, Any]) -> 'Message':
        """从 OpenAI 格式创建消息"""
        role = MessageRole(data.get("role", "user"))
        content = data.get("content") or ""
        name = data.get("name")
        tool_call_id = data.get("tool_call_id")
        reasoning_content = data.get("reasoning_content")
        
        blocks = []
        # 处理工具调用 (从顶层提取)
        if "tool_calls" in data:
            for tc in data["tool_calls"]:
                tc_id = tc.get("id")
                func = tc.get("function", {})
                tc_name = func.get("name")
                tc_args = func.get("arguments")
                
                # 解析参数字符串为字典
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except:
                        pass
                
                blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_args))

        # 处理多模态或纯文本内容
        if isinstance(content, list):
            for item in content:
                item_type = item.get("type", "text")
                
                if item_type == "text":
                    blocks.append(ContentBlock.from_text(item.get("text", "")))
                elif item_type == "image_url":
                    image_url = item.get("image_url", {})
                    url = image_url.get("url", "")
                    if url.startswith("data:"):
                        # Base64 图片
                        parts = url.split(",")
                        media_type = parts[0].replace("data:", "").replace(";base64", "")
                        data_str = parts[1] if len(parts) > 1 else ""
                        blocks.append(ContentBlock.from_image_base64(data_str, media_type))
                    else:
                        blocks.append(ContentBlock.from_image_url(url))
            
            content = blocks
        elif blocks:
            # 如果有工具调用块且 content 是字符串
            if content:
                blocks.insert(0, ContentBlock.from_text(content))
            content = blocks
        
        return cls(
            role=role, 
            content=content, 
            name=name, 
            tool_call_id=tool_call_id,
            reasoning_content=reasoning_content
        )
    
    @classmethod
    def from_anthropic_format(cls, data: Dict[str, Any]) -> 'Message':
        """从 Anthropic 格式创建消息"""
        role = MessageRole(data.get("role", "user"))
        content = data.get("content", "")
        
        # 处理多模态内容
        if isinstance(content, list):
            blocks = []
            for item in content:
                item_type = item.get("type", "text")
                
                if item_type == "text":
                    blocks.append(ContentBlock.from_text(item.get("text", "")))
                elif item_type == "image":
                    source = item.get("source", {})
                    source_type = source.get("type", "url")
                    
                    if source_type == "url":
                        blocks.append(ContentBlock.from_image_url(source.get("url", "")))
                    elif source_type == "base64":
                        blocks.append(ContentBlock.from_image_base64(
                            source.get("data", ""),
                            source.get("media_type", "image/jpeg")
                        ))
            
            content = blocks
        
        return cls(role=role, content=content)
    
    @classmethod
    def from_bailian_format(cls, data: Dict[str, Any]) -> 'Message':
        """从百炼格式创建消息"""
        role = MessageRole(data.get("role", "user"))
        content = data.get("content", "")
        name = data.get("name")
        tool_call_id = data.get("tool_call_id")
        
        # 处理多模态内容
        if isinstance(content, list):
            blocks = []
            for item in content:
                if "text" in item:
                    blocks.append(ContentBlock.from_text(item["text"]))
                elif "image" in item:
                    image = item["image"]
                    if image.startswith("data:"):
                        parts = image.split(",")
                        media_type = parts[0].replace("data:", "").replace(";base64", "")
                        data = parts[1] if len(parts) > 1 else ""
                        blocks.append(ContentBlock.from_image_base64(data, media_type))
                    else:
                        blocks.append(ContentBlock.from_image_url(image))
            
            content = blocks
        
        return cls(role=role, content=content, name=name, tool_call_id=tool_call_id)