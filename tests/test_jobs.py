import asyncio

import pytest

from hac.jobs import JobManager
from hac.models import Job, JobStatus, TranscodeSettings


def make_job(jid="j1", status=JobStatus.QUEUED):
    return Job(id=jid, output_filename="x.opus",
               settings=TranscodeSettings(format="opus", codec="libopus", bitrate="48k"),
               status=status)


def test_add_broadcasts_update():
    jm = JobManager(max_concurrent=1)
    q = jm.subscribe()
    j = make_job()
    jm.add(j)
    event = q.get_nowait()
    assert event["event"] == "job.update"
    assert j.id in event["data"]


def test_set_progress_broadcasts_only_on_delta():
    jm = JobManager()
    q = jm.subscribe()
    j = make_job()
    jm.jobs[j.id] = j
    jm.set_status(j.id, JobStatus.RUNNING)
    q.get_nowait()  # consume status event
    jm.set_progress(j.id, 10.0)
    assert q.get_nowait()["event"] == "job.update"
    jm.set_progress(j.id, 10.1)  # below threshold → dropped
    with pytest.raises(asyncio.QueueEmpty):
        q.get_nowait()
    jm.set_progress(j.id, 11.0)
    q.get_nowait()


def test_retry_resets_state():
    jm = JobManager()
    j = make_job()
    j.status = JobStatus.FAILED
    j.error = "boom"
    j.progress = 40.0
    jm.jobs[j.id] = j
    assert jm.retry(j.id) is True
    assert j.status == JobStatus.QUEUED and j.error is None and j.progress == 0.0
    # retrying a running job is rejected
    j2 = make_job("j2", JobStatus.RUNNING)
    jm.jobs[j2.id] = j2
    assert jm.retry("j2") is False


def test_clear_finished_keeps_active():
    jm = JobManager()
    done = make_job("d", JobStatus.DONE)
    run = make_job("r", JobStatus.RUNNING)
    jm.jobs = {j.id: j for j in (done, run)}
    removed = jm.clear_finished()
    assert removed == 1 and "d" not in jm.jobs and "r" in jm.jobs


async def test_cancel_queued_job():
    """Queued jobs must be cancellable without a running proc (v1 bug fix)."""
    jm = JobManager()
    j = make_job()
    jm.add(j)
    ok = await jm.cancel(j.id)
    assert ok is True
    assert j.status == JobStatus.CANCELLED


async def test_worker_executes_job(monkeypatch):
    jm = JobManager(max_concurrent=1)

    async def fake_execute(job, mgr):
        jm.set_status(job.id, JobStatus.RUNNING)
        jm.set_progress(job.id, 50.0)
        jm.set_status(job.id, JobStatus.DONE)

    from hac import transcoder
    monkeypatch.setattr(transcoder, "execute_job", fake_execute)

    j = make_job()
    jm.add(j)
    jm.start_workers()
    for _ in range(100):
        if j.status == JobStatus.DONE:
            break
        await asyncio.sleep(0.02)
    await jm.stop_workers()
    assert j.status == JobStatus.DONE
