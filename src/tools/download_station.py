"""Synology Download Station API client + LangGraph tool definitions.

Uses Synology DSM V6 API authentication (SID) against the NAS. Each tool call
logs in, performs its request, and logs out within a single HTTP session so no
SID is left dangling on the NAS. Credentials are sent as POST form data (never
in the URL query string). Authentication is required — if it fails, the error
is surfaced rather than silently degrading to an empty result.

Required config (config/settings.yaml):
  services:
    download_station:
      url: "http://<YOUR_NAS_IP>:5000"
      username: "${DS_USERNAME}"
      password: "${DS_PASSWORD}"

API reference:
  - Login:  /webapi/auth.cgi?api=SYNO.API.Auth&version=6&method=login
  - Tasks:  /webapi/DownloadStation/task.cgi?api=SYNO.DownloadStation.Task&version=3
  - Info:   /webapi/DownloadStation/info.cgi?api=SYNO.DownloadStation.Info&version=1
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


DS_API_BASE = "/webapi"


class DownloadStationError(Exception):
    """Raised when Download Station auth or an API call fails cleanly."""


class DownloadStationClient:
    """Async client for Synology Download Station API (V7 SID auth with auto-discovery).

    Credentials go in a POST body; every call is a login → request → logout
    cycle so sessions are not leaked. Automatically discovers the correct auth
    endpoint path and version for DSM 7.x.
    """

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._sid: str | None = None
        self._auth_path: str | None = None
        self._auth_version: int | None = None

    async def _discover_auth(self, client: httpx.AsyncClient) -> tuple[str, int]:
        """Query SYNO.API.Info to find the auth endpoint path and version."""
        resp = await client.get(
            f"{self.base_url}{DS_API_BASE}/query.cgi",
            params={"api": "SYNO.API.Info", "version": "1", "method": "query", "query": "all"}
        )
        resp.raise_for_status()
        data = resp.json()
        auth_info = data.get("data", {}).get("SYNO.API.Auth", {})
        path = auth_info.get("path", "entry.cgi")
        max_version = auth_info.get("maxVersion", 7)
        # Use version 7 if available, otherwise use maxVersion
        version = 7 if max_version >= 7 else max_version
        return path, version

    async def _login(self, client: httpx.AsyncClient) -> bool:
        """Authenticate with V7/V6 SID login (credentials in POST body). True on success."""
        if not self.username or not self.password:
            return False
        
        # Discover auth endpoint and version if not already done
        if not self._auth_path or not self._auth_version:
            self._auth_path, self._auth_version = await self._discover_auth(client)
        
        resp = await client.post(
            f"{self.base_url}{DS_API_BASE}/{self._auth_path}",
            data={
                "api": "SYNO.API.Auth",
                "version": str(self._auth_version),
                "method": "login",
                "account": self.username,
                "passwd": self.password,
                "session": "DownloadStation",
                "format": "sid",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            self._sid = data.get("data", {}).get("sid")
            return bool(self._sid)
        return False

    async def _logout(self, client: httpx.AsyncClient) -> None:
        """Release the SID. Best-effort — never raises."""
        if not self._sid:
            return
        try:
            await client.get(
                f"{self.base_url}{DS_API_BASE}/auth.cgi",
                params={
                    "api": "SYNO.API.Auth",
                    "version": "6",
                    "method": "logout",
                    "session": "DownloadStation",
                    "_sid": self._sid,
                },
            )
        except Exception:
            pass
        finally:
            self._sid = None

    async def _call(self, path: str, params: dict | None = None, method: str = "GET") -> dict:
        """Log in, make one authenticated request, then log out.

        Raises DownloadStationError if authentication fails, so callers surface
        the real cause instead of mistaking it for an empty result.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if not await self._login(client):
                raise DownloadStationError(
                    "Download Station authentication failed — check DS_USERNAME/DS_PASSWORD."
                )
            try:
                request_params = dict(params or {})
                request_params["_sid"] = self._sid
                url = f"{self.base_url}{DS_API_BASE}{path}"
                if method == "POST":
                    resp = await client.post(url, params=request_params)
                else:
                    resp = await client.get(url, params=request_params)
                resp.raise_for_status()
                return resp.json()
            finally:
                await self._logout(client)

    async def _task_api(self, action: str, version: int = 3, http_method: str = "GET", **extra_params) -> dict:
        """Call the Download Station Task API."""
        params = {
            "api": "SYNO.DownloadStation.Task",
            "version": version,
            "method": action,
            **extra_params,
        }
        return await self._call("/DownloadStation/task.cgi", params, method=http_method)


def _client() -> DownloadStationClient:
    s = get_settings().download_station
    return DownloadStationClient(
        base_url=s.get("url", "http://<YOUR_NAS_IP>:5000"),
        username=s.get("username"),
        password=s.get("password"),
    )


@tool
async def download_station_list() -> str:
    """List all active torrent and download tasks in Download Station."""
    try:
        result = await _client()._task_api("list", additional="detail,transfer")
        tasks = result.get("data", {}).get("tasks", [])

        if not tasks:
            return "Download Station has no active tasks."

        # Separate active and completed
        active = [t for t in tasks if t.get("status") not in ("finished", "seeding")]
        completed = [t for t in tasks if t.get("status") in ("finished", "seeding")]

        lines = [
            f"Download Station — {len(active)} active, {len(completed)} complete",
            "",
        ]

        if active:
            lines.append(f"── Active ({len(active)}) ──")
            for t in active:
                title = t.get("title", "Unknown")
                status = t.get("status", "?")
                downloaded = t.get("additional", {}).get("transfer", {}).get("size_downloaded", "0")
                progress = t.get("additional", {}).get("transfer", {}).get("downloaded_pct", "?")
                lines.append(f"  • {title}")
                lines.append(f"    Status: {status}  |  {progress}%  |  {downloaded} bytes downloaded")

        if completed:
            lines.append(f"\n── Completed ({len(completed)}) ──")
            for t in completed[:5]:
                title = t.get("title", "Unknown")
                status = t.get("status", "finished")
                lines.append(f"  • {title} [{status}]")
            if len(completed) > 5:
                lines.append(f"  ... and {len(completed) - 5} more completed tasks")

        return "\n".join(lines)

    except DownloadStationError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Synology Download Station."
    except httpx.TimeoutException:
        return "❌ Download Station request timed out."
    except Exception as e:
        return f"❌ Failed to list tasks: {type(e).__name__}: {e}"


@tool
async def download_station_add(url: str) -> str:
    """Add a torrent/magnet/NZB URL to Download Station for download.

    Args:
        url: Torrent file URL, magnet link, or NZB URL to download.
    """
    try:
        data = await _client()._task_api("create", http_method="POST", uri=url)
        if data.get("success"):
            return f"✅ Added download to Download Station: {url[:80]}..."
        return f"⚠️ Download Station returned: {data}"

    except DownloadStationError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Synology Download Station."
    except Exception as e:
        return f"❌ Failed to add download: {type(e).__name__}: {e}"


@tool
async def download_station_pause(task_id: str) -> str:
    """Pause a specific Download Station task by its ID.

    Args:
        task_id: The task ID from download_station_list().
    """
    try:
        data = await _client()._task_api("pause", http_method="POST", id=task_id)
        if data.get("success"):
            return f"⏸️  Paused task {task_id}."
        return f"⚠️ Failed to pause task: {data}"

    except DownloadStationError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Synology Download Station."
    except Exception as e:
        return f"❌ Failed to pause task: {type(e).__name__}: {e}"


@tool
async def download_station_resume(task_id: str) -> str:
    """Resume a paused Download Station task by its ID.

    Args:
        task_id: The task ID from download_station_list().
    """
    try:
        data = await _client()._task_api("resume", http_method="POST", id=task_id)
        if data.get("success"):
            return f"▶️  Resumed task {task_id}."
        return f"⚠️ Failed to resume task: {data}"

    except DownloadStationError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Synology Download Station."
    except Exception as e:
        return f"❌ Failed to resume task: {type(e).__name__}: {e}"


@tool
async def download_station_info() -> str:
    """Get Download Station version and capability info."""
    try:
        params = {
            "api": "SYNO.DownloadStation.Info",
            "version": 1,
            "method": "getinfo",
        }
        result = await _client()._call("/DownloadStation/info.cgi", params=params)
        info = result.get("data", {})

        if not info:
            return "Could not retrieve Download Station info."

        lines = [
            "Synology Download Station Info",
            f"  Version:      {info.get('version_string', '?')}",
            f"  Is Manager:   {info.get('is_manager', False)}",
        ]

        # Available service types
        services = info.get("service", [])
        if services:
            lines.append("  Services:")
            for svc in services:
                name = svc.get("service_name", "?")
                enabled = svc.get("enabled", False)
                icon = "✅" if enabled else "❌"
                lines.append(f"    {icon} {name}")

        return "\n".join(lines)

    except DownloadStationError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Synology Download Station."
    except Exception as e:
        return f"❌ Failed to get info: {type(e).__name__}: {e}"


@tool
async def download_station_stats() -> str:
    """Get Download Station task statistics summary."""
    try:
        result = await _client()._task_api("list", additional="detail,transfer")
        tasks = result.get("data", {}).get("tasks", [])

        if not tasks:
            return "Download Station has no tasks to report stats on."

        total = len(tasks)
        downloading = sum(1 for t in tasks if t.get("status") == "downloading")
        paused = sum(1 for t in tasks if t.get("status") == "paused")
        finished = sum(1 for t in tasks if t.get("status") == "finished")
        seeding = sum(1 for t in tasks if t.get("status") == "seeding")
        error = sum(1 for t in tasks if t.get("status") == "error")
        waiting = sum(1 for t in tasks if t.get("status") == "waiting")

        # Calculate total size
        total_size = sum(int(t.get("size", 0)) for t in tasks)
        total_downloaded = sum(
            int(t.get("additional", {}).get("transfer", {}).get("size_downloaded", 0))
            for t in tasks
        )

        def fmt_bytes(b: float) -> str:
            for unit in ("B", "KB", "MB", "GB", "TB"):
                if b < 1024:
                    return f"{b:.1f} {unit}"
                b /= 1024
            return f"{b:.1f} PB"

        lines = [
            "Download Station — Task Statistics",
            f"  Total tasks:       {total}",
            f"  Downloading:       {downloading}",
            f"  Seeding:           {seeding}",
            f"  Paused:            {paused}",
            f"  Waiting:           {waiting}",
            f"  Finished:          {finished}",
            f"  Error:             {error}",
            f"  Total size:        {fmt_bytes(total_size)}",
            f"  Total downloaded:  {fmt_bytes(total_downloaded)}",
        ]

        return "\n".join(lines)

    except DownloadStationError as e:
        return f"❌ {e}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Synology Download Station."
    except Exception as e:
        return f"❌ Failed to get stats: {type(e).__name__}: {e}"
