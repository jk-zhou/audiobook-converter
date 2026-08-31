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
    from hac import metadata, uploads
    from hac.models import Job, TranscodeSettings
    f1 = tmp_path / "第01集 有声书.flac"
    f1.write_bytes(b"x")
    f2 = tmp_path / "第02集.flac"
    f2.write_bytes(b"x")

    monkeypatch.setattr(metadata, "read_source_tags",
                        lambda p: {"title": "真标题"} if "01" in p.name else {})
    job = Job(mode="merge", source_paths=[f1, f2], output_filename="x",
              settings=TranscodeSettings(format="m4b"))
    titles = chapter_titles(job)
    assert titles == ["真标题", "第02集"]


def test_chapter_titles_no_id_prefix(monkeypatch, tmp_path):
    """上传文件的磁盘名带 {upload_id}_ 前缀——章节名绝不能泄漏它。"""
    import uuid
    from hac import metadata, uploads
    from hac.models import Job, TranscodeSettings, Upload
    f1 = tmp_path / "ccf4f9017ec1_007《诛仙》第5集.m4a"
    f1.write_bytes(b"x")
    fid = uuid.uuid4().hex[:12]
    monkeypatch.setattr(uploads, "_store",
                        {fid: Upload(id=fid, name="007《诛仙》第5集.m4a",
                                     path=f1, size=1)})
    monkeypatch.setattr(metadata, "read_source_tags", lambda p: {})  # 源无 title
    job = Job(mode="merge", source_ids=[fid], source_paths=[f1],
              output_filename="x", settings=TranscodeSettings(format="m4b"))
    titles = chapter_titles(job)
    assert titles == ["007《诛仙》第5集"]
    assert "ccf4f9017ec1" not in titles[0]
