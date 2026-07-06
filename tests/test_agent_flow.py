"""Behavioral tests for the agent's chat-facing flow: streaming hygiene and
multi-turn memory. Uses fake models so no Ollama is required."""
import asyncio

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent


@tool
async def search_tv(query: str) -> str:
    """Search for TV shows by name."""
    return "1. Severance (2022) [371980]\n2. Severance (2006) [79242]"


@tool
async def add_tv_show(tvdb_id: int, title: str) -> str:
    """Add a TV show by TVDB id."""
    return f"✅ Added '{title}'"


def _collect_stream(agent, message, config=None):
    """Replicates the exact filtering used by openai_api._stream_response."""
    from src.llm.postprocess import clean_response

    async def run():
        emitted = []
        async for update in agent.astream(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
            stream_mode="updates",
        ):
            for node, payload in update.items():
                if node not in ("model", "agent"):
                    continue
                for msg in (payload or {}).get("messages", []):
                    if getattr(msg, "tool_calls", None):
                        continue
                    text = clean_response(msg)
                    if text:
                        emitted.append(text)
        return emitted

    return asyncio.run(run())


def test_stream_never_leaks_tool_calls_or_think_tags(fake_model_factory):
    script = [
        AIMessage(content="", tool_calls=[
            {"name": "search_tv", "args": {"query": "severance"}, "id": "c1", "type": "tool_call"}]),
        AIMessage(content="<think>two matches, must ask</think>"
                          "Two matches:\n- Severance (2022)\n- Severance (2006)\n\nWhich one?"),
    ]
    agent = create_agent(fake_model_factory(script), tools=[search_tv])
    out = "\n".join(_collect_stream(agent, "add severance"))

    assert "Which one?" in out
    assert "<think>" not in out
    assert "tool_call" not in out
    assert "c1" not in out
    assert '"query"' not in out


def test_multi_turn_memory_resolves_follow_up(fake_model_factory):
    seen = []

    class Spy:
        def __call__(self, messages):
            seen.clear()
            seen.extend(str(m.content) for m in messages)

    script = [
        AIMessage(content="Two matches: 1. Severance (2022), 2. Severance (2006). Which one?"),
        AIMessage(content="", tool_calls=[
            {"name": "add_tv_show", "args": {"tvdb_id": 79242, "title": "Severance (2006)"},
             "id": "c2", "type": "tool_call"}]),
        AIMessage(content="✅ Added Severance (2006)."),
    ]
    model = fake_model_factory(script)
    orig_generate = type(model)._generate
    spy = Spy()

    def spying_generate(self, messages, *a, **k):
        spy(messages)
        return orig_generate(self, messages, *a, **k)

    type(model)._generate = spying_generate

    agent = create_agent(model, tools=[add_tv_show], checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t"}}
    _collect_stream(agent, "add severance", cfg)
    out = "\n".join(_collect_stream(agent, "the second one", cfg))

    assert "✅ Added Severance (2006)." in out
    assert any("add severance" in c for c in seen), "turn-1 context lost"
    assert any("Which one?" in c for c in seen), "turn-1 answer lost"


def test_agent_graph_builds_from_real_registry():
    from src.graphs.conversational import create_agent
    agent = create_agent()
    assert agent is not None


def test_registry_has_no_duplicate_names_and_expected_count():
    from src.tools.registry import all_tools
    names = [t.name for t in all_tools]
    assert len(names) == len(set(names))
    assert len(names) == 67
