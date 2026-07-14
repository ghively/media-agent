"""Calibre ebook tools — talks to the Calibre Content Server's /ajax API.

Config (``services.calibre``): ``url`` (content server, e.g.
``http://nas:8081``) plus optional ``username``/``password`` (HTTP digest
or basic auth, as configured on the server).
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings

_NOT_CONFIGURED = ("❌ Calibre isn't configured. Set services.calibre.url "
                   "(the content server) in settings.yaml.")


def _cfg() -> dict | None:
    cfg = get_settings().calibre
    if not cfg.get("url"):
        return None
    return cfg


def _auth(cfg: dict):
    if cfg.get("username"):
        return (cfg["username"], cfg.get("password", ""))
    return None


async def _get(path: str, params: dict | None = None):
    cfg = _cfg()
    async with httpx.AsyncClient(timeout=30, auth=_auth(cfg)) as client:
        resp = await client.get(f"{cfg['url'].rstrip('/')}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


async def _books_by_ids(ids: list) -> list[dict]:
    if not ids:
        return []
    data = await _get("/ajax/books", params={"ids": ",".join(str(i) for i in ids)})
    books = []
    for book_id in ids:
        info = data.get(str(book_id)) or {}
        if info:
            books.append(info)
    return books


def _format_books(books: list[dict]) -> list[str]:
    lines = []
    for b in books:
        title = b.get("title", "Unknown")
        authors = ", ".join(b.get("authors") or []) or "Unknown"
        fmts = ", ".join((b.get("formats") or [])) if isinstance(b.get("formats"), list) else ""
        series = b.get("series")
        extra = f" ({series} #{b.get('series_index')})" if series else ""
        lines.append(f"  • {title}{extra} by {authors}" + (f" [{fmts}]" if fmts else ""))
    return lines


@tool
async def calibre_search(query: str) -> str:
    """Search the Calibre ebook library by title, author, or any Calibre
    search expression (e.g. 'author:Herbert')."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        result = await _get("/ajax/search", params={"query": query, "num": 15})
        ids = result.get("book_ids", [])
        total = result.get("total_num", len(ids))
        if not ids:
            return f"No ebooks found for '{query}'."
        books = await _books_by_ids(ids[:15])
        header = f"Found {total} ebook(s)" + (f", showing {len(books)}" if total > len(books) else "")
        return header + ":\n\n" + "\n".join(_format_books(books))
    except httpx.ConnectError:
        return "❌ Cannot connect to the Calibre content server."
    except Exception as e:
        return f"❌ Calibre search failed: {type(e).__name__}: {e}"


@tool
async def calibre_recent(limit: int = 10) -> str:
    """Show ebooks recently added to the Calibre library."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        result = await _get("/ajax/search", params={
            "query": "", "num": min(max(limit, 1), 25),
            "sort": "timestamp", "sort_order": "desc",
        })
        ids = result.get("book_ids", [])
        if not ids:
            return "The Calibre library is empty."
        books = await _books_by_ids(ids)
        return f"Recently added ebooks ({len(books)}):\n\n" + "\n".join(_format_books(books))
    except httpx.ConnectError:
        return "❌ Cannot connect to the Calibre content server."
    except Exception as e:
        return f"❌ Calibre recent failed: {type(e).__name__}: {e}"
