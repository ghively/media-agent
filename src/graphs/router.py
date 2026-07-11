"""Deterministic intent router — the fast path in front of the LLM agent.

Common natural-language commands ("what's downloading?", "check health",
"search for Andor", "add Breaking Bad", "download snes roms", "list my
audiobooks", "check youtube subscriptions") are recognized with regex
patterns and answered by calling the underlying tools directly — no LLM
round-trip. Anything the router doesn't confidently recognize falls through
to the LangGraph ReAct agent (``try_route`` returns ``None``).

Covered domains: Sonarr/Radarr (TV & movies), Emby, health/disk/queues,
SABnzbd, Download Station, ROMs & emulation platforms (Internet Archive),
YouTube (downloads + channel subscriptions), Audible audiobooks, Bandcamp,
and library maintenance (inventory/duplicates/naming).

Design rules (hardening):
- The router NEVER raises. A crash in any handler is logged and the message
  falls through to the LLM agent, so the user always gets an answer.
- Patterns are conservative: only fire on high-confidence matches. Ambiguous
  or conversational messages go to the LLM.
- Normalization preserves case — URLs, ASINs, file paths, and channel names
  are case-sensitive payloads. All patterns match case-insensitively.
- Anything that adds, downloads in bulk, or renames files requires
  confirmation first (numbered results or yes/no), mirroring the agent's
  confirmation rule. Pending confirmations are per-thread, expire after
  PENDING_TTL_SECONDS, and the table is bounded.
- Tool modules are imported lazily inside handlers so optional integrations
  (SABnzbd, Download Station, YouTube) degrade gracefully and the router
  stays cheap to import.
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── pending confirmation state ───────────────────────────────────────────────

PENDING_TTL_SECONDS = 15 * 60
MAX_PENDING_THREADS = 100
MAX_RESULTS_SHOWN = 5


@dataclass
class PendingSelection:
    """A confirmation waiting on one thread.

    kind="media": numbered Sonarr/Radarr results ("yes" / "add #2").
    kind="rom":   numbered Internet Archive ROM sets (same picks).
    kind="action": a single yes/no action (bulk download, file rename).
    """
    results: list[dict] = field(default_factory=list)
    auto_add: bool = False
    kind: str = "media"
    action: object = None          # async zero-arg callable for kind="action"
    created: float = field(default_factory=time.monotonic)

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.created > PENDING_TTL_SECONDS


_pending: dict[str, PendingSelection] = {}


def _sweep_pending() -> None:
    """Drop expired entries; bound the table size."""
    for tid in [t for t, p in _pending.items() if p.expired]:
        _pending.pop(tid, None)
    while len(_pending) > MAX_PENDING_THREADS:
        oldest = min(_pending, key=lambda t: _pending[t].created)
        _pending.pop(oldest, None)


def _set_pending(thread_id: str, pending: PendingSelection) -> None:
    _sweep_pending()
    _pending[thread_id] = pending


def clear_pending(thread_id: str) -> None:
    _pending.pop(thread_id, None)


# ── text normalization ──────────────────────────────────────────────────────

_PUNCT_RE = re.compile(r"[?!.]+$")
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Collapse whitespace and strip trailing punctuation. Case is preserved
    (URLs, ASINs, paths, and channel names are case-sensitive); all patterns
    compile with re.IGNORECASE instead."""
    text = text.strip().replace("’", "'")
    text = _PUNCT_RE.sub("", text).strip()
    return _WS_RE.sub(" ", text)


# ── media-type extraction for search/add queries ────────────────────────────

_TV_WORDS = re.compile(
    r"\b(?:the\s+)?(?:tv\s+show|tv\s+series|show|series|tv)\b", re.IGNORECASE)
_MOVIE_WORDS = re.compile(r"\b(?:the\s+)?(?:movie|film)\b", re.IGNORECASE)
_FILLER_RE = re.compile(r"\b(?:called|named|titled)\b", re.IGNORECASE)


def _extract_media_query(raw: str) -> tuple[str, str | None]:
    """Pull an optional media-type hint out of a search/add phrase.

    "the movie Dune"        → ("Dune", "movie")
    "tv show Severance"     → ("Severance", "tv")
    "Breaking Bad"          → ("Breaking Bad", None)
    """
    media_type = None
    query = raw
    if _MOVIE_WORDS.search(query):
        media_type = "movie"
        query = _MOVIE_WORDS.sub(" ", query)
    elif _TV_WORDS.search(query):
        media_type = "tv"
        query = _TV_WORDS.sub(" ", query)
    query = _FILLER_RE.sub(" ", query)
    query = _WS_RE.sub(" ", query).strip(" \"'")
    return query, media_type


# ── ROM platform extraction ──────────────────────────────────────────────────
# Aliases map to the platform slugs rom.py's tools expect (nes, snes, ...).
# Multi-word aliases are checked first so "super nintendo" beats "nintendo".

_PLATFORM_ALIASES: list[tuple[str, str]] = [
    ("super nintendo", "snes"), ("super famicom", "snes"),
    ("nintendo 64", "n64"), ("nintendo ds", "nds"), ("nintendo entertainment system", "nes"),
    ("game boy advance", "gba"), ("gameboy advance", "gba"),
    ("game boy color", "gbc"), ("gameboy color", "gbc"),
    ("game boy", "gb"), ("gameboy", "gb"),
    ("mega drive", "genesis"), ("megadrive", "genesis"), ("sega genesis", "genesis"),
    ("sega cd", "segacd"), ("sega saturn", "saturn"),
    ("playstation 2", "ps2"), ("playstation 1", "psx"), ("playstation", "psx"),
    ("pc engine", "pce"), ("turbografx", "pce"),
    ("atari 2600", "atari2600"),
    ("famicom", "nes"),
    ("nes", "nes"), ("snes", "snes"), ("n64", "n64"), ("nds", "nds"),
    ("3ds", "3ds"), ("gba", "gba"), ("gbc", "gbc"), ("gb", "gb"),
    ("genesis", "genesis"), ("dreamcast", "dreamcast"), ("saturn", "saturn"),
    ("psx", "psx"), ("ps1", "psx"), ("ps2", "ps2"), ("psp", "psp"),
    ("gamecube", "gamecube"), ("wii", "wii"), ("pce", "pce"),
]


def _extract_platform(text: str) -> tuple[str, str]:
    """Return (platform_slug, text with the platform words removed)."""
    for alias, slug in _PLATFORM_ALIASES:
        pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
        if pattern.search(text):
            remainder = _WS_RE.sub(" ", pattern.sub(" ", text)).strip(" \"'")
            return slug, remainder
    return "", text.strip(" \"'")


_KNOWN_PLATFORMS = sorted({slug for _, slug in _PLATFORM_ALIASES})


# ── URL detection ────────────────────────────────────────────────────────────

_YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/\S+",
    re.IGNORECASE)
_BANDCAMP_URL_RE = re.compile(r"(?:https?://)?[\w.-]+\.bandcamp\.com/\S+", re.IGNORECASE)
_MAGNET_RE = re.compile(r"magnet:\?\S+", re.IGNORECASE)
_TORRENT_URL_RE = re.compile(r"https?://\S+\.torrent(?:\?\S*)?", re.IGNORECASE)
_NZB_URL_RE = re.compile(r"https?://\S+\.nzb(?:\?\S*)?", re.IGNORECASE)
_ANY_URL_RE = re.compile(r"(?:https?://|magnet:\?|www\.)\S+", re.IGNORECASE)


def _ensure_scheme(url: str) -> str:
    if url.lower().startswith(("http://", "https://", "magnet:")):
        return url
    return f"https://{url}"


def _youtube_content_type(lower_text: str) -> str:
    if re.search(r"\b(?:music|song|audio|mp3)\b", lower_text):
        return "music"
    if "podcast" in lower_text:
        return "podcast"
    if "concert" in lower_text:
        return "concert"
    return "video"


# ── unified structured search (reuses hardened searchers) ───────────────────

async def _structured_search(query: str, media_type: str | None) -> list[dict]:
    """Search Sonarr/Radarr concurrently; return ranked result dicts."""
    from src.tools.search import _search_radarr, _search_sonarr

    searches = []
    if media_type in (None, "tv"):
        searches.append(_search_sonarr(query, MAX_RESULTS_SHOWN))
    if media_type in (None, "movie"):
        searches.append(_search_radarr(query, MAX_RESULTS_SHOWN))

    results_lists = await asyncio.gather(*searches, return_exceptions=True)
    results: list[dict] = []
    for rl in results_lists:
        if isinstance(rl, list):
            results.extend(rl)
    results.sort(key=lambda r: (-r.get("relevance", 0), str(r.get("title", ""))))

    # Dedup by (title, source)
    seen: set = set()
    unique: list[dict] = []
    for r in results:
        key = (str(r.get("title", "")).lower(), r.get("source"))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique[:MAX_RESULTS_SHOWN]


async def _rom_search_structured(query: str, platform: str) -> list[dict]:
    """Search Internet Archive for ROM sets; return result dicts."""
    from src.providers.rom import _search_archive_sync

    raw = await asyncio.to_thread(_search_archive_sync, query, platform)
    results = []
    for r in raw[:MAX_RESULTS_SHOWN]:
        size = r.get("item_size") or 0
        size_gb = size / 1024 / 1024 / 1024 if size else 0
        results.append({
            "title": r.get("title", "Unknown"),
            "year": "",
            "source": "archive",
            "source_type": "rom",
            "id": r.get("identifier"),
            "overview": f"{size_gb:.1f} GB" if size_gb else "size unknown",
            "relevance": 0,
            "platform": platform,
        })
    return results


_TYPE_LABELS = {"tv": "TV show", "movie": "movie", "rom": "ROM set"}


def _format_results(results: list[dict], query: str, auto_add: bool) -> str:
    lines = [f"Found {len(results)} match(es) for '{query}':", ""]
    for i, r in enumerate(results, 1):
        year = f" ({r['year']})" if r.get("year") else ""
        label = _TYPE_LABELS.get(r.get("source_type"), r.get("source_type", ""))
        lines.append(f"  {i}. {r['title']}{year} — {label}")
        if r.get("overview"):
            lines.append(f"     {r['overview'][:110]}")
    lines.append("")
    if auto_add:
        lines.append("Want me to grab one? Say 'yes' for #1, or 'add #2' / 'the second one'.")
    else:
        lines.append("Say 'add #1' (or 'the first one') if you want me to grab one of these.")
    return "\n".join(lines)


async def _add_result(result: dict) -> str:
    """Execute the selected search result (Sonarr, Radarr, or ROM download)."""
    title = str(result.get("title", "Unknown"))
    source_id = result.get("id")
    source_type = result.get("source_type")
    if source_id is None:
        return f"❌ Can't grab '{title}' — the search result has no usable ID."
    if source_type == "movie":
        from src.tools.radarr import add_movie
        return await add_movie.ainvoke({"tmdb_id": int(source_id), "title": title})
    if source_type == "rom":
        from src.providers.rom import rom_download
        return await rom_download.ainvoke({
            "identifier": str(source_id),
            "platform": result.get("platform", ""),
        })
    from src.tools.sonarr import add_tv_show
    return await add_tv_show.ainvoke({"tvdb_id": int(source_id), "title": title})


def _confirm_action(thread_id: str, prompt: str, action) -> str:
    """Store a yes/no pending action and return the confirmation question."""
    _set_pending(thread_id, PendingSelection(kind="action", action=action, auto_add=True))
    return prompt


# ── pending-selection resolution ─────────────────────────────────────────────

_YES_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|confirm|do it|go ahead|go for it|"
    r"add it|grab it|get it|download it|that's the one|thats the one|correct|right one)$",
    re.IGNORECASE)
_NO_RE = re.compile(
    r"^(?:no|nope|nah|cancel|stop|never ?mind|nevermind|don't|dont|wrong one|none of (?:those|them))$",
    re.IGNORECASE)
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
}
_PICK_RE = re.compile(
    r"^(?:add |grab |get |download |use |pick |choose |go with )?"
    r"(?:the )?"
    r"(?:number |option |result |#)?"
    r"(?P<sel>\d+|first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)"
    r"(?: one)?$",
    re.IGNORECASE)


def _parse_selection(text: str, count: int) -> int | None:
    """Return a 0-based index into pending results, or None if not a pick."""
    m = _PICK_RE.match(text)
    if not m:
        return None
    sel = m.group("sel").lower()
    if sel == "last":
        return count - 1
    idx = _ORDINALS.get(sel)
    if idx is None:
        try:
            idx = int(sel)
        except ValueError:
            return None
    if 1 <= idx <= count:
        return idx - 1
    return None


async def _resolve_pending(text: str, thread_id: str) -> str | None:
    """Handle yes/no/pick replies when a confirmation is pending on this thread."""
    pending = _pending.get(thread_id)
    if pending is None:
        return None
    if pending.expired:
        _pending.pop(thread_id, None)
        return None

    if _NO_RE.match(text):
        _pending.pop(thread_id, None)
        return "Okay, cancelled — nothing was done."

    if pending.kind == "action":
        if _YES_RE.match(text):
            _pending.pop(thread_id, None)
            return await pending.action()
        # Not a yes/no — let other intents or the LLM handle it.
        return None

    if _YES_RE.match(text):
        if pending.auto_add:
            _pending.pop(thread_id, None)
            return await _add_result(pending.results[0])
        return ("Which one? Say 'the first one' or 'add #2' "
                "and I'll grab it.")

    idx = _parse_selection(text, len(pending.results))
    if idx is not None:
        _pending.pop(thread_id, None)
        return await _add_result(pending.results[idx])

    # Not a confirmation/selection — let the LLM (or other intents) handle it,
    # but keep the pending state alive in case they come back to it.
    return None


# ── URL intents (checked before the pattern table) ───────────────────────────

async def _try_url_intents(text: str, thread_id: str) -> str | None:
    """Handle messages containing a recognizable media URL."""
    if not _ANY_URL_RE.search(text):
        return None
    lower = text.lower()
    wants_download = bool(re.search(
        r"\b(?:download|grab|get|save|add|queue|fetch)\b", lower))
    wants_subscribe = bool(re.search(
        r"\b(?:subscribe|follow|monitor|watch for)\b", lower))
    wants_info = bool(re.search(
        r"\b(?:info|about|what is|what's|details|tell me)\b", lower))

    yt = _YOUTUBE_URL_RE.search(text)
    if yt:
        url = _ensure_scheme(yt.group(0))
        try:
            from src.providers.youtube import (
                youtube_add_subscription, youtube_download, youtube_get_info,
            )
        except ImportError:
            return "❌ YouTube support isn't installed (yt-dlp missing)."
        if wants_subscribe:
            ctype = _youtube_content_type(lower)
            args = {"url": url}
            if ctype != "video":
                args["content_type"] = ctype
            return await youtube_add_subscription.ainvoke(args)
        if wants_download:
            return await youtube_download.ainvoke(
                {"url": url, "content_type": _youtube_content_type(lower)})
        if wants_info:
            return await youtube_get_info.ainvoke({"url": url})
        # Bare link: show info and offer to download it.
        info = await youtube_get_info.ainvoke({"url": url})
        ctype = _youtube_content_type(lower)

        async def _do_download():
            return await youtube_download.ainvoke({"url": url, "content_type": ctype})

        _set_pending(thread_id, PendingSelection(kind="action", action=_do_download))
        return f"{info}\n\nWant me to download it? (yes/no)"

    bc = _BANDCAMP_URL_RE.search(text)
    if bc:
        url = _ensure_scheme(bc.group(0))
        from src.providers.bandcamp import bandcamp_download
        if wants_download:
            return await bandcamp_download.ainvoke({"url": url})

        async def _do_bandcamp():
            return await bandcamp_download.ainvoke({"url": url})

        return _confirm_action(
            thread_id,
            "That's a Bandcamp link — want me to download the album with "
            "full metadata and artwork? (yes/no)",
            _do_bandcamp,
        )

    magnet = _MAGNET_RE.search(text)
    torrent = _TORRENT_URL_RE.search(text)
    if magnet or torrent:
        url = (magnet or torrent).group(0)
        try:
            from src.tools.download_station import download_station_add
        except ImportError:
            return "❌ Download Station support isn't installed."
        if wants_download:
            return await download_station_add.ainvoke({"url": url})

        async def _do_torrent():
            return await download_station_add.ainvoke({"url": url})

        return _confirm_action(
            thread_id,
            "That looks like a torrent — add it to Download Station? (yes/no)",
            _do_torrent,
        )

    nzb = _NZB_URL_RE.search(text)
    if nzb:
        url = nzb.group(0)
        try:
            from src.tools.sabnzbd import sabnzbd_add_nzb
        except ImportError:
            return "❌ SABnzbd support isn't installed."
        category = "tv" if re.search(r"\b(?:tv|show|episode|series)\b", lower) else "movies"
        if wants_download:
            return await sabnzbd_add_nzb.ainvoke({"nzb_url": url, "category": category})

        async def _do_nzb():
            return await sabnzbd_add_nzb.ainvoke({"nzb_url": url, "category": category})

        return _confirm_action(
            thread_id,
            f"That's an NZB — queue it in SABnzbd under '{category}'? (yes/no)",
            _do_nzb,
        )

    # Some other URL — the LLM can decide what to do with it.
    return None


# ── intent handlers ──────────────────────────────────────────────────────────
# Every handler: async (match, thread_id) -> str | None. Tool errors come back
# as "❌ ..." strings from the tools themselves; that's fine to show the user.
# Returning None (after a match) falls through to the LLM.

async def _h_queue(match, thread_id):
    from src.tools.health import check_queue_status
    return await check_queue_status.ainvoke({})


async def _h_health(match, thread_id):
    from src.tools.health import check_all_health
    return await check_all_health.ainvoke({})


async def _h_disk(match, thread_id):
    from src.tools.health import check_disk_space
    return await check_disk_space.ainvoke({})


async def _h_list_tv(match, thread_id):
    from src.tools.sonarr import list_tv_shows
    return await list_tv_shows.ainvoke({})


async def _h_list_movies(match, thread_id):
    from src.tools.radarr import list_movies
    return await list_movies.ainvoke({})


async def _h_recent(match, thread_id):
    from src.tools.emby import emby_recent
    return await emby_recent.ainvoke({})


async def _h_calendar(match, thread_id):
    from src.tools.sonarr import get_tv_calendar
    return await get_tv_calendar.ainvoke({})


async def _h_missing_tv(match, thread_id):
    from src.tools.sonarr import search_missing_episodes
    return await search_missing_episodes.ainvoke({})


async def _h_missing_movies(match, thread_id):
    from src.tools.radarr import search_missing_movies
    return await search_missing_movies.ainvoke({})


async def _h_missing_all(match, thread_id):
    from src.tools.radarr import search_missing_movies
    from src.tools.sonarr import search_missing_episodes
    tv, movies = await asyncio.gather(
        search_missing_episodes.ainvoke({}),
        search_missing_movies.ainvoke({}),
        return_exceptions=True,
    )
    parts = [p for p in (tv, movies) if isinstance(p, str)]
    return "\n".join(parts) if parts else "❌ Missing-media search failed."


async def _h_scan(match, thread_id):
    from src.tools.emby import emby_scan
    return await emby_scan.ainvoke({})


async def _h_history(match, thread_id):
    from src.tools.radarr import get_movie_history
    from src.tools.sonarr import get_tv_history
    tv, movies = await asyncio.gather(
        get_tv_history.ainvoke({}),
        get_movie_history.ainvoke({}),
        return_exceptions=True,
    )
    parts = []
    if isinstance(tv, str):
        parts.append("TV:\n" + tv)
    if isinstance(movies, str):
        parts.append("Movies:\n" + movies)
    return "\n\n".join(parts) if parts else "❌ Couldn't fetch history."


async def _h_torrents(match, thread_id):
    try:
        from src.tools.download_station import download_station_list
    except ImportError:
        return "❌ Download Station support isn't installed."
    return await download_station_list.ainvoke({})


async def _h_ds_stats(match, thread_id):
    try:
        from src.tools.download_station import download_station_stats
    except ImportError:
        return "❌ Download Station support isn't installed."
    return await download_station_stats.ainvoke({})


async def _h_pause_downloads(match, thread_id):
    try:
        from src.tools.sabnzbd import sabnzbd_pause
    except ImportError:
        return "❌ SABnzbd support isn't installed."
    return await sabnzbd_pause.ainvoke({})


async def _h_resume_downloads(match, thread_id):
    try:
        from src.tools.sabnzbd import sabnzbd_resume
    except ImportError:
        return "❌ SABnzbd support isn't installed."
    return await sabnzbd_resume.ainvoke({})


async def _h_sab_status(match, thread_id):
    try:
        from src.tools.sabnzbd import sabnzbd_status
    except ImportError:
        return "❌ SABnzbd support isn't installed."
    return await sabnzbd_status.ainvoke({})


async def _h_sab_queue(match, thread_id):
    try:
        from src.tools.sabnzbd import sabnzbd_queue
    except ImportError:
        return "❌ SABnzbd support isn't installed."
    return await sabnzbd_queue.ainvoke({})


async def _h_tv_queue(match, thread_id):
    from src.tools.sonarr import get_tv_queue
    return await get_tv_queue.ainvoke({})


async def _h_movie_queue(match, thread_id):
    from src.tools.radarr import get_movie_queue
    return await get_movie_queue.ainvoke({})


async def _h_quality_profiles(match, thread_id):
    scope = (match.groupdict().get("scope") or "").lower()
    from src.tools.radarr import radarr_list_quality_profiles
    from src.tools.sonarr import sonarr_list_quality_profiles
    if scope in ("sonarr", "tv"):
        return await sonarr_list_quality_profiles.ainvoke({})
    if scope in ("radarr", "movie", "movies"):
        return await radarr_list_quality_profiles.ainvoke({})
    tv, movies = await asyncio.gather(
        sonarr_list_quality_profiles.ainvoke({}),
        radarr_list_quality_profiles.ainvoke({}),
        return_exceptions=True,
    )
    parts = []
    if isinstance(tv, str):
        parts.append("Sonarr (TV):\n" + tv)
    if isinstance(movies, str):
        parts.append("Radarr (movies):\n" + movies)
    return "\n\n".join(parts) if parts else "❌ Couldn't fetch quality profiles."


async def _h_root_folders(match, thread_id):
    scope = (match.groupdict().get("scope") or "").lower()
    from src.tools.radarr import radarr_list_root_folders
    from src.tools.sonarr import sonarr_list_root_folders
    if scope in ("sonarr", "tv"):
        return await sonarr_list_root_folders.ainvoke({})
    if scope in ("radarr", "movie", "movies"):
        return await radarr_list_root_folders.ainvoke({})
    tv, movies = await asyncio.gather(
        sonarr_list_root_folders.ainvoke({}),
        radarr_list_root_folders.ainvoke({}),
        return_exceptions=True,
    )
    parts = []
    if isinstance(tv, str):
        parts.append("Sonarr (TV):\n" + tv)
    if isinstance(movies, str):
        parts.append("Radarr (movies):\n" + movies)
    return "\n\n".join(parts) if parts else "❌ Couldn't fetch root folders."


async def _h_emby_libraries(match, thread_id):
    from src.tools.emby import emby_libraries
    return await emby_libraries.ainvoke({})


async def _h_emby_search(match, thread_id):
    query = match.group("query").strip(" \"'")
    if not query or len(query) > 80:
        return None
    from src.tools.emby import emby_search
    return await emby_search.ainvoke({"query": query})


# ── ROM / emulation handlers ─────────────────────────────────────────────────

async def _h_rom_collection(match, thread_id):
    from src.providers.rom import rom_get_collection
    return await rom_get_collection.ainvoke({})


async def _h_rom_verify(match, thread_id):
    raw = (match.groupdict().get("platform") or "").strip()
    platform, _ = _extract_platform(raw) if raw else ("", "")
    if not platform:
        return ("Which platform should I verify? I know these: "
                + ", ".join(_KNOWN_PLATFORMS) + ".")
    from src.providers.rom import rom_verify_dat
    return await rom_verify_dat.ainvoke({"platform": platform})


async def _rom_search_and_pend(raw_query: str, thread_id: str, auto_add: bool) -> str | None:
    platform, query = _extract_platform(raw_query)
    if not platform and (not query or len(query) > 80):
        return None
    results = await _rom_search_structured(query, platform)
    label = query or f"{platform} ROM sets"
    if not results:
        return f"No ROM sets found on Internet Archive for '{label}'."
    _set_pending(thread_id, PendingSelection(
        results=results, auto_add=auto_add, kind="rom"))
    reply = _format_results(results, label, auto_add=auto_add)
    return reply + "\n(Heads-up: ROM sets can be large — sizes are shown above.)"


async def _h_rom_search(match, thread_id):
    return await _rom_search_and_pend(match.group("query").strip(), thread_id, auto_add=False)


async def _h_rom_download(match, thread_id):
    return await _rom_search_and_pend(match.group("query").strip(), thread_id, auto_add=True)


def _platform_arg(match) -> dict:
    """Optional platform group → tool args ({} when absent/unknown)."""
    raw = (match.groupdict().get("platform") or "").strip()
    if not raw:
        return {}
    slug, _ = _extract_platform(raw)
    return {"platform": slug} if slug else {}


async def _h_rom_scan(match, thread_id):
    from src.tools.rom_tools import rom_scan_library
    return await rom_scan_library.ainvoke(_platform_arg(match))


async def _h_rom_problems(match, thread_id):
    from src.tools.rom_tools import rom_check_problems
    return await rom_check_problems.ainvoke(_platform_arg(match))


async def _h_rom_dupes(match, thread_id):
    from src.tools.rom_tools import rom_find_duplicates
    return await rom_find_duplicates.ainvoke(_platform_arg(match))


async def _h_rom_inspect(match, thread_id):
    from src.tools.rom_tools import rom_inspect
    return await rom_inspect.ainvoke({"path": match.group("path")})


# ── YouTube handlers (no-URL forms) ──────────────────────────────────────────

async def _h_yt_list_subs(match, thread_id):
    try:
        from src.providers.youtube import youtube_list_subscriptions
    except ImportError:
        return "❌ YouTube support isn't installed."
    return await youtube_list_subscriptions.ainvoke({})


async def _h_yt_check_subs(match, thread_id):
    try:
        from src.providers.youtube import youtube_check_subscriptions
    except ImportError:
        return "❌ YouTube support isn't installed."
    return await youtube_check_subscriptions.ainvoke({})


async def _h_yt_unsub(match, thread_id):
    name = match.group("name").strip(" \"'")
    if not name:
        return None
    try:
        from src.providers.youtube import youtube_remove_subscription
    except ImportError:
        return "❌ YouTube support isn't installed."
    return await youtube_remove_subscription.ainvoke({"name_or_url": name})


async def _h_yt_sub_no_url(match, thread_id):
    # "subscribe to <name>" without a URL — the URL step already handled links.
    return ("I need the channel URL to subscribe (youtube.com/@channel). "
            "Paste it and say 'subscribe'.")


# ── Audible handlers ─────────────────────────────────────────────────────────

async def _h_audible_library(match, thread_id):
    from src.providers.audible import audible_list_library
    return await audible_list_library.ainvoke({})


async def _h_audible_new(match, thread_id):
    from src.providers.audible import audible_download_new
    return await audible_download_new.ainvoke({})


async def _h_audible_check(match, thread_id):
    from src.providers.audible import audible_check_auth
    return await audible_check_auth.ainvoke({})


async def _h_audible_setup(match, thread_id):
    from src.providers.audible import audible_setup_auth
    return await audible_setup_auth.ainvoke({})


_ASIN_RE = re.compile(r"^[A-Za-z0-9]{10}$")


async def _h_audible_download(match, thread_id):
    rest = match.group("rest").strip(" \"'")
    if _ASIN_RE.match(rest):
        from src.providers.audible import audible_download
        return await audible_download.ainvoke({"asin": rest.upper()})
    # A title, not an ASIN — the LLM can look up the ASIN in the library.
    return None


# ── Bandcamp handlers ────────────────────────────────────────────────────────

async def _h_bandcamp_collection(match, thread_id):
    from src.providers.bandcamp import bandcamp_download_collection

    async def _do_collection():
        return await bandcamp_download_collection.ainvoke({})

    return _confirm_action(
        thread_id,
        "That downloads every purchased album in your Bandcamp collection — "
        "it can take a while. Go ahead? (yes/no)",
        _do_collection,
    )


# ── Library maintenance handlers ─────────────────────────────────────────────

def _naming_convention(match, path: str) -> str:
    conv = (match.groupdict().get("conv") or "").lower().rstrip("s")
    if conv in ("tv", "movie"):
        return "tv" if conv == "tv" else "movies"
    return "movies" if "movie" in path.lower() else "tv"


async def _h_lib_inventory(match, thread_id):
    from src.tools.library_tools import library_build_inventory
    return await library_build_inventory.ainvoke({"path": match.group("path")})


async def _h_lib_duplicates(match, thread_id):
    from src.tools.library_tools import library_find_duplicates
    return await library_find_duplicates.ainvoke({"path": match.group("path")})


async def _h_lib_duplicates_nopath(match, thread_id):
    return ("Which folder should I scan for duplicates? "
            "Give me a path, e.g. 'find duplicates in /media/movies'.")


async def _h_lib_check_naming(match, thread_id):
    from src.tools.library_tools import library_check_naming
    path = match.group("path")
    return await library_check_naming.ainvoke(
        {"path": path, "convention": _naming_convention(match, path)})


async def _h_lib_fix_naming(match, thread_id):
    from src.tools.library_tools import library_fix_naming
    path = match.group("path")
    convention = _naming_convention(match, path)

    async def _do_fix():
        return await library_fix_naming.ainvoke(
            {"path": path, "convention": convention})

    return _confirm_action(
        thread_id,
        f"This renames files under {path} to the '{convention}' convention "
        "(an undo log is written first). Go ahead? (yes/no)",
        _do_fix,
    )


async def _h_lib_undo(match, thread_id):
    from src.tools.library_tools import library_undo_rename
    return await library_undo_rename.ainvoke({"undo_log_path": match.group("path")})


# ── media search/add handlers ────────────────────────────────────────────────

# "grab it", "add that", "get the first one" with no router-pending selection
# refer to something from the LLM conversation — the LLM has that context,
# the router doesn't. Never hijack them into a fresh title search.
_DEICTIC_QUERIES = {"it", "that", "this", "them", "those", "these", "one",
                    "both", "all of them", "everything"}


def _is_deictic(query: str) -> bool:
    q = query.lower().strip()
    return q in _DEICTIC_QUERIES or _PICK_RE.match(q) is not None


async def _h_search(match, thread_id):
    raw = match.group("query").strip()
    query, media_type = _extract_media_query(raw)
    if not query or len(query) > 80 or _is_deictic(query):
        return None  # let the LLM interpret unusual queries
    results = await _structured_search(query, media_type)
    if not results:
        return f"No matches for '{query}' in TV or movie sources."
    _set_pending(thread_id, PendingSelection(results=results, auto_add=False))
    return _format_results(results, query, auto_add=False)


async def _h_add(match, thread_id):
    raw = match.group("query").strip()
    query, media_type = _extract_media_query(raw)
    if not query or len(query) > 80 or _is_deictic(query):
        return None
    results = await _structured_search(query, media_type)
    if not results:
        return (f"I couldn't find anything matching '{query}' to add. "
                "Try a different spelling?")
    _set_pending(thread_id, PendingSelection(results=results, auto_add=True))
    return _format_results(results, query, auto_add=True)


# ── intent table ─────────────────────────────────────────────────────────────
# Order matters: specific intents first; broad search/add catch-alls last.

def _rx(*patterns: str) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_INTENTS: list[tuple[str, list[re.Pattern], object]] = [
    # ── missing media (before the broad search catch-all) ──
    ("missing_all", _rx(
        r"^(?:search for |find |check (?:for )?)?(?:all )?missing (?:media|content|stuff|items)$",
        r"^search for missing$",
        r"^(?:find|search for) (?:all )?missing episodes and movies$",
    ), _h_missing_all),
    ("missing_tv", _rx(
        r"^(?:search for |find |check (?:for )?|look for )?missing episodes?$",
        r"^(?:search for |find )?wanted episodes?$",
        r"^what(?:'s| is| are)? missing (?:episodes?|shows?|on tv)$",
    ), _h_missing_tv),
    ("missing_movies", _rx(
        r"^(?:search for |find |check (?:for )?|look for )?missing (?:movies?|films?)$",
        r"^what(?:'s| is| are)? missing movies?$",
    ), _h_missing_movies),

    # ── status / health / space ──
    ("queue", _rx(
        r"^(?:so )?what(?:'s| is)(?: currently)? downloading(?: right now| now| at the moment)?$",
        r"^(?:is )?anything downloading$",
        r"^downloads?$",
        r"^(?:show |list |check |get )?(?:the |my )?download (?:queue|status|progress)$",
        r"^(?:show |list |check )?(?:all |the |my )?queues?(?: status)?$",
        r"^check all queues$",
        r"^queue status$",
        r"^what(?:'s| is) in the queue$",
    ), _h_queue),
    ("health", _rx(
        r"^(?:run |do )?(?:a )?health ?check$",
        r"^(?:check |show )?(?:the )?health(?: of everything| status)?$",
        r"^is everything (?:ok|okay|alright|healthy|running|up|good|working)$",
        r"^(?:are )?all (?:systems|services) (?:ok|okay|healthy|up|operational|running|good)$",
        r"^(?:check |show |what(?:'s| is) the )?(?:system |service |server )?status$",
        r"^how(?:'s| is) everything(?: looking| doing)?$",
        r"^status of (?:all )?(?:the )?(?:services|servers|everything)$",
    ), _h_health),
    ("disk", _rx(
        r"^(?:check |show |how much |what(?:'s| is) (?:my |the )?)?(?:free |available )?(?:disk|storage|drive) ?space(?: left| available| do i have)?$",
        r"^how much space (?:is left|do i have|remains)$",
        r"^(?:check |show )?free space$",
        r"^space left$",
    ), _h_disk),

    # ── per-service queues & stats ──
    ("sab_status", _rx(
        r"^(?:sabnzbd|sab|usenet) status$",
        r"^(?:what's |what is |check |show )?(?:the )?download speed$",
        r"^how fast (?:are|is) (?:the )?downloads?(?: going)?$",
    ), _h_sab_status),
    ("sab_queue", _rx(
        r"^(?:sabnzbd|sab|usenet) queue$",
    ), _h_sab_queue),
    ("tv_queue", _rx(
        r"^(?:tv|sonarr) queue$",
        r"^what (?:tv|shows?) (?:is|are) downloading$",
    ), _h_tv_queue),
    ("movie_queue", _rx(
        r"^(?:movie|movies|radarr|film) queue$",
        r"^what movies? (?:is|are) downloading$",
    ), _h_movie_queue),
    ("ds_stats", _rx(
        r"^(?:download station|ds|nas) (?:stats|statistics|speed)$",
        r"^torrent (?:stats|speed)$",
    ), _h_ds_stats),

    # ── library lists ──
    ("list_tv", _rx(
        r"^(?:list|show)(?: me)?(?: all)?(?: of)?(?: my)? (?:tv )?shows$",
        r"^(?:list|show)(?: me)?(?: all)?(?: of)?(?: my)? (?:tv|series)$",
        r"^what (?:tv )?shows (?:do i have|am i (?:monitoring|tracking))$",
        r"^how many (?:tv )?shows (?:do i have|are there)$",
        r"^my (?:tv )?shows$",
    ), _h_list_tv),
    ("list_movies", _rx(
        r"^(?:list|show)(?: me)?(?: all)?(?: of)?(?: my)? (?:movies|films)$",
        r"^what (?:movies|films) do i have$",
        r"^how many (?:movies|films) (?:do i have|are there)$",
        r"^my (?:movies|films)$",
    ), _h_list_movies),
    ("recent", _rx(
        r"^what(?:'s| was| is)? ?(?:been )?recently added(?: to (?:emby|the library|plex))?$",
        r"^(?:show |list )?recent(?:ly)? (?:added|additions)(?: to (?:emby|the library))?$",
        r"^what(?:'s| is) new(?: in (?:emby|the library))?$",
        r"^(?:any |show me )?(?:new|latest) (?:additions|stuff|content|arrivals)$",
        r"^recent$",
    ), _h_recent),
    ("calendar", _rx(
        r"^what(?:'s| is) (?:airing|on)(?: tv)?(?: today| tonight| this week| soon)?$",
        r"^(?:show |check )?(?:the |my )?(?:tv )?calendar$",
        r"^(?:any )?upcoming episodes?$",
        r"^what(?:'s| is) (?:coming (?:up|out)|upcoming)(?: this week| soon)?$",
        r"^what episodes? (?:are )?(?:airing|coming)(?: this week| today| soon)?$",
    ), _h_calendar),
    ("scan", _rx(
        r"^(?:re)?scan (?:the |my )?(?:emby )?library$",
        r"^(?:run |trigger |start )?(?:a |an )?(?:emby |library )scan$",
        r"^refresh (?:the |my )?(?:emby )?library$",
        r"^refresh emby$",
        r"^emby scan$",
    ), _h_scan),
    ("history", _rx(
        r"^(?:show |check |list )?(?:the |my )?(?:download |recent )?history$",
        r"^what (?:was|got) (?:recently )?downloaded(?: recently)?$",
    ), _h_history),
    ("torrents", _rx(
        r"^(?:list |show |check )?(?:my |the |all )?torrents?$",
        r"^(?:list |show |check )?download station(?: tasks| downloads| queue)?$",
        r"^(?:list |show )?ds tasks$",
    ), _h_torrents),
    ("pause", _rx(
        r"^pause (?:all )?(?:the )?downloads?$",
        r"^pause (?:sabnzbd|sab|usenet)$",
        r"^stop (?:all )?(?:the )?downloads?$",
    ), _h_pause_downloads),
    ("resume", _rx(
        r"^(?:resume|unpause|restart|continue) (?:all )?(?:the )?downloads?$",
        r"^(?:resume|unpause) (?:sabnzbd|sab|usenet)$",
    ), _h_resume_downloads),

    # ── service configuration ──
    ("quality_profiles", _rx(
        r"^(?:list |show )?(?:(?P<scope>sonarr|radarr|tv|movies?) )?quality profiles$",
    ), _h_quality_profiles),
    ("root_folders", _rx(
        r"^(?:list |show )?(?:(?P<scope>sonarr|radarr|tv|movies?) )?root folders$",
    ), _h_root_folders),
    ("emby_libraries", _rx(
        r"^(?:list |show )?(?:my |the )?(?:emby )?libraries$",
    ), _h_emby_libraries),

    # ── ROMs & emulation ──
    ("rom_collection", _rx(
        r"^(?:list |show |check )?(?:my )?(?:rom|game|games) collection$",
        r"^(?:list|show)(?: me)?(?: all)?(?: of)?(?: my)? (?:roms|games|classic games|retro games)$",
        r"^what (?:roms|games) do i have$",
        r"^my (?:roms|games)$",
    ), _h_rom_collection),
    ("rom_inspect", _rx(
        r"^(?:inspect|examine) (?:the )?(?:rom )?(?P<path>/\S+)$",
        r"^rom (?:info|metadata|details) (?:for |on )?(?P<path>/\S+)$",
        r"^get (?:the )?metadata (?:for|of|on) (?:the )?(?:rom )?(?P<path>/\S+)$",
        r"^what is (?P<path>/\S+\.(?:nes|sfc|smc|gb|gbc|gba|n64|z64|v64|nds|md|gen|sms|gg|pce|a26|lnx|zip|bin|cue|iso))$",
    ), _h_rom_inspect),
    ("rom_dupes", _rx(
        r"^(?:find|check for|look for) duplicate (?:(?P<platform>[\w ]+?) )?(?:roms|games)$",
        r"^dedupe? (?:my |the )?(?:(?P<platform>[\w ]+?) )?roms?$",
        r"^rom (?:duplicates|dedupe?)$",
        r"^(?:are there |do i have )?duplicate roms$",
    ), _h_rom_dupes),
    ("rom_problems", _rx(
        r"^(?:check|debug) (?:my |the )?(?:(?P<platform>[\w ]+?) )?roms?(?: (?:library |collection )?for (?:problems|issues|errors))?$",
        r"^(?:any |find )?(?:bad|broken|corrupt|damaged) roms?$",
        r"^rom (?:problems|issues|debug|health)$",
        r"^debug (?:my |the )?rom (?:library|collection)$",
    ), _h_rom_problems),
    ("rom_scan", _rx(
        r"^(?:deep )?scan (?:my |the )?(?:(?P<platform>[\w ]+?) )?roms?(?: library| collection| folder)?$",
        r"^rom (?:scan|inventory|report)$",
        r"^(?:identify|analyze|analyse|parse) (?:my |the )?roms?(?: library| collection)?$",
        r"^what (?:types? of |kinds? of )?roms do i have$",
    ), _h_rom_scan),
    ("rom_verify", _rx(
        r"^verify (?:my )?(?P<platform>[\w ]+?) roms?$",
        r"^verify roms?(?: (?:for|against dats?) ?(?P<platform>[\w ]+))?$",
        r"^verify (?:my )?rom collection$",
    ), _h_rom_verify),
    ("rom_download", _rx(
        r"^(?:download|get|grab|add) (?P<query>.+?) roms?(?: sets?)?$",
        r"^(?:download|get|grab) (?:the )?(?P<query>.+?) rom ?sets?$",
        r"^(?:download|get|grab) roms? (?:for |of )?(?P<query>.+)$",
    ), _h_rom_download),
    ("rom_search", _rx(
        r"^(?:search|look) (?:for )?(?P<query>.+?) roms?(?: sets?)?$",
        r"^(?:search for|find) roms? (?:for |of )?(?P<query>.+)$",
        r"^search (?:the )?(?:internet )?archive for (?P<query>.+)$",
        r"^(?:find|search for) (?P<query>.+?) roms?$",
    ), _h_rom_search),

    # ── YouTube subscriptions (URL forms handled in the URL step) ──
    ("yt_list_subs", _rx(
        r"^(?:list |show )?(?:my )?(?:youtube |yt |channel )?subscriptions$",
        r"^what (?:channels )?am i subscribed to$",
    ), _h_yt_list_subs),
    ("yt_check_subs", _rx(
        r"^check (?:my )?(?:youtube |yt |channel )?subscriptions$",
        r"^(?:any )?new (?:youtube )?(?:uploads|videos)$",
        r"^check (?:for )?new (?:videos|uploads)$",
    ), _h_yt_check_subs),
    ("yt_unsub", _rx(
        r"^(?:unsubscribe|unfollow) (?:from |to )?(?P<name>.+)$",
        r"^remove (?:the )?(?:youtube )?subscription (?:for |to )?(?P<name>.+)$",
    ), _h_yt_unsub),
    ("yt_sub_no_url", _rx(
        r"^subscribe (?:me )?(?:to )?(?!.*(?:youtube\.com|youtu\.be))(?P<name>.+)$",
    ), _h_yt_sub_no_url),

    # ── Audiobooks / Audible ──
    ("audible_library", _rx(
        r"^(?:list |show )?(?:my )?(?:audio ?books?|audible)(?: library)?$",
        r"^what audio ?books? do i have$",
    ), _h_audible_library),
    ("audible_new", _rx(
        r"^(?:download|sync|get|grab) (?:my )?new audio ?books?$",
        r"^sync audible$",
        r"^audible sync$",
    ), _h_audible_new),
    ("audible_check", _rx(
        r"^check audible(?: auth| login| authentication)?$",
        r"^is audible (?:logged in|authenticated|working|connected)$",
    ), _h_audible_check),
    ("audible_setup", _rx(
        r"^set ?up audible(?: auth(?:entication)?)?$",
        r"^log ?in to audible$",
    ), _h_audible_setup),
    ("audible_download", _rx(
        r"^(?:download|get|grab) (?:the )?audio ?book (?P<rest>.+)$",
    ), _h_audible_download),

    # ── Bandcamp ──
    ("bandcamp_collection", _rx(
        r"^(?:download|sync|get|grab) (?:my )?(?:entire |whole |full )?bandcamp collection$",
        r"^sync bandcamp$",
    ), _h_bandcamp_collection),

    # ── Library maintenance ──
    ("lib_inventory", _rx(
        r"^(?:build |create |make )?(?:a |an )?(?:library |file )?inventory (?:of |for |in )?(?P<path>/\S+)$",
        r"^inventory (?P<path>/\S+)$",
    ), _h_lib_inventory),
    ("lib_duplicates", _rx(
        r"^(?:find|check for|look for) duplicates? (?:in |at |under )?(?P<path>/\S+)$",
        r"^(?:find|check for) duplicate (?:files|media) (?:in |at )?(?P<path>/\S+)$",
    ), _h_lib_duplicates),
    ("lib_duplicates_nopath", _rx(
        r"^(?:find|check for|look for) duplicates?$",
        r"^(?:find|check for) duplicate (?:files|media)$",
    ), _h_lib_duplicates_nopath),
    ("lib_check_naming", _rx(
        r"^check (?:file ?)?nam(?:ing|es) (?:in |at |under |for )?(?P<path>/\S+)(?: as (?P<conv>tv|movies?))?$",
    ), _h_lib_check_naming),
    ("lib_fix_naming", _rx(
        r"^fix (?:file ?)?nam(?:ing|es) (?:in |at |under |for )?(?P<path>/\S+)(?: as (?P<conv>tv|movies?))?$",
        r"^rename files (?:in |at |under )?(?P<path>/\S+)(?: as (?P<conv>tv|movies?))?$",
    ), _h_lib_fix_naming),
    ("lib_undo", _rx(
        r"^undo (?:the )?(?:last )?renames? (?:from |using |with )?(?P<path>/\S+)$",
        r"^revert renames? (?:from |using |with )?(?P<path>/\S+)$",
    ), _h_lib_undo),

    # ── Emby search ("do I have X?") ──
    ("emby_search", _rx(
        r"^search (?:emby|the library|my library) for (?P<query>.+)$",
        r"^do (?:i|we) (?:already )?have (?P<query>.+?)(?: in (?:emby|the library))?$",
        r"^is (?P<query>.+) in (?:my|the) library$",
    ), _h_emby_search),

    # ── Broad catch-alls last ──
    ("search", _rx(
        r"^(?:search|look) for (?P<query>.+)$",
        r"^search (?P<query>.+)$",
        r"^(?:find|lookup|look up) (?P<query>.+)$",
    ), _h_search),
    ("add", _rx(
        r"^(?:add|download|grab|get) (?P<query>.+)$",
        r"^(?:can you |please |could you )+(?:add|download|grab|get) (?P<query>.+?)(?: for me| please)?$",
    ), _h_add),
]


# ── entry point ──────────────────────────────────────────────────────────────

async def try_route(message: str, thread_id: str) -> str | None:
    """Try to answer ``message`` deterministically.

    Returns the reply string when an intent matched and was handled, or
    ``None`` when the message should go to the LLM agent. Never raises.
    """
    try:
        text = _normalize(message)
        if not text or len(text) > 300:
            return None

        # 1. A pending confirmation takes priority.
        reply = await _resolve_pending(text, thread_id)
        if reply is not None:
            logger.info("router: pending-confirmation handled %r", text[:60])
            return reply

        # 2. Media URLs (YouTube, Bandcamp, magnet/.torrent, .nzb).
        reply = await _try_url_intents(text, thread_id)
        if reply is not None:
            logger.info("router: url intent handled %r", text[:60])
            return reply

        # 3. Intent table.
        for name, patterns, handler in _INTENTS:
            for pattern in patterns:
                match = pattern.match(text)
                if match:
                    reply = await handler(match, thread_id)
                    if reply is not None:
                        logger.info("router: intent %s handled %r", name, text[:60])
                    return reply

        return None
    except Exception:
        # Deterministic path must never take the agent down — fall through.
        logger.exception("router: failed on %r; falling back to LLM", message[:80])
        return None
