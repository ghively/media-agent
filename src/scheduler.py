"""APScheduler integration for Media Agent.

Provides a MediaScheduler class with predefined job templates and lifecycle
management. Each scheduled job runs a LangGraph graph (monitoring or curation)
via the agent's conversational graph.

Requires: ``apscheduler>=3.10``
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Type alias for the job callback
JobCallback = Callable[[], Coroutine[Any, Any, str]]


class MediaScheduler:
    """Scheduler for periodic media-agent tasks.

    Usage::

        scheduler = MediaScheduler()
        scheduler.add_job("health_check", my_callback)
        scheduler.start()
        # ...
        scheduler.stop()
    """

    # ── predefined job templates ──────────────────────────────────────────
    # Each entry: (trigger_factory, description)

    JOB_TEMPLATES: dict[str, tuple[Any, str]] = {
        "health_check": (
            lambda: IntervalTrigger(minutes=30),
            "Check service health every 30 minutes",
        ),
        "missing_episodes": (
            lambda: IntervalTrigger(hours=12),
            "Search for missing/wanted episodes every 12 hours",
        ),
        "daily_cleanup": (
            lambda: CronTrigger(hour=3, minute=0),
            "Run daily cleanup tasks at 3:00 AM",
        ),
        "weekly_scan": (
            lambda: CronTrigger(day_of_week="sun", hour=2, minute=0),
            "Full library scan every Sunday at 2:00 AM",
        ),
    }

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}  # name -> apscheduler job_id
        self._callbacks: dict[str, JobCallback] = {}
        self._running = False

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> str:
        """Start the scheduler.  Returns a status message."""
        if self._running:
            return "ℹ️ Scheduler is already running."
        self._scheduler.start()
        self._running = True
        job_count = len(self._jobs)
        return f"▶️ Scheduler started with {job_count} job(s)."

    def stop(self) -> str:
        """Stop the scheduler and remove all jobs.  Returns a status message."""
        if not self._running:
            return "ℹ️ Scheduler is not running."
        self._scheduler.shutdown(wait=False)
        self._running = False
        return "⏹️ Scheduler stopped."

    # ── job management ────────────────────────────────────────────────────

    def add_job(
        self,
        name: str,
        callback: JobCallback | None = None,
        trigger: str = "health_check",
    ) -> str:
        """Add a scheduled job.

        Args:
            name: Unique job name.
            callback: Async callable returning a status string.  If omitted,
                      a no-op callback is registered so the schedule is visible.
            trigger: One of the predefined template keys (``health_check``,
                     ``missing_episodes``, ``daily_cleanup``, ``weekly_scan``)
                     or a cron expression ``"min hour dom mon dow"``.

        Returns:
            A formatted status string.
        """
        if name in self._jobs:
            return f"⚠️ Job '{name}' already exists. Remove it first or use a different name."

        # Resolve trigger
        trigger_obj = self._resolve_trigger(trigger)
        if trigger_obj is None:
            return f"❌ Unknown trigger template: {trigger!r}."

        # Store callback or no-op
        if callback is None:

            async def _noop() -> str:
                logger.info("Job '%s' fired (no callback registered)", name)
                return f"Job '{name}' ran (no-op)"

            self._callbacks[name] = _noop
        else:
            self._callbacks[name] = callback

        # Wrap the coroutine for APScheduler
        async def _wrapper():
            try:
                cb = self._callbacks.get(name)
                if cb:
                    result = await cb()
                    logger.info("Job '%s' completed: %s", name, result)
            except Exception:
                logger.exception("Job '%s' raised an exception", name)

        job = self._scheduler.add_job(_wrapper, trigger_obj, id=name, name=name)
        self._jobs[name] = job.id
        desc = self.JOB_TEMPLATES.get(trigger, (None, f"Custom: {trigger}"))[1]
        return f"✅ Added job '{name}' — {desc}"

    def remove_job(self, name: str) -> str:
        """Remove a scheduled job by name.  Returns a status message."""
        if name not in self._jobs:
            return f"⚠️ Job '{name}' not found."
        try:
            self._scheduler.remove_job(self._jobs[name])
        except Exception as e:
            return f"❌ Failed to remove job '{name}': {e}"
        del self._jobs[name]
        self._callbacks.pop(name, None)
        return f"🗑️ Removed job '{name}'."

    def list_jobs(self) -> str:
        """List all scheduled jobs with their next run time.

        Returns a formatted string.
        """
        jobs = self._scheduler.get_jobs()
        if not jobs:
            return "📋 No scheduled jobs."

        lines = [f"📋 Scheduled jobs ({len(jobs)}):\n"]
        for job in sorted(jobs, key=lambda j: j.name or ""):
            next_run = job.next_run_time
            next_str = next_run.strftime("%Y-%m-%d %H:%M UTC") if next_run else "N/A"
            lines.append(f"  • {job.name}")
            lines.append(f"    Next run: {next_str}")
            lines.append(f"    Trigger:  {_trigger_summary(job.trigger)}")
            lines.append("")
        return "\n".join(lines).rstrip()

    # ── helpers ───────────────────────────────────────────────────────────

    def _resolve_trigger(self, trigger_spec: str) -> Any:
        """Resolve a trigger template name or cron expression."""
        if trigger_spec in self.JOB_TEMPLATES:
            factory, _ = self.JOB_TEMPLATES[trigger_spec]
            return factory()
        # Try parsing as cron expression "min hour dom mon dow"
        parts = trigger_spec.strip().split()
        if len(parts) == 5:
            try:
                return CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )
            except (ValueError, TypeError):
                pass
        return None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def job_count(self) -> int:
        return len(self._jobs)


# ── helpers ────────────────────────────────────────────────────────────────


def _trigger_summary(trigger: Any) -> str:
    """Human-readable trigger description."""
    if hasattr(trigger, "fields"):
        # CronTrigger
        try:
            return trigger.__str__()
        except Exception:
            return repr(trigger)
    if hasattr(trigger, "interval"):
        # IntervalTrigger
        try:
            return trigger.__str__()
        except Exception:
            return repr(trigger)
    return repr(trigger)