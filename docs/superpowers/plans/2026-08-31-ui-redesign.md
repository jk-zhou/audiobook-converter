# UI/UX 全面改版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Audiobook Converter 前端从「上下三区块」重排为「左主工作区 + 右侧栏」，建立设计 token 体系、预设优先的渐进披露表单、SVG 图标体系，并补齐可访问性；保持 Vanilla JS 无构建链、仅深色主题、E2E 全绿。

**Architecture:** 无框架前端（index.html + styles.css + app.js，共 ~1400 行）。改版以 HTML 结构重排 + CSS 全面重写为主，app.js 只做必要的渲染与辅助函数改动。所有 E2E 依赖的 DOM 契约（元素 ID、`.tab[data-tab]`、`.pbar > div`、`.verify`、`#file-list tr`、`.uprow`、`header .logo`、`.layout`、`.lower`）保持不变。

**Tech Stack:** Vanilla JS + 原生 CSS（无构建、无 CDN、无外部依赖）；图标为 inline SVG sprite。

**Spec:** 本计划 + `docs/01-design.md`（产品定位：单用户本地部署的批量音频转码工具，目标设备为桌面浏览器为主、平板/手机基本可用）。

**Worktree:** `/home/clawbot/workspace/audiobook-converter-ui`，分支 `feat/ui-redesign`（隔离自 main）。

## Global Constraints

- 仅深色主题（不做浅色，不做 prefers-color-scheme 切换）
- 零 CDN / 零外部资源：字体用系统栈，图标用 inline SVG sprite
- E2E 选择器契约必须保留：`#col-files #col-settings #col-jobs #btn-start #file-list #file-head #file-input #folder-input #file-empty #preset #format #codec #bitrate #samplerate #channels #normalize #merge-on #merge-fields #merge-title #merge-artist #merge-composer #merge-cover #merge-hint #title-source #title-pattern #title-pattern-row #meta-title #meta-artist #meta-album #meta-composer #lib-list #lib-path #lib-roots #lib-up #uploads-list #up-count #up-del-selected #up-del-all #up-add-selected #columns-pop #btn-columns #btn-sort-reset #btn-clear-files #btn-cancel-all #btn-clear-finished #btn-zip #job-list #toast #health-badge #upload-progress #pane-upload #panel-library #panel-uploads #preset-hint #err-codec #err-channels #file-count`、`.tab[data-tab=…]/.tab.active`、`.layout`、`.lower`、`.pbar > div`、`.verify`、`.uprow`、`.badge.*`、`header .logo`
- 按钮文字、状态 badge 词（queued/running/tagging/merging/done/failed/cancelled）保持中文原文不变（E2E 有文本断言）
- 触控目标 ≥44px；正文对比度 ≥4.5:1；支持 `prefers-reduced-motion`
- 每个任务完成即提交；提交信息遵循现有风格（`feat:`/`fix:`/`docs:` 前缀）
- 验证命令：`uv run pytest -q`（60 项）；`./scripts/run-e2e.sh partN`（E2E 在隔离数据目录运行，安全）

---

### Task 1: 设计 token 与基础样式重写（styles.css 全面重写）

**Files:**
- Modify: `src/hac/static/styles.css`（全量重写，131 行 → ~400 行）

**Interfaces:**
- Produces: CSS 变量 token 体系（下方全部列出），所有后续任务的样式基础
- 保留：`.hidden`、`.small`、`.dim`、`.mono`、`.btn` 系列、`.pill` 等既有类名（app.js 大量生成这些 class）

**Token 定义（写入 `:root`）：**

```css
:root {
  /* 色彩：三层深度 + 语义色 */
  --bg: #0b0d12;            /* 页面底（更深，拉开与面板层次） */
  --panel: #14171e;         /* 面板 */
  --panel2: #1c202a;        /* 面板内嵌控件/表头 */
  --panel3: #232834;        /* hover/激活面 */
  --border: #2b3140;
  --border-strong: #3a4254;
  --text: #e8ebf1;
  --text2: #a8b0bf;         /* 次要文字（对比度 ≥4.5:1 on panel） */
  --dim: #78808f;           /* 仅辅助信息 */
  --accent: #4f8cff; --accent2: #78b0ff;
  --ok: #3ecf7a; --warn: #e6a23c; --err: #f2635b;
  --radius-s: 6px; --radius: 10px; --radius-l: 14px;
  /* 间距 4/8 节奏 */
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px;
  /* 字号阶梯 */
  --fs-xs: 12px; --fs-sm: 13px; --fs-md: 14px; --fs-lg: 16px; --fs-xl: 20px;
  --focus-ring: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent);
}
```

**基础规则：**
- `:focus-visible { outline: none; box-shadow: var(--focus-ring); }` 全局焦点环
- `.btn` 最小高度 36px（小按钮 32px，主按钮 44px），`:hover` 用 `--panel3` + 150ms 过渡
- `@media (prefers-reduced-motion: reduce) { * { transition-duration: .01ms !important; animation: none !important; } }`
- `.field label` 间距统一 8px；fieldset 改为卡片化（`--panel2` 底 + `--radius-l`）

- [ ] **Step 1:** 重写 styles.css（token + 基础组件 + 全部既有区块样式迁移适配）
- [ ] **Step 2:** `uv run pytest -q` → 60 passed
- [ ] **Step 3:** `./scripts/run-e2e.sh part3` → 19/19
- [ ] **Step 4:** 启动服务截图，向用户展示
- [ ] **Step 5:** Commit `feat(ui): design token 体系与基础样式重写`

---

### Task 2: SVG 图标体系

**Files:**
- Modify: `src/hac/static/index.html`（body 顶部加 `<svg style="display:none"><symbol id="i-…">…</symbol></svg>` sprite）
- Modify: `src/hac/static/app.js`（加 `icon(name)` helper；替换生成 HTML 中的 emoji）

**Interfaces:**
- Produces: `icon(name)` 返回 `<svg class="ic"><use href="#i-NAME"/></svg>` 字符串
- Symbol 清单（16 个，stroke 1.5px、24 viewBox、currentColor）：
  `i-upload i-folder i-library i-trash i-download i-play i-x i-check i-alert i-chevron-down i-grip i-arrow-up i-arrow-down i-settings i-list i-music`
- `.ic { width:16px; height:16px; flex:none; }`，按钮内 `display:inline-flex; align-items:center; gap:6px`

替换点（对照 index.html/app.js）：
- `📚 合并为一个 M4B` → `i-music`；`🗑` → `i-trash`
- `⬇ 打包 zip` → `i-download`；`▶ 开始转换` → `i-play`；`⤵ 加入列表` → `i-download`
- `✕ 取消全部` → `i-x`；`⬆ 上级` → `i-arrow-up`；`⠿` 拖拽把手 → `i-grip`
- 行删除 `✕` → `i-x`；图标按钮补 `aria-label`（如删除行 → `aria-label="从列表移除 {文件名}"`）

- [ ] **Step 1:** index.html 加 sprite；styles.css 加 `.ic` 与按钮 inline-flex
- [ ] **Step 2:** app.js 加 `icon()` helper 并替换全部 emoji
- [ ] **Step 3:** `uv run pytest -q` + `./scripts/run-e2e.sh part2 part3` 全绿
- [ ] **Step 4:** 截图展示
- [ ] **Step 5:** Commit `feat(ui): inline SVG 图标体系替换 emoji`

---

### Task 3: 布局重排（左主工作区 + 右侧栏）

**Files:**
- Modify: `src/hac/static/index.html`（结构调整，所有 ID/data-tab 保留）
- Modify: `src/hac/static/styles.css`（布局段重写）
- Modify: `src/hac/static/app.js`（若有因结构变化的查询路径；预期无）

**新结构（保留 E2E 契约的 ID/类）：**

```
header（logo + 标题 + health pill，不变）
main.layout（display:grid; grid-template-columns: 1fr 360px; gap: var(--s4)）
├─ section#col-files.files-panel     ← 左侧主区（文件 tab + 表格）
└─ aside.lower                        ← 右侧栏（class 保留给 E2E）
   ├─ section#col-settings.panel      ← 转换设置卡
   │  ├─ 预设（主控件，Task 4 细化；本任务先原样迁移）
   │  └─ …全部字段原样迁移，ID 不变
   │  └─ #btn-start（sticky bottom within sidebar: position:sticky; bottom:8px）
   └─ section#col-jobs.panel          ← 任务卡
```

- 标题文案：`1 · 文件` → `文件`、`2 · 设置` → `转换设置`、`3 · 任务` → `任务`；`#file-count` 保留
- `#btn-start` sticky：侧栏滚动时始终可见；文件列表非空时加 `.ready`（accent 边框微光）
- `@media (max-width:1100px)`：grid 变单列（侧栏下移），保留原断点行为

- [ ] **Step 1:** index.html 结构调整（settings+jobs 移入 aside.lower）
- [ ] **Step 2:** styles.css 布局段重写 + sticky CTA
- [ ] **Step 3:** `uv run pytest -q`；`./scripts/run-e2e.sh` 全套（布局改动影响面大）→ 74/74
- [ ] **Step 4:** 截图展示（桌面 1440px + 1100px 断点）
- [ ] **Step 5:** Commit `feat(ui): 左主工作区+右侧栏布局重排，sticky 开始转换`

---

### Task 4: 设置表单渐进披露

**Files:**
- Modify: `src/hac/static/index.html`
- Modify: `src/hac/static/styles.css`
- Modify: `src/hac/static/app.js`（预设摘要 chips 渲染 + 折叠逻辑 + 会话恢复兼容）

**设计：**
1. 预设区置顶加大：select 之外渲染参数摘要 chips（`AAC · 48k · 24kHz · 单声道`，数据来自 presets 接口，`#preset-hint` 复用为容器）
2. `<details class="adv">` 包裹「高级参数」：格式/编码器/码率/采样率/声道/loudnorm；summary 行显示当前组合摘要；预设选中时默认收起，选「自定义」时默认展开。用原生 `<details>`（无 JS 依赖），open 状态存入会话
3. 合并 M4B（`#merge-on` 勾选后 `#merge-fields` 展开，现有逻辑保留）：开启时通用元数据 fieldset 中与书级重复的「标题/作者/专辑/演播者」四行加 `.meta-dup` 并隐藏（仅合并模式），单文件模式照旧——JS 在 `merge-on` change 时切换
4. 封面 input：外包统一样式按钮（label for=merge-cover），原生控件视觉隐藏但保留可聚焦

**会话兼容：** `saveSession()/restoreSession()` 增存 `advOpen`；其余字段名不变。

- [ ] **Step 1:** HTML 结构 + details 折叠 + 封面按钮化
- [ ] **Step 2:** app.js：chips 渲染、merge 联动隐藏、会话字段
- [ ] **Step 3:** pytest + E2E part2（合并主流程）+ part3（会话恢复）全绿
- [ ] **Step 4:** 截图展示（收起/展开两态）
- [ ] **Step 5:** Commit `feat(ui): 设置面板渐进披露（预设优先+高级折叠+元数据去重）`

---

### Task 5: 文件表格与上传体验

**Files:**
- Modify: `src/hac/static/styles.css`
- Modify: `src/hac/static/app.js`

**设计：**
1. **空列自动隐藏**：`renderFiles()` 中对当前 9 列计算「全列空」→ 该列 `<th>/<td>` 加 `.col-auto-hidden`（与用户手动列设置取与；「列 ▾」勾选仍生效）
2. **空状态重做**：`#file-empty` 改为图标 + 文案 + 真实 `<label for="file-input" class="btn primary">添加文件</label>` CTA
3. **拖放区视觉**：读 app.js 现有 dragover/drop 监听点，在其上切换 `body.dropping`，`.layout::after` 显示全屏虚线框 + 「松开以添加文件」遮罩（只加视觉层，不重复绑定 drop 逻辑）
4. **键盘重排替代（WCAG 2.2 AA）**：每行操作列在 hover/focus-within 时显示 `↑ ↓` 小按钮（`i-arrow-up/i-arrow-down`，视觉 28px + hit area 扩到 44px），调用/新增 `moveUpload(id, delta)`
5. 行删除 ✕ 触控区扩到 ≥40px

- [ ] **Step 1:** 读 app.js 现有 drag/move/drop 逻辑确认挂点
- [ ] **Step 2:** 实现空列隐藏 + 空状态 + dropzone 视觉 + 键盘重排
- [ ] **Step 3:** pytest + E2E part1 + part3（排序/列设置相关用例）全绿
- [ ] **Step 4:** 截图展示（空状态 / 有数据 / 拖放态）
- [ ] **Step 5:** Commit `feat(ui): 表格空列隐藏+空状态+拖放视觉+键盘重排`

---

### Task 6: 任务面板与全局可访问性

**Files:**
- Modify: `src/hac/static/index.html`
- Modify: `src/hac/static/styles.css`
- Modify: `src/hac/static/app.js`

**设计：**
1. 任务卡重做：顶部状态条（色条按状态 queued 灰/running 蓝/merging 橙/done 绿/failed 红）；`.pbar > div` 渐变保留（E2E 契约）；错误区 `role=alert`
2. `#job-list` 加 `aria-live="polite"`；`#toast` 加 `role="status"`；`#upload-progress` 加 `aria-live="polite"`
3. 任务空状态：图标 + 「选择文件后点开始转换」+ 指向 `#btn-start` 的按钮（点击滚动+聚焦）
4. 全站焦点走查：`.pop` 关闭与 focus 管理；装饰性 `<use>` 图标加 `aria-hidden="true"`
5. 表格 `<th>` 加 `aria-sort`（ascending/descending/none）

- [ ] **Step 1:** 任务卡样式 + 空状态 + role/aria 补齐
- [ ] **Step 2:** pytest + E2E part4（多任务流程）+ part3 全绿
- [ ] **Step 3:** 截图展示（运行中任务卡）
- [ ] **Step 4:** Commit `feat(ui): 任务面板重做 + aria-live/role 补齐`

---

### Task 7: 响应式与收尾验证

**Files:**
- Modify: `src/hac/static/styles.css`
- Modify: `docs/01-design.md`（追加「设计系统」章节：token 表、图标清单、布局规则）

**设计：**
- 断点：≤1440px 侧栏 340px；≤1100px 单列（侧栏下移，文件区在前）；≤768px 面板 padding 12px；表格容器始终 `overflow-x:auto`
- 触控目标最终走查：所有可点元素 ≥40px 视觉 / ≥44px hit
- reduced-motion / focus-visible 全站走查

- [ ] **Step 1:** 响应式规则 + 收尾样式统一
- [ ] **Step 2:** `uv run pytest -q` → 60/60
- [ ] **Step 3:** `./scripts/run-e2e.sh` 全量 → 74/74
- [ ] **Step 4:** 375/768/1100/1440 四档截图，向用户展示
- [ ] **Step 5:** Commit `feat(ui): 响应式收尾 + 设计系统文档`

---

## Self-Review 结论

- **Spec 覆盖**：诊断的 16 项问题 → T1(6/7/9) T2(7) T3(1/2/3) T4(15/16) T5(4/5/10/14) T6(11/12/13) T7(12/13)，全部有对应任务 ✓
- **占位符**：无 TBD/TODO；app.js 挂点已注明「先读确认」的具体范围 ✓
- **契约一致性**：所有 E2E 选择器已逐条列出并锁定 ✓
