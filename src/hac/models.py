from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal
import uuid

from pydantic import BaseModel, Field

Format = Literal["mp3", "m4a", "m4b", "opus", "ogg", "flac", "wav"]

DEFAULT_CODEC = {
    "mp3": "libmp3lame",
    "m4a": "aac",
    "m4b": "aac",
    "opus": "libopus",
    "ogg": "libvorbis",
    "flac": "flac",
    "wav": "pcm_s16le",
}

# containers that support embedded cover art as an attached-pic stream
COVER_CAPABLE = {"mp3", "m4a", "m4b", "flac"}
# for mp4-family, re-encode cover to mjpeg (movenc writes covr atom);
# for mp3/flac the source picture stream can be stream-copied
COVER_REENCODE = {"m4a", "m4b"}


class TranscodeSettings(BaseModel):
    format: Format
    codec: str | None = None
    profile: str | None = None
    bitrate: str | None = None
    quality: int | None = None
    samplerate: int | None = None
    channels: int | None = Field(default=None, ge=1, le=2)
    compression_level: int | None = Field(default=None, ge=0, le=10)
    extra_args: list[str] = []


class MetadataEdit(BaseModel):
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    albumartist: str | None = None
    date: str | None = None
    genre: str | None = None
    composer: str | None = None
    track: tuple[int, int] | None = None
    disc: tuple[int, int] | None = None


class MergeOptions(BaseModel):
    book_title: str | None = None
    book_artist: str | None = None
    composer: str | None = None
    cover_upload_id: str | None = None


class VerifyInfo(BaseModel):
    codec: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    duration: float | None = None
    output_size: int | None = None
    source_size: int | None = None
    savings_pct: float | None = None


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    TAGGING = "tagging"
    MERGING = "merging"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.TAGGING, JobStatus.MERGING}


TitleSource = Literal["inherit", "filename", "pattern"]


class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    mode: Literal["single", "merge"] = "single"
    source_ids: list[str] = []
    source_paths: list[Path] = []
    source_names: list[str] = []       # 用户视角的源文件名快照（不含内部 id）
    output_filename: str
    settings: TranscodeSettings
    merge: MergeOptions | None = None
    metadata: MetadataEdit = Field(default_factory=MetadataEdit)
    normalize: bool = False
    # WYSIWYG ordering + title/track fallback (single mode)
    position: int | None = None          # 1-based index in the files panel
    total: int | None = None             # panel file count
    title_source: TitleSource = "inherit"
    title_pattern: str | None = None     # e.g. "第${TrackNum}集"
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    error: str | None = None
    output_path: Path | None = None
    verify: VerifyInfo | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_duration_sec: float | None = None


class Upload(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    path: Path
    size: int
    info: dict | None = None


class JobCreate(BaseModel):
    mode: Literal["single", "merge"] = "single"
    source_ids: list[str] = []
    preset_id: str | None = None
    settings: TranscodeSettings | None = None
    output_filename: str | None = None
    metadata: MetadataEdit = Field(default_factory=MetadataEdit)
    normalize: bool = False
    merge: MergeOptions | None = None
    position: int | None = None
    total: int | None = None
    title_source: TitleSource = "inherit"
    title_pattern: str | None = None


class Preset(BaseModel):
    id: str
    name: str
    description: str
    settings: TranscodeSettings
    extension: str
    filename_suffix: str
    requires_encoder: str | None = None

    def effective_enabled(self, encoders: set[str]) -> bool:
        return self.requires_encoder is None or self.requires_encoder in encoders
