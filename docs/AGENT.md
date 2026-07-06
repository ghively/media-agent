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
  Ollama first,           58 tools across 12         strips <think> traces
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

## 3. Tool catalog (58 tools)

Risk legend: 🟢 read-only · 🟡 mutating (adds/changes state, reversible) ·
🔴 destructive or externally significant (renames files, spends
bandwidth/quota, touches accounts).

### TV — Sonarr
| Tool | Risk | Purpose |
|---|---|---|
| `search_tv` | 🟢 | Look up shows by name (returns tvdbIds) |
| `list_tv_shows` / `get_tv_queue` / `get_tv_history` / `get_tv_calendar` / `get_tv_health` | 🟢 | Library, queue, activity, schedule, health |
| `add_tv_show` | 🟡 | Add show to monitored library + start episode search |
| `search_missing_episodes` | 🟡 | Trigger indexer-wide search (heavy on indexers) |

### Movies — Radarr
| Tool | Risk | Purpose |
|---|---|---|
| `search_movie` | 🟢 | Look up movies (returns tmdbIds) |
| `list_movies` / `get_movie_queue` / `get_movie_history` / `get_movie_health` | 🟢 | Library, queue, activity, health |
| `add_movie` | 🟡 | Add movie + start search |
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
explicit user approval), or `deny` (disabled). The six 🔴 high-impact tools
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

Pending approvals expire after 15 minutes. The whole mechanism is covered
by tests (`tests/test_approvals.py`), including the model-cannot-self-approve
and changed-arguments cases.

Other standing safeguards: search-then-confirm prompt policy for adds, the
25-step recursion cap, `library_sort_dir` undo logs, and Bearer-token API
auth.

## 6. Bulletproofing roadmap — recommended next work

What exists is now functional end-to-end and tested. These are the additions
that would harden it further, roughly in order of value:

**Reliability**
1. *Persistent memory* — swap the CLI's `InMemorySaver` for the SQLite
   checkpointer (`langgraph-checkpoint-sqlite`, stored in `/state`) so
   conversations and **pending approvals** survive container restarts, and
   give the OpenAI API per-thread state the same way.
2. *Config doctor* — a `--doctor` startup command: ping every configured
   service, verify the Ollama model is pulled and `num_ctx` fits in RAM,
   and print a red/green table. Catches 90% of "the agent is broken"
   reports before they reach chat.
3. *HTTP retries with backoff* — one shared httpx client per service with
   2–3 retries on connect/5xx errors; home-lab services restart often.
4. *CI* — a GitHub Action running `pytest` on every push (the suite runs in
   under a second and needs no live services).

**Safety**
5. *Disk-space preflight* — `rom_download` and bulk downloads should call
   the disk-space check first and refuse (or ask) when free space < the
   estimated size + margin.
6. *Audit log* — append every mutating tool call (name, args, outcome,
   approval state) to `/state/audit.jsonl`; makes "what did the agent do
   while I was out" answerable.
7. *Prompt-injection hardening* — search results (torrent titles, YouTube
   descriptions) are untrusted text that flows into the model. Add a system
   prompt rule to never treat tool output as instructions, and length-cap
   what tools return.

**Capability / workflows**
8. *Notifications* — a Telegram interface (the bot library is already in
   the Docker image): scheduler alerts, "download finished", and approval
   prompts answerable from your phone. This is the natural companion to the
   approval gate.
9. *Quality profile & root-folder selection* — list Sonarr/Radarr profiles
   and let adds specify them (currently hardcoded to profile 1, `/tv/` and
   `/movies/`).
10. *Removal tools* — `remove_tv_show` / `remove_movie` (with `confirm`
    policy) so library management is symmetric.
11. *Weekly digest* — scheduler job that runs health + queue + recent adds
    and sends one summary notification.
12. *Duplicate/orphan workflow* — wire `scanner.cross_reference` /
    `find_orphans` into tools so "what's wasting space?" works end-to-end.
13. *Subtitles (Bazarr) and music (Lidarr/beets)* — same client+tools
    pattern as Sonarr/Radarr when those services join the stack.
14. *Model eval harness* — a canned 15-prompt script scored on tool-choice
    correctness, so Profile A/B comparisons are repeatable instead of
    vibes-based.
