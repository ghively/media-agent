"""Komga comic/manga server tools.

Config (``services.komga``): ``url`` and ``api_key`` (Komga → Settings →
API keys; sent as the ``X-API-Key`` header). All tools degrade to a clear
"not configured" message when the section is absent.
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


def _cfg() -> dict | None:
    cfg = get_settings().komga
    if not cfg.get("url") or not cfg.get("api_key"):
        return None
    return cfg


async def _get(path: str, params: dict | None = None):
    cfg = _cfg()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{cfg['url'].rstrip('/')}{path}",
            headers={"X-API-Key": cfg["api_key"]},
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


_NOT_CONFIGURED = ("❌ Komga isn't configured. Set services.komga.url and "
                   "api_key in settings.yaml.")


@tool
async def komga_search(query: str) -> str:
    """Search the Komga comic/manga library for a series by name."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        data = await _get("/api/v1/series", params={"search": query, "size": 15})
        series = data.get("content", [])
        if not series:
            return f"No comics found for '{query}' in Komga."
        lines = [f"Found {len(series)} series:\n"]
        for s in series:
            meta = s.get("metadata", {})
            status = meta.get("status", "")
            books = s.get("booksCount", 0)
            lines.append(f"  • {s.get('name', 'Unknown')} — {books} book(s)"
                         + (f" [{status}]" if status else ""))
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Komga."
    except Exception as e:
        return f"❌ Komga search failed: {type(e).__name__}: {e}"


@tool
async def komga_recent(limit: int = 10) -> str:
    """Show comics/manga recently added to Komga."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        data = await _get("/api/v1/books", params={
            "sort": "createdDate,desc", "size": min(max(limit, 1), 25)})
        books = data.get("content", [])
        if not books:
            return "No books in Komga yet."
        lines = [f"Recently added comics ({len(books)}):\n"]
        for b in books:
            series = b.get("seriesTitle", "")
            name = b.get("name", "Unknown")
            lines.append(f"  • {series} — {name}" if series else f"  • {name}")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Komga."
    except Exception as e:
        return f"❌ Komga recent failed: {type(e).__name__}: {e}"


@tool
async def komga_scan() -> str:
    """Make Komga rescan all of its comic libraries for new files."""
    try:
        cfg = _cfg()
        if cfg is None:
            return _NOT_CONFIGURED
        libraries = await _get("/api/v1/libraries")
        if not libraries:
            return "❌ Komga has no libraries to scan."
        async with httpx.AsyncClient(timeout=30) as client:
            for lib in libraries:
                resp = await client.post(
                    f"{cfg['url'].rstrip('/')}/api/v1/libraries/{lib['id']}/scan",
                    headers={"X-API-Key": cfg["api_key"]},
                )
                resp.raise_for_status()
        names = ", ".join(lib.get("name", "?") for lib in libraries)
        return f"✅ Komga scan triggered for: {names}."
    except httpx.ConnectError:
        return "❌ Cannot connect to Komga."
    except Exception as e:
        return f"❌ Komga scan failed: {type(e).__name__}: {e}"
