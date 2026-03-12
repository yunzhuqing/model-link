"""
OpenAI 供应商实现 (OpenAI Provider)
实现 OpenAI API 的调用。
"""
from typing import Optional, List, Dict, Any, Generator
import json
import time
import uuid

from .base import BaseProvider, ProviderConfig, ProviderCapability
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall, ToolParameter, ToolType
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk


def parse_openai_request(data: dict) -> ChatRequest:
    """
    从 OpenAI 格式解析请求
    
    Args:
        data: OpenAI 格式的请求数据
    
    Returns:
        ChatRequest 对象
    """
    messages = []
    for msg_data in data.get('messages', []):
        role = MessageRole(msg_data.get('role', 'user'))
        content = msg_data.get('content')
        name = msg_data.get('name')
        tool_call_id = msg_data.get('tool_call_id')
        reasoning_content = msg_data.get('reasoning_content')
        
        blocks = []
        if 'tool_calls' in msg_data:
            for tc in msg_data['tool_calls']:
                tc_id = tc.get('id')
                func = tc.get('function', {})
                tc_name = func.get('name')
                tc_args = func.get('arguments')
                
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except:
                        pass
                
                blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_args if isinstance(tc_args, dict) else {}))
        
        if isinstance(content, list):
            for item in content:
                item_type = item.get('type', 'text')
                if item_type == 'text':
                    blocks.append(ContentBlock.from_text(item.get('text', '')))
                elif item_type == 'image_url':
                    image_url = item.get('image_url', {})
                    url = image_url.get('url', '')
                    if url.startswith('data:'):
                        parts = url.split(',')
                        media_type = parts[0].replace('data:', '').replace(';base64', '')
                        data_str = parts[1] if len(parts) > 1 else ''
                        blocks.append(ContentBlock.from_image_base64(data_str, media_type))
                    else:
                        blocks.append(ContentBlock.from_image_url(url))
                elif item_type == 'video_url':
                    video_url = item.get('video_url', {})
                    url = video_url.get('url', '')
                    blocks.append(ContentBlock.from_video_url(url))
                elif item_type == 'audio_url':
                    audio_url = item.get('audio_url', {})
                    url = audio_url.get('url', '')
                    blocks.append(ContentBlock.from_audio_url(url) if hasattr(ContentBlock, 'from_audio_url') else ContentBlock.from_video_url(url))
                elif item_type == 'file_url':
                    file_url = item.get('file_url', {})
                    url = file_url.get('url', '')
                    blocks.append(ContentBlock.from_file_url(url) if hasattr(ContentBlock, 'from_file_url') else ContentBlock.from_video_url(url))
            content = blocks if blocks else None
        elif blocks:
            if content:
                blocks.insert(0, ContentBlock.from_text(content))
            content = blocks
        
        messages.append(Message(
            role=role,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            reasoning_content=reasoning_content
        ))
    
    tools = []
    for tool_data in data.get('tools', []):
        func = tool_data.get('function', tool_data)
        name = func.get('name', '')
        description = func.get('description', '')
        params_schema = func.get('parameters', {})
        
        parameters = []
        properties = params_schema.get('properties', {})
        required = params_schema.get('required', [])
        
        for param_name, param_schema in properties.items():
            parameters.append(ToolParameter(
                name=param_name,
                type=param_schema.get('type', 'string'),
                description=param_schema.get('description'),
                required=param_name in required,
                enum=param_schema.get('enum'),
                default=param_schema.get('default')
            ))
        
        tools.append(ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            tool_type=ToolType.FUNCTION
        ))
    
    known_keys = {
        'model', 'messages', 'temperature', 'top_p', 'max_tokens',
        'stream', 'tools', 'tool_choice', 'stop', 'presence_penalty',
        'frequency_penalty', 'user'
    }
    metadata = {k: v for k, v in data.items() if k not in known_keys}
    
    return ChatRequest(
        messages=messages,
        model=data.get('model', ''),
        temperature=data.get('temperature'),
        top_p=data.get('top_p'),
        max_tokens=data.get('max_tokens'),
        stream=data.get('stream', False),
        tools=tools,
        tool_choice=data.get('tool_choice'),
        stop=data.get('stop'),
        presence_penalty=data.get('presence_penalty'),
        frequency_penalty=data.get('frequency_penalty'),
        user=data.get('user'),
        metadata=metadata
    )


class OpenAIProvider(BaseProvider):
    """
    OpenAI 供应商实现
    
    提供 OpenAI API 的调用能力。
    """
    
    PROVIDER_TYPE: str = "openai"
    
    # OpenAI 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
    ]
    
    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    
    # OpenAI 支持的模型列表
    SUPPORTED_MODELS = {
        "gpt-4o": {
            "description": "GPT-4o - 最先进的多模态模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4o-mini": {
            "description": "GPT-4o mini - 快速且经济的多模态模型",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4-turbo": {
            "description": "GPT-4 Turbo - 更快的 GPT-4",
            "context_size": 128000,
            "supports_vision": True,
        },
        "gpt-4": {
            "description": "GPT-4 - 高级推理能力",
            "context_size": 8192,
            "supports_vision": False,
        },
        "gpt-3.5-turbo": {
            "description": "GPT-3.5 Turbo - 快速且经济",
            "context_size": 16385,
            "supports_vision": False,
        },
    }
    
    def __init__(self, config: ProviderConfig):
        """
        初始化 OpenAI 供应商
        
        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        
        super().__init__(config)
    
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
    
    @property
    def client(self) -> Any:
        """获取 HTTP 客户端"""
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                timeout=self.config.timeout,
                headers=self.get_headers()
            )
        return self._client
    
    def supports_model(self, model: str) -> bool:
        """检查是否支持某个模型"""
        return True  # OpenAI 支持自定义模型
    
    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """获取模型信息"""
        if model in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model]
        return {
            "description": f"Model: {model}",
            "context_size": 8192,
            "supports_vision": False,
        }
    
    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据
        
        将 ChatRequest 转换为 OpenAI API 格式。
        
        Args:
            request: 对话请求对象
        
        Returns:
            OpenAI 请求字典
        """
        result = {
            "model": request.model,
            "messages": [self._message_to_openai(msg) for msg in request.messages],
            "stream": request.stream,
        }
        
        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.max_tokens is not None:
            result["max_tokens"] = request.max_tokens
        if request.tools:
            result["tools"] = [self._tool_to_openai(t) for t in request.tools]
        if request.tool_choice:
            result["tool_choice"] = request.tool_choice
        if request.stop:
            result["stop"] = request.stop
        if request.presence_penalty is not None:
            result["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            result["frequency_penalty"] = request.frequency_penalty
        if request.user:
            result["user"] = request.user
        
        # 添加额外参数
        result.update(request.metadata)
        
        return result
    
    def _message_to_openai(self, message: Message) -> Dict[str, Any]:
        """将 Message 转换为 OpenAI 格式"""
        result = {"role": message.role.value}
        
        if message.name:
            result["name"] = message.name
        
        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id
        
        if message.reasoning_content:
            result["reasoning_content"] = message.reasoning_content
        
        if isinstance(message.content, str):
            result["content"] = message.content
        elif isinstance(message.content, list):
            from app.abstraction.messages import ContentType
            text_blocks = [b for b in message.content if b.type == ContentType.TEXT]
            tool_call_blocks = [b for b in message.content if b.type == ContentType.TOOL_CALL]
            
            if len(text_blocks) == len(message.content) and len(tool_call_blocks) == 0:
                result["content"] = " ".join(b.text or "" for b in text_blocks)
            else:
                result["content"] = [self._content_block_to_openai(b) for b in message.content]
                
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
    
    def _content_block_to_openai(self, block) -> Dict[str, Any]:
        """将 ContentBlock 转换为 OpenAI 格式"""
        from app.abstraction.messages import ContentType
        
        if block.type == ContentType.TEXT:
            return {"type": "text", "text": block.text}
        elif block.type == ContentType.IMAGE_URL:
            return {"type": "image_url", "image_url": {"url": block.url}}
        elif block.type == ContentType.IMAGE_BASE64:
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{block.media_type or 'image/jpeg'};base64,{block.data}"}
            }
        elif block.type == ContentType.VIDEO_URL:
            return {"type": "video_url", "video_url": {"url": block.url}}
        elif block.type == ContentType.VIDEO_BASE64:
            return {
                "type": "video_url",
                "video_url": {"url": f"data:{block.media_type or 'video/mp4'};base64,{block.data}"}
            }
        elif block.type == ContentType.AUDIO_URL:
            return {"type": "audio_url", "audio_url": {"url": block.url}}
        elif block.type == ContentType.AUDIO_BASE64:
            return {
                "type": "audio_url",
                "audio_url": {"url": f"data:{block.media_type or 'audio/mp3'};base64,{block.data}"}
            }
        elif block.type == ContentType.FILE_URL:
            return {"type": "file_url", "file_url": {"url": block.url}}
        elif block.type == ContentType.FILE_BASE64:
            return {
                "type": "file_url",
                "file_url": {"url": f"data:{block.media_type or 'application/octet-stream'};base64,{block.data}"}
            }
        else:
            return {"type": block.type.value, "url": block.url, "data": block.data}
    
    def _tool_to_openai(self, tool: ToolDefinition) -> Dict[str, Any]:
        """将 ToolDefinition 转换为 OpenAI 格式"""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.get_parameters_schema()
            }
        }
    
    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析响应数据
        
        将 OpenAI 响应格式转换为 ChatResponse。
        
        Args:
            response_data: 响应数据
            model: 模型名称
        
        Returns:
            对话响应对象
        """
        choices = []
        for choice_data in response_data.get("choices", []):
            choice = self._parse_choice(choice_data)
            choices.append(choice)
        
        usage_data = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0)
        )
        
        return ChatResponse(
            id=response_data.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
            model=model,
            choices=choices,
            usage=usage,
            created=response_data.get("created", int(time.time())),
            provider=self.PROVIDER_TYPE
        )
    
    def _parse_choice(self, choice_data: Dict[str, Any]) -> ChatChoice:
        """解析单个选择项"""
        message_data = choice_data.get("message", {})
        message = self._parse_message(message_data) if message_data else None
        
        finish_reason_str = choice_data.get("finish_reason")
        finish_reason = FinishReason(finish_reason_str) if finish_reason_str else FinishReason.STOP
        
        tool_calls = []
        if "tool_calls" in message_data:
            tool_calls = [self._parse_tool_call(tc) for tc in message_data["tool_calls"]]
        
        return ChatChoice(
            index=choice_data.get("index", 0),
            message=message,
            finish_reason=finish_reason,
            tool_calls=tool_calls
        )
    
    def _parse_message(self, data: Dict[str, Any]) -> Message:
        """从 OpenAI 格式解析 Message"""
        role = MessageRole(data.get("role", "assistant"))
        content = data.get("content")
        name = data.get("name")
        tool_call_id = data.get("tool_call_id")
        reasoning_content = data.get("reasoning_content")
        
        blocks = []
        if "tool_calls" in data:
            for tc in data["tool_calls"]:
                tc_id = tc.get("id")
                func = tc.get("function", {})
                tc_name = func.get("name")
                tc_args = func.get("arguments")
                
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except:
                        pass
                
                from app.abstraction.messages import ContentBlock
                blocks.append(ContentBlock.from_tool_call(tc_id, tc_name, tc_args))
        
        if isinstance(content, list):
            from app.abstraction.messages import ContentBlock, ContentType
            for item in content:
                item_type = item.get("type", "text")
                if item_type == "text":
                    blocks.append(ContentBlock.from_text(item.get("text", "")))
                elif item_type == "image_url":
                    image_url = item.get("image_url", {})
                    url = image_url.get("url", "")
                    if url.startswith("data:"):
                        parts = url.split(",")
                        media_type = parts[0].replace("data:", "").replace(";base64", "")
                        data_str = parts[1] if len(parts) > 1 else ""
                        blocks.append(ContentBlock.from_image_base64(data_str, media_type))
                    else:
                        blocks.append(ContentBlock.from_image_url(url))
            content = blocks if blocks else None
        elif blocks:
            if content:
                from app.abstraction.messages import ContentBlock
                blocks.insert(0, ContentBlock.from_text(content))
            content = blocks
        
        return Message(
            role=role,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            reasoning_content=reasoning_content
        )
    
    def _parse_tool_call(self, data: Dict[str, Any]) -> ToolCall:
        """从 OpenAI 格式解析 ToolCall"""
        tool_id = data.get("id", "")
        call_type = data.get("type", "function")
        func = data.get("function", {})
        name = func.get("name", "")
        arguments_str = func.get("arguments", "{}")
        
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            arguments = {}
        
        return ToolCall(
            id=tool_id,
            name=name,
            arguments=arguments,
            call_type=call_type
        )
    
    def chat(self, request: ChatRequest) -> ChatResponse:
        """执行对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)
        
        request_data = self.prepare_request(request)
        request_data["stream"] = False
        
        url = f"{self.config.base_url}/chat/completions"
        
        try:
            response = self.client.post(url, json=request_data)
            
            if response.status_code >= 400:
                # Try to parse error response
                try:
                    error_data = response.json()
                    raise RuntimeError(f"OpenAI API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    raise RuntimeError(f"OpenAI API error ({response.status_code}): {response.text}")
            
            response.raise_for_status()
            
            response_data = response.json()
            return self.parse_response(response_data, request.model)
        
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"OpenAI API error: {str(e)}")
    
    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """执行流式对话请求"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)
        
        request_data = self.prepare_request(request)
        request_data["stream"] = True
        
        url = f"{self.config.base_url}/chat/completions"
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        
        try:
            with self.client.stream("POST", url, json=request_data) as response:
                # Check for error status before streaming
                if response.status_code >= 400:
                    # Read the error response and raise with details
                    error_text = ""
                    for chunk in response.iter_bytes():
                        if chunk:
                            error_text += chunk.decode('utf-8')
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(f"OpenAI API error ({response.status_code}): {json.dumps(error_data, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        raise RuntimeError(f"OpenAI API error ({response.status_code}): {error_text}")
                
                for line in response.iter_lines():
                    if not line:
                        continue
                    
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk_data = json.loads(data_str)
                            chunk = self._parse_stream_chunk(chunk_data, response_id, request.model)
                            if chunk:
                                yield chunk
                        except json.JSONDecodeError:
                            continue
        
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"OpenAI streaming API error: {str(e)}")
    
    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """解析流式响应块"""
        choices = data.get("choices", [])
        if not choices:
            return None
        
        choice = choices[0]
        delta = choice.get("delta", {})
        
        content = delta.get("content")
        role = delta.get("role")
        
        finish_reason_str = choice.get("finish_reason")
        finish_reason = None
        if finish_reason_str:
            try:
                finish_reason = FinishReason(finish_reason_str)
            except ValueError:
                finish_reason = FinishReason.STOP
        
        tool_calls = delta.get("tool_calls", [])
        
        return StreamChunk(
            id=data.get("id", response_id),
            model=data.get("model", model),
            delta_content=content,
            delta_role=role,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            created=data.get("created", int(time.time()))
        )
    
    def list_models(self) -> List[Dict[str, Any]]:
        """列出可用模型"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "openai",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 8192),
                "supports_vision": info.get("supports_vision", False),
            })
        return models