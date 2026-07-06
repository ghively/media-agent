# Media Agent

A standalone, containerized agent for managing a personal media ecosystem.

## Current Status: Full stack — all phases built and functional

All service integrations are first-class: Sonarr, Radarr, Emby, SABnzbd,
Synology Download Station, unified search, Bandcamp, Audible, ROMs
(Internet Archive), YouTube (yt-dlp), and library organization, duplicate/orphan
analysis, plus Lidarr (music) and Bazarr (subtitles) when configured — 67+ tools
total, with a config-driven approval gate on high-impact actions and a
pytest suite covering the agent's chat behavior end-to-end (no live
services needed):

```bash
pip install -r requirements-dev.txt
pytest                                   # test suite (no live services needed)
python -m src.main --doctor              # diagnose the whole deployment
python scripts/model_eval.py --label X   # repeatable model comparison
```

See [SPEC.md](SPEC.md) for the original design specification.

## Quick Start

```bash
# Copy and fill in credentials
cp config/settings.yaml.example config/settings.yaml

# Build and run
docker compose up -d

# Interact via CLI
docker exec -it media-agent python -m src.main --interactive
```

Or just open **http://<host>:8088/chat** in a browser, or enable two-way
**Telegram chat** (`notifications.telegram_chat: true`) and talk to the
agent from your phone — same brain, same approval gate, every interface.

## Documentation

- **[docs/AGENT.md](docs/AGENT.md)** — agent architecture, the full 67-tool
  catalog with risk ratings, built-in workflows, model profiles (thinking vs
  non-thinking), the approval system, and the bulletproofing roadmap.
- [SPEC.md](SPEC.md) — original design specification.

## Local model recommendations (Ollama)

The agent binds ~60 tool schemas, which is demanding for small models. These
are the smallest models that stay reliable, from testing and current
tool-calling benchmarks:

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:7b` | ~4.7 GB | **Default.** Non-thinking, solid tool calling, no reasoning-trace handling needed |
| `qwen3.5:9b` | ~6.6 GB | Best quality/size balance; thinking model — set `llm.reasoning: false` |
| `qwen3.5:4b` | ~3.4 GB | Smallest recommended; good on CPU-only or 6 GB VRAM boxes |
| `qwen3:8b` | ~5.2 GB | Proven alternative in the same class |

Not recommended below ~4B (`qwen3.5:2b`, `llama3.2:3b`, `qwen3.5:0.8b`): with
a tool list this large they drop or malform tool calls too often to be useful.

**Thinking vs non-thinking models:** earlier versions of this agent streamed
raw model tokens, so thinking models (qwen3/qwen3.5) leaked `<think>` traces
and tool-call JSON into chat — the practical workaround was a non-thinking
model like `qwen2.5:7b`, which remains the default. Streaming is now filtered
and reasoning traces are stripped in-app, so thinking models work too; they
generally tool-call better per parameter, at the cost of extra latency while
they think.

**Both profiles are switchable from `.env` alone** — set `OLLAMA_MODEL` (and
`OLLAMA_REASONING=false` for thinking models, empty otherwise), then
`docker compose up -d --force-recreate media-agent`. See
[docs/AGENT.md](docs/AGENT.md#2-model-profiles) for the profile comparison
and an A/B test script.

### Ollama settings that matter

- **`num_ctx` (context window) is critical.** Ollama defaults to 2048–4096
  tokens, which is smaller than this agent's system prompt + tool schemas.
  When the context overflows, Ollama silently truncates the prompt — the
  model loses its tool definitions and starts printing tool-call JSON into
  the chat. The agent sets `num_ctx: 16384` by default (`llm.num_ctx` in
  `settings.yaml`); don't go below 8192.
- **Thinking models** (qwen3/qwen3.5, deepseek-r1) emit `<think>` traces.
  Set `llm.reasoning: false` to ask Ollama to disable them; the agent also
  strips any leaked traces from responses as a safety net. Do not set
  `reasoning` for non-thinking models (qwen2.5, llama3.x) — Ollama errors
  on the flag for models without thinking support.
- `llm.keep_alive` (default `10m`) keeps the model loaded between requests
  so follow-up messages don't pay the model-load latency.

### Hosted fallback (optional)

Set `llm.hosted_url` / `hosted_key` / `hosted_model` to an OpenAI-compatible
endpoint and the agent automatically falls back to it for any request where
Ollama fails or is unreachable.
