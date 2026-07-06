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

Guidelines:
- When the user asks to add something, search first, then add — unless you \
already have results from earlier in the conversation, in which case use them.
- If a search returns multiple results, present them clearly and ask which one.
- Use ✅ for success, ❌ for errors, ⚠️ for warnings.
- If a tool fails, explain what went wrong in plain, friendly language.
- Be natural and conversational. Greet, acknowledge, confirm. \
Don't just dump tool output — frame it like a helpful assistant would.
- Keep responses focused but warm. A sentence of context beats a bare list.
- After adding any movie or TV show, automatically trigger an Emby library scan \
so it shows up without the user needing to do anything manually. The whole point \
of this assistant is end-to-end automation — the user asks, you handle every step. \
Same applies to any download that produces local files (Bandcamp, Audible, ROMs, YouTube).
"""


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