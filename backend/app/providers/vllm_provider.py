"""
vLLM 供应商实现 (vLLM Provider)

vLLM 暴露与 OpenAI Chat Completions 兼容的 REST API，因此本实现直接
继承 OpenAIProvider 并只覆盖必要的配置项：

- PROVIDER_TYPE  →  "vllm"
- DEFAULT_BASE_URL → "http://localhost:8000/v1"（本地部署的默认地址）
- API key 可选   → vLLM 默认不启用认证，api_key 留空时跳过 Authorization 头
- stream_options → 部分旧版 vLLM 不支持 include_usage；遇到错误时
                   自动降级（不要求 usage chunk）

典型部署示例
-----------
    vllm serve Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0 --port 8000

配置时将 Base URL 填写为 http://<host>:8000/v1 即可。
"""
import logging
from typing import Generator, Dict, Any, List, Optional
import time

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk, StreamEventType
from app.abstraction.chat import FinishReason
from app.abstraction.messages import Message, MessageRole


class VLLMProvider(OpenAIProvider):
    """
    vLLM 供应商实现。

    vLLM 兼容 OpenAI /v1/chat/completions 接口，大多数行为与 OpenAIProvider
    完全一致。本类的主要定制点：

    1. ``PROVIDER_TYPE = "vllm"``  — 注册标识符
    2. ``DEFAULT_BASE_URL``       — 指向本地 vLLM 默认监听地址
    3. API key 可选               — vLLM 无鉴权时 api_key 可留空
    4. ``stream_options``         — 早期 vLLM 不支持 ``include_usage``；
                                   本实现先尝试带 usage，出错时回退
    """

    PROVIDER_TYPE: str = "vllm"

    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.VISION,
    ]

    # vLLM 默认在本地 8000 端口监听
    DEFAULT_BASE_URL = "http://localhost:8000/v1"

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        # 调用祖父类（BaseProvider）而非 OpenAIProvider，
        # 避免 OpenAIProvider.__init__ 重复设置 base_url
        super().__init__(config)

    def get_headers(self) -> Dict[str, str]:
        """
        构建请求头。

        vLLM 不强制要求 API key；当 api_key 为空时省略 Authorization 头，
        避免某些 vLLM 部署因收到意外的 ``Authorization: Bearer `` 而报错。
        """
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据。

        继承 OpenAIProvider 的转换逻辑，并进行 vLLM 特有的调整：
        - 移除 ``reasoning_effort``：vLLM 不支持该参数
        - 添加 ``chat_template_kwargs.enable_thinking``：当设置了
          reasoning_effort 或模型名包含 "thinking" 时开启思考模式
        """
        # 在调用 super() 之前保存 reasoning_effort，因为后续要用它判断是否开启 thinking
        has_reasoning = bool(
            request.reasoning_effort and request.reasoning_effort != 'none'
        )
        has_thinking_model = "thinking" in request.model.lower()

        data = super().prepare_request(request)

        # 移除 OpenAI 特有的 reasoning_effort（vLLM 不支持）
        data.pop("reasoning_effort", None)

        # 当设置了 reasoning_effort 或模型名包含 "thinking" 时，
        # 添加 chat_template_kwargs.enable_thinking = true
        if has_reasoning or has_thinking_model:
            chat_template_kwargs = data.get("chat_template_kwargs", {})
            chat_template_kwargs["enable_thinking"] = True
            data["chat_template_kwargs"] = chat_template_kwargs
        logging.debug(f"Prepared vLLM request data: {data}")

        return data

    def stream_chat(self, request: ChatRequest) -> Generator[StreamChunk, None, None]:
        """
        执行流式对话请求。

        先尝试带 ``stream_options.include_usage`` 的请求（新版 vLLM 支持），
        若服务端返回 400/422 错误则回退到不带该选项的普通流式请求。
        """
        import json
        import uuid
        import time

        error = self.validate_request(request)
        if error:
            raise ValueError(error)

        request_data = self.prepare_request(request)
        request_data["stream"] = True
        request_data["stream_options"] = {"include_usage": True}

        url = f"{self.config.base_url}/chat/completions"
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        def _do_stream(req_data: Dict[str, Any]) -> Generator[StreamChunk, None, None]:
            with self._trace_call(request.model, input_data=request_data), \
                 self.client.stream("POST", url, json=req_data) as response:
                if response.status_code in (400, 422):
                    error_text = ""
                    for chunk in response.iter_bytes():
                        if chunk:
                            error_text += chunk.decode("utf-8")
                    raise _StreamOptionsNotSupported(error_text, response.status_code)

                if response.status_code >= 400:
                    error_text = ""
                    for chunk in response.iter_bytes():
                        if chunk:
                            error_text += chunk.decode("utf-8")
                    try:
                        error_data = json.loads(error_text)
                        raise RuntimeError(
                            f"vLLM API error ({response.status_code}): "
                            f"{json.dumps(error_data, ensure_ascii=False)}"
                        )
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"vLLM API error ({response.status_code}): {error_text}"
                        )

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
                        except json.JSONDecodeError as err:
                            continue

        try:
            yield from _do_stream(request_data)
        except _StreamOptionsNotSupported:
            # 回退：移除 stream_options 再试
            fallback_data = dict(request_data)
            fallback_data.pop("stream_options", None)
            try:
                yield from _do_stream(fallback_data)
            except _StreamOptionsNotSupported as e:
                raise RuntimeError(f"vLLM streaming API error: {e.message}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"vLLM streaming API error: {str(e)}")

    # ----------------------------------------------------------------
    # vLLM reasoning field mapping
    # ----------------------------------------------------------------
    # vLLM uses "reasoning" in the delta instead of "reasoning_content"
    # (which is used by DeepSeek/OpenAI). We override the stream chunk
    # parser and message parser to handle this difference.

    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """
        解析流式响应块。

        覆盖 OpenAIProvider 实现，增加对 vLLM ``reasoning`` 字段的支持。
        vLLM 使用 ``delta.reasoning`` 而非 ``delta.reasoning_content``
        来传递推理内容。
        """
        choices = data.get("choices", [])
        usage = data.get("usage")

        if not choices:
            if usage:
                return StreamChunk(
                    id=data.get("id", response_id),
                    model=data.get("model", model),
                    usage=usage,
                    event_type=StreamEventType.USAGE,
                    created=data.get("created", int(time.time()))
                )
            return None

        choice = choices[0]
        delta = choice.get("delta", {})

        content = delta.get("content")
        role = delta.get("role")

        # vLLM uses "reasoning" instead of "reasoning_content"
        reasoning_content = delta.get("reasoning_content") or delta.get("reasoning")

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
            delta_reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            created=data.get("created", int(time.time()))
        )

    def _parse_message(self, data: Dict[str, Any]) -> Message:
        """
        从 vLLM 格式解析 Message。

        覆盖 OpenAIProvider 实现，增加对 vLLM ``reasoning`` 字段的支持。
        vLLM 使用 ``message.reasoning`` 而非 ``message.reasoning_content``。
        """
        # Let the parent handle the main parsing
        message = super()._parse_message(data)

        # If reasoning_content wasn't set by parent (which reads "reasoning_content"),
        # check for vLLM's "reasoning" field
        if not message.reasoning_content:
            reasoning = data.get("reasoning")
            if reasoning:
                message.reasoning_content = reasoning

        return message

    def supports_model(self, model: str) -> bool:
        """vLLM 支持任意部署的模型，始终返回 True。"""
        return True

    def get_model_info(self, model: str) -> Optional[Dict[str, Any]]:
        """返回通用模型信息占位。"""
        return {
            "description": f"vLLM model: {model}",
            "context_size": 8192,
            "supports_vision": False,
        }


class _StreamOptionsNotSupported(Exception):
    """内部异常：服务端不支持 stream_options，需要回退。"""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
