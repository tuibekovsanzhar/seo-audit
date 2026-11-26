"""DECISIONS 378: "Kural onayı" (Rule approval), a sheet of the team file, never the client Ek.

One row per rule behind the audit's findings: what the rule found in this audit, the SEO team's own pass condition for
the checklist items it answers to, its maturity (approved, disputed, not reviewed) with the expert verdicts behind it,
and an empty "Karar" column with a dropdown (Onayla / Sorgula). `tools/import_rule_approvals.py` writes a reviewer's
decisions from this sheet into `rule_approval.json`.
"""
from __future__ import annotations

from . import checklist, rule_maturity
from .xlsx import _col

NAMES = {"tr": "Kural onayı", "en": "Rule approval"}
HEADERS = {
    "tr": ["Kural", "Kontrol", "Bu denetimde", "Kontrol listesi maddesi", "Ekibin geçme koşulu", "Durum",
           "Uzman sonuçları", "Son uzman kararı", "Karar", "Not"],
    "en": ["Rule", "Check", "In this audit", "Checklist item", "Team's pass condition", "Status", "Expert results",
           "Latest expert verdict", "Decision", "Note"],
}
DECISION_COLUMN = 8  # "Karar" / "Decision", 0-based: column I
DECISIONS = {"tr": ["Onayla", "Sorgula"], "en": ["Approve", "Question"]}
STATUS = {"tr": {"approved": "Onaylı", "disputed": "Tartışmalı", "unreviewed": "İncelenmedi"},
          "en": {"approved": "Approved", "disputed": "Disputed", "unreviewed": "Not reviewed"}}
VERDICT = {"tr": {"correct": "doğru", "wrong": "yanlış", "incomplete": "eksik", "wording": "ifade"},
           "en": {"correct": "correct", "wrong": "wrong", "incomplete": "incomplete", "wording": "wording"}}
PLACEMENT = {"tr": {"card": "kart", "confirm": "teyit edin", "appendix": "yalnız ekte", "note": "not",
                    "own_limit": "Maya'nın sınırı", "rejected": "reddedildi"},
             "en": {"card": "card", "confirm": "confirm first", "appendix": "appendix only", "note": "note",
                    "own_limit": "Maya's own limit", "rejected": "rejected"}}
UNITS = {"tr": ("grup", "adres"), "en": ("groups", "addresses")}
ORDER = {"disputed": 0, "unreviewed": 1, "approved": 2}


def _results(row: dict | None, lang: str) -> str:
    if not row:
        return ""
    V = VERDICT[lang]
    parts = [f"{row.get(k, 0)} {V[k]}" for k in ("correct", "wrong", "incomplete")]
    if row.get("wording"):
        parts.append(f"{row['wording']} {V['wording']}")
    return " · ".join(parts)


def _latest(row: dict | None, lang: str) -> str:
    last = (row or {}).get("latest") or {}
    if not last:
        return ""
    return f"{VERDICT[lang].get(last.get('verdict'), last.get('verdict'))} ({last.get('review')}, {last.get('on')})"


def sheet(selection: dict, lang: str = "tr") -> dict | None:
    lang = "tr" if lang == "tr" else "en"
    rules: dict[str, dict] = {}
    for g in selection.get("groups") or []:
        for m in g.get("members") or []:
            rule = m.get("rule_id")
            if not rule:
                continue
            r = rules.setdefault(rule, {"check": m.get("check_id") or "", "groups": [], "urls": set(), "placements": []})
            if not any(x is g for x in r["groups"]):
                r["groups"].append(g)
                r["placements"].append(g.get("placement") or "")
            r["urls"].update(g.get("urls") or [])
    if not rules:
        return None
    unit_g, unit_a = UNITS[lang]
    rows = []
    for rule in sorted(rules, key=lambda x: (ORDER[rule_maturity.level(x)], x)):
        r = rules[rule]
        where = ", ".join(PLACEMENT[lang].get(p, p) for p in dict.fromkeys(r["placements"]) if p)
        items = checklist.items_for_rule(rule, r["check"])
        stats = rule_maturity.stats(rule)
        rows.append([rule, r["check"], f"{len(r['groups'])} {unit_g} · {len(r['urls'])} {unit_a}" + (f" · {where}" if where else ""),
                     "\n".join(f"{it['id']} {it['item']}" for it in items),
                     "\n".join(it["pass"] for it in items if it["pass"]),
                     STATUS[lang][rule_maturity.level(rule)], _results(stats, lang), _latest(stats, lang), "", ""])
    col = _col(DECISION_COLUMN + 1)
    return {"name": NAMES[lang], "header": HEADERS[lang], "rows": rows, "widths": [28, 9, 30, 34, 50, 13, 26, 34, 12, 30],
            "validations": [{"ref": f"{col}2:{col}{len(rows) + 1}", "list": DECISIONS[lang]}]}
