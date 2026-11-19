"""Import an SEO expert's notes from a reviewed Ek into docs/expert-reviews/ (DECISIONS 373).

    .venv/bin/python tools/import_notes.py EK.xlsx --brand mmi --audit 536b4b64 [--answer CARD=verdict ...] [--write]

Reads the "Özet" sheet of an Ek a reviewer saved in Excel, LibreOffice or Google Sheets: the notes column is the one whose
header names a note ("İlginay's not", "Not", "Notes"), or column J. Each card with a note becomes a review item with
its rules, read from the Ek's own "Bulgu bazında" rows of that card (column "Kural"), and a verdict from the note's words:

    Doğru                                      -> correct
    Hatalı / Yanlış                            -> wrong
    hangi / nerede / eksik / anlaşılmıyor ...  -> incomplete

A note the words do not settle (none of them, more than one, or "Doğru" with more after it: "Doğru ama …") is listed as
unsure and nothing is written until it is answered with --answer CARD=verdict (correct, wrong, incomplete, wording).
Without --write the result is printed. The labels the lock checks (`maya_audit/expert_labels.py`) are added by hand.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VERDICTS = ("correct", "wrong", "incomplete", "wording")
WRONG = re.compile(r"\b(hatal[ıi]|yanl[ıi][şs])", re.I)
INCOMPLETE = re.compile(r"\b(hangi|nerede|eksik|anla[şs][ıi]lm[ıi]yor|belirtilmeli|eklenmeli|verilmeli|yazm[ıi]yor)", re.I)
CORRECT = re.compile(r"^\s*do[ğg]ru\b", re.I)
NOTE_HEADER = re.compile(r"\bnot(e|lar|es)?\b|\bnot$", re.I)


def fold(text: str) -> str:
    return (text or "").replace("İ", "i").replace("I", "ı").lower()


def classify(note: str) -> str | None:
    """The verdict a note's words give, or None when they do not settle it."""
    text = fold(note).strip()
    if not text:
        return None
    found = set()
    if WRONG.search(text):
        found.add("wrong")
    if INCOMPLETE.search(text):
        found.add("incomplete")
    if CORRECT.match(text):
        rest = CORRECT.sub("", text).strip(" .,!;:-")
        found.add("correct" if not rest else "correct+")
    if found == {"correct"}:
        return "correct"
    if len(found) == 1 and "correct+" not in found:
        return next(iter(found))
    return None


def note_column(header: list) -> int:
    for i, h in enumerate(header):
        if NOTE_HEADER.search(fold(str(h))):
            return i
    return 9


def read_notes(path: Path) -> dict:
    from maya_audit import xlsx
    book = xlsx.read_any(path)
    summary = book.get("Özet") or []
    if not summary:
        raise SystemExit(f"{path.name}: no 'Özet' sheet")
    col = note_column(summary[0])
    rules: dict[int, list[str]] = {}
    found = book.get("Bulgu bazında") or []
    if found:
        head = [str(h) for h in found[0]]
        k, r = (head.index("Kart") if "Kart" in head else None), (head.index("Kural") if "Kural" in head else None)
        for row in found[1:]:
            if k is None or r is None or k >= len(row) or r >= len(row):
                continue
            try:
                n = int(float(row[k]))
            except (TypeError, ValueError):
                continue
            if row[r] and row[r] not in rules.setdefault(n, []):
                rules[n].append(row[r])
    cards = []
    for i, row in enumerate(summary[1:], 2):
        note = str(row[col]).strip() if col < len(row) and row[col] is not None else ""
        if not note:
            continue
        try:
            n = int(float(row[0]))
        except (TypeError, ValueError):
            continue
        cards.append({"card": n, "title": str(row[1]), "rule_ids": rules.get(n, []), "expert_note": note,
                      "verdict": classify(note), "cell": f"{chr(65 + col)}{i}"})
    return {"header": str(summary[0][col]) if col < len(summary[0]) else "", "cards": cards}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ek", type=Path)
    ap.add_argument("--brand", required=True)
    ap.add_argument("--audit", required=True, help="the saved audit's id (8 characters or more)")
    ap.add_argument("--reviewer", default="İlginay (SEO)")
    ap.add_argument("--reviewed-on", default=date.today().isoformat())
    ap.add_argument("--answer", action="append", default=[], help="CARD=verdict for a note the words do not settle")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    got = read_notes(args.ek)
    answers = {}
    for a in args.answer:
        card, _, verdict = a.partition("=")
        if verdict not in VERDICTS:
            ap.error(f"--answer {a}: verdict must be one of {VERDICTS}")
        answers[int(card)] = verdict
    unsure = []
    for c in got["cards"]:
        if c["card"] in answers:
            c["verdict"], c["answered"] = answers[c["card"]], True
        if c["verdict"] is None:
            unsure.append(c)
    for c in got["cards"]:
        print(f"{c['cell']:<5} card {c['card']:>2} {str(c['verdict'] or 'UNSURE'):<11} {c['title'][:45]:<45} | {c['expert_note'][:70]}")
    if unsure:
        print("\nUnsure, answer with --answer CARD=verdict: " + ", ".join(str(c["card"]) for c in unsure))
        return 2
    out = {"_about": "Expert review of Maya Audit cards, imported from the reviewed Ek by tools/import_notes.py (DECISIONS "
                     "373). verdict: correct, wrong, incomplete, wording; labels: what the expert lock checks.",
           "audit": f"{args.brand} {args.audit[:8]}", "audit_id": args.audit[:8], "reviewer": args.reviewer,
           "reviewed_on": args.reviewed_on, "source_file": f"{args.ek.name}, Özet, column \"{got['header']}\"",
           "cards": got["cards"]}
    path = ROOT / "docs" / "expert-reviews" / f"{args.brand}-{args.audit[:8]}.json"
    if args.write:
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
