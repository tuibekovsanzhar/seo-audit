"""INT-1 to INT-4: audit integrity gates (spec §5 INT).

Gates run before any other check and carry no severity. Each returns the raw
evidence behind its state, so a reader can reproduce it (spec §1).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from ..classify import describe_blockers, identify_blocker
from ..config import EMPTY_BROWSER_CHECK_URLS, CrawlConfig
from ..directives import noindex_directives
from ..fetcher import gaps_by_host
from ..html_links import is_html
from ..index_data import EMPTY_CHECK_PURPOSE
from ..models import Confidence, CrawlResult, FetchClass, GateResult, PageFetch, StopReason
from ..probes import BROWSER_USER_AGENT, UA_CHECK_BOT, UA_CHECK_PURPOSE
from ..registry import entry
from ..render import WEBSOCKET_BLOCKING_UNAVAILABLE
from ..urls import detect_templates, normalize_url, origin_of

SAMPLE = 25
IMPAIRED = (FetchClass.BLOCKED, FetchClass.RATE_LIMITED)
# Checks that are only valid on a complete crawl (spec INT-2, IDX-7).
GATED_ON_COMPLETE_CRAWL = [
    "IDX-7 orphan pages (Not assessed unless the crawl is complete)",
    "Any sitewide count (reported as a lower bound unless the crawl is complete)",
]


def _ratio(n: int, d: int) -> str:
    return f"{n}/{d} ({(100 * n / d):.1f}%)" if d else "0/0"


def _page_evidence(page: PageFetch) -> dict:
    return {
        "url": page.url,
        "status": page.status,
        "error": page.error,
        "fetch_class": page.fetch_class.value,
        "confidence": page.classification_confidence.value,
        "evidence": page.classification_evidence,
        "headers": page.headers,
        "requested_at": page.requested_at,
        "reproduce": page.reproduce(),
    }


def int1_fetch_classification(result: CrawlResult, cfg: CrawlConfig) -> GateResult:
    title = "Fetch classification per page"
    pages = result.pages
    if not pages:
        return GateResult(
            "INT-1", title, "not_assessed", Confidence.NOT_ASSESSED,
            "No pages were fetched, so there is nothing to classify.",
            {"stop_reason": result.stop_reason.value, "stop_detail": result.stop_detail},
        )

    by_class = Counter(p.fetch_class.value for p in pages)
    impaired = [p for p in pages if p.fetch_class in IMPAIRED]
    verified_impaired = [p for p in impaired if p.classification_confidence == Confidence.VERIFIED]
    errors = [p for p in pages if p.fetch_class == FetchClass.ERROR]
    empty = [p for p in pages if (p.analysis or {}).get("empty_response")]
    start = next((p for p in pages if p.discovered_via == "start"), None)

    share = len(impaired) / len(pages)
    verified_share = len(verified_impaired) / len(pages)
    start_impaired = start is not None and start.fetch_class in IMPAIRED
    start_impaired_verified = start_impaired and start.classification_confidence == Confidence.VERIFIED

    reasons = []
    if share >= cfg.degraded_threshold:
        reasons.append(
            f"{_ratio(len(impaired), len(pages))} of fetched pages were blocked or rate-limited, "
            f"at or above the {cfg.degraded_threshold:.0%} threshold"
        )
    if start_impaired:
        reasons.append(f"the start URL was {start.fetch_class.value}")
    degraded = bool(reasons)
    # The gate is Verified only if it would reach the same state using Verified
    # classifications alone; otherwise it rests on an estimate (spec §2.2).
    degraded_on_verified = verified_share >= cfg.degraded_threshold or start_impaired_verified
    confidence = Confidence.VERIFIED if (not degraded or degraded_on_verified) else Confidence.ESTIMATED

    if degraded:
        summary = "Audit degraded: " + "; ".join(reasons) + "."
        if confidence == Confidence.ESTIMATED:
            summary += (
                f" Only {_ratio(len(verified_impaired), len(pages))} rest on Verified classifications, "
                "so this result is an estimate."
            )
    elif impaired:
        summary = (
            f"{_ratio(len(impaired), len(pages))} of fetched pages were blocked or rate-limited, "
            f"below the {cfg.degraded_threshold:.0%} threshold; the audit is not degraded."
        )
    elif empty:
        # "All pages" is not said of pages that sent nothing (DECISIONS 204, FA-023): they are the site's own answers,
        # and IDX-1 reports them.
        summary = (f"{len(pages)} fetched pages were answered by the site itself, none blocked or rate-limited; "
                   f"{len(empty)} of them were empty (status 200 with under {cfg.empty_response_max_bytes} bytes; see IDX-1).")
    else:
        summary = f"All {len(pages)} fetched pages returned the server's own response; none were blocked or rate-limited."
    if errors:
        summary += f" {len(errors)} page(s) failed at the transport level."

    how_to_fix = None
    if impaired:
        how_to_fix = (
            f'Maya\'s crawler (user agent "{result.user_agent}") was blocked or rate-limited on '
            f"{len(impaired)} page(s). If you own this site, allowlist that user agent in your WAF, "
            "bot-protection, and rate-limiting rules, then re-run the audit. Content checks do not "
            "run on those pages, so no finding describes them."
        )

    return GateResult(
        "INT-1", title, "degraded" if degraded else "ok", confidence, summary,
        {
            "pages_fetched": len(pages),
            "by_fetch_class": dict(by_class),
            "blocked_or_rate_limited": _ratio(len(impaired), len(pages)),
            "blocked_or_rate_limited_verified_only": _ratio(len(verified_impaired), len(pages)),
            "degraded_threshold": f"{cfg.degraded_threshold:.0%} (policy)",
            "start_url": _page_evidence(start) if start else None,
            "impaired_pages": [_page_evidence(p) for p in impaired[:SAMPLE]],
            "transport_error_pages": [_page_evidence(p) for p in errors[:SAMPLE]],
            "content_checks_suppressed_on": sum(1 for p in pages if not p.content_checks_eligible),
            # Answers with status 2xx that sent nothing (IDX-1, DECISIONS 204): the site's own, so not impaired.
            "empty_responses": {"count": len(empty), "limit_bytes": cfg.empty_response_max_bytes,
                                "urls": [p.url for p in empty[:SAMPLE]]},
            # Who answered instead of the site on the impaired pages, where the response says (ACC-9 reports it).
            "blocked_by": describe_blockers([b for b in (identify_blocker(
                p.status, p.headers, p.classification_evidence, p.fetch_class.value) for p in impaired) if b]),
        },
        how_to_fix,
    )


def int2_crawl_completeness(result: CrawlResult, cfg: CrawlConfig) -> GateResult:
    title = "Crawl completeness"
    pages = result.pages
    unreadable = [p for p in pages if p.fetch_class != FetchClass.OK]
    # A 200 that sent nothing has no links to follow either (review B16): pages linked only from it may look orphaned.
    empty = [p for p in pages if p.fetch_class == FetchClass.OK and (p.analysis or {}).get("empty_response")]
    redirects = [p for p in pages if p.status is not None and 300 <= p.status < 400]
    skipped_pages = [s for s in result.skipped_robots if s.discovered_via != "sitemap_document"]
    fetched_urls = {p.url for p in pages}
    sitemap_fetched = [u for u in result.sitemap_urls if u in fetched_urls]
    sitemap_only = [p.url for p in pages if p.discovered_via == "sitemap"]

    rows = [r for r in (getattr(result, "sessions", None) or []) if r.get("finished_at")]
    reasons = []
    if len(rows) > 1:
        # The pages in a resumed crawl were not seen at one moment. Anything comparing two pages —
        # duplicate detection, canonical targets, date conflicts — is comparing across that gap, and
        # a reader deciding how much to trust this crawl needs to know before the findings, not after.
        first, last = rows[0].get("started_at"), rows[-1].get("started_at")
        reasons.append(f"assembled from {len(rows)} sessions between {first} and {last}; pages were not "
                       "all seen at the same moment")
    if result.stop_reason != StopReason.EXHAUSTED:
        reasons.append(f"stopped early ({result.stop_reason.value}): {result.stop_detail}")
    if unreadable:
        reasons.append(f"{len(unreadable)} page(s) could not be read, so links on them were not followed")
    if empty:
        reasons.append(f"{len(empty)} page(s) answered with an empty page, so links on them could not be read")
    complete = not reasons

    caveats = list(result.sitemap_notes)
    if skipped_pages:
        caveats.append(
            f"{len(skipped_pages)} URL(s) were skipped because robots.txt disallows them for Maya's user "
            "agent; links on those pages were not followed, so pages linked only from them may look orphaned."
        )

    discovery = getattr(result, "render_discovery", None) or {}
    if discovery.get("used"):
        caveats.append(
            f"Link discovery used rendering: {discovery['links_added']} link(s) on {sum(1 for row in discovery['pages'] if row.get('used'))} "
            "page(s) exist only after JavaScript runs and were followed. Only the homepage and key pages were rendered "
            "for links, so pages linked only from the rendered view of other pages may be missing from this crawl.")

    if complete:
        summary = f"Complete: every discovered URL was fetched or skipped ({len(pages)} page fetches)."
    else:
        summary = "Incomplete: " + "; ".join(reasons) + "."

    fixes = {
        StopReason.PAGE_CAP: f"Raise the page cap (currently {cfg.max_pages}) to crawl the rest of the site.",
        StopReason.TIME_LIMIT: f"Raise the time limit (currently {cfg.time_limit_s}s) to crawl the rest of the site.",
        StopReason.RATE_LIMIT: "The site rate-limited Maya. See INT-1 for the allowlist fix, then re-run.",
        StopReason.ROBOTS_DISALLOWED: "robots.txt does not allow Maya's user agent to crawl. See INT-4 for the rule.",
        StopReason.NETWORK: "No answer from the site reached this computer, so nothing was crawled directly. This is not a finding "
                            "about the site. Check this computer's connection (VPN, iCloud Private Relay, Wi-Fi) and run the audit again.",
        StopReason.STOPPED: "The audit was stopped on request. Resume it to crawl the rest of the site.",
        StopReason.ERROR: "The start URL could not be fetched. Check the URL, DNS, and TLS, then re-run.",
    }
    how_to_fix = fixes.get(result.stop_reason)
    if how_to_fix is None and unreadable:
        how_to_fix = "Resolve the blocked, rate-limited, or failed pages listed in INT-1, then re-run."
    elif how_to_fix is None and empty:
        how_to_fix = "Find out why the empty pages listed under IDX-1 send nothing, then re-run."

    return GateResult(
        "INT-2", title, "complete" if complete else "incomplete", Confidence.VERIFIED, summary,
        {
            "stop_reason": result.stop_reason.value,
            "stop_detail": result.stop_detail,
            "limits": {"max_pages": cfg.max_pages, "time_limit_s": cfg.time_limit_s},
            "elapsed_s": result.elapsed_s,
            "sessions": len(rows) or 1,
            "session_windows": [{"session_no": r["session_no"], "started_at": r.get("started_at"),
                                 "finished_at": r.get("finished_at")} for r in rows] if len(rows) > 1 else None,
            "urls_discovered": len(result.discovered_urls),
            "page_fetches": len(pages),
            "pages_counted_toward_cap": len(pages) - len(redirects),
            "redirect_responses": len(redirects),
            "unreadable_pages": [{"url": p.url, "fetch_class": p.fetch_class.value, "status": p.status, "error": p.error} for p in unreadable[:SAMPLE]],
            "empty_pages": {"count": len(empty), "urls": [p.url for p in empty[:SAMPLE]]},
            "skipped_by_robots": len(skipped_pages),
            "not_fetched": {"count": len(result.not_fetched_urls), "sample": result.not_fetched_urls[:SAMPLE]},
            "sitemaps": [
                {"url": d.url, "status": d.status, "kind": d.kind, "urls_found": d.urls_found, "error": d.error}
                for d in result.sitemap_docs
            ],
            "sitemap_urls_listed": len(result.sitemap_urls),
            "sitemap_urls_fetched": len(sitemap_fetched),
            "sitemap_discovery_notes": result.sitemap_notes,
            "fetched_only_via_sitemap": sitemap_only[:SAMPLE],
            "caveats": caveats,
            "checks_gated_until_complete": GATED_ON_COMPLETE_CRAWL,
        },
        how_to_fix,
    )


def int3_rendering_disclosure(result: CrawlResult, cfg: CrawlConfig) -> GateResult:
    title = "Rendering mode disclosure"
    render = getattr(result, "render", None)
    html_ok = [
        p.url for p in result.pages
        if p.fetch_class == FetchClass.OK and p.status is not None and 200 <= p.status < 300 and is_html(p.content_type)
    ]
    # Pages the site marks noindex are deliberately not rendered (they cannot be cited), so they are
    # disclosed separately rather than counted as templates the render budget could not reach.
    noindexed = {p.url for p in result.pages
                 if p.analysis is not None and noindex_directives(p.analysis, p.headers)}
    templates = detect_templates([u for u in html_ok if u not in noindexed])
    rendered = render.pages if render else {}
    rendered_ok = {u for u, e in rendered.items() if e.get("ok")}
    by_url = {p.url: p for p in result.pages}
    key_pages = []
    for raw in cfg.key_pages:
        url = normalize_url(raw, result.origin)
        page = by_url.get(url) if url else None
        key_pages.append({"url": url or raw, "fetched": page is not None,
                          "fetch_class": page.fetch_class.value if page else None, "rendered": url in rendered_ok})
    templates_not_rendered = [
        {"template": t, "pages": len(urls), "sample_url": urls[0], "rendered": False}
        for t, urls in sorted(templates.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if not any(u in rendered_ok for u in urls)
    ]
    mode = render.mode if render else "raw_html_only"
    reason = (render.reason if render else "rendering was not requested for this run (crawl only)")
    skipped_by_type = {u: dict(Counter(r["skipped_type"] for r in e.get("requests", []) if r.get("skipped_type")))
                       for u, e in rendered.items()}
    websocket_blocking = (WEBSOCKET_BLOCKING_UNAVAILABLE
                          if any(e.get("websocket_blocking") == "unavailable" for e in rendered.values()) else None)
    if mode == "raw_plus_sampled_render":
        failed = [u for u, e in rendered.items() if not e.get("ok")]
        summary = (
            f"Raw HTML for every page, plus a rendered view (JavaScript executed) for {len(rendered_ok)} of "
            f"{cfg.render_budget} render slots. Not rendered: {len(templates_not_rendered)} template(s), "
            f"{sum(1 for k in key_pages if not k['rendered'])} key page(s)."
        )
        if noindexed:
            summary += (f" {len(noindexed)} page(s) marked noindex were not rendered: they cannot be cited, so "
                        "RND does not report content gaps on them (ACC-3 reports the directive).")
        if failed:
            summary += f" {len(failed)} render(s) failed."
        timed_out = [u for u, e in rendered.items() if e.get("ok") and e.get("navigation_timed_out")]
        if timed_out:
            summary += (f" {len(timed_out)} page(s) had not finished loading within the render timeout; the DOM was "
                        "read as it stood, so those rendered views may be partial.")
        unsettled = [u for u, e in rendered.items() if e.get("ok") and e.get("network_idle") is False]
        if unsettled:
            summary += (f" On {len(unsettled)} page(s) the network had not gone idle when the DOM was read, so a "
                        "late-loading part of those pages may be missing from the rendered view.")
        skipped_total = sum(sum(counts.values()) for counts in skipped_by_type.values())
        if skipped_total:
            summary += (f" {skipped_total} image, media and font request(s) were not fetched while rendering: they "
                        "are not needed to read a page's text, and the rendered views are not screenshots.")
        if websocket_blocking:
            summary += " " + websocket_blocking
        if not cfg.render_third_party:
            summary += " Resources on other origins were not loaded while rendering, so a site whose scripts live on a CDN may look less rendered than it is."
    else:
        summary = (
            f"Every observation in this audit describes the raw HTML response. Rendering did not run ({reason}), "
            f"so {len(templates)} template(s) and {len(key_pages)} key page(s) were not rendered. Engines that execute "
            "JavaScript (e.g. Google) may see more than this audit shows."
        )
    return GateResult(
        "INT-3", title, "disclosure", Confidence.VERIFIED, summary,
        {
            "rendering_mode": mode,
            "reason": reason,
            "browser": render.browser if render else None,
            "view_of_every_observation": "raw, unless a finding says it compares the rendered view",
            "render_budget": cfg.render_budget,
            "render_order": render.order if render else [],
            "rendered_pages": [{"url": u, "ok": e.get("ok"), "status": e.get("status"), "error": e.get("error"),
                                "network_idle": e.get("network_idle"),
                                "websocket_blocking": e.get("websocket_blocking"),
                                "navigation_timed_out": e.get("navigation_timed_out"),
                                "requests_allowed": sum(1 for r in e.get("requests", []) if r["action"] == "allowed"),
                                "requests_aborted": sum(1 for r in e.get("requests", []) if r["action"] == "aborted"),
                                "requests_skipped_by_type": skipped_by_type[u]}
                               for u, e in rendered.items()],
            "third_party_resources_loaded": bool(render and render.third_party_loaded),
            "websocket_blocking": websocket_blocking,
            "templates_not_rendered": templates_not_rendered,
            "noindexed_not_rendered": sorted(noindexed)[:40],
            "template_grouping_confidence": Confidence.ESTIMATED.value,
            "key_pages": key_pages,
            "auto_suggested_key_pages": "not implemented in this build",
        },
    )


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


PROBE_HEADER = ("X-Maya-Probe", "ua-differential")


def int4_crawler_identity(result: CrawlResult, cfg: CrawlConfig) -> GateResult:
    title = "Maya crawler identity and robots.txt compliance"
    requests = result.requests
    policies = result.robots_policy_by_origin
    own = [r for r in requests if r.purpose not in ("probe", UA_CHECK_PURPOSE, EMPTY_CHECK_PURPOSE)]
    # IDX-1's browser re-ask of pages empty to Maya (first review C1/C2): browser user agent, tagged, capped.
    empty_checks = [r for r in requests if r.purpose == EMPTY_CHECK_PURPOSE]
    probes = [r for r in requests if r.purpose == "probe"]
    # ACC-4 without ownership (DECISIONS 205): a browser and Googlebot's user agent, tagged, once each per URL.
    ua_checks = [r for r in requests if r.purpose == UA_CHECK_PURPOSE]
    agents = sorted({r.user_agent for r in own})

    robots_seq: dict[str, int] = {}
    for r in requests:
        if r.purpose == "robots":
            robots_seq.setdefault(origin_of(r.url), r.seq)

    disallowed_requests, out_of_order = [], []
    for r in requests:
        if r.purpose == "robots":
            continue
        origin = origin_of(r.url)
        policy = policies.get(origin)
        if r.purpose == "render_subresource" and cfg.render_third_party and origin != result.origin and policy is None:
            continue  # third-party assets loaded by the browser only when explicitly enabled (disclosed in INT-3)
        if policy is None or robots_seq.get(origin, 10**9) > r.seq:
            out_of_order.append({"seq": r.seq, "url": r.url, "purpose": r.purpose})
            continue
        decision = policy.decide(cfg.product_token, r.url)
        if not decision.allowed:
            disallowed_requests.append({"seq": r.seq, "url": r.url, "purpose": r.purpose, "decision": decision.to_dict()})

    # Probes (spec §8 Q1): only on ownership-verified sites, tagged, and capped.
    # Ownership is re-derived here from the raw homepage meta tags rather than
    # trusting the collection step's flag, so a bug there cannot hide a probe.
    ownership_verified = bool(cfg.site_verification_token) and any(
        page.depth == 0 and page.analysis is not None
        and cfg.site_verification_token in page.analysis["verification_tokens"]
        for page in result.pages
    )
    if not ownership_verified and cfg.site_verification_token and cfg.site_verification_dns:
        # The DNS method leaves nothing on a page to re-derive from. The record found is kept in the access data, and
        # must be exactly the record this token makes.
        from ..ownership import txt_record

        recorded = getattr(getattr(result, "access", None), "ownership", None) or {}
        ownership_verified = (recorded.get("verified") is True and recorded.get("method") == "dns_txt"
                              and recorded.get("record") == txt_record(cfg.site_verification_token))
    untagged = [r.seq for r in probes if r.extra_headers.get(PROBE_HEADER[0]) != PROBE_HEADER[1]]
    probe_problems = []
    if probes and not ownership_verified:
        probe_problems.append(f"{len(probes)} probe request(s) were sent to a site whose ownership is not verified")
    if untagged:
        probe_problems.append(f"{len(untagged)} probe request(s) lacked the {PROBE_HEADER[0]} header")
    if len(probes) > cfg.max_probe_requests:
        probe_problems.append(f"{len(probes)} probe requests exceeded the cap of {cfg.max_probe_requests}")
    googlebot = entry(UA_CHECK_BOT).probe_user_agent
    if len(ua_checks) > 2 * cfg.ua_check_urls:
        probe_problems.append(f"{len(ua_checks)} user-agent check requests exceeded the cap of {2 * cfg.ua_check_urls}")
    untagged_checks = [r.seq for r in ua_checks if r.extra_headers.get(PROBE_HEADER[0]) != PROBE_HEADER[1]]
    if untagged_checks:
        probe_problems.append(f"{len(untagged_checks)} user-agent check request(s) lacked the {PROBE_HEADER[0]} header")
    other_agents = sorted({r.user_agent for r in ua_checks} - {BROWSER_USER_AGENT, googlebot})
    if other_agents:
        probe_problems.append(f"user-agent check requests used other user agents {other_agents}")
    if len(empty_checks) > EMPTY_BROWSER_CHECK_URLS:
        probe_problems.append(f"{len(empty_checks)} empty-page browser check requests exceeded the cap of "
                              f"{EMPTY_BROWSER_CHECK_URLS}")
    untagged_empty = [r.seq for r in empty_checks if r.extra_headers.get(PROBE_HEADER[0]) != PROBE_HEADER[1]]
    if untagged_empty:
        probe_problems.append(f"{len(untagged_empty)} empty-page browser check request(s) lacked the {PROBE_HEADER[0]} header")
    other_empty_agents = sorted({r.user_agent for r in empty_checks} - {BROWSER_USER_AGENT})
    if other_empty_agents:
        probe_problems.append(f"empty-page browser check requests used other user agents {other_empty_agents}")
    against_robots = []
    for r in ua_checks:
        policy = policies.get(origin_of(r.url))
        if r.user_agent == googlebot and (policy is None or not policy.decide(UA_CHECK_BOT, r.url).allowed):
            against_robots.append(r.seq)
    if against_robots:
        probe_problems.append(f"{len(against_robots)} request(s) with Googlebot's user agent went to URLs robots.txt "
                              "does not allow Googlebot")

    # Politeness: smallest gap between the end of one request to a host and the start of the next to that host
    # (DECISIONS 219 part 2: requests to other sites run beside the audited site's, each host at its own gap).
    # Measured on the monotonic clock the fetcher itself paces on. Mixing clocks (a wall-clock start
    # plus a monotonic duration) reported a violation that never happened on the first live crawl of a
    # real site, because a clock adjustment mid-run shifts wall-clock stamps against monotonic ones.
    # Resource requests made by the browser within one page render are a burst by nature; politeness is
    # measured between page-level requests (including one render and the next).
    host_gaps, clock = gaps_by_host(requests)
    gaps = [gap for values in host_gaps.values() for gap in values]
    crawl_delays = [r["crawl_delay"] for r in result.robots if r.get("crawl_delay")]
    backoff = getattr(result, "backoff", None)
    # A session with no finish time never completed — a crawl that was killed, or a stale row. It is
    # reported, but not counted as a peer of a session whose figures are known.
    all_rows = getattr(result, "sessions", None) or []
    rows = [r for r in all_rows if r.get("finished_at")]
    unfinished = [r["session_no"] for r in all_rows if not r.get("finished_at")]
    sessions_evidence: dict[str, Any] = {"count": len(rows) or 1, "this_session": rows[-1]["session_no"] if rows else 1}
    if unfinished:
        sessions_evidence["sessions_that_never_finished"] = unfinished
    if len(rows) > 1:
        sessions_evidence["assembled_from"] = [
            {k: r[k] for k in ("session_no", "started_at", "finished_at", "requests", "min_gap_ms",
                               "configured_delay_s", "final_delay_s", "stop_reason") if r.get(k) is not None}
            for r in rows]
        sessions_evidence["note"] = (
            "This crawl was resumed. Politeness is judged per session: this gate measured the requests made "
            "in the session it ran in, and the rows above carry each earlier session's own figures. A page "
            "fetched in one session and a page fetched in another were not seen at the same moment.")
        fingerprints = {r["robots_sha256"] for r in rows if r.get("robots_sha256")}
        if len(fingerprints) > 1:
            sessions_evidence["robots_changed_between_sessions"] = True
    # The audited site's required gap is the floor in use: the configured delay or its Crawl-delay, or, when adaptive
    # pacing narrowed it on a fast, error-free site, the narrowest gap it used (never below 0.5 s nor the Crawl-delay;
    # amends DECISIONS 82). Another host's is the configured delay, or its own Crawl-delay where Maya kept it.
    configured_gap_ms = max([cfg.request_delay_s * 1000] + [d["honored_seconds"] * 1000 for d in crawl_delays])
    narrowed = list((backoff or {}).get("narrowed") or [])
    required_gap_ms = min([configured_gap_ms] + [n["to_s"] * 1000 for n in narrowed])
    site_host = ((backoff or {}).get("site_host") or urlsplit(result.origin or "").hostname or "").lower()
    other_gaps_s = dict((backoff or {}).get("host_gaps_s") or {})
    tolerance_ms = 25.0
    by_host, slow_hosts = [], []
    for host, values in sorted(host_gaps.items(), key=lambda kv: (kv[0] != site_host, kv[0])):
        need = required_gap_ms if host == site_host else max(cfg.request_delay_s, other_gaps_s.get(host, 0.0)) * 1000
        smallest = round(min(values), 1) if values else None
        by_host.append({"host": host, "requests": len(values) + 1, "min_gap_ms": smallest, "required_gap_ms": round(need, 1)})
        if smallest is not None and smallest + tolerance_ms < need:
            slow_hosts.append((host, smallest, need))
    min_gap_ms = round(min(gaps), 1) if gaps else None
    # The shared site limit (DECISIONS 294): Maya's own requests to the site never had more in flight than it allowed.
    site_limit = (backoff or {}).get("site_limit") or None
    own_in_flight = most_in_flight([r for r in requests if r.purpose != "render_subresource"
                                    and (urlsplit(r.url).hostname or "").lower() == site_host])

    problems = []
    if site_limit and own_in_flight > int(site_limit.get("configured") or 1):
        problems.append(f"{own_in_flight} of Maya's requests to {site_host} were in flight at once, above the site limit "
                        f"of {site_limit.get('configured')}")
    if agents and agents != [cfg.user_agent]:
        problems.append(f"requests used user agents {agents}, expected only {cfg.user_agent!r}")
    if out_of_order:
        problems.append(f"{len(out_of_order)} request(s) were made before robots.txt was fetched for their origin")
    if disallowed_requests:
        problems.append(f"{len(disallowed_requests)} request(s) went to URLs robots.txt disallows")
    for host, smallest, need in slow_hosts[:5]:
        problems.append(f"smallest gap between requests to {host} was {smallest}ms, below the required {need:.0f}ms")
    problems.extend(probe_problems)

    skipped = [
        {"url": s.url, "discovered_via": s.discovered_via, "reason": s.decision["reason"], "rule": s.decision["rule"]}
        for s in result.skipped_robots
    ]
    no_request_evidence = not own
    if problems:
        summary = "Violation: " + "; ".join(problems) + "."
    elif no_request_evidence:
        detail = ("the audit deadline expired before any HTTP request could be attempted" if result.deadline_hit
                  else "no HTTP request was attempted")
        summary = f"Not assessed: {detail}. Requests skipped after the deadline are excluded from INT-4."
    else:
        summary = (
            f"Compliant: all {len(own)} of Maya's own requests used one user agent, robots.txt was fetched before "
            f"any other request to its origin, no request went to a disallowed URL, and {len(skipped)} URL(s) were "
            "skipped per robots.txt."
        )
        if probes:
            summary += (
                f" {len(probes)} tagged probe request(s) with AI-bot user agents were sent to this "
                "ownership-verified site (cap " + str(cfg.max_probe_requests) + ")."
            )
        if ua_checks:
            summary += (f" {len(ua_checks)} tagged request(s) compared a browser with Googlebot's user agent, one each "
                        f"(ACC-4; cap {2 * cfg.ua_check_urls}).")
        if empty_checks:
            summary += (f" {len(empty_checks)} tagged request(s) with a browser user agent re-asked pages that were empty "
                        f"to Maya (IDX-1; cap {EMPTY_BROWSER_CHECK_URLS}).")
    for delay in crawl_delays:
        if delay["capped"]:
            summary += (
                f" robots.txt declares Crawl-delay: {delay['seconds']:g}s for this user agent (line {delay['line']}); "
                f"Maya honored it up to its {delay['cap_seconds']:g}s cap."
            )

    bot_info_check = result.bot_info_check or {
        "state": "not_recorded",
        "reason": "No crawler-information page result was recorded.",
    }
    if bot_info_check.get("state") == "not_configured":
        summary += " No separate Maya information page was configured; the site audit continued."
    elif bot_info_check.get("state") == "unavailable":
        summary += f" Maya's optional information page could not be checked ({bot_info_check.get('reason')}); the site audit continued."

    state = "violation" if problems else "not_assessed" if no_request_evidence else "compliant"
    return GateResult(
        "INT-4", title, state, Confidence.NOT_ASSESSED if no_request_evidence else Confidence.VERIFIED, summary,
        {
            "user_agents_used": agents,
            "product_token": cfg.product_token,
            "bot_info_url": cfg.bot_info_url,
            "bot_info_check": bot_info_check,
            "requests_by_purpose": dict(Counter(r.purpose for r in requests)),
            "robots": result.robots,
            "skipped_by_robots": skipped[:SAMPLE],
            "skipped_by_robots_count": len(skipped),
            "requests_to_disallowed_urls": disallowed_requests,
            "requests_before_robots": out_of_order,
            "probes": {
                "count": len(probes),
                "cap": cfg.max_probe_requests,
                "ownership_verified": ownership_verified,
                "untagged_seqs": untagged,
                "user_agents": sorted({r.user_agent for r in probes}),
            },
            "ua_check": {
                "count": len(ua_checks),
                "cap": 2 * cfg.ua_check_urls,
                "untagged_seqs": untagged_checks,
                "user_agents": sorted({r.user_agent for r in ua_checks}),
                "googlebot_requests_against_robots": against_robots,
            },
            "politeness": {
                "measured_on": clock,
                "required_gap_ms": round(required_gap_ms, 1),
                "min_observed_gap_ms": min_gap_ms,
                "tolerance_ms": tolerance_ms,
                "crawl_delay": crawl_delays,
                # Backoff only ever widens the gap, so `required_gap_ms` above stays the floor this
                # gate checks against. Reported so a reader can see the site asked Maya to slow down
                # and that it did, rather than having to infer it from the elapsed time.
                "configured_delay_s": cfg.request_delay_s,
                # A resumed crawl has more than one session. Politeness holds per session — one user
                # agent, robots.txt first, a minimum gap — and this gate measures only the session it
                # ran in. Earlier sessions are listed with their own figures so nothing implies this
                # run's compliance covers requests it never made.
                "sessions": sessions_evidence,
                "final_delay_s": round(backoff["final_delay_s"], 3) if backoff else cfg.request_delay_s,
                "widened_after_rate_limit": backoff["widenings"] if backoff else [],
                # Adaptive pacing (DECISIONS 219 part 2): each narrowing of the audited site's gap, the floor it could
                # not go below, and the gaps measured per host (requests to other sites run in parallel).
                "adaptive_pacing": bool((backoff or {}).get("adaptive_pacing")),
                "narrowed": narrowed,
                "floor_s": (backoff or {}).get("floor_s"),
                "narrowing_stopped": (backoff or {}).get("narrowing_stopped"),
                "by_host": by_host[:40],
                "hosts": len(by_host),
                # The shared limit on the audited site after the crawl, and the most of Maya's own requests to it that
                # were in flight at once (the page reader's are not in this log; the limit counts both).
                "site_limit": site_limit,
                "max_in_flight_own": own_in_flight,
            },
        },
        None if not problems else "This is a defect in Maya's crawler, not in the audited site.",
    )


def most_in_flight(records) -> int:
    """The most requests in flight at one moment, from their monotonic start and end (0 when none have them)."""
    edges = []
    for r in records:
        if r.started_mono is None or r.ended_mono is None:
            continue
        edges += [(r.started_mono, 1), (max(r.ended_mono, r.started_mono), -1)]
    most = now = 0
    for _, step in sorted(edges, key=lambda e: (e[0], e[1])):  # an end before a start at the same moment
        now += step
        most = max(most, now)
    return most


def run_integrity_gates(result: CrawlResult, cfg: CrawlConfig) -> list[GateResult]:
    return [
        int1_fetch_classification(result, cfg),
        int2_crawl_completeness(result, cfg),
        int3_rendering_disclosure(result, cfg),
        int4_crawler_identity(result, cfg),
    ]
