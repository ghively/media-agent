# Media Agent

A containerized, conversational agent for managing a full personal media ecosystem — TV shows, movies, music, audiobooks, YouTube content, and classic game ROMs. Powered by a local LLM (Qwen 3.5 9B via Ollama) with 49 tools across 7 content providers.

## Status: Production (Phases 1–4 Complete)

| Phase | Scope | Status |
|---|---|---|
| **1 — Core** | Sonarr (TV), Radarr (movies), Emby library, health checks, CLI, OpenAI-compatible API | ✅ Live |
| **2 — Downloads** | SABnzbd, Download Station, unified search, library scanner, naming enforcer, scheduler, dashboard | ✅ Built |
| **3 — Rich Media** | YouTube (yt-dlp), Bandcamp, Audible | ✅ Built |
| **4 — Classic Games** | ROMs (Internet Archive, DAT verification) | ✅ Built |
| **5 — Expansion** | Telegram bot, podcasts, Twitch, comics, ebooks | 📋 Planned |

**49 tools** · **4,230 lines** of Python · **1 Docker container** · **Local LLM** (no external API costs)

---

## Quick Start

```bash
# Clone
git clone git@github.com:ghively/media-agent.git
cd media-agent

# Configure
cp config/settings.yaml.example config/settings.yaml
cp .env.example .env
# Fill in API keys from 1Password vault "Gregory"

# Build and run
docker compose up -d --build

# Verify
curl http://localhost:8088/health
# → {"status":"ok"}

# Interact
docker exec -it media-agent python -m src.main -i
```

---

## Interfaces

| Interface | URL / Command | Auth | Description |
|---|---|---|---|
| **Web Dashboard** | `http://gh-nvidia:8088/dashboard` | None | Service health, download queues, recent activity |
| **CLI (interactive)** | `docker exec -it media-agent python -m src.main -i` | None | Chat REPL — type natural language commands |
| **CLI (one-shot)** | `docker exec media-agent python -m src.main -q "what's downloading?"` | None | Single query, exits |
| **CLI (health)** | `docker exec media-agent python -m src.main --health` | None | Quick health check across all services |
| **OpenAI API** | `POST http://gh-nvidia:8088/v1/chat/completions` | Bearer token | OpenAI-compatible endpoint for Open WebUI / other apps |
| **API (streaming)** | Same endpoint with `"stream": true` | Bearer token | SSE token-by-token streaming |
| **Telegram** | *Pending bot token* | Bot token | Mobile chat interface |

### Using the OpenAI-compatible API

```bash
curl -X POST http://localhost:8088/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "media-agent",
    "messages": [{"role": "user", "content": "list my tv shows"}]
  }'
```

Mount in Open WebUI: Settings → Connections → add `http://gh-nvidia:8088/v1` with your API key.

---

## Capabilities (49 Tools)

### TV Shows — Sonarr (8 tools)
Search and add shows, list monitored library, check queue/history/calendar/health, trigger missing episode searches.

### Movies — Radarr (7 tools)
Search and add movies, list monitored library, check queue/history/health, trigger missing movie searches.

### Emby Library (5 tools)
Search across libraries, browse recent additions, list libraries, trigger scans, get item details.

### Unified Search & Download (2 tools)
`search_media` queries Sonarr + Radarr + Download Station simultaneously and returns ranked results. `download_media` auto-routes to the right client.

### SABnzbd (5 tools)
Queue, history, status, pause, resume.

### Download Station (4 tools)
List, add, pause, resume — Synology's torrent manager.

### Health (3 tools)
One-shot health check across all services, NAS disk space, unified queue status.

### YouTube (4 tools)
Download videos via yt-dlp, manage channel subscriptions, check for new uploads.

### Bandcamp (2 tools)
Download single albums or entire purchased collection.

### Audible (5 tools)
List library, download books, sync new titles, set up/check OAuth authentication.

### ROMs (4 tools)
Search Internet Archive No-Intro collections, download ROMs, verify against DAT files, list collection by platform.

---

## Architecture

The agent uses a **three-layer architecture**: LLM handles intent parsing and exception reasoning; deterministic code handles API calls; a scheduler handles proactive monitoring.

```
User Input → [LLM Intent Parse] → [Tool Selection] → [API Call] → [LLM Response Format] → User
```

The conversational engine is **LangGraph's `create_react_agent`** — the LLM selects tools, calls them, sees results, and loops until it can answer. All 49 tools are registered in a single registry and available to the agent simultaneously.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system diagram, data flow, and component reference.

---

## Infrastructure

| Service | Host | Port | Role |
|---|---|---|---|
| **Sonarr v4** | gh-storage (Synology NAS) | 8989 | TV show manager (native SPK) |
| **Radarr** | gh-storage | 8310 | Movie manager (native SPK) |
| **SABnzbd** | gh-storage | 8080 | Usenet downloader |
| **Download Station** | gh-storage | 5000 | Torrent manager (Synology DSM) |
| **Emby** | gh-media (Intel NUC) | 8096 | Media server / library UI |
| **Ollama** | gh-nvidia (this machine) | 11435 | Local LLM (Qwen 3.5 9B) |

The media-agent container joins the `agent-mesh` Docker network to reach Ollama, and connects to gh-storage/gh-media over the LAN.

---

## Configuration

All secrets live in **1Password vault "Gregory"** and are injected via `.env` (gitignored). The config loader (`src/config.py`) does `${VAR}` substitution from `settings.yaml` → environment variables.

| Variable | Source | Required |
|---|---|---|
| `SONARR_API_KEY` | 1Password "Sonarr API Key (GH-Storage)" | Yes |
| `RADARR_API_KEY` | 1Password "Radarr API Key (GH-Storage)" | Yes |
| `EMBY_API_KEY` | 1Password "Emby API" | Yes |
| `SABNZBD_API_KEY` | 1Password "SABnzbd API Key" | Yes |
| `MEDIA_AGENT_API_KEY` | Self-generated | Yes |
| `HOSTED_LLM_*` | Z.AI / OpenRouter | Optional fallback |

See [`.env.example`](.env.example) and [`config/settings.yaml.example`](config/settings.yaml.example) for all options.

---

## Development

This project is designed for **AI-assisted continuous development**. The following files provide full context for any AI agent (Claude, GPT, Copilot, etc.) picking up this codebase:

| File | Purpose |
|---|---|
| **[CLAUDE.md](CLAUDE.md)** | AI-agent context file — read this first when working on this codebase |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System architecture, data flow, component reference |
| **[docs/](docs/)** | Full documentation wiki (tool reference, dev guide, API reference) |
| **[SPEC.md](SPEC.md)** | Historical design specification (original vision document) |

### Key development patterns

- **All tools are async** `@tool` functions from `langchain_core.tools`
- **All tools return formatted strings** (not dicts) — the LLM sees them as text
- **All tools use `httpx.AsyncClient`** for network calls
- **All tools have try/except** returning `❌` error strings, never raising
- **Config via `get_settings()`** singleton from `src/config.py`
- **Tool registration in `src/tools/registry.py`** — add new tools here

See [docs/development-guide.md](docs/development-guide.md) for the complete development workflow.

---

## Tech Stack

- **Python 3.12** + **LangGraph** (ReAct agent) + **LangChain** (tool protocol)
- **FastAPI** (API server + dashboard)
- **Ollama** (local LLM inference — Qwen 3.5 9B)
- **httpx** (async HTTP client for all service APIs)
- **APScheduler** (proactive monitoring cron)
- **Docker** (single container, joins agent-mesh network)

---

## Project Structure

```
media-agent/
├── CLAUDE.md              # AI context file (READ THIS FIRST)
├── ARCHITECTURE.md        # System architecture + diagrams
├── README.md              # This file
├── SPEC.md                # Historical design spec
├── docker-compose.yml     # Container orchestration
├── Dockerfile             # Build definition
├── requirements.txt       # Python dependencies
├── .env.example           # Environment variable template
├── config/
│   └── settings.yaml.example
├── docs/                  # Documentation wiki
│   ├── README.md          # Wiki index
│   ├── tool-reference.md  # Complete 49-tool reference
│   ├── development-guide.md
│   ├── deployment-guide.md
│   └── api-reference.md
└── src/
    ├── main.py            # Entry point (--serve, --interactive, --query, --health)
    ├── config.py          # Settings loader (YAML + env var substitution)
    ├── scheduler.py       # APScheduler proactive monitoring
    ├── engine/
    │   └── types.py       # Pydantic data models
    ├── llm/
    │   └── client.py      # Circuit-breaker LLM router (local → fallback)
    ├── graphs/
    │   └── conversational.py  # LangGraph ReAct agent + system prompt
    ├── tools/             # LangChain @tool functions
    │   ├── registry.py    # Tool aggregation (all_tools export)
    │   ├── sonarr.py      # 8 TV tools
    │   ├── radarr.py      # 7 movie tools
    │   ├── emby.py        # 5 library tools
    │   ├── health.py      # 3 health tools
    │   ├── sabnzbd.py     # 5 usenet tools
    │   ├── download_station.py  # 4 torrent tools
    │   └── search.py      # 2 unified search tools
    ├── providers/         # Content-specific acquisition providers
    │   ├── base.py        # MediaProvider protocol
    │   ├── youtube.py     # 4 YouTube tools (yt-dlp)
    │   ├── bandcamp.py    # 2 Bandcamp tools
    │   ├── audible.py     # 5 Audible tools
    │   └── rom.py         # 4 ROM tools
    ├── library/           # Library management engine
    │   ├── scanner.py     # Inventory, cross-reference, orphans, duplicates
    │   └── naming.py      # Naming convention enforcement + undo
    └── interfaces/        # User-facing interfaces
        ├── cli.py         # Interactive REPL + one-shot
        ├── openai_api.py  # OpenAI-compatible API (FastAPI)
        └── dashboard.py   # Web dashboard (inline HTML)
```

---

## License

Personal use. Not for distribution.

---

*Built by Kevin (Hermes Agent) for Gene. Living documentation — every runtime change updates these docs.*
