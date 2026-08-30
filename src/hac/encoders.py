import subprocess

from . import config

_cache: set[str] | None = None


def reset_cache() -> None:
    global _cache
    _cache = None


def detect_encoders(ffmpeg_path=None) -> set[str]:
    global _cache
    if _cache is not None:
        return _cache
    exe = str(ffmpeg_path or config.FFMPEG_PATH)
    if not exe:
        _cache = set()
        return _cache
    try:
        out = subprocess.run(
            [exe, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except Exception:
        _cache = set()
        return _cache
    names: set[str] = set()
    for line in out.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("Flags"):
            continue
        parts = stripped.split()
        # lines look like: " A....D libopus   libopus Opus (codec opus)"
        if len(parts) >= 2 and parts[0][0] in "AVS":
            names.add(parts[1])
    _cache = names
    return names
