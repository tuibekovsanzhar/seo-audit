"""Per-rule accuracy from the SEO team's card reviews (docs/expert-reviews/*.json), DECISIONS 340.

Writes docs/expert-reviews/ACCURACY.md: for each rule, how many reviewed cards carried it and the expert's verdicts
(correct, wrong, wording, incomplete), the latest verdict, and the review it came from. tests/test_expert_review_340.py
checks the file matches the reviews. Run: python scripts/expert_accuracy.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs" / "expert-reviews"
OUT = FOLDER / "ACCURACY.md"
VERDICTS = ("correct", "wrong", "wording", "incomplete")


def reviews() -> list[dict]:
    out = []
    for path in sorted(FOLDER.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({**data, "_file": path.name})
    return sorted(out, key=lambda r: (r.get("reviewed_on") or "", r.get("review") or 1, r["_file"]))


def table() -> str:
    rows: dict[str, Counter] = defaultdict(Counter)
    last: dict[str, tuple[str, str]] = {}
    revs = reviews()
    for r in revs:
        for card in r.get("cards") or []:
            for rule in card.get("rule_ids") or []:
                rows[rule][card["verdict"]] += 1
                last[rule] = (card["verdict"], r["_file"].removesuffix(".json"))
    lines = ["# Expert review accuracy by rule", "",
             "Made by `scripts/expert_accuracy.py` from " + ", ".join(f"`{r['_file']}`" for r in revs)
             + " (DECISIONS 338, 340). A card's verdict counts once for each rule on it; \"wrong\" is the expert's verdict, "
               "before the evidence was checked (each review file says what the evidence showed and what was fixed).", "",
             "| Rule | Cards reviewed | Correct | Wrong | Wording | Incomplete | Share correct | Latest |",
             "|---|---|---|---|---|---|---|---|"]
    for rule in sorted(rows):
        c = rows[rule]
        n = sum(c.values())
        lines.append(f"| `{rule}` | {n} | " + " | ".join(str(c[v]) for v in VERDICTS)
                     + f" | {round(100 * c['correct'] / n)}% | {last[rule][0]} ({last[rule][1]}) |")
    total = Counter()
    for r in revs:
        total.update(card["verdict"] for card in r.get("cards") or [])
    cards = sum(total.values())
    lines += ["", f"Cards reviewed: {cards}; " + ", ".join(f"{v} {total[v]}" for v in VERDICTS)
              + (f" ({round(100 * total['correct'] / cards)}% correct)." if cards else "."), ""]
    return "\n".join(lines)


if __name__ == "__main__":
    OUT.write_text(table(), encoding="utf-8")
    print(f"wrote {OUT}")
