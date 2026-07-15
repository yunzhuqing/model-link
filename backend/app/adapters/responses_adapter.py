"""
OpenAI Responses API 适配器
处理 /v1/responses 格式的请求和响应转换。

OpenAI Responses API 是 OpenAI 的新一代 API 格式，
与 Chat Completions 相比有以下不同：
- 使用 `input` 替代 `messages`
- 使用 `instructions` 替代 system message
- 使用 `max_output_tokens` 替代 `max_tokens`
- 响应使用 `output` 替代 `choices`
- 流式事件使用更细粒度的事件类型
"""
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

from .base import BaseAdapter
from app.utils import gen_id as _gen_id, REASONING_EFFORT_DEFAULT_FOR_THINKING, json_loads

logger = logging.getLogger("gateway")

from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.utils import json_loads
from app.abstraction.tools import ToolDefinition, ToolParameter, ToolType

# ═══════════════════════════════════════════════════════════════════════
# Module-level content / tool parsing helpers
# ═══════════════════════════════════════════════════════════════════════

def _extract_str(block: dict, key: str) -> str:
    """Extract a string value from a block dict, auto-unwrapping {'url': ...} dicts."""
    val = block.get(key, '')
    if isinstance(val, dict):
        val = val.get('url', '')
    return val


def _safe_list(val) -> list:
    """Return val as a list if it is a list, otherwise an empty list."""
    return val if isinstance(val, list) else []


def _register_fid_media(file_map: dict, block: dict):
    """Register a file_id → media mapping from a content block.

    When a block has a file_id but no concrete URL (e.g. input_image with only
    file_id, no image_url), the file_id itself is stored as a placeholder URL.
    The gateway's _resolve_file_ids will later resolve it to asset://asset-xxx.
    """
    fid = block.get('file_id', '')
    if not fid:
        return
    blk_type = block.get('type', '')
    role = block.get('role', '')
    if blk_type in ('input_image', 'image'):
        url = _extract_str(block, 'image_url') or fid
        file_map[fid] = {'type': 'image', 'url': url, 'role': role}
    elif blk_type in ('input_video', 'video'):
        url = _extract_str(block, 'video_url') or fid
        file_map[fid] = {'type': 'video', 'url': url, 'role': role}
    elif blk_type in ('input_audio', 'audio'):
        url = _extract_str(block, 'audio_url') or _extract_str(block, 'url') or fid
        file_map[fid] = {'type': 'audio', 'url': url, 'role': role}


def _parse_image_block(block: dict) -> ContentBlock:
    """Parse a single image content block (input_image / image type)."""
    image_role = block.get('role')
    if 'image_url' in block:
        url = _extract_str(block, 'image_url')
        if url.startswith('data:'):
            parts = url.split(',')
            media_type = parts[0].replace('data:', '').replace(';base64', '')
            data_str = parts[1] if len(parts) > 1 else ''
            cb = ContentBlock.from_image_base64(data_str, media_type)
        else:
            cb = ContentBlock.from_image_url(url)
    elif 'source' in block:
        source = block['source']
        if source.get('type') == 'base64':
            cb = ContentBlock.from_image_base64(
                source.get('data', ''),
                source.get('media_type', 'image/jpeg')
            )
        else:
            cb = ContentBlock.from_image_url(source.get('url', ''))
    elif block.get('file_id'):
        # file_id-only reference (no image_url) — preserve as URL for later resolution
        cb = ContentBlock.from_image_url(block['file_id'])
    else:
        cb = ContentBlock.from_text('')
    cb.role = image_role or cb.role
    cb.view = block.get('view')  # 3D multi-view angle
    return cb


def _parse_content_blocks(blocks: list) -> list:
    """Parse a list of content block dicts → ContentBlock objects.

    Handles: input_text, output_text, text, input_image, input_video, input_audio, input_file.
    Shared by both pure-content-block messages and content arrays inside
    role-based messages — this is the single source of truth for block parsing.
    """
    result = []
    for block in blocks:
        block_type = block.get('type', 'input_text')
        if block_type in ('input_text', 'output_text', 'text'):
            result.append(ContentBlock.from_text(block.get('text', '')))
        elif block_type in ('input_image', 'image'):
            result.append(_parse_image_block(block))
        elif block_type in ('input_video', 'video'):
            url = _extract_str(block, 'video_url')
            if url:
                fps = block.get('fps')
                cb = ContentBlock.from_video_url(url, fps=str(fps) if fps is not None else None)
                cb.role = block.get('role') or cb.role
                result.append(cb)
            elif block.get('file_id'):
                # file_id-only reference — preserve as URL for later resolution
                cb = ContentBlock.from_video_url(block['file_id'])
                cb.role = block.get('role') or cb.role
                result.append(cb)
        elif block_type == 'input_audio':
            if 'input_audio' in block:
                a = block['input_audio']
                result.append(ContentBlock.from_audio_base64(
                    a.get('data', ''),
                    f"audio/{a.get('format', 'wav')}"
                ))
            elif block.get('audio_url'):
                url = block['audio_url']
                if isinstance(url, dict):
                    url = url.get('url', '')
                cb = ContentBlock.from_audio_url(url)
                cb.role = block.get('role') or cb.role
                result.append(cb)
            elif block.get('file_id'):
                # file_id-only reference — preserve as URL for later resolution
                result.append(ContentBlock.from_audio_url(block['file_id']))
        elif block_type == 'input_file':
            file_block = _file_block_from_item(block)
            if file_block is not None:
                result.append(file_block)
        elif block_type == 'function_call':
            call_id = block.get('call_id', block.get('id', ''))
            name = block.get('name', '')
            args = block.get('arguments', '{}')
            if isinstance(args, str):
                try:
                    args = json_loads(args)
                except Exception:
                    args = {}
            result.append(ContentBlock.from_tool_call(call_id, name, args))
        elif block_type == 'function_call_output':
            call_id = block.get('call_id', '')
            output = block.get('output', '')
            # Parse nested content blocks in output (e.g. input_image)
            if isinstance(output, list):
                parsed_output = _parse_content_blocks(output)
                output = parsed_output if parsed_output else output
            result.append(ContentBlock.from_tool_result(call_id, output))
    return result


# ── Input item handlers (used by _dispatch_input_item) ──────────────────

def _handle_function_call_item(item: dict, messages: list):
    """Convert a function_call input item → assistant Message with tool_call block.

    Consecutive function_call items are merged into a single assistant message
    (they represent one model turn with multiple parallel tool calls), so that
    downstream providers requiring tool-call / tool-result pairing (e.g.
    DeepSeek, Bailian) can correctly match tool responses to their calls.

    Also merges into a preceding assistant message that carries text content
    or reasoning, producing a single assistant turn with content + tool_calls.
    """
    args_str = item.get('arguments', '{}')
    try:
        args = json_loads(args_str) if isinstance(args_str, str) else args_str
    except (json.JSONDecodeError, TypeError):
        args = {}
    call_id = item.get('call_id') or item.get('id', '')
    block = ContentBlock.from_tool_call(call_id, item.get('name', ''), args)

    if messages:
        last = messages[-1]
        if last.role == MessageRole.ASSISTANT:
            # Case 1: previous assistant message contains *only* tool_call blocks
            if (isinstance(last.content, list)
                    and last.content
                    and all(isinstance(b, ContentBlock) and b.type == ContentType.TOOL_CALL
                            for b in last.content)):
                last.content.append(block)
                return
            # Case 2: previous assistant message is reasoning-only (no content / empty)
            # Merge tool_calls into the same turn so reasoning_content + tool_calls
            # coexist in one assistant message.
            if last.reasoning_content and (not last.content or (isinstance(last.content, list) and not last.content)):
                if last.content is None:
                    last.content = [block]
                elif isinstance(last.content, list) and not last.content:
                    last.content.append(block)
                else:
                    last.content = [block]
                return
            # Case 3: previous assistant message has text content (string or list
            # with non-tool-call blocks).  Merge tool_calls into the same turn so
            # that content + tool_calls coexist in one message.  This handles
            # /v1/responses input like:
            #   [message(assistant, text), function_call, function_call_output]
            if isinstance(last.content, str):
                if last.content.strip():
                    last.content = [ContentBlock.from_text(last.content), block]
                else:
                    last.content = [block]
                return
            if isinstance(last.content, list) and last.content:
                has_non_tc = any(
                    isinstance(b, ContentBlock) and b.type != ContentType.TOOL_CALL
                    for b in last.content
                )
                if has_non_tc:
                    last.content.append(block)
                    return

    messages.append(Message(role=MessageRole.ASSISTANT, content=[block]))


def _handle_generation_call_item(item: dict, messages: list, item_type: str):
    """Convert a generation_call item → assistant Message with tool_call block."""
    call_id = item.get('id', '')
    tool_name = item_type.replace('_call', '')  # e.g. 'image_generation'
    if item_type == '3d_generation_call':
        payload = {'status': item.get('status', 'completed'),
                   'content': item.get('content', [])}
    else:
        payload = {'status': item.get('status', 'completed'),
                   'result': item.get('result', '')}
    block = ContentBlock.from_tool_call(call_id, tool_name, payload)
    messages.append(Message(role=MessageRole.ASSISTANT, content=[block]))


def _image_block_from_ref(ref: str) -> Optional[ContentBlock]:
    """从 image_url / file_id 字符串构造图片内容块（支持 data URI base64）。"""
    if not isinstance(ref, str) or not ref:
        return None
    if ref.startswith('data:'):
        # data:image/png;base64,xxxx
        head, _, b64 = ref.partition(',')
        media_type = head.replace('data:', '').replace(';base64', '') or 'image/jpeg'
        return ContentBlock.from_image_base64(b64, media_type)
    return ContentBlock.from_image_url(ref)


def _file_block_from_item(it: dict) -> Optional[ContentBlock]:
    """从 input_file 项构造文件内容块。"""
    file_data = it.get('file_data')
    file_url = it.get('file_url')
    filename = it.get('filename')
    if isinstance(file_data, str) and file_data:
        if file_data.startswith(('http://', 'https://')):
            block = ContentBlock.from_file_url(file_data)
            if filename:
                block.filename = filename
            return block
        if file_data.startswith('data:'):
            head, _, b64 = file_data.partition(',')
            media_type = head.replace('data:', '').replace(';base64', '') or 'application/octet-stream'
        else:
            b64 = file_data
            media_type = 'application/octet-stream'
        return ContentBlock.from_file_base64(b64, media_type, filename)
    ref = file_url or it.get('file_id')
    if isinstance(ref, str) and ref:
        block = ContentBlock.from_file_url(ref)
        if filename:
            block.filename = filename
        return block
    return None


def _parse_function_call_output(output):
    """解析 function_call_output.output（字符串或 input_* 数组）为 tool_result 值。

    Responses API 支持工具结果包含图片/文件：
        output: string | [{"type":"input_text",...},
                          {"type":"input_image","image_url": "url|dataURI", "file_id":...},
                          {"type":"input_file","file_data": dataURI, "file_url":..., "filename":...}]
    含图片/文件时返回 ContentBlock 列表，纯文本返回字符串（向后兼容）。
    """
    if isinstance(output, str):
        return output
    if not isinstance(output, list):
        return str(output) if output is not None else ''

    blocks: list = []
    for it in output:
        if isinstance(it, str):
            blocks.append(ContentBlock.from_text(it))
            continue
        if not isinstance(it, dict):
            continue
        itype = it.get('type', 'input_text')
        if itype in ('input_text', 'text', 'output_text'):
            blocks.append(ContentBlock.from_text(it.get('text', '')))
        elif itype in ('input_image', 'image'):
            ref = it.get('image_url') or it.get('url') or it.get('file_id') or ''
            blk = _image_block_from_ref(ref)
            if blk is not None:
                blocks.append(blk)
        elif itype in ('input_file', 'file'):
            blk = _file_block_from_item(it)
            if blk is not None:
                blocks.append(blk)

    if any(b.type != ContentType.TEXT for b in blocks):
        # 含图片/文件 → 保留为内容块列表
        return blocks
    if blocks:
        # 纯文本 → 扁平化为字符串
        return ' '.join(b.text or '' for b in blocks)
    return ''


def _handle_function_call_output_item(item: dict, messages: list):
    """Convert a function_call_output item → tool Message."""
    call_id = item.get('call_id', '')
    result_value = _parse_function_call_output(item.get('output', ''))
    block = ContentBlock.from_tool_result(call_id, result_value)
    messages.append(Message(role=MessageRole.TOOL, content=[block], tool_call_id=call_id))


def _handle_reasoning_item(item: dict, messages: list):
    """Convert a reasoning input item → assistant Message with reasoning_content.

    Priority for extracting reasoning text:
      1. summary (array of summary_text blocks)
      2. encrypted_content
      3. content (reasoning_text block or plain string)
    """
    reasoning_content = ""

    # Priority 1: summary array of summary_text blocks
    for block in _safe_list(item.get('summary')):
        if isinstance(block, dict) and block.get('type') == 'summary_text':
            text = block.get('text', '')
            if text:
                if reasoning_content:
                    reasoning_content += '\n' + text
                else:
                    reasoning_content = text

    # Priority 2: encrypted_content
    if not reasoning_content:
        encrypted = item.get('encrypted_content', '')
        if isinstance(encrypted, str) and encrypted:
            reasoning_content = encrypted

    # Priority 3: content dict or string
    if not reasoning_content:
        content = item.get('content', '')
        if isinstance(content, dict) and content.get('type') == 'reasoning_text':
            reasoning_content = content.get('text', '')
        elif isinstance(content, str):
            reasoning_content = content

    if not reasoning_content:
        return

    if messages:
        last = messages[-1]
        if last.role == MessageRole.ASSISTANT and not last.reasoning_content:
            # Merge into an assistant message that is either:
            #   - reasoning-only / content-empty, or
            #   - tool_call-only (consecutive function_call items)
            last.reasoning_content = reasoning_content
            return

    messages.append(Message(role=MessageRole.ASSISTANT, reasoning_content=reasoning_content))


def _handle_role_message_item(item: dict, messages: list):
    """Convert a role-based message item → Message.

    When the content array contains function_call / function_call_output blocks
    mixed with regular content blocks (non-standard but common client bug),
    split them into separate messages: assistant (tool_calls) + tool (results).
    The remaining regular content stays in the original role.

    Also merges into a preceding reasoning-only or tool_calls assistant message
    so that content + reasoning + tool_calls coexist in a single assistant turn.
    Providers like Moonshot and MiniMax require strict adjacency and reject
    intervening assistant messages.
    """
    role = MessageRole(item.get('role', 'user'))
    content = item.get('content', '')

    if isinstance(content, list):
        blocks = _parse_content_blocks(content)
        if blocks:
            # ── Split mixed content: tool_calls → assistant, tool_results → tool ──
            regular_blocks = []
            tool_call_blocks = []
            tool_result_blocks = []
            for b in blocks:
                if isinstance(b, ContentBlock):
                    if b.type == ContentType.TOOL_CALL:
                        tool_call_blocks.append(b)
                    elif b.type == ContentType.TOOL_RESULT:
                        tool_result_blocks.append(b)
                    else:
                        regular_blocks.append(b)
                else:
                    regular_blocks.append(b)

            # Emit in conversation order: user text → assistant (tool_calls) → tool (results)
            if regular_blocks:
                messages.append(Message(
                    role=role,
                    content=regular_blocks,
                    name=item.get('name'),
                ))
            if tool_call_blocks:
                messages.append(Message(
                    role=MessageRole.ASSISTANT,
                    content=tool_call_blocks,
                ))
            for b in tool_result_blocks:
                messages.append(Message(
                    role=MessageRole.TOOL,
                    content=[b] if not isinstance(b, list) else b,
                    tool_call_id=b.tool_call_id,
                ))
            return

    # ── Merge with preceding assistant message ──
    if role == MessageRole.ASSISTANT and messages:
        last = messages[-1]
        if last.role == MessageRole.ASSISTANT:
            # Case A: preceding assistant is reasoning-only (no content / empty).
            # Merge text content into the same turn.
            if last.reasoning_content and (not last.content or (isinstance(last.content, list) and not last.content)):
                last.content = content
                return
            # Case B: preceding assistant has tool_calls in its content list.
            # Merge non-tool-call content blocks into the same turn.
            if isinstance(last.content, list):
                has_tool_calls = any(
                    isinstance(b, ContentBlock) and b.type == ContentType.TOOL_CALL
                    for b in last.content
                )
                if has_tool_calls:
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, ContentBlock) and block.type != ContentType.TOOL_CALL:
                                last.content.append(block)
                    elif isinstance(content, str) and content:
                        last.content.append(ContentBlock.from_text(content))
                    reasoning = item.get('reasoning_content')
                    if reasoning and not last.reasoning_content:
                        last.reasoning_content = reasoning
                    return

    messages.append(Message(
        role=role,
        content=content,
        name=item.get('name'),
        tool_call_id=item.get('call_id') or item.get('tool_call_id'),
    ))


# ── Tool definition parsers ─────────────────────────────────────────────

def _parse_function_tool_def(tool_data: dict) -> ToolDefinition:
    """Parse a function tool definition dict → ToolDefinition."""
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
            default=param_schema.get('default'),
            items=param_schema.get('items'),
        ))

    return ToolDefinition(
        name=name,
        description=description,
        parameters=parameters,
        tool_type=ToolType.FUNCTION,
        parameters_schema=params_schema or None,
    )


def _extract_video_gen_metadata(tool_data: dict, file_id_media_map: dict) -> dict:
    """Extract video_generation tool params → metadata dict."""
    meta = {'_video_generation': True}

    size = tool_data.get('size')
    if size and isinstance(size, str):
        meta['size'] = size.replace("*", "x").replace("×", "x")
    aspect_ratio = tool_data.get('aspect_ratio')
    if aspect_ratio:
        meta['aspect_ratio'] = aspect_ratio
    resolution = tool_data.get('resolution')
    if resolution:
        meta['resolution'] = resolution
    seconds = tool_data.get('seconds')
    if seconds is not None:
        meta['seconds'] = seconds
    n = tool_data.get('n')
    if n is not None:
        meta['n'] = int(n)
    generate_audio = tool_data.get('generate_audio')
    if generate_audio is not None:
        meta['generate_audio'] = bool(generate_audio)
    watermark = tool_data.get('watermark')
    if watermark is not None:
        meta['watermark'] = bool(watermark)
    person_generation = tool_data.get('person_generation')
    if person_generation:
        meta['person_generation'] = person_generation

    raw_parameters = tool_data.get('parameters')
    if isinstance(raw_parameters, dict):
        meta['parameters'] = raw_parameters

    if file_id_media_map:
        meta['file_id_media_map'] = file_id_media_map

    return meta


def _extract_image_gen_metadata(tool_data: dict) -> dict:
    """Extract image_generation tool params → metadata dict."""
    meta = {}

    size = tool_data.get('size')
    if size and isinstance(size, str):
        meta['size'] = size.replace("*", "x").replace("×", "x")
    n = tool_data.get('n') or tool_data.get('number') or tool_data.get('count')
    if n is not None:
        meta['number'] = int(n)
    response_format = tool_data.get('response_format')
    if response_format:
        meta['response_format'] = response_format
    image_format = tool_data.get('image_format') or tool_data.get('output_format')
    if image_format:
        meta['image_format'] = image_format
    seed = tool_data.get('seed')
    if seed is not None:
        meta['seed'] = seed
    watermark = tool_data.get('watermark')
    if watermark is not None:
        meta['watermark'] = bool(watermark)
    aspect_ratio = tool_data.get('aspect_ratio')
    if aspect_ratio:
        meta['aspect_ratio'] = aspect_ratio
    resolution = tool_data.get('resolution')
    if resolution:
        meta['resolution'] = resolution
    quality = tool_data.get('quality')
    if quality:
        meta['quality'] = quality

    return meta


async def _convert_image_url_to_b64(url: str, fallback_mime: str = "image/png") -> Optional[str]:
    """Download an image URL and return it as a base64 data URI.

    Returns ``data:<mime>;base64,<b64data>`` on success, or ``None`` on failure.
    """
    from app.http_client import shared_redirect_client
    import base64 as _base64
    try:
        async with shared_redirect_client() as client:
            resp = await client.get(url, timeout=60)
            resp.raise_for_status()
            content_type = (
                resp.headers.get("content-type", "").split(";")[0].strip()
                or fallback_mime
            )
            content = resp.content

        def _encode():
            b64 = _base64.b64encode(content).decode("ascii")
            return f"data:{content_type};base64,{b64}"

        return await asyncio.to_thread(_encode)
    except Exception:
        return None


async def _apply_b64_json_to_image_output(output: list, storage=None) -> None:
    """Convert ``image_generation_call`` result URLs to base64 data URIs in-place.

    Resolution order:
      1. Use ``_b64_data`` / ``_mime_type`` stored on the item by
         ``_save_image_data_uris_to_storage()`` — zero-download, fast path.
      2. For local file paths (e.g. ``/v1/files/...``), read via ``storage.read_binary()``.
      3. For HTTP(S) URLs, download and convert via ``_convert_image_url_to_b64()``.

    When *storage* is provided (a ``StorageBackend`` instance), local file paths
    are resolved via ``storage.read_binary()``.
    """
    import base64 as _base64

    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get('type') != 'image_generation_call':
            continue
        url = item.get('result', '')
        if not url or not isinstance(url, str) or url.startswith('data:'):
            continue

        # Priority 1: use preserved base64 data from _save_image_data_uris_to_storage
        _b64 = item.get('_b64_data')
        _mime = item.get('_mime_type')
        if _b64 and _mime:
            item['result'] = f"data:{_mime};base64,{_b64}"
            continue

        b64_data = None
        content_type = "image/png"

        # Priority 2: try storage backend for local file paths
        if storage is not None and url.startswith('/'):
            try:
                def _read_and_encode():
                    raw = storage.read_binary(url)
                    if raw:
                        return "image/png", _base64.b64encode(raw).decode("ascii")
                    return None, None

                content_type, b64_data = await asyncio.to_thread(_read_and_encode)
            except Exception:
                pass

        # Priority 3: HTTP download fallback
        if b64_data is None:
            b64_result = await _convert_image_url_to_b64(url)
            if b64_result:
                item['result'] = b64_result
            continue

        item['result'] = f"data:{content_type};base64,{b64_data}"


async def _save_image_data_uris_to_storage(output: list, storage, response_id: str) -> None:
    """Save image data URIs to binary storage and replace with storage URLs.

    Scans *output* for ``image_generation_call`` items whose ``result`` is a
    data URI (``data:<mime>;base64,<data>``), decodes the base64 payload, saves
    it to the configured storage backend via ``write_binary()``, and replaces the
    data URI with the returned storage URL.

    The original base64 data is preserved as ``_b64_data`` and ``_mime_type``
    on the item so that ``_apply_b64_json_to_image_output()`` can use it directly
    without needing to re-download the image from the storage URL.

    Does nothing for items whose result is already a URL (not a data URI).

    Args:
        output:     List of output items (modified in-place).
        storage:    ``StorageBackend`` instance.
        response_id: Unique response identifier for generating file keys.
    """
    import base64 as _base64

    for i, item in enumerate(output):
        if not isinstance(item, dict):
            continue
        if item.get('type') != 'image_generation_call':
            continue
        result = item.get('result', '')
        if not result or not isinstance(result, str) or not result.startswith('data:'):
            continue

        try:
            # Parse data URI: data:<mime>;base64,<data>
            header, b64_data = result.split(',', 1)
            mime_type = header.replace('data:', '').split(';')[0]

            # Map MIME type to file extension
            _MIME_EXT = {
                'image/png': '.png',
                'image/jpeg': '.jpg',
                'image/webp': '.webp',
                'image/gif': '.gif',
            }
            ext = _MIME_EXT.get(mime_type, '.png')

            # Decode base64 and save to storage in a thread to avoid
            # blocking the event loop on CPU-heavy base64 decode and I/O.
            image_key = f"{response_id}_{i}{ext}"

            def _decode_and_save():
                image_bytes = _base64.b64decode(b64_data)
                return storage.write_binary(image_key, image_bytes, mime_type)

            url = await asyncio.to_thread(_decode_and_save)

            # Replace data URI with storage URL
            item['result'] = url
            # Preserve original base64 data and MIME type so that
            # _apply_b64_json_to_image_output can reconstruct the
            # data URI without re-downloading from the storage URL.
            item['_b64_data'] = b64_data
            item['_mime_type'] = mime_type
        except Exception:
            logger.warning(f"Failed to save image {i} data URI to storage", exc_info=True)


def _strip_internal_fields(output: list) -> None:
    """Remove internal-use-only fields from output items before returning."""
    _INTERNAL_FIELDS = frozenset({'_b64_data', '_mime_type'})
    for item in output:
        if isinstance(item, dict):
            for f in _INTERNAL_FIELDS:
                item.pop(f, None)


def _extract_video_erase_metadata(tool_data: dict, file_id_media_map: dict) -> dict:
    """Extract video_erase tool params → metadata dict."""
    meta = {'_video_erase': True}

    template_id = tool_data.get('template_id')
    if template_id is not None:
        meta['template_id'] = template_id
    model = tool_data.get('model')
    if model:
        meta['erase_model'] = model
    erase_type = tool_data.get('erase_type')
    if erase_type:
        meta['erase_type'] = erase_type
    erase_method = tool_data.get('erase_method')
    if erase_method:
        meta['erase_method'] = erase_method
    area = tool_data.get('area')
    if area:
        meta['area'] = area

    if file_id_media_map:
        meta['file_id_media_map'] = file_id_media_map

    return meta


def _extract_3d_gen_metadata(tool_data: dict) -> dict:
    """Extract 3d_generation tool params → metadata dict."""
    meta = {'_3d_generation': True}

    pbr = tool_data.get('pbr')
    if pbr is None:
        pbr = tool_data.get('enable_pbr')
    if pbr is not None:
        meta['enable_pbr'] = bool(pbr)
        meta['pbr'] = bool(pbr)

    output_format = tool_data.get('output_format') or tool_data.get('result_format')
    if output_format:
        meta['output_format'] = output_format
        meta['result_format'] = output_format

    enable_geometry = tool_data.get('enable_geometry')
    if enable_geometry is None:
        enable_geometry = tool_data.get('geometry')
    if enable_geometry is not None:
        meta['enable_geometry'] = bool(enable_geometry)

    face_count = tool_data.get('face_count')
    if face_count is not None:
        meta['face_count'] = int(face_count)
    generate_type = tool_data.get('generate_type')
    if generate_type:
        meta['generate_type'] = generate_type
    polygon_type = tool_data.get('polygon_type')
    if polygon_type:
        meta['polygon_type'] = polygon_type

    return meta


class OpenAIResponsesAdapter(BaseAdapter):
    API_TYPE = "responses"  # Maps to model.api_type for access control
    """
    OpenAI Responses API 适配器

    负责：
    - 将 OpenAI /v1/responses 请求格式解析为 ChatRequest
    - 将 ChatResponse 转换为 OpenAI Responses 格式
    - 处理 OpenAI Responses 格式的流式响应
    """

    # ── Item dispatcher for mixed-format input arrays ──────────────────
    # Value: (handler, needs_item_type) — generation_call handlers need
    # the item_type string to derive the correct tool name.
    _INPUT_DISPATCH = {
        'function_call':          (_handle_function_call_item, False),
        'image_generation_call':  (_handle_generation_call_item, True),
        'video_generation_call':  (_handle_generation_call_item, True),
        'video_erase_call':       (_handle_generation_call_item, True),
        '3d_generation_call':     (_handle_generation_call_item, True),
        'function_call_output':   (_handle_function_call_output_item, False),
        'reasoning':              (_handle_reasoning_item, False),
    }

    # Set of item types that are dispatched via _INPUT_DISPATCH (not plain content blocks)
    _SPECIAL_INPUT_TYPES = frozenset(_INPUT_DISPATCH.keys())

    def _build_file_id_media_map(self, data: dict) -> dict:
        """Scan all media input blocks and collect file_id → {type, url, role} mappings.

        Supports image/video/audio blocks inside role-based messages' content arrays,
        plus top-level plain blocks with media roles (first_frame, reference_image, …).
        """
        file_map: dict = {}
        _MEDIA_ROLES = {'first_frame', 'last_frame', 'reference_image',
                        'reference_video', 'reference_audio', ''}

        for item in _safe_list(data.get('input')):
            if not isinstance(item, dict):
                continue

            # 1. Content blocks nested inside role-based messages
            for blk in _safe_list(item.get('content')):
                if isinstance(blk, dict):
                    _register_fid_media(file_map, blk)

            # 2. Top-level plain media blocks (role is a media role or absent)
            top_type = item.get('type', '')
            top_fid = item.get('file_id', '')
            top_role = item.get('role', '')
            if top_fid and top_role in _MEDIA_ROLES and top_type:
                _register_fid_media(file_map, {**item, 'type': top_type, 'file_id': top_fid, 'role': top_role})

        return file_map

    def _parse_tools(self, data: dict, file_id_media_map: dict):
        """Parse the 'tools' array → (ToolDefinition list, accumulated metadata dict)."""
        tools = []
        img_meta: dict = {}
        vid_meta: dict = {}
        erase_meta: dict = {}

        for tool_data in _safe_list(data.get('tools')):
            ttype = tool_data.get('type', 'function')

            if ttype == 'function':
                tools.append(_parse_function_tool_def(tool_data))
            elif ttype == 'web_search_preview':
                pass  # pass through as metadata
            elif ttype == 'video_erase':
                erase_meta.update(_extract_video_erase_metadata(tool_data, file_id_media_map))
            elif ttype == 'video_generation':
                vid_meta.update(_extract_video_gen_metadata(tool_data, file_id_media_map))
            elif ttype == 'image_generation':
                img_meta.update(_extract_image_gen_metadata(tool_data))
            elif ttype == '3d_generation':
                vid_meta.update(_extract_3d_gen_metadata(tool_data))

        return tools, img_meta, vid_meta, erase_meta

    @staticmethod
    def _resolve_reasoning_effort(data: dict) -> Optional[str]:
        """Parse the 'reasoning' field → Optional[str] reasoning_effort."""
        reasoning = data.get('reasoning')
        if not reasoning:
            return None
        if isinstance(reasoning, dict):
            effort = reasoning.get('effort')
        elif isinstance(reasoning, str):
            effort = reasoning
        else:
            return None

        # Auto-enable if model name contains "thinking" and no explicit effort set
        if not effort:
            model_name = data.get('model', '')
            if 'thinking' in model_name.lower():
                effort = REASONING_EFFORT_DEFAULT_FOR_THINKING

        return effort

    @staticmethod
    def _collect_metadata(data: dict, reasoning: Optional[dict],
                          img_meta: dict, vid_meta: dict,
                          erase_meta: Optional[dict] = None) -> dict:
        """Collect extra parameters and merge tool metadata into ChatRequest.metadata."""
        _KNOWN = {
            'model', 'input', 'instructions', 'temperature', 'top_p',
            'max_output_tokens', 'stream', 'tools', 'tool_choice',
            'stop', 'presence_penalty', 'frequency_penalty', 'user',
            'metadata', 'store', 'truncation', 'reasoning',
            'n', 'seed',
        }
        metadata = {k: v for k, v in data.items() if k not in _KNOWN}

        if reasoning and isinstance(reasoning, dict):
            metadata['reasoning'] = reasoning
        if img_meta:
            metadata.update(img_meta)
        if vid_meta:
            metadata.update(vid_meta)
        if erase_meta:
            metadata.update(erase_meta)

        return metadata

    # ───────────────────────────────────────────────────────────────────
    #  Input message building  (used by parse_request)
    # ───────────────────────────────────────────────────────────────────

    @classmethod
    def _all_content_blocks(cls, items: list) -> bool:
        """Return True if every item is a plain content block (no role, no dispatch type)."""
        return all(isinstance(it, dict) and 'role' not in it and 'type' in it
                   and it.get('type') not in cls._SPECIAL_INPUT_TYPES
                   for it in items)

    def _dispatch_input_item(self, item: dict, messages: list):
        """Route a single input dict to the correct handler via _INPUT_DISPATCH."""
        item_type = item.get('type', '')
        handler_info = self._INPUT_DISPATCH.get(item_type)
        if handler_info:
            handler, pass_type = handler_info
            if pass_type:
                handler(item, messages, item_type)
            else:
                handler(item, messages)
        elif 'role' in item:
            _handle_role_message_item(item, messages)

    def _build_messages_from_input(self, data: dict):
        """Convert the Responses-API 'instructions' + 'input' fields → (system, messages).

        - ``instructions`` → ``system`` (pass-through, can be str or list of content blocks)
        - ``role=system`` in input → merged into ``system``
        - ``role=developer`` in input → ``Message(role=DEVELOPER)`` in messages
        - Everything else → dispatched as usual

        Returns ``(system, messages: List[Message])`` where *system* is
        ``None | str | List[Dict[str, Any]]``.
        """
        messages = []

        # System value from instructions (pass-through, may be str or list)
        system_val = data.get('instructions')

        input_data = data.get('input', '')
        if isinstance(input_data, str):
            return (system_val,
                    [Message(role=MessageRole.USER, content=input_data)])

        if not isinstance(input_data, list):
            return (system_val, messages)

        if self._all_content_blocks(input_data):
            blocks = _parse_content_blocks(input_data)
            if blocks:
                messages.append(Message(role=MessageRole.USER, content=blocks))
            return (system_val, messages)

        # Mixed format
        for item in input_data:
            if isinstance(item, str):
                messages.append(Message(role=MessageRole.USER, content=item))
            elif isinstance(item, dict):
                # Intercept only role=system (same concept as instructions)
                if item.get('role') == 'system':
                    content = item.get('content', '')
                    if isinstance(content, list):
                        texts = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
                        content = ' '.join(texts) if texts else ''
                    if content:
                        if system_val is None:
                            system_val = content
                        elif isinstance(system_val, str):
                            system_val = system_val + '\n\n' + content
                        else:
                            system_val = list(system_val) + [{'type': 'text', 'text': content}]
                else:
                    self._dispatch_input_item(item, messages)

        return (system_val, messages)

    # ───────────────────────────────────────────────────────────────────
    #  parse_request  —  6-step orchestration
    # ───────────────────────────────────────────────────────────────────

    def parse_request(self, data: dict) -> ChatRequest:
        """Parse an OpenAI Responses-API request → ChatRequest.

        请求格式:
        {
            "model": "gpt-4o",
            "input": "Tell me a joke",
            "input": [{"role": "user", "content": "..."}],
            "instructions": "You are a helpful assistant.",
            "temperature": 0.7, "max_output_tokens": 1000,
            "stream": false, "tools": [...]
        }
        """
        # 1. Build messages from instructions + input
        system, messages = self._build_messages_from_input(data)

        # 2. Build file_id → media map
        file_id_media_map = self._build_file_id_media_map(data)

        # 3. Parse tools
        tools, img_meta, vid_meta, erase_meta = self._parse_tools(data, file_id_media_map)

        # 4. Resolve reasoning effort
        reasoning_effort = self._resolve_reasoning_effort(data)

        # 5. Collect metadata (extra params + tool metadata)
        metadata = self._collect_metadata(
            data, data.get('reasoning'), img_meta, vid_meta, erase_meta)

        # 5.5. Capture parallel_tool_calls and user-facing metadata
        parallel_tool_calls = data.get('parallel_tool_calls')
        if parallel_tool_calls is not None:
            parallel_tool_calls = bool(parallel_tool_calls)
        user_metadata = data.get('metadata')
        if user_metadata is not None and isinstance(user_metadata, dict):
            metadata['_user_metadata'] = user_metadata

        # 6. Assemble ChatRequest
        return ChatRequest(
            messages=messages,
            model=data.get('model', ''),
            system=system,
            temperature=data.get('temperature'),
            top_p=data.get('top_p'),
            max_tokens=data.get('max_output_tokens'),
            stream=data.get('stream', False),
            tools=tools,
            tool_choice=data.get('tool_choice'),
            stop=data.get('stop'),
            presence_penalty=data.get('presence_penalty'),
            frequency_penalty=data.get('frequency_penalty'),
            user=data.get('user'),
            session_id=data.get('session_id'),
            reasoning_effort=reasoning_effort,
            parallel_tool_calls=parallel_tool_calls,
            n=data.get('n'),
            seed=data.get('seed'),
            metadata=metadata,
        )

    def format_response(self, response: ChatResponse,
                        parallel_tool_calls: Optional[bool] = None,
                        metadata: Optional[dict] = None,
                        response_id: Optional[str] = None) -> dict:
        """
        将 ChatResponse 转换为 OpenAI Responses API 格式。

        响应格式:
        {
            "id": "resp_xxx",
            "object": "response",
            "created_at": 1234567890,
            "model": "gpt-4o",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_xxx",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "Hello!"}
                    ]
                }
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30
            }
        }
        """
        output = []

        # ── Detect generation type by model name ──────────────────────────
        # Rather than relying on response.id prefix conventions, inspect the
        # model name to decide how to render the output.
        model_lower = (response.model or "").lower()

        # Image generation models:
        #   Bailian:          qwen-image-*, z-image-turbo
        #   Volcengine:       *seedream*
        #   Gemini/VertexAI:  imagen*, *image-generation*, *native-image*,
        #                     gemini-*-image* (e.g. gemini-2.5-flash-image,
        #                     gemini-3-pro-image-preview, gemini-3.1-flash-image-preview)
        #   TencentVOD:       gem-*, mingmou-*, hy-image-*, gpt-image-*
        #   Other:            *flux*, *nanobanana*
        is_image_generation = (
            "qwen-image" in model_lower or
            model_lower == "z-image-turbo" or
            "seedream" in model_lower or
            "imagen" in model_lower or
            "image-generation" in model_lower or
            "native-image" in model_lower or
            (model_lower.startswith("gemini-") and "image" in model_lower) or
            model_lower.startswith("gem-") or
            model_lower.startswith("mingmou-") or
            model_lower.startswith("hy-image-") or
            model_lower.startswith("gpt-image-") or
            "flux" in model_lower or
            "nanobanana" in model_lower or
            getattr(response, 'provider', '') == "volcengine_image"
        )

        # Video generation models:
        #   Bailian:       happyhorse-*
        #   Volcengine:    *seedance*
        #   Gemini/Vertex: veo*
        #   TencentVOD:    kling-*, vidu*, pixverse-*, gv-*, hy-video-*
        is_video_generation = (
            model_lower.startswith("happyhorse") or
            "seedance" in model_lower or
            model_lower.startswith("veo") or
            model_lower.startswith("kling-") or
            model_lower.startswith("vidu") or
            model_lower.startswith("pixverse-") or
            model_lower.startswith("gv-") or
            model_lower.startswith("hy-video-") or 
            model_lower.startswith("mps-")
        )

        # 3D generation models: hunyuan-3d* / hy-3d* (Tencent), *seed3d* (Volcengine)
        is_3d_generation = (
            model_lower.startswith("hunyuan-3d") or
            model_lower.startswith("hy-3d") or
            "seed3d" in model_lower
        )

        if is_3d_generation:
            # The message content is a JSON list of 3d_generation_call items stored by
            # execute_hunyuan3d_generation() in the provider. Each item has:
            # {
            #   "type": "3d_generation_call",
            #   "id": "<job_id>",
            #   "status": "completed",
            #   "content": [{"type": "OBJ", "url": "...", "preview_url": "..."}]
            # }
            items = []
            if response.choices and response.choices[0].message:
                msg = response.choices[0].message
                content = msg.content
                if isinstance(content, str):
                    raw = content
                elif hasattr(msg, 'get_text_content'):
                    raw = msg.get_text_content() or "[]"
                else:
                    raw = "[]"
                try:
                    items = json_loads(raw) if isinstance(raw, str) else []
                except (json.JSONDecodeError, TypeError):
                    items = []

            for i, item in enumerate(items):
                if isinstance(item, dict):
                    call_id = item.get("id", f"{response.id}-{i}" if i > 0 else response.id)
                    status = item.get("status", "completed")
                    content_list = item.get("content", [])
                else:
                    call_id = f"{response.id}-{i}" if i > 0 else response.id
                    status = "completed"
                    content_list = []
                output.append({
                    "type": "3d_generation_call",
                    "id": call_id,
                    "status": status,
                    "content": content_list,
                })

        elif is_video_generation:
            # The message content is a JSON list of video_generation_call items stored by
            # execute_tencentvod_video_generation() in the provider.  Each item has:
            #   {"type": "video_generation_call", "status": "completed", "result": "<url>"}
            items = []
            if response.choices and response.choices[0].message:
                msg = response.choices[0].message
                content = msg.content
                if isinstance(content, str):
                    raw = content
                elif hasattr(msg, 'get_text_content'):
                    raw = msg.get_text_content() or "[]"
                else:
                    raw = "[]"
                try:
                    items = json_loads(raw) if isinstance(raw, str) else []
                except (json.JSONDecodeError, TypeError):
                    items = []

            for i, item in enumerate(items):
                # Prefer item's own id (set by provider, e.g. gen_id("vid")).
                # Fall back to deriving from the enclosing response id.
                default_id = f"{response.id}-{i}" if i > 0 else response.id
                call_id = item.get("id", default_id) if isinstance(item, dict) else default_id
                if isinstance(item, dict):
                    status = item.get("status", "completed")
                    result = item.get("result", "")
                    item_type = item.get("type", "video_generation_call")
                else:
                    status = "completed"
                    result = str(item)
                    item_type = "video_generation_call"
                output.append({
                    "type": item_type,
                    "id": call_id,
                    "status": status,
                    "result": result,
                })

        elif is_image_generation:
            # The message content is a JSON list of image_generation_call items stored by
            # execute_image_generation() in the provider.  Each item has:
            #   {"type": "image_generation_call", "status": "completed", "result": "<url|b64>"}
            items = []
            if response.choices and response.choices[0].message:
                msg = response.choices[0].message
                # message.content is set to a plain JSON string by execute_image_generation().
                # Read it directly if it's already a string; fall back to get_text_content()
                # if the content was converted to a list of ContentBlock objects.
                content = msg.content
                if isinstance(content, str):
                    raw = content
                elif hasattr(msg, 'get_text_content'):
                    raw = msg.get_text_content() or "[]"
                else:
                    raw = "[]"
                try:
                    items = json_loads(raw) if isinstance(raw, str) else []
                except (json.JSONDecodeError, TypeError):
                    items = []

            for i, item in enumerate(items):
                call_id = f"{response.id}-{i}" if i > 0 else response.id
                if isinstance(item, dict):
                    status = item.get("status", "completed")
                    result = item.get("result", "")
                else:
                    # Fallback: item is a raw string (URL or base64)
                    status = "completed"
                    result = str(item)
                output.append({
                    "type": "image_generation_call",
                    "id": call_id,
                    "status": status,
                    "result": result,
                })
        else:
            for choice in response.choices:
                # Include reasoning output item with summary_text if available
                if choice.reasoning_content:
                    output.append({
                        'type': 'reasoning',
                    'id': _gen_id("rs"),
                    'summary': [
                        {
                            'type': 'summary_text',
                            'text': choice.reasoning_content
                        }
                    ]
                    })

                if choice.message:
                    content_items = []
                    text = choice.message.get_text_content()

                    if text:
                        content_items.append({
                            'type': 'output_text',
                            'text': text,
                            'annotations': []
                        })

                    if choice.tool_calls:
                        for tc in choice.tool_calls:
                            output.append({
                                'type': 'function_call',
                                'id': tc.id,
                                'call_id': tc.id,
                                'name': tc.name,
                                'arguments': json.dumps(tc.arguments, ensure_ascii=False),
                                'status': 'completed'
                            })

                    if content_items:
                        output.append({
                            'type': 'message',
                            'id': _gen_id("msg"),
                            'role': 'assistant',
                            'status': 'completed',
                            'content': content_items
                        })

        # Map finish_reason to status
        status = 'completed'
        if response.choices:
            fr = response.choices[0].finish_reason.value
            status_map = {
                'stop': 'completed',
                'length': 'incomplete',
                'tool_calls': 'completed',
                'content_filter': 'failed',
            }
            status = status_map.get(fr, 'completed')

        usage_dict: dict = {
            'input_tokens': response.usage.prompt_tokens,
            'output_tokens': response.usage.completion_tokens,
            'total_tokens': response.usage.total_tokens,
        }
        # Include detailed token breakdowns when available
        input_details: dict = {}
        if response.usage.cached_tokens:
            input_details['cached_tokens'] = response.usage.cached_tokens
        if input_details:
            usage_dict['input_tokens_details'] = input_details

        output_details: dict = {}
        if response.usage.reasoning_tokens:
            output_details['reasoning_tokens'] = response.usage.reasoning_tokens
        if output_details:
            usage_dict['output_tokens_details'] = output_details

        # Include price information if available
        if response.usage.price is not None:
            usage_dict['price'] = response.usage.price.to_dict()

        # Always include the requested format in the response so that upper
        # layers (sync return / async GET polling) can decide whether to
        # convert image URLs to base64 data URIs.
        result = {
            'id': response_id or (response.id.replace('chatcmpl-', 'resp_') if response.id.startswith('chatcmpl-') else response.id),
            'object': 'response',
            'created_at': response.created,
            'model': response.model,
            'status': status,
            'output': output,
            'usage': usage_dict,
        }
        result['parallel_tool_calls'] = bool(parallel_tool_calls)
        result['metadata'] = metadata if isinstance(metadata, dict) else None
        if is_image_generation:
            result['response_format'] = response.usage.extra.get('_response_format', 'b64_json')
        return result

    def format_stream_chunk(self, chunk: StreamChunk) -> str:
        """
        将 StreamChunk 转换为 OpenAI Responses 流式事件格式。

        事件类型:
        - response.output_text.delta: 文本增量
        - response.function_call_arguments.delta: 工具调用参数增量
        - response.output_text.done / response.content_part.done / response.output_item.done:
            finish chunk with full text (emitted before response.completed)
        - response.completed: 完成事件

        Convention: when a chunk carries both `finish_reason` and `delta_content`, the
        `delta_content` contains the FULL assembled text (not a new delta). In this case
        we emit the three "done" closure events instead of a delta event.
        """
        events = []
        msg_id = getattr(self, '_stream_msg_id', None)

        # IMPORTANT: Process tool_calls BEFORE finish_reason
        # so that function_call events are emitted before response.completed
        
        if chunk.tool_calls:
            # Track the current call_id for deltas that don't carry an id
            # (Azure sends id only on the first chunk of each tool call)
            if not hasattr(self, '_stream_current_tc_call_id'):
                self._stream_current_tc_call_id = None
            # Track index → call_id mapping for providers that use index-based deltas
            if not hasattr(self, '_stream_tc_index_to_call_id'):
                self._stream_tc_index_to_call_id = {}

            for tc in chunk.tool_calls:
                call_id = tc.get('id', '')
                tc_index = tc.get('index')
                func = tc.get('function', {})
                name = func.get('name', '')
                args = func.get('arguments', '')

                if call_id:
                    # New function call start — emit response.output_item.added
                    self._stream_current_tc_call_id = call_id
                    output_index = getattr(self, '_stream_output_index', 0)
                    self._stream_output_index = output_index + 1
                    # Track call_id → output_index for arguments.delta events
                    if not hasattr(self, '_stream_tool_output_indices'):
                        self._stream_tool_output_indices = {}
                    self._stream_tool_output_indices[call_id] = output_index
                    # Track index → call_id for providers that use index-based deltas
                    if tc_index is not None:
                        self._stream_tc_index_to_call_id[tc_index] = call_id
                    
                    # Store function call info for later use in response.output_item.done
                    if not hasattr(self, '_stream_tool_calls'):
                        self._stream_tool_calls = []
                    fc_id = _gen_id("fc")
                    self._stream_tool_calls.append({
                        'id': fc_id,
                        'call_id': call_id,
                        'name': name,
                        'arguments': '',  # will be accumulated
                        'output_index': output_index,
                        'done': False  # track whether done events have been emitted
                    })

                    item_added = {
                        'type': 'response.output_item.added',
                        'output_index': output_index,
                        'item': {
                            'id': fc_id,
                            'type': 'function_call',
                            'status': 'in_progress',
                            'arguments': '',
                            'call_id': call_id,
                            'name': name
                        }
                    }
                    events.append(f"event: response.output_item.added\ndata: {json.dumps(item_added, ensure_ascii=False)}\n\n")

                # For deltas without call_id, resolve via index → call_id mapping,
                # then fall back to the last known call_id
                effective_call_id = call_id
                if not effective_call_id and tc_index is not None:
                    effective_call_id = self._stream_tc_index_to_call_id.get(tc_index, '')
                if not effective_call_id:
                    effective_call_id = self._stream_current_tc_call_id or ''

                if args:
                    # Accumulate arguments in _stream_tool_calls entry
                    tool_calls_list = getattr(self, '_stream_tool_calls', [])
                    for fc_info in tool_calls_list:
                        if fc_info['call_id'] == effective_call_id:
                            fc_info['arguments'] += args
                            break

                    # Determine output_index for this arguments delta
                    tool_indices = getattr(self, '_stream_tool_output_indices', {})
                    tc_output_index = tool_indices.get(effective_call_id, 0) if effective_call_id else (max(tool_indices.values()) if tool_indices else 0)
                    event_data = {
                        'type': 'response.function_call_arguments.delta',
                        'output_index': tc_output_index,
                        'delta': args
                    }
                    events.append(f"event: response.function_call_arguments.delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n")
                    
                    # Check if the ACCUMULATED arguments form complete JSON.
                    # For providers like Gemini that send all args in one chunk, this
                    # triggers immediately. For Azure/OpenAI (incremental deltas), it
                    # triggers only when the full JSON is assembled.
                    for fc_info in tool_calls_list:
                        if fc_info['call_id'] == effective_call_id and not fc_info['done']:
                            try:
                                json.loads(fc_info['arguments'])
                                # Complete JSON — emit done events now
                                fc_info['done'] = True
                                fc_name = fc_info['name'] or name
                                args_done = {
                                    'type': 'response.function_call_arguments.done',
                                    'output_index': fc_info['output_index'],
                                    'arguments': fc_info['arguments']
                                }
                                events.append(f"event: response.function_call_arguments.done\ndata: {json.dumps(args_done, ensure_ascii=False)}\n\n")
                                
                                item_done = {
                                    'type': 'response.output_item.done',
                                    'output_index': fc_info['output_index'],
                                    'item': {
                                        'id': fc_info['id'],
                                        'type': 'function_call',
                                        'status': 'completed',
                                        'arguments': fc_info['arguments'],
                                        'call_id': effective_call_id,
                                        'name': fc_name
                                    }
                                }
                                events.append(f"event: response.output_item.done\ndata: {json.dumps(item_done, ensure_ascii=False)}\n\n")
                            except (json.JSONDecodeError, TypeError):
                                pass
                            break

        if chunk.finish_reason and chunk.delta_content is not None:
            # Full-text finish chunk
            full_text = chunk.delta_content or ""
            resp_id = chunk.id.replace('chatcmpl-', 'resp_') if chunk.id.startswith('chatcmpl-') else chunk.id

            # Close any tool calls that haven't emitted done events yet.
            # This handles cases where the accumulated args form valid JSON but
            # the done events weren't emitted during delta processing (e.g. edge cases).
            tool_calls_list = getattr(self, '_stream_tool_calls', [])
            for fc_info in tool_calls_list:
                if not fc_info['done'] and fc_info['arguments']:
                    fc_info['done'] = True
                    args_done = {
                        'type': 'response.function_call_arguments.done',
                        'output_index': fc_info['output_index'],
                        'arguments': fc_info['arguments']
                    }
                    events.append(f"event: response.function_call_arguments.done\ndata: {json.dumps(args_done, ensure_ascii=False)}\n\n")
                    item_done = {
                        'type': 'response.output_item.done',
                        'output_index': fc_info['output_index'],
                        'item': {
                            'id': fc_info['id'],
                            'type': 'function_call',
                            'status': 'completed',
                            'arguments': fc_info['arguments'],
                            'call_id': fc_info['call_id'],
                            'name': fc_info['name']
                        }
                    }
                    events.append(f"event: response.output_item.done\ndata: {json.dumps(item_done, ensure_ascii=False)}\n\n")

            # Only emit text/content_part/message done events if there was actual
            # text content AND it hasn't already been closed (e.g. by a tool_calls
            # transition). For function-call-only responses we skip these.
            has_text = (
                getattr(self, '_stream_text_started', False)
                and not getattr(self, '_stream_text_closed', False)
            )
            had_text = getattr(self, '_stream_text_started', False)
            has_tool_calls = bool(getattr(self, '_stream_tool_calls', []))
            text_output_index = getattr(self, '_stream_text_output_index', 0)
            if has_text:
                # 1. response.output_text.done
                text_done: dict = {
                    'type': 'response.output_text.done',
                    'output_index': text_output_index,
                    'content_index': 0,
                    'text': full_text
                }
                if msg_id:
                    text_done['item_id'] = msg_id
                events.append(f"event: response.output_text.done\ndata: {json.dumps(text_done, ensure_ascii=False)}\n\n")

                # 2. response.content_part.done
                part_done: dict = {
                    'type': 'response.content_part.done',
                    'output_index': text_output_index,
                    'content_index': 0,
                    'part': {
                        'type': 'output_text',
                        'text': full_text,
                        'annotations': []
                    }
                }
                if msg_id:
                    part_done['item_id'] = msg_id
                events.append(f"event: response.content_part.done\ndata: {json.dumps(part_done, ensure_ascii=False)}\n\n")

                # 3. response.output_item.done (message)
                item_done: dict = {
                    'type': 'response.output_item.done',
                    'output_index': text_output_index,
                    'item': {
                        'type': 'message',
                        'id': msg_id or '',
                        'role': 'assistant',
                        'status': 'completed',
                        'content': [{'type': 'output_text', 'text': full_text, 'annotations': []}]
                    }
                }
                events.append(f"event: response.output_item.done\ndata: {json.dumps(item_done, ensure_ascii=False)}\n\n")

            # 4. response.completed — only emit once.
            # When there are tool calls (function-call-only response), defer completed
            # to the end of the stream (in generate() loop) so that ALL tool call events
            # from all chunks are emitted before completed. This handles providers like
            # Gemini that may send multiple chunks each with separate function calls.
            if has_tool_calls and not had_text:
                # Defer completed — it will be emitted at the end of generate()
                # Store usage info for the deferred completed event
                self._stream_deferred_usage = chunk.usage
                self._stream_deferred_resp_id = resp_id
                self._stream_deferred_model = chunk.model
            elif not getattr(self, '_stream_completed_emitted', False):
                self._stream_completed_emitted = True
                # Use the full Azure response object verbatim when available; otherwise build a
                # complete response object that includes the full output text and usage info.
                azure_resp = chunk.usage.extra.get('_azure_completed_response') if chunk.usage else None
                if azure_resp:
                    completed_resp = azure_resp
                else:
                    # Build output array with full message text so clients receive a complete
                    # response object (mirroring what a non-streaming response would return).
                    output_items = []

                    # Include reasoning output item if accumulated during the stream
                    stream_reasoning = getattr(self, '_stream_full_reasoning', '')
                    if stream_reasoning:
                        rs_id = getattr(self, '_stream_reasoning_id', _gen_id("rs"))
                        output_items.append({
                            'type': 'reasoning',
                            'id': rs_id,
                            'summary': [{
                                'type': 'summary_text',
                                'text': stream_reasoning
                            }]
                        })

                    # Include message first (output_index=1), then function_calls
                    # (output_index=2+), matching the streaming event order.
                    if had_text:
                        output_content = [{'type': 'output_text', 'text': full_text, 'annotations': []}]
                        output_items.append({
                            'type': 'message',
                            'id': msg_id or _gen_id("msg"),
                            'role': 'assistant',
                            'status': 'completed',
                            'content': output_content
                        })

                    tool_calls_list = getattr(self, '_stream_tool_calls', [])
                    for fc_info in tool_calls_list:
                        output_items.append({
                            'type': 'function_call',
                            'id': fc_info['id'],
                            'call_id': fc_info['call_id'],
                            'name': fc_info['name'],
                            'arguments': fc_info['arguments'],
                            'status': 'completed'
                        })
                    completed_resp = {
                        'id': resp_id,
                        'object': 'response',
                        'status': 'completed',
                        'model': chunk.model,
                        'output': output_items,
                    }
                    if chunk.usage:
                        usage_out: dict = {
                            'input_tokens': chunk.usage.prompt_tokens,
                            'output_tokens': chunk.usage.completion_tokens,
                            'total_tokens': chunk.usage.total_tokens,
                        }
                        if chunk.usage.cached_tokens:
                            usage_out['input_tokens_details'] = {'cached_tokens': chunk.usage.cached_tokens}
                        if chunk.usage.reasoning_tokens:
                            usage_out['output_tokens_details'] = {'reasoning_tokens': chunk.usage.reasoning_tokens}
                        if chunk.usage.price is not None:
                            usage_out['price'] = chunk.usage.price.to_dict()
                        completed_resp['usage'] = usage_out
                completed: dict = {
                    'type': 'response.completed',
                    'response': completed_resp
                }
                events.append(f"event: response.completed\ndata: {json.dumps(completed, ensure_ascii=False)}\n\n")

        elif chunk.delta_content:
            # Regular incremental delta — lazily emit text start events on first text
            if not getattr(self, '_stream_text_started', False):
                events.append(self._emit_text_start_events())
            text_oi = getattr(self, '_stream_text_output_index', 0)
            event_data: dict = {
                'type': 'response.output_text.delta',
                'output_index': text_oi,
                'content_index': 0,
                'delta': chunk.delta_content
            }
            if msg_id:
                event_data['item_id'] = msg_id
            events.append(f"event: response.output_text.delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n")

        elif chunk.finish_reason:
            # finish_reason only (no full text) — emit response.completed directly
            # Only emit once to avoid duplicates
            if not getattr(self, '_stream_completed_emitted', False):
                self._stream_completed_emitted = True
                resp_id = chunk.id.replace('chatcmpl-', 'resp_') if chunk.id.startswith('chatcmpl-') else chunk.id
                
                # Build output array - include function_calls if any were accumulated
                output_items = []
                tool_calls_list = getattr(self, '_stream_tool_calls', [])
                for fc_info in tool_calls_list:
                    output_items.append({
                        'type': 'function_call',
                        'id': fc_info['id'],
                        'call_id': fc_info['call_id'],
                        'name': fc_info['name'],
                        'arguments': fc_info['arguments'],
                        'status': 'completed'
                    })
                
                completed = {
                    'type': 'response.completed',
                    'response': {
                        'id': resp_id,
                        'object': 'response',
                        'status': 'completed',
                        'model': chunk.model,
                        'output': output_items
                    }
                }
                if chunk.usage:
                    usage_out: dict = {
                        'input_tokens': chunk.usage.prompt_tokens,
                        'output_tokens': chunk.usage.completion_tokens,
                        'total_tokens': chunk.usage.total_tokens,
                    }
                    if chunk.usage.price is not None:
                        usage_out['price'] = chunk.usage.price.to_dict()
                    completed['response']['usage'] = usage_out
                events.append(f"event: response.completed\ndata: {json.dumps(completed, ensure_ascii=False)}\n\n")

        # Emit any raw SSE strings that the provider encoded for verbatim passthrough
        # (e.g. Azure reasoning_summary events that have no StreamChunk equivalent).
        if chunk.raw_sse_passthrough:
            events.extend(chunk.raw_sse_passthrough)

        return ''.join(events) if events else ''

    def format_stream_start(self, model_name: str, response_id: Optional[str] = None, msg_id: Optional[str] = None) -> Optional[str]:
        """发送 Responses API 流式开始事件

        Args:
            model_name: 模型名称
            response_id: 可选的响应 ID。若提供则直接使用（e.g. Azure 的真实 resp_xxx ID），
                         否则自动生成一个新的 ID。
            msg_id: 可选的消息 item ID。若提供则直接使用（e.g. Azure 的真实 msg_xxx ID），
                    否则自动生成一个新的 ID。
        """
        if not response_id:
            response_id = _gen_id("resp")
        if not msg_id:
            msg_id = _gen_id("msg")

        now = int(time.time())
        events = []

        # Shared response envelope used in both response.created and response.in_progress
        response_envelope = {
            'id': response_id,
            'object': 'response',
            'created_at': now,
            'model': model_name,
            'status': 'in_progress',
            'output': []
        }

        # response.created
        created_data = {
            'type': 'response.created',
            'response': response_envelope
        }
        events.append(f"event: response.created\ndata: {json.dumps(created_data)}\n\n")

        # response.in_progress
        in_progress_data = {
            'type': 'response.in_progress',
            'response': response_envelope
        }
        events.append(f"event: response.in_progress\ndata: {json.dumps(in_progress_data)}\n\n")

        # NOTE: response.output_item.added (message) and response.content_part.added
        # are NOT emitted here. They are deferred and emitted lazily when the first
        # text content delta arrives. This avoids emitting message/content_part events
        # for function-call-only responses (e.g. Gemini tool calls).
        # The flag _stream_text_started tracks whether these events have been emitted.
        self._stream_text_started = False
        # Track whether response.completed has been emitted to avoid duplicates
        self._stream_completed_emitted = False
        # Initialize output index counter for function call items.
        # Starts at 0 — if text content arrives later, the message item takes index 0
        # and function calls shift accordingly. But for function-call-only responses,
        # the first function call is at index 0.
        self._stream_output_index = 0

        return ''.join(events)

    def _emit_text_start_events(self) -> str:
        """Emit response.output_item.added (message) and response.content_part.added
        events lazily on the first text delta. Returns the SSE string."""
        msg_id = getattr(self, '_stream_msg_id', None) or ''
        events = []

        # Message takes the current output_index (after reasoning if present)
        text_output_index = getattr(self, '_stream_output_index', 0)
        self._stream_text_output_index = text_output_index
        self._stream_output_index = text_output_index + 1

        # response.output_item.added
        item_data = {
            'type': 'response.output_item.added',
            'output_index': text_output_index,
            'item': {
                'type': 'message',
                'id': msg_id,
                'role': 'assistant',
                'status': 'in_progress',
                'content': []
            }
        }
        events.append(f"event: response.output_item.added\ndata: {json.dumps(item_data)}\n\n")

        # response.content_part.added
        part_data = {
            'type': 'response.content_part.added',
            'item_id': msg_id,
            'output_index': text_output_index,
            'content_index': 0,
            'part': {
                'type': 'output_text',
                'text': '',
                'annotations': []
            }
        }
        events.append(f"event: response.content_part.added\ndata: {json.dumps(part_data)}\n\n")

        self._stream_text_started = True
        return ''.join(events)

    def _emit_text_close_events(self, full_text: str) -> str:
        """Emit response.output_text.done / content_part.done / output_item.done
        events to close the text output item BEFORE function_call items begin.
        Required by providers like Bailian that send text content before tool_calls
        in the same stream."""
        msg_id = getattr(self, '_stream_msg_id', None) or ''
        text_output_index = getattr(self, '_stream_text_output_index', 0)
        events = []
        text_str = full_text or ''

        # response.output_text.done
        text_done: dict = {
            'type': 'response.output_text.done',
            'output_index': text_output_index,
            'content_index': 0,
            'text': text_str,
        }
        if msg_id:
            text_done['item_id'] = msg_id
        events.append(f"event: response.output_text.done\ndata: {json.dumps(text_done, ensure_ascii=False)}\n\n")

        # response.content_part.done
        part_done: dict = {
            'type': 'response.content_part.done',
            'output_index': text_output_index,
            'content_index': 0,
            'part': {
                'type': 'output_text',
                'text': text_str,
                'annotations': [],
            },
        }
        if msg_id:
            part_done['item_id'] = msg_id
        events.append(f"event: response.content_part.done\ndata: {json.dumps(part_done, ensure_ascii=False)}\n\n")

        # response.output_item.done (message)
        item_done: dict = {
            'type': 'response.output_item.done',
            'output_index': text_output_index,
            'item': {
                'type': 'message',
                'id': msg_id,
                'role': 'assistant',
                'status': 'completed',
                'content': [{'type': 'output_text', 'text': text_str, 'annotations': []}],
            },
        }
        events.append(f"event: response.output_item.done\ndata: {json.dumps(item_done, ensure_ascii=False)}\n\n")

        self._stream_text_closed = True
        return ''.join(events)

    def create_stream_response(self, chunks, model_name: str):
        """
        Override base implementation to extract the real response ID from the
        first chunk before emitting the `response.created` SSE event.

        When the upstream provider (e.g. Azure Responses API) yields a role-only
        marker chunk whose ID is the real `resp_xxx` assigned by Azure, we:
          1. Capture that ID and use it in `format_stream_start`.
          2. Drop the role-only marker chunk (it carries no content to send).
          3. Process all remaining chunks normally.

        For other providers that do not emit such a marker, the first chunk will
        either have content or be a finish chunk, and we simply fall back to
        generating a random ID in `format_stream_start`.

        Error handling: we eagerly consume the first chunk *before* committing to
        an SSE stream.  Most provider errors (authentication, invalid parameters,
        unsupported models, etc.) surface on the very first iteration of the
        upstream generator.  By catching them here we return a proper JSON error
        response with ``content-type: application/json`` instead of an SSE event.
        """
        from quart import Response
        from app.middleware.gateway_service import GatewayServiceError, ProviderError

        def _is_marker_chunk(chunk: StreamChunk) -> bool:
            """Return True if this chunk is a role-only marker carrying an ID."""
            return bool(
                chunk.delta_role
                and not chunk.delta_content
                and not chunk.delta_reasoning_content
                and not chunk.finish_reason
                and not chunk.tool_calls
                and not chunk.raw_sse_passthrough
            )

        async def generate():
            try:
                real_response_id = None
                real_msg_id = None
                buffered_chunk = None

                ait = chunks.__aiter__()

                # Eagerly consume the first chunk to surface provider errors early.
                try:
                    chunk = await ait.__anext__()
                except StopAsyncIteration:
                    chunk = None

                # Consume all leading marker chunks before emitting the start event.
                # Markers are role-only chunks with no content/finish/tool_calls:
                #   delta_role == "assistant"   → carries the real resp_xxx response ID
                #   delta_role.startswith("msg_") → carries the real msg_xxx message ID
                # We keep consuming until we see the first non-marker (real content) chunk.
                while chunk is not None:
                    if not _is_marker_chunk(chunk):
                        # Real content chunk — buffer it for after the start event
                        buffered_chunk = chunk
                        break

                    role_val = chunk.delta_role
                    if role_val == "assistant":
                        real_response_id = chunk.id if chunk.id else None
                    elif role_val and role_val.startswith("msg_"):
                        real_msg_id = role_val

                    try:
                        chunk = await ait.__anext__()
                    except StopAsyncIteration:
                        chunk = None
                        break

                # Ensure we always have a concrete msg_id before emitting the start event.
                # For non-Azure providers (e.g. Bailian) no marker chunks carry a msg_id, so
                # we generate one here and store it on the adapter so that format_stream_chunk
                # can include item_id in every response.output_text.delta event.
                if not real_msg_id:
                    real_msg_id = _gen_id("msg")
                self._stream_msg_id = real_msg_id

                # Emit the start event using captured real IDs (or generated fallbacks)
                start_event = self.format_stream_start(model_name, real_response_id, real_msg_id)
                if start_event:
                    yield start_event

                # ----------------------------------------------------------------
                # Accumulate text and handle finish/usage chunk pairing.
                #
                # Non-Azure providers (e.g. Bailian) emit the finish_reason and
                # the usage as TWO separate consecutive StreamChunks:
                #   1. finish chunk  – finish_reason="stop", no content, no usage
                #   2. usage chunk   – choices=[], usage={...}, no finish_reason
                #
                # The Responses API adapter needs to emit the three "done" closure
                # events (output_text.done / content_part.done / output_item.done)
                # with the FULL assembled text, followed by response.completed
                # containing the usage.  This requires combining the two chunks.
                #
                # Azure already combines them into a single chunk (delta_content =
                # full text, finish_reason set, usage set), so we pass those through
                # unchanged.
                # ----------------------------------------------------------------
                full_text = ""          # accumulated response text
                full_reasoning = ""     # accumulated reasoning text
                reasoning_started = False   # have we emitted reasoning_summary_part.added?
                reasoning_closed = False    # have we emitted reasoning_summary done events?
                finish_chunk = None     # buffered finish chunk waiting for usage

                def _emit_reasoning_start():
                    """Emit response.output_item.added (reasoning) + response.reasoning_summary_part.added."""
                    rs_id = _gen_id("rs")
                    self._stream_reasoning_id = rs_id
                    # Reasoning item takes the current output_index
                    reasoning_output_index = getattr(self, '_stream_output_index', 0)
                    self._stream_reasoning_output_index = reasoning_output_index
                    self._stream_output_index = reasoning_output_index + 1
                    parts = []
                    # 1. response.output_item.added (reasoning)
                    item_data = {
                        'type': 'response.output_item.added',
                        'output_index': reasoning_output_index,
                        'item': {
                            'type': 'reasoning',
                            'id': rs_id,
                            'status': 'in_progress',
                            'summary': []
                        }
                    }
                    parts.append(f"event: response.output_item.added\ndata: {json.dumps(item_data, ensure_ascii=False)}\n\n")
                    # 2. response.reasoning_summary_part.added
                    event_data = {
                        'type': 'response.reasoning_summary_part.added',
                        'item_id': rs_id,
                        'output_index': reasoning_output_index,
                        'summary_index': 0,
                        'part': {
                            'type': 'summary_text',
                            'text': ''
                        }
                    }
                    parts.append(f"event: response.reasoning_summary_part.added\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n")
                    return ''.join(parts)

                def _emit_reasoning_delta(text):
                    """Emit response.reasoning_summary_text.delta event."""
                    rs_id = getattr(self, '_stream_reasoning_id', '')
                    reasoning_output_index = getattr(self, '_stream_reasoning_output_index', 0)
                    event_data = {
                        'type': 'response.reasoning_summary_text.delta',
                        'item_id': rs_id,
                        'output_index': reasoning_output_index,
                        'summary_index': 0,
                        'delta': text
                    }
                    return f"event: response.reasoning_summary_text.delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                def _emit_reasoning_done():
                    """Emit reasoning_summary_text.done + part.done + output_item.done (reasoning)."""
                    rs_id = getattr(self, '_stream_reasoning_id', '')
                    reasoning_output_index = getattr(self, '_stream_reasoning_output_index', 0)
                    parts = []
                    # 1. response.reasoning_summary_text.done
                    text_done = {
                        'type': 'response.reasoning_summary_text.done',
                        'item_id': rs_id,
                        'output_index': reasoning_output_index,
                        'summary_index': 0,
                        'text': full_reasoning
                    }
                    parts.append(f"event: response.reasoning_summary_text.done\ndata: {json.dumps(text_done, ensure_ascii=False)}\n\n")
                    # 2. response.reasoning_summary_part.done
                    part_done = {
                        'type': 'response.reasoning_summary_part.done',
                        'item_id': rs_id,
                        'output_index': reasoning_output_index,
                        'summary_index': 0,
                        'part': {
                            'type': 'summary_text',
                            'text': full_reasoning
                        }
                    }
                    parts.append(f"event: response.reasoning_summary_part.done\ndata: {json.dumps(part_done, ensure_ascii=False)}\n\n")
                    # 3. response.output_item.done (reasoning) with item.summary
                    item_done = {
                        'type': 'response.output_item.done',
                        'output_index': reasoning_output_index,
                        'item': {
                            'type': 'reasoning',
                            'id': rs_id,
                            'status': 'completed',
                            'summary': [{
                                'type': 'summary_text',
                                'text': full_reasoning
                            }]
                        }
                    }
                    parts.append(f"event: response.output_item.done\ndata: {json.dumps(item_done, ensure_ascii=False)}\n\n")
                    return ''.join(parts)

                def _process_chunk(chunk):
                    """
                    Route a single chunk, always using the locally accumulated full_text
                    for the done-event sequence:

                    - Reasoning delta                  → emit reasoning summary events
                    - Incremental text delta           → accumulate text, yield SSE delta
                    - Combined finish+usage (Azure)    → override delta_content with full_text,
                                                         yield done events + response.completed
                    - Finish-only (Bailian/OpenAI)     → accumulate any final content, buffer
                    - Usage-only                       → combine with buffered finish using
                                                         full_text, yield done events + completed
                    - Anything else                    → yield SSE as-is
                    """
                    nonlocal full_text, full_reasoning, reasoning_started, reasoning_closed, finish_chunk
                    import copy
                    parts = []

                    # Handle reasoning_content (e.g. from Bailian qwen models with thinking)
                    if chunk.delta_reasoning_content:
                        if not reasoning_started:
                            parts.append(_emit_reasoning_start())
                            reasoning_started = True
                        parts.append(_emit_reasoning_delta(chunk.delta_reasoning_content))
                        full_reasoning += chunk.delta_reasoning_content

                    # When transitioning from reasoning to text content, close reasoning
                    if chunk.delta_content and reasoning_started and not reasoning_closed:
                        parts.append(_emit_reasoning_done())
                        reasoning_closed = True

                    if chunk.finish_reason and chunk.usage is not None:
                        # Close reasoning if still open
                        if reasoning_started and not reasoning_closed:
                            parts.append(_emit_reasoning_done())
                            reasoning_closed = True
                        # Combined finish+usage chunk (Azure convention or equivalent).
                        # Clear any previously buffered finish_chunk to avoid duplicate emissions
                        finish_chunk = None
                        combined = copy.copy(chunk)
                        combined.delta_content = full_text
                        # Store accumulated reasoning so format_stream_chunk can include it
                        self._stream_full_reasoning = full_reasoning
                        parts.append(self.format_stream_chunk(combined))
                        return ''.join(parts)

                    if chunk.finish_reason:
                        # Close reasoning if still open
                        if reasoning_started and not reasoning_closed:
                            parts.append(_emit_reasoning_done())
                            reasoning_closed = True
                        # Finish-only chunk (Bailian/OpenAI standard): usage arrives later.
                        if chunk.delta_content:
                            full_text += chunk.delta_content
                        finish_chunk = chunk
                        return ''.join(parts)

                    if (chunk.usage and not chunk.finish_reason
                            and not chunk.tool_calls
                            and not chunk.delta_content
                            and not chunk.delta_reasoning_content):
                        # Usage-only chunk (stream_options / incremental_output).
                        # Guard against providers (e.g. Gemini) that include usage in
                        # every SSE chunk — a chunk with content is not usage-only.
                        if finish_chunk is not None:
                            combined = copy.copy(finish_chunk)
                            combined.delta_content = full_text
                            combined.usage = chunk.usage
                            finish_chunk = None
                            # Store accumulated reasoning so format_stream_chunk can include it
                            self._stream_full_reasoning = full_reasoning
                            parts.append(self.format_stream_chunk(combined))
                            return ''.join(parts)
                        return ''.join(parts)

                    # Normal incremental delta (content / tool_calls / etc.)
                    if chunk.delta_content:
                        full_text += chunk.delta_content

                    # When tool_calls arrive while reasoning is still open, close the
                    # reasoning summary BEFORE emitting function_call events. Otherwise
                    # function_call output items are nested inside the reasoning item.
                    if (chunk.tool_calls
                            and reasoning_started
                            and not reasoning_closed):
                        parts.append(_emit_reasoning_done())
                        reasoning_closed = True

                    # When tool_calls arrive while a text output item is still open,
                    # close the text item first so that function_call events are not
                    # nested inside the message item.  Providers like Bailian stream
                    # text content before tool_calls, and some providers (Moonshot,
                    # MiniMax) reject text content interleaved with function calls.
                    if (chunk.tool_calls
                            and getattr(self, '_stream_text_started', False)
                            and not getattr(self, '_stream_text_closed', False)):
                        parts.append(self._emit_text_close_events(full_text))

                    parts.append(self.format_stream_chunk(chunk))
                    return ''.join(parts)

                # Process buffered first chunk (if any)
                if buffered_chunk is not None:
                    sse = _process_chunk(buffered_chunk)
                    if sse:
                        yield sse

                # Process remaining chunks
                async for chunk in ait:
                    sse = _process_chunk(chunk)
                    if sse:
                        yield sse

                # If a finish chunk was buffered but no usage chunk followed (e.g. the
                # upstream didn't send stream_options usage), emit it now with full_text.
                if finish_chunk is not None:
                    finish_chunk.delta_content = full_text
                    sse = self.format_stream_chunk(finish_chunk)
                    if sse:
                        yield sse

                # If response.completed was never emitted (e.g. when all chunks were
                # tool-call-only and completed was deferred), emit it now.
                if not getattr(self, '_stream_completed_emitted', False):
                    self._stream_completed_emitted = True
                    output_items = []

                    # Include reasoning if accumulated
                    stream_reasoning = getattr(self, '_stream_full_reasoning', '') or full_reasoning
                    if stream_reasoning:
                        rs_id = getattr(self, '_stream_reasoning_id', _gen_id("rs"))
                        output_items.append({
                            'type': 'reasoning',
                            'id': rs_id,
                            'summary': [{
                                'type': 'summary_text',
                                'text': stream_reasoning
                            }]
                        })

                    # Include message first (output_index=1), then function_calls
                    # (output_index=2+), matching the streaming event order.
                    if full_text and getattr(self, '_stream_text_started', False):
                        output_items.append({
                            'type': 'message',
                            'id': real_msg_id or _gen_id("msg"),
                            'role': 'assistant',
                            'status': 'completed',
                            'content': [{'type': 'output_text', 'text': full_text, 'annotations': []}]
                        })

                    tool_calls_list = getattr(self, '_stream_tool_calls', [])
                    for fc_info in tool_calls_list:
                        output_items.append({
                            'type': 'function_call',
                            'id': fc_info['id'],
                            'call_id': fc_info['call_id'],
                            'name': fc_info['name'],
                            'arguments': fc_info['arguments'],
                            'status': 'completed'
                        })

                    deferred_resp_id = getattr(self, '_stream_deferred_resp_id', _gen_id("resp"))
                    deferred_model = getattr(self, '_stream_deferred_model', model_name)
                    deferred_usage = getattr(self, '_stream_deferred_usage', None)
                    completed_resp = {
                        'id': deferred_resp_id,
                        'object': 'response',
                        'status': 'completed',
                        'model': deferred_model,
                        'output': output_items,
                    }
                    if deferred_usage:
                        usage_out = {
                            'input_tokens': deferred_usage.prompt_tokens,
                            'output_tokens': deferred_usage.completion_tokens,
                            'total_tokens': deferred_usage.total_tokens,
                        }
                        if deferred_usage.price is not None:
                            usage_out['price'] = deferred_usage.price.to_dict()
                        completed_resp['usage'] = usage_out
                    completed_event = {
                        'type': 'response.completed',
                        'response': completed_resp
                    }
                    yield f"event: response.completed\ndata: {json.dumps(completed_event, ensure_ascii=False)}\n\n"

                yield self.format_stream_end()

            except (GatewayServiceError, ProviderError) as e:
                yield self.format_stream_error(e)
                yield self.format_stream_end()
            except Exception as e:
                yield self.format_stream_error(e)
                yield self.format_stream_end()

        from quart import Response
        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )

    def format_stream_end(self) -> str:
        """Responses API 流式结束标记"""
        return "data: [DONE]\n\n"

    def format_error_response(self, message: str, status_code: int, error_data: dict = None) -> dict:
        """
        Format an error for the Responses API.

        Canonical error_data is built from UpstreamProviderError fields:
            {"type": "...", "message": "...", "request_id": "..."}
        """
        if error_data and isinstance(error_data, dict):
            return {
                'error': {
                    'type': error_data.get('type', 'server_error'),
                    'message': error_data.get('message', message),
                    'code': status_code,
                }
            }
        return {
            'error': {
                'message': message,
                'type': 'server_error',
                'code': status_code,
            }
        }

    def format_stream_error(self, error: Exception) -> str:
        """将错误转换为 Responses API 格式的流式错误事件"""
        from app.middleware.gateway_service import ProviderError

        if isinstance(error, ProviderError) and error.error_data:
            ed = error.error_data
            # Canonical error_data: {"type": "...", "message": "...", "request_id": "..."}
            error_event = {
                'error': {
                    'type': ed.get('type', 'server_error'),
                    'message': ed.get('message', str(error)),
                }
            }
        else:
            error_event = {
                'type': 'server_error',
                'message': str(error)
            }

        return f"event: error\ndata: {json.dumps(error_event)}\n\n"
