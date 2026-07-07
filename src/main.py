"""Media Agent entry point."""
import argparse
import asyncio
import logging


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
    web dashboard, and (if enabled in config) the scheduler."""
    import uvicorn

    # Mount dashboard on the existing FastAPI app
    from src.interfaces.dashboard import mount_dashboard
    from src.interfaces.openai_api import app as api_app
    mount_dashboard(api_app)

    # Start the scheduler on the server's event loop — AsyncIOScheduler
    # needs a running asyncio loop, so it must start inside a startup hook.
    @api_app.on_event("startup")
    async def _start_scheduler():
        try:
            from src.config import get_settings
            if not get_settings().scheduler.get("enabled", False):
                logging.info("Scheduler disabled in config")
                return

            from src.scheduler import MediaScheduler
            from src.tools.health import check_all_health

            sched = MediaScheduler()

            async def _health_job() -> str:
                return await check_all_health.ainvoke({})

            sched.add_job("health_check", _health_job, trigger="health_check")
            logging.info(sched.start())
        except Exception as e:
            logging.warning("Scheduler not started: %s", e)

    uvicorn.run(
        api_app,
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
