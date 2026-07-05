"""Conversational graph using LangGraph's create_react_agent."""
from langgraph.prebuilt import create_react_agent

from src.tools.registry import all_tools
from src.llm.client import create_llm

SYSTEM_PROMPT = """You are Media Agent, a helpful assistant that manages a personal media library.

You have these capabilities:
• TV shows: search_tv, add_tv_show, list_tv_shows, get_tv_queue, get_tv_history,
  search_missing_episodes, get_tv_calendar, get_tv_health
• Movies: search_movie, add_movie, list_movies, get_movie_queue, get_movie_history,
  search_missing_movies, get_movie_health
• Emby library: emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item
• Health: check_all_health, check_disk_space, check_queue_status
• Music: bandcamp_download, bandcamp_download_collection
• Audiobooks: audible_list_library, audible_download, audible_download_new,
  audible_setup_auth, audible_check_auth
• Classic games: rom_search_archive, rom_download, rom_verify_dat, rom_get_collection
• Library management: library_build_inventory, library_find_duplicates,
  library_check_naming, library_fix_naming, library_undo_rename

Available phase 2 tools (when services are deployed):
• Search all: search_media, download_media
• Download clients: sabnzbd_queue, sabnzbd_pause, sabnzbd_resume
• YouTube: youtube_download, youtube_add_subscription

Guidelines:
- When the user asks to add something, search first, confirm the match, then add.
- Format responses concisely with bullet points.
- Use ✅ for success, ❌ for errors, ⚠️ for warnings.
- If a tool fails, explain what went wrong in plain language.
- If a search returns multiple results, list them and ask which one the user wants.
- Keep responses short — you're a tool-using agent, not a chatbot.
- For downloads that produce local files (Bandcamp, Audible, ROMs, YouTube), tell
  the user to run an Emby library scan to pick up the new files.
"""


def create_agent():
    """Create the conversational agent.

    Uses the local LLM directly. The circuit breaker in MediaLLM handles
    failover — we expose it via get_llm() which returns the appropriate
    BaseChatModel. We wrap it in a thin adapter so LangGraph gets a
    BaseChatModel while the circuit breaker tracks health.

    Note: For full circuit-breaker integration, the agent would need to
    call get_llm() on every invocation. Since create_react_agent binds
    the LLM at construction time, we use local_llm (the common path) and
    rely on Ollama's own retry behavior. The hosted fallback is available
    via the MEDIA_AGENT_API_KEY bypass in Open WebUI if local is down.
    """
    llm = create_llm()
    # Use the local LLM directly — it's the primary path.
    # The MediaLLM wrapper is available for manual failover.
    base_llm = llm.local_llm

    agent = create_react_agent(
        base_llm,
        tools=all_tools,
        prompt=SYSTEM_PROMPT,
    )
    return agent