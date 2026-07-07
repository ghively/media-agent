"""Tests for domain toolsets, prompt budget, and history trimming —
the small-local-model guarantees."""
from src.graphs.conversational import (
    DOMAIN_TOOLS, build_system_prompt, tools_for_domain,
)
from src.graphs.router import CORE, DOMAIN_KEYWORDS
from src.interfaces.cli import MAX_HISTORY_MESSAGES, _trim_history
from src.tools.registry import all_tools

_REGISTERED = {t.name for t in all_tools}


def test_every_domain_tool_exists_in_registry():
    for domain, names in DOMAIN_TOOLS.items():
        missing = set(names) - _REGISTERED
        assert not missing, f"{domain}: unknown tools {sorted(missing)}"


def test_every_router_domain_has_a_toolset():
    for domain in DOMAIN_KEYWORDS:
        assert domain in DOMAIN_TOOLS, f"router domain {domain!r} has no toolset"
    assert CORE in DOMAIN_TOOLS


def test_domain_toolsets_are_small():
    # The whole point: a small model should never see a huge tool list.
    for domain, names in DOMAIN_TOOLS.items():
        assert 1 <= len(names) <= 13, f"{domain} binds {len(names)} tools"


def test_core_prompt_is_compact():
    prompt = build_system_prompt(tools_for_domain(CORE))
    # ~450 tokens ceiling; the old prompt for 59 tools was 5x this
    assert len(prompt) < 2000, f"core prompt too long: {len(prompt)} chars"


def test_domain_prompts_reference_only_bound_tools():
    tv_tools = tools_for_domain("tv")
    prompt = build_system_prompt(tv_tools)
    for t in tv_tools:
        assert t.name in prompt
    assert "bandcamp_download" not in prompt
    assert "rom_download" not in prompt


def test_history_trimming_bounds_context():
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    trimmed = _trim_history(msgs)
    assert len(trimmed) == MAX_HISTORY_MESSAGES
    assert trimmed[-1] == msgs[-1]  # newest kept


def test_short_history_untouched():
    msgs = [{"role": "user", "content": "hi"}]
    assert _trim_history(msgs) == msgs
