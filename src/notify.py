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

The request/approval loop also needs *per-user* pushes ("your request is
ready") and *admin* pushes ("approval needed"): :func:`notify_chat` sends to
one Telegram chat id, :func:`notify_admins` fans out to every configured
admin chat (plus the general channel).

Always best-effort: failures are logged and swallowed so a dead webhook can
never break a scheduled job or a tool.
"""
import logging

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)


def _telegram_token() -> str:
    try:
        cfg = get_settings().notifications
        return cfg.get("bot_token") or get_settings().telegram.get("bot_token", "")
    except Exception:
        return ""


async def _send_telegram(chat_id: str, text: str) -> bool:
    token = _telegram_token()
    if not token or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4000]})
            resp.raise_for_status()
        return True
    except Exception:
        logger.warning("telegram notification failed", exc_info=True)
        return False


async def notify(title: str, message: str) -> bool:
    """Send a notification to the configured channel.
    Returns True when delivered, False otherwise."""
    try:
        cfg = get_settings().notifications
    except Exception:
        return False
    kind = (cfg.get("kind") or "ntfy").lower()
    url = cfg.get("url", "")

    if kind == "telegram":
        return await _send_telegram(cfg.get("chat_id", ""), f"{title}\n\n{message}")

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


async def notify_chat(chat_id: str, title: str, message: str) -> bool:
    """Push to ONE Telegram chat (a requester's phone). Best-effort; needs a
    bot token (telegram.bot_token or notifications.bot_token)."""
    return await _send_telegram(str(chat_id), f"{title}\n\n{message}")


async def notify_admins(title: str, message: str) -> bool:
    """Push to the general channel plus every configured admin chat.
    True when at least one delivery succeeded."""
    delivered = await notify(title, message)
    try:
        from src.users import admin_chat_ids
        admins = admin_chat_ids()
    except Exception:
        admins = []
    try:
        general = str(get_settings().notifications.get("chat_id", ""))
    except Exception:
        general = ""
    for chat_id in admins:
        if chat_id == general:
            continue  # already reached via notify() when kind=telegram
        if await _send_telegram(chat_id, f"{title}\n\n{message}"):
            delivered = True
    return delivered
