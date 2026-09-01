# 子项目 D · 网页播放/预览（A/B 对比）设计

> 状态：已批准（2026-09-01）
> 范围：Range 流式端点（产物/源/书库）、章节解析、mini 试听播放器、A/B 双面板同步对比
> 定位边界：验证工具（桌面快速验证转码效果），不做 MediaSession/锁屏/后台续播/移动端长听优化

## 1. 后端：流式端点

```
GET  /api/stream/job/{job_id}        转码产物（outputs/{job_id}/ 下唯一产物文件）
GET  /api/stream/upload/{upload_id}  已上传源文件（注册表校验）
GET  /api/stream/lib/{path*}         书库文件（复用 is_allowed 白名单）
GET  /api/stream/{kind}/{id}/info    {duration, codec, bitrate, sample_rate, channels, chapters: [{start, end, title}]}
```

- 自定义 Range 响应类（Starlette FileResponse 不支持 Range）：
  - 解析 `Range: bytes=start-end` / `bytes=start-` / `bytes=-suffix`；非法/越界 → 416
  - 命中 → 206 + `Content-Range` + `Accept-Ranges: bytes`；文件 seek 后按 64KB 分块 yield
  - 无 Range 头 → 200 全量
- MIME 按扩展名映射：m4a/m4b→audio/mp4，mp3→audio/mpeg，ogg/opus→audio/ogg，flac→audio/flac，wav→audio/wav；未知扩展→application/octet-stream（浏览器退回下载）
- 章节：`ffprobe -show_chapters`（复用 probe 基建），仅 M4B 有，其它容器返回空数组
- 安全校验与现有 API 一致：upload id 必须在注册表、lib 路径必须在白名单、job 必须存在且有产物；本地/LAN 工具无鉴权（既有边界）

## 2. 前端：播放器（原生 `<audio>` + 自绘控制，无第三方库）

### 2.1 Mini 试听（单面板）

- 入口：uploads 表行 ▶、书库表行 ▶、任务卡片「▶ 试听」
- 页面底部固定 mini 播放条（替代性出现，全局仅一个播放器实例）：播放/暂停、进度条 seek、时间、0.5–2× 倍速、音量
- 切换播放源即替换 `src`；`data-stream-url` 属性驱动

### 2.2 A/B 双面板对比（核心）

- 入口：任务卡片「A/B 对比」（有产物且源仍存在时显示）
- 抽屉内左右双面板：左 = 源（upload/lib），右 = 产物
- **同步引擎**：以「最近操作者」为准——
  - 监听两侧 `play/pause/seeking/ratechange` 事件：事件发起侧为操作者，另一侧镜像同一时间点与状态；`syncing` 标志位防事件回环
  - 播放中每秒对齐一次漂移（差值 > 0.3s 才校正，避免抖动）
- 章节跳转：产物有章节时显示章节 chips（含时间），点击双侧 seek
- 键盘：`Space` 播放/暂停、`←/→` 快退/快进 5s（抽屉内焦点时生效，不干扰全局快捷场景）
- 音量：双侧独立（源与产物响度差异本身是 A/B 感知对象）

### 2.3 边界明确不做

MediaSession/锁屏、后台续播、音频焦点、移动端长听优化。info/chapters 端点与播放器逻辑已解耦，将来升级一等公民只补前端。

## 3. UX 候选落位

- 「转码前后 A/B 试听打通」✓ 本子项目落地
- 剩余候选（通知/全局进度/失败诊断/批量操作）在子项目 E 统一评估

## 4. 测试

**单元**（pytest + httpx）：
- Range 解析矩阵：`bytes=0-99`、`bytes=100-`、`bytes=-500`、越界、非法 → 206/416 断言 + Content-Range 头
- 章节 ffprobe 解析（fixture m4b 带章节）
- 安全校验：不存在 upload id / 白名单外 lib 路径 / 无产物 job → 404/403
- info 端点字段

**E2E**：
- 产物试听：mini 播放器 canplay + duration ≈ ffprobe 时长
- A/B：seek 产物侧 → 双侧 currentTime 差 < 0.5s；章节 chip 点击跳转
- 书库行试听；无章节产物不渲染章节区
- 音量独立性

## 5. 风险与边界

- 大文件：seek 后分块 yield，不整读内存
- 浏览器解码：opus/ogg/flac/wav 现代浏览器全支持；不支持的容器退回下载（Content-Disposition 由前端判断）
- 双音频元素自动播放策略：浏览器要求用户手势后才能出声——所有播放入口都是点击触发，天然满足
