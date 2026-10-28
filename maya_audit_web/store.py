"""Local storage: projects, plans, confirmations, audits, their progress events and conversations.

One SQLite file, outside the repository (see `data_home`). It holds metadata only: the report, the
saved crawl and the page evidence are files in each audit's folder. An audit row outlives the process,
which is what lets an audit that was running when the app closed come back as "interrupted".

This is the seam a hosted version replaces: the same methods over a managed database, with a tenant id
added to every row and query (docs/DASHBOARD-INTEGRATION.md).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB_NAME = "web-v1.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, profile TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, url TEXT NOT NULL, mode TEXT NOT NULL, key_pages TEXT NOT NULL,
    backlinks INTEGER NOT NULL, fingerprint TEXT NOT NULL, total_usd REAL NOT NULL, document TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS confirmations (
    plan_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, approved_usd REAL NOT NULL, confirmed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE, project_id TEXT NOT NULL, url TEXT NOT NULL, mode TEXT NOT NULL,
    key_pages TEXT NOT NULL, backlinks INTEGER NOT NULL, approved_usd REAL NOT NULL, config TEXT NOT NULL,
    state TEXT NOT NULL, outcome TEXT, outcome_reason TEXT, crawl_stop TEXT, error_code TEXT, progress TEXT NOT NULL,
    sessions INTEGER NOT NULL, paid_state TEXT NOT NULL, queue_seq INTEGER NOT NULL,
    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE INDEX IF NOT EXISTS audits_by_project ON audits (project_id, created_at);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id TEXT NOT NULL, version INTEGER NOT NULL, type TEXT NOT NULL,
    data TEXT NOT NULL, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_by_audit ON events (audit_id, id);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL,
    body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS messages_by_audit ON messages (audit_id, id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# Lifecycle of the job. What the audit found is `outcome`, a separate column in the engine's own words.
ACTIVE = ("queued", "running", "stopping")
RESUMABLE = ("stopped", "interrupted")
TERMINAL = ("finished", "stopped", "interrupted", "failed")
EVENT_VERSION = 1
# Progress events kept per audit. Older counter updates go first; phase, state and log events are kept longer.
MAX_PROGRESS_EVENTS = 600
MAX_EVENTS = 1500
_JSON = {"profile", "key_pages", "document", "config", "progress", "data", "body", "firecrawl", "flags"}
_BOOL = {"backlinks"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def later(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def is_past(stamp: str) -> bool:
    return datetime.fromisoformat(stamp) <= datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


def is_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)


def data_home(environ=None) -> Path:
    """Where history and saved reports live: ~/.maya-audit/web unless MAYA_AUDIT_HOME moves ~/.maya-audit.

    The spending ledger and the paid-data cache are the engine's, one level up, shared with the command line.
    """
    environ = os.environ if environ is None else environ
    return Path(environ.get("MAYA_AUDIT_HOME") or Path.home() / ".maya-audit") / "web"


class Store:
    def __init__(self, folder: Path | str) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.RLock()
        path = self.folder / DB_NAME
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        os.chmod(path, 0o600)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        # Columns added after the first release of this file's format. Adding a column keeps older history readable.
        for table, column, kind in (("confirmations", "approved_credits", "REAL NOT NULL DEFAULT 0"),
                                    ("audits", "firecrawl", "TEXT NOT NULL DEFAULT '{}'"),
                                    ("audits", "language", "TEXT NOT NULL DEFAULT 'en'"),
                                    # Decisions taken when the audit was started (today: to run without paid data).
                                    ("audits", "flags", "TEXT NOT NULL DEFAULT '{}'")):
            if column not in {row["name"] for row in self._db.execute(f"PRAGMA table_info({table})")}:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- plumbing --------------------------------------------------------------------------------

    def _run(self, sql: str, args: tuple = ()) -> tuple[int, int]:
        """(rows changed, last row id), read under the same lock as the statement."""
        with self._lock:
            cursor = self._db.execute(sql, args)
            return cursor.rowcount, cursor.lastrowid

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        for key in _JSON & out.keys():
            out[key] = json.loads(out[key])
        for key in _BOOL & out.keys():
            out[key] = bool(out[key])
        return out

    def _one(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        with self._lock:
            return self._row(self._db.execute(sql, args).fetchone())

    def _all(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [self._row(row) for row in self._db.execute(sql, args).fetchall()]

    def audit_folder(self, audit_id: str) -> Path:
        if not is_id(audit_id):
            raise ValueError("not an audit id")
        return self.folder / "audits" / audit_id

    # -- small values ----------------------------------------------------------------------------

    def get_meta(self, key: str) -> Any:
        row = self._one("SELECT value FROM meta WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else None

    def set_meta(self, key: str, value: Any) -> None:
        self._run("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                  (key, json.dumps(value)))

    # -- projects --------------------------------------------------------------------------------

    def profile(self, project_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM projects WHERE id = ?", (project_id,))

    def save_profile(self, project_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        self._run("INSERT INTO projects (id, profile, updated_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                  "profile = excluded.profile, updated_at = excluded.updated_at",
                  (project_id, json.dumps(profile, ensure_ascii=False), now()))
        return self.profile(project_id)

    # -- plans and confirmations -----------------------------------------------------------------

    def create_plan(self, *, project_id: str, url: str, mode: str, key_pages: list[str], backlinks: bool,
                    fingerprint: str, total_usd: float, document: dict[str, Any], lifetime_s: float) -> dict[str, Any]:
        """A plan is written once and never changed: other options mean another plan."""
        row = {"id": document["id"], "project_id": project_id, "url": url, "mode": mode, "key_pages": json.dumps(key_pages),
               "backlinks": int(backlinks), "fingerprint": fingerprint, "total_usd": total_usd,
               "document": json.dumps(document, ensure_ascii=False), "created_at": now(), "expires_at": later(lifetime_s)}
        with self._lock:
            self._db.execute("INSERT INTO plans VALUES (:id, :project_id, :url, :mode, :key_pages, :backlinks, :fingerprint, "
                             ":total_usd, :document, :created_at, :expires_at)", row)
        return self.plan(row["id"])

    def plan(self, plan_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM plans WHERE id = ?", (plan_id,))

    def confirmation(self, plan_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM confirmations WHERE plan_id = ?", (plan_id,))

    def confirm(self, plan: dict[str, Any], approved_usd: float, approved_credits: float = 0.0) -> dict[str, Any]:
        """Record the approval once. A second identical request finds the first and changes nothing."""
        self._run("INSERT OR IGNORE INTO confirmations (plan_id, fingerprint, approved_usd, confirmed_at, expires_at, approved_credits) "
                  "VALUES (?, ?, ?, ?, ?, ?)", (plan["id"], plan["fingerprint"], approved_usd, now(), plan["expires_at"], approved_credits))
        return self.confirmation(plan["id"])

    # -- audits ----------------------------------------------------------------------------------

    def create_audit(self, plan: dict[str, Any], approved_usd: float, config: dict[str, Any],
                     firecrawl: dict[str, Any] | None = None, language: str = "en",
                     flags: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
        """(audit, created). One audit per plan: a second start of the same plan returns the first audit."""
        with self._lock:
            existing = self._one("SELECT * FROM audits WHERE plan_id = ?", (plan["id"],))
            if existing:
                return existing, False
            seq = (self._one("SELECT COALESCE(MAX(queue_seq), 0) + 1 AS n FROM audits") or {"n": 1})["n"]
            row = {"id": new_id(), "plan_id": plan["id"], "project_id": plan["project_id"], "url": plan["url"],
                   "mode": plan["mode"], "key_pages": json.dumps(plan["key_pages"]), "backlinks": int(plan["backlinks"]),
                   "approved_usd": float(approved_usd), "config": json.dumps(config, ensure_ascii=False, default=str),
                   "state": "queued", "outcome": None, "outcome_reason": None, "crawl_stop": None, "error_code": None,
                   "progress": "{}", "sessions": 0,
                   # "skipped": paid data was on the plan and the person chose to run without it (the reason is in `flags`).
                   "paid_state": "none" if not plan["backlinks"] else "skipped" if (flags or {}).get("paid_skipped") else "pending",
                   "queue_seq": seq, "created_at": now(), "started_at": None, "finished_at": None,
                   "firecrawl": json.dumps(firecrawl or {}), "language": language,
                   "flags": json.dumps(flags or {}, ensure_ascii=False)}
            self._db.execute(
                "INSERT INTO audits (id, plan_id, project_id, url, mode, key_pages, backlinks, approved_usd, config, state, outcome, "
                "outcome_reason, crawl_stop, error_code, progress, sessions, paid_state, queue_seq, created_at, started_at, "
                "finished_at, firecrawl, language, flags) VALUES (:id, :plan_id, :project_id, :url, :mode, :key_pages, :backlinks, :approved_usd, "
                ":config, :state, :outcome, :outcome_reason, :crawl_stop, :error_code, :progress, :sessions, :paid_state, "
                ":queue_seq, :created_at, :started_at, :finished_at, :firecrawl, :language, :flags)", row)
            return self.audit(row["id"]), True

    def audit(self, audit_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM audits WHERE id = ?", (audit_id,))

    def audits(self, *, query: str = "", domain: str = "", status: str = "", limit: int = 50, offset: int = 0
               ) -> tuple[list[dict[str, Any]], int]:
        """Newest first, with the total for the same filter."""
        where, args = [], []
        if query.strip():
            like = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(url LIKE ? ESCAPE '\\' OR project_id LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM messages m "
                         "WHERE m.audit_id = audits.id AND m.kind = 'text' AND m.body LIKE ? ESCAPE '\\'))")
            args += [like, like, like]
        if domain:
            where.append("project_id = ?")
            args.append(domain)
        if status:
            where.append("state = ?")
            args.append(status)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = self._one(f"SELECT COUNT(*) AS n FROM audits{clause}", tuple(args))["n"]
        rows = self._all(f"SELECT * FROM audits{clause} ORDER BY created_at DESC, queue_seq DESC LIMIT ? OFFSET ?",
                         (*args, limit, offset))
        return rows, total

    def previous_audit(self, audit: dict[str, Any]) -> dict[str, Any] | None:
        """The audit of the same site before this one that produced a report."""
        return self._one("SELECT * FROM audits WHERE project_id = ? AND queue_seq < ? AND outcome IS NOT NULL "
                         "ORDER BY queue_seq DESC LIMIT 1", (audit["project_id"], audit["queue_seq"]))

    def latest_reported(self, project_id: str) -> dict[str, Any] | None:
        """The most recent audit of this site that produced a report."""
        return self._one("SELECT * FROM audits WHERE project_id = ? AND outcome IS NOT NULL ORDER BY queue_seq DESC LIMIT 1", (project_id,))

    def update_audit(self, audit_id: str, **fields: Any) -> None:
        allowed = {"state", "outcome", "outcome_reason", "crawl_stop", "error_code", "progress", "sessions", "paid_state",
                   "approved_usd", "started_at", "finished_at", "queue_seq", "url", "firecrawl"}
        sets, args = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(key)
            sets.append(f"{key} = ?")
            args.append(json.dumps(value, ensure_ascii=False) if key in ("progress", "firecrawl") else value)
        self._run(f"UPDATE audits SET {', '.join(sets)} WHERE id = ?", (*args, audit_id))

    def move_audit(self, audit_id: str, from_states: tuple[str, ...], to_state: str) -> bool:
        """Change state only from one of `from_states`: two clicks on Stop or Resume cannot both win."""
        marks = ",".join("?" * len(from_states))
        changed, _ = self._run(f"UPDATE audits SET state = ? WHERE id = ? AND state IN ({marks})",
                               (to_state, audit_id, *from_states))
        return changed == 1

    def next_queued(self) -> dict[str, Any] | None:
        return self._one("SELECT * FROM audits WHERE state = 'queued' ORDER BY queue_seq LIMIT 1")

    def requeue(self, audit_id: str) -> None:
        with self._lock:
            seq = self._one("SELECT COALESCE(MAX(queue_seq), 0) + 1 AS n FROM audits")["n"]
            self._db.execute("UPDATE audits SET queue_seq = ? WHERE id = ?", (seq, audit_id))

    def count_active(self) -> int:
        return self._one(f"SELECT COUNT(*) AS n FROM audits WHERE state IN ({','.join('?' * len(ACTIVE))})", ACTIVE)["n"]

    def unfinished(self) -> list[dict[str, Any]]:
        return self._all(f"SELECT * FROM audits WHERE state IN ({','.join('?' * len(ACTIVE))})", ACTIVE)

    def delete_audit(self, audit_id: str) -> None:
        """Every row of one audit in one transaction (D-20): a failure part-way leaves the audit whole, never half gone."""
        with self._lock:
            row = self.audit(audit_id)
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for table in ("events", "messages"):
                    self._db.execute(f"DELETE FROM {table} WHERE audit_id = ?", (audit_id,))
                self._db.execute("DELETE FROM audits WHERE id = ?", (audit_id,))
                if row:
                    self._db.execute("DELETE FROM confirmations WHERE plan_id = ?", (row["plan_id"],))
                    self._db.execute("DELETE FROM plans WHERE id = ?", (row["plan_id"],))
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    # -- events ----------------------------------------------------------------------------------

    def add_event(self, audit_id: str, type_: str, data: dict[str, Any]) -> int:
        """Append one progress event and return its id. Ids only ever grow, across all audits."""
        with self._lock:
            cursor = self._db.execute("INSERT INTO events (audit_id, version, type, data, ts) VALUES (?, ?, ?, ?, ?)",
                                      (audit_id, EVENT_VERSION, type_, json.dumps(data, ensure_ascii=False), now()))
            event_id = cursor.lastrowid
            if event_id % 50 == 0:
                self._trim_events(audit_id)
            return event_id

    def _trim_events(self, audit_id: str) -> None:
        for where, keep in (("AND type = 'progress'", MAX_PROGRESS_EVENTS), ("", MAX_EVENTS)):
            self._db.execute(
                f"DELETE FROM events WHERE audit_id = ? {where} AND id NOT IN (SELECT id FROM events WHERE audit_id = ? "
                f"{where} ORDER BY id DESC LIMIT ?)", (audit_id, audit_id, keep))

    def events(self, audit_id: str, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM events WHERE audit_id = ? AND id > ? ORDER BY id LIMIT ?", (audit_id, after, limit))

    def last_event_id(self, audit_id: str) -> int:
        return self._one("SELECT COALESCE(MAX(id), 0) AS n FROM events WHERE audit_id = ?", (audit_id,))["n"]

    # -- conversation ----------------------------------------------------------------------------

    def add_message(self, audit_id: str, role: str, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        created = now()
        _, row_id = self._run("INSERT INTO messages (audit_id, role, kind, body, created_at) VALUES (?, ?, ?, ?, ?)",
                              (audit_id, role, kind, json.dumps(body, ensure_ascii=False), created))
        return {"id": row_id, "role": role, "kind": kind, "body": body, "created_at": created}

    def messages(self, audit_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._all("SELECT id, role, kind, body, created_at FROM messages WHERE audit_id = ? ORDER BY id DESC LIMIT ?",
                         (audit_id, limit))
        return rows[::-1]
