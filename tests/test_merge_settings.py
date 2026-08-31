"""Merge must adopt the user's audio encoding settings (AAC family only)."""
import pytest
from fastapi import HTTPException

from hac.main import validate_merge_settings
from hac.merger import build_merge_args
from hac.models import TranscodeSettings
from hac.transcoder import audio_encode_args


def he_settings():
    return TranscodeSettings(format="m4b", codec="libfdk_aac",
                             profile="aac_he", bitrate="48k", channels=1)


def test_audio_encode_args_he():
    a = audio_encode_args(he_settings())
    assert a[a.index("-profile:a") + 1] == "aac_he"
    assert a[a.index("-b:a") + 1] == "48k"
    assert "-vbr" not in a          # bitrate wins over quality (mutual exclusion)


def test_merge_args_adopt_user_settings(tmp_path):
    srcs = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    meta = tmp_path / "m.txt"
    meta.write_text(";FFMETADATA1\n")
    a = build_merge_args(srcs, None, meta, tmp_path / "o.m4b", he_settings())
    assert "-c:a" in a and "libfdk_aac" in a
    assert a[a.index("-profile:a") + 1] == "aac_he"
    assert a[a.index("-b:a") + 1] == "48k"
    assert a[a.index("-f") + 1] == "mp4"
    # user's channels pass through; nothing hardcoded beyond that
    assert a[a.index("-ac") + 1] == "1"
    assert "-ar" not in a   # HE preset leaves samplerate to the encoder


def test_merge_args_lc_with_ar_ac(tmp_path):
    srcs = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    meta = tmp_path / "m.txt"
    meta.write_text(";FFMETADATA1\n")
    s = TranscodeSettings(format="m4b", codec="aac", bitrate="64k",
                          samplerate=24000, channels=1)
    a = build_merge_args(srcs, None, meta, tmp_path / "o.m4b", s)
    assert a[a.index("-ar") + 1] == "24000"
    assert a[a.index("-ac") + 1] == "1"


def test_validate_accepts_aac_family():
    validate_merge_settings(TranscodeSettings(format="m4b", codec="aac"))
    validate_merge_settings(he_settings())


def test_validate_rejects_opus():
    with pytest.raises(HTTPException) as e:
        validate_merge_settings(TranscodeSettings(format="m4b", codec="libopus"))
    assert "libopus" in e.value.detail


def test_validate_rejects_profile_without_fdk():
    with pytest.raises(HTTPException):
        validate_merge_settings(
            TranscodeSettings(format="m4b", codec="aac", profile="aac_he"))


def test_validate_rejects_he_v2_mono():
    with pytest.raises(HTTPException) as e:
        validate_merge_settings(TranscodeSettings(
            format="m4b", codec="libfdk_aac", profile="aac_he_v2", channels=1))
    assert "立体声" in e.value.detail


def test_chunked_chapter_timing():
    """Part boundaries use actual part durations; in-part offsets accumulate."""
    from hac.merger import build_chapter_meta_chunked
    meta = build_chapter_meta_chunked(
        part_durations=[10.5, 4.0],          # actual encoded part lengths
        chunk_sizes=[2, 1],
        source_durations=[5.0, 5.0, 4.0],    # sources (slightly shorter than encoded)
        titles=["一", "二", "三"],
        book_title="书", composer="演",
    )
    assert "composer=演" in meta
    assert "START=0\nEND=5000" in meta or "START=0\nEND=5000" in meta.replace("\r", "")
    # ch2 starts at 5000 (within part 1), part 2 starts at ACTUAL 10500
    assert "START=5000" in meta
    assert "END=10000" in meta
    assert "START=10500" in meta
    assert "END=14500" in meta


def test_concat_list_escapes_quotes(tmp_path):
    from hac.merger import build_concat_list
    p1 = tmp_path / "it's.m4a"; p1.write_bytes(b"x")
    lf = tmp_path / "l.txt"
    build_concat_list([p1], lf)
    content = lf.read_text()
    assert content.startswith("file '")
    assert "\\'" in content   # quote escaped


def test_referenced_by_active(tmp_path):
    """Active (queued/running) jobs lock their sources; finished ones don't."""
    from hac import uploads as up
    from hac.models import Job, JobStatus, TranscodeSettings

    j1 = Job(mode="single", source_ids=["u1"], output_filename="x",
             settings=TranscodeSettings(format="mp3"))
    j2 = Job(mode="single", source_ids=["u2"], output_filename="y",
             settings=TranscodeSettings(format="mp3"))
    j2.status = JobStatus.DONE
    jobs = {"j1": j1, "j2": j2}
    assert up.referenced_by_active("u1", jobs) is True    # queued/running lock
    assert up.referenced_by_active("u2", jobs) is False   # done → deletable


def test_remove_upload(tmp_path):
    from hac import uploads as up
    from hac.models import Upload
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    up._store["u1"] = Upload(id="u1", name="a.mp3", path=f, size=1)
    assert up.remove("u1") is True and not f.exists()
    assert up.remove("u1") is False   # already gone


