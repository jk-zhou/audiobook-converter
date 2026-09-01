"""End-to-end transcode & merge execution against the real ffmpeg binary."""
import json
import subprocess

import pytest

from hac import config
from hac.jobs import JobManager
from hac.models import Job, JobStatus, TranscodeSettings, MergeOptions, MetadataEdit


def ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
         "-show_streams", "-show_chapters", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "outputs")
    config.ensure_dirs()


class FakeMgr:
    """Minimal JobManager-compatible stub."""

    def __init__(self):
        self.jobs = {}
        self.procs = {}

    def set_status(self, jid, status, error=None):
        j = self.jobs[jid]
        j.status = status
        if error:
            j.error = error

    def set_progress(self, jid, pct):
        self.jobs[jid].progress = pct

    def register_proc(self, jid, proc):
        self.procs[jid] = proc


@pytest.fixture
def mgr():
    return FakeMgr()


def test_single_opus_transcodes(sources_dir, mgr):
    from hac.transcoder import execute_single
    j = Job(mode="single", source_paths=[sources_dir / "ch1.mp3"],
            output_filename="test",
            settings=TranscodeSettings(format="opus", codec="libopus",
                                       bitrate="48k", samplerate=24000,
                                       channels=1, compression_level=10),
            metadata=MetadataEdit(title="测试"))
    mgr.jobs[j.id] = j
    asyncio_run(execute_single(j, mgr))
    assert j.status == JobStatus.DONE, j.error
    data = ffprobe(j.output_path)
    st = data["streams"][0]
    assert st["codec_name"] == "opus"
    assert st["channels"] == 1
    # Ogg/Opus containers always report 48kHz (RFC 7845); internal coding rate
    # follows -ar 24000. ffprobe stream sample_rate is fixed at 48000.
    assert int(st["sample_rate"]) == 48000
    assert j.verify and j.verify.codec == "opus"
    assert j.verify.savings_pct and j.verify.savings_pct > 0


def test_single_normalize_flag(sources_dir, mgr):
    from hac.transcoder import execute_single
    j = Job(mode="single", source_paths=[sources_dir / "ch1.mp3"],
            output_filename="norm", normalize=True,
            settings=TranscodeSettings(format="opus", codec="libopus", bitrate="64k"))
    mgr.jobs[j.id] = j
    asyncio_run(execute_single(j, mgr))
    assert j.status == JobStatus.DONE, j.error


def test_merge_m4b_chapters(sources_dir, mgr):
    from hac.merger import execute_merge
    j = Job(mode="merge",
            source_paths=[sources_dir / "ch1.mp3", sources_dir / "ch2.m4a",
                          sources_dir / "ch3.flac"],
            output_filename="书.m4b",
            settings=TranscodeSettings(format="m4b", codec="aac", bitrate="64k"),
            merge=MergeOptions(book_title="测试书", book_artist="测试作者"))
    mgr.jobs[j.id] = j
    asyncio_run(execute_merge(j, mgr))
    assert j.status == JobStatus.DONE, j.error

    data = ffprobe(j.output_path)
    chapters = data.get("chapters", [])
    assert len(chapters) == 3
    assert chapters[1]["start_time"] == chapters[0]["end_time"]
    assert chapters[2]["start_time"] == chapters[1]["end_time"]
    titles = [c["tags"]["title"] for c in chapters]
    assert titles[0] == "第一章 开端"
    fmt = data["format"]
    assert fmt["tags"]["title"] == "测试书"
    assert fmt["tags"]["artist"] == "测试作者"
    st = data["streams"][0]
    assert st["codec_name"] == "aac"
    assert st["channels"] == 1


def test_merge_with_cover(sources_dir, mgr, monkeypatch):
    from hac import merger
    from hac.merger import execute_merge
    cover = sources_dir / "cover.jpg"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=blue:s=440x440:d=0.1", "-frames:v", "1", str(cover)],
        check=True)

    j = Job(mode="merge",
            source_paths=[sources_dir / "ch1.mp3", sources_dir / "ch2.m4a"],
            output_filename="cover-book.m4b",
            settings=TranscodeSettings(format="m4b", codec="aac"),
            merge=MergeOptions(book_title="带封面的书"))
    monkeypatch.setattr(merger, "_resolve_cover", lambda job, work: cover)
    mgr.jobs[j.id] = j
    asyncio_run(execute_merge(j, mgr))
    assert j.status == JobStatus.DONE, j.error
    data = ffprobe(j.output_path)
    vstreams = [s for s in data["streams"] if s["codec_type"] == "video"]
    assert len(vstreams) == 1
    assert vstreams[0]["codec_name"] == "mjpeg"
    assert vstreams[0].get("disposition", {}).get("attached_pic") == 1


def test_cancelled_ffmpeg_leaves_no_output(sources_dir, mgr, monkeypatch):
    from hac import transcoder
    j = Job(mode="single", source_paths=[sources_dir / "ch1.mp3"],
            output_filename="x",
            settings=TranscodeSettings(format="opus", codec="libopus", bitrate="48k"))
    mgr.jobs[j.id] = j

    class FakeProc:
        returncode = None

        def send_signal(self, s):
            pass

        async def wait(self):
            return 0

        def kill(self):
            pass

    async def cancelling_run(args, register_proc=None, on_progress=None):
        if register_proc:
            register_proc(FakeProc())
        mgr.set_status(j.id, JobStatus.CANCELLED)
        return 0, ""

    monkeypatch.setattr(transcoder, "run_ffmpeg", cancelling_run)
    asyncio_run(transcoder.execute_single(j, mgr))
    assert j.status == JobStatus.CANCELLED
    assert not list(config.OUTPUT_DIR.glob("*")) or all(
        p.exists() is False or "x" not in p.name for p in config.OUTPUT_DIR.glob("*"))


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
