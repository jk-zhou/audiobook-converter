"""batch orchestration: preview/execute across uploads & outputs pools."""
import json
import subprocess
from pathlib import Path

import pytest

from hac import batch, db, uploads as uploads_mod, jobs as jobs_mod
from hac.models import Job, JobStatus, TranscodeSettings, Upload


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    db.init_db(tmp_path)
    up_dir = tmp_path / "uploads"
    up_dir.mkdir()
    monkeypatch.setattr(uploads_mod.config, "UPLOAD_DIR", up_dir)
    # two real mp3 uploads (tag writing needs valid MPEG frames)
    import subprocess
    for uid, name in [("aaaaaaaaaaaa", "旧1.mp3"), ("bbbbbbbbbbbb", "旧2.mp3")]:
        f = up_dir / f"{uid}_{name}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", "sine=frequency=500:duration=0.3",
                        "-c:a", "libmp3lame", str(f)], check=True)
        u = Upload(id=uid, name=name, path=f, size=f.stat().st_size)
        uploads_mod._store[uid] = u
    u1 = uploads_mod._store["aaaaaaaaaaaa"]
    u2 = uploads_mod._store["bbbbbbbbbbbb"]
    uploads_mod._store[u1.id] = u1
    uploads_mod._store[u2.id] = u2
    monkeypatch.setattr(uploads_mod, "_store", uploads_mod._store)
    yield {"up_dir": up_dir, "u1": u1, "u2": u2}
    uploads_mod._store.clear()


TPL = "${TrackNum:2} ${TrackTitle}·${Artist}"


def test_preview_uploads(env):
    res = batch.preview_batch(
        pool="uploads", ids=["aaaaaaaaaaaa", "bbbbbbbbbbbb"],
        template=TPL,
        filenames={"aaaaaaaaaaaa": "01 风起·萧鼎.mp3", "bbbbbbbbbbbb": "02 云涌·萧鼎.mp3"},
        total=None)
    assert res[0]["status"] == "ok"
    assert res[0]["new_name"] == "01 风起·萧鼎.mp3"
    assert res[0]["fields"]["TrackNum"] == 1
    assert res[0]["fields"]["TrackTitle"] == "风起"


def test_preview_conflict(env):
    res = batch.preview_batch(
        pool="uploads", ids=["aaaaaaaaaaaa", "bbbbbbbbbbbb"],
        template="${TrackTitle}", filenames={
            "aaaaaaaaaaaa": "同名.mp3", "bbbbbbbbbbbb": "同名.mp3"}, total=None)
    # 第一个保留，第二个冲突跳过（先到先得）
    assert res[0]["status"] == "ok"
    assert res[1]["status"] == "skipped" and "冲突" in res[1]["reason"]


def test_execute_uploads_renames_disk_and_registry(env):
    res = batch.execute_batch(
        pool="uploads", ids=["aaaaaaaaaaaa"], template="${TrackNum:2} ${TrackTitle}·${Artist}",
        write_fields=["title", "artist", "track"],
        filenames={"aaaaaaaaaaaa": "01 风起·萧鼎.mp3"}, total=None)
    assert res["ok"] == 1
    new_path = env["up_dir"] / "aaaaaaaaaaaa_01 风起·萧鼎.mp3"
    old_path = env["up_dir"] / "aaaaaaaaaaaa_旧1.mp3"
    assert new_path.exists() and not old_path.exists()
    assert uploads_mod.get("aaaaaaaaaaaa").name == "01 风起·萧鼎.mp3"


def test_execute_outputs_updates_jobrecord(env):
    jm = jobs_mod.JobManager(max_concurrent=1)
    from hac.models import Job
    # 单模板往返：旧名未补零 → 渲染出补零新名（规范化即重命名价值）
    out = env["up_dir"] / "1 旧章节.opus"
    out.write_bytes(b"x" * 5)
    job = Job(id="jobout001", mode="single", source_ids=["s"], source_paths=[],
              source_names=["a"], output_filename="1 旧章节.opus",
              settings=TranscodeSettings(format="opus", codec="libopus"))
    job.output_path = out
    jm.add(job)
    jm.set_status("jobout001", JobStatus.DONE)
    res = batch.execute_batch(
        pool="outputs", ids=["jobout001"], template="${TrackNum:2} ${TrackTitle}",
        write_fields=[], filenames={"jobout001": "1 旧章节.opus"},
        total=3, job_manager=jm)
    assert res["ok"] == 1
    assert (env["up_dir"] / "01 旧章节.opus").exists()
    assert db.get_job_record("jobout001").output_filename == "01 旧章节.opus"


def test_locked_uploads_skipped(env, monkeypatch):
    monkeypatch.setattr(batch, "_locked", lambda uid: uid == "aaaaaaaaaaaa")
    res = batch.execute_batch(
        pool="uploads", ids=["aaaaaaaaaaaa"], template="${TrackTitle}",
        write_fields=[], filenames={"aaaaaaaaaaaa": "01 风起·萧鼎.mp3"}, total=None)
    assert res["skipped"] == 1
    assert env["u1"].path.exists()


def test_invalid_template_raises(env):
    with pytest.raises(ValueError):
        batch.preview_batch(pool="uploads", ids=["aaaaaaaaaaaa"],
                            template="${TrackTitle}${Artist}",
                            filenames={}, total=None)
