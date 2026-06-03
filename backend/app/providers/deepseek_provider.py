"""
DeepSeek 供应商实现 (DeepSeek Provider)
实现 DeepSeek AI 模型的 API 调用。

DeepSeek API 采用 OpenAI 兼容格式，继承 OpenAIProvider 复用代码。
DeepSeek API 文档: https://api-docs.deepseek.com/
"""
from typing import Optional, List, Dict, Any, AsyncGenerator
import logging
import time

from .openai_provider import OpenAIProvider
from .base import ProviderConfig, ProviderCapability
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType

logger = logging.getLogger(__name__)


class DeepSeekProvider(OpenAIProvider):
    """
    DeepSeek 供应商实现

    DeepSeek 提供 DeepSeek-V3、DeepSeek-R1 等大模型服务。
    其 API 与 OpenAI 兼容，可直接复用 OpenAI 的请求/响应处理逻辑。
    """

    PROVIDER_TYPE: str = "deepseek"

    # DeepSeek 支持的能力
    CAPABILITIES: List[ProviderCapability] = [
        ProviderCapability.CHAT,
        ProviderCapability.STREAMING,
        ProviderCapability.TOOLS,
        ProviderCapability.CACHE,
    ]

    # 默认 API 基础 URL
    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"

    # DeepSeek 支持的模型列表
    SUPPORTED_MODELS = {
        "deepseek-chat": {
            "description": "DeepSeek V3 - 通用大语言模型",
            "context_size": 128000,
            "supports_vision": False,
        },
        "deepseek-reasoner": {
            "description": "DeepSeek R1 - 推理模型",
            "context_size": 128000,
            "supports_vision": False,
        },
        "deepseek-v4-pro": {
            "description": "DeepSeek V4 Pro - 旗舰级大语言模型",
            "context_size": 1000000,
            "supports_vision": False,
        },
        "deepseek-v4-flash": {
            "description": "DeepSeek V4 Flash - 极速大语言模型",
            "context_size": 1000000,
            "supports_vision": False,
        },
    }

    def __init__(self, config: ProviderConfig):
        """
        初始化 DeepSeek 供应商

        Args:
            config: 供应商配置
        """
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL

        super().__init__(config)

    def prepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        准备请求数据

        复用 OpenAI 格式，添加 DeepSeek 特有的参数处理。
        """
        # When the system prompt indicates AI coding agent usage, force
        # reasoning to the highest available effort level.
        system_text = request.get_system_message()
        if system_text and not request.reasoning_effort:
            if any(kw in system_text for kw in ("Claude Code", "OpenCode", "Codex", "Cline")):
                request.reasoning_effort = 'max'

        # DeepSeek 要求 tool 消息必须紧跟在 assistant(tool_calls) 之后，
        # 中间不能有其他消息类型（如另一个 assistant 消息）。
        # 对消息列表进行重排，确保满足此约束。
        self._reorder_tool_messages(request.messages)

        result = super().prepare_request(request)

        # DeepSeek 特有：根据模型是否支持思维和 reasoning_effort 设置 thinking 参数
        if request.metadata.get('support_thinking', False):
            reasoning_effort = request.reasoning_effort or 'none'
            if reasoning_effort != 'none':
                result["thinking"] = {"type": "enabled"}
            else:
                result["thinking"] = {"type": "disabled"}
        return result

    @staticmethod
    def _reorder_tool_messages(messages: list) -> None:
        """重排消息列表，确保 tool 消息紧跟在对应的 assistant(tool_calls) 之后。

        DeepSeek / Bailian 等严格实现的 Chat Completions API 要求：
        assistant(tool_calls) 之后必须紧跟 tool 消息响应每个 tool_call_id，
        中间不能插入其他 assistant 或 user 消息。

        例如：
            [assistant(tool_calls=[A]), assistant(text), tool(A)]
            → [assistant(tool_calls=[A]), tool(A), assistant(text)]

        此方法原地修改消息列表。
        """
        if len(messages) < 2:
            return

        pending_call_ids = None       # 当前 tool_calls 的 call_id 集合
        non_tool_start = None         # 第一个待延迟的非 tool 消息的索引
        tool_indices_to_move = []     # 需要移动到前面的 tool 消息索引

        def _flush():
            """提交当前轮次的重排。"""
            nonlocal non_tool_start, tool_indices_to_move
            if non_tool_start is not None and tool_indices_to_move:
                _apply_reorder(messages, non_tool_start, tool_indices_to_move)
            non_tool_start = None
            tool_indices_to_move = []

        i = 0
        while i < len(messages):
            msg = messages[i]

            # 提取消息中的 tool_call_ids
            msg_call_ids = set()
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ContentBlock) and block.type == ContentType.TOOL_CALL:
                        if block.tool_call_id:
                            msg_call_ids.add(block.tool_call_id)

            if msg_call_ids:
                # 遇到新的 assistant(tool_calls)，提交上一轮的重排
                _flush()
                pending_call_ids = msg_call_ids
                i += 1

            elif pending_call_ids and msg.role == MessageRole.TOOL and msg.tool_call_id in pending_call_ids:
                # 匹配的 tool 消息，记录其位置（稍后移到 non_tool_start 之前）
                tool_indices_to_move.append(i)
                pending_call_ids.discard(msg.tool_call_id)
                i += 1

            elif pending_call_ids:
                # 在等待 tool 响应期间遇到了非 tool 消息
                if non_tool_start is None:
                    non_tool_start = i
                i += 1

            else:
                i += 1

        # 最后一轮重排
        _flush()


def _apply_reorder(messages: list, insert_at: int, tool_indices: list) -> None:
    """将 tool_indices 位置的 tool 消息移动到 insert_at 位置，原地修改列表。

    例如 messages=[A, B(assistant), C(tool)], insert_at=1, tool_indices=[2]
    → [A, C(tool), B(assistant)]
    """
    # 从后往前提取，保持索引有效
    extracted = []
    for idx in reversed(tool_indices):
        extracted.append(messages.pop(idx))
    extracted.reverse()

    # 按原顺序插入到目标位置
    for tool_msg in extracted:
        messages.insert(insert_at, tool_msg)
        insert_at += 1

    async def aprepare_request(self, request: ChatRequest) -> Dict[str, Any]:
        """
        异步请求准备 — 在调用同步 prepare_request 之前，若本轮包含 tool_result
        且最近一条 assistant 消息缺失 reasoning_content，则从数据库按上一轮
        最后一个 tool_call_id 反查并回填到该 assistant 消息上。
        """
        await self._maybe_inject_saved_thinking(request)
        return self.prepare_request(request)

    async def _maybe_inject_saved_thinking(self, request: ChatRequest) -> None:
        """对每一个包含 tool_calls 的 assistant 消息:
          - 若用户已带上 reasoning_content（非 None）→ 跳过
          - 否则按该消息的最后一个 tool_call_id 查 DB:
              命中 → 回填 reasoning_content
              未命中 → 强制设为空串 ""（避免上游因缺字段拒绝）
        """
        messages = request.messages or []
        if not messages:
            return

        from app.thinking_record_dao import get_thinking

        for assistant_msg in messages:
            if assistant_msg.role != MessageRole.ASSISTANT:
                continue

            tool_call_ids: List[str] = []
            if isinstance(assistant_msg.content, list):
                for block in assistant_msg.content:
                    if isinstance(block, ContentBlock) and block.type == ContentType.TOOL_CALL and block.tool_call_id:
                        tool_call_ids.append(block.tool_call_id)
            if not tool_call_ids:
                continue

            # 用户已带上 reasoning_content 则跳过（None 才视为未带）
            if assistant_msg.reasoning_content is not None:
                continue

            last_tool_call_id = tool_call_ids[-1]
            content = ""
            try:
                record = await get_thinking(last_tool_call_id)
                if record and record.get("thinking_content"):
                    content = record["thinking_content"]
            except Exception as exc:
                logger.warning("[deepseek] inject thinking lookup failed: %s", exc)

            assistant_msg.reasoning_content = content

    def _message_to_openai(self, message: Message) -> Dict[str, Any]:
        """DeepSeek 特化:允许 reasoning_content="" 透传(基类用 truthy 判断会丢失空串)。

        空串场景:assistant 含 tool_calls 且未命中数据库时,由
        _maybe_inject_saved_thinking 设为 "",此处补上字段。
        """
        result = super()._message_to_openai(message)
        if (
            message.reasoning_content == ""
            and "reasoning_content" not in result
        ):
            result["reasoning_content"] = ""
        return result

    def parse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """
        解析 DeepSeek 响应数据

        复用 OpenAI 格式解析，处理 DeepSeek 特有的 reasoning_content 字段。
        """
        response = super().parse_response(response_data, model)
        response.provider = self.PROVIDER_TYPE

        # 处理 DeepSeek 的 reasoning_content（思考过程）
        for i, choice_data in enumerate(response_data.get("choices", [])):
            message_data = choice_data.get("message", {})
            if "reasoning_content" in message_data:
                response.choices[i].reasoning_content = message_data["reasoning_content"]

        return response

    async def aparse_response(self, response_data: Dict[str, Any], model: str) -> ChatResponse:
        """异步解析响应 — 解析完成后持久化 reasoning_content + 最后一个 tool_call_id。"""
        response = self.parse_response(response_data, model)
        await self._maybe_persist_from_response(response_data)
        return response

    async def _maybe_persist_from_response(self, response_data: Dict[str, Any]) -> None:
        """从原始非流式响应中提取 reasoning_content + 最后一个 tool_call_id，写入数据库。"""
        try:
            choices = response_data.get("choices") or []
            if not choices:
                return
            message_data = choices[0].get("message") or {}
            reasoning = message_data.get("reasoning_content")
            tool_calls = message_data.get("tool_calls") or []
            if not reasoning or not tool_calls:
                return
            last_id = tool_calls[-1].get("id")
            if not last_id:
                return
            from app.thinking_record_dao import save_thinking
            await save_thinking(last_id, reasoning)
        except Exception as exc:
            logger.warning("[deepseek] persist thinking from response failed: %s", exc)

    def _parse_stream_chunk(self, data: Dict[str, Any], response_id: str, model: str) -> Optional[StreamChunk]:
        """
        解析流式响应块

        复用 OpenAI 格式，处理 DeepSeek 特有的 reasoning_content 字段。
        """
        chunk = super()._parse_stream_chunk(data, response_id, model)

        if chunk:
            # 处理 DeepSeek 的 reasoning_content（思考过程）
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "reasoning_content" in delta:
                    chunk.delta_reasoning_content = delta["reasoning_content"]

        return chunk

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """流式对话 — 在基类流的基础上累积 reasoning_content 与 tool_call_id，
        流结束时持久化思考内容。"""
        reasoning_parts: List[str] = []
        # tool_calls 在 delta 中按 index 分片增量到来，这里只关心最后出现的 id
        tool_ids_by_index: Dict[int, str] = {}

        async for chunk in super().stream_chat(request):
            if chunk is not None:
                if chunk.delta_reasoning_content:
                    reasoning_parts.append(chunk.delta_reasoning_content)
                for tc in (chunk.tool_calls or []):
                    if not isinstance(tc, dict):
                        continue
                    idx = tc.get("index", 0) or 0
                    tc_id = tc.get("id")
                    if tc_id:
                        tool_ids_by_index[idx] = tc_id
            yield chunk

        if reasoning_parts and tool_ids_by_index:
            last_index = max(tool_ids_by_index.keys())
            last_id = tool_ids_by_index.get(last_index)
            if last_id:
                try:
                    from app.thinking_record_dao import save_thinking
                    await save_thinking(last_id, "".join(reasoning_parts))
                except Exception as exc:
                    logger.warning("[deepseek] persist thinking from stream failed: %s", exc)

    def list_models(self) -> List[Dict[str, Any]]:
        """列出可用模型"""
        models = []
        for model_name, info in self.SUPPORTED_MODELS.items():
            models.append({
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "deepseek",
                "description": info.get("description", ""),
                "context_size": info.get("context_size", 128000),
                "supports_vision": info.get("supports_vision", False),
            })
        return models
