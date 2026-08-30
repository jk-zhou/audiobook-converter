import asyncio
from pathlib import Path

from . import config, metadata, probe, transcoder
from .models import Job, JobStatus

BITRATE = "64k"
SAMPLERATE = 24000


def _escape_ffmetadata(value: str) -> str:
    for ch in ("\\", "=", ";", "#"):
        value = value.replace(ch, f"\\{ch}")
    return value.replace("\n", " ").replace("\r", " ")


def build_chapter_meta(
    durations: list[float],
    titles: list[str],
    book_title: str | None = None,
    book_artist: str | None = None,
) -> str:
    """Build ffmetadata text with cumulative chapter times (ms)."""
    lines = [";FFMETADATA1"]
    if book_title:
        lines.append(f"title={_escape_ffmetadata(book_title)}")
    if book_artist:
        lines.append(f"artist={_escape_ffmetadata(book_artist)}")
    t = 0.0
    for d, title in zip(durations, titles):
        start_ms = round(t * 1000)
        t += d
        end_ms = round(t * 1000)
        lines += [
            "",
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start_ms}",
            f"END={end_ms}",
            f"title={_escape_ffmetadata(title)}",
        ]
    return "\n".join(lines) + "\n"


def chapter_titles(sources: list[Path]) -> list[str]:
    titles = []
    for s in sources:
        try:
            tags = metadata.read_source_tags(s)
        except Exception:
            tags = {}
        titles.append(tags.get("title") or s.stem)
    return titles


def build_merge_args(
    sources: list[Path],
    cover: Path | None,
    meta_file: Path,
    dst: Path,
    normalize: bool = False,
) -> list[str]:
    n = len(sources)
    args = [str(config.FFMPEG_PATH), "-y", "-hide_banner", "-nostdin"]
    for s in sources:
        args += ["-i", str(s)]
    if cover:
        args += ["-i", str(cover)]
    meta_idx = n + (1 if cover else 0)
    args += ["-i", str(meta_file)]

    fc = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[c]"
    if normalize:
        fc += f";[c]{transcoder.LOUDNORM}[outa]"
        out_label = "[outa]"
    else:
        out_label = "[c]"
    args += ["-filter_complex", fc, "-map", out_label]

    if cover:
        args += ["-map", f"{n}:v", "-c:v", "mjpeg",
                 "-disposition:v:0", "attached_pic"]

    args += ["-c:a", "aac", "-b:a", BITRATE, "-ar", str(SAMPLERATE), "-ac", "1"]
    args += ["-map_metadata", str(meta_idx), "-map_chapters", str(meta_idx)]
    args += ["-movflags", "+faststart", "-f", "mp4",
             "-progress", "pipe:1", "-nostats", str(dst)]
    return args


def _resolve_cover(job: Job, work: Path) -> Path | None:
    if job.merge and job.merge.cover_upload_id:
        from . import uploads
        u = uploads.get(job.merge.cover_upload_id)
        if u and u.path.exists():
            return u.path
    try:
        got = metadata.extract_cover(job.source_paths[0])
    except Exception:
        got = None
    if got:
        data, ext = got
        p = work / f"{job.id}_cover{ext}"
        p.write_bytes(data)
        return p
    return None


async def execute_merge(job: Job, mgr) -> None:
    """Merge N sources into one .m4b with embedded chapters + cover."""
    mgr.set_status(job.id, JobStatus.MERGING)
    sources = job.source_paths

    durations = []
    for s in sources:
        d = probe.probe_duration(s)
        if d is None:
            mgr.set_status(job.id, JobStatus.FAILED,
                           error=f"cannot probe input: {s.name}")
            return
        durations.append(d)
    job.total_duration_sec = sum(durations)

    work = config.WORK_DIR
    meta_file = work / f"{job.id}_chapters.txt"
    book = job.merge or None
    meta_file.write_text(
        build_chapter_meta(
            durations, chapter_titles(sources),
            book_title=book.book_title if book else None,
            book_artist=book.book_artist if book else None,
        ),
        encoding="utf-8",
    )
    cover = _resolve_cover(job, work)

    work_dst = work / f"{job.id}.m4b"
    args = build_merge_args(sources, cover, meta_file, work_dst, normalize=job.normalize)
    rc, err_tail = await transcoder.run_ffmpeg(
        args,
        register_proc=lambda p: mgr.register_proc(job.id, p),
        on_progress=lambda us: mgr.set_progress(
            job.id, transcoder.calc_progress(us, job.total_duration_sec)),
    )
    meta_file.unlink(missing_ok=True)
    if cover and cover.parent == work:
        cover.unlink(missing_ok=True)

    if job.status == JobStatus.CANCELLED:
        work_dst.unlink(missing_ok=True)
        return
    if rc != 0 or not work_dst.exists():
        work_dst.unlink(missing_ok=True)
        mgr.set_status(job.id, JobStatus.FAILED,
                       error=(err_tail or f"ffmpeg exit {rc}")[-500:])
        return

    final = config.OUTPUT_DIR / f"{job.id}_{transcoder.output_filename(job)}"
    work_dst.rename(final)
    job.output_path = final
    mgr.set_progress(job.id, 100.0)
    transcoder._finish_with_verify(job, mgr)
    mgr.set_status(job.id, JobStatus.DONE)
