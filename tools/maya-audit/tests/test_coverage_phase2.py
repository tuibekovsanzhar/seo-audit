"""Phase 2: the reader takes pages in the crawler's order, finds a sitemap when Maya could not, stops when it keeps
failing, says why each page was not read, and has its share of the audit's time. Everything is in memory.
"""
import json
import sys
from pathlib import Path

import httpx
import pytest

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, panel, reader
from maya_audit.firecrawl.reading import SITEMAP_DOCUMENTS, ReadingQueue, discover_through_reader, sitemap_locations
from maya_audit.report import run_outcome
from maya_audit.runclock import READER_SECONDS_PER_PAGE, reader_allowance_s, reader_seconds_per_page
from test_firecrawl import SITE, Firecrawl, blocked_audit, client_for, doc, no_lookups  # noqa: F401
from test_review_fixes import QUIET

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import coverage_benchmark as bench  # noqa: E402

ROOT = "https://bank.test"
CFG = CrawlConfig(**{**QUIET, "max_pages": 50})
ALL_ON = Options(read_always=True, max_pages=50, sitemap_discovery=True)


# -- the order ------------------------------------------------------------------------------------------------------
def test_the_reading_queue_takes_key_pages_then_navigation_then_the_least_read_section():
    queue = ReadingQueue()
    queue.add(f"{ROOT}/", "start", 0)
    for n in range(1, 4):
        queue.add(f"{ROOT}/kettles/item-{n}", "link", 1)
    queue.add(f"{ROOT}/teapots/item-1", "link", 1)
    queue.add(f"{ROOT}/kettles?page=2", "link", 1)
    queue.add(f"{ROOT}/landing", "sitemap", None)
    queue.add(f"{ROOT}/pricing", "link", 1, nav=True)
    queue.add(f"{ROOT}/appointments", "key_page", 1)
    order = []
    while len(queue):
        url, _via, _depth = queue.pop()
        queue.taken(url)
        order.append(url.removeprefix(ROOT))
    assert order[:3] == ["/", "/appointments", "/pricing"]                    # start, the marked page, the menu
    assert order[3:5] == ["/kettles/item-1", "/teapots/item-1"]               # one of each kind before a second kettle
    assert order[5] == "/landing"                                             # a kind of page not read yet, known only from the sitemap
    assert order[6:] == ["/kettles/item-2", "/kettles/item-3", "/kettles?page=2"]  # more of the same, and page 2 of a list last
    plain = ReadingQueue(spread=False)
    for url, via in ((f"{ROOT}/a/1", "link"), (f"{ROOT}/b/1", "sitemap"), (f"{ROOT}/key", "key_page")):
        plain.add(url, via, 1)
    assert [plain.pop()[0].removeprefix(ROOT) for _ in range(3)] == ["/a/1", "/b/1", "/key"]  # the old order, kept to measure against
    again = ReadingQueue()
    again.add(f"{ROOT}/x", "link", 2)
    again.add(f"{ROOT}/x", "link", 1, nav=True)   # found again, this time in the menu: it moves up, and is still one entry
    again.add(f"{ROOT}/y", "link", 1)
    assert len(again) == 2 and again.pop()[0] == f"{ROOT}/x" and again.waiting() == [f"{ROOT}/y"]


# -- the sitemap ----------------------------------------------------------------------------------------------------
def test_sitemap_addresses_are_read_from_plain_xml_escaped_xml_and_an_index():
    plain = "<urlset><url><loc> https://bank.test/a </loc></url><url><loc>https://bank.test/b?x=1&amp;y=2</loc></url></urlset>"
    assert sitemap_locations(plain) == (["https://bank.test/a", "https://bank.test/b?x=1&y=2"], False)
    shown = "<html><body><pre>&lt;urlset&gt;&lt;url&gt;&lt;loc&gt;https://bank.test/a&lt;/loc&gt;&lt;/url&gt;&lt;/urlset&gt;</pre></body></html>"
    assert sitemap_locations(shown) == (["https://bank.test/a"], False)
    index = "<sitemapindex><sitemap><loc>https://bank.test/pages.xml</loc></sitemap></sitemapindex>"
    assert sitemap_locations(index) == (["https://bank.test/pages.xml"], True) and sitemap_locations("<html>nothing</html>") == ([], False)


def test_sitemap_discovery_is_bounded_stays_on_the_site_and_obeys_robots():
    from types import SimpleNamespace
    asked = []
    docs = {f"{ROOT}/sitemap.xml": "<sitemapindex>" + "".join(f"<sitemap><loc>{ROOT}/s{n}.xml</loc></sitemap>" for n in range(1, 6))
            + "<sitemap><loc>https://other.example/s.xml</loc></sitemap></sitemapindex>",
            f"{ROOT}/s1.xml": f"<urlset><url><loc>{ROOT}/a</loc></url><url><loc>https://other.example/x</loc></url><url><loc>{ROOT}/b</loc></url></urlset>"}

    def scrape(url):
        asked.append(url)
        return SimpleNamespace(html=docs.get(url, ""), status=200 if url in docs else 404, cached=False)
    found = discover_through_reader(scrape, ROOT, [], lambda u: True, lambda u: u.startswith(ROOT), 50)
    assert asked == [f"{ROOT}/sitemap.xml", f"{ROOT}/s1.xml"] and len(asked) == SITEMAP_DOCUMENTS  # the index and one document, no more
    assert found["urls"] == [f"{ROOT}/a", f"{ROOT}/b"] and "more sitemap document(s) were not asked for" in found["note"]
    assert [d["outcome"] for d in found["documents"]] == ["index", "read"]
    asked.clear()
    refused = discover_through_reader(scrape, ROOT, [f"{ROOT}/private/map.xml"], lambda u: "/private/" not in u, lambda u: u.startswith(ROOT), 50)
    assert f"{ROOT}/private/map.xml" not in asked and refused["documents"][0]["outcome"] == "disallowed_by_robots"


LINKED = {f"{ROOT}/robots.txt": SITE[f"{ROOT}/robots.txt"],
          f"{ROOT}/": doc("Home", "<h1>Home</h1><p>" + "Words about the business. " * 20 + f'</p><a href="{ROOT}/about">About</a>'),
          f"{ROOT}/about": doc("About us", "<h1>About</h1><p>" + "More words about the business. " * 20 + "</p>"),
          f"{ROOT}/landing/offer": doc("An offer nothing links to", "<h1>Offer</h1><p>" + "Words about the offer. " * 20 + "</p>"),
          f"{ROOT}/sitemap.xml": f"<urlset><url><loc>{ROOT}/</loc></url><url><loc>{ROOT}/about</loc></url><url><loc>{ROOT}/landing/offer</loc></url>"
                                 f"<url><loc>{ROOT}/private/x</loc></url></urlset>"}


def test_a_challenged_sites_sitemap_is_asked_for_after_the_first_page_and_its_unlinked_pages_are_read(tmp_path, no_lookups):
    api = Firecrawl(LINKED)
    info = reader.apply(blocked_audit(), CFG, client_for(tmp_path, api), ALL_ON)
    section = panel.section(info)
    assert api.urls[:2] == [f"{ROOT}/", f"{ROOT}/sitemap.xml"]  # the homepage first: nothing is spent on a sitemap if the reader cannot read the site
    assert f"{ROOT}/landing/offer" in api.urls and section["pages_read"] == 3
    assert section["sitemap"] == {"documents": [{"url": f"{ROOT}/sitemap.xml", "outcome": "read", "status": 200, "addresses": 4, "from_cache": False}],
                                  "addresses_found": 4, "note": None}
    assert section["coverage"]["sitemap_addresses_found"] == 4 and section["options"]["sitemap_discovery"] is True
    assert any("Sitemap through Firecrawl" in line and "4 address(es) found in 1 of 1" in line for line in panel.summary_lines(section))
    # Without it (the old behaviour) the unlinked page is never found.
    old = Firecrawl(LINKED)
    without = reader.apply(blocked_audit(), CFG, client_for(tmp_path / "old", old), Options(read_always=True, max_pages=50, sitemap_discovery=False))
    assert f"{ROOT}/sitemap.xml" not in old.urls and without["pages_read"] == 2 and "sitemap" not in without


def test_the_sitemap_is_not_asked_for_when_the_reader_reads_nothing_or_maya_already_has_one_or_the_cap_is_small(tmp_path, no_lookups):
    wall = lambda body: httpx.Response(200, json={"success": True, "data": {  # noqa: E731
        "rawHtml": "<html><title>Just a moment...</title><body>Checking your browser</body></html>", "metadata": {"statusCode": 403}}})
    walled = Firecrawl(LINKED, wall)
    reader.apply(blocked_audit(), CFG, client_for(tmp_path / "a", walled), ALL_ON)
    assert not [u for u in walled.urls if u.endswith("sitemap.xml")]
    small = Firecrawl(LINKED)
    reader.apply(blocked_audit(), CFG, client_for(tmp_path / "b", small), Options(read_always=True, max_pages=5, sitemap_discovery=True))
    assert not [u for u in small.urls if u.endswith("sitemap.xml")]


def test_an_unanswered_sitemap_request_stops_the_reading_instead_of_paying_again(tmp_path, no_lookups):
    sent = []

    def flaky(request):
        url = json.loads(request.content)["url"]
        sent.append(url)
        if url.endswith("sitemap.xml"):
            raise httpx.ReadTimeout("no answer")
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": LINKED[url], "metadata": {"statusCode": 200, "url": url}}})
    client = client_for(tmp_path, Firecrawl(LINKED))
    client._http = httpx.Client(base_url="https://api.firecrawl.dev", transport=httpx.MockTransport(flaky))
    info = reader.apply(blocked_audit(), CFG, client, ALL_ON)
    assert sent == [f"{ROOT}/", f"{ROOT}/sitemap.xml"] and info["pages_read"] == 1  # nothing is asked after a request that may have been billed
    assert "may have been charged" in info["stopped_because"] and "was not read" in info["sitemap"]["note"]
    assert client.calls[-1]["billing_status"] == "possibly_billed"


# -- stopping when the reader keeps failing, and saying why ------------------------------------------------------------
def test_a_reader_that_starts_being_turned_away_stops_after_five_in_a_row_and_each_page_says_why(tmp_path, no_lookups):
    pages = {f"{ROOT}/robots.txt": SITE[f"{ROOT}/robots.txt"],
             f"{ROOT}/": doc("Home", "<h1>Home</h1><p>" + "Words. " * 60 + "</p>" + "".join(f'<a href="{ROOT}/p{n}">p{n}</a>' for n in range(1, 30))),
             **{f"{ROOT}/p{n}": doc(f"Page {n}", f"<h1>Page {n}</h1><p>" + "Words. " * 60 + "</p>") for n in range(1, 30)}}
    count = {"pages": 0}

    def turned_away_later(body):
        if body["url"].endswith(("robots.txt", "sitemap.xml")):
            return None
        count["pages"] += 1
        if count["pages"] > 3:
            return httpx.Response(200, json={"success": True, "data": {"rawHtml": "<html><title>Just a moment...</title><body>Checking your browser</body></html>",
                                                                      "metadata": {"statusCode": 403}}})
        return None
    api = Firecrawl(pages, turned_away_later)
    outcome = blocked_audit()
    info = reader.apply(outcome, CFG, client_for(tmp_path, api), Options(read_always=True, max_pages=50))
    section = panel.section(info)
    cover = section["coverage"]
    assert section["pages_read"] == 3 and count["pages"] == 8  # three read, five refused in a row, then no more: 22 requests were not paid for
    assert section["stopped_because"] == "the last 5 pages asked for came back unreadable, so no more were requested"
    assert cover["not_requested_because"] == "reader_kept_failing" and cover["known_urls_not_requested"] == 22 and cover["causes"] == {"reader_challenged": 5}
    assert [row["cause"] for row in section["pages"]] == [None, None, None, *["reader_challenged"] * 5]
    code, word, sentence = run_outcome(outcome.result, outcome.gates, section)
    assert word == "INCOMPLETE" and "5 requested URL(s) gave no readable document (5 reader challenged)" in sentence
    assert "22 more discovered URL(s) remain unchecked (the reader kept getting unreadable answers)" in sentence
    assert any(line == "Asked for and not read: 5 reader challenged." for line in panel.summary_lines(section))
    # Dead links are the site's own answers: they never count as the reader being turned away.
    dead = {**pages, f"{ROOT}/": doc("Home", "<h1>Home</h1><p>" + "Words. " * 60 + "</p>" + "".join(f'<a href="{ROOT}/gone{n}">x</a>' for n in range(1, 9)) + f'<a href="{ROOT}/p1">p1</a>')}
    quiet = reader.apply(blocked_audit(), CFG, client_for(tmp_path / "dead", Firecrawl(dead)), Options(read_always=True, max_pages=50))
    assert quiet["pages_read"] == 2 and not quiet.get("stopped_because") and quiet["coverage"]["causes"] == {"error_status": 8}


def test_every_kind_of_unread_page_has_its_own_cause():
    cause = reader.page_cause
    assert cause({"outcome": "read"}) is None and cause({"outcome": "blocked", "status": 403}) == "reader_challenged"
    assert cause({"outcome": "redirected_out_of_scope"}) == "redirect_to_another_site" and cause({"outcome": "redirected"}) == "redirect_within_the_site"
    assert cause({"outcome": "error", "status": 404}) == "error_status" and cause({"outcome": "error", "status": 200}) == "empty_document"
    assert cause({"outcome": "error", "status": None}) == "no_status"  # A18 (W1): only a 2xx is an empty document
    assert cause({"outcome": "error", "status": 302}) == "error_status"
    assert cause({"outcome": "failed", "reason": "Firecrawl could not load the page as a website (HTTP 500): x"}) == "provider_could_not_load"
    assert cause({"outcome": "failed", "reason": "Firecrawl did not answer (ReadTimeout); it may have been charged and was not retried"}) == "timeout_or_no_answer"
    assert cause({"outcome": "failed", "reason": "this audit's Firecrawl requests would reach 12 credits, above the 10 confirmed"}) == "credit_or_request_limit"
    assert cause({"outcome": "failed", "reason": "Firecrawl refused the request"}) == "provider_refused"


# -- time -----------------------------------------------------------------------------------------------------------
def test_the_readers_share_of_the_time_is_kept_up_front_and_the_assumption_can_be_changed(monkeypatch, no_lookups):
    assert READER_SECONDS_PER_PAGE == 8.0 and reader_seconds_per_page() == 8.0 and reader_allowance_s(50, 1.0) == 450.0
    monkeypatch.setenv("MAYA_AUDIT_READER_SECONDS_PER_PAGE", "20")
    assert reader_seconds_per_page() == 20.0 and reader_allowance_s(50, 1.0) == 1050.0 and reader_allowance_s(50, 1.0, 5.0) == 300.0
    for bad in ("0", "abc", "9999"):
        monkeypatch.setenv("MAYA_AUDIT_READER_SECONDS_PER_PAGE", bad)
        assert reader_seconds_per_page() == 8.0
    monkeypatch.delenv("MAYA_AUDIT_READER_SECONDS_PER_PAGE")
    # Maya's own crawl stops at the limit less the reserve; the reader may use the rest.
    kept = blocked_audit(time_limit_s=600.0, reader_reserve_s=450.0)
    plain = blocked_audit(time_limit_s=600.0)
    assert 430 < kept.deadline_mono - kept.started_mono <= 601 and kept.deadline_mono - kept.started_mono > 590
    assert 590 < plain.deadline_mono - plain.started_mono <= 601
    from maya_audit import cli
    args = cli._parser().parse_args(["crawl", "https://example.com/", "--max-pages", "50"])
    args.reader_planned = False
    without = cli._crawl_config(args)
    args.reader_planned = True
    with_reader = cli._crawl_config(args)
    # 5 requests at once (DECISIONS 294): 50 pages x max(1 s gap, 8 s / 5) = 80 s (one at a time it was 50 x 9 = 450 s).
    assert without.reader_reserve_s == 0 and with_reader.reader_reserve_s == 80.0 and with_reader.time_limit_s == without.time_limit_s + 80.0
    slower = cli._parser().parse_args(["crawl", "https://example.com/", "--max-pages", "50", "--reader-seconds-per-page", "20"])
    slower.reader_planned = True
    assert cli._crawl_config(slower).reader_reserve_s == 200.0  # 50 x max(1, 20 / 5)
    given = cli._parser().parse_args(["crawl", "https://example.com/", "--max-pages", "50", "--time-limit", "400"])
    given.reader_planned = True
    assert cli._crawl_config(given).time_limit_s == 400 and cli._crawl_config(given).reader_reserve_s == 80  # its own 80 s, at most half of a limit that was given


def test_the_time_split_shows_what_the_assumption_buys():
    fast, typical, slow = (bench.time_split(8.0, answer) for answer in (2.0, 8.0, 20.0))
    assert (fast["pages_read"], typical["pages_read"]) == (50, 50) and 15 < slow["pages_read"] < 30  # eight seconds is not enough for a twenty-second reader
    assert bench.time_split(20.0, 20.0)["pages_read"] == 50
    before = bench.time_split(8.0, 4.0, crawl_takes_s=840.0, kept_for_reader=False, limit_s=840.0)
    after = bench.time_split(8.0, 4.0, crawl_takes_s=390.0, kept_for_reader=True)
    assert before["pages_read"] == 0 and after["pages_read"] == 50


# -- the benchmark's own claims ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    wanted = {"static", "restaurant", "tr_en", "sitemap_only", "javascript", "clinic_challenged", "both_challenged", "reader_turned_away",
              "shop_50_challenged", "saas_50_challenged", "shop_50_open"}
    out = {}
    for number, scenario in enumerate(s for s in bench.scenarios() if s.name in wanted):
        folder = tmp_path_factory.mktemp(f"bench{number}")
        out[scenario.name] = (scenario, bench.run(scenario, bench.BEFORE, folder / "b"), bench.run(scenario, bench.AFTER, folder / "a"))
    return out


def test_benchmark_more_of_the_right_pages_are_read_where_it_was_possible(measured):
    _s, before, after = measured["clinic_challenged"]
    assert (before["readable"], after["readable"]) == (37, 50) and after["sitemap_found"] == 50 and after["outcome"] == "COMPLETED" and after["key_read"] == 1
    _s, before, after = measured["shop_50_challenged"]
    assert before["readable"] == after["readable"] == 50 and after["parts_of_site"] > before["parts_of_site"] + 5  # the same fifty requests, more kinds of page
    assert after["key_read"] == 1 and after["why_pending"] == "page_cap" and after["outcome"] == "INCOMPLETE" and after["pending"] == 471
    _s, before, after = measured["reader_turned_away"]
    assert before["readable"] == after["readable"] == 8 and after["requests"] < before["requests"] / 2 and after["credits"] < before["credits"] / 2
    assert after["causes"] == {"reader_challenged": 5} and after["why_pending"] == "reader_kept_failing" and after["pending"] > 0
    _s, before, after = measured["javascript"]
    assert after["readable"] == 9 and after["usable"] == 9 and after["level"] == "complete_sample"  # the menu exists only in the reader's document
    _s, before, after = measured["both_challenged"]
    assert after["readable"] == 0 and after["outcome"] == "DEGRADED" and after["causes"] == {"reader_challenged": 1} and after["requests"] == 1
    _s, _b, open_shop = measured["shop_50_open"]
    assert measured["shop_50_challenged"][2]["parts_of_site"] == open_shop["parts_of_site"]  # a challenged site is now sampled as an open one is


def test_benchmark_healthy_sites_are_unchanged_and_gain_no_findings(measured):
    for name in ("static", "restaurant", "tr_en", "sitemap_only"):
        scenario, before, after = measured[name]
        assert scenario.healthy and after["readable"] == before["readable"] == len(scenario.pages), name
        assert (after["problems"], after["notes"]) == (before["problems"], before["notes"]) and after["outcome"] == "COMPLETED", name
        assert after["requests"] == before["requests"] and after["credits"] == before["credits"] and after["pending"] == 0, name
        assert after["credits"] <= after["max_credits"]


def test_the_written_benchmark_is_the_one_the_script_produces_in_shape():
    text = (Path(__file__).parents[1] / "docs" / "COVERAGE-BENCHMARK.md").read_text(encoding="utf-8")
    for heading in ("# Coverage benchmark: before and after Phase 2", "## Why pages were not read (after)", "## Healthy sites: no new findings",
                    "## Time and memory", "## The time kept for the reader"):
        assert heading in text, heading
    assert all(scenario.about in text for scenario in bench.scenarios())


def test_one_figure_for_known_and_unread_pages_when_a_reader_read_some_maya_did_not_fetch():
    from types import SimpleNamespace
    from maya_audit.report import known_unread
    result = SimpleNamespace(not_fetched_urls=[f"{ROOT}/p{n}" for n in range(110)])
    assert known_unread(result, None) == 110 and known_unread(result, {"used": False, "coverage": {"known_urls_not_requested": 3}}) == 110
    read = {"used": True, "pages": [{"url": f"{ROOT}/", "outcome": "read"}], "coverage": {"known_urls_not_requested": 85}}
    assert known_unread(result, read) == 85  # the reader read 25 of the 110: every sentence says 85
    assert known_unread(result, {"used": True, "pages": [{"url": f"{ROOT}/", "outcome": "blocked"}], "coverage": {"known_urls_not_requested": 0}}) == 110
