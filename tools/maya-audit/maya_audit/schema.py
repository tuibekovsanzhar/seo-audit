"""The shape of the JSON report, frozen under a version number.

Anything that reads a report (the web interface, a script, a later version of this tool) reads
`schema_version` first. The shape below is what that number promises: which keys a report has and which
fields every gate, check, finding, review item, crawl and page record carries. It is derived from the code,
compared in the tests with the frozen copy in docs/report-schema-<version>.json, and described in
docs/REPORT-SCHEMA.md.

To change the shape: change the code, raise SCHEMA_VERSION (the first number when a field is removed,
renamed or changes meaning; the second when one is added), run `python -m maya_audit.schema` to write the
new frozen copy, and describe the change in docs/REPORT-SCHEMA.md. The tests fail until all three agree.

Not covered, on purpose: what is inside a finding's or a check's `evidence`, a page's `analysis`, and the
data collected for one check family (`crawl.access`, `crawl.index`, ...). Those differ from check to check
and are for people and for the check that wrote them, not for a program to rely on.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from .findings import STATUSES, CheckResult, Finding, ReviewItem, Severity
from .brand import FOUND_IN as BRAND_FOUND_IN, SOURCES as BRAND_SOURCES
from .index_data import HTTP_REDIRECT_LINES
from .models import (Confidence, CrawlResult, FetchClass, GateResult, PageFetch, RequestRecord, SitemapDoc, SkippedUrl,
                     StopReason)

SCHEMA_VERSION = "1.29"

# Always present.
REPORT_KEYS = ("generation", "schema_version", "report_version", "status_meanings", "scope", "gates", "checks", "answer_engine_panel",
               "findings_in_priority_order", "needs_human_review", "page_counts", "brand", "problem_summary", "time_limit_cuts", "audit_status",
               "crawl",
               # What the release gate decided about this report (maya_audit.release_gate, DECISIONS 278), 1.20.
               "release_gate")
# Present only when the run produced them.
OPTIONAL_REPORT_KEYS = ("dataforseo", "firecrawl", "archives", "crux", "ownership", "evidence_saved", "migrated",
                        # The platform and CDN the pages show: {"name", "cdn", "signals"} (H34).
                        "platform")
PAGE_COUNT_KEYS = ("pages_checked", "redirects")
# The brand name the audit used (maya_audit.brand.resolve), schema 1.14. `source` is "typed", "site", "domain" or None;
# `found_in` says where a name read from the site was found; `pages` how many pages gave it.
BRAND_KEYS = ("name", "source", "confirmed", "found_in", "pages")
# The totals and the problems by page (maya_audit.report.problem_summary), schema 1.9.
# `files` (1.11): addresses that are files, not pages (a sitemap, robots.txt, a document), with the same row shape as
# `by_page`. `pages_checked` counts pages, not addresses (maya_audit.report.read_counts).
# `start_address` (1.14): only when the start address answered 400-599 and the audit ran from another page.
PROBLEM_SUMMARY_KEYS = ("pages_checked", "problems", "notes", "by_severity", "whole_site", "by_page", "files", "not_listed", "page_checks", "single_page",
                        "start_address")
PROBLEM_START_ADDRESS_KEYS = ("entered", "status", "audited_from")
# How many of the page checks could run (maya_audit.report.page_checks), schema 1.11.
PROBLEM_PAGE_CHECKS_KEYS = ("total", "could_run", "limited")
PROBLEM_WHOLE_SITE_KEYS = ("problems", "worst_severity", "finding_ids", "shared_elements")
# A site-wide problem that one shared header or footer element causes on most pages (maya_audit.shared_elements), 1.11.
# `element` holds `type` ("link", "image", "heading"), then `href`, `src` or `text`, and `where`.
PROBLEM_SHARED_ELEMENT_KEYS = ("finding_id", "kind", "element", "pages")
SHARED_ELEMENT_KINDS = ("link_no_text", "link_no_address", "heading_jump", "heading_jump_varied", "image_no_alt",
                        "links_no_address", "link_generic", "link_no_text_pattern")
SHARED_ELEMENT_WHERE = ("header", "nav", "footer", "aside", "repeated")
# `audit_status.content_coverage` (maya_audit.report.audit_status). `pages_read`, `other_addresses`, `unread_left_out`
# and the `firecrawl_only` and `total` of `read_by` are 1.11; `readable_unique_urls` holds the same number as `pages_read`.
CONTENT_COVERAGE_KEYS = ("level", "pages_read", "readable_unique_urls", "read_by", "other_addresses", "page_requests_by_maya",
                         "discovered_urls", "known_urls_not_read", "unread_left_out", "key_pages_not_read", "reasons", "note")
READ_BY_KEYS = ("maya_only", "firecrawl_only", "both", "firecrawl", "total")
OTHER_ADDRESSES_KEYS = ("files", "same_page")
UNREAD_LEFT_OUT_KEYS = ("robots_disallowed", "not_a_page")
# `firecrawl.coverage` after a reading (maya_audit.firecrawl.reader). `sitemap_addresses_found` is what the reader
# itself found when it was asked for the sitemap; `sitemap_addresses_known` (1.11) what Maya's own crawl knew.
FIRECRAWL_COVERAGE_KEYS = ("attempted", "read", "page_cap", "cap_reached", "known_urls_not_requested", "not_requested_because",
                           "requested_without_a_readable_document", "causes", "sections_sampled", "sitemap_addresses_found",
                           "sitemap_addresses_known", "page_requests", "requests_without_a_new_page", "unread_left_out",
                           "answered_with_an_error_status", "status_unknown", "from_cache", "key_pages_not_read",
                           "indexability_disagreements", "indexability_disagreements_count", "examples_not_requested", "elapsed_s",
                           # 1.21 (DECISIONS 294): the reader's measured pace, the assumed one, the pages the time limit
                           # left unread, and whether it read beside Maya's own steps.
                           "seconds_per_page_measured", "call_seconds_measured", "seconds_per_page_assumed", "skipped_for_time",
                           "ran_beside_maya",
                           # 1.28 (DECISIONS 317): how the plan's one page limit was shared; block answers never count.
                           "page_limit",
                           # 1.22 (DECISIONS 295): calls that timed out: pages asked for once more, read on that try, skipped.
                           "timeouts")
# Why known addresses were not asked for. "request_allowance_used" (1.11): the audit's request allowance was spent
# before the pages read reached the cap. None when nothing was left.
NOT_REQUESTED_BECAUSE = ("page_cap", "time_limit", "stopped_on_request", "reader_kept_failing", "request_allowance_used",
                         "credit_or_request_limit", "provider_timeout", "provider_error", "not_reached")
PROBLEM_PAGE_KEYS = ("url", "problems", "worst_severity", "finding_ids", "items")
# What one problem is on one page (maya_audit.report.page_item), schema 1.10. `kind` is a key of report.PAGE_KINDS;
# what is inside `values` differs from kind to kind.
PROBLEM_PAGE_ITEM_KEYS = ("finding_id", "check_id", "severity", "kind", "values")
PROBLEM_NOT_LISTED_KEYS = ("finding_id", "pages")
TIME_LIMIT_CUT_KEYS = ("collector", "reason", "checks_not_run", "checks_run_on_fetched_pages_only")
SCOPE_KEYS = ("kind", "count", "urls")
COVERAGE_KEYS = ("not_assessed", "rule")
DATAFORSEO_KEYS = ("source", "audit_id", "panel", "confidence", "target", "status", "checks", "calls", "requests_sent",
                   "estimated_usd", "cost_usd", "relevance",
                   # Only when requests were left out because of the account's balance: why, after which check, and which.
                   "stopped", "note")
DATAFORSEO_STATUSES = ("assessed", "partly_assessed", "not_assessed")
# The two commands save evidence slightly differently; these are the keys both write.
EVIDENCE_SAVED_KEYS = ("folder", "mode", "pages", "not_saved", "total_bytes")
# The optional `firecrawl` section (maya_audit.firecrawl.panel.SECTION_KEYS). Not every key is in every report.
FIRECRAWL_KEYS = ("source", "enabled", "used", "purpose", "reason", "notice", "options", "proxy", "owner_approved_bypass",
                  "zero_data_retention", "page_cap", "crawl_blocked", "robots", "pages", "rendered", "pages_read",
                  "skipped_by_robots", "pages_blocked_for_firecrawl_too", "checks_from_firecrawl", "needs_decision",
                  "stopped_because", "errors", "calls", "requests_sent", "credits", "usd", "coverage", "sitemap", "unsupported_resources",
                  # 1.21 (DECISIONS 294): requests in flight at once, and each step down after a 429, a 5xx or a slow answer.
                  "concurrency")
# Archived copies (maya_audit.archives): a free fallback when nothing could read the live site.
ARCHIVES_KEYS = ("enabled", "cost_usd", "page_cap", "sources", "notice", "requests_sent", "downloaded_bytes", "fetched_at")
# Core Web Vitals from the Chrome UX Report (maya_audit.crux). Not every key is in every report.
CRUX_KEYS = ("source", "status", "summary", "metrics", "origin", "form_factor", "data_until", "fetched_at", "passes_core_web_vitals")
# Site ownership verification (maya_audit.ownership).
OWNERSHIP_KEYS = ("verified", "method", "token", "checked_at", "summary", "instructions")
# Left out of the written report by models.to_jsonable.
UNWRITTEN = ("robots_policy_by_origin",)


def _fields(record: type) -> list[str]:
    return [f.name for f in fields(record) if not f.name.startswith("_") and f.name not in UNWRITTEN]


def shape() -> dict[str, Any]:
    """The report's shape as plain data: key lists and the fixed vocabularies."""
    return {
        "schema_version": SCHEMA_VERSION,
        "report": {"required": list(REPORT_KEYS), "optional": list(OPTIONAL_REPORT_KEYS)},
        "gate": _fields(GateResult),
        "check": _fields(CheckResult),
        "finding": _fields(Finding),
        "review_item": _fields(ReviewItem),
        "scope": list(SCOPE_KEYS),
        "coverage": list(COVERAGE_KEYS),
        "page_counts": list(PAGE_COUNT_KEYS),
        "brand": list(BRAND_KEYS),
        "problem_summary": list(PROBLEM_SUMMARY_KEYS),
        "problem_whole_site": list(PROBLEM_WHOLE_SITE_KEYS),
        "problem_shared_element": list(PROBLEM_SHARED_ELEMENT_KEYS),
        "problem_page": list(PROBLEM_PAGE_KEYS),
        "problem_page_item": list(PROBLEM_PAGE_ITEM_KEYS),
        "problem_not_listed": list(PROBLEM_NOT_LISTED_KEYS),
        "problem_page_checks": list(PROBLEM_PAGE_CHECKS_KEYS),
        "problem_start_address": list(PROBLEM_START_ADDRESS_KEYS),
        "time_limit_cut": list(TIME_LIMIT_CUT_KEYS),
        "content_coverage": list(CONTENT_COVERAGE_KEYS),
        "read_by": list(READ_BY_KEYS),
        "other_addresses": list(OTHER_ADDRESSES_KEYS),
        "unread_left_out": list(UNREAD_LEFT_OUT_KEYS),
        "firecrawl_coverage": list(FIRECRAWL_COVERAGE_KEYS),
        "crawl": _fields(CrawlResult),
        "page": _fields(PageFetch),
        "request": _fields(RequestRecord),
        "sitemap_doc": _fields(SitemapDoc),
        "skipped_url": _fields(SkippedUrl),
        "dataforseo": list(DATAFORSEO_KEYS),
        "firecrawl": list(FIRECRAWL_KEYS),
        "archives": list(ARCHIVES_KEYS),
        "crux": list(CRUX_KEYS),
        "ownership": list(OWNERSHIP_KEYS),
        "evidence_saved": list(EVIDENCE_SAVED_KEYS),
        "vocabulary": {
            "check_status": list(STATUSES),
            "severity": [s.value for s in Severity],
            "confidence": [c.value for c in Confidence],
            "fetch_class": [c.value for c in FetchClass],
            "stop_reason": [r.value for r in StopReason],
            "dataforseo_status": list(DATAFORSEO_STATUSES),
            "shared_element_kind": list(SHARED_ELEMENT_KINDS),
            "shared_element_where": list(SHARED_ELEMENT_WHERE),
            "not_requested_because": list(NOT_REQUESTED_BECAUSE),
            # What http:// does on one host, in the evidence of IDX-2's redirect finding (`hosts[].outcome`), 1.13.
            "http_redirect_outcome": list(HTTP_REDIRECT_LINES),
            # Where the audit's brand name came from (`brand.source`, `brand.found_in`), 1.14.
            "brand_source": list(BRAND_SOURCES),
            "brand_found_in": list(BRAND_FOUND_IN),
        },
    }


def frozen_path(version: str = SCHEMA_VERSION) -> Path:
    return Path(__file__).resolve().parent.parent / "docs" / f"report-schema-{version}.json"


def differences(old: Any, new: Any, at: str = "") -> list[str]:
    """Plain lines saying what differs between two shapes."""
    if isinstance(old, dict) and isinstance(new, dict):
        lines = []
        for key in sorted(set(old) | set(new)):
            where = f"{at}.{key}" if at else key
            if key not in new:
                lines.append(f"{where}: removed")
            elif key not in old:
                lines.append(f"{where}: added")
            else:
                lines += differences(old[key], new[key], where)
        return lines
    if isinstance(old, list) and isinstance(new, list):
        removed, added = [x for x in old if x not in new], [x for x in new if x not in old]
        lines = ([f"{at}: removed {removed}"] if removed else []) + ([f"{at}: added {added}"] if added else [])
        return lines or ([f"{at}: order changed"] if old != new else [])
    return [] if old == new else [f"{at}: {old!r} -> {new!r}"]


def version_key(version: str) -> tuple[int, ...]:
    """A schema version as numbers, for telling which of two is newer: "1.10" comes after "1.9" (as text it would
    not). Anything that is not numbers separated by dots sorts first."""
    try:
        return tuple(int(part) for part in version.split("."))
    except (AttributeError, ValueError):
        return ()


def unsupported_reason(report: dict[str, Any]) -> str | None:
    """Why a program written for this schema should not read `report`, or None when it can.

    Same first number: readable (a higher second number only adds fields)."""
    version = report.get("schema_version")
    if not isinstance(version, str):
        return "the report has no schema_version (it was written before the format was frozen)"
    if version_key(version)[:1] != version_key(SCHEMA_VERSION)[:1]:
        return f"the report is schema {version}; this version of the tool reads {SCHEMA_VERSION.split('.')[0]}.x"
    return None


if __name__ == "__main__":  # write the frozen copy for the current version
    path = frozen_path()
    path.write_text(json.dumps(shape(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")
