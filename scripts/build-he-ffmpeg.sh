#!/usr/bin/env bash
# Build an ffmpeg with FULL HE-AAC support (libfdk_aac + SBR/PS) from source.
#
# Why this script exists (verified 2026-08-30):
#   * BtbN latest static builds no longer ship libfdk_aac (downloaded & tested).
#   * Ubuntu multiverse libfdk-aac2 lacks SBR/PS modules -> "Unable to set the AOT 5".
#   * Only upstream fdk-aac (mstorsjo) has working HE-AAC.
# Runtime: ~10 min on 6 cores. Result: vendor/bin/{ffmpeg,ffprobe} with libfdk_aac,
# after which the app auto-enables the two HE-AAC presets at startup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${HAC_BUILD_DIR:-/tmp/hac-he-build}"
FDK_VER="${FDK_VER:-2.0.2}"
FFMPEG_VER="${FFMPEG_VER:-7.1.1}"

sudo apt-get install -y -q autoconf automake libtool pkg-config nasm \
    libopus-dev libmp3lame-dev curl ca-certificates

mkdir -p "$BUILD"; cd "$BUILD"

# --- fdk-aac (upstream, has SBR/PS) ---
if [ ! -f fdk-local/lib/libfdk-aac.a ]; then
    [ -d "fdk-aac-$FDK_VER" ] || {
        curl -fsSL "https://github.com/mstorsjo/fdk-aac/archive/refs/tags/v$FDK_VER.tar.gz" -o fdk.tgz
        tar -xzf fdk.tgz
    }
    cd "fdk-aac-$FDK_VER"
    ./autogen.sh
    ./configure --prefix="$BUILD/fdk-local" --disable-shared --with-pic --enable-static
    make -j"$(nproc)" && make install
    cd "$BUILD"
fi

# --- ffmpeg ---
if [ ! -f "ffmpeg-$FFMPEG_VER/ffmpeg" ]; then
    [ -d "ffmpeg-$FFMPEG_VER" ] || {
        curl -fsSL "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz" -o ff.tar.xz
        tar -xJf ff.tar.xz
    }
    cd "ffmpeg-$FFMPEG_VER"
    PKG_CONFIG_PATH="$BUILD/fdk-local/lib/pkgconfig" \
    ./configure --enable-gpl --enable-nonfree --enable-libfdk-aac \
        --enable-libopus --enable-libmp3lame \
        --disable-autodetect --disable-doc \
        --extra-cflags="-I$BUILD/fdk-local/include" \
        --extra-ldflags="-L$BUILD/fdk-local/lib"
    make -j"$(nproc)"
fi

# --- install into vendor ---
mkdir -p "$ROOT/vendor/bin"
cp "ffmpeg-$FFMPEG_VER/ffmpeg" "ffmpeg-$FFMPEG_VER/ffprobe" "$ROOT/vendor/bin/"
"$ROOT/vendor/bin/ffmpeg" -hide_banner -encoders | grep -q libfdk_aac \
    && echo "OK: vendor/bin now has libfdk_aac — HE-AAC presets will auto-enable at startup" \
    || { echo "FAILED: no libfdk_aac in built binary"; exit 1; }
