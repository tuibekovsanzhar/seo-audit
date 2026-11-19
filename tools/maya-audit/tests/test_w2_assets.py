"""W2 item group G: heavy and mislabelled media (H29), loading behaviour from markup (H30), social preview and
page-level markup gaps (H32), duplicate analytics tags (H33) and the platform the site runs on (H34)."""

from __future__ import annotations

from fakeserver import FakeServer
from fakeserver.scenarios import robots
from fakeserver.server import Response, Site
from maya_audit.audit import run_audit
from maya_audit.checks.structure import media_weight_findings, media_size
from maya_audit.config import CrawlConfig
from maya_audit.findings import Severity

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0}


def image(url, size, kind="image/jpeg", status=200):
    return {"url": url, "pages": ["https://s.test/"], "source": "fetched", "status": status, "content_type": kind,
            "content_length": str(size), "body_bytes": 4096, "body_truncated": True}


# -- H29 ---------------------------------------------------------------------------------------------------------
def test_an_image_over_one_mb_is_s3_and_names_file_and_size():
    [heavy] = media_weight_findings([image("https://s.test/a.jpg", 2_000_000), image("https://s.test/b.jpg", 600_000),
                                     image("https://s.test/c.jpg", 90_000)], [], set(), "https://s.test/")
    # S3 because the 2 MB file is shown on the homepage (review G08); elsewhere it would be S4.
    assert heavy.title == "2 sampled image file(s) are over 500 KB" and heavy.severity == Severity.S3
    assert [r["bytes"] for r in heavy.evidence["images"]] == [2_000_000, 600_000]


def test_images_between_500_kb_and_one_mb_are_s4():
    [heavy] = media_weight_findings([image("https://s.test/a.jpg", 700_000)], [], set())
    assert heavy.severity == Severity.S4


def test_a_file_whose_size_is_unknown_is_not_counted_as_small_or_heavy():
    row = {**image("https://s.test/a.jpg", 0), "content_length": None}
    assert media_size(row) is None
    assert media_weight_findings([row], [], set()) == []


def test_a_png_served_under_a_jpg_name_is_an_info_note():
    [mime] = media_weight_findings([image("https://s.test/banner.jpg", 50_000, "image/png")], [], set())
    assert mime.severity == Severity.INFO and mime.evidence["images"][0]["content_type"] == "image/png"
    assert media_weight_findings([image("https://s.test/photo.webp", 50_000, "image/webp")], [], set()) == []


def test_a_heavy_video_is_requested_once_with_a_small_cap_and_reported():
    page = ('<!doctype html><html lang="tr"><head><title>Ana Sayfa | Deneme</title></head><body><main><h1>Deneme</h1>'
            '<p>Deneme sayfasının metni burada duruyor ve bir video oynatıyor.</p>'
            '<video autoplay muted><source src="/v/promo.mp4" type="video/mp4"></video>'
            '<video src="/v/promo.mp4"></video></main></body></html>')
    site = Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": Response(body=page),
                 "/v/promo.mp4": Response(body=b"\0" * 6_000_000, content_type="video/mp4")})
    with FakeServer(site) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**FAST, max_pages=5))
        asked = [r.path for r in server.requests if r.path.startswith("/v/")]
    assert asked == ["/v/promo.mp4"]
    [video] = [f for c in outcome.checks for f in c.findings if "video file(s)" in f.title]
    assert video.severity == Severity.S4 and video.evidence["videos"][0]["bytes"] == 6_000_000


# -- H30 ---------------------------------------------------------------------------------------------------------
def markup(pages_html):
    from test_false_alarms import site
    return site(pages_html)


def test_images_without_width_and_height_are_counted_per_page():
    from maya_audit.checks.structure import image_loading_findings
    from test_false_alarms import html
    _, pages = markup({"/": html('<img src="/a.jpg" alt="A"><img src="/b.jpg" alt="B" width="10" height="10">'
                                 '<img src="/c.jpg" alt="C" style="aspect-ratio: 4/3">')})
    [unsized] = image_loading_findings(pages, set())
    assert unsized.title == "1 image(s) on 1 page(s) have no width and height (layout shift risk)"


def test_a_preload_typed_image_jpg_is_noted():
    from maya_audit.checks.structure import image_loading_findings
    from test_false_alarms import html
    _, pages = markup({"/": html("<p>x</p>", head='<link rel="preload" as="image" href="/h.jpg" type="image/jpg">')})
    [preload] = image_loading_findings(pages, set())
    assert "image/jpg" in preload.title and preload.severity == Severity.INFO


def test_only_classic_head_scripts_without_defer_or_async_block():
    from maya_audit.checks.page_markup import page_markup_findings
    from test_false_alarms import html
    head = ('<script src="/a.js"></script><script src="/b.js" defer></script><script src="/c.js" async></script>'
            '<script type="module" src="/d.js"></script><script>inline()</script>')
    _, pages = markup({"/": html('<script src="/body.js"></script>', head=head)})
    from maya_audit.checks.page_markup import blocking_scripts
    assert blocking_scripts(pages[0].analysis) == ["/a.js"]
    # One blocking script is an observation (review G11); three of the site's own make the finding.
    observations: list = []
    assert [f for f in page_markup_findings(pages, set(), observations) if "script" in f.title] == []
    assert observations[0]["scripts"] == 1 and observations[0]["top_hosts"][0]["scripts"] == 1
    _, pages = markup({"/": html("<p>x</p>", head=head + '<script src="/e.js"></script><script src="/f.js"></script>')})
    [blocking] = [f for f in page_markup_findings(pages, set()) if "script" in f.title]
    assert blocking.title == "1 page(s) load 3 script(s) in <head> without defer or async"
    assert blocking.evidence["pages"][0]["examples"] == ["/a.js", "/e.js", "/f.js"]


# -- H32 ---------------------------------------------------------------------------------------------------------
def page_markup(pages_html):
    from maya_audit.checks.page_markup import page_markup_findings
    _, pages = markup(pages_html)
    return page_markup_findings(pages, set())


def test_a_page_without_viewport_is_s3_and_a_zoom_lock_is_info():
    from test_false_alarms import html
    [missing] = [f for f in page_markup({"/": html("<p>x</p>")}) if "viewport" in f.title]
    assert missing.severity == Severity.S3
    locked = html("<p>x</p>", head='<meta name="viewport" content="width=device-width, maximum-scale=1.0">')
    [zoom] = [f for f in page_markup({"/": locked}) if "zooming" in f.title]
    assert zoom.severity == Severity.INFO
    fine = html("<p>x</p>", head='<meta name="viewport" content="width=device-width, initial-scale=1">')
    assert not [f for f in page_markup({"/": fine}) if "viewport" in f.title or "zooming" in f.title]


def test_http_subresources_on_an_https_page_are_mixed_content_but_links_are_not():
    from test_false_alarms import html
    body = '<img src="http://cdn.example.test/a.jpg" alt="A"><a href="http://other.example.test/">x</a>'
    [mixed] = [f for f in page_markup({"/": html(body)}) if "mixed content" in f.title]
    assert mixed.severity == Severity.S3
    assert [r["url"] for r in mixed.evidence["pages"][0]["resources"]] == ["http://cdn.example.test/a.jpg"]
    assert not [f for f in page_markup({"/": html('<a href="http://other.example.test/">x</a>')}) if "mixed" in f.title]


def test_open_graph_without_twitter_card_is_noted():
    from maya_audit.checks.structure import str10_previews
    from maya_audit.config import CrawlConfig as Config
    from maya_audit.structure_data import StructureData
    from test_false_alarms import html
    og = '<meta property="og:title" content="Sayfa">'
    result, pages = markup({"/": html("<p>x</p>", head=og),
                            "/b": html("<p>x</p>", head=og + '<meta name="twitter:card" content="summary">')})
    check = str10_previews(result, Config(), pages, set(), StructureData())
    # An observation since review G13, not a finding.
    assert [f for f in check.findings if "Twitter" in f.title] == []
    [card] = [o for o in check.observations if "twitter" in o["metric"]]
    assert card["pages"] == 1 and card["examples"] == [pages[0].url]


# -- H33 ---------------------------------------------------------------------------------------------------------
GTM_FRAME = '<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-AB12CD"></iframe></noscript>'
GTM_SCRIPT = "<script>(function(w,d,s,l,i){})(window,document,'script','dataLayer','GTM-AB12CD');</script>"
GTAG = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-XYZ123"></script>'


def analytics(head, body):
    from test_false_alarms import html
    return [f for f in page_markup({"/": html(body, head=head)}) if "analytics" in f.title]


def test_one_container_with_its_noscript_pair_is_not_double_counting():
    assert analytics(GTM_SCRIPT, GTM_FRAME) == []
    assert analytics(GTAG, "") == []


def test_a_container_printed_twice_or_beside_a_direct_gtag_is_noted_with_its_ids():
    [twice] = analytics(GTM_SCRIPT, GTM_FRAME * 2)
    assert twice.severity == Severity.INFO and twice.evidence["pages"][0]["containers"] == ["GTM-AB12CD"]
    assert "Tag Assistant" in twice.how_to_fix
    # A container beside a direct gtag.js for another id is an observation since review G10; one id loaded twice is not.
    assert analytics(GTM_SCRIPT + GTAG, GTM_FRAME) == []
    [doubled] = analytics(GTAG + GTAG, "")
    assert doubled.evidence["pages"][0]["measurement_ids"] == ["G-XYZ123"]


# -- H34 ---------------------------------------------------------------------------------------------------------
def platform_of(pages_html, headers=None):
    from maya_audit.site_platform import recognise
    result, pages = markup(pages_html)
    for page in pages:
        page.headers = headers or {}
    return recognise(result)


def test_a_platform_is_named_from_its_script_host_and_the_cdn_from_headers():
    from test_false_alarms import html
    shop = html("<p>x</p>", head='<script src="https://cdn.shopify.com/s/files/theme.js"></script>')
    found = platform_of({"/": shop}, {"server": "cloudflare"})
    assert found["name"] == "Shopify" and found["cdn"] == "Cloudflare" and len(found["signals"]) == 2


def test_woocommerce_is_told_apart_from_wordpress_and_a_generator_counts():
    from test_false_alarms import html
    woo = html("<p>x</p>", head='<script src="/wp-content/plugins/woocommerce/assets/js/cart.js"></script>')
    assert platform_of({"/": woo})["name"] == "WooCommerce"
    wp = html("<p>x</p>", head='<meta name="generator" content="WordPress 6.6">')
    assert platform_of({"/": wp}) == {"name": "WordPress", "cdn": None, "signals": [platform_of({"/": wp})["signals"][0]],
                                      # DECISIONS 365: one page stating it
                                      "confidence": "medium", "pages_seen": 1, "pages_looked": 1}


def test_an_unknown_site_has_no_platform_and_headers_may_be_missing():
    from test_false_alarms import html
    assert platform_of({"/": html("<p>x</p>")}) is None
    assert platform_of({"/": html("<p>x</p>")}, {"Server": "nginx"}) is None
