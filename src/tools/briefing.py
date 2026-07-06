"""One-call status briefing — the "what's new?" tool.

Small local models handle one aggregate call far better than chaining five
lookups, so vague conversational asks ("what's new?", "morning update",
"anything happening?") map to this single tool.
"""
import asyncio

from langchain_core.tools import tool


@tool
async def daily_briefing() -> str:
    """One combined status update: service problems (only if any), active
    downloads, episodes airing today/soon, recently added items, and shows
    to continue. Use for vague asks like "what's new?" or "give me an update"."""
    from src.tools.health import check_all_health, check_queue_status
    from src.tools.sonarr import get_tv_calendar
    from src.tools.emby import emby_recent, emby_next_up

    async def _safe(tool_obj, args=None):
        try:
            return await tool_obj.ainvoke(args or {})
        except Exception as e:
            return f"❌ {type(e).__name__}: {e}"

    health, queues, calendar, recent, next_up = await asyncio.gather(
        _safe(check_all_health),
        _safe(check_queue_status),
        _safe(get_tv_calendar),
        _safe(emby_recent, {"limit": 8}),
        _safe(emby_next_up),
    )

    sections = []
    # Lead with health only when something is actually wrong
    if "❌" in health or "⚠️" in health:
        sections.append(f"⚠️ Service problems:\n{health}")
    sections.append(f"Downloads:\n{queues}")
    sections.append(f"Airing soon:\n{calendar}")
    sections.append(f"Recently added:\n{recent}")
    sections.append(next_up)
    if "❌" not in health and "⚠️" not in health:
        sections.append("✅ All services healthy.")

    return "\n\n".join(sections)
