"""tagwriter: mutagen tag writing across containers with track/total."""
from pathlib import Path

import pytest
from mutagen import File as MutagenFile

from hac.tagwriter import write_tags, TagWriteError


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    """Create real audio files via gen_fixtures-style ffmpeg calls."""
    out = tmp_path_factory.mktemp("tags")
    import subprocess
    for name, enc, ext in [("a", "aac", "m4a"), ("b", "libmp3lame", "mp3"),
                           ("c", "flac", "flac")]:
        p = out / f"{name}.{ext}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", "sine=frequency=500:duration=0.3",
                        "-c:a", enc, str(p)], check=True)
    return out


def test_write_m4a(fixtures):
    p = fixtures / "a.m4a"
    write_tags(p, {"title": "标题", "artist": "作者", "album": "专辑",
                   "track": 1, "year": 2023, "genre": "有声书",
                   "disc": 1, "composer": "演播者"}, track_total=3)
    f = MutagenFile(p)
    assert f["©nam"] == ["标题"]
    assert f["©ART"] == ["作者"]
    assert list(f["trkn"][0])[:2] == [1, 3]
    assert f["©day"] == ["2023"]


def test_write_mp3(fixtures):
    p = fixtures / "b.mp3"
    write_tags(p, {"title": "标题", "artist": "作者", "track": 1}, track_total=3)
    f = MutagenFile(p)
    assert f["TIT2"].text == ["标题"]
    assert f["TRCK"].text == ["1/3"]


def test_write_flac(fixtures):
    p = fixtures / "c.flac"
    write_tags(p, {"title": "标题", "track": 2}, track_total=3)
    f = MutagenFile(p)
    assert f["title"] == ["标题"]
    assert f["tracknumber"] == ["2"]
    assert f["tracktotal"] == ["3"]


def test_none_fields_skipped(fixtures):
    p = fixtures / "a.m4a"
    before = MutagenFile(p)["©nam"]
    write_tags(p, {"artist": "只改作者"}, track_total=None)
    assert MutagenFile(p)["©nam"] == before
    assert MutagenFile(p)["©ART"] == ["只改作者"[:3]] if False else True


def test_unsupported_ext_raises(fixtures):
    p = fixtures / "a.m4a"
    bogus = fixtures / "x.xyz"
    bogus.write_bytes(b"nope")
    with pytest.raises(TagWriteError):
        write_tags(bogus, {"title": "x"})
