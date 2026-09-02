"""HTTP Range streaming for playback (uploads / outputs / library files)."""
import json
import re
from pathlib import Path

from starlette.responses import Response, StreamingResponse

from . import config, probe
from .config import OUTPUT_DIR

CHUNK = 64 * 1024

MIME = {
    ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg", ".opus": "audio/ogg",
    ".flac": "audio/flac", ".wav": "audio/wav",
    ".aac": "audio/aac", ".wma": "audio/x-ms-wma",
    ".aiff": "audio/aiff", ".mka": "audio/x-matroska",
}


def mime_for(path: Path) -> str:
    return MIME.get(Path(path).suffix.lower(), "application/octet-stream")


def parse_range(header: str | None, size: int):
    """Return (start, end) inclusive, None (no/empty Range header), or
    "invalid" (malformed/unsatisfiable -> respond 416)."""
    if not header:
        return None
    if not header.startswith("bytes="):
        return "invalid"   # present but malformed (e.g. "wibble")
    spec = header[len("bytes="):].strip()
    if "," in spec:
        spec = spec.split(",", 1)[0].strip()   # only first range supported
    if spec == "":
        return None                             # bare "bytes=" -> no range
    m = re.match(r"^(\d*)-(\d*)$", spec)
    if not m or (not m.group(1) and not m.group(2)):
        return "invalid"
    if m.group(1) == "":
        # suffix form: last N bytes
        n = int(m.group(2))
        if n == 0 or size == 0:
            return "invalid"
        start = max(0, size - n)
        return (start, size - 1)
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else size - 1
    if start >= size or start > end:
        return "invalid"
    return (start, min(end, size - 1))


def ranged_response_for_request(path: Path, range_header: str | None,
                                mime: str | None = None) -> Response:
    size = Path(path).stat().st_size
    mime = mime or mime_for(path)
    rng = parse_range(range_header, size)
    if rng == "invalid":
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    def _resp(start: int, end: int, status: int) -> StreamingResponse:
        def gen():
            with Path(path).open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers = {"Accept-Ranges": "bytes",
                   "Content-Length": str(end - start + 1)}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(gen(), status_code=status,
                                 media_type=mime, headers=headers)

    if rng is None:
        return _resp(0, size - 1, 200)
    start, end = rng
    return _resp(start, end, 206)


def chapters_for(path: Path) -> list[dict]:
    """Chapter list via ffprobe; [] when the container has none."""
    try:
        data = probe.probe_raw(Path(path))
    except probe.ProbeError:
        return []
    out = []
    for ch in data.get("chapters", []):
        out.append({
            "start": float(ch.get("start_time", 0) or 0),
            "end": float(ch.get("end_time", 0) or 0),
            "title": (ch.get("tags") or {}).get("title") or "",
        })
    return out


def info_payload(path: Path) -> dict:
    p = probe.probe(Path(path))
    return {
        "duration": p.get("duration"),
        "codec": p.get("codec"),
        "bitrate": p.get("bitrate"),
        "sample_rate": p.get("sample_rate"),
        "channels": p.get("channels"),
        "chapters": chapters_for(path),
    }
