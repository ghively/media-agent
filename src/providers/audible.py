"""Audible audiobook provider — wraps audible-cli with OAuth + DRM removal."""
import asyncio
import json
import os
import subprocess
from pathlib import Path
from langchain_core.tools import tool

from src.engine.types import MediaItem, AcquireResult, JobStatus


# Import emby_scan for auto-triggering after downloads
from src.tools.emby import _client as _emby_client_factory

AUDIBLE_AUTH_DIR = Path("/config/audible")
AUDIBLE_AUTH_FILE = AUDIBLE_AUTH_DIR / "auth.json"
AUDIBLE_DOWNLOAD_DIR = Path("/tmp/audible_downloads")


@tool
async def audible_list_library() -> str:
    """List all audiobooks in your Audible library."""
    try:
        if not AUDIBLE_AUTH_FILE.exists():
            return "❌ Audible not authenticated. Run `audible_setup_auth` first."

        proc = await asyncio.create_subprocess_exec(
            "audible", "library", "list",
            "--auth-file", str(AUDIBLE_AUTH_FILE),
            "--output", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            return f"❌ Failed to list library: {stderr.decode()[:500]}"

        books = json.loads(stdout)
        if not books:
            return "Your Audible library is empty."

        lines = [f"Audible library ({len(books)} books):\n"]
        for book in books[:30]:
            title = book.get("title", "Unknown")
            author = book.get("authors", [{}])[0].get("name", "Unknown")
            duration = book.get("runtime_length_min", "?")
            lines.append(f"  • {title} by {author} ({duration} min)")
        if len(books) > 30:
            lines.append(f"\n  ... and {len(books) - 30} more")
        return "\n".join(lines)

    except FileNotFoundError:
        return "❌ audible-cli not installed. Run: pip install audible-cli"
    except Exception as e:
        return f"❌ Audible library failed: {type(e).__name__}: {e}"


@tool
async def audible_download(asin: str) -> str:
    """Download an audiobook by ASIN (Amazon Standard Identification Number).
    Downloads as AAXC, then decrypts to M4B with embedded metadata."""
    try:
        if not AUDIBLE_AUTH_FILE.exists():
            return "❌ Audible not authenticated. Run `audible_setup_auth` first."

        # Create download directory
        os.makedirs(AUDIBLE_DOWNLOAD_DIR, exist_ok=True)

        # Step 1: Download AAXC
        proc = await asyncio.create_subprocess_exec(
            "audible", "download", "--asin", asin,
            "--auth-file", str(AUDIBLE_AUTH_FILE),
            "--output-dir", str(AUDIBLE_DOWNLOAD_DIR),
            "--aaxc",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            return f"❌ Audible download failed: {stderr.decode()[:500]}"

        # Find the downloaded AAXC file
        aaxc_files = list(Path(AUDIBLE_DOWNLOAD_DIR).rglob("*.aaxc"))
        if not aaxc_files:
            return "❌ Downloaded file not found (AAXC)."

        aaxc_path = aaxc_files[0]

        # Step 2: Remove DRM (decrypt to M4B)
        output_path = aaxc_path.with_suffix(".m4b")
        proc = await asyncio.create_subprocess_exec(
            "audible", "decrypt",
            "--input", str(aaxc_path),
            "--output", str(output_path),
            "--auth-file", str(AUDIBLE_AUTH_FILE),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            return f"❌ DRM removal failed: {stderr.decode()[:500]}\nThe AAXC file is at {aaxc_path}"

        # Cleanup AAXC
        aaxc_path.unlink(missing_ok=True)

        # Trigger Emby library scan
        try:
            await _emby_client_factory()._post("/emby/Library/Refresh")
        except Exception:
            pass  # Don't fail if Emby scan fails

        return (
            f"✅ Downloaded and decrypted: {output_path.name}\n"
            f"   Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB\n"
            f"   Path: {output_path}\n"
            f"   ✅ Emby library scan triggered."
        )

    except asyncio.TimeoutError:
        return "❌ Download timed out. Large audiobooks may need more time."
    except FileNotFoundError:
        return "❌ audible-cli not installed. Run: pip install audible-cli"
    except Exception as e:
        return f"❌ Audible download failed: {type(e).__name__}: {e}"


@tool
async def audible_download_new() -> str:
    """Download audiobooks added to your library since the last sync."""
    try:
        # Get library
        proc = await asyncio.create_subprocess_exec(
            "audible", "library", "list",
            "--auth-file", str(AUDIBLE_AUTH_FILE),
            "--output", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            return f"❌ Failed to list library: {stderr.decode()[:500]}"

        books = json.loads(stdout)
        # Track downloaded ASINs
        state_file = Path("/state/audible_downloaded.json")
        downloaded = set()
        if state_file.exists():
            downloaded = set(json.loads(state_file.read_text()))

        new_books = [b for b in books if b.get("asin") not in downloaded]
        if not new_books:
            return "No new audiobooks found since last sync."

        results = []
        success_count = 0
        for book in new_books[:5]:  # Limit to 5 per sync
            asin = book["asin"]
            title = book.get("title", "Unknown")
            results.append(f"Downloading: {title} ({asin})")
            # Download each book
            proc = await asyncio.create_subprocess_exec(
                "audible", "download", "--asin", asin,
                "--auth-file", str(AUDIBLE_AUTH_FILE),
                "--output-dir", str(AUDIBLE_DOWNLOAD_DIR),
                "--aaxc",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120)
            # Only mark as downloaded if the subprocess succeeded
            if proc.returncode == 0:
                downloaded.add(asin)
                success_count += 1
            else:
                results.append(f"  ❌ Failed to download {title}")

        # Save state
        state_file.write_text(json.dumps(list(downloaded)))

        # Trigger Emby library scan
        try:
            await _emby_client_factory()._post("/emby/Library/Refresh")
        except Exception:
            pass  # Don't fail if Emby scan fails

        emoji = "✅" if success_count else "⚠️"
        return f"{emoji} Downloaded {success_count} new audiobook(s):\n" + "\n".join(results) + "\n✅ Emby library scan triggered."

    except Exception as e:
        return f"❌ Audible sync failed: {type(e).__name__}: {e}"


@tool
async def audible_setup_auth() -> str:
    """Set up Audible authentication. Run this first to configure audible-cli.
    Requires a browser login flow — you'll be prompted for a verification code."""
    return (
        "⚠️ Audible authentication setup requires user interaction.\n\n"
        "To set up:\n"
        "1. Run: `audible quickstart --auth-file /config/audible/auth.json`\n"
        "2. You'll be prompted to open a URL in a browser\n"
        "3. Log in to Amazon and paste the redirect URL back\n"
        "4. Once complete, run `audible_check_auth` to verify\n\n"
        "The auth file will persist in /config/audible/ and survive container restarts.\n"
        "Auth tokens expire ~30 days — the agent will prompt you to re-authenticate."
    )


@tool
async def audible_check_auth() -> str:
    """Check if Audible authentication is still valid."""
    if not AUDIBLE_AUTH_FILE.exists():
        return "❌ Not authenticated. Run `audible_setup_auth` to configure."
    try:
        size = AUDIBLE_AUTH_FILE.stat().st_size
        if size > 100:
            return f"✅ Auth file found ({size // 1024} KB). Run `audible_list_library` to verify it works."
        else:
            return f"⚠️ Auth file exists but is very small ({size} bytes). May be invalid."
    except Exception as e:
        return f"❌ Failed to check auth: {e}"