"""Review G07/G08 and live gaps 1, 2 and 4, worker gx2: which image and video files STR-7 samples, how it asks for them,
and how heavy media is weighed by where it is shown."""

from __future__ import annotations

import os

import pytest

from fakeserver import FakeServer
from fakeserver.scenarios import robots
from fakeserver.server import Response, Site
from maya_audit.audit import run_audit
from maya_audit.checks.structure import media_weight_findings, negotiated_format
from maya_audit.config import CrawlConfig
from maya_audit.findings import Severity
from maya_audit.media_sample import media_requests

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0}


def image(url, size, kind="image/jpeg", pages=("https://s.test/p",), vary=None):
    return {"url": url, "pages": list(pages), "source": "fetched", "status": 200, "content_type": kind, "vary": vary,
            "content_length": str(size), "body_bytes": 4096, "body_truncated": True}


# -- G07 ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("row", [
    image("https://s.test/a.jpg", 9, "image/webp", vary="Accept-Encoding, Accept"),
    image("https://shop.test/cdn/shop/files/a.jpg?width=800", 9, "image/png"),
    image("https://res.cloudinary.com/x/image/upload/f_auto,q_auto/a.jpg", 9, "image/png"),
    image("https://x.imgix.net/a.png?auto=format,compress", 9, "image/jpeg"),
    image("https://s.test/_next/image?url=%2Fa.png&w=640", 9, "image/jpeg"),
    image("https://s.test/a.png", 9, "image/avif"),
])
def test_an_image_service_or_a_lighter_format_is_not_a_mismatch(row):
    assert media_weight_findings([row], [], set()) == []


def test_a_heavier_format_under_a_lighter_name_is_still_noted():
    [note] = media_weight_findings([image("https://s.test/banner.jpg", 9, "image/png")], [], set())
    assert note.severity == Severity.INFO and note.evidence["images"][0]["content_type"] == "image/png"
    assert negotiated_format(image("https://s.test/banner.jpg", 9, "image/png"), "jpg", "image/png") is None


# -- G08 ---------------------------------------------------------------------------------------------------------
def test_a_very_heavy_image_off_the_homepage_and_key_pages_is_s4():
    rows = [image("https://s.test/kampanya.gif", 5_000_000, "image/gif", pages=["https://s.test/kampanya"])]
    [heavy] = media_weight_findings(rows, [], {"https://s.test/urun"}, "https://s.test/")
    assert heavy.severity == Severity.S4


def test_a_very_heavy_image_on_a_key_page_is_s3():
    rows = [image("https://s.test/a.jpg", 2_000_000, pages=["https://s.test/urun"]),
            image("https://s.test/b.jpg", 3_000_000, pages=["https://s.test/kampanya"])]
    [heavy] = media_weight_findings(rows, [], {"https://s.test/urun"}, "https://s.test/")
    assert heavy.severity == Severity.S3 and len(heavy.evidence["images"]) == 2


# -- live gaps 1 and 4: the sample ---------------------------------------------------------------------------------
def page(body, head=""):
    return Response(body=f'<!doctype html><html lang="en"><head><title>Shop page</title>{head}</head><body><main>'
                         f'<h1>Shop</h1><p>{"Words about the shop and its products. " * 20}</p>{body}</main></body></html>')


def audit(site, **config):
    """Audit `site`; its "/" body is wrapped as a homepage linking six pages, "{img}" in it naming another host of
    the same server."""
    with FakeServer(site) as server:
        port = server.base_url.rsplit(":", 1)[1]
        links = "".join(f'<a href="/p{n}">P{n}</a>' for n in range(6))
        site.routes["/"] = page(links + site.routes["/"].body.replace("{img}", f"http://img.localhost:{port}"))
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**FAST, "max_pages": 10, **config}))
        return outcome, list(server.requests)


def test_the_homepage_hero_is_sampled_before_the_other_pages_images():
    thumbs = {f"/p{n}": page("".join(f'<img src="/t/{n}-{k}.jpg" alt="Item {k}">' for k in range(6))) for n in range(6)}
    images = {f"/t/{n}-{k}.jpg": Response(body=b"\xff\xd8" + b"\0" * 900, content_type="image/jpeg")
              for n in range(6) for k in range(6)}
    hero = Response(body=b"\xff\xd8" + b"\0" * 2_500_000, content_type="image/jpeg")
    home = '<img src="/hero/banner-2.jpg" alt="Autumn collection" width="1920" height="800">'
    site = Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": Response(body=home), **thumbs, **images,
                 "/hero/banner-2.jpg": hero})
    outcome, requests = audit(site, image_checks_max=4)
    assert "/hero/banner-2.jpg" in [r.path for r in requests]
    [heavy] = [f for c in outcome.checks for f in c.findings if "over 500 KB" in f.title]
    assert heavy.severity == Severity.S3


def test_the_sites_asset_host_is_sampled_with_other_sites_off_and_asked_like_a_browser():
    # The images live on another host (localhost beside the site's 127.0.0.1): it serves all of them, so it is the
    # site's asset host and its images are requested although links to other sites are off.
    images = Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"),
                   **{f"/a/{k}.jpg": Response(body=b"RIFF" + b"\0" * 200, content_type="image/webp") for k in range(6)}})
    with FakeServer(images, host="localhost") as cdn:
        home = "".join(f'<img src="{cdn.base_url}/a/{k}.jpg" alt="Item {k}">' for k in range(6))
        site = Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": Response(body=home),
                     **{f"/p{n}": page("<p>x</p>") for n in range(6)}})
        outcome, _ = audit(site, check_external_links=False)
        asked = [r for r in cdn.requests if r.path.startswith("/a/")]
    assert len(asked) == 6 and all("image/webp" in (r.headers.get("accept") or "") for r in asked)
    str7 = next(c for c in outcome.checks if c.check_id == "STR-7")
    assert str7.evidence["image_files_requested"] == 6
    assert not [f for f in str7.findings if "format" in f.title]  # WebP under .jpg is lighter: not a mismatch


# -- live gap 2: videos a script loads ----------------------------------------------------------------------------
def test_media_requests_are_the_video_files_without_stream_manifests():
    entry = {"requests": [{"url": "https://s.test/v/clip.mp4", "type": "media"},
                          {"url": "https://s.test/v/clip.mp4", "type": "media"},
                          {"url": "https://s.test/v/live.m3u8", "type": "xhr"},
                          {"url": "https://s.test/v/seg1.ts", "type": "media"},
                          {"url": "https://s.test/v/teaser.webm", "type": "fetch"},
                          {"url": "https://s.test/app.js", "type": "script"},
                          {"url": "https://s.test/", "type": "document", "main_document": True}]}
    assert media_requests(entry) == ["https://s.test/v/clip.mp4", "https://s.test/v/teaser.webm"]


def _no_browser() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
    except Exception as exc:  # noqa: BLE001
        return f"Playwright unavailable: {exc}"
    return None if os.path.exists(path) else f"Chromium is not installed ({path})"


@pytest.mark.skipif(_no_browser() is not None, reason=_no_browser() or "")
def test_a_video_a_script_inserts_is_sized_when_rendering_ran():
    script = ("<script>var v=document.createElement('video');v.src='/v/promo.mp4';v.muted=true;v.autoplay=true;"
              "v.preload='auto';document.querySelector('main').appendChild(v);</script>")
    site = Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": Response(body=script),
                 **{f"/p{n}": page("<p>x</p>") for n in range(6)},
                 "/v/promo.mp4": Response(body=b"\0" * 6_000_000, content_type="video/mp4")})
    outcome, requests = audit(site, render_enabled=True)
    [video] = [f for c in outcome.checks for f in c.findings if "video file(s)" in f.title]
    assert video.evidence["videos"][0]["bytes"] == 6_000_000
