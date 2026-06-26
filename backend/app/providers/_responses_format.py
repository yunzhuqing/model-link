"""
OpenAI Responses API 格式转换共享模块 (Responses API Format Helpers)

提供将内部抽象类型（ChatRequest、Message 等）与 OpenAI Responses API
协议格式互相转换的纯函数。不依赖任何 Provider 实例状态，可被任意
Provider 直接导入使用。

职责边界
--------
- 请求构建：ChatRequest → Responses API 请求体 dict
- 响应解析：Responses API 响应体 dict → ChatResponse
- 消息转换：内部 Message ↔ Responses API input/output 格式

不包含 HTTP 调用、流式 SSE 解析、认证头构建等 Provider 特定逻辑。

使用方
------
- OpenAIResponsesCompatProvider
- AzureProvider (Responses API 路径)
- TencentVODProvider (Responses API 路径)
- 未来任何需要对接 Responses API 兼容接口的 Provider
"""
import json
import re
import time
import uuid
from typing import Dict, Any, List, Optional

from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.tools import ToolDefinition, ToolCall
from app.utils import json_loads

# ── 网关内部元数据键，不向上游透传 ──────────────────────────────
_GATEWAY_INTERNAL_KEYS = frozenset({
    'support_thinking', 'support_online_image', 'support_online_video', 'reasoning',
    'output_pricing', 'timeout', '_image_generation', '_video_generation',
    '_3d_generation', '_on_task_created', '_on_model_resolved',
    'verbosity',
})

# ── OpenAI Responses API 允许的元数据透传键 ──────────────────────
# build_responses_request 中，只有这些 OpenAI Responses API 规范字段才允许
# 通过 request.metadata 透传到上游请求体。其他字段由函数体显式构建。
_RESPONSES_API_METADATA_PASSTHROUGH = frozenset({
    'background',
    'context_management',
    'conversation',
    'include',
    'max_tool_calls',
    'metadata',           # OpenAI Responses API 顶层 metadata 字段
    'moderation',
    'parallel_tool_calls',
    'previous_response_id',
    'prompt',
    'prompt_cache_retention',
    'safety_identifier',
    'service_tier',
    'store',
    'stream_options',
    'top_logprobs',
    'truncation',
})


def _is_gpt5_or_newer(model: str) -> bool:
    """Check if model is GPT-5 or newer (these models don't support temperature)."""
    m = re.match(r'^gpt-(\d+)', model.lower())
    if m:
        return int(m.group(1)) >= 5
    return False


# ══════════════════════════════════════════════════════════════════
# 工具 / 格式转换
# ══════════════════════════════════════════════════════════════════


def response_format_to_responses_api(response_format: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Chat Completions response_format to Responses API text.format.

    Chat Completions format:
        {"type": "json_object"}
        {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}

    Responses API format:
        {"format": {"type": "json_object"}}
        {"format": {"type": "json_schema", "name": "...", "schema": {...}, "strict": true}}
    """
    fmt_type = response_format.get("type")
    if fmt_type == "json_schema":
        json_schema = response_format.get("json_schema", {})
        schema = json_schema.get("schema", {})
        if isinstance(schema, dict):
            if "additionalProperties" not in schema:
                schema = {**schema, "additionalProperties": False}
            if "required" not in schema and "properties" in schema:
                schema = {**schema, "required": list(schema["properties"].keys())}
        format_def: Dict[str, Any] = {
            "type": "json_schema",
            "name": json_schema.get("name", "response"),
            "schema": schema,
        }
        if json_schema.get("strict") is not None:
            format_def["strict"] = json_schema["strict"]
        else:
            format_def["strict"] = True
        return {"format": format_def}
    elif fmt_type == "json_object":
        return {"format": {"type": "json_object"}}
    else:
        return {"format": response_format}


def tool_to_responses_api(tool: ToolDefinition) -> Dict[str, Any]:
    """将 ToolDefinition 转换为 OpenAI Responses API flat 工具格式。

    Responses API 使用 flat 格式（无 ``function`` 包装）：
        {"type": "function", "name": "...", "description": "...", "parameters": {...}}

    Chat Completions 使用嵌套格式：
        {"type": "function", "function": {"name": "...", ...}}

    两者不兼容，需按 API 类型选择正确的转换函数。
    """
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.get_parameters_schema()
    }


def _tool_result_to_responses_output(tool_result):
    """将 tool_result 转换为 Responses API function_call_output.output。

    纯文本返回字符串；含图片/文件等多模态内容时返回 input_* 内容块数组
    （input_text / input_image / input_file），从而保留工具返回的图片。

    Responses API function_call_output.output 支持：
        string | [{"type":"input_text","text":...},
                  {"type":"input_image","image_url": "url|dataURI"},
                  {"type":"input_file","file_data": dataURI, "file_url":..., "filename":...}]
    """
    if not isinstance(tool_result, list):
        return tool_result or ""

    # 纯文本 → 扁平化为字符串（向后兼容）
    if all(b.type == ContentType.TEXT for b in tool_result):
        return " ".join(b.text or "" for b in tool_result)

    parts: List[Dict[str, Any]] = []
    for b in tool_result:
        if b.type == ContentType.TEXT:
            parts.append({"type": "input_text", "text": b.text or ""})
        elif b.type == ContentType.IMAGE_URL:
            parts.append({"type": "input_image", "image_url": b.url or ""})
        elif b.type == ContentType.IMAGE_BASE64:
            media = b.media_type or "image/jpeg"
            parts.append({
                "type": "input_image",
                "image_url": f"data:{media};base64,{b.data or ''}",
            })
        elif b.type == ContentType.FILE_URL:
            parts.append({"type": "input_file", "file_url": b.url or ""})
        elif b.type == ContentType.FILE_BASE64:
            media = b.media_type or "application/octet-stream"
            part: Dict[str, Any] = {
                "type": "input_file",
                "file_data": f"data:{media};base64,{b.data or ''}",
            }
            if b.filename:
                part["filename"] = b.filename
            parts.append(part)
    return parts if parts else ""


# ══════════════════════════════════════════════════════════════════
# 消息转换：内部 Message → Responses API input 条目
# ══════════════════════════════════════════════════════════════════

def _message_to_responses_items(message: Message) -> List[Dict[str, Any]]:
    """将单条 Message 转换为一个或多个 Responses API input 条目。

    Returns:
        Responses API input 条目列表（通常为 1 条，tool 调用时可能多条）
    """
    blocks = message.get_content_blocks()
    role = message.role

    # ── TOOL 角色：工具结果消息 ────────────────────────────────
    if role == MessageRole.TOOL:
        result: List[Dict[str, Any]] = []
        for block in blocks:
            if block.type == ContentType.TOOL_RESULT:
                result.append({
                    "type": "function_call_output",
                    "call_id": block.tool_call_id or message.tool_call_id or "",
                    "output": _tool_result_to_responses_output(block.tool_result),
                })
        if not result:
            text = " ".join(b.text or "" for b in blocks if b.type == ContentType.TEXT)
            result.append({
                "type": "function_call_output",
                "call_id": message.tool_call_id or "",
                "output": text,
            })
        return result

    # ── ASSISTANT 角色 ─────────────────────────────────────────
    if role == MessageRole.ASSISTANT:
        result = []

        for block in blocks:
            if block.type == ContentType.TOOL_CALL:
                args = block.tool_arguments or {}
                result.append({
                    "type": "function_call",
                    "call_id": block.tool_call_id or "",
                    "name": block.tool_name or "",
                    "arguments": (
                        args if isinstance(args, str)
                        else json.dumps(args, ensure_ascii=False)
                    ),
                })

        text_blocks = [b for b in blocks if b.type == ContentType.TEXT]
        if text_blocks:
            content_parts = [
                {"type": "output_text", "text": b.text or ""}
                for b in text_blocks
            ]
            result.append({
                "type": "message",
                "role": "assistant",
                "content": content_parts,
            })

        if not result:
            result.append({"type": "message", "role": "assistant", "content": []})

        return result

    # ── USER 角色（默认）──────────────────────────────────────
    tool_result_items: List[Dict[str, Any]] = []
    content_parts: List[Dict[str, Any]] = []

    for block in blocks:
        if block.type == ContentType.TOOL_RESULT:
            tool_result_items.append({
                "type": "function_call_output",
                "call_id": block.tool_call_id or "",
                "output": _tool_result_to_responses_output(block.tool_result),
            })
        elif block.type == ContentType.TEXT:
            content_parts.append({"type": "input_text", "text": block.text or ""})
        elif block.type in (ContentType.IMAGE_URL,):
            content_parts.append({"type": "input_image", "image_url": block.url or ""})
        elif block.type == ContentType.IMAGE_BASE64:
            media = block.media_type or "image/jpeg"
            content_parts.append({
                "type": "input_image",
                "image_url": f"data:{media};base64,{block.data or ''}",
            })
        elif block.type in (ContentType.AUDIO_URL,):
            content_parts.append({"type": "input_audio", "audio_url": block.url or ""})
        elif block.type == ContentType.AUDIO_BASE64:
            media = block.media_type or "audio/mp3"
            content_parts.append({
                "type": "input_audio",
                "data": block.data or "",
                "format": media.split("/")[-1] if "/" in (media or "") else "mp3",
            })
        elif block.type in (ContentType.FILE_URL,):
            content_parts.append({"type": "input_file", "file_url": block.url or ""})
        elif block.type == ContentType.FILE_BASE64:
            media = block.media_type or "application/octet-stream"
            filename = getattr(block, 'filename', None) or "document"
            content_parts.append({
                "type": "input_file",
                "file_data": f"data:{media};base64,{block.data or ''}",
                "filename": filename,
            })

    result = []
    result.extend(tool_result_items)
    if content_parts:
        result.append({"type": "message", "role": "user", "content": content_parts})
    elif not tool_result_items:
        result.append({"type": "message", "role": "user", "content": []})

    return result


def messages_to_responses_input(messages: List[Message]) -> List[Dict[str, Any]]:
    """将内部 Message 列表转换为 OpenAI Responses API 的 ``input`` 数组。

    Responses API input 格式规则
    ----------------------------
    - user 消息    → ``{"role": "user", "content": [{type: input_text/input_image/input_audio/input_file, ...}]}``
    - assistant 消息（含工具调用）→ 每个 tool_call 单独作为顶层 ``{"type": "function_call", ...}`` 条目，
      文本内容作为 ``{"role": "assistant", "content": [{type: output_text, ...}]}``
    - tool 消息（工具结果）→ 顶层 ``{"type": "function_call_output", "call_id": "...", "output": "..."}``
    """
    result: List[Dict[str, Any]] = []
    for msg in messages:
        items = _message_to_responses_items(msg)
        result.extend(items)
    return result


# ══════════════════════════════════════════════════════════════════
# 请求构建：ChatRequest → Responses API 请求体
# ══════════════════════════════════════════════════════════════════

def build_responses_request(request: ChatRequest) -> Dict[str, Any]:
    """将 ChatRequest 转换为 OpenAI Responses API 请求格式。

    规则：
      - 第一条 system 消息提取为 ``instructions``
      - 其余消息转换为 ``input`` 数组（OpenAI messages 格式）
      - max_tokens → max_output_tokens
      - reasoning_effort → reasoning.effort

    这是一个纯函数，不依赖 Provider 实例状态。
    调用方可在返回的 dict 上继续添加 Provider 特有字段。
    """
    other_messages = []
    developer_items = []
    for msg in request.messages:
        if msg.role == MessageRole.DEVELOPER:
            content = msg.get_text_content() or ''
            if content:
                developer_items.append({"role": "developer", "content": content})
        elif msg.role != MessageRole.SYSTEM:
            other_messages.append(msg)

    input_array = developer_items + messages_to_responses_input(other_messages)

    result: Dict[str, Any] = {
        "model": request.model,
        "input": input_array,
        "stream": request.stream,
    }

    if request.system is not None:
        if isinstance(request.system, list):
            instructions = " ".join(
                b.get("text", "") for b in request.system
                if isinstance(b, dict) and b.get("type") == "text"
            )
            if instructions:
                result["instructions"] = instructions
        else:
            result["instructions"] = request.system

    if request.temperature is not None:
        if not _is_gpt5_or_newer(request.model):
            result["temperature"] = request.temperature
    if request.top_p is not None:
        result["top_p"] = request.top_p
    if request.max_tokens is not None:
        result["max_output_tokens"] = request.max_tokens

    if request.tools:
        result["tools"] = [tool_to_responses_api(t) for t in request.tools]
    if request.tool_choice:
        result["tool_choice"] = request.tool_choice

    if request.response_format is not None:
        result["text"] = response_format_to_responses_api(request.response_format)
    
    # verbosity 在 Responses API 中应嵌套在 text 下，而非顶层参数
    verbosity = request.metadata.get("verbosity")
    if verbosity is not None:
        if "text" not in result:
            result["text"] = {}
        result["text"]["verbosity"] = verbosity

    if request.user:
        result["user"] = request.user

    if request.reasoning_effort and request.reasoning_effort != 'none':
        result["reasoning"] = {
            "effort": request.reasoning_effort,
            "summary": "auto",
        }

    for key, value in request.metadata.items():
        if key in _RESPONSES_API_METADATA_PASSTHROUGH and key not in _GATEWAY_INTERNAL_KEYS:
            result[key] = value

    return result


# ══════════════════════════════════════════════════════════════════
# 响应解析：Responses API 响应体 → ChatResponse
# ══════════════════════════════════════════════════════════════════

def parse_responses_response(response_data: Dict[str, Any], model: str) -> ChatResponse:
    """将 OpenAI Responses API 响应体解析为 ChatResponse。

    响应结构：
    {
      "id": "resp_xxx",
      "object": "response",
      "created_at": ...,
      "model": "...",
      "status": "completed",
      "output": [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "..."}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "..."}]},
        {"type": "function_call", "call_id": "...", "name": "...", "arguments": "..."}
      ],
      "usage": {"input_tokens": ..., "output_tokens": ..., "total_tokens": ...}
    }
    """
    output_items = response_data.get("output", [])
    status = response_data.get("status", "completed")

    # ── 检测特殊生成调用类型 ──────────────────────────────────────
    _GEN_TYPE_MAP = {
        "image_generation_call": "img",
        "video_generation_call": "vid",
        "3d_generation_call": "3d",
    }
    gen_type: Optional[str] = None
    gen_items: List[Dict[str, Any]] = []

    for item in output_items:
        item_type = item.get("type", "")
        if item_type in _GEN_TYPE_MAP:
            gen_type = gen_type or _GEN_TYPE_MAP[item_type]
            if item_type == "image_generation_call":
                gen_items.append({
                    "type": "image_generation_call",
                    "id": item.get("id", ""),
                    "status": item.get("status", "completed"),
                    "result": item.get("result", ""),
                })
            elif item_type == "video_generation_call":
                gen_items.append({
                    "type": "video_generation_call",
                    "id": item.get("id", ""),
                    "status": item.get("status", "completed"),
                    "result": item.get("result", ""),
                })
            elif item_type == "3d_generation_call":
                gen_items.append({
                    "type": "3d_generation_call",
                    "id": item.get("id", ""),
                    "status": item.get("status", "completed"),
                    "content": item.get("content", []),
                })

    if gen_type and gen_items:
        gen_json = json.dumps(gen_items, ensure_ascii=False)
        message = Message(
            role=MessageRole.ASSISTANT,
            content=gen_json,
        )
        choice = ChatChoice(
            index=0,
            message=message,
            finish_reason=FinishReason.STOP,
            tool_calls=[],
        )
        usage_data = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        raw_id = response_data.get("id", f"{gen_type}_{uuid.uuid4().hex[:8]}")
        created = response_data.get("created_at", int(time.time()))
        resp_id = raw_id if raw_id.startswith(f"{gen_type}_") or raw_id.startswith(f"{gen_type}-") else f"{gen_type}_{raw_id}"
        usage.extra['_upstream_status'] = status
        upstream_error = response_data.get("error")
        if upstream_error:
            usage.extra['_upstream_error'] = upstream_error
        return ChatResponse(
            id=resp_id,
            model=response_data.get("model", model),
            choices=[choice],
            usage=usage,
            created=created,
            provider="openai_responses_compt"
        )

    # ── 收集 reasoning content ────────────────────────────────────
    reasoning_text: Optional[str] = None
    for item in output_items:
        if item.get("type") == "reasoning":
            summaries = item.get("summary", [])
            parts = [s.get("text", "") for s in summaries if s.get("type") == "summary_text"]
            if parts:
                reasoning_text = "\n".join(parts)
                break

    # ── 收集文本 / 工具调用 ────────────────────────────────────────
    text_parts: List[str] = []
    tool_calls: List[ToolCall] = []
    tool_call_blocks: List[ContentBlock] = []

    for item in output_items:
        item_type = item.get("type", "")

        if item_type == "message":
            content_list = item.get("content", [])
            for content_block in content_list:
                block_type = content_block.get("type", "")
                if block_type in ("output_text", "text"):
                    text = content_block.get("text", "")
                    if text:
                        text_parts.append(text)

        elif item_type == "function_call":
            call_id = item.get("call_id") or item.get("id", "")
            name = item.get("name", "")
            args_str = item.get("arguments", "{}")
            try:
                args = json_loads(args_str) if isinstance(args_str, str) else args_str
            except (json.JSONDecodeError, TypeError):
                args = {}

            tool_calls.append(ToolCall(
                id=call_id,
                name=name,
                arguments=args,
                call_type="function"
            ))
            tool_call_blocks.append(ContentBlock.from_tool_call(call_id, name, args))

    full_text = "\n".join(text_parts) if text_parts else None
    content_blocks: List[ContentBlock] = []
    if full_text:
        content_blocks.append(ContentBlock.from_text(full_text))
    content_blocks.extend(tool_call_blocks)

    message = Message(
        role=MessageRole.ASSISTANT,
        content=content_blocks if content_blocks else (full_text or ""),
        reasoning_content=reasoning_text
    )

    status_to_finish: Dict[str, FinishReason] = {
        "completed": FinishReason.STOP,
        "incomplete": FinishReason.LENGTH,
        "failed": FinishReason.STOP,
    }
    if tool_calls:
        finish_reason = FinishReason.TOOL_CALLS
    else:
        finish_reason = status_to_finish.get(status, FinishReason.STOP)

    choice = ChatChoice(
        index=0,
        message=message,
        finish_reason=finish_reason,
        tool_calls=tool_calls,
        reasoning_content=reasoning_text
    )

    usage_data = response_data.get("usage", {})
    usage = UsageInfo(
        prompt_tokens=usage_data.get("input_tokens", 0),
        completion_tokens=usage_data.get("output_tokens", 0),
        total_tokens=usage_data.get("total_tokens", 0)
    )
    input_details = usage_data.get("input_tokens_details", {})
    output_details = usage_data.get("output_tokens_details", {})
    if input_details.get("cached_tokens"):
        usage.cached_tokens = input_details["cached_tokens"]
    if output_details.get("reasoning_tokens"):
        usage.reasoning_tokens = output_details["reasoning_tokens"]

    resp_id = response_data.get("id", f"resp_{uuid.uuid4().hex[:8]}")
    created = response_data.get("created_at", int(time.time()))

    usage.extra['_upstream_status'] = status
    upstream_error = response_data.get("error")
    if upstream_error:
        usage.extra['_upstream_error'] = upstream_error

    return ChatResponse(
        id=resp_id,
        model=response_data.get("model", model),
        choices=[choice],
        usage=usage,
        created=created,
        provider="openai_responses_compt"
    )
