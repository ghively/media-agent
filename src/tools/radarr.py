"""Radarr v3 API client + LangGraph tool definitions."""
import httpx
from langchain_core.tools import tool
from src.config import get_settings


class RadarrClient:
    """Async client for Radarr v3 API."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = timeout

    async def _get(self, endpoint: str, params: dict | None = None):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v3{endpoint}", headers=self.headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, endpoint: str, json_data: dict):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/v3{endpoint}", headers=self.headers, json=json_data
            )
            resp.raise_for_status()
            return resp.json()


def _client() -> RadarrClient:
    s = get_settings().radarr
    return RadarrClient(s["url"], s["api_key"])


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
async def add_movie(tmdb_id: int, title: str) -> str:
    """Add a movie to the monitored library by its TMDb ID."""
    try:
        body = {
            "tmdbId": tmdb_id,
            "title": title,
            "qualityProfileId": 1,
            "rootFolderPath": "/movies/",
            "monitored": True,
            "addOptions": {"searchForMovie": True},
        }
        await _client()._post("/movie", body)
        return f"✅ Added '{title}' (tmdbId: {tmdb_id}) to Radarr. Download search started — Emby will update automatically when the file imports."
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return f"❌ '{title}' may already be in your library, or the tmdbId is invalid."
        return f"❌ Radarr returned HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to add movie: {type(e).__name__}: {e}"


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
    """Check current Radarr download queue."""
    try:
        result = await _client()._get("/queue")
        records = result.get("records", []) if isinstance(result, dict) else result
        if not records:
            return "Radarr download queue is empty."
        lines = [f"{len(records)} item(s) in queue:\n"]
        for r in records:
            title = r.get("title", "Unknown")
            status = r.get("status", "unknown")
            lines.append(f"  • {title} — {status}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to get queue: {type(e).__name__}: {e}"


@tool
async def get_movie_history() -> str:
    """Show recent Radarr activity."""
    try:
        result = await _client()._get("/history", params={"pageSize": 15, "includeMovie": "true"})
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
