"""Audit log of mutating tool calls.

Every tool call that changes state (adds, downloads, renames, pauses, …) is
appended to ``<state>/audit.jsonl`` — one JSON object per line with the tool
name, arguments, outcome summary, and timestamp — so "what did the agent do
while I was out?" is always answerable.

Also enforces a hard cap on tool output length before it reaches the model:
external services return untrusted, unbounded text (torrent titles, video
descriptions); capping bounds both prompt-injection surface and context use.
"""
import json
import re
import time
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

# Read-only tools are not audited. Everything else is.
_READ_ONLY_PATTERNS = re.compile(
    r"^(search_|list_|get_|check_)"
    r"|^(emby_search|emby_recent|emby_libraries|emby_get_item)$"
    r"|^(sabnzbd_queue|sabnzbd_history|sabnzbd_status)$"
    r"|^(download_station_list|download_station_info|download_station_stats)$"
    r"|^(youtube_get_info|youtube_list_subscriptions)$"
    r"|^(audible_list_library|audible_check_auth|audible_setup_auth)$"
    r"|^(rom_search_archive|rom_get_collection|rom_verify_dat)$"
    r"|^(library_check_naming|library_inventory)$"
)

MAX_TOOL_OUTPUT_CHARS = 8000


def is_mutating(tool_name: str) -> bool:
    return not _READ_ONLY_PATTERNS.match(tool_name)


def _audit_path():
    from src.config import get_state_dir
    return get_state_dir() / "audit.jsonl"


def record(tool_name: str, args: dict, outcome: str) -> None:
    """Append one audit entry. Failures to write never break the tool call."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": tool_name,
        "args": {k: v for k, v in args.items() if k != "state"},
        # first line of the outcome is enough to know what happened
        "outcome": (outcome or "").split("\n")[0][:300],
    }
    try:
        with open(_audit_path(), "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass


def _cap(text: Any) -> Any:
    if isinstance(text, str) and len(text) > MAX_TOOL_OUTPUT_CHARS:
        return text[:MAX_TOOL_OUTPUT_CHARS] + "\n… [output truncated]"
    return text


def wrap_audit(tool: BaseTool) -> BaseTool:
    """Wrap *tool* so its calls are audited (if mutating) and its output is
    length-capped. Keeps the tool's schema — including any hidden injected
    state field added by the approval gate."""
    audited = is_mutating(tool.name)

    async def wrapper(**kwargs):
        try:
            result = await tool.ainvoke(kwargs)
        except Exception as e:
            if audited:
                record(tool.name, kwargs, f"EXCEPTION {type(e).__name__}: {e}")
            raise
        if audited:
            record(tool.name, kwargs, str(result))
        return _cap(result)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=wrapper,
        metadata=tool.metadata,
    )


def apply_audit(tools: list[BaseTool]) -> list[BaseTool]:
    return [wrap_audit(t) for t in tools]
