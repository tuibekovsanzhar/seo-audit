"""DECISIONS 286: a start page answered with 429 is waited out once (Retry-After up to 120 s), and when still nothing
was read, the homepage alone is asked for through Firecrawl's basic reader. Mock transports; no test waits or reaches
a network (Fetcher.sleep is recorded, not slept)."""
from __future__ import annotations

import httpx
import pytest

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.fetcher import Fetcher
from maya_audit import maya_blocked
from maya_audit.firecrawl import Options, panel, reader
from maya_audit.models import FetchClass, StopReason
from test_crawl_order import QUIET
from test_firecrawl import SITE, Firecrawl, client_for, doc, TEXT, no_lookups  # noqa: F401

HTML = {"content-type": "text/html; charset=utf-8"}
ROBOTS = "User-agent: *\nDisallow: /private/\n"
CF = {"server": "cloudflare", "cf-ray": "a5-IST"}


@pytest.fixture
def slept(monkeypatch):
    waits = []

    def fake(self, seconds):
        waits.append(seconds)
        return True
    monkeypatch.setattr(Fetcher, "sleep", fake)
    return waits


def site(home_answers, *, other=None):
    """bank.test: robots allows all; the homepage gives `home_answers` in turn (status, retry_after), then the last one."""
    asked = []

    def handler(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS, headers={"content-type": "text/plain"})
        if path == "/":
            asked.append(path)
            status, wait = home_answers[min(len(asked), len(home_answers)) - 1]
            if status == 429:
                return httpx.Response(429, headers={**HTML, **CF, **({"retry-after": str(wait)} if wait else {})},
                                      text="<html><title>Too many requests</title></html>")
            return httpx.Response(200, headers=HTML, text=doc("Bank", "<h1>Bank</h1>" + TEXT + '<a href="/about">About</a>'))
        if path == "/about" and other:
            return other(request)
        if path == "/about":
            return httpx.Response(200, headers=HTML, text=doc("About", "<h1>About</h1>" + TEXT))
        return httpx.Response(404, headers=HTML, text="<title>x</title>")
    return handler, asked


def home_requests(outcome):
    """The crawler's own page requests for the homepage (other steps ask for "/" too: redirect and http checks)."""
    return [q for q in outcome.result.requests if q.purpose == "page" and q.url == "https://bank.test/"]


def audit(handler, **cfg):
    return run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 5, **cfg}), httpx.MockTransport(handler))


# ------------------------------------------------------------------ the crawler's one longer wait


def test_a_start_page_429_with_a_60_second_retry_after_is_waited_once_and_read(slept, no_lookups):
    handler, asked = site([(429, 60), (200, None)])
    outcome = audit(handler)
    home = outcome.result.pages[0]
    assert home.fetch_class == FetchClass.OK and home.retried_after_429 and slept.count(60.0) == 1
    assert [a["status"] for a in home._attempts] == [429, 200]
    assert home._attempts[0]["retry_after_s"] == 60.0 and home._attempts[0]["waited_s"] == 60.0
    assert home._attempts[0]["server"] == "cloudflare" and home._attempts[0]["cf_ray"] == "a5-IST"
    # The report keeps both, as evidence lines of the page (its 1.20 shape unchanged).
    from maya_audit.models import to_jsonable
    lines = [x for x in to_jsonable(home)["classification_evidence"] if x.startswith("attempt ")]
    assert lines[0].startswith("attempt 1: status 429, Retry-After 60 s, server cloudflare, cf-ray a5-IST at ")
    assert lines[0].endswith("waited 60 s and asked once more") and lines[1].startswith("attempt 2: status 200 at ")
    assert "_attempts" not in to_jsonable(home)
    assert outcome.result.stop_reason != StopReason.RATE_LIMIT and len(home_requests(outcome)) == 2


def test_the_wait_is_once_a_second_429_stops_the_crawl_with_both_attempts_recorded(slept, no_lookups):
    handler, asked = site([(429, 60), (429, 60)])
    outcome = audit(handler)
    home = outcome.result.pages[0]
    assert len(home_requests(outcome)) == 2 and slept.count(60.0) == 1
    assert outcome.result.stop_reason == StopReason.RATE_LIMIT
    assert [a["status"] for a in home._attempts] == [429, 429]


@pytest.mark.parametrize("wait, retried", [(120, True), (121, False)])
def test_the_start_page_cap_is_120_seconds(slept, no_lookups, wait, retried):
    handler, asked = site([(429, wait), (200, None)])
    outcome = audit(handler)
    assert (len(home_requests(outcome)) == 2) is retried and outcome.result.pages[0].retried_after_429 is retried
    if not retried:
        assert outcome.result.stop_reason == StopReason.RATE_LIMIT and outcome.result.pages[0]._attempts == []


def test_a_later_page_keeps_the_30_second_cap(slept, no_lookups):
    """Counter-example: only the start page waits longer; any other page asking for 60 s still stops the crawl."""
    handler, _ = site([(200, None)], other=lambda r: httpx.Response(429, headers={**HTML, "retry-after": "60"}, text="x"))
    outcome = audit(handler)
    about = next(p for p in outcome.result.pages if p.url.endswith("/about"))
    assert not about.retried_after_429 and 60.0 not in slept
    assert outcome.result.stop_reason == StopReason.RATE_LIMIT


# ------------------------------------------------------------------ the homepage through Firecrawl's basic reader


def rate_limited_audit(slept):
    handler, _ = site([(429, 60), (429, 60)])
    return audit(handler, max_pages=10)


def after_of(info):
    """DECISIONS 289: what the reader did after Maya's crawler was rate-limited."""
    return info["crawl_blocked"]["after_rate_limit"]


def plain_rate_limited_audit():
    """Every request refused with 429, robots.txt too: a plain rate limit, not a block on Maya's crawler's pages."""
    handler, _ = site([(429, 60), (429, 60)])

    def everything_429(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(429, headers={**HTML, "retry-after": "60"}, text="x")
        return handler(request)
    return audit(everything_429, max_pages=10)


def test_blocked_on_pages_the_reader_goes_on_with_the_basic_proxy_and_no_tick(tmp_path, slept, no_lookups):
    """DECISIONS 288 (changed 2026-10-30): 429 on pages while robots.txt is served. No owner's approval is needed for the
    basic proxy: the reader reads on as the page reader, within robots.txt."""
    outcome = rate_limited_audit(slept)
    api = Firecrawl(SITE)
    client = client_for(tmp_path, api)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client, Options(read_always=True, max_pages=10))
    after = after_of(info)
    assert after["read"] and after["pages_read"] >= 2 and after["proxy"] == "basic"
    assert after["owner_approved_bypass"] is False and after["maya_blocked"] == maya_blocked.LABEL
    assert {b["proxy"] for b in api.bodies} == {"basic"} and "https://bank.test/about" in api.urls
    assert "https://bank.test/private/accounts" not in api.urls  # robots.txt disallows it
    assert info["purpose"] == reader.MAIN_PURPOSE and info["used"]
    # ACC-9 keeps its own finding, with the AI-crawler warning: not rewritten into a challenge note.
    [acc9] = [f for c in outcome.checks if c.check_id == "ACC-9" for f in c.findings]
    assert acc9.rule_id == "acc9.blocked_429"
    assert panel.section(info)["crawl_blocked"]["after_rate_limit"] == after  # saved with the report


def test_the_stronger_proxy_is_used_only_with_the_owners_approval(tmp_path, slept, no_lookups):
    outcome = rate_limited_audit(slept)
    api = Firecrawl(SITE)
    client = client_for(tmp_path, api, proxy="enhanced", owner_approved_bypass=True)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client,
                        Options(read_always=True, max_pages=10, proxy="enhanced", owner_approved_bypass=True))
    assert after_of(info)["proxy"] == "enhanced" and after_of(info)["owner_approved_bypass"] is True
    assert Options(proxy="enhanced").problem()  # without the tick the plan refuses it before any request


def test_a_site_whose_robots_txt_cannot_be_read_gets_no_reader_request(tmp_path, slept, no_lookups):
    """robots.txt refused too: the reader goes on as on any audit, and asks for nothing robots.txt has not allowed."""
    outcome = plain_rate_limited_audit()
    assert not maya_blocked.holds(outcome.result)
    api = Firecrawl(SITE)
    reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options(read_always=True, max_pages=10))
    assert [url for url in api.urls if not url.endswith("/robots.txt")] == []


def test_a_saved_homepage_only_read_is_named_by_the_crawl_record(tmp_path, slept, no_lookups):
    """A report written before the reader read on says "homepage only, after the site rate-limited Maya's crawler" and
    has no fallback record (286 dropped it). Shown with the block's name when its crawl record shows 429 on pages while
    robots.txt was served; without the crawl record it is left as written."""
    outcome = rate_limited_audit(slept)
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options(read_always=True, max_pages=10))
    saved = {**info, "purpose": reader.HOMEPAGE_FALLBACK_PURPOSE,
             "crawl_blocked": {k: v for k, v in info["crawl_blocked"].items() if k != "homepage_fallback"}}
    assert any("Used as: homepage only, after Maya's crawler was blocked (429 on pages)." in line
               for line in panel.summary_lines(saved, outcome.result))
    assert any("Used as: homepage only, after the site rate-limited Maya's crawler." in line for line in panel.summary_lines(saved))


def test_a_homepage_the_reader_cannot_read_either_is_said_so(tmp_path, slept, no_lookups):
    outcome = rate_limited_audit(slept)
    api = Firecrawl({})  # every page answers 404 through the reader
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api),
                        Options(read_always=True, max_pages=10))
    assert after_of(info)["read"] is False and after_of(info)["pages_read"] == 0 and not info["used"]


def test_a_site_that_rate_limited_after_a_page_was_read_is_read_on_through_the_reader(tmp_path, slept, no_lookups):
    """DECISIONS 289, nihan.com.tr (2026-10-30): the homepage answered 200, the next page 429 with Retry-After: 60, and
    Maya's crawl stopped. Maya stops its own page requests; the reader reads the other pages up to the cap."""
    handler, _ = site([(200, None)], other=lambda r: httpx.Response(429, headers={**HTML, **CF, "retry-after": "60"}, text="x"))
    outcome = audit(handler, max_pages=10)
    assert outcome.result.stop_reason == StopReason.RATE_LIMIT and not maya_blocked.holds(outcome.result)
    own = [p.url for p in outcome.result.pages]
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options(read_always=True, max_pages=10))
    assert info["used"] and info["purpose"] == reader.MAIN_PURPOSE and info["pages_read"] >= 3
    assert "https://bank.test/contact" in api.urls and {b["proxy"] for b in api.bodies} == {"basic"}
    assert "https://bank.test/private/accounts" not in api.urls  # robots.txt
    after = after_of(info)
    assert after["read"] and after["maya_blocked"] is None and after["maya_stopped"].startswith("https://bank.test/about asked Maya")
    assert [p.url for p in outcome.result.pages] == own  # Maya's own crawl record is unchanged: it sent no new request
    # The rate limit stays on record as the reader's note (ACC-9), not a headline.
    [acc9] = [f for c in outcome.checks if c.check_id == "ACC-9" for f in c.findings]
    assert "rate-limited Maya's direct crawler on 1 of 2 request(s)" in acc9.title and acc9.severity.value == "Info"


def test_without_a_reader_a_rate_limit_still_stops_the_audit_as_before(slept, no_lookups):
    """Firecrawl off: nothing changes. Maya stops, and the pages read are the one Maya read."""
    from maya_audit.report import pages_shown
    handler, _ = site([(200, None)], other=lambda r: httpx.Response(429, headers={**HTML, "retry-after": "60"}, text="x"))
    outcome = audit(handler, max_pages=10)
    assert outcome.result.stop_reason == StopReason.RATE_LIMIT
    # DECISIONS 289 (3): one number for "pages read for content": the refused page is not one (it said 2).
    assert pages_shown(outcome.result) == 1


# ------------------------------------------------------------------ DECISIONS 288: named, worded, gated


def test_the_crawl_and_acc9_name_the_block_on_mayas_crawler(slept, no_lookups):
    outcome = rate_limited_audit(slept)
    assert maya_blocked.holds(outcome.result)
    assert outcome.result.stop_detail.startswith("blocked for Maya's crawler (429 on pages): ")
    [finding] = next(c for c in outcome.checks if c.check_id == "ACC-9").findings
    assert finding.rule_id == "acc9.blocked_429" and finding.title.startswith("Maya's crawler blocked (429 on pages): Cloudflare answered")
    assert "AI crawlers may get the same treatment" in finding.how_to_fix and finding.evidence["maya_blocked"] == maya_blocked.LABEL


def test_a_site_whose_files_are_refused_too_keeps_the_general_wording(slept, no_lookups):
    handler, _ = site([(429, 60), (429, 60)])

    def everything_429(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(429, headers={**HTML, "retry-after": "60"}, text="x")
        return handler(request)
    outcome = audit(everything_429, max_pages=10)
    acc9 = next(c for c in outcome.checks if c.check_id == "ACC-9")
    assert not any(f.rule_id == "acc9.blocked_429" for f in acc9.findings)
    assert not (outcome.result.stop_detail or "").startswith(maya_blocked.LABEL)


def test_the_turkish_wording_says_mayas_crawler_was_blocked():
    from maya_audit.checks.access import FIX_429
    from maya_audit_web import wording
    title = ("Maya's crawler blocked (429 on pages): Cloudflare answered 2 of 2 page request(s) with 429 while robots.txt "
             "and the sitemap were served. AI crawlers may get the same treatment")
    shown, ok = wording.title("ACC-9", title, "tr")
    assert ok and shown.startswith("Maya'nın tarayıcısı engellendi (sayfalarda 429): Cloudflare")
    assert "Yapay zekâ tarayıcıları da aynı muameleyi görebilir" in shown
    fix, ok = wording.fix(FIX_429.format(who="Cloudflare", token="Maya-Audit"), "tr")
    assert ok and "bot ve hız sınırı kurallarını" in fix
    stop, ok = wording.reason("rate_limit: blocked for Maya's crawler (429 on pages): https://bank.test/ asked Maya to wait "
                              "60s (Retry-After), longer than the 30s allowed; stopped requesting pages", "tr")
    assert ok and "Maya'nın tarayıcısı engellendi (sayfalarda 429)" in stop and "rate" not in stop


def test_the_gate_drafts_only_a_report_with_nothing_read():
    """DECISIONS 288 (changed): pages read through a reader are pages read; only 0 pages read is a draft."""
    from maya_audit import release_gate
    one_page = {"checks": [], "audit_status": {"content_coverage": {"pages_read": 1}},
                "firecrawl": {"crawl_blocked": {"homepage_fallback": {"continued": False, "maya_blocked": maya_blocked.LABEL}}}}
    none = {"checks": [], "audit_status": {"content_coverage": {"pages_read": 0}}}
    assert not [v for v in release_gate.check_report(one_page) if v["rule"] == "RG-14"]
    assert [v["hard"] for v in release_gate.check_report(none) if v["rule"] == "RG-14"] == [True]
