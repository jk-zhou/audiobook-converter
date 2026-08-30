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
