"""Agent-friendly one-shot conversion API.

设计目标：agent 用最少的请求完成「给路径 → 转码/合并 → 输出到目录」。
- inputs 支持目录（递归收集音频）或文件，必须在 HAC_LIBRARY_ROOTS 白名单内
- output_dir 必须在 HAC_OUTPUT_ROOTS 白名单内
- 响应保持极简（一行 JSON 摘要），帮助走 GET /api/agent/help
"""
import asyncio
import shutil
import time
from pathlib import Path

from fastapi import HTTPException

from . import library
from .config import LIBRARY_ROOTS, OUTPUT_ROOTS
from .models import ACTIVE_STATUSES

AUDIO_EXTS = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg", ".opus",
              ".wav", ".wma", ".aiff", ".mka"}


def _under_roots(path: Path, roots: list[Path]) -> bool:
    rp = path.resolve()
    return any(rp == Path(r).resolve() or rp.is_relative_to(Path(r).resolve())
               for r in roots)


def collect_inputs(inputs: list[str]) -> list[Path]:
    """Expand dirs/files into an audio path list (natural-sorted, deduped)."""
    files: list[Path] = []
    seen = set()
    for raw in inputs:
        p = Path(raw).expanduser()
        if not _under_roots(p, LIBRARY_ROOTS):
            raise HTTPException(403, f"路径不在白名单内（HAC_LIBRARY_ROOTS）：{p}")
        if p.is_dir():
            batch = sorted((f for f in p.rglob("*")
                            if f.is_file() and f.suffix.lower() in AUDIO_EXTS),
                           key=lambda f: [int(t) if t.isdigit() else t.lower()
                                          for t in __import__("re").split(r"(\d+)", f.name)])
            files.extend(batch)
        elif p.is_file():
            if p.suffix.lower() not in AUDIO_EXTS:
                raise HTTPException(400, f"不是可识别的音频文件：{p}")
            files.append(p)
        else:
            raise HTTPException(404, f"路径不存在：{p}")
    out = []
    for f in files:
        rp = str(f.resolve())
        if rp not in seen:
            seen.add(rp)
            out.append(f)
    if not out:
        raise HTTPException(400, "输入中没有可识别的音频文件")
    return out


def validate_output_dir(dest: str | None) -> Path | None:
    if not dest:
        return None
    d = Path(dest).expanduser()
    if not _under_roots(d, OUTPUT_ROOTS):
        raise HTTPException(
            403, f"output_dir 不在白名单内（HAC_OUTPUT_ROOTS）：{d}")
    d.mkdir(parents=True, exist_ok=True)
    return d


async def wait_jobs(get_jobs, ids: list[str], timeout: float, poll: float = 0.5):
    """Await until all ids are terminal (or timeout). Must run on the loop —
    a sync poll would block the very loop the transcodes need."""
    deadline = time.monotonic() + timeout
    while True:
        rows = get_jobs(ids)
        if all(r["status"] not in ACTIVE_STATUSES for r in rows):
            return rows
        if time.monotonic() > deadline:
            return rows
        await asyncio.sleep(poll)


def export_output(output_path: Path, dest_dir: Path, move: bool = True) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(output_path).name
    if dest.exists():
        dest = dest_dir / f"{Path(output_path).stem}_1{Path(output_path).suffix}"
    if move:
        shutil.move(str(output_path), dest)
    else:
        shutil.copy2(output_path, dest)
    return dest
