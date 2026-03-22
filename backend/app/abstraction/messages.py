"""
消息抽象模块 (Message Abstraction)
提供统一的消息格式，支持多模态内容（文本、图片、音频、视频、文件等）。
"""
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass


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
    def from_video_url(cls, url: str) -> 'ContentBlock':
        """从视频 URL 创建内容块"""
        return cls(type=ContentType.VIDEO_URL, url=url)
    
    @classmethod
    def from_video_base64(cls, data: str, media_type: str = "video/mp4") -> 'ContentBlock':
        """从 Base64 视频创建内容块"""
        return cls(type=ContentType.VIDEO_BASE64, data=data, media_type=media_type)
    
    @classmethod
    def from_audio_url(cls, url: str) -> 'ContentBlock':
        """从音频 URL 创建内容块"""
        return cls(type=ContentType.AUDIO_URL, url=url)
    
    @classmethod
    def from_audio_base64(cls, data: str, media_type: str = "audio/mp3") -> 'ContentBlock':
        """从 Base64 音频创建内容块"""
        return cls(type=ContentType.AUDIO_BASE64, data=data, media_type=media_type)
    
    @classmethod
    def from_file_url(cls, url: str) -> 'ContentBlock':
        """从文件 URL 创建内容块"""
        return cls(type=ContentType.FILE_URL, url=url)
    
    @classmethod
    def from_file_base64(cls, data: str, media_type: str = "application/octet-stream") -> 'ContentBlock':
        """从 Base64 文件创建内容块"""
        return cls(type=ContentType.FILE_BASE64, data=data, media_type=media_type)
    
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
        elif isinstance(self.content, list):
            # Convert any dict items to ContentBlock objects
            self.content = [self._ensure_content_block(item) for item in self.content]
    
    @staticmethod
    def _ensure_content_block(item: Union[ContentBlock, Dict[str, Any]]) -> ContentBlock:
        """Ensure an item is a ContentBlock, converting from dict if necessary"""
        if isinstance(item, ContentBlock):
            return item
        elif isinstance(item, dict):
            # Convert dict to ContentBlock
            content_type_str = item.get('type', 'text')
            # Normalize Responses API type names to internal ContentType values
            _type_map = {
                'input_text': 'text',
                'input_image': 'image_url',
                'input_audio': 'audio_url',
                'input_file': 'file_url',
            }
            content_type_str = _type_map.get(content_type_str, content_type_str)
            try:
                content_type = ContentType(content_type_str)
            except ValueError:
                content_type = ContentType.TEXT
            
            # Extract url: may be in 'url', or 'image_url' (string or dict)
            url = item.get('url')
            if not url:
                image_url_val = item.get('image_url')
                if isinstance(image_url_val, str):
                    url = image_url_val
                elif isinstance(image_url_val, dict):
                    url = image_url_val.get('url')

            return ContentBlock(
                type=content_type,
                text=item.get('text'),
                url=url,
                media_type=item.get('media_type'),
                data=item.get('data'),
                tool_call_id=item.get('tool_call_id') or item.get('id'),
                tool_name=item.get('tool_name') or item.get('name') or item.get('function', {}).get('name'),
                tool_arguments=item.get('tool_arguments') or item.get('function', {}).get('arguments'),
                tool_result=item.get('tool_result'),
                is_error=item.get('is_error', False)
            )
        else:
            # Unknown type, return empty text block
            return ContentBlock(type=ContentType.TEXT, text=str(item) if item else "")
    
    def get_text_content(self) -> Optional[str]:
        """获取文本内容"""
        if isinstance(self.content, str):
            return self.content
        elif isinstance(self.content, list):
            texts = []
            for block in self.content:
                # Handle both ContentBlock objects and dicts
                if isinstance(block, ContentBlock):
                    if block.type == ContentType.TEXT and block.text:
                        texts.append(block.text)
                elif isinstance(block, dict):
                    if block.get('type') == 'text' and block.get('text'):
                        texts.append(block.get('text'))
            return " ".join(texts) if texts else None
        return None
    
    def get_content_blocks(self) -> List[ContentBlock]:
        """获取内容块列表"""
        if isinstance(self.content, str):
            return [ContentBlock.from_text(self.content)]
        elif isinstance(self.content, list):
            return [self._ensure_content_block(item) for item in self.content]
        return []
