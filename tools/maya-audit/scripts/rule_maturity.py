"""The rule maturity register from the SEO team's card reviews (docs/expert-reviews/*.json), DECISIONS 378.

Writes maya_audit/rule_maturity.json: for each rule, how many reviewed cards carried it and the verdicts (correct,
wrong, incomplete, wording), the brands it was found correct on, and the latest verdict with its review and date.
`maya_audit.rule_maturity` reads only that packaged file at run time; tests/test_rule_maturity.py checks it matches the
reviews. Run: python scripts/rule_maturity.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs" / "expert-reviews"
OUT = ROOT / "maya_audit" / "rule_maturity.json"
VERDICTS = ("correct", "wrong", "incomplete", "wording")
ABOUT = ("DECISIONS 378: each rule's record in the SEO team's card reviews (docs/expert-reviews), made by "
         "scripts/rule_maturity.py. A card's verdict counts once for each rule on it; the brand is the review file's "
         "name before its first '-'. maya_audit/rule_maturity.py turns this into a level: approved, disputed or "
         "unreviewed.")


def reviews(folder: Path | None = None) -> list[dict]:
    """Every review file, ordered by review date, then review number, then file name (as ACCURACY.md orders them)."""
    out = []
    for path in sorted((folder or FOLDER).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({**data, "_file": path.name})
    return sorted(out, key=lambda r: (r.get("reviewed_on") or "", r.get("review") or 1, r["_file"]))


def build(folder: Path | None = None) -> dict:
    counts: dict[str, Counter] = {}
    brands: dict[str, set] = {}
    latest: dict[str, dict] = {}
    for r in reviews(folder):
        brand = r["_file"].split("-", 1)[0]
        for card in r.get("cards") or []:
            verdict = card.get("verdict")
            if verdict not in VERDICTS:
                continue
            for rule in dict.fromkeys(card.get("rule_ids") or []):
                counts.setdefault(rule, Counter())[verdict] += 1
                if verdict == "correct":
                    brands.setdefault(rule, set()).add(brand)
                latest[rule] = {"verdict": verdict, "review": r["_file"].removesuffix(".json"),
                                "on": r.get("reviewed_on") or ""}
    rules = {rule: {**{v: counts[rule][v] for v in VERDICTS}, "brands_correct": sorted(brands.get(rule, ())),
                    "latest": latest[rule]}
             for rule in sorted(counts)}
    return {"_about": ABOUT, "rules": rules}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
