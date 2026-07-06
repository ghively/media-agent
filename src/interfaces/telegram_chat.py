"""Two-way Telegram chat — talk to Media Agent from your phone.

Long-polls the Telegram Bot API (plain HTTPS, no framework) and feeds
messages from YOUR chat into the agent graph. Each Telegram chat gets a
persistent conversation thread, so follow-ups and approval flows ("yes, go
ahead") work exactly like the CLI.

Enable in settings.yaml:

    notifications:
      telegram_bot_token: "..."
      telegram_chat_id: "..."      # only this chat is answered
      telegram_chat: true          # turn on two-way chat

Send /new in Telegram to start a fresh conversation thread.
"""
import asyncio
import logging
import uuid

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
RECURSION_LIMIT = 25


def telegram_chat_enabled() -> bool:
    from src.notify import telegram_configured, _config
    return telegram_configured() and bool(_config().get("telegram_chat", False))


async def _send(client: httpx.AsyncClient, token: str, chat_id: str, text: str):
    for chunk_start in range(0, max(len(text), 1), 4000):
        await client.post(
            f"{_TELEGRAM_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[chunk_start:chunk_start + 4000]},
        )


async def _handle_message(agent, client, token, chat_id, text, thread_ref):
    from langgraph.errors import GraphRecursionError
    from src.llm.postprocess import clean_response

    if text.strip().lower() in ("/new", "/reset"):
        thread_ref[0] = f"telegram-{chat_id}-{uuid.uuid4().hex[:8]}"
        await _send(client, token, chat_id, "🆕 Started a fresh conversation.")
        return
    if text.strip().lower() in ("/start", "/help"):
        await _send(client, token, chat_id,
                    "🎬 Media Agent here. Ask me things like:\n"
                    "• what's new?\n• add the movie Heat\n"
                    "• what should I watch next?\n• check health\n\n"
                    "/new starts a fresh conversation.")
        return

    await client.post(f"{_TELEGRAM_API}/bot{token}/sendChatAction",
                      json={"chat_id": chat_id, "action": "typing"})
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": text}]},
            config={
                "configurable": {"thread_id": thread_ref[0]},
                "recursion_limit": RECURSION_LIMIT,
            },
        )
        reply = clean_response(result["messages"][-1])
    except GraphRecursionError:
        reply = ("⚠️ I hit my step limit — the model looped on tool calls. "
                 "Try a more specific request.")
    except Exception as e:
        reply = f"❌ {type(e).__name__}: {e}"
    await _send(client, token, chat_id, reply)


async def run_telegram_chat() -> None:
    """Long-poll loop. Run as a background task on the server's event loop."""
    from src.notify import _config
    from src.graphs.conversational import create_agent

    cfg = _config()
    token = cfg["telegram_bot_token"]
    allowed_chat = str(cfg["telegram_chat_id"])

    # Persistent memory shared with nothing else (own db table namespace is
    # fine — thread ids are telegram-*)
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from src.config import get_state_dir
        checkpointer_cm = AsyncSqliteSaver.from_conn_string(
            str(get_state_dir() / "checkpoints.db"))
    except Exception:
        from contextlib import asynccontextmanager
        from langgraph.checkpoint.memory import InMemorySaver

        @asynccontextmanager
        async def _mem():
            yield InMemorySaver()
        checkpointer_cm = _mem()

    async with checkpointer_cm as checkpointer:
        if hasattr(checkpointer, "setup"):
            await checkpointer.setup()
        agent = create_agent(checkpointer=checkpointer)
        thread_ref = [f"telegram-{allowed_chat}"]
        offset = 0
        logger.info("Telegram chat interface started (chat %s)", allowed_chat)

        async with httpx.AsyncClient(timeout=70) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{_TELEGRAM_API}/bot{token}/getUpdates",
                        params={"timeout": 50, "offset": offset,
                                "allowed_updates": '["message"]'},
                    )
                    data = resp.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        message = update.get("message") or {}
                        text = message.get("text", "")
                        chat_id = str((message.get("chat") or {}).get("id", ""))
                        if not text:
                            continue
                        if chat_id != allowed_chat:
                            logger.warning("Ignoring message from unknown chat %s", chat_id)
                            continue
                        await _handle_message(agent, client, token, chat_id,
                                              text, thread_ref)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("Telegram poll error: %s: %s", type(e).__name__, e)
                    await asyncio.sleep(10)
