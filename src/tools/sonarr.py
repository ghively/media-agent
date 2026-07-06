"""Sonarr v3 API client + LangGraph tool definitions."""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


class SonarrClient:
    """Async client for Sonarr v3 API."""

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


def _client() -> SonarrClient:
    s = get_settings().sonarr
    return SonarrClient(s["url"], s["api_key"])


@tool
async def search_tv(query: str) -> str:
    """Search for TV shows by name. Returns matching shows with titles, years, and tvdbIds."""
    try:
        results = await _client()._get("/series/lookup", params={"term": query})
        if not results:
            return f"No TV shows found for '{query}'."
        lines = [f"Found {len(results)} result(s):\n"]
        for i, r in enumerate(results[:10], 1):
            title = r.get("title", "Unknown")
            year = r.get("year", "")
            tvdb_id = r.get("tvdbId", "N/A")
            lines.append(f"  {i}. {title} ({year}) [tvdbId: {tvdb_id}]")
        return "\n".join(lines)
    except httpx.ConnectError:
        return f"❌ Cannot connect to Sonarr."
    except httpx.TimeoutException:
        return "❌ Sonarr request timed out."
    except Exception as e:
        return f"❌ Sonarr search failed: {type(e).__name__}: {e}"


@tool
async def add_tv_show(tvdb_id: int, title: str) -> str:
    """Add a TV show to the monitored library by its TVDB ID."""
    try:
        settings = get_settings().sonarr
        body = {
            "tvdbId": tvdb_id,
            "title": title,
            "qualityProfileId": settings.get("quality_profile_id", 4),
            "rootFolderPath": settings.get("root_folder_path", "/your/media/tv"),
            "monitored": True,
            "addOptions": {"searchForMissingEpisodes": True},
            "seriesType": "standard",
        }
        await _client()._post("/series", body)
        return f"✅ Added '{title}' (tvdbId: {tvdb_id}) to Sonarr. Episode search started — Emby will update automatically when episodes import."
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return f"❌ '{title}' may already be in your library, or the tvdbId is invalid."
        return f"❌ Sonarr returned HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to add show: {type(e).__name__}: {e}"


@tool
async def list_tv_shows() -> str:
    """List all monitored TV shows."""
    try:
        series = await _client()._get("/series")
        if not series:
            return "No TV shows are currently monitored."
        lines = [f"Monitoring {len(series)} show(s):\n"]
        for s in sorted(series, key=lambda x: x.get("title", "")):
            stats = s.get("statistics", {})
            seasons = stats.get("seasonCount", 0)
            episodes = stats.get("episodeFileCount", 0)
            lines.append(f"  • {s['title']} — {seasons} seasons, {episodes} episodes")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to list shows: {type(e).__name__}: {e}"


@tool
async def get_tv_queue() -> str:
    """Check current Sonarr download queue."""
    try:
        result = await _client()._get("/queue")
        records = result.get("records", []) if isinstance(result, dict) else result
        if not records:
            return "Sonarr download queue is empty."
        lines = [f"{len(records)} item(s) in queue:\n"]
        for r in records:
            title = r.get("title", "Unknown")
            status = r.get("status", "unknown")
            size = float(r.get("size", 0) or 0)
            left = float(r.get("sizeleft", 0) or 0)
            pct = f" — {round((1 - left / size) * 100)}%" if size > 0 else ""
            lines.append(f"  • {title} — {status}{pct}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to get queue: {type(e).__name__}: {e}"


@tool
async def get_tv_history() -> str:
    """Show recent Sonarr activity (grabs and imports)."""
    try:
        result = await _client()._get("/history", params={"pageSize": 15, "includeSeries": "true"})
        records = result.get("records", []) if isinstance(result, dict) else []
        if not records:
            return "No recent Sonarr activity."
        lines = [f"Recent activity ({len(records)} events):\n"]
        for r in records[:15]:
            etype = r.get("eventType", "unknown")
            series = r.get("series", {}).get("title", "Unknown")
            lines.append(f"  • [{etype}] {series}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to get history: {type(e).__name__}: {e}"


@tool
async def search_missing_episodes() -> str:
    """Trigger a search for missing/wanted episodes."""
    try:
        await _client()._post("/command", {"name": "MissingEpisodeSearch"})
        return "✅ Missing episodes search triggered."
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to trigger search: {type(e).__name__}: {e}"


@tool
async def get_tv_calendar() -> str:
    """Show upcoming/airing episodes (next 7 days)."""
    try:
        from datetime import datetime, timedelta
        start = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        results = await _client()._get("/calendar", params={"start": start, "end": end, "includeSeries": "true"})
        if not results:
            return "No episodes airing in the next 7 days."
        lines = [f"Upcoming episodes ({len(results)}):\n"]
        for ep in sorted(results, key=lambda x: x.get("airDateUtc", "")):
            series = ep.get("series", {}).get("title", "Unknown")
            season = ep.get("seasonNumber", 0)
            number = ep.get("episodeNumber", 0)
            title = ep.get("title", "TBA")
            airdate = ep.get("airDate", "")[:10]
            lines.append(f"  • {airdate} — {series} S{season:02d}E{number:02d} - {title}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to get calendar: {type(e).__name__}: {e}"


@tool
async def get_tv_health() -> str:
    """Check Sonarr health status."""
    try:
        issues = await _client()._get("/health")
        if not issues:
            return "✅ Sonarr health: all checks passing."
        lines = [f"⚠️ Sonarr health issues ({len(issues)}):\n"]
        for issue in issues:
            itype = issue.get("type", "unknown")
            msg = issue.get("message", "no message")
            lines.append(f"  • [{itype}] {msg}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Health check failed: {type(e).__name__}: {e}"


@tool
async def sonarr_list_quality_profiles() -> str:
    """List available quality profiles for TV shows."""
    try:
        profiles = await _client()._get("/qualityprofile")
        if not profiles:
            return "No quality profiles found."
        lines = ["Available Sonarr quality profiles:\n"]
        for p in profiles:
            name = p.get("name", "Unknown")
            pid = p.get("id", "N/A")
            lines.append(f"  • {name} (ID: {pid})")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to list quality profiles: {type(e).__name__}: {e}"


@tool
async def sonarr_list_root_folders() -> str:
    """List available root folders for TV shows."""
    try:
        folders = await _client()._get("/rootfolder")
        if not folders:
            return "No root folders found."
        lines = ["Available Sonarr root folders:\n"]
        for f in folders:
            path = f.get("path", "Unknown")
            fid = f.get("id", "N/A")
            free_space = f.get("freeSpace", "0")
            lines.append(f"  • {path} (ID: {fid}, Free: {free_space})")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to list root folders: {type(e).__name__}: {e}"


@tool
async def refresh_tv_show(series_id: int) -> str:
    """Refresh a TV show's metadata and disk scan."""
    try:
        result = await _client()._post("/command", {"name": "RefreshSeries", "seriesId": series_id})
        return f"✅ Refresh triggered for series ID {series_id}."
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to refresh TV show: {type(e).__name__}: {e}"


@tool
async def search_season(series_id: int, season_number: int) -> str:
    """Search for all episodes in a specific season."""
    try:
        result = await _client()._post("/command", {
            "name": "SeasonSearch",
            "seriesId": series_id,
            "seasonNumber": season_number
        })
        return f"✅ Season search triggered for series ID {series_id}, season {season_number}."
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to search season: {type(e).__name__}: {e}"
