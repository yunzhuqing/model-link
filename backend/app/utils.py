"""
Shared utility functions and constants for Model Link AI Gateway.
"""
import os


# ── Reasoning Effort Constants ──────────────────────────────────────────────
# Standard reasoning_effort levels used across adapters and providers.
# Replaces hardcoded string values ('low', 'medium', 'high', 'none').
REASONING_EFFORT_LOW = 'low'
REASONING_EFFORT_MEDIUM = 'medium'
REASONING_EFFORT_HIGH = 'high'
REASONING_EFFORT_NONE = 'none'

# Default reasoning_effort applied when the model name contains "thinking"
# but no explicit reasoning_effort / thinking parameter was provided.
REASONING_EFFORT_DEFAULT_FOR_THINKING = REASONING_EFFORT_MEDIUM


def gen_id(prefix: str) -> str:
    """
    Generate a unique ID with the given prefix and a 48-character hex suffix.

    The format matches OpenAI's identifier style:
      resp_08a90de11516ea260069c1e8c3e01c8193a407cbeddc0316a8
      msg_08a90de11516ea260069c1e8c3e01c8193a407cbeddc0316a8
      rs_08a90de11516ea260069c1e8c3e01c8193a407cbeddc0316a8

    Args:
        prefix: The identifier prefix, e.g. ``"resp_"``, ``"msg_"``, ``"rs_"``.

    Returns:
        A string of the form ``{prefix}{48 hex chars}``.

    Example::

        >>> gen_id("resp_")
        'resp_3c80e8079c2a413c95fcba33f1df254f00846b462ca547a8'
        >>> len(gen_id("resp_")) - len("resp_")
        48
    """
    return f"{prefix}_{os.urandom(24).hex()}"
