import asyncio
import os
from pathlib import Path

from . import config, metadata, probe, transcoder
from .models import Job, JobStatus, TranscodeSettings

MERGE_CHUNK = int(os.getenv("HAC_MERGE_CHUNK", "500"))   # inputs per ffmpeg pass;
# caps peak RSS/fd usage for huge merges (tunable for testing)


def _escape_ffmetadata(value: str) -> str:
    for ch in ("\\", "=", ";", "#"):
        value = value.replace(ch, f"\\{ch}")
    return value.replace("\n", " ").replace("\r", " ")


def build_chapter_meta(
    durations: list[float],
    titles: list[str],
    book_title: str | None = None,
    book_artist: str | None = None,
    composer: str | None = None,
) -> str:
    """Build ffmetadata text with cumulative chapter times (ms)."""
    lines = [";FFMETADATA1"]
    if book_title:
        lines.append(f"title={_escape_ffmetadata(book_title)}")
    if book_artist:
        lines.append(f"artist={_escape_ffmetadata(book_artist)}")
    if composer:
        lines.append(f"composer={_escape_ffmetadata(composer)}")
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


def build_chunk_args(
    sources: list[Path], dst: Path, settings: TranscodeSettings, normalize: bool = False,
) -> list[str]:
    """Phase-1 pass: encode one chunk to the target settings (audio only)."""
    n = len(sources)
    args = [str(config.FFMPEG_PATH), "-y", "-hide_banner", "-nostdin"]
    for s in sources:
        args += ["-i", str(s)]
    fc = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[c]"
    if normalize:
        fc += f";[c]{transcoder.LOUDNORM}[outa]"
        out_label = "[outa]"
    else:
        out_label = "[c]"
    args += ["-filter_complex", fc, "-map", out_label]
    args += transcoder.audio_encode_args(settings)
    args += ["-progress", "pipe:1", "-stats_period", "0.05", "-nostats", str(dst)]
    return args


def build_concat_list(parts: list[Path], list_file: Path) -> None:
    lines = [f"file '{p.resolve()}'".replace("'", "'\\''") for p in parts]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_finalize_args(
    parts: list[Path],
    list_file: Path,
    meta_file: Path,
    cover: Path | None,
    dst: Path,
) -> list[str]:
    """Phase-2 pass: stream-copy concat of the encoded parts + chapters + cover."""
    args = [str(config.FFMPEG_PATH), "-y", "-hide_banner", "-nostdin",
            "-f", "concat", "-safe", "0", "-i", str(list_file)]
    meta_idx = 1
    if cover:
        args += ["-i", str(cover)]
        meta_idx = 2
    args += ["-i", str(meta_file)]
    args += ["-map", "0:a"]
    if cover:
        args += ["-map", f"{meta_idx - 1}:v", "-c:v", "mjpeg",
                 "-disposition:v:0", "attached_pic"]
    args += ["-c:a", "copy"]
    args += ["-map_metadata", str(meta_idx), "-map_chapters", str(meta_idx)]
    args += ["-movflags", "+faststart", "-f", "mp4",
             "-progress", "pipe:1", "-stats_period", "0.05", "-nostats", str(dst)]
    return args


def chapter_titles(job: Job) -> list[str]:
    """Chapter title per source: title tag → clean filename stem (no internal
    upload-id prefix)."""
    from . import uploads
    titles = []
    for i, s in enumerate(job.source_paths):
        try:
            tags = metadata.read_source_tags(s)
        except Exception:
            tags = {}
        stem = None
        if i < len(job.source_ids):
            stem = uploads.display_stem(job.source_ids[i])
        titles.append(tags.get("title") or stem or s.stem)
    return titles


def build_merge_args(
    sources: list[Path],
    cover: Path | None,
    meta_file: Path,
    dst: Path,
    settings: TranscodeSettings,
    normalize: bool = False,
) -> list[str]:
    """Merge args adopt the user's audio encoding settings (AAC family only —
    validated upstream); only the container format is forced to m4b."""
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

    args += transcoder.audio_encode_args(settings)
    args += ["-map_metadata", str(meta_idx), "-map_chapters", str(meta_idx)]
    args += ["-movflags", "+faststart", "-f", "mp4",
             "-progress", "pipe:1", "-stats_period", "0.05", "-nostats", str(dst)]
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


def build_chunk_args(
    sources: list[Path], dst: Path, settings: TranscodeSettings, normalize: bool = False,
) -> list[str]:
    """Phase-1 pass: encode one chunk to the target settings (audio only)."""
    n = len(sources)
    args = [str(config.FFMPEG_PATH), "-y", "-hide_banner", "-nostdin"]
    for s in sources:
        args += ["-i", str(s)]
    fc = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[c]"
    if normalize:
        fc += f";[c]{transcoder.LOUDNORM}[outa]"
        out_label = "[outa]"
    else:
        out_label = "[c]"
    args += ["-filter_complex", fc, "-map", out_label]
    args += transcoder.audio_encode_args(settings)
    args += ["-progress", "pipe:1", "-stats_period", "0.05", "-nostats", str(dst)]
    return args


def build_concat_list(parts: list[Path], list_file: Path) -> None:
    lines = []
    for p in parts:
        rp = str(p.resolve()).replace("'", "'\\''")
        lines.append(f"file '{rp}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_finalize_args(
    parts: list[Path],
    list_file: Path,
    meta_file: Path,
    cover: Path | None,
    dst: Path,
) -> list[str]:
    """Phase-2 pass: stream-copy concat of encoded parts + chapters + cover."""
    args = [str(config.FFMPEG_PATH), "-y", "-hide_banner", "-nostdin",
            "-f", "concat", "-safe", "0", "-i", str(list_file)]
    meta_idx = 1
    if cover:
        args += ["-i", str(cover)]
        meta_idx = 2
    args += ["-i", str(meta_file)]
    args += ["-map", "0:a"]
    if cover:
        args += ["-map", f"{meta_idx - 1}:v", "-c:v", "mjpeg",
                 "-disposition:v:0", "attached_pic"]
    args += ["-c:a", "copy"]
    args += ["-map_metadata", str(meta_idx), "-map_chapters", str(meta_idx)]
    args += ["-movflags", "+faststart", "-f", "mp4",
             "-progress", "pipe:1", "-stats_period", "0.05", "-nostats", str(dst)]
    return args


def build_chapter_meta_chunked(
    part_durations: list[float],
    chunk_sizes: list[int],
    source_durations: list[float],
    titles: list[str],
    book_title: str | None = None,
    book_artist: str | None = None,
    composer: str | None = None,
) -> str:
    """Chapters for the chunked path: part boundaries use ACTUAL encoded part
    durations; in-part offsets accumulate source durations."""
    lines = [";FFMETADATA1"]
    if book_title:
        lines.append(f"title={_escape_ffmetadata(book_title)}")
    if book_artist:
        lines.append(f"artist={_escape_ffmetadata(book_artist)}")
    if composer:
        lines.append(f"composer={_escape_ffmetadata(composer)}")
    src = 0
    part_start = 0.0
    for pd, size in zip(part_durations, chunk_sizes):
        t = part_start
        for _ in range(size):
            start_ms = round(t * 1000)
            t += source_durations[src]
            lines += ["", "[CHAPTER]", "TIMEBASE=1/1000",
                      f"START={start_ms}", f"END={round(t * 1000)}",
                      f"title={_escape_ffmetadata(titles[src])}"]
            src += 1
        part_start += pd
    return "\n".join(lines) + "\n"


def _chunks(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


async def _probe_many(paths: list[Path]) -> list:
    sem = asyncio.Semaphore(16)

    async def one(p):
        async with sem:
            return await asyncio.to_thread(probe.probe_duration, p)

    return list(await asyncio.gather(*[one(p) for p in paths]))


async def execute_merge(job: Job, mgr) -> None:
    """Merge N sources into one .m4b with embedded chapters + cover.

    <= MERGE_CHUNK inputs: single pass. More: two-phase (encode 500-input
    chunks, then stream-copy concat) so peak ffmpeg memory stays bounded —
    a 3000-input single pass needs several GB of RSS and gets OOM-killed
    on small hosts, which took the whole app down (user report 2026-08-30).
    """
    mgr.set_status(job.id, JobStatus.MERGING)
    sources = job.source_paths
    work = config.WORK_DIR

    durations = await _probe_many(sources)
    bad = [s.name for s, d in zip(sources, durations) if d is None]
    if bad:
        mgr.set_status(job.id, JobStatus.FAILED,
                       error=f"cannot probe input: {', '.join(bad[:3])}")
        return
    total = sum(durations)
    job.total_duration_sec = total

    book = job.merge or None
    cover = _resolve_cover(job, work)
    work_dst = work / f"{job.id}.m4b"
    rc, err_tail = 0, ""

    def report(us, base, span):
        frac = min(1.0, us / 1_000_000 / (total or 1))
        mgr.set_progress(job.id, base + frac * span)

    async def check_cancel() -> bool:
        if job.status == JobStatus.CANCELLED:
            work_dst.unlink(missing_ok=True)
            return True
        return False

    if len(sources) <= MERGE_CHUNK:
        meta_file = work / f"{job.id}_chapters.txt"
        meta_file.write_text(
            build_chapter_meta(durations, chapter_titles(job),
                               book_title=book.book_title if book else None,
                               book_artist=book.book_artist if book else None,
                               composer=book.composer if book else None),
            encoding="utf-8")
        args = build_merge_args(sources, cover, meta_file, work_dst,
                                job.settings, normalize=job.normalize)
        rc, err_tail = await transcoder.run_ffmpeg(
            args,
            register_proc=lambda p: mgr.register_proc(job.id, p),
            on_progress=lambda us: report(us, 0.0, 99.0))
        meta_file.unlink(missing_ok=True)
        if await check_cancel():
            if cover and cover.parent == work:
                cover.unlink(missing_ok=True)
            return
    else:
        # ---- phase 1: encode chunks (audio only) ----
        parts: list[Path] = []
        chunk_sizes: list[int] = []
        encoded = 0.0
        fail_msg = None
        for idx, chunk in enumerate(_chunks(sources, MERGE_CHUNK)):
            part = work / f"{job.id}_part{idx:03d}.m4a"
            offset = sum(chunk_sizes)
            chunk_dur = sum(durations[offset:offset + len(chunk)])
            args = build_chunk_args(chunk, part, job.settings, normalize=job.normalize)
            rc, err_tail = await transcoder.run_ffmpeg(
                args,
                register_proc=lambda p: mgr.register_proc(job.id, p),
                on_progress=lambda us: report(us, encoded / total * 90.0,
                                              chunk_dur / total * 90.0))
            if await check_cancel():
                for p in parts:
                    p.unlink(missing_ok=True)
                if cover and cover.parent == work:
                    cover.unlink(missing_ok=True)
                return
            if rc != 0 or not part.exists():
                fail_msg = (err_tail or f"chunk {idx} exit {rc}")[-500:]
                break
            parts.append(part)
            chunk_sizes.append(len(chunk))
            encoded += chunk_dur
        if fail_msg:
            for p in parts:
                p.unlink(missing_ok=True)
            if cover and cover.parent == work:
                cover.unlink(missing_ok=True)
            mgr.set_status(job.id, JobStatus.FAILED, error=fail_msg)
            return

        # ---- chapter timing from ACTUAL part durations ----
        part_durs = await _probe_many(parts)
        if any(d is None for d in part_durs):
            mgr.set_status(job.id, JobStatus.FAILED, error="cannot probe merged parts")
            return
        meta_file = work / f"{job.id}_chapters.txt"
        meta_file.write_text(
            build_chapter_meta_chunked(
                [d for d in part_durs if d is not None], chunk_sizes,
                durations, chapter_titles(job),
                book_title=book.book_title if book else None,
                book_artist=book.book_artist if book else None,
                composer=book.composer if book else None),
            encoding="utf-8")
        list_file = work / f"{job.id}_list.txt"
        build_concat_list(parts, list_file)

        # ---- phase 2: stream-copy concat + chapters + cover ----
        args = build_finalize_args(parts, list_file, meta_file, cover, work_dst)
        rc, err_tail = await transcoder.run_ffmpeg(
            args,
            register_proc=lambda p: mgr.register_proc(job.id, p),
            on_progress=lambda us: report(us, 90.0, 9.5))
        for p in parts:
            p.unlink(missing_ok=True)
        list_file.unlink(missing_ok=True)
        meta_file.unlink(missing_ok=True)
        if await check_cancel():
            if cover and cover.parent == work:
                cover.unlink(missing_ok=True)
            return

    if cover and cover.parent == work:
        cover.unlink(missing_ok=True)
    if rc != 0 or not work_dst.exists():
        work_dst.unlink(missing_ok=True)
        mgr.set_status(job.id, JobStatus.FAILED,
                       error=(err_tail or f"ffmpeg exit {rc}")[-500:])
        return

    final = config.OUTPUT_DIR / f"{job.id}_{transcoder.output_filename(job)}"
    work_dst.rename(final)
    job.output_path = final
    mgr.set_progress(job.id, 100.0)
    # off the event loop: ffprobe on multi-GB outputs can take a while
    await asyncio.to_thread(transcoder._finish_with_verify, job, mgr)
    mgr.set_status(job.id, JobStatus.DONE)
