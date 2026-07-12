"""ROM library tools — identify, inspect, debug, and dedup the ROM collection.

Wraps :mod:`src.library.rom_analyzer` as LangChain tools. All analysis is
synchronous filesystem work (walks, header reads, CRC hashing), so every call
is offloaded via ``asyncio.to_thread`` — a big library scan never blocks the
event loop.

Paths are confined to the ROM library (``services.roms``) or the media root
(``library.media_root``): the agent is network-reachable, so unbounded paths
would let a caller hash or enumerate anything the container can read.
"""
import asyncio
import os
from collections import Counter

from langchain_core.tools import tool

from src.config import get_settings
from src.library import rom_analyzer as ra


def _rom_roots() -> list[str]:
    """Directories ROM tools are allowed to touch."""
    settings = get_settings()
    roots = []
    roms_cfg = settings.roms
    for key in ("library_dir", "download_path"):
        value = roms_cfg.get(key)
        if value:
            roots.append(os.path.realpath(value))
    media_root = settings.library.get("media_root")
    if media_root:
        roots.append(os.path.realpath(media_root))
    return roots


def _default_root() -> str | None:
    roots = _rom_roots()
    return roots[0] if roots else None


def _confine(path: str) -> tuple[str | None, str | None]:
    """Resolve *path* and confirm it lives under an allowed ROM/media root."""
    roots = _rom_roots()
    if not roots:
        return None, ("❌ Error: no ROM library configured — set "
                      "services.roms.library_dir (or download_path) in settings.yaml.")
    target = os.path.realpath(path)
    for root in roots:
        if target == root or target.startswith(root + os.sep):
            return target, None
    return None, (f"❌ Error: path {path!r} is outside the ROM library / media "
                  f"root. ROM tools only operate inside: {', '.join(roots)}")


def _resolve_scan_path(path: str, platform: str) -> tuple[str | None, str | None]:
    """Turn optional path/platform args into a confined directory."""
    if path:
        return _confine(path)
    root = _default_root()
    if root is None:
        return None, ("❌ Error: no ROM library configured — set "
                      "services.roms.library_dir in settings.yaml, or pass a path.")
    if platform:
        candidate = os.path.join(root, platform)
        if os.path.isdir(candidate):
            return candidate, None
    return root, None


def _issue_lines(infos: list, limit: int = 25) -> list[str]:
    lines = []
    shown = 0
    for info in infos:
        for issue in info.issues:
            if shown >= limit:
                remaining = sum(len(i.issues) for i in infos) - shown
                lines.append(f"  ... and {remaining} more issue(s)")
                return lines
            where = info.name if not info.container else f"{info.name} (in {os.path.basename(info.container)})"
            lines.append(f"  • {where}: {issue}")
            shown += 1
    return lines


def _scan_sync(target: str) -> str:
    infos = ra.scan_directory(target)
    if not infos:
        return f"No ROM files found under {target}."

    platforms = Counter(ra.PLATFORM_NAMES.get(i.platform, i.platform) for i in infos)
    formats = Counter(i.fmt for i in infos if i.fmt)
    with_title = sum(1 for i in infos if i.title)
    with_issues = [i for i in infos if i.issues]
    total_bytes = sum(i.size for i in infos if not i.container)

    lines = [f"📦 ROM library scan of {target}", ""]
    lines.append(f"Files analyzed: {len(infos)} "
                 f"({total_bytes / 1024 / 1024:.0f} MB on disk)")
    lines.append(f"Header metadata extracted: {with_title} file(s)")
    lines.append("")
    lines.append("By platform:")
    for name, count in platforms.most_common():
        lines.append(f"  • {name}: {count}")
    lines.append("")
    lines.append("By format:")
    for name, count in formats.most_common(12):
        lines.append(f"  • {name}: {count}")
    if with_issues:
        lines.append("")
        lines.append(f"⚠️ {len(with_issues)} file(s) have issues — "
                     "run rom_check_problems for the full report. Sample:")
        lines.extend(_issue_lines(with_issues, limit=5))
    else:
        lines.append("")
        lines.append("✅ No issues detected.")
    return "\n".join(lines)


def _inspect_sync(target: str) -> str:
    if target.lower().endswith(".zip"):
        infos = ra.analyze_zip(target)
    else:
        infos = [ra.analyze_file(target)]

    lines = []
    for info in infos:
        header = info.name if not info.container else f"{info.name} (inside {os.path.basename(info.container)})"
        lines.append(f"🎮 {header}")
        lines.append(f"  Platform: {ra.PLATFORM_NAMES.get(info.platform, info.platform)}")
        if info.fmt:
            lines.append(f"  Format:   {info.fmt}")
        if info.title:
            lines.append(f"  Internal title: {info.title}")
        if info.game_code:
            lines.append(f"  Game code: {info.game_code}")
        if info.region:
            lines.append(f"  Region:   {info.region}")
        if info.revision:
            lines.append(f"  Revision: {info.revision}")
        for key, value in info.extra.items():
            lines.append(f"  {key.replace('_', ' ').title()}: {value}")
        lines.append(f"  Size:     {info.size:,} bytes")
        if info.crc32:
            lines.append(f"  CRC32:    {info.crc32} (No-Intro DAT key)")
        if info.tags:
            lines.append(f"  Filename tags: {' '.join(info.tags)}")
        if info.issues:
            lines.append("  ⚠️ Issues:")
            for issue in info.issues:
                lines.append(f"    • {issue}")
        else:
            lines.append("  ✅ No issues detected.")
        lines.append("")
    return "\n".join(lines).rstrip()


def _duplicates_sync(target: str) -> str:
    infos = ra.scan_directory(target)
    if not infos:
        return f"No ROM files found under {target}."

    exact = ra.find_exact_duplicates(infos)
    variants = ra.find_variant_groups(infos)

    lines = [f"🔍 Duplicate check for {len(infos)} ROM(s) under {target}", ""]
    if exact:
        wasted = sum(sum(i.size for i in g[1:]) for g in exact)
        lines.append(f"Exact duplicates (identical CRC32): {len(exact)} group(s), "
                     f"~{wasted / 1024 / 1024:.0f} MB reclaimable")
        for group in exact[:15]:
            keeper = ra.pick_keeper(group)
            lines.append(f"  • CRC {group[0].crc32}:")
            for info in group:
                marker = "KEEP " if info is keeper else "dupe "
                where = info.path if not info.container else f"{info.container} → {info.name}"
                lines.append(f"      [{marker}] {where}")
        if len(exact) > 15:
            lines.append(f"  ... and {len(exact) - 15} more group(s)")
    else:
        lines.append("✅ No exact duplicates found.")

    lines.append("")
    if variants:
        lines.append(f"Same game, different version/region: {len(variants)} group(s)")
        for group in variants[:10]:
            lines.append(f"  • {group[0].base_title} "
                         f"({ra.PLATFORM_NAMES.get(group[0].platform, group[0].platform)}):")
            for info in group:
                detail = ", ".join(x for x in (info.region, info.revision) if x) or "no tags"
                lines.append(f"      - {info.name} ({detail})")
        if len(variants) > 10:
            lines.append(f"  ... and {len(variants) - 10} more group(s)")
        lines.append("")
        lines.append("Variants are usually intentional (regions/revisions) — "
                     "nothing is deleted automatically.")
    else:
        lines.append("No region/revision variant groups found.")
    return "\n".join(lines)


def _problems_sync(target: str) -> str:
    infos = ra.scan_directory(target)
    if not infos:
        return f"No ROM files found under {target}."

    with_issues = [i for i in infos if i.issues]
    if not with_issues:
        return (f"✅ Checked {len(infos)} ROM(s) under {target} — "
                "no problems found (headers, checksums, byte order, "
                "copier headers, cue/bin structure, bad-dump tags).")

    issue_count = sum(len(i.issues) for i in with_issues)
    lines = [f"🔧 ROM debug report for {target}",
             f"Checked {len(infos)} file(s) — {issue_count} issue(s) "
             f"across {len(with_issues)} file(s):", ""]
    lines.extend(_issue_lines(with_issues, limit=40))
    lines.append("")
    lines.append("Tips: strip copier headers and convert N64 dumps to .z64 for "
                 "No-Intro-consistent hashes; replace [b] bad dumps; "
                 "rebuild missing .cue sheets for raw .bin tracks.")
    return "\n".join(lines)


# ── tools ────────────────────────────────────────────────────────────────────


@tool
async def rom_scan_library(path: str = "", platform: str = "") -> str:
    """Scan the ROM library: identify every ROM's platform and format from
    file headers, extract metadata, and summarize any problems found.

    Args:
        path: Directory to scan. Defaults to the configured ROM library.
        platform: Optional platform subfolder (nes, snes, n64, gba, psx...).
    """
    try:
        target, err = _resolve_scan_path(path, platform)
        if err:
            return err
        if not os.path.isdir(target):
            return f"❌ Directory not found: {target}"
        return await asyncio.to_thread(_scan_sync, target)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"


@tool
async def rom_inspect(path: str) -> str:
    """Deep-inspect one ROM file (or zip of ROMs): platform, format, internal
    header title, region, game code, header checksum validation, CRC32, and
    any problems. Works for NES, SNES, GB/GBC, GBA, N64, NDS, Genesis,
    SMS/GG, Lynx, PC Engine, Atari 2600, and disc formats.

    Args:
        path: Full path to the ROM file.
    """
    try:
        target, err = _confine(path)
        if err:
            return err
        if not os.path.isfile(target):
            return f"❌ File not found: {target}"
        return await asyncio.to_thread(_inspect_sync, target)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"


@tool
async def rom_find_duplicates(path: str = "", platform: str = "") -> str:
    """Find duplicate ROMs: exact byte-identical copies (matched by CRC32,
    including inside zips) with a keep/delete recommendation, plus groups of
    the same game in different regions/revisions. Nothing is deleted.

    Args:
        path: Directory to scan. Defaults to the configured ROM library.
        platform: Optional platform subfolder (nes, snes, ...).
    """
    try:
        target, err = _resolve_scan_path(path, platform)
        if err:
            return err
        if not os.path.isdir(target):
            return f"❌ Directory not found: {target}"
        return await asyncio.to_thread(_duplicates_sync, target)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"


@tool
async def rom_check_problems(path: str = "", platform: str = "") -> str:
    """Debug the ROM collection: find corrupt or truncated files, failed
    header checksums (won't boot on real hardware), byte-swapped N64 dumps,
    SNES/PCE copier headers, misnamed files (extension vs content), orphaned
    .cue/.bin disc tracks, bad-dump [b] tags, and broken zips.

    Args:
        path: Directory to scan. Defaults to the configured ROM library.
        platform: Optional platform subfolder (nes, snes, ...).
    """
    try:
        target, err = _resolve_scan_path(path, platform)
        if err:
            return err
        if not os.path.isdir(target):
            return f"❌ Directory not found: {target}"
        return await asyncio.to_thread(_problems_sync, target)
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"
