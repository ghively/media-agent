# Media Agent — Architecture, Tools, Workflows & Approval Policy

This is the operator's reference for how the agent is put together, what it
can do, and which actions deserve human approval.

## 1. Architecture

```
                 ┌────────────────────────────────────────────────┐
   you ──────────►  Interfaces                                     │
                 │   • CLI REPL / one-shot   (src/interfaces/cli)  │
                 │   • OpenAI-compatible API (…/openai_api)        │
                 │     └ works with Open WebUI, etc.               │
                 │   • Web dashboard         (…/dashboard)         │
                 │   • Scheduler jobs        (src/scheduler)       │
                 └───────────────┬────────────────────────────────┘
                                 │ messages
                 ┌───────────────▼────────────────────────────────┐
                 │  Agent graph (src/graphs/conversational.py)    │
                 │  LangGraph create_react_agent:                 │
                 │    model turn → tool calls? ──yes──► run tools │
                 │        ▲                                │      │
                 │        └────── tool results ────────────┘      │
                 │    …loops until a tool-call-free answer,       │
                 │    bounded by recursion_limit (25)             │
                 └───────────────┬────────────────────────────────┘
                                 │
        ┌────────────────────────┼──────────────────────────┐
        ▼                        ▼                          ▼
  LLM routing             Tool registry              Post-processing
  (src/llm/client)        (src/tools/registry)       (src/llm/postprocess)
  Ollama first,           62 tools across 12         strips <think> traces
  hosted fallback         services (below)           and tool-call syntax
  via with_fallbacks                                 from every reply
```

Key behaviors:

- **Conversation memory.** The CLI keeps history via a LangGraph
  checkpointer (thread `cli`), so "add the second one" resolves against the
  previous search. The OpenAI API is stateless — the chat front-end resends
  full history each request, which the graph replays.
- **Output hygiene.** Chat streaming emits only final, tool-call-free agent
  messages; intermediate tool-calling turns are never streamed. All
  user-facing text additionally passes through `clean_response()`.
- **Loop safety.** Small models can get stuck re-calling tools; the graph
  stops at 25 agent↔tool round-trips and returns a readable error.

## 2. Model profiles

Both profiles are first-class and switchable from `.env` alone:

| | Profile A — non-thinking (default) | Profile B — thinking |
|---|---|---|
| Model | `qwen2.5:7b` (~4.7 GB) | `qwen3.5:9b` (~6.6 GB), or `qwen3.5:4b` (~3.4 GB) small |
| `OLLAMA_REASONING` | **must stay empty** (Ollama rejects the think flag) | `false` (suppress trace; leaks stripped in-app anyway) |
| Strengths | fastest first token, predictable | better tool selection & multi-step planning per size |
| Trade-off | weaker on ambiguous multi-step asks | thinks before answering → higher latency |

To switch (or A/B test):

```bash
# 1. Pull the model you want to test
ollama pull qwen3.5:9b

# 2. Edit .env
#    OLLAMA_MODEL=qwen3.5:9b
#    OLLAMA_REASONING=false

# 3. Restart the agent
docker compose up -d --force-recreate media-agent
```

A good comparison script for both profiles: "what's airing this week?",
"add the movie Heat", (ambiguous — two matches, should ask), "the 1995 one",
"check health and disk space". Watch for: correct tool choice, asking
before adding on ambiguity, no JSON/`<think>` fragments in replies, latency.

Keep `OLLAMA_NUM_CTX=16384` for either profile — below ~8k the tool schemas
get truncated by Ollama and tool calling degrades sharply.

## 3. Tool catalog (62 tools)

Risk legend: 🟢 read-only · 🟡 mutating (adds/changes state, reversible) ·
🔴 destructive or externally significant (renames files, spends
bandwidth/quota, touches accounts).

### TV — Sonarr
| Tool | Risk | Purpose |
|---|---|---|
| `search_tv` | 🟢 | Look up shows by name (returns tvdbIds) |
| `list_tv_shows` / `get_tv_queue` / `get_tv_history` / `get_tv_calendar` / `get_tv_health` | 🟢 | Library, queue, activity, schedule, health |
| `list_tv_profiles` | 🟢 | Quality profiles + root folders (with free space) |
| `add_tv_show` | 🟡 | Add show (dynamic quality profile + root folder) + start search |
| `remove_tv_show` | 🔴 | Remove show; optional file deletion (approval-gated) |
| `search_missing_episodes` | 🟡 | Trigger indexer-wide search (heavy on indexers) |

### Movies — Radarr
| Tool | Risk | Purpose |
|---|---|---|
| `search_movie` | 🟢 | Look up movies (returns tmdbIds) |
| `list_movies` / `get_movie_queue` / `get_movie_history` / `get_movie_health` | 🟢 | Library, queue, activity, health |
| `list_movie_profiles` | 🟢 | Quality profiles + root folders (with free space) |
| `add_movie` | 🟡 | Add movie (dynamic quality profile + root folder) + start search |
| `remove_movie` | 🔴 | Remove movie; optional file deletion (approval-gated) |
| `search_missing_movies` | 🟡 | Trigger indexer-wide search |

### Emby
| Tool | Risk | Purpose |
|---|---|---|
| `emby_search` / `emby_recent` / `emby_libraries` / `emby_get_item` | 🟢 | Search/browse the library |
| `emby_scan` | 🟡 | Trigger a library refresh |

### Health
`check_all_health`, `check_disk_space`, `check_queue_status` — all 🟢.

### Unified search
| Tool | Risk | Purpose |
|---|---|---|
| `search_media` | 🟢 | One search across Sonarr + Radarr + Download Station |
| `download_media` | 🟡 | Add result *N* from the last search to the right service |

### Download clients — SABnzbd / Download Station
| Tool | Risk | Purpose |
|---|---|---|
| `sabnzbd_queue` / `sabnzbd_history` / `sabnzbd_status` | 🟢 | Queue and server status |
| `download_station_list` / `_info` / `_stats` | 🟢 | Task list and server info |
| `sabnzbd_pause` / `sabnzbd_resume`, `download_station_pause` / `_resume` | 🟡 | Pause/resume downloads |
| `sabnzbd_add_nzb`, `download_station_add` | 🔴 | Download arbitrary URLs handed to the agent |

### Music — Bandcamp
| Tool | Risk | Purpose |
|---|---|---|
| `bandcamp_download` | 🟡 | Download one album/track you own |
| `bandcamp_download_collection` | 🔴 | Bulk-download the entire purchased collection |

### Audiobooks — Audible
| Tool | Risk | Purpose |
|---|---|---|
| `audible_list_library` / `audible_check_auth` | 🟢 | Library and auth status |
| `audible_setup_auth` | 🟢 | Prints manual auth instructions (no action) |
| `audible_download` | 🟡 | Download + decrypt one book (uses account) |
| `audible_download_new` | 🔴 | Bulk-download everything new since last sync |

### ROMs — Internet Archive
| Tool | Risk | Purpose |
|---|---|---|
| `rom_search_archive` / `rom_get_collection` / `rom_verify_dat` | 🟢 | Search, list, verify checksums |
| `rom_download` | 🔴 | ROM *sets* are often tens–hundreds of GB |

### YouTube
| Tool | Risk | Purpose |
|---|---|---|
| `youtube_get_info` / `youtube_list_subscriptions` | 🟢 | Metadata, subscription list |
| `youtube_download` / `youtube_add_subscription` / `youtube_remove_subscription` / `youtube_check_subscriptions` | 🟡 | Download videos, manage channel monitoring |

### Library organization
| Tool | Risk | Purpose |
|---|---|---|
| `library_inventory` / `library_check_naming` | 🟢 | Summarize and validate a directory (no changes) |
| `library_sort_dir` | 🔴 | **Mass-renames files** to the naming convention (writes an undo log) |
| `library_undo_rename` | 🟡 | Roll back a `library_sort_dir` run from its undo log |

## 4. Built-in workflows

These flows are encoded in the system prompt plus tool design; the model
chains them, the graph executes them:

1. **Add media** — `search_tv`/`search_movie` → one clear match: add and
   confirm; multiple matches: list them and *ask the user* → `add_tv_show` /
   `add_movie` (which also kicks off the episode/movie search).
2. **Unified search & grab** — `search_media` (all sources, ranked, cached)
   → user picks a number → `download_media(N)` dispatches to the right
   service.
3. **Download → organize** — provider download (Bandcamp/Audible/ROM/
   YouTube) → agent offers `library_sort_dir` on the download folder →
   `library_check_naming` to verify → `library_undo_rename` if it went wrong.
4. **Health monitoring** — `check_all_health` / `check_disk_space` /
   `check_queue_status`, also available headless via `--health` and as
   scheduler job templates (`health_check` every 30 min, `missing_episodes`
   every 12 h, daily cleanup, weekly scan) when `scheduler.enabled: true`.
5. **Subscriptions** — `youtube_add_subscription` → periodic
   `youtube_check_subscriptions` (manual or scheduled) → downloads new
   uploads.

## 5. Approval policy — implemented

Every tool has a policy: `auto` (run immediately), `confirm` (require
explicit user approval), or `deny` (disabled). The eight 🔴 high-impact tools
default to `confirm`; everything else defaults to `auto`. Override any tool
in settings.yaml:

```yaml
approvals:
  rom_download: auto            # trust ROM downloads without asking
  emby_scan: confirm            # gate extra tools if you like
  download_station_add: deny    # disable a tool entirely
```

**The `confirm` gate is enforced in code, not by the model**
(`src/tools/approval.py`). A gated tool executes only when both hold:

1. the same tool **with the same arguments** was already requested earlier
   in the conversation, and
2. **your actual latest message** contains an explicit approval
   ("yes", "approve", "go ahead", …). A negation ("no, don't") always wins
   and clears the request; changed arguments require a fresh approval.

The model cannot self-approve: without a matching user approval the tool
returns `⏸️ APPROVAL REQUIRED` (nothing executes) and the agent relays the
question. The flow in chat:

```
you>  organize /media/music
agent ⏸️ library_sort_dir will rename files under /media/music to the
      music convention (undo log written). Proceed?  [yes/no]
you>  yes
agent ✅ Renamed 214 files. Undo log: /media/music/.media_agent_undo/…
```

The eight confirm-by-default tools: `library_sort_dir`, `rom_download`,
`bandcamp_download_collection`, `audible_download_new`, `sabnzbd_add_nzb`,
`download_station_add`, `remove_tv_show`, `remove_movie`.

Pending approvals expire after 15 minutes and are mirrored to
`<state>/pending_approvals.json`, so a container restart doesn't drop an
approval mid-flow. The whole mechanism is covered by tests
(`tests/test_approvals.py`), including the model-cannot-self-approve and
changed-arguments cases.

Other standing safeguards: search-then-confirm prompt policy for adds, the
25-step recursion cap, `library_sort_dir` undo logs, Bearer-token API auth,
an audit log of every mutating call (`<state>/audit.jsonl`), tool output
length caps, disk-space preflight on bulk downloads, and a prompt rule that
tool output is data, never instructions.

## 6. Hardening — implemented

Everything from the original bulletproofing roadmap that is now built:

- **Persistent memory** — the CLI uses the SQLite checkpointer
  (`<state>/checkpoints.db`); conversations survive restarts, `new` starts
  a fresh thread, and pending approvals persist to disk.
- **Config doctor** — `python -m src.main --doctor` checks config, state
  dir, Ollama (model pulled, `num_ctx` floor), Sonarr/Radarr/Emby/SABnzbd/
  Download Station reachability + auth, fallback LLM, and Telegram; prints
  a red/green table and exits non-zero on core failures.
- **HTTP retries** — Sonarr/Radarr/Emby clients retry connects (×2).
- **CI** — `.github/workflows/ci.yml` runs the suite on py3.11/3.12.
- **Disk-space preflight** — `rom_download` (with size estimate from IA
  metadata), `bandcamp_download_collection`, `audible_download_new`,
  `youtube_download` refuse when free space would drop below
  `library.min_free_gb`.
- **Audit log + output caps + injection rule** — see §5.
- **Telegram notifications** — health alerts (on state change only) and the
  weekly digest push via `notifications.telegram_*` settings.
- **Scheduler jobs** — `health`, `missing`, `digest` wired from
  `scheduler.jobs` config into APScheduler on server startup.
- **Quality profile & root-folder selection** — adds resolve profiles and
  folders dynamically from the live instance (hardcoded `profile 1` /
  `/tv/` / `/movies/` used to 400 on most installs); `list_tv_profiles` /
  `list_movie_profiles` expose the choices.
- **Removal tools** — `remove_tv_show` / `remove_movie`, approval-gated.
- **Weekly digest** — health + queues + disk + recent adds in one push.
- **Model eval harness** — `scripts/model_eval.py` (latency, hygiene-leak,
  and error counts per canned prompt; one JSON report per model profile).
- **Message trimming** — conversation history is capped at 60 messages
  before each model call so long threads can't overflow `num_ctx`.

### Verified integrations (July 2026 API audit)

Every service call was audited against current upstream docs/source. Fixed
as a result: Sonarr's command name (`MissingEpisodeSearch`, singular — the
old name never triggered anything), history/calendar embed params
(`includeSeries`/`includeMovie` — items showed "Unknown" without them),
Emby user-scoped routes (`/Users/{id}/Items/Latest` and `/Users/{id}/Items/{id}` —
the user-less forms don't exist), SABnzbd `server_stats` semantics
(historical bandwidth, not live server state), Synology credential
percent-encoding + 2FA error surfacing, audible-cli's real interface
(profile-based auth via `AUDIBLE_CONFIG_DIR`; `library export --format
json`; ffmpeg voucher decryption — there is no `--auth-file` flag and no
built-in `decrypt` command), bandcamp-dl's real flags (`--base-dir`,
`%{...}` templates; collections need the separate easlice tool), yt-dlp
flag dedup + `approximate_date` for subscription checks + ffmpeg presence
check, and internetarchive 5.x (`fields=` on search, `silent=` removed).

### LangChain/LangGraph posture (July 2026 review)

- `create_react_agent` is deprecated in LangGraph v1 (removed in v2). The
  replacement (`langchain.agents.create_agent`) **cannot yet express our
  Ollama→hosted fallback** (`RunnableWithFallbacks` unsupported — tracked
  upstream in langchain#33129), so we deliberately stay on
  `create_react_agent` with `langgraph <2` pinned. Revisit when the issue
  closes.
- The `InjectedState` approval gate is the sanctioned pattern for our
  dual stateful-CLI/stateless-API architecture; LangGraph's `interrupt()` /
  `HumanInTheLoopMiddleware` require per-thread persistence the OpenAI API
  doesn't have.
- Message-level streaming (`stream_mode="updates"`) is a deliberate
  correctness choice over token-level `stream_mode="messages"`, which would
  re-open think-tag leakage for thinking models mid-stream.

## 7. Remaining roadmap

- *Two-way Telegram* — answering approval prompts from your phone (needs a
  polling bot loop mapped into conversation threads).
- *Per-thread API memory* — optional thread ids on the OpenAI API so
  interrupt-based HITL and server-side history become possible.
- *Duplicate/orphan workflow* — wire `scanner.cross_reference` /
  `find_orphans` into tools so "what's wasting space?" works end-to-end.
- *Subtitles (Bazarr) and music (Lidarr/beets)* — same client+tools pattern
  as Sonarr/Radarr when those services join the stack.
- *Token-level streaming for Profile A* — typing effect for non-thinking
  models via `stream_mode="messages"` with tool-call-chunk filtering.
- *`create_agent` migration* — once upstream supports model fallbacks.
