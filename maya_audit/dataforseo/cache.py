"""Local cache of successful DataForSEO responses (SQLite, outside the repository)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

CACHE_NAME = "dataforseo-cache.db"


def cache_key(endpoint: str, payload: Any) -> str:
    """The endpoint path plus a SHA-256 of the request parameters in a fixed order."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return endpoint + "#" + hashlib.sha256(canonical.encode()).hexdigest()


class Cache:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, endpoint TEXT NOT NULL, "
                       "stored_at REAL NOT NULL, body TEXT NOT NULL)")

    @contextlib.contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """A connection that is committed and then closed. `with sqlite3.connect()` alone only ends the
        transaction; the open handle kept the file locked on Windows (WinError 32 on delete)."""
        with contextlib.closing(sqlite3.connect(self.path, timeout=10)) as db:
            with db:
                yield db

    def get(self, endpoint: str, payload: Any, lifetime_s: int) -> tuple[dict[str, Any], float] | None:
        """(response, stored_at) when a response younger than `lifetime_s` is held; otherwise None."""
        with self._db() as db:
            row = db.execute("SELECT body, stored_at FROM responses WHERE key = ?",
                             (cache_key(endpoint, payload),)).fetchone()
        if row is None or time.time() - row[1] > lifetime_s:
            return None
        return json.loads(row[0]), row[1]

    def put(self, endpoint: str, payload: Any, body: dict[str, Any], stored_at: float | None = None) -> None:
        """`stored_at` is when the answer arrived, so a later read of the cache gives the same date as the fresh report."""
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO responses (key, endpoint, stored_at, body) VALUES (?, ?, ?, ?)",
                       (cache_key(endpoint, payload), endpoint, time.time() if stored_at is None else stored_at,
                        json.dumps(body, ensure_ascii=False)))
