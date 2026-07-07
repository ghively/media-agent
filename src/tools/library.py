"""Library management tools — inventory, naming checks/fixes, duplicates.

Exposes the functions in src/library/ to the agent. Renames are reversible:
fix operations write an undo log that library_undo_rename can replay.
"""
import asyncio

from langchain_core.tools import tool

from src.library import naming, scanner


@tool
async def library_inventory(path: str) -> str:
    """Scan a media directory and summarize its contents (file counts, sizes, types).

    Args:
        path: Absolute path of the media directory to scan.
    """
    try:
        return await asyncio.to_thread(scanner.build_inventory, path)
    except Exception as e:
        return f"❌ Inventory failed: {type(e).__name__}: {e}"


@tool
async def library_find_duplicates(path: str) -> str:
    """Find duplicate files in a media directory by size and content hash.

    Args:
        path: Absolute path of the media directory to scan.
    """
    try:
        return await asyncio.to_thread(scanner.find_duplicates, path)
    except Exception as e:
        return f"❌ Duplicate scan failed: {type(e).__name__}: {e}"


@tool
async def library_check_naming(path: str, convention: str = "tv") -> str:
    """Check filenames in a directory against a naming convention without changing anything.

    Args:
        path: Absolute path of the directory to check.
        convention: One of 'movie' (Title (Year)/Title (Year).ext),
                    'tv' (Show/Season ##/Show - s##e## - Title.ext),
                    or 'music' (Artist/Album/Track ## - Title.ext).
    """
    try:
        return await asyncio.to_thread(naming.check_naming, path, convention)
    except Exception as e:
        return f"❌ Naming check failed: {type(e).__name__}: {e}"


@tool
async def library_fix_naming(path: str, convention: str = "tv") -> str:
    """Rename files in a directory to match a naming convention.

    Writes an undo log to {path}/.media_agent_undo/ so the batch can be
    reverted with library_undo_rename. Check first with library_check_naming.

    Args:
        path: Absolute path of the directory to fix.
        convention: One of 'movie', 'tv', or 'music'.
    """
    try:
        return await asyncio.to_thread(naming.fix_naming, path, convention)
    except Exception as e:
        return f"❌ Naming fix failed: {type(e).__name__}: {e}"


@tool
async def library_undo_rename(undo_log_path: str) -> str:
    """Revert a batch of renames made by library_fix_naming.

    Args:
        undo_log_path: Path to the .media_agent_undo/undo_*.json log file
                       reported by library_fix_naming.
    """
    try:
        return await asyncio.to_thread(naming.undo_rename, undo_log_path)
    except Exception as e:
        return f"❌ Undo failed: {type(e).__name__}: {e}"
