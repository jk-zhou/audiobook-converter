"""API: settings/session KV, import gate, jobs merge + pagination."""
import pytest
from httpx import ASGITransport, AsyncClient

from hac import db, jobs as jobs_mod
from hac.main import app
from hac.models import Job, JobStatus, TranscodeSettings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    db.init_db(tmp_path)
    jm = jobs_mod.JobManager(max_concurrent=1)
    monkeypatch.setattr(app.state, "jm", jm, raising=False)
    # main.py uses module-level jm; patch it too
    import hac.main as m
    monkeypatch.setattr(m, "jm", jm)
    yield jm


async def _c():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def test_settings_roundtrip(client):
    import asyncio

    async def go():
        async with await _c() as c:
            r = await c.put("/api/settings", json={"key": "settings.default", "value": '{"a":1}'})
            assert r.status_code == 200
            r = await c.get("/api/settings")
            rows = r.json()
            assert any(x["key"] == "settings.default" and x["value"] == '{"a":1}' for x in rows)

    asyncio.run(go())


def test_session_and_import_gate(client):
    import asyncio

    async def go():
        async with await _c() as c:
            r = await c.get("/api/session")
            assert r.status_code == 404
            r = await c.post("/api/settings/import", json={"form": {}})
            assert r.status_code == 200
            r = await c.get("/api/session")
            assert r.json() == {"form": {}}
            r = await c.post("/api/settings/import", json={"form": {"b": 2}})
            assert r.status_code == 409

    asyncio.run(go())


def _mk_job(jm, jid, status=JobStatus.DONE):
    from pathlib import Path
    j = Job(id=jid, mode="single", source_ids=["s"], source_paths=[Path("/x")],
            source_names=["a.m4a"], output_filename="a.opus",
            settings=TranscodeSettings(format="opus", codec="libopus"))
    j.output_path = tmp_out = Path("/tmp/opencode") / f"{jid}.opus"
    tmp_out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out.write_bytes(b"x")
    jm.add(j)
    if status != JobStatus.QUEUED:
        jm.set_status(j.id, status)
    return j


def test_jobs_merge_db_and_pagination(client):
    import asyncio

    async def go():
        # create 3 done jobs then evict from memory (clear_finished)
        for i in range(3):
            _mk_job(client, f"job{i:08d}")
        client.clear_finished()
        async with await _c() as c:
            r = await c.get("/api/jobs")
            rows = r.json()
            assert len(rows) == 3
            assert all(x["output_deleted_at"] for x in rows)
            r = await c.get("/api/jobs", params={"limit": 2, "offset": 0})
            assert len(r.json()) == 2
            r = await c.get("/api/jobs", params={"limit": 2, "offset": 2})
            assert len(r.json()) == 1

    asyncio.run(go())


def test_delete_output_endpoint(client):
    import asyncio

    async def go():
        j = _mk_job(client, "jobdel01")
        async with await _c() as c:
            r = await c.delete("/api/jobs/nonexist/output")
            assert r.status_code == 404
            r = await c.delete("/api/jobs/jobdel01/output")
            assert r.status_code == 200
            assert not j.output_path.exists()
            r = await c.get("/api/jobs")
            row = next(x for x in r.json() if x["id"] == "jobdel01")
            assert row["output_deleted_at"]

    asyncio.run(go())


def test_clear_finished_response(client):
    import asyncio

    async def go():
        _mk_job(client, "jobclr01")
        _mk_job(client, "jobclr02")
        async with await _c() as c:
            r = await c.post("/api/jobs/clear-finished")
            assert r.status_code == 200 and r.json()["cleaned"] == 2

    asyncio.run(go())
