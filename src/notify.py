"""Best-effort webhook notifications.

The scheduler's findings (health problems, the daily report) are useless if
they only reach the container log. When ``notifications.url`` is configured,
:func:`notify` pushes them to a webhook; three payload shapes are supported
via ``notifications.kind``:

- ``ntfy``     — POST plain text to an ntfy topic URL (``Title`` header)
- ``discord``  — POST ``{"content": ...}`` to a Discord webhook
- ``generic``  — POST ``{"title": ..., "message": ...}`` JSON
- ``telegram`` — send via the Telegram Bot API; uses ``notifications.chat_id``
  plus ``notifications.bot_token`` (falls back to ``telegram.bot_token``),
  no ``url`` needed

Always best-effort: failures are logged and swallowed so a dead webhook can
never break a scheduled job or a tool.
"""
import logging

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)


async def notify(title: str, message: str) -> bool:
    """Send a notification. Returns True when delivered, False otherwise."""
    try:
        cfg = get_settings().notifications
    except Exception:
        return False
    kind = (cfg.get("kind") or "ntfy").lower()
    url = cfg.get("url", "")

    if kind == "telegram":
        token = cfg.get("bot_token") or get_settings().telegram.get("bot_token", "")
        chat_id = cfg.get("chat_id", "")
        if not token or not chat_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id,
                          "text": f"{title}\n\n{message}"[:4000]})
                resp.raise_for_status()
            return True
        except Exception:
            logger.warning("telegram notification failed", exc_info=True)
            return False

    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if kind == "discord":
                resp = await client.post(
                    url, json={"content": f"**{title}**\n{message}"[:1900]})
            elif kind == "generic":
                resp = await client.post(
                    url, json={"title": title, "message": message})
            else:  # ntfy
                resp = await client.post(
                    url, content=message.encode("utf-8"),
                    headers={"Title": title})
            resp.raise_for_status()
        return True
    except Exception:
        logger.warning("notification delivery failed (kind=%s)", kind, exc_info=True)
        return False
