# Media Agent — Deployment Guide

**Version:** 2.0  
**Date:** 2026-07-05

---

## Prerequisites

| Requirement | Details |
|---|---|
| Docker + Docker Compose | On the host machine (gh-nvidia) |
| Ollama container | Running in `agent-lab_agent-mesh` network with `qwen3.5:9b` model |
| Network access | To gh-storage (192.168.0.133) and gh-media (192.168.0.144) |
| API keys | In `.env` file, sourced from 1Password vault "Gregory" |

---

## First Deployment

### 1. Clone the Repository

```bash
git clone git@github.com:ghively/media-agent.git
cd media-agent
```

### 2. Configure Environment

```bash
# Copy templates
cp config/settings.yaml.example config/settings.yaml
cp .env.example .env

# Fill in API keys (from 1Password vault "Gregory")
# Required: SONARR_API_KEY, RADARR_API_KEY, EMBY_API_KEY, SABNZBD_API_KEY
# Required: MEDIA_AGENT_API_KEY (generate one: openssl rand -hex 16)
nano .env
```

### 3. Verify settings.yaml

Check `config/settings.yaml` — the service URLs should match your network:

```yaml
services:
  sonarr:
    url: "http://192.168.0.133:8989"   # gh-storage NAS
    api_key: "${SONARR_API_KEY}"
  radarr:
    url: "http://192.168.0.133:8310"   # gh-storage NAS
    api_key: "${RADARR_API_KEY}"
  emby:
    url: "http://192.168.0.144:8096"   # gh-media NUC
    api_key: "${EMBY_API_KEY}"
  sabnzbd:
    url: "http://192.168.0.133:8080"   # gh-storage NAS
    api_key: "${SABNZBD_API_KEY}"
```

### 4. Build and Start

```bash
docker compose up -d --build
```

First build takes ~3-5 minutes (installs ffmpeg, yt-dlp, audible-cli, etc.).

### 5. Verify

```bash
# Container health
docker compose ps
# → media-agent   Up (healthy)

# API health
curl http://localhost:8088/health
# → {"status":"ok"}

# Tool count
docker exec media-agent python -c "from src.tools.registry import all_tools; print(f'{len(all_tools)} tools')"
# → 49 tools

# Dashboard
# Open http://localhost:8088/dashboard in a browser
```

### 6. Test the Agent

```bash
# CLI test (first query will be slow — model warmup)
docker exec media-agent python -m src.main -q "is everything healthy?"
```

---

## Rebuilding After Code Changes

```bash
cd /home/ghively/agent-lab/media-agent

# Rebuild and restart (preserves container name and network)
docker compose up -d --build

# Quick verify
curl http://localhost:8088/health
```

For a clean rebuild (no cache):

```bash
docker compose build --no-cache && docker compose up -d
```

---

## Connecting Open WebUI

1. Open Open WebUI → Settings → Connections
2. Add a new OpenAI-compatible connection:
   - **URL:** `http://gh-nvidia:8088/v1`
   - **API Key:** The value of `MEDIA_AGENT_API_KEY` from your `.env`
3. Save. The "media-agent" model appears in the model dropdown.
4. Start chatting.

---

## Configuration Reference

### settings.yaml sections

| Section | Keys | Purpose |
|---|---|---|
| `server` | `host`, `port`, `api_key` | API server bind address and auth |
| `llm` | `ollama_url`, `ollama_model`, `hosted_url`, `hosted_key`, `hosted_model` | LLM configuration |
| `services.sonarr` | `url`, `api_key` | Sonarr API |
| `services.radarr` | `url`, `api_key` | Radarr API |
| `services.emby` | `url`, `api_key` | Emby API |
| `services.sabnzbd` | `url`, `api_key` | SABnzbd API |
| `scheduler` | `enabled`, `jobs` | APScheduler config (currently auto-started) |
| `library` | `media_root`, `naming_conventions` | Library management paths and rules |

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SONARR_API_KEY` | Yes | — | Sonarr v4 API key |
| `RADARR_API_KEY` | Yes | — | Radarr API key |
| `EMBY_API_KEY` | Yes | — | Emby API key |
| `SABNZBD_API_KEY` | Yes | — | SABnzbd API key |
| `MEDIA_AGENT_API_KEY` | Yes | — | Bearer token for API auth |
| `HOSTED_LLM_URL` | No | — | Fallback LLM endpoint |
| `HOSTED_LLM_KEY` | No | — | Fallback LLM API key |
| `HOSTED_LLM_MODEL` | No | — | Fallback LLM model name |
| `MEDIA_AGENT_CONFIG` | No | `config/settings.yaml` | Custom config path |

---

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs media-agent

# Common causes:
# 1. Missing .env file → copy .env.example
# 2. Missing settings.yaml → copy settings.yaml.example
# 3. Can't reach agent-mesh network → ensure agent-lab is running
```

### Ollama connection failed

```bash
# Verify agent-lab is running
docker ps | grep ollama

# Verify model is available
docker exec agent-lab-ollama-1 ollama list | grep qwen

# Test connectivity from media-agent container
docker exec media-agent curl -s http://agent-lab-ollama-1:11435/api/tags
```

### Service API connection failed

```bash
# Test from the container
docker exec media-agent curl -s http://192.168.0.133:8989/api/v3/health \
  -H "X-Api-Key: $SONARR_API_KEY"

# Common causes:
# 1. Wrong API key → check .env
# 2. Wrong URL → check settings.yaml
# 3. Service is down → check the host
# 4. Firewall blocking → check DSM firewall on NAS
```

### First query is slow

The Qwen 3.5 9B model needs to load into VRAM on first use (~10-15 seconds). Subsequent queries are ~35 tok/s. The circuit breaker will route to the fallback LLM if Ollama times out.

### Tool count is wrong

```bash
# Check which optional tools loaded
docker compose logs media-agent 2>&1 | grep -i import
```

Optional tools (SABnzbd, Download Station, YouTube, Search) are wrapped in try/except. If a dependency is missing, they silently don't load. Check `requirements.txt` and the Dockerfile.

---

## Backup

The container uses two bind mounts:
- `./config/` — settings.yaml (contains `${VAR}` placeholders, safe to back up)
- `agent-state` volume — scheduler state, undo logs

The `.env` file is gitignored and contains real secrets. Back up separately (or rely on 1Password as source of truth).

---

## Rollback

```bash
# Revert to previous commit
git log --oneline -5
git checkout <previous-commit> -- .
docker compose up -d --build
```

Container data (config, state) is bind-mounted — safe across rebuilds.

---

## Host-Specific Notes

### gh-nvidia (deployment host)

- Docker group membership required: `sg docker -c "docker compose ..."`
- The `agent-lab` Docker Compose project must be running (provides Ollama + agent-mesh network)
- GPU is NOT used by media-agent directly — it uses Ollama over the network

### gh-storage (Synology NAS)

- Sonarr, Radarr, SABnzbd run as native SPK packages (not Docker)
- Download Station is a built-in DSM package
- DSM firewall must allow traffic from gh-nvidia (192.168.0.x)

### gh-media (Intel NUC)

- Emby runs on bare metal
- Has a 4GB tmpfs RAM disk for transcoding
- No other services for the media agent

---

*Last updated: 2026-07-05*
