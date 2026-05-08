"""
Shared utility functions and constants for Model Link AI Gateway.
"""
import os
import re
import json
import logging

import demjson3

try:
    from json_repair import repair_json as _repair_json
except ImportError:  # pragma: no cover
    _repair_json = None

logger = logging.getLogger("gateway")

_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json|json5|javascript|js)?\s*\n(.*?)\n?\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)

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


def _strip_code_fence(s: str) -> str:
    m = _CODE_FENCE_RE.match(s)
    if m:
        return m.group(1)
    return s


def _extract_json_payload(s: str) -> str | None:
    """Extract the first balanced {...} or [...] from a string with surrounding noise.

    LLMs often wrap JSON with explanations like "Here is the JSON: {...}. Hope it helps."
    Returns the substring or None if no plausible payload is found. Bracket counting is
    string-aware so braces inside string literals don't unbalance the scan.
    """
    start = -1
    opener = closer = ""
    for i, ch in enumerate(s):
        if ch == "{":
            start, opener, closer = i, "{", "}"
            break
        if ch == "[":
            start, opener, closer = i, "[", "]"
            break
    if start < 0:
        return None

    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def json_loads(s: str | bytes, **kwargs):
    """Parse a JSON string, falling back to tolerant parsers for real-world LLM output.

    Strategy (cheapest to most aggressive):
      1. ``json.loads`` — strict, fast, handles well-formed input.
      2. Strip ```` ```json ``` ```` fences and surrounding prose, retry strict.
      3. ``demjson3.decode(strict=False)`` — tolerates control chars, ``\\xNN`` escapes.
      4. ``json_repair.repair_json`` — handles single quotes, unescaped quotes/newlines,
         trailing commas, truncated payloads, ``Infinity``/``NaN``/``undefined``.

    Bytes input is decoded to ``str`` once up front so all parsers see the same value.

    Raises ``json.JSONDecodeError`` only if every strategy fails.
    """
    if isinstance(s, (bytes, bytearray)):
        try:
            s = s.decode("utf-8")
        except UnicodeDecodeError:
            s = s.decode("utf-8", errors="replace")

    std_err = None
    try:
        return json.loads(s, **kwargs)
    except json.JSONDecodeError as e1:
        std_err = str(e1)

    cleaned = _strip_code_fence(s.strip())
    if cleaned != s:
        try:
            return json.loads(cleaned, **kwargs)
        except json.JSONDecodeError:
            pass

    extracted = _extract_json_payload(cleaned)
    if extracted and extracted != cleaned:
        try:
            return json.loads(extracted, **kwargs)
        except json.JSONDecodeError:
            cleaned = extracted

    demjson_err = None
    try:
        return demjson3.decode(cleaned, strict=False)
    except demjson3.JSONDecodeError as e2:
        demjson_err = str(e2)

    if _repair_json is not None:
        try:
            repaired = _repair_json(cleaned, return_objects=True)
            if repaired != "" or cleaned.strip() in ('""', "''"):
                return repaired
        except Exception as e3:  # json_repair raises various types
            repair_err = str(e3)
        else:
            repair_err = "empty result"
    else:
        repair_err = "json_repair not installed"

    logger.error(
        "json_loads failed with all parsers: std=%s demjson=%s repair=%s raw_len=%d raw=%s",
        std_err,
        demjson_err,
        repair_err,
        len(s),
        s,
    )
    raise json.JSONDecodeError(
        f"Failed to parse JSON (std={std_err}; demjson={demjson_err}; repair={repair_err})",
        s,
        0,
    )
