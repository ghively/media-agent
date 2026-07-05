# Media Agent

A standalone, containerized agent for managing a personal media ecosystem.

## Current Status: MVP (Sonarr + Radarr + Emby)

See [SPEC.md](SPEC.md) for the full design specification.

## Quick Start

```bash
# Copy and fill in credentials
cp config/settings.yaml.example config/settings.yaml

# Build and run
docker compose up -d

# Interact via CLI
docker exec -it media-agent python -m src.main --interactive
```
