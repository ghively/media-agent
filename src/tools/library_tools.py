"""Library management tools — wraps scanner and naming modules as LangChain tools.

The scanner/naming functions do synchronous, potentially long filesystem work
(directory walks, hashing, renames). These async wrappers offload that work to
a worker thread via ``asyncio.to_thread`` so a large scan never blocks the event
loop (and with it every other request + the scheduler), and wrap it in
try/except so a tool never raises — per project convention it returns
``❌ Error: ...`` instead.
"""
import asyncio

from langchain_core.tools import tool

from src.library.scanner import build_inventory as _build_inventory
from src.library.scanner import find_duplicates as _find_duplicates
from src.library.naming import check_naming as _check_naming
from src.library.naming import fix_naming as _fix_naming
from src.library.naming import undo_rename as _undo_rename


@tool
async def library_build_inventory(path: str) -> str:
    """Walk a media directory and build a file inventory with sizes and types.
    Use this to audit what's on disk — total size, file count, breakdown by extension.
    Pass the directory path (e.g. /media/movies or /media/tv)."""
    try:
        return await asyncio.to_thread(_build_inventory, path)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"


@tool
async def library_find_duplicates(path: str) -> str:
    """Find duplicate media files in a directory by comparing file sizes and content hashes.
    Use this to identify duplicate movies, shows, or music taking up extra space.
    Pass the directory path to scan."""
    try:
        return await asyncio.to_thread(_find_duplicates, path)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"


@tool
async def library_check_naming(path: str, convention: str = "tv") -> str:
    """Check filenames in a directory against naming conventions.
    Conventions: 'tv', 'movie', or 'music'. Returns violations with suggested fixes.
    Pass the directory path and the convention to check against."""
    try:
        return await asyncio.to_thread(_check_naming, path, convention)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"


@tool
async def library_fix_naming(path: str, convention: str = "tv") -> str:
    """Rename files to match naming conventions. Creates an undo log before renaming.
    Conventions: 'tv', 'movie', or 'music'. Returns a summary of renames made.
    Pass the directory path and the convention to apply."""
    try:
        return await asyncio.to_thread(_fix_naming, path, convention)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"


@tool
async def library_undo_rename(undo_log_path: str) -> str:
    """Revert a batch rename using an undo log created by library_fix_naming.
    Pass the path to the undo log file (from the .media_agent_undo/ directory)."""
    try:
        return await asyncio.to_thread(_undo_rename, undo_log_path)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"
