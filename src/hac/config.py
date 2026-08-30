import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("HAC_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
WORK_DIR = DATA_DIR / "work"
OUTPUT_DIR = DATA_DIR / "outputs"
VENDOR_BIN = BASE_DIR / "vendor" / "bin"

MAX_CONCURRENT_JOBS = int(os.getenv("HAC_MAX_CONCURRENT", "2"))
MAX_UPLOAD_SIZE_MB = int(os.getenv("HAC_MAX_UPLOAD_MB", "500"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
MAX_MERGE_INPUTS = 500
UPLOAD_CHUNK = 1024 * 1024


def _parse_roots() -> list[Path]:
    raw = os.getenv("HAC_LIBRARY_ROOTS", "")
    roots = [Path(p).expanduser().resolve() for p in raw.split(":") if p.strip()]
    if not roots:
        roots = [DATA_DIR / "library"]
    return roots


def ensure_dirs() -> None:
    for d in (UPLOAD_DIR, WORK_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for r in LIBRARY_ROOTS:
        r.mkdir(parents=True, exist_ok=True)


def resolve_binary(name: str, env_key: str) -> Path | None:
    p = os.getenv(env_key)
    if p and Path(p).expanduser().exists():
        return Path(p).expanduser().resolve()
    vendor = VENDOR_BIN / name
    if vendor.exists():
        return vendor
    which = shutil.which(name)
    return Path(which) if which else None


FFMPEG_PATH = resolve_binary("ffmpeg", "HAC_FFMPEG_PATH")
FFPROBE_PATH = resolve_binary("ffprobe", "HAC_FFPROBE_PATH")
LIBRARY_ROOTS = _parse_roots()
