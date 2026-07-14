"""Conversational graph using LangGraph's create_react_agent.

All interfaces go through :func:`run_agent` / :func:`stream_agent` rather than
invoking the compiled graph directly. These helpers:

- always supply a ``thread_id`` (the compiled graph uses a checkpointer, which
  makes it mandatory — invoking without one raises);
- cap the ReAct loop with a recursion limit and turn overruns into a friendly
  message instead of a traceback;
- trim long conversation histories so persistent threads (dashboard, CLI)
  never overflow the model's context window, and periodically compact the
  stored checkpoint so memory use stays bounded;
- drive the circuit breaker in :class:`src.llm.client.MediaLLM`: when Ollama
  has failed repeatedly, requests skip straight to the hosted fallback until
  the breaker half-opens, instead of waiting out connection timeouts.

Conversation memory persists across restarts in ``/state/agent_memory.db``
(AsyncSqliteSaver) when the state volume is available; otherwise it degrades
to the in-process MemorySaver.
"""
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import (
    AIMessage, HumanMessage, RemoveMessage, SystemMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from src.audit import ToolAuditHandler
from src.llm.client import MediaLLM, create_llm
from src.tools.registry import all_tools

logger = logging.getLogger(__name__)

# Each ReAct step (LLM call or tool batch) counts against this. 16 allows
# ~7 tool rounds — plenty for real queries, small enough to stop loops fast.
RECURSION_LIMIT = 16

# Keep at most this many messages of history per thread when calling the
# model. 70 tool schemas + the system prompt already consume a large slice
# of num_ctx; a fatter window makes Ollama silently truncate from the top —
# dropping the system prompt and tool definitions first.
MAX_HISTORY_MESSAGES = 20

# Stored checkpoints grow forever on persistent threads (dashboard, CLI).
# Once a thread exceeds COMPACT_THRESHOLD stored messages, rewrite it down
# to the most recent COMPACT_KEEP.
COMPACT_THRESHOLD = 120
COMPACT_KEEP = 40

# Tag on the local model's runs so the error tracker can tell local failures
# from hosted-fallback failures.
_LOCAL_LLM_TAG = "local-llm"

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
- ROM library care: scan and identify ROMs by parsing their file headers
  (platform, format, internal title, region, game codes), inspect a single
  ROM's metadata, find duplicate ROMs (exact CRC matches with a keep
  recommendation, plus region/revision variants), and debug problems —
  corrupt headers, failed checksums, byte-swapped N64 dumps, copier
  headers, misnamed files, orphaned cue/bin tracks, bad-dump tags
- YouTube: download videos or audio-only (music/concert/podcast), get video
  info, and manage channel subscriptions (add/list/check/remove)
- Music: download Bandcamp albums by URL, or sync the whole purchased
  collection; manage artists with Lidarr (search, add, list, music queue)
- Audiobooks: list the Audible library, download by ASIN, sync newly
  purchased books, set up or check Audible authentication
- Podcasts: subscribe by RSS URL, list subscriptions, check and download
  new episodes
- Twitch: check if a channel is live, record streams to the library,
  check recording status
- Comics & manga: search the Komga library, recent additions, trigger scans
- Ebooks: search the Calibre library, recent additions
- Torrents: qBittorrent (list, add, pause, resume) or Synology Download
  Station — magnet links go to whichever is configured
- Indexers: unified Prowlarr search across all torrent/usenet indexers
  when the normal TV/movie search comes up empty
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
The bulk tools enforce this themselves: rom_download, \
bandcamp_download_collection, audible_download_new, and library_fix_naming \
only preview until called with confirm=true. Set confirm=true ONLY after the \
user has explicitly said yes to that exact operation.

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
    """Prompt hook for create_react_agent: system prompt + trimmed history.

    The current date is appended so calendar-flavored questions ("what's on
    next Tuesday?") aren't answered by a model that doesn't know today."""
    date_line = f"\n\nToday is {datetime.now().strftime('%A, %B %d, %Y')}."
    return [SystemMessage(content=SYSTEM_PROMPT + date_line)] + _trim_history(state["messages"])


class _LLMErrorTracker(AsyncCallbackHandler):
    """Counts local-model errors during one run.

    ``with_fallbacks()`` can silently serve a turn on the hosted model after
    the local one failed. Without this hook the run looks successful and the
    breaker records a success for a dead Ollama — so every later turn keeps
    paying the local timeout before falling back.
    """

    def __init__(self):
        self.local_errors = 0

    async def on_llm_error(self, error, *, tags=None, **kwargs):
        if tags and _LOCAL_LLM_TAG in tags:
            self.local_errors += 1


class AgentRuntime:
    """Compiled agents plus the LLM router/circuit breaker.

    Two graphs are compiled against the *same* checkpointer:

    - ``local_agent``: local Ollama primary, with a per-call fallback to the
      hosted model when one is configured (transient mid-run failures).
    - ``fallback_agent``: hosted model primary — used when the circuit
      breaker is OPEN so requests don't wait out a dead Ollama's timeouts.
    """

    def __init__(self, checkpointer):
        self.checkpointer = checkpointer
        self.llm: MediaLLM = create_llm()

        # Always bind tools explicitly — create_react_agent's auto-bind can
        # silently fail with some LangChain/Ollama versions, causing the model
        # to emit tool calls as JSON text instead of tool_call messages.
        # The tag lets _LLMErrorTracker attribute errors to the local model.
        local_bound = self.llm.local_llm.bind_tools(all_tools).with_config(
            tags=[_LOCAL_LLM_TAG])
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
            checkpointer=checkpointer,
        )
        self.fallback_agent = None
        if fallback_bound is not None:
            self.fallback_agent = create_react_agent(
                fallback_bound,
                tools=all_tools,
                prompt=_build_prompt,
                checkpointer=checkpointer,
            )

        # Domain-scoped agents (LLM-light mode): one graph per domain, bound
        # to that domain's tools only. A small local model choosing among
        # ~10 tools is far more reliable than among 92 — and burns a fraction
        # of the schema tokens. Shares the checkpointer, so scoped and full
        # turns interleave on the same thread. Disable via llm.tool_scoping.
        self.scoped_agents: dict = {}
        try:
            from src.config import get_settings
            scoping_enabled = get_settings().llm.get("tool_scoping", True)
        except Exception:
            scoping_enabled = True
        if scoping_enabled:
            from src.graphs.scoping import DOMAINS, tools_for_domain
            by_name = {t.name: t for t in all_tools}
            for domain in DOMAINS:
                subset = [by_name[n] for n in tools_for_domain(domain)
                          if n in by_name]
                if not subset:
                    continue
                scoped_bound = self.llm.local_llm.bind_tools(subset).with_config(
                    tags=[_LOCAL_LLM_TAG])
                self.scoped_agents[domain] = create_react_agent(
                    scoped_bound,
                    tools=subset,
                    prompt=_build_prompt,
                    checkpointer=checkpointer,
                )

    async def pick_agent(self, message: str = ""):
        """Select the compiled graph for this request.

        Breaker OPEN → hosted full agent. Otherwise, an unambiguous domain
        classification picks the scoped local agent; anything else runs the
        full local agent."""
        if self.fallback_agent is not None:
            chosen = await self.llm.get_llm()
            if chosen is self.llm.fallback_llm:
                return self.fallback_agent, True
        if self.scoped_agents and message:
            from src.graphs.scoping import classify
            domain = classify(message)
            if domain is not None and domain in self.scoped_agents:
                logger.info("scoped agent: %s", domain)
                return self.scoped_agents[domain], False
        return self.local_agent, False


async def _make_checkpointer():
    """SQLite persistence on the state volume; in-memory when unavailable."""
    state_dir = Path(os.environ.get("MEDIA_AGENT_STATE_DIR", "/state"))
    try:
        if state_dir.is_dir() and os.access(state_dir, os.W_OK):
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            db_path = state_dir / "agent_memory.db"
            conn = await aiosqlite.connect(db_path)
            saver = AsyncSqliteSaver(conn)
            await saver.setup()
            logger.info("conversation memory persisted at %s", db_path)
            return saver
    except Exception:
        logger.warning(
            "sqlite checkpointer unavailable — conversation memory will not "
            "survive restarts", exc_info=True)
    return MemorySaver()


_runtime: AgentRuntime | None = None
_runtime_lock = asyncio.Lock()


async def get_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        async with _runtime_lock:
            if _runtime is None:
                _runtime = AgentRuntime(await _make_checkpointer())
    return _runtime


_audit_handler = ToolAuditHandler()


def _thread_config(thread_id: str, tracker: _LLMErrorTracker | None = None) -> dict:
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }
    callbacks = [_audit_handler]
    if tracker is not None:
        callbacks.append(tracker)
    config["callbacks"] = callbacks
    return config


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
_TRUNCATED_MSG = (
    "\n\n⚠️ The connection to the model dropped mid-reply — the answer "
    "above may be incomplete."
)


def _is_recursion_error(exc: Exception) -> bool:
    try:
        from langgraph.errors import GraphRecursionError
        return isinstance(exc, GraphRecursionError)
    except ImportError:
        return "recursion" in type(exc).__name__.lower()


def _last_user_text(message: str, messages: list | None) -> str:
    """The text used for domain scoping: the latest user utterance."""
    if messages:
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                return str(m.get("content", ""))
    return message or ""


async def _record_outcome(runtime: AgentRuntime, tracker: _LLMErrorTracker) -> None:
    """Update the breaker after a run that produced a reply.

    A reply that needed the per-call fallback still means the local model is
    failing — count it, so the breaker opens and later requests skip the
    local timeout entirely.
    """
    if tracker.local_errors:
        await runtime.llm.record_failure()
    else:
        await runtime.llm.record_success()


async def run_agent(message: str, thread_id: str, *, messages: list | None = None) -> str:
    """Run one conversational turn and return the reply text.

    Pass ``messages`` (list of ``{"role", "content"}`` dicts) instead of
    ``message`` to seed a whole history (stateless OpenAI-API requests).
    Never raises — failures come back as friendly ❌/⚠️ strings.
    """
    runtime = await get_runtime()
    agent, using_fallback = await runtime.pick_agent(_last_user_text(message, messages))
    payload = {"messages": messages or [{"role": "user", "content": message}]}
    tracker = _LLMErrorTracker()
    config = _thread_config(thread_id, tracker)

    try:
        result = await agent.ainvoke(payload, config)
        if not using_fallback:
            await _record_outcome(runtime, tracker)
        reply = _extract_text(result["messages"][-1].content) or "Done — but I have nothing to report."
        await _compact_thread(thread_id)
        return reply
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


async def _stream_text(agent, payload: dict, config: dict):
    """Yield text chunks from one graph run."""
    async for event in agent.astream_events(payload, version="v2", config=config):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk is not None:
                text = _extract_text(getattr(chunk, "content", ""))
                if text:
                    yield text


async def stream_agent(message: str, thread_id: str, *, messages: list | None = None):
    """Yield reply text chunks for one conversational turn.

    Same semantics as :func:`run_agent`, as an async generator for SSE
    endpoints. Yields friendly error text instead of raising; retries once
    on the hosted model when nothing has been streamed yet.
    """
    runtime = await get_runtime()
    agent, using_fallback = await runtime.pick_agent(_last_user_text(message, messages))
    payload = {"messages": messages or [{"role": "user", "content": message}]}
    tracker = _LLMErrorTracker()
    config = _thread_config(thread_id, tracker)

    streamed_any = False
    try:
        async for text in _stream_text(agent, payload, config):
            streamed_any = True
            yield text
        if not using_fallback:
            await _record_outcome(runtime, tracker)
        await _compact_thread(thread_id)
        return
    except Exception as exc:
        if _is_recursion_error(exc):
            yield _RECURSION_MSG
            return
        logger.exception("agent stream failed (fallback=%s)", using_fallback)
        if not using_fallback:
            await runtime.llm.record_failure()

    # Mirror run_agent's retry: if nothing reached the client yet, replay the
    # turn on the hosted model instead of surfacing a failure.
    if not streamed_any and not using_fallback and runtime.fallback_agent is not None:
        try:
            async for text in _stream_text(runtime.fallback_agent, payload, config):
                streamed_any = True
                yield text
            return
        except Exception:
            logger.exception("fallback stream retry also failed")

    # A partially-streamed reply must not end silently truncated.
    yield _TRUNCATED_MSG if streamed_any else _FAILURE_MSG


async def record_exchange(thread_id: str, user_message: str, assistant_message: str) -> None:
    """Append a router-handled exchange to the thread's checkpoint.

    When the deterministic router answers a message, the LLM never sees that
    turn. Recording it keeps the agent's memory in sync so follow-ups like
    "tell me more about the second one" still have context. Best-effort:
    failures are logged, never raised.
    """
    try:
        runtime = await get_runtime()
        await runtime.local_agent.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": [
                HumanMessage(content=user_message),
                AIMessage(content=assistant_message),
            ]},
            as_node="agent",
        )
        await _compact_thread(thread_id)
    except Exception:
        logger.debug("could not record router exchange for %s", thread_id, exc_info=True)


async def _compact_thread(thread_id: str) -> None:
    """Bound a thread's stored history.

    ``_trim_history`` only trims what is *sent to the model*; the checkpoint
    itself accumulates every message forever. Once it passes the threshold,
    drop everything but the recent tail (aligned to a HumanMessage so no
    tool-call pair is orphaned). Best-effort.
    """
    try:
        runtime = await get_runtime()
        config = {"configurable": {"thread_id": thread_id}}
        state = await runtime.local_agent.aget_state(config)
        msgs = (state.values or {}).get("messages", []) if state else []
        if len(msgs) <= COMPACT_THRESHOLD:
            return
        keep = _trim_history(msgs, COMPACT_KEEP)
        drop = msgs[:len(msgs) - len(keep)]
        removals = [RemoveMessage(id=m.id) for m in drop if getattr(m, "id", None)]
        if removals:
            await runtime.local_agent.aupdate_state(
                config, {"messages": removals}, as_node="agent")
            logger.info("compacted thread %s: dropped %d stored messages",
                        thread_id, len(removals))
    except Exception:
        logger.debug("compaction failed for %s", thread_id, exc_info=True)


async def aclose_runtime() -> None:
    """Close the checkpointer's DB connection (server shutdown hook)."""
    if _runtime is None:
        return
    conn = getattr(_runtime.checkpointer, "conn", None)
    if conn is not None:
        try:
            await conn.close()
        except Exception:
            pass


async def forget_thread(thread_id: str) -> None:
    """Drop a thread's checkpoints (used by stateless API requests).

    Checkpointers keep every thread forever; per-request threads would leak.
    Best-effort — older checkpoint backends lack (a)delete_thread.
    """
    if _runtime is None:
        return
    saver = _runtime.checkpointer
    try:
        await saver.adelete_thread(thread_id)
        return
    except (AttributeError, NotImplementedError):
        pass
    except Exception:
        return
    try:
        saver.delete_thread(thread_id)
    except Exception:
        pass
