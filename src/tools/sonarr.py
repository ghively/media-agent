"""Sonarr v3 API tools."""
import httpx
from langchain_core.tools import tool

from src.config import get_settings
from src.tools.arr import ArrClient

# Backwards-compatible alias
SonarrClient = ArrClient


def _client() -> ArrClient:
    s = get_settings().sonarr
    if not s.get("url") or not s.get("api_key"):
        raise RuntimeError(
            "Sonarr is not configured — set services.sonarr.url and api_key "
            "in config/settings.yaml"
        )
    return ArrClient(s["url"], s["api_key"])


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
        return "❌ Cannot connect to Sonarr."
    except httpx.TimeoutException:
        return "❌ Sonarr request timed out."
    except Exception as e:
        return f"❌ Sonarr search failed: {type(e).__name__}: {e}"


@tool
async def add_tv_show(tvdb_id: int, title: str) -> str:
    """Add a TV show to the monitored library by its TVDB ID."""
    try:
        s = get_settings().sonarr
        body = {
            "tvdbId": tvdb_id,
            "title": title,
            "qualityProfileId": s.get("quality_profile_id", 1),
            "rootFolderPath": s.get("root_folder", "/tv/"),
            "monitored": True,
            "addOptions": {"searchForMissingEpisodes": True},
            "seriesType": "standard",
        }
        await _client()._post("/series", body)
        return f"✅ Added '{title}' (tvdbId: {tvdb_id}) to the library. Searching for episodes..."
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
            size = r.get("size") or 0
            sizeleft = r.get("sizeleft") or 0
            if size:
                pct = (1 - sizeleft / size) * 100
                lines.append(f"  • {title} — {status} ({pct:.0f}%)")
            else:
                lines.append(f"  • {title} — {status}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to get queue: {type(e).__name__}: {e}"


@tool
async def get_tv_history() -> str:
    """Show recent Sonarr activity (grabs and imports)."""
    try:
        result = await _client()._get("/history", params={"pageSize": 15})
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
        await _client()._post("/command", {"name": "MissingEpisodesSearch"})
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
        results = await _client()._get("/calendar", params={"start": start, "end": end})
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
