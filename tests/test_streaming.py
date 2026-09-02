"""streaming: Range parsing, 206 responses, chapters, security checks."""
import json
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from hac import db, streaming, uploads as uploads_mod, jobs as jobs_mod
from hac.main import app
from hac.models import Job, JobStatus, TranscodeSettings, Upload


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    db.init_db(tmp_path)
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    # real audio fixture
    f = out_dir / "job0001_x.opus"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=500:duration=0.5",
                    "-c:a", "libopus", str(f)], check=True)
    monkeypatch.setattr(streaming.config, "OUTPUT_DIR", out_dir)
    jm = jobs_mod.JobManager(max_concurrent=1)
    import hac.main as m
    monkeypatch.setattr(m, "jm", jm)
    yield {"out_dir": out_dir, "jm": jm, "opus": f}


async def _c():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# ---------- parse_range ----------

def test_parse_none():
    assert streaming.parse_range(None, 1000) is None
    assert streaming.parse_range("bytes=", 1000) is None


def test_parse_full_matrix():
    assert streaming.parse_range("bytes=0-99", 1000) == (0, 99)
    assert streaming.parse_range("bytes=100-", 1000) == (100, 999)
    assert streaming.parse_range("bytes=-500", 1000) == (500, 999)
    assert streaming.parse_range("bytes=-100000", 1000) == (0, 999)  # suffix clamp
    assert streaming.parse_range("bytes=999-999", 1000) == (999, 999)


def test_parse_invalid():
    assert streaming.parse_range("bytes=500-100", 1000) == "invalid"   # start>end
    assert streaming.parse_range("bytes=2000-", 1000) == "invalid"     # out of range
    assert streaming.parse_range("wibble", 1000) == "invalid"


# ---------- mime ----------

def test_mime_map():
    assert streaming.mime_for(Path("a.m4b")) == "audio/mp4"
    assert streaming.mime_for(Path("a.mp3")) == "audio/mpeg"
    assert streaming.mime_for(Path("a.opus")) == "audio/ogg"
    assert streaming.mime_for(Path("a.weird")) == "application/octet-stream"


# ---------- chapters ----------

def test_chapters_mp3_empty(tmp_path):
    f = tmp_path / "x.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=duration=0.3", "-c:a", "libmp3lame", str(f)],
                   check=True)
    assert streaming.chapters_for(f) == []


# ---------- endpoints ----------

def _mk_job(env):
    job = Job(id="job0001", mode="single", source_ids=["s"], source_paths=[],
              source_names=["x"], output_filename="x.opus",
              settings=TranscodeSettings(format="opus", codec="libopus"))
    job.output_path = env["opus"]
    env["jm"].add(job)
    env["jm"].set_status("job0001", JobStatus.DONE)
    return job


def test_stream_job_range(env):
    import asyncio

    _mk_job(env)

    async def go():
        async with await _c() as c:
            r = await c.get("/api/stream/job/job0001",
                            headers={"Range": "bytes=0-99"})
            assert r.status_code == 206
            assert r.headers["content-range"].startswith("bytes 0-99/")
            assert r.headers["accept-ranges"] == "bytes"
            assert len(r.content) == 100
            r2 = await c.get("/api/stream/job/job0001")
            assert r2.status_code == 200
            r3 = await c.get("/api/stream/job/job0001",
                             headers={"Range": "bytes=999999999-"})
            assert r3.status_code == 416

    asyncio.run(go())


def test_stream_job_missing(env):
    import asyncio

    async def go():
        async with await _c() as c:
            r = await c.get("/api/stream/job/nope")
            assert r.status_code == 404

    asyncio.run(go())


def test_stream_upload_security(env, tmp_path):
    import asyncio

    f = tmp_path / "up.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=duration=0.3", "-c:a", "libmp3lame", str(f)],
                   check=True)
    u = Upload(id="upload00001", name="up.mp3", path=f, size=f.stat().st_size)
    uploads_mod._store[u.id] = u

    async def go():
        async with await _c() as c:
            r = await c.get("/api/stream/upload/upload00001")
            assert r.status_code == 200
            r = await c.get("/api/stream/upload/nope")
            assert r.status_code == 404

    asyncio.run(go())
    uploads_mod._store.pop("upload00001")


def test_info_endpoint(env):
    import asyncio

    _mk_job(env)

    async def go():
        async with await _c() as c:
            r = await c.get("/api/stream/job/job0001/info")
            assert r.status_code == 200
            d = r.json()
            assert d["codec"] == "opus"
            assert d["duration"] > 0.3
            assert d["chapters"] == []

    asyncio.run(go())
