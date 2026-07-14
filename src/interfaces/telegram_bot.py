"""Telegram bot interface — chat with the agent from your phone.

Config (top-level ``telegram`` section in settings.yaml):

- ``bot_token``: from @BotFather (``${TELEGRAM_BOT_TOKEN}``). Absent → the
  interface stays off.
- ``allowed_chat_ids``: list of Telegram chat ids allowed to command the
  agent. **The bot refuses everyone until this is set** — an open bot would
  hand library control (including renames and multi-GB downloads) to anyone
  who finds it. An unauthorized chat is answered with its own chat id so
  onboarding is one copy-paste.

Same invocation rule as every interface: router-first (``try_route``), then
``run_agent``. Each chat gets its own persistent thread (``tg-<chat_id>``),
so yes/no confirmations and "add the first one" follow-ups work naturally.
"""
import logging

logger = logging.getLogger(__name__)

_application = None  # telegram.ext.Application while the bot is running

_TELEGRAM_MSG_LIMIT = 4000  # hard API cap is 4096 chars


async def _answer(text: str, thread_id: str) -> str:
    from src.graphs.conversational import record_exchange, run_agent
    from src.graphs.router import try_route
    from src.users import is_admin

    reply = await try_route(text, thread_id)
    if reply is not None:
        await record_exchange(thread_id, text, reply)
        return reply
    if not is_admin(thread_id):
        # Non-admins never reach the LLM agent: its toolset includes direct
        # add/rename/delete tools, which would bypass the role gate the
        # router enforces. The deterministic path covers everything a
        # requester-tier user is allowed to do.
        return ("I didn't catch that. You can request media ('add Severance "
                "season 2'), check on things ('what's downloading?', 'my "
                "requests'), or say 'help' for the full list.")
    return await run_agent(text, thread_id)


async def start_telegram_bot():
    """Start long-polling if a bot token is configured. Never raises."""
    global _application
    try:
        from src.config import get_settings
        cfg = get_settings().telegram
        token = cfg.get("bot_token", "")
        if not token:
            return
        allowed = {str(c) for c in (cfg.get("allowed_chat_ids") or [])}

        from telegram.ext import Application, MessageHandler, filters

        async def handle(update, context):
            msg = update.effective_message
            if msg is None or not msg.text:
                return
            chat_id = str(update.effective_chat.id)
            if chat_id not in allowed:
                await msg.reply_text(
                    f"⛔ This chat isn't authorized to use the media agent.\n"
                    f"Your chat id is {chat_id} — add it to "
                    f"telegram.allowed_chat_ids in settings.yaml and restart.")
                return
            try:
                reply = await _answer(msg.text, f"tg-{chat_id}")
            except Exception:
                logger.exception("telegram turn failed")
                reply = "❌ Something went wrong answering that — check the agent logs."
            for i in range(0, len(reply), _TELEGRAM_MSG_LIMIT):
                await msg.reply_text(reply[i:i + _TELEGRAM_MSG_LIMIT])

        app = Application.builder().token(token).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        _application = app
        if allowed:
            logger.info("telegram bot polling (authorized chats: %d)", len(allowed))
        else:
            logger.warning(
                "telegram bot polling but telegram.allowed_chat_ids is empty — "
                "it will refuse every chat and reply with the chat id to add")
    except Exception:
        logger.exception("telegram bot failed to start — continuing without it")


async def stop_telegram_bot():
    """Stop polling cleanly on server shutdown. Never raises."""
    global _application
    app = _application
    _application = None
    if app is None:
        return
    try:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
    except Exception:
        logger.debug("telegram bot shutdown failed", exc_info=True)
