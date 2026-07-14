"""Tests for the agent runtime helpers (trimming, error mapping, config)."""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.graphs.conversational import (
    MAX_HISTORY_MESSAGES,
    RECURSION_LIMIT,
    SYSTEM_PROMPT,
    _build_prompt,
    _extract_text,
    _thread_config,
    _trim_history,
)


def _convo(n_turns: int) -> list:
    msgs = []
    for i in range(n_turns):
        msgs.append(HumanMessage(content=f"question {i}"))
        msgs.append(AIMessage(content=f"answer {i}"))
    return msgs


def test_trim_noop_when_short():
    msgs = _convo(3)
    assert _trim_history(msgs) is msgs


def test_trim_caps_length():
    msgs = _convo(100)
    trimmed = _trim_history(msgs)
    assert len(trimmed) <= MAX_HISTORY_MESSAGES
    # Window must start on a human message so tool calls aren't orphaned.
    assert isinstance(trimmed[0], HumanMessage)
    # Most recent message survives.
    assert trimmed[-1].content == msgs[-1].content


def test_trim_skips_orphaned_tool_results():
    msgs = _convo(30)
    # Force the raw cut to land on a ToolMessage.
    msgs = msgs + [
        AIMessage(content="", tool_calls=[
            {"name": "t", "args": {}, "id": "call1"}]),
        ToolMessage(content="result", tool_call_id="call1"),
        HumanMessage(content="follow up"),
        AIMessage(content="final"),
    ]
    trimmed = _trim_history(msgs, max_messages=3)
    assert isinstance(trimmed[0], HumanMessage)
    assert trimmed[0].content == "follow up"


def test_build_prompt_prepends_system():
    state = {"messages": _convo(2)}
    prompt = _build_prompt(state)
    assert isinstance(prompt[0], SystemMessage)
    # System prompt plus a date grounding line ("Today is ...").
    assert prompt[0].content.startswith(SYSTEM_PROMPT)
    assert "Today is" in prompt[0].content
    assert len(prompt) == 5


def test_thread_config():
    cfg = _thread_config("abc")
    assert cfg["configurable"]["thread_id"] == "abc"
    assert cfg["recursion_limit"] == RECURSION_LIMIT


def test_extract_text_variants():
    assert _extract_text("plain") == "plain"
    assert _extract_text(["a", "b"]) == "ab"
    assert _extract_text([{"type": "text", "text": "hi"},
                          {"type": "tool_use", "id": "x"}]) == "hi"


def test_registry_imports_and_has_tools():
    from src.tools.registry import all_tools
    # Exact count: a silently-dropped optional tool group must fail loudly.
    # Update this (and the docs) when adding or removing tools.
    assert len(all_tools) == 102
    names = [t.name for t in all_tools]
    assert len(names) == len(set(names)), "duplicate tool names confuse the LLM"
    for t in all_tools:
        assert t.description, f"tool {t.name} has no description for the LLM"
