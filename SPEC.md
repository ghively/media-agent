# Media Agent — Design Specification (Historical)

> **⚠️ HISTORICAL DOCUMENT** — This is the original design spec from 2026-07-05.  
> It describes the planned architecture. The actual built system may differ.  
>  
> **For current architecture:** See [ARCHITECTURE.md](ARCHITECTURE.md)  
> **For AI development context:** See [CLAUDE.md](CLAUDE.md)  
> **For current tool list:** See [docs/tool-reference.md](docs/tool-reference.md)  
> **For the current README:** See [README.md](README.md)  
>  
> This document is preserved for design rationale and decision history.

**Version:** 1.0.0 (original design — see ARCHITECTURE.md for as-built)  
**Date:** 2026-07-05  
**Author:** Kevin (Hermes Agent) for Gene  
**Status:** MVP — Sonarr + Radarr + Emby (original scope; actual system is Phases 1–4)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Scope](#2-scope)
3. [Architecture](#3-architecture)
4. [Provider System](#4-provider-system)
5. [LLM Engine](#5-llm-engine)
6. [Tool Surface](#6-tool-surface)
7. [LangGraph Graphs](#7-langgraph-graphs)
8. [Library Management](#8-library-management)
9. [Interfaces](#9-interfaces)
10. [Container Specification](#10-container-specification)
11. [Security Model](#11-security-model)
11. [Decision Boundaries](#12-decision-boundaries)
12. [MVP Scope](#13-mvp-scope)
13. [Future Phases](#14-future-phases)
14. [Infrastructure Dependencies](#15-infrastructure-dependencies)
15. [Local LLM Model Selection](#16-local-llm-model-selection)

---

## 1. Executive Summary

Media Agent is a standalone, containerized agent that provides conversational
control, autonomous monitoring, intelligent acquisition, and library management
for a personal media ecosystem spanning TV, movies, music, YouTube, audiobooks,
Bandcamp, ROMs, and ad-hoc downloads from usenet and torrents.

The agent exposes three interfaces — a Telegram bot, an OpenAI-compatible API
(for mounting in Open WebUI), and a web dashboard — all powered by a single
LangGraph engine with a pluggable provider system.

**MVP delivers:** Sonarr (TV) + Radarr (movies) + Emby (library) with
conversational control via CLI and OpenAI-compatible API.

---

## 2. Scope

### Core Capabilities (four pillars)

| Pillar | Description |
|---|---|
| **Conversational Control** | Natural language interface: "add Breaking Bad", "what's downloading?", "why did this fail?" |
| **Autonomous Monitoring** | Scheduled health checks, queue monitoring, disk space, failed download detection, proactive alerting |
| **Intelligent Acquisition** | Search → add → track → notify across all content types with automatic transport routing |
| **Library Management** | First-run audit, smart sorting, deduplication, naming enforcement, metadata completeness, orphan detection |

### Content Types (by phase)

| Phase | Content | Provider | Acquisition Pattern |
|---|---|---|---|
| **MVP** | TV shows | TVProvider (Sonarr) | Indexer-based |
| **MVP** | Movies | MovieProvider (Radarr) | Indexer-based |
| **Phase 2** | Library management | Curation engine | Filesystem + API |
| **Phase 2** | Torrent + unified search | ManualProvider (Prowlarr) | Indexer search |
| **Phase 3** | YouTube (concerts/tutorials) | YouTubeProvider (yt-dlp) | Direct download |
| **Phase 3** | Audiobooks | AudibleProvider (audible-cli) | Authenticated extraction |
| **Phase 3** | Music (indexer) | MusicProvider (Lidarr) | Indexer-based |
| **Phase 3** | Music (purchases) | BandcampProvider (bandcamp-dl) | Direct download |
| **Phase 4** | ROMs | ROMProvider (internetarchive + RomM) | Direct download |
| **Phase 5** | Podcasts, Twitch, Comics, Ebooks | Plugin slots | Per-provider |

---

## 3. Architecture

### Design Principles

1. **Provider plugin system** — every content source implements the same
   `MediaProvider` protocol. Adding a source = writing a new provider class.
   Graphs, interfaces, and scheduler never change.

2. **Three-layer processing** — Intent (LLM) → Workflow (deterministic) →
   Exception (LLM). Most operations are fixed API sequences. The LLM earns its
   cost at intent parsing and exception handling, not rote API calls.

3. **Transport-invisible search** — users think in content, not protocols.
   `search_media("pink floyd")` queries all sources (torrent + usenet) and
   auto-routes downloads to the right client based on result protocol.

4. **Local-first LLM** — defaults to local Ollama (free, low latency), falls
   back to hosted API if local is unavailable or overloaded.

5. **Containerized and managed as code** — everything in one Docker container,
   deployed via docker-compose, infrastructure dependencies (Prowlarr,
   qBittorrent, Lidarr, RomM) deployed via homelab-ansible.

### System Diagram

```
┌──────────────────────────────────────────────────────────┐
│               media-agent (Docker Container)              │
│                                                           │
│   ┌──────────┐  ┌──────────────┐  ┌────────────────┐     │
│   │ Telegram  │  │ OpenAI API   │  │  APScheduler   │     │
│   │ Bot       │  │ /v1/chat/    │  │  (proactive)   │     │
│   │ (Phase 2) │  │ completions  │  │                │     │
│   └─────┬────┘  └──────┬───────┘  └───────┬────────┘     │
│         └──────────────┼──────────────────┘               │
│                        ▼                                  │
│   ┌────────────────────────────────────────────────────┐  │
│   │                 LangGraph Engine                    │  │
│   │   ┌─────────────┐  ┌──────────────┐                │  │
│   │   │Conversational│  │ Acquisition  │                │  │
│   │   │   Graph      │  │   Graph      │                │  │
│   │   └──────┬───────┘  └──────┬───────┘                │  │
│   │          └────────┬────────┘                        │  │
│   │                   ▼                                 │  │
│   │   ┌─────────────┐  ┌──────────────┐                │  │
│   │   │ Monitoring  │  │  Curation    │                │  │
│   │   │   Graph     │  │   Graph      │                │  │
│   │   └─────────────┘  └──────────────┘                │  │
│   └────────────────────────────────────────────────────┘  │
│                        ▼                                  │
│   ┌────────────────────────────────────────────────────┐  │
│   │              Provider Registry                      │  │
│   │   Routes content requests to the right provider     │  │
│   │   based on content type. Each provider implements   │  │
│   │   the MediaProvider protocol.                       │  │
│   └────────────────────┬───────────────────────────────┘  │
│                        ▼                                  │
│   ┌────────────────────────────────────────────────────┐  │
│   │               Tool Layer                            │  │
│   │  sonarr · radarr · sabnzbd · emby · prowlarr        │  │
│   │  qbittorrent · ytdlp · audible · bandcamp           │  │
│   │  archive · romm · library_health                    │  │
│   └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
               │ HTTP/REST
    ┌──────────┼──────────────────┐
    ▼          ▼                  ▼
 gh-storage  gh-storage       gh-media
 (Synology)  (Synology)       (Intel NUC)
 Sonarr:8989 SABnzbd:8080    Emby:8096
 Radarr:8310 DownloadStation
 Prowlarr:9696 (deploy)
 qBittorrent (deploy)
 Lidarr:8686 (deploy)
 RomM (deploy)
```

---

## 4. Provider System

### The Provider Protocol

Every content source implements this interface:

```python
from typing import Protocol
from pathlib import Path

class MediaProvider(Protocol):
    """Every content source implements this."""

    name: str                    # "tv", "movie", "youtube", "audible"
    content_types: list[str]     # ["episode", "movie", "concert", ...]
    acquisition_pattern: str     # "indexer" | "direct" | "authenticated"

    async def discover(self, query: str | None = None) -> list[MediaItem]:
        """
        Search for content by name/URL/channel.
        - indexer:        *arr API search (Sonarr/Radarr/Lidarr)
        - direct:         URL parse + metadata fetch (yt-dlp --dump-json)
        - authenticated:  library API listing (audible-cli library list)
        """
        ...

    async def acquire(self, item: MediaItem) -> AcquireResult:
        """
        Trigger download. Returns job ID for tracking.
        - indexer:        POST to *arr → triggers SABnzbd/torrent
        - direct:         run download tool (yt-dlp/bandcamp-downloader)
        - authenticated:  run download + decrypt (audible-cli download + decrypt)
        """
        ...

    async def process(self, item: MediaItem, downloaded_path: Path) -> Path:
        """
        Metadata, artwork, naming, NFO generation.
        Returns final path in library structure.
        All patterns converge here.
        """
        ...

    async def get_status(self, job_id: str) -> JobStatus:
        """
        Check download/processing progress.
        - indexer:        *arr queue API
        - direct:         poll download progress
        - authenticated:  poll audible-cli job
        """
        ...

    async def monitor(self) -> list[MediaItem]:
        """
        Check subscriptions/playlists for new content.
        Called by the scheduler for proactive acquisition.
        """
        ...
```

### Core Data Types

```python
from pydantic import BaseModel
from enum import Enum
from pathlib import Path
from datetime import datetime

class ContentType(str, Enum):
    TV_EPISODE = "tv_episode"
    MOVIE = "movie"
    MUSIC_ALBUM = "music_album"
    MUSIC_TRACK = "music_track"
    CONCERT = "concert"
    TUTORIAL = "tutorial"
    AUDIOBOOK = "audiobook"
    ROM = "rom"
    PODCAST = "podcast"
    UNKNOWN = "unknown"

class MediaItem(BaseModel):
    id: str                       # Provider-specific ID
    title: str
    content_type: ContentType
    provider: str                 # Which provider found this
    metadata: dict                # Provider-specific metadata
    download_url: str | None = None
    quality: str | None = None    # "1080p", "FLAC", etc.
    size_bytes: int | None = None

class AcquireResult(BaseModel):
    job_id: str                   # For status tracking
    status: str                   # "queued", "downloading", "processing", "complete", "failed"
    estimated_time: int | None = None  # seconds

class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: float               # 0.0 - 1.0
    speed: str | None = None      # "5.2 MB/s"
    eta: int | None = None        # seconds
    error: str | None = None

class LibraryIssue(BaseModel):
    severity: str                 # "info", "warning", "critical"
    category: str                 # "orphan", "duplicate", "naming", "metadata", "corrupt"
    file_path: Path
    description: str
    auto_fixable: bool = False
    fix_action: str | None = None
```

### Provider Registry — All Phases

```
INDEXER-BASED (discover via API → download via *arr)
├── TVProvider       → Sonarr:8989    [MVP]
├── MovieProvider    → Radarr:8310    [MVP]
└── MusicProvider    → Lidarr:8686    [Phase 3]

DIRECT-DOWNLOAD (run tool → process → place)
├── YouTubeProvider  → yt-dlp         [Phase 3]
├── BandcampProvider → bandcamp-dl    [Phase 3]
├── ROMProvider      → internetarchive [Phase 4]
└── ManualProvider   → Prowlarr search [Phase 2]

AUTHENTICATED-EXTRACTION (OAuth → download → decrypt)
└── AudibleProvider  → audible-cli    [Phase 3]

FUTURE PLUGIN SLOTS
├── PodcastProvider  → RSS/feed
├── TwitchProvider   → streamlink
├── ComicProvider    → Komga API
└── EbookProvider    → Calibre API
```

---

## 5. LLM Engine

### Local-First Router

```python
class MediaLLM:
    """Routes to local Ollama first, falls back to hosted API."""

    def __init__(self, config):
        self.primary = OllamaClient(
            url=config.ollama_url,      # http://agent-lab-ollama-1:11435
            model=config.ollama_model   # qwen3.5:9b
        )
        self.fallback = OpenAIClient(
            url=config.hosted_url,      # Z.AI / OpenRouter
            api_key=config.hosted_key,
            model=config.hosted_model
        )
        self._local_healthy = True
        self._health_check_interval = 30  # seconds

    async def call(self, messages, tools):
        if self._local_healthy:
            try:
                return await self.primary.call(
                    messages, tools, timeout=15
                )
            except (TimeoutError, ConnectionError):
                self._local_healthy = False
                # Background health check re-enables local
        return await self.fallback.call(messages, tools)
```

### LLM Model Selection

**Primary (local Ollama):** Qwen 3.5 9B (already resident on gh-nvidia)

| Criterion | Qwen 3.5 9B | Why it wins |
|---|---|---|
| Tool calling | Native, reliable | Supports OpenAI-compatible function calling format |
| Context window | 128K tokens | Handles full conversation history + tool results |
| VRAM | ~6.6 GB | Fits alongside other models on the 12GB RTX 3060 |
| Speed on RTX 3060 | ~35 tok/s | Acceptable for conversational latency (<3s response) |
| Multilingual | 29+ languages | Handles international media titles |
| License | Apache 2.0 | Fully open, no usage restrictions |
| Already installed | ✅ On gh-nvidia Ollama | No download needed — verified resident |

**Fallback (hosted API):** GLM-4.7 via Z.AI or OpenRouter free pool

**Why not larger models?** The RTX 3060 has 12GB VRAM with no MIG. Qwen 2.5 7B at Q4_K_M quantization uses ~5.5GB, leaving headroom for the OS and potential concurrent models. Larger models (14B+) would consume 10GB+ and risk OOM under load. For tool-calling accuracy, 7B is sufficient — the tool surface is well-described and the graph constrains the LLM's decision space.

**Alternative considered:** Llama 3.1 8B — good tool calling but less reliable function argument formatting than Qwen 2.5. Mistral 7B — smaller context window (32K vs 128K).

---

## 6. Tool Surface

### Design Principle: Task-Oriented, Not Endpoint-Oriented

Tools operate at task level ("add a show") not API level ("POST /api/v3/series").
The LLM reasons about tasks, not HTTP endpoints.

### MVP Tools (Sonarr + Radarr + Emby)

#### TV / Sonarr (8 tools)

| Tool | Purpose |
|---|---|
| `search_tv(query)` | Search for a TV show by name → returns matches with tvdbId |
| `add_tv_show(tvdb_id, quality_profile_id=1, monitored=true)` | Add show to Sonarr library |
| `list_tv_shows()` | List all monitored shows + status |
| `get_tv_queue()` | Current download queue + status |
| `get_tv_history()` | Recent grab/import activity |
| `search_missing_episodes()` | Trigger search for wanted/missing episodes |
| `get_tv_calendar(days=7)` | Upcoming/airing episodes |
| `get_tv_health()` | Sonarr health checks (indexers, disk, etc.) |

#### Movies / Radarr (7 tools)

| Tool | Purpose |
|---|---|
| `search_movie(query)` | Search for a movie by name → TMDb matches |
| `add_movie(tmdb_id, quality_profile_id=1, monitored=true)` | Add movie to Radarr library |
| `list_movies()` | List all monitored movies + status |
| `get_movie_queue()` | Current download queue |
| `get_movie_history()` | Recent activity |
| `search_missing_movies()` | Trigger search for wanted movies |
| `get_movie_health()` | Radarr health checks |

#### Library / Emby (5 tools)

| Tool | Purpose |
|---|--- |
| `emby_search(query)` | Search across all Emby libraries |
| `emby_recent(limit=20)` | Recently added items |
| `emby_libraries()` | List all libraries + item counts |
| `emby_scan(library_name=None)` | Trigger library refresh |
| `emby_get_item(item_id)` | Get details of a specific media item |

#### Health (3 tools)

| Tool | Purpose |
|---|---|
| `check_all_health()` | One-shot health check across all services |
| `check_disk_space()` | NAS volume usage |
| `check_queue_status()` | Unified view of all active downloads |

**MVP total: 23 tools.**

### Full Tool Surface (All Phases)

#### Unified Search & Download (Phase 2 — 5 tools)

| Tool | Purpose |
|---|---|
| `search_media(query, content_type=None, min_quality=None, max_size=None)` | Search ALL sources (torrent + usenet) in one call. Returns unified ranked results. |
| `download_media(result_id)` | Download a search result. Auto-routes to qBittorrent or SABnzbd based on protocol. |
| `get_download_status(job_id)` | Check any download regardless of client. |
| `get_all_downloads()` | All active downloads across both clients, unified view. |
| `cancel_download(job_id)` | Cancel + remove from whichever client has it. |

#### Admin (3 tools)

| Tool | Purpose |
|---|---|
| `pause_downloads()` | Pause all download clients |
| `resume_downloads()` | Resume all download clients |
| `trigger_library_scan()` | Trigger Emby library scan |

#### YouTube (Phase 3 — 4 tools)

| Tool | Purpose |
|---|---|
| `youtube_download(url, content_type="concert")` | Download a video with full metadata + artwork |
| `youtube_add_subscription(url, content_type, config)` | Monitor a channel/playlist |
| `youtube_list_subscriptions()` | List active subscriptions |
| `youtube_check_new()` | Check subscriptions for new content |

#### Bandcamp (Phase 3 — 2 tools)

| Tool | Purpose |
|---|---|
| `bandcamp_download(url)` | Download a Bandcamp album/track |
| `bandcamp_download_collection()` | Download all purchased albums |

#### Audible (Phase 3 — 4 tools)

| Token | Purpose |
|---|---|
| `audible_list_library()` | List Audible library |
| `audible_download(asin)` | Download + decrypt a specific book |
| `audible_download_new()` | Download books added since last sync |
| `audible_check_auth()` | Check auth status, prompt re-auth if needed |

#### ROMs (Phase 4 — 6 tools)

| Tool | Purpose |
|---|---|
| `rom_search_archive(query)` | Search Internet Archive No-Intro collections |
| `rom_download(item_id)` | Download ROM or ROM set |
| `rom_verify_dat(platform)` | Verify ROM checksums against DAT files |
| `rom_get_collection()` | List current ROM collection by platform |
| `romm_scan()` | Trigger RomM library scan |
| `romm_search(query)` | Search RomM library |

#### Library Management (Phase 2 — 8 tools)

| Tool | Purpose |
|---|---|
| `library_audit()` | Full first-run audit: inventory, cross-reference, quality |
| `library_sort_dir(path)` | Smart-sort an unsorted directory |
| `library_find_dups()` | Find duplicate items across libraries |
| `library_find_orphans()` | Find files not tracked by any manager |
| `library_check_naming()` | Check naming convention compliance |
| ` management()Check metadata completeness (missing art/NFO) |
| `library_apply_fixes(issue_ids)` | Apply auto-fixable issues |
| `library_quality_review()` | Review low-quality items for upgrades |

**Full tool surface: ~55 tools across all phases.**

---

## 7. LangGraph Graphs

### Overview

Four LangGraph state graphs power the agent. Each has a different trigger and
termination condition.

| Graph | Trigger | Termination |
|---|---|--- |
| Conversational | User message | Message answered |
| Acquisition | "Add X" intent or scheduled search | Item imported or failed |
| Monitoring | APScheduler tick | All checks processed |
| Curation | Scheduled or on-demand | All issues classified |

### Conversational Graph (MVP)

```
START → parse_intent → [route]
  ├── "status" query → call tools (health/queue/calendar) → format_response → END
  ├── "search" query → call search tools → format_response → END
  ├── "add" request → confirm with user → call add tool → format_response → END
  ├── "help" → return help text → END
  └── fallback → general LLM response → END
```

State:

```python
class ConversationState(TypedDict):
    messages: list[BaseMessage]
    intent: str | None          # "status", "search", "add", "help", "general"
    tool_results: list[dict]
    response: str | None
```

### Acquisition Graph (Phase 2)

```
START → search → found?
  ├── YES → add_monitored → trigger_grab → monitor_loop → imported?
  │    ├── YES → process → notify → END
  │    └── NO → retry? (max 3) → YES → re-search / NO → notify_failure → END
  └── NO → fuzzy_match → ask_user → END
```

State:

```python
class AcquisitionState(TypedDict):
    query: str
    content_type: ContentType
    search_results: list[MediaItem]
    selected_item: MediaItem | None
    job_id: str | None
    status: str
    retries: int
    final_path: Path | None
    error: str | None
```

### Monitoring Graph (Phase 2)

```
START → check_all_services → collect_issues → triage
  ├── silent → END
  ├── alert → send_notification → END
  └── auto_fix → fix_issue → log_fix → END
```

### Curation Graph (Phase 2)

```
START → scan_filesystem → cross_reference_libraries → classify_issues
  ├── auto_fix → fix + log → END
  ├── report → add to digest → END
  └── escalate → notify user → END
```

---

## 8. Library Management

### Three Operational Modes

#### Mode 1: First-Run Audit (one-time)

When the agent first deploys, it inventories everything on disk:

1. **Inventory** — Walk entire media tree, query Emby/Sonarr/Radarr APIs
2. **Cross-reference** — Every file: tracked by *arr? In Emby? Orphaned? Duplicate?
3. **Quality assessment** — Flag low-quality, oversized, upgrade candidates
4. **Report** — Structured audit with counts, issues, recommended actions

#### Mode 2: Smart Sort (on-demand)

The engine can sort any directory of unsorted files through 5 stages:

1. **Identify** — Extension analysis, filename pattern matching, embedded metadata probe, sidecar file check
2. **Enrich** — Get proper metadata from the right source (*arr, TMDb, MusicBrainz, IGDB)
3. **Normalize** — Rename to library convention (reversible via symlink)
4. **Place** — Route to correct library directory, dedup check, disk space check
5. **Index** — Generate NFO, trigger Emby scan, link in manager DB

#### Mode 3: Continuous Maintenance (scheduled)

| Job | Schedule | Action |
|---|---|---|
| Stale download cleanup | Daily 3am | Remove .tmp, .part, incomplete |
| Missing episode search | Every 12h | Sonarr wanted/missing |
| Emby sync check | Daily | Compare Emby DB to filesystem |
| Naming enforcement | Weekly | Auto-fix naming violations |
| Deduplication scan | Weekly | Find + report duplicates |
| Metadata completeness | Weekly | Fix missing posters/NFO |
| ROM integrity verify | Monthly | Checksum verify against DATs |
| Disk health + space | Every 30min | Volume usage, Synology disk/pool health |
| Orphan detection | Weekly | Report untracked files |
| Quality review | Monthly | Flag upgrade candidates |

### Issue Classification

Every detected issue is classified:

| Classification | Criteria | Action |
|---|---|---|
| **AUTO-FIX** | Reversible (rename, move, regenerate), no data loss, high confidence | Agent fixes it, logs the change, appears in digest |
| **REPORT** | Informational (disk space, stats), no action needed yet | Collected into daily/weekly digest |
| **ESCALATE** | Deletion, ambiguous, data loss risk, requires preference | Agent asks via Telegram with options |
| **IGNORE** | Marked as expected by user, already pending | Logged silently |

---

## 9. Interfaces

### Security: API Authentication

The OpenAI-compatible API and dashboard require a bearer token:

```yaml
# config/settings.yaml
server:
  api_key: "${MEDIA_AGENT_API_KEY}"  # Generated token, required for all endpoints
```

All API requests must include `Authorization: Bearer <token>`. The health check
endpoint `/health` is exempt (for Docker HEALTHCHECK). Open WebUI is configured
with this API key as the connection password.

### MVP Interfaces

#### CLI Interface

```bash
# Interactive REPL
python -m src.main --interactive

# One-shot query
python -m src.main --query "what's downloading?"

# Health check
python -m src.main --health
```

#### OpenAI-Compatible API (for Open WebUI)

```python
# POST /v1/chat/completions
# GET /v1/models
```

The agent appears as a model named "media-agent" in Open WebUI. Users select it
from the dropdown and chat naturally. Tool calls are invisible — the user sees
only the natural language response. Streaming via SSE for token-by-token display.

### Phase 2 Interfaces

#### Telegram Bot

Long-polling bot that handles:
- Conversational queries ("add this show", "what's downloading?")
- Proactive push notifications (downloads complete, health alerts, escalations)
- Inline keyboard buttons for decision points ("which duplicate to keep?")

**Note:** Requires a dedicated bot token from Gregory's manager bot. The existing
Hermes bot token (`hermes_damnitkevin_bot`) is NOT shared.

#### Web Dashboard (FastAPI)

- `/dashboard` — Web UI with library stats, active downloads, recent activity
- `/api` — REST API for programmatic access
- `/ws` — WebSocket for live status updates
- `/health` — Health check endpoint

---

## 10. Container Specification

### Directory Structure

```
media-agent/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
├── config/
│   ├── settings.yaml.example     # Template — copy to settings.yaml and fill in
│   ├── subscriptions.yaml.example
│   └── prompts/
│       ├── conversational.txt    # System prompt for chat graph
│       ├── curation.txt          # System prompt for curation reasoning
│       └── monitoring.txt        # System prompt for health-check triage
├── src/
│   ├── __init__.py
│   ├── main.py                   # Entry point: starts all loops
│   ├── config.py                 # Pydantic settings loader
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py             # Local-first LLM router
│   │   └── health.py             # Background Ollama health check
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── registry.py           # Provider registration + routing
│   │   └── types.py              # MediaItem, JobStatus, LibraryIssue types
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py               # MediaProvider protocol
│   │   ├── tv.py                 # Sonarr provider [MVP]
│   │   └── movie.py              # Radarr provider [MVP]
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py           # LangGraph tool definitions
│   │   ├── sonarr.py             # Sonarr API client [MVP]
│   │   ├── radarr.py             # Radarr API client [MVP]
│   │   └── emby.py               # Emby API client [MVP]
│   ├── graphs/
│   │   ├── __inft__.py
│   │   └── conversational.py     # Conversational graph [MVP]
│   ├── interfaces/
│   │   ├── __init__.py
│   │   ├── cli.py                # CLI interface [MVPI]
│   │   └── openai_api.py         # OpenAI-compatible API [MVP]
│   └── scheduler.py              # APScheduler [Phase 2]
│   └── library/                  # [Phase 2]
│       ├── scanner.py
│       ├── integrity.py
│   │   ├── deduplicator.py
│   │   ├── naming.py
│   │   ├── metadata_check.py
│   │   ├── orphans.py
│   │   └── disk_health.py
└── tests/
    ├── conftest.py               # Fixtures with mock API responses
    ├── test_tools/
    │   ├── test_sonarr.py
    │   ├── test_radarr.py
    │   └── test_emby.py
    ├── test_providers/
    │   ├── test_tv.py
│   └── test_movie.py
    └── test_graphs/
        └── test_conversational.py
```

### Dockerfile

```dockerfile
FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r media && useradd -r -g media -d /app media

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY --chown=media:media src/ /app/src/
COPY --chown=media:media config/ /app/config/

WORKDIR /app

# Run as non-root
USER media

# Expose API port
EXPOSE 8088

# Health check (health endpoint is exempt from auth)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8088/health || exit 1

CMD ["python", "-m", "src.main"]
```

### docker-compose.yml

```yaml
version: "3.9"

services:
  media-agent:
    build: .
    container_name: media-agent
    restart: unless-stopped
    ports:
      - "127.0.0.1:8088:8088"
    env_file:
      - .env
    volumes:
      - ./config:/app/config
      - agent-state:/state
    networks:
      - agent-mesh           # Join existing agent-lab network for Ollama access
      - default
    extra_hosts:
      - "host.docker.internal:host-gateway"

networks:
  agent-mesh:
    external: true            # The agent-lab's existing network
    name: agent-lab_agent-mesh

volumes:
  agent-state:
```

### requirements.txt (MVP)

```
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-ollama>=0.2.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
httpx>=0.27.0
APScheduler>=3.10.0
sse-starlette>=2.0.0
rich>=13.0.0          # CLI formatting
```

### settings.yaml Structure

```yaml
# config/settings.yaml.example
server:
  host: "0.0.0.0"
  port: 8088

llm:
  # CRITICAL: Use the agent-mesh Docker network address, not host.docker.internal
  # The agent-lab Ollama container has OLLAMA_HOST=0.0.0.0:11435 (internal port 11435)
  # The media-agent container joins the agent-mesh network to reach it
  ollama_url: "http://agent-lab-ollama-1:11435"
  ollama_model: "qwen3.5:9b"
  hosted_url: ""           # Optional fallback (Z.AI, OpenRouter)
  hosted_key: ""           # Optional
  hosted_model: ""         # Optional
  temperature: 0
  timeout: 15

services:
  sonarr:
    url: "http://192.168.0.133:8989"
    api_key: "${SONARR_API_KEY}"
  radarr:
    url: "http://192.168.0.133:8310"
    api_key: "${RADARR_API_KEY}"
  emby:
    url: "http://192.168.0.144:8096"
    api_key: "${EMBY_API_KEY}"
  sabnzbd:                  # [Phase 2]
    url: "http://192.168.0.133:8080"
    api_key: "${SABNZBD_API_KEY}"

scheduler:
  enabled: false            # [Phase 2]
  jobs: []

library:
  media_root: "/media"      # NFS mount point [Phase 2]
  naming_conventions:
    movies: "/movies/{title} ({year})/{title} ({year}).{ext}"
    tv: "/tv/{show}/Season {season:02d}/{show} - s{season:02d}e{episode:02d} - {title}.{ext}"
    music: "/music/{artist}/{album}/{track:02d} - {title}.{ext}"
    concerts: "/music/concerts/{artist}/{title} ({year})/{title} ({year}).{ext}"
    audiobooks: "/audiobooks/{author}/{title}/{title}.m4b"
    roms: "/roms/{platform}/{name}.{ext}"
```

---

## 11. Security Model

### Credentials

All API keys are stored in 1Password vault "Gregory". At deploy time they are
written to a `.env` file that is:
- Never committed to git (`.gitignore`)
- chmod 600
- Mounted into the container via `env_file`

The container reads credentials from environment variables. No secrets in code
or config files.

### Network Posture

- API server binds to `127.0.0.1:8088` only — not exposed to LAN by default
- All outbound connections go to known hosts on LAN (gh-storage, gh-media) or
  localhost (Ollama)
- No inbound ports exposed beyond localhost

### Decision Boundaries

| Autonomous (no approval) | Escalate to user |
|---|---|
| Search for media, report matches | Actually adding/removing monitored items |
| Health checks, status reports | Deleting files (orphans, duplicates) |
| Pause/resume downloads | Moving files between volumes |
| Trigger library scans | Changing quality profiles |
| Retry failed imports once | Changing indexer config |
| Disk space alerts | Anything involving >10GB writes |

Rule: **read-only and reversible = autonomous. Anything that modifies the
library or costs storage = ask first.**

---

## 12. MVP Scope

### What the MVP Delivers

1. **Sonarr API client** — full TV show management (search, add, list, queue, history, health)
2. **Radarr API client** — full movie management (search, add, list, queue, history, health)
3. **Emby API client** — library queries (search, recent, libraries, scan, item details)
4. **Conversational graph** — LangGraph state machine that parses intent and routes to the right tools
5. **CLI interface** — interactive REPL + one-shot queries
6. **OpenAI-compatible API** — mountable in Open WebUI as "media-agent"
7. **Local LLM** — Qwen 2.5 7B via Ollama with hosted fallback
8. **Docker container** — self-contained, reproducible deployment

### MVP User Stories

```
As a user, I can:
  ✓ Search for a TV show: "search for Breaking Bad"
  ✓ Add a TV show: "add Breaking Bad"
  ✓ List my shows: "what shows do I have?"
  ✓ Check download queue: "what's downloading?"
  ✓ Check health: "is everything healthy?"
  ✓ Search for a movie: "search for The Matrix"
  ✓ Add a movie: "add The Matrix"
  ✓ List my movies: "how many movies do I have?"
  ✓ Browse Emby: "what was recently added?"
  ✓ Search Emby: "do I have The Matrix?"
  ✓ Trigger scan: "scan the movie library"
  ✓ Get upcoming episodes: "what's airing this week?"
  ✓ Chat via Open WebUI as "media-agent" model
  ✓ Chat via CLI with `python -m src.main --interactive`
```

### MVP Definition of Done

- [ ] All API clients tested against live services
- [ ] Conversational graph routes intents correctly
- [ ] CLI accepts queries and returns formatted responses
- [ ] OpenAI-compatible API responds to /v1/chat/completions
- [ ] OpenAI-compatible API streams responses via SSE
- [ ] Container builds and runs
- [ ] Health check endpoint responds
- [ ] LLM connects to local Ollama
- [ ] Local-first fallback works (kill Ollama → uses hosted)
- [ ] Settings loaded from settings.yaml with env var substitution
- [ ] `.env.example` documents all required variables

---

## 13. Future Phases

### Phase 2: Library Management + Unified Search + Scheduler + Telegram

- Deploy Prowlarr + qBittorrent on NAS via homelab-ansible
- Deploy NFS export on NAS for container media access
- Library audit, smart sort, continuous maintenance
- Unified search across all indexers
- Download client routing (SABnzbd vs qBittorrent)
- APScheduler for proactive monitoring
- Telegram bot (requires dedicated bot token)
- Web dashboard (FastAPI + HTML/JS)

### Phase 3: YouTube + Audible + Music + Bandcamp

- Deploy Lidarr on NAS
- yt-dlp provider (concerts, tutorials, subscriptions)
- Audible provider (OAuth, DRM removal, incremental sync)
- Bandcamp provider (purchases, one-off downloads)
- Bundle yt-dlp, audible-cli, bandcamp-dl, mutagen into container

### Phase 4: ROMs

- Deploy RomM on NAS
- ROM provider (Internet Archive No-Intro/Redump downloads)
- DAT file verification
- 1G1R filtering
- BIOS file management

### Phase 4.5: Configuration Migration

- Migrate Sonarr/Radarr from native SPK to Docker containers on NAS
- Consolidate all Servarr services under one Docker Compose project
- Managed via homelab-ansible

### Phase 5: Plugin Expansion

- Podcasts (RSS), Twitch (streamlink), Comics (Komga), Ebooks (Calibre)
- New providers implement the protocol, register, done

---

## 14. Infrastructure Dependencies

### Currently Running (confirmed live)

| Service | Host | Address | Status |
|---|---|---|---|
| Sonarr v4 | gh-storage (Synology) | 192.168.0.133:8989 | ✅ Native SPK |
| Radarr | gh-storage | 192.168.0.133:8310 | ✅ Native SPK |
| SABnzbd | gh-storage | 192.168.0.133:8080 | ✅ |
| Download Station | gh-storage | 192.168.0.133:5000 | ✅ |
| Emby | gh-media (Intel NUC) | 192.168.0.144:8096 | ✅ |
| Ollama | gh-nvidia | localhost:11435 (containerized) | ✅ |

### To Deploy (via homelab-ansible)

| Service | Host | Method | Phase |
|---|---|---|---|
| Prowlarr | gh-storage | Docker | Phase 2 |
| qBittorrent | gh-storage | Docker | Phase 2 |
| Lidarr | gh-storage | Docker | Phase 3 |
| RomM | gh-storage | Docker | Phase 4 |
| NFS export | gh-storage | DSM config | Phase 2 |

### Storage Layout (on Synology NAS)

```
/volume1/media/
├── movies/                        (Radarr managed)
├── tv/                            (Sonarr managed)
├── music/
│   ├── lidarr/                    (Lidarr managed)
│   ├── bandcamp/                  (Bandcamp provider)
│   └── concerts/                  (YouTube content_type=concert)
├── audiobooks/                    (Audible provider)
├── roms/
│   ├── nes/ snes/ genesis/ n64/ gba/ psx/ arcade/
│   └── _dat/                      (No-Intro DAT files)
├── tutorials/                     (YouTube content_type=tutorial)
├── podcasts/                      (future)
└── downloads/                     (SABnzbd/torrent staging)
```

---

## 15. Local LLM Model Selection

**Decision: Qwen 3.5 9B (already resident on gh-nvidia Ollama)**

| Criterion | Value |
|---|---|
| Model | Qwen 3.5 9B |
| Size | 6.6 GB |
| VRAM usage | ~6.6 GB loaded |
| Context window | 128K tokens |
| Tool calling | Native OpenAI-compatible function calling |
| Speed on RTX 3060 | ~35 tok/s |
| License | Apache 2.0 |
| Status | Already installed and verified on gh-nvidia |

### Why this model for this agent

1. **Tool calling is the core capability.** Qwen 3.5 has reliable native
   function-calling support. The agent's entire value proposition depends on
   correct tool selection and argument formatting.

2. **128K context window.** Conversation history + tool results + system prompt
   can easily reach 10K+ tokens. 128K leaves massive headroom.

3. **Fits the VRAM budget.** The RTX 3060 has 12GB. Qwen 3.5 9B uses ~6.6GB,
   leaving 5.4GB headroom. The Ollama container shares VRAM with potential
   concurrent models.

4. **Already installed.** No download needed — the model is verified resident
   in the Ollama container on gh-nvidia.

5. **Multilingual.** Handles international media titles (anime, foreign films,
   K-pop, etc.) without romanization issues.

### Alternatives Considered

| Model | Size | VRAM | Tool calling | Why not |
|---|---|---|---|---|
| Qwen 2.5 7B | 7B | ~5.5GB | Good | Not installed — would need pull. Qwen 3.5 is newer/better |
| Llama 3.1 8B | 8B | ~6.5GB | Good | Not installed. Less reliable function arg formatting |
| Mistral 7B | 7B | ~5.5GB | OK | 32K context (vs 128K), weaker tool calling |
| Gemma 4 12B | 12B | ~7.6GB | Decent | Available but heavier VRAM, weaker tool calling than Qwen |
| Qwen 3.5 4B | 4B | ~3.4GB | Decent | Available but less reliable for 23+ tools |

### Ollama Integration Notes

**CRITICAL:** The Ollama container in agent-lab has a port mismatch:
- Container env: `OLLAMA_HOST=0.0.0.0:11435`
- Docker port mapping: `container:11434 → host:11435`

The media-agent container MUST join the `agent-mesh` Docker network and reach
Ollama at `http://172.18.0.2:11435` (container IP) or use the internal Docker
DNS name `http://agent-lab-ollama-1:11435`. Do NOT use `host.docker.internal:11435`
as the port mapping is broken.

The recommended approach is to add the media-agent to the agent-lab's
`agent-mesh` network in the docker-compose, using the internal network address.

---

## Appendix A: Credential Reference

All credentials in 1Password vault "Gregory". Variable names only — never values.

| Variable | 1Password Item | Used in Phase |
|---|---|---|
| `SONARR_API_KEY` | "Sonarr API Key (GH-Storage)" | MVP |
| `RADARR_API_KEY` | "Radarr API Key (GH-Storage)" | MVP |
| `EMBY_API_KEY` | "Emby API" | MVP |
| `SABNZBD_API_KEY` | "SABnzbd API Key" | Phase 2 |
| `TELEGRAM_BOT_TOKEN` | TBD (create via Gregory manager bot) | Phase 2 |
| `PROWLARR_API_KEY` | TBD (after Prowlarr deploy) | Phase 2 |
| `QBITTORRENT_USER/PASS` | TBD | Phase 2 |
| `AUDIBLE_AUTH` | File (audible-cli auth.json) | Phase 3 |
| `IPTORRENTS_SESSION` | Prowlarr-managed | Phase 2 |

---

## Appendix B: Build Sequence

### MVP Build Order

1. Project scaffold (pyproject.toml, directory structure, .gitignore)
2. Type definitions (src/engine/types.py)
3. API clients (sonarr.py, radarr.py, emby.py) — testable independently
4. TV provider (wrapping Sonarr client)
5. Movie provider (wrapping Radarr client)
6. Tool registry (LangGraph tool definitions)
7. Conversational graph (intent → route → tools → respond)
8. LLM client (local-first router)
9. CLI interface
10. OpenAI-compatible API
11. Dockerfile + docker-compose.yml
12. Integration test against live services
13. Deploy container

---

*This specification is a living document. Each phase updates it with what was
built, what was learned, and what changed from the original design.*
