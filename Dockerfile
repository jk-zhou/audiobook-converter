# ---- Stage 1: build fdk-aac + ffmpeg (nonfree: libfdk_aac) ----
# Nonfree build: image is for self-hosting only, not for redistribution.
FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential pkg-config yasm nasm autoconf automake libtool \
      libopus-dev libmp3lame-dev libvorbis-dev \
      ca-certificates curl xz-utils git && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# fdk-aac 2.0.2
RUN curl -fsSL https://github.com/mstorsjo/fdk-aac/archive/refs/tags/v2.0.2.tar.gz | tar xz && \
    cd fdk-aac-2.0.2 && ./autogen.sh && \
    ./configure --prefix=/usr/local --enable-static --disable-shared && \
    make -j"$(nproc)" && make install
# ffmpeg 7.1.1 (stable release; full codec coverage, no --disable-everything)
RUN curl -fsSL https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz | tar xJ && \
    cd ffmpeg-7.1.1 && ./configure --prefix=/usr/local \
      --enable-gpl --enable-nonfree --enable-libfdk-aac \
      --enable-libopus --enable-libmp3lame --enable-libvorbis \
      --disable-doc --disable-debug && \
    make -j"$(nproc)" && make install

# ---- Stage 2: runtime ----
FROM python:3.11-slim
# runtime libs for the encoder set linked into ffmpeg (same debian release as builder)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl gosu ca-certificates \
      libopus0 libmp3lame0 libvorbis0a libvorbisenc2 libogg0 \
      && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=builder /usr/local/bin/ffprobe /usr/local/bin/ffprobe
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
# PUID/PGID left empty by default: root runs uvicorn directly.
# NAS deployments (compose) set PUID/PGID; entrypoint drops privileges then.
ENV HAC_DATA_DIR=/app/data \
    HAC_MAX_CONCURRENT=2 \
    PUID= \
    PGID=
RUN mkdir -p /app/data/uploads /app/data/work /app/data/outputs /app/data/library
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
