"""Bazarr API client + tools (subtitle management).

Registered only when ``services.bazarr`` is configured in settings.
Bazarr's API uses an ``X-API-KEY`` header (Settings → General in Bazarr).
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


def _headers() -> dict:
    return {"X-API-KEY": get_settings().bazarr["api_key"]}


def _base() -> str:
    return get_settings().bazarr["url"].rstrip("/")


async def _get(path: str, params: dict | None = None):
    transport = httpx.AsyncHTTPTransport(retries=2)
    async with httpx.AsyncClient(timeout=15, transport=transport) as client:
        resp = await client.get(f"{_base()}/api{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


@tool
async def bazarr_status() -> str:
    """Check Bazarr (subtitles) health and how many items are missing subtitles."""
    try:
        status = await _get("/system/status")
        badges = await _get("/badges")
        data = status.get("data", status)
        version = data.get("bazarr_version", "?")
        ep_wanted = badges.get("episodes", 0)
        movie_wanted = badges.get("movies", 0)
        lines = [
            f"Bazarr v{version}: ✅ up",
            f"  Missing subtitles — episodes: {ep_wanted}, movies: {movie_wanted}",
        ]
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Bazarr."
    except Exception as e:
        return f"❌ Bazarr status failed: {type(e).__name__}: {e}"


@tool
async def bazarr_wanted_subtitles(kind: str = "all") -> str:
    """List episodes/movies that are missing subtitles (Bazarr).

    Args:
        kind: 'episodes', 'movies', or 'all' (default).
    """
    lines = []
    try:
        if kind in ("all", "episodes"):
            data = await _get("/episodes/wanted", params={"start": 0, "length": 15})
            items = data.get("data", [])
            lines.append(f"Episodes missing subtitles ({data.get('total', len(items))}):")
            for item in items:
                series = item.get("seriesTitle", "?")
                episode = item.get("episode_number", "?")
                title = item.get("episodeTitle", "")
                langs = ", ".join(l.get("name", "?") for l in item.get("missing_subtitles", []))
                lines.append(f"  • {series} {episode} — {title} [{langs}]")
            if not items:
                lines.append("  (none)")
        if kind in ("all", "movies"):
            data = await _get("/movies/wanted", params={"start": 0, "length": 15})
            items = data.get("data", [])
            lines.append(f"Movies missing subtitles ({data.get('total', len(items))}):")
            for item in items:
                title = item.get("title", "?")
                langs = ", ".join(l.get("name", "?") for l in item.get("missing_subtitles", []))
                lines.append(f"  • {title} [{langs}]")
            if not items:
                lines.append("  (none)")
        return "\n".join(lines) if lines else "❌ kind must be 'episodes', 'movies', or 'all'."
    except httpx.ConnectError:
        return "❌ Cannot connect to Bazarr."
    except Exception as e:
        return f"❌ Bazarr wanted list failed: {type(e).__name__}: {e}"
