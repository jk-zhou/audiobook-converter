"""Agent one-shot API: paths -> transcode -> export, minimal responses."""
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from hac import agent as agent_mod
from hac import db, jobs as jobs_mod
from hac.config import OUTPUT_DIR
from hac.main import app


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    db.init_db(tmp_path / "data")

    lib_root = tmp_path / "library" / "books"
    (lib_root / "书A").mkdir(parents=True)
    out_root = tmp_path / "library" / "out"
    out_root.mkdir(parents=True)
    monkeypatch.setattr(agent_mod, "LIBRARY_ROOTS", [lib_root.parent])
    monkeypatch.setattr(agent_mod, "OUTPUT_ROOTS", [out_root])
    # library.is_allowed / exports 运行时读 config —— 一并 patch
    from hac import config as hac_config
    monkeypatch.setattr(hac_config, "LIBRARY_ROOTS", [lib_root.parent])
    monkeypatch.setattr(hac_config, "OUTPUT_ROOTS", [out_root])
    # ASGITransport 不走 lifespan → ensure_dirs 未执行，work/outputs 指到 tmp
    monkeypatch.setattr(hac_config, "WORK_DIR", tmp_path / "data" / "work")
    monkeypatch.setattr(hac_config, "OUTPUT_DIR", tmp_path / "data" / "outputs")
    (tmp_path / "data" / "work").mkdir(parents=True)
    (tmp_path / "data" / "outputs").mkdir(parents=True)

    jm = jobs_mod.JobManager(max_concurrent=2)
    import hac.main as m
    monkeypatch.setattr(m, "jm", jm)
    # workers 在各测试的事件循环内启动（fixture 里没有 loop）

    # 真实音频文件（44.1kHz mp3 —— 同时覆盖 libopus 采样率修正路径）
    for i, name in enumerate(["1 风起.mp3", "2 云涌.mp3"], 1):
        f = lib_root / "书A" / name
        subprocess_run_sine(f, freq=400 + i * 50)
    yield {"lib_root": lib_root, "out_root": out_root, "jm": jm,
           "book_dir": lib_root / "书A"}


def subprocess_run_sine(path: Path, freq: int):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration=0.4",
                    "-ar", "44100", "-c:a", "libmp3lame", str(path)], check=True)


async def _c():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def test_agent_convert_single_with_output_dir(env):
    import asyncio

    async def go():
        env["jm"].start_workers()
        async with await _c() as c:
            r = await c.post("/api/agent/convert", json={
                "inputs": [str(env["book_dir"])],
                "preset": "audiobook_opus_32k",
                "merge": False,
                "output_dir": str(env["out_root"]),
                "timeout": 120,
            })
            assert r.status_code == 200, r.text
            jobs = r.json()["jobs"]
            assert len(jobs) == 2
            assert all(j["status"] == "done" for j in jobs), str(jobs)
            # 产物已导出到 output_dir
            outs = [Path(j["output"]) for j in jobs]
            assert all(o.parent == env["out_root"] for o in outs)
            assert all(o.exists() for o in outs)

    asyncio.run(go())
    for t in env["jm"]._workers:
        t.cancel()


def test_agent_convert_merge(env):
    import asyncio

    async def go():
        env["jm"].start_workers()
        async with await _c() as c:
            r = await c.post("/api/agent/convert", json={
                "inputs": [str(env["book_dir"])],
                "preset": "audiobook_aac_lc_64k",
                "merge": True,
                "book_title": "测试书",
                "book_artist": "测试作者",
            })
            assert r.status_code == 200, r.text
            jobs = r.json()["jobs"]
            assert len(jobs) == 1 and jobs[0]["status"] == "done", str(jobs)
            assert jobs[0]["output"].endswith(".m4b")

    asyncio.run(go())
    for t in env["jm"]._workers:
        t.cancel()


def test_agent_convert_outside_whitelist_403(env):
    import asyncio

    async def go():
        env["jm"].start_workers()
        async with await _c() as c:
            r = await c.post("/api/agent/convert", json={
                "inputs": ["/etc"], "preset": "audiobook_opus_32k"})
            assert r.status_code == 403

    asyncio.run(go())
    for t in env["jm"]._workers:
        t.cancel()


def test_agent_status_and_help(env):
    import asyncio

    async def go():
        env["jm"].start_workers()
        async with await _c() as c:
            r = await c.get("/api/agent/help")
            assert r.status_code == 200
            assert "agent/convert" in r.text
            r = await c.get("/api/agent/status", params={"ids": "nope"})
            assert r.status_code == 200 and r.json()["jobs"] == []

    asyncio.run(go())
    for t in env["jm"]._workers:
        t.cancel()


def test_agent_convert_bad_preset_400(env):
    import asyncio

    async def go():
        env["jm"].start_workers()
        async with await _c() as c:
            r = await c.post("/api/agent/convert", json={
                "inputs": [str(env["book_dir"])], "preset": "nope"})
            assert r.status_code == 400

    asyncio.run(go())
    for t in env["jm"]._workers:
        t.cancel()
