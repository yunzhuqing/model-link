# 数据分析权限区分：新增「分析所有分组」权限 + 分组多选筛选

## 目标
1. 新增系统权限 `stats.analyze_all_groups`（默认 root 具备），持有者可查看**跨所有分组**的统计数据（而非仅当前用户维度）。
2. 在 `UsagePage` 用可搜索的**分组多选下拉**替换原 `Group ID` 文本输入；选中分组后按所选分组筛选，不选则查看全部分组（仅对持有权限的用户开放）。

## 设计原则（权限模型）
- **持有 `stats.analyze_all_groups`**：不传分组 → 全部分组（不做 user 维度收敛）；传 `group_ids` → 限定分组。
- **未持有**：保持现有行为不变 —— 不传分组时收敛到当前用户自己的记录；传 `group_id` 时仍按该分组查（保留 `GroupStatistics` 在 `GroupDetail` 里对分组管理员的既有行为，不回归）。
- 这样新权限仅"打开"全分组聚合视图，不破坏非特权用户的既有用法（`GroupStatistics` 走单 `group_id`，由 group 路由的成员校验把关）。

---

## 后端改动

### 1. 新增权限种子 — `backend/app/models.py`
在 `DEFAULT_PERMISSIONS` 列表末尾（约 line 933 的 `]` 之前）追加：
```python
{
    "key": "stats.analyze_all_groups",
    "label": "全分组数据分析",
    "description": "查看跨所有分组的使用统计数据（而非仅当前用户维度），并可按分组多选筛选",
    "allowed_roles": ["root"],
},
```
`check_permission` 对 `root` 角色恒为 True，故默认仅 root 通过；`allowed_roles: ["root"]` 与现有 `user.manage` 等保持一致。后续可在权限管理页给 admin 授权（编辑 allowed_roles）。

### 2. 启动时自动播种权限 — `backend/app/__init__.py`
当前 `seed_default_permissions()` 仅在 `GET /api/permissions` 被调用。`check_permission` 在权限行不存在时对任何人（含 root）返回 False，因此必须保证新权限行落库。
在 `app.before_serving(_init_arq)`（line 546）后新增：
```python
async def _seed_permissions():
    from app.models import seed_default_permissions
    await seed_default_permissions()
app.before_serving(_seed_permissions)
```
（幂等，已存在的不重复插入。）

### 3. `backend/app/routes/usage.py`
- 顶部导入：`from app.models import UsageRecord, User, UserGroup, check_permission`（现仅 `UsageRecord`）。

- 新增权限解析辅助：
```python
async def _can_analyze_all_groups(session, username: str) -> bool:
    """当前用户是否持有跨分组数据分析权限。"""
    res = await session.execute(select(User).where(User.username == username))
    user = res.scalars().first()
    if user is None:
        return False
    roles_res = await session.execute(
        select(UserGroup.role).where(UserGroup.user_id == user.id)
    )
    roles = {r[0] for r in roles_res.all()}
    best_role = "root" if "root" in roles else ("admin" if "admin" in roles else None)
    if best_role is None:
        return False
    return await check_permission(best_role, "stats.analyze_all_groups", session)

async def _resolve_analyze_all(username: str) -> bool:
    async with get_db_session() as session:
        return await _can_analyze_all_groups(session, username)
```
（独立短 session，符合"不在跨 LLM 调用期间持有连接"的既有约定；这里无 LLM 调用，仅一次轻量查询。）

- `_get_summary_filters(current_username=None, analyze_all=False)`（line 179）改造：
  - 解析多值分组：合并 `request.args.getlist("group_id")` 与逗号分隔的 `group_ids` 参数，转 int 去重保序 → `group_ids` 列表。
  - user_name 收敛规则：
    - `analyze_all=True`：不自动收敛到当前用户；仅当显式传 `user_name` 时才按其过滤（全分组视图）。
    - `analyze_all=False`：保留旧行为 —— 当无 `group_ids` 且无 `api_key_hash` 时收敛到 `current_username`。
  - 返回字典新增 `'group_ids'`；保留 `'group_id'`（取 `group_ids[0]` 或 None）以兼容 metabase 单值路径。

- `_apply_filters(stmt, filters)`（line 209）：分组过滤改为优先 `group_ids`（`UsageRecord.group_id.in_(...)`），否则回退单 `group_id`（`==`）。

- `list_records`（line 104）：同样 `analyze_all = await _resolve_analyze_all(current_username)`；解析 `group_ids`；收敛逻辑同上（`analyze_all=False` 且无分组/无 api_key_hash 时收敛到当前用户）。

- 全部 summary 端点（`get_summary_totals` / `by_model` / `by_group` / `by_currency` / `by_api_key` / `time_series_by_model` / `time_series` / 旧 `get_summary`）：在 `_require_jwt()` 后取 `analyze_all`，传入 `_get_summary_filters(current_username, analyze_all)`。其余逻辑不动。

### 4. `backend/app/stats/metabase_client.py`
`_filter_clauses`（line 106）支持多分组：当 `group_ids` 长度 >1 → MBQL `["in", uuid, field_ref("groupid"), [ids]]`；长度 ==1 → 复用 `_eq`；并保留对单 `group_id` 的回退。`user_name` 过滤不变（`analyze_all=False` 时 filters 仍带 `user_name`，metabase 自然收敛到该用户）。

---

## 前端改动

### 5. 新组件 `frontend/src/components/GroupMultiSelect.tsx`
参照 `TagSelector.tsx` 的 portal + 搜索 + chip 模式，简化为：
- `props: { value: number[]; onChange: (ids: number[]) => void }`
- 通过 `groupsApi.list()` 拉取分组（复用 `['my-permissions']` 同款 React Query 去重思路可选），按 `name`/`id` 搜索过滤。
- 已选项以 chip 形式展示分组名，支持移除；下拉支持搜索、多选。

### 6. `frontend/src/pages/UsagePage.tsx`
- 读取权限（复用 queryKey `['my-permissions']` 与 Layout 共享缓存）：
  ```ts
  const { data: permData } = useQuery({
    queryKey: ['my-permissions'],
    queryFn: async () => (await permissionsApi.myPermissions()).data,
  });
  const canAnalyzeAll = permData?.permissions?.['stats.analyze_all_groups'] === true;
  ```
- 状态：`groupId: string` → `groupIds: number[]`。
- 筛选区：`canAnalyzeAll` 时渲染 `<GroupMultiSelect value={groupIds} onChange={...}>` 取代 Group ID 文本框；否则不渲染分组筛选项（非特权用户只看自己的数据，无分组筛选 UI）。
- 构造请求参数：`recordsParams` / `filterParams` / `timeSeriesParams` 中把 `group_id` 改为对每个选中 id 追加一个 `group_id` 重复参数（后端 `getlist` 解析多值）。`filterKey` 随 `groupIds` 变化以触发重新拉取。
- `setPage(1)` 在 onChange 中调用（与原文本框一致）。

### 7. 构建验证
- `cd frontend && npm run build`（按记忆规则：前端改动后必跑构建校验）。
- 可选：`cd backend && uv run pytest`。

---

## 影响面与兼容性
- `GroupStatistics.tsx`（`GroupDetail` 统计 tab）仍传单 `group_id` → 后端解析为 `group_ids=[id]` → `.in_([id])` 等价于 `==`，行为不变。
- 非特权用户：默认用户维度（不变）；`UsagePage` 不再显示分组筛选 UI。
- 特权用户：默认全分组聚合；可多选细分。
- 启动播种确保新权限对 root 生效（避免 `check_permission` 因行缺失返回 False）。
- 不新建/改 migration（权限是运行期数据，由 `seed_default_permissions` 幂等插入，非 schema 变更）。
