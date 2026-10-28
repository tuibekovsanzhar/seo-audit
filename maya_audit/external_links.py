"""Requests to other sites: whether a page another site holds still exists (DECISIONS 211; amends 35).

A page links to another site (an `<a href>`, an Organization's sameAs profile, an og:image on a CDN, an hreflang
alternate, a link in llms.txt). Whether that address still leads somewhere is asked once, politely, through the crawl's
own fetcher: the same user agent, pace, time limit and URL safety (a private or reserved address is refused), never
through a page reader or a paid provider. Before the first request to another site its robots.txt is fetched and
obeyed, and that request counts toward the cap.

- A link starts with HEAD; suspicious404/410, unsupported HEAD405/501 and redirects receive bounded GET corroboration (at most4GETs,4KB each), within the same shared cap. An og:image and an hreflang alternate are read with a GET by `structure_data`, which asks this module for
  room first and reports what it sent.
- Broken means GET-confirmed404 or410. A redirect is followed within guards; a recorded cycle remains a request-specific finding and an incomplete walk remains unknown. 403, 429, 999, a 5xx, a timeout or a host that does not
  exist could not be checked, and is never called broken. After a 429, or a request that got no answer, that site is
  asked nothing more.
- At most `external_link_cap` requests in all (robots.txt included) and `CrawlConfig.external_sites_max` other sites.
  With `check_external_links` off only sameAs links are asked (at most `same_as_checks_max`, as DECISIONS 196 does).
- An address IDX-6 already asked (a link to another site at one of this site's paths, DECISIONS 196) is not asked again.

The state lives in memory on the crawl result (`CrawlResult._external`) while the audit runs; `summary` is what the
report keeps (`crawl.structure.external`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .config import CrawlConfig, external_link_cap
from .fetcher import Fetcher
from .models import CrawlResult
from .urls import normalize_url, origin_of

HEAD_PURPOSE = "external_link_head"
GET_PURPOSE = "external_link_status"
RETRY_BYTES = 4 * 1024
BROKEN = (404, 410)
# A HEAD the site does not take: asked again once as a GET.
NO_HEAD = (405, 501)

# Why an address of another site was not asked, or what its answer could not say. The keys are in the report's
# evidence and in llms.txt's link counts; the sentences are what the coverage and the evidence say.
REASONS = {
    "uncorroborated": "a suspicious HEAD response could not be corroborated by a GET within policy and budgets",
    "redirect_loop": "a GET redirect cycle was observed for this client",
    "redirect_limit": "redirect verification stopped without a proven cycle",
    "off": "links to other sites are not checked (--no-external-links)",
    "cap": "the cap of requests to other sites was reached",
    "sites_cap": "the cap of other sites was reached",
    "time_limit": "the audit's time limit was reached before the request could be sent",
    "robots": "the other site's robots.txt disallows it",
    "no_answer": "the other site did not answer (no such host, a timeout or a failed connection)",
    "refused": "the other site refused or limited the request (401, 403, 429, 999 or the like), so whether the page exists is not known",
    "server_error": "the other site answered with a server error (5xx), so whether the page exists is not known",
    "other_status": "the other site's answer does not say whether the page exists",
}
UNCHECKED = frozenset(REASONS)


@dataclass
class ExternalBudget:
    enabled: bool
    cap: int
    sites_max: int
    same_as_max: int
    requests: int = 0          # requests sent to other sites, robots.txt included
    robots_requests: int = 0
    same_as_requests: int = 0
    sites: list[str] = field(default_factory=list)          # other origins asked, in order
    quiet: dict[str, str] = field(default_factory=dict)     # origin -> why it is asked nothing more
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)  # url -> what `check` found
    not_asked: dict[str, int] = field(default_factory=dict)  # reason -> addresses not asked

    def summary(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "cap": self.cap, "sites_max": self.sites_max, "same_as_max": self.same_as_max,
                "requests": self.requests, "robots_requests": self.robots_requests, "sites": len(self.sites),
                "sites_asked": self.sites[:40], "sites_asked_nothing_more": dict(list(self.quiet.items())[:40]),
                "not_asked": dict(self.not_asked),
                "method": "HEAD with bounded GET corroboration of 404/410/405/501 and redirects; robots.txt and shared cap apply",
                "broken": "GET-confirmed 404 or 410; bounded redirect outcomes and unavailable corroboration are recorded separately"}


def pages_read(result: CrawlResult) -> int:
    return sum(1 for page in result.pages if page.readable_document() and page.analysis is not None)


def budget(result: CrawlResult, cfg: CrawlConfig) -> ExternalBudget:
    """The audit's one budget for requests to other sites, made the first time it is needed."""
    held = getattr(result, "_external", None)
    if held is None:
        held = ExternalBudget(enabled=cfg.check_external_links,
                              cap=external_link_cap(cfg.external_link_checks_max, cfg.external_link_checks_base,
                                                    pages_read(result), cfg.single_page),
                              sites_max=cfg.external_sites_max, same_as_max=cfg.same_as_checks_max)
        result._external = held
    return held


def _out_of_time(fetcher: Fetcher) -> bool:
    fetcher.poll_stop()
    return fetcher.deadline_mono is not None and time.monotonic() >= fetcher.deadline_mono


def room(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, url: str, *, same_as: bool = False) -> str | None:
    """None when `url` (on another site) may be asked now, else the reason it may not (a key of REASONS). Fetches and
    obeys that site's robots.txt first, counted toward the cap. The caller sends the request and calls `sent`."""
    held = budget(result, cfg)
    origin = origin_of(url)
    if not held.enabled and not same_as:
        return "off"
    if same_as and held.same_as_requests >= held.same_as_max:
        return "cap"
    if _out_of_time(fetcher):
        return "time_limit"
    # Links to other sites are the first to give way to the time limit (DECISIONS 219): one is asked only while the time
    # left is more than rendering, the performance rounds, the sitemap check and llms.txt's links are estimated to need.
    # A sameAs profile is part of the structure checks (as DECISIONS 196) and is not held back.
    if not same_as:
        from .timeplan import short_of_time

        if short_of_time(fetcher, result, cfg):
            return "time_limit"
    if origin in held.quiet:
        return held.quiet[origin]
    new_site = origin not in held.sites
    if new_site and len(held.sites) >= held.sites_max:
        return "sites_cap"
    # With the check on, everything counts toward the cap; with it off, the sameAs cap alone bounds the requests.
    needed = 2 if new_site and origin not in result.robots_policy_by_origin else 1
    if held.enabled and held.requests + needed > held.cap:
        return "cap"
    if new_site:
        held.sites.append(origin)
    if origin not in result.robots_policy_by_origin:
        from .crawler import load_robots  # local import: crawler does not import this module

        before = len(fetcher.log)
        result.robots_policy_by_origin[origin] = load_robots(fetcher, origin, cfg)
        spent = len(fetcher.log) - before
        held.requests += spent
        held.robots_requests += spent
    policy = result.robots_policy_by_origin[origin]
    if policy.mode == "not_checked":
        held.quiet[origin] = "no_answer"
        return "no_answer"
    if not policy.decide(cfg.product_token, url).allowed:
        return "robots"
    if held.enabled and held.requests + 1 > held.cap:
        return "cap"
    if _out_of_time(fetcher):
        return "time_limit"
    return None


def verdict(status: int | None, error: str | None) -> str:
    """"works", "broken", or the key of REASONS that says why the answer settles nothing."""
    if error is not None or status is None:
        return "time_limit" if error == "audit_deadline_skipped" else "no_answer"
    if status in BROKEN:
        return "broken"
    if 200 <= status < 400:
        return "works"
    if status in (401, 403, 429, 999):
        return "refused"
    if status >= 500:
        return "server_error"
    return "other_status"


def sent(result: CrawlResult, cfg: CrawlConfig, url: str, response, *, same_as: bool = False, quiet: bool = True) -> None:
    """Count one request `room` allowed, and stop asking a site that limited Maya or did not answer.

    `quiet=False` counts the request without silencing the site: a HEAD that failed in transport is followed by one GET
    (A23), and only that GET's failure says the site does not answer."""
    held = budget(result, cfg)
    if response.error == "audit_deadline_skipped":
        return
    held.requests += 1
    held.same_as_requests += 1 if same_as else 0
    origin = origin_of(url)
    if response.status == 429:
        held.quiet[origin] = "refused"
    elif quiet and (response.error is not None or response.status is None):
        held.quiet[origin] = "no_answer"


def _from_idx6(result: CrawlResult, url: str) -> dict[str, Any] | None:
    """What IDX-6's own request to this address got (DECISIONS 196), so it is not asked twice."""
    seen = (getattr(getattr(result, "index", None), "other_site_targets", None) or {}).get(url)
    if not seen or not seen.get("requested_at"):
        return None
    return {"url": url, "status": seen.get("status"), "error": seen.get("error"), "location": seen.get("location"),
            "requested_at": seen.get("requested_at"), "method": "GET", "asked_by": "IDX-6 (other_site_link)"}


def check(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, url: str, *, same_as: bool = False, initial: dict | None = None) -> dict[str, Any]:
    """Whether `url`, on another site, still leads somewhere: {"url", "checked", "verdict", "status", "error",
    "location", "requested_at", "method", "reason"}. "checked" is True for "works" and "broken"; otherwise "verdict"
    is a key of REASONS and "reason" its sentence. Each address is asked at most once in an audit."""
    held = budget(result, cfg)
    if url in held.answers:
        return held.answers[url]
    entry = initial or _from_idx6(result, url)
    prior_redirect = entry if entry is not None and entry.get("status") is not None and (
        300 <= entry["status"] < 400 or (entry.get("method") == "HEAD" and entry["status"] in BROKEN + NO_HEAD)) else None
    if prior_redirect:
        entry = None  # A reused redirect is a lead, not proof of its destination.
    if entry is None:
        why = None if prior_redirect else room(fetcher, result, cfg, url, same_as=same_as)
        if why is not None:
            held.not_asked[why] = held.not_asked.get(why, 0) + 1
            entry = {"url": url, "checked": False, "verdict": why, "reason": REASONS[why]}
            if why != "time_limit":
                held.answers[url] = entry
            return entry
        attempts = list(prior_redirect.get("attempts") or [prior_redirect]) if prior_redirect else []
        current, method, seen = url, "HEAD", set()
        if prior_redirect:
            current = (prior_redirect.get("location") or url) if 300 <= prior_redirect["status"] < 400 else url
            method = "GET"
            seen = {url} if prior_redirect.get("method") == "GET" and 300 <= prior_redirect["status"] < 400 else set()
        reason = None
        unavailable = None
        # At most one HEAD and four GETs, including redirect hops. Every hop checks robots,
        # public-target safety, deadline and the shared request budget; no automatic redirects.
        for _ in range(max(0, 4 - sum(a.get("method") == "GET" for a in attempts)) if prior_redirect else 5):
            why = room(fetcher, result, cfg, current, same_as=same_as)
            if why:
                unavailable = why
                reason = "uncorroborated" if attempts and attempts[0]["status"] in BROKEN else why
                break
            response = fetcher.get(current, HEAD_PURPOSE if method == "HEAD" else GET_PURPOSE,
                                   0 if method == "HEAD" else RETRY_BYTES, method=method)
            # Some servers drop a HEAD they do not handle (A23): one GET is tried before the site is taken as silent.
            head_failed = (method == "HEAD" and (response.error is not None or response.status is None)
                           and response.error != "audit_deadline_skipped" and not str(response.error).startswith("timeout"))
            sent(result, cfg, current, response, same_as=same_as, quiet=not head_failed)
            location = normalize_url(response.headers["location"], current) if response.headers.get("location") else None
            attempts.append({"url": current, "method": method, "status": response.status, "error": response.error,
                             "requested_at": response.started_at, "location": location,
                             "body_bytes": len(response.body), "truncated": response.truncated})
            if head_failed:
                method = "GET"
                continue
            if response.error or response.status is None:
                break
            if method == "HEAD" and response.status in BROKEN + NO_HEAD:
                method = "GET"
                continue
            if 300 <= response.status < 400:
                if not location:
                    reason = "redirect_limit"
                    break
                # A HEAD redirect is a lead, never proof of its destination's GET outcome.
                if method == "GET":
                    seen.add(current)
                    if location in seen:
                        reason = "redirect_loop"
                        break
                current, method = location, "GET"
                continue
            break
        else:
            reason = "redirect_limit"
        last = attempts[-1] if attempts else {}
        entry = {"url": url, "status": last.get("status"), "error": last.get("error"),
                 "requested_at": last.get("requested_at"), "location": last.get("location"),
                 "method": last.get("method"), "final_url": last.get("url"), "attempts": attempts, "corroboration_unavailable": unavailable}
        if reason:
            entry.update(checked=False, verdict=reason, reason=REASONS[reason])
            held.answers[url] = entry
            return entry
    found = verdict(entry["status"], entry["error"])
    entry.update(checked=found in ("works", "broken"), verdict=found)
    if found in REASONS:
        entry["reason"] = REASONS[found]
    if found != "time_limit":
        held.answers[url] = entry
    return entry


def other_site(url: str, origin: str, site: str, family: tuple[str, ...]) -> bool:
    """Whether `url` is on another site: not this origin, not another host of this site (www, a subdomain), not a
    domain of the same brand (DECISIONS 196), and an http(s) address."""
    from .urls import in_domain_family, registrable_domain

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or origin_of(url) == origin:
        return False
    return registrable_domain(host) != site and not in_domain_family(host, family)
