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
        # real encoder lines: " A....D libopus   libopus Opus (codec opus)"
        # legend lines contain " = " (e.g. "A..... = Audio") — skip them
        if len(parts) < 2 or parts[0][0] not in "AVS":
            continue
        name = parts[1]
        if name == "=" or not name.replace("_", "").replace("-", "").isalnum():
            continue
        names.add(name)
    _cache = names
    return names
