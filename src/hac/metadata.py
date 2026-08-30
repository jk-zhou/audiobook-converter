import base64
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC, TALB, TCOM, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp4 import MP4

from .models import MetadataEdit


def read_source_tags(path: Path) -> dict:
    """Read source tags via mutagen easy interface; lowercase keys, scalar values."""
    f = MutagenFile(path, easy=True)
    if not f or not f.tags:
        return {}
    out = {}
    for k, v in f.tags.items():
        if isinstance(v, list):
            v = v[0] if v else None
        if v is None:
            continue
        out[str(k).lower()] = str(v)
    return out


def extract_cover(path: Path) -> tuple[bytes, str] | None:
    """Extract embedded cover art; returns (data, ext)."""
    try:
        audio = MutagenFile(path)
    except Exception:
        return None
    if audio is None:
        return None
    data, mime = None, "image/jpeg"
    # ID3 (mp3)
    if hasattr(audio, "tags") and audio.tags is not None and hasattr(audio.tags, "getall"):
        apics = audio.tags.getall("APIC")
        if apics:
            data = apics[0].data
            mime = apics[0].mime or mime
    # MP4
    if data is None and isinstance(audio, MP4) and audio.tags and "covr" in audio.tags:
        cov = audio.tags["covr"][0]
        data = bytes(cov)
        mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else mime
    # FLAC
    if data is None and isinstance(audio, FLAC) and audio.pictures:
        data = audio.pictures[0].data
        mime = audio.pictures[0].mime or mime
    # Ogg/Opus (METADATA_BLOCK_PICTURE)
    if data is None and audio.tags is not None:
        raw = None
        try:
            for k in ("metadata_block_picture", "Metadata_Block_Picture"):
                if k in audio.tags:
                    raw = audio.tags[k][0]
                    break
        except Exception:
            raw = None
        if raw:
            try:
                pic = Picture(base64.b64decode(raw))
                data, mime = pic.data, pic.mime
            except Exception:
                data = None
    if not data:
        return None
    ext = ".png" if "png" in mime else ".jpg"
    return data, ext


def _fmt_pair(n: int, total: int | None) -> str:
    return f"{n}/{total}" if total else str(n)


def write_tags(path: Path, edit: MetadataEdit) -> None:
    """Apply user overrides on top of tags ffmpeg already copied from source."""
    ext = path.suffix.lower()
    if not any([edit.title, edit.artist, edit.album, edit.albumartist, edit.date,
                edit.genre, edit.composer, edit.track, edit.disc]):
        return
    if ext == ".mp3":
        _write_mp3(path, edit)
    elif ext in (".m4a", ".m4b", ".mp4"):
        _write_mp4(path, edit)
    elif ext == ".flac":
        _write_flac(path, edit)
    elif ext in (".opus", ".ogg"):
        _write_vorbis(path, edit)
    # wav: no tag support, skip


def _apply_vorbis(audio, edit: MetadataEdit) -> None:
    if edit.title: audio["title"] = edit.title
    if edit.artist: audio["artist"] = edit.artist
    if edit.album: audio["album"] = edit.album
    if edit.albumartist: audio["albumartist"] = edit.albumartist
    if edit.date: audio["date"] = edit.date
    if edit.genre: audio["genre"] = edit.genre
    if edit.composer: audio["composer"] = edit.composer
    if edit.track: audio["tracknumber"] = _fmt_pair(*edit.track)
    if edit.disc: audio["discnumber"] = _fmt_pair(*edit.disc)


def _write_mp3(path: Path, edit: MetadataEdit) -> None:
    try:
        audio = ID3(path)
    except Exception:
        audio = ID3()
    if edit.title: audio.add(TIT2(encoding=3, text=edit.title))
    if edit.artist: audio.add(TPE1(encoding=3, text=edit.artist))
    if edit.album: audio.add(TALB(encoding=3, text=edit.album))
    if edit.albumartist: audio.add(TPE2(encoding=3, text=edit.albumartist))
    if edit.date: audio.add(TDRC(encoding=3, text=edit.date))
    if edit.genre: audio.add(TCON(encoding=3, text=edit.genre))
    if edit.composer: audio.add(TCOM(encoding=3, text=edit.composer))
    if edit.track: audio.add(TRCK(encoding=3, text=_fmt_pair(*edit.track)))
    if edit.disc: audio.add(TPOS(encoding=3, text=_fmt_pair(*edit.disc)))
    audio.save(path)


def _write_mp4(path: Path, edit: MetadataEdit) -> None:
    audio = MP4(path)
    if edit.title: audio["\xa9nam"] = [edit.title]
    if edit.artist: audio["\xa9ART"] = [edit.artist]
    if edit.album: audio["\xa9alb"] = [edit.album]
    if edit.albumartist: audio["aART"] = [edit.albumartist]
    if edit.date: audio["\xa9day"] = [edit.date]
    if edit.genre: audio["\xa9gen"] = [edit.genre]
    if edit.composer: audio["\xa9wrt"] = [edit.composer]
    if edit.track: audio["trkn"] = [(edit.track[0], edit.track[1] or 0)]
    if edit.disc: audio["disk"] = [(edit.disc[0], edit.disc[1] or 0)]
    audio.save()


def _write_flac(path: Path, edit: MetadataEdit) -> None:
    audio = FLAC(path)
    _apply_vorbis(audio, edit)
    audio.save()


def _write_vorbis(path: Path, edit: MetadataEdit) -> None:
    audio = MutagenFile(path)
    if audio is None or audio.tags is None:
        return
    _apply_vorbis(audio, edit)
    audio.save()
