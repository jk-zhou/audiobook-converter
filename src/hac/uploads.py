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


def display_stem(source_id: str) -> str | None:
    """User-facing filename stem for a source id (never leaks the internal
    '{upload_id}_' storage prefix). Library files use their own path."""
    if source_id.startswith("lib:"):
        return Path(source_id[4:]).stem
    u = _store.get(source_id)
    if u:
        return Path(u.name).stem
    return None


def referenced_by_active(source_id: str, jobs: dict) -> bool:
    """True if any QUEUED/RUNNING/TAGGING/MERGING job still consumes this id."""
    from .models import ACTIVE_STATUSES
    return any(source_id in j.source_ids
               for j in jobs.values() if j.status in ACTIVE_STATUSES)


def all_uploads() -> list[Upload]:
    return list(_store.values())


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


def remove(upload_id: str, delete_file: bool = True) -> bool:
    u = _store.pop(upload_id, None)
    if not u:
        return False
    if delete_file:
        u.path.unlink(missing_ok=True)
    return True
