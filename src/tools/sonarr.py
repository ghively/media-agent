"""Sonarr v3 API client + LangGraph tool definitions."""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


def _transport() -> httpx.AsyncHTTPTransport:
    """Shared transport with connect retries — home-lab services restart often."""
    return httpx.AsyncHTTPTransport(retries=2)


class SonarrClient:
    """Async client for Sonarr v3 API."""

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


def _client() -> SonarrClient:
    s = get_settings().sonarr
    return SonarrClient(s["url"], s["api_key"])


async def _resolve_defaults(client: SonarrClient,
                            quality_profile: str = "",
                            root_folder: str = "") -> tuple[int, str]:
    """Resolve quality profile id and root folder path against the live
    instance. Sonarr validates both on POST /series — hardcoded values 400
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
        cfg = get_settings().sonarr.get("quality_profile", "")
        matched = [p for p in profiles if p.get("name", "").lower() == str(cfg).lower()]
        profile_id = (matched[0] if matched else profiles[0])["id"]

    folders = await client._get("/rootfolder")
    if not folders:
        raise ValueError("Sonarr has no root folders configured.")
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
async def add_tv_show(tvdb_id: int, title: str,
                      quality_profile: str = "", root_folder: str = "") -> str:
    """Add a TV show to the monitored library by its TVDB ID.

    Args:
        tvdb_id: TVDB id from search_tv results.
        title: Show title.
        quality_profile: Optional quality profile NAME (see list_tv_profiles).
            Defaults to the configured/first profile.
        root_folder: Optional root folder path. Defaults to the first one.
    """
    try:
        client = _client()
        profile_id, folder_path = await _resolve_defaults(
            client, quality_profile, root_folder)
        body = {
            "tvdbId": tvdb_id,
            "title": title,
            "qualityProfileId": profile_id,
            "rootFolderPath": folder_path,
            "monitored": True,
            "addOptions": {"searchForMissingEpisodes": True},
            "seriesType": "standard",
        }
        await client._post("/series", body)
        return f"✅ Added '{title}' (tvdbId: {tvdb_id}) to {folder_path}. Searching for episodes..."
    except ValueError as e:
        return f"❌ {e}"
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return (f"❌ Sonarr rejected the add (HTTP 400): "
                    f"{e.response.text[:300]}")
        return f"❌ Sonarr returned HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to add show: {type(e).__name__}: {e}"


@tool
async def list_tv_profiles() -> str:
    """List Sonarr quality profiles and root folders (for use with add_tv_show)."""
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
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to list profiles: {type(e).__name__}: {e}"


@tool
async def remove_tv_show(title: str, delete_files: bool = False) -> str:
    """Remove a TV show from Sonarr by its title.

    Args:
        title: Exact or unambiguous partial title of a monitored show.
        delete_files: Also delete the show's files from disk (default False —
            only stops monitoring).
    """
    try:
        client = _client()
        series = await client._get("/series")
        matches = [s for s in series
                   if title.lower() in s.get("title", "").lower()]
        exact = [s for s in matches if s.get("title", "").lower() == title.lower()]
        if exact:
            matches = exact
        if not matches:
            return f"❌ No monitored show matches '{title}'."
        if len(matches) > 1:
            names = "\n".join(f"  • {s['title']}" for s in matches[:10])
            return f"⚠️ Multiple shows match '{title}' — be more specific:\n{names}"
        show = matches[0]
        async with httpx.AsyncClient(timeout=30, transport=_transport()) as http:
            resp = await http.delete(
                f"{client.base_url}/api/v3/series/{show['id']}",
                headers=client.headers,
                params={"deleteFiles": str(bool(delete_files)).lower()},
            )
            resp.raise_for_status()
        files_note = " and deleted its files" if delete_files else " (files kept on disk)"
        return f"✅ Removed '{show['title']}' from Sonarr{files_note}."
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to remove show: {type(e).__name__}: {e}"


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
    """Check current Sonarr download queue with full progress details."""
    try:
        result = await _client()._get("/queue")
        records = result.get("records", []) if isinstance(result, dict) else result
        if not records:
            return "Sonarr download queue is empty."
        lines = [f"Sonarr queue — {len(records)} item(s):\n"]
        for r in records:
            title = r.get("title", "Unknown")
            status = r.get("status", "unknown")
            size = r.get("size", 0) or 0
            sizeleft = r.get("sizeleft", 0) or 0
            timeleft = r.get("timeleft", "")
            quality = r.get("quality", {}).get("quality", {}).get("name", "")
            dl_status = r.get("trackedDownloadStatus", "")

            if size > 0:
                done_mb = (size - sizeleft) / (1024 * 1024)
                total_mb = size / (1024 * 1024)
                pct = round(((size - sizeleft) / size) * 100)
                size_str = f"{done_mb:.0f}/{total_mb:.0f} MB ({pct}%)"
            else:
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
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to get queue: {type(e).__name__}: {e}"


@tool
async def get_tv_history() -> str:
    """Show recent Sonarr activity (grabs and imports)."""
    try:
        # includeSeries embeds the series object (absent by default)
        result = await _client()._get(
            "/history", params={"pageSize": 15, "includeSeries": "true"})
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
        # Sonarr's command name is singular: MissingEpisodeSearch
        await _client()._post("/command", {"name": "MissingEpisodeSearch", "monitored": True})
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
        results = await _client()._get(
            "/calendar", params={"start": start, "end": end, "includeSeries": "true"})
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
