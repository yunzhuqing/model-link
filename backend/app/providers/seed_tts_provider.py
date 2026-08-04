"""
Seed TTS 独立供应商（火山引擎 openspeech 文本转语音）。

对应 Bytedance openspeech 的 ``/api/v3/tts/create`` 接口（模型如
``seed-audio-1.0``），支持文本、图像、音频多模态输入。

这是独立于 ``volcengine`` 的 provider 类型（``PROVIDER_TYPE = "seed_tts"``），
不要与 Ark 的 ``VolcengineProvider`` 合并 —— 两者是不同服务：
  - Ark      走 ``{base_url}/v3/responses`` + Bearer Token（chat/embedding/图像等）
  - openspeech 走 ``{base_url}/api/v3/tts/create`` + ``X-Api-Key``（仅 TTS）

provider 的 ``base_url`` 在管理后台配置（留空则使用默认
``https://openspeech.bytedance.com``）。

与 OpenAI 的 ``/audio/speech`` 不同：
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
"""
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from .base import BaseProvider, ProviderConfig, ProviderCapability, UpstreamProviderError
from ._tts import parse_tts_input
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.tts import TTSRequest, TTSResponse, AUDIO_FORMAT_MIME_TYPES, DEFAULT_AUDIO_FORMAT


class SeedTTSProvider(BaseProvider):
    """火山引擎 openspeech 文本转语音 provider（seed-audio 等）。"""

    PROVIDER_TYPE: str = "seed_tts"

    CAPABILITIES: List[ProviderCapability] = [ProviderCapability.AUDIO]

    DEFAULT_BASE_URL: str = "https://openspeech.bytedance.com"

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
    # TTS 仅支持 speech()；chat/stream_chat 不适用
    # ------------------------------------------------------------------
    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError("SeedTTSProvider only supports text-to-speech (speech()).")

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        raise NotImplementedError("SeedTTSProvider only supports text-to-speech (speech()).")
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
            # audio_config）与上游响应明细打进 Langfuse，便于排查 seed TTS 明细。
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
                    "Seed TTS response missing 'url' field",
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
            raise RuntimeError(f"Seed TTS API error: {str(e)}")
