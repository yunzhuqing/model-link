"""
Monitoring / Observability backends.

Provides a pluggable tracer abstraction. Add new backends by implementing
:class:`BaseTracer` and registering them in ``TRACER_REGISTRY``.

When *config* is a list, the tracer for the current deployment's region
(``MODEL_LINK_REGION`` env var) is selected. Falls back to the first entry
if the env var is unset or no matching region is found.
"""

import os

from .base import BaseTracer
from .langfuse_tracer import LangfuseTracer

__all__ = ["BaseTracer", "LangfuseTracer", "create_tracer"]

TRACER_REGISTRY: dict[str, type[BaseTracer]] = {
    "langfuse": LangfuseTracer,
}


def _create_single_tracer(config: dict) -> BaseTracer | None:
    """Create a single tracer instance from one config dict."""
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


def _select_config(configs: list[dict]) -> dict | None:
    """Select the config matching ``MODEL_LINK_REGION``, or the first entry."""
    if not configs:
        return None
    region = os.getenv("MODEL_LINK_REGION", "cn")
    if region:
        for cfg in configs:
            if cfg.get("region") == region:
                return cfg
    return configs[0]


def create_tracer(config: list[dict] | dict | None) -> BaseTracer | None:
    """Create a tracer from monitoring config(s).

    Args:
        config: A list of monitoring config dicts, a single legacy dict,
                or None. When a list, selects the entry whose ``region``
                matches the ``MODEL_LINK_REGION`` environment variable.
                Falls back to the first entry if unset or no match.

    Returns:
        A :class:`BaseTracer` instance, or ``None`` if *config* is None/empty.
    """
    if not config:
        return None

    if isinstance(config, dict):
        return _create_single_tracer(config)

    selected = _select_config(config)
    if selected is None:
        return None
    return _create_single_tracer(selected)