# 子项目 A · Unraid 7.3.2 部署设计

> 状态：已批准（2026-09-01）
> 范围：Dockerfile 多阶段重构（内置 libfdk）、PUID/PGID 权限方案、compose 面向 Unraid 重写、GHCR 发布 CI、部署文档
> 不做：CA 应用模板、arm64 架构、镜像瘦身优化

## 1. 背景与目标

现有 Docker 三件套存在三个 Unraid 落地问题：

1. **权限**：镜像固定以 `app`(uid 1000) 运行，Unraid share 默认属主 `nobody:users`(99:100)，写 `/app/data` 必然 Permission denied
2. **HE-AAC 缺失**：BtbN 静态 ffmpeg 不含 libfdk_aac，两个 HE-AAC 预设在容器里永远隐藏
3. **分发**：镜像只本地构建，没有 pull-and-run 路径

目标：Unraid 7.3.2 用户通过内置 Compose Manager 在 5 分钟内完成部署，HE-AAC 开箱即用，升级只拉镜像。

## 2. Dockerfile 重构（多阶段）

```
Stage 1 — builder (debian:bookworm-slim)
  apt: build-essential yasm nasm pkg-config autoconf libtool
  git clone --depth 1 https://github.com/mstorsjo/fdk-aac && autoreconf && ./configure --prefix=/usr/local --enable-shared=no && make -j && make install
  ffmpeg 6.x/7.x 源码: ./configure --enable-gpl --enable-nonfree --enable-libfdk-aac
                       --disable-doc --disable-debug --disable-autodetect
                       （显式开启所需协议/解复用器，控制体积与编译时间）
  make -j && make install

Stage 2 — runtime (python:3.11-slim)
  apt: curl ca-certificates gosu
  COPY --from=builder /usr/local/bin/ffmpeg /usr/local/bin/ffprobe
  useradd 不再预建 uid 1000 用户（用户由 entrypoint 动态创建）
  COPY src/ pyproject.toml → pip install .
  COPY docker-entrypoint.sh → ENTRYPOINT ["/app/docker-entrypoint.sh"]
  HEALTHCHECK / EXPOSE 8000 保持不变
```

要点：
- `--enable-nonfree` + `--enable-libfdk-aac`：产物不可再分发（FFmpeg nonfree 定义），镜像仅限自用；文档显式声明（linuxserver.io 同样做法）
- ffmpeg configure 用 `--disable-autodetect` + 显式白名单，编译时间约 3-5 分钟，最终镜像体积增量约 15-20MB
- apt 的 ffmpeg 依赖包不再安装（runtime 只用编译产物），删除 BtbN 下载逻辑

## 3. Entrypoint 权限逻辑（PUID/PGID）

`docker-entrypoint.sh`（shell，无 s6）：

```sh
if [ "$(id -u)" = "0" ] && [ -n "$PUID" ] && [ "$PUID" != "0" ]; then
  # 创建组/用户（若 gid/uid 已被占用则复用；debian 基础镜像用 groupadd/useradd）
  getent group "$PGID" >/dev/null || groupadd -g "$PGID" hac
  getent passwd "$PUID" >/dev/null || useradd -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin hac
  # 仅当属主不匹配才递归 chown（大目录防重复全量 chown），从不触碰 /books
  for d in /app/data; do
    [ -d "$d" ] && [ "$(stat -c %u "$d")" != "$PUID" ] && chown -R "$PUID:$PGID" "$d"
  done
  exec gosu "$PUID:$PGID" uvicorn hac.main:app --host 0.0.0.0 --port 8000
fi
exec uvicorn hac.main:app --host 0.0.0.0 --port 8000
```

- 默认 `PUID=99 PGID=100`（compose 里显式声明）
- 容器以非 root 运行（`user:` 指令）时直接走最后一行 exec——本地开发/其它 NAS 灵活性保留
- `/books` 挂载只读，永不 chown

## 4. docker-compose.yml（面向 Unraid）

```yaml
services:
  audiobook-converter:
    image: ghcr.io/OWNER/audiobook-converter:latest
    # 备选：不用发布镜像时取消注释，从本地仓库构建
    # build: .
    container_name: audiobook-converter
    ports:
      - "8000:8000"
    environment:
      - PUID=99            # Unraid nobody
      - PGID=100           # Unraid users
      - TZ=Asia/Shanghai
      - HAC_MAX_CONCURRENT=2
      # 书库白名单（冒号分隔，容器内路径）
      - HAC_LIBRARY_ROOTS=/books:/app/data/library
    volumes:
      - /mnt/user/appdata/audiobook-converter:/app/data
      - /mnt/user/audiobooks:/books:ro
    restart: unless-stopped
```

- OWNER 在 CI 与 compose 中使用同一个 GitHub repo 路径
- Compose Manager 粘贴即用；`build:` 注释行保留本地构建路径

## 5. CI（.github/workflows/docker.yml）

- 触发：push 到 `main`（latest + sha tag）；push tag `v*`（版本 tag）
- `docker/build-push-action@v6` + `docker/login-action@v3`（GITHUB_TOKEN 自带 packages:write）
- 仅 `linux/amd64`（Unraid 为 x86_64；arm64 YAGNI）
- 层缓存（`cache-from/to: type=gha`）保证增量构建分钟级
- 首次发布后：GitHub 包页面手动把 visibility 设为 public（一次性）

## 6. 文档（docs/08-unraid-deploy.md）

1. Compose Manager 步骤：Docker → Compose → Add New Stack → 粘贴 compose.yml → 编辑 appdata/audiobooks 路径与 TZ → Up
2. 首次访问 `http://<unraid-ip>:8000`；健康徽章应显示 `ffmpeg ✓ · N 编码器`（libfdk 生效则 HE-AAC 预设可见）
3. 权限排查：`Permission denied` 时在 Unraid 终端 `newperms /mnt/user/appdata/audiobook-converter`；或核对 PUID/PGID
4. nonfree 声明：镜像含 libfdk_aac（nonfree），仅限自用部署
5. 升级：Compose → Check for Updates / Recreate（拉新镜像）
6. 卸载：Down 不删数据；数据全部在 appdata share

## 7. 验收标准

- [ ] `docker compose up` 后容器以 PUID 进程运行（`docker exec ... id` 验证）
- [ ] appdata share 由 Unraid 默认属主创建的空目录可被容器写入
- [ ] `/api/health` 显示 libfdk_aac 编码器，HE-AAC 预设可见可选
- [ ] 上传 → 转码 → 下载全流程通（产物落 appdata share，宿主机可读）
- [ ] 书库只读挂载：浏览可见、写操作（删除/重命名）被拒绝且不崩溃
- [ ] GHCR 镜像在干净 Unraid 上 pull-and-run（用户手动验证 D1-D7 中与部署相关项）
