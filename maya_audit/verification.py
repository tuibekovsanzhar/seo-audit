"""The audit's own second look at its most serious findings, before the report is written (DECISIONS 272).

After every check has run and severities are set, a few findings are asked again on the live site:
    - every High (S2) or Critical (S1) finding, and every Medium (S3) one that rests on an unverified check
      (`launch_gated`), whose rule has a re-test below (`RETESTS`);
    - at most `verification_urls_per_finding` addresses of each, and `verification_max_requests` requests in all;
    - with Maya's own user agent, through a new fetcher with the crawl's pace (never faster than robots.txt's
      Crawl-delay), only where robots.txt allows Maya's token, within `verification_time_s` of its own;
    - where a bot-specific answer is the other explanation (an error page, an empty page), one more request as a browser
      (`probes.BROWSER_USER_AGENT`), recorded beside the result and never deciding it; off with `probes_enabled`.

The result is written to `Finding.verification`:
    {"state": "confirmed" | "changed" | "not_reproduced" | "not_retested", "checked": [one row per request],
     "reason": why it was not retested (only then), "second_client": the browser's answer (when asked)}
"confirmed": every address answered as the finding says; "not_reproduced": none did; "changed": some did, or the
problem took another form (404 became 500). A request that failed (a timeout, a refused connection) is not a verdict:
it is listed and the state is decided by the others, or "not_retested" when none answered.

It never changes a finding's severity, title or scope: a site that answered once and failed once is reported as it was
found, with both answers beside it. A High or Critical finding whose rule has no re-test here, or that the stage did
not reach, says "not_retested" with the reason (DECISIONS 278); that is not a verdict either. Other findings without a
re-test carry no `verification`. The requests come after the integrity gates (INT-*) and are listed in the summary
(`CrawlResult.verification`), not in the crawl's request log.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Any, Callable
from urllib.parse import urljoin

from .analysis import analyze_html
from .classify import classify_fetch, empty_response
from .fetcher import Fetcher
from .html_links import decode_body, extract_link_edges, is_html
from .models import FetchClass

CONFIRMED, CHANGED, NOT_REPRODUCED, NOT_RETESTED = "confirmed", "changed", "not_reproduced", "not_retested"
PURPOSE = "verification"
_SEVERE = ("S1", "S2")


def _get(value: Any, name: str):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _sev(finding) -> str:
    value = _get(finding, "severity")
    return getattr(value, "value", value) or ""


class _Asker:
    """One request per call, counted against the cap; `None` with a reason when it was not sent."""

    def __init__(self, fetcher: Fetcher, cfg, policy, cap: int):
        self.fetcher, self.cfg, self.policy, self.cap = fetcher, cfg, policy, cap
        self.sent = 0
        self.why_not: str | None = None

    def __call__(self, url: str, user_agent: str | None = None, headers: dict | None = None) -> dict | None:
        if self.sent >= self.cap:
            self.why_not = f"the re-test's request cap ({self.cap}) was reached"
            return None
        if self.policy is not None and not self.policy.decide(self.cfg.product_token, url).allowed:
            self.why_not = "robots.txt disallows Maya's user agent"
            return None
        response = self.fetcher.get(url, PURPOSE, self.cfg.max_body_bytes, user_agent=user_agent, extra_headers=headers)
        if response.error == "audit_deadline_skipped":
            self.why_not = "the re-test's time ran out" if not self.fetcher.stopped else "the audit was stopped"
            return None
        self.sent += 1
        content_type = response.headers.get("content-type")
        fetch_class = classify_fetch(response.status, response.headers, response.body, response.error).fetch_class
        ok = fetch_class == FetchClass.OK and bool(response.status) and 200 <= response.status < 300
        row = {"url": url, "client": "browser" if user_agent else "maya", "requested_at": response.started_at,
               "status": response.status, "error": response.error, "fetch_class": fetch_class.value,
               "body_bytes": len(response.body),
               "empty_response": ok and empty_response(response.status, content_type, response.body, response.truncated,
                                                       self.cfg.empty_response_max_bytes)}
        if ok and response.body and is_html(content_type):
            text = decode_body(response.body, content_type)
            row["_analysis"] = analyze_html(text, url)
            row["_links"] = {edge["target"] for edge in extract_link_edges(text, url)}
        if response.status and 300 <= response.status < 400 and response.headers.get("location"):
            row["_location"] = urljoin(url, response.headers["location"])
        return row


# Each re-test: (finding, its addresses, ask) -> rows, each row carrying "outcome": CONFIRMED / NOT_REPRODUCED / CHANGED,
# or None when the answer says nothing (a failed request).

def _client_error(finding, urls, ask, cfg):
    before = {p.get("url"): p.get("status") for p in (_get(finding, "evidence") or {}).get("pages") or []
              if isinstance(p, dict)}
    rows = []
    for url in urls:
        row = ask(url)
        if row is None:
            break
        status = row["status"]
        if status is None:
            row["outcome"] = None
        elif 400 <= status < 500:
            row["outcome"] = CONFIRMED if status == before.get(url) or before.get(url) is None else CHANGED
        elif 200 <= status < 300:
            row["outcome"] = NOT_REPRODUCED
        else:
            row["outcome"] = CHANGED
        rows.append(row)
    return rows


def _follow(url, ask, hops=4):
    """The answer at the end of `url`'s redirects, asked one hop at a time (each hop is a counted request)."""
    row = ask(url)
    while row is not None and row.get("_location") and hops:
        row, hops = ask(row["_location"]), hops - 1
    return row


def _broken_link(finding, urls, ask, cfg):
    """DECISIONS 278: a broken internal link is re-tested where the claim is: the source page still links to the
    address, and that address still ends in a 4xx. Asking the error page alone proves only that an error page is one.
    An address only the sitemap lists is asked as before (`_client_error`)."""
    evidence = _get(finding, "evidence") or {}
    by_source: dict[str, list[dict]] = {}
    for link in evidence.get("link_sources") or []:
        by_source.setdefault(link.get("source"), []).append(link)
    if not by_source:
        return _client_error(finding, urls, ask, cfg)
    rows = []
    for url in urls:
        if url not in by_source:
            # A sitemap entry: the claim is that the listed address ends in a 4xx, through its redirects.
            end = _follow(url, ask)
            if end is None:
                break
            status = end["status"]
            rows.append({**_public(end), "url": url, "target_reached": end["url"], "target_status": status,
                         "outcome": None if status is None else CONFIRMED if 400 <= status < 500
                         else NOT_REPRODUCED if 200 <= status < 300 else CHANGED})
            continue
        page = ask(url)
        if page is None:
            break
        link = by_source[url][0]
        row = {**_public(page), "link": link.get("links_to"), "target": link.get("target")}
        if page["status"] is None or "_links" not in page:
            row["outcome"] = None if page["status"] is None else CHANGED
            rows.append(row)
            continue
        row["link_present"] = link.get("links_to") in page["_links"]
        if not row["link_present"]:
            row["outcome"] = NOT_REPRODUCED
            rows.append(row)
            continue
        end = _follow(link.get("links_to"), ask)
        if end is None:
            rows.append({**row, "outcome": None})
            break
        row.update(target_status=end["status"], target_reached=end["url"])
        status = end["status"]
        row["outcome"] = (None if status is None else CONFIRMED if 400 <= status < 500
                          else NOT_REPRODUCED if 200 <= status < 300 else CHANGED)
        rows.append(row)
    return rows


def _empty(finding, urls, ask, cfg):
    rows = []
    for url in urls:
        row = ask(url)
        if row is None:
            break
        if row["status"] is None:
            row["outcome"] = None
        elif row["empty_response"]:
            row["outcome"] = CONFIRMED
        elif 200 <= row["status"] < 300 and row["fetch_class"] == FetchClass.OK.value:
            row["outcome"] = NOT_REPRODUCED
        else:
            row["outcome"] = CHANGED
        rows.append(row)
    return rows


def _home(finding, urls, ask, cfg, judge: Callable[[dict, Any], str]):
    row = ask(urls[0])
    if row is None:
        return []
    analysis = row.get("_analysis")
    row["outcome"] = judge(analysis, cfg) if analysis else (None if row["status"] is None else CHANGED)
    return [row]


def _organization(analysis, cfg) -> str:
    broken = [b for b in (analysis.get("structured_data") or {}).get("jsonld_blocks") or [] if not b.get("ok")]
    if any("Organization" in (b.get("recovered_types") or []) for b in broken):
        return CONFIRMED
    return CHANGED if broken else NOT_REPRODUCED


def _outline(analysis, cfg) -> str:
    from .checks.structure import questions_not_headings
    visible = [h for h in analysis["headings"] if h["level"] in (2, 3) and h["text"].strip() and not h.get("hidden")]
    thin = len(visible) < cfg.homepage_min_subheadings and (
        analysis["visible_words"] >= cfg.homepage_outline_min_words or questions_not_headings(analysis))
    return CONFIRMED if thin else NOT_REPRODUCED


RETESTS: dict[str, tuple[Callable, bool]] = {
    # rule id: (re-test, whether a browser's answer is worth recording beside it)
    "idx1.4xx.referenced": (_broken_link, True),
    "idx1.4xx.referenced.linked": (_broken_link, True),
    # The engine's own name while the audit runs; the evidence judgments rename it when the report is written
    # (`judgment.empty.*`), which is too late for this stage but kept for a report re-tested from its saved form.
    # No browser request here: the index step already asked a browser (`empty_browser_check`, in the evidence).
    "idx1.empty": (_empty, False),
    "judgment.empty.repeated": (_empty, True),
    "judgment.empty.single": (_empty, True),
    "str3.organization_broken": (lambda f, u, a, c: _home(f, u, a, c, _organization), False),
    "str2.home_outline": (lambda f, u, a, c: _home(f, u, a, c, _outline), False),
}


def in_scope(finding) -> bool:
    if _get(finding, "rule_id") not in RETESTS:
        return False
    sev = _sev(finding)
    return sev in _SEVERE or (sev == "S3" and bool(_get(finding, "launch_gated")))


def _state(rows: list[dict]) -> str:
    outcomes = [r["outcome"] for r in rows if r.get("outcome")]
    if not outcomes:
        return NOT_RETESTED
    if all(o == CONFIRMED for o in outcomes):
        return CONFIRMED
    if all(o == NOT_REPRODUCED for o in outcomes):
        return NOT_REPRODUCED
    return CHANGED


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def run(checks, result, cfg, transport=None, hooks=None, pace_s: float | None = None) -> dict:
    """Re-test the findings in scope and write `verification` on each. Returns the summary for `CrawlResult`.

    Every High or Critical finding leaves with a state (DECISIONS 278): one that was not asked again says so,
    `not_retested`, with the reason (no re-test for its rule, the stage switched off, the cap...). A missing state
    used to look the same as a confirmed one on a client card."""
    summary = _run(checks, result, cfg, transport, hooks, pace_s)
    for check in checks:
        for finding in _get(check, "findings") or []:
            if (in_scope(finding) or _sev(finding) in _SEVERE) and not _get(finding, "verification"):
                reason = (summary.get("reason") if in_scope(finding) and summary.get("reason")
                          else "no re-test for this rule" if not in_scope(finding)
                          else "the re-test did not reach this finding")
                _set(finding, {"state": NOT_RETESTED, "checked": [], "reason": reason,
                               "subjects": list((_get(finding, "scope") or {}).get("urls") or [])})
    return summary


def _run(checks, result, cfg, transport=None, hooks=None, pace_s: float | None = None) -> dict:
    targets = sorted((f for c in checks for f in (_get(c, "findings") or []) if in_scope(f)), key=_sev)
    summary: dict[str, Any] = {"enabled": bool(cfg.verification_enabled), "user_agent": cfg.user_agent,
                               "cap": cfg.verification_max_requests, "requests": 0, "findings": len(targets)}
    if not cfg.verification_enabled:
        summary["reason"] = "switched off (--no-verification)"
        return summary
    if not targets:
        summary["reason"] = "no finding in scope"
        return summary
    if getattr(result, "stopped", False):
        summary["reason"] = "the audit was stopped"
        return summary
    from .index_data import _NO_MORE_REQUESTS
    if result.stop_reason in _NO_MORE_REQUESTS:
        summary["reason"] = f"the crawl stopped early ({result.stop_reason.value}); no extra request was sent"
        return summary
    policy = (getattr(result, "robots_policy_by_origin", None) or {}).get(result.origin)
    if policy is None or policy.stops_requests:
        summary["reason"] = "robots.txt was not read, or asks for nothing more"
        return summary

    from .robots import crawl_delay
    delay = max(pace_s or 0.0, cfg.request_delay_s)
    if policy.robots is not None and crawl_delay(policy.robots, cfg.product_token):
        delay = max(delay, min(crawl_delay(policy.robots, cfg.product_token)[0], cfg.max_crawl_delay_s))
    fetcher = Fetcher(cfg.user_agent, cfg.request_timeout_s, delay, transport, cfg.ca_bundle,
                      block_loopback=cfg.block_loopback)
    fetcher.deadline_mono = time.monotonic() + cfg.verification_time_s
    if hooks is not None and getattr(hooks, "should_stop", None) is not None:
        fetcher.stop_check = hooks.stop_requested
    ask = _Asker(fetcher, cfg, policy, cfg.verification_max_requests)
    from .probes import BROWSER_USER_AGENT, PROBE_HEADERS
    try:
        for finding in targets:
            retest, second = RETESTS[_get(finding, "rule_id")]
            urls = list((_get(finding, "scope") or {}).get("urls") or [])[:cfg.verification_urls_per_finding]
            if not urls:
                continue
            ask.why_not = None
            rows = retest(finding, urls, ask, cfg)
            # `subjects`: what the finding is about, so a re-test of anything else is never called a confirmation.
            record: dict[str, Any] = {"state": _state(rows), "checked": [_public(r) for r in rows],
                                      "subjects": list((_get(finding, "scope") or {}).get("urls") or [])}
            if record["state"] == NOT_RETESTED:
                record["reason"] = ask.why_not or "no request got an answer"
            if second and rows and cfg.probes_enabled:
                other = ask(urls[0], user_agent=BROWSER_USER_AGENT, headers=PROBE_HEADERS)
                if other is not None:
                    record["second_client"] = {k: v for k, v in _public(other).items() if k != "url"}
            _set(finding, record)
    finally:
        fetcher.close()
    summary["requests"] = ask.sent
    summary["states"] = dict(Counter(_get(_get(f, "verification") or {}, "state") for f in targets
                                     if _get(f, "verification")))
    return summary


def _set(finding, record: dict) -> None:
    if isinstance(finding, dict):
        finding["verification"] = record
    else:
        finding.verification = record
