# 04 · 验收标准（Verification）

> **原则**（Karpathy #4）：每个功能都必须有可验证的成功标准，循环验证
> **执行人**：开发完成后按本文件逐项跑通；任何一项不过 = 该功能不算完成

---

## 1. MVP 验收（v0.1 必过）

### Test 1：单文件上传

**操作**：拖一个 50MB FLAC 到上传区

**期望**：
- [ ] 浏览器看到上传进度条（不是瞬间到 100%）
- [ ] 上传完成后文件出现在"Files"列表
- [ ] 列表项显示文件名、文件大小、时长
- [ ] 服务端目录 `data/uploads/` 出现新文件

**验证命令**：
```bash
ls -la data/uploads/
# 应该看到 {file_id}_chapter1.flac，大小接近 50MB
```

### Test 2：选预设 → 自动填表

**操作**：点击预设下拉框，选 "Opus 中 (48k VBR)"

**期望**：
- [ ] Format 字段自动填 "opus"
- [ ] Codec 字段自动填 "libopus"
- [ ] Bitrate 字段自动填 "48k"
- [ ] Samplerate 字段自动填 "24000"
- [ ] Channels 字段自动填 "1"
- [ ] Filename 字段自动填 `原名_opus_48k.opus`

### Test 3：手动改字段 → 预设重置

**操作**：选完 Opus 中预设后，手动把 Bitrate 改成 "32k"

**期望**：
- [ ] 预设下拉框自动切回 "— 自定义 —"

### Test 4：转码进度实时显示 ⭐ 核心

**操作**：选 Opus 中(48k) → 点 Start Conversion

**期望**：
- [ ] Jobs 列表出现新任务，状态 "running"
- [ ] 进度条从 0% 逐步增长（**不是瞬间跳到 100%**，也不是假的固定速度）
- [ ] 进度变化是连续的、单调递增的
- [ ] 进度数字与进度条一致

**判断假进度**：如果进度条总是均匀地每隔 1 秒跳一次（如 0%, 33%, 66%, 100%），说明解析 FFmpeg stderr 失败了。

### Test 5：输出文件正确（Opus 三档）

**操作**：用同一个 1h WAV 文件分别跑 Opus 低/中/高三档

**验证命令**（每档一次）：
```bash
ffprobe -v quiet -print_format json -show_format -show_streams output.opus | jq '{codec: .streams[0].codec_name, bitrate: .format.bit_rate, samplerate: .streams[0].sample_rate, channels: .streams[0].channels}'
```

**期望**：

| 档位 | codec_name | bit_rate | samplerate | channels |
|---|---|---|---|---|
| Opus 低(32k) | opus | ~32000 | 24000 | 1 |
| Opus 中(48k) | opus | ~48000 | 24000 | 1 |
| Opus 高(64k) | opus | ~64000 | 24000 | 1 |

**容差**：bit_rate 允许 ±5%（VBR 模式下不是精确值）

### Test 6：文件体积对比

**操作**：用同一个 1h 原始 WAV（约 600 MB）跑 Opus 三档

**期望**：

| 输入 | 输出 | 压缩比 |
|---|---|---|
| WAV 1h (600 MB) | Opus 低 (~14 MB) | ~43x |
| WAV 1h (600 MB) | Opus 中 (~21 MB) | ~29x |
| WAV 1h (600 MB) | Opus 高 (~28 MB) | ~21x |

### Test 7：元数据嵌入（MP3/FLAC/MP4/Opus）

**操作**：填 Title="测试标题", Artist="测试艺术家" → 转码

**验证命令**：
```bash
# Opus / FLAC / OGG 用 vorbis comment
ffprobe -v quiet -show_format output.opus | grep -E "TITLE|ARTIST"
# MP3 用 ID3
ffprobe -v quiet -show_format output.mp3 | grep -E "title|artist"

# 或用 mutagen 直接验证
python3 -c "
from mutagen import File
f = File('output.opus')
print(dict(f.tags))
"
```

**期望**：
```
TITLE=测试标题
ARTIST=测试艺术家
```

### Test 8：元数据继承（未填字段从源文件复制）

**操作**：源文件 tag 有 Album="原专辑"，转换时 Album 字段留空

**期望**：
- [ ] 输出文件 Album = "原专辑"（自动继承）
- [ ] 用户填的字段覆盖源文件

### Test 9：下载

**操作**：任务完成后点击下载按钮

**期望**：
- [ ] 浏览器触发下载
- [ ] 文件名是用户设置的（如 `chapter1_opus_48k.opus`）
- [ ] 文件大小与 ffprobe 显示的 size 一致
- [ ] 下载的文件用播放器能正常播放

### Test 10：取消任务

**操作**：转码中途点取消

**期望**：
- [ ] FFmpeg 子进程在 5s 内退出
- [ ] 任务状态变 "cancelled"
- [ ] 输出文件被标记 `.partial` 后缀
- [ ] 点击下载返回 404（或"文件不存在"）

### Test 11：多文件批量

**操作**：上传 5 个 FLAC → 选 Opus 中 → Start

**期望**：
- [ ] 创建 5 个任务（不一定并发跑，看 MAX_CONCURRENT_JOBS 设置）
- [ ] 每个任务独立显示进度
- [ ] 所有任务完成后，总进度 100%

---

## 2. API 验收（curl 层面）

### Test A1: 上传

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "files=@test.flac" \
  -F "files=@test2.mp3" | jq

# 期望
# {"uploads": [{"id": "abc123", "name": "test.flac", ...}, ...]}
```

### Test A2: 创建任务

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "abc123",
    "output_filename": "test_opus_48k",
    "settings": {
      "format": "opus",
      "codec": "libopus",
      "bitrate": "48k",
      "vbr": "on",
      "samplerate": 24000,
      "channels": 1,
      "compression_level": 10
    },
    "metadata": {"title": "测试"}
  }' | jq

# 期望: {"job_id": "job_xyz"}
```

### Test A3: 查任务

```bash
curl http://localhost:8000/api/jobs | jq
# 期望: 完整任务列表
```

### Test A4: SSE 连接

```bash
curl -N http://localhost:8000/api/events
# 期望: 持续收到 job.update / job.list / keepalive 事件
```

### Test A5: 删除任务

```bash
curl -X DELETE http://localhost:8000/api/jobs/job_xyz
# 期望: {"ok": true}
```

### Test A6: 获取预设

```bash
curl http://localhost:8000/api/presets | jq
# 期望: 3 个预设（FDK-AAC 被过滤），每个含 settings/extension/filename_suffix
```

### Test A7: 探测源文件

```bash
curl http://localhost:8000/api/probe/abc123 | jq
# 期望: {"duration": 3600.5, "channels": 2, "samplerate": 44100, ...}
```

---

## 3. 性能验收（非强制，但记录）

### Test P1: 转码速度

**操作**：转一个 1h Opus 高(64k)

**期望**：
- [ ] 在 4 核 CPU 上，转码时间 < 5 分钟（即 > 12x 实时速度）
- [ ] 多文件并发（2 个）时，CPU 利用率 > 150%（说明真在并行）

### Test P2: 上传速度

**操作**：浏览器上传 500MB WAV（接近上限）

**期望**：
- [ ] 上传时间接近网络带宽决定的时间（无明显服务器瓶颈）
- [ ] 服务端内存占用 < 100MB（说明流式读生效）

### Test P3: SSE 连接数

**操作**：开 5 个浏览器标签页同时连 SSE

**期望**：
- [ ] 5 个连接都收到 job.update（无丢失）
- [ ] 服务端内存增长 < 10MB / 连接

---

## 4. 主观验收（听感）

**操作**：同一段 5 分钟有声书（人声为主）：
1. 原始 WAV（参考）
2. Opus 低(32k)
3. Opus 中(48k)
4. Opus 高(64k)

**对照听感标准**：

| 档位 | 听感 |
|---|---|
| 原始 | 完整频响，无压缩 |
| Opus 低(32k) | 极小体积，人声清晰，背景音乐丢失高频；窄带特征（NB）可听出 |
| Opus 中(48k) | 平衡，标准宽带（SWB），适合大多数场景 |
| Opus 高(64k) | 高质量，与原始难以分辨差异 |

**判断依据**：
- 能听出"低频丢失/闷" → 档位过低
- 与原始无差异 → 档位过高（浪费空间）
- **48k 通常是甜点**

---

## 5. 边界情况验收

### Test E1: 损坏的输入文件

**操作**：上传一个扩展名是 .flac 但内容是文本的文件

**期望**：
- [ ] ffprobe 返回错误或 duration=0
- [ ] 任务创建时立即标记 failed
- [ ] 不崩溃、不占内存

### Test E2: 空文件

**操作**：上传 0 字节文件

**期望**：
- [ ] 上传返回 400 + 错误信息
- [ ] 任务不创建

### Test E3: 超大文件

**操作**：上传 600MB（超过 MAX_UPLOAD_SIZE_MB=500）

**期望**：
- [ ] 返回 413
- [ ] 服务端磁盘不留下未完成文件

### Test E4: 同名文件

**操作**：上传两个同名 `chapter.flac`

**期望**：
- [ ] 两个文件都成功上传（用不同 file_id 区分）
- [ ] 转码后输出文件名带 job_id 前缀或不同后缀，避免覆盖

### Test E5: 不支持的输入格式

**操作**：上传一个 `.wma` 或 `.aiff`（部分格式 ffmpeg 可能不支持或 codec 未编译）

**期望**：
- [ ] 任务标记 failed
- [ ] 错误信息明确指出 codec 不支持
- [ ] 不影响其他任务

---

## 6. 自动化测试（pytest）

### 必须通过的单元测试

```python
# tests/test_presets.py
def test_opus_low_builds_correct_ffmpeg_args():
    """验证 Opus 低(32k) 预设生成正确的 ffmpeg 命令"""

def test_opus_mid_builds_correct_ffmpeg_args():
    """验证 Opus 中(48k) 预设"""

def test_opus_high_builds_correct_ffmpeg_args():
    """验证 Opus 高(64k) 预设"""

def test_aac_preset_disabled():
    """FDK-AAC 预设默认 disabled"""

def test_get_enabled_presets_filters_disabled():
    """/api/presets 只返回 enabled=True 的"""

# tests/test_progress.py
def test_progress_parser_handles_carriage_return():
    """FFmpeg 用 \\r 分隔进度块"""

def test_progress_parser_handles_partial_chunks():
    """跨 chunk 边界不丢数据"""

def test_calc_progress_normalized_correctly():
    """time_us / total_duration 归一化到 0-100"""

def test_calc_progress_handles_zero_duration():
    """total_duration_sec=None 时返回 0 不崩溃"""

# tests/test_metadata.py
def test_write_tags_mp3():
    """MP3 ID3 tag 写入"""

def test_write_tags_flac():
    """FLAC Vorbis Comment 写入"""

def test_write_tags_opus():
    """Opus Vorbis Comment 写入"""

def test_metadata_inherits_unset_fields():
    """未填字段从 inherited dict 继承"""

# tests/test_jobs.py
def test_job_manager_concurrency_limit():
    """Semaphore 限制并发数"""

def test_job_manager_cancel_running_job():
    """取消任务时 FFmpeg 被 SIGTERM"""

def test_job_manager_broadcasts_events():
    """状态变化触发 SSE 事件"""
```

**目标**：所有测试通过 = MVP 完成

---

## 7. 验收签字

每个验证项完成后，在文档里勾选：

```markdown
## 验收记录

- 日期：____
- 执行人：____
- v0.1 MVP: ☐ 通过 / ☐ 不通过
- 失败项（如有）：____
```

---

## 8. 回归测试清单（每次改动后跑）

即使不在开发新功能，每次代码改动后必跑：

- [ ] Test 4（转码进度实时显示）—— 核心功能，不能坏
- [ ] Test 5（输出文件正确）—— 数据真实性
- [ ] Test 7（元数据嵌入）—— 用户最常用的功能
- [ ] Test 10（取消任务）—— 错误路径
- [ ] 单元测试全部通过

任何一项失败 = 阻塞合并。

---

## 9. v0.2 验收：模板解析

### Test T1：基础模板匹配

**操作**：模板 `第${TrackNum}集 ${TrackTitle} - ${Artist}.m4a`

**期望**：

| 文件 | TrackNum | TrackTitle | Artist |
|---|---|---|---|
| 第01集 哈利波特与凤凰社 - J.K.罗琳.m4a | 1 | 哈利波特与凤凰社 | J.K.罗琳 |
| 第02集 神秘的房间 - J.K.罗琳.m4a | 2 | 神秘的房间 | J.K.罗琳 |
| 第19集 阿兹卡班囚徒 - J.K.罗琳.m4a | 19 | 阿兹卡班囚徒 | J.K.罗琳 |

### Test T2：前导零处理（宽松模式）

**操作**：模板 `第${TrackNum:3}集 ${TrackTitle}.m4a` + 宽松模式

**期望**：

| 文件 | TrackNum（解析） | TrackNum（写入） |
|---|---|---|
| 第001集 HP.m4a | 1 | 001/2452 |
| 第01集 HP.m4a | 1 | 001/2452 |
| 第1集 HP.m4a | 1 | 001/2452 |

### Test T3：前导零处理（严格模式）

**操作**：模板 `第${TrackNum:3}集 ${TrackTitle}.m4a` + 严格模式

**期望**：

| 文件 | 行为 |
|---|---|
| 第001集 HP.m4a | ✓ 匹配，TrackNum=1 |
| 第01集 HP.m4a | ✗ 不匹配（必须恰好 3 位） |
| 第1集 HP.m4a | ✗ 不匹配 |

### Test T4：Year 严格 4 位

**操作**：模板 `(${Year}) ${TrackTitle}.mp3`

**期望**：

| 文件 | 行为 |
|---|---|
| (2003) Harry Potter.mp3 | ✓ year=2003 |
| (20) Harry Potter.mp3 | ✗ 不匹配（必须 4 位） |
| (20035) Harry Potter.mp3 | ✗ 不匹配（必须恰好 4 位） |

### Test T5：可选字段

**操作**：模板 `Ch${TrackNum} - ${TrackTitle?}.mp3`

**期望**：

| 文件 | TrackNum | TrackTitle |
|---|---|---|
| Ch01 - The Beginning.mp3 | 1 | The Beginning |
| Ch02.mp3 | 2 | None（可选，缺失不报错） |

### Test T6：模板不匹配 → 跳过

**操作**：模板 `第${TrackNum}集 ${TrackTitle}.m4a` + `skip_unmatched=True`

**期望**：

| 文件 | 行为 |
|---|---|
| 第01集 HP.m4a | ✓ applied |
| 第02集.m4a | ✓ applied（TrackTitle fallback） |
| Ch01 Harry Potter.mp3 | ⏭️ skipped（不匹配） |
| 第XX集 Bad.mp3 | ⏭️ skipped（TrackNum 不是数字） |

### Test T7：TrackTitle fallback

**操作**：模板 `第${TrackNum}集 ${TrackTitle}.m4a`

**期望**：

| 文件 | TrackTitle | fallback_notes |
|---|---|---|
| 第01集 哈利波特.m4a | 哈利波特 | (空) |
| 第02集.m4a | 第02集 | ["TrackTitle 从文件名 '第02集' 替代"] |

### Test T8：AlbumArtist 三种模式

**操作**：

模式 A — 复制 Artist（默认）：
- 文件 1: `Ch01 - HP - J.K.罗琳.m4a` → TPE2="J.K.罗琳"
- 文件 2: `Ch02 - Stand - Stephen King.m4a` → TPE2="Stephen King"

模式 B — 用户输入 "JK Rowling"：
- 文件 1: `Ch01 - HP - J.K.罗琳.m4a` → TPE2="JK Rowling"
- 文件 2: `Ch02 - Stand - Stephen King.m4a` → TPE2="JK Rowling"

模式 C — 留空：
- 文件 1: `Ch01 - HP - J.K.罗琳.m4a` → (不写 TPE2)
- 文件 2: `Ch02 - Stand - Stephen King.m4a` → (不写 TPE2)

### Test T9：TrackNum 写入格式

**操作**：2452 个文件，TrackNum 从 1 到 2452，零填充 3 位

**期望**：
- 所有文件写入 `TRCK` = `"001/2452"`, `"002/2452"`, ..., `"2452/2452"`
- Apple Books 按数字排序正确

### Test T10：批量应用报告

**操作**：2452 个文件，模板匹配后 apply

**期望**：

```json
{
  "total": 2452,
  "applied": 2401,
  "skipped": 48,
  "error": 3,
  "details": [
    {"file_id": "abc", "status": "applied", "parsed": {...}},
    {"file_id": "def", "status": "skipped", "reason": "模板不匹配"},
    ...
  ]
}
```

---

## 10. v0.2 验收：反向重命名

### Test R1：基础反向模板

**操作**：正向模板解析后，字段值为 `{album: "HP", track_num: 1, track_title: "The Beginning"}`
反向模板：`${Album} - Ch${TrackNum:3} - ${TrackTitle}.opus`

**期望输出**：`HP - Ch001 - The Beginning.opus`

### Test R2：特殊字符 sanitize

**操作**：反向模板生成的文件名包含 `/`、`:`、`?`

**期望**：
- `/` → `-`
- `:` → `-`
- `?` → ``（删除）

**示例**：
```
原始: "Chapter 1: The Beginning / Part A?"
sanitize: "Chapter 1- The Beginning - Part A"
```

### Test R3：冲突检测 + 自动后缀

**操作**：批量重命名，两个文件生成相同的新文件名

**期望**：
- 第一个文件：`Ch001 - HP.opus`
- 第二个文件：`Ch001 - HP-1.opus`

### Test R4：原地重命名 + .bak 备份

**操作**：原地重命名，`backup=True`

**期望**：
- 旧文件：`chapter1.mp3`
- 新文件：`HP - Ch001 - HP.opus`
- 备份文件：`chapter1.mp3.bak`（旧文件副本）

### Test R5：强制预览

**操作**：调用 `/api/rename/apply` 前必须先调用 `/api/rename/preview`

**期望**：
- preview 返回完整的新文件名列表（含冲突标记、是否清理）
- apply 才真正执行
- 前端 UI：预览表格 → "确认并执行"按钮 → 才发起 apply

### Test R6：新目录策略

**操作**：`strategy=NEW_DIR`，原目录 `/data/uploads/`

**期望**：
- 生成目录：`/data/uploads/renamed_{timestamp}/`
- 文件移入新目录
- 原目录文件保留

---

## 11. v0.2 验收：API 端到端

### Test API-T1：解析模板语法

```bash
curl -X POST http://localhost:8000/api/template/parse \
  -H "Content-Type: application/json" \
  -d '{"template": "第${TrackNum}集 ${TrackTitle}.m4a"}'

# 期望返回:
# {"segments": [
#   {"kind": "literal", "value": "第"},
#   {"kind": "field", "value": "TrackNum", "optional": false, "format_spec": null},
#   {"kind": "literal", "value": "集 "},
#   {"kind": "field", "value": "TrackTitle", "optional": false, "format_spec": null},
#   {"kind": "literal", "value": ".m4a"}
# ]}
```

### Test API-T2：试运行匹配

```bash
curl -X POST http://localhost:8000/api/template/match \
  -H "Content-Type: application/json" \
  -d '{
    "template": {
      "template": "第${TrackNum}集 ${TrackTitle} - ${Artist}.m4a",
      "track_num_config": {"zero_pad": 3, "include_total": true, "total_value": 2452}
    },
    "file_ids": ["abc", "def", "ghi"]
  }'

# 期望返回每个文件的匹配结果
```

### Test API-T3：应用模板（dry_run）

```bash
curl -X POST http://localhost:8000/api/template/apply \
  -H "Content-Type: application/json" \
  -d '{
    "template": {...},
    "dry_run": true
  }'

# dry_run=true 不写入，仅返回"将要做什么"
```

### Test API-T4：重命名预览

```bash
curl -X POST http://localhost:8000/api/rename/preview \
  -H "Content-Type: application/json" \
  -d '{
    "template": "${Album} - Ch${TrackNum:3} - ${TrackTitle}.opus",
    "field_source": "template_parse",
    "strategy": "in_place"
  }'

# 期望返回每个文件的 old_path → new_path + 冲突标记
```

---

## 12. v0.2 验收：单元测试

```python
# tests/test_template.py

class TestParseTemplate:
    def test_simple_field(self):
        """${TrackNum} 解析为单个 field segment"""

    def test_with_literal(self):
        """'第${TrackNum}集' 解析为 literal + field + literal"""

    def test_optional_marker(self):
        """${TrackNum?} 标记为 optional=True"""

    def test_zero_pad_format(self):
        """${TrackNum:3} 标记为 format_spec='3'"""

    def test_multiple_fields(self):
        """多个字段正确解析"""

    def test_invalid_template_raises(self):
        """语法错误抛出 ValueError"""

class TestMatchFilename:
    def test_basic_match(self):
        """基本模板匹配"""

    def test_optional_field_missing(self):
        """可选字段缺失填 None，不报错"""

    def test_no_match_returns_none(self):
        """模板不匹配返回 None"""

    def test_tracknum_strict_pad(self):
        """严格模式：必须 N 位"""

    def test_tracknum_loose_pad(self):
        """宽松模式：去前导零"""

    def test_year_strict_4_digits(self):
        """Year 必须恰好 4 位"""

    def test_greedy_with_separator(self):
        """贪婪字段被后续 literal 截断"""

class TestRenderFilename:
    def test_basic_render(self):
        """基本反向模板渲染"""

    def test_zero_pad_in_render(self):
        """${Num:3} 渲染时格式化"""

    def test_missing_optional_field(self):
        """可选字段缺失渲染为空字符串"""

    def test_missing_required_raises(self):
        """必填字段缺失抛 ValueError"""

class TestApplyTemplate:
    def test_tracktitle_fallback_to_filename(self):
        """TrackTitle 缺失时用文件名（去扩展名）"""

    def test_album_artist_copy_mode(self):
        """AlbumArtist = Artist"""

    def test_album_artist_user_mode(self):
        """AlbumArtist = 用户输入值"""

    def test_album_artist_empty_mode(self):
        """AlbumArtist 模式 = 空时不写入"""

    def test_track_num_with_total(self):
        """TrackNum 格式化为 '001/2452'"""

    def test_skip_unmatched_files(self):
        """skip_unmatched=True 时不匹配的文件跳过"""

class TestSanitizeFilename:
    def test_replace_slash(self):
        """'/' → '-'"""

    def test_replace_colon(self):
        """':' → '-'"""

    def test_replace_question(self):
        """'?' → ''"""

    def test_strip_trailing_dot_space(self):
        """尾部 '.' 和空格被去除"""

class TestResolveConflict:
    def test_no_conflict_returns_original(self):
        """无冲突时返回原名"""

    def test_conflict_adds_suffix(self):
        """冲突时加 -1, -2 后缀"""

    def test_multiple_conflicts(self):
        """多个冲突按递增数字处理"""
```

**目标**：v0.2 单元测试 ≥ 20 个全部通过

---

## 13. v0.2 验收：Apple Books 导入验证

**真实环境测试**（用户在自己的 macOS 上做）：

1. 准备 2452 个章节的音频文件
2. 用本工具批量应用模板 + 写入元数据
3. **验证 ID3 字段**：
   ```bash
   ffprobe -v quiet -show_format file1.m4a | grep -E "title|artist|album|track"
   # 期望：title=..., artist=..., album=..., TRCK=001/2452, TPE2=...
   ```
4. **导入 Apple Books**：
   - 选中所有文件 → 右键 → Open With → Books
5. **验证导入后排序**：
   - 打开 Books.app → 进入该书
   - 检查章节列表是否按 001, 002, ..., 2452 顺序排列
6. **验证导入速度**：
   - 对比"导入未处理的 2452 个文件"和"导入处理后的 2452 个文件"的耗时
   - 期望：处理后导入至少快 30%（因为 Books 无需重新解析元数据）
