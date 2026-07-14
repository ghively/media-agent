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
    import logging

    import uvicorn
    from src.interfaces.dashboard import mount_dashboard
    from src.interfaces.openai_api import app as api_app
    from src.interfaces.openai_api import shutdown_hooks, startup_hooks

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    mount_dashboard(api_app)

    # Name each missing credential up front instead of letting it surface as
    # a mysterious 401 from a service later.
    try:
        from src.config import get_settings
        for warning in get_settings().validate():
            logger.warning("config: %s", warning)
    except Exception:
        logger.exception("config validation failed")

    # Close the conversation-memory DB cleanly on shutdown.
    async def _close_runtime():
        from src.graphs.conversational import aclose_runtime
        await aclose_runtime()

    shutdown_hooks.append(_close_runtime)

    # Telegram interface — no-op unless telegram.bot_token is configured.
    try:
        from src.interfaces.telegram_bot import start_telegram_bot, stop_telegram_bot
        startup_hooks.append(start_telegram_bot)
        shutdown_hooks.append(stop_telegram_bot)
    except Exception as e:
        logger.warning("Telegram interface unavailable: %s", e)

    # Start scheduler in the main event loop (not a bare thread).
    # AsyncIOScheduler must bind to the running event loop.
    try:
        from src.scheduler import MediaScheduler

        sched = MediaScheduler()

        # Register default jobs. Anything a human should act on is pushed via
        # src.notify (no-op unless notifications.url is configured) — a
        # finding that only reaches the container log reaches nobody.
        async def _health_check():
            from src.notify import notify
            from src.tools.health import check_all_health
            result = await check_all_health.ainvoke({})
            logger.info("Scheduled health check: %s", result[:200])
            if "❌" in result or "⚠️" in result:
                await notify("Media Agent: health problem", result[:2000])
            return result

        async def _missing_search():
            from src.tools.sonarr import search_missing_episodes
            from src.tools.radarr import search_missing_movies
            await search_missing_episodes.ainvoke({})
            await search_missing_movies.ainvoke({})
            return "Missing search complete"

        async def _daily_report():
            # Read-only daily report: surface health so problems are seen.
            from src.notify import notify
            from src.tools.health import check_all_health
            result = await check_all_health.ainvoke({})
            logger.info("Scheduled daily health report: %s", result[:200])
            await notify("Media Agent: daily report", result[:2000])
            return "Daily report complete"

        async def _weekly_scan():
            from src.tools.emby import emby_scan
            result = await emby_scan.ainvoke({})
            logger.info("Scheduled weekly library scan: %s", result[:200])
            return "Weekly scan triggered"

        async def _availability_check():
            # Requesters get a Telegram push the moment their approved
            # request actually lands in Emby (the seerr "available" event).
            from src.tools.requests_tools import check_availability
            result = await check_availability()
            logger.info("Scheduled availability check: %s", result[:200])
            return result

        async def _cleanup_sweep():
            # Quarantine-before-delete: only items whose grace period has
            # fully elapsed are acted on; unreachable services = skip.
            from src.tools.cleanup_tools import run_sweep
            result = await run_sweep()
            logger.info("Scheduled cleanup sweep: %s", result[:200])
            return result

        sched.add_job("health_check", _health_check, "health_check")
        sched.add_job("missing_search", _missing_search, "missing_episodes")
        sched.add_job("daily_cleanup", _daily_report, "daily_cleanup")
        sched.add_job("weekly_scan", _weekly_scan, "weekly_scan")
        sched.add_job("availability_check", _availability_check, "availability_check")
        sched.add_job("cleanup_sweep", _cleanup_sweep, "cleanup_sweep")

        # Start scheduler — must run inside the server's event loop, not a
        # separate thread (AsyncIOScheduler binds to the current loop)
        startup_hooks.append(sched.start)
        shutdown_hooks.append(sched.stop)

        logger.info("Scheduler configured with %d default jobs", sched.job_count)
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