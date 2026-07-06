"""Media Agent entry point."""
import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(description="Media Agent")
    parser.add_argument("--interactive", "-i", action="store_true", help="Start interactive CLI")
    parser.add_argument("--query", "-q", type=str, help="One-shot query")
    parser.add_argument("--health", action="store_true", help="Quick health check")
    parser.add_argument("--doctor", action="store_true",
                        help="Diagnose the whole deployment (config, Ollama, services)")
    parser.add_argument("--serve", "-s", action="store_true", help="Start API server with all services")
    parser.add_argument("--host", default="0.0.0.0", help="API server host")
    parser.add_argument("--port", "-p", type=int, default=8088, help="API server port")
    args = parser.parse_args()

    if args.doctor:
        from src.doctor import run_doctor
        ok = asyncio.run(run_doctor())
        sys.exit(0 if ok else 1)
    elif args.health:
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
    import logging
    import uvicorn

    # Mount dashboard on the existing FastAPI app
    from src.interfaces.dashboard import mount_dashboard
    from src.interfaces.openai_api import app as api_app
    mount_dashboard(api_app)

    # Start the scheduler once uvicorn's event loop is running —
    # AsyncIOScheduler must attach to the running asyncio loop, so starting
    # it from a plain background thread would never fire jobs.
    from src.config import get_settings
    if get_settings().scheduler.get("enabled", False):
        @api_app.on_event("startup")
        async def _start_scheduler():
            try:
                from src.scheduler import MediaScheduler
                from src.jobs import register_configured_jobs
                sched = MediaScheduler()
                count = register_configured_jobs(sched)
                logging.info(sched.start())
                logging.info(f"Registered {count} scheduled job(s)")
            except Exception as e:
                logging.warning(f"Scheduler not started: {e}")

    uvicorn.run(
        api_app,
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()