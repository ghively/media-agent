"""Append-only audit trail of agent tool invocations.

The agent renames files and starts multi-GB downloads; when something looks
wrong a week later, "which tool ran, with what arguments, and what came back"
must be answerable. Every LLM-path tool call is appended as one JSON line to
``/state/tool_audit.jsonl`` (on the persistent state volume).

Router-path tool calls don't pass through LangChain callbacks — they are
covered by the router's own ``router: intent ... handled`` log lines, and
every destructive router action is user-confirmed first.

Best-effort by design: audit failures are logged at debug and never break a
tool call. If the state volume is missing, auditing is silently disabled.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)

_AUDIT_PATH = Path(os.environ.get("MEDIA_AGENT_STATE_DIR", "/state")) / "tool_audit.jsonl"
_MAX_FIELD_CHARS = 500


def _clip(value) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text[:_MAX_FIELD_CHARS]


def _write_line(entry: dict) -> None:
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        logger.debug("audit write failed", exc_info=True)


class ToolAuditHandler(AsyncCallbackHandler):
    """LangChain callback that journals tool start/end/error events."""

    def __init__(self):
        self._starts: dict[str, float] = {}

    @staticmethod
    def _base(run_id, name: str) -> dict:
        return {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": str(run_id),
            "tool": name,
        }

    async def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        name = (serialized or {}).get("name", "unknown")
        self._starts[str(run_id)] = time.monotonic()
        entry = self._base(run_id, name) | {
            "event": "start",
            "args": _clip(inputs if inputs is not None else input_str),
        }
        await asyncio.to_thread(_write_line, entry)

    async def on_tool_end(self, output, *, run_id, **kwargs):
        started = self._starts.pop(str(run_id), None)
        entry = self._base(run_id, kwargs.get("name", "")) | {
            "event": "end",
            "result": _clip(getattr(output, "content", output)),
        }
        if started is not None:
            entry["seconds"] = round(time.monotonic() - started, 2)
        await asyncio.to_thread(_write_line, entry)

    async def on_tool_error(self, error, *, run_id, **kwargs):
        self._starts.pop(str(run_id), None)
        entry = self._base(run_id, kwargs.get("name", "")) | {
            "event": "error",
            "error": _clip(f"{type(error).__name__}: {error}"),
        }
        await asyncio.to_thread(_write_line, entry)
