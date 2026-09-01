import asyncio
import json
import time
from datetime import datetime

from . import db
from .models import ACTIVE_STATUSES, Job, JobStatus


class JobManager:
    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.jobs: dict[str, Job] = {}
        self.procs: dict[str, asyncio.subprocess.Process] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.subscribers: list[asyncio.Queue] = []
        self._workers: list[asyncio.Task] = []
        self._last_progress: dict[str, float] = {}
        self._last_db_progress: dict[str, tuple[float, float]] = {}  # (pct, ts)

    # ---- DB persistence ----
    def _persist(self, job: Job) -> None:
        try:
            db.save_job(job)
        except Exception:
            pass  # DB failure must never break the running transcode

    def restore_from_db(self) -> int:
        """Load full history from DB into memory; active -> interrupted."""
        n = 0
        for rec in db.list_job_records():
            job = db.job_record_to_job(rec)
            if job.status in ACTIVE_STATUSES:
                job.status = JobStatus.INTERRUPTED
                job.error = "服务重启，任务中断（源文件仍在可重试）"
                job.finished_at = job.finished_at or datetime.now()
                self._persist(job)
            self.jobs[job.id] = job
            n += 1
        return n

    def db_only_jobs(self) -> list[Job]:
        """History rows evicted from memory (after clear_finished)."""
        mem = set(self.jobs.keys())
        return [db.job_record_to_job(r) for r in db.list_job_records()
                if r.id not in mem]

    def delete_output(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.output_path:
            try:
                job.output_path.unlink(missing_ok=True)
            except OSError:
                pass
        job.output_deleted_at = datetime.now()
        self._persist(job)
        try:
            db.mark_output_deleted(job_id)
        except Exception:
            pass
        self.broadcast("job.update", job.model_dump(mode="json"))
        return True

    def start_workers(self) -> None:
        for _ in range(self.max_concurrent):
            self._workers.append(asyncio.create_task(self._worker()))

    async def stop_workers(self) -> None:
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

    # ---- SSE ----
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

    def broadcast(self, event: str, data) -> None:
        payload = json.dumps(data, default=str) if not isinstance(data, str) else data
        for q in self.subscribers:
            try:
                q.put_nowait({"event": event, "data": payload})
            except asyncio.QueueFull:
                pass

    def broadcast_list(self) -> None:
        self.broadcast("job.list", [j.model_dump(mode="json") for j in self.jobs.values()])

    # ---- job lifecycle ----
    def add(self, job: Job) -> None:
        self.jobs[job.id] = job
        self._persist(job)
        self.broadcast("job.update", job.model_dump(mode="json"))
        self.queue.put_nowait(job.id)

    async def _worker(self) -> None:
        while True:
            jid = await self.queue.get()
            try:
                job = self.jobs.get(jid)
                if not job or job.status != JobStatus.QUEUED:
                    continue
                async with self.semaphore:
                    if job.status != JobStatus.QUEUED:
                        continue
                    try:
                        from . import transcoder
                        await transcoder.execute_job(job, self)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        self.set_status(jid, JobStatus.FAILED, error=f"{type(e).__name__}: {e}")
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                self.queue.task_done()

    def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        job.status = status
        if error is not None:
            job.error = error
        if status == JobStatus.DONE:
            job.finished_at = datetime.now()
            job.progress = 100.0
        if status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED,
                      JobStatus.INTERRUPTED):
            self._last_db_progress.pop(job_id, None)
        self._persist(job)
        self.broadcast("job.update", job.model_dump(mode="json"))

    def set_progress(self, job_id: str, pct: float) -> None:
        job = self.jobs.get(job_id)
        if not job or job.status not in ACTIVE_STATUSES:
            return
        job.progress = min(100.0, max(0.0, pct))
        last = self._last_progress.get(job_id, -1.0)
        if abs(job.progress - last) >= 0.5 or job.progress >= 100.0:
            self._last_progress[job_id] = job.progress
            self.broadcast("job.update", job.model_dump(mode="json"))
        # DB throttle: >=5% delta or >=5s since last DB write
        last_pct, last_ts = self._last_db_progress.get(job_id, (-100.0, 0.0))
        now = time.monotonic()
        if abs(job.progress - last_pct) >= 5.0 or (now - last_ts) >= 5.0:
            self._last_db_progress[job_id] = (job.progress, now)
            self._persist(job)

    def register_proc(self, job_id: str, proc: asyncio.subprocess.Process) -> None:
        self.procs[job_id] = proc

    async def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in ACTIVE_STATUSES:
            return False
        proc = self.procs.pop(job_id, None)
        if proc and proc.returncode is None:
            from .transcoder import terminate
            await terminate(proc)
        job.status = JobStatus.CANCELLED
        job.finished_at = job.finished_at or datetime.now()
        self._persist(job)
        self.broadcast("job.update", job.model_dump(mode="json"))
        return True

    def retry(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            return False
        job.status = JobStatus.QUEUED
        job.progress = 0.0
        job.error = None
        job.verify = None
        job.finished_at = None
        self._last_progress.pop(job_id, None)
        self._last_db_progress.pop(job_id, None)
        self._persist(job)
        self.broadcast("job.update", job.model_dump(mode="json"))
        self.queue.put_nowait(job.id)
        return True

    async def cancel_all(self) -> int:
        count = 0
        for jid, job in list(self.jobs.items()):
            if await self.cancel(jid):
                count += 1
        return count

    def clear_finished(self) -> int:
        """清理产物：删除输出文件、DB 标记保留历史、内存移除条目。"""
        gone = [jid for jid, j in self.jobs.items()
                if j.status in (JobStatus.DONE, JobStatus.FAILED,
                                JobStatus.CANCELLED, JobStatus.INTERRUPTED)]
        for jid in gone:
            self.delete_output(jid)
            self.jobs.pop(jid, None)
            self._last_progress.pop(jid, None)
            self.procs.pop(jid, None)
        if gone:
            self.broadcast_list()
        return len(gone)
