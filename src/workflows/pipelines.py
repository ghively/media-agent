"""Deterministic workflow pipelines.

Each pipeline is a plain coroutine that runs a complete multi-step media
workflow in code — search, decide, act, verify — and returns one compact
report string. The LLM's only jobs are picking the right pipeline and
relaying ambiguous choices to the user; everything else is deterministic.

This is the main token-budget lever for small local models: one tool call
replaces a 3–4 round ReAct loop, and every mutating step verifies its own
result before reporting success (a claim is only ✅ Verified after a
read-back confirms the new state).
"""
import asyncio

import httpx

from src.config import get_settings
from src.tools.arr import ArrClient

# Confidence rules for auto-acting on a search result without asking.
_DECISIVE_SCORE = 80        # top result must be at least a prefix match
_DECISIVE_MARGIN = 20       # and clearly ahead of the runner-up


# ── verified add: Sonarr ─────────────────────────────────────────────────────

async def add_series_verified(tvdb_id: int, title: str) -> str:
    """Add a series to Sonarr, then read back /series to verify it's present."""
    s = get_settings().sonarr
    if not s.get("url") or not s.get("api_key"):
        return "❌ Sonarr is not configured — set services.sonarr.url and api_key."
    client = ArrClient(s["url"], s["api_key"])

    body = {
        "tvdbId": tvdb_id,
        "title": title,
        "qualityProfileId": s.get("quality_profile_id", 1),
        "rootFolderPath": s.get("root_folder", "/tv/"),
        "monitored": True,
        "addOptions": {"searchForMissingEpisodes": True},
        "seriesType": "standard",
    }

    already_present = False
    try:
        await client._post("/series", body)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            # Likely "already exists" — the verify step below settles it
            already_present = True
        else:
            return f"❌ Sonarr returned HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Failed to add show: {type(e).__name__}: {e}"

    # Verify: the show must now appear in the library
    try:
        series = await client._get("/series")
        match = next((x for x in series if x.get("tvdbId") == tvdb_id), None)
    except Exception as e:
        return (
            f"⚠️ Add request sent for '{title}' but verification failed "
            f"({type(e).__name__}). Check list_tv_shows to confirm."
        )

    if match is None:
        if already_present:
            return f"❌ Sonarr rejected '{title}' (tvdbId {tvdb_id}) and it is not in the library — the ID may be invalid."
        return f"⚠️ Add request accepted but '{title}' is not visible in the library yet. Re-check with list_tv_shows."

    seasons = match.get("statistics", {}).get("seasonCount", "?")
    if already_present:
        return f"ℹ️ '{match.get('title', title)}' was already in the library (verified, {seasons} seasons monitored)."
    return (
        f"✅ Verified: '{match.get('title', title)}' added to the library "
        f"({seasons} seasons, monitored). Episode search triggered."
    )


# ── verified add: Radarr ─────────────────────────────────────────────────────

async def add_movie_verified(tmdb_id: int, title: str) -> str:
    """Add a movie to Radarr, then read back /movie to verify it's present."""
    s = get_settings().radarr
    if not s.get("url") or not s.get("api_key"):
        return "❌ Radarr is not configured — set services.radarr.url and api_key."
    client = ArrClient(s["url"], s["api_key"])

    body = {
        "tmdbId": tmdb_id,
        "title": title,
        "qualityProfileId": s.get("quality_profile_id", 1),
        "rootFolderPath": s.get("root_folder", "/movies/"),
        "monitored": True,
        "addOptions": {"searchForMovie": True},
    }

    already_present = False
    try:
        await client._post("/movie", body)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            already_present = True
        else:
            return f"❌ Radarr returned HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError:
        return "❌ Cannot connect to Radarr."
    except Exception as e:
        return f"❌ Failed to add movie: {type(e).__name__}: {e}"

    try:
        movies = await client._get("/movie")
        match = next((x for x in movies if x.get("tmdbId") == tmdb_id), None)
    except Exception as e:
        return (
            f"⚠️ Add request sent for '{title}' but verification failed "
            f"({type(e).__name__}). Check list_movies to confirm."
        )

    if match is None:
        if already_present:
            return f"❌ Radarr rejected '{title}' (tmdbId {tmdb_id}) and it is not in the library — the ID may be invalid."
        return f"⚠️ Add request accepted but '{title}' is not visible in the library yet. Re-check with list_movies."

    has_file = "file already present" if match.get("hasFile") else "searching for release"
    if already_present:
        return f"ℹ️ '{match.get('title', title)}' was already in the library (verified, {has_file})."
    return f"✅ Verified: '{match.get('title', title)}' added to the library, monitored ({has_file})."


# ── one-shot acquire: search → decide → add → verify ─────────────────────────

async def grab_media(query: str, kind: str | None = None) -> str:
    """Search Sonarr and Radarr for *query*; auto-add if one result clearly wins,
    otherwise return numbered options (cached for download_media)."""
    from src.tools import search as search_module

    searches = []
    if kind in (None, "tv"):
        searches.append(search_module._search_sonarr(query, 8))
    if kind in (None, "movie"):
        searches.append(search_module._search_radarr(query, 8))
    if not searches:
        return f"❌ Unknown kind {kind!r} — use 'tv', 'movie', or omit it."

    results_lists = await asyncio.gather(*searches, return_exceptions=True)
    candidates: list[dict] = []
    for rl in results_lists:
        if isinstance(rl, list):
            candidates.extend(rl)

    if not candidates:
        return (
            f"❌ No matches for '{query}' in Sonarr or Radarr. "
            f"Check the spelling or try search_media for a broader search."
        )

    candidates.sort(key=lambda r: (-r["relevance"], r["title"]))

    # Deduplicate by title + source
    seen: set = set()
    unique: list[dict] = []
    for r in candidates:
        key = (r["title"].lower(), r["source"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    top = unique[0]
    decisive = top["relevance"] >= _DECISIVE_SCORE and (
        len(unique) == 1 or top["relevance"] - unique[1]["relevance"] >= _DECISIVE_MARGIN
    )

    if decisive:
        if top["source_type"] == "tv":
            return await add_series_verified(top["id"], top["title"])
        return await add_movie_verified(top["id"], top["title"])

    # Ambiguous — cache the options so download_media(n) can act on a pick
    search_module._last_results = unique[:8]
    label = {"tv": "TV", "movie": "Movie"}
    lines = [f"Multiple matches for '{query}' — ask the user which one, then call download_media(<number>):"]
    for i, r in enumerate(search_module._last_results, 1):
        year = f" ({r['year']})" if r.get("year") else ""
        lines.append(f"  {i}. {r['title']}{year} [{label.get(r['source_type'], r['source_type'])}]")
    return "\n".join(lines)


# ── consolidated status ──────────────────────────────────────────────────────

async def system_report() -> str:
    """Health, download queues, and disk space for every configured service,
    gathered concurrently into one compact report."""
    from src.tools.health import check_all_health, check_disk_space, check_queue_status

    health, queues, disk = await asyncio.gather(
        check_all_health.ainvoke({}),
        check_queue_status.ainvoke({}),
        check_disk_space.ainvoke({}),
    )
    return (
        "System report\n"
        f"── Health ──\n{health}\n"
        f"── Queues ──\n{queues}\n"
        f"── Disk ──\n{disk}"
    )


# ── YouTube subscription sync (scheduler-friendly, no LLM) ───────────────────

async def sync_youtube(max_downloads: int = 3) -> str:
    """Check every YouTube subscription and download new uploads automatically.

    First check of a channel only records a baseline (no bulk backfill).
    Downloads are verified on disk before the subscription state advances,
    so a failed download is retried on the next sync.
    """
    from datetime import datetime, timezone
    from src.providers import youtube as yt

    subs = yt._load_subscriptions()
    if not subs:
        return "No YouTube subscriptions configured. Use youtube_add_subscription first."

    now = datetime.now(timezone.utc).isoformat()
    downloaded = 0
    lines = []

    for sub in subs:
        name = sub.get("name", "?")
        try:
            returncode, stdout, _ = await yt._run_ytdlp([
                "--flat-playlist",
                "--playlist-end", "1",
                "--print", "%(title)s|%(id)s",
                "--no-download",
                "--skip-download",
                sub["url"],
            ], timeout=30)
        except asyncio.TimeoutError:
            lines.append(f"  ⚠️ {name}: timed out")
            continue
        except FileNotFoundError:
            return "❌ yt-dlp not found. Install it: pip install yt-dlp"

        if returncode != 0:
            lines.append(f"  ⚠️ {name}: yt-dlp error")
            continue

        entries = [l.strip() for l in stdout.split("\n") if l.strip() and "|" in l]
        if not entries:
            lines.append(f"  ⚠️ {name}: no uploads found")
            continue

        vid_title, vid_id = entries[0].rsplit("|", 1)
        last_upload = sub.get("last_upload")
        sub["last_checked"] = now

        if not last_upload:
            # First check: record baseline, don't backfill the whole channel
            sub["last_upload"] = vid_id
            lines.append(f"  📋 {name}: baseline set (\"{vid_title[:60]}\")")
        elif vid_id == last_upload:
            lines.append(f"  ✓ {name}: no new uploads")
        elif downloaded >= max_downloads:
            lines.append(f"  ⏭️ {name}: new upload \"{vid_title[:60]}\" skipped (max {max_downloads}/run)")
        else:
            result = await yt.download_video(
                f"https://youtube.com/watch?v={vid_id}",
                sub.get("content_type", "video"),
            )
            if result.startswith("✅"):
                sub["last_upload"] = vid_id  # only advance on verified download
                downloaded += 1
                lines.append(f"  ✅ {name}: downloaded \"{vid_title[:60]}\"")
            else:
                lines.append(f"  ❌ {name}: {result[:120]}")

    yt._save_subscriptions(subs)

    header = f"YouTube sync — {len(subs)} channel(s) checked, {downloaded} download(s)"
    return "\n".join([header] + lines)


# ── library naming cleanup with verification ─────────────────────────────────

async def library_cleanup(path: str, convention: str = "tv") -> str:
    """Check naming, fix violations, then re-check to verify the result.
    Renames are reversible via the undo log reported at the end."""
    from pathlib import Path
    from src.library.naming import scan_issues, fix_naming, _UNDO_DIR

    try:
        total, issues = await asyncio.to_thread(scan_issues, path, convention)
    except ValueError as e:
        return f"❌ {e}"

    if not issues:
        return f"✅ Verified: all {total} file(s) in {path} already comply with '{convention}' naming."

    await asyncio.to_thread(fix_naming, path, convention)

    total_after, remaining = await asyncio.to_thread(scan_issues, path, convention)
    fixed = len(issues) - len(remaining)

    # Newest undo log for this run
    undo_logs = sorted((Path(path) / _UNDO_DIR).glob(f"undo_{convention}_*.json"))
    undo_line = f"\n   Undo:   library_undo_rename('{undo_logs[-1]}')" if undo_logs else ""

    if not remaining:
        status = f"✅ Verified: {total_after} file(s) now comply with '{convention}' naming."
    else:
        examples = "; ".join(msg for _, msg in remaining[:3])
        status = (
            f"⚠️ {len(remaining)} issue(s) could not be fixed automatically "
            f"(e.g., {examples}) — review manually."
        )

    return (
        f"Library cleanup [{convention}] on {path}\n"
        f"   Before: {len(issues)} issue(s) in {total} file(s)\n"
        f"   Fixed:  {fixed}\n"
        f"   {status}"
        f"{undo_line}"
    )


# ── missing-content searches ─────────────────────────────────────────────────

async def trigger_missing_searches() -> str:
    """Kick off missing-episode and missing-movie searches on both services."""
    results = []
    settings = get_settings()

    for name, cfg, command in (
        ("Sonarr", settings.sonarr, "MissingEpisodesSearch"),
        ("Radarr", settings.radarr, "MissingMoviesSearch"),
    ):
        if not cfg.get("url"):
            results.append(f"{name}: not configured, skipped")
            continue
        try:
            client = ArrClient(cfg["url"], cfg.get("api_key", ""))
            await client._post("/command", {"name": command})
            results.append(f"{name}: ✅ missing-content search triggered")
        except Exception as e:
            results.append(f"{name}: ❌ {type(e).__name__}")

    return "\n".join(results)
