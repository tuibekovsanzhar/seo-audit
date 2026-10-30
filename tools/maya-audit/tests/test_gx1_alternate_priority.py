"""Crawl order (live gap 3): the hreflang alternates and the canonical target the homepage names in its <head> are read
before ordinary and navigation links, so a capped crawl reads /en even when only <head> points at it."""

from __future__ import annotations

from fakeserver import FakeServer
from fakeserver.scenarios import page, robots, sitemap
from fakeserver.server import Response, Site
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.scratchpad import PRIORITY, FrontierUrl, Scratchpad

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0, "probes_enabled": False}
TEXT = ("Kettles boil water quickly and switch themselves off. This page describes one kettle, its capacity, its "
        "warranty and how to descale it so it lasts for years. ") * 3
PRODUCTS = [f"/urun-{n}" for n in range(1, 16)]
HEAD = ('<link rel="alternate" hreflang="tr" href="{base}/"><link rel="alternate" hreflang="en" href="{base}/en">'
        '<link rel="alternate" hreflang="x-default" href="{base}/">')


def doc(title: str, body: str, head: str = "") -> Response:
    return Response(body=f"<!doctype html><html lang='tr'><head><title>{title}</title>{head}</head>"
                         f"<body><main><h1>{title}</h1>{body}<p>{TEXT}</p></main></body></html>")


def site(listed: bool) -> Site:
    links = "".join(f'<a href="{p}">Ürün {p}</a> ' for p in PRODUCTS)
    paths = ("/", *PRODUCTS, "/en") if listed else ("/", *PRODUCTS)
    return Site({"/robots.txt": robots("User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n"),
                 "/sitemap.xml": sitemap(*paths),
                 "/": doc("Ana sayfa", f"<nav>{links}</nav>", head=HEAD),
                 "/en": doc("Home", "<p>English version.</p>", head=HEAD),
                 **{p: doc(f"Ürün {p}", "<p>Ürün.</p>") for p in PRODUCTS}})


def crawled(listed: bool) -> dict[str, str]:
    with FakeServer(site(listed)) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**FAST, "max_pages": 4}))
        base = server.base_url
    return {p.url.replace(base, "") or "/": p.discovered_via for p in outcome.result.pages}


def test_an_hreflang_alternate_named_only_in_head_is_read_within_a_small_cap():
    pages = crawled(listed=False)
    assert "/en" in pages and pages["/en"] == "alternate"


def test_a_sitemap_url_named_by_hreflang_moves_up_but_stays_sitemap_found():
    pages = crawled(listed=True)
    assert pages.get("/en") == "sitemap"


def test_the_frontier_moves_an_alternate_up_and_keeps_its_route():
    pad = Scratchpad()
    try:
        pad.add_urls([FrontierUrl("https://x.example/", 0, "start", None)])
        pad.add_urls([FrontierUrl("https://x.example/a", 1, "link", "https://x.example/", True)])
        pad.add_urls([FrontierUrl("https://x.example/en", None, "sitemap", None)])
        pad.add_urls([FrontierUrl("https://x.example/en", 1, "alternate", "https://x.example/")])
        assert PRIORITY["alternate"] == PRIORITY["key_page"]
        order = []
        while (item := pad.get_next_url()) is not None:
            order.append((item.url.rsplit("/", 1)[-1] or "/", item.via))
            pad.mark_status(item.url, "crawled")
        assert order == [("/", "start"), ("en", "sitemap"), ("a", "link")]
    finally:
        pad.close()
