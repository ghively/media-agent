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
    # Case is preserved (URLs/ASINs/paths are case-sensitive payloads);
    # whitespace collapses and trailing punctuation is stripped.
    assert _normalize("  What's Downloading?!  ") == "What's Downloading"
    assert _normalize("Check   Health.") == "Check Health"
    assert _normalize("what’s downloading") == "what's downloading"
    url = "https://youtu.be/dQw4w9WgXcQ"
    assert url in _normalize(f"download   {url}")


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
    ("the movie Dune", "Dune", "movie"),
    ("tv show Severance", "Severance", "tv"),
    ("the series called Andor", "Andor", "tv"),
    ("Breaking Bad", "Breaking Bad", None),
    ('the film named "Heat"', "Heat", "movie"),
])
def test_extract_media_query(raw, query, mtype):
    got_query, got_type = _extract_media_query(_normalize(raw))
    assert got_query == query
    assert got_type == mtype


@pytest.mark.parametrize("raw,platform,remainder", [
    ("snes", "snes", ""),
    ("super nintendo", "snes", ""),
    ("mario kart 64", "", "mario kart 64"),
    ("nintendo 64 racing", "n64", "racing"),
    ("playstation classics", "psx", "classics"),
    ("game boy advance", "gba", ""),
    ("sega genesis collection", "genesis", "collection"),
])
def test_extract_platform(raw, platform, remainder):
    from src.graphs.router import _extract_platform
    got_platform, got_rest = _extract_platform(raw)
    assert got_platform == platform
    assert got_rest == remainder


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
    # per-service queues & stats
    ("sabnzbd status", "src.tools.sabnzbd.sabnzbd_status"),
    ("what's the download speed?", "src.tools.sabnzbd.sabnzbd_status"),
    ("usenet queue", "src.tools.sabnzbd.sabnzbd_queue"),
    ("tv queue", "src.tools.sonarr.get_tv_queue"),
    ("movie queue", "src.tools.radarr.get_movie_queue"),
    ("download station stats", "src.tools.download_station.download_station_stats"),
    # service configuration
    ("emby libraries", "src.tools.emby.emby_libraries"),
    ("list libraries", "src.tools.emby.emby_libraries"),
    # ROMs & emulation
    ("list my rom collection", "src.providers.rom.rom_get_collection"),
    ("what games do I have?", "src.providers.rom.rom_get_collection"),
    ("show my retro games", "src.providers.rom.rom_get_collection"),
    ("verify my snes roms", "src.providers.rom.rom_verify_dat"),
    # YouTube subscriptions
    ("list my youtube subscriptions", "src.providers.youtube.youtube_list_subscriptions"),
    ("subscriptions", "src.providers.youtube.youtube_list_subscriptions"),
    ("check youtube subscriptions", "src.providers.youtube.youtube_check_subscriptions"),
    ("any new uploads?", "src.providers.youtube.youtube_check_subscriptions"),
    ("unsubscribe from LinusTechTips", "src.providers.youtube.youtube_remove_subscription"),
    # Audible
    ("list my audiobooks", "src.providers.audible.audible_list_library"),
    ("audible library", "src.providers.audible.audible_list_library"),
    ("download my new audiobooks", "src.providers.audible.audible_download_new"),
    ("sync audible", "src.providers.audible.audible_download_new"),
    ("check audible auth", "src.providers.audible.audible_check_auth"),
    ("is audible logged in?", "src.providers.audible.audible_check_auth"),
    ("set up audible", "src.providers.audible.audible_setup_auth"),
    ("download audiobook B002V0QK4C", "src.providers.audible.audible_download"),
    # Library maintenance
    ("build an inventory of /media/tv", "src.tools.library_tools.library_build_inventory"),
    ("find duplicates in /media/movies", "src.tools.library_tools.library_find_duplicates"),
    ("check naming in /media/tv", "src.tools.library_tools.library_check_naming"),
    ("undo rename /media/.media_agent_undo/log1.json", "src.tools.library_tools.library_undo_rename"),
    # Emby search
    ("do I have The Matrix?", "src.tools.emby.emby_search"),
    ("search emby for Alien", "src.tools.emby.emby_search"),
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


# ── deictic guard: never hijack references to LLM-shown results ──────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "grab it", "add that", "download it", "get the first one", "add #2",
])
async def test_deictic_add_falls_through_without_pending(message):
    assert await try_route(message, "no-pending-thread") is None


# ── scoped quality profiles / root folders ───────────────────────────────────

@pytest.mark.asyncio
async def test_quality_profiles_scoped(monkeypatch):
    sonarr = _patch_tool(monkeypatch, "src.tools.sonarr.sonarr_list_quality_profiles", "tv profiles")
    radarr = _patch_tool(monkeypatch, "src.tools.radarr.radarr_list_quality_profiles", "movie profiles")
    assert await try_route("sonarr quality profiles", "t1") == "tv profiles"
    assert await try_route("radarr quality profiles", "t1") == "movie profiles"
    combined = await try_route("quality profiles", "t1")
    assert "tv profiles" in combined and "movie profiles" in combined
    assert len(sonarr.calls) == 2 and len(radarr.calls) == 2


@pytest.mark.asyncio
async def test_root_folders_combined(monkeypatch):
    _patch_tool(monkeypatch, "src.tools.sonarr.sonarr_list_root_folders", "tv roots")
    _patch_tool(monkeypatch, "src.tools.radarr.radarr_list_root_folders", "movie roots")
    combined = await try_route("show root folders", "t1")
    assert "tv roots" in combined and "movie roots" in combined


# ── ROM search & download confirmation flow ──────────────────────────────────

FAKE_ARCHIVE = [
    {"title": "Nintendo - SNES (No-Intro)", "identifier": "no-intro_snes",
     "item_size": 3 * 1024**3},
    {"title": "SNES Romset (Redump)", "identifier": "redump_snes",
     "item_size": 5 * 1024**3},
]


def _patch_rom_search(monkeypatch, results=FAKE_ARCHIVE):
    import src.providers.rom as rom_mod

    def fake_search(query, platform):
        fake_search.calls.append((query, platform))
        return list(results)

    fake_search.calls = []
    monkeypatch.setattr(rom_mod, "_search_archive_sync", fake_search)
    return fake_search


@pytest.mark.asyncio
async def test_rom_download_flow(monkeypatch):
    search = _patch_rom_search(monkeypatch)
    rom_dl = _patch_tool(monkeypatch, "src.providers.rom.rom_download", "✅ ROM set downloaded")

    reply = await try_route("download snes roms", "r1")
    assert "no-intro_snes" not in reply  # human-readable list, not raw ids
    assert "ROM set" in reply
    assert "GB" in reply  # sizes surfaced before confirming
    assert search.calls == [("", "snes")]  # platform extracted, passed through
    assert router._pending["r1"].kind == "rom"

    confirm = await try_route("yes", "r1")
    assert confirm == "✅ ROM set downloaded"
    assert rom_dl.calls == [{"identifier": "no-intro_snes", "platform": "snes"}]
    assert "r1" not in router._pending


@pytest.mark.asyncio
async def test_rom_search_by_title_pick_second(monkeypatch):
    _patch_rom_search(monkeypatch)
    rom_dl = _patch_tool(monkeypatch, "src.providers.rom.rom_download", "✅ downloading")
    await try_route("search for super nintendo roms", "r2")
    confirm = await try_route("the second one", "r2")
    assert confirm == "✅ downloading"
    assert rom_dl.calls[0]["identifier"] == "redump_snes"


@pytest.mark.asyncio
async def test_rom_verify_unknown_platform_asks():
    reply = await try_route("verify my rom collection", "r3")
    assert "Which platform" in reply
    assert "snes" in reply


@pytest.mark.asyncio
async def test_rom_verify_platform_alias(monkeypatch):
    verify = _patch_tool(monkeypatch, "src.providers.rom.rom_verify_dat", "✅ verified")
    reply = await try_route("verify my super nintendo roms", "r4")
    assert reply == "✅ verified"
    assert verify.calls == [{"platform": "snes"}]


# ── YouTube URL intents ──────────────────────────────────────────────────────

YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_youtube_download_url(monkeypatch):
    dl = _patch_tool(monkeypatch, "src.providers.youtube.youtube_download", "✅ downloaded")
    reply = await try_route(f"download {YT_URL}", "y1")
    assert reply == "✅ downloaded"
    # URL case must survive normalization
    assert dl.calls == [{"url": YT_URL, "content_type": "video"}]


@pytest.mark.asyncio
async def test_youtube_download_as_music(monkeypatch):
    dl = _patch_tool(monkeypatch, "src.providers.youtube.youtube_download", "✅ audio saved")
    await try_route(f"grab the audio from {YT_URL}", "y2")
    assert dl.calls[0]["content_type"] == "music"


@pytest.mark.asyncio
async def test_youtube_subscribe_url(monkeypatch):
    sub = _patch_tool(monkeypatch, "src.providers.youtube.youtube_add_subscription", "✅ subscribed")
    url = "https://youtube.com/@SomeChannel"
    reply = await try_route(f"subscribe to {url}", "y3")
    assert reply == "✅ subscribed"
    assert sub.calls[0]["url"] == url


@pytest.mark.asyncio
async def test_youtube_bare_url_offers_download(monkeypatch):
    _patch_tool(monkeypatch, "src.providers.youtube.youtube_get_info", "Title: Some Video")
    dl = _patch_tool(monkeypatch, "src.providers.youtube.youtube_download", "✅ done")
    reply = await try_route(YT_URL, "y4")
    assert "Some Video" in reply
    assert "download it" in reply.lower()
    confirm = await try_route("yes", "y4")
    assert confirm == "✅ done"
    assert dl.calls


@pytest.mark.asyncio
async def test_subscribe_without_url_asks_for_it():
    reply = await try_route("subscribe to LinusTechTips", "y5")
    assert "URL" in reply


# ── Bandcamp ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bandcamp_url_download(monkeypatch):
    dl = _patch_tool(monkeypatch, "src.providers.bandcamp.bandcamp_download", "✅ album saved")
    url = "https://artist.bandcamp.com/album/cool-album"
    reply = await try_route(f"download {url}", "b1")
    assert reply == "✅ album saved"
    assert dl.calls == [{"url": url}]


@pytest.mark.asyncio
async def test_bandcamp_collection_requires_confirmation(monkeypatch):
    dl = _patch_tool(monkeypatch, "src.providers.bandcamp.bandcamp_download_collection", "✅ collection synced")
    reply = await try_route("download my bandcamp collection", "b2")
    assert "yes/no" in reply
    assert not dl.calls  # nothing ran yet
    confirm = await try_route("yes", "b2")
    assert confirm == "✅ collection synced"
    assert len(dl.calls) == 1


# ── magnet / torrent / NZB URLs ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_magnet_with_verb_adds_directly(monkeypatch):
    add = _patch_tool(monkeypatch, "src.tools.download_station.download_station_add", "✅ task added")
    magnet = "magnet:?xt=urn:btih:ABCDEF1234567890"
    reply = await try_route(f"add {magnet}", "m1")
    assert reply == "✅ task added"
    assert add.calls == [{"url": magnet}]


@pytest.mark.asyncio
async def test_bare_magnet_asks_first(monkeypatch):
    add = _patch_tool(monkeypatch, "src.tools.download_station.download_station_add", "✅ added")
    reply = await try_route("magnet:?xt=urn:btih:ABC123", "m2")
    assert "yes/no" in reply
    assert not add.calls
    assert (await try_route("no", "m2")).lower().startswith("okay")
    assert not add.calls


@pytest.mark.asyncio
async def test_nzb_url_categorised_as_tv(monkeypatch):
    add = _patch_tool(monkeypatch, "src.tools.sabnzbd.sabnzbd_add_nzb", "✅ queued")
    url = "https://indexer.example.com/get/12345.nzb"
    reply = await try_route(f"download this tv episode {url}", "n1")
    assert reply == "✅ queued"
    assert add.calls == [{"nzb_url": url, "category": "tv"}]


# ── Audible specifics ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audible_asin_uppercased(monkeypatch):
    dl = _patch_tool(monkeypatch, "src.providers.audible.audible_download", "✅ audiobook saved")
    reply = await try_route("download audiobook b002v0qk4c", "a1")
    assert reply == "✅ audiobook saved"
    assert dl.calls == [{"asin": "B002V0QK4C"}]


@pytest.mark.asyncio
async def test_audible_title_falls_through_to_llm():
    # A title isn't an ASIN — the LLM should look it up in the library.
    assert await try_route("download audiobook The Martian", "a2") is None


# ── Library maintenance flows ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fix_naming_requires_confirmation(monkeypatch):
    fix = _patch_tool(monkeypatch, "src.tools.library_tools.library_fix_naming", "✅ renamed 12 files")
    reply = await try_route("fix naming in /media/tv", "l1")
    assert "yes/no" in reply and "undo log" in reply
    assert not fix.calls
    confirm = await try_route("go ahead", "l1")
    assert confirm == "✅ renamed 12 files"
    assert fix.calls == [{"path": "/media/tv", "convention": "tv"}]


@pytest.mark.asyncio
async def test_fix_naming_infers_movie_convention(monkeypatch):
    fix = _patch_tool(monkeypatch, "src.tools.library_tools.library_fix_naming", "✅ done")
    await try_route("fix naming in /media/movies", "l2")
    await try_route("yes", "l2")
    assert fix.calls[0]["convention"] == "movies"


@pytest.mark.asyncio
async def test_check_naming_passes_convention(monkeypatch):
    check = _patch_tool(monkeypatch, "src.tools.library_tools.library_check_naming", "✅ ok")
    await try_route("check naming in /media/downloads as movies", "l3")
    assert check.calls == [{"path": "/media/downloads", "convention": "movies"}]


@pytest.mark.asyncio
async def test_duplicates_without_path_asks():
    reply = await try_route("find duplicates", "l4")
    assert "path" in reply.lower()


@pytest.mark.asyncio
async def test_emby_search_query_preserved(monkeypatch):
    search = _patch_tool(monkeypatch, "src.tools.emby.emby_search", "Found it")
    await try_route("do I have The Matrix?", "e1")
    assert search.calls == [{"query": "The Matrix"}]
