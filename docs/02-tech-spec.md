# 02 · 技术实现规格（Tech Spec v2）

> **版本**：v2（2026-08-30 重写）—— 取代 MiniMax M3 起草的 v1（已发现 9 处实现级 bug，见 §14）。
> **范围**：v0.1 MVP + 8 项改进（M4B 合并 / 本地目录导入 / loudnorm / zip / 任务管理 / 验证面板 / 上传进度 / 封面）。
> **回答的问题**：数据结构、API、FFmpeg 命令怎么拼、错误怎么处理。
> **v0.2 模板批处理规格**已迁至 `05-v0.2-spec-draft.md`，本文不含。

---

## 1. 依赖与二进制解析

### 1.1 Python 依赖

```toml
[project]
name = "audiobook-converter"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "python-multipart>=0.0.9",
    "sse-starlette>=2.0",
    "mutagen>=1.47",
    "pydantic>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "httpx>=0.27"]
```

> **v1 的错误**：v1 依赖 `imageio-ffmpeg`，但该包**只提供 ffmpeg、不含 ffprobe**（v1 注释"同一二进制也含 ffprobe"是错的），且静态包不含 libfdk_aac。v2 弃用 imageio-ffmpeg。

### 1.2 FFmpeg / FFprobe 二进制解析顺序

```python
# config.py
def resolve_binary(name: str, env_key: str) -> Path | None:
    # 1. 显式环境变量 HAC_FFMPEG_PATH / HAC_FFPROBE_PATH
    # 2. vendor/bin/<name>  （scripts/setup-ffmpeg.sh 下载的 BtbN 静态构建，含 ffmpeg+ffprobe+libfdk_aac）
    # 3. shutil.which(name)（系统安装兜底）
```

1.2 之补充（2026-08-30 实测修正）：BtbN 最新静态构建**已不含** libfdk_aac；Ubuntu 的 libfdk-aac2 包**缺 SBR/PS 模块**。
需要 HE-AAC 时运行 `scripts/build-he-ffmpeg.sh`（源码编译上游 fdk-aac v2.0.2 + ffmpeg 7.1.1，约 10 分钟）。
应用启动时探测编码器，HE 预设按探测结果自动启用/隐藏——无论哪种 ffmpeg，应用都可用。

### 1.3 编码器探测（encoders.py）

启动时执行一次并缓存：

```python
def detect_encoders(ffmpeg_path: str) -> set[str]:
    """解析 `ffmpeg -hide_banner -encoders` 输出，返回编码器名集合。"""
    # 输出行形如: " A....D libfdk_aac   AAC (Advanced Audio Coding)"
    # 取第 3 列（编码器名）；匹配 libopus / libfdk_aac / aac / libmp3lame
```

- `/api/health` 返回探测结果，前端据此展示"哪些预设可用"
- 预设的 `requires_encoder` 不在集合中 → 该预设**自动禁用**（不再有手写 `enabled=False`）

---

## 2. 数据模型（Pydantic）

### 2.1 TranscodeSettings

```python
Format = Literal["mp3", "m4a", "m4b", "opus", "ogg", "flac", "wav"]

class TranscodeSettings(BaseModel):
    format: Format
    codec: str | None = None            # None = 按格式自动推断
    profile: str | None = None          # libfdk: "aac_he" | "aac_he_v2"
    bitrate: str | None = None          # "32k" | "48k" | "64k" | "128k" ...
    samplerate: int | None = None       # Hz；None = 让编码器决定
    channels: int | None = Field(default=None, ge=1, le=2)
    compression_level: int | None = Field(default=None, ge=0, le=10)  # libopus 专用
    extra_args: list[str] = []          # 高级用户透传
```

> **v1 的 bug（已修）**：v1 有独立 `vbr` 字段，导致 libfdk 分支可能同时输出 `-vbr 3` 和 `-vbr on` → ffmpeg 直接报错。v2 **删除该字段**，VBR 语义内置在参数构造里（§4.1）：
> - `libfdk_aac`：bitrate 存在 → ABR `-b:a`；quality 存在 → VBR `-vbr N`（0-5），**二者互斥**
> - `libopus`：恒为 VBR，`-b:a` 即目标码率，无需额外 flag
> - `libmp3lame`：`-q:a N`

### 2.2 MergeOptions（M4B 合并）

```python
class MergeOptions(BaseModel):
    book_title: str | None = None       # 默认 = 第一个文件 title tag 或目录名
    book_artist: str | None = None      # 作者
    cover_upload_id: str | None = None  # 上传的封面；空则尝试取第一个源的内嵌封面
    normalize: bool = False             # loudnorm 响度归一化
```

### 2.3 Job

```python
class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    TAGGING = "tagging"        # 仅 single 模式（merge 的元数据在 ffmpeg 内完成）
    MERGING = "merging"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

class VerifyInfo(BaseModel):
    codec: str | None = None
    bitrate: int | None = None        # bps，来自 ffprobe
    sample_rate: int | None = None
    channels: int | None = None
    duration: float | None = None
    output_size: int | None = None
    source_size: int | None = None
    savings_pct: float | None = None  # (1 - out/src) * 100

class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    mode: Literal["single", "merge"] = "single"
    source_ids: list[str] = []        # single: 1 个；merge: ≥2 个（有序）
    source_paths: list[Path] = []     # 解析后的实际路径
    output_filename: str
    settings: TranscodeSettings
    merge: MergeOptions | None = None # mode=merge 时必填
    metadata: MetadataEdit = Field(default_factory=MetadataEdit)
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    error: str | None = None
    output_path: Path | None = None
    verify: VerifyInfo | None = None  # ⭐ 完成后 ffprobe 回读
    created_at / started_at / finished_at: datetime
    total_duration_sec: float | None
```

### 2.4 MetadataEdit

```python
class MetadataEdit(BaseModel):
    title / artist / album / albumartist / date / genre / composer: str | None
    track: tuple[int, int] | None     # (number, total)
    disc: tuple[int, int] | None
```

> 封面不再放在 MetadataEdit（仅 merge 用 `MergeOptions.cover_upload_id`；single 模式的封面随源文件标签自动复制）。

### 2.5 Upload（服务端注册表）

```python
class Upload(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    path: Path
    size: int
    info: dict | None = None          # probe 结果（duration 等）
```

内存注册表 `dict[upload_id, Upload]`。**不再用 glob 猜路径**（v1 bug）。

### 2.6 Preset

```python
@dataclass
class Preset:
    id: str
    name: str
    description: str
    settings: TranscodeSettings
    extension: str
    filename_suffix: str
    requires_encoder: str | None = None   # 例 "libfdk_aac"；探测不到 → 禁用

def effective_enabled(p: Preset, encoders: set[str]) -> bool:
    return p.requires_encoder is None or p.requires_encoder in encoders
```

### 2.7 预设清单（6 个）

| id | 名称 | codec | profile | 码率 | 采样率 | 声道 | 扩展名 | requires_encoder |
|---|---|---|---|---|---|---|---|---|
| `audiobook_opus_32k` | Opus 低 32k | libopus | — | 32k | 24000 | 1 | opus | — |
| `audiobook_opus_48k` | Opus 中 48k | libopus | — | 48k | 24000 | 1 | opus | — |
| `audiobook_opus_64k` | Opus 高 64k | libopus | — | 64k | 24000 | 1 | opus | — |
| `audiobook_aac_lc_64k` | AAC-LC 64k (M4A/M4B) | aac（原生） | — | 64k | 24000 | 1 | m4a | — |
| `audiobook_aac_he_48k` | HE-AAC v1 48k | libfdk_aac | aac_he | 48k | — | 1 | m4a | libfdk_aac |
| `audiobook_aac_he_v2_32k` | HE-AAC v2 32k 立体声 | libfdk_aac | aac_he_v2 | 32k | — | 2 | m4a | libfdk_aac |

**设计说明**：
- **HE-AAC v1 而非 v2 用于单声道**：v2 的 Parametric Stereo 只对立体声有效，v1（SBR）才是单声道下 HE 的正确形态。v2 保留为立体声 32k 档。
- HE 档不固定 `-ar`（SBR 双率采样由编码器自决，强制 -ar 可能冲突）；AAC-LC 固定 24000（与 Opus 档一致，符合有声书频带需求）
- AAC-LC 档存在的原因：M4B 合并路线用原生 `aac` 编码器，无任何非自由依赖，任何 ffmpeg 都能跑
- **libfdk 通道数上报 quirk**（实测 2026-08-30）：libfdk HE 输出经 ffprobe 恒报 `channels=2`（SBR 上采样所致），即使请求 `-ac 1`。预设保持 channels=1 的意图（单声道核），验证面板展示编码器真实上报值。

---

## 3. API 设计

### 3.1 路由表

| Method | Path | 用途 | 请求 | 响应 |
|---|---|---|---|---|
| GET | `/` | 前端单页 | — | index.html |
| POST | `/api/upload` | 多文件上传（流式） | multipart `files[]`（+可选 `covers[]`） | `{uploads:[{id,name,size,info}]}` |
| GET | `/api/library/roots` | 白名单根目录 | — | `{roots:[str]}` |
| GET | `/api/library/list?path=` | 浏览白名单目录 | — | `{path, dirs:[], files:[{id,name,size}]}` |
| GET | `/api/presets` | 预设清单（含 enabled 与原因） | — | `[Preset]` |
| POST | `/api/jobs` | 创建任务（单文件或合并） | `JobCreate` | `{job_id}` |
| GET | `/api/jobs` | 全部任务 | — | `[Job]` |
| GET | `/api/jobs/{id}` | 任务详情 | — | `Job` |
| POST | `/api/jobs/{id}/retry` | 重试失败任务 | — | `{ok}` |
| DELETE | `/api/jobs/{id}` | 取消/移除任务 | — | `{ok}` |
| POST | `/api/jobs/cancel-all` | 取消所有排队+运行中 | — | `{ok, cancelled}` |
| POST | `/api/jobs/clear-finished` | 清除已完成/失败/取消 | — | `{ok, removed}` |
| GET | `/api/events` | **SSE 进度流** | — | `text/event-stream` |
| GET | `/api/download/{id}` | 单文件下载 | — | binary |
| GET | `/api/download/zip?ids=a,b,c` | zip 批量下载 | — | binary（临时文件流式） |
| GET | `/api/probe/{upload_id}` | 源文件元信息 | — | probe dict |
| GET | `/api/health` | 健康检查 + 编码器状态 | — | `{status, ffmpeg, encoders, presets_enabled}` |

**JobCreate**（`POST /api/jobs` 二合一）：

```json
// 单文件
{"mode": "single", "source_ids": ["abc"], "output_filename": "...",
 "settings": {...}, "metadata": {...}, "normalize": false}
// 合并
{"mode": "merge", "source_ids": ["a","b","c"], "output_filename": "我的有声书.m4b",
 "settings": {...}, "merge": {"book_title": "...", "book_artist": "...", "cover_upload_id": "x", "normalize": false}}
```

### 3.2 SSE 协议

```
event: job.list     data: [Job,...]        ← 连接建立时一次
event: job.update   data: {Job}            ← 每次状态/进度/verify 变化推完整 Job
event: keepalive    data:                  # 30s 心跳
```

Job JSON 含 `verify`（完成后）与 `error`（失败时 stderr 尾部 500 字符）。

---

## 4. FFmpeg 参数映射

### 4.1 build_ffmpeg_args()（single 模式）

```python
def build_ffmpeg_args(src, dst, settings, normalize=False) -> list[str]:
    args = [FFMPEG, "-y", "-hide_banner", "-nostdin", "-i", src, "-vn", "-map_metadata", "0"]
    if settings.codec: args += ["-c:a", settings.codec]
    if settings.profile: args += ["-profile:a", settings.profile]

    # ⭐ 码率/VBR —— 互斥，修复 v1 双 -vbr 冲突 bug
    if settings.bitrate:
        args += ["-b:a", settings.bitrate]
    elif settings.quality is not None and settings.codec == "libfdk_aac":
        args += ["-vbr", str(settings.quality)]     # FDK VBR 0-5

    if settings.samplerate: args += ["-ar", str(settings.samplerate)]
    if settings.channels:   args += ["-ac", str(settings.channels)]
    if settings.compression_level is not None and settings.codec == "libopus":
        args += ["-compression_level", str(settings.compression_level)]
    if normalize:
        args += ["-af", "loudnorm=I=-20:TP=-3:LRA=11"]
    if settings.extra_args: args += settings.extra_args
    args += ["-progress", "pipe:1", "-nostats", dst]
```

### 4.2 命令实例

**Opus 中 48k**：
```bash
ffmpeg -y -nostdin -i in.flac -vn -map_metadata 0 \
  -c:a libopus -b:a 48k -compression_level 10 -ar 24000 -ac 1 \
  -progress pipe:1 -nostats out.opus
```

**HE-AAC v1 48k 单声道**（libfdk 存在时）：
```bash
ffmpeg -y -nostdin -i in.flac -vn -map_metadata 0 \
  -c:a libfdk_aac -profile:a aac_he -b:a 48k -ac 1 \
  -progress pipe:1 -nostats out.m4a
```
（`aac_he` profile 由 ffmpeg 自动启用 SBR；不传 `-ar`，让编码器自决双率采样。）

**AAC-LC 64k**（M4A/M4B 基础）：
```bash
ffmpeg -y -nostdin -i in.flac -vn -map_metadata 0 \
  -c:a aac -b:a 64k -ar 24000 -ac 1 -progress pipe:1 out.m4a
```

**loudnorm 开启时**：`-af loudnorm=I=-20:TP=-3:LRA=11` 插在输出前。

### 4.3 M4B 合并（merge 模式，merger.py）

**输入**：有序源文件 ≥2、书名/作者、可选封面、AAC-LC 64k 单声道（固定用原生 aac，保证 Apple 兼容）。

**Step 1 —— 探测时长**：逐源 ffprobe → `dur[i]`；总时长 = Σ。

**Step 2 —— 生成 ffmetadata**（时间累积，毫秒，TIMEBASE=1/1000）：

```
;FFMETADATA1
title={book_title}
artist={book_artist}

[CHAPTER]
TIMEBASE=1/1000
START=0
END={dur0}
title={第一个源的 title tag 或文件名 stem}

[CHAPTER]
TIMEBASE=1/1000
START={dur0}
END={dur0+dur1}
title=...
```

**Step 3 —— 生成 concat 滤镜图**（filter_complex 而非 concat demuxer：对异构输入更稳）：

```
[0:a][1:a]...[N-1:a]concat=n=N:v=0:a=1[outa]
```

**Step 4 —— 封面来源**：
1. 用户上传封面（`cover_upload_id`）
2. 否则 mutagen 从第一个源提取内嵌封面 → 临时 jpg/png
3. 都没有 → 不做视频 map（无封面 M4B 合法）

**Step 5 —— 命令**：

```bash
ffmpeg -y -nostdin \
  -i ch01.mp3 -i ch02.m4a ... -i chNN.flac \    # 0..N-1
  -i cover.jpg \          # N（若有）
  -i chapters.txt \       # N+1，ffmetadata
  -filter_complex "[0:a][1:a]...concat=n=N:v=0:a=1[outa]" \
  -map "[outa]" -map N:v -c:a aac -b:a 64k -ar 24000 -ac 1 \
  -c:v mjpeg -disposition:v:0 attached_pic \
  -map_metadata N+1 -map_chapters N+1 \
  -movflags +faststart -f mp4 \
  out.m4b
```

（无封面时去掉 cover 输入与 `-map N:v -c:v`。有 loudnorm 时 filter_complex 追加 `loudnorm` 链。）

**上限**：`MAX_MERGE_INPUTS = 500`（filter graph 长度 & argv 限制），超出报 400。

**进度**：`out_time_us / Σdur` 归一化（输出时长 ≈ 输入和，误差可接受）。

### 4.4 进度解析（与 v1 相同，保留）

- 主通道 `-progress pipe:1`：`out_time_us=` + `progress=continue|end`
- 兜底：stderr `time=HH:MM:SS.ms`
- 进程退出码必须 0；`progress=end` 且 rc=0 才算成功
- `total_duration_sec` 创建 Job 时由 ffprobe 取得（merge = Σ 各源）

### 4.5 取消

- running：SIGTERM ffmpeg → 5s 超时 SIGKILL；输出标记 `.partial`（下载路由拒绝）
- **queued：直接从队列移除置 cancelled**（v1 的 cancel 只找 proc，queued 任务无法取消）

---

## 5. 模块拆分（src/hac/）

| 文件 | 职责 |
|---|---|
| `config.py` | 路径/env 解析、二进制解析、常量 |
| `encoders.py` | ffmpeg -encoders 探测（启动缓存） |
| `models.py` | Pydantic 数据模型（§2） |
| `presets.py` | 6 预设 + `effective_enabled()` |
| `probe.py` | ffprobe 封装（duration/tags/codec…） |
| `uploads.py` | Upload 注册表 + 流式保存 |
| `transcoder.py` | single 转码：build args + 进度 + 取消 + verify |
| `merger.py` | m4b 合并：章节生成 + concat + 封面 |
| `metadata.py` | mutagen 读源 tags / 写输出 tags（含继承） |
| `library.py` | 白名单目录扫描 |
| `jobs.py` | JobManager：信号量/队列/重试/取消/清空/SSE 广播 |
| `events.py` | SSE 事件流（job.list / job.update / keepalive） |
| `main.py` | FastAPI 路由 + lifespan（探测、建目录） |
| `static/` | index.html / app.js / styles.css |

### 5.1 元数据继承（修复 v1 断链）

```python
inherited = read_source_tags(job.source_paths[0])   # 转码前读源 tags
metadata.write_tags(output_path, job.metadata, inherited=inherited)
```

- merge 模式：不写逐文件 tags；书级 title/artist 走 ffmetadata 全局段 + 章节标题
- cover：mp3→APIC、flac→Picture、mp4/m4a→covr、opus/ogg→METADATA_BLOCK_PICTURE（mutagen 处理）

---

## 6. 关键行为约定

### 6.1 上传（流式，修复 v1 全内存 bug）

```python
# Content-Length 预检 → 413；分块 1MB 写入临时文件；完成后 ffprobe 探测
# 探测失败（非音频）→ 400 并删除落盘文件
```

### 6.2 zip 下载（修复 v1 内存打包）

逐 job 写入临时 zip 文件 → `FileResponse(temp, background=...unlink)`，避免大包 OOM。

### 6.3 verify（数据真实）

任务 done 前对输出 ffprobe：codec/bit_rate/sample_rate/channels/size + savings_pct = (1 − out/in)×100。SSE `job.update` 携带，前端验证面板展示。

### 6.4 /api/health

```json
{"status": "ok", "ffmpeg": "/path", "ffprobe_ok": true,
 "encoders": ["libopus", "aac", "libfdk_aac"],
 "presets_enabled": 5, "presets_disabled": 1}
```

---

## 7. 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `HAC_DATA_DIR` | `<repo>/data` | uploads/ work/ outputs/ 根 |
| `HAC_MAX_CONCURRENT` | `2` | 并发 FFmpeg 数 |
| `HAC_MAX_UPLOAD_MB` | `500` | 单文件上限 |
| `HAC_LIBRARY_ROOTS` | `<data>/library` | 目录导入白名单根（`:` 分隔多个） |
| `HAC_FFMPEG_PATH` / `HAC_FFPROBE_PATH` | vendor → which | 二进制覆盖 |

**目录导入安全**：所有 path 先 `resolve()` 再校验 `is_relative_to(任一白名单根)`，否则 403。允许的音频扩展白名单之外直接忽略。

---

## 8. SSE 协议

同 v1：`EventSource` + `job.list`（连接时全量）+ `job.update`（增量全字段）+ 30s `keepalive`。事件广播用每订阅者 `asyncio.Queue`（慢消费者丢帧不阻塞）。

---

## 9. 前端要点（Vanilla JS，无构建）

- 上传：`XMLHttpRequest` + `upload.onprogress` → 逐文件进度条（修复 v1 fetch 无法显示进度的问题）
- 预设联动：选预设填表；手改任意参数字段 → 预设下拉回"— 自定义 —"
- 合并开关：勾选后 Settings 面板出现 书名/作者/封面，并要求文件列表 ≥2（按列表顺序 concat）
- 目录浏览器：FILES 栏切换"本地目录"模式，走 `/api/library/list`
- 任务卡片：状态色 + 进度条 + verify 面板 + 失败 error + retry/下载
- 顶部操作条：全部下载 zip / 清空已完成 / 取消全部

---

## 10. 错误处理

| HTTP | 场景 |
|---|---|
| 400 | 请求体错误 / merge 文件数 <2 / 超 MAX_MERGE_INPUTS |
| 403 | library 路径越出白名单 |
| 404 | job/upload/download 不存在（含 .partial） |
| 413 | 上传超限（Content-Length 预检 + 流中截断） |
| 422/500 | 探测失败、ffmpeg 失败 → Job FAILED + error 信息保留 |

坏输入文件：上传即 ffprobe，失败拒绝入库（不留垃圾文件）；任务运行中 ffmpeg 失败 → FAILED，error = stderr 尾部 500 字符。

---

## 11. 单元测试清单（tests/）

- `test_build_args`：每预设生成的参数矩阵（codec/bitrate/ar/ac/compression_level）；libfdk 不会出现双 -vbr；loudnorm 出现/不出现
- `test_progress`：`\r\n` 混合分隔、跨 chunk、归一化、duration=0
- `test_presets`：requires_encoder 过滤逻辑
- `test_metadata`：继承（填的覆盖、未填保留）、mp4/mp3/flac/opus 写入、封面
- `test_merge`：章节时间累积算法（多文件 START/END 拼接）、ffmetadata 渲染
- `test_library`：白名单内列出、越界 403、`..` 穿越
- `test_jobs`：并发上限、queued 取消、retry 状态重置、广播

---

## 12. 部署与运行

### 12.1 一键脚本（本地运行入口）

`run.sh`（项目根目录）是用户的唯一入口命令，封装了 venv 创建、依赖安装、二进制探测与进程管理：

| 命令 | 行为 |
|---|---|
| `./run.sh` / `start` | 确保依赖 → 解析 ffmpeg（vendor → 系统）→ `exec uvicorn hac.main:app` |
| `stop` | `pgrep -f "uvicorn hac.main:app"` 并 SIGTERM |
| `setup` | uv/venv 安装依赖；缺 ffmpeg 时调 `scripts/setup-ffmpeg.sh` |
| `he` | 调 `scripts/build-he-ffmpeg.sh`（源码编译 libfdk，启用 HE-AAC 预设） |
| `doctor` | 打印 python/ffmpeg/编码器/各预设可用性/白名单/数据目录 |
| `help` | 帮助菜单（命令、选项、环境变量、示例） |

选项：`-p/--port`、`-H/--host`、`-r/--reload`、`-l/--library DIR`（追加白名单根，可重复）。
环境变量与 §7 相同，外加 `HAC_PORT` / `HAC_HOST` 作为端口与地址的默认值。

### 12.2 Docker

- `python:3.11-slim` + `curl`；构建时下载 BtbN ffmpeg（ffmpeg+ffprobe 齐全，但**不含 libfdk_aac**，实测 2026-08-30），下载失败则 apt ffmpeg 兜底
- 默认镜像 HE-AAC 预设自动隐藏（编码器探测兜底，应用功能不受影响）；需要 HE 时可用 `docker run -v ./vendor/bin:/app/vendor/bin:ro` 挂载本地编译好的二进制，或在镜像内跑 `scripts/build-he-ffmpeg.sh`
- 非 root uid=1000；volume `/app/data`；HEALTHCHECK `/api/health`
- `HAC_LIBRARY_ROOTS` 可挂载额外书库目录（只读挂载建议）

---

## 13. 工作量估算

| 模块 | 行数估算 |
|---|---|
| 后端（13 模块） | ~1500 |
| 前端（3 文件） | ~900 |
| 测试 | ~600 |
| Docker + scripts | ~100 |
| **合计** | **~3100** |

---

## 14. v1 spec 的 9 处错误对照（存档）

1. ffprobe 路径 = ffmpeg 路径（imageio 无 ffprobe）→ 弃 imageio，双二进制解析
2. libfdk 可能输出两个 `-vbr` → 互斥分支
3. HE-AAC v2 配单声道（PS 工具无效）→ HE v1 48k 单声道 + v2 32k 立体声
4. 上传 `await f.read()` 全内存 → 分块流式
5. `write_tags` 未传 inherited → 继承断链
6. zip 全内存 → 临时文件
7. preset 手写 `enabled` → requires_encoder 自动探测
8. 无 `/api/health` 但 Docker 测它 → 补
9. 静态目录相对路径、queued 不能取消、source_id 靠 glob → 修
