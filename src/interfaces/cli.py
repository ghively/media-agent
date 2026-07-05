"""CLI interface for Media Agent."""
import asyncio
import sys

from rich.console import Console
from rich.markdown import Markdown


async def cli_repl():
    """Interactive REPL for the media agent."""
    console = Console()
    console.print("[bold green]Media Agent[/] — Interactive Mode")
    console.print("Type 'exit' or 'quit' to leave.\n")

    from src.graphs.conversational import create_agent
    agent = create_agent()

    while True:
        try:
            user_input = console.input("[bold cyan]you>[/] ")
            if user_input.strip().lower() in ("exit", "quit"):
                console.print("[dim]Goodbye![/]")
                break
            if not user_input.strip():
                continue

            with console.status("[dim]Thinking...[/]"):
                result = await agent.ainvoke({
                    "messages": [{"role": "user", "content": user_input}]
                })

            response = result["messages"][-1].content
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
    from src.graphs.conversational import create_agent
    agent = create_agent()

    with console.status("[dim]Thinking...[/]"):
        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": query}]
        })

    console.print(result["messages"][-1].content)


async def cli_health():
    """Quick health check."""
    console = Console()
    from src.tools.health import check_all_health
    result = await check_all_health.ainvoke({})
    console.print(result)
