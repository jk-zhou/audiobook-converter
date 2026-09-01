# 子项目 B · 数据持久化层设计

> 状态：已批准（2026-09-01）
> 范围：SQLite 持久层（用户设置、任务历史、工作会话）、设置/会话 API、localStorage 一次性迁移、任务历史分页与产物清理语义
> 不做：Alembic 迁移框架、设置冲突合并、自动过期清理、多用户隔离

## 1. 背景与目标

现状三类数据各有短板：

| 数据 | 现状 | 问题 |
|---|---|---|
| 用户设置/列设置 | localStorage | 换设备/清浏览器即丢；NAS 多设备访问体验不一致 |
| 工作会话（表单草稿+工作集） | localStorage + uploads 注册表磁盘恢复 | 同上；跨设备不共享 |
| 任务历史 | 内存 + jobs.py JSON 落盘 | 服务重启丢任务；无历史查询 |

目标：全部落 SQLite（`data/hac.db`），多设备一致；重启后任务历史与会话完整恢复；老用户 localStorage 一次性无感迁移。

## 2. 技术选型

- **SQLModel**（roadmap 既定）：与 Pydantic 同源，类型安全，boilerplate 少
- **SQLite WAL 模式**：单进程 FastAPI 单写者足够，读并发不受限
- 不上 Alembic：单用户工具，用 `schema_version` KV 做破坏性变更检测（不匹配时启动报错并提示备份），加表用 `create_all`

## 3. 表结构

```python
# settings：KV，value 为 JSON 字符串（schema 跟随前端，后端不展开字段）
class SettingEntry(SQLModel, table=True):
    key: str = Field(primary_key=True)          # "settings.default" / "settings.columns" / "schema_version"
    value: str                                   # JSON
    updated_at: datetime                         # last-write-wins，多设备后写覆盖

# session：单行（id 固定 "current"），完整前端会话快照
class SessionEntry(SQLModel, table=True):
    id: str = Field(primary_key=True)            # 恒为 "current"
    value: str                                   # JSON: {form, columns, sort, workingSet}
    updated_at: datetime

# jobs：任务历史
class JobRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)            # 与现有 job id 一致
    mode: str                                    # single / merge
    status: str                                  # queued/running/tagging/merging/done/failed/cancelled/interrupted
    preset_id: str | None
    settings_json: str | None                    # TranscodeSettings
    metadata_json: str | None                    # MetadataEdit
    normalize: bool
    title_source: str
    title_pattern: str | None
    source_ids_json: str                         # list[str]
    source_names_json: str | None                # 快照（源删除后历史仍可读）
    output_filename: str | None
    output_path: str | None
    output_size: int | None
    verify_json: str | None                      # VerifyInfo
    error: str | None
    progress: float                              # SSE 回调节流落库：每 5% 或 5s
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    output_deleted_at: datetime | None           # 产物手动清理标记
```

要点：
- `source_names_json` 快照解决「源已删历史不可读」
- `interrupted` 为新终态：启动加载时发现非终态任务 → 标记，前端显示「服务重启中断」
- 进度落库节流在 jobs.py 统一实现（回调处比较上次落库时间/进度差）

## 4. API

| 端点 | 行为 |
|---|---|
| `GET /api/settings` | 返回全部 kv（`{key, value, updated_at}` 列表） |
| `PUT /api/settings` | body `{key, value}`；upsert，last-write-wins |
| `GET /api/session` | 返回 session JSON 或 404（空） |
| `PUT /api/session` | 覆盖保存；前端防抖 500ms 触发，`unload` 时 `sendBeacon` |
| `POST /api/settings/import` | body 即 session JSON；仅当服务端 session 为空时接受（409 否则）；一次性迁移用 |
| `GET /api/jobs?limit=&offset=` | 分页历史，默认 limit=50，按 created_at 倒序 |
| `DELETE /api/jobs/{id}/output` | 删产物文件、置 `output_deleted_at`，历史条目保留 |
| `POST /api/jobs/clear-finished` | 语义变更：改为对全部 done 任务执行产物清理（不再是删除历史） |

兼容性：现有 `GET /api/jobs` 响应结构不变（内存态与 DB 历史合并返回，运行中任务在前）；`startConversion` 创建任务时同步写 DB。

## 5. 前端改动

- `saveSession()`：防抖 500ms `PUT /api/session`；`beforeunload`/`visibilitychange(hidden)` 时 `navigator.sendBeacon` flush
- `restoreSession()`：`GET /api/session` 成功 → 恢复；404/失败 → 回退读 localStorage（向后兼容）
- **一次性迁移**：启动时若 localStorage 有 `hac.session.v1` 且 `GET /api/session` 为 404 → `POST /api/settings/import` → 成功后 `localStorage.removeItem`
- 「清空已完成」按钮改文案「清理产物」，条目显示「产物已清理」状态徽标；done 且产物已删的任务下载按钮禁用
- 任务列表分页：初始 50 条，「加载更多」按钮追加

## 6. 数据文件布局

```
data/
├── hac.db            # 新增（SQLite，WAL 产生 -wal/-shm 临时文件）
├── uploads/          # 不变
├── outputs/          # 不变
├── library/          # 不变
└── logs/             # 不变
```

## 7. 测试

**单元**（pytest，内存 SQLite）：
- settings/session kv 读写、import 仅空时接受（409）
- job 创建落库、进度节流落库、终态落库
- 启动恢复：DB 中的历史加载回内存；非终态 → interrupted
- DELETE output：文件删除 + 标记置位 + 条目保留

**E2E**（改造 part3）：
- 上传 → 创建任务 → **重启服务** → 历史任务可见（含参数/验证信息）、产物可下载
- 会话（表单值+列设置+工作集）重启后恢复
- localStorage 迁移：预置 localStorage 数据 → 首次加载 → 服务端有 session 且本地清空

## 8. 风险与边界

- 大量历史任务后列表 DOM 渲染：分页 50 条/页控制
- SQLite 文件损坏：文档提示备份 `data/hac.db`（Unraid appdata 本身会被备份插件覆盖）
- 「运行中任务在内存、历史在 DB」双源：`GET /api/jobs` 合并时以内存为准，内存没有的从 DB 读——保持简单，不做双向同步
