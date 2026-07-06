"""Outbound notifications (Telegram Bot API).

One-way push via plain HTTPS — no bot framework needed. Configure in
settings.yaml / .env:

    notifications:
      telegram_bot_token: "${TELEGRAM_BOT_TOKEN:-}"
      telegram_chat_id: "${TELEGRAM_CHAT_ID:-}"

Used by scheduler jobs (health alerts, weekly digest). Two-way approval
replies from the phone are a future step — see docs/AGENT.md roadmap.
"""
import logging

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_MAX_MESSAGE = 4000  # Telegram hard limit is 4096


def _config() -> dict:
    from src.config import get_settings
    return get_settings()._data.get("notifications", {}) or {}


def telegram_configured() -> bool:
    cfg = _config()
    return bool(cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"))


async def telegram_check() -> tuple[bool, str]:
    """Validate the bot token (used by the config doctor)."""
    cfg = _config()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_TELEGRAM_API}/bot{cfg['telegram_bot_token']}/getMe"
        )
        data = resp.json()
    if data.get("ok"):
        return True, f"bot @{data['result'].get('username', '?')} OK"
    return False, f"token rejected: {data.get('description', resp.status_code)}"


async def send(text: str) -> bool:
    """Send a notification. Returns False (and logs) on any failure —
    notifications must never crash a job."""
    if not telegram_configured():
        return False
    cfg = _config()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_TELEGRAM_API}/bot{cfg['telegram_bot_token']}/sendMessage",
                json={"chat_id": cfg["telegram_chat_id"], "text": text[:_MAX_MESSAGE]},
            )
            data = resp.json()
        if not data.get("ok"):
            logger.warning("Telegram send failed: %s", data)
            return False
        return True
    except Exception as e:
        logger.warning("Telegram send failed: %s: %s", type(e).__name__, e)
        return False
