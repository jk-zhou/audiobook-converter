"""Write audio tags via mutagen across containers (m4a/mp3/flac/ogg).

fields keys: title/artist/album/track(+track_total)/year/genre/disc/composer.
None values are skipped — only requested fields are written.
"""
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TALB, TCOM, TCON, TDRC, TIT2, TPE1, TPOS, TRCK
from mutagen.mp4 import MP4


class TagWriteError(Exception):
    pass


def write_tags(path: Path, fields: dict, track_total: int | None = None) -> None:
    """Write fields (None/absent = untouched). track gets N/total when given."""
    path = Path(path)
    audio = MutagenFile(path, easy=False)
    if audio is None:
        raise TagWriteError(f"unsupported file: {path.name}")

    if isinstance(audio, MP4):
        _write_mp4(audio, fields, track_total)
        audio.save()
        return
    if isinstance(audio, FLAC) or audio.__class__.__name__ == "OggVorbis":
        _write_vorbis(audio, fields, track_total)
        audio.save()
        return
    if audio.__class__.__name__ == "MP3":
        # MP3: tags live in an ID3 sidecar; ensure it exists
        if audio.tags is None:
            audio.add_tags()
        _write_id3(audio.tags, fields, track_total)
        audio.save()
        return
    # generic mutagen File (ogg/opus/wav...) — Vorbis comments
    try:
        _write_vorbis(audio, fields, track_total)
        audio.save()
    except Exception as e:
        raise TagWriteError(f"unsupported container: {path.name} ({e})")


def _mp4_set(audio: MP4, atom: str, value):
    if value is not None and value != "":
        audio[atom] = value


def _write_mp4(audio: MP4, f: dict, track_total: int | None):
    _mp4 = {
        "title": ("©nam", lambda v: [v]),
        "artist": ("©ART", lambda v: [v]),
        "album": ("©alb", lambda v: [v]),
        "year": ("©day", lambda v: [str(v)]),
        "genre": ("©gen", lambda v: [v]),
        "composer": ("©wrt", lambda v: [v]),
        "disc": ("disk", lambda v: [(int(v), 1)]),
    }
    for key, (atom, wrap) in _mp4.items():
        if f.get(key) is not None:
            audio[atom] = wrap(f[key])
    if f.get("track") is not None:
        audio["trkn"] = [(int(f["track"]), int(track_total or 0))]


def _id3(audio_or_path: Path):
    tags = ID3(audio_or_path)
    return tags


def _write_id3(tags: ID3, f: dict, track_total: int | None):
    if f.get("title") is not None:
        tags.add(TIT2(encoding=3, text=[f["title"]]))
    if f.get("artist") is not None:
        tags.add(TPE1(encoding=3, text=[f["artist"]]))
    if f.get("album") is not None:
        tags.add(TALB(encoding=3, text=[f["album"]]))
    if f.get("track") is not None:
        trk = f"{f['track']}" + (f"/{track_total}" if track_total else "")
        tags.add(TRCK(encoding=3, text=[trk]))
    if f.get("year") is not None:
        tags.add(TDRC(encoding=3, text=[str(f["year"])]))
    if f.get("genre") is not None:
        tags.add(TCON(encoding=3, text=[f["genre"]]))
    if f.get("disc") is not None:
        tags.add(TPOS(encoding=3, text=[str(f["disc"])]))
    if f.get("composer") is not None:
        tags.add(TCOM(encoding=3, text=[f["composer"]]))


def _write_vorbis(audio, f: dict, track_total: int | None):
    m = {"title": "title", "artist": "artist", "album": "album",
         "year": "date", "genre": "genre", "composer": "composer",
         "disc": "discnumber"}
    for key, tag in m.items():
        if f.get(key) is not None:
            audio[tag] = [str(f[key])]
    if f.get("track") is not None:
        audio["tracknumber"] = [str(f["track"])]
        if track_total is not None:
            audio["tracktotal"] = [str(track_total)]
