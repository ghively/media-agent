"""Library scanner — walks media directories, builds inventories, and finds
duplicate files by size + content fingerprint."""
import os
import hashlib
from pathlib import Path
from collections import defaultdict


def build_inventory(path: str) -> str:
    """Walk a media root directory and build a file inventory.

    Fingerprints each file by path, size, and extension.
    Returns a formatted summary string.
    """
    root = Path(path)
    if not root.exists():
        return f"❌ Path does not exist: {path}"
    if not root.is_dir():
        return f"❌ Not a directory: {path}"

    inventory = []
    errors = []
    total_size = 0

    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        # Skip hidden files and common metadata
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() in (".nfo", ".srt", ".sub", ".idx", ".jpg", ".png", ".txt"):
            continue

        try:
            stat = entry.stat()
            fp = {
                "path": str(entry),
                "name": entry.name,
                "size": stat.st_size,
                "extension": entry.suffix.lower(),
                "modified": float(stat.st_mtime),
            }
            inventory.append(fp)
            total_size += stat.st_size
        except OSError as e:
            errors.append(f"  ⚠️  {entry}: {e}")

    lines = [
        f"📦 Library inventory for: {path}",
        f"   Files found: {len(inventory)}",
        f"   Total size:  {_format_size(total_size)}",
    ]
    # Break down by extension
    ext_counts = defaultdict(int)
    ext_sizes = defaultdict(int)
    for fp in inventory:
        ext_counts[fp["extension"]] += 1
        ext_sizes[fp["extension"]] += fp["size"]
    if ext_counts:
        lines.append("")
        lines.append("   By type:")
        for ext in sorted(ext_counts):
            lines.append(f"     {ext or '(no ext)'}: {ext_counts[ext]} files ({_format_size(ext_sizes[ext])})")

    if errors:
        lines.append("")
        lines.append("   Errors encountered:")
        lines.extend(errors)

    return "\n".join(lines)


def find_duplicates(path: str) -> str:
    """Find duplicate files under a directory by grouping on size, then
    confirming with a fast content hash.

    Walks the tree directly (using the same file filters as build_inventory)
    rather than re-parsing a summary string, so it actually inspects files.
    Reports each group of 2+ files sharing an identical size and head/tail
    hash as likely duplicates.
    """
    root = Path(path)
    if not root.exists():
        return f"❌ Path does not exist: {path}"
    if not root.is_dir():
        return f"❌ Not a directory: {path}"

    # Collect candidate files grouped by size (same skip filters as build_inventory)
    size_groups = defaultdict(list)
    scanned = 0
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() in (".nfo", ".srt", ".sub", ".idx", ".jpg", ".png", ".txt"):
            continue
        try:
            sz = entry.stat().st_size
        except OSError:
            continue
        scanned += 1
        size_groups[sz].append(str(entry))

    dupes_found = False
    lines = [
        "🔁 Duplicate File Analysis",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Largest first — biggest space wins are most actionable.
    for size, group in sorted(size_groups.items(), reverse=True):
        if len(group) < 2:
            continue
        # Confirm same-size candidates with a quick content hash.
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
    lines.append(f"   (Searched {scanned} files across {len(size_groups)} unique sizes)")
    return "\n".join(lines)


# ── helpers ──────────────────────────────────────────────────────────────


def _format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _quick_hash(path: str, blocks: int = 3) -> str:
    """Read the first and last 64 KB of a file for a fast duplicate check."""
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        # First 64 KB
        h.update(f.read(65536))
    with open(path, "rb") as f:
        # Last 64 KB
        f.seek(max(0, os.path.getsize(path) - 65536))
        h.update(f.read(65536))
    return h.hexdigest()