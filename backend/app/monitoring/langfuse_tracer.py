"""Langfuse tracer implementation."""

import logging
import threading
from typing import Any, Dict

from langfuse import propagate_attributes

from .base import BaseTracer

logger = logging.getLogger("monitoring")

_client_pool: dict[tuple, Any] = {}
_client_lock = threading.Lock()


def _get_client(config: dict):
    key = (
        config["public_key"],
        config["secret_key"],
        config.get("endpoint", "https://cloud.langfuse.com"),
    )
    if key not in _client_pool:
        with _client_lock:
            if key not in _client_pool:
                from langfuse import Langfuse

                _client_pool[key] = Langfuse(
                    public_key=config["public_key"],
                    secret_key=config["secret_key"],
                    host=config.get("endpoint", "https://cloud.langfuse.com"),
                )
    return _client_pool[key]


# ── observation type detection ──────────────────────────────────────────


def _detect_type(input_data: dict | None) -> str:
    """Infer the Langfuse observation type from the raw request payload.

    Examines the **last** message to decide:

    - ``"tool"`` — the last message is a tool result (role="tool" or
      content block type="tool_result")
    - ``"generation"`` — everything else
    """
    if not input_data:
        return "generation"

    # ── /v1/responses uses "input" instead of "messages" ──────────────
    messages = input_data.get("messages") or input_data.get("input") or []
    if not messages:
        return "generation"

    last = messages[-1] if messages else {}
    if not isinstance(last, dict):
        return "generation"

    # ── OpenAI /v1/chat/completions: role="tool" ──────────────────────
    role = last.get("role", "")
    if role == "tool":
        return "tool"

    # ── Anthropic /v1/messages: content blocks ────────────────────────
    content = last.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return "tool"

    # ── OpenAI /v1/responses: "type" field on input items ─────────────
    if last.get("type") == "function_call_output":
        return "tool"

    return "generation"


def _extract_tool_name(input_data: dict | None) -> str:
    """Extract the tool name matching the last tool-result message.

    Walks backward from the last message to find the assistant message
    whose ``tool_calls`` / ``tool_use`` block references the same id as
    the final tool result.  Supports both OpenAI and Anthropic shapes.
    """
    if not input_data:
        return "unknown"

    messages = input_data.get("messages") or input_data.get("input") or []
    if len(messages) < 2:
        return "unknown"

    last = messages[-1]
    if not isinstance(last, dict):
        return "unknown"

    # ── Determine the target tool-call id from the last message ─────────
    target_id: str | None = None

    # OpenAI /v1/chat/completions: role="tool" → tool_call_id
    if last.get("role") == "tool":
        target_id = last.get("tool_call_id")

    # Anthropic /v1/messages: last user msg with tool_result block
    elif isinstance(last.get("content"), list):
        for block in last["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                target_id = block.get("tool_use_id")
                break

    # OpenAI /v1/responses: function_call_output items
    if not target_id:
        target_id = last.get("call_id")

    if not target_id:
        return "unknown"

    # ── Walk backward to find the matching tool definition ──────────────
    for msg in reversed(messages[:-1]):
        if not isinstance(msg, dict):
            continue

        # OpenAI /v1/chat/completions: assistant msg with tool_calls
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict) and tc.get("id") == target_id:
                    fn = tc.get("function", {})
                    return fn.get("name", "unknown")

        # Anthropic /v1/messages: assistant msg with tool_use blocks
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == target_id:
                    return block.get("name", "unknown")

    return "unknown"


def _derive_model_prefix(model_name: str) -> str:
    """Return the provider prefix from a model name.

    ``"claude-sonnet-4-6"`` → ``"claude"``
    ``"gemini-2.5-pro"`` → ``"gemini"``
    ``"kimi-k2"`` → ``"kimi"``
    """
    return model_name.split("-")[0]


def _derive_trace_name(
    name: str,
    input_data: dict | None,
    obs_type: str,
    provider_type: str = "",
) -> str:
    """Build a structured trace name from the observation type.

    * generation → ``"generation-{provider_type}-{model_prefix}"``
      (e.g. ``generation-bailian-qwen``)
    * tool       → ``"tool-{toolname}"``
    """
    if obs_type == "tool":
        tool_name = _extract_tool_name(input_data)
        return f"tool-{tool_name}"
    parts = ["generation"]
    if provider_type:
        parts.append(provider_type)
    parts.append(_derive_model_prefix(name))
    return "-".join(parts)


# ── child span ───────────────────────────────────────────────────────────


class ChildSpan:
    """Lightweight handle for a nested child observation.

    Created by ``LangfuseTracer.start_child()``, this wraps a Langfuse
    observation that is nested under the parent gateway span.

    Supports arbitrary nesting: a ChildSpan can create its own child spans
    via ``start_child()``, forming a tree of observations.
    """

    def __init__(self, observation: Any, client: Any = None):
        self._obs = observation
        self._client = client

    def start_child(self, name: str, model: str | None = None, provider_type: str = "", input_data: dict | None = None, obs_type: str | None = None) -> "ChildSpan | None":
        """Create a child observation nested under this span."""
        if self._obs is None or self._client is None:
            return None
        try:
            from langfuse.types import TraceContext

            if obs_type:
                _type = obs_type
            else:
                _type = _detect_type(input_data) if input_data else "generation"
            trace_name = _derive_trace_name(name, input_data, _type, provider_type)
            child = self._client.start_observation(
                name=trace_name,
                as_type=_type,
                model=model or name,
                trace_context=TraceContext(
                    trace_id=self._obs.trace_id,
                    parent_span_id=self._obs.id,
                ),
            )
            return ChildSpan(child, client=self._client)
        except Exception as e:
            logger.warning(f"[langfuse] Failed to start child span: {e}")
            return None

    def log_input(self, data: dict) -> None:
        if self._obs is not None:
            try:
                self._obs.update(input=data)
            except Exception:
                pass

    def log_output(self, data: dict) -> None:
        if self._obs is not None:
            try:
                self._obs.update(output=data)
            except Exception:
                pass

    def end(self, error: Exception | None = None) -> None:
        if self._obs is not None:
            try:
                if error is not None:
                    self._obs.update(level="ERROR", status_message=str(error))
                self._obs.end()
            except Exception:
                pass


# ── tracer ──────────────────────────────────────────────────────────────


class LangfuseTracer(BaseTracer):
    """Langfuse-based tracer using the langfuse Python SDK v4.x.

    Each instance manages one generation observation for a single request.
    The underlying Langfuse client is shared across requests.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._client = None
        self._generation = None

    def start(self, name: str, input_data: Dict[str, Any] | None = None, session_id: str | None = None) -> None:
        obs_type = _detect_type(input_data)
        trace_name = _derive_trace_name(name, input_data, obs_type)
        try:
            self._client = _get_client(self.config)
            if session_id:
                with propagate_attributes(session_id=session_id):
                    self._generation = self._client.start_observation(
                        name=trace_name,
                        as_type=obs_type,
                        model=name,
                    )
            else:
                self._generation = self._client.start_observation(
                    name=trace_name,
                    as_type=obs_type,
                    model=name,
                )
        except Exception as e:
            logger.warning(f"[langfuse] Failed to start {obs_type}: {e}")
            self._generation = None

    def start_child(self, name: str, model: str | None = None, provider_type: str = "", input_data: dict | None = None, obs_type: str | None = None) -> ChildSpan | None:
        """Create a child observation nested under the current gateway span.

        *name* and *model* are used to derive the model prefix for the trace
        name.  *provider_type* is inserted into the name for generation-type
        spans (e.g. ``generation-bailian-qwen``).  *input_data* is used to
        detect the observation type (``_detect_type``) and to extract the
        tool name for tool-type spans.

        *obs_type* overrides the auto-detected observation type.  Pass
        ``"span"`` for generic spans that don't fit generation/tool.

        Returns a ``ChildSpan`` handle, or ``None`` when the parent
        observation was never started successfully.
        """
        if self._generation is None or self._client is None:
            return None
        try:
            from langfuse.types import TraceContext

            if obs_type:
                _type = obs_type
            else:
                _type = _detect_type(input_data) if input_data else "generation"
            trace_name = _derive_trace_name(name, input_data, _type, provider_type)
            child = self._client.start_observation(
                name=trace_name,
                as_type=_type,
                model=model or name,
                trace_context=TraceContext(
                    trace_id=self._generation.trace_id,
                    parent_span_id=self._generation.id,
                ),
            )
            return ChildSpan(child, client=self._client)
        except Exception as e:
            logger.warning(f"[langfuse] Failed to start child span: {e}")
            return None

    def log_input(self, data: Dict[str, Any]) -> None:
        if self._generation is not None:
            try:
                self._generation.update(input=data)
            except Exception as e:
                logger.warning(f"[langfuse] Failed to log input: {e}")

    def log_output(self, data: Dict[str, Any]) -> None:
        if self._generation is not None:
            try:
                if isinstance(data, dict) and "usage" in data:
                    usage = data.get("usage") or {}
                    self._generation.update(
                        output=data,
                        usage_details={
                            "input": usage.get("prompt_tokens", 0) or 0,
                            "output": usage.get("completion_tokens", 0) or 0,
                        },
                    )
                else:
                    self._generation.update(output=data)
            except Exception as e:
                logger.warning(f"[langfuse] Failed to log output: {e}")

    def set_metadata(self, metadata: Dict[str, Any]) -> None:
        if self._generation is not None:
            try:
                self._generation.update(metadata=metadata)
            except Exception as e:
                logger.warning(f"[langfuse] Failed to set metadata: {e}")

    def end(self, error: Exception | None = None) -> None:
        try:
            if self._generation is not None:
                if error is not None:
                    self._generation.update(
                        level="ERROR",
                        status_message=str(error),
                    )
                self._generation.end()
            if self._client is not None:
                self._client.flush()
        except Exception as e:
            logger.warning(f"[langfuse] Failed to end generation: {e}")
