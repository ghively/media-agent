"""YouTube provider using yt-dlp (subprocess) + LangGraph tool definitions.

Uses yt-dlp via subprocess (not the Python library) for maximum reliability
and compatibility. Supports downloading videos, managing subscriptions, and
checking for new uploads.

Required config (config/settings.yaml):
  services:
    youtube:
      download_path: "/path/to/downloads"
      subscriptions_file: "/path/to/subscriptions.json"

Note: yt-dlp must be installed on the system ('pip install yt-dlp' or
'apt install yt-dlp').
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from langchain_core.tools import tool

from src.config import get_settings


# Import emby_scan for auto-triggering after downloads
from src.tools.emby import _client as _emby_client_factory


async def _run_ytdlp(cmd: list[str], timeout: int) -> SimpleNamespace:
    """Run a yt-dlp command without blocking the event loop.

    Mirrors subprocess.run's result shape (.returncode/.stdout/.stderr, text)
    but uses asyncio so concurrent requests and the scheduler keep running.
    Raises asyncio.TimeoutError on timeout and FileNotFoundError if yt-dlp
    is not installed.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise
    return SimpleNamespace(
        returncode=proc.returncode,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


# ── Default paths ───────────────────────────────────────────────────────────

DEFAULT_DOWNLOAD_PATH = os.path.expanduser("~/media/youtube")
DEFAULT_SUBS_FILE = os.path.expanduser("~/.config/media-agent/youtube_subs.json")


def _get_config() -> dict:
    """Get YouTube config from settings, with sensible defaults."""
    yt = get_settings().youtube
    return {
        "download_path": yt.get("download_path", DEFAULT_DOWNLOAD_PATH),
        "subscriptions_file": yt.get("subscriptions_file", DEFAULT_SUBS_FILE),
    }


def _ensure_download_dir(path: str) -> str:
    """Create the download directory if it doesn't exist."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def _load_subscriptions() -> list[dict]:
    """Load subscriptions from the subscriptions file."""
    config = _get_config()
    subs_file = config["subscriptions_file"]
    if not os.path.exists(subs_file):
        return []
    try:
        with open(subs_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_subscriptions(subs: list[dict]) -> None:
    """Save subscriptions to the subscriptions file."""
    config = _get_config()
    subs_file = config["subscriptions_file"]
    Path(subs_file).parent.mkdir(parents=True, exist_ok=True)
    with open(subs_file, "w") as f:
        json.dump(subs, f, indent=2)


# ── Tools ───────────────────────────────────────────────────────────────────

@tool
async def youtube_download(url: str, content_type: str = "video") -> str:
    """Download a YouTube video/audio using yt-dlp.

    Downloads the best available quality format. For music/concerts, downloads
    audio-only (best audio). For 'video', downloads best video+audio.

    Args:
        url: YouTube video URL to download.
        content_type: Type of content — 'video' (default), 'concert', 'music',
                      'podcast', or 'clip'. Determines format selection.
    """
    try:
        config = _get_config()
        download_dir = _ensure_download_dir(config["download_path"])

        # Determine format based on content type
        if content_type in ("music", "concert", "podcast"):
            # Audio-only: best audio, embed metadata
            fmt = "bestaudio/best"
            extract_audio = True
        else:
            # Best video+audio
            fmt = "bestvideo+bestaudio/best"
            extract_audio = False

        # Build yt-dlp command
        output_template = os.path.join(download_dir, "%(title)s.%(ext)s")

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--print", "after_move:filepath",
            "-o", output_template,
        ]

        if extract_audio:
            cmd.extend(["-f", "bestaudio", "--extract-audio", "--audio-format", "mp3"])
        else:
            cmd.extend(["-f", fmt, "--merge-output-format", "mkv"])

        # Embed metadata
        cmd.extend(["--embed-metadata", "--add-metadata"])

        # Add the URL
        cmd.append(url)

        # Run yt-dlp (async — does not block the event loop)
        result = await _run_ytdlp(cmd, timeout=600)  # 10 min timeout for downloads

        if result.returncode != 0:
            stderr = result.stderr.strip() or "no error output"
            return f"❌ yt-dlp failed (exit {result.returncode}): {stderr[:500]}"

        # Parse output for the file path
        output_paths = [l.strip() for l in result.stdout.split("\n") if l.strip()]

        # Trigger Emby library scan
        try:
            await _emby_client_factory()._post("/emby/Library/Refresh")
        except Exception:
            pass  # Don't fail if Emby scan fails

        if output_paths:
            return f"✅ Downloaded: {output_paths[-1]}\n✅ Emby library scan triggered."

        return f"✅ Download completed successfully (saved to {download_dir}).\n✅ Emby library scan triggered."

    except asyncio.TimeoutError:
        return "❌ yt-dlp timed out (10 min limit). The download may still be running."
    except FileNotFoundError:
        return "❌ yt-dlp not found. Install it: pip install yt-dlp  or  apt install yt-dlp"
    except Exception as e:
        return f"❌ YouTube download failed: {type(e).__name__}: {e}"


@tool
async def youtube_add_subscription(url: str, content_type: str = "concert") -> str:
    """Subscribe to a YouTube channel for monitoring new uploads.

    Stores the channel URL and content type in a local subscriptions file
    for periodic checking via youtube_check_subscriptions().

    Args:
        url: YouTube channel URL (e.g., https://youtube.com/@channel).
        content_type: Type of content expected — 'concert', 'music', 'video',
                      'podcast', 'vlog'. Default: 'concert'.
    """
    try:
        # Resolve the channel URL to get the channel name via yt-dlp
        cmd = [
            "yt-dlp",
            "--print", "channel",
            "--print", "channel_url",
            "--no-download",
            "--skip-download",
            url,
        ]
        result = await _run_ytdlp(cmd, timeout=30)

        if result.returncode != 0:
            # Fall back to using the URL as-is
            channel_name = url.rstrip("/").split("/")[-1]
            channel_url = url
        else:
            lines = [l.strip() for l in result.stdout.split("\n") if l.strip()]
            channel_name = lines[0] if lines else url
            channel_url = lines[1] if len(lines) > 1 else url

        # Load existing subscriptions
        subs = _load_subscriptions()

        # Check if already subscribed
        for sub in subs:
            if sub["url"] == channel_url or sub["name"] == channel_name:
                return (
                    f"Already subscribed to '{channel_name}' "
                    f"(content_type: {sub.get('content_type', 'video')})."
                )

        # Add new subscription
        subs.append({
            "name": channel_name,
            "url": channel_url,
            "content_type": content_type,
            "added": datetime.now(timezone.utc).isoformat(),
            "last_checked": None,
            "last_upload": None,
        })

        _save_subscriptions(subs)
        return (
            f"✅ Subscribed to '{channel_name}' ({content_type}). "
            f"Total subscriptions: {len(subs)}"
        )

    except asyncio.TimeoutError:
        return "❌ yt-dlp timed out resolving channel URL."
    except FileNotFoundError:
        return "❌ yt-dlp not found. Install it: pip install yt-dlp"
    except Exception as e:
        return f"❌ Failed to add subscription: {type(e).__name__}: {e}"


@tool
async def youtube_check_subscriptions() -> str:
    """Check all subscribed YouTube channels for new uploads.

    Uses yt-dlp to fetch the latest upload for each channel and compares
    against the last known upload. Updates the subscriptions file with
    the latest results.
    """
    try:
        subs = _load_subscriptions()
        if not subs:
            return "No YouTube subscriptions configured. Use youtube_add_subscription() to add some."

        lines = [f"Checking {len(subs)} subscription(s) for new uploads...", ""]
        now = datetime.now(timezone.utc).isoformat()
        new_uploads = []

        for sub in subs:
            name = sub["name"]
            url = sub["url"]
            last_upload = sub.get("last_upload")

            try:
                # Fetch latest uploads via yt-dlp
                cmd = [
                    "yt-dlp",
                    "--flat-playlist",
                    "--playlist-end", "3",
                    "--print", "%(title)s|%(id)s|%(upload_date)s",
                    "--no-download",
                    "--skip-download",
                    url,
                ]
                result = await _run_ytdlp(cmd, timeout=30)

                if result.returncode != 0:
                    lines.append(f"  ⚠️ {name}: yt-dlp error")
                    continue

                uploads = [l.strip() for l in result.stdout.split("\n") if l.strip()]
                if not uploads:
                    lines.append(f"  ⚠️ {name}: no uploads found")
                    continue

                # Parse the latest upload
                latest = uploads[0]
                parts = latest.split("|")
                if len(parts) >= 3:
                    vid_title, vid_id, upload_date = parts[0], parts[1], parts[2]
                    # Format: YYYYMMDD → YYYY-MM-DD
                    if len(upload_date) == 8:
                        upload_date_fmt = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
                    else:
                        upload_date_fmt = upload_date

                    vid_url = f"https://youtube.com/watch?v={vid_id}"

                    if last_upload and vid_id != last_upload:
                        new_uploads.append(f"  🆕 {name}: \"{vid_title}\" ({upload_date_fmt})")
                        lines.append(f"  🆕 {name}: \"{vid_title}\" ({upload_date_fmt})")
                        lines.append(f"     {vid_url}")
                    elif not last_upload:
                        lines.append(f"  📋 {name}: \"{vid_title}\" ({upload_date_fmt}) [first check]")
                    else:
                        lines.append(f"  ✓ {name}: no new uploads (last: {vid_title})")

                    # Update last_upload
                    sub["last_upload"] = vid_id
                else:
                    lines.append(f"  ✓ {name}: checked")

            except asyncio.TimeoutError:
                lines.append(f"  ⚠️ {name}: timed out")
            except Exception as exc:
                lines.append(f"  ⚠️ {name}: {exc}")

            sub["last_checked"] = now

        # Save updated subscriptions
        _save_subscriptions(subs)

        lines.append("")
        if new_uploads:
            lines.append(f"Found {len(new_uploads)} new upload(s)!")
        else:
            lines.append("No new uploads found.")

        return "\n".join(lines)

    except FileNotFoundError:
        return "❌ yt-dlp not found. Install it: pip install yt-dlp"
    except Exception as e:
        return f"❌ Failed to check subscriptions: {type(e).__name__}: {e}"


@tool
async def youtube_list_subscriptions() -> str:
    """List all active YouTube channel subscriptions with their details."""
    try:
        subs = _load_subscriptions()
        if not subs:
            return (
                "No YouTube subscriptions configured. "
                "Use youtube_add_subscription() to add channels."
            )

        lines = [f"YouTube Subscriptions ({len(subs)}):", ""]

        # Sort by name
        for i, sub in enumerate(sorted(subs, key=lambda s: s.get("name", "").lower()), 1):
            name = sub.get("name", "Unknown")
            content_type = sub.get("content_type", "video")
            added = sub.get("added", "")[:10] if sub.get("added") else "?"
            last_checked = sub.get("last_checked", "")
            if last_checked:
                last_checked_dt = last_checked[:10] if len(last_checked) > 10 else last_checked
            else:
                last_checked_dt = "never"
            last_upload = sub.get("last_upload", "—")

            lines.append(f"  {i}. {name}")
            lines.append(f"     Type: {content_type}  |  Added: {added}")
            lines.append(f"     Last checked: {last_checked_dt}")
            lines.append(f"     Last upload: {last_upload}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list subscriptions: {type(e).__name__}: {e}"


@tool
async def youtube_remove_subscription(name_or_url: str) -> str:
    """Remove a YouTube channel subscription by name or URL.

    Args:
        name_or_url: The channel name or URL to remove.
    """
    try:
        subs = _load_subscriptions()
        if not subs:
            return "No subscriptions to remove."

        target = name_or_url.lower().strip()
        before = len(subs)
        subs = [
            s for s in subs
            if s.get("name", "").lower() != target
            and s.get("url", "").lower() != target
        ]

        if len(subs) == before:
            return (
                f"Subscription '{name_or_url}' not found. "
                f"Use youtube_list_subscriptions() to see active subscriptions."
            )

        _save_subscriptions(subs)
        return f"✅ Removed subscription '{name_or_url}'. {len(subs)} remaining."

    except Exception as e:
        return f"❌ Failed to remove subscription: {type(e).__name__}: {e}"


@tool
async def youtube_get_info(url: str) -> str:
    """Get metadata and format info about a YouTube video without downloading.

    Args:
        url: YouTube video URL to inspect.
    """
    try:
        cmd = [
            "yt-dlp",
            "--print", "title",
            "--print", "channel",
            "--print", "upload_date",
            "--print", "duration",
            "--print", "view_count",
            "--print", "like_count",
            "--print", "description",
            "--no-download",
            "--skip-download",
            url,
        ]
        result = await _run_ytdlp(cmd, timeout=30)

        if result.returncode != 0:
            return f"❌ Failed to get video info: {result.stderr.strip()[:300]}"

        lines = [l.strip() for l in result.stdout.split("\n") if l.strip()]

        # yt-dlp prints each field on its own line
        info = {
            "title": lines[0] if len(lines) > 0 else "Unknown",
            "channel": lines[1] if len(lines) > 1 else "Unknown",
            "upload_date": lines[2] if len(lines) > 2 else "?",
            "duration_sec": lines[3] if len(lines) > 3 else "?",
            "views": lines[4] if len(lines) > 4 else "?",
            "likes": lines[5] if len(lines) > 5 else "?",
            "description": lines[6] if len(lines) > 6 else "",
        }

        # Format duration
        duration = info["duration_sec"]
        try:
            secs = int(duration)
            h, remainder = divmod(secs, 3600)
            m, s = divmod(remainder, 60)
            if h:
                duration_str = f"{h}h {m}m {s}s"
            else:
                duration_str = f"{m}m {s}s"
        except (ValueError, TypeError):
            duration_str = duration

        # Format upload date
        upload_date = info["upload_date"]
        if len(upload_date) == 8:
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

        output = [
            f"Title:       {info['title']}",
            f"Channel:     {info['channel']}",
            f"Uploaded:    {upload_date}",
            f"Duration:    {duration_str}",
            f"Views:       {info['views']}",
            f"Likes:       {info['likes']}",
        ]
        if info["description"]:
            desc = info["description"][:300]
            output.append(f"\nDescription:\n{desc}")

        return "\n".join(output)

    except asyncio.TimeoutError:
        return "❌ yt-dlp timed out fetching video info."
    except FileNotFoundError:
        return "❌ yt-dlp not found. Install it: pip install yt-dlp"
    except Exception as e:
        return f"❌ Failed to get video info: {type(e).__name__}: {e}"