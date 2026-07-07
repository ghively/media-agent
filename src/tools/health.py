"""Health check tools."""
import asyncio

import httpx
from langchain_core.tools import tool

from src.config import get_settings


async def _probe(name: str, url: str, headers: dict | None = None,
                 params: dict | None = None, issue_count: bool = False) -> str:
    """Probe a single service endpoint and return a one-line status."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            if issue_count:
                issues = resp.json()
                if issues:
                    return f"{name}: ⚠️ {len(issues)} issue(s)"
            return f"{name}: ✅ healthy"
    except httpx.ConnectError:
        return f"{name}: ❌ unreachable"
    except Exception as e:
        return f"{name}: ❌ {type(e).__name__}"


def _health_probes() -> list:
    """Build probe coroutines for every configured service."""
    settings = get_settings()
    probes = []

    sonarr = settings.sonarr
    if sonarr.get("url"):
        probes.append(_probe(
            "Sonarr", f"{sonarr['url'].rstrip('/')}/api/v3/health",
            headers={"X-Api-Key": sonarr.get("api_key", "")}, issue_count=True,
        ))
    radarr = settings.radarr
    if radarr.get("url"):
        probes.append(_probe(
            "Radarr", f"{radarr['url'].rstrip('/')}/api/v3/health",
            headers={"X-Api-Key": radarr.get("api_key", "")}, issue_count=True,
        ))
    emby = settings.emby
    if emby.get("url"):
        probes.append(_probe(
            "Emby", f"{emby['url'].rstrip('/')}/emby/System/Info",
            headers={"X-Emby-Token": emby.get("api_key", "")},
        ))
    sabnzbd = settings.sabnzbd
    if sabnzbd.get("url"):
        probes.append(_probe(
            "SABnzbd", f"{sabnzbd['url'].rstrip('/')}/api",
            params={"mode": "version", "output": "json",
                    "apikey": sabnzbd.get("api_key", "")},
        ))
    return probes


@tool
async def check_all_health() -> str:
    """Check health across all configured media services (Sonarr, Radarr, Emby, SABnzbd)."""
    probes = _health_probes()
    if not probes:
        return "No services configured — check config/settings.yaml."
    results = await asyncio.gather(*probes)
    return "\n".join(results)


@tool
async def check_disk_space() -> str:
    """Check disk space on the media server (as reported by Sonarr)."""
    try:
        settings = get_settings()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.sonarr['url'].rstrip('/')}/api/v3/diskspace",
                headers={"X-Api-Key": settings.sonarr["api_key"]},
            )
            resp.raise_for_status()
            disks = resp.json()
        lines = ["Disk space (via Sonarr):\n"]
        for disk in disks:
            path = disk.get("path", "unknown")
            free = disk.get("freeSpace", 0) / (1024**3)
            total = disk.get("totalSpace", 0) / (1024**3)
            if total > 0:
                pct = (1 - free / total) * 100
                warn = " ⚠️" if pct >= 90 else ""
                lines.append(f"  • {path}: {free:.1f} GB free / {total:.1f} GB ({pct:.0f}% used){warn}")
        return "\n".join(lines) if len(lines) > 1 else "No disk space info available."
    except Exception as e:
        return f"❌ Failed to check disk space: {type(e).__name__}: {e}"


async def _queue_count(name: str, url: str, api_key: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{url.rstrip('/')}/api/v3/queue",
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records", []) if isinstance(data, dict) else data
            return f"{name} queue: {len(records)} item(s)"
    except Exception:
        return f"{name} queue: ❌ unreachable"


@tool
async def check_queue_status() -> str:
    """Check download queues across all services."""
    settings = get_settings()
    checks = []
    if settings.sonarr.get("url"):
        checks.append(_queue_count("Sonarr", settings.sonarr["url"],
                                   settings.sonarr.get("api_key", "")))
    if settings.radarr.get("url"):
        checks.append(_queue_count("Radarr", settings.radarr["url"],
                                   settings.radarr.get("api_key", "")))
    if not checks:
        return "No queue-capable services configured."
    results = await asyncio.gather(*checks)
    return "\n".join(results)
