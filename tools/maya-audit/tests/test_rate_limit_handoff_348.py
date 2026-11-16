"""DECISIONS 348: a site that rate-limits Maya's crawler (naturesgarden.net: Retry-After 60 after 6 pages, every run
stopped at 7 pages and Firecrawl read the same 7 of 144 allowed).

Mock transports only; no test waits (Fetcher.sleep is recorded, the reader's retry wait is made tiny) or reaches a
network. A rate-limited shop: / links to /about, /products and /contact; /about answers 429 with a Retry-After.
"""
from __future__ import annotations

import httpx
import pytest

from maya_audit import client_selection, read_sources
from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, reader, settings
from maya_audit.models import StopReason
from test_crawl_order import QUIET
from test_firecrawl import SITE, Firecrawl, client_for, no_lookups  # noqa: F401
from test_rate_limited_start import CF, HTML, audit, site, slept  # noqa: F401


def limited(after: list[tuple[int, int | None]]):
    """/about answers in turn (status, Retry-After), then the last one; every other page is read."""
    asked = []

    def about(request):
        asked.append(request.url.path)
        status, wait = after[min(len(asked), len(after)) - 1]
        if status == 429:
            return httpx.Response(429, headers={**HTML, **CF, **({"retry-after": str(wait)} if wait else {})}, text="x")
        return httpx.Response(200, headers=HTML, text="<html><title>About</title><body><h1>About</h1>"
                                                      + "word " * 300 + "</body></html>")
    handler, _ = site([(200, None)], other=about)
    return handler, asked


# ---------------------------------------------------------------- 3. Retry-After up to 90 s, once per host


def test_a_60_second_retry_after_on_a_later_page_is_waited_once_and_read(slept, no_lookups):
    handler, asked = limited([(429, 60), (200, None)])
    outcome = audit(handler, max_pages=5)
    about = next(p for p in outcome.result.pages if p.url.endswith("/about"))
    assert about.retried_after_429 and slept.count(60.0) == 1 and len(asked) == 2
    assert outcome.result.stop_reason != StopReason.RATE_LIMIT


def test_a_second_long_wait_on_the_host_stops_the_crawl(slept, no_lookups):
    handler, asked = limited([(429, 60), (429, 60)])
    outcome = audit(handler, max_pages=5)
    assert slept.count(60.0) == 1 and len(asked) == 2
    assert outcome.result.stop_reason == StopReason.RATE_LIMIT
    assert outcome.result.stop_detail == ("https://bank.test/about asked Maya to wait 60s (Retry-After) again, after the "
                                          "one long wait of 60s allowed per host; stopped requesting pages")


def test_a_wait_over_90_seconds_still_stops_at_once(slept, no_lookups):
    handler, asked = limited([(429, 91), (200, None)])
    outcome = audit(handler, max_pages=5)
    assert 91.0 not in slept and len(asked) == 1 and outcome.result.stop_reason == StopReason.RATE_LIMIT
    assert "longer than the 90s allowed" in outcome.result.stop_detail
    assert CrawlConfig().long_retry_after_s == 90.0 and CrawlConfig().max_retry_after_s == 30.0


def test_the_stop_message_has_a_wording_pattern_and_a_turkish_form():
    from maya_audit_web import wording
    detail = ("https://naturesgarden.net/collections/all asked Maya to wait 60s (Retry-After) again, after the one long "
              "wait of 60s allowed per host; stopped requesting pages")
    text, _ = wording.term(detail, "tr"), None
    shown = text or wording.line(detail, "tr")[0]
    assert shown and "yine 60 saniye" in shown and "https://naturesgarden.net/collections/all" in shown


# ---------------------------------------------------------------- 2. every planned address goes to the reader


def stopped_audit(slept_list):
    handler, _ = limited([(429, 120)])  # over 90 s: Maya stops at /about
    return audit(handler, max_pages=10)


@pytest.fixture
def quick_retry(monkeypatch):
    monkeypatch.setattr(settings, "RETRY_WAIT_S", 0.01)


def test_after_maya_is_rate_limited_the_needed_reading_takes_every_known_address(tmp_path, slept, no_lookups):
    outcome = stopped_audit(slept)
    assert outcome.result.stop_reason == StopReason.RATE_LIMIT
    own = {p.url for p in outcome.result.pages}
    assert "https://bank.test/products" not in own and "https://bank.test/contact" not in own
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api),
                        Options(read_always=True, max_pages=10, read_scope="needed"))
    # Before (DECISIONS 327's "needed" scope) the reader skipped every address Maya had not asked for.
    assert {"https://bank.test/products", "https://bank.test/contact"} <= set(api.urls)
    assert info["scope"]["mode"] == "all" and info["scope"]["maya_stopped"] == "rate_limit"
    assert info["coverage"]["known_urls_not_requested"] == 0


def test_without_a_stop_the_needed_reading_stays_as_it_was(tmp_path, slept, no_lookups):
    handler, _ = site([(200, None)])
    outcome = audit(handler, max_pages=10)
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api),
                        Options(read_always=True, max_pages=10, read_scope="needed"))
    assert info["scope"]["mode"] == "needed"


def test_firecrawls_own_429_is_asked_once_more_after_a_jittered_wait(tmp_path, slept, no_lookups, quick_retry):
    outcome = stopped_audit(slept)
    refused = []

    def once(body):
        if body["url"] == "https://bank.test/products" and not refused:
            refused.append(body["url"])
            return httpx.Response(429, json={"success": False, "error": "Rate limit exceeded"})
        return None
    api = Firecrawl(SITE, responder=once)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api),
                        Options(read_always=True, max_pages=10, read_scope="needed"))
    assert api.urls.count("https://bank.test/products") == 2
    assert any(r["url"] == "https://bank.test/products" and r["outcome"] == "read" for r in info["pages"])
    assert any(step.get("reason") == "429 from Firecrawl" for step in info["concurrency"]["backed_off"]) or \
        info["concurrency"]["final"] <= info["concurrency"]["start"]


def test_jitter_stays_between_one_and_one_and_a_half():
    values = [reader._jitter() for _ in range(200)]
    assert all(1.0 <= v <= 1.5 for v in values) and len(set(values)) > 1


# ---------------------------------------------------------------- 4. per source: Maya direct and Firecrawl


def test_each_source_says_what_it_read_and_what_refused_it(tmp_path, slept, no_lookups):
    outcome = stopped_audit(slept)

    def blocked(body):
        if body["url"] == "https://bank.test/contact":
            return httpx.Response(200, json={"success": True, "data": {
                "rawHtml": "<html><title>Just a moment...</title><body>Checking your browser</body></html>",
                "metadata": {"statusCode": 403, "url": body["url"]}}})
        return None
    api = Firecrawl(SITE, responder=blocked)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api),
                        Options(read_always=True, max_pages=10, read_scope="needed"))
    from maya_audit.models import to_jsonable
    report = {"crawl": {"pages": [to_jsonable(p) for p in outcome.result.pages], "stop_reason": "rate_limit",
                        "stop_detail": outcome.result.stop_detail}, "firecrawl": info}
    s = read_sources.summary(report)
    assert s["maya"]["rate_limited"] == 1 and s["maya"]["read"] >= 1 and s["maya"]["stopped"] == "rate_limit"
    assert s["reader"]["used"] and s["reader"]["read"] >= 2 and s["reader"]["read"] + s["reader"]["blocked"] + \
        s["reader"]["other"] + s["reader"]["rate_limited"] == s["reader"]["asked"]
    tr = read_sources.lines(s, "tr")
    assert tr[0].startswith("Maya'nın doğrudan tarayıcısı:") and "hız sınırında durdu" in tr[0]
    assert tr[1].startswith("Firecrawl:")


def test_the_naturesgarden_shape_is_said_per_source():
    pages = [{"url": f"https://n.test/p{i}", "status": 200, "fetch_class": "ok"} for i in range(6)]
    pages.append({"url": "https://n.test/collections/all", "status": 429, "fetch_class": "rate_limited"})
    rows = [{"url": f"https://n.test/p{i}", "outcome": "read", "status": 200} for i in range(7)]
    report = {"crawl": {"pages": pages, "stop_reason": "rate_limit", "stop_detail": "x"},
              "firecrawl": {"enabled": True, "used": True, "pages": rows, "coverage": {"known_urls_not_requested": 0}}}
    s = read_sources.summary(report)
    assert read_sources.lines(s, "tr") == [
        "Maya'nın doğrudan tarayıcısı: 7 sayfa isteği, 6 okundu, 0 engel sayfası, 1 × 429 (hız sınırında durdu).",
        "Firecrawl: 7 sayfa isteği, 7 okundu, 0 engel sayfası, 0 × 429."]
    assert read_sources.lines(s, "en")[1] == "Firecrawl: 7 page requests, 7 read, 0 block pages, 0 × 429."
    cov = client_selection.coverage(report, [])
    assert cov["lines"][0]["kind"] == "sources"
    from maya_audit.client_appendix import coverage_text
    assert coverage_text(cov["lines"][0], "tr").startswith("Maya'nın doğrudan tarayıcısı: 7 sayfa isteği")


def test_a_reader_that_was_not_used_says_so():
    report = {"crawl": {"pages": [{"url": "https://n.test/", "status": 200, "fetch_class": "ok"}]}, "firecrawl": {}}
    assert read_sources.lines(read_sources.summary(report), "en")[1] == "Firecrawl: not used."
