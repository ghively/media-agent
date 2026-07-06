"""Health check tools."""
import httpx
from langchain_core.tools import tool

from src.config import get_settings


@tool
async def check_all_health() -> str:
    """Check health across all media services (Sonarr, Radarr, Emby)."""
    results = []
    settings = get_settings()

    # Sonarr
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.sonarr['url']}/api/v3/health",
                headers={"X-Api-Key": settings.sonarr["api_key"]},
            )
            resp.raise_for_status()
            issues = resp.json()
            status = "✅ healthy" if not issues else f"⚠️ {len(issues)} issue(s)"
        results.append(f"Sonarr: {status}")
    except Exception as e:
        results.append(f"Sonarr: ❌ {type(e).__name__}")

    # Radarr
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.radarr['url']}/api/v3/health",
                headers={"X-Api-Key": settings.radarr["api_key"]},
            )
            resp.raise_for_status()
            issues = resp.json()
            status = "✅ healthy" if not issues else f"⚠️ {len(issues)} issue(s)"
        results.append(f"Radarr: {status}")
    except Exception as e:
        results.append(f"Radarr: ❌ {type(e).__name__}")

    # Emby
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.emby['url']}/emby/System/Info",
                headers={"X-Emby-Token": settings.emby["api_key"]},
            )
            resp.raise_for_status()
            results.append("Emby: ✅ healthy")
    except Exception as e:
        results.append(f"Emby: ❌ {type(e).__name__}")

    return "\n".join(results)


@tool
async def check_disk_space() -> str:
    """Check disk space on the media server."""
    # For MVP, we check if Sonarr/Radarr report disk space via their system status
    try:
        settings = get_settings()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.sonarr['url']}/api/v3/diskspace",
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
                lines.append(f"  • {path}: {free:.1f} GB free / {total:.1f} GB ({pct:.0f}% used)")
        return "\n".join(lines) if len(lines) > 1 else "No disk space info available."
    except Exception as e:
        return f"❌ Failed to check disk space: {type(e).__name__}: {e}"


@tool
async def check_queue_status() -> str:
    """Check download queues across all services."""
    results = []
    settings = get_settings()

    # Sonarr queue
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.sonarr['url']}/api/v3/queue",
                headers={"X-Api-Key": settings.sonarr["api_key"]},
            )
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records", []) if isinstance(data, dict) else data
            results.append(f"Sonarr queue: {len(records)} item(s)")
    except Exception:
        results.append("Sonarr queue: ❌ unreachable")

    # Radarr queue
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.radarr['url']}/api/v3/queue",
                headers={"X-Api-Key": settings.radarr["api_key"]},
            )
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records", []) if isinstance(data, dict) else data
            results.append(f"Radarr queue: {len(records)} item(s)")
    except Exception:
        results.append("Radarr queue: ❌ unreachable")

    return "\n".join(results)
