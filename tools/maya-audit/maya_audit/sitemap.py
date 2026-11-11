from __future__ import annotations

import gzip
from io import BytesIO
from collections import deque

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from collections import Counter

from .fetcher import Fetcher
from .models import SitemapDoc, SkippedUrl
from .robots import RobotsPolicy
from .urls import normalize_url, same_origin
from . import clock as _clock

# Where a sitemap address came from when nobody named it: Maya asked for /sitemap.xml on its own.
GUESSED = "guess"
# The start of the note said when a sitemap index was read in part (DECISIONS 299): the discovered count is then partial.
PARTIAL = "sitemap index read in part"


def family(url: str) -> str:
    """The kind of sitemap file, its numbers left out and its folder kept: sitemap_products_1.xml and
    sitemap_products_2.xml?from=9 are one family, sitemap_pages_1.xml another, and /en/sitemap_products_1.xml (another
    language) a third."""
    import re
    from urllib.parse import urlsplit
    folder, _sep, name = urlsplit(url).path.lower().rpartition("/")
    return folder + "/" + re.sub(r"\d+", "#", name.split(".", 1)[0])


def spread(urls: list[str]) -> list[str]:
    """The files of a sitemap index in turn by family (products 1, pages 1, blogs 1, products 2, ...), so reading
    stops with every kind of page represented, not only the first file's."""
    groups: dict[str, list[str]] = {}
    for url in urls:
        groups.setdefault(family(url), []).append(url)
    # Within a family, an even spread too: the first file, the last, the middle, then the quarters (a catalog's
    # newest products are not only in its first file).
    groups = {key: _bisected(members) for key, members in groups.items()}
    out: list[str] = []
    rank = 0
    while len(out) < len(urls):
        for members in groups.values():
            if rank < len(members):
                out.append(members[rank])
        rank += 1
    return out


def _bisected(items: list[str]) -> list[str]:
    """First, last, then the midpoints of the gaps left, widest first: [1..8] -> 1, 8, 4, 6, 2, 5, 7, 3."""
    if len(items) <= 2:
        return list(items)
    order, taken = [0, len(items) - 1], {0, len(items) - 1}
    gaps = [(0, len(items) - 1)]
    while gaps:
        gaps.sort(key=lambda gap: gap[0] - gap[1])
        low, high = gaps.pop(0)
        if high - low < 2:
            continue
        mid = (low + high) // 2
        if mid not in taken:
            taken.add(mid)
            order.append(mid)
        gaps += [(low, mid), (mid, high)]
    return [items[i] for i in order]


def partial(notes) -> bool:
    """Whether a sitemap index was read in part (its note is among `notes`): the discovered count is then partial."""
    return any(str(note).startswith(PARTIAL) for note in notes or [])


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _locs(root, container: str) -> list[str]:
    return [loc for loc, _ in _entries(root, container)]


def _entries(root, container: str) -> list[tuple[str, str | None]]:
    out = []
    for element in root:
        if _local(element.tag) != container:
            continue
        loc = lastmod = None
        for child in element:
            if _local(child.tag) == "loc" and child.text:
                loc = child.text.strip()
            elif _local(child.tag) == "lastmod" and child.text:
                lastmod = child.text.strip()
        if loc:
            out.append((loc, lastmod))
    return out


def discover_sitemap_urls(
    fetcher: Fetcher,
    policy: RobotsPolicy,
    origin: str,
    product_token: str,
    max_docs: int,
    max_depth: int,
    max_bytes: int,
    skipped: list[SkippedUrl],
    lastmods: dict[str, str | None] | None = None,
    deadline: float | None = None,
    named_in: dict[str, str] | None = None,
    file_of: dict[str, str] | None = None,
    enough: int | None = None,
) -> tuple[list[SitemapDoc], list[str], list[str]]:
    """Fetch sitemaps named in robots.txt plus /sitemap.xml; same-origin only.

    `named_in`, when given, is filled with where each sitemap address came from: "robots.txt", "sitemap index <url>",
    or "guess" for the /sitemap.xml asked for without being named (IDX-5, DECISIONS 206).

    The third value is the notes about what was left out (A14, A15): sitemap files not read because of the time share or
    the file limit, sitemap files robots.txt names on another address, and listed addresses on another origin (http
    beside https, www beside the bare name). None of these is read, and none is dropped without a word.

    `enough` (DECISIONS 299): once this many addresses are known and every family of files in each sitemap index has
    had one file read (`spread`), the index's other files are not read; a note starting with `PARTIAL` says how many."""
    named_in = named_in if named_in is not None else {}
    sources: list[str] = []
    other_host_files: list[str] = []
    off_origin: list[str] = []
    off_origin_count = 0
    if policy.robots is not None:
        for value, _line in policy.robots.sitemaps:
            url = normalize_url(value, origin)
            if url and same_origin(url, origin):
                sources.append(url)
                named_in.setdefault(url, "robots.txt")
            elif url:
                other_host_files.append(url)
    default = f"{origin}/sitemap.xml"
    if default not in sources:
        sources.append(default)
        named_in.setdefault(default, GUESSED)

    queue = deque((url, max_depth) for url in sources)
    seen_docs: set[str] = set()
    docs: list[SitemapDoc] = []
    page_urls: dict[str, None] = {}

    notes: list[str] = []
    timed_out = False
    # Each file named in robots.txt (or guessed) is read; of an index's files, at least one of each family.
    families: dict[tuple[str, str], int] = {("source", url): 0 for url in sources}
    family_of: dict[str, tuple[str, str]] = {url: ("source", url) for url in sources}
    lazy_stop = False
    while queue and len(docs) < max_docs:
        if enough is not None and len(page_urls) >= enough and all(families.values()):
            lazy_stop = True
            break
        if deadline is not None and _clock.monotonic() > deadline:
            notes.append(f"sitemap discovery stopped after {len(docs)} document(s) with {len(queue)} still queued: "
                         "it had used its share of the crawl's time limit. Sitemap-based coverage is partial.")
            timed_out = True
            break
        url, depth = queue.popleft()
        if url in seen_docs or depth <= 0:
            continue
        seen_docs.add(url)
        if url in family_of:
            families[family_of[url]] += 1
        decision = policy.decide(product_token, url)
        if not decision.allowed:
            skipped.append(SkippedUrl(url, "sitemap_document", decision.to_dict()))
            continue

        response = fetcher.get(url, "sitemap", max_bytes + 1)
        final_url = url
        redirects = 0
        while (response.error is None and response.status is not None and 300 <= response.status < 400
               and response.headers.get("location") and redirects < 5):
            target = normalize_url(response.headers["location"], final_url)
            if not target or not same_origin(target, origin):
                break
            redirect_decision = policy.decide(product_token, target)
            if not redirect_decision.allowed:
                skipped.append(SkippedUrl(target, "sitemap_redirect", redirect_decision.to_dict()))
                break
            final_url = target
            seen_docs.add(target)
            response = fetcher.get(target, "sitemap", max_bytes + 1)
            redirects += 1
        if response.error or response.status is None or not (200 <= response.status < 300):
            docs.append(SitemapDoc(url, response.status, response.error or
                                   (f"redirect to {response.headers.get('location')} was not followed" if response.status and 300 <= response.status < 400 else None), None, 0))
            continue
        if response.truncated:
            docs.append(SitemapDoc(url, response.status, f"larger than {max_bytes} bytes; skipped", None, 0))
            continue
        body = response.body
        if final_url.lower().endswith(".gz") or body.startswith(b"\x1f\x8b"):
            try:
                with gzip.GzipFile(fileobj=BytesIO(body)) as stream:
                    body = stream.read(max_bytes + 1)
            except (OSError, EOFError) as exc:
                docs.append(SitemapDoc(url, response.status, f"gzip_error: {exc}", None, 0))
                continue
            if len(body) > max_bytes:
                docs.append(SitemapDoc(url, response.status, f"decompressed sitemap larger than {max_bytes} bytes; skipped", None, 0))
                continue
        try:
            root = ElementTree.fromstring(body)
        except (ElementTree.ParseError, DefusedXmlException) as exc:
            docs.append(SitemapDoc(url, response.status, f"parse_error: {exc}", None, 0))
            continue

        kind = _local(root.tag)
        if kind == "sitemapindex":
            nested = [normalize_url(loc, final_url) for loc in _locs(root, "sitemap")]
            other = [n for n in nested if n and not same_origin(n, origin)]
            off_origin_count += len(other)
            off_origin.extend(other[: max(0, 5 - len(off_origin))])
            nested = [n for n in nested if n and same_origin(n, origin)]
            for n in nested:
                if named_in.get(n) in (None, GUESSED):
                    named_in[n] = f"sitemap index {url}"
            docs.append(SitemapDoc(url, response.status, None, kind, len(nested)))
            nested = spread(list(dict.fromkeys(nested)))
            for n in nested:
                if n not in family_of:
                    family_of[n] = (url, family(n))
                    families.setdefault(family_of[n], 0)
            queue.extend((n, depth - 1) for n in nested)
        elif kind == "urlset":
            entries = [(normalize_url(loc, final_url), lastmod) for loc, lastmod in _entries(root, "url")]
            locs = [loc for loc, _ in entries if loc and same_origin(loc, origin)]
            other = [loc for loc, _ in entries if loc and not same_origin(loc, origin)]
            off_origin_count += len(other)
            off_origin.extend(other[: max(0, 5 - len(off_origin))])
            before = len(page_urls)
            for loc, lastmod in entries:
                if loc and same_origin(loc, origin):
                    page_urls.setdefault(loc, None)
                    if file_of is not None:  # the first sitemap file that listed it (the sitemap check's sample, DECISIONS 294)
                        file_of.setdefault(loc, url)
                    if lastmods is not None:
                        lastmods.setdefault(loc, lastmod)
            stamps = Counter(lastmod for loc, lastmod in entries if loc and same_origin(loc, origin) and lastmod)
            top, top_count = stamps.most_common(1)[0] if stamps else (None, 0)
            media = Counter(_local(child.tag) for element in root if _local(element.tag) == "url" for child in element
                            if _local(child.tag) in ("image", "video"))
            docs.append(SitemapDoc(url, response.status, None, kind, len(locs), sum(stamps.values()), len(stamps),
                                   top, top_count, media["image"], media["video"], len(page_urls) - before))
        else:
            docs.append(SitemapDoc(url, response.status, f"unexpected root element <{kind}>", None, 0))

    pending = sum(1 for url, depth in queue if url not in seen_docs and depth > 0)
    if pending and lazy_stop:
        listed = len({u for u, _depth in queue} | seen_docs)
        notes.append(f"{PARTIAL}: {len(page_urls)} addresses from {len(seen_docs)} of {listed} sitemap files, enough for "
                     f"the page cap and the sitemap check's sample ({enough}), with every kind of sitemap file read at "
                     f"least once; {pending} file(s) were not read, so the discovered count is partial.")
    elif pending and not timed_out and len(docs) >= max_docs:
        notes.append(f"sitemap discovery read its limit of {max_docs} sitemap file(s); {pending} more were not read. "
                     "Sitemap-based coverage is partial.")
    if other_host_files:
        notes.append(f"robots.txt names {len(other_host_files)} sitemap file(s) on another address, which were not read: "
                     f"{', '.join(other_host_files[:3])}.")
    if off_origin_count:
        notes.append(f"the sitemaps list {off_origin_count} address(es) on another origin (http beside https, or www beside "
                     f"the bare name), which were not taken as this site's pages: {', '.join(off_origin[:3])}.")
    return docs, list(page_urls), notes


def file_map(docs, urls, file_of: dict | None = None) -> dict[str, str]:
    """{address: the sitemap file that listed it first} (DECISIONS 337). From the crawl's own record when it has one;
    else from the files' `new_urls` in reading order (schema 1.32); else, for a report written before, only when the
    files' address counts add up exactly to the addresses known (no address listed twice), so the order says it. An
    empty map when none of these holds: the file is then not said, never guessed."""
    if file_of:
        return dict(file_of)
    urls = list(urls or [])
    rows = [d if isinstance(d, dict) else d.__dict__ for d in docs or []]
    sets = [r for r in rows if r.get("kind") == "urlset"]
    if sets and all(r.get("new_urls") is not None for r in sets):
        counts = [(r["url"], r["new_urls"]) for r in sets]
    elif sets and sum(int(r.get("urls_found") or 0) for r in sets) == len(urls):
        counts = [(r["url"], int(r.get("urls_found") or 0)) for r in sets]
    else:
        return {}
    if sum(n for _, n in counts) != len(urls):
        return {}
    out, at = {}, 0
    for file, n in counts:
        for url in urls[at:at + n]:
            out[url] = file
        at += n
    return out
