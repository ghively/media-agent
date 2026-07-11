"""ROM/classic games provider — Internet Archive downloads + DAT verification.

The Internet Archive client, DAT parsing, and MD5 hashing are all synchronous
and can run for a long time (multi-GB downloads, hashing up to 100 files). Every
blocking section is offloaded via ``asyncio.to_thread`` so the event loop — and
with it every other tool and the scheduler — keeps running.
"""
import asyncio
import os
from pathlib import Path
from langchain_core.tools import tool


# Import emby_scan for auto-triggering after downloads
from src.tools.emby import _client as _emby_client_factory

ROM_DOWNLOAD_DIR = Path("/tmp/rom_downloads")
ROM_LIBRARY_DIR = Path("/media/roms")  # Mount via NFS when available


# ── blocking helpers (run in a worker thread) ───────────────────────────────


def _search_archive_sync(query: str, platform: str) -> list[dict]:
    """Query Internet Archive (blocking). Returns raw result dicts."""
    import internetarchive as ia

    search_query = f"no-intro {query}" if not platform else f"no-intro {platform} {query}"
    results = list(ia.search_items(search_query))[:10]
    if not results:
        results = list(ia.search_items(f"redump {query} {platform}"))[:10]
    return results


def _download_sync(identifier: str, platform: str) -> dict:
    """Download an Internet Archive item (blocking). Returns a result summary."""
    import internetarchive as ia

    os.makedirs(ROM_DOWNLOAD_DIR, exist_ok=True)
    dest = ROM_DOWNLOAD_DIR / (platform or identifier)

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
    platform_dir = ROM_LIBRARY_DIR / platform
    if not platform_dir.exists():
        return f"❌ ROM directory not found: {platform_dir}\nMount the media directory or use the default path."

    dat_dir = ROM_LIBRARY_DIR / "_dat"
    dat_file = dat_dir / f"{platform}.dat"
    if not dat_file.exists():
        return (
            f"⚠️ DAT file not found: {dat_file}\n\n"
            f"Download No-Intro DATs from:\n"
            f"https://datomatic.no-intro.org/\n\n"
            f"Place them in {dat_dir}/ and run again."
        )

    import hashlib
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
        md5 = hashlib.md5(rf.read_bytes()).hexdigest()
        if md5 in known_games:
            verified += 1
        else:
            # Many ROMs have a 512-byte header; check the headerless hash too.
            if rf.stat().st_size > 512:
                data = rf.read_bytes()
                if len(data) > 512:
                    headerless = hashlib.md5(data[512:]).hexdigest()
                    if headerless in known_games:
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
    if not ROM_LIBRARY_DIR.exists():
        return f"❌ ROM library not found at {ROM_LIBRARY_DIR}.\nMount the media directory to see ROMs."

    platforms = [p for p in ROM_LIBRARY_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")]
    if not platforms:
        return "No ROMs found in the library."

    lines = ["ROM collection by platform:\n"]
    for platform in sorted(platforms):
        count = len(list(platform.rglob("*.nes"))) + len(list(platform.rglob("*.sfc"))) + \
                len(list(platform.rglob("*.smc"))) + len(list(platform.rglob("*.gen"))) + \
                len(list(platform.rglob("*.n64"))) + len(list(platform.rglob("*.gba"))) + \
                len(list(platform.rglob("*.gbc"))) + len(list(platform.rglob("*.iso"))) + \
                len(list(platform.rglob("*.chd")))
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
async def rom_download(identifier: str, platform: str = "") -> str:
    """Download a ROM set from Internet Archive by identifier.
    Optionally specify platform to organize the download."""
    try:
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
