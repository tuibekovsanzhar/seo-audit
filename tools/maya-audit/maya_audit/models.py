from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any


class Confidence(str, Enum):
    """Spec §2.2. How sure we are that an observation is true."""

    VERIFIED = "verified"
    INFERRED = "inferred"
    ESTIMATED = "estimated"
    NOT_ASSESSED = "not_assessed"


class FetchClass(str, Enum):
    """Spec INT-1. How a page fetch resolved."""

    OK = "ok"  # the server's own response (any status), not an edge intervention
    BLOCKED = "blocked"  # bot challenge or access denial
    RATE_LIMITED = "rate_limited"  # 429
    ERROR = "error"  # transport failure: timeout, DNS, TLS, dropped connection


class StopReason(str, Enum):
    """Spec INT-2 stop reasons, plus robots_disallowed (see README, open items)."""

    EXHAUSTED = "exhausted"
    PAGE_CAP = "page_cap"
    TIME_LIMIT = "time_limit"
    RATE_LIMIT = "rate_limit"
    ERROR = "error"
    ROBOTS_DISALLOWED = "robots_disallowed"
    # No answer from the site reached this computer (a failed DNS lookup here, a timeout, a refused connection), so
    # Maya's own crawler requested no page. Not a statement about the site.
    NETWORK = "network_problem"
    STOPPED = "stopped"  # a stop was requested (maya_audit.progress); resumable with a crawl database


@dataclass
class RequestRecord:
    """One HTTP request Maya made. INT-4 audits this log."""

    seq: int
    url: str
    purpose: str  # "robots" | "sitemap" | "page"
    user_agent: str
    started_at: str
    status: int | None
    error: str | None
    elapsed_ms: float
    extra_headers: dict[str, str] = field(default_factory=dict)
    ttfb_ms: float | None = None
    # Monotonic stamps, in seconds, for the politeness audit. `started_at` is wall clock, for people;
    # intervals are measured on the clock that cannot be stepped by NTP mid-crawl (INT-4).
    started_mono: float | None = None
    ended_mono: float | None = None
    # Which slot of the shared site limit carried the request (maya_audit.sitelimit, DECISIONS 294): 0 is the audit's
    # own thread, 1-9 the sitemap check's workers; None before the limit existed (the crawl) or for another host.
    slot: int | None = None


@dataclass
class Classification:
    fetch_class: FetchClass
    confidence: Confidence
    evidence: list[str]


@dataclass
class PageFetch:
    url: str
    discovered_via: str  # "start" | "key_page" | "alternate" | "link" | "rendered_link" | "sitemap" | "redirect"
    depth: int | None  # click depth from the start URL; None for sitemap-only URLs
    requested_at: str
    user_agent: str
    status: int | None
    error: str | None
    elapsed_ms: float
    content_type: str | None
    body_bytes: int
    body_truncated: bool
    headers: dict[str, str]
    fetch_class: FetchClass
    classification_confidence: Confidence
    classification_evidence: list[str]
    redirect_location: str | None = None
    retried_after_429: bool = False
    # Every request for this page when there was more than one (DECISIONS 286): requested_at, status, retry_after_s,
    # waited_s, fetch_class, server, cf_ray. In memory only ("_"): the report gets them as `classification_evidence`
    # lines ("attempt 1: ..."), so its 1.20 shape is unchanged. Empty when the page was asked for once.
    _attempts: list[dict[str, Any]] = field(default_factory=list)
    # INT-3: "raw" is the HTML Maya's own request received. "provider" is a document a third-party reader returned:
    # it may already hold what JavaScript added, so it says nothing about what a crawler that runs no script receives.
    view: str = "raw"
    # INT-1: content checks are suppressed on pages Maya could not read.
    content_checks_eligible: bool = True
    links_found: int = 0
    # Extracted HTML facts for readable HTML pages (maya_audit.analysis).
    analysis: dict[str, Any] | None = None
    # Same-origin link edges from this page: [{"target", "anchor"}] (IDX-6, IDX-7).
    outlinks: list[dict[str, str]] = field(default_factory=list)
    # Links to other sites (first 300), for checks about where a page sends its readers.
    external_links: list[dict[str, str]] = field(default_factory=list)
    # Request sent -> response headers (PRF-1).
    ttfb_ms: float | None = None
    # Bytes that came over the network (compressed, as sent), beside `body_bytes` decoded (A10). None: not measured.
    wire_bytes: int | None = None
    # Template, page type, internal link score, click depth and importance (maya_audit.page_groups, DECISIONS 297,
    # schema 1.23). Estimated; never used for a severity. None until the audit's finalization sets it.
    grouping: dict[str, Any] | None = None
    # A server error message printed into the page, with the server's file path ({"marker", "line"}, the account
    # folder masked; maya_audit.classify.error_disclosure). Kept in memory for IDX-1; never written to a report.
    _error_text: dict[str, str] | None = field(default=None, repr=False)

    def readable_document(self) -> bool:
        """Whether this record holds a document the content checks may read.

        A measured 2xx answer, or a provider's document (`view` "provider") whose HTTP status the provider did not
        report. An unknown status stays unknown (`status` None): it is never written as a measured 200. An empty page
        (`analysis["empty_response"]`, IDX-1) is not a document: there is nothing in it to read."""
        if self.fetch_class != FetchClass.OK or self.error is not None:
            return False
        if self.analysis and self.analysis.get("empty_response"):
            return False
        if self.status is None:
            return self.view == "provider"
        return 200 <= self.status < 300

    def reproduce(self) -> str:
        return f"curl -i -A {shlex.quote(self.user_agent)} {shlex.quote(self.url)}"


@dataclass
class SkippedUrl:
    url: str
    discovered_via: str
    decision: dict[str, Any]


@dataclass
class SitemapDoc:
    url: str
    status: int | None
    error: str | None
    kind: str | None  # "urlset" | "sitemapindex" | None
    urls_found: int
    # For a urlset: how many entries carry <lastmod>, how many distinct values, and the most common one (IDX-5).
    lastmod_count: int = 0
    lastmod_distinct: int = 0
    lastmod_top: str | None = None
    lastmod_top_count: int = 0
    # For a urlset: how many <image:image> and <video:video> entries it holds (SEO-036, DECISIONS 304, schema 1.24).
    image_entries: int = 0
    video_entries: int = 0


@dataclass
class GateResult:
    """Outcome of an INT gate. Gates carry no severity (spec §6)."""

    check_id: str
    title: str
    state: str
    confidence: Confidence
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    how_to_fix: str | None = None


@dataclass
class CrawlResult:
    start_url: str
    origin: str
    user_agent: str
    product_token: str
    started_at: str
    finished_at: str
    elapsed_s: float
    config: dict[str, Any]
    robots: list[dict[str, Any]]
    pages: list[PageFetch]
    skipped_robots: list[SkippedUrl]
    sitemap_docs: list[SitemapDoc]
    sitemap_urls: list[str]
    discovered_urls: list[str]
    not_fetched_urls: list[str]
    stop_reason: StopReason
    stop_detail: str
    requests: list[RequestRecord]
    deadline_hit: bool = False
    # True when a stop was requested at any point, during the crawl or the data collection after it.
    stopped: bool = False
    # Whether link discovery also read rendered pages, and what that added (maya_audit.render_discovery).
    render_discovery: dict[str, Any] | None = None
    # Pre-flight fetch of the public bot info page; None for loopback test runs.
    bot_info_check: dict[str, Any] | None = None
    # Data collected after the crawl for ACC checks (maya_audit.access_data).
    access: Any = None
    # Data collected after the crawl for IDX checks (maya_audit.index_data).
    index: Any = None
    # T1 rendering sample and results for RND checks (maya_audit.render).
    render: Any = None
    # Statuses of URLs pages point to (og:image, sameAs, hreflang) for STR checks (maya_audit.structure_data).
    structure: Any = None
    # Repeated timing/reliability samples and optional PageSpeed/CrUX data (maya_audit.perf_data).
    perf: Any = None
    # Citation records and the site-side fetches they needed (maya_audit.ans_data).
    citations: Any = None
    citation_domains: Any = None
    # How this computer looked hosts up during the audit (maya_audit.resolver): the pre-flight check, and per host
    # which method answered (the system resolver, or DNS over HTTPS when it failed). About this computer, not the site.
    network: dict[str, Any] | None = None
    # Collector exceptions are retained so a partial report can explain which checks did not run.
    collector_errors: dict[str, str] = field(default_factory=dict)
    # {'final_delay_s': float, 'widenings': [...], 'notes': [...]} when a rate limit widened the gap.
    backoff: Any = None
    # One row per crawl session; a resumed crawl has more than one and the INT gates say so.
    sessions: Any = None
    # <lastmod> per sitemap URL, None when absent (IDX-5).
    sitemap_lastmods: dict[str, str | None] = field(default_factory=dict)
    # Disclosures about sitemap discovery, e.g. that it stopped on its time budget (INT-2, IDX-5).
    sitemap_notes: list[str] = field(default_factory=list)
    robots_policy_by_origin: dict[str, Any] = field(default_factory=dict, repr=False)
    # Where each sitemap file was named: "robots.txt", "sitemap index <url>" or "guess" (maya_audit.sitemap). In
    # memory for IDX-5's failed-file finding, which writes what it needs into its own evidence.
    # How long each step took, how many requests it sent and how long of that was waiting (DECISIONS 219): rows of
    # {step, started_at, seconds, requests, waiting_s}, in order; the report adds the Firecrawl page reader's row.
    steps: list[dict[str, Any]] = field(default_factory=list)
    # The optional steps the time limit cut (DECISIONS 219), in the order they give way: "other_site_links",
    # "llms_links", "sitemap_check", "performance", "rendering". Empty when nothing was cut or the audit was stopped.
    skipped_for_time: list[str] = field(default_factory=list)
    # The re-test of the most serious findings (maya_audit.verification, DECISIONS 272): its requests, cap and states.
    verification: dict[str, Any] | None = None
    # The page grouping's method and counts (maya_audit.page_groups, DECISIONS 297, schema 1.23).
    page_grouping: dict[str, Any] | None = None
    # The same grouping for the pages a page reader (Firecrawl) read when Maya's crawler was blocked (DECISIONS 304,
    # schema 1.24): the summary keys of `page_grouping`, plus `reader` and `pages` ({url: grouping record}). Maya's own
    # page records hold no content then, so `page_grouping` scores nothing. None when no reader read the site for Maya.
    reader_page_grouping: dict[str, Any] | None = None
    # The business type the audit used (maya_audit.business_types, DECISIONS 311, schema 1.25): {id, label, chosen_by
    # ("user" | "suggestion"), suggestion {id, label, reason, signals, scores}, page_types (the importance summary),
    # not_found, version}. None in a report saved before it.
    business_type: dict[str, Any] | None = None
    # Every requested address that redirected (Stage 8a, DECISIONS 315, schema 1.26): {url, hops [{url, status,
    # target}], final, final_status, loop}. None in a report saved before it.
    redirects: list[dict[str, Any]] | None = None
    # The site's country/language folders (DECISIONS 316, schema 1.27): {folders, main, versions, root_is_version,
    # basis}. None in a report saved before it.
    locales: dict[str, Any] | None = None
    _sitemap_named_in: dict[str, str] = field(default_factory=dict, repr=False)
    # In memory only: the sitemap file that listed each sitemap URL, for the sitemap check's sample (DECISIONS 294).
    _sitemap_file_of: dict[str, str] = field(default_factory=dict, repr=False)
    # The sitemap check's data while the audit runs (maya_audit.index_data.check_sitemap_urls); written under
    # `crawl.index.sitemap_check`.
    _sitemap_check: Any = field(default=None, repr=False)
    # The budget of requests to other sites while the audit runs (maya_audit.external_links, DECISIONS 211); its
    # summary is written under `crawl.structure.external`.
    _external: Any = field(default=None, repr=False)
    # The pool of requests to other sites while the audit runs (maya_audit.other_sites, DECISIONS 219 part 2); in
    # memory only.
    _other_sites: Any = field(default=None, repr=False)


def page_record(page: PageFetch) -> dict[str, Any]:
    """A page as plain JSON-ready data, working data ("_" keys of its analysis) included, for the crawl database."""
    record = asdict(page)
    record["fetch_class"] = page.fetch_class.value
    record["classification_confidence"] = page.classification_confidence.value
    return record


def page_from_record(record: dict[str, Any]) -> PageFetch:
    known = {f.name for f in fields(PageFetch)}
    data = {k: v for k, v in record.items() if k in known}  # a record written by a later version may carry more
    data["fetch_class"] = FetchClass(data["fetch_class"])
    data["classification_confidence"] = Confidence(data["classification_confidence"])
    return PageFetch(**data)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in fields(value)
                if f.name != "robots_policy_by_origin" and not f.name.startswith("_")}
    if isinstance(value, dict):
        # Keys starting with "_" hold in-memory working data (e.g. page text), never written to reports.
        return {str(k): to_jsonable(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    return value
