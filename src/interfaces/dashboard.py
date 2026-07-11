"""Web dashboard for Media Agent.

Mounts on the existing FastAPI app. Provides a browser-based dashboard with:
- Service health cards (Sonarr, Radarr, Emby, SABnzbd)
- Recent activity feed (last grabs/imports)
- Download queue with progress
- Disk space
- Quick action buttons
- Chat interface (talk to the agent directly from the dashboard)

Usage in main.py::

    from src.interfaces.dashboard import mount_dashboard
    mount_dashboard(app)
"""
import asyncio
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from src.config import get_settings
from src.interfaces.openai_api import _check_auth


class ChatRequest(BaseModel):
    message: str


def mount_dashboard(app: FastAPI) -> None:
    _register_routes(app)
    # Mount static assets directory for React build
    import os
    from fastapi.staticfiles import StaticFiles
    # React build is at /app/src/static/ (not relative to interfaces/)
    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    static_dir = os.path.normpath(static_dir)
    if os.path.isdir(static_dir):
        assets_dir = os.path.join(static_dir, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


def _register_routes(app: FastAPI) -> None:

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_page():
        # Try to serve the React build; fall back to inline HTML
        import os
        static_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "static"))
        react_index = os.path.join(static_dir, "index.html")
        if os.path.exists(react_index):
            with open(react_index) as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content=_DASHBOARD_HTML)

    @app.get("/api/dashboard/data", include_in_schema=False)
    async def dashboard_data(authorization: str | None = Header(None)):
        # Requires the configured API key when one is set; open otherwise.
        # These routes drive the full agent, so gate them behind the same
        # credential as the OpenAI-compatible API.
        _check_auth(authorization)
        data = await _gather_all_data()
        return JSONResponse(data)

    @app.post("/api/dashboard/chat", include_in_schema=False)
    async def dashboard_chat(req: ChatRequest, authorization: str | None = Header(None)):
        """Chat endpoint for the dashboard. Streams response as SSE.

        Uses a fixed thread_id ("dashboard") so conversation history persists
        across messages via the agent's MemorySaver checkpointer. This lets
        follow-up messages like "add the first one" reference earlier results.
        """
        _check_auth(authorization)
        import json as _json

        # All dashboard messages share one conversation thread, so follow-ups
        # like "add the first one" keep their context.
        thread_id = "dashboard"

        async def _stream():
            from src.graphs.conversational import record_exchange, stream_agent
            from src.graphs.router import try_route

            try:
                # Deterministic fast path first — instant, no LLM round-trip.
                routed = await try_route(req.message, thread_id)
                if routed is not None:
                    await record_exchange(thread_id, req.message, routed)
                    yield f"data: {_json.dumps({'content': routed, 'done': False})}\n\n"
                    yield f"data: {_json.dumps({'content': '', 'done': True, 'full': routed})}\n\n"
                    return

                collected = []
                async for text in stream_agent(req.message, thread_id):
                    collected.append(text)
                    yield f"data: {_json.dumps({'content': text, 'done': False})}\n\n"

                full = "".join(collected) or "No response."
                yield f"data: {_json.dumps({'content': '', 'done': True, 'full': full})}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'content': '', 'done': True, 'error': f'❌ {type(e).__name__}: {e}'})}\n\n"

        return StreamingResponse(_stream(), media_type="text/event-stream")


# ── data gathering ────────────────────────────────────────────────────────


async def _gather_all_data() -> dict:
    """Collect live status from all services in parallel."""
    from src.tools.sonarr import SonarrClient
    from src.tools.radarr import RadarrClient
    from src.tools.emby import EmbyClient

    settings = get_settings()
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    # Run all health checks concurrently
    sonarr_task = _gather_sonarr(settings)
    radarr_task = _gather_radarr(settings)
    emby_task = _gather_emby(settings)
    sabnzbd_task = _gather_sabnzbd(settings)
    download_station_task = _gather_download_station(settings)

    sonarr_data, radarr_data, emby_data, sabnzbd_data, ds_data = await asyncio.gather(
        sonarr_task, radarr_task, emby_task, sabnzbd_task, download_station_task
    )

    services = {
        "sonarr": sonarr_data,
        "radarr": radarr_data,
        "emby": emby_data,
    }
    if sabnzbd_data:
        services["sabnzbd"] = sabnzbd_data
    if ds_data:
        services["download_station"] = ds_data

    # Collect activity + disk space
    activity_task = _gather_activity(settings)
    disk_task = _gather_disk_space(settings)
    activity, disk_space = await asyncio.gather(activity_task, disk_task)

    # Check local tools availability (no remote health endpoint — just check config).
    # Offloaded: it does a blocking rglob over the ROM library.
    local_tools = await asyncio.to_thread(_check_local_tools, settings)

    all_healthy = all(s.get("status") == "healthy" for s in services.values())
    return {
        "timestamp": now,
        "overall_status": "healthy" if all_healthy else "degraded",
        "services": services,
        "activity": activity,
        "disk_space": disk_space,
        "local_tools": local_tools,
    }


async def _gather_sonarr(settings) -> dict:
    from src.tools.sonarr import SonarrClient
    try:
        cfg = settings.sonarr
        client = SonarrClient(cfg["url"], cfg["api_key"])
        health = await client._get("/health")
        queue = await client._get("/queue")
        series = await client._get("/series")
        queue_records = queue if isinstance(queue, list) else queue.get("records", [])
        ok = not health
        return {
            "name": "Sonarr",
            "status": "healthy" if ok else "warning",
            "health": "✅ All checks passing" if ok else
                "⚠️ " + health[0].get("message", "issues found")[:120] if health else "✅",
            "queue_count": len(queue_records),
            "queue_items": [_format_queue_item(r) for r in queue_records[:5]],
            "library_count": len(series) if isinstance(series, list) else 0,
            "emoji": "✅" if ok else "⚠️",
        }
    except Exception as e:
        return {"name": "Sonarr", "status": "error", "health": f"❌ {e}",
                "queue_count": 0, "queue_items": [], "library_count": 0, "emoji": "❌"}


async def _gather_radarr(settings) -> dict:
    from src.tools.radarr import RadarrClient
    try:
        cfg = settings.radarr
        client = RadarrClient(cfg["url"], cfg["api_key"])
        health = await client._get("/health")
        queue = await client._get("/queue")
        movies = await client._get("/movie")
        queue_records = queue if isinstance(queue, list) else queue.get("records", [])
        ok = not health
        return {
            "name": "Radarr",
            "status": "healthy" if ok else "warning",
            "health": "✅ All checks passing" if ok else
                "⚠️ " + health[0].get("message", "issues found")[:120] if health else "✅",
            "queue_count": len(queue_records),
            "queue_items": [_format_queue_item(r) for r in queue_records[:5]],
            "library_count": len(movies) if isinstance(movies, list) else 0,
            "emoji": "✅" if ok else "⚠️",
        }
    except Exception as e:
        return {"name": "Radarr", "status": "error", "health": f"❌ {e}",
                "queue_count": 0, "queue_items": [], "library_count": 0, "emoji": "❌"}


async def _gather_emby(settings) -> dict:
    from src.tools.emby import EmbyClient
    try:
        cfg = settings.emby
        client = EmbyClient(cfg["url"], cfg["api_key"])
        libraries = await client._get("/emby/Library/VirtualFolders")
        ok = isinstance(libraries, list)
        # Get recent items — use Items endpoint with sorting (doesn't require user ID)
        recent_items = []
        try:
            recent = await client._get("/emby/Items", params={
                "SortBy": "DateCreated", "SortOrder": "Descending",
                "Limit": 5, "Recursive": "true",
                "IncludeItemTypes": "Movie,Series",
                "Fields": "PrimaryImageAspectRatio",
            })
            items = recent.get("Items", []) if isinstance(recent, dict) else []
            for item in items[:5]:
                recent_items.append({
                    "name": item.get("Name", ""),
                    "type": item.get("Type", ""),
                })
        except Exception:
            pass
        return {
            "name": "Emby",
            "status": "healthy" if ok else "warning",
            "libraries": len(libraries) if isinstance(libraries, list) else 0,
            "recent": recent_items,
            "emoji": "✅" if ok else "⚠️",
        }
    except Exception as e:
        return {"name": "Emby", "status": "error", "libraries": 0,
                "recent": [], "emoji": "❌"}


async def _gather_sabnzbd(settings) -> dict | None:
    try:
        cfg = settings.sabnzbd
        if not cfg.get("url") or not cfg.get("api_key"):
            return None
        import httpx
        base = cfg["url"].rstrip("/")
        params = {"mode": "queue", "output": "json", "apikey": cfg["api_key"]}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base}/api", params=params)
            resp.raise_for_status()
            data = resp.json()
        queue = data.get("queue", {})
        slots = queue.get("slots", [])
        items = []
        for slot in slots[:5]:
            items.append({
                "name": slot.get("filename", slot.get("name", "Unknown")),
                "progress": _calc_sabnzbd_progress(slot),
                "size": slot.get("size", ""),
                "status": slot.get("status", ""),
            })
        return {
            "name": "SABnzbd",
            "status": "healthy",
            "queue_count": len(slots),
            "queue_items": items,
            "speed": queue.get("speed", ""),
            "emoji": "✅",
        }
    except Exception as e:
        # Configured but failing — surface it as an error card (counts toward
        # "degraded") instead of hiding the service as if it were absent.
        return {
            "name": "SABnzbd", "status": "error", "queue_count": 0,
            "queue_items": [], "health": f"❌ {type(e).__name__}: {e}", "emoji": "❌",
        }


def _ds_error(msg: str) -> dict:
    """Error card for a configured-but-failing Download Station."""
    return {
        "name": "Download Station", "status": "error", "queue_count": 0,
        "queue_items": [], "health": f"❌ {msg}", "emoji": "❌",
    }


async def _gather_download_station(settings) -> dict | None:
    """Check Synology Download Station connectivity and list active tasks."""
    try:
        cfg = settings.download_station
        if not cfg.get("url") or not cfg.get("username"):
            return None
        import httpx
        base = cfg["url"].rstrip("/")

        # Auth: get SID (credentials in POST body, not the URL query)
        async with httpx.AsyncClient(timeout=10) as client:
            auth_resp = await client.post(f"{base}/webapi/auth.cgi", data={
                "api": "SYNO.API.Auth", "version": "6", "method": "login",
                "account": cfg["username"], "passwd": cfg["password"],
                "session": "DownloadStation", "format": "sid",
            })
            auth_data = auth_resp.json()
            if not auth_data.get("success"):
                return _ds_error("authentication failed — check credentials")
            sid = auth_data["data"]["sid"]

            # List tasks
            task_resp = await client.get(f"{base}/webapi/entry.cgi", params={
                "api": "SYNO.DownloadStation.Task", "version": "2",
                "method": "list", "additional": "detail",
                "_sid": sid,
            })
            task_data = task_resp.json()

            # Logout
            await client.get(f"{base}/webapi/auth.cgi", params={
                "api": "SYNO.API.Auth", "version": "6", "method": "logout", "_sid": sid,
            })

        if not task_data.get("success"):
            return _ds_error("task list request rejected by DSM")

        tasks = task_data.get("data", {}).get("tasks", [])
        active = [t for t in tasks if t.get("status") == "downloading"]
        items = []
        for t in active[:5]:
            additional = t.get("additional", {}).get("detail", {})
            size = additional.get("size", 0)
            size_downloaded = additional.get("size_downloaded", 0)
            progress = round(size_downloaded / size * 100) if size else 0
            size_mb = size / 1024 / 1024 if size else 0
            items.append({
                "name": t.get("title", "Unknown"),
                "progress": progress,
                "size": f"{size_mb:.0f} MB" if size_mb > 1 else "",
                "status": t.get("status", "unknown"),
            })
        return {
            "name": "Download Station",
            "status": "healthy",
            "queue_count": len(active),
            "queue_items": items,
            "emoji": "✅",
        }
    except Exception as e:
        return _ds_error(f"{type(e).__name__}: {e}")


def _check_local_tools(settings) -> dict:
    """Check availability of local-only tools (YouTube, Audible, ROMs).
    These don't have remote health endpoints — we check if their config
    and external dependencies exist."""
    from pathlib import Path
    import shutil

    tools = {}

    # YouTube — check if yt-dlp is installed
    yt_cfg = settings.youtube
    ytdlp_available = shutil.which("yt-dlp") is not None
    subs_file = Path(yt_cfg.get("subscriptions_file", "/state/youtube_subs.json"))
    subs_count = 0
    if subs_file.exists():
        try:
            import json
            subs = json.loads(subs_file.read_text())
            subs_count = len(subs) if isinstance(subs, list) else len(subs.keys()) if isinstance(subs, dict) else 0
        except Exception:
            pass
    tools["youtube"] = {
        "name": "YouTube",
        "status": "available" if ytdlp_available else "error",
        "emoji": "✅" if ytdlp_available else "❌",
        "info": f"yt-dlp {'installed' if ytdlp_available else 'missing'}, {subs_count} subscriptions",
    }

    # Audible — check if audible-cli is installed and auth exists
    audible_cfg = settings.audible
    audible_available = shutil.which("audible") is not None
    auth_file = Path(audible_cfg.get("auth_dir", "/config/audible")) / "auth.json"
    auth_status = "authenticated" if auth_file.exists() else "not authenticated"
    tools["audible"] = {
        "name": "Audible",
        "status": "available" if (audible_available and auth_file.exists()) else
                  ("warning" if audible_available else "error"),
        "emoji": "✅" if audible_available and auth_file.exists() else
                  ("⚠️" if audible_available else "❌"),
        "info": f"audible-cli {'installed' if audible_available else 'missing'}, {auth_status}",
    }

    # ROMs — check if internetarchive is installed
    ia_available = shutil.which("ia") is not None
    roms_cfg = settings.roms
    rom_dir = Path(roms_cfg.get("library_dir", "/media/roms"))
    rom_count = 0
    if rom_dir.exists():
        try:
            rom_count = sum(1 for _ in rom_dir.rglob("*") if _.is_file())
        except Exception:
            pass
    tools["roms"] = {
        "name": "Classic Games (ROMs)",
        "status": "available" if ia_available else "error",
        "emoji": "✅" if ia_available else "❌",
        "info": f"internetarchive {'installed' if ia_available else 'missing'}, {rom_count} files in library",
    }

    # Bandcamp — check if bandcamp-dl is installed
    bc_available = shutil.which("bandcamp-dl") is not None
    tools["bandcamp"] = {
        "name": "Bandcamp",
        "status": "available" if bc_available else "error",
        "emoji": "✅" if bc_available else "❌",
        "info": f"bandcamp-dl {'installed' if bc_available else 'missing'}",
    }

    return tools


async def _gather_activity(settings) -> list:
    """Get recent activity from Sonarr + Radarr history."""
    from src.tools.sonarr import SonarrClient
    from src.tools.radarr import RadarrClient
    activity = []

    try:
        cfg = settings.sonarr
        client = SonarrClient(cfg["url"], cfg["api_key"])
        history = await client._get("/history", params={"pageSize": 5})
        records = history.get("records", []) if isinstance(history, dict) else []
        for r in records[:3]:
            series = r.get("series") or {}
            episode = r.get("episode") or {}
            data = r.get("data") or {}
            title = series.get("title", "")
            if not title:
                # Try extracting from the imported/downloaded path in data
                path = data.get("importedPath") or data.get("droppedPath") or data.get("downloadUrl") or ""
                if path:
                    # Extract a readable title from the filename
                    import os
                    fname = os.path.basename(path.split("?")[0])
                    title = fname.replace(".mkv", "").replace(".mp4", "").replace(".", " ")[:60]
                else:
                    title = "Unknown"
            if episode.get("seasonNumber") is not None:
                title += f" S{episode['seasonNumber']:02d}E{episode.get('episodeNumber', 0):02d}"
            activity.append({
                "service": "Sonarr",
                "event": r.get("eventType", "unknown"),
                "title": title,
                "time": r.get("date", ""),
            })
    except Exception:
        pass

    try:
        cfg = settings.radarr
        client = RadarrClient(cfg["url"], cfg["api_key"])
        history = await client._get("/history", params={"pageSize": 5})
        records = history.get("records", []) if isinstance(history, dict) else []
        for r in records[:3]:
            movie = r.get("movie") or {}
            data = r.get("data") or {}
            title = movie.get("title", "")
            if not title:
                path = data.get("importedPath") or data.get("droppedPath") or ""
                if path:
                    import os
                    fname = os.path.basename(path)
                    title = fname.replace(".mkv", "").replace(".mp4", "").replace(".", " ")[:60]
                else:
                    title = "Unknown"
            activity.append({
                "service": "Radarr",
                "event": r.get("eventType", "unknown"),
                "title": title,
                "time": r.get("date", ""),
            })
    except Exception:
        pass

    # Sort by time descending
    activity.sort(key=lambda x: x.get("time", ""), reverse=True)
    return activity[:6]


async def _gather_disk_space(settings) -> dict:
    """Try to get SABnzbd disk space (it reports NAS storage info)."""
    try:
        cfg = settings.sabnzbd
        if not cfg.get("url"):
            return {}
        import httpx
        base = cfg["url"].rstrip("/")
        params = {"mode": "queue", "output": "json", "apikey": cfg["api_key"]}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base}/api", params=params)
            resp.raise_for_status()
            data = resp.json()
        queue = data.get("queue", {})
        return {
            "download_dir": queue.get("download_dir", ""),
            "disk_free_1": queue.get("disk_free_1", ""),
            "disk_total_1": queue.get("disk_total_1", ""),
        }
    except Exception:
        return {}


def _format_queue_item(record: dict) -> dict:
    """Format a Sonarr/Radarr queue record for display."""
    # Try multiple fields for the title
    name = ""
    series = record.get("series") or {}
    movie = record.get("movie") or {}
    if series.get("title"):
        name = series["title"]
        episode = record.get("episode") or {}
        if episode.get("seasonNumber") is not None:
            name += f" S{episode['seasonNumber']:02d}E{episode.get('episodeNumber', 0):02d}"
    elif movie.get("title"):
        name = movie["title"]
        year = movie.get("year")
        if year:
            name += f" ({year})"
    elif record.get("title"):
        name = record["title"]

    size = record.get("size", 0)
    size_mb = size / 1024 / 1024 if size else 0
    progress = 0
    if record.get("sizeleft") and record.get("size"):
        try:
            total = float(record.get("size", 1))
            left = float(record.get("sizeleft", 0))
            progress = round((1 - left / total) * 100) if total > 0 else 0
        except (ValueError, TypeError):
            progress = 0
    elif size and not record.get("sizeleft"):
        progress = 100
    return {
        "name": name or "Unknown",
        "progress": progress,
        "size": f"{size_mb:.0f} MB" if size_mb > 1 else "",
        "status": record.get("status", "unknown"),
        "tracked": record.get("trackedDownloadStatus", ""),
    }


def _calc_sabnzbd_progress(slot: dict) -> int:
    """Calculate progress percentage from SABnzbd slot data."""
    try:
        mb = float(slot.get("mb", 0))
        mb_left = float(slot.get("mbleft", 0))
        if mb > 0:
            return round((1 - mb_left / mb) * 100)
    except (ValueError, TypeError):
        pass
    return 0


# ── inline HTML ──────────────────────────────────────────────────────────

_DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<title>Media Agent Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #0d1117; color: #c9d1d9; min-height: 100vh;
    -webkit-tap-highlight-color: transparent; -webkit-text-size-adjust: 100%; overflow-x: hidden;
  }
  .container { max-width: 900px; margin: 0 auto; padding: 16px; }

  /* Header */
  .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
  .header h1 { font-size: 1.3rem; display: flex; align-items: center; gap: 8px; }
  .header h1 small { font-size: 0.75rem; color: #8b949e; font-weight: 400; }
  .header .timestamp { font-size: 0.75rem; color: #8b949e; text-align: right; }
  .refresh-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px;
    background: #2ea043; transition: background 0.3s;
  }
  .refresh-dot.fetching { background: #58a6ff; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

  /* Status bar */
  .status-bar {
    padding: 10px 14px; border-radius: 8px; margin-bottom: 16px;
    font-size: 0.85rem; font-weight: 600; text-align: center;
  }
  .status-bar.healthy { background: #0d2818; border: 1px solid #2ea043; color: #7ee787; }
  .status-bar.degraded { background: #2d2200; border: 1px solid #bb8009; color: #d29922; }

  /* Layout */
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
  @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
  .full-width { grid-column: 1 / -1; }

  /* Cards */
  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 14px;
  }
  .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .card-header h2 { font-size: 0.95rem; font-weight: 600; }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.65rem;
    font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .badge-healthy { background: #0d2818; color: #7ee787; border: 1px solid #2ea043; }
  .badge-warning { background: #2d2200; color: #d29922; border: 1px solid #bb8009; }
  .badge-error   { background: #3d1114; color: #f85149; border: 1px solid #da3633; }

  /* Queue items */
  .queue-item { padding: 6px 0; border-bottom: 1px solid #21262d; font-size: 0.8rem; }
  .queue-item:last-child { border-bottom: none; }
  .queue-item .name { color: #c9d1d9; margin-bottom: 3px; }
  .progress-bar {
    height: 4px; background: #21262d; border-radius: 2px; overflow: hidden; margin-top: 3px;
  }
  .progress-fill {
    height: 100%; background: #58a6ff; border-radius: 2px; transition: width 0.3s;
  }
  .queue-meta { font-size: 0.7rem; color: #8b949e; margin-top: 2px; }

  /* Activity */
  .activity-item { padding: 5px 0; border-bottom: 1px solid #21262d; font-size: 0.8rem; display: flex; gap: 8px; align-items: center; }
  .activity-item:last-child { border-bottom: none; }
  .activity-tag {
    display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.65rem;
    font-weight: 600; text-transform: uppercase; flex-shrink: 0;
  }
  .tag-grabbed { background: #1f6feb33; color: #58a6ff; }
  .tag-imported { background: #0d2818; color: #7ee787; }
  .tag-failed { background: #3d1114; color: #f85149; }
  .tag-download { background: #1f6feb33; color: #58a6ff; }
  .activity-title { flex-grow: 1; color: #c9d1d9; }

  /* Quick actions */
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .action-btn {
    min-height: 44px; padding: 10px 14px; border: 1px solid #30363d; border-radius: 6px;
    background: #21262d; color: #c9d1d9; font-size: 0.8rem; cursor: pointer;
    transition: all 0.15s; touch-action: manipulation; user-select: none;
  }
  .action-btn:hover { border-color: #58a6ff; color: #58a6ff; }
  .action-btn:active { transform: scale(0.97); }
  .action-btn.busy { opacity: 0.5; cursor: wait; }

  /* Chat */
  .chat-section {
    margin-top: 4px; border: 1px solid #30363d; border-radius: 8px;
    background: #161b22; overflow: hidden;
  }
  .chat-messages {
    max-height: 320px; overflow-y: auto; padding: 12px; scroll-behavior: smooth;
  }
  .chat-msg { margin-bottom: 10px; font-size: 0.83rem; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; }
  .chat-msg.user { color: #58a6ff; }
  .chat-msg.agent { color: #c9d1d9; }
  .chat-msg.system { color: #8b949e; font-style: italic; font-size: 0.75rem; }
  .chat-msg .label { font-size: 0.65rem; text-transform: uppercase; color: #484f58; margin-bottom: 2px; }
  .chat-input-area { display: flex; border-top: 1px solid #30363d; }
  .chat-input {
    flex-grow: 1; padding: 12px; border: none; background: #0d1117; color: #c9d1d9;
    font-size: 16px; font-family: inherit; outline: none;
  }
  .chat-send {
    padding: 10px 20px; border: none; background: #238636; color: white;
    font-size: 0.85rem; font-weight: 600; cursor: pointer; transition: background 0.15s;
  }
  .chat-send:hover { background: #2ea043; }
  .chat-send:disabled { background: #21262d; color: #484f58; cursor: wait; }

  /* Loading + misc */
  .spinner {
    display: inline-block; border: 2px solid #30363d; border-top-color: #58a6ff;
    border-radius: 50%; width: 14px; height: 14px; animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .empty { color: #484f58; font-size: 0.8rem; font-style: italic; padding: 8px 0; }
  .footer { text-align: center; color: #484f58; font-size: 0.7rem; padding: 16px 0 8px; }
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>🎬 Media Agent <small>Dashboard</small></h1>
    <div class="timestamp"><span class="refresh-dot" id="refresh-dot"></span><span id="timestamp">Loading...</span></div>
  </div>

  <div id="status-bar" class="status-bar healthy">Loading...</div>

  <!-- Quick Actions -->
  <div class="card" style="margin-bottom: 16px;">
    <div class="actions">
      <button class="action-btn" onclick="quickAction('is everything healthy?')">Health Check</button>
      <button class="action-btn" onclick="quickAction('what is downloading?')">Downloads</button>
      <button class="action-btn" onclick="quickAction('list my tv shows')">TV Shows</button>
      <button class="action-btn" onclick="quickAction('how many movies do I have?')">Movies</button>
      <button class="action-btn" onclick="quickAction('what was recently added to emby?')">Recent</button>
      <button class="action-btn" onclick="quickAction('what is airing this week?')">Calendar</button>
      <button class="action-btn" onclick="quickAction('search for missing episodes')">Find Missing</button>
      <button class="action-btn" onclick="quickAction('check disk space')">Disk Space</button>
      <button class="action-btn" onclick="quickAction('check all queues')">All Queues</button>
      <button class="action-btn" onclick="quickAction('list download station tasks')">Torrents</button>
    </div>
  </div>

  <!-- Service cards + Queue -->
  <div class="grid">
    <div class="card" id="sonarr-card">
      <div class="card-header"><h2 id="sonarr-title">📺 Sonarr</h2><span id="sonarr-badge" class="badge badge-error">...</span></div>
      <div id="sonarr-body" class="card-body"></div>
    </div>
    <div class="card" id="radarr-card">
      <div class="card-header"><h2 id="radarr-title">🎬 Radarr</h2><span id="radarr-badge" class="badge badge-error">...</span></div>
      <div id="radarr-body" class="card-body"></div>
    </div>
    <div class="card" id="emby-card">
      <div class="card-header"><h2 id="emby-title">📺 Emby</h2><span id="emby-badge" class="badge badge-error">...</span></div>
      <div id="emby-body" class="card-body"></div>
    </div>
    <div class="card" id="sabnzbd-card">
      <div class="card-header"><h2 id="sabnzbd-title">⚡ SABnzbd</h2><span id="sabnzbd-badge" class="badge badge-error">...</span></div>
      <div id="sabnzbd-body" class="card-body"></div>
    </div>
    <div class="card" id="download-station-card">
      <div class="card-header"><h2 id="download-station-title">🧲 Download Station</h2><span id="download-station-badge" class="badge badge-error">...</span></div>
      <div id="download-station-body" class="card-body"></div>
    </div>
  </div>

  <!-- Local Tools Status -->
  <div class="card" style="margin-bottom: 16px;">
    <div class="card-header"><h2>🛠️ Content Providers</h2></div>
    <div id="local-tools" style="display: flex; gap: 12px; flex-wrap: wrap;"></div>
  </div>

  <!-- Activity Feed -->
  <div class="card" style="margin-bottom: 16px;">
    <div class="card-header"><h2>📋 Recent Activity</h2></div>
    <div id="activity-feed"><div class="empty">Loading...</div></div>
  </div>

  <!-- Chat -->
  <div class="chat-section">
    <div class="card-header" style="padding: 10px 12px; border-bottom: 1px solid #30363d;">
      <h2>💬 Chat with Media Agent</h2>
    </div>
    <div class="chat-messages" id="chat-messages">
      <div class="chat-msg system">Ask me anything — search, add, check status, manage downloads...</div>
    </div>
    <div class="chat-input-area">
      <input type="text" class="chat-input" id="chat-input"
        placeholder="Type a message... (e.g. 'add Breaking Bad', 'what's downloading?')"
        onkeydown="if(event.key==='Enter')sendChat()">
      <button class="chat-send" id="chat-send" onclick="sendChat()">Send</button>
    </div>
  </div>

  <div class="footer">Media Agent &mdash; auto-refresh 30s &mdash; <span id="tool-count">--</span> tools loaded</div>

</div>

<script>
const CARD_SERVICES = ["sonarr", "radarr", "emby", "sabnzbd", "download_station"];

function esc(text) {
  const d = document.createElement("div");
  d.textContent = text || "";
  return d.innerHTML;
}

function badge(status) {
  const display = status === "download_station" ? "download-station" : status;
  return `<span class="badge badge-${status}">${status}</span>`;
}

function progressBar(pct) {
  return `<div class="progress-bar"><div class="progress-fill" style="width:${Math.max(0, Math.min(100, pct))}%"></div></div>`;
}

function renderService(key, svc) {
  // Map service keys to element IDs (download_station → download-station)
  const elemKey = key.replace(/_/g, "-");
  const card = document.getElementById(elemKey + "-card");
  if (!svc) {
    if (card) card.style.display = "none";
    return;
  }
  if (card) card.style.display = "";
  document.getElementById(elemKey + "-title").textContent = `${svc.emoji} ${esc(svc.name)}`;
  const badgeEl = document.getElementById(elemKey + "-badge");
  badgeEl.className = `badge badge-${svc.status}`;
  badgeEl.textContent = svc.status;

  let body = "";
  if (svc.library_count !== undefined) {
    body += `<div style="font-size:0.8rem;color:#8b949e;margin-bottom:6px;">Library: <strong style="color:#c9d1d9;">${svc.library_count}</strong> items</div>`;
  }
  if (svc.health) {
    body += `<div style="font-size:0.75rem;margin-bottom:8px;">${esc(svc.health.substring(0, 150))}</div>`;
  }
  if (svc.queue_items && svc.queue_items.length > 0) {
    body += `<div style="font-size:0.7rem;text-transform:uppercase;color:#484f58;margin-bottom:4px;">Queue (${svc.queue_count})</div>`;
    for (const item of svc.queue_items) {
      body += `<div class="queue-item">
        <div class="name">${esc(item.name)}</div>
        ${progressBar(item.progress || 0)}
        <div class="queue-meta">${esc(item.size || "")} ${item.status ? "· " + esc(item.status) : ""} · ${item.progress || 0}%</div>
      </div>`;
    }
  } else if (svc.queue_count === 0) {
    body += `<div class="empty">Queue empty</div>`;
  }
  if (svc.recent && svc.recent.length > 0) {
    body += `<div style="font-size:0.7rem;text-transform:uppercase;color:#484f58;margin-top:6px;margin-bottom:4px;">Recently Added</div>`;
    for (const r of svc.recent) {
      body += `<div style="font-size:0.78rem;color:#8b949e;">• ${esc(r.name)}</div>`;
    }
  }
  if (svc.speed) {
    body += `<div class="queue-meta" style="margin-top:6px;">Speed: ${esc(svc.speed)} KB/s</div>`;
  }
  document.getElementById(elemKey + "-body").innerHTML = body;
}

function renderLocalTools(tools) {
  const el = document.getElementById("local-tools");
  if (!tools) {
    el.innerHTML = '<div class="empty">Checking...</div>';
    return;
  }
  let html = "";
  for (const [key, tool] of Object.entries(tools)) {
    html += `<div style="flex: 1; min-width: 140px; padding: 8px; background: #0d1117; border-radius: 6px; border: 1px solid #30363d;">
      <div style="font-size: 0.8rem; font-weight: 600; margin-bottom: 3px;">${tool.emoji} ${esc(tool.name)}</div>
      <div style="font-size: 0.68rem; color: #8b949e;">${esc(tool.info)}</div>
    </div>`;
  }
  el.innerHTML = html;
}

function renderActivity(items) {
  const el = document.getElementById("activity-feed");
  if (!items || items.length === 0) {
    el.innerHTML = `<div class="empty">No recent activity</div>`;
    return;
  }
  let html = "";
  for (const a of items) {
    const eventTag = a.event || "unknown";
    const tagClass = {
      "grabbed": "tag-grabbed", "imported": "tag-imported",
      "downloadFailed": "tag-failed", "downloadFolderImported": "tag-imported",
      "episodeFileDeleted": "tag-failed",
    }[eventTag] || "tag-download";
    const time = a.time ? new Date(a.time).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : "";
    html += `<div class="activity-item">
      <span class="activity-tag ${tagClass}">${esc(a.service)}</span>
      <span class="activity-title">${esc(a.title)}</span>
      <span style="font-size:0.7rem;color:#484f58;">${time}</span>
    </div>`;
  }
  el.innerHTML = html;
}

function renderData(data) {
  const ts = document.getElementById("timestamp");
  ts.textContent = new Date(data.timestamp).toLocaleTimeString();

  const sb = document.getElementById("status-bar");
  const overall = data.overall_status;
  sb.className = `status-bar ${overall}`;
  sb.textContent = overall === "healthy" ? "✅ All Systems Operational" : "⚠️ Degraded";

  for (const key of CARD_SERVICES) {
    renderService(key, data.services[key]);
  }
  renderActivity(data.activity);
  renderLocalTools(data.local_tools);
}

async function fetchData() {
  const dot = document.getElementById("refresh-dot");
  dot.className = "refresh-dot fetching";
  try {
    const resp = await fetch("/api/dashboard/data");
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    renderData(data);
  } catch (e) {
    document.getElementById("status-bar").textContent = "❌ Failed to fetch: " + e.message;
    document.getElementById("status-bar").className = "status-bar degraded";
  }
  dot.className = "refresh-dot";
}

// ── Chat ──
async function sendChat() {
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  const msg = input.value.trim();
  if (!msg) return;

  input.value = "";
  sendBtn.disabled = true;
  sendBtn.textContent = "Sending...";

  const msgs = document.getElementById("chat-messages");

  // Show user message
  const userDiv = document.createElement("div");
  userDiv.className = "chat-msg user";
  userDiv.innerHTML = `<div class="label">You</div>${esc(msg)}`;
  msgs.appendChild(userDiv);
  msgs.scrollTop = msgs.scrollHeight;

  // Show thinking indicator
  const thinkingDiv = document.createElement("div");
  thinkingDiv.className = "chat-msg system";
  thinkingDiv.id = "thinking-indicator";
  thinkingDiv.innerHTML = `<span class="spinner"></span> Thinking...`;
  msgs.appendChild(thinkingDiv);
  msgs.scrollTop = msgs.scrollHeight;

  try {
    const resp = await fetch("/api/dashboard/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: msg}),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);

    // The endpoint streams Server-Sent Events: `data: {content, done, full, error}`.
    document.getElementById("thinking-indicator").remove();
    const agentDiv = document.createElement("div");
    agentDiv.className = "chat-msg agent";
    agentDiv.innerHTML = `<div class="label">Media Agent</div><span class="body"></span>`;
    const body = agentDiv.querySelector(".body");
    msgs.appendChild(agentDiv);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "", acc = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let payload;
        try { payload = JSON.parse(line.slice(6)); } catch (_) { continue; }
        if (payload.error) { acc = payload.error; }
        else if (payload.content) { acc += payload.content; }
        else if (payload.done && !acc) { acc = payload.full || "No response."; }
        body.textContent = acc;
        msgs.scrollTop = msgs.scrollHeight;
      }
    }
    if (!acc) body.textContent = "No response.";
  } catch (e) {
    const ind = document.getElementById("thinking-indicator");
    if (ind) ind.remove();
    const errDiv = document.createElement("div");
    errDiv.className = "chat-msg system";
    errDiv.textContent = "❌ Failed to get response: " + e.message;
    msgs.appendChild(errDiv);
  }

  sendBtn.disabled = false;
  sendBtn.textContent = "Send";
}

function quickAction(msg) {
  document.getElementById("chat-input").value = msg;
  sendChat();
}

// ── Init ──
fetchData();
setInterval(fetchData, 30000);

// Focus chat input on load
document.getElementById("chat-input").focus();
</script>
</body>
</html>
"""
