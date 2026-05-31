---
name: arq-task-queue
description: ARQ async task queue for offloading API key usage DB writes with debouncing
metadata:
  type: project
---

ARQ 用于优化 API Key 的 `last_used_at` / `request_count` 更新操作。原实现每个请求通过 `asyncio.create_task()` 直接写 DB，高并发下压力大。现在改为通过 ARQ 入队，由 Worker 异步消费。

**核心文件：**
- `app/arq_client.py` — 生产者（Quart 进程内入队）
- `app/arq_worker.py` — 消费者（支持嵌入式/独立进程两种模式）
- `app/routes/gateway_helpers.py` — 调用 `enqueue_apikey_usage()` 替换了原来的 `_async_update_apikey_usage()`
- `app/__init__.py` — `before_serving` 初始化 ARQ client，条件启动嵌入式 worker；`after_serving` 清理

**去重策略：** `job_id = apikey_usage:{api_key_id}:{time_bucket}`，bucket = `int(time.time() / 5)`，ARQ 的 `SETNX` 保证同一窗口内仅一个任务。`_defer_by=5s` 推迟执行以允许更多请求合并。

**运行模式：**
- 嵌入式：`ARQ_EMBEDDED_WORKER=true`，Worker 作为 asyncio Task 跑在 Quart 进程内，共享 DB 连接池
- 独立进程：`uv run arq app.arq_worker.WorkerSettings`

**Why:** 高并发下每请求一次 DB UPDATE 竞争激烈，改为队列异步消费减少连接池压力和行锁竞争。去重进一步降低写入频率（1000 req/s/key → 每5秒1次写入）。

**How to apply:** 部署时设置 `ARQ_EMBEDDED_WORKER=true` 即可。如需独立扩缩 Worker，使用 `arq` CLI 启动独立进程。[[env-variables]]
