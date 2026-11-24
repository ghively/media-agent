# Proof of concept: Media Agent on Open Intelligent UI

Branch `poc/openintelligentui`. The `master-public` branch and the running
container are untouched.

**Before:** you chat with media-agent in a plain-text panel, and it runs on
qwen3.5:9b through Ollama.

**After:** you chat in Open Intelligent UI (CopilotKit's Next.js chat) and a
cloud model (Claude by default, OpenAI optional) answers with visuals.
"What's downloading?" comes back as progress bars, "how full are my disks?"
as a bar chart and "are my services healthy?" as a status board. Adds and
downloads still wait for your yes, now as Approve and Decline buttons.

## What's in here

| Path | What it is |
| --- | --- |
| `oiui/` | Open Intelligent UI ([CopilotKit/OpenIntelligentUI](https://github.com/CopilotKit/OpenIntelligentUI), MIT, commit `8391a94`) |
| `oiui/apps/agent/oiui_agent/media_bridge.py` | Loads media-agent's tools, adds JSON data tools for charts, and enforces the approval gate |
| `oiui/apps/app/src/hooks/use-media-approval.tsx` | The Approve and Decline card |
| `src/`, `config/`, `dashboard/` | media-agent, unchanged |

How the pieces connect:

```text
Browser :3000 (Next.js, CopilotKit)
  → /api/copilotkit
  → agent :8123 (FastAPI + LangGraph deep agent, localhost only)
      cloud model (Claude or OpenAI)
      media-agent's 102 tools, imported from src/tools/registry.py
      + media_download_queue_data, media_disk_usage_data,
        media_service_health_data (same APIs, JSON out)
      approval gate (server side)
  → your Sonarr, Radarr, Emby, SABnzbd and other services,
    using config/settings.yaml and .env exactly as before
```

## Run it

You need Node 22+, pnpm 9+, Python 3.12+ and [uv](https://docs.astral.sh/uv/)
on a machine that can reach your media services, such as the GPU host.

```bash
git clone https://github.com/ghively/media-agent.git media-agent-poc
cd media-agent-poc
git checkout poc/openintelligentui

# Reuse your existing media-agent config and service keys
cp /path/to/your/media-agent/config/settings.yaml config/settings.yaml
cp /path/to/your/media-agent/.env .env

cd oiui
make setup                  # installs everything, creates the two env files
nano apps/agent/.env        # set ANTHROPIC_API_KEY=...
make dev                    # UI on :3000, agent on 127.0.0.1:8123
```

Open http://localhost:3000 and tap one of the starter questions.

If your `settings.yaml` uses Docker network names (like
`agent-lab-ollama-1`) for any service the PoC needs, swap them for IPs,
because this runs on the host and not inside the `agent-mesh` network.
Ollama isn't used here.

## Keys

| Key | Where | Needed? |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | `oiui/apps/agent/.env` | Yes, with the default `LLM_MODEL=claude-sonnet-5-5` |
| `OPENAI_API_KEY` | `oiui/apps/agent/.env` | Only if you set `LLM_MODEL=chat-latest` or `gpt-*` |
| `TYPESAFE_API_KEY` | `oiui/apps/agent/.env` | No. It turns on Jev routing, which sends the last few chat messages to TypeSafe |
| Sonarr, Radarr and other service keys | repo root `.env` | Yes, same as today |

Keys stay on the server. The browser never asks for them, because
`NEXT_PUBLIC_SERVER_KEYS=true` is set in `oiui/apps/app/.env.local`.

## What changed in behavior

- **Confirmations:** they're stronger than before. The agent server refuses
  every tool that adds, downloads, records, subscribes, unsubscribes,
  renames, approves or denies a request, or schedules cleanup, unless you
  clicked Approve for that exact tool and those exact arguments in the
  current turn. One click pays for one run. Bulk tools (`rom_download`,
  `bandcamp_download_collection`, `audible_download_new`,
  `library_fix_naming`) still preview freely; only the `confirm=true` run is
  gated. The list is `ALWAYS_GATED` and `GATED_WHEN_CONFIRMED` in
  `media_bridge.py`.
- **Fast path:** the new UI doesn't use it. Every message goes to the cloud
  model, which is what lets "what's downloading?" come back as a visual. The
  CLI, the Telegram bot and the old dashboard still use it, unchanged.
- **Jev:** off unless `TYPESAFE_API_KEY` is set. Without it, the model picks
  the visual itself, and nothing goes to TypeSafe.
- **Demo bits removed from the agent:** sample CSV, trip photos, the todo
  list, the login-form demo and the meeting picker. The native pie and bar
  chart components and the sandboxed generated UI stay.
- **Telemetry:** CopilotKit's anonymous install counter is turned off by
  `DO_NOT_TRACK=1` in `.env.local`.

## Safety notes

- The agent listens on 127.0.0.1 only. Next.js serves the UI on port 3000
  with no login, and anyone who can reach it can ask for downloads and click
  Approve. Keep it on your LAN or behind your reverse proxy with auth, and
  don't expose it to the internet.
- Chat history lives in the agent's memory and is lost on restart.

## Tests

```bash
cd oiui/apps/agent && uv run pytest -q      # agent: 123 tests, including the approval gate
cd oiui/apps/app && pnpm test               # UI: 167 tests, including the Approve card
cd oiui/apps/app && pnpm build              # production build
```

media-agent's own suite (`python -m pytest tests/ -q` at the repo root) is
untouched by this branch.
