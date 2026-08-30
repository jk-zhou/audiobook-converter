# Audiobook Converter

> 简易版网页 foobar2000 —— 一个支持多文件批量转码、元数据编辑、后台任务管理的 Web App。
> 主场景：有声书批量压成 Opus/AAC（32-64 kbps），单声道、24 kHz、体积砍 80%+。

---

## 它能做什么

> ✅ **v0.2 已实现**（分支 `feat/mvp-improved`）：MVP + 8 项改进全部可用，详见 `docs/02-tech-spec.md`。

### 本轮实现（MVP + 8 项改进）
- ✅ 上传多个音频文件（mp3 / m4a / m4b / aac / flac / ogg / opus / wav…），XHR 逐文件上传进度
- ✅ 6 个预设：Opus 32/48/64k、AAC-LC 64k、HE-AAC v1 48k / v2 32k（libfdk 存在时自动启用）
- ✅ 单文件转码 + 元数据编辑（未填字段自动继承源文件）
- ✅ **合并为一个 M4B**：内嵌章节（时间无缝衔接）+ 书名/作者 + 封面（上传或自动提取内嵌）
- ✅ **loudnorm 响度归一化**开关（目标 -20 LUFS）
- ✅ **本地目录导入**（白名单根目录，零上传）
- ✅ SSE 实时进度 + **验证面板**（ffprobe 回读 codec/码率/节省 %）
- ✅ 单文件 / **zip 批量**下载、失败重试、取消全部、清空已完成

### v0.2 (元数据批处理) 📋 归档草案
- 📋 模板语法 / AlbumArtist 三模式 / 反向重命名 → 规格草案见 `docs/05-v0.2-spec-draft.md`，待实施

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

## 部署方式

### 方式 1：一键脚本（推荐）

```bash
./run.sh                                 # 启动，默认 0.0.0.0，局域网可访问
./run.sh help                            # 查看全部命令/选项/环境变量
./run.sh start -H 127.0.0.1              # 仅本机可访问
./run.sh doctor                          # 环境体检
./run.sh stop                            # 停止
```

### 方式 2：手动 Python（开发调试用）

```bash
uv venv && uv pip install -e ".[dev]"
uvicorn hac.main:app --host 0.0.0.0 --port 8000
```

### 方式 3：Docker 单容器（NAS/服务器推荐）

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

🟢 **v0.2 已实现**（feat/mvp-improved 分支）：FastAPI 后端 + Vanilla JS 前端 + 测试 + Docker。

**文档**：
- 📄 `docs/02-tech-spec.md` — 技术规格 v2（修正 v1 的 9 处 bug）
- 📄 `docs/04-verification.md` — 验收标准 v2（含 8 项新功能硬性验收）
- 📄 `docs/05-v0.2-spec-draft.md` — v0.2 模板批处理规格草案（归档）

**运行**（一键脚本，含帮助菜单）：
```bash
./run.sh                # 最简启动，默认 0.0.0.0 局域网可访问；本机访问 http://127.0.0.1:8000
./run.sh help           # 全部命令与选项
./run.sh doctor         # 环境体检（依赖/ffmpeg/预设可用性）
./run.sh stop           # 停止服务
```
常用示例：
```bash
./run.sh start -p 9000                    # 指定端口，局域网可访问
./run.sh start -H 127.0.0.1               # 仅本机可访问
./run.sh start -l /mnt/nas/audiobooks     # 挂载 NAS 书库目录
./run.sh he                               # 源码编译 libfdk，启用 HE-AAC 预设
```
> 首次运行会自动创建虚拟环境并安装依赖；ffmpeg 缺失时 `./run.sh setup` 自动下载。
> 应用启动时自动探测编码器：有 libfdk_aac → 6 预设全开；无 → HE-AAC 两档自动隐藏，其余照常。

下一步：按 `docs/04-verification.md` 在浏览器逐项验收。
