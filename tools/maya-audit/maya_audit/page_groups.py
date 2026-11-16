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
  a utility page, at most 35 for a policy page linked only from footers.
- *Aliases* (DECISIONS 298): a page read whose canonical names another same-site address is an alias of it. Links to
  the alias count for the canonical. A canonical that was not read but ends in the same item as its aliases
  (`/collections/x/products/y` -> `/products/y`) is scored too, from its aliases' links, and listed in
  `page_grouping.canonical_pages`.
- *Order*: `importance_rank` breaks equal importance by body links in, then products listed, then sitemap order,
  then crawl order. Never by address.
- *Citable content*: a flag on blog and article pages, for weighting by business type later. It changes no score.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict, deque
from urllib.parse import unquote, urlsplit

from .page_words import ARTICLE_FOLDERS, CATEGORY_WORDS, PRODUCT_FOLDERS, fold

# 3 (DECISIONS 347): a sitewide og:type is a site default, not a page's type; item addresses with an id are products,
# pages listing them categories; store and branch pages are "location"; account and sign-in pages are utility; the
# homepage is the most important page. 4 (DECISIONS 350): a place page needs coordinates or opening hours, its own place
# markup, and no product, offer or service markup.
METHOD_VERSION = 4
PAGE_TYPES = ("home", "category", "product", "blog_article", "location", "policy", "utility", "other")

# -- URL pattern ---------------------------------------------------------------------------------------------------

# A folder of this many different children or more is a slug position (detect_templates' rule, DECISIONS 297).
MIN_SIBLINGS = 2
# A segment that looks like an id: has a digit and is long, or is hex / a uuid.
_ID = re.compile(r"^(?=.*\d)[\w.-]{6,}$|^\d+$|^[0-9a-f]{8,}$|^[0-9a-f-]{32,36}$", re.IGNORECASE)
# A language folder ("/en", "/tr", "/en-us", "/zh-hans", "/es-419"): kept as it is, and the folder after it is a
# section, as at the root. After the language only a region (two letters or three digits) or a script (DECISIONS 311:
# "/qr-menu/" is a page, not a language).
_LOCALE = re.compile(r"^[a-z]{2}(?:[-_](?:[a-z]{2}|\d{3}|hans|hant|latn|cyrl|arab))?$", re.IGNORECASE)
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
# DECISIONS 347 (atasunoptik: /Uye/PlusLogin, /Uye/OrderTracker typed "ürün"): a segment naming an account, a sign-in, a
# membership or one's orders, as a word of it (/uye, /my-orders, /siparis-takip) or at its end (/PlusLogin). Words that
# also name products or offers (sepet, profil, hesap-ac) count only as a whole segment (UTILITY_SEGMENTS).
ACCOUNT_WORD = re.compile(
    r"(?:^|[-_.])(?:uye|uyeler|uyelik|myaccount|my-account|hesabim|login|logout|signin|signout|signup|register|kayit-ol|"
    r"giris-yap|uye-girisi|siparislerim|siparis-takip|siparis-takibi|ordertracker|order-tracking|my-orders|"
    r"sifremi-unuttum|adreslerim|favorilerim|profilim|my-profile)(?:$|[-_.])|(?:login|logout|signin|signup|register|tracker)$")


def account_segment(segment: str) -> bool:
    """A folded address segment that names an account, sign-in, order or cart page (DECISIONS 347)."""
    return bool(ACCOUNT_WORD.search(segment))


# DECISIONS 347: an item address with an id: a name of several words, at least two of them holding a digit (a model
# code, a colour code, a size), and a trailing number of four digits or more ("…-0ax2034s-600087-…_82087").
_ITEM_ID = re.compile(r"^(?P<name>.+?)[_-](?P<id>\d{4,})$")


def item_address(url: str) -> bool:
    segs = _segments(url)
    if not segs:
        return False
    m = _ITEM_ID.match(fold(segs[-1]))
    if not m:
        return False
    words = [w for w in re.split(r"[-_.]+", m.group("name")) if w]
    return len(words) >= 4 and sum(1 for w in words if any(c.isdigit() for c in w)) >= 2


LOCATION_TYPES = frozenset({"Store", "LocalBusiness", "Optician", "AutoDealer", "Pharmacy", "Restaurant", "CafeOrCoffeeShop",
                            "MedicalClinic", "Dentist", "Hospital", "BankOrCreditUnion", "ClothingStore", "ShoeStore",
                            "ElectronicsStore", "HomeGoodsStore", "GroceryStore", "DepartmentStore", "JewelryStore",
                            "SportingGoodsStore", "HealthAndBeautyBusiness", "AutoRepair", "Hotel", "Place"})
# DECISIONS 350 (isbank: /ihtiyac-kredisi and /ek-hesap carry the bank's BankOrCreditUnion and PostalAddress markup
# beside their loan offer): a postal address alone is any organisation's; a place page has coordinates or opening hours.
PLACE_DETAIL_TYPES = frozenset({"GeoCoordinates", "OpeningHoursSpecification"})
# Markup of what a page sells or does: such a page is a product, fee or calculator page, never one place.
NOT_A_PLACE_TYPES = frozenset({"Product", "ProductGroup", "Offer", "AggregateOffer", "LoanOrCredit", "FinancialProduct",
                               "BankAccount", "DepositAccount", "CreditCard", "PaymentCard", "InvestmentOrDeposit",
                               "MortgageLoan", "Service", "FinancialService", "WebApplication", "SoftwareApplication",
                               "ItemList", "OfferCatalog"})
_MAP = re.compile(r"google\.[a-z.]+/maps|maps\.google|yandex\.[a-z.]+/map|/maps/embed|openstreetmap\.org", re.IGNORECASE)
_HOURS = re.compile(r"\b(?:çalışma|calisma|açılış|acilis|mağaza|magaza|ziyaret) saatleri\b|\bopening hours\b|\bstore hours\b",
                    re.IGNORECASE)


def location_reason(page, sitewide_types: frozenset = frozenset()) -> str | None:
    """DECISIONS 347, 350: a page that is mainly one place of the business (a store, a branch): its own place markup
    (not one most pages carry) with coordinates or opening hours; or an embedded map with opening hours in its headings
    or GeoCoordinates. Never a page whose markup says it sells or does something (a product, a loan, an offer, a
    service, a calculator). None otherwise."""
    a = page.analysis or {}
    types = set((a.get("structured_data") or {}).get("types") or [])
    if types & NOT_A_PLACE_TYPES:
        return None
    place = sorted((types - set(sitewide_types)) & LOCATION_TYPES)
    if place and types & PLACE_DETAIL_TYPES:
        return f"{place[0]} markup with {sorted(types & PLACE_DETAIL_TYPES)[0]}"
    maps = any(_MAP.search(f.get("src") or "") for f in a.get("iframes") or [] if isinstance(f, dict))
    heads = " ".join(h.get("text") or "" for h in a.get("headings") or [] if isinstance(h, dict))
    if maps and _HOURS.search(heads):
        return "an embedded map and opening hours"
    if maps and "GeoCoordinates" in types:
        return "an embedded map and GeoCoordinates"
    return None


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
TYPE_WEIGHT = {"home": 100, "category": 80, "product": 70, "blog_article": 60, "location": 50, "other": 50, "policy": 15,
               "utility": 0}
# DECISIONS 347: an og:type on this share of the pages read (and at least OG_DEFAULT_MIN pages) is the site's default.
OG_DEFAULT_SHARE = 0.5
OG_DEFAULT_MIN = 4
# A page linking (outside its menu and footer) to this many item addresses lists products.
ITEM_LINKS_MIN = 3
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


def _og(page) -> str:
    return ((page.analysis.get("og") or {}).get("og:type") or [""])[0].casefold()


def og_default(read) -> str | None:
    """The og:type most pages read carry when it is the site's default (DECISIONS 347), else None: on at least half of
    them, OG_DEFAULT_MIN or more."""
    kinds = Counter(_og(p) for p in read)
    kinds.pop("", None)
    if not kinds or not read:
        return None
    top, n = kinds.most_common(1)[0]
    return top if n >= OG_DEFAULT_MIN and n / len(read) >= OG_DEFAULT_SHARE else None


def _item_links(page) -> set[str]:
    return {t for t in _body_targets(page) if item_address(t)}


def page_type(page, home: str, homes: set[str], products: dict, site_og: str | None = None,
              sitewide_types: frozenset = frozenset()) -> tuple[str, str]:
    """(type, basis). The order: home, utility (an account or sign-in address too), policy, an item address with an id,
    a place of the business, then the STR-3 page kind (`structure.page_kind`) with a sitewide og:type left out
    (`site_og`, DECISIONS 347), own Product markup, links to item addresses."""
    from .checks.structure import nested_product, page_kind
    if page.url == home:
        return "home", "the start address's final page"
    if page.url in homes:
        return "home", "a language version of the homepage (hreflang or <html lang>)"
    segs = [fold(s) for s in _segments(page.url)]
    utility = next((s for s in segs if s in UTILITY_SEGMENTS), None)
    if utility:
        return "utility", f"/{utility} in the address"
    account = next((s for s in segs if account_segment(s)), None)
    if account:
        return "utility", f"an account, sign-in or order address (/{account})"
    types = set(page.analysis["structured_data"]["types"]) & UTILITY_TYPES
    if types:
        return "utility", f"its structured data is a {sorted(types)[0]}"
    body = [s for s in segs if not is_locale(s)]
    if body and body[0] in POLICY_FOLDERS:
        return "policy", f"path /{body[0]}/…"
    if body and _words(body[-1]) & POLICY_WORDS and body[0] not in (PRODUCT_FOLDERS | CATEGORY_WORDS | ARTICLE_FOLDERS):
        return "policy", f"policy word in the address ({sorted(_words(body[-1]) & POLICY_WORDS)[0]})"
    nested = nested_product(segs)
    if nested:
        # Shopify's /collections/<c>/products/<p>: a product shown inside a collection (STR-3's rule, DECISIONS 298).
        return "product", nested
    if len(body) >= 2 and body[0] in ARTICLE_FOLDERS_GROUPING and not set(body) & CATEGORY_WORDS and (
            len(body) >= 3 or body[0] in ARTICLE_FOLDERS):
        return "blog_article", f"path /{body[0]}/…"
    if item_address(page.url):
        return "product", "an item address with a model code and an id"
    place = location_reason(page, sitewide_types)
    if place:
        return "location", place
    kind, why = page_kind(page, home, products)
    own_types = set(page.analysis["structured_data"]["types"]) - set(sitewide_types)
    if kind == "product" and site_og == "product" and (why or "").startswith("og:type"):
        # og:type=product on most pages read is the site's default, not this page's type (DECISIONS 347)
        if page.url in products:
            return "product", products[page.url]
        if len(body) >= 2 and body[0] in PRODUCT_FOLDERS:
            return "product", f"path /{body[0]}/…"
        if "Product" in own_types and own_types & {"Offer", "AggregateOffer"}:
            return "product", "its own Product markup with an Offer"
        kind, why = None, None
    if kind == "product":
        return "product", why
    items = _item_links(page)
    if len(items) >= ITEM_LINKS_MIN:
        return "category", f"links to {len(items)} item addresses outside its menu and footer"
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
# A policy or legal page linked only from footers (DECISIONS 298): above a product it would mislead.
POLICY_FOOTER_CAP = 35
# A link outside the menu and footer on at least this share of the pages read (and this many pages) is a sitewide block.
SITEWIDE_BLOCK_SHARE = 0.5
SITEWIDE_BLOCK_MIN_PAGES = 4
POLICY_FOOTER_ONLY = "policy page linked only from footers or sitewide blocks"
WEIGHTS = {"internal_link_score": 0.5, "click_depth": 0.25, "page_type": 0.25}


def _last_segment(url: str) -> str:
    segs = _segments(url)
    return fold(segs[-1]) if segs else ""


def _product_key(url: str) -> str:
    """One key per product: `/collections/x/products/y` and `/products/y` (language folder kept) are the same one."""
    from .checks.structure import nested_product
    segs = [fold(x) for x in _segments(url)]
    if nested_product(segs):
        lead = next(i for i, x in enumerate(segs) if x in CATEGORY_WORDS)
        segs = segs[:lead] + segs[-2:]
    return "/" + "/".join(segs)


def canonical_aliases(read, nodes: set[str], origin: str = "", fetched: set[str] = frozenset()) -> dict[str, str]:
    """{alias: canonical} for the pages read whose canonical names another same-site address (DECISIONS 298): a page
    read, or an address not read that ends in the same item as the alias (`/collections/x/products/y` names
    `/products/y`). A canonical not read that names another item (every page canonical to one address, a known CMS
    mistake), or that was fetched and is not a readable page (a redirect, an error), is not followed: the page keeps its
    links."""
    from .index_data import canonical_target
    from .urls import same_origin, upper_escapes
    out = {}
    for p in read:
        target = canonical_target(p)
        # A canonical that differs only in the case of its percent-escapes names the page itself (DECISIONS 305).
        if not target or upper_escapes(target) == upper_escapes(p.url) or (origin and not same_origin(target, origin)) or (
                target in fetched and target not in nodes):
            continue
        if target in nodes or (_last_segment(target) and _last_segment(target) == _last_segment(p.url)):
            out[p.url] = target
    return out


def _resolver(pages, nodes: set[str] = frozenset(), canonicals: bool = True, aliases: dict[str, str] | None = None):
    """Where a link to an address ends up: its redirects followed, then, when it is an alias (`canonical_aliases`), its
    canonical (links to a duplicate are counted for the page it names, as search engines merge them). Without
    `aliases`, a page read whose canonical names another page read."""
    from .index_data import canonical_target
    hops = {p.url: p.redirect_location for p in pages if p.redirect_location and p.status and 300 <= p.status < 400}
    if canonicals and aliases is not None:
        hops.update(aliases)
    for p in pages if canonicals and aliases is None else ():
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


def link_graph(pages, nodes: set[str], canonicals: bool = True,
               aliases: dict[str, str] | None = None) -> dict[str, dict[str, float]]:
    """{source: {target: weight}} between the pages in `nodes`, redirects followed and, with `canonicals`, links to an
    alias counted for its canonical (`_resolver`) and the alias's own links moved to its canonical; self-links left
    out. A canonical that was not read (in `nodes`, not among the pages) has only the links of its aliases. The link
    score uses the merged graph; click depth the links as a visitor clicks them (an unread canonical then links where
    its aliases do)."""
    resolve = _resolver(pages, nodes, canonicals, aliases)
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
    for u in nodes - set(graph):
        graph[u] = {}
    if canonicals:
        # An alias's own links are its canonical's (one page to a search engine): moved, not copied, so a duplicate
        # passes on no more than one page would.
        for alias, canonical in (aliases or {}).items():
            if alias in graph and canonical in graph:
                for v, w in graph[alias].items():
                    if v != canonical:
                        graph[canonical][v] = max(graph[canonical].get(v, 0.0), w)
                graph[alias] = {}
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


def _sitewide_types(read) -> frozenset:
    """Structured-data types on at least OG_DEFAULT_SHARE of the pages read: a site default, not a page's own."""
    if len(read) < OG_DEFAULT_MIN:
        return frozenset()
    counts = Counter(t for p in read for t in set((p.analysis.get("structured_data") or {}).get("types") or []))
    return frozenset(t for t, n in counts.items() if n / len(read) >= OG_DEFAULT_SHARE)


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
    pages_by_url = {p.url: p for p in read}
    site_items = any(_item_links(p) for p in read)  # the site's listings link to item addresses
    for url, (kind, _) in list(types.items()):
        if kind == "other" and by_key[keys[url]]:
            top, n = by_key[keys[url]].most_common(1)[0]
            total = sum(by_key[keys[url]].values())
            # DECISIONS 347 (atasunoptik's /iletisim on the listings' layout): a page that links to no item lists
            # nothing, whatever template it shares.
            if top == "category" and site_items and url in pages_by_url and not _item_links(pages_by_url[url]):
                continue
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


HOME_FIRST = "the homepage is the most important page (DECISIONS 347)"


def home_first(records: dict[str, dict], key: str = "page_type") -> None:
    """DECISIONS 347 (owner): the homepage is always the most important page. A homepage (or a language version of it)
    scoring below another page takes that page's importance; its parts say so. Changed in place."""
    homes = [g for g in records.values() if isinstance(g, dict) and g.get(key) == "home" and "importance" in g]
    others = [g["importance"] for g in records.values() if isinstance(g, dict) and g.get(key) != "home"
              and isinstance(g.get("importance"), (int, float))]
    top = max(others, default=0)
    for g in homes:
        if g["importance"] < top:
            g["importance"] = top
            g["importance_parts"] = {**(g.get("importance_parts") or {}), "raised": HOME_FIRST}


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
    aliases = canonical_aliases(read, nodes, origin, {p.url for p in pages})
    patterns = url_patterns(known + list(aliases.values()))
    layouts = {p.url: layout_fingerprint(p.analysis) for p in read}
    keys = template_keys(read, patterns, layouts)
    try:
        products = product_template(read, home)["products"]
    except (KeyError, TypeError):  # a saved page record without the working data the price reader needs
        products = {}
    homes = _home_language_versions(read, home)
    site_og = og_default(read)
    sitewide_types = _sitewide_types(read)
    types = {p.url: page_type(p, home, homes, products, site_og, sitewide_types) for p in read}
    refine_types(read, types, keys, layouts, patterns)

    unread = {c for c in aliases.values() if c not in nodes}  # canonicals scored from their aliases
    by_canonical: dict[str, list[str]] = defaultdict(list)
    for alias, canonical in aliases.items():
        by_canonical[canonical].append(alias)
    for canonical in unread:
        kinds = Counter(types[a][0] for a in by_canonical[canonical])
        kind = kinds.most_common(1)[0][0]
        types[canonical] = (kind, f"not read; the type of its {len(by_canonical[canonical])} alias(es)")
        layouts[canonical] = layouts[by_canonical[canonical][0]]
        keys[canonical] = patterns.get(canonical, "/")
    scored_urls = nodes | unread

    graph = link_graph(pages, scored_urls, aliases=aliases)
    rank = pagerank(graph)
    link_score = _log_scale(rank)
    home_page = next((p for p in read if p.url == home), None)
    resolve = _resolver(pages, scored_urls, aliases=aliases)
    alternates = {resolve(h.get("href") or "") for h in ((home_page.analysis or {}).get("hreflang") or [])} if home_page else set()
    depth, via_hreflang = click_depths(link_graph(pages, scored_urls, canonicals=False, aliases=aliases), home,
                                       alternates - {home})
    # A canonical not read is as close as the nearest of its aliases (the same content), or its own links if closer.
    via_alias: dict[str, str] = {}
    for canonical in unread:
        reached = [(depth[a], a) for a in by_canonical[canonical] if a in depth]
        if reached and (canonical not in depth or min(reached)[0] < depth[canonical]):
            depth[canonical], via_alias[canonical] = min(reached)
            if via_alias[canonical] in via_hreflang:
                via_hreflang.add(canonical)
    indexable = {p.url for p in indexable_pages(result)}

    # Where each page is linked from, over the merged links: body (outside menu and footer), menu, footer only.
    linked_from: dict[str, set[str]] = defaultdict(set)  # pages read that link to it (to it or to an alias of it)
    body_in: dict[str, set[str]] = defaultdict(set)
    in_menu: set[str] = set()
    listed_products: dict[str, set[str]] = defaultdict(set)
    product_patterns = {patterns.get(u) for u, (k, _) in types.items() if k == "product"} - {None, "/"}
    for p in read:
        for edge in p.outlinks or []:
            target = resolve(edge.get("target") or "")
            if not edge.get("footer") and not edge.get("nav"):
                # Products listed: links in the page's own content to product pages, read or not (by their pattern),
                # one per product whatever its ?variant= (DECISIONS 298).
                item = resolve((edge.get("target") or "").split("#")[0].split("?")[0])
                if item != p.url and ((item in types and types[item][0] == "product")
                                      or patterns.get(item) in product_patterns):
                    listed_products[p.url].add(_product_key(item))
            if target not in scored_urls or target == p.url:
                continue
            linked_from[target].add(p.url)
            # A link record says only whether *any* link to the target sits in a menu or a footer: one in the menu
            # and one in the footer is menu-and-footer when there are 2+ links; a single one in a <nav> in the
            # footer is the footer's. A footer with two links to it (nihan) is still the footer's only.
            if edge.get("nav") and (not edge.get("footer") or (edge.get("links") or 1) >= 2):
                in_menu.add(target)
            elif not edge.get("nav") and not edge.get("footer"):
                body_in[target].add(p.url)
    # A policy linked from the menu, or from the content of some pages, is not footer-only. A content link on most
    # pages read is a sitewide block (a cookie banner, a newsletter form's consent line) and counts as a footer.
    sitewide_body = SITEWIDE_BLOCK_SHARE * len(read) if len(read) >= SITEWIDE_BLOCK_MIN_PAGES else math.inf
    menu_or_body = in_menu | {u for u, sources in body_in.items() if len(sources) < sitewide_body}
    sitemap_at: dict[str, int] = {}
    for i, u in enumerate(result.sitemap_urls or []):
        if isinstance(u, str):
            sitemap_at.setdefault(u, i)
            sitemap_at.setdefault(u.rstrip("/") if urlsplit(u).path not in ("", "/") else u, i)
    crawl_at = {p.url: i for i, p in enumerate(pages)}

    def grouping(url: str) -> dict:
        kind, why = types[url]
        d = depth.get(url)
        d_score = DEPTH_SCORE.get(d, DEPTH_SCORE_DEEPER) if d is not None else 0
        score = (WEIGHTS["internal_link_score"] * link_score[url] + WEIGHTS["click_depth"] * d_score
                 + WEIGHTS["page_type"] * TYPE_WEIGHT[kind])
        # Not indexable (noindex, canonical elsewhere) or a search/cart/account page: at most 20, whatever its links.
        # A policy page linked only from footers: at most 35 (DECISIONS 298). A canonical not read: its indexability
        # is not known, so no cap is applied for it and it says so.
        if url in unread:
            capped = False
        elif url not in indexable:
            capped = "not indexable"
        elif kind == "utility":
            capped = "utility page"
        elif kind == "policy" and url not in menu_or_body:
            capped = POLICY_FOOTER_ONLY
        else:
            capped = False
        cap = POLICY_FOOTER_CAP if capped == POLICY_FOOTER_ONLY else NOT_INDEXABLE_CAP
        importance = min(round(score), cap) if capped else round(score)
        if d is None:
            depth_basis = "not reached from the homepage through the pages read"
        elif url in via_alias:
            depth_basis = f"through its alias {via_alias[url]}" + (" (and the homepage's hreflang)" if url in via_hreflang else "")
        else:
            depth_basis = "links and the homepage's hreflang" if url in via_hreflang else "links"
        out = {
            "template_key": keys[url], "url_pattern": patterns.get(url, keys[url]), "layout": layouts[url],
            "page_type": kind, "page_type_basis": why,
            "internal_link_score": link_score[url], "inlinks": len(linked_from[url]),
            "click_depth": d, "click_depth_basis": depth_basis,
            "importance": importance,
            "importance_parts": {"internal_link_score": link_score[url], "click_depth": d_score,
                                 "page_type": TYPE_WEIGHT[kind], "capped": capped},
            "tie_break": {"body_inlinks": len(body_in[url]), "products_listed": len(listed_products[url]),
                          "sitemap_position": sitemap_at.get(url)},
            "citable_content": kind == "blog_article",
        }
        if url in aliases:
            out["canonical"] = aliases[url]
        if url in by_canonical:
            out["aliases"] = len(by_canonical[url])
        if url in unread:
            out["read"] = False
            out["indexable"] = None
            out["basis"] = (f"not read: scored from the links to its {len(by_canonical[url])} alias(es), which name it "
                            "as their canonical")
        return out

    groupings = {url: grouping(url) for url in scored_urls}
    home_first(groupings)

    def order(url: str):
        g, first = groupings[url], min([crawl_at.get(a, len(pages)) for a in by_canonical.get(url, [])] or [len(pages)])
        tb = g["tie_break"]
        return (g["page_type"] != "home", -g["importance"], -tb["body_inlinks"], -tb["products_listed"],
                tb["sitemap_position"] if tb["sitemap_position"] is not None else math.inf, crawl_at.get(url, first))
    for i, url in enumerate(sorted(scored_urls, key=order), 1):
        groupings[url]["importance_rank"] = i
    for url, g in groupings.items():
        if "canonical" in g:
            g["canonical_importance"] = groupings.get(g["canonical"], {}).get("importance")

    for p in pages:
        p.grouping = groupings[p.url] if p.url in nodes else {
            "not_scored": "redirect" if p.redirect_location else "not a readable HTML page"}
    scored = [p for p in pages if p.url in nodes]
    summary = {
        "method_version": METHOD_VERSION, "confidence": "Estimated",
        "pages_scored": len(scored), "pages_not_scored": len(pages) - len(scored),
        "page_types": dict(Counter(types[p.url][0] for p in scored).most_common()),
        "templates": dict(Counter(keys[p.url] for p in scored).most_common(40)),
        "templates_total": len({keys[p.url] for p in scored}),
        "not_reached_from_homepage": sum(1 for p in scored if p.url not in depth),
        "reached_through_hreflang": sum(1 for p in scored if p.url in via_hreflang),
        "aliases": len(aliases),
        "canonical_pages_scored": len(unread),
        "canonical_pages": {url: groupings[url] for url in sorted(unread, key=order)},
        "citable_content_pages": sum(1 for p in scored if groupings[p.url]["citable_content"]),
        "weights": WEIGHTS, "type_weights": TYPE_WEIGHT, "footer_link_weight": FOOTER_WEIGHT,
        "not_indexable_cap": NOT_INDEXABLE_CAP, "policy_footer_cap": POLICY_FOOTER_CAP,
        "order": "importance, then body links in, then products listed, then sitemap order, then crawl order",
        "basis": "Links and click depth are measured over the pages read only; a page reached through a page that "
                 "was not read may be closer to the homepage than shown.",
    }
    result.page_grouping = summary
    return summary
