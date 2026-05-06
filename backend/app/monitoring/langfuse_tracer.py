"""Langfuse tracer implementation."""

import logging
import threading
from typing import Any, Dict

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

    def start(self, name: str, input_data: Dict[str, Any] | None = None) -> None:
        obs_type = _detect_type(input_data)
        try:
            self._client = _get_client(self.config)
            self._generation = self._client.start_observation(
                name=name,
                as_type=obs_type,
                model=name,
            )
        except Exception as e:
            logger.warning(f"[langfuse] Failed to start {obs_type}: {e}")
            self._generation = None

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
