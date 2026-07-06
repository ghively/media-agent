"""Provider base protocol and data types."""
from pathlib import Path
from typing import Protocol, runtime_checkable

from src.engine.types import MediaItem, AcquireResult, JobStatus


@runtime_checkable
class MediaProvider(Protocol):
    """Every content source implements this interface."""

    name: str = ""
    content_types: list[str] = []
    acquisition_pattern: str = "indexer"  # indexer | direct | authenticated

    async def discover(self, query: str | None = None) -> list[MediaItem]:
        """Search for content by name/URL/channel."""
        ...

    async def acquire(self, item: MediaItem) -> AcquireResult:
        """Trigger download. Returns job ID for tracking."""
        ...

    async def process(self, item: MediaItem, downloaded_path: Path) -> Path:
        """Metadata, artwork, naming, NFO generation. Returns final library path."""
        ...

    async def get_status(self, job_id: str) -> JobStatus:
        """Check download/processing progress."""
        ...

    async def monitor(self) -> list[MediaItem]:
        """Check subscriptions/playlists for new content. Called by scheduler."""
        ...
