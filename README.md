# Media Agent

A containerized, conversational AI agent for managing a personal media ecosystem — TV shows, movies, music, audiobooks, YouTube content, and classic game ROMs. Powered by a local LLM (qwen3.5:9b via Ollama) with **70 tools** across 12 categories.

Ask it things like *"what's new on my server?"*, *"add The Matrix in 1080p"*, or *"what's downloading?"* — it searches, adds, monitors, and scans your library automatically.

---

## Quick Start (5 minutes)

**Prerequisites:** Docker + Docker Compose on any x86_64 Linux machine with at least 8 GB RAM (GPU optional).

```bash
# 1. Clone
git clone https://github.com/ghively/media-agent.git
cd media-agent

# 2. Configure
cp .env.example .env
cp config/settings.yaml.example config/settings.yaml
# Edit .env and settings.yaml with your service URLs and API keys

# 3. Build and run
docker compose up -d --build

# 4. Verify
curl http://localhost:8088/health
# → {"status":"ok"}

# 5. Chat with it
docker exec -it media-agent python -m src.main -i
```

That's it. The agent runs as a single Docker container and connects to your existing media services over the network.

---

## What You Need (The Services)

This agent doesn't store media itself — it manages **your existing** services. You need at least one of these running somewhere on your network:

| Service | Required? | What it does | Typical host |
|---|---|---|---|
| **Sonarr** | Recommended | TV show management — search, download, organize | NAS, server |
| **Radarr** | Recommended | Movie management — search, download, organize | NAS, server |
| **Emby / Jellyfin** | Recommended | Media library — browse, scan, play | NAS, media server |
| **SABnzbd** | Optional | Usenet download client | NAS, server |
| **Ollama** | Required | Local LLM inference — runs the agent's brain | Same machine or another |

All services communicate over HTTP. They can be on the same machine, a NAS, or anywhere on your network.

---

## Configuration

### 1. Set up your services

Copy the example files:

```bash
cp .env.example .env
cp config/settings.yaml.example config/settings.yaml
```

### 2. Edit `.env` with your actual keys

```bash
# Your media service URLs and API keys
SONARR_URL=http://your-nas:8989
SONARR_API_KEY=your_sonarr_api_key_here

RADARR_URL=http://your-nas:8310
RADARR_API_KEY=your_radarr_api_key_here

EMBY_URL=http://your-media-server:8096
EMBY_API_KEY=your_emby_api_key_here

SABNZBD_URL=http://your-nas:8080
SABNZBD_API_KEY=your_sabnzbd_api_key_here

# Optional: hosted LLM fallback (used when local Ollama is unreachable)
# HOSTED_LLM_URL=https://api.openai.com/v1
# HOSTED_LLM_KEY=sk-...
# HOSTED_LLM_MODEL=gpt-4o-mini

# A key for the OpenAI-compatible API endpoint
MEDIA_AGENT_API_KEY=generate-a-random-key-here
```

### 3. Edit `config/settings.yaml` for quality profiles and paths

```yaml
services:
  sonarr:
    url: "${SONARR_URL}"
    api_key: "${SONARR_API_KEY}"
    quality_profile_id: 4          # Replace with your HD-1080p profile ID
    root_folder_path: "/your/media/tv"  # Your TV show storage path

  radarr:
    url: "${RADARR_URL}"
    api_key: "${RADARR_API_KEY}"
    quality_profile_id: 4          # Replace with your HD-1080p profile ID
    root_folder_path: "/your/media/movies"  # Your movie storage path

  emby:
    url: "${EMBY_URL}"
    api_key: "${EMBY_API_KEY}"

  sabnzbd:
    url: "${SABNZBD_URL}"
    api_key: "${SABNZBD_API_KEY}"
```

**Need to find your quality profile IDs?** Run this after building:

```bash
docker exec media-agent python -c "
import asyncio
from src.tools.sonarr import sonarr_list_quality_profiles
print(asyncio.run(sonarr_list_quality_profiles.ainvoke({})))
"
```

### 4. Build and verify

```bash
docker compose up -d --build
sleep 5
curl http://localhost:8088/health
```

---

## How to Use It

### Chat interface (interactive)

```bash
docker exec -it media-agent python -m src.main -i
```

You can type things like:
- *"What's new on my server?"*
- *"Search for The Matrix"*
- *"Add Breaking Bad in 1080p"*
- *"What's currently downloading?"*
- *"Show me my library"*
- *"Are all my services healthy?"*

The agent will search, present options, and ask for confirmation before adding anything. It never silently downloads content.

### One-shot queries

```bash
docker exec media-agent python -m src.main -q "how much disk space is free?"
docker exec media-agent python -m src.main -q "what's downloading?"
docker exec media-agent python -m src.main -q "list my movies"
```

### Web dashboard

Open `http://your-machine:8088/dashboard` in a browser for a visual overview of service health, download queues, and recent activity.

### OpenAI-compatible API

```bash
curl -X POST http://your-machine:8088/v1/chat/completions \
  -H "Authorization: Bearer YOUR_MEDIA_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "media-agent",
    "messages": [{"role": "user", "content": "list my tv shows"}]
  }'
```

This works with any OpenAI-compatible client (Open WebUI, SillyTavern, etc.).

---

## Architecture

```
User Input (CLI / API / Dashboard)
    │
    ▼
LangGraph ReAct Agent (LLM + 70 tools)
    │
    ├── Sonarr tools (12)   → TV show management
    ├── Radarr tools (10)   → Movie management
    ├── Emby tools (5)      → Library search, scan
    ├── SABnzbd tools (6)   → Download queue, history
    ├── Download Station (6)→ Torrent management
    ├── Health tools (3)    → Service health checks
    ├── Search tools (2)    → Unified cross-source search
    ├── YouTube tools (6)   → Video download + subscriptions
    ├── Bandcamp tools (2)  → Music downloads
    ├── Audible tools (5)   → Audiobook management
    ├── ROM tools (4)       → Retro game collections
    ├── ROM library (4)     → Header ID, dedup, problem checks
    └── Library tools (5)   → Inventory, duplicates, naming
    │
    ▼
Your media services (Sonarr, Radarr, Emby, SABnzbd...)
```

The agent uses **LangGraph's `create_react_agent`** — the LLM (qwen3.5:9b via local Ollama) decides which tools to call, executes them, sees results, and loops until it can answer. All 70 tools are registered in a single registry and available simultaneously.

**Key design points:**
- **Local-first:** Uses local Ollama for all inference. Zero API costs. Optional cloud LLM fallback.
- **Always confirms:** Before adding or downloading anything, the agent searches first, presents results, and asks for explicit confirmation.
- **Automatic scanning:** After confirmed additions, it triggers an Emby library scan so content appears without manual steps.
- **Self-healing:** Tools have try/except wrappers — failures return friendly error messages instead of crashes.

---

## Deployment Guide (for other Hermes agents or devs)

Detailed instructions for deploying in a new environment are in:

| Document | What it covers |
|---|---|
| [CLAUDE.md](CLAUDE.md) | AI context file — read this first when working on the codebase |
| [docs/deployment-guide.md](docs/deployment-guide.md) | Full deployment walkthrough for first-time setup |
| [docs/development-guide.md](docs/development-guide.md) | How to add new tools, providers, or integrations |
| [docs/tool-reference.md](docs/tool-reference.md) | Complete reference for all 70 tools |
| [docs/api-reference.md](docs/api-reference.md) | OpenAI-compatible API documentation |

### For Hermes / Claude / Cursor agents

If you're an AI agent being asked to deploy this, start with `CLAUDE.md` — it contains the 10 commandments, source map, and common gotchas that will save you from making mistakes the original builder already made.

### Quick deployment checklist

1. ✅ Docker + Docker Compose installed
2. ✅ Ollama running with `qwen3.5:9b` pulled (`ollama pull qwen3.5:9b`)
3. ✅ Media services running (Sonarr, Radarr, Emby at minimum)
4. ✅ `.env` populated with real URLs and API keys
5. ✅ `settings.yaml` configured with your quality profiles and storage paths
6. ✅ Port 8088 available on the host
7. ✅ Docker network can reach Ollama (default: `agent-mesh`)

---

## Capabilities (70 Tools)

| Category | Tools | What you can ask |
|---|---|---|
| **TV — Sonarr** | 12 | Search shows, add to library, check queue/history, view calendar, check health, trigger missing episode search, browse quality profiles and root folders, refresh metadata, search seasons |
| **Movies — Radarr** | 10 | Search movies, add to library, check queue/history, check health, browse quality profiles and root folders, refresh metadata |
| **Library — Emby** | 5 | Search across libraries, browse recent additions, list libraries, trigger scan, get item details |
| **Downloads — SABnzbd** | 6 | View queue, history, server status, pause/resume, add NZB |
| **Torrents — Download Station** | 6 | List tasks, add downloads, pause/resume, version info, task statistics |
| **Search** | 2 | Unified cross-source search (movies + TV + torrents), auto-route download |
| **Health** | 3 | Check all services, disk space, queue status |
| **YouTube** | 6 | Download videos, subscribe to channels, check for new uploads, get video info |
| **Bandcamp** | 2 | Download individual albums or entire purchased collection |
| **Audible** | 5 | List library, download books, sync new titles, set up/check auth |
| **ROMs** | 4 | Search Internet Archive collections, download ROM sets, verify with DAT files, browse by platform |
| **ROM Library** | 4 | Scan and identify ROMs by file header, inspect a single ROM, find duplicates (CRC), check for problems |
| **Library** | 5 | Build filesystem inventory, find duplicates, check and fix naming conventions, undo renames |

---

## I Want to Add a New Tool

See the [development guide](docs/development-guide.md), or just tell your AI agent to add one — the `CLAUDE.md` file has everything it needs to get started.

The pattern is:
1. Write an `async def` function with `@tool` decorator
2. Register it in `src/tools/registry.py`
3. Build and verify

---

## Tech Stack

- **Python 3.12** + **LangGraph** (ReAct agent) + **LangChain** (tool protocol)
- **FastAPI** (API server + dashboard)
- **Ollama** (local LLM inference — qwen3.5:9b)
- **httpx** (async HTTP client for all service APIs)
- **APScheduler** (proactive monitoring — health checks, missing searches, cleanup)
- **Docker** (single container deployment)

---

## License

Personal use. Built for sharing — pull requests welcome.

---

*Living documentation — every runtime change updates these docs.*