import pytest

from hac.models import TranscodeSettings
from hac.transcoder import build_ffmpeg_args, calc_progress


def settings(fmt="opus", codec="libopus", **kw):
    base = dict(bitrate="48k", samplerate=24000, channels=1)
    base.update(kw)
    return TranscodeSettings(format=fmt, codec=codec, **base)


def test_opus_args():
    a = build_ffmpeg_args("/tmp/in.flac", "/tmp/out.opus",
                          settings("opus", "libopus", compression_level=10))
    assert "-c:a" in a and "libopus" in a
    assert "-b:a" in a and "48k" in a
    assert "-ar" in a and "24000" in a
    assert "-ac" in a and "1" in a
    assert "-compression_level" in a and "10" in a


def test_compression_level_omitted_for_non_opus():
    a = build_ffmpeg_args("/tmp/i", "/tmp/o",
                          settings("mp3", "libmp3lame", compression_level=10))
    assert "-compression_level" not in a


def test_no_double_vbr_for_fdk_with_bitrate():
    s = TranscodeSettings(format="m4a", codec="libfdk_aac", profile="aac_he",
                          bitrate="48k", quality=3, channels=1)
    a = build_ffmpeg_args("/tmp/i", "/tmp/o", s)
    assert a.count("-vbr") == 0
    assert a[a.index("-b:a") + 1] == "48k"
    assert a[a.index("-profile:a") + 1] == "aac_he"


def test_fdk_vbr_when_no_bitrate():
    s = TranscodeSettings(format="m4a", codec="libfdk_aac", bitrate=None, quality=3)
    a = build_ffmpeg_args("/tmp/i", "/tmp/o", s)
    assert a[a.index("-vbr") + 1] == "3"
    assert "-b:a" not in a


def test_he_profile_no_samplerate():
    a = build_ffmpeg_args("/tmp/i", "/tmp/o",
                          TranscodeSettings(format="m4a", codec="libfdk_aac",
                                            profile="aac_he", bitrate="48k", channels=1))
    assert "-ar" not in a


def test_loudnorm_flag():
    a = build_ffmpeg_args("/tmp/i", "/tmp/o", settings("opus", "libopus"), normalize=True)
    assert "-af" in a and "loudnorm" in a[a.index("-af") + 1]
    a2 = build_ffmpeg_args("/tmp/i", "/tmp/o", settings("opus", "libopus"))
    assert "loudnorm" not in a2


def test_extra_args_passthrough():
    a = build_ffmpeg_args("/tmp/i", "/tmp/o", settings("opus", "libopus", extra_args=["-foo", "bar"]))
    assert "-foo" in a and "bar" in a


def test_progress_flags_last():
    a = build_ffmpeg_args("/tmp/i", "/tmp/o", settings("opus", "libopus"))
    i = a.index("-progress")
    assert a[i:i + 3] == ["-progress", "pipe:1", "-stats_period"]
    assert "pipe:1" in a and a[-2] == "-nostats"


def test_cover_maps_for_m4a():
    a = build_ffmpeg_args("/tmp/i", "/tmp/o",
                          settings("m4a", "aac", bitrate="64k"))
    assert "0:v?" in a
    assert "attached_pic" in a


def test_no_cover_maps_for_opus():
    a = build_ffmpeg_args("/tmp/i", "/tmp/o", settings("opus", "libopus"))
    assert "0:v?" not in a


def test_progress_parser_partial_chunks():
    from hac.transcoder import parse_progress

    class S:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        async def read(self, n):
            return self.chunks.pop(0) if self.chunks else b""

    import asyncio

    async def collect():
        return [u async for u in parse_progress(S([
            b"frame=1\r\nout_time_us=1000000\r\nprogress=continue\r\n",
            b"\nframe=2\nout_time_us=2000000\r\nprogress=end\r\n",
        ]))]

    updates = asyncio.run(collect())
    assert {"time_us": 1000000} in updates
    assert {"time_us": 2000000} in updates
    assert {"done": True} in updates


def test_calc_progress():
    assert calc_progress(30_000_000, 60.0) == pytest.approx(50.0)
    assert calc_progress(120_000_000, 60.0) == 100.0
    assert calc_progress(1000, None) == 0.0
    assert calc_progress(-5, 10.0) == 0.0


def test_libopus_44100_autocorrects_to_48k():
    """libopus 不支持 44.1kHz——必须自动重采样为 48k，否则编码器打开即失败。"""
    a = build_ffmpeg_args("/tmp/in.mp3", "/tmp/out.opus",
                          TranscodeSettings(format="opus", codec="libopus",
                                            bitrate="64k", samplerate=44100))
    assert "48000" in a
    assert "44100" not in a


def test_non_opus_samplerate_untouched():
    a = build_ffmpeg_args("/tmp/in.mp3", "/tmp/out.m4a",
                          TranscodeSettings(format="m4a", codec="aac",
                                            samplerate=44100))
    assert "44100" in a
