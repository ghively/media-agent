"""Synology Download Station API client + LangGraph tool definitions.

Uses Synology DSM V6 API authentication (SID cookie) against the NAS at port 5000.
The NAS URL is derived from config — the 'url' field under services.sonarr is used
as the NAS host (port 5000), since Sonarr runs on the same Synology NAS.

For MVP simplicity, this client attempts cookie-based V6 auth. If credentials
are not configured, it falls back to an unauthenticated mode that may work if
Download Station has been configured to allow it.

Required config (config/settings.yaml):
  services:
    download_station:
      url: "http://192.168.0.133:5000"
      username: "${DS_USER}"
      password: "${DS_PASS}"

API reference:
  - Login:  /webapi/auth.cgi?api=SYNO.API.Auth&version=6&method=login
  - Tasks:  /webapi/DownloadStation/task.cgi?api=SYNO.DownloadStation.Task&version=3
  - Info:   /webapi/DownloadStation/info.cgi?api=SYNO.DownloadStation.Info&version=1
"""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


DS_API_BASE = "/webapi"


class DownloadStationClient:
    """Async client for Synology Download Station API (V6 SID auth)."""

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

    async def _login(self, client: httpx.AsyncClient) -> bool:
        """Authenticate with V6 SID login. Returns True on success.

        Credentials go through httpx params (percent-encoded) — interpolating
        them into the URL breaks logins for any password containing
        & # + % or spaces.
        """
        if not self.username or not self.password:
            return False
        resp = await client.get(
            f"{self.base_url}{DS_API_BASE}/auth.cgi",
            params={
                "api": "SYNO.API.Auth",
                "version": 6,
                "method": "login",
                "account": self.username,
                "passwd": self.password,
                "session": "DownloadStation",
                "format": "cookie",
            },
        )
        data = resp.json()
        if data.get("success"):
            self._sid = data.get("data", {}).get("sid")
            return True
        # 403/404/406 error codes = DSM 2FA in the way — surface that clearly
        code = (data.get("error") or {}).get("code")
        if code in (403, 404, 406):
            raise RuntimeError(
                "DSM account requires 2-factor authentication, which this "
                "integration does not support. Use a dedicated DSM account "
                "without 2FA (restricted to Download Station) instead."
            )
        return False

    async def _ensure_auth(self, client: httpx.AsyncClient) -> bool:
        """Ensure we have a valid SID, logging in if needed."""
        if self._sid:
            return True
        return await self._login(client)

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """Make an authenticated GET request to the DSM API."""
        request_params = dict(params or {})
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await self._ensure_auth(client)
            if self._sid:
                request_params["_sid"] = self._sid

            resp = await client.get(
                f"{self.base_url}{DS_API_BASE}{path}",
                params=request_params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, data: dict | None = None) -> dict:
        """Make an authenticated POST request to the DSM API."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await self._ensure_auth(client)
            params = {}
            if self._sid:
                params["_sid"] = self._sid

            resp = await client.post(
                f"{self.base_url}{DS_API_BASE}{path}",
                params=params,
                data=data,
            )
            resp.raise_for_status()
            return resp.json()

    async def _task_api(self, method: str, version: int = 3, **extra_params) -> dict:
        """Call the Download Station Task API."""
        params = {
            "api": "SYNO.DownloadStation.Task",
            "version": version,
            "method": method,
            **extra_params,
        }
        return await self._get("/DownloadStation/task.cgi", params=params)


def _client() -> DownloadStationClient:
    s = get_settings().download_station
    return DownloadStationClient(
        base_url=s.get("url", "http://192.168.0.133:5000"),
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
                size = t.get("size", "0")
                downloaded = t.get("additional", {}).get("transfer", {}).get("size_downloaded", "0")
                progress = t.get("additional", {}).get("transfer", {}).get("downloaded_pct", "?")
                lines.append(f"  • {title}")
                lines.append(f"    Status: {status}  |  {progress}%  |  {size} bytes downloaded")

        if completed:
            lines.append(f"\n── Completed ({len(completed)}) ──")
            for t in completed[:5]:
                title = t.get("title", "Unknown")
                status = t.get("status", "finished")
                lines.append(f"  • {title} [{status}]")
            if len(completed) > 5:
                lines.append(f"  ... and {len(completed) - 5} more completed tasks")

        return "\n".join(lines)

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
        params = {
            "api": "SYNO.DownloadStation.Task",
            "version": 3,
            "method": "create",
            "uri": url,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            ds_client = _client()
            await ds_client._ensure_auth(client)
            sid_param = {}
            if ds_client._sid:
                sid_param["_sid"] = ds_client._sid

            resp = await client.post(
                f"{ds_client.base_url}{DS_API_BASE}/DownloadStation/task.cgi",
                params={**sid_param, **params},
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("success"):
            return f"✅ Added download to Download Station: {url[:80]}..."
        return f"⚠️ Download Station returned: {data}"

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
        params = {
            "api": "SYNO.DownloadStation.Task",
            "version": 3,
            "method": "pause",
            "id": task_id,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            ds_client = _client()
            await ds_client._ensure_auth(client)
            sid_param = {}
            if ds_client._sid:
                sid_param["_sid"] = ds_client._sid

            resp = await client.post(
                f"{ds_client.base_url}{DS_API_BASE}/DownloadStation/task.cgi",
                params={**sid_param, **params},
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("success"):
            return f"⏸️  Paused task {task_id}."
        return f"⚠️ Failed to pause task: {data}"

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
        params = {
            "api": "SYNO.DownloadStation.Task",
            "version": 3,
            "method": "resume",
            "id": task_id,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            ds_client = _client()
            await ds_client._ensure_auth(client)
            sid_param = {}
            if ds_client._sid:
                sid_param["_sid"] = ds_client._sid

            resp = await client.post(
                f"{ds_client.base_url}{DS_API_BASE}/DownloadStation/task.cgi",
                params={**sid_param, **params},
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("success"):
            return f"▶️  Resumed task {task_id}."
        return f"⚠️ Failed to resume task: {data}"

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
        client = _client()
        result = await client._get("/DownloadStation/info.cgi", params=params)
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

    except httpx.ConnectError:
        return "❌ Cannot connect to Synology Download Station."
    except Exception as e:
        return f"❌ Failed to get stats: {type(e).__name__}: {e}"