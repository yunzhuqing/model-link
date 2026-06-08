# Model Link — AI Gateway

Unified gateway for multiple LLM providers (OpenAI, Anthropic, DeepSeek, Gemini, Azure, Tencent, BytePlus, Moonshot, GLM, MiniMax, vLLM, Volcengine), exposing OpenAI/Anthropic-compatible endpoints for chat, embeddings, images, rerank, and responses.

## Project layout

```
backend/     — Quart ASGI server (Python 3.12+, uv)
frontend/    — React 19 SPA (Vite, TypeScript, Tailwind CSS 4)
Dockerfile   — Multi-stage: Node frontend build → Python backend + static
```

## Backend (`backend/`)

**Stack**: Quart (async Flask) + uvicorn + SQLAlchemy 2.0 (async) + Flask-Migrate/Alembic

**Startup**:
```
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Every route handler must be `async`

The entire app runs on asyncio via uvicorn. All Quart route handlers, before/after request hooks, and provider methods are `async def`. Never use synchronous I/O in route handlers.

### Architecture (three-layer)

```
API layer (routes/) → Middleware (middleware/gateway_service.py) → Providers (providers/)
```

- **`routes/`** — Quart blueprints for each API surface (gateway, embeddings, images, rerank, users, apikeys, usage, etc.)
- **`middleware/gateway_service.py`** — Model resolution, provider routing, unified error handling. Routes never call providers directly.
- **`providers/`** — One module per provider, each subclassing `BaseProvider` (see `providers/base.py`). Use `httpx.AsyncClient`.
- **`adapters/`** — Format translation between external API protocols (OpenAI, Anthropic) and the internal `ChatRequest`/`ChatResponse` abstraction.
- **`abstraction/`** — Internal canonical types: `ChatRequest`, `ChatResponse`, `StreamChunk`, `Message`, `EmbeddingRequest`, etc.

### Database

- Two engines coexist: **sync** (Flask-SQLAlchemy, for Alembic migrations) and **async** (SQLAlchemy async engine, for runtime queries).
- Route handlers open short-lived async sessions via `get_db_session()` — never hold a DB connection across an upstream LLM call.
- Models defined in `app/models.py` (~1250 lines, single file). All models import from `from app import db`.

### Database migrations (CRITICAL)

**Never create or modify migration scripts by hand.** Always use the management script:

```
cd backend
FLASK_APP=manage.py uv run flask db migrate -m "description of change"
FLASK_APP=manage.py uv run flask db upgrade
```

Other useful commands:
```
FLASK_APP=manage.py uv run flask db current      # Show current revision
FLASK_APP=manage.py uv run flask db history      # Show migration history
FLASK_APP=manage.py uv run flask db downgrade    # Roll back one revision
```

`manage.py` creates a temporary Flask app (not Quart) wired to the same `db`/`migrate` instances from `app/__init__.py`, so Alembic autogenerate sees all models correctly.

### Key patterns

- **Request lifecycle**: Auth → Resolve model + rate-limit check → LLM upstream call → Usage record (fire-and-forget). Each phase opens its own short-lived DB session.
- **uvloop is blocked** in `app/main.py` because it raises RuntimeError on closed TCP transports that SQLAlchemy's pre-ping can't catch.
- **Request ID**: Every request gets a UUID (from `X-Request-Id` header or auto-generated), injected into log records via `ContextVar`, returned in response headers.
- **Leader election**: Uses `tooz` for distributed coordination. Background services (usage sync, compression, resync) only run on the elected leader node.
- **Langfuse tracing**: Flushed on graceful shutdown via `after_serving` hook.
- **Exchange rates**: Daily refresh scheduled at startup, runs on a background thread.

### Responses API adapter (`adapters/responses_adapter.py`) — critical rules

The `/v1/responses` endpoint converts OpenAI Responses-API format to internal `ChatRequest` and back. Several ordering constraints must be maintained:

**Input → Message conversion (`_handle_*` functions):**
- Consecutive `function_call` items MUST be merged into a single `Message(role=ASSISTANT, content=[TOOL_CALL, ...])`.
- `function_call` items that follow an assistant message with text/reasoning MUST merge into it (Case 3 + Case A). Result: one assistant Message with `content + tool_calls + reasoning_content`.
- `function_call_output` items each become a separate `Message(role=TOOL)`.
- `_parse_content_blocks` MUST handle `output_text` type (not just `input_text`/`text`), since Responses API output is fed back as input in multi-turn.

**Streaming SSE event order:**
```
response.created → response.in_progress
→ [reasoning item: output_item.added → delta... → done]   (output_index=0)
→ [message item:  output_item.added → content_part.added → output_text.delta → done]  (output_index=1)
→ [function_call:  output_item.added → arguments.delta → done]  (output_index=2+)
→ response.completed  (output array: reasoning, message, function_calls — in index order)
```

Key rules enforced in `_process_chunk()` and `format_stream_chunk()`:
1. **Reasoning closes before tool_calls**: `chunk.tool_calls` + `reasoning_started` + not `reasoning_closed` → emit `_emit_reasoning_done()` first.
2. **Text closes before tool_calls**: `chunk.tool_calls` + `_stream_text_started` + not `_stream_text_closed` → emit `_emit_text_close_events()` first.
3. **`response.completed` output array**: message BEFORE function_calls (matches output_index: 0=reasoning, 1=message, 2+=function_call).
4. **`_is_marker_chunk()` MUST check `delta_reasoning_content`**: chunks with reasoning content are NOT role-only markers. Providers like Bailian send reasoning without `delta_content` (incremental_output mode), so omitting this check drops reasoning chunks.

### Running tests

```
cd backend
uv run pytest
```

Tests are async (`pytest-asyncio`). Use `httpx.AsyncClient` for making requests to the test app.

## Frontend (`frontend/`)

**Stack**: React 19 + TypeScript 5.9 + Vite 7 + Tailwind CSS 4 + React Router 7 + React Query 5

```
cd frontend
npm run dev      # Development server
npm run build    # Production build → dist/
```

### Key patterns

- **API client**: `src/api/client.ts` — Axios instance with Bearer token interceptor and 401 redirect.
- **Auth**: `src/contexts/AuthContext.tsx` — JWT token management, persisted in localStorage.
- **Routing**: `src/App.tsx` — React Router with `ProtectedRoute` wrapper. API key selection is scoped by workspace.
- **Styling**: Tailwind CSS 4. Components are in `src/components/`, pages in `src/pages/`.
- **i18n**: Uses `react-i18next`, locale resources in `src/i18n/`.

### Production

Production builds go into `backend/static/` (or wherever the Quart app serves static files from). The Dockerfile handles this in the multi-stage build.
