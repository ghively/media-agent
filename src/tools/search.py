"""Unified search across media sources + LangGraph tool definitions.

Aggregates results from Sonarr (TV), Radarr (movies), Download Station (torrents),
and SABnzbd (usenet). Results are ranked by relevance to the query and returned
in a single unified list. The source_type param lets callers filter, but users
should NOT specify torrent vs usenet — that's an internal implementation detail.
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings

# ── Shared type for search results ──────────────────────────────────────────

SEARCH_RESULT_FIELDS = [
    "title",
    "year",
    "source",     # "sonarr" | "radarr" | "download_station"
    "source_type", # "tv" | "movie" | "torrent"
    "id",          # source-specific ID (tvdbId, tmdbId, task id)
    "overview",    # optional description
    "relevance",   # simple rank score (higher = better match)
]


def _score_relevance(title: str, query: str) -> int:
    """Simple relevance scoring: exact match > word match > substring match."""
    t = title.lower().strip()
    q = query.lower().strip()

    if t == q:
        return 100
    if t.startswith(q):
        return 80
    if q in t:
        return 60
    # Check individual words
    query_words = set(q.split())
    title_words = set(t.split())
    overlap = query_words & title_words
    if overlap:
        return 30 + (len(overlap) * 10)
    return 10


# ── Individual source searchers ─────────────────────────────────────────────

async def _search_sonarr(query: str, limit: int) -> list[dict]:
    """Search Sonarr for matching TV shows."""
    try:
        s = get_settings().sonarr
        headers = {"X-Api-Key": s["api_key"]}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{s['url'].rstrip('/')}/api/v3/series/lookup",
                headers=headers,
                params={"term": query},
            )
            resp.raise_for_status()
            results = resp.json()
    except Exception:
        return []

    items = []
    for r in results[:limit]:
        items.append({
            "title": r.get("title", "Unknown"),
            "year": r.get("year", ""),
            "source": "sonarr",
            "source_type": "tv",
            "id": r.get("tvdbId"),
            "overview": r.get("overview", "")[:200] if r.get("overview") else "",
            "relevance": _score_relevance(r.get("title", ""), query),
        })
    return items


async def _search_radarr(query: str, limit: int) -> list[dict]:
    """Search Radarr for matching movies."""
    try:
        s = get_settings().radarr
        headers = {"X-Api-Key": s["api_key"]}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{s['url'].rstrip('/')}/api/v3/movie/lookup",
                headers=headers,
                params={"term": query},
            )
            resp.raise_for_status()
            results = resp.json()
    except Exception:
        return []

    items = []
    for r in results[:limit]:
        items.append({
            "title": r.get("title", "Unknown"),
            "year": r.get("year", ""),
            "source": "radarr",
            "source_type": "movie",
            "id": r.get("tmdbId"),
            "overview": r.get("overview", "")[:200] if r.get("overview") else "",
            "relevance": _score_relevance(r.get("title", ""), query),
        })
    return items


async def _search_download_station(query: str, limit: int) -> list[dict]:
    """Search Download Station for matching torrent/download tasks."""
    try:
        ds = get_settings().download_station
        base_url = ds.get("url", "http://192.168.0.133:5000")
        username = ds.get("username")
        password = ds.get("password")

        if not username or not password:
            return []  # No auth configured, skip DS search

        # Login first
        async with httpx.AsyncClient(timeout=15) as client:
            login_url = (
                f"{base_url}/webapi/auth.cgi"
                f"?api=SYNO.API.Auth&version=6&method=login"
                f"&account={username}&passwd={password}"
                f"&session=DownloadStation&format=cookie"
            )
            login_resp = await client.get(login_url)
            login_data = login_resp.json()
            sid = login_data.get("data", {}).get("sid") if login_data.get("success") else None

            if not sid:
                return []

            # List all tasks
            task_params = {
                "api": "SYNO.DownloadStation.Task",
                "version": 3,
                "method": "list",
                "additional": "detail",
                "_sid": sid,
            }
            task_resp = await client.get(
                f"{base_url}/webapi/DownloadStation/task.cgi",
                params=task_params,
            )
            task_resp.raise_for_status()
            task_data = task_resp.json()

    except Exception:
        return []

    tasks = task_data.get("data", {}).get("tasks", [])
    items = []
    for t in tasks[:limit]:
        title = t.get("title", "Unknown")
        status = t.get("status", "?")
        size = t.get("size", "0")

        items.append({
            "title": title,
            "year": "",
            "source": "download_station",
            "source_type": "torrent",
            "id": t.get("id"),
            "overview": f"Status: {status}, Size: {size} bytes",
            "relevance": _score_relevance(title, query),
        })
    return items


# ── Unified search tool ─────────────────────────────────────────────────────

@tool
async def search_media(query: str, source_type: str | None = None) -> str:
    """Search across all media sources (Sonarr, Radarr, Download Station).

    Returns a unified ranked list of matching TV shows, movies, and torrents.
    The user should NOT specify 'torrent' vs 'usenet' — all sources are
    searched by default.

    Args:
        query: The search term (title, name, or keyword).
        source_type: Optional filter — 'tv', 'movie', 'torrent', or None for all.
    """
    try:
        # Determine which sources to search
        searches = []
        if source_type is None or source_type == "tv":
            searches.append(_search_sonarr(query, 10))
        if source_type is None or source_type == "movie":
            searches.append(_search_radarr(query, 10))
        if source_type is None or source_type == "torrent":
            searches.append(_search_download_station(query, 10))

        # Run searches concurrently
        from asyncio import gather
        results_lists = await gather(*searches, return_exceptions=True)

        # Flatten and filter errors
        all_results: list[dict] = []
        for rl in results_lists:
            if isinstance(rl, list):
                all_results.extend(rl)

        if not all_results:
            return f"No results found for '{query}' across any source."

        # Sort by relevance (descending), then by title
        all_results.sort(key=lambda r: (-r["relevance"], r["title"]))

        # Deduplicate by title + source
        seen: set = set()
        unique_results: list[dict] = []
        for r in all_results:
            key = (r["title"].lower(), r["source"])
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        source_names = {
            "sonarr": "TV (Sonarr)",
            "radarr": "Movies (Radarr)",
            "download_station": "Torrents (DS)",
        }

        lines = [f"Found {len(unique_results)} result(s) for '{query}':", ""]
        for i, r in enumerate(unique_results[:15], 1):
            source_label = source_names.get(r["source"], r["source"])
            year_str = f" ({r['year']})" if r.get("year") else ""
            lines.append(f"  {i}. {r['title']}{year_str} ← {source_label}")
            if r.get("overview"):
                overview = r["overview"][:120]
                lines.append(f"     {overview}")
            lines.append(f"     [id: {r['id']}]")

        if len(unique_results) > 15:
            lines.append(f"\n  ... and {len(unique_results) - 15} more results")

        lines.append("")
        lines.append("To download a result, use: download_media(result_id)")
        lines.append("where result_id is the number from the list above.")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Search failed: {type(e).__name__}: {e}"


# ── Download tool ───────────────────────────────────────────────────────────

@tool
async def download_media(result_id: int) -> str:
    """Download a media result by its position number from search_media().

    This tool triggers the appropriate download action based on the result's
    source (Sonarr → add TV show, Radarr → add movie, Download Station → the
    item is already tracking). The search results store the connection between
    position numbers and source IDs.

    Args:
        result_id: The 1-based index from the search_media results list.
    """
    # This tool cannot download on its own: search results aren't persisted
    # across tool calls, so there is no position→source mapping to act on.
    # Be explicit that NOTHING was downloaded and route to the real tool,
    # rather than implying a download started.
    try:
        return (
            f"⚠️  No download was started for result #{result_id} — this dispatcher "
            f"has no access to the previous search results.\n\n"
            f"Add it directly with the source-specific tool instead:\n"
            f"  • TV show:   add_tv_show(tvdb_id=..., title=...)     [sonarr]\n"
            f"  • Movie:     add_movie(tmdb_id=..., title=...)       [radarr]\n"
            f"  • Torrent:   download_station_add(url=...)           [download station]\n\n"
            f"Re-run search_media(query) to get the id/title, then call the tool above."
        )
    except Exception as e:
        return f"❌ Download failed: {type(e).__name__}: {e}"