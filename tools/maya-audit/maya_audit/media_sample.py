"""Which image and video files STR-7 requests, and how (review G07, G08; live gaps 1, 2 and 4, worker gx2).

STR-7 sizes a sample of the files the pages show; it never downloads them (one small GET, the size from the answer's
Content-Length). This module decides three things for that sample, so `structure_data` (the requests) and
`other_sites` (the queue of requests to other sites) decide them the same way:

- The order (live gap 1). Every image the homepage and the key pages show or preload comes first, under its own cap
  (key_image_checks_max, P1); then the sample proper: the homepage's first images, its preloads and the
  largest-declared images, then the rest page by page. Ordering by declared size alone missed banners that declare
  none (live, 22 Oct: three 1.1-1.8 MB lazy banners on a homepage were never asked for).
- Which hosts are the site's own (live gap 4). The audited site's registrable domain, and a host that serves most of
  the site's content images (static.<platform>.cloud, a shop's image CDN): its images are requested like the site's
  own, also with --no-external-links, under the same cap (image_checks_max) and robots.txt. This narrows decision 211
  ("an image on another site only when links to other sites are checked") to hosts that are not the site's asset host.
- What is asked for: the Accept header a browser sends for an image (G07), so an image service that picks the
  format from it answers what a reader gets.

And the videos a page loads by script (live gap 2): when rendering ran, the media files the browser asked for are
sized with the same small request as the <video src> files the markup names. A video a script inserts only later
(on scroll, after a click) is never asked for by the render, so the markup's own promise is read too (P1): a
VideoObject's contentUrl and a lazy loader's data-src. Videos on the site's asset host are the site's own, as images.
"""

from __future__ import annotations

import ipaddress
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from .config import ASSET_HOST_MIN_IMAGES, ASSET_HOST_SHARE, IMAGE_ACCEPT, IMAGE_SAMPLE_HERO, IMAGE_SAMPLE_PRIORITY_SHARE
from .urls import normalize_url, origin_of, registrable_domain

IMAGE_HEADERS = {"Accept": IMAGE_ACCEPT}
# A video file the browser asked for, by its address: HLS and DASH manifests and their segments are left out (a
# manifest is a few KB that names the real files; its size says nothing about the page's weight).
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".ogv")
STREAM_EXTENSIONS = (".m3u8", ".mpd", ".ts", ".m4s")


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def asset_hosts(result) -> set[str]:
    """Hosts on another registrable domain that serve at least ASSET_HOST_SHARE of the site's distinct content images,
    and at least ASSET_HOST_MIN_IMAGES of them: the site's own asset host, whatever its domain."""
    from .structure_data import content_images, indexable_pages

    site = registrable_domain(_host(getattr(result, "origin", "") or ""))
    urls = {img["url"] for page in indexable_pages(result) for img in content_images(page)}
    by_host = Counter(_host(url) for url in urls)
    return {host for host, n in by_host.items()
            if host and registrable_domain(host) != site and n >= ASSET_HOST_MIN_IMAGES and n >= ASSET_HOST_SHARE * len(urls)}


def own_image(url: str, result, hosts: set[str]) -> bool:
    """Whether an image is requested as the site's own: its origin, its registrable domain, or its asset host. An IP
    address has no registrable domain (`registrable_domain` returns it unchanged), so another port on the same address
    is another site unless it is the asset host."""
    host = _host(url)
    site = registrable_domain(_host(result.origin))
    same_domain = registrable_domain(host) == site and not _is_ip(host)
    return origin_of(url) == result.origin or same_domain or host in hosts


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _area(img: dict) -> int:
    try:
        return int(img.get("width") or 0) * int(img.get("height") or 0)
    except (TypeError, ValueError):
        return 0


def key_image_limit(cfg) -> int:
    """How many images of the homepage and the key pages are sized on top of the sample (P1): none when the image
    check is off (image_checks_max 0)."""
    return max(0, getattr(cfg, "key_image_checks_max", 0)) if getattr(cfg, "image_checks_max", 0) > 0 else 0


def image_sample(result, limit: int, key_urls=(), key_limit: int = 0) -> tuple[list[tuple[str, list[str]]], int]:
    """Up to `key_limit` + `limit` image addresses, each with the pages that show it, and how many distinct addresses
    there are. First (P1), up to `key_limit`: every image the homepage preloads or shows, then every image of each
    key page, in page order, whatever size they declare. Then the sample of `limit`: at most
    IMAGE_SAMPLE_PRIORITY_SHARE of it the homepage's preloaded images and its first IMAGE_SAMPLE_HERO content images,
    the largest-declared images of the homepage and the key pages, and each key page's first images; then one page at
    a time, so the rest of the sample is spread over the site."""
    from .access_data import homepage_url
    from .structure_data import content_images, indexable_pages

    pages = indexable_pages(result)
    per_page = [(page.url, list(dict.fromkeys(img["url"] for img in content_images(page)))) for page in pages]
    shown_on: dict[str, list[str]] = {}
    for page_url, urls in per_page:
        for url in urls:
            shown_on.setdefault(url, []).append(page_url)
    home = homepage_url(result)
    important = [page for page in pages if page.url == home] + [page for page in pages if page.url in set(key_urls)
                                                                   and page.url != home]
    priority: list[str] = []
    every_key_image: list[str] = []
    for n, page in enumerate(important):
        if n == 0 and page.url == home:
            for row in page.analysis.get("image_preloads") or []:
                url = normalize_url(row.get("href") or "", page.url)
                if url:
                    shown_on.setdefault(url, [page.url])
                    priority.append(url)
                    every_key_image.append(url)
        priority += [img["url"] for img in content_images(page)[:IMAGE_SAMPLE_HERO]]
        every_key_image += [img["url"] for img in content_images(page)]
    # P1: the homepage's and the key pages' images, all of them up to their own cap, before the sample.
    pinned = list(dict.fromkeys(every_key_image))[:max(0, key_limit)]
    declared = sorted(((img, page.url) for page in important for img in content_images(page) if _area(img)),
                      key=lambda pair: -_area(pair[0]))
    priority += [img["url"] for img, _ in declared]
    chosen: dict[str, None] = {}
    for url in priority:
        if len(chosen) >= max(1, int(limit * IMAGE_SAMPLE_PRIORITY_SHARE)) or len(chosen) >= limit:
            break
        if url not in pinned:
            chosen.setdefault(url, None)
    depth = 0
    while len(chosen) < limit and any(depth < len(urls) for _, urls in per_page):
        for _, urls in per_page:
            if depth < len(urls) and len(chosen) < limit and urls[depth] not in pinned:
                chosen.setdefault(urls[depth], None)
        depth += 1
    return [(url, shown_on[url][:5]) for url in [*pinned, *chosen]], len(shown_on)


def media_requests(entry: dict[str, Any]) -> list[str]:
    """The video files a rendered page asked for (the browser's own requests, routed or aborted): a media request,
    or any request for an address with a video file's extension; stream manifests and segments left out."""
    out = []
    for row in entry.get("requests") or []:
        url = row.get("url") or ""
        path = urlsplit(url).path.lower()
        if path.endswith(STREAM_EXTENSIONS) or row.get("main_document"):
            continue
        if row.get("type") == "media" or path.endswith(VIDEO_EXTENSIONS):
            out.append(url)
    return list(dict.fromkeys(out))


def size_rendered_videos(fetcher, result, cfg, render_data) -> None:
    """Live gap 2: the video files rendered pages asked for that the markup did not name, sized like the others
    (one small GET, `video_size`, 4 KB) and added to STR-7's videos: on this site or its asset host, allowed by
    robots.txt, within
    what is left of the same cap (VIDEO_CHECKS_MAX, never more than image_checks_max)."""
    from .structure_data import VIDEO_CHECKS_MAX

    data = getattr(result, "structure", None)
    if data is None:
        return
    shown_on: dict[str, list[str]] = {}
    for page_url, entry in (getattr(render_data, "pages", None) or {}).items():
        requested = media_requests(entry) if isinstance(entry, dict) else []
        if requested:
            entry["media_requests"] = requested[:20]
        for url in requested:
            shown_on.setdefault(url, []).append(page_url)
    from .crawler import load_robots  # local import: crawler does not import this module

    room = min(VIDEO_CHECKS_MAX, cfg.image_checks_max) - len(data.videos)
    hosts = asset_hosts(result)
    for url, pages in shown_on.items():
        if url in data.videos:
            continue
        if room <= 0:
            break
        entry: dict[str, Any] = {"url": url, "pages": list(dict.fromkeys(pages))[:5], "found_by": "rendering"}
        data.videos[url] = entry
        room -= 1
        size_video(fetcher, result, cfg, data, entry, hosts, load_robots)


def video_sources(page) -> list[tuple[str, str]]:
    """(video file address, how it was found) for one page: a <video>'s or <source>'s src or data-src ("markup"), and
    a VideoObject's contentUrl that names a video file ("structured_data", P1). A contentUrl that is a page (a video
    platform's watch page) is left out: it is not a file the page downloads."""
    from .analysis import iter_typed_nodes, node_types

    out: list[tuple[str, str]] = []
    for media in page.analysis.get("media") or []:
        for src in [media.get("src"), *(media.get("sources") or [])]:
            url = normalize_url(src, page.url) if src and not src.lower().startswith("data:") else None
            if url:
                out.append((url, "markup"))
    for item in page.analysis.get("_structured_items") or []:
        for node, _nested in iter_typed_nodes(item.get("data")):
            if "VideoObject" not in node_types(node):
                continue
            for value in node.get("contentUrl") if isinstance(node.get("contentUrl"), list) else [node.get("contentUrl")]:
                url = normalize_url(value, page.url) if isinstance(value, str) and value.strip() else None
                if url and urlsplit(url).path.lower().endswith(VIDEO_EXTENSIONS):
                    out.append((url, "structured_data"))
    return list(dict.fromkeys(out))


def size_video(fetcher, result, cfg, data, entry: dict[str, Any], hosts: set[str], load_robots) -> None:
    """One small GET (`video_size`, 4 KB) for a video file, the size read from Content-Length: only on this site or
    its asset host, and only when that host's robots.txt allows it (read first if the audit has not yet)."""
    url = entry["url"]
    if not own_image(url, result, hosts):
        entry.update(source="not_fetched", reason="on another site")
        return
    origin = origin_of(url)
    if origin not in result.robots_policy_by_origin and load_robots is not None:
        result.robots_policy_by_origin[origin] = load_robots(fetcher, origin, cfg)
    policy = result.robots_policy_by_origin.get(origin)
    decision = policy.decide(cfg.product_token, url) if policy is not None else None
    if decision is None or not decision.allowed:
        entry.update(source="not_fetched", reason=f"robots.txt for {origin} "
                     + ("was not read" if decision is None else f"disallows it: {decision.reason}"))
        return
    response = fetcher.get(url, "video_size", 4096)
    if response.error == "audit_deadline_skipped":
        entry.update(source="not_fetched", reason="the audit's time limit was reached before this video was checked")
        data.cut_by_time_limit += 1
        return
    entry.update(source="fetched", status=response.status, error=response.error,
                 content_type=response.headers.get("content-type"), requested_at=response.started_at,
                 method="GET", body_bytes=len(response.body), body_truncated=response.truncated,
                 content_length=response.headers.get("content-length"))
