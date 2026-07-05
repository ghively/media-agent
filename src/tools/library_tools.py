"""Library management tools — wraps scanner and naming modules as LangChain tools."""
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
    return _build_inventory(path)


@tool
async def library_find_duplicates(path: str) -> str:
    """Find duplicate media files in a directory by comparing file sizes and content hashes.
    Use this to identify duplicate movies, shows, or music taking up extra space.
    Pass the directory path to scan."""
    inventory = _build_inventory(path)
    return _find_duplicates(inventory)


@tool
async def library_check_naming(path: str, convention: str = "tv") -> str:
    """Check filenames in a directory against naming conventions.
    Conventions: 'tv', 'movie', or 'music'. Returns violations with suggested fixes.
    Pass the directory path and the convention to check against."""
    return _check_naming(path, convention)


@tool
async def library_fix_naming(path: str, convention: str = "tv") -> str:
    """Rename files to match naming conventions. Creates an undo log before renaming.
    Conventions: 'tv', 'movie', or 'music'. Returns a summary of renames made.
    Pass the directory path and the convention to apply."""
    return _fix_naming(path, convention)


@tool
async def library_undo_rename(undo_log_path: str) -> str:
    """Revert a batch rename using an undo log created by library_fix_naming.
    Pass the path to the undo log file (from the .media_agent_undo/ directory)."""
    return _undo_rename(undo_log_path)
