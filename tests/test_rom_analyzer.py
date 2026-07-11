"""Tests for the ROM analysis engine — real synthesized ROM files on disk."""
import zipfile

import pytest

from src.library import rom_analyzer as ra


# ── ROM builders (canonical header layouts) ──────────────────────────────────

def build_nes(prg_banks=1, chr_banks=1, mapper=1, truncate=False) -> bytes:
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = prg_banks
    header[5] = chr_banks
    header[6] = (mapper & 0x0F) << 4
    header[7] = mapper & 0xF0
    body = bytes(prg_banks * 16384 + chr_banks * 8192)
    data = bytes(header) + body
    return data[:200] if truncate else data


def build_gb(title=b"TESTGAME", bad_checksum=False, bad_logo=False) -> bytes:
    rom = bytearray(0x8000)
    rom[0x104:0x134] = b"\x00" * 48 if bad_logo else ra._GB_LOGO
    rom[0x134:0x134 + len(title)] = title
    rom[0x143] = 0x80  # CGB-enhanced
    rom[0x14A] = 0x01  # overseas
    checksum = 0
    for b in rom[0x134:0x14D]:
        checksum = (checksum - b - 1) & 0xFF
    rom[0x14D] = (checksum + 1) & 0xFF if bad_checksum else checksum
    return bytes(rom)


def build_gba(title=b"TESTADV", code=b"ATSE", bad_checksum=False) -> bytes:
    rom = bytearray(0x1000)
    rom[0x04:0x14] = ra._GBA_LOGO_PREFIX
    rom[0xA0:0xA0 + len(title)] = title
    rom[0xAC:0xB0] = code
    checksum = 0
    for b in rom[0xA0:0xBD]:
        checksum -= b
    value = (checksum - 0x19) & 0xFF
    rom[0xBD] = (value + 1) & 0xFF if bad_checksum else value
    return bytes(rom)


def build_snes(title=b"SUPER TEST GAME", copier_header=False,
               bad_checksum=False) -> bytes:
    rom = bytearray(0x10000)
    rom[0x7FC0:0x7FC0 + 21] = title.ljust(21)
    rom[0x7FD9] = 0x01  # USA
    checksum = 0x1234
    complement = checksum ^ 0xFFFF
    if bad_checksum:
        complement ^= 0x00FF
    rom[0x7FDC:0x7FDE] = complement.to_bytes(2, "little")
    rom[0x7FDE:0x7FE0] = checksum.to_bytes(2, "little")
    if copier_header:
        return bytes(512) + bytes(rom)
    return bytes(rom)


def build_n64_byteswapped() -> bytes:
    rom = bytearray(0x1000)
    rom[0:4] = b"\x37\x80\x40\x12"
    # Title "TEST" at 0x20 in byte-swapped order → "ETTS" wait, swap pairs.
    rom[0x20:0x24] = b"ETTS"[:4]
    return bytes(rom)


def build_genesis(declared_checksum=0, region=b"JUE") -> bytes:
    rom = bytearray(0x210)
    rom[0x100:0x110] = b"SEGA MEGA DRIVE "
    rom[0x150:0x160] = b"TEST CARTRIDGE  "
    rom[0x1F0:0x1F3] = region
    rom[0x18E:0x190] = declared_checksum.to_bytes(2, "big")
    # body (0x200..0x210) is zeros → true checksum is 0
    return bytes(rom)


# ── filename tag parsing ─────────────────────────────────────────────────────

def test_parse_filename_tags():
    tags = ra.parse_filename_tags("Super Game (USA, Europe) (Rev 1) [b].nes")
    assert tags["base"] == "Super Game"
    assert tags["regions"] == ["USA", "Europe"]
    assert tags["revision"] == "Rev 1"
    assert tags["bad_dump"] is True

    tags = ra.parse_filename_tags("Puzzle Quest (Japan) (Beta).sfc")
    assert tags["prerelease"] == "Beta"
    assert tags["regions"] == ["Japan"]
    assert not tags["bad_dump"]


# ── per-system parsing ───────────────────────────────────────────────────────

def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_nes_parse_and_truncation(tmp_path):
    good = ra.analyze_file(_write(tmp_path, "Game (USA).nes", build_nes(mapper=4)))
    assert good.platform == "nes"
    assert good.fmt == "iNES"
    assert good.extra["mapper"] == 4
    assert good.region == "USA"
    assert not good.issues

    bad = ra.analyze_file(_write(tmp_path, "Broken.nes", build_nes(truncate=True)))
    assert any("truncated" in i for i in bad.issues)

    headerless = ra.analyze_file(_write(tmp_path, "Old.nes", bytes(32768)))
    assert any("iNES header" in i for i in headerless.issues)


def test_gb_parse_checksums(tmp_path):
    good = ra.analyze_file(_write(tmp_path, "Game (World).gbc", build_gb()))
    assert good.fmt.startswith("Game Boy Color")
    assert good.title == "TESTGAME"
    assert not good.issues

    bad = ra.analyze_file(_write(tmp_path, "Bad.gbc", build_gb(bad_checksum=True)))
    assert any("header checksum failed" in i for i in bad.issues)

    nologo = ra.analyze_file(_write(tmp_path, "NoLogo.gb", build_gb(bad_logo=True)))
    assert any("logo bytes corrupt" in i for i in nologo.issues)


def test_gba_parse(tmp_path):
    good = ra.analyze_file(_write(tmp_path, "Adv.gba", build_gba()))
    assert good.title == "TESTADV"
    assert good.game_code == "ATSE"
    assert good.region == "USA"  # 'E' code
    assert not good.issues

    bad = ra.analyze_file(_write(tmp_path, "BadAdv.gba", build_gba(bad_checksum=True)))
    assert any("header checksum failed" in i for i in bad.issues)


def test_snes_parse_copier_header(tmp_path):
    good = ra.analyze_file(_write(tmp_path, "Super.sfc", build_snes()))
    assert good.fmt == "SNES LoROM"
    assert good.title == "SUPER TEST GAME"
    assert good.region == "USA"
    assert not good.issues

    copier = ra.analyze_file(_write(tmp_path, "Copier.smc", build_snes(copier_header=True)))
    assert any("copier header" in i for i in copier.issues)
    assert copier.title == "SUPER TEST GAME"  # still parsed past the junk

    bad = ra.analyze_file(_write(tmp_path, "BadSum.sfc", build_snes(bad_checksum=True)))
    assert any("checksum/complement" in i for i in bad.issues)


def test_n64_byte_order(tmp_path):
    swapped = ra.analyze_file(_write(tmp_path, "Game.v64", build_n64_byteswapped()))
    assert "byte-swapped" in swapped.fmt
    assert any("convert to native .z64" in i for i in swapped.issues)
    assert swapped.title == "TEST"  # unswapped for reading


def test_genesis_checksum(tmp_path):
    good = ra.analyze_file(_write(tmp_path, "Cart.md", build_genesis(0)))
    assert good.title == "TEST CARTRIDGE"
    assert good.region == "JUE"
    assert not good.issues

    bad = ra.analyze_file(_write(tmp_path, "BadCart.md", build_genesis(0xBEEF)))
    assert any("checksum mismatch" in i for i in bad.issues)


def test_extension_content_mismatch(tmp_path):
    # NES content wearing a .gba extension
    info = ra.analyze_file(_write(tmp_path, "Sneaky.gba", build_nes()))
    assert info.platform == "nes"
    assert any("misnamed" in i for i in info.issues)


def test_zero_byte_file(tmp_path):
    info = ra.analyze_file(_write(tmp_path, "Empty.nes", b""))
    assert any("zero-byte" in i for i in info.issues)


# ── zip introspection ────────────────────────────────────────────────────────

def test_zip_members_get_crc_from_central_directory(tmp_path):
    rom = build_gb()
    zpath = tmp_path / "Game (USA).zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("Game (USA).gbc", rom)
    infos = ra.analyze_zip(str(zpath))
    assert len(infos) == 1
    assert infos[0].title == "TESTGAME"
    assert infos[0].container == str(zpath)
    import zlib
    assert infos[0].crc32 == f"{zlib.crc32(rom) & 0xFFFFFFFF:08X}"


def test_corrupt_zip(tmp_path):
    zpath = _write(tmp_path, "broken.zip", b"not a zip at all")
    infos = ra.analyze_zip(zpath)
    assert any("corrupt zip" in i for info in infos for i in info.issues)


# ── cue/bin structure ────────────────────────────────────────────────────────

def test_cue_bin_structure(tmp_path):
    (tmp_path / "Game (USA).bin").write_bytes(bytes(2048))
    (tmp_path / "Game (USA).cue").write_text(
        'FILE "Game (USA).bin" BINARY\n  TRACK 01 MODE2/2352\n')
    (tmp_path / "Broken (USA).cue").write_text(
        'FILE "Missing Track.bin" BINARY\n')
    (tmp_path / "Orphan.bin").write_bytes(bytes(2048))

    infos = ra.scan_directory(str(tmp_path))
    by_name = {i.name: i for i in infos}
    assert not by_name["Game (USA).cue"].issues
    assert any("missing track" in i for i in by_name["Broken (USA).cue"].issues)
    assert any("no .cue sheet" in i for i in by_name["Orphan.bin"].issues)
    assert not by_name["Game (USA).bin"].issues


# ── duplicates ───────────────────────────────────────────────────────────────

def test_exact_duplicates_across_loose_and_zip(tmp_path):
    rom = build_gb()
    _write(tmp_path, "Game (USA).gbc", rom)
    _write(tmp_path, "Game (USA) (Copy).gbc", rom)
    with zipfile.ZipFile(tmp_path / "Game.zip", "w") as zf:
        zf.writestr("Game (USA).gbc", rom)

    infos = ra.scan_directory(str(tmp_path))
    groups = ra.find_exact_duplicates(infos)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_variant_groups_and_keeper(tmp_path):
    _write(tmp_path, "Game X (USA).gb", build_gb(title=b"GAME X U"))
    _write(tmp_path, "Game X (Europe).gb", build_gb(title=b"GAME X E"))
    infos = ra.scan_directory(str(tmp_path))
    variants = ra.find_variant_groups(infos)
    assert len(variants) == 1
    assert {i.name for i in variants[0]} == {"Game X (USA).gb", "Game X (Europe).gb"}

    # keeper prefers good dumps over [b] bad dumps
    good = ra.RomInfo(path="a", name="Game (USA).nes")
    bad = ra.RomInfo(path="b", name="Game (USA) [b].nes")
    assert ra.pick_keeper([bad, good]) is good


# ── tool layer (async, confined) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rom_scan_library_tool(tmp_path):
    from src.tools.rom_tools import rom_scan_library
    _write(tmp_path, "Game (USA).nes", build_nes())
    _write(tmp_path, "Bad.gbc", build_gb(bad_checksum=True))
    report = await rom_scan_library.ainvoke({"path": str(tmp_path)})
    assert "NES" in report and "Game Boy Color" in report
    assert "issues" in report.lower()


@pytest.mark.asyncio
async def test_rom_inspect_tool(tmp_path):
    from src.tools.rom_tools import rom_inspect
    path = _write(tmp_path, "Super Game (USA) (Rev 1).sfc", build_snes())
    report = await rom_inspect.ainvoke({"path": path})
    assert "SNES LoROM" in report
    assert "SUPER TEST GAME" in report
    assert "CRC32" in report
    assert "Rev 1" in report


@pytest.mark.asyncio
async def test_rom_check_problems_tool(tmp_path):
    from src.tools.rom_tools import rom_check_problems
    _write(tmp_path, "Fine (USA).nes", build_nes())
    _write(tmp_path, "Swapped.v64", build_n64_byteswapped())
    report = await rom_check_problems.ainvoke({"path": str(tmp_path)})
    assert "byte-swapped" in report or "convert to native" in report


@pytest.mark.asyncio
async def test_rom_find_duplicates_tool(tmp_path):
    from src.tools.rom_tools import rom_find_duplicates
    rom = build_nes()
    _write(tmp_path, "Game (USA).nes", rom)
    _write(tmp_path, "Game (USA) (Copy).nes", rom)
    report = await rom_find_duplicates.ainvoke({"path": str(tmp_path)})
    assert "Exact duplicates" in report
    assert "KEEP" in report


@pytest.mark.asyncio
async def test_rom_tools_confined():
    from src.tools.rom_tools import rom_inspect
    result = await rom_inspect.ainvoke({"path": "/etc/passwd"})
    assert result.startswith("❌")
    assert "outside" in result


# ── router intents ───────────────────────────────────────────────────────────

class FakeTool:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self.reply


@pytest.mark.asyncio
@pytest.mark.parametrize("message,tool_name,expected_args", [
    ("scan my roms", "rom_scan_library", {}),
    ("scan my rom library", "rom_scan_library", {}),
    ("analyze my roms", "rom_scan_library", {}),
    ("scan my snes roms", "rom_scan_library", {"platform": "snes"}),
    ("debug my roms", "rom_check_problems", {}),
    ("check my roms for problems", "rom_check_problems", {}),
    ("any corrupt roms?", "rom_check_problems", {}),
    ("check my super nintendo roms for issues", "rom_check_problems", {"platform": "snes"}),
    ("find duplicate roms", "rom_find_duplicates", {}),
    ("dedupe my roms", "rom_find_duplicates", {}),
    ("find duplicate snes roms", "rom_find_duplicates", {"platform": "snes"}),
    ("get metadata for /media/roms/nes/Game.nes", "rom_inspect",
     {"path": "/media/roms/nes/Game.nes"}),
    ("inspect /media/roms/Game (USA).sfc".replace(" (USA)", ""), "rom_inspect",
     {"path": "/media/roms/Game.sfc"}),
    ("rom info /media/roms/x.gba", "rom_inspect", {"path": "/media/roms/x.gba"}),
])
async def test_rom_intents(monkeypatch, message, tool_name, expected_args):
    import src.tools.rom_tools as rt
    from src.graphs.router import try_route
    fake = FakeTool("✅ ok")
    monkeypatch.setattr(rt, tool_name, fake)
    reply = await try_route(message, "rr1")
    assert reply == "✅ ok"
    assert fake.calls == [expected_args]


@pytest.mark.asyncio
async def test_rom_scan_does_not_shadow_collection_or_verify(monkeypatch):
    """'what roms do i have' still lists the collection; 'verify my snes
    roms' still runs DAT verification — the new intents must not shadow them."""
    import src.providers.rom as rom_mod
    from src.graphs.router import try_route
    coll = FakeTool("collection")
    verify = FakeTool("verified")
    monkeypatch.setattr(rom_mod, "rom_get_collection", coll)
    monkeypatch.setattr(rom_mod, "rom_verify_dat", verify)
    assert await try_route("what roms do i have", "rr2") == "collection"
    assert await try_route("verify my snes roms", "rr2") == "verified"
