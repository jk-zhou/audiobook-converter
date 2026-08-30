# Audiobook Converter

> 简易版网页 foobar2000 —— 一个支持多文件批量转码、元数据编辑、后台任务管理的 Web App。
> 主场景：有声书批量压成 Opus/AAC（32-64 kbps），单声道、24 kHz、体积砍 80%+。

---

## 它能做什么

> ⚠️ **当前状态**：全部为已设计/已规划，**代码尚未开始开发**。详见 `docs/03-roadmap.md` §1 状态表。

### v0.1 (MVP) 📝 已设计
- 📝 上传多个音频文件（aac / mp3 / wav / flac / ogg / opus / m4a…）
- 📝 选择目标格式 / 编码 / 码率 / 采样率 / 声道
- 📝 4 个开箱即用的有声书预设（FDK-AAC 48k 暂未启用 + Opus 32/48/64k 三档）
- 📝 批量编辑元数据（标题 / 艺术家 / 专辑 / 封面）
- 📝 后台执行转码，单文件进度 + 总进度 SSE 推送
- 📝 单文件下载 / 批量 zip 下载

### v0.2 (元数据批处理) 📝 已设计
- 📝 **模板语法**（8 个字段）—— `第${TrackNum}集 ${TrackTitle} - ${Artist}.m4a`
- 📝 **AlbumArtist 三种模式** —— 复制 Artist / 用户输入 / 留空
- 📝 **TrackNum 带总数格式** —— `TRCK = "001/2452"` 让 Apple Books 排序最稳
- 📝 **反向模板批量重命名** —— 原地修改 + 强制预览 + 自动 .bak 备份
- 📝 **TrackTitle fallback** —— 缺失时用文件名替代

### v0.3 (流媒体播放 + 数据库) 📝 已设计
- 📝 **Range 请求流** —— 支持 seek、A-B 循环
- 📝 **A/B 同步对比播放** —— 拖动任一侧，另一侧跟随
- 📝 **章节跳转** —— mutagen 读 ID3 CHAP + 按 TrackNum 切
- 📝 **SQLite + SQLModel** —— 任务历史、批处理会话、撤销机制
- 📝 **5 分钟撤销窗口** —— 重命名可撤销

### v0.4+ (暂不实施)
- ⏸ 云盘上传（WebDAV / S3）
- ⏸ 实时波形/频谱
- ⏸ OAuth（OneDrive / Google Drive）
- ⏸ 全文搜索、重复检测


---

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/01-design.md](docs/01-design.md) | 设计文档：产品定位、技术选型、架构图、UI 布局、数据流 |
| [docs/02-tech-spec.md](docs/02-tech-spec.md) | 技术规格：数据模型、API 设计、FFmpeg 参数映射、SSE 协议 |
| [docs/03-roadmap.md](docs/03-roadmap.md) | 路线图：MVP / v0.2 / v0.3 范围 + 已知未做项 |
| [docs/04-verification.md](docs/04-verification.md) | 验收标准：端到端测试 + 主观听感参考 |

---

## 技术栈一览

| 层 | 选型 | 理由 |
|---|---|---|
| 后端框架 | **FastAPI** (Python 3.11+) | 异步原生 + SSE 友好 + 类型提示 |
| 转码引擎 | **FFmpeg**（静态二进制） | 行业事实标准，格式覆盖 99% |
| 元数据 | **mutagen** | MP3/FLAC/MP4/Opus 全覆盖，支持封面嵌入 |
| 任务调度 | **asyncio + Semaphore** | 单用户场景，无需 Redis/Celery |
| 前端 | **Vanilla JS + HTML5 + CSS** | 无构建步骤，单页三栏 |
| 进度推送 | **Server-Sent Events (SSE)** | 比 WebSocket 简单，HTTP 兼容 |

---

## 快速理解（30 秒版）

```
浏览器 ─HTTP/POST─> FastAPI ─subprocess─> FFmpeg ─转码─> 输出文件
   ↑                   │                          │
   └─── SSE 推送 ──────┴──── mutagen 写元数据 ────�
```

文件生命周期：
1. 用户拖文件 → POST `/api/upload` → 文件存到 `data/uploads/{uuid}/`
2. 用户填参数 → POST `/api/jobs` → Job 进入队列
3. 后台 Worker pick up → spawn ffmpeg → 实时解析进度 → SSE 推到前端
4. 转码完成 → mutagen 写元数据 → 标记 status=done
5. 用户 GET `/api/download/{id}` → 浏览器下载

---

## 部署方式（v0.1 计划）

### 方式 1：本地 Python（开发用）

```bash
pip install -e .
uvicorn hac.main:app --host 0.0.0.0 --port 8000
```

### 方式 2：Docker 单容器（推荐）

```bash
docker build -t audiobook-converter .
docker run -d \
  --name audiobook-converter \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  audiobook-converter

# 浏览器访问 http://localhost:8000
```

或用 docker-compose：

```bash
docker compose up -d
```

详细设计见 [`docs/03-roadmap.md` §1.5](docs/03-roadmap.md)，
验收测试见 [`docs/04-verification.md` §14](docs/04-verification.md)。

---

## 当前状态

🟡 **设计阶段**——4 份文档已落地（共 3700+ 行），代码尚未开始开发。

**已完成**：
- 📄 `docs/01-design.md` — 设计文档（591 行）
- 📄 `docs/02-tech-spec.md` — 技术规格（1577 行）
- 📄 `docs/03-roadmap.md` — 路线图 + 13 个 ADR（688 行）
- 📄 `docs/04-verification.md` — 验收标准（794 行）

**未完成**：
- ❌ 代码骨架（`src/hac/`）
- ❌ 单元测试（`tests/`）
- ❌ 端到端测试
- ❌ 任何 v0.1/v0.2/v0.3 的可运行代码

下一步：审完 4 份文档后按 `docs/03-roadmap.md` §1 优先级起代码骨架。
