"""Twitch provider — live checks and stream recording via streamlink.

Recordings can run for hours, so ``twitch_record`` starts the streamlink
subprocess detached and returns immediately; ``twitch_recordings`` reports
progress. Output lands under ``settings.twitch.download_path`` (default
``/media/twitch``). Channel names are validated (alphanumeric/underscore)
before ever reaching the command line.
"""
import asyncio
import re
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from src.config import get_settings

_CHANNEL_RE = re.compile(r"^\w{3,30}$")

# Live recordings: channel → {"proc": Process, "file": Path, "started": str}
_recordings: dict[str, dict] = {}


def _download_root() -> Path:
    cfg = get_settings().twitch
    return Path(cfg.get("download_path") or "/media/twitch")


def _clean_channel(channel: str) -> str | None:
    channel = channel.strip().lower()
    channel = channel.removeprefix("https://").removeprefix("http://")
    channel = channel.removeprefix("www.").removeprefix("twitch.tv/")
    channel = channel.strip("/ ")
    return channel if _CHANNEL_RE.match(channel) else None


@tool
async def twitch_check_live(channel: str) -> str:
    """Check whether a Twitch channel is live (and what stream qualities are
    available). Pass the channel name or twitch.tv URL."""
    try:
        name = _clean_channel(channel)
        if name is None:
            return f"❌ '{channel}' doesn't look like a Twitch channel name."
        proc = await asyncio.create_subprocess_exec(
            "streamlink", "--json", f"https://twitch.tv/{name}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        import json
        try:
            data = json.loads(stdout or b"{}")
        except json.JSONDecodeError:
            data = {}
        streams = data.get("streams") or {}
        if proc.returncode != 0 or not streams:
            return f"📴 {name} is not live right now."
        qualities = ", ".join(streams.keys())
        return f"🔴 {name} is LIVE. Available qualities: {qualities}. Use twitch_record to record."
    except asyncio.TimeoutError:
        return "❌ Twitch check timed out."
    except FileNotFoundError:
        return "❌ streamlink not installed. Run: pip install streamlink"
    except Exception as e:
        return f"❌ Twitch check failed: {type(e).__name__}: {e}"


@tool
async def twitch_record(channel: str, quality: str = "best") -> str:
    """Start recording a live Twitch stream to the media library. Returns
    immediately — the recording runs in the background until the stream ends
    (check progress with twitch_recordings). One recording per channel."""
    try:
        name = _clean_channel(channel)
        if name is None:
            return f"❌ '{channel}' doesn't look like a Twitch channel name."
        if not re.match(r"^[\w,]{2,30}$", quality):
            return f"❌ '{quality}' isn't a valid quality (try 'best' or '720p')."
        existing = _recordings.get(name)
        if existing and existing["proc"].returncode is None:
            return f"⚠️ Already recording {name} → {existing['file'].name}"

        dest_dir = _download_root()
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"{name}_{stamp}.ts"

        proc = await asyncio.create_subprocess_exec(
            "streamlink", "--output", str(dest),
            f"https://twitch.tv/{name}", quality,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        # Give streamlink a moment to fail fast (offline channel, bad quality).
        try:
            await asyncio.wait_for(proc.wait(), timeout=8)
            _recordings.pop(name, None)
            return (f"📴 Recording didn't start — {name} is probably offline "
                    f"(streamlink exited with code {proc.returncode}).")
        except asyncio.TimeoutError:
            pass  # still running → recording is live
        _recordings[name] = {
            "proc": proc, "file": dest,
            "started": datetime.now().strftime("%H:%M:%S"),
        }
        return (f"🔴 Recording {name} ({quality}) → {dest}\n"
                "It runs until the stream ends. Check with twitch_recordings.")
    except FileNotFoundError:
        return "❌ streamlink not installed. Run: pip install streamlink"
    except Exception as e:
        return f"❌ Twitch record failed: {type(e).__name__}: {e}"


@tool
async def twitch_recordings() -> str:
    """Show the status of Twitch recordings started this session."""
    try:
        if not _recordings:
            return "No Twitch recordings this session."
        lines = ["Twitch recordings:\n"]
        for name, rec in _recordings.items():
            proc = rec["proc"]
            size_mb = 0.0
            try:
                size_mb = rec["file"].stat().st_size / 1024 / 1024
            except OSError:
                pass
            if proc.returncode is None:
                lines.append(f"  🔴 {name} — recording since {rec['started']} "
                             f"({size_mb:.0f} MB) → {rec['file'].name}")
            else:
                lines.append(f"  ✅ {name} — finished ({size_mb:.0f} MB) → {rec['file'].name}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Failed to list recordings: {type(e).__name__}: {e}"
