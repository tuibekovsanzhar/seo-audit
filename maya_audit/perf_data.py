"""Data collected after the crawl for PRF checks.

PRF-1 / PRF-2: a sample of URLs is fetched again in spaced rounds with the same
fetcher (same identity, politeness, request log). The crawl fetch is attempt 1 and
an IDX-1 refetch, when there was one, is another attempt, so every URL's full
history is in `attempts_by_url`. IDX-1 uses the same history to decide what
"fails on every attempt" means, so the two checks never disagree.

PRF-3 (optional, T2): PageSpeed Insights lab runs (Google's servers load the page
with Lighthouse, so only on ownership-verified sites) and CrUX field data (an
aggregate lookup; nothing is sent to the site). Category scores are never read.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from .network import PublicTransport

from .access_data import homepage_url, key_page_urls
from .classify import classify_fetch
from .config import CrawlConfig
from .fetcher import Fetcher, tls_verify, utc_now
from .html_links import is_html
from .models import CrawlResult, FetchClass, StopReason
from .urls import detect_templates

# Lighthouse audit ids (checked against Lighthouse's default config, 2026-09-14) and CrUX metric names
# (checked against the CrUX API docs, 2026-09-14). The live PSI response shape is on the launch gate.
LAB_AUDITS = {"largest-contentful-paint": "LCP (ms)", "cumulative-layout-shift": "CLS",
              "total-blocking-time": "TBT (ms)", "server-response-time": "TTFB (ms)"}
FIELD_METRICS = {"largest_contentful_paint": "LCP p75 (ms)", "interaction_to_next_paint": "INP p75 (ms)",
                 "cumulative_layout_shift": "CLS p75", "experimental_time_to_first_byte": "TTFB p75 (ms)"}


@dataclass
class PerfData:
    enabled: bool
    skipped_reason: str | None = None
    egress_region: str | None = None
    sample: list[dict[str, Any]] = field(default_factory=list)
    rounds: list[dict[str, Any]] = field(default_factory=list)
    # url -> attempts from the PRF rounds only; see attempts_by_url for the full history.
    extra_attempts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    lab_field: dict[str, Any] | None = None


def failed(attempt: dict) -> bool:
    return attempt["fetch_class"] == FetchClass.ERROR.value or (
        attempt["fetch_class"] == FetchClass.OK.value and (attempt["status"] or 0) >= 500)


def counted(attempt: dict) -> bool:
    """Blocked and rate-limited answers are INT-1's; they are neither a success nor a failure here."""
    return attempt["fetch_class"] in (FetchClass.OK.value, FetchClass.ERROR.value)


def attempts_by_url(result: CrawlResult) -> dict[str, list[dict[str, Any]]]:
    """Every fetch of each crawled URL, in order: the crawl, the IDX-1 refetch, then PRF rounds."""
    out: dict[str, list[dict[str, Any]]] = {}
    for page in result.pages:
        out.setdefault(page.url, []).append({
            "source": "crawl", "requested_at": page.requested_at, "status": page.status, "error": page.error,
            "fetch_class": page.fetch_class.value, "ttfb_ms": page.ttfb_ms, "total_ms": page.elapsed_ms,
            "bytes": page.body_bytes, "truncated": page.body_truncated})
    index = getattr(result, "index", None)
    for refetch in (index.refetches if index else []):
        again = refetch["refetch"]
        out.setdefault(refetch["url"], []).append({
            "source": "idx_refetch", "requested_at": again["requested_at"], "status": again["status"],
            "error": again["error"], "fetch_class": again["fetch_class"], "ttfb_ms": again.get("ttfb_ms"),
            "total_ms": again.get("elapsed_ms"), "truncated": again.get("truncated")})
    perf = getattr(result, "perf", None)
    for url, attempts in (perf.extra_attempts.items() if perf else []):
        out.setdefault(url, []).extend(attempts)
    for attempts in out.values():
        attempts.sort(key=lambda a: a["requested_at"])
    return out


def choose_sample(result: CrawlResult, cfg: CrawlConfig) -> list[dict[str, Any]]:
    """Homepage → key pages → one page per template → URLs that failed in the crawl (to test them again)."""
    # An empty page (IDX-1, DECISIONS 204) answers fast because it sends nothing: it says nothing about the site's speed.
    readable = {p.url: p for p in result.pages if p.fetch_class == FetchClass.OK and p.status
                and 200 <= p.status < 300 and is_html(p.content_type) and not (p.analysis or {}).get("empty_response")}
    chosen: dict[str, str] = {}

    def add(url: str, why: str) -> None:
        if url not in chosen and len(chosen) < cfg.prf_max_urls:
            chosen[url] = why

    home = homepage_url(result)
    if home in readable:
        add(home, "homepage")
    for url in [u for u in key_page_urls(result, cfg) if u in readable][: cfg.prf_key_page_slots]:
        add(url, "user-marked key page")
    templates = sorted(detect_templates(list(readable)).items(), key=lambda kv: (-len(kv[1]), kv[0]))
    added = 0
    for template, urls in templates:
        if added >= cfg.prf_template_slots:
            break
        if not any(u in chosen for u in urls):
            add(sorted(urls)[0], f"template {template} ({len(urls)} page(s))")
            added += 1
    for page in result.pages:
        if page.fetch_class == FetchClass.ERROR or (page.fetch_class == FetchClass.OK and (page.status or 0) >= 500):
            add(page.url, "failed during the crawl")
    return [{"url": u, "why": w} for u, w in chosen.items()]


def collect_perf_data(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig) -> PerfData:
    data = PerfData(enabled=cfg.prf_enabled, egress_region=cfg.egress_region)
    if cfg.pagespeed_enabled:
        data.lab_field = collect_lab_field(result, cfg, fetcher)
    if not cfg.prf_enabled:
        data.skipped_reason = "extra PRF rounds disabled (--no-prf); only the crawl fetch and IDX-1 refetches exist"
        return data
    if result.stop_reason == StopReason.RATE_LIMIT:
        data.skipped_reason = "the crawl stopped because the site rate-limited Maya; no extra requests were sent"
        return data
    data.sample = choose_sample(result, cfg)
    policy = result.robots_policy_by_origin.get(result.origin)
    for n in range(cfg.prf_extra_rounds):
        if n and cfg.prf_round_gap_s:
            if not fetcher.sleep(cfg.prf_round_gap_s):
                data.skipped_reason = "overall audit deadline reached before the next performance sample"
                return data
        round_info = {"round": n + 2, "started_at": utc_now(), "requests": 0}
        data.rounds.append(round_info)
        for item in data.sample:
            url = item["url"]
            if policy is not None and not policy.decide(cfg.product_token, url).allowed:
                continue  # defensive: never send a request robots.txt disallows
            response = fetcher.get(url, "prf_sample", cfg.max_body_bytes)
            if response.error == "audit_deadline_skipped":  # never sent: not a slow or failed response
                data.skipped_reason = f"overall audit deadline reached during round {n + 2}; the round is incomplete"
                return data
            round_info["requests"] += 1
            classification = classify_fetch(response.status, response.headers, response.body, response.error)
            data.extra_attempts.setdefault(url, []).append({
                "source": f"prf_round_{n + 2}", "requested_at": response.started_at, "status": response.status,
                "error": response.error, "fetch_class": classification.fetch_class.value, "ttfb_ms": response.ttfb_ms,
                "total_ms": response.elapsed_ms, "bytes": len(response.body), "truncated": response.truncated})
            if classification.fetch_class == FetchClass.RATE_LIMITED:
                data.skipped_reason = f"stopped during round {n + 2}: {url} answered 429"
                return data
    return data


# -- PRF-3 ---------------------------------------------------------------------

def _psi_runs(client: httpx.Client, cfg: CrawlConfig, url: str, fetcher: Fetcher) -> dict[str, Any]:
    runs = []
    for _ in range(cfg.psi_runs):
        run: dict[str, Any] = {"requested_at": utc_now()}
        try:
            response = fetcher.api_request(client, "GET", cfg.psi_endpoint, params={"url": url, "strategy": "mobile", "category": "PERFORMANCE"},
                                           headers={"X-Goog-Api-Key": cfg.google_api_key})  # A26: not in the address
            run["http_status"] = response.status_code
            if response.status_code != 200:
                run["error"] = response.text[:300].replace(cfg.google_api_key or "\0", "redacted")
            else:
                lhr = response.json().get("lighthouseResult") or {}
                # Only these fields are read. lighthouseResult.categories (the 0-100 scores) is never touched.
                run.update(lighthouse_version=lhr.get("lighthouseVersion"), fetch_time=lhr.get("fetchTime"),
                           final_url=lhr.get("finalUrl") or lhr.get("finalDisplayedUrl"),
                           runtime_error=lhr.get("runtimeError"))
                audits = lhr.get("audits") or {}
                run["values"] = {label: (audits.get(audit_id) or {}).get("numericValue")
                                 for audit_id, label in LAB_AUDITS.items()}
        except (httpx.HTTPError, ValueError) as exc:
            run["error"] = type(exc).__name__
        runs.append(run)
    good = [r for r in runs if r.get("values") and not r.get("runtime_error")]
    medians = {}
    for label in LAB_AUDITS.values():
        values = [r["values"][label] for r in good if isinstance(r["values"].get(label), (int, float))]
        medians[label] = {"median": statistics.median(values), "runs": len(values)} if values else \
            {"median": None, "runs": 0, "reason": "not in any successful PSI response"}
    return {"runs": runs, "medians": medians}


def _crux(client: httpx.Client, cfg: CrawlConfig, url: str, fetcher: Fetcher) -> dict[str, Any]:
    out: dict[str, Any] = {}
    parts = urlsplit(url)
    for scope, body in (("url", {"url": url}), ("origin", {"origin": f"{parts.scheme}://{parts.netloc}"})):
        entry: dict[str, Any] = {"scope": scope, "requested_at": utc_now()}
        try:
            response = fetcher.api_request(client, "POST", cfg.crux_endpoint, headers={"X-Goog-Api-Key": cfg.google_api_key},  # A26
                                   json={**body, "metrics": list(FIELD_METRICS)})
            entry["http_status"] = response.status_code
            if response.status_code == 200:
                record = response.json().get("record") or {}
                metrics = record.get("metrics") or {}
                entry["collection_period"] = record.get("collectionPeriod")
                entry["p75"] = {label: ((metrics.get(name) or {}).get("percentiles") or {}).get("p75")
                                for name, label in FIELD_METRICS.items()}
                out = {**entry, "earlier_attempts": out.get("attempts", [])}
                break
            entry["error"] = response.text[:200].replace(cfg.google_api_key or "\0", "redacted")
        except (httpx.HTTPError, ValueError) as exc:
            entry["error"] = type(exc).__name__
        out.setdefault("attempts", []).append(entry)
    return out


def collect_lab_field(result: CrawlResult, cfg: CrawlConfig, fetcher: Fetcher) -> dict[str, Any]:
    base = {"psi_endpoint": cfg.psi_endpoint, "crux_endpoint": cfg.crux_endpoint, "api_key": "redacted",
            "strategy": "mobile", "runs_per_url": cfg.psi_runs}
    if not cfg.google_api_key:
        return {**base, "assessed": False, "reason": "no Google API key ($MAYA_AUDIT_GOOGLE_API_KEY)"}
    readable = {p.url for p in result.pages if p.fetch_class == FetchClass.OK and p.status and 200 <= p.status < 300}
    urls = [u for u in key_page_urls(result, cfg) if u in readable] or [homepage_url(result)]
    urls = urls[: cfg.psi_max_urls]
    access = getattr(result, "access", None)
    verified = bool(access and access.ownership.get("verified"))
    entries = []
    with httpx.Client(timeout=max(cfg.request_timeout_s, 60.0), trust_env=False, transport=PublicTransport(allow_loopback=not cfg.block_loopback,
                          verify=tls_verify(cfg.ca_bundle), before_connect=fetcher.remaining_timeout)) as client:
        for url in urls:
            entry: dict[str, Any] = {"url": url, "field": _crux(client, cfg, url, fetcher)}
            if verified:
                entry["lab"] = _psi_runs(client, cfg, url, fetcher)
            else:
                entry["lab"] = {"assessed": False, "reason": "lab runs make Google's servers load the page with "
                                                             "Lighthouse, so they only run on ownership-verified sites"}
            entries.append(entry)
    return {**base, "assessed": True, "ownership_verified": verified, "urls": entries,
            "urls_not_run": [u for u in key_page_urls(result, cfg) if u in readable][cfg.psi_max_urls:]}


RELIABILITY_DEFINITION = ('PRF-2 counts transport errors and HTTP 5xx among OK/error-class attempts. HTTP 4xx are separate retrieval observations; empty 2xx responses are not transport failures. Blocked/rate-limited requests and persistently failing URLs assigned to IDX-1 are excluded from the rate. Outcome counts include the full native crawl/refetch/PRF history before these exclusions; sitemap probes, browser and provider requests are outside this population.')


def request_outcomes(history):
    """Disjoint observed response classes, independent of PRF-2's rate exclusions."""
    from collections import Counter
    out=Counter()
    for attempts in history.values():
        for a in attempts:
            status=a.get('status')
            if a.get('error') and a.get('fetch_class')=='error':out['transport_failures']+=1
            elif isinstance(status,int) and 400<=status<500:out['http_4xx']+=1
            elif isinstance(status,int) and status>=500:out['http_5xx']+=1
            elif isinstance(status,int) and 200<=status<300 and a.get('bytes')==0:out['empty_2xx']+=1
    return dict(out)
