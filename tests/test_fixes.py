"""Tests for the production-readiness fixes.

Covers: config substitution + validation, SABnzbd secret scrubbing, the
confirm= gates on destructive tools, the router's command-noun stoplist,
the stateless API's stable router thread, dashboard session threads, the
naming fix/undo round trip, and the notify module's payload dispatch.
"""
import json

import pytest

from src.graphs.router import try_route


# ── config ───────────────────────────────────────────────────────────────────

def test_env_substitution_unset_becomes_empty(monkeypatch):
    from src.config import _substitute_env
    monkeypatch.delenv("MA_TEST_UNSET", raising=False)
    monkeypatch.setenv("MA_TEST_SET", "value123")
    assert _substitute_env("${MA_TEST_UNSET}") == ""
    assert _substitute_env("${MA_TEST_SET}") == "value123"
    assert _substitute_env({"k": ["${MA_TEST_SET}"]}) == {"k": ["value123"]}


def test_validate_names_missing_credentials(tmp_path, monkeypatch):
    from src.config import Settings
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        "server: {api_key: ''}\n"
        "services:\n"
        "  sonarr: {url: 'http://x:1', api_key: ''}\n"
        "  download_station: {url: 'http://x:1', username: '', password: ''}\n"
    )
    warnings = Settings(str(cfg)).validate()
    joined = "\n".join(warnings)
    assert "sonarr" in joined
    assert "download_station" in joined
    assert "WITHOUT authentication" in joined


def test_validate_quiet_when_configured(tmp_path):
    from src.config import Settings
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        "server: {api_key: 'k'}\n"
        "services:\n"
        "  sonarr: {url: 'http://x:1', api_key: 'abc'}\n"
    )
    assert Settings(str(cfg)).validate() == []


# ── SABnzbd secret hygiene ───────────────────────────────────────────────────

def test_sabnzbd_scrub_removes_long_keys(monkeypatch):
    from src.tools import sabnzbd

    class FakeSettings:
        sabnzbd = {"api_key": "deadbeefcafe1234"}

    monkeypatch.setattr(sabnzbd, "get_settings", lambda: FakeSettings())
    msg = "error for url http://nas/api?apikey=deadbeefcafe1234&mode=queue"
    assert "deadbeefcafe1234" not in sabnzbd._scrub(msg)
    assert "***" in sabnzbd._scrub(msg)


def test_sabnzbd_scrub_leaves_short_keys_alone(monkeypatch):
    from src.tools import sabnzbd

    class FakeSettings:
        sabnzbd = {"api_key": "x"}

    monkeypatch.setattr(sabnzbd, "get_settings", lambda: FakeSettings())
    assert sabnzbd._scrub("extra text") == "extra text"


def test_sabnzbd_http_error_has_no_url():
    import httpx
    from src.tools.sabnzbd import SabnzbdClient, SabnzbdError

    resp = httpx.Response(
        status_code=403,
        request=httpx.Request("GET", "http://nas/api?apikey=SECRETSECRET"),
    )
    with pytest.raises(SabnzbdError) as exc_info:
        SabnzbdClient._checked_json(resp)
    assert "SECRETSECRET" not in str(exc_info.value)
    assert "403" in str(exc_info.value)


# ── confirm= gates on destructive tools ──────────────────────────────────────

@pytest.mark.asyncio
async def test_bandcamp_collection_previews_without_confirm():
    from src.providers.bandcamp import bandcamp_download_collection
    reply = await bandcamp_download_collection.ainvoke({"confirm": False})
    assert reply.startswith("⏸️")
    assert "confirm=true" in reply


@pytest.mark.asyncio
async def test_rom_download_previews_without_confirm(monkeypatch):
    from src.providers import rom as rom_mod

    monkeypatch.setattr(
        rom_mod, "_item_info_sync",
        lambda identifier: {"title": "SNES Set", "size_gb": 12.3})

    def _boom(*a, **k):
        raise AssertionError("download must not run without confirm")

    monkeypatch.setattr(rom_mod, "_download_sync", _boom)
    reply = await rom_mod.rom_download.ainvoke({"identifier": "abc"})
    assert reply.startswith("⏸️")
    assert "12.3 GB" in reply


@pytest.mark.asyncio
async def test_fix_naming_tool_previews_without_confirm(monkeypatch, tmp_path):
    """confirm=False must never reach the renaming function."""
    import src.tools.library_tools as lt

    def _boom(*a, **k):
        raise AssertionError("fix must not run without confirm")

    monkeypatch.setattr(lt, "_fix_naming", _boom)
    monkeypatch.setattr(lt, "_check_naming", lambda p, c: "3 issues found")
    # /tmp is the test media_root (conftest), so tmp_path is confined-OK.
    reply = await lt.library_fix_naming.ainvoke(
        {"path": str(tmp_path), "convention": "movie"})
    assert "⏸️" in reply and "3 issues found" in reply and "confirm=true" in reply


# ── naming fix + undo round trip ─────────────────────────────────────────────

def test_fix_naming_then_undo_restores_tree(tmp_path):
    from src.library.naming import fix_naming, undo_rename

    movie_dir = tmp_path / "Old Movie (1999)"
    movie_dir.mkdir()
    original = movie_dir / "oldmovie.mkv"
    original.write_bytes(b"data")

    report = fix_naming(str(tmp_path), "movie")
    fixed = movie_dir / "Old Movie (1999).mkv"
    assert fixed.exists() and not original.exists(), report

    undo_logs = list((tmp_path / ".media_agent_undo").glob("undo_*.json"))
    assert len(undo_logs) == 1
    entries = json.loads(undo_logs[0].read_text())
    assert entries[0]["old"].endswith("oldmovie.mkv")

    undo_report = undo_rename(str(undo_logs[0]))
    assert original.exists() and not fixed.exists(), undo_report


# ── router command-noun stoplist ─────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "get the tv calendar",
    "download the queue",
    "grab my history",
    "add the collection",
])
async def test_command_nouns_fall_through_to_llm(message):
    assert await try_route(message, "sl1") is None


# ── stateless API: stable router thread ──────────────────────────────────────

def test_router_thread_id_stable_across_history_growth():
    from src.interfaces.openai_api import ChatMessage, _router_thread_id

    convo1 = [ChatMessage(role="user", content="add Dune")]
    convo2 = convo1 + [
        ChatMessage(role="assistant", content="Found 2. Which one?"),
        ChatMessage(role="user", content="the first one"),
    ]
    assert _router_thread_id(convo1) == _router_thread_id(convo2)
    other = [ChatMessage(role="user", content="add Alien")]
    assert _router_thread_id(convo1) != _router_thread_id(other)


# ── dashboard session threads ────────────────────────────────────────────────

def test_dashboard_thread_for_sessions():
    from src.interfaces.dashboard import _thread_for
    assert _thread_for("abcd1234abcd1234") == "dashboard-abcd1234abcd1234"
    # Junk or missing session ids collapse to the shared legacy thread.
    assert _thread_for(None) == "dashboard"
    assert _thread_for("short") == "dashboard"
    assert _thread_for("../../etc/passwd") == "dashboard"
    assert _thread_for("x" * 200) == "dashboard"


# ── notify ───────────────────────────────────────────────────────────────────

class _FakeResponse:
    def raise_for_status(self):
        pass


class _FakeClient:
    sent: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        _FakeClient.sent.append((url, kwargs))
        return _FakeResponse()


@pytest.mark.asyncio
async def test_notify_disabled_without_url():
    from src.notify import notify
    assert await notify("t", "m") is False


@pytest.mark.asyncio
async def test_notify_dispatches_by_kind(monkeypatch):
    import src.notify as notify_mod

    class FakeSettings:
        notifications = {"url": "http://ntfy/topic", "kind": "discord"}

    monkeypatch.setattr(notify_mod, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(notify_mod.httpx, "AsyncClient", _FakeClient)
    _FakeClient.sent.clear()
    assert await notify_mod.notify("Title", "Body") is True
    url, kwargs = _FakeClient.sent[0]
    assert kwargs["json"]["content"].startswith("**Title**")


# ── emby item id validation ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emby_get_item_rejects_path_traversal():
    from src.tools.emby import emby_get_item
    reply = await emby_get_item.ainvoke({"item_id": "../System/Info"})
    assert reply.startswith("❌")
    assert "not a valid" in reply
