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
                        # the model node is "model" in langchain.agents
                        # (was "agent" in langgraph.prebuilt)
                        if node in ("model", "agent"):
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
    """Interactive REPL for the media agent.

    Conversation state persists across restarts in a SQLite checkpointer
    under the state directory. Each REPL turn sends only the new user
    message; the graph replays prior turns from the checkpoint, so
    follow-ups like "add the second one" work — even after a restart.
    Type 'new' to start a fresh conversation thread.
    """
    import uuid

    console = Console()
    console.print("[bold green]Media Agent[/] — Interactive Mode")
    console.print("Type 'exit' or 'quit' to leave, 'new' for a fresh conversation.\n")

    from src.graphs.conversational import create_agent

    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from src.config import get_state_dir
        db_path = get_state_dir() / "checkpoints.db"
        checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(db_path))
    except Exception as e:
        console.print(f"[dim]Persistent memory unavailable ({e}); using in-memory.[/]")
        from contextlib import asynccontextmanager
        from langgraph.checkpoint.memory import InMemorySaver

        @asynccontextmanager
        async def _mem():
            yield InMemorySaver()
        checkpointer_cm = _mem()

    # Remember the active thread across restarts so 'new' sticks
    thread_file = None
    thread_id = "cli"
    try:
        from src.config import get_state_dir
        thread_file = get_state_dir() / "cli_thread.txt"
        if thread_file.exists():
            thread_id = thread_file.read_text().strip() or "cli"
    except Exception:
        pass

    async with checkpointer_cm as checkpointer:
        if hasattr(checkpointer, "setup"):
            await checkpointer.setup()  # create tables; not automatic
        agent = create_agent(checkpointer=checkpointer)
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": RECURSION_LIMIT,
        }

        while True:
            try:
                user_input = console.input("[bold cyan]you>[/] ")
                command = user_input.strip().lower()
                if command in ("exit", "quit"):
                    console.print("[dim]Goodbye![/]")
                    break
                if command == "new":
                    config["configurable"]["thread_id"] = f"cli-{uuid.uuid4().hex[:8]}"
                    if thread_file is not None:
                        thread_file.write_text(config["configurable"]["thread_id"])
                    console.print("[dim]Started a fresh conversation.[/]")
                    continue
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
