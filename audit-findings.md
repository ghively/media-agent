# Media Agent — Code Audit Findings

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
