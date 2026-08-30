# 04 · 验收标准（Verification v2）

> **版本**：v2（2026-08-30 重写）—— 修正 v1 与最终方案的矛盾（D9/A6），并补齐 8 项新功能的验收。
> **原则**：每个功能必须有可验证的成功标准；浏览器端到端走查是**最高优先级**验收，ffprobe 命令是交叉证据。

---

## 1. MVP 核心验收（浏览器用户视角）

### Test 1：上传进度（XHR）
- [ ] 拖入 50MB FLAC → 看到逐文件上传进度条**逐步增长**（非瞬间 100%）
- [ ] 完成后文件出现在 Files 列表（文件名/大小/时长）
- [ ] `data/uploads/` 出现文件

### Test 2：预设联动
- [ ] 选 "Opus 中 (48k)" → format=opus, codec=libopus, bitrate=48k, samplerate=24000, channels=1, 文件名后缀 `_opus_48k.opus`
- [ ] 手改 Bitrate → 预设下拉回 "— 自定义 —"

### Test 3：转码进度真实（⭐核心）
- [ ] Start 后任务卡出现，进度**连续单调递增**（非匀速假进度）
- [ ] 进度数字与进度条一致

### Test 4：输出参数正确（ffprobe 交叉验证）
```bash
ffprobe -v quiet -print_format json -show_format -show_streams out.opus \
  | jq '{codec:.streams[0].codec_name, br:.format.bit_rate, ar:.streams[0].sample_rate, ch:.streams[0].channels}'
```
| 档位 | codec | bit_rate | sr | ch |
|---|---|---|---|---|
| Opus 32/48/64k | opus | 目标±25%（VBR）* | 48000** | 1 |

\* 合成正弦波是 Opus VBR 的病态信号（实测 57.8k @ 48k 目标）；真人声贴住目标。VBR 下码率是目标值不是承诺值。
\** Ogg/Opus 容器按 RFC 7845 恒报 48000 Hz（24000 只是编码器内部处理率）——UI/文档声称的 24k 指编码率。

### Test 5：验证面板（新）
- [ ] 任务完成后卡片显示 codec / 码率 / 采样率 / 声道 / 体积节省 %
- [ ] 数值与上面 ffprobe 结果一致（±5%）

### Test 6：元数据写入 + 继承
- [ ] 填 Title/Artist → 输出有值
- [ ] 源文件有 Album、UI 留空 → 输出继承 Album
- [ ] mutagen 验证

### Test 7：下载
- [ ] 单文件下载文件名正确、可播放
- [ ] zip 下载：多选任务 → 1 个 zip，条目数正确，Content-Length 与磁盘一致

### Test 8：取消 / 重试 / 清空（新）
- [ ] 转码中点取消 → 5s 内退出，状态 cancelled，下载 404（.partial）
- [ ] **排队中**任务取消 → 状态直接 cancelled
- [ ] 失败任务点重试 → 回 queued → 正常跑完
- [ ] 清空已完成 → 面板只剩未完成
- [ ] 取消全部 → queued+running 全部 cancelled

### Test 9：批量 5 文件
- [ ] 5 任务逐个/并发执行，各自独立进度，全部完成

---

## 2. 新功能验收（v2 八项）

### Test F1：M4B 合并 ⭐
**操作**：上传 3 个章节（不同格式混合，如 mp3+m4a+flac），勾选"合并为一个 M4B"，填书名/作者，跑 AAC-LC 64k

```bash
ffprobe -v quiet -print_format json -show_chapters -show_format out.m4b | jq '.chapters | length'
ffprobe out.m4b 2>&1 | grep -i chapter
ffprobe -show_format out.m4b | grep -E "title|artist"
```
- [ ] 输出 .m4b，总时长 ≈ Σ 源时长（±2s）
- [ ] **章节数 = 3**，第 2 章 START == 第 1 章 END（时间无缝衔接）
- [ ] 章节标题 = 源 title tag（缺省用文件名）
- [ ] 全局 title/artist 正确
- [ ] 有封面时 ffprobe 显示 mjpeg video stream（attached_pic）；Apple Books 可显示
- [ ] 输出在 Apple Books /任意播放器章节列表按序显示

### Test F2：loudnorm
- [ ] 勾选"响度归一化"转码 → 用 `ffmpeg -af ebur128 -f null -` 测输出 integrated LUFS
- [ ] 目标 I=-20 LUFS，实测在 ±2 LU 内；不开 loudnorm 的对照组则无此约束
- [ ] 任务进度条仍正常（filter 链不影响进度解析）

### Test F3：本地目录导入
- [ ] `GET /api/library/roots` 返回白名单根
- [ ] 浏览 `HAC_LIBRARY_ROOTS` 内目录 → 列出 dirs/音频文件
- [ ] 勾选文件入队 → 与上传文件等效跑通转码
- [ ] 访问白名单外路径（含 `..` 穿越）→ **403**

### Test F4：HE-AAC 自动探测
- [ ] `GET /api/health` 的 encoders 数组反映真实 ffmpeg 能力
- [ ] 本机 ffmpeg 含 libfdk → 预设列表出现 HE-AAC 两档；否则隐藏并说明
- [ ] HE-AAC v1 输出：`ffprobe` codec_name=aac，且 profile 含 HE（或 SBR 特征），单声道

> ⚠️ **libfdk 获取的实测记录（2026-08-30）**：BtbN 最新静态构建**已不含 libfdk_aac**（下载 122MB 实测）；
> Ubuntu multiverse 的 `libfdk-aac2 2.0.2-3~ubuntu5` 亦缺少 SBR/PS 模块（HE 编码报 "Unable to set the AOT 5"）。
> 唯一可靠路径 = 源码编译上游 fdk-aac + ffmpeg，见 `scripts/build-he-ffmpeg.sh`（约 10 分钟）。

### Test F5：任务管理操作条
- [ ] cancel-all / clear-finished / retry 各按钮行为正确且 SSE 同步刷新

### Test F6：封面嵌入（single）
- [ ] 源 mp3 带 APIC 封面 → 转出 m4a/mp3 后封面仍在（mutagen 验证 covr/APIC）

---

## 3. API 验收（curl）

- A1 `POST /api/upload`（multipart 多文件）→ `{uploads:[{id,name,size,info}]}`
- A2 `POST /api/jobs`（single / merge 两种 body）→ `{job_id}`
- A3 `GET /api/jobs` 全量；A4 `curl -N /api/events` 收到 job.list/job.update/keepalive
- A5 `DELETE /api/jobs/{id}` ok；`POST /api/jobs/{id}/retry` ok
- A6 `GET /api/presets`：≥4 个 enabled；本机（有 libfdk 时）6 个全 enabled，每个含 settings/extension/suffix
- A7 `GET /api/probe/{id}` 返回 duration/channels/samplerate
- A8 `GET /api/health` 返回 encoders
- A9 `GET /api/download/zip?ids=...` 返回合法 zip
- A10 白名单外 `GET /api/library/list?path=/etc` → 403

---

## 4. 边界情况

- E1 假 FLAC（内容为文本）→ 上传即 400，不留文件
- E2 0 字节文件 → 400
- E3 超上限 → 413，磁盘无残留
- E4 同名两文件 → 不同 upload id，输出不互相覆盖
- E5 不支持格式（.wma 等）→ 任务 FAILED + 明确错误，不影响其他任务
- E6 merge 传 1 个文件 → 400；>500 → 400

---

## 5. 单元测试

`tests/` 覆盖 `02-tech-spec.md` §11 清单；**全部通过 = 阻塞解除**。回归必跑：参数构造、进度解析、章节累积、继承、白名单。

---

## 6. Docker 验收

- D1 `docker build` 成功，镜像 < 550MB
- D2 容器 healthy；`/api/health` 返回 encoders
- D3 volume 挂载：容器内转码 → 宿主 `./data/outputs/` 可见
- D4 compose up/down 正常
- D5 非 root：`docker exec ... whoami` = app
- **D6（修订，翻转 v1 的 D9）**：`docker exec ... ffmpeg -encoders | grep libfdk_aac` **应有输出**（BtbN 二进制内置）；`/api/presets` 含 HE-AAC 档
- D7 容器重启后 /app/data 文件保留

---

## 6. 主观听感（记录，不阻塞）

同段 5 分钟有声书：Opus 32/48/64 + AAC-LC 64 + HE-AAC 48 对照。48k Opus 为甜点；32k 可听出窄带；HE-AAC 48k 与 Opus 64k 相当。

---

## 7. 验收记录

- 日期：____　执行人：____
- 浏览器走查（§1+§2 全部）：☐ 通过
- 单元测试：☐ 全绿
- ffprobe 交叉验证：☐ 一致
