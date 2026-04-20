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
import json
import os
import time
import uuid
from typing import Optional

from .base import BaseAdapter
from app.utils import gen_id as _gen_id, REASONING_EFFORT_DEFAULT_FOR_THINKING

from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.messages import Message, MessageRole, ContentBlock
from app.abstraction.tools import ToolDefinition, ToolParameter, ToolType


class OpenAIResponsesAdapter(BaseAdapter):
    """
    OpenAI Responses API 适配器

    负责：
    - 将 OpenAI /v1/responses 请求格式解析为 ChatRequest
    - 将 ChatResponse 转换为 OpenAI Responses 格式
    - 处理 OpenAI Responses 格式的流式响应
    """

    def parse_request(self, data: dict) -> ChatRequest:
        """
        解析 OpenAI Responses 格式的请求。

        请求格式:
        {
            "model": "gpt-4o",
            "input": "Tell me a joke",
            // 或者数组格式:
            "input": [
                {"role": "user", "content": "Tell me a joke"}
            ],
            "instructions": "You are a helpful assistant.",
            "temperature": 0.7,
            "max_output_tokens": 1000,
            "stream": false,
            "tools": [...]
        }
        """
        messages = []

        # 处理 instructions（系统提示）
        if 'instructions' in data:
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content=data['instructions']
            ))

        # 处理 input
        input_data = data.get('input', '')

        if isinstance(input_data, str):
            # 简单字符串输入
            messages.append(Message(
                role=MessageRole.USER,
                content=input_data
            ))
        elif isinstance(input_data, list):
            # 数组格式输入
            # Items can be:
            # 1. Message objects with 'role' field
            # 2. function_call items (assistant tool calls)
            # 3. function_call_output items (tool results)
            # 4. Plain content blocks (no 'role', has 'type' like input_text/input_image)

            # Check if ALL items are plain content blocks (no role, no special types)
            SPECIAL_TYPES = {'function_call', 'function_call_output', 'image_generation_call', 'video_generation_call', '3d_generation_call'}
            is_pure_content_blocks = all(
                isinstance(item, dict)
                and 'role' not in item
                and 'type' in item
                and item.get('type') not in SPECIAL_TYPES
                for item in input_data
            )

            if is_pure_content_blocks:
                # Treat as a single user message with multiple content blocks
                blocks = []
                for block in input_data:
                    block_type = block.get('type', 'input_text')

                    if block_type in ('input_text', 'text'):
                        blocks.append(ContentBlock.from_text(block.get('text', '')))
                    elif block_type in ('input_image', 'image'):
                        if 'image_url' in block:
                            # image_url can be a string or a dict with 'url' key
                            image_url_val = block['image_url']
                            url = image_url_val if isinstance(image_url_val, str) else image_url_val.get('url', '')
                            if url.startswith('data:'):
                                parts = url.split(',')
                                media_type = parts[0].replace('data:', '').replace(';base64', '')
                                data_str = parts[1] if len(parts) > 1 else ''
                                blocks.append(ContentBlock.from_image_base64(data_str, media_type))
                            else:
                                blocks.append(ContentBlock.from_image_url(url))
                        elif 'source' in block:
                            source = block['source']
                            if source.get('type') == 'base64':
                                blocks.append(ContentBlock.from_image_base64(
                                    source.get('data', ''),
                                    source.get('media_type', 'image/jpeg')
                                ))
                            elif source.get('type') == 'url':
                                blocks.append(ContentBlock.from_image_url(source.get('url', '')))
                    elif block_type in ('input_video', 'video'):
                        video_url_val = block.get('video_url', '')
                        if isinstance(video_url_val, dict):
                            video_url_val = video_url_val.get('url', '')
                        if video_url_val:
                            blocks.append(ContentBlock.from_video_url(video_url_val))

                if blocks:
                    messages.append(Message(
                        role=MessageRole.USER,
                        content=blocks
                    ))
            else:
                # Mixed format: messages, function_call, function_call_output items
                for item in input_data:
                    if isinstance(item, str):
                        messages.append(Message(
                            role=MessageRole.USER,
                            content=item
                        ))
                    elif isinstance(item, dict):
                        item_type = item.get('type', '')

                        if item_type == 'function_call':
                            # Assistant tool call item — convert to assistant message with tool_call block
                            args_str = item.get('arguments', '{}')
                            try:
                                args = json.loads(args_str) if isinstance(args_str, str) else args_str
                            except (json.JSONDecodeError, TypeError):
                                args = {}
                            call_id = item.get('call_id') or item.get('id', '')
                            tool_name = item.get('name', '')
                            block = ContentBlock.from_tool_call(call_id, tool_name, args)
                            messages.append(Message(
                                role=MessageRole.ASSISTANT,
                                content=[block]
                            ))

                        elif item_type == 'image_generation_call':
                            # Image generation call item — represents a previously executed
                            # image generation operation in the conversation history.
                            #
                            # Format:
                            # {
                            #   "type": "image_generation_call",
                            #   "id": "<call_id>",
                            #   "status": "in_progress|completed|generating|failed",
                            #   "result": "<image data or description>"
                            # }
                            #
                            # We store this as a tool_call content block on an ASSISTANT message
                            # so that multi-turn conversations that include prior image generation
                            # results are preserved in the message history passed to the provider.
                            call_id = item.get('id', '')
                            status = item.get('status', 'completed')
                            result = item.get('result', '')

                            # Represent as a tool call from the assistant (the generation request)
                            block = ContentBlock.from_tool_call(
                                call_id,
                                'image_generation',
                                {'status': status, 'result': result}
                            )
                            messages.append(Message(
                                role=MessageRole.ASSISTANT,
                                content=[block]
                            ))

                        elif item_type == 'video_generation_call':
                            # Video generation call item — represents a previously executed
                            # video generation operation in the conversation history.
                            #
                            # Format:
                            # {
                            #   "type": "video_generation_call",
                            #   "id": "<call_id>",
                            #   "status": "in_progress|completed|generating|failed",
                            #   "result": "<video_url>"
                            # }
                            call_id = item.get('id', '')
                            status = item.get('status', 'completed')
                            result = item.get('result', '')

                            block = ContentBlock.from_tool_call(
                                call_id,
                                'video_generation',
                                {'status': status, 'result': result}
                            )
                            messages.append(Message(
                                role=MessageRole.ASSISTANT,
                                content=[block]
                            ))

                        elif item_type == '3d_generation_call':
                            # 3D generation call item — represents a previously executed
                            # 3D generation operation in the conversation history.
                            #
                            # Format:
                            # {
                            #   "type": "3d_generation_call",
                            #   "id": "<call_id>",
                            #   "status": "in_progress|completed|generating|failed",
                            #   "content": [{"type": "OBJ", "url": "...", "preview_url": "..."}]
                            # }
                            call_id = item.get('id', '')
                            status = item.get('status', 'completed')
                            content = item.get('content', [])

                            block = ContentBlock.from_tool_call(
                                call_id,
                                '3d_generation',
                                {'status': status, 'content': content}
                            )
                            messages.append(Message(
                                role=MessageRole.ASSISTANT,
                                content=[block]
                            ))

                        elif item_type == 'function_call_output':
                            # Tool result item — convert to tool message
                            call_id = item.get('call_id', '')
                            output = item.get('output', '')
                            block = ContentBlock.from_tool_result(call_id, str(output))
                            messages.append(Message(
                                role=MessageRole.TOOL,
                                content=[block],
                                tool_call_id=call_id
                            ))

                        elif 'role' in item:
                            # Standard message object with role
                            role_str = item.get('role', 'user')
                            role = MessageRole(role_str)
                            content = item.get('content', '')

                            if isinstance(content, list):
                                blocks = []
                                for block in content:
                                    block_type = block.get('type', 'input_text')

                                    if block_type in ('input_text', 'text'):
                                        blocks.append(ContentBlock.from_text(block.get('text', '')))
                                    elif block_type in ('input_image', 'image'):
                                        # Handle image content
                                        if 'image_url' in block:
                                            # image_url can be a string or a dict with 'url' key
                                            image_url_val = block['image_url']
                                            url = image_url_val if isinstance(image_url_val, str) else image_url_val.get('url', '')
                                            if url.startswith('data:'):
                                                parts = url.split(',')
                                                media_type = parts[0].replace('data:', '').replace(';base64', '')
                                                data_str = parts[1] if len(parts) > 1 else ''
                                                blocks.append(ContentBlock.from_image_base64(data_str, media_type))
                                            else:
                                                blocks.append(ContentBlock.from_image_url(url))
                                        elif 'source' in block:
                                            source = block['source']
                                            if source.get('type') == 'base64':
                                                blocks.append(ContentBlock.from_image_base64(
                                                    source.get('data', ''),
                                                    source.get('media_type', 'image/jpeg')
                                                ))
                                            elif source.get('type') == 'url':
                                                blocks.append(ContentBlock.from_image_url(source.get('url', '')))
                                    elif block_type in ('input_video', 'video'):
                                        video_url_val = block.get('video_url', '')
                                        if isinstance(video_url_val, dict):
                                            video_url_val = video_url_val.get('url', '')
                                        if video_url_val:
                                            blocks.append(ContentBlock.from_video_url(video_url_val))
                                    elif block_type == 'input_audio':
                                        if 'input_audio' in block:
                                            audio_data = block['input_audio']
                                            blocks.append(ContentBlock.from_audio_base64(
                                                audio_data.get('data', ''),
                                                f"audio/{audio_data.get('format', 'wav')}"
                                            ))
                                    elif block_type == 'input_file':
                                        if 'file_url' in block:
                                            blocks.append(ContentBlock.from_file_url(block['file_url'].get('url', '')))

                                content = blocks if blocks else content

                            tool_call_id = item.get('call_id') or item.get('tool_call_id')
                            name = item.get('name')

                            messages.append(Message(
                                role=role,
                                content=content,
                                name=name,
                                tool_call_id=tool_call_id
                            ))

        # Collect file_id → {type, url} mappings from all media input blocks.
        # Supports input_image, input_video, input_audio blocks that carry a file_id field.
        # Insertion order is preserved so that Seedance variable numbering (图片1, 视频1, …)
        # matches the order the media blocks appear in the input array.
        #
        # Shape: { file_id: {'type': 'image'|'video'|'audio', 'url': str} }
        _file_id_media_map: dict = {}
        for _top_item in data.get('input', []) if isinstance(data.get('input'), list) else []:
            if not isinstance(_top_item, dict):
                continue
            # Scan content blocks inside role-based messages
            _content = _top_item.get('content', [])
            if isinstance(_content, list):
                for _blk in _content:
                    if not isinstance(_blk, dict):
                        continue
                    _blk_type = _blk.get('type', '')
                    _fid = _blk.get('file_id', '')
                    if not _fid:
                        continue
                    _blk_role = _blk.get('role', '')
                    if _blk_type in ('input_image', 'image'):
                        _url = _blk.get('image_url', '')
                        if isinstance(_url, dict):
                            _url = _url.get('url', '')
                        if _url:
                            _file_id_media_map[_fid] = {'type': 'image', 'url': _url, 'role': _blk_role}
                    elif _blk_type in ('input_video', 'video'):
                        _url = _blk.get('video_url', '')
                        if isinstance(_url, dict):
                            _url = _url.get('url', '')
                        if _url:
                            _file_id_media_map[_fid] = {'type': 'video', 'url': _url, 'role': _blk_role}
                    elif _blk_type in ('input_audio', 'audio'):
                        _url = _blk.get('audio_url', '') or _blk.get('url', '')
                        if isinstance(_url, dict):
                            _url = _url.get('url', '')
                        if _url:
                            _file_id_media_map[_fid] = {'type': 'audio', 'url': _url, 'role': _blk_role}
            # Also scan top-level plain blocks (no 'role' used as message-role,
            # but the block itself may carry a media role like 'first_frame')
            _top_type = _top_item.get('type', '')
            _top_fid = _top_item.get('file_id', '')
            _top_role = _top_item.get('role', '')
            # Only treat as a plain media block when the role is a media role or absent
            _MEDIA_ROLES = {'first_frame', 'last_frame', 'reference_image', 'reference_video', 'reference_audio', ''}
            if _top_fid and _top_role in _MEDIA_ROLES:
                if _top_type in ('input_image', 'image'):
                    _url = _top_item.get('image_url', '')
                    if isinstance(_url, dict):
                        _url = _url.get('url', '')
                    if _url:
                        _file_id_media_map[_top_fid] = {'type': 'image', 'url': _url, 'role': _top_role}
                elif _top_type in ('input_video', 'video'):
                    _url = _top_item.get('video_url', '')
                    if isinstance(_url, dict):
                        _url = _url.get('url', '')
                    if _url:
                        _file_id_media_map[_top_fid] = {'type': 'video', 'url': _url, 'role': _top_role}
                elif _top_type in ('input_audio', 'audio'):
                    _url = _top_item.get('audio_url', '') or _top_item.get('url', '')
                    if isinstance(_url, dict):
                        _url = _url.get('url', '')
                    if _url:
                        _file_id_media_map[_top_fid] = {'type': 'audio', 'url': _url, 'role': _top_role}

        # 处理工具定义
        tools = []
        accumulated_img_metadata: dict = {}  # collects image_generation tool parameters
        accumulated_vid_metadata: dict = {}  # collects video_generation tool parameters
        for tool_data in data.get('tools', []):
            tool_type = tool_data.get('type', 'function')

            if tool_type == 'function':
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
                        items=param_schema.get('items')
                    ))

                tools.append(ToolDefinition(
                    name=name,
                    description=description,
                    parameters=parameters,
                    tool_type=ToolType.FUNCTION
                ))
            elif tool_type == 'web_search_preview':
                # Web search tool - pass through as metadata
                pass

            elif tool_type == 'video_generation':
                # Video generation tool — extract generation parameters into metadata.
                # These are picked up by TencentVOD provider when routing to
                # CreateAigcVideoTask.
                #
                # Supported fields:
                #   size / video_size – output video dimensions (WxH), used to derive AspectRatio
                #   aspect_ratio      – explicit AspectRatio ("16:9", "9:16", etc.)
                #   seconds           – video duration in seconds
                #   resolution        – resolution tier ("720p", "1080p", etc.)
                #   n / number        – number of videos (currently 1)
                #   audio_generation  – "Enabled" | "Disabled"
                #   person_generation – "AllowAdult" | "Disallow"
                #   enhance_prompt    – "Enabled"
                #   negative_prompt   – negative prompt string
                #   reference_images  – list of image URLs for reference (image-to-video)
                #   reference_videos  – list of video URLs for reference (video-to-video)
                #   last_frame_url    – URL of last frame image (tail frame)
                #   last_frame_file_id – FileId of last frame image
                vid_metadata: dict = {'_video_generation': True}

                size = tool_data.get('size') or tool_data.get('video_size')
                if size:
                    vid_metadata['size'] = size
                    vid_metadata['video_size'] = size

                # Accept both 'aspect_ratio' (TencentVOD) and 'ratio' (Seedance) field names.
                aspect_ratio = tool_data.get('aspect_ratio') or tool_data.get('ratio')
                if aspect_ratio:
                    vid_metadata['aspect_ratio'] = aspect_ratio
                    vid_metadata['ratio'] = aspect_ratio  # also store under Seedance key

                seconds = tool_data.get('seconds') or tool_data.get('video_seconds') or tool_data.get('duration')
                if seconds is not None:
                    vid_metadata['seconds'] = str(seconds)
                    vid_metadata['duration'] = seconds  # also store under Seedance key

                resolution = tool_data.get('resolution')
                if resolution:
                    vid_metadata['resolution'] = resolution

                n = tool_data.get('n') or tool_data.get('number') or tool_data.get('count')
                if n is not None:
                    vid_metadata['number'] = int(n)

                # generate_audio: bool, default True.
                # - For Seedance API: stored as generate_audio (bool)
                # - For TencentVOD API: mapped to OutputConfig.AudioGeneration ("Enabled" | "Disabled")
                # Accept both generate_audio (new) and audio_generation (legacy).
                generate_audio = tool_data.get('generate_audio')
                if generate_audio is None:
                    generate_audio = True  # default: audio enabled
                audio_generation = tool_data.get('audio_generation')
                if audio_generation:
                    # Legacy explicit string value takes precedence for TencentVOD
                    vid_metadata['audio_generation'] = audio_generation
                    # Also derive bool for Seedance
                    vid_metadata['generate_audio'] = (audio_generation == "Enabled")
                else:
                    vid_metadata['audio_generation'] = "Enabled" if generate_audio else "Disabled"
                    vid_metadata['generate_audio'] = bool(generate_audio)

                person_generation = tool_data.get('person_generation')
                if person_generation:
                    vid_metadata['person_generation'] = person_generation

                enhance_prompt = tool_data.get('enhance_prompt')
                if enhance_prompt:
                    vid_metadata['enhance_prompt'] = enhance_prompt

                negative_prompt = tool_data.get('negative_prompt')
                if negative_prompt:
                    vid_metadata['negative_prompt'] = negative_prompt

                reference_images = tool_data.get('reference_images')
                if reference_images:
                    if isinstance(reference_images, str):
                        reference_images = [reference_images]
                    vid_metadata['reference_images'] = reference_images

                reference_videos = tool_data.get('reference_videos')
                if reference_videos:
                    if isinstance(reference_videos, str):
                        reference_videos = [reference_videos]
                    vid_metadata['reference_videos'] = reference_videos

                last_frame_url = tool_data.get('last_frame_url')
                if last_frame_url:
                    vid_metadata['last_frame_url'] = last_frame_url

                last_frame_file_id = tool_data.get('last_frame_file_id')
                if last_frame_file_id:
                    vid_metadata['last_frame_file_id'] = last_frame_file_id

                reference_audios = tool_data.get('reference_audios')
                if reference_audios:
                    if isinstance(reference_audios, str):
                        reference_audios = [reference_audios]
                    vid_metadata['reference_audios'] = reference_audios

                seed = tool_data.get('seed')
                if seed is not None:
                    vid_metadata['seed'] = seed

                watermark = tool_data.get('watermark')
                if watermark is not None:
                    vid_metadata['watermark'] = bool(watermark)

                # Accept a 'parameters' dict that is forwarded verbatim to the
                # upstream provider API (e.g. Gemini Veo predictLongRunning).
                # Individual top-level fields (aspect_ratio, seconds, …) take
                # precedence over keys inside 'parameters' when both are set.
                raw_parameters = tool_data.get('parameters')
                if isinstance(raw_parameters, dict):
                    vid_metadata['parameters'] = raw_parameters

                # Pass file_id → media info map so the provider can:
                #   1. Substitute {{file_id}} → 图片n / 视频n / 音频n in prompts
                #   2. Build reference_images / reference_videos / reference_audios lists
                if _file_id_media_map:
                    vid_metadata['file_id_media_map'] = _file_id_media_map

                accumulated_vid_metadata.update(vid_metadata)

            elif tool_type == 'image_generation':
                # Image generation tool — extract generation parameters into metadata.
                # These are picked up by providers that support native image generation:
                #   - Volcengine: _execute_image_generation_direct() → /v3/images/generations
                #   - Gemini: prepare_request() → responseModalities: ["TEXT", "IMAGE"]
                #
                # Supported fields:
                #   size             – output image dimensions, e.g. "1024x1024" or "2K"
                #   n                – number of images to generate (aliases: number, count)
                #   response_format  – return format: "b64_json" (default) or "url"
                #   image_format     – image file format: "png" (default) or "jpg"
                #   seed             – random seed for reproducibility
                #   watermark        – bool, whether to add a watermark
                img_metadata = {}

                size = tool_data.get('size')
                if size:
                    img_metadata['size'] = size

                # Accept `n`, `number`, or `count` for image quantity
                n = tool_data.get('n') or tool_data.get('number') or tool_data.get('count')
                if n is not None:
                    img_metadata['number'] = int(n)

                response_format = tool_data.get('response_format')
                if response_format:
                    img_metadata['response_format'] = response_format

                image_format = tool_data.get('image_format') or tool_data.get('output_format')
                if image_format:
                    img_metadata['image_format'] = image_format

                seed = tool_data.get('seed')
                if seed is not None:
                    img_metadata['seed'] = seed

                watermark = tool_data.get('watermark')
                if watermark is not None:
                    img_metadata['watermark'] = bool(watermark)

                aspect_ratio = tool_data.get('aspect_ratio')
                if aspect_ratio:
                    img_metadata['aspect_ratio'] = aspect_ratio

                resolution = tool_data.get('resolution')
                if resolution:
                    img_metadata['resolution'] = resolution

                # Accumulate image generation params; we'll merge into metadata below.
                accumulated_img_metadata.update(img_metadata)

            elif tool_type == '3d_generation':
                # 3D generation tool — extract generation parameters into metadata.
                # These are picked up by HunyuanProvider when routing to
                # SubmitHunyuanTo3DRapidJob / SubmitHunyuanTo3DProJob.
                #
                # Tool fields:
                #   pbr             – bool, enable PBR material generation
                #   output_format   – "OBJ"|"GLB"|"STL"|"USDZ"|"FBX"|"MP4"
                #   enable_geometry – bool, geometry-only (白模) generation (alias: geometry)
                #   face_count      – int (Pro only, not effective for LowPoly): 3000–1500000
                #   generate_type   – "Normal"|"LowPoly"|"Geometry"|"Sketch" (Pro only)
                #   polygon_type    – "triangle"|"quadrilateral" (Pro+LowPoly only)
                #
                # Multi-view images are NOT passed in the tool definition.
                # They are collected from the input content blocks where each
                # input_image block carries a "view" field:
                #   {"type": "input_image", "image_url": "...", "view": "back"|"left"|"right"}
                threed_metadata: dict = {'_3d_generation': True}

                # pbr (accept both 'pbr' and 'enable_pbr')
                pbr = tool_data.get('pbr')
                if pbr is None:
                    pbr = tool_data.get('enable_pbr')
                if pbr is not None:
                    threed_metadata['enable_pbr'] = bool(pbr)
                    threed_metadata['pbr'] = bool(pbr)

                # output_format (accept both 'output_format' and 'result_format')
                output_format = tool_data.get('output_format') or tool_data.get('result_format')
                if output_format:
                    threed_metadata['output_format'] = output_format
                    threed_metadata['result_format'] = output_format

                # enable_geometry (accept both 'enable_geometry' and 'geometry')
                enable_geometry = tool_data.get('enable_geometry')
                if enable_geometry is None:
                    enable_geometry = tool_data.get('geometry')
                if enable_geometry is not None:
                    threed_metadata['enable_geometry'] = bool(enable_geometry)

                # face_count (Pro only)
                face_count = tool_data.get('face_count')
                if face_count is not None:
                    threed_metadata['face_count'] = int(face_count)

                # generate_type (Pro only): Normal | LowPoly | Geometry | Sketch
                generate_type = tool_data.get('generate_type')
                if generate_type:
                    threed_metadata['generate_type'] = generate_type

                # polygon_type (Pro+LowPoly only): triangle | quadrilateral
                polygon_type = tool_data.get('polygon_type')
                if polygon_type:
                    threed_metadata['polygon_type'] = polygon_type

                # Collect multi-view images from the input content blocks.
                # Each input_image block that has a "view" field contributes one
                # multi-view entry. Supported view values:
                #   front, back, left, right, up, down, left_front, right_front
                # These are used by hunyuan-3d-pro as MultiViewImages.
                _multi_view_images = []
                for _top_item in data.get('input', []) if isinstance(data.get('input'), list) else []:
                    if not isinstance(_top_item, dict):
                        continue
                    _item_content = _top_item.get('content', [])
                    if isinstance(_item_content, list):
                        for _blk in _item_content:
                            if not isinstance(_blk, dict):
                                continue
                            if _blk.get('type') in ('input_image', 'image'):
                                _view = _blk.get('view', '')
                                if not _view:
                                    continue  # skip images without a view angle
                                _img_url = _blk.get('image_url', '')
                                if isinstance(_img_url, dict):
                                    _img_url = _img_url.get('url', '')
                                _img_b64 = _blk.get('image_base64', '')
                                if _img_url or _img_b64:
                                    _multi_view_images.append({
                                        'url': _img_url,
                                        'image_base64': _img_b64,
                                        'view': _view,
                                    })

                if _multi_view_images:
                    threed_metadata['multi_view_images'] = _multi_view_images

                accumulated_vid_metadata.update(threed_metadata)

        # Parse reasoning parameter
        reasoning_effort = None
        reasoning = data.get('reasoning')
        if reasoning:
            if isinstance(reasoning, dict):
                reasoning_effort = reasoning.get('effort')
            elif isinstance(reasoning, str):
                reasoning_effort = reasoning

        # 如果模型名包含 "thinking" 但没有设置任何 reasoning_effort 参数，
        # 将 reasoning_effort 设置为默认值
        model_name = data.get('model', '')
        if 'thinking' in model_name.lower() and not reasoning_effort:
            reasoning_effort = REASONING_EFFORT_DEFAULT_FOR_THINKING

        # 收集额外参数
        known_keys = {
            'model', 'input', 'instructions', 'temperature', 'top_p',
            'max_output_tokens', 'stream', 'tools', 'tool_choice',
            'stop', 'presence_penalty', 'frequency_penalty', 'user',
            'metadata', 'store', 'truncation', 'reasoning'
        }
        metadata = {k: v for k, v in data.items() if k not in known_keys}

        # Store full reasoning config in metadata so providers can use all fields (e.g. summary)
        if reasoning and isinstance(reasoning, dict):
            metadata['reasoning'] = reasoning

        # Merge image_generation tool parameters into metadata so the Volcengine
        # provider can forward them to /v3/images/generations
        if accumulated_img_metadata:
            metadata.update(accumulated_img_metadata)

        # Merge video_generation tool parameters into metadata so the TencentVOD
        # provider can forward them to CreateAigcVideoTask
        if accumulated_vid_metadata:
            metadata.update(accumulated_vid_metadata)

        # Preserve the raw tools array so that Responses-API-compatible providers
        # (openai_responses_compt) can pass it directly to the upstream without
        # reconstructing it from ToolDefinition objects.
        raw_tools = data.get('tools', [])
        if raw_tools:
            metadata['_raw_tools'] = raw_tools

        return ChatRequest(
            messages=messages,
            model=data.get('model', ''),
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
            reasoning_effort=reasoning_effort,
            metadata=metadata
        )

    def format_response(self, response: ChatResponse) -> dict:
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

        # Detect image generation responses by ID prefix or provider type.
        # These are returned by image generation providers (Volcengine, Gemini)
        # and should be rendered as image_generation_call output items, not messages.
        # gen_id("img") produces "img_xxxx" format.
        is_image_generation = (
            response.id.startswith("img-") or
            response.id.startswith("img_") or
            getattr(response, 'provider', '') == "volcengine_image"
        )

        # Detect video generation responses by ID prefix.
        # gen_id("vid") produces "vid_xxxx" format.
        is_video_generation = (
            response.id.startswith("vid-") or
            response.id.startswith("vid_")
        )

        # Detect 3D generation responses by ID prefix.
        # gen_id("3d") produces "3d_xxxx" format.
        is_3d_generation = (
            response.id.startswith("3d-") or
            response.id.startswith("3d_")
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
                    items = json.loads(raw) if isinstance(raw, str) else []
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
                    items = json.loads(raw) if isinstance(raw, str) else []
                except (json.JSONDecodeError, TypeError):
                    items = []

            for i, item in enumerate(items):
                call_id = f"{response.id}-{i}" if i > 0 else response.id
                if isinstance(item, dict):
                    status = item.get("status", "completed")
                    result = item.get("result", "")
                else:
                    status = "completed"
                    result = str(item)
                output.append({
                    "type": "video_generation_call",
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
                    items = json.loads(raw) if isinstance(raw, str) else []
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

        return {
            'id': response.id.replace('chatcmpl-', 'resp_') if response.id.startswith('chatcmpl-') else response.id,
            'object': 'response',
            'created_at': response.created,
            'model': response.model,
            'status': status,
            'output': output,
            'usage': usage_dict
        }

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

            # Only emit text/content_part/message done events if there was actual text content
            # (i.e. _stream_text_started is True). For function-call-only responses we skip these.
            has_text = getattr(self, '_stream_text_started', False)
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
            if has_tool_calls and not has_text:
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

                    # Include function_calls in output if any were accumulated during the stream
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

                    # Only include message in output if there was actual text content
                    if has_text:
                        output_content = [{'type': 'output_text', 'text': full_text, 'annotations': []}]
                        output_items.append({
                            'type': 'message',
                            'id': msg_id or _gen_id("msg"),
                            'role': 'assistant',
                            'status': 'completed',
                            'content': output_content
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
        from flask import Response, jsonify
        from app.middleware.gateway_service import GatewayServiceError, ProviderError
        import itertools

        # ------------------------------------------------------------------
        # Eagerly consume the first chunk to surface provider errors early.
        # ------------------------------------------------------------------
        chunk_iter_raw = iter(chunks)
        first_chunks: list = []
        try:
            first_chunk = next(chunk_iter_raw)
            first_chunks.append(first_chunk)
        except StopIteration:
            pass
        except ProviderError as e:
            return jsonify(self.format_error_response(e.message, e.status_code, e.error_data)), e.status_code
        except GatewayServiceError as e:
            return jsonify(self.format_error_response(e.message, e.status_code)), e.status_code
        except Exception as e:
            return jsonify(self.format_error_response(str(e), 500)), 500

        # Re-chain the eagerly consumed chunk(s) with the remaining iterator
        all_chunks = itertools.chain(first_chunks, chunk_iter_raw)

        def _is_marker_chunk(chunk: StreamChunk) -> bool:
            """Return True if this chunk is a role-only marker carrying an ID."""
            return bool(
                chunk.delta_role
                and not chunk.delta_content
                and not chunk.finish_reason
                and not chunk.tool_calls
                and not chunk.raw_sse_passthrough
            )

        def generate():
            try:
                real_response_id = None
                real_msg_id = None
                buffered_chunk = None

                chunk_iter = iter(all_chunks)

                # Consume all leading marker chunks before emitting the start event.
                # Markers are role-only chunks with no content/finish/tool_calls:
                #   delta_role == "assistant"   → carries the real resp_xxx response ID
                #   delta_role.startswith("msg_") → carries the real msg_xxx message ID
                # We keep consuming until we see the first non-marker (real content) chunk.
                while True:
                    try:
                        chunk = next(chunk_iter)
                    except StopIteration:
                        chunk = None
                        break

                    if not _is_marker_chunk(chunk):
                        # Real content chunk — buffer it for after the start event
                        buffered_chunk = chunk
                        break

                    role_val = chunk.delta_role
                    if role_val == "assistant":
                        real_response_id = chunk.id if chunk.id else None
                    elif role_val and role_val.startswith("msg_"):
                        real_msg_id = role_val
                    # Any other role value is silently dropped

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

                    if chunk.usage and not chunk.finish_reason:
                        # Usage-only chunk (stream_options / incremental_output).
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
                    parts.append(self.format_stream_chunk(chunk))
                    return ''.join(parts)

                # Process buffered first chunk (if any)
                if buffered_chunk is not None:
                    sse = _process_chunk(buffered_chunk)
                    if sse:
                        yield sse

                # Process remaining chunks
                for chunk in chunk_iter:
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

                    # Include function_calls
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

                    # Include message if there was text content
                    if full_text and getattr(self, '_stream_text_started', False):
                        output_items.append({
                            'type': 'message',
                            'id': real_msg_id or _gen_id("msg"),
                            'role': 'assistant',
                            'status': 'completed',
                            'content': [{'type': 'output_text', 'text': full_text, 'annotations': []}]
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

        from flask import Response
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

        OpenAI Responses API returns errors in the same format as Chat Completions:
        {"error": {"message": "...", "type": "...", "param": "...", "code": null}}

        When error_data is provided from the upstream provider, it already contains the
        full error structure (e.g. {"error": {...}}), so we return it as-is.
        """
        if error_data:
            return error_data
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
            # error_data may already be wrapped as {"error": {...}}; unwrap if so
            inner = error.error_data
            if 'error' in inner and isinstance(inner['error'], dict):
                inner = inner['error']
            error_event = inner
        else:
            error_event = {
                'type': 'server_error',
                'message': str(error)
            }

        return f"event: error\ndata: {json.dumps(error_event)}\n\n"
