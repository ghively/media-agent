"""Media-agent PoC: tool loading, approval gate and optional Jev routing."""

import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from oiui_agent import media_bridge as mb


def _approval(cid, tool, args, summary="do it"):
    return {"id": cid, "name": mb.APPROVAL_TOOL,
            "args": {"tool": tool, "argsJson": json.dumps(args), "summary": summary}}


def _call(cid, name, args):
    return {"id": cid, "name": name, "args": args}


ADD = {"tmdb_id": 603, "title": "The Matrix"}


def _gate(messages, call):
    request = SimpleNamespace(tool_call=call, tool=None, state={"messages": messages})
    ran = []

    def handler(req):
        ran.append(req.tool_call["name"])
        return ToolMessage(content="✅ Added", tool_call_id=req.tool_call["id"])

    result = mb.MediaApprovalMiddleware().wrap_tool_call(request, handler)
    return result, ran


def test_media_tools_load():
    names = {t.name for t in mb.load_media_tools()}
    assert {"add_movie", "check_queue_status", "sabnzbd_queue"} <= names
    assert len(names) >= 90


def test_every_gated_tool_exists_in_media_agent():
    names = {t.name for t in mb.load_media_tools()}
    assert (mb.ALWAYS_GATED | mb.GATED_WHEN_CONFIRMED) <= names


def test_read_only_tools_pass_without_approval():
    call = _call("c1", "check_queue_status", {})
    result, ran = _gate([HumanMessage("what's downloading?"), AIMessage("", tool_calls=[call])], call)
    assert ran == ["check_queue_status"]


def test_add_without_approval_is_refused():
    call = _call("c1", "add_movie", ADD)
    result, ran = _gate([HumanMessage("add the matrix"), AIMessage("", tool_calls=[call])], call)
    assert ran == []
    assert result.content.startswith("⛔") and mb.APPROVAL_TOOL in result.content


def test_add_after_approve_click_runs_once():
    approve = _approval("a1", "add_movie", ADD)
    call = _call("c1", "add_movie", ADD)
    msgs = [HumanMessage("add the matrix"), AIMessage("", tool_calls=[approve]),
            ToolMessage("APPROVED", tool_call_id="a1"), AIMessage("", tool_calls=[call])]
    _, ran = _gate(msgs, call)
    assert ran == ["add_movie"]

    # Same approval can't pay for a second identical add.
    msgs += [ToolMessage("✅ Added", tool_call_id="c1")]
    again = _call("c2", "add_movie", ADD)
    _, ran = _gate(msgs + [AIMessage("", tool_calls=[again])], again)
    assert ran == []


def test_declined_or_mismatched_approval_is_refused():
    call = _call("c1", "add_movie", ADD)
    declined = [HumanMessage("add"), AIMessage("", tool_calls=[_approval("a1", "add_movie", ADD)]),
                ToolMessage("DECLINED", tool_call_id="a1"), AIMessage("", tool_calls=[call])]
    assert _gate(declined, call)[1] == []

    other = {"tmdb_id": 999, "title": "Something else"}
    mismatch = [HumanMessage("add"), AIMessage("", tool_calls=[_approval("a1", "add_movie", other)]),
                ToolMessage("APPROVED", tool_call_id="a1"), AIMessage("", tool_calls=[call])]
    assert _gate(mismatch, call)[1] == []


def test_approval_from_an_earlier_turn_does_not_count():
    call = _call("c1", "add_movie", ADD)
    msgs = [HumanMessage("add"), AIMessage("", tool_calls=[_approval("a1", "add_movie", ADD)]),
            ToolMessage("APPROVED", tool_call_id="a1"), AIMessage("ok"),
            HumanMessage("now add it"), AIMessage("", tool_calls=[call])]
    assert _gate(msgs, call)[1] == []


def test_bulk_preview_is_free_but_confirmed_run_is_gated():
    preview = _call("c1", "rom_download", {"identifier": "nes-set", "confirm": False})
    assert _gate([HumanMessage("get the nes set"), AIMessage("", tool_calls=[preview])], preview)[1] == ["rom_download"]
    run = _call("c2", "rom_download", {"identifier": "nes-set", "confirm": True})
    assert _gate([HumanMessage("yes"), AIMessage("", tool_calls=[run])], run)[1] == []


def test_defaults_count_as_matching_args():
    assert mb.args_match({"url": "x"}, {"url": "x", "category": ""}, {"category": ""})
    assert not mb.args_match({"url": "x"}, {"url": "y"})


def test_data_tools_report_errors_instead_of_raising(monkeypatch, tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        "services:\n"
        "  sonarr: {url: 'http://127.0.0.1:9', api_key: k}\n"
        "  radarr: {url: 'http://127.0.0.1:9', api_key: k}\n"
        "  emby: {url: 'http://127.0.0.1:9', api_key: k}\n"
        "  sabnzbd: {url: 'http://127.0.0.1:9', api_key: k}\n"
    )
    monkeypatch.setenv("MEDIA_AGENT_CONFIG", str(cfg))
    import src.config as config
    for attr in ("_settings", "_instance"):
        if hasattr(config, attr):
            monkeypatch.setattr(config, attr, None)
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()

    disk = json.loads(asyncio.run(mb.media_disk_usage_data.ainvoke({})))
    assert "error" in disk
    queue = json.loads(asyncio.run(mb.media_download_queue_data.ainvoke({})))
    assert queue["items"] == [] and queue["errors"]
    health = json.loads(asyncio.run(mb.media_service_health_data.ainvoke({})))
    assert [s["ok"] for s in health["services"]] == [False, False, False]


def test_jev_is_skipped_without_a_typesafe_key(monkeypatch):
    from oiui_agent import visualization_router as vr

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert vr.jev_enabled() is False
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    assert vr.jev_enabled() is True
    monkeypatch.setenv("JEV_ROUTING", "off")
    assert vr.jev_enabled() is False


def test_real_graph_refuses_unapproved_add(monkeypatch):
    """Through the actual main.agent graph: an unapproved add never runs."""
    import importlib
    import sys
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    import oiui_agent.model

    class ToolCapableFakeModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(oiui_agent.model, "build_model", lambda **kwargs: ToolCapableFakeModel(
        responses=[AIMessage("", tool_calls=[_call("c1", "add_movie", ADD)]), AIMessage("ok")],
    ))
    sys.modules.pop("main", None)
    try:
        main = importlib.import_module("main")
        config = {"configurable": {"thread_id": "gate-test"}}
        main.agent.invoke({"messages": [HumanMessage("add the matrix")]}, config)
        msgs = main.agent.get_state(config).values["messages"]
        result = next(m for m in msgs if isinstance(m, ToolMessage) and m.tool_call_id == "c1")
        assert result.content.startswith("⛔ Not run: add_movie")
    finally:
        sys.modules.pop("main", None)
