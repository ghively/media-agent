"""Pydantic data models for Media Agent."""
from pydantic import BaseModel
from enum import Enum
from pathlib import Path


class ContentType(str, Enum):
    TV_EPISODE = "tv_episode"
    MOVIE = "movie"
    MUSIC_ALBUM = "music_album"
    MUSIC_TRACK = "music_track"
    CONCERT = "concert"
    TUTORIAL = "tutorial"
    AUDIOBOOK = "audiobook"
    ROM = "rom"
    UNKNOWN = "unknown"


class MediaItem(BaseModel):
    id: str
    title: str
    content_type: ContentType = ContentType.UNKNOWN
    provider: str = ""
    metadata: dict = {}
    download_url: str | None = None
    quality: str | None = None
    size_bytes: int | None = None


class AcquireResult(BaseModel):
    job_id: str
    status: str = "queued"
    estimated_time: int | None = None


class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: float = 0.0
    speed: str | None = None
    eta: int | None = None
    error: str | None = None


class LibraryIssue(BaseModel):
    severity: str = "info"
    category: str = ""
    file_path: Path | None = None
    description: str = ""
    auto_fixable: bool = False
    fix_action: str | None = None
