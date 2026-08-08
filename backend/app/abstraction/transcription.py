"""
Audio transcription abstraction module.
Defines the unified transcription request and response models.

Compatible with the OpenAI Audio API (`/v1/audio/transcriptions`).
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.abstraction.chat import UsageInfo


# Response formats accepted by the OpenAI transcription endpoint.
# ``json`` (default) returns ``{"text": "..."}``; ``text``/``srt`` return raw
# text; ``verbose_json``/``diarized_json`` return a structured JSON payload
# that also carries the audio ``duration`` used for billing.
TRANSCRIPTION_FORMATS = {"json", "text", "srt", "verbose_json", "diarized_json"}
DEFAULT_TRANSCRIPTION_FORMAT = "json"


@dataclass
class TranscriptionRequest:
    """
    Unified audio transcription request model.

    Compatible with the OpenAI ``/audio/transcriptions`` API:

        multipart/form-data with:
          file=..., model="gpt-4o-transcribe-diarize",
          response_format="diarized_json", chunking_strategy=auto,
          known_speaker_names[]=agent,
          known_speaker_references[]=data:audio/wav;base64,...

    The route handler also accepts ``application/json`` input with a
    ``file_url`` (http(s) URL, ``data:`` URI, or bare base64); it resolves
    that source to bytes before filling this object. The provider forwards
    ``file_bytes``/``filename``/``mime_type`` plus the scalar/array
    parameters to the upstream verbatim.
    """
    model: str
    file_bytes: bytes = b""
    filename: str = "audio"
    mime_type: str = "application/octet-stream"
    language: Optional[str] = None                 # ISO-639-1 language code
    prompt: Optional[str] = None                  # Text to guide transcription style
    response_format: str = DEFAULT_TRANSCRIPTION_FORMAT
    temperature: Optional[float] = None            # 0.0 - 1.0
    timestamp_granularities: Optional[List[str]] = None  # ["segment","word"]
    chunking_strategy: Optional[str] = None       # "auto" / "none"
    known_speaker_names: Optional[List[str]] = None
    known_speaker_references: Optional[List[str]] = None
    user: Optional[str] = None
    # Original URL when the gateway received JSON ``file_url`` input.  Some
    # providers (Volcengine AUC) require a publicly reachable URL instead of
    # an uploaded multipart file.
    source_url: Optional[str] = None
    provider_options: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TranscriptionResponse:
    """
    Unified audio transcription response.

    A provider produces whichever of ``data`` / ``text`` is natural for the
    requested ``response_format``:

      - ``json`` / ``verbose_json`` / ``diarized_json`` → parsed JSON dict
        in ``data`` (and the transcript text mirrored in ``text``).
      - ``text`` / ``srt`` → raw body string in ``text``.

    ``duration`` (seconds of audio) is extracted from the upstream response
    when available (verbose_json / diarized_json) and surfaced through the
    ``usage`` object so the fire-and-forget ``record_usage`` path can bill it.
    """
    text: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    content_type: str = "application/json"
    model: str = ""
    usage: Optional['UsageInfo'] = None

    def to_dict(self) -> Dict[str, Any]:
        """Metadata view for tracing / logging (excludes large payloads)."""
        return {
            "model": self.model,
            "content_type": self.content_type,
            "has_data": self.data is not None,
            "text_len": len(self.text) if self.text else 0,
            "usage": self.usage.to_dict() if self.usage else None,
        }
