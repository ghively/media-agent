"""ROM/classic games provider — Internet Archive downloads + DAT verification."""
import os
from pathlib import Path
from langchain_core.tools import tool

ROM_DOWNLOAD_DIR = Path("/tmp/rom_downloads")
ROM_LIBRARY_DIR = Path("/media/roms")  # Mount via NFS when available


@tool
async def rom_search_archive(query: str, platform: str = "") -> str:
    """Search Internet Archive for No-Intro/Redump ROM sets.
    Optionally filter by platform (nes, snes, genesis, n64, gba, psx, etc.)."""
    try:
        import internetarchive as ia

        search_query = f"no-intro {query}" if not platform else f"no-intro {platform} {query}"
        search = ia.search_items(search_query)
        results = list(search)[:10]

        if not results:
            search = ia.search_items(f"redump {query} {platform}")
            results = list(search)[:10]

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
        import internetarchive as ia

        os.makedirs(ROM_DOWNLOAD_DIR, exist_ok=True)
        dest = ROM_DOWNLOAD_DIR / (platform or identifier)

        # Download the item
        item = ia.get_item(identifier)
        if not item.exists:
            return f"❌ Item '{identifier}' not found on Internet Archive."

        # Get files, filter to ROM types
        rom_extensions = {".nes", ".sfc", ".smc", ".gen", ".md", ".n64", ".z64",
                         ".gba", ".gbc", ".gb", ".iso", ".bin", ".cue", ".chd",
                         ".zip", ".7z", ".ps1", ".pce", ".a26", ".col"}
        roms = [f for f in item.files if Path(f.get("name", "")).suffix.lower() in rom_extensions]

        if not roms:
            # If no ROMs, download all files
            roms = list(item.files)

        total = len(roms)
        batch = roms[:20]

        os.makedirs(dest, exist_ok=True)
        downloaded = 0

        lines = [f"Downloading {len(batch)} of {total} file(s) from '{identifier}'...\n"]
        for f in batch:
            fname = f.get("name", "")
            item.download(fname, destdir=str(dest), silent=True)
            downloaded += 1
            lines.append(f"  ✓ {fname}")

        lines.append(f"\n✅ Downloaded {downloaded} files to {dest}")
        if total > 20:
            lines.append(f"   ({total - 20} more files skipped — download individually)")
        lines.append("\nRun `rom_verify_dat` to verify checksums against No-Intro DATs.")
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

        # Parse DAT file
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

        # Scan ROM files
        rom_extensions = {".nes", ".sfc", ".smc", ".gen", ".md", ".n64", ".z64",
                         ".gba", ".gbc", ".gb", ".iso", ".bin", ".chd"}
        rom_files = [f for f in platform_dir.rglob("*") if f.suffix.lower() in rom_extensions]

        verified = 0
        unknown = 0
        results = []

        for rf in rom_files[:100]:
            data = rf.read_bytes()
            md5 = hashlib.md5(data).hexdigest()
            if md5 in known_games:
                verified += 1
                continue
            # Also check headerless version — many ROMs have a 512-byte header
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

    except FileNotFoundError:
        return "❌ Platform directory not found."
    except Exception as e:
        return f"❌ ROM verification failed: {type(e).__name__}: {e}"


@tool
async def rom_get_collection() -> str:
    """List current ROM collection by platform."""
    try:
        if not ROM_LIBRARY_DIR.exists():
            return f"❌ ROM library not found at {ROM_LIBRARY_DIR}.\nMount the media directory to see ROMs."

        platforms = [p for p in ROM_LIBRARY_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")]
        if not platforms:
            return "No ROMs found in the library."

        rom_extensions = {".nes", ".sfc", ".smc", ".gen", ".md", ".n64", ".z64",
                          ".gba", ".gbc", ".gb", ".iso", ".bin", ".chd"}
        lines = ["ROM collection by platform:\n"]
        for platform in sorted(platforms):
            count = sum(
                1 for f in platform.rglob("*")
                if f.is_file() and f.suffix.lower() in rom_extensions
            )
            if count > 0:
                lines.append(f"  • {platform.name}: {count} games")
        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list ROMs: {type(e).__name__}: {e}"