"""Append-only record of every DataForSEO call and what it cost.

One JSON object per line. A paid call writes a "reserve" line with its estimate *before* the
request, under the same lock that checks the daily budget, and a "settle" line with the real cost
afterwards. Lines are only ever appended; the state of a call is its last line. A reservation that
is never settled (a timeout, a crash) keeps counting at its estimate, because it may have been billed.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .. import filelock

LEDGER_NAME = "dataforseo-ledger.jsonl"
# States whose real cost is unknown: they count at the estimate.
UNSETTLED = {"reserved", "possibly_billed"}


class LedgerCorrupt(RuntimeError):
    """The ledger cannot be read, so today's spend is unknown and paid calls must stop."""


class BudgetExceeded(RuntimeError):
    """This call's estimate would take today's spend past the daily budget."""


class AuditCapReached(RuntimeError):
    """This call's estimate would take what one audit has spent or reserved past the limit for one audit."""

    def __init__(self, message: str, cap: float, spent: float) -> None:
        super().__init__(message)
        self.cap, self.spent = cap, spent


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Ledger:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.path.with_name(self.path.name + ".lock"), "a+") as lock:
            filelock.lock(lock, blocking=True)
            try:
                yield
            finally:
                filelock.unlock(lock)

    def _read(self) -> list[dict[str, Any]]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeDecodeError) as exc:
            raise LedgerCorrupt(f"the DataForSEO ledger {self.path} cannot be read ({exc})") from exc
        rows = []
        for number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not (isinstance(row, dict) and isinstance(row["id"], str) and isinstance(row["ts"], str)
                        and row["event"] in {"reserve", "settle", "cache_hit", "free"}
                        and isinstance(row["estimate"], (int, float))
                        and isinstance(row.get("cost"), (int, float, type(None)))):
                    raise ValueError("unexpected fields")
            except (ValueError, KeyError, TypeError) as exc:
                raise LedgerCorrupt(
                    f"the DataForSEO ledger {self.path} is corrupt at line {number} ({exc}). Paid calls are "
                    "stopped because today's spend cannot be worked out. The file has not been changed: "
                    "repair or move it, then run again.") from exc
            rows.append(row)
        return rows

    def _append(self, row: dict[str, Any]) -> None:
        line = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode()
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)  # one write of one line: a reader never sees half a row
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _fold(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        calls: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["id"] in calls and row["event"] == "settle":
                calls[row["id"]].update({k: row[k] for k in ("status", "cost", "note", "settled_ts") if k in row})
            else:
                calls[row["id"]] = dict(row)
        return list(calls.values())

    @staticmethod
    def _counted(call: dict[str, Any]) -> float:
        if call["status"] in UNSETTLED or call.get("cost") is None:
            return float(call["estimate"])
        return float(call["cost"])

    def calls(self) -> list[dict[str, Any]]:
        """One row per call, in its latest state."""
        with self._locked():
            return self._fold(self._read())

    def spent_today(self) -> float:
        today = _now().date().isoformat()
        return round(sum(self._counted(c) for c in self.calls() if c["ts"][:10] == today), 6)

    def _row(self, event: str, status: str, endpoint: str, target: str | None, audit_id: str | None,
             estimate: float, cost: float | None, cache: str, note: str | None = None) -> dict[str, Any]:
        return {"id": uuid.uuid4().hex, "event": event, "status": status, "ts": _now().isoformat(timespec="seconds"),
                "endpoint": endpoint, "target": target, "audit_id": audit_id, "estimate": round(estimate, 6),
                "cost": cost, "cache": cache, "note": note}

    def reserve(self, endpoint: str, target: str | None, audit_id: str | None, estimate: float,
                daily_budget: float, audit_cap: float | None = None) -> str:
        """Check the daily budget and the audit's own limit, and write the reservation, in one locked step.

        `audit_cap` is the most one audit may spend. What this `audit_id` already has settled or reserved, on any day,
        is added up here, so the limit holds across sessions of a resumed audit and whatever total was confirmed.
        Returns the call id."""
        with self._locked():
            calls = self._fold(self._read())
            if audit_cap is not None:
                used = round(sum(self._counted(c) for c in calls if c.get("audit_id") == audit_id), 6)
                if round(used + estimate, 6) > round(audit_cap, 6):
                    raise AuditCapReached(
                        f"this audit reached its ${audit_cap:.2f} DataForSEO limit: ${used:.4f} is already spent or reserved "
                        f"for it and this call is estimated at up to ${estimate:.4f}. No request was sent.", audit_cap, used)
            today = _now().date().isoformat()
            spent = round(sum(self._counted(c) for c in calls if c["ts"][:10] == today), 6)
            if round(spent + estimate, 6) > round(daily_budget, 6):
                raise BudgetExceeded(
                    f"DataForSEO daily budget reached: ${spent:.4f} already spent or reserved today (UTC), this call "
                    f"is estimated at up to ${estimate:.4f}, and the budget is ${daily_budget:.2f}. No request was sent.")
            row = self._row("reserve", "reserved", endpoint, target, audit_id, estimate, None, "miss")
            self._append(row)
            return row["id"]

    def settle(self, call_id: str, status: str, cost: float | None, note: str | None = None) -> None:
        """Record how a reserved call ended: its real cost, or that it may have been billed."""
        with self._locked():
            self._append({"id": call_id, "event": "settle", "status": status, "ts": _now().isoformat(timespec="seconds"),
                          "settled_ts": _now().isoformat(timespec="seconds"), "estimate": 0.0,
                          "cost": None if cost is None else round(float(cost), 6), "note": note})

    def note(self, event: str, endpoint: str, target: str | None, audit_id: str | None, cost: float = 0.0,
             cache: str = "miss", note: str | None = None) -> None:
        """A row that reserves nothing: a cache hit, or a call to a free endpoint."""
        with self._locked():
            self._read()  # refuse to add to a file that cannot be understood
            self._append(self._row(event, "settled", endpoint, target, audit_id, 0.0, cost, cache, note))
