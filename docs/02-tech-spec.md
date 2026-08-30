# 02 · 技术实现规格（Tech Spec）

> **目标读者**：写代码的人
> **回答的问题**：数据结构、API、FFmpeg 命令怎么拼、错误怎么处理

---

## 1. 依赖与版本

### 1.1 Python 依赖

```toml
# pyproject.toml
[project]
name = "audiobook-converter"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "python-multipart>=0.0.9",      # 文件上传
    "sse-starlette>=2.0",           # SSE 响应
    "mutagen>=1.47",                # 元数据
    "imageio-ffmpeg>=0.5",          # 静态 ffmpeg
    "pydantic>=2.6",                # API 模型
]
```

### 1.2 FFmpeg 二进制探测

```python
# config.py
import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE_PATH = FFMPEG_PATH  # imageio 提供的同一个二进制也含 ffprobe

# 启动时探测 libfdk_aac 是否可用
def probe_codec_support(codec: str) -> bool:
    """返回 True 表示当前 ffmpeg 支持该 codec"""
    result = subprocess.run(
        [FFMPEG_PATH, "-hide_banner", "-codecs"],
        capture_output=True, text=True
    )
    return codec in result.stdout
```

**注意**：`imageio-ffmpeg` 默认下载的 ffmpeg 不含 `libfdk_aac`。如果用户想用 HE-AAC v2 预设，需要：
- 用 BtbN/FFmpeg-Builds 提供的 `GPL` 静态构建
- 或自行编译时启用 `--enable-libfdk-aac`

---

## 2. 数据模型（Pydantic）

### 2.1 TranscodeSettings

```python
from pydantic import BaseModel, Field
from typing import Literal

Format = Literal["mp3", "m4a", "flac", "ogg", "opus", "wav", "aac"]

class TranscodeSettings(BaseModel):
    format: Format
    codec: str | None = None              # 自动推断如果为 None
    profile: str | None = None            # FDK-AAC: "aac_he_v2"
    bitrate: str | None = None            # "128k", "48k"
    quality: int | None = None            # VBR q 值
    vbr: Literal["off", "on"] | None = None
    samplerate: int | None = None         # Hz
    channels: int | None = Field(default=None, ge=1, le=2)
    compression_level: int | None = Field(default=None, ge=0, le=10)
    extra_args: list[str] = []
```

### 2.2 MetadataEdit

```python
class MetadataEdit(BaseModel):
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    albumartist: str | None = None
    date: str | None = None               # YYYY-MM-DD
    genre: str | None = None
    track: tuple[int, int] | None = None # (number, total)
    disc: tuple[int, int] | None = None
    composer: str | None = None
    cover_path: str | None = None         # 服务端临时路径
```

### 2.3 Job

```python
from datetime import datetime
from pathlib import Path
from enum import Enum
import uuid

class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    TAGGING = "tagging"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    source_path: Path
    output_filename: str
    settings: TranscodeSettings
    metadata: MetadataEdit = Field(default_factory=MetadataEdit)
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0                 # 0-100
    error: str | None = None
    output_path: Path | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_duration_sec: float | None = None
```

### 2.4 Preset

```python
@dataclass
class Preset:
    id: str
    name: str
    description: str
    settings: TranscodeSettings
    extension: str
    filename_suffix: str
    enabled: bool = True
```

**4 个有声书预设**（`presets.py`）：

```python
PRESETS: list[Preset] = [
    Preset(
        id="audiobook_aac_he_v2_48k",
        name="有声书 · AAC HE-AAC v2 48k VBR",
        description="�️ 需要 libfdk_aac 支持，暂未启用",
        settings=TranscodeSettings(
            format="m4a",
            codec="libfdk_aac",
            profile="aac_he_v2",
            bitrate="48k",
            quality=3,                # FDK VBR 等级 0-5，3 = 高质量
            vbr="on",
            samplerate=24000,
            channels=1,
        ),
        extension="m4a",
        filename_suffix="_he-aac-v2_48k",
        enabled=False,                # ⭐ 等静态 ffmpeg 含 libfdk_aac 后改为 True
    ),
    Preset(
        id="audiobook_opus_low_32k",
        name="有声书 · Opus 低 (32k VBR)",
        description="极小体积，单声道，纯人声最佳",
        settings=TranscodeSettings(
            format="opus",
            codec="libopus",
            bitrate="32k",
            vbr="on",
            samplerate=24000,
            channels=1,
            compression_level=10,
        ),
        extension="opus",
        filename_suffix="_opus_32k",
    ),
    Preset(
        id="audiobook_opus_mid_48k",
        name="有声书 · Opus 中 (48k VBR)",
        description="平衡档，单声道，人声+轻背景音乐",
        settings=TranscodeSettings(
            format="opus",
            codec="libopus",
            bitrate="48k",
            vbr="on",
            samplerate=24000,
            channels=1,
            compression_level=10,
        ),
        extension="opus",
        filename_suffix="_opus_48k",
    ),
    Preset(
        id="audiobook_opus_high_64k",
        name="有声书 · Opus 高 (64k VBR)",
        description="高质量档，单声道，有声剧、含背景音乐场景",
        settings=TranscodeSettings(
            format="opus",
            codec="libopus",
            bitrate="64k",
            vbr="on",
            samplerate=24000,
            channels=1,
            compression_level=10,
        ),
        extension="opus",
        filename_suffix="_opus_64k",
    ),
]
```

---

## 3. API 设计

### 3.1 路由表

| Method | Path | 用途 | 请求体 | 响应 |
|---|---|---|---|---|
| POST | `/api/upload` | 多文件上传 | multipart/form-data | `[{file_id, name, size}]` |
| POST | `/api/jobs` | 创建转码任务 | `{source_id, output_filename, settings, metadata}` | `{job_id}` |
| GET | `/api/jobs` | 列出所有任务 | — | `[Job]` |
| GET | `/api/jobs/{id}` | 任务详情 | — | `Job` |
| DELETE | `/api/jobs/{id}` | 取消/删除任务 | — | `{ok}` |
| GET | `/api/events` | **SSE 进度流** | — | `text/event-stream` |
| GET | `/api/download/{id}` | 下载输出文件 | — | binary |
| GET | `/api/download-zip` | 打包 zip 下载多个任务 | `?ids=a,b,c` | binary |
| GET | `/api/probe/{source_id}` | ffprobe 元数据 | — | `{duration, channels, samplerate, bitrate, tags}` |
| GET | `/api/presets` | 返回预设清单 | — | `[Preset]` |

### 3.2 请求/响应示例

**POST /api/upload**（multipart）

```
POST /api/upload HTTP/1.1
Content-Type: multipart/form-data; boundary=...

--boundary
Content-Disposition: form-data; name="files"; filename="chapter1.flac"
Content-Type: audio/flac

<binary>
--boundary--
```

响应：
```json
{
  "uploads": [
    {"id": "abc123", "name": "chapter1.flac", "size": 52428800}
  ]
}
```

**POST /api/jobs**

```json
{
  "source_id": "abc123",
  "output_filename": "chapter1_opus_32k",
  "settings": {
    "format": "opus",
    "codec": "libopus",
    "bitrate": "32k",
    "vbr": "on",
    "samplerate": 24000,
    "channels": 1,
    "compression_level": 10
  },
  "metadata": {
    "title": "Chapter 1",
    "artist": "Author Name"
  }
}
```

响应：`{"job_id": "job_xyz789"}`

### 3.3 SSE 协议

**GET /api/events** 返回 `text/event-stream`，事件格式：

```
event: job.update
data: {"id": "job_xyz", "status": "running", "progress": 42.5}

event: job.update
data: {"id": "job_xyz", "status": "done", "progress": 100.0}

event: job.update
data: {"id": "job_xyz", "status": "failed", "error": "exit code 1"}

```

**事件类型**：
- `job.update`：任务状态/进度变化（每次进度变化都推）
- `job.list`：完整任务列表（连接建立时发一次，用于前端初始化）
- `keepalive`：每 30s 发一个空心跳，防止代理超时

**前端 EventSource 用法**：

```js
const es = new EventSource('/api/events');
es.addEventListener('job.update', e => {
  const job = JSON.parse(e.data);
  updateJobCard(job.id, job);
});
es.addEventListener('job.list', e => {
  const jobs = JSON.parse(e.data);
  renderJobList(jobs);
});
```

---

## 4. FFmpeg 参数映射

### 4.1 build_ffmpeg_args()

这是核心转换函数——把 `TranscodeSettings` 翻译成命令行参数：

```python
def build_ffmpeg_args(
    src: Path,
    dst: Path,
    settings: TranscodeSettings
) -> list[str]:
    args = [FFMPEG_PATH, "-y", "-hide_banner", "-i", str(src), "-vn"]

    # Codec
    if settings.codec:
        args += ["-c:a", settings.codec]

    # Profile (FDK-AAC)
    if settings.profile:
        args += ["-profile:a", settings.profile]

    # Bitrate / Quality 二选一
    if settings.bitrate:
        args += ["-b:a", settings.bitrate]
    elif settings.quality is not None:
        codec = settings.codec or ""
        if codec in ("libmp3lame", "libvorbis", "libopus"):
            args += ["-q:a", str(settings.quality)]
        elif codec == "libfdk_aac":
            args += ["-vbr", str(settings.quality)]

    # VBR 开关
    if settings.vbr == "on":
        args += ["-vbr", "on"]

    # 采样率 / 声道
    if settings.samplerate:
        args += ["-ar", str(settings.samplerate)]
    if settings.channels:
        args += ["-ac", str(settings.channels)]

    # Opus 压缩等级
    if settings.compression_level is not None:
        args += ["-compression_level", str(settings.compression_level)]

    # 用户透传
    if settings.extra_args:
        args += list(settings.extra_args)

    # 进度输出（stdout key=value）
    args += ["-progress", "pipe:1", "-nostats"]

    args.append(str(dst))
    return args
```

### 4.2 FFmpeg 命令实例

#### 4.2.1 Opus 三档

**低（32k）**：
```bash
ffmpeg -y -hide_banner -i input.flac -vn \
  -c:a libopus -b:a 32k -vbr on \
  -compression_level 10 \
  -ar 24000 -ac 1 \
  -progress pipe:1 -nostats \
  output.opus
```

**中（48k）**：
```bash
ffmpeg -y -hide_banner -i input.flac -vn \
  -c:a libopus -b:a 48k -vbr on \
  -compression_level 10 \
  -ar 24000 -ac 1 \
  -progress pipe:1 -nostats \
  output.opus
```

**高（64k）**：
```bash
ffmpeg -y -hide_banner -i input.flac -vn \
  -c:a libopus -b:a 64k -vbr on \
  -compression_level 10 \
  -ar 24000 -ac 1 \
  -progress pipe:1 -nostats \
  output.opus
```

#### 4.2.2 AAC HE-AAC v2（暂未启用）

```bash
ffmpeg -y -hide_banner -i input.flac -vn \
  -c:a libfdk_aac -profile:a aac_he_v2 \
  -vbr 3 -b:a 48k -vbr on \
  -ar 22050 -ac 1 \              # ffmpeg 会从 24000 重采样到 22050
  -progress pipe:1 -nostats \
  output.m4a
```

### 4.3 进度解析

FFmpeg 的 `-progress pipe:1` 输出是 key=value 格式：

```
frame=123
fps=25.00
stream_0_0_q=28.0
total_size=1024000
out_time_us=60000000         ← 已处理微秒
out_time_ms=60000
out_time=00:01:00.000000
progress=continue            ← 或 progress=end

frame=456
...
progress=end
```

**解析器**（伪代码）：

```python
async def parse_progress(stream):
    """解析 FFmpeg stdout，按 \r 分隔的 key=value 块"""
    buf = ""
    while True:
        chunk = await stream.read(1024)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="ignore")
        # FFmpeg 用 \r 分隔块（不是 \n）
        while "\r" in buf or "\n" in buf:
            for sep in ("\r", "\n"):
                if sep in buf:
                    line, buf = buf.split(sep, 1)
                    break
            line = line.strip()
            if line.startswith("out_time_us="):
                us = int(line.split("=", 1)[1])
                yield {"time_us": us}
            elif line.startswith("progress="):
                yield {"done": line.split("=", 1)[1] == "end"}
```

**进度归一化**：

```python
def calc_progress(time_us: int, total_duration_sec: float) -> float:
    if not total_duration_sec:
        return 0.0
    pct = (time_us / 1_000_000) / total_duration_sec * 100
    return min(100.0, max(0.0, pct))
```

**关键**：进度必须在创建 Job 时通过 `ffprobe` 获取 `total_duration_sec`，否则无法归一化。

---

## 5. 模块拆分

### 5.1 config.py

```python
from pathlib import Path
import imageio_ffmpeg

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
WORK_DIR = DATA_DIR / "work"
OUTPUT_DIR = DATA_DIR / "outputs"

for d in (UPLOAD_DIR, WORK_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE_PATH = FFMPEG_PATH

MAX_CONCURRENT_JOBS = 2        # 同时跑的 FFmpeg 进程数
MAX_UPLOAD_SIZE_MB = 500       # 单文件上限
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB
```

### 5.2 probe.py

```python
import json
import subprocess
from pathlib import Path
from .config import FFPROBE_PATH

def probe(path: Path) -> dict:
    """调用 ffprobe，返回时长、声道、采样率、码率、tag"""
    result = subprocess.run(
        [FFPROBE_PATH, "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True
    )
    data = json.loads(result.stdout)
    stream = next(s for s in data["streams"] if s["codec_type"] == "audio")
    return {
        "duration": float(data["format"]["duration"]),
        "bitrate": int(data["format"].get("bit_rate", 0)),
        "channels": stream["channels"],
        "samplerate": int(stream["sample_rate"]),
        "codec": stream["codec_name"],
        "tags": data["format"].get("tags", {}),
    }
```

### 5.3 transcoder.py

```python
import asyncio
from pathlib import Path
from .config import FFMPEG_PATH
from . import metadata
from .models import Job, JobStatus

async def transcode(
    job: Job,
    on_progress: callable,
    on_status: callable
) -> None:
    """执行转码 + 元数据写入"""
    on_status(JobStatus.RUNNING)
    job.started_at = datetime.now()

    args = build_ffmpeg_args(job.source_path, job.work_output, job.settings)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    # 同时读 stdout（进度）和 stderr（错误）
    stderr_task = asyncio.create_task(_drain_stderr(proc.stderr))
    async for update in parse_progress(proc.stdout):
        if update.get("done"):
            break
        if "time_us" in update:
            pct = calc_progress(update["time_us"], job.total_duration_sec)
            on_progress(pct)

    await proc.wait()
    await stderr_task

    if proc.returncode != 0:
        on_status(JobStatus.FAILED, error=f"ffmpeg exit {proc.returncode}")
        return

    # 写元数据
    on_status(JobStatus.TAGGING)
    try:
        metadata.write_tags(job.work_output, job.metadata)
    except Exception as e:
        on_status(JobStatus.FAILED, error=f"metadata write: {e}")
        return

    # 移动到 outputs/
    job.output_path = OUTPUT_DIR / f"{job.id}_{job.output_filename}{ext}"
    job.work_output.rename(job.output_path)

    on_progress(100.0)
    on_status(JobStatus.DONE)
    job.finished_at = datetime.now()


async def cancel_transcode(proc: asyncio.subprocess.Process) -> None:
    """发 SIGTERM，让 ffmpeg 退出"""
    try:
        proc.send_signal(signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (ProcessLookupError, asyncio.TimeoutError):
        proc.kill()
```

### 5.4 metadata.py（mutagen 封装）

```python
from pathlib import Path
from mutagen import File
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TPE2, TDRC, TCON, TRCK, TPOS
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4
from .models import MetadataEdit

def read_source_tags(path: Path) -> dict:
    """从源文件读取所有 tag，返回 dict（小写 key）"""
    f = File(path, easy=True)
    return dict(f.tags) if f.tags else {}

def write_tags(path: Path, edit: MetadataEdit, inherited: dict | None = None) -> None:
    """写入元数据：用户填的覆盖，未填的用 inherited（源文件 tag）"""
    ext = path.suffix.lower()

    # 合并策略
    final = dict(inherited or {})
    for field, value in edit.model_dump(exclude_none=True).items():
        if field == "cover_path":
            continue
        final[field] = value

    if ext == ".mp3":
        _write_mp3(path, edit, final)
    elif ext == ".flac":
        _write_flac(path, edit, final)
    elif ext in (".m4a", ".mp4"):
        _write_mp4(path, edit, final)
    elif ext in (".ogg", ".opus"):
        _write_vorbis(path, edit, final)
    else:
        # WAV 等无 tag 支持，跳过
        return


def _write_mp3(path, edit, tags):
    try:
        audio = ID3(path)
    except Exception:
        audio = ID3()
    if edit.title: audio.add(TIT2(encoding=3, text=edit.title))
    if edit.artist: audio.add(TPE1(encoding=3, text=edit.artist))
    if edit.album: audio.add(TALB(encoding=3, text=edit.album))
    # ... 其他字段
    if edit.cover_path:
        cover_data = Path(edit.cover_path).read_bytes()
        audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="cover", data=cover_data))
    audio.save(path)


def _write_flac(path, edit, tags):
    audio = FLAC(path)
    if edit.title: audio["title"] = edit.title
    if edit.artist: audio["artist"] = edit.artist
    # ...
    if edit.cover_path:
        cover = Picture()
        cover.data = Path(edit.cover_path).read_bytes()
        cover.type = 3  # Cover (front)
        cover.mime = "image/jpeg"
        audio.add_picture(cover)
    audio.save()


def _write_mp4(path, edit, tags):
    audio = MP4(path)
    if edit.title: audio["\xa9nam"] = edit.title
    if edit.artist: audio["\xa9ART"] = edit.artist
    if edit.album: audio["\xa9alb"] = edit.album
    if edit.cover_path:
        cover_data = Path(edit.cover_path).read_bytes()
        audio["covr"] = [MP4.Cover(cover_data, imageformat=MP4.Cover.FORMAT_JPEG)]
    audio.save()


def _write_vorbis(path, edit, tags):
    audio = File(path)
    if edit.title: audio["title"] = edit.title
    if edit.artist: audio["artist"] = edit.artist
    # Opus 用 VorbisComments，mutagen 自动处理
    audio.save()
```

### 5.5 jobs.py（JobManager）

```python
import asyncio
from typing import Callable
from .models import Job, JobStatus
from .transcoder import transcode

class JobManager:
    def __init__(self, max_concurrent: int = 2):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.procs: dict[str, asyncio.subprocess.Process] = {}
        self.event_subscribers: list[asyncio.Queue] = []

    def add(self, job: Job) -> None:
        self.jobs[job.id] = job
        self._broadcast({"event": "job.update", "data": job.model_dump_json()})

    async def run(self, job_id: str) -> None:
        job = self.jobs[job_id]
        async with self.semaphore:
            task = asyncio.create_task(transcode(
                job,
                on_progress=lambda pct: self._on_progress(job_id, pct),
                on_status=lambda status, **kw: self._on_status(job_id, status, **kw)
            ))
            self.tasks[job_id] = task
            self.procs[job_id] = task._proc  # transcoder 需返回
            await task

    def _on_progress(self, job_id: str, pct: float) -> None:
        self.jobs[job_id].progress = pct
        self._broadcast(...)

    def _on_status(self, job_id: str, status: JobStatus, **kw) -> None:
        self.jobs[job_id].status = status
        if "error" in kw:
            self.jobs[job_id].error = kw["error"]
        self._broadcast(...)

    async def cancel(self, job_id: str) -> None:
        if job_id in self.procs:
            proc = self.procs[job_id]
            await cancel_transcode(proc)
        self.jobs[job_id].status = JobStatus.CANCELLED

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=100)
        self.event_subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.event_subscribers.remove(q)

    def _broadcast(self, event: dict) -> None:
        for q in self.event_subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 慢消费者丢弃
```

### 5.6 events.py（SSE 广播）

```python
import asyncio
import json
from sse_starlette.sse import EventSourceResponse

async def event_stream(job_manager: JobManager):
    queue = job_manager.subscribe()

    # 连接建立时发完整列表
    initial = [{"event": "job.list", "data": json.dumps([j.model_dump(mode="json") for j in job_manager.jobs.values()])}]
    for e in initial:
        yield e

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield event
            except asyncio.TimeoutError:
                # 心跳
                yield {"event": "keepalive", "data": ""}
    finally:
        job_manager.unsubscribe(queue)
```

### 5.7 main.py（FastAPI 入口）

```python
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
import shutil
import zipfile
import io

from .config import UPLOAD_DIR, WORK_DIR, OUTPUT_DIR, MAX_UPLOAD_SIZE_MB
from .jobs import JobManager
from .events import event_stream
from .probe import probe
from .models import Job, TranscodeSettings, MetadataEdit

app = FastAPI()
jm = JobManager(max_concurrent=2)

# 静态前端
app.mount("/static", StaticFiles(directory="hac/static"), name="static")

@app.get("/")
async def index():
    return FileResponse("hac/static/index.html")


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "No files")

    results = []
    for f in files:
        # 流式读取大文件
        content = await f.read()
        if len(content) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(413, f"{f.filename} too large")

        file_id = uuid.uuid4().hex[:12]
        dst = UPLOAD_DIR / f"{file_id}_{f.filename}"
        dst.write_bytes(content)

        # 探测元数据
        info = probe(dst)
        results.append({
            "id": file_id,
            "name": f.filename,
            "size": len(content),
            "info": info,
        })

    return {"uploads": results}


@app.post("/api/jobs")
async def create_job(payload: dict):
    job = Job(
        source_path=UPLOAD_DIR / f"{payload['source_id']}_...",  # 查找
        output_filename=payload["output_filename"],
        settings=TranscodeSettings(**payload["settings"]),
        metadata=MetadataEdit(**payload.get("metadata", {})),
    )
    job.total_duration_sec = probe(job.source_path)["duration"]
    jm.add(job)
    asyncio.create_task(jm.run(job.id))
    return {"job_id": job.id}


@app.get("/api/jobs")
async def list_jobs():
    return [j.model_dump(mode="json") for j in jm.jobs.values()]


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str):
    if job_id not in jm.jobs:
        raise HTTPException(404)
    await jm.cancel(job_id)
    return {"ok": True}


@app.get("/api/events")
async def events():
    return EventSourceResponse(event_stream(jm))


@app.get("/api/download/{job_id}")
async def download(job_id: str):
    job = jm.jobs.get(job_id)
    if not job or not job.output_path or not job.output_path.exists():
        raise HTTPException(404)
    return FileResponse(
        job.output_path,
        filename=f"{job.output_filename}{job.output_path.suffix}",
        media_type="application/octet-stream",
    )


@app.get("/api/download-zip")
async def download_zip(ids: str):
    job_ids = ids.split(",")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for jid in job_ids:
            job = jm.jobs.get(jid)
            if job and job.output_path and job.output_path.exists():
                zf.write(job.output_path, job.output_path.name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                              headers={"Content-Disposition": "attachment; filename=converted.zip"})


@app.get("/api/probe/{source_id}")
async def probe_source(source_id: str):
    # 找到上传文件
    matches = list(UPLOAD_DIR.glob(f"{source_id}_*"))
    if not matches:
        raise HTTPException(404)
    return probe(matches[0])


@app.get("/api/presets")
async def list_presets():
    return [p.model_dump() for p in PRESETS if p.enabled]
```

---

## 6. 前端（Vanilla JS）

### 6.1 app.js 关键模块

```js
// 1. SSE 连接
const es = new EventSource('/api/events');
es.addEventListener('job.list', e => renderJobs(JSON.parse(e.data)));
es.addEventListener('job.update', e => updateJob(JSON.parse(e.data)));
es.addEventListener('keepalive', e => {});

// 2. 文件上传
async function uploadFiles(files) {
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  const res = await fetch('/api/upload', { method: 'POST', body: fd });
  const { uploads } = await res.json();
  uploadedFiles.push(...uploads);
  renderFileList();
}

// 3. 选预设 → 填表
document.getElementById('preset').addEventListener('change', e => {
  const preset = presets.find(p => p.id === e.target.value);
  if (!preset) return;
  document.getElementById('format').value = preset.settings.format;
  document.getElementById('codec').value = preset.settings.codec;
  document.getElementById('bitrate').value = preset.settings.bitrate || '';
  document.getElementById('samplerate').value = preset.settings.samplerate;
  document.getElementById('channels').value = preset.settings.channels;
  document.getElementById('filename').value =
    `${baseName}${preset.filename_suffix}.${preset.extension}`;
});

// 4. 改字段 → 预设下拉重置
['format','codec','bitrate','quality','samplerate','channels']
  .forEach(id => document.getElementById(id).addEventListener('change', () => {
    document.getElementById('preset').value = '';
  }));

// 5. 启动转码
async function startConversion() {
  const settings = {
    format: document.getElementById('format').value,
    codec: document.getElementById('codec').value,
    bitrate: document.getElementById('bitrate').value || null,
    samplerate: parseInt(document.getElementById('samplerate').value),
    channels: parseInt(document.getElementById('channels').value),
    // ... 其他
  };
  const metadata = {
    title: document.getElementById('meta-title').value || null,
    artist: document.getElementById('meta-artist').value || null,
    // ...
  };
  for (const file of selectedFiles) {
    await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_id: file.id,
        output_filename: document.getElementById('filename').value,
        settings,
        metadata,
      })
    });
  }
}

// 6. 下载
function downloadJob(jobId) {
  window.location.href = `/api/download/${jobId}`;
}
```

---

## 7. 测试策略

### 7.1 单元测试

```python
# tests/test_presets.py
def test_opus_low_builds_correct_ffmpeg_args():
    p = PRESETS[1]  # opus_low_32k
    args = build_ffmpeg_args(Path("in.flac"), Path("out.opus"), p.settings)
    assert "-c:a" in args and "libopus" in args
    assert "-b:a" in args and "32k" in args
    assert "-ar" in args and "24000" in args
    assert "-ac" in args and "1" in args
    assert "-compression_level" in args and "10" in args


def test_aac_preset_disabled_by_default():
    p = PRESETS[0]  # aac_he_v2_48k
    assert p.enabled is False


# tests/test_progress.py
@pytest.mark.asyncio
async def test_progress_parser_handles_partial_chunks():
    chunks = [
        b"frame=1\r\nout_time_us=1000000\r\nprogress=continue\r\n",
        b"\nframe=2\r\nout_time_us=2000000\r\nprogress=continue\r\n",
    ]
    updates = []
    async for u in parse_progress(MockStream(chunks)):
        updates.append(u)
    assert len(updates) == 2


def test_progress_normalized_to_duration():
    pct = calc_progress(30_000_000, total_duration_sec=60.0)
    assert abs(pct - 50.0) < 0.01
```

### 7.2 端到端测试（见 04-verification.md）

---

## 8. 错误处理约定

### 8.1 错误码

| HTTP | 场景 |
|---|---|
| 400 | 请求体格式错误 |
| 404 | job_id / source_id 不存在 |
| 413 | 文件超过 MAX_UPLOAD_SIZE_MB |
| 500 | FFmpeg 崩溃（已捕获转 JobStatus.FAILED） |

### 8.2 Job 失败状态保留错误信息

```python
class Job(BaseModel):
    status: JobStatus
    error: str | None = None  # FFmpeg stderr 最后 500 字符
```

前端展示失败原因，**不丢失诊断信息**。

### 8.3 取消行为

```python
async def cancel(job_id: str):
    """取消任务，output_path 标记为 .partial，不允许下载"""
    proc = self.procs.get(job_id)
    if proc:
        proc.send_signal(signal.SIGTERM)
        await proc.wait()

    job = self.jobs[job_id]
    job.status = JobStatus.CANCELLED
    if job.output_path and job.output_path.exists():
        job.output_path.rename(job.output_path.with_suffix(job.output_path.suffix + ".partial"))
```

下载路由检查 `.partial` 后缀并 404。

---

## 9. 配置选项

可通过环境变量覆盖：

```bash
HAC_MAX_CONCURRENT=4 uvicorn hac.main:app
HAC_MAX_UPLOAD_MB=1000 uvicorn hac.main:app
HAC_DATA_DIR=/var/lib/audiobook-converter uvicorn hac.main:app
```

```python
# config.py
import os
MAX_CONCURRENT_JOBS = int(os.getenv("HAC_MAX_CONCURRENT", 2))
MAX_UPLOAD_SIZE_MB = int(os.getenv("HAC_MAX_UPLOAD_MB", 500))
DATA_DIR = Path(os.getenv("HAC_DATA_DIR", BASE_DIR / "data"))
```

---

## 10. 模板语法规范（v0.2 核心功能）

### 10.1 模板语法

```
${FieldName}              # 必填字段
${FieldName?}             # 可选字段（缺失填 None）
${FieldName:N}            # 数字零填充（N 位）
```

支持的 8 个字段：

| 字段 | 类型 | 匹配规则 | 适用语法 |
|---|---|---|---|
| `TrackNum` | int | `\d+`，去前导零存为 int | `${TrackNum}` / `${TrackNum:3}` |
| `TrackTitle` | str | 贪婪任意字符 | `${TrackTitle}` |
| `Artist` | str | 贪婪任意字符 | `${Artist}` |
| `Album` | str | 贪婪任意字符 | `${Album}` |
| `Year` | int | `\d{4}` 严格 4 位 | `${Year}` |
| `Genre` | str | 贪婪任意字符 | `${Genre}` |
| `DiscNum` | int | `\d+` | `${DiscNum}` |
| `Composer` | str | 贪婪任意字符 | `${Composer}` |

**模板语法解析正则**：

```python
TEMPLATE_RE = re.compile(
    r'\$\{([A-Za-z_][A-Za-z0-9_]*)'   # 字段名
    r'(\??)'                           # 可选标记
    r'(?::(\d+))?'                     # 格式化说明
    r'\}'
)
```

### 10.2 模板解析（parse_template）

把模板字符串解析成 `Segment` 列表：

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class Segment:
    kind: Literal["literal", "field"]
    value: str
    optional: bool = False
    format_spec: str | None = None

def parse_template(template: str) -> list[Segment]:
    segments = []
    pos = 0
    for m in TEMPLATE_RE.finditer(template):
        if m.start() > pos:
            segments.append(Segment(kind="literal", value=template[pos:m.start()]))
        segments.append(Segment(
            kind="field",
            value=m.group(1),
            optional=(m.group(2) == "?"),
            format_spec=m.group(3),
        ))
        pos = m.end()
    if pos < len(template):
        segments.append(Segment(kind="literal", value=template[pos:]))
    return segments
```

### 10.3 文件名匹配（match_filename）

**状态机匹配算法**：

```python
NUMERIC_FIELDS = {"track_num", "year", "disc_num"}

def match_filename(
    filename: str,
    segments: list[Segment],
    strict_pad: bool = False
) -> dict | None:
    """返回 {字段名: 值} 或 None（不匹配）"""
    # 扩展名处理：如果最后一个 segment 是 literal 且以 . 开头，
    # 把它视为扩展名，匹配前先去掉
    last_seg = segments[-1] if segments else None
    name_to_match = filename
    segments_to_match = segments
    if last_seg and last_seg.kind == "literal" and last_seg.value.startswith("."):
        ext = last_seg.value
        idx = filename.rfind(ext)
        if idx > 0:
            name_to_match = filename[:idx]
            segments_to_match = segments[:-1]

    result = {}
    pos = 0
    n = len(name_to_match)

    for i, seg in enumerate(segments_to_match):
        if seg.kind == "literal":
            if name_to_match[pos:pos+len(seg.value)] != seg.value:
                return None
            pos += len(seg.value)

        elif seg.kind == "field":
            # 找下一个 literal（如果有）
            next_literal_value = None
            for j in range(i+1, len(segments_to_match)):
                if segments_to_match[j].kind == "literal":
                    next_literal_value = segments_to_match[j].value
                    break

            if next_literal_value is None:
                # 最后一个字段，吃到末尾
                value = name_to_match[pos:].strip()
                pos = n
            else:
                idx = name_to_match.find(next_literal_value, pos)
                if idx == -1:
                    if seg.optional:
                        result[seg.value] = None
                        continue
                    return None
                value = name_to_match[pos:idx].strip()
                pos = idx

            # 数字字段特殊处理
            if seg.value in NUMERIC_FIELDS:
                parsed_value = _parse_numeric(value, seg.value, seg.format_spec, strict_pad)
                if parsed_value is None and not seg.optional:
                    return None
                result[seg.value] = parsed_value
            else:
                result[seg.value] = value

    return result


def _parse_numeric(value: str, field_name: str, format_spec: str | None, strict_pad: bool):
    """解析数字字段，处理零填充"""
    value = value.strip()

    if field_name == "year":
        # Year 严格 4 位
        if re.match(r'^\d{4}$', value):
            return int(value)
        return None

    if format_spec and strict_pad:
        # 严格要求位数
        pad = int(format_spec)
        if re.match(rf'^\d{{{pad}}}$', value):
            return int(value)
        return None

    # 宽松模式：任意位数
    if re.match(r'^\d+$', value):
        return int(value)
    return None
```

### 10.4 测试用例

```python
def test_basic_match():
    segments = parse_template("第${TrackNum}集 ${TrackTitle}.m4a")
    result = match_filename("第01集 哈利波特与凤凰社.m4a", segments)
    assert result == {"track_num": 1, "track_title": "哈利波特与凤凰社"}

def test_optional_field_with_optional_marker():
    segments = parse_template("Ch${TrackNum} - ${TrackTitle?}.mp3")
    result = match_filename("Ch01.mp3", segments)
    assert result == {"track_num": 1, "track_title": None}

def test_no_match_returns_none():
    segments = parse_template("第${TrackNum}集.mp3")
    result = match_filename("Ch01.mp3", segments)
    assert result is None

def test_tracknum_strict_pad():
    segments = parse_template("第${TrackNum:3}集.mp3", strict_pad=True)
    assert match_filename("第001集.mp3", segments) == {"track_num": 1}
    assert match_filename("第01集.mp3", segments) is None  # 严格模式：必须 3 位

def test_tracknum_loose_pad():
    segments = parse_template("第${TrackNum:3}集.mp3", strict_pad=False)
    assert match_filename("第001集.mp3", segments) == {"track_num": 1}
    assert match_filename("第01集.mp3", segments) == {"track_num": 1}  # 宽松：去前导零
    assert match_filename("第1集.mp3", segments) == {"track_num": 1}

def test_year_strict_4_digits():
    segments = parse_template("(${Year}) ${TrackTitle}.mp3")
    assert match_filename("(2003) Harry Potter.mp3", segments) == {"year": 2003, "track_title": "Harry Potter"}
    assert match_filename("(20) Harry Potter.mp3", segments) is None  # 必须 4 位
```

### 10.5 反向模板（render_filename）

```python
def render_filename(template: str, fields: dict) -> str:
    """反向模板渲染（用于生成新文件名）"""
    def repl(m):
        field_name = m.group(1)
        optional = m.group(2) == "?"
        fmt = m.group(3)

        if field_name not in fields or fields[field_name] is None:
            if optional:
                return ""
            raise ValueError(f"Missing required field: {field_name}")

        value = fields[field_name]
        if fmt and fmt.isdigit():
            if isinstance(value, int):
                return f"{value:0{int(fmt)}d}"
        return str(value)

    return re.sub(r'\$\{([^}?]+)(\??)(?::(\d+))?\}', repl, template)
```

---

## 11. 批处理 API（v0.2 完整设计）

### 11.1 数据模型

```python
from enum import Enum
from pydantic import BaseModel
from typing import Literal, Any

class AlbumArtistMode(str, Enum):
    USER_INPUT = "user_input"
    COPY_ARTIST = "copy_artist"
    EMPTY = "empty"

class BatchAlbumArtistConfig(BaseModel):
    mode: AlbumArtistMode = AlbumArtistMode.COPY_ARTIST
    user_value: str | None = None

class TrackNumConfig(BaseModel):
    zero_pad: int | None = 3            # 0 = 不补零，3 = 补到 3 位
    include_total: bool = True          # 是否包含总章节数
    total_value: int | None = None      # 用户指定的总数
    strict_pad: bool = False            # 严格匹配模式

class FilenameTemplate(BaseModel):
    template: str
    track_num_config: TrackNumConfig = Field(default_factory=TrackNumConfig)
    album_artist_config: BatchAlbumArtistConfig = Field(default_factory=BatchAlbumArtistConfig)
    skip_unmatched: bool = True
    fallback_title_to_filename: bool = True

class TemplateMatchEntry(BaseModel):
    file_id: str
    filename: str
    matched: bool
    parsed: dict[str, Any] | None = None
    fallback_notes: list[str] = []
    error: str | None = None

class TemplateMatchResult(BaseModel):
    template: FilenameTemplate
    total: int
    matched_count: int
    unmatched_count: int
    entries: list[TemplateMatchEntry]

class BatchApplyRequest(BaseModel):
    template: FilenameTemplate
    dry_run: bool = True
```

### 11.2 完整应用流程（核心函数）

```python
def apply_template_to_file(
    file: AudioFile,
    template: FilenameTemplate,
    total_files: int
) -> ApplyResult:
    """应用模板到一个文件（含所有 fallback 逻辑）"""
    # Step 1: 解析模板
    segments = parse_template(template.template)
    parsed = match_filename(
        file.filename,
        segments,
        strict_pad=template.track_num_config.strict_pad
    )

    if parsed is None:
        return ApplyResult(
            file_id=file.id,
            status="skipped",
            reason="模板不匹配"
        )

    fallback_notes = []

    # Step 2: TrackTitle fallback（决策 B）
    if not parsed.get("track_title"):
        if template.fallback_title_to_filename:
            parsed["track_title"] = Path(file.filename).stem.strip()
            fallback_notes.append(f"TrackTitle 从文件名 '{parsed['track_title']}' 替代")
        else:
            return ApplyResult(
                file_id=file.id,
                status="skipped",
                reason="TrackTitle 缺失且未启用 fallback"
            )

    # Step 3: TrackNum 格式化（带总数）
    if parsed.get("track_num") is not None:
        total = template.track_num_config.total_value or total_files
        parsed["track_num_formatted"] = format_track_with_total(
            parsed["track_num"],
            total,
            template.track_num_config.zero_pad,
            template.track_num_config.include_total
        )

    # Step 4: AlbumArtist（决策 A）
    if template.album_artist_config.mode == AlbumArtistMode.USER_INPUT:
        parsed["album_artist"] = template.album_artist_config.user_value
    elif template.album_artist_config.mode == AlbumArtistMode.COPY_ARTIST:
        parsed["album_artist"] = parsed.get("artist")
    else:
        parsed["album_artist"] = None

    return ApplyResult(
        file_id=file.id,
        status="applied",
        parsed=parsed,
        fallback_notes=fallback_notes
    )


def format_track_with_total(
    track_num: int,
    total: int,
    zero_pad: int | None,
    include_total: bool
) -> str:
    """格式化为 "001/2452" 格式"""
    track_str = f"{track_num:0{zero_pad}d}" if zero_pad else str(track_num)
    if include_total:
        return f"{track_str}/{total}"
    return track_str
```

### 11.3 API 端点

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/template/parse` | 解析模板语法，返回 segments |
| POST | `/api/template/match` | 试运行匹配（不写入） |
| POST | `/api/template/preview` | 匹配 + 与现有 ID3 对比 |
| POST | `/api/template/apply` | 写入元数据（跳过不匹配） |

### 11.4 ID3 tag 字段映射

```python
ID3_FIELD_MAP = {
    # 模板字段 → ID3 字段（每个格式的 key）
    "track_num":   {"mp3": "TRCK",   "vorbis": "TRACKNUMBER", "mp4": "trkn"},
    "track_title": {"mp3": "TIT2",   "vorbis": "TITLE",       "mp4": "\xa9nam"},
    "artist":      {"mp3": "TPE1",   "vorbis": "ARTIST",      "mp4": "\xa9ART"},
    "album":       {"mp3": "TALB",   "vorbis": "ALBUM",       "mp4": "\xa9alb"},
    "album_artist": {"mp3": "TPE2",  "vorbis": "ALBUMARTIST", "mp4": "aART"},
    "year":        {"mp3": "TDRC",   "vorbis": "DATE",        "mp4": "\xa9day"},
    "genre":       {"mp3": "TCON",   "vorbis": "GENRE",       "mp4": "\xa9gen"},
    "disc_num":    {"mp3": "TPOS",   "vorbis": "DISCNUMBER",  "mp4": "disk"},
    "composer":    {"mp3": "TCOM",   "vorbis": "COMPOSER",    "mp4": "\xa9wrt"},
}
```

---

## 12. 反向重命名 API（v0.2 完整设计）

### 12.1 数据模型

```python
class RenameStrategy(str, Enum):
    IN_PLACE = "in_place"
    NEW_DIR = "new_dir"
    ZIP = "zip"

class ConflictStrategy(str, Enum):
    SUFFIX = "suffix"
    ERROR = "error"

class FieldSource(str, Enum):
    TEMPLATE_PARSE = "template_parse"   # 从正向模板解析结果
    EXISTING_ID3 = "existing_id3"        # 从现有 ID3

class RenameRequest(BaseModel):
    template: str                           # 反向模板
    field_source: FieldSource = FieldSource.TEMPLATE_PARSE
    strategy: RenameStrategy = RenameStrategy.IN_PLACE
    conflict_strategy: ConflictStrategy = ConflictStrategy.SUFFIX
    sanitize: bool = True
    backup: bool = True                     # 生成 .bak
    zero_pad_track: int | None = None       # 写入时格式化位数

class RenameEntry(BaseModel):
    file_id: str
    old_path: str
    new_path: str
    has_conflict: bool = False
    sanitized: bool = False
    backup_path: str | None = None
    error: str | None = None

class RenamePreviewResult(BaseModel):
    total: int
    conflict_count: int
    sanitized_count: int
    entries: list[RenameEntry]

class RenameApplyResult(BaseModel):
    total: int
    success: int
    failed: int
    backup_created_count: int
    entries: list[RenameEntry]
```

### 12.2 重命名执行函数

```python
def sanitize_filename(name: str) -> str:
    """清理 macOS / Windows / Linux 都不允许的字符"""
    bad_chars = {
        '/': '-', '\\': '-', ':': '-',
        '*': '', '?': '', '"': "'",
        '<': '(', '>': ')',
        '|': '-', '\0': ''
    }
    result = name
    for old, new in bad_chars.items():
        result = result.replace(old, new)
    result = ''.join(c for c in result if ord(c) >= 32)
    return result.rstrip('. ')


def resolve_conflict(base_name: str, ext: str, existing: set[str]) -> str:
    """冲突处理：加 -1, -2, ... 直到不冲突"""
    if f"{base_name}{ext}" not in existing:
        return f"{base_name}{ext}"
    i = 1
    while f"{base_name}-{i}{ext}" in existing:
        i += 1
    return f"{base_name}-{i}{ext}"


def execute_rename(
    old_path: Path,
    new_path: Path,
    backup: bool = True
) -> tuple[bool, str | None]:
    """执行原地重命名（可备份）"""
    backup_path = None
    if backup and not old_path.with_suffix(old_path.suffix + ".bak").exists():
        shutil.copy2(old_path, old_path.with_suffix(old_path.suffix + ".bak"))
        backup_path = str(old_path.with_suffix(old_path.suffix + ".bak"))

    try:
        old_path.rename(new_path)
        return True, backup_path
    except Exception as e:
        return False, str(e)
```

### 12.3 API 端点

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/rename/preview` | 计算新文件名 + 冲突检测 |
| POST | `/api/rename/apply` | 执行重命名（原地） |
| POST | `/api/rename/undo` | v0.2：5 分钟内撤销 |

### 12.4 完整重命名流程

```
1. 用户输入反向模板: "${Album} - Ch${TrackNum:3} - ${TrackTitle}.opus"
2. 系统从"模板解析结果"或"现有 ID3"提取字段值
3. 调用 render_filename() 生成新文件名
4. sanitize_filename() 清理非法字符
5. detect_collisions() 检测冲突
6. 返回预览（包含旧路径、新路径、冲突标记、是否清理）
7. 用户确认
8. execute_rename() 执行（原地或新目录）
9. 返回执行报告（成功/失败、是否生成 .bak）
```
