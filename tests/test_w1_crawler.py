"""Review fixes of the crawler, robots and access package (W1): docs/review-fixes/w1-crawler.md names each item."""

from __future__ import annotations

import gzip
import tracemalloc
import zlib
from types import SimpleNamespace

from fakeserver import FakeServer
from fakeserver.server import Response, Site
from maya_audit.checks import perf
from maya_audit.fetcher import Fetcher
from maya_audit.robots import decide, parse_robots

UA = "MayaAuditBot/0.1 (+test)"


def fetcher(**kwargs) -> Fetcher:
    return Fetcher(UA, 10.0, 0.0, **kwargs)


# -- H17: a rule above the first User-agent line --------------------------------------------------------------------
def test_rules_before_any_user_agent_are_kept_with_their_line_and_text_and_apply_to_nobody():
    robots = parse_robots("Disallow: /cdn-cgi/\nCrawl-delay: 5\n\nUser-agent: *\nDisallow: /checkout\n")
    assert robots.ungrouped == [(1, "Disallow: /cdn-cgi/"), (2, "Crawl-delay: 5")]
    assert decide(robots, "MayaAuditBot", "https://e.com/cdn-cgi/x").allowed
    assert not decide(robots, "MayaAuditBot", "https://e.com/checkout").allowed
    assert robots.groups[0].crawl_delay is None
    assert parse_robots("User-agent: *\nDisallow: /a\n").ungrouped == []


# -- A6: bounded decompression, A10: wire bytes -----------------------------------------------------------------------
def test_a_gzip_bomb_is_cut_at_the_body_cap_without_decoding_it_whole():
    bomb = gzip.compress(b"\0" * (64 * 1024 * 1024), 9)
    site = Site({"/bomb": Response(body=bomb, headers={"Content-Encoding": "gzip"})})
    with FakeServer(site) as server:
        f = fetcher()
        tracemalloc.start()
        response = f.get(server.base_url + "/bomb", "page", 1024 * 1024)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        f.close()
        sent = server.requests[0].headers.get("accept-encoding")
    assert response.error is None and response.truncated and len(response.body) == 1024 * 1024
    assert peak < 16 * 1024 * 1024, peak  # httpx's own decoding expanded each network chunk whole (~150 MB measured)
    assert sent == "gzip, deflate"
    assert response.wire_bytes is not None and 0 < response.wire_bytes <= len(bomb)


def test_gzip_and_both_kinds_of_deflate_decode_to_the_same_body():
    text = ("<html><title>Kokular</title><p>" + "koku " * 4000 + "</p></html>").encode()
    raw = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    raw_deflate = raw.compress(text) + raw.flush()
    site = Site({"/g": Response(body=gzip.compress(text), headers={"Content-Encoding": "gzip"}),
                 "/z": Response(body=zlib.compress(text), headers={"Content-Encoding": "deflate"}),
                 "/r": Response(body=raw_deflate, headers={"Content-Encoding": "deflate"}),
                 "/plain": Response(body=text)})
    with FakeServer(site) as server:
        f = fetcher()
        bodies = {p: f.get(server.base_url + p, "page", 5 * 1024 * 1024) for p in ("/g", "/z", "/r", "/plain")}
        small = f.get(server.base_url + "/g", "page", 100)
        f.close()
    assert all(r.body == text and not r.truncated and r.error is None for r in bodies.values())
    assert bodies["/plain"].wire_bytes == len(text) and bodies["/g"].wire_bytes < len(text)
    assert small.truncated and small.body == text[:100]


def test_a_body_that_is_not_the_gzip_it_claims_is_a_decoding_error_not_a_crash():
    site = Site({"/bad": Response(body=b"not gzip at all", headers={"Content-Encoding": "gzip"})})
    with FakeServer(site) as server:
        f = fetcher()
        response = f.get(server.base_url + "/bad", "page", 1024)
        f.close()
    assert response.status is None and response.error.startswith("http_error (DecodingError")


# -- A9: an empty 2xx is neutral for pacing ---------------------------------------------------------------------------
def test_empty_answers_neither_narrow_the_gap_nor_stop_narrowing():
    f = fetcher()
    f.adaptive, f.site_host, f.delay_s, f.pacing_clean_answers = True, "e.com", 1.0, 3
    for _ in range(10):
        f._pace_after("e.com", "page", 200, None, 5.0, empty=True)
    assert f.delay_s == 1.0 and f.narrowings == [] and f.narrowing_stopped is None
    for _ in range(3):
        f._pace_after("e.com", "page", 200, None, 5.0)
    assert f.delay_s == 0.75
    f.close()


def test_an_empty_page_from_a_live_server_does_not_narrow_the_gap():
    site = Site({"/": Response(body="")})
    with FakeServer(site) as server:
        f = fetcher()
        f.adaptive, f.site_host, f.per_host, f.delay_s, f.min_delay_s, f.pacing_clean_answers = True, "127.0.0.1", True, 0.01, 0.0, 2
        for _ in range(6):
            f.get(server.base_url + "/", "page", 1024)
        f.close()
    assert f.narrowings == []


# -- H28: the HTML is not cached at the CDN ---------------------------------------------------------------------------
def _page(url, headers, status=200, ttfb=900.0):
    return SimpleNamespace(url=url, headers=headers, status=status, ttfb_ms=ttfb, content_type="text/html", view="raw")


def test_html_marked_private_that_the_cdn_did_not_cache_is_one_info_finding_with_the_status_values():
    # G05 (gx3): every page carrying a CDN status must say miss, and Cache-Control must forbid a shared copy.
    pages = [_page("https://e.com/", {"cache-control": "private, max-age=0", "cf-cache-status": "DYNAMIC"}),
             _page("https://e.com/a", {"cache-control": "no-store", "cf-cache-status": "MISS"}),
             # No CDN word at all: not counted either way.
             _page("https://e.com/c", {"cache-control": "private"})]
    [finding] = perf._cdn_cache_findings(pages, set(), {"value": 900.0, "pages": 3})
    assert finding.severity.value == "Info" and "not cached at the CDN" in finding.title and "DYNAMIC" in finding.title
    assert [p["url"] for p in finding.evidence["pages"]] == ["https://e.com/", "https://e.com/a"]
    # Cacheable at the edge, or a page the CDN served from its cache: the rule no longer holds on (nearly) every page.
    mixed = pages + [_page("https://e.com/b", {"cache-control": "public, s-maxage=300", "cf-cache-status": "DYNAMIC"}),
                     _page("https://e.com/d", {"cache-control": "max-age=600", "cf-cache-status": "HIT"})]
    assert perf._cdn_cache_findings(mixed, set(), None) == []


# -- B05, B06, H26: ACC-3 -------------------------------------------------------------------------------------------
def _html_page(url, meta=(), headers=None):
    analysis = {"meta": [{"name": "robots", "content": c} for c in meta], "has_main_region": False, "main_region_chars": 0,
                "visible_chars": 100, "main_region_nosnippet_chars": 0, "data_nosnippet_chars": 0, "outside_head": {}}
    return SimpleNamespace(url=url, analysis=analysis, headers=headers or {}, content_checks_eligible=True, status=200,
                           outlinks=[], content_type="text/html")


def _acc3(pages, sitemap=(), key_pages=()):
    from maya_audit.checks.access import acc3_page_controls
    from maya_audit.config import CrawlConfig

    result = SimpleNamespace(pages=pages, sitemap_urls=list(sitemap), sitemap_docs=[], origin="https://e.com")
    return acc3_page_controls(result, CrawlConfig(key_pages=tuple(key_pages)))


def test_noindex_in_a_header_is_read_without_an_html_analysis():
    from maya_audit.directives import noindex_directives

    assert noindex_directives(None, {"x-robots-tag": "noindex"}) == ["X-Robots-Tag: noindex"]
    assert noindex_directives(None, {}) == []


def test_a_sitemap_page_with_noindex_is_one_s3_finding():  # review G16: no second S2 for the sitemap side
    check = _acc3([_html_page("https://e.com/a", ["noindex"]), _html_page("https://e.com/k", ["noindex"]),
                   _html_page("https://e.com/o", ["noindex"])], sitemap=["https://e.com/a", "https://e.com/k"],
                  key_pages=["/k"])
    by_title = {f.title: f.severity.value for f in check.findings}
    assert by_title == {"noindex via meta on 1 page(s)": "S1",
                        "noindex via meta on 1 page(s) the sitemap lists: check that this is intended": "S3",
                        "noindex via meta (page intent should be reviewed) on 1 page(s)": "Info"}


def test_unavailable_after_a_past_date_is_a_noindex_and_a_future_one_a_note():
    check = _acc3([_html_page("https://e.com/old", ["unavailable_after: Wed, 03 Nov 2021 15:00:00 GMT"]),
                   _html_page("https://e.com/new", headers={"x-robots-tag": "unavailable_after: 2999-01-01"})],
                  key_pages=["/old"])
    by_title = {f.title: f.severity.value for f in check.findings}
    assert by_title == {"unavailable_after (date passed) via meta on 1 page(s)": "S1",
                        "unavailable_after 2999-01-01 via X-Robots-Tag on 1 page(s)": "Info"}


# -- B13: ANS-4 points only at findings that block the engine's search or live token -------------------------------
def test_ans4_links_an_engine_only_to_findings_that_block_its_search_or_live_tokens():
    from maya_audit.checks.answers import _blocked_tokens_for
    from maya_audit.findings import CheckResult

    def finding(title, blocked):
        return SimpleNamespace(check_id="ACC-2", title=title, evidence={"blocked_tokens": blocked}, severity="S1", id=title)

    acc2 = CheckResult("ACC-2", "t", "findings", "s", [
        finding("robots.txt line 3 (Disallow: /) blocks training bot(s) GPTBot sitewide", ["GPTBot"]),
        finding("Policy mismatch: declared policy blocks training bots, but robots.txt allows OAI-SearchBot on at least one sampled URL", []),
        finding("robots.txt line 5 (Disallow: /) blocks search bot(s) OAI-SearchBot sitewide", ["OAI-SearchBot"]),
        finding("robots.txt line 7 (Disallow: /) blocks training bot(s) Google-Extended sitewide", ["Google-Extended"])])
    assert [b["title"] for b in _blocked_tokens_for("chatgpt", [acc2])] == [
        "robots.txt line 5 (Disallow: /) blocks search bot(s) OAI-SearchBot sitewide"]
    assert _blocked_tokens_for("google-ai-overview", [acc2]) == []
    assert len(_blocked_tokens_for("gemini", [acc2])) == 1  # Google-Extended governs Gemini's grounding


# -- B14: registry rows and retired tokens ----------------------------------------------------------------------------
def test_new_registry_rows_send_no_probe_and_are_gated():
    from maya_audit.probes import probe_bots
    from maya_audit.registry import entry

    for token in ("Bytespider", "GoogleOther", "Google-CloudVertexBot", "Meta-ExternalFetcher"):
        row = entry(token)
        assert row.probe_user_agent is None and row.launch_gated
    assert not {b.token for b in probe_bots()} & {"Meta-ExternalFetcher"}


def test_rules_for_retired_anthropic_tokens_are_an_info_note():
    from maya_audit.checks.access import acc2_robots_rules
    from maya_audit.config import CrawlConfig
    from maya_audit.robots import policy_from_response

    text = b"User-agent: anthropic-ai\nUser-agent: Claude-Web\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    policy = policy_from_response("https://e.com/robots.txt", 200, None, text, 500 * 1024, [])
    access = SimpleNamespace(url_sample=[{"url": "https://e.com/", "why": "homepage"}])
    result = SimpleNamespace(origin="https://e.com", robots_policy_by_origin={"https://e.com": policy}, access=access,
                             pages=[], sitemap_urls=[], start_url="https://e.com/")
    check = acc2_robots_rules(result, CrawlConfig())
    [note] = [f for f in check.findings if "no longer" in f.title]
    assert note.title == "robots.txt has rules for anthropic-ai, claude-web, which no longer have any effect"
    assert note.severity.value == "Info" and note.evidence["blocked_tokens"] == []


# -- D-15: an empty or malformed IP-range file verifies nothing --------------------------------------------------------
def test_an_unusable_range_file_makes_requests_unverifiable_not_spoofed(tmp_path):
    from maya_audit.logs import analyze_logs

    log = tmp_path / "access.log"
    log.write_text('66.249.66.1 - - [10/Oct/2026:13:55:36 +0000] "GET / HTTP/1.1" 200 512 "-" '
                   '"Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"\n', encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text('{"creationTime": "2026-10-01", "ranges": []}', encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("not-a-network\n", encoding="utf-8")
    for ranges in (empty, bad):
        logs = analyze_logs((str(log),), "combined", (("OAI-SearchBot", str(ranges)),))
        stats = logs["bots"]["OAI-SearchBot"]
        assert stats["spoofed"] == 0 and stats["unverifiable"] == 1
        assert logs["ip_range_files"][0]["prefixes"] == 0 and "unusable" in logs["ip_range_files"][0]
    mixed = tmp_path / "mixed.txt"
    mixed.write_text("66.249.64.0/19\nnot-a-network\n", encoding="utf-8")
    logs = analyze_logs((str(log),), "combined", (("OAI-SearchBot", str(mixed)),))
    assert logs["bots"]["OAI-SearchBot"]["verified"] == 1 and logs["ip_range_files"][0]["malformed_entries"] == 1


# -- A7: an IPv4 address inside an IPv6 one, A8: a www move keeps https ---------------------------------------------
def test_ipv4_inside_ipv6_is_judged_by_the_ipv4_address():
    import pytest
    from maya_audit.urls import UnsafeTargetError, public_addresses

    for host in ("64:ff9b::a9fe:a9fe", "64:ff9b::a00:1", "::ffff:10.0.0.1", "2002:a9fe:a9fe::1", "64:ff9b:1::a9fe:a9fe",
                 "::ffff:127.0.0.1"):
        with pytest.raises(UnsafeTargetError):
            public_addresses(f"http://[{host}]/", allow_loopback=False)
    assert public_addresses("http://[64:ff9b::808:808]/", allow_loopback=False) == ["64:ff9b::808:808"]
    assert public_addresses("http://[2606:4700::1111]/", allow_loopback=False) == ["2606:4700::1111"]


def test_a_www_move_may_not_leave_https():
    from maya_audit.urls import is_allowed_origin_move

    assert not is_allowed_origin_move("https://e.com/", "http://www.e.com/")
    assert is_allowed_origin_move("https://e.com/", "https://www.e.com/")
    assert is_allowed_origin_move("http://e.com/", "https://www.e.com/")
    assert is_allowed_origin_move("http://www.e.com/", "http://e.com/")


# -- A5: a robots.txt that never stops redirecting --------------------------------------------------------------------
def test_a_robots_txt_still_redirecting_after_the_hops_is_unavailable_and_allows_crawling():
    from maya_audit.robots import policy_from_response

    policy = policy_from_response("https://e.com/robots.txt", 301, None, b"", 500 * 1024, ["h"] * 5)
    assert policy.mode == "allow_all" and "RFC 9309 §2.3.1.2" in policy.reason and not policy.stops_requests


# -- A12: one lock per site, A2: tracking parameters ------------------------------------------------------------------
def test_the_crawl_lock_is_the_site_and_its_port_not_the_origin_before_the_redirect():
    from maya_audit.urls import lock_key

    assert lock_key("http://e.com/") == lock_key("https://www.e.com/x") == "e.com"
    assert lock_key("https://blog.e.com/") == "blog.e.com"
    assert lock_key("http://127.0.0.1:8001/") != lock_key("http://127.0.0.1:8002/")


def test_links_that_differ_only_in_tracking_parameters_are_asked_for_once():
    from maya_audit.config import CrawlConfig
    from maya_audit.crawler import Crawler
    from maya_audit.urls import crawl_identity

    assert crawl_identity("https://e.com/a;jsessionid=X1?utm_source=x&b=2&a=1&PHPSESSID=9&gclid=z") == "https://e.com/a?a=1&b=2"
    body = ('<html><head><title>Ev</title></head><body><a href="/p?utm_source=mail">p</a><a href="/p?gclid=1">p</a>'
            '<a href="/p">p</a><a href="/q?id=3&PHPSESSID=abc">q</a><a href="/q?id=3&PHPSESSID=def">q</a></body></html>')
    page = '<html><head><title>P</title></head><body><p>Bir sayfa.</p></body></html>'
    site = Site({"/": Response(body=body), "/p": Response(body=page), "/q": Response(body=page)},
                fallback=Response(body=page))
    with FakeServer(site) as server:
        Crawler(CrawlConfig(request_delay_s=0, robots_samples=1, render_enabled=False, prf_enabled=False,
                            probes_enabled=False, refetch_delay_s=0)).run(server.base_url + "/")
        asked = [r.path for r in server.requests if r.route_path in ("/p", "/q")]
    assert asked == ["/p?utm_source=mail", "/q?id=3&PHPSESSID=abc"]


# -- A13: one retry for a 503 with Retry-After ------------------------------------------------------------------------
def test_a_503_with_a_short_retry_after_is_asked_once_more():
    from maya_audit.config import CrawlConfig
    from maya_audit.crawler import Crawler

    def flaky(site, request):
        site.state["n"] = site.state.get("n", 0) + 1
        if site.state["n"] == 1:
            return Response(503, "busy", {"Retry-After": "1"})
        return Response(body="<html><head><title>Ev</title></head><body><p>Merhaba.</p></body></html>")

    with FakeServer(Site({"/": flaky})) as server:
        result = Crawler(CrawlConfig(request_delay_s=0, robots_samples=1, render_enabled=False, prf_enabled=False,
                                     probes_enabled=False, refetch_delay_s=0)).run(server.base_url + "/")
    home = next(p for p in result.pages if p.url == server.base_url + "/")
    assert home.status == 200 and CrawlConfig().max_retry_after_s == 30.0


# -- A14, A15: sitemap files and addresses left out are said ----------------------------------------------------------
def test_sitemap_files_past_the_limit_and_addresses_on_another_origin_are_noted():
    from maya_audit.config import CrawlConfig
    from maya_audit.crawler import Crawler

    index = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
             + "".join(f"<sitemap><loc>{{base}}/s{i}.xml</loc></sitemap>" for i in range(4)) + "</sitemapindex>")
    urlset = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              '<url><loc>{base}/a</loc></url><url><loc>https://www.example.com/a</loc></url></urlset>')
    xml = "application/xml"
    site = Site({"/robots.txt": Response(body="User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"
                                              "Sitemap: https://cdn.example.com/sitemap.xml\n", content_type="text/plain"),
                 "/sitemap.xml": Response(body=index, content_type=xml),
                 **{f"/s{i}.xml": Response(body=urlset, content_type=xml) for i in range(4)}},
                fallback=Response(body="<html><head><title>A</title></head><body><p>A.</p></body></html>"))
    with FakeServer(site) as server:
        result = Crawler(CrawlConfig(request_delay_s=0, robots_samples=1, render_enabled=False, prf_enabled=False,
                                     probes_enabled=False, refetch_delay_s=0, max_sitemap_docs=3,
                                     max_pages=3)).run(server.base_url + "/")
    notes = " ".join(result.sitemap_notes)
    assert "read its limit of 3 sitemap file(s); 2 more were not read" in notes
    assert "https://cdn.example.com/sitemap.xml" in notes and "https://www.example.com/a" in notes


# -- A21, A22: what the unverified Googlebot check makes of an empty page, a 404 and a challenge ----------------------
def _answer(status, words=300, fetch_class="ok", empty=False, evidence=()):
    return {"status": status, "visible_words": words, "fetch_class": fetch_class, "empty_response": empty,
            "classification_evidence": list(evidence), "headers": {}, "content_type": "text/html", "title": "T",
            "body_sha256": str(words), "text_sha256": str(words), "body_bytes": words * 6, "location": None,
            "error_disclosure": None, "error": None}


def test_googlebot_checks_name_an_empty_page_a_404_and_a_cdn_challenge_apart():
    from maya_audit.config import CrawlConfig
    from maya_audit.probes import compare, ua_verdict

    cfg, browser = CrawlConfig(), _answer(200)
    assert compare(browser, _answer(200, words=0, empty=True), 0.5)[0] == "blocked"
    assert ua_verdict(browser, _answer(200, words=0, empty=True), cfg)[0] == "empty_for_bot"
    assert ua_verdict(browser, _answer(404, words=2), cfg)[0] == "not_found_for_bot"
    challenge = _answer(403, words=5, fetch_class="blocked", evidence=["header cf-mitigated: challenge"])
    assert ua_verdict(browser, challenge, cfg)[0] == "challenged"
    assert ua_verdict(browser, _answer(403, words=5, fetch_class="blocked", evidence=["status 403"]), cfg)[0] == "refused"


def test_a_challenge_to_the_unverified_googlebot_is_info_and_an_empty_page_s3():
    from maya_audit.checks.access import UA_CHECK_SEVERITY

    assert UA_CHECK_SEVERITY["challenged"].value == "Info" and UA_CHECK_SEVERITY["refused"].value == "S3"
    assert UA_CHECK_SEVERITY["empty_for_bot"].value == "S3" and UA_CHECK_SEVERITY["not_found_for_bot"].value == "S3"


# -- A23: a HEAD lost in transport gets one GET before the site is taken as silent -----------------------------------
def test_a_head_that_fails_in_transport_is_tried_once_with_get(monkeypatch):
    from maya_audit import external_links
    from maya_audit.config import CrawlConfig
    from maya_audit.fetcher import RawResponse

    calls = []
    monkeypatch.setattr(external_links, "room", lambda *a, **k: None)

    def get(url, purpose, limit, method="GET"):
        calls.append(method)
        if method == "HEAD":
            return RawResponse(url, None, {}, b"", False, 1, "connection_dropped (RemoteProtocolError)", "2026-10-21T10:00:00Z")
        return RawResponse(url, 200, {}, b"<p>ok</p>", False, 1, None, "2026-10-21T10:00:00Z")

    result = SimpleNamespace(pages=[], index=None)
    row = external_links.check(SimpleNamespace(get=get), result, CrawlConfig(), "https://help.example/a")
    assert calls == ["HEAD", "GET"] and row["verdict"] == "works"
    assert "https://help.example" not in result._external.quiet


# -- A26: the Google API key is a header --------------------------------------------
def test_the_crux_key_is_sent_in_a_header_not_in_the_address():
    import httpx
    from maya_audit import crux

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(404, json={})

    crux.collect("https://e.com", "SECRET-KEY", transport=httpx.MockTransport(handler))
    assert seen and "SECRET-KEY" not in str(seen[0].url) and seen[0].headers.get("x-goog-api-key") == "SECRET-KEY"


def test_an_unavailable_after_date_with_a_weekday_comma_stays_whole_also_when_scoped():
    from maya_audit.directives import parse_directive_list

    assert parse_directive_list("googlebot: unavailable_after: Wed, 03 Nov 2027 15:00:00 GMT", "*") == [
        ("googlebot", "unavailable_after", "Wed, 03 Nov 2027 15:00:00 GMT")]
    assert parse_directive_list("noindex, unavailable_after: Wednesday, 03-Nov-27 15:00:00 GMT, nofollow", "*") == [
        ("*", "noindex", None), ("*", "unavailable_after", "Wednesday, 03-Nov-27 15:00:00 GMT"), ("*", "nofollow", None)]
