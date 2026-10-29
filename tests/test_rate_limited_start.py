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
ROBOTS = "User-agent: *\nAllow: /\n"
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


def fallback_of(info):
    return info["crawl_blocked"]["homepage_fallback"]


def test_with_nothing_read_the_homepage_alone_is_asked_for_through_the_basic_reader(tmp_path, slept, no_lookups):
    outcome = rate_limited_audit(slept)
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api),
                        Options(read_always=True, max_pages=10))
    assert api.urls == ["https://bank.test/"]  # one page, no robots.txt (Maya's policy is used), no sitemap
    assert api.bodies[0]["proxy"] == "basic"
    fallback = fallback_of(info)
    assert fallback["read"] and fallback["proxy"] == "basic" and fallback["owner_approved_bypass"] is False
    assert fallback["continued"] is False and fallback["maya_blocked"] == maya_blocked.LABEL
    assert info["used"] and "STR-1" in info["checks_from_firecrawl"]
    # DECISIONS 288: the record reaches the saved report (inside `crawl_blocked`, one of the section's own keys).
    assert panel.section(info)["crawl_blocked"]["homepage_fallback"] == fallback


def test_without_the_owners_approval_the_bypass_is_never_used(tmp_path, slept, no_lookups):
    """The plan chose the enhanced proxy but nobody ticked the owner's approval: homepage only, basic."""
    outcome = rate_limited_audit(slept)
    api = Firecrawl(SITE)
    client = client_for(tmp_path, api)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client,
                        Options(read_always=True, max_pages=10, owner_approved_bypass=False))
    assert [b["proxy"] for b in api.bodies] == ["basic"] and fallback_of(info)["continued"] is False


def test_with_the_owners_approval_the_reader_goes_on_past_the_homepage(tmp_path, slept, no_lookups):
    """DECISIONS 288: 429 on pages while robots.txt is served, and the owner approved bypassing bot protection."""
    outcome = rate_limited_audit(slept)
    api = Firecrawl(SITE)
    client = client_for(tmp_path, api, proxy="enhanced", owner_approved_bypass=True)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client,
                        Options(read_always=True, max_pages=10, proxy="enhanced", owner_approved_bypass=True))
    fallback = fallback_of(info)
    assert fallback["continued"] is True and fallback["read"] and fallback["proxy"] == "enhanced"
    assert len(api.urls) > 1 and "https://bank.test/about" in api.urls  # the site's other pages, not the homepage alone
    assert info["purpose"] == reader.CONTINUED_PURPOSE
    assert client.proxy == "enhanced"


def test_approval_does_not_reach_past_a_plain_rate_limit(tmp_path, slept, no_lookups):
    """Counter-example: robots.txt refused too, so it is not "429 on pages while the files are served"; even with the
    owner's approval the reader stops at the homepage."""
    handler, _ = site([(429, 60), (429, 60)])

    def everything_429(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(429, headers={**HTML, "retry-after": "60"}, text="x")
        return handler(request)
    outcome = audit(everything_429, max_pages=10)
    assert not maya_blocked.holds(outcome.result)
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api, proxy="enhanced", owner_approved_bypass=True),
                        Options(read_always=True, max_pages=10, proxy="enhanced", owner_approved_bypass=True))
    assert len(api.bodies) <= 1  # the homepage at most, whatever stopped the crawl
    fallback = (info.get("crawl_blocked") or {}).get("homepage_fallback")
    assert fallback is None or fallback["continued"] is False


def test_a_homepage_the_reader_cannot_read_either_is_said_so(tmp_path, slept, no_lookups):
    outcome = rate_limited_audit(slept)
    api = Firecrawl({})  # every page answers 404 through the reader
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api),
                        Options(read_always=True, max_pages=10))
    assert len(api.bodies) == 1 and fallback_of(info)["read"] is False and not info["used"]
    assert "could not read it" in info["reason"]


def test_a_site_that_rate_limited_after_pages_were_read_is_not_asked_again(tmp_path, slept, no_lookups):
    """DECISIONS 52 still holds once anything was read: no reader request after a rate limit."""
    handler, _ = site([(200, None)], other=lambda r: httpx.Response(429, headers={**HTML, "retry-after": "600"}, text="x"))
    outcome = audit(handler, max_pages=10)
    assert outcome.result.stop_reason == StopReason.RATE_LIMIT
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api),
                        Options(read_always=True, max_pages=10))
    assert api.bodies == [] and "homepage_fallback" not in info.get("crawl_blocked", {}) and "rate-limited Maya's crawler" in info["reason"]


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


def test_the_gate_keeps_a_homepage_only_read_as_a_draft_and_lets_an_approved_one_through():
    from maya_audit import release_gate
    base = {"checks": [], "audit_status": {"content_coverage": {"pages_read": 1}}}
    stopped = {**base, "firecrawl": {"crawl_blocked": {"homepage_fallback": {"continued": False, "maya_blocked": maya_blocked.LABEL}}}}
    went_on = {**base, "firecrawl": {"crawl_blocked": {"homepage_fallback": {"continued": True, "maya_blocked": maya_blocked.LABEL}}}}
    [v] = [v for v in release_gate.check_report(stopped) if v["rule"] == "RG-14"]
    assert v["hard"] and v["message"].startswith("site content could not be read: blocked for Maya's crawler (429 on pages)")
    assert not [v for v in release_gate.check_report(went_on) if v["rule"] == "RG-14"]
