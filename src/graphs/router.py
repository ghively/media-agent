"""Deterministic domain router.

Routes each user message to a domain-specific toolset with plain keyword
scoring — no LLM call, no tokens. Binding only the relevant 4–13 tools
(instead of all ~60) keeps the schema overhead small and makes tool
selection far more reliable for small local models.

Ambiguous or generic requests fall through to the 'core' domain, whose
workflow tools (grab_media, system_report, ...) handle cross-domain asks.
"""
import re

CORE = "core"

# Order matters only for stable tie-breaking in tests; ties route to CORE.
DOMAIN_KEYWORDS: dict[str, set[str]] = {
    "tv": {
        "tv", "show", "shows", "series", "episode", "episodes", "season",
        "seasons", "sonarr", "airing", "calendar",
    },
    "movies": {
        "movie", "movies", "film", "films", "radarr",
    },
    "library": {
        "library", "rename", "renames", "naming", "organize", "organise",
        "duplicate", "duplicates", "inventory", "cleanup", "undo",
        "emby", "libraries",
    },
    "downloads": {
        "sabnzbd", "nzb", "usenet", "torrent", "torrents", "magnet",
        "seeding", "queue", "queues", "paused", "unpause",
    },
    "audio": {
        "music", "album", "albums", "bandcamp", "audiobook", "audiobooks",
        "audible", "track", "tracks", "asin",
    },
    "youtube": {
        "youtube", "channel", "channels", "subscription", "subscriptions",
        "video", "videos", "upload", "uploads", "subscribe", "unsubscribe",
    },
    "roms": {
        "rom", "roms", "game", "games", "emulator", "nes", "snes", "n64",
        "gba", "genesis", "psx", "no-intro", "redump", "dat",
    },
    "system": {
        "health", "status", "disk", "space", "storage", "system", "report",
        "healthy", "unreachable",
    },
}


def route(text: str) -> str:
    """Pick the domain whose keywords best match *text*.

    Deterministic: unique highest keyword-hit count wins; zero hits or a
    tie routes to CORE (whose workflow tools cover cross-domain requests).
    """
    words = set(re.findall(r"[a-z0-9@#-]+", text.lower()))
    if not words:
        return CORE

    scores = {
        domain: len(words & keywords)
        for domain, keywords in DOMAIN_KEYWORDS.items()
    }
    best = max(scores.values())
    if best == 0:
        return CORE
    winners = [d for d, s in scores.items() if s == best]
    return winners[0] if len(winners) == 1 else CORE
