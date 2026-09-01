# 子项目 D · 网页播放/A-B 对比 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Range 流式端点（产物/源/书库 + 章节信息）、底部 mini 试听条、A/B 双面板同步对比抽屉。

**Architecture:** `hac/streaming.py` 提供 Range 解析与分块 206 响应（Starlette Response 流式 yield）；main.py 三类流端点 + info 端点（ffprobe 章节）。前端单全局 `<audio>` + mini 条；A/B 抽屉两个 `<audio>`，以「最近操作者」镜像同步（syncing 标志防回环 + 1s 漂移校正）。

**Tech Stack:** Starlette streaming response、ffprobe -show_chapters、原生 `<audio>`。

**Spec:** `docs/superpowers/specs/2026-09-01-web-playback-design.md`

**Worktree:** `/home/clawbot/workspace/audiobook-converter-player`，分支 `feat/web-playback`

## Global Constraints

- Range：单区间；`bytes=start-end` / `start-` / `-suffix`；非法/越界 416；命中 206 + `Content-Range` + `Accept-Ranges: bytes`
- MIME 按扩展名；未知 → application/octet-stream
- 安全校验：upload id 必须在注册表、lib 路径必须 is_allowed、job 必须存在且有产物
- 不做 MediaSession/锁屏（验证工具定位）
- E2E 全量保持绿

---

### Task 1: `hac/streaming.py` — Range 解析 + 流式响应 + 端点

**Files:**
- Create: `src/hac/streaming.py`
- Modify: `src/hac/main.py`（/api/stream/{kind}/{id}、/info）
- Test: `tests/test_streaming.py`

**Interfaces:**
- Produces:
  - `parse_range(header: str|None, size: int) -> tuple[int,int]|None|"invalid"`（None=无 Range 全量；"invalid"=416）
  - `ranged_file_response(path, mime) -> Response`（206/200，64KB 分块）
  - `mime_for(path) -> str`
  - `chapters_for(path) -> list[dict]`（ffprobe -show_chapters，无章节 []）
  - 端点：`GET /api/stream/upload/{uid}`、`GET /api/stream/job/{jid}`、`GET /api/stream/lib/{path*}`、`GET /api/stream/{kind}/{id}/info`

- [ ] **Step 1:** 失败测试：parse_range 矩阵（None/full/`0-99`/`100-`/`-500`/越界/垃圾→invalid）；mime 映射；chapters（fixture m4b 有章节、mp3 无）；安全（坏 upload id 404、lib 白名单外 403、无产物 job 404）；端点 206 头断言
- [ ] **Step 2:** FAIL → 实现 → PASS；**Step 3:** Commit `feat(playback): Range 流式端点 + 章节 info`

### Task 2: Mini 试听播放器

**Files:**
- Modify: `src/hac/static/index.html`（底部播放条）
- Modify: `src/hac/static/app.js`（miniPlayer 状态、入口按钮：uploads 行/书库行/任务卡片）
- Modify: `src/hac/static/styles.css`

**UI 契约：**
- 全局唯一播放条：▶/⏸、进度 seek、时间、倍速（0.5-2x）、音量、关闭
- uploads 行与书库行加 ▶ 图标按钮；任务卡片 done 加「▶ 试听」（stream/job）
- 切源即换 src 并自动播放

- [ ] **Step 1:** HTML/CSS/JS 实现
- [ ] **Step 2:** pytest + 手动截图
- [ ] **Step 3:** Commit `feat(playback): mini 试听条（uploads/书库/产物）`

### Task 3: A/B 双面板对比

**Files:**
- Modify: `src/hac/static/index.html`（A/B 抽屉）
- Modify: `src/hac/static/app.js`（abPlayer 同步引擎、章节 chips、键盘）
- Modify: `src/hac/static/styles.css`

**同步引擎契约：**
- 任一侧 play/pause/seeked/ratechange → 镜像到另一侧同一时间点（syncing 标志防回环）
- 播放中每秒漂移检查：|Δ|>0.3s 才校正
- 章节 chips：以产物章节为准，点击双侧 seek
- 键盘（抽屉内）：Space 播放暂停、←/→ ±5s
- 双侧独立音量

- [ ] **Step 1:** HTML/CSS/JS
- [ ] **Step 2:** pytest + 截图
- [ ] **Step 3:** Commit `feat(playback): A/B 双面板同步对比（章节跳转+键盘）`

### Task 4: E2E + 收尾

**Files:**
- Modify: `tests/e2e/part2_merge_features.py`（F9：产物试听 + A/B 同步断言）
- Modify: `README.md`、`docs/06-handoff.md`

- [ ] **Step 1:** E2E：mini 试听 canplay+duration；A/B seek 后双侧 currentTime 差 <0.5s；章节 chip 跳转；书库行试听
- [ ] **Step 2:** `uv run pytest -q` + `./scripts/run-e2e.sh` 全量
- [ ] **Step 3:** docs；Commit `test(e2e): 播放/A-B 场景 + docs`

## Self-Review

- Spec §1 端点/Range/章节=T1；§2.1 mini=T2；§2.2 A/B=T3；§4 E2E=T4 ✓
- 无占位符；流端点安全校验显式列出 ✓
