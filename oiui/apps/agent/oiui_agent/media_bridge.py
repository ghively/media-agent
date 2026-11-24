"""Bridge between media-agent and the OpenIntelligentUI agent (proof of concept).

What this module does:

- Puts the media-agent repo root on ``sys.path`` and loads its ~100 LangChain
  tools from ``src.tools.registry`` unchanged (Sonarr, Radarr, Emby, SABnzbd,
  ROMs, YouTube, ...). Service URLs and keys still come from media-agent's own
  ``config/settings.yaml`` + ``.env``, exactly as before.
- Adds three read-only "data" tools that return JSON instead of prose, so the
  model can draw progress bars and charts from real numbers.
- Enforces media-agent's confirmation rule on the server: every tool that adds,
  downloads, records, renames or deletes is refused unless the user clicked
  Approve on a ``requestMediaApproval`` card for that exact call in this turn.
  The model cannot get past this by itself; only a click in the browser does.

The deterministic fast path (``src/graphs/router.py``) is not used here: every
message in the new UI goes to the cloud model, so "what's downloading?" can
come back as a visual. The CLI, Telegram bot and old dashboard keep using it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import httpx
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# oiui/apps/agent/oiui_agent/media_bridge.py -> parents[4] is the media-agent repo root
MEDIA_AGENT_ROOT = Path(
    os.environ.get("MEDIA_AGENT_ROOT") or Path(__file__).resolve().parents[4]
)
if str(MEDIA_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(MEDIA_AGENT_ROOT))
# media-agent reads config/settings.yaml relative to the working directory;
# this agent runs from oiui/apps/agent, so point it at the repo's copy.
os.environ.setdefault(
    "MEDIA_AGENT_CONFIG", str(MEDIA_AGENT_ROOT / "config" / "settings.yaml")
)
# Service keys (SONARR_API_KEY, ...) stay in media-agent's own .env at the repo
# root. Load it without overriding anything already set.
try:
    from dotenv import load_dotenv

    load_dotenv(MEDIA_AGENT_ROOT / ".env", override=False)
except ImportError:  # python-dotenv is an OIUI agent dependency; belt and braces
    pass

APPROVAL_TOOL = "requestMediaApproval"
APPROVED = "APPROVED"

# Tools that change something: always need a click on Approve first.
ALWAYS_GATED = {
    # adds and downloads
    "add_tv_show", "add_movie", "add_artist", "download_media",
    "sabnzbd_add_nzb", "download_station_add", "qbittorrent_add",
    "youtube_download", "bandcamp_download", "audible_download",
    "twitch_record", "podcast_check_new",
    # subscriptions
    "youtube_add_subscription", "youtube_remove_subscription",
    "podcast_subscribe", "podcast_unsubscribe",
    # renames, requests, cleanup
    "library_undo_rename", "approve_media_request", "deny_media_request",
    "cleanup_schedule", "cleanup_run_now", "cleanup_set_retention",
    "cleanup_remove_rule",
}
# Bulk tools that only preview with confirm=False; the real run needs a click.
GATED_WHEN_CONFIRMED = {
    "rom_download", "bandcamp_download_collection", "audible_download_new",
    "library_fix_naming",
}


def load_media_tools() -> list:
    """media-agent's full tool list, unchanged."""
    from src.tools.registry import all_tools  # media-agent's registry

    return list(all_tools)


# ── read-only data tools (JSON for charts) ───────────────────────────────────


def _gb(value) -> float:
    try:
        return round(float(value) / (1024**3), 1)
    except (TypeError, ValueError):
        return 0.0


def _mb(value) -> float:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return 0.0


@tool
async def media_disk_usage_data() -> str:
    """Disk usage per media drive as JSON, for drawing disk-usage bars or charts.
    Returns {"disks": [{"path", "free_gb", "total_gb", "used_pct"}]} or {"error"}."""
    try:
        from src.config import get_settings

        s = get_settings().sonarr
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{s['url']}/api/v3/diskspace", headers={"X-Api-Key": s["api_key"]}
            )
            resp.raise_for_status()
            disks = []
            for d in resp.json():
                total = d.get("totalSpace", 0) or 0
                free = d.get("freeSpace", 0) or 0
                if total <= 0:
                    continue
                disks.append({
                    "path": d.get("path", "unknown"),
                    "free_gb": _gb(free),
                    "total_gb": _gb(total),
                    "used_pct": round((1 - free / total) * 100, 1),
                })
        return json.dumps({"source": "Sonarr diskspace API", "disks": disks})
    except Exception as e:  # media-agent convention: tools never raise
        return json.dumps({"error": f"{type(e).__name__}: could not read disk space"})


async def _arr_queue(client: httpx.AsyncClient, conf: dict, service: str) -> list[dict]:
    resp = await client.get(
        f"{conf['url']}/api/v3/queue",
        headers={"X-Api-Key": conf["api_key"]},
        params={"pageSize": 100},
    )
    resp.raise_for_status()
    data = resp.json()
    records = data.get("records", []) if isinstance(data, dict) else data
    items = []
    for r in records:
        size = r.get("size") or 0
        left = r.get("sizeleft") or 0
        items.append({
            "service": service,
            "title": r.get("title", "Unknown"),
            "status": r.get("status", ""),
            "size_mb": _mb(size / (1024**2)),
            "left_mb": _mb(left / (1024**2)),
            "percent": round((1 - left / size) * 100, 1) if size else 0.0,
            "time_left": r.get("timeleft", ""),
        })
    return items


@tool
async def media_download_queue_data() -> str:
    """Everything downloading right now, as JSON, for drawing progress bars.
    Combines SABnzbd (speed, MB left, per-item percent) with the Sonarr and
    Radarr queues. Returns {"sabnzbd": {...}, "items": [...], "errors": [...]}."""
    from src.config import get_settings

    settings = get_settings()
    out: dict = {"sabnzbd": None, "items": [], "errors": []}

    try:
        from src.tools.sabnzbd import _client as sab_client

        q = (await sab_client()._call("queue")).get("queue", {}) or {}
        out["sabnzbd"] = {
            "status": q.get("status", ""),
            "paused": bool(q.get("paused", False)),
            "speed": q.get("speed", ""),
            "total_mb": _mb(q.get("mb")),
            "left_mb": _mb(q.get("mbleft")),
            "time_left": q.get("timeleft", ""),
        }
        for slot in q.get("slots", []) or []:
            out["items"].append({
                "service": "SABnzbd",
                "title": slot.get("filename", "Unknown"),
                "status": slot.get("status", ""),
                "size_mb": _mb(slot.get("mb")),
                "left_mb": _mb(slot.get("mbleft")),
                "percent": _mb(slot.get("percentage")),
                "time_left": slot.get("timeleft", ""),
            })
    except Exception as e:
        out["errors"].append(f"SABnzbd: {type(e).__name__}")

    async with httpx.AsyncClient(timeout=10) as client:
        for service, conf in (("Sonarr", settings.sonarr), ("Radarr", settings.radarr)):
            try:
                out["items"].extend(await _arr_queue(client, conf, service))
            except Exception as e:
                out["errors"].append(f"{service}: {type(e).__name__}")
    return json.dumps(out)


@tool
async def media_service_health_data() -> str:
    """Up/down status of Sonarr, Radarr and Emby as JSON, for a status board.
    Returns {"services": [{"name", "ok", "issues", "detail"}]}."""
    from src.config import get_settings

    settings = get_settings()
    checks = (
        ("Sonarr", settings.sonarr, "/api/v3/health", "X-Api-Key"),
        ("Radarr", settings.radarr, "/api/v3/health", "X-Api-Key"),
        ("Emby", settings.emby, "/emby/System/Info", "X-Emby-Token"),
    )
    services = []
    async with httpx.AsyncClient(timeout=10) as client:
        for name, conf, path, header in checks:
            try:
                resp = await client.get(f"{conf['url']}{path}", headers={header: conf["api_key"]})
                resp.raise_for_status()
                body = resp.json()
                issues = body if isinstance(body, list) else []
                services.append({
                    "name": name,
                    "ok": True,
                    "issues": len(issues),
                    "detail": [i.get("message", "") for i in issues][:5],
                })
            except Exception as e:
                services.append({"name": name, "ok": False, "issues": 0, "detail": [type(e).__name__]})
    return json.dumps({"services": services})


data_tools = [media_disk_usage_data, media_download_queue_data, media_service_health_data]


# ── approval gate ────────────────────────────────────────────────────────────


def needs_approval(name: str, args: dict) -> bool:
    if name in ALWAYS_GATED:
        return True
    return name in GATED_WHEN_CONFIRMED and bool(args.get("confirm"))


def _defaults(tool_obj) -> dict:
    try:
        return {k: v.get("default") for k, v in (tool_obj.args or {}).items()}
    except Exception:
        return {}


def args_match(approved: dict, actual: dict, defaults: dict | None = None) -> bool:
    """Same call? Missing keys count as the tool's default value."""
    defaults = defaults or {}
    for key in set(approved) | set(actual):
        a = approved.get(key, defaults.get(key))
        b = actual.get(key, defaults.get(key))
        if a != b and str(a) != str(b):
            return False
    return True


def _parse_args_json(raw) -> dict | None:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def find_approval(messages: list, name: str, args: dict, current_call_id: str,
                  defaults: dict | None = None) -> str | None:
    """Return the id of an unused Approve click for this exact call, or None.

    An approval counts only if it came after the user's latest message, the
    user's answer starts with APPROVED, and no earlier executed call has
    already used it."""
    last_human = max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1
    )
    results = {
        m.tool_call_id: (m.content if isinstance(m.content, str) else str(m.content))
        for m in messages
        if isinstance(m, ToolMessage)
    }
    approvals: list[str] = []
    executed: list[tuple[str, dict]] = []
    for i, m in enumerate(messages):
        if i <= last_human or not isinstance(m, AIMessage):
            continue
        for call in m.tool_calls or []:
            cid = call.get("id")
            if call.get("name") == APPROVAL_TOOL:
                answer = results.get(cid, "")
                req = call.get("args", {}) or {}
                approved_args = _parse_args_json(req.get("argsJson"))
                if (
                    answer.strip().upper().startswith(APPROVED)
                    and req.get("tool") == name
                    and approved_args is not None
                    and args_match(approved_args, args, defaults)
                ):
                    approvals.append(cid)
            elif cid != current_call_id and call.get("name") == name and cid in results:
                if not results[cid].startswith("⛔"):
                    executed.append((cid, call.get("args", {}) or {}))
    # Each approval pays for one execution, oldest first.
    used = sum(1 for _, a in executed if args_match(a, args, defaults))
    return approvals[used] if used < len(approvals) else None


def refusal(name: str, args: dict, call_id: str) -> ToolMessage:
    return ToolMessage(
        content=(
            f"⛔ Not run: {name} needs the user's approval first. Call "
            f"{APPROVAL_TOOL} with tool=\"{name}\", argsJson set to exactly "
            f"{json.dumps(args, sort_keys=True)}, and a one-line summary. "
            "Run it only after the user clicks Approve. If they decline, don't retry."
        ),
        tool_call_id=call_id,
        name=name,
    )


class MediaApprovalMiddleware(AgentMiddleware):
    """Refuse gated media tools unless the user approved that exact call."""

    def _check(self, request):
        call = request.tool_call
        name = call.get("name", "")
        args = call.get("args", {}) or {}
        if not needs_approval(name, args):
            return None
        messages = (request.state or {}).get("messages", [])
        if find_approval(messages, name, args, call.get("id"), _defaults(request.tool)):
            logger.info("approved media action: %s", name)
            return None
        return refusal(name, args, call.get("id"))

    def wrap_tool_call(self, request, handler):
        return self._check(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._check(request) or await handler(request)


MEDIA_PROMPT = f"""
You are the user's personal media assistant for their home media library
(Sonarr, Radarr, Emby, SABnzbd, Download Station, qBittorrent, Lidarr,
Prowlarr, Komga, Calibre, YouTube, Bandcamp, Audible, podcasts, Twitch, ROMs).
Talk like a person: short and warm. Use the tools silently; never show tool
names or raw JSON in chat text.

## Visual answers for media data

- "What's downloading?" / queue questions: call media_download_queue_data and
  draw one progress bar per item (title, percent, MB left, time left) plus the
  overall SABnzbd speed. If everything is idle, say so in one line.
- Disk or storage questions: call media_disk_usage_data and draw a horizontal
  bar per drive (used vs free, with GB and percent).
- Health/status questions: call media_service_health_data and show a small
  status board (green ok, red down, issue counts).
- Lists (recent additions, missing episodes, search results): a table is fine.
- Only chart numbers a tool returned. If a tool reports an error, say which
  service failed instead of drawing empty charts.

## Confirmation rule (enforced by the server)

Never add, download, record, subscribe, unsubscribe, rename, approve, deny or
schedule cleanup on your own. For those actions:
1. Search or preview first and show what you found.
2. Call {APPROVAL_TOOL} with tool = the exact tool name, argsJson = the exact
   JSON arguments you will pass, and a one-line plain-English summary
   (include size for ROM sets and bulk downloads).
3. Only if the result starts with APPROVED, call that tool with exactly those
   arguments. If declined, acknowledge and stop.
Bulk tools (rom_download, bandcamp_download_collection, audible_download_new,
library_fix_naming) preview with confirm=false freely; the run with
confirm=true needs approval. Any gated call without approval is refused.
After adding a show or movie, trigger an Emby scan.
Search results show [tmdbId: N] for movies and [tvdbId: N] for TV: use the
right ID for the right service.
"""
