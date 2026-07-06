"""Emby API client + LangGraph tool definitions."""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


def _transport() -> httpx.AsyncHTTPTransport:
    """Shared transport with connect retries — home-lab services restart often."""
    return httpx.AsyncHTTPTransport(retries=2)


class EmbyClient:
    """Async client for Emby API."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Emby-Token": api_key}
        self.timeout = timeout

    async def _get(self, path: str, params: dict | None = None):
        async with httpx.AsyncClient(timeout=self.timeout, transport=_transport()) as client:
            resp = await client.get(
                f"{self.base_url}{path}", headers=self.headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, json_data: dict | None = None):
        async with httpx.AsyncClient(timeout=self.timeout, transport=_transport()) as client:
            resp = await client.post(
                f"{self.base_url}{path}", headers=self.headers, json=json_data
            )
            resp.raise_for_status()
            return resp.json()


def _client() -> EmbyClient:
    s = get_settings().emby
    return EmbyClient(s["url"], s["api_key"])


_cached_user_id: str | None = None


async def _user_id() -> str:
    """Resolve a user id for user-scoped endpoints (/Users/{id}/Items/...).

    Emby has no user-less /Items/Latest or /Items/{id} route, so these calls
    must be made in a user's context. Uses ``services.emby.user_id`` from
    settings when set; otherwise picks the first user reported by the server
    and caches it for the process lifetime.
    """
    global _cached_user_id
    configured = get_settings().emby.get("user_id", "")
    if configured:
        return configured
    if _cached_user_id:
        return _cached_user_id
    users = await _client()._get("/emby/Users")
    if not users:
        raise RuntimeError("Emby reported no users; set services.emby.user_id")
    _cached_user_id = users[0].get("Id", "")
    return _cached_user_id


@tool
async def emby_search(query: str) -> str:
    """Search across all Emby libraries."""
    try:
        result = await _client()._get("/emby/Items", params={
            "SearchTerm": query, "Recursive": "true", "Limit": "20"
        })
        items = result.get("Items", [])
        total = result.get("TotalRecordCount", 0)
        if not items:
            return f"No results found for '{query}' in Emby."
        lines = [f"Found {total} result(s):\n"]
        for item in items:
            name = item.get("Name", "Unknown")
            itype = item.get("Type", "")
            year = item.get("ProductionYear", "")
            year_str = f" ({year})" if year else ""
            lines.append(f"  • {name}{year_str} [{itype}]")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Emby."
    except Exception as e:
        return f"❌ Emby search failed: {type(e).__name__}: {e}"


@tool
async def emby_recent(limit: int = 20) -> str:
    """Show recently added items in Emby."""
    try:
        user_id = await _user_id()
        result = await _client()._get(
            f"/emby/Users/{user_id}/Items/Latest", params={"Limit": str(limit)}
        )
        if not result:
            return "No recently added items."
        if isinstance(result, dict):
            items = result.get("Items", [])
        else:
            items = result
        if not items:
            return "No recently added items."
        lines = [f"Recently added ({len(items)}):\n"]
        for item in items[:20]:
            name = item.get("Name", "Unknown")
            itype = item.get("Type", "")
            lines.append(f"  • {name} [{itype}]")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Emby."
    except Exception as e:
        return f"❌ Failed to get recent items: {type(e).__name__}: {e}"


@tool
async def emby_libraries() -> str:
    """List all Emby libraries."""
    try:
        result = await _client()._get("/emby/Library/VirtualFolders")
        if not result:
            return "No libraries found."
        lines = [f"Emby libraries ({len(result)}):\n"]
        for lib in result:
            name = lib.get("Name", "Unknown")
            ltype = lib.get("CollectionType", "mixed")
            lines.append(f"  • {name} [{ltype}]")
        return "\n".join(lines)
    except httpx.ConnectError:
        return "❌ Cannot connect to Emby."
    except Exception as e:
        return f"❌ Failed to list libraries: {type(e).__name__}: {e}"


@tool
async def emby_scan() -> str:
    """Trigger an Emby library scan/refresh."""
    try:
        await _client()._post("/emby/Library/Refresh")
        return "✅ Library scan triggered."
    except httpx.ConnectError:
        return "❌ Cannot connect to Emby."
    except Exception as e:
        return f"❌ Failed to trigger scan: {type(e).__name__}: {e}"


@tool
async def emby_get_item(item_id: str) -> str:
    """Get details of a specific Emby media item by ID."""
    try:
        user_id = await _user_id()
        item = await _client()._get(f"/emby/Users/{user_id}/Items/{item_id}")
        name = item.get("Name", "Unknown")
        itype = item.get("Type", "")
        year = item.get("ProductionYear", "")
        overview = item.get("Overview", "No description available.")
        runtime = item.get("RunTimeTicks", 0)
        # Convert ticks to minutes (10,000,000 ticks per second)
        minutes = runtime // 600000000 if runtime else 0
        lines = [
            f"Name: {name}",
            f"Type: {itype}",
            f"Year: {year}" if year else "",
            f"Runtime: {minutes} min" if minutes else "",
            f"\nOverview:\n{overview[:500]}",
        ]
        return "\n".join(l for l in lines if l)
    except httpx.ConnectError:
        return "❌ Cannot connect to Emby."
    except Exception as e:
        return f"❌ Failed to get item: {type(e).__name__}: {e}"
