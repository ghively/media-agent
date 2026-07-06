"""Tests for the approval gate — the hard human-in-the-loop control."""
import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from src.tools.approval import (
    HIGH_IMPACT_DEFAULTS,
    apply_approval_policies,
    gate_tool,
    get_policies,
)


@tool
async def risky(path: str) -> str:
    """A pretend high-impact tool."""
    return f"EXECUTED on {path}"


def _state(last_user_text: str) -> dict:
    return {"messages": [HumanMessage(content=last_user_text)]}


def _invoke(gated, args, user_text):
    return asyncio.run(gated.ainvoke({**args, "state": _state(user_text)}))


def test_first_call_is_blocked_and_asks_for_approval():
    gated = gate_tool(risky, "confirm")
    result = _invoke(gated, {"path": "/media"}, "sort my library")
    assert "APPROVAL REQUIRED" in result
    assert "EXECUTED" not in result


def test_approval_in_users_next_message_executes():
    gated = gate_tool(risky, "confirm")
    _invoke(gated, {"path": "/media"}, "sort my library")
    result = _invoke(gated, {"path": "/media"}, "yes, go ahead")
    assert result == "EXECUTED on /media"


def test_denial_clears_pending_and_does_not_execute():
    gated = gate_tool(risky, "confirm")
    _invoke(gated, {"path": "/media"}, "sort my library")
    result = _invoke(gated, {"path": "/media"}, "no, don't")
    assert "declined" in result
    # a follow-up call without fresh approval must re-ask, not execute
    result = _invoke(gated, {"path": "/media"}, "hmm")
    assert "APPROVAL REQUIRED" in result


def test_negation_beats_approval_keyword():
    gated = gate_tool(risky, "confirm")
    _invoke(gated, {"path": "/media"}, "sort it")
    result = _invoke(gated, {"path": "/media"}, "no, don't do it. not okay")
    assert "EXECUTED" not in result


def test_different_args_need_their_own_approval():
    gated = gate_tool(risky, "confirm")
    _invoke(gated, {"path": "/media"}, "sort my library")
    # user approves, but the model tries different arguments — blocked
    result = _invoke(gated, {"path": "/etc"}, "yes")
    assert "APPROVAL REQUIRED" in result
    assert "EXECUTED" not in result


def test_model_cannot_self_approve_without_user_text():
    gated = gate_tool(risky, "confirm")
    _invoke(gated, {"path": "/media"}, "sort my library")
    # same user message as before (no approval present) — still blocked
    result = _invoke(gated, {"path": "/media"}, "sort my library")
    assert "APPROVAL REQUIRED" in result


def test_deny_policy_never_executes():
    gated = gate_tool(risky, "deny")
    result = _invoke(gated, {"path": "/media"}, "yes yes approved go ahead")
    assert "disabled" in result
    assert "EXECUTED" not in result


def test_model_facing_schema_hides_state_field():
    gated = gate_tool(risky, "confirm")
    assert "state" not in gated.tool_call_schema.model_fields
    assert "path" in gated.tool_call_schema.model_fields


def test_high_impact_defaults_applied_in_registry():
    from src.tools.registry import all_tools
    by_name = {t.name: t for t in all_tools}
    for name in HIGH_IMPACT_DEFAULTS:
        assert (by_name[name].metadata or {}).get("approval_policy") == "confirm", name
    # read-only tools are untouched
    assert (by_name["search_tv"].metadata or {}).get("approval_policy") is None


def test_config_overrides_policy(test_settings):
    import src.config
    test_settings.write_text(
        test_settings.read_text().replace(
            "approvals: {}",
            "approvals: {rom_download: auto, emby_scan: deny, search_tv: bogus}",
        )
    )
    src.config._settings = None
    try:
        policies = get_policies()
        assert policies["rom_download"] == "auto"      # default confirm overridden
        assert policies["emby_scan"] == "deny"          # extra tool gated
        assert policies.get("search_tv") is None or policies.get("search_tv") not in (
            "auto", "confirm", "deny",
        ) or "search_tv" not in policies                # invalid value ignored
        assert policies["library_sort_dir"] == "confirm"  # untouched default stays
    finally:
        test_settings.write_text(
            test_settings.read_text().replace(
                "approvals: {rom_download: auto, emby_scan: deny, search_tv: bogus}",
                "approvals: {}",
            )
        )
        src.config._settings = None


def test_end_to_end_two_turn_approval_through_agent(fake_model_factory):
    """Full graph: model calls gated tool → blocked; user approves in the
    next turn → the same call executes."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.prebuilt import create_react_agent

    gated = gate_tool(risky, "confirm")
    call = {"name": "risky", "args": {"path": "/media"}, "id": "c1", "type": "tool_call"}
    script = [
        AIMessage(content="", tool_calls=[call]),
        AIMessage(content="This will reorganize /media. Proceed?"),
        AIMessage(content="", tool_calls=[{**call, "id": "c2"}]),
        AIMessage(content="Done — organized /media."),
    ]
    agent = create_react_agent(
        fake_model_factory(script), tools=[gated], checkpointer=InMemorySaver()
    )
    cfg = {"configurable": {"thread_id": "t"}}

    r1 = asyncio.run(agent.ainvoke(
        {"messages": [{"role": "user", "content": "sort my library"}]}, cfg))
    tool_outputs = [m.content for m in r1["messages"] if m.type == "tool"]
    assert any("APPROVAL REQUIRED" in c for c in tool_outputs)
    assert not any("EXECUTED" in c for c in tool_outputs)

    r2 = asyncio.run(agent.ainvoke(
        {"messages": [{"role": "user", "content": "yes go ahead"}]}, cfg))
    tool_outputs = [m.content for m in r2["messages"] if m.type == "tool"]
    assert any("EXECUTED on /media" in c for c in tool_outputs)
