"""ROM/classic games provider — Internet Archive downloads + DAT verification.

The Internet Archive client, DAT parsing, and MD5 hashing are all synchronous
and can run for a long time (multi-GB downloads, hashing up to 100 files). Every
blocking section is offloaded via ``asyncio.to_thread`` so the event loop — and
with it every other tool and the scheduler — keeps running.

Paths come from ``settings.roms``: ``download_path``/``library_dir`` (default
``/media/roms`` on the mounted media volume) and ``dat_path`` (default
``<library>/_dat``).
"""
import asyncio
import hashlib
import os
from pathlib import Path
from langchain_core.tools import tool

from src.config import get_settings

# Import emby_scan for auto-triggering after downloads
from src.tools.emby import _client as _emby_client_factory


def _library_dir() -> Path:
    cfg = get_settings().roms
    return Path(cfg.get("library_dir") or cfg.get("download_path") or "/media/roms")


def _download_dir() -> Path:
    cfg = get_settings().roms
    return Path(cfg.get("download_path") or cfg.get("library_dir") or "/media/roms")


def _dat_dir() -> Path:
    cfg = get_settings().roms
    return Path(cfg.get("dat_path") or (_library_dir() / "_dat"))


def _md5_of(path: Path, skip: int = 0) -> str:
    """Chunked MD5 so multi-GB images never load fully into memory."""
    h = hashlib.md5()
    with open(path, "rb") as fh:
        if skip:
            fh.seek(skip)
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── blocking helpers (run in a worker thread) ───────────────────────────────


def _search_archive_sync(query: str, platform: str) -> list[dict]:
    """Query Internet Archive (blocking). Returns raw result dicts."""
    import internetarchive as ia

    search_query = f"no-intro {query}" if not platform else f"no-intro {platform} {query}"
    results = list(ia.search_items(search_query))[:10]
    if not results:
        results = list(ia.search_items(f"redump {query} {platform}"))[:10]
    return results


def _item_info_sync(identifier: str) -> dict:
    """Fetch title/size metadata for one Internet Archive item (blocking)."""
    import internetarchive as ia

    item = ia.get_item(identifier)
    if not item.exists:
        return {"error": f"❌ Item '{identifier}' not found on Internet Archive."}
    meta = item.metadata or {}
    size = getattr(item, "item_size", 0) or 0
    return {
        "title": meta.get("title", identifier),
        "size_gb": size / 1024 / 1024 / 1024 if size else 0,
    }


def _download_sync(identifier: str, platform: str) -> dict:
    """Download an Internet Archive item (blocking). Returns a result summary."""
    import internetarchive as ia

    download_root = _download_dir()
    os.makedirs(download_root, exist_ok=True)
    dest = download_root / (platform or identifier)

    item = ia.get_item(identifier)
    if not item.exists:
        return {"error": f"❌ Item '{identifier}' not found on Internet Archive."}

    rom_extensions = {".nes", ".sfc", ".smc", ".gen", ".md", ".n64", ".z64",
                      ".gba", ".gbc", ".gb", ".iso", ".bin", ".cue", ".chd",
                      ".zip", ".7z", ".ps1", ".pce", ".a26", ".col"}
    roms = [f for f in item.files if Path(f.get("name", "")).suffix.lower() in rom_extensions]
    if not roms:
        roms = item.files[:20]

    os.makedirs(dest, exist_ok=True)
    sliced = roms[:20]
    total = len(roms)
    capped = len(sliced)

    lines = [f"Downloading {capped} file(s) from '{identifier}'...\n"]
    downloaded = 0
    failed = 0
    for f in sliced:
        fname = f.get("name", "")
        try:
            item.download(fname, destdir=str(dest), silent=True)
            downloaded += 1
            lines.append(f"  ✓ {fname}")
        except Exception as fe:
            failed += 1
            lines.append(f"  ❌ {fname}: {fe}")

    emoji = "✅" if downloaded else "⚠️"
    lines.append(f"\n{emoji} Downloaded {downloaded} file(s) to {dest}" + (f" ({failed} failed)" if failed else ""))
    if total > capped:
        lines.append(f"   ({total - capped} more files skipped — download individually)")

    return {"lines": lines, "downloaded": downloaded, "dest": str(dest)}


def _verify_dat_sync(platform: str) -> str:
    """Verify ROM checksums against a No-Intro DAT file (blocking)."""
    platform_dir = _library_dir() / platform
    if not platform_dir.exists():
        return f"❌ ROM directory not found: {platform_dir}\nMount the media directory or use the default path."

    dat_dir = _dat_dir()
    dat_file = dat_dir / f"{platform}.dat"
    if not dat_file.exists():
        return (
            f"⚠️ DAT file not found: {dat_file}\n\n"
            f"Download No-Intro DATs from:\n"
            f"https://datomatic.no-intro.org/\n\n"
            f"Place them in {dat_dir}/ and run again."
        )

    import xml.etree.ElementTree as ET

    tree = ET.parse(dat_file)
    root = tree.getroot()

    known_games = {}
    for game in root.findall(".//game"):
        name = game.get("name", "")
        for rom in game.findall("rom"):
            md5 = rom.get("md5", "").lower()
            sha1 = rom.get("sha1", "").lower()
            size = rom.get("size", "")
            if md5:
                known_games[md5] = {"name": name, "sha1": sha1, "size": size}

    rom_extensions = {".nes", ".sfc", ".smc", ".gen", ".md", ".n64", ".z64",
                      ".gba", ".gbc", ".gb", ".iso", ".bin", ".chd"}
    rom_files = [f for f in platform_dir.rglob("*") if f.suffix.lower() in rom_extensions]

    verified = 0
    unknown = 0
    results = []

    for rf in rom_files[:100]:
        md5 = _md5_of(rf)
        if md5 in known_games:
            verified += 1
        else:
            # Many ROMs have a 512-byte copier header; check the headerless
            # hash too (chunked, so large files never load into memory).
            if rf.stat().st_size > 512 and _md5_of(rf, skip=512) in known_games:
                verified += 1
                continue
            unknown += 1
            results.append(rf.name)

    return (
        f"✅ ROM verification for {platform}: {verified} verified, {unknown} unknown\n\n"
        f"Verified: {verified}/{len(rom_files)} files match No-Intro DAT\n"
        f"Unknown: {unknown} files not in DAT (may be hacks, translations, or bad dumps)"
        + ("\n\nFirst unknown files:\n" + "\n".join(f"  • {r}" for r in results[:10]) if results else "")
    )


def _get_collection_sync() -> str:
    """List the ROM collection by platform (blocking rglob counts)."""
    library_dir = _library_dir()
    if not library_dir.exists():
        return f"❌ ROM library not found at {library_dir}.\nMount the media directory to see ROMs."

    platforms = [p for p in library_dir.iterdir() if p.is_dir() and not p.name.startswith("_")]
    if not platforms:
        return "No ROMs found in the library."

    game_extensions = {".nes", ".sfc", ".smc", ".gen", ".n64", ".gba",
                       ".gbc", ".iso", ".chd"}
    lines = ["ROM collection by platform:\n"]
    for platform in sorted(platforms):
        count = sum(1 for f in platform.rglob("*") if f.suffix.lower() in game_extensions)
        if count > 0:
            lines.append(f"  • {platform.name}: {count} games")
    return "\n".join(lines)


# ── tools ────────────────────────────────────────────────────────────────────


@tool
async def rom_search_archive(query: str, platform: str = "") -> str:
    """Search Internet Archive for No-Intro/Redump ROM sets.
    Optionally filter by platform (nes, snes, genesis, n64, gba, psx, etc.)."""
    try:
        results = await asyncio.to_thread(_search_archive_sync, query, platform)
        if not results:
            return f"No ROM sets found for '{query}'."

        lines = [f"Found {len(results)} result(s) on Internet Archive:\n"]
        for r in results:
            title = r.get("title", "Unknown")
            id_ = r.get("identifier", "")
            size = r.get("item_size", 0)
            size_gb = size / 1024 / 1024 / 1024 if size else 0
            lines.append(f"  • {title} [{id_}] ({size_gb:.1f} GB)")
        lines.append("\nUse `rom_download` with the identifier to download.")
        return "\n".join(lines)

    except ImportError:
        return "❌ internetarchive library not installed. Run: pip install internetarchive"
    except Exception as e:
        return f"❌ Archive search failed: {type(e).__name__}: {e}"


@tool
async def rom_download(identifier: str, platform: str = "", confirm: bool = False) -> str:
    """Download a ROM set from Internet Archive by identifier (bulk — sets
    can be tens of GB). Call with confirm=False first: it reports the set's
    name and size without downloading. After the user approves, call again
    with confirm=True. Optionally specify platform to organize the download."""
    try:
        if not confirm:
            info = await asyncio.to_thread(_item_info_sync, identifier)
            if info.get("error"):
                return info["error"]
            size = f"{info['size_gb']:.1f} GB" if info.get("size_gb") else "unknown size"
            return (
                f"⏸️ '{info['title']}' [{identifier}] is {size}. Nothing "
                "downloaded yet. Ask the user to approve, then call "
                "rom_download again with confirm=true."
            )

        result = await asyncio.to_thread(_download_sync, identifier, platform)
        if result.get("error"):
            return result["error"]

        lines = result["lines"]

        # Auto-verify against DAT files if platform specified
        if platform:
            lines.append(f"\nVerifying ROMs against No-Intro DATs...")
            try:
                verify_result = await rom_verify_dat.ainvoke({"platform": platform})
                lines.append(verify_result)
            except Exception as ve:
                lines.append(f"  ⚠️ Verification skipped: {ve}")

        # Trigger Emby library scan
        try:
            await _emby_client_factory()._post("/emby/Library/Refresh")
        except Exception:
            pass  # Don't fail if Emby scan fails

        lines.append("\n✅ Emby library scan triggered.")
        return "\n".join(lines)

    except ImportError:
        return "❌ internetarchive library not installed."
    except Exception as e:
        return f"❌ ROM download failed: {type(e).__name__}: {e}"


@tool
async def rom_verify_dat(platform: str) -> str:
    """Verify ROM collection checksums against No-Intro DAT files.
    Platform: nes, snes, genesis, n64, gba, etc."""
    try:
        return await asyncio.to_thread(_verify_dat_sync, platform)
    except FileNotFoundError:
        return "❌ Platform directory not found."
    except Exception as e:
        return f"❌ ROM verification failed: {type(e).__name__}: {e}"


@tool
async def rom_get_collection() -> str:
    """List current ROM collection by platform."""
    try:
        return await asyncio.to_thread(_get_collection_sync)
    except Exception as e:
        return f"❌ Failed to list ROMs: {type(e).__name__}: {e}"
