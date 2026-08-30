import pytest

from hac.merger import build_chapter_meta, _escape_ffmetadata, chapter_titles


def test_chapter_times_cumulative():
    meta = build_chapter_meta([10.0, 5.5, 120.25], ["一", "二", "三"],
                              book_title="书", book_artist="作者")
    assert meta.startswith(";FFMETADATA1")
    assert "title=书" in meta
    assert "artist=作者" in meta
    ch1_start, ch1_end = "START=0", "END=10000"
    assert ch1_start in meta and ch1_end in meta
    assert "START=10000" in meta   # ch2 starts where ch1 ends
    assert "END=15500" in meta     # 10 + 5.5 = 15.5s
    assert "START=15500" in meta   # ch3 starts where ch2 ends
    assert "END=135750" in meta    # 135.25s total
    assert "title=三" in meta


def test_escape_special_chars():
    assert _escape_ffmetadata("a=b") == "a\\=b"
    assert _escape_ffmetadata("a;b") == "a\\;b"
    assert _escape_ffmetadata("a\nb") == "a b"


def test_chapter_titles_fallback(monkeypatch, tmp_path):
    from hac import metadata
    f1 = tmp_path / "第01集 有声书.flac"
    f1.write_bytes(b"x")
    f2 = tmp_path / "第02集.flac"
    f2.write_bytes(b"x")

    monkeypatch.setattr(metadata, "read_source_tags",
                        lambda p: {"title": "真标题"} if "01" in p.name else {})
    titles = chapter_titles([f1, f2])
    assert titles == ["真标题", "第02集"]
