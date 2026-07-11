"""Conversational graph using LangGraph's create_react_agent.

All interfaces go through :func:`run_agent` / :func:`stream_agent` rather than
invoking the compiled graph directly. These helpers:

- always supply a ``thread_id`` (the compiled graph uses a checkpointer, which
  makes it mandatory — invoking without one raises);
- cap the ReAct loop with a recursion limit and turn overruns into a friendly
  message instead of a traceback;
- trim long conversation histories so persistent threads (dashboard, CLI)
  never overflow the model's context window;
- drive the circuit breaker in :class:`src.llm.client.MediaLLM`: when Ollama
  has failed repeatedly, requests skip straight to the hosted fallback until
  the breaker half-opens, instead of waiting out connection timeouts.
"""
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from src.llm.client import MediaLLM, create_llm
from src.tools.registry import all_tools

logger = logging.getLogger(__name__)

# In-process checkpointer — accumulates conversation state across messages
# for the same thread_id. Each dashboard session uses "dashboard" as the
# thread_id, so follow-up messages like "add the first one" have context.
_checkpointer = MemorySaver()

# Each ReAct step (LLM call or tool batch) counts against this. 16 allows
# ~7 tool rounds — plenty for real queries, small enough to stop loops fast.
RECURSION_LIMIT = 16

# Keep at most this many messages of history per thread when calling the
# model. Persistent threads otherwise grow without bound and blow past
# num_ctx, silently truncating the system prompt.
MAX_HISTORY_MESSAGES = 40

SYSTEM_PROMPT = """You are a personal media assistant — a friendly, conversational \
companion who helps manage a home media library.

You're chatting with the person who owns this library. Talk like a real person, \
not a help desk. Be warm, direct, and genuinely useful.

HOW TO TALK:
- Speak naturally. Short sentences. Contractions. Like texting a friend.
- ZERO JSON, EVER. No code blocks, no brackets, no key:value pairs, no
  backticks. If you find yourself typing `{` or `[`, stop — you are breaking
  the conversation. The user should never see anything that looks like a
  computer format.
- When showing lists, keep them readable. "You've got 5 shows downloading —
  SpongeBob, Ren & Stimpy..." not raw filenames.
- If something is interesting, say so. "Oh nice, you're grabbing the new
  Andor" not just "Andor is downloading."

TOOL USE:
- You have tools available. USE THEM silently. Do not describe what you
  plan to do — just do it. Never narrate, never write JSON, never explain
  how the tools work.
- When the user asks what's downloading, grab the queue info from all
  services at once and summarize it.
- When the user asks to search for something, search immediately.
- After tools return data, summarize the results conversationally.
- Never output tool names, function names, or anything technical. Just
  plain English.

WHAT YOU DO:
- TV & movies: search and add (always confirm first), queues, history,
  calendar, missing episodes/movies, quality profiles, root folders, refresh
- Library: search Emby ("do I have..."), recent additions, libraries, scans;
  build file inventories, find duplicate files, check and fix file naming
- Downloads: SABnzbd (queue, pause/resume, speed, add NZBs) and Synology
  Download Station (torrents, magnet links, stats)
- Classic games & emulation: search Internet Archive for No-Intro/Redump
  ROM sets, download them by identifier, verify collections against DAT
  files, list the ROM collection by platform (nes, snes, n64, gba, psx...)
- YouTube: download videos or audio-only (music/concert/podcast), get video
  info, and manage channel subscriptions (add/list/check/remove)
- Music: download Bandcamp albums by URL, or sync the whole purchased
  collection
- Audiobooks: list the Audible library, download by ASIN, sync newly
  purchased books, set up or check Audible authentication
- Remember what was discussed earlier in the conversation so "add the first one" works

CONFIRMATION RULE:
When the user asks to add or download something, search first, show them \
what you found in plain language, and ask if that's the right one before adding. \
Never silently add or download anything. Once they confirm, go ahead and add it, \
then trigger an Emby scan so it shows up in the library.
The same goes for big or irreversible operations: confirm before downloading \
a ROM set (they can be tens of GB — mention the size), before syncing a whole \
Bandcamp collection, and before renaming files (fix naming). For renames, \
check naming first, show what would change, and mention that an undo log is \
written so it can be reverted.

ID MATCHING:
- Search results show [tmdbId: N] for movies and [tvdbId: N] for TV shows.
  Use the right ID type for the right service — movie ID for movies, TV ID
  for shows. Don't mix them.
- ROM sets download by their Internet Archive identifier (shown in search
  results). Audiobooks download by ASIN (a 10-character code from the
  library list). YouTube and Bandcamp need the actual URL.
- For "download the audiobook X": list the Audible library first to find
  its ASIN, then download by that ASIN.

ERROR HANDLING:
If a tool fails, explain it simply. "Sonarr seems to be down right now" not \
"HTTPConnectionPool: connection refused." Keep it human."""


def _trim_history(messages: list, max_messages: int = MAX_HISTORY_MESSAGES) -> list:
    """Keep the most recent messages without orphaning tool calls.

    Cuts to the last ``max_messages``, then advances the window start to the
    next HumanMessage so it never opens with a dangling ToolMessage or an
    AI tool-call whose results were dropped (both are API errors upstream).
    """
    if len(messages) <= max_messages:
        return messages
    window = messages[-max_messages:]
    for i, msg in enumerate(window):
        if isinstance(msg, HumanMessage):
            return window[i:]
    # No human message in the window (pathological); keep only the tail
    # message if it is safe, else return the window unchanged.
    return window


def _build_prompt(state: dict) -> list:
    """Prompt hook for create_react_agent: system prompt + trimmed history."""
    return [SystemMessage(content=SYSTEM_PROMPT)] + _trim_history(state["messages"])


class AgentRuntime:
    """Compiled agents plus the LLM router/circuit breaker.

    Two graphs are compiled against the *same* checkpointer:

    - ``local_agent``: local Ollama primary, with a per-call fallback to the
      hosted model when one is configured (transient mid-run failures).
    - ``fallback_agent``: hosted model primary — used when the circuit
      breaker is OPEN so requests don't wait out a dead Ollama's timeouts.
    """

    def __init__(self):
        self.llm: MediaLLM = create_llm()

        # Always bind tools explicitly — create_react_agent's auto-bind can
        # silently fail with some LangChain/Ollama versions, causing the model
        # to emit tool calls as JSON text instead of tool_call messages.
        local_bound = self.llm.local_llm.bind_tools(all_tools)
        fallback_bound = None
        if self.llm.fallback_llm is not None:
            fallback_bound = self.llm.fallback_llm.bind_tools(all_tools)
            try:
                local_bound = local_bound.with_fallbacks([fallback_bound])
            except Exception:
                pass

        self.local_agent = create_react_agent(
            local_bound,
            tools=all_tools,
            prompt=_build_prompt,
            checkpointer=_checkpointer,
        )
        self.fallback_agent = None
        if fallback_bound is not None:
            self.fallback_agent = create_react_agent(
                fallback_bound,
                tools=all_tools,
                prompt=_build_prompt,
                checkpointer=_checkpointer,
            )

    async def pick_agent(self):
        """Select the compiled graph for this request via the circuit breaker."""
        if self.fallback_agent is None:
            return self.local_agent, False
        chosen = await self.llm.get_llm()
        if chosen is self.llm.fallback_llm:
            return self.fallback_agent, True
        return self.local_agent, False


_runtime: AgentRuntime | None = None


def get_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
    return _runtime


def create_agent():
    """Backwards-compatible accessor: the local-primary compiled agent."""
    return get_runtime().local_agent


def _thread_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }


def _extract_text(content) -> str:
    """Normalize message content (str or content-block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


_RECURSION_MSG = (
    "⚠️ That request needed more steps than I allow in one go. "
    "Try breaking it into smaller pieces."
)
_FAILURE_MSG = (
    "❌ I couldn't reach the language model right now. "
    "Check that Ollama is running, then try again."
)


def _is_recursion_error(exc: Exception) -> bool:
    try:
        from langgraph.errors import GraphRecursionError
        return isinstance(exc, GraphRecursionError)
    except ImportError:
        return "recursion" in type(exc).__name__.lower()


async def run_agent(message: str, thread_id: str, *, messages: list | None = None) -> str:
    """Run one conversational turn and return the reply text.

    Pass ``messages`` (list of ``{"role", "content"}`` dicts) instead of
    ``message`` to seed a whole history (stateless OpenAI-API requests).
    Never raises — failures come back as friendly ❌/⚠️ strings.
    """
    runtime = get_runtime()
    agent, using_fallback = await runtime.pick_agent()
    payload = {"messages": messages or [{"role": "user", "content": message}]}
    config = _thread_config(thread_id)

    try:
        result = await agent.ainvoke(payload, config)
        if not using_fallback:
            await runtime.llm.record_success()
        return _extract_text(result["messages"][-1].content) or "Done — but I have nothing to report."
    except Exception as exc:
        if _is_recursion_error(exc):
            return _RECURSION_MSG
        logger.exception("agent run failed (fallback=%s)", using_fallback)
        if not using_fallback:
            await runtime.llm.record_failure()
            # One retry on the hosted model, if configured.
            if runtime.fallback_agent is not None:
                try:
                    result = await runtime.fallback_agent.ainvoke(payload, config)
                    return _extract_text(result["messages"][-1].content) or _FAILURE_MSG
                except Exception:
                    logger.exception("fallback agent retry also failed")
        return _FAILURE_MSG


async def stream_agent(message: str, thread_id: str, *, messages: list | None = None):
    """Yield reply text chunks for one conversational turn.

    Same semantics as :func:`run_agent`, as an async generator for SSE
    endpoints. Yields friendly error text instead of raising.
    """
    runtime = get_runtime()
    agent, using_fallback = await runtime.pick_agent()
    payload = {"messages": messages or [{"role": "user", "content": message}]}
    config = _thread_config(thread_id)

    streamed_any = False
    try:
        async for event in agent.astream_events(payload, version="v2", config=config):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk is not None:
                    text = _extract_text(getattr(chunk, "content", ""))
                    if text:
                        streamed_any = True
                        yield text
        if not using_fallback:
            await runtime.llm.record_success()
    except Exception as exc:
        if _is_recursion_error(exc):
            yield _RECURSION_MSG
            return
        logger.exception("agent stream failed (fallback=%s)", using_fallback)
        if not using_fallback:
            await runtime.llm.record_failure()
        if not streamed_any:
            yield _FAILURE_MSG


async def record_exchange(thread_id: str, user_message: str, assistant_message: str) -> None:
    """Append a router-handled exchange to the thread's checkpoint.

    When the deterministic router answers a message, the LLM never sees that
    turn. Recording it keeps the agent's memory in sync so follow-ups like
    "tell me more about the second one" still have context. Best-effort:
    failures are logged, never raised.
    """
    try:
        runtime = get_runtime()
        await runtime.local_agent.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": [
                HumanMessage(content=user_message),
                AIMessage(content=assistant_message),
            ]},
            as_node="agent",
        )
    except Exception:
        logger.debug("could not record router exchange for %s", thread_id, exc_info=True)


def forget_thread(thread_id: str) -> None:
    """Drop a thread's checkpoints (used by stateless API requests).

    MemorySaver keeps every thread forever; per-request threads would leak.
    Best-effort — older langgraph checkpoint versions lack delete_thread.
    """
    try:
        _checkpointer.delete_thread(thread_id)
    except Exception:
        pass
