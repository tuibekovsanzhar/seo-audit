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
                             structure=crawl.get("structure"))
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
    """DECISIONS 321: a saved certificate expiry gets its severity by the days left at the audit (under 7 Blocker, under
    14 High, under 30 Medium), and a certificate the saved IDX-2 evidence shows inside the new 30-day window, with no
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
            if (tls.get("valid") and isinstance(tls.get("days_left"), (int, float)) and tls["days_left"] < window
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
          jsonld_by_url: dict[str, list[str]] | None = None, saved_texts: list[str] | None = None) -> tuple[dict, dict, dict]:
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
    _decisions_309(r, changes, saved_texts or [])
    _decisions_315(r, changes)
    _decisions_316(r, aff, changes)
    _decisions_317(r, changes)
    _decisions_318(r, changes)
    _decisions_321(r, changes)
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
        "kind": "offline rule reassessment", "rules": "DECISIONS 284 (3) and (4), 290, 300, 301, 304, 309, 315, 316, 317, 318 and 321, applied by DECISIONS 285",
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


def saved_data(report: dict, affected: dict | None = None, saved_texts: list[str] | None = None) -> tuple[dict, list[str]]:
    """(copy, changes): only what DECISIONS 309 reads from the saved data (the platform, the RND-6 label), for a report
    the current engine wrote, which needs no other rule; `changes` is empty when nothing applies."""
    r = deepcopy(report)
    changes: list[str] = []
    _decisions_309(r, changes, saved_texts or [])
    # DECISIONS 321: a certificate's expiry severity is read from the saved evidence, so a report of the current schema
    # written before it gets it too; the order and the problem summary follow.
    cert: list[str] = []
    _decisions_321(r, cert)
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
