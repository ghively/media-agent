"""Media Agent entry point."""
import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(description="Media Agent")
    parser.add_argument("--interactive", "-i", action="store_true", help="Start interactive CLI")
    parser.add_argument("--query", "-q", type=str, help="One-shot query")
    parser.add_argument("--health", action="store_true", help="Quick health check")
    parser.add_argument("--serve", "-s", action="store_true", help="Start API server with all services")
    parser.add_argument("--host", default="0.0.0.0", help="API server host")
    parser.add_argument("--port", "-p", type=int, default=8088, help="API server port")
    args = parser.parse_args()

    if args.health:
        asyncio.run(_run_health())
    elif args.query:
        asyncio.run(_run_query(args.query))
    elif args.serve:
        _run_server(args.host, args.port)
    elif args.interactive:
        asyncio.run(_run_interactive())
    else:
        parser.print_help()


async def _run_health():
    from src.interfaces.cli import cli_health
    await cli_health()


async def _run_query(query: str):
    from src.interfaces.cli import cli_one_shot
    await cli_one_shot(query)


async def _run_interactive():
    from src.interfaces.cli import cli_repl
    await cli_repl()


def _run_server(host: str, port: int):
    """Start the API server with all interfaces: OpenAI-compatible API,
    web dashboard, and optional scheduler."""
    import threading
    import uvicorn

    # Mount dashboard on the existing FastAPI app
    from src.interfaces.dashboard import mount_dashboard
    from src.interfaces.openai_api import app as api_app
    mount_dashboard(api_app)

    # Start scheduler in background thread
    try:
        from src.scheduler import MediaScheduler
        sched = MediaScheduler()
        import threading
        t = threading.Thread(target=lambda: sched.start(), daemon=True)
        t.start()
        import logging
        logging.info("Scheduler started")
    except Exception as e:
        import logging
        logging.warning(f"Scheduler not started: {e}")

    uvicorn.run(
        api_app,
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


def _run_serve():
    """Run both the API server and CLI interface."""
    import threading
    from src.interfaces.openai_api import app as api_app
    from src.interfaces.dashboard import mount_dashboard
    mount_dashboard(api_app)

    # Start scheduler
    try:
        from src.scheduler import get_scheduler
        sched = get_scheduler()
        threading.Thread(target=lambda: asyncio.run(sched.start()), daemon=True).start()
    except Exception as e:
        pass

    import uvicorn
    uvicorn.run(api_app, host="0.0.0.0", port=8088, log_level="info")


if __name__ == "__main__":
    main()