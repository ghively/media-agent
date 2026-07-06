# CLAUDE.md — AI Development Context

> **Read this first.** This file gives any AI agent (Claude, GPT, Copilot, Codex) the context needed to work on this codebase productively. It captures conventions, patterns, gotchas, and the mental model that isn't obvious from the code alone.

---

## Project Identity

**Media Agent** — a conversational agent for managing a personal media ecosystem.  
**Owner:** the owner  
**Built by:** an AI agent  
**Repo:** `github.com/the-owner/media-agent` (private)  
**Language:** Python 3.12  
**Framework:** LangGraph (ReAct agent) + FastAPI  
**Deployment:** Docker container on your-gpu-host (NVIDIA RTX 3060 workstation)

---

## Quick Orientation

| Need | Read this |
|---|---|
| Understand the system | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Find a specific tool | [docs/tool-reference.md](docs/tool-reference.md) |
| Add a new tool or provider | [docs/development-guide.md](docs/development-guide.md) |
| Deploy or rebuild | [docs/deployment-guide.md](docs/deployment-guide.md) |
| Use the API | [docs/api-reference.md](docs/api-reference.md) |
| Original design vision | [SPEC.md](SPEC.md) (historical) |

---

## The 10 Commandments (Non-Negotiable Conventions)

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

---

## Architecture in 60 Seconds

```
User Input (CLI/API/Dashboard)
    │
    ▼
LangGraph create_react_agent(llm, 66 tools)
    │
    ├── LLM decides which tools to call
    ├── Tools execute (async, parallel when possible)
    ├── Results go back to LLM as text
    └── LLM loops until it can answer
    │
    ▼
Formatted response → User
```

**LLM:** Qwen 2.5 7B via Ollama (local, free, ~35 tok/s).  
**Circuit breaker:** Local-first, falls back to hosted API after 3 failures.  
**Scheduler:** APScheduler daemon thread (health checks, missing searches, cleanup).

---

## Source Map

```
src/
├── main.py              # CLI entry: --serve | --interactive | --query | --health
├── config.py            # Settings singleton: YAML + ${ENV_VAR} substitution
├── scheduler.py         # APScheduler: health(30m), missing(12h), cleanup(3am)
├── engine/
│   └── types.py         # Pydantic models: MediaItem, ContentType, etc.
├── llm/
│   └── client.py        # MediaLLM: circuit breaker (CLOSED→OPEN→HALF_OPEN)
├── graphs/
│   └── conversational.py # create_react_agent + SYSTEM_PROMPT
├── tools/               # LangChain @tool functions (API-backed)
    │   ├── registry.py      # ← all_tools aggregation (THE import point)
    │   ├── sonarr.py        # 12 tools: search, add, list, queue, history, calendar, health, missing, quality profiles, root folders, refresh, season search
    │   ├── radarr.py        # 10 tools: search, add, list, queue, history, health, missing, quality profiles, root folders, refresh
    │   ├── emby.py          # 5 tools: search, recent, libraries, scan, get_item
    │   ├── health.py        # 3 tools: all_health, disk_space, queue_status
    │   ├── sabnzbd.py       # 6 tools: queue, history, status, pause, resume, add NZB
    │   ├── download_station.py # 6 tools: list, add, pause, resume, info, stats
    │   └── search.py        # 2 tools: search_media (unified), download_media
├── providers/           # Content-specific providers (subprocess-backed)
│   ├── base.py          # MediaProvider protocol
│   ├── youtube.py       # 6 tools via yt-dlp subprocess
│   ├── bandcamp.py      # 2 tools via bandcamp-downloader subprocess
│   ├── audible.py       # 5 tools via audible-cli subprocess
│   └── rom.py           # 4 tools via internetarchive subprocess
├── library/             # Library management
│   ├── scanner.py       # Inventory, cross-reference, orphans, duplicates
│   └── naming.py        # Naming convention check/fix + undo logs
└── interfaces/
    ├── cli.py           # Interactive REPL + one-shot + health
    ├── openai_api.py    # FastAPI: /v1/chat/completions + /v1/models + /health
    └── dashboard.py     # Web dashboard HTML (mounted on FastAPI app)
```

---

## How to Add a New Tool

1. **Write the tool** in the appropriate module (`src/tools/` or `src/providers/`):

```python
@tool
async def my_new_tool(param: str) -> str:
    """One-line description of what this tool does. The LLM reads this."""
    try:
        settings = get_settings()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{settings.some_service['url']}/api/endpoint",
                headers={"X-Api-Key": settings.some_service["api_key"]},
            )
            resp.raise_for_status()
            data = resp.json()
        # Format as human-readable string
        return f"✅ Found {len(data)} items:\n" + "\n".join(f"  • {d['name']}" for d in data)
    except httpx.ConnectError:
        return "❌ Cannot connect to service."
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {e}"
```

2. **Register it** in `src/tools/registry.py`:

```python
from src.tools.my_module import my_new_tool
# Add to the all_tools list
```

3. **If it's an optional tool** (requires a dependency that might not be installed), wrap in try/except:

```python
try:
    from src.tools.my_module import my_new_tool
    _my_tools = [my_new_tool]
except ImportError:
    _my_tools = []
```

4. **Update docs:** Add to [docs/tool-reference.md](docs/tool-reference.md)

5. **Rebuild:** `docker compose up -d --build`

6. **Verify:** `docker exec media-agent python -c "from src.tools.registry import all_tools; print(len(all_tools))"`

---

## How to Add a New Provider

Providers are for content types that need **external tools** (subprocess calls), not just API calls.

1. **Create `src/providers/myprovider.py`** following the pattern in `youtube.py` or `audible.py`
2. **Implement the provider as `@tool` functions** — providers ARE tools, they just happen to shell out
3. **Register in `registry.py`** (with try/except guard if the external tool might not be installed)
4. **Add to Dockerfile** if a new system/pip package is needed
5. **Update docs**

---

## Configuration System

`config/settings.yaml` is the config file. It uses `${ENV_VAR}` substitution:

```yaml
services:
  sonarr:
    url: "http://<YOUR_NAS_IP>:8989"
    api_key: "${SONARR_API_KEY}"   # ← replaced from environment at load time
```

The `Settings` class in `src/config.py` is a **singleton** — call `get_settings()` anywhere.

**Adding a new service config section:**
1. Add to `config/settings.yaml.example`
2. Add a `@property` to `Settings` class in `src/config.py`
3. Add env vars to `.env.example`

---

## Testing

Currently no automated tests. To verify manually:

```bash
# Build and start
docker compose up -d --build

# Check health
curl http://localhost:8088/health

# Check tool count
docker exec media-agent python -c "from src.tools.registry import all_tools; print(f'{len(all_tools)} tools')"

# Test a query
docker exec media-agent python -m src.main -q "what's downloading?"

# Interactive test
docker exec -it media-agent python -m src.main -i
```

---

## Common Gotchas

### Ollama Network Address
Use `http://agent-lab-ollama-1:11435` (agent-mesh DNS name), NOT `localhost:11434` or `host.docker.internal`. The media-agent container joins the `agent-mesh` Docker network to reach Ollama.

### Tool Returns Must Be Strings
LangGraph passes tool returns to the LLM as text. If you return a dict, the LLM sees `str(dict)` which is ugly and token-heavy. Always format as a human-readable string.

### Async Everything
All tools, all API calls, all interfaces are async. The agent runs in an async event loop. Don't use `requests` (sync) — use `httpx.AsyncClient`.

### Subprocess in Tools
Providers (YouTube, Audible, etc.) use `asyncio.create_subprocess_exec()` to call external tools. Never use `subprocess.run()` (blocking) — it will freeze the event loop.

### Settings Singleton
`get_settings()` caches on first call. If you change config, you must restart the container. Don't try to "reload" settings at runtime.

### Download Station Config Gap
`src/tools/download_station.py` reads config from `get_settings()._data` directly (bypassing the property pattern). Adding a `download_station` property to `Settings` in `config.py` is a one-line fix.

---

## Git Workflow

```bash
# Standard flow
git checkout -b feature/your-feature
# ... make changes ...
git add -A
git commit -m "feat: description"
git push origin feature/your-feature
# Create PR on GitHub
```

**Commit message convention:** `type: description` (feat, fix, docs, refactor, test, chore)

---

## Infrastructure Context

This agent is part of a larger homelab:

| Host | Role | Managed By |
|---|---|---|
| **your-gpu-host** | GPU workstation, AI/agent lab, this container | Hermes agent-lab |
| **your-nas** | Synology NAS, ~90TB, media services | DSM + homelab-ansible |
| **your-media-host** | Intel NUC, Emby media server | Bare metal |
| **your-vps-host** | VPS, mail/web | homelab-ansible |
| **your-git-host** | Self-hosted GitLab CI/CD | homelab-ansible |

**Source of truth for infrastructure:** `homelab-ansible` repo on self-hosted GitLab.  
**Secrets:** Password manager (all API keys).  
**Documentation:** Living docs in GitLab `docs` repo + this repo's `docs/` directory.

---

## What's Next (Roadmap)

| Priority | Feature | Effort |
|---|---|---|
| **High** | Telegram bot interface (needs bot token from a bot) | Small — `python-telegram-bot` already installed |
| **High** | Prowlarr + qBittorrent deploy on NAS (enables full unified search) | Medium — Docker deploy on your-nas |
| **Medium** | Lidarr deploy (music management) | Small — Docker deploy |
| **Medium** | Automated tests (pytest + pytest-asyncio) | Medium |
| **Medium** | NFS mount into container (enables library scanner on real files) | Small — DSM config + compose volume |
| **Low** | Podcast provider (RSS) | Small — new provider |
| **Low** | Twitch provider (streamlink) | Small — new provider |
| **Low** | Comic provider (Komga API) | Small — new provider |
| **Low** | Ebook provider (Calibre API) | Small — new provider |

---

## Questions an AI Agent Should Ask Before Making Changes

1. **Am I adding a tool?** → Follow the tool pattern exactly (async, string return, try/except)
2. **Am I adding a service?** → Add config property, env var, settings.yaml entry
3. **Am I changing the agent behavior?** → Update SYSTEM_PROMPT in `conversational.py`
4. **Am I changing network config?** → Don't break the agent-mesh → Ollama path
5. **Am I adding a dependency?** → Add to requirements.txt AND Dockerfile pip install
6. **Will this change break existing tools?** → Run `docker exec media-agent python -c "from src.tools.registry import all_tools; print(len(all_tools))"` after rebuild
7. **Did I update the docs?** → README, ARCHITECTURE.md, docs/tool-reference.md as needed

---

*Last updated: 2026-07-05. If the code and this file disagree, the code is right — fix this file.*
