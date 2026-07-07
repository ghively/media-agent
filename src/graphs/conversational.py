"""Conversational graph using LangGraph's create_react_agent."""
from src.tools.registry import all_tools

_BASE_PROMPT = """You are Media Agent, a helpful assistant that manages a personal media library
(TV via Sonarr, movies via Radarr, the Emby library, downloads via SABnzbd and
Synology Download Station, plus music, audiobooks, YouTube, and classic-game ROMs).

You have these tools:
{tool_list}

Guidelines:
- When the user asks to add something, search first, confirm the match, then add.
- Format responses concisely with bullet points.
- Use ✅ for success, ❌ for errors, ⚠️ for warnings.
- If a tool fails, explain what went wrong in plain language.
- If a search returns multiple results, list them and ask which one the user wants.
- Keep responses short — you're a tool-using agent, not a chatbot.
- For downloads that produce local files (Bandcamp, Audible, ROMs, YouTube), offer
  to organize them with library_fix_naming (check first with library_check_naming).
"""


def build_system_prompt(tools: list | None = None) -> str:
    """Build the system prompt with the tool list generated from the registry,
    so the prompt can never reference tools that don't exist."""
    tools = all_tools if tools is None else tools
    lines = []
    for t in tools:
        summary = (t.description or "").strip().split("\n")[0]
        lines.append(f"• {t.name} — {summary}")
    return _BASE_PROMPT.format(tool_list="\n".join(lines))


def create_agent():
    """Create the conversational agent (local LLM with hosted fallback if configured)."""
    from langgraph.prebuilt import create_react_agent
    from src.llm.client import create_llm

    llm = create_llm()
    model = llm.runnable(all_tools)

    agent = create_react_agent(
        model,
        tools=all_tools,
        prompt=build_system_prompt(),
    )
    return agent
