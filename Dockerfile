FROM python:3.11-slim

# ffmpeg fallback + curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl ca-certificates && rm -rf /var/lib/apt/lists/*

# BtbN static ffmpeg (includes libfdk_aac + ffprobe) -> enables HE-AAC presets.
# Falls back to the apt ffmpeg above if the download fails at build time.
ARG FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz
RUN set -e; \
    tmp=$(mktemp -d); \
    (curl -fsSL "$FFMPEG_URL" -o "$tmp/f.tar.xz" \
      && tar -xJf "$tmp/f.tar.xz" -C "$tmp" \
      && find "$tmp" -type f -name ffmpeg  -exec cp {} /usr/local/bin/ \; \
      && find "$tmp" -type f -name ffprobe -exec cp {} /usr/local/bin/ \; \
      && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe) \
     || echo "WARN: BtbN download failed; apt ffmpeg (no libfdk_aac) will be used"; \
    rm -rf "$tmp"

RUN useradd -m -u 1000 app
WORKDIR /app
USER app

COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app src/ ./src/
RUN pip install --no-cache-dir .

ENV HAC_DATA_DIR=/app/data \
    HAC_MAX_CONCURRENT=2
RUN mkdir -p /app/data/uploads /app/data/work /app/data/outputs /app/data/library

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

EXPOSE 8000
ENTRYPOINT ["uvicorn", "hac.main:app", "--host", "0.0.0.0", "--port", "8000"]
