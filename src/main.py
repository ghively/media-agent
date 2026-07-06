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

    # Mount dashboard + browser chat on the existing FastAPI app
    from src.interfaces.dashboard import mount_dashboard
    from src.interfaces.chat_page import mount_chat_page
    from src.interfaces.openai_api import app as api_app
    from src.interfaces.api import router as api_router
    mount_dashboard(api_app)
    mount_chat_page(api_app)
    api_app.include_router(api_router)

    # Serve the built React frontend (if present)
    import os
    frontend_dist = os.environ.get("FRONTEND_DIST", "/app/frontend/dist")
    if os.path.isdir(frontend_dist):
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse

        # Mount static assets (JS, CSS, images)
        api_app.mount(
            "/assets",
            StaticFiles(directory=os.path.join(frontend_dist, "assets")),
            name="frontend-assets",
        )

        # SPA fallback — all non-API, non-doc routes return index.html
        @api_app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Don't intercept API or v1 routes
            if full_path.startswith(("api/", "v1/", "dashboard", "chat", "health")):
                return None
            index = os.path.join(frontend_dist, "index.html")
            if os.path.isfile(index):
                return FileResponse(index)
            return None

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

    # Two-way Telegram chat, when enabled in notifications settings
    from src.interfaces.telegram_chat import telegram_chat_enabled

    if telegram_chat_enabled():
        @api_app.on_event("startup")
        async def _start_telegram_chat():
            import asyncio as _asyncio
            from src.interfaces.telegram_chat import run_telegram_chat
            _asyncio.create_task(run_telegram_chat())
            logging.info("Telegram chat interface starting")

    uvicorn.run(
        api_app,
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()