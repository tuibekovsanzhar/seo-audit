"""Phase 1B: one deadline, one stop request and one pace for every step of an audit.

Clocks are fake and every provider is a mock transport: no test waits in real time or reaches a network.
"""
import json

import httpx
import pytest

from maya_audit import crux
from maya_audit.config import CrawlConfig
from maya_audit.dataforseo import DataForSEOClient, DataForSEOError, Ledger, pricing
from maya_audit.dataforseo import client as dfs_client
from maya_audit.dataforseo.cache import CACHE_NAME, Cache
from maya_audit.dataforseo.credentials import Credentials
from maya_audit.dataforseo.ledger import LEDGER_NAME
from maya_audit.firecrawl import Options, panel, reader
from maya_audit.firecrawl.client import Stopped
from maya_audit.models import StopReason
from maya_audit.report import build_report, duration_line, run_outcome
from maya_audit.runclock import OUT_OF_TIME, STOPPED, RunClock, for_outcome, reader_allowance_s
from test_firecrawl import SITE, Firecrawl, blocked_audit, client_for, no_lookups  # noqa: F401
from test_review_fixes import QUIET

CFG = CrawlConfig(**{**QUIET, "max_pages": 10})
MAIN = Options(read_always=True, max_pages=10)


class FakeTime:
    """A clock that only moves when something sleeps or a test moves it."""

    def __init__(self, now=1000.0):
        self.now, self.slept = now, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def clocked(time, **more):
    return RunClock(clock=time.clock, sleep=time.sleep, started_mono=time.now, **more)


def test_the_clock_refuses_after_the_deadline_or_a_stop_and_caps_a_request_by_the_time_left():
    time = FakeTime()
    asked = {"stop": False}
    clock = clocked(time, deadline_mono=time.now + 60, should_stop=lambda: asked["stop"])
    assert clock.why_not() is None and clock.timeout(90) == 60 and clock.timeout(20) == 20
    time.now += 58
    assert clock.why_not() is None and clock.why_not(5) == OUT_OF_TIME and clock.timeout(90) == 2
    time.now += 5
    assert clock.why_not() == OUT_OF_TIME and clock.timeout(90) == 0
    asked["stop"] = True
    assert clock.why_not() == STOPPED  # a stop is said as a stop, even when time has also run out
    assert RunClock().why_not() is None and RunClock().timeout(90) == 90 and reader_allowance_s(50, 1.0) == 450.0


def test_requests_to_the_site_wait_their_turn_and_a_stop_during_the_wait_sends_nothing():
    time = FakeTime()
    clock = clocked(time, pace_s=3.0)
    assert clock.wait_for_turn() is None and time.slept == []  # the first request does not wait
    clock.site_was_asked()
    time.now += 1.0
    assert clock.wait_for_turn() is None and round(sum(time.slept), 3) == 2.0  # the rest of the gap, no more
    clock.site_was_asked()
    stop = {"now": False}
    clock.should_stop = lambda: stop["now"]
    real_sleep = time.sleep
    time.sleep = lambda seconds: (real_sleep(seconds), stop.update(now=True))[0]
    clock.sleep = time.sleep
    assert clock.wait_for_turn() == STOPPED


def test_a_deadline_reached_before_the_reader_sends_no_provider_request_and_spends_nothing(tmp_path, no_lookups):
    outcome = blocked_audit()
    api = Firecrawl(SITE)
    client = client_for(tmp_path, api)
    time = FakeTime()
    client.clock = clocked(time, deadline_mono=time.now - 1)  # the audit's time limit has already passed
    info = reader.apply(outcome, CFG, client, MAIN)
    section = panel.section(info)
    assert api.bodies == [] and client.requests_sent == 0 and client.ledger.spent_today() == 0 and client.calls == []
    assert not section["used"] and section["reason"] == f"Firecrawl was not started: {OUT_OF_TIME}" and section["stopped_because"] == OUT_OF_TIME
    assert run_outcome(outcome.result, outcome.gates, section)[1] == "DEGRADED"  # nothing was read, and the block stands
    assert [f.severity.value for c in outcome.checks if c.check_id == "ACC-9" for f in c.findings] == ["S3"]  # untouched


def test_the_audits_own_deadline_reaches_a_reader_made_before_the_crawl(tmp_path, no_lookups):
    outcome = blocked_audit()
    assert outcome.deadline_mono is not None and outcome.pace_s == CFG.request_delay_s and outcome.started_mono is not None
    outcome.deadline_mono = 1.0  # long past, on the monotonic clock
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CFG, client_for(tmp_path, api), MAIN)  # the client has no deadline of its own
    assert api.bodies == [] and "time limit was reached" in info["reason"]
    assert for_outcome(outcome).deadline_mono == 1.0 and for_outcome(outcome).why_not() == OUT_OF_TIME


def test_a_stop_between_provider_pages_sends_no_next_request_and_keeps_what_was_read(tmp_path, no_lookups):
    outcome = blocked_audit()
    api = Firecrawl(SITE)
    client = client_for(tmp_path, api)
    seen = []
    client.clock = RunClock(should_stop=lambda: len(api.bodies) >= 2)  # stop asked for once two pages were requested

    info = reader.apply(outcome, CFG, client, MAIN, progress=seen.append)
    section = panel.section(info)
    assert len(api.bodies) == 2 and section["pages_read"] == 2 and section["used"]
    assert section["stopped_because"].startswith(STOPPED) and not [row for row in section["pages"] if row["outcome"] == "failed"]
    assert client.ledger.spent_today() == 4  # two pages, two credits each: nothing reserved for a third
    code, word, sentence = run_outcome(outcome.result, outcome.gates, section)
    assert (code, word) == (3, "INCOMPLETE") and "reading stopped early" in sentence
    assert [event["attempted"] for event in seen] == [1, 2] and seen[-1]["read"] == 1 and seen[-1]["page_cap"] == 10
    report = build_report(outcome.result, outcome.gates, outcome.checks, firecrawl=section, all_phases_s=12.3456)
    assert report["audit_status"]["content_coverage"]["level"] == "partial"  # the partial report is still built
    assert report["audit_status"]["timing"]["all_phases_s"] == 12.346 and report["audit_status"]["timing"]["page_reader_s"] is not None


def test_provider_requests_keep_mayas_pace_and_cached_pages_do_not_wait(tmp_path, no_lookups):
    outcome = blocked_audit()
    outcome.pace_s = 2.0  # as if a robots.txt Crawl-delay or a rate limit had widened Maya's own gap
    api = Firecrawl(SITE)
    time = FakeTime()
    client = client_for(tmp_path, api, audit_id="run-one")
    client.clock = clocked(time)
    reader.apply(outcome, CFG, client, MAIN)
    assert len(api.bodies) == 5 and client.clock.pace_s == 2.0
    assert round(sum(time.slept), 3) == 8.0  # four gaps of two seconds between five requests; the first did not wait
    again_time = FakeTime()
    again = client_for(tmp_path, api, audit_id="run-one")  # the same audit: a new one reads again (A16, W1)
    again.clock = clocked(again_time)
    reader.apply(blocked_audit(), CFG, again, MAIN)
    assert len(api.bodies) == 5 and again_time.slept == [] and again.requests_sent == 0  # served from Maya's own copies


def test_a_site_that_rate_limited_maya_before_any_page_is_asked_for_its_homepage_only(tmp_path, no_lookups):
    """DECISIONS 52, narrowed by 286: nothing at all was read, so the homepage alone is asked for once through the
    basic reader; the site's other pages are not (the rest stays in `tests/test_rate_limited_start.py`)."""
    outcome = blocked_audit()
    outcome.result.stop_reason = StopReason.RATE_LIMIT
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CFG, client_for(tmp_path, api), MAIN)
    assert api.urls == ["https://bank.test/"] and info["homepage_fallback"]["read"]


def test_a_request_is_never_started_with_too_little_time_left_and_its_timeout_fits_what_is_left(tmp_path, no_lookups):
    api = Firecrawl(SITE)
    time = FakeTime()
    client = client_for(tmp_path, api)
    client.clock = clocked(time, deadline_mono=time.now + 30)
    client.scrape("https://bank.test/")
    assert api.bodies[0]["timeout"] == 25000  # the provider's own limit sits inside the 30 seconds left, not the usual 85
    time.now += 27  # three seconds left: an answer could not be read in time
    with pytest.raises(Stopped, match="time limit was reached; no further Firecrawl request was sent"):
        client.scrape("https://bank.test/about")
    assert len(api.bodies) == 1 and client.ledger.spent_today() == 2


def test_a_slow_request_that_is_cut_off_is_possibly_billed_and_no_second_one_starts(tmp_path, no_lookups):
    from maya_audit.firecrawl import PossiblyBilled
    sent = []

    def slow(request):
        sent.append(1)
        raise httpx.ReadTimeout("no answer in time")
    outcome = blocked_audit()
    client = client_for(tmp_path, Firecrawl(SITE))
    client._http = httpx.Client(base_url="https://api.firecrawl.dev", transport=httpx.MockTransport(slow))
    info = reader.apply(outcome, CFG, client, MAIN)
    assert len(sent) == 1 and client.ledger.spent_today() == 2  # the reservation stays: it may have been charged
    assert client.calls[0]["billing_status"] == "possibly_billed" and "may have been charged" in info["stopped_because"]
    assert issubclass(PossiblyBilled, Exception)


def paid(tmp_path, transport, **more):
    return DataForSEOClient(Credentials("login", "password-made-up"), Ledger(tmp_path / LEDGER_NAME), Cache(tmp_path / CACHE_NAME),
                            daily_budget=5.0, approved_usd=5.0, approved_always_ask=True, transport=transport, **more)


def test_the_paid_panels_send_nothing_after_the_deadline_and_retry_only_what_was_never_sent(tmp_path, monkeypatch):
    import time as real_time
    monkeypatch.setattr(dfs_client, "RETRY_WAIT_S", 0)
    sent = []

    def ok(request):
        sent.append(request.url.path)
        return httpx.Response(200, json={"status_code": 20000, "tasks": [{"status_code": 20000, "cost": 0.02, "result": [{}]}]})
    late = paid(tmp_path, httpx.MockTransport(ok), deadline_mono=real_time.monotonic() - 1)
    with pytest.raises(DataForSEOError, match="deadline reached; no further request sent"):
        late.request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}])
    assert sent == [] and late.ledger.spent_today() == 0
    stopped = paid(tmp_path / "s", httpx.MockTransport(ok), should_stop=lambda: True)
    with pytest.raises(DataForSEOError, match="stopped on request"):
        stopped.request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}])
    assert sent == []
    # Definitely not sent (no connection): tried once more, then reported. Sent and unanswered: never repeated.
    tries = []

    def refused(request):
        tries.append("refused")
        raise httpx.ConnectError("refused")
    with pytest.raises(DataForSEOError, match="in 2 attempts"):
        paid(tmp_path / "r", httpx.MockTransport(refused)).request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}])

    def silent(request):
        tries.append("silent")
        raise httpx.ReadTimeout("no answer")
    unanswered = paid(tmp_path / "t", httpx.MockTransport(silent))
    with pytest.raises(DataForSEOError, match="may have been billed"):
        unanswered.request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}])
    assert tries == ["refused", "refused", "silent"] and unanswered.ledger.spent_today() > 0  # kept reserved


def test_core_web_vitals_and_the_archives_do_not_start_after_the_deadline(no_lookups):
    from maya_audit import archives
    time = FakeTime()
    late = clocked(time, deadline_mono=time.now - 1)
    asked = httpx.MockTransport(lambda request: pytest.fail("no request after the deadline"))
    answer = crux.collect("https://shop.test/", "made-up-key", transport=asked, clock=late)
    assert answer["status"] == "not_available" and "time limit was reached before Google was asked" in answer["summary"]
    section = archives.collect(blocked_audit().result, CFG, wayback=True, transport=asked, sleep=lambda s: None, clock=late)
    assert section["requests_sent"] == 0 and section["sources"][0]["pages_read"] == 0


def test_the_report_says_the_whole_jobs_time_not_only_the_crawls():
    from types import SimpleNamespace
    result = SimpleNamespace(elapsed_s=41.2)
    assert duration_line(result, None) == "**Duration:** 41.2 seconds for Maya's own crawl and checks (a page reader and paid panels, when used, run after it)"
    assert duration_line(result, 187.44) == "**Duration:** 41.2 seconds for Maya's own crawl and checks; 187.4 seconds for the whole audit, every step included"


def test_in_the_web_app_a_spent_time_limit_stops_the_reader_before_it_spends_and_the_whole_job_time_is_reported(tmp_path):
    pytest.importorskip("fastapi")
    from test_web_app import API, Site, cloudflare, get, plan, start
    from test_web_app import web as web_fixture  # noqa: F401
    from test_web_firecrawl import PAGES, services
    import test_web_app

    made = []
    factory = test_web_app.web.__wrapped__(tmp_path) if hasattr(test_web_app.web, "__wrapped__") else None
    assert factory is not None
    make = next(factory)
    try:
        api = Firecrawl(PAGES)
        client = make(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
        engine = client.app.state.runner.engine
        engine.overrides = {**engine.overrides, "time_limit_s": 0.0}  # the audit's time is spent before the reader's turn
        audit = start(client, plan(client))
        report = get(client, audit, "/result")
        assert api.bodies == [] and report["firecrawl"]["used"] is False and "time limit was reached" in report["firecrawl"]["reason"]
        assert get(client, audit)["firecrawl"]["state"] == "pending"  # nothing was reserved or sent: the approval is unspent
        assert audit["outcome"]["code"] != "COMPLETED"
        # With time, the same site is read, and the report carries the whole job's time beside the crawl's own.
        engine.overrides = {k: v for k, v in engine.overrides.items() if k != "time_limit_s"}
        done = start(client, plan(client, key_pages=["/about"]))
        timing = get(client, done, "/result")["audit_status"]["timing"]
        assert api.bodies and timing["all_phases_s"] >= timing["crawl_and_checks_s"] and timing["page_reader_s"] is not None
        assert "for the whole audit, every step included" in client.get(f"{API}/audits/{done['id']}/downloads/markdown").text
        events = client.get(f"{API}/audits/{done['id']}/events", headers={"last-event-id": "0"}).text
        assert '"step": "firecrawl"' in events and '"attempted"' in events
    finally:
        for _ in factory:
            pass
