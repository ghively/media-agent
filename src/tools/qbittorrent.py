"""qBittorrent Web API tools.

Config (``services.qbittorrent``): ``url``, ``username``, ``password``.
Each call is a login → request cycle (the SID cookie never appears in a
URL). When qBittorrent is configured, the router prefers it over Download
Station for magnet/.torrent links.
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings

_NOT_CONFIGURED = ("❌ qBittorrent isn't configured. Set services.qbittorrent "
                   "url/username/password in settings.yaml.")


class QbitError(Exception):
    """Raised when qBittorrent auth or an API call fails cleanly."""


def _cfg() -> dict | None:
    cfg = get_settings().qbittorrent
    if not cfg.get("url"):
        return None
    return cfg


async def _call(method: str, path: str, data: dict | None = None,
                params: dict | None = None):
    """Login, perform one API call, return the response text/json."""
    cfg = _cfg()
    base = cfg["url"].rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        login = await client.post(f"{base}/api/v2/auth/login", data={
            "username": cfg.get("username", ""),
            "password": cfg.get("password", ""),
        })
        if login.status_code != 200 or "Ok" not in login.text:
            raise QbitError("qBittorrent login failed — check username/password.")
        if method == "POST":
            resp = await client.post(f"{base}/api/v2{path}", data=data)
        else:
            resp = await client.get(f"{base}/api/v2{path}", params=params)
        if resp.status_code >= 400:
            raise QbitError(f"qBittorrent returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            return resp.text


def _fmt_speed(bps: int) -> str:
    return f"{bps / 1024 / 1024:.1f} MB/s" if bps >= 1024 * 1024 else f"{bps / 1024:.0f} KB/s"


@tool
async def qbittorrent_list() -> str:
    """List torrents in qBittorrent with progress and speeds."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        torrents = await _call("GET", "/torrents/info")
        if not torrents:
            return "qBittorrent has no torrents."
        active = [t for t in torrents if t.get("state") not in
                  ("pausedUP", "stoppedUP", "uploading", "stalledUP")]
        done = len(torrents) - len(active)
        lines = [f"qBittorrent — {len(active)} active, {done} seeding/complete\n"]
        for t in sorted(active, key=lambda x: x.get("progress", 0))[:20]:
            name = t.get("name", "Unknown")
            progress = round((t.get("progress") or 0) * 100)
            state = t.get("state", "?")
            speed = _fmt_speed(t.get("dlspeed") or 0)
            lines.append(f"  • {name} — {progress}% [{state}] ↓{speed}")
        if len(active) > 20:
            lines.append(f"  ... and {len(active) - 20} more active")
        return "\n".join(lines)
    except QbitError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to qBittorrent."
    except Exception as e:
        return f"❌ Failed to list torrents: {type(e).__name__}: {e}"


@tool
async def qbittorrent_add(url: str, category: str = "") -> str:
    """Add a torrent to qBittorrent by magnet link or .torrent URL."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        if not url.lower().startswith(("magnet:", "http://", "https://")):
            return "❌ That doesn't look like a magnet link or torrent URL."
        data = {"urls": url}
        if category:
            data["category"] = category
        result = await _call("POST", "/torrents/add", data=data)
        if isinstance(result, str) and "fail" in result.lower():
            return "❌ qBittorrent rejected the torrent (invalid or duplicate)."
        return "✅ Torrent added to qBittorrent."
    except QbitError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to qBittorrent."
    except Exception as e:
        return f"❌ Failed to add torrent: {type(e).__name__}: {e}"


@tool
async def qbittorrent_pause() -> str:
    """Pause ALL torrents in qBittorrent."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        await _call("POST", "/torrents/stop", data={"hashes": "all"})
        return "⏸️ All qBittorrent torrents paused."
    except QbitError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to qBittorrent."
    except Exception as e:
        # Older qBittorrent (<5) uses /torrents/pause
        try:
            await _call("POST", "/torrents/pause", data={"hashes": "all"})
            return "⏸️ All qBittorrent torrents paused."
        except Exception:
            return f"❌ Failed to pause torrents: {type(e).__name__}: {e}"


@tool
async def qbittorrent_resume() -> str:
    """Resume ALL torrents in qBittorrent."""
    try:
        if _cfg() is None:
            return _NOT_CONFIGURED
        await _call("POST", "/torrents/start", data={"hashes": "all"})
        return "▶️ All qBittorrent torrents resumed."
    except QbitError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to qBittorrent."
    except Exception as e:
        try:
            await _call("POST", "/torrents/resume", data={"hashes": "all"})
            return "▶️ All qBittorrent torrents resumed."
        except Exception:
            return f"❌ Failed to resume torrents: {type(e).__name__}: {e}"
