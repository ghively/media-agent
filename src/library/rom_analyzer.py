"""ROM analysis engine — identify, inspect, debug, and dedup ROM files.

Pure stdlib (zlib, zipfile, struct-free byte slicing). Everything here is
synchronous and file-bound; the tool layer offloads calls via
``asyncio.to_thread``.

What it knows how to do:

- **Identify** a ROM's platform and format from its extension AND its bytes
  (header magic), so a mis-named file is caught, not mis-filed.
- **Parse header metadata** for the major cartridge systems: internal title,
  region, game codes, mapper/board info, and header checksums:
    NES (iNES / NES 2.0), SNES (LoROM/HiROM + copier headers), Game Boy /
    Game Boy Color, Game Boy Advance, Nintendo 64 (byte-order detection),
    Nintendo DS, Genesis / Mega Drive, Master System / Game Gear, Atari
    Lynx, PC Engine, Atari 2600.
- **Debug**: zero-byte and truncated files, corrupt/missing headers, failed
  header checksums (won't boot on real hardware), byte-swapped N64 dumps,
  SNES/PCE copier headers, extension/content mismatches, orphaned .cue
  sheets and stray .bin tracks for disc systems, bad-dump [b] filename tags.
- **Dedup**: exact duplicates by CRC32 (zip entries use the CRC already
  stored in the archive — the same checksum No-Intro DATs key on) and
  same-game variant groups (region/revision) via No-Intro filename tags.
"""
from __future__ import annotations

import os
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

# Files larger than this are not fully read for CRC/deep checks (disc images
# can be enormous); identification still works from the header bytes.
MAX_HASH_BYTES = 256 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 128 * 1024 * 1024
HEADER_READ_BYTES = 2 * 1024 * 1024
MAX_FILES_PER_SCAN = 5000

# ── extension → platform map ─────────────────────────────────────────────────

EXTENSION_PLATFORMS: dict[str, str] = {
    ".nes": "nes", ".fds": "fds", ".unf": "nes",
    ".sfc": "snes", ".smc": "snes", ".fig": "snes", ".swc": "snes",
    ".gb": "gb", ".gbc": "gbc", ".sgb": "gb",
    ".gba": "gba", ".agb": "gba",
    ".n64": "n64", ".z64": "n64", ".v64": "n64",
    ".nds": "nds", ".dsi": "nds", ".3ds": "3ds", ".cia": "3ds",
    ".md": "genesis", ".gen": "genesis", ".smd": "genesis", ".32x": "sega32x",
    ".sms": "mastersystem", ".gg": "gamegear", ".sg": "sg1000",
    ".pce": "pce", ".sgx": "pce",
    ".a26": "atari2600", ".a52": "atari5200", ".a78": "atari7800",
    ".lnx": "lynx", ".jag": "jaguar", ".j64": "jaguar",
    ".ws": "wonderswan", ".wsc": "wonderswan",
    ".ngp": "ngp", ".ngc": "ngp",
    ".vb": "virtualboy", ".col": "colecovision", ".int": "intellivision",
    ".gcm": "gamecube", ".rvz": "wii", ".wbfs": "wii", ".wad": "wii",
    ".iso": "disc", ".bin": "disc", ".cue": "disc", ".chd": "disc",
    ".img": "disc", ".mdf": "disc", ".pbp": "psx", ".cso": "psp",
    ".gdi": "dreamcast", ".cdi": "dreamcast",
    ".d64": "c64", ".t64": "c64", ".tap": "c64", ".adf": "amiga",
    ".rom": "unknown-cart",
}

ROM_EXTENSIONS = set(EXTENSION_PLATFORMS) | {".zip", ".7z"}

PLATFORM_NAMES: dict[str, str] = {
    "nes": "NES", "fds": "Famicom Disk System", "snes": "SNES",
    "gb": "Game Boy", "gbc": "Game Boy Color", "gba": "Game Boy Advance",
    "n64": "Nintendo 64", "nds": "Nintendo DS", "3ds": "Nintendo 3DS",
    "genesis": "Genesis/Mega Drive", "sega32x": "Sega 32X",
    "mastersystem": "Master System", "gamegear": "Game Gear",
    "sg1000": "SG-1000", "pce": "PC Engine/TurboGrafx",
    "atari2600": "Atari 2600", "atari5200": "Atari 5200",
    "atari7800": "Atari 7800", "lynx": "Atari Lynx", "jaguar": "Atari Jaguar",
    "wonderswan": "WonderSwan", "ngp": "Neo Geo Pocket",
    "virtualboy": "Virtual Boy", "colecovision": "ColecoVision",
    "intellivision": "Intellivision", "gamecube": "GameCube", "wii": "Wii",
    "disc": "Disc-based (PSX/PS2/Saturn/...)", "psx": "PlayStation",
    "psp": "PSP", "dreamcast": "Dreamcast", "c64": "Commodore 64",
    "amiga": "Amiga", "unknown-cart": "Unknown cartridge", "unknown": "Unknown",
}


@dataclass
class RomInfo:
    """Everything we learned about one ROM file (or zip member)."""
    path: str                      # on-disk path (the zip for members)
    name: str                      # display name (member name for zip entries)
    size: int = 0
    platform: str = "unknown"
    fmt: str = ""                  # e.g. "iNES", "SNES LoROM", "N64 (.z64 native)"
    title: str = ""                # internal header title
    region: str = ""               # header region, else filename region tag
    revision: str = ""             # filename revision tag ("Rev 1", "v1.1")
    game_code: str = ""            # GBA/NDS product code
    extra: dict = field(default_factory=dict)   # parser-specific details
    tags: list[str] = field(default_factory=list)   # filename () and [] tags
    crc32: str = ""                # 8-hex-digit CRC32 (No-Intro convention)
    container: str = ""            # "" for loose files, zip path for members
    issues: list[str] = field(default_factory=list)

    @property
    def base_title(self) -> str:
        """Filename with No-Intro tags stripped — the 'game identity'."""
        return _strip_tags(Path(self.name).stem)


# ── filename tag parsing (No-Intro convention) ───────────────────────────────

_TAG_RE = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")
_REGION_WORDS = {
    "usa", "europe", "japan", "world", "korea", "china", "asia", "australia",
    "brazil", "canada", "france", "germany", "italy", "spain", "netherlands",
    "sweden", "taiwan", "uk", "unknown", "en", "ja", "fr", "de", "es", "it",
}
_REV_RE = re.compile(r"^(?:rev\s*[\w.]+|v\d[\w.]*)$", re.IGNORECASE)


def parse_filename_tags(filename: str) -> dict:
    """Extract region/revision/status tags from a No-Intro style filename.

    "Super Game (USA, Europe) (Rev 1) [b]" →
        {"base": "Super Game", "regions": ["USA", "Europe"],
         "revision": "Rev 1", "tags": [...], "bad_dump": True, ...}
    """
    stem = Path(filename).stem
    regions: list[str] = []
    revision = ""
    tags: list[str] = []
    bad_dump = False
    unlicensed = False
    prerelease = ""

    for m in _TAG_RE.finditer(stem):
        paren, bracket = m.group(1), m.group(2)
        if bracket is not None:
            tags.append(f"[{bracket}]")
            if bracket.lower().startswith("b"):
                bad_dump = True
            continue
        tags.append(f"({paren})")
        parts = [p.strip() for p in paren.split(",")]
        if all(p.lower() in _REGION_WORDS for p in parts if p):
            regions.extend(parts)
        elif _REV_RE.match(paren.strip()):
            revision = paren.strip()
        elif paren.strip().lower() in ("beta", "proto", "sample", "demo", "alpha") \
                or paren.strip().lower().startswith(("beta ", "proto ")):
            prerelease = paren.strip()
        elif paren.strip().lower() == "unl":
            unlicensed = True

    return {
        "base": _strip_tags(stem),
        "regions": regions,
        "revision": revision,
        "tags": tags,
        "bad_dump": bad_dump,
        "unlicensed": unlicensed,
        "prerelease": prerelease,
    }


def _strip_tags(stem: str) -> str:
    return _TAG_RE.sub("", stem).strip().rstrip("-").strip()


def _printable(raw: bytes) -> str:
    """Decode a fixed-width header text field."""
    text = raw.decode("ascii", errors="replace").replace("�", "?")
    text = text.replace("\x00", " ").strip()
    return re.sub(r"\s+", " ", text)


def _text_score(raw: bytes) -> int:
    """How much of a byte field looks like printable ASCII (header sniffing)."""
    return sum(1 for b in raw if 0x20 <= b <= 0x7E or b == 0x00)


# ── per-system header parsers ────────────────────────────────────────────────
# Each parser takes (data, info) where data is the first HEADER_READ_BYTES of
# the file (or the whole file if smaller) and mutates info in place.

_GB_LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D"
    "0008111F8889000EDCCC6EE6DDDDD999"
    "BBBB67636E0EECCCDDDC999FBBB9333E"
)
_GBA_LOGO_PREFIX = bytes.fromhex("24FFAE51699AA2213D84820A84E409AD")


def _parse_nes(data: bytes, info: RomInfo) -> None:
    if data[:4] != b"NES\x1a":
        info.fmt = "headerless NES"
        info.issues.append("missing iNES header (won't load in most emulators)")
        return
    prg = data[4] * 16384
    chr_ = data[5] * 8192
    trainer = bool(data[6] & 0x04)
    mapper = (data[6] >> 4) | (data[7] & 0xF0)
    nes2 = (data[7] & 0x0C) == 0x08
    info.fmt = "NES 2.0" if nes2 else "iNES"
    info.extra["mapper"] = mapper
    info.extra["prg_rom"] = f"{prg // 1024} KB"
    info.extra["chr_rom"] = f"{chr_ // 1024} KB" if chr_ else "CHR-RAM"
    expected = 16 + (512 if trainer else 0) + prg + chr_
    if info.size < expected:
        info.issues.append(
            f"truncated: header declares {expected} bytes, file has {info.size}")


def _parse_snes(data: bytes, info: RomInfo) -> None:
    offset = 0
    if info.size % 1024 == 512:
        offset = 512
        info.issues.append("512-byte copier header present (strip it for No-Intro match)")

    best = None  # (score, map_name, header_bytes)
    for map_name, base in (("LoROM", 0x7FC0), ("HiROM", 0xFFC0)):
        start = base + offset
        header = data[start:start + 32]
        if len(header) < 32:
            continue
        checksum = int.from_bytes(header[0x1E:0x20], "little")
        complement = int.from_bytes(header[0x1C:0x1E], "little")
        score = _text_score(header[:21])
        if checksum ^ complement == 0xFFFF:
            score += 50
        if best is None or score > best[0]:
            best = (score, map_name, header)

    if best is None or best[0] < 15:
        info.fmt = "SNES (no internal header found)"
        info.issues.append("cannot locate SNES internal header — possibly corrupt or an odd dump")
        return

    score, map_name, header = best
    info.fmt = f"SNES {map_name}"
    info.title = _printable(header[:21])
    region_byte = header[0x19]
    regions = {0: "Japan", 1: "USA", 2: "Europe", 3: "Sweden", 4: "Finland",
               5: "Denmark", 6: "France", 7: "Netherlands", 8: "Spain",
               9: "Germany", 10: "Italy", 11: "China", 13: "Korea"}
    info.region = regions.get(region_byte, f"code {region_byte}")
    checksum = int.from_bytes(header[0x1E:0x20], "little")
    complement = int.from_bytes(header[0x1C:0x1E], "little")
    if checksum ^ complement != 0xFFFF:
        info.issues.append("internal checksum/complement pair invalid (bad or modified dump)")


def _parse_gb(data: bytes, info: RomInfo) -> None:
    if len(data) < 0x150:
        info.issues.append("file too small to contain a Game Boy header")
        return
    cgb_flag = data[0x143]
    is_cgb = cgb_flag in (0x80, 0xC0)
    info.fmt = "Game Boy Color" if is_cgb else "Game Boy"
    if cgb_flag == 0xC0:
        info.fmt += " (GBC only)"
    title_len = 11 if is_cgb else 16
    info.title = _printable(data[0x134:0x134 + title_len])
    info.region = "Japan" if data[0x14A] == 0 else "Overseas"
    if data[0x104:0x134] != _GB_LOGO:
        info.issues.append("Nintendo logo bytes corrupt (won't boot on hardware)")
    checksum = 0
    for b in data[0x134:0x14D]:
        checksum = (checksum - b - 1) & 0xFF
    if checksum != data[0x14D]:
        info.issues.append("header checksum failed (won't boot on hardware)")


def _parse_gba(data: bytes, info: RomInfo) -> None:
    if len(data) < 0xC0:
        info.issues.append("file too small to contain a GBA header")
        return
    info.fmt = "Game Boy Advance"
    info.title = _printable(data[0xA0:0xAC])
    info.game_code = _printable(data[0xAC:0xB0])
    regions = {"J": "Japan", "E": "USA", "P": "Europe", "D": "Germany",
               "F": "France", "I": "Italy", "S": "Spain"}
    if len(info.game_code) == 4:
        info.region = regions.get(info.game_code[3], "")
    if data[0x04:0x14] != _GBA_LOGO_PREFIX:
        info.issues.append("Nintendo logo bytes corrupt (won't boot on hardware)")
    checksum = 0
    for b in data[0xA0:0xBD]:
        checksum -= b
    if (checksum - 0x19) & 0xFF != data[0xBD]:
        info.issues.append("header checksum failed (won't boot on hardware)")


def _parse_n64(data: bytes, info: RomInfo) -> None:
    magic = data[:4]
    if magic == b"\x80\x37\x12\x40":
        info.fmt = "N64 (.z64 native big-endian)"
        header = data
    elif magic == b"\x37\x80\x40\x12":
        info.fmt = "N64 (.v64 byte-swapped)"
        info.issues.append("byte-swapped dump — convert to native .z64 for consistent hashing")
        header = bytes(data[i ^ 1] for i in range(min(len(data), 0x40)))
    elif magic == b"\x40\x12\x37\x80":
        info.fmt = "N64 (.n64 little-endian)"
        info.issues.append("little-endian dump — convert to native .z64 for consistent hashing")
        header = bytes(data[(i & ~3) + (3 - (i & 3))] for i in range(min(len(data), 0x40)))
    else:
        info.fmt = "N64 (unrecognized byte order)"
        info.issues.append("first bytes match no known N64 byte order — possibly corrupt")
        return
    info.title = _printable(header[0x20:0x34])


def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _parse_nds(data: bytes, info: RomInfo) -> None:
    if len(data) < 0x160:
        info.issues.append("file too small to contain a DS header")
        return
    info.fmt = "Nintendo DS"
    info.title = _printable(data[0x00:0x0C])
    info.game_code = _printable(data[0x0C:0x10])
    if _crc16(data[:0x15E]) != int.from_bytes(data[0x15E:0x160], "little"):
        info.issues.append("header CRC16 failed (bad or modified dump)")


def _parse_genesis(data: bytes, info: RomInfo, full_data: bytes | None) -> None:
    console = _printable(data[0x100:0x110])
    if "SEGA" not in console.upper():
        info.fmt = "Genesis (no SEGA header)"
        info.issues.append("missing 'SEGA' console header — interleaved (.smd) or corrupt dump")
        return
    info.fmt = console or "Genesis/Mega Drive"
    overseas = _printable(data[0x150:0x180])
    domestic = _printable(data[0x120:0x150])
    info.title = overseas or domestic
    info.region = _printable(data[0x1F0:0x1F3])
    if full_data is not None and len(full_data) > 0x200:
        declared = int.from_bytes(data[0x18E:0x190], "big")
        checksum = 0
        body = full_data[0x200:]
        for i in range(0, len(body) - 1, 2):
            checksum = (checksum + (body[i] << 8) + body[i + 1]) & 0xFFFF
        if checksum != declared:
            info.issues.append("ROM checksum mismatch vs header (bad or modified dump)")


def _parse_sms(data: bytes, info: RomInfo) -> None:
    for base in (0x7FF0, 0x3FF0, 0x1FF0):
        if data[base:base + 8] == b"TMR SEGA":
            info.fmt = "Master System / Game Gear"
            region_code = data[base + 0xF] >> 4
            regions = {3: "Japan (SMS)", 4: "Export (SMS)", 5: "Japan (GG)",
                       6: "Export (GG)", 7: "International (GG)"}
            info.region = regions.get(region_code, "")
            return
    info.fmt = "SMS/GG (no TMR SEGA header)"
    info.issues.append("missing 'TMR SEGA' header — very early dump or corrupt file")


def _parse_lynx(data: bytes, info: RomInfo) -> None:
    if data[:4] == b"LYNX":
        info.fmt = "Atari Lynx (.lnx with header)"
        info.title = _printable(data[10:42])
    else:
        info.fmt = "Atari Lynx (headerless)"


def _parse_pce(data: bytes, info: RomInfo) -> None:
    info.fmt = "PC Engine"
    if info.size % 8192 == 512:
        info.issues.append("512-byte copier header present (strip it for No-Intro match)")


def _parse_a26(data: bytes, info: RomInfo) -> None:
    info.fmt = "Atari 2600"
    if info.size not in (2048, 4096, 8192, 16384, 32768, 65536) and info.size < 2048:
        info.issues.append(f"unusual size for a 2600 ROM ({info.size} bytes)")


# Magic-byte signatures for extension/content mismatch detection.
_MAGIC_PLATFORMS: list[tuple[bytes, int, str]] = [
    (b"NES\x1a", 0, "nes"),
    (b"\x80\x37\x12\x40", 0, "n64"),
    (b"\x37\x80\x40\x12", 0, "n64"),
    (b"\x40\x12\x37\x80", 0, "n64"),
    (b"LYNX", 0, "lynx"),
]

_PARSERS = {
    "nes": _parse_nes,
    "snes": _parse_snes,
    "gb": _parse_gb,
    "gbc": _parse_gb,
    "gba": _parse_gba,
    "n64": _parse_n64,
    "nds": _parse_nds,
    "mastersystem": _parse_sms,
    "gamegear": _parse_sms,
    "lynx": _parse_lynx,
    "pce": _parse_pce,
    "atari2600": _parse_a26,
}


# ── single-file analysis ─────────────────────────────────────────────────────

def analyze_bytes(name: str, data: bytes, size: int, path: str,
                  container: str = "") -> RomInfo:
    """Analyze one ROM given its (header) bytes. ``data`` may be the whole
    file or just the first HEADER_READ_BYTES."""
    ext = Path(name).suffix.lower()
    platform = EXTENSION_PLATFORMS.get(ext, "unknown")
    info = RomInfo(path=path, name=name, size=size, platform=platform,
                   container=container)

    file_tags = parse_filename_tags(name)
    info.tags = file_tags["tags"]
    info.revision = file_tags["revision"]
    if file_tags["regions"]:
        info.region = ", ".join(file_tags["regions"])
    if file_tags["bad_dump"]:
        info.issues.append("filename is tagged [b] — known bad dump, consider replacing")

    if size == 0:
        info.issues.append("zero-byte file")
        return info

    # Extension/content mismatch: magic bytes say a different platform.
    for magic, at, magic_platform in _MAGIC_PLATFORMS:
        if data[at:at + len(magic)] == magic and platform not in (magic_platform, "unknown"):
            info.issues.append(
                f"content looks like {PLATFORM_NAMES.get(magic_platform, magic_platform)} "
                f"but extension says {PLATFORM_NAMES.get(platform, platform)} — misnamed?")
            platform = magic_platform
            info.platform = magic_platform
            break

    parser = _PARSERS.get(platform)
    if platform == "genesis":
        _parse_genesis(data, info, data if len(data) == size else None)
    elif parser is not None:
        parser(data, info)
    elif not info.fmt:
        info.fmt = PLATFORM_NAMES.get(platform, platform)

    # Header region wins over filename region only when filename had none.
    return info


def analyze_file(path: str) -> RomInfo:
    """Analyze one on-disk ROM file (loose file, not a zip)."""
    p = Path(path)
    size = p.stat().st_size
    read_size = size if size <= HEADER_READ_BYTES else HEADER_READ_BYTES
    # Genesis full-checksum needs the whole file; only for reasonably sized ROMs.
    ext = p.suffix.lower()
    if EXTENSION_PLATFORMS.get(ext) == "genesis" and size <= 32 * 1024 * 1024:
        read_size = size
    with open(p, "rb") as f:
        data = f.read(read_size)
    info = analyze_bytes(p.name, data, size, str(p))
    if size <= MAX_HASH_BYTES:
        info.crc32 = _crc32_file(p)
    return info


def _crc32_file(p: Path) -> str:
    crc = 0
    with open(p, "rb") as f:
        while chunk := f.read(1024 * 1024):
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xFFFFFFFF:08X}"


def analyze_zip(path: str) -> list[RomInfo]:
    """Analyze every ROM inside a zip. CRCs come free from the archive's
    central directory (the checksum No-Intro DATs use)."""
    results: list[RomInfo] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for entry in zf.infolist():
                if entry.is_dir():
                    continue
                ext = Path(entry.filename).suffix.lower()
                if ext not in EXTENSION_PLATFORMS:
                    continue
                if entry.file_size <= MAX_ZIP_MEMBER_BYTES:
                    data = zf.read(entry)
                else:
                    with zf.open(entry) as member:
                        data = member.read(HEADER_READ_BYTES)
                info = analyze_bytes(entry.filename, data, entry.file_size,
                                     path, container=path)
                info.crc32 = f"{entry.CRC & 0xFFFFFFFF:08X}"
                results.append(info)
        if not results:
            info = RomInfo(path=path, name=Path(path).name,
                           size=Path(path).stat().st_size, platform="unknown",
                           fmt="zip (no ROM entries)")
            info.issues.append("zip contains no recognizable ROM files")
            results.append(info)
    except zipfile.BadZipFile:
        info = RomInfo(path=path, name=Path(path).name, platform="unknown",
                       fmt="corrupt zip")
        info.issues.append("corrupt zip archive (BadZipFile)")
        results.append(info)
    return results


# ── directory scanning ───────────────────────────────────────────────────────

def scan_directory(root: str) -> list[RomInfo]:
    """Walk *root* and analyze every ROM-looking file (bounded)."""
    results: list[RomInfo] = []
    cue_files: list[Path] = []
    bin_files: list[Path] = []
    count = 0

    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            if count >= MAX_FILES_PER_SCAN:
                break
            p = Path(dirpath) / fname
            ext = p.suffix.lower()
            if ext not in ROM_EXTENSIONS:
                continue
            count += 1
            try:
                if ext == ".zip":
                    results.extend(analyze_zip(str(p)))
                elif ext == ".7z":
                    info = RomInfo(path=str(p), name=fname,
                                   size=p.stat().st_size, platform="unknown",
                                   fmt="7z archive (not inspected)")
                    results.append(info)
                else:
                    if ext == ".cue":
                        cue_files.append(p)
                    if ext == ".bin":
                        bin_files.append(p)
                    results.append(analyze_file(str(p)))
            except Exception as e:  # one unreadable file never kills a scan
                info = RomInfo(path=str(p), name=fname, platform="unknown")
                info.issues.append(f"unreadable: {type(e).__name__}: {e}")
                results.append(info)

    _check_disc_structure(results, cue_files, bin_files)
    return results


_CUE_FILE_RE = re.compile(r'FILE\s+"([^"]+)"', re.IGNORECASE)


def _check_disc_structure(results: list[RomInfo], cue_files: list[Path],
                          bin_files: list[Path]) -> None:
    """Cross-check .cue sheets against their referenced tracks."""
    referenced: set[str] = set()
    by_path = {info.path: info for info in results}

    for cue in cue_files:
        info = by_path.get(str(cue))
        try:
            content = cue.read_text(errors="replace")
        except Exception:
            continue
        refs = _CUE_FILE_RE.findall(content)
        if info is not None:
            info.fmt = "cue sheet"
            info.extra["tracks"] = len(refs)
        for ref in refs:
            target = (cue.parent / ref)
            referenced.add(str(target.resolve()))
            if not target.exists() and info is not None:
                info.issues.append(f"cue references missing track: {ref}")

    for b in bin_files:
        if str(b.resolve()) not in referenced:
            info = by_path.get(str(b))
            if info is not None:
                info.issues.append(
                    "raw .bin with no .cue sheet referencing it — emulators may not load it")


# ── duplicates ───────────────────────────────────────────────────────────────

def find_exact_duplicates(infos: list[RomInfo]) -> list[list[RomInfo]]:
    """Group files whose (crc32, size) match — byte-identical content."""
    groups: dict[tuple[str, int], list[RomInfo]] = {}
    for info in infos:
        if info.crc32 and info.size:
            groups.setdefault((info.crc32, info.size), []).append(info)
    return [g for g in groups.values() if len(g) > 1]


def find_variant_groups(infos: list[RomInfo]) -> list[list[RomInfo]]:
    """Group different dumps of the same game (region/revision variants)."""
    exact_keys = set()
    for group in find_exact_duplicates(infos):
        for info in group[1:]:
            exact_keys.add(id(info))
    groups: dict[tuple[str, str], list[RomInfo]] = {}
    for info in infos:
        base = info.base_title.lower()
        if not base or id(info) in exact_keys:
            continue
        groups.setdefault((info.platform, base), []).append(info)
    return [g for g in groups.values() if len(g) > 1]


def pick_keeper(group: list[RomInfo]) -> RomInfo:
    """Recommend which copy of an exact-duplicate group to keep."""
    def rank(info: RomInfo) -> tuple:
        tags = parse_filename_tags(info.name)
        return (
            tags["bad_dump"],              # good dumps first
            bool(tags["prerelease"]),      # finals before betas/protos
            info.container != "",          # loose files before zip members
            info.path,
        )
    return sorted(group, key=rank)[0]
