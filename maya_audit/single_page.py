"""A single-page audit: one address is read and checked, and the report says so (Owner, 2026-10-13).

The crawl reads the address given and nothing else (`CrawlConfig.single_page`: no link is followed, no sitemap is
asked for, the page cap is 1). The checks then need three rules of their own, or one page would be judged as if it
were a site:

- A check that compares the pages of a site (duplicates, orphans, shared descriptions, "no About page was found",
  the sitemap's coverage) has nothing to compare. It is not assessed, with that reason, and is not counted among the
  page checks that "could not run".
- A check about the homepage (its Organization data, the brand in its title, its main heading) applies only when the
  page audited is the homepage. On any other page the homepage findings are left out; a missing <h1> is still
  reported, as the ordinary finding it is on any page.
- What the page depends on that belongs to the site (robots.txt rules, the redirects that lead to the page,
  http:// to https:// on its host) is still checked. Those findings are site-wide in scope, and every output labels
  them "site-level".

`settle` is applied when the checks are first built and again after a page reader has replaced the content checks.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .access_data import homepage_url
from .findings import CheckResult, Severity
from .models import CrawlResult

# Checks whose question is about several pages of a site together.
COMPARES_PAGES = ("IDX-5", "IDX-7", "IDX-8", "STR-16", "STR-17", "STR-21", "STR-22", "STR-23")
NOT_APPLICABLE = ("Not assessed in a single-page audit: this check compares the pages of a site, and only one page was read.")
NOT_THE_HOMEPAGE = "Not assessed: the page audited is not the site's homepage, and this check is about the homepage."
# What the report says about its own scope, in every output (English; maya_audit_web words it for the reader).
TITLE = "Single-page audit: {url}"
ONLY_THIS_PAGE = "Only this page was read; other pages of the site were not checked."
SITE_LEVEL = "Site-level (affects this page)"
OUTCOME = ("Single-page audit: the page was read and every check that applies to one page ran. Other pages of the site "
           "were not checked.")
COVERAGE = "1 page was read: the one this single-page audit was asked for. Other pages of the site were not checked."
MARK = "single_page"  # in a settled check's evidence: why it was not assessed


def is_single(result: CrawlResult | None) -> bool:
    return bool(((getattr(result, "config", None) or {}).get("single_page")))


def page_url(result: CrawlResult) -> str:
    """The page audited: the address given, or where its redirects landed."""
    return homepage_url(result)


def is_homepage(result: CrawlResult) -> bool:
    """Whether the page audited is the site's homepage: its path is the root."""
    return urlsplit(page_url(result)).path in ("", "/")


def settle(checks: list[CheckResult], result: CrawlResult) -> None:
    """Apply the single-page rules to the checks, in place. Does nothing for an ordinary audit, and nothing twice."""
    if not is_single(result):
        return
    home = is_homepage(result)
    for check in checks:
        if check.check_id in COMPARES_PAGES:
            _not_assessed(check, NOT_APPLICABLE, "compares_pages")
        elif not home and check.check_id == "STR-18":
            _not_assessed(check, NOT_THE_HOMEPAGE, "not_the_homepage")
        elif not home:
            kept, left_out = [], []
            for finding in check.findings:
                if check.check_id == "STR-3" and finding.title == "The homepage has no Organization structured data":
                    left_out.append(finding.title)
                    continue
                if check.check_id == "STR-2" and finding.title == "The homepage has no <h1>":
                    # Still a page without a main heading: said as it is said of any page, at that finding's severity.
                    finding.title, finding.severity = "1 page(s) have no <h1>", Severity.S4
                    finding.expected, finding.how_to_fix = "one <h1> naming the page topic", "Add one <h1> that names the page's topic."
                kept.append(finding)
            if check.check_id == "STR-3":  # P2: the WebSite observation is about the homepage too
                check.observations = [o for o in check.observations
                                      if o.get("metric") != "homepage with no WebSite structured data"]
            if left_out:
                check.findings = kept
                check.evidence = {**(check.evidence or {}), "homepage_findings_left_out": left_out, "left_out_because": NOT_THE_HOMEPAGE}
                if not kept and check.status == "findings":
                    check.status = "pass"
                    check.summary = "No finding on the page audited. " + NOT_THE_HOMEPAGE


def _not_assessed(check: CheckResult, reason: str, why: str) -> None:
    if (check.evidence or {}).get(MARK):
        return
    check.status, check.summary, check.findings, check.review_items = "not_assessed", reason, [], []
    check.evidence = {**(check.evidence or {}), MARK: why}
    check.coverage = {}


def not_applicable(check: Any) -> bool:
    """A check a single-page audit set aside: it is not one of the page checks that "could not run"."""
    evidence = (check.get("evidence") if isinstance(check, dict) else getattr(check, "evidence", None)) or {}
    return bool(evidence.get(MARK))
