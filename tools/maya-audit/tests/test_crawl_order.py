"""Which pages a capped crawl fetches: the real homepage first, then a sample that stands for the site.

Offline: every site here is an httpx mock transport (needed for http->https and apex->www, which a
loopback server cannot play) or the fake server.
"""

from urllib.parse import urlsplit

import httpx
import pytest

from fakeserver import FakeServer, Response, Site
from maya_audit.config import CrawlConfig
from maya_audit.crawler import Crawler
from maya_audit.html_links import extract_link_edges
from maya_audit.scratchpad import CRAWLED, MEMORY, FrontierUrl, Scratchpad
from maya_audit.urls import section_key

QUIET = dict(request_delay_s=0, robots_samples=1, render_enabled=False, prf_enabled=False, probes_enabled=False,
             refetch_delay_s=0)
WORDS = ["kaygi", "uyku", "stres", "dikkat", "ofke", "yas", "travma", "panik", "fobi", "bagimlilik", "depresyon",
         "ergenlik", "evlilik", "yalnizlik", "tukenmislik", "hafiza", "kabus", "utangaclik", "kiskanclik", "ozguven"]


def html(body="", nav=""):
    return (f"<html lang='tr'><head><title>Sayfa</title></head><body><header><nav>{nav}</nav></header>"
            f"<main><h1>Sayfa</h1>{body}</main></body></html>")


def links(paths):
    return "".join(f'<a href="{path}">{path}</a>' for path in paths)


def sitemap(origin, paths):
    return ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{origin}{path}</loc></url>" for path in paths) + "</urlset>")


def site(pages, redirects=None, sitemaps=None):
    """A mock web: {origin: {path: html}}, {url: (status, location)}, {origin: [sitemap paths]}."""
    redirects, sitemaps = redirects or {}, sitemaps or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        origin, path = f"{request.url.scheme}://{request.url.host}", request.url.path
        if url in redirects:
            status, location = redirects[url]
            return httpx.Response(status, headers={"location": location})
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        if path == "/sitemap.xml" and origin in sitemaps:
            return httpx.Response(200, text=sitemap(origin, sitemaps[origin]), headers={"content-type": "application/xml"})
        if path in pages.get(origin, {}):
            return httpx.Response(200, text=pages[origin][path], headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="not found", headers={"content-type": "text/plain"})

    return httpx.MockTransport(handler)


def crawl(start, transport, hosts, **options):
    config = CrawlConfig(**{**QUIET, "allowed_live_hosts": frozenset(hosts), **options})
    return Crawler(config, transport).run(start)


# The homepage ------------------------------------------------------------------------------------
PRODUCTS = [f"/urun-{word}" for word in WORDS]


@pytest.mark.parametrize("start, redirect, home", [
    ("http://marka.example/", (301, "https://marka.example/"), "https://marka.example/"),          # http -> https
    ("https://marka.example/", (301, "https://www.marka.example/"), "https://www.marka.example/"),  # apex -> www
    ("https://marka.example/", (302, "https://marka.example/tr/"), "https://marka.example/tr/"),    # root -> /tr/
])
def test_the_start_urls_redirect_target_is_fetched_first_even_when_the_sitemap_already_listed_it(start, redirect, home):
    origin = home[:home.index("/", 8)]
    home_path = urlsplit(home).path
    # The sitemap lists twenty product pages before the homepage, as the two real sites that exposed this did.
    listed = PRODUCTS + [home_path]
    pages = {origin: {home_path: html(links(PRODUCTS[:3])), **{path: html(links(PRODUCTS)) for path in PRODUCTS}}}
    result = crawl(start, site(pages, {start: redirect}, {origin: listed}), {urlsplit(start).hostname, urlsplit(home).hostname},
                   max_pages=4)

    assert [(page.url, page.status) for page in result.pages[:2]] == [(start, redirect[0]), (home, 200)]
    assert result.pages[1].discovered_via == "redirect"
    assert home in result.sitemap_urls  # it really was queued from the sitemap before the redirect was seen
    assert len(result.pages) == 5 and result.stop_reason.value == "page_cap"  # the redirect does not use up the cap
    assert home not in result.not_fetched_urls


def test_a_redirect_target_jumps_the_queue_whatever_put_it_there_but_a_fetched_url_is_never_requeued():
    pad = Scratchpad(MEMORY)
    pad.add_urls([FrontierUrl("http://s/", 0, "start", None)])
    pad.add_urls([FrontierUrl(f"http://s/{name}", None, "sitemap", None) for name in ("a", "home", "b")])
    pad.add_urls([FrontierUrl("http://s/l", 1, "link", "http://s/")])
    assert pad.add_urls([FrontierUrl("http://s/home", 0, "redirect", "http://s/")]) == 1
    assert pad.get_next_url() == FrontierUrl("http://s/home", 0, "redirect", "http://s/")
    pad.mark_status("http://s/home", CRAWLED)
    assert pad.add_urls([FrontierUrl("http://s/home", 0, "redirect", "http://s/x")]) == 0
    assert pad.get_next_url().url == "http://s/"
    # A weaker route never demotes a URL: the navigation link stays a navigation link.
    pad.add_urls([FrontierUrl("http://s/n", 1, "link", "http://s/", True)])
    pad.add_urls([FrontierUrl("http://s/n", 2, "link", "http://s/l")])
    pad.mark_status("http://s/", CRAWLED)
    assert pad.get_next_url() == FrontierUrl("http://s/n", 1, "link", "http://s/", True)


# The sample --------------------------------------------------------------------------------------
def hospital():
    """Shaped like the site that exposed this: 60 blog posts at /tr/<slug>/ swamp everything else."""
    origin = "https://hastane.example"
    posts = [f"/tr/{a}-ve-{b}-rehberi/" for a in WORDS[:10] for b in WORDS[10:16]]
    services = [f"/tr/tibbi-bolumlerimiz/{word}-tedavisi/" for word in WORDS[:8]]
    methods = [f"/tr/tani-ve-tedavi-yontemleri/{word}-testi/" for word in WORDS[:5]]
    team = [f"/tr/team/uzman-{word}/" for word in WORDS[:6]]
    english = ["/en/", "/en/medical-units/addiction/", "/en/medical-units/sleep/", "/en/team/doctor-a/"]
    nav = links(["/tr/", "/tr/tibbi-bolumlerimiz/", "/tr/hakkimizda/", "/tr/iletisim/", "/en/"])
    pages = {"/tr/": html(links(posts[:30]), nav),                       # the homepage body is a wall of blog links
             "/tr/tibbi-bolumlerimiz/": html(links(services), nav),
             "/tr/hakkimizda/": html(links(team[:2]), nav), "/tr/iletisim/": html("", nav), "/en/": html(links(english[1:]), nav),
             **{path: html(links(posts), nav) for path in posts},        # and every post links to every other post
             **{path: html("", nav) for path in services + methods + team + english[1:]}}
    listed = posts + ["/tr/"] + services + methods + team + english      # the sitemap lists the blog first too
    transport = site({origin: pages}, {origin + "/": (302, origin + "/tr/")}, {origin: listed})
    return origin, transport, dict(posts=posts, services=services, methods=methods, team=team)


def test_a_capped_crawl_takes_the_homepage_then_the_navigation_then_one_page_per_section():
    origin, transport, groups = hospital()
    result = crawl(origin + "/", transport, {"hastane.example"}, max_pages=10)
    fetched = [page.url.removeprefix(origin) for page in result.pages if page.status == 200]
    assert len(fetched) == 10 and result.stop_reason.value == "page_cap"

    assert fetched[0] == "/tr/"                                                         # the homepage
    assert set(fetched[1:5]) == {"/tr/tibbi-bolumlerimiz/", "/tr/hakkimizda/", "/tr/iletisim/", "/en/"}  # its navigation
    rest = fetched[5:]
    in_group = lambda name: [path for path in rest if path in groups[name]]
    assert len(in_group("services")) >= 1 and len(in_group("methods")) == 1 and len(in_group("team")) == 1
    assert any(path.startswith("/en/medical-units/") for path in rest)
    # Sixty blog posts, linked from everywhere and first in the sitemap, do not crowd the rest out. They share
    # the /tr/* section with three navigation pages already fetched, so here they wait for the next round.
    assert len(in_group("posts")) <= 1
    # DECISIONS 316: /tr/ and /en/ are language folders, so /en/team/* and /tr/team/* are one section (/_l/team/*):
    # the first round takes one page of each of the four sections not sampled yet, then a second round begins.
    from maya_audit.locales import section_url
    keys = [section_key(section_url(origin + path, ["tr", "en"])) for path in rest]
    assert len(set(keys[:4])) == 4 and set(keys) == set(keys[:4])


def test_once_every_section_has_a_page_the_crawl_goes_round_again_and_an_uncapped_crawl_still_fetches_everything():
    origin, transport, groups = hospital()
    result = crawl(origin + "/", transport, {"hastane.example"}, max_pages=22)
    fetched = [page.url.removeprefix(origin) for page in result.pages if page.status == 200]
    counts = {name: sum(path in paths for path in fetched) for name, paths in groups.items()}
    assert all(counts[name] >= 3 for name in ("services", "methods", "team")) and 1 <= counts["posts"] <= 4, counts

    everything = crawl(origin + "/", hospital()[1], {"hastane.example"}, max_pages=500)
    assert everything.stop_reason.value == "exhausted" and not everything.not_fetched_urls
    assert sum(page.status == 200 for page in everything.pages) == 60 + 8 + 5 + 6 + 4 + 4


def test_key_pages_still_come_before_the_navigation_and_links_before_sitemap_only_urls_of_the_same_section():
    pad = Scratchpad(MEMORY)
    pad.add_urls([FrontierUrl("http://s/", 0, "start", None), FrontierUrl("http://s/key", None, "key_page", None)])
    pad.add_urls([FrontierUrl("http://s/blog/from-sitemap", None, "sitemap", None)])
    pad.add_urls([FrontierUrl("http://s/blog/linked", 1, "link", "http://s/"),
                  FrontierUrl("http://s/menu", 1, "link", "http://s/", True),
                  FrontierUrl("http://s/shop/linked", 1, "link", "http://s/")])
    order = []
    while (claimed := pad.get_next_url()) is not None:
        order.append(claimed.url.removeprefix("http://s"))
        pad.mark_status(claimed.url, CRAWLED)
    assert order == ["/", "/key", "/menu", "/blog/linked", "/shop/linked", "/blog/from-sitemap"]


def test_navigation_links_are_recognised_in_nav_header_and_role_navigation_and_nowhere_else():
    page = ('<header><a href="/logo">Logo</a></header><nav><ul><li><a href="/a">A</a></li></ul></nav>'
            '<div role="navigation"><div><a href="/b">B</a></div></div><div><a href="/after-role">x</a></div>'
            '<main><a href="/body">Body</a><a href="/a">A again</a></main><footer><a href="/footer">F</a></footer>')
    edges = {edge["target"].removeprefix("http://s"): edge for edge in extract_link_edges(page, "http://s/")}
    assert {path for path, edge in edges.items() if edge.get("nav")} == {"/logo", "/a", "/b"}
    assert "nav" not in edges["/body"] and "nav" not in edges["/footer"] and "nav" not in edges["/after-role"]
    assert edges["/a"]["anchor"] == "A"


@pytest.mark.parametrize("url, key", [
    ("https://s/", "/"), ("https://s/pricing", "/pricing"), ("https://s/tr/", "/tr"),
    ("https://s/tr/bir-blog-yazisi/", "/tr/*"), ("https://s/tr/baska-yazi/?page=2", "/tr/*"),
    ("https://s/tr/tibbi-bolumlerimiz/alkol/", "/tr/tibbi-bolumlerimiz/*"),
    ("https://s/urun-adi-289", "/{id}"), ("https://s/p/12345/reviews", "/p/{id}/*"),
])
def test_section_key(url, key):
    assert section_key(url) == key


def test_the_fake_server_agrees_a_root_redirect_to_a_language_folder_leads_to_the_homepage_first():
    posts = [f"/tr/{word}-yazisi/" for word in WORDS]
    pages = {"/": Response(302, "", headers={"Location": "/tr/"}),
             "/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
             "/tr/": Response(body=html(links(posts[:2]))), **{path: Response(body=html()) for path in posts}}
    with FakeServer(Site(pages)) as server:
        pages["/sitemap.xml"] = Response(body=sitemap(server.base_url, posts + ["/tr/"]), content_type="application/xml")
        result = Crawler(CrawlConfig(max_pages=3, **QUIET)).run(server.base_url + "/")
    assert [page.url.removeprefix(server.base_url) for page in result.pages[:2]] == ["/", "/tr/"]
