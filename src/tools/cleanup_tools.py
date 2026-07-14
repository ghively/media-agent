"""Library cleanup — Maintainerr's patterns, conversational.

Quarantine-before-delete: nothing is ever deleted immediately. "delete Dune
in 14 days" puts the item in a *quarantine ledger* (and, best-effort, a
visible "Leaving Soon" Emby collection); the daily sweep executes the action
only after the grace period, and "keep Dune" reprieves it any time before
that. Every sweep action is pushed via notifications first — the
notification-before-action pattern.

Graduated actions (per item, not delete-only): ``delete`` removes from
Sonarr/Radarr *with files* and adds an import-list exclusion so list syncs
can't re-add it; ``unmonitor`` keeps the files but stops future grabs.

Retention rules: "keep the newest 10 episodes of NewsShow" — the sweep
unmonitors and deletes episode files older than the newest N downloaded,
recomputed fresh each run (a rolling window, like Maintainerr's rank
properties).

Fail-safe invariant (verified Maintainerr semantics): **unknown state = no
action**. If Sonarr/Radarr can't be reached while evaluating an item, that
item is skipped this run — an outage must never cause a surprise deletion.
"""
import logging

from langchain_core.tools import tool

from src import store
from src.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_GRACE_DAYS = 7
LEAVING_SOON = "Leaving Soon"


def _grace_days() -> int:
    try:
        return int(get_settings().cleanup.get("grace_days", DEFAULT_GRACE_DAYS))
    except Exception:
        return DEFAULT_GRACE_DAYS


# ── *arr lookups & actions ───────────────────────────────────────────────────

async def _find_in_arr(title: str) -> dict | None:
    """Find a library item by title in Sonarr then Radarr.
    Returns {kind, arr_id, title} or None. Raises on connection failure so
    callers can distinguish "not found" from "couldn't check"."""
    wanted = title.strip().lower()
    from src.tools.sonarr import _client as sonarr_client
    for s in await sonarr_client()._get("/series"):
        if s.get("title", "").strip().lower() == wanted:
            return {"kind": "tv", "arr_id": s["id"], "title": s["title"]}
    from src.tools.radarr import _client as radarr_client
    for m in await radarr_client()._get("/movie"):
        if m.get("title", "").strip().lower() == wanted:
            return {"kind": "movie", "arr_id": m["id"], "title": m["title"]}
    return None


async def _execute_action(item: dict) -> str:
    """Run a due quarantine item's action. Raises on service failure."""
    if item["kind"] == "tv":
        from src.tools.sonarr import _client as client
        if item["action"] == "unmonitor":
            series = await client()._get(f"/series/{item['arr_id']}")
            series["monitored"] = False
            await client()._put(f"/series/{item['arr_id']}", series)
            return f"unmonitored '{item['title']}'"
        await client()._delete(f"/series/{item['arr_id']}", params={
            "deleteFiles": "true", "addImportListExclusion": "true"})
        return f"deleted '{item['title']}' (files removed, list-excluded)"
    from src.tools.radarr import _client as client
    if item["action"] == "unmonitor":
        movie = await client()._get(f"/movie/{item['arr_id']}")
        movie["monitored"] = False
        await client()._put(f"/movie/{item['arr_id']}", movie)
        return f"unmonitored '{item['title']}'"
    await client()._delete(f"/movie/{item['arr_id']}", params={
        "deleteFiles": "true", "addImportListExclusion": "true"})
    return f"deleted '{item['title']}' (files removed, list-excluded)"


# ── "Leaving Soon" Emby collection (best-effort visibility) ──────────────────

async def _emby_leaving_soon(title: str) -> None:
    """Add the item to a visible 'Leaving Soon' Emby collection. Purely
    cosmetic — any failure is swallowed; the ledger is the source of truth."""
    try:
        from src.tools.emby import _client
        client = _client()
        found = await client._get("/emby/Items", params={
            "SearchTerm": title, "Recursive": "true", "Limit": "5",
            "IncludeItemTypes": "Movie,Series"})
        items = [i for i in found.get("Items", [])
                 if i.get("Name", "").strip().lower() == title.strip().lower()]
        if not items:
            return
        item_id = items[0]["Id"]
        boxsets = await client._get("/emby/Items", params={
            "SearchTerm": LEAVING_SOON, "IncludeItemTypes": "BoxSet",
            "Recursive": "true", "Limit": "5"})
        existing = [b for b in boxsets.get("Items", [])
                    if b.get("Name") == LEAVING_SOON]
        if existing:
            await client._post(
                f"/emby/Collections/{existing[0]['Id']}/Items?Ids={item_id}")
        else:
            await client._post(
                f"/emby/Collections?Name={LEAVING_SOON}&Ids={item_id}")
    except Exception:
        logger.debug("leaving-soon collection update failed", exc_info=True)


# ── retention rules ("keep newest N episodes") ───────────────────────────────

async def _apply_retention_rule(rule: dict) -> str | None:
    """Delete episode files beyond the newest N for one show.
    Returns a summary line, or None when nothing was done. Raises on
    connection failure — the caller skips the rule (fail-safe)."""
    conditions, actions = rule["conditions"], rule["actions"]
    keep = int(actions.get("keep_last", 0))
    if keep <= 0:
        return None
    title = str(conditions.get("series_title", "")).strip().lower()
    from src.tools.sonarr import _client as client
    series = [s for s in await client()._get("/series")
              if s.get("title", "").strip().lower() == title]
    if not series:
        return None
    sid = series[0]["id"]
    files = await client()._get("/episodefile", params={"seriesId": sid})
    if len(files) <= keep:
        return None
    # Newest N *currently downloaded* files stay — recomputed fresh each run.
    ordered = sorted(files, key=lambda f: f.get("dateAdded", ""), reverse=True)
    doomed = ordered[keep:]
    for f in doomed:
        await client()._delete(f"/episodefile/{f['id']}")
    return (f"'{series[0]['title']}': removed {len(doomed)} old episode "
            f"file(s), kept the newest {keep}")


# ── the sweep (scheduler job + on-demand tool) ───────────────────────────────

async def run_sweep() -> str:
    """Execute due quarantine actions and retention rules. Never raises.
    Per-item failures skip that item (unknown state = no action)."""
    lines: list[str] = []

    try:
        due = await store.quarantine_due()
    except Exception:
        logger.exception("cleanup sweep: store unavailable")
        return "cleanup sweep skipped (store unavailable)"

    for item in due:
        try:
            summary = await _execute_action(item)
            await store.quarantine_set_status(item["id"], "done")
            lines.append(f"  • {summary}")
        except Exception:
            # Sonarr/Radarr unreachable or errored: skip, retry next sweep.
            logger.warning("cleanup sweep: skipping %r (service unreachable?)",
                           item["title"], exc_info=True)
            lines.append(f"  ⚠️ skipped '{item['title']}' — service unreachable, "
                         "will retry next sweep")

    try:
        retention_rules = await store.rules_list(kind="retention")
    except Exception:
        retention_rules = []
    for rule in retention_rules:
        try:
            summary = await _apply_retention_rule(rule)
            if summary:
                lines.append(f"  • {summary}")
        except Exception:
            logger.warning("cleanup sweep: retention rule #%s skipped",
                           rule.get("id"), exc_info=True)
            lines.append(f"  ⚠️ retention rule #{rule.get('id')} skipped — "
                         "Sonarr unreachable, will retry next sweep")

    if not lines:
        return "cleanup sweep: nothing due"
    report = "🧹 Cleanup sweep:\n" + "\n".join(lines)
    from src.notify import notify
    await notify("Media Agent: cleanup sweep", report[:2000])
    return report


async def quarantine_summary() -> str:
    """The 'leaving soon' list, with days remaining."""
    import time
    try:
        items = await store.quarantine_list()
    except Exception as e:
        return f"❌ Couldn't read the quarantine ledger: {type(e).__name__}: {e}"
    if not items:
        return "🧹 Nothing is scheduled for cleanup."
    lines = [f"🧹 Leaving soon ({len(items)}):", ""]
    now = time.time()
    for it in items:
        left = max(0, (it["added_at"] + it["grace_days"] * 86400 - now) / 86400)
        lines.append(f"  • {it['title']} [{it['kind']}] — {it['action']} in "
                     f"{left:.1f} day(s) ({it['reason'] or 'manual'})")
    lines.append("")
    lines.append("Say 'keep <title>' to rescue one.")
    return "\n".join(lines)


async def schedule_cleanup(title: str, days: int | None = None,
                           action: str = "delete") -> str:
    """Quarantine one library item by title. Never raises."""
    try:
        days = _grace_days() if days is None else max(0, int(days))
        try:
            found = await _find_in_arr(title)
        except Exception:
            return ("❌ Couldn't check the library (Sonarr/Radarr unreachable) — "
                    "nothing was scheduled. Unknown state = no action.")
        if found is None:
            return f"❌ '{title}' isn't in Sonarr or Radarr."
        existing = await store.quarantine_find(found["title"])
        if existing:
            return f"ℹ️ '{found['title']}' is already scheduled ({existing['action']})."
        await store.quarantine_add(found["kind"], found["arr_id"], found["title"],
                                   action, "manual", days)
        await _emby_leaving_soon(found["title"])
        verb = "removed from monitoring" if action == "unmonitor" else "deleted"
        return (f"🧹 '{found['title']}' will be {verb} in {days} day(s). "
                f"It's in the '{LEAVING_SOON}' list — say 'keep {found['title']}' "
                "to cancel.")
    except Exception as e:
        logger.exception("schedule_cleanup failed")
        return f"❌ Couldn't schedule cleanup: {type(e).__name__}: {e}"


async def reprieve(title: str) -> str:
    """Rescue a quarantined item ('keep X'). Never raises."""
    try:
        item = await store.quarantine_find(title)
        if item is None:
            return f"ℹ️ Nothing matching '{title}' is scheduled for cleanup."
        await store.quarantine_set_status(item["id"], "reprieved")
        return f"✅ Kept '{item['title']}' — removed from the cleanup schedule."
    except Exception as e:
        return f"❌ Couldn't reprieve '{title}': {type(e).__name__}: {e}"


# ── LLM-path tools ───────────────────────────────────────────────────────────

@tool
async def cleanup_status() -> str:
    """Show what's scheduled for cleanup ('leaving soon') and when."""
    return await quarantine_summary()


@tool
async def cleanup_schedule(title: str, days: int = 0, action: str = "delete") -> str:
    """Schedule a show or movie for cleanup after a grace period (default from
    config, usually 7 days). action: 'delete' (remove files + block list
    re-adds) or 'unmonitor' (keep files, stop future downloads). The item can
    be rescued with cleanup_keep until the deadline."""
    return await schedule_cleanup(title, days if days > 0 else None, action)


@tool
async def cleanup_keep(title: str) -> str:
    """Rescue a title from the cleanup schedule (cancel its pending
    delete/unmonitor)."""
    return await reprieve(title)


@tool
async def cleanup_run_now() -> str:
    """Run the cleanup sweep immediately (normally runs daily): executes due
    quarantine actions and retention rules."""
    return await run_sweep()


@tool
async def cleanup_set_retention(series_title: str, keep_last: int) -> str:
    """Keep only the newest N episodes of a show, deleting older episode
    files on each daily sweep (rolling retention for news/daily shows)."""
    try:
        if keep_last < 1:
            return "❌ keep_last must be at least 1."
        rule_id = await store.rule_add(
            "retention", {"series_title": series_title.strip()},
            {"keep_last": int(keep_last)})
        return (f"✅ Retention rule #{rule_id}: keep the newest {keep_last} "
                f"episodes of '{series_title}'. Older files are removed on "
                "the daily sweep (skipped safely if Sonarr is unreachable).")
    except Exception as e:
        return f"❌ Couldn't add the retention rule: {type(e).__name__}: {e}"


@tool
async def cleanup_list_rules() -> str:
    """List stored automation rules (auto-approve + retention) with ids."""
    try:
        from src.engine.rules import describe_rule
        rules = await store.rules_list(enabled_only=False)
        if not rules:
            return "📋 No stored rules."
        return "📋 Stored rules:\n" + "\n".join(
            f"  • {describe_rule(r)}" for r in rules)
    except Exception as e:
        return f"❌ Couldn't list rules: {type(e).__name__}: {e}"


@tool
async def cleanup_remove_rule(rule_id: int) -> str:
    """Delete a stored automation rule by its #id."""
    try:
        if await store.rule_remove(int(rule_id)):
            return f"🗑️ Removed rule #{rule_id}."
        return f"❌ No rule #{rule_id}."
    except Exception as e:
        return f"❌ Couldn't remove rule #{rule_id}: {type(e).__name__}: {e}"
