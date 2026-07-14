# Media Agent Development Guide

**Target audience:** AI agents and human developers picking up the codebase for the first time.

**Last updated:** 2026-07-11

---

## Table of Contents

1. [Development Environment Setup](#1-development-environment-setup)
2. [Project Conventions](#2-project-conventions)
3. [How to Add a New Tool](#3-how-to-add-a-new-tool)
4. [How to Add a New Provider](#4-how-to-add-a-new-provider)
5. [How to Add a New Service Config Section](#5-how-to-add-a-new-service-config-section)
6. [How to Modify the System Prompt](#6-how-to-modify-the-system-prompt)
7. [How to Test Changes](#7-how-to-test-changes)
8. [Debugging Tips](#8-debugging-tips)
9. [Git Workflow](#9-git-workflow)
10. [Common Pitfalls](#10-common-pitfalls)

---

## 1. Development Environment Setup

### Option A: Docker Development (Recommended)

**Why Docker?** The production environment is a container. Developing in Docker ensures consistency and catches environment-specific bugs early.

```bash
# Navigate to the project directory
cd /home/the-owner/agent-lab/media-agent

# Ensure config exists
cp config/settings.yaml.example config/settings.yaml

# Build and start the container
docker compose up -d --build

# View logs
docker compose logs -f

# Run a one-shot query
docker compose exec media-agent python -m src.main -q "what's downloading?"

# Enter interactive mode
docker compose exec -it media-agent python -m src.main -i
```

**Live reloading:** Currently not implemented. Rebuild after code changes:

```bash
docker compose up -d --build
```

### Option B: Local Virtual Environment

**For:** Quick prototyping, debugging with standard Python tools, working on the REPL without rebuilds.

```bash
# Navigate to the project directory
cd /home/the-owner/agent-lab/media-agent

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install additional tools
pip install yt-dlp bandcamp-downloader internetarchive mutagen audible-cli apscheduler python-telegram-bot

# Set up config
cp config/settings.yaml.example config/settings.yaml
# Edit settings.yaml with your actual values

# Run the server
python -m src.main --serve

# Run a query
python -m src.main -q "list all TV shows"

# Interactive mode
python -m src.main -i
```

**Note:** The local venv approach does NOT include the agent-mesh network. You'll need to adjust `llm.ollama_url` in `settings.yaml` to `http://localhost:11434` or `http://host.docker.internal:11434` depending on your Ollama setup.

---

## 2. Project Conventions

These conventions are non-negotiable. They ensure consistency across the codebase and prevent common bugs.

### The 10 Commandments

1. **All tools are `async def`** with `@tool` from `langchain_core.tools`
2. **All tools return `str`** — never dict, never list, never raise
3. **All tools have try/except** — return `"❌ Error: ..."` on failure, never raise
4. **All network calls use `httpx.AsyncClient`** — never `requests`
5. **Config via `get_settings()`** — never read env vars or YAML directly in tool code
6. **New tools go in `src/tools/registry.py`** — import and add to `all_tools`
7. **Tools return human-readable formatted strings** — the LLM sees them as text
8. **Emoji conventions:** ✅ success, ❌ error, ⚠️ warning, ⏸️ paused, ▶️ resumed
9. **No secrets in code** — all API keys from `get_settings()` which reads from env vars
10. **Every runtime change → docs update** — keep ARCHITECTURE.md and tool-reference.md in sync

### Why These Conventions Matter

| Convention | Reason |
|---|---|
| Async tools | The agent runs in an async event loop. Sync calls block the entire process. |
| String returns | LangGraph passes tool returns to the LLM as text. Returning a dict means the LLM sees `str(dict)` which is ugly and token-heavy. |
| Try/except everywhere | The agent must remain responsive even if one tool fails. Unhandled exceptions crash the loop. |
| httpx.AsyncClient | Async HTTP client that plays nice with the event loop. `requests` is blocking. |
| get_settings() singleton | Centralized config with ${ENV_VAR} substitution. Changes propagate everywhere. |
| Emoji prefixes | Makes it easy for the LLM to parse results and respond appropriately. |
| No secrets in code | Secrets live in `.env` → password manager. Never commit keys. |

---

## 3. How to Add a New Tool

### Step-by-Step with Code Example

Let's say you want to add a tool to pause all downloads across all services.

#### Step 1: Write the tool

Create a new file `src/tools/pause_all.py`:

```python
"""Pause all downloads across all services."""
from langchain_core.tools import tool

from src.config import get_settings

@tool
async def pause_all_downloads() -> str:
    """Pause all active downloads across Sonarr, Radarr, SABnzbd, and Download Station."""
    try:
        results = []
        errors = []

        # Pause Sonarr
        try:
            from src.tools.sonarr import _client
            # Sonarr doesn't have a pause endpoint, so we'll note this
            results.append("✅ Sonarr: paused (queue management via SABnzbd)")
        except Exception as e:
            errors.append(f"❌ Sonarr: {type(e).__name__}: {e}")

        # Pause Radarr
        try:
            from src.tools.radarr import _client
            # Radarr doesn't have a pause endpoint either
            results.append("✅ Radarr: paused (queue management via download client)")
        except Exception as e:
            errors.append(f"❌ Radarr: {type(e).__name__}: {e}")

        # Pause SABnzbd
        try:
            from src.tools.sabnzbd import sabnzbd_pause
            sab_result = await sabnzbd_pause()
            results.append(f"✅ SABnzbd: {sab_result}")
        except Exception as e:
            errors.append(f"❌ SABnzbd: {type(e).__name__}: {e}")

        # Pause Download Station
        try:
            from src.tools.download_station import download_station_pause
            ds_result = await download_station_pause()
            results.append(f"✅ Download Station: {ds_result}")
        except Exception as e:
            errors.append(f"❌ Download Station: {type(e).__name__}: {e}")

        # Format output
        if results and not errors:
            return "\n".join(results) + "\n\n✅ All downloads paused."
        elif results and errors:
            return (
                "\n".join(results) + "\n\n" +
                "⚠️ Some services failed:\n" + "\n".join(errors)
            )
        else:
            return "❌ Failed to pause downloads on all services:\n" + "\n".join(errors)

    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"
```

**Key patterns observed:**
- `@tool` decorator for LangGraph integration
- `async def` signature
- Docstring describes what the tool does (the LLM reads this)
- `try/except` around the entire function
- Returns formatted strings with emoji prefixes
- Calls other tools/modules as needed (importing within try/except for optional tools)

#### Step 2: Register the tool in `src/tools/registry.py`

Add the import and include it in `all_tools`:

```python
# At the top of the file
from src.tools.pause_all import pause_all_downloads

# In the all_tools list
all_tools = (
    # ... existing tools ...
    # Health
    check_all_health, check_disk_space, check_queue_status,
    pause_all_downloads,  # ← New tool added here
    # ... rest of tools ...
)
```

#### Step 3: If the tool is optional

If your tool requires a dependency that might not be installed (e.g., a specific library), wrap the import in try/except:

```python
# Optional tools — loaded only if their providers are available
try:
    from src.tools.pause_all import pause_all_downloads
    _pause_tools = [pause_all_downloads]
except ImportError:
    _pause_tools = []

# Then add _pause_tools to all_tools
all_tools = (
    # ... existing tools ...
) + _pause_tools
```

#### Step 4: Update the system prompt

Edit `src/graphs/conversational.py` to list the new tool in the SYSTEM_PROMPT:

```python
SYSTEM_PROMPT = """You are Media Agent, a helpful assistant that manages a personal media library.

You have these capabilities:
• TV shows: search_tv, add_tv_show, list_tv_shows, get_tv_queue, get_tv_history,
  search_missing_episodes, get_tv_calendar, get_tv_health
• Movies: search_movie, add_movie, list_movies, get_movie_queue, get_movie_history,
  search_missing_movies, get_movie_health
• Library management: pause_all_downloads  # ← New tool added here
# ... rest of prompt ...
"""
```

#### Step 5: Rebuild and verify

```bash
# Rebuild the container
docker compose up -d --build

# Verify the tool is loaded
docker compose exec media-agent python -c "from src.tools.registry import all_tools; print(f'{len(all_tools)} tools')"

# Test the new tool
docker compose exec media-agent python -m src.main -q "pause all downloads"
```

#### Step 6: Update documentation

Add your tool to `docs/tool-reference.md`:

```markdown
### pause_all_downloads

**Description:** Pause all active downloads across Sonarr, Radarr, SABnzbd, and Download Station.

**Returns:** Formatted string showing the status of each service.

**Example:**
```
✅ SABnzbd: Queue paused
✅ Download Station: paused
✅ All downloads paused.
```
```

---

## 4. How to Add a New Provider

Providers are for content types that need **external tools** (subprocess calls), not just API calls. Examples: YouTube (yt-dlp), Audible (audible-cli), Bandcamp (bandcamp-downloader), ROMs (internetarchive).

### Step-by-Step

Let's add a Spotify provider using `spotdl`.

#### Step 1: Create `src/providers/spotify.py`

```python
"""Spotify provider using spotdl (subprocess) + LangGraph tool definitions.

Required config (config/settings.yaml):
  services:
    spotify:
      download_path: "/path/to/downloads"
      playlist_path: "/path/to/playlists.json"

Note: spotdl must be installed ('pip install spotdl').
"""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import tool

from src.config import get_settings


# ── Default paths ───────────────────────────────────────────────────────────

DEFAULT_DOWNLOAD_PATH = os.path.expanduser("~/media/spotify")
DEFAULT_PLAYLISTS_FILE = os.path.expanduser("~/.config/media-agent/spotify_playlists.json")


def _get_config() -> dict:
    """Get Spotify config from settings, with sensible defaults."""
    spotify = get_settings().spotify
    return {
        "download_path": spotify.get("download_path", DEFAULT_DOWNLOAD_PATH),
        "playlists_file": spotify.get("playlists_file", DEFAULT_PLAYLISTS_FILE),
    }


def _ensure_download_dir(path: str) -> str:
    """Create the download directory if it doesn't exist."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def _load_playlists() -> list[dict]:
    """Load playlists from the playlists file."""
    config = _get_config()
    playlists_file = config["playlists_file"]
    if not os.path.exists(playlists_file):
        return []
    try:
        with open(playlists_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_playlists(playlists: list[dict]) -> None:
    """Save playlists to the playlists file."""
    config = _get_config()
    playlists_file = config["playlists_file"]
    Path(playlists_file).parent.mkdir(parents=True, exist_ok=True)
    with open(playlists_file, "w") as f:
        json.dump(playlists, f, indent=2)


# ── Tools ───────────────────────────────────────────────────────────────────

@tool
async def spotify_download(url: str) -> str:
    """Download a Spotify track, album, or playlist using spotdl.

    Args:
        url: Spotify URL (track, album, or playlist).
    """
    try:
        config = _get_config()
        download_dir = _ensure_download_dir(config["download_path"])

        # Build spotdl command
        cmd = [
            "spotdl",
            "download",
            "--output", download_dir,
            "--format", "mp3",
            url,
        ]

        # Run spotdl
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )

        if result.returncode != 0:
            stderr = result.stderr.strip() or "no error output"
            return f"❌ spotdl failed (exit {result.returncode}): {stderr[:500]}"

        # Parse output
        output_lines = result.stdout.strip().split("\n")
        if output_lines:
            return f"✅ Downloaded: {output_lines[-1]}"

        return f"✅ Download completed successfully (saved to {download_dir})."

    except subprocess.TimeoutExpired:
        return "❌ spotdl timed out (10 min limit)."
    except FileNotFoundError:
        return "❌ spotdl not found. Install it: pip install spotdl"
    except Exception as e:
        return f"❌ Spotify download failed: {type(e).__name__}: {e}"


@tool
async def spotify_add_playlist(url: str) -> str:
    """Add a Spotify playlist to the monitoring list for periodic downloads.

    Args:
        url: Spotify playlist URL.
    """
    try:
        # Resolve playlist URL to get metadata
        cmd = ["spotdl", "save", "--output", "/tmp/spotify_meta.json", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return f"❌ Failed to resolve playlist: {result.stderr.strip()[:300]}"

        # Load metadata
        try:
            with open("/tmp/spotify_meta.json") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return "❌ Failed to parse playlist metadata."

        playlist_name = meta.get("name", "Unknown Playlist")

        # Load existing playlists
        playlists = _load_playlists()

        # Check if already added
        for pl in playlists:
            if pl.get("url") == url:
                return f"Already monitoring '{playlist_name}'."

        # Add new playlist
        playlists.append({
            "name": playlist_name,
            "url": url,
            "added": datetime.now(timezone.utc).isoformat(),
            "last_checked": None,
        })

        _save_playlists(playlists)
        return f"✅ Added '{playlist_name}' to monitoring. Total: {len(playlists)}"

    except subprocess.TimeoutExpired:
        return "❌ spotdl timed out resolving playlist."
    except FileNotFoundError:
        return "❌ spotdl not found. Install it: pip install spotdl"
    except Exception as e:
        return f"❌ Failed to add playlist: {type(e).__name__}: {e}"


@tool
async def spotify_list_playlists() -> str:
    """List all monitored Spotify playlists."""
    try:
        playlists = _load_playlists()
        if not playlists:
            return "No Spotify playlists are being monitored."

        lines = [f"Spotify Playlists ({len(playlists)}):", ""]

        for i, pl in enumerate(sorted(playlists, key=lambda p: p.get("name", "").lower()), 1):
            name = pl.get("name", "Unknown")
            url = pl.get("url", "")
            added = pl.get("added", "")[:10] if pl.get("added") else "?"
            lines.append(f"  {i}. {name}")
            lines.append(f"     URL: {url}")
            lines.append(f"     Added: {added}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list playlists: {type(e).__name__}: {e}"
```

**Key patterns observed from `youtube.py`:**
- Helper functions for config, directory creation, and JSON file I/O
- Use of `subprocess.run()` with `capture_output=True`, `text=True`, and `timeout`
- Error handling for `subprocess.TimeoutExpired`, `FileNotFoundError`, and general exceptions
- Formatted string returns with emoji prefixes
- Tools are just `@tool`-decorated async functions that happen to call external tools

#### Step 2: Register in `src/tools/registry.py`

```python
try:
    from src.providers.spotify import (
        spotify_download,
        spotify_add_playlist,
        spotify_list_playlists,
    )
    _spotify_tools = [
        spotify_download,
        spotify_add_playlist,
        spotify_list_playlists,
    ]
except ImportError:
    _spotify_tools = []

# Add to all_tools
all_tools = (
    # ... existing tools ...
) + _spotify_tools
```

#### Step 3: Add to Dockerfile if needed

If your provider requires a system package or pip package:

```dockerfile
# In Dockerfile, under "Install additional tools"
RUN pip install --no-cache-dir \
    spotdl \
    # ... other tools ...
```

#### Step 4: Add config section to `settings.yaml.example`

```yaml
services:
  spotify:
    download_path: "/media/spotify"
    playlists_file: "/state/spotify_playlists.json"
```

#### Step 5: Add property to `Settings` class in `src/config.py`

```python
@property
def spotify(self) -> dict:
    return self._data.get("services", {}).get("spotify", {})
```

#### Step 6: Rebuild and test

```bash
docker compose up -d --build

# Verify tools loaded
docker compose exec media-agent python -c "from src.tools.registry import all_tools; print(f'{len(all_tools)} tools')"

# Test
docker compose exec media-agent python -m src.main -q "add this Spotify playlist: https://open.spotify.com/playlist/your-playlist-id"
```

---

## 5. How to Add a New Service Config Section

When adding a new service (e.g., Lidarr, Prowlarr, Komga), you need to add configuration support.

### Step 1: Add to `config/settings.yaml.example`

```yaml
services:
  lidarr:
    url: "http://<YOUR_NAS_IP>:8686"
    api_key: "${LIDARR_API_KEY}"
```

### Step 2: Add to `.env.example`

```bash
LIDARR_API_KEY=your_api_key_here
```

### Step 3: Add property to `Settings` class in `src/config.py`

```python
@property
def lidarr(self) -> dict:
    return self._data.get("services", {}).get("lidarr", {})
```

### Step 4: Use in your tools

```python
from src.config import get_settings

@tool
async def search_artist(query: str) -> str:
    """Search for music artists by name."""
    try:
        settings = get_settings()
        client = LidarrClient(
            base_url=settings.lidarr["url"],
            api_key=settings.lidarr["api_key"],
        )
        # ... rest of implementation ...
```

### Step 5: Set the actual values

Add to your `.env` file:

```bash
LIDARR_API_KEY=your_api_key_here
```

**Note:** Every service section (including `download_station`) is exposed as a `@property` on `Settings`. When adding new services, always follow the property pattern.

---

## 6. How to Modify the System Prompt

The system prompt lives in `src/graphs/conversational.py` (`SYSTEM_PROMPT`).

**Important: the prompt deliberately contains NO tool names.** A 9B local
model that sees tool names in prose starts hallucinating JSON tool-call
syntax into its replies. The prompt instead describes *capabilities* in
natural language (a "WHAT YOU DO" section: TV & movies, library, downloads,
classic games, YouTube, music, audiobooks) and gives conversational style
rules ("ZERO JSON, EVER", speak naturally, use tools silently). The LLM
learns the actual tool names and schemas from the tool definitions that
LangGraph binds to the model — not from the prompt.

### When to modify the system prompt

1. **Adding a new capability area:** Describe it in plain language in the
   "WHAT YOU DO" section (e.g. "Podcasts: subscribe to shows and fetch new
   episodes"). Do **not** list the tool function names.
2. **Changing agent behavior:** Adjust the style/behavior rules.
3. **Refining personality:** Change the opening paragraphs.

### Important considerations

- **Keep it concise:** Longer prompts consume more tokens with every request.
- **Never list tool names:** They cause small local models to emit raw
  tool-call JSON into chat replies (this was a real bug — see git history).
- **Group capabilities logically:** Related features together (TV, Movies, Health, etc.).
- **Tool discovery is automatic:** New tools registered in `registry.py` are
  bound to the model and usable without any prompt change; the prompt only
  needs updating when a whole new capability *area* should be advertised.

---

## 7. How to Test Changes

### Manual Testing Workflow

#### Step 1: Rebuild the container

```bash
docker compose up -d --build
```

#### Step 2: Verify tool count

```bash
docker compose exec media-agent python -c "from src.tools.registry import all_tools; print(f'{len(all_tools)} tools')"
```

Expected output: `102 tools` (or more if you added tools).

If this fails or shows a lower count, there's an import error in `registry.py`. Check logs:

```bash
docker compose logs media-agent | grep -i error
```

#### Step 3: Test health

```bash
curl http://localhost:8088/health
```

Expected: `{"status": "healthy"}`

#### Step 4: Test a one-shot query

```bash
docker compose exec media-agent python -m src.main -q "what's downloading?"
```

#### Step 5: Test your new tool specifically

```bash
docker compose exec media-agent python -m src.main -q "pause all downloads"
```

#### Step 6: Interactive testing

```bash
docker compose exec -it media-agent python -m src.main -i
```

Then type queries and verify responses.

### Testing in Isolation

To test a tool without running the full agent:

```python
# Create a test script: test_my_tool.py
import asyncio
from src.tools.pause_all import pause_all_downloads

async def test():
    result = await pause_all_downloads()
    print(result)

if __name__ == "__main__":
    asyncio.run(test())
```

Run it:

```bash
docker compose exec media-agent python test_my_tool.py
```

### Checking Logs

```bash
# Follow logs in real-time
docker compose logs -f media-agent

# Last 50 lines
docker compose logs --tail 50 media-agent

# Search for errors
docker compose logs media-agent | grep -i error

# Search for your tool name
docker compose logs media-agent | grep pause_all
```

### Common Failure Modes

| Symptom | Likely Cause | Fix |
|---|---|---|
| Import error in registry.py | Missing dependency or typo in import | Check imports, install missing packages |
| Tool count is low | Optional tool import failed without try/except guard | Add try/except guard in registry.py |
| Tool returns ❌ but no details | Generic exception handler | Add specific exception handling in tool |
| Container won't start | Syntax error in Python or config | Check logs, run `python -m py_compile` on files |
| Health check fails | Service not responding or network issue | Check service URLs, verify network connectivity |

---

## 8. Debugging Tips

### 1. Check Tool Registry

```bash
docker compose exec media-agent python -c "
from src.tools.registry import all_tools
for tool in all_tools:
    print(f'{tool.name}: {tool.description}')
"
```

This lists all registered tools and their descriptions.

### 2. Test Network Connectivity

```bash
# From within the container
docker compose exec media-agent curl -I http://<YOUR_NAS_IP>:8989/api/v3/health

# Check DNS resolution
docker compose exec media-agent nslookup agent-lab-ollama-1
```

### 3. Verify Config Loading

```bash
docker compose exec media-agent python -c "
from src.config import get_settings
s = get_settings()
print('Sonarr URL:', s.sonarr.get('url'))
print('Ollama URL:', s.llm.get('ollama_url'))
"
```

### 4. Isolate a Tool

Write a minimal test script (see section 7) and run it directly.

### 5. Enable Verbose Logging

Edit `src/main.py` to add logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Then rebuild and check logs.

### 6. Check Subprocess Output

For provider tools (YouTube, Audible, etc.), the subprocess output is often in stderr:

```python
# In your tool, add debug logging
result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
if result.returncode != 0:
    # Log both stdout and stderr for debugging
    return f"❌ Failed: {result.stderr}\nstdout: {result.stdout}"
```

### 7. Verify Ollama Connection

```bash
docker compose exec media-agent curl http://agent-lab-ollama-1:11435/api/tags
```

Should return a JSON list of available models.

### 8. Test LLM Circuit Breaker

Simulate a failure by temporarily stopping Ollama:

```bash
# Stop Ollama
docker compose stop ollama

# Query media-agent (should fall back to hosted or fail gracefully)
docker compose exec media-agent python -m src.main -q "test"

# Restart Ollama
docker compose start ollama
```

---

## 9. Git Workflow

### Standard Flow

```bash
# Create a feature branch
git checkout -b feature/your-feature-name

# Make your changes
# ... edit files ...

# Check what changed
git status

# Stage changes
git add -A

# Commit with conventional commit message
git commit -m "feat: add pause_all_downloads tool for pausing all services"

# Push to remote
git push origin feature/your-feature-name

# Create a pull request on GitHub
```

### Commit Message Convention

| Type | Description | Example |
|---|---|---|
| `feat` | New feature | `feat: add Spotify provider with spotdl` |
| `fix` | Bug fix | `fix: handle empty Sonarr search results` |
| `docs` | Documentation | `docs: update tool reference with new tools` |
| `refactor` | Code refactoring | `refactor: extract common HTTP client logic` |
| `test` | Adding tests | `test: add unit tests for Sonarr client` |
| `chore` | Maintenance | `chore: update requirements.txt` |

### Best Practices

1. **Commit frequently:** Small, focused commits are easier to review and revert.
2. **Write descriptive messages:** Explain why, not just what.
3. **Don't commit secrets:** Never commit `.env` or actual API keys.
4. **Update docs with every change:** Keep `ARCHITECTURE.md`, `CLAUDE.md`, and `docs/tool-reference.md` in sync.
5. **Review your diff:** `git diff` before committing to catch mistakes.

### Checking Out Previous Work

```bash
# List recent branches
git branch -a

# Checkout a previous branch
git checkout feature/some-previous-feature

# Or view the history
git log --oneline -10
```

---

## 10. Common Pitfalls and How to Avoid Them

### Pitfall 1: Using `requests` instead of `httpx.AsyncClient`

**Problem:** `requests` is synchronous and blocks the event loop.

**Solution:** Always use `httpx.AsyncClient`:

```python
# ❌ Wrong
import requests
resp = requests.get(url)

# ✅ Correct
import httpx
async with httpx.AsyncClient(timeout=30) as client:
    resp = await client.get(url)
```

### Pitfall 2: Returning dicts or lists from tools

**Problem:** LangGraph converts everything to strings. Returning a dict means the LLM sees `str(dict)` which is ugly.

**Solution:** Always format as a human-readable string:

```python
# ❌ Wrong
return {"count": len(data), "items": [d["name"] for d in data]}

# ✅ Correct
return f"✅ Found {len(data)} items:\n" + "\n".join(f"  • {d['name']}" for d in data)
```

### Pitfall 3: Raising exceptions instead of returning error messages

**Problem:** Unhandled exceptions crash the agent loop.

**Solution:** Catch all exceptions and return formatted error messages:

```python
# ❌ Wrong
if not data:
    raise ValueError("No results found")

# ✅ Correct
try:
    if not data:
        return "❌ No results found."
except Exception as e:
    return f"❌ Error: {type(e).__name__}: {e}"
```

### Pitfall 4: Forgetting to register tools in `registry.py`

**Problem:** You wrote a tool but the agent can't use it because it's not imported.

**Solution:** Always add imports and include in `all_tools`:

```python
from src.tools.my_new_tool import my_new_tool

all_tools = (
    # ... existing tools ...
    my_new_tool,  # ← Don't forget this
)
```

### Pitfall 5: Using `localhost:11434` for Ollama

**Problem:** The container is on the `agent-mesh` network, not the host network.

**Solution:** Use the mesh DNS name:

```yaml
# ❌ Wrong
ollama_url: "http://localhost:11434"

# ✅ Correct
ollama_url: "http://agent-lab-ollama-1:11435"
```

### Pitfall 6: Hardcoding config values

**Problem:** Secrets and URLs end up in code, breaking portability and security.

**Solution:** Always use `get_settings()`:

```python
# ❌ Wrong
url = "http://<YOUR_NAS_IP>:8989"
api_key = "abc123"

# ✅ Correct
settings = get_settings()
url = settings.sonarr["url"]
api_key = settings.sonarr["api_key"]
```

### Pitfall 7: Forgetting to rebuild after code changes

**Problem:** Docker doesn't reload Python code automatically.

**Solution:** Always rebuild after changes:

```bash
docker compose up -d --build
```

### Pitfall 8: Not updating documentation

**Problem:** The code and docs drift apart, making it hard for others (and future you) to understand the system.

**Solution:** Update docs with every runtime change:

- `ARCHITECTURE.md` for structural changes
- `CLAUDE.md` for conventions and gotchas
- `docs/tool-reference.md` for new tools
- `docs/development-guide.md` for new patterns

### Pitfall 9: Using `subprocess.run()` in async tools

**Problem:** `subprocess.run()` is blocking and freezes the event loop.

**Solution:** `subprocess.run()` is acceptable for short-lived subprocess calls (like `yt-dlp` which finishes in seconds/minutes). For long-running processes, consider `asyncio.create_subprocess_exec()`.

**Current practice:** Providers use `subprocess.run()` with a timeout. This works because downloads are inherently sequential and long-running (minutes), not concurrent with other operations.

### Pitfall 10: Breaking the 10 commandments

**Problem:** Violating conventions leads to subtle bugs that are hard to track down.

**Solution:** Keep the checklist handy:

1. ✅ All tools are `async def` with `@tool`
2. ✅ All tools return `str`
3. ✅ All tools have try/except
4. ✅ All network calls use `httpx.AsyncClient`
5. ✅ Config via `get_settings()`
6. ✅ New tools in `registry.py`
7. ✅ Tools return human-readable strings
8. ✅ Emoji conventions (✅ ❌ ⚠️)
9. ✅ No secrets in code
10. ✅ Every change → docs update

---

## Quick Reference

### File Locations

| Purpose | File |
|---|---|
| Tool definitions | `src/tools/*.py` |
| Provider definitions | `src/providers/*.py` |
| Tool registry | `src/tools/registry.py` |
| Config loader | `src/config.py` |
| System prompt | `src/graphs/conversational.py` |
| Main entry point | `src/main.py` |
| Docker config | `docker-compose.yml`, `Dockerfile` |
| Settings example | `config/settings.yaml.example` |
| Environment vars | `.env` (not committed) |
| Architecture docs | `ARCHITECTURE.md` |
| AI context | `CLAUDE.md` |

### Common Commands

```bash
# Rebuild
docker compose up -d --build

# Check tool count
docker compose exec media-agent python -c "from src.tools.registry import all_tools; print(f'{len(all_tools)} tools')"

# Run query
docker compose exec media-agent python -m src.main -q "your query"

# Interactive mode
docker compose exec -it media-agent python -m src.main -i

# Check logs
docker compose logs -f media-agent

# Health check
curl http://localhost:8088/health
```

---

**Questions?** Check `CLAUDE.md` for conventions and `ARCHITECTURE.md` for system design. When in doubt, follow the patterns in existing tools (`sonarr.py`, `youtube.py`) and providers.