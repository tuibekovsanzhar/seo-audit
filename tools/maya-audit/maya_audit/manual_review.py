"""The owner's manual checks of an audit's findings: one review file per audit (DECISIONS 301 (1)).

`review.json` beside the audit's report.json (the web app's artifacts folder; for a CLI report `<report>.review.json`):

    {"version": 1, "entries": [{"finding_id": "STR-12-c792bc34", "rule_id": "str12.language",
                                "result": "confirmed" | "rejected", "by": "who checked", "date": "2026-11-03",
                                "seen": "what was seen", "note": "optional text shown on the card"}]}

DECISIONS 324: the same file keeps the person's P0 marks of cards, apart from the checks, under `"p0"`:
`[{"finding_id": <a finding of the card>, "action": "set" | "removed", "by", "date", "note"}]` ("Acil" set by hand, or
the automatic P0 taken off). They reach `client_selection` as `p0:<finding id>` keys of `confirmations()`.

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
P0_ACTIONS = ("set", "removed")
P0_PREFIX = "p0:"
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
    for entry in review.get("p0") or []:  # DECISIONS 324: the person's P0 marks of cards
        if isinstance(entry, dict) and entry.get("action") in P0_ACTIONS and entry.get("finding_id"):
            out[P0_PREFIX + str(entry["finding_id"])] = entry
    return out


def p0_entry(finding_id: str, action: str, *, by: str, note: str | None = None, when: str | None = None) -> dict:
    """A P0 mark of a card (DECISIONS 324): "set" makes it P0 ("Acil"), "removed" takes the automatic P0 off."""
    if action not in P0_ACTIONS:
        raise ValueError(f"action must be one of {P0_ACTIONS}, not {action!r}")
    if not finding_id or not str(by or "").strip():
        raise ValueError("a P0 mark needs the finding id and who marked it")
    row = {"finding_id": str(finding_id)[:80], "action": action, "by": str(by).strip()[:120], "date": when or date.today().isoformat()}
    if note and str(note).strip():
        row["note"] = str(note).strip()[:MAX_TEXT]
    return row


def _write(path: Path, review: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".review-", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(review, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _keep(review: dict, entries: list, p0: list, replaced: list) -> dict:
    out = {"version": VERSION, "entries": entries}
    if p0:
        out["p0"] = p0
    if replaced:
        out["replaced"] = replaced
    return out


def record_p0(path: str | Path, row: dict) -> dict:
    """Add a P0 mark (one per finding id; a later one replaces an earlier one, kept under `replaced`)."""
    path = Path(path)
    review = load(path)
    kept, replaced = [], list(review.get("replaced") or [])
    for old in review.get("p0") or []:
        (replaced if old.get("finding_id") == row["finding_id"] else kept).append(old)
    review = _keep(review, review["entries"], kept + [row], replaced)
    _write(path, review)
    return review


def undo_p0(path: str | Path, finding_ids: list[str]) -> list[str]:
    """Take the P0 marks of these findings out (kept under `replaced` with the date); returns the ids taken out."""
    path = Path(path)
    review = load(path)
    wanted = set(finding_ids)
    kept, gone = [], []
    for old in review.get("p0") or []:
        (gone if old.get("finding_id") in wanted else kept).append(old)
    if not gone:
        return []
    replaced = list(review.get("replaced") or []) + [{**old, "undone": date.today().isoformat()} for old in gone]
    _write(path, _keep(review, review["entries"], kept, replaced))
    return [old.get("finding_id") for old in gone]


def entry(finding_id: str, result: str, *, by: str, seen: str | None = None, note: str | None = None, rule_id: str | None = None,
          when: str | None = None) -> dict:
    if result not in RESULTS:
        raise ValueError(f"result must be one of {RESULTS}, not {result!r}")
    # DECISIONS 310: who checked is required; what was seen is optional (the owner's choice for the web form).
    if not finding_id or not str(by or "").strip():
        raise ValueError("a manual check needs the finding id and who checked")
    row = {"finding_id": str(finding_id)[:80], "result": result, "by": str(by).strip()[:120], "date": when or date.today().isoformat()}
    if seen and str(seen).strip():
        row["seen"] = str(seen).strip()[:MAX_TEXT]
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
    review = _keep(review, kept + [row], list(review.get("p0") or []), replaced)
    _write(path, review)
    return review


def undo(path: str | Path, finding_ids: list[str]) -> list[str]:
    """Take the current entries of these findings out of the review file (DECISIONS 310: "Geri al"): each moves to
    `replaced`, so its history is kept, and the finding is unchecked again. Returns the ids taken out."""
    path = Path(path)
    review = load(path)
    wanted = set(finding_ids)
    kept, gone = [], []
    for old in review["entries"]:
        (gone if old.get("finding_id") in wanted else kept).append(old)
    if not gone:
        return []
    replaced = list(review.get("replaced") or []) + [{**old, "undone": date.today().isoformat()} for old in gone]
    _write(path, _keep(review, kept, list(review.get("p0") or []), replaced))
    return [old.get("finding_id") for old in gone]
