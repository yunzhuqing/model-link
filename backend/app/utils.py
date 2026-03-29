"""
Shared utility functions for Model Link AI Gateway.
"""
import os


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
    return f"{prefix}{os.urandom(24).hex()}"
