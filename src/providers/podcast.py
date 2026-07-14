"""Podcast provider — RSS subscriptions + episode downloads (pure httpx).

Subscriptions live in ``/state/podcast_subs.json`` and downloaded-episode
GUIDs in ``/state/podcast_downloaded.json``, so syncs are incremental and
survive restarts. Audio lands under ``settings.podcasts.download_path``
(default ``/media/podcasts/<feed>/``) so Emby can index it.
"""
import asyncio
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from langchain_core.tools import tool

from src.config import get_settings

# Import emby_scan for auto-triggering after downloads
from src.tools.emby import _client as _emby_client_factory

_STATE_DIR = Path(os.environ.get("MEDIA_AGENT_STATE_DIR", "/state"))
_SUBS_FILE = _STATE_DIR / "podcast_subs.json"
_DOWNLOADED_FILE = _STATE_DIR / "podcast_downloaded.json"
MAX_EPISODES_PER_FEED = 3


def _download_root() -> Path:
    cfg = get_settings().podcasts
    return Path(cfg.get("download_path") or "/media/podcasts")


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w \-.()]", "_", name).strip() or "podcast"


def _parse_feed(xml_text: str) -> dict:
    """Parse an RSS feed into {title, episodes: [{title, guid, url}]}.

    Namespaced feeds (itunes etc.) are handled by ignoring namespaces on the
    elements we read. Never raises on missing fields — episodes without an
    audio enclosure are skipped.
    """
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:  # Atom or malformed — not supported
        raise ValueError("not an RSS feed (no <channel>)")
    title = (channel.findtext("title") or "Untitled podcast").strip()
    episodes = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        url = enclosure.get("url", "")
        if not url:
            continue
        ep_title = (item.findtext("title") or "Untitled episode").strip()
        guid = (item.findtext("guid") or url).strip()
        episodes.append({"title": ep_title, "guid": guid, "url": url})
    return {"title": title, "episodes": episodes}


async def _fetch_feed(url: str) -> dict:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return _parse_feed(resp.text)


@tool
async def podcast_subscribe(feed_url: str) -> str:
    """Subscribe to a podcast by its RSS feed URL. New episodes download on
    each podcast_check_new run (and can be scheduled)."""
    try:
        feed = await _fetch_feed(feed_url)
        subs = _load_json(_SUBS_FILE, {})
        name = feed["title"]
        subs[name] = {"url": feed_url}
        _save_json(_SUBS_FILE, subs)
        return (f"✅ Subscribed to '{name}' ({len(feed['episodes'])} episodes "
                f"in feed). Run podcast_check_new to download the latest.")
    except httpx.ConnectError:
        return "❌ Cannot fetch the feed URL."
    except Exception as e:
        return f"❌ Podcast subscribe failed: {type(e).__name__}: {e}"


@tool
async def podcast_unsubscribe(name: str) -> str:
    """Unsubscribe from a podcast by name (as shown by podcast_list_subscriptions).
    Already-downloaded episodes stay on disk."""
    try:
        subs = _load_json(_SUBS_FILE, {})
        match = next((k for k in subs if k.lower() == name.strip().lower()), None)
        if match is None:
            listing = ", ".join(subs) or "none"
            return f"❌ No subscription named '{name}'. Subscribed: {listing}."
        del subs[match]
        _save_json(_SUBS_FILE, subs)
        return f"✅ Unsubscribed from '{match}'."
    except Exception as e:
        return f"❌ Podcast unsubscribe failed: {type(e).__name__}: {e}"


@tool
async def podcast_list_subscriptions() -> str:
    """List podcast subscriptions."""
    try:
        subs = _load_json(_SUBS_FILE, {})
        if not subs:
            return "No podcast subscriptions yet. Use podcast_subscribe with an RSS URL."
        lines = [f"Podcast subscriptions ({len(subs)}):\n"]
        for name, info in sorted(subs.items()):
            lines.append(f"  • {name} — {info.get('url', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Failed to list podcasts: {type(e).__name__}: {e}"


async def _download_episode(client: httpx.AsyncClient, feed_name: str, ep: dict) -> Path:
    dest_dir = _download_root() / _safe_name(feed_name)
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(ep["url"].split("?")[0]).suffix or ".mp3"
    dest = dest_dir / f"{_safe_name(ep['title'])}{suffix}"
    async with client.stream("GET", ep["url"]) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            async for chunk in resp.aiter_bytes(1 << 20):
                fh.write(chunk)
    return dest


@tool
async def podcast_check_new() -> str:
    """Check every podcast subscription for new episodes and download them
    (up to 3 per feed per run, newest first)."""
    try:
        subs = _load_json(_SUBS_FILE, {})
        if not subs:
            return "No podcast subscriptions yet. Use podcast_subscribe with an RSS URL."
        downloaded = set(_load_json(_DOWNLOADED_FILE, []))
        lines = []
        new_count = 0
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            for name, info in subs.items():
                try:
                    feed = await _fetch_feed(info["url"])
                except Exception as fe:
                    lines.append(f"  ⚠️ {name}: feed fetch failed ({type(fe).__name__})")
                    continue
                fresh = [e for e in feed["episodes"] if e["guid"] not in downloaded]
                for ep in fresh[:MAX_EPISODES_PER_FEED]:
                    try:
                        dest = await _download_episode(client, name, ep)
                        downloaded.add(ep["guid"])
                        new_count += 1
                        lines.append(f"  ✓ {name}: {ep['title']} → {dest.name}")
                    except Exception as de:
                        lines.append(f"  ❌ {name}: {ep['title']} failed ({type(de).__name__})")
                if len(fresh) > MAX_EPISODES_PER_FEED:
                    lines.append(f"    ({len(fresh) - MAX_EPISODES_PER_FEED} older "
                                 f"episodes of {name} skipped — run again for more)")
        _save_json(_DOWNLOADED_FILE, sorted(downloaded))

        if new_count:
            try:
                await _emby_client_factory()._post("/emby/Library/Refresh")
                lines.append("✅ Emby library scan triggered.")
            except Exception:
                pass
        header = (f"✅ Downloaded {new_count} new episode(s):" if new_count
                  else "No new podcast episodes.")
        return header + ("\n" + "\n".join(lines) if lines else "")
    except Exception as e:
        return f"❌ Podcast check failed: {type(e).__name__}: {e}"
