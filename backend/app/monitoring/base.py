"""Abstract base class for monitoring/tracing backends."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTracer(ABC):
    """Abstract tracer for observability backends (Langfuse, LangSmith, etc.).

    Lifecycle::

        tracer = create_tracer(config)
        if tracer:
            tracer.start(name="...")
            tracer.log_input({...})
            # ... do work ...
            tracer.log_output({...})
            tracer.end()
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def start(self, name: str, input_data: Dict[str, Any] | None = None, session_id: str | None = None) -> None:
        """Start a generation span. Called before the provider call.

        Args:
            name: Span name (typically the model name).
            input_data: Raw request payload, used to infer the observation type
                        (generation, tool, agent, etc.).
            session_id: Optional session ID for grouping traces into conversations.
        """
        ...

    @abstractmethod
    def log_input(self, data: Dict[str, Any]) -> None:
        """Log the request input (model, messages, parameters)."""
        ...

    @abstractmethod
    def log_output(self, data: Dict[str, Any]) -> None:
        """Log the response output (content, token usage)."""
        ...

    @abstractmethod
    def set_metadata(self, metadata: Dict[str, Any]) -> None:
        """Attach arbitrary metadata to the current span."""
        ...

    @abstractmethod
    def end(self, error: Exception | None = None) -> None:
        """End the generation span. If *error* is not None, record the error.

        Must call ``flush()`` to ensure data is sent.
        """
        ...

    @abstractmethod
    def start_child(self, name: str, model: str | None = None, provider_type: str = "", input_data: dict | None = None, obs_type: str | None = None) -> Any:
        """Create a child observation nested under the current span.

        Args:
            name: Span name.
            model: Model name (for generation-type spans).
            provider_type: Provider type string (e.g. "volcengine").
            input_data: Raw request payload, used to auto-detect obs_type
                        when obs_type is not explicitly provided.
            obs_type: Override the observation type (e.g. "span", "generation",
                      "tool"). When None, the type is inferred from input_data.

        Returns a child-span handle (implementation-specific) or None if
        the parent span was never started.
        """
        ...
