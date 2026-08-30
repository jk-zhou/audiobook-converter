from pathlib import Path

from hac.metadata import write_tags, read_source_tags
from hac.models import MetadataEdit


def test_mp3_write_and_inherit(tmp_path):
    # create a tagged source mp3 via ffmpeg
    src = tmp_path / "src.mp3"
    import subprocess
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=0.3",
        "-c:a", "libmp3lame", "-id3v2_version", "3",
        "-metadata", "album=原专辑", "-metadata", "artist=源作者",
        str(src)], check=True)

    out = tmp_path / "out.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-c:a", "libmp3lame", str(out)], check=True)

    # user fills title only → album/artist inherited, title overridden
    write_tags(out, MetadataEdit(title="新标题"))
    tags = read_source_tags(out)
    assert tags["title"] == "新标题"
    assert tags["album"] == "原专辑"
    assert tags["artist"] == "源作者"


def test_opus_write(tmp_path):
    import subprocess
    out = tmp_path / "out.opus"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "sine=duration=0.3", "-c:a", "libopus", str(out)], check=True)
    edit = MetadataEdit(title="T", artist="A", album="AL", track=(1, 3))
    write_tags(out, edit)
    tags = read_source_tags(out)
    assert tags["title"] == "T"
    assert tags["tracknumber"] == "1/3"


def test_m4a_write(tmp_path):
    import subprocess
    out = tmp_path / "out.m4a"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "sine=duration=0.3", "-c:a", "aac", str(out)], check=True)
    write_tags(out, MetadataEdit(title="标题", albumartist="朗读者"))
    from mutagen import File
    f = File(str(out))
    assert f["\xa9nam"][0] == "标题"
    assert f["aART"][0] == "朗读者"


def test_empty_edit_is_noop(tmp_path):
    p = tmp_path / "x.opus"
    import subprocess
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "sine=duration=0.1", "-c:a", "libopus", str(p)], check=True)
    before = p.stat().st_mtime
    write_tags(p, MetadataEdit())
    assert p.stat().st_mtime == before
