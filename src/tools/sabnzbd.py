"""SABnzbd API client + LangGraph tool definitions."""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


class SabnzbdClient:
    """Async client for SABnzbd API."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def _call(self, mode: str, **kwargs) -> dict:
        """Make a GET request to the SABnzbd API.

        SABnzbd uses query-string parameters: /api?mode=...&output=json&apikey=...
        """
        params = {
            "mode": mode,
            "output": "json",
            "apikey": self.api_key,
            **kwargs,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api", params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, mode: str, **kwargs) -> dict:
        """Make a POST request to the SABnzbd API."""
        params = {
            "mode": mode,
            "output": "json",
            "apikey": self.api_key,
            **kwargs,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api", params=params
            )
            resp.raise_for_status()
            return resp.json()


def _client() -> SabnzbdClient:
    s = get_settings().sabnzbd
    return SabnzbdClient(s["url"], s["api_key"])


@tool
async def sabnzbd_queue() -> str:
    """Get the current SABnzbd download queue — active, paused, and queued items."""
    try:
        data = await _client()._call("queue")
        queue = data.get("queue", {})
        if not queue:
            return "SABnzbd queue is empty or unavailable."

        status = queue.get("status", "unknown")
        paused = queue.get("paused", False)
        speed = queue.get("speed", "0 B/s")
        kb_total = queue.get("kb", "0")
        kb_left = queue.get("mbleft", "0")
        slots = queue.get("slots", [])

        lines = [
            f"SABnzbd Queue — Status: {status}",
            f"  Speed: {speed}  |  Paused: {paused}",
            f"  Total: {kb_total} MB  |  Left: {kb_left} MB",
            f"  Items in queue: {len(slots)}",
        ]

        if slots:
            lines.append("")
            for i, slot in enumerate(slots[:20], 1):
                filename = slot.get("filename", "Unknown")
                size = slot.get("size", "?")
                mb_left = slot.get("mbleft", "0")
                status_str = slot.get("status", "?")

                # Format index number
                index_label = slot.get("index", "")
                lines.append(
                    f"  {i}. {filename}"
                )
                lines.append(f"     Size: {size}  |  Left: {mb_left} MB  |  Status: {status_str}")

            if len(slots) > 20:
                lines.append(f"  ... and {len(slots) - 20} more items")

        return "\n".join(lines)

    except httpx.ConnectError:
        return "❌ Cannot connect to SABnzbd."
    except httpx.TimeoutException:
        return "❌ SABnzbd request timed out."
    except Exception as e:
        return f"❌ SABnzbd queue failed: {type(e).__name__}: {e}"


@tool
async def sabnzbd_history(limit: int = 20) -> str:
    """Show recent completed and failed SABnzbd downloads.

    Args:
        limit: Maximum number of history entries to return (default: 20).
    """
    try:
        data = await _client()._call("history", limit=limit)
        history = data.get("history", {})
        slots = history.get("slots", [])
        if not slots:
            return "No SABnzbd download history."

        total = history.get("total_size", "?")
        month = history.get("month_size", "?")

        lines = [
            f"SABnzbd History ({len(slots)} entries)",
            f"  Total downloaded: {total}  |  This month: {month}",
            "",
        ]

        for slot in slots[:limit]:
            name = slot.get("name", "Unknown")
            status = slot.get("status", "unknown")
            completed = slot.get("completed", "?")
            size = slot.get("size", "?")
            category = slot.get("category", "")
            fail_msg = slot.get("fail_message", "")

            status_icon = "✅" if status == "Completed" else "❌"
            lines.append(f"  {status_icon} {name}")
            lines.append(f"     Status: {status}  |  Size: {size}  |  Completed: {completed}")
            if category:
                lines.append(f"     Category: {category}")
            if fail_msg:
                lines.append(f"     Fail: {fail_msg}")
            lines.append("")

        return "\n".join(lines)

    except httpx.ConnectError:
        return "❌ Cannot connect to SABnzbd."
    except httpx.TimeoutException:
        return "❌ SABnzbd request timed out."
    except Exception as e:
        return f"❌ SABnzbd history failed: {type(e).__name__}: {e}"


@tool
async def sabnzbd_status() -> str:
    """Get SABnzbd server health, disk space, and download speed."""
    try:
        # Full status from queue endpoint provides speed, disk, and pause state
        queue_data = await _client()._call("queue")
        queue = queue_data.get("queue", {})

        # server_stats returns HISTORICAL bandwidth totals (day/week/month/
        # total + per-server byte counts) — not live connection state
        try:
            server_data = await _client()._call("server_stats", output="json")
        except Exception:
            server_data = {}

        lines = ["SABnzbd Status", "─" * 40]

        # Queue-level info
        status = queue.get("status", "unknown")
        speed = queue.get("speed", "0 B/s")
        speed_limit = queue.get("speedlimit", "100")
        paused = queue.get("paused", False)
        disk_total = queue.get("diskspacetotal", "?")
        disk_free = queue.get("diskspace1", disk_total)
        disk_free_norm = queue.get("diskspace2", "?")

        lines.append(f"  Status:            {status}")
        lines.append(f"  Paused:            {paused}")
        lines.append(f"  Current Speed:     {speed}")
        lines.append(f"  Speed Limit:       {speed_limit}%")
        lines.append(f"  Free Disk:         {disk_free} {disk_free_norm}")

        # Historical usage from server_stats (keys: day/week/month/total bytes)
        def _gb(v):
            try:
                return f"{int(v) / (1024 ** 3):.1f} GB"
            except (TypeError, ValueError):
                return "?"
        if server_data:
            lines.append("")
            lines.append("Bandwidth used:")
            lines.append(f"  Today: {_gb(server_data.get('day'))}   "
                         f"Week: {_gb(server_data.get('week'))}   "
                         f"Month: {_gb(server_data.get('month'))}   "
                         f"All time: {_gb(server_data.get('total'))}")

        # Download/upload totals from queue
        mb_total = queue.get("mb", "0")
        mb_left = queue.get("mbleft", "0")
        lines.append("")
        lines.append(f"  Total Downloaded:  {mb_total} MB")
        lines.append(f"  Remaining:         {mb_left} MB")

        return "\n".join(lines)

    except httpx.ConnectError:
        return "❌ Cannot connect to SABnzbd."
    except httpx.TimeoutException:
        return "❌ SABnzbd request timed out."
    except Exception as e:
        return f"❌ SABnzbd status failed: {type(e).__name__}: {e}"


@tool
async def sabnzbd_pause() -> str:
    """Pause all SABnzbd downloads."""
    try:
        result = await _client()._call("pause")
        if result.get("status"):
            return "⏸️  SABnzbd downloads paused."
        return "✅ SABnzbd pause command sent."
    except httpx.ConnectError:
        return "❌ Cannot connect to SABnzbd."
    except Exception as e:
        return f"❌ Failed to pause SABnzbd: {type(e).__name__}: {e}"


@tool
async def sabnzbd_resume() -> str:
    """Resume all paused SABnzbd downloads."""
    try:
        result = await _client()._call("resume")
        if result.get("status"):
            return "▶️  SABnzbd downloads resumed."
        return "✅ SABnzbd resume command sent."
    except httpx.ConnectError:
        return "❌ Cannot connect to SABnzbd."
    except Exception as e:
        return f"❌ Failed to resume SABnzbd: {type(e).__name__}: {e}"


@tool
async def sabnzbd_add_nzb(nzb_url: str, category: str = "") -> str:
    """Add an NZB to SABnzbd for download.

    Args:
        nzb_url: URL to the .nzb file or a magnet link.
        category: Optional category (e.g., 'tv', 'movies', 'music').
    """
    try:
        params = {"mode": "addurl", "name": nzb_url}
        if category:
            params["cat"] = category
        result = await _client()._call(**params)
        nzo_ids = result.get("nzo_ids", [])
        if nzo_ids:
            return f"✅ Added NZB to SABnzbd. ID: {nzo_ids[0]}"
        return "✅ NZB added to SABnzbd queue."
    except httpx.ConnectError:
        return "❌ Cannot connect to SABnzbd."
    except Exception as e:
        return f"❌ Failed to add NZB: {type(e).__name__}: {e}"