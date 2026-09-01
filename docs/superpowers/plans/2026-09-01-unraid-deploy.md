# 子项目 A · Unraid 部署 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dockerfile 多阶段重构（内置 libfdk_aac 的 ffmpeg）、PUID/PGID entrypoint、compose 面向 Unraid 7.3.2 重写、GHCR 发布 CI、部署文档；本地 Docker 完整验证。

**Architecture:** builder 阶段从源码编译 fdk-aac + ffmpeg（--enable-nonfree --enable-libfdk-aac），runtime 阶段 python:3.11-slim 只装 curl/gosu + 编译产物 + 应用；root 启动时 entrypoint 按 PUID/PGID（默认 99/100）建用户、按需 chown /app/data、gosu 降权 exec uvicorn。

**Tech Stack:** Docker 多阶段、debian bookworm、shell entrypoint、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-09-01-unraid-deploy-design.md`

**Worktree:** `/home/clawbot/workspace/audiobook-converter-deploy`，分支 `feat/unraid-deploy`

## Global Constraints

- ffmpeg configure：`--enable-gpl --enable-nonfree --enable-libfdk-aac --disable-doc --disable-debug`（不 disable-everything，保持全格式覆盖承诺）
- entrypoint 从不 chown `/books`；chown 仅在 `/app/data` 属主不匹配时执行
- 镜像内不预建固定 uid 用户；PUID=0 或非 root 启动时跳过降权
- HEALTHCHECK/EXPOSE 8000 保持不变；`/api/health` 必须报告 libfdk_aac
- ffmpeg 用稳定 release tarball（7.1.x）+ fdk-aac 2.0.2，不用 git master（可复现构建）
- ffmpeg 源码编译耗时约 5-10 分钟，超出单命令超时限制 → 后台构建 + 轮询

---

### Task 1: docker-entrypoint.sh

**Files:**
- Create: `docker-entrypoint.sh`（repo root，与 Dockerfile 同级）

**Interfaces:**
- Produces: 容器入口脚本。行为：非 root 或 PUID 未设/为 0 → 直接 exec uvicorn；root 且 PUID 有效 → getent 建组/用户（已存在则复用）→ stat 检查 `/app/data` 属主不匹配才 `chown -R` → `exec gosu $PUID:$PGID uvicorn ...`

- [ ] **Step 1:** 写 `docker-entrypoint.sh`（spec §3 逻辑，debian 语法：getent/groupadd/useradd）

```sh
#!/bin/sh
set -e

PUID="${PUID:-}"
PGID="${PGID:-}"

run_uvicorn() { exec uvicorn hac.main:app --host 0.0.0.0 --port 8000; }

if [ "$(id -u)" = "0" ] && [ -n "$PUID" ] && [ "$PUID" != "0" ]; then
  PGID="${PGID:-$PUID}"
  getent group "$PGID" >/dev/null || groupadd -g "$PGID" hac
  getent passwd "$PUID" >/dev/null || useradd -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin hac
  if [ -d /app/data ] && [ "$(stat -c %u /app/data)" != "$PUID" ]; then
    chown -R "$PUID:$PGID" /app/data
  fi
  exec gosu "$PUID:$PGID" uvicorn hac.main:app --host 0.0.0.0 --port 8000
fi

run_uvicorn
```

- [ ] **Step 2:** `chmod +x docker-entrypoint.sh && sh -n docker-entrypoint.sh`（语法检查）；如装了 shellcheck 则跑
- [ ] **Step 3:** 逻辑冒烟（本地 sh 模拟 PUID 分支无法在宿主测，留待 Task 4 容器内验证）
- [ ] **Step 4:** Commit `feat(deploy): PUID/PGID entrypoint`

### Task 2: Dockerfile 多阶段重写

**Files:**
- Modify: `Dockerfile`（全量重写）
- Modify: `.dockerignore`（若需排除 docs/tests）

**Interfaces:**
- Consumes: `docker-entrypoint.sh`（Task 1）
- Produces: 本地镜像 `audiobook-converter:dev`，含 `/usr/local/bin/ffmpeg`（libfdk_aac）、gosu、entrypoint

- [ ] **Step 1:** 重写 Dockerfile：

```dockerfile
# ---- Stage 1: build fdk-aac + ffmpeg (nonfree: libfdk_aac) ----
FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential pkg-config yasm nasm autoconf automake libtool \
      ca-certificates curl xz-utils git && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# fdk-aac 2.0.2
RUN curl -fsSL https://github.com/mstorsjo/fdk-aac/archive/refs/tags/v2.0.2.tar.gz | tar xz && \
    cd fdk-aac-2.0.2 && ./autogen.sh && ./configure --prefix=/usr/local --enable-static --disable-shared && \
    make -j"$(nproc)" && make install
# ffmpeg 7.1.1 (stable release)
RUN curl -fsSL https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz | tar xJ && \
    cd ffmpeg-7.1.1 && ./configure --prefix=/usr/local \
      --enable-gpl --enable-nonfree --enable-libfdk-aac \
      --disable-doc --disable-debug && \
    make -j"$(nproc)" && make install

# ---- Stage 2: runtime ----
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl gosu ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=builder /usr/local/bin/ffprobe /usr/local/bin/ffprobe
WORKDIR /app
COPY --chown=root:root pyproject.toml ./
COPY --chown=root:root src/ ./src/
RUN pip install --no-cache-dir .
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENV HAC_DATA_DIR=/app/data HAC_MAX_CONCURRENT=2 PUID= PGID=
RUN mkdir -p /app/data/uploads /app/data/work /app/data/outputs /app/data/library
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
```

注意：`ENV PUID= PGID=` 留空 = entrypoint 走非降权分支（docker run 不传时 root 直跑 uvicorn；compose 显式传 99/100）。旧镜像的 `useradd -u 1000 app` 删除。

- [ ] **Step 2:** 后台构建（超时长）：`nohup docker build -t audiobook-converter:dev . > /tmp/opencode/docker-build.log 2>&1 &`，轮询直到完成（ffmpeg 编译 5-10 分钟；层缓存后增量快）
- [ ] **Step 3:** 验证镜像：`docker run --rm audiobook-converter:dev ffmpeg -hide_banner -encoders | grep libfdk_aac`；`ffprobe -version`
- [ ] **Step 4:** Commit `feat(deploy): 多阶段 Dockerfile，镜像内置 libfdk ffmpeg`

### Task 3: compose 面向 Unraid 重写

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1:** 按 spec §4 重写（image: ghcr.io/OWNER/audiobook-converter:latest，注释 build: 备选；PUID=99/PGID=100；TZ；HAC_LIBRARY_ROOTS=/books:/app/data/library；卷：appdata + /mnt/user/audiobooks:ro）。OWNER 占位注释说明改成自己的 GitHub 用户名/组织
- [ ] **Step 2:** `docker compose config` 校验语法；本地功能冒烟：临时 override 用 build 出的镜像起容器（不挂 Unraid 路径，用本地 data/）
- [ ] **Step 3:** Commit `feat(deploy): compose 面向 Unraid 重写`

### Task 4: 容器内完整验证（PUID/权限/健康/HE-AAC）

**Files:** 无新文件（验证 Task 1-3）

- [ ] **Step 1:** 模拟 Unraid 属主：`mkdir -p /tmp/opencode/unraid-appdata && sudo chown -R 99:100 /tmp/opencode/unraid-appdata`（无 sudo 则用 docker 容器 chown：`docker run --rm -v /tmp/opencode/unraid-appdata:/x alpine chown -R 99:100 /x`）
- [ ] **Step 2:** 起容器：`docker run -d --name hac-test -p 18000:8000 -e PUID=99 -e PGID=100 -v /tmp/opencode/unraid-appdata:/app/data audiobook-converter:dev`
- [ ] **Step 3:** 断言：`docker exec hac-test id` 输出 uid=99；容器内进程 `ps` 为 uvicorn 且用户 99；`curl -f localhost:18000/api/health` 且 JSON encoders 含 libfdk_aac；`/tmp/opencode/unraid-appdata/uploads` 出现目录且属主 99:100
- [ ] **Step 4:** 上传一个测试音频（curl POST /api/upload）→ 产物写入 appdata 卷 → 宿主可读
- [ ] **Step 5:** 清理 `docker rm -f hac-test`；Commit（若有 fix）

### Task 5: GitHub Actions 发布工作流

**Files:**
- Create: `.github/workflows/docker.yml`

- [ ] **Step 1:** workflow：push main → build&push `ghcr.io/${{ github.repository }}:latest` + sha tag；tag `v*` → 版本 tag；`docker/setup-buildx-action` + `cache-from/to: type=gha`；仅 linux/amd64；permissions `packages: write`
- [ ] **Step 2:** 本地 `docker buildx build --platform linux/amd64 .` 干跑（CI 外验证 buildx 语法可用；完整 CI 触发需 push 后观察）
- [ ] **Step 3:** Commit `ci(docker): GHCR 自动发布（amd64，gha 缓存）`

### Task 6: 部署文档 + 收尾

**Files:**
- Create: `docs/08-unraid-deploy.md`

- [ ] **Step 1:** 按 spec §6 写文档（Compose Manager 步骤、路径/PUID 定制、健康验证、权限排查 newperms、nonfree 声明、升级/卸载、GHCR 包 public 化一次性步骤）
- [ ] **Step 2:** README Docker 段落加 Unraid 链接
- [ ] **Step 3:** `uv run pytest -q`（确保无回归）+ 全量 E2E（改动仅部署层，跑 part3 冒烟即可，但按基线跑全量）
- [ ] **Step 4:** Commit `docs(deploy): Unraid 部署指南`；汇总验收清单（spec §7），标注哪些项本地已验、哪些留待 Unraid 真机

## Self-Review

- Spec §2-6 全覆盖：Task1=§3，Task2=§2，Task3=§4，Task5=§5，Task6=§6；§7 验收在 Task4+Task6 ✓
- 无占位符；entrypoint/Dockerfile/compose 均给出完整代码 ✓
- 契约一致：entrypoint 文件名、镜像 tag、环境变量名跨任务一致 ✓
