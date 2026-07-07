"""Bandcamp download provider — wraps bandcamp-downloader (bandcamp-dl)."""
import asyncio
import os
from pathlib import Path
from langchain_core.tools import tool


@tool
async def bandcamp_download(url: str) -> str:
    """Download a Bandcamp album/track with full metadata and artwork.
    Pass the Bandcamp album or track URL. Returns the download path."""
    try:
        download_dir = f"/tmp/bandcamp/{Path(url).stem}"
        os.makedirs(download_dir, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "bandcamp-dl", "--template", "{artist}/{album}/{track_num} - {title}",
            "--directory", download_dir, url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            return f"❌ Bandcamp download failed: {stderr.decode()[:500]}"

        # Find downloaded files
        files = list(Path(download_dir).rglob("*"))
        audio_files = [f for f in files if f.suffix in (".flac", ".mp3", ".wav", ".aac")]

        if audio_files:
            artist = audio_files[0].parent.parent.name
            album = audio_files[0].parent.name
            return f"✅ Downloaded {len(audio_files)} track(s) to {download_dir}\nArtist: {artist}\nAlbum: {album}\n\nRun `library_fix_naming` to organize into the media library."
        else:
            return f"✅ Downloaded files to {download_dir}.\nCheck the directory and run `library_fix_naming` to organize."

    except asyncio.TimeoutError:
        return "❌ Bandcamp download timed out (120s). The file may be large or the URL may be invalid."
    except FileNotFoundError:
        return "❌ bandcamp-dl not installed. Run: pip install bandcamp-downloader"
    except Exception as e:
        return f"❌ Bandcamp download failed: {type(e).__name__}: {e}"


@tool
async def bandcamp_download_collection() -> str:
    """Download all purchased Bandcamp albums from your collection.
    Requires bandcamp-dl to be configured with your account credentials."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "bandcamp-dl", "--collection", "--all",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            output = stderr.decode()[:500]
            if "credentials" in output.lower() or "login" in output.lower():
                return "❌ Bandcamp collection download requires authentication.\nConfigure bandcamp-dl with your identity cookie or run `bandcamp-dl --cookie-file cookie.txt`"
            return f"❌ Collection download failed: {output}"

        return f"✅ Collection download complete.\n{stdout.decode()[:1000]}"

    except asyncio.TimeoutError:
        return "❌ Collection download timed out. Large collections may need more time."
    except FileNotFoundError:
        return "❌ bandcamp-dl not installed."
    except Exception as e:
        return f"❌ Bandcamp collection failed: {type(e).__name__}: {e}"