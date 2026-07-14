# Media Agent — Deployment Guide

**Version:** 2.0  
**Last updated:** 2026-07-11

---

## Prerequisites

| Requirement | Details |
|---|---|
| Docker + Docker Compose | On the host machine (your-gpu-host) |
| Ollama container | Running in `agent-lab_agent-mesh` network with `qwen3.5:9b` model |
| Network access | To your-nas (<YOUR_NAS_IP>) and your-media-host (<YOUR_MEDIA_IP>) |
| API keys | In `.env` file, sourced from password manager

---

## First Deployment

### 1. Clone the Repository

```bash
git clone git@github.com:the-owner/media-agent.git
cd media-agent
```

### 2. Configure Environment

```bash
# Copy templates
cp config/settings.yaml.example config/settings.yaml
cp .env.example .env

# Fill in API keys (from your password manager)
# Required: SONARR_API_KEY, RADARR_API_KEY, EMBY_API_KEY, SABNZBD_API_KEY
# Required: MEDIA_AGENT_API_KEY (generate one: openssl rand -hex 16)
nano .env
```

### 3. Verify settings.yaml

Check `config/settings.yaml` — the service URLs should match your network:

```yaml
services:
  sonarr:
    url: "http://<YOUR_NAS_IP>:8989"   # your-nas NAS
    api_key: "${SONARR_API_KEY}"
  radarr:
    url: "http://<YOUR_NAS_IP>:8310"   # your-nas NAS
    api_key: "${RADARR_API_KEY}"
  emby:
    url: "http://<YOUR_MEDIA_IP>:8096"   # your-media-host NUC
    api_key: "${EMBY_API_KEY}"
  sabnzbd:
    url: "http://<YOUR_NAS_IP>:8080"   # your-nas NAS
    api_key: "${SABNZBD_API_KEY}"
```

**Also check `llm.ollama_url`.** The default
(`http://agent-lab-ollama-1:11435`) only resolves on the original
agent-lab host. Point it at your own Ollama instance — a stock install
listens on port **11434** (e.g. `http://<OLLAMA_HOST>:11434`) — and make
sure the model is pulled (`ollama pull qwen3.5:9b`, or change
`llm.ollama_model` to a tool-calling model you have). The agent starts
fine without an LLM (the deterministic router still answers common
commands), but conversational queries will fail until this URL is right.

### 3b. New-box checklist

If this is **not** the original agent-lab host, two more things before
building:

1. **The `agent-mesh` Docker network.** `docker-compose.yml` declares an
   external network `agent-lab_agent-mesh`; compose refuses to start if it
   doesn't exist. Either create it:
   ```bash
   docker network create agent-lab_agent-mesh
   ```
   or, if your Ollama isn't containerized on a shared network, delete the
   `agent-mesh` entries from the `networks:` blocks in `docker-compose.yml`
   and reach Ollama by host IP instead.

2. **Point MEDIA_ROOT at your media library.** Compose mounts
   `${MEDIA_ROOT:-./media}` at `/media`, where every download provider
   (music, audiobooks, ROMs, YouTube) and the library scanner write. Set it
   in `.env` to the real library (e.g. an NFS mount of the NAS):
   ```bash
   MEDIA_ROOT=/mnt/nas/media
   ```
   Left unset, downloads land in `./media` next to the compose file — still
   persistent, just not on the NAS. Audible auth lives on the `/state`
   volume (`services.audible.auth_dir`, default `/state/audible`) and
   survives restarts either way.

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
# → 102 tools

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
cd /home/the-owner/agent-lab/media-agent

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

> **Note:** the compose file binds the port to `127.0.0.1` only. From
> another machine, `http://<host>:8088` is **not** reachable — connect from
> the same host, join the containers to a shared Docker network (use
> `http://media-agent:8088/v1`), or front it with an authenticated reverse
> proxy / VPN before widening the bind.

1. Open Open WebUI → Settings → Connections
2. Add a new OpenAI-compatible connection:
   - **URL:** `http://localhost:8088/v1` (same host; see note above)
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
| `services.bandcamp` | `download_path` | Bandcamp download root (default `/media/music`) |
| `services.audible` | `auth_dir`, `download_path` | Audible auth (default `/state/audible`) and download root (default `/media/audiobooks`) |
| `notifications` | `url`, `kind`, `chat_id` | Optional push for scheduler findings (`ntfy`, `discord`, `generic`, or `telegram`) |
| `services.podcasts` | `download_path` | Podcast episode downloads (default `/media/podcasts`) |
| `services.twitch` | `download_path` | Twitch recordings (default `/media/twitch`) |
| `services.komga` | `url`, `api_key` | Komga comic server (optional) |
| `services.calibre` | `url`, `username`, `password` | Calibre content server (optional) |
| `services.lidarr` | `url`, `api_key`, `quality_profile_id`, `metadata_profile_id`, `root_folder_path` | Lidarr music management (optional) |
| `services.prowlarr` | `url`, `api_key` | Prowlarr unified indexer search (optional) |
| `services.qbittorrent` | `url`, `username`, `password` | qBittorrent (optional; preferred over Download Station for magnets when set) |
| `telegram` | `bot_token`, `allowed_chat_ids` | Telegram chat interface (optional; refuses chats not in the allowlist) |

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SONARR_API_KEY` | Yes | — | Sonarr v4 API key |
| `RADARR_API_KEY` | Yes | — | Radarr API key |
| `EMBY_API_KEY` | Yes | — | Emby API key |
| `SABNZBD_API_KEY` | Yes | — | SABnzbd API key |
| `MEDIA_AGENT_API_KEY` | Recommended | — | Bearer token for API auth. Unset = auth disabled (safe only behind the default loopback bind) |
| `HOSTED_LLM_URL` | No | — | Fallback LLM endpoint |
| `HOSTED_LLM_KEY` | No | — | Fallback LLM API key |
| `HOSTED_LLM_MODEL` | No | — | Fallback LLM model name |
| `MEDIA_AGENT_CONFIG` | No | `config/settings.yaml` | Custom config path |
| `MEDIA_ROOT` | Recommended | `./media` | Host path mounted at `/media` (docker-compose) — point at the real media library |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token (from @BotFather) |
| `LIDARR_API_KEY` / `PROWLARR_API_KEY` / `KOMGA_API_KEY` | No | — | Optional service integrations |
| `QBIT_USERNAME` / `QBIT_PASSWORD` / `CALIBRE_PASSWORD` | No | — | Optional service credentials |

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
docker exec media-agent curl -s http://<YOUR_NAS_IP>:8989/api/v3/health \
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

The `.env` file is gitignored and contains real secrets. Back up separately (or rely on password manager as source of truth).

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

### your-gpu-host (deployment host)

- Docker group membership required: `sg docker -c "docker compose ..."`
- The `agent-lab` Docker Compose project must be running (provides Ollama + agent-mesh network)
- GPU is NOT used by media-agent directly — it uses Ollama over the network

### your-nas (Synology NAS)

- Sonarr, Radarr, SABnzbd run as native SPK packages (not Docker)
- Download Station is a built-in DSM package
- DSM firewall must allow traffic from your-gpu-host (your-NAS-IP)

### your-media-host (Intel NUC)

- Emby runs on bare metal
- Has a 4GB tmpfs RAM disk for transcoding
- No other services for the media agent

---

*Last updated: 2026-07-11*
