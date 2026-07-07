"""Library scanner — walks media directories, fingerprints files, and finds
duplicates by size + content hash."""
import os
import hashlib
from pathlib import Path
from collections import defaultdict

# Sidecar/metadata files that aren't media content
_SKIP_EXTENSIONS = {".nfo", ".srt", ".sub", ".idx", ".jpg", ".png", ".txt"}


def scan_files(path: str) -> list[dict]:
    """Walk a media root and return one fingerprint dict per media file.

    Each entry has: path, name, size, extension, modified.
    Hidden files and sidecar metadata (.nfo, .srt, artwork, ...) are skipped.
    Raises ValueError if the path doesn't exist or isn't a directory.
    """
    root = Path(path)
    if not root.exists():
        raise ValueError(f"Path does not exist: {path}")
    if not root.is_dir():
        raise ValueError(f"Not a directory: {path}")

    inventory = []
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() in _SKIP_EXTENSIONS:
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        inventory.append({
            "path": str(entry),
            "name": entry.name,
            "size": stat.st_size,
            "extension": entry.suffix.lower(),
            "modified": float(stat.st_mtime),
        })
    return inventory


def build_inventory(path: str) -> str:
    """Walk a media root directory and return a formatted inventory summary."""
    try:
        inventory = scan_files(path)
    except ValueError as e:
        return f"❌ {e}"

    total_size = sum(fp["size"] for fp in inventory)
    lines = [
        f"📦 Library inventory for: {path}",
        f"   Files found: {len(inventory)}",
        f"   Total size:  {_format_size(total_size)}",
    ]

    ext_counts = defaultdict(int)
    ext_sizes = defaultdict(int)
    for fp in inventory:
        ext_counts[fp["extension"]] += 1
        ext_sizes[fp["extension"]] += fp["size"]
    if ext_counts:
        lines.append("")
        lines.append("   By type:")
        for ext in sorted(ext_counts):
            lines.append(
                f"     {ext or '(no ext)'}: {ext_counts[ext]} files "
                f"({_format_size(ext_sizes[ext])})"
            )

    return "\n".join(lines)


def find_duplicates(path: str) -> str:
    """Find duplicate files under *path* by grouping on size, then comparing
    a quick content hash (first + last 64 KB). Returns a formatted report."""
    try:
        inventory = scan_files(path)
    except ValueError as e:
        return f"❌ {e}"

    size_groups: dict[int, list[str]] = defaultdict(list)
    for fp in inventory:
        size_groups[fp["size"]].append(fp["path"])

    dupes_found = False
    lines = [
        "🔁 Duplicate File Analysis",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for size, group in sorted(size_groups.items()):
        if len(group) < 2 or size == 0:
            continue
        hashes = defaultdict(list)
        for fp in group:
            try:
                hashes[_quick_hash(fp)].append(fp)
            except OSError:
                pass
        for hgroup in hashes.values():
            if len(hgroup) < 2:
                continue
            dupes_found = True
            lines.append("")
            lines.append(f"   ⚠️  {_format_size(size)} — {len(hgroup)} copies:")
            for fp in hgroup:
                lines.append(f"       • {fp}")

    if not dupes_found:
        lines.append("")
        lines.append("   ✅ No duplicate files detected by size+hash.")

    lines.append("")
    lines.append(f"   (Searched {len(inventory)} files across {len(size_groups)} unique sizes)")
    return "\n".join(lines)


# ── helpers ──────────────────────────────────────────────────────────────


def _format_size(size_bytes: float) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _quick_hash(path: str) -> str:
    """Hash the first and last 64 KB of a file for a fast duplicate check."""
    h = hashlib.md5(usedforsecurity=False)
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        h.update(f.read(65536))
        if size > 65536:
            f.seek(max(0, size - 65536))
            h.update(f.read(65536))
    return h.hexdigest()
