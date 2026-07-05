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
    import uvicorn
    from src.interfaces.dashboard import mount_dashboard
    from src.interfaces.openai_api import app as api_app

    mount_dashboard(api_app)

    # Start scheduler in the main event loop (not a bare thread).
    # AsyncIOScheduler must bind to the running event loop.
    try:
        from src.scheduler import MediaScheduler
        import logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)

        sched = MediaScheduler()

        # Register default jobs
        async def _health_check():
            from src.tools.health import check_all_health
            result = await check_all_health.ainvoke({})
            logger.info("Scheduled health check: %s", result[:200])
            return result

        async def _missing_search():
            from src.tools.sonarr import search_missing_episodes
            from src.tools.radarr import search_missing_movies
            await search_missing_episodes.ainvoke({})
            await search_missing_movies.ainvoke({})
            return "Missing search complete"

        sched.add_job("health_check", _health_check, "health_check")
        sched.add_job("missing_search", _missing_search, "missing_episodes")

        # Start scheduler — must be called from within the running event loop,
        # not a separate thread (AsyncIOScheduler binds to the current loop)
        @api_app.on_event("startup")
        async def _start_scheduler():
            sched.start()

        logger.info("Scheduler configured with 2 default jobs")
    except Exception as e:
        import logging
        logging.basicConfig(level=logging.WARNING)
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