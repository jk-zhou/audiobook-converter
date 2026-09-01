"""JobManager DB persistence: add/status/progress, restore, clear semantics."""
from pathlib import Path

import pytest

from hac import db, jobs as jobs_mod
from hac.models import Job, JobStatus, TranscodeSettings


@pytest.fixture()
def dbtmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    db.init_db(tmp_path)
    yield tmp_path


@pytest.fixture()
def jm(dbtmp):
    return jobs_mod.JobManager(max_concurrent=1)


def _job(jid="job00000001", out="a.opus"):
    return Job(
        id=jid, mode="single", source_ids=["src1"], source_paths=[Path("/x")],
        source_names=["a.m4a"], output_filename=out,
        settings=TranscodeSettings(format="opus", codec="libopus"),
    )


def test_add_persists_to_db(jm):
    jm.add(_job())
    rec = db.get_job_record("job00000001")
    assert rec is not None and rec.status == "queued"


def test_set_status_persists(jm):
    jm.add(_job())
    jm.set_status("job00000001", JobStatus.DONE)
    rec = db.get_job_record("job00000001")
    assert rec.status == "done" and rec.progress == 100.0
    assert rec.finished_at is not None


def test_progress_throttle_persists_5pct(jm):
    jm.add(_job())
    jm.set_progress("job00000001", 1.0)   # first write
    jm.set_progress("job00000001", 2.0)   # <5% delta -> no DB write
    rec = db.get_job_record("job00000001")
    assert rec.progress == 1.0
    jm.set_progress("job00000001", 6.0)   # >=5% -> write
    assert db.get_job_record("job00000001").progress == 6.0


def test_restore_from_db(jm, dbtmp):
    jm.add(_job())
    jm.set_status("job00000001", JobStatus.DONE)
    jm2 = jobs_mod.JobManager(max_concurrent=1)
    jm2.restore_from_db()
    assert "job00000001" in jm2.jobs
    assert jm2.jobs["job00000001"].status == JobStatus.DONE


def test_restore_marks_active_as_interrupted(jm, dbtmp):
    jm.add(_job())
    jm.set_status("job00000001", JobStatus.RUNNING)
    jm2 = jobs_mod.JobManager(max_concurrent=1)
    jm2.restore_from_db()
    assert jm2.jobs["job00000001"].status == JobStatus.INTERRUPTED
    assert "重启" in (jm2.jobs["job00000001"].error or "")


def test_clear_finished_deletes_output_keeps_history(jm, dbtmp, tmp_path):
    job = _job()
    outfile = tmp_path / "a.opus"
    outfile.write_bytes(b"x")
    job.output_path = outfile
    jm.add(job)
    jm.set_status("job00000001", JobStatus.DONE)
    n = jm.clear_finished()
    assert n == 1
    assert not outfile.exists()                      # 产物删除
    rec = db.get_job_record("job00000001")           # 历史保留
    assert rec is not None and rec.output_deleted_at is not None
    assert "job00000001" not in jm.jobs              # 内存移除


def test_delete_output_single(jm, dbtmp, tmp_path):
    job = _job()
    outfile = tmp_path / "a.opus"
    outfile.write_bytes(b"x")
    job.output_path = outfile
    jm.add(job)
    jm.set_status("job00000001", JobStatus.DONE)
    assert jm.delete_output("job00000001") is True
    assert not outfile.exists()
    assert db.get_job_record("job00000001").output_deleted_at is not None
    assert "job00000001" in jm.jobs                  # 单任务删除保留内存条目
    assert jm.delete_output("nonexistent") is False


def test_db_only_jobs(jm, dbtmp):
    jm.add(_job())
    jm.set_status("job00000001", JobStatus.DONE)
    jm.clear_finished()
    only = jm.db_only_jobs()
    assert [j.id for j in only] == ["job00000001"]
