import asyncio
import json

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
                    if job.status == JobStatus.DONE:
                        # auto-clean consumed uploads (files stay in outputs/)
                        from . import uploads as uploads_mod
                        cleaned = uploads_mod.cleanup_for_job(job, self.jobs)
                        if cleaned:
                            self.broadcast("uploads.changed", {"removed": cleaned})
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
            from datetime import datetime
            job.finished_at = datetime.now()
            job.progress = 100.0
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
        job.finished_at = job.finished_at or __import__("datetime").datetime.now()
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
        gone = [jid for jid, j in self.jobs.items()
                if j.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)]
        for jid in gone:
            self.jobs.pop(jid, None)
            self._last_progress.pop(jid, None)
            self.procs.pop(jid, None)
        if gone:
            self.broadcast_list()
        return len(gone)
