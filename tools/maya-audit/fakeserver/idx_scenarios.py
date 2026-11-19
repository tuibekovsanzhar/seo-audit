"""Scripted websites (and fake Google/Bing APIs) for the IDX checks."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile

from .scenarios import Scenario, page, robots, sitemap
from .server import FakeServer, RequestSeen, Response, Site

FAST_IDX = {"request_delay_s": 0.0, "request_timeout_s": 1.0, "robots_sample_interval_s": 0.05,
            "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0, "prf_round_gap_s": 0.0,
            "render_enabled": False}
ARTICLE_WORDS = [f"word{i}" for i in range(400)]


def text_page(title: str, words: list[str], head: str = "", links: tuple[str, ...] = (), headers=None) -> Response:
    """A page whose visible text is exactly `words` plus link anchors (title lives in <head>)."""
    anchors = "".join(f'<a href="{h}">{h}</a> ' for h in links)
    return Response(body=f"<html><head><title>{title}</title>{head}</head><body><p>{' '.join(words)}</p>{anchors}</body></html>",
                    headers=dict(headers or {}))


def canonical(href: str) -> str:
    return f'<link rel="canonical" href="{href}">'


def _status_codes() -> Site:
    def flaky(site: Site, request: RequestSeen) -> Response:
        site.state["flaky"] = site.state.get("flaky", 0) + 1
        return Response(500, "oops") if site.state["flaky"] == 1 else page("Recovered")

    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": sitemap("/", "/sitemap-only-404"),
        "/": page("Home", "/ok", "/gone", "/broken-500", "/flaky-500", "/hang", "/drop", "/moved"),
        "/ok": page("OK"),
        "/gone": Response(404, "<html><title>Not found</title></html>"),
        "/sitemap-only-404": Response(410, "<html><title>Gone</title></html>"),
        "/broken-500": Response(500, "<html><title>Server error</title></html>"),
        "/flaky-500": flaky,
        "/hang": Response(body="<html>late</html>", delay_s=2.5),
        "/drop": Response(drop_connection=True),
        "/moved": Response(301, "", {"Location": "/deleted"}),
        "/deleted": Response(404, "<html><title>Deleted</title></html>"),
    })


def _start_404() -> Site:
    return Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"),
                 "/start-gone": Response(404, "<html><title>Gone</title></html>")})


def _redirects() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Home", "/a", "/loop1", "/self", "/c"),
        "/a": Response(301, "", {"Location": "/b"}),
        "/b": Response(301, "", {"Location": "/c"}),
        "/c": page("C"),
        "/loop1": Response(302, "", {"Location": "/loop2"}),
        "/loop2": Response(302, "", {"Location": "/loop1"}),
        "/self": Response(301, "", {"Location": "/self"}),
    })


def _canonicals() -> Site:
    near = ARTICLE_WORDS.copy()
    near[200] = "changed"
    different = [f"other{i}" for i in range(400)]
    links = ("/self", "/conflict", "/canon-broken", "/canon-noindex", "/article", "/print-version",
             "/near-copy", "/canon-different", "/canon-redirect", "/canon-offsite")
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": text_page("Home", ["home"] * 3, links=links),
        "/self": text_page("Self", ["self"] * 20, head=canonical("/self")),
        "/conflict": text_page("Conflict", ["conflict"] * 20, head=canonical("/conflict"),
                               headers={"Link": '</somewhere-else>; rel="canonical"'}),
        "/canon-broken": text_page("Broken canonical", ["broken"] * 20, head=canonical("/does-not-exist")),
        "/canon-noindex": text_page("Noindex canonical", ["noidx"] * 20, head=canonical("/noindexed")),
        "/noindexed": text_page("Noindexed", ["hidden"] * 20, head='<meta name="robots" content="noindex">'),
        "/article": text_page("Article", ARTICLE_WORDS),
        "/print-version": text_page("Article (print)", ARTICLE_WORDS, head=canonical("/article")),
        "/near-copy": text_page("Article copy", near, head=canonical("/article")),
        "/canon-different": text_page("Different", different, head=canonical("/article")),
        "/canon-redirect": text_page("Via redirect", ARTICLE_WORDS, head=canonical("/old-article")),
        "/old-article": Response(301, "", {"Location": "/article"}),
        "/canon-offsite": text_page("Syndicated", ["syndicated"] * 20, head=canonical("https://publisher.example/story")),
    })


def _sitemap_health() -> Site:
    ok = [f"/p{i}" for i in range(1, 8)]
    urls = ["/", *ok, "/dead1", "/dead2", "/hidden"]
    body = "".join(f"<url><loc>{{base}}{u}</loc><lastmod>2026-01-01</lastmod></url>" for u in urls)
    routes = {
        "/robots.txt": robots("User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": Response(body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                                 content_type="application/xml"),
        "/": page("Home", *ok),
        "/dead1": Response(404, "gone"), "/dead2": Response(404, "gone"),
        "/hidden": page("Hidden", head='<meta name="robots" content="noindex">'),
    }
    routes.update({u: page(u) for u in ok})
    return Site(routes)


def _canonical_latest_posts() -> Site:
    """Seen on a real client (Midas, 2026-09-22): the same article at /x and /x/, canonical -> /x/, cached on different
    days so only a "latest posts" list differs (about 10% of the words). That is the same content, not S2. Beside
    it, a page canonicalized to a genuinely different article on the same template."""
    article = " ".join(f"article{i}" for i in range(360))

    def post(latest: str, canonical_to: str | None, body: str = article) -> Response:
        head = canonical(canonical_to) if canonical_to else ""
        return Response(body=f"<html><head><title>Fund guide</title>{head}</head><body><nav>Home Blog Help</nav>"
                             f"<main><h1>Fund guide</h1><p>{body}</p><section><h3>Latest posts</h3>"
                             f"<p>{latest}</p></section></main><footer>Acme 2026</footer></body></html>")
    fresh = " ".join(f"freshpost{i}" for i in range(40))
    older = " ".join(f"olderpost{i}" for i in range(40))
    other = " ".join(f"otherarticle{i}" for i in range(360))
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Home", "/blog/fund-guide", "/blog/fund-guide/", "/blog/moved-guide"),
        "/blog/fund-guide": post(fresh, "/blog/fund-guide/"),
        "/blog/fund-guide/": post(older, "/blog/fund-guide/"),
        "/blog/moved-guide": post(fresh, "/blog/other-guide/"),
        "/blog/other-guide/": post(older, "/blog/other-guide/", body=other),
    })


def _sitemap_future() -> Site:
    entries = [("/", "2026-08-01"), ("/a", "2026-08-15"), ("/b", "2099-01-01")]
    body = "".join(f"<url><loc>{{base}}{u}</loc><lastmod>{d}</lastmod></url>" for u, d in entries)
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/sitemap.xml": Response(body=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                                 content_type="application/xml"),
        "/": page("Home", "/a", "/b"), "/a": page("A"), "/b": page("B"),
    })


def _sitemap_bad_lastmod() -> Site:
    """DECISIONS 372 (F01): <lastmod> values that are not dates (a typo, a day/month form, a placeholder) beside real
    ones, and a future date: the check counts the bad ones and still reports the future one."""
    entries = [("/", "2026-08-01"), ("/a", "16/11/2026"), ("/b", "2099-01-01"), ("/c", "{lastmod}"), ("/d", "2026-13-45")]
    body = "".join(f"<url><loc>{{base}}{u}</loc><lastmod>{d}</lastmod></url>" for u, d in entries)
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/sitemap.xml": Response(body=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                                 content_type="application/xml"),
        "/": page("Home", "/a", "/b", "/c", "/d"), "/a": page("A"), "/b": page("B"), "/c": page("C"), "/d": page("D"),
    })


def _sitemap_only_bad_lastmod() -> Site:
    """Every <lastmod> is the same malformed value: no "identical" finding about a value that is not a date."""
    entries = [("/", "not-a-date"), ("/a", "not-a-date"), ("/b", "not-a-date")]
    body = "".join(f"<url><loc>{{base}}{u}</loc><lastmod>{d}</lastmod></url>" for u, d in entries)
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/sitemap.xml": Response(body=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                                 content_type="application/xml"),
        "/": page("Home", "/a", "/b"), "/a": page("A"), "/b": page("B"),
    })


def _sitemap_stamped_docs() -> Site:
    """A sitemap index of two documents: one gives all six URLs the same timestamp to the second (the file's
    generation time, as on a real client), the other gives each URL its own date."""
    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    products = [f"/product/{i}" for i in range(6)]
    posts = [f"/post/{i}" for i in range(6)]
    stamped = "".join(f"<url><loc>{{base}}{u}</loc><lastmod>2026-09-17T10:43:24+03:00</lastmod></url>" for u in products)
    varied = "".join(f"<url><loc>{{base}}{u}</loc><lastmod>2026-0{i + 1}-1{i}</lastmod></url>" for i, u in enumerate(posts))
    routes = {
        "/robots.txt": robots("User-agent: *\nAllow: /\nSitemap: {base}/sitemap_index.xml\n"),
        "/sitemap_index.xml": Response(body=f'<sitemapindex {ns}><sitemap><loc>{{base}}/sitemap-products.xml</loc>'
                                            f'</sitemap><sitemap><loc>{{base}}/sitemap-posts.xml</loc></sitemap></sitemapindex>',
                                       content_type="application/xml"),
        "/sitemap-products.xml": Response(body=f"<urlset {ns}>{stamped}</urlset>", content_type="application/xml"),
        "/sitemap-posts.xml": Response(body=f"<urlset {ns}>{varied}</urlset>", content_type="application/xml"),
        "/": page("Home", *products, *posts),
    }
    routes.update({u: page(u) for u in products + posts})
    return Site(routes)


def _no_sitemap(n: int) -> Site:
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": page("Home", *[f"/item/{i}" for i in range(n)])}
    routes.update({f"/item/{i}": page(f"Item {i}") for i in range(n)})
    return Site(routes)


def _orphans_depth() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": sitemap("/", "/orphan", "/campaign"),
        "/": page("Home", "/l1"), "/l1": page("L1", "/l2"), "/l2": page("L2", "/l3"),
        "/l3": page("L3", "/l4"), "/l4": page("L4", "/l5"), "/l5": page("L5"),
        "/orphan": page("Orphan"), "/campaign": page("Campaign"),
    })


def _duplicates() -> Site:
    same = [f"dup{i}" for i in range(120)]
    near_a = [f"near{i}" for i in range(400)]
    near_b = near_a.copy()
    near_b[100] = "tweak"
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": text_page("Home", ["home"], links=("/dup-a", "/dup-b", "/title-1", "/title-2", "/near-a", "/near-b",
                                                "/dup-noindex", "/dup-canonical")),
        "/dup-a": text_page("Dup A", same), "/dup-b": text_page("Dup B", same),
        "/title-1": text_page("Shared title", ["first"] * 30), "/title-2": text_page("Shared title", ["second"] * 30),
        "/near-a": text_page("Near A", near_a), "/near-b": text_page("Near B", near_b),
        "/dup-noindex": text_page("Dup noindex", same, head='<meta name="robots" content="noindex">'),
        "/dup-canonical": text_page("Dup canonical", same, head=canonical("/dup-a")),
    })


def _gsc_site() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Home", "/pricing", "/docs", "/about", "/new", "/snippetless"),
        "/pricing": page("Pricing"), "/docs": page("Docs"), "/about": page("About"), "/new": page("New"),
        "/snippetless": page("Snippetless", head='<meta name="robots" content="nosnippet">'),
    })


def gsc_api(base_of_site: callable, token: str = "test-token") -> Site:
    """Fake URL Inspection API. `base_of_site()` returns the audited site's base URL at request time."""

    def inspect(site: Site, request: RequestSeen) -> Response:
        if request.headers.get("authorization") != f"Bearer {token}":
            return Response(401, json.dumps({"error": "unauthorized"}), content_type="application/json")
        body = json.loads(request.body or b"{}")
        path = body.get("inspectionUrl", "")[len(base_of_site()):]
        base = base_of_site()
        results = {
            "/pricing": {"verdict": "NEUTRAL", "coverageState": "Crawled - currently not indexed",
                         "indexingState": "INDEXING_ALLOWED", "robotsTxtState": "ALLOWED"},
            "/docs": {"verdict": "NEUTRAL", "coverageState": "Excluded by ‘noindex’ tag",
                      "indexingState": "BLOCKED_BY_META_TAG", "robotsTxtState": "ALLOWED"},
            "/": {"verdict": "PASS", "coverageState": "Submitted and indexed", "indexingState": "INDEXING_ALLOWED",
                  "googleCanonical": base + "/", "userCanonical": base + "/"},
            "/about": {"verdict": "PASS", "coverageState": "Submitted and indexed", "indexingState": "INDEXING_ALLOWED",
                       "googleCanonical": base + "/", "userCanonical": base + "/about"},
            "/new": {"verdict": "NEUTRAL", "coverageState": "URL is unknown to Google"},
            "/snippetless": {"verdict": "PASS", "coverageState": "Submitted and indexed", "indexingState": "INDEXING_ALLOWED"},
        }
        result = results.get(path, {"verdict": "VERDICT_UNSPECIFIED"})
        return Response(200, json.dumps({"inspectionResult": {"indexStatusResult": result}}), content_type="application/json")

    return Site({"/v1/urlInspection/index:inspect": inspect})


def bing_api(base_of_site: callable, key: str = "bing-key") -> Site:
    def url_info(site: Site, request: RequestSeen) -> Response:
        if request.query.get("apikey") != key:
            return Response(401, "{}", content_type="application/json")
        path = request.query.get("url", "")[len(base_of_site()):]
        status = 404 if path == "/docs" else 200
        return Response(200, json.dumps({"d": {"HttpStatus": status, "LastCrawledDate": "/Date(1757671200000)/",
                                               "DiscoveryDate": "/Date(1750000000000)/", "IsPage": True,
                                               "Url": request.query.get("url")}}), content_type="application/json")

    return Site({"/webmaster/api.svc/json/GetUrlInfo": url_info})


@contextlib.contextmanager
def tls_sites(kind: str, redirect: bool = True):
    """HTTPS site plus a plain-HTTP twin. kind: valid | near_expiry | expired | mismatch | variant_mismatch.

    Both servers answer for localhost and www.localhost (which resolves to 127.0.0.1).

    Yields (https_server, http_server, ca_bundle_path).
    """
    from .tls import TestCA

    with tempfile.TemporaryDirectory() as directory:
        ca = TestCA(directory)
        both = ("localhost", "www.localhost")
        options = {"valid": {"hostnames": both}, "near_expiry": {"hostnames": both, "days_valid": 7},
                   "expired": {"hostnames": both, "expired": True}, "mismatch": {"hostnames": ("wrong.test",)},
                   "variant_mismatch": {"hostnames": ("localhost",)}}[kind]
        cert = ca.issue(kind, **options)
        https_site = Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": page("Secure home", "/about"),
                           "/about": page("About")})
        with FakeServer(https_site, tls=(cert.cert, cert.key), host="localhost") as https:
            def to_https(site: Site, request: RequestSeen) -> Response:
                if request.route_path == "/robots.txt":
                    return robots("User-agent: *\nAllow: /\n")
                host = (request.headers.get("host") or "localhost").split(":")[0]
                return Response(301, "", {"Location": f"https://{host}:{https.port}{request.path}"})

            plain = Site({}, fallback=to_https) if redirect else Site({
                "/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": page("Plain home")})
            with FakeServer(plain, host="localhost") as http:
                yield https, http, ca.files.cert


IDX_SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("idx_status_codes", "404s (linked, sitemap-only, behind a redirect), a persistent 500, a transient 500, "
             "a page that always times out, and one that always drops the connection.", _status_codes, FAST_IDX),
    Scenario("idx_start_404", "The start URL itself is a 404 that nothing links to.", _start_404, FAST_IDX,
             start_path="/start-gone"),
    Scenario("idx_redirects", "A 2-hop chain, a two-URL loop, and a self-redirect.", _redirects, FAST_IDX),
    Scenario("idx_canonicals", "Self, conflicting, broken, noindexed, identical, near-identical, different, "
             "redirecting, and off-site canonicals.", _canonicals, FAST_IDX),
    Scenario("idx_sitemap_health", "Sitemap with 3 of 11 URLs broken or noindex and identical lastmod values.",
             _sitemap_health, FAST_IDX),
    Scenario("idx_sitemap_future", "One sitemap lastmod in 2099.", _sitemap_future, FAST_IDX),
    Scenario("idx_sitemap_bad_lastmod", "Malformed <lastmod> values beside real and future ones (F01).", _sitemap_bad_lastmod,
             FAST_IDX),
    Scenario("idx_sitemap_only_bad_lastmod", "Every <lastmod> the same malformed value.", _sitemap_only_bad_lastmod, FAST_IDX),
    Scenario("idx_canonical_latest_posts", "The same article at /x and /x/ differing only in a 'latest posts' list, "
             "and a page canonicalized to a different article on the same template.", _canonical_latest_posts, FAST_IDX),
    Scenario("idx_sitemap_stamped_docs", "A sitemap document whose six URLs share one lastmod to the second, beside "
             "one with real per-URL dates.", _sitemap_stamped_docs, FAST_IDX),
    Scenario("idx_no_sitemap_large", "61 pages, no sitemap.", lambda: _no_sitemap(60), {**FAST_IDX, "max_pages": 80}),
    Scenario("idx_no_sitemap_small", "11 pages, no sitemap.", lambda: _no_sitemap(10), FAST_IDX),
    Scenario("idx_orphans_depth", "Two sitemap-only pages and a 5-click-deep page.", _orphans_depth, FAST_IDX),
    Scenario("idx_duplicates", "Identical text, shared titles, near-identical text, plus excluded noindex and "
             "canonicalized copies.", _duplicates, FAST_IDX),
    Scenario("idx_gsc_bing", "Key pages checked against fake Search Console and Bing Webmaster APIs.", _gsc_site,
             {**FAST_IDX, "key_pages": ("/", "/pricing", "/docs", "/about", "/new", "/snippetless")}),
]}
