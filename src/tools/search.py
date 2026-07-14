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
            # Kept for the request/approval loop's auto-approve rules
            # ("anything under 3 seasons", "genre anime").
            "genres": r.get("genres") or [],
            "season_count": len([s for s in (r.get("seasons") or [])
                                 if s.get("seasonNumber", 0) > 0]) or None,
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
            "genres": r.get("genres") or [],
        })
    return items


async def _search_download_station(query: str, limit: int) -> list[dict]:
    """Search Download Station for matching torrent/download tasks."""
    try:
        ds = get_settings().download_station
        if not ds.get("username") or not ds.get("password"):
            return []  # No auth configured, skip DS search

        # Reuse the hardened Download Station client: credentials go in the
        # POST body (never the URL query string) and it logs in/out per call.
        from src.tools.download_station import _client
        task_data = await _client()._task_api("list", additional="detail")
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
            id_prefix = "tmdbId" if r["source"] == "radarr" else "tvdbId" if r["source"] == "sonarr" else "id"
            lines.append(f"     [{id_prefix}: {r['id']}]")

        if len(unique_results) > 15:
            lines.append(f"\n  ... and {len(unique_results) - 15} more results")

        lines.append("")
        lines.append("To download: use the appropriate add tool:")
        lines.append("  • Movies: add_movie(tmdb_id=N, title=\"...\")")
        lines.append("  • TV:     add_tv_show(tvdb_id=N, title=\"...\")")
        lines.append("The tmdbId / tvdbId numbers are shown in brackets above.")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Search failed: {type(e).__name__}: {e}"


# ── Download tool ───────────────────────────────────────────────────────────

@tool
async def download_media(source: str, title: str, source_id: int) -> str:
    """Download media by specifying the source and ID directly.

    Args:
        source: 'movie' for Radarr, 'tv' for Sonarr
        title: The title of the media
        source_id: tmdbId for movies, tvdbId for TV shows
    """
    try:
        if source.lower() == "movie":
            from src.tools.radarr import add_movie
            result = await add_movie.ainvoke({"tmdb_id": source_id, "title": title})
            return result
        elif source.lower() == "tv":
            from src.tools.sonarr import add_tv_show
            result = await add_tv_show.ainvoke({"tvdb_id": source_id, "title": title})
            return result
        else:
            return f"❌ Unknown source '{source}'. Use 'movie' or 'tv'."
    except Exception as e:
        return f"❌ Download failed: {type(e).__name__}: {e}"