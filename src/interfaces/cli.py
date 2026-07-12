"""CLI interface for Media Agent.

Messages go router-first: common commands ("what's downloading?", "check
health", "add Breaking Bad") are answered deterministically without an LLM
round-trip; everything else goes to the LangGraph agent. Router-handled
exchanges are recorded into the agent's thread memory so follow-ups keep
their context either way.
"""
import uuid

from rich.console import Console
from rich.markdown import Markdown


async def _answer(message: str, thread_id: str) -> str:
    """Route deterministically when possible, else run the agent."""
    from src.graphs.conversational import record_exchange, run_agent
    from src.graphs.router import try_route

    reply = await try_route(message, thread_id)
    if reply is not None:
        await record_exchange(thread_id, message, reply)
        return reply
    return await run_agent(message, thread_id)


async def cli_repl():
    """Interactive REPL for the media agent."""
    console = Console()
    console.print("[bold green]Media Agent[/] — Interactive Mode")
    console.print("Type 'exit' or 'quit' to leave.\n")

    # One conversation thread per REPL session.
    thread_id = f"cli-{uuid.uuid4().hex[:8]}"

    while True:
        try:
            user_input = console.input("[bold cyan]you>[/] ")
            if user_input.strip().lower() in ("exit", "quit"):
                console.print("[dim]Goodbye![/]")
                break
            if not user_input.strip():
                continue

            with console.status("[dim]Thinking...[/]"):
                response = await _answer(user_input, thread_id)

            console.print()
            console.print(Markdown(response))
            console.print()

        except KeyboardInterrupt:
            console.print("\n[dim]Goodbye![/]")
            break
        except Exception as e:
            console.print(f"[red]Error: {type(e).__name__}: {e}[/]")


async def cli_one_shot(query: str):
    """Run a single query and print the result."""
    console = Console()
    from src.graphs.conversational import forget_thread

    thread_id = f"oneshot-{uuid.uuid4().hex[:8]}"
    try:
        with console.status("[dim]Thinking...[/]"):
            response = await _answer(query, thread_id)
        console.print(response)
    finally:
        forget_thread(thread_id)


async def cli_health():
    """Quick health check."""
    console = Console()
    from src.tools.health import check_all_health
    result = await check_all_health.ainvoke({})
    console.print(result)
