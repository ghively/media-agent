"""Tests for the LLM-light pass: filler stripping, help/greeting, stats,
deterministic audiobook/artist/release flows, torrent pause intents, and the
domain classifier for scoped tool binding."""
import pytest

from src.graphs import router
from src.graphs.router import get_stats, try_route
from src.graphs.scoping import CORE_TOOLS, DOMAINS, classify, tools_for_domain
from tests.test_router import _patch_tool


# ── filler stripping widens coverage ─────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("message,dotted", [
    ("hey can you check the download queue please",
     "src.tools.health.check_queue_status"),
    ("please list my tv shows", "src.tools.sonarr.list_tv_shows"),
    ("ok what's downloading right now", "src.tools.health.check_queue_status"),
    ("scan the library now", "src.tools.emby.emby_scan"),
    ("could you check disk space for me", "src.tools.health.check_disk_space"),
])
async def test_polite_phrasings_route(monkeypatch, message, dotted):
    fake = _patch_tool(monkeypatch, dotted, "✅ ok")
    assert await try_route(message, "pf1") == "✅ ok"
    assert fake.calls


@pytest.mark.asyncio
async def test_bare_ok_still_confirms(monkeypatch):
    """Filler stripping must not eat a lone 'ok' that answers a pending
    confirmation."""
    fix = _patch_tool(monkeypatch, "src.tools.library_tools.library_fix_naming", "✅ renamed")
    await try_route("fix naming in /media/tv", "pf2")
    assert await try_route("ok", "pf2") == "✅ renamed"


def test_strip_filler_keeps_mid_sentence_words():
    assert router._strip_filler("add Thank You for Smoking") == "add Thank You for Smoking"
    assert router._strip_filler("please add Dune for me") == "add Dune"
    assert router._strip_filler("ok") == "ok"


# ── help / greeting ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["help", "what can you do", "commands"])
async def test_help_is_deterministic(message):
    reply = await try_route(message, "h1")
    assert "add Breaking Bad" in reply and "health check" in reply


@pytest.mark.asyncio
async def test_greeting_is_deterministic():
    reply = await try_route("hello", "h2")
    assert "help" in reply.lower()


# ── stats ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_track_router_vs_llm():
    before = get_stats()
    await try_route("help", "st1")                    # router hit
    await try_route("ponder the meaning of life", "st1")  # miss → llm
    after = get_stats()
    assert after["router"] == before["router"] + 1
    assert after["llm"] == before["llm"] + 1


# ── deterministic audiobook-by-title ─────────────────────────────────────────

_BOOKS = [
    {"title": "Project Hail Mary", "asin": "B08G9PRS1K"},
    {"title": "The Martian", "asin": "B00B5HZGUG"},
    {"title": "The Martian: Classified", "asin": "B09XYZ0000"},
]


@pytest.mark.asyncio
async def test_audiobook_title_single_match_confirms(monkeypatch):
    import src.providers.audible as audible_mod

    async def fake_lib():
        return list(_BOOKS)

    monkeypatch.setattr(audible_mod, "_fetch_library", fake_lib)
    dl = _patch_tool(monkeypatch, "src.providers.audible.audible_download", "✅ saved")
    reply = await try_route("download audiobook Project Hail Mary", "ab1")
    assert "Project Hail Mary" in reply and "(yes/no)" in reply
    assert not dl.calls
    assert await try_route("yes", "ab1") == "✅ saved"
    assert dl.calls == [{"asin": "B08G9PRS1K"}]


@pytest.mark.asyncio
async def test_audiobook_title_multiple_matches_numbered(monkeypatch):
    import src.providers.audible as audible_mod

    async def fake_lib():
        return list(_BOOKS)

    monkeypatch.setattr(audible_mod, "_fetch_library", fake_lib)
    dl = _patch_tool(monkeypatch, "src.providers.audible.audible_download", "✅ saved")
    reply = await try_route("download the audiobook Martian", "ab2")
    assert "The Martian" in reply and "2." in reply
    assert await try_route("the second one", "ab2") == "✅ saved"
    assert dl.calls == [{"asin": "B09XYZ0000"}]


# ── deterministic add-artist ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_artist_flow(monkeypatch):
    import src.tools.lidarr as lidarr_mod

    async def fake_lookup(query):
        return [{"artistName": "Radiohead", "foreignArtistId": "mbid-123",
                 "genres": ["rock"]}]

    monkeypatch.setattr(lidarr_mod, "_lookup_artists", fake_lookup)
    add = _patch_tool(monkeypatch, "src.tools.lidarr.add_artist", "✅ added")
    reply = await try_route("add artist Radiohead", "ar1")
    assert "Radiohead" in reply
    assert await try_route("yes", "ar1") == "✅ added"
    assert add.calls == [{"foreign_artist_id": "mbid-123", "name": "Radiohead"}]


# ── deterministic indexer grab flow ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_prowlarr_grab_flow_routes_magnet_to_qbit(monkeypatch):
    import src.tools.prowlarr as prowlarr_mod

    async def fake_search(query, limit=50):
        return [{"title": "Alien 1979 2160p", "indexer": "Idx", "size": 2 << 30,
                 "seeders": 42, "protocol": "torrent",
                 "magnetUrl": "magnet:?xt=urn:btih:alien"}]

    monkeypatch.setattr(prowlarr_mod, "_search_raw", fake_search)

    class QbitConfigured:
        qbittorrent = {"url": "http://qbit:8085"}

    monkeypatch.setattr("src.config.get_settings", lambda: QbitConfigured())
    qb = _patch_tool(monkeypatch, "src.tools.qbittorrent.qbittorrent_add", "✅ queued")
    reply = await try_route("search the indexers for Alien 1979", "px1")
    assert "Alien 1979 2160p" in reply and "42 seeders" in reply
    assert await try_route("yes", "px1") == "✅ queued"
    assert qb.calls == [{"url": "magnet:?xt=urn:btih:alien"}]


@pytest.mark.asyncio
async def test_prowlarr_unconfigured_message():
    reply = await try_route("search the indexers for something", "px2")
    assert "isn't configured" in reply


# ── torrent pause/resume intents ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pause_torrents_needs_qbit():
    reply = await try_route("pause all torrents", "pt1")
    assert "qBittorrent" in reply


# ── domain classifier ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("why does sonarr keep failing to grab episodes of Severance?", "tv_movies"),
    ("compare the seeders on my torrents and tell me which to keep", "downloads"),
    ("recommend an album like this artist's early work", "music"),
    ("which audiobooks have I not finished?", "audiobooks"),
    ("summarize my podcasts", "podcasts"),
    ("which youtube channels upload most often?", "video_online"),
    ("what manga am I missing volumes of?", "books_comics"),
    ("are my snes roms all verified?", "games"),
    ("hello there", None),                       # no domain signal → full agent
    ("show me the movie and the torrent", None),  # two domains tie → full agent
])
def test_domain_classifier(text, expected):
    assert classify(text) == expected


def test_domain_tools_exist_in_registry():
    from src.tools.registry import all_tools
    names = {t.name for t in all_tools}
    for domain in DOMAINS:
        for tool_name in tools_for_domain(domain):
            assert tool_name in names, f"{domain}: unknown tool {tool_name}"
    for core in CORE_TOOLS:
        assert core in names
