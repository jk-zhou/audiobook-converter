import pytest

from hac.library import is_allowed, list_dir


@pytest.fixture
def roots(tmp_path):
    r = tmp_path / "books"
    (r / "sub").mkdir(parents=True)
    (r / "a.flac").write_bytes(b"x")
    (r / "b.mp3").write_bytes(b"x")
    (r / "note.txt").write_text("no")
    return [r]


def test_allowed_inside(roots):
    assert is_allowed(roots[0], roots) is True
    assert is_allowed(roots[0] / "a.flac", roots) is True
    assert is_allowed(roots[0] / "sub", roots) is True


def test_denied_outside(roots, tmp_path):
    outside = tmp_path / "evil.flac"
    outside.write_bytes(b"x")
    assert is_allowed(outside, roots) is False
    assert is_allowed(tmp_path, roots) is False


def test_traversal_denied(roots):
    outside = roots[0] / ".." / ".."
    assert is_allowed(outside, roots) is False


def test_list_dir_filters_audio(roots):
    res = list_dir(str(roots[0]), roots)
    names = {f["name"] for f in res["files"]}
    assert names == {"a.flac", "b.mp3"}
    assert any(d["name"] == "sub" for d in res["dirs"])


def test_list_dir_outside_raises(roots, tmp_path):
    with pytest.raises(PermissionError):
        list_dir(str(tmp_path), roots)
    with pytest.raises(PermissionError):
        list_dir("/etc", roots)
