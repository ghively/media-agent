"""Audible audiobook provider — wraps audible-cli with OAuth + DRM removal.

Paths come from ``settings.audible`` (config/settings.yaml):

- ``auth_dir``: directory holding ``auth.json``. Defaults to ``/state/audible``
  (on the mounted state volume) so authentication survives container
  restarts. A legacy auth file at ``/config/audible/auth.json`` is still
  picked up when the configured location has none.
- ``download_path``: where decrypted M4B files land. Defaults to
  ``/media/audiobooks`` (on the mounted media volume) so Emby can see them.
"""
import asyncio
import json
import os
from pathlib import Path
from langchain_core.tools import tool

from src.config import get_settings

# Import emby_scan for auto-triggering after downloads
from src.tools.emby import _client as _emby_client_factory

# Pre-fix deployments kept auth here (unmounted in stock compose, so it did
# not actually survive restarts — but a manually mounted /config might have it).
_LEGACY_AUTH_FILE = Path("/config/audible/auth.json")


def _auth_file() -> Path:
    cfg = get_settings().audible
    configured = cfg.get("auth_dir")
    if configured:
        return Path(configured) / "auth.json"
    default = Path("/state/audible/auth.json")
    if not default.exists() and _LEGACY_AUTH_FILE.exists():
        return _LEGACY_AUTH_FILE
    return default


def _download_dir() -> Path:
    cfg = get_settings().audible
    return Path(cfg.get("download_path") or "/media/audiobooks")


async def _fetch_library() -> list[dict]:
    """Parsed Audible library for programmatic use (router title lookup).
    Raises on any failure — callers fall back to the LLM path."""
    auth_file = _auth_file()
    if not auth_file.exists():
        raise RuntimeError("Audible not authenticated")
    proc = await asyncio.create_subprocess_exec(
        "audible", "library", "list",
        "--auth-file", str(auth_file),
        "--output", "json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        raise RuntimeError("audible library list failed")
    return json.loads(stdout)


@tool
async def audible_list_library(page: int = 1) -> str:
    """List audiobooks in your Audible library (30 per page, with the ASIN
    codes needed by audible_download). Pass page=2 for the next 30."""
    try:
        auth_file = _auth_file()
        if not auth_file.exists():
            return "❌ Audible not authenticated. Run `audible_setup_auth` first."

        proc = await asyncio.create_subprocess_exec(
            "audible", "library", "list",
            "--auth-file", str(auth_file),
            "--output", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            return f"❌ Failed to list library: {stderr.decode()[:500]}"

        books = json.loads(stdout)
        if not books:
            return "Your Audible library is empty."

        page = max(1, page)
        shown = books[(page - 1) * 30:page * 30]
        if not shown:
            return f"No audiobooks on page {page} — the library has {len(books)} book(s)."
        lines = [f"Audible library ({len(books)} books, page {page}):\n"]
        for book in shown:
            title = book.get("title", "Unknown")
            author = book.get("authors", [{}])[0].get("name", "Unknown")
            duration = book.get("runtime_length_min", "?")
            asin = book.get("asin", "?")
            lines.append(f"  • {title} by {author} ({duration} min) [ASIN: {asin}]")
        remaining = len(books) - page * 30
        if remaining > 0:
            lines.append(f"\n  ... {remaining} more — ask for page {page + 1}")
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
        auth_file = _auth_file()
        if not auth_file.exists():
            return "❌ Audible not authenticated. Run `audible_setup_auth` first."

        download_dir = _download_dir()
        os.makedirs(download_dir, exist_ok=True)

        # Step 1: Download AAXC
        proc = await asyncio.create_subprocess_exec(
            "audible", "download", "--asin", asin,
            "--auth-file", str(auth_file),
            "--output-dir", str(download_dir),
            "--aaxc",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            return f"❌ Audible download failed: {stderr.decode()[:500]}"

        # Find the downloaded AAXC file
        aaxc_files = list(download_dir.rglob("*.aaxc"))
        if not aaxc_files:
            return "❌ Downloaded file not found (AAXC)."

        aaxc_path = aaxc_files[0]

        # Step 2: Remove DRM (decrypt to M4B)
        output_path = aaxc_path.with_suffix(".m4b")
        proc = await asyncio.create_subprocess_exec(
            "audible", "decrypt",
            "--input", str(aaxc_path),
            "--output", str(output_path),
            "--auth-file", str(auth_file),
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
async def audible_download_new(confirm: bool = False) -> str:
    """Download audiobooks added to your library since the last sync (bulk,
    up to 5 per run). Call with confirm=False first: it lists what would be
    downloaded without downloading. After the user approves, call again with
    confirm=True to start the downloads."""
    try:
        auth_file = _auth_file()
        if not auth_file.exists():
            return "❌ Audible not authenticated. Run `audible_setup_auth` first."

        # Get library
        proc = await asyncio.create_subprocess_exec(
            "audible", "library", "list",
            "--auth-file", str(auth_file),
            "--output", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            return f"❌ Failed to list library: {stderr.decode()[:500]}"

        books = json.loads(stdout)
        # Track downloaded ASINs. Ensure the state dir exists first, otherwise
        # write_text() below would raise *after* downloading and nothing would
        # be recorded — every book would re-download on the next run.
        state_file = Path("/state/audible_downloaded.json")
        state_file.parent.mkdir(parents=True, exist_ok=True)
        downloaded = set()
        if state_file.exists():
            downloaded = set(json.loads(state_file.read_text()))

        new_books = [b for b in books if b.get("asin") not in downloaded]
        if not new_books:
            return "No new audiobooks found since last sync."

        if not confirm:
            preview = "\n".join(
                f"  • {b.get('title', 'Unknown')} ({b['asin']})" for b in new_books[:5]
            )
            extra = f"\n  ... and {len(new_books) - 5} more (next runs)" if len(new_books) > 5 else ""
            return (
                f"⏸️ {len(new_books)} new audiobook(s) to download:\n{preview}{extra}\n\n"
                "Nothing downloaded yet. Ask the user to approve, then call "
                "audible_download_new again with confirm=true."
            )

        download_dir = _download_dir()
        os.makedirs(download_dir, exist_ok=True)

        results = []
        success_count = 0
        for book in new_books[:5]:  # Limit to 5 per sync
            asin = book["asin"]
            title = book.get("title", "Unknown")
            results.append(f"Downloading: {title} ({asin})")
            # Download each book
            proc = await asyncio.create_subprocess_exec(
                "audible", "download", "--asin", asin,
                "--auth-file", str(auth_file),
                "--output-dir", str(download_dir),
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
    auth_file = _auth_file()
    return (
        "⚠️ Audible authentication setup requires user interaction.\n\n"
        "To set up:\n"
        f"1. Run: `audible quickstart --auth-file {auth_file}`\n"
        "2. You'll be prompted to open a URL in a browser\n"
        "3. Log in to Amazon and paste the redirect URL back\n"
        "4. Once complete, run `audible_check_auth` to verify\n\n"
        f"The auth file persists in {auth_file.parent}/ (on the state volume) "
        "and survives container restarts.\n"
        "Auth tokens expire ~30 days — the agent will prompt you to re-authenticate."
    )


@tool
async def audible_check_auth() -> str:
    """Check if Audible authentication is still valid."""
    try:
        auth_file = _auth_file()
        if not auth_file.exists():
            return "❌ Not authenticated. Run `audible_setup_auth` to configure."
        size = auth_file.stat().st_size
        if size > 100:
            return f"✅ Auth file found ({size // 1024} KB). Run `audible_list_library` to verify it works."
        else:
            return f"⚠️ Auth file exists but is very small ({size} bytes). May be invalid."
    except Exception as e:
        return f"❌ Failed to check auth: {e}"
