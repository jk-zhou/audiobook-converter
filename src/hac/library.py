from pathlib import Path

from . import config

AUDIO_EXTS = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg", ".opus", ".wav", ".wma", ".aiff", ".mka"}


def is_allowed(path: Path, roots: list[Path] | None = None) -> bool:
    roots = roots if roots is not None else config.LIBRARY_ROOTS
    try:
        rp = path.resolve()
    except (OSError, ValueError):
        return False
    return any(rp == r or rp.is_relative_to(r) for r in roots)


def list_dir(path: str = "", roots: list[Path] | None = None) -> dict:
    roots = roots if roots is not None else config.LIBRARY_ROOTS
    target = Path(path).expanduser() if path else roots[0]
    try:
        target = target.resolve()
    except (OSError, ValueError):
        raise PermissionError(f"path outside library roots: {path}")
    if not is_allowed(target, roots):
        raise PermissionError(f"path outside library roots: {path}")
    if not target.exists():
        raise FileNotFoundError(f"path does not exist: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"not a directory: {target}")
    dirs, files = [], []
    try:
        entries = sorted(target.iterdir(), key=lambda e: e.name.lower())
    except PermissionError as e:
        raise PermissionError(f"permission denied: {target}") from e
    for e in entries:
        if e.is_dir():
            dirs.append({"name": e.name, "path": str(e)})
        elif e.is_file() and e.suffix.lower() in AUDIO_EXTS:
            files.append({
                "id": f"lib:{e}",
                "name": e.name,
                "size": e.stat().st_size,
            })
    return {"path": str(target), "dirs": dirs, "files": files}
