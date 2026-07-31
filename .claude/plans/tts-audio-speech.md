# Plan: OpenAI-compatible `/v1/audio/speech` (TTS) endpoint

Mirrors the `embeddings`/`images` pattern (abstraction → provider → middleware → route), adds a new `support_tts` model feature flag, and records best-effort audio usage via the existing per-second audio billing branch.

## Backend

### 1. New abstraction — `backend/app/abstraction/tts.py`
- `TTSRequest` dataclass: `model`, `input` (str), `voice`, `response_format` (default `"mp3"`), `speed` (Optional[float]), `instructions` (Optional[str], for gpt-4o-mini-tts), `user`, `metadata`. Mirror `EmbeddingRequest`.
- `TTSResponse` dataclass: `audio_bytes: bytes`, `content_type: str`, `model: str`, `usage: Optional[UsageInfo]`, `to_dict()` for tracing/metadata.

### 2. OpenAI provider — `backend/app/providers/openai_provider.py`
- Add `async def speech(self, request: TTSRequest) -> TTSResponse:` after `embed()` (~L992). POST JSON `{model, input, voice, response_format, speed, instructions}` to `{self.config.base_url}/audio/speech`, returns binary. Mirror `embed()` but return `response.content` (bytes). Derive `content_type` from `response_format` (`audio/{fmt}`). Raise `UpstreamProviderError` (base.py:19) on upstream >=400. Estimate `output_audio_seconds` from input character count (`len(input) / 15.0` speech-rate heuristic) and build a `UsageInfo(extra={'output_audio_seconds': ..., 'output_audio_tokens': len(input), 'output_audio_price_unit': 0.0})` wrapped in `ChatResponse` inside `TTSResponse.usage` so `record_usage` can read `.usage`.

### 3. Middleware — `backend/app/middleware/gateway_service.py`
- Add `support_tts: bool = False` to `ResolvedModelData` (request_context.py:94) and populate `support_tts=bool(getattr(db_model,'support_tts',False))` in `resolve_model` (~L309).
- Add `async def speech(self, resolved, request, tracer=None) -> TTSResponse` mirroring `embed()` (L1099-1171): tracer metadata, `request.model = resolved.model_real_name`, pass `support_tts` into `request.metadata`, gate on `resolved.support_tts` + `hasattr(provider_instance,'speech')`, wrap `UpstreamProviderError`/`RuntimeError` → `ProviderError`.

### 4. New route — `backend/app/routes/audio.py`
- `audio_bp = Blueprint('audio', __name__)`, `POST /v1/audio/speech`. Mirror embeddings.py 4-phase structure. Validate model + input (+ voice required by OpenAI). Return `Response(audio_bytes, mimetype=content_type, headers={'Content-Disposition': ...})`. Error handling mirrors embeddings.py:207-224. Best-effort usage recording mirroring `_record_image_usage`.

### 5. Blueprint registration — `backend/app/__init__.py`
- Register `audio_bp` at ~L625-655.

### 6. `support_tts` flag plumbing (mirror `support_embedding`)
- `models.py`: column on `ModelTemplate` (~L496) + `Model` (~L627), both `to_dict()` (~L546, L682).
- `routes/providers.py`: `create_model` (~L328), `update_model` allowlist (~L374).
- `routes/model_templates.py`: create (~L123) + update loop (~L152).
- `routes/apikeys.py:453`: serialize into allowed-models payload.

### 7. Migration (CLAUDE.md — management script, no hand-edit)
```
cd backend
FLASK_APP=manage.py uv run flask db migrate -m "add support_tts flag"
FLASK_APP=manage.py uv run flask db upgrade
```

## Frontend (admin can toggle the flag per model)

### 8. `frontend/src/pages/ProviderList.tsx`
- Add `support_tts` (label "TTS") to features array (~L1189), type defs (81/135), defaults (222), template-copy (478), badge (355).

### 9. `frontend/src/pages/ModelTemplates.tsx`
- `FEATURES_KEYS` (128), `FEATURE_I18N_MAP` (142), defaults (114), badge filter (1135).

### 10. `frontend/src/pages/GroupModels.tsx`
- Type defs (34/70), copy (262), badges (428/527).

### 11. i18n — add `modelTemplates.features.tts` + group feature keys (en/zh) in `frontend/src/i18n/`.

### 12. `npm run build` to verify compilation (memory rule).

## Scope notes / decisions
- **Billing mismatch**: OpenAI bills TTS per input character; the existing billing formula bills audio per-second only. I estimate `output_audio_seconds` from text length (~14 chars/sec) and set `output_audio_tokens` = char count (recorded but not billed). Admin configures `output_pricing` `{"audio":{"type":"per_second","price":<per-second>}}`. Best-effort, consistent with the existing audio billing branch.
- Only OpenAI provider explicitly implemented; `AzureProvider` (subclass) inherits `speech()` since it overrides only base_url — works for free.
- No existing TTS route test; optionally add an env-gated live-server test modeled on `test_seedance_video_generation.py` (skippable).

## Files touched (~17)
Backend: `abstraction/tts.py` (new), `providers/openai_provider.py`, `middleware/gateway_service.py`, `request_context.py`, `routes/audio.py` (new), `__init__.py`, `models.py`, `routes/providers.py`, `routes/model_templates.py`, `routes/apikeys.py`, + migration.
Frontend: `ProviderList.tsx`, `ModelTemplates.tsx`, `GroupModels.tsx`, i18n files.
