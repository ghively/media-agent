# Workflow Map

Every supported workflow, what runs it, and which steps are deterministic
code versus LLM calls. Design rule: **the LLM only does what code can't —
parse intent, present choices, summarize.** Everything else (searching,
deciding on clear matches, acting, verifying) is deterministic Python.

## Why this shape (small local models)

A qwen-class 9B model degrades with many bound tools and long prompts, and
every extra ReAct round costs a full prompt re-read. Three mechanisms keep
quality up and tokens down:

1. **Domain routing** (`src/graphs/router.py`) — keyword scoring, zero LLM
   tokens, picks a per-domain agent that binds only 4–13 tools instead of
   ~60. Ambiguity falls back to the `core` agent, whose workflow tools
   cover cross-domain asks.
2. **Workflow pipelines** (`src/workflows/pipelines.py`) — one tool call
   runs search → decide → act → verify in code. A "add Severance" request
   is 1 LLM round instead of 3–4.
3. **Verification before claiming done** — every mutating step reads back
   the resulting state before reporting `✅ Verified`. The system prompt
   forbids claiming success without a ✅ in tool output; `⚠️`/`❌` mean
   not-done and are reported as such.

Token budget mechanics: Ollama `num_ctx` is raised to 8192 (the 2048
default silently truncates tool-bound prompts), `num_predict` caps output
per step, `recursion_limit` bounds ReAct loops, and the REPL keeps only
user turns + final answers in history (tool chatter is dropped).

## Conversational workflows (LLM in the loop)

| Ask | Track | LLM's role | Deterministic parts |
|---|---|---|---|
| "add Severance" | `core` → `grab_media` | pick tool, relay result | search Sonarr+Radarr, rank, auto-add if decisive (score ≥80 & margin ≥20), verify via read-back |
| ambiguous match | `grab_media` → numbered options → user picks → `download_media(n)` | present options, ask | option cache, dispatch to verified add |
| "what's downloading?" | `downloads` domain → queue tools | pick tool, summarize | queue/status API calls |
| "is everything healthy?" | `system` domain → `system_report` | relay | concurrent health+queues+disk probes |
| "clean up my TV folder" | `library` domain → `library_cleanup` | pick path/convention | check → fix → re-check verify, undo log |
| "rename went wrong" | `library_undo_rename` | pick undo log from prior output | replay undo log in reverse |
| "find duplicates" | `library_find_duplicates` | relay | size+hash scan |
| "download this YouTube video" | `youtube` domain → `youtube_download` | extract URL/type | yt-dlp download, file-on-disk verification |
| "subscribe to channel X" | `youtube_add_subscription` | extract URL | channel resolution, dedupe, persist |
| "get my new audiobooks" | `audio` domain → `audible_download_new` | relay | state-file diff, download, only successes marked done |
| "grab this Bandcamp album" | `bandcamp_download` | extract URL | bandcamp-dl, file count verification |
| "find SNES ROM sets" | `roms` domain → `rom_search_archive` → `rom_download` → `rom_verify_dat` | pick identifier | archive search, download, DAT checksum verify |
| "what aired this week?" | `get_tv_calendar` | relay | calendar API |
| "search for missing stuff" | `search_missing_episodes` / `trigger_missing_searches` | pick | command POST |

## Scheduled workflows (no LLM at all)

Configured in `settings.yaml` under `scheduler:`; each fires a pipeline
directly on the server event loop:

| Job | Default cadence | Pipeline |
|---|---|---|
| `health_check` | 30 min | `system_report` — health, queues, disk |
| `missing_search` | 12 h | `trigger_missing_searches` — Sonarr + Radarr wanted-content search |
| `youtube_sync` | 6 h | `sync_youtube` — check subscriptions, download new uploads (verified on disk before state advances; first check only sets a baseline, no backfill) |
| `audible_sync` | daily 4:00 | `audible_download_new` — download new library additions |

Any job accepts a custom cron via `trigger: "min hour dom mon dow"`.

## Verification contract

Every mutating action verifies before reporting:

- **Sonarr/Radarr add** → POST, then GET the library and confirm the
  tvdbId/tmdbId is present (also converts a 400 "already exists" into a
  verified ℹ️ instead of a false failure).
- **YouTube download** → yt-dlp's reported path is checked on disk; size
  reported. `sync_youtube` only advances a channel's `last_upload` marker
  after a verified download, so failures retry next run.
- **Library fix** → `library_cleanup` re-scans after renaming and reports
  remaining issues; every batch has an undo log.
- **Audible sync** → only exit-code-0 downloads are recorded as done.

Output symbols are a contract the prompt enforces: `✅ Verified` = state
confirmed, `ℹ️` = no-op (already true), `⚠️` = attempted but unconfirmed,
`❌` = failed. The agent must not claim completion without ✅.

## Domain → toolset map

See `DOMAIN_TOOLS` in `src/graphs/conversational.py`:

- `core` (fallback): grab_media, search_media, download_media,
  system_report, sync_youtube, library_cleanup, check_queue_status
- `tv` / `movies`: the Sonarr / Radarr toolsets + grab_media
- `library`: naming/duplicate/inventory tools + Emby
- `downloads`: SABnzbd + Download Station + queue status
- `audio`: Bandcamp + Audible
- `youtube`: downloads + subscriptions + sync
- `roms`: Internet Archive + DAT verification
- `system`: health/disk/queues/report

API clients can force a domain with the model name `media-agent:<domain>`
(e.g. `media-agent:tv`); otherwise routing is automatic per request.
