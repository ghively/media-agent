"""Tests for the feature wiring pass: new provider intents, quick-reply
suggestions, torrent-client preference, podcast feed parsing, and the
Telegram-adjacent notify path."""
import pytest

from src.graphs import router
from src.graphs.router import pending_suggestions, try_route
from tests.test_router import _patch_tool


# ── new router intents dispatch ──────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("message,dotted", [
    ("list my podcasts", "src.providers.podcast.podcast_list_subscriptions"),
    ("podcast subscriptions", "src.providers.podcast.podcast_list_subscriptions"),
    ("check for new podcast episodes", "src.providers.podcast.podcast_check_new"),
    ("sync podcasts", "src.providers.podcast.podcast_check_new"),
    ("is shroud live?", "src.providers.twitch.twitch_check_live"),
    ("record shroud's stream", "src.providers.twitch.twitch_record"),
    ("show my twitch recordings", "src.providers.twitch.twitch_recordings"),
    ("search comics for One Piece", "src.tools.komga.komga_search"),
    ("recent comics", "src.tools.komga.komga_recent"),
    ("scan the comic library", "src.tools.komga.komga_scan"),
    ("search ebooks for Dune", "src.tools.calibre.calibre_search"),
    ("recent ebooks", "src.tools.calibre.calibre_recent"),
    ("list my artists", "src.tools.lidarr.list_artists"),
    ("music queue", "src.tools.lidarr.get_music_queue"),
    ("search the indexers for Alien 1979", "src.tools.prowlarr.prowlarr_search"),
])
async def test_new_intents_dispatch(monkeypatch, message, dotted):
    fake = _patch_tool(monkeypatch, dotted, "✅ ok")
    reply = await try_route(message, "nf1")
    assert reply == "✅ ok"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_podcast_subscribe_url_passed(monkeypatch):
    sub = _patch_tool(monkeypatch, "src.providers.podcast.podcast_subscribe", "✅ subbed")
    reply = await try_route(
        "subscribe to the podcast https://example.com/feed.xml", "nf2")
    assert reply == "✅ subbed"
    assert sub.calls == [{"feed_url": "https://example.com/feed.xml"}]


@pytest.mark.asyncio
async def test_youtube_subscribe_intent_still_works(monkeypatch):
    """Podcast intents must not swallow the YouTube no-URL subscribe hint."""
    reply = await try_route("subscribe to LinusTechTips", "nf3")
    assert "channel URL" in reply


# ── torrent-client preference ────────────────────────────────────────────────

class _QbitConfigured:
    qbittorrent = {"url": "http://qbit:8085"}


class _QbitAbsent:
    qbittorrent = {}


@pytest.mark.asyncio
async def test_magnet_prefers_qbittorrent(monkeypatch):
    monkeypatch.setattr("src.config.get_settings", lambda: _QbitConfigured())
    qb = _patch_tool(monkeypatch, "src.tools.qbittorrent.qbittorrent_add", "✅ qbit added")
    reply = await try_route("download magnet:?xt=urn:btih:abc123", "m1")
    assert reply == "✅ qbit added"
    assert qb.calls == [{"url": "magnet:?xt=urn:btih:abc123"}]


@pytest.mark.asyncio
async def test_magnet_falls_back_to_download_station(monkeypatch):
    monkeypatch.setattr("src.config.get_settings", lambda: _QbitAbsent())
    ds = _patch_tool(monkeypatch, "src.tools.download_station.download_station_add", "✅ ds added")
    reply = await try_route("download magnet:?xt=urn:btih:abc123", "m2")
    assert reply == "✅ ds added"
    assert ds.calls == [{"url": "magnet:?xt=urn:btih:abc123"}]


# ── quick-reply suggestions ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suggestions_for_yes_no_action(monkeypatch):
    fix = _patch_tool(monkeypatch, "src.tools.library_tools.library_fix_naming", "✅ done")
    await try_route("fix naming in /media/tv", "sg1")
    assert pending_suggestions("sg1") == ["yes", "no"]
    await try_route("yes", "sg1")
    assert pending_suggestions("sg1") is None
    assert fix.calls


@pytest.mark.asyncio
async def test_suggestions_for_numbered_results(monkeypatch):
    async def fake_search(query, media_type):
        return [
            {"title": "Dune", "year": 2021, "source_type": "movie", "id": 1,
             "overview": "", "relevance": 5, "source": "radarr"},
            {"title": "Dune Part Two", "year": 2024, "source_type": "movie",
             "id": 2, "overview": "", "relevance": 4, "source": "radarr"},
        ]

    monkeypatch.setattr(router, "_structured_search", fake_search)
    await try_route("add the movie Dune", "sg2")
    assert pending_suggestions("sg2") == ["yes", "add #2", "no"]


def test_suggestions_none_without_pending():
    assert pending_suggestions("nothing-here") is None


# ── podcast feed parsing ─────────────────────────────────────────────────────

_SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test Cast</title>
  <item>
    <title>Episode 2</title>
    <guid>ep-2</guid>
    <enclosure url="https://cdn.example.com/ep2.mp3" type="audio/mpeg"/>
  </item>
  <item>
    <title>Episode 1</title>
    <guid>ep-1</guid>
    <enclosure url="https://cdn.example.com/ep1.mp3" type="audio/mpeg"/>
  </item>
  <item>
    <title>No audio post</title>
    <guid>ep-0</guid>
  </item>
</channel></rss>"""


def test_podcast_feed_parsing():
    from src.providers.podcast import _parse_feed
    feed = _parse_feed(_SAMPLE_RSS)
    assert feed["title"] == "Test Cast"
    assert [e["guid"] for e in feed["episodes"]] == ["ep-2", "ep-1"]
    assert feed["episodes"][0]["url"].endswith("ep2.mp3")


def test_podcast_feed_rejects_non_rss():
    from src.providers.podcast import _parse_feed
    with pytest.raises(ValueError):
        _parse_feed("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")


# ── twitch channel sanitation ────────────────────────────────────────────────

def test_twitch_channel_cleaning():
    from src.providers.twitch import _clean_channel
    assert _clean_channel("https://twitch.tv/Shroud/") == "shroud"
    assert _clean_channel("shroud") == "shroud"
    assert _clean_channel("bad name!") is None
    assert _clean_channel("--exec=evil") is None


# ── telegram notify kind ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notify_telegram_kind(monkeypatch):
    import src.notify as notify_mod
    from tests.test_fixes import _FakeClient

    class FakeSettings:
        notifications = {"kind": "telegram", "chat_id": "42",
                         "bot_token": "tok123"}
        telegram = {}

    monkeypatch.setattr(notify_mod, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(notify_mod.httpx, "AsyncClient", _FakeClient)
    _FakeClient.sent.clear()
    assert await notify_mod.notify("Report", "All good") is True
    url, kwargs = _FakeClient.sent[0]
    assert "api.telegram.org/bottok123" in url
    assert kwargs["json"]["chat_id"] == "42"
