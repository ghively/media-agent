"""LangChain tool wrappers for library management (naming + inventory).

These expose src/library/naming.py and src/library/scanner.py to the agent.
The underlying functions are synchronous filesystem walks, so they run in a
worker thread to keep the event loop free.
"""
import asyncio

from langchain_core.tools import tool

from src.library import naming, scanner


@tool
async def library_check_naming(path: str, convention: str = "tv") -> str:
    """Check whether files under a directory follow the library naming
    convention, without changing anything.

    Args:
        path: Directory to scan (e.g. /media/tv or a download folder).
        convention: 'tv', 'movie', or 'music'.
    """
    try:
        return await asyncio.to_thread(naming.check_naming, path, convention)
    except Exception as e:
        return f"❌ Naming check failed: {type(e).__name__}: {e}"


@tool
async def library_sort_dir(path: str, convention: str = "tv") -> str:
    """Rename/organize files under a directory to match the library naming
    convention. Writes an undo log so renames can be rolled back with
    library_undo_rename. Use after downloads (music, audiobooks, ROMs,
    YouTube) to organize files into the library.

    Args:
        path: Directory whose files should be organized.
        convention: 'tv', 'movie', or 'music'.
    """
    try:
        return await asyncio.to_thread(naming.fix_naming, path, convention)
    except Exception as e:
        return f"❌ Library sort failed: {type(e).__name__}: {e}"


@tool
async def library_undo_rename(undo_log_path: str) -> str:
    """Roll back a previous library_sort_dir run using its undo log file
    (the path is printed in the library_sort_dir output).

    Args:
        undo_log_path: Path to the undo_*.json log file.
    """
    try:
        return await asyncio.to_thread(naming.undo_rename, undo_log_path)
    except Exception as e:
        return f"❌ Undo failed: {type(e).__name__}: {e}"


@tool
async def library_find_duplicates(path: str, min_size_mb: int = 50) -> str:
    """Find duplicate media files under a directory and report reclaimable
    space ("what's wasting space?"). Uses size + fast partial hashing, so it
    is safe on large libraries. Reports only — deletes nothing.

    Args:
        path: Directory to scan (e.g. /media or /media/movies).
        min_size_mb: Ignore files smaller than this (default 50 MB).
    """
    try:
        return await asyncio.to_thread(scanner.scan_duplicates, path, min_size_mb)
    except Exception as e:
        return f"❌ Duplicate scan failed: {type(e).__name__}: {e}"


@tool
async def library_find_orphans(path: str) -> str:
    """Find media files under a directory that no service manages — not in
    any Sonarr series folder or Radarr movie folder. Orphans are manual
    downloads, leftovers, or unimported files. Reports only — deletes nothing.

    Args:
        path: Directory to scan (e.g. /media).
    """
    try:
        known: list[str] = []
        try:
            from src.tools.sonarr import _client as _sonarr
            series = await _sonarr()._get("/series")
            known.extend(s.get("path", "") for s in series)
        except Exception:
            pass
        try:
            from src.tools.radarr import _client as _radarr
            movies = await _radarr()._get("/movie")
            known.extend(m.get("path", "") for m in movies)
        except Exception:
            pass
        if not known:
            return ("❌ Could not fetch managed paths from Sonarr or Radarr — "
                    "orphan detection needs at least one of them reachable.")
        return await asyncio.to_thread(scanner.scan_orphans, path, known)
    except Exception as e:
        return f"❌ Orphan scan failed: {type(e).__name__}: {e}"


@tool
async def library_inventory(path: str) -> str:
    """Summarize a media directory: file count, total size, and a breakdown
    by file type.

    Args:
        path: Directory to inventory (e.g. /media/movies).
    """
    try:
        return await asyncio.to_thread(scanner.build_inventory, path)
    except Exception as e:
        return f"❌ Inventory failed: {type(e).__name__}: {e}"
