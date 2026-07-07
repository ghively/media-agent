"""CLI interface for Media Agent."""
from rich.console import Console
from rich.markdown import Markdown

# Keep the last N messages of history (user + final assistant text only —
# tool call chatter is deliberately dropped so context stays small).
MAX_HISTORY_MESSAGES = 12


def _trim_history(messages: list[dict]) -> list[dict]:
    """Bound conversation history for small-model context budgets."""
    return messages[-MAX_HISTORY_MESSAGES:]


async def cli_repl():
    """Interactive REPL for the media agent."""
    console = Console()
    console.print("[bold green]Media Agent[/] — Interactive Mode")
    console.print("Type 'exit' or 'quit' to leave.\n")

    from src.graphs.conversational import resolve_agent, run_agent

    history: list[dict] = []

    while True:
        try:
            user_input = console.input("[bold cyan]you>[/] ")
            if user_input.strip().lower() in ("exit", "quit"):
                console.print("[dim]Goodbye![/]")
                break
            if not user_input.strip():
                continue

            history.append({"role": "user", "content": user_input})
            messages = _trim_history(history)
            _, domain = resolve_agent(messages)

            with console.status(f"[dim]Thinking ({domain})...[/]"):
                response = await run_agent(messages)

            history.append({"role": "assistant", "content": response})
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
    from src.graphs.conversational import run_agent

    with console.status("[dim]Thinking...[/]"):
        response = await run_agent([{"role": "user", "content": query}])

    console.print(response)


async def cli_health():
    """Quick health check — deterministic, no LLM involved."""
    console = Console()
    from src.workflows.pipelines import system_report
    console.print(await system_report())
