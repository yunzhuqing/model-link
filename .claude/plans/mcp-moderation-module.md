# Plan: MCP 模块 — 查询火山引擎 Seedance 封控原因

## 目标

新增一个 MCP (Model Context Protocol) server，暴露一个工具 `get_seedance_block_reasons`，供 Claude Desktop / IDE 等 MCP 客户端调用，查询火山引擎 Seedance 内容被封控 (block_reasons) 的原因。

调用火山引擎 `GetModerationResult` API：
- `POST https://open.volcengineapi.com/?Action=GetModerationResult&Version=2024-01-01`
- 请求体：`{"Id": "<id>", "Type": "asset_id | task_id | request_id"}`
- 认证：Volcengine Signature V4 (HMAC-SHA256)，host=`open.volcengineapi.com`，service=`ark`，region=`cn-beijing`
- 返回 `Result.block_reasons`（列表，含 `label` / `sub_label` / `detail`）

## 关键决策（已与用户确认）

1. **形态**：MCP Server（stdio transport），暴露工具。
2. **凭证**：复用数据库中 Volcengine Provider 行的 `extra_config`（`ark_access_key` / `ark_secret_key` / `ark_region`）。
3. **签名主机**：按文档用 `open.volcengineapi.com`（非 asset.py 现用的 `ark.cn-beijing.volcengineapi.com`）。

## 复用现有代码

- **签名**：[asset.py:56-150](backend/app/providers/volcengine/asset.py#L56-L150) 的 `_build_ark_auth_headers` 已实现完整 V4 签名链，但 `host` 硬编码为 `ARK_API_HOST`。**改造**：新增可选参数 `host`（默认 `ARK_API_HOST`），使签名可指定 `open.volcengineapi.com`。其余逻辑不变。
- **共享 httpx 客户端**：`app.http_client.shared_client`（[http_client.py](backend/app/http_client.py)）。
- **凭证解析**：仿照 [files.py:75-124](backend/app/routes/files.py#L75-L124) 的 `_get_volcengine_credentials`，按 `provider_id` / `provider_name` 查 `Provider` 表，读 `extra_config`。
- **DB 异步引擎**：`app._init_async_engine()` / `app.get_db_session()`（[app/__init__.py:334,344](backend/app/__init__.py#L334)）。MCP server 进程启动时调用 `_init_async_engine()`，不创建 Quart app。

## 新增文件

### 1. `backend/app/mcp/__init__.py`
空包标记。

### 2. `backend/app/mcp/moderation.py` — 核心查询逻辑
```python
async def get_moderation_result(
    *, id: str, type: str,
    access_key: str, secret_key: str, region: str = "cn-beijing",
) -> dict:
```
- 校验 `type ∈ {asset_id, task_id, request_id}`。
- 构造 payload `{"Id": id, "Type": type}`，`json.dumps(ensure_ascii=False)`。
- 调用改造后的 `_build_ark_auth_headers(host="open.volcengineapi.com", service="ark", region=region, action="GetModerationResult", payload_str=...)`。
- `POST https://open.volcengineapi.com/?Action=GetModerationResult&Version=2024-01-01`，`content=payload_str`（raw bytes，保证 SHA256 与签名一致），`headers=...`。
- ≥400 → 抛 `RuntimeError` 带响应体；成功返回完整响应 JSON。
- 提供薄包装 `async def fetch_block_reasons(id, type, *, provider_id=None, provider_name=None)`：解析凭证 → 调用 → 返回 `{"block_reasons": [...], "raw": {...}}`。

凭证解析（新函数，放在 moderation.py 或 server.py）：
```python
async def resolve_volcengine_creds(provider_id=None, provider_name=None) -> dict:
```
- `async with get_db_session() as session:` 查 `Provider where type=="volcengine", is_active==True`，可选 `id==provider_id` 或 `name==provider_name`。
- 若未指定，取第一条（按 id 升序）；若 `MCP_VOLCENGINE_PROVIDER_ID` 环境变量存在则用它。
- 要求 `access_key` 和 `secret_key` 都非空，否则抛错提示在管理后台配置 AK/SK。
- 返回 `{access_key, secret_key, region, provider_id, provider_name}`。

### 3. `backend/app/mcp/server.py` — FastMCP server
- 使用官方 `mcp` SDK 的 `FastMCP`（`from mcp.server.fastmcp import FastMCP`）。
- 工具 `get_seedance_block_reasons(id: str, type: str, provider_id: int | None = None, provider_name: str | None = None) -> str`：
  - 调用 `fetch_block_reasons(...)`，把 `block_reasons` 格式化为人类可读文本（无封控时返回“未检测到封控”；有则逐条列出 label/sub_label/detail）。
- 启动时（lifespan 或首次调用懒初始化）调用 `app._init_async_engine()`；退出时 `_dispose_async_engine()`。
- 加载 `.env`（`python-dotenv.load_dotenv()`），使 `DATABASE_URL` 等可用。
- `if __name__ == "__main__": mcp.run(transport="stdio")`。

## 改动现有文件

### 4. `backend/app/providers/volcengine/asset.py`
- `_build_ark_auth_headers` 增加参数 `host: str = ARK_API_HOST`，函数体内 `host` 用该参数。返回头 `Host` 同步用该值。其余不变。所有现有调用点（CreateAsset/GetAsset/DeleteAsset）不传 host，行为不变。

### 5. `backend/pyproject.toml` + `backend/requirements.txt`
- 新增依赖 `mcp`（官方 `mcp` SDK，`>=1.2`，含 `mcp.server.fastmcp.FastMCP` 与 stdio transport）。

## 运行方式（文档化，不改 Docker）

- 开发/本地：`cd backend && uv run python -m app.mcp.server`
- Claude Desktop 配置示例（写入 `claude_desktop_config.json`）：
  ```json
  {
    "mcpServers": {
      "model-link-seedance": {
        "command": "uv",
        "args": ["run", "--directory", "<repo>/backend", "python", "-m", "app.mcp.server"],
        "env": { "DATABASE_URL": "<同 backend 的 DATABASE_URL>" }
      }
    }
  }
  ```
- 也可在 `pyproject.toml` 的 `[project.scripts]` 加 `model-link-mcp = "app.mcp.server:main"`（可选）。

## 测试

- 在 `backend/tests/` 下新增 `test_mcp_moderation.py`（pytest-asyncio）：
  - mock `shared_client` 与签名，验证 payload/host/Action 正确、`type` 校验拒绝非法值、成功路径返回 `block_reasons`、4xx 抛错带响应体。
  - 不真实调用火山引擎。

## 风险与注意

- `open.volcengineapi.com` 的 V4 签名 service 确认为 `ark`（ResponseMetadata.Service=ark）；host 用实际请求 host。若签名报 403/SignatureDoesNotMatch，需复核 canonical query/host；现留 host 参数化以便排查。
- MCP server 进程独立，需能读到 `DATABASE_URL` 与 Provider 表；要求运行环境与 backend 共享同一数据库与 `.env`。
- AK/SK 来自 Provider 行，仅支持配置了 `ark_access_key`/`ark_secret_key` 的账号；未配置时给出明确报错。
