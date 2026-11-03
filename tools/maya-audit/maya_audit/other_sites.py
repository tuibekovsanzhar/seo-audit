"""Requests to other sites, in parallel with the audit's own (DECISIONS 219 part 2; what is asked: DECISIONS 196, 211).

Right after the crawl, every request to another site the later steps would make is put in one queue, in the order
those steps asked before: IDX-6's links to another site at one of this site's paths, then the structure step's sameAs
profiles, og:images and hreflang alternates on another origin, then STR-7's images on another site, then the other
links, most-linked first. The caps (IDX-6's own, the other-site budget's requests, sites and sameAs links) are applied
while the queue is built, so the same links are asked every run, whatever answers first. A robots.txt counts toward the
budget's cap when the queue says so (a site IDX-6 asks has its robots.txt free, as before), and a HEAD a site does not
take (405, 501) is asked again as a GET only within room the queue left under the cap, given to the first links in
queue order.

A pool of `CrawlConfig.other_site_workers` threads (4) then asks the queue: each worker takes one other site at a time,
fetches and obeys its robots.txt first, then asks its addresses in queue order at that site's own gap (the configured
delay, or its Crawl-delay up to `max_crawl_delay_s`). A site that answered 429 or did not answer is asked nothing more.
Every request goes through the crawl's fetcher: the same user agent, URL safety (a private or reserved address is
refused), time limit and stop request; never a page reader or a paid provider. The audited site stays on the audit's
own thread, one request at a time. The pool is joined after the sitemap check; what it did not send is "not checked:
time limit". Only then are the answers written into the index and structure data (`later`), and the budget
(`maya_audit.external_links.ExternalBudget`) takes the counts, so llms.txt's links to other sites (asked after the join,
on the audit's thread) get what is left, as before.

The step timing table has the pool's own row, `other_sites`: from its start to its last answer, its requests, and as
"Of which waiting" the time within that span when none of its requests was in flight (every worker was waiting out a
gap). The audit's own steps count only their own requests and waiting; the wait for the pool at the join, when there
is one, is the row `other_sites_wait`.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from .config import CrawlConfig
from .fetcher import Fetcher, RawResponse, utc_now
from .models import CrawlResult
from .media_sample import IMAGE_HEADERS
from .urls import normalize_url, origin_of
from . import clock as _clock

IDX6 = "idx6"          # IDX-6's GET (purpose other_site_link), outside the other-site budget
CHECK = "check"        # external_links.check: one HEAD (sameAs profiles and other links)
OG = "og"              # an og:image on another origin: a GET of the first 64 KB
HTML = "html"          # an hreflang alternate on another origin: a GET of the page
IMAGE = "image"        # STR-7: an image on another site, a GET of 4 KB


@dataclass
class Item:
    url: str
    kind: str
    purpose: str
    max_bytes: int
    method: str = "GET"
    same_as: bool = False
    budget: bool = True        # counts toward the other-site budget (not IDX-6's own requests)
    retry: bool = False        # a 405/501 to the HEAD may be asked again as a GET
    by_idx6: bool = False      # a CHECK address IDX-6 asks itself: answered from that request, nothing more is sent
    why: str | None = None     # why it was not asked: a key of external_links.REASONS ("robots" with `decision`)
    decision: dict | None = None
    response: RawResponse | None = None
    retry_response: RawResponse | None = None

    @property
    def origin(self) -> str:
        return origin_of(self.url)


@dataclass
class OtherSitePool:
    fetcher: Fetcher
    result: CrawlResult
    cfg: CrawlConfig
    items: list[Item] = field(default_factory=list)
    keyed: dict[tuple[str, str], Item] = field(default_factory=dict)
    sites: list[str] = field(default_factory=list)            # the budget's other sites, in queue order
    robots_paid: set[str] = field(default_factory=set)         # origins whose robots.txt counts toward the cap
    policies: dict[str, Any] = field(default_factory=dict)     # robots.txt read by the workers, merged at the join
    robots_spent: dict[str, int] = field(default_factory=dict)
    quiet: dict[str, str] = field(default_factory=dict)
    unplanned: dict[str, str] = field(default_factory=dict)    # a CHECK address not asked, and why (decided at build)
    started_mono: float | None = None
    started_at: str | None = None
    finished_mono: float | None = None
    joined: bool = False
    _later: list[Callable[[], None]] = field(default_factory=list)
    _futures: list[Any] = field(default_factory=list)
    _executor: ThreadPoolExecutor | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- what the collectors ask -------------------------------------------------------------------------------------

    def item(self, url: str, kind: str) -> Item | None:
        return self.keyed.get((url, kind))

    def later(self, fill: Callable[[], None]) -> None:
        """Run `fill` on the audit's own thread once the pool is joined (at once if it already is)."""
        if self.joined:
            fill()
        else:
            self._later.append(fill)

    # -- running ----------------------------------------------------------------------------------------------------

    def start(self) -> None:
        by_site: dict[str, list[Item]] = {}
        for item in self.items:
            if item.why is None and not item.by_idx6:
                by_site.setdefault(item.origin, []).append(item)
        self.started_mono, self.started_at = _clock.monotonic(), utc_now()
        if not by_site:
            return
        self._executor = ThreadPoolExecutor(max(1, self.cfg.other_site_workers), thread_name_prefix="other-sites")
        self._futures = [self._executor.submit(self._ask_site, origin, items) for origin, items in by_site.items()]

    def _out_of_time(self) -> bool:
        self.fetcher.poll_stop()
        return self.fetcher.deadline_mono is not None and _clock.monotonic() >= self.fetcher.deadline_mono

    def _policy(self, origin: str):
        from .crawler import load_robots  # local import: crawler does not import this module
        from .robots import crawl_delay

        held = self.result.robots_policy_by_origin.get(origin) or self.policies.get(origin)
        if held is not None:
            return held
        before = self.fetcher.thread_requests
        policy = load_robots(self.fetcher, origin, self.cfg)
        with self._lock:
            self.policies[origin] = policy
            self.robots_spent[origin] = self.fetcher.thread_requests - before
        delay = crawl_delay(policy.robots, self.cfg.product_token) if policy.robots is not None else None
        host = (urlsplit(origin).hostname or "").lower()
        gap = max(self.cfg.request_delay_s, min(delay[0], self.cfg.max_crawl_delay_s)) if delay else self.cfg.request_delay_s
        self.fetcher.set_host_gap(host, gap)
        return policy

    def _ask_site(self, origin: str, items: list[Item]) -> None:
        """One other site, on one worker: its robots.txt first, then its addresses in queue order."""
        from .external_links import GET_PURPOSE, NO_HEAD, RETRY_BYTES

        self.fetcher.mark_pool_thread()
        for item in items:
            if self._out_of_time():
                item.why = "time_limit"
                continue
            if item.budget and origin in self.quiet:
                item.why = self.quiet[origin]
                continue
            policy = self._policy(origin)
            if item.budget and policy.mode == "not_checked":
                self.quiet[origin] = item.why = "no_answer"
                continue
            decision = policy.decide(self.cfg.product_token, item.url)
            if not decision.allowed:
                item.why, item.decision = "robots", decision.to_dict()
                continue
            if self._out_of_time():
                item.why = "time_limit"
                continue
            # An image is asked for as a browser asks (G07): an image service then answers the format a reader gets.
            headers = IMAGE_HEADERS if item.kind == IMAGE else None
            item.response = self.fetcher.get(item.url, item.purpose, item.max_bytes, method=item.method,
                                             extra_headers=headers)
            if item.response.error == "audit_deadline_skipped":
                item.why = "time_limit"
                continue
            self._went_quiet(item, item.response)
            if (item.method == "HEAD" and item.response.status in NO_HEAD and item.retry and origin not in self.quiet
                    and not self._out_of_time()):
                again = self.fetcher.get(item.url, GET_PURPOSE, RETRY_BYTES)
                if again.error != "audit_deadline_skipped":
                    item.retry_response = again
                    self._went_quiet(item, again)

    def _went_quiet(self, item: Item, response: RawResponse) -> None:
        if not item.budget:
            return
        if response.status == 429:
            self.quiet[item.origin] = "refused"
        elif response.error is not None or response.status is None:
            self.quiet[item.origin] = "no_answer"

    def join(self) -> None:
        """Wait for the workers (each stops at the time limit or a stop), then hand the answers to the collectors."""
        if self.joined:
            return
        if self._futures:
            busy = not all(f.done() for f in self._futures)
            if busy:
                self.fetcher.begin_step("other_sites_wait")
            wait(self._futures)
            self._executor.shutdown(wait=True)
        self.finished_mono = _clock.monotonic()
        self.joined = True
        for future in self._futures:
            failed = future.exception()
            if failed is not None:  # a worker's own failure is said, not a silent gap; its addresses stay not checked
                self.result.collector_errors.setdefault("other_sites", f"{type(failed).__name__}: {str(failed)[:300]}")
        for origin, policy in self.policies.items():
            self.result.robots_policy_by_origin.setdefault(origin, policy)
        self._settle_budget()
        self._step_row()
        for fill in self._later:
            fill()
        self._later.clear()

    def _sent(self, item: Item) -> list[RawResponse]:
        return [r for r in (item.response, item.retry_response) if r is not None and r.error != "audit_deadline_skipped"]

    def _settle_budget(self) -> None:
        from . import external_links as external

        held = external.budget(self.result, self.cfg)
        for origin in self.sites:
            if origin not in held.sites:
                held.sites.append(origin)
        for origin in self.robots_paid:
            spent = self.robots_spent.get(origin, 0)
            held.requests += spent
            held.robots_requests += spent
        for item in self.items:
            if item.budget:
                sent = len(self._sent(item))
                held.requests += sent
                held.same_as_requests += sent if item.same_as else 0
        for origin, why in self.quiet.items():
            held.quiet.setdefault(origin, why)
        # What external_links.check would have answered for each CHECK address, so a later check reads it.
        for item in self.items:
            if item.kind != CHECK or item.url in held.answers:
                continue
            entry = self.check_entry(item)
            # Qualify the actual pool observation through the same guarded engine path.
            # All queued initial requests are settled first; corroboration spends only actual remaining room.
            if entry.get("requested_at"):
                entry = external.check(self.fetcher, self.result, self.cfg, item.url, same_as=item.same_as, initial=entry)
            if not entry["checked"] and entry["verdict"] in external.UNCHECKED and not entry.get("requested_at"):
                held.not_asked[entry["verdict"]] = held.not_asked.get(entry["verdict"], 0) + 1
            if entry["verdict"] != "time_limit":
                held.answers[item.url] = entry
        for url, why in self.unplanned.items():
            if url in held.answers:
                continue
            held.not_asked[why] = held.not_asked.get(why, 0) + 1
            held.answers[url] = {"url": url, "checked": False, "verdict": why, "reason": external.REASONS[why]}

    def check_entry(self, item: Item) -> dict[str, Any]:
        """external_links.check's answer for a CHECK item (or, for an address IDX-6 asked, from IDX-6's request)."""
        from . import external_links as external

        cached = external.budget(self.result, self.cfg).answers.get(item.url)
        if cached is not None:
            return cached
        source = item
        idx6 = self.keyed.get((item.url, IDX6))
        if item.by_idx6 or (idx6 is not None and idx6.response is not None and idx6.why is None):
            source = idx6
        if source.why is not None or source.response is None:
            why = source.why or "time_limit"
            return {"url": item.url, "checked": False, "verdict": why, "reason": external.REASONS[why]}
        response = source.retry_response or source.response
        if source is idx6:
            entry = {"url": item.url, "status": response.status, "error": response.error, "location": _location(response, item.url),
                     "requested_at": response.started_at, "method": "GET", "asked_by": "IDX-6 (other_site_link)"}
        else:
            entry = {"url": item.url, "status": response.status, "error": response.error, "requested_at": response.started_at,
                     "location": _location(response, item.url),
                     "method": "GET" if source.retry_response else "HEAD"}
        entry["attempts"] = [{"url": item.url, "method": "GET" if source is idx6 or response is source.retry_response else "HEAD",
            "status": response.status, "error": response.error, "requested_at": response.started_at,
            "location": _location(response, item.url), "body_bytes": len(response.body), "truncated": response.truncated}
            for response in self._sent(source)]
        found = external.verdict(entry["status"], entry["error"])
        entry.update(checked=found in ("works", "broken"), verdict=found)
        if found in external.REASONS:
            entry["reason"] = external.REASONS[found]
        return entry

    def _step_row(self) -> None:
        """The pool's row of the step timing table: its span, its requests, and the time none of them was in flight."""
        if self.started_mono is None or not self._futures:
            return
        seqs = set(self.fetcher.pool_seqs)
        records = [r for r in self.fetcher.log if r.seq in seqs and r.started_mono is not None and r.ended_mono is not None]
        end = max([self.started_mono] + [r.ended_mono for r in records])
        spans = sorted((r.started_mono, r.ended_mono) for r in records)
        busy, cursor = 0.0, self.started_mono
        for a, b in spans:
            a = max(a, cursor)
            if b > a:
                busy += b - a
                cursor = b
        seconds = max(0.0, end - self.started_mono)
        row = {"step": "other_sites", "started_at": self.started_at, "seconds": round(seconds, 1),
               "requests": len(seqs), "waiting_s": round(max(0.0, seconds - busy), 1)}
        steps = self.fetcher.steps
        at = next((n + 1 for n, s in enumerate(steps) if s.get("step") == "crawl"), len(steps))
        steps.insert(at, row)


def _location(response: RawResponse, url: str) -> str | None:
    return normalize_url(response.headers["location"], url) if response.headers.get("location") else None


def active(result: CrawlResult) -> OtherSitePool | None:
    """The pool while it runs. Once joined, a collector asks in turn again (a page reader's second pass, for one)."""
    pool = getattr(result, "_other_sites", None)
    return pool if pool is not None and not pool.joined else None


# -- building the queue --------------------------------------------------------------------------------------------------

def build(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig) -> OtherSitePool:
    """The queue, in the order the steps asked before, with every cap applied (the same links every run)."""
    from . import external_links as external
    from .index_data import misplaced_links
    from .structure_data import OG_IMAGE_BYTES, _targets, image_sample, other_site_link_targets

    pool = OtherSitePool(fetcher, result, cfg)
    crawled = {p.url for p in result.pages}

    def add(item: Item) -> Item:
        pool.items.append(item)
        pool.keyed[(item.url, item.kind)] = item
        return item

    # IDX-6: its own cap, outside the budget; its robots.txt reads are free for the budget (as before).
    rows, _family = misplaced_links(result, cfg)
    free_robots = set(result.robots_policy_by_origin)
    for n, url in enumerate(dict.fromkeys(row["target"] for row in rows)):
        item = add(Item(url, IDX6, "other_site_link", 64 * 1024, budget=False))
        if n >= cfg.idx6_other_site_checks_max:
            item.why = "cap"
        else:
            free_robots.add(item.origin)

    held = external.budget(result, cfg)
    state = {"requests": held.requests, "same_as": held.same_as_requests}
    sites = list(held.sites)
    known_robots = set(free_robots)

    def plan(url: str, kind: str, purpose: str, max_bytes: int, method: str = "GET", same_as: bool = False):
        """external_links.room's caps, applied now. Returns the item, or the reason it is not asked."""
        if not held.enabled and not same_as:
            return "off"
        if same_as and state["same_as"] >= held.same_as_max:
            return "cap"
        origin = origin_of(url)
        new_site = origin not in sites
        if new_site and len(sites) >= held.sites_max:
            return "sites_cap"
        needed = 2 if new_site and origin not in known_robots else 1
        if held.enabled and state["requests"] + needed > held.cap:
            return "cap"
        if new_site:
            sites.append(origin)
        if origin not in known_robots:
            known_robots.add(origin)
            pool.robots_paid.add(origin)
            state["requests"] += 1
        state["requests"] += 1
        state["same_as"] += 1 if same_as else 0
        return add(Item(url, kind, purpose, max_bytes, method=method, same_as=same_as))

    def plan_check(url: str, same_as: bool) -> None:
        if (url, CHECK) in pool.keyed or url in pool.unplanned or url in held.answers:
            return
        idx6 = pool.keyed.get((url, IDX6))
        if idx6 is not None and idx6.why is None:
            add(Item(url, CHECK, external.HEAD_PURPOSE, 0, method="HEAD", same_as=same_as, budget=False, by_idx6=True))
            return
        found = plan(url, CHECK, external.HEAD_PURPOSE, 0, method="HEAD", same_as=same_as)
        if isinstance(found, str):
            pool.unplanned[url] = found

    from .access_data import key_page_urls
    from .media_sample import asset_hosts, key_image_limit, own_image

    hosts = asset_hosts(result)
    # The structure step: sameAs profiles, og:images and hreflang alternates on another origin. An og:image on the
    # site's asset host is the site's own (P1): structure_data asks for it, not this queue.
    for url, kind in _targets(result):
        if url in crawled or origin_of(url) == result.origin or (kind == "image" and own_image(url, result, hosts)):
            continue
        if kind == "same_as":
            plan_check(url, True)
        else:
            purpose_kind = OG if kind == "image" else HTML
            found = plan(url, purpose_kind, external.GET_PURPOSE, OG_IMAGE_BYTES if kind == "image" else cfg.max_body_bytes)
            if isinstance(found, str):
                add(Item(url, purpose_kind, external.GET_PURPOSE, 0, why=found))
    # STR-7: images on another site, only when links to other sites are checked. The site's own asset host is not
    # another site (maya_audit.media_sample): the same sample and the same test as structure_data's.
    sample, _count = image_sample(result, cfg.image_checks_max, key_page_urls(result, cfg), key_image_limit(cfg))
    for url, _pages in sample:
        if own_image(url, result, hosts):
            continue
        found = plan(url, IMAGE, "image_status", 4096) if cfg.check_external_links else "off"
        if isinstance(found, str):
            add(Item(url, IMAGE, "image_status", 0, why=found))
    # Links to other sites, most-linked first, only when links to other sites are checked.
    if cfg.check_external_links:
        for row in other_site_link_targets(result, cfg):
            plan_check(row["url"], False)

    # What is left under the cap is room for a GET after a HEAD the site does not take, first links first.
    room = (held.cap - state["requests"]) if held.enabled else (held.same_as_max - state["same_as"])
    for item in pool.items:
        if room <= 0:
            break
        if item.method == "HEAD" and item.why is None and not item.by_idx6 and (held.enabled or item.same_as):
            item.retry = True
            room -= 1
    pool.sites = sites
    return pool


def start(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig) -> OtherSitePool | None:
    """Build the queue and start the pool, when adaptive pacing is on (DECISIONS 219 part 2). None when it is off."""
    if not cfg.adaptive_pacing:
        return None
    pool = build(fetcher, result, cfg)
    pool.start()
    result._other_sites = pool
    return pool
