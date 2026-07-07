"""Workflow tools — one call runs a complete deterministic pipeline.

These are the preferred tools for the agent: each collapses a multi-step
search/act/verify flow into a single tool call, which keeps ReAct loops
short and token usage low on small local models.
"""
from langchain_core.tools import tool

from src.workflows import pipelines


@tool
async def grab_media(query: str, kind: str | None = None) -> str:
    """Find a TV show or movie by name and add it to the library in one step.
    Searches, auto-adds when one match clearly wins, and verifies the add.
    If several matches are plausible it returns a numbered list — ask the
    user to pick, then call download_media(number).

    Args:
        query: Title to find (e.g. 'Severance').
        kind: Optional 'tv' or 'movie' to skip the other search.
    """
    return await pipelines.grab_media(query, kind)


@tool
async def system_report() -> str:
    """Full system status in one call: service health, download queues,
    and disk space across Sonarr, Radarr, Emby, and SABnzbd."""
    return await pipelines.system_report()


@tool
async def sync_youtube(max_downloads: int = 3) -> str:
    """Check all YouTube subscriptions and download new uploads automatically.
    Downloads are verified on disk before being marked done.

    Args:
        max_downloads: Cap on downloads this run (default 3).
    """
    return await pipelines.sync_youtube(max_downloads)


@tool
async def library_cleanup(path: str, convention: str = "tv") -> str:
    """Check naming in a directory, fix violations, and re-check to verify.
    Reversible — reports the undo command at the end.

    Args:
        path: Absolute path of the directory to clean up.
        convention: 'movie', 'tv', or 'music'.
    """
    return await pipelines.library_cleanup(path, convention)
