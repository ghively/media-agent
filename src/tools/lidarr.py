"""Lidarr v1 API client + tools (music library management).

Registered only when ``services.lidarr`` is configured in settings.
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


def _transport() -> httpx.AsyncHTTPTransport:
    return httpx.AsyncHTTPTransport(retries=2)


class LidarrClient:
    """Async client for Lidarr v1 API."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = timeout

    async def _get(self, endpoint: str, params: dict | None = None):
        async with httpx.AsyncClient(timeout=self.timeout, transport=_transport()) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1{endpoint}", headers=self.headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, endpoint: str, json_data: dict):
        async with httpx.AsyncClient(timeout=self.timeout, transport=_transport()) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1{endpoint}", headers=self.headers, json=json_data
            )
            resp.raise_for_status()
            return resp.json()


def _client() -> LidarrClient:
    s = get_settings().lidarr
    return LidarrClient(s["url"], s["api_key"])


@tool
async def search_artist(query: str) -> str:
    """Search for music artists by name (Lidarr). Returns matches with
    MusicBrainz ids for use with add_artist."""
    try:
        results = await _client()._get("/artist/lookup", params={"term": query})
        if not results:
            return f"No artists found for '{query}'."
        lines = [f"Found {len(results)} artist(s):\n"]
        for i, r in enumerate(results[:10], 1):
            name = r.get("artistName", "Unknown")
            mbid = r.get("foreignArtistId", "?")
            genres = ", ".join(r.get("genres", [])[:3])
            extra = f" — {genres}" if genres else ""
            lines.append(f"  {i}. {name}{extra} [mbid: {mbid}]")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Lidarr."
    except Exception as e:
        return f"❌ Lidarr search failed: {type(e).__name__}: {e}"


@tool
async def add_artist(mbid: str, name: str) -> str:
    """Add an artist to the monitored music library by MusicBrainz id
    (from search_artist). Quality/metadata profiles and root folder are
    resolved from the live Lidarr instance."""
    try:
        client = _client()
        quality = await client._get("/qualityprofile")
        metadata = await client._get("/metadataprofile")
        folders = await client._get("/rootfolder")
        if not (quality and metadata and folders):
            return "❌ Lidarr has no quality/metadata profiles or root folders configured."
        body = {
            "foreignArtistId": mbid,
            "artistName": name,
            "qualityProfileId": quality[0]["id"],
            "metadataProfileId": metadata[0]["id"],
            "rootFolderPath": folders[0]["path"],
            "monitored": True,
            "addOptions": {"searchForMissingAlbums": True},
        }
        await client._post("/artist", body)
        return f"✅ Added '{name}' to {folders[0]['path']}. Searching for albums..."
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return f"❌ Lidarr rejected the add (HTTP 400): {e.response.text[:300]}"
        return f"❌ Lidarr returned HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Lidarr."
    except Exception as e:
        return f"❌ Failed to add artist: {type(e).__name__}: {e}"


@tool
async def list_artists() -> str:
    """List all monitored music artists (Lidarr)."""
    try:
        artists = await _client()._get("/artist")
        if not artists:
            return "No artists are currently monitored."
        lines = [f"Monitoring {len(artists)} artist(s):\n"]
        for a in sorted(artists, key=lambda x: x.get("artistName", ""))[:40]:
            stats = a.get("statistics", {})
            albums = stats.get("albumCount", 0)
            tracks = stats.get("trackFileCount", 0)
            lines.append(f"  • {a.get('artistName', '?')} — {albums} albums, {tracks} tracks")
        if len(artists) > 40:
            lines.append(f"\n  ... and {len(artists) - 40} more")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Lidarr."
    except Exception as e:
        return f"❌ Failed to list artists: {type(e).__name__}: {e}"


@tool
async def get_music_queue() -> str:
    """Check the Lidarr music download queue."""
    try:
        result = await _client()._get("/queue")
        records = result.get("records", []) if isinstance(result, dict) else result
        if not records:
            return "Lidarr download queue is empty."
        lines = [f"{len(records)} item(s) in queue:\n"]
        for r in records[:20]:
            title = r.get("title", "Unknown")
            status = r.get("status", "unknown")
            lines.append(f"  • {title} — {status}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Lidarr."
    except Exception as e:
        return f"❌ Failed to get queue: {type(e).__name__}: {e}"
