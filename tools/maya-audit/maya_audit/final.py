"""The one final result every output is built from (guide stages 02/04/10, M1 minimum; DECISIONS 280).

Three parts:

- `settle` + `verify`: the finalization that runs after severities are set, once inside `run_audit` and again after a
  page reader (Firecrawl) replaced checks, so a replaced finding gets the same broken-link tracing, rule id, facts,
  page types and re-test state as one Maya judged itself. `settle` sends nothing; `verify` is the controlled re-test
  I/O and, after a reader, only re-tests findings without a record, within what is left of the request cap.
- `seal(outcome)` -> `FinalAuditResult`: the report, its full address lists and its release-gate decision, built once.
  The CLI and the web worker both call it. `from_report` is the adapter for a saved report, including one saved before
  the gate existed (the gate is then run on it, never assumed PASS).
- `broken_link_cards` / `cards_markdown`: where a broken internal link is and what to edit, from the final report only.

Supplementary panels (DataForSEO, Firecrawl section, CrUX, archives, ownership) may be added to `report` after sealing;
`checks`, `answer_engine_panel`, `findings_in_priority_order` and `release_gate` are final, and `digest` covers them.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

REPLACEMENT_UNKNOWN = "unknown"
LINK_RULES = ("idx1.4xx.referenced", "idx1.4xx.referenced.linked")
FINAL_KEYS = ("checks", "answer_engine_panel", "findings_in_priority_order", "release_gate")


# ---------------------------------------------------------------- finalization


def settle(checks, result) -> None:
    """The steps after severity, in order. Idempotent; no request is sent."""
    from .checks.index import broken_link_sources
    from .checks.structure import annotate_page_types
    from .facts import attach
    from .rules import assign
    broken_link_sources(checks, result)  # skips a finding already traced (it has target_urls)
    assign(checks)
    attach(checks)
    # Page kinds for the site checks, as before; the answer-engine panel never had them.
    annotate_page_types([c for c in checks if not _get(c, "check_id").startswith("ANS")], result)


def verify(checks, result, cfg, transport=None, hooks=None, pace_s: float | None = None, *,
           after_provider: bool = False) -> dict:
    """The controlled re-test. After a page reader: only findings with no record, within the cap that is left."""
    from . import verification
    if not after_provider:
        return verification.run(checks, result, cfg, transport, hooks, pace_s)
    first = result.verification or {}
    left = cfg.verification_max_requests - int(first.get("requests") or 0)
    return verification.run(checks, result, cfg, transport, hooks, pace_s, only_missing=True, cap=left)


def after_provider(outcome, cfg) -> None:
    """Run the shared finalization again after a page reader replaced checks (called by `firecrawl.reader.apply`)."""
    result = outcome.result
    settle(outcome.checks, result)
    summary = verify(outcome.checks, result, cfg, getattr(outcome, "transport", None), getattr(outcome, "hooks", None),
                     getattr(outcome, "pace_s", None), after_provider=True)
    if result.verification is not None:
        result.verification = {**result.verification, "after_provider": summary}
    else:
        result.verification = {"after_provider": summary}


# ---------------------------------------------------------------- the sealed result


def digest_of(report: dict) -> str:
    """A hash of the final parts of a report; a renderer or adapter must leave it unchanged."""
    final = {key: report.get(key) for key in FINAL_KEYS}
    return hashlib.sha256(json.dumps(final, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FinalAuditResult:
    report: dict
    affected: dict = field(default_factory=dict)
    digest: str = ""

    @property
    def gate(self) -> dict:
        return self.report.get("release_gate") or {}

    @property
    def decision(self) -> str | None:
        return self.gate.get("decision")

    @property
    def cards(self) -> dict[str, list[dict]]:
        return broken_link_cards(self.report)


def seal(outcome, *, firecrawl: dict | None = None, brand: dict | None = None,
         all_phases_s: float | None = None, slept_s: float | None = None) -> FinalAuditResult:
    """Build the report and its full address lists once, from the engine's final checks."""
    from .report import report_and_affected
    report, affected = report_and_affected(outcome.result, outcome.gates, outcome.checks, firecrawl=firecrawl,
                                           all_phases_s=all_phases_s, brand=brand, slept_s=slept_s)
    return FinalAuditResult(report, affected, digest_of(report))


def from_report(report: dict, affected: dict | None = None) -> FinalAuditResult:
    """The adapter for a saved report. Works on a copy; a report without a gate (saved before schema 1.20) gets the
    gate run on it; missing address lists come from each finding's own scope."""
    report = deepcopy(report)
    known = dict(affected or {})
    for item in _items(report):
        if item.get("id") and item["id"] not in known:
            scope = item.get("scope") or {}
            known[item["id"]] = list(scope.get("_all_urls") or scope.get("urls") or [])
    if not isinstance(report.get("release_gate"), dict):
        from .release_gate import run
        report["release_gate"] = run(report, known)
    return FinalAuditResult(report, known, digest_of(report))


def _get(value, name):
    return (value.get(name) if isinstance(value, dict) else getattr(value, name, None)) or ""


def _items(report: dict):
    for check in [*(report.get("checks") or []), *(report.get("answer_engine_panel") or [])]:
        yield from check.get("findings") or []
        yield from check.get("review_items") or []


# ---------------------------------------------------------------- broken-link cards


def broken_link_cards(report: dict) -> dict[str, list[dict]]:
    """For each broken-internal-link finding: one card per link (the page and link to edit) and one per sitemap entry
    that ends at the error. Only what the evidence records; the right new address is never guessed."""
    statuses = {p.get("url"): p.get("status") for p in (report.get("crawl") or {}).get("pages") or [] if isinstance(p, dict)}
    out: dict[str, list[dict]] = {}
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            if f.get("rule_id") not in LINK_RULES:
                continue
            evidence = f.get("evidence") or {}
            base = {"finding_id": f.get("id"), "rule_id": f.get("rule_id"), "severity": f.get("severity")}
            state = (f.get("verification") or {}).get("state")
            cards = [{**base, "kind": "link", "source_url": row.get("source"), "link_text": row.get("anchor"),
                      "links_to": row.get("links_to"), "target_url": row.get("target"),
                      "target_status": statuses.get(row.get("target")),
                      "replacement_url": None, "replacement": REPLACEMENT_UNKNOWN, "verification": state}
                     for row in evidence.get("link_sources") or [] if isinstance(row, dict)]
            cards += [{**base, "kind": "sitemap", "source_url": url, "link_text": None, "links_to": url,
                       "target_url": None, "target_status": None,
                       "replacement_url": None, "replacement": REPLACEMENT_UNKNOWN, "verification": state}
                      for url in evidence.get("sitemap_only") or []]
            if cards:
                out[f.get("id")] = cards
    return out


def target_line(card: dict) -> str:
    target = card.get("target_url")
    if not target:
        return "error page (see the finding)"
    return f"{target} ({card['target_status']})" if card.get("target_status") else target


def cards_markdown(report: dict) -> str:
    """The "what to edit" table for broken internal links; empty when there is none."""
    cards = [c for rows in broken_link_cards(report).values() for c in rows]
    if not cards:
        return ""
    lines = ["", "## Broken links: what to edit", "",
             "Each row is one link to change. Maya does not know the right new address: choose the page the link should "
             "point to, or remove the link. Sitemap rows: correct or remove the entry.", "",
             "| Page to edit | Link text | Links to | Ends at | Replacement |", "|---|---|---|---|---|"]
    for c in cards:
        source = c["source_url"] if c["kind"] == "link" else f"sitemap.xml entry {c['source_url']}"
        lines.append(f"| {_cell(source)} | {_cell(c.get('link_text') or '—')} | {_cell(c.get('links_to'))} | "
                     f"{_cell(target_line(c))} | {c['replacement']} |")
    return "\n".join(lines) + "\n"


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")
