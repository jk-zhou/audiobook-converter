#!/usr/bin/env bash
# Download a static FFmpeg build (BtbN, GPL, includes libfdk_aac + ffprobe) into vendor/bin.
# Personal-use only: binaries linked with libfdk_aac are non-redistributable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/vendor/bin"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="${HAC_FFMPEG_URL:-https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz}"

mkdir -p "$VENDOR"
echo ">> downloading $URL"
curl -fL "$URL" -o "$TMP/ffmpeg.tar.xz"
echo ">> extracting"
tar -xJf "$TMP/ffmpeg.tar.xz" -C "$TMP"
find "$TMP" -type f -name ffmpeg  -exec cp {} "$VENDOR/" \;
find "$TMP" -type f -name ffprobe -exec cp {} "$VENDOR/" \;
chmod +x "$VENDOR/ffmpeg" "$VENDOR/ffprobe"

echo ">> verifying"
"$VENDOR/ffmpeg" -version | head -1
if "$VENDOR/ffmpeg" -hide_banner -encoders 2>/dev/null | grep -q libfdk_aac; then
    echo "OK: libfdk_aac available (HE-AAC presets enabled)"
else
    echo "WARN: libfdk_aac missing, HE-AAC presets will stay disabled"
fi
