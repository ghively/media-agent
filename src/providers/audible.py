"""Audible audiobook provider — wraps audible-cli.

How audible-cli actually works (verified against the tool's source):

- Auth is PROFILE-based, not file-flag based. There is no ``--auth-file``
  option on any command. The app reads ``config.toml`` + the auth file from
  its config dir, which we pin with the ``AUDIBLE_CONFIG_DIR`` env var so
  auth persists in /config/audible across container restarts.
- ``library list`` has no JSON output; JSON comes from
  ``library export --format json --output <file>`` (writes a file, not
  stdout; ``authors`` is a comma-joined string, not a list of dicts).
- ``decrypt`` is NOT a built-in command (it's an optional plugin). Instead,
  every ``download --aaxc`` writes a ``.voucher`` file next to the ``.aaxc``
  containing the AES key/IV, and ffmpeg decrypts natively with
  ``-audible_key``/``-audible_iv``.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from langchain_core.tools import tool

AUDIBLE_CONFIG_DIR = Path("/config/audible")
AUDIBLE_DOWNLOAD_DIR = Path("/tmp/audible_downloads")


def _env() -> dict:
    """Subprocess env pinning audible-cli's app dir to persistent storage."""
    return {**os.environ, "AUDIBLE_CONFIG_DIR": str(AUDIBLE_CONFIG_DIR)}


def _configured() -> bool:
    return (AUDIBLE_CONFIG_DIR / "config.toml").exists()


async def _run(*cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, env=_env(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(), stderr.decode()


async def _export_library() -> list[dict]:
    """Fetch the library as parsed JSON via ``library export``."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        code, _, stderr = await _run(
            "audible", "library", "export",
            "--format", "json", "--output", str(out_path),
            timeout=60,
        )
        if code != 0:
            raise RuntimeError(stderr[:500])
        return json.loads(out_path.read_text())
    finally:
        out_path.unlink(missing_ok=True)


def _voucher_key_iv(voucher_path: Path) -> tuple[str, str]:
    """Extract the AES key/IV from a .voucher file written by --aaxc."""
    data = json.loads(voucher_path.read_text())
    license_response = (
        data.get("content_license", {}).get("license_response", {})
    )
    key, iv = license_response.get("key"), license_response.get("iv")
    if not key or not iv:
        raise RuntimeError(f"No key/iv in voucher {voucher_path.name}")
    return key, iv


async def _decrypt_aaxc(aaxc_path: Path) -> Path:
    """Decrypt an .aaxc to .m4b with ffmpeg using its voucher's key/IV."""
    voucher = aaxc_path.with_suffix(".voucher")
    if not voucher.exists():
        raise RuntimeError(f"Voucher file missing for {aaxc_path.name}")
    key, iv = _voucher_key_iv(voucher)
    output = aaxc_path.with_suffix(".m4b")
    code, _, stderr = await _run(
        "ffmpeg", "-y",
        "-audible_key", key, "-audible_iv", iv,
        "-i", str(aaxc_path),
        "-c", "copy", str(output),
        timeout=600,
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg decrypt failed: {stderr[-500:]}")
    return output


@tool
async def audible_list_library() -> str:
    """List all audiobooks in your Audible library."""
    try:
        if not _configured():
            return "❌ Audible not authenticated. Run `audible_setup_auth` first."

        books = await _export_library()
        if not books:
            return "Your Audible library is empty."

        lines = [f"Audible library ({len(books)} books):\n"]
        for book in books[:30]:
            title = book.get("title", "Unknown")
            # `authors` is a comma-joined string in the export format
            author = book.get("authors", "Unknown")
            duration = book.get("runtime_length_min", "?")
            lines.append(f"  • {title} by {author} ({duration} min) [asin: {book.get('asin', '?')}]")
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
    Downloads as AAXC, then decrypts to M4B (ffmpeg + the voucher's key)."""
    try:
        if not _configured():
            return "❌ Audible not authenticated. Run `audible_setup_auth` first."

        os.makedirs(AUDIBLE_DOWNLOAD_DIR, exist_ok=True)

        code, _, stderr = await _run(
            "audible", "download", "--asin", asin,
            "--output-dir", str(AUDIBLE_DOWNLOAD_DIR), "--aaxc",
            timeout=600,
        )
        if code != 0:
            return f"❌ Audible download failed: {stderr[:500]}"

        aaxc_files = sorted(
            AUDIBLE_DOWNLOAD_DIR.rglob("*.aaxc"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not aaxc_files:
            return "❌ Downloaded file not found (AAXC)."
        aaxc_path = aaxc_files[0]

        output_path = await _decrypt_aaxc(aaxc_path)
        aaxc_path.unlink(missing_ok=True)

        return (
            f"✅ Downloaded and decrypted: {output_path.name}\n"
            f"   Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB\n"
            f"   Path: {output_path}\n"
            f"   Run `library_sort_dir` to organize into the audiobooks library."
        )

    except asyncio.TimeoutError:
        return "❌ Download timed out. Large audiobooks may need more time."
    except FileNotFoundError:
        return "❌ audible-cli (or ffmpeg) not installed."
    except Exception as e:
        return f"❌ Audible download failed: {type(e).__name__}: {e}"


@tool
async def audible_download_new() -> str:
    """Download audiobooks added to your library since the last sync."""
    try:
        if not _configured():
            return "❌ Audible not authenticated. Run `audible_setup_auth` first."

        from src.preflight import disk_preflight
        problem = disk_preflight(str(AUDIBLE_DOWNLOAD_DIR))
        if problem:
            return problem

        books = await _export_library()

        # Track downloaded ASINs across runs
        from src.config import get_state_dir
        state_file = get_state_dir() / "audible_downloaded.json"
        downloaded: set = set()
        if state_file.exists():
            downloaded = set(json.loads(state_file.read_text()))

        new_books = [b for b in books if b.get("asin") and b["asin"] not in downloaded]
        if not new_books:
            return "No new audiobooks found since last sync."

        os.makedirs(AUDIBLE_DOWNLOAD_DIR, exist_ok=True)
        results = []
        for book in new_books[:5]:  # Limit to 5 per sync
            asin = book["asin"]
            title = book.get("title", "Unknown")
            code, _, stderr = await _run(
                "audible", "download", "--asin", asin,
                "--output-dir", str(AUDIBLE_DOWNLOAD_DIR), "--aaxc",
                timeout=600,
            )
            if code == 0:
                results.append(f"  ✓ {title} ({asin})")
                downloaded.add(asin)
            else:
                results.append(f"  ✗ {title} ({asin}): {stderr[:120]}")

        state_file.write_text(json.dumps(sorted(downloaded)))

        return (
            f"✅ Synced {len(new_books[:5])} new audiobook(s):\n" + "\n".join(results) +
            "\n\nAAXC files are in " + str(AUDIBLE_DOWNLOAD_DIR) +
            " — use audible_download for individual decryption, or ask me to decrypt them."
        )

    except Exception as e:
        return f"❌ Audible sync failed: {type(e).__name__}: {e}"


@tool
async def audible_setup_auth() -> str:
    """Set up Audible authentication. Run this first to configure audible-cli.
    Requires an interactive browser login flow."""
    return (
        "⚠️ Audible authentication is interactive and must be done once in a terminal:\n\n"
        "1. Open a shell in the container:\n"
        "   docker exec -it media-agent bash\n"
        "2. Run the interactive setup (profile-based; there is no --auth-file flag):\n"
        "   AUDIBLE_CONFIG_DIR=/config/audible audible quickstart\n"
        "3. Follow the prompts (marketplace country code, external browser login,\n"
        "   paste the redirect URL back).\n"
        "4. Verify with `audible_check_auth`.\n\n"
        "The profile persists in /config/audible/ and survives container restarts."
    )


@tool
async def audible_check_auth() -> str:
    """Check if Audible authentication is configured and working."""
    if not _configured():
        return "❌ Not authenticated (no /config/audible/config.toml). Run `audible_setup_auth`."
    try:
        code, stdout, stderr = await _run("audible", "activation-bytes", timeout=30)
        if code == 0:
            return "✅ Audible auth is working."
        return f"⚠️ Auth exists but a test call failed: {stderr[:300]}"
    except FileNotFoundError:
        return "❌ audible-cli not installed. Run: pip install audible-cli"
    except Exception as e:
        return f"❌ Failed to check auth: {type(e).__name__}: {e}"
