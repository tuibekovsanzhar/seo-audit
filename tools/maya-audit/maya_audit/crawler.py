"""Breadth-first crawl that produces the raw material for every check.

Order of operations, chosen so INT-4 can prove compliance from the request log:
robots.txt first, then sitemaps, then pages. Link-discovered URLs are crawled
before sitemap-only URLs ("sitemap-last"), so pages found only via the sitemap
stay distinguishable (spec IDX-7; OpenSEO PM research).
"""

from __future__ import annotations

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
from .urls import (crawl_identity, edit_preview, without_edit_preview, host_allowed, is_allowed_origin_move, is_loopback_host, lock_key, normalize_url,
                   origin_of, same_origin)
from . import clock as _clock

MAX_ROBOTS_REDIRECTS = 5
MAX_START_REDIRECTS = 5
# DECISIONS 358: the site's own pages answering with a redirect to its twin address (apex <-> www, http -> https) this
# many times move the crawl there, as a start redirect does; one is enough when robots.txt names its sitemap there.
TWIN_MOVE_REDIRECTS = 3
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


# A 429 on the start page or on one of this many first pages starts a waiting page reader at once (DECISIONS 299).
EARLY_READER_FIRST_PAGES = 3


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
                            if abs(gap - cfg.request_delay_s) > 1e-9},
            # The limit Maya's later steps and the page reader shared on the audited site (DECISIONS 294); None when
            # nothing ran after the crawl.
            "site_limit": fetcher.site_limiter.summary() if getattr(fetcher, "site_limiter", None) is not None else None}


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
        # Called once, with what the crawl knows so far, when one of its first page requests answers 429 (DECISIONS
        # 299): a page reader may start then, before the Retry-After wait and the rest of Maya's crawl.
        self.on_rate_limited = None
        self.rate_limited_at: dict | None = None

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
                if not settings.get("sampling"):  # DECISIONS 327: a crawl saved before Akıllı mode still resumes
                    settings.pop("sampling", None)
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
        t0 = _clock.monotonic()

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
                remaining = cfg.time_limit_s - (_clock.monotonic() - t0)
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
        self._sitemap_file_of: dict[str, str] = {}
        self._sitemap_loc_of: dict[str, dict] = {}  # DECISIONS 340: <loc> as written, and its line
        self._sitemap_read_at: dict[str, str] = {}
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
            result.elapsed_s = round(_clock.monotonic() - t0, 3)
            result.stopped = fetcher.stopped
            # A stop moves the deadline to "now" to end the run; that is not the time limit being reached.
            result.deadline_hit = not fetcher.stopped and bool(
                fetcher.deadline_hits or _clock.monotonic() >= fetcher.deadline_mono)
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
        self._locale_info = None
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
        # DECISIONS 358: earlier origins of this site after a move to its twin address: still fetched (they are the site's
        # own addresses, their redirects are measured) and their links are internal.
        aliases: set[str] = set(frontier.get_meta("origin_aliases") or []) if frontier.resumed else set()
        self._host_moves: list[dict] = list(frontier.get_meta("host_moves") or []) if frontier.resumed else []
        twin_hits: dict[str, list[str]] = {}

        def on_site(u: str) -> bool:
            return same_origin(u, origin) or origin_of(u) in aliases

        def twin_named(o: str) -> bool:
            """robots.txt of an origin of this site names a sitemap on `o`."""
            for pol in policies.values():
                for value, _line in (pol.robots.sitemaps if pol.robots is not None else []):
                    u = normalize_url(value, pol.url)
                    if u and origin_of(u) == o:
                        return True
            return False
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
        if not cfg.single_page:
            self._locales(frontier, start, sitemap_urls)
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
                if item.via not in ("redirect", "start") and edit_preview(item.url):
                    # DECISIONS 351: a CMS edit or preview address is its clean page, asked for once under that address
                    item = replace(item, url=without_edit_preview(item.url))
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
        # DECISIONS 327 (Akıllı ~150): the plan, made when the first page is read and again after the first wave.
        sampler = None
        self._sampler = None
        retyped = False

        def keep(page: PageFetch | None) -> None:
            if page is not None:
                frontier.save_page(page_record(page))

        def progress(url: str | None = None, **extra) -> None:
            if self.hooks.on_progress is not None:
                self.hooks.emit("crawl", **extra, pages_fetched=earlier_counted + pages_counted, max_pages=earlier_counted + cfg.max_pages,
                                pages_discovered=sum(frontier.counts().values()), url=url,
                                # Beside the pages the cap counts: this session's redirect hops and repeats after a 429,
                                # and every request sent so far (robots.txt and sitemaps included).
                                other_fetches=fetches - pages_counted, requests_sent=len(fetcher.log),
                                # Maya's own gap between requests now, for the progress box (DECISIONS 295).
                                delay_s=round(float(fetcher.delay_s or 0.0), 2),
                                sampling=self._sampling_progress(fetched) if sampler is not None else None)
        fetch_budget = cfg.max_pages * 3  # redirects are not pages but must stay bounded
        fetches = 0
        consecutive_rate_limited = 0
        total_cooldown_s = 0.0
        long_waits: dict[str, float] = {}  # DECISIONS 348: host -> the one long Retry-After waited out there
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

            if not on_site(url):
                frontier.mark_status(url, SKIPPED)
                continue

            decision = policies.get(origin_of(url), policies[origin]).decide(token, url)
            if not decision.allowed:
                skipped.append(SkippedUrl(url, via, decision.to_dict()))
                frontier.mark_status(url, SKIPPED)
                start_chain = False
                continue

            if fetcher.poll_stop():
                stop_reason, stop_detail = StopReason.STOPPED, "stopped on request before every page was fetched"
                pending.append(url)
                break
            if _clock.monotonic() - t0 >= cfg.time_limit_s * cfg.crawl_time_share:
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
            if (response.status == 429 and self.rate_limited_at is None and self.on_rate_limited is not None
                    and (via == "start" or pages_counted < EARLY_READER_FIRST_PAGES)):
                self._announce_rate_limit(fetcher, url, response, start, origin, started_at, token, policies, pages,
                                          skipped, sitemap_docs, sitemap_urls, frontier)
            retried = False
            attempts: list[dict] = []
            retry_after = parse_retry_after(response.headers.get("retry-after"))
            # One retry after a 429, or after a 503 that names when to come back (A13), when the wait is within the cap.
            # The start page's 429 has a longer cap (DECISIONS 286): without it nothing is read at all. Still once.
            cap = (max(cfg.max_retry_after_s, cfg.start_max_retry_after_s)
                   if via == "start" and response.status == 429 else cfg.max_retry_after_s)
            host = (urlsplit(url).hostname or "").lower()
            if (response.status in (429, 503) and retry_after is not None and cap < retry_after <= cfg.long_retry_after_s
                    and host not in long_waits):
                # DECISIONS 348: one longer wait (up to long_retry_after_s) per host, then the same single retry
                long_waits[host] = retry_after
                cap = retry_after
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
            if (aliases and origin_of(url) in aliases and via != "start" and not is_redirect
                    and classification.fetch_class == FetchClass.OK and response.status and 200 <= response.status < 300
                    and is_html(content_type)):
                # DECISIONS 359: after the move to the twin address, a page the earlier address answers with its content
                # instead of redirecting is a copy of the twin's page: kept as evidence (status, canonical), not read as a
                # page of its own nor counted against the page cap; the same address on the twin is read instead.
                page.analysis = analyze_html(decode_body(response.body, content_type))
                twin_url = self._make_twin_copy(page, origin)
                frontier.set_meta("host_moves", self._host_moves)
                frontier.add_urls([FrontierUrl(twin_url, depth, "redirect", url)])
                progress(url)
                continue
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
                    if retry_after > cfg.long_retry_after_s:
                        stop_detail = (
                            f"{url} asked Maya to wait {retry_after:.0f}s (Retry-After), longer than the "
                            f"{cfg.long_retry_after_s:.0f}s allowed; stopped requesting pages"
                        )
                    else:
                        stop_detail = (
                            f"{url} asked Maya to wait {retry_after:.0f}s (Retry-After) again, after the one long wait "
                            f"of {long_waits.get(host, retry_after):.0f}s allowed per host; stopped requesting pages"
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
                elif (target and not start_chain and not on_site(target) and on_site(url) and is_allowed_origin_move(url, target)
                      and host_allowed(target, cfg.allowed_live_hosts)):
                    # DECISIONS 358: the site sends its own pages to its twin address (carpexonline.com -> www.): after
                    # TWIN_MOVE_REDIRECTS such answers (one when robots.txt names a sitemap there) the crawl moves there,
                    # reads that address's robots.txt and sitemaps, and the targets met so far are queued.
                    twin = origin_of(target)
                    twin_hits.setdefault(twin, []).append(target)
                    if len(twin_hits[twin]) >= TWIN_MOVE_REDIRECTS or twin_named(twin):
                        aliases.add(origin)
                        self._host_moves.append({"from": origin, "to": twin, "redirects": len(twin_hits[twin]),
                                                 "after_pages": earlier_counted + pages_counted,
                                                 "sitemap_named": twin_named(twin)})
                        origin = twin
                        aliases.discard(origin)
                        frontier.set_meta("origin", origin)
                        frontier.set_meta("origin_aliases", sorted(aliases))
                        frontier.set_meta("host_moves", self._host_moves)
                        fetcher.site_host = (urlsplit(origin).hostname or "").lower() or None
                        if origin not in policies:
                            policies[origin] = self._load_robots(fetcher, origin)
                            self._apply_crawl_delay(fetcher, policies[origin])
                        if not cfg.single_page:
                            docs, urls = self._discover_sitemaps(fetcher, policies[origin], origin, skipped)
                            sitemap_docs.extend(docs)
                            sitemap_urls.extend(u for u in urls if u not in sitemap_urls)
                            enqueue([FrontierUrl(u, None, "sitemap", None) for u in urls])
                            if sampler is not None:
                                sampler.add(urls, files=dict(self._sitemap_file_of))
                        frontier.add_urls([FrontierUrl(u, depth, "redirect", url) for u in twin_hits.pop(twin)])
                        # DECISIONS 359: pages the earlier address answered itself before the move (the start page
                        # aside) are copies too: read again at the twin address, not counted twice
                        for earlier in pages:
                            if (earlier.discovered_via != "start" and origin_of(earlier.url) in aliases and earlier.analysis
                                    and earlier.status and 200 <= earlier.status < 300 and is_html(earlier.content_type)):
                                twin_url = self._make_twin_copy(earlier, origin)
                                frontier.save_page(page_record(earlier))
                                pages_counted -= 1
                                frontier.add_urls([FrontierUrl(twin_url, earlier.depth, "redirect", earlier.url)])
                        frontier.set_meta("host_moves", self._host_moves)
                if target and on_site(target):
                    # via="redirect" sorts ahead of everything queued, matching the appendleft it replaces.
                    frontier.add_urls([FrontierUrl(target, depth, "redirect", url)])
                continue

            if start_chain and frontier.locale_folders:
                # DECISIONS 316: the version the homepage landed on (/global-en) is the main one among copies of a page.
                from .locales import locale_of
                frontier.set_main_locale(locale_of(url, frontier.locale_folders))
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
                internal = [e for e in edges if on_site(e["target"])]
                page.outlinks = internal[:cfg.max_outlinks_per_page]
                page.external_links = [e for e in edges if not on_site(e["target"])][:cfg.max_external_links_per_page]
                # Every link is followed, whatever the cap on how many the report keeps. In a single-page audit none
                # is: the page's links are recorded (they are part of the page) and nothing is queued.
                if not cfg.single_page:
                    enqueue([FrontierUrl(e["target"], (depth or 0) + 1, "link", url, bool(e.get("nav")))
                                       for e in internal])
                why = "homepage" if not home_seen else "key page" if url in self._key_urls else None
                home_seen = True
                if why == "homepage" and self.hooks.on_progress is not None:
                    # DECISIONS 311: the business type this homepage suggests, for the progress box. A hint only: the
                    # report's own suggestion is worked out again from every page read.
                    try:
                        from .business_types import suggest
                        from .site_platform import _platform_hits
                        found = suggest(page.analysis, internal, next(iter(_platform_hits(page)), None),
                                        [url] + [e["target"] for e in internal])
                        progress(url, business_suggestion={k: found[k] for k in ("id", "label", "reason")})
                    except Exception:  # noqa: BLE001  never fails the crawl
                        pass
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

            if cfg.sampling and not cfg.single_page and not is_redirect:
                if sampler is None:
                    # the first page read (normally the homepage): plan from the sitemap and its links
                    sampler = self._sampler = self._start_sampling(frontier, page, origin, sitemap_urls)
                elif not retyped and pages_counted >= sampler.wave_one_size():
                    retyped = True
                    self._replan(frontier, pages)

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
            elapsed_s=round(_clock.monotonic() - t0, 3),
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
            _sitemap_file_of=dict(self._sitemap_file_of),
            _sitemap_loc_of=dict(self._sitemap_loc_of), _sitemap_read_at=dict(self._sitemap_read_at),
            sessions=session_rows,
            render_discovery=discovery.summary(),
            backoff={"configured_delay_s": cfg.request_delay_s, "final_delay_s": fetcher.delay_s,
                     "widenings": list(fetcher.delay_widenings), "notes": rate_limit_notes,
                     "total_cooldown_s": round(total_cooldown_s, 1), **pacing_record(fetcher, cfg)},
            # DECISIONS 316: known from the start for the page reader that reads right after the crawl; worked out again
            # with the pages' hreflang links when the audit settles (`final.locale_record`).
            locales=({**self._locale_info, "main": frontier.main_locale} if getattr(self, "_locale_info", None) else None),
            sampling=self._sampler.record() if getattr(self, "_sampler", None) is not None else None,
            host_moves=list(self._host_moves),
        )

    def _make_twin_copy(self, page: PageFetch, origin: str) -> str:
        """DECISIONS 359: make a page the earlier address answered itself a copy of the twin's page: its canonical kept
        as evidence, its content not read as a page of its own; recorded in the last move's copies. Returns the same
        address on the twin."""
        parts = urlsplit(page.url)
        twin_url = origin + (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        canonical = next(iter(((page.analysis or {}).get("canonicals") or [])), None)
        page.analysis = None
        page.outlinks, page.external_links, page.links_found = [], [], 0
        page.content_checks_eligible = False
        page.classification_evidence = [*page.classification_evidence,
                                        f"twin copy: {origin_of(page.url)} answered with the page itself instead of "
                                        f"redirecting to {origin}; read at {twin_url}"
                                        + (f"; its canonical is {canonical}" if canonical else "")]
        if self._host_moves:
            copies = self._host_moves[-1].setdefault("copies", [])
            if len(copies) < 500:
                copies.append({"url": page.url, "status": page.status, "canonical": canonical, "twin": twin_url})
        return twin_url

    def _start_sampling(self, frontier, page, origin: str, sitemap_urls: list[str]):
        """DECISIONS 327: the Akıllı plan from what is known after the first page: the sitemap and that page's links
        (with their menu texts). The business type is the person's choice, else the one this homepage suggests."""
        from . import business_types as bt
        from .locales import HOME_COPIES
        from .sampling import Sampler
        cfg = self.config
        edges = [e for e in (page.outlinks or []) if same_origin(e.get("target") or "", origin)]
        anchors: dict[str, list[str]] = {}
        for e in edges:
            anchors.setdefault(e["target"], []).extend(e.get("anchors") or ([e["anchor"]] if e.get("anchor") else []))
        known = [page.url, *sitemap_urls, *anchors, *sorted(self._key_urls)]
        pid = cfg.business_type if cfg.business_type and cfg.business_type != bt.AUTO and bt.valid(cfg.business_type) else None
        if pid is None:
            try:
                # DECISIONS 358: with the homepage's platform, as the report's own suggestion has (Ticimax -> E-ticaret)
                from .site_platform import _platform_hits
                platform = next(iter(_platform_hits(page)), None)
            except Exception:  # noqa: BLE001  a hint only
                platform = None
            try:
                pid = bt.suggest(page.analysis, edges, platform, known, frontier.locale_folders)["id"]
            except Exception:  # noqa: BLE001  "Diğer" plans by Stage 3's page types
                pid = bt.DEFAULT
        sampler = Sampler(pid, budget=cfg.max_pages, folders=frontier.locale_folders, main=frontier.main_locale,
                          lastmods=dict(self._lastmods))
        sampler.add(known, anchors, {e["target"] for e in edges if e.get("nav")}, files=dict(self._sitemap_file_of))
        homes = [u for u, (t, _) in sampler.types.items() if t == "home"]
        self._sampling_fixed = list(dict.fromkeys([page.url, *homes[:HOME_COPIES], *sorted(self._key_urls)]))
        frontier.set_plan(sampler.plan(fixed=self._sampling_fixed, read={page.url: "home"}))
        return sampler

    def _replan(self, frontier, pages) -> None:
        """DECISIONS 327: after the first wave, the pages read are typed with their content, unread addresses of their URL
        templates follow them, and the rest of the budget is planned again (with the addresses found meanwhile)."""
        sampler = self._sampler
        sampler.add(frontier.urls_with_status(QUEUED), files=dict(self._sitemap_file_of))
        links = {p.url: [e["target"] for e in p.outlinks or [] if not e.get("nav") and not e.get("footer")] for p in pages if p.analysis}
        real = sampler.retype({p.url: p.analysis for p in pages if p.analysis}, links)
        frontier.set_plan(sampler.plan(fixed=self._sampling_fixed, read=real))

    def _sampling_progress(self, fetched: set[str]) -> dict:
        """Per page type: pages read so far and planned (for the progress box)."""
        s = self._sampler
        rec = s.record()
        read: dict[str, int] = {}
        for u in fetched:
            t = s.types.get(u, ("",))[0]
            read[t] = read.get(t, 0) + 1
        return {"types": [{"id": t, "label": row["label"], "rank": row["rank"], "read": read.get(t, 0), "planned": row["planned"],
                           "known": row["known"]} for t, row in rec["types"].items()
                          if row["label"] and (row["planned"] or row["known"])], "wave": len(s.waves), "profile": s.pid}

    def _announce_rate_limit(self, fetcher, url, response, start, origin, started_at, token, policies, pages, skipped,
                             sitemap_docs, sitemap_urls, frontier) -> None:
        """Hand `on_rate_limited` a copy of what the crawl knows now (robots.txt, sitemaps, addresses found, pages read):
        nothing it holds is changed by the crawl that goes on."""
        self.rate_limited_at = {"url": url, "at": utc_now(), "elapsed_s": round(_clock.monotonic() - self._t0, 3),
                                "retry_after": response.headers.get("retry-after")}
        known = CrawlResult(
            start_url=start, origin=origin, user_agent=self.config.user_agent, product_token=token, started_at=started_at,
            finished_at=utc_now(), elapsed_s=round(_clock.monotonic() - self._t0, 3), config=self.config.snapshot(),
            robots=[self._policy_summary(p) for p in policies.values()], pages=list(pages), skipped_robots=list(skipped),
            sitemap_docs=list(sitemap_docs), sitemap_urls=list(sitemap_urls),
            discovered_urls=sorted(set(frontier.all_urls()) | set(sitemap_urls)), not_fetched_urls=[],
            stop_reason=None, stop_detail="", requests=[], robots_policy_by_origin=dict(policies),
            sitemap_lastmods=dict(self._lastmods), sitemap_notes=list(self._sitemap_notes),
            _sitemap_named_in=dict(self._sitemap_named_in), _sitemap_file_of=dict(self._sitemap_file_of),
            _sitemap_loc_of=dict(self._sitemap_loc_of), _sitemap_read_at=dict(self._sitemap_read_at))
        try:
            started = self.on_rate_limited(fetcher, known)
        except Exception as exc:  # a reader that cannot start leaves the crawl as it was
            started = False
            self.rate_limited_at["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        self.rate_limited_at["reader_started"] = bool(started)

    def _locales(self, frontier, start: str, sitemap_urls: list[str]) -> None:
        """DECISIONS 316: the site's country/language folders from the addresses known before the first page (the
        sitemap, the start address and key pages), and the business type's key page types, so the crawl reads one
        version of each page first. A resumed crawl keeps the main version its first session found."""
        from .business_types import key_type_test
        from .locales import detect
        known = [start, *sorted(self._key_urls), *sitemap_urls]
        info = detect(known, start_url=start)
        self._locale_info = info
        main = frontier.main_locale if frontier.resumed and frontier.locale_folders else info["main"]
        try:
            boost = key_type_test(self.config.business_type, sitemap_urls, info["folders"])
        except Exception:  # noqa: BLE001  a hint only: the crawl goes on in its usual order
            boost = None
        frontier.set_locales(info["folders"], main, boost)

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
            cfg.max_sitemap_bytes, skipped, self._lastmods, deadline, self._sitemap_named_in, self._sitemap_file_of,
            # Enough addresses for the page cap and the sitemap check's sample, spread over the index's files
            # (DECISIONS 299): the rest of a large index is not read.
            # A sitemap of up to SITEMAP_CHECK_ALL_UP_TO addresses is read whole, to be checked whole (DECISIONS 343).
            enough=cfg.max_pages + max(0, cfg.sitemap_check_max,
                                       cfg.sitemap_check_all_up_to if cfg.sitemap_check_max and not cfg.fast_check else 0),
            loc_of=self._sitemap_loc_of, read_at=self._sitemap_read_at,
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
                # DECISIONS 363: directives written inside a comment, which no crawler reads
                commented_directives=[{"line": n, "text": t} for n, t in getattr(policy.robots, "commented", [])],
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
