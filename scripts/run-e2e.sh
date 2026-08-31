#!/usr/bin/env bash
# Browser E2E suite runner — isolated data dir, self-managed server lifecycle.
#
# Usage:
#   ./scripts/run-e2e.sh              # run all 3 parts
#   ./scripts/run-e2e.sh part2        # run a single part (part1|part2|part3)
#
# The server runs on E2E_PORT (default 8765) with HAC_DATA_DIR pointed at an
# isolated temp dir, so your real data/ is never touched. Chromium crash under
# a full /tmp? The runner exports TMPDIR to a repo-adjacent dir automatically.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ONLY="${1:-all}"
PORT="${E2E_PORT:-8765}"
export E2E_BASE_URL="http://127.0.0.1:${PORT}"
E2E_DATA="$(mktemp -d /tmp/hac-e2e-data.XXXXXX)"
export E2E_SHOTS="$ROOT/data/e2e-shots"
mkdir -p "$E2E_SHOTS" "$ROOT/data/e2e-tmp"
export TMPDIR="${TMPDIR:-$ROOT/data/e2e-tmp}"

log()  { printf '\033[1;34m[e2e]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[e2e]\033[0m %s\n' "$*" >&2; }

cleanup() {
    if [ -n "${SRV_PID:-}" ]; then
        kill "$SRV_PID" 2>/dev/null
    fi
    log "服务已停止；隔离数据保留在 $E2E_DATA（server.log 在 data/e2e-server.log）"
}
trap cleanup EXIT

# deps
if ! .venv/bin/python -c "import hac" >/dev/null 2>&1; then
    log "依赖缺失 — 先运行 ./run.sh setup"
    exit 2
fi
if ! .venv/bin/python -c "import playwright" >/dev/null 2>&1; then
    log "安装 playwright…"
    uv pip install -q playwright && .venv/bin/python -m playwright install chromium >/dev/null
fi

# fixtures (synthetic audio + library folder)
.venv/bin/python tests/e2e/gen_fixtures.py || exit 2
mkdir -p "$E2E_DATA/library"
cp -r data/library/testbook "$E2E_DATA/library/" 2>/dev/null

# ffmpeg: vendor → system
if [ -x vendor/bin/ffmpeg ]; then
    export HAC_FFMPEG_PATH="$ROOT/vendor/bin/ffmpeg"
    export HAC_FFPROBE_PATH="$ROOT/vendor/bin/ffprobe"
elif ! command -v ffmpeg >/dev/null; then
    fail "未找到 ffmpeg — 运行 ./run.sh setup"
    exit 2
fi

# server lifecycle: fresh isolated data dir per part
start_server() {
    rm -rf "$E2E_DATA"
    mkdir -p "$E2E_DATA/library" "$E2E_DATA/tmp"
    cp -r data/library/testbook "$E2E_DATA/library/" 2>/dev/null
    nohup env HAC_DATA_DIR="$E2E_DATA" \
        HAC_LIBRARY_ROOTS="$E2E_DATA/library" \
        HAC_MERGE_CHUNK=100 \
        TMPDIR="$ROOT/data/e2e-tmp" \
        .venv/bin/uvicorn hac.main:app --host 127.0.0.1 --port "$PORT" \
        > "$ROOT/data/e2e-server.log" 2>&1 &
    SRV_PID=$!
    for i in $(seq 1 20); do
        curl -sf -m 2 "$E2E_BASE_URL/api/health" >/dev/null && return 0
        sleep 0.5
    done
    fail "服务未启动，日志：$E2E_DATA/server.log"
    return 1
}

stop_server() {
    [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null
    wait "$SRV_PID" 2>/dev/null
    SRV_PID=""
}

FAILED=0
PARTS="part1_transcode part2_merge_features part3_ui_session"
if [ "$ONLY" != "all" ]; then
    PARTS=""
    for want in $ONLY; do
        match=$(ls tests/e2e/ | grep "^${want}" | head -1)
        [ -z "$match" ] && { fail "找不到测试部件: $want（可选: part1 part2 part3）"; exit 2; }
        PARTS="$PARTS ${match%.py}"
    done
fi

for part in $PARTS; do
    start_server || exit 2
    log "服务就绪 $E2E_BASE_URL（隔离数据目录 $E2E_DATA）"
    log "=== $part ==="
    if TMPDIR="${TMPDIR:-$ROOT/data/e2e-tmp}" \
       .venv/bin/python "tests/e2e/${part}.py"; then
        :
    else
        FAILED=1
        log "$part 有失败项（截图在 $E2E_SHOTS）"
    fi
    stop_server
done

log "完成。截图目录：$E2E_SHOTS"
exit $FAILED
