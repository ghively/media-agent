"""Tests for the deterministic workflow pipelines."""
import asyncio

import pytest

import src.tools.search as search_module
import src.workflows.pipelines as pipelines
from src.tools.arr import ArrClient


# ── verified adds ────────────────────────────────────────────────────────────

class _FakeArr:
    """Patch target for ArrClient._get/_post."""
    def __init__(self):
        self.posted = []
        self.library = []


@pytest.fixture
def fake_arr(monkeypatch, test_settings):
    fake = _FakeArr()

    async def _post(self, endpoint, json_data):
        fake.posted.append((endpoint, json_data))
        return {}

    async def _get(self, endpoint, params=None):
        return fake.library

    monkeypatch.setattr(ArrClient, "_post", _post)
    monkeypatch.setattr(ArrClient, "_get", _get)
    return fake


def test_add_series_verified_success(fake_arr):
    fake_arr.library = [
        {"tvdbId": 371980, "title": "Severance",
         "statistics": {"seasonCount": 2}},
    ]
    result = asyncio.run(pipelines.add_series_verified(371980, "Severance"))
    assert "✅ Verified" in result
    assert "Severance" in result
    assert fake_arr.posted[0][0] == "/series"


def test_add_series_unverified_warns(fake_arr):
    fake_arr.library = []  # POST accepted but show never appears
    result = asyncio.run(pipelines.add_series_verified(1, "Ghost Show"))
    assert result.startswith("⚠️")
    assert "not visible" in result


def test_add_movie_verified_success(fake_arr):
    fake_arr.library = [{"tmdbId": 603, "title": "The Matrix", "hasFile": False}]
    result = asyncio.run(pipelines.add_movie_verified(603, "The Matrix"))
    assert "✅ Verified" in result
    assert "searching for release" in result


# ── grab_media ───────────────────────────────────────────────────────────────

def _mk(title, source_type, id_, relevance, year=2020):
    source = "sonarr" if source_type == "tv" else "radarr"
    return {"title": title, "year": year, "source": source,
            "source_type": source_type, "id": id_, "overview": "",
            "relevance": relevance}


@pytest.fixture
def patched_search(monkeypatch):
    """Patch the per-source searchers grab_media relies on."""
    state = {"tv": [], "movie": []}

    async def fake_sonarr(query, limit):
        return state["tv"]

    async def fake_radarr(query, limit):
        return state["movie"]

    monkeypatch.setattr(search_module, "_search_sonarr", fake_sonarr)
    monkeypatch.setattr(search_module, "_search_radarr", fake_radarr)
    return state


def test_grab_media_decisive_adds_and_verifies(patched_search, monkeypatch):
    patched_search["tv"] = [_mk("Severance", "tv", 371980, 100)]
    added = []

    async def fake_add(tvdb_id, title):
        added.append((tvdb_id, title))
        return f"✅ Verified: '{title}' added."

    monkeypatch.setattr(pipelines, "add_series_verified", fake_add)
    result = asyncio.run(pipelines.grab_media("severance"))
    assert added == [(371980, "Severance")]
    assert "✅ Verified" in result


def test_grab_media_ambiguous_returns_numbered_options(patched_search):
    patched_search["tv"] = [_mk("Heat", "tv", 1, 100)]
    patched_search["movie"] = [_mk("Heat", "movie", 949, 100, 1995)]
    result = asyncio.run(pipelines.grab_media("heat"))
    assert "Multiple matches" in result
    assert "1." in result and "2." in result
    # Options must be cached for download_media(n)
    assert len(search_module._last_results) == 2


def test_grab_media_no_results(patched_search):
    result = asyncio.run(pipelines.grab_media("zzzz no such thing"))
    assert result.startswith("❌")


def test_grab_media_rejects_bad_kind():
    result = asyncio.run(pipelines.grab_media("heat", kind="book"))
    assert "Unknown kind" in result


# ── library_cleanup ──────────────────────────────────────────────────────────

def test_library_cleanup_fixes_and_verifies(tmp_path):
    d = tmp_path / "Heat (1995)"
    d.mkdir()
    (d / "heat.1995.1080p.mkv").write_bytes(b"x")
    result = asyncio.run(pipelines.library_cleanup(str(tmp_path), "movie"))
    assert "Before: 1 issue(s)" in result
    assert "Fixed:  1" in result
    assert "✅ Verified" in result
    assert "library_undo_rename" in result


def test_library_cleanup_already_compliant(tmp_path):
    d = tmp_path / "Heat (1995)"
    d.mkdir()
    (d / "Heat (1995).mkv").write_bytes(b"x")
    result = asyncio.run(pipelines.library_cleanup(str(tmp_path), "movie"))
    assert "✅ Verified" in result and "already comply" in result


def test_library_cleanup_bad_path():
    result = asyncio.run(pipelines.library_cleanup("/no/such/dir", "tv"))
    assert result.startswith("❌")


# ── system_report ────────────────────────────────────────────────────────────

def test_system_report_combines_sections(monkeypatch):
    import src.tools.health as health

    class FakeTool:
        def __init__(self, text):
            self.text = text

        async def ainvoke(self, _):
            return self.text

    monkeypatch.setattr(health, "check_all_health", FakeTool("Sonarr: ✅ healthy"))
    monkeypatch.setattr(health, "check_queue_status", FakeTool("Sonarr queue: 2 item(s)"))
    monkeypatch.setattr(health, "check_disk_space", FakeTool("Disk: 100 GB free"))

    result = asyncio.run(pipelines.system_report())
    assert "── Health ──" in result and "✅ healthy" in result
    assert "── Queues ──" in result and "2 item(s)" in result
    assert "── Disk ──" in result and "100 GB" in result


# ── sync_youtube ─────────────────────────────────────────────────────────────

def test_sync_youtube_downloads_new_and_advances_state(tmp_path, monkeypatch):
    import src.providers.youtube as yt

    subs = [{
        "name": "TestChannel", "url": "https://youtube.com/@test",
        "content_type": "video", "added": "2026-01-01",
        "last_checked": None, "last_upload": "old_vid",
    }]
    saved = {}

    monkeypatch.setattr(yt, "_load_subscriptions", lambda: subs)
    monkeypatch.setattr(yt, "_save_subscriptions", lambda s: saved.update({"subs": s}))

    async def fake_ytdlp(args, timeout=30):
        return 0, "New Video Title|new_vid\n", ""

    async def fake_download(url, content_type):
        assert "new_vid" in url
        return "✅ Verified: downloaded /media/youtube/New Video Title.mkv (10.0 MB)"

    monkeypatch.setattr(yt, "_run_ytdlp", fake_ytdlp)
    monkeypatch.setattr(yt, "download_video", fake_download)

    result = asyncio.run(pipelines.sync_youtube())
    assert "1 download(s)" in result
    assert saved["subs"][0]["last_upload"] == "new_vid"


def test_sync_youtube_failed_download_does_not_advance(monkeypatch):
    import src.providers.youtube as yt

    subs = [{"name": "C", "url": "u", "content_type": "video",
             "last_checked": None, "last_upload": "old_vid"}]
    saved = {}
    monkeypatch.setattr(yt, "_load_subscriptions", lambda: subs)
    monkeypatch.setattr(yt, "_save_subscriptions", lambda s: saved.update({"subs": s}))

    async def fake_ytdlp(args, timeout=30):
        return 0, "T|new_vid\n", ""

    async def fake_download(url, content_type):
        return "❌ yt-dlp failed (exit 1): network error"

    monkeypatch.setattr(yt, "_run_ytdlp", fake_ytdlp)
    monkeypatch.setattr(yt, "download_video", fake_download)

    result = asyncio.run(pipelines.sync_youtube())
    assert "0 download(s)" in result
    # State must NOT advance — the download retries next sync
    assert saved["subs"][0]["last_upload"] == "old_vid"


def test_sync_youtube_first_check_sets_baseline_without_download(monkeypatch):
    import src.providers.youtube as yt

    subs = [{"name": "C", "url": "u", "content_type": "video",
             "last_checked": None, "last_upload": None}]
    saved = {}
    monkeypatch.setattr(yt, "_load_subscriptions", lambda: subs)
    monkeypatch.setattr(yt, "_save_subscriptions", lambda s: saved.update({"subs": s}))

    async def fake_ytdlp(args, timeout=30):
        return 0, "T|vid1\n", ""

    called = []

    async def fake_download(url, content_type):
        called.append(url)
        return "✅"

    monkeypatch.setattr(yt, "_run_ytdlp", fake_ytdlp)
    monkeypatch.setattr(yt, "download_video", fake_download)

    result = asyncio.run(pipelines.sync_youtube())
    assert "baseline set" in result
    assert not called  # no backfill on first check
    assert saved["subs"][0]["last_upload"] == "vid1"
