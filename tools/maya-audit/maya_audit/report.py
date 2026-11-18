from __future__ import annotations

import json
import math
import re
import string
from collections import Counter
from pathlib import Path
from typing import Any

from urllib.parse import urlsplit

from .access_data import homepage_url
from .ai_skills import SKILLS, SkillBrief, skill_names
from .coverage import clean_on_what_was_read
from . import brand as brand_module, launch_gate, single_page, timeplan
from .findings import SEVERITY_DEFINITIONS, STATUS_MEANINGS, CheckResult, is_hygiene, priority_key
from .models import CrawlResult, FetchClass, GateResult, to_jsonable
from .html_links import is_html
from .index_data import HTTP_REDIRECT_LINES
from .urls import non_page_kind, normalize_url, registrable_domain


REPORT_VERSION = "0.4"


def build_report(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult] | None = None, *,
                 firecrawl: dict | None = None, all_phases_s: float | None = None, slept_s: float | None = None,
                 brand: dict[str, Any] | None = None) -> dict[str, Any]:
    """The JSON report. `brand` is the audit's brand (`maya_audit.brand.resolve`); by default it is read from the
    crawl's own pages, with no typed name. Outputs use `maya_audit.final.seal`, which also keeps the address lists."""
    return report_and_affected(result, gates, checks, firecrawl=firecrawl, all_phases_s=all_phases_s, brand=brand,
                               slept_s=slept_s)[0]


def report_and_affected(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult] | None = None, *,
                        firecrawl: dict | None = None, all_phases_s: float | None = None, slept_s: float | None = None,
                        brand: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """The JSON report and the full affected-address lists, both from the same qualified checks."""
    from .judgments import qualify_checks
    checks = qualify_checks(checks or [], result)
    site = [c for c in checks if not c.check_id.startswith("ANS")]
    ordered = sorted((f for c in site for f in c.findings), key=priority_key)
    from .schema import SCHEMA_VERSION  # here: schema.py describes this module's output

    by_id = {f["id"]: f for f in to_jsonable([f for c in site for f in c.findings])}
    report = {
        # The shape of this file (docs/REPORT-SCHEMA.md). A program reading a report checks this first.
        "schema_version": SCHEMA_VERSION,
        "generation": generation_metadata(result, firecrawl),
        # The vocabulary of check statuses, kept for `migrate` (0.3 -> 0.4). Not the shape version.
        "report_version": REPORT_VERSION,
        # 0.4 added "partial" and "observed" and a `coverage` block on every check (DECISIONS §99).
        "status_meanings": STATUS_MEANINGS,
        "scope": "INT-1..INT-4 gates" + (", " + ", ".join(sorted({c.check_id.split("-")[0] for c in checks})) + " checks"
                                         if checks else ""),
        "gates": to_jsonable(gates),
        "checks": to_jsonable(site),
        # Kept out of "checks" and out of the site priority order on purpose (spec §5 ANS).
        "answer_engine_panel": to_jsonable([c for c in checks if c.check_id.startswith("ANS")]),
        "findings_in_priority_order": [f.id for f in ordered],
        "needs_human_review": [r.id for c in checks for r in c.review_items],
        # What the page cap counts, and the redirect hops beside it (`crawl.pages` holds both kinds of record).
        "page_counts": dict(zip(("pages_checked", "redirects"), page_counts(result))),
        # The brand name the audit used and where it came from: typed, the site's own name, the address, or none (1.14).
        "brand": brand if brand is not None else brand_module.resolve(result),
        # The totals every output prints, and which page each problem is on (schema 1.9). Counted once, here.
        "problem_summary": problem_summary([by_id[f.id] for f in ordered], affected_urls(site),
                                           pages_checked=pages_shown(result, firecrawl), checks=site,
                                           single_page=single_page.page_url(result) if single_page.is_single(result) else None,
                              start_address=start_address(result)),
        # Empty unless the time limit was reached: which checks it stopped and which ran without their extra requests.
        "time_limit_cuts": time_limit_cuts(result, checks),
        # Direct access, content coverage and what is known about real AI crawlers, kept apart (schema 1.6).
        "audit_status": {**audit_status(result, gates, checks, firecrawl), "timing": timing(result, firecrawl, all_phases_s, slept_s)},
        "crawl": {**to_jsonable(result), "steps": timeplan.step_rows(getattr(result, "steps", None), firecrawl)},
    }
    # The platform and CDN the pages show, only when one is recognised (H34, maya_audit.site_platform).
    from .site_platform import recognise
    if (platform := recognise(result)) is not None:
        report["platform"] = platform
    if not (report.get("platform") or {}).get("name"):
        # DECISIONS 309: a page reader's copies keep no script list; the sitemap names and addresses still show some.
        from .site_platform import recognise_saved
        if (saved := recognise_saved(report)) is not None:
            report["platform"] = saved
    # DECISIONS 301 (2): which page regions of a language-mismatch finding are in the other language.
    from .language_regions import attach as attach_regions
    attach_regions(report)
    # G1 (DECISIONS 278): the release gate's decision on the report itself, last; it never changes a finding.
    from .release_gate import run as release_gate
    affected = affected_urls(checks)  # site and answer-engine findings, as the companion file always listed them
    report["release_gate"] = release_gate(report, affected)
    return report, affected


def affected_urls(checks: list[CheckResult]) -> dict[str, list[str]]:
    """Every affected page of every finding and review item, by id.

    The report's `scope.urls` holds the first 25 and `scope.count` the total. A program that must show or
    export all of them saves this beside the report rather than growing every report by the full lists.
    """
    out: dict[str, list[str]] = {}
    for check in checks:
        for item in [*check.findings, *check.review_items]:
            out[item.id] = list(item.scope.get("_all_urls") or item.scope.get("urls") or [])
    return out


PROBLEM_SEVERITIES = ("S1", "S2", "S3", "S4")
SEVERITY_WORDS = {"S1": "blocker", "S2": "high", "S3": "medium", "S4": "low"}
WHOLE_SITE = "Whole site"
# The same row when it also holds an element only one section's pages carry (a per-language menu): DECISIONS 198.
WHOLE_OR_SECTION = "Whole site or one section"
NOT_LISTED_LINE = "“{title}” also affects {pages} not listed here."  # pages: "1 more page", "15 more pages"
BY_PAGE_NOTE = "Pages with no problem are not listed. Notes are not counted."
# "Problems by page" in the Markdown names at most this many pages (CR-13); the rest are in the JSON.
BY_PAGE_ROWS = 25
BY_PAGE_MORE = "{n:more page|more pages} with problems: JSON report, `problem_summary.by_page`."
BY_PAGE_COLUMN = "What is wrong on this page"
FILES_TITLE = "Files (sitemaps, robots.txt, documents)"
FILES_COLUMN = "What is wrong with this file"


def pages_shown(result: CrawlResult, firecrawl: dict | None = None) -> int:
    """The number of pages a reader of the report is told were read for content: the unique pages read, by Maya's own
    crawler or a page reader (`read_counts`), the one figure every output prints. A page Maya asked for and was refused
    (a 429, a 403) was not read and is not counted (DECISIONS 289: nihan.com.tr said "2 pages read for content" in the
    headline and "1 page" everywhere else). `page_counts` keeps what the crawl fetched."""
    return read_counts(result, firecrawl)["pages"]


def _field(record: Any, name: str) -> Any:
    return record.get(name) if isinstance(record, dict) else getattr(record, name, None)


def _own_documents(result: Any) -> list[tuple[str, bool]]:
    """(address, whether it is a file rather than a page) for every record of Maya's own crawl that holds a readable
    document. From a CrawlResult, or from the `crawl` section of a saved report (the same rule as
    `PageFetch.readable_document`)."""
    out = []
    for page in _field(result, "pages") or []:
        kind = _field(page, "fetch_class")
        status = _field(page, "status")
        if getattr(kind, "value", kind) != "ok" or _field(page, "error") is not None:
            continue
        if not (_field(page, "view") == "provider" if status is None else 200 <= status < 300):
            continue
        media = _field(page, "content_type")
        is_file = bool(non_page_kind(_field(page, "url")) or (media and not is_html(media)))
        # Successful transport is not readable page content. Keep fetched-file diagnostics
        # separate; a small valid HTML document still counts without a size threshold.
        if not is_file and ((_field(page, "analysis") or {}).get("empty_response")
                            or _field(page, "body_bytes") == 0
                            or _field(page, "content_checks_eligible") is False):
            continue
        out.append((_field(page, "url"), is_file))
    return out


def read_counts(result: Any, firecrawl: dict | None = None) -> dict[str, Any]:
    """How many pages were read, counted once for every output (DECISIONS 170). A page is a distinct HTML document
    that was read: by Maya's own crawler, by the page reader, or by both.

    Two kinds of address Maya's crawler fetched are not pages and are counted beside them (`other_addresses`):
    `files` (a PDF or another document, an image: not HTML) and `same_page` (an address the page reader recorded as
    redirecting to a page that was read, such as /blog?tab=news leading to /blog: one document, two addresses).
    `read_by` holds three numbers that do not overlap and add up to `total`; `firecrawl` (every page the reader read:
    `firecrawl_only` + `both`) is kept for programs written against schema 1.6.

    `result` is a CrawlResult or the `crawl` section of a saved report; `firecrawl` the report's section."""
    section = firecrawl or {}
    rows = (section.get("pages") or []) if section.get("used") else []
    through = {row["url"] for row in rows if row.get("outcome") == "read"}
    documents = _own_documents(result)
    html = {url for url, is_file in documents if not is_file}
    leads_to = {row["url"]: normalize_url(row["final_url"]) or row["final_url"] for row in rows
                if row.get("outcome") == "redirected" and row.get("final_url")}
    own, files, same = set(), set(), set()
    for url, is_file in documents:
        if url in through:
            own.add(url)
        elif is_file:
            files.add(url)
        elif leads_to.get(url) not in (None, url) and (leads_to[url] in through or leads_to[url] in html):
            same.add(url)
        else:
            own.add(url)
    by = {"maya_only": len(own - through), "firecrawl_only": len(through - own), "both": len(own & through)}
    return {"pages": sum(by.values()), "read_by": {**by, "firecrawl": len(through), "total": sum(by.values())},
            "other_addresses": {"files": len(files), "same_page": len(same)}}


READ_SENTENCE = "{pages:page|pages} read."
ALSO_FETCHED = {(True, True): "Also fetched: {files:file|files} (PDF or other documents) and {same:address that leads|addresses that lead} to a page already read.",
                (True, False): "Also fetched: {files:file|files} (PDF or other documents).",
                (False, True): "Also fetched: {same:address that leads|addresses that lead} to a page already read."}


def also_fetched(other: dict[str, Any] | None) -> str | None:
    """"Also fetched: 5 files (PDF or other documents) and 7 addresses that lead to a page already read." None when
    every address fetched was a page of its own."""
    files, same = int((other or {}).get("files") or 0), int((other or {}).get("same_page") or 0)
    text = ALSO_FETCHED.get((bool(files), bool(same)))
    return phrase(text, files=files, same=same) if text else None


def read_sentence(counts: dict[str, Any]) -> str:
    """The one sentence for how much was read: "43 pages read. Also fetched: 5 files (PDF or other documents) and 7
    addresses that lead to a page already read." The second part is left out when every address was a page."""
    also = also_fetched(counts.get("other_addresses"))
    return phrase(READ_SENTENCE, pages=counts["pages"]) + (" " + also if also else "")


def _worst(findings: list[dict[str, Any]]) -> str | None:
    levels = [f["severity"] for f in findings]
    return min(levels, key=lambda level: PROBLEM_SEVERITIES.index(level) if level in PROBLEM_SEVERITIES else 9) if levels else None


def page_checks(checks: list[Any]) -> dict[str, Any]:
    """How many of the report's page checks could run (schema 1.11, DECISIONS 168). A page check is one whose question
    is answered by reading the audited pages (`coverage.PAGE_DEPENDENT`; the answer-engine panel and the paid data
    panels are never among them). One that is `not_assessed` could not run, and neither could one whose own evidence
    says it looked at no page (`pages_checked` or `candidates` is 0). `limited`: fewer than half could, so
    "no problems found" is not a clean result. From CheckResult objects or a saved report's check dicts."""
    from .coverage import NEEDS_AN_INDEXABLE_PAGE, PAGE_DEPENDENT

    def get(check, key):
        return check.get(key) if isinstance(check, dict) else getattr(check, key, None)

    def looked_at_nothing(check) -> bool:
        # The check's own evidence says it looked at no page: the test `coverage.settle` applies since schema 1.11, so
        # a report saved before it (the check reads "partial" there) is counted the same way. Nothing is guessed for
        # a check that recorded no such figure.
        evidence = get(check, "evidence") or {}
        return (get(check, "check_id") in NEEDS_AN_INDEXABLE_PAGE and get(check, "status") in ("pass", "partial", "observed", "not_applicable")
                and not get(check, "findings") and (evidence.get("pages_checked") == 0 or evidence.get("candidates") == 0))

    # A check a single-page audit set aside (it compares pages, or is about a homepage that was not audited) is not a
    # check that "could not run": it does not apply.
    from .single_page import not_applicable

    known = [check for check in checks if get(check, "check_id") in PAGE_DEPENDENT and not not_applicable(check)]
    ran = sum(1 for check in known if get(check, "status") != "not_assessed" and not looked_at_nothing(check))
    return {"total": len(known), "could_run": ran, "limited": ran < len(known) / 2}


def problem_summary(findings: list[dict[str, Any]], all_urls: dict[str, list[str]] | None = None, *,
                    pages_checked: int = 0, checks: list[Any] | None = None, single_page: str | None = None,
                    start_address: dict[str, Any] | None = None) -> dict[str, Any]:
    """How many problems there are and which page each is on, from findings as the report JSON holds them.

    A problem is a finding that is not a note (severity other than Info). A site-wide problem is counted once, under
    `whole_site`, and never against the pages it lists. So is one shared element that only a section's pages carry
    (`grouped_once`): its scope is those pages, its title says "of /tr/", and it is one line, not one on each page's row. Every other problem counts once for each distinct page it
    names: the full list (`all_urls`, by finding id: `affected_urls` or the saved affected-urls.json) when there is
    one, else the first 25 the report keeps in `scope.urls`. Where fewer pages are listed than `scope.count`, the
    difference is said in `not_listed`, so nothing is left out without a line saying so. Rows keep the order the
    findings came in (the report's priority order); the answer-engine panel is not passed in. Each page's
    row carries `items`: what each of its problems is on that page (`page_item`), from the finding's own evidence.
    An address that is a file (a sitemap, robots.txt, a document: `urls.non_page_kind`) gets its row under `files`,
    never among the pages. `whole_site.shared_elements` names the element behind each problem that one shared header
    or footer element causes on most pages. `pages_checked` is pages (`read_counts`), not addresses.
    `checks` (the report's site checks) adds `page_checks`: how many of the page checks could run.
    """
    by_severity = {level: 0 for level in (*PROBLEM_SEVERITIES, "Info")}
    whole: list[dict[str, Any]] = []
    pages: dict[str, list[dict[str, Any]]] = {}
    files: dict[str, list[dict[str, Any]]] = {}
    not_listed = []
    for finding in findings:
        by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
        if finding["severity"] == "Info":
            continue
        scope = finding.get("scope") or {}
        if grouped_once(finding):
            whole.append(finding)
            continue
        listed = list((all_urls or {}).get(finding["id"]) or scope.get("urls") or [])
        if said_once(finding, listed, pages_checked):
            whole.append(finding)
            continue
        for url in dict.fromkeys(listed):
            # A sitemap file, robots.txt or a document is not a page: it is listed apart, never as a page's row.
            (files if non_page_kind(url) else pages).setdefault(url, []).append(finding)
        missing = int(scope.get("count") or 0) - len(listed)
        if missing > 0:
            not_listed.append({"finding_id": finding["id"], "pages": missing})

    def row(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"problems": len(items), "worst_severity": _worst(items), "finding_ids": [f["id"] for f in items]}

    # Each page's row also says what is wrong on that page (`items`, schema 1.10), in the order of `finding_ids`.
    def table(found: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return sorted(({"url": url, **row(items), "items": [page_item(f, url) for f in items]} for url, items in found.items()),
                      key=lambda r: (PROBLEM_SEVERITIES.index(r["worst_severity"]) if r["worst_severity"] in PROBLEM_SEVERITIES else 9,
                                     -r["problems"], r["url"]))

    notes = by_severity["Info"]
    return {"pages_checked": pages_checked, "problems": sum(by_severity.values()) - notes, "notes": notes,
            "by_severity": by_severity, "whole_site": {**row(whole), "shared_elements": shared_elements_of(whole)},
            "by_page": table(pages), "files": table(files), "not_listed": not_listed,
            **({"page_checks": page_checks(checks)} if checks is not None else {}),
            # A single-page audit (schema 1.13): the one address that was read. Absent in an ordinary audit.
            **({"single_page": {"url": single_page}} if single_page else {}),
            # The start address answered with an error and the audit ran from another page (schema 1.14). Absent otherwise.
            **({"start_address": start_address} if start_address else {})}


START_FAILED = "The start address you entered returned {status} ({path}). The audit was run from {audited_from} instead."


def start_address(result: CrawlResult) -> dict[str, Any] | None:
    """{"entered", "status", "audited_from"} when the address the audit was started on answered 400-599 and the audit
    still read the site from another page (the root, found through the sitemap); else None (DECISIONS 202). A
    single-page audit has no other page: its outcome already says the page could not be read."""
    if single_page.is_single(result):
        return None
    entered = normalize_url(result.start_url) or result.start_url
    first = next((p for p in result.pages if p.url == entered), None)
    status = getattr(first, "status", None)
    if not isinstance(status, int) or not 400 <= status <= 599:
        return None
    home = homepage_url(result)
    if home == entered or not any(p.url == home and p.status and 200 <= p.status < 300 for p in result.pages):
        return None
    return {"entered": result.start_url, "status": status, "audited_from": home}


def start_failed_line(found: dict[str, Any] | None) -> str | None:
    """The sentence every output puts first when the start address failed, or None."""
    if not found:
        return None
    parts = urlsplit(str(found.get("entered") or ""))
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return START_FAILED.format(status=found.get("status"), path=path, audited_from=found.get("audited_from"))


def section_only(finding: dict[str, Any]) -> bool:
    """Whether a finding is about one element that only the pages of a section carry (a per-language menu, a
    related-posts block under /blog/): its `evidence.shared_element` holds `section` and its scope is not the site's."""
    element = (finding.get("evidence") or {}).get("shared_element")
    return isinstance(element, dict) and "section" in element and (finding.get("scope") or {}).get("kind") != "sitewide"


def grouped_once(finding: dict[str, Any]) -> bool:
    """Whether "Problems by page" lists a problem once, in its first row, and not on each page's row: a site-wide
    problem, and one shared element of a section (DECISIONS 198: one element is one line, wherever it reaches)."""
    return (finding.get("scope") or {}).get("kind") == "sitewide" or section_only(finding)


# A page-scope problem whose line under each page would only repeat its title is said once, in the first row, when it is
# on this many pages, or on this share of the pages read and at least SAID_ONCE_MIN_PAGES (DECISIONS 218).
SAID_ONCE_PAGES = 10
SAID_ONCE_SHARE = 0.6
SAID_ONCE_MIN_PAGES = 5


def said_once(finding: dict[str, Any], listed: list[str], pages_checked: int = 0) -> bool:
    """Whether "Problems by page" lists a page-scope problem once, in its first row, and on no page's row: its line under
    a page would be the generic "Also affected by" (kind `affected`), and it is on many pages (DECISIONS 218). A problem
    whose line says something about the page itself stays on the rows."""
    pages = [url for url in dict.fromkeys(listed) if not non_page_kind(url)]
    count = max(int((finding.get("scope") or {}).get("count") or 0), len(pages))
    many = count >= SAID_ONCE_PAGES or (count >= SAID_ONCE_MIN_PAGES and pages_checked > 0 and count >= SAID_ONCE_SHARE * pages_checked)
    return bool(pages) and many and all(page_item(finding, url)["kind"] == "affected" for url in pages)


def whole_row_label(summary: dict[str, Any]) -> str:
    """What the first row of "Problems by page" is called: "Whole site", or "Whole site or one section" when it also
    holds an element of one section (whose own line says which: "on 26 page(s) of /tr/")."""
    shared = (summary.get("whole_site") or {}).get("shared_elements") or []
    return WHOLE_OR_SECTION if any("section" in (entry.get("element") or {}) for entry in shared) else WHOLE_SITE


def shared_elements_of(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The site-wide problems that one shared element causes (maya_audit.shared_elements): which element, and on how
    many pages. Read from each finding's `evidence.shared_element`."""
    out = []
    for finding in findings:
        element = (finding.get("evidence") or {}).get("shared_element")
        if isinstance(element, dict):
            out.append({"finding_id": finding["id"], "kind": element.get("kind"),
                        "element": {key: value for key, value in element.items() if key not in ("kind", "pages")},
                        "pages": element.get("pages")})
    return out


# -- what is wrong on one page ---------------------------------------------------------------------------------------
#
# A finding's title counts the whole site ("31 page title(s) above the 60-character guidance band"). Under one page
# that figure misleads, so each page's row says what is wrong on that page, with that page's own numbers. The numbers
# come from the finding's `evidence` as the report JSON holds it, so a saved report is read the same way as a new one.

class _Phrase(string.Formatter):
    """str.format with two additions: `{count:page|pages}` writes "1 page" or "3 pages" (the number, then the word
    for one or for many), and `{count:.}` groups thousands with a dot, as Turkish does. A whole number written with a
    word is grouped with a comma ("1,234 pages")."""

    def format_field(self, value: Any, format_spec: str) -> str:
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        whole = isinstance(value, int) and not isinstance(value, bool)
        if "|" in format_spec:
            one, _, many = format_spec.partition("|")
            # A caller may hand over a number already written out ("1"): it is one all the same.
            return (f"{value:,}" if whole else str(value)) + " " + (one if value == 1 or str(value).strip() == "1" else many)
        if format_spec == ".":
            return f"{value:,}".replace(",", ".") if whole else str(value)
        return super().format_field(value, format_spec)


_PHRASE = _Phrase()


def phrase(template: str, **values: Any) -> str:
    """`template` with its placeholders filled, by the rule above. The web layer's `strings.t` uses the same rule."""
    return _PHRASE.format(template, **values)


def holes(template: str) -> list[str]:
    """The placeholder names in a template, whatever form each takes."""
    return [name for _, name, _, _ in _PHRASE.parse(template) if name]


# One table of kinds: the English sentence, and the plain form used when the page's own number is not in the report
# (the evidence list was cut before this page, or an older check did not record it). The plain form never borrows the
# site-wide count. The web layer words the same kinds through its `bypage.<kind>` strings (English word for word).
PAGE_KINDS: dict[str, tuple[str, str | None]] = {
    # the default, for a finding no rule below covers
    "affected": ("Also affected by: “{title}” (site-wide: {count:page|pages})", "Also affected by: “{title}”"),
    # IDX-1
    "status_5xx": ("Returns a server error (5xx) on every attempt", None),
    "connection_fails": ("Fails at the connection level on every attempt", None),
    "times_out": ("Times out on every attempt", None),
    "status_4xx": ("Returns {status}", "Returns a client error (4xx)"),
    # IDX-3
    "redirect_loop": ("Redirect cycle observed in the tested native requests", None),
    "redirect_intermittent": ("Redirect and success responses varied across native attempts; inspect the saved success evidence", None),
    "redirect_self_once": ("Redirect cycle observed; verification is incomplete", None),
    "redirect_chain": ("Starts a chain of {redirects} redirects, ending at {final}", "Starts a redirect chain of 2 or more hops"),
    "redirect_to_http": ("Redirects to an http:// address: {target}", "Redirects from https:// to an http:// address"),
    # IDX-4
    "canonical_different": ("Canonical points to {canonical}: different content", "Canonical points to a URL with different content"),
    "canonical_different_via": ("Canonical points to {canonical} (which ends at {ends_at}): different content",
                                "Canonical points to a URL with different content"),
    "canonical_broken": ("Canonical points to {canonical}, which is broken, noindexed or an error",
                         "Canonical points to a URL that is broken, noindexed or an error"),
    "canonical_conflict": ("Declares conflicting canonicals", None),
    # IDX-6
    "link_broken": ("Links to {target}, which returns {status}", "Links to a page that returns an error"),
    "links_tagged": ("{count:internal link|internal links} tagged {parameters}", "Has internal links that carry tracking parameters"),
    "links_other_site": ("{count:link points|links point} to another site ({sites}) at a path that exists on this one",
                         "Has links to another site at a path that exists on this one"),
    # IDX-7, IDX-8
    "orphan": ("Listed only in the sitemap: no internal link points to it", None),
    "text_identical": ("Has the same visible text as {others:other page|other pages}", "Has the same visible text as other pages"),
    "text_near_identical": ("Main content is nearly identical to {others:other page|other pages}",
                            "Main content is nearly identical to other pages"),
    "title_shared": ("Shares its title “{title}” with {others:other page|other pages}", "Shares its title with other pages"),
    # IDX-8, merged (DECISIONS 225): which group the page is in, and what the group's pages share.
    "duplicate_group": ("Copy or near-copy of {others:other page|other pages} ({signals})", "Copy or near-copy of other pages"),
    # ACC-3
    "robots_directive": ("Robots instruction on this page: {label}", "Has a robots instruction that withholds it"),
    # PRF-1, PRF-2
    "slow_html": ("Takes {seconds} s (median) to return its HTML", "Slow to return its HTML"),
    "timeouts_some": ("Timed out on {timeouts} of {attempts} attempts", "Times out on some attempts"),
    "fails_some": ("Failed on {failures} of {attempts} attempts", "Fails on some attempts"),
    # RND-1, RND-3, RND-6, RND-7
    "content_after_js": ("Main content appears only after JavaScript runs ({raw:,} words in the raw HTML, {rendered:,} after)",
                         "Main content appears only after JavaScript runs"),
    "content_partly_after_js": ("Part of the content appears only after JavaScript runs ({raw:,} words in the raw HTML, {rendered:,} after)",
                                "Part of the content appears only after JavaScript runs"),
    "maybe_client_rendered": ("May be client-rendered (not opened in a browser)", None),
    "revealed_words": ("{added:more word appears|more words appear} only after a click or scroll ({before:,} → {after:,})",
                       "More content appears only after a click or scroll"),
    "maybe_hidden_content": ("May hide content behind a click or scroll (not opened in a browser)", None),
    "html_large": ("HTML is {kb:,} KB", "HTML is very large"),
    "main_content_late": ("Main content starts {kb:,} KB into the HTML", "Main content starts late in the HTML"),
    "main_share": ("Only {percent}% of the page's text is main content", "Less than {limit}% of the page's text is main content"),
    # STR-1, STR-2
    "no_title": ("No <title>", None),
    "title_same_start": ("Title begins with the same words as {others:other page|other pages}: “{start}”",
                         "Title begins with the same words as other pages"),
    "title_generic": ("Generic title: “{title}”", "Generic title"),
    "no_h1": ("No <h1>", None),
    "no_organization": ("No Organization structured data", None),
    "no_subheadings": ("Long page with no subheadings ({words:,} words)", "Long page with no subheadings"),
    # STR-3, STR-4, STR-5, STR-6
    "jsonld_unparsed": ("Has JSON-LD that does not parse", None),
    "markup_url_broken": ("Structured data names {markup_url}, which returns {status}", "Structured data names a URL that returns an error"),
    "markup_differs": ("Structured-data {field} differs from the {field} shown on the page",
                       "Structured data differs from what the page shows"),
    # A price that differs is said with both values (DECISIONS 175).
    "markup_price_differs": ("Structured data says {markup} {currency}; the page shows “{shown}”",
                             "Structured-data price differs from the price shown on the page"),
    "brand_id_name": ("Names the brand “{name}” under an @id that carries another name on other pages",
                      "Uses a brand @id that carries a different name on other pages"),
    "date_future": ("Carries a future date: {date} ({signal})", "Carries a future date"),
    "dates_apart": ("Date signals are more than {limit} days apart", "Date signals are far apart"),
    # STR-7, STR-8
    "images_broken": ("{images:image file does|image files do} not load", "Has image files that do not load"),
    "alt_missing": ("{images:likely meaningful image has|likely meaningful images have} missing or empty alt text",
                    "Has likely meaningful images with missing or empty alt text"),
    # Where the grid is and what its first row says, so it can be found on the page (DECISIONS 200).
    "div_grid": ("<div> grid at {selector}; first row: “{first_row}”", "Lays out a pricing or spec comparison as <div> grids instead of <table>"),
    # Named by the heading it sits under (DECISIONS 223); the selector stays in the evidence only.
    "div_grid_heading": ("<div> grid under “{heading}”; first row: “{first_row}”",
                         "Lays out a pricing or spec comparison as <div> grids instead of <table>"),
    "table_empty": ("Contains {tables:empty <table> element|empty <table> elements}", "Contains an empty <table> element"),
    # STR-9, STR-10
    "hreflang_status": ("hreflang {hreflang} points to {target}, which answers {status}", "Has hreflang links to URLs that do not return 200"),
    "hreflang_redirect": ("hreflang {hreflang} points to {target}, which answers {status} (redirects to {location})",
                          "Has hreflang links to URLs that do not return 200"),
    "hreflang_no_return": ("hreflang {hreflang} to {target} is not returned", "Has hreflang links that are not returned"),
    "lang_mismatch": ("<html lang> says {declared}, but the text reads as {detected}", "<html lang> does not match the content language"),
    "og_image_dead": ("og:image returns {status}: {image}", "og:image returns 404/410"),
    # STR-11, STR-12, STR-13, STR-14
    "entity_two_values": ("Structured data gives one entity two {field} values: {first} and {second}",
                          "Structured data gives one entity different {field} values"),
    "entity_many_values": ("Structured data gives one entity {count} different {field} values: {values}",
                           "Structured data gives one entity different {field} values"),
    "language_mismatch": ("Declared as {declared}, but the main content is mostly {language}", "Mostly in another language than it declares"),
    "headings_language": ("{headings:section heading is|section headings are} in {language}, but the page is declared as {declared}",
                          "Has section headings in another language than it declares"),
    "placeholder_text": ("Contains placeholder or template text", None),
    "template_markers": ("Has unfilled template markers: {markers}", "Has unfilled template markers"),
    "links_generic": ("{links:link names its target|links name their target} only with generic text",
                      "Has links that name their target only with generic text"),
    "links_no_text": ("{links:link has|links have} no text at all", "Has links with no text at all"),
    # STR-16, STR-19, STR-20
    "description_shared": ("Shares its meta description with {others:other page|other pages}", "Shares its meta description with other pages"),
    "links_no_address": ("{links:link has|links have} no address a crawler can follow",
                         "Has links with no address a crawler can follow (number on this page not recorded)"),
    "message_in_media": ("Carries its message in video or animation, with {words:word|words} of text",
                         "Carries its message in video or animation, with little text"),
    # TSEO-1
    "title_long": ("Title above the editorial guidance band ({characters} characters)", "Title above the editorial guidance band (over {limit} characters)"),
    "title_short": ("Title below the editorial guidance band ({characters:character|characters})", "Title below the editorial guidance band (under {limit} characters)"),
    "description_long": ("Meta description above the editorial guidance band ({characters} characters)", "Meta description above the editorial guidance band (over {limit} characters)"),
    "description_short": ("Meta description below the editorial guidance band ({characters:character|characters})", "Meta description below the editorial guidance band (under {limit} characters)"),
    "heading_jumps": ("Heading jumps {jumps}", "Heading levels are skipped"),
}
# Added to a sentence that describes the first of several such things on the page.
MORE_ON_PAGE = " (and {more} more on this page)"


def _rows(finding: dict[str, Any], key: str, url: str, field: str = "url") -> list[dict[str, Any]]:
    """The evidence rows under `key` that are about `url`. A row names its page in `field`; a list there means any of them."""
    found = []
    for row in (finding.get("evidence") or {}).get(key) or []:
        named = row.get(field) if isinstance(row, dict) else None
        if named == url or (isinstance(named, list) and url in named):
            found.append(row)
    return found


def _first(finding: dict[str, Any], key: str, url: str, field: str = "url") -> tuple[dict[str, Any], dict[str, Any]]:
    """(the first row about `url`, {"more": n} when there are n further ones). ({}, {}) when the page has no row."""
    rows = _rows(finding, key, url, field)
    return (rows[0], {"more": len(rows) - 1} if len(rows) > 1 else {}) if rows else ({}, {})


def _near(address: str | None, url: str) -> str | None:
    """An address as a path when it is on the page's own host ("/tr/"), else whole."""
    if not isinstance(address, str):
        return address
    there, here = urlsplit(address), urlsplit(url)
    if (there.scheme, there.netloc) != (here.scheme, here.netloc):
        return address
    return (there.path or "/") + (f"?{there.query}" if there.query else "")


def _cut(text: Any, limit: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _listed_all(finding: dict[str, Any], key: str, total_key: str) -> bool:
    """True when the evidence list under `key` is whole, so counting a page's rows in it gives that page's number."""
    evidence = finding.get("evidence") or {}
    total = evidence.get(total_key)
    return isinstance(total, int) and total <= len(evidence.get(key) or [])


def _others(finding: dict[str, Any], group: list | None = None) -> dict[str, Any]:
    count = len(group) if group else int((finding.get("scope") or {}).get("count") or 0)
    return {"others": count - 1} if count > 1 else {}


def _status_4xx(f, url, m):
    return "status_4xx", {"status": _first(f, "pages", url)[0].get("status")}


def _redirect_chain(f, url, m):
    chain = next((c for c in (f.get("evidence") or {}).get("chains") or [] if (c.get("hops") or [None])[0] == url), {})
    return "redirect_chain", {"redirects": chain.get("redirects"), "final": _near((chain.get("hops") or [None])[-1], url)}


def _redirect_to_http(f, url, m):
    return "redirect_to_http", {"target": _first(f, "redirects", url)[0].get("target")}


def _canonical_different(f, url, m):
    row = _first(f, "pages", url)[0]
    hops = row.get("resolved_via") or []
    if row.get("canonical") and len(hops) > 1 and hops[-1] != row["canonical"]:
        return "canonical_different_via", {"canonical": row["canonical"], "ends_at": _near(hops[-1], url)}
    return "canonical_different", {"canonical": row.get("canonical")}


def _canonical_broken(f, url, m):
    return "canonical_broken", {"canonical": _first(f, "pages", url)[0].get("canonical")}


def _link_broken(f, url, m):
    evidence = f.get("evidence") or {}
    return "link_broken", {"target": evidence.get("target"), "status": evidence.get("target_status")}


def _links_tagged(f, url, m):
    rows = _rows(f, "links", url, "source")
    if not rows or not _listed_all(f, "links", "links_count"):
        return "links_tagged", {}
    by_value = Counter(value for row in rows for value in row.get("parameters") or [])
    shown = ", ".join(by_value) if len(by_value) == 1 else ", ".join(f"{value} ({many})" for value, many in by_value.items())
    return "links_tagged", {"count": len(rows), "parameters": shown}


def _links_other_site(f, url, m):
    rows = _rows(f, "links", url, "source")
    if not rows or not _listed_all(f, "links", "links_count"):
        return "links_other_site", {}
    return "links_other_site", {"count": len(rows), "sites": ", ".join(dict.fromkeys(str(row.get("other_site")) for row in rows))}


def _title_shared_idx8(f, url, m):
    evidence = f.get("evidence") or {}
    return "title_shared", {"title": _cut(evidence["title"]) if evidence.get("title") else None, **_others(f, evidence.get("urls"))}


def _text_identical(f, url, m):
    return "text_identical", _others(f, (f.get("evidence") or {}).get("urls"))


def _text_near_identical(f, url, m):
    return "text_near_identical", _others(f, (f.get("evidence") or {}).get("urls"))


def _duplicate_group(f, url, m):
    group = next((g for g in (f.get("evidence") or {}).get("duplicate_groups") or [] if url in (g.get("urls") or [])), None)
    if not group:
        return "duplicate_group", {}
    return "duplicate_group", {"others": len(group["urls"]) - 1, "signals": list(group.get("signals") or []),
                               **({"same_text": group["same_text_pages"]} if group.get("same_text_pages") else {})}


def _robots_directive(f, url, m):
    return "robots_directive", {"label": m.group("label")}


def _slow_html(f, url, m):
    median = _first(f, "pages", url)[0].get("median_total_ms")
    return "slow_html", {"seconds": round(median / 1000, 1) if isinstance(median, (int, float)) else None}


def _counts(kind: str, key: str, *names: str):
    def rule(f, url, m):
        row = _first(f, key, url)[0]
        return kind, {name: row.get(name) for name in names}
    return rule


def _content_after_js(kind: str):
    def rule(f, url, m):
        row = _first(f, "pages", url)[0]
        return kind, {"raw": row.get("raw_words"), "rendered": row.get("rendered_words")}
    return rule


def _revealed_words(f, url, m):
    row = _first(f, "pages", url)[0]
    before, after = row.get("words_before"), row.get("words_after")
    if not (isinstance(before, int) and isinstance(after, int) and after > before):
        return "revealed_words", {}
    return "revealed_words", {"added": after - before, "before": before, "after": after}


def _kilobytes(kind: str, name: str):
    def rule(f, url, m):
        size = _first(f, "pages", url)[0].get(name)
        return kind, {"kb": size // 1000 if isinstance(size, int) else None}
    return rule


def _main_share(f, url, m):
    share = _first(f, "pages", url)[0].get("main_share")
    # Rounded down: 0.295 under a "less than 30%" rule is said as 29%, never as 30%.
    return "main_share", {"percent": math.floor(share * 100 + 1e-9) if isinstance(share, (int, float)) else None, "limit": int(m.group("limit"))}


def _title_shared(f, url, m):
    group = next((g for g in (f.get("evidence") or {}).get("groups") or [] if url in (g.get("urls") or [])), None)
    if not group:
        return "title_shared", {}
    return "title_shared", {"title": _cut(group.get("title") or ""), "others": len(group["urls"]) - 1}


def _title_same_start(f, url, m):
    group = next((g for g in (f.get("evidence") or {}).get("groups") or []
                  if any(isinstance(page, dict) and page.get("url") == url for page in g.get("pages") or [])), None)
    if not group:
        return "title_same_start", {}
    return "title_same_start", {"start": group.get("shared_start"), "others": len(group["pages"]) - 1}


def _title_generic(f, url, m):
    title = _first(f, "pages", url)[0].get("title")
    return "title_generic", {"title": _cut(title) if title else None}


def _no_subheadings(f, url, m):
    return "no_subheadings", {"words": _first(f, "pages", url)[0].get("content_words")}


def _markup_url_broken(f, url, m):
    row, more = _first(f, "items", url)
    return "markup_url_broken", {"markup_url": row.get("markup_url"), "status": row.get("markup_url_status"), **more}


def _markup_differs(f, url, m):
    return "markup_differs", {"field": m.group("field")}


def _shown_prices(row: dict[str, Any], only_own: bool = False) -> list[str]:
    """The prices of the page an STR-4 price row holds, as written on the page. A report saved before 2026-10-11 holds
    them as plain text; a newer one as {text, value, currency, context, where}."""
    found = row.get("visible")
    if isinstance(found, str) or not found:
        return []
    texts = [entry.get("text") if isinstance(entry, dict) else entry for entry in found
             if not (only_own and isinstance(entry, dict) and entry.get("where") != "main content")]
    return list(dict.fromkeys(str(text) for text in texts if text))


def _markup_price_differs(f, url, m):
    rows = [row for row in _rows(f, "values", url) if row.get("field") == "price"]
    row, more = (rows[0] if rows else {}), ({"more": len(rows) - 1} if len(rows) > 1 else {})
    shown = _shown_prices(row, only_own=True) or _shown_prices(row)
    return "markup_price_differs", {"markup": row.get("schema_value"), "currency": row.get("schema_currency"),
                                    "shown": shown[0] if shown else None, **more}


# -- what a finding's evidence says, line by line -----------------------------------------------------------------------
#
# Some findings are only understood with their values beside them: a price that "differs" (which price, from what?),
# a brand "named 5 different ways" (which five?). These lines are read from the finding's or the review item's own
# evidence, so a saved report gives the same lines as a new one. The web layer words the same kinds through its
# `detail.<kind>` strings.
DETAILS_TITLE = "The values"
DETAIL_KINDS = {
    "price_pair": "Markup: {markup} / Shown: “{shown}”",
    "price_unclear": "Markup: {markup} / Shown: {shown} ({why})",
    "price_none": "Markup: {markup} / Shown: no price of the page's own ({why})",
    "brand_name": "“{name}”: {sources}",
    "og_site_name": "og:site_name is “{value}”",
    "more": "and {more} more",
    # IDX-1: where else its empty or failing pages are listed, and in which sections they are (DECISIONS 215).
    "also_sitemap": "Also listed in the sitemap: {count} of these pages (IDX-5 counts them in its share).",
    "also_sitemap_left_out": ("Also listed in the sitemap: {count} of these pages. Without them the sitemap's share of URLs "
                              "that are not live is within IDX-5's threshold, so IDX-5 makes no finding of its own."),
    "also_sitemap_plain": "Also listed in the sitemap: {count} of these pages.",
    "also_llms": "Also linked from {file}: {count} of these pages.",
    "also_acc4": "Also in ACC-4's comparison of Googlebot's user agent with a browser: {count} of these pages.",
    "section_pages": "{section}: {count:page|pages} (for example {examples})",
    # IDX-8: one line a group of copies or near-copies (DECISIONS 225), with decision 190's advice for variants.
    "duplicate_group": "{pages}: {signals}",
    "duplicate_group_variant": ("{pages}: {signals}. These look like variants of one product: add what sets each apart "
                                "(ingredients, weight, use), or create a parent product page."),
    # IDX-2: what http:// does on each host (decision 188), one line a host.
    **{f"http_{outcome}": line for outcome, line in HTTP_REDIRECT_LINES.items()},
}
DETAILS_SHOWN = 12
# A source of a brand name as it is said in a list ("title suffix (38 pages)").
NAME_SOURCES = {"title suffix/prefix": "title suffix", "Organization name": "Organization name", "og:site_name": "og:site_name",
                "WebSite name": "WebSite name", "footer legal name": "footer legal name", "logo alt text": "logo alt text"}


def detail_lines(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The values behind one finding or review item: [{"kind", "url" (when the line is about one page), "values"}].
    Empty for a finding whose title already says everything."""
    evidence, check_id, title = entry.get("evidence") or {}, entry.get("check_id"), entry.get("title") or ""
    lines: list[dict[str, Any]] = []
    if check_id == "STR-4" and "price" in title:
        for row in evidence.get("values") or []:
            if not isinstance(row, dict) or row.get("field") != "price":
                continue
            markup = " ".join(str(part) for part in (row.get("schema_value"), row.get("schema_currency")) if part)
            if row.get("outcome") == "conflict":
                shown = _shown_prices(row, only_own=True) or _shown_prices(row)
                lines.append({"kind": "price_pair", "url": row.get("url"), "values": {"markup": markup, "shown": ", ".join(shown[:3])}})
                continue
            shown = _shown_prices(row, only_own=True) or _shown_prices(row)
            why = row.get("why_not_reliable") or (row.get("visible") if isinstance(row.get("visible"), str) else None) or "not shown on the page"
            lines.append({"kind": "price_unclear" if shown else "price_none", "url": row.get("url"),
                          "values": {"markup": markup, "why": why, **({"why_code": row["why_code"]} if row.get("why_code") else {}),
                                     **({"shown": ", ".join(f"“{text}”" for text in shown[:3])} if shown else {})}})
    elif check_id == "STR-5" and evidence.get("variants"):
        for variant in evidence["variants"]:
            seen = variant.get("seen_as") or []
            name = variant.get("name") or next((s.get("value") for s in seen if s.get("value")), variant.get("normalized"))
            by_source = variant.get("by_source")
            if not isinstance(by_source, dict):  # saved before the counts were kept: count what the report lists
                counted: Counter = Counter()
                for source in seen:
                    counted[source.get("source")] += int(source.get("pages") or 1)
                by_source = dict(counted)
            lines.append({"kind": "brand_name", "values": {"name": name, "sources": [
                {"source": source, "pages": pages} for source, pages in by_source.items() if source]}})
    elif check_id == "STR-5" and title.startswith("og:site_name holds"):
        lines = [{"kind": "og_site_name", "url": row.get("url"), "values": {"value": row.get("og_site_name")}}
                 for row in evidence.get("pages") or [] if isinstance(row, dict)]
    elif check_id == "IDX-2" and title.startswith("No HTTP to HTTPS redirect"):
        # One line a host, the hosts that are not redirected first. A report saved before the outcomes were kept has
        # none: its title says the one answer in its parenthesis.
        rows = [row for row in evidence.get("hosts") or [] if isinstance(row, dict) and row.get("outcome") in HTTP_REDIRECT_LINES]
        tested = {row.get("host"): row for row in rows}
        for row in sorted(rows, key=lambda row: row["outcome"] == "redirects_to_https"):
            values = {"url": row.get("http_url") or f"http://{row.get('host')}/", "status": row.get("status"), "location": row.get("location")}
            if row["outcome"] == "redirects_to_http_served":
                try:
                    values["status"] = (tested.get(urlsplit(row.get("location") or "").hostname) or {}).get("status")
                except ValueError:
                    pass
            lines.append({"kind": f"http_{row['outcome']}", "values": values})
    elif check_id == "IDX-1" and (evidence.get("also_listed_in") or evidence.get("by_section")):
        # Where else these pages are listed, and in which sections they are (DECISIONS 215).
        for also in evidence.get("also_listed_in") or []:
            if not isinstance(also, dict):
                continue
            where = also.get("where")
            kind = ("also_sitemap_left_out" if also.get("left_out") else "also_sitemap_plain" if also.get("not_in_share_finding")
                    else "also_sitemap") if where == "sitemap" else "also_llms" if where == "llms.txt" else "also_acc4" if where == "acc4" else None
            if kind:
                lines.append({"kind": kind, "values": {"count": also.get("count"), **({"file": also["file"]} if also.get("file") else {})}})
        for row in evidence.get("by_section") or []:
            if isinstance(row, dict):
                lines.append({"kind": "section_pages", "values": {"section": row.get("section"), "count": row.get("count"),
                                                                  "examples": ", ".join(row.get("examples") or [])}})
    elif check_id == "IDX-8" and evidence.get("duplicate_groups"):
        # One line a group of copies or near-copies, with what its pages share (DECISIONS 225).
        for row in evidence["duplicate_groups"]:
            if not isinstance(row, dict):
                continue
            urls = [url for url in row.get("urls") or [] if isinstance(url, str)]
            lines.append({"kind": "duplicate_group_variant" if row.get("variant_like") else "duplicate_group",
                          "values": {"pages": ", ".join(_page_path(url) for url in urls), "signals": list(row.get("signals") or []),
                                     **({"same_text": row["same_text_pages"]} if row.get("same_text_pages") else {})}})
    if len(lines) > DETAILS_SHOWN:
        lines = lines[:DETAILS_SHOWN] + [{"kind": "more", "values": {"more": len(lines) - DETAILS_SHOWN}}]
    return lines


def _page_path(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


# What the pages of one duplicate group share (IDX-8, DECISIONS 225), as a group's line says it. The web layer words
# the same codes through its `detail.signal.<code>` strings.
DUPLICATE_SIGNALS = {"same_text": "same text", "nearly_same": "nearly the same main content", "same_title": "same title",
                     "same_description": "same description", "same_text_some": "same text on {same_text} of them"}


def signals_sentence(values: dict[str, Any]) -> str:
    """"nearly the same main content, same title, same text on 2 of them"."""
    said = [DUPLICATE_SIGNALS[code] for code in values.get("signals") or [] if code in DUPLICATE_SIGNALS]
    if values.get("same_text"):
        said.append(phrase(DUPLICATE_SIGNALS["same_text_some"], same_text=values["same_text"]))
    return ", ".join(said)


def detail_sentence(line: dict[str, Any], origin: str | None = None) -> str:
    """One detail line in the engine's English, as the Markdown report prints it."""
    values = dict(line["values"])
    if line["kind"] == "brand_name":
        values["sources"] = ", ".join(f"{NAME_SOURCES.get(s['source'], s['source'])} ({_counted(s['pages'], 'page')})" for s in values["sources"])
    if "signals" in values:
        values["signals"] = signals_sentence(values)
    text = phrase(DETAIL_KINDS[line["kind"]], **values)
    return f"`{_short(line['url'], origin) if origin else line['url']}`: {text}" if line.get("url") else text


def merged_detail_sentences(details: list[dict[str, Any]], origin: str | None = None) -> list[str]:
    """`detail_sentence` for each line, with the pages that say the same thing on one line ("`/`, `/a`: og:site_name is
    “X”"): a value repeated on several pages is said once (gx3 length guard)."""
    said: dict[str, list[str]] = {}
    for line in details:
        text = detail_sentence({**line, "url": None})
        said.setdefault(text, [])
        if line.get("url"):
            said[text].append(f"`{_short(line['url'], origin) if origin else line['url']}`")
    return [f"{', '.join(pages)}: {text}" if pages else text for text, pages in said.items()]


def title_with_details(entry: dict[str, Any]) -> str:
    """A site-wide finding's title with what it counts said after it: "The brand is named 3 different ways: “Acme”:
    title suffix (38 pages); “ACME Ltd”: footer legal name (1 page)". Only for a brand's names; any other title as it is."""
    names = [detail_sentence(line) for line in detail_lines(entry) if line["kind"] in ("brand_name", "more")]
    return (entry.get("title") or "") + (": " + "; ".join(names) if names else "")


def _brand_id_name(f, url, m):
    for clash in (f.get("evidence") or {}).get("clashes") or []:
        for name, pages in (clash.get("names") or {}).items():
            if url in pages:
                return "brand_id_name", {"name": _cut(name)}
    return "brand_id_name", {}


def _date_future(f, url, m):
    row, more = _first(f, "dates", url)
    return "date_future", {"date": row.get("date"), "signal": row.get("signal"), **more}


def _dates_apart(f, url, m):
    return "dates_apart", {"limit": int(m.group("limit"))}


def _images(kind: str, field: str):
    """How many of the listed images are on this page. Said only when the list is whole (the title gives its total)."""
    def rule(f, url, m):
        # One row may stand for several images of one kind on the page (`count`: a flag for every row of a table).
        def images(found):
            return sum(int(row.get("count") or 1) if isinstance(row, dict) else 1 for row in found)

        rows = _rows(f, "images", url, field)
        whole = int(m.group("total")) <= images((f.get("evidence") or {}).get("images") or [])
        return kind, {"images": images(rows)} if rows and whole else {}
    return rule


def _div_grid(f, url, m):
    """The grid by the heading it sits under, else by a short name of its own ("div.price-list"), never the whole path
    (DECISIONS 223). A grid of a report saved before has neither: its old line, with the path."""
    row, more = _first(f, "grids", url)
    if row.get("heading"):
        return "div_grid_heading", {"heading": row["heading"], "first_row": row.get("first_row"), **more}
    return "div_grid", {"selector": row.get("label") or row.get("selector"), "first_row": row.get("first_row"), **more}


def _hreflang_status(f, url, m):
    row, more = _first(f, "links", url)
    values = {"hreflang": row.get("hreflang"), "target": row.get("target"), "status": row.get("status"), **more}
    if row.get("location"):
        return "hreflang_redirect", {**values, "location": _near(row["location"], url)}
    return "hreflang_status", values


def _hreflang_no_return(f, url, m):
    row, more = _first(f, "links", url)
    return "hreflang_no_return", {"hreflang": row.get("hreflang"), "target": row.get("target"), **more}


def _og_image_dead(f, url, m):
    row = _first(f, "images", url)[0]
    return "og_image_dead", {"image": row.get("og:image"), "status": row.get("status")}


def _entity_values(f, url, m):
    row, more = _first(f, "contradictions", url)
    field = row.get("field") or m.group("field")
    given = list(dict.fromkeys(", ".join(str(v) for v in d.get("value") or []) for d in row.get("descriptions") or []))
    given = [value for value in given if value]

    def shown(value: str) -> str:  # a date or a number as it is; any other text in quotation marks
        return value if re.fullmatch(r"[\d\-:.+TZ ]+", value) else f"“{_cut(value)}”"

    if len(given) == 2:
        return "entity_two_values", {"field": field, "first": shown(given[0]), "second": shown(given[1]), **more}
    if len(given) > 2:
        return "entity_many_values", {"field": field, "count": len(given), "values": ", ".join(shown(v) for v in given), **more}
    return "entity_two_values", {"field": field}


def _language_mismatch(f, url, m):
    row = _first(f, "pages", url)[0]
    return "language_mismatch", {"declared": row.get("declared"), "language": row.get("main_content_language")}


def _headings_language(f, url, m):
    row = _first(f, "pages", url)[0]
    return "headings_language", {"headings": row.get("headings_count"), "language": row.get("headings_language"), "declared": row.get("declared")}


def _template_markers(f, url, m):
    markers = list(dict.fromkeys(str(row.get("marker")) for row in _rows(f, "found", url) if row.get("marker")))
    if not markers:
        return "template_markers", {}
    return "template_markers", {"markers": ", ".join(markers[:3]), **({"more": len(markers) - 3} if len(markers) > 3 else {})}


def _link_count(kind: str):
    def rule(f, url, m):
        rows = _rows(f, "links", url, "source")
        if not rows or not _listed_all(f, "links", "count"):
            return kind, {}
        field = "links_with_generic_text" if kind == "links_generic" else "links"
        if any(not isinstance(row.get(field), int) for row in rows):
            return kind, {}  # legacy evidence lacks qualifying counts; do not borrow all anchors
        return kind, {"links": sum(row[field] for row in rows)}
    return rule


def _description_shared(f, url, m):
    group = next((g for g in (f.get("evidence") or {}).get("groups") or [] if url in (g.get("urls") or [])), None)
    count = (group or {}).get("count")
    return "description_shared", {"others": count - 1} if isinstance(count, int) and count > 1 else {}


def _links_no_address(f, url, m):
    return "links_no_address", {"links": _first(f, "by_page", url)[0].get("links")}


def _message_in_media(f, url, m):
    return "message_in_media", {"words": _first(f, "pages", url)[0].get("words_of_its_own")}


def _characters(kind: str):
    def rule(f, url, m):
        return kind, {"characters": _first(f, "items", url)[0].get("characters"), "limit": int(m.group("limit"))}
    return rule


def _heading_jumps(f, url, m):
    row = _first(f, "items", url)[0]
    pairs = Counter((jump.get("from"), jump.get("to")) for jump in row.get("examples") or [] if isinstance(jump, dict))
    if not pairs:
        return "heading_jumps", {}
    shown = ", ".join(f"H{before}→H{after}" + (f" ({many}×)" if many > 1 else "") for (before, after), many in pairs.items())
    left = int(row.get("jump_count") or 0) - sum(pairs.values())
    return "heading_jumps", {"jumps": shown, **({"more": left} if left > 0 else {})}


def _plain(kind: str):
    return lambda f, url, m: (kind, {})


# (check, a pattern its finding's title matches, the rule). First match wins; no match is the default, `affected`.
# A check keeps its titles in English in the report, so matching them is matching the engine's own words.
PAGE_RULES: tuple[tuple[str, str, Any], ...] = (
    ("IDX-1", r"return a server error \(5xx\)", _plain("status_5xx")),
    ("IDX-1", r"fail at the connection level", _plain("connection_fails")),
    ("IDX-1", r"time out on every attempt", _plain("times_out")),
    ("IDX-1", r"return a client error \(4xx\)", _status_4xx),
    ("IDX-3", r"redirect loop", _plain("redirect_loop")),
    ("IDX-3", r"intermittently redirect to themselves", _plain("redirect_intermittent")),
    ("IDX-3", r"redirected to themselves once|verification is incomplete", _plain("redirect_self_once")),
    ("IDX-3", r"loop (for visitors without cookies|in Maya)", _plain("redirect_loop")),
    ("IDX-3", r"redirect chain", _redirect_chain),
    ("IDX-3", r"redirect from https:// to an http:// address", _redirect_to_http),
    ("IDX-4", r"canonicalized to a URL with different content", _canonical_different),
    ("IDX-4", r"canonical that is broken, noindexed, or an error", _canonical_broken),
    ("IDX-4", r"declare conflicting canonicals", _plain("canonical_conflict")),
    ("IDX-6", r"^Link target returns ", _link_broken),
    ("IDX-6", r"carry tracking parameters", _links_tagged),
    ("IDX-6", r"point to another site", _links_other_site),
    ("IDX-7", r"listed only in the sitemap", _plain("orphan")),
    ("IDX-8", r"have identical visible text", _text_identical),
    ("IDX-8", r"share the title", _title_shared_idx8),
    ("IDX-8", r"nearly identical main content", _text_near_identical),
    ("IDX-8", r"copies or near-copies of each other", _duplicate_group),
    ("ACC-3", r"^(?P<label>.+) on \d+ page\(s\)$", _robots_directive),
    ("PRF-1", r"\(median\) to return their HTML", _slow_html),
    ("PRF-1", r"time out on some attempts", _counts("timeouts_some", "pages", "timeouts", "attempts")),
    ("PRF-2", r"failed on some attempts", _counts("fails_some", "pages", "failures", "attempts")),
    ("RND-1", r"^Main content is missing from the raw HTML", _content_after_js("content_after_js")),
    ("RND-1", r"^Part of the content", _content_after_js("content_partly_after_js")),
    ("RND-1", r"may be client-rendered", _plain("maybe_client_rendered")),
    ("RND-3", r"show more content only after a click or scroll", _revealed_words),
    ("RND-3", r"may hide content behind interaction", _plain("maybe_hidden_content")),
    ("RND-6", r"have HTML larger than", _kilobytes("html_large", "bytes")),
    ("RND-6", r"start their main content more than", _kilobytes("main_content_late", "main_offset_bytes")),
    ("RND-7", r"less than (?P<limit>\d+)% of their text in the main content", _main_share),
    ("STR-1", r"have no <title>", _plain("no_title")),
    ("STR-1", r"title\(s\) are shared by", _title_shared),
    ("STR-1", r"begin with the same \d+ characters", _title_same_start),
    ("STR-1", r"have a generic title", _title_generic),
    ("STR-2", r"have no <h1>", _plain("no_h1")),
    ("STR-2", r"The homepage has no <h1>", _plain("no_h1")),
    ("STR-3", r"The homepage has no Organization structured data", _plain("no_organization")),
    ("STR-2", r"have no subheadings", _no_subheadings),
    ("STR-3", r"JSON-LD that does not parse", _plain("jsonld_unparsed")),
    ("STR-3", r"structured data that returns an error", _markup_url_broken),
    ("STR-4", r"structured-data price differs from", _markup_price_differs),
    ("STR-4", r"structured-data (?P<field>.+?) differs from", _markup_differs),
    ("STR-5", r"brand @id\(s\) carry a different name", _brand_id_name),
    ("STR-6", r"carry a future date", _date_future),
    ("STR-6", r"date signals more than (?P<limit>\d+) days apart", _dates_apart),
    ("STR-7", r"^(?P<total>\d+) of \d+ sampled image file\(s\) do not load", _images("images_broken", "shown_on")),
    ("STR-7", r"^(?P<total>\d+) likely meaningful image\(s\)", _images("alt_missing", "url")),
    ("STR-8", r"pricing or spec comparisons as <div> grids", _div_grid),
    ("STR-8", r"contain an empty <table> element", _counts("table_empty", "pages", "tables")),
    ("STR-9", r"hreflang links to URLs that do not return 200", _hreflang_status),
    ("STR-9", r"hreflang links that are not returned", _hreflang_no_return),
    ("STR-9", r"<html lang> that does not match", _counts("lang_mismatch", "pages", "declared", "detected")),
    ("STR-10", r"og:image that returns 404/410", _og_image_dead),
    ("STR-11", r"same entity twice in structured data with a different (?P<field>.+)$", _entity_values),
    ("STR-12", r"mostly in another language than they declare", _language_mismatch),
    ("STR-12", r"section headings in another language", _headings_language),
    ("STR-12", r"placeholder or template text", _plain("placeholder_text")),
    ("STR-13", r"template markers", _template_markers),
    ("STR-14", r"only with generic text", _link_count("links_generic")),
    ("STR-14", r"have no text at all", _link_count("links_no_text")),
    ("STR-16", r"meta description\(s\) are shared by", _description_shared),
    ("STR-19", r"have no address a crawler can follow", _links_no_address),
    ("STR-20", r"carry their message in video or animation", _message_in_media),
    ("TSEO-1", r"page title\(s\) above the (?P<limit>\d+)-character", _characters("title_long")),
    ("TSEO-1", r"page title\(s\) below the (?P<limit>\d+)-character", _characters("title_short")),
    ("TSEO-1", r"meta description\(s\) above the (?P<limit>\d+)-character", _characters("description_long")),
    ("TSEO-1", r"meta description\(s\) below the (?P<limit>\d+)-character", _characters("description_short")),
    ("TSEO-1", r"heading level jump\(s\)", _heading_jumps),
)


def page_item(finding: dict[str, Any], url: str) -> dict[str, Any]:
    """What one finding is on one page: a `kind` from PAGE_KINDS and the page's own `values`, read from the finding as
    the report JSON holds it. A value the report does not hold is left out (the sentence then takes its plain form);
    the finding's site-wide count is never used as the page's. A finding no rule covers is `affected`."""
    evidence=finding.get('evidence') or {}
    if finding.get('check_id')=='STR-14' and evidence.get('link_observation_kind')=='generic_text':
        kind,values=_link_count('links_generic')(finding,url,None)
        return {'finding_id':finding.get('id'),'check_id':'STR-14','severity':finding.get('severity'),'kind':kind,'values':values}
    kind, values = "affected", None
    for check_id, pattern, rule in PAGE_RULES:
        if finding.get("check_id") != check_id:
            continue
        match = re.search(pattern, finding.get("title") or "")
        if match:
            try:
                kind, values = rule(finding, url, match)
            except (AttributeError, KeyError, TypeError, ValueError):  # evidence in a shape the rule does not know
                kind, values = "affected", None
            break
    if values is None:
        count = int((finding.get("scope") or {}).get("count") or 0)
        # An element shared by the pages of one section says its own page count in its title ("on 6 page(s) of /blog/"),
        # so the line does not add "site-wide: 6 pages" to it (DECISIONS 198).
        shared = isinstance((finding.get("evidence") or {}).get("shared_element"), dict)
        values = {"title": finding.get("title") or finding.get("id"), **({"count": count} if count > 1 and not shared else {})}
    return {"finding_id": finding.get("id"), "check_id": finding.get("check_id"), "severity": finding.get("severity"),
            "kind": kind, "values": {name: value for name, value in values.items() if value is not None}}


def page_form(item: dict[str, Any]) -> str:
    """"text" when the item holds every value its sentence needs, else "plain"."""
    text, plain = PAGE_KINDS.get(item["kind"]) or PAGE_KINDS["affected"]
    return "text" if plain is None or all(name in item["values"] for name in holes(text)) else "plain"


# Values that hold a language code ("en"); a sentence names the language ("English"). The report's JSON keeps the code.
LANGUAGE_VALUES = ("language", "declared", "detected")


def page_sentence(item: dict[str, Any]) -> str:
    """The English sentence for one item, as the Markdown report prints it."""
    from .language import NAMES

    text, plain = PAGE_KINDS.get(item["kind"]) or PAGE_KINDS["affected"]
    values = {name: NAMES.get(str(value).lower(), value) if name in LANGUAGE_VALUES else value for name, value in item["values"].items()}
    if isinstance(values.get("signals"), list):
        values["signals"] = signals_sentence(values)
    try:
        if page_form(item) == "plain":
            return phrase(plain, **values)
        return phrase(text, **values) + (phrase(MORE_ON_PAGE, more=values["more"]) if values.get("more") else "")
    except (KeyError, IndexError, ValueError):
        return plain or text


def with_page_items(summary: dict[str, Any], findings: list[dict[str, Any]], checks: list[Any] | None = None) -> dict[str, Any]:
    """`summary` with `items` on each page's row, for a report saved before schema 1.10; with `page_checks` counted
    from the report's `checks`; and with `files` and `whole_site.shared_elements` for one saved before they existed. A
    copy: the saved report is not changed. A finding the report no longer holds is left as `affected`, with its id for
    a title."""
    if checks is not None:
        # Counted again at display time, also for a report that holds the figure: a 1.11 report saved before the
        # count learned to read a check's own "looked at no page" evidence says more could run than did.
        summary = {**summary, "page_checks": page_checks(checks)}
    by_id = {finding["id"]: finding for finding in findings}
    if not all("items" in row for row in summary.get("by_page") or []):
        summary = {**summary, "by_page": [row if "items" in row else
                                          {**row, "items": [page_item(by_id.get(i) or {"id": i}, row["url"]) for i in row["finding_ids"]]}
                                          for row in summary["by_page"]]}
    # Stored page-items are derived presentation, not source evidence. Recalculate generic-only
    # counts from the retained qualifying fields, including reports written before this repair.
    if any(item.get("kind") == "links_generic" and item.get("finding_id") in by_id
           for row in summary.get("by_page", []) for item in row.get("items", [])):
        summary = {**summary, "by_page": [{**row, "items": [
            page_item(by_id[item["finding_id"]], row["url"])
            if item.get("kind") == "links_generic" and item.get("finding_id") in by_id else item
            for item in row.get("items", [])]} for row in summary.get("by_page", [])]}
    if "files" not in summary:  # saved before files were listed apart: a sitemap document is not a page
        summary = {**summary, "by_page": [row for row in summary["by_page"] if not non_page_kind(row["url"])],
                   "files": [row for row in summary["by_page"] if non_page_kind(row["url"])]}
    if "shared_elements" not in (summary.get("whole_site") or {}):
        summary = {**summary, "whole_site": {**summary["whole_site"], "shared_elements": shared_elements_of(
            [by_id[i] for i in summary["whole_site"].get("finding_ids") or [] if i in by_id])}}
    return summary


def _counted(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


HEADLINE_LIMITED = "Only {could_run} of {total} page checks could run, so this is not a clean result."
HEADLINE_LIMITED_NONE = "The {could_run} that ran found no problems on {pages}"


def headline(summary: dict[str, Any]) -> str:
    """"15 problems found on 50 pages (1 high, 5 medium, 9 low) + 12 notes": every problem, not only the worst.

    When fewer than half of the page checks could run (`page_checks.limited`), that is said first: "Only 16 of 41
    page checks could run, so this is not a clean result." A short list of problems is then not read as a clean site."""
    pages = _counted(summary["pages_checked"], "page")
    ran = summary.get("page_checks") or {}
    limited = HEADLINE_LIMITED.format(**ran) if ran.get("limited") else ""
    if summary["problems"]:
        levels = ", ".join(f"{summary['by_severity'][level]} {SEVERITY_WORDS[level]}" for level in PROBLEM_SEVERITIES
                           if summary["by_severity"].get(level))
        text = f"{_counted(summary['problems'], 'problem')} across assessed scope; {pages} read for content" + (f" ({levels})" if levels else "")
    elif limited:
        text = HEADLINE_LIMITED_NONE.format(could_run=ran["could_run"], pages=pages)
    else:
        text = f"No problems found on {pages}"
    text = (limited + " " if limited else "") + text + (f" + {_counted(summary['notes'], 'note')}" if summary["notes"] else "")
    # A single-page audit says what it did not look at, in the same line as its count.
    text += ". " + single_page.ONLY_THIS_PAGE if summary.get("single_page") else ""
    # A start address that answered with an error is said before any count: the pages counted are not the one typed.
    failed = start_failed_line(summary.get("start_address"))
    return f"{failed} {text}" if failed else text


def problems_by_page_lines(summary: dict[str, Any], titles: dict[str, str], origin: str, limit: int | None = BY_PAGE_ROWS) -> list[str]:
    """The "Problems by page" section of the Markdown report: at most `limit` pages (CR-13; None for all), the rest
    named by count and left to the JSON's `problem_summary.by_page`. Empty when there is no problem to list."""
    whole_label = single_page.SITE_LEVEL if summary.get("single_page") else whole_row_label(summary)
    rows = ([{"page": whole_label, **summary["whole_site"]}] if summary["whole_site"]["problems"] else []) + [
        {"page": f"`{_short(row['url'], origin)}`", **row} for row in summary["by_page"]]
    files = [{"page": f"`{_short(row['url'], origin)}`", **row} for row in summary.get("files") or []]
    if not rows and not files and not summary["not_listed"]:
        return []

    def cell(text: str) -> str:
        return str(text).replace("|", "\\|").replace("\n", " ")

    lines = ["## Problems by page", ""]

    # The whole site keeps each problem's own title; a page says what is wrong on that page, with its own numbers.
    def wrong(row: dict[str, Any]) -> str:
        # Two findings can say the same thing about a page (a shared title is seen by two checks): said once.
        if row.get("items"):
            return "; ".join(dict.fromkeys(page_sentence(item) for item in row["items"]))
        return "; ".join(dict.fromkeys(titles.get(i, i) for i in row["finding_ids"]))

    if rows:
        # At most BY_PAGE_ROWS pages (CR-13); the whole-site row is not a page and is always shown.
        whole = 1 if rows[0]["page"] == whole_label and summary["whole_site"]["problems"] else 0
        shown, more = rows[:whole + limit] if limit else rows, max(0, len(rows) - whole - limit) if limit else 0
        lines += [f"| Page | Problems | Worst severity | {BY_PAGE_COLUMN} |", "|---|---|---|---|"]
        lines += [f"| {cell(row['page'])} | {row['problems']} | {SEVERITY_DEFINITIONS[row['worst_severity']].partition(':')[0]} | "
                  f"{cell(wrong(row))} |" for row in shown]
        lines.append("")
        if more:
            lines += [phrase(BY_PAGE_MORE, n=more), ""]
    if files:  # not pages: listed under the table, never as rows of it
        lines += [f"**{FILES_TITLE}**", "", f"| File | Problems | Worst severity | {FILES_COLUMN} |", "|---|---|---|---|"]
        lines += [f"| {cell(row['page'])} | {row['problems']} | {SEVERITY_DEFINITIONS[row['worst_severity']].partition(':')[0]} | "
                  f"{cell('; '.join(titles.get(i, i) for i in row['finding_ids']))} |" for row in files]
        lines.append("")
    for entry in summary["not_listed"]:
        lines += [NOT_LISTED_LINE.format(title=titles.get(entry["finding_id"], entry["finding_id"]),
                                         pages=_counted(entry["pages"], "more page")), ""]
    return lines + [BY_PAGE_NOTE, ""]


def write_json(report: dict[str, Any], path: str, overwrite: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)


POINTER = ("The audit is supplied alongside this prompt as the `{key}` object. Read it there; do not "
           "assume any value that is not in it.")
# Everything a report holds about the crawl itself. It is the bulk of the file (5.17 MB of a real
# 5.3 MB report) and none of it is what a document is written from: page bodies, every discovered
# URL, every sitemap lastmod. The findings already quote what they rely on.
CRAWL_SUMMARY_KEYS = ("start_url", "origin", "user_agent", "product_token", "started_at", "finished_at",
                      "elapsed_s", "stop_reason", "stop_detail")


def analysis_payload(report: dict[str, Any]) -> dict[str, Any]:
    """The report with the raw crawl dump replaced by a summary of it.

    A real 50-page report is 5.3 MB, of which 5.17 MB is `crawl` — far past what a model can read,
    and none of it is evidence a finding cites: each finding already carries the values it rests on.
    What survives is the method detail the report's own "Method" section needs.
    """
    crawl = report.get("crawl") or {}
    summary = {key: crawl[key] for key in CRAWL_SUMMARY_KEYS if key in crawl}
    if isinstance(crawl.get("config"), dict):
        config = crawl["config"]
        summary["config"] = {key: config[key] for key in ("max_pages", "request_delay_s", "bot_info_url",
                                                          "key_pages", "allowed_live_hosts") if key in config}
    summary["omitted"] = ("Page bodies, discovered URLs, sitemap entries and per-request logs are in the full "
                          "evidence report, not here. Every finding quotes the values it relies on.")
    out = {**{k: v for k, v in report.items() if k != "crawl"}, "crawl_summary": summary}

    def compact(finding: dict) -> dict:
        # DECISIONS 347: each page's own step for the links to a redirect repeats the evidence's targets (old address ->
        # final address); the appendix reads it, the brief does not need it.
        ev = finding.get("evidence")
        if isinstance(ev, dict) and "page_fixes" in ev:
            finding = {**finding, "evidence": {k: v for k, v in ev.items() if k != "page_fixes"}}
        # Each affected page's kind repeats its address; the brief needs how many pages of each kind (DECISIONS 278).
        kinds = finding.get("page_types")
        if not isinstance(kinds, dict):
            return finding
        counts: dict[str, int] = {}
        for kind in kinds.values():
            counts[kind] = counts.get(kind, 0) + 1
        return {**finding, "page_types": counts}
    for key in ("checks", "answer_engine_panel"):
        if isinstance(out.get(key), list):
            out[key] = [{**c, "findings": [compact(f) for f in c.get("findings") or []]} if isinstance(c, dict) else c
                        for c in out[key]]
    if isinstance(report.get("release_gate"), dict):
        # The decision and its counts; the full violation list stays in the evidence report (DECISIONS 278).
        out["release_gate"] = {k: report["release_gate"].get(k) for k in ("version", "decision", "counts", "high_not_retested")}
    return out


def _brand_name(result: CrawlResult) -> str:
    """A label for prose, not an identity claim: the registrable domain, minus its suffix."""
    # urlsplit().hostname drops the port and lowercases; netloc keeps both, and "127.0.0.1:8000"
    # then reduces to nonsense.
    host = registrable_domain(urlsplit(result.origin).hostname or "")
    return host.split(".")[0] if host else result.origin


def build_llm_brief(report: dict[str, Any], result: CrawlResult, skills: list[str] | None = None,
                    brand_name: str | None = None, inline: bool = False) -> dict[str, Any]:
    """Pair the finished report with the prompts that turn it into a readable document.

    Deliberately *not* part of `build_report`. The report is the evidence file: it is what a
    finding cites, what gets diffed between runs, and what someone re-reads in a year. Prompt text
    is instructions to a model, it is far larger than the findings it wraps, and it changes
    whenever the wording is improved. Mixing the two would mean every report diff filled with
    prose edits, and a reader unable to tell measured evidence from instructions about how to
    describe it.

    A skill whose data is absent is returned with `prompt: None` and the missing keys named, never
    rendered against empty placeholders — an empty section reads as "nothing to report", which is
    the same mistake as showing a `not_assessed` check as a pass.
    """
    chosen = skills or skill_names()
    unknown = [name for name in chosen if name not in SKILLS]
    if unknown:
        raise ValueError(f"unknown skill(s): {', '.join(unknown)}; available: {', '.join(skill_names())}")

    brand = brand_name or _brand_name(result)
    from .ai_skills.payload import budgeted_payload  # lists bounded, data fence neutralised (review E-R1/E-R2)
    audit = budgeted_payload(analysis_payload(report))
    if inline:
        audit_section = "```json\n" + json.dumps(audit, indent=2, ensure_ascii=False) + "\n```"
        panel_section = ("```json\n"
                         + json.dumps(audit.get("answer_engine_panel", []), indent=2, ensure_ascii=False) + "\n```")
    else:
        audit_section = POINTER.format(key="audit")
        panel_section = POINTER.format(key="audit.answer_engine_panel")

    briefs = []
    for name in chosen:
        skill = SKILLS[name]
        reasons = skill.unavailable(report)
        missing = list(reasons)
        prompt = None if missing else skill.render(brand_name=brand, site_url=result.origin,
                                                   audit_section=audit_section, panel_section=panel_section)
        briefs.append(to_jsonable(SkillBrief(skill_name=name, goal=skill.goal, prompt=prompt, missing=missing,
                                             missing_reasons=reasons)))

    return {
        "brief_version": "0.2",  # 0.2: page text fenced as data, bounded payload, output contract (W5)
        "generated_for": result.origin,
        "brand_name": brand,
        "report_version": report.get("report_version"),
        # Restated here because a brief may be handed to a model on its own, without the report.
        "how_to_use": ("Each entry pairs a goal with a prompt. Send one prompt, together with the `audit` "
                       "object in this file, to a model to get that document. A prompt of null means the "
                       "audit did not collect what that skill needs; the missing keys are listed, and "
                       "the right response is to say so, not to run the skill anyway."),
        "audit": None if inline else audit,
        "skills": briefs,
    }


def write_llm_brief(brief: dict[str, Any], path: str, overwrite: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as fh:
        json.dump(brief, fh, indent=2, ensure_ascii=False)


EXIT_COMPLETED, EXIT_DEGRADED, EXIT_ERROR, EXIT_INCOMPLETE = 0, 1, 2, 3
_DEGRADED_STOPS = {"rate_limit", "error", "robots_disallowed", "network_problem"}


# Which checks depend on which data collector (maya_audit.audit), for saying what a time limit cut.
COLLECTOR_CHECKS = {"access": ("ACC-",), "index": ("IDX-",), "structure": ("STR-", "TSEO-"), "render": ("RND-",),
                    "performance": ("PRF-",), "sitemap_check": ("IDX-5", "ACC-8"), "citations": ("ANS-",),
                    "citation_domains": ("ANS-",)}


def time_limit_cuts(result: CrawlResult, checks: list[CheckResult] | None) -> list[dict[str, Any]]:
    """What the time limit cost, one row per data collector it stopped: which checks did not run, which ran short."""
    rows = []
    for name, message in result.collector_errors.items():
        if name not in COLLECTOR_CHECKS or "deadline" not in message:
            continue
        family = [c for c in checks or [] if c.check_id.startswith(COLLECTOR_CHECKS[name])]
        # A check that is "not assessed" for a reason of its own (no access logs, no structured data) is in neither list.
        lost = [c for c in family if c.status == "not_assessed"
                and ("collector_error" in (c.evidence or {}) or "deadline" in c.summary.lower())]
        rows.append({"collector": name, "reason": message, "checks_not_run": [c.check_id for c in lost],
                     "checks_run_on_fetched_pages_only": [c.check_id for c in family if c.status != "not_assessed"]})
    return rows


def time_limit_lines(result: CrawlResult, checks: list[CheckResult] | None) -> list[str]:
    """Plain sentences for the top of a report when the time limit was reached. Empty when it was not."""
    cuts = time_limit_cuts(result, checks)
    stopped = getattr(result, "stopped", False)
    # Which optional steps gave way to the time limit (DECISIONS 219), in one sentence.
    skipped = timeplan.skipped_note(getattr(result, "skipped_for_time", None))
    if not (cuts or result.deadline_hit or stopped):
        return [skipped] if skipped else []
    limit = result.config.get("time_limit_s") if isinstance(result.config, dict) else None
    lines = [f"The audit reached its time limit{f' of {limit:g} seconds' if isinstance(limit, (int, float)) else ''}. "
             "Run it again with a larger --time-limit for complete results."]
    if stopped:
        # A stop ends the run the way the deadline does, so the checks below word it as "deadline reached".
        lines = ["The audit was stopped on request before it finished. The pages already fetched were checked; "
                 "whatever needed another request is reported as not checked (worded below as \"deadline reached\"). "
                 "Resume the audit for complete results."]
    if skipped and not stopped:
        lines.append(skipped)
    if not cuts:
        lines.append("Every check still ran; some of their extra requests were not sent (see each check's coverage).")
    for cut in cuts:
        short = cut["checks_run_on_fetched_pages_only"]
        if cut["checks_not_run"]:
            lines.append(f"Not run ({cut['collector']} data: {cut['reason']}): {', '.join(cut['checks_not_run'])}.")
        if short:
            lines.append(f"Run on the pages already fetched, without {'rendering' if cut['collector'] == 'render' else 'their extra requests'} "
                         f"({cut['collector']} data: {cut['reason']}): {', '.join(short)}.")
    return lines


def page_counts(result: CrawlResult) -> tuple[int, int]:
    """(pages checked, redirects followed). A redirect is a fetch but not a page, and is not counted against the page cap."""
    redirects = sum(1 for page in result.pages if page.status is not None and 300 <= page.status < 400)
    return len(result.pages) - redirects, redirects


def pages_phrase(result: CrawlResult) -> str:
    """"10 pages + 1 redirect": what the page cap counts, and the redirect hops beside it."""
    pages, redirects = page_counts(result)
    return f"{pages} page{'' if pages == 1 else 's'}" + (f" + {redirects} redirect{'' if redirects == 1 else 's'}" if redirects else "")


def readable_pages(result: CrawlResult, firecrawl: dict | None) -> str | None:
    """"6 (read through Firecrawl; Maya's own crawler was blocked)", when Firecrawl supplied page content.

    Counts each page once (`read_counts`), and says what else was fetched that is not a page. Maya's own crawl stays
    the access test: this says who read the pages, it does not undo the block."""
    if not firecrawl or not firecrawl.get("used") or not firecrawl.get("pages_read"):
        return None
    counts = read_counts(result, firecrawl)
    by = counts["read_by"]
    through = by["firecrawl"] or firecrawl["pages_read"]
    total = counts["pages"] or through
    also = also_fetched(counts["other_addresses"])
    also = f". {also.rstrip('.')}" if also else ""  # a line of its own in a list: the caller ends it
    if firecrawl.get("purpose") == "main page reader":
        only_own = by["maya_only"]
        return (f"{total} (via Firecrawl)" if not only_own else f"{total} ({through} via Firecrawl, {only_own} by Maya's own crawler)") + also
    live = by["maya_only"] + by["both"]
    how = (f"{through} read through Firecrawl; Maya's own crawler read {live} and was blocked on the rest" if live
           else "read through Firecrawl; Maya's own crawler was blocked")
    return f"{total} ({how})" + also


def known_unread(result: CrawlResult, firecrawl: dict | None) -> int:
    """How many addresses are known and unread: one figure for every sentence. When a reader read pages, it is the
    reader's count, which already leaves out what the reader read of the addresses Maya's own crawl did not fetch."""
    section = firecrawl or {}
    if section.get("used") and any(row.get("outcome") == "read" for row in section.get("pages") or []):
        counted = (section.get("coverage") or {}).get("known_urls_not_requested", 0)
        if (section.get("options") or {}).get("read_scope") == "needed":
            # DECISIONS 335: a reader that read only where needed (DECISIONS 327/329) never asks the addresses Maya did
            # not fetch, so its own count is no answer: Maya's unread addresses, less any the reader read.
            read = {row.get("url") for row in section.get("pages") or [] if row.get("outcome") == "read"}
            return max(counted, sum(1 for u in result.not_fetched_urls if u not in read))
        return counted
    return len(result.not_fetched_urls)


# What a check that found nothing says when not every page found was read (decision 189; which check:
# `coverage.clean_on_what_was_read`). `n` and `m` are the report's one pair: `read_counts(...)["pages"]` and
# `known_unread(...)`. The web layer words the same two sentences through its `result.clean_on_read` strings.
CLEAN_ON_READ = "No problem found on the {n:page|pages} read ({m} not read)"
CLEAN_ON_READ_CUT = "No problem found on the {n:page|pages} read (the reading was cut short)"


def clean_on_read_sentence(read: int, unread: int) -> str:
    return phrase(CLEAN_ON_READ, n=read, m=unread) if unread else phrase(CLEAN_ON_READ_CUT, n=read)


ALLOWANCE = "the page reader used all {n} page requests this audit allows and read {m:page|pages}"
ALLOWANCE_ELSEWHERE = "; {k:request|requests} led to pages already read or to missing pages"
LEFT_OUT = "+{n:address|addresses} left out: disallowed by robots.txt or not a page"
_ALLOWANCE_REFUSAL = re.compile(r"the Firecrawl (?:page cap|request allowance) of \d+ for this audit is (?:reached|used)")


def allowance_sentence(firecrawl: dict | None) -> str | None:
    """The one sentence for a reading that ended because its request allowance was used: "the page reader used all 51
    page requests this audit allows and read 43 pages; 8 requests led to pages already read or to missing pages".
    None for any other stop. What is counted, and paid for, is requests: one that redirects to a page already read, or
    finds no page, is spent all the same. A report saved before `not_requested_because` could say
    "request_allowance_used" is recognised by the client's own refusal ("the Firecrawl page cap of 50 ... is reached")."""
    section = firecrawl or {}
    coverage = section.get("coverage") or {}
    if not (coverage.get("not_requested_because") == "request_allowance_used"
            or _ALLOWANCE_REFUSAL.search(section.get("stopped_because") or "")):
        return None
    read = int(section.get("pages_read") or 0)
    sent = coverage.get("page_requests")
    if sent is None:  # saved before the reader counted them: every request but the one for robots.txt was for a page
        asked_robots = (section.get("robots") or {}).get("source") not in (None, "Maya's own crawler")
        sent = max(read, int(section.get("requests_sent") or 0) - int(asked_robots))
    elsewhere = coverage.get("requests_without_a_new_page")
    elsewhere = max(0, sent - read) if elsewhere is None else elsewhere
    return phrase(ALLOWANCE, n=sent, m=read) + (phrase(ALLOWANCE_ELSEWHERE, k=elsewhere) if elsewhere else "")


# A provider's own error text can run to a paragraph ("Request timed out ... try increasing the timeout parameter ...").
# A summary or a coverage sentence says what happened in a few words, by the HTTP status the provider answered (H19); the
# provider's own text stays in the report's `firecrawl` section (`stopped_because`, `errors`), where evidence is read.
PROVIDER_STATUS_REASONS = {408: "the page reader timed out", 504: "the page reader timed out",
                           429: "the page reader's own rate limit was reached", 402: "the page reader's account has no credit",
                           401: "the page reader refused the request", 403: "the page reader refused the request"}
PROVIDER_STATUS_OTHER = "the page reader returned no document"
PROVIDER_STATUS_5XX = "the page reader could not load the page"
PROVIDER_REASON = "{reason} (HTTP {status})"
_PROVIDER_STATUS = re.compile(r"\(HTTP (?P<status>\d{3})\)")
PROVIDER_REASON_MAX = 160


def provider_reason(text: str | None) -> str:
    """Why a page reader stopped, in one short sentence. A provider's error ("Firecrawl returned no document (HTTP 408):
    <the provider's own paragraph>") is said by its status: "the page reader timed out (HTTP 408)". Maya's own stop
    sentences ("the last 5 pages asked for came back unreadable, so no more were requested") are kept as they are; any
    other long text keeps its first clause."""
    text = " ".join(str(text or "").split())
    found = _PROVIDER_STATUS.search(text)
    if found and (text.startswith("Firecrawl") or len(text) > PROVIDER_REASON_MAX):
        status = int(found.group("status"))
        reason = PROVIDER_STATUS_REASONS.get(status) or (PROVIDER_STATUS_5XX if status >= 500 else PROVIDER_STATUS_OTHER)
        return PROVIDER_REASON.format(reason=reason, status=status)
    if len(text) <= PROVIDER_REASON_MAX:
        return text
    first = re.split(r"(?<=[.:;])\s", text, maxsplit=1)[0].rstrip(".:;")
    return first if len(first) <= PROVIDER_REASON_MAX else first[:PROVIDER_REASON_MAX - 1].rstrip() + "…"


def reader_gaps(firecrawl: dict | None) -> list[str]:
    """Why a reader's sample is not the whole of what was found: one phrase per reason, empty when there is none."""
    section = firecrawl or {}
    coverage = section.get("coverage") or {}
    gaps = []
    allowance = allowance_sentence(section)
    if allowance:
        # One sentence for one stop: what was allowed, what was read, and where the other requests went. Neither
        # "reading stopped early" nor "a credit or request limit" is said beside it (DECISIONS 170).
        gaps.append(allowance)
    elif section.get("stopped_because"):
        gaps.append(f"reading stopped early ({provider_reason(section['stopped_because'])})")
    waiting = coverage.get("known_urls_not_requested") or 0
    skipped = coverage.get("skipped_for_time") or 0
    if skipped and not allowance:
        # The time limit came first (DECISIONS 294): how many, and the pace the reader measured, not an assumed one.
        pace = coverage.get("seconds_per_page_measured")
        gaps.append(f"{skipped} page(s) were not read for lack of time" + (
            f" (the page reader measured {float(pace):.1f} s a page)" if pace else ""))
    elif waiting and not allowance:
        because = {"time_limit": "the time limit was reached", "stopped_on_request": "the audit was stopped",
                   "reader_kept_failing": "the reader kept getting unreadable answers",
                   "credit_or_request_limit": "a credit or request limit was reached"}.get(coverage.get("not_requested_because") or "")
        gaps.append(f"{waiting} more discovered URL(s) remain unchecked" + (
            f" (the page cap of {coverage.get('page_cap')} was reached)" if coverage.get("cap_reached") else f" ({because})" if because else ""))
    left_out = sum(int(count or 0) for count in (coverage.get("unread_left_out") or {}).values())
    if left_out and waiting:
        gaps.append(phrase(LEFT_OUT, n=left_out))
    failed = coverage.get("requested_without_a_readable_document") or 0
    if failed:
        # Why, in the reader's own words for each page: a challenge, another site, an empty document, a provider failure.
        named = {name: count for name, count in (coverage.get("causes") or {}).items()
                 if name not in ("error_status", "redirect_within_the_site")}
        why = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in sorted(named.items()))
        gaps.append(f"{failed} requested URL(s) gave no readable document" + (f" ({why})" if why else ""))
    timeouts = coverage.get("timeouts") or {}
    if timeouts.get("skipped"):
        # Calls that timed out (DECISIONS 295): each such page was asked for once more, then skipped; the counts.
        gaps.append(TIMEOUTS_PHRASE.format(read=int(coverage.get("read") or 0), retried=int(timeouts.get("retried") or 0),
                                           skipped=int(timeouts["skipped"])))
    missing = coverage.get("key_pages_not_read") or []
    if missing:
        gaps.append(f"{len(missing)} key page(s) were not read")
    return gaps


TIMEOUTS_PHRASE = "Firecrawl: {read} page(s) read, {retried} retried after a timeout, {skipped} skipped"


def coverage_note(level: str, pages: int) -> str:
    return {"none": "No page content could be read.",
            "partial": f"{pages} page(s) were read; additional discovered URLs remain unchecked or a step did not finish.",
            "complete_sample": f"{pages} page(s) were read: every address found within the audit's scope. That is "
                               "the sample this audit could discover, not proof about pages it never found."}[level]


_READER_REASONS = re.compile(r"^(?:reading stopped early \(|Firecrawl: \d+ page\(s\) read, |\d+ more discovered URL\(s\) remain unchecked|\d+ page\(s\) were not read for lack of time|\d+ requested URL\(s\) gave no readable document|"
                             r"\d+ key page\(s\) were not read|the page reader used all |\+\d+ address)")


def content_coverage_shown(report: dict[str, Any]) -> dict[str, Any]:
    """The report's `audit_status.content_coverage` as it is displayed. A report that holds `pages_read` (schema 1.11
    from team-preview-11 run 2) is shown as it is. An older one counted addresses and listed up to three stop reasons;
    the same engine functions are applied to its own `crawl` and `firecrawl` sections, so it shows pages, three
    disjoint `read_by` numbers and one stop sentence. A copy: the saved report is not changed. None for a report with
    no such section (before schema 1.6)."""
    saved = ((report.get("audit_status") or {}).get("content_coverage"))
    if not isinstance(saved, dict) or "pages_read" in saved:
        return saved if isinstance(saved, dict) else None
    section = report.get("firecrawl") or {}
    counts = read_counts(report.get("crawl") or {}, section)
    reasons = list(saved.get("reasons") or [])
    if counts["read_by"]["firecrawl"]:
        main = section.get("purpose") == "main page reader"
        reasons = reader_gaps(section) + [text for text in reasons if not _READER_REASONS.match(text)
                                          and not (main and text.startswith("Maya's crawl stopped: page_cap "))]
    level = saved.get("level") if saved.get("level") in ("none", "partial", "complete_sample") else "partial"
    if level != "none":
        level = "partial" if reasons else "complete_sample"
    also = also_fetched(counts["other_addresses"])
    return {**saved, "level": level, "pages_read": counts["pages"], "readable_unique_urls": counts["pages"],
            "read_by": counts["read_by"], "other_addresses": counts["other_addresses"], "reasons": reasons,
            "note": coverage_note(level, counts["pages"]) + (" " + also if also else "")}


def audit_status(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult] | None = None,
                 firecrawl: dict | None = None) -> dict[str, Any]:
    """Four separate answers that must not be read as one: whether Maya's own requests got in, how much content was
    read and through whom, what is known about the AI vendors' own crawlers, and the sentence that says all three.

    A finished job is not a complete audit; content read through a reader is not access; a user-agent probe is not
    a vendor's crawler. Each is its own field so no interface has to infer one from another."""
    checks = checks or []
    pages = [p for p in result.pages if not (p.status is not None and 300 <= p.status < 400)]
    by_class = {name: sum(1 for p in pages if p.fetch_class.value == name) for name in ("ok", "blocked", "rate_limited", "error")}
    int1 = next((g for g in gates if g.check_id == "INT-1"), None)
    if not pages:
        direct = "unknown"
    elif int1 is not None and int1.state == "degraded":
        direct = "rate_limited" if by_class["rate_limited"] > by_class["blocked"] else "challenged"
    else:
        direct = "readable" if by_class["ok"] else "unknown"
    direct_note = {"readable": f"Maya's direct crawler was let in ({by_class['ok']} of {len(pages)} page request(s) answered by the site itself"
                               + (f"; {by_class['blocked'] + by_class['rate_limited']} blocked or rate-limited" if by_class["blocked"] + by_class["rate_limited"] else "") + ").",
                   "challenged": f"Maya's direct crawler was challenged or blocked on {by_class['blocked']} of {len(pages)} page request(s).",
                   "rate_limited": f"Maya's direct crawler was rate-limited on {by_class['rate_limited']} of {len(pages)} page request(s).",
                   "unknown": "Maya's direct crawler requested no page, so direct access is unknown."}[direct]
    from . import maya_blocked
    blocked_429 = direct == "rate_limited" and maya_blocked.holds(result)  # DECISIONS 288: a block on Maya's crawler
    if blocked_429:
        direct_note = (f"Maya's direct crawler was blocked (429 on pages) on {by_class['rate_limited']} of {len(pages)} page "
                       "request(s), while robots.txt and the sitemap were served.")
    if not pages and result.stop_reason.value == "network_problem":
        # No answer reached this computer: said as that, never as something the site did.
        direct_note = f"Direct access was not measured: {result.stop_detail}."

    section = firecrawl or {}
    counts = read_counts(result, firecrawl)
    by, readable = counts["read_by"], counts["pages"]
    through = by["firecrawl"]
    reader_cover = section.get("coverage") or {}
    if blocked_429 and through:  # said plainly, with what was read instead (DECISIONS 288)
        direct_note = (f"Maya's own crawler was blocked (429 on pages) on {by_class['rate_limited']} of {len(pages)} page "
                       f"request(s); {through} page(s) read through Firecrawl.")
    reasons = reader_gaps(section) if through else []
    if result.not_fetched_urls and not through:
        reasons.append(f"{len(result.not_fetched_urls)} discovered URL(s) were not fetched")
    stop = result.stop_reason.value
    # When the page reader is the audit's main reader, what was left unread is the reader's to say, once: the page cap
    # of Maya's own crawl is not a second reason beside it (it stays in `crawl.stop_reason`).
    said_by_reader = bool(through) and section.get("purpose") == "main page reader" and stop == "page_cap"
    if stop not in ("exhausted",) and not (through and direct in ("challenged", "rate_limited")) and not said_by_reader:
        reasons.append(f"Maya's crawl stopped: {stop} ({result.stop_detail})")
    if getattr(result, "stopped", False):
        reasons.append("the audit was stopped on request")
    if result.deadline_hit:
        reasons.append("the time limit was reached")
    if known_unread(result, firecrawl) and through and not reasons:
        reasons.append(f"{known_unread(result, firecrawl)} more discovered URL(s) remain unchecked")
    level = "none" if not readable else "partial" if reasons else "complete_sample"
    also = also_fetched(counts["other_addresses"])
    coverage = {"level": level,
                # Pages, not addresses (`read_counts`): the one figure every output prints. `readable_unique_urls` is the
                # name it had before schema 1.11 and holds the same number.
                "pages_read": readable, "readable_unique_urls": readable, "read_by": by, "other_addresses": counts["other_addresses"],
                "page_requests_by_maya": len(pages), "discovered_urls": len(result.discovered_urls),
                "known_urls_not_read": known_unread(result, firecrawl),
                # Known addresses that are not in that figure: robots.txt disallows them, or they are files, not pages.
                "unread_left_out": dict(reader_cover.get("unread_left_out") or {"robots_disallowed": 0, "not_a_page": 0}) if through
                else {"robots_disallowed": 0, "not_a_page": 0},
                "key_pages_not_read": reader_cover.get("key_pages_not_read") or [], "reasons": reasons,
                "note": (single_page.COVERAGE if single_page.is_single(result) and level == "complete_sample"
                         else coverage_note(level, readable) + (" " + also if also else ""))}

    by_id = {c.check_id: c for c in checks}
    logs, probe = by_id.get("ACC-5"), by_id.get("ACC-4")
    if logs is not None and logs.status not in ("not_assessed",):
        vendor, vendor_note = "verified_log_evidence", "Server logs supplied with the audit show which crawlers really visited (ACC-5)."
    elif probe is not None and probe.status not in ("not_assessed",):
        vendor, vendor_note = "limited_user_agent_probe", (
            "Requests were sent under AI and search crawlers' names from Maya's own network (ACC-4). That shows how the site treats "
            "those names from an unknown address; it is not the vendors' own crawlers, and ownership verification is permission to "
            "run the test, not proof of a crawler's identity.")
    else:
        vendor, vendor_note = "not_measured", "Genuine AI-crawler access was not measured."
    status = {"direct_access": {"state": direct, "note": direct_note, "page_requests": len(pages), "by_response": by_class},
              "content_coverage": coverage, "vendor_crawler_evidence": {"state": vendor, "note": vendor_note}}
    status['summary'] = read_status_summary(status, counts)
    return status


def read_status_summary(status, counts):
    """The same readable-document summary for fresh results and explicit offline copies."""
    by = counts['read_by']; through, readable = by['firecrawl'], counts['pages']
    read_line = (f"We read {through} page(s) through Firecrawl" + (f" and {by['maya_only']} with Maya's own crawler" if by['maya_only'] else "") + "."
                 if through else f"Maya's own crawler read {readable} page(s)." if readable else "No page content was read.")
    direct = status['direct_access']
    direct_note = direct['note']
    if through:  # "We read N page(s) through Firecrawl." is said first: the direct note does not say it again (DECISIONS 299)
        direct_note = direct_note.replace(f"; {through} page(s) read through Firecrawl.", ".")
    return " ".join([read_line, direct_note if direct['state'] != 'readable' or not through else '',
                     status['vendor_crawler_evidence']['note'], status['content_coverage']['note']]).replace("  ", " ").strip()


def coverage_lines(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult] | None, firecrawl: dict | None) -> list[str]:
    """What this audit covers, as the same sentences every output shows: how Maya's own requests were answered, how
    much content was read and through whom, what is known about real AI crawlers, and how old any saved copy is."""
    status = audit_status(result, gates, checks, firecrawl)
    lines = [f"Direct access (Maya's own crawler): {status['direct_access']['note']}",
             f"Content coverage: {status['content_coverage']['note']}"
             + (" Reasons: " + "; ".join(status["content_coverage"]["reasons"]) + "." if status["content_coverage"]["reasons"] else ""),
             f"Real AI crawlers: {status['vendor_crawler_evidence']['note']}"]
    cached = cache_note(firecrawl)
    if cached:
        lines.append(cached)
    return lines


def cache_note(firecrawl: dict | None) -> str | None:
    """How many of the reader's pages came from Maya's saved copies, and from when. None when all were read afresh."""
    rows = [row for row in (firecrawl or {}).get("pages") or [] if row.get("outcome") == "read"]
    saved = sorted(str(row.get("observed_at") or "") for row in rows if row.get("from_cache"))
    if not saved:
        return None
    return (f"Saved copies: {len(saved)} of the {len(rows)} page(s) read through Firecrawl came from Maya's own saved copies, the oldest "
            f"made {saved[0][:16].replace('T', ' ')} UTC. The site may have changed since; a new audit after a day reads it again.")


# A wall-clock gap this much larger than the audit's own (awake) time is said as sleep (DECISIONS 295, agent default).
SLEEP_NOTE_MIN_S = 120.0
SLEEP_NOTE = ("The computer slept for about {minutes} min during this audit; the durations count only the time it was "
              "awake.")


def sleep_note(slept_s: float | None) -> str | None:
    """The sentence for a computer that slept during the audit, or None when it did not (or it is not known)."""
    if slept_s is None or float(slept_s) < SLEEP_NOTE_MIN_S:
        return None
    return SLEEP_NOTE.format(minutes=max(1, round(float(slept_s) / 60)))


def duration_line(result: CrawlResult, all_phases_s: float | None, slept_s: float | None = None) -> str:
    """The Markdown report's duration: Maya's own crawl, and the whole audit when it was measured; and, when the
    computer slept during the audit, how long (DECISIONS 295)."""
    own = f"**Duration:** {result.elapsed_s} seconds for Maya's own crawl and checks"
    note = sleep_note(slept_s)
    return own + (f"; {round(float(all_phases_s), 1)} seconds for the whole audit, every step included" if all_phases_s is not None
                  else " (a page reader and paid panels, when used, run after it)") + (f". {note}" if note else "")


def timing(result: CrawlResult, firecrawl: dict | None = None, all_phases_s: float | None = None,
           slept_s: float | None = None) -> dict[str, Any]:
    """How long the audit took, by step. `crawl.elapsed_s` is Maya's own crawl and its data collection only; a page
    reader and the paid panels run after it. `all_phases_s` is the whole job when the caller measured it, else null.
    `slept_s` (1.22, DECISIONS 295) is how long the computer slept during the audit: the wall clock less the audit's own
    clock, which stops while the computer sleeps; null when not measured. `slept_note` says it when it is 2 min or more."""
    reader = ((firecrawl or {}).get("coverage") or {}).get("elapsed_s")
    return {"crawl_and_checks_s": result.elapsed_s, "page_reader_s": reader,
            "all_phases_s": None if all_phases_s is None else round(float(all_phases_s), 3),
            "slept_s": None if slept_s is None else round(float(slept_s), 1), "slept_note": sleep_note(slept_s),
            "note": "crawl.elapsed_s covers Maya's own crawl only; all_phases_s is the whole job, when it was measured; "
                    "neither counts time the computer slept (slept_s)"}


def read_through_reader(firecrawl: dict | None) -> int:
    """Pages Firecrawl read as the audit's page reader after Maya's own crawler was challenged; 0 otherwise."""
    if not firecrawl or not firecrawl.get("used") or firecrawl.get("purpose") != "main page reader":
        return 0
    how = firecrawl.get("crawl_blocked") or {}
    # Also when no answer reached this computer and the reader read the site: the reader's pages are the audit's pages.
    return (firecrawl.get("pages_read") or 0) if how.get("blocked") or how.get("direct_not_reached") else 0


# Maya's crawler stopped by 429s, and the page reader read pages (DECISIONS 295). The web layer words the cover label
# through `result.outcome.blocked_read_through`.
BLOCKED_READ_THROUGH = "Maya's crawler was blocked (429 on pages); {n} page(s) were read through Firecrawl"
BLOCKED_READ_THROUGH_SENTENCE = re.compile(r"^Maya's crawler was blocked \(429 on pages\); (?P<pages>\d+) page\(s\) were read through Firecrawl")


def _read_after_rate_limit(firecrawl: dict | None) -> int:
    """Pages the page reader read after Maya's crawler was stopped by 429s; 0 when it read none or was not used."""
    section = firecrawl or {}
    if not section.get("used"):
        return 0
    return int(section.get("pages_read") or 0)


# The audit stopped at its page limit and at nothing else (DECISIONS 226). The web layer words the cover label through
# `result.outcome.partial_page_cap`.
PARTIAL_PAGE_CAP = ("Partial audit: {read} of {total} known pages were read (the page limit of {cap}). Findings cover only the "
                    "pages read.")
PARTIAL_PAGE_CAP_SENTENCE = re.compile(r"^Partial audit: (?P<read>\d+) of (?P<total>\d+) known pages were read \(the page limit of (?P<cap>\d+)\)\.")


def _reader_only_capped(firecrawl: dict | None) -> bool:
    """Whether a page reader, when one was used, left nothing out but what its own page cap kept out: no stop, no failed
    page, no other reason for addresses it did not ask for."""
    section = firecrawl or {}
    if not section.get("used"):
        return not section.get("stopped_because")
    coverage = section.get("coverage") or {}
    return (not section.get("stopped_because") and not coverage.get("requested_without_a_readable_document")
            and coverage.get("not_requested_because") in (None, "page_cap")
            and (not coverage.get("known_urls_not_requested") or coverage.get("cap_reached")))


# The sentence of a complete audit (CR-07). It claims only what the run knows: every discovered page was crawled. How
# many checks could not run is said when the checks are passed in; "every check ran" is never claimed when one did not.
COMPLETE = "The audit completed: every discovered page was crawled."
COMPLETE_ALL_RAN = "The audit completed: every discovered page was crawled and every check ran."
COMPLETE_NOT_RUN = ("The audit completed: every discovered page was crawled; {n:check|checks} could not run "
                    "(see Coverage and checks).")


def checks_not_run(checks: list[Any] | None) -> int | None:
    """How many of the site's checks are `not_assessed` (the answer-engine panel is not counted; a check a single-page
    audit sets aside does not apply). None when no checks are known."""
    if checks is None:
        return None
    from .single_page import not_applicable

    def get(check, key):
        return check.get(key) if isinstance(check, dict) else getattr(check, key, None)
    return sum(1 for check in checks if not str(get(check, "check_id") or "").startswith("ANS")
               and get(check, "status") == "not_assessed" and not not_applicable(check))


def reader_left_pages_unread(firecrawl: dict | None) -> bool:
    """Whether the audit's main page reader left something unread that its coverage line names (`reader_gaps`: its page
    cap or request allowance with pages waiting, an early stop, pages with no readable document, a key page). The
    outcome is decided on the same signal as the coverage sentence, so the two never disagree (DECISIONS 138, H18)."""
    section = firecrawl or {}
    if not section.get("used") or section.get("purpose") != "main page reader":
        return False
    return bool(reader_gaps(section))


def run_outcome(result: CrawlResult, gates: list[GateResult], firecrawl: dict | None = None,
                checks: list[Any] | None = None) -> tuple[int, str, str]:
    """The run's exit code, a one-word result, and the sentence that explains it.

    Degraded outranks incomplete: a crawl that was blocked and also ran out of pages is reported as
    blocked, because raising the page cap would not fix it. A site that challenged Maya's own crawler and was then
    read through Firecrawl was read: the challenge alone does not make the audit degraded, but it is said in the
    sentence, and anything the reader left unread (its page cap, a stop, a failure, a key page) makes the audit
    incomplete. Reading through a reader is never reported as crawlers being let in. A main page reader that stopped
    early with pages unread makes the audit incomplete even when Maya's own crawl read everything (DECISIONS 138, H18).
    Exit codes are unchanged: 0 complete, 1 degraded, 2 error, 3 incomplete. `checks`, when given, lets a complete
    audit say how many checks could not run (CR-07); it never changes the code.
    """
    bad_gates = [g.check_id for g in gates if g.state in {"degraded", "blocked", "failed", "violation"}]
    through = read_through_reader(firecrawl)
    if through:
        bad_gates = [gate for gate in bad_gates if gate != "INT-1"]
    stop = result.stop_reason.value
    # A collector or a robots.txt fetch cut short by the time limit is unfinished work, not a site problem.
    failed_collectors = {k: v for k, v in result.collector_errors.items()
                         if not v.startswith("overall audit ") and k != "audit_stopped"}
    stopped = getattr(result, "stopped", False)
    out_of_time = result.deadline_hit or "audit_deadline_skipped" in (result.stop_detail or "")
    stopped_badly = stop in _DEGRADED_STOPS and "audit_deadline_skipped" not in (result.stop_detail or "")
    not_reached = stop == "network_problem"
    if not_reached and through:
        stopped_badly = False  # Maya's own requests got no answer here, and the reader read the site: the content was read
    read_after_429 = _read_after_rate_limit(firecrawl) if stop == "rate_limit" else 0
    if read_after_429:
        # Maya's crawler was stopped by 429s and the page reader read the site's pages (DECISIONS 295): the outcome code
        # stays DEGRADED (Maya's own requests were refused), but the site is not said to be unreadable. "Could not read
        # the site properly" stays for a reading of 0 pages.
        more = [gate for gate in bad_gates if gate != "INT-1"]
        why = list(reader_gaps(firecrawl))
        if more:
            why.append(f"{', '.join(more)} reported degradation, blocking, or an integrity violation")
        if failed_collectors:
            why.append(f"{len(failed_collectors)} data collector(s) failed")
        return (EXIT_DEGRADED, "DEGRADED", BLOCKED_READ_THROUGH.format(n=read_after_429) + ("; " + "; ".join(why) if why else "")
                + ". Genuine AI-crawler access was not measured. Findings cover only the pages read.")
    if bad_gates or stopped_badly or failed_collectors:
        why = []
        if bad_gates:
            why.append(f"{', '.join(bad_gates)} reported degradation, blocking, or an integrity violation")
        if stopped_badly:
            why.append(f"the crawl stopped early ({stop}: {result.stop_detail})")
        if failed_collectors:
            why.append(f"{len(failed_collectors)} data collector(s) failed")
        if not_reached and not bad_gates and not failed_collectors:
            # Nothing was read and nothing is known about the site: the sentence must not sound like a site problem.
            return (EXIT_DEGRADED, "DEGRADED", f"The audit could not reach the site from this computer: {result.stop_detail}. "
                    "Nothing is reported against the site. Run the audit again when the connection works.")
        return EXIT_DEGRADED, "DEGRADED", "The audit could not read the site properly: " + "; ".join(why) + "."
    if through:
        gaps = reader_gaps(firecrawl)
        if stopped:
            gaps.insert(0, "it was stopped on request and can be resumed")
        if out_of_time:
            gaps.insert(0, "the overall time limit was reached before every step finished")
        limits = ("Maya's own requests got no answer on this computer, so direct access was not measured. Genuine AI-crawler access "
                  "was not measured." if not_reached else
                  "Maya's direct crawler was challenged. Genuine AI-crawler access was not measured.")
        if gaps:
            return (EXIT_INCOMPLETE, "INCOMPLETE", f"The audit finished with partial coverage: {through} page(s) were read through Firecrawl; "
                    + "; ".join(gaps) + f". {limits} Findings cover only the pages read.")
        if single_page.is_single(result):
            return (EXIT_COMPLETED, "COMPLETED", f"Single-page audit: the page was read through Firecrawl. {limits} Other pages of the site "
                    "were not checked; some direct-request checks could not be completed.")
        return (EXIT_COMPLETED, "COMPLETED", f"We read {through} page(s) through Firecrawl: every address found from the homepage and "
                f"those pages. {limits} The report covers these {through} page(s); some direct-request checks could not be completed.")
    if (stop == "page_cap" and (result.stop_detail or "").startswith("page cap") and not out_of_time and not stopped
            and _reader_only_capped(firecrawl)):
        # Only the page limit stopped the audit (DECISIONS 226): a partial audit, said as such. Exit code 3 and the
        # INCOMPLETE label stay.
        read = read_counts(result, firecrawl)["pages"] if (firecrawl or {}).get("pages_read") else page_counts(result)[0]
        cap = (firecrawl or {}).get("page_cap") if (firecrawl or {}).get("pages_read") else None
        cap = cap or (getattr(result, "config", None) or {}).get("max_pages") or read
        return (EXIT_INCOMPLETE, "INCOMPLETE", PARTIAL_PAGE_CAP.format(read=read, total=read + known_unread(result, firecrawl), cap=cap))
    reader_unread = reader_left_pages_unread(firecrawl)
    if (reader_unread and stop == "exhausted" and not out_of_time and not stopped and not result.not_fetched_urls
            and _reader_only_capped(firecrawl) and ((firecrawl or {}).get("coverage") or {}).get("cap_reached")):
        # Maya's own crawl read everything and only the reader's page limit left pages unread: the partial audit of
        # DECISIONS 226, with the reader's cap.
        read = read_counts(result, firecrawl)["pages"]
        cap = (firecrawl or {}).get("page_cap") or ((firecrawl or {}).get("coverage") or {}).get("page_cap") or read
        return (EXIT_INCOMPLETE, "INCOMPLETE", PARTIAL_PAGE_CAP.format(read=read, total=read + known_unread(result, firecrawl), cap=cap))
    if stop != "exhausted" or out_of_time or result.not_fetched_urls or stopped or reader_unread:
        why = []
        if stopped:
            why.append("it was stopped on request and can be resumed")
        if stop not in _DEGRADED_STOPS and stop not in ("exhausted", "stopped"):
            why.append(f"{stop}: {result.stop_detail}")
        if out_of_time and stop != "time_limit":
            why.append("the overall time limit was reached before every check finished")
        if reader_unread:
            # Why the reader stopped, and what it asked for and could not read; the one "not read" figure follows.
            why.extend(gap for gap in reader_gaps(firecrawl) if not re.match(r"\d+ more discovered URL|\+\d+ address", gap))
        if known_unread(result, firecrawl):
            why.append(f"{known_unread(result, firecrawl)} discovered URL(s) were not " + ("read" if (firecrawl or {}).get("used") else "fetched"))
        return (EXIT_INCOMPLETE, "INCOMPLETE",
                "The audit finished but is incomplete (" + "; ".join(why) + "). Findings cover only what was fetched.")
    if single_page.is_single(result):
        return EXIT_COMPLETED, "COMPLETED", single_page.OUTCOME
    not_run = checks_not_run(checks)
    if not_run is None:
        return EXIT_COMPLETED, "COMPLETED", COMPLETE
    return EXIT_COMPLETED, "COMPLETED", phrase(COMPLETE_NOT_RUN, n=not_run) if not_run else COMPLETE_ALL_RAN


def internal_link_lines(result: CrawlResult, checks: list[CheckResult]) -> list[str]:
    """The "Internal links" section of the Markdown report: click depth, and the most and least linked pages."""
    idx7 = next((c for c in checks if c.check_id == "IDX-7"), None)
    graph = next((o for o in (idx7.observations if idx7 else []) if "most_linked" in o), None)
    discovery = getattr(result, "render_discovery", None) or {}
    if graph is None and not discovery.get("used"):
        return []
    lines = ["## Internal links", ""]
    if discovery.get("used"):
        lines += [f"Link discovery used rendering: {discovery['links_added']} link(s) exist only after JavaScript runs "
                  f"and were followed ({discovery['limit']}).", ""]
    if graph is None:
        return lines
    if graph.get("note"):
        lines += [graph["note"], ""]
    depths = graph["pages_by_click_depth"]
    lines += ["Pages by clicks from the homepage: " + ", ".join(
        f"{count} at {depth}" if depth.isdigit() else f"{count} {depth}" for depth, count in depths.items()) + ".", ""]
    for heading, rows in (("Most linked pages", graph["most_linked"]), ("Least linked pages", graph["least_linked"])):
        lines += [f"**{heading}**", "", "| Page | Links to it | Clicks from homepage |", "|---|---|---|"]
        lines += [f"| `{_short(row['url'], result.origin)}` | {row['inbound_links']} | "
                  f"{row['click_depth'] if row['click_depth'] is not None else 'not reached by links'} |" for row in rows]
        lines.append("")
    return lines


# Rows of the problem list and the action plan that say the same thing about other pages are one row, naming up to
# MERGED_PAGES_NAMED pages (DECISIONS 225). Since the accuracy round the rows must share semantic evidence
# (`qualified_group_key`), never only a title with its numbers taken out: the title-only `repeated_key` of decision 225
# was no longer called and was removed (CR-29). The web layer words the same line through `practical.merged`.
MERGED_PAGES_NAMED = 3
MERGED = "{title}: {paths}"
MERGED_MORE = "{title}: {paths} and {more} more"
# A count, not a digit inside an address or a name ("/missing-136" keeps its number).
_NUMBER = re.compile(r"(?<![\w/.-])\d+(?:[.,]\d+)*(?![\w/-])")


def qualified_group_key(finding):
    """Presentation grouping requires semantic evidence, never just a matching title."""
    import json
    def get(key, default=None):
        return finding.get(key, default) if isinstance(finding, dict) else getattr(finding, key, default)
    evidence = get('evidence', {}) or {}
    shared = evidence.get('shared_element')
    scope = get('scope', {}) or {}
    if not isinstance(shared, dict) or len(scope.get('_all_urls') or scope.get('urls') or []) < int(scope.get('count') or 0):
        return ('individual', get('id'))
    identity = {k: v for k, v in shared.items() if k not in ('pages', 'links', 'count')}
    return (get('check_id'), str(get('severity')), str(get('confidence')), get('how_to_fix'),
            json.dumps(identity, sort_keys=True, ensure_ascii=False))


def finding_counts(finding):
    """Explicit units. Never infer occurrences from a title or an incomplete evidence sample."""
    scope, evidence = finding.get('scope') or {}, finding.get('evidence') or {}
    shared = evidence.get('shared_element') or {}
    occurrences = None
    per_template = None  # shared.links counts target groups, not occurrences
    source_target_groups = evidence.get('count') if finding.get('check_id') == 'STR-14' else None
    if finding.get('check_id') in ('STR-14', 'STR-19') and isinstance(evidence.get('occurrences'), int):
        occurrences = evidence['occurrences']
    by_page = evidence.get('by_page') or []
    if by_page and all(isinstance(r.get('links'), int) for r in by_page) and len(by_page) >= int(scope.get('count') or 0):
        occurrences = sum(r['links'] for r in by_page)
    elif finding.get('check_id') == 'STR-14':
        links = evidence.get('links') or []
        field = 'links_with_generic_text' if 'generic' in (finding.get('title') or '') else 'links'
        complete = (not shared and isinstance(evidence.get('count'), int) and len(links) == evidence['count'])
        if links and complete and all(isinstance(r.get(field), int) for r in links):
            occurrences = sum(r[field] for r in links)
        if shared and links and len({r.get('source') for r in links}) == int(scope.get('count') or 0):
            per_page = {}
            if all(isinstance(r.get(field), int) for r in links):
                for r in links:
                    per_page[r['source']] = per_page.get(r['source'], 0) + r[field]
                occurrences = sum(per_page.values())
                if len(set(per_page.values())) == 1:
                    per_template = next(iter(per_page.values()))
    return {'occurrences': occurrences, 'affected_pages': scope.get('count'),
            **({'title_unit':evidence['title_count_unit']} if evidence.get('title_count_unit') else {}),
            'listed_unique_pages': len(set(scope.get('_all_urls') or scope.get('urls') or [])),
            'template_groups': 1 if shared else 0, 'occurrences_per_template': per_template,
            'source_target_groups': source_target_groups}


def merge_repeated(rows: list[Any], key) -> list[list[Any]]:
    """`rows` in their order, as groups: a row whose `key` an earlier row has is put with that row."""
    groups: dict[Any, list[Any]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    return list(groups.values())


def merged_pages(lists: list[tuple[list[str], int]]) -> tuple[list[str], int]:
    """(up to MERGED_PAGES_NAMED pages named, how many more) for rows that are one: each row's (pages, page count). When
    every row lists all its pages, the distinct pages are counted; otherwise the rows' counts are added."""
    named = list(dict.fromkeys(url for urls, _ in lists for url in urls))
    whole = all(len(urls) >= count for urls, count in lists)
    total = len(named) if whole else max(len(named), sum(count for _, count in lists))
    return named[:MERGED_PAGES_NAMED], max(0, total - MERGED_PAGES_NAMED)


def merged_title(title: str, paths: list[str], more: int) -> str:
    return (MERGED_MORE if more else MERGED).format(title=title, paths=", ".join(paths), more=more)


# -- presentation: one card per problem, said once (preview-23 review, section C) -------------------------------------
#
# The engine's findings stay as they are (DECISIONS 20: one IDX-6 finding per broken target). What follows only decides
# how the Markdown shows them: which findings are one card, what a card says, and what is said once for all cards.

ACC6_LINE = re.compile(r"^(?P<vendor>[^:]+): Training(?: \((?P<training>[^)]+)\))?: (?P<training_state>.+?) · "
                       r"Search(?: \((?P<search>[^)]+)\))?: (?P<search_state>.+?) · Live fetch(?: \((?P<live>[^)]+)\))?: (?P<live_state>.+)$")


def presentation_group_key(finding: Any) -> tuple:
    """`qualified_group_key`, and three groupings of what one check says several times about one thing (CR-02, CR-24):
    IDX-6's broken targets of one status and one fix (one finding per target stays in the JSON), ACC-2's findings for one
    robots.txt line (one per bot role), and ACC-6's per-provider notes. Only the Markdown cards use it; the web's
    `semantic_group` keeps `qualified_group_key`, so its merged rows are unchanged."""
    def get(key, default=None):
        return finding.get(key, default) if isinstance(finding, dict) else getattr(finding, key, default)
    evidence = get("evidence", {}) or {}
    check = get("check_id")
    if check == "IDX-6" and evidence.get("target") and evidence.get("target_status") is not None:
        return ("IDX-6:broken-targets", str(getattr(get("severity"), "value", get("severity"))), evidence["target_status"],
                get("how_to_fix"))
    rule = evidence.get("rule") if isinstance(evidence.get("rule"), dict) else None
    if check == "ACC-2" and rule and rule.get("line") is not None:
        return ("ACC-2:robots-line", evidence.get("robots_url"), rule.get("line"), rule.get("pattern"))
    if check == "ACC-6" and ACC6_LINE.match(get("title") or ""):
        return ("ACC-6:providers",)
    return qualified_group_key(finding)


def _urls(finding: Any) -> list[str]:
    return list(finding.scope.get("_all_urls") or finding.scope.get("urls") or [])


def _fully_listed(same: list[Any]) -> bool:
    return all(len(_urls(f)) >= int(f.scope.get("count") or 0) for f in same)


def group_pages(same: list[Any]) -> int | str:
    """How many pages a card's findings are on: "site-wide" for a site-wide one; the distinct pages when every finding
    lists all of its own, else the larger of the pages named and the largest count (DECISIONS 359: never the counts
    added up, which counts a page two findings share twice; at least that many)."""
    if any(f.scope.get("kind") == "sitewide" for f in same):
        return "site-wide"
    named = set(url for f in same for url in _urls(f))
    if _fully_listed(same):
        return len(named)
    return max([len(named)] + [int(f.scope.get("count") or 0) for f in same])


def _pages_label(pages: int | str) -> str:
    return pages if isinstance(pages, str) else phrase("{n:page|pages}", n=pages)


def estimate(finding: Any) -> dict[str, str]:
    """The owner and effort of a finding's fix: the qualified judgment's when it set one, else the catalogue's. Both
    are labelled estimates (recommendation_catalog), not measurements."""
    action = ((finding.evidence or {}).get("judgment") or {}).get("action") or {}
    if action.get("owner") and action.get("effort"):
        return {"owner": action["owner"], "effort": action["effort"]}
    from .recommendation_catalog import note
    found = note(finding.check_id, finding.title)
    return {"owner": found["owner"], "effort": found["effort"]}


def why_it_matters(finding: Any) -> str | None:
    """The catalogue's sentence for why the finding matters (CR-16), looked up by the title the check wrote (kept under
    the judgment's `source`, as `judgments.qualify` does) and then the title shown. None for no sentence of its own."""
    from .recommendation_catalog import why
    source = (((finding.evidence or {}).get("judgment") or {}).get("source") or {}).get("title")
    return why(finding.check_id, source or "", finding.title)


def _unverified(finding: Any) -> str | None:
    """"Unverified check (LG-42)": the card's own part of the launch-gate note; the sentence is said once, above."""
    if not finding.launch_gated:
        return None
    items = launch_gate.gate_items(finding.launch_gated)
    return f"{launch_gate.UNVERIFIED_LABEL} ({', '.join(items) if items else '; '.join(finding.launch_gated)})"


EFFORT_WORDS = {"S": "small", "M": "medium", "L": "large"}
HIGH_IMPACT = ("S1", "S2")
FIRST_FIXES = 10
EXAMPLE_PAGES = 5
BROKEN_TARGETS_SHOWN = 10

FIX_FIRST_INTRO = ("Each card names its check, how sure the observation is, why it matters and the fix. Said once here "
                   "rather than on every card: complete URLs, fields and request records are in the JSON report, by "
                   "finding ID. To verify a fix: {verify} Cards marked “{label} (LG-n)” use a rule not yet validated "
                   "on real sites: confirm the finding by hand before acting on it.")
NOTES_TITLE = "Notes (no action implied)"
NOTES_INTRO = "Recorded facts that may be intentional. One line each; the full detail is in the JSON report."
HYGIENE_TITLE = "Hygiene"
HYGIENE_INTRO = ("Small site-wide settings most sites leave as they are; each has a fix, none is urgent. One line each; "
                 "the full detail is in the JSON report.")
HYGIENE_MORE = "{n:more hygiene item|more hygiene items} in the JSON report"
FIRST_FIXES_NOTE = ("One row per check, in the order of the cards below (the # is the card's number): severity first, then "
                    "verified observations before unverified rules and estimates; a key page or the homepage before other "
                    "pages. A row names the check's other S1-S3 cards after “also”. Effort and owner are estimates, not "
                    "measurements.")
SERIOUS = ("S1", "S2", "S3")
ALSO_NAMED = 2
MATRIX_NOTE = ("Impact: high for S1 and S2. Effort: small (S) or medium/large (M, L), from the same estimates as the "
               "table above. Every problem card is placed, by its number.")
QUADRANTS = (("High impact", "Quick wins", "Major projects"), ("Lower impact", "Fill-ins", "Later"))
CRAWL_GAP_ONCE = ("Pages found but not read: {reason}. Every page check below ran only on the pages that were read; this "
                  "is said once here, not on each row.")
BROKEN_TARGETS = "{n:internal link target returns|internal link targets return} {status}"
BROKEN_TARGETS_MORE = "{n:more target|more targets}: JSON report, IDX-6 findings"


def card_groups(findings: list[Any]) -> tuple[list[list[Any]], list[list[Any]]]:
    """(problem cards, notes), each a list of groups of findings in priority order (CR-06: a finding at Info implies
    no action and is a note, never a numbered card)."""
    problems = [f for f in findings if f.severity.value != "Info"]
    notes = [f for f in findings if f.severity.value == "Info"]
    return merge_repeated(problems, presentation_group_key), merge_repeated(notes, presentation_group_key)


def card_heading(same: list[Any], origin: str) -> str:
    finding = same[0]
    if len(same) == 1:
        return finding.title
    if finding.check_id == "IDX-6" and finding.evidence.get("target"):
        return phrase(BROKEN_TARGETS, n=len(same), status=finding.evidence.get("target_status"))
    if finding.check_id == "ACC-2" and isinstance(finding.evidence.get("rule"), dict):
        rule = finding.evidence["rule"]
        roles = list(dict.fromkeys(m.group(1) for m in (re.search(r"blocks (\w+) bot", f.title) for f in same) if m))
        return f"robots.txt line {rule.get('line')} (Disallow: {rule.get('pattern')}) blocks {', '.join(roles)} bots"
    named, more = merged_pages([(_urls(f), int(f.scope.get("count") or 0)) for f in same])
    return merged_title(finding.title, [_short(url, origin) for url in named], more)


def card_lines(number: int, same: list[Any], origin: str, as_saved: dict[str, Any]) -> list[str]:
    """One numbered card of "What to fix first": only what is particular to these findings."""
    finding = same[0]
    pages = group_pages(same)
    shown = pages if isinstance(pages, str) or _fully_listed(same) else "not fully listed"
    head = f"**Check:** {finding.check_id} · **Confidence:** {finding.confidence.value} · **Affected pages:** {shown}"
    unverified = _unverified(finding)
    lines = [f"### {number}. [{finding.severity.value}] {card_heading(same, origin)}", "",
             head + (f" · **{unverified}**" if unverified else ""), ""]
    why = why_it_matters(finding)
    if why:
        lines += [f"**Why it matters:** {why}", ""]
    lines += [f"**Expected:** {finding.expected}", "", f"**Suggested fix:** {finding.how_to_fix}", ""]
    if finding.check_id in ('STR-14', 'STR-19'):
        counts = finding_counts(to_jsonable(finding))
        lines += [f"**Counting units:** source-target groups: {counts['source_target_groups'] if counts['source_target_groups'] is not None else 'unavailable'}; occurrences: {counts['occurrences'] if counts['occurrences'] is not None else 'unavailable'}; affected pages: {counts['affected_pages']}; template groups: {counts['template_groups']}. Counts in a title may refer to groups, not occurrences.", ""]
    if len(same) > 1 and finding.check_id == "IDX-6" and finding.evidence.get("target"):
        # One block for the broken targets (CR-02): the first ten with how many pages link to each, the rest in the JSON.
        lines += ["| Broken target | Linked from (pages) |", "|---|---|",
                  *[f"| `{_short(f.evidence['target'], origin)}` | {int(f.scope.get('count') or len(_urls(f)))} |"
                    for f in same[:BROKEN_TARGETS_SHOWN]]]
        if len(same) > BROKEN_TARGETS_SHOWN:
            lines.append(f"| {phrase(BROKEN_TARGETS_MORE, n=len(same) - BROKEN_TARGETS_SHOWN)} | |")
        lines.append("")
    else:
        if len(same) > 1 and finding.check_id == "ACC-2":
            lines += ["**Each rule finding:**", *[f"- [{f.severity.value}] {f.title}" for f in same], ""]
        urls = list(dict.fromkeys(url for f in same for url in f.scope.get("urls") or []))
        if urls:
            lines += ["**Example pages:**", *[f"- `{url}`" for url in urls[:EXAMPLE_PAGES]]]
            rest = max(len(urls), pages if isinstance(pages, int) else 0) - EXAMPLE_PAGES
            if rest > 0:
                lines.append(f"- … {phrase('{n:more page|more pages}', n=rest)} in the JSON report")
            lines.append("")
    details = detail_lines(as_saved[finding.id])
    if details:
        lines += [f"**{DETAILS_TITLE}:**", *[f"- {said}" for said in merged_detail_sentences(details, origin)], ""]
    notes = list(dict.fromkeys(note for f in same for note in f.notes))
    if notes:
        lines += ["**Notes:**", *[f"- {note}" for note in notes], ""]
    return lines


def note_lines(groups: list[list[Any]]) -> list[str]:
    """"Notes (no action implied)": one line a note (check · title · pages); ACC-6's providers as one table (CR-06,
    CR-24). Hygiene findings (`findings.is_hygiene`: a fix, but site-wide and seen on most sites) follow as a short
    "Hygiene" list, capped at config.HYGIENE_LINES (G25). Each note's full card stays in the JSON report."""
    if not groups:
        return []
    hygiene = [same for same in groups if is_hygiene(same[0])]
    groups = [same for same in groups if not is_hygiene(same[0])]
    lines = [f"## {NOTES_TITLE}", "", NOTES_INTRO, ""] if groups else []
    tables: list[str] = []
    for same in groups:
        finding = same[0]
        unverified = _unverified(finding)
        found = [ACC6_LINE.match(f.title) for f in same] if finding.check_id == "ACC-6" else []
        if found and all(found):
            lines.append(f"- {finding.check_id} · Training crawlers are set apart from search crawlers for "
                         f"{phrase('{n:provider|providers}', n=len(same))} (table below) · site-wide"
                         + (f" · {unverified}" if unverified else ""))
            tables += ["", "| Provider | Training | Search | Live fetch |", "|---|---|---|---|",
                       *[f"| {m['vendor']} | {(m['training'] + ': ') if m['training'] else ''}{m['training_state']} | "
                         f"{(m['search'] + ': ') if m['search'] else ''}{m['search_state']} | "
                         f"{(m['live'] + ': ') if m['live'] else ''}{m['live_state']} |" for m in found]]
            continue
        lines.append(_note_line(same))
    lines = lines + tables + ([""] if groups else [])
    return lines + hygiene_lines(hygiene)


def _note_line(same: list[Any]) -> str:
    finding = same[0]
    unverified = _unverified(finding)
    title = "; ".join(dict.fromkeys(f.title for f in same))  # one line, every finding named
    return (f"- {finding.check_id} · {_cell(title)} · {_pages_label(group_pages(same))}"
            + (f" · {unverified}" if unverified else ""))


def hygiene_lines(groups: list[list[Any]]) -> list[str]:
    """"Hygiene" (G25): one line a group, at most config.HYGIENE_LINES, then how many more are in the JSON report."""
    from .config import HYGIENE_LINES
    if not groups:
        return []
    lines = [f"## {HYGIENE_TITLE}", "", HYGIENE_INTRO, "", *(_note_line(same) for same in groups[:HYGIENE_LINES])]
    if len(groups) > HYGIENE_LINES:
        lines.append(f"- … {phrase(HYGIENE_MORE, n=len(groups) - HYGIENE_LINES)}")
    return lines + [""]


def first_fix_rows(groups: list[list[Any]]) -> list[tuple[int, list[Any]]]:
    """(card number, group) for the first card of each check, up to FIRST_FIXES (H37): one row per check."""
    rows, seen = [], set()
    for number, same in enumerate(groups, 1):
        if same[0].check_id in seen:
            continue
        seen.add(same[0].check_id)
        rows.append((number, same))
        if len(rows) == FIRST_FIXES:
            break
    return rows


def also_serious(groups: list[list[Any]], same: list[Any]) -> list[tuple[int, list[Any]]]:
    """(card number, group) of the other S1-S3 cards of `same`'s check: a "first fixes" row is one per check, so it names
    them rather than hide a second Medium-or-worse finding of the same check (G25)."""
    check = same[0].check_id
    return [(number, group) for number, group in enumerate(groups, 1)
            if group is not same and group[0].check_id == check and group[0].severity.value in SERIOUS]


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def first_fixes_lines(groups: list[list[Any]], origin: str) -> list[str]:
    """"First 10 fixes" (H37): # (the card's number) · problem · pages affected · severity · effort · owner."""
    rows = first_fix_rows(groups)
    if not rows:
        return []
    lines = [f"## First {len(rows)} fixes" if len(rows) > 1 else "## First fix", "", FIRST_FIXES_NOTE, "",
             "| # | Problem | Pages affected | Severity | Effort | Owner |", "|---|---|---|---|---|---|"]
    for number, same in rows:
        finding = same[0]
        guess = estimate(finding)
        mark = (f" — {_unverified(finding)}" if finding.launch_gated
                else f" — {finding.confidence.value}" if finding.confidence.value != "verified" else "")
        also = also_serious(groups, same)
        if also:
            named = "; ".join(f"#{n} {card_heading(g, origin)}" for n, g in also[:ALSO_NAMED])
            mark += f" — also {named}" + (f" and {len(also) - ALSO_NAMED} more" if len(also) > ALSO_NAMED else "")
        lines.append(f"| {number} | {_cell(card_heading(same, origin) + mark)} | {_pages_label(group_pages(same))} | "
                     f"{finding.severity.value} | {EFFORT_WORDS.get(guess['effort'], guess['effort'])} | {guess['owner']} |")
    return lines + [""]


def impact_effort_lines(groups: list[list[Any]]) -> list[str]:
    """A 2×2 of every problem card by impact (severity) and effort (the estimate): quick wins, major projects, fill-ins,
    later (H37). Placement only; nothing is re-scored."""
    if not groups:
        return []
    cells: dict[tuple[bool, bool], list[str]] = {(high, small): [] for high in (True, False) for small in (True, False)}
    for number, same in enumerate(groups, 1):
        finding = same[0]
        cells[(finding.severity.value in HIGH_IMPACT, estimate(finding)["effort"] == "S")].append(f"#{number} {finding.check_id}")
    lines = ["## Impact and effort", "", MATRIX_NOTE, "", "| | Small effort | Medium or large effort |", "|---|---|---|"]
    for (label, quick, slow), high in zip(QUADRANTS, (True, False)):
        lines.append(f"| **{label}** | **{quick}:** {', '.join(cells[(high, True)]) or '—'} | "
                     f"**{slow}:** {', '.join(cells[(high, False)]) or '—'} |")
    return lines + [""]


def discovered_phrase(result) -> str:
    """"N URLs discovered", and when a sitemap index was read in part (DECISIONS 299) that the figure is partial."""
    from .sitemap import partial
    n = len(result.discovered_urls)
    return f"{n} URLs discovered" + (" (partial: a large sitemap index was read in part)" if partial(result.sitemap_notes) else "")


def summary_lines(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult], firecrawl: dict | None,
                  summary: dict[str, Any], groups: list[list[Any]]) -> list[str]:
    """The executive summary (H37): the result, the scope, and the top three problems, in five lines."""
    word, sentence = run_outcome(result, gates, firecrawl, checks)[1:]
    not_run = checks_not_run(checks) or 0
    scope = (f"{_pages_label(summary['pages_checked'])} read of {discovered_phrase(result)}; "
             + (f"{not_run} of {len(checks)} checks could not run (see Coverage and checks)." if not_run
                else f"all {len(checks)} checks ran."))
    lines = ["## Summary", "", f"- **Result:** {word} — {sentence}", f"- **Scope:** {scope}"]
    for number, same in enumerate(groups[:3], 1):
        finding = same[0]
        lines.append(f"- **Problem {number}:** [{finding.severity.value}] {card_heading(same, result.origin)} "
                     f"({_pages_label(group_pages(same))})")
    if not groups:
        lines.append("- **Problems:** none found in what was assessed; checks that could not run are not passes.")
    return lines + [""]


def first_clause(text: str, limit: int = 200) -> str:
    text = " ".join(str(text or "").split())
    found = re.match(r"(.+?[.!?])(\s|$)", text)
    text = found.group(1) if found else text
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def not_assessed_lines(checks: list[CheckResult]) -> list[str]:
    """The checks that could not run, one line each, for the short Markdown report."""
    rows = [c for c in checks if not c.check_id.startswith("ANS") and c.status == "not_assessed"]
    if not rows:
        return []
    return ["## Not assessed", "", "These checks could not run. Not assessed is never a pass.", "",
            *[f"- **{c.check_id} {c.title}:** {_cell(first_clause(c.summary))}" for c in rows], ""]


def _markdown_head(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult], firecrawl: dict | None):
    """What the full and the short Markdown both start with: the header lines, the headline, the summary and the first
    fixes, and the findings they were made from."""
    from .judgments import qualify_checks
    checks = qualify_checks(checks, result)
    site_checks = [c for c in checks if not c.check_id.startswith("ANS")]
    findings = sorted((f for c in site_checks for f in c.findings), key=priority_key)
    title = single_page.TITLE.format(url=single_page.page_url(result)) if single_page.is_single(result) else f"Maya Audit: {result.origin}"
    # The result sentence is said once, as the summary's first line.
    lines = [f"# {title}", "", f"**Run date:** {result.started_at}",
             f"**Pages checked:** {pages_phrase(result)}, of {discovered_phrase(result)}",
             f"**Crawl status:** {result.stop_reason.value} — {result.stop_detail}",
             duration_line(result, None), ""]
    readable = readable_pages(result, firecrawl)
    if readable:
        lines[3] = (f"**Pages read:** {readable}" if firecrawl.get("purpose") == "main page reader"
                    else f"**Readable pages:** {readable}. Maya's own crawl remains the live access test.")
    summary = problem_summary(to_jsonable(findings), affected_urls(site_checks), pages_checked=pages_shown(result, firecrawl),
                              checks=site_checks, single_page=single_page.page_url(result) if single_page.is_single(result) else None,
                              start_address=start_address(result))
    lines += [f"**{headline(summary)}**", ""]
    problems, notes = card_groups(findings)
    lines += summary_lines(result, gates, site_checks, firecrawl, summary, problems)
    lines += first_fixes_lines(problems, result.origin)
    return checks, site_checks, findings, summary, problems, notes, lines


def render_markdown_brief(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult], *,
                          firecrawl: dict | None = None) -> str:
    """The short Markdown report (`--markdown-brief`, H37): the summary, the first ten fixes, the impact and effort
    grid and the checks that could not run; about two pages. `render_markdown` stays the full report."""
    _checks, site_checks, _findings, _summary, problems, notes, lines = _markdown_head(result, gates, checks, firecrawl)
    lines += impact_effort_lines(problems)
    lines += not_assessed_lines(site_checks)
    rest = len(problems) - len(first_fix_rows(problems))
    plain = sum(1 for same in notes if not is_hygiene(same[0]))
    lines += ["## More in the full report", "",
              f"{phrase('{n:more problem card|more problem cards}', n=rest)}, {phrase('{n:note|notes}', n=plain)} "
              f"(no action implied) and {phrase('{n:hygiene item|hygiene items}', n=len(notes) - plain)} are in the full "
              "Markdown report (--markdown); every finding, URL and request record is in the JSON report (--json).", ""]
    return "\n".join(lines)


def render_markdown(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult], *, firecrawl: dict | None = None) -> str:
    """Create a readable Markdown report from the same measured objects as the JSON report.

    Order (preview-23 review, H37 and section C): the header and headline; a five-line summary; the first ten fixes, one
    row per check; the impact and effort grid; what the audit covers; the problem cards, with what every card would
    repeat said once above them; the notes (no action implied), one line each; problems by page (at most 25 rows); the
    coverage table, with "pages found but not read" said once; then the appendices."""
    checks, site_checks, findings, summary, problems, notes, lines = _markdown_head(result, gates, checks, firecrawl)
    review_items = [(c.check_id, item) for c in site_checks for item in c.review_items]
    lines += impact_effort_lines(problems)
    lines += ["## What this audit covers", "", *(f"- {line}" for line in coverage_lines(result, gates, checks, firecrawl)), ""]
    cut = time_limit_lines(result, checks)
    if cut:
        lines += ["## Cut short by the time limit", "", *(f"- {line}" for line in cut), ""]
    other_errors = {name: message for name, message in result.collector_errors.items() if "deadline" not in message
                    and name != "audit_deadline"}
    if other_errors:
        lines += ["## Checks that could not finish", ""]
        lines.extend(f"- **{name}:** {message}" for name, message in other_errors.items())
        lines.append("")
    as_saved = {f.id: to_jsonable(f) for f in findings}
    from .judgments import VERIFY
    lines += ["## What to fix first" + (" (overall time limit reached; later checks may be incomplete)"
                                        if result.deadline_hit else ""), ""]
    if problems:
        lines += [FIX_FIRST_INTRO.format(verify=VERIFY, label=launch_gate.UNVERIFIED_LABEL), ""]
        # The same check saying the same thing about other pages is one card (DECISIONS 225; CR-02, CR-24).
        for number, same in enumerate(problems, 1):
            lines += card_lines(number, same, result.origin, as_saved)
    else:
        lines += ["No problems were identified in the pages and checks covered by this run. This does not mean "
                  "unchecked pages or unavailable checks passed.", ""]
    lines += note_lines(notes)
    lines += problems_by_page_lines(summary, {f.id: title_with_details(as_saved[f.id]) if f.scope.get("kind") == "sitewide" else f.title
                                              for f in findings}, result.origin)
    if review_items:
        lines += ["## Items for a person to review", ""]
        for check_id, item in review_items:
            lines += [f"- **{check_id}: {item.title}** — {item.why_review} Suggested action: {item.suggested_action}"]
            lines += [f"  - {detail_sentence(line, result.origin)}" for line in detail_lines(to_jsonable(item))]
        lines.append("")
    lines += internal_link_lines(result, checks)
    lines += ["## Coverage and checks", ""]
    from .coverage import CRAWL_GAP_NAMES
    gap = next((part for check in site_checks for part in check.coverage.get("not_assessed", [])
                if part.get("part") in CRAWL_GAP_NAMES), None)
    if gap:
        lines += [f"> {CRAWL_GAP_ONCE.format(reason=gap['reason'])}", ""]
    lines += ["| Check | Result | Summary |", "|---|---|---|"]
    clean_on_read = clean_on_read_sentence(read_counts(result, firecrawl)["pages"], known_unread(result, firecrawl))
    for check in site_checks:
        # A check that found nothing, and is partial only because pages were found and not read, says so first.
        text = (f"{clean_on_read}. " if clean_on_what_was_read(check) else "") + check.summary.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {check.check_id} {check.title} | {check.status} | {text} |")
        for part in check.coverage.get("not_assessed", []):
            if part.get("part") in CRAWL_GAP_NAMES:
                continue  # said once, above the table (CR-05)
            count = f" ({part['count']} pages/items)" if part.get("count") is not None else ""
            lines.append(f"|  | Not assessed{count} | {part['part']}: {part['reason']} |")
    answers = [c for c in checks if c.check_id.startswith("ANS")]
    if answers:
        lines += ["", "## Answer-engine observations", "",
                  "These observations use supplied citation data. They do not change site findings, "
                  "and do not measure general AI visibility or sentiment.", ""]
        for check in answers:
            lines += [f"### {check.check_id}: {check.title}", "",
                      f"**Result:** {check.status} — {check.summary}", ""]
            for finding in check.findings:
                lines += [f"- **{finding.title}:** {finding.expected} Suggested fix: {finding.how_to_fix}"
                          + (f" **{launch_gate.UNVERIFIED_LABEL}:** {launch_gate.note(finding.launch_gated)}" if finding.launch_gated else "")]
            for item in check.review_items:
                lines += [f"- **Review: {item.title}:** {item.why_review} {item.suggested_action}"]
            for gap in check.coverage.get("not_assessed", []):
                lines += [f"- Not assessed: {gap['part']} — {gap['reason']}"]
            if check.observations:
                lines += ["", "**Recorded observations:**", "",
                          "    " + json.dumps(to_jsonable(check.observations), ensure_ascii=False).replace("\n", "\n    "), ""]
    if len(result.sessions or []) > 1:
        lines += ["", "## Resumed crawl coverage", "",
                  "This report combines saved pages from multiple sessions. Earlier pages were not fetched again; "
                  "content may have changed between sessions. The page cap applies to each session. "
                  "Request details cover the latest session; integrity summaries retain earlier session totals.", ""]
    lines += ["", "## Integrity checks", ""]
    for gate in gates:
        lines.append(f"- **{gate.check_id} {gate.title}: {gate.state}** — {gate.summary}")
    # Appendix: how long each step took, with the page reader's row when it ran (DECISIONS 219).
    steps = timeplan.markdown_lines(getattr(result, "steps", None), firecrawl)
    if steps:
        lines += ["", *steps]
    no_citations = (getattr(result.citations, "path", None) is None
                    and getattr(result.citation_domains, "path", None) is None)
    citation_note = ("No citation data supplied; AI citation-related checks are not assessed. " if no_citations
                     else "AI-answer citations are not measured unless the supplied citation data covers them. ")
    lines += ["", "## Important limits", "",
              "This report covers only the pages and data listed above. A partial crawl is not a clean bill of health. "
              + citation_note + "A technical audit checks site conditions; it cannot promise that an AI service will "
              "cite the site.", ""]
    return "\n".join(lines)


def write_markdown(content: str, path: str, overwrite: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def _short(url: str, origin: str) -> str:
    return url[len(origin):] or "/" if url.startswith(origin) else url


def render_checks(result: CrawlResult, checks: list[CheckResult]) -> str:
    """Site checks, then the answer-engine panel: ANS results are kept visually separate (spec §5 ANS)."""
    site = [c for c in checks if not c.check_id.startswith("ANS")]
    answers = [c for c in checks if c.check_id.startswith("ANS")]
    out = _render_group(result, site)
    if answers:
        out += ("\n" + "=" * 78 + "\nANSWER-ENGINE OBSERVATIONS (separate panel)\n"
                "Samples of engine behavior: non-deterministic, time-dependent, and paid (T4). They never change a "
                "site finding's\nseverity or confidence. Per engine only; engines are never summed.\n"
                + "=" * 78 + "\n\n" + _render_group(result, answers))
    return out


def _render_group(result: CrawlResult, checks: list[CheckResult]) -> str:
    o = result.origin
    lines: list[str] = []
    for check in checks:
        lines.append(f"{check.check_id}  {check.title}")
        lines.append(f"      status: {check.status.upper()}")
        lines.append(f"      {check.summary}")
        for gap in check.coverage.get("not_assessed", []):
            count = gap.get("count")
            amount = "" if count is None else f" ({'at least ' if gap.get('count_is_lower_bound') else ''}{count})"
            lines.append(f"      NOT ASSESSED: {gap['part']}{amount}: {gap['reason']}")
        for item in check.review_items:
            lines.append(f"      >>> NEEDS HUMAN REVIEW (no severity): {item.title}")
            lines.append(f"          why: {item.why_review}")
            lines.append(f"          confidence {item.confidence.value} · scope {item.scope['kind']} ×{item.scope['count']} · "
                         f"engines: {', '.join(item.engines)}")
            if item.scope["urls"]:
                lines.append(f"          urls: {[_short(u, o) for u in item.scope['urls'][:6]]}")
            if item.evidence.get("pairs") and "reproduce_browser" in item.evidence["pairs"][0]:
                lines.append(f"          reproduce (browser): {item.evidence['pairs'][0]['reproduce_browser']}")
                lines.append(f"          reproduce (bot):     {item.evidence['pairs'][0]['reproduce_bot']}")
            if item.launch_gated:
                lines.append(f"          LAUNCH-GATED: {' | '.join(item.launch_gated)}")
            lines.append(f"          action: {item.suggested_action}")
        for f in sorted(check.findings, key=priority_key):
            intent = ""
            if f.intent and f.intent["severity_otherwise"] != f.severity.value:
                intent = f"  (intent: {f.intent['kind']}; would otherwise be {f.intent['severity_otherwise']})"
            elif f.intent:
                intent = f"  (matches {f.intent['kind'].replace('_', ' ')})"
            lines.append(f"      [{f.severity.value}] {f.title}{intent}")
            lines.append(
                f"          confidence {f.confidence.value} · rationale {f.rationale} · cost {f.cost_tier} · "
                f"scope {f.scope['kind']} ×{f.scope['count']} · engines: {', '.join(f.engines)}"
            )
            if f.scope["kind"] != "sitewide" and f.scope["urls"]:
                lines.append(f"          urls: {[_short(u, o) for u in f.scope['urls'][:6]]}")
            for note in f.notes:
                lines.append(f"          note: {note}")
            if f.launch_gated:
                lines.append(f"          LAUNCH-GATED: {' | '.join(f.launch_gated)}")
            reproduce = f.evidence.get("reproduce")
            pairs = f.evidence.get("pairs")
            if reproduce is None and pairs and isinstance(pairs[0], dict) and "reproduce_bot" in pairs[0]:
                reproduce = pairs[0]["reproduce_bot"]
            if reproduce is None and f.evidence.get("pages") and isinstance(f.evidence["pages"][0], dict):
                reproduce = f.evidence["pages"][0].get("reproduce")
            if isinstance(reproduce, list):
                reproduce = reproduce[0] if reproduce else None
            if reproduce:
                lines.append(f"          reproduce: {reproduce}")
            lines.append(f"          fix: {f.how_to_fix}")
        for obs in check.observations:
            lines.append(f"      observation (no severity): {obs}")
        lines.append("")
    reviews = [(c.check_id, r) for c in checks for r in c.review_items]
    if reviews:
        lines.append("Needs human review (no severity; listed before severity-ranked findings so they are not missed)")
        for check_id, r in sorted(reviews, key=lambda cr: cr[1].importance_tier):
            lines.append(f"   * {check_id} {r.title}")
        lines.append("")
    ordered = sorted((f for c in checks for f in c.findings), key=priority_key)
    if ordered and checks and checks[0].check_id.startswith("ANS"):
        lines.append("Panel order (spec: failure type, then most recent citation)")
        for i, f in enumerate([f for c in checks for f in c.findings], 1):
            lines.append(f"  {i:>2}. [{f.severity.value}] {f.check_id} {f.title}")
        lines.append("")
    elif ordered:
        # Problems are numbered; a note implies no action and is listed apart, unnumbered (CR-06).
        problems = [f for f in ordered if f.severity.value != "Info"]
        notes = [f for f in ordered if f.severity.value == "Info"]
        if problems:
            lines.append("Priority order (severity, then verified before unverified or estimated, importance, impact, scope)")
            for i, f in enumerate(problems, 1):
                lines.append(f"  {i:>2}. [{f.severity.value}] {f.check_id} {f.title}"
                             + (f"  ({launch_gate.UNVERIFIED_LABEL})" if f.launch_gated else ""))
            lines.append("")
        if notes:
            lines.append(NOTES_TITLE)
            lines += [f"   - {f.check_id} {f.title}" for f in notes]
            lines.append("")
    return "\n".join(lines)


def render_text(result: CrawlResult, gates: list[GateResult], checks: list[CheckResult] | None = None, *,
                firecrawl: dict | None = None) -> str:
    o = result.origin
    lines = [
        *([single_page.TITLE.format(url=single_page.page_url(result)), single_page.ONLY_THIS_PAGE, ""] if single_page.is_single(result) else []),
        f"Start URL   {result.start_url}",
        *([f"Start       {start_failed_line(start_address(result))}"] if start_address(result) else []),
        f"User agent  {result.user_agent}",
        f"Crawl       stop={result.stop_reason.value} ({result.stop_detail}); "
        f"{pages_phrase(result)} checked, {len(result.requests)} requests, {result.elapsed_s}s",
        *([("Pages read  " if firecrawl.get("purpose") == "main page reader" else "Readable    pages: ") + readable_pages(result, firecrawl)]
          if readable_pages(result, firecrawl) else []),
        "Result      {}: {}".format(*run_outcome(result, gates, firecrawl, checks)[1:]),
        *(f"Covers      {line}" for line in coverage_lines(result, gates, checks, firecrawl)),
        *(f"Time limit  {line}" for line in time_limit_lines(result, checks)),
        "",
    ]
    for gate in gates:
        lines.append(f"{gate.check_id}  {gate.title}")
        lines.append(f"      state: {gate.state.upper()}   confidence: {gate.confidence.value}")
        lines.append(f"      {gate.summary}")
        ev = gate.evidence

        if gate.check_id == "INT-1" and ev.get("pages_fetched"):
            lines.append(
                f"      by class: {ev['by_fetch_class']} · blocked/rate-limited {ev['blocked_or_rate_limited']} "
                f"(verified only {ev['blocked_or_rate_limited_verified_only']}) · threshold {ev['degraded_threshold']}"
            )
            for page in ev["impaired_pages"] + ev["transport_error_pages"]:
                lines.append(
                    f"      - {_short(page['url'], o)}  {page['status'] or '---'}  {page['fetch_class']} "
                    f"[{page['confidence']}]  {'; '.join(page['evidence'])}"
                )
                lines.append(f"          reproduce: {page['reproduce']}")

        if gate.check_id == "INT-2":
            lines.append(
                f"      discovered {ev['urls_discovered']} · fetched {ev['page_fetches']} "
                f"(counted toward cap {ev['pages_counted_toward_cap']}, redirects {ev['redirect_responses']}) · "
                f"skipped by robots {ev['skipped_by_robots']} · not fetched {ev['not_fetched']['count']}"
            )
            sitemap_bits = ", ".join(
                f"{_short(d['url'], o)} {d['status']}{' ' + d['kind'] if d['kind'] else ''}"
                for d in ev["sitemaps"]
            )
            lines.append(
                f"      sitemaps: {sitemap_bits or 'none'} · sitemap URLs listed {ev['sitemap_urls_listed']}, "
                f"fetched {ev['sitemap_urls_fetched']}"
            )
            if ev["fetched_only_via_sitemap"]:
                lines.append(f"      fetched only via sitemap: {[_short(u, o) for u in ev['fetched_only_via_sitemap']]}")
            if ev["not_fetched"]["sample"]:
                lines.append(f"      not fetched (sample): {[_short(u, o) for u in ev['not_fetched']['sample'][:8]]}")
            for caveat in ev["caveats"]:
                lines.append(f"      caveat: {caveat}")

        if gate.check_id == "INT-3":
            templates = ev["templates_not_rendered"]
            lines.append(
                "      templates not rendered (grouping is an estimate): "
                + (", ".join(f"{t['template']} ×{t['pages']}" for t in templates) or "none")
            )
            unrendered = [k for k in ev["key_pages"] if not k["rendered"]]
            if unrendered:
                lines.append(f"      key pages not rendered: {[_short(k['url'], o) for k in unrendered]}"
                             + (" (not fetched by this crawl)"
                                if any(not k["fetched"] for k in unrendered) else ""))

        if gate.check_id == "INT-4":
            for robots in ev["robots"]:
                detail = f"{robots['status'] if robots['status'] is not None else robots['error']}"
                lines.append(f"      robots.txt {_short(robots['url'], o)} → {detail}; mode={robots['mode']}: {robots['reason']}")
                if robots.get("matched_group_kind"):
                    lines.append(
                        f"      group used for {ev['product_token']}: {robots['matched_group_kind']} "
                        f"(user-agent line(s) {robots['matched_group_lines']})"
                    )
            for skip in ev["skipped_by_robots"]:
                lines.append(f"      skipped {_short(skip['url'], o)}: {skip['reason']}")
            lines.append(
                f"      requests by purpose {ev['requests_by_purpose']} · to disallowed URLs "
                f"{len(ev['requests_to_disallowed_urls'])} · before robots.txt {len(ev['requests_before_robots'])} · "
                f"min gap {ev['politeness']['min_observed_gap_ms']}ms (required {ev['politeness']['required_gap_ms']}ms)"
            )

        if gate.how_to_fix:
            lines.append(f"      fix: {gate.how_to_fix}")
        lines.append("")
    if checks:
        lines.append(render_checks(result, checks))
    return "\n".join(lines)


NOT_RECORDED = "not recorded"
_PROVENANCE: dict[str, Any] | None = None


def _git_head(root: Path) -> str | None:
    """The commit checked out at `root`, read from the files (no git program needed): `.git` is a folder, or in a
    worktree a file naming one ("gitdir: ..."). None when there is no repository or it cannot be read."""
    try:
        git = root / ".git"
        if git.is_file():
            line = git.read_text(encoding="utf-8").strip()
            if not line.startswith("gitdir:"):
                return None
            git = (root / line.partition(":")[2].strip()).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if re.fullmatch(r"[0-9a-f]{40}", head) else None
        ref = head.partition(":")[2].strip()
        common = git
        if (git / "commondir").is_file():  # a worktree keeps its branches in the main repository
            common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve()
        for folder in (git, common):
            if (folder / ref).is_file():
                return (folder / ref).read_text(encoding="utf-8").strip()
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                sha, _, name = line.partition(" ")
                if name.strip() == ref:
                    return sha
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return None


def _checkout_root(root: Path) -> Path:
    """The folder holding `.git` for a source tree at `root`. The project lives in a subfolder of its repository
    (tools/maya-audit), so a source tree (it has pyproject.toml) looks upward; anything else, such as an installed
    package inside a virtual environment, is only looked at itself, so it never picks up an unrelated repository."""
    if (root / ".git").exists() or not (root / "pyproject.toml").is_file():
        return root
    return next((p for p in root.parents if (p / ".git").exists()), root)


def source_provenance(root: Path | None = None) -> dict[str, Any]:
    """Where the engine's code came from (CR-25, C62): the git commit when it runs from a checkout, else the base commit
    and release named in RELEASE-SNAPSHOT.json beside the package, else "not recorded". Read once per process; never
    fails an audit. A snapshot's base commit is the commit its files were taken from, not proof of an unchanged tree."""
    global _PROVENANCE
    if root is None and _PROVENANCE is not None:
        return dict(_PROVENANCE)
    default = root is None
    root = Path(__file__).resolve().parent.parent if root is None else Path(root)
    out: dict[str, Any] = {"source_commit": NOT_RECORDED, "source_kind": NOT_RECORDED, "release": None, "base_commit": None}
    try:
        snapshot = json.loads((root / "RELEASE-SNAPSHOT.json").read_text(encoding="utf-8"))
        if isinstance(snapshot, dict):
            out["release"] = snapshot.get("release")
            out["base_commit"] = snapshot.get("base_commit")
    except (OSError, ValueError):
        pass
    head = _git_head(_checkout_root(root))
    if head:
        out.update(source_commit=head, source_kind="git checkout (uncommitted changes not recorded)")
    elif out["base_commit"]:
        out.update(source_commit=out["base_commit"], source_kind="RELEASE-SNAPSHOT.json base commit")
    if default:
        _PROVENANCE = out
    return dict(out)


def generation_metadata(result, reader=None):
    """Source-scoped bookkeeping; probe/request/page counters are deliberately not forced to agree."""
    from datetime import datetime, timezone
    from collections import Counter
    from . import __version__
    requests = getattr(result, 'requests', None)
    purposes = Counter((r.get('purpose') if isinstance(r,dict) else getattr(r,'purpose','unknown')) for r in requests or [])
    coverage = (reader or {}).get('coverage') or {}
    provenance = source_provenance()
    return {'engine_version': __version__, 'processed_at': datetime.now(timezone.utc).isoformat(),
            # Which code wrote this report (CR-25): a commit, or "not recorded"; never a reason for the audit to fail.
            'source_commit': provenance['source_commit'], 'source_provenance': provenance,
            'native_started_at': result.started_at, 'native_finished_at': getattr(result,'finished_at',None),
            'native_stop': {'reason': getattr(result.stop_reason,'value',result.stop_reason), 'detail':getattr(result,'stop_detail',None)},
            'native_page_cap': (getattr(result,'config',None) or {}).get('max_pages'),
            'native_page_records':len(result.pages), 'native_requests_by_purpose':dict(purposes) if requests is not None else None,
            'reader': {'page_cap':(reader or {}).get('page_cap'), 'requests_sent':(reader or {}).get('requests_sent'),
                       'total_request_allowance': (reader['page_cap']+1) if isinstance((reader or {}).get('page_cap'),int) else None,
                       'bootstrap_request_reserve':1 if reader else None,
                       'page_requests':coverage.get('page_requests'), 'requests_without_a_new_page':coverage.get('requests_without_a_new_page'),
                       'stop_reason':coverage.get('not_requested_because'), 'stop_detail':(reader or {}).get('stopped_because'),
                       'bootstrap_requests':'not separately recorded' },
            'scope_note':'Native crawl finish is not whole-job finish. Main-page scope, sitemap/link probes, render subresources, reader retries and provider budgets are separate.'}
