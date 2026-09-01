import asyncio
import logging
import os
import tempfile
import zipfile
from contextlib import asynccontextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import config, encoders, library, probe, presets, uploads
from .jobs import JobManager
from .models import DEFAULT_CODEC, Job, JobCreate, JobStatus
from .events import sse_endpoint
from .transcoder import _raise_nofile


class _SuccessOnlyFilter(logging.Filter):
    """Silence 2xx/3xx access logs (noise for bulk uploads); keep errors."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return record.args[4] >= 400
        except Exception:
            return True


def setup_logging() -> None:
    """Daily-rotating file log under data/logs, 30 days retention."""
    log_dir = config.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        log_dir / "app.log", when="midnight", backupCount=30, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "hac"):
        logging.getLogger(name).addHandler(handler)


logging.getLogger("uvicorn.access").addFilter(_SuccessOnlyFilter())

jm = JobManager(max_concurrent=config.MAX_CONCURRENT_JOBS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # raise fd soft limit -> hard limit so huge merges (thousands of inputs,
    # one fd each) don't die with "Too many open files". Children inherit it.
    # Done in-process because uvloop ignores preexec_fn in subprocess spawns.
    _raise_nofile()
    config.ensure_dirs()
    setup_logging()
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


@app.get("/api/uploads")
async def list_uploads():
    """All stored uploads (uploads-library tab) + active-task reference flags."""
    return [{"id": u.id, "name": u.name, "size": u.size, "info": u.info,
             "referenced": uploads.referenced_by_active(u.id, jm.jobs)}
            for u in uploads.all_uploads()]


class UploadsDeleteRequest(BaseModel):
    ids: list[str]


@app.delete("/api/uploads/{upload_id}")
async def delete_upload(upload_id: str):
    u = uploads.get(upload_id)
    if not u:
        raise HTTPException(404, "upload not found")
    if uploads.referenced_by_active(upload_id, jm.jobs):
        raise HTTPException(409, f"「{u.name}」正在被任务使用，不能删除")
    uploads.remove(upload_id)
    jm.broadcast("uploads.changed", {"removed": [upload_id]})
    return {"ok": True}


@app.post("/api/uploads/delete")
async def delete_uploads_batch(req: UploadsDeleteRequest):
    removed, skipped = [], []
    for uid in req.ids:
        u = uploads.get(uid)
        if not u:
            continue
        if uploads.referenced_by_active(uid, jm.jobs):
            skipped.append(u.name)
            continue
        uploads.remove(uid)
        removed.append(uid)
    if removed:
        jm.broadcast("uploads.changed", {"removed": removed})
    return {"removed": len(removed), "skipped": skipped}


@app.get("/api/probe/{upload_id}")
async def probe_upload(upload_id: str):
    u = uploads.get(upload_id)
    if not u:
        raise HTTPException(404, "upload not found")
    return u.info


# ---------- library (server-side directory import) ----------

@app.get("/api/library/roots")
async def library_roots():
    # name = 根目录 basename（面向用户显示），path 仅用于前端回传导航
    return {"roots": [{"path": str(r), "name": r.name or str(r)} for r in config.LIBRARY_ROOTS]}


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


class LibraryProbeRequest(BaseModel):
    paths: list[str]


@app.post("/api/library/probe")
async def library_probe(req: LibraryProbeRequest):
    """Batch-probe library files for metadata columns / sorting."""
    out = {}
    for path in req.paths[: config.MAX_MERGE_FILES]:
        p = Path(path)
        if not library.is_allowed(p) or not p.is_file():
            continue
        try:
            info = probe.probe(p)
            tags = info.get("tags") or {}
            out[str(p)] = {
                "title": tags.get("title"),
                "track": tags.get("track"),
                "album": tags.get("album"),
                "artist": tags.get("artist"),
                "composer": tags.get("composer"),
                "duration": info.get("duration"),
                "codec": info.get("codec"),
                "bitrate": info.get("bitrate"),
                "sample_rate": info.get("sample_rate"),
            }
        except probe.ProbeError:
            out[str(p)] = {"title": None, "track": None, "album": None,
                           "artist": None, "composer": None, "duration": None}
    return out


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
    from . import uploads
    stem = uploads.display_stem(req.source_ids[0]) or paths[0].stem
    if req.mode == "merge":
        base = (req.merge.book_title if req.merge else None) or stem
        return str(base)
    ext = req.settings.format if req.settings else "opus"
    suffix = ""
    if req.preset_id:
        p = presets.get_preset(req.preset_id)
        if p:
            suffix = p.filename_suffix
    return f"{stem}{suffix}.{ext}"


M4B_CODECS = {"aac", "libfdk_aac"}


def validate_merge_settings(settings) -> None:
    """M4B/MP4 container only supports the AAC family; mirrors UI hints."""
    codec = settings.codec or DEFAULT_CODEC[settings.format]
    if codec not in M4B_CODECS:
        raise HTTPException(
            400, f"编码器 {codec} 不兼容 M4B：仅支持 AAC 系（aac / libfdk_aac），"
                 f"Opus/MP3 等请用逐文件模式")
    if settings.profile and settings.codec != "libfdk_aac":
        raise HTTPException(400, f"profile {settings.profile} 需搭配 libfdk_aac 编码器")
    if settings.profile == "aac_he_v2" and settings.channels not in (2, None):
        raise HTTPException(400, "HE-AAC v2 需要立体声：请把声道设为 2")


@app.post("/api/jobs")
async def create_job(req: JobCreate):
    if not req.source_ids:
        raise HTTPException(400, "source_ids required")
    if req.mode == "merge" and len(req.source_ids) < 2:
        raise HTTPException(400, "merge needs at least 2 sources")
    if req.mode == "merge" and len(req.source_ids) > config.MAX_MERGE_FILES:
        raise HTTPException(
            400, f"合并文件数 {len(req.source_ids)} 超过单个任务的上限 {config.MAX_MERGE_FILES}"
                 f"（可用 --max-merge-files 或 HAC_MAX_MERGE_FILES 调整）")

    paths = [_resolve_source(s) for s in req.source_ids]

    if req.mode == "merge":
        total = sum(p.stat().st_size for p in paths)
        if total > config.MAX_MERGE_BYTES:
            used = (f"{total / (1 << 30):.2f}GB" if total >= (1 << 30)
                    else f"{total / (1 << 20):.1f}MB")
            raise HTTPException(
                400, f"本任务合并总体积 {used} 超过单个任务的上限 "
                     f"{config.MAX_MERGE_GB}GB（可用 --max-merge-gb 或 HAC_MAX_MERGE_GB 调整）")

    # preset provides the base settings; request fields act as explicit overrides
    settings = None
    if req.preset_id:
        p = presets.get_preset(req.preset_id)
        if not p:
            raise HTTPException(400, f"unknown preset: {req.preset_id}")
        if not p.effective_enabled(encoders.detect_encoders()):
            raise HTTPException(400, f"preset disabled: {p.requires_encoder} missing")
        settings = p.settings
    if req.settings is not None:
        overrides = req.settings.model_dump(exclude_none=True)
        settings = (settings or req.settings).model_copy(update=overrides)
    if settings is None:
        raise HTTPException(400, "settings or preset_id required")

    merge_opts = req.merge if req.mode == "merge" else None
    if merge_opts:
        # merge always produces an M4B regardless of the preset's format
        settings = settings.model_copy(update={"format": "m4b"})
        validate_merge_settings(settings)
        if not merge_opts.book_title:
            from . import uploads as _uploads
            merge_opts = merge_opts.model_copy(
                update={"book_title": _uploads.display_stem(req.source_ids[0])
                        or paths[0].stem})

    source_names = []
    for sid, path in zip(req.source_ids, paths):
        from . import uploads as _up
        source_names.append(Path(_up.display_stem(sid) or path.stem).name)

    job = Job(
        mode=req.mode,
        source_ids=req.source_ids,
        source_paths=paths,
        source_names=source_names,
        output_filename=req.output_filename or _default_output_name(req, paths),
        settings=settings,
        metadata=req.metadata,
        normalize=req.normalize or bool(merge_opts and getattr(merge_opts, "normalize", False)),
        merge=merge_opts,
        position=req.position,
        total=req.total,
        title_source=req.title_source,
        title_pattern=req.title_pattern,
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
