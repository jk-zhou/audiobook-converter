"""db.py: SQLite engine, three tables, KV helpers, Job<->JobRecord conversion."""
from datetime import datetime
from pathlib import Path

import pytest

from hac import db
from hac.models import Job, JobStatus, TranscodeSettings, MetadataEdit


@pytest.fixture()
def dbtmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_engine", None)  # force re-init per test
    db.init_db(tmp_path)
    yield tmp_path


from hac.models import VerifyInfo


def _sample_job() -> Job:
    return Job(
        id="job0001abc",
        mode="merge",
        output_filename="书名.m4b",
        settings=TranscodeSettings(format="m4b", codec="aac", bitrate="48k"),
        metadata=MetadataEdit(title="书名"),
        normalize=True,
        source_ids=["abc123", "lib:/books/x.mp3"],
        source_names=["第一章.m4a", "x.mp3"],
        title_source="pattern",
        title_pattern="第${TrackNum:3}集",
        progress=100.0,
        status=JobStatus.DONE,
        verify=VerifyInfo(codec="aac", output_size=12345),
    )


def test_init_db_creates_file(dbtmp):
    assert (dbtmp / "hac.db").exists()


def test_kv_roundtrip(dbtmp):
    assert db.kv_get("settings.default") is None
    db.kv_set("settings.default", '{"bitrate": "48k"}')
    assert db.kv_get("settings.default") == '{"bitrate": "48k"}'
    db.kv_set("settings.default", '{"bitrate": "64k"}')  # upsert
    assert db.kv_get("settings.default") == '{"bitrate": "64k"}'
    rows = db.kv_all()
    assert any(r["key"] == "settings.default" for r in rows)


def test_session_single_row_upsert(dbtmp):
    assert db.session_get() is None
    assert db.session_exists() is False
    db.session_set('{"form": {}}')
    db.session_set('{"form": {"bitrate": "48k"}}')  # overwrite, still one row
    assert db.session_get() == '{"form": {"bitrate": "48k"}}'
    assert db.session_exists() is True


def test_schema_version_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    db.init_db(tmp_path)
    db.kv_set("schema_version", "999")
    monkeypatch.setattr(db, "_engine", None)
    with pytest.raises(RuntimeError):
        db.init_db(tmp_path)


def test_job_record_roundtrip(dbtmp):
    job = _sample_job()
    db.save_job(job)
    rec = db.get_job_record(job.id)
    assert rec is not None
    back = db.job_record_to_job(rec)
    assert back.id == job.id
    assert back.status == JobStatus.DONE
    assert back.settings.bitrate == "48k"
    assert back.source_ids == job.source_ids
    assert back.source_names == job.source_names
    assert back.title_pattern == job.title_pattern
    assert back.normalize is True
    assert back.metadata.title == "书名"
    assert back.verify.output_size == 12345


def test_list_job_records_all(dbtmp):
    db.save_job(_sample_job())
    assert len(db.list_job_records()) == 1
