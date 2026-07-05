# Codex Build Instructions for media-agent MVP

## Context

You are building the MVP for a media management agent. The full design spec is in SPEC.md.
Read it carefully before starting. This file gives you the specific implementation guidance
to avoid ambiguity.

## What to Build (MVP Only)

Build ONLY the following — nothing from Phase 2+:

1. **Project scaffold** — pyproject.toml, requirements.txt, .gitignore (already exists), directory structure
2. **Type definitions** (`src/engine/types.py`) — Pydantic models from the spec
3. **API clients**:
   - `src/tools/sonarr.py` — Sonarr v3 API client (8 tool functions)
   - `src/tools/radarr.py` — Radarr v3 API client (7 tool functions)
   - `src/tools/emby.py` — Emby API client (5 tool functions)
4. **Health check tools** (`src/tools/health.py`) — check_all_health, check_disk_space, check_queue_status
5. **Provider wrappers** (`src/providers/tv.py`, `src/providers/movie.py`) — thin wrappers around API clients
6. **LLM client** (`src/llm/client.py`) — local-first router (Ollama → hosted fallback)
7. **Conversational graph** (`src/graphs/conversational.py`) — LangGraph state machine
8. **CLI interface** (`src/interfaces/cli.py`) — interactive REPL + one-shot queries
9. **OpenAI-compatible API** (`src/interfaces/openai_api.py`) — FastAPI with SSE streaming
10. **Configuration** (`src/config.py`) — Pydantic settings with env var loading
11. **Dockerfile** and **docker-compose.yml** per spec
12. **Tests** — at least basic tests for each API client and the graph

## Key Implementation Details

### Ollama Connection (CRITICAL)

The Ollama container runs in the `agent-lab_agent-mesh` Docker network. The
media-agent container joins this network. Reach Ollama at:

```
http://agent-lab-ollama-1:11435
```

Use model `qwen3.5:9b`. Do NOT use `host.docker.internal` or `localhost:11434`.

Use `langchain-ollama` (`ChatOllama`) for the LLM client:
```python
from langchain_ollama import ChatOllama
llm = ChatOllama(
    base_url="http://agent-lab-ollama-1:11435",
    model="qwen3.5:9b",
    temperature=0,
)
```

### Servarr API Pattern (Sonarr/Radarr)

Both use identical API patterns:
- Base URL from config
- Auth: `?apikey=<key>` query parameter on every request
- All endpoints under `/api/v3/`
- Use `httpx.AsyncClient` for async HTTP

Key endpoints (Sonarr examples — Radarr is identical, swap movie/series):

```
GET  /api/v3/series?apikey=             → list all series
GET  /api/v3/series/lookup?term=X&apikey=  → search for a show
POST /api/v3/series?apikey=             → add a show (body: {tmdbId, title, qualityProfileId, rootFolderPath, monitored})
GET  /api/v3/queue?apikey=              → download queue
GET  /api/v3/history?apikey=            → recent activity
POST /api/v3/command?apikey=            → trigger search (body: {name: "SeriesSearch", seriesId: N})
GET  /api/v3/calendar?apikey=           → upcoming episodes
GET  /api/v3/health?apikey=             → health checks
```

For Radarr, swap `series` → `movie`, `SeriesSearch` → `MoviesSearch`, `seriesId` → `movieIds`.

### Emby API

Emby uses header-based auth:
```
GET /emby/Items?api_key=<key>
Headers: X-Emby-Token: <key>
```

Key endpoints:
```
GET /emby/Items?SearchTerm=X&Recursive=true&api_key=    → search
GET /emby/Items/Latest?api_key=                          → recent items
GET /emby/Library/VirtualFolders?api_key=                → list libraries
POST /emby/Library/Refresh?api_key=                      → trigger scan
GET /emby/Users/<userId>/Items?api_key=                   → user library
GET /emby/Items/<id>?api_key=                             → item details
```

### LangGraph Conversational Graph

Use `StateGraph` from langgraph with a typed state dict. The graph should:

1. Accept user message as input
2. Use the LLM with `bind_tools()` to determine intent
3. Route to: status_query, search_query, add_request, help, general
4. Execute tools if needed
5. Format and return response

Use `create_react_agent` from `langgraph.prebuilt` if simpler — it handles the
tool-call loop automatically. The system prompt should describe all available tools.

### OpenAI-Compatible API

Implement these endpoints in FastAPI:

```
GET  /v1/models                    → {"data": [{"id": "media-agent"}]}
POST /v1/chat/completions          → OpenAI-compatible response with streaming
GET  /health                       → health check (no auth required)
```

For streaming, use `sse-starlette` and return `text/event-stream` with `data: {...}\n\n` format.
Each chunk should be an OpenAI-compatible `ChatCompletionChunk`.

Require `Authorization: Bearer <token>` on `/v1/` endpoints. Token from `MEDIA_AGENT_API_KEY` env var.

### Configuration

Use `pydantic-settings` with `SettingsConfigDict(env_file=".env", env_nested_delimiter="__")`.

The settings.yaml is loaded manually (not by pydantic) — read it, substitute `${ENV_VAR}` patterns,
then pass to Pydantic models.

### CLI Interface

```bash
# Interactive REPL
python -m src.main --interactive

# One-shot query  
python -m src.main --query "what's downloading?"

# Health check
python -m src.main --health
```

Use `rich` for formatted terminal output.

## DO NOT Build

- Telegram bot (Phase 2)
- Library management / curation (Phase 2)
- Scheduler / monitoring (Phase 2)
- YouTube/Audible/Bandcamp/ROM providers (Phase 3+)
- Web dashboard (Phase 2)
- Acquisition graph with state machine (Phase 2)
- SABnzbd/qBittorrent/Prowlarr integration (Phase 2)

## Environment Variables

```
SONARR_API_KEY=<from .env>
RADARR_API_KEY=<from .env>
EMBY_API_KEY=<from .env>
SONARR_URL=http://192.168.0.133:8989
RADARR_URL=http://192.168.0.133:8310
EMBY_URL=http://192.168.0.144:8096
MEDIA_AGENT_API_KEY=<generated token for API auth>
OLLAMA_URL=http://agent-lab-ollama-1:11435
OLLAMA_MODEL=qwen3.5:9b
```

## Quality Bar

- Every API client method has error handling (timeouts, connection errors, bad status codes)
- The conversational graph handles the case where the LLM picks a wrong/nonexistent tool
- The OpenAI API returns proper error responses (400 for bad input, 401 for no auth, 500 for errors)
- Tests use mocked HTTP responses (don't hit real APIs in CI)
- Type hints everywhere — use Pydantic models for all data structures
- Docstrings on all public functions

## File Creation Order

1. pyproject.toml, requirements.txt
2. src/__init__.py, src/config.py
3. src/engine/types.py
4. src/tools/sonarr.py, src/tools/radarr.py, src/tools/emby.py, src/tools/health.py
5. src/tools/registry.py (LangGraph @tool definitions wrapping the API clients)
6. src/providers/base.py, src/providers/tv.py, src/providers/movie.py
7. src/llm/client.py
8. src/graphs/conversational.py
9. src/interfaces/cli.py, src/interfaces/openai_api.py
10. src/main.py
11. Dockerfile, docker-compose.yml, config/settings.yaml.example
12. tests/
