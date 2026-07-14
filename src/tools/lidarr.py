"""Lidarr music management tools (mirrors the Sonarr/Radarr pattern).

Config (``services.lidarr``): ``url``, ``api_key``, plus ``quality_profile_id``,
``metadata_profile_id`` and ``root_folder_path`` used when adding artists.
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings

_NOT_CONFIGURED = ("❌ Lidarr isn't configured. Set services.lidarr.url and "
                   "api_key in settings.yaml.")


class LidarrClient:
    """Async client for Lidarr v1 API."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = timeout

    async def _get(self, endpoint: str, params: dict | None = None):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1{endpoint}", headers=self.headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, endpoint: str, json_data: dict):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1{endpoint}", headers=self.headers, json=json_data
            )
            resp.raise_for_status()
            return resp.json()


def _client() -> LidarrClient | None:
    s = get_settings().lidarr
    if not s.get("url") or not s.get("api_key"):
        return None
    return LidarrClient(s["url"], s["api_key"])


async def _lookup_artists(query: str) -> list[dict] | None:
    """Raw artist lookup for the router's deterministic add-artist flow.
    Returns None when Lidarr isn't configured; raises on request failure."""
    client = _client()
    if client is None:
        return None
    return await client._get("/artist/lookup", params={"term": query})


@tool
async def search_artist(query: str) -> str:
    """Search Lidarr for a music artist by name. Returns matches with the
    foreignArtistId needed by add_artist."""
    try:
        client = _client()
        if client is None:
            return _NOT_CONFIGURED
        results = await client._get("/artist/lookup", params={"term": query})
        if not results:
            return f"No artists found for '{query}'."
        lines = [f"Found {len(results)} artist(s):\n"]
        for i, r in enumerate(results[:10], 1):
            name = r.get("artistName", "Unknown")
            genres = ", ".join((r.get("genres") or [])[:3])
            fid = r.get("foreignArtistId", "N/A")
            lines.append(f"  {i}. {name}" + (f" ({genres})" if genres else "")
                         + f" [artistId: {fid}]")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Lidarr."
    except Exception as e:
        return f"❌ Lidarr search failed: {type(e).__name__}: {e}"


@tool
async def add_artist(foreign_artist_id: str, name: str) -> str:
    """Add a music artist to Lidarr by the artistId from search_artist.
    Monitors the artist and starts searching for missing albums."""
    try:
        client = _client()
        if client is None:
            return _NOT_CONFIGURED
        settings = get_settings().lidarr
        body = {
            "foreignArtistId": foreign_artist_id,
            "artistName": name,
            "qualityProfileId": settings.get("quality_profile_id", 1),
            "metadataProfileId": settings.get("metadata_profile_id", 1),
            "rootFolderPath": settings.get("root_folder_path", "/media/music"),
            "monitored": True,
            "addOptions": {"searchForMissingAlbums": True},
        }
        await client._post("/artist", body)
        return f"✅ Added '{name}' to Lidarr. Album search started."
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return f"❌ '{name}' may already be in Lidarr, or the artistId is invalid."
        return f"❌ Lidarr returned HTTP {e.response.status_code}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Lidarr."
    except Exception as e:
        return f"❌ Failed to add artist: {type(e).__name__}: {e}"


@tool
async def list_artists(page: int = 1) -> str:
    """List artists monitored in Lidarr, 30 per page alphabetically."""
    try:
        client = _client()
        if client is None:
            return _NOT_CONFIGURED
        artists = await client._get("/artist")
        if not artists:
            return "No artists are monitored in Lidarr."
        page = max(1, page)
        ordered = sorted(artists, key=lambda a: a.get("artistName", ""))
        shown = ordered[(page - 1) * 30:page * 30]
        if not shown:
            return f"No artists on page {page} — {len(artists)} artist(s) total."
        lines = [f"Monitoring {len(artists)} artist(s) (page {page}):\n"]
        for a in shown:
            stats = a.get("statistics", {})
            albums = stats.get("albumCount", 0)
            tracks = stats.get("trackFileCount", 0)
            lines.append(f"  • {a.get('artistName', 'Unknown')} — {albums} albums, {tracks} tracks")
        remaining = len(ordered) - page * 30
        if remaining > 0:
            lines.append(f"\n  ... {remaining} more — ask for page {page + 1}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Lidarr."
    except Exception as e:
        return f"❌ Failed to list artists: {type(e).__name__}: {e}"


@tool
async def get_music_queue() -> str:
    """Check ONLY Lidarr's music download queue. For a combined view across
    all services, use check_queue_status instead."""
    try:
        client = _client()
        if client is None:
            return _NOT_CONFIGURED
        result = await client._get("/queue")
        records = result.get("records", []) if isinstance(result, dict) else result
        if not records:
            return "Lidarr download queue is empty."
        lines = [f"{len(records)} item(s) in the music queue:"]
        for r in records[:20]:
            title = r.get("title", "Unknown")
            status = r.get("status", "unknown")
            lines.append(f"  • {title} — {status}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Lidarr."
    except Exception as e:
        return f"❌ Failed to get music queue: {type(e).__name__}: {e}"
