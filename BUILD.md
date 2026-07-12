# Codex Build Instructions for media-agent MVP (Historical)

> **⚠️ HISTORICAL DOCUMENT** — These were the original build instructions used to scaffold the MVP.  
> The system has since grown to 70 tools across Phases 1–4.  
>  
> **For current development guidance:** See [docs/development-guide.md](docs/development-guide.md) and [CLAUDE.md](CLAUDE.md)

## Context

You are building the MVP for a media management agent. The full design spec is in SPEC.md.
Read it carefully before starting. This file gives you the specific implementation guidance
to avoid ambiguity. **When BUILD.md and SPEC.md conflict, BUILD.md wins** — it contains
the verified implementation details.

## What to Build (MVP Only)

1. **Project scaffold** — pyproject.toml, requirements.txt, directory structure per SPEC.md
2. **Type definitions** (`src/engine/types.py`) — Pydantic models (see §Types below)
3. **API clients** — Sonarr, Radarr, Emby (see §API Clients below for exact endpoints)
4. **Health check tools** (`src/tools/health.py`)
5. **Tool registry** (`src/tools/registry.py`) — LangGraph @tool definitions
6. **LLM client** (`src/llm/client.py`) — local-first router with circuit breaker
7. **Conversational graph** (`src/graphs/conversational.py`) — use `create_react_agent` (see §Graph)
8. **CLI interface** (`src/interfaces/cli.py`)
9. **OpenAI-compatible API** (`src/interfaces/openai_api.py`) — FastAPI with SSE (see §SSE)
10. **Configuration** (`src/config.py`)
11. **Dockerfile** and **docker-compose.yml**
12. **Tests** — mock-based tests for API clients and graph

## DO NOT Build

- Telegram bot, web dashboard (Phase 2)
- Library management / curation / scheduler (Phase 2)
- YouTube/Audible/Bandcamp/ROMs (Phase 3+)
- SABnzbd/qBittorrent/Prowlarr (Phase 2)
- Acquisition state machine graph (Phase 2)

---

## Ollama Connection (CRITICAL)

The Ollama container runs in the `agent-lab_agent-mesh` Docker network. The
media-agent container joins this network. Reach Ollama at:

```
http://agent-lab-ollama-1:11435
```

Use model `qwen3.5:9b`. Do NOT use `host.docker.internal` or `localhost:11434`.

```python
from langchain_ollama import ChatOllama
llm = ChatOllama(
    base_url="http://agent-lab-ollama-1:11435",
    model="qwen3.5:9b",
    temperature=0,
)
```

---

## Servarr API Clients (Sonarr + Radarr)

Both share identical API patterns. Use `httpx.AsyncClient`. Auth via `X-Api-Key` header
(not query param — header is cleaner and avoids logging keys in URLs).

### Base Client Pattern

```python
import httpx
from typing import Any

class ServarrClient:
    """Base client for Sonarr/Radarr v3 API."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = timeout

    async def _get(self, endpoint: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v3{endpoint}",
                headers=self.headers,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, endpoint: str, json_data: dict) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/v3{endpoint}",
                headers=self.headers,
                json=json_data,
            )
            resp.raise_for_status()
            return resp.json()
```

### Sonarr Endpoints (exact)

```python
class SonarrClient(ServarrClient):
    async def search_series(self, query: str) -> list[dict]:
        """GET /api/v3/series/lookup?term={query}"""
        return await self._get("/series/lookup", params={"term": query})

    async def add_series(self, tvdb_id: int, title: str,
                         quality_profile_id: int = 1,
                         root_folder_path: str = "/tv/",
                         monitored: bool = True) -> dict:
        """POST /api/v3/series"""
        body = {
            "tvdbId": tvdb_id,
            "title": title,
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": monitored,
            "addOptions": {"searchForMissingEpisodes": True},
            "seriesType": "standard",
        }
        return await self._post("/series", body)

    async def list_series(self) -> list[dict]:
        """GET /api/v3/series"""
        return await self._get("/series")

    async def get_queue(self) -> list[dict]:
        """GET /api/v3/queue — returns records from queue response"""
        result = await self._get("/queue")
        return result.get("records", result) if isinstance(result, dict) else result

    async def get_history(self, page: int = 1, page_size: int = 20) -> dict:
        """GET /api/v3/history"""
        return await self._get("/history", params={"page": page, "pageSize": page_size})

    async def search_missing(self, series_id: int | None = None) -> dict:
        """POST /api/v3/command — trigger search"""
        body = {"name": "MissingEpisodesSearch"}
        if series_id:
            body["seriesId"] = series_id
        return await self._post("/command", body)

    async def get_calendar(self, start: str | None = None, end: str | None = None) -> list[dict]:
        """GET /api/v3/calendar"""
        params = {}
        if start: params["start"] = start
        if end: params["end"] = end
        return await self._get("/calendar", params=params or None)

    async def get_health(self) -> list[dict]:
        """GET /api/v3/health"""
        return await self._get("/health")
```

### Radarr Endpoints (exact — swap series→movie)

Same pattern, different endpoints:
- `search_movie`: GET `/api/v3/movie/lookup?term={query}`
- `add_movie`: POST `/api/v3/movie` with body `{"tmdbId": N, "title": "...", "qualityProfileId": 1, "rootFolderPath": "/movies/", "monitored": true, "addOptions": {"searchForMovie": true}}`
- `list_movies`: GET `/api/v3/movie`
- `get_queue`: GET `/api/v3/queue`
- `get_history`: GET `/api/v3/history`
- `search_missing`: POST `/api/v3/command` with `{"name": "MissingMoviesSearch"}`
- `get_health`: GET `/api/v3/health`

---

## Emby API Client

Emby uses `X-Emby-Token` header OR `api_key` query param. Use the header.

```python
class EmbyClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Emby-Token": api_key}
        self.timeout = timeout

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}{path}",
                headers=self.headers,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, json_data: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                headers=self.headers,
                json=json_data,
            )
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, limit: int = 20) -> dict:
        """GET /emby/Items?SearchTerm={query}&Recursive=true&Limit={limit}"""
        return await self._get("/emby/Items", params={
            "SearchTerm": query, "Recursive": "true", "Limit": limit
        })

    async def get_recent(self, limit: int = 20) -> dict:
        """GET /emby/Items/Latest"""
        return await self._get("/emby/Items/Latest", params={"Limit": limit})

    async def get_libraries(self) -> list[dict]:
        """GET /emby/Library/VirtualFolders"""
        return await self._get("/emby/Library/VirtualFolders")

    async def trigger_scan(self) -> Any:
        """POST /emby/Library/Refresh"""
        return await self._post("/emby/Library/Refresh")

    async def get_item(self, item_id: str) -> dict:
        """GET /emby/Items/{item_id}"""
        return await self._get(f"/emby/Items/{item_id}")
```

---

## LangGraph Conversational Graph

**Decision: Use `create_react_agent` from `langgraph.prebuilt`.**

The MOA review flagged the choice between custom StateGraph and `create_react_agent`.
Use `create_react_agent` — it handles the tool-call loop automatically (LLM decides
which tools to call, calls them, sees results, repeats until done). For the MVP, the
simpler approach is better. We can migrate to a custom StateGraph in Phase 2 when we
need disambiguation nodes and multi-turn confirmation flows.

```python
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool

# Define tools as LangGraph tool functions
@tool
def search_tv(query: str) -> str:
    """Search for TV shows by name. Returns matching shows with titles, years, and tvdbIds.
    Use this when the user asks to find or search for a TV show."""
    # Implementation calls SonarrClient.search_series(query)
    # Returns formatted string: "Found 3 results:\n1. Breaking Bad (2008) [tvdbId: 81189]..."
    ...

@tool
def add_tv_show(tvdb_id: int, title: str) -> str:
    """Add a TV show to the monitored library by its TVDB ID.
    The show will be monitored and a search for episodes will be triggered."""
    ...
    return f"✅ Added '{title}' (tvdbId: {tvdb_id}) to the library. Searching for episodes..."

# Create the agent
SYSTEM_PROMPT = """You are Media Agent, a helpful assistant that manages a personal media library.

You can:
- Search and add TV shows (via Sonarr)
- Search and add movies (via Radarr)
- Browse and search the Emby library
- Check download queues and service health
- View upcoming episodes and recent additions

When the user asks to add something, search first, then confirm the match before adding.
Format responses concisely. Use checkmarks (✅) for success, (❌) for errors.
If a tool fails, explain what went wrong in plain language."""

agent = create_react_agent(llm, tools=all_tools, prompt=SYSTEM_PROMPT)
```

### Tool Return Format

**Always return strings, not dicts.** The LLM sees tool return values as text, not structured
data. Format tool results as human-readable strings that the LLM can incorporate into its
response:

```python
@tool
def list_tv_shows() -> str:
    """List all monitored TV shows."""
    series = await sonarr.list_series()
    if not series:
        return "No TV shows are currently monitored."
    lines = [f"Monitoring {len(series)} shows:\n"]
    for s in sorted(series, key=lambda x: x.get("title", "")):
        seasons = s.get("statistics", {}).get("seasonCount", 0)
        episodes = s.get("statistics", {}).get("episodeFileCount", 0)
        lines.append(f"  • {s['title']} — {seasons} seasons, {episodes} episodes")
    return "\n".join(lines)
```

### Error Handling in Tools

Wrap every tool in error handling. Return clear error messages, not exceptions:

```python
@tool
def get_tv_health() -> str:
    """Check Sonarr health status."""
    try:
        issues = await sonarr.get_health()
        if not issues:
            return "✅ Sonarr health: all checks passing."
        results = ["⚠️ Sonarr health issues:\n"]
        for issue in issues:
            results.append(f"  • [{issue.get('type', 'unknown')}] {issue.get('message', 'no message')}")
        return "\n".join(results)
    except httpx.ConnectError:
        return "❌ Cannot connect to Sonarr at " + sonarr.base_url
    except httpx.TimeoutException:
        return "❌ Sonarr request timed out."
    except Exception as e:
        return f"❌ Sonarr health check failed: {type(e).__name__}: {e}"
```

---

## LLM Client — Circuit Breaker Pattern

The MOA review flagged a race condition in the simple router. Use a circuit breaker:

```python
import asyncio
import time
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"      # Local is healthy, use it
    OPEN = "open"          # Local is unhealthy, use fallback
    HALF_OPEN = "half_open"  # Testing if local recovered

class MediaLLM:
    def __init__(self, ollama_url, ollama_model, fallback_url=None, fallback_key=None, fallback_model=None):
        self.local_llm = ChatOllama(base_url=ollama_url, model=ollama_model, temperature=0)
        self.fallback_llm = None
        if fallback_url:
            self.fallback_llm = ChatOpenAI(base_url=fallback_url, api_key=fallback_key,
                                           model=fallback_model, temperature=0)

        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure_time = 0
        self._lock = asyncio.Lock()
        self._failure_threshold = 3      # Open after 3 failures
        self._recovery_timeout = 60       # Try half-open after 60s
        self._half_open_max_calls = 1
        self._half_open_calls = 0

    async def get_llm(self) -> BaseChatModel:
        """Get the appropriate LLM based on circuit breaker state."""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return self.local_llm
            elif self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time > self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    return self.local_llm  # Try local once
                return self.fallback_llm if self.fallback_llm else self.local_llm
            else:  # HALF_OPEN
                if self._half_open_calls < self._half_open_max_calls:
                    self._half_open_calls += 1
                    return self.local_llm
                return self.fallback_llm if self.fallback_llm else self.local_llm

    async def record_success(self):
        async with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED

    async def record_failure(self):
        async with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()
            if self._failures >= self._failure_threshold:
                self._state = CircuitState.OPEN
```

---

## OpenAI-Compatible API with SSE Streaming

This is the critical format detail the MOA review flagged. Here's the exact SSE format
Open WebUI expects:

### SSE Chunk Format

Each chunk is a JSON object prefixed with `data: ` and suffixed with `\n\n`:

```
data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1234567890,"model":"media-agent","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1234567890,"model":"media-agent","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1234567890,"model":"media-agent","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1234567890,"model":"media-agent","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### FastAPI Implementation

```python
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json, time, uuid

app = FastAPI(title="Media Agent")

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = "media-agent"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None

def check_auth(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing API key")
    token = authorization.removeprefix("Bearer ")
    if token != settings.server.api_key:
        raise HTTPException(401, "Invalid API key")

@app.get("/v1/models")
async def list_models(authorization: str | None = Header(None)):
    check_auth(authorization)
    return {"data": [{"id": "media-agent", "object": "model", "owned_by": "media-agent"}]}

@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: str | None = Header(None),
):
    check_auth(authorization)

    if request.stream:
        return StreamingResponse(
            stream_response(request.messages),
            media_type="text/event-stream",
        )
    else:
        # Non-streaming: run agent, return full response
        result = await agent.ainvoke({"messages": [m.model_dump() for m in request.messages]})
        content = result["messages"][-1].content
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "media-agent",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

async def stream_response(messages: list[ChatMessage]):
    """Stream agent response as SSE chunks."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())

    def chunk(content: str = "", finish_reason: str | None = None) -> str:
        payload = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "media-agent",
            "choices": [{
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish_reason,
            }],
        }
        return f"data: {json.dumps(payload)}\n\n"

    # Initial role chunk
    yield chunk()  # Empty delta with role assistant

    # Stream agent tokens
    async for event in agent.astream_events(
        {"messages": [m.model_dump() for m in messages]},
        version="v2",
    ):
        if event["event"] == "on_chat_model_stream":
            token = event["data"]["chunk"].content
            if token:
                yield chunk(content=token)

    # Final chunk + DONE
    yield chunk(finish_reason="stop")
    yield "data: [DONE]\n\n"

@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## Configuration

Use `pydantic-settings` with `.env` file. Load `settings.yaml` for service URLs:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml, re, os

class Settings:
    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path) as f:
            raw = f.read()
        # Substitute ${ENV_VAR} patterns
        def replacer(m):
            return os.environ.get(m.group(1), m.group(0))
        resolved = re.sub(r'\$\{([^}]+)\}', replacer, raw)
        self._data = yaml.safe_load(resolved)

    @property
    def sonarr(self): return self._data["services"]["sonarr"]
    @property
    def radarr(self): return self._data["services"]["radarr"]
    @property
    def emby(self): return self._data["services"]["emby"]
    @property
    def llm(self): return self._data["llm"]
    @property
    def server(self): return self._data["server"]

settings = Settings()
```

---

## Docker Compose

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
      - agent-mesh
      - default

networks:
  agent-mesh:
    external: true
    name: agent-lab_agent-mesh

volumes:
  agent-state:
```

---

## CLI Interface

```python
import asyncio
from rich.console import Console
from rich.markdown import Markdown

async def cli_repl():
    console = Console()
    console.print("[bold green]Media Agent[/] — Interactive Mode")
    console.print("Type 'exit' or 'quit' to leave.\n")

    while True:
        try:
            user_input = console.input("[bold cyan]you>[/] ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            if not user_input.strip():
                continue

            # Run agent
            result = await agent.ainvoke({
                "messages": [{"role": "user", "content": user_input}]
            })
            response = result["messages"][-1].content
            console.print(Markdown(response))
            console.print()
        except KeyboardInterrupt:
            console.print("\n[dim]Goodbye![/]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
```

---

## System Prompt

```python
SYSTEM_PROMPT = """You are Media Agent, a helpful assistant that manages a personal media library.

You can:
- Search and add TV shows (via Sonarr)
- Search and add movies (via Radarr)
- Browse and search the Emby library
- Check download queues and service health
- View upcoming episodes and recent additions

Guidelines:
- When the user asks to add something, search first, confirm the match, then add.
- Format responses concisely with bullet points.
- Use ✅ for success, ❌ for errors, ⚠️ for warnings.
- If a tool fails, explain what went wrong in plain language.
- If a search returns multiple results, list them and ask which one the user wants.
- Keep responses short — you're a tool-using agent, not a chatbot.

Available TV tools: search_tv, add_tv_show, list_tv_shows, get_tv_queue,
get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health

Available movie tools: search_movie, add_movie, list_movies, get_movie_queue,
get_movie_history, search_missing_movies, get_movie_health

Available library tools: emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item

Available health tools: check_all_health, check_disk_space, check_queue_status
"""
```

---

## Requirements

```
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-ollama>=0.2.0
langchain-openai>=0.2.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
httpx>=0.27.0
rich>=13.0.0
sse-starlette>=2.0.0
PyYAML>=6.0
```

---

## Build Order

1. `pyproject.toml` + `requirements.txt`
2. `src/config.py` — Settings loader
3. `src/engine/types.py` — Pydantic data models
4. `src/tools/sonarr.py` — SonarrClient + tool functions
5. `src/tools/radarr.py` — RadarrClient + tool functions
6. `src/tools/emby.py` — EmbyClient + tool functions
7. `src/tools/health.py` — Health check tools
8. `src/tools/registry.py` — Import all tools, export `all_tools` list
9. `src/llm/client.py` — Circuit breaker LLM router
10. `src/graphs/conversational.py` — create_react_agent with tools + system prompt
11. `src/interfaces/cli.py` — CLI REPL
12. `src/interfaces/openai_api.py` — FastAPI OpenAI-compatible endpoint
13. `src/main.py` — Entry point (CLI or API mode)
14. `Dockerfile` + `docker-compose.yml`
15. `config/settings.yaml.example`
16. `tests/` — Mock-based tests

## Quality Bar

- Every API client method has try/except with clear error messages
- Every @tool function returns a string (not dict) with formatted output
- The agent handles wrong/missing tool arguments gracefully
- API requires Bearer token auth on /v1/ endpoints
- /health endpoint is unauthenticated
- Docker container runs as non-root user
- All public functions have docstrings
- Type hints on all function signatures
