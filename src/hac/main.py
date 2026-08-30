import asyncio
import os
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import config, encoders, library, probe, presets, uploads
from .jobs import JobManager
from .models import DEFAULT_CODEC, Job, JobCreate, JobStatus
from .events import sse_endpoint

jm = JobManager(max_concurrent=config.MAX_CONCURRENT_JOBS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    encoders.reset_cache()
    jm.start_workers()
    yield
    await jm.stop_workers()


app = FastAPI(title="Audiobook Converter", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# ---------- uploads ----------

@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        u = await uploads.save_stream(f)
        results.append({"id": u.id, "name": u.name, "size": u.size, "info": u.info})
    return {"uploads": results}


@app.post("/api/upload/cover")
async def upload_cover(cover: UploadFile = File(...)):
    u = uploads.save_cover(cover)
    return {"id": u.id, "name": u.name}


@app.get("/api/probe/{upload_id}")
async def probe_upload(upload_id: str):
    u = uploads.get(upload_id)
    if not u:
        raise HTTPException(404, "upload not found")
    return u.info


# ---------- library (server-side directory import) ----------

@app.get("/api/library/roots")
async def library_roots():
    return {"roots": [str(r) for r in config.LIBRARY_ROOTS]}


@app.get("/api/library/list")
async def library_list(path: str = ""):
    try:
        return library.list_dir(path)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except NotADirectoryError as e:
        raise HTTPException(400, str(e))


# ---------- presets / health ----------

@app.get("/api/presets")
async def list_presets():
    return presets.presets_payload(encoders.detect_encoders())


@app.get("/api/health")
async def health():
    ff = config.FFMPEG_PATH
    enc = encoders.detect_encoders()
    enabled = sum(1 for p in presets.PRESETS if p.effective_enabled(enc))
    return {
        "status": "ok" if ff else "error: ffmpeg not found",
        "ffmpeg": str(ff) if ff else None,
        "ffprobe_ok": bool(config.FFPROBE_PATH),
        "encoders": sorted(enc),
        "presets_enabled": enabled,
        "presets_disabled": len(presets.PRESETS) - enabled,
    }


# ---------- jobs ----------

def _resolve_source(sid: str) -> Path:
    if sid.startswith("lib:"):
        p = Path(sid[4:])
        if not library.is_allowed(p):
            raise HTTPException(403, f"path outside library roots: {p}")
        if not p.is_file():
            raise HTTPException(400, f"not a file: {p}")
        return p
    u = uploads.get(sid)
    if not u:
        raise HTTPException(404, f"source not found: {sid}")
    return u.path


def _default_output_name(req: JobCreate, paths: list[Path]) -> str:
    if req.mode == "merge":
        base = (req.merge.book_title if req.merge else None) or paths[0].stem
        return str(base)
    ext = req.settings.format if req.settings else "opus"
    suffix = ""
    if req.preset_id:
        p = presets.get_preset(req.preset_id)
        if p:
            suffix = p.filename_suffix
    return f"{paths[0].stem}{suffix}.{ext}"


@app.post("/api/jobs")
async def create_job(req: JobCreate):
    if not req.source_ids:
        raise HTTPException(400, "source_ids required")
    if req.mode == "merge" and len(req.source_ids) < 2:
        raise HTTPException(400, "merge needs at least 2 sources")
    if req.mode == "merge" and len(req.source_ids) > config.MAX_MERGE_INPUTS:
        raise HTTPException(400, f"merge limited to {config.MAX_MERGE_INPUTS} sources")

    paths = [_resolve_source(s) for s in req.source_ids]

    settings = req.settings
    if settings is None and req.preset_id:
        p = presets.get_preset(req.preset_id)
        if not p:
            raise HTTPException(400, f"unknown preset: {req.preset_id}")
        enc = encoders.detect_encoders()
        if not p.effective_enabled(enc):
            raise HTTPException(400, f"preset disabled: {p.requires_encoder} missing")
        settings = p.settings
    if settings is None:
        raise HTTPException(400, "settings or preset_id required")

    merge_opts = req.merge if req.mode == "merge" else None
    if merge_opts and not merge_opts.book_title:
        merge_opts = merge_opts.model_copy(update={"book_title": paths[0].stem})

    job = Job(
        mode=req.mode,
        source_ids=req.source_ids,
        source_paths=paths,
        output_filename=req.output_filename or _default_output_name(req, paths),
        settings=settings,
        metadata=req.metadata,
        normalize=req.normalize or bool(merge_opts and getattr(merge_opts, "normalize", False)),
        merge=merge_opts,
    )
    jm.add(job)
    return {"job_id": job.id}


@app.get("/api/jobs")
async def list_jobs():
    return [j.model_dump(mode="json") for j in jm.jobs.values()]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = jm.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.model_dump(mode="json")


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    if not jm.retry(job_id):
        raise HTTPException(400, "job is not retryable")
    return {"ok": True}


@app.post("/api/jobs/cancel-all")
async def cancel_all_jobs():
    return {"ok": True, "cancelled": await jm.cancel_all()}


@app.post("/api/jobs/clear-finished")
async def clear_finished_jobs():
    return {"ok": True, "removed": jm.clear_finished()}


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str):
    if job_id not in jm.jobs:
        raise HTTPException(404, "job not found")
    await jm.cancel(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str):
    job = jm.jobs.get(job_id)
    if not job or not job.output_path or not job.output_path.exists():
        raise HTTPException(404, "output not available")
    if job.status != JobStatus.DONE:
        raise HTTPException(404, "output not available")
    return FileResponse(
        job.output_path,
        filename=job.output_path.name.split("_", 1)[-1],
        media_type="application/octet-stream",
    )


@app.get("/api/download/zip")
async def download_zip(ids: str):
    job_ids = [s.strip() for s in ids.split(",") if s.strip()]
    entries = []
    for jid in job_ids:
        job = jm.jobs.get(jid)
        if job and job.status == JobStatus.DONE and job.output_path and job.output_path.exists():
            entries.append(job)
    if not entries:
        raise HTTPException(404, "no completed jobs to zip")
    tmp = tempfile.NamedTemporaryFile(
        suffix=".zip", delete=False, dir=str(config.DATA_DIR), prefix="hac_zip_")
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as zf:
        for job in entries:
            arcname = f"{job.id}_{job.output_filename}"
            zf.write(job.output_path, arcname)
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename="converted.zip",
        background=BackgroundTask(os.unlink, tmp.name),
    )


@app.get("/api/events")
async def events():
    return sse_endpoint(jm)
