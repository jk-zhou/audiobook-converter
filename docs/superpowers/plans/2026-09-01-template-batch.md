# 子项目 C · 模板语法 + 批量重命名/写 tag 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 模板引擎（parse/render/match 双向）、TrackNum 特殊处理、转码侧 pattern 升级、uploads/outputs 批量重命名 + mutagen 写 tag、嵌入式批处理 UI（实时预览）。

**Architecture:** 新模块 `hac/template.py`（纯函数：parse_template → Segment 列表；render；match_filename 状态机——字面量锚点切分 + 相邻贪婪字段歧义报错）。`hac/batch.py` 编排池文件 rename + tagwriter（复用 mutagen）。API 两个端点 preview/execute；UI 抽屉嵌「已上传文件」tab 与任务卡片。

**Tech Stack:** 纯 Python 正则 + mutagen（已有依赖）。

**Spec:** `docs/superpowers/specs/2026-09-01-template-batch-design.md`

**Worktree:** `/home/clawbot/workspace/audiobook-converter-template`，分支 `feat/template-batch`

## Global Constraints

- TrackNum tag 写 `N/total`（total = 池内文件数）；文件名零填充 `${TrackNum:3}`
- 重命名仅原地：uploads `{id}_{newname}`、outputs rename + DB output_filename 同步
- 被运行中任务引用（referenced_by_active）→ skipped；目标名冲突 → 该文件拒绝
- 模板必须含 ≥1 字面量锚点（全字段无字面量 → 400）；相邻贪婪字段无法唯一切分 → 该文件「歧义」错误
- 强制预览：execute 前 UI 必须已展示 preview（前端流程控制；API 层 execute 仍直接执行）
- E2E 全量保持绿

---

### Task 1: 模板引擎 `hac/template.py`

**Files:**
- Create: `src/hac/template.py`
- Test: `tests/test_template.py`

**Interfaces:**
- Produces:
  - `parse_template(tpl) -> list[Segment]`（Segment: kind=literal/field, value, optional, width）
  - `render(tpl, fields: dict, total: int|None=None) -> str`（缺失必填字段抛 TemplateError；optional→""；int 字段零填充；TrackNum 渲染后返回）
  - `match_filename(tpl, filename_stem) -> dict`（字段→值；TrackNum 支持 `1`、`01`、`1/294`；歧义抛 `TemplateMatchError(reason)`；无字面量多字段抛参数错）
  - `validate_template(tpl) -> list[str]`（未知字段/无锚点等错误消息，空=合法）

- [ ] **Step 1:** 写失败测试（矩阵）：
  - parse：`${TrackNum}`/`${TrackNum?}`/`${TrackNum:3}`/字面量混合/未知字段
  - render：零填充、optional 缺失→空、必填缺失抛错、track/total 写 tag 由调用方处理
  - match：`第${TrackNum}集 ${TrackTitle}` ↔ `第1集 风起`；`${TrackNum}/${TrackTotal}` 中 track/total；`01`→1；贪婪歧义（`${TrackTitle} ${TrackTitle}` 无锚点）报错；字面量锚点回溯
  - validate：未知字段、空模板、全字段无字面量
- [ ] **Step 2:** `uv run pytest tests/test_template.py -q` FAIL
- [ ] **Step 3:** 实现 template.py
- [ ] **Step 4:** PASS + 全量 pytest；**Step 5:** Commit `feat(template): 模板引擎 parse/render/match + TrackNum 特殊处理`

### Task 2: 写 tag 模块 `hac/tagwriter.py`

**Files:**
- Create: `src/hac/tagwriter.py`
- Test: `tests/test_tagwriter.py`（用 gen_fixtures 造真实 m4a/mp3/flac）

**Interfaces:**
- Produces: `write_tags(path: Path, fields: dict, track_total: int|None) -> None`
  - fields 键：title/artist/album/track(+track_total)/year/genre/disc/composer（None 跳过）
  - m4a: ©nam/©ART/©alb/trkn[(n,total)]/©day/©gen/ disk /©wrt；mp3: TIT2/TPE1/TALB/TRCK(1/294)/TDRC/TCON/TPOS/TCOM；flac/ogg: title/artist/album/tracknumber+tracktotal/date/genre/discnumber/composer

- [ ] **Step 1:** 失败测试：m4a 写全字段 → mutagen 回读断言（trkn=(1,3)）；mp3 TRCK="1/3"；flac tracknumber="1"+tracktotal="3"；不支持的扩展抛 ValueError
- [ ] **Step 2:** 实现 → PASS；**Step 3:** Commit `feat(template): mutagen 写 tag（m4a/mp3/flac/ogg，track/total）`

### Task 3: 批处理编排 + API

**Files:**
- Create: `src/hac/batch.py`
- Modify: `src/hac/main.py`（/api/batch/preview、/api/batch/execute）
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: template.py、tagwriter.py、uploads 注册表、db（outputs 池 jobrecord）
- Produces:
  - `preview_batch(pool, ids, template, write_fields, total_hint) -> list[dict]`（每项 {id, name, fields, new_name, tag_changes, status, reason}）
  - `execute_batch(...)` → {ok, skipped, failed, details}；uploads rename 后注册表更新（内存+磁盘文件名）；outputs rename 后更新 jobrecord.output_filename/output_path
  - 请求模型 `BatchRequest`（pydantic）进 main.py

- [ ] **Step 1:** 失败测试：uploads 池 rename 后磁盘/注册表/db 一致；outputs rename 后 jobrecord 更新；locked（ACTIVE 引用）跳过；冲突（新名撞现有）拒绝；非法模板 400；track/total=池大小
- [ ] **Step 2:** 实现 → PASS；**Step 3:** Commit `feat(batch): 批处理编排 + preview/execute API`

### Task 4: 批处理 UI（抽屉 + 实时预览）

**Files:**
- Modify: `src/hac/static/index.html`（drawer 结构、批量处理按钮）
- Modify: `src/hac/static/app.js`（选中态、drawer、预览防抖、执行）
- Modify: `src/hac/static/styles.css`（drawer、chips、冲突标红）
- Modify: `tests/e2e/part2_merge_features.py` 或新增断言（见 Task 5）

**UI 契约：**
- 「已上传文件」工具行加「批量处理」（勾选≥1 启用，仅音频文件；cover 跳过）
- 任务卡片产物行加「批量处理」（pool=outputs，预选该 job 全部产物 id）
- drawer：模板输入 + 8 字段 chip 插入 + 预览表（防抖 300ms POST preview）+ 写 tag 勾选 + 执行 → 报告
- a11y：drawer role=dialog、Esc 关闭、焦点圈闭

- [ ] **Step 1:** HTML drawer 骨架 + CSS
- [ ] **Step 2:** app.js 交互（选中集合、预览、执行、报告渲染）
- [ ] **Step 3:** pytest + 截图验证
- [ ] **Step 4:** Commit `feat(ui): 批处理抽屉（模板/实时预览/执行报告）`

### Task 5: 转码侧模板升级 + E2E + 收尾

**Files:**
- Modify: `src/hac/main.py`（title_pattern/output_filename 模板解析走 template.py；错误内联报 400）
- Modify: `src/hac/transcoder.py`（渲染标题/输出名；track 写 N/total）
- Modify: `src/hac/static/index.html`（输出文件名模板输入，hint 更新）
- Modify: `src/hac/static/app.js`
- Test/E2E: part2 增批处理场景（勾选→预览→执行→ffprobe 回读 tag）；part1 加模板标题断言

- [ ] **Step 1:** 转码侧：title_source=pattern 与新输出名模板走 render（源无 track 用列表顺序，现有逻辑）；TrackNum tag 写 N/total（single 模式 total=面板文件数）
- [ ] **Step 2:** E2E part2 追加批处理用例；part1 追加 `${TrackNum:3} ${TrackTitle}` 断言
- [ ] **Step 3:** `uv run pytest -q` + `./scripts/run-e2e.sh` 全量
- [ ] **Step 4:** 文档：README 功能列表、handoff 勾掉 v0.2
- [ ] **Step 5:** Commit `feat(template): 转码侧模板升级 + E2E + docs`

## Self-Review

- Spec §1-4 全覆盖（T1=§1, T2=§2.2, T3=§2+§3, T4=§4, T5=§1.4+§6）✓
- 无占位符；接口签名跨任务一致（preview_batch/execute_batch/write_tags）✓
- YAGNI 已裁剪项（新目录/zip/.bak/撤销）与 spec 一致 ✓
