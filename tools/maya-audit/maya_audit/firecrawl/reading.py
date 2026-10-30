"""Which page a reader is asked for next, and what a site's sitemap adds when Maya's own crawler could not read it.

A reader used to take addresses first come, first served: on a large site that meant the homepage and then the first
fifty links, often one category of one shop. Maya's own crawler already spreads a capped crawl (maya_audit.scratchpad:
the start page and key pages, then navigation links, then the section of the site read least so far, then
sitemap-only addresses, with page 2, 3, ... of a list last). `ReadingQueue` gives a reader the same order, in memory.

Sitemap discovery through a reader follows the shape of OpenSEO's discovery (sitemaps named in robots.txt, else
/sitemap.xml; a bounded number of documents; a cap on addresses taken). It was read from
https://github.com/every-app/open-seo at commit deb44913c2e345ec29ce6fb066a94ca428ebc681 (MIT, Ben Senescu; notice in
licenses/OPENSEO-MIT-LICENSE.txt). No OpenSEO code is copied here: the limits and the parsing are Maya's own.
"""

from __future__ import annotations

import html
import re
from typing import Any, Callable

from ..urls import is_pagination, normalize_url, section_key
from .settings import SITEMAP_MIN_PAGE_CAP as SITEMAP_MIN_CAP  # counted in the audit's stated maximum
from .settings import SITEMAP_REQUESTS as SITEMAP_DOCUMENTS

# The crawler's own classes (maya_audit.scratchpad.PRIORITY): lower is sooner.
_CLASS = {"redirect": 0, "start": 1, "key_page": 1, "alternate": 1, "ranking_page": 1.5, "link": 3, "rendered_link": 3, "sitemap": 4}
_NAV, _PAGINATION = 2, 5
# A sitemap document costs a request like a page does. At most this many are asked for, and only when the audit's
# page cap is at least SITEMAP_MIN_CAP, so a small audit spends its requests on pages.
# Addresses taken from sitemaps: enough to choose from, bounded (OpenSEO: maxPages * 20, between 500 and 50,000).
SITEMAP_URLS_PER_CAP = 20
_LOC = re.compile(r"<loc[^>]*>\s*([^<\s][^<]*?)\s*</loc>", re.IGNORECASE)
_ESCAPED_LOC = re.compile(r"&lt;loc&gt;\s*(.*?)\s*&lt;/loc&gt;", re.IGNORECASE | re.DOTALL)


class ReadingQueue:
    """Addresses waiting to be read, in the order a capped audit should take them.

    `spread` False is the old order (first come, first served), kept so the difference can be measured."""

    def __init__(self, spread: bool = True) -> None:
        self.spread = spread
        self._items: dict[str, dict[str, Any]] = {}
        self._taken: dict[str, int] = {}
        self._seq = 0

    def add(self, url: str, via: str, depth: int | None, nav: bool = False) -> None:
        url = normalize_url(url) or url
        priority = _NAV if nav and via in ("link", "rendered_link") else _CLASS.get(via, 3)
        if via not in ("start", "key_page", "redirect") and is_pagination(url):
            priority = _PAGINATION
        held = self._items.get(url)
        if held is not None:
            if priority < held["priority"]:  # a link first seen in the body, then found in the navigation
                held.update(priority=priority, via=via)
            return
        self._seq += 1
        self._items[url] = {"url": url, "via": via, "depth": depth, "priority": priority, "seq": self._seq, "section": section_key(url)}

    def __len__(self) -> int:
        return len(self._items)

    def pop(self) -> tuple[str, str, int | None] | None:
        if not self._items:
            return None
        if not self.spread:
            item = min(self._items.values(), key=lambda i: i["seq"])
        else:
            # Start, key pages and redirect targets strictly first. From navigation links down, the section of the site
            # read least so far goes first, then the class, then the order found.
            item = min(self._items.values(), key=lambda i: (
                i["priority"] >= _PAGINATION, min(i["priority"], _CLASS["link"]),
                0 if i["priority"] < _NAV else self._taken.get(i["section"], 0), i["priority"], i["seq"]))
        del self._items[item["url"]]
        return item["url"], item["via"], item["depth"]

    def taken(self, url: str) -> None:
        """This address was asked for: its section counts as sampled once more."""
        section = section_key(url)
        self._taken[section] = self._taken.get(section, 0) + 1

    def waiting(self) -> list[str]:
        return [item["url"] for item in sorted(self._items.values(), key=lambda i: i["seq"])]

    def sections_read(self) -> int:
        return len(self._taken)


def sitemap_locations(text: str) -> tuple[list[str], bool]:
    """(addresses in a sitemap document, whether it is an index of other sitemaps). A reader may hand the XML back as
    it is, or as a page that shows it with the tags escaped; both are read."""
    found = _LOC.findall(text) or [html.unescape(value) for value in _ESCAPED_LOC.findall(text)]
    index = bool(re.search(r"<\s*sitemapindex\b|&lt;\s*sitemapindex\b", text, re.IGNORECASE))
    return [html.unescape(value).strip() for value in found if value.strip()], index


def discover_through_reader(scrape: Callable[[str], Any], origin: str, declared: list[str], allowed: Callable[[str], bool],
                            in_scope: Callable[[str], bool], page_cap: int) -> dict[str, Any]:
    """Ask the reader for the site's sitemap when Maya's own crawler could not read one. Bounded: at most
    SITEMAP_DOCUMENTS documents, the audited site's own addresses only, robots.txt obeyed for the sitemap itself.

    Returns what was asked and found; `urls` are page addresses to consider, never to trust blindly."""
    sources = [u for u in dict.fromkeys([*declared, f"{origin}/sitemap.xml"]) if in_scope(u)]
    out: dict[str, Any] = {"documents": [], "urls": [], "note": None}
    limit = max(500, min(page_cap * SITEMAP_URLS_PER_CAP, 50_000))
    queue = list(sources)
    while queue and len(out["documents"]) < SITEMAP_DOCUMENTS:
        url = queue.pop(0)
        if not allowed(url):
            out["documents"].append({"url": url, "outcome": "disallowed_by_robots"})
            continue
        fetched = scrape(url)  # the caller's guarded request: page cap, credits, deadline, stop, pace
        text = fetched.html or ""
        if fetched.status is not None and fetched.status >= 400 or not text.strip():
            out["documents"].append({"url": url, "outcome": "not_found" if fetched.status in (404, 410) else "unreadable", "status": fetched.status})
            continue
        locations, is_index = sitemap_locations(text)
        mine = [u for u in (normalize_url(value, origin) for value in locations) if u and in_scope(u)]
        out["documents"].append({"url": url, "outcome": "index" if is_index else "read", "status": fetched.status, "addresses": len(mine),
                                 "from_cache": bool(fetched.cached)})
        if is_index:
            queue = [u for u in mine if u not in queue][:SITEMAP_DOCUMENTS] + queue
        else:
            out["urls"] += [u for u in mine if u not in out["urls"]][: limit - len(out["urls"])]
    if queue and len(out["documents"]) >= SITEMAP_DOCUMENTS:
        out["note"] = f"{len(queue)} more sitemap document(s) were not asked for (at most {SITEMAP_DOCUMENTS} per audit through a reader)"
    return out
