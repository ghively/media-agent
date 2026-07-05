# Media Agent — Code Audit Findings

Full-tree audit of `src/` (~5,000 lines), 2026-07-05. Each finding was verified
against the actual code (file:line quoted). This supersedes the previous audit;
items from that round that are genuinely fixed are noted under
[Already clean](#already-clean--stale-docs).

## Severity summary

| # | Severity | Finding | Location | Status |
|---|----------|---------|----------|--------|
| 1 | 🔴 High | Dashboard API routes had **no auth** — full agent control unauthenticated on the LAN | `dashboard.py` | ✅ Fixed |
| 2 | 🔴 High | `youtube.py` used blocking `subprocess.run` in 4 async tools — froze the event loop | `youtube.py` | ✅ Fixed |
| 3 | 🔴 High | `library_find_duplicates` was dead — parsed a summary string, always "0 files" | `scanner.py` | ✅ Fixed |
| 4 | 🔴 High | All `library_*` tools did blocking fs walks / MD5 hashing in the async loop | `library_tools.py` | ✅ Fixed |
| 5 | 🟠 Med | Circuit breaker built but never wired — no Ollama→hosted failover | `conversational.py:57`, `client.py` | ⬜ Open |
| 6 | 🟠 Med | Download Station SID session leak — logs in every call, never logs out | `download_station.py:48-69` | ⬜ Open |
| 7 | 🟠 Med | Download Station auth failure reported as "no tasks" (ignores `_ensure_auth`) | `download_station.py:65-84` | ⬜ Open |
| 8 | 🟠 Med | Download Station credentials in URL query, un-encoded | `download_station.py:52-57` | ⬜ Open |
| 9 | 🟠 Med | *arr history & calendar omit `includeSeries`/`includeMovie` → titles "Unknown" | `sonarr.py:130,165`, `radarr.py:130` | ⬜ Open |
| 10 | 🟠 Med | `download_media` reports success but does nothing | `search.py:252-277` | ⬜ Open |
| 11 | 🟠 Med | `undo_rename` could overwrite an existing file (data loss) | `naming.py:349` | ✅ Fixed |
| 12 | 🟠 Med | Dashboard `_gather_*` swallow all exceptions → broken service looks "healthy" | `dashboard.py` | ⬜ Open |
| 13 | 🟠 Med | `library_*` wrappers had no try/except (could raise) | `library_tools.py` | ✅ Fixed |
| 14 | 🟡 Low | Scheduler `daily_cleanup` (3 AM) & `weekly_scan` defined but never registered | `main.py:77-78` | ⬜ Open |
| 15 | 🟡 Low | `scheduler.stop()` leaves jobs populated; can't restart the scheduler | `scheduler.py:75-81` | ⬜ Open |
| 16 | 🟡 Low | `emby_search` header count mismatches the ≤20 items listed | `emby.py:49` | ⬜ Open |
| 17 | 🟡 Low | `get_tv_queue` fetches `sizeleft` then drops it — no progress shown | `sonarr.py:117` | ⬜ Open |
| 18 | 🟡 Low | SABnzbd output mislabels disk/queue fields | `sabnzbd.py:67-74,177-185` | ⬜ Open |
| 19 | 🟡 Low | `_check_local_tools` unbounded blocking `rglob` on every 30s refresh | `dashboard.py:386` | ⬜ Open |
| 20 | 🟡 Low | `cli_repl` uses blocking `console.input()` in an async fn (harmless today) | `cli.py:20` | ⬜ Open |
| 21 | 🟡 Low | `_quick_hash` (head+tail only) can flag distinct files as duplicates | `scanner.py` | ⬜ Open |
| 22 | 🟡 Low | `audible_download_new` prefixes ✅ even when 0 succeeded | `audible.py:169` | ⬜ Open |
| 23 | 🟡 Low | `rom_download` counts attempts, not verified downloads | `rom.py:83-85` | ⬜ Open |

---

## Fixed in this pass

**#1 — Dashboard auth.** `/api/dashboard/data` and `/api/dashboard/chat` now call
`_check_dashboard_auth(request)`, which requires `server.api_key` via an
`Authorization: Bearer` header, an `md_key` cookie, or a `?key=` query param
(constant-time compared with `hmac.compare_digest`). The browser dashboard
persists `?key=SECRET` into the cookie on load (React `main.jsx` + inline
fallback) and strips it from the URL. No key configured ⇒ open, matching the
OpenAI API's behaviour. **Open the dashboard once as
`http://<host>:8088/dashboard?key=<server.api_key>`.**

**#2 — youtube.py async subprocess.** Added `_run_ytdlp(cmd, timeout)` using
`asyncio.create_subprocess_exec`; all four call sites (`youtube_download`,
`youtube_add_subscription`, `youtube_check_subscriptions`, `youtube_get_info`)
now await it instead of `subprocess.run`. Timeout handlers switched to
`asyncio.TimeoutError`. A long download no longer freezes health checks, chat,
or the scheduler.

**#3 — find_duplicates.** Rewrote `scanner.find_duplicates(path)` to walk the
tree directly (same file filters as `build_inventory`), group by size, then
confirm with a content hash — instead of parsing a summary string that never
contained paths. Verified end-to-end: it now finds real duplicates across
subdirectories.

**#4 / #13 — library async offload + error handling.** Every `library_*` tool
now runs its blocking work via `asyncio.to_thread(...)` and is wrapped in
try/except returning `❌ Error: ...`, so scans/renames/hashes can't block the
event loop or raise out of the tool.

**#11 — undo_rename data-loss guard.** `undo_rename` now skips (with a warning)
any entry whose original path is already occupied, instead of letting
`os.rename` clobber it.

---

## Open items (recommended next)

- **Themes:** the remaining Mediums cluster around Download Station (#6–#8:
  session leak, masked auth errors, credentials in URL — worth a single pass on
  that client), the *arr "Unknown" titles (#9: add `includeSeries=true` /
  `includeMovie=true`), silent success/failure reporting (#10, #12), and the
  never-wired circuit breaker (#5).
- **Lows** are mostly output-labeling and doc/behavior drift; low risk.

---

## Already clean / stale docs

Re-verified against current source — these are **not** bugs:

- API-key comparison **is** constant-time (`hmac.compare_digest`, `openai_api.py:48`).
- `download_station` config property **exists** (`config.py`) — the CLAUDE.md
  "config gap" gotcha is stale.
- Audible "dead-code partial return" and "marks failed as done" — **both fixed**;
  per-book gating on `returncode == 0` is correct.
- `rom_download`'s `total > capped` branch is reachable and correct (not the old
  `> 20` dead branch).
- `*arr`/Emby HTTP clients don't leak (`async with` + timeout + `raise_for_status`).
- Registry is complete — every `@tool` on disk is registered (59 tools; CLAUDE.md's
  "49" is doc drift).
- No `shell=True` / command injection in any provider (all argv list-form).
