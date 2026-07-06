"""Bandcamp download provider.

Single album/track downloads use ``bandcamp-dl`` (PyPI package
``bandcamp-downloader``, the iheanyi/Evolution0 project). Its template
placeholders use ``%{field}`` syntax and the output directory flag is
``--base-dir`` — verified against the tool's argparse definitions.

Collection downloads are NOT supported by bandcamp-dl at all; they require
the separate ``bandcamp-downloader`` CLI (easlice project) which reads your
browser's login cookies. The collection tool uses it when present and
explains how to install it when not.
"""
import asyncio
import os
import shutil
from pathlib import Path
from langchain_core.tools import tool

BANDCAMP_TEMPLATE = "%{artist}/%{album}/%{track} - %{title}"


@tool
async def bandcamp_download(url: str) -> str:
    """Download a Bandcamp album/track with full metadata and artwork.
    Pass the Bandcamp album or track URL. Returns the download path."""
    try:
        download_dir = f"/tmp/bandcamp/{Path(url).stem}"
        os.makedirs(download_dir, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "bandcamp-dl", "--template", BANDCAMP_TEMPLATE,
            "--base-dir", download_dir, url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            return f"❌ Bandcamp download failed: {stderr.decode()[:500]}"

        # Find downloaded files
        files = list(Path(download_dir).rglob("*"))
        audio_files = [f for f in files if f.suffix in (".flac", ".mp3", ".wav", ".aac")]

        if audio_files:
            artist = audio_files[0].parent.parent.name
            album = audio_files[0].parent.name
            return f"✅ Downloaded {len(audio_files)} track(s) to {download_dir}\nArtist: {artist}\nAlbum: {album}\n\nRun `library_sort_dir` to organize into the media library."
        else:
            return f"✅ Downloaded files to {download_dir}.\nCheck the directory and run `library_sort_dir` to organize."

    except asyncio.TimeoutError:
        return "❌ Bandcamp download timed out (300s). The album may be large or the URL may be invalid."
    except FileNotFoundError:
        return "❌ bandcamp-dl not installed. Run: pip install bandcamp-downloader"
    except Exception as e:
        return f"❌ Bandcamp download failed: {type(e).__name__}: {e}"


@tool
async def bandcamp_download_collection(username: str = "") -> str:
    """Download all purchased albums from your Bandcamp collection.
    Requires the 'bandcamp-downloader' CLI (easlice project) and a browser
    you are logged in to Bandcamp with.

    Args:
        username: Your Bandcamp username (the name in bandcamp.com/<username>).
    """
    if shutil.which("bandcamp-downloader") is None:
        return (
            "❌ Collection downloads need the separate 'bandcamp-downloader' tool "
            "(the installed bandcamp-dl only handles single album/track URLs).\n"
            "Install it with: pipx install git+https://github.com/easlice/bandcamp-downloader\n"
            "Then log in to Bandcamp in Firefox on the same machine and retry."
        )
    if not username:
        return "❌ Please provide your Bandcamp username (bandcamp.com/<username>)."

    try:
        from src.preflight import disk_preflight
        download_dir = "/tmp/bandcamp/collection"
        os.makedirs(download_dir, exist_ok=True)
        problem = disk_preflight(download_dir)
        if problem:
            return problem

        proc = await asyncio.create_subprocess_exec(
            "bandcamp-downloader", "--browser", "firefox",
            "--directory", download_dir, username,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3600)

        if proc.returncode != 0:
            output = stderr.decode()[:500]
            if "cookie" in output.lower() or "login" in output.lower():
                return (
                    "❌ Could not read Bandcamp login cookies. Log in to "
                    "bandcamp.com in Firefox on this machine, then retry."
                )
            return f"❌ Collection download failed: {output}"

        return (
            f"✅ Collection download complete → {download_dir}\n"
            f"{stdout.decode()[:800]}\n"
            f"Run `library_sort_dir` to organize into the media library."
        )

    except asyncio.TimeoutError:
        return "❌ Collection download timed out (1h). Re-run to resume — completed albums are skipped."
    except Exception as e:
        return f"❌ Bandcamp collection failed: {type(e).__name__}: {e}"
