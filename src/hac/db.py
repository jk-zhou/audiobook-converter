"""SQLite persistence: settings KV, session snapshot, job history.

WAL mode; schema_version gate (no auto-migration — single-user tool).
"""
import json
from datetime import datetime
from pathlib import Path

import sqlalchemy
from sqlmodel import Field, SQLModel, Session as DBSession, create_engine, select

from .models import Job

SCHEMA_VERSION = "1"


class SettingEntry(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=datetime.now)


class SessionEntry(SQLModel, table=True):
    id: str = Field(primary_key=True, default="current")
    value: str
    updated_at: datetime = Field(default_factory=datetime.now)


class JobRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    mode: str
    status: str
    preset_id: str | None = None          # reserved (Job model has none yet)
    settings_json: str | None = None
    merge_json: str | None = None
    metadata_json: str | None = None
    normalize: bool = False
    title_source: str = "inherit"
    title_pattern: str | None = None
    source_ids_json: str = "[]"
    source_names_json: str | None = None
    output_filename: str | None = None
    output_path: str | None = None
    output_size: int | None = None
    verify_json: str | None = None
    error: str | None = None
    progress: float = 0.0
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output_deleted_at: datetime | None = None


_engine = None


def init_db(data_dir: Path) -> None:
    """Create engine/tables; gate on schema_version (no auto-migration)."""
    global _engine
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_dir / 'hac.db'}")
    with DBSession(engine) as s:
        s.exec(sqlalchemy.text("PRAGMA journal_mode=WAL"))
    SQLModel.metadata.create_all(engine)
    _engine = engine
    with DBSession(_engine) as s:
        row = s.get(SettingEntry, "schema_version")
        if row is None:
            s.add(SettingEntry(key="schema_version", value=SCHEMA_VERSION))
            s.commit()
        elif row.value != SCHEMA_VERSION:
            raise RuntimeError(
                f"hac.db schema_version={row.value} != {SCHEMA_VERSION}; "
                "请先备份 data/hac.db 后删除或升级程序")


def get_engine():
    if _engine is None:
        raise RuntimeError("db.init_db() not called")
    return _engine


# ---------- KV ----------

def kv_get(key: str) -> str | None:
    with DBSession(get_engine()) as s:
        row = s.get(SettingEntry, key)
        return row.value if row else None


def kv_set(key: str, value: str) -> None:
    with DBSession(get_engine()) as s:
        row = s.get(SettingEntry, key)
        if row:
            row.value = value
            row.updated_at = datetime.now()
        else:
            s.add(SettingEntry(key=key, value=value))
        s.commit()


def kv_all() -> list[dict]:
    with DBSession(get_engine()) as s:
        rows = s.exec(select(SettingEntry)).all()
        return [{"key": r.key, "value": r.value,
                 "updated_at": r.updated_at.isoformat()} for r in rows]


# ---------- session ----------

def session_get() -> str | None:
    with DBSession(get_engine()) as s:
        row = s.get(SessionEntry, "current")
        return row.value if row else None


def session_set(value: str) -> None:
    with DBSession(get_engine()) as s:
        row = s.get(SessionEntry, "current")
        if row:
            row.value = value
            row.updated_at = datetime.now()
        else:
            s.add(SessionEntry(id="current", value=value))
        s.commit()


def session_exists() -> bool:
    with DBSession(get_engine()) as s:
        return s.get(SessionEntry, "current") is not None


# ---------- jobs ----------

def save_job(job: Job) -> None:
    rec = job_to_record(job)
    with DBSession(get_engine()) as s:
        existing = s.get(JobRecord, job.id)
        if existing:
            for k, v in rec.model_dump().items():
                setattr(existing, k, v)
        else:
            s.add(rec)
        s.commit()


def get_job_record(job_id: str) -> JobRecord | None:
    with DBSession(get_engine()) as s:
        return s.get(JobRecord, job_id)


def list_job_records() -> list[JobRecord]:
    with DBSession(get_engine()) as s:
        return list(s.exec(select(JobRecord)).all())


def mark_output_deleted(job_id: str) -> None:
    with DBSession(get_engine()) as s:
        row = s.get(JobRecord, job_id)
        if row:
            row.output_deleted_at = datetime.now()
            s.commit()


def _dump(model) -> str | None:
    return None if model is None else json.dumps(
        model.model_dump(mode="json"), ensure_ascii=False)


def _load(cls, raw):
    return None if raw is None else cls(**json.loads(raw))


def job_to_record(job: Job) -> JobRecord:
    return JobRecord(
        id=job.id,
        mode=job.mode,
        status=job.status.value,
        settings_json=_dump(job.settings),
        merge_json=_dump(job.merge),
        metadata_json=_dump(job.metadata),
        normalize=job.normalize,
        title_source=job.title_source,
        title_pattern=job.title_pattern,
        source_ids_json=json.dumps(job.source_ids, ensure_ascii=False),
        source_names_json=json.dumps(job.source_names, ensure_ascii=False),
        output_filename=job.output_filename,
        output_path=str(job.output_path) if job.output_path else None,
        output_size=(job.verify.output_size if job.verify else None),
        verify_json=_dump(job.verify),
        error=job.error,
        progress=job.progress,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def job_record_to_job(rec: JobRecord) -> Job:
    from .models import (TranscodeSettings, MetadataEdit, MergeOptions,
                         VerifyInfo, JobStatus)

    return Job(
        id=rec.id,
        mode=rec.mode,
        status=JobStatus(rec.status),
        settings=_load(TranscodeSettings, rec.settings_json),
        merge=_load(MergeOptions, rec.merge_json),
        metadata=_load(MetadataEdit, rec.metadata_json) or MetadataEdit(),
        normalize=rec.normalize,
        title_source=rec.title_source,
        title_pattern=rec.title_pattern,
        source_ids=json.loads(rec.source_ids_json),
        source_names=json.loads(rec.source_names_json) if rec.source_names_json else [],
        output_filename=rec.output_filename or "unknown",
        output_path=Path(rec.output_path) if rec.output_path else None,
        output_size=None,
        verify=_load(VerifyInfo, rec.verify_json),
        error=rec.error,
        progress=rec.progress,
        created_at=rec.created_at or datetime.now(),
        started_at=rec.started_at,
        finished_at=rec.finished_at,
        output_deleted_at=rec.output_deleted_at,
    )
