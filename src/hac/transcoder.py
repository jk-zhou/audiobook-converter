import asyncio
import signal
from pathlib import Path

from . import config, metadata, probe
from .models import COVER_CAPABLE, COVER_REENCODE, DEFAULT_CODEC, Job, JobStatus, TranscodeSettings

LOUDNORM = "loudnorm=I=-20:TP=-3:LRA=11"


def build_ffmpeg_args(
    src: Path, dst: Path, s: TranscodeSettings, normalize: bool = False,
) -> list[str]:
    codec = s.codec or DEFAULT_CODEC[s.format]
    args = [str(config.FFMPEG_PATH), "-y", "-hide_banner", "-nostdin",
            "-i", str(src), "-map", "0:a"]

    # cover art passthrough for containers that support attached-pic streams
    if s.format in COVER_CAPABLE:
        args += ["-map", "0:v?"]
        args += ["-c:v", "mjpeg" if s.format in COVER_REENCODE else "copy"]
        args += ["-disposition:v", "attached_pic"]

    args += ["-c:a", codec]
    if s.profile:
        args += ["-profile:a", s.profile]

    # bitrate / VBR are mutually exclusive (fixes v1 double -vbr bug)
    if s.bitrate:
        args += ["-b:a", s.bitrate]
    elif s.quality is not None and codec == "libfdk_aac":
        args += ["-vbr", str(s.quality)]

    if s.samplerate:
        args += ["-ar", str(s.samplerate)]
    if s.channels:
        args += ["-ac", str(s.channels)]
    if s.compression_level is not None and codec == "libopus":
        args += ["-compression_level", str(s.compression_level)]

    args += ["-map_metadata", "0"]
    if normalize:
        args += ["-af", LOUDNORM]
    if s.extra_args:
        args += list(s.extra_args)
    args += ["-progress", "pipe:1", "-stats_period", "0.05", "-nostats", str(dst)]
    return args


def calc_progress(time_us: int, total_duration_sec: float | None) -> float:
    if not total_duration_sec:
        return 0.0
    pct = (time_us / 1_000_000) / total_duration_sec * 100
    return min(100.0, max(0.0, pct))


async def parse_progress(stream) -> dict:
    """Parse `ffmpeg -progress pipe:1` key=value blocks (\r/\n separated)."""
    buf = b""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf or b"\r" in buf:
            idx_n, idx_r = buf.find(b"\n"), buf.find(b"\r")
            if idx_n == -1:
                idx = idx_r
            elif idx_r == -1:
                idx = idx_n
            else:
                idx = min(idx_n, idx_r)
            line = buf[:idx].strip()
            buf = buf[idx + 1:]
            if not line:
                continue
            text = line.decode("utf-8", errors="ignore")
            if text.startswith("out_time_us="):
                try:
                    yield {"time_us": int(text.split("=", 1)[1])}
                except ValueError:
                    pass
            elif text.startswith("out_time_ms="):
                # ffmpeg quirk: out_time_ms is actually microseconds
                try:
                    yield {"time_us": int(text.split("=", 1)[1])}
                except ValueError:
                    pass
            elif text.startswith("progress="):
                yield {"done": text.split("=", 1)[1].strip() == "end"}
            elif text.startswith("time="):
                yield {"stderr_time": text.split("=", 1)[1]}


async def run_ffmpeg(args: list[str], register_proc=None, on_progress=None) -> tuple[int, str]:
    """Run ffmpeg; drain stderr concurrently; report progress. Returns (rc, stderr_tail)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if register_proc:
        register_proc(proc)

    err_tail = b""

    async def drain_err() -> None:
        nonlocal err_tail
        while chunk := await proc.stderr.read(4096):
            err_tail = (err_tail + chunk)[-2000:]

    err_task = asyncio.create_task(drain_err())
    total_us = 0
    async for update in parse_progress(proc.stdout):
        if update.get("done"):
            break
        if "time_us" in update:
            total_us = update["time_us"]
            if on_progress:
                on_progress(total_us)
    rc = await proc.wait()
    await err_task
    return rc, err_tail.decode("utf-8", errors="ignore")


async def terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (ProcessLookupError, asyncio.TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def output_filename(job: Job) -> str:
    from .uploads import sanitize_filename
    name = sanitize_filename(job.output_filename)
    ext = job.settings.format
    if not name.lower().endswith(f".{ext}"):
        name = f"{name}.{ext}"
    return name


async def execute_single(job: Job, mgr) -> None:
    """Single-file transcode pipeline: ffmpeg → tags → outputs → verify."""
    mgr.set_status(job.id, JobStatus.RUNNING)
    src = job.source_paths[0]
    try:
        dur = probe.probe_duration(src)
    except Exception:
        dur = None
    job.total_duration_sec = dur

    work_dst = config.WORK_DIR / f"{job.id}.{job.settings.format}"
    args = build_ffmpeg_args(src, work_dst, job.settings, normalize=job.normalize)
    rc, err_tail = await run_ffmpeg(
        args,
        register_proc=lambda p: mgr.register_proc(job.id, p),
        on_progress=lambda us: mgr.set_progress(
            job.id, calc_progress(us, job.total_duration_sec)),
    )
    if job.status == JobStatus.CANCELLED:
        work_dst.unlink(missing_ok=True)
        return
    if rc != 0 or not work_dst.exists():
        work_dst.unlink(missing_ok=True)
        mgr.set_status(job.id, JobStatus.FAILED,
                       error=(err_tail or f"ffmpeg exit {rc}")[-500:])
        return

    mgr.set_status(job.id, JobStatus.TAGGING)
    try:
        metadata.write_tags(work_dst, job.metadata)
    except Exception as e:
        mgr.set_status(job.id, JobStatus.FAILED, error=f"metadata write: {e}")
        return

    final = config.OUTPUT_DIR / f"{job.id}_{output_filename(job)}"
    work_dst.rename(final)
    job.output_path = final
    mgr.set_progress(job.id, 100.0)
    _finish_with_verify(job, mgr)
    mgr.set_status(job.id, JobStatus.DONE)


def _finish_with_verify(job: Job, mgr) -> None:
    try:
        v = probe.probe_verify(job.output_path)
        source_size = sum(p.stat().st_size for p in job.source_paths if p.exists())
        v["source_size"] = source_size
        if source_size and v.get("output_size"):
            v["savings_pct"] = round((1 - v["output_size"] / source_size) * 100, 1)
        job.verify = v
    except Exception:
        pass


async def execute_job(job: Job, mgr) -> None:
    if job.mode == "merge":
        from . import merger
        await merger.execute_merge(job, mgr)
    else:
        await execute_single(job, mgr)
