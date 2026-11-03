"""The owner's manual checks of an audit's findings: one review file per audit (DECISIONS 301 (1)).

`review.json` beside the audit's report.json (the web app's artifacts folder; for a CLI report `<report>.review.json`):

    {"version": 1, "entries": [{"finding_id": "STR-12-c792bc34", "rule_id": "str12.language",
                                "result": "confirmed" | "rejected", "by": "who checked", "date": "2026-11-03",
                                "seen": "what was seen", "note": "optional text shown on the card"}]}

One entry per finding id; a later entry replaces an earlier one (its history is kept in `replaced`). A confirmed finding
is "measured, confirmed by manual check" and competes for the cards; a rejected one leaves the client PDF and stays in
the appendix as rejected (`client_selection`). The report itself is never changed: its digest and the release gate
judge the report, not this file. The web app's "Teyit edin" buttons and `build_data.py --confirm/--reject` write the
same file.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

VERSION = 1
RESULTS = ("confirmed", "rejected")
NAME = "review.json"
MAX_TEXT = 1000


def path_for(report_path: str | Path) -> Path:
    """The review file of a report: `review.json` in a web artifacts folder, else `<report>.review.json`."""
    p = Path(report_path)
    return p.with_name(NAME) if p.parent.name == "artifacts" else p.with_name(p.stem + ".review.json")


def load(path: str | Path | None) -> dict:
    if not path or not Path(path).is_file():
        return {"version": VERSION, "entries": []}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ValueError(f"{path}: not a review file (expected {{'version', 'entries': [...]}})")
    return data


def confirmations(review: dict) -> dict[str, dict]:
    """{finding id or rule id: entry}, the form `client_selection.select` reads."""
    out = {}
    for entry in review.get("entries") or []:
        if entry.get("result") in RESULTS:
            out[entry.get("finding_id") or entry.get("rule_id")] = entry
    return out


def entry(finding_id: str, result: str, *, by: str, seen: str, note: str | None = None, rule_id: str | None = None,
          when: str | None = None) -> dict:
    if result not in RESULTS:
        raise ValueError(f"result must be one of {RESULTS}, not {result!r}")
    if not finding_id or not by or not seen:
        raise ValueError("a manual check needs the finding id, who checked and what was seen")
    row = {"finding_id": str(finding_id)[:80], "result": result, "by": str(by)[:120], "date": when or date.today().isoformat(),
           "seen": str(seen)[:MAX_TEXT]}
    if rule_id:
        row["rule_id"] = str(rule_id)[:80]
    if note:
        row["note"] = str(note)[:MAX_TEXT]
    return row


def record(path: str | Path, row: dict) -> dict:
    """Add `row` to the review file at `path` (written whole, atomically); returns the file's content."""
    path = Path(path)
    review = load(path)
    kept, replaced = [], list(review.get("replaced") or [])
    for old in review["entries"]:
        (replaced if old.get("finding_id") == row["finding_id"] else kept).append(old)
    review = {"version": VERSION, "entries": kept + [row], **({"replaced": replaced} if replaced else {})}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".review-", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(review, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return review
