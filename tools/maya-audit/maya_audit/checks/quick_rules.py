"""Quick checks from the 165-item checklist mapping (DECISIONS 304): ten rules over data the crawl already reads.

Each rule makes an ordinary finding in the check it belongs to; none sends a request. They run where that check runs
(`extend`, called by the access, index and structure runners, so a page reader's content view gets them too) and on a
saved report offline (`maya_audit.reassess_rules`), where a rule whose data the report does not keep says so instead.

| Checklist | Rule id | Check | What it reports |
|---|---|---|---|
| SEO-061 | idx6.alias_links | IDX-6 | internal links to an address whose canonical is another page |
| SEO-099 | str15.empty_collections | STR-15 | indexable collections/categories listing no product or almost none |
| (c) | tseo1.url_decomposed | TSEO-1 | addresses with a combining character (i + U+0307 for "İ") |
| SEO-031 | acc3.robots_noindex | ACC-3 | pages with noindex that robots.txt blocks a search crawler from reading |
| SEO-046 | idx7.pagination_unlinked | IDX-7 | list pages with a next page that no <a href> on them links to |
| SEO-093 | idx7.product_no_category | IDX-7 | product pages with no breadcrumb or link to a category in their content |
| SEO-036 | idx5.no_image_sitemap, idx5.no_video_sitemap | IDX-5 | no image/video sitemap entries on a site with many |
| SEO-067 | tseo1.url_slug_unclear | TSEO-1 | slugs that are only an id, over 100 characters, or hold spaces/symbols |
| SEO-078 | str3.article_no_author | STR-3 | article pages that name no author (byline, rel/itemprop, markup) |
| SEO-097 | str3.product_no_identifier | STR-3 | product pages whose Product markup has no GTIN and no MPN |

Page types, aliases and products listed come from the page grouping (`maya_audit.page_groups`, DECISIONS 297/298), run
on the pages these checks see. The thresholds are agent defaults, listed in docs/LAUNCH-GATE.md (LG-102).
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from types import SimpleNamespace
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit

from ..directives import page_directives
from ..findings import Finding, Severity, scope_for
from ..models import Confidence
from ..page_groups import is_locale
from ..page_words import ARTICLE_FOLDERS, CATEGORY_WORDS, fold

GOOGLE = "Google AI Overviews / AI Mode"
COPILOT = "Microsoft Copilot (Bing index)"
DOCUMENTED = "Documented (Google Search Central)"

# SEO-099: a collection listing this many products or fewer is "near-empty"; the site needs this many product pages
# for its collections to be judged at all.
NEAR_EMPTY_MAX = 2
MIN_PRODUCT_PAGES = 3
# SEO-093: categories the site must have before a product's missing link to one is a finding.
MIN_CATEGORY_PAGES = 3
# SEO-036: "many" images (different image addresses outside the header, menu and footer of the pages read) and videos
# (pages read that show one) before a missing image or video sitemap is a finding.
MANY_IMAGES = 200
MANY_VIDEO_PAGES = 10
# SEO-067: a slug longer than this (decoded) is very long.
SLUG_MAX = 100
# A slug that is only an id: digits, hex, a uuid, or digits with no run of three letters ("p-12345").
_ID_ONLY = re.compile(r"^(?:\d+|[0-9a-f]{8,}|[0-9a-f-]{32,36})$", re.IGNORECASE)
_LETTERS3 = re.compile(r"[^\W\d_]{3,}")
_PAGE_QUERY = ("page", "p", "sayfa", "pg")
_PAGE_PATH = re.compile(r"/(?:page|sayfa|seite|pagina)/(\d+)/?$", re.IGNORECASE)
SEARCH_CRAWLERS = ("Googlebot", "Bingbot")
VIDEO_HOSTS = re.compile(r"(?:youtube(?:-nocookie)?\.com/embed|player\.vimeo\.com|fast\.wistia\.net|youtu\.be/)", re.IGNORECASE)

ALIAS_LINKS_EXPECTED = "internal links point to each page's canonical address"
ALIAS_LINKS_FIX = ("Change the links to name the canonical address. When a template builds them (on Shopify, product "
                   "links inside a collection, /collections/<c>/products/<p>), change it there: remove "
                   "\"within: collection\" from the product card's link so it points to /products/<p>.")
EMPTY_COLLECTIONS_EXPECTED = "every indexable collection or category page lists products"
EMPTY_COLLECTIONS_FIX = ("Fill these collections or merge each into a related one with a 301 redirect; while one is "
                         "empty, add noindex to it and take it out of the menu and the sitemap.")
EMPTY_COLLECTIONS_NOTE = ("Estimated: the products are counted from the links in each page's own HTML (one per product). "
                          "A list that loads its products with JavaScript shows none here: confirm in a browser.")
DECOMPOSED_EXPECTED = "every address is written with composed characters (Unicode NFC) or plain letters"
DECOMPOSED_FIX = ("Change these address names (the handle: the name of a product or page at the end of its address) "
                  "to their composed or plain form (the evidence gives each one, for example etbi̇s -> etbis), redirect "
                  "each old address to the new one with a 301, and update the links and the sitemap. The combining dot "
                  "usually comes from lowercasing a capital İ in the tool that wrote the address name.")
ROBOTS_NOINDEX_EXPECTED = "a page meant to leave the index can be crawled, so its noindex is seen"
ROBOTS_NOINDEX_FIX = ("Choose one per page. To take it out of the index, allow it in robots.txt so crawlers can read the "
                      "noindex, and block it only after it has dropped out. To keep crawlers out, remove the noindex "
                      "and rely on robots.txt, knowing the address can still be indexed from links to it.")
PAGINATION_EXPECTED = "each page of a list links to the next one with an <a href> link"
PAGINATION_FIX = ("Add plain <a href> links to the next pages (numbered pages or a \"next\" link) in the list's HTML. "
                  "A \"load more\" button or infinite scroll can stay for visitors, with the links beside it.")
PRODUCT_CATEGORY_EXPECTED = "each product page links back to its category"
PRODUCT_CATEGORY_FIX = ("Add a breadcrumb trail with links (Home > Category > Product), or a link to the product's main "
                        "category, to the product template, and mark the trail up with BreadcrumbList.")
PRODUCT_CATEGORY_NOTE = ("Estimated: page types are worked out from addresses, links and markup (page grouping), and a "
                         "link counts when it sits in the page's content or in a breadcrumb trail, not in the menu "
                         "or the footer.")
IMAGE_SITEMAP_EXPECTED = "a site with many images lists them in its sitemap (<image:image>)"
IMAGE_SITEMAP_FIX = ("Add image entries (<image:image> with the image address) for each page's main images to the "
                     "sitemap, or a separate image sitemap named in robots.txt.")
VIDEO_SITEMAP_EXPECTED = "a site with many videos lists them in a video sitemap (<video:video>)"
VIDEO_SITEMAP_FIX = ("Add video entries (<video:video> with a title, description, thumbnail and the video's address) "
                     "to the sitemap, or a separate video sitemap named in robots.txt.")
SLUG_EXPECTED = "page addresses are short and made of readable words"
SLUG_FIX = ("Give these pages short slugs made of words (for example /products/linen-shirt-white), redirect each old "
            "address to the new one with a 301 and update the links.")
AUTHOR_EXPECTED = "each article names its author, on the page and in its markup"
AUTHOR_FIX = ("Show the author's name on each article, linked to an author page, and add author (a Person with name "
              "and url) to the article's Article or BlogPosting markup.")
AUTHOR_NOTE = ("Estimated: an author counts when the page has a byline element (a class or id such as author or "
               "byline), rel=author, itemprop=author, a meta author tag or an author in its structured data.")
AUTHOR_SAVED_NOTE = ("Read from a saved report, which keeps the meta tags, the structured data and the page's saved "
                     "JSON-LD but no byline element: confirm on the page.")
IDENTIFIER_EXPECTED = "Product markup carries a GTIN or an MPN, and a brand"
IDENTIFIER_FIX = ("Add the product's GTIN (its barcode: gtin13 for an EAN) or, when it has none, its MPN, and the brand, "
                  "to the Product markup. On Shopify, fill each variant's barcode field so the theme writes it.")


# -- the pages and their grouping ------------------------------------------------------------------------------------

def _read(pages) -> list:
    from ..structure_data import readable_html
    return [p for p in pages if p.analysis and readable_html(p) and getattr(p, "content_checks_eligible", True) is not False]


def grouping_of(result) -> dict[str, dict]:
    """{url: grouping record} for the pages `result` holds, from `page_groups.annotate` on a copy of its frame (the
    pages' own `grouping` is set as the final step sets it). {} when nothing can be grouped."""
    from ..page_groups import annotate
    view = SimpleNamespace(pages=list(result.pages), start_url=getattr(result, "start_url", "") or "",
                           origin=getattr(result, "origin", None), discovered_urls=getattr(result, "discovered_urls", None) or [],
                           sitemap_urls=getattr(result, "sitemap_urls", None) or [], page_grouping=None)
    if not _read(view.pages):
        return {}
    summary = annotate(view)
    out = {p.url: p.grouping for p in view.pages if isinstance(p.grouping, dict) and "importance" in p.grouping}
    out.update({u: g for u, g in (summary.get("canonical_pages") or {}).items() if isinstance(g, dict)})
    return out


def _segments(url: str) -> list[str]:
    return [fold(unquote(s)) for s in urlsplit(url).path.split("/") if s]


def _tier(urls, key_urls) -> int:
    return 0 if any(u in key_urls for u in urls) else 2


def _bare(url: str) -> str:
    return (url or "").split("#", 1)[0]


def _in_content(edge: dict) -> bool:
    """A link outside the menu and footer. A link record merges every link to one target, so a target the menu also
    links is the menu's (a theme with a desktop and a mobile menu links each collection twice from them)."""
    return not edge.get("nav") and not edge.get("footer")


def _path(url: str) -> str:
    """The address without query and fragment, decoded, without a trailing slash: one list whatever its sort order."""
    parts = urlsplit(url)
    return f"{parts.netloc.lower()}{unquote(parts.path).rstrip('/')}"


# -- SEO-061: links to an alias --------------------------------------------------------------------------------------

def alias_links(read, groups: dict, key_urls=frozenset()) -> list[Finding]:
    # A canonical that differs only in how it is percent-encoded (%CC%87 / %cc%87) names the page itself.
    aliases = {u: g["canonical"] for u, g in groups.items() if g.get("canonical") and unquote(g["canonical"]) != unquote(u)}
    if not aliases:
        return []
    links, pages, targets = 0, [], defaultdict(set)
    for p in read:
        found = 0
        for edge in p.outlinks or []:
            target = _bare(edge.get("target") or "")
            if target in aliases and target != p.url and aliases[target] != p.url:
                found += int(edge.get("links") or 1)
                targets[target].add(p.url)
        if found:
            links += found
            pages.append(p.url)
    if not pages:
        return []
    patterns = Counter((groups.get(t) or {}).get("url_pattern") or "/" for t in targets)
    top = sorted(targets, key=lambda t: (-len(targets[t]), t))[:20]
    return [Finding("IDX-6", f"{links} internal link(s) on {len(pages)} page(s) point to an address whose canonical is another page",
        Severity.S4, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(pages),
        {"link_count": links, "page_count": len(pages), "alias_targets": len(targets),
         "targets": [{"url": t, "canonical": aliases[t], "linked_from_pages": len(targets[t])} for t in top],
         "target_patterns": dict(patterns.most_common(10)),
         "rule": "a link (menu, content or footer) to a page read whose canonical names another address (page grouping's aliases)"},
        ALIAS_LINKS_EXPECTED, ALIAS_LINKS_FIX, importance_tier=_tier(pages, key_urls))]


# -- SEO-099: empty or near-empty collections ------------------------------------------------------------------------

def _is_category_url(url: str) -> bool:
    segs = _segments(url)
    return bool(set(segs) & CATEGORY_WORDS)


def empty_collections(read, groups: dict, indexable: set[str], key_urls=frozenset()) -> list[Finding]:
    types = {u: g.get("page_type") for u, g in groups.items()}
    if sum(1 for t in types.values() if t == "product") < MIN_PRODUCT_PAGES:
        return []
    rows = []
    for p in read:
        g = groups.get(p.url) or {}
        segs = _segments(p.url)
        body = segs[1:] if segs and is_locale(segs[0]) else segs  # a leading language folder (/en/...) only
        if (g.get("page_type") != "category" or p.url not in indexable or urlsplit(p.url).query
                or (body and body[0] in ARTICLE_FOLDERS | {"blogs"}) or (body and body[-1] in CATEGORY_WORDS)):
            continue  # a blog's list, or the index of all collections (/collections): not a product list
        listed = int((g.get("tie_break") or {}).get("products_listed") or 0)
        if listed > NEAR_EMPTY_MAX:
            continue
        # A parent category that lists its subcategories (2+ in its content) is a hub, not an empty list.
        own = _path(p.url)
        subs = {_path(t) for e in p.outlinks or [] if _in_content(e)
                and (t := _bare(e.get("target") or "")) and _path(t) != own and not _is_product_in_list(t)
                and (types.get(t) == "category" or _is_category_url(t))}
        if len(subs) >= 2:
            continue
        rows.append({"url": p.url, "products_listed": listed, "empty": listed == 0})
    if not rows:
        return []
    urls = [r["url"] for r in rows]
    empty = sum(1 for r in rows if r["empty"])
    return [Finding("STR-15", f"{len(urls)} indexable collection or category page(s) list no product or almost none",
        Severity.S4, Confidence.ESTIMATED, "Documented (Google: soft 404s, thin pages)", [GOOGLE, COPILOT], scope_for(urls),
        {"pages": rows[:40], "empty": empty, "near_empty": len(rows) - empty, "near_empty_max": NEAR_EMPTY_MAX,
         "rule": f"an indexable category page (page grouping) listing {NEAR_EMPTY_MAX} products or fewer in its content, "
                 "and not a hub listing 2+ subcategories"},
        EMPTY_COLLECTIONS_EXPECTED, EMPTY_COLLECTIONS_FIX, notes=[EMPTY_COLLECTIONS_NOTE],
        importance_tier=_tier(urls, key_urls))]


# -- decomposed characters in addresses ------------------------------------------------------------------------------

def composed(text: str) -> str:
    """`text` in NFC, with the dot that lowercasing "İ" leaves after an "i" (i + U+0307) taken out."""
    return unicodedata.normalize("NFC", text).replace("i̇", "i").replace("İ", "İ")


def decomposed_addresses(known: list[str], read_urls: set[str], sitemap: set[str], key_urls=frozenset()) -> list[Finding]:
    rows = {}
    for url in known:
        if not isinstance(url, str) or url in rows:
            continue
        path = unquote(urlsplit(url).path)
        marks = sorted({f"U+{ord(c):04X}" for c in path if unicodedata.combining(c)})
        if marks:
            fixed = urlsplit(url)._replace(path=quote(composed(path), safe="/:@!$&'()*+,;=-._~")).geturl()
            rows[url] = {"url": url, "characters": marks, "fixed": fixed, "read": url in read_urls, "in_sitemap": url in sitemap}
    if not rows:
        return []
    urls = list(rows)
    return [Finding("TSEO-1", f"{len(urls)} address(es) contain a decomposed character (a letter followed by a combining mark)",
        Severity.S4, Confidence.VERIFIED, "Documented (Unicode normalization, NFC)", [GOOGLE, COPILOT], scope_for(urls),
        {"addresses": list(rows.values())[:40], "read": sum(r["read"] for r in rows.values()),
         "in_sitemap": sum(r["in_sitemap"] for r in rows.values()),
         "characters": dict(Counter(c for r in rows.values() for c in r["characters"]).most_common()),
         "rule": "the decoded path holds a combining character (Unicode category M), such as U+0307 after an i"},
        DECOMPOSED_EXPECTED, DECOMPOSED_FIX, importance_tier=_tier(urls, key_urls))]


# -- SEO-031: noindex behind robots.txt ------------------------------------------------------------------------------

def robots_noindex(read, policy, key_urls=frozenset(), user_agent: str = "") -> list[Finding]:
    if policy is None:
        return []
    rows = []
    for p in read:
        if not (p.status and 200 <= p.status < 300):
            continue
        noindex = [d["raw"] for d in page_directives(p) if d["directive"] in ("noindex", "none") and d["scope"] in ("*", "googlebot", "bingbot")]
        if not noindex:
            continue
        blocked = []
        for bot in SEARCH_CRAWLERS:
            decision = policy.decide(bot, p.url)
            if not decision.allowed:
                blocked.append({"bot": bot, "robots": decision.reason})
        if blocked:
            rows.append({"url": p.url, "noindex": noindex[0], "blocked_for": blocked})
    if not rows:
        return []
    urls = [r["url"] for r in rows]
    return [Finding("ACC-3", f"{len(urls)} page(s) carry noindex but robots.txt blocks search crawlers from reading it",
        Severity.S4, Confidence.VERIFIED, "Documented (Google: robots.txt and noindex)", [GOOGLE, COPILOT], scope_for(urls),
        {"pages": rows[:40], "rule": "a page Maya read with noindex (all crawlers, Googlebot or Bingbot) that robots.txt "
                                     "disallows for Googlebot or Bingbot, which therefore never see the noindex",
         "reproduce": [f"curl -s {r['url']} | grep -i robots" for r in rows[:3]]},
        ROBOTS_NOINDEX_EXPECTED, ROBOTS_NOINDEX_FIX, importance_tier=_tier(urls, key_urls))]


# -- SEO-046: next pages not linked ----------------------------------------------------------------------------------

def page_number(url: str) -> int | None:
    parts = urlsplit(url)
    for key, value in parse_qsl(parts.query):
        if key.lower() in _PAGE_QUERY and value.isdigit():
            return int(value)
    found = _PAGE_PATH.search(parts.path)
    return int(found.group(1)) if found else None


def _list_key(url: str) -> tuple[str, tuple]:
    """The list a page-numbered address belongs to: its path without /page/N, and its query without the page number."""
    parts = urlsplit(_bare(url))
    path = _PAGE_PATH.sub("", parts.path).rstrip("/") or "/"
    query = tuple(sorted((k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _PAGE_QUERY))
    return f"{parts.scheme}://{parts.netloc}{path}", query


def pagination_unlinked(read, groups: dict, known: list[str], key_urls=frozenset()) -> list[Finding]:
    second: dict[tuple, str] = {}
    for url in known:
        if isinstance(url, str) and page_number(url) == 2:
            second.setdefault(_list_key(url), url)
    rows = []
    for p in read:
        g = groups.get(p.url) or {}
        targets = {_bare(e.get("target") or "") for e in p.outlinks or []}
        own = page_number(p.url) or 1
        nxt = ((p.analysis or {}).get("pagination_links") or {}).get("next")
        if nxt:
            nxt = _bare(urljoin(p.url, nxt))
            if nxt not in targets and nxt != p.url:
                rows.append({"url": p.url, "next": nxt, "source": "<link rel=\"next\">"})
            continue
        if own != 1 or g.get("page_type") != "category":
            continue
        later = second.get(_list_key(p.url))
        if later and later not in targets and not any(page_number(t) and _list_key(t) == _list_key(p.url) for t in targets):
            rows.append({"url": p.url, "next": later, "source": "a page-2 address the audit found elsewhere"})
    if not rows:
        return []
    urls = [r["url"] for r in rows]
    by_rel = all(r["source"].startswith("<link") for r in rows)
    return [Finding("IDX-7", f"{len(urls)} list page(s) do not link to their next page with an <a href> link",
        Severity.S4, Confidence.VERIFIED if by_rel else Confidence.ESTIMATED, "Documented (Google: pagination best practices)",
        [GOOGLE, COPILOT], scope_for(urls),
        {"pages": rows[:40], "rule": "the page's <link rel=\"next\">, or a page-2 address of the same list found elsewhere, "
                                     "is not the target of any link on the page"},
        PAGINATION_EXPECTED, PAGINATION_FIX, importance_tier=_tier(urls, key_urls))]


# -- SEO-093: product pages without a link to a category -------------------------------------------------------------

def product_no_category(read, groups: dict, indexable: set[str], key_urls=frozenset()) -> list[Finding]:
    types = {u: g.get("page_type") for u, g in groups.items()}
    if sum(1 for t in types.values() if t == "category") < MIN_CATEGORY_PAGES:
        return []
    by_product: dict[str, list] = defaultdict(list)
    for p in read:
        g = groups.get(p.url) or {}
        if g.get("page_type") == "product":
            by_product[g.get("canonical") or p.url].append(p)
    missing = []
    for key, copies in by_product.items():
        if not any(p.url in indexable for p in copies) and key not in groups:
            continue

        def linked(p) -> bool:
            if any((b.get("links") or 0) >= 2 and not b.get("in_chrome") for b in (p.analysis or {}).get("breadcrumbs") or []):
                return True
            return any(not e.get("nav") and not e.get("footer") and _bare(e.get("target") or "") != p.url
                       and (types.get(_bare(e.get("target") or "")) == "category" or _is_category_url(e.get("target") or ""))
                       and not _is_product_in_list(e.get("target") or "")
                       for e in p.outlinks or [])
        if not any(linked(p) for p in copies):
            missing.append(next((p.url for p in copies if p.url == key), copies[0].url))
    if not missing:
        return []
    return [Finding("IDX-7", f"{len(missing)} product page(s) have no breadcrumb or link to a category in their content",
        Severity.S4, Confidence.ESTIMATED, "Documented (Google: breadcrumbs and internal links)", [GOOGLE, COPILOT],
        scope_for(missing),
        {"products": len(by_product), "without_category_link": len(missing),
         "rule": "no breadcrumb trail with 2+ links and no link outside the menu and footer to a category page"},
        PRODUCT_CATEGORY_EXPECTED, PRODUCT_CATEGORY_FIX, notes=[PRODUCT_CATEGORY_NOTE],
        importance_tier=_tier(missing, key_urls))]


def _is_product_in_list(url: str) -> bool:
    from .structure import nested_product
    return bool(nested_product(_segments(url)))


# -- SEO-036: image and video sitemaps -------------------------------------------------------------------------------

def media_sitemaps(read, sitemap_docs, key_urls=frozenset()) -> tuple[list[Finding], str | None]:
    """(findings, why not assessed). Not assessed when no urlset was read, or the sitemap records hold no media counts
    (a report saved before schema 1.24)."""
    docs = [d if isinstance(d, dict) else vars(d) for d in sitemap_docs or []]
    urlsets = [d for d in docs if d.get("kind") == "urlset" and not d.get("error")]
    if not urlsets:
        return [], "no sitemap urlset was read"
    if any("image_entries" not in d for d in urlsets):
        return [], "the sitemap records hold no image or video counts (a report saved before schema 1.24)"
    images = {img.get("src") for p in read for img in (p.analysis or {}).get("images") or []
              if img.get("src") and not img.get("in_chrome")}
    video_pages = [p.url for p in read if any(m.get("tag") == "video" for m in (p.analysis or {}).get("media") or [])
                   or any(VIDEO_HOSTS.search(str(f.get("src") or "")) for f in (p.analysis or {}).get("iframes") or []
                          if isinstance(f, dict))]
    out = []
    if len(images) >= MANY_IMAGES and not sum(int(d.get("image_entries") or 0) for d in urlsets):
        out.append(Finding("IDX-5", f"The sitemap lists no images although the pages read show {len(images)} different images",
            Severity.S4, Confidence.VERIFIED, "Documented (Google: image sitemaps)", [GOOGLE], scope_for([d["url"] for d in urlsets]),
            {"images": len(images), "sitemap_files": len(urlsets), "many": MANY_IMAGES,
             "rule": f"{MANY_IMAGES}+ different image addresses outside the header, menu and footer, and no <image:image> in any sitemap file read"},
            IMAGE_SITEMAP_EXPECTED, IMAGE_SITEMAP_FIX))
    if len(video_pages) >= MANY_VIDEO_PAGES and not sum(int(d.get("video_entries") or 0) for d in urlsets):
        out.append(Finding("IDX-5", f"The sitemap lists no videos although {len(video_pages)} pages read show a video",
            Severity.S4, Confidence.VERIFIED, "Documented (Google: video sitemaps)", [GOOGLE], scope_for(video_pages),
            {"video_pages": len(video_pages), "sitemap_files": len(urlsets), "many": MANY_VIDEO_PAGES,
             "rule": f"{MANY_VIDEO_PAGES}+ pages read with a video, and no <video:video> in any sitemap file read"},
            VIDEO_SITEMAP_EXPECTED, VIDEO_SITEMAP_FIX, importance_tier=_tier(video_pages, key_urls)))
    return out, None


# -- SEO-067: unclear slugs ------------------------------------------------------------------------------------------

def slug_problem(url: str) -> str | None:
    segments = [s for s in urlsplit(url).path.split("/") if s]
    if not segments:
        return None
    slug = unicodedata.normalize("NFC", unquote(segments[-1]))
    stem = slug.rsplit(".", 1)[0] if re.search(r"\.(?:html?|php|aspx?)$", slug, re.IGNORECASE) else slug
    if len(stem) > SLUG_MAX:
        return "over 100 characters"
    if any(not (c.isalnum() or c in "-_.~") and not unicodedata.combining(c) for c in stem):
        return "spaces or symbols"
    if _ID_ONLY.match(stem) or (any(c.isdigit() for c in stem) and not _LETTERS3.search(stem)):
        return "an id only"
    return None


def unclear_slugs(read, groups: dict, indexable: set[str], key_urls=frozenset()) -> list[Finding]:
    rows = {}
    for p in read:
        g = groups.get(p.url) or {}
        if p.url not in indexable or g.get("page_type") in ("home", "utility") or page_number(p.url):
            continue
        why = slug_problem(p.url)
        if why:
            rows[p.url] = why
    if not rows:
        return []
    urls = list(rows)
    return [Finding("TSEO-1", f"{len(urls)} page address(es) have an unclear slug (an id only, over 100 characters, or spaces and symbols)",
        Severity.S4, Confidence.VERIFIED, "Documented (Google: URL structure)", [GOOGLE, COPILOT], scope_for(urls),
        {"pages": [{"url": u, "why": rows[u]} for u in urls[:40]], "by_reason": dict(Counter(rows.values()).most_common()),
         "rule": "the last path segment, decoded: over 100 characters; or a space or symbol (not a letter, digit, - _ . ~); "
                 "or only an id (digits, hex, a uuid, or digits with no run of 3 letters)"},
        SLUG_EXPECTED, SLUG_FIX, importance_tier=_tier(urls, key_urls))]


# -- SEO-078: author on article pages --------------------------------------------------------------------------------

def author_signals(analysis: dict) -> list[str]:
    signals = set(analysis.get("author_signals") or [])
    if any(m.get("name") == "author" and m.get("content") for m in analysis.get("meta") or []):
        signals.add("meta author")
    if "Person" in ((analysis.get("structured_data") or {}).get("types") or []):
        signals.add("Person markup")
    return sorted(signals)


def article_no_author(read, groups: dict, indexable: set[str], key_urls=frozenset(), saved: bool = False) -> list[Finding]:
    articles = [p for p in read if (groups.get(p.url) or {}).get("page_type") == "blog_article" and p.url in indexable]
    missing = [p.url for p in articles if not author_signals(p.analysis or {})]
    if not missing:
        return []
    return [Finding("STR-3", f"{len(missing)} article page(s) name no author (no byline or author markup)",
        Severity.S4, Confidence.ESTIMATED, "Documented (Google: author markup best practices)", [GOOGLE, COPILOT],
        scope_for(missing),
        {"articles": len(articles), "without_author": len(missing),
         "rule": "an indexable article page (page grouping) with no byline element, rel=author, itemprop=author, meta "
                 "author, author in its structured data or Person markup"},
        AUTHOR_EXPECTED, AUTHOR_FIX, notes=[AUTHOR_NOTE, AUTHOR_SAVED_NOTE] if saved else [AUTHOR_NOTE],
        importance_tier=_tier(missing, key_urls))]


# -- SEO-097: product identifiers ------------------------------------------------------------------------------------

def _has_identifier(product: dict) -> bool:
    return bool(product.get("gtin") or product.get("mpn") or product.get("variant_identifiers")
                or any(o.get("gtin") or o.get("mpn") for o in product.get("offers") or []))


def product_no_identifier(read, groups: dict, key_urls=frozenset()) -> tuple[list[Finding], int]:
    """(findings, product pages with Product fields recorded)."""
    seen, rows, recorded = set(), [], 0
    for p in read:
        g = groups.get(p.url) or {}
        products = [x for x in ((p.analysis or {}).get("structured_data") or {}).get("products") or [] if not x.get("in_list")]
        if g.get("page_type") != "product" or not products:
            continue
        key = g.get("canonical") or p.url
        if key in seen:
            continue
        seen.add(key)
        recorded += 1
        if not any(_has_identifier(x) for x in products):
            first = products[0]
            rows.append({"url": p.url, "sku": first.get("sku"), "brand": first.get("brand"),
                         "offers": len(first.get("offers") or []), "has_variant": first.get("has_variant")})
    if not rows:
        return [], recorded
    urls = [r["url"] for r in rows]
    return [Finding("STR-3", f"{len(urls)} product page(s) have Product markup without a GTIN or MPN",
        Severity.S4, Confidence.VERIFIED, "Documented (Google: merchant listing structured data)", [GOOGLE], scope_for(urls),
        {"pages": rows[:40], "product_pages_with_markup": recorded, "without_brand": sum(1 for r in rows if not r["brand"]),
         "rule": "no gtin, gtin8/12/13/14, isbn or mpn on the Product node, its offers or its variants"},
        IDENTIFIER_EXPECTED, IDENTIFIER_FIX, importance_tier=_tier(urls, key_urls))], recorded


# -- running them ----------------------------------------------------------------------------------------------------

RULE_CHECKS = {"IDX-5": "SEO-036", "IDX-6": "SEO-061, links to redirects (Stage 8a)", "IDX-7": "SEO-046, SEO-093",
               "STR-3": "SEO-078, SEO-097", "STR-15": "SEO-099", "TSEO-1": "decomposed characters, SEO-067", "ACC-3": "SEO-031",
               # Stage 8a, borrowed from Screaming Frog (DECISIONS 315, checks/stage8_rules.py).
               "IDX-4": "canonical chains", "STR-9": "hreflang target language", "STR-7": "images over 100 KB",
               # The SEO team's technical review (DECISIONS 343, checks/team_rules.py).
               "IDX-1": "redirects to an error page", "IDX-8": "second addresses of a page",
               "STR-1": "sub-pages copying the parent", "STR-2": "H1 of the section's name"}


def findings(result, *, key_urls=frozenset(), check_ids=None, saved: bool = False) -> tuple[dict[str, list[Finding]], list[dict]]:
    """({check id: new findings}, [{rule, why} not assessed]) for the checks in `check_ids` (all when None)."""
    from ..structure_data import indexable_pages
    wanted = set(check_ids) if check_ids is not None else set(RULE_CHECKS)
    out: dict[str, list[Finding]] = defaultdict(list)
    unassessed: list[dict] = []
    if not wanted & set(RULE_CHECKS):
        return out, unassessed
    pages = list(result.pages)
    read = _read(pages)
    if not read:
        return out, unassessed
    groups = grouping_of(result)
    indexable = {p.url for p in indexable_pages(result)}
    read_urls = {p.url for p in read}
    sitemap = [u for u in getattr(result, "sitemap_urls", None) or [] if isinstance(u, str)]
    origin = getattr(result, "origin", None) or ""
    from ..urls import same_origin
    known = list(dict.fromkeys([p.url for p in pages] + [_bare(e.get("target") or "") for p in read for e in p.outlinks or []]
                               + list(getattr(result, "discovered_urls", None) or []) + sitemap))
    known = [u for u in known if u and (not origin or same_origin(u, origin))]
    if "IDX-6" in wanted:
        out["IDX-6"] += alias_links(read, groups, key_urls)
    if "STR-15" in wanted:
        out["STR-15"] += empty_collections(read, groups, indexable, key_urls)
    if "TSEO-1" in wanted:
        out["TSEO-1"] += decomposed_addresses(known, read_urls, set(sitemap), key_urls)
        out["TSEO-1"] += unclear_slugs(read, groups, indexable, key_urls)
    if "ACC-3" in wanted:
        policies = getattr(result, "robots_policy_by_origin", None)
        if policies is None:
            unassessed.append({"rule": "SEO-031 noindex behind robots.txt (acc3.robots_noindex)",
                               "why": "the saved report keeps no robots.txt text to test Googlebot's and Bingbot's rules"})
        else:
            out["ACC-3"] += robots_noindex(read, policies.get(origin), key_urls)
    if "IDX-7" in wanted:
        out["IDX-7"] += pagination_unlinked(read, groups, known, key_urls)
        out["IDX-7"] += product_no_category(read, groups, indexable, key_urls)
    if "IDX-5" in wanted:
        media, why = media_sitemaps(read, getattr(result, "sitemap_docs", None) or [], key_urls)
        out["IDX-5"] += media
        if why:
            unassessed.append({"rule": "SEO-036 image and video sitemaps (idx5.no_image_sitemap, idx5.no_video_sitemap)", "why": why})
    if "STR-3" in wanted:
        out["STR-3"] += article_no_author(read, groups, indexable, key_urls, saved=saved)
        made, recorded = product_no_identifier(read, groups, key_urls)
        out["STR-3"] += made
        if not recorded and any((groups.get(p.url) or {}).get("page_type") == "product" for p in read):
            unassessed.append({"rule": "SEO-097 product identifiers (str3.product_no_identifier)",
                               "why": "no product page read has Product fields recorded (no Product markup, or a report "
                                      "saved before schema 1.24 without its saved JSON-LD)"})
    # Stage 8a (DECISIONS 315): whole-crawl rules borrowed from Screaming Frog.
    from . import stage8_rules as s8
    if "IDX-6" in wanted:
        out["IDX-6"] += s8.links_to_redirect(pages, read, key_urls)
    if "IDX-4" in wanted:
        out["IDX-4"] += s8.canonical_chain(read, key_urls)
    if "STR-9" in wanted:
        out["STR-9"] += s8.hreflang_wrong_language(read, key_urls)
    if "STR-7" in wanted:
        structure = getattr(result, "structure", None)
        if structure is None and saved:
            unassessed.append({"rule": "images over 100 KB (str7.over_100kb)",
                               "why": "the saved report keeps no image sample"})
        else:
            out["STR-7"] += s8.images_over_100kb(structure, key_urls)
    # DECISIONS 343: the SEO team's technical review (checks/team_rules.py).
    from . import team_rules
    made, missing = team_rules.findings(result, read, groups, wanted, key_urls, saved=saved)
    for check_id, new in made.items():
        out[check_id] += new
    unassessed.extend(missing)
    return out, unassessed


def extend(checks, result, cfg) -> None:
    """Add the quick checks' findings to the checks in `checks` they belong to (the engine's runners, before
    `settle_all`). A check that was not assessed gets none; one that gets a finding is "findings"."""
    from ..access_data import key_page_urls
    by_id = {c.check_id: c for c in checks if c.status != "not_assessed"}
    try:
        key_urls = set(key_page_urls(result, cfg))
    except Exception:  # a result without an origin (a made-up frame in a test)
        key_urls = set()
    made, _ = findings(result, key_urls=key_urls, check_ids=set(by_id))
    for check_id, new in made.items():
        check = by_id.get(check_id)
        if check is None or not new:
            continue
        check.findings.extend(new)
        check.status = "findings"
