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

**Custom tools (`custom_tool_call` / `custom_tool_call_output`)**: supported for input and output, stream and non-stream.
- Input `custom_tool_call` → assistant `ContentType.CUSTOM_TOOL_CALL` block; `custom_tool_call_output` → tool `ContentType.CUSTOM_TOOL_CALL_OUTPUT` block (distinct `ContentType` values, NOT plain `TOOL_CALL`/`TOOL_RESULT`). Pairing key is `call_id` ↔ `call_id`; the output side resolves `call_id` → `caller_id` (legacy) → `caller.caller_id` → item `id`.
- Custom metadata is stored as **fixed typed fields** on `ContentBlock` (`namespace` / `caller` / `item_id` / `input_raw` / `prompt_cache_breakpoint`), not a free-form dict. `build_responses_request` / Volcengine `_message_to_input_item` reconstruct the `custom_tool_call` / `custom_tool_call_output` items from these fields via `_custom_tool_call_item_from_block` / `_custom_tool_call_output_item_from_block`.
- Providers treat custom variants uniformly: `TOOL_CALL_TYPES = (TOOL_CALL, CUSTOM_TOOL_CALL)` and `TOOL_RESULT_TYPES = (TOOL_RESULT, CUSTOM_TOOL_CALL_OUTPUT)` are exported from `messages.py` — CC upstreams (OpenAI/Anthropic/Gemini/Vertex/DeepSeek) serialize custom blocks as ordinary function tool calls; only the Responses-API paths emit `custom_tool_call` / `custom_tool_call_output`.
- Output: a `ToolCall` with `call_type == "custom"` formats as a `custom_tool_call` item (`_custom_tool_call_output_item`), carrying `namespace` / `caller` / `item_id` / `input_raw` from the upstream. Streaming uses `response.custom_tool_call_input.delta` / `.done` events.
- `openai_responses_compt_provider._parse_responses_event` maps `item_id` → `call_id` (`tc_id_map`) because `custom_tool_call_input.delta` only carries the item id.
- Responses-API upstream parsers emit tool-call **delta chunks without `id`**: the adapter's `format_stream_chunk` treats any chunk with an `id` as a *new* tool-call start, so a repeated id would emit duplicate `response.output_item.added`. Deltas resolve via `output_index → call_id` or `_stream_current_tc_call_id`.
- Custom tool input is often **not JSON** (e.g. code patches), so the JSON-completion `done`-event detection never fires. The finish-chunk cleanup (`not fc_info['done'] and (arguments or type == 'custom')`) always closes custom tool calls with `custom_tool_call_input.done` + `output_item.done`.

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
