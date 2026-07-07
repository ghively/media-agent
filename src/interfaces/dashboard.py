"""Web dashboard for Media Agent.

Mounts on the existing FastAPI app (from openai_api.py) to provide a
browser-based dashboard showing service health, active downloads, and
recent activity.

Usage in main.py / API server startup::

    # In _run_server(), after the app is imported:
    from src.interfaces.dashboard import mount_dashboard
    mount_dashboard(app)
"""
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from src.config import get_settings


def mount_dashboard(app: FastAPI) -> None:
    """Register the dashboard routes on the FastAPI app.

    Adds:
      - GET /dashboard        → HTML dashboard page
      - GET /api/dashboard/data → JSON data endpoint
    """
    _register_routes(app)


def _register_routes(app: FastAPI) -> None:
    """Inner registration to keep the public API clean."""

    # ── HTML dashboard ─────────────────────────────────────────────────

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_page():
        """Render the main dashboard HTML page (inline, no external deps)."""
        return HTMLResponse(content=_DASHBOARD_HTML)

    # ── JSON data API ──────────────────────────────────────────────────

    @app.get("/api/dashboard/data", include_in_schema=False)
    async def dashboard_data():
        """Return live dashboard data as JSON."""
        health_data = await _gather_health_data()
        return JSONResponse(health_data)


# ── data gathering ────────────────────────────────────────────────────────


async def _arr_card(name: str, health_tool, queue_tool) -> dict:
    """Build a dashboard card for an *arr service from its health/queue tools."""
    try:
        # These are LangChain tools — invoke via .ainvoke, not direct calls
        health_text = await health_tool.ainvoke({})
        queue_text = await queue_tool.ainvoke({})
        ok = "✅" in health_text
        return {
            "name": name,
            "status": "healthy" if ok else "warning",
            "health": health_text,
            "queue": queue_text,
            "emoji": "✅" if ok else "⚠️",
        }
    except Exception as e:
        return {
            "name": name,
            "status": "error",
            "health": f"❌ {e}",
            "queue": "N/A",
            "emoji": "❌",
        }


async def _gather_health_data() -> dict:
    """Collect live status from all services asynchronously."""
    from src.tools.sonarr import get_tv_health, get_tv_queue
    from src.tools.radarr import get_movie_health, get_movie_queue
    from src.tools.emby import EmbyClient

    settings = get_settings()
    now = datetime.now(timezone.utc).isoformat()

    services = {}
    services["sonarr"] = await _arr_card("Sonarr", get_tv_health, get_tv_queue)
    services["radarr"] = await _arr_card("Radarr", get_movie_health, get_movie_queue)

    # Emby
    try:
        emby_settings = settings.emby
        client = EmbyClient(emby_settings["url"], emby_settings["api_key"])
        libraries = await client._get("/emby/Library/VirtualFolders")
        emby_ok = isinstance(libraries, list)
        services["emby"] = {
            "name": "Emby",
            "status": "healthy" if emby_ok else "warning",
            "libraries": len(libraries) if isinstance(libraries, list) else 0,
            "emoji": "✅" if emby_ok else "⚠️",
        }
    except Exception:
        services["emby"] = {
            "name": "Emby",
            "status": "error",
            "libraries": 0,
            "emoji": "❌",
        }

    # Overall
    all_healthy = all(s["status"] == "healthy" for s in services.values())
    return {
        "timestamp": now,
        "overall_status": "healthy" if all_healthy else "degraded",
        "services": services,
    }


# ── inline HTML ──────────────────────────────────────────────────────────


_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Media Agent Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #0d1117; color: #c9d1d9; padding: 24px; min-height: 100vh;
  }
  h1 { font-size: 1.5rem; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
  h1 small { font-size: 0.8rem; color: #8b949e; font-weight: 400; }
  .subtitle { color: #8b949e; margin-bottom: 24px; font-size: 0.9rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px;
    transition: border-color 0.2s;
  }
  .card:hover { border-color: #58a6ff; }
  .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .card-header h2 { font-size: 1.1rem; font-weight: 600; }
  .badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem;
    font-weight: 600; text-transform: uppercase;
  }
  .badge-healthy { background: #1b4332; color: #7ee787; border: 1px solid #2ea043; }
  .badge-warning { background: #3d2e00; color: #d29922; border: 1px solid #bb8009; }
  .badge-error   { background: #3d1114; color: #f85149; border: 1px solid #da3633; }
  .card-body { font-size: 0.85rem; line-height: 1.5; white-space: pre-wrap; }
  .card-body .ok   { color: #7ee787; }
  .card-body .warn { color: #d29922; }
  .card-body .err  { color: #f85149; }
  .footer { margin-top: 24px; text-align: center; color: #484f58; font-size: 0.8rem; }
  .loading { text-align: center; padding: 48px; color: #8b949e; }
  .loading .spinner { display: inline-block; border: 3px solid #30363d; border-top-color: #58a6ff;
    border-radius: 50%; width: 24px; height: 24px; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<h1>🎬 Media Agent <small>Dashboard</small></h1>
<div class="subtitle" id="timestamp">Loading...</div>

<div id="status-bar"></div>
<div class="grid" id="cards">
  <div class="loading"><div class="spinner"></div><br>Fetching service data...</div>
</div>
<div class="footer">Media Agent &mdash; refresh every 30s</div>

<script>
(async function() {
  const CARD_ORDER = ["sonarr", "radarr", "emby"];

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function badge(status) {
    const cls = "badge-" + status;
    return `<span class="badge ${cls}">${status}</span>`;
  }

  function renderData(data) {
    const ts = document.getElementById("timestamp");
    const d = new Date(data.timestamp);
    ts.textContent = "Last updated: " + d.toLocaleString();

    const sb = document.getElementById("status-bar");
    const overall = data.overall_status;
    sb.innerHTML = `<div class="card" style="margin-bottom:16px;border-color:${
      overall === "healthy" ? "#2ea043" : "#bb8009"
    }"><strong>Overall Status:</strong> ${overall === "healthy" ? "✅ All systems operational" : "⚠️ Degraded"}</div>`;

    const grid = document.getElementById("cards");
    grid.innerHTML = "";

    for (const key of CARD_ORDER) {
      const svc = data.services[key];
      if (!svc) continue;
      const card = document.createElement("div");
      card.className = "card";

      let bodyHtml = "";
      if (key === "sonarr" || key === "radarr") {
        const healthLines = (svc.health || "").split("\\n").map(l => escapeHtml(l)).join("<br>");
        const queueLines = (svc.queue || "").split("\\n").map(l => escapeHtml(l)).join("<br>");
        bodyHtml = `<div><strong>Health:</strong></div><div class="ok">${healthLines}</div><br><div><strong>Queue:</strong></div><div>${queueLines}</div>`;
      } else if (key === "emby") {
        bodyHtml = `<div><strong>Libraries:</strong> ${svc.libraries}</div>`;
      }

      card.innerHTML = `
        <div class="card-header">
          <h2>${svc.emoji} ${escapeHtml(svc.name)}</h2>
          ${badge(svc.status)}
        </div>
        <div class="card-body">${bodyHtml}</div>
      `;
      grid.appendChild(card);
    }
  }

  async function fetchData() {
    try {
      const resp = await fetch("/api/dashboard/data");
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      renderData(data);
    } catch (e) {
      document.getElementById("cards").innerHTML =
        `<div class="card" style="border-color:#da3633"><div class="card-body err">Failed to fetch dashboard data: ${escapeHtml(e.message)}</div></div>`;
    }
  }

  await fetchData();
  setInterval(fetchData, 30000);
})();
</script>
</body>
</html>"""


# ── auto-mount convenience ──────────────────────────────────────────────


def auto_mount() -> None:
    """Auto-mount dashboard on the existing app when imported.

    Call this in ``openai_api.py`` after ``app = FastAPI(...)``::

        from src.interfaces.dashboard import auto_mount
        auto_mount()
    """
    try:
        from src.interfaces.openai_api import app
        mount_dashboard(app)
    except ImportError:
        pass  # App not ready yet; caller should mount explicitly