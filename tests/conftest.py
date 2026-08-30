"""Shared fixtures: real ffmpeg/ffprobe binaries and synthetic audio sources."""
import subprocess

import pytest

from hac import config


@pytest.fixture(scope="session")
def real_ffmpeg():
    ff = config.FFMPEG_PATH
    ffp = config.FFPROBE_PATH
    assert ff and ffp, "ffmpeg/ffprobe required for tests"
    return {"ffmpeg": str(ff), "ffprobe": str(ffp)}


def _gen(path: str, codec: list[str], extra_meta: list[str] | None = None,
         seconds: float = 0.5):
    meta: list[str] = []
    for kv in (extra_meta or []):
        meta += ["-metadata", kv]
    cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={seconds}"]
           + codec + meta
           + [str(path)])
    subprocess.run(cmd, check=True)


@pytest.fixture
def sources_dir(tmp_path):
    """Three 'chapters' in mixed formats with tags."""
    d = tmp_path / "book"
    d.mkdir()
    _gen(d / "ch1.mp3", ["-c:a", "libmp3lame", "-id3v2_version", "3"],
         ["title=第一章 开端", "artist=某作者"])
    _gen(d / "ch2.m4a", ["-c:a", "aac"],
         ["title=第二章 转折"])
    _gen(d / "ch3.flac", ["-c:a", "flac"],
         ["title=第三章 结局"])
    return d
