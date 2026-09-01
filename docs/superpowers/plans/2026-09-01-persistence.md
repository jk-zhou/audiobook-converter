# 子项目 B · 数据持久化层 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SQLite 持久层（settings/session/jobs 三表）+ API + 前端服务端会话同步 + localStorage 一次性迁移 + 任务历史重启恢复。

**Architecture:** `hac/db.py` 持有 SQLModel 引擎（WAL）；Job 模型加 `output_deleted_at` 与 `interrupted` 终态；JobManager 每次变更同步落库、启动时从 DB 恢复全部历史（非终态标 interrupted）；`clear_finished` 语义改为「删产物留历史」；GET /api/jobs 返回内存∪DB 合并列表（DB 独有记录附 output_deleted_at 标记）。前端 saveSession 防抖 PUT + sendBeacon flush + 404 回退 localStorage + 一次性 import。

**Tech Stack:** SQLModel、SQLite WAL、pytest（内存库）、Playwright E2E。

**Spec:** `docs/superpowers/specs/2026-09-01-persistence-design.md`

**Worktree:** `/home/clawbot/workspace/audiobook-converter-persist`，分支 `feat/persistence`

## Global Constraints

- DB 文件：`{DATA_DIR}/hac.db`，PRAGMA journal_mode=WAL、foreign_keys=ON
- schema_version KV 不匹配 → 启动抛错并提示备份（不做自动迁移）
- 现有 API 响应结构不变：`GET /api/jobs` 仍是列表（新增可选 `?limit=&offset=`，默认全量）；SSE 事件不变
- 进度落库节流：距上次落库 ≥5% 或 ≥5s
- `clear_finished`/`DELETE /api/jobs/{id}/output`：只删产物文件，历史条目永久保留（`output_deleted_at` 标记）
- E2E 全量必须保持绿；part3 会话用例改为「服务重启后恢复」场景

---

### Task 1: `hac/db.py` — 引擎 + 三表 + KV 助手

**Files:**
- Create: `src/hac/db.py`
- Modify: `pyproject.toml`（dependencies += sqlmodel）
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `init_db(data_dir: Path) -> None`（建表 + WAL + schema_version 检查，引擎存模块级 `_engine`）
  - `get_engine() -> Engine`
  - `kv_get(key) -> str | None`、`kv_set(key, value_json) -> None`、`kv_all() -> list[dict]`
  - `session_get() -> str | None`、`session_set(value_json) -> None`、`session_exists() -> bool`
  - `job_record_to_job(rec) -> Job`、`job_to_record(job) -> JobRecord`

- [ ] **Step 1:** `uv add sqlmodel`；写失败测试：init_db 建 `hac.db`、kv 读写、session 单行 upsert、schema_version 不匹配抛 RuntimeError、job_to_record/job_record_to_job 往返一致（含 settings/merge/metadata/verify/source_ids JSON、datetime 保留）
- [ ] **Step 2:** `uv run pytest tests/test_db.py -q` 确认 FAIL
- [ ] **Step 3:** 实现 db.py（三表模型 + 助手；JobRecord 字段见 spec §3）
- [ ] **Step 4:** 测试 PASS；**Step 5:** Commit `feat(persist): SQLite 引擎与三表（settings/session/jobs）`

### Task 2: Job 模型扩展

**Files:**
- Modify: `src/hac/models.py`（JobStatus.INTERRUPTED、Job.output_deleted_at）
- Modify: `src/hac/static/app.js`（STATUS_TXT 加 interrupted: "中断"）
- Test: `tests/test_models_job.py`

- [ ] **Step 1:** 失败测试：`JobStatus("interrupted")` 存在；`Job(...).output_deleted_at` 默认 None 且可序列化（model_dump mode=json）
- [ ] **Step 2:** 实现；前端 STATUS_TXT 同步加词（badge 样式复用 cancelled 灰）
- [ ] **Step 3:** PASS + `uv run pytest -q` 全绿；**Step 4:** Commit `feat(persist): Job 增加 interrupted 终态与 output_deleted_at`

### Task 3: JobManager 落库 + 启动恢复 + 清理语义

**Files:**
- Modify: `src/hac/jobs.py`
- Modify: `src/hac/main.py`（lifespan：`db.init_db(config.DATA_DIR)` → `manager.restore_from_db()`）
- Test: `tests/test_jobs_persist.py`

**Interfaces:**
- Consumes: Task 1 的 job_to_record/session helpers
- Produces:
  - `JobManager.restore_from_db()`：DB 全量载入内存；非终态 → `interrupted`（error="服务重启中断"）；终态保留（done/failed/cancelled）
  - `add/set_status/set_progress/cancel/retry` 内部同步 upsert DB；set_progress 按 5%/5s 节流（broadcast 节流保持 0.5% 不变）
  - `clear_finished()`：对每个终态任务 → 删产物文件（存在时）→ `output_deleted_at=now` → **内存移除**（DB 行保留）；返回清理数
  - `delete_output(job_id)`：单任务删产物 + 标记，内存条目保留
  - `db_only_jobs()` → DB 中不在内存的 Job 列表（供 GET /api/jobs 合并）

- [ ] **Step 1:** 失败测试（tmp_path 数据目录）：add 后 DB 有行；set_status(DONE) 后 status/finished_at/progress=100 落库；restore 后内存恢复且终态保留；restore 时 QUEUED → interrupted；clear_finished 删文件且 DB 标记置位且内存移除；delete_output 单个标记；进度节流（两次 set_progress 间隔 <5% 不落库——用 kv/行 updated 或 progress 值判断）
- [ ] **Step 2:** FAIL → 实现 → PASS
- [ ] **Step 3:** main.py lifespan 接线；`uv run pytest -q` 全绿
- [ ] **Step 4:** Commit `feat(persist): JobManager 落库/恢复/清理产物语义`

### Task 4: API — settings / session / import / jobs 合并

**Files:**
- Modify: `src/hac/main.py`
- Test: `tests/test_api_persist.py`（httpx ASGI）

**Interfaces:**
- Produces:
  - `GET /api/settings` → `[{"key","value","updated_at"}]`；`PUT /api/settings` `{key,value}` → upsert
  - `GET /api/session` → JSON 或 404；`PUT /api/session` 任意 JSON 覆盖
  - `POST /api/settings/import`：body=任意 JSON；session 存在 → 409；否则写入并 200
  - `GET /api/jobs?limit=&offset=`：内存∪DB 合并（按 created_at 倒序；DB 独有带 output_deleted_at），limit/offset 可选默认全量
  - `DELETE /api/jobs/{id}/output` → 404/200；`POST /api/jobs/clear-finished` 语义=清理产物（响应 `{cleaned: n}`）

- [ ] **Step 1:** 失败测试：settings GET/PUT 往返；session PUT→GET；import 首次 200 二次 409；jobs 合并（创建 1 个任务 → clear_finished → GET /api/jobs 仍含该任务且 output_deleted_at 非空）；limit/offset 切片；DELETE output 404
- [ ] **Step 2:** 实现 → PASS → `uv run pytest -q`
- [ ] **Step 3:** Commit `feat(persist): settings/session/import API + 任务历史合并与产物清理`

### Task 5: 前端 — 服务端会话 + 迁移 + 清理产物 UI

**Files:**
- Modify: `src/hac/static/app.js`（saveSession/restoreSession 重写、迁移、按钮语义、加载更多）
- Modify: `src/hac/static/index.html`（按钮文案）
- Modify: `src/hac/static/styles.css`（产物已清理徽标）

**Interfaces:**
- Consumes: Task 4 的 API
- Produces: `saveSession()`（防抖 500ms PUT /api/session；beforeunload/hidden → sendBeacon）；`restoreSession()`（GET 404 → 回退 localStorage）；启动迁移（localStorage 有 v1 && 服务端 404 → POST import → 清本地）；badge 样式 `.badge.cleaned`；jobs 渲染上限 50 + 「加载更多」

- [ ] **Step 1:** 实现（保持 SESSION_KEY 兼容读取；import 成功后 removeItem；sendBeacon 用 Blob JSON）
- [ ] **Step 2:** 「清空已完成」→「清理产物」；done 且 output_deleted_at → badge「产物已清理」+ 下载按钮禁用；任务列表默认渲染 50 条 + 加载更多
- [ ] **Step 3:** `uv run pytest -q` + E2E part1 part2 冒烟
- [ ] **Step 4:** Commit `feat(persist): 前端服务端会话/迁移/清理产物 UI`

### Task 6: E2E 重启场景 + 全量回归 + 文档

**Files:**
- Modify: `tests/e2e/part3_ui_session.py`（会话与任务历史改为跨重启验证）
- Modify: `README.md`（数据落点 hac.db）、`docs/06-handoff.md`（未完成事项勾掉 #5 的持久化部分）

- [ ] **Step 1:** part3 新增：上传→建任务→等 done→**重启 e2e 服务进程**（run-e2e.sh 起停封装外，脚本内 kill + 重启同 DATA_DIR）→ GET /api/jobs 含历史（status done）→ 刷新页面会话恢复（表单值/列设置）；localStorage 迁移用例（预置 v1 数据 → 首载 → 服务端有 session）
- [ ] **Step 2:** `uv run pytest -q` + `./scripts/run-e2e.sh` 全量绿
- [ ] **Step 3:** 文档更新；Commit `test(e2e): 持久化重启场景 + docs`

## Self-Review

- Spec §3 三表 / §4 API / §5 前端 / §7 测试全覆盖（Task1=§3，Task3=§2+恢复，Task4=§4，Task5=§5，Task6=§7 E2E）✓
- API 兼容性决策显式化：/api/jobs 保持列表结构 + 可选分页参数（UI 客户端截断）✓
- 类型/命名一致：output_deleted_at / interrupted / import 端点跨任务一致 ✓
