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

import json
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
            from .analysis import ORG_AUTHOR, jsonld_author_kind
            # DECISIONS 363: an author that is only an organization is said as that, not as a named author
            org = jsonld_author_kind([{"data": v} for v in values]) == "organization"
            signals = set(analysis.get("author_signals") or []) - {"JSON-LD author", ORG_AUTHOR}
            analysis["author_signals"] = sorted(signals | {ORG_AUTHOR if org else "JSON-LD author"})
    return with_products


def _decisions_315(report: dict, changes: list[str]) -> None:
    """Stage 8a: every redirect hop per requested address (`crawl.redirects`, schema 1.26), from the saved page
    records (each redirect answer is kept with its status and target)."""
    from .checks.stage8_rules import redirect_records
    from .models import page_from_record
    crawl = report.get("crawl") or {}
    if crawl.get("redirects") is not None:
        return
    pages = [page_from_record(p) for p in crawl.get("pages") or [] if isinstance(p, dict)]
    crawl["redirects"] = redirect_records(pages)
    if crawl["redirects"]:
        changes.append(f"{len(crawl['redirects'])} redirecting address(es) recorded hop by hop (DECISIONS 315)")


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
                             sitemap_docs=crawl.get("sitemap_docs") or [], page_grouping=None,
                             structure=crawl.get("structure"),
                             # DECISIONS 343: the redirect hops and the missing-page probe, for idx1.error_redirect
                             redirects=crawl.get("redirects"), index=crawl.get("index"))
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


def _decisions_309(report: dict, changes: list[str], saved_texts: list[str]) -> None:
    """The platform from the saved data when the report names none (a page reader's copies keep no script list), and
    RND-6 measured on Firecrawl's HTML labelled as such (an audit saved before the label, DECISIONS 299 (4))."""
    from .checks.render import RENDERED_NOTE, RENDERED_VIA_FIRECRAWL
    from .site_platform import recognise_saved
    if not (report.get("platform") or {}).get("name"):
        found = recognise_saved(report, saved_texts)
        if found:
            report["platform"] = found
            changes.append(f"platform: {found['name']} recognised from the saved data ({'; '.join(found['signals'])}), DECISIONS 309")
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            ev = f.get("evidence") or {}
            if f.get("check_id") != "RND-6" or ev.get("html_measured") or (ev.get("source") or {}).get("reader") != "firecrawl":
                continue
            f["title"] = (f.get("title") or "") + RENDERED_VIA_FIRECRAWL
            f["evidence"] = {**ev, "html_measured": "rendered (Firecrawl)"}
            f["notes"] = list(f.get("notes") or []) + [RENDERED_NOTE]
            changes.append(f"{f['id']}: measured on Firecrawl's rendered HTML, labelled and sent to confirm first (DECISIONS 309)")


# ---------------------------------------------------------------- DECISIONS 316

# What a saved page record shows of a bot-protection page that answered 200 with the vendor's own document (the live
# classifier reads the body; a saved record keeps the iframes and the visible word count). Imperva's block page:
# "Request unsuccessful. Incapsula incident ID: ..." in an iframe of /_Incapsula_Resource (airastana.com, 2026-11-05).
BLOCK_PAGE_MAX_WORDS = 50
# Checks that are about the request, not the page's content: what was measured on a block page stays measured.
REQUEST_CHECKS = ("ACC-1", "ACC-2", "ACC-4", "ACC-5", "ACC-6", "ACC-7", "ACC-8", "IDX-2", "INT-1", "INT-2", "INT-3", "INT-4")
BLOCK_SIZE_MARGIN = 200  # bytes: a light request's answer this close to the block pages' size, with their robots tag


def saved_block_page(record: dict) -> str | None:
    """The vendor whose block page a saved page record holds, or None (DECISIONS 316)."""
    if not isinstance(record, dict) or record.get("fetch_class") != "ok":
        return None
    a = record.get("analysis") or {}
    if int(a.get("visible_words") or 0) > BLOCK_PAGE_MAX_WORDS:
        return None
    if any("/_Incapsula_Resource" in str((f or {}).get("src") or "") for f in a.get("iframes") or [] if isinstance(f, dict)):
        return "Imperva"
    return None


def _robots_of(record: dict) -> str:
    meta = (record.get("analysis") or {}).get("meta") or []
    return next((str(m.get("content") or "").strip().lower() for m in meta
                 if isinstance(m, dict) and str(m.get("name") or "").lower() == "robots"), "")


def _decisions_316(report: dict, affected: dict, changes: list[str]) -> None:
    """Block pages in the saved data, and the site's country/language folders (DECISIONS 316).

    A page Maya's crawler saved as read that is a bot-protection page (`saved_block_page`) is marked blocked: it is not
    a page read, and what was measured only on it (its noindex, its iframe, its timing, the sitemap addresses that gave
    the same document) is left out, each removal listed. Findings judged on the page reader's own copy of a page stay.
    The soft-404 probe's answer is the same document when every page was blocked: it goes to "confirm first"."""
    crawl = report.get("crawl") or {}
    if crawl.get("locales") is None:
        from .final import locale_record
        from .models import page_from_record
        pages = [page_from_record(p) for p in crawl.get("pages") or [] if isinstance(p, dict)]
        view = SimpleNamespace(pages=pages, start_url=crawl.get("start_url") or "", origin=crawl.get("origin"),
                               sitemap_urls=crawl.get("sitemap_urls") or [], discovered_urls=crawl.get("discovered_urls") or [])
        crawl["locales"] = locale_record(view)
        if int(crawl["locales"].get("versions") or 0) >= 2:
            changes.append(f"{crawl['locales']['versions']} country/language versions recorded (crawl.locales, DECISIONS 316)")
    records = [p for p in crawl.get("pages") or [] if isinstance(p, dict)]
    blocked = {p["url"]: saved_block_page(p) for p in records if saved_block_page(p)}
    if not blocked:
        return
    vendor = sorted(set(blocked.values()))[0]
    sizes = [int(p.get("body_bytes") or 0) for p in records if p["url"] in blocked]
    robots = {_robots_of(p) for p in records if p["url"] in blocked} - {""}
    for p in records:
        if p["url"] in blocked:
            p["fetch_class"] = "blocked"
            p["content_checks_eligible"] = False
            if isinstance(p.get("grouping"), dict):
                p["grouping"]["read"] = False  # not a page read: never a key page
            p["classification_confidence"] = "estimated"
            p["classification_evidence"] = list(p.get("classification_evidence") or []) + [
                f"body signature imperva_incapsula_iframe: {vendor}'s block page, recognised from the saved page record "
                "(DECISIONS 316)"]
    changes.append(f"{len(blocked)} page(s) Maya's crawler saved as read are {vendor}'s block page: marked blocked, "
                   "not counted as read (DECISIONS 316)")
    fc = report.get("firecrawl") or {}
    fc_read = {r.get("url") for r in fc.get("pages") or [] if isinstance(r, dict) and r.get("outcome") == "read"} if fc.get("used") else set()
    fc_checks = set(fc.get("checks_from_firecrawl") or []) if fc.get("used") else set()

    def same_document(attempt: dict) -> bool:
        if attempt.get("url") in blocked or attempt.get("fetch_class") == "blocked":
            return True
        noindex = " ".join(attempt.get("noindex") or []).lower()
        size = attempt.get("body_bytes", attempt.get("bytes"))
        return (bool(sizes) and isinstance(size, int) and min(sizes) - BLOCK_SIZE_MARGIN <= size <= max(sizes) + BLOCK_SIZE_MARGIN
                and bool(robots) and any(r in noindex for r in robots))

    for check in report.get("checks") or []:
        cid = check.get("check_id") or ""
        if cid in REQUEST_CHECKS or cid.startswith(("ANS", "DFS")):
            continue
        kept = []
        for f in check.get("findings") or []:
            urls = list(affected.get(f["id"]) or (f.get("scope") or {}).get("urls") or [])
            if cid == "IDX-5":
                decisions = (f.get("evidence") or {}).get("sitemap_decisions") or []
                attempts = [d["attempts"][-1] for d in decisions if isinstance(d, dict) and d.get("attempts")]
                if attempts and all(same_document(a) for a in attempts):
                    changes.append(f"{f['id']}: removed; all {len(attempts)} sitemap address(es) checked answered with "
                                   f"{vendor}'s block page, not the site's page (DECISIONS 316)")
                    affected.pop(f["id"], None)
                    continue
            elif cid == "IDX-1" and ((f.get("evidence") or {}).get("probe") or {}).get("title") is None \
                    and len(blocked) >= len([p for p in records if p.get("status") and 200 <= p["status"] < 300]):
                f["confidence"] = "estimated"
                note = (f"Every page Maya requested answered with {vendor}'s block page, so this answer is most likely the "
                        "same block page, not the site's own: check a made-up address in a normal browser.")
                if note not in (f.get("notes") or []):
                    f["notes"] = list(f.get("notes") or []) + [note]
                    changes.append(f"{f['id']}: estimated, confirm first: the probe most likely got {vendor}'s block page (DECISIONS 316)")
            else:
                bad = [u for u in urls if u in blocked and not (cid in fc_checks and u in fc_read)]
                if urls and len(bad) == len(urls):
                    changes.append(f"{f['id']}: removed; measured only on {vendor}'s block page ({len(bad)} page(s)): "
                                   f"{(f.get('title') or '')[:80]} (DECISIONS 316)")
                    affected.pop(f["id"], None)
                    continue
                if bad:
                    affected[f["id"]] = [u for u in urls if u not in set(bad)]
                    f["notes"] = list(f.get("notes") or []) + [
                        f"{len(bad)} of its pages were {vendor}'s block page and are left out (DECISIONS 316)."]
                    changes.append(f"{f['id']}: {len(bad)} block page(s) left out of its pages (DECISIONS 316)")
            kept.append(f)
        if len(kept) != len(check.get("findings") or []):
            from .checks.access import _status
            check["findings"] = kept
            check["status"] = _status(kept, check.get("review_items") or ())
    _no_comparison(report, records, vendor, changes)
    _block_status(report, blocked, vendor, changes)


def _no_comparison(report: dict, records: list[dict], vendor: str, changes: list[str]) -> None:
    """"Seen only in Firecrawl's copy" (DECISIONS 300 (9)) compares the reader's copy with Maya's own. When every page
    Maya's crawler saved was a block page there is nothing to compare: a fresh audit of a blocked site sets no such mark
    (`double_reading.applies`), so it is taken off; the finding keeps its own confidence and notes otherwise."""
    from .double_reading import NOTE, SEEN_IN
    own = [p for p in records if p.get("analysis") and p.get("view") != "provider"]
    if not own or any(p.get("fetch_class") == "ok" and p.get("content_checks_eligible") is not False for p in own):
        return
    cleared = 0
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            ev = f.get("evidence") or {}
            if (ev.get("reading") or {}).get("seen_in") == SEEN_IN:
                ev.pop("reading", None)
                f["notes"] = [n for n in f.get("notes") or [] if n != NOTE]
                cleared += 1
    if cleared:
        changes.append(f"{cleared} finding(s) no longer marked \"seen only in Firecrawl's copy\": every page of Maya's own "
                       f"copy was {vendor}'s block page, so there was nothing to compare (DECISIONS 316)")


def _block_status(report: dict, blocked: dict, vendor: str, changes: list[str]) -> None:
    """ACC-9, the direct-access line and the pages-read count of a copy whose block pages were recognised."""
    from .checks.access import acc9_automated_visitors
    from .models import page_from_record, to_jsonable
    from .report import read_counts, read_status_summary, coverage_note, also_fetched
    crawl = report.get("crawl") or {}
    pages = [page_from_record(p) for p in crawl.get("pages") or [] if isinstance(p, dict)]
    requests = [SimpleNamespace(url=r.get("url"), purpose=r.get("purpose"), status=r.get("status"))
                for r in crawl.get("requests") or [] if isinstance(r, dict)]
    view = SimpleNamespace(pages=pages, start_url=crawl.get("start_url") or "", origin=crawl.get("origin"),
                           requests=requests, user_agent=crawl.get("user_agent") or "")
    cfg = SimpleNamespace(degraded_threshold=float((crawl.get("config") or {}).get("degraded_threshold") or 0.20),
                          product_token=crawl.get("product_token") or "Maya-Audit")
    result = acc9_automated_visitors(view, cfg)
    fc = report.get("firecrawl") or {}
    if fc.get("used") and fc.get("pages_read") and result.findings:
        from .firecrawl.reader import note_the_challenge
        note_the_challenge([result], int(fc["pages_read"]))
    acc9 = to_jsonable(result)
    for i, check in enumerate(report.get("checks") or []):
        if check.get("check_id") == "ACC-9":
            report["checks"][i] = {**check, **{k: acc9[k] for k in ("status", "summary", "findings", "evidence") if k in acc9}}
            changes.append(f"ACC-9: {acc9.get('summary')} (DECISIONS 316)")
    status = report.get("audit_status") or {}
    direct = status.get("direct_access")
    own = [p for p in pages if not (p.status is not None and 300 <= p.status < 400)]
    if isinstance(direct, dict) and own:
        by = {name: sum(1 for p in own if p.fetch_class.value == name) for name in ("ok", "blocked", "rate_limited", "error")}
        direct.update(state="challenged" if by["blocked"] else direct.get("state"), by_response=by,
                      note=f"Maya's direct crawler was challenged or blocked on {by['blocked']} of {len(own)} page "
                           f"request(s) ({vendor}'s block page, answered with status 200).")
    counts = read_counts(crawl, report.get("firecrawl"))
    cov = status.get("content_coverage")
    if isinstance(cov, dict):
        cov.update(pages_read=counts["pages"], readable_unique_urls=counts["pages"], read_by=counts["read_by"],
                   other_addresses=counts["other_addresses"])
        if not counts["pages"]:
            cov["level"] = "none"
        also = also_fetched(counts["other_addresses"])
        cov["note"] = coverage_note(cov["level"], counts["pages"]) + (" " + also if also else "")
        if direct and status.get("vendor_crawler_evidence"):
            status["summary"] = read_status_summary(status, counts)
    summary = report.get("problem_summary")
    if isinstance(summary, dict):
        summary["pages_checked"] = counts["pages"]


def _decisions_317(report: dict, changes: list[str]) -> None:
    """DECISIONS 317: how the plan's page limit is shared, for a saved audit the page reader read: Maya's pages read
    count, its block answers do not (`firecrawl.coverage.page_limit`, worked out from the saved data; the reading
    itself is what the audit's engine did, so it is marked `worked_out_offline`)."""
    fc = report.get("firecrawl") or {}
    cov = fc.get("coverage")
    if not fc.get("used") or not isinstance(cov, dict) or isinstance(cov.get("page_limit"), dict):
        return
    from .firecrawl.reader import page_limit_record
    crawl = report.get("crawl") or {}
    plan = fc.get("page_cap") or (fc.get("options") or {}).get("max_pages") or (crawl.get("config") or {}).get("max_pages")
    if not isinstance(plan, int):
        return
    read = sum(1 for p in crawl.get("pages") or [] if isinstance(p, dict) and p.get("fetch_class") == "ok"
               and isinstance(p.get("status"), int) and 200 <= p["status"] < 300 and p.get("content_checks_eligible") is not False
               and p.get("analysis"))
    cov["page_limit"] = {**page_limit_record(crawl, plan, read), "worked_out_offline": True}
    if cov["page_limit"]["block_answers"]:
        changes.append(f"Page limit: {cov['page_limit']['block_answers']} block answer(s) to Maya's crawler not counted; the page "
                       f"reader could read up to {cov['page_limit']['reader_new_pages_allowed']} of {plan} page(s) and read "
                       f"{fc.get('pages_read') or 0} (DECISIONS 317)")


def _decisions_318(report: dict, changes: list[str]) -> None:
    """DECISIONS 318: a saved 429 block on Maya's page requests that was consistent (`checks.access.consistent_429`, read
    from the finding's evidence and the saved page records) is measured: its confidence becomes Verified, so it is a card
    and not "Teyit edin". A single or occasional 429 keeps Inferred."""
    from .checks.access import consistent_429
    crawl = report.get("crawl") or {}
    threshold = float((crawl.get("config") or {}).get("degraded_threshold") or 0.20)
    start = next((p for p in crawl.get("pages") or [] if isinstance(p, dict) and p.get("discovered_via") == "start"), {})
    retried = bool(start.get("retried_after_429")) and start.get("status") == 429
    for check in report.get("checks") or []:
        if check.get("check_id") != "ACC-9":
            continue
        for f in check.get("findings") or []:
            if f.get("rule_id") not in ("acc9.blocked_429", "acc9.rate_limited_429") or f.get("confidence") != "inferred":
                continue
            ev = f.get("evidence") or {}
            blocked, asked = int(ev.get("pages_blocked_or_challenged") or 0), int(ev.get("pages_requested") or 0)
            widespread = bool(ev.get("start_url_blocked")) or (asked > 0 and blocked / asked >= threshold)
            if consistent_429(blocked, retried and bool(ev.get("start_url_blocked")), widespread):
                f["confidence"] = "verified"
                changes.append(f"{f['id']}: Verified, a card: the 429s on Maya's page requests were consistent "
                               f"({blocked} of {asked}{', the homepage asked again after the wait' if retried else ''}) (DECISIONS 318)")


def _not_retested(f: dict) -> None:
    """A High or Blocker finding carries a re-test state (RG-5); a certificate's expiry date has no re-test, so it says
    "not_retested" with the reason, as the engine's verification stage writes it."""
    if f.get("severity") in ("S1", "S2") and not f.get("verification"):
        f["verification"] = {"state": "not_retested", "checked": [], "reason": "no re-test for this rule",
                             "subjects": list((f.get("scope") or {}).get("urls") or [])}


def _decisions_321(report: dict, changes: list[str]) -> None:
    """DECISIONS 321/322: a saved certificate expiry gets its severity by the days left at the audit (7 days or fewer
    Blocker, 14 or fewer High, 30 or fewer Medium; inclusive since DECISIONS 322), and a certificate the saved IDX-2 evidence shows inside the new 30-day window, with no
    expiry finding (the old window was 14 days), gets the finding this engine would write (same title, same id)."""
    from .checks.index import expiry_finding, expiry_severity
    from .config import CrawlConfig
    from .models import to_jsonable
    window = CrawlConfig.tls_expiry_warning_days
    for check in report.get("checks") or []:
        if check.get("check_id") != "IDX-2":
            continue
        findings = check.setdefault("findings", [])
        dated = set()
        for f in findings:
            if f.get("rule_id") != "idx2.expires":
                continue
            hosts = (f.get("evidence") or {}).get("hosts") or []
            days = next((h.get("days_left") for h in hosts if isinstance(h.get("days_left"), (int, float))), None)
            dated |= {h.get("not_after") for h in hosts}
            if days is None:
                continue
            target = expiry_severity(days).value
            if f.get("severity") != target:
                changes.append(f"{f['id']}: certificate expires in {days:g} day(s): {f.get('severity')} -> {target} (DECISIONS 321)")
                _set_severity(f, target)
            f["expected"] = f"more than {window:g} days of validity left"  # the 30-day window, not the old 14
            _not_retested(f)
        expiring: dict[str, list[dict]] = {}
        for entry in (check.get("evidence") or {}).get("hosts") or []:
            tls = (entry or {}).get("tls") or {}
            if (tls.get("valid") and isinstance(tls.get("days_left"), (int, float)) and tls["days_left"] <= window
                    and tls.get("not_after") and tls["not_after"] not in dated):
                expiring.setdefault(tls["not_after"], []).append(entry)
        for not_after, entries in expiring.items():
            new = to_jsonable(expiry_finding(not_after, entries, window))
            _not_retested(new)
            findings.append(new)
            changes.append(f"{new['id']}: certificate expires in {new['evidence']['hosts'][0]['days_left']:g} day(s), inside "
                           f"the 30-day window: a {new['severity']} finding (DECISIONS 321)")
        if findings:
            check["status"] = "findings"


def _decisions_329(report: dict, changes: list[str]) -> None:
    """DECISIONS 329: IDX-8's "pages differ mostly by the place name" groups stand only on the business type's location
    pages; the page types are the current engine's (`client_selection.grouping`, as the team report reads them)."""
    from .checks.index import LOCATION_RULE, gate_location_templates
    from .client_selection import grouping
    if not any(f.get("rule_id") == LOCATION_RULE for c in report.get("checks") or [] if c.get("check_id") == "IDX-8"
               for f in c.get("findings") or []):
        return
    records, summary = grouping(report)
    info = (summary or {}).get("business_type") or {}
    if info.get("error"):
        return  # the business type could not be worked out: the saved finding stays as it was
    types = {u: (g or {}).get("business_page_type") for u, g in records.items()}
    least = ((report.get("crawl") or {}).get("config") or {}).get("location_template_min_pages")
    for row in gate_location_templates(report.get("checks") or [], types, info.get("id"), least):
        changes.append(f"{row['finding_id']}: pages under {row['section']} differ by place name, but {row['reason']} "
                       f"({', '.join(row['page_types'])}): left out (DECISIONS 329)")


def _decisions_337(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 337: IDX-1's "4xx, linked internally or listed in the sitemap" split by what is to be fixed (the links,
    the sitemap entries, mistyped hrefs), traced again from the saved pages' links and redirects; the sitemap file of
    each entry from the saved sitemap files (`sitemap.file_map`). The new findings' pages go into `affected`."""
    from dataclasses import fields
    from .checks.index import REFERENCED_4XX_TITLE, broken_link_sources
    from .findings import Finding, Severity
    from .models import Confidence, page_from_record, to_jsonable
    check = next((c for c in report.get("checks") or [] if c.get("check_id") == "IDX-1"), None)
    if check is None:
        return
    todo = [f for f in check.get("findings") or [] if REFERENCED_4XX_TITLE.search(f.get("title") or "")
            and (f.get("evidence") or {}).get("split") != 337]
    if not todo:
        return
    crawl = report.get("crawl") or {}
    result = SimpleNamespace(pages=[page_from_record(p) for p in crawl.get("pages") or [] if isinstance(p, dict)],
                             sitemap_urls=crawl.get("sitemap_urls") or [], sitemap_docs=crawl.get("sitemap_docs") or [],
                             config=crawl.get("config") or {}, origin=crawl.get("origin"), start_url=crawl.get("start_url"))
    names = {f.name for f in fields(Finding)}
    objects = []
    for f in todo:
        values = {k: v for k, v in f.items() if k in names}
        values["severity"], values["confidence"] = Severity(f["severity"]), Confidence(f["confidence"])
        objects.append(Finding(**values))
    native = SimpleNamespace(check_id="IDX-1", findings=objects)
    broken_link_sources([native], result)
    kept = [f for f in check["findings"] if f not in todo]
    made = [to_jsonable(f) for f in native.findings]
    check["findings"] = kept + made
    old_ids = {f["id"] for f in todo}
    for f in made:
        affected[f["id"]] = list((f.get("scope") or {}).get("urls") or [])
    for i in old_ids - {f["id"] for f in made}:
        affected.pop(i, None)
    changes.append(f"IDX-1 broken links split by what is to be fixed: {', '.join(f['rule_id'] or f['title'][:40] for f in made)} "
                   "(DECISIONS 337)")


def _refresh_id(f: dict, affected: dict, old: str | None, urls: list | None = None) -> None:
    """A saved finding's id and rule after its title or scope changed, and its affected list moved with it."""
    import hashlib
    from .rules import rule_id
    f["rule_id"] = rule_id(f["check_id"], f["title"])
    basis = f"{f['check_id']}|{f['title']}|{sorted((f.get('scope') or {}).get('urls', []))}"
    f["id"] = f"{f['check_id']}-{hashlib.sha1(basis.encode()).hexdigest()[:8]}"
    if old and old != f["id"]:
        affected.pop(old, None)
    affected[f["id"]] = list(urls if urls is not None else (f.get("scope") or {}).get("urls") or [])


def _decisions_338(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 338, from the SEO team's review of enpara 2e5829fb, applied to a saved report's findings:
    (1) TSEO-1: a page whose head breaks before only meta or Open Graph tags (a robots tag whose value was not recorded
    included) moves from High to Medium; (2) ACC-2: a block on parameter, old-script or form paths that reaches no page
    the site puts forward is Info; (3) STR-5: the domain form and a section's sub-brand are not other names, and the
    pages to fix are those with another name; (4) STR-2: listing pages are not long pages lacking subheadings;
    (5) IDX-2: a temporary http:// -> https:// code under HSTS of a year or more is Info."""
    from .checks.access import DELIBERATE_NOTES, deliberate_rule
    from .checks.index import HSTS_LONG_S, HSTS_NOTE
    from .checks.page_markup import HEAD_KEPT_NOTE, kept_in_head, place_head_row
    from .checks.structure import BRANCH_EXTRA_WORDS, brand_key, drop_listing_pages
    from .findings import scope_for
    crawl = report.get("crawl") or {}
    pages = {p.get("url"): p for p in crawl.get("pages") or [] if isinstance(p, dict)}
    checks = report.get("checks") or []
    by_check = {c.get("check_id"): c for c in checks}

    # (1) TSEO-1
    head = by_check.get("TSEO-1")
    lost_f = next((f for f in (head or {}).get("findings") or [] if f.get("rule_id") == "tseo1.head_closed_lost"), None)
    if lost_f:
        later_f = next((f for f in head["findings"] if f.get("rule_id") == "tseo1.head_closed_later"), None)
        rows = {r["url"]: r for f in (lost_f, later_f) if f for r in (f.get("evidence") or {}).get("pages") or []}
        urls = list(dict.fromkeys([*((lost_f.get("scope") or {}).get("urls") or []),
                                   *(((later_f or {}).get("scope") or {}).get("urls") or [])]))
        lost, later = [], []
        for u in urls:
            a = (pages.get(u) or {}).get("analysis") or {}
            out = a.get("outside_head") or {}
            row = dict(rows.get(u) or {"url": u, "closed_by": out.get("closed_early_by"), "canonical_after": out.get("canonical", 0),
                                       "robots_after": sorted({"robots", "googlebot", "bingbot"} & set(out.get("meta") or [])),
                                       "hreflang_after": out.get("hreflang", 0), "meta_after": [], "properties_after": [],
                                       "title_after": out.get("title", 0)})
            row.setdefault("robots_content", out.get("robots_content"))
            row["kept_in_head"] = kept_in_head(a)
            place_head_row(row, lost, later)
        moved = len(urls) - len(lost) - (len(((later_f or {}).get("scope") or {}).get("urls") or []))
        if moved > 0 or not lost:
            old_lost, old_later = lost_f.get("id"), (later_f or {}).get("id")
            if later and not later_f:
                later_f = deepcopy(lost_f)
                head["findings"].append(later_f)
            if later_f is not None and later:
                later_f.update(title=f"{len(later)} page(s) end <head> early: meta or Open Graph tags after it are read as body",
                               severity="S3", scope=scope_for([r["url"] for r in later]),
                               expected="every meta and Open Graph tag before any body element",
                               evidence={**(later_f.get("evidence") or {}), "pages": later[:40]})
                later_f["notes"] = [n for n in later_f.get("notes") or [] if not n.startswith("Verified from the HTML: the element")] + \
                    ([HEAD_KEPT_NOTE] if HEAD_KEPT_NOTE not in (later_f.get("notes") or []) else [])
                _refresh_id(later_f, affected, old_later, [r["url"] for r in later])
            if lost:
                lost_f.update(title=f"{len(lost)} page(s) end <head> early: canonical, robots or hreflang tags after it are read as body",
                              scope=scope_for([r["url"] for r in lost]), evidence={**lost_f["evidence"], "pages": lost[:40]})
                _refresh_id(lost_f, affected, old_lost, [r["url"] for r in lost])
            else:
                head["findings"].remove(lost_f)
                affected.pop(old_lost, None)
            changes.append(f"TSEO-1: {moved} page(s) whose head breaks before only meta or Open Graph tags moved from High to "
                           "Medium (DECISIONS 338)")

    # (2) ACC-2
    n = 0
    for f in (by_check.get("ACC-2") or {}).get("findings") or []:
        ev = f.get("evidence") or {}
        kind = deliberate_rule((ev.get("rule") or {}).get("pattern") or "")
        if kind and (ev.get("path_kind") or {}).get("kind") == "not_put_forward" and f.get("severity") != "Info":
            pattern = ev["rule"]["pattern"]
            f["intent"] = {"kind": "deliberate_rule", "rule_kind": kind, "severity_otherwise": f["severity"]}
            f["severity"] = "Info"
            f["notes"] = [*(f.get("notes") or []), DELIBERATE_NOTES[kind].format(pattern=pattern)]
            ev["path_kind"] = {"kind": "deliberate_rule", "rule_kind": kind}
            n += 1
    if n:
        changes.append(f"ACC-2: {n} block(s) on parameter, old-script or form paths only are Info (DECISIONS 338)")

    # (3) STR-5
    for f in list((by_check.get("STR-5") or {}).get("findings") or []):
        if not str(f.get("title") or "").startswith("The brand is named"):
            continue
        ev = f.get("evidence") or {}
        merged: dict[str, dict] = {}
        for v in ev.get("variants") or []:
            key = brand_key(v.get("name") or v.get("normalized") or "")
            m = merged.setdefault(key, {"name": v.get("name"), "pages": 0, "seen_as": [], "sources": set()})
            m["pages"] += v.get("pages") or 0
            m["seen_as"] += v.get("seen_as") or []
            m["sources"] |= set((v.get("by_source") or {}).keys())
        if not merged:
            continue
        main = max(merged, key=lambda k: (merged[k]["pages"], k))
        home = (crawl.get("start_url") or "").rstrip("/") + "/"
        subs = [k for k, m in merged.items() if k != main and k.startswith(main + " ")
                and BRANCH_EXTRA_WORDS[0] <= len(k.split()) - len(main.split()) <= BRANCH_EXTRA_WORDS[1]
                and m["sources"] <= {"title suffix/prefix", "og:site_name"} and all(s.get("url") != home for s in m["seen_as"])]
        counted = [k for k in merged if k not in subs]
        old = f.get("id")
        if len(counted) <= 2:
            report_findings = by_check["STR-5"]["findings"]
            report_findings.remove(f)
            affected.pop(old, None)
            changes.append(f"STR-5: the brand names seen are one name written as a domain or a sub-brand: no finding (DECISIONS 338)")
            continue
        urls = sorted({s["url"] for k in counted if k != main for s in merged[k]["seen_as"] if s.get("url")})
        f.update(title=f"The brand is named {len(counted)} different ways", scope=scope_for(urls))
        # a saved variant keeps 10 example pages: the count is what the engine counted, the list what it kept
        f["scope"]["count"] = max(len(urls), sum(merged[k]["pages"] for k in counted if k != main))
        ev.update(main_name=merged[main]["name"], sub_brands_not_counted=[merged[k]["name"] for k in subs],
                  variants=[v for v in ev.get("variants") or [] if brand_key(v.get("name") or "") in counted],
                  observed_values=sorted({s.get("value") for k in counted for s in merged[k]["seen_as"] if s.get("value")}))
        _refresh_id(f, affected, old, urls)
        changes.append(f"STR-5: {len(counted)} brand names counted (the domain form and sub-brands left out); "
                       f"{len(urls)} page(s) to fix (DECISIONS 338)")

    # (4) STR-2
    types = {u: (p.get("grouping") or {}).get("page_type") for u, p in pages.items() if isinstance(p.get("grouping"), dict)}
    before = {f.get("id") for c in checks for f in c.get("findings") or []}
    for fid in drop_listing_pages(checks, types):
        affected.pop(fid, None)
        changes.append(f"STR-2: listing pages left out of the long pages without subheadings (DECISIONS 338)")
    for c in checks:
        for f in c.get("findings") or []:
            if f.get("id") not in before:
                affected[f["id"]] = list((f.get("scope") or {}).get("urls") or [])

    # (5) IDX-2
    homes = [p for p in pages.values() if p.get("depth") == 0 and str(p.get("url", "")).startswith("https://")]
    hsts = None
    for p in homes:
        value = {str(k).lower(): v for k, v in (p.get("headers") or {}).items()}.get("strict-transport-security") or ""
        m = re.search(r"max-age\s*=\s*\"?(\d+)", value, re.I)
        if m:
            hsts = int(m.group(1))
            break
    for f in (by_check.get("IDX-2") or {}).get("findings") or []:
        if "with a temporary redirect" in (f.get("title") or "") and hsts and hsts >= HSTS_LONG_S and f.get("severity") != "Info":
            f["severity"] = "Info"
            f["notes"] = [*(f.get("notes") or []), HSTS_NOTE.format(days=round(hsts / 86400))]
            f.setdefault("evidence", {})["hsts_max_age_s"] = hsts
            changes.append(f"IDX-2: temporary http:// -> https:// redirect under HSTS of {round(hsts / 86400)} days is Info "
                           "(DECISIONS 338)")


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


def _texts_by_url(saved_texts: list[str] | None) -> dict[str, str]:
    """{url: main text} of the saved page copies (Maya's and the page reader's evidence files, as text)."""
    out: dict[str, str] = {}
    for raw in saved_texts or []:
        try:
            saved = json.loads(raw)
        except ValueError:
            continue
        if isinstance(saved, dict) and isinstance(saved.get("url"), str) and isinstance(saved.get("main_text"), str):
            out.setdefault(saved["url"], saved["main_text"])
    return out


def _decisions_356(report: dict, affected: dict, changes: list[str], saved_texts: list[str] | None = None,
                   business: str | None = None, unassessed: list[dict] | None = None) -> None:
    """DECISIONS 356: the business profile's own checks (`checks.profile_rules`) on the saved page records, with the
    pages typed for the audit's business type (the person's choice, else the report's or the suggestion) and the
    main text of the saved evidence copies. A finding of these rules already in the report is replaced."""
    from .checks import profile_rules
    from .client_selection import grouping
    from .launch_gate import items_of
    from .models import to_jsonable
    crawl = report.get("crawl") or {}
    pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict) and isinstance(p.get("analysis"), dict)]
    checks = {c.get("check_id"): c for c in report.get("checks") or [] if c.get("status") != "not_assessed"}
    before = {}
    for check in checks.values():
        for f in list(check.get("findings") or []):
            if f.get("rule_id") in profile_rules.RULES:
                before[f["rule_id"]] = f.get("title")
                check["findings"].remove(f)
                affected.pop(f.get("id"), None)
    if not pages:
        return
    records, summary = grouping(report, business)
    profile = (summary.get("business_type") or {}).get("id")
    types = {u: g.get("business_page_type") for u, g in records.items()}
    made, missing = profile_rules.findings(pages, types, profile, _texts_by_url(saved_texts))
    if unassessed is not None:
        unassessed.extend(missing)
    for check_id, new in made.items():
        check = checks.get(check_id)
        if check is None:
            continue
        for finding in new:
            finding.launch_gated = items_of(check_id, finding)[0]
            urls = list(finding.scope.get("_all_urls") or finding.scope.get("urls") or [])
            record = to_jsonable(finding)
            check.setdefault("findings", []).append(record)
            if check.get("status") == "pass":
                check["status"] = "findings"
            affected[record["id"]] = urls
            if before.get(record["rule_id"]) != record["title"]:
                changes.append(f"{record['id']}: {record['title']} ({record['severity']}; DECISIONS 356, {profile})")


def _decisions_359(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 359: after a move to the twin address (`crawl.host_moves`), the pages the earlier address answered with
    their content instead of redirecting are one card (`idx4.twin_served`), recorded as the move's copies, and no longer
    told again as canonicals on the www variant. Offline, from the saved page records; the other findings keep their
    counts until a new crawl reads each page once."""
    from .checks.index import INDEX_ENGINES, TWIN_SERVED_FIX, twin_served
    from .findings import Finding, Severity, scope_for
    from .launch_gate import items_of
    from .models import Confidence, to_jsonable
    from .urls import origin_of
    crawl = report.get("crawl") or {}
    moves = [m for m in crawl.get("host_moves") or [] if isinstance(m, dict)]
    if not moves:
        return
    pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict)]
    for move in moves:
        if move.get("copies") is not None:
            continue
        old = str(move.get("from") or "")
        copies = []
        for p in pages:
            status = p.get("status")
            if (origin_of(p.get("url") or "") == old and p.get("discovered_via") != "start" and isinstance(status, int)
                    and 200 <= status < 300 and "html" in str(p.get("content_type") or "").lower()):
                path = (p["url"][len(old):] or "/")
                copies.append({"url": p["url"], "status": status,
                               "canonical": next(iter(((p.get("analysis") or {}).get("canonicals") or [])), None),
                               "twin": str(move.get("to") or "") + path})
        move["copies"] = copies
    rows = twin_served(moves, pages)
    checks = {c.get("check_id"): c for c in report.get("checks") or []}
    check = checks.get("IDX-4")
    if not rows or check is None or check.get("status") == "not_assessed":
        return
    served = {r["url"] for r in rows}
    for f in list(check.get("findings") or []):
        if f.get("rule_id") == "idx4.twin_served":
            check["findings"].remove(f)
            affected.pop(f.get("id"), None)
        elif f.get("rule_id") == "idx4.variant":
            left = [r for r in (f.get("evidence") or {}).get("pages") or [] if r.get("url") not in served]
            urls = [u for u in affected.get(f.get("id")) or (f.get("scope") or {}).get("urls") or [] if u not in served]
            if not urls:
                check["findings"].remove(f)
                affected.pop(f.get("id"), None)
                changes.append(f"{f.get('id')}: removed, its pages are the twin address's copies (DECISIONS 359)")
            else:
                f["evidence"]["pages"] = left
                f["scope"] = {**f.get("scope", {}), "urls": urls[:25], "count": len(urls)}
                f["title"] = f"{len(urls)} page(s) declare a canonical on the http:// or www variant of this site"
                affected[f["id"]] = urls
    from urllib.parse import urlsplit
    urls = [r["url"] for r in rows]
    old_host, new_host = urlsplit(rows[0]["from"]).hostname, urlsplit(str(rows[0]["to"])).hostname
    finding = Finding(
        "IDX-4", f"{len(urls)} page(s) on {old_host} answer with their content instead of redirecting to {new_host}",
        Severity.S3, Confidence.VERIFIED, "Documented (Google: one address per page; redirect duplicates)",
        INDEX_ENGINES, scope_for(urls), {"pages": rows[:40], "from": rows[0]["from"], "to": rows[0]["to"]},
        f"every address on {old_host} redirects permanently to the same address on {new_host}",
        TWIN_SERVED_FIX.format(old=old_host, new=new_host),
        notes=["Most addresses on this host redirect; these answered with the page instead, so the same page has two "
               "addresses. In this saved audit both copies were read; a new crawl reads each page once."])
    finding.launch_gated = items_of("IDX-4", finding)[0]
    record = to_jsonable(finding)
    check.setdefault("findings", []).append(record)
    if check.get("status") == "pass":
        check["status"] = "findings"
    affected[record["id"]] = urls
    changes.append(f"{record['id']}: {record['title']} (S3; DECISIONS 359)")


def _shrink(check: dict, f: dict, drop: set[str], affected: dict, changes: list[str], why: str,
            ref: str = "DECISIONS 360") -> None:
    """Take `drop` out of a page finding's addresses (scope, affected list, evidence page lists) and say so; the finding
    goes when no address is left. The count in its title follows (its first number)."""
    urls = [u for u in affected.get(f.get("id")) or (f.get("scope") or {}).get("urls") or [] if u not in drop]
    if len(urls) == len(affected.get(f.get("id")) or (f.get("scope") or {}).get("urls") or []):
        return
    if not urls:
        check["findings"].remove(f)
        affected.pop(f.get("id"), None)
        changes.append(f"{f.get('id')}: removed, {why} ({ref})")
        if not check["findings"] and check.get("status") == "findings":
            check["status"] = "pass"
        return
    old = f.get("title") or ""
    f["title"] = re.sub(r"^\d+", str(len(urls)), old, count=1)
    f["scope"] = {**(f.get("scope") or {}), "urls": urls[:25], "count": len(urls)}
    ev = f.get("evidence") or {}
    for key in ("pages", "facts"):
        if isinstance(ev.get(key), list):
            ev[key] = [x for x in ev[key] if (x.get("url") if isinstance(x, dict) else x) not in drop]
    affected[f["id"]] = urls
    changes.append(f"{f.get('id')}: {old} -> {f['title']} ({why}; {ref})")


def _decisions_360(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 360 (İlginay's review of the MMI Ek), on a saved report's records: (1) no "no <title>" or "no meta
    description" for a page whose own copy has one (the reader's copy may lack it) or prints it in the body after a
    <head> that closed normally; (2) an only-hidden <h1> is reported only when the record says how it is hidden (from the
    rendered page's computed style; saved raw records do not say, so they are not reported); (3) a brand name given only by
    page titles that holds the main name with the page's subject is not another name; (4) a link target whose canonical
    names a page with different content is not an alias (IDX-4's card says its canonical is wrong); (5) each page's step
    in a link card names its links."""
    from .link_fixes import alias_fixes, no_text_fixes
    crawl = report.get("crawl") or {}
    pages = {p.get("url"): p for p in crawl.get("pages") or [] if isinstance(p, dict)}
    render = ((crawl.get("render") or {}).get("pages") or {}) if isinstance(crawl.get("render"), dict) else {}

    def has(url: str, what: str) -> bool:
        a = (pages.get(url) or {}).get("analysis") or {}
        out = a.get("outside_head") or {}
        normal = not out.get("closed_early_by")
        if what == "title":
            rendered = (((render.get(url) or {}).get("rendered") or {}) if isinstance(render.get(url), dict) else {}).get("title")
            return bool(a.get("title") or (normal and out.get("title")) or rendered)
        return bool(any(m.get("name") == "description" and m.get("content") for m in a.get("meta") or [])
                    or (normal and "description" in (out.get("meta") or [])))
    different = set()
    for check in report.get("checks") or []:
        for f in list(check.get("findings") or []):
            rule, ev = f.get("rule_id"), f.get("evidence") or {}
            urls = affected.get(f.get("id")) or (f.get("scope") or {}).get("urls") or []
            if rule == "str1.no_title":
                _shrink(check, f, {u for u in urls if has(u, "title")}, affected, changes, "the page has a <title>")
            elif rule == "str10.no_description":
                _shrink(check, f, {u for u in urls if has(u, "description")}, affected, changes, "the page has a meta description")
            elif rule == "str2.hidden_h1":
                said = [r for r in ev.get("pages") or [] if isinstance(r, dict) and "computed style" in str(r.get("hidden_by") or "")]
                keep = {r["url"] for r in said}
                _shrink(check, f, {u for u in urls if u not in keep}, affected, changes,
                        "the record does not say how the <h1> is hidden (aria-hidden or a script's wrapper is not hidden)")
            elif rule == "idx4.different":
                different |= {(r.get("url"), r.get("canonical")) for r in ev.get("pages") or [] if isinstance(r, dict)}
    for check in report.get("checks") or []:
        for f in list(check.get("findings") or []):
            rule, ev = f.get("rule_id"), f.get("evidence") or {}
            if rule == "str5.names" and isinstance(ev.get("variants"), list) and ev["variants"]:
                main = max(ev["variants"], key=lambda v: v.get("pages") or 0)
                key = str(main.get("normalized") or "")
                subjects = [v for v in ev["variants"] if v is not main and f" {key} " in f" {v.get('normalized') or ''} "
                            and set((v.get("by_source") or {})) <= {"title suffix/prefix"}]
                if key and subjects:
                    ev["variants"] = [v for v in ev["variants"] if v not in subjects]
                    ev["category_titles_not_counted"] = [*(ev.get("category_titles_not_counted") or []), *(v.get("name") for v in subjects)]
                    if len(ev["variants"]) <= 2:
                        check["findings"].remove(f)
                        affected.pop(f.get("id"), None)
                        changes.append(f"{f.get('id')}: removed, the other names were page subjects before the brand (DECISIONS 360)")
                    else:
                        old = f["title"]
                        f["title"] = f"The brand is named {len(ev['variants'])} different ways"
                        changes.append(f"{f.get('id')}: {old} -> {f['title']} (DECISIONS 360)")
            elif rule == "idx6.alias_links":
                targets = [t for t in ev.get("targets") or [] if isinstance(t, dict)]
                wrong = [t for t in targets if (t.get("url"), t.get("canonical")) in different]
                left = [t for t in targets if t not in wrong]
                if wrong and not left:
                    check["findings"].remove(f)
                    affected.pop(f.get("id"), None)
                    changes.append(f"{f.get('id')}: removed, its target's canonical names a page with other content "
                                   "(IDX-4's card) (DECISIONS 360)")
                    continue
                ev["targets"] = left
                aliases = {t["url"]: t["canonical"] for t in left if t.get("url") and t.get("canonical")}
                if aliases and not ev.get("page_fixes"):
                    ev["page_fixes"] = alias_fixes(pages.values(), aliases)[:500]
            elif rule in ("prf1.slow", "prf1.timeouts") and "pages_measured" not in ev:
                measured = len(((crawl.get("perf") or {}).get("sample")) or [])
                if measured:  # DECISIONS 360 (6): the card says how many pages the timing sample measured
                    ev["pages_measured"] = measured
            elif rule == "str14.no_text" and not ev.get("page_fixes"):
                ev["page_fixes"] = no_text_fixes([r for r in ev.get("links") or [] if isinstance(r, dict)])[:500]


def _decisions_363(report: dict, affected: dict, changes: list[str], jsonld_by_url: dict | None = None) -> None:
    """DECISIONS 363 (the SEO team's gaps on enpara), on a saved report: the notes for a sitemap with no <lastmod>
    (IDX-5), llms.txt served without a charset (ACC-8; a byte-order mark only in a new crawl), an <h1> question no
    section answers (STR-2), and articles that name only an organization as author (STR-3, from the saved JSON-LD).
    A note already in the report is not added again."""
    from .checks.access import llms_encoding
    from .checks.index import sitemap_without_lastmod
    from .checks.quick_rules import ORG_AUTHOR_EXPECTED, ORG_AUTHOR_FIX, ORG_AUTHOR_NOTE
    from .checks.structure import H1_PROMISE, h1_promise
    from .findings import Finding, Severity, scope_for
    from .launch_gate import items_of
    from .models import Confidence, to_jsonable
    crawl = report.get("crawl") or {}
    checks = {c.get("check_id"): c for c in report.get("checks") or []}

    def observe(cid: str, obs: dict | None) -> None:
        check = checks.get(cid)
        if not obs or check is None or check.get("status") == "not_assessed":
            return
        if any(o.get("metric") == obs["metric"] for o in check.get("observations") or []):
            return
        check.setdefault("observations", []).append(obs)
        changes.append(f"{cid}: note added: {obs['metric']} (DECISIONS 363)")
    observe("IDX-5", sitemap_without_lastmod(crawl.get("sitemap_docs")))
    observe("ACC-8", llms_encoding((crawl.get("access") or {}).get("llms")))
    pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict) and isinstance(p.get("analysis"), dict)]
    promised = [{"url": p["url"], "h1": h, "unanswered": left} for p in pages for h, left in [h1_promise(p["analysis"])] if left]
    if promised:
        observe("STR-2", {"metric": H1_PROMISE, "pages": len(promised), "examples": promised[:100]})
    check = checks.get("STR-3")
    if not jsonld_by_url or check is None or check.get("status") == "not_assessed" or any(
            f.get("rule_id") == "str3.article_org_author" for f in check.get("findings") or []):
        return
    import json as _json
    from .analysis import jsonld_author_kind
    org_only = []
    for p in pages:
        if (p.get("grouping") or {}).get("page_type") != "blog_article" or not jsonld_by_url.get(p["url"]):
            continue
        signals = set(p["analysis"].get("author_signals") or []) - {"JSON-LD author", "JSON-LD author (organization)"}
        values = []
        for block in jsonld_by_url[p["url"]]:
            try:
                values.append(_json.loads(block, strict=False))
            except ValueError:
                continue
        if not signals and jsonld_author_kind([{"data": v} for v in values]) == "organization" and not any(
                m.get("name") == "author" and m.get("content") for m in p["analysis"].get("meta") or []):
            org_only.append(p["url"])
    if not org_only:
        return
    finding = Finding("STR-3", f"{len(org_only)} article page(s) name only an organization as author", Severity.S4,
                      Confidence.ESTIMATED, "Documented (Google: author markup best practices)",
                      ["Google AI Overviews / AI Mode", "Microsoft Copilot (Bing index)"], scope_for(org_only),
                      {"organization_only": len(org_only), "pages": org_only[:40],
                       "rule": "an indexable article page whose structured data names only organizations as author"},
                      ORG_AUTHOR_EXPECTED, ORG_AUTHOR_FIX, notes=[ORG_AUTHOR_NOTE])
    finding.launch_gated = items_of("STR-3", finding)[0]
    record = to_jsonable(finding)
    check.setdefault("findings", []).append(record)
    if check.get("status") == "pass":
        check["status"] = "findings"
    affected[record["id"]] = org_only
    changes.append(f"{record['id']}: {record['title']} (S4; DECISIONS 363)")


def _decisions_364(report: dict, affected: dict, changes: list[str], jsonld_by_url: dict | None = None) -> None:
    """DECISIONS 364: image and file names with a space, a combining mark, brackets or commas (tseo1.file_name_unsafe), on
    a saved report: from each page's img src, og:image, file links and preloads, the image sample, and the Product images
    of the saved JSON-LD. A finding already there is replaced when the saved JSON-LD adds Product images to it."""
    import json as _json
    from .checks.quick_rules import _read, unsafe_file_names
    from .checks.stage8_rules import _images
    from .file_names import product_images
    from .launch_gate import items_of
    from .models import page_from_record, to_jsonable
    crawl = report.get("crawl") or {}
    check = next((c for c in report.get("checks") or [] if c.get("check_id") == "TSEO-1"), None)
    if check is None or check.get("status") == "not_assessed":
        return
    old = [f for f in check.get("findings") or [] if f.get("rule_id") == "tseo1.file_name_unsafe"]
    products: dict[str, list[str]] = {}
    for url, blocks in (jsonld_by_url or {}).items():
        values = []
        for block in blocks or []:
            try:
                values.append(_json.loads(block, strict=False))
            except ValueError:
                continue
        if found := product_images(values):
            products[url] = found
    if old and not products:
        return
    read = _read([page_from_record(p) for p in crawl.get("pages") or [] if isinstance(p, dict)])
    made = unsafe_file_names([(p.url, p.analysis) for p in read], _images(crawl.get("structure")), products)
    if not made or (old and old[0].get("title") == to_jsonable(made[0]).get("title")
                    and old[0].get("evidence", {}).get("files") == to_jsonable(made[0])["evidence"]["files"]):
        return
    for f in old:
        check["findings"].remove(f)
        affected.pop(f.get("id"), None)
    finding = made[0]
    finding.launch_gated = items_of("TSEO-1", finding)[0]
    record = to_jsonable(finding)
    check.setdefault("findings", []).append(record)
    if check.get("status") == "pass":
        check["status"] = "findings"
    affected[record["id"]] = list(finding.scope.get("_all_urls") or finding.scope.get("urls") or [])
    changes.append(f"{record['id']}: {record['title']} (S4; DECISIONS 364)")


def _add_finding(report: dict, affected: dict, check_id: str, finding, urls: list[str], changes: list[str], why: str) -> None:
    from .launch_gate import items_of
    from .models import to_jsonable
    check = next((c for c in report.get("checks") or [] if c.get("check_id") == check_id), None)
    if check is None:
        return
    finding.launch_gated = items_of(check_id, finding)[0]
    record = to_jsonable(finding)
    check.setdefault("findings", []).append(record)
    if check.get("status") == "pass":
        check["status"] = "findings"
    affected[record["id"]] = list(urls)
    changes.append(f"{record['id']}: {record['title']} ({why}; DECISIONS 368)")


def _decisions_368(report: dict, affected: dict, changes: list[str], saved_texts: list[str] | None = None) -> None:
    """DECISIONS 368: İlginay's review of the MMI Ek's "Diğer bulgular", on a saved report.

    (1) "The homepage has N visible section headings" goes when the homepage has as many <h2>/<h3> as the rule asks,
    hidden ones counted, in any saved reading; when most of its <h2> are product card names, that is said instead
    (str2.card_headings). (2) Section headings in another language are judged again against the page's own language
    (declared, and its text's) with the English question words. (3) A canonical to a page with different content is
    kept only when every saved reading (raw HTML, the browser's, the page reader's) agrees and one is final; readings
    that differ become idx4.versions_differ. (4) Each page's own line on the findings that said only a count."""
    import json as _json
    from collections import defaultdict
    from types import SimpleNamespace
    from urllib.parse import urlsplit
    from .checks.index import VERSIONS_DIFFER_FIX, VERSIONS_DIFFER_TITLE, canonical_readings
    from .checks.structure import card_headings_finding
    from .config import MIN_FOREIGN_HEADINGS
    from .example_rows import attach, headings_language
    from .findings import Finding, Severity, scope_for
    from .language import NAMES, detect_language, heading_language
    from .models import Confidence
    saved: dict[str, list[dict]] = {}
    for raw in saved_texts or []:
        try:
            rec = _json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("url"), str):
            saved.setdefault(rec["url"], []).append(rec)
    crawl = report.get("crawl") or {}
    pages = {p.get("url"): p for p in crawl.get("pages") or [] if isinstance(p, dict)}
    checks = {c.get("check_id"): c for c in report.get("checks") or [] if isinstance(c, dict)}

    def count(headings) -> int:
        return sum(1 for h in headings or [] if isinstance(h, dict) and h.get("level") in (2, 3) and str(h.get("text") or "").strip())

    # (1) the homepage's outline
    check = checks.get("STR-2")
    home = next((p["url"] for p in pages.values() if p.get("depth") == 0 and 200 <= (p.get("status") or 0) < 300), None)
    if check is not None and check.get("status") != "not_assessed":
        for f in [f for f in check.get("findings") or [] if f.get("rule_id") == "str2.home_outline"]:
            ev = f.get("evidence") or {}
            url = ((ev.get("pages") or [{}])[0] or {}).get("url") or home
            readings = [((pages.get(url) or {}).get("analysis") or {}).get("headings")] + [r.get("headings") for r in saved.get(url, [])]
            most = max(count(h) for h in readings)
            if most >= (ev.get("minimum_subheadings") or 3):
                check["findings"].remove(f)
                affected.pop(f.get("id"), None)
                changes.append(f"{f.get('id')}: removed, the homepage has {most} <h2>/<h3> headings, hidden ones counted (DECISIONS 368)")
        if home and not any(f.get("rule_id") == "str2.card_headings" for f in check.get("findings") or []):
            rec = next((r for r in saved.get(home, []) if r.get("headings") and r.get("main_text")), None)
            made = card_headings_finding(home, rec["headings"], rec["main_text"].split("\n"), set()) if rec else None
            if made is not None:
                _add_finding(report, affected, "STR-2", made, [home], changes, "product card names as <h2>")
        if not check.get("findings") and check.get("status") == "findings":
            check["status"] = "pass"

    # (2) headings in another language than the page's own
    check = checks.get("STR-12")
    for f in [f for f in (check or {}).get("findings") or [] if f.get("rule_id") == "str12.headings"]:
        ev = f.get("evidence") or {}
        kept, drop = [], set()
        for row in ev.get("pages") or []:
            if not isinstance(row, dict):
                continue
            declared = row.get("declared")
            text = next((r.get("main_text") for r in saved.get(row.get("url"), []) if r.get("main_text")), None)
            detected = detect_language(text, declared=declared).get("language") if text else row.get("detected")
            by_language: dict[str, list[str]] = defaultdict(list)
            for heading in dict.fromkeys(row.get("headings") or []):  # DECISIONS 371: a repeated heading counts once
                language = heading_language(heading, declared=declared)
                if language and language not in (declared, detected):
                    by_language[language].append(heading)
            odd = max(by_language.items(), key=lambda kv: len(kv[1]), default=(None, []))
            if len(odd[1]) >= MIN_FOREIGN_HEADINGS:
                row.update(headings_language=odd[0], headings=odd[1], headings_count=len(odd[1]), detected=detected,
                           row=headings_language(declared, detected, odd[0], odd[1]))
                kept.append(row)
            else:
                drop.add(row.get("url"))
        if drop:
            _shrink(check, f, drop, affected, changes, "the headings are in the page's own language", "DECISIONS 368")
        if kept and f in check.get("findings", []):
            pairs = sorted({(r["declared"], r["headings_language"]) for r in kept})
            label = "; ".join(f"declared {NAMES.get(d, d)}, headings in {NAMES.get(m, m)}" for d, m in pairs)
            f["title"] = f"{len(kept)} page(s) have section headings in another language than they declare ({label})"
            ev["pages"] = kept
    if check is not None and not check.get("findings") and check.get("status") == "findings":
        check["status"] = "pass"

    # (3) a canonical to a page with different content, from every saved reading
    check = checks.get("IDX-4")
    read_by_reader = {p.get("url") for p in (report.get("firecrawl") or {}).get("pages") or []
                      if isinstance(p, dict) and p.get("outcome") == "read"}
    firecrawl = {}
    for url, recs in saved.items():
        own_at = (pages.get(url) or {}).get("requested_at")
        other = [r for r in recs if r.get("requested_at") != own_at]
        if url in read_by_reader and other:
            firecrawl[url] = {"canonicals": other[0].get("canonicals") or [], "read_at": other[0].get("requested_at")}
    for f in [f for f in (check or {}).get("findings") or [] if f.get("rule_id") == "idx4.different"]:
        ev = f.get("evidence") or {}
        rows = [r for r in ev.get("pages") or [] if isinstance(r, dict) and r.get("url")]
        unassessed: list[dict] = []
        raw = {r["url"]: list(((pages.get(r["url"]) or {}).get("analysis") or {}).get("canonicals") or []) or [r.get("canonical")]
               for r in rows}
        kept, differ = canonical_readings(rows, SimpleNamespace(pages=[], render=crawl.get("render") or {}), unassessed,
                                          firecrawl, raw)
        ev["pages"] = kept + [r for r in rows if r["url"] not in {x["url"] for x in kept + differ + unassessed}]
        drop = {r["url"] for r in differ + unassessed}
        if unassessed:
            (check.setdefault("evidence", {}).setdefault("not_assessed", [])).extend(
                {k: v for k, v in r.items() if k in ("url", "canonical", "versions", "reason")} for r in unassessed)
        if drop:
            _shrink(check, f, drop, affected, changes, "the saved readings of the canonical disagree or none is final",
                    "DECISIONS 368")
        if differ:
            urls = [r["url"] for r in differ]
            made = Finding("IDX-4", VERSIONS_DIFFER_TITLE.format(n=len(urls)), Severity.S3, Confidence.VERIFIED,
                           "Documented (Google: rel=canonical is read from the rendered page too)",
                           f.get("engines") or [], scope_for(urls), {"pages": differ[:40]},
                           "the same canonical in the raw HTML and in the rendered page", VERSIONS_DIFFER_FIX,
                           notes=["Each reading is listed with its date; a browser reading taken before the page "
                                  "finished loading is marked so."])
            _add_finding(report, affected, "IDX-4", made, urls, changes, "raw and rendered canonicals differ")
    if check is not None and not check.get("findings") and check.get("status") == "findings":
        check["status"] = "pass"

    # (4) each page's own line
    for fid in attach(report):
        changes.append(f"{fid}: each page's own line added (which text, element and place; DECISIONS 368)")


def _decisions_370(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 370: an ACC-6 finding (a vendor's bots blocked on some sampled addresses) is attached only to the
    addresses its robots.txt rule blocks, read from the saved ACC-2 decisions (address, bot, rule), each with its line,
    and carries one site-wide line; when the saved decisions do not name the addresses, once, to robots.txt itself."""
    from .example_rows import robots_pages, robots_site_row
    from .findings import scope_for
    decisions = [d for c in report.get("checks") or [] if c.get("check_id") == "ACC-2"
                 for f in c.get("findings") or [] for d in (f.get("evidence") or {}).get("decisions") or []]
    robots_url = next((r.get("url") for r in (report.get("crawl") or {}).get("robots") or [] if isinstance(r, dict)), None)
    for check in report.get("checks") or []:
        if check.get("check_id") != "ACC-6":
            continue
        for f in check.get("findings") or []:
            ev = f.setdefault("evidence", {})
            if f.get("rule_id") != "acc6.scope" or ev.get("site_row"):
                continue
            tokens = list(ev.get("blocked_tokens") or [])
            sample = int(ev.get("sample_size") or 0)
            pages = robots_pages(decisions, tokens)
            if pages:
                reasons = list(dict.fromkeys(r for p in pages for r in p["reasons"]))
                urls = [p["url"] for p in pages]
                ev.update(pages=pages, blocked_urls=len(pages),
                          site_row=robots_site_row(reasons, len(pages), max(sample, len(pages)), tokens))
            else:
                counts = re.search(r"\((\d+)/(\d+) sampled URLs\)", f.get("title") or "")
                blocked = int(counts.group(1)) if counts else sample
                urls = [robots_url] if robots_url else []
                ev.update(blocked_urls=blocked, site_row=robots_site_row([], blocked, max(sample, blocked), tokens))
            before = len(affected.get(f.get("id")) or (f.get("scope") or {}).get("urls") or [])
            f["scope"] = scope_for(urls, sitewide=bool(sample) and len(urls) == sample)
            affected[f["id"]] = urls
            changes.append(f"{f['id']}: {before} -> {len(urls)} address(es), only where robots.txt blocks "
                           f"{', '.join(tokens)} (DECISIONS 370)")


def _decisions_371(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 371: İlginay's review of the Nature's Garden Ek, on a saved report. An <h1> said hidden by the rendered
    page's computed style is kept only when the saved reading says no screen reader reads it either (older readings do
    not say: not established); a collection is "no products" only with 0 in its HTML and 0 in the rendered page; account,
    sign-in and cart pages leave the content findings (RND-1, RND-3)."""
    from .checks.quick_rules import empty_row, rendered_products
    from .page_groups import is_utility_address
    crawl = report.get("crawl") or {}
    render = (crawl.get("render") or {}).get("pages") or {}
    types = {p.get("url"): (p.get("grouping") or {}).get("page_type") for p in crawl.get("pages") or [] if isinstance(p, dict)}
    for check in report.get("checks") or []:
        for f in list(check.get("findings") or []):
            rule, ev = f.get("rule_id"), f.get("evidence") or {}
            urls = affected.get(f.get("id")) or (f.get("scope") or {}).get("urls") or []
            if rule in ("str2.hidden_h1", "str2.home_hidden_h1"):
                drop = set()
                for row in ev.get("pages") or []:
                    if not isinstance(row, dict) or "computed style" not in str(row.get("hidden_by") or ""):
                        continue
                    seen = (render.get(row.get("url")) or {}).get("h1_visibility") or []
                    if not any(isinstance(v, dict) and v.get("accessible") is False for v in seen):
                        drop.add(row.get("url"))
                if drop:
                    _shrink(check, f, drop, affected, changes,
                            "the saved reading does not say whether a screen reader reads the <h1>", "DECISIONS 371")
            elif rule == "str15.empty_collections":
                drop = set()
                for row in ev.get("pages") or []:
                    if not isinstance(row, dict):
                        continue
                    after_js = rendered_products(render.get(row.get("url")), types)
                    if int(row.get("products_listed") or 0) > 0 or after_js:
                        drop.add(row.get("url"))
                    else:
                        row.update(empty=True, rendered_products=after_js, row=empty_row(after_js))
                if drop:
                    _shrink(check, f, drop, affected, changes,
                            "the page lists products (in its HTML or after its scripts run)", "DECISIONS 371")
                if f in check.get("findings", []):
                    ev.update(empty=len(ev.get("pages") or []), near_empty=0)
            elif str(rule or "").startswith(("rnd1.", "rnd3.")):
                drop = {u for u in urls if isinstance(u, str) and is_utility_address(u)}
                if drop:
                    _shrink(check, f, drop, affected, changes, "an account, sign-in or cart page is not content",
                            "DECISIONS 371")
        if not check.get("findings") and check.get("status") == "findings":
            check["status"] = "pass"


def _decisions_373(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 373 (Efsa's review, İlginay's notes): on a saved report, "long pages have no subheadings" is kept only for
    pages whose reading counted styled section titles (an older reading did not: it cannot tell "no titles" from "titles
    styled as text", the Enpara note's case); a collection with no product in its HTML that was not rendered is a coverage
    gap of STR-15, not "no products"."""
    from .coverage import part
    for check in report.get("checks") or []:
        for f in list(check.get("findings") or []):
            rule, ev = f.get("rule_id"), f.get("evidence") or {}
            if rule == "str2.no_subheadings":
                drop = {r.get("url") for r in ev.get("pages") or [] if isinstance(r, dict) and "styled_headings" not in r}
                if drop:
                    _shrink(check, f, drop, affected, changes,
                            "the saved reading did not count styled section titles, so 'no subheadings' is not established",
                            "DECISIONS 373")
            elif rule == "str15.empty_collections":
                drop = [r.get("url") for r in ev.get("pages") or [] if isinstance(r, dict) and r.get("rendered_products") is None]
                if drop:
                    check.setdefault("evidence", {})["collections_not_rendered"] = drop
                    gap = part("collection pages with no product in their HTML",
                               "the page was not opened in a browser, so whether its products load by script is unknown",
                               len(drop), False)
                    check.setdefault("coverage", {}).setdefault("not_assessed", []).append(gap)
                    _shrink(check, f, set(drop), affected, changes,
                            "not rendered: whether its products load by script is unknown (coverage)", "DECISIONS 373")
        if not check.get("findings") and check.get("status") == "findings":
            check["status"] = "pass"


def _decisions_379(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 379 (owner, the Ticimax Ek): a file whose folder name holds the space or the combining mark was written
    «dosya adı «offer.svg» (boşluk); önerilen ad: offer.svg». Each such file of a saved tseo1.file_name_unsafe finding is
    given its folder (from the address it keeps) and its page rows name the folder instead. A file the page wrote with
    whitespace inside "https://" ("https: //host/offer.svg", read from the page's own file_names) is a mistyped address:
    its rows say so with the address as meant. Applied once: a file that already says whether its folder is the problem
    is left as it is."""
    from .checks.quick_rules import FILE_NAME_WORDS, file_name_row
    from .file_names import absolute, folder_problem, mistyped_scheme, plain_name
    written: dict[str, str] = {}  # the resolved address a saved file keeps -> the mistyped address the page wrote
    for page in (report.get("crawl") or {}).get("pages") or []:
        for ref in ((page or {}).get("analysis") or {}).get("file_names") or []:
            url = (ref or {}).get("url") if isinstance(ref, dict) else None
            if url and mistyped_scheme(url) and page.get("url"):
                written[absolute(url, page["url"])] = url.strip()
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            if f.get("rule_id") != "tseo1.file_name_unsafe":
                continue
            ev = f.get("evidence") or {}
            fixed = []
            for rec in ev.get("files") or []:
                if not isinstance(rec, dict) or "folder" in rec or not rec.get("file"):
                    continue
                address = rec.get("address") or ""
                meant = mistyped_scheme(written[address]) if address in written else None
                found = None if meant else folder_problem(address)
                old = {lang: W["row"].format(f=rec["file"], p=", ".join(W[k] for k in rec.get("problems") or []),
                                             s=rec.get("plain_name") or "") for lang, W in FILE_NAME_WORDS.items()}
                rec.update({"folder": found[0] if found else None, "folder_problems": found[1] if found else [],
                            "folder_plain": plain_name(found[0], extension=False) if found else None,
                            "mistyped": {"written": written[address][:200], "address": meant} if meant else None})
                if found or meant:
                    fixed.append((rec, old))
            for rec, old in fixed:
                for row in ev.get("pages") or []:
                    text = (row or {}).get("row") or {}
                    for lang in FILE_NAME_WORDS:
                        if old[lang] in (text.get(lang) or ""):
                            text[lang] = text[lang].replace(old[lang], file_name_row(rec, lang))
            if fixed:
                changes.append(f"{f.get('id')}: {len(fixed)} file(s) with a mistyped address or a folder name that "
                               "holds the problem say so (DECISIONS 379)")


def _decisions_374(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 374 (the owner, MMI Ek): a slow-page finding keeps only pages over its threshold on the value it is
    judged on (the median); a robots tag outside <head> names the tag, where it sits and why, and is not reported where
    Maya's Googlebot request got it in <head> (a saved report from before this has no such request: said so)."""
    from .example_rows import googlebot_heads, robots_outside, timing_metric, timing_threshold, timing_value
    crawl = report.get("crawl") or {}
    pages = {p.get("url"): p for p in crawl.get("pages") or [] if isinstance(p, dict)}
    platform = (report.get("platform") or {}).get("name") if isinstance(report.get("platform"), dict) else None
    bots = googlebot_heads((crawl.get("access") or {}).get("ua_check"))
    for check in report.get("checks") or []:
        for f in list(check.get("findings") or []):
            rule, ev = f.get("rule_id"), f.get("evidence") or {}
            if rule == "prf1.slow":
                metric, threshold = timing_metric(f), timing_threshold(f)
                if threshold is None:
                    continue
                drop = {r.get("url") for r in ev.get("pages") or [] if isinstance(r, dict) and r.get("samples") is not None
                        and (timing_value(r, metric) or 0) <= threshold}
                if drop:
                    _shrink(check, f, drop, affected, changes, "the page's judged median is not over the threshold",
                            "DECISIONS 374")
            elif rule == "acc3.robots_outside_head" and not ev.get("pages"):
                urls = list((ev.get("robots_tags_outside_head") or {}).keys())
                records = [robots_outside(u, ((pages.get(u) or {}).get("analysis") or {}), platform, bots.get(u)) for u in urls]
                streamed_fine = any(r["cause"] == "streamed" and r["googlebot_in_head"] for r in records)
                drop = {r["url"] for r in records if r["googlebot_in_head"] or (streamed_fine and r["cause"] == "streamed")}
                ev["pages"] = [r for r in records if r["url"] not in drop][:40]
                if drop:
                    _shrink(check, f, drop, affected, changes, "Googlebot gets the tag in <head>", "DECISIONS 374")
        if not check.get("findings") and check.get("status") == "findings":
            check["status"] = "pass"


def _decisions_365(report: dict, changes: list[str]) -> None:
    """DECISIONS 365: the platform worked out again from the saved pages with the current signals (images, the generator
    tag, X-Powered-By, footer credits) and its confidence; a report whose pages show none keeps what it had (DECISIONS
    309's saved-data signals, "medium")."""
    from types import SimpleNamespace
    from .models import page_from_record
    from .site_platform import recognise
    old = report.get("platform") if isinstance(report.get("platform"), dict) else {}
    pages = [page_from_record(p) for p in (report.get("crawl") or {}).get("pages") or []
             if isinstance(p, dict) and isinstance(p.get("analysis"), dict)]
    try:
        found = recognise(SimpleNamespace(pages=pages)) if pages else None
    except Exception:  # noqa: BLE001  a hint only: keep the saved one
        found = None
    if found and found.get("name"):
        new = {**found, "cdn": found.get("cdn") or old.get("cdn")}
        if new.get("cdn") and not found.get("cdn"):
            new["signals"] = list(found.get("signals") or []) + [s for s in old.get("signals") or [] if s.startswith(new["cdn"])]
        if (old.get("name"), old.get("confidence")) != (new["name"], new["confidence"]):
            report["platform"] = new
            changes.append(f"platform: {old.get('name') or 'none'} -> {new['name']} ({new['confidence']}; DECISIONS 365)")


def _decisions_351(report: dict, changes: list[str]) -> None:
    """DECISIONS 351: a saved `idx6.alias_links` finding gives Shopify's step only on a Shopify site."""
    from .checks.quick_rules import ALIAS_LINKS_FIX_SHOPIFY, alias_fix
    platform = (report.get("platform") or {}).get("name") if isinstance(report.get("platform"), dict) else None
    if not platform:
        try:
            from .site_platform import recognise_saved
            platform = (recognise_saved(report) or {}).get("name")
        except Exception:  # noqa: BLE001  a hint only
            platform = None
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            if f.get("rule_id") != "idx6.alias_links" or f.get("how_to_fix") != ALIAS_LINKS_FIX_SHOPIFY:
                continue
            new = alias_fix(platform, [t.get("url") for t in (f.get("evidence") or {}).get("targets") or [] if t.get("url")])
            if new != f["how_to_fix"]:
                f["how_to_fix"] = new
                changes.append(f"{f.get('id')}: the general fix, not Shopify's (platform: {platform or 'not recognised'}) "
                               "(DECISIONS 351)")


def _decisions_350(report: dict, changes: list[str]) -> None:
    """DECISIONS 350: a saved `idx6.alias_links` finding names the link a template puts on most of its pages (its text,
    place and canonical), from the saved page records. (`idx6.links_to_redirect` is made again by DECISIONS 343.)"""
    from .checks.stage8_rules import TEMPLATE_LINK_SHARE, template_link
    from .models import page_from_record
    pages = None
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            ev = f.get("evidence") or {}
            if f.get("rule_id") != "idx6.alias_links" or ev.get("template_link") or not ev.get("targets"):
                continue
            top, count = ev["targets"][0], ev.get("page_count") or 0
            if (top.get("linked_from_pages") or 0) < TEMPLATE_LINK_SHARE * count or count < 5:
                continue
            if pages is None:
                pages = []
                for rec in (report.get("crawl") or {}).get("pages") or []:
                    try:
                        pages.append(page_from_record(rec))
                    except (KeyError, TypeError, ValueError):
                        continue
            shared = template_link(pages, top["url"], {p.url for p in pages}, top.get("canonical"), "canonical")
            if shared and shared.get("pages"):
                ev["template_link"] = shared
                changes.append(f"{f.get('id')}: the template link named ({shared.get('where')}, {top['url']}) (DECISIONS 350)")


def _decisions_349(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 349 (naturesgarden.net 342a0b14, whose appendix and sector file were refused by RG-7): (1) a page in a
    blog or article folder that an STR-3 finding took for a product by its price and buy button alone is not one: the
    row goes, and a finding with no row left goes too; (2) a finding's page kinds take the kind its own evidence gave a
    page that only the page reader read (before: "unknown", which the release gate refuses content advice for)."""
    import re as _re
    from urllib.parse import unquote, urlsplit
    from .checks.structure import ARTICLE_FOLDERS, BLOG_FOLDERS, evidence_page_kinds
    from .page_words import fold
    folders = ARTICLE_FOLDERS | BLOG_FOLDERS

    def in_blog(url: str) -> bool:
        return bool({fold(unquote(x)) for x in urlsplit(url or "").path.split("/") if x} & folders)
    for check in report.get("checks") or []:
        for f in list(check.get("findings") or []):
            ev = f.get("evidence") or {}
            rows = ev.get("pages")
            if (f.get("rule_id") or "").startswith("str3.") and isinstance(rows, list):
                kept = [r for r in rows if not (isinstance(r, dict) and r.get("page_kind") == "product"
                                                and str(r.get("classified_by") or "").startswith("one price of its own")
                                                and in_blog(r.get("url") or ""))]
                if len(kept) != len(rows):
                    dropped = len(rows) - len(kept)
                    if not kept:
                        check["findings"].remove(f)
                        affected.pop(f.get("id"), None)
                        changes.append(f"{f.get('id')}: removed; its {dropped} page(s) are blog posts with a product "
                                       "widget, not product pages (DECISIONS 349)")
                        continue
                    old = f.get("id")
                    urls = [r["url"] for r in kept if isinstance(r, dict) and r.get("url")]
                    ev["pages"] = kept
                    f["title"] = _re.sub(r"^\d+", str(len(kept)), f.get("title") or "", count=1)
                    f["scope"] = {**(f.get("scope") or {}), "urls": urls, "count": len(urls)}
                    _refresh_id(f, affected, old, urls)
                    changes.append(f"{f['id']}: {dropped} blog post(s) with a product widget left out (DECISIONS 349)")
            judged = evidence_page_kinds(ev)
            kinds = f.get("page_types")
            if judged and isinstance(kinds, dict):
                filled = {u: judged[u] for u, k in kinds.items() if k == "unknown" and judged.get(u)}
                if filled:
                    f["page_types"] = {**kinds, **filled}
                    changes.append(f"{f.get('id')}: the kind of {len(filled)} page(s) read by the page reader taken "
                                   "from the finding's own evidence (DECISIONS 349)")
    from .checks.access import _status
    for check in report.get("checks") or []:
        check["status"] = _status(check.get("findings") or [], check.get("review_items") or ())


def _decisions_347(report: dict, changes: list[str]) -> None:
    """DECISIONS 347 (the review of atasunoptik): (1) the page grouping worked out again with the current method when
    the saved one is older (`page_groups.METHOD_VERSION`): a sitewide og:type is a site default, item addresses with an
    id are products, pages listing them categories, store pages "location", account and sign-in pages utility, the
    homepage first; (2) the ACC-2 findings' rule read again from their titles, so a block of training bots only is
    `acc2.training_block.*` (a policy choice, never P0 or P1). Offline, from the saved page records."""
    from types import SimpleNamespace
    from .models import page_from_record
    from .page_groups import METHOD_VERSION, annotate
    from .rules import rule_id
    crawl = report.get("crawl") or {}
    summary = crawl.get("page_grouping")
    if isinstance(summary, dict) and (summary.get("method_version") or 0) < METHOD_VERSION and not (
            isinstance(crawl.get("reader_page_grouping"), dict) and crawl["reader_page_grouping"].get("pages")):
        records = [rec for rec in crawl.get("pages") or [] if isinstance(rec, dict)]
        pages = []
        for rec in records:
            try:
                pages.append((rec, page_from_record(rec)))
            except (KeyError, TypeError, ValueError):
                pages = []
                break
        if pages:
            result = SimpleNamespace(pages=[pg for _, pg in pages], start_url=crawl.get("start_url") or "",
                                     origin=crawl.get("origin"), discovered_urls=crawl.get("discovered_urls") or [],
                                     sitemap_urls=crawl.get("sitemap_urls") or [], page_grouping=None)
            try:
                fresh = annotate(result)
            except Exception as exc:  # noqa: BLE001  the saved grouping stays, said so
                changes.append(f"page grouping not worked out again ({type(exc).__name__}); the saved one is used (DECISIONS 347)")
                fresh = None
            if fresh is not None:
                before = dict(summary.get("page_types") or {})
                for rec, pg in pages:
                    rec["grouping"] = pg.grouping
                crawl["page_grouping"] = {**fresh, **{k: summary[k] for k in ("business_type", "importance_source") if k in summary}}
                changes.append(f"page types worked out again (method {METHOD_VERSION}, DECISIONS 347): {before} -> "
                               f"{fresh.get('page_types')}")
    for check in report.get("checks") or []:
        if check.get("check_id") != "ACC-2":
            continue
        for f in check.get("findings") or []:
            new = rule_id("ACC-2", f.get("title") or "")
            if new and new != f.get("rule_id"):
                changes.append(f"{f.get('id')}: rule {f.get('rule_id')} -> {new} (DECISIONS 347)")
                f["rule_id"] = new


def _decisions_343(report: dict, affected: dict, changes: list[str], unassessed: list[dict] | None = None) -> None:
    """DECISIONS 343 and 344 (the SEO team's technical review, Efsa's enpara report; İlginay's review of its Ek): the rules
    of `checks.team_rules` and the links to a redirect (`stage8_rules.links_to_redirect`, split for application and
    sign-in steps), recomputed from the saved page records with the engine's own functions; a finding of these rules
    already in the report is replaced. Then the sitemap-errors card takes the redirects to an error page
    (`team_rules.settle`). For a report of the current schema too."""
    from types import SimpleNamespace
    from .checks import team_rules
    from .checks.access import _status
    from .checks.quick_rules import _read, grouping_of
    from .checks.stage8_rules import links_to_redirect
    from .launch_gate import items_of
    from .models import page_from_record, to_jsonable
    crawl = report.get("crawl") or {}
    pages = []
    for p in crawl.get("pages") or []:
        try:
            pages.append(page_from_record(p))
        except (KeyError, TypeError, ValueError):  # a record without a page's fields (a hand-made or very old report)
            continue
    if not pages:
        return
    result = SimpleNamespace(pages=pages, start_url=crawl.get("start_url") or "", origin=crawl.get("origin"),
                             discovered_urls=crawl.get("discovered_urls") or [], sitemap_urls=crawl.get("sitemap_urls") or [],
                             page_grouping=None, redirects=crawl.get("redirects"), index=crawl.get("index"))
    read = _read(pages)
    checks = {c.get("check_id"): c for c in report.get("checks") or [] if c.get("status") != "not_assessed"}
    replaced = set(team_rules.RULES) | {"str1.subpage_copies_parent", "str2.h1_parent_name", "idx6.links_to_redirect",
                                        "idx6.links_to_flow_redirect", "idx6.links_to_login_redirect",
                                        "idx6.links_to_entry_redirect"}
    before = {}
    for check in checks.values():
        for f in list(check.get("findings") or []):
            if f.get("rule_id") in replaced:
                before[f["rule_id"]] = f.get("title")
                check["findings"].remove(f)
                affected.pop(f.get("id"), None)
    made, missing = team_rules.findings(result, read, grouping_of(result) if read else {}, set(checks), saved=True)
    if "IDX-6" in checks:
        made["IDX-6"] = list(made.get("IDX-6") or []) + links_to_redirect(pages, read)
    if unassessed is not None:
        unassessed.extend(missing)
    for check_id, new in made.items():
        check = checks.get(check_id)
        if check is None or not new:
            continue
        for finding in new:
            finding.launch_gated = items_of(check_id, finding)[0]
            urls = list(finding.scope.get("_all_urls") or finding.scope.get("urls") or [])
            record = to_jsonable(finding)
            check.setdefault("findings", []).append(record)
            affected[record["id"]] = urls
            if before.get(record["rule_id"]) != record["title"]:
                changes.append(f"{record['id']}: {record['title']} ({record['severity']}; DECISIONS 343, 344)")
    # DECISIONS 344: the sitemap-errors card takes the redirects to an error page, with a 301 target per address
    if "IDX-1" in checks:
        team_rules.settle([checks["IDX-1"]], result)
        for f in checks["IDX-1"].get("findings") or []:
            if f.get("rule_id") == "idx1.4xx.sitemap_only" and (f.get("evidence") or {}).get("suggestions") is not None:
                if "suggestions" not in str(changes):
                    changes.append(f"{f['id']}: a status chain and a 301 target (or 410) per address (DECISIONS 344)")
            if f.get("rule_id") == "idx1.error_redirect":
                rows = [r for r in (f.get("evidence") or {}).get("pages") or [] if isinstance(r, dict)]
                urls = [r["url"] for r in rows if not r.get("probe")] or [r["url"] for r in rows]
                _refresh_id(f, affected, f.get("id"), urls)
                f["rule_id"] = "idx1.error_redirect"
        for f in checks["IDX-1"].get("findings") or []:
            affected.setdefault(f["id"], list((f.get("scope") or {}).get("urls") or []))
    for check in checks.values():
        check["status"] = _status(check.get("findings") or [], check.get("review_items") or ())


def _decisions_340(report: dict, affected: dict, changes: list[str]) -> None:
    """DECISIONS 340 (the SEO team's 2nd review, enpara fee70191): FAQPage is suggested only for a real question-and-
    answer block. A saved report kept no record of the blocks around a page's questions, so a page stays only when one
    of its headings names an FAQ ("Sıkça Sorulan Sorular", "SSS", "FAQ" ...); a page the engine already judged
    (`qa_container`) keeps its judgment. A finding with no page left goes."""
    from .checks.structure import FAQ_SECTION, QA_CONTAINER_NOTE
    from .findings import scope_for
    pages = {p.get("url"): p for p in (report.get("crawl") or {}).get("pages") or [] if isinstance(p, dict)}
    for check in report.get("checks") or []:
        for f in list(check.get("findings") or []):
            if f.get("rule_id") != "str3.qa_no_faqpage":
                continue
            rows = [r for r in (f.get("evidence") or {}).get("pages") or [] if isinstance(r, dict)]
            if rows and all("qa_container" in r for r in rows):
                continue
            kept = []
            for r in rows:
                if r.get("qa_container"):
                    kept.append(r)
                    continue
                heads = ((pages.get(r.get("url")) or {}).get("analysis") or {}).get("headings") or []
                if any(FAQ_SECTION.search(str(h.get("text") or "")) for h in heads if isinstance(h, dict)):
                    kept.append({**r, "qa_container": "faq_heading_on_page"})
            dropped = len(rows) - len(kept)
            if not dropped:
                continue
            old = f.get("id")
            if not kept:
                check["findings"].remove(f)
                affected.pop(old, None)
            else:
                urls = [r["url"] for r in kept]
                f.update(title=f"{len(urls)} page(s) show questions and answers but have no FAQPage structured data",
                         scope=scope_for(urls), evidence={**f["evidence"], "pages": kept})
                f["notes"] = [*(f.get("notes") or []), QA_CONTAINER_NOTE]
                _refresh_id(f, affected, old, urls)
            changes.append(f"STR-3: FAQPage no longer suggested on {dropped} page(s) whose questions are headings or "
                           "paragraphs in an ordinary section, not an FAQ block (DECISIONS 340)")

    # STR-5: an Organization or WebSite name that is the page's own <title> is not another name of the brand
    from .checks.structure import brand_key
    titles = {u: ((p.get("analysis") or {}).get("title") or "") for u, p in pages.items()}
    for check in report.get("checks") or []:
        for f in list(check.get("findings") or []):
            if f.get("rule_id") != "str5.names":
                continue
            ev = f.get("evidence") or {}
            variants = [v for v in ev.get("variants") or [] if isinstance(v, dict)]
            gone, kept = [], []
            for v in variants:
                seen = [x for x in v.get("seen_as") or [] if isinstance(x, dict)]
                title_like = [x for x in seen if x.get("source") in ("Organization name", "WebSite name")
                              and brand_key(x.get("value") or "") == brand_key(titles.get(x.get("url")) or "x\x00")]
                others = set(v.get("by_source") or {}) - {"Organization name", "WebSite name"}
                if seen and len(title_like) == len(seen) and not others:
                    gone += title_like
                else:
                    kept.append(v)
            if not gone:
                continue
            old = f.get("id")
            note = [{"value": x.get("value"), "source": x.get("source"), "url": x.get("url")} for x in gone][:20]
            if len(kept) <= 2:
                check["findings"].remove(f)
                affected.pop(old, None)
            else:
                main = ev.get("main_name")
                urls = sorted({x.get("url") for v in kept if v.get("name") != main for x in v.get("seen_as") or []
                               if isinstance(x, dict) and x.get("url")})
                f.update(title=f"The brand is named {len(kept)} different ways", scope={**scope_for(urls), "kind": "template"},
                         evidence={**ev, "variants": kept, "page_titles_not_counted": note})
                _refresh_id(f, affected, old, urls)
            changes.append(f"STR-5: {len(gone)} Organization/WebSite name(s) that are the page's own title not counted as "
                           f"names of the brand ({', '.join(sorted({str(x.get('value')) for x in gone}))}) (DECISIONS 340)")


def apply(report: dict, affected: dict | None = None, *, source_audit_id: str | None = None,
          jsonld_by_url: dict[str, list[str]] | None = None, saved_texts: list[str] | None = None,
          business: str | None = None) -> tuple[dict, dict, dict]:
    """(report, affected, record) for a copy of `report` with the changed rules applied. `record` lists every change
    and what could not be assessed offline; it is also written to `generation.analysis`. `jsonld_by_url`: each page's
    saved JSON-LD blocks (the audit's evidence copies), for the Product fields and authors (DECISIONS 304).
    `saved_texts`: the saved page copies as text, for the platform when the report names none (DECISIONS 309)."""
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
    _decisions_365(r, changes)  # DECISIONS 365: the platform from the saved pages with the current signals
    _decisions_309(r, changes, saved_texts or [])
    _decisions_315(r, changes)
    _decisions_316(r, aff, changes)
    _decisions_317(r, changes)
    _decisions_318(r, changes)
    _decisions_321(r, changes)
    _decisions_329(r, changes)
    _decisions_337(r, aff, changes)
    _decisions_338(r, aff, changes)
    _decisions_340(r, aff, changes)
    _decisions_347(r, changes)  # DECISIONS 347: page types again; training-only robots blocks their own rule
    _decisions_349(r, aff, changes)  # DECISIONS 349: blog posts with a product widget; reader pages' kinds
    _decisions_350(r, changes)  # DECISIONS 350: the alias-links card names its template link
    _decisions_351(r, changes)  # DECISIONS 351: Shopify's step only on a Shopify site
    _decisions_343(r, aff, changes, quick_unassessed)  # DECISIONS 343, 344: replaces what _decisions_304 added
    _decisions_356(r, aff, changes, saved_texts, business, quick_unassessed)  # DECISIONS 356: the profile's checks
    _decisions_359(r, aff, changes)  # DECISIONS 359: the twin address's copies are one card
    _decisions_360(r, aff, changes)  # DECISIONS 360: İlginay's review of the MMI Ek
    _decisions_363(r, aff, changes, jsonld_by_url)  # DECISIONS 363: the SEO team's gaps
    _decisions_364(r, aff, changes, jsonld_by_url)  # DECISIONS 364: image and file names
    _decisions_368(r, aff, changes, saved_texts)  # DECISIONS 368: İlginay's review of "Diğer bulgular"
    _decisions_370(r, aff, changes)  # DECISIONS 370: crawler findings only where robots.txt blocks
    _decisions_371(r, aff, changes)  # DECISIONS 371: İlginay's review of the Nature's Garden Ek
    _decisions_373(r, aff, changes)  # DECISIONS 373: Efsa's review (no subheadings, unrendered collections)
    _decisions_374(r, aff, changes)  # DECISIONS 374: judged timing values, the robots tag outside <head>
    _decisions_379(r, aff, changes)  # DECISIONS 379: a file's folder name, when the problem is there
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
        "kind": "offline rule reassessment", "rules": "DECISIONS 284 (3) and (4), 290, 300, 301, 304, 309, 315, 316, 317, 318, 321, 329, 337, 338, 340, 343, 344, 347, 349, 350, 351 and 356, applied by DECISIONS 285",
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


def saved_data(report: dict, affected: dict | None = None, saved_texts: list[str] | None = None,
               business: str | None = None, jsonld_by_url: dict | None = None) -> tuple[dict, list[str]]:
    """(copy, changes): only what DECISIONS 309 reads from the saved data (the platform, the RND-6 label), the certificate
    bands (321) and the place-name groups on location pages only (329), for a report of the current schema; `changes`
    is empty when nothing applies."""
    r = deepcopy(report)
    changes: list[str] = []
    _decisions_365(r, changes)  # DECISIONS 365: the platform from the saved pages with the current signals
    _decisions_309(r, changes, saved_texts or [])
    # DECISIONS 321: a certificate's expiry severity is read from the saved evidence, so a report of the current schema
    # written before it gets it too; the order and the problem summary follow.
    cert: list[str] = []
    _decisions_321(r, cert)
    _decisions_329(r, cert)  # DECISIONS 329: place-name groups only on location pages, also for a current-schema report
    if affected is not None:
        _decisions_337(r, affected, cert)  # DECISIONS 337: broken links split by what is to be fixed
        _decisions_338(r, affected, cert)  # DECISIONS 338: the SEO team's review of enpara
        _decisions_340(r, affected, cert)  # DECISIONS 340: FAQPage only for a real Q&A block
        # DECISIONS 343: the SEO team's technical review (redirects to an error page, second addresses, Product on
        # articles, sub-pages copying the parent, the section's name as H1)
        _decisions_347(r, cert)  # DECISIONS 347: page types again; training-only robots blocks their own rule
        _decisions_349(r, affected, cert)  # DECISIONS 349: blog posts with a product widget; reader pages' kinds
        _decisions_350(r, cert)  # DECISIONS 350: the alias-links card names its template link
        _decisions_351(r, cert)  # DECISIONS 351: Shopify's step only on a Shopify site
        _decisions_343(r, affected, cert)
        _decisions_356(r, affected, cert, saved_texts, business)  # DECISIONS 356: the business profile's own checks
        _decisions_359(r, affected, cert)  # DECISIONS 359: the twin address's copies are one card
        _decisions_360(r, affected, cert)  # DECISIONS 360: İlginay's review of the MMI Ek
        _decisions_363(r, affected, cert, jsonld_by_url)  # DECISIONS 363: the SEO team's gaps
        _decisions_364(r, affected, cert, jsonld_by_url)  # DECISIONS 364: image and file names
        _decisions_368(r, affected, cert, saved_texts)  # DECISIONS 368: İlginay's review of "Diğer bulgular"
        _decisions_370(r, affected, cert)  # DECISIONS 370: crawler findings only where robots.txt blocks
        _decisions_371(r, affected, cert)  # DECISIONS 371: İlginay's review of the Nature's Garden Ek
        _decisions_373(r, affected, cert)  # DECISIONS 373: Efsa's review (no subheadings, unrendered collections)
        _decisions_374(r, affected, cert)  # DECISIONS 374: judged timing values, the robots tag outside <head>
        # DECISIONS 379: a mistyped address or a folder name, also for a report of the current schema (a new crawl made
        # before the rule, which the web app does not re-evaluate in full)
        _decisions_379(r, affected, cert)
    if cert:
        from .report import problem_summary
        from .severity import apply as apply_severity
        changes += cert
        apply_severity(r.get("checks") or [], r.get("crawl") or {})
        order = _order(r)
        r["findings_in_priority_order"] = order
        by_id = {f["id"]: f for c in r.get("checks") or [] for f in c.get("findings") or []}
        old = r.get("problem_summary") or {}
        single = old.get("single_page")
        r["problem_summary"] = problem_summary([by_id[i] for i in order], affected or {}, pages_checked=old.get("pages_checked") or 0,
                                               checks=r.get("checks"),
                                               single_page=single.get("url") if isinstance(single, dict) else single,
                                               start_address=old.get("start_address"))
    if changes:
        from . import release_gate
        r["release_gate"] = release_gate.run(r, affected or {})
    return r, changes
