"""Tests for the library scanner."""
import pytest

from src.library.scanner import build_inventory, find_duplicates, scan_files


def test_scan_files_skips_hidden_and_sidecars(tmp_path):
    (tmp_path / "movie.mkv").write_bytes(b"a" * 100)
    (tmp_path / "movie.nfo").write_text("meta")
    (tmp_path / ".hidden.mkv").write_bytes(b"h")
    files = scan_files(str(tmp_path))
    assert [f["name"] for f in files] == ["movie.mkv"]
    assert files[0]["size"] == 100


def test_scan_files_bad_path():
    with pytest.raises(ValueError):
        scan_files("/no/such/dir")


def test_build_inventory_summary(tmp_path):
    (tmp_path / "a.mkv").write_bytes(b"a" * 2048)
    (tmp_path / "b.mp3").write_bytes(b"b" * 1024)
    report = build_inventory(str(tmp_path))
    assert "Files found: 2" in report
    assert ".mkv" in report and ".mp3" in report


def test_find_duplicates_detects_identical_content(tmp_path):
    content = b"same-bytes" * 1000
    (tmp_path / "one.mkv").write_bytes(content)
    (tmp_path / "two.mkv").write_bytes(content)
    (tmp_path / "other.mkv").write_bytes(b"different" * 1000)
    report = find_duplicates(str(tmp_path))
    assert "2 copies" in report
    assert "one.mkv" in report and "two.mkv" in report
    assert "other.mkv" not in report


def test_find_duplicates_same_size_different_content(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"a" * 500)
    (tmp_path / "b.bin").write_bytes(b"b" * 500)
    report = find_duplicates(str(tmp_path))
    assert "No duplicate files detected" in report
