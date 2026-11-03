"""Findings seen only in Firecrawl's copy of the pages, not in Maya's own reading (v0.3 stage 6, DECISIONS 300 (9)).

When Firecrawl is the audit's page reader on a site Maya's own crawler could read too (DECISIONS 131), the content
checks judge Firecrawl's copy. That copy is the page as Firecrawl's browser built it, and on nihan it held
visitor-specific blocks Maya's copy did not (DECISIONS 299 (5), IMPLEMENTATION-STATUS "Double reading"). So the same
content checks are also run on Maya's own copies, offline, and a finding that has no counterpart there is marked:

    evidence.reading = {"seen_in": "firecrawl_only", "note": ...}
    confidence: verified -> estimated (a lower confidence is kept); the finding's notes say why

Nothing else changes: not the finding, its severity, its scope, nor which copy the checks judge. A client report puts
such a finding under "Teyit edin" (`client_selection.confirm_reason`) until the owner's manual check confirms it.

Counterpart: the same rule, and the same title once numbers and parenthesised example lists are left out ("47 heading
level jump(s)" and "214 heading level jump(s)" are one; a repeated block's heading “Cart 0 items” and “Secure
Shopping” are two). Only where Maya's own copy of the page was read; a site that blocked Maya has nothing to compare.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any

SEEN_IN = "firecrawl_only"
NOTE = ("Seen only in Firecrawl's copy of the pages, not in Maya's own reading of the same pages: confirm it in a normal "
        "browser before acting on it.")
_EXAMPLES = re.compile(r"\((?:[^()]*“[^()]*)\)")


def finding_key(rule_id: str | None, title: str | None) -> tuple[str, str]:
    text = _EXAMPLES.sub("", title or "")
    text = re.sub(r"[0-9][0-9.,]*", "#", text)
    return (rule_id or "", re.sub(r"\s+", " ", text).strip())


def _get(value: Any, name: str):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _rule(finding: Any, check_id: str) -> str | None:
    rule = _get(finding, "rule_id")
    if rule:
        return rule
    from .rules import rule_id
    try:
        return rule_id(check_id, _get(finding, "title") or "")
    except Exception:
        return None


def keys_of(checks: list) -> set[tuple[str, str]]:
    out = set()
    for check in checks:
        cid = _get(check, "check_id")
        for f in _get(check, "findings") or []:
            out.add(finding_key(_rule(f, cid), _get(f, "title")))
    return out


def _mark(finding: Any) -> bool:
    evidence = _get(finding, "evidence")
    if evidence is None:
        evidence = {}
        if isinstance(finding, dict):
            finding["evidence"] = evidence
        else:
            finding.evidence = evidence
    if (evidence.get("reading") or {}).get("seen_in") == SEEN_IN:
        return False
    evidence["reading"] = {"seen_in": SEEN_IN, "note": NOTE}
    confidence = _get(finding, "confidence")
    if getattr(confidence, "value", confidence) == "verified":
        if isinstance(finding, dict):
            finding["confidence"] = "estimated"
        else:
            from .models import Confidence
            finding.confidence = Confidence.ESTIMATED
    notes = _get(finding, "notes")
    if notes is None:
        notes = []
        if isinstance(finding, dict):
            finding["notes"] = notes
        else:
            finding.notes = notes
    if NOTE not in notes:
        notes.append(NOTE)
    return True


def mark(reader_checks: list, own_checks: list) -> list[str]:
    """Mark, in `reader_checks`, every finding with no counterpart in `own_checks`. Returns their ids (or titles)."""
    own = keys_of(own_checks)
    marked = []
    for check in reader_checks:
        cid = _get(check, "check_id")
        for f in _get(check, "findings") or []:
            if finding_key(_rule(f, cid), _get(f, "title")) not in own and _mark(f):
                marked.append(_get(f, "id") or _get(f, "title"))
    return marked


def own_content_checks(result, cfg) -> list:
    """The content checks Firecrawl's reading replaces (`firecrawl.reader.CONTENT_CHECKS`), run on Maya's own pages."""
    from .checks.index import idx8_duplicates
    from .checks.structure import run_structure_checks
    from .coverage import settle_all
    from .firecrawl.reader import CONTENT_CHECKS
    checks = run_structure_checks(result, cfg, [])
    checks += settle_all([idx8_duplicates(result, cfg)], result)
    return [c for c in checks if c.check_id in CONTENT_CHECKS]


# ---------------------------------------------------------------- a saved report

def result_from_report(report: dict):
    """Maya's own reading of a saved report as a crawl result (its page records; no request is made)."""
    from .config import CrawlConfig
    from .models import CrawlResult, StopReason, page_from_record
    c = report.get("crawl") or {}
    names = {f.name for f in dataclasses.fields(CrawlConfig)}
    cfg = CrawlConfig(**{k: v for k, v in (c.get("config") or {}).items() if k in names})
    try:
        stop = StopReason(c.get("stop_reason"))
    except ValueError:
        stop = StopReason(list(StopReason)[0].value)
    result = CrawlResult(start_url=c.get("start_url") or "", origin=c.get("origin") or "", user_agent=c.get("user_agent") or "",
                         product_token=c.get("product_token") or "", started_at=c.get("started_at") or "",
                         finished_at=c.get("finished_at") or "", elapsed_s=c.get("elapsed_s") or 0.0,
                         config=c.get("config") or {}, robots=c.get("robots") or [],
                         pages=[page_from_record(p) for p in c.get("pages") or [] if isinstance(p, dict)],
                         skipped_robots=[], sitemap_docs=[], sitemap_urls=c.get("sitemap_urls") or [],
                         discovered_urls=c.get("discovered_urls") or [], not_fetched_urls=[], stop_reason=stop,
                         stop_detail=c.get("stop_detail") or "", requests=[])
    return result, cfg


def applies(report: dict) -> bool:
    """Firecrawl's reading judged the content checks while Maya's own copies of the same pages were read."""
    reader = report.get("firecrawl") or {}
    blocked = (reader.get("crawl_blocked") or {}).get("blocked")
    own = [p for p in (report.get("crawl") or {}).get("pages") or []
           if isinstance(p, dict) and (p.get("analysis") or None) and p.get("view") != "provider"]
    return bool(reader.get("checks_from_firecrawl")) and blocked is False and bool(own)


def mark_report(report: dict) -> list[str]:
    """Mark a saved report's Firecrawl-only findings in place (call it on a copy). Returns the ids marked."""
    if not applies(report):
        return []
    from .firecrawl.reader import CONTENT_CHECKS
    result, cfg = result_from_report(report)
    own = own_content_checks(result, cfg)
    reader = [c for c in report.get("checks") or [] if c.get("check_id") in CONTENT_CHECKS]
    return mark(reader, own)
