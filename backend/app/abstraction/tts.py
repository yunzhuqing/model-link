"""
Text-to-speech (TTS) abstraction module.
Defines the unified TTS request and response models.

Compatible with the OpenAI Audio API (`/v1/audio/speech`).
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from app.abstraction.chat import UsageInfo


# Audio formats supported by the OpenAI speech endpoint.
# Mapping from the `response_format` request field to a MIME type.
AUDIO_FORMAT_MIME_TYPES: Dict[str, str] = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}

DEFAULT_AUDIO_FORMAT = "mp3"


@dataclass
class TTSRequest:
    """
    Unified text-to-speech request model.

    Compatible with the OpenAI audio/speech API format:
        {"model": "...", "input": "text to synthesize", "voice": "alloy",
         "response_format": "mp3", "speed": 1.0}
    """
    model: str
    input: Union[str, List[Any], Dict[str, Any]]        # Text to synthesize, or content-block array (text/image/audio)
    voice: str = "alloy"                                # Voice preset
    response_format: str = DEFAULT_AUDIO_FORMAT         # mp3 / opus / aac / flac / wav / pcm
    speed: Optional[float] = None                       # 0.25 - 4.0
    instructions: Optional[str] = None                  # Voice style instructions (gpt-4o-mini-tts)
    user: Optional[str] = None                          # User identifier
    loudness: Optional[float] = None                   # Volume adjustment (doubao audio_config.loudness_rate)
    pitch: Optional[float] = None                      # Pitch adjustment (doubao audio_config.pitch_rate)
    enable_subtitle: bool = False                      # Request subtitles (returned only when enable_url=true)
    enable_url: bool = False                           # Return a file URL instead of an audio stream
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSResponse:
    """
    Unified text-to-speech response.

    A provider produces whichever of ``audio_bytes`` / ``audio_url`` is
    natural for the upstream:

      - OpenAI ``/audio/speech`` returns a binary stream → ``audio_bytes``.
      - Doubao ``/api/v3/tts/create`` returns a download URL → ``audio_url``.

    The route handler normalizes to what the client asked for
    (``TTSRequest.enable_url``): if a URL was requested but only bytes are
    available, the route persists the bytes to storage and synthesizes a URL;
    if a stream was requested but only a URL is available, the route downloads
    the URL. ``subtitle`` carries subtitle data when ``enable_subtitle`` is set.
    The optional ``usage`` field holds a ``UsageInfo``-shaped object so the
    fire-and-forget ``record_usage`` path can bill it.
    """
    audio_bytes: Optional[bytes] = None
    audio_url: Optional[str] = None
    content_type: str = "audio/mpeg"
    model: str = ""
    subtitle: Optional[Any] = None
    usage: Optional['UsageInfo'] = None

    def to_dict(self) -> Dict[str, Any]:
        """Metadata view for tracing / logging (excludes the audio payload)."""
        size = len(self.audio_bytes) if self.audio_bytes else 0
        return {
            "model": self.model,
            "content_type": self.content_type,
            "size_bytes": size,
            "audio_url": self.audio_url,
            "subtitle": self.subtitle,
            "usage": self.usage.to_dict() if self.usage else None,
        }
