import json
import subprocess
from pathlib import Path

from . import config


class ProbeError(Exception):
    pass


def probe_raw(path: Path) -> dict:
    exe = str(config.FFPROBE_PATH) if config.FFPROBE_PATH else "ffprobe"
    try:
        result = subprocess.run(
            [exe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=120, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise ProbeError(f"ffprobe failed: {e.stderr[:300]}") from e
    except Exception as e:
        raise ProbeError(f"ffprobe error: {e}") from e
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ProbeError("ffprobe returned non-JSON output") from e


def probe(path: Path) -> dict:
    data = probe_raw(path)
    fmt = data.get("format", {})
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise ProbeError("no audio stream found")
    st = streams[0]
    try:
        duration = float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    try:
        bitrate = int(fmt.get("bit_rate", 0) or 0)
    except (TypeError, ValueError):
        bitrate = 0
    try:
        sample_rate = int(st.get("sample_rate", 0) or 0)
    except (TypeError, ValueError):
        sample_rate = 0
    return {
        "duration": duration,
        "bitrate": bitrate,
        "channels": int(st.get("channels", 0) or 0),
        "sample_rate": sample_rate,
        "codec": st.get("codec_name"),
        "tags": fmt.get("tags", {}) or {},
    }


def probe_duration(path: Path) -> float | None:
    try:
        return probe(path)["duration"]
    except ProbeError:
        return None


def probe_verify(path: Path) -> dict:
    """Read back output parameters for the verify panel."""
    p = probe(path)
    size = path.stat().st_size
    return {
        "codec": p["codec"],
        "bitrate": p["bitrate"],
        "sample_rate": p["sample_rate"],
        "channels": p["channels"],
        "duration": p["duration"],
        "output_size": size,
    }
