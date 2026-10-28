"""Requests made after the crawl for the IDX checks.

Requests to the audited site go through the crawl's fetcher (same identity,
politeness, request log, robots.txt compliance audited by INT-4). Calls to the
Google Search Console and Bing Webmaster APIs are not requests to the audited
site: they use a separate client and are recorded here, with secrets redacted.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import certifi
import httpx

from .network import PublicTransport

from .analysis import analyze_html
from .classify import classify_fetch, empty_response, error_disclosure
from .config import CrawlConfig
from .directives import noindex_directives
from .fetcher import Fetcher, tls_verify, utc_now
from .html_links import decode_body, is_html
from .models import CrawlResult, FetchClass, StopReason
from .urls import host_allowed, is_loopback_host, is_registrable_domain, non_page_kind, normalize_url, same_origin, validate_public_target, UnsafeTargetError, public_addresses

KEPT = ("server", "content-type", "location", "x-robots-tag", "link", "retry-after")
# OpenSSL X509 verification codes (x509_vfy.h) mapped to a plain label.
VERIFY_CODES = {10: "expired", 9: "not_yet_valid", 62: "hostname_mismatch", 18: "self_signed",
                19: "untrusted_root", 20: "untrusted_issuer", 21: "untrusted_issuer"}


@dataclass
class IndexData:
    refetches: list[dict[str, Any]] = field(default_factory=list)
    canonical_targets: dict[str, dict[str, Any]] = field(default_factory=dict)
    # IDX-2: one entry per checked host (start host, then its www / non-www variant).
    hosts: list[dict[str, Any]] = field(default_factory=list)
    variant_note: str | None = None
    gsc: dict[str, Any] | None = None
    bing: dict[str, Any] | None = None
    indexnow: dict[str, Any] | None = None
    bing_skipped: str | None = None
    # IDX-1: the one request for a made-up address, and what came back.
    soft_404: dict[str, Any] | None = None
    # IDX-3: a URL that looped in the crawl, and the homepage, requested again: url -> {"url", "why" ("loop" or
    # "homepage"), "attempts": [{"outcome", "hops", ...}], "reason" when nothing could be asked} (DECISIONS 195).
    redirect_rechecks: dict[str, dict[str, Any]] = field(default_factory=dict)
    # IDX-6: links to another site at one of this site's own paths, each distinct address requested once:
    # url -> {"url", "checked", "status" | "reason"} (DECISIONS 196).
    other_site_targets: dict[str, dict[str, Any]] = field(default_factory=dict)
    # IDX-1: pages empty to Maya's own user agent twice, a few of them asked once with a browser user agent (first
    # review C1/C2): {"user_agent", "purpose", "cap", "answers": [...], "reason" when nothing was sent}.
    empty_browser_check: dict[str, Any] | None = None
    # IDX-5: the sitemap URLs the crawl did not read, each asked once with a light request (DECISIONS 206). Filled by
    # the last data collector of the audit (`check_sitemap_urls`); None until it ran.
    sitemap_check: "SitemapCheck | None" = None


def _observe(fetcher: Fetcher, url: str, purpose: str, cfg: CrawlConfig) -> dict[str, Any]:
    response = fetcher.get(url, purpose, cfg.max_body_bytes)
    classification = classify_fetch(response.status, response.headers, response.body, response.error)
    content_type = response.headers.get("content-type")
    analysis = None
    if response.status and 200 <= response.status < 300 and is_html(content_type) and response.body:
        analysis = analyze_html(decode_body(response.body, content_type))
    return {
        "url": url, "requested_at": response.started_at, "status": response.status, "error": response.error,
        "elapsed_ms": response.elapsed_ms, "ttfb_ms": response.ttfb_ms, "truncated": response.truncated,
        "fetch_class": classification.fetch_class.value, "headers": {k: v for k, v in response.headers.items() if k in KEPT},
        "location": normalize_url(response.headers["location"], url) if response.headers.get("location") else None,
        "analysis": analysis,
        "noindex": noindex_directives(analysis, response.headers),
        # IDX-1: an answer that says "OK" and sends nothing (DECISIONS 204).
        "empty_response": classification.fetch_class == FetchClass.OK and empty_response(
            response.status, content_type, response.body, response.truncated, cfg.empty_response_max_bytes),
        "body_bytes": len(response.body),
        "readable_html": bool(analysis and not empty_response(response.status, content_type, response.body, response.truncated, cfg.empty_response_max_bytes)),
    }


EMPTY_CHECK_PURPOSE = "empty_browser_check"


def empty_browser_check(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, policy, refetches: list[dict[str, Any]],
                        key_urls: list[str]) -> dict[str, Any]:
    """Ask a few pages that were empty twice to Maya's own user agent once more, as a browser (first review C1/C2).

    Two empty answers to one client are one client's view: a site that sends nothing to automated clients and a full
    page to browsers (seen live: 57 URLs empty to Maya, read fine by another reader) is an access problem, not empty
    pages. At most config.EMPTY_BROWSER_CHECK_URLS addresses (the homepage and key pages first), one GET each with
    probes.BROWSER_USER_AGENT and the `X-Maya-Probe: ua-differential` header, through the same fetcher (its pace, time
    limit and request log), only where robots.txt allows Maya's own token, never retried. Off with `probes_enabled`, as
    the ACC-4 user-agent check is (DECISIONS 205)."""
    from .config import EMPTY_BROWSER_CHECK_URLS
    from .probes import BROWSER_USER_AGENT, PROBE_HEADERS
    entry: dict[str, Any] = {"user_agent": BROWSER_USER_AGENT, "purpose": EMPTY_CHECK_PURPOSE,
                             "cap": EMPTY_BROWSER_CHECK_URLS, "answers": []}
    again = {r["url"]: r["refetch"] for r in refetches}
    twice = [p.url for p in result.pages if (p.analysis or {}).get("empty_response") and p.status and 200 <= p.status < 300
             and (again.get(p.url) or {}).get("empty_response") and not (again.get(p.url) or {}).get("error")]
    if not twice:
        entry["reason"] = "no page was empty on two requests"
        return entry
    home = next((p.url for p in result.pages if p.depth == 0), None)
    first = set(key_urls) | ({home} if home else set())
    ordered = sorted(twice, key=lambda u: u not in first)  # stable: crawl order inside each group
    if not cfg.probes_enabled:
        entry["reason"] = "requests with another user agent are switched off (probes)"
    elif result.stop_reason in _NO_MORE_REQUESTS:
        entry["reason"] = f"the crawl stopped early ({result.stop_reason.value}); no extra request was sent"
    if "reason" in entry:
        return entry
    for url in ordered[:EMPTY_BROWSER_CHECK_URLS]:
        if not policy.decide(cfg.product_token, url).allowed:
            entry["answers"].append({"url": url, "sent": False, "reason": "robots.txt disallows Maya's user agent"})
            continue
        response = fetcher.get(url, EMPTY_CHECK_PURPOSE, cfg.max_body_bytes, user_agent=BROWSER_USER_AGENT,
                               extra_headers=PROBE_HEADERS)
        if response.error == "audit_deadline_skipped":
            entry["answers"].append({"url": url, "sent": False, "reason": "the audit's time limit was reached"})
            break
        content_type = response.headers.get("content-type")
        fetch_class = classify_fetch(response.status, response.headers, response.body, response.error).fetch_class
        ok = fetch_class == FetchClass.OK and bool(response.status) and 200 <= response.status < 300
        empty = ok and empty_response(response.status, content_type, response.body, response.truncated,
                                      cfg.empty_response_max_bytes)
        entry["answers"].append({"url": url, "sent": True, "requested_at": response.started_at, "status": response.status,
                                 "error": response.error, "fetch_class": fetch_class.value, "body_bytes": len(response.body),
                                 "empty_response": empty, "content": ok and not empty})
    return entry


def soft_404_probe(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, policy) -> dict[str, Any]:
    """Ask once for a page that cannot exist and record the answer. A site should say 404 (or 410).

    One request, through the same fetcher as everything else (same user agent, same delay between
    requests), to a path made up for this audit, and only if robots.txt allows it. A redirect is
    recorded, not followed: following it would be a second request.
    """
    url = f"{result.origin}/maya-audit-no-such-page-{secrets.token_hex(8)}"
    entry: dict[str, Any] = {"url": url, "sent": False,
                             "path": "random, generated for this audit, so no real page can have it"}
    if not cfg.soft_404_probe:
        entry["reason"] = "switched off (--no-soft-404-probe)"
    elif result.stop_reason in (StopReason.RATE_LIMIT, StopReason.ROBOTS_DISALLOWED, StopReason.ERROR, StopReason.NETWORK):
        entry["reason"] = f"the crawl stopped early ({result.stop_reason.value}); no extra request was sent"
    elif not any(p.status and 200 <= p.status < 300 for p in result.pages):
        entry["reason"] = "no page of the site answered 200, so a missing page cannot be told from the rest"
    elif not policy.decide(cfg.product_token, url).allowed:
        entry["reason"] = "robots.txt disallows this path for Maya's user agent"
    elif fetcher.deadline_mono is not None and time.monotonic() >= fetcher.deadline_mono:
        entry["reason"] = "the audit's time limit was reached before the request could be sent"
    else:
        response = fetcher.get(url, "soft_404_probe", 64 * 1024)
        if response.error == "audit_deadline_skipped":
            entry["reason"] = "the audit's time limit was reached before the request could be sent"
            return entry
        location = normalize_url(response.headers["location"], url) if response.headers.get("location") else None
        title = None
        content_type = response.headers.get("content-type")
        if response.status and 200 <= response.status < 300 and is_html(content_type) and response.body:
            title = analyze_html(decode_body(response.body, content_type)).get("title")
        entry.update(sent=True, requested_at=response.started_at, status=response.status, error=response.error,
                     redirect_location=location, final_url=location or url,
                     final_url_note=("the redirect was recorded, not followed (one request only)" if location else
                                     "no redirect: the answer came from the requested address"),
                     title=title)
    return entry


# -- IDX-3: redirects that loop -----------------------------------------------------------------------------------------

# Crawl outcomes after which no further request is sent to the site.
_NO_MORE_REQUESTS = (StopReason.RATE_LIMIT, StopReason.ROBOTS_DISALLOWED, StopReason.ERROR, StopReason.NETWORK)
LOOPS, RESOLVES, ANSWERED, NOT_CHECKED = "loops", "resolves", "answered", "not_checked"


def crawl_redirects(result: CrawlResult) -> dict[str, str]:
    """Every redirecting URL of the crawl and where it pointed, from the one response the crawl has for it."""
    return {p.url: p.redirect_location for p in result.pages if p.status and 300 <= p.status < 400 and p.redirect_location}


def redirect_walks(redirects: dict[str, str]) -> tuple[list[list[str]], list[list[str]]]:
    """(chains, loops) in the crawl's redirect map. A chain is the list of its hops from the first URL to the last
    target; a loop is the list of its hops ending on the URL it comes back to (a self-redirect is [url, url])."""
    targets = set(redirects.values())
    chains, loops, walked = [], [], set()
    for head in redirects:
        if head in targets:
            continue
        hops, seen, current = [head], {head}, redirects[head]
        walked.add(head)
        while current:
            if current in seen:
                loops.append(hops + [current])
                break
            hops.append(current)
            seen.add(current)
            walked.add(current)
            current = redirects.get(current)
        else:
            chains.append(hops)
    for url in redirects:  # cycles with no head
        if url in walked:
            continue
        cycle, current = [], url
        while current and current not in walked:
            walked.add(current)
            cycle.append(current)
            current = redirects.get(current)
        loops.append(cycle + [url])
    return chains, loops


def cookie_pairs(set_cookies: list[str]) -> dict[str, str]:
    """{name: value} of each Set-Cookie header, the attributes (Path, Expires, ...) left out. Held in memory only."""
    out: dict[str, str] = {}
    for raw in set_cookies:
        pair = raw.split(";", 1)[0].strip()
        if "=" in pair and pair.split("=", 1)[0].strip():
            name, value = pair.split("=", 1)
            out[name.strip()] = value.strip()
    return out


def _walk_again(fetcher: Fetcher, url: str, cfg: CrawlConfig, policy, origin: str, cookies: bool = False) -> dict[str, Any]:
    """Follow `url` once more, hop by hop, each hop its own logged request through the crawl's fetcher. The outcome:
    "loops" (it repeated a URL and cookie state in this walk), "resolves" (it ended on a 2xx
    answer), "answered" (it ended on something else: an error status, a block, a redirect off the audited site) or
    "not_checked" (robots.txt, the time limit or a failed connection kept a hop from being read).

    With `cookies` (DECISIONS 217) the walk sends back, as a Cookie header, the cookies this site set during this walk
    and nothing else: purpose `redirect_recheck_cookies`, Maya's own user agent. The cookies live in this function
    only; a hop records whether the site set one (`set_cookie`), never its value."""
    purpose = "redirect_recheck_cookies" if cookies else "redirect_recheck"
    jar: dict[str, str] = {}
    hops: list[dict[str, Any]] = []
    # A loop is coming back to an address with the same request: with cookies, the same cookies too.
    seen, current = {(url, None)}, url
    for _ in range(max(1, cfg.redirect_recheck_max_hops)):
        if not same_origin(current, origin):
            return {"outcome": ANSWERED, "hops": hops, "reason": f"redirects off the audited site, to {current}; not followed"}
        if not policy.decide(cfg.product_token, current).allowed:
            return {"outcome": NOT_CHECKED, "hops": hops, "reason": "robots.txt disallows this address for Maya's user agent"}
        if fetcher.deadline_mono is not None and time.monotonic() >= fetcher.deadline_mono:
            # Said here, without asking the fetcher: a refused request would count as the time limit cutting this step.
            return {"outcome": NOT_CHECKED, "hops": hops, "reason": "the audit's time limit was reached before the request could be sent"}
        sent = "; ".join(f"{name}={value}" for name, value in jar.items()) if cookies and jar else None
        response = fetcher.get(current, purpose, 64 * 1024, cookie=sent)
        if response.error == "audit_deadline_skipped":
            return {"outcome": NOT_CHECKED, "hops": hops, "reason": "the audit's time limit was reached before the request could be sent"}
        location = normalize_url(response.headers["location"], current) if response.headers.get("location") else None
        hop = {"url": current, "requested_at": response.started_at, "status": response.status, "error": response.error,
               "location": location, "set_cookie": bool(response.set_cookies)}
        if cookies:
            hop["cookie_sent"] = sent is not None
            jar.update(cookie_pairs(response.set_cookies))
        hops.append(hop)
        if response.error is not None or response.status is None:
            return {"outcome": NOT_CHECKED, "hops": hops, "reason": f"the request failed ({response.error})"}
        if 300 <= response.status < 400 and location:
            state = (location, "; ".join(f"{name}={value}" for name, value in jar.items()) if cookies and jar else None)
            if state in seen:
                return {"outcome": LOOPS, "hops": hops, "cycle_observed": True}
            seen.add(state)
            current = location
            continue
        content_type = response.headers.get("content-type")
        classification = classify_fetch(response.status, response.headers, response.body, response.error)
        readable = (200 <= response.status < 300 and classification.fetch_class == FetchClass.OK
                    and is_html(content_type) and bool(response.body.strip())
                    and not empty_response(response.status, content_type, response.body, response.truncated,
                                           cfg.empty_response_max_bytes))
        return {"outcome": RESOLVES if readable else ANSWERED, "hops": hops, "final_status": response.status,
                "readable_html": readable, "fetch_class": classification.fetch_class.value}
    return {"outcome": NOT_CHECKED, "hops": hops, "cycle_observed": False,
            "reason": f"hop limit ({cfg.redirect_recheck_max_hops}) reached without a proven cycle"}


def recheck_redirects(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, policy) -> dict[str, dict[str, Any]]:
    """IDX-3 (DECISIONS 195): one response is not enough to say "this URL never resolves". Every loop of the crawl (at
    most `max_refetches` of them) is walked `redirect_recheck_attempts` more times, and so is the homepage, whose one
    crawl answer may have been the lucky one. Same fetcher: same pace, robots.txt, time limit and request log."""
    from .access_data import homepage_url  # local import: access_data does not import this module

    _chains, loops = redirect_walks(crawl_redirects(result))
    wanted: dict[str, str] = {loop[0]: "loop" for loop in loops[: cfg.max_refetches]}
    home = homepage_url(result)
    if any(p.url == home and p.status and 200 <= p.status < 300 for p in result.pages):
        wanted.setdefault(home, "homepage")
    reason = None
    if cfg.redirect_recheck_attempts <= 0:
        reason = "re-checks are switched off"
    elif result.stop_reason in _NO_MORE_REQUESTS:
        reason = f"the crawl stopped early ({result.stop_reason.value}); no extra request was sent"
    elif policy.stops_requests:
        reason = "robots.txt could not be read, so Maya makes no further requests to this site"
    # A resumed crawl does not fetch the pages of its earlier sessions again, and neither do the re-checks.
    this_session = {r.url for r in fetcher.log if r.purpose == "page"} if len(result.sessions or []) > 1 else None
    out: dict[str, dict[str, Any]] = {}
    for url, why in wanted.items():
        entry: dict[str, Any] = {"url": url, "why": why, "attempts": []}
        out[url] = entry
        if reason:
            entry["reason"] = reason
            continue
        if this_session is not None and url not in this_session:
            entry["reason"] = "read in an earlier session of this resumed crawl, which is not fetched again"
            continue
        for _ in range(cfg.redirect_recheck_attempts):
            attempt = _walk_again(fetcher, url, cfg, policy, result.origin)
            entry["attempts"].append(attempt)
            if attempt["outcome"] == NOT_CHECKED and not attempt["hops"]:
                break  # robots.txt or the time limit: the next attempt would be refused the same way
        # Every cookie-less re-check looped: one more walk that sends back the cookies the site sets (DECISIONS 217).
        if why == "loop" and _native_cycles(entry, cfg.redirect_recheck_attempts):
            entry["cookie_walk"] = _walk_again(fetcher, url, cfg, policy, result.origin, cookies=True)
    return out


def observed_cycle(walk: dict[str, Any]) -> bool:
    """A cutoff is not a cycle. Older evidence must contain a closed redirect path."""
    if walk.get("outcome") != LOOPS or walk.get("cycle_observed") is False:
        return False
    # Historical walks lack the flag. A cookie transition cannot prove a repeated client state.
    hops = walk.get("hops") or []
    if walk.get("cycle_observed") is not True and any(h.get("cookie_sent") for h in hops):
        return False
    seen = set()
    for hop in hops:
        if hop.get("error") or (hop.get("cookie_sent") and walk.get("cycle_observed") is not True):
            return False
        seen.add(hop.get("url"))
        if 300 <= (hop.get("status") or 0) < 400 and hop.get("location") in seen:
            return True
    return False


def _native_cycles(entry: dict[str, Any], attempts_wanted: int) -> bool:
    attempts = entry.get("attempts") or []
    return bool(attempts_wanted > 0 and len(attempts) >= attempts_wanted and all(observed_cycle(a) for a in attempts))


def redirect_verdict(entry: dict[str, Any] | None, attempts_wanted: int) -> str:
    """Scoped native observations, never a claim about every visitor or future request.

    Legacy resolves outcomes recorded status only and cannot establish readable page content.
    Missing cookie verification cannot establish persistence.
    """
    entry = entry or {}
    if any(a.get("outcome") == RESOLVES and a.get("readable_html") is True for a in entry.get("attempts") or []):
        return "intermittent"
    if _native_cycles(entry, attempts_wanted):
        walk = entry.get("cookie_walk") or {}
        if walk.get("outcome") == RESOLVES and walk.get("readable_html") is True:
            return "cookie" if any(hop.get("cookie_sent") for hop in walk.get("hops") or []) else "intermittent"
        if observed_cycle(walk):
            return "always"
    return "unchecked"


# -- IDX-6: a link to another site at one of this site's own paths ------------------------------------------------------

def _path_key(url: str) -> str:
    return urlsplit(url).path.rstrip("/").casefold()


def misplaced_links(result: CrawlResult, cfg: CrawlConfig) -> tuple[list[dict[str, Any]], int]:
    """(links to another site whose path is the path of a page of this one, how many such links were left out because
    they go to a brand-family domain). The site's own other hosts (www, a blog subdomain) are not another site."""
    from .urls import in_domain_family, registrable_domain

    own_paths = {_path_key(u): u for u in list(result.discovered_urls) + list(result.sitemap_urls) if _path_key(u)}
    site = registrable_domain(urlsplit(result.origin).hostname or "")
    rows, family = [], 0
    for page in result.pages:
        for edge in page.external_links or []:
            host = urlsplit(edge["target"]).hostname or ""
            if registrable_domain(host) == site:
                continue
            twin = own_paths.get(_path_key(edge["target"]))
            if not twin:
                continue
            if in_domain_family(host, cfg.brand_family_domains):
                family += 1
                continue
            rows.append({"source": page.url, "target": edge["target"], "anchor": edge["anchor"],
                         "same_path_on_this_site": twin, "other_site": host})
    return rows, family


def check_other_site_targets(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig) -> dict[str, dict[str, Any]]:
    """IDX-6 (DECISIONS 196): ask each distinct other-site address once whether it leads to a page. The same rules as
    every request to another origin (maya_audit.structure_data): that origin's robots.txt is fetched and obeyed first,
    the fetcher refuses a non-public target, keeps the pace and the time limit, and no redirect is followed. Runs
    whether or not `check_external_links` is on: this is one link kind the owner asked to have verified."""
    from .crawler import load_robots  # local import: crawler does not import this module
    from .other_sites import IDX6, active
    from .urls import origin_of

    rows, _family = misplaced_links(result, cfg)
    out: dict[str, dict[str, Any]] = {}
    pool = active(result)
    if pool is not None:
        # Asked by the other-site pool (DECISIONS 219 part 2); written here once it is joined.
        for url in dict.fromkeys(row["target"] for row in rows):
            entry = out[url] = {"url": url, "checked": False}
            item = pool.item(url, IDX6)
            pool.later(lambda entry=entry, item=item: _idx6_fill(entry, item, cfg))
        return out
    sent = 0
    for url in dict.fromkeys(row["target"] for row in rows):
        entry: dict[str, Any] = {"url": url, "checked": False}
        out[url] = entry
        if sent >= cfg.idx6_other_site_checks_max:
            entry["reason"] = _IDX6_CAP.format(cap=cfg.idx6_other_site_checks_max)
            continue
        if fetcher.deadline_mono is not None and time.monotonic() >= fetcher.deadline_mono:
            entry["reason"] = _IDX6_TIME
            continue
        origin = origin_of(url)
        if origin not in result.robots_policy_by_origin:
            result.robots_policy_by_origin[origin] = load_robots(fetcher, origin, cfg)
        decision = result.robots_policy_by_origin[origin].decide(cfg.product_token, url)
        if not decision.allowed:
            entry["reason"] = f"robots.txt for {origin} disallows it: {decision.reason}"
            continue
        response = fetcher.get(url, "other_site_link", 64 * 1024)
        if response.error == "audit_deadline_skipped":
            entry["reason"] = _IDX6_TIME
            continue
        sent += 1
        _idx6_answer(entry, response, url)
    return out


_IDX6_CAP = "the cap of {cap} requests to other sites was reached"
_IDX6_TIME = "the audit's time limit was reached before the request could be sent"


def _idx6_answer(entry: dict[str, Any], response, url: str) -> None:
    entry.update(requested_at=response.started_at, status=response.status, error=response.error,
                 location=normalize_url(response.headers["location"], url) if response.headers.get("location") else None)
    if response.error is not None or response.status is None:
        entry["reason"] = f"the request failed ({response.error})"
    else:
        entry["checked"] = True


def _idx6_fill(entry: dict[str, Any], item, cfg: CrawlConfig) -> None:
    """IDX-6's entry from the other-site pool's answer (the same wording as when it is asked in turn)."""
    from .urls import origin_of

    if item is None or item.why == "time_limit" or (item.why is None and item.response is None):
        entry["reason"] = _IDX6_TIME
    elif item.why == "cap":
        entry["reason"] = _IDX6_CAP.format(cap=cfg.idx6_other_site_checks_max)
    elif item.why == "robots":
        entry["reason"] = f"robots.txt for {origin_of(item.url)} disallows it: {(item.decision or {}).get('reason')}"
    else:
        _idx6_answer(entry, item.response, item.url)


# -- IDX-5: every URL of the sitemap, not only those the crawl read (DECISIONS 206) --------------------------------------

# A light request reads at most this much: enough for the status, the headers, the meta robots tag and the canonical.
LIGHT_REQUEST_BYTES = 64 * 1024
# After this many blocked answers in a row no more light requests are sent (a 429 stops them at once, DECISIONS 52).
BLOCKED_IN_A_ROW = 3
# What one sitemap URL turned out to be. The first five are counted in IDX-5's share; "canonical_elsewhere" is a live
# page and "disallowed" was not asked: both are listed beside the share, not in it.
NOT_LIVE_KINDS = ("redirect", "not_found", "server_error", "empty", "noindex")
NOT_CHECKED_REASONS = {
    "cap": "not asked: the cap of light requests was reached (a sample spread over the site's sections was asked)",
    "rate_limit": "not asked: the site answered 429 (too many requests), so no further light request was sent",
    "blocked": f"not asked: the site blocked {BLOCKED_IN_A_ROW} light requests in a row, so no further one was sent",
    "time_limit": "not asked: the audit's time limit was reached before the request could be sent",
    "off": "not asked: the sitemap check is switched off (sitemap_check_max is 0)",
    "single_page": "not asked: a single-page audit asks for no other page",
    "crawl_stopped": "not asked: the crawl stopped early, so no further request was sent",
    "robots_unreadable": "not asked: robots.txt could not be read, so Maya makes no further requests to this site",
}


@dataclass
class SitemapCheck:
    """What the sitemap check asked and why the rest was not asked. `rows` holds one light request each, as
    `light_request` records it; the URLs the crawl read are judged from the crawl's own records, not copied here."""
    cap: int = 0
    listed: int = 0
    files: int = 0
    read_by_crawl: int = 0
    disallowed: list[str] = field(default_factory=list)
    wanted: int = 0  # URLs that needed a light request
    sampled: bool = False  # the cap left some of them out: the ones asked are a sample spread over the sections
    rows: list[dict[str, Any]] = field(default_factory=list)
    # ACC-8's own light requests to the links of llms.txt (purpose `llms_link_check`): IDX-1 counts their empty answers.
    llms_rows: list[dict[str, Any]] = field(default_factory=list)
    not_checked: dict[str, int] = field(default_factory=dict)  # reason -> how many URLs
    not_checked_sample: list[dict[str, str]] = field(default_factory=list)
    stopped_because: str | None = None  # "rate_limit", "blocked" or "time_limit"
    # Said when the time limit cut the check short (the collector reads it: maya_audit.audit.collect).
    reason: str | None = None


def light_request(fetcher: Fetcher, url: str, purpose: str, cfg: CrawlConfig) -> dict[str, Any]:
    """One GET that reads at most 64 KB and follows no redirect: the status, Location, the byte count, X-Robots-Tag,
    the meta robots tag and the canonical from the first 64 KB, the empty-page rule and the error-message rule."""
    response = fetcher.get(url, purpose, LIGHT_REQUEST_BYTES)
    content_type = response.headers.get("content-type")
    classification = classify_fetch(response.status, response.headers, response.body, response.error)
    analysis = None
    if response.status and 200 <= response.status < 300 and is_html(content_type) and response.body:
        analysis = analyze_html(decode_body(response.body, content_type))
    html = [u for u in (normalize_url(h, url) for h in (analysis or {}).get("canonicals", [])) if u]
    header = link_header_canonicals(response.headers.get("link"), url)
    return {
        "url": url, "requested_at": response.started_at, "status": response.status, "error": response.error,
        "fetch_class": classification.fetch_class.value, "content_type": content_type,
        "location": normalize_url(response.headers["location"], url) if response.headers.get("location") else None,
        "bytes": len(response.body), "truncated": response.truncated,
        "x_robots_tag": response.headers.get("x-robots-tag"),
        "noindex": noindex_directives(analysis, response.headers),
        "canonical": html[0] if html else (header[0] if header else None),
        "empty": classification.fetch_class == FetchClass.OK and empty_response(
            response.status, content_type, response.body, response.truncated, cfg.empty_response_max_bytes),
        "error_text": error_disclosure(response.body, response.status, content_type),
    }


def answer_kind(url: str, status: int | None, fetch_class: str, empty: bool, noindex, canonical: str | None) -> str:
    """What one answer says about a URL: one of NOT_LIVE_KINDS, "canonical_elsewhere", "live", or "blocked" /
    "no_answer" when it says nothing about the page (a challenge, a rate limit, a failed connection)."""
    if fetch_class in (FetchClass.BLOCKED.value, FetchClass.RATE_LIMITED.value):
        return "blocked"
    if fetch_class == FetchClass.ERROR.value or status is None:
        return "no_answer"
    if 300 <= status < 400:
        return "redirect"
    if 400 <= status < 500:
        return "not_found"
    if status >= 500:
        return "server_error"
    if not 200 <= status < 300:
        return "no_answer"
    if empty:
        return "empty"
    if noindex:
        return "noindex"
    # A canonical on the http:// or www variant of the URL's own address is the URL itself (review B02).
    variant = canonical_variant(canonical, url)
    if canonical and (variant["counterpart"] if variant else canonical) != url:
        return "canonical_elsewhere"
    return "live"


def page_kind(page) -> str:
    """`answer_kind` of a page the crawl read."""
    chosen, _, _ = effective_canonical(page) if page.analysis else (None, [], [])
    return answer_kind(page.url, page.status, page.fetch_class.value, bool((page.analysis or {}).get("empty_response")),
                       noindex_directives(page.analysis, page.headers) if page.analysis else
                       noindex_directives(None, page.headers), chosen)


def row_kind(row: dict[str, Any]) -> str:
    """`answer_kind` of one light request."""
    return answer_kind(row["url"], row.get("status"), row.get("fetch_class") or "", bool(row.get("empty")), row.get("noindex"),
                       row.get("canonical"))


def section_sample(urls: list[str], cap: int) -> list[str]:
    """At most `cap` of `urls`: one from each top-level section in turn (by the first part of the path), each section
    in its own sitemap order. The same list every run for the same sitemap."""
    sections: dict[str, list[str]] = {}
    for url in urls:
        sections.setdefault(urlsplit(url).path.strip("/").split("/", 1)[0].casefold(), []).append(url)
    out: list[str] = []
    depth = 0
    while len(out) < cap and any(depth < len(group) for group in sections.values()):
        for group in sections.values():
            if depth < len(group) and len(out) < cap:
                out.append(group[depth])
        depth += 1
    return out


class LightRequests:
    """Light requests through the crawl's fetcher, with the stopping rules both the sitemap check and ACC-8 use: a
    429 stops them, so do 3 blocked answers in a row, and so does the time limit. robots.txt is obeyed."""

    def __init__(self, fetcher: Fetcher, cfg: CrawlConfig, policy, purpose: str) -> None:
        self.fetcher, self.cfg, self.policy, self.purpose = fetcher, cfg, policy, purpose
        self.stopped_because: str | None = None
        self._blocked = 0

    def ask(self, url: str) -> dict[str, Any] | None:
        """The row, or None when nothing was sent (`stopped_because` then says why)."""
        if self.stopped_because:
            return None
        if self.fetcher.deadline_mono is not None and time.monotonic() >= self.fetcher.deadline_mono:
            self.stopped_because = "time_limit"
            return None
        row = light_request(self.fetcher, url, self.purpose, self.cfg)
        if row["error"] == "audit_deadline_skipped":
            self.stopped_because = "time_limit"
            return None
        if row["fetch_class"] == FetchClass.RATE_LIMITED.value:
            self.stopped_because = "rate_limit"
        elif row["fetch_class"] == FetchClass.BLOCKED.value:
            self._blocked += 1
            if self._blocked >= BLOCKED_IN_A_ROW:
                self.stopped_because = "blocked"
        else:
            self._blocked = 0
        return row


def check_sitemap_urls(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig) -> SitemapCheck:
    """IDX-5 (DECISIONS 206): every sitemap URL, not only those the crawl read. A URL the crawl read is judged from the
    crawl (no request); a file (a nested sitemap, an image, a PDF) is left out; a URL robots.txt disallows is counted
    as disallowed and not asked; every other one is asked once with `light_request`, at most `sitemap_check_max`, a
    sample spread over the site's sections when there are more."""
    policy = result.robots_policy_by_origin.get(result.origin)
    check = SitemapCheck(cap=max(0, cfg.sitemap_check_max), listed=len(result.sitemap_urls))
    read = {p.url for p in result.pages}
    wanted: list[str] = []
    for url in result.sitemap_urls:
        if non_page_kind(url):
            check.files += 1
        elif url in read:
            check.read_by_crawl += 1
        elif policy is not None and not policy.decide(cfg.product_token, url).allowed:
            check.disallowed.append(url)
        else:
            wanted.append(url)
    check.wanted = len(wanted)
    why_none = ("single_page" if cfg.single_page else "off" if check.cap == 0
                else "crawl_stopped" if result.stop_reason in _NO_MORE_REQUESTS
                else "robots_unreadable" if policy is None or policy.stops_requests else None)
    if why_none:
        if wanted:
            check.not_checked[why_none] = len(wanted)
            check.not_checked_sample = [{"url": u, "reason": NOT_CHECKED_REASONS[why_none]} for u in wanted[:20]]
        return check
    asked = section_sample(wanted, check.cap) if len(wanted) > check.cap else wanted
    check.sampled = len(asked) < len(wanted)
    requests = LightRequests(fetcher, cfg, policy, "sitemap_check")
    for url in asked:
        row = requests.ask(url)
        if row is None:
            break
        check.rows.append(row)
        if requests.stopped_because:
            break
    check.stopped_because = requests.stopped_because
    unsent = asked[len(check.rows):]
    chosen = set(asked)
    capped = [u for u in wanted if u not in chosen]
    if unsent:
        check.not_checked[check.stopped_because or "time_limit"] = len(unsent)
    if capped:
        check.not_checked["cap"] = len(capped)
    check.not_checked_sample = ([{"url": u, "reason": NOT_CHECKED_REASONS[check.stopped_because or "time_limit"]} for u in unsent]
                                + [{"url": u, "reason": NOT_CHECKED_REASONS["cap"]} for u in capped])[:20]
    if check.stopped_because == "time_limit":
        check.reason = "overall audit deadline reached during the sitemap check; the URLs not asked are reported as not checked"
    return check


# -- IDX-5: sitemap addresses written wrongly (DECISIONS 206, LG-79); no request ---------------------------------------

# The Turkish letters a "?" most often stands for when a sitemap was written in another encoding than UTF-8.
TURKISH_LETTERS = ("ç", "ğ", "ı", "ö", "ş", "ü")
_PIECES = re.compile(r"[/\-_.\s=&#]+")
_WORDS = re.compile(r"\w+")
MAX_GUESSED_MARKS = 3  # a piece with more "?" than this is not guessed (6^3 = 216 spellings at most)


def malformed(url: str) -> str | None:
    """Address diagnostics, not a corruption verdict. `question_mark` denotes valid word-like query syntax with
    unknown intended text; `space`/`invalid_encoding` identify observable invalid characters. No lost letters inferred."""
    if '\ufffd' in url or re.search(r'%(?![0-9A-Fa-f]{2})', url):
        return 'invalid_encoding'
    if " " in url:
        return "space"
    query = urlsplit(url).query
    if query and "=" not in query and "&" not in query and ("-" in query or "?" in query) \
            and all(ch.isalnum() or ch in "-?" for ch in query):
        return "question_mark"
    return None


def not_percent_encoded(url: str) -> bool:
    """Whether the path or query holds a letter outside ASCII written as it is ("/ürünler"), not percent-encoded."""
    parts = urlsplit(url)
    return any(ord(ch) > 127 and ch.isalpha() for ch in parts.path + parts.query)


def page_words(result: CrawlResult) -> set[str]:
    """Every word of the visible text of the pages read, in lower case."""
    words: set[str] = set()
    for page in result.pages:
        text = (page.analysis or {}).get("_visible_text") or ""
        words.update(_WORDS.findall(text.replace("İ", "i").replace("I", "ı").lower()))
    return words


def guess_words(url: str, words: set[str]) -> list[dict[str, str]]:
    """For each piece of the address that holds a "?", the word of the pages read it most likely is, with each "?"
    put back as one of ç, ğ, ı, ö, ş, ü: [{"fragment": "?deme", "word": "ödeme"}]. A piece with no such word is left out."""
    parts = urlsplit(url)
    out = []
    for piece in _PIECES.split(f"{parts.path}?{parts.query}" if parts.query else parts.path):
        marks = piece.count("?")
        if not marks or marks > MAX_GUESSED_MARKS or not piece.replace("?", ""):
            continue
        spellings = [""]
        for ch in piece.lower():
            spellings = [s + letter for s in spellings for letter in (TURKISH_LETTERS if ch == "?" else (ch,))]
        found = next((w for w in spellings if w in words), None)
        if found:
            out.append({"fragment": piece, "word": found})
    return out


def link_header_canonicals(link_header: str | None, base: str) -> list[str]:
    """Targets of `Link: <url>; rel="canonical"` entries."""
    out = []
    for part in (link_header or "").split(","):
        if "<" not in part or ">" not in part:
            continue
        target = part[part.index("<") + 1: part.index(">")]
        params = part[part.index(">") + 1:].lower().replace(" ", "")
        if 'rel="canonical"' in params or "rel=canonical" in params:
            url = normalize_url(target, base)
            if url:
                out.append(url)
    return out


def effective_canonical(page) -> tuple[str | None, list[str], list[str]]:
    html = [u for u in (normalize_url(h, page.url) for h in (page.analysis or {}).get("canonicals", [])) if u]
    header = link_header_canonicals(page.headers.get("link"), page.url)
    chosen = html[0] if html else (header[0] if header else None)
    return chosen, html, header


def canonical_variant(canonical: str | None, url: str) -> dict[str, str] | None:
    """{"counterpart", "differs_in"} when `canonical` is on the http:// or www variant of `url`'s own host (review B02):
    the same address written with the other scheme and/or with or without "www.". `counterpart` is that address on
    `url`'s own scheme and host, which is what the canonical is judged as. None for anything else."""
    if not canonical:
        return None
    try:
        a, b = urlsplit(canonical), urlsplit(url)
    except ValueError:
        return None
    host_a, host_b = (a.hostname or "").lower(), (b.hostname or "").lower()
    if not host_a or (a.scheme, host_a, a.port) == (b.scheme, host_b, b.port):
        return None
    # Normalized addresses carry no default port, so an explicit port that differs is another server, not a variant.
    if host_a.removeprefix("www.") != host_b.removeprefix("www.") or a.scheme not in ("http", "https") or a.port != b.port:
        return None
    differs = [part for part, differ in (("scheme", a.scheme != b.scheme), ("www", host_a != host_b)) if differ]
    counterpart = b._replace(path=a.path or "/", query=a.query, fragment="").geturl()
    return {"counterpart": normalize_url(counterpart) or counterpart, "differs_in": " and ".join(differs)}


def canonical_target(page) -> str | None:
    """The page's chosen canonical as it is judged: a canonical on the http:// or www variant of the page's own host
    counts as the same address on the page's scheme and host (review B02), so a page whose canonical is its own http://
    address is self-canonical."""
    chosen, _, _ = effective_canonical(page)
    variant = canonical_variant(chosen, page.url)
    return variant["counterpart"] if variant else chosen


def canonical_elsewhere(page) -> bool:
    """True when the page's chosen canonical points at another address (its scheme or www variant does not count)."""
    target = canonical_target(page)
    return bool(target) and target != page.url


def cloudflare_machinery(url: str) -> bool:
    """An address under Cloudflare's own /cdn-cgi/ (review H09): not a page of the site."""
    from .config import CLOUDFLARE_PATH_SEGMENT
    try:
        path = urlsplit(url).path
    except ValueError:
        return False
    return path.strip("/").split("/", 1)[0].lower() == CLOUDFLARE_PATH_SEGMENT


def edge_machinery(url: str) -> str | None:
    """The CDN or edge platform whose own machinery an address is under (config.EDGE_MACHINERY_SEGMENTS: Cloudflare's
    /cdn-cgi/, Akamai's /akam/, Vercel's /_vercel/, Netlify's /.netlify/, Imperva's /_Incapsula_Resource), or None.
    Such an address is not a page of the site (review H09, G06, G27)."""
    from .config import EDGE_MACHINERY_SEGMENTS
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    return EDGE_MACHINERY_SEGMENTS.get(path.strip("/").split("/", 1)[0].lower())


_CF_HIDDEN = re.compile(r"\[email(?:\s|\xa0)protected\]", re.I)


def cloudflare_email_pages(result: CrawlResult) -> list[dict[str, Any]]:
    """Pages where Cloudflare's e-mail obfuscation replaced an address (review H09): a link to /cdn-cgi/l/email-protection,
    or the text "[email protected]" Cloudflare writes in the address's place. [{"url", "signals"}]."""
    from .config import CLOUDFLARE_EMAIL_PATH
    rows = []
    for page in result.pages:
        signals = []
        if any(urlsplit(edge["target"]).path.lower().startswith(CLOUDFLARE_EMAIL_PATH) for edge in page.outlinks):
            signals.append("link to the e-mail protection page")
        if _CF_HIDDEN.search((page.analysis or {}).get("_visible_text") or ""):
            signals.append("“[email protected]” in the visible text")
        if signals:
            rows.append({"url": page.url, "signals": signals})
    return rows


def _segments(url: str) -> list[str]:
    from urllib.parse import unquote
    from .analysis import fold_text
    return [fold_text(unquote(part)) for part in urlsplit(url).path.split("/") if part]


_COPY_SUFFIX = re.compile(r"^(?P<stem>.+?)-\d+$")
_TITLE_PARTS = re.compile(r"\s+[|\u2013\u2014\-\u00b7:]\s+|\s*[|\u2013\u2014\u00b7]\s*")


def _fold_label(text: str) -> str:
    """`fold_text`, and accents removed too ("Sin título" -> "sin titulo"): labels compared across languages."""
    import unicodedata
    from .analysis import fold_text
    folded = fold_text(text)
    return "".join(c for c in unicodedata.normalize("NFKD", folded) if not unicodedata.combining(c))


def placeholder_title(title: str | None) -> bool:
    """A title a CMS writes for a page nobody named ("Başlıksız – Mavi Atölye", "Untitled | Shop", "Sans titre"), review
    G02: the title, or one part of it between the separators a site name is added with, is in
    config.DRAFT_PLACEHOLDER_TITLES."""
    from .config import DRAFT_PLACEHOLDER_TITLES
    if not title or not title.strip():
        return False
    parts = [title, *_TITLE_PARTS.split(title)]
    return any(_fold_label(part) in DRAFT_PLACEHOLDER_TITLES for part in parts if part and part.strip())


def _shell_page(analysis: dict) -> bool:
    """The raw HTML is a client-rendered shell: an empty framework mount node (#__next, #app, #root). Its title and text
    are drawn by script, so a missing <title> in it is not a sign of anything (review G02/G03)."""
    return any(m.get("chars") == 0 for m in analysis.get("mount_nodes") or [])


def _own_content(analysis: dict | None) -> str | None:
    """The page's main-content text (header, navigation, footer and aside left out), normalised, or None when it has
    none. Not the raw-HTML hash: every page of a client-rendered site shares one shell (review G03)."""
    from .main_content import content_blocks, norm
    text = norm(" ".join(content_blocks(analysis or {})))
    return text or None


def _draft_word(parts: list[str], words: frozenset) -> str | None:
    """The draft word an address is named by (review G02): a whole path segment ("/test", "/taslak/"), the first word of
    the last segment when draft words are at least half of its words ("/test-marka", "/test-22222"), or its last word
    when that word names nothing but a draft ("/sss-test", seen live). Not a word in the middle of a longer name
    ("/blog/ab-test-nedir"), inside a word ("/latest"), or a content word ending a real name ("/request-demo")."""
    from .config import DRAFT_WORDS_ALSO_CONTENT
    for part in parts:
        if part.replace(" ", "-") in words:
            return part.replace(" ", "-")
    if not parts:
        return None
    named = [w for w in re.split(r"[\W_]+", parts[-1]) if w and not w.isdigit()]
    if not named:
        return None
    if named[0] in words and 2 * sum(w in words for w in named) >= len(named):
        return named[0]
    # Last in the slug only for words that name nothing else ("/sss-test"); "demo", "ornek", "sample" end real names
    # ("/request-demo", "/dilekce-ornek").
    if named[-1] in words and named[-1] not in DRAFT_WORDS_ALSO_CONTENT:
        return named[-1]
    return None


def draft_pages(result: CrawlResult) -> list[dict[str, Any]]:
    """Indexable pages listed in the sitemap that look like drafts or tests left published (review H13, G02, G03):
    [{"url", "signals", "title", "discovered_via"}].

    Every signal needs all three of: something in the address, a page nobody named (no title, or a CMS placeholder
    title such as "Başlıksız" or "Untitled"), and found only through the sitemap. So a titled "/request-demo",
    "/test-drive" or "/sample-recipes" is never one, whatever links reach it.
    - the address is named by a draft word (`_draft_word`, config.DRAFT_PATH_WORDS and DRAFT_PATH_WORDS_OTHER);
    - the last segment is another page's slug with "-<digits>" after it ("/hakkimizda-2" beside "/hakkimizda", "/arjava-2"
      beside "/arjava-3"), and the page's own main content is that page's own main content, not empty.
    A raw page that is a client-rendered shell (an empty mount node and no main-content text) is not judged on its
    missing title; when the audit rendered it, the rendered title is used."""
    from .config import DRAFT_PATH_WORDS, DRAFT_PATH_WORDS_OTHER
    draft_words = DRAFT_PATH_WORDS | DRAFT_PATH_WORDS_OTHER
    listed = set(result.sitemap_urls)
    pages = [p for p in result.pages if p.url in listed and p.status is not None and 200 <= p.status < 300
             and p.fetch_class == FetchClass.OK and p.analysis is not None and not p.analysis.get("empty_response")
             and is_html(p.content_type) and not noindex_directives(p.analysis, p.headers) and not canonical_elsewhere(p)]
    render = getattr(result, "render", None)
    rendered = {u: e for u, e in (getattr(render, "pages", None) or {}).items() if e.get("ok")}
    stems: dict[str, list[str]] = {}
    content: dict[str, str | None] = {}
    for page in result.pages:
        parts = _segments(page.url)
        if parts:
            match = _COPY_SUFFIX.match(parts[-1].replace(" ", "-"))
            for stem in {parts[-1].replace(" ", "-"), *([match["stem"]] if match else [])}:
                stems.setdefault(stem, []).append(page.url)
        content[page.url] = _own_content(page.analysis) if page.analysis else None
    rows = []
    for page in pages:
        title = page.analysis.get("title")
        shown = ((rendered.get(page.url) or {}).get("rendered") or {}).get("title")
        if shown and shown.strip():
            title = shown
        elif _shell_page(page.analysis) and not content.get(page.url):  # a shell with no text of its own
            continue
        untitled = not (title or "").strip()
        placeholder = placeholder_title(title)
        if not (untitled or placeholder) or page.discovered_via != "sitemap":
            continue
        parts = _segments(page.url)
        signals = []
        word = _draft_word(parts, draft_words)
        if word:
            signals.append(f"the address has the word “{word}”")
        match = _COPY_SUFFIX.match(parts[-1].replace(" ", "-")) if parts else None
        own = content.get(page.url)
        if match and own:
            copies = [u for u in stems.get(match["stem"], []) if u != page.url and content.get(u) == own]
            if copies:
                signals.append(f"the address is “{match['stem']}” with a number after it, beside a page of that name "
                               "with the same main content")
        if signals:
            signals.append("no title" if untitled else f"a placeholder title (“{title.strip()[:60]}”)")
            signals.append("found only through the sitemap")
            rows.append({"url": page.url, "signals": signals, "title": page.analysis.get("title"),
                         "discovered_via": page.discovered_via})
    return rows


def _address_key(url: str) -> tuple[str, str, str] | None:
    """(host, folded path without a page extension, query): two addresses of one page share it (review H20)."""
    from .config import PAGE_EXTENSIONS
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    path = parts.path.lower().rstrip("/") or "/"
    for ext in PAGE_EXTENSIONS:
        if path.endswith(ext):
            path = path[: -len(ext)]
            break
    return (parts.netloc.lower(), path, parts.query)


def _address_differences(a: str, b: str) -> list[str]:
    """How two paths of one page differ (review G04): "trailing slash", "file extension", "letter case", in that order."""
    from .config import PAGE_EXTENSIONS
    bare_a, bare_b = a.rstrip("/") or "/", b.rstrip("/") or "/"
    ext_a = next((e for e in PAGE_EXTENSIONS if bare_a.lower().endswith(e)), "")
    ext_b = next((e for e in PAGE_EXTENSIONS if bare_b.lower().endswith(e)), "")
    stem_a, stem_b = bare_a[: len(bare_a) - len(ext_a)], bare_b[: len(bare_b) - len(ext_b)]
    return [label for label, differs in (("trailing slash", (a != bare_a) != (b != bare_b)),
                                         ("file extension", ext_a != ext_b),
                                         ("letter case", stem_a != stem_b)) if differs]


def _points_to(page, other) -> bool:
    """`page` names `other` as its canonical, or redirects to it: the site already says which address is the page."""
    canonical = canonical_target(page) if getattr(page, "headers", None) is not None else None
    return other.url in (canonical, getattr(page, "redirect_location", None))


def address_pairs(pages: list) -> list[dict[str, Any]]:
    """Pages reached at two addresses that differ only by a trailing slash, a file extension (.aspx, .php, .html) or
    letter case, with the same visible text (review H20, G04): [{"urls": [kept, other], "kept", "other", "differs_in"}].
    `differs_in` names every difference ("trailing slash", "file extension", "letter case", joined with " and ").
    `kept` is the address without the extension (else the lower-case one, else the first in order); `other` is the
    second address. A pair where one address names the other as canonical, or redirects to it, is configured already
    and is left out."""
    by_key: dict[tuple, list] = {}
    for page in pages:
        if not (page.analysis and page.analysis.get("text_sha256")):
            continue
        key = _address_key(page.url)
        if key is not None:
            by_key.setdefault(key, []).append(page)
    out = []
    for same in by_key.values():
        if len(same) < 2:
            continue
        first = same[0]
        for other in same[1:]:
            if other.url == first.url or other.analysis["text_sha256"] != first.analysis["text_sha256"]:
                continue
            if _points_to(first, other) or _points_to(other, first):
                continue
            a, b = urlsplit(first.url).path, urlsplit(other.url).path
            differs = _address_differences(a, b)
            if "file extension" in differs:
                first_kept = len(a.rstrip("/")) < len(b.rstrip("/"))
            elif "letter case" in differs:
                first_kept = a == a.lower()
            else:
                first_kept = True
            kept, second = (first, other) if first_kept else (other, first)
            out.append({"urls": [kept.url, second.url], "kept": kept.url, "other": second.url,
                        "differs_in": " and ".join(differs) or "letter case"})
    return out


def _connect_first(addresses: list[str], port: int, timeout: float) -> socket.socket:
    """Connect to the first validated address that answers (a host may list an unreachable one first)."""
    error: OSError | None = None
    for address in addresses:
        try:
            return socket.create_connection((address, port), timeout=timeout)
        except OSError as exc:
            error = exc
    raise error


def inspect_tls(host: str, port: int, timeout: float, ca_bundle: str | None, *, fetcher: Fetcher | None = None) -> dict[str, Any]:
    context = ssl.create_default_context(cafile=ca_bundle or certifi.where())
    evidence: dict[str, Any] = {"host": host, "port": port, "checked_at": utc_now(),
                                "trust_store": "custom test CA" if ca_bundle else "certifi (Mozilla CA bundle)"}
    try:
        url = f"https://{'[' + host + ']' if ':' in host else host}:{port}/"
        if fetcher is not None:
            timeout = fetcher.request_budget(url, timeout)
        else:
            validate_public_target(url)
        addresses = public_addresses(url, allow_loopback=not fetcher.block_loopback if fetcher else True)
        if fetcher is not None:
            timeout = fetcher.request_budget(url, timeout)
        end = time.monotonic() + timeout
        with _connect_first(addresses, port, timeout) as raw:
            if fetcher is not None:
                timeout = min(end - time.monotonic(), fetcher.request_budget(url, timeout))
                if timeout <= 0:
                    raise httpx.TimeoutException("overall audit deadline reached")
                raw.settimeout(timeout)
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                evidence.update(
                    valid=True, protocol=tls.version(), not_after=not_after.isoformat(),
                    days_left=round((not_after - datetime.now(timezone.utc)).total_seconds() / 86400, 1),
                    subject=dict(x[0] for x in cert.get("subject", ())),
                    issuer=dict(x[0] for x in cert.get("issuer", ())),
                    subject_alt_names=[v for _, v in cert.get("subjectAltName", ())],
                )
    except (httpx.TimeoutException, UnsafeTargetError) as exc:
        evidence.update(valid=None, checked=False, error_kind="not_checked", reason=str(exc))
    except ssl.SSLCertVerificationError as exc:
        evidence.update(valid=False, error_kind=VERIFY_CODES.get(exc.verify_code, "verification_failed"),
                        verify_code=exc.verify_code, verify_message=exc.verify_message)
    except ssl.SSLError as exc:
        evidence.update(valid=False, error_kind="handshake_failed", error=str(exc))
    except OSError as exc:
        evidence.update(valid=None, error_kind="connect_failed", error=str(exc))
    return evidence


def www_variant(host: str) -> str | None:
    """www.example.com <-> example.com. None when the host has no meaningful www counterpart."""
    bare = host.lower().removeprefix("www.")
    # *.localhost is loopback (test servers), where the variant is exercised deliberately.
    if not is_loopback_host(bare) and not is_registrable_domain(bare):
        return None
    try:
        ipaddress.ip_address(host.strip("[]"))
        return None
    except ValueError:
        pass
    return host.removeprefix("www.") if host.startswith("www.") else f"www.{host}"


# What http:// on one host does, as IDX-2 says it (decision 188): outcome -> the engine's English line. The web layer
# words the same outcomes through its `detail.http_<outcome>` strings. `redirects_to_https` is the healthy one.
HTTP_REDIRECT_LINES = {
    "served_on_http": "{url} answers {status} without redirecting: the site is also served without encryption",
    "redirects_to_http_served": "{url} redirects to {location}, which answers {status}: still http://",
    "redirects_to_http_then_https": "{url} redirects to {location}, which then redirects to https://: one extra step",
    "redirects_elsewhere": "{url} redirects to {location}, not to https:// (where that leads was not followed)",
    "other_status": "{url} answered {status} without redirecting to https://",
    "redirects_to_https": "{url} redirects to https:// as it should",
}
# The outcomes that mean the site itself is reachable, whole, without encryption: High. The others are Low.
HTTP_SERVED_OUTCOMES = frozenset({"served_on_http", "redirects_to_http_served"})


def _is_2xx(status) -> bool:
    return isinstance(status, int) and 200 <= status < 300


def http_redirect_outcomes(hosts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For every host whose http:// address was tested: {"host", "outcome", "line", "values", ...the probe's own
    fields}. The probe records one hop. Where a host redirects to ANOTHER tested host's http:// address, what that
    address does is read from that host's own entry; any other target was not followed."""
    tested = {entry["host"]: entry.get("http_redirect") or {} for entry in hosts}
    out = []
    for entry in hosts:
        redirect = entry.get("http_redirect") or {}
        if not redirect.get("checked"):
            continue
        url = redirect.get("http_url") or f"http://{entry['host']}/"
        status, location = redirect.get("status"), redirect.get("location")
        values: dict[str, Any] = {"url": url}
        if redirect.get("redirects_to_https"):
            outcome = "redirects_to_https"
        elif _is_2xx(status):
            # Also the start address typed and served on http:// (`reason`: "the audited start URL is served over plain http").
            outcome, values["status"] = "served_on_http", status
        elif isinstance(status, int) and 300 <= status < 400 and location:
            outcome, values["location"] = "redirects_elsewhere", location
            try:
                target = urlsplit(location)
            except ValueError:
                target = None
            other = tested.get((target.hostname or "").lower()) if target is not None and target.scheme == "http" else None
            if (other is not None and (target.hostname or "").lower() != entry["host"] and other.get("checked")
                    and (target.path or "/") == (urlsplit(other.get("http_url") or "").path or "/")):
                if other.get("redirects_to_https"):
                    outcome = "redirects_to_http_then_https"
                elif _is_2xx(other.get("status")):
                    outcome, values["status"] = "redirects_to_http_served", other["status"]
        else:
            outcome, values["status"] = "other_status", status
        out.append({**redirect, "host": entry["host"], "outcome": outcome, "line": HTTP_REDIRECT_LINES[outcome].format(**values)})
    return out


def _check_host(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, host: str, role: str,
                scheme: str, port: int | None) -> dict[str, Any]:
    entry: dict[str, Any] = {"host": host, "role": role}
    loopback = is_loopback_host(host)
    redirect: dict[str, Any] = {"checked_at": utc_now()}
    if scheme == "https":
        entry["tls"] = inspect_tls(host, port or 443, cfg.request_timeout_s, cfg.ca_bundle, fetcher=fetcher)
        http_netloc = host if cfg.http_port in (None, 80) else f"{host}:{cfg.http_port}"
        http_origin = f"http://{http_netloc}"
        # Use the audited path, not "/": a site published under a subdirectory answers 404 at the
        # origin root, which would read as "no redirect to HTTPS" without ever testing a live URL.
        http_url = http_origin + (urlsplit(result.start_url).path or "/")
        redirect["http_url"] = http_url
        if loopback and cfg.http_port is None:
            redirect.update(checked=False, reason="loopback test run without a configured http_port")
        else:
            from .crawler import load_robots  # local import: crawler does not import this module

            if http_origin not in result.robots_policy_by_origin:
                result.robots_policy_by_origin[http_origin] = load_robots(fetcher, http_origin, cfg)
            http_policy = result.robots_policy_by_origin[http_origin]
            decision = http_policy.decide(cfg.product_token, http_url)
            redirect["robots_mode"] = http_policy.mode
            if not decision.allowed:
                redirect.update(checked=False, reason=(f"robots.txt for {http_origin} is unavailable: {decision.reason}" if http_policy.stops_requests else f"robots.txt for {http_origin} disallows it: {decision.reason}"))
            else:
                observed = _observe(fetcher, http_url, "http_redirect_check", cfg)
                location = observed["location"]
                loc = urlsplit(location) if location else None
                to_https = bool(loc and loc.scheme == "https"
                                and (loc.hostname or "").removeprefix("www.") == host.removeprefix("www."))
                is_redirect = bool(observed["status"] and 300 <= observed["status"] < 400)
                redirect.update(checked=observed["error"] is None, status=observed["status"], error=observed["error"],
                                location=location, redirects_to_https=is_redirect and to_https)
    else:
        # The audit was started on http://. What that address answered is already in the crawl: when it redirected
        # to https:// on the same host, the redirect exists, and the http:// in the start address was only how it
        # was typed. Seen live on 2026-10-07: "http://maximum.com/" answered 301 to https:// and was reported as
        # "No HTTP to HTTPS redirect".
        first = next((p for p in result.pages if p.url == normalize_url(result.start_url)), None)
        target = urlsplit(first.redirect_location or "") if first is not None else None
        if (first is not None and first.status is not None and 300 <= first.status < 400 and target.scheme == "https"
                and (target.hostname or "").removeprefix("www.") == host.removeprefix("www.")):
            redirect.update(http_url=result.start_url, checked=True, status=first.status, location=first.redirect_location,
                            redirects_to_https=True, seen_in="the crawl's own request for the start URL")
        else:
            redirect.update(http_url=result.start_url, checked=True, status=first.status if first is not None else None,
                            redirects_to_https=False, reason="the audited start URL is served over plain http")
        if loopback:
            entry["tls"] = {"host": host, "checked": False, "reason": "loopback test run over http; HTTPS not probed"}
        else:
            entry["tls"] = inspect_tls(host, 443, cfg.request_timeout_s, cfg.ca_bundle, fetcher=fetcher)
            redirect["https_available"] = bool(entry["tls"].get("valid"))
    entry["http_redirect"] = redirect
    return entry


def _gsc_inspect(cfg: CrawlConfig, urls: list[str], fetcher: Fetcher) -> dict[str, Any]:
    results = []
    with httpx.Client(timeout=cfg.request_timeout_s, trust_env=False, transport=PublicTransport(allow_loopback=not cfg.block_loopback,
                          verify=tls_verify(cfg.ca_bundle), before_connect=fetcher.remaining_timeout)) as client:
        for url in urls[: cfg.gsc_max_inspections]:
            entry: dict[str, Any] = {"url": url, "requested_at": utc_now()}
            try:
                response = fetcher.api_request(client, "POST",
                    cfg.gsc_endpoint,
                    headers={"Authorization": f"Bearer {cfg.gsc_access_token}"},
                    json={"inspectionUrl": url, "siteUrl": cfg.gsc_site_url, "languageCode": "en-US"},
                )
                entry["http_status"] = response.status_code
                if response.status_code == 200:
                    entry["indexStatusResult"] = response.json().get("inspectionResult", {}).get("indexStatusResult")
                else:
                    entry["error"] = f"API returned HTTP {response.status_code}"
            except (httpx.HTTPError, ValueError) as exc:
                entry["error"] = type(exc).__name__
            results.append(entry)
    return {"endpoint": cfg.gsc_endpoint, "site_url": cfg.gsc_site_url, "language_code": "en-US",
            "token": "redacted", "results": results, "skipped": urls[cfg.gsc_max_inspections:]}


def _bing_url_info(cfg: CrawlConfig, urls: list[str], fetcher: Fetcher) -> dict[str, Any]:
    results = []
    with httpx.Client(timeout=cfg.request_timeout_s, trust_env=False, transport=PublicTransport(allow_loopback=not cfg.block_loopback,
                          verify=tls_verify(cfg.ca_bundle), before_connect=fetcher.remaining_timeout)) as client:
        for url in urls[: cfg.gsc_max_inspections]:
            entry: dict[str, Any] = {"url": url, "requested_at": utc_now()}
            try:
                response = fetcher.api_request(client, "GET", f"{cfg.bing_endpoint}/GetUrlInfo",
                                      params={"siteUrl": cfg.bing_site_url, "url": url, "apikey": cfg.bing_api_key})
                entry["http_status"] = response.status_code
                if response.status_code == 200:
                    body = response.json()
                    entry["url_info"] = body.get("d", body) if isinstance(body, dict) else body
                else:
                    entry["error"] = f"API returned HTTP {response.status_code}"
            except (httpx.HTTPError, ValueError) as exc:
                entry["error"] = f"{type(exc).__name__}"
            results.append(entry)
    return {"endpoint": f"{cfg.bing_endpoint}/GetUrlInfo", "site_url": cfg.bing_site_url, "api_key": "redacted",
            "results": results}


def collect_index_data(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, key_urls: list[str]) -> IndexData:
    data = IndexData()
    origin = result.origin
    policy = result.robots_policy_by_origin[origin]

    # IDX-1: refetch 5xx, transport failures and empty pages (DECISIONS 204) once, after a delay.
    suspects = [p for p in result.pages
                if (p.fetch_class == FetchClass.OK and p.status and p.status >= 500) or p.fetch_class == FetchClass.ERROR
                or (p.analysis or {}).get("empty_response")]
    if suspects and cfg.refetch_delay_s:
        if not fetcher.sleep(cfg.refetch_delay_s):
            return data
    for page in suspects[: cfg.max_refetches]:
        again = _observe(fetcher, page.url, "page_refetch", cfg)
        data.refetches.append({"url": page.url, "first": {"status": page.status, "error": page.error,
                                                          "requested_at": page.requested_at},
                               "refetch": {k: again[k] for k in ("status", "error", "requested_at", "fetch_class",
                                                                 "elapsed_ms", "ttfb_ms", "truncated", "empty_response",
                                                                 "body_bytes", "readable_html")}})

    data.empty_browser_check = empty_browser_check(fetcher, result, cfg, policy, data.refetches, key_urls)

    # IDX-4: fetch same-origin canonical targets the crawl did not fetch (following redirects).
    fetched = {p.url: p for p in result.pages}
    for page in result.pages:
        if not (page.content_checks_eligible and page.analysis):
            continue
        # A canonical on the http:// or www variant is judged as the same address on the audited host (review B02).
        target = canonical_target(page)
        hops = 0
        while (target and target != page.url and same_origin(target, origin) and target not in fetched
               and target not in data.canonical_targets and len(data.canonical_targets) < cfg.max_canonical_fetches):
            if not policy.decide(cfg.product_token, target).allowed:
                data.canonical_targets[target] = {"url": target, "skipped": "robots.txt disallows Maya's user agent"}
                break
            observed = _observe(fetcher, target, "canonical_target", cfg)
            data.canonical_targets[target] = observed
            target = observed["location"] if observed["status"] and 300 <= observed["status"] < 400 else None
            hops += 1
            if hops > 5:
                break

    # IDX-3: walk every looping URL, and the homepage, again before anything is said about a loop.
    data.redirect_rechecks = recheck_redirects(fetcher, result, cfg, policy)
    # IDX-6: a link to another site at one of this site's own paths is asked once whether it leads anywhere.
    data.other_site_targets = check_other_site_targets(fetcher, result, cfg)

    data.soft_404 = soft_404_probe(fetcher, result, cfg, policy)

    # IDX-2: certificate and HTTP -> HTTPS redirect, for the start host and its www / non-www variant.
    parts = urlsplit(result.start_url)
    host = parts.hostname or ""
    data.hosts = [_check_host(fetcher, result, cfg, host, "start", parts.scheme, parts.port)]
    variant = www_variant(host)
    if variant is None:
        data.variant_note = (
            "no www variant: the start host is an IP address" if not host or host[0].isdigit() or ":" in host
            else f"no www variant checked: {host} is not a registrable domain (it is a subdomain, or a host on "
                 f"a shared hosting domain), so www.{host} is not an address this site is reached by")
    elif parts.scheme != "https":
        data.variant_note = "www variant not checked: the start URL is served over plain http"
    elif not host_allowed(f"https://{variant}/", cfg.allowed_live_hosts):
        data.variant_note = f"www variant {variant} not checked: host not allowed"
    else:
        from . import resolver
        try:
            resolver.resolve(variant, parts.port or 443)
        except resolver.LookupFailed as exc:
            data.variant_note = (f"www variant {variant} does not resolve ({exc.detail}); nothing to check" if exc.kind == "not_found" or (exc.kind == "unresolved" and any(
                                     a.get("method") == "system" and a.get("outcome") == "not_found" for a in exc.attempts))
                                 else f"www variant {variant} not checked: network problem on this computer ({exc.detail})")
        else:
            data.hosts.append(_check_host(fetcher, result, cfg, variant, "variant", "https", parts.port))

    # IDX-9 / IDX-10 (T2): owner-connected APIs, key pages only.
    if cfg.gsc_access_token and cfg.gsc_site_url and key_urls:
        data.gsc = _gsc_inspect(cfg, key_urls, fetcher)
    if cfg.bing_api_key and cfg.bing_site_url and key_urls:
        endpoint_host = urlsplit(cfg.bing_endpoint).hostname or ""
        if is_loopback_host(endpoint_host) or cfg.bing_api_verified:
            data.bing = _bing_url_info(cfg, key_urls, fetcher)
        else:
            data.bing_skipped = (
                "launch-gated: the Bing Webmaster JSON endpoint path and response shape are not verified against "
                "Microsoft's documentation (their published example is XML). Calls to the real API stay disabled "
                "until someone confirms them and sets bing_api_verified in code."
            )
    if cfg.indexnow_key:
        location = cfg.indexnow_key_location or f"{origin}/{cfg.indexnow_key}.txt"
        location = normalize_url(location, origin) or location
        entry: dict[str, Any] = {"key_location": location, "key": "redacted"}
        if not same_origin(location, origin):
            entry.update(checked=False, reason="key location is on another origin; not fetched")
        elif not policy.decide(cfg.product_token, location).allowed:
            entry.update(checked=False, reason="robots.txt disallows the key location for Maya's user agent")
        else:
            response = fetcher.get(location, "indexnow_key", 4096)
            entry.update(checked=True, status=response.status, error=response.error,
                         key_matches=response.status == 200 and cfg.indexnow_key in response.body.decode("utf-8", "replace"))
        data.indexnow = entry
    return data
