"""CLI interface for Media Agent."""
import asyncio
import sys

from rich.console import Console
from rich.markdown import Markdown

# How many agent↔tool round-trips to allow before bailing out. Small local
# models can loop; a bounded limit turns that into a readable error.
RECURSION_LIMIT = 25


def _tool_call_summary(message) -> list[str]:
    """Short human-readable lines for an AIMessage's tool calls."""
    lines = []
    for tc in getattr(message, "tool_calls", None) or []:
        args = ", ".join(f"{k}={v!r}" for k, v in (tc.get("args") or {}).items())
        lines.append(f"{tc.get('name', '?')}({args})")
    return lines


async def _run_turn(agent, console: Console, user_input: str, config: dict) -> None:
    """Run one agent turn, showing tool activity, then print the answer."""
    from langgraph.errors import GraphRecursionError
    from src.llm.postprocess import clean_response

    final_message = None
    try:
        with console.status("[dim]Thinking...[/]"):
            async for update in agent.astream(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
                stream_mode="updates",
            ):
                for node, payload in update.items():
                    for message in (payload or {}).get("messages", []):
                        if node == "agent":
                            for line in _tool_call_summary(message):
                                console.print(f"  [dim]→ {line}[/]")
                            if not getattr(message, "tool_calls", None):
                                final_message = message
    except GraphRecursionError:
        console.print(
            "[yellow]⚠️ The agent hit its step limit without finishing. "
            "This usually means the model is looping on tool calls — "
            "try a more specific request or a stronger model.[/]"
        )
        return

    if final_message is None:
        console.print("[yellow]⚠️ The agent finished without a reply.[/]")
        return

    console.print()
    console.print(Markdown(clean_response(final_message)))
    console.print()


async def cli_repl():
    """Interactive REPL for the media agent."""
    console = Console()
    console.print("[bold green]Media Agent[/] — Interactive Mode")
    console.print("Type 'exit' or 'quit' to leave.\n")

    from langgraph.checkpoint.memory import InMemorySaver
    from src.graphs.conversational import create_agent

    # In-memory checkpointer: each REPL turn sends only the new user message,
    # and the graph replays prior turns from the checkpoint, so follow-ups
    # like "add the second one" work.
    agent = create_agent(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": "cli"},
        "recursion_limit": RECURSION_LIMIT,
    }

    while True:
        try:
            user_input = console.input("[bold cyan]you>[/] ")
            if user_input.strip().lower() in ("exit", "quit"):
                console.print("[dim]Goodbye![/]")
                break
            if not user_input.strip():
                continue

            await _run_turn(agent, console, user_input, config)

        except KeyboardInterrupt:
            console.print("\n[dim]Goodbye![/]")
            break
        except Exception as e:
            console.print(f"[red]Error: {type(e).__name__}: {e}[/]")


async def cli_one_shot(query: str):
    """Run a single query and print the result."""
    console = Console()
    from src.graphs.conversational import create_agent

    agent = create_agent()
    config = {"recursion_limit": RECURSION_LIMIT}
    await _run_turn(agent, console, query, config)


async def cli_health():
    """Quick health check."""
    console = Console()
    from src.tools.health import check_all_health
    result = await check_all_health.ainvoke({})
    console.print(result)
