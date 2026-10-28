"""Round 2, run 2: empty pages, server error text, and a browser against Googlebot's user agent on a site whose ownership
is not verified (DECISIONS 204, 205; docs/FALSE-ALARMS.md FA-023; LG-75, LG-76, LG-77).

- A page that answers 200 and sends nothing (under 512 bytes, no title, no visible text) is the site's own answer, but
  not a page: IDX-1 reports it, and the content checks, PRF-1, the page reader and INT-1's "all pages" do not count it.
- A server error message with the server's file path is reported (the account folder masked); a tutorial quoting one
  is not.
- Without ownership, ACC-4 compares a browser with Googlebot's user agent on at most 3 URLs, one request each, tagged,
  never retried, and only where robots.txt allows Googlebot; INT-4 stays compliant.

Every site is made up and held in memory; nothing is fetched from the internet.
"""
import httpx

from maya_audit.classify import empty_response, error_disclosure, mask_server_path
from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, reader
from maya_audit.firecrawl.reader import page_cause
from maya_audit.perf_data import choose_sample
from maya_audit.probes import BROWSER_USER_AGENT
from maya_audit.registry import entry
from test_brand_and_launch_gate import no_lookups  # noqa: F401
from test_false_alarms import HTML_TYPE, KAFE, QUIET, TR, answer, audited
from test_firecrawl import Firecrawl, client_for

GOOGLEBOT = entry("Googlebot").probe_user_agent
FATAL = ("<br />\n<b>Fatal error</b>:  Uncaught Error: Call to undefined function demo_kafe_menu() in "
         "/home/u812345/public_html/wp-content/themes/kafe/header.php on line 9<br />")
EMPTY = httpx.Response(200, headers=HTML_TYPE, content=b"")


def by_title(check, words):
    return [f for f in check.findings if words in f.title]


# -- the rule itself --------------------------------------------------------------------------------------------------------
def test_an_empty_wrapper_is_empty_and_a_short_page_with_a_title_and_a_sentence_is_not():
    wrapper = b'<html><head></head><body><script>window.dataLayer=window.dataLayer||[];dl.push({})</script>\xe2\x80\x8b</body></html>'
    assert len(wrapper) < 512 and empty_response(200, "text/html", wrapper, False)
    assert empty_response(200, None, b"", False) and empty_response(204, "text/html; charset=utf-8", b"   \n", False)
    short = b'<!doctype html><html><head><title>Demo Kafe</title></head><body><p>We serve coffee every day.</p></body></html>'
    assert len(short) < 512 and not empty_response(200, "text/html", short, False)
    assert not empty_response(200, "text/html", b"<html><body><p>Open from nine.</p></body></html>", False)
    # Healthy and out of scope: a 600-byte page, an answer cut short, a 404, a file that is not HTML.
    assert not empty_response(200, "text/html", b"<html><body>" + b" " * 600 + b"</body></html>", False)
    assert not empty_response(200, "text/html", b"", True)
    assert not empty_response(404, "text/html", b"", False)
    assert not empty_response(200, "application/json", b"{}", False)


def test_a_server_error_with_a_path_is_found_and_masked_and_an_article_quoting_one_is_not():
    found = error_disclosure(FATAL.encode(), 500, "text/html")
    assert found and "/home/u8…/public_html/wp-content/themes/kafe/header.php on line 9" in found["line"]
    assert "u812345" not in found["line"] and mask_server_path("/home/demo/x") == "/home/de…/x"
    # Short 200 answer, and a message printed before the page starts: both count.
    assert error_disclosure(FATAL.encode(), 200, "text/html")
    assert error_disclosure((FATAL + "<!DOCTYPE html><html><body>" + "x" * 6000 + "</body></html>").encode(), 200, "text/html")
    # An article of 30 KB that quotes the same error inside <pre>: not the server's own message.
    article = ("<!DOCTYPE html><html><head><title>Fixing PHP errors</title></head><body><article><p>" + "Words about PHP. " * 1700
               + f"</p><pre>{FATAL}</pre></article></body></html>").encode()
    assert len(article) > 28_000 and error_disclosure(article, 200, "text/html") is None
    # A marker without a server path, or a path without a marker, is not enough.
    assert error_disclosure(b"Fatal error: Uncaught Error in x.php on line 9", 500, "text/html") is None
    assert error_disclosure(b"see /var/www/html for files", 500, "text/html") is None


# -- empty pages through the whole audit ------------------------------------------------------------------------------------
def kafe_with_an_empty_page(**options):
    links = '<a href="/a/">A</a> <a href="/menu">Menü</a> <a href="/iletisim">İletişim</a>'
    return audited({"/": answer(links, title="Demo Kafe"), "/a/": EMPTY, "/menu": answer(title="Menü | Demo Kafe"),
                    "/iletisim": answer(title="İletişim | Demo Kafe")}, sitemap=("/", "/a/", "/menu", "/iletisim"), **options)


def test_an_empty_page_is_reported_by_idx1_and_left_out_of_content_checks_speed_and_the_page_reader(tmp_path, no_lookups):
    outcome = kafe_with_an_empty_page()
    page = next(p for p in outcome.result.pages if p.url == KAFE + "/a/")
    assert page.fetch_class.value == "ok" and page.content_checks_eligible is False and not page.readable_document()
    assert page.analysis["empty_response"] == {"body_bytes": 0, "limit": 512}
    assert "empty response: status 200 with 0 bytes (under 512)" in page.classification_evidence

    [empty] = by_title(outcome.by_id["IDX-1"], "empty page")
    assert empty.title == "1 page(s) answer with an empty page (under 512 bytes)"
    # Repeated non-key failure; share alone does not establish critical impact. These audits run with probes off, so the
    # page is not asked again as a browser (first review C1/C2): two answers to one client stay S3 until another
    # client confirms them (tests/test_gx1_empty_browser_check.py has the S2 and bot-specific cases).
    assert (empty.severity.value, empty.confidence.value) == ("S3", "verified")
    assert empty.evidence["observation_strength"] == "repeated_empty_same_client_only"
    assert empty.scope["urls"] == [KAFE + "/a/"] and empty.evidence["pages"][0]["refetch"]["status"] == 200
    assert "LG-75" in empty.launch_gated
    # Refetched once, within the cap, and empty again.
    assert [r.url for r in outcome.result.requests if r.purpose == "page_refetch"] == [KAFE + "/a/"]

    # The content checks do not list it as a page without a title or a heading.
    for check_id in ("STR-1", "STR-2"):
        assert all(KAFE + "/a/" not in f.scope["urls"] for f in outcome.by_id[check_id].findings), check_id
    # PRF-1 does not take an empty page as its sample of the site's speed.
    assert KAFE + "/a/" not in [row["url"] for row in choose_sample(outcome.result, CrawlConfig(**QUIET))]
    # INT-1 does not say "all pages" of pages that sent nothing.
    int1 = next(g for g in outcome.gates if g.check_id == "INT-1")
    assert int1.state == "ok" and int1.summary == (
        "4 fetched pages were answered by the site itself, none blocked or rate-limited; 1 of them were empty "
        "(status 200 with under 512 bytes; see IDX-1).")
    assert int1.evidence["empty_responses"]["count"] == 1
    # The page reader is not asked for it.
    api = Firecrawl({KAFE + "/": answer(title="Demo Kafe").text, KAFE + "/menu": answer(title="Menü").text,
                     KAFE + "/iletisim": answer(title="İletişim").text})
    reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options(read_always=True, max_pages=10))
    assert api.urls and KAFE + "/a/" not in api.urls


def test_a_page_empty_only_once_is_an_observation_and_a_healthy_short_page_is_not_empty(no_lookups):
    once = lambda n: EMPTY if n == 1 else answer(title="Menü | Demo Kafe")  # noqa: E731
    outcome = audited({"/": answer('<a href="/menu">Menü</a>', title="Demo Kafe"), "/menu": once})
    assert not by_title(outcome.by_id["IDX-1"], "empty page")
    assert any(o.get("metric", "").startswith("empty on some attempts only") for o in outcome.by_id["IDX-1"].observations)

    six_hundred = httpx.Response(200, headers=HTML_TYPE, text="<!doctype html><html><head><title>Menü | Demo Kafe</title></head>"
                                 "<body><p>" + "Kahve " * 90 + "</p></body></html>")
    healthy = audited({"/": answer('<a href="/menu">Menü</a>', title="Demo Kafe"), "/menu": six_hundred})
    assert 550 < len(six_hundred.content) < 700 and not by_title(healthy.by_id["IDX-1"], "empty page")
    assert next(g for g in healthy.gates if g.check_id == "INT-1").summary.startswith("All 2 fetched pages returned")


def test_a_reader_document_of_106_bytes_is_an_empty_document_not_a_page(tmp_path, no_lookups):
    # Maya's own crawl stops at one page, so /kampanya (in the sitemap) is never fetched by Maya.
    outcome = audited({"/": answer(title="Demo Kafe"), "/kampanya": answer(title="Kampanya")}, sitemap=("/", "/kampanya"), max_pages=1)
    assert KAFE + "/kampanya" not in [p.url for p in outcome.result.pages]
    wrapper = '<html><head></head><body><script src="/app.js"></script><div id="root"></div></body></html>'
    assert len(wrapper) < 512
    api = Firecrawl({KAFE + "/": answer(title="Demo Kafe").text, KAFE + "/kampanya": wrapper})
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options(read_always=True, max_pages=10))
    [row] = [r for r in info["pages"] if r["url"] == KAFE + "/kampanya"]
    assert row["outcome"] == "error" and page_cause(row) == "empty_document"


def test_a_server_error_message_with_a_path_is_reported_with_the_account_folder_masked(no_lookups):
    broken = httpx.Response(500, headers=HTML_TYPE, text=FATAL)
    article = httpx.Response(200, headers=HTML_TYPE, text=(
        "<!DOCTYPE html><html><head><title>PHP hataları | Demo Kafe</title></head><body><main><h1>PHP hataları</h1><p>"
        + TR * 90 + f"</p><pre>{FATAL}</pre></main></body></html>"))
    outcome = audited({"/": answer('<a href="/x">x</a> <a href="/blog/php">PHP</a>', title="Demo Kafe"), "/x": broken,
                       "/blog/php": article})
    [shown] = by_title(outcome.by_id["IDX-1"], "server error message")
    assert shown.title == "1 page(s) show a server error message with the server's file paths"
    assert (shown.severity.value, shown.confidence.value) == ("S3", "verified") and shown.scope["urls"] == [KAFE + "/x"]
    line = shown.evidence["pages"][0]["line"]
    assert "/home/u8…/public_html/" in line and "u812345" not in str(shown.evidence) and "LG-76" in shown.launch_gated
    # The raw text stays in memory only: the page record written to a report has no _error_text.
    from maya_audit.report import build_report
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert all("_error_text" not in p for p in report["crawl"]["pages"]) and "u812345" not in str(report)


# -- ACC-4 without ownership: a browser against Googlebot's user agent ------------------------------------------------------
def ua_site(robots_txt="User-agent: *\nAllow: /\n", browser_gets_empty=False, **options):
    """Three addresses, one of them an empty page, behind a firewall that answers Googlebot's user agent with a 500 that
    carries the error text. A browser gets the real page, or (`browser_gets_empty`) an empty 200 everywhere."""
    asked = []

    def respond(request):
        ua, path = request.headers.get("user-agent", ""), request.url.path
        asked.append((path, ua, request.headers.get("x-maya-probe")))
        if path == "/robots.txt":
            return httpx.Response(200, text=robots_txt, headers={"content-type": "text/plain"})
        if path == "/sitemap.xml":
            return httpx.Response(404, text="none")
        if "Googlebot" in ua:
            return httpx.Response(500, headers=HTML_TYPE, text=FATAL)
        if ua == BROWSER_USER_AGENT and browser_gets_empty:
            return EMPTY
        links = '<a href="/menu/kahve">Kahve</a> <a href="/menu/cay">Çay</a> <a href="/bos/">Boş</a>'
        return {"/": answer(links, title="Demo Kafe"), "/menu/kahve": answer(title="Kahve | Demo Kafe"),
                "/menu/cay": answer(title="Çay | Demo Kafe"), "/bos/": EMPTY}.get(path, answer(title="Yok", status=404))

    from maya_audit.audit import run_audit
    config = CrawlConfig(**{**QUIET, "probes_enabled": True, "max_pages": 10, **options})
    outcome = run_audit(KAFE + "/", config, httpx.MockTransport(respond))
    outcome.by_id = {c.check_id: c for c in outcome.checks}
    outcome.asked = asked
    outcome.int4 = next(g for g in outcome.gates if g.check_id == "INT-4")
    return outcome


def test_googlebot_answered_with_a_server_error_where_a_browser_got_200_is_high_estimated_and_noted(no_lookups):
    outcome = ua_site()
    checks = [r for r in outcome.result.requests if r.purpose == "ua_check"]
    assert len(checks) == 6 and {r.user_agent for r in checks} == {BROWSER_USER_AGENT, GOOGLEBOT}
    assert all(r.extra_headers.get("X-Maya-Probe") == "ua-differential" for r in checks)
    # The homepage and the pages of the largest template; the empty page is not picked (DECISIONS 216).
    assert [r.url.removeprefix(KAFE) for r in checks][::2] == ["/", "/menu/cay", "/menu/kahve"]
    assert not [r for r in outcome.result.requests if r.purpose == "probe"]

    acc4 = outcome.by_id["ACC-4"]
    [finding] = acc4.findings
    assert finding.title == "A request with Googlebot's user agent got 500 on 3 of 3 URL(s) where a browser got 200"
    assert (finding.severity.value, finding.confidence.value) == ("S3", "estimated") and "LG-77" in finding.launch_gated
    assert any(n.startswith("Measured with a spoofed user agent from Maya's own address, not by Google") for n in finding.notes)
    assert acc4.status == "findings" and acc4.summary.startswith(
        "Firewall blocking was only partly assessed: a browser and Googlebot's user agent were compared on 3 URL(s)")
    assert any(p["part"] == "other AI crawlers' user agents" for p in acc4.coverage["not_assessed"])
    # The error text Googlebot's user agent was shown is IDX-1's finding too, masked.
    [shown] = by_title(outcome.by_id["IDX-1"], "server error message")
    assert "u812345" not in str(shown.evidence) and "Googlebot" in shown.evidence["pages"][0]["seen_by"]
    assert outcome.int4.state == "compliant", outcome.int4.summary
    assert "6 tagged request(s) compared a browser with Googlebot's user agent" in outcome.int4.summary


def test_googlebot_is_not_sent_where_robots_txt_disallows_it(no_lookups):
    outcome = ua_site("User-agent: *\nAllow: /\n\nUser-agent: Googlebot\nDisallow: /menu/\n")
    sent = [(r.url.removeprefix(KAFE), r.user_agent) for r in outcome.result.requests if r.purpose == "ua_check"]
    assert sent and not [path for path, ua in sent if ua == GOOGLEBOT and path.startswith("/menu/")]
    assert not [path for path, ua, _ in outcome.asked if "Googlebot" in ua and path.startswith("/menu/")]
    pairs = outcome.result.access.ua_check["pairs"]
    # Both sampled /menu/ pages (the largest template's first two, DECISIONS 216) are disallowed for Googlebot.
    assert [p["reason"] for p in pairs if not p["assessed"]] == ["not assessed (robots.txt)"] * 2
    assert outcome.int4.state == "compliant", outcome.int4.summary


def test_identical_answers_make_no_finding_and_an_owned_site_gets_the_full_check(run_audit_scenario):
    healthy = run_audit_scenario("acc_waf_not_owned")
    acc4 = healthy.checks["ACC-4"]
    assert acc4.findings == [] and acc4.status == "partial"  # nothing found; the other AI crawlers were not tested
    assert all(p["outcome"] == "same" for p in healthy.result.access.ua_check["pairs"] if p["assessed"])

    owned = run_audit_scenario("acc_ai_friendly")
    assert owned.result.access.ua_check is None and owned.result.access.probes is not None
    assert not [r for r in owned.result.requests if r.purpose == "ua_check"]
    assert owned.checks["ACC-4"].status == "pass"


def test_a_single_page_audit_compares_only_that_address(no_lookups):
    outcome = ua_site(single_page=True)
    checks = [r for r in outcome.result.requests if r.purpose == "ua_check"]
    assert [(r.url, r.user_agent) for r in checks] == [(KAFE + "/", BROWSER_USER_AGENT), (KAFE + "/", GOOGLEBOT)]
