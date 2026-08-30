# 03 · 路线图（Roadmap）

> **当前状态**：🟡 设计阶段（4 份文档已落地，**代码完全未开发**）
> **下一里程碑**：审完文档后起 v0.1 代码骨架

---

## 0. 当前进度

| 项 | 状态 |
|---|---|
| 项目目录 | ✅ 已创建 `/home/clawbot/workspace/audiobook-converter` |
| 设计文档 | ✅ 已写完 `docs/01-design.md`（591 行） |
| 技术规格 | ✅ 已写完 `docs/02-tech-spec.md`（1577 行） |
| 路线图 | ✅ 已写完 `docs/03-roadmap.md`（本文） |
| 验收标准 | ✅ 已写完 `docs/04-verification.md`（794 行） |
| 代码骨架 | ❌ **零代码，未开始** |
| 单元测试 | ❌ 未开发 |
| 端到端测试 | ❌ 未开发 |
| v0.1 MVP | ❌ 未开发（设计已敲定） |
| v0.2 元数据批处理 | ❌ 未开发（设计已敲定） |
| v0.3 播放+数据库 | ❌ 未开发（设计已敲定） |

---

## 1. MVP（v0.1）—— 最小可行产品

**目标**：从上传到下载完整跑通，Opus 三档可用

### 1.1 范围（设计已敲定，**代码未开发**）

- 📝 后端骨架：FastAPI + 9 个 API + JobManager
- 📝 FFmpeg 转码（含进度解析 + 取消）
- 📝 单文件元数据编辑（无封面）
- 📝 SSE 进度推送
- 📝 单文件下载
- 📝 前端三栏布局 + 预设下拉
- 📝 Opus 三档预设（32k/48k/64k）全部 enabled
- 📝 **Docker 容器化部署**（单镜像 + 可选 docker-compose，详见 §1.5）

### 1.2 不做（明确边界）

- ❌ FDK-AAC 预设（`enabled=False`，UI 隐藏）
- ❌ 封面图嵌入（API 接受 `cover_path` 但不实现写入）
- ❌ Zip 批量下载
- ❌ 预设管理 UI（配置文件直接编辑）
- ❌ 任务历史持久化（重启即清空）
- ❌ 多用户/鉴权
- ❌ 实时波形预览

### 1.3 工作量估算

| 任务 | 文件 | 估算行数 |
|---|---|---|
| 项目初始化 | `pyproject.toml` | 20 |
| 配置模块 | `config.py` | 50 |
| 预设定义 | `presets.py` | 100 |
| 数据模型 | `models.py` | 80 |
| FFprobe 探测 | `probe.py` | 40 |
| 转码引擎 | `transcoder.py` | 150 |
| 元数据写入 | `metadata.py` | 120 |
| 任务管理 | `jobs.py` | 120 |
| SSE 事件流 | `events.py` | 50 |
| FastAPI 路由 | `main.py` | 200 |
| 前端 HTML | `index.html` | 200 |
| 前端 JS | `app.js` | 400 |
| 前端样式 | `styles.css` | 200 |
| **总计** | | **~1730 行** |

按 Karpathy 准则 #2（简洁优先），实际可能更短。

**Docker 部署（v0.1 补丁，详见 §1.5）**：

| 文件 | 估算行数 |
|---|---|
| `Dockerfile` | 30 |
| `docker-compose.yml` | 15 |
| `.dockerignore` | 20 |
| **总计** | **~65 行** |

### 1.4 验收（详见 04-verification.md）

1. 上传 50MB FLAC → 看到上传进度
2. 选 Opus 中(48k) → 看到 FFmpeg 实时进度（从 stderr 解析）
3. 输出文件 `ffprobe` 验证：codec=opus, bit_rate≈48k, channels=1
4. 元数据（title/artist）正确嵌入（`mutagen-inspect` 验证）
5. 点击下载浏览器收到正确的 `.opus` 文件
6. 取消任务后输出文件无法下载（标记 .partial）

### 1.5 Docker 部署（v0.1 新增）

**目标**：一行命令拉起容器，本地/局域网/远程都能跑。

**设计决策**：

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| 1 | 容器拓扑 | **单容器**（可选 docker-compose 附加）| 本地工具，不需要多服务 |
| 2 | 基础镜像 | **`python:3.11-slim`** + apt 装 ffmpeg | 官方镜像稳定，体积可接受 |
| 3 | libfdk_aac | **不启用**（apt 默认 ffmpeg 不含）| 与 v0.1 preset 设计一致 |
| 4 | 数据持久化 | **必挂 volume** `./data:/app/data` | 容器重启即丢数据，必须挂载 |
| 5 | 端口 | **8000** | 与本地开发一致 |
| 6 | 用户权限 | **非 root 用户 `app`** | 安全最佳实践 |
| 7 | 健康检查 | **`/api/health` + curl** | 容器编排友好 |
| 8 | `.dockerignore` | **要写**（与 `.gitignore` 类似但更严）| 减小构建上下文 |
| 9 | GitHub Actions 自动构建 | **不做**（本地工具，无需 CI） | 简化维护 |

**镜像规格（估算）**：

```
基础镜像: python:3.11-slim  → ~120MB
+ ffmpeg (apt)              → ~200MB
+ Python deps (fastapi 等)   → ~50MB
+ 应用代码                   → <5MB
─────────────────────────────
总计:                        ~375MB
```

**部署命令（用户视角）**：

```bash
# 1. 拉取/构建镜像
docker build -t audiobook-converter .

# 2. 运行容器（一条命令）
docker run -d \
  --name audiobook-converter \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  audiobook-converter

# 3. 浏览器访问
open http://localhost:8000
```

或用 docker-compose：

```bash
docker compose up -d
```

**Dockerfile 关键点（设计稿，v0.1 代码阶段实现）**：

```dockerfile
FROM python:3.11-slim

# 系统依赖：ffmpeg + 健康检查用 curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 非 root 用户
RUN useradd -m -u 1000 app
WORKDIR /app
USER app

# Python 依赖
COPY --chown=app:app pyproject.toml ./
RUN pip install --no-cache-dir -e .

# 应用代码
COPY --chown=app:app src/ ./src/
COPY --chown=app:app static/ ./static/

# 数据目录（volume 挂载点）
RUN mkdir -p /app/data/uploads /app/data/outputs

# 环境变量
ENV HAC_DATA_DIR=/app/data \
    HAC_MAX_CONCURRENT=4

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# 入口点
EXPOSE 8000
ENTRYPOINT ["uvicorn", "hac.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml 草案**：

```yaml
services:
  web:
    build: .
    container_name: audiobook-converter
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    environment:
      - HAC_DATA_DIR=/app/data
      - HAC_MAX_CONCURRENT=4
```

**.dockerignore 草案**：

```
.git/
.gitignore
__pycache__/
*.py[cod]
.venv/
venv/
data/
uploads/
outputs/
logs/
*.log
*.partial
*.bak
tests/
docs/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.vscode/
.idea/
.DS_Store
README.md
*.md
!docs/  # 注意：如需复制文档进镜像，单独添加
```

**已知限制**：

| 限制 | 影响 | 缓解 |
|---|---|---|
| apt 装的 ffmpeg 无 libfdk_aac | HE-AAC v2 preset 无法启用 | 已在 `enabled=False` |
| 容器内时间默认 UTC | 转码日志时间戳与本地不同 | 容器启动时 `TZ` 环境变量 |
| 文件权限问题（容器内 uid=1000） | volume 挂载的目录权限不匹配 | 启动前 `chown -R 1000:1000 ./data` |

---

## 2. v0.2 —— 元数据批处理（最高优先级）

**目标**：解决用户最大痛点——几千章音频导入 Apple Books 后排序混乱。

详见 `docs/03-roadmap.md` §8 完整范围。

### 2.1 核心范围（设计已敲定，**代码未开发**）

- 📝 **模板语法**（8 个字段）：TrackNum / TrackTitle / Artist / Album / Year / Genre / DiscNum / Composer
- 📝 **AlbumArtist 三种模式**：复制 Artist / 用户输入 / 留空
- 📝 **TrackNum 写入带总数**：格式 `001/2452`
- 📝 **反向模板**：批量重命名（原地/新目录/zip 三策略）
- 📝 **强制预览 + .bak 备份**
- ❌ FDK-AAC 预设（仍 `enabled=False`，等静态 ffmpeg 支持）

---

## 3. v0.3 —— 流媒体播放 + 数据库

**目标**：闭环播放体验 + 持久化能力，让工具从"转码器"升级为"音频库管理器"。

详见 `docs/03-roadmap.md` §9 完整范围。

### 3.1 范围（设计已敲定，**代码未开发**）

- 📝 Range 请求流（HTTP 206）支持 seek、A-B 循环
- 📝 A/B 同步对比播放（拖动任一侧，另一侧跟随）
- 📝 章节跳转（mutagen 读 ID3 CHAP + 按 TrackNum 切）
- 📝 SQLite + SQLModel 数据库（4 张表）
- 📝 5 分钟撤销窗口（重命名可撤销）
- 📝 任务历史持久化（重启后能看到历史任务）
- 📝 文件库视图（按 album/artist 分组浏览）

### 3.2 不做（v0.3 明确边界）

- ❌ 实时波形/频谱（Web Audio API）—— v0.4
- ❌ 预设管理 UI（增删改预设）—— 延后
- ❌ 拖拽排序输出文件 —— 延后
- ❌ 自动响度归一化（loudnorm）—— 延后
- ❌ 主题切换（暗/亮）—— 延后

---

## 4. 不做的功能（永久）

| 功能 | 不做的理由 |
|---|---|
| 用户账号 / 鉴权 | 单用户本地工具，加账号是过度设计 |
| 云端存储 / 同步 | 违背本地优先原则，隐私成本高 |
| 实时波形预览 | Web Audio API 解码成本高，与"压缩工具"定位不符（v0.4+ 评估） |
| 多设备同步 | 加账号 + 云端，违背原则 |
| 云盘上传（WebDAV/S3/OAuth） | 涉及第三方账号 + Token 管理，v0.4 候选，长期可做 |
| AI 自动选参 | 用户场景明确（有声书），预设已经覆盖 |

> **注意**：之前版本曾列出"数据库（除 SQLite）"和"流媒体播放"为不做项——**这两项已在 v0.3 重新纳入**（§3）。

---

## 5. 已知技术债务与风险

| 项 | 影响 | 缓解 |
|---|---|---|
| 静态 ffmpeg 不含 libfdk_aac | FDK-AAC 预设不可用 | 文档明示 + `enabled=False` 兜底 |
| SSE 在 nginx 后会超时 | 长任务断连 | 文档明示 nginx 配置：`proxy_buffering off; proxy_read_timeout 86400;` |
| 服务重启任务丢失 | 用户体验差 | MVP 接受；v0.3 加 SQLite |
| 大文件上传内存压力 | OOM 风险 | 流式读 + 分块写入 |
| mutagen API 按格式分裂 | 代码复杂度 | 抽象 `_write_X()` 函数 |

---

## 6. 未来扩展方向（未列入 v0.x）

- 接入 MusicBrainz 指纹识别，自动补元数据
- 多任务并行下载（zip split）
- 移动端 PWA 化（添加 manifest.json + service worker）
- CLI 模式（`hac-cli transcode --preset opus_low *.flac`）
- WebSocket 替代 SSE（双向通信，便于"前端主动取消"）

---

## 7. 决策记录（ADR-style）

### ADR-001: 为什么不用数据库？

**决定**：MVP 用内存 JobManager + 落盘文件

**理由**：
- 任务生命周期短（分钟级）
- 数据量小（每个 Job < 1KB metadata）
- 持久化收益小（重启即重新上传）

**反悔条件**：用户希望"明天接着昨天的进度" → 加 SQLite

### ADR-002: 为什么 FDK-AAC 预设暂时禁用？

**决定**：保留配置但 `enabled=False`，UI 不显示

**理由**：
- `imageio-ffmpeg` 默认下载不含 libfdk_aac
- 让用户自编译会卡住大部分用户
- 但完全删掉预设 = 失去未来扩展点

**反悔条件**：用户主动编译了含 libfdk_aac 的 ffmpeg → 改 `enabled=True`

### ADR-003: 为什么采样率统一 24000？

**决定**：所有有声书预设填 24000 Hz

**理由**：
- 24000 是 Opus 的原生采样率（最高效）
- 22050 是 HE-AAC v2 的工作采样率（ffmpeg 会自动重采样）
- 统一填 24000 让 ffmpeg 按 codec 需求自适应
- UI tooltip 说明这点，避免用户困惑

### ADR-004: 为什么预设 compression_level: 10？

**决定**：Opus 三个预设都用 compression_level=10

**理由**：
- 离线转码，实时性无所谓
- 等级越高 = 压缩率越高 + 编码越慢
- 等级 0 是"实时优化"，等级 10 是"最佳压缩"
- 对 1h 有声书，慢几秒换 5-10% 体积下降，划算

**反悔条件**：用户觉得太慢 → 加高级开关让用户选 0-10

### ADR-005：模板语法 vs 正则（v0.2）

**决定**：用 `${Field}` 模板语法，不用正则。

**理由**：
- 正则对普通用户门槛过高
- 模板语法把"正则"封装成"自然语言填空"
- 90% 场景不需要正则的灵活性

### ADR-006：AlbumArtist 独立配置而非模板字段（v0.2）

**决定**：`${AlbumArtist}` 不在模板语法里，独立用"三种模式"配置。

**理由**：
- AlbumArtist 是"专辑级"字段，所有章节共享
- 从文件名提取 AlbumArtist 没有意义
- 模板只暴露 `${Artist}`（章节级），AlbumArtist 在配置里决定

### ADR-007：TrackTitle 缺失时用文件名 fallback（v0.2）

**决定**：TrackTitle 缺失不报错，自动用文件名（去扩展名）替代。

**理由**：
- Apple Books 没 title 会 fallback 到文件名，中文文件名按 Unicode 编码排序会乱
- 完全跳过文件太激进——大多数文件至少有文件名信息
- 用文件名替代是"有信息胜于无"的折中

### ADR-008：重命名默认原地修改 + 强制预览（v0.2）

**决定**：默认原地重命名，但必须先预览 + 用户确认。

**理由**：
- 用户期望"重命名 = 直接生效"，避免中间目录污染
- 强制预览确保用户看清每个新文件名再下手
- 可选 `.bak` 备份降低误操作风险

### ADR-009：v0.2 优先做元数据批处理而非其他特性（v0.2）

**决定**：v0.2 把元数据批处理（模板解析 + 反向重命名 + AlbumArtist 三模式）提到最高优先级，zip 批量下载、封面图等延后。

**理由**：
- 用户痛点明确：导入 Apple Books 后排序混乱
- 这是工具的核心使用价值，超过任何其他特性
- 实现复杂度可控（核心算法 ~500 行）

---

## 8. v0.2 详细范围

### 8.1 核心功能（设计已敲定，**代码未开发**）

- 📝 **模板语法**（8 个字段）：TrackNum / TrackTitle / Artist / Album / Year / Genre / DiscNum / Composer
- 📝 **AlbumArtist 三种模式**：复制 Artist / 用户输入 / 留空
- 📝 **TrackNum 写入带总数**：格式 `001/2452`
- 📝 **零填充三场景支持**：模板匹配 + 写入 ID3 + 反向模板
- 📝 **TrackTitle fallback**：缺失时用文件名
- 📝 **反向模板**：批量重命名（原地/新目录/zip 三策略）
- 📝 **强制预览 + .bak 备份**：重命名前的安全网
- 📝 **冲突自动后缀**：`-1`、`-2`

### 8.2 暂不做

- ❌ Zip 批量下载（v0.3）
- ❌ 封面图嵌入（v0.3）
- ❌ SQLite 历史（v0.3）
- ❌ 重命名撤销（v0.3，依赖历史）
- ❌ 组合模板（多模板叠加，永久不做）

### 8.3 工作量估算

| 任务 | 文件 | 估算行数 |
|---|---|---|
| 模板语法解析 | `template.py` | 250 |
| 反向模板渲染 | 同上 | 80 |
| 模板 API | `routers/template.py` | 120 |
| 重命名 API | `routers/rename.py` | 150 |
| 字段映射扩展 | `metadata.py` | +100 |
| 前端批处理 UI | `batch.html` + `batch.js` | 600 |
| 单元测试 | `tests/test_template.py` | 200 |
| **总计** | | **~1500 行** |

### 8.4 v0.2 验收

参见 `docs/04-verification.md` §10/11/12。

---

## 9. v0.3 详细范围

**目标**：闭环播放体验 + 持久化能力，让工具从"转码器"升级为"音频库管理器"。

### 9.1 流媒体播放（核心新增，设计已敲定，**代码未开发**）

**功能清单**：

- 📝 **Range 请求支持**（HTTP 206 Partial Content）—— 支持 seek、A-B 循环
- 📝 **A/B 同步播放** —— 拖动任一侧，另一侧自动跟随（±100ms 同步精度）
- 📝 **章节跳转** —— mutagen 读 ID3 CHAP 标记 + 按 TrackNum 切
- 📝 **音量独立控制** —— 源/编码两侧独立音量
- 📝 **键盘快捷键** —— 空格播放/暂停、← → 跳转 5s、J K L 倍速
- 📝 **Safari fallback 提示** —— FLAC/OGG 在 Safari 不支持时显示"建议 Chrome/Edge"
- ❌ 实时波形/频谱（Web Audio API）—— v0.4
- ❌ 直播流（Icecast/Shoutcast）—— 永久不做

**关键约束**：

| 浏览器 | 支持格式 |
|---|---|
| Chrome / Edge / Firefox | MP3, WAV, FLAC, OGG, Opus, M4A, AAC 全支持 |
| Safari | MP3, WAV, M4A, AAC 支持；FLAC, OGG, Opus 显示提示 |

**流媒体端点设计**：

```python
# 关键：支持 Range 请求
@app.get("/api/stream/{file_id}")
async def stream(file_id: str, request: Request):
    file_path = get_file_path(file_id)
    file_size = file_path.stat().st_size

    range_header = request.headers.get("range")
    if range_header:
        # 解析 Range: bytes=0-1023
        start, end = parse_range(range_header, file_size)
        return StreamingResponse(
            file_chunks(file_path, start, end),
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
                "Content-Type": "audio/mpeg",  # 按实际格式
            }
        )
    else:
        return FileResponse(file_path, headers={"Accept-Ranges": "bytes"})
```

**章节标记读取**：

```python
def read_chapters(file_path: Path) -> list[Chapter]:
    """mutagen 读 ID3 CHAP + Vorbis CHAPTER + MP4 chpl"""
    audio = mutagen.File(file_path)

    if isinstance(audio, mutagen.mp3.MP3):
        return [
            Chapter(start=ct.start, end=ct.end, title=str(ct.title))
            for ct in (audio.get("CTOC") or [])
        ]
    elif isinstance(audio, mutagen.flac.FLAC) or isinstance(audio, mutagen.oggvorbis.OggVorbis):
        # Vorbis CHAPTER 标记
        ...
    elif isinstance(audio, mutagen.mp4.MP4):
        # chpl atom
        ...
```

### 9.2 数据库（核心新增）

**技术选型**：SQLModel（与 Pydantic 兼容，类型安全，boilerplate 少）

**4 张表 + 索引**：

```sql
-- 文件表：所有上传过的文件元数据
CREATE TABLE files (
    id TEXT PRIMARY KEY,           -- uuid
    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,    -- 磁盘绝对路径
    file_size INTEGER,
    duration REAL,
    codec TEXT,
    bitrate INTEGER,
    sample_rate INTEGER,
    channels INTEGER,
    uploaded_at TIMESTAMP,
    deleted_at TIMESTAMP,          -- 软删除标记

    -- 当前元数据（最新一次写入）
    title TEXT,
    artist TEXT,
    album TEXT,
    album_artist TEXT,
    track_num INTEGER,
    disc_num INTEGER,
    year INTEGER,
    genre TEXT,
    composer TEXT,
    has_chapters BOOLEAN DEFAULT 0
);

-- 转码任务表
CREATE TABLE transcode_jobs (
    id TEXT PRIMARY KEY,
    source_file_id TEXT REFERENCES files(id),
    output_path TEXT NOT NULL,
    preset_id TEXT,
    status TEXT,                    -- pending/running/done/failed/cancelled
    progress REAL DEFAULT 0,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error TEXT,
    output_size INTEGER,
    output_duration REAL
);

-- 批处理会话表（v0.2 模板批处理的持久化）
CREATE TABLE batch_sessions (
    id TEXT PRIMARY KEY,
    template TEXT,
    config_json TEXT,                -- FilenameTemplate 序列化
    field_source TEXT,
    created_at TIMESTAMP,
    applied_count INTEGER,
    skipped_count INTEGER,
    status TEXT                      -- pending/running/done/cancelled
);

-- 备份表（撤销机制依赖）
CREATE TABLE file_backups (
    id TEXT PRIMARY KEY,
    original_path TEXT NOT NULL,
    backup_path TEXT NOT NULL,      -- .bak 文件路径
    created_at TIMESTAMP,
    restore_deadline TIMESTAMP,     -- 5 分钟后过期
    restored_at TIMESTAMP           -- 已恢复时间
);

CREATE INDEX idx_files_uploaded_at ON files(uploaded_at DESC);
CREATE INDEX idx_files_album ON files(album);
CREATE INDEX idx_jobs_status ON transcode_jobs(status);
CREATE INDEX idx_backups_deadline ON file_backups(restore_deadline) WHERE restored_at IS NULL;
```

**关键边界**：

| 决策 | 行为 |
|---|---|
| **软删除** | `DELETE /api/files/{id}` 只设 `deleted_at`，磁盘文件保留 |
| **手动清理** | `POST /api/cleanup` 删除 `deleted_at` 非空的文件 |
| **启动扫描** | 启动时遍历 `storage_path` 目录，与数据库对比，缺失的建索引，多余的标记孤儿 |
| **磁盘是真相** | 数据库元数据可重建，文件本身不能丢 |

**SQLModel 模型示例**：

```python
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class File(SQLModel, table=True):
    __tablename__ = "files"

    id: str = Field(primary_key=True)
    original_filename: str
    storage_path: str
    file_size: Optional[int] = None
    duration: Optional[float] = None
    codec: Optional[str] = None
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    uploaded_at: datetime
    deleted_at: Optional[datetime] = None

    # 元数据
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    track_num: Optional[int] = None
    disc_num: Optional[int] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    composer: Optional[str] = None
    has_chapters: bool = False


class TranscodeJob(SQLModel, table=True):
    __tablename__ = "transcode_jobs"

    id: str = Field(primary_key=True)
    source_file_id: str = Field(foreign_key="files.id")
    output_path: str
    preset_id: str
    status: str
    progress: float = 0.0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    output_size: Optional[int] = None
    output_duration: Optional[float] = None


class FileBackup(SQLModel, table=True):
    __tablename__ = "file_backups"

    id: str = Field(primary_key=True)
    original_path: str
    backup_path: str
    created_at: datetime
    restore_deadline: datetime
    restored_at: Optional[datetime] = None
```

### 9.3 撤销机制（v0.3 同步上线）

**5 分钟可撤销窗口**：

```python
def execute_rename(old_path: Path, new_path: Path) -> tuple[bool, str]:
    """重命名时自动建备份记录"""
    backup_path = old_path.with_suffix(old_path.suffix + ".bak")
    shutil.copy2(old_path, backup_path)

    # 数据库记录（5 分钟后过期）
    backup = FileBackup(
        id=uuid4(),
        original_path=str(old_path),
        backup_path=str(backup_path),
        created_at=datetime.utcnow(),
        restore_deadline=datetime.utcnow() + timedelta(minutes=5)
    )

    try:
        old_path.rename(new_path)
        session.add(backup)
        session.commit()
        return True, str(backup.id)
    except Exception as e:
        backup_path.unlink(missing_ok=True)
        return False, str(e)


def undo_rename(backup_id: str) -> bool:
    """5 分钟内可撤销"""
    backup = session.get(FileBackup, backup_id)

    if backup.restored_at is not None:
        raise ValueError("已撤销过")
    if datetime.utcnow() > backup.restore_deadline:
        raise ValueError("超过 5 分钟撤销窗口")

    # 找到对应的新文件路径
    new_path = ...  # 从 rename_log 查

    if not Path(new_path).exists():
        raise FileNotFoundError("新文件已被删除或移动")

    # 恢复原名
    shutil.move(str(new_path), backup.original_path)

    backup.restored_at = datetime.utcnow()
    session.commit()

    # 删除 .bak
    Path(backup.backup_path).unlink(missing_ok=True)

    return True
```

**前端 UX**：

```
┌─────────────────────────────────────────────────────────┐
│ 🔄 重命名成功                                             │
│                                                         │
│ ✅ 2452 个文件已重命名                                    │
│ ⏱ 撤销窗口剩余: 4 分 32 秒                                │
│                                                         │
│ [↩️ 撤销重命名]  [关闭窗口]                              │
└─────────────────────────────────────────────────────────┘
```

5 分钟倒计时，0 秒后按钮变灰。

### 9.4 工作量估算

| 任务 | 文件 | 估算行数 |
|---|---|---|
| Range 请求流 | `routers/stream.py` | 80 |
| 章节读取 | `chapters.py` | 120 |
| 数据库模型 | `db/models.py` | 150 |
| 数据库初始化 + 迁移 | `db/init.py` | 80 |
| 启动扫描 | `db/scan.py` | 100 |
| 撤销机制 | `routers/undo.py` | 100 |
| 播放器 UI | `player.html` + `player.js` | 400 |
| A/B 对比 UI | `compare.html` + `compare.js` | 350 |
| 单元测试 | `tests/test_db.py` + `tests/test_stream.py` | 250 |
| **总计** | | **~1630 行** |

### 9.5 验收

参见 `docs/04-verification.md` §14（v0.3 验收）。

---

## 10. v0.4+ 路线图（暂不实施）

**以下功能推迟到 v0.4+，等待 v0.3 用户反馈**：

### 10.1 云盘上传（v0.4 候选）

- **协议**：WebDAV（坚果云、Nextcloud）+ S3 兼容（MinIO、R2、AWS S3）
- **OAuth 推迟**：OneDrive / Google Drive / Dropbox 的 OAuth 流程较重，放 v0.5+
- **上传粒度**：整批 zip 上传（依赖 v0.3 zip 打包功能）
- **凭证存储**：明文 config.yaml（v0.4），加密存数据库（v0.5+）

### 10.2 高级播放功能（v0.4 候选）

- 实时波形/频谱（Web Audio API + Canvas）
- 批量波形对比（同一波形叠加显示）
- A/B 盲测（随机顺序，让用户盲选哪个更好）
- 响度归一化（EBU R128 / ReplayGain）

### 10.3 数据库演进（v0.5+）

- 全文搜索（标题/专辑/作者 FTS5 索引）
- 智能分组（按专辑自动归类）
- 重复文件检测（基于 fingerprint）
- 标签系统（自定义标签）

### 10.4 多用户/云端（永久不做）

工具定位是"本地单用户"，不演进为云服务。

---

## 11. 决策记录（v0.3 新增 ADR）

### ADR-010：流媒体用 Range 请求 + HTML5 audio，不用 ffmpeg 转码

**决定**：用 HTTP Range 请求 + 浏览器原生 `<audio>` 标签。

**理由**：
- HTML5 `<audio>` 在 Chrome/Edge/Firefox 上支持所有主流格式
- Safari 不支持 FLAC/OGG，但显示提示即可（用户能选浏览器）
- ffmpeg 实时转码为 MP3 流的 CPU 开销大（一个文件 10-30s 转码才能开播），且占用内存
- Range 请求支持 seek、A-B 循环等高级功能

**反悔条件**：用户报告"必须支持 Safari + FLAC" → 加 ffmpeg 转码分支

### ADR-011：SQLite + SQLModel

**决定**：用 SQLite 数据库 + SQLModel ORM。

**理由**：
- 任务历史、批处理会话、备份索引都需要持久化
- SQLModel 与 Pydantic 兼容，API 模型直接复用
- SQLite 零运维，单文件备份方便
- 比 SQLAlchemy Core 少 50%+ boilerplate

**反悔条件**：需要多进程共享数据库 → 切 PostgreSQL（v0.5+ 几乎不可能需要）

### ADR-012：软删除 + 手动 cleanup

**决定**：删除文件不立即 rm，只设 `deleted_at` 标记。

**理由**：
- 元数据误删可恢复（撤销机制需要）
- 批量删除给用户"反悔期"
- 手动 `/api/cleanup` 端点让用户控制清理时机
- 与 Apple Finder 的"移到废纸篓"心智模型一致

**反悔条件**：用户要"真删除" → 在 cleanup 端点加 `--hard` 选项

### ADR-013：启动扫描磁盘重建索引

**决定**：启动时遍历磁盘文件目录，与数据库对比，补缺失 + 标记孤儿。

**理由**：
- "磁盘是真相"——文件在磁盘上就视为存在
- 数据库可丢失/损坏，重建即可
- 防止"数据库说文件存在但磁盘上没了"这种不一致
- 用户手动 `rm` 删除的文件自动从数据库消失

**反悔条件**：磁盘 IO 太大 → 加 `--no-scan` 启动参数跳过

### ADR-014：v0.1 阶段就支持 Docker 单镜像部署（v0.1 补丁）

**决定**：v0.1 完成时同时交付 Dockerfile + docker-compose.yml + .dockerignore，用户可一行命令跑容器。

**理由**：
- 部署形态多样化：开发机用 Python、NAS/服务器用 Docker
- 工具定位是"本地工具"，但不少用户用 NAS 或远程服务器
- 一行 `docker run` 比"安装 Python + 装 ffmpeg + 拉依赖"对用户友好得多
- 官方 Python 镜像 + apt 装 ffmpeg 简单可靠，无需多阶段构建

**反悔条件**：用户反馈"需要更复杂的部署（K8s/Swarm）" → 升级为 Helm Chart 或 Compose 多服务

---

## 12. 总时间线（更新）

```
v0.1 (MVP)          ██████░░░░░░ 设计敲定 ░░░░░░░ 代码未开发（~1730 行待写）
v0.2 (元数据批处理)   ██████░░░░░░ 设计敲定 ░░░░░░░ 代码未开发（~1500 行待写）
v0.3 (播放+数据库)    ██████░░░░░░ 设计敲定 ░░░░░░░ 代码未开发（~1630 行待写）
v0.4 (云盘+高级)      ░░░░░░░░░░░░ 等待 v0.3 反馈
v0.5 (OAuth+FTS)      ░░░░░░░░░░░░ 长期规划
```

**当前阶段**：🟡 设计阶段——4 份文档（3736 行）已落地，**代码完全未开发**。
