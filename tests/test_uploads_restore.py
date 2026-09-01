"""restore_from_disk: rebuild the upload registry from data/uploads."""
import uuid

from hac import uploads
from hac.models import Upload


def test_restore_from_disk(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(uploads.config, "UPLOAD_DIR", upload_dir)

    uid = uuid.uuid4().hex[:12]
    f = upload_dir / (uid + "_第一章.mp3")
    f.write_bytes(b"abc" * 42)

    n = uploads.restore_from_disk()

    assert n == 1
    u = uploads.get(uid)
    assert u is not None
    assert u.name == "第一章.mp3"
    assert u.path == f
    assert u.size == 126


def test_restore_skips_unmatched_files(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(uploads.config, "UPLOAD_DIR", upload_dir)

    (upload_dir / "random-file-no-prefix.mp3").write_bytes(b"x")

    assert uploads.restore_from_disk() == 0


def test_restore_does_not_duplicate(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(uploads.config, "UPLOAD_DIR", upload_dir)

    uid = uuid.uuid4().hex[:12]
    existing = Upload(id=uid, name="已有.mp3", path=upload_dir / "x", size=1)
    uploads._store[existing.id] = existing
    (upload_dir / (uid + "_第一章.mp3")).write_bytes(b"abc")

    assert uploads.restore_from_disk() == 0
    assert uploads.get(existing.id).name == "已有.mp3"
    uploads._store.pop(existing.id)
