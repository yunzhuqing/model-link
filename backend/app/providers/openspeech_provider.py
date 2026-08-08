"""
火山引擎 openspeech 供应商（文本转语音 + 音频转写）。

统一承载 openspeech 服务的音频能力：
  - TTS：``POST {base_url}/api/v3/tts/create``（模型如 ``seed-audio-1.0``），
    支持文本、图像、音频多模态输入。
  - 转写：``POST {base_url}/api/v3/auc/bigmodel/submit`` + ``query``
    （BigModel AUC 异步接口，默认资源 ``volc.seedasr.auc``）。

这是独立于 Ark 的 provider 类型（``PROVIDER_TYPE = "volcengine_openspeech"``），
不要与 Ark 的 ``VolcengineProvider`` 合并 —— 两者是不同服务：
  - Ark（``volcengine``）走 ``{base_url}/v3/responses`` + Bearer Token
    （chat/embedding/图像等）。
  - openspeech 走 ``{base_url}/api/v3/tts/create`` + ``X-Api-Key``（音频能力）。

provider 的 ``base_url`` 在管理后台配置（留空则使用默认
``https://openspeech.bytedance.com``）。

TTS 与 OpenAI 的 ``/audio/speech`` 不同：
  - 鉴权使用 ``X-Api-Key`` 头，而非 Bearer Token。
  - 请求体使用 ``text_prompt`` / ``references`` / ``audio_config`` /
    ``watermark``，而非 OpenAI 的 ``input`` / ``voice``。

网关侧统一接收 OpenAI 风格的 ``/v1/audio/speech`` 请求（含通用 ``input``
内容块数组），由本 provider 翻译为上游格式：

  - text 块      → ``text_prompt``（多块拼接）
  - audio_url 块 → ``references`` 中的 ``{"audio_url": ...}`` / ``{"audio_data": ...}``
  - image_url 块 → ``references`` 中的 ``{"image_url": ...}`` / ``{"image_data": ...}``
  - voice        → ``references`` 中的 ``{"speaker": voice}``
  - response_format → ``audio_config.format``
  - speed        → ``audio_config.speech_rate``（OpenAI 1.0=正常，上游 0=正常）
  - loudness     → ``audio_config.loudness_rate``
  - pitch        → ``audio_config.pitch_rate``
  - sample       → ``audio_config.sample_rate``
  - enable_subtitle → 请求体 ``enable_subtitle``（透传）

上游成功时返回 ``{"duration": <秒>, "url": "<音频下载地址>"}``，本 provider
据 ``enable_url`` 决定：为真则直接返回上游 URL；否则下载该 URL 得到原始音频
字节作为流返回。``duration`` 作为计费时长（精确）。

转写与 OpenAI 的 ``/audio/transcriptions`` 不同：AUC 不接受 multipart
``file``，要求提交 ``audio.url``。因此 JSON URL 输入直接透传；multipart /
base64 输入先写入配置的存储后端（本地存储需要 ``PUBLIC_BASE_URL``）。
"""
import asyncio
import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from .base import BaseProvider, ProviderConfig, ProviderCapability, UpstreamProviderError
from ._tts import parse_tts_input
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.tts import TTSRequest, TTSResponse, AUDIO_FORMAT_MIME_TYPES, DEFAULT_AUDIO_FORMAT
from app.abstraction.transcription import TranscriptionRequest, TranscriptionResponse


DEFAULT_AUC_BASE_URL = "https://openspeech.bytedance.com"


def _secs(value, default=0.0) -> float:
    """Coerce a number to float seconds, rounded to 3 decimals."""
    try:
        return round(float(value), 3) if value is not None else default
    except (TypeError, ValueError):
        return default


def _segment_bounds(utt: Dict[str, Any]) -> tuple:
    """Upstream utterances may carry ms (``start_time``/``end_time``) or
    already-seconds (``start``/``end``)."""
    if "start_time" in utt or "end_time" in utt:
        start = utt.get("start_time") / 1000.0 if utt.get("start_time") is not None else 0.0
        end = utt.get("end_time") / 1000.0 if utt.get("end_time") is not None else 0.0
        return _secs(start), _secs(end)
    return _secs(utt.get("start")), _secs(utt.get("end"))


def _openai_speaker(speaker: Any) -> str:
    """OpenAI diarized segments use letter speakers (``"A"``, ``"B"``, ...);
    seed ASR reports numeric speaker indexes (``additions.speaker``: 1)."""
    if isinstance(speaker, bool):
        return str(speaker)
    if isinstance(speaker, (int, float)):
        n = int(speaker)
        return chr(64 + n) if 1 <= n <= 26 else str(n)
    s = str(speaker).strip()
    if s.isdigit():
        n = int(s)
        return chr(64 + n) if 1 <= n <= 26 else s
    return s


def _utt_additions(utt: Dict[str, Any]) -> Dict[str, Any]:
    additions = utt.get("additions")
    return additions if isinstance(additions, dict) else {}


def _speaker_of(utt: Dict[str, Any]) -> Optional[str]:
    speaker = utt.get("speaker")
    if speaker is None:
        speaker = utt.get("speaker_id")
    if speaker is None and isinstance(utt.get("speaker_info"), dict):
        speaker = utt["speaker_info"].get("speaker")
    if speaker is None:
        speaker = _utt_additions(utt).get("speaker")
    return _openai_speaker(speaker) if speaker is not None else None


def _build_usage(result: Dict[str, Any], transcription: Dict[str, Any], duration: float) -> Dict[str, Any]:
    """Build the OpenAI transcription ``usage`` block.

    OpenAI usage is polymorphic:
      - ``{"type": "tokens", "input_tokens", "output_tokens", "total_tokens",
           "input_token_details": {"audio_tokens", "text_tokens"}}`` when the
        upstream reports tokens;
      - ``{"type": "duration", "seconds": <number>}`` otherwise.
    """
    raw = transcription.get("usage") or result.get("usage")
    if isinstance(raw, dict):
        details = raw.get("input_token_details")
        details = details if isinstance(details, dict) else {}
        if raw.get("input_tokens") is not None or details.get("audio_tokens") is not None:
            input_tokens = raw.get("input_tokens")
            if input_tokens is None:
                input_tokens = details.get("audio_tokens", 0)
            output_tokens = raw.get("output_tokens") or 0
            total_tokens = raw.get("total_tokens")
            if total_tokens is None:
                total_tokens = input_tokens + output_tokens
            return {
                "type": "tokens",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "input_token_details": {
                    "audio_tokens": details.get("audio_tokens", input_tokens),
                    "text_tokens": details.get("text_tokens", 0),
                },
            }
    return {"type": "duration", "seconds": round(float(duration), 3)}


def _build_openai_transcription(fmt: str, text: str, transcription: Dict[str, Any], result: Dict[str, Any], duration: float) -> Dict[str, Any]:
    """Convert the upstream AUC result into OpenAI-compatible shapes.

    - ``json``          → ``{"text": ...}``
    - ``verbose_json``  → ``task`` / ``text`` / ``duration`` / ``segments``
      (numeric ids, no speaker)
    - ``diarized_json`` → same plus ``seg_N`` segment ids with ``speaker`` and
      ``type``, and an OpenAI ``usage`` block (tokens when the upstream
      reports them, otherwise duration)
    """
    if fmt not in ("verbose_json", "diarized_json"):
        return {"text": text}

    diarized = fmt == "diarized_json"
    segments: List[Dict[str, Any]] = []
    for i, utt in enumerate(transcription.get("utterances") or []):
        start, end = _segment_bounds(utt)
        seg: Dict[str, Any] = {
            "id": f"seg_{i}" if diarized else i,
            "start": start,
            "end": end,
            "text": utt.get("text", ""),
        }
        if diarized:
            seg["type"] = "transcript.text.segment"
            speaker = _speaker_of(utt)
            if speaker:
                seg["speaker"] = speaker
            additions = _utt_additions(utt)
            for key in ("emotion", "emotion_degree", "gender"):
                value = utt.get(key) if utt.get(key) is not None else additions.get(key)
                if value is not None:
                    seg[key] = value
        segments.append(seg)

    payload: Dict[str, Any] = {
        "task": "transcribe",
        "text": text,
        "duration": duration,
        "segments": segments,
    }
    if not diarized:
        language = (transcription.get("additions") or {}).get("language")
        if language:
            payload["language"] = str(language)
        return payload

    payload["usage"] = _build_usage(result, transcription, duration)
    return payload


def _resolve_audio_resource_id(model: str, cfg: Dict[str, Any]) -> str:
    """Model-dependent ``X-Api-Resource-Id`` for openspeech transcription:

    - ``seed-audio-transcription-2.x`` → ``volc.seedasr.auc``
    - ``seed-audio-transcription-1.x`` → ``volc.bigasr.auc``

    An explicit ``audio_resource_id`` provider option always wins.
    """
    configured = cfg.get("audio_resource_id")
    if configured:
        return str(configured)
    name = (model or "").lower()
    if "seed-audio-transcription-2" in name:
        return "volc.seedasr.auc"
    if "seed-audio-transcription-1" in name:
        return "volc.bigasr.auc"
    return "volc.seedasr.auc"


async def openspeech_transcribe(provider, request: TranscriptionRequest) -> TranscriptionResponse:
    """Transcribe audio through the openspeech BigModel AUC async API.

    AUC does not accept OpenAI's multipart ``file``.  It requires
    ``audio.url`` in the submit request, so JSON URL input is forwarded
    directly and multipart/base64 input is placed in the configured
    storage backend first (and therefore requires ``PUBLIC_BASE_URL`` for
    local storage).

    Task protocol (per the official AUC spec):
      - the task id is the ``X-Api-Request-Id`` header value (a UUID) chosen
        by the caller at submit time;
      - ``submit`` returns no body: success/failure is judged via the
        ``X-Api-Status-Code`` response header, and the message is carried in
        ``X-Api-Message``;
      - ``query`` polls with the same ``X-Api-Request-Id`` and reports status
        through the same response headers.
    """
    import os

    cfg = {**(provider.config.extra_config or {}), **(request.provider_options or {})}
    base = (cfg.get("auc_base_url") or getattr(provider, "DEFAULT_AUC_BASE_URL", None) or DEFAULT_AUC_BASE_URL).rstrip("/")
    resource_id = _resolve_audio_resource_id(request.model, cfg)
    timeout_s = float(cfg.get("audio_transcription_timeout", 300))
    poll_s = float(cfg.get("audio_transcription_poll_interval", 1.0))
    audio_url = request.source_url if request.source_url and request.source_url.startswith(("http://", "https://")) else None

    if not audio_url:
        from app.storage.factory import get_storage_backend
        from app.routes.audio import _guess_audio_filename
        filename = request.filename or _guess_audio_filename(request.mime_type)
        key = f"transcription_{uuid.uuid4().hex}_{filename.replace('/', '_')}"
        stored = await asyncio.to_thread(
            get_storage_backend().write_binary,
            key, request.file_bytes, request.mime_type or "application/octet-stream",
        )
        if stored.startswith(("http://", "https://")):
            audio_url = stored
        else:
            public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
            if not public_base:
                raise UpstreamProviderError(
                    "Openspeech transcription requires a public audio URL. "
                    "Set PUBLIC_BASE_URL or configure public S3 storage.",
                    status_code=500, error_type="configuration_error",
                )
            audio_url = f"{public_base}{stored if stored.startswith('/') else '/' + stored}"

    audio_format = (request.filename or "").rsplit(".", 1)[-1].lower() if "." in (request.filename or "") else ""
    if not audio_format:
        audio_format = (request.mime_type or "audio/wav").split("/")[-1].split(";")[0]

    def _bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    # diarized_json 需要说话人分句：强制开启说话人信息与 utterances 返回。
    diarized = request.response_format == "diarized_json"
    body = {
        "audio": {"url": audio_url, "format": audio_format},
        "request": {
            "model_name": cfg.get("audio_model_name") or "bigmodel",
            "enable_itn": _bool(cfg.get("enable_itn"), True),
            "enable_punc": _bool(cfg.get("enable_punc")),
            "enable_ddc": _bool(cfg.get("enable_ddc")),
            "enable_speaker_info": True if diarized else _bool(cfg.get("enable_speaker_info")),
            "show_utterances": True if diarized else _bool(cfg.get("show_utterances")),
            "enable_auto_lang": _bool(cfg.get("enable_auto_lang")),
            "enable_lid": _bool(cfg.get("enable_lid")),
            "enable_gender_detection": True if diarized else _bool(cfg.get("enable_gender_detection")),
            "enable_emotion_detection": True if diarized else _bool(cfg.get("enable_emotion_detection")),
            "sensitive_words_filter": cfg.get("sensitive_words_filter", ""),
        },
    }
    # Speaker separation requirements are provider-specific and should be
    # sent only when configured.
    for name in ("ssd_version", "ssd_mode"):
        if cfg.get(name) is not None:
            body["request"][name] = cfg[name]
    if request.language and request.language not in ("auto", ""):
        body["request"]["language"] = request.language

    # 任务 ID 由调用方在提交时通过 X-Api-Request-Id 头指定（UUID 格式），
    # query 时用同一个 UUID 查询。
    request_id = str(uuid.uuid4())
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": provider.config.api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
    }
    http = await provider._http()
    submit_url = f"{base}/api/v3/auc/bigmodel/submit"
    query_url = f"{base}/api/v3/auc/bigmodel/query"
    try:
        # submit 没有返回体：状态看响应头 X-Api-Status-Code，错误信息在
        # X-Api-Message 头里。
        response = await http.post(submit_url, json=body, headers=headers, timeout=60)
        status = str(response.headers.get("X-Api-Status-Code", "")).strip()
        if response.status_code >= 400 or status != "20000000":
            message = (
                response.headers.get("X-Api-Message")
                or response.text
                or f"submit failed (X-Api-Status-Code={status or 'missing'})"
            )
            raise UpstreamProviderError(message, status_code=502)

        # task_id == 提交时携带的 X-Api-Request-Id（UUID）。
        query_headers = {k: v for k, v in headers.items() if k != "X-Api-Sequence"}
        deadline = asyncio.get_running_loop().time() + timeout_s
        result = None
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_s)
            poll = await http.post(query_url, json={}, headers=query_headers, timeout=60)
            status = str(poll.headers.get("X-Api-Status-Code", "")).strip()
            if status == "20000000":
                try:
                    data = poll.json()
                except (json.JSONDecodeError, ValueError):
                    data = {}
                result = data.get("body", data)
                break
            if status not in ("20000001", "20000002", ""):
                message = (
                    poll.headers.get("X-Api-Message")
                    or poll.text
                    or f"query failed (X-Api-Status-Code={status or 'missing'})"
                )
                raise UpstreamProviderError(message, status_code=502)
        if result is None:
            raise UpstreamProviderError("Openspeech transcription timed out", status_code=504)

        transcription = result.get("result", {})
        text = transcription.get("text", "")
        duration_ms = result.get("audio_info", {}).get("duration") or transcription.get("additions", {}).get("duration")
        try:
            duration = float(duration_ms) / 1000 if duration_ms is not None else 0.0
        except (TypeError, ValueError):
            duration = 0.0
        data = _build_openai_transcription(request.response_format, text, transcription, result, duration)
        from app.abstraction.chat import UsageInfo
        usage = UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0,
                          extra={"output_audio_seconds": duration}) if duration > 0 else None
        return TranscriptionResponse(text=text, data=data, content_type="application/json", model=request.model, usage=usage)
    except UpstreamProviderError:
        raise
    except Exception as e:
        raise RuntimeError(f"Openspeech transcription API error: {e}")


class VolcengineOpenspeechProvider(BaseProvider):
    """火山引擎 openspeech 供应商（seed-audio TTS + BigModel AUC 转写）。"""

    PROVIDER_TYPE: str = "volcengine_openspeech"

    CAPABILITIES: List[ProviderCapability] = [ProviderCapability.AUDIO]

    DEFAULT_BASE_URL: str = "https://openspeech.bytedance.com"
    DEFAULT_AUC_BASE_URL: str = DEFAULT_AUC_BASE_URL

    # OpenAI speed (1.0 = normal) → 上游 speech_rate (0 = normal) 的线性映射。
    _SPEED_MAP: float = 1.0

    # ------------------------------------------------------------------
    # 请求头：上游使用 X-Api-Key
    # ------------------------------------------------------------------
    def get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["X-Api-Key"] = self.config.api_key
        return headers

    # ------------------------------------------------------------------
    # 音频能力之外不支持 chat/embedding
    # ------------------------------------------------------------------
    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError("VolcengineOpenspeechProvider only supports audio (speech()/transcribe()).")

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        raise NotImplementedError("VolcengineOpenspeechProvider only supports audio (speech()/transcribe()).")
        # yield required to make this a generator
        yield  # pragma: no cover

    # ------------------------------------------------------------------
    # 文本转语音
    # ------------------------------------------------------------------
    async def speech(self, request: TTSRequest) -> TTSResponse:
        parsed = parse_tts_input(request.input)
        text_prompt = parsed["text"]

        # references：speaker（来自 voice）+ 音频块 + 图像块
        references: List[Dict[str, Any]] = []
        if request.voice:
            references.append({"speaker": request.voice})
        for a in parsed["audio"]:
            if "url" in a:
                references.append({"audio_url": a["url"]})
            else:
                references.append({"audio_data": a["data"]})
        for im in parsed["image"]:
            if "url" in im:
                references.append({"image_url": im["url"]})
            else:
                references.append({"image_data": im["data"]})

        fmt = (request.response_format or DEFAULT_AUDIO_FORMAT).lower()
        audio_config: Dict[str, Any] = {"format": fmt}
        if request.speed is not None:
            # OpenAI: 1.0 = 正常；上游: 0 = 正常。
            audio_config["speech_rate"] = round((request.speed - 1.0) * self._SPEED_MAP, 3)
        if request.loudness is not None:
            audio_config["loudness_rate"] = request.loudness
        if request.pitch is not None:
            audio_config["pitch_rate"] = request.pitch
        if request.sample is not None:
            audio_config["sample_rate"] = request.sample

        body: Dict[str, Any] = {
            "model": request.model,
            "text_prompt": text_prompt,
            "references": references,
            "audio_config": audio_config,
            "watermark": {},
        }
        if request.enable_subtitle:
            body["enable_subtitle"] = True

        base = (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        url = f"{base}/api/v3/tts/create"

        try:
            http = await self._http()
            # 子 span：把发给 openspeech 的上游请求体（text_prompt / references /
            # audio_config）与上游响应明细打进 Langfuse，便于排查 openspeech TTS 明细。
            async with self._trace_call(request.model, input_data=body) as child_span:
                response = await http.post(url, json=body, headers=self.get_headers())

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        error_message = (
                            error_data.get("message")
                            or error_data.get("error", {}).get("message")
                            or json.dumps(error_data, ensure_ascii=False)
                        )
                    except json.JSONDecodeError:
                        error_message = response.text
                    raise UpstreamProviderError(
                        error_message,
                        status_code=response.status_code,
                        error_type="api_error",
                    )

                response.raise_for_status()
                data = response.json()
                if child_span:
                    child_span.log_output(data)

            audio_url = data.get("url")
            if not audio_url:
                raise UpstreamProviderError(
                    "Openspeech TTS response missing 'url' field",
                    status_code=502,
                    error_type="api_error",
                )

            content_type = AUDIO_FORMAT_MIME_TYPES.get(fmt, f"audio/{fmt}")

            # 字幕（若上游返回）
            subtitle: Optional[Any] = None
            for k in ("subtitle", "subtitle_url", "subtitles", "srt", "srt_url"):
                if data.get(k):
                    subtitle = data[k]
                    break

            # 上游返回真实时长，直接用于计费（比按字符估算精确）。
            duration = data.get("duration") or data.get("original_duration") or 0.0
            input_chars = len(text_prompt)

            from app.abstraction.chat import UsageInfo
            usage = UsageInfo(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                extra={
                    "output_audio_seconds": float(duration),
                    "output_audio_tokens": input_chars,
                    "output_audio_price_unit": 0.0,
                },
            )

            # enable_url=true：直接返回上游 URL，不下载音频流。
            # 否则下载 URL 得到音频字节，交给路由作为流返回。
            if request.enable_url:
                return TTSResponse(
                    audio_url=audio_url,
                    content_type=content_type,
                    model=request.model,
                    subtitle=subtitle,
                    usage=usage,
                )

            # 下载音频：openspeech 返回的 URL 是火山临时签名地址，下载时会
            # 302 重定向到实际存储。必须用 follow_redirects 的共享 client，
            # 否则拿到的是 302 响应体（HTML），以 audio/* 返回后无法播放。
            from app.http_client import get_shared_redirect_client
            audio_resp = await (await get_shared_redirect_client()).get(audio_url)
            if audio_resp.status_code >= 400:
                raise UpstreamProviderError(
                    f"Failed to download generated audio ({audio_resp.status_code})",
                    status_code=502,
                    error_type="api_error",
                )
            # 以真实响应 content-type 为准；若拿到的是 HTML/JSON（错误页），
            # 直接报错而不是把非音频字节当音频返回。
            downloaded_ct = (audio_resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            if downloaded_ct.startswith("audio/"):
                content_type = downloaded_ct
            elif downloaded_ct in ("text/html", "application/json", "text/plain"):
                raise UpstreamProviderError(
                    f"Failed to download generated audio: unexpected content-type '{downloaded_ct}'",
                    status_code=502,
                    error_type="api_error",
                )
            audio_bytes = audio_resp.content

            return TTSResponse(
                audio_bytes=audio_bytes,
                audio_url=audio_url,
                content_type=content_type,
                model=request.model,
                subtitle=subtitle,
                usage=usage,
            )

        except UpstreamProviderError:
            raise
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Openspeech TTS API error: {str(e)}")

    # ------------------------------------------------------------------
    # 音频转写（BigModel AUC 异步接口）
    # ------------------------------------------------------------------
    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        """Transcribe audio through the openspeech BigModel AUC async API."""
        return await openspeech_transcribe(self, request)
