"""Tests for the deterministic intent router (no live services needed)."""
import time

import pytest

from src.graphs import router
from src.graphs.router import (
    PendingSelection,
    _extract_media_query,
    _normalize,
    _parse_selection,
    try_route,
)


class FakeTool:
    """Stands in for a LangChain @tool: records calls, returns a canned reply."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict) -> str:
        self.calls.append(args)
        return self.reply


def _patch_tool(monkeypatch, dotted: str, reply: str) -> FakeTool:
    module_path, name = dotted.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    fake = FakeTool(reply)
    monkeypatch.setattr(module, name, fake)
    return fake


# ── normalization / parsing units ────────────────────────────────────────────

def test_normalize():
    assert _normalize("  What's Downloading?!  ") == "what's downloading"
    assert _normalize("Check   Health.") == "check health"
    assert _normalize("what’s downloading") == "what's downloading"


@pytest.mark.parametrize("text,count,expected", [
    ("the first one", 3, 0),
    ("add #2", 3, 1),
    ("number 3", 3, 2),
    ("2", 3, 1),
    ("second", 3, 1),
    ("grab the 3rd one", 3, 2),
    ("last", 3, 2),
    ("add #9", 3, None),   # out of range
    ("banana", 3, None),
])
def test_parse_selection(text, count, expected):
    assert _parse_selection(text, count) == expected


@pytest.mark.parametrize("raw,query,mtype", [
    ("the movie Dune", "dune", "movie"),
    ("tv show Severance", "severance", "tv"),
    ("the series called Andor", "andor", "tv"),
    ("Breaking Bad", "breaking bad", None),
    ('the film named "Heat"', "heat", "movie"),
])
def test_extract_media_query(raw, query, mtype):
    got_query, got_type = _extract_media_query(_normalize(raw))
    assert got_query == query
    assert got_type == mtype


# ── intent → tool dispatch ───────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("message,dotted", [
    ("what's downloading?", "src.tools.health.check_queue_status"),
    ("What is downloading right now", "src.tools.health.check_queue_status"),
    ("downloads", "src.tools.health.check_queue_status"),
    ("check all queues", "src.tools.health.check_queue_status"),
    ("anything downloading?", "src.tools.health.check_queue_status"),
    ("is everything healthy?", "src.tools.health.check_all_health"),
    ("health check", "src.tools.health.check_all_health"),
    ("status", "src.tools.health.check_all_health"),
    ("how's everything looking?", "src.tools.health.check_all_health"),
    ("check disk space", "src.tools.health.check_disk_space"),
    ("how much space do I have?", "src.tools.health.check_disk_space"),
    ("list my tv shows", "src.tools.sonarr.list_tv_shows"),
    ("what shows do i have", "src.tools.sonarr.list_tv_shows"),
    ("how many movies do I have?", "src.tools.radarr.list_movies"),
    ("list movies", "src.tools.radarr.list_movies"),
    ("what was recently added to emby?", "src.tools.emby.emby_recent"),
    ("what's new", "src.tools.emby.emby_recent"),
    ("what is airing this week?", "src.tools.sonarr.get_tv_calendar"),
    ("upcoming episodes", "src.tools.sonarr.get_tv_calendar"),
    ("missing episodes", "src.tools.sonarr.search_missing_episodes"),
    ("find missing movies", "src.tools.radarr.search_missing_movies"),
    ("scan the library", "src.tools.emby.emby_scan"),
    ("refresh emby", "src.tools.emby.emby_scan"),
    ("pause downloads", "src.tools.sabnzbd.sabnzbd_pause"),
    ("resume downloads", "src.tools.sabnzbd.sabnzbd_resume"),
    ("list download station tasks", "src.tools.download_station.download_station_list"),
    ("torrents", "src.tools.download_station.download_station_list"),
])
async def test_intents_dispatch(monkeypatch, message, dotted):
    fake = _patch_tool(monkeypatch, dotted, "✅ ok")
    reply = await try_route(message, "t1")
    assert reply == "✅ ok"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_missing_all_combines_both(monkeypatch):
    tv = _patch_tool(monkeypatch, "src.tools.sonarr.search_missing_episodes", "tv ok")
    mv = _patch_tool(monkeypatch, "src.tools.radarr.search_missing_movies", "movies ok")
    reply = await try_route("search for missing", "t1")
    assert "tv ok" in reply and "movies ok" in reply
    assert tv.calls and mv.calls


@pytest.mark.asyncio
async def test_history_combines_both(monkeypatch):
    _patch_tool(monkeypatch, "src.tools.sonarr.get_tv_history", "tv hist")
    _patch_tool(monkeypatch, "src.tools.radarr.get_movie_history", "movie hist")
    reply = await try_route("show history", "t1")
    assert "tv hist" in reply and "movie hist" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "tell me a joke",
    "why is dune so popular?",
    "hello there",
    "what do you think about the weather",
    "can you compare sonarr and radarr for me",
    "",
    "x" * 300,  # too long for the deterministic path
])
async def test_fallthrough_to_llm(message):
    assert await try_route(message, "t1") is None


@pytest.mark.asyncio
async def test_intent_ordering_missing_beats_search(monkeypatch):
    """'search for missing episodes' must hit the missing intent, not search."""
    fake = _patch_tool(monkeypatch, "src.tools.sonarr.search_missing_episodes", "missing ok")
    reply = await try_route("search for missing episodes", "t1")
    assert reply == "missing ok"
    assert fake.calls


# ── search / add confirmation flow ───────────────────────────────────────────

FAKE_TV = [
    {"title": "Breaking Bad", "year": 2008, "source": "sonarr",
     "source_type": "tv", "id": 81189, "overview": "Chemistry teacher.", "relevance": 100},
    {"title": "Breaking Bad: The Movie", "year": 2017, "source": "sonarr",
     "source_type": "tv", "id": 999, "overview": "", "relevance": 60},
]
FAKE_MOVIES = [
    {"title": "El Camino: A Breaking Bad Movie", "year": 2019, "source": "radarr",
     "source_type": "movie", "id": 559969, "overview": "Jesse runs.", "relevance": 60},
]


def _patch_search(monkeypatch, tv=FAKE_TV, movies=FAKE_MOVIES):
    async def fake_sonarr(query, limit):
        return list(tv)

    async def fake_radarr(query, limit):
        return list(movies)

    import src.tools.search as search_mod
    monkeypatch.setattr(search_mod, "_search_sonarr", fake_sonarr)
    monkeypatch.setattr(search_mod, "_search_radarr", fake_radarr)


@pytest.mark.asyncio
async def test_add_flow_confirm_yes(monkeypatch):
    _patch_search(monkeypatch)
    add_tv = _patch_tool(monkeypatch, "src.tools.sonarr.add_tv_show", "✅ Added 'Breaking Bad'")

    reply = await try_route("add Breaking Bad", "t1")
    assert "Breaking Bad" in reply
    assert "1." in reply  # numbered list
    assert "t1" in router._pending

    confirm = await try_route("yes", "t1")
    assert confirm == "✅ Added 'Breaking Bad'"
    assert add_tv.calls == [{"tvdb_id": 81189, "title": "Breaking Bad"}]
    assert "t1" not in router._pending


@pytest.mark.asyncio
async def test_add_flow_pick_movie_by_number(monkeypatch):
    _patch_search(monkeypatch)
    add_movie = _patch_tool(monkeypatch, "src.tools.radarr.add_movie", "✅ Added movie")

    await try_route("search for breaking bad", "t2")
    pending = router._pending["t2"]
    movie_idx = next(i for i, r in enumerate(pending.results)
                     if r["source_type"] == "movie") + 1

    confirm = await try_route(f"add #{movie_idx}", "t2")
    assert confirm == "✅ Added movie"
    assert add_movie.calls == [{"tmdb_id": 559969, "title": "El Camino: A Breaking Bad Movie"}]


@pytest.mark.asyncio
async def test_add_flow_cancel(monkeypatch):
    _patch_search(monkeypatch)
    await try_route("add Breaking Bad", "t3")
    reply = await try_route("no", "t3")
    assert "cancelled" in reply.lower()
    assert "t3" not in router._pending


@pytest.mark.asyncio
async def test_bare_yes_after_search_asks_which(monkeypatch):
    """A plain search shouldn't auto-add on 'yes' — ask which one."""
    _patch_search(monkeypatch)
    await try_route("search for breaking bad", "t4")
    reply = await try_route("yes", "t4")
    assert "which one" in reply.lower()
    assert "t4" in router._pending  # still pending


@pytest.mark.asyncio
async def test_pending_expires(monkeypatch):
    _patch_search(monkeypatch)
    await try_route("add Breaking Bad", "t5")
    router._pending["t5"].created = time.monotonic() - (router.PENDING_TTL_SECONDS + 1)
    # Expired: "yes" no longer resolves deterministically.
    assert await try_route("yes", "t5") is None
    assert "t5" not in router._pending


@pytest.mark.asyncio
async def test_pending_is_per_thread(monkeypatch):
    _patch_search(monkeypatch)
    await try_route("add Breaking Bad", "thread-a")
    # A different thread saying "yes" has nothing pending.
    assert await try_route("yes", "thread-b") is None


@pytest.mark.asyncio
async def test_search_no_results(monkeypatch):
    _patch_search(monkeypatch, tv=[], movies=[])
    reply = await try_route("search for zzzzz nonsense", "t6")
    assert "No matches" in reply
    assert "t6" not in router._pending


@pytest.mark.asyncio
async def test_movie_hint_skips_tv_search(monkeypatch):
    calls = {"tv": 0, "movies": 0}

    async def fake_sonarr(query, limit):
        calls["tv"] += 1
        return []

    async def fake_radarr(query, limit):
        calls["movies"] += 1
        return list(FAKE_MOVIES)

    import src.tools.search as search_mod
    monkeypatch.setattr(search_mod, "_search_sonarr", fake_sonarr)
    monkeypatch.setattr(search_mod, "_search_radarr", fake_radarr)

    reply = await try_route("add the movie El Camino", "t7")
    assert calls == {"tv": 0, "movies": 1}
    assert "El Camino" in reply


@pytest.mark.asyncio
async def test_router_never_raises(monkeypatch):
    """A crashing handler falls through to the LLM instead of erroring."""
    import src.tools.health as health_mod

    class Exploder:
        async def ainvoke(self, args):
            raise RuntimeError("boom")

    monkeypatch.setattr(health_mod, "check_queue_status", Exploder())
    assert await try_route("what's downloading?", "t8") is None


@pytest.mark.asyncio
async def test_pending_table_bounded(monkeypatch):
    _patch_search(monkeypatch)
    for i in range(router.MAX_PENDING_THREADS + 10):
        router._pending[f"bulk-{i}"] = PendingSelection(results=list(FAKE_TV), auto_add=True)
    await try_route("add Breaking Bad", "t9")
    assert len(router._pending) <= router.MAX_PENDING_THREADS + 1
