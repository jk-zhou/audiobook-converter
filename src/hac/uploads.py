import re
from pathlib import Path

from fastapi import HTTPException, UploadFile

from . import config, probe
from .models import Upload

_store: dict[str, Upload] = {}

_SANITIZE_RE = re.compile(r"[\\/:*?\"<>|\0]")


def sanitize_filename(name: str) -> str:
    name = _SANITIZE_RE.sub("-", name or "audio")
    return name.strip(". ") or "audio"


def get(upload_id: str) -> Upload | None:
    return _store.get(upload_id)


def all_uploads() -> list[Upload]:
    return list(_store.values())


def remove(upload_id: str, delete_file: bool = True) -> bool:
    u = _store.pop(upload_id, None)
    if not u:
        return False
    if delete_file:
        u.path.unlink(missing_ok=True)
    return True


def cleanup_for_job(job, all_jobs: dict) -> list[str]:
    """Delete source uploads after a job finished, unless another job still
    references them. Library files (lib:*) are never touched."""
    cleaned = []
    for sid in job.source_ids:
        if sid.startswith("lib:") or not _store.get(sid):
            continue
        referenced_elsewhere = any(
            sid in j.source_ids for jid, j in all_jobs.items()
            if jid != job.id and j is not job)
        if referenced_elsewhere:
            continue
        if remove(sid):
            cleaned.append(sid)
    # merge cover uploads are transient too
    if job.mode == "merge" and job.merge and job.merge.cover_upload_id:
        cover_id = job.merge.cover_upload_id
        if cover_id in _store and not any(
                cover_id in j.source_ids for jid, j in all_jobs.items() if jid != job.id):
            remove(cover_id)
    return cleaned


async def save_stream(f: UploadFile) -> Upload:
    """Chunked streaming save with size cap (fixes v1 full-in-memory bug)."""
    if config.FFMPEG_PATH is None:
        raise HTTPException(500, "ffmpeg binary not found on server")
    name = sanitize_filename(f.filename or "audio")
    upload_id = Upload(name=name, path=Path("."), size=0).id
    dst = config.UPLOAD_DIR / f"{upload_id}_{name}"
    size = 0
    try:
        with dst.open("wb") as out:
            while chunk := await f.read(config.UPLOAD_CHUNK):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"{name} exceeds {config.MAX_UPLOAD_SIZE_MB}MB limit")
                out.write(chunk)
    except HTTPException:
        dst.unlink(missing_ok=True)
        raise
    except Exception as e:
        dst.unlink(missing_ok=True)
        raise HTTPException(500, f"failed to write upload: {e}") from e
    if size == 0:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, f"{name} is empty")
    try:
        info = probe.probe(dst)
    except probe.ProbeError as e:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, f"{name} is not a decodable audio file: {e}") from e
    u = Upload(id=upload_id, name=name, path=dst, size=size, info=info)
    _store[u.id] = u
    return u


def save_cover(f: UploadFile) -> Upload:
    """Save an image (cover art); stored like uploads but without audio probe."""
    name = sanitize_filename(f.filename or "cover.jpg")
    upload_id = Upload(name=name, path=Path("."), size=0).id
    dst = config.UPLOAD_DIR / f"{upload_id}_{name}"
    size = 0
    with dst.open("wb") as out:
        while chunk := f.file.read(config.UPLOAD_CHUNK):
            size += len(chunk)
            if size > 20 * 1024 * 1024:
                dst.unlink(missing_ok=True)
                raise HTTPException(413, f"{name} exceeds 20MB limit")
            out.write(chunk)
    if size == 0:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, f"{name} is empty")
    u = Upload(id=upload_id, name=name, path=dst, size=size, info={"kind": "cover"})
    _store[u.id] = u
    return u
