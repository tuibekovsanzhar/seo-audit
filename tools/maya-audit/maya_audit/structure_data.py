"""Data collected after the crawl for STR checks: statuses of URLs that pages point to.

STR-5 (sameAs), STR-9 (hreflang targets), and STR-10 (og:image) need to know whether
a referenced URL works. URLs the crawl already fetched are reused. Other URLs on the
audited origin are requested (robots.txt obeyed, capped). URLs on any other origin go
through `maya_audit.external_links` (DECISIONS 211): that origin's robots.txt is fetched
and obeyed first, and every request counts toward one cap for the audit. With external
link checks off (`--no-external-links`, demo mode) only sameAs profile links are asked.
IDX-6's links to other sites are asked here too, last. Every request goes through the
same fetcher, so INT-4 audits it like any other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .analysis import analyze_html, iter_typed_nodes, node_types
from .html_links import decode_body, is_html
from .config import CrawlConfig
from .directives import noindex_directives
from .fetcher import Fetcher
from .index_data import canonical_elsewhere
from .models import CrawlResult, FetchClass
from urllib.parse import urlsplit

from .urls import normalize_url, origin_of, registrable_domain

# Organization and the subtypes commonly used for a brand. Not exhaustive (LocalBusiness alone has hundreds of
# subtypes); unrecognized types are listed in STR-3 evidence so a person can see what was there.
ORGANIZATION_TYPES = frozenset({
    "Organization", "Corporation", "LocalBusiness", "OnlineBusiness", "OnlineStore", "NGO", "EducationalOrganization",
    "GovernmentOrganization", "MedicalOrganization", "NewsMediaOrganization", "ResearchOrganization",
    "SportsOrganization", "PerformingGroup", "Airline", "Consortium", "Store", "Restaurant", "ProfessionalService",
    "FinancialService", "LegalService", "Project", "WorkersUnion", "LibrarySystem", "FundingScheme",
    # Banks, insurers, food, health and hotels (DECISIONS 229, FA-032): a card site's homepage typed only
    # BankOrCreditUnion was told it had no Organization structured data.
    "BankOrCreditUnion", "InsuranceAgency", "AccountingService", "FoodEstablishment", "CafeOrCoffeeShop", "Bakery",
    "BarOrPub", "FastFoodRestaurant", "Hospital", "MedicalClinic", "Physician", "Dentist", "Pharmacy", "Hotel",
})
# The list before DECISIONS 229, for STR-3's "@id given different types" only: the names added there are subtypes that
# a site often gives beside their parent on one @id (BankOrCreditUnion with FinancialService), which is no clash.
CLASH_ORGANIZATION_TYPES = ORGANIZATION_TYPES - {
    "BankOrCreditUnion", "InsuranceAgency", "AccountingService", "FoodEstablishment", "CafeOrCoffeeShop", "Bakery",
    "BarOrPub", "FastFoodRestaurant", "Hospital", "MedicalClinic", "Physician", "Dentist", "Pharmacy", "Hotel"}


def readable_html(page) -> bool:
    return page.readable_document() and is_html(page.content_type) and page.analysis is not None


def _page_key(url: str) -> tuple | None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not host or parts.scheme.lower() not in ("http", "https"):
        return None
    default = {"http": 80, "https": 443}
    port = None if port in (None, default.get(parts.scheme.lower())) else port
    return host, port, parts.path.rstrip("/") or "/", parts.query


def same_page(url_a: str | None, url_b: str | None) -> bool:
    """True when two addresses name one page: they differ at most by the scheme (http/https), a "www." prefix and a
    trailing slash (review G17). A canonical or a hreflang link written as `/en/` for the page at `/en`, or on the
    site's http:// variant, names the page itself, not another one. The query must match and the path's letter case
    too: `/En` and `?page=2` can be other pages."""
    if not url_a or not url_b:
        return False
    key_a, key_b = _page_key(url_a), _page_key(url_b)
    return key_a is not None and key_a == key_b


def indexable_pages(result: CrawlResult) -> list:
    """Readable HTML pages that are candidates for citation: no noindex, and canonical absent or self. A canonical on
    the http:// or www variant of the page's own address counts as self (review B02): IDX-4 reports it, and the page is
    not silently dropped from every content check."""
    out = []
    for page in result.pages:
        if not (readable_html(page) and page.content_checks_eligible):
            continue
        if noindex_directives(page.analysis, page.headers):
            continue
        if canonical_elsewhere(page):
            continue
        out.append(page)
    return out


def organization_nodes(analysis: dict) -> list[dict]:
    return [node for item in analysis.get("_structured_items", []) for node, _ in iter_typed_nodes(item["data"])
            if ORGANIZATION_TYPES & set(node_types(node))]


def department_nodes(analysis: dict) -> list[dict]:
    """Explicit organizational subunits, not inferred from their names or paths.

    A department is not a competing parent identity. This does not establish that
    its label is an owner-confirmed search alias or translated brand name.
    """
    out = []
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'department':
                    out.extend(n for n in as_list(child) if isinstance(n, dict))
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for item in analysis.get('_structured_items') or []:
        walk(item.get('data'))
    return out


def identity_organization_nodes(analysis: dict) -> list[dict]:
    excluded = {id(node) for node in department_nodes(analysis)}
    department_ids = {node.get('@id') for node in department_nodes(analysis) if node.get('@id')}
    return [node for node in organization_nodes(analysis)
            if id(node) not in excluded and node.get('@id') not in department_ids]


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def text_value(value) -> str | None:
    """A property value as text: a string, or the name / @id / url of a nested object."""
    for v in as_list(value):
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        if isinstance(v, dict):
            for key in ("name", "@value", "url", "@id"):
                if isinstance(v.get(key), str) and v[key].strip():
                    return v[key].strip()
    return None


@dataclass
class StructureData:
    # url -> {"url", "source": "crawl"|"fetched"|"not_fetched", "status", "error", "content_type", "location",
    #         "reason", "hreflang", "html_lang"}; an og:image also "image" ({"format", "width", "height"}, when its
    #         first 64 KB say so) and "hops" (same-site redirects followed, DECISIONS 209).
    links: dict[str, dict[str, Any]] = field(default_factory=dict)
    external_links_enabled: bool = False
    same_origin_requests: int = 0
    external_requests: int = 0
    cut_by_time_limit: int = 0  # link checks not made because the audit's time limit was reached
    # STR-7: image address -> {"url", "pages": [...], "source": "fetched"|"not_fetched", "status", "error",
    #                          "content_type", "reason"}; a sample, spread over the pages.
    images: dict[str, dict[str, Any]] = field(default_factory=dict)
    image_candidates: int = 0  # distinct main-content image addresses on the checked pages
    image_requests: int = 0
    # H29: the files <video src> / <source src> on the pages read play, video address -> {"url", "pages", "source",
    #      "status", "content_type", "content_length", ...}; one small GET each, at most VIDEO_CHECKS_MAX.
    videos: dict[str, dict[str, Any]] = field(default_factory=dict)
    # IDX-6 (DECISIONS 211): the links to other sites that were asked, url -> {"url", "pages", "links", "checked",
    # "verdict", "status", ...}, the most-linked first; how many there were; why the others were not asked.
    other_site_links: dict[str, dict[str, Any]] = field(default_factory=dict)
    other_site_link_candidates: int = 0
    other_site_links_not_checked: dict[str, int] = field(default_factory=dict)
    # The audit's requests to other sites (maya_audit.external_links.ExternalBudget.summary).
    external: dict[str, Any] | None = None


# og:image redirects on this site are followed this far (DECISIONS 209).
OG_IMAGE_HOPS = 3
OG_IMAGE_BYTES = 64 * 1024


def _u16(b: bytes, at: int, little: bool = False) -> int:
    return int.from_bytes(b[at:at + 2], "little" if little else "big")


def image_size(body: bytes) -> dict[str, Any] | None:
    """{"format", "width", "height"} read from the first bytes of a PNG, GIF, JPEG, WebP or ICO file, or None when
    they do not say (another format, or the size marker lies past the bytes received)."""
    b = body or b""
    size = None
    if b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) >= 24:
        size = ("png", int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big"))
    elif b[:6] in (b"GIF87a", b"GIF89a") and len(b) >= 10:
        size = ("gif", _u16(b, 6, True), _u16(b, 8, True))
    elif b[:4] == b"RIFF" and b[8:12] == b"WEBP" and len(b) >= 30:
        chunk = b[12:16]
        if chunk == b"VP8 ":
            size = ("webp", _u16(b, 26, True) & 0x3FFF, _u16(b, 28, True) & 0x3FFF)
        elif chunk == b"VP8L":
            size = ("webp", 1 + (((b[22] & 0x3F) << 8) | b[21]), 1 + (((b[24] & 0x0F) << 10) | (b[23] << 2) | ((b[22] & 0xC0) >> 6)))
        elif chunk == b"VP8X":
            size = ("webp", 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little"))
    elif b[:4] == b"\x00\x00\x01\x00" and len(b) >= 22:
        entries = [(b[at] or 256, b[at + 1] or 256) for at in range(6, 6 + 16 * min(_u16(b, 4, True), 16), 16) if at + 1 < len(b)]
        if entries:
            width, height = max(entries)
            size = ("ico", width, height)
    elif b[:2] == b"\xff\xd8":
        at = 2
        while at + 9 < len(b):
            if b[at] != 0xFF:
                at += 1
                continue
            marker = b[at + 1]
            if marker == 0xFF or marker == 0x01 or 0xD0 <= marker <= 0xD8:
                at += 1 if marker == 0xFF else 2
                continue
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                size = ("jpeg", _u16(b, at + 7), _u16(b, at + 5))
                break
            at += 2 + _u16(b, at + 2)
    if size is None or not (size[1] and size[2]):
        return None
    return {"format": size[0], "width": size[1], "height": size[2]}


def _targets(result: CrawlResult) -> list[tuple[str, str]]:
    """(url, kind) in priority order (DECISIONS 211): sameAs profile links first, then og:image, then hreflang
    alternates. Kind "same_as" needs the status only; "image" the first 64 KB (the image's size); "html" the page
    body (hreflang reciprocity)."""
    out: dict[str, str] = {}
    pages = indexable_pages(result)
    for page in result.pages:
        if page.analysis is None:
            continue
        for node in organization_nodes(page.analysis):
            for value in as_list(node.get("sameAs")):
                url = normalize_url(value, page.url) if isinstance(value, str) else None
                if url:
                    out.setdefault(url, "same_as")
    for page in pages:
        for value in page.analysis["og"].get("og:image", [])[:1]:
            url = normalize_url(value, page.url)
            if url:
                out.setdefault(url, "image")
    for page in pages:
        for link in page.analysis["hreflang"]:
            url = normalize_url(link["href"], page.url) if link["href"] else None
            if url:
                out.setdefault(url, "html")
    return list(out.items())


def _fetched(entry: dict[str, Any], response, url: str, purpose: str) -> None:
    entry.update(source="fetched", status=response.status, error=response.error,
                 content_type=response.headers.get("content-type"),
                 location=normalize_url(response.headers["location"], url) if response.headers.get("location") else None,
                 requested_at=response.started_at, purpose=purpose)


def collect_structure_data(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig) -> StructureData:
    from .crawler import load_robots  # local import: crawler does not import this module
    from . import external_links as external

    from .other_sites import active

    from .media_sample import asset_hosts, own_image

    data = StructureData(external_links_enabled=cfg.check_external_links)
    pool = active(result)
    hosts = asset_hosts(result)
    crawled = {p.url: p for p in result.pages}
    for url, kind in _targets(result):
        entry: dict[str, Any] = {"url": url, "kind": kind}
        data.links[url] = entry
        page = crawled.get(url)
        if page is not None:
            entry.update(source="crawl", status=page.status, error=page.error, content_type=page.content_type,
                         location=page.redirect_location, fetch_class=page.fetch_class.value,
                         hreflang=page.analysis["hreflang"] if page.analysis else None,
                         html_lang=page.analysis["html_lang"] if page.analysis else None)
            continue
        origin = origin_of(url)
        # An og:image on the site's asset host is the site's own (P1): asked here, under this site's link-check cap
        # and that host's robots.txt, also with --no-external-links (live: a platform CDN's share image went unread).
        if origin != result.origin and not (kind == "image" and own_image(url, result, hosts)):
            if pool is not None:  # asked by the other-site pool (DECISIONS 219 part 2), written once it is joined
                pool.later(lambda entry=entry, url=url, kind=kind: _from_pool(pool, fetcher, result, cfg, data, entry, url, kind))
            else:
                _ask_other_site(fetcher, result, cfg, data, entry, url, kind)
            continue
        if data.same_origin_requests >= cfg.str_link_checks_max:
            entry.update(source="not_fetched", reason=f"link check cap of {cfg.str_link_checks_max} reached")
            continue
        if origin not in result.robots_policy_by_origin:
            result.robots_policy_by_origin[origin] = load_robots(fetcher, origin, cfg)
        decision = result.robots_policy_by_origin[origin].decide(cfg.product_token, url)
        if not decision.allowed:
            entry.update(source="not_fetched", reason=f"robots.txt for {origin} disallows it: {decision.reason}")
            continue
        max_bytes = cfg.max_body_bytes if kind == "html" else OG_IMAGE_BYTES
        response = fetcher.get(url, "str_link_status", max_bytes)
        if response.error == "audit_deadline_skipped":
            # Not a failed link: the request was never sent. Reported as not checked, never as broken.
            entry.update(source="not_fetched", reason="the audit's time limit was reached before this link was checked")
            data.cut_by_time_limit += 1
            continue
        data.same_origin_requests += 1
        _fetched(entry, response, url, "str_link_status")
        if kind == "image":
            response = _follow_og_image(fetcher, result, cfg, data, entry, response, hosts, load_robots)
        _read_body(entry, kind, response)
    _check_images(fetcher, result, cfg, data, load_robots)
    _check_videos(fetcher, result, cfg, data)

    def other_links_and_counts() -> None:
        _check_other_site_links(fetcher, result, cfg, data)
        held = external.budget(result, cfg)
        data.external_requests = held.requests - held.robots_requests
        data.external = held.summary()

    if pool is not None:
        pool.later(other_links_and_counts)  # every answer is in the budget once the pool is joined
    else:
        other_links_and_counts()
    return data


def _from_pool(pool, fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, data: StructureData, entry: dict[str, Any],
               url: str, kind: str) -> None:
    """A sameAs link, an og:image or an hreflang alternate on another origin, from the other-site pool's answer."""
    from . import external_links as external
    from .other_sites import HTML, OG

    item = pool.item(url, OG if kind == "image" else HTML) if kind != "same_as" else None
    if item is None:
        # A sameAs link is answered from the budget's answers (external_links.check finds it there).
        _ask_other_site(fetcher, result, cfg, data, entry, url, kind)
        return
    if item.why is not None or item.response is None:
        why = item.why or "time_limit"
        entry.update(source="not_fetched", reason=external.REASONS[why])
        data.cut_by_time_limit += why == "time_limit"
        return
    _fetched(entry, item.response, url, external.GET_PURPOSE)
    _read_body(entry, kind, item.response)


def _read_body(entry: dict[str, Any], kind: str, response) -> None:
    content_type = entry.get("content_type")
    if not (response.status and 200 <= response.status < 300 and response.body):
        return
    if kind == "html" and is_html(content_type):
        analysis = analyze_html(decode_body(response.body, content_type))
        entry.update(hreflang=analysis["hreflang"], html_lang=analysis["html_lang"])
    elif kind == "image":
        size = image_size(response.body)
        if size:
            entry["image"] = size


def _follow_og_image(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, data: StructureData, entry: dict[str, Any],
                     response, hosts=frozenset(), load_robots=None):
    """An og:image on this site that redirects is followed on this site or its asset host (P1), at most OG_IMAGE_HOPS
    hops and within str_link_checks_max (DECISIONS 209). The entry then holds the last answer, and `hops` the way
    there."""
    from .media_sample import own_image

    hops = []
    while (response.status and 300 <= response.status < 400 and entry.get("location") and len(hops) < OG_IMAGE_HOPS
           and (origin_of(entry["location"]) == result.origin or own_image(entry["location"], result, hosts))
           and data.same_origin_requests < cfg.str_link_checks_max):
        target = entry["location"]
        origin = origin_of(target)
        if origin not in result.robots_policy_by_origin:
            if load_robots is None:
                break
            result.robots_policy_by_origin[origin] = load_robots(fetcher, origin, cfg)
        if not result.robots_policy_by_origin[origin].decide(cfg.product_token, target).allowed:
            break
        hops.append({"url": entry.get("final_url", entry["url"]), "status": response.status, "location": target})
        nxt = fetcher.get(target, "str_link_status", OG_IMAGE_BYTES)
        if nxt.error == "audit_deadline_skipped":
            break
        data.same_origin_requests += 1
        response = nxt
        _fetched(entry, response, target, "str_link_status")
        entry["final_url"] = target
    if hops:
        entry["hops"] = hops
    return response


def _ask_other_site(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, data: StructureData, entry: dict[str, Any],
                    url: str, kind: str) -> None:
    """A sameAs link, an og:image or an hreflang alternate on another origin (DECISIONS 211)."""
    from . import external_links as external

    if kind == "same_as":
        found = external.check(fetcher, result, cfg, url, same_as=True)
        entry.update(attempts=found.get("attempts"), verdict=found.get("verdict"))
        if not found.get("checked") or not found.get("requested_at"):
            entry.update(source="not_fetched", reason=found.get("reason"))
            data.cut_by_time_limit += found.get("verdict") == "time_limit"
            return
        entry.update(source="fetched", status=found.get("status"), error=found.get("error"), location=found.get("location"),
                     requested_at=found["requested_at"], purpose=external.HEAD_PURPOSE, method=found.get("method"))
        return
    why = external.room(fetcher, result, cfg, url)
    if why is not None:
        entry.update(source="not_fetched", reason=external.REASONS[why])
        data.cut_by_time_limit += why == "time_limit"
        return
    response = fetcher.get(url, external.GET_PURPOSE, cfg.max_body_bytes if kind == "html" else OG_IMAGE_BYTES)
    external.sent(result, cfg, url, response)
    if response.error == "audit_deadline_skipped":
        entry.update(source="not_fetched", reason="the audit's time limit was reached before this link was checked")
        data.cut_by_time_limit += 1
        return
    _fetched(entry, response, url, external.GET_PURPOSE)
    _read_body(entry, kind, response)


def other_site_link_targets(result: CrawlResult, cfg: CrawlConfig) -> list[dict[str, Any]]:
    """IDX-6 (DECISIONS 211): every link of the pages read to another site, once per address, with the pages that
    link to it, the most-linked first (then in the order they were found)."""
    from .external_links import other_site

    site = registrable_domain(urlsplit(result.origin).hostname or "")
    found: dict[str, dict[str, Any]] = {}
    for page in result.pages:
        for edge in page.external_links or []:
            url = edge["target"]
            if not other_site(url, result.origin, site, cfg.brand_family_domains):
                continue
            row = found.setdefault(url, {"url": url, "pages": [], "links": 0, "anchor": edge.get("anchor") or ""})
            if page.url not in row["pages"]:
                row["pages"].append(page.url)
            row["links"] += edge.get("links", 1)
    order = {url: n for n, url in enumerate(found)}
    return sorted(found.values(), key=lambda row: (-len(row["pages"]), -row["links"], order[row["url"]]))


def _check_other_site_links(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, data: StructureData) -> None:
    """Ask each link to another site, the most-linked first, within what is left of the cap (DECISIONS 211)."""
    from . import external_links as external

    targets = other_site_link_targets(result, cfg)
    data.other_site_link_candidates = len(targets)
    for row in targets:
        if not cfg.check_external_links:
            why = "off"
        else:
            found = external.check(fetcher, result, cfg, row["url"])
            if found.get("requested_at"):
                data.other_site_links[row["url"]] = {**{k: v for k, v in found.items() if k != "url"}, "url": row["url"],
                                                     "pages": row["pages"][:10], "pages_count": len(row["pages"]),
                                                     "links": row["links"], "anchor": row["anchor"][:120]}
                if not found["checked"]:
                    data.other_site_links_not_checked[found["verdict"]] = data.other_site_links_not_checked.get(found["verdict"], 0) + 1
                continue
            why = found["verdict"]
            data.cut_by_time_limit += why == "time_limit"
        data.other_site_links_not_checked[why] = data.other_site_links_not_checked.get(why, 0) + 1


def _image_from_pool(data: StructureData, entry: dict[str, Any], item) -> None:
    """STR-7's image on another site, from the other-site pool's answer (DECISIONS 219 part 2)."""
    from . import external_links as external

    if item.why is not None or item.response is None:
        why = item.why or "time_limit"
        entry.update(source="not_fetched", reason=("on another site; external link checks are off (--no-external-links)"
                                                   if why == "off" else external.REASONS[why]))
        data.cut_by_time_limit += why == "time_limit"
        return
    response = item.response
    data.image_requests += 1
    entry.update(source="fetched", status=response.status, error=response.error,
                 content_type=response.headers.get("content-type"), requested_at=response.started_at,
                     method="GET", body_bytes=len(response.body), body_truncated=response.truncated,
                     content_length=response.headers.get("content-length"), vary=response.headers.get("vary"))


def content_images(page) -> list[dict[str, Any]]:
    """The page's own images (in <main>, or outside header, nav and footer when there is no <main>) that have an
    address a browser can request, each with that address made absolute as "url"."""
    a = page.analysis
    out = []
    for img in a.get("images") or []:
        if not (img["in_main"] if a["has_main_region"] else not img["in_chrome"]):
            continue
        src = (img.get("src") or "").strip()
        url = normalize_url(src, page.url) if src and not src.lower().startswith(("data:", "#", "javascript:")) else None
        # src="#" or "?" resolves to the page itself: a theme's empty placeholder, not an image file that fails to load
        # (seen live: four "images that do not load" were the pages they were on).
        if url and url != page.url:
            out.append({**img, "url": url})
    return out


def image_sample(result: CrawlResult, limit: int, key_urls=(), key_limit: int = 0) -> tuple[list[tuple[str, list[str]]], int]:
    """Up to `key_limit` + `limit` image addresses, each with the pages that show it, and how many distinct addresses
    there are: every image of the homepage and the key pages first (P1), then the sample, page by page
    (maya_audit.media_sample, gx2)."""
    from .media_sample import image_sample as prioritised

    return prioritised(result, limit, key_urls, key_limit)


def _check_images(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, data: StructureData, load_robots) -> None:
    """Request a sample of image files to see whether they load. One small request each, paced like every other
    request; an image on another site is requested only when external link checks are on, and counts toward their
    cap (DECISIONS 211)."""
    from . import external_links as external
    from .access_data import key_page_urls
    from .media_sample import IMAGE_HEADERS, asset_hosts, key_image_limit, own_image
    from .other_sites import IMAGE, active

    sample, data.image_candidates = image_sample(result, cfg.image_checks_max, key_page_urls(result, cfg),
                                                 key_image_limit(cfg))
    hosts = asset_hosts(result)
    for url, pages in sample:
        entry: dict[str, Any] = {"url": url, "pages": pages}
        data.images[url] = entry
        origin = origin_of(url)
        own = own_image(url, result, hosts)
        pool = active(result)
        if not own and pool is not None and pool.item(url, IMAGE) is not None:
            pool.later(lambda entry=entry, item=pool.item(url, IMAGE): _image_from_pool(data, entry, item))
            continue
        if not own:
            why = external.room(fetcher, result, cfg, url) if cfg.check_external_links else "off"
            if why is not None:
                entry.update(source="not_fetched", reason=("on another site; external link checks are off (--no-external-links)"
                                                           if why == "off" else external.REASONS[why]))
                if why == "time_limit":
                    data.cut_by_time_limit += 1
                continue
            response = fetcher.get(url, "image_status", 4096, extra_headers=IMAGE_HEADERS)
            external.sent(result, cfg, url, response)
            if response.error == "audit_deadline_skipped":
                entry.update(source="not_fetched", reason="the audit's time limit was reached before this image was checked")
                data.cut_by_time_limit += 1
                continue
            data.image_requests += 1
            entry.update(source="fetched", status=response.status, error=response.error,
                         content_type=response.headers.get("content-type"), requested_at=response.started_at,
                     method="GET", body_bytes=len(response.body), body_truncated=response.truncated,
                     content_length=response.headers.get("content-length"), vary=response.headers.get("vary"))
            continue
        if origin not in result.robots_policy_by_origin:
            result.robots_policy_by_origin[origin] = load_robots(fetcher, origin, cfg)
        decision = result.robots_policy_by_origin[origin].decide(cfg.product_token, url)
        if not decision.allowed:
            entry.update(source="not_fetched", reason=f"robots.txt for {origin} disallows it: {decision.reason}")
            continue
        response = fetcher.get(url, "image_status", 4096, extra_headers=IMAGE_HEADERS)
        if response.error == "audit_deadline_skipped":
            entry.update(source="not_fetched", reason="the audit's time limit was reached before this image was checked")
            data.cut_by_time_limit += 1
            continue
        data.image_requests += 1
        entry.update(source="fetched", status=response.status, error=response.error,
                     content_type=response.headers.get("content-type"), requested_at=response.started_at,
                     method="GET", body_bytes=len(response.body), body_truncated=response.truncated,
                     content_length=response.headers.get("content-length"), vary=response.headers.get("vary"))


VIDEO_CHECKS_MAX = 5


def _check_videos(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, data: StructureData) -> None:
    """H29: how large the video files the pages play are. One GET each with the image check's small byte cap: the
    size is read from Content-Length, not by downloading the file. Only files on this site or its asset host, allowed
    by robots.txt, at most VIDEO_CHECKS_MAX (and never more than image_checks_max) of them, the site's own first.
    The files come from <video>/<source> (src or a lazy loader's data-src) and from a VideoObject's contentUrl (P1):
    a script that inserts the player on scroll leaves only that promise in the markup."""
    from .crawler import load_robots  # local import: crawler does not import this module
    from .media_sample import asset_hosts, own_image, size_video, video_sources

    shown_on: dict[str, list[str]] = {}
    found_by: dict[str, str] = {}
    for page in indexable_pages(result):
        for url, how in video_sources(page):
            shown_on.setdefault(url, []).append(page.url)
            found_by.setdefault(url, how)
    hosts = asset_hosts(result)
    ordered = sorted(shown_on, key=lambda url: not own_image(url, result, hosts))
    for url in ordered[:min(VIDEO_CHECKS_MAX, cfg.image_checks_max)]:
        entry: dict[str, Any] = {"url": url, "pages": list(dict.fromkeys(shown_on[url]))[:5], "found_by": found_by[url]}
        data.videos[url] = entry
        size_video(fetcher, result, cfg, data, entry, hosts, load_robots)
