"""Conversational graph using LangGraph's create_react_agent."""
from langgraph.prebuilt import create_react_agent

from src.tools.registry import all_tools
from src.llm.client import create_llm

# Keep this prompt short and behavioral. The full tool schemas are provided
# to the model separately via tool binding — re-listing every tool name here
# only burns context and confuses small local models. Never mention tools
# that are not registered in src/tools/registry.py.
SYSTEM_PROMPT = """You are Media Agent, an assistant that manages a personal media library \
(TV via Sonarr, movies via Radarr, the Emby library, music, audiobooks, ROMs, \
YouTube, and download clients).

How to work:
- Use your tools to answer; never guess library contents or invent results.
- Only call tools that exist in your tool list. If no tool fits, say so plainly.
- To add a TV show or movie: search first (search_tv / search_movie), then:
  - one clear match → add it and confirm what you did.
  - several plausible matches → list them briefly and ask the user which one.
- Answer follow-ups like "the second one" using the earlier search results in this conversation.
- After downloads that produce local files (music, audiobooks, ROMs, YouTube), \
offer to organize them with the library_sort_dir tool.

How to respond:
- Your reply must contain ONLY the answer for the user — plain language and short \
bullet points. Never include tool-call syntax, JSON, or internal reasoning.
- Use ✅ for success, ❌ for errors, ⚠️ for warnings.
- If a tool fails, relay the error briefly and suggest the next step. Do not \
retry the same failing call more than once.
- Keep responses short and concrete."""


def create_agent(checkpointer=None):
    """Create the conversational agent.

    Args:
        checkpointer: Optional LangGraph checkpointer. Pass one (e.g.
            ``InMemorySaver``) when the caller sends only the newest user
            message per turn and needs the graph to remember the
            conversation (the CLI does this). Leave ``None`` when the caller
            resends full message history each request (the OpenAI-compatible
            API does this).
    """
    llm = create_llm()

    agent = create_react_agent(
        llm.agent_model(all_tools),
        tools=all_tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    return agent
