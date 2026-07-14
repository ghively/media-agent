# Media Agent — Architecture

**Version:** 2.0 (as-built)  
**Last updated:** 2026-07-11  
**Status:** Reflects actual deployed system

> For the original design vision (including planned features), see [SPEC.md](SPEC.md). This document describes what is **actually built and running**.

---

## 1. System Overview

Media Agent is a single Docker container running on **your-gpu-host** (NVIDIA RTX 3060 workstation). It provides natural-language control over a media ecosystem spanning three physical hosts:

```
┌──────────────────────────────────────────────────────────────────────┐
│                     your-gpu-host (this machine)                         │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                   media-agent container                       │   │
│  │                    (127.0.0.1:8088)                           │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐     │   │
│  │  │  FastAPI    │  │  APScheduler │  │  LangGraph ReAct  │     │   │
│  │  │  Server     │  │  (daemon     │  │  Agent (92 tools) │     │   │
│  │  │  :8088      │  │   thread)    │  │                   │     │   │
│  │  │             │  │              │  │  ┌─────────────┐ │     │   │
│  │  │ • /v1/chat  │  │ • health 30m │  │  │   Qwen 3.5   │ │     │   │
│  │  │ • /dashboard│  │ • missing 12h│  │  │    9B LLM    │ │     │   │
│  │  │ • /health   │  │ • cleanup 3am│  │  │  (via Ollama)│ │     │   │
│  │  └──────┬─────┘  └──────┬───────┘  │  └──────┬──────┘ │     │   │
│  │         └───────────────┼──────────└────────┼────────┘     │   │
│  │                         └───────────────────┘               │   │
│  └────────────────────────────────┬─────────────────────────────┘   │
│                                   │ agent-mesh (Docker network)      │
│  ┌───────────────────────────────▼─────────────────────────────┐   │
│  │              ollama container (:11435)                       │   │
│  │              Model: qwen3.5:9b (~6.6 GB VRAM)               │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                    │ LAN (your local subnet)
        ┌───────────┴───────────────────────┐
        ▼                                   ▼
┌──────────────────────┐          ┌──────────────────────┐
│  your-nas (NAS)    │          │  your-media-host (NUC)      │
│  Synology DS1817+    │          │  Intel NUC           │
│  <YOUR_NAS_IP>       │          │  <YOUR_MEDIA_IP>       │
│                      │          │                      │
│  • Sonarr   :8989    │          │  • Emby     :8096    │
│  • Radarr   :8310    │          │    (4GB tmpfs        │
│  • SABnzbd  :8080    │          │     transcode)       │
│  • Download Stn:5000 │          │                      │
│  • ~90TB raw storage │          └──────────────────────┘
└──────────────────────┘
```

---

## 2. Component Architecture

### 2.1 Entry Point (`src/main.py`)

Four modes, selected via CLI args:

| Flag | Mode | What it does |
|---|---|---|
| `--serve` / `-s` | **Server** (default in Docker) | Starts FastAPI + dashboard + scheduler |
| `--interactive` / `-i` | **CLI REPL** | Interactive chat loop |
| `--query` / `-q` | **One-shot** | Single query, print result, exit |
| `--health` | **Health check** | Quick service health report |

The server mode mounts the dashboard routes onto the FastAPI app and starts the scheduler (an `AsyncIOScheduler` bound to the app's event loop) on FastAPI startup before launching uvicorn.

### 2.2 LLM Engine (`src/llm/client.py`)

**Circuit breaker pattern** — routes to local Ollama first, falls back to hosted API if local fails 3 times:

```
          ┌─────────┐
 request  │ CLOSED  │ ──→ local Ollama (Qwen 3.5 9B)
─────────►│ (normal)│         │
          └─────────┘    success? ──YES──→ reset failure count
              ▲               │
              │              NO (×3)
              │               ▼
          ┌─────────┐    ┌─────────┐
 reset    │HALF_OPEN│◄──│  OPEN   │──→ fallback LLM (if configured)
 after    │ (probe) │    │(failing)│    or local (if no fallback)
 60s      └─────────┘    └─────────┘
```

| State | Behavior |
|---|---|
| `CLOSED` | Use local Ollama. Track failures. |
| `OPEN` | Local is down. Use fallback (or local if no fallback configured). After 60s, transition to HALF_OPEN. |
| `HALF_OPEN` | Send one probe request to local. If success → CLOSED. If fail → OPEN. |

**Configuration** (`config/settings.yaml`):
```yaml
llm:
  ollama_url: "http://agent-lab-ollama-1:11435"  # agent-mesh DNS name
  ollama_model: "qwen3.5:9b"
  hosted_url: ""    # Optional Z.AI/OpenRouter fallback
  hosted_key: ""
  hosted_model: ""
  temperature: 0        # defaults to 0.2 — low temp keeps tool calls reliable
  timeout: 120          # per-request LLM timeout (seconds)
  num_ctx: 16384        # context window — 92 tool schemas + prompt + history
                        # overflow 8192 and Ollama truncates silently from the top
  num_predict: 1024     # generation cap
  keep_alive: "30m"     # keep model resident in VRAM between requests
  reasoning: false      # disable qwen3 thinking blocks (latency win)
```

### 2.3 Deterministic Router (`src/graphs/router.py`) — the fast path

Every user message hits the **deterministic intent router before the LLM**.
Politeness/filler is stripped first ("hey can you … please" routes like the
bare command), coverage is tracked (`get_stats()`, surfaced on the dashboard
as "⚡ N% instant"), and full acquire flows run without any LLM: audiobook
by title, add-artist, and indexer search→grab (Prowlarr → qBittorrent/DS/SAB).
~45 intent groups spanning every tool domain — TV/movies, health/disk/queues,
Emby, SABnzbd, Download Station, **ROMs & emulation platforms**, **YouTube**,
**Audible audiobooks**, **Bandcamp**, and **library maintenance** — are
matched with conservative regex patterns and answered by calling the tools
directly, typically in one service round-trip instead of a multi-second LLM
ReAct loop. A miss returns `None` and the message falls through to the LLM
agent.

```
User message
     │
     ▼
try_route(message, thread_id)          src/graphs/router.py
     │
     ├─ 1. pending confirmation? ("yes", "add #2", "the first one", "no")
     │     → media pick → add_movie / add_tv_show
     │     → ROM pick   → rom_download(identifier, platform)
     │     → yes/no action → run it (bulk download, file rename, ...)
     ├─ 2. media URL? (checked before the pattern table)
     │     → YouTube link + download/subscribe/info verb → yt tools
     │       (bare link: show info, offer to download — pending yes/no)
     │     → Bandcamp link → bandcamp_download (bare link asks first)
     │     → magnet / .torrent → download_station_add (bare link asks first)
     │     → .nzb → sabnzbd_add_nzb (category inferred: tv vs movies)
     ├─ 3. intent match? ("what's downloading?", "download snes roms",
     │     "list my audiobooks", "check youtube subscriptions",
     │     "fix naming in /media/tv", "verify my snes roms", ...)
     │     → call tool(s) directly, return formatted string
     │     → search/add/ROM intents store numbered results per thread
     │       (15-min TTL) so the confirmation flow is deterministic too
     └─ no match / handler crash → None → LangGraph ReAct agent
```

Intent domains (see `_INTENTS` in router.py — order matters, specific first):

| Domain | Examples | Tools |
|---|---|---|
| Status | "what's downloading?", "is everything healthy?", "disk space", "download speed" | health, sabnzbd_status |
| TV/Movies | "add Breaking Bad", "list my shows", "missing episodes", "tv queue", "quality profiles" | sonarr/radarr |
| Emby | "do I have The Matrix?", "recently added", "scan the library", "list libraries" | emby |
| ROMs / emulation | "download snes roms", "list my game collection", "verify my super nintendo roms" | rom (Internet Archive), platform aliases → slugs (super nintendo → snes, playstation → psx, ...) |
| ROM library care | "scan my roms", "debug my roms", "find duplicate snes roms", "get metadata for /media/roms/x.sfc" | rom_tools → rom_analyzer: header parsing (title/region/checksums), CRC32 dedup incl. inside zips, corrupt/byte-swapped/copier-header/cue-bin checks |
| YouTube | paste a link (info + offer), "download <url> as music", "subscribe to <url>", "check subscriptions" | youtube |
| Audiobooks | "list my audiobooks", "download audiobook <ASIN>", "sync audible", "check audible auth" | audible |
| Music | "download <bandcamp url>", "download my bandcamp collection" (confirms first) | bandcamp |
| Library | "find duplicates in /media/movies", "check/fix naming in /media/tv" (fix confirms first, undo log), "inventory /media/tv" | library_tools |
| Downloads | "pause downloads", "torrents", "usenet queue", magnet/.nzb/.torrent URLs | sabnzbd, download_station |

Hardening details:

- Normalization **preserves case** — URLs, ASINs, file paths, and channel
  names are case-sensitive payloads; patterns match case-insensitively.
- Deictic guard: "grab it" / "add the first one" with **no** router-pending
  selection falls through to the LLM (it refers to LLM-shown results).
- Anything bulky or irreversible (ROM sets — sizes shown, Bandcamp
  collection sync, file renames) requires a yes/no confirmation first.
- A non-ASIN "download audiobook <title>" falls through to the LLM, which
  looks up the ASIN in the Audible library.

Router-handled exchanges are written into the agent's checkpoint via
`record_exchange()`, so the LLM keeps full conversational context for
follow-ups either way. Because the router is plain Python, every routed
command keeps working even when Ollama is down.

### 2.4 Conversational Engine (`src/graphs/conversational.py`)

Uses **LangGraph's `create_react_agent`** — the prebuilt ReAct (Reason + Act) loop:

```
User message
     │
     ▼
┌─────────────┐     tool_calls?     ┌──────────────┐
│  LLM Call   │────────────────────►│ Execute Tools│
│ (Qwen 3.5)  │                     │ (parallel)   │
└─────────────┘◄────────────────────└──────────────┘
     │           results back              │
     │ (no more tool_calls)                │
     ▼                                     │
┌─────────────┐                            │
│  Response   │◄───────────────────────────┘
│  to user    │
└─────────────┘
```

The agent loops: LLM decides which tools to call → tools execute → results go back to LLM → LLM either calls more tools or produces a final response.

**System prompt** (in `conversational.py`) defines the agent's personality, lists available capabilities, and sets formatting rules (✅ ❌ ⚠️ emoji, concise bullet-point responses, search-before-add pattern).

**Runtime hardening.** All interfaces call `run_agent()` / `stream_agent()` instead of invoking the compiled graph directly. These helpers:

- always pass a `thread_id` (mandatory — the graph has a checkpointer: SQLite
  at `/state/agent_memory.db` so memory survives restarts, falling back to
  in-process MemorySaver when the state volume is absent);
- enforce `RECURSION_LIMIT = 16` on the ReAct loop and map `GraphRecursionError` to a friendly "break it into smaller pieces" message;
- trim thread history to the last 20 messages (`_trim_history`, aligned to a HumanMessage boundary so tool calls are never orphaned) before every model call, and compact stored checkpoints past 120 messages down to 40, so persistent threads never overflow `num_ctx` or RAM;
- drive the circuit breaker: two graphs are compiled against the same checkpointer — local-primary (with per-call hosted fallback) and hosted-primary — and `pick_agent()` selects one per request from the breaker state, so an OPEN breaker skips a dead Ollama's timeouts entirely;
- never raise: LLM failures come back as friendly ❌ strings, and each failure/success updates the breaker (an `on_llm_error` callback attributes with_fallbacks rescues to the *local* model, so a dead Ollama still opens the breaker);
- journal every LLM-path tool call to `/state/tool_audit.jsonl` (`src/audit.py`) — name, args, result, duration — so file renames and bulk downloads are traceable after the fact;
- **scope tools per turn** (`src/graphs/scoping.py`, `llm.tool_scoping`): a deterministic keyword classifier picks the message's domain, and the turn runs on a graph bound to only that domain's ~10 tools instead of all 92 — the main lever that keeps very small models reliable. Ambiguous messages (ties, no signal) use the full toolset.

Stateless OpenAI-API requests use a throwaway per-request agent thread that is deleted afterwards (`forget_thread`), plus a *stable* router thread keyed on the conversation's first user message so yes/no confirmations survive across requests. The dashboard gives each browser tab its own `dashboard-<session>` thread (reset via `POST /api/dashboard/reset`).

### 2.5 Tool Layer (`src/tools/` + `src/providers/`)

**Design principle: task-oriented, not endpoint-oriented.** Each tool does one useful thing at the task level ("search for a show"), not the API level ("POST /api/v3/series").

Every tool follows the same pattern:

```python
@tool
async def search_tv(query: str) -> str:
    """Search for TV shows by name. Returns matching shows."""
    try:
        settings = get_settings()
        client = SonarrClient(
            base_url=settings.sonarr["url"],
            api_key=settings.sonarr["api_key"],
        )
        results = await client.search_series(query)
        # ... format results ...
        return formatted_string
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr."
    except Exception as e:
        return f"❌ Error: {e}"
```

**Rules:**
1. **Async** — all tools are `async def`
2. **Return strings** — never dicts; the LLM sees the return as text
3. **Error-safe** — never raise; return `❌` error messages
4. **Config via singleton** — `get_settings()` from `src/config.py`

#### Tool Registry (`src/tools/registry.py`)

All tools are imported and combined into `all_tools` (a flat list). Optional tools (SABnzbd, Download Station, YouTube) use try/except guards so missing dependencies don't break the agent:

```python
all_tools = (
    [search_tv, add_tv_show, ...]  # Core (always available)
    + _sabnzbd_tools               # Optional (try/except guarded)
    + _search_tools
    + _download_station_tools
    + _youtube_tools
)
```

### 2.6 Provider Layer (`src/providers/`)

Providers handle content types that need **more than an API call** — they wrap external tools (yt-dlp, audible-cli, bandcamp-downloader, internetarchive) and manage file-level operations.

| Provider | Tools | External Dependency | Acquisition Pattern |
|---|---|---|---|
| `youtube.py` | 6 | yt-dlp (subprocess) | Direct download + metadata + subscriptions |
| `bandcamp.py` | 2 | bandcamp-downloader (subprocess) | Direct download |
| `audible.py` | 5 | audible-cli (subprocess) | Authenticated extraction |
| `rom.py` | 4 | internetarchive (subprocess) | Direct download + DAT verify |
| `podcast.py` | 4 | httpx (RSS) | Subscriptions + episode downloads |
| `twitch.py` | 3 | streamlink (subprocess) | Live checks + background stream recording |
| `komga.py` | 3 | Komga API | Comic search/recent/scan |
| `calibre.py` | 2 | Calibre content server | Ebook search/recent |
| `lidarr.py` | 4 | Lidarr API | Artist search/add/list + music queue |
| `prowlarr.py` | 2 | Prowlarr API | Unified indexer search |
| `qbittorrent.py` | 4 | qBittorrent Web API | Torrent list/add/pause/resume |

### 2.7 Library Management (`src/library/`)

| Module | Functions | Purpose |
|---|---|---|
| `scanner.py` | `build_inventory`, `find_duplicates` | Filesystem inventory + duplicate detection (size + content fingerprint) |
| `naming.py` | `check_naming`, `fix_naming`, `undo_rename` | Enforce naming conventions with reversible renames + undo logs |

Naming conventions:
- **Movies:** `/Title (Year)/Title (Year).ext`
- **TV:** `/Show/Season ##/Show - s##e## - Title.ext`
- **Music:** `/Artist/Album/Track ## - Title.ext`

### 2.8 Scheduler (`src/scheduler.py`)

APScheduler's `AsyncIOScheduler` runs on the FastAPI server's event loop (started on app startup). Predefined jobs:

| Job | Schedule | Action |
|---|---|---|
| Health check | Every 30 min | `check_all_health()` across all services |
| Missing episodes | Every 12 hours | `search_missing_episodes()` + `search_missing_movies()` |
| Daily cleanup | 3:00 AM daily | Read-only daily report: runs `check_all_health()` and logs the result (deletes nothing) |
| Weekly scan | Sunday 2:00 AM | `emby_scan()` — full Emby library scan |

### 2.9 Interfaces (`src/interfaces/`)

#### OpenAI-Compatible API (`openai_api.py`)

FastAPI app exposing:
- `POST /v1/chat/completions` — standard OpenAI format, with SSE streaming support
- `GET /v1/models` — returns the "media-agent" model
- `GET /health` — unauthenticated health check (for Docker HEALTHCHECK)

**Bearer token auth** on `/v1/` endpoints. If `api_key` is empty in config, auth is disabled (development mode).

#### Dashboard (`dashboard.py`)

Self-contained HTML/JS dashboard (no external dependencies, no build step). Mounted onto the FastAPI app via `mount_dashboard(app)`. Shows:
- Service health cards (Sonarr, Radarr, Emby, SABnzbd)
- Active downloads
- Recent activity

Data endpoint: `GET /api/dashboard/data` returns JSON.

#### CLI (`cli.py`)

Interactive REPL using `rich` for formatted output. Three entry points: `cli_repl()`, `cli_one_shot(query)`, `cli_health()`.

---

## 3. Data Flow

### 3.1 Conversational Query Flow

```
User: "add Breaking Bad"
  │
  ▼
POST /v1/chat/completions (or dashboard chat / CLI)
  │
  ▼
try_route("add breaking bad", thread_id)      ← deterministic fast path
  │  matches the add intent:
  │  1. Sonarr + Radarr lookups run concurrently
  │  2. Numbered matches shown, stored as pending selection (15-min TTL)
  │     "Found 3 matches... Say 'yes' for #1, or 'add #2'."
  ▼
User: "yes"
  │
  ▼
try_route("yes", thread_id) → resolves pending → add_tv_show(81189)
  │  "✅ Added 'Breaking Bad'. Episode search started..."
  │  (exchange recorded into the agent thread via record_exchange)
  ▼
Response → user (no LLM call was needed)

Anything the router doesn't match ("why is everything downloading so
slowly?") falls through to run_agent()/stream_agent():
  │
  ▼
LangGraph ReAct loop (recursion-limited, history-trimmed):
  1. LLM sees message + tool list
  2. LLM calls tools until it can answer
  3. LLM generates final response
  │
  ▼
Response → user
```

### 3.2 Proactive Monitoring Flow

```
APScheduler tick (every 30 min)
  │
  ▼
check_all_health()
  │
  ├── Sonarr GET /api/v3/health ──→ format result
  ├── Radarr GET /api/v3/health ──→ format result
  ├── Emby ping ─────────────────→ format result
  └── SABnzbd GET /api?mode=status──→ format result
  │
  ▼
(Results logged; future: push notification via Telegram)
```

---

## 4. Network Topology

```
┌─── agent-mesh (Docker bridge network) ───────────────────┐
│                                                          │
│  media-agent ◄──── HTTP ─────► ollama (:11435)          │
│  (172.18.0.x)                  (172.18.0.2)              │
│                                                          │
└──────────────────────────────────────────────────────────┘
       │
       │ HTTP (LAN your local subnet)
       │
       ├──► your-nas (<YOUR_NAS_IP>)
       │    ├── Sonarr   :8989
       │    ├── Radarr   :8310
       │    ├── SABnzbd  :8080
       │    └── Download Station :5000
       │
       └──► your-media-host (<YOUR_MEDIA_IP>)
            └── Emby     :8096
```

**Key:** The media-agent reaches Ollama via the `agent-mesh` Docker network (internal DNS name `agent-lab-ollama-1`). It reaches media services via the host network (LAN IPs). The `host.docker.internal` mapping is NOT used — the agent-mesh network is the correct path.

---

## 5. Docker Configuration

### Container Profile

| Property | Value |
|---|---|
| Base image | `python:3.12-slim` |
| Non-root user | `media` (created in Dockerfile) |
| Port | `127.0.0.1:8088:8088` (localhost only) |
| Networks | `agent-mesh` (external) + `default` |
| Restart policy | `unless-stopped` |
| Health check | `curl -f http://localhost:8088/health` every 30s |
| GPU access | None (LLM runs in separate Ollama container) |

### Additional System Dependencies (in Dockerfile)

- `ffmpeg` — media processing (probe, transcode)
- `git` — required by some pip packages
- `curl` — health check
- `yt-dlp` — YouTube downloads
- `bandcamp-downloader` — Bandcamp downloads
- `internetarchive` — Internet Archive (ROMs)
- `audible-cli` — Audible book downloads
- `mutagen` — audio metadata
- `apscheduler` — proactive monitoring
- `python-telegram-bot` — Telegram interface (Phase 5, installed preemptively)

---

## 6. Configuration System

### Config Loading (`src/config.py`)

1. Reads `config/settings.yaml` (path from `MEDIA_AGENT_CONFIG` env or default)
2. Recursively substitutes `${VAR}` patterns with environment variables
3. Returns a `Settings` singleton via `get_settings()`

### Property Access

```python
settings = get_settings()
settings.server          # → {"host": "0.0.0.0", "port": 8088, "api_key": "..."}
settings.llm             # → {"ollama_url": "...", "ollama_model": "..."}
settings.sonarr          # → {"url": "http://...", "api_key": "..."}
settings.radarr          # → {"url": "http://...", "api_key": "..."}
settings.emby            # → {"url": "http://...", "api_key": "..."}
settings.sabnzbd         # → {"url": "http://...", "api_key": "..."}
```

**Note:** every service section — including `download_station`, `youtube`, `audible`, `roms`, `library`, and `scheduler` — is exposed as a `@property` on `Settings`.

---

## 7. Security Model

### Credentials

All API keys in **password manager **, injected via `.env` → Docker `env_file`. The `.env` file is:
- Never committed (`.gitignore`)
- Contains only variable names, never values in `.env.example`

### Network

- API server binds to `127.0.0.1:8088` — not exposed to LAN
- All outbound traffic goes to known LAN hosts or localhost
- No inbound ports beyond localhost

### Decision Boundaries

| Autonomous (no approval) | Escalate to user |
|---|---|
| Search for media, report matches | Adding/removing monitored items (configurable) |
| Health checks, status reports | Deleting files |
| Pause/resume downloads | Moving files between volumes |
| Trigger library scans | Anything involving >10GB |
| Retry failed imports once | Changing quality profiles |

---

## 8. Design Decisions (As-Built)

### Why `create_react_agent` instead of custom StateGraph

The ReAct loop handles the tool-call cycle automatically. For a tool-heavy agent with 92 tools, this is simpler and more reliable than hand-wiring a custom graph. The system prompt constrains behavior sufficiently.

### Why strings instead of structured returns

LangGraph passes tool return values to the LLM as text. Returning a dict means the LLM sees `{'key': 'value'}` as a string, which it must parse. Returning a pre-formatted string means the LLM can directly incorporate it into its response. This reduces token count and improves response quality.

### Why local-first LLM

Zero API cost, low latency (~35 tok/s on RTX 3060), and data privacy. Qwen 3.5 9B has reliable tool-calling, 128K context, and fits in 6.6 GB VRAM leaving headroom on the 12 GB card. The circuit breaker ensures graceful degradation if local fails.

### Why a single container

The agent, its tools, and its interfaces are tightly coupled. They share the same Python process and memory space. Splitting into microservices would add network overhead and operational complexity for no benefit at this scale.
