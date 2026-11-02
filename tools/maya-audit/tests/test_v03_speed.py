"""v0.3 stage 2, speed (DECISIONS 294): one shared limit on the audited site, Firecrawl several at a time and started as
soon as the crawl ends, a smaller sitemap sample spread over the sitemap files, a time budget from measured times, and
the progress box.

Every site and every Firecrawl here is made up and held in memory; no socket is opened and nothing is paid for.
"""
import json
import threading
import time

import httpx
import pytest

from maya_audit import cli
from maya_audit.audit import run_audit
from maya_audit.checks.integrity import most_in_flight
from maya_audit.config import CrawlConfig
from maya_audit.fetcher import gaps_by_host
from maya_audit.firecrawl import Options, panel, reader, settings
from maya_audit.index_data import file_sample
from maya_audit.models import RequestRecord
from maya_audit.report import build_report, reader_gaps
from maya_audit.runclock import RunClock, for_outcome, reader_allowance_s
from maya_audit.sitelimit import MAYA, READER, SiteLimiter, backed_off, bad_answer, clamp
from maya_audit_web import wording
from test_false_alarms import HTML_TYPE, KAFE, answer
from test_firecrawl import KEY, Firecrawl, client_for, no_lookups  # noqa: F401
from test_review_fixes import QUIET

SITE_HOST = "demo-kafe.test"


# -- the shared site limit -------------------------------------------------------------------------------------------
def test_the_site_limit_spaces_starts_by_the_gap_and_never_has_more_in_flight_than_allowed():
    limiter = SiteLimiter(limit=3, gap=lambda: 0.05, maya_active=False)
    starts, lock, in_flight, most = [], threading.Lock(), [0], [0]

    def one():
        slot = limiter.acquire(READER)
        with lock:
            starts.append(slot.started_mono)  # when the limit let it start (what the request log records too)
            in_flight[0] += 1
            most[0] = max(most[0], in_flight[0])
        time.sleep(0.12)
        with lock:
            in_flight[0] -= 1
        limiter.release(slot)

    threads = [threading.Thread(target=one) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    starts.sort()
    assert most[0] == 3 == limiter.max_in_flight  # several at once: the answers overlap ...
    assert min(b - a for a, b in zip(starts, starts[1:])) >= 0.045  # ... but every start keeps the gap after the one before
    assert limiter.summary()["starts"] == {READER: 8}


def test_mayas_own_thread_keeps_slot_zero_and_a_waiting_maya_request_goes_before_the_reader():
    limiter = SiteLimiter(limit=2, gap=lambda: 0.0)
    # While Maya's steps run, the reader may not take slot 0.
    first = limiter.acquire(READER)
    assert first.index == 1
    assert limiter.acquire(READER, deadline_mono=time.monotonic() + 0.1) is None  # slot 0 is Maya's: nothing for the reader
    mine = limiter.acquire(MAYA, main=True)
    assert mine.index == 0
    limiter.release(mine)
    limiter.release(first)
    # Once Maya's steps are over, the reader may use every slot.
    limiter.maya_done()
    a, b = limiter.acquire(READER), limiter.acquire(READER)
    assert {a.index, b.index} == {0, 1}


def test_the_reader_starts_while_mayas_own_thread_waits_out_its_gap_without_delaying_it():
    # Maya's own requests are sequential, each the gap after the one before: the reader fits between them, and only where
    # starting leaves Maya's next start where it was.
    limiter = SiteLimiter(limit=3, gap=lambda: 0.2)
    times = {}

    def maya():
        first = limiter.acquire(MAYA, main=True)
        time.sleep(0.3)  # a slow answer
        limiter.release(first)
        times["maya_end"] = time.monotonic()
        times["maya_next"] = limiter.acquire(MAYA, main=True).started_mono

    thread = threading.Thread(target=maya)
    thread.start()
    time.sleep(0.05)
    reader_slot = limiter.acquire(READER, deadline_mono=time.monotonic() + 2)
    thread.join()
    assert reader_slot is not None and reader_slot.started_mono < times["maya_next"]  # it did not wait for Maya's steps
    assert times["maya_next"] - times["maya_end"] < 0.3  # and Maya's next request kept its own gap (0.2 s), not more


def test_the_first_request_through_the_limit_keeps_the_gap_after_the_crawls_last_one():
    limiter = SiteLimiter(limit=5, gap=lambda: 0.2)
    ended = time.monotonic()
    limiter.seed(ended - 0.1, ended)  # the crawl's last request to the site
    slot = limiter.acquire(MAYA, main=True)
    assert slot.started_mono - ended >= 0.19


def test_the_limit_backs_off_to_two_then_one_and_records_why():
    limiter = SiteLimiter(limit=5)
    assert limiter.back_off("429", MAYA) == 2 and limiter.back_off("slow", READER) == 1 and limiter.back_off("5xx", MAYA) is None
    assert [(s["from"], s["to"], s["reason"]) for s in limiter.summary()["backed_off"]] == [(5, 2, "429"), (2, 1, "slow")]
    assert limiter.summary()["configured"] == 5 and limiter.summary()["final"] == 1
    assert [backed_off(n) for n in (10, 5, 3, 2, 1)] == [2, 2, 2, 1, None]
    assert (clamp(0), clamp(11), clamp("x"), clamp(7)) == (1, 10, 5, 7)
    assert (bad_answer(429, None, 0.1, 2), bad_answer(503, None, 0.1, 2), bad_answer(200, None, 3.0, 2),
            bad_answer(None, "timeout (ReadTimeout)", None, 2), bad_answer(404, None, 0.1, 2),
            bad_answer(None, "audit_deadline_skipped", None, 2)) == ("429", "5xx", "slow", "no answer", None, None)


def _record(seq, start, end, slot=None, url="https://demo-kafe.test/a"):
    return RequestRecord(seq, url, "sitemap_check", "Maya-Audit/0.2", "2026-11-02T00:00:00+00:00", 200, None,
                         (end - start) * 1000, started_mono=start, ended_mono=end, slot=slot)


def test_int4_measures_the_gap_per_slot_and_between_starts_when_requests_overlap():
    # Two slots in flight together: each keeps 1 s after its own last request, and the starts are 0.5 s apart.
    records = [_record(1, 0.0, 0.8, 0), _record(2, 0.5, 1.3, 1), _record(3, 1.8, 2.0, 0), _record(4, 2.3, 2.5, 1)]
    gaps, _ = gaps_by_host(records)
    # Per slot: 0.8 -> 1.8 and 1.3 -> 2.3 (1000 ms each); between starts: 0 -> 0.5 -> 1.8 -> 2.3 (500, 1300, 500 ms).
    assert sorted(round(g) for g in gaps[SITE_HOST]) == [500, 500, 1000, 1000, 1300]
    assert most_in_flight(records) == 2
    # One request at a time (the crawl, no slot): only the end-to-start gap, as before.
    gaps, _ = gaps_by_host([_record(1, 0.0, 0.2), _record(2, 1.2, 1.4)])
    assert [round(g) for g in gaps[SITE_HOST]] == [1000]


# -- the sitemap check ---------------------------------------------------------------------------------------------------
def test_the_sample_takes_the_sitemap_files_in_turn_evenly_spaced_within_each():
    files = {"https://x.test/a.xml": [f"https://x.test/a/{n}" for n in range(100)],
             "https://x.test/b.xml": [f"https://x.test/b/{n}" for n in range(4)],
             "https://x.test/c.xml": [f"https://x.test/c/{n}" for n in range(50)]}
    file_of = {url: name for name, urls in files.items() for url in urls}
    urls = [url for listed in files.values() for url in listed]
    picked = file_sample(urls, 30, file_of)
    assert len(picked) == len(set(picked)) == 30 and picked == file_sample(urls, 30, file_of)  # the same every run
    by_file = {name: [u for u in picked if file_of[u] == name] for name in files}
    # b has only 4: the others share its unused turns.
    assert {name: len(v) for name, v in by_file.items()} == {"https://x.test/a.xml": 13, "https://x.test/b.xml": 4, "https://x.test/c.xml": 13}
    assert by_file["https://x.test/a.xml"][:3] == ["https://x.test/a/0", "https://x.test/a/7", "https://x.test/a/15"]  # spread out
    assert picked[:3] == ["https://x.test/a/0", "https://x.test/b/0", "https://x.test/c/0"]  # the files take turns


def _site_with_sitemaps(files, slow_s=0.0, watch=None, status=None):
    """A made-up site whose robots.txt names a sitemap index of `files` ({path: [page paths]}). Light requests take
    `slow_s`; `watch` counts the requests in flight; `status` maps a path to a status code."""
    lock = threading.Lock()
    index = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
             + "".join(f"<sitemap><loc>{KAFE}{name}</loc></sitemap>" for name in files) + "</sitemapindex>")

    def respond(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {KAFE}/index.xml\n", headers={"content-type": "text/plain"})
        if path == "/index.xml":
            return httpx.Response(200, headers={"content-type": "application/xml"}, text=index)
        if path in files:
            return httpx.Response(200, headers={"content-type": "application/xml"}, text=(
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>{KAFE}{p}</loc></url>" for p in files[path]) + "</urlset>"))
        if watch is not None:
            with lock:
                watch["now"] += 1
                watch["most"] = max(watch["most"], watch["now"])
        try:
            if slow_s:
                time.sleep(slow_s)
            if status and path in status:
                return httpx.Response(status[path], headers=HTML_TYPE, text="no")
            return answer(title=f"Sayfa {path}")
        finally:
            if watch is not None:
                with lock:
                    watch["now"] -= 1
    return respond


def test_the_sitemap_check_asks_four_at_once_through_the_site_limit_and_int4_stays_compliant(no_lookups):
    files = {f"/s{n}.xml": [f"/s{n}/p{i}" for i in range(15)] for n in range(3)}
    files["/s0.xml"].insert(0, "/")
    watch = {"now": 0, "most": 0}
    outcome = run_audit(KAFE + "/", CrawlConfig(**{**QUIET, "max_pages": 2, "sitemap_check_max": 20}),
                        httpx.MockTransport(_site_with_sitemaps(files, slow_s=0.05, watch=watch)))
    check = outcome.result.index.sitemap_check
    assert check.workers == 4 and len(check.rows) == 20 and check.sampled and check.sample_files == 3
    assert 2 <= watch["most"] <= 4  # light requests overlapped, never more than four
    asked = [r for r in outcome.result.requests if r.purpose == "sitemap_check"]
    assert {r.slot for r in asked} <= set(range(5)) and len({r.slot for r in asked}) > 1
    int4 = next(g for g in outcome.gates if g.check_id == "INT-4")
    assert int4.state == "compliant" and int4.evidence["politeness"]["max_in_flight_own"] <= 5
    assert int4.evidence["politeness"]["site_limit"]["configured"] == 5
    # The report says it was a sample, how many were checked, and over how many files.
    idx5 = next(c for c in outcome.checks if c.check_id == "IDX-5")
    assert (f"A sample was checked: 20 of the {check.wanted} sitemap URL(s) the crawl did not read, spread evenly over 3 "
            "sitemap file(s)." in idx5.summary), idx5.summary
    assert wording.line(idx5.summary, "tr")[1]  # said in Turkish too


def test_a_crawl_delay_keeps_the_site_at_one_request_at_a_time(no_lookups):
    files = {"/s0.xml": ["/"] + [f"/p{i}" for i in range(8)]}
    respond = _site_with_sitemaps(files)

    def with_delay(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nCrawl-delay: 0.01\nAllow: /\nSitemap: {KAFE}/index.xml\n",
                                  headers={"content-type": "text/plain"})
        return respond(request)
    outcome = run_audit(KAFE + "/", CrawlConfig(**{**QUIET, "max_pages": 2}), httpx.MockTransport(with_delay))
    assert any(r.get("crawl_delay") for r in outcome.result.robots)
    assert outcome.result.backoff["site_limit"]["configured"] == 1  # a site that asks for spacing gets one at a time
    assert outcome.result.index.sitemap_check.workers == 1


# -- Firecrawl several at a time --------------------------------------------------------------------------------------
TEXT = "<p>" + "Taze kahve ve ev yapımı tatlılar her gün hazırlanır. " * 15 + "</p>"


def _pages(n):
    links = "".join(f'<a href="/p{i}">Sayfa {i}</a>' for i in range(n))
    home = f'<!doctype html><html lang="tr"><head><title>Demo</title></head><body><main><h1>Demo</h1>{TEXT}{links}</main></body></html>'
    pages = {KAFE + "/": home}
    for i in range(n):
        pages[f"{KAFE}/p{i}"] = (f'<!doctype html><html lang="tr"><head><title>Sayfa {i}</title></head><body><main><h1>Sayfa {i}</h1>'
                                 f"{TEXT}</main></body></html>")
    return pages


def _site(pages):
    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        url = str(request.url)
        return httpx.Response(200, headers=HTML_TYPE, text=pages[url]) if url in pages else answer(title="Yok", status=404)
    return respond


class SlowFirecrawl(Firecrawl):
    """A made-up Firecrawl whose every answer takes `seconds`; counts the requests in flight."""

    def __init__(self, pages, seconds=0.05, responder=None):
        super().__init__(pages, responder)
        self.seconds, self.now, self.most, self.first_at = seconds, 0, 0, None
        self._lock = threading.Lock()

    def __call__(self, request):
        with self._lock:
            self.now += 1
            self.most = max(self.most, self.now)
            self.first_at = self.first_at or time.monotonic()
        try:
            time.sleep(self.seconds)
            return super().__call__(request)
        finally:
            with self._lock:
                self.now -= 1


MAIN = Options(read_always=True, max_pages=12)


def test_firecrawl_reads_up_to_five_at_once_through_the_site_limit_and_says_so(tmp_path, no_lookups):
    pages = _pages(11)
    outcome = run_audit(KAFE + "/", CrawlConfig(**{**QUIET, "max_pages": 12}), httpx.MockTransport(_site(pages)))
    api = SlowFirecrawl(pages)
    client = client_for(tmp_path, api)
    client.clock = for_outcome(outcome)  # the audit's own clock carries its site limit
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 12}), client, MAIN)
    section = panel.section(info)
    assert section["used"] and section["pages_read"] == 12 and len(api.urls) == len(set(api.urls)) == 12
    assert 2 <= api.most <= 5  # several at once, never more than the setting
    assert section["concurrency"]["configured"] == 5 and section["concurrency"]["start"] == 5
    assert section["concurrency"]["backed_off"] == [] and section["concurrency"]["max_in_flight"] <= 5
    assert section["coverage"]["seconds_per_page_measured"] > 0 and section["coverage"]["call_seconds_measured"] >= 0.05
    assert section["coverage"]["seconds_per_page_assumed"] == 8.0 and section["coverage"]["skipped_for_time"] == 0
    assert outcome.result.backoff["site_limit"]["starts"].get(READER) == 12  # the reader's starts went through the limit
    assert sorted(row["url"] for row in section["pages"]) == sorted(api.urls)
    report = build_report(outcome.result, outcome.gates, outcome.checks, firecrawl=section)
    assert report["schema_version"] == "1.21" and report["crawl"]["backoff"]["site_limit"]["configured"] == 5


def test_without_a_site_limit_the_reader_reads_one_page_at_a_time(tmp_path, no_lookups):
    pages = _pages(5)
    outcome = run_audit(KAFE + "/", CrawlConfig(**{**QUIET, "max_pages": 6}), httpx.MockTransport(_site(pages)))
    api = SlowFirecrawl(pages, seconds=0.02)
    client = client_for(tmp_path, api)
    client.clock = RunClock()  # a clock of its own, no shared limit: nothing spaces overlapping starts
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 6}), client, Options(read_always=True, max_pages=6))
    assert api.most == 1 and info["concurrency"]["start"] == 1 and info["concurrency"]["site_limit"] is False


@pytest.mark.parametrize("trouble, reason", [
    (lambda body: httpx.Response(429, json={"success": False, "error": "Rate limit exceeded"}), "429 from Firecrawl"),
    (lambda body: httpx.Response(200, json={"success": True, "data": {"rawHtml": "<html><title>x</title></html>",
                                                                      "metadata": {"statusCode": 503, "url": body["url"]}}}),
     "5xx from the site"),
])
def test_firecrawl_backs_off_to_two_then_one_and_goes_on_reading(tmp_path, no_lookups, trouble, reason):
    pages = _pages(11)
    bad = {f"{KAFE}/p3", f"{KAFE}/p6"}
    outcome = run_audit(KAFE + "/", CrawlConfig(**{**QUIET, "max_pages": 12}), httpx.MockTransport(_site(pages)))
    api = SlowFirecrawl(pages, seconds=0.02, responder=lambda body: trouble(body) if body["url"] in bad else None)
    client = client_for(tmp_path, api)
    client.clock = for_outcome(outcome)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 12}), client, MAIN)
    steps = info["concurrency"]["backed_off"]
    assert [(s["from"], s["to"], s["reason"]) for s in steps] == [(5, 2, reason), (2, 1, reason)]
    assert info["concurrency"]["final"] == 1 and info["used"] and info["pages_read"] >= 9  # it went on, more slowly
    if reason == "5xx from the site":  # the site's own answer slows the shared site limit too
        assert outcome.result.backoff["site_limit"]["backed_off"][0]["seen_by"] == "reader"


def test_the_concurrency_setting_is_one_to_ten(monkeypatch, tmp_path):
    assert Options(concurrency=0).problem() and Options(concurrency=11).problem() and Options(concurrency=10).problem() is None
    env = tmp_path / "none.env"
    assert settings.concurrency({"MAYA_AUDIT_ENV_FILE": str(env)}) == 5
    assert settings.concurrency({"MAYA_AUDIT_ENV_FILE": str(env), "MAYA_AUDIT_FIRECRAWL_CONCURRENCY": "8"}) == 8
    assert settings.concurrency({"MAYA_AUDIT_ENV_FILE": str(env), "MAYA_AUDIT_FIRECRAWL_CONCURRENCY": "50"}) == 10
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["crawl", KAFE + "/", "--firecrawl-concurrency", "11"])
    args = cli._parser().parse_args(["crawl", KAFE + "/", "--site-concurrency", "3"])
    assert cli._crawl_config(args).site_concurrency == 3
    assert "concurrency" in Options().as_dict()


def test_the_plan_fingerprint_does_not_change_with_requests_at_once():
    from maya_audit_web import paid

    def shown(concurrency):
        return {"requested": True, "options": {**Options(read_always=True).as_dict(), "concurrency": concurrency},
                "max_credits": 102, "max_usd": None}
    assert paid.fingerprint(KAFE, "quick", [], False, [], 0.0, shown(5)) == paid.fingerprint(KAFE, "quick", [], False, [], 0.0, shown(2))


# -- started as soon as the crawl ends --------------------------------------------------------------------------------
def test_the_reader_starts_when_the_crawl_ends_and_reads_beside_mayas_own_steps(tmp_path, no_lookups):
    pages = _pages(5)
    files = {"/s0.xml": ["/"] + [f"/p{i}" for i in range(5)] + [f"/x{i}" for i in range(30)]}
    sitemap_site = _site_with_sitemaps(files, slow_s=0.03)
    site = _site(pages)

    def respond(request):
        path = request.url.path
        return sitemap_site(request) if path in ("/robots.txt", "/index.xml", "/s0.xml") or path.startswith("/x") else site(request)
    api = SlowFirecrawl(pages, seconds=0.05)
    client = client_for(tmp_path, api)
    config = CrawlConfig(**{**QUIET, "max_pages": 6, "sitemap_check_max": 30})
    early = reader.EarlyReading(client, Options(read_always=True, max_pages=6))
    outcome = run_audit(KAFE + "/", config, httpx.MockTransport(respond), reader=early)
    assert early.started
    info = reader.apply(outcome, config, client, Options(read_always=True, max_pages=6), early=early)
    last_own = max(r.ended_mono for r in outcome.result.requests if r.purpose == "sitemap_check")
    assert api.first_at < last_own  # Firecrawl was reading while Maya's sitemap check still ran
    assert info["used"] and info["pages_read"] == 6 and info["coverage"]["ran_beside_maya"] is True
    assert info["coverage"]["elapsed_s"] is not None
    assert next(g for g in outcome.gates if g.check_id == "INT-4").state == "compliant"
    assert outcome.result.backoff["site_limit"]["starts"].get(READER) == 6


def test_a_challenged_crawl_does_not_start_the_reader_early_and_it_reads_after_the_audit(tmp_path, no_lookups):
    from test_firecrawl import SITE, challenged

    client = client_for(tmp_path, Firecrawl(SITE))
    options = Options(read_always=True, max_pages=10)
    early = reader.EarlyReading(client, options)
    outcome = run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 10}), httpx.MockTransport(challenged), reader=early)
    assert not early.started
    client.clock = for_outcome(outcome)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client, options, early=early)
    assert info["used"] and info["pages_read"] == 4 and not info["coverage"].get("ran_beside_maya")


# -- the time budget ----------------------------------------------------------------------------------------------------
def test_the_reader_allowance_shares_the_assumed_time_between_the_requests_in_flight():
    assert reader_allowance_s(50, 1.0, 8.0) == 450.0  # one at a time, as before
    assert reader_allowance_s(50, 1.0, 8.0, at_once=5) == 80.0  # 8 s shared by 5 in flight: 1.6 s a page
    assert reader_allowance_s(500, 1.0, 4.0, at_once=5) == 500.0  # never faster than the polite gap


def test_pages_the_time_limit_leaves_are_counted_with_the_measured_pace(tmp_path, no_lookups):
    pages = _pages(29)
    config = CrawlConfig(**{**QUIET, "max_pages": 30})
    outcome = run_audit(KAFE + "/", config, httpx.MockTransport(_site(pages)))
    api = SlowFirecrawl(pages, seconds=0.3)
    client = client_for(tmp_path, api, approved_credits=1000)
    clock = for_outcome(outcome)
    clock.deadline_mono = time.monotonic() + 1.6  # time for some pages, not for thirty
    clock.needs_s = 0.6  # before anything is measured (the real starting figure is 5 s; kept small to keep the test short)
    client.clock = clock
    info = reader.apply(outcome, config, client, Options(read_always=True, max_pages=30))
    coverage = info["coverage"]
    assert 0 < info["pages_read"] < 30 and coverage["not_requested_because"] == "time_limit"
    assert coverage["skipped_for_time"] == coverage["known_urls_not_requested"] > 0
    assert coverage["call_seconds_measured"] >= 0.3 and coverage["seconds_per_page_measured"] > 0
    # What a request needs became what the calls took (1.25 x their median, at least 0.5 s), not the figure set before.
    assert clock.needs_s != 0.6 and 0.5 <= clock.needs_s <= max(0.5, 2 * 1.25 * coverage["call_seconds_measured"])
    [line] = [g for g in reader_gaps(panel.section(info)) if "lack of time" in g]
    assert line.startswith(f"{coverage['skipped_for_time']} page(s) were not read for lack of time (the page reader measured ")
    assert wording.line(line, "tr")[1]


# -- the progress box ---------------------------------------------------------------------------------------------------
@pytest.fixture
def progress_app(tmp_path):
    from fastapi.testclient import TestClient

    from maya_audit_web import demo
    from maya_audit_web.app import create_app
    from maya_audit_web.runner import Engine
    from test_web_app import API, BASE

    engine = Engine(transport_factory=lambda: httpx.MockTransport(lambda r: httpx.Response(404)), allow_loopback=True,
                    overrides=demo.OVERRIDES)  # no politeness waits: the made-up audit ends in seconds
    client = TestClient(create_app(tmp_path / "web", engine=engine, port=8770), base_url=BASE)
    client.__enter__()
    client.get("/")
    client.headers["x-maya-token"] = client.get(f"{API}/session").json()["token"]
    yield client, API
    client.__exit__(None, None, None)


def test_the_audit_view_counts_firecrawl_beside_maya_and_estimates_from_the_measured_pace(progress_app):
    from datetime import datetime, timezone

    client, api = progress_app
    store = client.app.state.store
    plan = client.post(f"{api}/plans", json={"url": "https://demo-kafe.test/"})
    assert plan.status_code == 201, plan.text
    made = plan.json()
    started = client.post(f"{api}/audits", json={"plan_id": made["id"], "message": "audit"})
    assert started.status_code == 201, started.text
    audit_id = started.json()["id"]
    client.app.state.runner.wait(audit_id, 60)
    now = datetime.now(timezone.utc).isoformat()
    store.update_audit(audit_id, state="running", finished_at=None, started_at=now, progress={
        "phase": "render", "step": "rendering", "steps_seen": ["access", "sitemap", "crawling", "rendering"], "page_cap": 50,
        "pages_checked": 50, "at": now, "elapsed_s": 120.0,
        "firecrawl": {"attempted": 21, "read": 20, "failed": 0, "from_cache": 0, "page_cap": 50, "in_flight": 4, "seconds_per_page": 2.0}})
    view = client.get(f"{api}/audits/{audit_id}").json()
    assert view["counters"]["pages_checked"] == 50 and view["counters"]["firecrawl_read"] == 20 and view["counters"]["firecrawl_cap"] == 50
    assert view["eta"]["kind"] == "estimate" and view["eta"]["max_seconds"] == 60  # 30 pages left at 2 s a page
    assert "Firecrawl reads a page every 2.0 s" in view["eta"]["label"]
    # Without the reader's pace, after the crawl: the time limit's bound, never a made-up figure.
    store.update_audit(audit_id, progress={"phase": "render", "step": "rendering", "page_cap": 50, "pages_checked": 50, "at": now})
    view = client.get(f"{api}/audits/{audit_id}").json()
    assert view["eta"]["kind"] == "limit" and "time limit" in view["eta"]["label"]
    js = (__import__("pathlib").Path(__file__).parents[1] / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'T("job.pages.firecrawl"' in js and 'data.step === "firecrawl"' in js
    assert json.dumps(view)  # the view stays JSON
