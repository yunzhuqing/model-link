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
from typing import Dict, Any, List, Optional, AsyncGenerator

from .base import BaseProvider, ProviderConfig, ProviderCapability
from ._responses_format import (
    build_responses_request,
    parse_responses_response,
)
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk, StreamEventType, FinishReason
from app.abstraction.tts import TTSRequest, TTSResponse
from app.abstraction.transcription import TranscriptionRequest, TranscriptionResponse


class OpenAIResponsesCompatProvider(BaseProvider):
    """
    OpenAI Responses API 兼容供应商。

    直接继承 BaseProvider，通过 _responses_format 共享模块
    获取请求构建和响应解析能力。

    覆盖：
    - ``prepare_request``  → 委托给 build_responses_request()
    - ``chat``             → POST 到 /v1/responses
    - ``stream_chat``      → 解析 Responses API SSE 事件
    - ``parse_response``   → 委托给 parse_responses_response()
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
        """委托给共享模块构建 Responses API 请求体。"""
        return build_responses_request(request)

    async def speech(self, request: TTSRequest) -> TTSResponse:
        """
        执行文本转语音请求 (text-to-speech)。

        Delegates to the shared ``openai_speech`` helper (same ``/audio/speech``
        surface as the Chat-Completions-compatible provider). ``request.input``
        may be a plain string or an array of content blocks (text / image /
        audio) — it is passed through to the upstream verbatim.
        """
        from ._tts import openai_speech
        return await openai_speech(self, request)

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        """
        执行音频转文字请求 (audio transcription)。

        Delegates to the shared ``openai_transcribe`` helper (same
        ``/audio/transcriptions`` surface as the Chat-Completions-compatible
        provider). Forwards the multipart upload verbatim.
        """
        from ._transcription import openai_transcribe
        return await openai_transcribe(self, request)

    # ------------------------------------------------------------------
    # 非流式请求
    # ------------------------------------------------------------------

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """向 /v1/responses 发送非流式请求。"""
        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        request_data = await self.aprepare_request(request)
        request_data["stream"] = False

        url = f"{self.config.base_url}/responses"

        try:
            async with self._trace_call(request.model, input_data=request_data) as child_span:
                response = await (await self._http()).post(url, json=request_data, headers=self.get_headers())

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
                return await self.aparse_response(response_data, request.model)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"OpenAI Responses API error: {str(e)}")

    # ------------------------------------------------------------------
    # 响应解析：Responses API → ChatResponse
    # ------------------------------------------------------------------

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """委托给共享模块解析 Responses API 响应。"""
        return parse_responses_response(response_data, model)

    # ------------------------------------------------------------------
    # 流式请求
    # ------------------------------------------------------------------

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
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

        request_data = await self.aprepare_request(request)
        request_data["stream"] = True

        url = f"{self.config.base_url}/responses"
        response_id = f"resp_{uuid.uuid4().hex[:8]}"

        # 跟踪工具调用参数累积
        _tc_accum: Dict[str, Dict[str, Any]] = {}  # call_id → {name, args, ...}
        _tc_id_map: Dict[str, str] = {}            # item_id → call_id (custom_tool_call)

        try:
            async with self._trace_call(request.model, input_data=request_data) as child_span:
                async with (await self._http()).stream("POST", url, json=request_data, headers=self.get_headers()) as response:
                    if response.status_code >= 400:
                        error_text = ""
                        async for chunk in response.aiter_bytes():
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

                    async for line in response.aiter_lines():
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
                                event_data, current_event, response_id, request.model, _tc_accum, _tc_id_map
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
        tc_id_map: Dict[str, str],
    ) -> Optional[StreamChunk]:
        """
        将单个 Responses API SSE 事件解析为 StreamChunk。

        Args:
            event_data : 解析后的事件 JSON
            event_name : 来自 ``event:`` 行的事件类型名称
            response_id: 当前响应 ID
            model      : 模型名称
            tc_accum   : 工具调用参数累积字典（call_id → {name, args, ...}）
            tc_id_map  : custom_tool_call item_id → call_id 映射（delta 事件
                         只携带 item_id，需据此回查 call_id）

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
            "response.custom_tool_call_input.delta",
        ):
            item_id = event_data.get("item_id", "")
            call_id = event_data.get("call_id", "")
            delta_args = event_data.get("delta", "")

            is_custom = etype == "response.custom_tool_call_input.delta"
            if is_custom:
                # custom_tool_call_input.delta 只携带 item_id（ctc_xxx），需回查
                # output_item.added 时登记的 item_id → call_id 映射。
                if not call_id:
                    call_id = tc_id_map.get(item_id, item_id)
            else:
                call_id = call_id or item_id
            if call_id not in tc_accum:
                tc_accum[call_id] = {"name": "", "args": "", "namespace": None,
                                     "caller": None, "item_id": item_id, "type": "custom" if is_custom else "function"}
            tc_accum[call_id]["args"] += delta_args

            # 以 OpenAI Chat Completions 流格式透出，保持与适配器兼容。
            # 注意:增量 chunk 不携带 id —— 适配器的 format_stream_chunk 会把
            # 任何带 id 的 chunk 当作新的工具调用开始,重复 id 会触发重复的
            # response.output_item.added。增量通过 output_index → call_id 映射
            # (output_item.added 时登记)或 _stream_current_tc_call_id 解析。
            acc = tc_accum[call_id]
            tc_output_index = event_data.get("output_index", 0)
            if is_custom:
                tool_call_delta = [{
                    "index": tc_output_index,
                    "type": "custom",
                    "custom": {
                        "name": acc.get("name", ""),
                        "input": delta_args
                    },
                    "namespace": acc.get("namespace"),
                    "caller": acc.get("caller"),
                    "item_id": acc.get("item_id") or item_id,
                }]
            else:
                tool_call_delta = [{
                    "index": tc_output_index,
                    "type": "function",
                    "function": {
                        "name": acc.get("name", ""),
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
                    tc_accum[call_id] = {"name": name, "args": "", "namespace": None,
                                         "caller": None, "item_id": "", "type": "function"}
                    # 发出带函数名的首个 tool_calls delta
                    tool_call_delta = [{
                        "index": event_data.get("output_index", 0),
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
            elif item.get("type") == "custom_tool_call":
                call_id = item.get("call_id") or item.get("id", "")
                name = item.get("name", "")
                if call_id:
                    item_id = item.get("id", "")
                    tc_accum[call_id] = {
                        "name": name,
                        "args": "",
                        "namespace": item.get("namespace"),
                        "caller": item.get("caller"),
                        "item_id": item_id,
                        "type": "custom",
                    }
                    if item_id:
                        tc_id_map[item_id] = call_id
                    # 发出带函数名/命名空间的首个 tool_calls delta
                    tool_call_delta = [{
                        "index": event_data.get("output_index", 0),
                        "id": call_id,
                        "type": "custom",
                        "custom": {"name": name, "input": ""},
                        "namespace": item.get("namespace"),
                        "caller": item.get("caller"),
                        "item_id": item.get("id", ""),
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

    async def get_response(self, upstream_response_id: str, model: str) -> ChatResponse:
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
            response = await (await self._http()).get(url, headers=self.get_headers())

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
            return await self.aparse_response(response.json(), model)

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
