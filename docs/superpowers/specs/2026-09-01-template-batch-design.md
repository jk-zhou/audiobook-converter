# 子项目 C · 模板语法 + 批量重命名/写 tag 设计

> 状态：已批准（2026-09-01）
> 范围：模板引擎（parse/render/match 双向）、TrackNum 特殊处理（零填充 + track/total）、转码侧模板升级、uploads/outputs 批量重命名 + mutagen 写 tag、嵌入式批处理 UI（含实时预览）
> 不做：新目录/zip 导出策略、.bak 备份、撤销窗口、书库文件重命名、CA 式预设管理

## 1. 模板引擎（`hac/template.py`）

### 1.1 语法

```
${Field}      必填字段（反向解析：缺失则该文件匹配失败）
${Field?}     可选字段（缺失 → 空串）
${Field:N}    零填充 N 位（仅 int 字段）
字面量：其余字符原样
```

8 字段与匹配规则（沿用 05 草案 §10.1 表）：

| 字段 | 类型 | 匹配正则 |
|---|---|---|
| TrackNum | int | `\d+`（另支持 `\d+/\d+` track/total 形态） |
| TrackTitle | str | 贪婪 |
| Artist | str | 贪婪 |
| Album | str | 贪婪 |
| Year | int | `\d{4}` |
| Genre | str | 贪婪 |
| DiscNum | int | `\d+` |
| Composer | str | 贪婪 |

### 1.2 贪婪边界（修正草案已知问题）

多贪婪字段必须由字面量分隔。反向匹配算法：
1. 模板按字面量 segment 切分成锚点序列
2. 文件名（去扩展名）依次查找锚点 → 相邻锚点之间的文本归属其前的贪婪字段
3. 两个贪婪字段相邻（中间无字面量）→ 回溯切分不唯一 → 该文件报「模板歧义」错误（预览标红，不阻塞其它文件）
4. 模板无任何字面量且字段数 >1 → API 参数校验直接拒绝
5. 首尾锚点缺失时对应位置为贪婪字段 → 允许，但同模板内冲突时优先报歧义

### 1.3 TrackNum 特殊处理

| 场景 | 行为 |
|---|---|
| 正向渲染文件名 | `${TrackNum:3}` → `001`；`${TrackNum}` → 原值 |
| 正向写 tag | track 字段写 `N/total`（total = 任务池文件数，如 `1/294`）；现有「源无 track 用列表顺序」逻辑保留 |
| 反向解析 | `1/294` → TrackNum=1, TrackTotal=294；`01`/`1` → TrackNum；`TrackTotal` 不参与文件名模板但写入 tag |
| tag 容器格式 | MP4: `trkn` atom 自带 `(track, total)` 二元组；ID3v2: TRCK=`1/294`；Vorbis: TRACKNUMBER + TRACKTOTAL |

### 1.4 转码侧升级

- 「标题来源 → 自定义 pattern」改用新引擎：现有 `${TrackNum:3}` 语法为其子集，向后兼容（会话中已存的 pattern 不失效）
- 新增「输出文件名模板」输入（默认空 = 维持现状 `{源文件名 stem}.{ext}`），支持全部 8 字段；仅 single 模式生效（merge 产物名由书名决定）
- 校验：模板含未知字段/语法错误 → 保存时报错（err-hint 内联）

## 2. 批处理执行（`hac/batch.py` + `hac/tagwriter.py`）

### 2.1 对象池与动作

| 池 | 文件位置 | 重命名实现 | 附加影响 |
|---|---|---|---|
| uploads | `data/uploads/{id}_{name}` | 磁盘 rename 为 `{id}_{newname}`；注册表（内存 + DB）name 更新 | 工作集按 id 引用不受影响；历史任务 source_names 快照不变（历史就是历史） |
| outputs | `data/outputs/{job_id}/{filename}` | 磁盘 rename；jobs 记录 output_filename 更新 | 下载端点指向新名 |

### 2.2 写 tag（mutagen，新增依赖）

- 支持：.m4a/.m4b（MP4）、.mp3（ID3v2）、.flac（Vorbis）、.ogg/.opus（Vorbis）
- 字段级勾选（writeFields）：title / artist / album / track(+total) / year / genre / disc / composer
- 不勾 tag 时纯重命名
- mutagen 直接改 tag 容器不动音频流（毫秒级）；不做 .bak（写错可重复执行修正；预览确认是第一道防线）
- 正被运行中任务引用的文件：跳过（复用 `referenced_by_active`）
- 书库文件（lib: 前缀）：不在批处理池（只读挂载）

### 2.3 冲突与错误分类

每文件独立结果：`ok` / `skipped`（locked、无法解析、目标名冲突）+ 原因。目标名冲突判定：新名 == 池内任一现存名且 id 不同 → 拒绝。执行是逐文件独立事务：单文件失败不回滚其它。

## 3. API

```
POST /api/batch/preview
  {pool: "uploads"|"outputs", ids: [...], template: str, writeFields?: [...]}
  → {results: [{id, name, fields: {...}, new_name, tag_changes: {...}, status, reason}]}

POST /api/batch/execute   同参数
  → {report: {ok: n, skipped: n, failed: n, details: [...]}}
```

- preview 纯函数无副作用；execute 前端必须先调 preview 并展示（UI 强制流程）
- 转码侧无需新端点（模板在 job 内部解析）；`/api/jobs` 的 title_pattern 校验升级为模板校验

## 4. UI（嵌入「已上传文件」tab + 任务卡片）

- 工具行新增「批量处理」按钮（勾选 ≥1 文件启用）→ 右侧抽屉面板（drawer）：
  1. 顶部：池信息（已选 N 个文件 · uploads 池）
  2. 模板输入框 + 字段 chip 点击插入（8 字段，插入 `${Field}` 形式）；旁边「示例」按钮填入常见模板
  3. **实时预览表**（防抖 300ms 调 preview）：原文件名 → 解析字段 chips（缺失灰显）→ 新文件名（冲突/歧义标红 + 原因）→ tag 变更摘要
  4. 写 tag 勾选区（8 字段 checkbox，默认全不勾 = 纯重命名）
  5. 「执行」按钮 → 结果报告（ok/skipped/failed 计数 + 明细折叠）
- 任务卡片产物行加「批量处理」入口（pool=outputs，预选该任务全部产物）
- a11y：drawer 焦点圈闭、Esc 关闭、aria-label 齐全

## 5. UX 候选落位

- 「模板实时预览」✓ 本子项目落地
- 「失败任务智能诊断」不在本子项目（归 D 或收尾）

## 6. 测试

**单元**（pytest）：
- parse：全字段、optional、零填充、非法字段名、无字面量多字段拒绝
- render：TrackNum 零填充、缺字段 optional/必填行为、Unicode 字面量
- match：`第${TrackNum}集 ${TrackTitle}` 类真实文件名、`1/294` 解析、贪婪歧义报错、锚点回溯
- batch：uploads rename 后注册表一致性（内存+DB+磁盘三方）、locked 跳过、冲突拒绝
- tagwriter：fixture m4a/mp3/flac 写入后 mutagen 回读断言（含 track/total）

**E2E**（新增 part5 或并入 part2）：
- 勾选 3 文件 → 预览表渲染 → 执行 → ffprobe 回读新名与 tag
- 歧义模板标红且执行跳过该文件
- 转码 pattern 模板：`${TrackNum:3} ${TrackTitle}` 生成标题断言

## 7. 风险与边界

- mutagen 新依赖（纯 Python，无 C 扩展，体积小）
- 贪婪歧义是模板匹配的固有约束：文档写明「模板必须含字面量分隔符」的最佳实践
- 大池（294 文件）预览：preview 一次返回全部（纯字符串运算，性能无虞）
