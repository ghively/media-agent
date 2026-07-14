# Media Agent — Code Audit Findings

## 2026-07-14 — Production-readiness & feature-gap audit (frontend + LangGraph agent)

Full audit of production readiness and feature gaps across the web
dashboard / API interfaces and the LangGraph agent runtime, including
tuning for the stated purpose (a 9B local model managing a personal media
ecosystem through 70 tools). Every finding below was verified against the
code at the referenced location.

> **✅ Fix pass (same day):** every finding below — C1–C2, H1–H5, M1–M16,
> and the Low list — was fixed in the follow-up commits on this branch and
> verified (188/188 tests pass; server boots with auth + per-session chat +
> SQLite memory exercised live; React dashboard builds). Of the feature
> gaps: #1 (dashboard auth), #2 (media volume), #3 (webhook notifications),
> #5 (persistent memory), #7 (per-session threads), and #8 (tool audit log)
> shipped with the fixes. Still open: yes/no confirmation *buttons* (#4 —
> typed yes/no still, but a "New conversation" reset button was added),
> pagination params (#6 — output caps added instead), and the roadmap
> items in #9. Line numbers in the findings refer to the pre-fix tree.

### Verdict in one paragraph

The architecture is sound and previous hardening passes were real (router
fast path, argument-injection guards, non-root container, loopback bind,
constant-time auth compare, rename undo logs). But the system is **not
production-ready as deployed** for its core purpose: downloaded media
lands in unmounted container paths and vanishes on restart (C2), and
turning on the *documented, recommended* API key bricks the entire
dashboard because no frontend ever sends the Authorization header (C1).
On the agent side, the biggest risks are context-budget overflow on the
8k-token window (H4), no timeout on LLM calls (H5), and irreversible
tools that rely on prompt-level confirmation only (H3).

### Critical

| # | Finding | Location |
|---|---------|----------|
| C1 | **Setting `MEDIA_AGENT_API_KEY` (documented as "Recommended") breaks the whole dashboard.** `/api/dashboard/data` and `/api/dashboard/chat` enforce `_check_auth` (`src/interfaces/dashboard.py:64,76`), but neither frontend can supply a credential: the React client sends no `Authorization` header (`dashboard/src/api/client.js:4,10,25`) and neither does the inline-HTML fallback (`fetch("/api/dashboard/data")`, `dashboard.py:910`; chat POST, `dashboard.py:950`). There is no login UI, token field, or cookie session. With the key set, every data poll and chat message 401s; with it unset, auth is off entirely. docs/api-reference.md:142-155 documents Bearer auth on these routes as if it worked. | `src/interfaces/dashboard.py`, `dashboard/src/api/client.js` |
| C2 | **The acquire→library pipeline writes to paths that don't exist outside the container.** docker-compose.yml mounts only `./config:/app/config` and `agent-state:/state` — no media volume. But bandcamp stages to `/tmp/bandcamp/...` (`src/providers/bandcamp.py:17`), Audible to `/tmp/audible_downloads` (`audible.py:14`), ROMs to `/tmp/rom_downloads` with library at `/media/roms` (`rom.py:17-18`). Downloads land in the ephemeral container layer and vanish on restart — while each provider auto-triggers an Emby scan (`bandcamp.py:36`, `audible.py:105,184`, `rom.py:214`, `youtube.py:163`) on a library that never received the files. The core "download it for me" flow is non-functional as deployed. (Known partially: NFS mount is on the roadmap — but the tools present themselves to the user as working today.) | `docker-compose.yml`, `src/providers/*` |

### High

| # | Finding | Location |
|---|---------|----------|
| H1 | **SABnzbd API key leaks into LLM context, chat replies, and logs.** The key travels in the query string (`sabnzbd.py:24,39`); any HTTP error raises `httpx.HTTPStatusError` whose message embeds the full URL including `apikey=<SECRET>`, and every handler returns `{e}` verbatim (`sabnzbd.py:147,197,269,283,297,320`). Sonarr/Radarr/Emby correctly use headers. Fix: move key out of the query (SABnzbd accepts header auth on modern versions) or scrub URLs from error strings. | `src/tools/sabnzbd.py` |
| H2 | **Audible auth is written to `/config/audible/` — an unmounted path.** Compose mounts host config at `/app/config`, not `/config`. `audible_setup_auth` explicitly promises the auth file "will persist … and survive container restarts" (`audible.py:206`); it will not. Every restart silently de-authenticates Audible and requires the interactive OAuth flow again. | `src/providers/audible.py:12-14` |
| H3 | **Irreversible/bulk tools have no tool-level confirmation — only the router path confirms.** The deterministic router gates renames and bulk downloads behind yes/no, but the LangGraph agent can call `library_fix_naming` (mass `os.rename`, `library_tools.py:94`), `bandcamp_download_collection`, `audible_download_new`, and `rom_download` (multi-GB) directly. The only guard on the LLM path is the SYSTEM_PROMPT's confirmation rule — prompt-level guidance a 9B model can and will occasionally skip. The rename undo log is the sole backstop. Fix: require an explicit `confirm=True` parameter (defaulting to a dry-run preview) on destructive tools. | `src/tools/library_tools.py`, providers |
| H4 | **Context budget almost certainly overflows `num_ctx=8192` on real threads.** The model is bound to 70 tool schemas (~4–8k tokens serialized as JSON), plus a ~900-token system prompt, plus up to `MAX_HISTORY_MESSAGES = 40` messages (`conversational.py:39`) *including unbounded tool returns*: `list_tv_shows` iterates every series with no cap (`sonarr.py:87`; contrast `list_movies` which caps at 30), and `download_station_list` is uncapped (`download_station.py:183`). When the prompt exceeds `num_ctx`, Ollama silently truncates from the top — dropping the system prompt and tool definitions first, which degrades tool-calling into junk exactly on the long-lived dashboard thread. Fix: raise `num_ctx` to 16384 (fits a q4 9B + KV cache in 12 GB VRAM), cut `MAX_HISTORY_MESSAGES` to ~16–20, and cap every list tool's output. | `src/llm/client.py:27`, `src/graphs/conversational.py:39`, `src/tools/sonarr.py:87` |
| H5 | **No timeout on any LLM call.** `config/settings.yaml.example` documents `llm.timeout: 15`, but nothing reads it — `ChatOllama` and the `ChatOpenAI` fallback are constructed with no timeout (`src/llm/client.py:40-60`). A hung (not refused) Ollama connection stalls a turn indefinitely; the circuit breaker only counts *completed* failures, so hangs never trip it. Wire `llm.timeout` into both clients. | `src/llm/client.py` |

### Medium — agent runtime & tuning

| # | Finding | Location |
|---|---------|----------|
| M1 | **70 tools is past the reliable tool-selection budget for a 9B model**, and the overlap makes it worse: `check_queue_status`, `get_tv_queue`, `get_movie_queue`, `sabnzbd_queue`, and `download_station_list` all describe "download queue/tasks" in one terse docstring line with no when-to-use guidance; `emby_scan` / `emby_recent` / `refresh_*` share vocabulary similarly. The router hides this on common phrasings, but LLM-path accuracy suffers. Fix: differentiate docstrings ("use when the user asks about X, not Y") and/or bind a domain-relevant subset per turn. | `src/tools/*` docstrings |
| M2 | **Router confirmations are dead ends on the stateless OpenAI API.** Each `/v1/chat/completions` request gets a throwaway `thread_id` that is forgotten afterwards (`openai_api.py:68,79`), but pending confirmations are keyed by thread (`router.py:64`). The router asks "yes/no", the user's "yes" arrives on a fresh thread, the pending entry is unreachable, and the message falls to the LLM to re-derive intent from replayed history. Degraded, confusing UX for Open WebUI clients. Fix: derive a stable thread key from the client (e.g. hash of history head) or skip confirmation-generating intents on the stateless path. | `src/interfaces/openai_api.py`, `src/graphs/router.py` |
| M3 | **`stream_agent` has no hosted-model retry and can end truncated without an error.** `run_agent` retries once on the fallback agent (`conversational.py:272-277`); the streaming path doesn't, and when a stream dies after partial tokens it yields nothing further (`streamed_any` guard, `conversational.py:311`) — the dashboard shows a silently cut-off reply. | `src/graphs/conversational.py:281-312` |
| M4 | **Breaker records success even when the request was actually served by the per-call fallback.** `local_bound.with_fallbacks([fallback_bound])` can serve a turn via the hosted model while `run_agent` calls `record_success()` on the local breaker (`conversational.py:262-263`) — the breaker can stay CLOSED while Ollama is dead, so every turn pays the local timeout first. | `src/graphs/conversational.py` |
| M5 | **Conversation memory is RAM-only and grows without bound.** `MemorySaver` checkpoints accumulate every message forever on persistent threads ("dashboard", CLI) — `_trim_history` trims only what is *sent to the model*, not what is stored — and all of it is lost on restart. Fix: switch to `SqliteSaver` persisted under `/state` and add periodic thread truncation. | `src/graphs/conversational.py:30` |
| M6 | **All dashboard clients share one conversation and one confirmation slot.** `thread_id = "dashboard"` is hardcoded (`dashboard.py:81`), so two browsers/tabs interleave context, and a pending "rename files? yes/no" raised in one tab can be confirmed from another. There is also no way to reset the thread from the UI — a poisoned context persists until container restart. | `src/interfaces/dashboard.py:81` |
| M7 | **No date/time grounding in the system prompt.** Calendar-flavored questions that miss the router ("what's on next Tuesday?") reach a model that doesn't know today's date. Add the current date to the prompt hook (it's already a function — `_build_prompt`). | `src/graphs/conversational.py:137` |
| M8 | **Scheduler output goes nowhere a human looks.** Health checks, the 3 a.m. "daily report", and missing-media searches only write container logs (`main.py:64-93`). There is no notification channel (Telegram is roadmapped; `python-telegram-bot` is installed in the image but unused). The scheduler's monitoring value is close to zero until results are pushed somewhere. | `src/main.py`, `src/scheduler.py` |
| M9 | **No request observability or tool audit trail.** No structured log of which tools ran with which arguments (this agent renames files and starts multi-GB downloads), no `/metrics`, no request IDs; OpenAI responses hardcode `usage` to zeros and ignore `temperature`/`model` params (`openai_api.py:108`). | `src/interfaces/openai_api.py` |
| M10 | **Config is unvalidated at startup.** Unset `${VAR}` becomes `""` (`config.py:16`) — the right call for the auth key, but service API keys silently become empty strings that surface later as confusing 401s from Sonarr/Radarr instead of a clear startup error. `.env.example` also defines `SONARR_URL`/`RADARR_URL`/etc. that nothing substitutes (settings.yaml.example hardcodes URLs) — dead knobs that mislead deployment. Add a startup validation pass that names each missing key. | `src/config.py`, `.env.example` |

### Medium — tools & infrastructure

| # | Finding | Location |
|---|---------|----------|
| M11 | Three providers hardcode paths instead of using `get_settings()` (commandment 5): `audible.py:12-14`, `bandcamp.py:17`, `rom.py:17-18`. Worse, provider ROM tools use `/media/roms` while `rom_tools.py` reads `settings.roms` — the two tool families operate on **different directories** whenever `roms.download_path` is customized. | `src/providers/*` |
| M12 | `emby_get_item` interpolates an LLM-supplied ID into the URL path unencoded (`emby.py:136`) — `item_id="../System/Info"` reaches other Emby endpoints. Validate as numeric/alphanumeric. | `src/tools/emby.py:136` |
| M13 | Test coverage is router + ROM engine only. Untested: all API-backed tool bodies (response parsing/error mapping), `naming.py` rename/undo (the riskiest file-mutation code), `scanner.py`, subprocess command construction in all four providers, `config.py` substitution, `library_tools._confine` escape rejection. Registry smoke test asserts only `>= 40` tools (`test_conversational.py:77`), so silently dropping an optional group of tools wouldn't fail CI. | `tests/` |
| M14 | Dependencies are floating (`>=` everywhere in requirements.txt) and the Dockerfile's extra `pip install` block (yt-dlp, audible-cli, internetarchive, …) is fully unpinned — builds are non-reproducible and a yt-dlp/langchain upgrade can silently break a rebuild. `apscheduler`/`jinja2` are installed twice. | `requirements.txt`, `Dockerfile` |
| M15 | No container resource limits and no log rotation in compose; ROM verification reads whole files into memory (`rom.py:119-120`, 100-file cap only). Multi-GB downloads + no `mem_limit`/`logging:` config = host-level risk on the shared GPU box. | `docker-compose.yml` |
| M16 | Dashboard polling is expensive: every open tab triggers ~10 upstream HTTP calls **plus a full recursive file count of the ROM library** (`dashboard.py:407`, potentially over NFS) every 30 s, with no server-side cache or request coalescing. | `src/interfaces/dashboard.py` |

### Low

- `_h_add`'s catch-all (`^(?:add|download|grab|get) (.+)$`, `router.py:1184-1187`) can hijack phrasings like "get the tv calendar" (verb missing from the calendar patterns) into a Sonarr/Radarr title search. A stoplist of known nouns (calendar, queue, history, …) before the catch-all would tighten it.
- Chat input length is unbounded on the agent path (router caps at 300 chars; the LLM path takes anything a client pastes straight into an 8k context).
- No SSE keepalive on chat streams — multi-minute local-LLM turns behind a reverse proxy risk idle timeouts.
- `@app.on_event("startup")` (`main.py:97`) is deprecated in current FastAPI; migrate to lifespan handlers before an upgrade breaks it.
- Two dashboard frontends are maintained in parallel (React app + inline-HTML fallback in `dashboard.py`) and have already drifted (different quick-action sets); the inline fallback's `badge()` has dead code.
- After a page reload the React chat shows a fresh greeting while the server-side "dashboard" thread still remembers everything — the UI and agent memory disagree.
- `youtube_download` computes `fmt = "bestaudio/best"` then ignores it, hardcoding `-f bestaudio` (`youtube.py:122,140`); `--embed-metadata`/`--add-metadata` are redundant aliases.
- Download Station logout puts the SID in the query string (`download_station.py:105-113`) — short-lived token in access logs.
- `scanner.py` `cross_reference` (`:73`) and `find_orphans` (`:105`) return canned instructional text rather than doing the analysis — unregistered, but misleading scaffolding.
- Disk-space card sources SABnzbd only; if SABnzbd is down or absent the dashboard shows no disk info even though `check_disk_space` aggregates more sources.

### Feature gaps vs. intended purpose

1. **Frontend auth story** — token input + persisted credential (C1 is the bug; this is the feature).
2. **Media volume + configurable download roots** — the enabler for C2/M11; one compose volume block + wiring providers to `get_settings()`.
3. **Notifications** — Telegram bot (library already in the image) or ntfy/webhook, so scheduler findings and long-running download completions reach a human (M8).
4. **Confirmation UX in the dashboard** — yes/no buttons when the router/agent asks, instead of requiring typed "yes"; plus a "new conversation" button (M6).
5. **Persistent conversation memory** — SqliteSaver on `/state` (M5).
6. **Pagination** — list/history tools expose no page/offset; the agent can only ever see the first N items of a large library.
7. **Per-session dashboard threads** — session cookie → thread_id, enabling multi-device use without context bleed.
8. **Tool-call audit log** — append-only JSONL under `/state` of every tool invocation with args and outcome (M9); cheap and high-value for an agent that mutates a 90 TB library.
9. **Roadmap items still open** (from CLAUDE.md, confirmed absent): Telegram interface, Prowlarr/qBittorrent unified search, Lidarr, NFS mount, podcast/Twitch/comic/ebook providers.

### What is already solid (verified)

- Router-first architecture: ~45 intent groups, conservative patterns, never raises, confirmation flow with TTL-bounded pending table, deictic-reference guard; 169 tests pass.
- Argument-injection hardening (`--` guards before user URLs in yt-dlp/bandcamp-dl), no `shell=True`, no blocking subprocess, timeouts on all subprocess and HTTP calls.
- Container: non-root user, HEALTHCHECK, loopback-only port bind, external state volume.
- Auth: constant-time key comparison; empty-key-means-no-auth failure mode is at least documented.
- Rename operations write undo logs first; ROM/library tools confine paths (rom_tools confinement is test-covered).
- History trimming never orphans tool-call/result pairs; recursion overruns and LLM outages degrade to friendly messages.

### Suggested fix order

1. C2 + M11 — mount a media volume, make provider paths configurable (unblocks the core purpose).
2. C1 — dashboard credential support (token field storing to localStorage is enough for a homelab).
3. H1 — stop leaking the SABnzbd key.
4. H4 + H5 — `num_ctx` 16k, history 16–20, cap list tools, wire `llm.timeout`.
5. H2 — move Audible auth under `/state` or `/app/config`.
6. H3 — `confirm` parameter on destructive tools.
7. M5/M6 — SqliteSaver + per-session threads + reset endpoint.
8. M8 + feature gap 3 — notifications; the scheduler is running blind today.

---

## 2026-07-12 — Deployment-readiness verification pass

Independent re-verification ahead of deploying to a new box. Functional
state confirmed by execution, not just reading: **169/169 tests pass, all
28 source modules import, the registry loads 70 tools (no duplicate
names), `--serve` boots the API + scheduler (4 jobs), `/health` returns
200, the deterministic router answers "what's downloading?" with no LLM,
and the agent path degrades to a friendly error when Ollama is
unreachable.** Local-only LLM operation verified: with no hosted fallback
configured the circuit breaker always returns the local model — no crash.

New findings fixed in this pass:

| Severity | Finding | Fix |
|---|---|---|
| 🟠 Med | Unset `${VAR}` in settings.yaml was left as a literal string, so an unset `MEDIA_AGENT_API_KEY` **enabled** auth with the publicly-known literal `${MEDIA_AGENT_API_KEY}` as the accepted Bearer token (verified live) — contradicting the documented "no key = no auth" | `_substitute_env` now substitutes unset vars with `""` (`src/config.py`) |
| 🟠 Med | Fresh-box blockers undocumented: compose requires the pre-existing external `agent-lab_agent-mesh` network; default `llm.ollama_url` points at a homelab-only hostname; `/media` is never mounted by compose | New-box checklist + `llm.ollama_url` step added to `docs/deployment-guide.md` |
| 🟡 Low | tool-reference.md: "Unregistered Source Functions" section was false (all 5 listed tools ARE registered); `download_media` documented with a nonexistent `result_id` signature; 7 registered sonarr/radarr tools had no entries; `DS_USER`/`DS_PASS` (real names: `DS_USERNAME`/`DS_PASSWORD`); phantom `library_sort_dir` tool; wrong `sabnzbd_add_nzb` default; radarr port 7878 vs the standardized 8310 | All corrected |
| 🟡 Low | README self-contradiction: "70 tools" in prose but "66 Tools" header and breakdowns omitting the 4 `rom_tools.py` tools; ARCHITECTURE said youtube provider has 4 tools (has 6), described daily cleanup as deleting `.tmp`/`.part` files (it is a read-only health report), omitted the weekly Emby scan job, and carried a stale "download_station is not a property" note; development-guide quoted the pre-rewrite SYSTEM_PROMPT (tool-name lists were deliberately removed in `72478a4`); docs/README line/file counts stale | All corrected |
| 🟡 Low | Dashboard read `roms.library_dir` (example config defines `download_path`); example config advertised `audible.auth_file`/`download_path` keys the provider never reads (it uses fixed paths) | Dashboard accepts both keys; example config now states the real fixed paths |
| ⬜ Note | Open WebUI instructions said to connect from another host to `http://your-gpu-host:8088/v1`, unreachable through the loopback-only port bind | Guide corrected (same host / shared network / reverse proxy) |


Full-tree audit of the repository (~5,400 lines), **2026-07-11**. Each finding
was verified against the actual code (file:line quoted) and, where a fix was
applied, re-verified after the change.

> This record supersedes the original 2026-07-05 audit. The earlier snapshot is
> retired: several of its "won't fix" decisions (notably the intentionally-open
> dashboard) were revisited and hardened in this pass. The state below is
> current.

## Severity summary

| # | Severity | Finding | Location | Status |
|---|----------|---------|----------|--------|
| 1 | 🔴 High | Argument injection → command execution: LLM/user-controlled URL appended to yt-dlp/bandcamp-dl argv with no `--`, so `--exec=<cmd>` runs a shell command | `youtube.py`, `bandcamp.py` | ✅ Fixed |
| 2 | 🔴 High | Dashboard data/chat routes had no authentication — full agent control for anyone who can reach the port | `dashboard.py` | ✅ Fixed |
| 3 | 🔴 High | Published container port bound to `0.0.0.0` (whole LAN), contradicting the documented localhost-only design | `docker-compose.yml` | ✅ Fixed |
| 4 | 🟠 Med | Download Station credentials sent in the URL query string (leak into logs) in the unified-search path | `search.py` | ✅ Fixed |
| 5 | 🟠 Med | Library filesystem tools accepted an arbitrary `path` — enumerate/hash/rename anywhere the container could reach | `library_tools.py` | ✅ Fixed |
| 6 | 🔴 High | `await rom_verify_dat(platform)` awaited a `@tool` object (always `TypeError`, swallowed) → DAT verification silently never ran | `rom.py` | ✅ Fixed |
| 7 | 🟠 Med | All `rom_*` tools did blocking IA search/download/DAT-parse/MD5 hashing inside `async def` — froze the event loop and scheduler | `rom.py` | ✅ Fixed |
| 8 | 🟠 Med | `audible_download_new` wrote `/state/...json` without creating `/state` → raised after downloading, so ASINs were never recorded (re-download every run); also missing the auth-file guard its siblings have | `audible.py` | ✅ Fixed |
| 9 | 🟡 Low | `emby_recent(limit)` passed `limit` to the API but formatted a hardcoded `[:20]` — any `limit > 20` was silently truncated | `emby.py` | ✅ Fixed |
| 10 | 🟡 Low | `get_movie_queue` dropped the download-progress % that `get_tv_queue` computes (copy-paste divergence) | `radarr.py` | ✅ Fixed |
| 11 | 🟠 Med | `apscheduler` imported but absent from `requirements.txt` (Docker-only) → non-Docker installs got a silently-broken scheduler | `requirements.txt` | ✅ Fixed |
| 12 | 🟡 Low | Invalid `build-backend` in pyproject (`setuptools.backends._legacy:_Backend`) → `pip install .` would fail; `requires-python` also lagged the code | `pyproject.toml` | ✅ Fixed |
| 13 | 🟡 Low | DS credential env vars inconsistent (`DS_USERNAME`/`DS_PASSWORD` vs `DS_USER`/`DS_PASS`) and missing from `.env.example` | `download_station.py`, `.env.example` | ✅ Fixed |
| 14 | 🟡 Low | Deprecated `datetime.utcnow()`; unused imports in providers; dead branch in `_trigger_summary`; unused deps in requirements | multiple | ✅ Fixed |
| 15 | 🟡 Low | Doc drift: four different tool counts (49/59/61/66), missing Library category, wrong model name, stale "Download Station config gap" gotcha, wrong scheduler description | docs | ✅ Fixed |
| 16 | 🟡 Low | `_quick_hash` reads only head+tail 64 KB → two distinct files with matching size/head/tail could be reported as duplicates | `scanner.py` | ⬜ Accepted |
| 17 | 🟡 Low | `cli_repl` uses blocking `console.input()` in an async fn | `cli.py` | ⬜ Accepted |
| 18 | 🟡 Low | SABnzbd `apikey` passed as a URL query param (required by the SABnzbd API; lands in logs) | `dashboard.py` | ⬜ Accepted |

---

## What changed

**Security**
- **#1 Argument injection.** URLs are now passed after a `--` end-of-options
  separator in all four yt-dlp call sites and in bandcamp-dl. List-form argv
  already blocked shell metacharacters; `--` closes the remaining option-injection
  hole (e.g. a "URL" of `--exec=<cmd>`, which yt-dlp would otherwise run).
- **#2 Dashboard auth.** `/api/dashboard/data` and `/api/dashboard/chat` now call
  the same `_check_auth` guard as the `/v1` endpoints — a no-op when no
  `MEDIA_AGENT_API_KEY` is set, enforced (Bearer, constant-time compare) when one
  is. The `/dashboard` HTML shell remains open.
- **#3 Loopback bind.** `docker-compose.yml` publishes `127.0.0.1:8088:8088`.
  Expose beyond localhost only via an authenticated reverse proxy or VPN.
- **#4 DS credential leak.** The unified search reuses the hardened
  `DownloadStationClient` (POST-body credentials, login→request→logout) instead
  of a hand-built `GET` with `account=`/`passwd=` in the query string.
- **#5 Path confinement.** `library_*` tools resolve the requested path with
  `realpath` and require it to sit inside the configured `library.media_root`
  (blocks `..` traversal and symlink escapes; denies outright when `media_root`
  is unset).

**Correctness**
- **#6 rom verify.** `await rom_verify_dat.ainvoke({"platform": platform})` — the
  tool actually runs now instead of raising and being swallowed.
- **#7 rom blocking.** IA search/download, DAT parsing, and MD5 hashing moved into
  sync helpers invoked via `asyncio.to_thread`, matching the rest of the codebase.
- **#8 audible state.** `/state` is created before the sync-state write, and the
  auth-file guard was added.
- **#9/#10** — `emby_recent` honors `limit`; `get_movie_queue` shows progress %.

**Packaging / config / docs**
- **#11–#15** — `apscheduler` added to requirements (unused `sse-starlette` and
  `pydantic-settings` removed); valid setuptools build backend and
  `requires-python >=3.12`; `DS_USERNAME`/`DS_PASSWORD` standardized and added to
  `.env.example`; `datetime.now(timezone.utc)` replaces the deprecated call;
  unused imports and a dead branch removed; docs normalized to **66 tools** with a
  Library category, the correct `qwen3.5:9b` model name, an accurate scheduler
  description, and the stale DS "config gap" gotcha deleted.

---

## Still open (accepted, low risk)

- **#16 `_quick_hash` head+tail only.** The duplicate report is advisory (no
  deletion), so the risk is a misleading listing, not data loss. A full hash would
  slow large-library scans significantly; left as a documented trade-off.
- **#17 `cli_repl` blocking input.** Harmless in the current single-task REPL
  (nothing else shares the loop). Fix with a thread-offloaded prompt if a
  concurrent async task is ever added to the CLI.
- **#18 SABnzbd `apikey` in query string.** SABnzbd's API requires the key as a
  query parameter; it is an internal service and the value only reaches
  server/proxy logs. No code change available without a SABnzbd-side option.

## Known, not addressed (cosmetic)

- `SonarrClient`/`RadarrClient` (and `EmbyClient`/`SabnzbdClient`) are near-identical
  and could share one base client; `health.py` hand-rolls its httpx setup instead
  of reusing them. No behavioral impact — left for a future refactor.
- `bandcamp`/`audible`/`rom` providers are imported unconditionally in
  `registry.py` (their heavy deps import lazily inside functions, so this is safe),
  unlike the `try/except ImportError` guards used for the other optional providers.
- Several `.env.example` service URLs are inert unless the operator adds `${...}`
  references to `settings.yaml` (the example hardcodes URLs). Documented behavior of
  the env-substitution engine, not a bug.

## By design (not a defect)

- The `/v1` and dashboard APIs are **open when no `MEDIA_AGENT_API_KEY` is set**.
  This is intentional for a single-user localhost deployment; set a key before
  exposing the service. With the loopback bind (#3) this is safe by default.
