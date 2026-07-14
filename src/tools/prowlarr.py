"""Prowlarr unified indexer search tools.

Config (``services.prowlarr``): ``url`` and ``api_key``. Search results
include the indexer's download link (magnet/NZB) — paste it back to the
agent to queue it in qBittorrent, Download Station, or SABnzbd.
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings

_NOT_CONFIGURED = ("❌ Prowlarr isn't configured. Set services.prowlarr.url "
                   "and api_key in settings.yaml.")


def _cfg() -> dict | None:
    cfg = get_settings().prowlarr
    if not cfg.get("url") or not cfg.get("api_key"):
        return None
    return cfg


async def _get(path: str, params: dict | None = None):
    cfg = _cfg()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{cfg['url'].rstrip('/')}/api/v1{path}",
            headers={"X-Api-Key": cfg["api_key"]},
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


def _size_str(size: int) -> str:
    gb = size / 1024 / 1024 / 1024
    return f"{gb:.1f} GB" if gb >= 1 else f"{size / 1024 / 1024:.0f} MB"


@tool
async def prowlarr_search(query: str) -> str:
    """Unified search across ALL configured Prowlarr indexers (torrents +
    usenet). Use for content the Sonarr/Radarr searches can't find."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        results = await _get("/search", params={"query": query, "limit": 50})
        if not results:
            return f"No indexer results for '{query}'."
        results.sort(key=lambda r: r.get("seeders") or 0, reverse=True)
        lines = [f"Top indexer results for '{query}' ({len(results)} total):\n"]
        for r in results[:10]:
            title = r.get("title", "Unknown")
            indexer = r.get("indexer", "?")
            size = _size_str(r.get("size") or 0)
            seeders = r.get("seeders")
            seed_str = f", {seeders} seeders" if seeders is not None else ""
            lines.append(f"  • {title}\n    [{indexer}] {size}{seed_str}")
        lines.append("\nSay which one to grab and I'll queue its magnet/NZB link.")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Prowlarr."
    except Exception as e:
        return f"❌ Prowlarr search failed: {type(e).__name__}: {e}"


@tool
async def prowlarr_indexers() -> str:
    """List the indexers configured in Prowlarr and whether they're enabled."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        indexers = await _get("/indexer")
        if not indexers:
            return "Prowlarr has no indexers configured."
        lines = [f"Prowlarr indexers ({len(indexers)}):\n"]
        for idx in indexers:
            enabled = "✅" if idx.get("enable") else "⏸️"
            proto = idx.get("protocol", "?")
            lines.append(f"  {enabled} {idx.get('name', 'Unknown')} [{proto}]")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Prowlarr."
    except Exception as e:
        return f"❌ Failed to list indexers: {type(e).__name__}: {e}"
