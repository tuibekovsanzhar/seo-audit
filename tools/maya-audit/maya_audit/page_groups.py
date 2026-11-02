"""Page grouping, v0.3 stage 3 (DECISIONS 297): for every page the crawl read, a template, a page type, an internal
link score, a click depth from the homepage and an importance from 0 to 100.

Rule-based and Estimated throughout. Sends no request. Nothing here changes a finding, a severity, a confidence or the
release gate: the values are stored on each page record (`PageFetch.grouping`) and summarised in
`CrawlResult.page_grouping`, for ordering and sampling later.

- *Template key*: the URL pattern (`/products/*`, `/en/collections/*`) and, when one pattern holds pages built on
  different layouts, the layout too (`/pages/* ~ 3f2a9c`). The pattern comes from every same-site address the audit
  knew (pages read, links found, sitemap), so one product read among many known still gets `/products/*`.
- *Layout fingerprint*: a short hash of what a template decides and a page's own text does not: og:type, page-kind
  structured-data types, main-region kinds, breadcrumbs, and the page's form targets (language folder removed).
- *Page type*: home, category, product, blog_article, policy, utility (search, cart, account), other.
- *Internal link score*: a weighted PageRank over the links between the pages read (a link from an important page
  counts more); 0-100 on a log scale against the site's best-linked page.
- *Click depth*: fewest link steps from the homepage over the links of the pages read, the homepage's hreflang
  alternates counting as one step (said per page); None when no chain of read pages reaches it (never 0, never a
  guess).
- *Importance*: 50% link score, 25% click depth, 25% page type; at most 20 for a page that is not indexable and for
  a utility page.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict, deque
from urllib.parse import unquote, urlsplit

from .page_words import ARTICLE_FOLDERS, CATEGORY_WORDS, PRODUCT_FOLDERS, fold

METHOD_VERSION = 1
PAGE_TYPES = ("home", "category", "product", "blog_article", "policy", "utility", "other")

# -- URL pattern ---------------------------------------------------------------------------------------------------

# A folder of this many different children or more is a slug position (detect_templates' rule, DECISIONS 297).
MIN_SIBLINGS = 2
# A segment that looks like an id: has a digit and is long, or is hex / a uuid.
_ID = re.compile(r"^(?=.*\d)[\w.-]{6,}$|^\d+$|^[0-9a-f]{8,}$|^[0-9a-f-]{32,36}$", re.IGNORECASE)
# A language folder ("/en", "/tr", "/en-us"): kept as it is, and the folder after it is a section, as at the root.
_LOCALE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2,4})?$", re.IGNORECASE)
# Folders whose children are always one item each (a slug), even when only one child is known.
SLUG_FOLDERS = PRODUCT_FOLDERS | ARTICLE_FOLDERS | CATEGORY_WORDS | frozenset(
    {"pages", "policies", "blogs", "collection", "kategoriler", "urunler", "sayfa", "sayfalar", "p", "c"})


def _segments(url: str) -> list[str]:
    return [unquote(s) for s in urlsplit(url).path.split("/") if s]


def is_locale(segment: str) -> bool:
    return bool(_LOCALE.match(segment))


class _Node:
    __slots__ = ("children", "urls")

    def __init__(self):
        self.children: dict[str, _Node] = {}
        self.urls: list[str] = []


def _merge(into: _Node, other: _Node) -> None:
    into.urls.extend(other.urls)
    for seg, child in other.children.items():
        _merge(into.children.setdefault(seg, _Node()), child)


def _collapse(node: _Node, depth: int, section_depth: int, parent: str | None) -> None:
    if depth >= section_depth and node.children and (
            len(node.children) >= MIN_SIBLINGS or fold(parent or "") in SLUG_FOLDERS):
        merged = _Node()
        for child in node.children.values():
            _merge(merged, child)
        node.children = {"*": merged}
    else:
        for seg in list(node.children):
            if seg != "*" and _ID.match(seg):
                child = node.children.pop(seg)
                _merge(node.children.setdefault("*", _Node()), child)
    for seg, child in node.children.items():
        # The folder after a language folder is a section too: "/en/products/*", not "/en/*/*".
        child_section = section_depth + 1 if depth == 0 and is_locale(seg) else section_depth
        _collapse(child, depth + 1, child_section, seg)


def url_patterns(urls) -> dict[str, str]:
    """{url: pattern} for the given addresses, the pattern built from all of them. The query is not part of it."""
    root = _Node()
    for url in dict.fromkeys(urls):
        node = root
        for seg in _segments(url):
            node = node.children.setdefault(seg, _Node())
        node.urls.append(url)
    _collapse(root, 0, 1, None)
    out: dict[str, str] = {}

    def walk(node: _Node, path: list[str]) -> None:
        for url in node.urls:
            out[url] = "/" + "/".join(path)
        for seg, child in node.children.items():
            walk(child, path + [seg])
    walk(root, [])
    return out


# -- layout fingerprint ------------------------------------------------------------------------------------------

# Structured-data types a template sets, not a page's content (FAQPage, Answer, Person... vary page to page).
TEMPLATE_TYPES = frozenset({
    "Product", "ProductGroup", "IndividualProduct", "Offer", "AggregateOffer", "CollectionPage", "ItemList",
    "OfferCatalog", "SearchResultsPage", "BreadcrumbList", "Article", "BlogPosting", "NewsArticle", "Blog",
    "ContactPage", "AboutPage", "CheckoutPage", "ProfilePage", "Recipe", "Event", "JobPosting", "Course",
    "LocalBusiness", "Restaurant", "SoftwareApplication"})


def _strip_locale(path: str) -> str:
    segs = [s for s in path.split("?")[0].split("/") if s]
    if segs and is_locale(segs[0]):
        segs = segs[1:]
    return "/" + "/".join("*" if _ID.match(s) else s for s in segs)


def layout_features(analysis: dict) -> dict:
    og = (analysis.get("og") or {}).get("og:type") or [""]
    types = set((analysis.get("structured_data") or {}).get("types") or []) & TEMPLATE_TYPES
    forms = sorted({_strip_locale(a) for a in analysis.get("form_actions") or [] if a and not a.startswith("http")})
    return {"og_type": (og[0] or "").casefold(), "types": sorted(types),
            "main": sorted(analysis.get("main_region_types") or []),
            "breadcrumbs": bool(analysis.get("breadcrumbs")), "forms": forms}


def layout_fingerprint(analysis: dict) -> str:
    f = layout_features(analysis)
    text = "|".join([f["og_type"], ",".join(f["types"]), ",".join(f["main"]), str(int(f["breadcrumbs"])),
                     ",".join(f["forms"])])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:6]


# -- page type ---------------------------------------------------------------------------------------------------

UTILITY_SEGMENTS = frozenset({
    "search", "arama", "ara", "cart", "carts", "basket", "sepet", "sepetim", "checkout", "checkouts", "odeme",
    "account", "accounts", "my-account", "hesap", "hesabim", "login", "log-in", "signin", "sign-in", "giris",
    "uye-girisi", "register", "signup", "sign-up", "kayit", "uye-ol", "uyelik", "wishlist", "favoriler",
    "favorilerim", "orders", "siparislerim", "siparis-takibi", "order-tracking", "password", "sifremi-unuttum"})
UTILITY_TYPES = frozenset({"SearchResultsPage", "CheckoutPage", "ProfilePage"})
# "blogs" too (Shopify); STR-3's ARTICLE_FOLDERS is left as it is.
ARTICLE_FOLDERS_GROUPING = ARTICLE_FOLDERS | frozenset({"blogs"})
POLICY_FOLDERS = frozenset({"policies", "policy", "legal", "yasal", "politikalar", "sozlesmeler"})
# Words of a policy page's last address segment, compared folded, word by word ("mesafeli-satis-sozlesmesi").
POLICY_WORDS = frozenset({
    "policy", "policies", "privacy", "terms", "conditions", "legal", "imprint", "impressum", "disclaimer", "gdpr",
    "cookie", "cookies", "refund", "returns", "shipping", "kvkk", "gizlilik", "politika", "politikasi", "politikamiz",
    "sozlesme", "sozlesmesi", "aydinlatma", "cerez", "kosullar", "kosullari", "iade", "rıza", "riza", "datenschutz",
    "agb", "mentions", "confidentialite", "cgv", "privacidad", "terminos"})
POLICY_TITLE = re.compile(
    r"\b(?:privacy policy|cookie policy|terms of (?:service|use)|terms and conditions|refund policy|shipping policy|"
    r"return policy|politikas[ıi]|s[öo]zle[şs]mesi|kvkk|ayd[ıi]nlatma metni|kullan[ıi]m ko[şs]ullar[ıi])\b",
    re.IGNORECASE)
TYPE_WEIGHT = {"home": 100, "category": 80, "product": 70, "blog_article": 60, "other": 50, "policy": 15,
               "utility": 0}
# A pattern holding at least this many typed pages, this share of them one type, lends that type to its "other" pages.
TEMPLATE_MIN_PAGES = 3
TEMPLATE_SHARE = 0.8


def _words(segment: str) -> set[str]:
    return set(re.split(r"[-_.]+", fold(segment)))


def _home_language_versions(pages, home: str) -> set[str]:
    """Addresses that are a language version of the homepage: a single language folder ("/en") that the homepage's
    hreflang lists, or whose own <html lang> is that language."""
    out = set()
    home_page = next((p for p in pages if p.url == home), None)
    listed = {h.get("href") for h in ((home_page.analysis or {}).get("hreflang") or [])} if home_page else set()
    for p in pages:
        segs = _segments(p.url)
        if len(segs) == 1 and is_locale(segs[0]) and not urlsplit(p.url).query:
            lang = ((p.analysis or {}).get("html_lang") or "").split("-")[0].casefold()
            if p.url in listed or p.url.rstrip("/") in listed or lang == segs[0].split("-")[0].casefold():
                out.add(p.url)
    return out


def page_type(page, home: str, homes: set[str], products: dict) -> tuple[str, str]:
    """(type, basis). The order: home, utility, policy, then the STR-3 page kind (`structure.page_kind`)."""
    from .checks.structure import page_kind
    if page.url == home:
        return "home", "the start address's final page"
    if page.url in homes:
        return "home", "a language version of the homepage (hreflang or <html lang>)"
    segs = [fold(s) for s in _segments(page.url)]
    utility = next((s for s in segs if s in UTILITY_SEGMENTS), None)
    if utility:
        return "utility", f"/{utility} in the address"
    types = set(page.analysis["structured_data"]["types"]) & UTILITY_TYPES
    if types:
        return "utility", f"its structured data is a {sorted(types)[0]}"
    body = [s for s in segs if not is_locale(s)]
    if body and body[0] in POLICY_FOLDERS:
        return "policy", f"path /{body[0]}/…"
    if body and _words(body[-1]) & POLICY_WORDS and body[0] not in (PRODUCT_FOLDERS | CATEGORY_WORDS | ARTICLE_FOLDERS):
        return "policy", f"policy word in the address ({sorted(_words(body[-1]) & POLICY_WORDS)[0]})"
    nested = next((i for i, s in enumerate(body) if i >= 1 and s in PRODUCT_FOLDERS and i + 1 < len(body)
                   and body[0] in CATEGORY_WORDS), None)
    if nested is not None:
        # Shopify's /collections/<c>/products/<p>: a product shown inside a collection, not the collection
        # (STR-3's page_kind calls it a listing; left as it is there).
        return "product", f"path /{body[0]}/…/{body[nested]}/…"
    if len(body) >= 2 and body[0] in ARTICLE_FOLDERS_GROUPING and not set(body) & CATEGORY_WORDS and (
            len(body) >= 3 or body[0] in ARTICLE_FOLDERS):
        return "blog_article", f"path /{body[0]}/…"
    kind, why = page_kind(page, home, products)
    if kind == "product":
        return "product", why
    if kind in ("category", "pagination"):
        return "category", why
    if kind == "article":
        return "blog_article", why
    if POLICY_TITLE.search(page.analysis.get("title") or ""):
        return "policy", "a policy name in the title"
    return "other", (f"{kind} page ({why})" if kind else "no rule matched")


# -- links -------------------------------------------------------------------------------------------------------

DAMPING = 0.85
ITERATIONS = 60
# A link found only in the footer counts this much against one in the body or the menu (reasonable-surfer, agent).
FOOTER_WEIGHT = 0.25
DEPTH_SCORE = {0: 100, 1: 85, 2: 70, 3: 55, 4: 40, 5: 25}
DEPTH_SCORE_DEEPER = 10
NOT_INDEXABLE_CAP = 20
WEIGHTS = {"internal_link_score": 0.5, "click_depth": 0.25, "page_type": 0.25}


def _resolver(pages, nodes: set[str] = frozenset(), canonicals: bool = True):
    """Where a link to an address ends up: its redirects followed, then, when it is a page read whose canonical names
    another page read, that page (links to a duplicate are counted for the page it names, as search engines merge
    them). A canonical to a page that was not read is not followed: the duplicate keeps its links."""
    from .index_data import canonical_target
    hops = {p.url: p.redirect_location for p in pages if p.redirect_location and p.status and 300 <= p.status < 400}
    for p in pages if canonicals else ():
        if p.url in nodes:
            target = canonical_target(p)
            if target and target != p.url and target in nodes:
                hops[p.url] = target

    def resolve(url: str) -> str:
        seen = set()
        while url in hops and url not in seen and len(seen) < 10:
            seen.add(url)
            url = hops[url]
        return url
    return resolve


def link_graph(pages, nodes: set[str], canonicals: bool = True) -> dict[str, dict[str, float]]:
    """{source: {target: weight}} between the pages in `nodes`, redirects followed and, with `canonicals`, links to a
    duplicate counted for the page read its canonical names (`_resolver`); self-links left out. The link score uses
    the merged graph; click depth the links as a visitor clicks them."""
    resolve = _resolver(pages, nodes, canonicals)
    graph: dict[str, dict[str, float]] = {}
    for p in pages:
        if p.url not in nodes:
            continue
        out: dict[str, float] = {}
        for edge in p.outlinks or []:
            target = resolve(edge.get("target") or "")
            if target not in nodes or target == p.url:
                continue
            weight = FOOTER_WEIGHT if edge.get("footer") and not edge.get("nav") else 1.0
            out[target] = max(out.get(target, 0.0), weight)
        graph[p.url] = out
    return graph


def pagerank(graph: dict[str, dict[str, float]]) -> dict[str, float]:
    nodes = list(graph)
    n = len(nodes)
    if not n:
        return {}
    rank = dict.fromkeys(nodes, 1.0 / n)
    for _ in range(ITERATIONS):
        dangling = sum(rank[u] for u in nodes if not graph[u])
        new = dict.fromkeys(nodes, (1 - DAMPING) / n + DAMPING * dangling / n)
        for u in nodes:
            out = graph[u]
            total = sum(out.values())
            if total:
                share = DAMPING * rank[u] / total
                for v, w in out.items():
                    new[v] += share * w
        delta = sum(abs(new[u] - rank[u]) for u in nodes)
        rank = new
        if delta < 1e-10:
            break
    return rank


def click_depths(graph: dict[str, dict[str, float]], home: str,
                 alternates: set[str] = frozenset()) -> tuple[dict[str, int], set[str]]:
    """Fewest steps from the homepage, and the pages whose shortest chain starts with one of the homepage's hreflang
    alternates (`alternates`: one step, as a crawler follows them; a language switcher is often a form, not a link)."""
    if home not in graph:
        return {}, set()
    depth = {home: 0}
    via_hreflang: set[str] = set()
    queue = deque([home])
    while queue:
        u = queue.popleft()
        for v in graph[u]:
            if v not in depth:
                depth[v] = depth[u] + 1
                if u in via_hreflang:
                    via_hreflang.add(v)
                queue.append(v)
        if u == home:
            for v in sorted(alternates):
                if v in graph and v not in depth:
                    depth[v] = 1
                    via_hreflang.add(v)
                    queue.append(v)
    return depth, via_hreflang


def _log_scale(rank: dict[str, float]) -> dict[str, int]:
    if not rank:
        return {}
    lo, hi = min(rank.values()), max(rank.values())
    if hi <= lo:
        return dict.fromkeys(rank, 100)
    span = math.log(hi) - math.log(lo)
    return {u: round(100 * (math.log(r) - math.log(lo)) / span) for u, r in rank.items()}


# -- templates and types over the whole site ---------------------------------------------------------------------

def template_keys(read, patterns: dict[str, str], layouts: dict[str, str]) -> dict[str, str]:
    """{url: template key}. The URL pattern; where one pattern holds two layouts of 2+ pages each, the layout too
    ("/pages/* ~ 3f2a9c"); and pages alone in a pattern with no "*" (a flat site's "/about", "/contact") that share
    a folder and a layout with another such page are one template ("/* ~ 3f2a9c")."""
    per_pattern: dict[str, Counter] = defaultdict(Counter)
    for p in read:
        per_pattern[patterns.get(p.url, "/")][layouts[p.url]] += 1
    split = {pat for pat, c in per_pattern.items() if sum(1 for n in c.values() if n >= 2) >= 2}

    def lone(pat: str) -> bool:
        segs = [x for x in pat.split("/") if x]
        return bool(segs) and "*" not in segs and sum(per_pattern[pat].values()) == 1 and not (
            len(segs) == 1 and is_locale(segs[0]))

    flat: Counter = Counter()
    for p in read:
        pat = patterns.get(p.url, "/")
        if lone(pat):
            flat[(pat.rsplit("/", 1)[0], layouts[p.url])] += 1
    keys = {}
    for p in read:
        pat, layout = patterns.get(p.url, "/"), layouts[p.url]
        if pat in split and per_pattern[pat][layout] >= 2:
            keys[p.url] = f"{pat} ~ {layout}"
        elif lone(pat) and flat[(pat.rsplit("/", 1)[0], layout)] >= 2:
            keys[p.url] = f"{pat.rsplit('/', 1)[0]}/* ~ {layout}"
        else:
            keys[p.url] = pat
    return keys


# og:type=article on at least this share of the pages read is a site builder's default, not a sign of an article.
OG_ARTICLE_SITEWIDE = 0.5
# A page with links of its own (outside the menu and footer) to this many articles or products lists them.
LISTING_MIN_LINKS = 3
SECTION_MIN_PAGES = 2


def _body_targets(page) -> set[str]:
    return {e.get("target") for e in page.outlinks or [] if not e.get("nav") and not e.get("footer")} - {page.url}


def refine_types(read, types: dict[str, tuple[str, str]], keys: dict[str, str], layouts: dict[str, str],
                 patterns: dict[str, str]) -> None:
    """The whole-site rules after each page's own: a sitewide og:type=article is not an article; a template of mostly
    one type lends it to its untyped pages; a page that lists articles or products, or is the section page of the
    pages under its folder, is a category."""
    og_article = [p.url for p in read if ((p.analysis.get("og") or {}).get("og:type") or [""])[0].casefold() == "article"]
    if read and len(og_article) / len(read) >= OG_ARTICLE_SITEWIDE:
        folder_layouts = {layouts[u] for u, (k, why) in types.items() if k == "blog_article" and why.startswith("path")}
        for url in og_article:
            kind, why = types[url]
            if kind == "blog_article" and why.startswith("og:type"):
                if layouts[url] in folder_layouts:
                    types[url] = ("blog_article", "og:type='article' and the layout of the posts in an article folder")
                else:
                    types[url] = ("other", f"og:type='article' on {len(og_article)} of {len(read)} pages read "
                                           "(a site default), and no article folder or post layout")
    by_key: dict[str, Counter] = defaultdict(Counter)
    for url, (kind, _) in types.items():
        if kind != "other":
            by_key[keys[url]][kind] += 1
    for url, (kind, _) in list(types.items()):
        if kind == "other" and by_key[keys[url]]:
            top, n = by_key[keys[url]].most_common(1)[0]
            total = sum(by_key[keys[url]].values())
            if top in ("product", "category", "blog_article") and n >= TEMPLATE_MIN_PAGES and n / total >= TEMPLATE_SHARE:
                types[url] = (top, f"same template as {n} {top} page(s)")
    # Types by pattern, so a link to an article or a product that was not read still counts as one.
    pattern_type: dict[str, Counter] = defaultdict(Counter)
    for url, (kind, _) in types.items():
        if kind in ("blog_article", "product"):
            pattern_type[patterns.get(url, "/")][kind] += 1
    by_url = {p.url: p for p in read}
    for url, (kind, _) in list(types.items()):
        if kind != "other":
            continue
        page = by_url[url]
        listed = Counter()
        for target in _body_targets(page):
            counts = pattern_type.get(patterns.get(target, ""))
            if target in types and types[target][0] in ("blog_article", "product"):
                listed[types[target][0]] += 1
            elif counts and patterns.get(target) != patterns.get(url):
                listed[counts.most_common(1)[0][0]] += 1
        if sum(listed.values()) >= LISTING_MIN_LINKS:
            top = listed.most_common(1)[0][0]
            types[url] = ("category", f"links to {sum(listed.values())} {top} page(s) outside its menu and footer")
            continue
        # A section page: 2+ pages under its folder were read, and it links to 2+ pages under it (menu links count).
        prefix = url.split("?")[0].rstrip("/") + "/"
        under_read = [u for u in types if u != url and u.startswith(prefix)]
        linked = {e.get("target") for e in page.outlinks or []} & {u for u in patterns if u.startswith(prefix)}
        if len(under_read) >= SECTION_MIN_PAGES and len(linked) >= SECTION_MIN_PAGES:
            types[url] = ("category", f"the section page of its folder: links to {len(linked)} page(s) under it, "
                                      f"{len(under_read)} of them read")


# -- the whole -----------------------------------------------------------------------------------------------------

def annotate(result) -> dict:
    """Set `grouping` on every page record of `result` and `result.page_grouping`; return the summary."""
    from .access_data import homepage_url
    from .checks.structure import product_template
    from .structure_data import indexable_pages, readable_html
    from .urls import same_origin

    pages = list(result.pages)
    home = homepage_url(result)
    read = [p for p in pages if p.analysis and readable_html(p)]
    nodes = {p.url for p in read}
    origin = getattr(result, "origin", None) or ""
    known = [u for u in [p.url for p in pages] + list(result.discovered_urls or []) + list(result.sitemap_urls or [])
             if isinstance(u, str) and (not origin or same_origin(u, origin))]
    patterns = url_patterns(known)
    layouts = {p.url: layout_fingerprint(p.analysis) for p in read}
    keys = template_keys(read, patterns, layouts)
    try:
        products = product_template(read, home)["products"]
    except (KeyError, TypeError):  # a saved page record without the working data the price reader needs
        products = {}
    homes = _home_language_versions(read, home)
    types = {p.url: page_type(p, home, homes, products) for p in read}
    refine_types(read, types, keys, layouts, patterns)

    graph = link_graph(pages, nodes)
    rank = pagerank(graph)
    link_score = _log_scale(rank)
    home_page = next((p for p in read if p.url == home), None)
    resolve = _resolver(pages, nodes)
    alternates = {resolve(h.get("href") or "") for h in ((home_page.analysis or {}).get("hreflang") or [])} if home_page else set()
    depth, via_hreflang = click_depths(link_graph(pages, nodes, canonicals=False), home, alternates - {home})
    inlinks: Counter = Counter(v for u in graph for v in graph[u])
    indexable = {p.url for p in indexable_pages(result)}

    for p in pages:
        if p.url not in nodes:
            p.grouping = {"not_scored": "redirect" if p.redirect_location else "not a readable HTML page"}
            continue
        kind, why = types[p.url]
        d = depth.get(p.url)
        d_score = DEPTH_SCORE.get(d, DEPTH_SCORE_DEEPER) if d is not None else 0
        score = (WEIGHTS["internal_link_score"] * link_score[p.url] + WEIGHTS["click_depth"] * d_score
                 + WEIGHTS["page_type"] * TYPE_WEIGHT[kind])
        # Not indexable (noindex, canonical elsewhere) or a search/cart/account page: at most 20, whatever its links.
        capped = "not indexable" if p.url not in indexable else "utility page" if kind == "utility" else False
        importance = min(round(score), NOT_INDEXABLE_CAP) if capped else round(score)
        p.grouping = {
            "template_key": keys[p.url], "url_pattern": patterns.get(p.url, "/"), "layout": layouts[p.url],
            "page_type": kind, "page_type_basis": why,
            "internal_link_score": link_score[p.url], "inlinks": inlinks[p.url],
            "click_depth": d,
            "click_depth_basis": ("not reached from the homepage through the pages read" if d is None else
                                  "links and the homepage's hreflang" if p.url in via_hreflang else "links"),
            "importance": importance,
            "importance_parts": {"internal_link_score": link_score[p.url], "click_depth": d_score,
                                 "page_type": TYPE_WEIGHT[kind], "capped": capped},
        }
    scored = [p for p in pages if p.url in nodes]
    summary = {
        "method_version": METHOD_VERSION, "confidence": "Estimated",
        "pages_scored": len(scored), "pages_not_scored": len(pages) - len(scored),
        "page_types": dict(Counter(types[p.url][0] for p in scored).most_common()),
        "templates": dict(Counter(keys[p.url] for p in scored).most_common(40)),
        "templates_total": len({keys[p.url] for p in scored}),
        "not_reached_from_homepage": sum(1 for p in scored if p.url not in depth),
        "reached_through_hreflang": sum(1 for p in scored if p.url in via_hreflang),
        "weights": WEIGHTS, "type_weights": TYPE_WEIGHT, "footer_link_weight": FOOTER_WEIGHT,
        "not_indexable_cap": NOT_INDEXABLE_CAP,
        "basis": "Links and click depth are measured over the pages read only; a page reached through a page that "
                 "was not read may be closer to the homepage than shown.",
    }
    result.page_grouping = summary
    return summary
