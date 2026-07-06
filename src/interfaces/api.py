"""Structured JSON API endpoints for the React dashboard.

These return machine-readable data (not text strings like the LLM tools),
so the frontend can render animated progress bars, status cards, etc.
"""
import time
from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/queue")
async def get_queue():
    """Combined download queue from Sonarr, Radarr, and SABnzbd.

    Returns structured JSON with progress percentages, speeds, ETAs.
    """
    from src.config import get_settings

    result = {"timestamp": time.time(), "sonarr": [], "radarr": [], "sabnzbd": None}

    # ── Sonarr ──────────────────────────────────────────────────────
    try:
        from src.tools.sonarr import _client
        data = await _client()._get("/queue")
        records = data.get("records", []) if isinstance(data, dict) else (data or [])
        for r in records:
            size = r.get("size", 0) or 0
            sizeleft = r.get("sizeleft", 0) or 0
            result["sonarr"].append({
                "title": r.get("title", "Unknown"),
                "status": r.get("status", "unknown"),
                "quality": r.get("quality", {}).get("quality", {}).get("name", ""),
                "size_mb": round(size / (1024 * 1024), 1) if size else 0,
                "sizeleft_mb": round(sizeleft / (1024 * 1024), 1) if sizeleft else 0,
                "progress": round(((size - sizeleft) / size) * 100, 1) if size else 0,
                "timeleft": r.get("timeleft", ""),
                "eta": r.get("estimatedCompletionTime", ""),
                "warning": r.get("trackedDownloadStatus") == "warning",
            })
    except Exception:
        pass

    # ── Radarr ──────────────────────────────────────────────────────
    try:
        from src.tools.radarr import _client
        data = await _client()._get("/queue")
        records = data.get("records", []) if isinstance(data, dict) else (data or [])
        for r in records:
            size = r.get("size", 0) or 0
            sizeleft = r.get("sizeleft", 0) or 0
            result["radarr"].append({
                "title": r.get("title", "Unknown"),
                "status": r.get("status", "unknown"),
                "quality": r.get("quality", {}).get("quality", {}).get("name", ""),
                "size_mb": round(size / (1024 * 1024), 1) if size else 0,
                "sizeleft_mb": round(sizeleft / (1024 * 1024), 1) if sizeleft else 0,
                "progress": round(((size - sizeleft) / size) * 100, 1) if size else 0,
                "timeleft": r.get("timeleft", ""),
                "eta": r.get("estimatedCompletionTime", ""),
                "warning": r.get("trackedDownloadStatus") == "warning",
            })
    except Exception:
        pass

    # ── SABnzbd ────────────────────────────────────────────────────
    try:
        from src.tools.sabnzbd import _client
        data = await _client()._call("queue")
        queue = data.get("queue", {})
        slots = []
        for slot in (queue.get("slots") or [])[:20]:
            size_mb = _safe_float(slot.get("mb", 0))
            mbleft = _safe_float(slot.get("mbleft", 0))
            slots.append({
                "filename": slot.get("filename", "Unknown"),
                "category": slot.get("cat", ""),
                "status": slot.get("status", "?"),
                "size_mb": size_mb,
                "sizeleft_mb": mbleft,
                "progress": round(((size_mb - mbleft) / size_mb) * 100, 1) if size_mb else 0,
                "timeleft": slot.get("timeleft", ""),
            })
        result["sabnzbd"] = {
            "status": queue.get("status", "unknown"),
            "paused": bool(queue.get("paused", False)),
            "speed": queue.get("speed", "0 B/s"),
            "speed_limit": queue.get("speedlimit", "100"),
            "disk_free": queue.get("diskspace1", "?"),
            "slots": slots,
            "total_count": len(queue.get("slots") or []),
        }
    except Exception:
        pass

    return result


@router.get("/status")
async def get_status():
    """Service health status for all configured services."""
    result = {"timestamp": time.time(), "services": {}}

    # Sonarr
    try:
        from src.tools.sonarr import _client
        health = await _client()._get("/health")
        series = await _client()._get("/series")
        result["services"]["sonarr"] = {
            "name": "Sonarr",
            "status": "healthy" if not health else "warning",
            "shows": len(series),
            "issues": len(health),
        }
    except Exception:
        result["services"]["sonarr"] = {"name": "Sonarr", "status": "offline"}

    # Radarr
    try:
        from src.tools.radarr import _client
        health = await _client()._get("/health")
        movies = await _client()._get("/movie")
        result["services"]["radarr"] = {
            "name": "Radarr",
            "status": "healthy" if not health else "warning",
            "movies": len(movies),
            "issues": len(health),
        }
    except Exception:
        result["services"]["radarr"] = {"name": "Radarr", "status": "offline"}

    # Emby
    try:
        from src.config import get_settings
        from src.tools.emby import EmbyClient
        emby_s = get_settings().emby
        client = EmbyClient(emby_s["url"], emby_s["api_key"])
        libs = await client._get("/emby/Library/VirtualFolders")
        result["services"]["emby"] = {
            "name": "Emby",
            "status": "healthy",
            "libraries": len(libs) if isinstance(libs, list) else 0,
        }
    except Exception:
        result["services"]["emby"] = {"name": "Emby", "status": "offline"}

    # SABnzbd
    try:
        from src.tools.sabnzbd import _client
        data = await _client()._call("queue")
        queue = data.get("queue", {})
        result["services"]["sabnzbd"] = {
            "name": "SABnzbd",
            "status": "paused" if queue.get("paused") else "healthy",
            "speed": queue.get("speed", "0 B/s"),
            "queue_count": len(queue.get("slots") or []),
        }
    except Exception:
        result["services"]["sabnzbd"] = {"name": "SABnzbd", "status": "offline"}

    overall = all(s.get("status") in ("healthy", "paused") for s in result["services"].values())
    result["overall"] = "healthy" if overall else "degraded"
    return result


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
