# Media Agent — Code Audit Findings

Review of the full `src/` tree (~4,200 lines). Each finding below was verified
against the actual code; verification method is noted per item.

## Severity summary

| # | Severity | Finding |
|---|----------|---------|
| 1 | 🔴 High | `Settings` missing `youtube`/`download_station` — every YouTube & Download Station call fails |
| 2 | 🔴 High | `audible_download` success message drops 3 of 4 lines (dead-code return) |
| 3 | 🔴 High | `library_sort_dir` tool doesn't exist; the whole library module is unregistered |
| 4 | 🟠 Medium | Circuit breaker in `MediaLLM` is never used |
| 5 | 🟠 Medium | Scheduler is inert in `--serve` |
| 6 | 🟠 Medium | `audible_download_new` marks failed downloads as done |
| 7 | 🟠 Medium | `fix_naming` can silently overwrite files (data loss) |
| 8 | 🟡 Low | `rom_download` dead `total > 20` branch |
| 9 | 🟡 Low | Auth hardening: non-constant-time key compare; DS credentials in URL |
| 10 | 🟡 Low | 5 tools defined but never registered |
| 11 | 🟡 Low | Dead/duplicate code in `main.py` |
| 12 | 🟡 Low | Duplicated per-request HTTP client boilerplate (no pooling) |

---

## 🔴 High — functional breakage

### 1. `Settings` is missing `youtube` and `download_station`

`src/config.py:39-61` defines properties for `server`, `llm`, `sonarr`, `radarr`,
`emby`, `sabnzbd` only, and there is no `__getattr__`. But three call sites access
attributes that don't exist:

- `src/providers/youtube.py:35` → `get_settings().youtube`
- `src/tools/download_station.py:114` → `get_settings().download_station`
- `src/tools/search.py:111` → `get_settings().download_station`

**Verified:** instantiated the real `Settings` class — `.youtube` and
`.download_station` both raise `AttributeError`. Neither section exists in
`config/settings.yaml.example`.

**Impact:** all four YouTube tools raise `AttributeError` at runtime (caught →
returns a "❌ … failed" string); every Download Station tool is broken.
`search.py:_search_download_station` swallows the error and returns `[]`, so
unified search *silently* never includes torrents.

**Fix:** add `youtube` and `download_station` properties to `Settings` (and the
matching config sections).

### 2. `audible_download` throws away most of its success message

`src/providers/audible.py:102-105`:

```python
return f"✅ Downloaded and decrypted: {output_path.name}\n"
f"   Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB\n"   # dead code
f"   Path: {output_path}\n"                                        # never reached
f"   Run `library_sort_dir` to organize into the audiobooks library."
```

The `return` ends at line 102; the following f-strings are unreachable expression
statements (no parentheses/backslash to make them one literal).

**Verified via AST:** line 102 `return` returns a single `JoinedStr`; lines
103–105 parse as three bare `Expr` statements = dead code. The function returns
only `"✅ Downloaded and decrypted: X.m4b\n"`.

**Fix:** wrap the four strings in parentheses so they concatenate.

### 3. `library_sort_dir` doesn't exist, and the library module is unregistered dead code

The system prompt (`src/graphs/conversational.py:33-34`) and success messages in
`src/providers/bandcamp.py:37,39` and `src/providers/audible.py:105` all tell the
user/agent to run `library_sort_dir` — but no such tool exists.

**Verified:** `library_sort_dir` is never defined (only referenced in those 4
places). `src/library/naming.py` (`check_naming`, `fix_naming`, `undo_rename`) and
`src/library/scanner.py` (`build_inventory`, `find_duplicates`, …) have no `@tool`
decorators and are never imported by `src/tools/registry.py`.

**Impact:** the agent cannot organize anything it downloads.

**Fix:** register the library functions as tools (and add a `library_sort_dir`
entry point), or stop advertising the capability.

---

## 🟠 Medium

### 4. The circuit breaker is never used

`src/graphs/conversational.py:40-41` builds the agent with `llm.local_llm`
directly, bypassing `MediaLLM.get_llm()`.

**Verified:** `get_llm`/`record_success`/`record_failure` are never called outside
`src/llm/client.py`. All the `CircuitState` / hosted-fallback logic is dead — there
is no actual local→hosted failover despite the design.

### 5. The scheduler does nothing in `--serve`

Two independent defects:

1. `src/main.py:60` calls `sched.start()` in a bare `threading.Thread`.
   `AsyncIOScheduler` binds to `asyncio.get_event_loop()`, which raises
   `RuntimeError: There is no current event loop in thread …` in a worker thread
   (reproduced on Python 3.11). The exception is caught and logged as
   "Scheduler not started."
2. Independent of that, `MediaScheduler.add_job(...)` is never called in the serve
   path, so zero jobs exist regardless.

Bonus: the dead `_run_serve` at `src/main.py:87` calls `get_scheduler`, which is
not defined.

**Note:** apscheduler was not installed in the audit environment, so
`AsyncIOScheduler.start()` was not executed end-to-end; the underlying primitive
(`get_event_loop()` raising in a bare thread) and the "no jobs added" fact were
both verified. The feature is inert either way.

### 6. `audible_download_new` marks failed downloads as done

`src/providers/audible.py:148-159`: the subprocess result/returncode is ignored and
`downloaded.add(asin)` runs unconditionally, then state is persisted. A failed
download is permanently recorded as synced and never retried. It also skips the
`AUDIBLE_AUTH_FILE.exists()` check the other functions have, and the reported count
(`len(new_books[:5])`) counts attempts, not successes.

### 7. `fix_naming` can silently destroy files

`src/library/naming.py:139` uses `os.rename`, which on POSIX atomically replaces an
existing destination.

**Verified:** in a direct test `os.rename` overwrote a distinct existing file
(victim data lost, source gone, no undo entry for the lost file).

**Impact:** if two source files map to the same target (or a file already sits at
the target), one is overwritten with no recovery.

**Fix:** check `new_path.exists()` before renaming.

---

## 🟡 Low / polish

### 8. `rom_download` dead branch

`src/providers/rom.py:76,86`: `total = len(roms[:20])` is ≤ 20, so `if total > 20`
never fires; the "more files skipped" notice never prints and the count is
misleading.

### 9. Auth hardening

- `src/interfaces/openai_api.py:47` compares the API key with `!=` (not
  constant-time).
- Download Station passes `username`/`password` as URL query params
  (`src/tools/download_station.py:52-57`, `src/tools/search.py:121-126`), which
  leak into any request logging.

### 10. Inconsistent tool exposure

Defined but never imported in `registry.py` (registry references = 0):
`sabnzbd_add_nzb`, `download_station_info`, `download_station_stats`,
`youtube_get_info`, `youtube_remove_subscription`.

### 11. Dead/duplicate code in `main.py`

`_run_serve()` (`src/main.py:77`) is unused and duplicates `_run_server`; it
references the undefined `get_scheduler`. `main.py` also imports `threading` twice,
and `logging.info`/`logging.warning` are called with no logging config so the
messages vanish.

### 12. Duplicated HTTP client boilerplate

Sonarr/Radarr/Emby/SABnzbd each open a fresh `httpx.AsyncClient` per request (no
connection pooling) and repeat near-identical client code; a shared base client
would remove ~150 lines.

---

## Overall

The structure is clean and readable — consistent tool pattern, good
error-to-plain-language handling, sensible provider isolation. But several
advertised features are wired up incorrectly and fail the moment they're
exercised: YouTube/Download Station (config bug, #1), audiobook download output
(dead-code return, #2), library organization (missing tool, #3), and both
resilience features — circuit breaker (#4) and scheduler (#5) — are
non-functional. Findings #1–#3 are the ones to fix before shipping.
