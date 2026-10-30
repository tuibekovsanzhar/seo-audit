"""Breadth-first crawl that produces the raw material for every check.

Order of operations, chosen so INT-4 can prove compliance from the request log:
robots.txt first, then sitemaps, then pages. Link-discovered URLs are crawled
before sitemap-only URLs ("sitemap-last"), so pages found only via the sitemap
stay distinguishable (spec IDX-7; OpenSEO PM research).
"""

from __future__ import annotations

import time
import threading
import hashlib
import os
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from .botinfo import BotInfoPageNotReady, check_bot_info_page
from .classify import classify_fetch, empty_response, error_disclosure
from .config import CrawlConfig
from . import filelock
from .fetcher import Fetcher, gaps_by_host, utc_now
from .analysis import analyze_html
from .html_links import decode_body, extract_link_edges, is_html
from .models import (
    CrawlResult,
    FetchClass,
    PageFetch,
    SkippedUrl,
    page_from_record,
    page_record,
    StopReason,
)
from .robots import RobotsPolicy, crawl_delay, looks_like_html, policy_from_response, select_groups
from .progress import NO_HOOKS, Hooks
from .render_discovery import LinkDiscovery
from .scratchpad import (BLOCKED, CRAWLED, FAILED, MEMORY, QUEUED, RATE_LIMITED, SKIPPED,
                         FrontierUrl, Scratchpad, robots_fingerprint)
from .sitemap import discover_sitemap_urls
from .urls import (crawl_identity, host_allowed, is_allowed_origin_move, is_loopback_host, lock_key, normalize_url,
                   origin_of, same_origin)

MAX_ROBOTS_REDIRECTS = 5
MAX_START_REDIRECTS = 5
KEPT_HEADERS = (
    "server",
    "content-type",
    "content-length",
    "location",
    "retry-after",
    "cf-mitigated",
    "cf-ray",
    # Which bot protection answered, when it says so itself (classify.identify_blocker).
    "x-datadome",
    "x-iinfo",
    "x-cdn",
    "x-powered-by",
    "x-robots-tag",
    "link",
    "last-modified",  # STR-6
    # How the answer was sent and cached (A10, H28): PRF-1 tells an HTML page the CDN does not cache from the headers.
    "content-encoding",
    "vary",
    "cache-control",
    "etag",
    "age",
    "x-cache",
    "cf-cache-status",
    # The other CDNs' own words for the same (G05): RFC 9211 Cache-Status, Vercel, Netlify, Akamai, Fastly, CloudFront,
    # Sucuri, and the Via chain a cache adds. PRF-1 names a CDN only from these, never from the site's platform.
    "cache-status",
    "x-vercel-cache",
    "x-vercel-id",
    "x-nf-request-id",
    "akamai-cache-status",
    "x-served-by",
    "via",
    "x-amz-cf-id",
    "x-amz-cf-pop",
    "x-sucuri-cache",
    # Transport security (H32): the homepage's HSTS, read by PRF-1's security note.
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    # The rest of the OWASP baseline, read by PRF-1's security-headers note (DECISIONS 262).
    "content-security-policy-report-only",
    "referrer-policy",
    "x-frame-options",
    "permissions-policy",
)
# A kept header is evidence, not a copy of the site: a Content-Security-Policy can run to several KB on every page.
KEPT_HEADER_MAX_CHARS = 512


def kept_headers(headers: dict[str, str]) -> dict[str, str]:
    """The response headers a page record keeps (KEPT_HEADERS), each value cut at KEPT_HEADER_MAX_CHARS."""
    return {k: (v if len(v) <= KEPT_HEADER_MAX_CHARS else v[:KEPT_HEADER_MAX_CHARS] + " …(cut)")
            for k, v in headers.items() if k in KEPT_HEADERS}


class HostNotAllowed(ValueError):
    pass


class ConcurrentCrawlError(RuntimeError):
    pass


_SITE_LOCKS: dict[str, threading.Lock] = {}
_SITE_LOCKS_GUARD = threading.Lock()


@contextmanager
def _shared_site_lock(origin: str):
    """Advisory per-origin lock shared by processes on this machine/filesystem."""
    lock_dir = os.path.join(tempfile.gettempdir(), "maya-audit-locks")
    os.makedirs(lock_dir, mode=0o700, exist_ok=True)
    path = os.path.join(lock_dir, hashlib.sha256(origin.encode()).hexdigest() + ".lock")
    stream = open(path, "a+b")
    try:
        try:
            filelock.lock(stream, blocking=False)
        except OSError as exc:
            raise ConcurrentCrawlError(f"an audit of {origin} is already running on this host") from exc
        yield
    finally:
        try:
            filelock.unlock(stream)
        except OSError:
            pass
        stream.close()


def _attempt(response, retry_after: float | None, *, waited: float) -> dict:
    """One request for a page that was asked for twice (DECISIONS 286), as the report records it."""
    fetch_class = classify_fetch(response.status, response.headers, response.body, response.error).fetch_class
    return {"requested_at": response.started_at, "status": response.status, "error": response.error,
            "retry_after_s": retry_after, "waited_s": waited, "fetch_class": fetch_class.value,
            "server": response.headers.get("server"), "cf_ray": response.headers.get("cf-ray")}


def attempt_line(n: int, a: dict) -> str:
    """One attempt as the report's evidence line (DECISIONS 286)."""
    parts = [f"status {a['status']}" if a.get("status") is not None else f"error {a.get('error')}"]
    if a.get("retry_after_s") is not None:
        parts.append(f"Retry-After {a['retry_after_s']:g} s")
    parts += [f"{k} {a[key]}" for k, key in (("server", "server"), ("cf-ray", "cf_ray")) if a.get(key)]
    tail = f"; waited {a['waited_s']:g} s and asked once more" if a.get("waited_s") else ""
    return f"attempt {n}: {', '.join(parts)} at {a.get('requested_at')}{tail}"


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def pacing_record(fetcher: Fetcher, cfg: CrawlConfig) -> dict:
    """What `crawl.backoff` says about adaptive pacing (DECISIONS 219 part 2): whether it was on, each narrowing of the
    audited site's gap, the floor it could not go below, what stopped it, and each other host's own gap when it was
    not the configured one (a Crawl-delay)."""
    floor = fetcher.floor_s if fetcher.adaptive else None
    return {"adaptive_pacing": bool(fetcher.adaptive), "final_delay_s": fetcher.delay_s,
            "narrowed": list(fetcher.narrowings), "floor_s": round(floor, 3) if floor is not None else None,
            "narrowing_stopped": fetcher.narrowing_stopped, "site_host": fetcher.site_host,
            "host_gaps_s": {host: gap for host, gap in sorted(fetcher._gap_by_host.items())
                            if abs(gap - cfg.request_delay_s) > 1e-9}}


def load_robots(fetcher: Fetcher, origin: str, cfg: CrawlConfig) -> RobotsPolicy:
    """Fetch /robots.txt for an origin (following up to 5 redirects) and apply RFC 9309."""
    url = f"{origin}/robots.txt"
    hops: list[str] = []
    response = fetcher.get(url, "robots", cfg.max_robots_bytes + 1)
    while (
        response.error is None
        and response.status is not None
        and 300 <= response.status < 400
        and response.headers.get("location")
        and len(hops) < MAX_ROBOTS_REDIRECTS
    ):
        target = normalize_url(response.headers["location"], response.url)
        if target is None:
            break
        hops.append(target)
        response = fetcher.get(target, "robots", cfg.max_robots_bytes + 1)
    policy = policy_from_response(url, response.status, response.error, response.body, cfg.max_robots_bytes, hops)
    if response.truncated:
        policy.truncated = True
    policy.content_type = response.headers.get("content-type")
    policy.looks_like_html = looks_like_html(response.body, policy.content_type)
    policy.fetched_at = response.started_at
    # Hashed so a resumed session can tell whether the policy it inherits is the one it obeyed.
    policy.fingerprint = robots_fingerprint(response.body)
    return policy


# One place mapping a fetch outcome to the frontier row it writes.
FRONTIER_STATUS = {FetchClass.OK: CRAWLED, FetchClass.BLOCKED: BLOCKED,
                   FetchClass.RATE_LIMITED: RATE_LIMITED, FetchClass.ERROR: FAILED}


class Crawler:
    def __init__(self, config: CrawlConfig, transport: httpx.BaseTransport | None = None,
                 scratchpad: Scratchpad | None = None, hooks: Hooks | None = None) -> None:
        self.config = config
        self.hooks = hooks or NO_HOOKS
        self._transport = transport
        # In-memory by default: a crawl that is never resumed behaves exactly as it did before the
        # frontier moved to SQLite. A path (and --resume) is what makes it outlive the process.
        self._scratchpad = scratchpad
        self._owns_scratchpad = scratchpad is None
        self._robots_fingerprint: str | None = None

    def run(self, start_url: str, post_crawl=None) -> CrawlResult:
        normalized = normalize_url(start_url)
        if normalized is None:
            raise ValueError(f"not an http(s) URL: {start_url!r}")
        # Keyed by the site, not the origin before the start redirect (A12): http://e.com and https://www.e.com are one
        # site to be polite to, and the redirect of one audit may move it onto the other's origin.
        key = lock_key(normalized)
        with _shared_site_lock(key):
            with _SITE_LOCKS_GUARD:
                lock = _SITE_LOCKS.setdefault(key, threading.Lock())
            if not lock.acquire(blocking=False):
                raise ConcurrentCrawlError(f"an audit of {key} is already running in this process")
            try:
                from .config import SECRET_FIELDS
                settings = self.config.snapshot()
                mutable = {"db_path", "resume", "max_pages", "time_limit_s", "reader_reserve_s", "request_delay_s",
                           "robots_sample_interval_s", *SECRET_FIELDS}
                binding = {"start_url": normalized,
                           "settings": {k: v for k, v in settings.items() if k not in mutable}}
                if self._scratchpad is None:
                    self._scratchpad = Scratchpad(self.config.db_path or MEMORY, resume=self.config.resume,
                                                  binding=binding)
                else:
                    self._scratchpad.bind(binding)
                return self._run_locked(start_url, post_crawl)
            finally:
                if self._owns_scratchpad and self._scratchpad is not None:
                    self._scratchpad.close()
                    self._scratchpad = None
                lock.release()

    def _run_locked(self, start_url: str, post_crawl=None) -> CrawlResult:
        """Crawl, then optionally run `post_crawl(fetcher, result)` with the same
        fetcher (same identity, politeness, and request log) before closing."""
        cfg = self.config
        start = normalize_url(start_url)
        if start is None:
            raise ValueError(f"not an http(s) URL: {start_url!r}")
        start_host = urlsplit(start).hostname
        if start_host and start_host not in cfg.allowed_live_hosts:
            cfg = replace(cfg, allowed_live_hosts=cfg.allowed_live_hosts | frozenset({start_host}))
            self.config = cfg
        if cfg.block_loopback and is_loopback_host(start_host or ""):
            raise HostNotAllowed("loopback targets are blocked by hosted-use configuration")
        if not host_allowed(start, cfg.allowed_live_hosts):
            raise HostNotAllowed(
                f"refusing to crawl {origin_of(start)}: only loopback hosts are allowed unless the host "
                "is explicitly listed in allowed_live_hosts"
            )

        started_at = utc_now()
        t0 = time.monotonic()

        # A public crawler-info page is useful, but it belongs to Maya rather
        # than the site being audited. Its absence or 404 must not prevent the
        # user from checking a site. Record the result and continue.
        bot_info_check = {"state": "not_required", "reason": "loopback test crawl"}
        if not is_loopback_host(urlsplit(start).hostname or ""):
            if not cfg.bot_info_url:
                bot_info_check = {
                    "state": "not_configured",
                    "reason": "No optional Maya crawler-information page was configured; crawl continued.",
                }
            else:
                remaining = cfg.time_limit_s - (time.monotonic() - t0)
                if remaining <= 0:
                    bot_info_check = {"state": "unavailable", "url": cfg.bot_info_url,
                                      "reason": "overall audit deadline was reached before the optional page check",
                                      "crawl_continued": True}
                else:
                    try:
                        verified = check_bot_info_page(
                            cfg.bot_info_url, cfg.user_agent, cfg.product_token,
                            min(cfg.request_timeout_s, remaining), allow_loopback=not cfg.block_loopback,
                            deadline_mono=t0 + cfg.time_limit_s, stop_check=self.hooks.stop_requested
                        )
                        bot_info_check = {"state": "verified", **verified}
                    except BotInfoPageNotReady as exc:
                        bot_info_check = {
                            "state": "unavailable",
                            "url": cfg.bot_info_url,
                            "reason": str(exc),
                            "crawl_continued": True,
                        }

        self._lastmods: dict[str, str | None] = {}
        # Where each sitemap file was named (robots.txt, a sitemap index, or not named: the /sitemap.xml guess).
        self._sitemap_named_in: dict[str, str] = {}
        self._key_urls = {u for u in (normalize_url(k, start) for k in cfg.key_pages) if u}
        fetcher = Fetcher(cfg.user_agent, cfg.request_timeout_s, cfg.request_delay_s, self._transport, cfg.ca_bundle,
                          block_loopback=cfg.block_loopback)
        fetcher.deadline_mono = t0 + cfg.time_limit_s
        if cfg.adaptive_pacing:  # per-host gaps and the audited site's adaptive pacing (DECISIONS 219 part 2)
            fetcher.configure_pacing(cfg)
        fetcher.site_host = (start_host or "").lower() or None
        fetcher.stop_check = self.hooks.stop_requested if self.hooks.should_stop is not None else None
        self.hooks.emit("starting", max_pages=cfg.max_pages)
        # The step timing table (DECISIONS 219): robots.txt and the sitemaps first, then the pages, then each check.
        fetcher.begin_step("sitemap")
        try:
            result = self._crawl(fetcher, start, started_at, t0)
            result.bot_info_check = bot_info_check
            if post_crawl is not None:
                post_crawl(fetcher, result)
                result.requests = list(fetcher.log)
            fetcher.end_step()
            result.steps = list(fetcher.steps)
            # Pacing changes after the crawl too (the checks' requests count toward narrowing): the final figures.
            if result.backoff is not None:
                result.backoff.update(pacing_record(fetcher, cfg))
            # Include all post-crawl collectors (rendering, extra fetches and sampling waits), not
            # just the frontier loop. Reports and job runners need the actual elapsed time.
            result.finished_at = utc_now()
            result.elapsed_s = round(time.monotonic() - t0, 3)
            result.stopped = fetcher.stopped
            # A stop moves the deadline to "now" to end the run; that is not the time limit being reached.
            result.deadline_hit = not fetcher.stopped and bool(
                fetcher.deadline_hits or time.monotonic() >= fetcher.deadline_mono)
            if result.stopped:
                result.collector_errors.setdefault("audit_stopped", "the audit was stopped on request")
            if result.deadline_hit:
                result.collector_errors.setdefault("audit_deadline", f"overall audit time limit of {cfg.time_limit_s}s reached")
            # Closed here rather than inside _crawl: the collection pass above makes most of a
            # session's requests (441 of 455 on a real 10-page run), so a session row that stopped
            # counting before it understated every per-session figure INT-4 reports.
            self._close_session(fetcher, result)
        finally:
            if getattr(self, "_discovery", None) is not None:
                self._discovery.close()  # also when the crawl failed half-way: no browser is left running
            fetcher.close()
        return result

    # -- robots ---------------------------------------------------------------

    def _close_session(self, fetcher: Fetcher, result: CrawlResult) -> None:
        """Record what this session actually did, once every request it will make has been made."""
        log = fetcher.log
        # Same filter INT-4 uses: resource requests the browser makes inside one render are a burst
        # by nature, and politeness is measured between page-level requests. Counting them made the
        # session row report a 0.0 ms minimum gap against a 2 s delay on the first live run, which
        # read as a politeness violation on a crawl INT-4 had just called compliant.
        # Measured per host (DECISIONS 219 part 2): requests to other sites may run beside the audited site's.
        by_host, _clock = gaps_by_host(log)
        gaps = [gap / 1000 for host_gaps in by_host.values() for gap in host_gaps]
        stop_reason, stop_detail = getattr(self, "_session_stop", (None, ""))
        self._scratchpad.set_meta("final_delay_s", fetcher.delay_s)
        self._scratchpad.finish_session(
            user_agent=self.config.user_agent, robots_sha256=self._robots_fingerprint,
            requests=len(log), min_gap_ms=round(min(gaps) * 1000, 1) if gaps else None,
            configured_delay_s=self.config.request_delay_s, final_delay_s=fetcher.delay_s,
            stop_reason=stop_reason, stop_detail=stop_detail)
        result.sessions = self._scratchpad.sessions()

    def _load_robots(self, fetcher: Fetcher, origin: str) -> RobotsPolicy:
        policy = load_robots(fetcher, origin, self.config)
        if self._robots_fingerprint is None:  # the start origin's policy is the one a session is judged on
            self._robots_fingerprint = getattr(policy, "fingerprint", None)
        return policy

    # -- crawl ----------------------------------------------------------------

    def _crawl(self, fetcher: Fetcher, start: str, started_at: str, t0: float) -> CrawlResult:
        cfg = self.config
        self._t0 = t0
        self._sitemap_notes: list[str] = []
        token = cfg.product_token
        origin = origin_of(start)
        frontier = self._scratchpad
        # The start URL's redirect can move the crawl to another origin (http -> https, apex -> www). A resumed
        # session does not fetch the start URL again, so it takes the origin the earlier session settled on.
        saved_origin = frontier.get_meta("origin") if frontier.resumed else None
        if saved_origin and host_allowed(saved_origin, cfg.allowed_live_hosts):
            origin = saved_origin
            fetcher.site_host = (urlsplit(origin).hostname or "").lower() or None
        policies: dict[str, RobotsPolicy] = {origin: self._load_robots(fetcher, origin)}
        carried_delay = self._scratchpad.get_meta("final_delay_s")
        if carried_delay and carried_delay > fetcher.delay_s:
            # A site that rate-limited the previous session is met at that session's final pace, not
            # at full speed. Without this, resuming undoes the backoff that session earned.
            fetcher.delay_s = carried_delay
            fetcher.resumed_delay_from_s = carried_delay
        policy = policies[origin]
        self._apply_crawl_delay(fetcher, policy)

        skipped: list[SkippedUrl] = []
        pages: list[PageFetch] = []
        if frontier.resumed:
            # Earlier sessions' pages come back from the crawl database, so the report covers the whole
            # crawl. A URL marked fetched without a saved record (the process died in between) is fetched again.
            self._requeued = frontier.requeue_unsaved()
            pages = [page_from_record(record) for record in frontier.saved_pages()]
            skipped = [SkippedUrl(**record) for record in frontier.saved_skipped()]
        already_skipped = {item.url for item in skipped}
        self.hooks.emit("sitemap")
        # A single-page audit asks for no sitemap: it would only name pages that are not going to be read.
        sitemap_docs, sitemap_urls = ([], []) if cfg.single_page else self._discover_sitemaps(fetcher, policy, origin, skipped)

        # The frontier lives in SQLite (see scratchpad.py). `INSERT OR IGNORE` on the URL primary key
        # is the seen-set, so a URL already crawled can never be re-queued by a later link to it.
        frontier.set_meta("origin", origin)
        frontier.add_urls([FrontierUrl(start, 0, "start", None)])
        # Key pages are fetched because the owner marked them, not because the crawl happened to reach
        # them. Without this, a key page outside the first `max_pages` links is never audited at all: the
        # first client audit set five key pages and four were never fetched.
        if not cfg.single_page:
            frontier.add_urls([FrontierUrl(url, None, "key_page", None) for url in sorted(self._key_urls)
                               if same_origin(url, origin)])
            frontier.add_urls([FrontierUrl(url, None, "sitemap", None) for url in sitemap_urls])
        # A2: the crawl asks once for addresses that differ only in tracking or session parameters. The first variant
        # met is the one asked for and reported; a redirect's target is always followed (a session id may change on it).
        seen_identity: dict[str, str] = {}
        for known in frontier.all_urls():
            seen_identity.setdefault(crawl_identity(known), known)
        add_urls = frontier.add_urls

        def enqueue(items: list) -> None:
            kept = []
            for item in items:
                first = seen_identity.setdefault(crawl_identity(item.url), item.url)
                if first == item.url or item.via in ("redirect", "start"):
                    kept.append(item)
            add_urls(kept)

        fetched: set[str] = {page.url for page in pages}
        earlier_counted = sum(1 for page in pages if not (page.status is not None and 300 <= page.status < 400))
        pages_counted = 0  # this session's; the page cap is per session
        unsaved: PageFetch | None = None
        discovery = self._discovery = LinkDiscovery(fetcher, cfg, frontier.get_meta("render_discovery") if frontier.resumed else None)
        home_seen = frontier.resumed  # a resumed crawl has been through its homepage

        def keep(page: PageFetch | None) -> None:
            if page is not None:
                frontier.save_page(page_record(page))

        def progress(url: str | None = None) -> None:
            if self.hooks.on_progress is not None:
                self.hooks.emit("crawl", pages_fetched=earlier_counted + pages_counted, max_pages=earlier_counted + cfg.max_pages,
                                pages_discovered=sum(frontier.counts().values()), url=url,
                                # Beside the pages the cap counts: this session's redirect hops and repeats after a 429,
                                # and every request sent so far (robots.txt and sitemaps included).
                                other_fetches=fetches - pages_counted, requests_sent=len(fetcher.log))
        fetch_budget = cfg.max_pages * 3  # redirects are not pages but must stay bounded
        fetches = 0
        consecutive_rate_limited = 0
        total_cooldown_s = 0.0
        rate_limit_notes: list[str] = []
        start_chain = True  # still following the start URL's redirect chain
        stop_reason: StopReason | None = None
        stop_detail = ""
        pending: list[str] = []

        fetcher.begin_step("crawl")
        while stop_reason is None:
            # The page of the turn before is written once everything about it (its text, its links) is known.
            keep(unsaved)
            unsaved = None
            if fetcher.poll_stop():
                # Before anything is decided about the next URL: a stop that arrived while robots.txt was being read
                # leaves its rules unknown, and a URL judged on unknown rules would be skipped for good.
                stop_reason, stop_detail = StopReason.STOPPED, "stopped on request before every page was fetched"
                break
            claimed = frontier.get_next_url()
            if claimed is None:
                stop_reason = StopReason.EXHAUSTED
                stop_detail = "every discovered URL was fetched or skipped"
                break
            url, depth, via = claimed.url, claimed.depth, claimed.via

            if not same_origin(url, origin):
                frontier.mark_status(url, SKIPPED)
                continue

            decision = policies[origin].decide(token, url)
            if not decision.allowed:
                skipped.append(SkippedUrl(url, via, decision.to_dict()))
                frontier.mark_status(url, SKIPPED)
                start_chain = False
                continue

            if fetcher.poll_stop():
                stop_reason, stop_detail = StopReason.STOPPED, "stopped on request before every page was fetched"
                pending.append(url)
                break
            if time.monotonic() - t0 >= cfg.time_limit_s * cfg.crawl_time_share:
                stop_reason = StopReason.TIME_LIMIT
                stop_detail = (f"time limit of {cfg.time_limit_s}s reached" if cfg.crawl_time_share >= 1 else
                               f"the crawl used its share ({cfg.crawl_time_share:.0%}) of the {cfg.time_limit_s:g}s time "
                               "limit; the rest is kept for the checks that run after it")
                pending.append(url)
                break
            if pages_counted >= cfg.max_pages or fetches >= fetch_budget:
                stop_reason = StopReason.PAGE_CAP
                stop_detail = (
                    f"page cap of {cfg.max_pages} reached"
                    if pages_counted >= cfg.max_pages
                    else f"fetch budget of {fetch_budget} requests (pages plus redirects) reached"
                )
                pending.append(url)
                break

            response = fetcher.get(url, "page", cfg.max_body_bytes)
            fetches += 1
            retried = False
            attempts: list[dict] = []
            retry_after = parse_retry_after(response.headers.get("retry-after"))
            # One retry after a 429, or after a 503 that names when to come back (A13), when the wait is within the cap.
            # The start page's 429 has a longer cap (DECISIONS 286): without it nothing is read at all. Still once.
            cap = (max(cfg.max_retry_after_s, cfg.start_max_retry_after_s)
                   if via == "start" and response.status == 429 else cfg.max_retry_after_s)
            if response.status in (429, 503) and retry_after is not None and retry_after <= cap:
                if response.status == 503:  # a 429's wait is counted below, with the rate limit
                    total_cooldown_s += retry_after
                attempts.append(_attempt(response, retry_after, waited=retry_after))
                fetcher.sleep(retry_after)
                response = fetcher.get(url, "page", cfg.max_body_bytes)
                fetches += 1
                retried = True
                retry_after = parse_retry_after(response.headers.get("retry-after"))
                attempts.append(_attempt(response, retry_after, waited=0.0))

            classification = classify_fetch(response.status, response.headers, response.body, response.error)
            content_type = response.headers.get("content-type")
            page = PageFetch(
                url=url,
                discovered_via=via,
                depth=depth,
                requested_at=response.started_at,
                user_agent=cfg.user_agent,
                status=response.status,
                error=response.error,
                elapsed_ms=response.elapsed_ms,
                ttfb_ms=response.ttfb_ms,
                content_type=content_type,
                body_bytes=len(response.body),
                body_truncated=response.truncated,
                headers=kept_headers(response.headers),
                wire_bytes=response.wire_bytes,
                fetch_class=classification.fetch_class,
                classification_confidence=classification.confidence,
                classification_evidence=classification.evidence + [attempt_line(i, a) for i, a in enumerate(attempts, 1)],
                retried_after_429=retried,
                _attempts=attempts,
                content_checks_eligible=classification.fetch_class == FetchClass.OK,
            )
            # IDX-1 (DECISIONS 204): an answer that says "OK" and sends nothing stays the site's own answer (fetch_class
            # ok), but there is no page in it for the content checks to read.
            empty = (classification.fetch_class == FetchClass.OK
                     and empty_response(response.status, content_type, response.body, response.truncated,
                                        cfg.empty_response_max_bytes))
            if empty:
                page.content_checks_eligible = False
                page.classification_evidence = [*page.classification_evidence,
                                                f"empty response: status {response.status} with {len(response.body)} bytes "
                                                f"(under {cfg.empty_response_max_bytes})"]
            page._error_text = error_disclosure(response.body, response.status, content_type)
            if response.error is not None and fetcher.stopped:
                # The stop request arrived while this request was waiting its turn or while its answer was still
                # arriving. Either way the page was not read: it is left for a resume, not recorded as a failed page.
                stop_reason, stop_detail = StopReason.STOPPED, "stopped on request before every page was fetched"
                pending.append(url)
                break
            pages.append(page)
            unsaved = page
            fetched.add(url)
            # The frontier records how each URL ended, so a resumed crawl knows what is left and a
            # killed one leaves evidence of what it was doing.
            frontier.mark_status(url, FRONTIER_STATUS.get(classification.fetch_class, CRAWLED))

            is_redirect = response.status is not None and 300 <= response.status < 400
            if not is_redirect:
                pages_counted += 1
            progress(url)

            if classification.fetch_class == FetchClass.ERROR and via == "start":
                stop_reason, stop_detail = StopReason.ERROR, f"start URL could not be fetched: {response.error}"
                break

            if classification.fetch_class == FetchClass.RATE_LIMITED:
                consecutive_rate_limited += 1
                # Widen the gap for every later request, not just this one. Ported from OpenSEO's
                # crawl throttle (MIT): the interval grows on a refusal and is never narrowed again,
                # so the whole crawl slows down rather than pausing and then resuming at a pace the
                # site has already refused once.
                widened = fetcher.widen_delay(cfg.rate_limit_backoff_factor, cfg.max_request_delay_s)
                if widened is not None:
                    rate_limit_notes.append(f"{url} was rate-limited; the gap between requests widened to "
                                            f"{widened:.1f}s for the rest of the crawl")
                total_cooldown_s += retry_after or 0.0
                if total_cooldown_s > cfg.max_total_cooldown_s:
                    stop_reason = StopReason.RATE_LIMIT
                    stop_detail = (f"spent {total_cooldown_s:.0f}s waiting out rate limits, over the "
                                   f"{cfg.max_total_cooldown_s:.0f}s allowed; stopped requesting pages")
                    break
                if retry_after is not None and retry_after > cfg.max_retry_after_s:
                    stop_reason = StopReason.RATE_LIMIT
                    stop_detail = (
                        f"{url} asked Maya to wait {retry_after:.0f}s (Retry-After), longer than the "
                        f"{cfg.max_retry_after_s:.0f}s allowed; stopped requesting pages"
                    )
                    break
                if consecutive_rate_limited >= cfg.rate_limit_stop_after:
                    stop_reason = StopReason.RATE_LIMIT
                    stop_detail = f"{consecutive_rate_limited} consecutive rate-limited responses"
                    break
            else:
                consecutive_rate_limited = 0

            if is_redirect and response.headers.get("location"):
                target = normalize_url(response.headers["location"], url)
                page.redirect_location = target
                if target and start_chain and not same_origin(target, origin) and is_allowed_origin_move(url, target):
                    if host_allowed(target, cfg.allowed_live_hosts) and len(pages) <= MAX_START_REDIRECTS:
                        origin = origin_of(target)
                        frontier.set_meta("origin", origin)
                        fetcher.site_host = (urlsplit(origin).hostname or "").lower() or None
                        if origin not in policies:
                            policies[origin] = self._load_robots(fetcher, origin)
                            self._apply_crawl_delay(fetcher, policies[origin])
                            docs, urls = ([], []) if cfg.single_page else self._discover_sitemaps(fetcher, policies[origin], origin, skipped)
                            sitemap_docs.extend(docs)
                            sitemap_urls.extend(u for u in urls if u not in sitemap_urls)
                            enqueue([FrontierUrl(u, None, "sitemap", None) for u in urls])
                if target and same_origin(target, origin):
                    # via="redirect" sorts ahead of everything queued, matching the appendleft it replaces.
                    frontier.add_urls([FrontierUrl(target, depth, "redirect", url)])
                continue

            start_chain = False
            if classification.fetch_class == FetchClass.OK and response.status and 200 <= response.status < 300 and (is_html(content_type) or empty):
                text = decode_body(response.body, content_type)
                page.analysis = analyze_html(text)
                if empty:
                    page.analysis["empty_response"] = {"body_bytes": len(response.body), "limit": cfg.empty_response_max_bytes}
                if url in self._key_urls:  # RND-2 searches key pages' markup, not just visible text
                    page.analysis["_raw_html"] = text[: cfg.max_body_bytes]
                edges = extract_link_edges(text, url, cfg.max_anchor_texts_per_target)
                links = [e["target"] for e in edges]
                page.links_found = len(links)
                internal = [e for e in edges if same_origin(e["target"], origin)]
                page.outlinks = internal[:cfg.max_outlinks_per_page]
                page.external_links = [e for e in edges if not same_origin(e["target"], origin)][:cfg.max_external_links_per_page]
                # Every link is followed, whatever the cap on how many the report keeps. In a single-page audit none
                # is: the page's links are recorded (they are part of the page) and nothing is queued.
                if not cfg.single_page:
                    enqueue([FrontierUrl(e["target"], (depth or 0) + 1, "link", url, bool(e.get("nav")))
                                       for e in internal])
                why = "homepage" if not home_seen else "key page" if url in self._key_urls else None
                home_seen = True
                # Live gap 3: the homepage's and key pages' hreflang alternates and canonical target go to the front
                # (scratchpad.PRIORITY["alternate"]), so a 50-page crawl reads /en even when only <head> names it.
                if why and not cfg.single_page:
                    enqueue([FrontierUrl(target, (depth or 0) + 1, "alternate", url)
                             for target in head_link_targets(page, origin)])
                if why and discovery.wanted(url) and not cfg.single_page:
                    extra = discovery.extra_links(url, why, {e["target"] for e in internal}, policies[origin])
                    page.outlinks = (page.outlinks + extra)[:cfg.max_outlinks_per_page]  # marked "rendered": True
                    enqueue([FrontierUrl(e["target"], (depth or 0) + 1, "rendered_link", url, bool(e.get("nav")))
                                       for e in extra])

        if policies[origin].stops_requests or (not pages and skipped and stop_reason == StopReason.EXHAUSTED):
            stop_reason = (StopReason.RATE_LIMIT if policies[origin].status == 429
                           else StopReason.NETWORK if policies[origin].mode == "not_checked" else StopReason.ROBOTS_DISALLOWED)
            stop_detail = policies[origin].reason if policies[origin].stops_requests else (
                "robots.txt disallows the start URL for this user agent; no pages could be fetched"
            )

        keep(unsaved)
        discovery.close()
        frontier.set_meta("render_discovery", discovery.summary())
        # Sitemap discovery runs again in every session and meets the same disallowed sitemaps again.
        skipped = list({(item.url, item.discovered_via): item for item in skipped}.values())
        for item in skipped:
            if item.url not in already_skipped:
                frontier.save_skipped({"url": item.url, "discovered_via": item.discovered_via, "decision": item.decision})
        self._session_stop = (stop_reason.value if stop_reason else None, stop_detail)
        session_rows = frontier.sessions()
        pending.extend(frontier.urls_with_status(QUEUED))
        not_fetched = list(dict.fromkeys(u for u in pending if u not in fetched))

        return CrawlResult(
            start_url=start,
            origin=origin,
            user_agent=cfg.user_agent,
            product_token=token,
            started_at=started_at,
            finished_at=utc_now(),
            elapsed_s=round(time.monotonic() - t0, 3),
            config=cfg.snapshot(),
            robots=[self._policy_summary(p) for p in policies.values()],
            pages=pages,
            skipped_robots=skipped,
            sitemap_docs=sitemap_docs,
            sitemap_urls=sitemap_urls,
            discovered_urls=sorted(set(frontier.all_urls()) | set(sitemap_urls)),
            not_fetched_urls=not_fetched,
            stop_reason=stop_reason,
            stop_detail=stop_detail,
            requests=list(fetcher.log),
            robots_policy_by_origin=policies,
            sitemap_lastmods=dict(self._lastmods),
            sitemap_notes=list(self._sitemap_notes),
            _sitemap_named_in=dict(self._sitemap_named_in),
            sessions=session_rows,
            render_discovery=discovery.summary(),
            backoff={"configured_delay_s": cfg.request_delay_s, "final_delay_s": fetcher.delay_s,
                     "widenings": list(fetcher.delay_widenings), "notes": rate_limit_notes,
                     "total_cooldown_s": round(total_cooldown_s, 1), **pacing_record(fetcher, cfg)},
        )

    def _discover_sitemaps(
        self, fetcher: Fetcher, policy: RobotsPolicy, origin: str, skipped: list[SkippedUrl]
    ) -> tuple[list, list[str]]:
        if policy.stops_requests:
            return [], []
        cfg = self.config
        # Discovery gets a share of the time limit, so a site with dozens of sitemaps cannot use up the
        # whole budget before a single page is fetched.
        deadline = self._t0 + cfg.time_limit_s * cfg.sitemap_time_share
        docs, urls, notes = discover_sitemap_urls(
            fetcher, policy, origin, cfg.product_token, cfg.max_sitemap_docs, cfg.max_sitemap_depth,
            cfg.max_sitemap_bytes, skipped, self._lastmods, deadline, self._sitemap_named_in,
        )
        self._sitemap_notes.extend(notes)
        return docs, urls

    def _apply_crawl_delay(self, fetcher: Fetcher, policy: RobotsPolicy) -> None:
        if policy.robots is None:
            return
        delay = crawl_delay(policy.robots, self.config.product_token)
        if delay:
            honored = min(delay[0], self.config.max_crawl_delay_s)
            fetcher.delay_s = max(fetcher.delay_s, honored)
            # Adaptive pacing never narrows the gap below a Crawl-delay (DECISIONS 219 part 2).
            fetcher.crawl_delay_floor_s = max(fetcher.crawl_delay_floor_s, honored)

    def _policy_summary(self, policy: RobotsPolicy) -> dict:
        summary = {
            "url": policy.url,
            "mode": policy.mode,
            "reason": policy.reason,
            "status": policy.status,
            "error": policy.error,
            "bytes_read": policy.bytes_read,
            "truncated": policy.truncated,
            "redirect_hops": policy.redirect_hops,
            "content_type": policy.content_type,
            "looks_like_html": policy.looks_like_html,
        }
        if policy.robots is not None:
            groups, kind = select_groups(policy.robots, self.config.product_token)
            delay = crawl_delay(policy.robots, self.config.product_token)
            summary.update(
                matched_group_kind=kind,
                matched_group_lines=[line for g in groups for _, line in g.agents],
                crawl_delay=(
                    {
                        "seconds": delay[0],
                        "line": delay[1],
                        "honored_seconds": min(delay[0], self.config.max_crawl_delay_s),
                        "capped": delay[0] > self.config.max_crawl_delay_s,
                        "cap_seconds": self.config.max_crawl_delay_s,
                    }
                    if delay
                    else None
                ),
                sitemap_lines=[{"value": v, "line": n} for v, n in policy.robots.sitemaps],
                invalid_lines=policy.robots.invalid_lines,
            )
        return summary


def head_link_targets(page, origin: str) -> list[str]:
    """Same-origin addresses a page's <head> names as its other versions: hreflang alternates, then the canonical
    target (header or HTML), at most config.ALTERNATE_PRIORITY_MAX_PER_PAGE, the page itself left out (live gap 3)."""
    from .config import ALTERNATE_PRIORITY_MAX_PER_PAGE
    from .index_data import effective_canonical
    hrefs = [row.get("href") for row in (page.analysis or {}).get("hreflang") or []]
    found = [normalize_url(h, page.url) for h in hrefs if h] + [effective_canonical(page)[0]]
    targets = [u for u in dict.fromkeys(found) if u and u != page.url and same_origin(u, origin)]
    return targets[:ALTERNATE_PRIORITY_MAX_PER_PAGE]
