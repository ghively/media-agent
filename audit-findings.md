# Media Agent — Code Audit Findings

Full-tree audit of `src/` (~5,000 lines), 2026-07-05. Each finding was verified
against the actual code (file:line quoted). **21 of 23 findings are fixed**; the
two remaining are low-risk (documented below).

## Severity summary

| # | Severity | Finding | Location | Status |
|---|----------|---------|----------|--------|
| 1 | 🔴 High | Dashboard API routes had **no auth** — full agent control unauthenticated on the LAN | `dashboard.py` | ✅ Fixed |
| 2 | 🔴 High | `youtube.py` used blocking `subprocess.run` in 4 async tools — froze the event loop | `youtube.py` | ✅ Fixed |
| 3 | 🔴 High | `library_find_duplicates` was dead — parsed a summary string, always "0 files" | `scanner.py` | ✅ Fixed |
| 4 | 🔴 High | All `library_*` tools did blocking fs walks / MD5 hashing in the async loop | `library_tools.py` | ✅ Fixed |
| 5 | 🟠 Med | Circuit breaker built but never wired — no Ollama→hosted failover | `conversational.py` | ✅ Fixed |
| 6 | 🟠 Med | Download Station SID session leak — logged in every call, never logged out | `download_station.py` | ✅ Fixed |
| 7 | 🟠 Med | Download Station auth failure reported as "no tasks" | `download_station.py` | ✅ Fixed |
| 8 | 🟠 Med | Download Station credentials in URL query, un-encoded | `download_station.py` | ✅ Fixed |
| 9 | 🟠 Med | *arr history & calendar omitted `includeSeries`/`includeMovie` → titles "Unknown" | `sonarr.py`, `radarr.py` | ✅ Fixed |
| 10 | 🟠 Med | `download_media` reported success but did nothing | `search.py` | ✅ Fixed |
| 11 | 🟠 Med | `undo_rename` could overwrite an existing file (data loss) | `naming.py` | ✅ Fixed |
| 12 | 🟠 Med | Dashboard `_gather_*` swallowed all exceptions → broken service looked "healthy" | `dashboard.py` | ✅ Fixed |
| 13 | 🟠 Med | `library_*` wrappers had no try/except (could raise) | `library_tools.py` | ✅ Fixed |
| 14 | 🟡 Low | Scheduler `daily_cleanup` (3 AM) & `weekly_scan` defined but never registered | `main.py` | ✅ Fixed |
| 15 | 🟡 Low | `scheduler.stop()` left jobs populated; couldn't restart the scheduler | `scheduler.py` | ✅ Fixed |
| 16 | 🟡 Low | `emby_search` header count mismatched the ≤20 items listed | `emby.py` | ✅ Fixed |
| 17 | 🟡 Low | `get_tv_queue` fetched `sizeleft` then dropped it — no progress shown | `sonarr.py` | ✅ Fixed |
| 18 | 🟡 Low | SABnzbd output mislabeled disk/queue fields | `sabnzbd.py` | ✅ Fixed |
| 19 | 🟡 Low | `_check_local_tools` unbounded blocking `rglob` on every 30s refresh | `dashboard.py` | ✅ Fixed |
| 20 | 🟡 Low | `cli_repl` uses blocking `console.input()` in an async fn (harmless today) | `cli.py:20` | ⬜ Open |
| 21 | 🟡 Low | `_quick_hash` (head+tail only) can flag distinct files as duplicates | `scanner.py` | ⬜ Open |
| 22 | 🟡 Low | `audible_download_new` prefixed ✅ even when 0 succeeded | `audible.py` | ✅ Fixed |
| 23 | 🟡 Low | `rom_download` counted attempts, not verified downloads | `rom.py` | ✅ Fixed |

---

## What changed

**Highs**
- **#1 Dashboard auth** — `/api/dashboard/data` and `/chat` now require
  `server.api_key` via `Authorization: Bearer`, an `md_key` cookie, or a `?key=`
  query param (constant-time). Frontends persist `?key=` into the cookie and
  strip it from the URL. No key configured ⇒ open. **Open the dashboard once as
  `http://<host>:8088/dashboard?key=<server.api_key>`.**
- **#2 youtube.py** — new async `_run_ytdlp` helper (`asyncio.create_subprocess_exec`);
  all four call sites await it.
- **#3 find_duplicates** — walks the tree directly; verified it now finds real
  duplicates across subdirectories.
- **#4/#13 library_*** — blocking work via `asyncio.to_thread`, each tool wrapped
  in try/except.

**Mediums**
- **#5 failover** — local model wrapped with `with_fallbacks([hosted])` when a
  hosted fallback is configured (default path unchanged).
- **#6/#7/#8 Download Station** — client rewritten: login→request→logout per call
  (no leaked SID), credentials sent as POST form data, auth failure raised and
  surfaced instead of masked as "no tasks". The dashboard's own DS/SABnzbd
  gatherers now emit an **error card** (counts toward "degraded") instead of
  vanishing (#12), and DS login there also moved to POST.
- **#9** — added `includeSeries=true` / `includeMovie=true` to *arr history &
  calendar.
- **#10** — `download_media` now states plainly that nothing was downloaded and
  routes to the source-specific tool.
- **#11** — `undo_rename` skips (with a warning) when the original path is occupied.

**Lows**
- **#14** — `daily_cleanup` (health report) and `weekly_scan` (Emby scan) jobs
  registered; startup log reports the real job count.
- **#15** — `stop()` clears jobs/callbacks and replaces the scheduler so `start()`
  works again.
- **#16** — `emby_search` header shows "showing first N" when the library match
  exceeds the listed items.
- **#17** — `get_tv_queue` now shows a real progress %.
- **#18** — SABnzbd totals use `mb`/`mbleft`; disk shows "free of total".
- **#19** — `_check_local_tools` offloaded via `asyncio.to_thread`.
- **#22** — `audible_download_new` uses ⚠️ when 0 succeeded.
- **#23** — `rom_download` counts only files that downloaded without error and
  reports failures.

---

## Still open (accepted, low risk)

- **#20 — `cli_repl` blocking `console.input()`.** Harmless in the current
  single-task REPL (nothing else shares the loop). Would only matter if a
  concurrent async task were added to the CLI; fix then with a thread-offloaded
  prompt.
- **#21 — `_quick_hash` head+tail only.** Two distinct files with identical size
  and matching head/tail bytes could be reported as duplicates. The report is
  advisory (no deletion), so the risk is a misleading listing, not data loss.
  Upgrading to a full hash would slow large-library scans significantly; left as
  a documented trade-off.

---

## Already clean / stale docs

Re-verified against current source — these are **not** bugs:

- API-key comparison **is** constant-time (`hmac.compare_digest`, `openai_api.py:48`).
- `download_station` config property **exists** (`config.py`) — the CLAUDE.md
  "config gap" gotcha is stale.
- Audible "dead-code partial return" and "marks failed as done" — both already
  correct; per-book gating on `returncode == 0` holds.
- `*arr`/Emby HTTP clients don't leak (`async with` + timeout + `raise_for_status`).
- Registry is complete — every `@tool` on disk is registered (59 tools; CLAUDE.md's
  "49" is doc drift).
- No `shell=True` / command injection in any provider (all argv list-form).
