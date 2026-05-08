"""
OpenAI Responses API 兼容供应商 (OpenAI Responses API Compatible Provider)

用于对接任何兼容 OpenAI Responses API (/v1/responses) 的服务。
与 OpenAIProvider（Chat Completions）的区别：

请求格式差异：
  - 使用 `input` 替代 `messages`
  - 系统消息用 `instructions` 字段表达
  - 使用 `max_output_tokens` 替代 `max_tokens`
  - 推理参数用 `reasoning.effort` 表达

响应格式差异：
  - 使用 `output` 替代 `choices`
  - output 内容项类型为 `message` / `function_call` / `reasoning`
  - 文本内容块类型为 `output_text` 而非 `text`
  - usage 字段使用 `input_tokens` / `output_tokens`

流式事件差异：
  - 事件名称形如 `response.output_text.delta` / `response.completed`
  - 通过 `event:` + `data:` 双行 SSE 格式传输

典型使用场景
-----------
  - 对接 OpenAI 官方 Responses API（/v1/responses）
  - 对接实现了 Responses API 格式的第三方服务
  - 需要利用 reasoning / multi-turn 扩展能力时

配置说明
--------
  Base URL: 填写服务地址前缀，例如 https://api.openai.com/v1
  API Key : 填写对应的 API 密钥，留空时省略 Authorization 头
"""
import json
import time
import uuid
from typing import Dict, Any, List, Optional, Generator

from .base import BaseProvider, ProviderConfig, ProviderCapability
from .openai_provider import OpenAIProvider
from app.utils import json_loads
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.abstraction.tools import ToolCall

# 网关内部元数据键，不向上游透传
_GATEWAY_INTERNAL_KEYS = frozenset({
    'support_thinking', 'support_online_image', 'support_online_video', 'reasoning',
    '_raw_tools',  # raw tools array preserved by responses_adapter; handled separately
})


class OpenAIResponsesCompatProvider(OpenAIProvider):
    """
    OpenAI Responses API 兼容供应商。

    继承 OpenAIProvider 以复用消息格式转换逻辑（_message_to_openai、
    _content_block_to_openai 等），并覆盖：

    - ``prepare_request``  → 转换为 Responses API 请求格式
    - ``chat``             → POST 到 /v1/responses
    - ``stream_chat``      → 解析 Responses API SSE 事件
    - ``parse_response``   → 解析 Responses API 响应体
    """

    PROVIDER_TYPE: str = "openai_responses_compt"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
        ProviderCapability.AUDIO,
    ]

    # 无默认 Base URL，由用户配置
    DEFAULT_BASE_URL: str = ""

    def __init__(self, config: ProviderConfig):
        # 绕过 OpenAIProvider.__init__ 中 DEFAULT_BASE_URL 强制赋值
        from .base import BaseProvider as _Base
        _Base.__init__(self, config)

    # ------------------------------------------------------------------
    # 请求头
    # ------------------------------------------------------------------

    def get_headers(self) -> Dict[str, str]:
        """
        构建请求头。api_key 为空时省略 Authorization 头。
        """
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            if self.config.authorization and self.config.authorization != "Authorization":
                headers[self.config.authorization] = self.config.api_key
            else:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    # ------------------------------------------------------------------
    # 请求转换：ChatRequest → Responses API 格式
    # ------------------------------------------------------------------

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        将 ChatRequest 转换为 OpenAI Responses API 请求格式。

        规则：
          - 第一条 system 消息提取为 ``instructions``
          - 其余消息转换为 ``input`` 数组（OpenAI messages 格式）
          - max_tokens → max_output_tokens
          - reasoning_effort → reasoning.effort
        """
        # System instructions pass through as-is
        # Separate developer messages from regular messages for different handling
        other_messages = []
        developer_items = []
        for msg in request.messages:
            if msg.role == MessageRole.DEVELOPER:
                content = msg.get_text_content() or ''
                if content:
                    developer_items.append({"role": "developer", "content": content})
            elif msg.role != MessageRole.SYSTEM:
                other_messages.append(msg)

        # Build input array, developer messages first
        input_array = developer_items + self._messages_to_responses_input(other_messages)

        # 构建基础请求体
        result: Dict[str, Any] = {
            "model": request.model,
            "input": input_array,
            "stream": request.stream,
        }

        if request.system is not None:
            result["instructions"] = request.system

        if request.temperature is not None:
            result["temperature"] = request.temperature
        if request.top_p is not None:
            result["top_p"] = request.top_p
        if request.max_tokens is not None:
            result["max_output_tokens"] = request.max_tokens

        # Prefer the raw tools array preserved by responses_adapter (includes
        # non-function tools like image_generation / video_generation verbatim).
        # Fall back to rebuilding from ToolDefinition objects for other adapters.
        raw_tools = request.metadata.get('_raw_tools')
        if raw_tools:
            result["tools"] = raw_tools
        elif request.tools:
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

        # reasoning_effort → reasoning.effort
        if request.reasoning_effort and request.reasoning_effort != 'none':
            result["reasoning"] = {"effort": request.reasoning_effort}

        # 透传额外 metadata（过滤网关内部键）
        for key, value in request.metadata.items():
            if key not in _GATEWAY_INTERNAL_KEYS:
                result[key] = value

        return result

    # ------------------------------------------------------------------
    # 消息转换：内部格式 → Responses API input 格式
    # ------------------------------------------------------------------

    def _messages_to_responses_input(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """
        将内部 Message 列表转换为 OpenAI Responses API 的 ``input`` 数组。

        Responses API input 格式规则
        ----------------------------
        - user 消息    → ``{"role": "user", "content": [{type: input_text/input_image/input_audio/input_file, ...}]}``
        - assistant 消息（含工具调用）→ 每个 tool_call 单独作为顶层 ``{"type": "function_call", ...}`` 条目，
          文本内容作为 ``{"role": "assistant", "content": [{type: output_text, ...}]}``
        - tool 消息（工具结果）→ 顶层 ``{"type": "function_call_output", "call_id": "...", "output": "..."}``
        """
        result: List[Dict[str, Any]] = []

        for msg in messages:
            items = self._message_to_responses_items(msg)
            result.extend(items)

        return result

    def _message_to_responses_items(self, message: Message) -> List[Dict[str, Any]]:
        """
        将单条 Message 转换为一个或多个 Responses API input 条目。

        Returns:
            Responses API input 条目列表（通常为 1 条，tool 调用时可能多条）
        """
        blocks = message.get_content_blocks()
        role = message.role

        # ── TOOL 角色：工具结果消息 ────────────────────────────────
        if role == MessageRole.TOOL:
            # 每个内容块或 tool_call_id 映射为 function_call_output
            result: List[Dict[str, Any]] = []
            for block in blocks:
                if block.type == ContentType.TOOL_RESULT:
                    result.append({
                        "type": "function_call_output",
                        "call_id": block.tool_call_id or message.tool_call_id or "",
                        "output": block.tool_result or "",
                    })
            if not result:
                # fallback：直接用消息级的 tool_call_id
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

            # tool_call 块 → 顶层 function_call 条目
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

            # 文本块 → assistant content 消息
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

            # 如果 assistant 消息完全没有内容，至少保留一个空文本
            if not result:
                result.append({"type": "message", "role": "assistant", "content": []})

            return result

        # ── USER 角色（默认）──────────────────────────────────────
        # 包含 tool_result 块时，也处理为 function_call_output（Anthropic 风格兼容）
        tool_result_items: List[Dict[str, Any]] = []
        content_parts: List[Dict[str, Any]] = []

        for block in blocks:
            if block.type == ContentType.TOOL_RESULT:
                tool_result_items.append({
                    "type": "function_call_output",
                    "call_id": block.tool_call_id or "",
                    "output": block.tool_result or "",
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
                content_parts.append({
                    "type": "input_file",
                    "data": block.data or "",
                    "media_type": media,
                })
            # TOOL_CALL 在 user 消息中不应出现，忽略

        result = []
        # function_call_output 作为顶层条目（Anthropic tool_result 兼容）
        result.extend(tool_result_items)
        if content_parts:
            result.append({"type": "message", "role": "user", "content": content_parts})
        elif not tool_result_items:
            # 空 user 消息，保留最小结构
            result.append({"type": "message", "role": "user", "content": []})

        return result

    # ------------------------------------------------------------------
    # 非流式请求
    # ------------------------------------------------------------------

    def chat(self, request: ChatRequest) -> ChatResponse:
        """向 /v1/responses 发送非流式请求。"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        request_data = self.prepare_request(request)
        request_data["stream"] = False

        url = f"{self.config.base_url}/responses"

        try:
            with self._trace_call(request.model, input_data=request_data) as child_span:
                response = self.client.post(url, json=request_data)

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        raise RuntimeError(
                            f"OpenAI Responses API error ({response.status_code}): "
                            f"{json.dumps(error_data, ensure_ascii=False)}"
                        )
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"OpenAI Responses API error ({response.status_code}): {response.text}"
                        )

                response.raise_for_status()
                response_data = response.json()
                if child_span:
                    child_span.log_output(response_data)
                return self.parse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"OpenAI Responses API error: {str(e)}")

    # ------------------------------------------------------------------
    # 响应解析：Responses API → ChatResponse
    # ------------------------------------------------------------------

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        将 OpenAI Responses API 响应体解析为 ChatResponse。

        响应结构：
        {
          "id": "resp_xxx",
          "object": "response",
          "created_at": ...,
          "model": "...",
          "status": "completed",
          "output": [
            {
              "type": "reasoning",
              "summary": [{"type": "summary_text", "text": "..."}]
            },
            {
              "type": "message",
              "role": "assistant",
              "content": [{"type": "output_text", "text": "..."}]
            },
            {
              "type": "function_call",
              "call_id": "...", "name": "...", "arguments": "..."
            }
          ],
          "usage": {
            "input_tokens": ..., "output_tokens": ..., "total_tokens": ...
          }
        }
        """
        output_items = response_data.get("output", [])
        status = response_data.get("status", "completed")

        # ── 检测特殊生成调用类型 ──────────────────────────────────────
        # 上游 Responses API 可能直接返回 image_generation_call /
        # video_generation_call / 3d_generation_call 输出项。
        # 将它们整理成 JSON 列表存入消息文本，并为响应 ID 加上适当前缀，
        # 以便 format_response 走正确的图片/视频/3D 代码路径。
        _GEN_TYPE_MAP = {
            "image_generation_call": "img",
            "video_generation_call": "vid",
            "3d_generation_call": "3d",
        }
        gen_type: Optional[str] = None   # 'img' | 'vid' | '3d'
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
            # 以 JSON 字符串形式存入消息内容，与 execute_image_generation() 保持一致
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
            # Ensure ID carries the correct prefix so format_response detects it
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
                provider=self.PROVIDER_TYPE
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

        # 收集文本内容和工具调用
        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        tool_call_blocks: List[ContentBlock] = []

        for item in output_items:
            item_type = item.get("type", "")

            if item_type == "message":
                for content_block in item.get("content", []):
                    block_type = content_block.get("type", "")
                    if block_type == "output_text":
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

        # 组建消息内容
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

        # 映射 status → finish_reason
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

        # usage
        usage_data = response_data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0)
        )
        # 详细 token 信息
        input_details = usage_data.get("input_tokens_details", {})
        output_details = usage_data.get("output_tokens_details", {})
        if input_details.get("cached_tokens"):
            usage.cached_tokens = input_details["cached_tokens"]
        if output_details.get("reasoning_tokens"):
            usage.reasoning_tokens = output_details["reasoning_tokens"]

        resp_id = response_data.get("id", f"resp_{uuid.uuid4().hex[:8]}")
        created = response_data.get("created_at", int(time.time()))

        # Store the raw upstream status so callers (e.g. background worker) can
        # detect when the upstream itself returned an async (in_progress) response
        # and need to poll before saving the final result.
        usage.extra['_upstream_status'] = status

        # Preserve the upstream error object so callers can surface the real
        # error message to the end user when status == "failed".
        upstream_error = response_data.get("error")
        if upstream_error:
            usage.extra['_upstream_error'] = upstream_error

        return ChatResponse(
            id=resp_id,
            model=response_data.get("model", model),
            choices=[choice],
            usage=usage,
            created=created,
            provider=self.PROVIDER_TYPE
        )

    # ------------------------------------------------------------------
    # 流式请求
    # ------------------------------------------------------------------

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """
        向 /v1/responses 发送流式请求，解析 Responses API SSE 事件。

        Responses API 的 SSE 事件格式（每个事件由两行组成）：
            event: response.output_text.delta
            data: {"type":"response.output_text.delta","delta":"Hello"}

        主要事件类型：
          - response.created          : 响应开始
          - response.output_item.added: 新 output item（message / function_call）
          - response.output_text.delta: 文本增量
          - response.function_call_arguments.delta: 工具参数增量
          - response.output_text.done : 文本完成（携带完整文本）
          - response.completed        : 响应完成（携带完整响应体）
        """
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        request_data = self.prepare_request(request)
        request_data["stream"] = True

        url = f"{self.config.base_url}/responses"
        response_id = f"resp_{uuid.uuid4().hex[:8]}"

        # 跟踪工具调用参数累积
        _tc_accum: Dict[str, Dict[str, Any]] = {}  # call_id → {name, args}

        try:
            with self._trace_call(request.model, input_data=request_data), \
                 self.client.stream("POST", url, json=request_data) as response:
                if response.status_code >= 400:
                    error_text = ""
                    for chunk in response.iter_bytes():
                        if chunk:
                            error_text += chunk.decode("utf-8")
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(
                            f"OpenAI Responses API error ({response.status_code}): "
                            f"{json.dumps(error_data, ensure_ascii=False)}"
                        )
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"OpenAI Responses API error ({response.status_code}): {error_text}"
                        )

                current_event: Optional[str] = None

                for line in response.iter_lines():
                    if not line:
                        # 空行：事件边界，重置当前事件名
                        current_event = None
                        continue

                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue

                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue

                        try:
                            event_data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        chunk = self._parse_responses_event(
                            event_data, current_event, response_id, request.model, _tc_accum
                        )
                        if chunk:
                            yield chunk

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"OpenAI Responses API streaming error: {str(e)}")

    def _parse_responses_event(
        self,
        event_data: Dict[str, Any],
        event_name: Optional[str],
        response_id: str,
        model: str,
        tc_accum: Dict[str, Dict[str, Any]],
    ) -> Optional[StreamChunk]:
        """
        将单个 Responses API SSE 事件解析为 StreamChunk。

        Args:
            event_data : 解析后的事件 JSON
            event_name : 来自 ``event:`` 行的事件类型名称
            response_id: 当前响应 ID
            model      : 模型名称
            tc_accum   : 工具调用参数累积字典（call_id → {name, args}）

        Returns:
            StreamChunk 或 None（不需要产出的事件）
        """
        # 优先使用 event_name（来自 event: 行），其次使用 data 中的 type 字段
        etype = event_name or event_data.get("type", "")
        resp_id = event_data.get("response", {}).get("id", response_id) if "response" in event_data else response_id

        # ── 文本增量 ─────────────────────────────────────────────────
        if etype in (
            "response.output_text.delta",
            "response.text.delta",
        ):
            delta = event_data.get("delta", "")
            if delta:
                return StreamChunk(
                    id=resp_id,
                    model=model,
                    delta_content=delta,
                    created=int(time.time())
                )

        # ── 工具调用参数增量 ─────────────────────────────────────────
        elif etype in (
            "response.function_call_arguments.delta",
        ):
            item_id = event_data.get("item_id", "")
            call_id = event_data.get("call_id", item_id)
            delta_args = event_data.get("delta", "")

            if call_id not in tc_accum:
                tc_accum[call_id] = {"name": "", "args": ""}
            tc_accum[call_id]["args"] += delta_args

            # 以 OpenAI Chat Completions 流格式透出，保持与适配器兼容
            tool_call_delta = [{
                "index": 0,
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tc_accum[call_id].get("name", ""),
                    "arguments": delta_args
                }
            }]
            return StreamChunk(
                id=resp_id,
                model=model,
                tool_calls=tool_call_delta,
                created=int(time.time())
            )

        # ── 工具调用 item 出现（含函数名）────────────────────────────
        elif etype == "response.output_item.added":
            item = event_data.get("item", {})
            if item.get("type") == "function_call":
                call_id = item.get("call_id") or item.get("id", "")
                name = item.get("name", "")
                if call_id:
                    tc_accum[call_id] = {"name": name, "args": ""}
                    # 发出带函数名的首个 tool_calls delta
                    tool_call_delta = [{
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": ""}
                    }]
                    return StreamChunk(
                        id=resp_id,
                        model=model,
                        tool_calls=tool_call_delta,
                        created=int(time.time())
                    )

        # ── 响应完成事件（携带完整响应体）───────────────────────────
        elif etype == "response.completed":
            full_response = event_data.get("response", {})
            usage_data = full_response.get("usage", {})
            if usage_data:
                usage = {
                    "prompt_tokens": usage_data.get("input_tokens", 0),
                    "completion_tokens": usage_data.get("output_tokens", 0),
                    "total_tokens": usage_data.get("total_tokens", 0),
                }
                return StreamChunk(
                    id=resp_id,
                    model=model,
                    usage=usage,
                    finish_reason=FinishReason.STOP,
                    event_type=StreamEventType.USAGE,
                    created=int(time.time())
                )

        # ── 其他事件（response.created / response.in_progress 等）───
        # 不产出 StreamChunk
        return None

    # ------------------------------------------------------------------
    # 轮询上游异步响应
    # ------------------------------------------------------------------

    def get_response(self, upstream_response_id: str, model: str) -> ChatResponse:
        """
        通过 GET /v1/responses/{id} 查询上游异步响应的最新状态。

        当上游 Responses API 自身是异步的（即首次 POST 后返回
        ``status: "queued"`` / ``"in_progress"``），后台工作线程需要
        反复调用此方法轮询，直到状态变为 ``"completed"`` 或 ``"failed"``。

        返回的 ``ChatResponse.usage.extra['_upstream_status']`` 携带了
        原始的上游 status 字段，调用方可据此决定是否继续轮询。

        Args:
            upstream_response_id: 上游返回的 response id（如 ``resp_xxx``）。
            model: 模型名称（用于填充 ChatResponse.model）。

        Returns:
            解析后的 ChatResponse（包含最新 upstream status）。

        Raises:
            RuntimeError: 上游 HTTP 错误或网络问题。
        """
        url = f"{self.config.base_url}/responses/{upstream_response_id}"
        try:
            response = self.client.get(url)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    raise RuntimeError(
                        f"OpenAI Responses API error ({response.status_code}): "
                        f"{json.dumps(error_data, ensure_ascii=False)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"OpenAI Responses API error ({response.status_code}): {response.text}"
                    )

            response.raise_for_status()
            return self.parse_response(response.json(), model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"OpenAI Responses API get_response error: {str(e)}")

    # ------------------------------------------------------------------
    # 模型信息
    # ------------------------------------------------------------------

    def supports_model(self, model: str) -> bool:
        """Responses 兼容服务支持任意模型名称。"""
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """返回通用模型信息占位。"""
        return {
            "description": f"OpenAI Responses API compatible model: {model}",
            "context_size": 8192,
            "supports_vision": False,
        }
