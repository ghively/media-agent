"""Approval gate for high-impact tools.

Policy is config-driven (``approvals:`` in settings.yaml): every tool is
``auto`` (run immediately), ``confirm`` (require explicit user approval), or
``deny`` (never run). Six high-impact tools default to ``confirm``.

The ``confirm`` gate is enforced in code, not by the model. A gated tool's
wrapper receives the live graph state (via LangGraph ``InjectedState``) and
executes only when BOTH hold:

1. the same tool+arguments were already requested earlier this conversation
   (a pending approval exists), and
2. the **user's actual latest message** contains an explicit approval phrase.

The model cannot forge either condition — if it calls a gated tool without a
matching user approval, the wrapper refuses and returns an APPROVAL REQUIRED
notice for the model to relay. Denials clear the pending request.
"""
import json
import re
import time
from typing import Annotated, Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt import InjectedState
from pydantic import create_model

# Tools that default to `confirm` (see docs/AGENT.md for rationale):
# mass file renames, tens-to-hundreds-of-GB transfers, whole-account bulk
# downloads, and download-an-arbitrary-URL.
HIGH_IMPACT_DEFAULTS = {
    "library_sort_dir": "confirm",
    "rom_download": "confirm",
    "bandcamp_download_collection": "confirm",
    "audible_download_new": "confirm",
    "sabnzbd_add_nzb": "confirm",
    "download_station_add": "confirm",
    "remove_tv_show": "confirm",
    "remove_movie": "confirm",
}

VALID_POLICIES = ("auto", "confirm", "deny")

# Word-boundary approval / denial phrases checked against the user's latest
# message. Denial wins when both match ("no, don't do it").
_APPROVE_RE = re.compile(
    r"\b(yes|yep|yeah|approve|approved|confirm|confirmed|go ahead|do it|proceed|sure|ok|okay)\b",
    re.IGNORECASE,
)
_DENY_RE = re.compile(
    r"\b(no|nope|don'?t|stop|cancel|cancelled|deny|denied|abort|never ?mind|wait)\b",
    re.IGNORECASE,
)

# Pending approval requests: fingerprint -> unix timestamp of the request.
# Held in memory (single process serving one household) and mirrored to the
# state directory so a container restart doesn't drop an approval mid-flow.
_PENDING: dict[str, float] = {}
_PENDING_TTL_SECONDS = 15 * 60
_PENDING_MAX = 50
_PENDING_LOADED = False


def _pending_file():
    from src.config import get_state_dir
    return get_state_dir() / "pending_approvals.json"


def _load_pending() -> None:
    global _PENDING_LOADED
    if _PENDING_LOADED:
        return
    _PENDING_LOADED = True
    try:
        data = json.loads(_pending_file().read_text())
        if isinstance(data, dict):
            _PENDING.update({str(k): float(v) for k, v in data.items()})
    except (OSError, ValueError):
        pass


def _save_pending() -> None:
    try:
        _pending_file().write_text(json.dumps(_PENDING))
    except OSError:
        pass


def get_policies() -> dict[str, str]:
    """Effective per-tool policy: high-impact defaults overlaid with the
    ``approvals:`` section of settings.yaml."""
    policies = dict(HIGH_IMPACT_DEFAULTS)
    try:
        from src.config import get_settings
        configured = get_settings()._data.get("approvals", {}) or {}
    except Exception:
        configured = {}
    for name, policy in configured.items():
        policy = str(policy).strip().lower()
        if policy in VALID_POLICIES:
            policies[name] = policy
    return policies


def _fingerprint(tool_name: str, args: dict) -> str:
    return f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}"


def _prune_pending() -> None:
    now = time.time()
    expired = [k for k, ts in _PENDING.items() if now - ts > _PENDING_TTL_SECONDS]
    for k in expired:
        del _PENDING[k]
    while len(_PENDING) > _PENDING_MAX:
        del _PENDING[min(_PENDING, key=_PENDING.get)]


def _last_user_message(state) -> str:
    messages = (state or {}).get("messages", []) if isinstance(state, dict) else \
        getattr(state, "messages", []) or []
    for message in reversed(list(messages)):
        if isinstance(message, HumanMessage) or getattr(message, "type", "") == "human":
            content = message.content
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                )
            return str(content)
    return ""


def _format_args(args: dict) -> str:
    if not args:
        return "(no arguments)"
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def gate_tool(original: BaseTool, policy: str) -> BaseTool:
    """Wrap *original* with a `confirm` or `deny` policy.

    The wrapper keeps the tool's public name/description/argument schema, so
    the model sees no difference; a hidden state field lets the wrapper read
    the conversation to verify real user approval.
    """
    if policy == "deny":
        async def deny_wrapper(**kwargs):
            kwargs.pop("state", None)
            return (
                f"❌ The tool '{original.name}' is disabled by the approvals "
                f"policy in settings.yaml. Tell the user it is unavailable."
            )
        runner = deny_wrapper
    else:  # confirm
        async def confirm_wrapper(**kwargs):
            state = kwargs.pop("state", None)
            _load_pending()
            _prune_pending()
            fp = _fingerprint(original.name, kwargs)
            user_text = _last_user_message(state)
            denied = bool(_DENY_RE.search(user_text))
            approved = bool(_APPROVE_RE.search(user_text)) and not denied

            if fp in _PENDING and approved:
                del _PENDING[fp]
                _save_pending()
                return await original.ainvoke(kwargs)
            if fp in _PENDING and denied:
                del _PENDING[fp]
                _save_pending()
                return (
                    f"🚫 The user declined '{original.name}'. Do not retry; "
                    f"acknowledge and ask what they'd like instead."
                )
            _PENDING[fp] = time.time()
            _save_pending()
            return (
                f"⏸️ APPROVAL REQUIRED — '{original.name}' was NOT executed.\n"
                f"Requested action: {original.name}({_format_args(kwargs)})\n"
                f"Tell the user exactly what this will do and ask for a "
                f"yes/no. If they approve, call {original.name} again with "
                f"the SAME arguments."
            )
        runner = confirm_wrapper

    gated_schema = create_model(
        f"{original.name}_gated_schema",
        __base__=original.args_schema,
        state=(Annotated[Any, InjectedState()], None),
    )
    return StructuredTool(
        name=original.name,
        description=original.description,
        args_schema=gated_schema,
        coroutine=runner,
        metadata={"approval_policy": policy},
    )


def apply_approval_policies(tools: list[BaseTool]) -> list[BaseTool]:
    """Return *tools* with the configured approval policies applied."""
    policies = get_policies()
    gated = []
    for t in tools:
        policy = policies.get(t.name, "auto")
        gated.append(gate_tool(t, policy) if policy in ("confirm", "deny") else t)
    return gated
