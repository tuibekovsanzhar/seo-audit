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
LINK_RULES = ("idx1.4xx.referenced", "idx1.4xx.referenced.linked", "idx1.4xx.sitemap_only", "idx1.href_mistyped")
FINAL_KEYS = ("checks", "answer_engine_panel", "findings_in_priority_order", "release_gate")


# ---------------------------------------------------------------- finalization


def locale_record(result) -> dict:
    """`crawl.locales` (schema 1.27): `locales.detect` on every address the audit knows, the hreflang links of the pages
    read and the homepage it landed on."""
    from .access_data import homepage_url
    from .locales import detect
    pages = list(getattr(result, "pages", None) or [])
    hreflang = [h.get("href") for p in pages for h in ((getattr(p, "analysis", None) or {}).get("hreflang") or [])
                if isinstance(h, dict)]
    urls = [p.url for p in pages] + list(getattr(result, "sitemap_urls", None) or []) + list(
        getattr(result, "discovered_urls", None) or [])
    try:
        home = homepage_url(result)
    except Exception:  # noqa: BLE001
        home = getattr(result, "start_url", None)
    return detect(urls, hreflang, home)


def settle(checks, result) -> None:
    """The steps after severity, in order. Idempotent; no request is sent."""
    from .checks.index import broken_link_sources
    from .checks.structure import annotate_page_types
    from .facts import attach
    from .rules import assign
    broken_link_sources(checks, result)  # skips a finding already traced (it has target_urls)
    # DECISIONS 344: the sitemap-errors card takes the redirects to an error page, with a 301 target per address
    from .checks.team_rules import settle as team_settle
    team_settle(checks, result)
    assign(checks)
    attach(checks)
    # Page kinds for the site checks, as before; the answer-engine panel never had them.
    annotate_page_types([c for c in checks if not _get(c, "check_id").startswith("ANS")], result)
    # Templates, page types, link scores, click depth, importance (DECISIONS 297): stored, never a severity.
    from .page_groups import annotate as annotate_groups
    annotate_groups(result)
    # DECISIONS 338: a listing page is not a long page lacking subheadings
    from .checks.structure import drop_listing_pages
    drop_listing_pages([c for c in checks if not _get(c, "check_id").startswith("ANS")],
                       {p.url: (p.grouping or {}).get("page_type") for p in result.pages if isinstance(getattr(p, "grouping", None), dict)})
    # Country/language versions of the same pages (DECISIONS 316): the site's locale folders and its main version.
    result.locales = locale_record(result)
    # The business type (DECISIONS 311): page importance weighted by the profile; never a severity.
    from .business_types import attach as attach_business
    attach_business(result)
    # DECISIONS 329: IDX-8's place-name groups only on the business type's location pages (clinic, branch, store ...).
    from .checks.index import gate_location_templates
    config = getattr(result, "config", None)
    least = config.get("location_template_min_pages") if isinstance(config, dict) else getattr(config, "location_template_min_pages", None)
    types = {p.url: (p.grouping or {}).get("business_page_type") for p in result.pages
             if isinstance(getattr(p, "grouping", None), dict)}
    reader = getattr(result, "reader_page_grouping", None)  # a blocked site: the page reader's pages (DECISIONS 304)
    for url, g in ((reader or {}).get("pages") or {}).items() if isinstance(reader, dict) else ():
        if isinstance(g, dict) and not types.get(url):
            types[url] = g.get("business_page_type")
    gate_location_templates([c for c in checks if not _get(c, "check_id").startswith("ANS")], types,
                            (getattr(result, "business_type", None) or {}).get("id"), least)
    # DECISIONS 356: the business profile's own checks (SaaS / Yazılım: pricing, features, integrations, stories, demo),
    # once; their findings get rule ids and contract fields as every other.
    from .checks.profile_rules import RULES as PROFILE_RULES, extend as profile_checks
    site = [c for c in checks if not _get(c, "check_id").startswith("ANS")]
    if not any(_get(f, "rule_id") in PROFILE_RULES for c in site for f in (_get(c, "findings") or [])):
        profile_checks(site, result)
        assign(checks)
        attach(checks)
    # Every redirect hop of the crawl, per requested address (Stage 8a, DECISIONS 315).
    from .checks.stage8_rules import redirect_records
    result.redirects = redirect_records(result.pages)
    # What was measured on every page read (DECISIONS 323): Maya's own pages over a page reader's copy of the same page.
    from .page_measures import of_pages
    result.page_measures = {**(result.page_measures or {}), **of_pages(result.pages)} or None


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
    """For each finding that names an address pointed at from somewhere (broken links, sitemap entries, server errors,
    links to redirects, redirect chains, failing canonicals and hreflang targets; `link_places.WHERE_RULES`, DECISIONS
    337): one row per address and the page or entry that names it. Only what the report records; a new address is
    offered only where a redirect itself ends at a working page, never guessed."""
    from .link_places import places
    by_id = {f.get("id"): f for c in report.get("checks") or [] for f in c.get("findings") or [] if isinstance(f, dict)}
    out: dict[str, list[dict]] = {}
    for fid, rows in places(report).items():
        # DECISIONS 360: rows of an observation (links with tracking parameters) have no finding of their own
        f = by_id.get(fid) or {"rule_id": (rows[0] if rows else {}).get("rule_id"), "severity": "Info"}
        base = {"finding_id": fid, "rule_id": f.get("rule_id"), "severity": f.get("severity"),
                "verification": (f.get("verification") or {}).get("state")}
        cards = []
        for r in rows:
            suggested = r.get("suggested")
            url = suggested if isinstance(suggested, str) and suggested.startswith(("http://", "https://")) else None
            cards.append({**base, **r, "source_url": r["source"] if r["kind"] != "sitemap" else r["links_to"],
                          "target_url": r["ends_at"] if r["ends_at"] != r["links_to"] or r["kind"] == "link" else None,
                          "target_status": r["final_status"], "replacement_url": url,
                          "replacement": url or REPLACEMENT_UNKNOWN})
        out[fid] = cards
    return out


def target_line(card: dict) -> str:
    target = card.get("target_url")
    if not target:
        return "error page (see the finding)"
    return f"{target} ({card['target_status']})" if card.get("target_status") else target


def cards_markdown(report: dict) -> str:
    """The "what to edit" table for broken internal links; empty when there is none."""
    # DECISIONS 360: links with no text and links with tracking parameters are not broken links: the appendix lists them
    cards = [c for rows in broken_link_cards(report).values() for c in rows
             if c.get("rule_id") not in ("str14.no_text", "idx6.parameters")]
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
