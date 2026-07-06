"""Scheduled job implementations, wired into MediaScheduler by main.py.

Enable in settings.yaml:

    scheduler:
      enabled: true
      jobs:
        - {name: health, trigger: health_check}        # every 30 min
        - {name: missing, trigger: missing_episodes}   # every 12 h
        - {name: digest, trigger: weekly_scan}         # Sunday 02:00

Job callbacks return a status string (logged); health problems and the
weekly digest are pushed via src.notify when Telegram is configured.
"""
import logging

logger = logging.getLogger(__name__)

# Remember the last health state so we only notify on transitions,
# not every 30 minutes while a service stays down.
_last_health_bad = False


async def health_check_job() -> str:
    """Check all services; notify (once) when something goes unhealthy and
    again when it recovers."""
    global _last_health_bad
    from src.tools.health import check_all_health
    from src import notify

    report = await check_all_health.ainvoke({})
    bad = "❌" in report or "⚠️" in report
    if bad and not _last_health_bad:
        await notify.send(f"⚠️ Media Agent health alert:\n{report}")
    elif not bad and _last_health_bad:
        await notify.send("✅ Media Agent: all services healthy again.")
    _last_health_bad = bad
    return report


async def missing_search_job() -> str:
    """Kick Sonarr and Radarr searches for missing/wanted items."""
    from src.tools.sonarr import search_missing_episodes
    from src.tools.radarr import search_missing_movies

    tv = await search_missing_episodes.ainvoke({})
    movies = await search_missing_movies.ainvoke({})
    return f"{tv}\n{movies}"


async def weekly_digest_job() -> str:
    """One summary: health, queues, disk, recent additions — pushed to
    Telegram when configured."""
    from src.tools.health import check_all_health, check_disk_space, check_queue_status
    from src.tools.emby import emby_recent
    from src import notify

    sections = []
    for title, tool, args in (
        ("Health", check_all_health, {}),
        ("Queues", check_queue_status, {}),
        ("Disk", check_disk_space, {}),
        ("Recently added", emby_recent, {"limit": 10}),
    ):
        try:
            sections.append(f"— {title} —\n{await tool.ainvoke(args)}")
        except Exception as e:
            sections.append(f"— {title} —\n❌ {type(e).__name__}: {e}")

    digest = "📺 Media Agent weekly digest\n\n" + "\n\n".join(sections)
    await notify.send(digest)
    return digest


# name → callback, referenced from settings.yaml scheduler.jobs entries
JOB_CALLBACKS = {
    "health": health_check_job,
    "missing": missing_search_job,
    "digest": weekly_digest_job,
}


def register_configured_jobs(scheduler) -> int:
    """Add jobs listed in settings.yaml to *scheduler*. Returns the count."""
    from src.config import get_settings

    entries = get_settings().scheduler.get("jobs", []) or []
    count = 0
    for entry in entries:
        name = (entry or {}).get("name", "")
        trigger = (entry or {}).get("trigger", "health_check")
        callback = JOB_CALLBACKS.get(name)
        if callback is None:
            logger.warning("Unknown scheduler job name %r — valid: %s",
                           name, ", ".join(JOB_CALLBACKS))
            continue
        result = scheduler.add_job(name, callback, trigger=trigger)
        logger.info(result)
        count += 1
    return count
