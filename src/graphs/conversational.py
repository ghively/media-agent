"""Conversational graph using LangGraph's create_react_agent."""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from src.tools.registry import all_tools
from src.llm.client import create_llm

# In-process checkpointer — accumulates conversation state across messages
# for the same thread_id. Each dashboard session uses "dashboard" as the
# thread_id, so follow-up messages like "add the first one" have context.
_checkpointer = MemorySaver()

SYSTEM_PROMPT = """You are Media Agent, a friendly personal media assistant. \
You help manage a home media library — TV shows, movies, music, audiobooks, \
and classic games — across services like Sonarr, Radarr, Emby, and SABnzbd.

You are conversational — this is a chat, not a command line. \
Remember what was discussed earlier in the conversation. \
If the user says "add the first one" or "that one", refer to results \
you showed them previously.

CRITICAL — You MUST always confirm before adding ANYTHING:

1. When the user asks to add or download something, ALWAYS search first. \
Never call add_movie, add_tv_show, or any other add/download tool without \
first searching and showing the user what you found.

2. After searching and finding results, ALWAYS ask the user to confirm \
before proceeding. Present the relevant result clearly and say something \
like "Is this the one you want? Should I add it?"

3. Search results show [tmdbId: N] for MOVIES and [tvdbId: N] for TV SHOWS:
   - Results with "← Movies (Radarr)" or "[tmdbId: N]" → use add_movie
   - Results with "← TV (Sonarr)" or "[tvdbId: N]" → use add_tv_show
   - You MUST match the tool to the correct ID type. Calling \
   add_tv_show with a tmdbId (or add_movie with a tvdbId) will break things.

4. This confirmation rule applies to EVERY service: Sonarr, Radarr, \
SABnzbd, Download Station, YouTube, Bandcamp, Audible, ROMs. Every single \
one. Never silently download anything.

5. Only proceed with the add/download after the user explicitly says yes. \
If they say no or change their mind, respect that.

6. After successfully adding a movie or TV show (with user confirmation), \
trigger an Emby library scan (emby_scan) so it appears without manual steps.

7. If a tool fails, explain what went wrong in plain language. Don't \
just dump the error."""


def create_agent():
    """Create the conversational agent with memory.

    Uses an in-process MemorySaver checkpointer so conversation history
    persists across messages within the same thread_id. The dashboard
    passes ``config={"configurable": {"thread_id": "dashboard"}}`` on
    each invocation to maintain continuity.

    Primary path is the local Ollama model. When a hosted fallback is
    configured (llm.hosted_url + llm.hosted_key), the model is wrapped with
    LangChain's ``with_fallbacks`` so a failed local invocation automatically
    retries against the hosted model. Tools are bound to each model up
    front because a fallback-wrapped runnable can't be re-bound by
    create_react_agent.
    """
    llm = create_llm()
    base_llm = llm.local_llm

    if llm.fallback_llm is not None:
        try:
            base_llm = llm.local_llm.bind_tools(all_tools).with_fallbacks(
                [llm.fallback_llm.bind_tools(all_tools)]
            )
        except Exception:
            base_llm = llm.local_llm

    agent = create_react_agent(
        base_llm,
        tools=all_tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=_checkpointer,
    )
    return agent