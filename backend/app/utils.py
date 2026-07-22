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
# Internal reasoning_effort levels used across adapters and providers.
# Values: none, minimal, low, medium, high, xhigh, max
# These are the canonical set — provider-specific effort scales (e.g. Anthropic's
# max, OpenAI's xhigh) map into this set via to_internal_effort().
REASONING_EFFORT_NONE = 'none'
REASONING_EFFORT_MINIMAL = 'minimal'
REASONING_EFFORT_LOW = 'low'
REASONING_EFFORT_MEDIUM = 'medium'
REASONING_EFFORT_HIGH = 'high'
REASONING_EFFORT_XHIGH = 'xhigh'
REASONING_EFFORT_MAX = 'max'

# Default reasoning_effort applied when the model name contains "thinking"
# but no explicit reasoning_effort / thinking parameter was provided.
REASONING_EFFORT_DEFAULT_FOR_THINKING = REASONING_EFFORT_MEDIUM

# ── Anthropic effort ↔ internal reasoning_effort mapping ──────────────────────
# Anthropic API effort scale: low, medium, high, xhigh, max
# Internal scale:            none, minimal, low, medium, high, xhigh
#
# The mapping shifts Anthropic levels down by one because the Anthropic scale
# is shifted upward relative to the internal/OAI-compatible scale:
#   Anthropic low    → internal minimal
#   Anthropic medium → internal low
#   Anthropic high   → internal medium
#   Anthropic xhigh  → internal high
#   Anthropic max    → internal xhigh

_ANTHROPIC_TO_INTERNAL: dict[str, str] = {
    'low': REASONING_EFFORT_MINIMAL,
    'medium': REASONING_EFFORT_LOW,
    'high': REASONING_EFFORT_MEDIUM,
    'xhigh': REASONING_EFFORT_HIGH,
    'max': REASONING_EFFORT_XHIGH,
}

_INTERNAL_TO_ANTHROPIC: dict[str, str] = {
    REASONING_EFFORT_MINIMAL: 'low',
    REASONING_EFFORT_LOW: 'medium',
    REASONING_EFFORT_MEDIUM: 'high',
    REASONING_EFFORT_HIGH: 'xhigh',
    REASONING_EFFORT_XHIGH: 'max',
    REASONING_EFFORT_MAX: 'max',  # Anthropic has no level above max; cap at max
}


def to_internal_effort(provider_effort: str) -> str | None:
    """Convert a provider-specific effort string (e.g. Anthropic) to an internal
    REASONING_EFFORT_* constant. Returns None for unrecognised values."""
    return _ANTHROPIC_TO_INTERNAL.get(provider_effort)


def to_anthropic_effort(internal_effort: str) -> str:
    """Convert an internal REASONING_EFFORT_* value to an Anthropic effort string."""
    return _INTERNAL_TO_ANTHROPIC.get(internal_effort, 'medium')


# ── OpenAI/internal effort ↔ Volcengine Doubao effort mapping ──────────────
# Doubao scale (responses /v3/responses):     minimal, low, medium, high, max
# Doubao scale (chat/completions /v3/chat):   minimal, low, medium, high, xhigh, max
#
# IMPORTANT: Doubao "minimal" DISABLES thinking — this is incompatible with the
# OpenAI Responses API where "minimal" is a genuine (low) effort level. To stay
# compatible, OpenAI "none" maps to Doubao "minimal" (i.e. thinking off), and the
# OpenAI levels that DO want thinking are shifted so they never hit "minimal":
#   openai none      → minimal  (thinking OFF)
#   openai minimal   → low
#   openai low       → low
#   openai medium    → medium   (and up: identity)
#   openai high      → high
#   openai xhigh     → xhigh    (chat/completions only)
#   openai max       → max
# Doubao also requires the `thinking` switch enabled to actually return thinking
# content; see VolcengineProvider._resolve_doubao_reasoning.

_INTERNAL_TO_VOLCENGINE: dict[str, str] = {
    REASONING_EFFORT_NONE: 'minimal',
    REASONING_EFFORT_MINIMAL: 'low',
    REASONING_EFFORT_LOW: 'low',
    REASONING_EFFORT_MEDIUM: 'medium',
    REASONING_EFFORT_HIGH: 'high',
    REASONING_EFFORT_XHIGH: 'xhigh',
    REASONING_EFFORT_MAX: 'max',
}


def to_volcengine_effort(internal_effort: str, *, allow_xhigh: bool = True) -> str:
    """Map an internal/OpenAI reasoning_effort to a Volcengine Doubao effort.

    Args:
        internal_effort: one of the REASONING_EFFORT_* constants.
        allow_xhigh: when False (Doubao /v3/responses, which has no xhigh),
            xhigh is clamped down to high. chat/completions accepts xhigh.
    """
    mapped = _INTERNAL_TO_VOLCENGINE.get(internal_effort, 'medium')
    if mapped == 'xhigh' and not allow_xhigh:
        return 'high'
    return mapped


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
