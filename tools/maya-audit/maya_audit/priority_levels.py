"""P0-P3 on the cards: the team's sector audit method (DECISIONS 324; `docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm`).

The team scores a finding as 20 × impact × page weight × spread × status factor / effort and calls it P0 at 160 or
more, P1 at 80, P2 at 30, P3 above 0. Maya shows that label beside the severity, with three choices the owner made
(2026-11-08): the impact comes from Maya's severity (Blocker 5, High 4, Medium 3, Low 2), the effort is a neutral 3 for
every card (so an easy fix never jumps above a hard one; effort stays its own number on the card), and an indexing
blocker on a homepage or on a broad part of the sector's first two page types is P0 whatever it scores (the method's
manual P0, made automatic; a person can set or take off P0 in the review file).

The label never changes a severity, a confidence, a placement, the card order, the priority score or the quick wins.
Agent defaults: the page weight is the business profile's weight of the page's type / 100 (with "Diğer", Stage 3's type
weight); the spread is the method's 1-5 scale over the pages read of that type (one page of several 1; a homepage is its
own template, 5); a finding with no address, a host-level one (certificate, host redirects) or one about site files only (robots.txt,
sitemaps) is site-wide (weight 1, spread 5); one whose addresses were none of them read
weighs as an unmatched page (0.25) with spread 1 (one address) or 2; the status factor is 1 for an issue-type Blocker,
High or Medium and 0.5 otherwise (the method's Hatalı / Kısmen Uygun); a card takes its highest-scoring finding.
"""
from __future__ import annotations

from .client_selection import PROBLEM, affected, host_level, rule_type, severity

IMPACT = {"S1": 5, "S2": 4, "S3": 3, "S4": 2}
EFFORT = 3
THRESHOLDS = ((160, "P0"), (80, "P1"), (30, "P2"))
LEVELS = ("P0", "P1", "P2", "P3")
BROAD = 4                 # spread 4 = 31-70% of a page type's pages (the method's scale)
NOT_READ_WEIGHT = 0.25
# The method's manual P0: noindex / robots / 5xx / wrong canonical / JavaScript-only content on a key template.
P0_RULES = ("acc2.blocks", "acc3.noindex", "acc3.robots_noindex", "idx1.5xx", "idx1.empty", "idx4.other_site",
            "idx4.broken", "idx4.different", "idx4.redirect_loop", "rnd1.missing")
SITEWIDE_P0 = ("acc2.blocks.sitewide",)
# DECISIONS 347 (owner, atasunoptik: robots.txt blocking only ByteDance's training bot came out P0): a policy choice is
# never urgent. A card made only of these rules is at most P2, whatever it scores; a person may still set P0 by hand.
POLICY_RULES = ("acc2.training_block",)
POLICY_CAP = "P2"
# DECISIONS 329 (owner, after enpara 87f0425a's High broken-link card came out P3): the lowest level of a High or
# Blocker card. The score and the card order are unchanged.
HIGH_FLOOR = {"S1": "P2", "S2": "P2"}
WORDS = {"tr": {"P0": "Acil", "P1": "Öncelikli", "P2": "Planlı", "P3": "Sırası gelince"},
         "en": {"P0": "Urgent", "P1": "Priority", "P2": "Planned", "P3": "When convenient"}}
REASONS = {"tr": {"auto": "otomatik: indeksleme engeli ({where})", "set": "elle P0 yapıldı ({by}, {date})",
                  "removed": "otomatik P0 elle kaldırıldı ({by}, {date})", "home": "ana sayfa", "site": "site geneli",
                  "type": "{type}: {n}/{total} sayfa", "floor": "yüksek önem: en az P2",
                  "policy": "politika tercihi: en fazla P2"},
           "en": {"auto": "automatic: indexing blocker ({where})", "set": "set to P0 by hand ({by}, {date})",
                  "removed": "automatic P0 taken off by hand ({by}, {date})", "home": "homepage", "site": "whole site",
                  "type": "{type}: {n}/{total} pages", "floor": "high severity: at least P2", "policy": "a policy choice: at most P2"}}


def spread(n: int, total: int) -> int:
    """The method's spread: 1 a single address, 2 up to 10%, 3 up to 30%, 4 up to 70%, 5 more (of that type's pages)."""
    if n <= 0:
        return 0
    if n == 1 and total > 1:
        return 1
    share = n / max(total, 1)
    return 2 if share <= .10 else 3 if share <= .30 else 4 if share <= .70 else 5


def level(score: float) -> str | None:
    if not score or score <= 0:
        return None
    return next((name for floor, name in THRESHOLDS if score >= floor), "P3")


def _matches(rule: str | None, prefixes: tuple[str, ...]) -> bool:
    rule = rule or ""
    return any(rule == p or rule.startswith(p + ".") for p in prefixes)


class Context:
    """What the labels need from an audit: each page read's type and weight, and the profile's first two types."""

    def __init__(self, importance: dict[str, dict], summary: dict, read: set[str]):
        from . import business_types as bt
        from .page_groups import TYPE_WEIGHT
        info = (summary or {}).get("business_type") or {}
        pid = info.get("id") if isinstance(info, dict) else None
        self.profile = bt.profile(pid) if pid and pid != bt.DEFAULT else None
        self.read = {u.rstrip("/") for u in read}
        records = {u.rstrip("/"): r for u, r in importance.items() if u and isinstance(r, dict)}
        self.type_of: dict[str, str] = {}
        for url in self.read:  # every page read counts; one with no grouping record is of no known type ("other")
            rec = records.get(url) or {}
            self.type_of[url] = (rec.get("business_page_type") if self.profile else None) or rec.get("page_type") or "other"
        self.count: dict[str, int] = {}
        for kind in self.type_of.values():
            self.count[kind] = self.count.get(kind, 0) + 1
        self.first_two = {t["id"] for t in (self.profile or {}).get("page_types", []) if t.get("rank") in (1, 2)}
        self._stage3 = TYPE_WEIGHT
        self._bt = bt
        self.labels = {t["id"]: t["label"] for t in (self.profile or {}).get("page_types", [])}

    def weight(self, kind: str) -> float:
        if self.profile:
            return self._bt.weight(self.profile, kind) / 100
        return self._stage3.get(kind, self._stage3["other"]) / 100


SITE_FILES = (".xml", ".xml.gz", ".txt", ".gz")


def _site_wide(finding: dict, urls: list[str]) -> bool:
    """A finding about the whole site: no address, a host's own (certificate, host redirects), or only site files
    (robots.txt, sitemaps)."""
    from urllib.parse import urlsplit
    return not urls or bool(host_level(finding)) or all(urlsplit(u).path.lower().endswith(SITE_FILES) for u in urls)


def _spots(ctx: Context, urls: list[str], finding: dict | None = None) -> list[tuple[str | None, float, int, int, int]]:
    """[(type, weight, spread, affected pages of the type, pages read of the type)] for one finding's addresses."""
    if _site_wide(finding or {}, urls):
        return [(None, 1.0, 5, 0, 0)]
    read = [u.rstrip("/") for u in urls if u.rstrip("/") in ctx.type_of]
    if not read:
        return [(None, NOT_READ_WEIGHT, 1 if len(urls) == 1 else 2, 0, 0)]
    out = []
    for kind in sorted({ctx.type_of[u] for u in read}):
        n = sum(1 for u in read if ctx.type_of[u] == kind)
        total = ctx.count.get(kind, n)
        out.append((kind, ctx.weight(kind), 5 if kind == "home" else spread(n, total), n, total))
    return out


def label(group: dict, ctx: Context, lists: dict | None, confirmations: dict | None, lang: str = "tr") -> dict:
    """{"level", "score", "auto_p0", "manual", "basis"} for one card-group; level None only for an Info group."""
    best: dict | None = None
    auto: str | None = None
    words = REASONS[lang]
    for m in group.get("members") or []:
        sev = severity(m)
        impact = IMPACT.get(sev, 0)
        factor = 1.0 if sev in ("S1", "S2", "S3") and rule_type(m.get("rule_id")) == "issue" else 0.5
        urls = affected(m, lists)
        for kind, weight, spr, n, total in _spots(ctx, urls, m):
            score = round(20 * impact * weight * spr * factor / EFFORT, 1)
            if best is None or score > best["score"]:
                best = {"score": score, "finding_id": m.get("id"), "rule_id": m.get("rule_id"), "severity": sev,
                        "page_type": kind, "weight": weight, "spread": spr, "impact": impact, "factor": factor,
                        "pages": n, "of": total}
            if sev in PROBLEM and _matches(m.get("rule_id"), P0_RULES) and kind and n and \
                    (kind == "home" or (kind in ctx.first_two and spr >= BROAD)):
                where = words["home"] if kind == "home" else words["type"].format(
                    type=(ctx.labels.get(kind) or {}).get(lang, kind), n=n, total=total)
                auto = auto or words["auto"].format(where=where)
        if sev in PROBLEM and _matches(m.get("rule_id"), SITEWIDE_P0):
            auto = auto or words["auto"].format(where=words["site"])
    score = best["score"] if best else 0.0
    computed = level(score)
    if computed is None and any(severity(m) in PROBLEM for m in group.get("members") or []):
        computed = "P3"  # DECISIONS 325: every problem card has a level; pages that weigh 0 (search, cart) make it P3
    floor = None
    if group.get("severity") in HIGH_FLOOR and computed in (None, "P3"):
        # DECISIONS 329 (owner): a High (or Blocker) card is never P3; at least P2. The card order does not change.
        computed, floor = HIGH_FLOOR[group["severity"]], words["floor"]
    if group.get("placement") == "confirm":
        auto = None  # not established yet: no automatic P0 for a finding waiting in "Teyit edin"
    mark = None
    for fid in group.get("finding_ids") or []:
        mark = (confirmations or {}).get("p0:" + str(fid)) or mark
    members = group.get("members") or []
    if members and all(_matches(m.get("rule_id"), POLICY_RULES) for m in members):
        auto = None
        if computed in ("P0", "P1"):
            computed, floor = POLICY_CAP, words.get("policy") or floor
    final, reason = ("P0", auto) if auto else (computed, None)
    if mark and mark.get("action") == "set":
        final, reason = "P0", words["set"].format(by=mark.get("by", ""), date=mark.get("date", ""))
    elif mark and mark.get("action") == "removed":
        final = "P1" if (computed == "P0" or auto) else computed
        reason = words["removed"].format(by=mark.get("by", ""), date=mark.get("date", ""))
    return {"level": final, "score": score, "auto_p0": auto, "manual": mark, "reason": reason or (floor if final == computed else None),
            "basis": best, "floor": floor}


def annotate(rows: list[dict], importance: dict[str, dict], summary: dict, read: set[str], lists: dict | None,
             confirmations: dict | None) -> None:
    """Set `p_level` on every group (DECISIONS 324). Words for the reason are Turkish and English (`p_level_en`)."""
    ctx = Context(importance, summary, read)
    for g in rows:
        g["p_level"] = label(g, ctx, lists, confirmations, "tr")
        g["p_level_en"] = label(g, ctx, lists, confirmations, "en")


def word(level_: str | None, lang: str = "tr") -> str | None:
    """The plain word of a level for a business owner (the client brief): no codes."""
    return WORDS.get(lang, WORDS["tr"]).get(level_ or "")
