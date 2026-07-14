"""Tests for the request/approval loop, quotas, cleanup engine, and rules.

No live services: Sonarr/Radarr/Emby/Telegram are faked; the SQLite store
runs against the tmp MEDIA_AGENT_STATE_DIR from conftest.
"""
import pytest

from src import store
from src.engine.rules import describe_rule, evaluate_auto_approve, rule_matches
from src.graphs.router import _extract_season, try_route


class FakeTool:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict) -> str:
        self.calls.append(args)
        return self.reply


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    """Point the store at a per-test database."""
    monkeypatch.setenv("MEDIA_AGENT_STATE_DIR", str(tmp_path))
    yield


def _enable_roles(monkeypatch, admins=("111",), names=None, limit=None, overrides=None):
    cfg = {"admins": list(admins), "names": names or {},
           "request_limit": limit or {"count": 5, "days": 7},
           "overrides": overrides or {}}
    monkeypatch.setattr("src.users._users_cfg", lambda: cfg)


async def _silence_notify(monkeypatch):
    async def _noop(*a, **k):
        return True
    monkeypatch.setattr("src.notify.notify_admins", _noop)
    monkeypatch.setattr("src.notify.notify_chat", _noop)
    monkeypatch.setattr("src.notify.notify", _noop)


# ── season extraction ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,query,season", [
    ("Severance season 2", "Severance", 2),
    ("severance s2", "severance", 2),
    ("The Wire season 4", "The Wire", 4),
    ("Dune", "Dune", None),
    ("season 2", "season 2", None),   # nothing left after stripping → no scope
])
def test_extract_season(text, query, season):
    assert _extract_season(text) == (query, season)


# ── store ────────────────────────────────────────────────────────────────────

async def test_store_request_lifecycle():
    rid = await store.add_request("999", "Severance", "tv", 371980, season=2)
    req = await store.get_request(rid)
    assert req["status"] == "pending" and req["season"] == 2

    assert await store.set_request_status(rid, "approved", decided_by="111")
    assert (await store.get_request(rid))["status"] == "approved"
    assert [r["id"] for r in await store.awaiting_availability()] == [rid]

    dupe = await store.find_duplicate_request(371980, "tv")
    assert dupe and dupe["id"] == rid
    assert await store.find_duplicate_request(371980, "movie") is None


async def test_store_quota_counts_exclude_denied():
    for i in range(3):
        await store.add_request("999", f"Show {i}", "tv", i)
    denied = await store.add_request("999", "Bad One", "tv", 99)
    await store.set_request_status(denied, "denied")
    assert await store.count_recent_requests("999", days=7) == 3
    assert await store.count_recent_requests("someone-else", days=7) == 0


async def test_store_quarantine_and_rules():
    qid = await store.quarantine_add("movie", 42, "Dune", "delete", "manual", 7)
    assert (await store.quarantine_find("dune"))["id"] == qid
    assert await store.quarantine_due() == []          # grace not elapsed
    assert (await store.quarantine_due(now=10**12))[0]["id"] == qid
    await store.quarantine_set_status(qid, "reprieved")
    assert await store.quarantine_find("dune") is None

    rule_id = await store.rule_add("auto_approve", {"media_type": "movie"},
                                   {"approve": True})
    rules = await store.rules_list(kind="auto_approve")
    assert rules[0]["conditions"] == {"media_type": "movie"}
    assert await store.rule_remove(rule_id)
    assert await store.rules_list(kind="auto_approve") == []


# ── rule evaluation ──────────────────────────────────────────────────────────

def test_rule_matching():
    request = {"requester": "999", "requester_name": "alice",
               "media_type": "tv", "title": "Frieren", "year": 2023,
               "season_count": 1, "genres": ["Animation", "Anime"]}
    assert rule_matches({"requester": "Alice"}, request)
    assert rule_matches({"max_seasons": 3, "media_type": "tv"}, request)
    assert rule_matches({"genre": "anime"}, request)
    assert rule_matches({"min_year": 2020, "max_year": 2024}, request)
    assert not rule_matches({"max_seasons": 3}, {**request, "season_count": None})
    assert not rule_matches({"requester": "bob"}, request)
    assert not rule_matches({"unknown_key": 1}, request)  # fail safe

    rules = [
        {"kind": "auto_approve", "conditions": {"requester": "bob"},
         "actions": {"approve": True}},
        {"kind": "auto_approve", "conditions": {"genre": "anime"},
         "actions": {"approve": True, "root_folder": "/media/anime"}},
    ]
    actions = evaluate_auto_approve(rules, request)
    assert actions == {"approve": True, "root_folder": "/media/anime"}
    assert evaluate_auto_approve(rules, {**request, "genres": [],
                                         "requester_name": "carol",
                                         "requester": "1"}) is None


def test_describe_rule():
    text = describe_rule({"id": 3, "kind": "auto_approve",
                          "conditions": {"genre": "anime"},
                          "actions": {"approve": True, "root_folder": "/a"}})
    assert "#3" in text and "anime" in text and "auto-approve" in text


# ── roles ────────────────────────────────────────────────────────────────────

def test_roles_default_off_and_gating(monkeypatch):
    from src import users
    assert users.is_admin("tg-42")            # no admins configured → all admin
    _enable_roles(monkeypatch, admins=("111",),
                  overrides={"999": {"count": 10}})
    assert users.is_admin("tg-111")
    assert not users.is_admin("tg-999")
    assert users.is_admin("dash-1")           # local interfaces stay admin
    assert users.request_limit_for("999") == (10, 7)
    assert users.request_limit_for("888") == (5, 7)


# ── create_request: quota + auto-approve ─────────────────────────────────────

async def test_create_request_pending_and_quota(monkeypatch):
    await _silence_notify(monkeypatch)
    _enable_roles(monkeypatch, limit={"count": 1, "days": 7})
    from src.tools.requests_tools import create_request

    result = {"title": "Severance", "source_type": "tv", "id": 371980,
              "year": 2022, "season_count": 2, "genres": ["Drama"]}
    reply = await create_request("999", result, season=2)
    assert "Request #1 submitted" in reply and "season 2" in reply

    # Duplicate is reported, not re-queued (and doesn't burn quota).
    assert "already pending" in await create_request("888", result)

    # Quota of 1 is now spent for user 999.
    other = {"title": "Dune", "source_type": "movie", "id": 438631}
    assert "used all 1 requests" in await create_request("999", other)


async def test_create_request_auto_approved_by_rule(monkeypatch):
    await _silence_notify(monkeypatch)
    _enable_roles(monkeypatch, names={"999": "alice"})
    executed = {}

    async def fake_execute(req, overrides=None):
        executed.update(req=req, overrides=overrides)
        return "✅ Added 'Frieren' to Sonarr."
    monkeypatch.setattr("src.tools.requests_tools._execute_add", fake_execute)

    await store.rule_add("auto_approve", {"requester": "alice"},
                         {"approve": True, "root_folder": "/media/anime"})
    result = {"title": "Frieren", "source_type": "tv", "id": 1, "year": 2023}
    reply = await create_request_via_module("999", result)
    assert "auto-approved" in reply
    assert executed["overrides"]["root_folder"] == "/media/anime"
    assert (await store.get_request(1))["status"] == "approved"


async def create_request_via_module(requester, result, season=None):
    from src.tools.requests_tools import create_request
    return await create_request(requester, result, season)


# ── approve / deny ───────────────────────────────────────────────────────────

async def test_approve_and_deny(monkeypatch):
    await _silence_notify(monkeypatch)
    added = {}

    async def fake_execute(req, overrides=None):
        added.update(req=req)
        return "✅ Added."
    monkeypatch.setattr("src.tools.requests_tools._execute_add", fake_execute)
    from src.tools.requests_tools import approve, deny

    rid = await store.add_request("999", "Severance", "tv", 371980)
    reply = await approve(rid, decided_by="tg-111")
    assert "Approved request" in reply and added["req"]["title"] == "Severance"
    assert "already approved" in await approve(rid, decided_by="tg-111")

    rid2 = await store.add_request("999", "Junk", "movie", 5)
    reply = await deny(rid2, decided_by="tg-111", reason="not this one")
    assert "Denied" in reply and "not this one" in reply
    assert "No request #777" in await approve(777, decided_by="x")


# ── router intents ───────────────────────────────────────────────────────────

async def test_router_request_intents(monkeypatch):
    await _silence_notify(monkeypatch)
    _enable_roles(monkeypatch)
    rid = await store.add_request("999", "Severance", "tv", 371980)

    reply = await try_route("list requests", "tg-111")
    assert "Severance" in reply and "pending" in reply

    # Non-admin can't decide; admin can.
    assert "Only admins" in await try_route(f"approve #{rid}", "tg-999")

    async def fake_execute(req, overrides=None):
        return "✅ Added."
    monkeypatch.setattr("src.tools.requests_tools._execute_add", fake_execute)
    reply = await try_route(f"approve #{rid}", "tg-111")
    assert "Approved request" in reply

    reply = await try_route("my requests", "tg-999")
    assert "Severance" in reply and "Quota" in reply


async def test_router_nonadmin_add_becomes_request(monkeypatch):
    await _silence_notify(monkeypatch)
    _enable_roles(monkeypatch)

    async def fake_search(query, media_type):
        return [{"title": "Severance", "year": 2022, "source": "sonarr",
                 "source_type": "tv", "id": 371980, "overview": "",
                 "relevance": 3, "season_count": 2, "genres": []}]
    monkeypatch.setattr("src.graphs.router._structured_search", fake_search)

    reply = await try_route("add severance season 2", "tg-999")
    assert "Found 1 match" in reply
    reply = await try_route("yes", "tg-999")
    assert "Request #1 submitted" in reply and "season 2" in reply
    assert (await store.get_request(1))["season"] == 2


async def test_router_admin_add_stays_direct(monkeypatch):
    fake_add = FakeTool("✅ Added 'Severance' (season 2 only).")
    monkeypatch.setattr("src.tools.sonarr.add_tv_show", fake_add)

    async def fake_search(query, media_type):
        assert media_type == "tv"   # a season scope implies a show
        return [{"title": "Severance", "year": 2022, "source": "sonarr",
                 "source_type": "tv", "id": 371980, "overview": "",
                 "relevance": 3}]
    monkeypatch.setattr("src.graphs.router._structured_search", fake_search)

    await try_route("add severance season 2", "cli")
    reply = await try_route("yes", "cli")
    assert "✅" in reply
    assert fake_add.calls == [{"tvdb_id": 371980, "title": "Severance",
                               "season": 2}]


async def test_router_cleanup_intents(monkeypatch):
    await _silence_notify(monkeypatch)

    found = {"kind": "movie", "arr_id": 42, "title": "Dune"}

    async def fake_find(title):
        return found
    monkeypatch.setattr("src.tools.cleanup_tools._find_in_arr", fake_find)

    async def fake_leaving(title):
        return None
    monkeypatch.setattr("src.tools.cleanup_tools._emby_leaving_soon", fake_leaving)

    reply = await try_route("delete Dune in 14 days", "cli")
    assert "confirm" in reply.lower() or "yes/no" in reply
    reply = await try_route("yes", "cli")
    assert "'Dune' will be deleted in 14 day(s)" in reply

    reply = await try_route("what's leaving soon?", "cli")
    assert "Dune" in reply

    # "keep X" reprieves a quarantined title...
    reply = await try_route("keep Dune", "cli")
    assert "Kept 'Dune'" in reply
    # ...but unrelated "keep" phrasing falls through to the LLM.
    assert await try_route("keep me posted", "cli") is None


async def test_router_retention_and_rules(monkeypatch):
    await _silence_notify(monkeypatch)

    reply = await try_route("keep the newest 10 episodes of NewsShow", "cli")
    assert "confirm" in reply.lower()
    reply = await try_route("yes", "cli")
    assert "Retention rule" in reply
    rules = await store.rules_list(kind="retention")
    assert rules[0]["actions"]["keep_last"] == 10

    reply = await try_route("auto-approve anything under 3 seasons", "cli")
    reply = await try_route("yes", "cli")
    assert "Added rule" in reply
    reply = await try_route("always send anime to /media/anime", "cli")
    reply = await try_route("yes", "cli")
    assert "/media/anime" in reply

    listing = await try_route("list rules", "cli")
    assert "retention" in listing and "auto_approve" in listing

    rule_id = (await store.rules_list())[0]["id"]
    reply = await try_route(f"remove rule #{rule_id}", "cli")
    assert "Removed rule" in reply


# ── fail-safe invariants ─────────────────────────────────────────────────────

async def test_schedule_cleanup_failsafe_when_arr_down(monkeypatch):
    async def broken_find(title):
        raise ConnectionError("down")
    monkeypatch.setattr("src.tools.cleanup_tools._find_in_arr", broken_find)
    from src.tools.cleanup_tools import schedule_cleanup
    reply = await schedule_cleanup("Dune", 7)
    assert "nothing was scheduled" in reply
    assert await store.quarantine_list() == []


async def test_sweep_skips_unreachable_items(monkeypatch):
    await _silence_notify(monkeypatch)
    qid = await store.quarantine_add("movie", 42, "Dune", "delete", "manual", 0)

    async def broken_action(item):
        raise ConnectionError("down")
    monkeypatch.setattr("src.tools.cleanup_tools._execute_action", broken_action)
    from src.tools.cleanup_tools import run_sweep
    report = await run_sweep()
    assert "skipped 'Dune'" in report
    # Still quarantined — it will be retried next sweep, never lost.
    assert (await store.quarantine_list())[0]["id"] == qid

    async def ok_action(item):
        return f"deleted '{item['title']}'"
    monkeypatch.setattr("src.tools.cleanup_tools._execute_action", ok_action)
    report = await run_sweep()
    assert "deleted 'Dune'" in report
    assert await store.quarantine_list() == []


async def test_availability_sweep(monkeypatch):
    notified = []

    async def fake_notify_chat(chat_id, title, message):
        notified.append((chat_id, message))
        return True
    monkeypatch.setattr("src.notify.notify_chat", fake_notify_chat)

    rid = await store.add_request("999", "Severance", "tv", 371980)
    await store.set_request_status(rid, "approved")
    from src.tools import requests_tools

    # Emby down → unknown state, request stays approved.
    async def broken_emby(title, media_type):
        raise ConnectionError("down")
    monkeypatch.setattr(requests_tools, "_emby_has", broken_emby)
    await requests_tools.check_availability()
    assert (await store.get_request(rid))["status"] == "approved"

    async def emby_has(title, media_type):
        return True
    monkeypatch.setattr(requests_tools, "_emby_has", emby_has)
    result = await requests_tools.check_availability()
    assert "1 of 1" in result
    assert (await store.get_request(rid))["status"] == "available"
    assert notified and notified[0][0] == "999"
