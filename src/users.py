"""User roles and request quotas, keyed by conversation thread.

The seerr-lineage pattern (granular permissions + rolling request limits)
scaled down to a homelab: roles live in config, not a user database.

- ``users.admins`` — list of Telegram chat ids with full control. **Empty
  list = the role system is OFF** and every interface behaves exactly as
  before (single-owner deployment). That keeps this feature opt-in and
  backward compatible.
- Local interfaces (CLI, dashboard, API) are always admin — they run on the
  owner's machines; the role system only distinguishes Telegram chats.
- ``users.request_limit`` — rolling-window quota for non-admins:
  ``{count: 5, days: 7}``. Per-chat overrides in ``users.overrides``.
- ``users.names`` — optional chat-id → friendly-name map, used by
  auto-approve rules ("from alice") and shown in request lists.

Thread ids encode identity: the Telegram interface uses ``tg-<chat_id>``.
"""
from src.config import get_settings

DEFAULT_LIMIT_COUNT = 5
DEFAULT_LIMIT_DAYS = 7


def _users_cfg() -> dict:
    try:
        return get_settings().users
    except Exception:
        return {}


def roles_enabled() -> bool:
    """The role system is on only when at least one admin is configured."""
    return bool(_users_cfg().get("admins"))


def telegram_chat_id(thread_id: str) -> str | None:
    """Extract the Telegram chat id from a thread id, or None."""
    if thread_id and thread_id.startswith("tg-"):
        return thread_id[3:]
    return None


def is_admin(thread_id: str) -> bool:
    """Everything is admin until roles are enabled; then only listed
    Telegram chats (plus all local interfaces) are."""
    if not roles_enabled():
        return True
    chat_id = telegram_chat_id(thread_id)
    if chat_id is None:
        return True  # CLI / dashboard / API are owner-local
    admins = {str(a) for a in _users_cfg().get("admins", [])}
    return chat_id in admins


def display_name(requester: str) -> str:
    """Friendly name for a requester (a chat id), falling back to the id."""
    names = _users_cfg().get("names") or {}
    return str(names.get(str(requester), requester))


def chat_id_for_name(name: str) -> str | None:
    """Reverse lookup: friendly name → chat id (case-insensitive)."""
    names = _users_cfg().get("names") or {}
    lowered = name.strip().lower()
    for cid, n in names.items():
        if str(n).lower() == lowered:
            return str(cid)
    return None


def request_limit_for(requester: str) -> tuple[int, int]:
    """(count, days) rolling-window quota for this requester.

    count == 0 means unlimited.
    """
    cfg = _users_cfg()
    limit = cfg.get("request_limit") or {}
    count = int(limit.get("count", DEFAULT_LIMIT_COUNT))
    days = int(limit.get("days", DEFAULT_LIMIT_DAYS))
    overrides = (cfg.get("overrides") or {}).get(str(requester)) or {}
    count = int(overrides.get("count", count))
    days = int(overrides.get("days", days))
    return count, max(1, days)


def admin_chat_ids() -> list[str]:
    return [str(a) for a in _users_cfg().get("admins", [])]
