"""Radarr v3 API client + LangGraph tool definitions."""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


def _transport() -> httpx.AsyncHTTPTransport:
    """Shared transport with connect retries — home-lab services restart often."""
    return httpx.AsyncHTTPTransport(retries=2)


class RadarrClient:
    """Async client for Radarr v3 API."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = timeout

    async def _get(self, endpoint: str, params: dict | None = None):
        async with httpx.AsyncClient(timeout=self.timeout, transport=_transport()) as client:
            resp = await client.get(
                f"{self.base_url}/api/v3{endpoint}", headers=self.headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, endpoint: str, json_data: dict):
        async with httpx.AsyncClient(timeout=self.timeout, transport=_transport()) as client:
            resp = await client.post(
                f"{self.base_url}/api/v3{endpoint}", headers=self.headers, json=json_data
            )
            resp.raise_for_status()
            return resp.json()


def _client() -> RadarrClient:
    s = get_settings().radarr
    return RadarrClient(s["url"], s["api_key"])


async def _resolve_defaults(client: RadarrClient,
                            quality_profile: str = "",
                            root_folder: str = "") -> tuple[int, str]:
    """Resolve quality profile id and root folder path against the live
    instance. Radarr validates both on POST /movie — hardcoded values 400
    on any install whose profiles/folders differ."""
    profiles = await client._get("/qualityprofile")
    if quality_profile:
        matched = [p for p in profiles
                   if p.get("name", "").lower() == quality_profile.lower()]
        if not matched:
            names = ", ".join(p.get("name", "?") for p in profiles)
            raise ValueError(f"No quality profile named '{quality_profile}'. Available: {names}")
        profile_id = matched[0]["id"]
    else:
        cfg = get_settings().radarr.get("quality_profile", "")
        matched = [p for p in profiles if p.get("name", "").lower() == str(cfg).lower()]
        profile_id = (matched[0] if matched else profiles[0])["id"]

    folders = await client._get("/rootfolder")
    if not folders:
        raise ValueError("Radarr has no root folders configured.")
    if root_folder:
        matched = [f for f in folders if f.get("path", "").rstrip("/") == root_folder.rstrip("/")]
        if not matched:
            paths = ", ".join(f.get("path", "?") for f in folders)
            raise ValueError(f"No root folder '{root_folder}'. Available: {paths}")
        folder_path = matched[0]["path"]
    else:
        folder_path = folders[0]["path"]
    return profile_id, folder_path


@tool
async def search_movie(query: str) -> str:
    """Search for movies by name. Returns matching movies with titles, years, and tmdbIds."""
    try:
        results = await _client()._get("/movie/lookup", params={"term": query})
        if not results:
            return f"No movies found for '{query}'."
        lines = [f"Found {len(results)} result(s):\n"]
        for i, r in enumerate(results[:10], 1):
            title = r.get("title", "Unknown")
            year = r.get("year", "")
            tmdb_id = r.get("tmdbId", "N/A")
            lines.append(f"  {i}. {title} ({year}) [tmdbId: {tmdb_id}]")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except httpx.TimeoutException:
        return "❌ Radarr request timed out."
    except Exception as e:
        return f"❌ Radarr search failed: {type(e).__name__}: {e}"


@tool
async def add_movie(tmdb_id: int, title: str,
                    quality_profile: str = "", root_folder: str = "") -> str:
    """Add a movie to the monitored library by its TMDb ID.

    Args:
        tmdb_id: TMDb id from search_movie results.
        title: Movie title.
        quality_profile: Optional quality profile NAME (see list_movie_profiles).
            Defaults to the configured/first profile.
        root_folder: Optional root folder path. Defaults to the first one.
    """
    try:
        client = _client()
        profile_id, folder_path = await _resolve_defaults(
            client, quality_profile, root_folder)
        body = {
            "tmdbId": tmdb_id,
            "title": title,
            "qualityProfileId": profile_id,
            "rootFolderPath": folder_path,
            "monitored": True,
            # default enum is 'tba' (most restrictive); 'announced' lets
            # Radarr start grabbing as soon as a release exists
            "minimumAvailability": "announced",
            "addOptions": {"searchForMovie": True},
        }
        await client._post("/movie", body)
        return f"✅ Added '{title}' (tmdbId: {tmdb_id}) to {folder_path}. Searching..."
    except ValueError as e:
        return f"❌ {e}"
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return (f"❌ Radarr rejected the add (HTTP 400): "
                    f"{e.response.text[:300]}")
        return f"❌ Radarr returned HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to add movie: {type(e).__name__}: {e}"


@tool
async def list_movie_profiles() -> str:
    """List Radarr quality profiles and root folders (for use with add_movie)."""
    try:
        client = _client()
        profiles = await client._get("/qualityprofile")
        folders = await client._get("/rootfolder")
        lines = ["Quality profiles:"]
        for p in profiles:
            lines.append(f"  • {p.get('name', '?')} (id {p.get('id', '?')})")
        lines.append("Root folders:")
        for f in folders:
            free = f.get("freeSpace", 0) / (1024 ** 3)
            lines.append(f"  • {f.get('path', '?')} ({free:.0f} GB free)")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to list profiles: {type(e).__name__}: {e}"


@tool
async def remove_movie(title: str, delete_files: bool = False) -> str:
    """Remove a movie from Radarr by its title.

    Args:
        title: Exact or unambiguous partial title of a monitored movie.
        delete_files: Also delete the movie file from disk (default False —
            only stops monitoring).
    """
    try:
        client = _client()
        movies = await client._get("/movie")
        matches = [m for m in movies
                   if title.lower() in m.get("title", "").lower()]
        exact = [m for m in matches if m.get("title", "").lower() == title.lower()]
        if exact:
            matches = exact
        if not matches:
            return f"❌ No monitored movie matches '{title}'."
        if len(matches) > 1:
            names = "\n".join(f"  • {m['title']} ({m.get('year', '?')})" for m in matches[:10])
            return f"⚠️ Multiple movies match '{title}' — be more specific:\n{names}"
        movie = matches[0]
        async with httpx.AsyncClient(timeout=30, transport=_transport()) as http:
            resp = await http.delete(
                f"{client.base_url}/api/v3/movie/{movie['id']}",
                headers=client.headers,
                params={"deleteFiles": str(bool(delete_files)).lower()},
            )
            resp.raise_for_status()
        files_note = " and deleted its files" if delete_files else " (files kept on disk)"
        return f"✅ Removed '{movie['title']}' from Radarr{files_note}."
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to remove movie: {type(e).__name__}: {e}"


@tool
async def list_movies() -> str:
    """List all monitored movies."""
    try:
        movies = await _client()._get("/movie")
        if not movies:
            return "No movies are currently monitored."
        lines = [f"Monitoring {len(movies)} movie(s):\n"]
        for m in sorted(movies, key=lambda x: x.get("title", ""))[:30]:
            title = m.get("title", "Unknown")
            year = m.get("year", "")
            has_file = "✓" if m.get("hasFile") else "✗"
            lines.append(f"  • {title} ({year}) [{has_file}]")
        if len(movies) > 30:
            lines.append(f"\n  ... and {len(movies) - 30} more")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to list movies: {type(e).__name__}: {e}"


@tool
async def get_movie_queue() -> str:
    """Check current Radarr download queue with full progress details."""
    try:
        result = await _client()._get("/queue")
        records = result.get("records", []) if isinstance(result, dict) else result
        if not records:
            return "Radarr download queue is empty."
        lines = [f"Radarr queue — {len(records)} item(s):\n"]
        for r in records:
            title = r.get("title", "Unknown")
            status = r.get("status", "unknown")
            size = r.get("size", 0) or 0
            sizeleft = r.get("sizeleft", 0) or 0
            timeleft = r.get("timeleft", "")
            eta = r.get("estimatedCompletionTime", "")
            quality = r.get("quality", {}).get("quality", {}).get("name", "")
            dl_status = r.get("trackedDownloadStatus", "")

            if size > 0:
                done_mb = (size - sizeleft) / (1024 * 1024)
                total_mb = size / (1024 * 1024)
                pct = round(((size - sizeleft) / size) * 100)
                size_str = f"{done_mb:.0f}/{total_mb:.0f} MB ({pct}%)"
            else:
                pct = 0
                size_str = "?"

            parts = [f"  • {title}"]
            if quality:
                parts.append(f"[{quality}]")
            parts.append(f"— {status}")
            if size > 0:
                parts.append(f"({size_str})")
            if timeleft and timeleft != "0:00:00":
                parts.append(f"~{timeleft} left")
            if dl_status == "warning":
                parts.append("⚠️")
            lines.append(" ".join(parts))
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to get queue: {type(e).__name__}: {e}"


@tool
async def get_movie_history() -> str:
    """Show recent Radarr activity."""
    try:
        # includeMovie embeds the movie object (absent by default)
        result = await _client()._get(
            "/history", params={"pageSize": 15, "includeMovie": "true"})
        records = result.get("records", []) if isinstance(result, dict) else []
        if not records:
            return "No recent Radarr activity."
        lines = [f"Recent activity ({len(records)} events):\n"]
        for r in records[:15]:
            etype = r.get("eventType", "unknown")
            movie = r.get("movie", {}).get("title", "Unknown")
            lines.append(f"  • [{etype}] {movie}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to get history: {type(e).__name__}: {e}"


@tool
async def search_missing_movies() -> str:
    """Trigger a search for missing/wanted movies."""
    try:
        await _client()._post("/command", {"name": "MissingMoviesSearch"})
        return "✅ Missing movies search triggered."
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to trigger search: {type(e).__name__}: {e}"


@tool
async def get_movie_health() -> str:
    """Check Radarr health status."""
    try:
        issues = await _client()._get("/health")
        if not issues:
            return "✅ Radarr health: all checks passing."
        lines = [f"⚠️ Radarr health issues ({len(issues)}):\n"]
        for issue in issues:
            itype = issue.get("type", "unknown")
            msg = issue.get("message", "no message")
            lines.append(f"  • [{itype}] {msg}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Health check failed: {type(e).__name__}: {e}"
