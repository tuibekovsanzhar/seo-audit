"""PRF-1 to PRF-3: performance and fetch reliability (spec §5 PRF).

Framed around bots fetching within a time budget. A single timing is a Verified
fact about that request; "this page is slow" from repeated samples is Estimated.
Every attempt counted here is also what IDX-1 uses, so a URL that fails on every
attempt is IDX-1's, and one that sometimes works is PRF's.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from urllib.parse import urlsplit

from ..access_data import homepage_url, key_page_urls
from ..config import CrawlConfig
from ..coverage import settle_all
from ..findings import CheckResult, Finding, Rationale, Severity, is_homepage_url, scope_for
from ..html_links import is_html
from ..models import Confidence, CrawlResult
from ..perf_data import attempts_by_url, counted, failed
from .access import _status, _tier

LIVE_FETCHERS = ["ChatGPT-User (OpenAI)", "Claude-User (Anthropic)", "Perplexity-User", "Googlebot (crawl rate)"]
CAPPED = "Capped at S4: the vendors' live-fetch time budgets are not documented (Hypothesis)."
# The HTML is not cached at the CDN (H28, G05): the site forbids a shared copy and the CDN says it did not serve one.
# Only `private` and `no-store` forbid a shared cache: `no-cache` and `max-age=0` mean "check back before reuse", and a
# CDN may still keep the copy (RFC 9111 §5.2.2).
NOT_SHAREABLE = re.compile(r"\b(?:private|no-store)\b", re.I)
# Which CDN answered, from its own response headers (G05): (name, header, words in that header's value; "" = present).
# The first that matches names the CDN; RFC 9211 Cache-Status names its cache itself and comes last.
CDN_SIGNS = (
    ("Cloudflare", "cf-cache-status", ""), ("Cloudflare", "cf-ray", ""), ("Cloudflare", "server", "cloudflare"),
    ("CloudFront", "x-amz-cf-id", ""), ("CloudFront", "x-amz-cf-pop", ""), ("CloudFront", "via", "cloudfront"),
    ("CloudFront", "x-cache", "cloudfront"),
    ("Akamai", "akamai-cache-status", ""), ("Akamai", "server", "akamaighost"), ("Akamai", "x-cache", "tcp_"),
    ("Fastly", "x-served-by", "cache-"), ("Fastly", "via", "varnish"),
    ("Vercel", "x-vercel-cache", ""), ("Vercel", "x-vercel-id", ""), ("Vercel", "server", "vercel"),
    ("Netlify", "x-nf-request-id", ""), ("Netlify", "server", "netlify"),
    ("Sucuri", "x-sucuri-cache", ""), ("Sucuri", "server", "sucuri"),
)
# The headers in which a CDN says what it did with this answer, most specific first. `x-cache` may list several hops
# ("MISS, HIT": the shield missed, the edge nearest the client hit): its LAST hop is the one that answered.
STATUS_HEADERS = ("cache-status", "cf-cache-status", "akamai-cache-status", "x-vercel-cache", "x-sucuri-cache", "x-cache")
# Words of a status, read with "_" as a space ("TCP_MEM_HIT" is tcp, mem, hit). A hit word wins over a miss word in one
# hop; "expired" and "revalidated" mean the CDN kept a copy and checked it.
HIT_WORDS = frozenset({"hit", "refreshhit", "stale", "prerender", "revalidated", "updating", "expired"})
MISS_WORDS = frozenset({"miss", "dynamic", "bypass", "pass", "uncacheable"})
CACHE_FIX = ("If a page's HTML is the same for every visitor, let the CDN keep a copy: send Cache-Control with a public "
             "lifetime for shared caches (for example “public, s-maxage=300”) instead of private or no-store, or add a "
             "rule in the CDN that caches HTML for a short time and is purged when you publish. Keep pages that differ "
             "per visitor (cart, account) uncached.")
CACHE_EXPECTED = "the HTML of pages that are the same for every visitor is served from the CDN's cache"
HSTS_FIX = ("Send “Strict-Transport-Security: max-age=31536000” on https answers, from the web server or the application. "
            "Add includeSubDomains only when every subdomain serves https.")
HSTS_CDN = "Add the same header at the CDN in front of the site if that is simpler: it sends it on every https answer at its edge."
HSTS_EXPECTED = "an https site tells browsers to use https only (Strict-Transport-Security)"
# Google's published "poor" boundaries for field data (PageSpeed Insights docs, checked 2026-09-14).
POOR = {"LCP p75 (ms)": 4000.0, "INP p75 (ms)": 500.0, "CLS p75": 0.25}


def nearest_rank(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def _perf(result: CrawlResult):
    return getattr(result, "perf", None)


def _egress(cfg: CrawlConfig) -> str:
    return cfg.egress_region or "not recorded (set --egress-region; Maya does not look it up)"


def _row(a: dict) -> dict:
    return {k: a.get(k) for k in ("source", "requested_at", "status", "error", "ttfb_ms", "total_ms")}


def _is_timeout(a: dict) -> bool:
    return bool(a["error"] and a["error"].startswith("timeout"))


def _ok(a: dict) -> bool:
    return counted(a) and not failed(a)


# -- PRF-1 ---------------------------------------------------------------------

def prf1_response_time(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Server response time (HTML)"
    perf = _perf(result)
    history = attempts_by_url(result)
    key_urls = set(key_page_urls(result, cfg))
    sample = perf.sample if perf else []
    measured, too_few, slow = [], [], []
    for item in sample:
        attempts = history.get(item["url"], [])
        good = [a for a in attempts if _ok(a) and a["status"] and 200 <= a["status"] < 300 and a["total_ms"] is not None]
        row = {"url": item["url"], "why": item["why"], "successful_samples": len(good),
               "samples": [_row(a) for a in attempts]}
        if len(good) < cfg.prf_min_samples:
            too_few.append({**row, "reason": f"{len(good)} successful sample(s); {cfg.prf_min_samples} needed"})
            continue
        totals = [a["total_ms"] for a in good]
        ttfbs = [a["ttfb_ms"] for a in good if a["ttfb_ms"] is not None]
        row.update(median_total_ms=round(statistics.median(totals), 1), p90_total_ms=nearest_rank(totals, 90),
                   median_ttfb_ms=round(statistics.median(ttfbs), 1) if ttfbs else None)
        measured.append(row)
        if row["median_total_ms"] > cfg.prf_slow_median_s * 1000:
            slow.append(row)

    intermittent = []
    for url, attempts in history.items():
        timeouts = [a for a in attempts if _is_timeout(a)]
        if timeouts and any(_ok(a) for a in attempts):
            intermittent.append({"url": url, "timeouts": len(timeouts), "attempts": len([a for a in attempts if counted(a)]),
                                 "samples": [_row(a) for a in attempts], "timeout_s": cfg.request_timeout_s})

    findings = []
    common_notes = [CAPPED, "Timings are measured from Maya's crawler: request sent to last byte read (TTFB: to the "
                            "response headers). Both include connection setup when a new connection was opened, and "
                            "exclude Maya's own politeness wait."]
    if slow:
        urls = [r["url"] for r in slow]
        findings.append(Finding(
            "PRF-1", f"{len(urls)} page(s) take more than {cfg.prf_slow_median_s:g} s (median) to return their HTML",
            Severity.S4, Confidence.ESTIMATED,
            "Hypothesis (live fetch budget) / Documented (slow responses reduce crawl rate, Google)", LIVE_FETCHERS,
            scope_for(urls), {"pages": slow[:40], "threshold_s": cfg.prf_slow_median_s, "egress_region": _egress(cfg)},
            f"HTML returned in under {cfg.prf_slow_median_s:g} s", "Find what makes these responses slow (uncached "
            "rendering, slow queries, upstream calls) and cache or speed up the HTML response.",
            importance_tier=_tier(urls, key_urls),
            notes=common_notes + [f"Estimated: 'slow' generalizes from {cfg.prf_min_samples}+ samples; each sample "
                                  "is Verified. With 3 samples the p90 is the slowest sample.",
                                  f"The {cfg.prf_slow_median_s:g} s threshold is policy (spec default: 1.5 s)."]))
    # The homepage on its own (DECISIONS 258): a site-wide median hides a slow homepage, the one page every visitor and
    # crawler reaches first. Its own samples, each verified, against web.dev's "good" TTFB (0.8 s).
    home = homepage_url(result)
    home_row = next((r for r in measured if r["url"] == home or (r["why"] == "homepage" and is_homepage_url(r["url"]))), None)
    if home_row and home_row["median_ttfb_ms"] is not None and home_row["median_ttfb_ms"] > cfg.homepage_ttfb_max_ms:
        ms = round(home_row["median_ttfb_ms"])
        findings.append(Finding(
            "PRF-1", f"The homepage takes {ms} ms (median of {home_row['successful_samples']} requests) to start answering",
            Severity.S2, Confidence.VERIFIED,
            "Documented (web.dev: a good time to first byte is 0.8 s or less)", LIVE_FETCHERS,
            scope_for([home_row["url"]]), {"pages": [home_row], "threshold_ms": cfg.homepage_ttfb_max_ms,
                                          "egress_region": _egress(cfg)},
            "a homepage that starts answering within the good time to first byte",
            "Ask the platform or host for a page cache, or a CDN rule that caches the homepage HTML; then find what the "
            "server does before it starts answering (uncached rendering, slow queries, upstream calls).",
            importance_tier=0,
            notes=common_notes + ["High on the homepage by the owner's decision (DECISIONS 258); the threshold is web.dev's "
                                  "'good' time to first byte. Measured from Maya's network, not real users."]))
    if intermittent:
        urls = [r["url"] for r in intermittent]
        findings.append(Finding(
            "PRF-1", f"{len(urls)} URL(s) time out on some attempts but not others", Severity.S4, Confidence.VERIFIED,
            Rationale.HYPOTHESIS.value + " (live fetch budget)", LIVE_FETCHERS, scope_for(urls),
            {"pages": intermittent[:40], "egress_region": _egress(cfg)}, "every attempt answers within the timeout",
            "Look for what makes these URLs occasionally hang (cold caches, locks, upstream timeouts).",
            importance_tier=_tier(urls, key_urls),
            notes=[CAPPED, f"A URL that times out on every attempt is an IDX-1 finding, not this one."]))
    evidence = {"egress_region": _egress(cfg), "sample_size": len(sample), "measured": measured[:60],
                "not_enough_samples": too_few[:40], "not_enough_samples_count": len(too_few), "threshold_s": cfg.prf_slow_median_s,
                "rounds": perf.rounds if perf else [], "skipped_reason": perf.skipped_reason if perf else "not collected"}
    field_ttfb = _field_ttfb(perf)
    if field_ttfb:
        evidence["crux_field_ttfb_p75"] = field_ttfb
    # How the HTML is delivered (H28, H32), from the crawl's own answers: kept whatever the timing samples say.
    html = _html_pages(result)
    observations = []
    ttfbs = [p.ttfb_ms for p in html if p.ttfb_ms is not None]
    if ttfbs:
        median_ttfb = round(statistics.median(ttfbs), 1)
        evidence["crawl_median_ttfb_ms"] = {"value": median_ttfb, "pages": len(ttfbs)}
        observations.append({"metric": "median time to first byte of the HTML pages the crawl read", "value_ms": median_ttfb,
                             "pages": len(ttfbs), "threshold": "none: recorded whatever its value",
                             "cache_status": dict(Counter(_cache_label(p) for p in html).most_common(5))})
    findings += _cdn_cache_findings(html, key_urls, evidence.get("crawl_median_ttfb_ms"))
    cached = cache_observation(html)
    if cached:
        observations.append(cached)
    findings += _hsts_findings(result)
    findings += _security_header_findings(result)
    if not measured and not intermittent:
        reason = (perf.skipped_reason if perf and perf.skipped_reason else
                  f"no sampled URL had {cfg.prf_min_samples} successful fetches")
        if not findings:
            return CheckResult("PRF-1", title, "not_assessed", f"Not assessed: {reason}.", [], evidence, observations)
        # What the headers show stands; the response-time samples are what could not be judged.
        return CheckResult("PRF-1", title, _status(findings), f"{len(findings)} finding(s). Not assessed: {reason}.",
                           findings, evidence, observations)
    slowest = max(measured, key=lambda r: r["median_total_ms"], default=None)
    summary = (f"{len(findings)} finding(s)." if findings else
               f"{len(measured)} URL(s) measured {cfg.prf_min_samples}+ times; slowest median "
               f"{slowest['median_total_ms']:.0f} ms ({slowest['url']}).")
    if too_few:
        summary += f" {len(too_few)} sampled URL(s) had too few successful samples to judge."
    if ttfbs:
        summary += f" Median time to first byte of {len(ttfbs)} HTML page(s): {median_ttfb:.0f} ms."
    return CheckResult("PRF-1", title, _status(findings), summary, findings, evidence, observations)


def _html_pages(result: CrawlResult) -> list:
    """The HTML pages Maya's own crawl read (2xx, its own request, not a provider's document)."""
    return [p for p in result.pages if getattr(p, "view", "raw") == "raw" and p.status is not None
            and 200 <= p.status < 300 and is_html(p.content_type)]


def cdn_name(headers: dict | None) -> str | None:
    """The CDN that answered, from its own response headers (G05), or None when none says so. A platform's name is not
    a CDN's: a shop platform may or may not sit behind one."""
    lowered = {k.lower(): str(v).lower() for k, v in (headers or {}).items()}
    for name, header, word in CDN_SIGNS:
        value = lowered.get(header)
        if value is not None and word in value:
            return name
    status = next((str(v) for k, v in (headers or {}).items() if k.lower() == "cache-status"), "")
    if status:
        # RFC 9211: the last member is the cache nearest the client; its first item is that cache's name.
        return status.split(",")[-1].split(";")[0].strip().strip('"') or "a cache (Cache-Status)"
    return None


def _status_header(headers: dict) -> tuple[str, str] | None:
    for name in STATUS_HEADERS:
        if headers.get(name):
            return name, str(headers[name]).strip()
    return None


def cache_state(headers: dict | None) -> str | None:
    """"hit" when the CDN says it answered from a copy, "miss" when it says it went to the origin, None when it says
    neither. The hop nearest the client decides: the last of a comma list ("MISS, HIT" is a hit), RFC 9211's last member
    ("…; fwd=miss" without "hit" is a miss). An Age above 0 means a cache held the answer, whatever the status says."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    try:
        if float(str(headers.get("age") or "0").strip() or 0) > 0:
            return "hit"
    except ValueError:
        pass
    found = _status_header(headers)
    if found is None:
        return None
    name, value = found
    hop = value.split(",")[-1].lower()
    if name == "cache-status":
        params = {part.strip().split("=")[0] for part in hop.split(";")[1:]}
        return "hit" if "hit" in params else "miss" if "fwd" in params else None
    words = set(re.findall(r"[a-z]+", hop.replace("_", " ")))
    return "hit" if words & HIT_WORDS else "miss" if words & MISS_WORDS else None


def _cache_label(page) -> str:
    """The CDN's own word for what it did with this answer ("cf-cache-status DYNAMIC", "x-cache MISS, HIT"), or "none"."""
    found = _status_header({k.lower(): v for k, v in (page.headers or {}).items()})
    if found is None:
        return "no CDN cache header"
    name, value = found
    return f"{name} {value.upper() if name == 'cf-cache-status' else value}"


def _not_shareable(page) -> bool:
    return bool(NOT_SHAREABLE.search((page.headers or {}).get("cache-control") or ""))


def _cdn_cache_findings(pages: list, key_urls: set[str], ttfb: dict | None, share: float | None = None) -> list[Finding]:
    """Info (H28, G05): a CDN is named by its own headers, its own status says it went to the origin on (nearly) every
    HTML page that carries that status, and the site's Cache-Control forbids a shared copy (private, no-store). Every
    answer then waits for the origin server, for a person and for a bot alike. With no CDN named, a CDN that serves
    copies, or a site that only asks for revalidation (no-cache), nothing is reported: PRF-1's observation keeps the
    headers seen (`cache_observation`)."""
    from ..config import CDN_NOT_CACHED_SHARE
    share = CDN_NOT_CACHED_SHARE if share is None else share
    told = [(p, cdn_name(p.headers), cache_state(p.headers)) for p in pages]
    told = [(p, cdn, state) for p, cdn, state in told if cdn and state]
    hit = [(p, cdn) for p, cdn, state in told if state == "miss" and _not_shareable(p)]
    if not hit or len(hit) < share * len(told):
        return []
    labels = Counter(_cache_label(p) for p, _ in hit)
    controls = Counter((p.headers or {}).get("cache-control", "").strip() for p, _ in hit)
    cdns = Counter(cdn for _, cdn in hit)
    urls = [p.url for p, _ in hit]
    statuses = ", ".join(label for label, _ in labels.most_common(3))
    return [Finding(
        "PRF-1", f"The HTML of {len(urls)} page(s) is not cached at the CDN ({statuses})", Severity.INFO, Confidence.VERIFIED,
        "Measured (response headers) / Hypothesis (effect on AI fetchers)", LIVE_FETCHERS, scope_for(urls),
        {"cdn": dict(cdns), "cache_status": dict(labels), "cache_control": dict(controls.most_common(5)),
         "pages_with_cdn_status": len(told),
         "rule": f"a CDN named by its own headers; its status (the hop nearest the client) says miss, dynamic or bypass "
                 f"on at least {share:.0%} of the HTML pages carrying it; and Cache-Control private or no-store",
         "median_ttfb_ms": ttfb,
         "pages": [{"url": p.url, "ttfb_ms": p.ttfb_ms, **{k: (p.headers or {}).get(k) for k in
                    ("cache-control", *STATUS_HEADERS, "age", "server")}} for p, _ in hit[:40]]},
        CACHE_EXPECTED, CACHE_FIX, importance_tier=_tier(urls, key_urls),
        notes=["Verified: the headers as sent to Maya's crawler. Inferred: a cached copy at the CDN would answer faster; "
               "whether an AI fetcher gives up on a slow answer is not documented."])]


def cache_observation(pages: list) -> dict | None:
    """What the HTML pages' headers say about caching, as an observation (no severity): which CDN they name, if any,
    the statuses and the Cache-Control values. Recorded whether or not a finding was made."""
    if not pages:
        return None
    cdns = Counter(cdn_name(p.headers) or "none named" for p in pages)
    states = Counter(cache_state(p.headers) or "not said" for p in pages)
    controls = Counter((p.headers or {}).get("cache-control", "").strip() or "none" for p in pages)
    return {"metric": "how the HTML pages are cached (response headers)", "pages": len(pages),
            "cdn": dict(cdns.most_common(3)), "cdn_cache_state": dict(states), "cache_control": dict(controls.most_common(3)),
            "threshold": "none: a finding needs a named CDN that went to the origin and Cache-Control private or no-store"}


def _hsts_findings(result: CrawlResult) -> list[Finding]:
    """Info (H32): the https homepage sends no Strict-Transport-Security header. Placed in PRF-1, the check that reads how
    the HTML is delivered, so no new check id is needed (W1 notes, H32)."""
    home = homepage_url(result)
    page = next((p for p in result.pages if p.url == home and getattr(p, "view", "raw") == "raw"), None)
    if (page is None or urlsplit(home).scheme != "https" or page.status is None or not 200 <= page.status < 300
            or "strict-transport-security" in (page.headers or {})):
        return []
    # G14: the fix names no vendor's menu; when the answer shows a CDN, one sentence says the edge can add the header.
    cdn = cdn_name(page.headers)
    return [Finding(
        "PRF-1", "The https homepage sends no Strict-Transport-Security header", Severity.INFO, Confidence.VERIFIED,
        "Documented (RFC 6797)", ["browsers (none of the answer engines documents using it)"],
        scope_for([home], sitewide=True), {"url": home, "status": page.status, "headers_kept": page.headers,
                                           "cdn": cdn, "reproduce": page.reproduce()},
        HSTS_EXPECTED, HSTS_FIX + (" " + HSTS_CDN if cdn else ""))]


# DECISIONS 262: the response headers OWASP's Secure Headers Project lists as a baseline. A note, not a search issue.
SECURITY_HEADERS_DOC = "Documented (OWASP Secure Headers Project; MDN HTTP headers reference)"


def missing_security_headers(headers: dict) -> list[str]:
    """Which baseline security headers the response lacks (names as a developer types them)."""
    h = {k.lower(): (v or "") for k, v in (headers or {}).items()}
    missing = []
    if "content-security-policy" not in h and "content-security-policy-report-only" not in h:
        missing.append("Content-Security-Policy")
    if h.get("x-content-type-options", "").strip().lower() != "nosniff":
        missing.append("X-Content-Type-Options: nosniff")
    if "referrer-policy" not in h:
        missing.append("Referrer-Policy")
    if "x-frame-options" not in h and "frame-ancestors" not in h.get("content-security-policy", ""):
        missing.append("X-Frame-Options (or CSP frame-ancestors)")
    return missing


def _security_header_findings(result: CrawlResult) -> list[Finding]:
    """Info: the homepage's answer lacks baseline security headers (claude-seo reported this on three sites; we did not
    look). Read from the homepage only: headers are usually set once for the whole site."""
    home = homepage_url(result)
    page = next((p for p in result.pages if p.url == home and getattr(p, "view", "raw") == "raw"), None)
    # https only, as the HSTS note: a plain-http site has a larger problem first (and the offline fakes are http).
    if page is None or urlsplit(home).scheme != "https" or page.status is None or not 200 <= page.status < 300:
        return []
    missing = missing_security_headers(page.headers)
    if not missing:
        return []
    return [Finding(
        "PRF-1", f"The homepage answers without {len(missing)} baseline security header(s)", Severity.INFO,
        Confidence.VERIFIED, SECURITY_HEADERS_DOC, ["browsers and the site's visitors (not a search ranking signal)"],
        scope_for([home], sitewide=True), {"url": home, "missing": missing, "reproduce": page.reproduce()},
        "Content-Security-Policy, X-Content-Type-Options: nosniff, Referrer-Policy and frame protection on every answer",
        "Add the missing headers at the server, CDN or platform level (one setting for the whole site); start a new "
        "Content-Security-Policy in report-only mode so it breaks nothing.",
        notes=["Verified from the homepage's response headers. These protect visitors; no search or answer engine "
               "documents using them for ranking."])]


def _field_ttfb(perf) -> list[dict]:
    lab_field = perf.lab_field if perf else None
    rows = []
    for entry in (lab_field or {}).get("urls", []):
        p75 = (entry.get("field") or {}).get("p75") or {}
        if p75.get("TTFB p75 (ms)") is not None:
            rows.append({"url": entry["url"], "scope": entry["field"].get("scope"), "ttfb_p75_ms": p75["TTFB p75 (ms)"]})
    return rows


# -- PRF-2 ---------------------------------------------------------------------

def prf2_reliability(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Fetch reliability"
    history = attempts_by_url(result)
    key_urls = set(key_page_urls(result, cfg))
    flaky, persistent, not_counted, failing_urls = [], [], 0, []
    total = failures = 0
    from ..perf_data import request_outcomes, RELIABILITY_DEFINITION
    outcomes = request_outcomes(history)
    for url, attempts in history.items():
        not_counted += sum(1 for a in attempts if not counted(a))
        mine = [a for a in attempts if counted(a)]
        bad = [a for a in mine if failed(a)]
        if len(mine) >= 2 and bad and len(bad) == len(mine):
            persistent.append(url)  # IDX-1's finding; left out of the rate too (one report per root cause)
            continue
        total += len(mine)
        failures += len(bad)
        if bad:
            failing_urls.append(url)
        if bad and len(bad) < len(mine) and any(not _is_timeout(a) for a in bad):
            flaky.append({"url": url, "failures": len(bad), "attempts": len(mine), "samples": [_row(a) for a in mine]})
    findings = []
    if flaky:
        urls = [r["url"] for r in flaky]
        findings.append(Finding(
            "PRF-2", f"{len(urls)} URL(s) failed on some attempts and worked on others", Severity.S4, Confidence.VERIFIED,
            Rationale.HYPOTHESIS.value, ["all answer engines (a failed live fetch is not retried like a person would)"],
            scope_for(urls), {"pages": flaky[:40]}, "every attempt succeeds",
            "Check the server and upstream logs at the failed attempts' times (5xx, resets, dropped connections).",
            importance_tier=_tier(urls, key_urls),
            notes=["Capped at S4: Hypothesis.", "Timeout-only failures are PRF-1's; URLs failing on every attempt are IDX-1's."]))
    observations = []
    rate = failures / total if total else None
    if total >= cfg.prf_sitewide_min_attempts:
        if rate > cfg.prf_sitewide_failure_share:
            urls = sorted(failing_urls)
            findings.append(Finding(
                "PRF-2", f"{rate:.1%} of fetches failed across the audit (threshold {cfg.prf_sitewide_failure_share:.0%})",
                Severity.S4, Confidence.VERIFIED, Rationale.HYPOTHESIS.value, ["all answer engines"],
                scope_for(urls, sitewide=True), {"failures": failures, "attempts": total, "rate": round(rate, 4)},
                f"under {cfg.prf_sitewide_failure_share:.0%} of fetches fail", "Investigate origin stability.",
                importance_tier=_tier(urls, key_urls),
                notes=["Capped at S4: Hypothesis.", "Timeouts count toward the rate; URLs failing on every attempt "
                                                    "(IDX-1) do not."]))
    else:
        observations.append({"metric": "sitewide failure rate (not judged: too few attempts)", "failures": failures,
                              "attempts": total, "minimum_attempts": cfg.prf_sitewide_min_attempts})
    perf = _perf(result)
    rounds_missing = perf is None or not perf.rounds
    summary = f"{len(findings)} finding(s)." if findings else (
        f"{failures} failure(s) in {total} counted fetch(es); no URL failed intermittently.")
    status = _status(findings)
    if rounds_missing:
        reason = perf.skipped_reason if perf and perf.skipped_reason else "the extra fetch rounds did not run"
        summary += f" The 3-attempt sampling did not run ({reason}), so only crawl fetches and IDX-1 refetches count."
        if not findings:
            status = "not_assessed"
    return CheckResult("PRF-2", title, status, summary, findings,
                       {"request_outcomes": dict(outcomes),
                        "failure_definition": RELIABILITY_DEFINITION,
                        "attempts_counted": total, "failures": failures, "rate": round(rate, 4) if rate is not None else None,
                        "urls_failing_every_attempt_left_to_IDX-1": persistent,
                        "blocked_or_rate_limited_attempts_not_counted": not_counted,
                        "min_attempts_for_rate": cfg.prf_sitewide_min_attempts}, observations)


# -- PRF-3 ---------------------------------------------------------------------

def prf3_lab_field(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Core Web Vitals and Lighthouse metrics (optional)"
    perf = _perf(result)
    lab_field = perf.lab_field if perf else None
    if not lab_field:
        return CheckResult("PRF-3", title, "not_assessed", "Optional panel not run (--pagespeed).")
    if not lab_field.get("assessed"):
        return CheckResult("PRF-3", title, "not_assessed", f"Not assessed: {lab_field['reason']}.", evidence=lab_field)
    key_urls = set(key_page_urls(result, cfg))
    observations, poor = [], []
    for entry in lab_field["urls"]:
        field_data, lab = entry.get("field") or {}, entry.get("lab") or {}
        p75 = field_data.get("p75")
        observations.append({
            "url": entry["url"],
            "field (CrUX, Verified aggregate of real Chrome users; says nothing about bots)":
                {"scope": field_data.get("scope"), "p75": p75, "collection_period": field_data.get("collection_period")}
                if p75 else {"assessed": False, "reason": "no CrUX record for the URL or its origin",
                             "responses": [a.get("http_status") for a in field_data.get("attempts", [])]},
            "lab (Lighthouse via PageSpeed Insights, Estimated: varies run to run)":
                lab.get("medians") if lab.get("medians") else {"assessed": False, "reason": lab.get("reason")},
        })
        for label, limit in POOR.items():
            value = _number((p75 or {}).get(label))
            if value is not None and value > limit:
                poor.append({"url": entry["url"], "metric": label, "p75": value, "poor_above": limit,
                             "scope": field_data.get("scope")})
    findings = []
    for label in POOR:
        rows = [r for r in poor if r["metric"] == label]
        if rows:
            urls = [r["url"] for r in rows]
            findings.append(Finding(
                "PRF-3", f"{len(urls)} URL(s) have real-user {label} in Google's 'poor' range"
                         + (" (whole-origin data for some)" if any(r["scope"] == "origin" for r in rows) else ""),
                Severity.INFO,
                Confidence.VERIFIED, Rationale.HYPOTHESIS.value + " (for AI answers)",
                ["none directly: non-rendering AI crawlers never paint the page"], scope_for(urls), {"values": rows},
                "field p75 outside the 'poor' range", "Improve the metric for users; the AI-answer benefit is indirect.",
                cost_tier="T2", importance_tier=_tier(urls, key_urls),
                notes=["Info by spec, never above S4. A value with scope 'origin' is the whole site's data, used "
                       "because the URL had too little traffic."]))
    summary = (f"{len(findings)} Info finding(s); metric values below (no category scores)." if findings
               else "Metric values recorded below (no category scores).")
    evidence = {k: v for k, v in lab_field.items() if k != "urls"}
    evidence["category_scores"] = "never read or shown (spec §7)"
    return CheckResult("PRF-3", title, _status(findings), summary, findings, evidence, observations)


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def run_perf_checks(result: CrawlResult, cfg: CrawlConfig) -> list[CheckResult]:
    return settle_all([prf1_response_time(result, cfg), prf2_reliability(result, cfg), prf3_lab_field(result, cfg)], result)
