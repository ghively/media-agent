# Media Agent

A standalone, containerized agent for managing a personal media ecosystem.
It drives Sonarr (TV), Radarr (movies), Emby, SABnzbd, and Synology Download
Station, plus direct providers for YouTube (yt-dlp), Bandcamp, Audible, and
classic-game ROMs — all through a conversational LLM agent (local Ollama with
optional hosted fallback).

See [SPEC.md](SPEC.md) for the full design specification.

## Quick Start

```bash
# Copy and fill in credentials
cp config/settings.yaml.example config/settings.yaml
cp .env.example .env

# Build and run
docker compose up -d

# Interact via CLI
docker exec -it media-agent python -m src.main --interactive
```

## Usage

```bash
python -m src.main --interactive     # interactive REPL
python -m src.main -q "what's in the download queue?"   # one-shot query
python -m src.main --health          # quick service health check
python -m src.main --serve           # OpenAI-compatible API + dashboard (+ scheduler if enabled)
```

With `--serve` running:

- **OpenAI-compatible API** at `http://localhost:8088/v1/chat/completions`
  (model name `media-agent`; set `server.api_key` in settings to require a Bearer token)
- **Web dashboard** at `http://localhost:8088/dashboard`
- **Health endpoint** at `http://localhost:8088/health`

## Architecture (tuned for small local models)

Requests are routed **deterministically** (keyword scoring, no LLM tokens)
to a domain agent that binds only 4–13 relevant tools instead of all ~60,
with a compact generated prompt (~200–370 tokens vs ~1,340 before). Common
multi-step flows are **workflow pipelines** — plain code that runs
search → decide → act → **verify** in a single tool call, so "add Severance"
costs one LLM round instead of four. Every mutating action reads back the
resulting state and only reports `✅ Verified` when confirmed; scheduled
automation (health, missing-content search, YouTube/Audible sync) runs
pipelines directly with no LLM at all.

See [WORKFLOWS.md](WORKFLOWS.md) for the full workflow map and the
deterministic-vs-LLM breakdown.

## Tool groups

| Group | Tools |
|---|---|
| Workflows | `grab_media` (search+add+verify in one call), `system_report`, `sync_youtube`, `library_cleanup` |
| TV (Sonarr) | search, add, list, queue, history, missing-episode search, calendar, health |
| Movies (Radarr) | search, add, list, queue, history, missing-movie search, health |
| Emby | search, recent, libraries, scan, item details |
| Health | all-service health, disk space, queue status |
| Library | inventory, duplicate finder, naming check/fix/undo |
| Unified search | `search_media` across all sources + `download_media` by result number |
| SABnzbd | queue, history, status, pause, resume, add NZB |
| Download Station | list, add, pause, resume, info, stats |
| Bandcamp | album/track download, collection download |
| Audible | library list, download + decrypt, sync new, auth setup/check |
| ROMs | Internet Archive search/download, DAT verification, collection listing |
| YouTube | download, video info, subscriptions (add/remove/list/check) |

## Development

```bash
pip install -r requirements.txt
pip install pytest
python -m pytest tests/
```
