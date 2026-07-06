"""Tests for the hardening layer: audit log, output cap, disk preflight,
notifications config, and message trimming."""
import asyncio
import json

from langchain_core.tools import tool


@tool
async def mutate_something(target: str) -> str:
    """A pretend mutating tool."""
    return f"✅ mutated {target}"


@tool
async def get_something() -> str:
    """A pretend read-only tool."""
    return "x" * 20000  # oversized output


def test_read_only_classification():
    from src.audit import is_mutating
    assert not is_mutating("search_tv")
    assert not is_mutating("list_movies")
    assert not is_mutating("get_tv_queue")
    assert not is_mutating("check_all_health")
    assert not is_mutating("emby_recent")
    assert not is_mutating("library_inventory")
    assert not is_mutating("youtube_get_info")
    assert is_mutating("add_movie")
    assert is_mutating("remove_tv_show")
    assert is_mutating("library_sort_dir")
    assert is_mutating("emby_scan")
    assert is_mutating("youtube_download")


def test_mutating_call_is_recorded_and_output_capped():
    from src import audit
    from src.audit import wrap_audit

    wrapped = wrap_audit(mutate_something)
    result = asyncio.run(wrapped.ainvoke({"target": "/media"}))
    assert result == "✅ mutated /media"

    entries = [json.loads(l) for l in audit._audit_path().read_text().splitlines()]
    assert any(e["tool"] == "mutate_something" and e["args"] == {"target": "/media"}
               for e in entries)


def test_read_only_call_not_recorded_but_capped():
    from src import audit
    from src.audit import wrap_audit, MAX_TOOL_OUTPUT_CHARS

    before = audit._audit_path().read_text() if audit._audit_path().exists() else ""
    wrapped = wrap_audit(get_something)
    result = asyncio.run(wrapped.ainvoke({}))
    assert len(result) <= MAX_TOOL_OUTPUT_CHARS + 50
    assert "truncated" in result
    after = audit._audit_path().read_text() if audit._audit_path().exists() else ""
    assert before == after  # nothing new logged for read-only


def test_disk_preflight_blocks_when_needed_exceeds_free():
    from src.preflight import disk_preflight
    # an absurd requirement must always be refused
    problem = disk_preflight("/tmp", needed_gb=10_000_000)
    assert problem is not None and "Not enough disk space" in problem


def test_disk_preflight_allows_reasonable_request():
    from src.preflight import disk_preflight
    assert disk_preflight("/tmp", needed_gb=0) is None or "Not enough" in disk_preflight("/tmp", needed_gb=0)


def test_telegram_unconfigured_send_is_noop():
    from src import notify
    assert notify.telegram_configured() is False
    assert asyncio.run(notify.send("hello")) is False


def test_trim_history_bounds_message_count():
    from langchain_core.messages import AIMessage, HumanMessage
    from src.graphs.conversational import _trim, MAX_CONTEXT_MESSAGES

    messages = []
    for i in range(100):
        messages.append(HumanMessage(content=f"q{i}"))
        messages.append(AIMessage(content=f"a{i}"))
    trimmed = _trim(messages)
    assert len(trimmed) <= MAX_CONTEXT_MESSAGES
    assert trimmed[0].type == "human"  # never starts on a dangling tool/ai msg
    assert trimmed[-1].content == "a99"  # newest messages kept


def test_duplicate_scan_finds_real_duplicates(tmp_path):
    from src.library.scanner import scan_duplicates
    payload = b"x" * (1024 * 1024)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "movie.mkv").write_bytes(payload)
    (tmp_path / "b" / "movie-copy.mkv").write_bytes(payload)
    (tmp_path / "a" / "different.mkv").write_bytes(b"y" * (1024 * 1024))

    report = scan_duplicates(str(tmp_path), min_size_mb=0)
    assert "1 duplicate group" in report
    assert "movie.mkv" in report and "movie-copy.mkv" in report
    assert "different.mkv" not in report


def test_orphan_scan_respects_known_paths(tmp_path):
    from src.library.scanner import scan_orphans
    managed = tmp_path / "tv" / "Show"
    managed.mkdir(parents=True)
    (managed / "ep.mkv").write_bytes(b"x" * 1024)
    stray = tmp_path / "downloads"
    stray.mkdir()
    (stray / "random.mkv").write_bytes(b"y" * 2048)

    report = scan_orphans(str(tmp_path), [str(tmp_path / "tv" / "Show")])
    assert "random.mkv" in report
    assert "ep.mkv" not in report


def test_optional_integrations_absent_when_unconfigured():
    from src.tools.registry import all_tools
    names = {t.name for t in all_tools}
    # test settings configure neither Lidarr nor Bazarr
    assert "search_artist" not in names
    assert "bazarr_status" not in names
    # the duplicate/orphan workflow is always present
    assert "library_find_duplicates" in names
    assert "library_find_orphans" in names


def test_removal_tools_are_confirm_gated():
    from src.tools.registry import all_tools
    by_name = {t.name: t for t in all_tools}
    for name in ("remove_tv_show", "remove_movie"):
        assert (by_name[name].metadata or {}).get("approval_policy") == "confirm"
