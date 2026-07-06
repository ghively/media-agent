"""Disk-space preflight for bulk downloads.

Bulk operations (ROM sets, whole collections) can be tens to hundreds of GB.
Before starting one, check free space at the destination and refuse when it
is below the configured floor (``library.min_free_gb``, default 10)."""
import shutil
from pathlib import Path


def min_free_gb() -> float:
    from src.config import get_settings
    try:
        return float(get_settings().library.get("min_free_gb", 10))
    except (TypeError, ValueError):
        return 10.0


def disk_preflight(path: str, needed_gb: float | None = None) -> str | None:
    """Return an error string when the download should not start, else None.

    Args:
        path: Destination directory (nearest existing parent is measured).
        needed_gb: Estimated size when known; free space must cover it plus
            the configured floor. When unknown, only the floor is enforced.
    """
    target = Path(path)
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        free_gb = shutil.disk_usage(target).free / (1024 ** 3)
    except OSError as e:
        return f"❌ Cannot check disk space at {path}: {e}"

    floor = min_free_gb()
    required = floor + (needed_gb or 0)
    if free_gb < required:
        need = f" (~{needed_gb:.1f} GB needed)" if needed_gb else ""
        return (
            f"❌ Not enough disk space: {free_gb:.1f} GB free at {target}, "
            f"but {required:.1f} GB required{need} "
            f"(floor is {floor:.0f} GB — 'library.min_free_gb' in settings). "
            f"Free up space or lower the floor, then retry."
        )
    return None
