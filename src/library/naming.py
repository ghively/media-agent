"""Naming convention enforcement for media libraries.

Supports three conventions:
  - movie:  /movies/Title (Year)/Title (Year).ext
  - tv:     /tv/Show Name/Season ##/Show Name - s##e## - Episode Title.ext
  - music:  /music/Artist/Album/Track ## - Title.ext

Every rename creates a sidecar undo file (.media_agent_undo) so operations
are reversible.
"""
import os
import re
import shutil
import json
from pathlib import Path
from datetime import datetime

# ── patterns ─────────────────────────────────────────────────────────────


_MOVIE_PATTERN = re.compile(
    r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)\s*\.\w+$"
)

_TV_PATTERN = re.compile(
    r"^(?P<show>.+?)\s*-\s*s(?P<season>\d{2})e(?P<episode>\d{2})\s*-\s*(?P<title>.+?)\.\w+$"
)

_MUSIC_PATTERN = re.compile(
    r"^(?P<track>\d{2,3})\s*-\s*(?P<title>.+?)\.\w+$"
)

_UNDO_DIR = ".media_agent_undo"


# ── public API ───────────────────────────────────────────────────────────


def check_naming(path: str, convention: str = "tv") -> str:
    """Validate filenames under *path* against *convention*.

    Supported *convention* values:
      - "movie"  — /Title (Year)/Title (Year).ext
      - "tv"     — /Show/Season ##/Show - s##e## - Title.ext
      - "music"  — /Artist/Album/Track ## - Title.ext

    Returns a formatted report string.
    """
    root = Path(path)
    if not root.exists():
        return f"❌ Path does not exist: {path}"

    validator = _VALIDATORS.get(convention)
    if validator is None:
        return f"❌ Unknown convention: {convention!r}. Supported: movie, tv, music."

    issues = []
    ok_count = 0
    total = 0

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name.startswith("."):
            continue
        total += 1
        parent = file_path.parent
        grandparent = parent.parent if parent.parent else parent
        extra = grandparent.parent if grandparent.parent else grandparent

        is_ok, msg = validator(file_path, parent, grandparent, extra)
        if is_ok:
            ok_count += 1
        else:
            issues.append((str(file_path), msg))

    lines = [
        f"📋 Naming check [{convention}] on: {path}",
        f"   Files scanned: {total}",
        f"   Compliant:     {ok_count}",
        f"   Issues:        {len(issues)}",
    ]

    if issues:
        lines.append("")
        for fpath, msg in issues[:30]:
            lines.append(f"   ❌ {msg}")
            lines.append(f"       {fpath}")
        if len(issues) > 30:
            lines.append(f"   ... and {len(issues) - 30} more issues")

    return "\n".join(lines)


def fix_naming(path: str, convention: str = "tv") -> str:
    """Rename files under *path* to match *convention*.

    Creates an undo log in ``{root}/.media_agent_undo/`` so each rename
    can be rolled back.

    Returns a formatted report string.
    """
    root = Path(path)
    if not root.exists():
        return f"❌ Path does not exist: {path}"

    fixer = _FIXERS.get(convention)
    if fixer is None:
        return f"❌ Unknown convention: {convention!r}. Supported: movie, tv, music."

    # Prepare undo directory
    undo_dir = root / _UNDO_DIR
    undo_dir.mkdir(parents=True, exist_ok=True)
    undo_log = []
    errors = []
    renamed = 0
    skipped = 0

    for file_path in sorted(root.rglob("*"), key=lambda p: (len(p.parts), str(p))):
        if not file_path.is_file():
            continue
        if file_path.name.startswith("."):
            continue
        # Skip undo directory itself
        if _UNDO_DIR in file_path.parts:
            continue

        try:
            result = fixer(file_path, root)
            if result is None:
                skipped += 1
                continue
            old_path, new_path = result
            if old_path == new_path:
                skipped += 1
                continue

            new_path.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(old_path), str(new_path))
            undo_log.append({
                "old": str(old_path),
                "new": str(new_path),
                "time": datetime.utcnow().isoformat(),
            })
            renamed += 1
        except OSError as e:
            errors.append(f"   ❌ {file_path} — {e}")

    # Write undo log
    undo_file = None
    if undo_log:
        undo_stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        undo_file = undo_dir / f"undo_{convention}_{undo_stamp}.json"
        with open(undo_file, "w") as f:
            json.dump(undo_log, f, indent=2)

    lines = [
        f"🔧 Naming fix [{convention}] on: {path}",
        f"   Renamed: {renamed}",
        f"   Skipped: {skipped}",
    ]
    if undo_file:
        lines.append(f"   Undo:    {undo_file}")
    if errors:
        lines.append("")
        lines.extend(errors)
    if renamed == 0 and not errors:
        lines.append("   ✅ All files already comply with the convention.")
    return "\n".join(lines)


# ── validators ───────────────────────────────────────────────────────────


def _validate_movie(fp: Path, parent: Path, grandparent: Path, extra: Path):
    """Check /Title (Year)/Title (Year).ext"""
    name = fp.stem
    ext = fp.suffix
    # Parent dir should match
    m = _MOVIE_PATTERN.match(name + ext)
    if not m:
        return False, f"Filename does not match 'Title (Year).ext'"
    title = m.group("title")
    year = m.group("year")
    expected_parent = f"{title} ({year})"
    if parent.name != expected_parent:
        return False, f"Expected parent dir '{expected_parent}', got '{parent.name}'"
    return True, ""


def _validate_tv(fp: Path, parent: Path, grandparent: Path, extra: Path):
    """Check /Show/Season ##/Show - s##e## - Title.ext"""
    name = fp.stem
    ext = fp.suffix
    m = _TV_PATTERN.match(name + ext)
    if not m:
        return False, f"Filename does not match 'Show - s##e## - Title.ext'"
    show = m.group("show")
    season = m.group("season")
    # Parent should be "Season ##"
    expected_parent = f"Season {season}"
    if parent.name != expected_parent:
        return False, f"Expected parent dir '{expected_parent}', got '{parent.name}'"
    # Grandparent should be the show name
    if grandparent.name != show:
        return False, f"Expected grandparent dir '{show}', got '{grandparent.name}'"
    return True, ""


def _validate_music(fp: Path, parent: Path, grandparent: Path, extra: Path):
    """Check /Artist/Album/Track ## - Title.ext"""
    name = fp.stem
    ext = fp.suffix
    m = _MUSIC_PATTERN.match(name + ext)
    if not m:
        return False, f"Filename does not match 'Track ## - Title.ext'"
    return True, ""


_VALIDATORS = {
    "movie": _validate_movie,
    "tv": _validate_tv,
    "music": _validate_music,
}


# ── fixers ────────────────────────────────────────────────────────────────


def _fix_movie(fp: Path, root: Path):
    """Rename to /Title (Year)/Title (Year).ext"""
    name = fp.stem
    m = _MOVIE_PATTERN.match(fp.name)
    if m:
        # Already valid — ensure parent exists
        title = m.group("title")
        year = m.group("year")
        expected_parent = fp.parent.parent / f"{title} ({year})"
        if fp.parent == expected_parent:
            return None  # Already correct
        new_path = expected_parent / fp.name
        return fp, new_path

    # Try to extract year from parent directory
    parent_name = fp.parent.name
    year_match = re.search(r"\((\d{4})\)", parent_name)
    title_guess = re.sub(r"\s*\(\d{4}\)\s*", "", parent_name).strip()

    if year_match and title_guess:
        new_name = f"{title_guess} ({year_match.group(1)}){fp.suffix}"
        expected_parent = root / f"{title_guess} ({year_match.group(1)})"
        if fp.parent == expected_parent and fp.name == new_name:
            return None
        new_path = expected_parent / new_name
        return fp, new_path

    return None


def _fix_tv(fp: Path, root: Path):
    """Rename to /Show/Season ##/Show - s##e## - Title.ext"""
    m = _TV_PATTERN.match(fp.name)
    if m:
        show = m.group("show")
        season = m.group("season")
        expected_parent = root / show / f"Season {season}"
        if fp.parent == expected_parent:
            return None
        new_path = expected_parent / fp.name
        return fp, new_path

    # Try to infer from path structure
    parts = fp.relative_to(root).parts
    if len(parts) >= 3:
        show_name = parts[0]
        season_match = re.search(r"(\d+)", parts[1])
        season_num = int(season_match.group(1)) if season_match else 1
        ep_match = re.search(r"e(\d+)", fp.stem, re.IGNORECASE)
        ep_num = int(ep_match.group(1)) if ep_match else 1
        clean_title = re.sub(r"\s*[sS]\d+\s*[eE]\d+.*", "", fp.stem).strip()
        new_name = f"{show_name} - s{season_num:02d}e{ep_num:02d} - {clean_title}{fp.suffix}"
        expected_parent = root / show_name / f"Season {season_num:02d}"
        if fp.parent == expected_parent and fp.name == new_name:
            return None
        new_path = expected_parent / new_name
        return fp, new_path

    return None


def _fix_music(fp: Path, root: Path):
    """Rename to /Artist/Album/Track ## - Title.ext"""
    m = _MUSIC_PATTERN.match(fp.name)
    if m:
        return None  # Already compliant

    # Try to extract track number from filename
    track_match = re.search(r"^(\d{2,3})", fp.stem)
    if track_match:
        track = track_match.group(1)
        title = fp.stem[track_match.end():].lstrip(" .-")
        new_name = f"{track} - {title}{fp.suffix}"
        parts = fp.relative_to(root).parts
        if len(parts) >= 2:
            expected_parent = root / parts[0] / parts[1]
            new_path = expected_parent / new_name
            return fp, new_path
    return None


_FIXERS = {
    "movie": _fix_movie,
    "tv": _fix_tv,
    "music": _fix_music,
}


# ── undo ──────────────────────────────────────────────────────────────────


def undo_rename(undo_log_path: str) -> str:
    """Revert a batch of renames from an undo log file.

    Accepts the path to a ``.media_agent_undo/undo_*.json`` file.
    Returns a formatted report string.
    """
    path = Path(undo_log_path)
    if not path.exists():
        return f"❌ Undo log not found: {undo_log_path}"

    try:
        with open(path) as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return f"❌ Failed to read undo log: {e}"

    if not isinstance(entries, list):
        return "❌ Invalid undo log format."

    errors = []
    reverted = 0
    skipped = 0

    # Process in reverse so directory removals don't break later renames
    for entry in reversed(entries):
        old = Path(entry["old"])
        new = Path(entry["new"])
        if not new.exists():
            skipped += 1
            continue
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(new), str(old))
            reverted += 1
        except OSError as e:
            errors.append(f"   ❌ {new} → {old}: {e}")

    lines = [
        f"↩️ Undo applied from: {undo_log_path}",
        f"   Reverted: {reverted}",
        f"   Skipped:  {skipped}",
    ]
    if errors:
        lines.append("")
        lines.extend(errors)
    return "\n".join(lines)