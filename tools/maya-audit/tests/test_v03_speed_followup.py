"""v0.3 speed follow-up (DECISIONS 299): one clock for every wait (a fake one in tests), Firecrawl started at Maya's first
429, a large sitemap index read in part with a fair spread, the blocked sentence said once, and RND-6 on Firecrawl's
rendered HTML labelled as such.

Every site, every Firecrawl and every clock here is made up; no socket is opened and nothing is paid for.
"""
import json
import threading
import time as real_time

import httpx
import pytest

from maya_audit import clock
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.fetcher import Fetcher
from maya_audit.firecrawl import Options, panel, reader
from maya_audit.firecrawl.pace import ReaderPace
from maya_audit.report import build_report, read_status_summary, render_markdown, run_outcome
from maya_audit.runclock import RunClock
from maya_audit.sitemap import PARTIAL, family, spread
from maya_audit_web import summary, wording
from maya_audit_web.strings import set_language
from test_firecrawl import SITE, Firecrawl, blocked_audit, client_for, no_lookups  # noqa: F401
from test_rate_limited_start import CF, HTML, ROBOTS
from test_review_fixes import QUIET


# -- 1. one clock ------------------------------------------------------------------------------------------------------
def test_every_wait_goes_through_one_clock_and_a_fake_one_moves_without_waiting():
    began = real_time.perf_counter()
    with clock.using(clock.FakeClock(start=100.0)) as fake:
        # Firecrawl's own pace, built with its defaults: a 30 s gap is counted, not waited.
        pace = ReaderPace(1, 30.0)
        first = pace.acquire()
        pace.release(first)
        second = pace.acquire()
        assert second.started_mono - first.started_mono >= 30.0
        # The run clock and the fetcher's polite sleep (a Retry-After) too.
        run = RunClock(deadline_mono=fake.monotonic() + 1000)
        assert 999 <= run.remaining() <= 1000
        fetcher = Fetcher("ua", 5.0, 0.0, httpx.MockTransport(lambda r: httpx.Response(200)), None)
        assert fetcher.sleep(60.0) is True
        assert fake.slept >= 90.0
    assert real_time.perf_counter() - began < 2.0
    assert isinstance(clock.current(), clock.SystemClock)  # put back after the block


# -- 2. Firecrawl starts at Maya's first 429 -------------------------------------------------------------------------------
def _rate_limited_bank(firecrawl_asked: threading.Event, seen: dict):
    """bank.test: robots allows all, the homepage answers 429 (Retry-After 20) twice. Maya's second homepage request
    waits up to 5 s (real time, only when this fails) for Firecrawl's first request, and says whether it came first."""
    asked = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS, headers={"content-type": "text/plain"})
        if request.url.path == "/":
            asked.append(request.url.path)
            if len(asked) == 2:  # Maya's request after the Retry-After wait
                seen["firecrawl_before_retry"] = firecrawl_asked.wait(5.0)
            return httpx.Response(429, headers={**HTML, **CF, "retry-after": "20"}, text="<title>Too many</title>")
        return httpx.Response(404, headers=HTML, text="<title>x</title>")
    return handler


def test_firecrawl_starts_at_mayas_first_429_before_the_retry_after_wait_and_reads_beside_it(tmp_path, no_lookups):
    firecrawl_asked, seen = threading.Event(), {}
    api = Firecrawl(SITE)

    def recording(request):
        firecrawl_asked.set()
        return api(request)
    cfg = CrawlConfig(**{**QUIET, "max_pages": 10})
    client = client_for(tmp_path, Firecrawl())
    client._http = httpx.Client(base_url="https://api.firecrawl.dev", transport=httpx.MockTransport(recording))
    client.clock = RunClock()
    options = Options(read_always=True, max_pages=10, concurrency=1)
    early = reader.EarlyReading(client, options)
    with clock.using(clock.FakeClock()):
        outcome = run_audit("https://bank.test/", cfg, httpx.MockTransport(_rate_limited_bank(firecrawl_asked, seen)),
                            reader=early)
        info = reader.apply(outcome, cfg, client, options, early=early)
    assert early.started and seen["firecrawl_before_retry"] is True  # Firecrawl asked before Maya's retry was sent
    started = info["coverage"]["started_at_first_429"]
    assert started["url"] == "https://bank.test/" and started["retry_after"] == "20" and started["started_at_s"] < 5
    assert info["coverage"]["ran_beside_maya"] is True and info["pages_read"] >= 3
    # Maya's own crawl still waited out the Retry-After and asked again (429 again, nothing else to ask): its result
    # stands as before; the pages are Firecrawl's.
    assert [p.status for p in outcome.result.pages] == [429] and outcome.result.pages[0].retried_after_429
    code, word, sentence = run_outcome(outcome.result, outcome.gates, panel.section(info))
    assert f"We read {info['pages_read']} page(s) through Firecrawl" in sentence


def test_a_429_after_the_first_pages_does_not_start_the_reader_early(tmp_path, no_lookups):
    pages = {"/": '<a href="/a">a</a><a href="/b">b</a><a href="/c">c</a><a href="/d">d</a>'}

    def handler(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS, headers={"content-type": "text/plain"})
        if path == "/d":
            return httpx.Response(429, headers=HTML, text="<title>Too many</title>")
        if path in pages or path in ("/a", "/b", "/c"):
            return httpx.Response(200, headers=HTML, text=f"<html><title>{path}</title><body><main><h1>x</h1>{pages.get(path, '')}</main></body></html>")
        return httpx.Response(404, headers=HTML, text="<title>x</title>")
    client = client_for(tmp_path, Firecrawl())
    client.clock = RunClock()
    early = reader.EarlyReading(client, Options(read_always=False, read_blocked=True, max_pages=5))
    with clock.using(clock.FakeClock()):
        run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 10}), httpx.MockTransport(handler), reader=early)
    assert early.after_rate_limit is None and not early.started


# -- 3. a large sitemap index read in part, spread over its kinds of file ---------------------------------------------------
def _shop_with_index(products_files=6, per_file=100):
    files = {f"/sitemap_products_{n}.xml?from={n}": [f"/products/p{n}-{i}" for i in range(per_file)]
             for n in range(1, products_files + 1)}
    files["/sitemap_pages_1.xml"] = [f"/pages/page{i}" for i in range(5)]
    files["/sitemap_blogs_1.xml"] = [f"/blogs/news/post{i}" for i in range(5)]
    asked = []

    def urlset(paths):
        return ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>https://shop.test{p}</loc></url>" for p in paths) + "</urlset>")

    def handler(request):
        path = request.url.raw_path.decode()
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\nSitemap: https://shop.test/sitemap.xml\n",
                                  headers={"content-type": "text/plain"})
        if path == "/sitemap.xml":
            asked.append(path)
            body = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + "".join(f"<sitemap><loc>https://shop.test{f.replace('&', '&amp;')}</loc></sitemap>" for f in files)
                    + "</sitemapindex>")
            return httpx.Response(200, text=body, headers={"content-type": "application/xml"})
        if path in files:
            asked.append(path)
            return httpx.Response(200, text=urlset(files[path]), headers={"content-type": "application/xml"})
        return httpx.Response(200, headers=HTML, text="<html><title>Shop</title><body><main><h1>Shop</h1></main></body></html>")
    return handler, asked, files


def test_the_files_of_a_sitemap_index_are_read_in_turn_by_kind():
    files = ["/s_products_1.xml", "/s_products_2.xml", "/s_products_3.xml", "/s_pages_1.xml", "/s_blogs_1.xml"]
    assert family("https://x.test/sitemap_products_2.xml?from=9") == family("https://x.test/sitemap_products_10.xml")
    assert family("https://x.test/en/sitemap_products_1.xml") != family("https://x.test/sitemap_products_1.xml")
    # Products first, last, middle; pages and blogs between: each kind early.
    assert spread(files) == ["/s_products_1.xml", "/s_pages_1.xml", "/s_blogs_1.xml", "/s_products_3.xml", "/s_products_2.xml"]
    eight = [f"/s_products_{n}.xml" for n in range(1, 9)]
    assert [u.split("_")[-1] for u in spread(eight)] == ["1.xml", "8.xml", "4.xml", "6.xml", "2.xml", "5.xml", "7.xml", "3.xml"]


def test_a_large_sitemap_index_is_read_until_there_are_enough_addresses_and_says_the_count_is_partial():
    handler, asked, files = _shop_with_index()
    cfg = CrawlConfig(**{**QUIET, "max_pages": 10, "sitemap_check_max": 20})
    with clock.using(clock.FakeClock()):
        outcome = run_audit("https://shop.test/", cfg, httpx.MockTransport(handler))
    result = outcome.result
    # The index, then one file of each kind: products 1, pages 1, blogs 1 (110 addresses, at least the 30 needed).
    assert asked == ["/sitemap.xml", "/sitemap_products_1.xml?from=1", "/sitemap_pages_1.xml", "/sitemap_blogs_1.xml"]
    assert len(result.sitemap_urls) == 110
    note = next(n for n in result.sitemap_notes if n.startswith(PARTIAL))
    assert "from 4 of 9 sitemap files" in note and "5 file(s) were not read" in note and "(30)" in note
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str))
    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    assert "URLs discovered (partial: a large sitemap index was read in part)" in markdown
    assert summary.method(report)["discovered_partial"] is True


def test_a_small_sitemap_index_is_read_whole_and_the_count_is_not_called_partial():
    handler, asked, files = _shop_with_index(products_files=2, per_file=5)
    cfg = CrawlConfig(**{**QUIET, "max_pages": 10, "sitemap_check_max": 20})
    with clock.using(clock.FakeClock()):
        outcome = run_audit("https://shop.test/", cfg, httpx.MockTransport(handler))
    assert len(asked) == 1 + len(files) and len(outcome.result.sitemap_urls) == 20
    assert not [n for n in outcome.result.sitemap_notes if n.startswith(PARTIAL)]
    assert "partial" not in render_markdown(outcome.result, outcome.gates, outcome.checks).split("URLs discovered", 1)[1][:40]


# -- 4. the blocked sentence said once ---------------------------------------------------------------------------------
BLOCKED = ("Maya's crawler was blocked (429 on pages); 50 page(s) were read through Firecrawl; 18192 more discovered URL(s) "
           "remain unchecked (the page cap of 50 was reached); +45 addresses left out: disallowed by robots.txt or not a "
           "page. Genuine AI-crawler access was not measured. Findings cover only the pages read.")


@pytest.mark.parametrize("language", ["en", "tr"])
def test_the_card_says_maya_was_blocked_once_not_in_its_label_and_again_under_it(language):
    set_language(language)
    try:
        label = summary.outcome_label("DEGRADED", BLOCKED)
        shown, known = summary.outcome_shown("DEGRADED", BLOCKED)
        assert known and label.split(";")[0] not in shown
        assert shown.startswith("18192 more discovered URLs" if language == "en" else "Keşfedilen 18192 URL")
        # Any other outcome is shown as it was.
        other = "The audit could not read the site properly: every page was blocked."
        assert summary.outcome_shown("DEGRADED", other)[0] == wording.outcome(other)[0]
    finally:
        set_language("en")


def test_the_status_summary_says_how_many_pages_firecrawl_read_once():
    status = {"direct_access": {"state": "challenged", "note": "Maya's own crawler was blocked (429 on pages) on 1 of 1 page "
                                                                "request(s); 50 page(s) read through Firecrawl."},
              "vendor_crawler_evidence": {"note": "Genuine AI-crawler access was not measured."},
              "content_coverage": {"note": "50 page(s) were read."}}
    counts = {"pages": 50, "read_by": {"firecrawl": 50, "maya_only": 0}}
    line = read_status_summary(status, counts)
    assert line.count("through Firecrawl") == 1 and "on 1 of 1 page request(s)." in line


# -- 5. RND-6 on Firecrawl's rendered HTML ---------------------------------------------------------------------------------
def test_rnd6_measured_on_firecrawls_copy_says_it_is_rendered_html_and_not_comparable(tmp_path, no_lookups):
    heavy = dict(SITE)
    heavy["https://bank.test/"] = SITE["https://bank.test/"].replace("<body>", "<body><script>" + "x" * 600_000 + "</script>", 1)
    outcome = blocked_audit()
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, Firecrawl(heavy)),
                        Options(read_always=True, max_pages=10))
    rnd6 = outcome.by_id()["RND-6"]
    assert rnd6.evidence["html_measured"] == "rendered (Firecrawl)" and "not comparable" in rnd6.evidence["measured_on"]
    assert rnd6.findings and all(f.title.endswith("(rendered HTML via Firecrawl, not comparable with raw size)")
                                 for f in rnd6.findings)
    assert all(any("not the HTML the server sends" in n for n in f.notes) for f in rnd6.findings)
    assert "RND-6" in info["checks_from_firecrawl"]
    set_language("tr")
    try:
        for f in rnd6.findings:
            translated, known = wording.title("RND-6", f.title)
            assert known and "Firecrawl ile işlenmiş HTML" in translated, f.title
    finally:
        set_language("en")
