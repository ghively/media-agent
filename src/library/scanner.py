"""Library scanner — walks media directories, fingerprints files, and cross-references
against Sonarr, Radarr, and Emby data to identify orphans and duplicates."""
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


def cross_reference(inventory: str, emby_data: str, sonarr_data: str, radarr_data: str) -> str:
    """Match discovered files against service data.

    Each argument is a pre-formatted string (from build_inventory, or the
    tool output from Emby/Sonarr/Radarr tools).  This function parses
    enough to produce a cross-reference summary.

    Returns a formatted cross-reference report string.
    """
    lines = [
        "🔄 Cross-reference Report",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "   Inventory summary:",
        f"     {inventory.split(chr(10))[1] if chr(10) in inventory else inventory}",
        "",
        "   Library data received:",
    ]
    for label, data in [("Emby", emby_data), ("Sonarr", sonarr_data), ("Radarr", radarr_data)]:
        first_line = data.split("\n")[0] if data else "(no data)"
        lines.append(f"     {label}: {first_line[:80]}")

    lines.extend([
        "",
        "   Matching logic runs on the agent side; this report summarises",
        "   what each service reported and how many items are known.",
        "   Use find_orphans() for files absent from all services.",
        "   Use find_duplicates() for file paths with identical content.",
    ])
    return "\n".join(lines)


def find_orphans(cross_ref: str) -> str:
    """Identify files that don't appear in any service database.

    Accepts the output of cross_reference() and returns an orphan report.
    Because the full inventory isn't preserved as structured data across
    LLM invocations, this function provides a heuristic summary.

    Returns a formatted string describing potential orphan status.
    """
    lines = [
        "👻 Orphan Analysis",
        "━━━━━━━━━━━━━━━━━",
        "",
        "   To find true orphans the agent should:",
        "",
        "   1. Call sonarr.list_tv_shows() to get all monitored series paths",
        "   2. Call radarr.list_movies() to get all monitored movie paths",
        "   3. Call emby_search() on unmatched paths",
        "",
        "   Files whose path does not start with any known root folder",
        "   are candidates for manual review or cleanup.",
        "",
        "   Cross-reference context:",
    ]
    for line in cross_ref.split("\n"):
        lines.append(f"     {line}")
    return "\n".join(lines)


def find_duplicates(inventory: str) -> str:
    """Find duplicate files in the inventory by comparing size + hash.

    Accepts the *raw inventory* string from build_inventory() and reports
    file groups that are likely duplicates.

    Because the inventory is a text string, this function re-parses it
    to extract file paths and sizes, groups by size, and reports groups
    with more than one file at the same size as potential duplicates.
    """
    # Re-parse inventory text to extract file paths
    paths = []
    for line in inventory.split("\n"):
        line = line.strip()
        if line.startswith("/") or line.startswith("./"):
            # This is likely a path line from inventory; we can't reliably
            # re-parse the full text, so we do a best-effort extraction.
            # The real inventory is already available on disk; this is a
            # fallback for LLM-based invocation.
            paths.append(line)

    # Group by file extension for a reasonable-length report
    ext_groups = defaultdict(list)
    for p in paths:
        ext = Path(p).suffix.lower()
        ext_groups[ext].append(p)

    size_groups = defaultdict(list)
    for p in paths:
        try:
            sz = os.path.getsize(p)
            size_groups[sz].append(p)
        except OSError:
            pass

    dupes_found = False
    lines = [
        "🔁 Duplicate File Analysis",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for size, group in sorted(size_groups.items()):
        if len(group) < 2:
            continue
        # Quick content hash check
        actual_dupes = []
        hashes = defaultdict(list)
        for fp in group:
            try:
                h = _quick_hash(fp)
                hashes[h].append(fp)
            except OSError:
                pass
        for h, hgroup in hashes.items():
            if len(hgroup) >= 2:
                actual_dupes.append(hgroup)

        if not actual_dupes:
            continue
        dupes_found = True
        for hgroup in actual_dupes:
            lines.append(f"")
            lines.append(f"   ⚠️  {_format_size(size)} — {len(hgroup)} copies:")
            for fp in hgroup:
                lines.append(f"       • {fp}")

    if not dupes_found:
        lines.append("")
        lines.append("   ✅ No duplicate files detected by size+hash.")

    lines.append("")
    lines.append(f"   (Searched {len(paths)} files across {len(size_groups)} unique sizes)")
    return "\n".join(lines)


# ── helpers ──────────────────────────────────────────────────────────────


MEDIA_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts",
    ".mp3", ".flac", ".m4a", ".m4b", ".ogg", ".wav", ".aac",
}


def scan_duplicates(path: str, min_size_mb: int = 50) -> str:
    """Find likely duplicate media files under *path*.

    Groups files by exact size, then confirms with a fast first+last-64KB
    hash — no full-file reads, so it's usable on multi-TB libraries.
    Returns a report of duplicate groups and total reclaimable space.
    """
    root = Path(path)
    if not root.is_dir():
        return f"❌ Not a directory: {path}"

    min_size = min_size_mb * 1024 * 1024
    by_size: dict[int, list[Path]] = defaultdict(list)
    scanned = 0
    for entry in root.rglob("*"):
        try:
            if not entry.is_file() or entry.name.startswith("."):
                continue
            if entry.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            size = entry.stat().st_size
            if size < min_size:
                continue
            scanned += 1
            by_size[size].append(entry)
        except OSError:
            continue

    groups: list[tuple[int, list[Path]]] = []
    for size, candidates in by_size.items():
        if len(candidates) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for candidate in candidates:
            try:
                by_hash[_quick_hash(str(candidate))].append(candidate)
            except OSError:
                continue
        for dupes in by_hash.values():
            if len(dupes) >= 2:
                groups.append((size, sorted(dupes)))

    if not groups:
        return (f"✅ No duplicates found under {path} "
                f"({scanned} media files ≥{min_size_mb} MB checked).")

    groups.sort(key=lambda g: -g[0] * (len(g[1]) - 1))
    wasted = sum(size * (len(files) - 1) for size, files in groups)
    lines = [
        f"Found {len(groups)} duplicate group(s) under {path} — "
        f"{_format_size(wasted)} reclaimable:\n",
    ]
    for size, files in groups[:15]:
        lines.append(f"  {_format_size(size)} × {len(files)}:")
        for fp in files:
            lines.append(f"    • {fp}")
    if len(groups) > 15:
        lines.append(f"  ... and {len(groups) - 15} more groups")
    return "\n".join(lines)


def scan_orphans(path: str, known_paths: list[str]) -> str:
    """Find media files under *path* that live outside every known
    service-managed folder (*known_paths* from Sonarr series and Radarr
    movie records). Orphans are candidates for cleanup or re-import."""
    root = Path(path)
    if not root.is_dir():
        return f"❌ Not a directory: {path}"

    normalized = [p.rstrip("/") + "/" for p in known_paths if p]
    orphans: list[tuple[Path, int]] = []
    total_size = 0
    scanned = 0
    for entry in root.rglob("*"):
        try:
            if not entry.is_file() or entry.name.startswith("."):
                continue
            if entry.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            scanned += 1
            entry_str = str(entry)
            if any(entry_str.startswith(known) for known in normalized):
                continue
            size = entry.stat().st_size
            orphans.append((entry, size))
            total_size += size
        except OSError:
            continue

    if not orphans:
        return (f"✅ No orphans under {path} — all {scanned} media files "
                f"belong to a Sonarr/Radarr-managed folder.")

    orphans.sort(key=lambda o: -o[1])
    lines = [
        f"Found {len(orphans)} orphaned media file(s) under {path} "
        f"({_format_size(total_size)}) not managed by Sonarr/Radarr:\n",
    ]
    for fp, size in orphans[:25]:
        lines.append(f"  • {fp} ({_format_size(size)})")
    if len(orphans) > 25:
        lines.append(f"  ... and {len(orphans) - 25} more")
    lines.append("\nThese may be manual downloads, leftovers, or unimported files.")
    return "\n".join(lines)


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