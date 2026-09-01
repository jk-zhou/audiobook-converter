# 08 · Unraid 7.x 部署指南

> 适用 Unraid 7.x（含 7.3.2），使用内置 **Compose Manager**（Docker 页的 Compose 标签）。
> 5 分钟部署：粘贴 compose → 改两处路径 → Up。

## 0. 前置说明

- 镜像发布在 GHCR（`ghcr.io/<owner>/audiobook-converter`），由 GitHub Actions 在 push 到 main 时自动构建；无需在 NAS 上构建
- **nonfree 声明**：镜像内置自编译的 libfdk_aac（FFmpeg `--enable-nonfree`），仅限自用部署，不可再分发（linuxserver.io 同样做法）
- 单用户本地工具，无鉴权——仅在可信局域网暴露端口

## 1. 部署步骤

1. Docker 页 → **Compose** → **Add New Stack**，命名 `audiobook-converter`
2. 编辑 Stack 的 compose，粘贴仓库根目录 `docker-compose.yml` 内容，改两处：
   - `image:` 里 `OWNER` 换成实际 GitHub 用户名/组织
   - `volumes:` 里两行路径：
     - `/mnt/user/appdata/audiobook-converter` → 你的 appdata share（不存在会在启动时创建）
     - `/mnt/user/audiobooks` → 你的有声书库 share（只读挂载）
   - 可选：`TZ` 改成你所在时区
3. **Compose Up** → 等待镜像拉取并启动
4. 浏览器访问 `http://<unraid-ip>:8000`；右上角健康徽章应显示 `ffmpeg ✓ · N 编码器`——**HE-AAC 预设可见**说明 libfdk 生效

## 2. 数据落点（都在 appdata share，备份即拷贝）

| 路径 | 内容 |
|---|---|
| `appdata/audiobook-converter/uploads/` | 上传的源文件（含注册表，重启自动恢复） |
| `appdata/audiobook-converter/outputs/` | 转码产物（下载源） |
| `appdata/audiobook-converter/library/` | 默认书库（不放书也可用 /books 只读挂载） |
| `appdata/audiobook-converter/hac.db` | SQLite：设置/会话/任务历史（已落地，重启不丢） |
| `appdata/audiobook-converter/logs/` | 运行日志（每日轮转 30 天） |

## 3. 权限说明（PUID/PGID）

- 容器默认以 `PUID=99 / PGID=100`（Unraid 的 `nobody:users`）运行，与 share 默认属主一致，通常**零配置**
- 你的 appdata share 属主不是 99:100 时，容器启动会自动 `chown` 一次 `/app/data`（属主已匹配则跳过，不碰只读的 `/books`）
- 仍遇 `Permission denied`：Unraid 终端执行 `newperms /mnt/user/appdata/audiobook-converter`，或核对 compose 里 PUID/PGID 与 share 实际属主（`ls -ln`）
- 用其它 Linux 主机（非 Unraid）：compose 里把 PUID/PGID 改成 `id -u`/`id -g` 对应值

## 4. 升级 / 回滚 / 卸载

- **升级**：Compose 页 → Check for Updates / Recreate（拉新镜像，数据不受影响）
- **回滚**：把 `image:` 的 `latest` 改成具体版本 tag（如 `:v0.4.0`）后 Up
- **卸载**：Compose Down；数据保留在 appdata share，删栈不删数据

## 5. GHCR 包首次发布后的可见性（维护者一次性操作）

1. GitHub 仓库 → Packages → `audiobook-converter` → Package settings
2. Change visibility → **Public**（否则 Unraid 拉取需要登录）

## 6. 常见问题

- **健康徽章显示 `ffmpeg ✗`**：`docker logs audiobook-converter` 看启动错误；确认 `/app/data` 挂载存在
- **HE-AAC 预设仍隐藏**：`docker exec audiobook-converter ffmpeg -hide_banner -encoders | grep libfdk`，无输出说明拉到旧镜像（升级）
- **书库浏览为空**：检查 `HAC_LIBRARY_ROOTS` 与挂载点是否对应，且 share 内确有音频文件
- **端口被占**：compose 里 `"8000:8000"` 左侧改任意空闲端口
