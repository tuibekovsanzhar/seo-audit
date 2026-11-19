"""DECISIONS 373: every SEO-expert note as a label that a rebuilt saved audit must hold (the expert lock).

The labels live with the reviews, in `docs/expert-reviews/<brand>-<audit>.json`: each reviewed card can carry `labels`,
written from the note. A "wrong" note becomes `must_not_find` (the false finding, or the false wording, must never come
back); a "correct" note, or one asking for a detail ("which links?"), becomes `must_find` (the finding, or its detail,
must be there). `scripts/real_sites_benchmark.py expert` rebuilds the noted audits from a frozen copy of their saved
pages (outside the repository, `MAYA_AUDIT_BENCHMARK_DIR`) and checks every label; `tests/test_expert_lock.py` runs it
in the suite, and `tools/fix_log.py` gives an item "Düzeltildi" only when its labels hold.

A label tests one of (`on`):
    finding   a finding of `rules` (above Info unless `any_severity`) exists / does not
    card      a card carries a finding of `rules` / does not
    card_text the cards of `rules` (or the cards whose title matches `title`) say `regex` in `field` / do not
    row       a row of `sheet` whose `rule_column` value is in `rules` says `regex` in `column` / no such row says it

Nothing here names a brand; the reviews name only where a note was made."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEWS = ROOT / "docs" / "expert-reviews"
SEVERE = ("S1", "S2", "S3", "S4")
KINDS = ("must_find", "must_not_find")


def reviews(folder: Path = REVIEWS) -> list[dict]:
    out = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({**data, "_file": path.name})
    return out


def labels(folder: Path = REVIEWS) -> list[dict]:
    """Every label of every review, with the audit it is checked on (`audit_id`) and the note it came from."""
    out = []
    for review in reviews(folder):
        audit = review.get("audit_id")
        for card in review.get("cards") or []:
            for label in card.get("labels") or []:
                out.append({**label, "audit_id": label.get("audit_id") or audit, "review": review["_file"],
                            "card": card.get("card"), "note": card.get("expert_note"), "verdict": card.get("verdict")})
    return out


def validate(items: list[dict]) -> list[str]:
    """Problems with the labels (empty when they are well formed): an id, a kind, an audit, what is tested."""
    errors, seen = [], set()
    for x in items:
        lid = x.get("id")
        if not lid or lid in seen:
            errors.append(f"label without a unique id: {lid!r}")
        seen.add(lid)
        if x.get("kind") not in KINDS:
            errors.append(f"{lid}: kind must be one of {KINDS}")
        if not x.get("audit_id"):
            errors.append(f"{lid}: no audit to check it on")
        on = x.get("on")
        if on not in ("finding", "card", "card_text", "row"):
            errors.append(f"{lid}: unknown 'on' {on!r}")
        if on in ("finding", "card") and not x.get("rules"):
            errors.append(f"{lid}: no rules")
        if on in ("card_text", "row") and not x.get("regex"):
            errors.append(f"{lid}: no regex")
        if on == "row" and not x.get("sheet"):
            errors.append(f"{lid}: no sheet")
    return errors


def _rule_in(rule: str | None, rules) -> bool:
    rule = rule or ""
    return any(rule == r or (r.endswith(".") and rule.startswith(r)) for r in rules or [])


def _findings(ctx: dict) -> list[dict]:
    return [f for c in ctx["report"].get("checks") or [] for f in c.get("findings") or []]


def _cards(ctx: dict, label: dict) -> list[dict]:
    if label.get("title"):
        return [t for t in ctx["cards"] if re.search(label["title"], t.get("title") or "", re.I)]
    ids = {f["id"] for f in _findings(ctx) if _rule_in(f.get("rule_id"), label.get("rules"))}
    return [t for t in ctx["cards"] if set(t.get("finding_ids") or []) & ids]


def _text(card: dict, field: str) -> str:
    value = card.get(field)
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value or "")


def present(label: dict, ctx: dict) -> tuple[bool, str]:
    """(whether what the label names is there, what was seen)."""
    on = label["on"]
    if on == "finding":
        hits = [f for f in _findings(ctx) if _rule_in(f.get("rule_id"), label["rules"])
                and (label.get("any_severity") or f.get("severity") in SEVERE)]
        return bool(hits), f"{len(hits)} finding(s): " + ", ".join(sorted({f['id'] for f in hits})[:3])
    if on == "card":
        cards = _cards(ctx, label)
        return bool(cards), f"{len(cards)} card(s): " + "; ".join(str(t.get("title")) for t in cards[:2])
    if on == "card_text":
        cards = _cards(ctx, label)
        said = [t for t in cards if re.search(label["regex"], _text(t, label.get("field") or "title"), re.I)]
        return bool(said), f"{len(said)} of {len(cards)} card(s) say it"
    rows = ctx["book"].get(label["sheet"]) or []
    if not rows:
        return False, f"no sheet {label['sheet']!r}"
    head = rows[0]
    col = head.index(label["column"]) if label.get("column") in head else None
    key = head.index(label.get("rule_column") or "Kural") if (label.get("rule_column") or "Kural") in head else None
    hits = 0
    for r in rows[1:]:
        if label.get("rules") and (key is None or key >= len(r) or not _rule_in(str(r[key]), label["rules"])):
            continue
        cells = [str(r[col])] if col is not None and col < len(r) else [str(c) for c in r]
        if any(re.search(label["regex"], c, re.I) for c in cells):
            hits += 1
    return hits > 0, f"{hits} row(s) of {label['sheet']!r} say it"


def check(label: dict, ctx: dict | None) -> dict:
    """{"id", "kind", "ok", "seen"}: ok is True when the label holds, None when its audit was not rebuilt."""
    if ctx is None:
        return {"id": label["id"], "kind": label["kind"], "ok": None, "seen": "audit not in the frozen set"}
    there, seen = present(label, ctx)
    ok = there if label["kind"] == "must_find" else not there
    return {"id": label["id"], "kind": label["kind"], "ok": ok, "seen": seen}


def active(items: list[dict]) -> list[dict]:
    """The labels to check: a label a later review of the same expert overturned (`superseded_by`) is kept in the review
    for the record but not checked."""
    return [x for x in items if not x.get("superseded_by")]


def run(items: list[dict], built: dict[str, dict]) -> list[dict]:
    """Every active label checked on its rebuilt audit (`built`: {audit id prefix: ctx})."""
    out = []
    for x in active(items):
        ctx = next((c for k, c in built.items() if k.startswith(x["audit_id"][:8]) or x["audit_id"].startswith(k)), None)
        out.append({**check(x, ctx), "audit_id": x["audit_id"], "review": x["review"], "card": x["card"],
                    "note": x.get("note")})
    return out
