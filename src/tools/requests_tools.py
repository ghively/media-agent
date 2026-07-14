"""Media request lifecycle — the seerr loop, conversational.

submit → (auto-approve rules / quota check) → pending → approve/deny →
acquire via Sonarr/Radarr → availability sweep marks it Available and pushes
a Telegram note to the requester.

Requests are created by the router when a **non-admin** Telegram user asks
to add something (``create_request``), or by the LLM via the
``request_media`` tool. Admins add media directly, exactly as before — the
role system is off until ``users.admins`` is configured (see src/users.py).

The availability sweep (``check_availability``) is wired into the scheduler
in src/main.py: it diffs approved requests against Emby and notifies the
requester the moment their item is actually watchable — the highest-value
slice of the seerr notification fan-out.
"""
import logging

from langchain_core.tools import tool

from src import store
from src.engine.rules import evaluate_auto_approve
from src.users import display_name, is_admin, request_limit_for

logger = logging.getLogger(__name__)


def _quota_line(requester: str, used: int) -> str:
    count, days = request_limit_for(requester)
    if count <= 0:
        return ""
    return f"({used} of {count} requests used this {days}-day window)"


async def quota_available(requester: str) -> tuple[bool, str]:
    """Whether this requester may make another request, plus a status line."""
    count, days = request_limit_for(requester)
    if count <= 0:
        return True, ""
    used = await store.count_recent_requests(requester, days)
    if used >= count:
        return False, (f"you've used all {count} requests in the current "
                       f"{days}-day window — an admin can approve extras")
    return True, _quota_line(requester, used + 1)


async def _execute_add(req: dict, overrides: dict | None = None) -> str:
    """Run the actual Sonarr/Radarr add for an approved request."""
    overrides = overrides or {}
    if req["media_type"] == "movie":
        from src.tools.radarr import add_movie
        args = {"tmdb_id": int(req["source_id"]), "title": req["title"]}
        if overrides.get("quality_profile_id"):
            args["quality_profile_id"] = int(overrides["quality_profile_id"])
        if overrides.get("root_folder"):
            args["root_folder"] = overrides["root_folder"]
        return await add_movie.ainvoke(args)
    from src.tools.sonarr import add_tv_show
    args = {"tvdb_id": int(req["source_id"]), "title": req["title"]}
    if req.get("season"):
        args["season"] = int(req["season"])
    if overrides.get("quality_profile_id"):
        args["quality_profile_id"] = int(overrides["quality_profile_id"])
    if overrides.get("root_folder"):
        args["root_folder"] = overrides["root_folder"]
    return await add_tv_show.ainvoke(args)


async def create_request(requester: str, result: dict,
                         season: int | None = None) -> str:
    """Record a request from a search-result dict (see src/tools/search.py).

    Applies, in order: duplicate check, rolling quota, auto-approve rules.
    Auto-approved requests are executed immediately; the rest go pending and
    every admin gets a push. Returns the user-facing reply. Never raises.
    """
    try:
        title = str(result.get("title", "Unknown"))
        media_type = "movie" if result.get("source_type") == "movie" else "tv"
        source_id = result.get("id")
        if source_id is None:
            return f"❌ Can't request '{title}' — the search result has no usable ID."

        dupe = await store.find_duplicate_request(int(source_id), media_type)
        if dupe:
            who = display_name(dupe["requester"])
            return (f"ℹ️ '{title}' is already {dupe['status']} "
                    f"(request #{dupe['id']}, from {who}).")

        ok, quota_note = await quota_available(requester)
        if not ok:
            return f"⏸️ Can't request '{title}' — {quota_note}."

        req_id = await store.add_request(
            requester, title, media_type, int(source_id), season,
            str(result.get("year", "")))

        # Auto-approve rules (phase 4): first match wins.
        rule_request = {
            "requester": requester,
            "requester_name": display_name(requester),
            "media_type": media_type,
            "title": title,
            "year": result.get("year"),
            "season_count": result.get("season_count"),
            "genres": result.get("genres") or [],
        }
        try:
            rules = await store.rules_list(kind="auto_approve")
            actions = evaluate_auto_approve(rules, rule_request)
        except Exception:
            logger.exception("auto-approve rule evaluation failed")
            actions = None

        season_note = f" (season {season})" if season else ""
        if actions and actions.get("approve"):
            await store.set_request_status(req_id, "approved", decided_by="rule")
            add_reply = await _execute_add(await store.get_request(req_id), actions)
            return (f"✅ Request #{req_id}: '{title}'{season_note} was "
                    f"auto-approved by a rule.\n{add_reply}\n{quota_note}").strip()

        from src.notify import notify_admins
        who = display_name(requester)
        await notify_admins(
            "Media Agent: approval needed",
            f"Request #{req_id}: {who} wants '{title}'{season_note} "
            f"[{media_type}]. Reply 'approve #{req_id}' or 'deny #{req_id}'.")
        return (f"📨 Request #{req_id} submitted: '{title}'{season_note}. "
                f"An admin has been asked to approve it. {quota_note}").strip()
    except Exception as e:
        logger.exception("create_request failed")
        return f"❌ Couldn't record the request: {type(e).__name__}: {e}"


async def approve(request_id: int, decided_by: str) -> str:
    """Approve a pending request and run the add. Never raises."""
    try:
        req = await store.get_request(request_id)
        if req is None:
            return f"❌ No request #{request_id}."
        if req["status"] == "approved":
            return f"ℹ️ Request #{request_id} ('{req['title']}') is already approved."
        if req["status"] == "available":
            return f"ℹ️ Request #{request_id} ('{req['title']}') is already available."
        await store.set_request_status(request_id, "approved", decided_by=decided_by)
        add_reply = await _execute_add(req)
        from src.notify import notify_chat
        await notify_chat(req["requester"], "Request approved ✅",
                          f"'{req['title']}' was approved and is downloading. "
                          f"You'll get another message when it's ready to watch.")
        return f"✅ Approved request #{request_id} ('{req['title']}').\n{add_reply}"
    except Exception as e:
        logger.exception("approve failed")
        return f"❌ Couldn't approve request #{request_id}: {type(e).__name__}: {e}"


async def deny(request_id: int, decided_by: str, reason: str = "") -> str:
    """Deny a pending request and tell the requester. Never raises."""
    try:
        req = await store.get_request(request_id)
        if req is None:
            return f"❌ No request #{request_id}."
        await store.set_request_status(
            request_id, "denied", decided_by=decided_by, note=reason)
        from src.notify import notify_chat
        note = f" Reason: {reason}" if reason else ""
        await notify_chat(req["requester"], "Request denied",
                          f"'{req['title']}' wasn't approved.{note}")
        return f"🚫 Denied request #{request_id} ('{req['title']}').{note}"
    except Exception as e:
        logger.exception("deny failed")
        return f"❌ Couldn't deny request #{request_id}: {type(e).__name__}: {e}"


async def format_requests(status: str | None = None) -> str:
    """Human-readable request list (router + tool + dashboard share this)."""
    try:
        requests = await store.list_requests(status=status)
        if not requests:
            scope = f" {status}" if status else ""
            return f"📭 No{scope} media requests."
        icons = {"pending": "⏳", "approved": "▶️", "denied": "🚫", "available": "✅"}
        lines = [f"📨 Media requests ({len(requests)}):", ""]
        for r in requests:
            season = f" S{r['season']}" if r.get("season") else ""
            who = display_name(r["requester"])
            lines.append(f"  {icons.get(r['status'], '•')} #{r['id']} "
                         f"{r['title']}{season} [{r['media_type']}] — "
                         f"{r['status']}, from {who}")
        pending = [r for r in requests if r["status"] == "pending"]
        if pending:
            lines.append("")
            lines.append("Say 'approve #N' or 'deny #N' to decide pending ones.")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Couldn't list requests: {type(e).__name__}: {e}"


# ── availability sweep (scheduler job) ───────────────────────────────────────

async def _emby_has(title: str, media_type: str) -> bool:
    """Exact-ish title match in Emby for the right item type."""
    from src.tools.emby import _client
    include = "Movie" if media_type == "movie" else "Series"
    result = await _client()._get("/emby/Items", params={
        "SearchTerm": title, "Recursive": "true", "Limit": "10",
        "IncludeItemTypes": include,
    })
    wanted = title.strip().lower()
    for item in result.get("Items", []):
        if str(item.get("Name", "")).strip().lower() == wanted:
            return True
    return False


async def check_availability() -> str:
    """Mark approved requests that now exist in Emby and notify requesters.
    Wired as a scheduler job; safe to call ad hoc. Never raises."""
    try:
        waiting = await store.awaiting_availability()
    except Exception:
        logger.exception("availability sweep: store unavailable")
        return "availability sweep skipped (store unavailable)"
    if not waiting:
        return "availability sweep: nothing waiting"
    found = 0
    for req in waiting:
        try:
            if not await _emby_has(req["title"], req["media_type"]):
                continue
        except Exception:
            # Emby unreachable or flaky: unknown state = no action; the next
            # sweep retries. Never mark available on a guess.
            logger.warning("availability sweep: Emby check failed for %r",
                           req["title"], exc_info=True)
            continue
        await store.set_request_status(req["id"], "available")
        found += 1
        from src.notify import notify_chat
        await notify_chat(req["requester"], "Ready to watch 🎬",
                          f"'{req['title']}' is now in the library.")
    return f"availability sweep: {found} of {len(waiting)} request(s) now available"


# ── LLM-path tools ───────────────────────────────────────────────────────────

@tool
async def list_media_requests(status: str = "") -> str:
    """List media requests (the request/approval queue). Optional status
    filter: pending, approved, denied, or available."""
    return await format_requests(status or None)


@tool
async def approve_media_request(request_id: int) -> str:
    """Approve a pending media request by its #id and start the download."""
    return await approve(request_id, decided_by="agent")


@tool
async def deny_media_request(request_id: int, reason: str = "") -> str:
    """Deny a pending media request by its #id, with an optional reason."""
    return await deny(request_id, decided_by="agent", reason=reason)
