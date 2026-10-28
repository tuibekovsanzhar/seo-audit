"""What Firecrawl is used for in an audit, and the walls around it.

Two uses, both off unless the person switched Firecrawl on for that audit and confirmed its cost:

1. Content reader for a blocked site. Maya's own crawler has already run and its result stands: the block is
   reported (INT-1, ACC-9), and nothing here touches an access, robots.txt, header, redirect or timing check.
   If, and only if, that crawl was blocked or degraded, Firecrawl reads the homepage and the pages found from it,
   within the page cap and only where robots.txt allows. Those pages feed the content and structure checks
   (STR, TSEO-1, IDX-8) and nothing else. Every result built from them says so.

2. Rendering fallback. When the local browser cannot start, Firecrawl renders the pages the audit would have
   rendered, and the rendering checks (RND) run on the pair of Maya's raw HTML and Firecrawl's rendered HTML.

What a site's bot protection decided is respected by default: the proxy is "basic". The stronger proxies are used
only when the audit records that the site owner approved it.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from ..access_data import homepage_url, key_page_urls
from ..analysis import analyze_html
from ..classify import classify_fetch, empty_response
from ..config import CrawlConfig
from ..content_provider import (ContentLoadError, ContentProvider, ContentProviderError, ProviderIdentity,
                                ProviderLimitReached, ProviderRetentionRequired)
from ..coverage import settle_all
from ..directives import META_NAMES, noindex_directives
from ..fetcher import utc_now
from ..findings import CheckResult, check_id_key
from ..html_links import extract_link_edges
from ..models import Confidence, CrawlResult, FetchClass, PageFetch, StopReason
from ..robots import policy_from_response
from ..urls import non_page_kind, normalize_url, origin_of, same_origin
from . import settings
from .client import FirecrawlClient, ZeroDataRetentionUnavailable
from .reading import SITEMAP_MIN_CAP, ReadingQueue, discover_through_reader
from .settings import Options

SOURCE = "Source: Firecrawl (Maya's crawler was blocked)"
RENDER_SOURCE = "Source: Firecrawl rendered these pages (the local browser could not start)"
AI_NOTICE = ("AI crawlers may not see this content: it was read through a third-party reader after the site refused "
             "Maya's own crawler, and a crawler that says who it is may be refused the same way.")
# Checks that read page content only. Everything else (access, robots.txt, status codes, redirects, canonicals read
# from headers, timing, integrity) stays exactly as Maya's own crawler found it.
CONTENT_CHECKS = ("IDX-8", *(f"STR-{n}" for n in range(1, 24)), "TSEO-1")
# Firecrawl as the page reader of every audit: the label is the plain source, with no warning about AI crawlers.
MAIN_SOURCE = "Source: Firecrawl"
MAIN_WHY = "Firecrawl is the page reader for this audit"
MAIN_PURPOSE = "main page reader"
MAIN_NOTICE = ("Page content was read through Firecrawl, a third-party page reader. robots.txt, the sitemap, redirects, HTTP headers, "
               "response timing and the bot-access test are Maya's own direct requests. Firecrawl's document may already hold what "
               "JavaScript added, so it does not show what a crawler that runs no JavaScript receives, and reading it says nothing "
               "about whether AI crawlers are let in.")
USER_AGENT_LABEL = "Firecrawl"
# When the first pages asked for all come back unreadable, Firecrawl is being turned away as well: stop there
# instead of paying for a challenge page per address.
GIVE_UP_AFTER_UNREAD = 3
# The words of the client's refusal when an audit's request allowance is used (maya_audit.firecrawl.client).
REQUEST_ALLOWANCE = "request allowance"


def crawl_was_blocked(result: CrawlResult, cfg: CrawlConfig) -> tuple[bool, str]:
    """INT-1's own rule: the start page was blocked or rate-limited, or at least the threshold share of pages was."""
    pages = [p for p in result.pages if not (p.status is not None and 300 <= p.status < 400)]
    impaired = [p for p in pages if p.fetch_class in (FetchClass.BLOCKED, FetchClass.RATE_LIMITED)]
    start = next((p for p in result.pages if p.url == homepage_url(result)), None)
    if start is not None and start in impaired:
        return True, "the start page was blocked or challenged"
    if pages and len(impaired) / len(pages) >= cfg.degraded_threshold:
        return True, f"{len(impaired)} of {len(pages)} pages were blocked or challenged"
    return False, NOT_BLOCKED_WHY


NOT_BLOCKED_WHY = "Maya's own crawler read the site, so Firecrawl was not used"
# The same fact when Firecrawl is the page reader of every audit: it was used, and not because of a block.
MAIN_READER_NOT_BLOCKED_WHY = "Maya's own crawler read the site; Firecrawl read the pages as this audit's main page reader"
# How many pages whose two copies disagree on indexability are listed in the report (the count is always exact).
DISAGREEMENTS_LISTED = 40


NO_DOCUMENT = "Firecrawl returned no document"


def also_blocked(info: dict[str, Any]) -> bool:
    """Whether Firecrawl was turned away too: Maya's crawl was blocked, Firecrawl was asked, and every answer was a
    challenge page, an error page or no document at all. A refusal about the account (credits, key, zero data
    retention, a stop) is not this. Reads only what the report's section holds, so a saved report answers the same."""
    if info.get("errors") or info.get("used") or info.get("needs_decision") or not (info.get("crawl_blocked") or {}).get("blocked"):
        return False
    robots = info.get("robots") or {}
    rows = info.get("pages") or []
    if not rows:
        return robots.get("source") == "Firecrawl" and robots.get("mode") != "disallow_all" and robots.get("read") is False and (
            "status" in robots or NO_DOCUMENT in (robots.get("reason") or ""))
    return all(row.get("outcome") in ("blocked", "error") or (row.get("outcome") == "failed" and NO_DOCUMENT in (row.get("reason") or ""))
               for row in rows)


def _unread_counts(rows: list[dict[str, Any]]) -> str:
    challenged = sum(1 for row in rows if row["outcome"] == "blocked")
    empty = len(rows) - challenged
    parts = [f"{challenged} came back as a challenge or block page" if challenged else "", f"{empty} came back as an error or no document" if empty else ""]
    return f"{len(rows)} page(s) tried, " + " and ".join(part for part in parts if part)


def _robots_rules(result: CrawlResult, client: ContentProvider, info: dict[str, Any], product_token: str):
    """Reuse Maya's policy; if absent, apply the same policy to Firecrawl's target response.

    Provider API errors are not target robots.txt responses. In particular an API
    403 (credentials/ZDR) never grants permission to request site pages.
    """
    origin = result.origin
    policy = (result.robots_policy_by_origin or {}).get(origin)
    source = "Maya's own crawler"
    own_attempt = None
    if policy is not None and policy.mode == "not_checked":
        # Maya's own request got no answer on this computer: that is no rule of the site's. The reader asks for
        # robots.txt itself, and RFC 9309 is applied to the answer it gets.
        own_attempt, policy = policy.reason, None
    if policy is None:
        source = client.identity.name
        try:
            page = client.scrape(origin + "/robots.txt")
        except ContentProviderError as exc:
            info["robots"] = {"source": source, "read": False, "mode": "disallow_all", "reason": str(exc)}
            if own_attempt:
                info["robots"]["mayas_own_attempt"] = own_attempt
            if isinstance(exc, ContentLoadError):
                info.setdefault("errors", []).append(exc.diagnostic(origin + "/robots.txt"))
            if isinstance(exc, ProviderRetentionRequired):
                raise
            return None
        policy = policy_from_response(origin + "/robots.txt", page.status, None,
                                      _plain_text(page.html).encode("utf-8"), 500 * 1024, [])
        if policy.mode == "not_checked":  # an answer with no HTTP status: its rules are not known, so nothing is asked for
            policy.reason = f"robots.txt came back through {source} without an HTTP status, so its rules are not known"
    info["robots"] = {"source": source, "read": policy.mode == "parsed", "status": policy.status,
                      "mode": policy.mode, "reason": policy.reason}
    if own_attempt:
        info["robots"]["mayas_own_attempt"] = own_attempt
    if policy.stops_requests:
        return None
    return lambda url: policy.decide(product_token, url).allowed


def _plain_text(text: str) -> str:
    """robots.txt as text: a reader may hand it back wrapped in <pre>."""
    import html

    inner = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.IGNORECASE | re.DOTALL)
    return html.unescape(inner.group(1) if inner else text)


def _page_from(url: str, fetched, origin: str, cfg: CrawlConfig, via: str, depth: int, provider_name: str = USER_AGENT_LABEL,
               document_url: str | None = None) -> tuple[PageFetch, str]:
    """A page record built from what a reader returned, and how it was judged: "read", "blocked" or "error".

    The HTTP status is the provider's report of it, or None when the provider reported none: never a stand-in 200.
    `document_url` is the address the document was served from when that differs from `url` (a www twin): links and
    same-page anchors in the document are relative to it."""
    body = fetched.html.encode("utf-8", "ignore")
    known = fetched.status is not None
    # The body is checked for a challenge page whatever the status; a missing status is classified as an ordinary answer.
    judged = classify_fetch(fetched.status if known else 200, {}, body, None)
    page = PageFetch(
        url=url, discovered_via=via, depth=depth, requested_at=fetched.fetched_at, user_agent=provider_name,
        status=fetched.status if known else None, error=None, elapsed_ms=0.0, content_type=fetched.content_type or "text/html",
        body_bytes=len(body), body_truncated=False, headers={}, fetch_class=judged.fetch_class,
        classification_confidence=Confidence.ESTIMATED,
        classification_evidence=[f"read through {provider_name}", *([] if known else ["HTTP status not reported by the reader"]), *judged.evidence],
        view="provider", content_checks_eligible=judged.fetch_class == FetchClass.OK)
    if judged.fetch_class != FetchClass.OK:
        return page, "blocked"
    if (known and not 200 <= page.status < 300) or not fetched.html.strip():
        return page, "error"
    if empty_response(page.status if known else 200, page.content_type, body, False, cfg.empty_response_max_bytes):
        return page, "error"  # a 2xx document with nothing in it: cause "empty_document" (DECISIONS 204)
    base = document_url or url
    page.analysis = analyze_html(fetched.html, base)  # the reader's HTML has absolute addresses: see analysis.dead_link_kind
    edges = extract_link_edges(fetched.html, base, cfg.max_anchor_texts_per_target)
    page.links_found = len(edges)
    page.outlinks = [e for e in edges if _in_scope(e["target"], origin)][:cfg.max_outlinks_per_page]
    page.external_links = [e for e in edges if not _in_scope(e["target"], origin)][:cfg.max_external_links_per_page]
    return page, "read"


def page_cause(row: dict[str, Any]) -> str | None:
    """Why a page that was asked for is not among the pages read: one word a person can act on. None when it was read."""
    outcome, status = row.get("outcome"), row.get("status")
    if outcome in ("read", "unsupported_resource"):
        return None
    if outcome == "blocked":
        return "reader_challenged"            # the site turned the reader away as well
    if outcome == "redirected_out_of_scope":
        return "redirect_to_another_site"
    if outcome == "redirected":
        return "redirect_within_the_site"     # read under the address it leads to, when that was allowed and new
    if outcome == "error":
        # Only a 2xx with nothing in it is an empty document (A18); a reader answer with no status says only that.
        if status is None:
            return "no_status"
        return "error_status" if not (isinstance(status, int) and 200 <= status < 300) else "empty_document"
    reason = (row.get("reason") or "").lower()
    if "could not load the page as a website" in reason:
        return "provider_could_not_load"
    if "may have been charged" in reason or "did not answer" in reason:
        return "timeout_or_no_answer"
    if "credit" in reason or "approved" in reason or "budget" in reason or "page cap" in reason or "request allowance" in reason:
        return "credit_or_request_limit"
    return "provider_refused"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _in_scope(url: str, origin: str) -> bool:
    """The audited origin or its www twin: the one host alias a site's own redirect normally makes."""
    return same_origin(url, origin) or (urlsplit(url).scheme in ("http", "https") and _host(url) == _host(origin)
                                        and urlsplit(url).port == urlsplit(origin).port)


def where_it_landed(requested: str, final: str | None, origin: str) -> tuple[str, str | None]:
    """How the address a reader ended on relates to the one asked for.

    ("same", None): no redirect. ("alias", final): the www twin of the same address; the document is this page's.
    ("moved", final): another address of the audited site; the document belongs to that address, not the one asked for.
    ("outside", final): another site, or not a web address at all; the document is not analysed."""
    if final:
        raw = urlsplit(final)
        if raw.scheme not in ("http", "https") or raw.username or raw.password:
            # Not a web address, or one carrying credentials: never followed, and shown without them.
            return "outside", f"{raw.scheme}://{raw.hostname or ''}" if raw.hostname else f"{raw.scheme}:"
    landed = normalize_url(final or "") if final else None
    if not landed or landed == requested:
        return "same", None
    parts = urlsplit(landed)
    if parts.scheme not in ("http", "https") or parts.username or parts.password or _host(landed) != _host(origin):
        return "outside", landed
    asked = urlsplit(requested)
    same_place = (parts.path or "/").rstrip("/") == (asked.path or "/").rstrip("/") and parts.query == asked.query
    return ("alias" if same_place else "moved"), landed


# Findings of a content check that rest on Maya's own requests, not on the reader's document (A19): STR-6's dates from
# the Last-Modified header and from the sitemap. They are not labelled as read through the reader.
NOT_FROM_THE_READER = {"Last-Modified header": "Maya's own response headers", "sitemap <lastmod>": "the sitemap Maya read"}


def _label(checks: list[CheckResult], source: str, why: str, identity: ProviderIdentity = ProviderIdentity("firecrawl", "Firecrawl"),
           notice: str | None = AI_NOTICE) -> None:
    for check in checks:
        check.summary = f"{source}. {check.summary}"
        check.evidence = {**check.evidence, "source": {"reader": identity.id, "why": why, **({"notice": notice} if notice else {})}}
        own = [item for item in [*check.findings, *check.review_items]
               if (item.evidence or {}).get("signal") in NOT_FROM_THE_READER]
        for item in own:
            item.evidence = {**item.evidence, "source": {"reader": "maya", "why": NOT_FROM_THE_READER[item.evidence["signal"]]}}
        for item in [*check.findings, *check.review_items]:
            if item in own:
                continue
            item.evidence = {**item.evidence, "source": {"reader": identity.id, "why": why, **({"label": source, "notice": notice} if identity.id != "firecrawl" and notice else {})}}
        for finding in check.findings:
            if finding in own:
                continue
            finding.notes.insert(0, f"{source}. {notice}" if notice else f"{source}.")


def _usable(page: PageFetch | None) -> bool:
    # An empty page in Maya's own crawl (IDX-1, DECISIONS 204) is the site's answer: the reader is not asked for it.
    return (page is not None and page.fetch_class == FetchClass.OK and page.status is not None and 200 <= page.status < 300
            and page.readable_document())


def _merged(own: PageFetch | None, read: PageFetch, disagreements: list[dict[str, Any]] | None = None) -> PageFetch:
    """One page from two requests: Maya's own answer (status, headers, timing, how it was found) with the content
    Firecrawl read. A page Maya's crawler did not get keeps Firecrawl's record as it is.

    Whether the page may be indexed is the site's answer to a crawler, so Maya's own response decides it (DECISIONS
    167): its headers, and the robots meta tags of its own <head>, replace the reader's. A reader's document may hold
    what a script or an embedded frame added. Where the two copies disagree, the page is listed in `disagreements`."""
    if not _usable(own):
        return read
    analysis, evidence = read.analysis, []
    if own.analysis is not None and analysis is not None:
        mine, theirs = noindex_directives(own.analysis, own.headers), noindex_directives(analysis, read.headers)
        analysis = {**analysis, "meta": [m for m in analysis["meta"] if m["name"] not in META_NAMES]
                    + [m for m in own.analysis["meta"] if m["name"] in META_NAMES]}
        if bool(mine) != bool(theirs):
            if disagreements is not None:
                disagreements.append({"url": own.url, "own": mine, "reader": theirs})
            evidence.append(f"Maya's own copy says {'noindex' if mine else 'index'} and the copy read through {read.user_agent} says "
                            f"{'noindex' if theirs else 'index'}: Maya's own response is the one used")
    # Two requests, said as two: the status, headers and timing are Maya's own request; the document is the reader's.
    # Where the two documents differ in title, canonical or visible text, that is kept beside it (A17): a reader's copy
    # may hold what a script added, and the person reading the report should know the copies were not the same.
    differs: dict[str, Any] = {}
    if own.analysis is not None and analysis is not None:
        for key in ("title", "canonicals"):
            if (own.analysis.get(key) or None) != (analysis.get(key) or None):
                differs[key] = {"own": own.analysis.get(key), "reader": analysis.get(key)}
        if own.analysis.get("text_sha256") and analysis.get("text_sha256") and own.analysis["text_sha256"] != analysis["text_sha256"]:
            differs["visible_text"] = {"own_words": own.analysis.get("visible_words"), "reader_words": analysis.get("visible_words")}
    if analysis is not None:
        analysis = {**analysis, 'content_observation': {'source': read.user_agent, 'reader': 'firecrawl',
                    'url': read.url, 'observed_at': read.requested_at, 'native_requested_at': own.requested_at,
                    **({'differs_from_own_copy': differs} if differs else {})}}
    if differs:
        evidence.append(f"the copy read through {read.user_agent} differs from Maya's own in: {', '.join(differs)}")
    return replace(own, analysis=analysis, links_found=read.links_found, outlinks=read.outlinks, external_links=read.external_links,
                   view="provider", classification_evidence=[
                       *own.classification_evidence,
                       f"document read through {read.user_agent} at {read.requested_at}; status, headers and timing are Maya's own "
                       f"request at {own.requested_at}", *evidence])


def note_the_challenge(checks: list[CheckResult], pages_read: int) -> None:
    """ACC-9, when a reader read the pages anyway: the same observation, shown as a note rather than a headline.

    Nothing measured is changed or removed: who answered, how many of Maya's requests, and how to reproduce it stay in
    the evidence, with the severity the finding had. The note says what was observed and what was not measured. It
    does not say AI crawlers are unaffected, and it does not say nothing needs doing: neither was tested."""
    from ..checks.access import blocker_phrase
    from ..findings import Severity

    for check in checks:
        if check.check_id != "ACC-9" or not check.findings:
            continue
        for finding in check.findings:
            evidence = finding.evidence
            blockers = evidence.get("blocked_by") or []
            top = blockers[0] if blockers else {}
            who = top.get("name") or "The site's bot protection"
            did = "rate-limited" if top.get("kind") == "rate limit" else "challenged"
            hit, asked = evidence.get("pages_blocked_or_challenged"), evidence.get("pages_requested")
            counted = f" on {hit} of {asked} request(s)" if hit and asked else ""
            before = evidence.get("severity_before_reader") or finding.severity.value
            finding.title = (f"{who} {did} Maya's direct crawler{counted}. {pages_read} page(s) were read through Firecrawl instead. "
                             "Genuine AI-crawler access was not measured.")
            finding.severity = Severity.INFO
            finding.importance_tier = 3
            finding.evidence = {**evidence, "read_through": {"reader": "firecrawl", "pages_read": pages_read},
                                "severity_before_reader": before,
                                "shown_as_a_note_because": "the page content was read through a reader (a presentation choice, not a measurement)"}
            finding.how_to_fix = ("Decide with the site's owner whether this protection is intended for crawlers. To have direct access measured, "
                                  "allow Maya's user agent in the firewall or bot-protection rules and run the audit again. To test named crawler "
                                  "user agents, verify ownership so ACC-4 can run. This audit cannot say whether real AI crawlers are let in.")
            finding.notes = [f"Measured: {blocker_phrase(blockers)} answered Maya's own requests{counted}. Firecrawl then read {pages_read} page(s); "
                             "that shows the content is readable through that reader, not that any crawler is let in.",
                             "Not measured: what the AI vendors' own crawlers receive. Maya's crawler is an unverified bot, and a reader's "
                             "success is not evidence about them either. ACC-4, on ownership-verified sites, sends requests under those "
                             "crawlers' names from Maya's own network: a limited probe, not the vendors' real requests."]
        check.summary = (f"1 note: {blocker_phrase((check.evidence or {}).get('blocked_by') or [])} answered Maya's direct crawler; "
                         f"{pages_read} page(s) were read through Firecrawl. Genuine AI-crawler access was not measured.")


def read_blocked_site(result: CrawlResult, cfg: CrawlConfig, client: ContentProvider, options: Options,
                      info: dict[str, Any], *, blocked: bool = True, progress=None, ranking_urls=()) -> list[CheckResult] | None:
    """Read the site's content through Firecrawl and run the content checks on it. None when nothing was read.

    `blocked` False is Firecrawl as the reader of a site Maya's own crawler could read too: the same pages are asked
    for, and each page keeps Maya's own status, headers and timing with the content Firecrawl read."""
    from ..checks.index import idx8_duplicates
    from ..checks.structure import run_structure_checks

    origin, home = result.origin, homepage_url(result)
    allowed = _robots_rules(result, client, info, cfg.product_token)
    if allowed is None:
        info["reason"] = info["robots"]["reason"] + "; no page was requested"
        return None
    # The homepage, the pages the person marked, what Maya's crawler found, then what the pages read lead to: taken in
    # the crawler's own order (key pages, navigation, the least-read section first) rather than first come, first served.
    queue = ReadingQueue(spread=options.spread_by_section)
    queue.add(home, "start", 0)
    for url in ([] if cfg.single_page else key_page_urls(result, cfg)):
        queue.add(url, "key_page", 1)
    for url in ([] if cfg.single_page else ranking_urls):
        if _in_scope(url, origin):
            queue.add(url, "ranking_page", 1)
    own = {} if blocked else {page.url: page for page in result.pages}
    for page in own.values():  # the pages Maya's crawler read
        queue.add(page.url, page.discovered_via, page.depth)
    sitemap_known = set(result.sitemap_urls)
    for url in result.discovered_urls:
        queue.add(url, "sitemap" if url in sitemap_known else "link", 1)
    for url in result.sitemap_urls:
        queue.add(url, "sitemap", None)
    seen: set[str] = set()
    pages: list[PageFetch] = []
    rows = info.setdefault("pages", [])
    skipped_robots = 0
    unread = 0
    run_unreadable = 0
    # Page requests answered (a saved copy counts as asked, not as sent): what the request allowance was spent on.
    asked = sent = 0
    # Maya's own crawler read no sitemap (it was challenged): the reader is asked for one, within its own limits, once
    # it has shown it can read the site at all (after the first page), so nothing is spent on a site that turns it away.
    wants_sitemap = bool(blocked and options.sitemap_discovery and not result.sitemap_urls and options.max_pages >= SITEMAP_MIN_CAP)

    def ask_for_the_sitemap() -> None:
        declared = []
        policy = (result.robots_policy_by_origin or {}).get(origin)
        if policy is not None and getattr(policy, "robots", None) is not None:
            declared = [u for u in (normalize_url(value, origin) for value, _line in policy.robots.sitemaps) if u]
        try:
            found = discover_through_reader(client.scrape, origin, declared, allowed, lambda u: _in_scope(u, origin), options.max_pages)
        except ProviderRetentionRequired:
            raise
        except ContentLoadError as exc:  # the provider could not load it: the pages already known are still read
            found = {"documents": [], "urls": [], "note": f"the sitemap could not be loaded ({exc})"}
        except ContentProviderError as exc:
            # A stop, the deadline, a spending limit or an unanswered (possibly billed) request: nothing more is asked.
            info["sitemap"] = {"documents": [], "addresses_found": 0, "note": f"the sitemap was not read ({exc})"}
            info["stopped_because"] = str(exc)
            return
        info["sitemap"] = {"documents": found["documents"], "addresses_found": len(found["urls"]), "note": found["note"]}
        for address in found["urls"]:
            queue.add(address, "sitemap", None)

    while len(queue) and len(pages) < options.max_pages and not info.get("stopped_because"):
        url, via, depth = queue.pop()
        url = normalize_url(url) or url
        if non_page_kind(url):
            info.setdefault("unsupported_resources", []).append({"url": url, "kind": non_page_kind(url),
                                                                  "source": via, "outcome": "skipped_without_request"})
            continue  # never charged or counted in a failure streak
        if url in seen or not same_origin(url, origin):
            continue
        seen.add(url)
        if url in own and not _usable(own[url]):
            continue  # a redirect or an error page in Maya's own crawl: its status is the finding, there is no content to read
        if not allowed(url):
            skipped_robots += 1
            continue
        queue.taken(url)
        try:
            fetched = client.scrape(url)
        except ProviderLimitReached as exc:
            info["stopped_because"] = str(exc)
            break
        except ProviderRetentionRequired:
            raise
        except ContentLoadError as exc:
            asked += 1
            sent += 1
            info.setdefault("errors", []).append(exc.diagnostic(url))
            rows.append({"url": url, "outcome": "failed", "reason": str(exc)})
            # Try other already-known URLs, never retry this URL or change its proxy.
            # The client still enforces request count, approval, budget and stop.
            run_unreadable += 1
            if pages and options.stop_after_unreadable and run_unreadable >= options.stop_after_unreadable:
                info["stopped_because"] = (f"the last {run_unreadable} pages asked for came back unreadable, so no more were requested")
                break
            continue
        except ContentProviderError as exc:
            rows.append({"url": url, "outcome": "failed", "reason": str(exc)})
            info["stopped_because"] = str(exc)
            break  # an error from the service (no credit, budget, stop) is not something to push through
        asked += 1
        sent += not fetched.cached
        media = str(getattr(fetched, 'content_type', '') or '').lower()
        if media.startswith(('audio/', 'video/')):
            diagnostic = {"url": url, "kind": "media", "source": via, "outcome": "unsupported_resource",
                          "content_type": media, "observed_at": fetched.fetched_at, "from_cache": fetched.cached}
            info.setdefault('unsupported_resources', []).append(diagnostic)
            rows.append(diagnostic)
            continue  # a response identifying non-page media is not a website-reader failure
        # Where the reader ended up decides whose document this is. Another site's page is never analysed as this one's,
        # and a page of this site reached by a redirect is recorded under its own address, with the address asked for.
        if progress is not None:  # each step of the reading, for whoever is watching the audit
            progress({"phase": "firecrawl", "url": url, "attempted": len(rows) + 1, "read": len(pages), "page_cap": options.max_pages,
                      "failed": sum(1 for row in rows if row["outcome"] not in ("read", "redirected")),
                      "from_cache": sum(1 for row in rows if row.get("from_cache")) + int(bool(fetched.cached))})
        relation, landed = where_it_landed(url, getattr(fetched, "final_url", None), origin)
        seen_at = {"status": fetched.status, "status_known": fetched.status is not None, "from_cache": fetched.cached, "observed_at": fetched.fetched_at}
        if relation == "outside":
            rows.append({"url": url, "outcome": "redirected_out_of_scope", "final_url": landed, **seen_at,
                         "reason": "the reader was sent to an address outside the audited site, so its document was not analysed"})
            unread += 1
            continue
        if relation == "moved":
            if landed in seen or not allowed(landed):
                rows.append({"url": url, "outcome": "redirected", "final_url": landed, **seen_at,
                             "reason": "redirects to an address that robots.txt disallows" if not allowed(landed)
                             else "redirects to an address that is read under its own name"})
                continue
            seen.add(landed)
            rows.append({"url": url, "outcome": "redirected", "final_url": landed, **seen_at, "reason": "its document is recorded under the address it redirects to"})
            url, via = landed, "redirect"
        page, outcome = _page_from(url, fetched, origin, cfg, via, depth, client.identity.name, document_url=landed if relation == "alias" else None)
        rows.append({"url": url, "outcome": outcome, "bytes": page.body_bytes, **seen_at,
                     **({"final_url": landed, "host_alias": True} if relation == "alias" else {})})
        if outcome != "read":
            unread += 1
            # An error status is the site's own answer (a dead link): it does not mean the reader is being turned away.
            turned_away = not (outcome == "error" and isinstance(fetched.status, int) and fetched.status >= 400)
            run_unreadable = run_unreadable + 1 if turned_away else run_unreadable
            if not pages and unread >= GIVE_UP_AFTER_UNREAD:
                info["stopped_because"] = (f"the first {unread} pages asked for came back unreadable, so no more were requested")
                break
            if pages and options.stop_after_unreadable and run_unreadable >= options.stop_after_unreadable:
                # The reader was getting pages and now is not: the site has started turning it away, or the provider is
                # failing. Each further request would be paid for and thrown away.
                info["stopped_because"] = (f"the last {run_unreadable} pages asked for came back unreadable, so no more were requested")
                break
            continue
        run_unreadable = 0
        pages.append(page)
        if wants_sitemap and len(pages) == 1:
            ask_for_the_sitemap()
        # A page Maya found only in the sitemap has no click depth; a link from it has none either, rather than a made-up one.
        for edge in page.outlinks:
            if not cfg.single_page:  # a single-page audit reads the page and follows nothing from it
                queue.add(edge["target"], "link", None if depth is None else depth + 1, bool(edge.get("nav")))
    # What is still unread when reading ends: addresses known and never asked for (the cap, a stop, a provider limit),
    # and addresses asked for that gave no readable document.
    # Addresses Maya's own crawl found and did not fetch are known too, whether or not a page the reader read links to them:
    # one count of what is known and unread, not one for each reader.
    known = list(dict.fromkeys([*queue.waiting(), *(normalize_url(u) or u for u in (result.not_fetched_urls or []))]))
    unseen = [u for u in known if u not in seen and _in_scope(u, origin)]
    waiting = [u for u in unseen if allowed(u) and not non_page_kind(u)]
    # Known addresses that are not counted as unread, and why: one figure for "not read", and what it leaves out.
    disallowed = sum(1 for u in unseen if not allowed(u))
    left_out = {"robots_disallowed": disallowed, "not_a_page": len(unseen) - disallowed - len(waiting)}
    # A page that answered with an error status (a 404, a 500) was read: that status is the site's answer, and a broken
    # link is the finding. What counts as unread is a challenge, a provider failure, an empty document, another site.
    answered = [row for row in rows if row["outcome"] == "error" and isinstance(row.get("status"), int) and row["status"] >= 400]
    failed = [row["url"] for row in rows if row["outcome"] not in ("read", "redirected", "unsupported_resource") and row not in answered]
    key = [normalize_url(u) or u for u in key_page_urls(result, cfg)]
    read_urls = {page.url for page in pages}
    for row in rows:  # why each page that was asked for is not among the pages read
        row.setdefault("cause", page_cause(row))
    stopped = info.get("stopped_because") or ""
    why_waiting = (None if not waiting else "page_cap" if len(pages) >= options.max_pages
                   else "time_limit" if "time limit" in stopped else "stopped_on_request" if "stopped on request" in stopped
                   else "reader_kept_failing" if "came back unreadable" in stopped
                   # The request allowance (what is paid for) ran out before the pages read reached the cap: some requests
                   # led to a page already read, or to no page. Not a credit refusal, and not said as one.
                   else "request_allowance_used" if REQUEST_ALLOWANCE in stopped
                   else "provider_timeout" if any(word in stopped.lower() for word in ("timeout", "timed out", "408"))
                   else "credit_or_request_limit" if any(word in stopped.lower() for word in ("credit", "budget", "limit"))
                   else "provider_error" if stopped else "not_reached")
    causes: dict[str, int] = {}
    for row in rows:
        if row["cause"]:
            causes[row["cause"]] = causes.get(row["cause"], 0) + 1
    info.update(pages_read=len(pages), skipped_by_robots=skipped_robots,
                pages_blocked_for_firecrawl_too=sum(1 for row in rows if row["outcome"] == "blocked"),
                coverage={"attempted": len(rows), "read": len(pages), "page_cap": options.max_pages, "cap_reached": len(pages) >= options.max_pages and bool(waiting),
                          "known_urls_not_requested": len(waiting), "not_requested_because": why_waiting,
                          "requested_without_a_readable_document": len(failed), "causes": causes,
                          "sections_sampled": queue.sections_read(),
                          # Found by the reader itself, when it was asked for the sitemap (a challenged site); and what
                          # Maya's own crawl knew from the sitemap, which the reading queue was seeded with either way.
                          "sitemap_addresses_found": (info.get("sitemap") or {}).get("addresses_found", 0),
                          "sitemap_addresses_known": len(result.sitemap_urls or []),
                          "page_requests": sent, "requests_without_a_new_page": max(0, asked - len(pages)),
                          "unread_left_out": left_out,
                          "answered_with_an_error_status": len(answered),
                          "status_unknown": sum(1 for row in rows if row["outcome"] == "read" and not row.get("status_known")),
                          "from_cache": sum(1 for row in rows if row["outcome"] == "read" and row.get("from_cache")),
                          "key_pages_not_read": [u for u in key if u not in read_urls][:50],
                          # Pages whose two copies (Maya's own, the reader's) disagree on noindex; Maya's own is used.
                          "indexability_disagreements": [], "indexability_disagreements_count": 0,
                          "examples_not_requested": waiting[:10]})
    if not pages and info.get("errors"):
        info["reason"] = f"{client.identity.name} could not load the page as a website; see provider errors below"
        return None
    if not pages and info.get("stopped_because") and not rows:
        info["reason"] = f"Firecrawl read nothing: {info['stopped_because']}"
        return None
    if not pages:
        info["reason"] = "there was no page robots.txt allows"
        if rows:
            info["reason"] = (f"Firecrawl {options.proxy} was also blocked: " + _unread_counts(rows)) if also_blocked(info) \
                else "Firecrawl could not read the site either"
        return None
    # The same result, seen through the pages Firecrawl read. Maya's own structure data (its link and image
    # requests) does not apply to these pages and is left out; the checks then report what they could not test.
    unread_urls = [row["url"] for row in rows if row["outcome"] != "read"]
    unread_urls += [url for url in queue.waiting() if url not in seen]
    main = options.read_always
    if blocked:
        view = replace(result, pages=pages, structure=None, render=None,
                       not_fetched_urls=list(dict.fromkeys(unread_urls))[:1000])
    else:
        # Maya's crawl stands, page for page; what Firecrawl read replaces the content, and adds any page only it reached.
        through = {page.url: page for page in pages}
        disagreements: list[dict[str, Any]] = []
        both = [_merged(page, through[page.url], disagreements) if page.url in through else page for page in result.pages]
        both += [page for page in pages if page.url not in own]
        info["coverage"].update(indexability_disagreements=disagreements[:DISAGREEMENTS_LISTED],
                                indexability_disagreements_count=len(disagreements))
        view = replace(result, pages=both)
    checks = run_structure_checks(view, cfg, [])
    checks += settle_all([idx8_duplicates(view, cfg)], view)
    checks = [check for check in checks if check.check_id in CONTENT_CHECKS]
    if main:
        _label(checks, MAIN_SOURCE, MAIN_WHY, client.identity, notice=None)
    else:
        _label(checks, client.identity.source("Maya's crawler was blocked"), "Maya's crawler was blocked", client.identity)
    info["view_pages"] = pages  # for saving evidence; removed before the report is written
    return checks


def render_fallback(result: CrawlResult, cfg: CrawlConfig, client: ContentProvider, options: Options,
                    info: dict[str, Any]) -> list[CheckResult] | None:
    """Render the audit's sample through Firecrawl and run the rendering checks. None when nothing was rendered."""
    from ..checks.render import run_render_checks
    from ..render import RenderData, choose_render_sample

    rendered: dict[str, dict[str, Any]] = {}
    run_unreadable = 0  # same stop rule as apply(): consecutive unreadable answers after at least one page rendered
    sample = choose_render_sample(result, cfg, key_page_urls(result, cfg))[: min(cfg.render_budget, options.max_pages)]
    rows = info.setdefault("rendered", [])
    for row in sample:
        url = row["url"]
        try:
            fetched = client.scrape(url, wait_ms=1500)
        except ProviderLimitReached as exc:
            info["stopped_because"] = str(exc)
            break
        except ProviderRetentionRequired:
            raise
        except ContentLoadError as exc:
            info.setdefault("errors", []).append(exc.diagnostic(url))
            rows.append({"url": url, "outcome": "failed", "reason": str(exc)})
            # Try other already-known URLs, never retry this URL or change its proxy.
            # The client still enforces request count, approval, budget and stop.
            run_unreadable += 1
            if rendered and options.stop_after_unreadable and run_unreadable >= options.stop_after_unreadable:
                info["stopped_because"] = (f"the last {run_unreadable} pages asked for came back unreadable, so no more were requested")
                break
            continue
        except ContentProviderError as exc:
            rows.append({"url": url, "outcome": "failed", "reason": str(exc)})
            info["stopped_because"] = str(exc)
            break
        if not fetched.html.strip() or (fetched.status is not None and fetched.status >= 400):
            rows.append({"url": url, "outcome": "error", "status": fetched.status})
            continue
        run_unreadable = 0
        rendered[url] = {"url": url, "ok": True, "rendered": analyze_html(fetched.html), "why": row.get("why"),
                         "requests": [], "elapsed_ms": 0.0, "renderer": "firecrawl"}
        rows.append({"url": url, "outcome": "rendered", "status": fetched.status, "from_cache": fetched.cached})
    if not rendered:
        info["reason"] = "Firecrawl rendered no page"
        return None
    data = RenderData("raw_plus_sampled_render", None, browser=f"Firecrawl ({options.proxy} proxy)", budget=len(sample),
                      order=sample, pages=rendered, third_party_loaded=True, interactions_enabled=False)
    view = replace(result, render=data)
    checks = run_render_checks(view, cfg)
    _label(checks, RENDER_SOURCE, "the local browser could not start")
    info["render_data"] = data  # so the report's crawl.render says what happened; removed from the info before writing
    return checks


def browser_unavailable(result: CrawlResult) -> bool:
    render = result.render
    return render is None or (getattr(render, "mode", None) == "raw_html_only" and "disabled in configuration" not in (render.reason or ""))


def apply(outcome, cfg: CrawlConfig, client: FirecrawlClient, options: Options, *, progress=None, ranking_urls=()) -> dict[str, Any]:
    """Use Firecrawl for this audit where its conditions hold. Changes `outcome.checks` in place; returns the report section.

    Access results are never among the checks replaced. The section says what was asked for, what happened, what it
    cost, and which checks now rest on Firecrawl's reading.
    """
    result = outcome.result
    estimate = options.estimate(cfg.max_pages)
    info: dict[str, Any] = {
        "source": "Firecrawl (a third-party page reader; not Maya's own crawler)", "enabled": True, "used": False,
        "options": options.as_dict(), "proxy": options.proxy, "owner_approved_bypass": options.owner_approved_bypass,
        "zero_data_retention": {"requested": True, "applied": client.zero_data_retention,
                                "status": "applied" if client.zero_data_retention else "waived by the user for this audit"},
        "page_cap": options.max_pages, "notice": None, "checks_from_firecrawl": [], "reason": None,
    }
    replaced: dict[str, CheckResult] = {}
    # One deadline, one stop request and one pace for the whole audit (maya_audit.runclock). A client made before the
    # crawl takes them from the outcome here; a caller that set its own clock keeps it.
    clock = getattr(client, "clock", None)
    if clock is not None:
        if clock.deadline_mono is None:
            clock.deadline_mono = getattr(outcome, "deadline_mono", None)
        clock.pace_s = max(clock.pace_s, float(getattr(outcome, "pace_s", 0.0) or 0.0))
    began = time.monotonic()
    try:
        blocked, why = crawl_was_blocked(result, cfg)
        if options.read_always and not blocked:
            why = MAIN_READER_NOT_BLOCKED_WHY
        info["crawl_blocked"] = {"blocked": blocked, "why": why}
        if result.stop_reason == StopReason.NETWORK:
            info["crawl_blocked"].update(direct_not_reached=True, why=result.stop_detail)
        not_now = clock.why_not() if clock is not None else None
        if not_now is None and result.stop_reason == StopReason.RATE_LIMIT:
            # The site told Maya's crawler to slow down. Asking for the same pages through a reader in the same run
            # would be more requests to a site that asked for fewer (DECISIONS 52).
            not_now = "the site rate-limited Maya's crawler, so no further page was asked for through a reader in this run"
        if not_now and options.read_blocked and (blocked or options.read_always):
            info.update(reason=f"Firecrawl was not started: {not_now}", stopped_because=not_now, not_started=True)
        elif options.read_blocked and (blocked or options.read_always):
            checks = read_blocked_site(result, cfg, client, options, info, blocked=blocked, progress=progress, ranking_urls=ranking_urls)
            if checks:
                replaced.update({check.check_id: check for check in checks})
                if options.read_always:
                    info.update(used=True, purpose=MAIN_PURPOSE, notice=MAIN_NOTICE)
                    if blocked:
                        note_the_challenge(outcome.checks, info["pages_read"])
                else:
                    info.update(used=True, purpose="content reader for a blocked site", notice=AI_NOTICE)
        elif options.read_blocked:
            info["reason"] = why
        if options.render_fallback and not blocked and cfg.render_enabled and browser_unavailable(result):
            checks = render_fallback(result, cfg, client, options, info)
            if checks:
                replaced.update({check.check_id: check for check in checks})
                result.render = info.pop("render_data")
                info.update(used=True, purpose="rendering fallback", notice=RENDER_SOURCE)
    except ZeroDataRetentionUnavailable as exc:
        info["zero_data_retention"] = {"requested": True, "applied": False, "status": "not available"}
        info.update(used=False, reason=str(exc), needs_decision="zero_data_retention")
        replaced = {}
    except ProviderLimitReached as exc:
        info["stopped_because"] = str(exc)
    if replaced:
        outcome.checks[:] = [replaced.get(check.check_id, check) for check in outcome.checks]
        info["checks_from_firecrawl"] = sorted(replaced, key=check_id_key)
    info.pop("render_data", None)
    info.pop("not_started", None)
    if info.get("used") and info.get("pages_read"):
        # One "not read" figure in the whole report: every check's crawl-gap part says what the report itself says.
        from ..coverage import restate_crawl_gap
        from ..report import known_unread, read_counts

        restate_crawl_gap(outcome.checks, read_counts(result, info)["pages"], known_unread(result, info))
        from .. import single_page
        single_page.settle(outcome.checks, result)  # the reader's own content checks get the single-page rules too
    if replaced:
        from .. import launch_gate, root_cause
        root_cause.group(outcome.checks, result)  # the reader's own content checks are grouped as Maya's are
        launch_gate.apply(outcome.checks)  # the reader's own content checks are labelled as Maya's are
    from ..severity import apply as apply_severity
    apply_severity(outcome.checks, result)
    # The same finalization as Maya's own checks (DECISIONS 280): broken-link tracing, rule ids, facts, page kinds, and
    # a re-test state for any replaced finding that has none, within what is left of the re-test's request cap.
    from .. import final
    if replaced:
        final.after_provider(outcome, cfg)
    else:
        final.settle(outcome.checks, result)
    info.setdefault("coverage", {})["elapsed_s"] = round(time.monotonic() - began, 3)
    used = sum(call["credits"] for call in client.calls)
    rate = settings.usd_per_credit()
    info.update(calls=client.calls, requests_sent=client.requests_sent,
                credits={"per_page": estimate["credits_per_page"], "estimated_max": estimate["max_credits"], "used_or_reserved": used},
                usd={"per_credit": rate, "estimated_max": estimate["max_usd"],
                     "used_or_reserved": None if rate is None else round(used * rate, 4),
                     "note": None if rate is not None else "no dollar price per credit is configured, so only credits are shown"})
    return info
