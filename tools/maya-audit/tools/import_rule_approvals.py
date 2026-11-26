"""Write the SEO team's rule decisions from a team file's "Kural onayı" sheet into rule_approval.json (DECISIONS 378).

A reviewer fills the "Karar" column (Onayla / Sorgula; Approve / Question in an English file) and saves the file.
"Onayla" puts the rule under "approved" with who and when, and takes it out of "questioned"; "Sorgula" the reverse.
A blank decision changes nothing. An unknown word, or a rule rule_ids.json does not hold, stops the run: nothing is
written. Without --write it prints what would change.

  .venv/bin/python tools/import_rule_approvals.py TEAM.xlsx --by "İlginay" [--write]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maya_audit import rule_sheet, xlsx  # noqa: E402

FILE = ROOT / "maya_audit" / "rule_approval.json"
RULE_IDS = ROOT / "maya_audit" / "rule_ids.json"
WORDS = {"onayla": "approve", "approve": "approve", "sorgula": "question", "question": "question"}


def _known_rules() -> set[str]:
    """The rule ids of the catalogue ({check: [[rule_id, pattern], ...]}), of the review register and of the file."""
    from maya_audit import rule_maturity
    data = json.loads(RULE_IDS.read_text(encoding="utf-8"))
    known = {pair[0] for pairs in (data.get("rules") or {}).values() for pair in pairs if pair}
    known |= set(rule_maturity._register())
    current = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    return known | set(current.get("approved") or {}) | set(current.get("questioned") or {})


def decisions(path: str | Path) -> tuple[list[dict], list[str]]:
    """(the decisions in the sheet, the problems found) from a saved team file."""
    sheets = xlsx.read(Path(path))
    name = next((n for n in rule_sheet.NAMES.values() if n in sheets), None)
    if name is None:
        return [], [f"{Path(path).name}: no sheet named {' or '.join(rule_sheet.NAMES.values())}"]
    rows = sheets[name]
    header = [str(c or "").strip() for c in rows[0]]
    lang = "tr" if name == rule_sheet.NAMES["tr"] else "en"
    want = rule_sheet.HEADERS[lang]
    col = {key: header.index(want[i]) for key, i in (("rule", 0), ("decision", 8), ("note", 9)) if want[i] in header}
    if "rule" not in col or "decision" not in col:
        return [], [f"{name}: the columns {want[0]!r} and {want[8]!r} are needed"]
    known = _known_rules()
    out, problems = [], []
    for n, r in enumerate(rows[1:], 2):
        cell = lambda k: (str(r[col[k]]).strip() if k in col and col[k] < len(r) and r[col[k]] is not None else "")  # noqa: E731
        rule, word = cell("rule"), cell("decision")
        if not rule or not word:
            continue
        decision = WORDS.get(word.casefold())
        if decision is None:
            problems.append(f"{name} row {n}: {word!r} is not one of {', '.join(rule_sheet.DECISIONS[lang])}")
        if rule not in known:
            problems.append(f"{name} row {n}: {rule!r} is not a Maya rule (rule_ids.json)")
        if decision and rule in known:
            out.append({"rule": rule, "decision": decision, "note": cell("note")})
    return out, problems


def apply(data: dict, rows: list[dict], by: str, on: str) -> list[str]:
    """Change `data` in place; returns one line per change."""
    approved, questioned = data.setdefault("approved", {}), data.setdefault("questioned", {})
    changes = []
    for row in rows:
        entry = {"by": by, "on": on, "note": row["note"]}
        if row["decision"] == "approve":
            approved[row["rule"]] = entry
            questioned.pop(row["rule"], None)
            changes.append(f"approve  {row['rule']}")
        else:
            questioned[row["rule"]] = entry
            approved.pop(row["rule"], None)
            changes.append(f"question {row['rule']}")
    return changes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("team_file")
    ap.add_argument("--by", required=True, help="the reviewer's name, recorded with each decision")
    ap.add_argument("--write", action="store_true", help="write rule_approval.json (otherwise only print)")
    args = ap.parse_args(argv)
    rows, problems = decisions(args.team_file)
    for p in problems:
        print("PROBLEM", p)
    if problems:
        print("nothing written")
        return 1
    data = json.loads(FILE.read_text(encoding="utf-8"))
    changes = apply(data, rows, args.by, date.today().isoformat())
    for line in changes or ["no decision in the sheet"]:
        print(line)
    if args.write and changes:
        FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
