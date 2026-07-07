"""Conversational agents — one compact agent per domain.

Small local models degrade sharply when many tool schemas are bound and
prompts are long. Instead of one agent with ~60 tools, each request is
routed (deterministically, see router.py) to a domain agent that binds
only the tools for that domain, with a short system prompt generated
from those tools. Agents are cached per domain.
"""
from src.graphs.router import CORE, route
from src.tools.registry import all_tools

_BASE_PROMPT = """You are Media Agent. You manage a personal media server with tools.

Tools:
{tool_list}

Rules:
- Prefer workflow tools (grab_media, system_report, library_cleanup, sync_youtube): one call does search+act+verify.
- Use as few tool calls as possible. Do not repeat a call that already answered.
- Only report success when tool output shows ✅. Treat ⚠️/❌ as not done and say so.
- If a tool returns numbered options, show them briefly and ask the user to pick one; then call download_media(number).
- Reply in short bullets. No filler, no preamble."""

# Tool names bound per domain. CORE covers cross-domain and generic asks
# with high-level workflow tools only.
DOMAIN_TOOLS: dict[str, list[str]] = {
    CORE: [
        "grab_media", "search_media", "download_media", "system_report",
        "sync_youtube", "library_cleanup", "check_queue_status",
    ],
    "tv": [
        "grab_media", "search_tv", "add_tv_show", "list_tv_shows",
        "get_tv_queue", "get_tv_history", "search_missing_episodes",
        "get_tv_calendar", "get_tv_health",
    ],
    "movies": [
        "grab_media", "search_movie", "add_movie", "list_movies",
        "get_movie_queue", "get_movie_history", "search_missing_movies",
        "get_movie_health",
    ],
    "library": [
        "library_cleanup", "library_inventory", "library_find_duplicates",
        "library_check_naming", "library_fix_naming", "library_undo_rename",
        "emby_search", "emby_recent", "emby_libraries", "emby_scan",
        "emby_get_item",
    ],
    "downloads": [
        "check_queue_status", "sabnzbd_queue", "sabnzbd_history",
        "sabnzbd_status", "sabnzbd_pause", "sabnzbd_resume", "sabnzbd_add_nzb",
        "download_station_list", "download_station_add",
        "download_station_pause", "download_station_resume",
        "download_station_info", "download_station_stats",
    ],
    "audio": [
        "bandcamp_download", "bandcamp_download_collection",
        "audible_list_library", "audible_download", "audible_download_new",
        "audible_setup_auth", "audible_check_auth",
    ],
    "youtube": [
        "sync_youtube", "youtube_download", "youtube_get_info",
        "youtube_add_subscription", "youtube_remove_subscription",
        "youtube_list_subscriptions", "youtube_check_subscriptions",
    ],
    "roms": [
        "rom_search_archive", "rom_download", "rom_verify_dat",
        "rom_get_collection",
    ],
    "system": [
        "system_report", "check_all_health", "check_disk_space",
        "check_queue_status", "get_tv_health", "get_movie_health",
    ],
}

_TOOLS_BY_NAME = {t.name: t for t in all_tools}
_agent_cache: dict[str, object] = {}


def tools_for_domain(domain: str) -> list:
    """Resolve a domain's tool names against the registry (missing tools
    — e.g. an optional group that failed to load — are skipped)."""
    names = DOMAIN_TOOLS.get(domain, DOMAIN_TOOLS[CORE])
    return [_TOOLS_BY_NAME[n] for n in names if n in _TOOLS_BY_NAME]


def build_system_prompt(tools: list | None = None) -> str:
    """Build a compact system prompt from a toolset. One bullet per tool,
    first sentence only, so the prompt can never reference missing tools."""
    tools = all_tools if tools is None else tools
    lines = []
    for t in tools:
        summary = (t.description or "").strip().split("\n")[0][:100]
        lines.append(f"• {t.name} — {summary}")
    return _BASE_PROMPT.format(tool_list="\n".join(lines))


def create_agent(domain: str = CORE):
    """Create the agent for a domain (local LLM with hosted fallback)."""
    from langgraph.prebuilt import create_react_agent
    from src.llm.client import create_llm

    tools = tools_for_domain(domain)
    llm = create_llm()
    model = llm.runnable(tools)

    return create_react_agent(
        model,
        tools=tools,
        prompt=build_system_prompt(tools),
    )


def get_agent(domain: str = CORE):
    """Cached create_agent."""
    if domain not in _agent_cache:
        _agent_cache[domain] = create_agent(domain)
    return _agent_cache[domain]


def _recursion_limit() -> int:
    """Cap on ReAct steps per request (keeps a confused small model from
    looping through the token budget). Configurable via llm.recursion_limit."""
    try:
        from src.config import get_settings
        return int(get_settings().llm.get("recursion_limit", 12))
    except Exception:
        return 12


def resolve_agent(messages: list[dict], domain: str | None = None):
    """Pick the agent for a conversation: explicit domain override, or
    deterministic routing on the latest user message."""
    if domain is None:
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        domain = route(last_user)
    return get_agent(domain), domain


async def run_agent(messages: list[dict], domain: str | None = None) -> str:
    """Route, invoke with a bounded step budget, and return the final text."""
    agent, _ = resolve_agent(messages, domain)
    result = await agent.ainvoke(
        {"messages": messages},
        config={"recursion_limit": _recursion_limit()},
    )
    return result["messages"][-1].content
