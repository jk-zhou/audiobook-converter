# 06 · 项目进度与交接文档（Handoff）

> **最后更新**：2026-08-31
> **用途**：给接手本项目的开发者 / agent 的单页速览。读这页 + `README.md` 即可上手。

---

## 1. 项目当前状态（一句话）

**v0.2 已实现并验证**：网页版有声书批量转码器（FastAPI + FFmpeg + Vanilla JS），
支持 Opus/AAC/HE-AAC 预设、M4B 章节合并、loudnorm、书库导入、WYSIWYG 排序、
会话保持、源文件手动管理。pytest 60/60 · 浏览器 E2E 74/74 全绿。

## 2. 版本脉络（分支与关键 commit）

```
main ← feat/mvp-improved（已合并，快进）
  111b09a docs-only 起点（4 份设计文档，零代码）
  7c195cb docs v2 重写（修正 v1 spec 的 9 处 bug；v0.2 规格归档到 05）
  7f0a8c4 后端实现（13 模块，39 tests）
  52577d7 前端三栏 UI
  6a769f8 Docker 三件套
  1155636 merge 强制 m4b / 串行上传保序 / stats_period 进度平滑
  b4b9135 build-he-ffmpeg.sh（libfdk 实测结论）
  b789ad7 默认监听 0.0.0.0
  6781aa0 run.sh 一键启动 + doctor
  b24fcb4 fd 限限提升 / WYSIWYG 排序 / 标题来源 / track 回填 / composer
  0863fe1 分块两阶段合并 / 元数据列 / 会话保持 / 图标 / 滚动日志
  d2ecdf4 id 前缀泄漏修复 / 书库 UI / Part4 多任务场景
  dd1d41a E2E 套件入库（tests/e2e + run-e2e.sh）
  be40b4d 源文件手动管理模型（已上传 tab / delsrc / 每任务上限）
  f4833d4 验收状态 + 未完成事项
```

## 3. 已实现功能清单（简版）

| 功能 | 关键实现位置 |
|---|---|
| 上传（XHR 逐文件进度、文件夹拖拽递归） | `static/app.js uploadFiles/collectFilesFromDrop` |
| 6 预设（Opus 32/48/64k、AAC-LC 64k、HE-AAC v1/v2 自动探测启用） | `presets.py` + `encoders.py` |
| 单文件转码 + 元数据编辑（继承/文件名/pattern 标题、track 回填） | `transcoder.py` + `metadata.py` |
| M4B 合并（章节无缝、书名/作者/演播者/封面；>500 输入自动分块两阶段） | `merger.py` |
| loudnorm（-20 LUFS 实测 ±0） | `transcoder.LOUDNORM` |
| 书库导入（白名单根、UI 不暴露服务器路径） | `library.py` + `/api/library/*` |
| SSE 实时进度（20Hz 输出 + 0.5% 节流）+ 验证面板（ffprobe 回读+节省%） | `events.py` + `jobs.py` |
| WYSIWYG 排序（列头正反序/拖拽/自然排序/track/标题/大小/时间） | `app.js sortUploads` |
| 会话保持（工作集 + 全部设置 localStorage；刷新零丢失） | `app.js saveSession/fetchUploads` |
| 源文件手动管理（已上传 tab 🔒只读/⤵加回/删除；任务卡片 delsrc） | `uploads.py` + `/api/uploads/*` |
| zip 批量下载 / 重试 / 取消全部 / 清空已完成 | `main.py` |
| 滚动日志（data/logs 每天轮转 30 天）+ 4xx/5xx 访问日志 | `main.setup_logging` |
| Docker 单镜像 + compose + .dockerignore | 根目录三件套 |
| 一键脚本（start/stop/doctor/setup/he） | `run.sh` |

## 4. 验证状态（全部实测过）

- **pytest 60/60**：`tests/`（参数构造/进度解析/章节累积/清理保护/元数据/白名单/任务管理）
- **浏览器 E2E 74/74**：`tests/e2e/`（part1 转码 12 · part2 合并与新功能 26 · part3 UI/会话 19 · part4 多任务 17）
  - 运行：`./scripts/run-e2e.sh`（隔离数据目录、每部分自动重启服务、截图存 `data/e2e-shots/`）
- **大规模合并实测**：
  - 服务 fd 软限压到 200 时合并 300 输入成功（无修复时 EMFILE 复现）
  - 1500 合成文件分块合并：1500 章节无缝衔接
  - **258 个真实有声书文件**（《诛仙》北冥演播）分块合并：258 章节、断点 0、
    块边界解码 OK、书名/作者/演播者正确
- **loudnorm 实测**：输出 integrated LUFS = -20.0（目标 ±0）

## 5. ⚠️ 关键技术决策与已踩过的坑（接手者必读）

1. **fd 限制必须在父进程提升**：uvloop 的子进程实现**忽略 preexec_fn**。
   合并数千输入时每路占一个 fd；`main.py lifespan` 里 `_raise_nofile()` 把软限提到硬限。
   ⚠️ `bash ulimit -n 200` 默认**同时**压软硬限；测试环境要用 `ulimit -S -n`。
2. **HE-AAC/libfdk 的获取路径（实测结论）**：
   - BtbN 最新静态构建**已不含** libfdk_aac（2026-08 实测）
   - Ubuntu multiverse 的 `libfdk-aac2` **缺 SBR/PS 模块**（报 "Unable to set the AOT 5"）
   - 唯一可靠路径 = 源码编译上游 fdk-aac + ffmpeg → `scripts/build-he-ffmpeg.sh`（约 10 分钟）
   - 无 libfdk 时应用自动隐藏 HE 预设，其余功能不受影响
3. **大规模合并 = 分块两阶段**（`HAC_MERGE_CHUNK`，默认 500）：
   2000+ 输入的单遍 ffmpeg RSS ~6GB 会在小内存机器触发系统级 OOM 连坐整个应用。
   phase1 每块编码一次；phase2 concat demuxer **流复制**拼合 + 章节按**实测块时长**对齐。
4. **Opus 容器恒报 48000 Hz**（RFC 7845）；预设的 24000 指编码器内部处理率。
   ffprobe 显示 48k 不是 bug。
5. **VBR 码率是目标不是承诺**：合成正弦波上 Opus 过冲（57.8k@48k），真人声贴住目标。
   测试容差 ±25%（正弦信号）。
6. **libfdk SBR 上报 quirk**：HE 输出 ffprobe 恒报 `channels=2`（即使请求单声道核）。
7. **上传必须串行**：并发上传打乱 `state.uploads` 顺序 → 合并章节乱序（已修，勿回退）。
8. **ffmpeg `-stats_period 0.05`**：默认 0.5s 进度粒度在高速编码下近乎无进度；
   20Hz 输出 + 前端 0.5% 节流 = 平滑进度条。
9. **章节名净化**：磁盘文件名带 `{upload_id}_` 前缀，一切用户可见名
   （章节名/输出名/任务卡片源清单）必须走 `uploads.display_stem()`。
10. **前端会话恢复必须"合并"而非"替换"**：`restoreWorkingSet`/`fetchUploads`
    晚到的快照绝不能覆盖用户已拖入的文件（曾导致点击开始时 sources 为空的静默失败）。
11. **E2E 基建要点**：
    - runner 每部分**重启服务 + 换隔离数据目录**（mktemp），不碰真实 data/
    - /tmp 是 3.7G tmpfs：满了会让 chromium SIGTRAP；runner 自动设 `TMPDIR=repo/data/e2e-tmp`
    - 测试/脚本里避免 `pkill -f "uvicorn"` 字面量（会自匹配杀掉调用者）；
      用 `pkill -9 -f "[u]vicorn"` 方括号技巧
12. **部署默认 0.0.0.0**（局域网可访问）；单用户无鉴权，不可信网络请 `-H 127.0.0.1`。

## 6. 未完成事项（按优先级）

| # | 事项 | 说明 |
|---|------|------|
| 1 | Docker 验收 D1-D7 | 三件套已交付未实测（`docs/04-verification.md` §6）；需在有 docker 的机器跑 |
| 2 | NAS/远程真机部署 | 局域网多设备访问、防火墙端口、Unraid 只读挂载 + HAC_LIBRARY_ROOTS |
| 3 | Apple Books 真机回归 | 294 章《诛仙》合并产物导入 Books 实测章节导航/封面/续播（最终用户视角） |
| 4 | ~~v0.2 模板批处理~~ | ✅ 已落地（`feat/template-batch`）：模板引擎（parse/render/match）、TrackNum 零填充+track/total、uploads/outputs 批量重命名+mutagen 写 tag、嵌入式抽屉 UI+实时预览；详见 `docs/superpowers/specs/2026-09-01-template-batch-design.md` |
| 5 | ~~v0.3 播放器~~ | ✅ 已落地：SQLite 持久化（feat/persistence）+ 网页播放/A-B 对比（feat/web-playback，Range 流式/mini 试听/双面板同步/章节跳转）；MediaSession 与移动端长听优化仍为明确不做 |
| 6 | 任务队列可观测性 | 失败任务重试时若源已删除会 404（引导用户去已上传 tab）；可加更友好提示 |

明确**不做**（设计边界，见 roadmap §4）：多用户/鉴权、云端存储、实时波形、多设备同步。

## 7. 快速上手（下一个 agent 的第一步）

```bash
cd <repo>                       # 本仓库
./run.sh setup                  # 建 venv + 装依赖 +（缺 ffmpeg 时）下载静态构建
./run.sh doctor                 # 体检（看预设可用性/白名单/数据目录）
./run.sh                        # 起服务 → http://127.0.0.1:8000
./scripts/run-e2e.sh            # 74 项浏览器 E2E（需 playwright chromium）
uv run pytest                   # 60 项单元测试
./run.sh he                     # （可选）编译 libfdk 启用 HE-AAC 预设
```

环境变量速查：`HAC_PORT/HAC_HOST/HAC_LIBRARY_ROOTS/HAC_MAX_CONCURRENT/
HAC_MAX_UPLOAD_MB/HAC_MAX_MERGE_FILES/HAC_MAX_MERGE_GB/HAC_MERGE_CHUNK/HAC_DATA_DIR`。
