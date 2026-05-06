"""
Monitoring / Observability backends.

Provides a pluggable tracer abstraction. Add new backends by implementing
:class:`BaseTracer` and registering them in ``TRACER_REGISTRY``.
"""

from .base import BaseTracer
from .langfuse_tracer import LangfuseTracer

__all__ = ["BaseTracer", "LangfuseTracer", "create_tracer"]

TRACER_REGISTRY: dict[str, type[BaseTracer]] = {
    "langfuse": LangfuseTracer,
}


def create_tracer(config: dict | None) -> BaseTracer | None:
    """Create a tracer instance from a monitoring config dict.

    Args:
        config: The ``monitoring_config`` dict from ``Group.monitoring_config``.

    Returns:
        A :class:`BaseTracer` instance, or ``None`` if *config* is ``None``.
    """
    if not config:
        return None
    tracer_type = config.get("type", "")
    if not tracer_type:
        return None
    tracer_class = TRACER_REGISTRY.get(tracer_type)
    if tracer_class is None:
        import logging
        logging.getLogger("monitoring").warning(
            f"Unknown tracer type: {tracer_type}"
        )
        return None
    return tracer_class(config)
