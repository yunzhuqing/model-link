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
    DEVELOPER = "developer"  # Azure/OpenAI developer role, treated same as system
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

    def is_system_like(self) -> bool:
        """Return True for roles that act as system instructions (system, developer)."""
        return self in (MessageRole.SYSTEM, MessageRole.DEVELOPER)


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
    THINKING = "thinking"


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
    role: Optional[str] = None  # Media role: first_frame, last_frame, reference_image, reference_video, reference_audio
    view: Optional[str] = None  # 3D multi-view angle: front, back, left, right, up, down, left_front, right_front
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None
    # 工具结果：可以是纯文本字符串，也可以是多模态内容块列表（文本 + 图片）。
    # Anthropic 的 tool_result.content 原生支持内容块数组，例如工具返回图片。
    tool_result: Optional[Union[str, List["ContentBlock"]]] = None
    is_error: bool = False
    cache_control: Optional[Dict[str, Any]] = None  # Anthropic prompt caching: e.g. {"type": "ephemeral"}
    video_fps: Optional[str] = None  # FPS for video_url inputs (doubao, etc.)
    filename: Optional[str] = None  # filename for file content blocks (e.g. "document.pdf")
    signature: Optional[str] = None  # Anthropic thinking 块签名（仅 THINKING 类型使用）
    
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
    def from_video_url(cls, url: str, fps: str | None = None) -> 'ContentBlock':
        """从视频 URL 创建内容块"""
        return cls(type=ContentType.VIDEO_URL, url=url, video_fps=fps)
    
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
    def from_file_base64(cls, data: str, media_type: str = "application/octet-stream", filename: Optional[str] = None) -> 'ContentBlock':
        """从 Base64 文件创建内容块"""
        return cls(type=ContentType.FILE_BASE64, data=data, media_type=media_type, filename=filename)
    
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
    def from_tool_result(cls, tool_call_id: str, result: Union[str, List["ContentBlock"]], is_error: bool = False) -> 'ContentBlock':
        """从工具结果创建内容块（result 可为字符串或多模态内容块列表）"""
        return cls(
            type=ContentType.TOOL_RESULT,
            tool_call_id=tool_call_id,
            tool_result=result,
            is_error=is_error
        )

    def get_tool_result_text(self) -> str:
        """将 tool_result（字符串或内容块列表）扁平化为纯文本。

        供仅支持文本工具结果的供应商使用（Gemini、Vertex、Volcengine、Azure、
        Responses 等）。当 tool_result 为内容块列表时，仅提取其中的文本块，
        丢弃图片等非文本内容。
        """
        tr = self.tool_result
        if isinstance(tr, str):
            return tr
        if isinstance(tr, list):
            return " ".join(
                b.text or ""
                for b in tr
                if isinstance(b, ContentBlock) and b.type == ContentType.TEXT
            )
        return ""

    @classmethod
    def from_thinking(cls, thinking: str, signature: Optional[str] = None) -> 'ContentBlock':
        """从 Anthropic thinking 块创建内容块（thinking 文本存于 text，签名存于 signature）"""
        return cls(type=ContentType.THINKING, text=thinking, signature=signature)

    @classmethod
    def from_anthropic_content_item(cls, item: Any) -> Optional['ContentBlock']:
        """从 Anthropic 内容项（text / image）创建内容块。

        用于解析 tool_result.content 数组中的子内容块，例如工具返回图片：
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
        无法识别的类型返回 None。
        """
        if isinstance(item, str):
            return cls.from_text(item)
        if not isinstance(item, dict):
            return None
        itype = item.get('type', 'text')
        if itype == 'text':
            return cls.from_text(item.get('text', ''))
        if itype == 'image':
            source = item.get('source', {})
            source_type = source.get('type', 'url')
            if source_type == 'url':
                return cls.from_image_url(source.get('url', ''))
            if source_type == 'base64':
                raw_data = source.get('data', '')
                media_type = source.get('media_type', 'image/jpeg')
                # Strip data URI prefix if accidentally included
                if isinstance(raw_data, str) and raw_data.startswith('data:'):
                    parts = raw_data.split(',', 1)
                    if len(parts) > 1:
                        prefix = parts[0]  # "data:image/png;base64"
                        extracted_type = prefix.replace('data:', '').replace(';base64', '')
                        if extracted_type:
                            media_type = extracted_type
                        raw_data = parts[1]
                return cls.from_image_base64(raw_data, media_type)
        return None


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
                'file': 'file_base64',
            }
            content_type_str = _type_map.get(content_type_str, content_type_str)
            try:
                content_type = ContentType(content_type_str)
            except ValueError:
                content_type = ContentType.TEXT

            # Anthropic thinking 块: {"type":"thinking","thinking":"...","signature":"..."}
            # 文本字段是 'thinking'，需映射到 ContentBlock.text
            text_val = item.get('text')
            if content_type == ContentType.THINKING and text_val is None:
                text_val = item.get('thinking')

            # Extract url: may be in 'url', or 'image_url' (string or dict)
            url = item.get('url')
            if not url:
                image_url_val = item.get('image_url')
                if isinstance(image_url_val, str):
                    url = image_url_val
                elif isinstance(image_url_val, dict):
                    url = image_url_val.get('url')

            # Extract file-related fields from 'file' sub-object (OpenAI format)
            data = item.get('data')
            filename = item.get('filename')
            file_obj = item.get('file', {})
            if isinstance(file_obj, dict):
                if file_obj.get('file_data'):
                    fd = file_obj['file_data']
                    if isinstance(fd, str) and fd.startswith(("http://", "https://")):
                        url = fd
                        if content_type == ContentType.FILE_BASE64:
                            content_type = ContentType.FILE_URL
                    else:
                        data = fd
                if file_obj.get('filename'):
                    filename = file_obj['filename']
                # file_id → treat as file_url type
                if file_obj.get('file_id'):
                    url = file_obj['file_id']
                    if content_type == ContentType.FILE_BASE64:
                        content_type = ContentType.FILE_URL

            # Extract tool_call_id: may be 'tool_call_id', 'id', or 'tool_use_id' (Anthropic format)
            tool_call_id = item.get('tool_call_id') or item.get('tool_use_id') or item.get('id')

            # Extract tool_result: may be 'tool_result', or 'content' for tool_result type blocks
            tool_result_val = item.get('tool_result')
            if tool_result_val is None and content_type == ContentType.TOOL_RESULT:
                # Anthropic format: tool_result block uses 'content' for the result text
                raw_content = item.get('content')
                if isinstance(raw_content, str):
                    tool_result_val = raw_content
                elif isinstance(raw_content, list):
                    # content can be a list of content blocks, including images:
                    #   [{"type": "text", "text": "..."},
                    #    {"type": "image", "source": {...}}]
                    parsed_blocks = []
                    for part in raw_content:
                        blk = ContentBlock.from_anthropic_content_item(part)
                        if blk is not None:
                            parsed_blocks.append(blk)
                    if any(b.type != ContentType.TEXT for b in parsed_blocks):
                        # 含图片等非文本内容 → 保留为内容块列表
                        tool_result_val = parsed_blocks
                    elif parsed_blocks:
                        # 纯文本 → 扁平化为字符串（向后兼容）
                        tool_result_val = '\n'.join(b.text or '' for b in parsed_blocks)
                    else:
                        tool_result_val = None

            return ContentBlock(
                type=content_type,
                text=text_val,
                url=url,
                media_type=item.get('media_type'),
                data=data,
                filename=filename,
                role=item.get('role'),
                tool_call_id=tool_call_id,
                tool_name=item.get('tool_name') or item.get('name') or item.get('function', {}).get('name'),
                tool_arguments=item.get('tool_arguments') or item.get('function', {}).get('arguments'),
                tool_result=tool_result_val,
                is_error=item.get('is_error', False),
                cache_control=item.get('cache_control'),
                video_fps=item.get('video_fps'),
                signature=item.get('signature'),
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
