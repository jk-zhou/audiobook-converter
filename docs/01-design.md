# 01 · 设计文档（Design Doc）

> **定位**：简易版网页 foobar2000 —— 个人/小团队本地部署的批量音频转码 Web App
> **核心场景**：有声书批量压缩（Opus 32-64 kbps / AAC HE-AAC v2 48 kbps）
> **设计原则**：单用户、本地优先、零账号体系、零云端依赖

---

## 1. 产品定位与目标用户

### 1.1 解决什么问题

桌面端老牌工具（foobar2000、dBpoweramp、Switch）的痛点：
- **桌面绑定**：换电脑/操作系统要重装
- **多设备不便**：手机/平板访问不到
- **批量流程粗糙**：需要一拖一设置，重复劳动

本项目用 Web 形态解决：
- 任何设备浏览器访问（响应式）
- 上传后后台跑，不占前端
- 预设系统一次设置、批量应用
- 元数据统一编辑 + 自动继承源文件未修改的字段

### 1.2 不做什么（明确的边界）

- ❌ 多用户 / 鉴权 / 账号体系 —— 单用户本地工具
- ❌ 云端存储 —— 所有文件留在本机磁盘
- ❌ 实时波形预览 —— Web Audio API 解码成本太高
- ❌ 数据库（SQLite 都嫌重）—— 任务用内存 + JSON 落盘
- ❌ 流媒体 / 播放功能 —— 转码完下载走系统播放器

### 1.3 目标用户

- 收藏大量有声书 / 播客的个人
- 想要"低码率但听感损失小"的压缩方案
- 不想折腾桌面端 CLI 命令行参数的人

---

## 2. 技术选型与权衡

### 2.1 转码引擎：FFmpeg

| 选项 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **FFmpeg** ✅ | 格式覆盖 99%、成熟、参数体系完整 | 需要打包二进制（~80MB）或系统安装 | **唯一现实选择** |
| GStreamer | 灵活、插件化 | Web 部署复杂、文档割裂 | 不适合 |
| SoX | 轻量 | 格式支持少（无 AAC） | 不够用 |
| 云端 API | 零本地依赖 | 上传隐私差、按量付费、延迟 | 违背本地优先 |

**部署方式**：用 `imageio-ffmpeg` 或 `static-ffmpeg` Python 包自动下载静态二进制，免去系统依赖。**注意**：这两个包默认下载的 ffmpeg **不含 libfdk_aac**，所以 HE-AAC v2 预设暂时无法启用（见 §5 预设说明）。

### 2.2 后端框架：FastAPI

| 选项 | 优势 | 劣势 |
|---|---|---|
| **FastAPI** ✅ | 异步原生、SSE/WebSocket 友好、类型提示 | CPU 密集任务需要 subprocess 卸载 |
| Node.js + Express | FFmpeg child_process 简单、前后端同语言 | 大文件上传流式处理稍弱 |
| Go | 并发强、性能好 | 生态不如 Python/Node |

**选 FastAPI 的核心理由**：
1. SSE（Server-Sent Events）是任务进度推送的天然载体，FastAPI 原生支持
2. 后台任务用 `asyncio.create_subprocess_exec` 调 FFmpeg，CPU 卸载到子进程，不阻塞事件循环
3. 后续想接 ML（音频指纹、降噪）有 Python 生态

### 2.3 前端：Vanilla JS

**不用 React/Vue 的理由**：
- 单一职责工具，不需要复杂状态管理
- 没有构建步骤 = 没有 node_modules 黑洞，部署就是静态目录
- 文件拖拽用原生 HTML5 API，进度条用 SSE，够用

### 2.4 任务队列：内存级 + Semaphore

| 选项 | 适合场景 |
|---|---|
| **asyncio 任务表 + 并发上限** ✅ | 本工具：单用户/小团队，并发 2-4 个 FFmpeg 足够 |
| Celery + Redis | 多用户、生产环境、横向扩展 |
| RQ | 中量级 |

**结论**：内存级任务表 + semaphore 限并发。简单到能在一个文件里写完，复杂需求时再换 Celery。**服务重启后任务丢失**——MVP 接受这个限制。

### 2.5 部署形态：本地 + Docker 双形态（v0.1）

| 形态 | 适合场景 | 启动命令 |
|---|---|---|
| **本地 Python** ✅ | 开发机调试 | `uvicorn hac.main:app --host 0.0.0.0 --port 8000` |
| **Docker 单容器** ✅ | NAS、远程服务器、生产 | `docker run -p 8000:8000 -v ./data:/app/data audiobook-converter` |
| Docker Compose | 多容器编排（v0.3 数据库引入后才有意义） | `docker compose up -d` |

**Docker 设计要点**（详见 `docs/03-roadmap.md` §1.5）：
- 基础镜像：`python:3.11-slim` + apt 装 ffmpeg（无 libfdk_aac）
- 数据持久化：必挂 volume `./data:/app/data`
- 健康检查：`/api/health` 端点 + curl
- 非 root 用户：容器内 uid=1000
- 镜像体积：~375MB

**为什么同时支持两种形态**：
- 本地 Python：开发者日常调试，修改代码即生效
- Docker：NAS/服务器部署，一行命令拉起，无需手动装依赖
- 两者共存互不影响，**不强制** Docker

---

## 3. 架构设计

### 3.1 系统架构图

```
┌─────────────────────────────────────────────────┐
│  Browser (Vanilla JS)                           │
│  ┌──────────┐ ┌──────────┐ �──────────────┐   │
│  │ Upload   │ │ Settings │ │ Job Monitor  │   │
│  └────┬─────┘ └────┬─────┘ └──────┬───────┘   │
│       │ HTTP+multipart │         │ SSE stream │
└───────┼───────────────┼─────────┼─────────────┘
        ▼               ▼          ▼
┌─────────────────────────────────────────────────┐
│  FastAPI Server                                 │
│  ┌─────────�  ┌──────────────┐  ┌────────────┐ │
│  │ /upload │  │ /jobs (CRUD) │  │ /events    │ │
│  └────┬────┘  └──────┬───────┘  └─────�──────┘ │
│       │              │                │         │
│       ▼              ▼                ▼         │
│  ┌──────────────────────────────────────────┐   │
│  │   JobManager (asyncio)                   │   │
│  │   - Semaphore(N)                         │   │
│  │   - Progress parsers (FFmpeg stderr)     │   │
│  │   - Metadata writer (mutagen)            │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
        │                       │
        ▼                       ▼
   ffmpeg subprocess       mutagen (Python)
   (编码转码)             (元数据写入)
```

### 3.2 数据流（转码流水线）

```
[Upload] ──> 保存到 data/uploads/{job_id}/source.{ext}
              │
              ▼
        [Job Created] status=queued
              │
              ▼
        [Worker Pickup] status=running
              │
              ├─> ffmpeg -i source.{ext}
              │     -c:a {codec} -b:a {bitrate}
              │     -ar {samplerate} -af {filters}
              │     -y work/{job_id}/output.{ext}
              │     (stderr 解析 -progress pipe:1)
              │
              ├─> 解析 FFmpeg stderr 提取:
              │     - out_time_ms (进度)
              │     - progress (continue/end)
              │
              ▼
        [Transcode Done]
              │
              ▼
        [Metadata Phase] status=tagging
              │   mutagen.File(output).update(tags_dict)
              ▼
        [Complete] status=done, output_path 准备好
```

### 3.3 进度监控双通道

FFmpeg 提供两种进度机制，二选一或并存：
- **`-progress pipe:1`**：结构化 key=value 输出（推荐，主通道）
- **解析 stderr 中的 `time=HH:MM:SS.ms`**：兼容老版本（fallback）

状态机：`progress=continue` 持续读，`progress=end` 才视为完成。**进程退出码必须为 0 才算成功**。

---

## 4. UI 布局

### 4.1 单页三栏式

```
┌──────────────────────────────────────────────────────────────┐
│  🎵 Audiobook Converter                       [⚙ Settings]   │
├──────────────────┬──────────────────────┬────────────────────┤
│  1. FILES        │  2. SETTINGS          │  3. JOBS           │
│                  │                      │                    │
│  [Drop zone]     │  Preset: [▼]         │  ● transcoding...  │
│                  │  Format: [mp3 ▼]     │  ███████░░ 73%     │
│  • song1.flac    │  Codec:  [auto ▼]    │  file.mp3          │
│  • song2.wav     │  Bitrate:[320k ▼]    │                    │
│  • song3.ogg     │  Quality:[V0 ▼]     │  ● queued          │
│                  │  Sample: [44.1k ▼]  │  file2.mp3         │
│  [+ Add more]    │  Ch:    [2 ▼]       │                    │
│                  │                      │  ✓ done            │
│                  │  ── Metadata ──      │  file3.mp3 [↓]     │
│                  │  Title:    [______]  │                    │
│                  │  Artist:   [______]  │  ✗ failed          │
│                  │  Album:    [______]  │  file4.mp3         │
│                  │  Cover:    [Upload]  │    └ corrupt input │
│                  │                      │                    │
│                  │  [Start Conversion]  │                    │
└──────────────────┴──────────────────────┴────────────────────┘
```

### 4.2 交互流程

1. **选预设**（或自定义参数）→ 表单自动填充
2. **改任意字段** → 预设下拉重置为 "— 自定义 —"
3. **填元数据**（可选，留空 = 从源文件继承）
4. **点 Start Conversion** → 文件进入队列
5. **实时看进度**（SSE 推送，无需刷新）
6. **任务完成** → 自动出现在下载列表，可单独下载或打包 zip

---

## 5. 有声书预设设计

### 5.1 预设清单

| ID | 名称 | 编码 | 采样率 | 声道 | 比特率 | 质量 | enabled |
|---|---|---|---|---|---|---|---|
| `audiobook_aac_he_v2_48k` | AAC HE-AAC v2 48k VBR | libfdk_aac | 24000 | 1 | 48k | VBR 3 | � |
| `audiobook_opus_low_32k` | Opus 低 32k | libopus | 24000 | 1 | 32k | — | ✅ |
| `audiobook_opus_mid_48k` | Opus 中 48k | libopus | 24000 | 1 | 48k | — | ✅ |
| `audiobook_opus_high_64k` | Opus 高 64k | libopus | 24000 | 1 | 64k | — | ✅ |

### 5.2 预设技术决策

#### 5.2.1 FDK-AAC 暂不启用

- **原因**：`imageio-ffmpeg` / `static-ffmpeg` 自带的静态 ffmpeg 默认不含 `libfdk_aac`，需要自编译
- **现状**：保留配置 `enabled=False`，扩展点完整，未来用户自行安装好静态 ffmpeg 后改一个布尔值即可启用
- **UI 表现**：直接**隐藏**（不是灰色禁用），保留字段以备未来

#### 5.2.2 Opus 三档位

| 档位 | 比特率 | 适用场景 | 1h 体积（估算）|
|---|---|---|---|
| 低 | 32k | 纯人声、播客、访谈 | ~14 MB |
| 中 | 48k | 人声 + 轻背景音乐 | ~21 MB |
| 高 | 64k | 有声剧、有背景音乐 | ~28 MB |

**关键洞察**：32k 是 Opus 的"窄带下限"。Opus 规格表硬线：
- ≥ 48 kbps：标准宽带，频响到 20kHz
- 24-48 kbps：自动启用窄带（NB），频响上限 ~8kHz（人声 OK，但音乐会失真）
- < 24 kbps：极端窄带，几乎只剩语音

#### 5.2.3 采样率统一 24000 Hz

- 22050 Hz 是 CD 一半频率（最高可还原 ~11kHz）
- 24000 Hz 是 Opus 的"原生"采样率，与内部处理最匹配
- HE-AAC v2 工作在 22050 Hz（这是 SBR 的要求），但 ffmpeg 会自动重采样，所以预设里统一填 24000
- **这点要在前端 tooltip 里说清**，否则用户会困惑"为什么填了 24000 但 HE-AAC 输出看起来是 22050"

### 5.3 自动生成文件名

- Preset 2-4 Opus：`{原名}_opus_{bitrate/1k}k.opus`
- Preset 1 AAC（未来）：`{原名}_he-aac-v2_48k.m4a`

用户可在文件名输入框手动覆盖。

---

## 6. 数据模型概览

```python
# job.py
@dataclass
class TranscodeSettings:
    format: str              # mp3, flac, aac, ogg, wav, opus, m4a
    codec: str | None        # libmp3lame, libfdk_aac, libopus, pcm_s16le...
    bitrate: str | None      # 128k, 256k, 320k
    quality: int | None      # VBR q 值（0-9 LAME / 0-10 Opus）
    samplerate: int | None   # 44100, 48000, 24000
    channels: int | None     # 1, 2
    profile: str | None      # aac_he_v2 (FDK-AAC only)
    compression_level: int | None  # Opus only
    extra_args: list[str]    # 高级用户透传

@dataclass
class MetadataEdit:
    title, artist, album, albumartist, date, genre: str | None
    track, disc: tuple[int, int] | None
    cover_path: str | None    # 封面图，mutagen 嵌入

@dataclass
class Job:
    id: str                   # uuid4
    source_path: Path
    output_filename: str
    settings: TranscodeSettings
    metadata: MetadataEdit
    status: "queued|running|tagging|done|failed|cancelled"
    progress: float           # 0-100
    error: str | None
    output_path: Path | None
    created_at, started_at, finished_at: datetime | None
    total_duration_sec: float | None
```

完整字段定义和默认值见 `02-tech-spec.md` §2。

---

## 7. 关键技术挑战与对策

### 7.1 进度解析可靠性 ⭐

**问题**：FFmpeg 的 `-progress` 输出有时候会丢行或乱序
**对策**：
- 在 stderr 同时兜底解析 `time=00:01:23.45`
- 状态机：`progress=continue` 持续读，`progress=end` 才视为完成
- 进程退出码必须为 0 才算成功

### 7.2 取消任务

**做法**：`proc.send_signal(signal.SIGTERM)` → FFmpeg 会写入不完整的输出 → 需要标记 `output_path` 为 `.partial`，**不能让用户下载到损坏文件**

### 7.3 大文件上传

**对策**：
- FastAPI 默认会缓存到内存，必须 `UploadFile` 流式读 + 分块写入
- 客户端 `fetch` 用 `ReadableStream` 显示上传进度（区别于转码进度）

### 7.4 元数据保留 vs 覆盖

**关键 UX 决策**：
- 默认从源文件复制所有标签（mutagen 一次性 copy）
- 用户填的字段**覆盖**对应字段
- 未填的字段保留原值

### 7.5 封面图

mutagen 支持 FLAC/MP4 的内嵌封面，MP3 用 ID3 APIC。需分别处理。

---

## 8. 部署与运行

### 8.1 目录结构

```
audiobook-converter/
├── pyproject.toml
├── README.md
├── docs/
│   ├── 01-design.md (本文档)
│   ├── 02-tech-spec.md
│   ├── 03-roadmap.md
│   └── 04-verification.md
├── src/
│   └── hac/                  # 主代码（待开发）
│       ├── __init__.py
│       ├── main.py           # FastAPI app + 路由
│       ├── jobs.py           # JobManager
│       ├── transcoder.py     # FFmpeg 调用 + 进度解析
│       ├── metadata.py       # mutagen 读写
│       ├── probe.py          # ffprobe 包装
│       ├── events.py         # SSE 广播
│       ├── presets.py        # 4 个有声书预设
│       ├── config.py         # 路径 + 并发配置
│       └── static/           # 前端
│           ├── index.html
│           ├── app.js
│           └── styles.css
├── data/                     # 运行时数据（gitignore）
│   ├── uploads/
│   ├── work/
│   └── outputs/
└── tests/                    # 测试（待开发）
```

### 8.2 启动方式（MVP 计划）

```bash
# 安装依赖
pip install fastapi uvicorn mutagen imageio-ffmpeg sse-starlette python-multipart

# 启动
uvicorn hac.main:app --host 0.0.0.0 --port 8000 --reload
# 浏览器访问 http://localhost:8000
```

### 8.3 已知部署风险

- **静态 ffmpeg 不含 libfdk_aac** → HE-AAC v2 预设无法启用（已通过 `enabled=False` 规避）
- **大文件上传内存压力** → 用流式读 + 分块写入
- **SSE 在反向代理后超时** → nginx 需设 `proxy_buffering off;` + `proxy_read_timeout 86400;`

---

## 9. 设计原则回顾

1. **单用户、本地优先** —— 不做云、不做账号、不做订阅
2. **简洁优先** —— 能用一行配置解决的不要做 UI 控件
3. **预设驱动** —— 4 个有声书预设覆盖 80% 场景，剩下 20% 留自定义
4. **数据真实** —— 所有声称的指标（采样率、码率）必须能从 ffprobe 验证
5. **可验证** —— 每个功能都有 `04-verification.md` 里的硬性测试对应

---

## 10. 元数据批处理与智能文件名解析（v0.2 补充）

> **本节为追加章节**：解决用户痛点 —— 大量音频文件导入 Apple Books 后章节排序混乱。

### 10.1 痛点根因分析

**Apple Books 的"导入慢"+"排序乱"实际是同一根因的不同表现**：

| 现象 | 根因 |
|---|---|
| 导入几千章文件慢 | Books.app 对每个文件逐一解析元数据 |
| 播放列表章节排序混乱 | track number 格式不一致、album 字符串不一致、AlbumArtist 缺失、DiscNumber 缺失、Title 缺失 |

**解决方案**：导入 Apple Books **之前**，用一个工具批量"修复元数据"——保证所有文件共享一致的 `album + cover + track number + albumartist`。

### 10.2 模板语法（核心 UX）

**目标**：让用户输入"文件名格式"，自动提取字段，比正则更直观。

**模板语法规范**：

```
${FieldName}              ← 必填字段
${FieldName?}             ← 可选字段（缺失不报错）
${TrackNum:3}             ← 数字零填充（3 位）
```

**支持的 8 个字段**：

| 字段 | 类型 | 匹配规则 | 中文显示 |
|---|---|---|---|
| `TrackNum` | int | `\d+`，自动去前导零存为 int | 章节号 |
| `TrackTitle` | str | 贪婪任意字符（缺失时用文件名替代） | 章节标题 |
| `Artist` | str | 贪婪任意字符 | 作者（同时填 AlbumArtist） |
| `Album` | str | 贪婪任意字符 | 书名 |
| `Year` | int | `\d{4}` 严格 4 位 | 年份 |
| `Genre` | str | 贪婪任意字符 | 类型 |
| `DiscNum` | int | `\d+` | 碟号 |
| `Composer` | str | 贪婪任意字符 | 朗读者/作曲 |

**示例**：

```
模板: 第${TrackNum}集 ${TrackTitle} - ${Artist}.m4a

文件: 第01集 哈利波特与凤凰社 - J.K.罗琳.m4a
解析: TrackNum=1, TrackTitle="哈利波特与凤凰社", Artist="J.K.罗琳"

文件: 第02集.m4a
解析: TrackNum=2, TrackTitle="第02集"（来自文件名）, Artist=null
```

### 10.3 AlbumArtist 三种模式

模板只暴露 `${Artist}`，但 `AlbumArtist` 是 Apple Books 排序的关键字段。提供三种模式：

| 模式 | 行为 | 适用场景 |
|---|---|---|
| **复制 Artist 的值** | TPE2 = parsed.artist | 单作者多本书（默认） |
| **用户手动输入** | TPE2 = 用户填的字符串 | 多作者共享一个 Author（少见） |
| **留空** | 不写 TPE2 | 每章作者不同（罕见） |

### 10.4 TrackNum 写入格式

Apple Books 排序最稳的格式是**带总数**：

```
${TrackNum:3} → TRCK = "001/2452"
```

用户可配置：
- 零填充位数（不补零 / 2 位 / 3 位 / 4 位，默认 3 位）
- 总章节数（自动从文件数推断 / 用户手动指定）
- 匹配模式（宽松：接受任意位数；严格：必须恰好 N 位）

### 10.5 零填充作用域

`${Num:N}` 在三个地方都生效：

| 场景 | 行为 |
|---|---|
| **模板匹配** | 宽松模式：任意位数都行，去前导零；严格模式：必须 N 位 |
| **写入 ID3** | 自动格式化为 N 位（如 "001"） |
| **反向模板生成文件名** | 格式化为 N 位 |

### 10.6 反向模板（批量重命名）

**用途**：模板提取完字段后，按统一格式重命名文件。

**同一套语法** `${Field}`，但语义不同：

| 场景 | 字段来源 | 模板用途 |
|---|---|---|
| 正向解析 | 从文件名提取 | 提取已有文件元数据 |
| 反向生成 | 从解析结果或现有 ID3 | 生成新文件名 |

**重命名策略**：

| 策略 | 行为 | 安全等级 |
|---|---|---|
| **原地重命名**（默认） | 直接修改源文件 | 需强制预览+确认 |
| 生成到新目录 | 移动到 `renamed_{timestamp}/` | 原文件保留 |
| 打包成 zip | 全部打包成 zip 下载 | 最安全 |

**关键安全措施**：
- **强制预览**：必须先看新文件名列表，确认后才执行
- **自动 .bak 备份**：可勾选，重命名前生成 `.bak` 文件
- **冲突检测**：自动加 `-1`、`-2` 后缀（可配置改为报错）

### 10.7 批处理 UI 三个 Tab

```
[模板提取] [反向重命名] [统一设置]
```

**模板提取 Tab**：输入模板 → 实时预览匹配结果 → 应用
**反向重命名 Tab**：输入反向模板 → 预览新文件名 → 冲突检测 → 确认执行
**统一设置 Tab**：album/genre/year 等所有文件共享的字段

### 10.8 模板提取 UI 完整布局

```
┌──────────────────────────────────────────────────────────┐
│ 批处理模式                                                │
│                                                          │
│ [模板提取] [反向重命名] [统一设置]                         │
│                                                          │
│ ─── 模板提取 Tab ───                                     │
│                                                          │
│ 文件名模板:                                               │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ 第${TrackNum}集 ${TrackTitle} - ${Artist}.m4a       │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                          │
│ 插入字段:                                                 │
│ [章节号] [章节号:3]                                       │
│ [章节标题] [作者] [书名] [年份] [类型] [碟号] [朗读者]    │
│                                                          │
│ 模板语法说明:                                             │
│ • ${字段} 必填，缺失跳过文件                              │
│ • ${字段?} 可选，缺失填 None                             │
│ • ${字段:N} 数字零填充（N 位）                            │
│                                                          │
│ ─── TrackNum 写入格式 ───                                │
│ 零填充: [3 位 ▼]    总章节数: [自动推断（2452）▼]        │
│ 匹配模式: [宽松匹配 ▼]                                   │
│ 预览格式: TRCK = "001/2452"                              │
│                                                          │
│ ─── AlbumArtist 来源 ───                                 │
│ ◉ 复制 Artist 的值（推荐）                                │
│ ○ 用户手动输入 [_________________________________]       │
│ ○ 留空                                                    │
│                                                          │
│ ─── 其他选项 ───                                          │
│ ☑ 跳过不匹配的文件                                        │
│ ☑ TrackTitle 缺失时用文件名替代                            │
│                                                          │
│ [🧪 测试预览]                                             │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ 第01集 HP5 - 罗琳.m4a                                │ │
│ │   ✓ 章节号=1  章节标题="HP5"  作者="罗琳"             │ │
│ │ 第02集.m4a                                            │ │
│ │   ✓ 章节号=2  章节标题="第02集"（来自文件名）  作者=null│ │
│ │ HP - Ch3.mp3                                         │ │
│ │   ✗ 不匹配（跳过）                                    │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                          │
│ [✓ 应用模板]                                              │
└──────────────────────────────────────────────────────────┘
```

### 10.9 决策记录（追加 ADR）

#### ADR-005：模板语法 vs 正则

**决定**：用 `${Field}` 模板语法，不用正则。

**理由**：
- 正则对普通用户门槛过高（`(\d+).*? - (.*)` 难写易错）
- 模板语法把"正则"封装成"自然语言填空"
- 90% 场景不需要正则的灵活性

#### ADR-006：AlbumArtist 独立配置而非模板字段

**决定**：`${AlbumArtist}` 不在模板语法里，独立用"三种模式"配置。

**理由**：
- AlbumArtist 是"专辑级"字段，所有章节共享，从文件名提取没有意义
- 模板只暴露 `${Artist}`（章节级），AlbumArtist 在配置里决定
- 模板语法保持简洁

#### ADR-007：TrackTitle 缺失时用文件名 fallback

**决定**：TrackTitle 缺失不报错，自动用文件名（去扩展名）替代。

**理由**：
- Apple Books 没 title 会 fallback 到文件名，中文文件名按 Unicode 编码排序会乱
- 但完全跳过文件又太激进——大多数文件至少有文件名信息
- 用文件名替代是"有信息胜于无"的折中

#### ADR-008：重命名默认原地修改 + 强制预览

**决定**：默认原地重命名，但必须先预览 + 用户确认。

**理由**：
- 用户期望"重命名 = 直接生效"，避免中间目录污染
- 强制预览确保用户看清每个新文件名再下手
- 可选 `.bak` 备份降低误操作风险
