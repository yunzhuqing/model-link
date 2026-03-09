"""
AI Gateway API router.
Provides OpenAI-compatible and Anthropic-compatible endpoints.
Supports both JWT token and API key authentication.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional, Union, AsyncIterator
import json
import time
from datetime import datetime

from .. import models, database
from ..routers.users import get_current_user
from ..abstraction.messages import Message, MessageRole, ContentPart, ContentType
from ..abstraction.tools import Tool, ToolCall, ToolType, FunctionCall, FunctionDefinition
from ..abstraction.chat import (
    ChatCompletionRequest, ChatCompletionResponse, ChatChoice, Usage, ModelInfo, FinishReason
)
from ..abstraction.streaming import StreamChunk
from ..providers.base import ProviderConfig, ProviderAdapter
from ..providers.openai_provider import OpenAIProvider
from ..providers.anthropic_provider import AnthropicProvider
from ..providers.openai_compatible import (
    OpenAICompatibleProvider, OllamaProvider, VLLMProvider, 
    DeepSeekProvider, MoonshotProvider, ZhipuProvider
)

router = APIRouter()

# HTTP Bearer security scheme
security = HTTPBearer(auto_error=False)

# Register providers
ProviderAdapter.register("openai", OpenAIProvider)
ProviderAdapter.register("anthropic", AnthropicProvider)
ProviderAdapter.register("openai_compatible", OpenAICompatibleProvider)
ProviderAdapter.register("ollama", OllamaProvider)
ProviderAdapter.register("vllm", VLLMProvider)
ProviderAdapter.register("deepseek", DeepSeekProvider)
ProviderAdapter.register("moonshot", MoonshotProvider)
ProviderAdapter.register("zhipu", ZhipuProvider)


async def get_current_user_or_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(database.get_db)
) -> tuple[Optional[models.User], Optional[models.ApiKey]]:
    """
    Authenticate via either JWT token or API key.
    Returns (user, api_key) tuple - one will be None.
    """
    from jose import JWTError, jwt
    from ..auth import SECRET_KEY, ALGORITHM
    
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # First, try to find as API key
    api_key = db.query(models.ApiKey).filter(models.ApiKey.key == token).first()
    
    if api_key:
        # Validate API key
        if not api_key.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key is inactive"
            )
        
        # Check expiration
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired"
            )
        
        # Update last used time and increment request count
        api_key.last_used_at = datetime.utcnow()
        api_key.request_count += 1
        db.commit()
        
        return None, api_key
    
    # Try JWT token authentication
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token or API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user, None


def get_provider_instance(
    provider_model: models.Provider, 
    model: models.Model
) -> Any:
    """Create a provider instance from database model"""
    config = ProviderConfig(
        api_key=provider_model.api_key or "",
        base_url=provider_model.base_url,
        timeout=60
    )
    
    provider_name = provider_model.name.lower()
    
    # Try to match known providers
    if provider_name in ["openai", "anthropic", "ollama", "vllm", "deepseek", "moonshot", "zhipu"]:
        return ProviderAdapter.create(provider_name, config)
    
    # Default to OpenAI-compatible provider
    return OpenAICompatibleProvider(config, provider_model.name)


async def resolve_model(
    model_name: str, 
    db: Session
) -> tuple[models.Provider, models.Model]:
    """
    Resolve a model name to its provider and model configuration.
    
    Args:
        model_name: The model identifier (e.g., "gpt-4o", "claude-3-opus")
        db: Database session
        
    Returns:
        Tuple of (Provider, Model) from database
        
    Raises:
        HTTPException: If model not found
    """
    # Try to find the model in database
    db_model = db.query(models.Model).filter(models.Model.name == model_name).first()
    
    if db_model:
        db_provider = db.query(models.Provider).filter(
            models.Provider.id == db_model.provider_id
        ).first()
        if db_provider:
            return db_provider, db_model
    
    # Model not found, raise error
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Model '{model_name}' not found. Please configure it in the providers section."
    )


# ============== OpenAI Compatible Endpoints ==============

@router.get("/v1/models")
async def list_models(
    auth: tuple = Depends(get_current_user_or_api_key),
    db: Session = Depends(database.get_db)
):
    """List all available models (OpenAI compatible)"""
    current_user, api_key = auth
    providers = db.query(models.Provider).all()
    
    models_list = []
    for provider in providers:
        for model in provider.models:
            models_list.append({
                "id": model.name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": provider.name,
                "permission": [],
                "root": model.name,
                "parent": None,
            })
    
    return {
        "object": "list",
        "data": models_list
    }


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    auth: tuple = Depends(get_current_user_or_api_key),
    db: Session = Depends(database.get_db)
):
    """
    OpenAI-compatible chat completions endpoint.
    Supports both streaming and non-streaming responses.
    Supports JWT token or API key authentication.
    """
    current_user, api_key = auth
    body = await request.json()
    
    # Parse the request
    model_name = body.get("model")
    if not model_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Model is required"
        )
    
    messages_data = body.get("messages", [])
    if not messages_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Messages are required"
        )
    
    # Parse messages
    messages = []
    for msg in messages_data:
        role = msg.get("role")
        content = msg.get("content")
        
        # Handle multimodal content
        if isinstance(content, list):
            content_parts = []
            for part in content:
                if part.get("type") == "text":
                    content_parts.append(ContentPart(
                        type=ContentType.TEXT,
                        text=part.get("text", "")
                    ))
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url", {})
                    url = image_url.get("url", "")
                    if url.startswith("data:"):
                        # Base64 image
                        mime_end = url.index(";base64,")
                        mime_type = url[5:mime_end]
                        media = url[mime_end + 8:]
                        content_parts.append(ContentPart(
                            type=ContentType.IMAGE_BASE64,
                            media=media,
                            mime_type=mime_type
                        ))
                    else:
                        content_parts.append(ContentPart(
                            type=ContentType.IMAGE_URL,
                            url=url,
                            detail=image_url.get("detail")
                        ))
            message = Message(role=role, content=content_parts)
        else:
            message = Message(role=role, content=content)
        
        # Handle tool calls in assistant messages
        if role == "assistant" and "tool_calls" in msg:
            message.tool_calls = [
                ToolCall(
                    id=tc.get("id", ""),
                    type=tc.get("type", "function"),
                    function=FunctionCall(
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"]
                    )
                )
                for tc in msg["tool_calls"]
            ]
        
        # Handle tool response messages
        if "tool_call_id" in msg:
            message.tool_call_id = msg["tool_call_id"]
        
        messages.append(message)
    
    # Parse tools
    tools = None
    if "tools" in body:
        tools = []
        for tool_data in body["tools"]:
            if tool_data.get("type") == "function":
                func_data = tool_data.get("function", {})
                tools.append(Tool(
                    type=ToolType.FUNCTION,
                    function=FunctionDefinition(
                        name=func_data.get("name", ""),
                        description=func_data.get("description"),
                        parameters=func_data.get("parameters")
                    )
                ))
    
    # Create the unified request
    chat_request = ChatCompletionRequest(
        model=model_name,
        messages=messages,
        temperature=body.get("temperature"),
        top_p=body.get("top_p"),
        max_tokens=body.get("max_tokens"),
        max_completion_tokens=body.get("max_completion_tokens"),
        stop=body.get("stop"),
        frequency_penalty=body.get("frequency_penalty"),
        presence_penalty=body.get("presence_penalty"),
        logit_bias=body.get("logit_bias"),
        logprobs=body.get("logprobs"),
        top_logprobs=body.get("top_logprobs"),
        user=body.get("user"),
        seed=body.get("seed"),
        tools=tools,
        tool_choice=body.get("tool_choice"),
        parallel_tool_calls=body.get("parallel_tool_calls"),
        response_format=body.get("response_format"),
        stream=body.get("stream", False),
        stream_options=body.get("stream_options")
    )
    
    # Resolve model to provider
    provider, db_model = await resolve_model(model_name, db)
    
    # Create provider instance
    provider_instance = get_provider_instance(provider, db_model)
    
    try:
        if chat_request.stream:
            # Return streaming response
            return StreamingResponse(
                stream_response(provider_instance, chat_request),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # Return non-streaming response
            response = await provider_instance.chat_completion(chat_request)
            return response.model_dump()
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error from provider: {str(e)}"
        )


async def stream_response(
    provider_instance, 
    chat_request: ChatCompletionRequest
) -> AsyncIterator[str]:
    """Stream response chunks in SSE format"""
    try:
        async for chunk in provider_instance.stream_chat_completion(chat_request):
            yield chunk.to_sse()
        yield StreamChunk.create_done_chunk()
    except Exception as e:
        error_chunk = StreamChunk(
            id=f"error-{int(time.time())}",
            model=chat_request.model,
            choices=[]
        )
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


# ============== Anthropic Compatible Endpoints ==============

@router.get("/v1/complete")
async def anthropic_complete_placeholder():
    """Placeholder for Anthropic legacy complete endpoint"""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Please use /v1/messages for Anthropic API"
    )


@router.post("/v1/messages")
async def anthropic_messages(
    request: Request,
    auth: tuple = Depends(get_current_user_or_api_key),
    db: Session = Depends(database.get_db)
):
    """
    Anthropic-compatible messages endpoint.
    Accepts Anthropic API format and routes to configured providers.
    Supports JWT token or API key authentication.
    """
    current_user, api_key = auth
    body = await request.json()
    
    model_name = body.get("model")
    if not model_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Model is required"
        )
    
    messages_data = body.get("messages", [])
    system_prompt = body.get("system")
    
    # Build messages list
    messages = []
    
    # Add system message if present
    if system_prompt:
        messages.append(Message(role=MessageRole.SYSTEM, content=system_prompt))
    
    # Parse messages
    for msg in messages_data:
        role = msg.get("role")
        content = msg.get("content")
        
        # Handle content blocks
        if isinstance(content, list):
            content_parts = []
            for block in content:
                if block.get("type") == "text":
                    content_parts.append(ContentPart(
                        type=ContentType.TEXT,
                        text=block.get("text", "")
                    ))
                elif block.get("type") == "image":
                    source = block.get("source", {})
                    if source.get("type") == "base64":
                        content_parts.append(ContentPart(
                            type=ContentType.IMAGE_BASE64,
                            media=source.get("data"),
                            mime_type=source.get("media_type")
                        ))
                    elif source.get("type") == "url":
                        content_parts.append(ContentPart(
                            type=ContentType.IMAGE_URL,
                            url=source.get("url")
                        ))
                elif block.get("type") == "tool_use":
                    # Tool call in assistant message
                    pass  # Handle separately
            
            message = Message(role=role, content=content_parts if content_parts else None)
            
            # Handle tool_use blocks
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if tool_uses:
                message.tool_calls = [
                    ToolCall(
                        id=tu.get("id", ""),
                        type=ToolType.FUNCTION,
                        function=FunctionCall(
                            name=tu.get("name", ""),
                            arguments=json.dumps(tu.get("input", {}))
                        )
                    )
                    for tu in tool_uses
                ]
            
            messages.append(message)
        
        elif isinstance(content, str):
            messages.append(Message(role=role, content=content))
        
        # Handle tool_result content
        if msg.get("role") == "user":
            for block in (content if isinstance(content, list) else []):
                if block.get("type") == "tool_result":
                    messages.append(Message(
                        role=MessageRole.TOOL,
                        content=block.get("content", ""),
                        tool_call_id=block.get("tool_use_id", "")
                    ))
    
    # Parse tools
    tools = None
    if "tools" in body:
        tools = []
        for tool_data in body["tools"]:
            tools.append(Tool(
                type=ToolType.FUNCTION,
                function=FunctionDefinition(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description"),
                    parameters=tool_data.get("input_schema")
                )
            ))
    
    # Create the unified request
    chat_request = ChatCompletionRequest(
        model=model_name,
        messages=messages,
        max_tokens=body.get("max_tokens", 4096),
        temperature=body.get("temperature"),
        top_p=body.get("top_p"),
        stop=body.get("stop_sequences"),
        tools=tools,
        tool_choice=body.get("tool_choice"),
        stream=body.get("stream", False),
        user=body.get("metadata", {}).get("user_id")
    )
    
    # Resolve model to provider
    provider, db_model = await resolve_model(model_name, db)
    
    # Create provider instance
    provider_instance = get_provider_instance(provider, db_model)
    
    try:
        if chat_request.stream:
            # Return streaming response in Anthropic format
            return StreamingResponse(
                stream_anthropic_response(provider_instance, chat_request),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # Return non-streaming response
            response = await provider_instance.chat_completion(chat_request)
            return convert_to_anthropic_response(response)
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error from provider: {str(e)}"
        )


async def stream_anthropic_response(
    provider_instance,
    chat_request: ChatCompletionRequest
) -> AsyncIterator[str]:
    """Stream response chunks in Anthropic SSE format"""
    try:
        # Send message_start event
        message_id = f"msg_{int(time.time() * 1000)}"
        yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': message_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': chat_request.model}})}\n\n"
        
        content_index = 0
        text_buffer = ""
        
        async for chunk in provider_instance.stream_chat_completion(chat_request):
            for choice in chunk.choices:
                delta = choice.delta
                
                if delta.content:
                    # Send content_block_delta event
                    if not text_buffer:
                        # Start a new text block
                        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': content_index, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                        text_buffer = delta.content
                    else:
                        text_buffer += delta.content
                    
                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': content_index, 'delta': {'type': 'text_delta', 'text': delta.content}})}\n\n"
                
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': content_index, 'delta': {'type': 'input_json_delta', 'partial_json': tc.function.arguments}})}\n\n"
                
                if choice.finish_reason:
                    # Send content_block_stop and message_delta events
                    if text_buffer:
                        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': content_index})}\n\n"
                        content_index += 1
                    
                    finish_reason = "end_turn"
                    if choice.finish_reason == FinishReason.LENGTH:
                        finish_reason = "max_tokens"
                    elif choice.finish_reason == FinishReason.TOOL_CALLS:
                        finish_reason = "tool_use"
                    
                    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': finish_reason}, 'usage': {'output_tokens': chunk.usage.completion_tokens if chunk.usage else 0}})}\n\n"
        
        # Send message_stop event
        yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
    
    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': str(e)}})}\n\n"


def convert_to_anthropic_response(response: ChatCompletionResponse) -> Dict[str, Any]:
    """Convert unified response to Anthropic format"""
    content = []
    
    for choice in response.choices:
        message = choice.message
        
        if message.content:
            content.append({
                "type": "text",
                "text": message.content
            })
        
        if message.tool_calls:
            for tc in message.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": json.loads(tc.function.arguments) if tc.function.arguments else {}
                })
    
    stop_reason = "end_turn"
    if response.choices and response.choices[0].finish_reason:
        if response.choices[0].finish_reason == FinishReason.LENGTH:
            stop_reason = "max_tokens"
        elif response.choices[0].finish_reason == FinishReason.TOOL_CALLS:
            stop_reason = "tool_use"
    
    return {
        "id": response.id,
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": response.model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "cache_read_input_tokens": response.usage.cached_prompt_tokens,
            "cache_creation_input_tokens": response.usage.cache_creation_price
        }
    }