"""Generate synthetic audiobook fixtures for the browser E2E suite.

Usage: python tests/e2e/gen_fixtures.py
Creates /tmp/hac-e2e/ (uploaded-style files) and <repo>/data/library/testbook/
(server-side library folder). Idempotent — regenerates in place.
"""
import subprocess
import sys
from pathlib import Path

UP = Path("/tmp/hac-e2e")
LIB = Path(__file__).resolve().parent.parent.parent / "data" / "library" / "testbook"


def run(cmd):
    subprocess.run(cmd, check=True)


def main():
    UP.mkdir(parents=True, exist_ok=True)
    LIB.mkdir(parents=True, exist_ok=True)

    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", "-c:a", "libmp3lame",
         "-id3v2_version", "3", "-metadata", "title=第一章 开端",
         "-metadata", "artist=测试作者", str(UP / "ch1.mp3")])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=550:duration=2.5", "-c:a", "aac",
         "-metadata", "title=第二章 转折", str(UP / "ch2.m4a")])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=660:duration=2", "-c:a", "libmp3lame",
         "-id3v2_version", "3", "-metadata", "title=第三章 结局",
         str(UP / "ch3.mp3")])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=660:duration=2", "-c:a", "flac",
         "-metadata", "title=第三章 结局", str(LIB / "ch3.flac")])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=steelblue:s=400x400:d=0.1", "-frames:v", "1",
         str(UP / "cover.jpg")])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=330:duration=180", "-c:a", "pcm_s16le",
         str(UP / "long_ch.wav")])   # 15MB — real upload progress + slow transcode
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=300:duration=600", "-c:a", "pcm_s16le",
         str(UP / "long2.wav")])     # 50MB — cancel/loudnorm jobs
    print(f"fixtures ready: {UP} + {LIB}")


if __name__ == "__main__":
    sys.exit(main())
