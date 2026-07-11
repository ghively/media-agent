"""Deterministic intent router — the fast path in front of the LLM agent.

Common natural-language commands ("what's downloading?", "check health",
"search for Andor", "add Breaking Bad") are recognized with regex patterns
and answered by calling the underlying tools directly — no LLM round-trip.
Anything the router doesn't confidently recognize falls through to the
LangGraph ReAct agent (``try_route`` returns ``None``).

Design rules (hardening):
- The router NEVER raises. A crash in any handler is logged and the message
  falls through to the LLM agent, so the user always gets an answer.
- Patterns are conservative: only fire on high-confidence matches. Ambiguous
  or conversational messages go to the LLM.
- Adds always require confirmation (search → numbered list → "yes"/"add #2"),
  mirroring the agent's confirmation rule. Pending selections are per-thread,
  expire after PENDING_TTL_SECONDS, and the table is bounded.
- Tool modules are imported lazily inside handlers so optional integrations
  (SABnzbd, Download Station) degrade gracefully and the router stays cheap
  to import.
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
    """Search results awaiting a user selection/confirmation on one thread."""
    results: list[dict]          # unified search result dicts (title/year/source_type/id)
    auto_add: bool               # True when triggered by an "add X" request
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


def clear_pending(thread_id: str) -> None:
    _pending.pop(thread_id, None)


# ── text normalization ──────────────────────────────────────────────────────

_PUNCT_RE = re.compile(r"[?!.]+$")
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("’", "'")
    text = _PUNCT_RE.sub("", text).strip()
    return _WS_RE.sub(" ", text)


# ── media-type extraction for search/add queries ────────────────────────────

_TV_WORDS = re.compile(
    r"\b(?:the\s+)?(?:tv\s+show|tv\s+series|show|series|tv)\b", re.IGNORECASE)
_MOVIE_WORDS = re.compile(r"\b(?:the\s+)?(?:movie|film)\b", re.IGNORECASE)
_FILLER_RE = re.compile(r"\b(?:called|named|titled)\b", re.IGNORECASE)


def _extract_media_query(raw: str) -> tuple[str, str | None]:
    """Pull an optional media-type hint out of a search/add phrase.

    "the movie Dune"        → ("dune", "movie")
    "tv show Severance"     → ("severance", "tv")
    "Breaking Bad"          → ("breaking bad", None)
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


def _format_results(results: list[dict], query: str, auto_add: bool) -> str:
    type_labels = {"tv": "TV show", "movie": "movie"}
    lines = [f"Found {len(results)} match(es) for '{query}':", ""]
    for i, r in enumerate(results, 1):
        year = f" ({r['year']})" if r.get("year") else ""
        label = type_labels.get(r.get("source_type"), r.get("source_type", ""))
        lines.append(f"  {i}. {r['title']}{year} — {label}")
        if r.get("overview"):
            lines.append(f"     {r['overview'][:110]}")
    lines.append("")
    if auto_add:
        lines.append("Want me to add one? Say 'yes' for #1, or 'add #2' / 'the second one'.")
    else:
        lines.append("Say 'add #1' (or 'the first one') if you want me to grab one of these.")
    return "\n".join(lines)


async def _add_result(result: dict) -> str:
    """Add a selected search result via Sonarr or Radarr."""
    title = str(result.get("title", "Unknown"))
    source_id = result.get("id")
    if source_id is None:
        return f"❌ Can't add '{title}' — the search result has no usable ID."
    if result.get("source_type") == "movie":
        from src.tools.radarr import add_movie
        return await add_movie.ainvoke({"tmdb_id": int(source_id), "title": title})
    else:
        from src.tools.sonarr import add_tv_show
        return await add_tv_show.ainvoke({"tvdb_id": int(source_id), "title": title})


# ── pending-selection resolution ─────────────────────────────────────────────

_YES_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|confirm|do it|go ahead|go for it|"
    r"add it|grab it|get it|that's the one|thats the one|correct|right one)$")
_NO_RE = re.compile(
    r"^(?:no|nope|nah|cancel|stop|never ?mind|nevermind|don't|dont|wrong one|none of (?:those|them))$")
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
}
_PICK_RE = re.compile(
    r"^(?:add |grab |get |download |use |pick |choose |go with )?"
    r"(?:the )?"
    r"(?:number |option |result |#)?"
    r"(?P<sel>\d+|first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)"
    r"(?: one)?$")


def _parse_selection(text: str, count: int) -> int | None:
    """Return a 0-based index into pending results, or None if not a pick."""
    m = _PICK_RE.match(text)
    if not m:
        return None
    sel = m.group("sel")
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
    """Handle yes/no/pick replies when a selection is pending on this thread."""
    pending = _pending.get(thread_id)
    if pending is None:
        return None
    if pending.expired:
        _pending.pop(thread_id, None)
        return None

    if _NO_RE.match(text):
        _pending.pop(thread_id, None)
        return "Okay, cancelled — nothing was added."

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


# ── intent handlers ──────────────────────────────────────────────────────────
# Every handler: async (match, thread_id) -> str. Tool errors come back as
# "❌ ..." strings from the tools themselves; that's fine to show the user.

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
    parts = []
    if isinstance(tv, str):
        parts.append(tv)
    if isinstance(movies, str):
        parts.append(movies)
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


async def _h_search(match, thread_id):
    raw = match.group("query").strip()
    query, media_type = _extract_media_query(raw)
    if not query or len(query) > 80:
        return None  # let the LLM interpret unusual queries
    results = await _structured_search(query, media_type)
    if not results:
        return f"No matches for '{query}' in TV or movie sources."
    _sweep_pending()
    _pending[thread_id] = PendingSelection(results=results, auto_add=False)
    return _format_results(results, query, auto_add=False)


async def _h_add(match, thread_id):
    raw = match.group("query").strip()
    query, media_type = _extract_media_query(raw)
    if not query or len(query) > 80:
        return None
    results = await _structured_search(query, media_type)
    if not results:
        return (f"I couldn't find anything matching '{query}' to add. "
                "Try a different spelling?")
    _sweep_pending()
    _pending[thread_id] = PendingSelection(results=results, auto_add=True)
    return _format_results(results, query, auto_add=True)


# ── intent table ─────────────────────────────────────────────────────────────
# Order matters: specific intents first; broad search/add catch-alls last.

def _rx(*patterns: str) -> list[re.Pattern]:
    return [re.compile(p) for p in patterns]


_INTENTS: list[tuple[str, list[re.Pattern], object]] = [
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
    ("queue", _rx(
        r"^(?:so )?what(?:'s| is)(?: currently)? downloading(?: right now| now| at the moment)?$",
        r"^(?:is )?anything downloading$",
        r"^downloads?$",
        r"^(?:show |list |check )?(?:the |my )?download (?:queue|status|progress)$",
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
    # Broad catch-alls last. Query must be non-greedy captured to the end.
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
        if not text or len(text) > 200:
            return None

        # 1. A pending add/search confirmation takes priority.
        reply = await _resolve_pending(text, thread_id)
        if reply is not None:
            logger.info("router: pending-selection handled %r", text[:60])
            return reply

        # 2. Intent table.
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
