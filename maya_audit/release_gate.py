"""One release gate for a report and for the client report built from it (DECISIONS 278).

The engine, the professional report and the validation note used to check themselves in different places, and none of
them checked that a card, a PDF line or a validation row says what its finding says. This module is the one place that
does. It never changes a finding: it returns violations, and a decision made from them:

    PASS         no violation;
    CONDITIONAL  only soft violations: the output may go out, labelled conditional, with the violations listed;
    BLOCKED      at least one hard violation: the output must not go out (the skill refuses to print the PDF).

It reads only the finding contract (schema 1.20): `id` (finding_id), `check_id`/`rule_id` (control), `page_types`,
`evidence`, `measurement`, `verification`, `remediation`, `dedup_key`, plus `severity` and `scope`, and a check's
`coverage`. There is no brand name, no site-specific pattern and no fixed title in it: a new site runs through the same
rules unchanged. Missing data is never read as a pass: a rule that needs a field a finding does not carry says so.

Severity is the engine's (AGENTS.md, preamble 3): the gate never lowers or raises it. A High finding without evidence
blocks the output; the fix belongs in the check that made it.

Rules (hard = blocks, soft = conditional):
    RG-1  hard  every card names the findings it is made from, and each exists in the report
    RG-2  hard  every High/Critical finding has evidence beyond its severity and judgment records
    RG-3  hard  every address a card shows or writes is one of its findings' affected or target addresses
    RG-4  hard  "confirmed" only when every re-tested address is one the finding is about (`verification.subjects`,
                else its affected addresses); a card says confirmed only when its findings are
    RG-5  hard  every High/Critical finding carries a verification state (`not_retested` with a reason counts)
    RG-6  hard  a card's reference to another card ("6. işle", "task 6") needs evidence the two cards share
    RG-7  hard  a content recommendation (Article, product, price, conversion) only on pages of an allowed type; an
                unknown page type is not allowed
    RG-8  soft  one finding does not mix two states of one element (no <h1> and an empty <h1>)
    RG-9  soft  one element on one page is claimed by one finding only; findings sharing a dedup_key do not overlap
    RG-10 soft  an element is not reported absent on a page where it could not be measured; every not-assessed part
                says why, and counts the pages it names
    RG-11 hard  a card's fixed title topic and each conditional step rests on a finding that meets its condition
    RG-12 hard  a validation count ("9/9 kept") counts only items matched by finding and re-tested (see `checklist`)
    RG-13 soft  no visible card text ends cut off ("+" or "·" with nothing after it)
    RG-14 hard  the site's content was read: a report with 0 pages read is not delivered as a result (DECISIONS 287)
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlsplit

VERSION = "release-gate-1"
PASS, CONDITIONAL, BLOCKED = "PASS", "CONDITIONAL", "BLOCKED"
HIGH = ("S1", "S2")
STATES = ("confirmed", "changed", "not_reproduced", "not_retested")
# Kinds of page no Article, product, price or conversion advice is ever given for (they list or fail, they do not say).
NO_CONTENT_ADVICE = frozenset({"pagination", "archive", "listing", "tag", "category", "404", "unknown"})
# Evidence keys that are bookkeeping about a finding, not evidence of it.
NOT_EVIDENCE = frozenset({"severity_assessment", "judgment"})
# A reference from one card to another card, in Turkish or English ("6. işle birlikte", "task 6", "item #6").
CARD_REFERENCE = re.compile(r"(?<!\d)(\d{1,2})\.\s*(?:iş|işle|işte|işin|işi|işten|karta|kart)\b|\b(?:task|item|card)\s*#?(\d{1,2})\b",
                            re.IGNORECASE)
# A site address written in a text field ("/en", "/about/team"); not "a/b", "500 KB/s" or "<h2>/<h3>".
PATH = re.compile(r"(?<![\w:/.<>])/[A-Za-z0-9][\w\-.%{}]*(?:/[\w\-.%{}]+)*/?")
CUT_OFF = re.compile(r"(?:·|\+)\s*$")


def violation(rule: str, message: str, *, hard: bool, finding_id: str | None = None, card: int | None = None) -> dict:
    row = {"rule": rule, "hard": hard, "message": message}
    if finding_id:
        row["finding_id"] = finding_id
    if card is not None:
        row["card"] = card
    return row


def decision(violations: list[dict]) -> str:
    if any(v["hard"] for v in violations):
        return BLOCKED
    return CONDITIONAL if violations else PASS


def _get(value: Any, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


# ---------------------------------------------------------------- the finding contract (schema 1.20)

def findings_of(report: dict) -> dict[str, dict]:
    """Every finding of the report by id: the site checks and the answer-engine panel."""
    out: dict[str, dict] = {}
    for check in (report.get("checks") or []) + (report.get("answer_engine_panel") or []):
        for finding in check.get("findings") or []:
            if finding.get("id"):
                out[finding["id"]] = finding
    return out


def severity_of(finding: dict) -> str:
    s = finding.get("severity")
    return getattr(s, "value", s) or ""


def affected_urls(finding: dict, affected: dict | None = None) -> list[str]:
    """The addresses the finding is about: its `scope.urls` and the companion list (affected-urls.json), together."""
    full = (affected or {}).get(finding.get("id"))
    urls = list((finding.get("scope") or {}).get("urls") or []) + (full if isinstance(full, list) else [])
    return [u for u in dict.fromkeys(urls) if isinstance(u, str)]


def _addresses_in(value, out: set[str]) -> set[str]:
    """Every absolute address anywhere in a check's observations or evidence (for a card made from observations)."""
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            _addresses_in(v, out)
    elif isinstance(value, list):
        for v in value:
            _addresses_in(v, out)
    return out


def target_urls(finding: dict) -> list[str]:
    """Addresses the finding names but is not about: the broken targets of the source pages it lists."""
    return [u for u in (finding.get("evidence") or {}).get("target_urls") or [] if isinstance(u, str)]


def has_evidence(finding: dict) -> bool:
    evidence = finding.get("evidence") or {}
    return any(v not in (None, "", [], {}) for k, v in evidence.items() if k not in NOT_EVIDENCE)


def claims(finding: dict) -> list[dict]:
    """`measurement.claims`: [{"element", "state", "urls"}], what the finding says about which element on which page."""
    return [c for c in (finding.get("measurement") or {}).get("claims") or [] if isinstance(c, dict)]


def gaps(report: dict) -> list[dict]:
    """Every part of every check that was not assessed, with the element and pages when the check names them."""
    rows = []
    for check in report.get("checks") or []:
        for part in (check.get("coverage") or {}).get("not_assessed") or []:
            rows.append({"check_id": check.get("check_id"), **part})
    return rows


# ---------------------------------------------------------------- report rules (G1, and again before a PDF)

def check_report(report: dict, affected: dict | None = None) -> list[dict]:
    """Violations of the report itself: evidence, verification, page types, claims, gaps."""
    out: list[dict] = []
    # DECISIONS 287: nothing read is no audit of the site's content; the report is a draft (nihan.com.tr: one 429).
    coverage = (report.get("audit_status") or {}).get("content_coverage") or {}
    if "pages_read" in coverage and not coverage.get("pages_read"):
        out.append(violation("RG-14", "site content could not be read: 0 pages were read, so the report is a draft, not a "
                                      "result to deliver", hard=True))
    by_id = findings_of(report)
    gap_rows = gaps(report)
    unmeasured = {(g.get("element"), u) for g in gap_rows if g.get("element") for u in g.get("urls") or []}
    for g in gap_rows:
        if not g.get("reason") or (g.get("urls") and g.get("count") in (None, "")):
            out.append(violation("RG-10", f"{g.get('check_id')}: a part was not assessed without a reason, or names "
                                          f"pages without counting them ({g.get('part')!r})", hard=False))
    owners: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for fid, f in by_id.items():
        high = severity_of(f) in HIGH
        if high and not has_evidence(f):
            out.append(violation("RG-2", f"{fid} is {severity_of(f)} but has no evidence", hard=True, finding_id=fid))
        v = f.get("verification")
        if high and not (isinstance(v, dict) and v.get("state") in STATES):
            out.append(violation("RG-5", f"{fid} is {severity_of(f)} and carries no verification state", hard=True,
                                 finding_id=fid))
        if isinstance(v, dict) and v.get("state") == "confirmed":
            subjects = set(v.get("subjects") or affected_urls(f, affected))
            off = [r.get("url") for r in v.get("checked") or [] if r.get("url") not in subjects]
            if off:
                out.append(violation("RG-4", f"{fid} says confirmed, but re-tested {off[0]}, which the finding is not "
                                              "about", hard=True, finding_id=fid))
        remedy = f.get("remediation") or {}
        allowed = remedy.get("page_types")
        if remedy.get("content") and allowed is not None:
            types = f.get("page_types") or {}
            wrong = [u for u in affected_urls(f, affected) if types.get(u, "unknown") not in allowed
                     or types.get(u, "unknown") in NO_CONTENT_ADVICE]
            if wrong:
                kind = types.get(wrong[0], "unknown")
                out.append(violation("RG-7", f"{fid} gives content advice for {wrong[0]}, a page of type {kind}"
                                              + (" (page type unknown; no content advice)" if kind == "unknown" else ""),
                                     hard=True, finding_id=fid))
        states: dict[str, set[str]] = {}
        for c in claims(f):
            states.setdefault(c.get("element"), set()).add(c.get("state"))
            for u in c.get("urls") or []:
                owners.setdefault((c.get("element"), u), []).append((fid, c.get("state")))
                if c.get("state") == "absent" and (c.get("element"), u) in unmeasured:
                    out.append(violation("RG-10", f"{fid} reports {c.get('element')} absent on {u}, where it could not "
                                                  "be measured", hard=False, finding_id=fid))
        for element, seen in states.items():
            if len(seen) > 1:
                out.append(violation("RG-8", f"{fid} puts {', '.join(sorted(map(str, seen)))} {element} under one "
                                              "diagnosis; report each state with its own count", hard=False, finding_id=fid))
    seen_pairs = set()
    for (element, url), rows in owners.items():
        ids = sorted({fid for fid, _ in rows})
        if len(ids) > 1 and tuple(ids) not in seen_pairs:
            seen_pairs.add(tuple(ids))
            out.append(violation("RG-9", f"{' and '.join(ids)} both report {element} on {url} (and possibly more pages); "
                                          "one cause is one finding", hard=False, finding_id=ids[0]))
    by_key: dict[str, list[dict]] = {}
    for f in by_id.values():
        if f.get("dedup_key"):
            by_key.setdefault(f["dedup_key"], []).append(f)
    for key, group in by_key.items():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                ua, ub = set(affected_urls(a, affected)), set(affected_urls(b, affected))
                if ua and ub and len(ua & ub) / min(len(ua), len(ub)) >= 0.8:
                    out.append(violation("RG-9", f"{a['id']} and {b['id']} share dedup_key {key!r} and the same pages",
                                         hard=False, finding_id=a["id"]))
    return out


# ---------------------------------------------------------------- card rules (G2, before a PDF)

def path_of(url: str) -> str:
    return ((urlsplit(url).path or "/") if "://" in url else url).rstrip("/")


def card_paths(card: dict) -> set[str]:
    """The addresses a card holds, without a trailing slash: its links, its full list, its targets, its evidence line."""
    urls = list(card.get("all_urls") or []) + list(card.get("target_urls") or []) + [l.get("href") for l in card.get("links") or []]
    urls += [r.get(k) for r in card.get("link_rows") or [] for k in ("source_url", "links_to", "target_url")]
    paths = {path_of(u) for u in urls if isinstance(u, str)}
    paths |= {m.rstrip("/") for m in PATH.findall(card.get("fact") or "")}
    paths |= {p.rstrip("/") for p in card.get("known_paths") or []}
    return paths


def is_known(path: str, known: set[str]) -> bool:
    """The address, or a section of one ("/semt/" for "/semt/uskudar"), is among the known ones."""
    p = path.rstrip("/")
    return p in known or any(k.startswith(p + "/") for k in known)


def text_addresses(text: str, known: set[str]) -> list[str]:
    """The addresses written in `text` that are not among `known` (moved here from validate_data, DECISIONS 271)."""
    return [p for p in PATH.findall(text or "") if not is_known(p, known)]


def _card_text(card: dict) -> str:
    return " ".join(str(card.get(k) or "") for k in ("title", "steps", "verify", "status"))


def _tokens(card: dict) -> set[str]:
    """What a card's evidence holds that another card's could share: addresses, markers and elements."""
    out = {p for p in card_paths(card) if p not in ("", "/")}
    out |= set(re.findall(r"\{\{?[^{}\s]+\}?\}|<[a-z0-9]+[#.][^>\s]+>", card.get("fact") or ""))
    out |= {str(t) for t in card.get("evidence_tokens") or []}
    return out


def condition_met(condition: dict, findings: list[dict]) -> bool:
    """A catalogue condition: {"evidence_any": "pages[].in_sitemap"} holds when any finding's evidence has a true
    value there; {"rule_any": [ids]} when any finding has one of these rule ids."""
    if "rule_any" in condition:
        return any(f.get("rule_id") in condition["rule_any"] for f in findings)
    path = condition.get("evidence_any") or ""
    head, _, leaf = path.partition("[].")
    for f in findings:
        rows = (f.get("evidence") or {}).get(head) or []
        if any(isinstance(r, dict) and r.get(leaf) for r in rows):
            return True
    return False


def check_cards(data: dict, report: dict, affected: dict | None = None) -> list[dict]:
    """Violations of a professional report's cards (data.json) against the report they were built from."""
    out: list[dict] = []
    by_id = findings_of(report)
    ids_known = set(by_id) | {c.get("check_id") for c in report.get("checks") or []}
    cards = data.get("todos") or []
    for n, card in enumerate(cards, 1):
        fids = card.get("finding_ids")
        if not fids:
            out.append(violation("RG-1", f"card {n} names no finding", hard=True, card=n))
            continue
        missing = [i for i in fids if i not in ids_known]
        if missing:
            out.append(violation("RG-1", f"card {n} names {missing[0]}, which is not in the report", hard=True, card=n))
        mine = [by_id[i] for i in fids if i in by_id]
        allowed = set()
        for f in mine:
            allowed |= {path_of(u) for u in affected_urls(f, affected) + target_urls(f)}
        for check in report.get("checks") or []:  # a Note card made from a check's observations names the check
            if check.get("check_id") in fids:
                allowed |= {path_of(u) for u in _addresses_in([check.get("observations"), check.get("evidence")], set())}
        if mine:
            visible = [l.get("href") for l in card.get("links") or []] + [r.get("source_url") for r in card.get("link_rows") or []]
            for u in list(card.get("all_urls") or []) + visible:
                if isinstance(u, str) and path_of(u) not in allowed:
                    out.append(violation("RG-3", f"card {n} shows {u}, which none of its findings lists", hard=True, card=n))
                    break
        for field in ("title", "steps", "verify"):
            for p in text_addresses(card.get(field) or "", card_paths(card)):
                out.append(violation("RG-3", f"card {n} {field} names {p!r}, which is not among the card's addresses or "
                                              "evidence", hard=True, card=n))
        shown = card.get("verification_state")
        if shown == "confirmed" and not (mine and all((f.get("verification") or {}).get("state") == "confirmed" for f in mine)):
            out.append(violation("RG-4", f"card {n} says re-tested and confirmed, but its findings are not", hard=True, card=n))
        if mine and any(severity_of(f) in HIGH for f in mine) and shown not in STATES:
            out.append(violation("RG-5", f"card {n} is High but shows no re-test state", hard=True, card=n))
        for m in CARD_REFERENCE.finditer(_card_text(card)):
            j = int(m.group(1) or m.group(2))
            if j == n or not 1 <= j <= len(cards):
                continue
            if not _tokens(card) & _tokens(cards[j - 1]):
                out.append(violation("RG-6", f"card {n} sends part of its fix to card {j}, but the two cards share no "
                                              "evidence; no related task is assigned", hard=True, card=n))
        for topic in card.get("topics") or []:
            if not [i for i in topic.get("ids") or [] if i in ids_known]:
                out.append(violation("RG-11", f"card {n} title names {topic.get('topic')!r}, which no finding of this "
                                               "report supports", hard=True, card=n))
        for step in card.get("step_rules") or []:
            if step.get("shown") and not condition_met(step.get("when") or {}, mine):
                out.append(violation("RG-11", f"card {n} step {step.get('text')!r} is shown, but its condition "
                                               f"{step.get('when')} holds for none of its findings", hard=True, card=n))
        for field in ("title", "steps", "verify", "fact"):
            text = str(card.get(field) or "")
            if text and any(CUT_OFF.search(line) for line in text.split("\n")):
                out.append(violation("RG-13", f"card {n} {field} ends cut off: {text.splitlines()[-1][-40:]!r}",
                                     hard=False, card=n))
    return out


# ---------------------------------------------------------------- validation note (G3)

def checklist(items: Iterable[dict], report: dict, affected: dict | None = None) -> dict:
    """Match a validation checklist to a report by finding, never by wording.

    An item is {"label", "rule_id", "urls": [example addresses], "expected": "kept" | "closed", "manual_notes"}. It is
    matched to the finding with that rule id whose affected (or target) addresses share at least one of the item's
    addresses; without a shared address it is "unmatched", whatever the titles say. A matched finding counts as kept
    and checked only when its second look confirmed it; otherwise it is "not_retested". "closed" items are closed only
    when no finding of that rule holds any of their addresses.
    """
    by_id = findings_of(report)
    rows, counts = [], {"items": 0, "kept_and_retested": 0, "matched_not_retested": 0, "unmatched": 0, "closed": 0,
                        "still_reported": 0}
    for item in items:
        counts["items"] += 1
        want = {path_of(u) for u in item.get("urls") or []}
        candidates = [f for f in by_id.values() if f.get("rule_id") == item.get("rule_id")]
        hit = next((f for f in candidates
                    if want & {path_of(u) for u in affected_urls(f, affected) + target_urls(f)}), None)
        row = {"label": item.get("label"), "rule_id": item.get("rule_id"), "expected": item.get("expected", "kept"),
               "finding_id": hit.get("id") if hit else None, "severity": severity_of(hit) if hit else None,
               "verification": ((hit or {}).get("verification") or {}).get("state"),
               "manual_notes": item.get("manual_notes") or ""}
        if row["expected"] == "closed":
            row["result"] = "still_reported" if hit else "closed"
        elif not hit:
            row["result"] = "unmatched"
        elif row["verification"] == "confirmed":
            row["result"] = "kept_and_retested"
        else:
            row["result"] = "matched_not_retested"
        counts[row["result"]] += 1
        rows.append(row)
    return {"version": VERSION, "rows": rows, "counts": counts}


# ---------------------------------------------------------------- summary

SUMMARY_ROWS = (
    ("RG-2", "High finding without evidence", "must be 0"),
    ("RG-3", "Card address not in its finding", "must be 0"),
    ("RG-4", "Unconfirmed claim shown as confirmed", "must be 0"),
    ("RG-5", "High finding without a re-test state", "must be 0"),
    ("RG-6", "Card reference without shared evidence", "must be 0"),
    ("RG-7", "Content advice for the wrong page type", "must be 0"),
    ("RG-10", "Silent measurement gap", "must be 0"),
    ("RG-11", "Fixed title or step without a finding", "must be 0"),
    ("RG-14", "Site content could not be read", "must be 0"),
)


def run(report: dict, affected: dict | None = None, data: dict | None = None) -> dict:
    """The gate's record: decision, violations, and the counts the summary table prints."""
    violations = check_report(report, affected) + (check_cards(data, report, affected) if data is not None else [])
    counts: dict[str, int] = {}
    for v in violations:
        counts[v["rule"]] = counts.get(v["rule"], 0) + 1
    by_id = findings_of(report)
    not_retested = sorted(fid for fid, f in by_id.items() if severity_of(f) in HIGH
                          and (f.get("verification") or {}).get("state") in (None, "not_retested"))
    return {"version": VERSION, "decision": decision(violations), "violations": violations, "counts": counts,
            "high_not_retested": not_retested, "cards_checked": data is not None}


def summary_table(record: dict) -> str:
    """The pre-release summary for the person delivering the report (never printed in the client PDF)."""
    lines = ["| Check | Result | Rule |", "|---|---|---|"]
    for rule, label, want in SUMMARY_ROWS:
        lines.append(f"| {label} | {record['counts'].get(rule, 0)} ({want}) | {rule} |")
    lines.append(f"| High finding not re-tested | {len(record['high_not_retested'])} (listed) | — |")
    lines.append(f"\nDecision: {record['decision']}")
    return "\n".join(lines)
