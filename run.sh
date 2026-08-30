#!/usr/bin/env bash
# Audiobook Converter 一键启动脚本
# 用法: ./run.sh help
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${HAC_PORT:-8000}"
HOST="${HAC_HOST:-0.0.0.0}"
RELOAD=""
LIBRARY_EXTRA=""
ACTION="start"

usage() {
    cat <<'EOF'
🎧 Audiobook Converter — 一键启动

用法: ./run.sh [命令] [选项]

命令:
  start        启动 Web 服务（默认，可省略）
  stop         停止正在运行的服务
  setup        初始化：创建虚拟环境 + 安装依赖 + 下载 BtbN ffmpeg
  he           源码编译含 libfdk 的 ffmpeg（启用 HE-AAC 预设，约 10 分钟）
  doctor       体检：依赖 / ffmpeg / 编码器 / 预设可用性 一键诊断
  help         显示本帮助

选项（用于 start）:
  -p, --port PORT       监听端口        （默认 8000，或环境变量 HAC_PORT）
  -H, --host HOST       监听地址        （默认 0.0.0.0 局域网可访问，或 HAC_HOST；
                                         仅本机访问用 -H 127.0.0.1）
  -r, --reload          热重载（开发用）
  -l, --library DIR     追加「本地目录导入」白名单根，可重复使用

环境变量:
  HAC_PORT=8000                端口
  HAC_HOST=0.0.0.0             监听地址（127.0.0.1 = 仅本机）
  HAC_LIBRARY_ROOTS=/a:/b      目录导入白名单根（冒号分隔）
  HAC_MAX_CONCURRENT=2         并发转码数
  HAC_MAX_UPLOAD_MB=500        单文件上传上限
  HAC_DATA_DIR=./data          数据目录（uploads/work/outputs）

示例:
  ./run.sh                                  # 最简启动 http://127.0.0.1:8000
  ./run.sh start -p 9000 -H 0.0.0.0         # 局域网可访问
  ./run.sh start -l /mnt/nas/audiobooks     # 挂载 NAS 书库目录
  ./run.sh doctor                           # 检查环境
  ./run.sh he                               # 启用 HE-AAC（libfdk）
EOF
}

log() { printf '\033[1;34m[run]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[✗]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- python / deps ----------

py() {
    if [ -x .venv/bin/python ]; then echo .venv/bin/python; else command -v python3; fi
}

ensure_deps() {
    if ! "$(py)" -c "import hac" >/dev/null 2>&1; then
        log "安装依赖…"
        if command -v uv >/dev/null 2>&1; then
            uv venv -q && uv pip install -q -e ".[dev]"
        else
            "$(py)" -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
        fi
    fi
}

pick_python() {
    # prefer vendor ffmpeg-era venv, else uv run, else python3
    if [ -x .venv/bin/python ]; then echo ".venv/bin/python"; else echo "python3"; fi
}

# ---------- commands ----------

cmd_setup() {
    log "创建虚拟环境 + 安装依赖…"
    if command -v uv >/dev/null 2>&1; then
        uv venv && uv pip install -e ".[dev]"
    else
        python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
    fi
    if [ ! -x vendor/bin/ffmpeg ] && ! command -v ffmpeg >/dev/null 2>&1; then
        log "未找到 ffmpeg，下载 BtbN 静态构建…"
        ./scripts/setup-ffmpeg.sh
    fi
    log "完成。运行 ./run.sh start 启动服务"
}

cmd_he() {
    ./scripts/build-he-ffmpeg.sh
}

cmd_doctor() {
    ensure_deps
    log "python: $($(py) -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo '?')"
    "$(py)" - <<'PYEOF' || true
from pathlib import Path
import shutil, subprocess, sys
try:
    from hac import config, encoders, presets
except Exception as e:
    print(f"[✗] 应用依赖不完整: {e}")
    sys.exit(1)

ff = config.FFMPEG_PATH
fp = config.FFPROBE_PATH
print(f"ffmpeg : {ff or '未找到 ✗'}")
print(f"ffprobe: {fp or '未找到 ✗'}")
if not ff or not fp:
    print("  → 运行 ./run.sh setup 安装")
    sys.exit(1)

enc = encoders.detect_encoders()
print(f"编码器 : {len(enc)} 个" + ("，含 libfdk_aac ✓" if "libfdk_aac" in enc else "（无 libfdk_aac，HE-AAC 预设将隐藏）"))
on = sum(1 for p in presets.PRESETS if p.effective_enabled(enc))
print(f"预设   : {on}/{len(presets.PRESETS)} 可用")
for p in presets.PRESETS:
    mark = "✓" if p.effective_enabled(enc) else "✗"
    print(f"  {mark} {p.id}")
print(f"目录导入白名单: {[str(r) for r in config.LIBRARY_ROOTS]}")
print(f"数据目录: {config.DATA_DIR}")
print("[✓] 环境就绪，可以 ./run.sh start")
PYEOF
}

cmd_stop() {
    pids=$(pgrep -f "uvicorn hac[.]main:app" || true)
    if [ -z "$pids" ]; then
        log "没有正在运行的服务"
    else
        kill $pids && log "已停止 (pid: $(echo $pids | tr '\n' ' '))"
    fi
}

cmd_start() {
    ensure_deps
    PYBIN="$(pick_python)"
    if [ "$PYBIN" = "python3" ]; then
        die "虚拟环境缺失且 python3 无 hac 包，请先运行 ./run.sh setup"
    fi
    if [ ! -x vendor/bin/ffmpeg ] && ! command -v ffmpeg >/dev/null 2>&1; then
        warn "未找到 ffmpeg —— 运行 ./run.sh setup 或 ./run.sh he"
        exit 1
    fi
    [ -n "$LIBRARY_EXTRA" ] && export HAC_LIBRARY_ROOTS="${HAC_LIBRARY_ROOTS:+$HAC_LIBRARY_ROOTS:}$LIBRARY_EXTRA"

    if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "::" ]; then
        LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
        log "本机访问  → http://127.0.0.1:${PORT}"
        [ -n "${LAN_IP:-}" ] && log "局域网访问 → http://${LAN_IP}:${PORT}"
    else
        log "访问地址  → http://${HOST}:${PORT}"
    fi
    log "停止: ./run.sh stop"
    exec "$PYBIN" -m uvicorn hac.main:app --host "$HOST" --port "$PORT" $RELOAD
}

# ---------- arg parsing ----------

while [ $# -gt 0 ]; do
    case "$1" in
        start|stop|setup|he|doctor|help|-h|--help)
            ACTION="$1"; shift ;;
        -p|--port)   PORT="$2"; shift 2 ;;
        -H|--host)   HOST="$2"; shift 2 ;;
        -r|--reload) RELOAD="--reload"; shift ;;
        -l|--library)
            LIBRARY_EXTRA="${LIBRARY_EXTRA:+$LIBRARY_EXTRA:}$2"; shift 2 ;;
        *)
            echo "未知参数: $1"; usage; exit 1 ;;
    esac
done

case "$ACTION" in
    help|-h|--help) usage ;;
    start)  cmd_start ;;
    stop)   cmd_stop ;;
    setup)  cmd_setup ;;
    he)     cmd_he ;;
    doctor) cmd_doctor ;;
esac
