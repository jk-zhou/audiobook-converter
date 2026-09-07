"""分卷合并 + 直通（copy_audio）：创建分区、预检、构建参数。"""
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from hac import db, jobs as jobs_mod
from hac.main import app
from hac.merger import build_passthrough_args
from hac.models import Job, JobStatus, TranscodeSettings, Upload


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    db.init_db(tmp_path / "data")
    jm = jobs_mod.JobManager(max_concurrent=2)
    import hac.main as m
    monkeypatch.setattr(m, "jm", jm)

    # 4 个上传文件：3 个 aac + 1 个 mp3（用于直通预检失败场景）
    up_dir = tmp_path / "ups"
    up_dir.mkdir()
    ups = {}
    for i, codec in enumerate(["aac", "aac", "aac", "mp3"], 1):
        f = up_dir / f"up{i:08d}_第{i}集.m4a"
        f.write_bytes(b"x" * 64)
        u = Upload(id=f"up{i:08d}", name=f"第{i}集.m4a",
                   path=f, size=64, info={"codec": codec})
        ups[u.id] = u
    import hac.uploads as up_mod
    monkeypatch.setattr(up_mod, "_store", ups)
    import hac.main as m
    monkeypatch.setattr(m, "uploads", up_mod)
    yield {"jm": jm, "ups": ups}


def u_path_id(i):
    return f"up{i:08d}"


async def _c():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def test_split_partitions_into_volumes(env):
    import asyncio

    async def go():
        async with await _c() as c:
            r = await c.post("/api/jobs", json={
                "mode": "merge",
                "source_ids": ["up00000001", "up00000002", "up00000003"],
                "preset_id": "audiobook_aac_lc_64k",
                "merge": {"book_title": "书A"},
                "merge_split": 2,
            })
            assert r.status_code == 200, r.text
            ids = r.json()["job_ids"]
            assert len(ids) == 2   # 3 章 / 每卷 2 = 2 卷
            jobs = [env["jm"].jobs[i] for i in ids]
            assert [len(j.source_ids) for j in jobs] == [2, 1]
            assert jobs[0].output_filename == "书A_01"
            assert jobs[1].output_filename == "书A_02"
            # 卷 title 唯一且零填充（Apple Books 排序关键）
            assert jobs[0].merge.volume_title == "书A 第001-002章"
            assert jobs[1].merge.volume_title == "书A 第003-003章"
            assert jobs[0].merge.volume_disc == "1/2"

    asyncio.run(go())


def test_split_allows_single_volume_file(env):
    import asyncio

    async def go():
        async with await _c() as c:
            # 2 文件 / 每卷 5 章 → 1 卷；分卷模式放宽 ≥2 限制的场景不会出现，
            # 但单卷内部 2 个文件合法；真正要验证的是 merge_split 放宽逻辑
            r = await c.post("/api/jobs", json={
                "mode": "merge",
                "source_ids": ["up00000001", "up00000002"],
                "preset_id": "audiobook_aac_lc_64k",
                "merge": {"book_title": "书B"},
                "merge_split": 5,
            })
            assert r.status_code == 200
            assert len(r.json()["job_ids"]) == 1

    asyncio.run(go())


def test_passthrough_rejects_non_aac(env):
    import asyncio

    async def go():
        async with await _c() as c:
            r = await c.post("/api/jobs", json={
                "mode": "merge",
                "source_ids": ["up00000001", "up00000004"],   # 含 mp3
                "preset_id": "audiobook_aac_lc_64k",
                "merge": {"book_title": "书C"},
                "merge_copy": True,
            })
            assert r.status_code == 400
            assert "mp3" in r.json()["detail"]

    asyncio.run(go())


def test_passthrough_args_shape():
    a = build_passthrough_args(Path("/tmp/l.txt"), None, Path("/tmp/m.txt"),
                               Path("/tmp/o.m4b"),
                               extra_metadata={"title": "书A 第001-002章",
                                               "disc": "1/2"})
    joined = " ".join(a)
    assert "-c:a copy" in joined
    assert "title=书A 第001-002章" in joined and "disc=1/2" in joined
    assert "-map_chapters" in joined


def test_volume_metadata_reaches_args():
    """卷 title/disc 通过 extra_metadata 进入 ffmpeg 参数。"""
    from hac.merger import build_merge_args
    a = build_merge_args([], None, Path("/tmp/m.txt"), Path("/tmp/o.m4b"),
                         TranscodeSettings(format="m4b", codec="aac"),
                         extra_metadata={"title": "书A 第001-002章",
                                         "disc": "1/2"})
    assert "title=书A 第001-002章" in " ".join(a)
    assert "disc=1/2" in " ".join(a)
