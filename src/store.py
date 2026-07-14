"""Persistent state for the request/approval loop and library cleanup.

One small SQLite database (aiosqlite — already a dependency via the
conversation checkpointer) on the state volume holds everything that must
survive a restart:

- ``requests``   — media requests: pending → approved/denied → available
- ``quarantine`` — "leaving soon" ledger: items scheduled for cleanup with a
  grace period, reprievable until the deadline (Maintainerr's
  quarantine-before-delete pattern)
- ``rules``      — persisted rules: ``auto_approve`` (evaluated when a
  request is created) and ``retention`` ("keep the newest N episodes")

Design mirrors src/audit.py: the DB lives under ``MEDIA_AGENT_STATE_DIR``
(default ``/state``). Every call opens a short-lived connection — traffic
here is a few writes per day, so connection pooling would be complexity
without benefit. Callers (tools, router handlers) wrap these in their own
try/except per the tool conventions; functions here may raise.
"""
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester TEXT NOT NULL,
    title TEXT NOT NULL,
    media_type TEXT NOT NULL,          -- 'tv' | 'movie'
    source_id INTEGER,                 -- tvdbId / tmdbId
    season INTEGER,                    -- NULL = whole series
    year TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|denied|available
    created_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                -- 'tv' | 'movie'
    arr_id INTEGER NOT NULL,           -- Sonarr seriesId / Radarr movieId
    title TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'delete',   -- delete|unmonitor
    reason TEXT DEFAULT '',
    added_at REAL NOT NULL,
    grace_days INTEGER NOT NULL DEFAULT 7,
    status TEXT NOT NULL DEFAULT 'quarantined'  -- quarantined|reprieved|done
);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                -- 'auto_approve' | 'retention'
    conditions TEXT NOT NULL,          -- JSON
    actions TEXT NOT NULL,             -- JSON
    created_at REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
"""


def _db_path() -> Path:
    # Resolved per call (not at import) so tests can point the state dir at
    # a tmp directory before first use.
    return Path(os.environ.get("MEDIA_AGENT_STATE_DIR", "/state")) / "agent_store.db"


@asynccontextmanager
async def _conn():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(_SCHEMA)
        yield db


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── requests ─────────────────────────────────────────────────────────────────

async def add_request(requester: str, title: str, media_type: str,
                      source_id: int | None, season: int | None = None,
                      year: str = "") -> int:
    async with _conn() as db:
        cur = await db.execute(
            "INSERT INTO requests (requester, title, media_type, source_id, "
            "season, year, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (requester, title, media_type, source_id, season, year, time.time()))
        await db.commit()
        return cur.lastrowid


async def get_request(request_id: int) -> dict | None:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_requests(status: str | None = None, limit: int = 30) -> list[dict]:
    async with _conn() as db:
        if status:
            cur = await db.execute(
                "SELECT * FROM requests WHERE status = ? "
                "ORDER BY id DESC LIMIT ?", (status, limit))
        else:
            cur = await db.execute(
                "SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,))
        return _rows_to_dicts(await cur.fetchall())


async def set_request_status(request_id: int, status: str,
                             decided_by: str = "", note: str = "") -> bool:
    async with _conn() as db:
        cur = await db.execute(
            "UPDATE requests SET status = ?, decided_at = ?, decided_by = ?, "
            "note = ? WHERE id = ?",
            (status, time.time(), decided_by, note, request_id))
        await db.commit()
        return cur.rowcount > 0


async def find_duplicate_request(source_id: int, media_type: str) -> dict | None:
    """An existing non-denied request for the same title, if any."""
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM requests WHERE source_id = ? AND media_type = ? "
            "AND status != 'denied' ORDER BY id DESC LIMIT 1",
            (source_id, media_type))
        row = await cur.fetchone()
        return dict(row) if row else None


async def count_recent_requests(requester: str, days: int) -> int:
    """Requests this user made inside the rolling window (denied ones don't
    count against the quota — mirrors Overseerr's behavior)."""
    cutoff = time.time() - days * 86400
    async with _conn() as db:
        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE requester = ? "
            "AND created_at > ? AND status != 'denied'", (requester, cutoff))
        row = await cur.fetchone()
        return int(row["n"])


async def awaiting_availability() -> list[dict]:
    """Approved requests that haven't been marked available yet."""
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM requests WHERE status = 'approved' ORDER BY id")
        return _rows_to_dicts(await cur.fetchall())


# ── quarantine ───────────────────────────────────────────────────────────────

async def quarantine_add(kind: str, arr_id: int, title: str, action: str,
                         reason: str, grace_days: int) -> int:
    async with _conn() as db:
        cur = await db.execute(
            "INSERT INTO quarantine (kind, arr_id, title, action, reason, "
            "added_at, grace_days) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, arr_id, title, action, reason, time.time(), grace_days))
        await db.commit()
        return cur.lastrowid


async def quarantine_list(status: str = "quarantined") -> list[dict]:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM quarantine WHERE status = ? ORDER BY added_at",
            (status,))
        return _rows_to_dicts(await cur.fetchall())


async def quarantine_find(title: str) -> dict | None:
    """Case-insensitive title match among currently quarantined items."""
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM quarantine WHERE status = 'quarantined' "
            "AND lower(title) = lower(?) LIMIT 1", (title,))
        row = await cur.fetchone()
        if row:
            return dict(row)
        cur = await db.execute(
            "SELECT * FROM quarantine WHERE status = 'quarantined' "
            "AND lower(title) LIKE lower(?) LIMIT 1", (f"%{title}%",))
        row = await cur.fetchone()
        return dict(row) if row else None


async def quarantine_set_status(item_id: int, status: str) -> bool:
    async with _conn() as db:
        cur = await db.execute(
            "UPDATE quarantine SET status = ? WHERE id = ?", (status, item_id))
        await db.commit()
        return cur.rowcount > 0


async def quarantine_due(now: float | None = None) -> list[dict]:
    """Quarantined items whose grace period has fully elapsed."""
    now = time.time() if now is None else now
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM quarantine WHERE status = 'quarantined' "
            "AND added_at + grace_days * 86400 <= ?", (now,))
        return _rows_to_dicts(await cur.fetchall())


# ── rules ────────────────────────────────────────────────────────────────────

async def rule_add(kind: str, conditions: dict, actions: dict) -> int:
    async with _conn() as db:
        cur = await db.execute(
            "INSERT INTO rules (kind, conditions, actions, created_at) "
            "VALUES (?, ?, ?, ?)",
            (kind, json.dumps(conditions), json.dumps(actions), time.time()))
        await db.commit()
        return cur.lastrowid


async def rules_list(kind: str | None = None, enabled_only: bool = True) -> list[dict]:
    async with _conn() as db:
        query = "SELECT * FROM rules"
        clauses, params = [], []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if enabled_only:
            clauses.append("enabled = 1")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id"
        cur = await db.execute(query, params)
        rows = _rows_to_dicts(await cur.fetchall())
    for r in rows:
        r["conditions"] = json.loads(r["conditions"])
        r["actions"] = json.loads(r["actions"])
    return rows


async def rule_remove(rule_id: int) -> bool:
    async with _conn() as db:
        cur = await db.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        await db.commit()
        return cur.rowcount > 0
