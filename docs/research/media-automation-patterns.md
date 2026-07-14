# Research Report — Overseerr/Maintainerr-Style Automation Patterns

> Focused deep-research pass (2026-07-14) into the request-lifecycle and
> library-maintenance patterns proven by Overseerr/Jellyseerr/Seerr and
> Maintainerr, as candidates for this agent. 24 sources fetched, 119 claims
> extracted, top 25 adversarially verified: **25 confirmed, 0 refuted** — every
> claim below survived 3-vote verification against primary sources (project
> docs, source code, issues/PRs). Companion to
> [small-model-reliability.md](small-model-reliability.md), which left this
> question unanswered.

---

## Context: the ecosystem consolidated

Overseerr was archived Feb 15 2026 (after v1.35.0); **Seerr**
([seerr-team/seerr](https://github.com/seerr-team/seerr), 11.9k stars, v3.3.0
June 2026, [docs.seerr.dev](https://docs.seerr.dev/)) is the official successor
merging Overseerr and Jellyseerr into one codebase. Notably for us: **Emby is
now a first-class supported media server** (it was experimental in Jellyseerr),
so our exact Emby + Sonarr + Radarr stack is the canonical supported
combination for the request-lifecycle pattern. Cite Seerr docs for anything
forward-looking.

---

## Ranked feature patterns

Ranking is by (evidenced demand) × (fit for a conversational agent) ÷
(implementation weight). Everything below builds on APIs already integrated
(Sonarr/Radarr/Emby/Telegram + APScheduler) — **no new services required**.
The one recurring new requirement is a small persistent store (SQLite is
already in the stack via AsyncSqliteSaver) for requests, quotas, and
quarantine timers.

### 1. Request lifecycle with approval gates (the "seerr core loop")

The category-defining loop: **submit → approve → acquire → notify available**.
For us this means: a non-admin Telegram user says "add Severance" → the agent
records a *pending request* instead of adding it directly → admin gets a
Telegram push with approve/deny buttons → on approve, the existing
`add_series`/`add_movie` tools fire → when the item appears in Emby, the
requester gets a "now available" push.

- Demand: this is the entire raison d'être of the most-starred app in the
  category (11.9k stars).
- Weight: **moderate** — a `requests` table + router intents
  (approve/deny/list pending) + the pieces below. All acquisition and
  availability APIs already wrapped.

### 2. "Available now" tracking via scheduled library diff

Seerr scans the media server on a schedule (full ~24h, recently-added more
often) to flip requests to Available/Partially Available and to show
already-owned titles during discovery ([verified 3-0](https://docs.seerr.dev/)).
Directly reproducible: `src/tools/emby.py` already queries `/emby/Items` and
`src/scheduler.py` already runs periodic jobs — add a job that diffs pending
requests against Emby and notifies the requester on Telegram.

- Weight: **light**. Highest value-per-line-of-code item on this list.
- Bonus: "you already have that" replies during search/add flows.

### 3. Rolling-window request quotas with per-user overrides

Verified end-to-end through the paper trail: requested in
[overseerr#263](https://github.com/sct/overseerr/issues/263) (citing Ombi's
rolling 7-day rate as prior art), shipped in
[PR #1277](https://github.com/sct/overseerr/pull/1277) /
[v1.22.0](https://github.com/sct/overseerr/releases/tag/v1.22.0): global movie
and series limits ("x per y days"), per-user overrides, and quota progress
shown at request time. Conversational equivalent: "you have 2 of 5 requests
left this week" appended to Telegram replies.

- Weight: **moderate** — per-user request log + window config; no new services.

### 4. Permission tiers keyed to Telegram chat id

The whole lineage ships a "granular permission system" as a README-headline
feature — Jellyseerr's `permissions.ts` defines 30+ bitfield permissions
(REQUEST, AUTO_APPROVE, MANAGE_REQUESTS, MANAGE_USERS, ADMIN, …), with a
default permission set auto-assigned to new users and quota exemption for
manager roles (all verified at source level). Our version: extend the existing
Telegram chat-id allowlist into a role map (admin / requester / viewer),
auto-approve as a per-user bit, admins quota-exempt.

- Weight: **light** — it's a dict upgrade to config we already have.

### 5. Quarantine-before-delete cleanup ("leaving soon")

Maintainerr's signature pattern ([verified 3-0](https://docs.maintainerr.info/rules/)):
rule-matched media goes into a **visible collection** for N days before
deletion; items that stop matching are automatically reprieved. Our version: a
"Leaving Soon" Emby collection + a scheduled deletion job + a
notification-before-action Telegram digest, with **"keep X"** as the
conversational reprieve command — arguably a better reprieve UX than
Maintainerr's own.

- Weight: **moderate** — Emby collection management + a quarantine ledger are
  new; all downstream deletes use already-wrapped Sonarr/Radarr/Emby APIs.

### 6. Graduated cleanup actions (not delete-only)

Per rule group, Maintainerr offers: delete, **unmonitor**, **change quality
profile** (downgrade to save space), tag in *arr, report-only ("do nothing"),
plus **import-list exclusions** so *arr lists don't re-add removed media.
Every action maps to Sonarr/Radarr endpoints we already wrap; the list-exclusion
call is a one-endpoint addition.

- Weight: **light** per action. "Downgrade instead of delete" and
  "unmonitor but keep files" are natural conversational commands.

### 7. Rolling episode retention with outage fail-safety

Maintainerr's four Sonarr rank properties enable "keep the newest N episodes,
delete the rest", computed fresh each run over *currently-downloaded* episodes.
Critical verified semantic: **if Sonarr is unreachable during a run, affected
items are skipped, never matched** — unknown state = no action, so an outage
can't trigger surprise deletions. Adopt that invariant in any cleanup job we
build.

- Weight: **light-to-moderate** on existing Sonarr tools + scheduler.

### 8. Season-level request granularity

"Request individual seasons or movies" is the verbatim top feature bullet
across Overseerr → Jellyseerr → Seerr. Our "add this show" flow should ask or
accept season scope ("just season 1") instead of defaulting to whole-series —
Sonarr's per-season monitoring is already exposed by our 12 Sonarr tools.

- Weight: **light** — mostly router/prompt work, plus the season-search tool
  that already exists.

### 9. Natural-language auto-approve/routing rules (open demand)

[seerr#1184](https://github.com/seerr-team/seerr/issues/1184) (open) asks for
multi-condition rules at request time — genre/year/season-count/requester →
auto-approve + route (quality profile, root folder, tags). Jellyseerr shipped
only the routing half ("Override Rules",
[PR #945](https://github.com/seerr-team/seerr/pull/945)); rule-based
auto-approval remains unshipped anywhere. **This is the one place a
conversational agent can leapfrog the category**: "auto-approve anything under
3 seasons from Alice, send anime to the anime root folder" is a natural
sentence for us and an unbuilt web-form for them.

- Weight: **moderate** — predicate evaluation over request metadata; the
  add-parameters (profile/folder/tags) are already tool arguments.

### 10. Lifecycle notification fan-out (Telegram-first slice)

Seerr ships ~10 notification agents with per-event configuration. Our
highest-value slice is just two proactive Telegram events: **"approval
needed"** (to admins) and **"your request is available"** (to the requester) —
the bot interface already exists. Per-user event subscriptions can come later.

- Weight: **light** for the two-event slice.

---

## Suggested implementation order

Phase 1 (light, immediate): #2 availability diff job → #4 role map → #8
season-scoped adds → #10 two-event Telegram pushes.
Phase 2 (the request loop): #1 pending-request store + approve/deny flow → #3
quotas.
Phase 3 (maintenance): #5 quarantine collection + #6 graduated actions + #7
retention rules, all under the fail-safe invariant.
Phase 4 (differentiator): #9 NL-defined auto-approve rules.

Phases 1–2 make the agent a conversational Seerr; phase 3 makes it a
conversational Maintainerr; phase 4 is something neither has shipped.

---

## Evidence quality and gaps

- All 25 surviving claims concern the seerr lineage and Maintainerr; **no
  claims survived on the chat bots (Requestrr/Doplarr/Botdarr/Searcharr/
  Membarr), Ombi/Tautulli analytics, or Home Assistant media automations** —
  unanswered again, not refuted. The most useful missing piece is the chat
  bots' disambiguation UX (buttons vs numbered replies), which would directly
  inform our Telegram flows; our dashboard already has yes/no + pick buttons,
  so mirroring those in Telegram inline keyboards is the obvious default.
- Demand evidence is doc prominence, stars, and issue/PR paper trails rather
  than quantified upvote counts.
- Docs were verified to match shipped code where checked (Jellyseerr
  `permissions.ts`, Maintainerr rule enums) but not behavior-tested end-to-end.
- Maintainerr docs current through v3.17.1; recent versions made some behaviors
  configurable (end-of-quarantine action, automatic list exclusions), so exact
  toggles may drift.

## Open questions

1. Chat-native disambiguation/approval UX evidence (Requestrr/Doplarr/etc.) —
   uncovered by both research passes.
2. Can stale-media/most-watched signals come from Emby's API alone (watch
   state, play counts) without a Tautulli dependency? (Likely yes — worth a
   spike before building #5/#7 rules that want "last watched" data.)
3. Will Seerr ship rule-based auto-approval (#1184/PR #1190)? Determines
   whether #9 stays a differentiator.
4. Proven media intent phrasings from Home Assistant to seed the deterministic
   router — still unmined.
