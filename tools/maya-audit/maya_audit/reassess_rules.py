"""Rules changed after a report was written, applied offline to its saved findings (DECISIONS 285).

A saved report keeps the severities and findings it was written with. This applies the rules DECISIONS 284 changed to
the observations the report already holds, on a copy, with no request and no crawl:

- STR-2 "The homepage's only <h1> is hidden": the rule now gives it Medium (nothing re-tests it). The observation is
  unchanged; the severity and the note follow the current rule.
- STR-8 "pricing or spec comparisons as <div> grids": a grid in a block named as a calculator is left out. Each grid
  keeps its selector, label and heading in the finding's evidence, so the name test runs on them with the engine's own
  pattern. The other new test, a form control beside the grid, needs the page's structure, which a report does not
  keep: it is not assessed here and the result says so.

DECISIONS 290 adds three, on the evidence each finding already holds:

- ACC-4 "A request with Googlebot's user agent got 403/429 ... where a browser got 200" (every pair "refused"): a note,
  with the Search Console fix; the request came from Maya's address, which a firewall may refuse as a fake Googlebot.
- RND-3 "... may hide content behind interaction (raw-HTML heuristics)": Low, a check, with its note.
- STR-5 "The brand is named N different ways": a name given only by page titles that starts with the brand's main name
  ("Nihan Women's Coats") is a category title and is not counted; with two names or fewer left there is no finding.

DECISIONS 300 adds two, on what the report already holds:

- Findings seen only in Firecrawl's copy (`double_reading.mark_report`): when Firecrawl's reading judged the content
  checks and Maya's own copies of the same pages are in `crawl.pages`, the same content checks run on Maya's copies,
  only to compare; a finding with no counterpart there is marked (`evidence.reading`, estimated, a note). Which copy
  the checks judge does not change.
- ACC-3 "internal search or cart page(s) can be indexed (no noindex)", from the saved page records' meta robots,
  X-Robots-Tag and canonical (`checks.access.utility_indexable_findings`).

DECISIONS 304 adds the checklist's quick checks (`checks.quick_rules`), run on the saved page records with the
engine's own functions; a rule whose data the report does not keep (robots.txt's text for SEO-031, the sitemap's image
and video counts before schema 1.24) is listed as not assessed offline. The Product fields and an author in the
page's JSON-LD (schema 1.24) are read from the audit's saved evidence copies when the caller hands them in
(`saved_jsonld`, `tools/reassess_saved.py`).

Then what depends on the findings is derived again as a new report derives it: the severity policy, the priority
order, the problem summary (findings in priority order) and the release gate. Nothing else is re-run: re-running other
checks on Maya's own copies of the pages would mix readers when another reader (Firecrawl) read the site.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

NOT_ASSESSED_OFFLINE = ("a form control beside a grid (a calculator's input column next to its result column): the "
                        "report does not keep the page's structure around a grid")


def _hidden_h1(report: dict, changes: list[str]) -> None:
    from .checks.structure import HIDDEN_H1_MEDIUM, HOME_HIDDEN_H1_SEVERITY
    target = HOME_HIDDEN_H1_SEVERITY.value
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            if f.get("rule_id") != "str2.home_hidden_h1" or f.get("severity") in (target, "S4", "Info"):
                continue
            changes.append(f"{f['id']}: {f['severity']} -> {target} (str2.home_hidden_h1, DECISIONS 284 (3))")
            f["severity"] = target
            notes = f.setdefault("notes", [])
            if HIDDEN_H1_MEDIUM not in notes:
                notes.append(HIDDEN_H1_MEDIUM)
            assessment = (f.get("evidence") or {}).get("severity_assessment")
            if isinstance(assessment, dict):
                assessment["source_severity"] = assessment["severity"] = target


def _calculator_grids(report: dict, affected: dict, changes: list[str], unassessed: list[str]) -> None:
    from .analysis import CALCULATOR_NAME
    from .checks.structure import CALCULATOR_LEFT_OUT
    for check in report.get("checks") or []:
        if check.get("check_id") != "STR-8":
            continue
        kept = []
        for f in check.get("findings") or []:
            if f.get("rule_id") != "str8.pricing":
                kept.append(f)
                continue
            grids = (f.get("evidence") or {}).get("grids") or []
            named = [g for g in grids if CALCULATOR_NAME.search(" ".join(str(g.get(k) or "") for k in
                                                                         ("selector", "label", "heading", "container")))]
            rest = [g for g in grids if g not in named]
            if named:
                evidence = check.setdefault("evidence", {})
                left = evidence.setdefault("grids_left_out", [])
                for g in named:
                    left.append({"url": g.get("url"), "container": g.get("container"), "rows": g.get("rows"),
                                 **({"selector": g["selector"]} if g.get("selector") else {}),
                                 "why": CALCULATOR_LEFT_OUT, "calculator_named": True})
                evidence["grids_left_out_count"] = len(left)
            if not rest:
                changes.append(f"{f['id']}: removed; every grid is in a block named as a calculator "
                               f"({', '.join(sorted({str(g.get('url')) for g in named}))})")
                affected.pop(f["id"], None)
                continue
            if named:
                urls = sorted({g["url"] for g in rest if g.get("url")})
                f["evidence"]["grids"] = rest
                f["scope"] = {**(f.get("scope") or {}), "count": len(urls), "urls": urls}
                f["title"] = re.sub(r"^\d+ page", f"{len(urls)} page", f["title"])
                affected[f["id"]] = urls
                changes.append(f"{f['id']}: {len(named)} calculator grid(s) left out, {len(rest)} kept")
            # The kept grids were not checked for a control beside them: say so on the check.
            if rest:
                unassessed.extend(sorted({g["url"] for g in rest if g.get("url")}))
            kept.append(f)
        check["findings"] = kept
        if unassessed:
            parts = check.setdefault("coverage", {}).setdefault("not_assessed", [])
            parts.append({"part": "grids not checked for a form control beside them", "reason": NOT_ASSESSED_OFFLINE,
                          "count": len(unassessed)})
        from .checks.access import _status
        check["status"] = _status(check["findings"], check.get("review_items") or ())


def _set_severity(f: dict, target: str) -> None:
    f["severity"] = target
    assessment = (f.get("evidence") or {}).get("severity_assessment")
    if isinstance(assessment, dict):
        assessment["source_severity"] = assessment["severity"] = target


def _decisions_290(report: dict, affected: dict, changes: list[str]) -> None:
    from .checks.access import REFUSED_FIX, UA_CHECK_SEVERITY
    from .checks.render import RND3_CHECK_NOTE
    for check in report.get("checks") or []:
        kept = []
        for f in check.get("findings") or []:
            rule, sev = f.get("rule_id"), f.get("severity")
            pairs = (f.get("evidence") or {}).get("pairs") or []
            if rule == "acc4.ua_check.status" and pairs and all(p.get("outcome") == "refused" for p in pairs) and sev != "Info":
                changes.append(f"{f['id']}: {sev} -> {UA_CHECK_SEVERITY['refused'].value} (a spoofed Googlebot refused, DECISIONS 290)")
                _set_severity(f, UA_CHECK_SEVERITY["refused"].value)
                f["how_to_fix"] = REFUSED_FIX
            elif rule == "rnd3.maybe" and sev not in ("S4", "Info"):
                changes.append(f"{f['id']}: {sev} -> S4 (raw-HTML guess, a check, DECISIONS 290)")
                _set_severity(f, "S4")
                notes = f.setdefault("notes", [])
                if RND3_CHECK_NOTE not in notes:
                    notes.append(RND3_CHECK_NOTE)
            elif rule == "str5.names":
                variants = (f.get("evidence") or {}).get("variants") or []
                main = max(variants, key=lambda v: v.get("pages") or 0, default=None)
                lead = (main or {}).get("normalized") or ""
                categories = [v for v in variants if v is not main and lead and str(v.get("normalized", "")).startswith(lead + " ")
                              and set((v.get("by_source") or {})) == {"title suffix/prefix"}]
                if categories:
                    rest = [v for v in variants if v not in categories]
                    check.setdefault("evidence", {})["category_titles_not_counted"] = sorted(v.get("name") for v in categories)
                    if len(rest) <= 2:
                        changes.append(f"{f['id']}: removed; {len(categories)} of {len(variants)} names are category titles "
                                       f"({', '.join(sorted(v.get('name') for v in categories))}), DECISIONS 290")
                        affected.pop(f["id"], None)
                        continue
                    f["evidence"]["variants"] = rest
                    f["title"] = re.sub(r"named \d+ different ways", f"named {len(rest)} different ways", f["title"])
                    changes.append(f"{f['id']}: {len(categories)} category title(s) no longer counted, {len(rest)} names left")
            kept.append(f)
        if len(kept) != len(check.get("findings") or []):
            check["findings"] = kept
            from .checks.access import _status
            check["status"] = _status(kept, check.get("review_items") or ())


def _decisions_300(report: dict, affected: dict, changes: list[str]) -> None:
    from .double_reading import mark_report
    for fid in mark_report(report):
        changes.append(f"{fid}: seen only in Firecrawl's copy, not in Maya's own reading: estimated, confirm first "
                       "(DECISIONS 300)")
    from .checks.access import utility_indexable_findings
    from .models import page_from_record, to_jsonable
    acc3 = next((c for c in report.get("checks") or [] if c.get("check_id") == "ACC-3"), None)
    if acc3 is None or any(f.get("rule_id") == "acc3.utility_indexable" for f in acc3.get("findings") or []):
        return
    pages = [page_from_record(p) for p in (report.get("crawl") or {}).get("pages") or []
             if isinstance(p, dict) and p.get("content_checks_eligible") is not False and p.get("analysis")]
    agent = (report.get("crawl") or {}).get("user_agent") or ""
    for finding in to_jsonable(utility_indexable_findings(pages, set(), agent)):
        acc3.setdefault("findings", []).append(finding)
        affected[finding["id"]] = list((finding.get("scope") or {}).get("urls") or [])
        changes.append(f"{finding['id']}: added: {finding['title']} (DECISIONS 300)")
        from .checks.access import _status
        acc3["status"] = _status(acc3["findings"], acc3.get("review_items") or ())


def saved_jsonld(report: dict, blocks_by_url: dict[str, list[str]]) -> int:
    """Put the Product fields and a JSON-LD author, read from each page's saved JSON-LD blocks (the audit's evidence
    copies), on the copy's page records (`analysis.structured_data.products`, `analysis.author_signals`), as a report
    written by schema 1.24 holds them. Returns how many pages got Product fields. A block that does not parse is skipped."""
    import json
    from .analysis import jsonld_author, product_fields
    with_products = 0
    for record in (report.get("crawl") or {}).get("pages") or []:
        analysis = record.get("analysis") if isinstance(record, dict) else None
        raw = blocks_by_url.get(record.get("url")) if isinstance(analysis, dict) else None
        if not raw:
            continue
        values = []
        for block in raw:
            try:
                values.append(json.loads(block))
            except ValueError:
                try:
                    values.append(json.loads(block, strict=False))
                except ValueError:
                    continue
        products = product_fields(values)
        if products:
            analysis.setdefault("structured_data", {})["products"] = products
            with_products += 1
        if jsonld_author([{"data": v} for v in values]):
            analysis["author_signals"] = sorted(set(analysis.get("author_signals") or []) | {"JSON-LD author"})
    return with_products


def _decisions_304(report: dict, affected: dict, changes: list[str], unassessed: list[dict]) -> None:
    from types import SimpleNamespace
    from .checks.access import _status
    from .checks.quick_rules import findings as quick_findings
    from .launch_gate import items_of
    from .models import page_from_record, to_jsonable
    crawl = report.get("crawl") or {}
    pages = [page_from_record(p) for p in crawl.get("pages") or [] if isinstance(p, dict)]
    result = SimpleNamespace(pages=pages, start_url=crawl.get("start_url") or "", origin=crawl.get("origin"),
                             discovered_urls=crawl.get("discovered_urls") or [], sitemap_urls=crawl.get("sitemap_urls") or [],
                             sitemap_docs=crawl.get("sitemap_docs") or [], page_grouping=None)
    checks = {c.get("check_id"): c for c in report.get("checks") or [] if c.get("status") != "not_assessed"}
    made, missing = quick_findings(result, check_ids=set(checks), saved=True)
    unassessed.extend(missing)
    for check_id, new in made.items():
        check = checks[check_id]
        have = {f.get("rule_id") for f in check.get("findings") or []}
        for finding in new:
            if finding.rule_id in have:
                continue
            finding.launch_gated = items_of(check_id, finding)[0]
            urls = list(finding.scope.get("_all_urls") or finding.scope.get("urls") or [])
            record = to_jsonable(finding)
            check.setdefault("findings", []).append(record)
            affected[record["id"]] = urls
            changes.append(f"{record['id']}: added: {record['title']} ({record['severity']}, {record['confidence']}; DECISIONS 304)")
        check["status"] = _status(check.get("findings") or [], check.get("review_items") or ())


def _order(report: dict) -> list[str]:
    from .findings import Severity, priority_key
    from .models import Confidence
    findings = [f for c in report.get("checks") or [] if not str(c.get("check_id", "")).startswith("ANS")
                for f in c.get("findings") or []]

    def key(f):
        return priority_key(SimpleNamespace(check_id=f["check_id"], severity=Severity(f["severity"]),
                                            importance_tier=f.get("importance_tier", 2), scope=f.get("scope") or {},
                                            confidence=Confidence(f.get("confidence", "inferred")),
                                            launch_gated=f.get("launch_gated") or []))
    return [f["id"] for f in sorted(findings, key=key)]


def apply(report: dict, affected: dict | None = None, *, source_audit_id: str | None = None,
          jsonld_by_url: dict[str, list[str]] | None = None) -> tuple[dict, dict, dict]:
    """(report, affected, record) for a copy of `report` with the changed rules applied. `record` lists every change
    and what could not be assessed offline; it is also written to `generation.analysis`. `jsonld_by_url`: each page's
    saved JSON-LD blocks (the audit's evidence copies), for the Product fields and authors (DECISIONS 304)."""
    from . import release_gate
    from .report import problem_summary
    from .severity import apply as apply_severity
    r, aff = deepcopy(report), deepcopy(affected or {})
    changes: list[str] = []
    unassessed: list[str] = []
    _hidden_h1(r, changes)
    _calculator_grids(r, aff, changes, unassessed)
    _decisions_290(r, aff, changes)
    _decisions_300(r, aff, changes)
    quick_unassessed: list[dict] = []
    if jsonld_by_url:
        n = saved_jsonld(r, jsonld_by_url)
        changes.append(f"Product fields read from the saved JSON-LD of {n} page(s) (DECISIONS 304)")
    _decisions_304(r, aff, changes, quick_unassessed)
    from .language_regions import attach as attach_regions
    for fid in attach_regions(r):
        changes.append(f"{fid}: page regions in the other language recorded (DECISIONS 301)")
    apply_severity(r.get("checks") or [], r.get("crawl") or {})
    order = _order(r)
    r["findings_in_priority_order"] = order
    by_id = {f["id"]: f for c in r.get("checks") or [] for f in c.get("findings") or []}
    old = r.get("problem_summary") or {}
    single = old.get("single_page")
    r["problem_summary"] = problem_summary([by_id[i] for i in order], aff, pages_checked=old.get("pages_checked") or 0,
                                           checks=r.get("checks"),
                                           single_page=single.get("url") if isinstance(single, dict) else single,
                                           start_address=old.get("start_address"))
    r["release_gate"] = release_gate.run(r, aff)
    record = {
        "kind": "offline rule reassessment", "rules": "DECISIONS 284 (3) and (4), 290, 300, 301 and 304, applied by DECISIONS 285",
        "source_audit_id": source_audit_id, "processed_at": datetime.now(timezone.utc).isoformat(),
        "requests": 0, "changes": changes,
        "not_assessed_offline": ([{"rule": "STR-8 controls beside a grid", "why": NOT_ASSESSED_OFFLINE,
                                   "pages": sorted(set(unassessed))}] if unassessed else
                                 [{"rule": "STR-8 controls beside a grid", "why": NOT_ASSESSED_OFFLINE,
                                   "pages": [], "effect": "no pricing grid left to assess"}]) + quick_unassessed,
        "unchanged": "every other finding, observation, time and count is the source report's",
    }
    r.setdefault("generation", {})["analysis"] = record
    return r, aff, record
