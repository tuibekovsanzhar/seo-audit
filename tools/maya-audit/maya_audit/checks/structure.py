"""STR-1 to STR-10: content structure and semantics (spec §5 STR).

Every observation is on the raw HTML (what non-rendering answer engines receive).
The HTML facts are Verified; how much they matter for AI is mostly Hypothesis, so
severities stay low (spec). None of these checks are markable (spec §2.5).

Root cause once: a page whose content is missing from raw HTML (an RND-1 finding) is
not re-reported for its missing headings, images, tables, or visible values; the
homepage's missing Organization schema is reported by STR-3, not again by STR-5.
"""

from __future__ import annotations

import re
import shlex
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urljoin, urlsplit

from .. import shared_elements
from ..access_data import homepage_url, key_page_urls
from ..analysis import iter_typed_nodes, node_types
from ..config import (FORMAT_NEGOTIATING_IMAGE, IMAGE_HEAVY_BYTES, IMAGE_VERY_HEAVY_BYTES, VIDEO_HEAVY_BYTES,
                      DATE_LABELS_MORE, MONTH_NAMES_MORE, PLACEHOLDER_ALTS_MORE, PLACEHOLDER_VIDEO_NAMES_MORE,
                      PLACEHOLDER_ALT_FILE, PLACEHOLDER_ALTS, MIN_IMAGES_FOR_FORMAT_SHARE, NEXT_GEN_IMAGE_TYPES, OLDER_IMAGE_TYPES, FOREIGN_CONTENT_SHARE, MIN_FOREIGN_HEADINGS, MIN_WORDS_FOR_LANGUAGE_SHARE, PLACEHOLDER_TEXT, SITEWIDE_MIN_PAGES,
                      SITEWIDE_SHARE, TEASER_MIN_PAGES, TEASER_SHARE, CrawlConfig)
from ..coverage import settle_all
from ..findings import CheckResult, Finding, Rationale, ReviewItem, Severity, scope_for
from ..language import MIN_HITS as LANGUAGE_MIN_HITS
from ..language import (BCP47, NAMES, SUPPORTED, block_language, detect_language, english_text_assessable,
                        hreflang_code_problem, HEADING_METHOD, has_personal_title, heading_language, primary_subtag, turkish_fold)
from ..main_content import BASIS as MAIN_CONTENT_BASIS
from ..main_content import norm as block_norm
from ..main_content import (appears_on_most, blocks_on_most_pages, body_blocks, content_blocks, heading_blocks, main_blocks, own_text, teaser_blocks,
                            repeated_blocks)
from ..models import Confidence, CrawlResult
from ..page_words import (ARTICLE_FOLDERS, BUY_WORDS, CART_ACTION, CATEGORY_WORDS, FAQ_WORDS, PRICING_WORDS,
                          PRODUCT_FOLDERS, UI_WORD_LANGUAGES, UI_WORDS, fold, says)
from ..structure_data import (CLASH_ORGANIZATION_TYPES, ORGANIZATION_TYPES, StructureData, as_list, indexable_pages, organization_nodes,
                              same_page,
                              text_value)
from ..technical_seo import run_traditional_seo_quality_check
from ..urls import normalize_url, origin_of, registrable_domain
from .access import _status, _tier
from .small_site import run_small_site_checks
from .content_quality import (str13_template_markers, str14_anchor_text, str15_thin_content,
                              str16_duplicate_descriptions, str17_dead_ends)
from .render import banner_shaped_without_alt

CARD_ENGINES = ["ChatGPT search", "Perplexity", "Google AI Overviews / AI Mode"]
PASSAGE_ENGINES = ["all answer engines that retrieve passages"]
SD_ENGINES = ["Google AI Overviews / AI Mode", "Microsoft Copilot (Bing)", "other engines that read structured data"]
HYPOTHESIS = Rationale.HYPOTHESIS.value
# The homepage's own heading findings (DECISIONS 258) rest on a published standard, not on a hypothesis about engines.
HEADINGS_DOCUMENTED = ("Documented (WCAG 2.2 SC 1.3.1 and 2.4.6: headings are marked up as headings and describe the "
                       "content; a heading hidden with display:none is exposed to no reader) / Hypothesis (AI benefit)")
CAPPED = "Capped at S4: Hypothesis."

ARTICLE_TYPES = {"Article", "BlogPosting", "NewsArticle", "TechArticle", "Report", "ScholarlyArticle", "LiveBlogPosting",
                 "OpinionNewsArticle", "AnalysisNewsArticle", "ReportageNewsArticle", "SocialMediaPosting"}
PRODUCT_TYPES = {"Product", "ProductGroup", "IndividualProduct", "ProductModel"}
EXPECTED_TYPES = {
    "homepage": ORGANIZATION_TYPES,
    "product": PRODUCT_TYPES,
    "article": ARTICLE_TYPES,
    "pricing": PRODUCT_TYPES | {"Offer", "AggregateOffer", "SoftwareApplication", "WebApplication", "MobileApplication"},
    "faq": {"FAQPage"},
}
# English and Turkish folders (maya_audit.page_words, DECISIONS 229).
PRODUCT_SEGMENTS = PRODUCT_FOLDERS
ARTICLE_SEGMENTS = ARTICLE_FOLDERS
# A page the markup says is a restaurant or a list of pages is not an article because its og:type says "article"
# (FA-033): site builders set og:type=article on every page. A path word still makes it one.
NOT_ARTICLE_BY_OG_TYPE = frozenset({"Restaurant", "CollectionPage"})
KIND_NOTE = ("Estimated: page kind is guessed from the URL path (English and Turkish words), og:type, and for products a "
             "page price with a buy button.")
# How many pages must look like a product page by their price and buy button before any of them is taken for one,
# and before pages with a price and no buy button are noted (DECISIONS 229).
PRODUCT_TEMPLATE_MIN_PAGES = 2
GENERIC_TITLES = {"home", "homepage", "home page", "untitled", "untitled document", "index", "document", "welcome",
                  "react app", "vite app", "vite + react", "vite + react + ts", "next.js", "new page", "page",
                  # Turkish (B09), written folded: a title is compared as it is and folded ("Başlıksız" is "basliksiz").
                  "anasayfa", "ana sayfa", "basliksiz", "basliksiz belge", "yeni sayfa", "sayfa",
                  # German, French, Spanish, Arabic (G23), folded the same way ("Página de inicio").
                  "startseite", "neue seite", "unbenannt", "accueil", "page d accueil", "sans titre", "nouvelle page",
                  "inicio", "pagina de inicio", "sin titulo", "nueva pagina", "الرئيسية", "الصفحة الرئيسية"}


# -- shared helpers ------------------------------------------------------------

def _norm(text: str | None) -> str:
    # A capital dotted İ is Turkish i: casefold() would give "i" and a combining dot, which split the word in two
    # ("İçerenköy" was "i çerenköy", DECISIONS 221).
    return " ".join(re.sub(r"[^\w&]+", " ", (text or "").replace("İ", "i").casefold().replace("\u0307", "")).split())


def _rendering_gap(render_checks) -> set[str]:
    rnd1 = next((c for c in render_checks if c.check_id == "RND-1"), None)
    return {u for f in (rnd1.findings if rnd1 else []) if f.severity in (Severity.S2, Severity.S3)
            for u in f.scope["urls"]}


def _typed_nodes(analysis: dict) -> list[tuple[dict, bool]]:
    return [(node, nested) for item in analysis.get("_structured_items", []) for node, nested in iter_typed_nodes(item["data"])]


def _types(analysis: dict) -> set[str]:
    return set(analysis["structured_data"]["types"])


# Path sections that hold place pages (DECISIONS 266): never an article by og:type. Folded (no Turkish marks).
PLACE_SEGMENTS = frozenset({"sube", "subeler", "subelerimiz", "semt", "semtler", "bolge", "bolgeler", "ilce", "ilceler",
                            "magaza", "magazalar", "magazalarimiz", "lokasyon", "lokasyonlar", "branch", "branches",
                            "location", "locations", "store", "stores", "store-locator"})


# "Page 2", "Sayfa 2", "Seite 2", "Página 2", "Pagina 2", "Page 2 of 9" in a title (DECISIONS 278).
PAGE_NUMBER_TITLE = re.compile(r"\b(?:page|sayfa|seite|p[aá]gina)\s*\d+\b", re.IGNORECASE)
PAGE_PATH_WORDS = frozenset({"page", "sayfa", "seite", "pagina"})
# A list of posts links to at least this many pages under an article folder, outside its menu and footer.
PAGINATION_MIN_ITEMS = 3


def pagination_signals(page, segments: list[str]) -> list[str]:
    """Why a page looks like one page of a paginated list: a page number in its address, in its title, and links to
    several posts. One signal alone is not enough (a /blog/2024 post has a number in its address)."""
    query = urlsplit(page.url).query
    signals = []
    if (segments and segments[-1].isdigit()) or (len(segments) >= 2 and segments[-2] in PAGE_PATH_WORDS
                                                  and segments[-1].isdigit()) or re.search(r"(?:^|&)(?:page|p|sayfa)=\d+", query):
        signals.append("a page number in the address")
    if PAGE_NUMBER_TITLE.search(page.analysis.get("title") or ""):
        signals.append("a page number in the title")
    posts = {edge.get("target") for edge in getattr(page, "outlinks", None) or []
             if not edge.get("nav") and not edge.get("footer") and edge.get("target") != page.url
             and len([s for s in urlsplit(edge.get("target") or "").path.split("/") if s]) >= 2
             and fold([s for s in urlsplit(edge.get("target") or "").path.split("/") if s][0]) in ARTICLE_SEGMENTS}
    if len(posts) >= PAGINATION_MIN_ITEMS:
        signals.append(f"links to {len(posts)} posts")
    return signals


def page_kind(page, home: str, template: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """Estimated page kind from the URL path (English and Turkish words), og:type, and for products the page's own
    price with a buy button (`template`, from `product_template`). Never from the structured data being checked:
    Product markup does not make a product page. Markup only keeps a page typed Restaurant or CollectionPage from
    being an article by its og:type alone (DECISIONS 229, FA-033)."""
    if page.url == home:
        return "homepage", "the start URL's final page"
    og_type = (page.analysis["og"].get("og:type") or [""])[0].casefold()
    segments = [fold(s) for s in urlsplit(page.url).path.split("/") if s]
    listing = bool(set(segments) & CATEGORY_WORDS)  # a category, a tag, a collection or a brand: a list of pages
    if not listing and (og_type == "product" or (len(segments) >= 2 and segments[0] in PRODUCT_SEGMENTS)):
        return "product", f"og:type={og_type!r}" if og_type == "product" else f"path /{segments[0]}/…"
    if not listing and template and page.url in template:
        return "product", template[page.url]
    if segments and segments[-1] in PRICING_WORDS:
        return "pricing", f"path ends in /{segments[-1]}"
    if segments and segments[-1] in FAQ_WORDS:
        return "faq", f"path ends in /{segments[-1]}"
    paged = pagination_signals(page, segments)
    if len(paged) >= 2:
        # Page 2 of a blog is a list of posts, not a post (DECISIONS 278): no Article is expected of it.
        return "pagination", "; ".join(paged)
    if not listing and len(segments) >= 2 and segments[0] in ARTICLE_SEGMENTS:
        return "article", f"path /{segments[0]}/…"
    if segments and segments[0] in PLACE_SEGMENTS:
        # A branch, district or store page is a place, not an article, whatever its og:type (FA-035): its kind is
        # not guessed, so no type is expected of it.
        return None, None
    if not listing and og_type == "article" and not (NOT_ARTICLE_BY_OG_TYPE & _types(page.analysis)):
        return "article", f"og:type={og_type!r}"
    if listing:
        # A category, tag, collection or brand page lists other pages (DECISIONS 278); no type is expected of it.
        return "category", "a category, tag or collection word in the path"
    return None, None


def _buy_texts(page) -> list[str]:
    """The texts of the page's own buy buttons and links ("Sepete Ekle"), one per control. The header, menu, footer and
    sidebar are left out."""
    a = page.analysis
    texts = ([b["text"] for b in a.get("buttons") or [] if not b.get("in_chrome")] + list(a.get("input_buttons") or [])
             + [d["text"] for d in (a.get("link_controls") or []) + (a.get("dead_links") or []) if not d.get("in_footer") and not d.get("where")]
             + [anchor for edge in getattr(page, "outlinks", None) or [] if not edge.get("nav") and not edge.get("footer")
                for anchor in edge.get("anchors") or [edge.get("anchor") or ""]])
    return [text for text in texts if text and says(BUY_WORDS, fold(text))]


def _buy_control(page) -> str | None:
    """The text of the page's own buy button or link ("Sepete Ekle"), or the address of a form that posts to the cart;
    None when it has neither. The header, menu, footer and sidebar are left out."""
    texts = _buy_texts(page)
    if texts:
        return texts[0]
    return next((action for action in page.analysis.get("form_actions") or [] if CART_ACTION.search(fold(action))), None)


# A page is a list of products, not one product (H27), when it has this many buy buttons of its own, or links (outside
# the menu and footer) to this many pages that look like product pages. An agent default.
LISTING_MIN_ITEMS = 2
LISTING_TYPES = frozenset({"ItemList", "OfferCatalog", "CollectionPage", "SearchResultsPage"})


def listing_reason(page, products: set[str] | frozenset[str] = frozenset()) -> str | None:
    """Why a page is a list of products (a category page), or None: ItemList-type markup, several buy buttons of its
    own, or links to several pages that look like product pages (`products`)."""
    types = set(page.analysis["structured_data"]["types"]) & LISTING_TYPES
    if types:
        return f"its structured data is a {sorted(types)[0]}"
    buttons = len(_buy_texts(page))
    if buttons >= LISTING_MIN_ITEMS:
        return f"{buttons} buy buttons of its own"
    linked = {edge.get("target") for edge in getattr(page, "outlinks", None) or []
              if not edge.get("nav") and not edge.get("footer")} & (set(products) - {page.url})
    if len(linked) >= LISTING_MIN_ITEMS:
        return f"links to {len(linked)} pages that look like product pages"
    return None


def product_template(pages: list, home: str) -> dict:
    """The pages that look like a product page by what they show (DECISIONS 229): not the homepage, not under a category
    or an article folder, exactly one price of the page's own (`located_prices`: in its main content, not in link text,
    not in a block many pages repeat) and a buy control (`_buy_control`). At least `PRODUCT_TEMPLATE_MIN_PAGES` pages
    must look so, or none is taken for one. Product markup is not looked at.

    {"products": {url: why}, "maybe": [{"url", "price"}]}: "maybe" are the pages with that one price and no buy control,
    which may be product pages (an Info note, never a problem; STR-3 keeps those of no other kind)."""
    sitewide, shared_blocks, teasers = sitewide_prices(pages), blocks_on_most_pages(pages), teaser_blocks(pages)
    products, maybe = {}, []
    for p in pages:
        segments = [fold(s) for s in urlsplit(p.url).path.split("/") if s]
        if p.url == home or not p.analysis or set(segments) & (CATEGORY_WORDS | ARTICLE_FOLDERS):
            continue
        own = [t for t in located_prices(p.analysis, teasers, sitewide, shared_blocks) if t["not_own"] is None]
        if len({t["value"] for t in own}) != 1:  # one amount, however often it is shown
            continue
        control = _buy_control(p)
        if control:
            products[p.url] = f"one price of its own ({own[0]['text']}) and a buy control ({control[:60]})"
        else:
            maybe.append({"url": p.url, "price": own[0]["text"]})
    # A category page whose cards all show the same price looks like one product (H27): a list of products is neither
    # a product page nor a "maybe" one.
    candidates = set(products) | {row["url"] for row in maybe}
    by_url = {p.url: p for p in pages}
    listings = {url: why for url in candidates if (why := listing_reason(by_url[url], candidates))}
    products = {url: why for url, why in products.items() if url not in listings}
    maybe = [row for row in maybe if row["url"] not in listings]
    return {"products": products if len(products) >= PRODUCT_TEMPLATE_MIN_PAGES else {}, "maybe": maybe,
            "listings": listings}


def _finding(check_id, title, severity, confidence, rationale, engines, urls, evidence, expected, fix, key_urls,
             notes=(), cost_tier="T0", sitewide=False) -> Finding:
    return Finding(check_id, title, severity, confidence, rationale, engines, scope_for(urls, sitewide), evidence,
                   expected, fix, cost_tier=cost_tier, notes=list(notes), importance_tier=_tier(urls, key_urls))


# -- prices, ratings, dates -----------------------------------------------------

DOLLAR = {"USD", "CAD", "AUD", "NZD", "SGD", "HKD", "MXN"}
SYMBOLS = [("US$", {"USD"}), ("CA$", {"CAD"}), ("HK$", {"HKD"}), ("NZ$", {"NZD"}), ("R$", {"BRL"}), ("A$", {"AUD"}),
           ("C$", {"CAD"}), ("S$", {"SGD"}), ("$", DOLLAR), ("€", {"EUR"}), ("£", {"GBP"}), ("¥", {"JPY", "CNY"}),
           ("₺", {"TRY"}), ("₹", {"INR"}), ("₽", {"RUB"}), ("₩", {"KRW"})]
WORD_MARKERS = [("zł", {"PLN"}), ("kr", {"SEK", "NOK", "DKK", "ISK"}), ("TL", {"TRY"})]
ISO_CODES = {"USD", "EUR", "GBP", "TRY", "JPY", "CNY", "INR", "CAD", "AUD", "CHF", "SEK", "NOK", "DKK", "PLN", "BRL",
             "MXN", "RUB", "KRW", "NZD", "SGD", "HKD", "ZAR", "AED", "SAR"}
MARKERS = {**{m: c for m, c in SYMBOLS + WORD_MARKERS}, **{c: {c} for c in ISO_CODES}}
_MARK = "|".join([re.escape(m) for m, _ in SYMBOLS] + [rf"(?<![^\W\d_]){re.escape(m)}(?![^\W\d_])" for m, _ in WORD_MARKERS]
                 + [rf"\b{c}\b" for c in sorted(ISO_CODES)])
_NUM = r"\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
# Symbols written before the amount ($, £, ¥, ₩): a number before one of them is its price only when no number follows
# it. In "No. 1 $28.00" the "$" belongs to 28.00, not to 1 (item 11); "28,00 € 30,00 €" still reads as two prices.
_PREFIX_MARK = "|".join(re.escape(m) for m, _ in SYMBOLS if "$" in m or m in ("£", "¥", "₩"))
PRICE_TOKEN = re.compile(rf"(?P<m1>{_MARK})\s?(?P<n1>{_NUM})|(?P<n2>{_NUM})\s?(?:(?P<m2>{_PREFIX_MARK})(?!\s?\d)|"
                         rf"(?!{_PREFIX_MARK})(?P<m3>{_MARK}))")
RATING_TOKEN = re.compile(r"(?<![\d/.,])(\d(?:[.,]\d{1,2})?)\s*(?:/|out of)\s*(5|10|100)(?![\d/])", re.I)


def parse_number(text: str) -> Decimal | None:
    """Visible number in either convention: 1,299.00 / 1.299,00 / 49 / 49,90."""
    s = re.sub(r"[\s  ]", "", text)
    last = max(s.rfind("."), s.rfind(","))
    if last >= 0 and 1 <= len(s) - last - 1 <= 2:
        whole, frac = s[:last], s[last + 1:]
        s = re.sub(r"[.,]", "", whole) + "." + frac
    else:
        s = re.sub(r"[.,]", "", s)
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def schema_number(value) -> Decimal | None:
    """Structured-data number: schema.org asks for '.' as the decimal separator and no thousands separator."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return parse_number(str(value))


def _price_matches(text: str):
    """(token, start, end) for every price in `text`."""
    for m in PRICE_TOKEN.finditer(text):
        marker, number = (m.group("m1"), m.group("n1")) if m.group("m1") else (m.group("m2") or m.group("m3"), m.group("n2"))
        value = parse_number(number)
        if value is not None:
            yield {"text": m.group(0).strip(), "value": value, "currencies": MARKERS.get(marker, set())}, m.start(), m.end()


def price_tokens(text: str) -> list[dict]:
    return [token for token, _, _ in _price_matches(text)]


MONTHS = {name: i for i, names in enumerate(
    [("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
     ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
     ("december", "dec")], start=1) for name in names}
# Turkish month names (B09), each with and without its letters' marks: a page may write "Subat" for "Şubat".
TR_MONTHS = [("ocak",), ("şubat", "subat"), ("mart",), ("nisan",), ("mayıs", "mayis"), ("haziran",), ("temmuz",),
             ("ağustos", "agustos"), ("eylül", "eylul"), ("ekim",), ("kasım", "kasim"), ("aralık", "aralik")]
MONTHS.update({fold(name): i for i, names in enumerate(TR_MONTHS, start=1) for name in names})
# German, French and Spanish (G22): written as a page writes them; looked up folded ("février" is "fevrier").
MONTHS.update({fold(name): i for i, names in enumerate(MONTH_NAMES_MORE, start=1) for name in names})
_MONTH = "|".join(sorted(set(MONTHS) | {name for names in (*TR_MONTHS, *MONTH_NAMES_MORE) for name in names},
                         key=len, reverse=True))
DATE_PATTERNS = [
    ("iso", re.compile(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b")),
    ("mdy", re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+((?:19|20)\d{{2}})\b", re.I)),
    # "3 March 2026", "3. März 2026", "1er mars 2026", "14 de febrero de 2026".
    ("dmy", re.compile(rf"\b(\d{{1,2}})(?:\.|er)?\s+(?:de\s+)?({_MONTH})\.?,?\s+(?:de\s+)?((?:19|20)\d{{2}})\b", re.I)),
    ("dotted", re.compile(r"\b(\d{1,2})\.(\d{1,2})\.((?:19|20)\d{2})\b")),
]
DATE_LABEL = re.compile(r"(published|posted|updated|modified|last updated|last modified|yay[ıi]n(?:lanma)? tarihi|"
                        r"son g[üu]ncelleme|g[üu]ncelleme tarihi|g[üu]ncellendi|" + DATE_LABELS_MORE +
                        r")\s*(?:on|at|le|am|el)?\s*:?\s*$", re.I)
BYLINE = re.compile(r"\b[Bb]y\s+([A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,3})")


def parse_date(value) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if 'T' in value:
        try:
            instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return instant.astimezone(timezone.utc).date() if instant.tzinfo else instant.date()
        except ValueError:
            return None
    m = re.match(r"^((?:19|20)\d{2})-(\d{2})-(\d{2})", value)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).date()
    except (TypeError, ValueError, IndexError):
        return None


def _label_kind(label: str | None) -> str | None:
    if not label:
        return None
    label = fold(label)
    return "modified" if any(word in label for word in ("updated", "modified", "guncelle", "aktualisiert", "mis a jour",
                                                         "actualizado")) else "published"


def visible_dates(analysis: dict) -> list[dict]:
    """Dates a reader sees: <time> elements (any language) and dates in the text (ISO and d.m.y in any language;
    month names and "Published/Updated" labels in English, Turkish, German, French and Spanish)."""
    found = []
    for t in analysis["time_elements"]:
        if t["in_chrome"]:
            continue
        when = parse_date(t["datetime"] or t["text"])
        if when:
            prop = (t["itemprop"] or "").casefold()
            kind = "modified" if prop == "datemodified" else "published" if prop in ("datepublished", "datecreated") else None
            found.append({"date": when, "kind": kind, "source": "<time>", "text": t["datetime"] or t["text"]})
    text = analysis.get("_visible_text", "")
    for name, rx in DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                if name == "iso":
                    when = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif name == "mdy":
                    when = date(int(m.group(3)), MONTHS[fold(m.group(1))], int(m.group(2)))
                elif name == "dmy":
                    when = date(int(m.group(3)), MONTHS[fold(m.group(2))], int(m.group(1)))
                else:
                    when = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
            label = DATE_LABEL.search(text[max(0, m.start() - 40): m.start()])
            found.append({"date": when, "kind": _label_kind(label.group(1) if label else None), "source": "text",
                          "text": text[max(0, m.start() - 20): m.end()].strip()})
    unique: dict[tuple, dict] = {}
    for d in found:  # a <time> and its own text are one date; keep the labeled one
        key = d["date"]
        if key not in unique or (unique[key]["kind"] is None and d["kind"]):
            unique[key] = d
    return list(unique.values())


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


# -- STR-1 ---------------------------------------------------------------------

def site_name(result: CrawlResult) -> str | None:
    home = next((p for p in result.pages if p.url == homepage_url(result) and p.analysis), None)
    if home is None:
        return None
    names = home.analysis["og"].get("og:site_name") or [text_value(n.get("name")) for n in organization_nodes(home.analysis)]
    return next((n for n in names if n), None)


# About what a search result or a source card shows of a title before cutting it.
TITLE_SHOWN_CHARS = 50


def str1_titles(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    title = "Title present and distinctive"
    if not pages:
        return CheckResult("STR-1", title, "not_assessed", "No indexable HTML pages.")
    home, brand = homepage_url(result), _norm(site_name(result))
    missing = [p.url for p in pages if not p.analysis["title"]]
    generic = []
    for p in pages:
        t = _norm(p.analysis["title"])
        if t and (t in GENERIC_TITLES or fold(t) in GENERIC_TITLES or (brand and t == brand and p.url != home)):
            generic.append({"url": p.url, "title": p.analysis["title"],
                            "why": "the site name alone" if t == brand else "a generic placeholder title"})
    generic_urls = {g["url"] for g in generic}
    by_title: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        if p.analysis["title"] and p.url not in generic_urls:  # root cause once: a generic title is reported as generic
            by_title[_norm(p.analysis["title"])].append(p.url)
    duplicates = {t: urls for t, urls in by_title.items() if len(urls) > 1}
    # Titles that differ only after the part a search result or a source card shows: to a reader they are one title.
    by_start: dict[str, list[str]] = defaultdict(list)
    for t, urls in by_title.items():
        if len(t) >= TITLE_SHOWN_CHARS and len(urls) == 1:
            by_start[t[:TITLE_SHOWN_CHARS]].append(urls[0])
    same_start = {start: urls for start, urls in by_start.items() if len(urls) > 1}
    findings = []
    note = [CAPPED + " See spec §8 Q5 for the evidence that could re-evaluate this."]
    if missing:
        findings.append(_finding("STR-1", f"{len(missing)} page(s) have no <title>", Severity.S4, Confidence.VERIFIED,
                                 HYPOTHESIS, CARD_ENGINES, missing, {"pages": missing[:40]},
                                 "every indexable page has a title", "Add a <title> that names the page's topic.",
                                 key_urls, note))
    if duplicates:
        urls = [u for group in duplicates.values() for u in group]
        findings.append(_finding(
            "STR-1", f"{len(duplicates)} title(s) are shared by {len(urls)} different indexable pages", Severity.S4,
            Confidence.VERIFIED, HYPOTHESIS, CARD_ENGINES, urls,
            {"groups": [{"title": next(p.analysis["title"] for p in pages if p.url == g[0]), "urls": g}
                        for g in duplicates.values()][:40]},
            "each page's title is distinct", "Give each page a title that says what is different about it.", key_urls,
            note + ["Pages with noindex or a canonical pointing elsewhere are not counted."]))
    if same_start:
        urls = [u for group in same_start.values() for u in group]
        findings.append(_finding(
            "STR-1", f"{len(urls)} page title(s) begin with the same {TITLE_SHOWN_CHARS} characters as another page's, so they look "
                     "alike where a title is cut short", Severity.S4, Confidence.VERIFIED, HYPOTHESIS, CARD_ENGINES, urls,
            {"groups": [{"shared_start": next(p.analysis["title"] for p in pages if p.url == g[0])[:TITLE_SHOWN_CHARS],
                         "pages": [{"url": u, "title": next(p.analysis["title"] for p in pages if p.url == u)} for u in g]}
                        for g in same_start.values()][:40], "characters_compared": TITLE_SHOWN_CHARS},
            "the first words of each title say what is different about the page",
            "Put what is different first: “Privacy Policy · Brand”, not “Brand's tagline · Privacy Policy”.", key_urls,
            note + [f"The titles are different in full; that their first {TITLE_SHOWN_CHARS} characters are the same is Verified. Search "
                    "results and source cards show about 50 to 60 characters of a title."]))
    if generic:
        urls = [g["url"] for g in generic]
        findings.append(_finding(
            "STR-1", f"{len(urls)} page(s) have a generic title", Severity.S4, Confidence.VERIFIED, HYPOTHESIS,
            CARD_ENGINES, urls, {"pages": generic[:40], "site_name": site_name(result)},
            "a title a user would recognize in a source card", "Name the page's topic in the title.", key_urls,
            note + ["The placeholder list is English plus framework defaults; titles that are only the site name are "
                    "caught in any language. The homepage may be titled with the site name alone."]))
    summary = (f"{len(findings)} finding(s)." if findings
               else f"All {len(pages)} indexable page(s) have distinct, non-generic titles (English placeholder list).")
    return CheckResult("STR-1", title, _status(findings), summary, findings, {"pages_checked": len(pages)})


# -- STR-2 ---------------------------------------------------------------------

HIDDEN_H1_NOTE = ("Hidden by its own markup or an element around it (inline display:none or visibility:hidden, the hidden "
                  "attribute, aria-hidden). A heading hidden by a stylesheet class is seen only on rendered pages.")
# The severity of a hidden homepage <h1> (DECISIONS 284); `reassess_rules` applies it to saved reports.
HOME_HIDDEN_H1_SEVERITY = Severity.S3
HIDDEN_H1_MEDIUM = ("Medium: one reading of the homepage, not re-tested (the second look has no re-test for a hidden "
                    "heading); DECISIONS 284 lowers 258's High.")
SAME_AS_TITLE_NOTE = "The hidden <h1> repeats the page's <title> word for word."

def str2_headings(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str]) -> CheckResult:
    title = "Heading structure for passage extraction"
    checked = [p for p in pages if p.url not in gap]
    if not checked:
        return CheckResult("STR-2", title, "not_assessed", "No indexable pages with content in raw HTML.",
                           evidence={"excluded_as_rnd1_root_cause": sorted(gap)})
    no_h1, long_flat, multi, hidden_h1, cut_off, sections_cut_off = [], [], [], [], [], []
    # What each source showed, kept apart (INV-03): the raw HTML Maya fetched, and the visible <h1> texts of the rendered
    # page ([] when it was rendered and showed none; None when it was not rendered, so unknown). DECISIONS 281, 282.
    h1_sources: dict[str, dict] = {}
    subheadings = question = 0
    rendered = getattr(result.render, "pages", None) or {} if getattr(result, "render", None) is not None else {}
    computed = 0
    from ..evidence_accuracy import heading_state
    for p in checked:
        a = p.analysis
        levels = [h["level"] for h in a["headings"] if h["text"].strip()]
        h1s = [h["text"] for h in a["headings"] if h["level"] == 1 and h["text"].strip()]
        raw_h1s = list(h1s)
        shown = [h["text"] for h in a["headings"] if h["level"] == 1 and h["text"].strip() and not h.get("hidden")]
        hidden_by = "its markup: inline style, the hidden attribute or aria-hidden (on it or an element around it)"
        entry = rendered.get(p.url) or {}
        seen = [v for v in entry.get("h1_visibility") or [] if v.get("text")] if entry.get("ok") else []
        if seen:
            # The browser's computed style on a rendered page wins over the markup: it also sees a stylesheet class.
            computed += 1
            shown = [v["text"] for v in seen if v.get("visible")]
            h1s = h1s or [v["text"] for v in seen]
            hidden_by = "the rendered page's computed style (display, visibility or opacity of it or an element around it)"
        looked = entry.get("ok") and isinstance(entry.get("h1_visibility"), list)
        h1_sources[p.url] = {"url": p.url, "raw_h1": raw_h1s[:3],
                             "rendered_h1": [v["text"] for v in seen if v.get("visible")][:3] if looked else None}
        # An <h1> only the rendered page has is RND-2's finding ("headings ... appear only after JavaScript"); here the
        # page has an <h1> (DECISIONS 282).
        if not h1s and getattr(p, "body_truncated", False) and heading_state(a)["state"] != "empty":
            # The HTML stopped at the fetch-size limit before any <h1> was seen (the rendered page is built from the same
            # cut body): whether the page has one is unknown, not "no <h1>" (DECISIONS 282).
            cut_off.append(p.url)
        elif h1s and not shown:
            # Every <h1> the page has is hidden (H15): said as that, not as "no <h1>" (root cause once).
            title_text = a.get("title") or ""
            hidden_h1.append({"url": p.url, "h1": h1s[:3], "title": title_text or None,
                              "same_as_title": bool(title_text) and any(_norm(h) == _norm(title_text) for h in h1s),
                              "hidden_by": hidden_by})
        elif not h1s:
            no_h1.append(p.url)
        elif len(h1s) > 1:
            multi.append({"url": p.url, "h1": h1s[:5]})
        # Words in the main content when the page marks it up; otherwise all visible words (Estimated either way).
        words = a["visible_words"]
        if a["has_main_region"] and a["visible_chars"]:
            words = round(words * a["main_region_chars"] / a["visible_chars"])
        if words > cfg.long_page_words and not any(level >= 2 for level in levels) and getattr(p, "body_truncated", False):
            # The cut body has no subheading yet; the rest of the page may have them (DECISIONS 283 (8)).
            sections_cut_off.append(p.url)
        elif words > cfg.long_page_words and not any(level >= 2 for level in levels):
            long_flat.append({"url": p.url, "content_words": words, "tables_present": len(a.get("tables") or []),
                              "context": "tables may structure this page" if a.get("tables") else "prose/list structure requires review"})
        for h in a["headings"]:
            if h["level"] in (2, 3):
                subheadings += 1
                question += h["text"].rstrip().endswith(("?", "؟", "？"))
    findings = []
    home = homepage_url(result)
    from ..evidence_accuracy import heading_state
    heading_assessments = [{"url": p.url, **heading_state(p.analysis)} for p in checked]
    if home in no_h1:
        # The homepage is the page that says what the whole site is: without a main heading it is Medium, said on its
        # own, and the other pages stay Low (Owner, 2026-10-12).
        no_h1 = [url for url in no_h1 if url != home]
        if any(r["url"] == home and r["state"] == "empty" for r in heading_assessments):
            # An empty <h1> is its own diagnosis and its own rule (DECISIONS 278, 281), with the same weight.
            findings.append(_finding("STR-2", "The homepage has no meaningful <h1> text", Severity.S3, Confidence.VERIFIED,
                                     HYPOTHESIS, PASSAGE_ENGINES, [home], {"pages": [home], "empty_heading_urls": [home]},
                                     "one <h1> on the homepage with text saying what the site is",
                                     "Fill the homepage's empty <h1> with text that says what the site offers.", key_urls))
        else:
            # Medium by the owner's calibration (DECISIONS 181), so not capped (H12).
            findings.append(_finding("STR-2", "The homepage has no <h1>", Severity.S3, Confidence.VERIFIED,
                                     HYPOTHESIS, PASSAGE_ENGINES, [home], {"pages": [home]},
                                     "one <h1> on the homepage saying what the site is",
                                     "Add one <h1> to the homepage that says what the site offers.", key_urls))
    home_hidden = [row for row in hidden_h1 if row["url"] == home]
    other_hidden = [row for row in hidden_h1 if row["url"] != home]
    if home_hidden:
        row = home_hidden[0]
        # Medium (DECISIONS 284, which lowers 258's High): one reading of the page's markup or computed style, and the
        # second look has no re-test for it (verification.RETESTS), so it is never re-tested.
        findings.append(_finding(
            "STR-2", "The homepage's only <h1> is hidden", HOME_HIDDEN_H1_SEVERITY, Confidence.VERIFIED, HEADINGS_DOCUMENTED, PASSAGE_ENGINES,
            [home], {"pages": home_hidden}, "one visible <h1> on the homepage saying what the site is",
            "Show the homepage's <h1> (remove display:none, the hidden attribute or aria-hidden), or replace it with a visible "
            "<h1> that says what the site offers.", key_urls,
            [HIDDEN_H1_NOTE, HIDDEN_H1_MEDIUM] + ([SAME_AS_TITLE_NOTE] if row["same_as_title"] else [])))
    # The homepage's outline (DECISIONS 258): a homepage with real text but almost no visible section headings, or with
    # a question block whose questions are plain text, gives a reader moving by headings and a machine reading the
    # outline nothing to hold on to. High on the homepage by the owner's decision.
    home_page = next((p for p in checked if p.url == home), None)
    if home_page is not None:
        a = home_page.analysis
        visible_sub = [h for h in a["headings"] if h["level"] in (2, 3) and h["text"].strip() and not h.get("hidden")]
        plain_questions = questions_not_headings(a)
        short = len(visible_sub) < cfg.homepage_min_subheadings and (a["visible_words"] >= cfg.homepage_outline_min_words
                                                                     or plain_questions)
        if short and getattr(home_page, "body_truncated", False):
            # Counted on the part of the HTML read before the fetch-size limit: the rest may hold the headings
            # (DECISIONS 283 (8)). Not assessed, not "N visible section headings".
            if home not in sections_cut_off:
                sections_cut_off.append(home)
        elif short:
            findings.append(_finding(
                "STR-2", f"The homepage has {len(visible_sub)} visible section heading(s) for {a['visible_words']} words",
                Severity.S2, Confidence.VERIFIED, HEADINGS_DOCUMENTED, PASSAGE_ENGINES, [home],
                {"pages": [{"url": home, "visible_h2_h3": [h["text"] for h in visible_sub][:10],
                            "visible_words": a["visible_words"], "questions_not_headings": plain_questions[:10]}],
                 "minimum_subheadings": cfg.homepage_min_subheadings, "minimum_words": cfg.homepage_outline_min_words},
                "the homepage's sections and questions marked as <h2>/<h3> headings",
                "Mark each homepage section title as an <h2> and each question in its question block as an <h3> (or an "
                "accordion's <summary>), instead of styled <div>/<span> text.", key_urls,
                ["High on the homepage by the owner's decision (DECISIONS 258); the thresholds are policy."]))
    if other_hidden:
        urls = [row["url"] for row in other_hidden]
        findings.append(_finding(
            "STR-2", f"{len(urls)} page(s) have only a hidden <h1>", Severity.S4, Confidence.VERIFIED, HYPOTHESIS,
            PASSAGE_ENGINES, urls, {"pages": other_hidden[:40]}, "one visible <h1> naming the page topic",
            "Show the <h1> (remove display:none, the hidden attribute or aria-hidden), or replace it with a visible <h1> "
            "that names the page's topic.", key_urls,
            [CAPPED, HIDDEN_H1_NOTE] + ([SAME_AS_TITLE_NOTE] if any(r["same_as_title"] for r in other_hidden) else [])))
    if no_h1:
        findings.append(_finding("STR-2", f"{len(no_h1)} page(s) have no <h1>", Severity.S4, Confidence.VERIFIED,
                                 HYPOTHESIS, PASSAGE_ENGINES, no_h1, {"pages": no_h1[:40]},
                                 "one <h1> naming the page topic", "Add one <h1> that names the page's topic.",
                                 key_urls, [CAPPED]))
    if long_flat:
        urls = [r["url"] for r in long_flat]
        findings.append(_finding(
            "STR-2", f"{len(urls)} long page(s) (>{cfg.long_page_words} words) have no subheadings", Severity.S4,
            Confidence.VERIFIED, HYPOTHESIS, PASSAGE_ENGINES, urls, {"pages": long_flat[:40]},
            "sections with <h2>/<h3> headings", "Split the page into sections with descriptive <h2>/<h3> headings.",
            key_urls, [CAPPED, "Word count is of the <main>/<article> text when present, else all visible text."]))
    if multi:
        urls = [r["url"] for r in multi]
        findings.append(_finding("STR-2", f"{len(urls)} page(s) have more than one <h1>", Severity.INFO,
                                 Confidence.VERIFIED, HYPOTHESIS, PASSAGE_ENGINES, urls, {"pages": multi[:40]},
                                 "one <h1>", "Keep one <h1>; demote the others to <h2>.", key_urls))
    # No <h1> and an empty <h1> are two diagnoses with two fixes (DECISIONS 278): pages with an empty one get their own
    # finding, so a card never tells 69 pages to "fill the empty <h1>" when they have none.
    for f in list(findings):
        members = set(f.scope.get('_all_urls') or f.scope.get('urls') or [])
        rows = [r for r in heading_assessments if r['url'] in members]
        f.evidence['heading_assessments'] = rows
        empty = [r['url'] for r in rows if r['state'] == 'empty']
        if f.title.startswith("The homepage"):
            continue  # the homepage's empty <h1> is its own finding above
        if empty and 'no <h1>' in f.title:
            absent = [u for u in f.scope.get('_all_urls') or f.scope.get('urls') or [] if u not in set(empty)]
            if absent:
                f.title, f.evidence['pages'] = f"{len(absent)} page(s) have no <h1>", absent[:40]
                f.scope = scope_for(absent)
                f.evidence['heading_assessments'] = [r for r in rows if r['url'] in set(absent)]
            findings.append(_finding(
                "STR-2", f"{len(empty)} page(s) have an empty <h1>", Severity.S4, Confidence.VERIFIED, HYPOTHESIS,
                PASSAGE_ENGINES, empty, {"pages": empty[:40], "heading_assessments": [r for r in rows if r['url'] in set(empty)],
                                         "empty_heading_urls": empty},
                "one <h1> naming the page topic", "Fill the empty <h1> with text that names the page's topic.",
                key_urls, [CAPPED]))
            if not absent:
                findings.remove(f)
    for f in findings:  # after the empty-<h1> split, so every heading finding says what each source showed
        if "<h1>" in f.title:
            members = f.scope.get('_all_urls') or f.scope.get('urls') or []
            f.evidence['h1_sources'] = [h1_sources[u] for u in sorted(members) if u in h1_sources]
    observations = [{"metric": "share of <h2>/<h3> phrased as questions (recorded, not judged)",
                     "value": round(question / subheadings, 3) if subheadings else None,
                     "question_headings": question, "subheadings": subheadings}]
    # P4: a question-and-answer block whose questions are plain text (not headings, links, <summary> or <dt>).
    unmarked = [{"url": p.url, "questions": len(qs), "first_questions": qs[:3]}
                for p in checked for qs in [questions_not_headings(p.analysis)] if qs and not narrative_questions(p.analysis)]
    if unmarked:
        observations.append({"metric": QUESTIONS_NOT_HEADINGS, "pages": len(unmarked), "examples": unmarked[:5],
                             "note": "Mark each question as a heading (<h3>) or an accordion's <summary>, so a reader "
                                     "moving by headings and a machine reading the outline find it."})
    # A page cut off before any <h1> is not counted as checked here; coverage lists it (DECISIONS 282).
    summary = f"{len(findings)} finding(s)." if findings else f"All {len(checked) - len(cut_off)} page(s) have one <h1> and long pages are sectioned."
    if sections_cut_off and not findings:
        summary = (f"All {len(checked) - len(cut_off)} page(s) have one <h1>; {len(sections_cut_off)} page(s) were cut off "
                   "before their section headings could be counted.")
    return CheckResult("STR-2", title, _status(findings), summary, findings,
                       {"pages_checked": len(checked), "heading_assessments": heading_assessments, "excluded_as_rnd1_root_cause": sorted(gap),
                        "h1_cut_off": cut_off[:40], "h1_cut_off_count": len(cut_off),
                        "sections_cut_off": sections_cut_off[:40], "sections_cut_off_count": len(sections_cut_off),
                        "not_measured": "whether the <h1> matches the page topic",
                        "hidden_h1_assessed_by": {"rendered_computed_style": computed, "markup_only": len(checked) - computed,
                                                  "markup_only_limit": "an <h1> hidden by a stylesheet class is not seen "
                                                                       "without rendering"}}, observations)


# -- STR-3 ---------------------------------------------------------------------

# Required properties from Google's rich result docs for a few more types (B11). LocalBusiness is matched with its
# common subtypes only; a rarer subtype is not checked (not a pass: the note says which types were checked).
LOCAL_BUSINESS_TYPES = {"LocalBusiness", "Restaurant", "Store", "Dentist", "MedicalClinic", "Hotel", "CafeOrCoffeeShop",
                        "AutoRepair", "BeautySalon", "RealEstateAgent", "LegalService", "FoodEstablishment"}
MORE_REQUIRED = (({"Event"}, ("name", "startDate", "location")), ({"Recipe"}, ("name", "image")),
                 ({"VideoObject"}, ("name", "thumbnailUrl", "uploadDate")), (LOCAL_BUSINESS_TYPES, ("name", "address")),
                 ({"JobPosting"}, ("title", "description", "datePosted", "hiringOrganization")))
# A video name that names nothing: what a theme or plugin writes when the field is left to its default.
PLACEHOLDER_VIDEO_NAMES = {"video", "videos", "untitled", "başlıksız", "youtube video", "embedded video",
                           *PLACEHOLDER_VIDEO_NAMES_MORE, *(fold(name) for name in PLACEHOLDER_VIDEO_NAMES_MORE)}


# DECISIONS 261: values Google documents a format for, written in a form it cannot read (seen live on Carpex: a rating
# "4,38", a key "reviewCount " with a trailing space, a currency "try").
_ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")
_COMMA_DECIMAL = re.compile(r"^\s*\d+(?:\.\d{3})*,\d+\s*$")  # 4,38 and 1.299,90 (Turkish style)
_NUMBER = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*(?:%|/\s*\d+(?:\.\d+)?)?\s*$")
VALUE_DOCUMENTED = ("Documented (Google rich result docs: priceCurrency in three-letter ISO 4217 format, a period as the "
                    "decimal separator, ratingValue a number; schema.org property names are exact)")


def _invalid_values(node: dict) -> list[dict]:
    """Problems with values (not presence) on one typed node: each {"property", "value", "problem"}."""
    out = []
    for key in node:
        if isinstance(key, str) and key != key.strip() and key.strip():
            out.append({"property": key, "value": None, "problem": "property name has spaces around it, so it is "
                                                                   f"not '{key.strip()}'"})
    types = set(node_types(node))

    def scalar(name):
        value = node.get(name)
        return value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None

    if types & {"AggregateRating", "Rating"}:
        for name in ("ratingValue", "bestRating", "worstRating"):
            value = scalar(name)
            if isinstance(value, str) and value.strip():
                if _COMMA_DECIMAL.match(value):
                    out.append({"property": name, "value": value, "problem": "comma used as the decimal separator"})
                elif not _NUMBER.match(value):
                    out.append({"property": name, "value": value, "problem": "not a number"})
        try:
            rating, best = float(str(scalar("ratingValue"))), float(str(scalar("bestRating") or 5))
            if rating > best:
                out.append({"property": "ratingValue", "value": scalar("ratingValue"),
                            "problem": f"above bestRating ({scalar('bestRating') or 5})"})
        except ValueError:
            pass
    if types & {"Offer", "AggregateOffer", "PriceSpecification", "UnitPriceSpecification"}:
        currency = scalar("priceCurrency")
        if isinstance(currency, str) and currency.strip() and not _ISO_CURRENCY.match(currency.strip()):
            out.append({"property": "priceCurrency", "value": currency,
                        "problem": "not a three-letter upper-case ISO 4217 code"})
        for name in ("price", "lowPrice", "highPrice"):
            value = scalar(name)
            if isinstance(value, str) and _COMMA_DECIMAL.match(value):
                out.append({"property": name, "value": value, "problem": "comma used as the decimal separator"})
    return out


def _missing_required(node: dict, nested: bool) -> list[str]:
    """Google-documented required properties (product snippet, review snippet, breadcrumb, event, recipe, video,
    local business and job posting docs)."""
    types = set(node_types(node))
    missing = []

    def empty(key, obj=node):
        return obj.get(key) in (None, "", [], {})

    for kinds, keys in MORE_REQUIRED:
        if types & kinds:
            missing += [k for k in keys if empty(k) and k not in missing]
    if "JobPosting" in types and all(empty(k) for k in ("jobLocation", "applicantLocationRequirements")):
        missing.append("jobLocation (or applicantLocationRequirements for a remote job)")
    if types & PRODUCT_TYPES:
        if not text_value(node.get("name")):
            missing.append("name")
        if all(empty(k) for k in ("offers", "review", "aggregateRating")):
            missing.append("one of offers / review / aggregateRating")
    if "Offer" in types:
        spec = node.get("priceSpecification")
        if empty("price") and not (isinstance(spec, dict) and not empty("price", spec)):
            missing.append("price (or priceSpecification.price)")
    if "AggregateOffer" in types:
        missing += [k for k in ("lowPrice", "priceCurrency") if empty(k)]
    if "AggregateRating" in types:
        if empty("ratingValue"):
            missing.append("ratingValue")
        if empty("ratingCount") and empty("reviewCount"):
            missing.append("ratingCount or reviewCount")
        if not nested and empty("itemReviewed"):
            missing.append("itemReviewed")
    if "Review" in types:
        missing += [k for k in ("author", "reviewRating") if empty(k)]
        if not nested and empty("itemReviewed"):
            missing.append("itemReviewed")
    if "BreadcrumbList" in types:
        elements = [e for e in as_list(node.get("itemListElement")) if isinstance(e, dict)]
        if not elements:
            missing.append("itemListElement")
        for i, element in enumerate(elements):
            item = element.get("item")
            if empty("position", element):
                missing.append(f"itemListElement[{i}].position")
            if empty("name", element) and not (isinstance(item, dict) and item.get("name")):
                missing.append(f"itemListElement[{i}].name")
            if i < len(elements) - 1 and empty("item", element):
                missing.append(f"itemListElement[{i}].item")
    return missing


def _video_placeholder(node: dict, audit_day: date | None) -> list[str]:
    """Why a VideoObject looks like an unfilled default (H31): a name that names nothing (in any of the listed
    languages). An uploadDate on the audit day, which is what a template writes when it stamps the request date
    instead of the video's, counts only beside such a name or a missing thumbnail (G20): a news site's video really
    published today, with its own name and thumbnail, is not a default."""
    why = []
    name = text_value(node.get("name")) or ""
    if name.strip().casefold() in PLACEHOLDER_VIDEO_NAMES or fold(name.strip()) in PLACEHOLDER_VIDEO_NAMES:
        why.append(f'name is "{name.strip()}"')
    uploaded = text_value(node.get("uploadDate")) if isinstance(node.get("uploadDate"), str) else None
    no_thumbnail = node.get("thumbnailUrl") in (None, "", [], {})
    if audit_day and uploaded and uploaded[:10] == audit_day.isoformat() and (why or no_thumbnail):
        why.append(f"uploadDate {uploaded} is the audit day")
    return why


PARSE_NOTE = ("Each block that does not parse is listed with the parser's error, its line, column and character position "
              "within the block, the character there, and an excerpt with control characters written out.")
FAQ_RICH_RESULTS_NOTE = (
    "FAQPage: Since August 2023 Google shows FAQ rich results only for authoritative government and health "
    "sites; the type can still describe the page.")
QA_NOTE = ("Estimated from punctuation: at least three short blocks of the page's own content that end with a question "
           "mark, each followed by an answer, with no long section between them.")
CRUMB_NOTE = ("Estimated: an element whose class, id or aria-label says breadcrumb, with at least two steps and one "
              "link.")
# P2: the homepage's WebSite node is where Google reads the site's name (site names documentation).
WEBSITE_MISSING = "homepage with no WebSite structured data"
WEBSITE_NOTE = ("Google reads the site name shown in results from WebSite structured data on the homepage; it is a "
                "description of the site, not a ranking factor.")


def _parse_place(block: dict) -> str | None:
    """'line 1, column 472 (char 471): newline (U+000A) inside "streetAddress"', from a block `_jsonld` reported."""
    if block.get("line") is None:
        return None
    inside = f' inside "{block["in_property"]}"' if block.get("in_property") else ""
    return f'line {block["line"]}, column {block["column"]} (char {block["char_position"]}): {block["character"]}{inside}'


# P2: a block of questions and answers on the page, told by punctuation alone (any language): at least QA_MIN_PAIRS
# short blocks that end with a question mark, each followed by an answer that is not a question, with no more than
# QA_MAX_ANSWER_CHARS of text from one question to the next. An article whose question subheadings open long sections
# is not one. (Measured live on a shop's FAQ: answers of 84 to 1,200 characters, steps lists included.)
QUESTION_MARKS = ("?", "؟", "？")
QUESTIONS_NOT_HEADINGS = "pages whose question-and-answer block writes its questions as plain text"
QA_MIN_PAIRS = 3
QA_QUESTION_MAX_CHARS = 200
QA_ANSWER_MIN_CHARS = 20
QA_MAX_ANSWER_CHARS = 1500


def _qa_run(analysis: dict) -> list[int]:
    """The positions in _content_blocks of the questions of the longest run of question-and-answer pairs in the page's
    own content (header, navigation, footer and sidebar left out), when it has at least QA_MIN_PAIRS; else []."""
    blocks = [b.strip() for b in analysis.get("_content_blocks") or []]

    def question(text: str) -> bool:
        return 0 < len(text) <= QA_QUESTION_MAX_CHARS and text.endswith(QUESTION_MARKS)

    best: list[int] = []
    run: list[int] = []
    since = 0  # characters of answer text since the run's last question
    for i, text in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else ""
        if question(text) and len(nxt) >= QA_ANSWER_MIN_CHARS and not question(nxt):
            if since > QA_MAX_ANSWER_CHARS:
                run = []
            run.append(i)
            since = 0
            if len(run) > len(best):
                best = list(run)
        else:
            since += len(text)
    return best if len(best) >= QA_MIN_PAIRS else []


def qa_block(analysis: dict) -> list[str]:
    """The questions of the page's question-and-answer block (`_qa_run`), or []."""
    blocks = analysis.get("_content_blocks") or []
    return [blocks[i].strip()[:QA_QUESTION_MAX_CHARS] for i in _qa_run(analysis)]


def questions_not_headings(analysis: dict) -> list[str]:
    """P4: the questions of the page's question-and-answer block written as plain text, when all of them are: not a
    heading, not a link or button, not an accordion's <summary> or a <dt>. A reader using headings to move through the
    page, and a machine reading its outline, do not see them as questions."""
    run = _qa_run(analysis)
    blocks = analysis.get("_content_blocks") or []
    kinds = analysis.get("_content_block_kinds") or []
    toggles = analysis.get("_content_block_toggles") or []
    plain = [i for i in run if i < len(kinds) and kinds[i] == "text" and not (i < len(toggles) and toggles[i])]
    return [blocks[i].strip()[:QA_QUESTION_MAX_CHARS] for i in plain] if run and len(plain) == len(run) else []


def narrative_questions(analysis: dict) -> bool:
    """FA-037: an article whose questions are all plain running text (a story's dialogue, an interview) has no question-
    and-answer block: neither FAQPage nor "questions not marked as headings" is asked of it. Questions marked as headings,
    accordion toggles or <dt> are still read as a Q&A block."""
    og_type = ((analysis.get("og") or {}).get("og:type") or [""])[0].casefold()
    article = bool(ARTICLE_TYPES & set((analysis.get("structured_data") or {}).get("types") or [])) or og_type == "article"
    return article and bool(questions_not_headings(analysis))


def organization_gaps(analysis: dict) -> list[str]:
    """The recommended Organization properties (logo, sameAs) no Organization node on the page has."""
    nodes = organization_nodes(analysis)
    return [key for key in ("logo", "sameAs") if nodes and not any(node.get(key) not in (None, "", [], {}) for node in nodes)]


PAGE_ENTITY_TYPES = ARTICLE_TYPES | PRODUCT_TYPES | {"WebPage", "AboutPage", "ContactPage", "FAQPage", "ItemPage",
                                                     "CollectionPage", "ProfilePage", "QAPage", "SearchResultsPage"}


def id_key(ident: str, base: str) -> str:
    """An @id resolved against the page, fragment kept. normalize_url drops fragments (they never reach a
    server), but in JSON-LD the fragment is the identity: "/#org" and "/#jane" are different entities."""
    return urljoin(base, ident.strip())


def _id_of(node) -> str | None:
    return node["@id"].strip() if isinstance(node, dict) and isinstance(node.get("@id"), str) and node["@id"].strip() \
        else None


def _references(value, out: list) -> None:
    """Every bare {"@id": ...} reference (an object with nothing but @id) under a node."""
    if isinstance(value, dict):
        if set(value) == {"@id"} and _id_of(value):
            out.append(value["@id"].strip())
            return
        for key, child in value.items():
            if key != "@context":
                _references(child, out)
    elif isinstance(value, list):
        for child in value:
            _references(child, out)


def graph_integrity(result: CrawlResult, pages: list) -> dict:
    """Links inside the structured data, across every readable page the crawl fetched.

    - a reference ({"@id": X}) that no crawled page defines (a node with that @id and a @type);
    - one @id given different @types in different places;
    - a page-level node whose `url` names a different same-origin URL than the page's canonical (or the page
      itself), and whether that URL answered 200 when the crawl fetched it.
    """
    from ..index_data import effective_canonical

    defined: dict[str, set[str]] = defaultdict(set)
    where: dict[str, set[str]] = defaultdict(set)
    refs: list[tuple[str, str]] = []
    for p in result.pages:
        if not p.analysis:
            continue
        for item in p.analysis.get("_structured_items", []):
            for node, _ in iter_typed_nodes(item["data"]):
                ident = _id_of(node)
                if ident:
                    key = id_key(ident, p.url)
                    defined[key].update(node_types(node))
                    where[key].add(p.url)
            found: list[str] = []
            _references(item["data"], found)
            refs += [(p.url, id_key(r, p.url)) for r in found]
    page_urls = {p.url for p in pages}
    dangling = sorted({(u, r) for u, r in refs if r not in defined and u in page_urls})
    type_clash = [{"@id": k, "types": sorted(v), "on_pages": sorted(where[k])[:5]} for k, v in defined.items()
                  if len({t for t in v if t in PAGE_ENTITY_TYPES | CLASH_ORGANIZATION_TYPES | {"WebSite", "Person"}}) > 1]
    by_url = {p.url: p for p in result.pages}
    url_mismatch, url_broken = [], []
    for p in pages:
        chosen, _, _ = effective_canonical(p)
        own = chosen or p.url
        for node, nested in _typed_nodes(p.analysis):
            if nested or not (set(node_types(node)) & PAGE_ENTITY_TYPES):
                continue
            declared = text_value(node.get("url")) if isinstance(node.get("url"), str) else None
            target = normalize_url(declared, p.url) if declared else None
            if not target or origin_of(target) != result.origin or target == own:
                continue
            fetched = by_url.get(target)
            row = {"url": p.url, "type": node_types(node), "markup_url": target, "page_canonical": own,
                   "markup_url_status": fetched.status if fetched else None}
            (url_broken if fetched and fetched.status and fetched.status >= 400 else url_mismatch).append(row)
    return {"dangling": [{"url": u, "reference": r} for u, r in dangling], "type_clash": type_clash,
            "url_mismatch": url_mismatch, "url_broken": url_broken}


def str3_structured_data(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    title = "Structured data: present, parseable, and typed"
    if not pages:
        return CheckResult("STR-3", title, "not_assessed", "No indexable HTML pages.")
    home = homepage_url(result)
    parse_errors, required, expected_missing, type_counts = [], [], [], Counter()
    home_page = next((p for p in pages if p.url == home), None)
    template = product_template(pages, home)
    maybe_products, videos, qa_pages, crumb_pages, invalid_values = [], [], [], [], []
    started = getattr(result, "started_at", None)
    audit_day = datetime.fromisoformat(started).astimezone(timezone.utc).date() if started else None
    for p in pages:
        a = p.analysis
        sd = a["structured_data"]
        type_counts.update(sd["types"])
        bad = [b for b in sd["jsonld_blocks"] if not b["ok"]]
        if bad:
            parse_errors.append({"url": p.url, "blocks": bad[:5]})
        for node, nested in _typed_nodes(a):
            missing = _missing_required(node, nested)
            if missing:
                required.append({"url": p.url, "type": node_types(node), "missing": missing})
            wrong = _invalid_values(node)
            if wrong:
                invalid_values.append({"url": p.url, "type": node_types(node), "problems": wrong[:10]})
            why = _video_placeholder(node, audit_day) if "VideoObject" in node_types(node) else []
            if why:
                videos.append({"url": p.url, "name": text_value(node.get("name")), "uploadDate": node.get("uploadDate"),
                               "why": why})
        kind, basis = page_kind(p, home, template["products"])
        if kind in EXPECTED_TYPES and kind != "homepage" and not (EXPECTED_TYPES[kind] & _types(a)):
            expected_missing.append({"url": p.url, "page_kind": kind, "classified_by": basis,
                                     "expected_one_of": sorted(EXPECTED_TYPES[kind]), "types_found": sd["types"]})
        # P2: what the page shows, not its address: a run of questions and answers, a breadcrumb trail.
        recovered = {t for b in sd["jsonld_blocks"] for t in b.get("recovered_types") or []}
        questions = qa_block(a) if kind != "faq" and not narrative_questions(a) else []
        if questions and not ({"FAQPage", "QAPage"} & (_types(a) | recovered)):
            qa_pages.append({"url": p.url, "questions": len(questions), "first_questions": questions[:3],
                             "types_found": sd["types"]})
        trail = (a.get("breadcrumbs") or [None])[0]
        if trail and "BreadcrumbList" not in _types(a) | recovered:
            crumb_pages.append({"url": p.url, "trail": trail["text"], "links": trail["links"], "types_found": sd["types"]})
        shown = next((row["price"] for row in template["maybe"] if row["url"] == p.url), None)
        if shown and kind is None and not (PRODUCT_TYPES & _types(a)):
            maybe_products.append({"url": p.url, "price_shown": shown, "types_found": sd["types"]})
    findings = []
    doc = "Documented (Google: structured data is not required for AI features and must match visible content) / Hypothesis (AI benefit)"
    # The homepage's Organization, in one of three states (H11): absent, present in a block that does not parse, or
    # present and parsed. A broken block that holds the Organization is reported once, as that, and not again among
    # the blocks that do not parse.
    broken_organization, also_on = [], []
    if home_page is not None and not (ORGANIZATION_TYPES & _types(home_page.analysis)):
        broken_organization = [b for b in home_page.analysis["structured_data"]["jsonld_blocks"]
                               if not b["ok"] and ORGANIZATION_TYPES & set(b.get("recovered_types") or [])]
        if broken_organization:
            # The same broken block printed by the template on other pages (the same error at the same place, seen
            # live on a language version of the homepage) is the same fix: said with the homepage's finding.
            same_error = {(b.get("error"), b.get("snippet")) for b in broken_organization}
            for row in parse_errors:
                kept = [b for b in row["blocks"] if b not in broken_organization
                        and (b.get("error"), b.get("snippet")) not in same_error]
                if row["url"] != home and len(kept) < len(row["blocks"]):
                    also_on.append(row["url"])
                row["blocks"] = kept
            parse_errors = [row for row in parse_errors if row["blocks"]]
    if parse_errors:
        urls = [r["url"] for r in parse_errors]
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) have JSON-LD that does not parse", Severity.S4, Confidence.VERIFIED, doc,
            SD_ENGINES, urls, {"pages": parse_errors[:40]}, "every JSON-LD block is valid JSON",
            "Fix the JSON syntax shown in the snippet; a block that does not parse is ignored entirely.", key_urls,
            [CAPPED, PARSE_NOTE]))
    if broken_organization:
        # Severity as for a homepage with no Organization (DECISIONS 181): engines ignore a block that does not parse.
        first = broken_organization[0]
        # P2: the recommended properties the block lacks even once it parses (read from the lenient parse), so the
        # fix can add them too. Evidence only: a client report says it with the fix (the printed report is unchanged).
        recovered_props = {k for b in broken_organization for k in b.get("recovered_properties") or []}
        still_lacking = [key for key in ("logo", "sameAs") if key not in recovered_props]
        # High (DECISIONS 258): the site's identity block is unreadable on the page that says who the site is.
        findings.append(_finding(
            "STR-3", "The homepage's Organization block does not parse", Severity.S2, Confidence.VERIFIED, doc,
            SD_ENGINES, [home, *also_on], {"blocks": broken_organization[:5], "where": _parse_place(first),
                                           "types_found": home_page.analysis["structured_data"]["types"],
                                           "same_block_also_on": also_on,
                                           "recommended_still_lacking": still_lacking},
            "the homepage's Organization block is valid JSON",
            "Fix the existing Organization block where the parser stops (line, column and excerpt in the evidence): a line "
            "break or control character inside a quoted value must be removed or escaped. Do not add a second "
            "Organization block.", key_urls,
            ["Engines ignore a JSON-LD block that does not parse, so this Organization is not read at all.",
             "That the block describes an Organization is read from a lenient parse (control characters allowed); the "
             "parse error itself is Verified.", PARSE_NOTE]))
    elif home_page is not None and not (ORGANIZATION_TYPES & _types(home_page.analysis)):
        broken = any(not b["ok"] for b in home_page.analysis["structured_data"]["jsonld_blocks"])
        # Medium by the owner's calibration (DECISIONS 181), so not capped (H12, CR-08).
        findings.append(_finding(
            "STR-3", "The homepage has no Organization structured data", Severity.S3, Confidence.VERIFIED, doc,
            SD_ENGINES, [home], {"types_found": home_page.analysis["structured_data"]["types"],
                                 "recognized_organization_types": sorted(ORGANIZATION_TYPES)},
            "Organization (or a subtype) with name, logo, and sameAs on the homepage",
            "Add Organization JSON-LD to the homepage with the brand name, logo, url, and sameAs profile links.",
            key_urls, ["Also covers STR-5's 'missing Organization schema' (reported once, here)."]
            + (["The homepage has a JSON-LD block that does not parse; Organization may be inside it."] if broken else [])))
    elif home_page is not None:
        lacking = organization_gaps(home_page.analysis)
        if lacking:
            findings.append(_finding(
                "STR-3", f"The homepage's Organization structured data has no {' or '.join(lacking)}", Severity.INFO,
                Confidence.VERIFIED, doc, SD_ENGINES, [home], {"missing": lacking,
                                                               "types_found": home_page.analysis["structured_data"]["types"]},
                "Organization with name, logo, and sameAs on the homepage",
                "Add the missing properties to the existing Organization block: logo (an image URL) and sameAs (the "
                "brand's official profile addresses).", key_urls,
                ["Google lists logo and sameAs as recommended, not required, for Organization."]))
    observations = []
    if home_page is not None:
        # P2: the homepage has no WebSite node, parsed or in a block that does not parse. An observation, not a
        # finding: most healthy sites leave it out (as twitter:card, G13); a client report may still raise it.
        home_recovered = {t for b in home_page.analysis["structured_data"]["jsonld_blocks"]
                          for t in b.get("recovered_types") or []}
        if "WebSite" not in _types(home_page.analysis) | home_recovered:
            observations.append({"metric": WEBSITE_MISSING, "pages": 1, "examples": [home],
                                 "types_found": home_page.analysis["structured_data"]["types"], "note": WEBSITE_NOTE})
    if required:
        urls = sorted({r["url"] for r in required})
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) have structured data missing Google-required properties", Severity.INFO,
            Confidence.VERIFIED, "Documented (Google rich result docs: items missing required properties are not "
                                 "eligible for rich results)", SD_ENGINES, urls, {"items": required[:60]},
            "required properties present", "Add the missing properties listed per item.", key_urls,
            ["Checked for Product, Offer, AggregateOffer, AggregateRating, Review, BreadcrumbList, Event, Recipe, "
             "VideoObject, JobPosting and LocalBusiness with its common subtypes (the types whose Google docs list "
             "required properties; Article and Organization have none)."]))
    if invalid_values:
        urls = sorted({r["url"] for r in invalid_values})
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) have structured data values in a form Google cannot read", Severity.S3,
            Confidence.VERIFIED, VALUE_DOCUMENTED, SD_ENGINES, urls, {"items": invalid_values[:60]},
            "numbers with a period as the decimal separator, exact property names, ISO 4217 currency codes",
            "Correct each value listed per item in the template that prints the structured data: a period in numbers "
            "(4.38, not 4,38), property names without spaces, and the currency in capitals (TRY).", key_urls,
            ["Verified from the markup. A value Google cannot read leaves the item without the rating or price it "
             "describes; the visible page is unaffected."]))
    if videos:
        urls = sorted({r["url"] for r in videos})
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) have a VideoObject that looks like an unfilled default", Severity.INFO,
            Confidence.ESTIMATED, doc, SD_ENGINES, urls, {"items": videos[:60], "audit_day": audit_day and audit_day.isoformat()},
            "the video's own title and its real upload date",
            "Write the video's real title in name and the date it was first published in uploadDate.", key_urls,
            ["A name such as \"Video\", or an uploadDate equal to the audit day, is what a template writes when the "
             "fields are left to their default; the actual upload date is not known to the audit."]))
    if expected_missing:
        urls = [r["url"] for r in expected_missing]
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) lack the structured data type expected for their page kind", Severity.INFO,
            Confidence.ESTIMATED, doc, SD_ENGINES, urls, {"pages": expected_missing[:40]},
            "a type that describes the page", "Add the structured data type that matches the page's content.", key_urls,
            [KIND_NOTE]
            + ([FAQ_RICH_RESULTS_NOTE] if any(r["page_kind"] == "faq" for r in expected_missing) else [])))
    if qa_pages:
        urls = [r["url"] for r in qa_pages]
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) show questions and answers but have no FAQPage structured data", Severity.INFO,
            Confidence.ESTIMATED, doc, SD_ENGINES, urls, {"pages": qa_pages[:40],
                                                          "rule": {"min_pairs": QA_MIN_PAIRS,
                                                                   "max_answer_chars": QA_MAX_ANSWER_CHARS}},
            "FAQPage structured data that matches the questions and answers shown",
            "Check that the block is the page's own questions and answers; if so, describe them with FAQPage "
            "structured data whose text matches what the page shows.", key_urls,
            [QA_NOTE, FAQ_RICH_RESULTS_NOTE]))
    if crumb_pages:
        urls = [r["url"] for r in crumb_pages]
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) show a breadcrumb trail but have no BreadcrumbList structured data",
            Severity.INFO, Confidence.ESTIMATED, doc, SD_ENGINES, urls, {"pages": crumb_pages[:40]},
            "BreadcrumbList structured data that matches the trail shown",
            "Describe the breadcrumb trail the page shows with BreadcrumbList structured data (one ListItem per step, "
            "in order).", key_urls, [CRUMB_NOTE]))
    if len(maybe_products) >= PRODUCT_TEMPLATE_MIN_PAGES:
        # A price and no buy button: perhaps a product page, perhaps a service or a menu. A note, never a problem
        # (the owner's answer of 2026-10-15, DECISIONS 229).
        urls = [r["url"] for r in maybe_products]
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) show one price and no buy button: they may be product pages, check",
            Severity.INFO, Confidence.ESTIMATED, doc, SD_ENGINES, urls, {"pages": maybe_products[:40]},
            "a product page says it is one in its structured data",
            "Check these pages: if they sell one product, add Product structured data with an Offer; if not, nothing is needed.",
            key_urls, ["Estimated: each page shows exactly one price of its own (in its main content) and no buy button or "
                       "link (such as \u201cAdd to cart\u201d or \u201cSepete ekle\u201d); a product page is taken for one only "
                       "with a buy button."]))
    graph = graph_integrity(result, pages)
    from ..models import StopReason
    partial_crawl = result.stop_reason != StopReason.EXHAUSTED
    if graph["url_broken"]:
        urls = sorted({r["url"] for r in graph["url_broken"]})
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) name a URL in their structured data that returns an error", Severity.S4,
            Confidence.VERIFIED, doc, SD_ENGINES, urls, {"items": graph["url_broken"][:60]},
            "the url in the markup is the page's own live URL", "Point the markup's url at the page's canonical URL.",
            key_urls, [CAPPED, "Status from this crawl's own fetch of the markup URL."]))
    if graph["url_mismatch"]:
        urls = sorted({r["url"] for r in graph["url_mismatch"]})
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) name a different URL in their structured data than their canonical",
            Severity.INFO, Confidence.VERIFIED, doc, SD_ENGINES, urls, {"items": graph["url_mismatch"][:60]},
            "the url in the markup is the page's canonical URL",
            "Make the markup's url the page's canonical URL, so the entity and the page point at one address.",
            key_urls, ["Only page-level types are read (WebPage, Article, Product and their kin); links to other "
                       "entities are not mismatches."]))
    if graph["dangling"]:
        urls = sorted({r["url"] for r in graph["dangling"]})
        findings.append(_finding(
            "STR-3", f"{len(urls)} page(s) reference an @id that no crawled page defines", Severity.INFO,
            Confidence.VERIFIED, doc, SD_ENGINES, urls, {"items": graph["dangling"][:60]},
            "every @id reference resolves to a node with a type", "Define the referenced node (usually on the "
            "homepage), or reference an @id that exists.", key_urls,
            (["The crawl did not finish, so the node may be defined on a page it did not reach."]
             if partial_crawl else [])))
    if graph["type_clash"]:
        findings.append(_finding(
            "STR-3", f"{len(graph['type_clash'])} @id(s) are given different types in different places", Severity.INFO,
            Confidence.VERIFIED, doc, SD_ENGINES, sorted({u for r in graph["type_clash"] for u in r["on_pages"]}),
            {"items": graph["type_clash"][:40]}, "one @id, one kind of thing",
            "Use one @id per entity and give it the same type everywhere.", key_urls))
    summary = f"{len(findings)} finding(s)." if findings else "Structured data parses, the homepage has Organization, and required properties are present."
    return CheckResult("STR-3", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "types_seen": dict(type_counts.most_common(40)),
                        "graph": {"dangling_references": len(graph["dangling"]), "type_clashes": len(graph["type_clash"]),
                                  "url_mismatches": len(graph["url_mismatch"]), "url_errors": len(graph["url_broken"]),
                                  "scope": "every page this crawl fetched" + (" (crawl incomplete)" if partial_crawl else "")},
                        "formats_seen": sorted({f for p in pages for f in p.analysis["structured_data"]["formats"]}),
                        "rdfa_values_compared": "types only for RDFa beyond basic properties (see README)"},
                       observations)


# -- STR-4 ---------------------------------------------------------------------

FIELD_SEVERITY = {"price": Severity.S2, "currency": Severity.S2, "availability": Severity.S2,
                  "rating": Severity.S3, "date": Severity.S3, "product name": Severity.S3, "author": Severity.S3}
ESTIMATED_BASIS = {
    "product name": "compared by text containment and word overlap with the title and <h1> (no LLM, T0)",
    "author": "compared with an English 'By <Name>' byline (no LLM, T0)",
    "availability": "matched on English stock wording ('sold out', 'in stock', 'add to cart')",
    "date": "no date on the page is labeled published/updated, and neither structured-data date appears",
}
INFERRED_BASIS = {
    "price": ("Inferred: none of the prices shown on the page equals the markup price (Verified), but the page shows "
              "several different prices, so this assumes one of them is this offer's price."),
}
CONFIDENCE_BY_LABEL = {"verified": Confidence.VERIFIED, "inferred": Confidence.INFERRED, "estimated": Confidence.ESTIMATED}
IN_STOCK = {"InStock", "LimitedAvailability", "OnlineOnly", "InStoreOnly", "PreSale", "PreOrder", "BackOrder"}
OUT_OF_STOCK = {"OutOfStock", "SoldOut", "Discontinued"}
OUT_TEXT = re.compile(r"\b(out of stock|sold out|currently unavailable|no longer available)\b", re.I)
IN_TEXT = re.compile(r"\b(in stock|add to (cart|basket|bag)|buy now)\b", re.I)


def _offer_nodes(analysis: dict) -> list[dict]:
    nodes, seen = [], set()
    for node, _ in _typed_nodes(analysis):
        candidates = [node] if {"Offer", "AggregateOffer"} & set(node_types(node)) else []
        if set(node_types(node)) & PRODUCT_TYPES:
            candidates += [o for o in as_list(node.get("offers")) if isinstance(o, dict) and not o.get("@type")]
        for c in candidates:
            if id(c) not in seen:
                seen.add(id(c))
                nodes.append(c)
    return nodes


def _price_key(token: dict) -> str:
    return " ".join(token["text"].casefold().split())


def sitewide_prices(pages: list) -> set[str]:
    """Price texts shown on most of the audited pages: a banner ("from 29 USD"), not any one page's price."""
    return appears_on_most([{_price_key(t) for t in price_tokens(p.analysis.get("_visible_text", ""))} for p in pages])


YEARLY_WORDS = re.compile(r"year|annual|yıl|jahr|jähr|anual|annuel", re.IGNORECASE)
MONTHLY_WORDS = re.compile(r"month|aylık|aylik|monat|mensual|mensuel", re.IGNORECASE)
OTHER_STATE = ("every price the page shows is matched by another offer in the markup; this offer's price was not on the "
               "page in the state that was read (a monthly/yearly switch, or a plan whose price is not listed)")
# A markup price of 0 is shown on a page as a word, not as a number. Matched on `turkish_fold(text)`.
FREE_WORDS = re.compile(r"ücretsiz|bedava|ücret alınmaz|\bfree\b")
# Where a price stands on the page. Only the first is the page's own content (DECISIONS 175).
IN_MAIN = "main content"
NOT_OWN = {
    "outside": "outside the main content (header, navigation, footer or sidebar)",
    "link": "link text (a teaser for another page)",
    "teaser": f"a block repeated on at least {TEASER_SHARE:.0%} of the pages (and at least {TEASER_MIN_PAGES})",
    "sitewide": "a price shown on most pages of the site",
}
# Why a markup price could not be set against one price of the page: a person looks (the row's `why_code`).
PRICE_WHY = {
    "no_price": "no price is shown in the page text",
    "not_own": "the only prices in the page text are not this page's own (in link text, in a block other pages repeat, "
               "outside the main content, or in another currency than the markup)",
    "several": "the page's own content shows several different prices, and which of them is this offer's could not be told",
    "sibling": "another offer on the page matches a price it shows, and the one other price the page shows could not be "
               "paired with one of the several offers that are left",
    "accounted": "every price in the page's own content is matched by another offer in the markup",
    "other_state": OTHER_STATE,
}
CONTEXT_CHARS = 80


def located_prices(a: dict, teasers: frozenset[str] | set[str] = frozenset(), sitewide: frozenset[str] | set[str] = frozenset(),
                   shared_blocks: frozenset[str] | set[str] = frozenset()) -> list[dict]:
    """Every price in the page's text, with the text around it and where it stands.

    `not_own` is None for a price in the page's own main content, else why it is not taken for the page's price: it
    stands outside the main content, in link text (a card that leads to another page), in a block that many pages
    repeat (`teasers`), or it is a price most pages show (`sitewide`) outside a block of this page's own. Prices are
    read from the page's text as one string, so "99" and "TL" in two elements are still one price; a price that
    touches two text blocks takes the less reliable place of the two.
    """
    blocks = list(a.get("_text_blocks") or content_blocks(a))
    content, kinds = content_blocks(a), a.get("_content_block_kinds") or []
    if len(kinds) != len(content):
        kinds = ["text"] * len(content)
    place, at = [], 0
    for block in blocks:  # the content blocks are these same blocks, in order, with the page chrome left out
        if at < len(content) and content[at] == block:
            place.append(kinds[at])
            at += 1
        else:
            place.append(None)
    starts, position = [], 0
    for block in blocks:
        starts.append(position)
        position += len(block) + 1
    text = " ".join(blocks)
    own = {_price_key(t) for t in price_tokens(own_text(a, shared_blocks))} if sitewide else set()
    out = []
    for token, start, end in _price_matches(text):
        touched = range(max(0, bisect_right(starts, start) - 1), bisect_right(starts, end - 1))
        if any(place[i] is None for i in touched):
            reason = "outside"
        elif any(place[i] == "link" for i in touched):
            reason = "link"
        elif any(block_norm(blocks[i]) in teasers for i in touched):
            reason = "teaser"
        elif _price_key(token) in sitewide and _price_key(token) not in own:
            reason = "sitewide"
        else:
            reason = None
        around = " ".join(text[max(0, start - (CONTEXT_CHARS - (end - start)) // 2):end + (CONTEXT_CHARS - (end - start)) // 2].split())
        out.append({**token, "context": around[:CONTEXT_CHARS + 20], "not_own": reason,
                    "sitewide": _price_key(token) in sitewide and _price_key(token) not in own})
    return out


def _shown(token: dict, where: str | None = None) -> dict:
    """One price of the page as an evidence row keeps it."""
    return {"text": token["text"], "value": str(token["value"]), "currency": "/".join(sorted(token["currencies"])) or None,
            "context": token["context"], "where": where or (NOT_OWN[token["not_own"]] if token["not_own"] else IN_MAIN)}


def _settle_prices(rows: list[dict], located: list[dict]) -> None:
    """Decide every markup price that no price on the page equals (DECISIONS 175).

    A difference is a problem only when it can be shown: the page's own content holds exactly one price that could be
    this offer's, and it is another amount. A price counts as the page's own when it stands in the main content, not in
    link text and not in a block many pages repeat, and its currency mark, when it has one, agrees with the markup's;
    prices that another offer of the page matches are set aside first. No such price, or several, and a person looks.

    Several offers on one page: when one of them matches the page and nothing else is shown, the others that the
    same description lists beside it are the page's other state (a monthly/yearly switch). When one more price is
    shown and exactly one offer is left without a match, that offer and that price are a pair, and the difference
    stands (markup 89 beside a shown $99). When several offers are left, which of them the price belongs to cannot
    be told, and a person looks. With no offer matched at all, one shown price contradicts every offer.
    """
    prices = [row for row in rows if row["field"] == "price"]
    accounted = {row["_value"] for row in prices if row["outcome"] == "match"}
    listed_beside_a_match = {row["_listed_in"] for row in prices if row["outcome"] == "match" and row["_listed_in"] is not None}
    left = {row["_value"] for row in prices if row["outcome"] != "match"}
    for row in prices:
        value, listed_in, currency, entity = row["_value"], row["_listed_in"], row["_currency"], row["_entity"]
        if row["outcome"] == "match":
            continue

        def agrees(token: dict) -> bool:
            return not (token["currencies"] and currency) or currency in token["currencies"]

        own = [t for t in located if t["not_own"] is None and agrees(t) and t["value"] not in accounted]
        distinct = sorted({t["value"] for t in own})
        if not distinct and entity is not None:
            # The page shows one price, and another description of this same thing (not an offer listed beside this
            # one) gives that price: this description says something else about it, and the difference stands.
            shown = [t for t in located if t["not_own"] is None and agrees(t)]
            twin = {t["value"] for t in shown} & {other["_value"] for other in prices if other is not row
                                                  and other["outcome"] == "match" and other.get("_entity") == entity
                                                  and (listed_in is None or other.get("_listed_in") != listed_in)}
            if len({t["value"] for t in shown}) == 1 and twin:
                own, distinct = shown, sorted(twin)
                row["same_thing_described_twice"] = True
        # What the row shows of the page: the candidates first, then every other price and why it was set aside.
        aside = [_shown(t, None if t["not_own"] else "another currency than the markup" if not agrees(t) else
                        "main content, matched by another offer in the markup")
                 for t in located if t not in own]
        seen, visible = set(), []
        for entry in [_shown(t) for t in own] + aside:
            if (entry["text"], entry["where"]) not in seen:
                seen.add((entry["text"], entry["where"]))
                visible.append(entry)
        row["visible"] = visible[:10]
        beside_a_match = listed_in in listed_beside_a_match
        if len(distinct) == 1 and not (accounted and len(left) > 1 and not row.get("same_thing_described_twice")):
            row.update(outcome="conflict", confidence="verified", distinct_prices_shown=1,
                       visible=[v for v in visible if v["where"] == IN_MAIN][:3] + [v for v in visible if v["where"] != IN_MAIN][:7])
            continue
        code = ("sibling" if len(distinct) == 1 else "several" if distinct else "other_state" if beside_a_match
                else "accounted" if any(t["not_own"] is None and agrees(t) for t in located)
                else "not_own" if located else "no_price")
        row.update(outcome="not_visible", why_code=code, why_not_reliable=PRICE_WHY[code])
        if distinct:
            row["distinct_prices_shown"] = len(distinct)
        if code != "other_state":
            continue
        row["other_state"] = True
        # Twelve months with a discount of up to a half: the yearly price of a plan the page shows per month. The
        # offer's own name decides first; the arithmetic alone is used only when the offer does not name its period.
        label = row.get("offer", "")
        named_yearly, named_monthly = bool(YEARLY_WORDS.search(label)), bool(MONTHLY_WORDS.search(label))
        base = next((v for v in sorted(accounted) if v and 6 <= value / v <= 12), None) if not (named_monthly and not named_yearly) else None
        if named_yearly or (base is not None and not label):
            row["likely"] = ("a yearly price" + (f": {value} is {float(value / base):g} × the {base} the page shows"
                                                 if base is not None else " (the offer is named as yearly)"))
    for row in prices:
        for key in ("_value", "_listed_in", "_currency", "_entity"):
            row.pop(key, None)


def site_brand_keys(result: CrawlResult, pages: list) -> set[str]:
    """The site's own names, normalised (`brand_key`): og:site_name, the Organization and WebSite names that describe
    this site, and the first label of its host. The same sources STR-5 reads, without its judgement of them."""
    home = homepage_url(result)
    names = [urlsplit(result.origin).hostname.removeprefix("www.").split(".")[0]] if urlsplit(result.origin).hostname else []
    names += [value for _, value in og_site_names(pages)[0]]
    for p in pages:
        names += [text_value(node.get("name")) or "" for node in organization_nodes(p.analysis)
                  if _is_this_site(node, p.url, home, result.origin)]
        if p.url == home:
            names += [text_value(node.get("name")) or "" for node, nested in _typed_nodes(p.analysis)
                      if not nested and "WebSite" in node_types(node)]
    return {brand_key(name) for name in names if name and brand_key(name)}


def name_without_brand(name: str, brands: set[str] | frozenset[str]) -> str:
    """A product name without the site's own name around it: "Acme - Premium Plus" -> "Premium Plus". The segments
    are those a title separator makes; one that is a name of the site is dropped. Unchanged when nothing is left."""
    kept = [part.strip() for part in TITLE_SEPARATORS.split(name) if part.strip() and brand_key(part) not in brands]
    return " ".join(kept) if kept else name


def _compare_page(page, text: str, english: bool, sitewide: frozenset[str] | set[str] = frozenset(),
                  shared_blocks: frozenset[str] | set[str] = frozenset(), teasers: frozenset[str] | set[str] = frozenset(),
                  brands: frozenset[str] | set[str] = frozenset()) -> list[dict]:
    """One row per structured-data value compared: outcome conflict / not_visible / match / not_assessed.

    `sitewide` holds price texts shown on most pages. A markup price that equals one of them still matches, but
    they are not taken for this page's price when it differs: a site-wide "29 USD" banner says nothing about an
    event priced at 0 in the markup. A site-wide price is ignored only where it sits in a block most pages share
    (`shared_blocks`): a homepage whose own headline says "from 50.000 TL" shows that price itself, however many
    other pages repeat the amount in a banner. `teasers` are the text blocks a good part of the site repeats, and
    `brands` the site's own names (left out of a product name before it is compared). A price row holds both sides:
    `schema_value` with `schema_currency` and `offer_parent`, and `visible`, the prices of the page with the text
    around each and where it stands; a row that could not be decided says why in `why_not_reliable`.
    """
    rows = []
    a = page.analysis
    located = located_prices(a, teasers, sitewide, shared_blocks)
    ignored = sorted({t["text"] for t in located if t["sitewide"]})
    kinds = a.get("_content_block_kinds") or []
    own_blocks = [block for at, block in enumerate(content_blocks(a))
                  if block_norm(block) not in teasers and not (at < len(kinds) and kinds[at] == "link")]
    free = FREE_WORDS.search(turkish_fold(" ".join(own_blocks)))
    # Which `offers` list each offer sits in, when a description lists several; and what each offer is an offer of.
    listed_in = {id(offer): id(node) for node, _ in _typed_nodes(a) for offers in [as_list(node.get("offers"))]
                 if len(offers) > 1 for offer in offers if isinstance(offer, dict)}
    parent_of = {id(offer): node for node, _ in _typed_nodes(a) for offer in as_list(node.get("offers")) if isinstance(offer, dict)}
    for offer in _offer_nodes(a):
        spec = offer.get("priceSpecification") if isinstance(offer.get("priceSpecification"), dict) else {}
        currency = text_value(offer.get("priceCurrency") or spec.get("priceCurrency"))
        parent = parent_of.get(id(offer)) or (offer.get("itemOffered") if isinstance(offer.get("itemOffered"), dict) else None)
        for key, raw in (("price", offer.get("price")), ("lowPrice", offer.get("lowPrice")), ("priceSpecification.price", spec.get("price"))):
            value = schema_number(text_value(raw)) if raw not in (None, "") else None
            if value is None:
                continue
            row = {"field": "price", "property": key, "schema_value": str(raw), "schema_currency": currency.upper() if currency else None,
                   "offer_parent": {"type": node_types(parent), "name": text_value(parent.get("name"))} if parent else None}
            label = " ".join(text_value(offer.get(k)) or "" for k in ("name", "category", "description"))[:120].strip()
            if label:
                row["offer"] = label
            row["_value"], row["_listed_in"], row["_currency"] = value, listed_in.get(id(offer)), currency.upper() if currency else None
            # What the offer is an offer of, to know two descriptions of one thing from two things.
            named = _norm(text_value(parent.get("name"))) if parent else ""
            row["_entity"] = (tuple(sorted(node_types(parent))), named) if named else None
            matched = [t for t in located if t["value"] == value]
            if ignored:
                row["site_wide_prices_ignored"] = ignored
            if matched:
                row.update(outcome="match", visible=[_shown(matched[0])])
            elif value == 0 and free:
                # A price of 0 is shown as a word: "Ücretsiz", "free".
                row.update(outcome="match", free_wording=True,
                           visible=[{"text": free.group(0), "value": "0", "currency": None, "context": None, "where": IN_MAIN}])
            else:
                row["outcome"] = "undecided"  # settled below, once every offer of the page is known
            rows.append(row)
            if currency and matched:
                seen = [t["currencies"] for t in matched]
                crow = {"field": "currency", "property": "priceCurrency", "schema_value": currency,
                        "visible": sorted({t["text"] for t in matched})}
                if all(seen) and currency.upper() not in set().union(*seen):
                    crow.update(outcome="conflict", confidence="verified",
                                visible_currencies=sorted(set().union(*seen)))
                else:
                    crow.update(outcome="match")
                rows.append(crow)
        availability = text_value(offer.get("availability"))
        if availability:
            state = availability.rstrip("/").rsplit("/", 1)[-1]
            row = {"field": "availability", "property": "availability", "schema_value": availability}
            out_text, in_text = OUT_TEXT.search(text), IN_TEXT.search(text)
            if not english:
                row.update(outcome="not_assessed", reason="availability wording is matched in English only")
            elif state in IN_STOCK and out_text and not in_text:
                row.update(outcome="conflict", confidence="estimated", visible=out_text.group(0))
            elif state in OUT_OF_STOCK and in_text and not out_text:
                row.update(outcome="conflict", confidence="estimated", visible=in_text.group(0))
            else:
                row.update(outcome="match")
            rows.append(row)
    _settle_prices(rows, located)
    products_named = sum(1 for node, _ in _typed_nodes(a) if set(node_types(node)) & PRODUCT_TYPES and text_value(node.get("name")))
    for node, _ in _typed_nodes(a):
        types = set(node_types(node))
        if "AggregateRating" in types and node.get("ratingValue") not in (None, ""):
            value, best = schema_number(text_value(node.get("ratingValue"))), schema_number(text_value(node.get("bestRating")) or "5")
            if value is None:
                continue
            row = {"field": "rating", "property": "ratingValue", "schema_value": str(node["ratingValue"])}
            shown = [(parse_number(m.group(1)), m.group(0)) for m in RATING_TOKEN.finditer(text)
                     if best is not None and Decimal(m.group(2)) == best]
            if shown and not any(v is not None and abs(v - value) <= Decimal("0.05") for v, _ in shown):
                row.update(outcome="conflict", confidence="verified", visible=[t for _, t in shown][:5])
            elif shown:
                row.update(outcome="match")
            elif str(node["ratingValue"]) in text or str(node["ratingValue"]).replace(".", ",") in text:
                row.update(outcome="match")
            else:
                row.update(outcome="not_visible", visible="no 'x/5' rating and no matching number in the page text")
            rows.append(row)
        if types & PRODUCT_TYPES:
            name = text_value(node.get("name"))
            if name:
                row = {"field": "product name", "property": "name", "schema_value": name}
                # The site's own name around a product name ("Acme - Premium Plus") is not part of what the page
                # calls the product.
                core = name_without_brand(name, brands)
                if core != name:
                    row["compared_as"] = core
                if _norm(name) in _norm(text) or _norm(core) in _norm(text):
                    row.update(outcome="match")
                else:
                    h1 = " ".join(h["text"] for h in a["headings"] if h["level"] == 1)
                    heading = " ".join([a["title"] or "", h1])
                    name_tokens, head_tokens = set(_norm(core).split()), set(_norm(heading).split())
                    overlap = len(name_tokens & head_tokens) / len(name_tokens) if name_tokens else 0
                    row.update(visible=heading.strip()[:120], token_overlap_with_title_and_h1=round(overlap, 2))
                    if overlap >= 0.5:
                        row.update(outcome="match", confidence="estimated")
                    elif h1.strip() and products_named == 1:
                        # The page is about one product and its <h1> names something else: a difference.
                        row.update(outcome="conflict", confidence="estimated")
                    else:
                        # A name that is not on the page is not a different name: a page that lists several
                        # products, or has no <h1>, does not say what this one is called.
                        row.update(outcome="not_visible", why_not_reliable="the product name is not shown on this page")
                rows.append(row)
        if types & ARTICLE_TYPES:
            for author in as_list(node.get("author")):
                name = text_value(author)
                if not name or name.startswith("http"):
                    continue
                row = {"field": "author", "property": "author", "schema_value": name}
                byline = BYLINE.search(text) if english else None
                if _norm(name) in _norm(text):
                    row.update(outcome="match")
                elif byline and _norm(byline.group(1)) not in _norm(name) and _norm(name) not in _norm(byline.group(1)):
                    row.update(outcome="conflict", confidence="estimated", visible=byline.group(0))
                else:
                    row.update(outcome="not_visible", visible="author name not found in the page text")
                rows.append(row)
    rows.extend(_date_rows(a, text))
    return rows


def _schema_dates(analysis: dict) -> dict[str, dict]:
    """First datePublished / dateModified on the page, preferring top-level nodes."""
    out: dict[str, dict] = {}
    for index, (node, nested) in enumerate(sorted(_typed_nodes(analysis), key=lambda nn: nn[1])):
        for key in ("datePublished", "dateModified"):
            if key not in out and parse_date(text_value(node.get(key))):
                out[key] = {"raw": text_value(node.get(key)), "date": parse_date(text_value(node.get(key))),
                            "type": node_types(node), "entity": node.get('@id') or f'node:{index}'}
    return out


def _date_rows(analysis: dict, text: str) -> list[dict]:
    schema = _schema_dates(analysis)
    if not schema:
        return []
    shown = visible_dates(analysis)
    if not shown:
        return []  # "no visible date" is STR-6's Info, not a conflict
    rows = []

    def near(d, pool):
        return any(abs((d - v["date"]).days) <= 1 for v in pool)

    for key, kind in (("datePublished", "published"), ("dateModified", "modified")):
        if key not in schema:
            continue
        d = schema[key]["date"]
        labeled = [v for v in shown if v["kind"] == kind]
        row = {"field": "date", "property": key, "schema_value": schema[key]["raw"],
               "visible": [f'{v["text"]} ({v["kind"] or "unlabeled"})' for v in shown][:6]}
        if labeled:
            row.update(outcome="match" if near(d, labeled) else "conflict", confidence="verified")
        elif any(near(s["date"], shown) for s in schema.values()):
            row.update(outcome="match")
        else:
            # Every visible date is unlabeled, so there is nothing to compare against: dates on a page
            # are often customer testimonials or comments, not the page's own. The first live audit of a
            # client site reported 7 pages this way, every one of them a testimonial date.
            row.update(outcome="not_assessed", reason="no visible date is labelled published/updated; "
                                                      "unlabelled dates on the page may belong to other content")
        rows.append(row)
    return rows


def str4_consistency(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str]) -> tuple[CheckResult, set[str]]:
    title = "Structured data vs visible content consistency"
    with_sd = [p for p in pages if p.analysis.get("_structured_items")]
    checked = [p for p in with_sd if p.url not in gap]
    if not checked:
        return CheckResult("STR-4", title, "not_assessed", "No indexable page with structured data and content in raw HTML.",
                           evidence={"excluded_as_rnd1_root_cause": sorted(u for u in gap if u in {p.url for p in with_sd})}), set()
    conflicts: dict[tuple, list] = defaultdict(list)
    not_visible: dict[str, list] = defaultdict(list)
    not_assessed, compared = [], Counter()
    date_conflict_pages = set()
    sitewide, shared_blocks = sitewide_prices(pages), blocks_on_most_pages(pages)
    teasers, brands = teaser_blocks(pages), site_brand_keys(result, pages)
    price_rows = []
    for p in checked:
        text = p.analysis.get("_visible_text", "")
        english, why = english_text_assessable(p.analysis)
        for row in _compare_page(p, text, english, sitewide, shared_blocks, teasers, brands):
            compared[row["field"]] += 1
            row = {"url": p.url, **row}
            if row["field"] == "price":
                price_rows.append(row)
            if row["outcome"] == "conflict":
                conflicts[(row["field"], row["confidence"])].append(row)
                if row["field"] == "date":
                    date_conflict_pages.add(p.url)
            elif row["outcome"] == "not_visible":
                not_visible["price in another state" if row.get("other_state") else row["field"]].append(row)
            elif row["outcome"] == "not_assessed":
                not_assessed.append({**row, "language": why})
    findings = []
    for (field, confidence), rows in sorted(conflicts.items(), key=lambda kv: (FIELD_SEVERITY[kv[0][0]].value, kv[0][0])):
        urls = sorted({r["url"] for r in rows})
        severity = FIELD_SEVERITY[field]
        exact = confidence == "verified"
        findings.append(_finding(
            "STR-4", f"{len(urls)} page(s): structured-data {field} differs from the {field} shown on the page",
            severity, CONFIDENCE_BY_LABEL[confidence],
            "Documented (Google: markup must be a true representation of visible content) / Hypothesis (answer quality)",
            SD_ENGINES, urls, {"values": rows[:60]}, f"the structured-data {field} matches what the page shows",
            "Update whichever value is wrong so the markup and the visible page agree (usually the markup is stale).",
            key_urls,
            ([] if exact else [INFERRED_BASIS[field] if confidence == "inferred"
                               else f"Estimated: {ESTIMATED_BASIS[field]}."])
            + (["A price, currency, or availability an engine would quote is wrong (spec: S2)."]
               if severity == Severity.S2 else [])))
    review_items = []
    for field, rows in not_visible.items():
        urls = sorted({r["url"] for r in rows})
        if field == "price in another state":
            review_items.append(ReviewItem(
                "STR-4", f"{len(urls)} page(s): the markup lists {len(rows)} price(s) the page did not show when it was read",
                "Every price shown on the page is matched by an offer in the markup, so nothing shown contradicts it. The "
                "remaining offers carry prices the page did not show in the state that was read: usually the other side of "
                "a monthly/yearly switch, or a plan whose price is not listed. That is not a conflict, but a person should "
                "confirm the page can show each of them.",
                Confidence.INFERRED, SD_ENGINES, scope_for(urls), {"values": rows[:60]},
                "Switch the page to its other state (for example yearly billing) and check that each of these prices "
                "appears. Remove from the markup any price the page never shows.",
                importance_tier=_tier(urls, key_urls)))
            continue
        if field == "price":
            review_items.append(ReviewItem(
                "STR-4", f"{len(urls)} page(s): the markup price is not shown on the page, or the page's own price could not be told apart",
                "A markup price that differs from the page is reported as a problem only when the page's own content shows "
                "exactly one price that could be this offer's. On these pages there was no such price, or more than one: a "
                "price in a teaser for another page, in a block many pages repeat, in another currency or beside other "
                "offers is not taken for this page's price. Each row gives the markup price with its currency, every price "
                "found in the page text with the words around it, and why none could be relied on.",
                Confidence.ESTIMATED, SD_ENGINES, scope_for(urls),
                {"values": rows[:60], "values_count": len(rows),
                 "a_price_is_the_pages_own_when": "it stands in the main content, not in link text, not in a block on at least "
                                                 f"{TEASER_SHARE:.0%} of the pages (and at least {TEASER_MIN_PAGES}), its currency mark "
                                                 "agrees with the markup's, and no other offer of the page matches it"},
                "Open each page and compare the price a visitor sees with the markup price in the row. Update the markup where "
                "it is out of date, and remove from the markup a price the page never shows.",
                importance_tier=_tier(urls, key_urls)))
            continue
        review_items.append(ReviewItem(
            "STR-4", f"{len(urls)} page(s): structured-data {field} is not shown on the page",
            "Google says not to mark up content readers cannot see, but a value missing from the text is not a proven "
            "conflict (it may be shown as an image, or be stale). A person should check which it is.",
            Confidence.ESTIMATED if field in ("author", "rating") else Confidence.VERIFIED, SD_ENGINES, scope_for(urls),
            {"values": rows[:60]}, "Show the value on the page, or remove it from the markup if it is out of date.",
            importance_tier=_tier(urls, key_urls)))
    judged = sum(compared.values()) - len(not_assessed)
    summary = (f"{len(findings)} finding(s), {len(review_items)} review item(s)." if findings or review_items
               else f"All {judged} structured-data value(s) that could be compared match the visible text, on "
                    f"{len(checked)} page(s).")
    if not_assessed:
        summary += f" {len(not_assessed)} value(s) could not be compared (see coverage)."
    return CheckResult("STR-4", title, _status(findings, review_items), summary, findings,
                       {"pages_compared": len(checked), "values_compared_by_field": dict(compared),
                        "values_judged": judged, "not_assessed": not_assessed[:40],
                        # Every price compared and how it came out, so a "match" or a missing conflict can be checked.
                        "price_comparisons": price_rows[:60], "price_comparisons_count": len(price_rows),
                        "site_wide_prices": sorted(sitewide), "teaser_blocks": len(teasers), "site_names_left_out_of_product_names": sorted(brands),
                        "not_assessed_count": len(not_assessed), "llm_comparison": "not built (fuzzy fields use T0 text rules)",
                        "excluded_as_rnd1_root_cause": sorted(u for u in gap if u in {p.url for p in with_sd})},
                       [], review_items), date_conflict_pages


# -- STR-11 --------------------------------------------------------------------

# Markup fields STR-11 compares between two descriptions of one entity, with STR-4's name for the same field so a
# conflict STR-4 already reports on a page is not reported twice (root cause once).
MARKUP_FIELDS = {"price": ("price", Severity.S2), "priceCurrency": ("currency", Severity.S2),
                 "availability": ("availability", Severity.S2), "name": ("product name", Severity.S3),
                 "datePublished": ("date", Severity.S3), "dateModified": ("date", Severity.S3)}


def _family(node: dict) -> str:
    types = set(node_types(node))
    if types & PRODUCT_TYPES or types & {"Offer", "AggregateOffer"}:
        return "product"
    if types & ARTICLE_TYPES:
        return "article"
    if types & ORGANIZATION_TYPES:
        return "organization"
    return "other"


def _markup_values(node: dict) -> dict[str, frozenset]:
    """The comparable values one description gives, with its offers folded in (offers is where prices live)."""
    offers = [node] + [o for o in as_list(node.get("offers")) if isinstance(o, dict)]
    out: dict[str, set] = defaultdict(set)
    for o in offers:
        spec = o.get("priceSpecification") if isinstance(o.get("priceSpecification"), dict) else {}
        for raw in (o.get("price"), o.get("lowPrice"), spec.get("price")):
            number = schema_number(text_value(raw)) if raw not in (None, "") else None
            if number is not None:
                out["price"].add(number)
        currency = text_value(o.get("priceCurrency") or spec.get("priceCurrency"))
        if currency:
            out["priceCurrency"].add(currency.upper())
        availability = text_value(o.get("availability"))
        if availability:
            out["availability"].add(availability.rstrip("/").rsplit("/", 1)[-1])
    for key in ("datePublished", "dateModified"):
        when = parse_date(text_value(node.get(key)))
        if when:
            out[key].add(when)
    name = text_value(node.get("name") or node.get("headline"))
    if name:
        out["name"].add(_norm(name))
    return {k: frozenset(v) for k, v in out.items()}


def _entity_descriptions(page) -> dict[tuple, list[dict]]:
    """Top-level descriptions of the same entity on one page: by @id, else by type family and name."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for item in page.analysis.get("_structured_items", []):
        for node, nested in iter_typed_nodes(item["data"]):
            if nested:
                continue
            ident = text_value(node.get("@id")) if isinstance(node.get("@id"), str) else None
            name = text_value(node.get("name") or node.get("headline"))
            if ident:
                key = ("@id", id_key(ident, page.url))
            elif name:
                key = ("name", _family(node), _norm(name))
            else:
                continue
            groups[key].append({"format": item["format"], "type": node_types(node), "values": _markup_values(node),
                                "raw_dates": {field: node[field] for field in ('datePublished','dateModified') if field in node}})
    return {k: v for k, v in groups.items() if len(v) > 1}


def str11_markup_contradictions(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str],
                                str4: CheckResult) -> CheckResult:
    title = "Structured data contradicts itself"
    if not pages:
        return CheckResult("STR-11", title, "not_assessed", "No indexable HTML pages.")
    str4_conflicts = {(r["url"], r["field"]) for f in str4.findings for r in f.evidence.get("values", [])}
    unparseable = [p.url for p in pages if any(not b["ok"] for b in p.analysis["structured_data"]["jsonld_blocks"])]
    rows_by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    left_to_str4, pages_with_repeats = [], 0
    precision_reviews = []
    for p in pages:
        groups = _entity_descriptions(p)
        pages_with_repeats += bool(groups)
        for key, descriptions in groups.items():
            for field, (str4_field, _) in MARKUP_FIELDS.items():
                if field == "name" and key[0] != "@id":
                    continue  # grouped by name: the names agree by construction
                given = [d for d in descriptions if d["values"].get(field)]
                clash = False
                for i, a in enumerate(given):
                    for b in given[i + 1:]:
                        if a["values"][field] & b["values"][field]:
                            continue
                        raw = [str(d.get("raw_dates", {}).get(field, "")) for d in (a, b)]
                        mixed_precision = (sum(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)) for v in raw) == 1
                                           and any("T" in v for v in raw))
                        if mixed_precision and any(abs((x-y).days) <= 1 for x in a["values"][field] for y in b["values"][field]):
                            precision_reviews.append({"url": p.url, "entity": key[-1], "field": field,
                                                      "raw_values": raw, "reason": "date-only timezone is unknown"})
                            continue
                        clash = True
                if not clash:
                    continue
                row = {"url": p.url, "entity": key[-1], "grouped_by": "@id" if key[0] == "@id" else "type and name",
                       "field": field,
                       "descriptions": [{"format": d["format"], "type": d["type"],
                                         "value": sorted(str(v) for v in d["values"][field]),
                                         **({'raw_value':d['raw_dates'][field]} if field in d['raw_dates'] else {})} for d in given],
                       "reproduce": f"curl -s -A {shlex.quote(cfg.user_agent)} {shlex.quote(p.url)} | "
                                    "grep -o -E 'application/ld\\+json|itemprop=\"[a-zA-Z]+\"[^>]*'"}
                if (p.url, str4_field) in str4_conflicts:
                    left_to_str4.append(row)
                    continue
                grouped = "verified" if key[0] == "@id" else "inferred"
                rows_by[(field, grouped)].append(row)
    findings = []
    for (field, grouped), rows in sorted(rows_by.items(), key=lambda kv: (MARKUP_FIELDS[kv[0][0]][1].value, kv[0])):
        urls = sorted({r["url"] for r in rows})
        severity = MARKUP_FIELDS[field][1]
        findings.append(_finding(
            "STR-11", f"{len(urls)} page(s) describe the same entity twice in structured data with a different {field}",
            severity, Confidence.VERIFIED if grouped == "verified" else Confidence.INFERRED,
            "Documented (Google: markup must be a true representation of the page) / Hypothesis (answer quality)",
            SD_ENGINES, urls, {"contradictions": rows[:60]},
            f"every description of one entity gives the same {field}",
            "Keep one description per entity, or generate every description from the same source; at least one of "
            "these values is stale.", key_urls,
            (["Inferred: these descriptions carry no shared @id; they are taken to be the same entity because they "
              "have the same type and name on the same page."] if grouped == "inferred" else [])
            + (["A price, currency, or availability an engine would quote is wrong in at least one description "
                "(the same severity as STR-4)."] if severity == Severity.S2 else [])))
    summary = (f"{len(findings)} finding(s)." if findings else
               f"No entity is described twice with different values ({pages_with_repeats} of {len(pages)} page(s) "
               "describe an entity more than once).")
    if unparseable:
        summary += f" {len(unparseable)} page(s) have JSON-LD that does not parse, so its descriptions were not compared."
    if precision_reviews:
        summary += f" {len(precision_reviews)} date comparison(s) have mixed precision and were not assessed."
    return CheckResult("STR-11", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "pages_describing_an_entity_more_than_once": pages_with_repeats,
                        "unparseable_jsonld_pages": unparseable[:40], "unparseable_jsonld_pages_count": len(unparseable),
                        "left_to_STR-4": left_to_str4[:40],
                        "date_precision_not_assessed": precision_reviews[:60],
                        "date_precision_not_assessed_count": len(precision_reviews),
                        "fields_compared": sorted(MARKUP_FIELDS),
                        "scope": "within one page; the same @id across pages is not compared yet"})


# -- STR-5 ---------------------------------------------------------------------

LEGAL_SUFFIXES = {"inc", "llc", "ltd", "limited", "gmbh", "ag", "sa", "sas", "sarl", "srl", "spa", "bv", "nv", "plc",
                  "corp", "corporation", "co", "company", "oy", "ab", "pty", "kft", "sro", "kk", "aş", "as", "ltd şti", "şti"}
TITLE_SEPARATORS = re.compile(r"\s+[|\-–—·•:]\s+")
COPYRIGHT = re.compile(r"(?:©|\(c\)|copyright)\s*(?:(?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?\s*)?(?:©\s*)?"
                       r"(?P<name>[^.|•·©\n]{2,80}?)\s*(?:[.|•·]|,?\s*all rights|$)", re.I)


# Years and year ranges at the start of a copyright name ("© 2023-2025 Demo Kafe", "Copyright © 2024, Demo Kafe").
COPYRIGHT_YEARS = re.compile(r"^(?:(?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?[\s,©]*)+")
# A branch: the most-used name and 1 to 4 more words, given by a structured-data node off the homepage (DECISIONS 221).
BRANCH_EXTRA_WORDS = (1, 4)
BRANCHES_NOT_COUNTED = "Branch names are not counted as other names: {names}."


def copyright_name(match: re.Match) -> str:
    """The name of a copyright line, leading years and year ranges taken off (DECISIONS 221)."""
    return COPYRIGHT_YEARS.sub("", match.group("name").strip(" ,")).strip(" ,")


def brand_key(name: str) -> str:
    """Normalized brand name for counting variants: case, punctuation, a trailing 'logo', and legal suffixes removed."""
    tokens = _norm(name).split()
    if tokens and tokens[-1] == "logo":
        tokens = tokens[:-1]
    changed = True
    while changed and len(tokens) > 1:
        changed = False
        if tokens[-2:] == ["a", "ş"]:
            tokens, changed = tokens[:-2], True
        elif tokens[-1] in LEGAL_SUFFIXES or tokens[-1] == "&":  # "GmbH & Co"
            tokens, changed = tokens[:-1], True
    return " ".join(tokens)


def localized_name_extras(records: list[dict]) -> set[str]:
    """Counting qualification only: one declared entity, unconfirmed name meaning."""
    extras = set()
    for record in records:
        labels = record['names']
        representative = max(labels, key=lambda name: (len(labels[name]), brand_key(name)))
        extras.update(brand_key(name) for name in labels if name != representative)
        record['counted_as_one_entity'] = True
    return extras


def _is_this_site(node: dict, page_url: str, home: str, origin: str) -> bool:
    """Whether an Organization node describes the audited site, rather than some other company.

    Sites mark up organizations that are not their own: customer stories, sector directories, review
    pages. The first 50-page live audit of a real site collected 237 "brand name variants" that way,
    every one of them another company. A node counts only when it points at this site (url or @id), or
    when it is on the homepage with no url to contradict it.
    """
    for key in ("url", "@id"):
        value = text_value(node.get(key))
        if value:
            resolved = normalize_url(value, page_url)
            return bool(resolved) and origin_of(resolved) == origin
    return page_url == home


BRAND_NAME_KEY = "str5.site_name"


def og_site_names(pages: list) -> tuple[list[tuple[str, str]], list[dict]]:
    """([(page, og:site_name) that names the site], [pages whose og:site_name holds the page's title]).

    og:site_name is the site's name. A template that fills it with the page's title ("Privacy | Acme") does one
    thing wrong on every such page; read as names, seven pages gave seven "names" (DECISIONS 176). A value that
    equals the page's own title, or has a title separator in it, is not a name source and is reported once. A
    homepage titled with the brand alone has the same title and site name by right: a value that equals the title
    counts only when it is not the value most pages give."""
    usual = Counter(_norm(v) for p in pages for v in p.analysis["og"].get("og:site_name", [])[:1]).most_common(1)
    usual_site_name = usual[0][0] if usual else None
    named, titles = [], []
    for p in pages:
        for v in p.analysis["og"].get("og:site_name", [])[:1]:
            same_as_title = bool(_norm(v)) and _norm(v) == _norm(p.analysis["title"]) and _norm(v) != usual_site_name
            if TITLE_SEPARATORS.search(v) or same_as_title:
                titles.append({"url": p.url, "og_site_name": v[:200], "title": (p.analysis["title"] or "")[:200]})
            else:
                named.append((p.url, v))
    return named, titles


def str5_entity(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], data: StructureData) -> CheckResult:
    from ..structure_data import identity_organization_nodes, department_nodes
    title = "Entity identity consistency"
    if not pages:
        return CheckResult("STR-5", title, "not_assessed", "No indexable HTML pages.")
    home = homepage_url(result)
    home_page = next((p for p in result.pages if p.url == home and p.analysis), None)
    sources: list[dict] = []
    declared: dict[str, str] = {}
    org_urls: dict[str, set[str]] = defaultdict(set)
    for p in result.pages:
        if not p.analysis:
            continue
        for node in identity_organization_nodes(p.analysis):
            name = text_value(node.get("name"))
            if not name or not _is_this_site(node, p.url, home, result.origin):
                continue
            sources.append({"source": "Organization name", "value": name, "url": p.url})
            for key in ("alternateName", "legalName"):
                for v in as_list(node.get(key)):
                    if isinstance(v, str) and v.strip():
                        declared[brand_key(v)] = f"{key}: {v}"
            for same in as_list(node.get("sameAs")):
                url = normalize_url(same, p.url) if isinstance(same, str) else None
                if url:
                    org_urls[url].add(p.url)
    named, title_in_site_name = og_site_names(pages)
    sources += [{"source": "og:site_name", "value": value, "url": url} for url, value in named]
    if home_page:
        for node, nested in _typed_nodes(home_page.analysis):
            if not nested and "WebSite" in node_types(node) and text_value(node.get("name")):
                sources.append({"source": "WebSite name", "value": text_value(node.get("name")), "url": home})
                break
    # One @id that names the brand differently on different pages: the markup itself contradicts, which needs
    # no judgement about whether two spellings are the same name.
    names_by_id: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    aliases_by_id: dict[str, set[str]] = defaultdict(set)
    publishers_by_id: dict[str, set[str]] = defaultdict(set)
    locales_by_id: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for p in result.pages:
        if not p.analysis:
            continue
        for node in identity_organization_nodes(p.analysis) + [n for n, nested in _typed_nodes(p.analysis)
                                                       if "WebSite" in node_types(n)]:
            ident, name = _id_of(node), text_value(node.get("name"))
            if ident and name and _is_this_site(node, p.url, home, result.origin):
                identity = id_key(ident, p.url)
                names_by_id[identity][name].add(p.url)
                locale = primary_subtag(text_value(node.get('inLanguage')) or p.analysis.get('html_lang') or '')
                locales_by_id[identity][brand_key(name)].add(locale or 'unknown')
                for publisher in as_list(node.get('publisher')):
                    if isinstance(publisher, dict) and publisher.get('@id'):
                        publishers_by_id[identity].add(id_key(publisher['@id'], p.url))
                for field in ('alternateName', 'legalName'):
                    for alias in as_list(node.get(field)):
                        if isinstance(alias, str) and alias.strip():
                            aliases_by_id[identity].add(brand_key(alias))
    for identity, publishers in publishers_by_id.items():
        for publisher in publishers:
            aliases_by_id[identity].update(aliases_by_id.get(publisher, set()))
    id_clashes, localized_names, declared_aliases = [], [], []
    for identity, names in names_by_id.items():
        normalized = {brand_key(name) for name in names}
        if len(normalized) <= 1:
            continue  # punctuation/case/legal suffixes do not establish another identity
        record = {'@id': identity, 'names': {n: sorted(u)[:5] for n, u in names.items()}}
        remaining = normalized - aliases_by_id[identity]
        if len(remaining) <= 1 and aliases_by_id[identity]:
            declared_aliases.append(record)
            continue
        locales = locales_by_id[identity]
        known = set().union(*locales.values())
        if 'unknown' not in known and len(known) > 1 and all(
                not (locales[a] & locales[b]) for a in normalized for b in normalized if a != b):
            localized_names.append({**record, 'qualification':
                'Same-entity names occur in different declared locales; translation/alias meaning requires owner review, not a proven contradiction.'})
            continue
        id_clashes.append(record)
    if home_page:
        # The © line is its own text node. Searching the whole footer as one string ran the name into the
        # next link ("Maya AI Back to top Built for what's next"), seen on the first live crawl.
        blocks = [b for b in home_page.analysis.get("_text_blocks", []) if "©" in b or "copyright" in b.casefold()]
        for block in blocks[:3] or [home_page.analysis["footer_text"]]:
            m = COPYRIGHT.search(block)
            if m and copyright_name(m):
                sources.append({"source": "footer legal name", "value": copyright_name(m), "url": home})
                break
        # Only a logo in the header/nav is the site's own. A page full of customer logos (a "trusted by"
        # strip) produced "Volkswagen" as a brand-name variant on the first live crawl.
        chrome_logos = [l for l in home_page.analysis["logo_alts"] if l["in_chrome"] and l["alt"]]
        if len(chrome_logos) == 1:
            sources.append({"source": "logo alt text", "value": chrome_logos[0]["alt"], "url": home})
        elif chrome_logos:
            notes_logo = f"{len(chrome_logos)} logo images in the header/nav: none treated as the site's own logo"
            sources.append({"source": "logo alt text (not used)", "value": "", "url": home, "note": notes_logo})
    # Title suffix/prefix: a segment repeated on several pages that is either the dominant one or shares a word
    # with another brand source, word for word (so "Pricing" in "Pricing | Acme" is not taken for a brand).
    segment_pages: dict[str, list[str]] = defaultdict(list)
    raw_segment: dict[str, str] = {}
    for p in pages:
        parts = TITLE_SEPARATORS.split(p.analysis["title"] or "")
        if len(parts) < 2:
            continue
        for seg in {parts[0].strip(), parts[-1].strip()}:
            if seg and len(seg.split()) <= 5:
                segment_pages[brand_key(seg)].append(p.url)
                raw_segment.setdefault(brand_key(seg), seg)
    other_keys = [set(brand_key(s["value"]).split()) for s in sources if brand_key(s["value"])]
    repeated = {k: v for k, v in segment_pages.items() if len(v) >= 2}
    dominant = max(repeated, key=lambda k: len(repeated[k]), default=None)
    for key, urls in repeated.items():
        words = set(key.split())
        if key == dominant or any(words <= other or other <= words for other in other_keys):
            sources.append({"source": "title suffix/prefix", "value": raw_segment[key], "url": urls[0], "pages": len(urls)})

    variants: dict[str, list[dict]] = defaultdict(list)
    # Every page each name was seen on and how many pages each source gave it, counted before any list is cut.
    seen_on: dict[str, set[str]] = defaultdict(set)
    by_source: dict[str, Counter] = defaultdict(Counter)
    spellings: dict[str, Counter] = defaultdict(Counter)
    for s in sources:
        key = brand_key(s["value"])
        if key:
            variants[key].append(s)
            on = set(repeated.get(key) or []) if s["source"] == "title suffix/prefix" else set()
            seen_on[key] |= on | {s["url"]}
            by_source[key][s["source"]] += len(on) or 1
            spellings[key][s["value"]] += len(on) or 1
    # A name declared in alternateName/legalName is not an inconsistency, unless it is also used as the main name.
    org_names = {k for k, v in variants.items() if any(x["source"] == "Organization name" for x in v)}
    counted = {k: v for k, v in variants.items() if k not in declared or k in org_names}
    # Different-language labels of one declared entity are not independent brand
    # identities. This is a counting qualification, not a confirmed translation.
    localized_extras = localized_name_extras(localized_names)
    counted = {k: v for k, v in counted.items() if k not in localized_extras}
    # A copyright holder can be a legal operator or rights holder, not a conflicting marketing identity
    # (owner decision, DECISIONS 256): a name seen only in the © line is not another name of the brand.
    counted = {k: v for k, v in counted.items() if any(s['source'] != 'footer legal name' for s in v)}
    # A branch (DECISIONS 221): the most-used name and 1 to 4 more words ("Demo Kafe Kadıköy Şube"), given by a
    # structured-data node on a page other than the homepage and by nothing on the homepage (the branch page's own
    # title may repeat it). Not another name of the brand: listed, not counted.
    main = max(counted, key=lambda k: (len(seen_on[k]), k), default=None)
    branches: dict[str, list[dict]] = {}
    for key, given in counted.items():
        extra = len(key.split()) - len(main.split()) if main else 0
        if (main and key != main and key.startswith(main + " ") and BRANCH_EXTRA_WORDS[0] <= extra <= BRANCH_EXTRA_WORDS[1]
                and any(x["source"] in ("Organization name", "WebSite name") for x in given)
                and not (seen_on[key] & {home}) and all(x["url"] != home for x in given)):
            branches[key] = given
    counted = {k: v for k, v in counted.items() if k not in branches}
    # A category title (DECISIONS 290): the main name and more words, given only by page titles ("Nihan Women's Coats"
    # on a collection page). The page's subject after the brand, not another name of the brand: listed, not counted.
    categories = {k for k, given in counted.items()
                  if main and k != main and k.startswith(main + " ") and all(x["source"] == "title suffix/prefix" for x in given)}
    counted = {k: v for k, v in counted.items() if k not in categories}
    findings = []
    if id_clashes:
        urls = sorted({u for c in id_clashes for us in c["names"].values() for u in us})
        findings.append(_finding(
            "STR-5", f"{len(id_clashes)} brand @id(s) carry a different name on different pages", Severity.S4,
            Confidence.VERIFIED, HYPOTHESIS, ["all answer engines that resolve brand entities"], urls,
            {"clashes": id_clashes[:20]}, "one @id, one name",
            "Give the Organization (or WebSite) node the same name wherever its @id appears; put other names in "
            "alternateName.", key_urls, [CAPPED, "Verified: the same @id is given these different names; no "
                                                 "judgement about spelling is involved."]))
    if len(counted) > 2:
        # Every page a counted name was seen on (a title suffix is seen on many pages, not only its first), so a finding
        # about the same pages' names can be told apart from this one or matched to it (DECISIONS 283 (3)).
        urls = sorted({u for k in counted for u in seen_on[k]})
        findings.append(_finding(
            "STR-5", f"The brand is named {len(counted)} different ways", Severity.S4, Confidence.ESTIMATED, HYPOTHESIS,
            ["all answer engines that resolve brand entities"], urls,
            {"variants": [{"normalized": k, "name": spellings[k].most_common(1)[0][0], "spellings": sorted(spellings[k]),
                           "pages": len(seen_on[k]), "by_source": dict(by_source[k].most_common()),
                           "seen_as": [{kk: vv for kk, vv in s.items()} for s in v][:10]}
                          for k, v in sorted(counted.items(), key=lambda kv: -len(seen_on[kv[0]]))],
             "observed_values": sorted({s["value"] for v in counted.values() for s in v}),
             "assessment": {"verified": "these values differ, as written, in the sources listed",
                            "estimated": "whether they name the same real-world entity (normalization and "
                                         "judgement, not evidence)"},
             "declared_in_schema_not_counted": declared,
             "branches_not_counted": [spellings[k].most_common(1)[0][0] for k in sorted(branches)]},
            "one brand name (plus names declared in alternateName/legalName)",
            "Use one brand name in titles, og:site_name, Organization name, footer, and logo alt; declare legitimate "
            "other names in Organization alternateName or legalName.", key_urls, sitewide=True,
            notes=[CAPPED, "Estimated: whether two spellings are 'the same name' depends on normalization (case, "
                           "punctuation, legal suffixes such as Inc/GmbH/A.Ş., a trailing 'logo')."]))
    if title_in_site_name:
        urls = sorted({row["url"] for row in title_in_site_name})
        findings.append(_finding(
            "STR-5", f"og:site_name holds the page title on {len(urls)} page(s)", Severity.S4, Confidence.VERIFIED, HYPOTHESIS,
            ["all answer engines that resolve brand entities"], urls,
            {"pages": title_in_site_name[:60], "pages_count": len(urls)},
            "og:site_name holds the site's name, the same on every page",
            "Set og:site_name to the site's name alone on these pages. The page's own title belongs in og:title.", key_urls,
            [CAPPED, "Verified: on these pages the tag's content is the page's own title, or has a title separator in it "
                     "( | , - , – , — , · or : between spaces). These values are not counted as names of the brand."]))
    # DECISIONS 283 (3): the site's name as these pages give it is one cause; "named N ways" and "og:site_name holds the
    # page title" on the same pages are one finding said twice, so they share a key and the release gate (RG-9) says so.
    for f in findings:
        if f.title.startswith("The brand is named ") or f.title.startswith("og:site_name holds the page title"):
            f.dedup_key = BRAND_NAME_KEY
    dead, inconclusive = [], []
    for url, found_on in org_urls.items():
        entry = data.links.get(url, {"source": "not_fetched", "reason": "not collected"})
        row = {"sameAs": url, "on_pages": sorted(found_on)[:5], "source": entry["source"],
               "status": entry.get("status"), "error": entry.get("error"), "reason": entry.get("reason")}
        if entry.get("status") in (404, 410):
            dead.append(row)
        elif entry["source"] == "not_fetched" or not (entry.get("status") and 200 <= entry["status"] < 400):
            inconclusive.append(row)
    if dead:
        pages_with = sorted({u for r in dead for u in r["on_pages"]})
        findings.append(_finding(
            "STR-5", f"{len(dead)} sameAs profile link(s) return 404/410", Severity.S4, Confidence.VERIFIED, HYPOTHESIS,
            ["all answer engines that resolve brand entities"], pages_with, {"links": dead},
            "sameAs links point to live profiles", "Replace or remove the dead profile URLs in Organization sameAs.",
            key_urls, [CAPPED]))
    summary = f"{len(findings)} finding(s)." if findings else f"{len(counted)} brand name variant(s); no dead sameAs links found."
    if branches:
        summary += " " + BRANCHES_NOT_COUNTED.format(names=", ".join(spellings[k].most_common(1)[0][0] for k in sorted(branches)))
    if inconclusive:
        summary += f" {len(inconclusive)} sameAs link(s) not assessed or inconclusive (see evidence)."
    has_org = home_page is not None and bool(ORGANIZATION_TYPES & _types(home_page.analysis))
    from .. import brand as identity
    identity_inputs = identity.identity_observations(result, pages)
    selected = identity.choose_identity(identity_inputs)
    alias_inputs = identity.declared_aliases(pages, selected['name'] if selected else None, urlsplit(result.origin).hostname)
    return CheckResult("STR-5", title, _status(findings), summary, findings,
                       {"name_sources": sources[:60], "name_sources_count": len(sources),
                        "identity_inputs": identity_inputs, "identity_alias_inputs": alias_inputs,
                        "localized_name_observations": localized_names,
                        "department_names_not_counted": [{"url": p.url, "name": text_value(n.get('name')), "@id": n.get('@id')}
                            for p in pages for n in department_nodes(p.analysis)],
                        "declared_identity_aliases": declared_aliases,
                        "og_site_name_holding_the_title": len(title_in_site_name),
                        "branches_not_counted": [spellings[k].most_common(1)[0][0] for k in sorted(branches)],
                        "category_titles_not_counted": [spellings[k].most_common(1)[0][0] for k in sorted(categories)],
                        "product_brands": "not read: the brand of a product a shop sells is not a name of the site",
                        "sameAs_not_assessed_or_inconclusive": inconclusive,
                        "organization_schema_on_homepage": has_org or "missing (reported once, under STR-3)",
                        "external_link_checks": ("on" if data.external_links_enabled else
                                                  "off (--no-external-links); sameAs links are still asked, at most 10")})


# -- STR-6 ---------------------------------------------------------------------

STAMPABLE = ("sitemap <lastmod>", "schema dateModified", "Last-Modified header")


def _signal(row: dict, kind: str, for_pattern: bool = False):
    """A date signal as compared per page. For spotting a sitewide pattern (`for_pattern`), a Last-Modified
    generated per request still counts: it is one more page dated the audit day, the same pattern as a cache
    time an hour old, and leaving it out would hide the pattern on exactly the sites that show it most."""
    if kind == "sitemap <lastmod>":
        return row["sitemap"]
    if kind == "schema dateModified":
        return (row["schema"].get("dateModified") or {}).get("date")
    return row["header"] if for_pattern or not row["header_is_request_time"] else None


def judge_dates(rows: list[dict], audit_day: date, cfg: CrawlConfig) -> dict:
    """STR-6's judgement over per-page date signals. Pure, so it runs the same on a saved report's rows.

    A row: url, schema {"datePublished"/"dateModified": {"date"}}, visible [{"date", "kind"}], sitemap,
    header, header_is_request_time, requested_day, use_visible.

    A signal nearly every page carries with the same date says nothing about any one page, so it is reported
    once, sitewide, and left out of the per-page comparison (root cause once):
      - dated the audit day: possible generation stamp, or legitimate same-day edits;
      - one identical other date: possible template, migration, or shared legitimate update.
    A Last-Modified header within 5 minutes of the request is generated per request and never compared.
    """
    stamped: dict[str, dict] = {}
    for kind in STAMPABLE:
        carrying = [r for r in rows if _signal(r, kind, True)]
        if len(carrying) < cfg.autostamp_min_pages:
            continue
        today = [r for r in carrying if abs((_signal(r, kind, True) - audit_day).days) <= 1]
        common, count = Counter(_signal(r, kind, True) for r in carrying).most_common(1)[0]
        if len(today) / len(carrying) >= cfg.autostamp_share:
            stamped[kind] = {"signal": kind, "how": "dated the audit day", "count": len(today),
                             "carrying": len(carrying), "urls": [r["url"] for r in today]}
        elif count / len(carrying) >= cfg.autostamp_share:
            stamped[kind] = {"signal": kind, "how": f"one identical date ({common.isoformat()})", "count": count,
                             "carrying": len(carrying),
                             "urls": [r["url"] for r in carrying if _signal(r, kind, True) == common]}
    future, conflicts, compared_pages = [], [], 0
    limit = cfg.date_conflict_days
    for r in rows:
        # HTTP representation/cache dates and sitemap resource timestamps do not establish
        # the same editorial event. Preserve them in evidence, not a conflict count.
        signals = {kind: _signal(r, kind) for kind in ('schema dateModified',)
                   if _signal(r, kind)}
        updated_shown = [v["date"] for v in r["visible"] if v["kind"] == "modified"]
        if r["use_visible"] and updated_shown:
            signals["visible 'updated' date"] = max(updated_shown)
        published = {}
        if (r["schema"].get("datePublished") or {}).get("date"):
            published["schema datePublished"] = r["schema"]["datePublished"]["date"]
        published_shown = [v["date"] for v in r["visible"] if v["kind"] == "published"]
        if r["use_visible"] and published_shown:
            published["visible 'published' date"] = min(published_shown)
        # Future dates are checked on every signal, stamped or not: a future date is wrong either way.
        every = {kind: _signal(r, kind) for kind in STAMPABLE if _signal(r, kind)}
        labeled = {f"visible {v['kind']} date": v["date"] for v in r["visible"] if v["kind"]}
        for name, d in {**every, **published, **labeled}.items():
            if d > r["requested_day"] + timedelta(days=1):
                future.append({"url": r["url"], "signal": name, "date": d.isoformat()})
        problems = []
        compared_pages += len(signals) >= 2 or bool(published and signals)  # the two comparisons below
        if len(signals) >= 2 and (max(signals.values()) - min(signals.values())).days > limit:
            problems.append(f"last-modified signals are {(max(signals.values()) - min(signals.values())).days} days apart")
        published_entity = (r['schema'].get('datePublished') or {}).get('entity')
        modified_entity = (r['schema'].get('dateModified') or {}).get('entity')
        comparable_entities = not (published_entity and modified_entity and published_entity != modified_entity)
        if published and signals and comparable_entities:
            earliest_pub = min(published.values())
            early = {k: v for k, v in signals.items() if (earliest_pub - v).days > limit}
            if early:
                problems.append(f"{', '.join(early)} is more than {limit} days before the publication date")
        if problems:
            conflicts.append({"url": r["url"], "problems": problems,
                              "signals": {k: v.isoformat() for k, v in {**signals, **published}.items()},
                              "raw_fields": {k:v.get('raw') or str(v.get('date')) for k,v in r['schema'].items()}})
    return {"stamped": stamped, "future": future, "conflicts": conflicts, "compared_pages": compared_pages}


def str6_freshness(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str],
                   str4_date_conflicts: set[str]) -> CheckResult:
    title = "Freshness signals are present and agree"
    if not pages:
        return CheckResult("STR-6", title, "not_assessed", "No indexable HTML pages.")
    audit_day = datetime.fromisoformat(result.started_at).astimezone(timezone.utc).date()
    home = homepage_url(result)
    rows = []
    header_request_time = 0
    for p in pages:
        a = p.analysis
        schema = _schema_dates(a)
        shown = visible_dates(a) if p.url not in gap else []
        header = p.headers.get("last-modified")
        header_dt = None
        try:
            header_dt = parsedate_to_datetime(header).astimezone(timezone.utc) if header else None
        except (TypeError, ValueError, IndexError):
            header_dt = None
        requested = datetime.fromisoformat(p.requested_at).astimezone(timezone.utc)
        at_request_time = bool(header_dt and abs((header_dt - requested).total_seconds()) <= 300)
        header_request_time += at_request_time
        rows.append({
            "page": p, "url": p.url, "schema": schema, "visible": shown,
            "sitemap": parse_date(result.sitemap_lastmods.get(p.url)), "header": header_dt.date() if header_dt else None,
            "header_is_request_time": at_request_time, "raw_header": header, "raw_sitemap": result.sitemap_lastmods.get(p.url),
            "requested_day": requested.date(),
            "use_visible": p.url not in str4_date_conflicts,  # schema vs visible dates were already reported by STR-4
        })

    judged = judge_dates(rows, audit_day, cfg)
    findings = []
    for kind, stamp in judged["stamped"].items():
        if kind == "sitemap <lastmod>" and not stamp["how"].startswith("dated the audit day"):
            continue  # one identical sitemap date is IDX-5's finding; it is still left out of the comparison here
        findings.append(_finding(
            "STR-6", f"{kind} looks auto-stamped: {stamp['count']} of {stamp['carrying']} pages carry "
                     f"{'a date within ±1 day of the audit' if stamp['how'].startswith('dated') else stamp['how']}",
            Severity.INFO, Confidence.INFERRED, HYPOTHESIS, ["answer engines judging freshness"], stamp["urls"],
            {"signal": kind, "pattern": stamp["how"], "audit_day": audit_day.isoformat(),
             "pages_with_signal": stamp["carrying"], "pages_matching": stamp["count"],
             "min_pages": cfg.autostamp_min_pages, "share": cfg.autostamp_share},
            "dates change only when the content changes", f"Verify {kind} against actual edit records; change date generation only if inaccurate.",
            key_urls, sitewide=True,
            notes=[CAPPED, f"Thresholds ({cfg.autostamp_min_pages} pages, {cfg.autostamp_share:.0%}) are uncalibrated "
                           "guesses.", "Verified: the dates are as shown. That they were generated rather than set "
                           "from real edits is Inferred from the pattern, and is why this signal is left out of the "
                           "per-page comparison (reported once, here)."]
            + (['Same-day Last-Modified headers do not establish incorrect edit dates or a cache cause. Compare with publication records before changing date generation.']
               if kind == "Last-Modified header" else [])))

    undated, not_assessed = [], []
    template = product_template(pages, home)
    for r in rows:
        p = r["page"]
        kind, basis = page_kind(p, home, template["products"])
        is_article = kind == "article" or bool(ARTICLE_TYPES & _types(p.analysis))
        if is_article and p.url not in gap and not r["visible"]:
            english, why = english_text_assessable(p.analysis)
            if english:
                undated.append({"url": r["url"], "classified_by": basis or "Article-type structured data",
                                "schema_dates": {k: v["raw"] for k, v in r["schema"].items()}})
            else:
                not_assessed.append({"url": r["url"], "reason": f"no <time> or numeric date; month names are "
                                                                 f"matched in English only ({why})"})
    future, conflicts, compared_pages = judged["future"], judged["conflicts"], judged["compared_pages"]
    limit = cfg.date_conflict_days
    if future:
        urls = sorted({f["url"] for f in future})
        findings.append(_finding("STR-6", f"{len(urls)} page(s) carry a future date", Severity.S4, Confidence.VERIFIED,
                                 HYPOTHESIS, ["answer engines judging freshness"], urls, {"dates": future[:60]},
                                 "no date later than today", "Correct the future-dated value.", key_urls,
                                 [CAPPED, "Unlabeled visible dates (events, deadlines) are not counted."]))
    if conflicts:
        urls = [c["url"] for c in conflicts]
        findings.append(_finding(
            "STR-6", f"{len(urls)} page(s) have date signals more than {limit} days apart", Severity.S4,
            Confidence.VERIFIED, HYPOTHESIS, ["answer engines judging freshness"], urls, {"pages": conflicts[:60]},
            "Dates for the same event agree; publication and modification remain distinct", "Compare each reported signal with records for the same event; correct only supported contradictions and preserve publication versus modification dates.",
            key_urls, [CAPPED, "A Last-Modified header equal to the request time is treated as generated per request and "
                               "not compared; auto-stamped signals are not compared either."]))
    if undated:
        urls = [u["url"] for u in undated]
        findings.append(_finding(
            "STR-6", f"{len(urls)} article-type page(s) show no published or updated date", Severity.INFO,
            Confidence.ESTIMATED, HYPOTHESIS, ["answer engines judging freshness"], urls, {"pages": undated[:60]},
            "a visible published/updated date", "Show the published and last-updated dates on the page.", key_urls,
            ["Estimated: article type is guessed from the URL path, og:type, or Article structured data."]))
    observations = [{"metric": "pages whose Last-Modified header equals the request time (generated per request)",
                     "value": header_request_time}] if header_request_time else []
    agreement = (f"date signals agree on the {compared_pages} of {len(rows)} page(s) that carry two or more"
                 if compared_pages else f"none of the {len(rows)} page(s) carries two date signals, so agreement "
                                        "could not be checked")
    summary = f"{len(findings)} finding(s)." if findings else (
        f"{agreement[0].upper()}{agreement[1:]}; no date is in the future, and article pages show a date.")
    if not_assessed:
        summary += f" 'No visible date' not assessed on {len(not_assessed)} non-English page(s)."
    return CheckResult("STR-6", title, _status(findings), summary, findings,
                       {"audit_day": audit_day.isoformat(), "not_assessed": not_assessed[:40],
                        "not_assessed_count": len(not_assessed), "pages_with_two_or_more_signals": compared_pages,
                        "agreement_not_assessable_pages": len(rows) - compared_pages,
                        "stamped_signals_not_compared": {k: v["how"] for k, v in judged["stamped"].items()},
                        "per_page": [{"url": r["url"], "schema": {k: v["raw"] for k, v in r["schema"].items()},
                                      "visible": [f'{_iso(v["date"])} ({v["kind"] or "unlabeled"})' for v in r["visible"]][:5],
                                      "sitemap_lastmod": r["raw_sitemap"], "last_modified_header": r["raw_header"]}
                                     for r in rows][:60],
                        "thresholds": {"conflict_days": limit, "autostamp_min_pages": cfg.autostamp_min_pages,
                                       "autostamp_share": cfg.autostamp_share}}, observations)


# -- STR-7 ---------------------------------------------------------------------

DECORATIVE_HINT = re.compile(r"icon|sprite|spacer|pixel|blank|divider|bullet|arrow|avatar|emoji", re.I)
# A file name says what an image shows only as a whole word of that name: "fon-header-map-mobil.jpg" and
# "chart_2024.png" do, "roadmap.png", "vegetable.jpg" and the host "maps.googleapis.com" do not (decision 186).
MEANINGFUL_WORDS = frozenset({"chart", "graph", "diagram", "infographic", "screenshot", "product", "figure", "table",
                              "map", "photo"})
# Hosts that serve map tiles and map controls (the squares of an embedded map, its pin, its transparent overlay):
# decorative whatever their name. Matched as the host itself or any subdomain of it. Only the two Google hosts were
# seen in a real report (2026-10-12); the rest are an agent default (LAUNCH-GATE).
MAP_HOSTS = ("maps.googleapis.com", "maps.gstatic.com", "maps.google.com", "tile.openstreetmap.org", "api.mapbox.com",
             "tiles.mapbox.com", "api.maptiler.com", "arcgisonline.com", "maps.yandex.net", "static-maps.yandex.ru")
MAP_IMAGE = "a map tile or map control (decorative)"
# The size a browser gives an image that has none of its own (an SVG without dimensions). A page reader that saves
# the page as a browser built it writes that size into the copy as width="300" height="150": in the saved copies of
# four sites (2026-10-11) every image with exactly this size was an SVG. It says nothing about how large the image
# is shown, so it is not size evidence.
UNSIZED_DEFAULT = (300, 150)
# The same kind of image this many times on one page (one folder, one file type: a flag for every row of a table)
# is listed as one row with its count.
SAME_PATTERN_ROWS = 5
BESIDE_LABEL = "beside its own label (the text next to it says what it shows)"


_PLACEHOLDER_FILE = re.compile(PLACEHOLDER_ALT_FILE, re.I)


def placeholder_alt(img: dict) -> str | None:
    """Why an image's alt text names no image (H16), or None: a placeholder word or a theme's default (`PLACEHOLDER_ALTS`
    and `PLACEHOLDER_ALTS_MORE`, compared folded, the WHOLE alt: "Foto" is one, "Foto der Praxis" is not), or a file
    name or a camera's numbering. An alt equal to the title attribute is not a sign (G09): shop and blog themes write
    the product's or the post's own name in both."""
    alt = (img.get("alt") or "").strip()
    if not alt:
        return None
    plain = " ".join(re.sub(r"[^\w]+", " ", fold(alt)).split())
    if plain in PLACEHOLDER_ALTS or plain in PLACEHOLDER_ALTS_MORE:
        return "a placeholder word"
    if _PLACEHOLDER_FILE.search(alt):
        return "a file name"
    return None


def name_words(src: str) -> list[str]:
    """The words of an image's file name: the last path segment without query, fragment or extension, percent-decoded,
    split at anything that is not a letter and at a lower-to-upper case change. A data: address has no file name."""
    if src.strip().lower().startswith("data:"):
        return []
    path = src.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if "://" in path or path.startswith("//"):
        path = urlsplit(path).path.rstrip("/")
    name = unquote(path.rpartition("/")[2])
    if "." in name:
        name = name.rsplit(".", 1)[0]
    name = "".join(" " + char if char.isupper() and index and name[index - 1].islower() else char
                   for index, char in enumerate(name))
    return [word.lower() for word in re.findall(r"[^\W\d_]+", name)]


def name_hint(src: str) -> bool:
    """True when the file name has a word that says the image carries information: a list word, or that word + "s"."""
    return any(word in MEANINGFUL_WORDS or (word.endswith("s") and word[:-1] in MEANINGFUL_WORDS) for word in name_words(src))


def map_host(src: str) -> bool:
    """True for an image served by a map host (`MAP_HOSTS`) or any subdomain of one."""
    if src.strip().lower().startswith("data:") or ("://" not in src and not src.startswith("//")):
        return False
    try:
        host = (urlsplit(src.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == known or host.endswith("." + known) for known in MAP_HOSTS)


def src_pattern(src: str) -> str:
    """An image address as its folder and file type: "https://cdn.test/country/*.svg"."""
    path = src.split("?", 1)[0].split("#", 1)[0]
    folder, _, name = path.rpartition("/")
    return f"{folder}/*.{name.rsplit('.', 1)[-1].lower() if '.' in name else ''}"


def group_same_pattern(rows: list[dict]) -> list[dict]:
    """Rows of one page that share a src pattern `SAME_PATTERN_ROWS` or more times become one row with `count`."""
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        by_key[(row["url"], src_pattern(row["src"]), row["alt_state"], row["why"])].append(row)
    out = []
    for (_, pattern, _, _), same in by_key.items():
        if len(same) >= SAME_PATTERN_ROWS and not same[0]["src"].startswith("data:"):
            out.append({**same[0], "src_pattern": pattern, "count": len(same)})
        else:
            out.extend(same)
    return out


def image_total(rows: list[dict]) -> int:
    return sum(row.get("count", 1) for row in rows)


# H29, G08: an image file over the first size is heavy (S4), over the second very heavy (S3 on the homepage or a key
# page, S4 elsewhere); a video over the third (S4). The sizes live in config.
_FORMAT_NEGOTIATED = re.compile(FORMAT_NEGOTIATING_IMAGE, re.I)
# Formats lighter than the older one a file name promises: an image service sends them for a .jpg or .png address
# when the browser accepts them (G07), which is the point of the service, not a photo left unconverted.
MODERN_IMAGE_TYPES = frozenset({"image/webp", "image/avif"})
# H29: what a file name's extension promises, to compare with the Content-Type the server sends.
EXTENSION_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
                   "webp": "image/webp", "avif": "image/avif", "svg": "image/svg+xml"}


def media_size(row: dict) -> int | None:
    """A sampled file's size in bytes: its Content-Length, or the bytes read when the whole file was read. None
    when neither says (a chunked answer cut at the byte cap): unknown, not small."""
    try:
        return int(row["content_length"])
    except (KeyError, TypeError, ValueError):
        return row.get("body_bytes") if row.get("body_truncated") is False else None


def negotiated_format(row: dict, ext: str, kind: str) -> str | None:
    """Why a sampled image's Content-Type may differ from its name without anything being wrong (G07), or None: the
    answer varies with the Accept header, the address is an image service's that picks the format, or the server
    sent a modern format (WebP, AVIF) for an older name."""
    if "accept" in [part.strip().lower() for part in (row.get("vary") or "").split(",")]:
        return "the answer varies with the Accept header (Vary: Accept)"
    if _FORMAT_NEGOTIATED.search(row.get("url") or ""):
        return "an image service's address that picks the format for the browser"
    if kind in MODERN_IMAGE_TYPES and EXTENSION_TYPES.get(ext) not in MODERN_IMAGE_TYPES:
        return f"{kind} is lighter than the {EXTENSION_TYPES.get(ext)} the name says"
    return None


def media_weight_findings(images: list[dict], videos: list[dict], key_urls: set[str], home: str | None = None) -> list:
    """H29: sampled image files that are heavy or carry a format their name does not say, and video files the pages
    play that are heavy. Sizes come from the answers to the sample STR-7 requests, not from downloading the files.
    A file over IMAGE_VERY_HEAVY_BYTES makes the finding S3 only when it is shown on the homepage (`home`) or a key
    page; elsewhere it stays S4 (G08): one finding either way, listing the files."""
    findings = []
    important = set(key_urls) | ({home} if home else set())
    ok = [row for row in images if row.get("status") and 200 <= row["status"] < 300]
    heavy = sorted(({"image": row["url"], "bytes": media_size(row), "shown_on": row["pages"]} for row in ok
                    if (media_size(row) or 0) > IMAGE_HEAVY_BYTES), key=lambda r: -r["bytes"])
    if heavy:
        urls = sorted({page for row in heavy for page in row["shown_on"]})
        worst = Severity.S3 if any(row["bytes"] > IMAGE_VERY_HEAVY_BYTES and important & set(row["shown_on"])
                                   for row in heavy) else Severity.S4
        findings.append(_finding(
            "STR-7", f"{len(heavy)} sampled image file(s) are over 500 KB", worst, Confidence.VERIFIED,
            Rationale.MEASURED.value, ["page speed for every reader", "Google Images"], urls,
            {"images": heavy[:60], "sampled": len(ok), "unknown_size": sum(media_size(row) is None for row in ok),
             "thresholds_bytes": {"S4": IMAGE_HEAVY_BYTES, "S3": IMAGE_VERY_HEAVY_BYTES}},
            "content images well under 500 KB each", "Shrink the image to the largest size it is shown at and "
            "compress it (or serve WebP/AVIF); then replace the file at the same address.", key_urls,
            ["Sizes are the Content-Length the server sent for a sample of image files; S3 when one over 1 MB is shown "
             "on the homepage or a key page."]))
    mismatched, negotiated = [], 0
    for row in ok:
        kind = (row.get("content_type") or "").split(";")[0].strip().lower()
        ext = urlsplit(row["url"]).path.rsplit("/", 1)[-1].rpartition(".")[2].lower()
        if kind.startswith("image/") and EXTENSION_TYPES.get(ext) not in (None, kind):
            if negotiated_format(row, ext, kind):
                negotiated += 1
                continue
            mismatched.append({"image": row["url"], "name_says": EXTENSION_TYPES[ext], "content_type": kind,
                               "shown_on": row["pages"]})
    if mismatched:
        urls = sorted({page for row in mismatched for page in row["shown_on"]})
        findings.append(_finding(
            "STR-7", f"{len(mismatched)} sampled image file(s) are served in a format their file name does not say",
            Severity.INFO, Confidence.VERIFIED, HYPOTHESIS, ["Google Images", "page speed for every reader"], urls,
            {"images": mismatched[:60], "left_out_as_format_negotiation": negotiated}, "each image file's name and Content-Type name the same format",
            "Replace the file with one exported in the format its name says (or rename it and update the pages); a PNG "
            "photo saved as .jpg is usually also much larger than a real JPEG.", key_urls,
            ["Browsers read the file's own bytes, so the image still shows; the mismatch usually means a photo was "
             "never converted to JPEG or WebP."]))
    big_videos = sorted(({"video": row["url"], "bytes": media_size(row), "content_type": row.get("content_type"),
                          "shown_on": row["pages"], "found_by": row.get("found_by") or "markup"}
                         for row in videos if row.get("source") == "fetched"
                         and row.get("status") and 200 <= row["status"] < 300
                         and (media_size(row) or 0) > VIDEO_HEAVY_BYTES), key=lambda r: -r["bytes"])
    if big_videos:
        urls = sorted({page for row in big_videos for page in row["shown_on"]})
        findings.append(_finding(
            "STR-7", f"{len(big_videos)} video file(s) the pages play are over 5 MB", Severity.S4, Confidence.VERIFIED,
            Rationale.MEASURED.value, ["page speed for every reader"], urls, {"videos": big_videos[:20],
                                                                               "threshold_bytes": VIDEO_HEAVY_BYTES},
            "videos under 5 MB, or loaded only when played",
            "Reduce the video's size (shorter, lower bitrate), add preload=\"none\" or a poster image, or host it on a "
            "video platform and embed it.", key_urls,
            ["An autoplaying or preloaded video is downloaded with the page, on mobile data too."]
            + (["A file found only in a VideoObject's contentUrl is the video the page says it plays; whether the page "
                "downloads it before it is played was not observed."]
               if any(row["found_by"] == "structured_data" for row in big_videos) else [])))
    return findings


def image_loading_findings(pages: list, key_urls: set[str]) -> list:
    """H30, from the markup: content images with neither width and height nor an inline aspect-ratio (the browser
    cannot keep their space, so the page shifts as they load), and image preloads that declare type="image/jpg",
    which is not a media type: a browser that checks the type skips the preload. An image the markup shows sized
    another way (a sizing class or style, a sized <source> of its <picture>, a lazy loader's data-src placeholder;
    `css_sized`, G12) is not counted. A note on most pages is one site-wide note."""
    from ..structure_data import content_images

    findings, unsized, wrong_type = [], [], []
    for page in pages:
        # A map's tiles and pins are placed by the map's own script, not by the page's flow (decision 186).
        images = [img for img in content_images(page) if not img.get("aspect_ratio") and not img.get("css_sized")
                  and not map_host(img["url"]) and (img.get("width") is None or img.get("height") is None)]
        if images:
            unsized.append({"url": page.url, "images": len(images), "examples": [img["url"] for img in images[:3]]})
        wrong_type += [{"url": page.url, "preload": row["href"], "type": row["type"]}
                       for row in page.analysis.get("image_preloads") or [] if row.get("type") == "image/jpg"]
    if unsized:
        urls = [row["url"] for row in unsized]
        findings.append(_finding(
            "STR-7", f"{sum(row['images'] for row in unsized)} image(s) on {len(urls)} page(s) have no width and height "
            "(layout shift risk)", Severity.INFO, Confidence.VERIFIED, HYPOTHESIS, ["page experience for every reader"],
            urls, {"pages": unsized[:60]}, "each content image declares its width and height (or an aspect-ratio)",
            "Add width and height attributes with the image's own pixel size (CSS can still scale it), or an "
            "aspect-ratio in its style.", key_urls,
            ["Cumulative Layout Shift is a Core Web Vital; whether these images move the page depends on the CSS, "
             "which the audit does not apply."], sitewide=len(urls) >= max(SITEWIDE_MIN_PAGES, len(pages) / 2)))
    if wrong_type:
        urls = sorted({row["url"] for row in wrong_type})
        findings.append(_finding(
            "STR-7", f"{len(wrong_type)} image preload(s) declare type=\"image/jpg\", which is not a media type",
            Severity.INFO, Confidence.VERIFIED, Rationale.DOCUMENTED.value, ["page speed for every reader"], urls,
            {"preloads": wrong_type[:20]}, "a preload type a browser recognises (image/jpeg), or none",
            "Change type=\"image/jpg\" to type=\"image/jpeg\" on the <link rel=preload>, or remove the type.", key_urls,
            ["A browser skips a preload whose type it does not support, so the image is fetched late."]))
    return findings


def image_file_findings(pages: list, key_urls: set[str], data, home: str | None = None) -> tuple[list, list[dict], dict]:
    """STR-7's two additions: image files that do not load (from the sample the collector requested), and the
    share of images offered in a current format. Returns (findings, observations, evidence)."""
    from ..structure_data import content_images

    findings, observations = [], []
    sampled = list((getattr(data, "images", None) or {}).values())
    fetched = [row for row in sampled if row.get("source") == "fetched"]
    broken = []
    for row in fetched:
        status, kind = row.get("status"), (row.get("content_type") or "").split(";")[0].strip().lower()
        if row.get("error") or status is None:
            problem = f"request failed: {row.get('error')}"
        elif status >= 400:
            problem = f"HTTP {status}"
        elif 200 <= status < 300 and kind and not kind.startswith("image/") and kind != "application/octet-stream":
            problem = f"answers with {kind}, not an image"
        else:
            continue
        broken.append({"image": row["url"], "problem": problem, "status": status, "shown_on": row["pages"]})
    if broken:
        urls = sorted({page for row in broken for page in row["shown_on"]})
        findings.append(_finding(
            "STR-7", f"{len(broken)} of {len(fetched)} sampled image file(s) do not load", Severity.S3, Confidence.VERIFIED,
            Rationale.SELF_EVIDENT.value, ["Google Images", "multimodal answers", "every reader of the page"], urls,
            {"images": broken[:60], "sampled": len(fetched),
             "reproduce": f"curl -sI {shlex.quote(broken[0]['image'])}"},
            "every image on a page loads", "Restore the file or correct the address in the page.", key_urls,
            ["A sample, not every image: the audit requests a limited number of image files, spread over the pages."]))
    not_fetched = Counter(row.get("reason", "") for row in sampled if row.get("source") != "fetched")
    from ..evidence_accuracy import image_formats, FORMAT_ACTION, FORMAT_EXPECTED
    assessment = image_formats(pages, sampled)
    images = assessment['occurrences']
    observations.append({'metric': 'Image format references in markup; delivery is a separate response assessment', **assessment})
    if images >= MIN_IMAGES_FOR_FORMAT_SHARE:
        urls = sorted({r['page'] for r in assessment['markup_references']})
        findings.append(_finding(
            "STR-7", f"{assessment['markup_modern_occurrences']} of {images} image occurrence(s) reference WebP or AVIF in markup; delivery assessed separately",
            Severity.INFO, Confidence.ESTIMATED, HYPOTHESIS, ["page speed for every reader"], urls,
            {'format_assessment': assessment}, FORMAT_EXPECTED, FORMAT_ACTION, key_urls,
            [assessment['limits']]))
    findings += media_weight_findings(fetched, list((getattr(data, "videos", None) or {}).values()), key_urls, home)
    evidence = {"image_files_sampled": len(sampled), "image_files_requested": len(fetched),
                "image_files_not_requested": dict(not_fetched),
                "distinct_content_images": getattr(data, "image_candidates", 0), "format_assessment": assessment}
    return findings, observations, evidence


def str7_alt(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str], data=None) -> CheckResult:
    title = "Images: alt text, files that load, formats"
    checked = [p for p in pages if p.url not in gap]
    meaningful, other = [], []
    equivalent_images = []
    placeholder_alts = []
    role_reviews = []
    total = missing_total = empty_total = rnd4_excluded = details_not_assessed = 0
    empty_alt_not_assessed = no_source = map_left_out = 0
    for p in checked:
        a = p.analysis
        counts = a.get("image_counts")
        for img in a["images"]:
            in_content = img["in_main"] if a["has_main_region"] else not img["in_chrome"]
            if not in_content:
                continue
            if not isinstance(counts, dict):
                total += 1
            if img["alt"] is not None and img["alt"].strip():
                why = None if img.get('declared_decorative') else placeholder_alt(img)
                if why:
                    placeholder_alts.append({'url':p.url,'src':img.get('src'),'alt':img['alt'],'why':why,
                        'element_id':img.get('element_id'),'requested_at':getattr(p,'requested_at',None),
                        'observed_at':(a.get('content_observation')or{}).get('observed_at')or getattr(p,'requested_at',None),
                        'source':(a.get('content_observation')or{}).get('source')or getattr(p,'view','unknown'),
                        'context':{k:img.get(k)for k in('declared_decorative','equivalent_text','equivalent_text_basis','role_assessment')},
                        'qualification':'Whole-value placeholder estimate; inspect actual image purpose and equivalent text before choosing alt.'})
                continue
            if not isinstance(counts, dict):
                if img["alt"] is None:
                    missing_total += 1
                else:
                    empty_total += 1
            if banner_shaped_without_alt(img):
                rnd4_excluded += 1  # RND-4 already reports it as a possible image of text
                continue
            w, h, src = img["width"], img["height"], img["src"] or ""
            if not src:
                no_source += 1  # no src and no lazy-load address: nothing is shown, so there is nothing to describe
                continue
            # An image written into the page as a data: address is stored as its start and its size, not whole.
            row = {"url": p.url, "src": shared_elements.short_data_address(src), "width": w, "height": h,
                   "alt_state": "missing" if img["alt"] is None else "empty",
                   "element_id": img.get('element_id'),
                   "observed_at": (a.get('content_observation') or {}).get('observed_at') or getattr(p, "requested_at", None),
                   "source": (a.get('content_observation') or {}).get('source') or getattr(p,'view','unknown'),
                   "context": {k: img[k] for k in ('equivalent_text', 'equivalent_text_basis', 'role_assessment', 'table_context', 'presentation_context') if k in img}}
            if img.get("lazy"):
                row["lazy_loaded"] = True  # `src` here is the address the page loads on scroll (data-src and similar)
            if map_host(src):
                # A tile, a pin or an overlay of an embedded map: decorative whatever its name or size (decision 186).
                if img["alt"] == "":
                    map_left_out += 1
                else:
                    other.append({**row, "why": MAP_IMAGE})
                continue
            if (w, h) == UNSIZED_DEFAULT:
                w = h = None  # the browser's size for an unsized image, not the image's own
            if img.get('functional_unlabelled_link'):
                meaningful.append({**row, "why": "image-only link without an accessible name"})
            elif img.get('declared_decorative') and img['alt'] == '':
                equivalent_images.append({**row, 'why': 'explicit presentation/hidden role and empty alt',
                                          'qualification': 'declared intent, not visual certification'})
            elif img.get('informative_context'):
                meaningful.append({**row, 'why': 'informative caption: ' + img['informative_context']})
            elif img.get('equivalent_text_basis') or img.get('beside_label'):
                equivalent_images.append({**row, 'why': img.get('equivalent_text_basis') or BESIDE_LABEL,
                                          'qualification': 'structural estimate; image pixels/interaction not reviewed'})
                if img['alt'] is None:
                    other.append({**row, "why": BESIDE_LABEL})
            else:
                role_reviews.append({**row, 'why': 'image role unresolved: wrapper, file name and intrinsic dimensions alone do not establish information conveyed',
                                     'qualification': 'not assessed; inspect displayed image, CSS, function and equivalent written content'})
                if img['alt'] == '':
                    empty_alt_not_assessed += 1
                else:
                    other.append({**row, "why": "no size or hint to tell"})
        if isinstance(counts, dict):
            region = counts.get("main_content" if a["has_main_region"] else "outside_chrome", {})
            total += region.get("total", 0)
            missing_total += region.get("missing_alt", 0)
            empty_total += region.get("empty_alt", 0)
            details_not_assessed += max(0, region.get("total", 0) - region.get("details_retained", 0))
    meaningful, other = group_same_pattern(meaningful), group_same_pattern(other)
    findings = []
    if meaningful:
        # The same image without alt text on most pages (a banner every page carries) is one element: reported once
        # for the whole site, by its src, and taken out of each page's row (maya_audit.shared_elements).
        by_page: dict[str, set] = defaultdict(set)
        for r in meaningful:
            by_page[r["url"]].add(r["src"])
        shared = shared_elements.split(by_page, [p.url for p in checked])
        everywhere = [r for r in meaningful if r["src"] in shared]
        meaningful = [r for r in meaningful if r["src"] not in shared]
        urls = sorted({r["url"] for r in meaningful})
        without = image_total([r for r in meaningful if r["alt_state"] == "missing"])
        emptied = image_total(meaningful) - without
        per_page = _finding(
            "STR-7", f"{image_total(meaningful)} likely meaningful image(s) on {len(urls)} page(s): {without} with no alt text, "
                     f"{emptied} with an empty alt",
            Severity.S4, Confidence.ESTIMATED, HYPOTHESIS, ["multimodal answers", "all answer engines that read alt text"],
            urls, {"images": meaningful[:60], "images_count": image_total(meaningful), "no_alt": without, "empty_alt": emptied},
            "informative images describe what they show",
            "Add alt text that states what the image shows (for charts, the key numbers).", key_urls,
            [CAPPED, "The missing attribute is Verified; informative purpose is Estimated from function and explicit content context.",
             "Equivalent text and declared decorative intent are reviewed separately. Missing CSS, pixels or role evidence remains unassessed; intrinsic size, file name and figure wrappers do not prove purpose."])
        if meaningful:
            findings.append(per_page)
        for src in sorted(shared):
            rows = [r for r in everywhere if r["src"] == src]
            on = sorted({r["url"] for r in rows})
            shown = shared_elements.shown_address(src, result.origin)
            findings.append(shared_elements.finding(
                per_page, "image_no_alt", {"type": "image", "src": shown, "where": shared_elements.REPEATED}, on,
                {"images": rows[:5]}, importance_tier=_tier(on, key_urls), section=shared.section(src, on), src=shown))
    if placeholder_alts:
        urls=sorted({r['url']for r in placeholder_alts})
        findings.append(_finding("STR-7",f"{len(placeholder_alts)} image(s) on {len(urls)} page(s) have likely placeholder alt text",
            Severity.S4,Confidence.ESTIMATED,HYPOTHESIS,['screen readers'],urls,{'images':placeholder_alts,
                'source_collection_times':sorted({r['observed_at']for r in placeholder_alts if r.get('observed_at')})},
            'informative images have purpose-appropriate descriptions, not file names or placeholder labels',
            'Inspect each image and equivalent written text. Replace a placeholder with a description of its actual purpose when informative; preserve appropriate empty alt for decoration. Do not invent an image description from its filename.',key_urls,
            ['Estimated from the whole alt value; visual purpose and equivalent text still require review.']))
    if other:
        urls = sorted({r["url"] for r in other})
        findings.append(_finding(
            "STR-7", f"{image_total(other)} other image(s) on {len(urls)} page(s) have no alt attribute", Severity.INFO,
            Confidence.VERIFIED, HYPOTHESIS, ["multimodal answers"], urls, {"images": other[:60]},
            'decorative images carry alt=""', 'Add alt="" to decorative images, or descriptive alt text otherwise.',
            key_urls))
    observations = [{"metric": "main-content images without an alt attribute / total", "missing": missing_total,
                     "empty_alt": empty_total, "total": total,
                     "left_to_RND-4_as_possible_image_of_text": rnd4_excluded}]
    try:
        home = homepage_url(result)
    except AttributeError:  # a result rebuilt without page depths (unit tests, saved copies): no homepage to weigh by
        home = None
    file_findings, file_observations, file_evidence = image_file_findings(checked, key_urls, data, home)
    findings += file_findings + image_loading_findings(checked, key_urls)
    observations += file_observations
    classified_total = max(0, total - details_not_assessed)
    summary = (f"{len(findings)} finding(s)." if findings
               else f"No missing alt attribute was found in the {classified_total} image detail(s) retained "
                    f"({total} main-content image(s) counted; banner-shaped ones are left to RND-4).")
    if details_not_assessed:
        summary += f" {details_not_assessed} image(s) exceeded the extraction detail cap and were not classified."
    if empty_alt_not_assessed:
        summary += f" {empty_alt_not_assessed} empty-alt image(s) could not be classified as decorative or meaningful."
    return CheckResult("STR-7", title, _status(findings), summary, findings,
                       {"pages_checked": len(checked), "excluded_as_rnd1_root_cause": sorted(gap),
                        "image_details_not_assessed_count": details_not_assessed,
                        "empty_alt_not_assessed_count": empty_alt_not_assessed,
                        "equivalent_description_reviews": equivalent_images,
                        "unassessed_image_roles": role_reviews,
                        "images_with_no_source_skipped": no_source, "map_images_left_out_count": map_left_out,
                        **file_evidence,
                        "scope": "every image in the main content of every checked page; images in the header, "
                                 "navigation and footer (the logo, menu icons) are left out on purpose",
                        "lazy_loading": "an image with an empty or placeholder src is read from data-src, data-srcset, "
                                        "data-lazy-src or data-original"}, observations)


# -- STR-8 ---------------------------------------------------------------------

COMPARISON_PATH = re.compile(r"(^|/)(pricing|plans|prices|compare|comparison|specs|specifications)(/|$)|-vs-", re.I)
# A page that has a real table (header cells and at least this many rows) keeps its tabular facts in a <table>: its
# <div> grids are layout beside it, not a table that is missing (DECISIONS 200).
REAL_TABLE_ROWS = 2
# A grid with a form control inside or a <form> around, and an empty <table> in such a block (DECISIONS 223).
CALCULATOR_LEFT_OUT = "a calculator or form: its rows are input fields, not a table of facts"


def str8_semantic_tables(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str]) -> CheckResult:
    title = "Semantic HTML for comparative and structured facts"
    checked = [p for p in pages if p.url not in gap]
    comparisons, others, numbered, left_out, empty = [], [], [], [], []
    for p in checked:
        path = urlsplit(p.url).path
        # A <table> with no row at all (it was recorded and never reported until DECISIONS 200). One inside a form or
        # a calculator's block is where the calculator writes its result: left out (DECISIONS 223).
        without_rows = sum(1 for table in p.analysis["tables"] if not table.get("rows") and not table.get("has_controls"))
        if without_rows:
            empty.append({"url": p.url, "tables": without_rows})
        in_forms = sum(1 for table in p.analysis["tables"] if not table.get("rows") and table.get("has_controls"))
        if in_forms:
            left_out.append({"url": p.url, "container": "table", "rows": 0, "tables": in_forms, "why": CALCULATOR_LEFT_OUT})
        real = [table for table in p.analysis["tables"] if table.get("has_th") and (table.get("rows") or 0) >= REAL_TABLE_ROWS]
        # What the rows of the page's real tables (those with header cells) are about.
        in_tables = {_norm(label) for table in p.analysis["tables"] if table.get("has_th") for label in table.get("row_labels") or []}
        for grid in p.analysis["div_grids"]:
            if grid.get("has_controls") or grid.get("calculator_named"):
                left_out.append({"url": p.url, "container": grid["container"], "rows": grid["rows"],
                                 **({"selector": grid["selector"]} if grid.get("selector") else {}), "why": CALCULATOR_LEFT_OUT})
                continue
            labels = [_norm(label) for label in grid.get("row_labels") or [] if _norm(label)]
            copied = sum(1 for label in labels if label in in_tables)
            if grid.get("in_collapse") or (labels and copied * 2 >= len(labels)):
                # A grid that folds away, or that repeats a real table of the same page, is another view of facts
                # the page already holds in a <table> (or shows only on a click): not a table that is missing.
                left_out.append({"url": p.url, "container": grid["container"], "rows": grid["rows"],
                                 "why": "inside a collapse or accordion" if grid.get("in_collapse")
                                 else f"{copied} of {len(labels)} row labels are in a real <table> with header cells on this page"})
                continue
            if real:
                left_out.append({"url": p.url, "container": grid["container"], "rows": grid["rows"],
                                 **({"selector": grid["selector"]} if grid.get("selector") else {}),
                                 "why": f"the page has a real <table> with header cells and {max(table['rows'] for table in real)} rows"})
                continue
            cells = " ".join(t for row in grid["sample_rows"] for t in row)
            has_price = bool(price_tokens(cells))
            row = {"url": p.url, **grid, "has_price": has_price}
            if has_price or COMPARISON_PATH.search(path):
                comparisons.append({**row, "why": "prices in the cells" if has_price else "pricing/comparison URL path"})
            else:
                others.append(row)
        for run in p.analysis["numbered_paragraph_runs"]:
            numbered.append({"url": p.url, **run})
    findings = []
    semantic = [{"url": p.url, "requested_at": getattr(p, "requested_at", None), **row}
                for p in checked for row in p.analysis.get("_table_semantics", [])
                if row["assessment"] == "missing_headers" and row["parser_complete"]]
    if semantic:
        urls = sorted({r["url"] for r in semantic})
        findings.append(_finding("STR-8", f"{len(semantic)} data table(s) on {len(urls)} page(s) lack supported header associations",
            Severity.S4, Confidence.ESTIMATED, HYPOTHESIS, ["screen readers"], urls,
            {"tables": semantic, "tables_count": len(semantic), "affected_pages": len(urls)},
            "data cells have meaningful row or column headers",
            "Associate data with meaningful native headers or explicit accessible header references; verify with a screen reader. No ranking penalty is established.", key_urls,
            ["Estimated from saved HTML structure; visual layout and assistive-technology interaction were not tested."]))
    if comparisons:
        urls = sorted({r["url"] for r in comparisons})
        findings.append(_finding(
            "STR-8", f"{len(urls)} page(s) lay out pricing or spec comparisons as <div> grids instead of <table>",
            Severity.S4, Confidence.ESTIMATED, HYPOTHESIS, ["answer engines answering comparison questions"], urls,
            {"grids": comparisons[:40]}, "comparisons in <table> with header cells",
            "Use a <table> with <th> headers for the comparison (it can keep the same visual design).", key_urls,
            [CAPPED, "Estimated: a 'grid' is repeated rows with the same short cells; 'pricing/spec' is from prices in the "
                     "cells or the URL path."]))
    if others:
        urls = sorted({r["url"] for r in others})
        findings.append(_finding(
            "STR-8", f"{len(urls)} page(s) have other table-like <div> grids", Severity.INFO, Confidence.ESTIMATED,
            HYPOTHESIS, ["answer engines answering comparison questions"], urls, {"grids": others[:40]},
            "tabular facts in <table>", "If this is tabular data, use a <table>.", key_urls))
    if empty:
        urls = sorted(row["url"] for row in empty)
        findings.append(_finding(
            "STR-8", f"{len(urls)} page(s) contain an empty <table> element", Severity.S4, Confidence.VERIFIED, HYPOTHESIS,
            ["answer engines answering comparison questions", "screen readers"], urls,
            {"pages": empty[:60], "pages_count": len(empty), "tables_count": sum(row["tables"] for row in empty)},
            "a <table> holds the rows it was made for",
            "Remove the empty <table>, or put the rows it was meant to hold into it.", key_urls,
            ["Empty in the HTML the server sent; a script may fill it."]))
    observations = ([{"metric": "runs of numbered paragraphs that could be <ol> lists (recorded, not judged)",
                      "value": len(numbered), "sample": numbered[:10]}] if numbered else [])
    summary = f"{len(findings)} finding(s)." if findings else "No unsupported data-table associations or table-like <div> grids found."
    check = CheckResult("STR-8", title, _status(findings), summary, findings,
                       {"pages_checked": len(checked), "real_tables": sum(len(p.analysis["tables"]) for p in checked),
                        "empty_tables": sum(row["tables"] for row in empty),
                        "grids_left_out": left_out[:40], "grids_left_out_count": len(left_out),
                        "table_semantics_unassessed": [{"url": p.url, "reason": "saved table association evidence unavailable"} for p in checked if p.analysis.get("tables") and "_table_semantics" not in p.analysis]
                        + [{"url": p.url, "element": row["element"], "reason": "table role or header relationships not established"}
                           for p in checked for row in p.analysis.get("_table_semantics", []) if row["assessment"] == "uncertain" or not row["parser_complete"]],
                        "excluded_as_rnd1_root_cause": sorted(gap)}, observations)

    from ..coverage import derive
    check.coverage = derive(check.check_id, check.status, check.evidence, check.observations)
    check.settle_status()
    return check


# -- STR-9 ---------------------------------------------------------------------

# STR-9 guesses the language from the main text only, and from at least this many of its words (DECISIONS 224).
STR9_MIN_MAIN_WORDS = 150
STR9_TOO_LITTLE = "too little main text ({words} words, need {need})"
STR9_MIXED = ("the page holds the declared language too ({declared_hits} of its common words): mixed languages, not a "
              "wrong declaration")


def _hreflang_target_page(page, row: dict, problems: list, not_read: list) -> None:
    """What is wrong with the page an hreflang link names (B04): kept out of the index (noindex, or a canonical that
    points elsewhere), or no title / no meta description, so the language version has nothing to show in results.

    Only crawled targets have their page read; a target answered by the link check alone is listed as not read,
    never as fine."""
    from ..directives import noindex_directives
    from ..index_data import effective_canonical
    if page is None or page.analysis is None:
        not_read.append({**row, "reason": "the target was not crawled, so its title, description and robots were not read"})
        return
    why = []
    if noindex_directives(page.analysis, page.headers):
        why.append("noindex")
    canonical, _, _ = effective_canonical(page)
    if canonical and not same_page(canonical, page.url):
        why.append(f"canonical points to {canonical}")
    if not (page.analysis.get("title") or "").strip():
        why.append("empty <title>")
    if not any(m["name"] == "description" and (m["content"] or "").strip() for m in page.analysis["meta"]):
        why.append("empty meta description")
    if why:
        problems.append({**row, "problems": why})


# P4: a header, menu or footer left in another language than the page, told by the controls' own words (UI_WORDS):
# at least CHROME_FOREIGN_MIN distinct labels of another language (a menu may mix both). The page's language is its
# main text's when the stopword guess is clear, else the declared one.
CHROME_FOREIGN_MIN = 2
CHROME_LANGUAGE = "pages whose header, menu or footer labels are in another language than the page"
_LABEL_SPLIT = re.compile(r"\s*[/|·•]\s*")


def chrome_labels(page) -> list[str]:
    """The names of the page's own header, menu and footer controls, as a screen reader says them: the text of links
    there (with or without an address), buttons there, and the alt text of the icons there (seen live: alt="My Cart"
    on the cart icon of a Turkish menu), each split at "/" or "|" ("Sign up / Login" is two labels), folded."""
    a = page.analysis or {}
    texts = [anchor for edge in page.outlinks or [] if edge.get("nav") or edge.get("footer")
             for anchor in edge.get("anchors") or [edge.get("anchor") or ""]]
    texts += [d.get("text") or "" for d in a.get("dead_links") or [] if d.get("where") or d.get("in_footer")]
    texts += [b.get("text") or "" for b in a.get("buttons") or [] if b.get("in_chrome")]
    texts += [img.get("alt") or "" for img in a.get("images") or [] if img.get("in_chrome")]
    return list(dict.fromkeys(part for text in texts for part in _LABEL_SPLIT.split(" ".join(fold(text).split())) if part))


def chrome_language_mismatch(page) -> dict | None:
    a = page.analysis or {}
    declared = primary_subtag(a.get("html_lang"))
    guessed = detect_language(a.get("_visible_text") or "", declared=declared).get("language")
    lang = guessed or declared
    if lang not in UI_WORDS:
        return None
    own, foreign = [], {}
    for label in chrome_labels(page):
        langs = UI_WORD_LANGUAGES.get(label)
        if not langs:
            continue
        if lang in langs:
            own.append(label)
        else:
            foreign[label] = sorted(langs)
    if len(foreign) < CHROME_FOREIGN_MIN:
        return None
    return {"url": page.url, "page_language": lang, "language_from": "main text" if guessed else "declared",
            "labels": list(foreign)[:8], "label_languages": sorted({x for v in foreign.values() for x in v}),
            "labels_in_page_language": own[:5]}


def str9_language(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], data: StructureData) -> CheckResult:
    title = "Language and locale declaration"
    if not pages:
        return CheckResult("STR-9", title, "not_assessed", "No indexable HTML pages.")
    missing, invalid, mismatch, lang_not_assessed = [], [], [], []
    # The header, menu, footer and blocks most pages repeat are left out of the guess (DECISIONS 224).
    repeated = repeated_blocks(pages)
    bad_codes, relative, broken, one_way, target_not_assessed, out_of_scope = [], [], [], [], [], []
    site = registrable_domain(urlsplit(result.origin).hostname or "")
    same_code, cluster_gaps, target_problems, target_not_read = [], [], [], []
    crawled = {page.url: page for page in result.pages}
    for p in pages:
        a = p.analysis
        lang = a["html_lang"]
        if not lang:
            missing.append(p.url)
        elif not BCP47.match(lang.strip()):
            invalid.append({"url": p.url, "lang": lang})
        declared = primary_subtag(lang)
        guess = detect_language(" ".join(main_blocks(a, repeated)), min_words=STR9_MIN_MAIN_WORDS, declared=declared)
        if guess["words"] < STR9_MIN_MAIN_WORDS:
            guess["reason"] = STR9_TOO_LITTLE.format(words=guess["words"], need=STR9_MIN_MAIN_WORDS)
        if lang and guess["language"]:
            if declared in SUPPORTED:
                declared_hits = guess["hits"].get(declared, 0)
                if guess["language"] != declared and declared_hits >= LANGUAGE_MIN_HITS:
                    # The declared language is there too: a page in two languages, not a wrong declaration.
                    lang_not_assessed.append({"url": p.url, "declared": lang, "detected": guess["language"],
                                              "stopword_hits": guess["hits"],
                                              "reason": STR9_MIXED.format(declared_hits=declared_hits)})
                elif guess["language"] != declared:
                    mismatch.append({"url": p.url, "declared": lang, "detected": guess["language"],
                                     "stopword_hits": guess["hits"], "main_words": guess["words"]})
            else:
                lang_not_assessed.append({"url": p.url, "declared": lang,
                                          "reason": f"the language guess covers {sorted(SUPPORTED)} only"})
        elif lang:
            lang_not_assessed.append({"url": p.url, "declared": lang, "reason": guess["reason"]})
        targets_by_code: dict[str, set[str]] = defaultdict(set)
        for link in a["hreflang"]:
            if link["href"]:
                targets_by_code[link["hreflang"].casefold()].add(normalize_url(link["href"], p.url) or link["href"])
        for code, targets in targets_by_code.items():
            if len(targets) > 1:
                same_code.append({"url": p.url, "hreflang": code, "targets": sorted(targets)})
        if a["hreflang"]:
            gaps = [what for what, there in (("x-default", "x-default" in targets_by_code),
                                             ("a link to this page itself",
                                              any(same_page(p.url, t) for ts in targets_by_code.values()
                                                  for t in ts))) if not there]
            if gaps:
                cluster_gaps.append({"url": p.url, "missing": gaps})
        for link in a["hreflang"]:
            code, href = link["hreflang"], link["href"]
            problem = hreflang_code_problem(code)
            if problem:
                bad_codes.append({"url": p.url, "hreflang": code, "why": problem})
            if href and not urlsplit(href).scheme:
                relative.append({"url": p.url, "hreflang": code, "href": href})
            target = normalize_url(href, p.url) if href else None
            if not target or same_page(target, p.url):
                continue
            entry = data.links.get(target, {"source": "not_fetched", "reason": "not collected"})
            row = {"url": p.url, "hreflang": code, "target": target, "status": entry.get("status"),
                   "source": entry["source"]}
            if (entry["source"] == "not_fetched" and not cfg.check_external_links
                    and registrable_domain(urlsplit(target).hostname or "") != site):
                # A language version on its own domain (a ccTLD) with links to other sites off (G18): outside this
                # audit, listed as such, not a part of STR-9 left unassessed.
                out_of_scope.append({**row, "reason": "on another domain; links to other sites are not checked "
                                                      "(--no-external-links)"})
            elif entry["source"] == "not_fetched" or entry.get("error"):
                target_not_assessed.append({**row, "reason": entry.get("reason") or entry.get("error")})
            elif not (entry.get("status") and 200 <= entry["status"] < 300):
                broken.append({**row, "location": entry.get("location")})
            else:
                back = {normalize_url(l["href"], target) for l in (entry.get("hreflang") or []) if l["href"]}
                if not any(same_page(p.url, b) for b in back):
                    one_way.append({**row, "target_hreflang": [l["hreflang"] for l in entry.get("hreflang") or []]})
                _hreflang_target_page(crawled.get(target), row, target_problems, target_not_read)
    findings = []
    google = "Documented (Google hreflang docs) / Hypothesis (AI engines)"
    if broken:
        urls = sorted({r["url"] for r in broken})
        findings.append(_finding(
            "STR-9", f"{len(urls)} page(s) have hreflang links to URLs that do not return 200", Severity.S4,
            Confidence.VERIFIED, google, ["Google AI Overviews / AI Mode", "engines answering in the user's locale"],
            urls, {"links": broken[:60]}, "every hreflang target returns 200",
            "Point hreflang at the final 200 URL of each locale (not a redirect or a missing page).", key_urls))
    if one_way:
        urls = sorted({r["url"] for r in one_way})
        findings.append(_finding(
            "STR-9", f"{len(urls)} page(s) have hreflang links that are not returned", Severity.S4, Confidence.VERIFIED,
            google, ["Google AI Overviews / AI Mode", "engines answering in the user's locale"], urls,
            {"links": one_way[:60]}, "alternate pages link back to each other",
            "Add the return hreflang link on each target page (Google ignores one-way annotations).", key_urls,
            ["Google: 'If two pages don't both point to each other, the tags will be ignored.'",
             "Only <link> annotations in HTML are read; hreflang in HTTP headers or sitemaps is not built."]))
    if same_code:
        urls = sorted({r["url"] for r in same_code})
        findings.append(_finding(
            "STR-9", f"{len(urls)} page(s) give the same hreflang code to two or more URLs", Severity.S4,
            Confidence.VERIFIED, google, ["Google AI Overviews / AI Mode", "engines answering in the user's locale"],
            urls, {"items": same_code[:60]}, "one URL per hreflang code",
            "Keep one URL for each language-region code; give the other version its own code or drop the link.",
            key_urls))
    if target_problems:
        targets = sorted({r["target"] for r in target_problems})
        findings.append(_finding(
            "STR-9", f"{len(targets)} hreflang target page(s) are not indexable or have an empty title or description",
            Severity.S4, Confidence.VERIFIED, google,
            ["Google AI Overviews / AI Mode", "engines answering in the user's locale"], targets,
            {"links": target_problems[:60]}, "every language version is indexable and has its own title and description",
            "Give each language version an indexable, self-canonical page with its own <title> and meta description, "
            "or drop it from the hreflang set.", key_urls))
    if cluster_gaps:
        urls = sorted({r["url"] for r in cluster_gaps})
        findings.append(_finding(
            "STR-9", f"{len(urls)} page(s) with hreflang links lack x-default or a link to themselves", Severity.INFO,
            Confidence.VERIFIED, google, ["engines answering in the user's locale"], urls, {"items": cluster_gaps[:60]},
            "each page lists itself and an x-default in its hreflang set",
            "Add the page's own hreflang link and an x-default for visitors whose language is not listed.", key_urls,
            ["Google recommends both; neither is required for the other links to work."]))
    if mismatch:
        urls = [r["url"] for r in mismatch]
        findings.append(_finding(
            "STR-9", f"{len(urls)} page(s) declare a <html lang> that does not match the content language", Severity.S4,
            Confidence.ESTIMATED, HYPOTHESIS, ["engines answering in the user's language"], urls, {"pages": mismatch[:40]},
            "<html lang> names the content language", "Set <html lang> to the page's actual language.", key_urls,
            ["Estimated: stopword-based language guess, reported only when it is confident."]))
    for rows, label, fix in ((missing, "have no <html lang>", "Add lang to the <html> element."),
                             (invalid, "have a malformed <html lang> value", "Use a BCP 47 code such as en or tr-TR."),
                             (bad_codes, "have malformed hreflang codes",
                              "Use a language code with an optional ISO 3166-1 region (en-GB, not en-UK), or x-default."),
                             (relative, "use relative hreflang URLs",
                              "Use fully-qualified URLs; Google's docs require the scheme and host.")):
        if rows:
            urls = sorted({r if isinstance(r, str) else r["url"] for r in rows})
            findings.append(_finding("STR-9", f"{len(urls)} page(s) {label}", Severity.INFO, Confidence.VERIFIED, google,
                                     ["engines answering in the user's language"], urls, {"items": rows[:60]},
                                     "valid language declarations", fix, key_urls))
    from ..judgments import LANGUAGE_SUMMARY
    summary = f"{len(findings)} finding(s)." if findings else LANGUAGE_SUMMARY
    if target_not_assessed:
        summary += f" {len(target_not_assessed)} hreflang target(s) not assessed (see evidence)."
    if target_not_read:
        summary += f" {len(target_not_read)} hreflang target page(s) not read for title, description and indexing (see evidence)."
    if out_of_scope:
        summary += f" {len(out_of_scope)} hreflang target(s) on another domain, outside this audit (see evidence)."
    return CheckResult("STR-9", title, _status(findings), summary, findings,
                       {"lang_mismatch_not_assessed": lang_not_assessed[:40],
                        "lang_mismatch_not_assessed_count": len(lang_not_assessed),
                        "hreflang_targets_not_assessed": target_not_assessed[:40],
                        "hreflang_targets_not_assessed_count": len(target_not_assessed),
                        "hreflang_target_pages_not_read": target_not_read[:40],
                        "hreflang_target_pages_not_read_count": len(target_not_read),
                        "hreflang_targets_out_of_scope": out_of_scope[:40],
                        "hreflang_targets_out_of_scope_count": len(out_of_scope),
                        "language_guess": f"stopwords for {sorted(SUPPORTED)} (Estimated)"},
                       _chrome_language_observation(pages))


def _chrome_language_observation(pages: list) -> list[dict]:
    """P4: an STR-9 observation (a client report may raise it): the pages whose own menu speaks another language."""
    rows = [row for page in pages for row in [chrome_language_mismatch(page)] if row]
    return [{"metric": CHROME_LANGUAGE, "pages": len(rows), "examples": rows[:5],
             "note": "Translate the theme's labels into the page's language, or show each language its own menu."}] if rows else []


# -- STR-10 --------------------------------------------------------------------

# An og:image the share card cannot use (DECISIONS 209): the site icon, or an image under 200 × 200 pixels (the smallest
# share image the large networks show).
ICON_TYPES = frozenset({"image/x-icon", "image/vnd.microsoft.icon"})
MIN_SHARE_IMAGE = 200
# P1: under 600 × 315 the large networks show the share image as a small thumbnail beside the text, not the large
# card (Meta's sharing guide; 1200 × 630 is what it recommends). A note, not a problem.
LARGE_CARD_IMAGE = (600, 315)
# P3: STR-10 observations a client report reads by these names.
OG_URL_DIFFERS = "pages whose og:url names another address than their canonical"
EMPTY_META = "pages with an empty <meta name> tag"


def str10_previews(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], data: StructureData) -> CheckResult:
    title = "Link-preview metadata"
    if not pages:
        return CheckResult("STR-10", title, "not_assessed", "No indexable HTML pages.")
    missing: dict[str, list[str]] = defaultdict(list)
    empty: dict[str, list[str]] = defaultdict(list)
    dead, inconclusive, icons, small, thumb, no_card, og_url_differs = [], [], [], [], [], [], []
    empty_meta: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        a = p.analysis
        # Every og: tag the page's head carries, with or without a value (`og` keeps only the ones that have one).
        written = {entry["property"] for entry in a.get("meta_properties") or []} | {m["name"] for m in a["meta"]}
        for tag in ("og:title", "og:description", "og:image"):
            if not a["og"].get(tag):
                # <meta property="og:title" content=""> is there, with nothing in it: said as empty, not as missing.
                (empty if tag in written else missing)[tag].append(p.url)
        if not any(m["name"] == "description" and m["content"] for m in a["meta"]):
            missing["meta description"].append(p.url)
        # H32: X (Twitter) reads og: tags for the card's text and image but needs twitter:card to show a card.
        if (a["og"].get("og:title") or a["og"].get("og:image")) and "twitter:card" not in written:
            no_card.append(p.url)
        # P3: og:url naming another address than the canonical, compared as URLs (an empty path is "/", RFC 3986), so
        # "https://site.example" and "https://site.example/" are the same address and never reported.
        canonical = normalize_url((a.get("canonicals") or [""])[0], p.url) if a.get("canonicals") else None
        og_url = normalize_url((a["og"].get("og:url") or [""])[0], p.url) if a["og"].get("og:url") else None
        if canonical and og_url and canonical != og_url:
            og_url_differs.append({"url": p.url, "og:url": og_url, "canonical": canonical})
        # P3: a <meta name> written with no content (keywords, author…); description is said above, as a finding.
        for meta in a["meta"]:
            if not meta["content"] and meta["name"] != "description" and not meta["name"].startswith(("og:", "twitter:")):
                empty_meta[meta["name"]].append(p.url)
        for value in a["og"].get("og:image", [])[:1]:
            target = normalize_url(value, p.url)
            entry = data.links.get(target or "", {"source": "not_fetched", "reason": "not an http(s) URL"})
            row = {"url": p.url, "og:image": target or value, "status": entry.get("status"), "source": entry["source"],
                   "reason": entry.get("reason") or entry.get("error"), "content_type": entry.get("content_type")}
            # The site icon as share image (DECISIONS 209): told by the address alone, so no request is needed.
            content_type = (entry.get("content_type") or "").split(";", 1)[0].strip().lower()
            if urlsplit(target or value).path.lower().endswith(".ico") or content_type in ICON_TYPES:
                icons.append({**row, "final_url": entry.get("final_url")})
            elif entry.get("image") and min(entry["image"]["width"], entry["image"]["height"]) < MIN_SHARE_IMAGE:
                small.append({**row, "image": entry["image"], "final_url": entry.get("final_url")})
            elif entry.get("image") and (entry["image"]["width"] < LARGE_CARD_IMAGE[0]
                                         or entry["image"]["height"] < LARGE_CARD_IMAGE[1]):
                thumb.append({**row, "image": entry["image"], "final_url": entry.get("final_url"),
                              "hops": entry.get("hops")})
            if entry.get("status") in (404, 410):
                dead.append(row)
            elif entry["source"] == "not_fetched" or not (entry.get("status") and 200 <= entry["status"] < 300):
                inconclusive.append(row)
    findings = []
    if icons:
        urls = sorted({r["url"] for r in icons})
        findings.append(_finding(
            "STR-10", f"{len(urls)} page(s) use the site icon as share image (og:image is a .ico file)", Severity.S4,
            Confidence.VERIFIED, HYPOTHESIS, CARD_ENGINES, urls, {"images": icons[:60]},
            "og:image is a share image of at least 1200 × 630, not the site icon",
            "The share image is the site icon; use an image of at least 1200 × 630.", key_urls, [CAPPED]))
    if small:
        urls = sorted({r["url"] for r in small})
        findings.append(_finding(
            "STR-10", f"{len(urls)} page(s) have a share image smaller than 200 × 200 pixels",
            Severity.S4, Confidence.VERIFIED, HYPOTHESIS, CARD_ENGINES, urls,
            {"images": small[:60], "minimum": f"{MIN_SHARE_IMAGE} × {MIN_SHARE_IMAGE}",
             "size_read_from": "the first 64 KB of the image file (PNG, GIF, JPEG, WebP or ICO header)"},
            "og:image is at least 200 × 200 pixels",
            "The share image is too small to be shown; use an image of at least 1200 × 630.", key_urls, [CAPPED]))
    if thumb:
        urls = sorted({r["url"] for r in thumb})
        findings.append(_finding(
            "STR-10", f"{len(urls)} page(s) have a share image smaller than 600 × 315 pixels (shown as a small thumbnail)",
            Severity.INFO, Confidence.VERIFIED, HYPOTHESIS, CARD_ENGINES, urls,
            {"images": thumb[:60], "large_card_minimum": f"{LARGE_CARD_IMAGE[0]} × {LARGE_CARD_IMAGE[1]}",
             "size_read_from": "the first 64 KB of the image file (PNG, GIF, JPEG, WebP or ICO header)"},
            "og:image is at least 1200 × 630 pixels",
            "Use a share image of 1200 × 630 pixels, and point og:image at its final address rather than one that "
            "redirects.", key_urls, ["Presentation of a shared link, not selection by answer engines."]))
    if dead:
        urls = sorted({r["url"] for r in dead})
        findings.append(_finding(
            "STR-10", f"{len(urls)} page(s) have an og:image that returns 404/410", Severity.S4, Confidence.VERIFIED,
            HYPOTHESIS, CARD_ENGINES, urls, {"images": dead[:60]}, "og:image returns the image",
            "Point og:image at an image URL that exists.", key_urls, [CAPPED]))
    for tag, urls in missing.items():
        findings.append(_finding(
            "STR-10", f"{len(urls)} page(s) have no {tag}", Severity.INFO, Confidence.VERIFIED, HYPOTHESIS, CARD_ENGINES,
            urls, {"pages": urls[:60]}, f"{tag} present", f"Add {tag}.", key_urls,
            ["Presentation of a citation, not selection (spec)."]))
    for tag, urls in empty.items():
        findings.append(_finding(
            "STR-10", f"{len(urls)} page(s) have an empty {tag}", Severity.INFO, Confidence.VERIFIED, HYPOTHESIS, CARD_ENGINES,
            urls, {"pages": urls[:60], "tag_present_with_no_content": True}, f"{tag} has a value", f"Give {tag} a value.", key_urls,
            ["Presentation of a citation, not selection (spec)."]))
    # G13: most healthy sites leave twitter:card out, X builds a summary card from the og: tags, and it has nothing to
    # do with how answer engines cite a page: an observation, not a finding.
    observations = [{"metric": "pages with Open Graph tags but no twitter:card", "pages": len(no_card),
                     "examples": no_card[:5],
                     "note": "X falls back to the og: tags for the card's text and image; add "
                             '<meta name="twitter:card" content="summary_large_image"> for the large card'}] if no_card else []
    # P3: small hygiene facts a client report may raise; observations, as twitter:card (G13).
    if og_url_differs:
        observations.append({"metric": OG_URL_DIFFERS, "pages": len(og_url_differs), "examples": og_url_differs[:5],
                             "note": "Networks group shares under og:url; it should name the page's canonical address."})
    if empty_meta:
        observations.append({"metric": EMPTY_META, "pages": len({u for urls in empty_meta.values() for u in urls}),
                             "names": {name: len(urls) for name, urls in sorted(empty_meta.items())},
                             "examples": sorted({u for urls in empty_meta.values() for u in urls})[:5],
                             "note": "An empty tag says nothing; remove it or give it a value (search engines ignore keywords)."})
    summary = f"{len(findings)} finding(s)." if findings else (
        "Preview metadata is present" + (" and every og:image that was checked works." if not inconclusive else
                                         "; og:image works where it could be checked."))
    if inconclusive:
        summary += f" {len(inconclusive)} og:image URL(s) not assessed or inconclusive (see evidence)."
    return CheckResult("STR-10", title, _status(findings), summary, findings,
                       {"og_image_not_assessed_or_inconclusive": inconclusive[:40],
                        "og_image_not_assessed_count": len(inconclusive)}, observations)


# -- STR-12 --------------------------------------------------------------------

_URL_LANGUAGE = re.compile(r"^/([a-z]{2})(?:-[a-z]{2})?(?:/|$)", re.I)


def declared_language(page) -> tuple[str | None, dict]:
    """The language a page says it is in, and every signal it gives: URL folder, its own hreflang, <html lang>.

    The URL folder wins, then the page's hreflang entry for itself, then <html lang>: a template can ship one
    `lang` on every translation, but nobody puts a page under /tr/ by accident.
    """
    a = page.analysis
    folder = _URL_LANGUAGE.match(urlsplit(page.url).path)
    own = next((primary_subtag(link["hreflang"]) for link in a.get("hreflang") or []
                if link["hreflang"].casefold() != "x-default"
                and normalize_url(link["href"], page.url) == page.url), None)
    signals = {"url_folder": folder.group(1).lower() if folder and folder.group(1).lower() in NAMES else None,
               "hreflang_for_this_url": own, "html_lang": primary_subtag(a.get("html_lang"))}
    return next((value for value in signals.values() if value), None), signals


def language_share(blocks: list[str], declared: str) -> dict:
    """How much of the text, by words, is in another language than `declared`. Passages too short to call are left out."""
    words = {"declared": 0, "foreign": 0, "unclassified": 0}
    by_language: Counter = Counter()
    samples = []
    for block in blocks:
        n = len(block.split())
        language = block_language(block)
        if language is None:
            words["unclassified"] += n
        elif language == declared:
            words["declared"] += n
        else:
            words["foreign"] += n
            by_language[language] += n
            if len(samples) < 3:
                samples.append(block[:200])
    classified = words["declared"] + words["foreign"]
    return {"words": words, "classified_words": classified, "share": round(words["foreign"] / classified, 2) if classified else None,
            "foreign_languages": dict(by_language.most_common()), "samples": samples}


def placeholder_hits(blocks: list[str]) -> list[dict]:
    """Template or site-builder text left in the content, each with the passage it sits in."""
    hits, seen = [], set()
    for block in blocks:
        folded = turkish_fold(block)
        for phrase in PLACEHOLDER_TEXT:
            at = folded.find(phrase)
            # Names are ordinary privacy/form prose unless explicitly marked as a template slot.
            if phrase in {"your company name", "your business name", "şirket adınız", "firma adınız"}:
                slot = re.search(r"[\[<{]\s*" + re.escape(phrase) + r"\s*[\]>}]", folded)
                if not slot and folded.strip(" .:—-! ") != phrase and not re.search(re.escape(phrase) + r"\s+(?:here|goes here|burada yer alacak|buraya)(?:\W|$)", folded):
                    continue
            if at >= 0 and phrase not in seen:
                seen.add(phrase)
                hits.append({"phrase": phrase, "sample": block[max(0, at - 60): at + len(phrase) + 100]})
    return hits


def str12_content_language(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    title = "Content language mismatch and placeholder text"
    if not pages:
        return CheckResult("STR-12", title, "not_assessed", "No indexable HTML pages.")
    repeated = repeated_blocks(pages)
    mismatched, placeholders, not_assessed, foreign_headings = [], [], [], []
    for p in pages:
        blocks = main_blocks(p.analysis, repeated)
        hits = placeholder_hits(body_blocks(p.analysis, repeated))
        if hits:
            placeholders.append({"url": p.url, "found": hits[:10]})
        declared, signals = declared_language(p)
        if declared is None:
            not_assessed.append({"url": p.url, "reason": "the page declares no language (no /xx/ folder, hreflang or <html lang>)"})
            continue
        if declared not in SUPPORTED:
            not_assessed.append({"url": p.url, "declared": declared,
                                 "reason": f"the language guess covers {sorted(SUPPORTED)} only"})
            continue
        # Headings first: a template's leftover section titles ("Neuro Therapy Unit", "Information for new
        # patient") sit among real content and need not tip the body over the share below.
        by_language: dict[str, list[str]] = defaultdict(list)
        # People's names are left out: a team page in English lists "Prof. Dr. Vehbi Alp Üçok", and the Turkish
        # letters in a name are not Turkish text.
        headings = heading_blocks(p.analysis, repeated)
        names = [h for h in headings if has_personal_title(h)]
        for heading in headings:
            language = heading_language(heading, among_names=bool(names), declared=declared)
            if language and language != declared:
                by_language[language].append(heading[:120])
        odd = max(by_language.items(), key=lambda kv: len(kv[1]), default=(None, []))
        if len(odd[1]) >= MIN_FOREIGN_HEADINGS:
            foreign_headings.append({"url": p.url, "declared": declared, "declared_by": signals,
                                     "headings_language": odd[0], "headings": odd[1][:12], "headings_count": len(odd[1]),
                                     "name_headings_left_out": len(names)})
        measured = language_share(blocks, declared)
        if measured["classified_words"] < MIN_WORDS_FOR_LANGUAGE_SHARE:
            not_assessed.append({"url": p.url, "declared": declared, "reason":
                                 f"only {measured['classified_words']} words of main content could be assigned to a "
                                 f"language (need {MIN_WORDS_FOR_LANGUAGE_SHARE})"})
            continue
        if measured["share"] >= FOREIGN_CONTENT_SHARE:
            top = next(iter(measured["foreign_languages"]))
            mismatched.append({"url": p.url, "declared": declared, "declared_by": signals,
                               "main_content_language": top, "foreign_share": measured["share"],
                               "words": measured["words"], "foreign_languages": measured["foreign_languages"],
                               "samples": measured["samples"]})
    findings = []
    engines = ["engines answering in the user's language", "all answer engines that quote page text"]
    if mismatched:
        mismatched.sort(key=lambda row: -row["foreign_share"])
        urls = [row["url"] for row in mismatched]
        pairs = sorted({(row["declared"], row["main_content_language"]) for row in mismatched})
        label = "; ".join(f"declared {NAMES.get(d, d)}, written mostly in {NAMES.get(m, m)}" for d, m in pairs)
        findings.append(_finding(
            "STR-12", f"{len(urls)} page(s) are mostly in another language than they declare ({label})", Severity.S2,
            Confidence.ESTIMATED, Rationale.SELF_EVIDENT.value, engines, urls, {"pages": mismatched[:40], "threshold": FOREIGN_CONTENT_SHARE,
                                                             "compared": MAIN_CONTENT_BASIS},
            "a page's main content is in the language its URL and markup declare",
            "Replace the text with the page's own content in the declared language, or move the page to the right "
            "language folder and fix its lang and hreflang. Text in another language on a translated page is often "
            "untranslated or left over from a template.", key_urls,
            [f"Estimated: each passage of main content is assigned a language from stopword counts; the page is "
             f"reported when at least {FOREIGN_CONTENT_SHARE:.0%} of the assigned words are not in the declared language.",
             "Read the sample before acting: quoted material, product names and code can be in another language on purpose."]))
    already = {row["url"] for row in mismatched}
    foreign_headings = [row for row in foreign_headings if row["url"] not in already]
    if foreign_headings:
        urls = [row["url"] for row in foreign_headings]
        pairs = sorted({(row["declared"], row["headings_language"]) for row in foreign_headings})
        label = "; ".join(f"declared {NAMES.get(d, d)}, headings in {NAMES.get(m, m)}" for d, m in pairs)
        findings.append(_finding(
            "STR-12", f"{len(urls)} page(s) have section headings in another language than they declare ({label})",
            Severity.S3, Confidence.ESTIMATED, Rationale.SELF_EVIDENT.value, engines, urls,
            {"pages": foreign_headings[:40], "minimum_headings": MIN_FOREIGN_HEADINGS, "method": HEADING_METHOD},
            "a page's headings are in the language its URL and markup declare",
            "Translate these headings, or remove the sections if they are left over from a theme or template "
            "(headings such as demo section titles usually come with demo text under them).", key_urls,
            [f"Estimated: a heading is assigned a language from stopwords, and a page is reported at "
             f"{MIN_FOREIGN_HEADINGS} or more headings in one other language. Its body text is mostly in the declared "
             "language, or it would be in the finding above.",
             "Read the headings before acting: brand and product names can be in another language on purpose.",
             "Still a heuristic over word lists. Not counted as evidence: words in parentheses, a common word between "
             "two capitalised words (a term or a name such as “Proof of Stake”), and a word that is ordinary in the "
             "declared language (“et” in a Turkish heading)."]))
    if placeholders:
        urls = [row["url"] for row in placeholders]
        findings.append(_finding(
            "STR-12", f"{len(urls)} page(s) contain placeholder or template text", Severity.S2, Confidence.VERIFIED,
            Rationale.SELF_EVIDENT.value, engines, urls, {"pages": placeholders[:40], "phrases_checked": len(PLACEHOLDER_TEXT)},
            "published pages carry their own text, not a template's",
            "Replace the placeholder text with real content, or unpublish the page until it has some.", key_urls,
            ["The phrase is Verified as present in the page's main content; whether it is a leftover is for a person "
             "to confirm from the sample (a page about placeholder text would also match)."]))
    assessed = len(pages) - len(not_assessed)
    summary = (f"{len(findings)} finding(s)." if findings else
               f"Main content matches the declared language on {assessed} page(s), and no placeholder text was found.")
    if not_assessed:
        summary += f" Language not assessed on {len(not_assessed)} page(s) (see evidence)."
    return CheckResult("STR-12", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "language_not_assessed": not_assessed[:40],
                        "language_not_assessed_count": len(not_assessed), "compared": MAIN_CONTENT_BASIS,
                        "site_wide_rule": f"{SITEWIDE_SHARE:.0%} of pages, from {SITEWIDE_MIN_PAGES} pages",
                        "language_guess": f"stopwords for {sorted(SUPPORTED)} (Estimated)"})


def run_structure_checks(result: CrawlResult, cfg: CrawlConfig, render_checks: list[CheckResult]) -> list[CheckResult]:
    pages = indexable_pages(result)
    key_urls = set(key_page_urls(result, cfg))
    gap = _rendering_gap(render_checks) & {p.url for p in pages}
    data = result.structure if result.structure is not None else StructureData()
    str4, str4_date_pages = str4_consistency(result, cfg, pages, key_urls, gap)
    return settle_all([
        str1_titles(result, cfg, pages, key_urls),
        str2_headings(result, cfg, pages, key_urls, gap),
        str3_structured_data(result, cfg, pages, key_urls),
        str4,
        str5_entity(result, cfg, pages, key_urls, data),
        str6_freshness(result, cfg, pages, key_urls, gap, str4_date_pages),
        str7_alt(result, cfg, pages, key_urls, gap, data),
        str8_semantic_tables(result, cfg, pages, key_urls, gap),
        str9_language(result, cfg, pages, key_urls, data),
        str10_previews(result, cfg, pages, key_urls, data),
        str11_markup_contradictions(result, cfg, pages, key_urls, str4),
        str12_content_language(result, cfg, pages, key_urls),
        str13_template_markers(result, cfg, pages, key_urls),
        str14_anchor_text(result, cfg, pages, key_urls),
        str15_thin_content(result, cfg, pages, key_urls, gap),
        str16_duplicate_descriptions(result, cfg, pages, key_urls, gap),
        str17_dead_ends(result, cfg, pages, key_urls, gap),
        *run_small_site_checks(result, cfg, pages, key_urls, gap),
        run_traditional_seo_quality_check(result, pages, key_urls, gap),
    ], result)


def annotate_page_types(checks, result: CrawlResult) -> None:
    """`Finding.page_types` for every finding (DECISIONS 278, schema 1.20): the estimated kind of each affected page, as
    `page_kind` says it, "404" for a page that answered 404/410, and "unknown" for a page the crawl did not read or whose
    kind is not established. The release gate allows content advice only for an established, allowed kind."""
    home = homepage_url(result)
    read = {p.url: p for p in result.pages if getattr(p, "analysis", None)}
    gone = {p.url for p in result.pages if p.status in (404, 410)}
    template = product_template(list(read.values()), home)
    kinds: dict[str, str] = {}

    def kind_of(url: str) -> str:
        if url not in kinds:
            if url in gone:
                kinds[url] = "404"
            elif url in read:
                kinds[url] = page_kind(read[url], home, template["products"])[0] or "unknown"
            else:
                kinds[url] = "unknown"
        return kinds[url]

    for check in checks:
        for finding in getattr(check, "findings", None) or []:
            urls = finding.scope.get("_all_urls") or finding.scope.get("urls") or []
            finding.page_types = {u: kind_of(u) for u in urls if isinstance(u, str)} or None
