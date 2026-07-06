"""Post-processing for local-model output.

Small local models (qwen3 / qwen3.5, deepseek-r1, etc.) leak two kinds of
non-answer text into their message content:

1. Reasoning traces — ``<think> ... </think>`` blocks emitted inline when
   Ollama does not separate thinking (langchain-ollama's ``reasoning=False``
   is unreliable for Qwen-family models, so we strip defensively here).
2. Raw tool-call syntax — when a model fails to use structured tool calling
   it may print ``<tool_call>{...}</tool_call>`` or a bare JSON blob like
   ``{"name": "search_tv", "arguments": {...}}`` as plain text.

Everything user-facing must go through :func:`clean_response`.
"""
import json
import re

from langchain_core.messages import BaseMessage

# <think>...</think> (also <thinking>) — closed blocks anywhere in the text
_THINK_BLOCK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
# An opening tag that never got closed (model cut off) — drop to end of text
_THINK_OPEN = re.compile(r"<think(?:ing)?>.*\Z", re.DOTALL | re.IGNORECASE)
# Inline pseudo tool-call markup some chat templates leak as text
_TOOL_CALL_BLOCK = re.compile(r"<(tool_call|function_call)>.*?</\1>", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove <think> blocks and leaked tool-call markup from *text*."""
    text = _THINK_BLOCK.sub("", text)
    text = _THINK_OPEN.sub("", text)
    text = _TOOL_CALL_BLOCK.sub("", text)
    return text.strip()


def _looks_like_tool_call_json(text: str) -> bool:
    """True if *text* is nothing but a JSON blob shaped like a tool call."""
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return False
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    keys = set(data.keys())
    return bool(
        {"name", "arguments"} <= keys
        or {"name", "parameters"} <= keys
        or {"tool", "tool_input"} <= keys
        or {"function", "arguments"} <= keys
    )


def message_text(message: BaseMessage) -> str:
    """Extract plain text from a message whose content may be a list of blocks."""
    content = message.content
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


def clean_response(message: BaseMessage) -> str:
    """Turn the agent's final message into user-safe text.

    Strips reasoning traces and leaked tool-call syntax. Returns a fallback
    notice if nothing readable remains (e.g. the model emitted only a raw
    tool call the runtime could not execute).
    """
    text = strip_reasoning(message_text(message))
    if not text or _looks_like_tool_call_json(text):
        return (
            "⚠️ The model did not produce a readable answer "
            "(it may have emitted a malformed tool call). "
            "Try rephrasing, or switch to a stronger model "
            "(see the model recommendations in the README)."
        )
    return text
