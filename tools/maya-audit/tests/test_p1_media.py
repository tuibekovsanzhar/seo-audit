"""P1 (kör nokta planı, 22 Oct): what STR-7 and STR-10 must measure on the pages that matter, whatever the sample.

Live, on a Ticimax shop: three 1.1-1.8 MB lazy banners on the homepage declared no size and were never asked for, a
10 MB video named only in the homepage's VideoObject (a script inserts the player on scroll) was never sized, and a
200 × 200 share image behind a redirect to the platform's CDN was never read. Each rule below is written for any
site, with a test of what it must find and one of what it must not."""

from __future__ import annotations

import struct

from fakeserver import FakeServer
from fakeserver.scenarios import robots
from fakeserver.server import Response, Site
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.findings import Severity

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0}
ALLOW = robots("User-agent: *\nAllow: /\n")
JPEG = Response(body=b"\xff\xd8" + b"\0" * 900, content_type="image/jpeg")


def png(width: int, height: int, pad: int = 200) -> Response:
    """A PNG whose header says width × height (all STR-10 reads), padded to `pad` bytes."""
    head = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return Response(body=head + b"\0" * max(0, pad - len(head)), content_type="image/png")


def page(body: str, head: str = "") -> Response:
    return Response(body=f'<!doctype html><html lang="en"><head><title>Shop page</title>{head}</head><body><main>'
                         f'<h1>Shop</h1><p>{"Words about the shop and its products. " * 20}</p>{body}</main></body></html>')


def audit(site: Site, home_body: str, home_head: str = "", cdn: str = "", **config):
    """Audit `site` with a homepage of `home_body` linking six pages; "{cdn}" in the homepage names `cdn`."""
    with FakeServer(site) as server:
        links = "".join(f'<a href="/p{n}">P{n}</a>' for n in range(6))
        site.routes["/"] = page(links + home_body.replace("{cdn}", cdn), home_head.replace("{cdn}", cdn))
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**FAST, "max_pages": 10, **config}))
        return outcome, list(server.requests)


def findings(outcome, check_id: str) -> list:
    return [f for c in outcome.checks if c.check_id == check_id for f in c.findings]


def thumbs_site(**extra) -> Site:
    """Six pages of six small product photos each, so the page-by-page sample has plenty to choose from."""
    pages = {f"/p{n}": page("".join(f'<img src="/t/{n}-{k}.jpg" alt="Item {k}">' for k in range(6))) for n in range(6)}
    return Site({"/robots.txt": ALLOW, **pages, **{f"/t/{n}-{k}.jpg": JPEG for n in range(6) for k in range(6)}, **extra})


# -- images: every image of the homepage, whatever it declares -----------------------------------------------------
def test_a_lazy_banner_with_no_declared_size_low_on_the_homepage_is_measured():
    small = "".join(f'<img src="/home/{k}.jpg" alt="Tile {k}">' for k in range(5))
    banner = '<img class="lazy" src="/img/blank.gif" data-src="/home/kampanya-banner.jpg" alt="Kampanya">'
    heavy_png = Response(body=b"\x89PNG\r\n\x1a\n" + b"\0" * 1_700_000, content_type="image/png")
    site = thumbs_site(**{f"/home/{k}.jpg": JPEG for k in range(5)}, **{"/home/kampanya-banner.jpg": heavy_png})
    outcome, requests = audit(site, small + banner, image_checks_max=4)
    assert "/home/kampanya-banner.jpg" in [r.path for r in requests]
    heavy = next(f for f in findings(outcome, "STR-7") if "over 500 KB" in f.title)
    assert heavy.severity == Severity.S3  # over 1 MB on the homepage
    mismatch = next(f for f in findings(outcome, "STR-7") if "format their file name" in f.title)
    assert mismatch.evidence["images"][0]["content_type"] == "image/png"


def test_the_key_page_images_have_their_own_cap_on_top_of_the_sample():
    home = "".join(f'<img src="/home/{k}.jpg" alt="Tile {k}">' for k in range(12))
    site = thumbs_site(**{f"/home/{k}.jpg": JPEG for k in range(12)})
    _, requests = audit(site, home, image_checks_max=2, key_image_checks_max=5)
    asked = [r.path for r in requests if r.path.startswith(("/home/", "/t/"))]
    assert len(asked) == 7 and sum(p.startswith("/home/") for p in asked) >= 5


def test_no_image_is_requested_when_the_image_check_is_off():
    home = "".join(f'<img src="/home/{k}.jpg" alt="Tile {k}">' for k in range(4))
    site = thumbs_site(**{f"/home/{k}.jpg": JPEG for k in range(4)})
    _, requests = audit(site, home, image_checks_max=0)
    assert not [r for r in requests if r.path.startswith(("/home/", "/t/"))]


def test_small_homepage_images_are_measured_but_not_reported():
    home = "".join(f'<img src="/home/{k}.jpg" alt="Tile {k}">' for k in range(8))
    site = thumbs_site(**{f"/home/{k}.jpg": JPEG for k in range(8)})
    outcome, requests = audit(site, home, image_checks_max=2)
    assert sum(r.path.startswith("/home/") for r in requests) == 8
    assert not [f for f in findings(outcome, "STR-7") if "over 500 KB" in f.title or "format their file name" in f.title]


# -- videos ---------------------------------------------------------------------------------------------------------
def video_object(content_url: str) -> str:
    return ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"VideoObject","name":"Tanıtım",'
            '"thumbnailUrl":"/poster.jpg","uploadDate":"2026-01-05","contentUrl":"' + content_url + '"}</script>')


def asset_host(**files) -> Site:
    """Another host that serves most of the site's images: the site's asset host."""
    return Site({"/robots.txt": ALLOW, **{f"/a/{k}.jpg": JPEG for k in range(6)}, **files})


def test_a_video_named_only_by_its_videoobject_on_the_asset_host_is_sized():
    cdn_site = asset_host(**{"/v/promo.mp4": Response(body=b"\0" * 6_000_000, content_type="video/mp4")})
    with FakeServer(cdn_site, host="localhost") as cdn:
        images = "".join(f'<img src="{{cdn}}/a/{k}.jpg" alt="Item {k}">' for k in range(6))
        outcome, _ = audit(Site({"/robots.txt": ALLOW, **{f"/p{n}": page("<p>x</p>") for n in range(6)}}),
                           images + video_object("{cdn}/v/promo.mp4"), cdn=cdn.base_url, check_external_links=False)
        asked = [r.path for r in cdn.requests]
    assert "/v/promo.mp4" in asked
    [video] = [f for f in findings(outcome, "STR-7") if "video file(s)" in f.title]
    row = video.evidence["videos"][0]
    assert row["bytes"] == 6_000_000 and row["found_by"] == "structured_data"
    assert any("contentUrl" in note for note in video.notes)


def test_a_lazy_video_source_is_sized():
    site = Site({"/robots.txt": ALLOW, **{f"/p{n}": page("<p>x</p>") for n in range(6)},
                 "/v/clip.mp4": Response(body=b"\0" * 5_500_000, content_type="video/mp4")})
    outcome, requests = audit(site, '<video muted playsinline><source data-src="/v/clip.mp4" type="video/mp4"></video>')
    assert "/v/clip.mp4" in [r.path for r in requests]
    assert [f for f in findings(outcome, "STR-7") if "video file(s)" in f.title]


def test_a_videoobject_pointing_at_a_watch_page_or_another_site_is_not_downloaded():
    site = Site({"/robots.txt": ALLOW, **{f"/p{n}": page("<p>x</p>") for n in range(6)}})
    outcome, requests = audit(site, video_object("https://www.youtube.com/watch?v=abc123")
                              + video_object("https://video.other.example/clip.mp4"), check_external_links=False)
    structure = outcome.result.structure
    assert "https://www.youtube.com/watch?v=abc123" not in structure.videos
    assert structure.videos["https://video.other.example/clip.mp4"]["reason"] == "on another site"
    assert not [f for f in findings(outcome, "STR-7") if "video file(s)" in f.title]


# -- the share image ------------------------------------------------------------------------------------------------
def test_a_share_image_redirected_to_the_asset_host_is_read_and_a_200px_one_is_a_note():
    cdn_site = asset_host(**{"/og/share.png": png(200, 200)})
    with FakeServer(cdn_site, host="localhost") as cdn:
        site = Site({"/robots.txt": ALLOW, **{f"/p{n}": page("<p>x</p>") for n in range(6)}})
        site.routes["/uploads/share.png"] = Response(status=301, headers={"Location": f"{cdn.base_url}/og/share.png"})
        images = "".join(f'<img src="{{cdn}}/a/{k}.jpg" alt="Item {k}">' for k in range(6))
        outcome, _ = audit(site, images, home_head='<meta property="og:image" content="/uploads/share.png">',
                           cdn=cdn.base_url, check_external_links=False)
    str10 = findings(outcome, "STR-10")
    [thumb] = [f for f in str10 if "600 × 315" in f.title]
    assert thumb.severity == Severity.INFO
    assert thumb.evidence["images"][0]["image"]["width"] == 200 and thumb.evidence["images"][0]["hops"]
    assert not [f for f in str10 if "200 × 200" in f.title]


def test_a_large_share_image_is_not_noted_and_a_tiny_one_stays_s4():
    site = Site({"/robots.txt": ALLOW, **{f"/p{n}": page("<p>x</p>") for n in range(6)},
                 "/og/large.png": png(1200, 630), "/og/tiny.png": png(120, 120)})
    outcome, _ = audit(site, "", home_head='<meta property="og:image" content="/og/large.png">')
    assert not [f for f in findings(outcome, "STR-10") if "share image smaller" in f.title]
    site.routes["/p0"] = page("<p>x</p>", '<meta property="og:image" content="/og/tiny.png">')
    outcome, _ = audit(site, "", home_head='<meta property="og:image" content="/og/large.png">')
    str10 = findings(outcome, "STR-10")
    assert [f.severity for f in str10 if "200 × 200" in f.title] == [Severity.S4]
    assert not [f for f in str10 if "600 × 315" in f.title]
