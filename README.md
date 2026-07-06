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

## Local model recommendations (Ollama)

The agent binds ~60 tool schemas, which is demanding for small models. These
are the smallest models that stay reliable, from testing and current
tool-calling benchmarks:

| Model | Size | Notes |
|---|---|---|
| `qwen3.5:9b` | ~6.6 GB | **Default.** Best quality/size balance; fits 8 GB VRAM / 16 GB Mac |
| `qwen3.5:4b` | ~3.4 GB | Smallest recommended; good on CPU-only or 6 GB VRAM boxes |
| `qwen3:8b` | ~5.2 GB | Proven fallback if qwen3.5 misbehaves |

Not recommended below ~4B (`qwen3.5:2b`, `llama3.2:3b`, `qwen3.5:0.8b`): with
a tool list this large they drop or malform tool calls too often to be useful.

### Ollama settings that matter

- **`num_ctx` (context window) is critical.** Ollama defaults to 2048–4096
  tokens, which is smaller than this agent's system prompt + tool schemas.
  When the context overflows, Ollama silently truncates the prompt — the
  model loses its tool definitions and starts printing tool-call JSON into
  the chat. The agent sets `num_ctx: 16384` by default (`llm.num_ctx` in
  `settings.yaml`); don't go below 8192.
- **Thinking models** (qwen3/qwen3.5, deepseek-r1) emit `<think>` traces.
  Set `llm.reasoning: false` to ask Ollama to disable them; the agent also
  strips any leaked traces from responses as a safety net.
- `llm.keep_alive` (default `10m`) keeps the model loaded between requests
  so follow-up messages don't pay the model-load latency.

### Hosted fallback (optional)

Set `llm.hosted_url` / `hosted_key` / `hosted_model` to an OpenAI-compatible
endpoint and the agent automatically falls back to it for any request where
Ollama fails or is unreachable.
