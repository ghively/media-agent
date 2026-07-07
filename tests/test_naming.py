"""Tests for library naming check/fix/undo."""
import json

from src.library.naming import check_naming, fix_naming, undo_rename


def _make_tv_tree(root):
    good = root / "The Wire" / "Season 01"
    good.mkdir(parents=True)
    (good / "The Wire - s01e01 - The Target.mkv").write_bytes(b"x")
    bad = root / "The Wire" / "Season 01"
    (bad / "the.wire.S01E02.hdtv.mkv").write_bytes(b"y")
    return root


def test_check_naming_tv(tmp_path):
    _make_tv_tree(tmp_path)
    report = check_naming(str(tmp_path), "tv")
    assert "Files scanned: 2" in report
    assert "Compliant:     1" in report
    assert "Issues:        1" in report


def test_check_naming_unknown_convention(tmp_path):
    assert "Unknown convention" in check_naming(str(tmp_path), "podcast")


def test_check_naming_missing_path():
    assert "does not exist" in check_naming("/no/such/dir", "tv")


def test_fix_naming_movie_and_undo(tmp_path):
    movie_dir = tmp_path / "Heat (1995)"
    movie_dir.mkdir()
    src = movie_dir / "heat.1995.1080p.mkv"
    src.write_bytes(b"film")

    report = fix_naming(str(tmp_path), "movie")
    assert "Renamed: 1" in report

    fixed = tmp_path / "Heat (1995)" / "Heat (1995).mkv"
    assert fixed.exists()
    assert not src.exists()

    # Undo log written and replayable
    undo_files = list((tmp_path / ".media_agent_undo").glob("undo_movie_*.json"))
    assert len(undo_files) == 1
    entries = json.loads(undo_files[0].read_text())
    assert len(entries) == 1

    undo_report = undo_rename(str(undo_files[0]))
    assert "Reverted: 1" in undo_report
    assert src.exists()
    assert not fixed.exists()


def test_fix_naming_no_changes_needed(tmp_path):
    d = tmp_path / "Heat (1995)"
    d.mkdir()
    (d / "Heat (1995).mkv").write_bytes(b"x")
    report = fix_naming(str(tmp_path), "movie")
    assert "Renamed: 0" in report
    assert "already comply" in report


def test_undo_missing_log():
    assert "not found" in undo_rename("/no/such/undo.json")
