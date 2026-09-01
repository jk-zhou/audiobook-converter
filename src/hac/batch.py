"""Batch rename + tag-write orchestration over uploads / outputs pools."""
import re
from pathlib import Path

from pydantic import BaseModel

from . import db, tagwriter, uploads as uploads_mod
from .template import match_filename, validate_template, TemplateMatchError

STEM_RE = re.compile(r"^([0-9a-f]{12})_(.+)$")


class BatchRequest(BaseModel):
    pool: str  # "uploads" | "outputs"
    ids: list[str]
    template: str
    write_fields: list[str] = []
    filenames: dict[str, str] = {}   # id -> current display name (client truth)
    track_total: int | None = None


def _locked(upload_id: str) -> bool:
    from .models import ACTIVE_STATUSES
    # main.py 持有 jobs 引用；循环导入防护：从注册状态判断
    from .main import jm
    job = jm.jobs.get(upload_id)
    if job and job.status in ACTIVE:
        return True
    return any(upload_id in j.source_ids for j in jm.jobs.values()
               if j.status in ACTIVE_STATUSES)


from .models import ACTIVE_STATUSES  # noqa: E402  (after _locked uses it via closure)


def _resolve_new_name(template: str, stem: str, ext: str) -> tuple[str, dict]:
    fields = match_filename(template, stem)
    from .template import render
    new_stem = render(template, fields)
    return f"{new_stem}{ext}", fields


def _check_conflicts(entries: list[dict]) -> None:
    """Same new_name from different ids -> conflict for all participants."""
    seen: dict[str, str] = {}
    for e in entries:
        if e["status"] != "ok":
            continue
        name = e["new_name"]
        if name in seen and seen[name] != e["id"]:
            e["status"] = "skipped"
            e["reason"] = f"目标名冲突：{name}（与 {seen[name]}）"
        else:
            seen[name] = e["id"]


def preview_batch(pool: str, ids: list[str], template: str,
                  filenames: dict[str, str], total: int | None,
                  job_manager=None) -> list[dict]:
    errs = validate_template(template)
    if errs:
        raise ValueError(errs[0])
    out = []
    for uid in ids:
        name = filenames.get(uid, "")
        ext = Path(name).suffix if name else ""
        stem = Path(name).stem if name else ""
        entry = {"id": uid, "name": name, "fields": {}, "new_name": name,
                 "tag_changes": {}, "status": "ok", "reason": ""}
        try:
            fields = match_filename(template, stem)
            new_name, _ = _resolve_new_name(template, stem, ext)
            entry["fields"] = fields
            entry["new_name"] = new_name
            if pool == "uploads" and _locked(uid):
                entry["status"] = "skipped"
                entry["reason"] = "正被任务使用"
        except TemplateMatchError as e:
            entry["status"] = "skipped"
            entry["reason"] = str(e)
        out.append(entry)
    _check_conflicts(out)
    return out


def execute_batch(pool: str, ids: list[str], template: str,
                  write_fields: list[str], filenames: dict[str, str],
                  total: int | None = None, job_manager=None) -> dict:
    track_total = total
    previews = preview_batch(pool, ids, template, filenames,
                             track_total, job_manager)
    report = {"ok": 0, "skipped": 0, "failed": 0, "details": []}

    if pool == "uploads":
        for p in previews:
            if p["status"] != "ok":
                report["skipped"] += 1
                report["details"].append(p)
                continue
            try:
                u = uploads_mod.get(p["id"])
                if not u or not u.path.exists():
                    raise FileNotFoundError(p["name"])
                new_path = u.path.parent / f"{p['id']}_{p['new_name']}"
                if write_fields:
                    fields = {k: p["fields"].get(_FIELD_MAP[k])
                              for k in write_fields}
                    fields = {k: v for k, v in fields.items() if v is not None}
                    if "track" in fields:
                        fields["track"] = fields["track"]
                    tagwriter.write_tags(u.path, fields,
                                         track_total=p["fields"].get("TrackTotal")
                                         or track_total)
                u.path.rename(new_path)
                u.path = new_path
                u.name = p["new_name"]
                report["ok"] += 1
                report["details"].append(p)
            except Exception as e:
                p["status"] = "failed"
                p["reason"] = f"{type(e).__name__}: {e}"
                report["failed"] += 1
                report["details"].append(p)
        return report

    # outputs pool
    from .models import ACTIVE_STATUSES
    for p in previews:
        jid = p["id"]
        job = (job_manager.jobs.get(jid) if job_manager else None)
        if not job or not job.output_path or not job.output_path.exists():
            p["status"] = "skipped"
            p["reason"] = "产物不存在"
            report["skipped"] += 1
            report["details"].append(p)
            continue
        try:
            new_path = job.output_path.parent / p["new_name"]
            if new_path != job.output_path:
                job.output_path.rename(new_path)
            job.output_path = new_path
            job.output_filename = p["new_name"]
            if job_manager:
                job_manager._persist(job)
            if write_fields and p["fields"]:
                fields = {k: p["fields"].get(_FIELD_MAP.get(k, k))
                          for k in write_fields}
                fields = {k: v for k, v in fields.items() if v is not None}
                tagwriter.write_tags(new_path, fields,
                                     track_total=p["fields"].get("TrackTotal")
                                     or track_total)
            report["ok"] += 1
            report["details"].append(p)
        except Exception as e:
            p["status"] = "failed"
            p["reason"] = f"{type(e).__name__}: {e}"
            report["failed"] += 1
            report["details"].append(p)
    return report


# template field -> tag writer field
_FIELD_MAP = {"title": "TrackTitle", "artist": "Artist", "album": "Album",
              "track": "TrackNum", "year": "Year", "genre": "Genre",
              "disc": "DiscNum", "composer": "Composer"}
_FIELD_KEY_BY_TEMPLATE = {v: k for k, v in _FIELD_MAP.items()}

from . import tagwriter  # noqa: E402
