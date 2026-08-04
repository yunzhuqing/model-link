"""
Shared text-to-speech implementation for OpenAI-compatible providers.

Both ``OpenAIProvider`` (Chat Completions compatible) and
``OpenAIResponsesCompatProvider`` (Responses API compatible) expose the same
``/audio/speech`` surface, so the TTS call lives here and is delegated to by
each provider's ``speech()`` method.

The ``input`` field is polymorphic — it may be a plain string:

    {"input": "The quick brown fox..."}

or an array of content blocks (mirroring the OpenAI input/items shape) that
may include text, image, and audio parts:

    {"input": [
        {"type": "input_text",  "text": "Describe this image."},
        {"type": "input_image", "image_url": "..."},
        {"type": "input_audio", "input_audio": {"data": "...", "format": "wav"}},
    ]}

The gateway passes ``input`` through to the upstream verbatim (string or
array); the upstream decides what it accepts. Text extracted from the blocks
is used only for best-effort spoken-duration estimation.
"""
import json
from typing import Any, Dict, List, Union

from .base import UpstreamProviderError
from app.abstraction.tts import TTSResponse, AUDIO_FORMAT_MIME_TYPES, DEFAULT_AUDIO_FORMAT

# Typical English speech rate used to estimate billed audio seconds from the
# input text length. Approximate — the upstream does not report duration.
_CHARS_PER_SECOND = 14.0


def _extract_text_from_input(input_val: Union[str, List[Any], Dict[str, Any]]) -> str:
    """Recursively pull text out of a string or content-block input."""
    return parse_tts_input(input_val)["text"]


def _normalize_media(value: Any) -> Dict[str, str]:
    """
    Normalize an image/audio content value into ``{"url": ...}`` or
    ``{"data": <base64>}``. Accepts a plain string, a data URI, or a
    ``{"url": ...}`` / ``{"data": ...}`` dict.
    """
    if isinstance(value, dict):
        raw = value.get("url") or value.get("data") or value.get("base64")
    else:
        raw = value
    if not raw:
        return {}
    raw = str(raw)
    if raw.startswith(("http://", "https://")):
        return {"url": raw}
    if raw.startswith("data:"):
        # data URI: data:<mime>;base64,<...>
        b64 = raw.split(",", 1)[1] if "," in raw else raw
        return {"data": b64}
    return {"data": raw}  # assume raw base64


def parse_tts_input(input_val: Any) -> Dict[str, Any]:
    """
    Parse the universal TTS ``input`` into structured parts.

    Universal input shape (a string or an array of content blocks):

        [
            {"type": "text",      "text": "..."},
            {"type": "image_url", "image_url": {"url": "<url or base64>"}},
            {"type": "audio_url", "audio_url": {"url": "<url or base64>"}},
        ]

    Returns ``{"text": str, "audio": [...], "image": [...]}`` where each
    media entry is ``{"url": ...}`` or ``{"data": <base64>}``.
    """
    result: Dict[str, Any] = {"text": "", "audio": [], "image": []}
    if input_val is None:
        return result
    if isinstance(input_val, str):
        result["text"] = input_val
        return result

    items: List[Any] = input_val if isinstance(input_val, list) else [input_val]
    text_parts: List[str] = []
    for item in items:
        if isinstance(item, str):
            text_parts.append(item)
            continue
        if not isinstance(item, dict):
            continue

        btype = item.get("type", "")
        # Text block (OpenAI: "text"; Responses API: "input_text"; output_text).
        if btype in ("text", "input_text", "output_text") or "text" in item:
            txt = item.get("text") or item.get("input_text") or item.get("output_text")
            if txt:
                text_parts.append(str(txt))
            continue

        # Audio block.
        audio = item.get("audio_url") or item.get("input_audio") or item.get("audio")
        if audio is not None:
            norm = _normalize_media(audio)
            if norm:
                result["audio"].append(norm)
            continue

        # Image block.
        image = item.get("image_url") or item.get("input_image") or item.get("image")
        if image is not None:
            norm = _normalize_media(image)
            if norm:
                result["image"].append(norm)
            continue

        # Nested content (e.g. a message-shaped item with a "content" array).
        if "content" in item:
            sub = parse_tts_input(item["content"])
            if sub["text"]:
                text_parts.append(sub["text"])
            result["audio"].extend(sub["audio"])
            result["image"].extend(sub["image"])

    result["text"] = " ".join(p for p in text_parts if p)
    return result


async def openai_speech(provider, request) -> TTSResponse:
    """
    POST ``{base_url}/audio/speech`` and return the raw audio bytes.

    ``provider`` is duck-typed: it must expose ``config`` (with ``base_url``),
    ``get_headers()``, and ``_http()`` — i.e. any ``BaseProvider`` subclass.
    """
    # OpenAI's /audio/speech requires a voice (unlike seed_tts, where the
    # speaker comes from reference audio). Enforce it here, at the provider
    # boundary, not at the gateway route — voice is optional for other TTS
    # providers.
    if not request.voice:
        raise UpstreamProviderError(
            "Voice is required for this provider's text-to-speech",
            status_code=400,
            error_type="invalid_request",
        )

    request_data: Dict[str, Any] = {
        "model": request.model,
        # OpenAI's /audio/speech only accepts a text string. The universal
        # input may be a string or a content-block array (text/image_url/
        # audio_url); extract and concatenate the text parts. Image/audio
        # blocks are ignored here — OpenAI TTS cannot consume them.
        "input": _extract_text_from_input(request.input),
        "voice": request.voice,
    }

    fmt = (request.response_format or DEFAULT_AUDIO_FORMAT).lower()
    request_data["response_format"] = fmt

    if request.speed is not None:
        request_data["speed"] = request.speed
    if request.instructions:
        request_data["instructions"] = request.instructions
    if request.user:
        request_data["user"] = request.user

    url = f"{provider.config.base_url}/audio/speech"

    try:
        response = await (await provider._http()).post(
            url, json=request_data, headers=provider.get_headers()
        )

        if response.status_code >= 400:
            # OpenAI returns a JSON error body even on failure.
            try:
                error_data = response.json()
                error_message = (
                    error_data.get("error", {}).get("message")
                    or json.dumps(error_data, ensure_ascii=False)
                )
            except json.JSONDecodeError:
                error_data = None
                error_message = response.text
            raise UpstreamProviderError(
                error_message,
                status_code=response.status_code,
                error_type="api_error",
            )

        response.raise_for_status()

        audio_bytes = response.content
        content_type = AUDIO_FORMAT_MIME_TYPES.get(fmt, f"audio/{fmt}")

        # Estimate spoken duration from the textual portion of the input for
        # best-effort per-second billing. Character count is recorded (but not
        # billed) for visibility.
        text = _extract_text_from_input(request.input)
        input_chars = len(text)
        estimated_seconds = round(input_chars / _CHARS_PER_SECOND, 3) if input_chars else 0.0

        # Imported here to avoid a circular import at module load time.
        from app.abstraction.chat import UsageInfo
        usage = UsageInfo(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            extra={
                "output_audio_seconds": estimated_seconds,
                "output_audio_tokens": input_chars,
                "output_audio_price_unit": 0.0,
            },
        )

        return TTSResponse(
            audio_bytes=audio_bytes,
            content_type=content_type,
            model=request.model,
            usage=usage,
        )

    except UpstreamProviderError:
        raise
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"OpenAI speech API error: {str(e)}")
