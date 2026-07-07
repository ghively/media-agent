"""Unified search across media sources + LangGraph tool definitions.

Aggregates results from Sonarr (TV), Radarr (movies), and Download Station
(torrents). Results are ranked by relevance to the query and returned in a
single numbered list. The most recent search results are cached so
`download_media(result_id)` can act on a numbered result directly.
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings

# Cache of the most recent search_media results, so download_media can
# resolve a 1-based result number back to a concrete item.
_last_results: list[dict] = []


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

async def _search_arr(service: str, endpoint: str, source_type: str,
                      id_field: str, query: str, limit: int) -> list[dict]:
    """Search a Sonarr/Radarr lookup endpoint for matching items."""
    try:
        s = get_settings().service(service)
        if not s.get("url"):
            return []
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{s['url'].rstrip('/')}/api/v3{endpoint}",
                headers={"X-Api-Key": s.get("api_key", "")},
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
            "source": service,
            "source_type": source_type,
            "id": r.get(id_field),
            "overview": (r.get("overview") or "")[:200],
            "relevance": _score_relevance(r.get("title", ""), query),
        })
    return items


async def _search_sonarr(query: str, limit: int) -> list[dict]:
    return await _search_arr("sonarr", "/series/lookup", "tv", "tvdbId", query, limit)


async def _search_radarr(query: str, limit: int) -> list[dict]:
    return await _search_arr("radarr", "/movie/lookup", "movie", "tmdbId", query, limit)


async def _search_download_station(query: str, limit: int) -> list[dict]:
    """Search Download Station tasks for matching titles."""
    try:
        from src.tools.download_station import DownloadStationClient
        ds = get_settings().download_station
        if not ds.get("url") or not ds.get("username") or not ds.get("password"):
            return []
        client = DownloadStationClient(
            base_url=ds["url"], username=ds["username"], password=ds["password"],
        )
        task_data = await client._task_api("list", additional="detail")
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

    Returns a unified numbered list of matching TV shows, movies, and torrents,
    ranked by relevance. Pass a result number to download_media() to act on it.

    Args:
        query: The search term (title, name, or keyword).
        source_type: Optional filter — 'tv', 'movie', 'torrent', or None for all.
    """
    global _last_results
    try:
        searches = []
        if source_type in (None, "tv"):
            searches.append(_search_sonarr(query, 10))
        if source_type in (None, "movie"):
            searches.append(_search_radarr(query, 10))
        if source_type in (None, "torrent"):
            searches.append(_search_download_station(query, 10))

        from asyncio import gather
        results_lists = await gather(*searches, return_exceptions=True)

        all_results: list[dict] = []
        for rl in results_lists:
            if isinstance(rl, list):
                all_results.extend(rl)

        if not all_results:
            return f"No results found for '{query}' across any source."

        all_results.sort(key=lambda r: (-r["relevance"], r["title"]))

        # Deduplicate by title + source
        seen: set = set()
        unique_results: list[dict] = []
        for r in all_results:
            key = (r["title"].lower(), r["source"])
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        _last_results = unique_results[:15]

        source_names = {
            "sonarr": "TV (Sonarr)",
            "radarr": "Movies (Radarr)",
            "download_station": "Torrents (DS)",
        }

        lines = [f"Found {len(unique_results)} result(s) for '{query}':", ""]
        for i, r in enumerate(_last_results, 1):
            source_label = source_names.get(r["source"], r["source"])
            year_str = f" ({r['year']})" if r.get("year") else ""
            lines.append(f"  {i}. {r['title']}{year_str} ← {source_label} [id: {r['id']}]")
            if r.get("overview"):
                lines.append(f"     {r['overview'][:120]}")

        if len(unique_results) > 15:
            lines.append(f"\n  ... and {len(unique_results) - 15} more results")

        lines.append("")
        lines.append("To download a result: download_media(result_id) with its number above.")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Search failed: {type(e).__name__}: {e}"


# ── Download tool ───────────────────────────────────────────────────────────

@tool
async def download_media(result_id: int) -> str:
    """Download a result from the most recent search_media() call by its number.

    Dispatches based on the result's source: TV shows are added to Sonarr,
    movies to Radarr. Download Station results are already-tracked tasks.

    Args:
        result_id: The 1-based number from the search_media results list.
    """
    if not _last_results:
        return "❌ No cached search results. Run search_media(query) first."
    if not 1 <= result_id <= len(_last_results):
        return (
            f"❌ result_id {result_id} is out of range — the last search returned "
            f"{len(_last_results)} result(s)."
        )

    r = _last_results[result_id - 1]
    try:
        if r["source_type"] == "tv":
            from src.tools.sonarr import add_tv_show
            return await add_tv_show.ainvoke({"tvdb_id": r["id"], "title": r["title"]})
        if r["source_type"] == "movie":
            from src.tools.radarr import add_movie
            return await add_movie.ainvoke({"tmdb_id": r["id"], "title": r["title"]})
        if r["source_type"] == "torrent":
            return (
                f"ℹ️ '{r['title']}' is already a Download Station task (id: {r['id']}). "
                f"Use download_station_resume/download_station_pause to manage it."
            )
        return f"❌ Unknown source type: {r['source_type']}"
    except Exception as e:
        return f"❌ Download failed: {type(e).__name__}: {e}"
