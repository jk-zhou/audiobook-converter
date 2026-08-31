"""Title/track resolution (WYSIWYG order) + composer in merge metadata."""
import subprocess

import pytest

from hac.merger import build_chapter_meta
from hac.transcoder import parse_track_number, render_title_pattern, resolve_title_and_track
from hac.models import Job, JobStatus, TranscodeSettings


def test_parse_track_number():
    assert parse_track_number("3") == 3
    assert parse_track_number("3/12") == 3
    assert parse_track_number(["7/30"]) == 7
    assert parse_track_number(None) is None
    assert parse_track_number("abc") is None


def test_render_title_pattern():
    assert render_title_pattern("第${TrackNum}集", 5) == "第5集"
    assert render_title_pattern("第${TrackNum:3}集", 5) == "第005集"
    assert render_title_pattern("第${TrackNum:3}集", 1234) == "第1234集"
    assert render_title_pattern("Ch ${TrackNum}", None) == "Ch "
    assert render_title_pattern("plain", 1) == "plain"


def _mk_source(tmp_path, name, with_track=True):
    p = tmp_path / name
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "sine=duration=0.1", "-c:a", "libmp3lame", "-id3v2_version", "3"]
    if with_track:
        cmd += ["-metadata", "track=7/30"]
    cmd += [str(p)]
    subprocess.run(cmd, check=True)
    return p


def _job(tmp_path, src, **kw):
    defaults = dict(mode="single", source_paths=[src], output_filename="x",
                    settings=TranscodeSettings(format="mp3", codec="libmp3lame"),
                    position=4, total=20)
    defaults.update(kw)
    return Job(**defaults)


def test_track_fallback_to_position(tmp_path):
    src = _mk_source(tmp_path, "a.mp3", with_track=False)
    title, track = resolve_title_and_track(_job(tmp_path, src), src)
    assert title is None                       # inherit: no override
    assert track == (4, 20)                    # order used as track number


def test_source_track_wins_over_position(tmp_path):
    src = _mk_source(tmp_path, "b.mp3", with_track=True)
    _, track = resolve_title_and_track(_job(tmp_path, src), src)
    assert track is None                       # source has track → no override


def test_title_from_filename(tmp_path):
    src = _mk_source(tmp_path, "第04集 标题.mp3", with_track=False)
    title, _ = resolve_title_and_track(
        _job(tmp_path, src, title_source="filename"), src)
    assert title == "第04集 标题"


def test_title_from_pattern_uses_source_track_then_position(tmp_path):
    src_with = _mk_source(tmp_path, "c.mp3", with_track=True)      # track 7
    j = _job(tmp_path, src_with, title_source="pattern",
             title_pattern="第${TrackNum:3}集")
    title, _ = resolve_title_and_track(j, src_with)
    assert title == "第007集"

    src_without = _mk_source(tmp_path, "d.mp3", with_track=False)
    j2 = _job(tmp_path, src_without, title_source="pattern",
              title_pattern="第${TrackNum}集", position=12)
    title2, _ = resolve_title_and_track(j2, src_without)
    assert title2 == "第12集"                       # falls back to position


def test_inherit_no_position_is_noop(tmp_path):
    src = _mk_source(tmp_path, "e.mp3", with_track=False)
    title, track = resolve_title_and_track(
        _job(tmp_path, src, position=None, total=None), src)
    assert title is None and track is None


def test_composer_in_ffmetadata():
    meta = build_chapter_meta([10.0], ["ch1"], book_title="书",
                              book_artist="作者", composer="演播者")
    assert "composer=演播者" in meta
