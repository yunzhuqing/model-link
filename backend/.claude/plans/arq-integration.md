# ARQ Integration Plan — Offload API Key Usage Updates to Task Queue

## Problem

Every authenticated request calls `_async_update_apikey_usage()` via `asyncio.create_task()`, which opens a new DB session and executes:

```sql
UPDATE ml_api_keys SET last_used_at = NOW(), request_count = request_count + 1 WHERE id = ?
```

Under high concurrency (thousands of requests/sec), this means thousands of competing DB writes per second — one per request — putting unnecessary pressure on the database.

## Goal

Move the `last_used_at` / `request_count` update into an ARQ-managed Redis-backed task queue, with **time-window debouncing** so that multiple requests for the same API key within a ~5 second window result in a single DB write.

## Design

### Architecture

```
Quart request handler
  └─ enqueue_apikey_usage(api_key_id)
       └─ ARQ Redis enqueue (job_id = "apikey_usage:{id}:{bucket}", deferred 5s)
            └─ ARQ Worker process
                 └─ update_apikey_usage(ctx, api_key_id)
                      └─ DB: UPDATE last_used_at, request_count += 1
```

### Debouncing Strategy

- **Time bucketing**: `bucket = int(time.time() / 5)` — each 5-second window gets a unique bucket ID
- **Job ID dedup**: `job_id = f"apikey_usage:{api_key_id}:{bucket}"` — ARQ's `_job_id` uses Redis `SETNX` under the hood; if a job with the same ID already exists, the enqueue raises a conflict → caught and silently ignored
- **Deferred execution**: `_defer_by = 5` — delays job execution by 5 seconds to give more requests time to coalesce into the same bucket
- **Net effect**: For API key X getting 1000 requests in 5 seconds → 1 DB write (instead of 1000)

### Fallback

If Redis/ARQ is unavailable, enqueue fails silently with a warning log. The API key stats (`last_used_at`, `request_count`) are eventually reconciled by the existing usage-sync leader service anyway, so occasional misses are tolerable.

## Files to Create

### 1. `backend/app/arq_worker.py` — Worker settings + job functions

- `async def update_apikey_usage(ctx, api_key_id: int)` — the ARQ job function
  - Opens a short-lived DB session via `get_db_session()`
  - Executes `UPDATE ml_api_keys SET last_used_at = NOW(), request_count = request_count + 1 WHERE id = ?`
  - Commits and logs
- `async def startup(ctx)` — initializes the async DB engine (worker process has its own event loop)
- `async def shutdown(ctx)` — disposes the async DB engine
- `WorkerSettings` class with:
  - `functions = [update_apikey_usage]`
  - `on_startup = startup`
  - `on_shutdown = shutdown`
  - `redis_settings` from `ARQ_REDIS_URL` env var (defaults to `CACHE_REDIS_URL`)
  - `queue_name` from `ARQ_QUEUE_NAME` env var (defaults to `arq:queue`)

### 2. `backend/app/arq_client.py` — Client for enqueuing from Quart

- `_arq_pool: ArqRedis | None` — singleton pool reference
- `async def init_arq()` — creates the `arq.create_pool()` connection (called at app startup)
- `async def close_arq()` — closes the pool (called at app shutdown)
- `async def enqueue_apikey_usage(api_key_id: int)` — enqueues the job with debouncing
  - Computes `bucket = int(time.time() / ARQ_DEBOUNCE_SECONDS)`
  - Calls `_arq_pool.enqueue_job("update_apikey_usage", api_key_id, _job_id=f"apikey_usage:{api_key_id}:{bucket}", _defer_by=ARQ_DEBOUNCE_SECONDS)`
  - Catches `JobConflict` (duplicate job_id) → silent no-op
  - Catches other exceptions → warning log

## Files to Modify

### 3. `backend/pyproject.toml`

Add `arq>=0.26.0` to dependencies.

### 4. `backend/app/routes/gateway_helpers.py`

- Remove the `_async_update_apikey_usage` function (lines 176-194)
- Replace `asyncio.create_task(_async_update_apikey_usage(auth_ctx.api_key_id))` at lines 273 and 308 with `await enqueue_apikey_usage(auth_ctx.api_key_id)` (from `app.arq_client`)
- Add import for `enqueue_apikey_usage`

### 5. `backend/app/__init__.py`

In `create_app()`:
- Add `app.before_serving(_init_arq)` after the async engine init (line 399)
- Add `await close_arq()` to `_shutdown_cleanup()` (line 424-430)

Where:
```python
from app.arq_client import init_arq as _init_arq, close_arq as _close_arq
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ARQ_REDIS_URL` | `$CACHE_REDIS_URL` or `redis://localhost:6379/0` | Redis URL for ARQ backend |
| `ARQ_QUEUE_NAME` | `arq:queue` | Redis key prefix for the job queue |
| `ARQ_DEBOUNCE_SECONDS` | `5` | Time window for coalescing updates |

## Worker Process

Start the ARQ worker alongside the Quart server:

```bash
cd backend
ARQ_REDIS_URL=redis://... uv run arq app.arq_worker.WorkerSettings
```

This runs as a separate process. In production (Docker/K8s), this would be a separate container or sidecar.

## Migration Steps

1. Add `arq` to `pyproject.toml`, run `uv sync`
2. Create `app/arq_worker.py` and `app/arq_client.py`
3. Modify `app/routes/gateway_helpers.py`
4. Modify `app/__init__.py`
5. Deploy with ARQ worker process running alongside the app
6. Monitor logs for any enqueue failures

## Risk Assessment

- **Low risk**: The existing `request_count` / `last_used_at` fields are also periodically reconciled by the usage-sync leader service, so even if ARQ jobs are lost, stats eventually converge
- **No behavioral change**: The update is already fire-and-forget; moving it to ARQ doesn't change the API contract or response behavior
- **Redis dependency**: The app already depends on Redis for caching, rate limiting, and leader election — ARQ adds no new infrastructure dependency
