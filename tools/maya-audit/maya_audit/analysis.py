"""Single-pass extraction of the HTML facts that checks need.

Stored on each readable page (PageFetch.analysis) so checks never re-fetch or
re-parse. Deliberately a streaming parser, not a DOM. Keys starting with "_"
(for example the visible text) are kept in memory for checks but left out of
JSON reports.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .config import CSS_SIZED_IMAGE_CLASS, TEMPLATE_MARKERS
from .own_document import BEFORE_BODY, embedded_spans, records, without

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
NON_CONTENT = {"script", "style", "noscript", "svg", "template"}
MAIN_REGION = {"main", "article"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# Common client-side framework mount points (RND-1 T0 heuristic).
MOUNT_IDS = {"root", "app", "__next", "__nuxt", "___gatsby", "svelte", "q-app"}
VERIFICATION_META = "maya-site-verification"
CHROME = {"nav", "header", "footer", "aside"}
# Attributes that hold a Microdata / RDFa property value instead of the element text.
VALUE_ATTRS = {"meta": "content", "a": "href", "link": "href", "area": "href", "img": "src", "audio": "src",
               "video": "src", "source": "src", "iframe": "src", "embed": "src", "track": "src", "object": "data",
               "time": "datetime", "data": "value", "meter": "value"}
SEMANTIC_BLOCKS = {"table", "ul", "ol", "dl"}
GRID_CONTAINERS = {"div", "section"}
GRID_CELL_TAGS = {"div", "span", "strong", "b", "em", "i", "small", "p", "h2", "h3", "h4", "h5", "h6"}
NODE_TEXT_CAP = 200
# STR-7: an image is "beside a label" when the element that directly holds it is one of these, has a few characters
# of its own text and holds at most two images: a flag beside its country code, an icon beside its name. The text
# already says what the image shows (DECISIONS 178).
LABEL_PARENTS = frozenset({"td", "th", "li", "a", "button", "figure", "span", "div", "p", "label"})
LABEL_MAX_CHARS = 60
LABEL_MAX_IMAGES = 2
# STR-8: how many first-cell texts of a table's (or a grid's) rows are kept, to tell a copy of a table from a table.
ROW_LABELS_KEPT = 20
SELECTOR_PART_MAX = 80
FIRST_ROW_MAX = 120
# A form control (DECISIONS 223): a grid or a table with one inside, or a <form> around, is a calculator or a form.
CONTROL_TAGS = frozenset({"input", "select", "textarea", "output"})
# A block named as a calculator (its class, id or the heading it sits under): its grid shows computed values, not a
# table of facts (DECISIONS 284). Not a page type: only the block that carries the name.
CALCULATOR_NAME = re.compile(r"calculat|(?<![a-z])calc(?![a-z])|[-_]calc|hesapla|simulat|simülasyon|rechner", re.I)
# Blocks too wide to say a control is beside a grid: any control anywhere on the page marks them.
PAGE_BLOCKS = frozenset({"html", "body", "main"})
# An empty <table> is in a calculator's block when the table or one of its nearest ancestors (not the page itself:
# html, body, main, article) holds a control. An agent default.
CONTROL_BLOCK_LEVELS = 3
PAGE_LEVEL_TAGS = frozenset({"html", "body", "main", "article"})
HEADING_TEXT_MAX = 120
_COLLAPSE_CLASS = re.compile(r"^(collapse|collapsed|collapsing|collapsible)$|accordion")
NUMBERED = re.compile(r"^\s*(?:\d{1,2}[.)]|step\s+\d{1,2}\b)", re.I)
_WS = re.compile(r"\s+")
# P2: what themes call a breadcrumb trail in class, id or aria-label.
_CRUMB = re.compile(r"bread-?crumb|(?<![a-z])crumbs?(?![a-z])", re.I)
MAX_ITEMS = 200
# Where a lazy-loading script keeps an image's real address until it swaps it into `src`.
LAZY_SRC_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-lazy", "data-url", "data-echo", "data-srcset",
                  "data-lazy-srcset", "srcset")
_PLACEHOLDER_SRC = re.compile(r"^(data:|about:blank|#$)|(placeholder|spacer|blank|transparent|loading|lazy|1x1|pixel)[^/]*\.(gif|png|svg|jpe?g|webp)", re.I)
TEMPLATE_MARKER = re.compile("|".join(f"(?P<m{i}>{rx})" for i, (_, rx) in enumerate(TEMPLATE_MARKERS)))
URL_ATTRS = {"a": ("href",), "area": ("href",), "link": ("href",), "img": ("src", "data-src", "srcset"),
             "source": ("src", "srcset"), "iframe": ("src",), "script": ("src",), "video": ("src", "poster"),
             "audio": ("src",), "form": ("action",)}
# H32: attributes a browser loads as part of the page (not links a reader follows); on an https page an http:// value
# here is mixed content. A <link> counts only with one of SUBRESOURCE_RELS.
SUBRESOURCE_ATTRS = {"img": ("src",), "source": ("src",), "iframe": ("src",), "script": ("src",), "video": ("src", "poster"),
                     "audio": ("src",), "embed": ("src",), "link": ("href",)}
SUBRESOURCE_RELS = frozenset({"stylesheet", "preload", "icon", "modulepreload"})
# H33: tag-manager and analytics ids as the loaders print them in a page's markup.
GTM_LOADER = re.compile(r"googletagmanager\.com/gtm\.js\?id=(GTM-[A-Z0-9]+)|['\"](GTM-[A-Z0-9]+)['\"]\s*\)")
# A <link> (preload, preconnect, dns-prefetch) loads no tag: counted, it made one GTM snippet read as two (G10).
_LINK_TAG = re.compile(r"<link\b[^>]*>", re.I)
# A class that sizes an image by CSS (G12, config.CSS_SIZED_IMAGE_CLASS), and inline styles that do.
_CSS_SIZED_CLASS = re.compile(CSS_SIZED_IMAGE_CLASS, re.I)
_SIZED_STYLE = re.compile(r"aspect-ratio|object-fit|(?:^|;)\s*height\s*:\s*\d", re.I)
GTM_NOSCRIPT = re.compile(r"googletagmanager\.com/ns\.html\?id=(GTM-[A-Z0-9]+)")
GTAG_LOADER = re.compile(r"googletagmanager\.com/gtag/js\?id=((?:G|GT|AW|DC|UA)-[A-Z0-9-]+)")


def template_markers(text: str) -> list[str]:
    """Unfilled template markers in `text`, as written, in order, without repeats."""
    return list(dict.fromkeys(m.group(0) for m in TEMPLATE_MARKER.finditer(text or "")))


_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


def image_source(attr: dict[str, str]) -> tuple[str | None, bool]:
    """(the image's real address, whether it is lazy-loaded).

    A lazy-loaded image ships with an empty or placeholder `src` and its real address in `data-src`
    (or a sibling attribute); a script swaps it in on scroll. Reading only `src` reports such an
    image as having none.
    """
    src = (attr.get("src") or "").strip()
    deferred = next((attr[name].strip() for name in LAZY_SRC_ATTRS if (attr.get(name) or "").strip()), "")
    if deferred and "srcset" in next(name for name in LAZY_SRC_ATTRS if (attr.get(name) or "").strip()):
        deferred = deferred.split(",")[0].strip().split(" ")[0]
    lazy = attr.get("loading", "").strip().lower() == "lazy" or any(
        (attr.get(name) or "").strip() for name in LAZY_SRC_ATTRS if name != "srcset") or "lazy" in attr.get("class", "").lower()
    if deferred and (not src or _PLACEHOLDER_SRC.search(src)):
        return deferred, True
    return (src or None), lazy


def hidden_by_markup(attr: dict[str, str]) -> bool:
    """Hidden by its own markup: the hidden attribute, aria-hidden="true", or an inline display:none/visibility:hidden.
    A class that hides it through a stylesheet is not seen here (only a rendered page can tell, `render.py`)."""
    return ("hidden" in attr or attr.get("aria-hidden", "").strip().lower() == "true"
            or bool(_HIDDEN_STYLE.search(attr.get("style", ""))))


def _hidden(attr: dict[str, str]) -> bool:
    """Not shown to anyone: hidden, aria-hidden, display:none, or sized 0 or 1 pixel (a tracking beacon's shape)."""
    tiny = any(attr.get(name, "").strip().rstrip("px") in ("0", "1") for name in ("width", "height"))
    return ("hidden" in attr or attr.get("aria-hidden", "").strip().lower() == "true"
            or bool(_HIDDEN_STYLE.search(attr.get("style", ""))) or tiny)



# DECISIONS 338: an element styled as a section title (its class or id says so), not a heading tag.
STYLED_TITLE = re.compile(r"(?:^|[\s_-])(?:title|heading|baslik|başlık|subtitle|section-title|accordion-(?:header|title|button)|"
                          r"question|soru)(?:$|[\s_-])", re.I)
STYLED_TITLE_TAGS = ("div", "span", "p", "strong", "b", "a", "label", "button")

class _Analyzer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url: str | None = None
        self.stack: list[tuple[str, tuple[str, ...], list[dict]]] = []
        self.depth: dict[str, int] = defaultdict(int)
        self.open_collectors: list[dict] = []
        self.saw_main = False
        self.main_region_types = set()
        self.in_title = False
        self.in_head = False
        # The page's own title, meta tags, canonical and hreflang links are the ones before its body starts
        # (DECISIONS 167). The body starts at <body>, or at the first element that cannot stand in a head.
        self.body_started = False
        self.title_seen = False
        self.in_other_title = False  # a second <title>, or one in the body: not the page's, and not text a visitor sees
        self.outside_title = 0
        self.outside_meta: list[str] = []
        self.outside_robots: list[str] = []
        # DECISIONS 338: section titles that are not <h2>-<h6> tags (role="heading", <summary>, <dt>, an accordion
        # toggle, an element whose class or id names a title), outside the header, menu and footer.
        self.styled_headings = 0
        self.outside_canonical = 0
        # An element that cannot stand in a head, met while <head> is still open, ends the head there (a widget's <div>,
        # an <img>): what follows is read as body by browsers and by Google (DECISIONS 260).
        self.head_closed_by: dict | None = None
        self.outside_hreflang = 0
        self.outside_properties: list[str] = []
        self.title_parts: list[str] = []
        self.meta: list[dict[str, str]] = []
        self.canonicals: list[str] = []
        self.text_parts: list[str] = []
        # One flag per text part: is it page content (in <main>/<article>, outside header/nav/footer/aside)?
        self.text_in_main: list[bool] = []
        self.text_in_chrome: list[bool] = []
        # ... and what kind of text it is: a "heading", a "link" label, or running "text".
        self.text_kind: list[str] = []
        self.text_toggle: list[bool] = []  # P4: inside <summary> or <dt>
        # Link, image and script addresses that still hold a template marker ("https://x/{inline_image_1}").
        self.template_urls: list[dict] = []
        self.body_chars = self.nosnippet_chars = self.main_chars = self.main_nosnippet_chars = 0
        self.paragraph_chars = self.words = 0
        self.headings: list[dict] = []
        self.heading_count = 0
        self.heading_last_level: int | None = None
        self.heading_level_skips: list[dict] = []
        # Open <header>, <nav>, <footer> and <aside> elements, innermost last: where a heading sits.
        self.chrome_tags: list[str] = []
        self.heading_level_skips_total = 0
        self.mounts: list[dict] = []
        self.tabpanels: list[dict] = []
        self.canvases: list[dict] = []
        self.buttons: list[dict] = []
        # The value of every <input type=submit|button> (a buy button is often one) and the action of every <form>:
        # how STR-3 tells a product page from its buy control (DECISIONS 229).
        self.input_buttons: list[str] = []
        self.form_actions: list[str] = []
        self.images: list[dict] = []
        # Formats offered by the <source> elements of the <picture> being read, or None outside one; and whether one
        # of those <source> elements declares its width and height (the browser then keeps the image's space, G12).
        self._picture: list[str] | None = None
        self._picture_sized = False
        # Keep exact image counts after the bounded detail sample fills. STR-7 uses
        # these totals so a mega-menu or image gallery cannot silently look complete.
        self.image_counts = {
            "main_content": {"total": 0, "missing_alt": 0, "empty_alt": 0, "details_retained": 0},
            "outside_chrome": {"total": 0, "missing_alt": 0, "empty_alt": 0, "details_retained": 0},
        }
        self.iframes: list[dict] = []
        # <a> elements that lead nowhere: href="#", href="javascript:...", or (in the footer) no href at all.
        self.dead_links: list[dict] = []
        self.dead_link_total = 0
        # <a href="#"> elements the page's own markup marks as a control (a menu toggle, a modal opener): not links.
        self.link_controls: list[dict] = []
        self.link_control_total = 0
        # <video> and animation players: where a page's message may sit instead of in text.
        self.media: list[dict] = []
        self._video: dict | None = None  # the <video> being read, for its <source src> (H29)
        # H30/H32: <link rel=preload as=image> tags, and sub-resources asked over plain http:// (mixed content on an
        # https page). Both capped.
        self.preloads: list[dict] = []
        self.insecure_refs: list[dict] = []
        self.pdf_links: list[dict] = []
        self.breadcrumbs: list[dict] = []  # P2: visible breadcrumb trails, {"links", "text", "in_chrome"}
        # SEO-046 (DECISIONS 304): <link rel="next"/"prev"> as written; SEO-078: where the page names an author.
        self.pagination_links: dict[str, str] = {}
        self.author_signals: set[str] = set()
        self.scripts: list[dict] = []
        self.noscript_parts: list[str] = []
        self.html_lang: str | None = None
        self.saw_html = False
        self.hreflang: list[dict] = []
        self.properties: list[dict] = []
        self.footer_parts: list[str] = []
        self.footer_len = 0
        self.logo_alts: list[dict] = []
        self.times: list[dict] = []
        self.tables: list[dict] = []
        self._row_starts = False  # a <tr> opened and its first cell has not come yet
        self.div_grids: list[dict] = []
        # The text of the last heading closed outside the header, menu and footer: the heading a grid sits under.
        self.last_heading: str | None = None
        self.h1_elements = []
        self.numbered_runs: list[dict] = []
        # Microdata / RDFa items: top-level items and the stack of open items.
        self.items: list[dict] = []
        self.item_stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        self._pending_collectors: list[dict] = []
        in_main = self.depth["main"] > 0
        in_chrome = self.depth["chrome"] > 0
        if not in_chrome and self.body_started and (
                (attr.get("role") or "").strip().lower() == "heading" or tag in ("summary", "dt")
                or (tag == "button" and ("aria-expanded" in attr or "aria-controls" in attr))
                or (tag in STYLED_TITLE_TAGS and STYLED_TITLE.search(f'{attr.get("class", "")} {attr.get("id", "")}'))):
            self.styled_headings += 1
        if tag == "html" and not self.saw_html:
            self.saw_html = True
            self.html_lang = attrs_get(attrs, "lang")
        # Inside <noscript>, <template> or a script nothing starts the body: a tracking pixel in a head's <noscript>
        # is not page content.
        if not self.body_started and not self.depth["non_content"] and (tag == "body" or tag not in BEFORE_BODY):
            self.body_started = True
            if tag != "body" and self.in_head:
                self.head_closed_by = {"tag": tag, "id": attr.get("id", "")[:80], "class": attr.get("class", "")[:120],
                                       "line": self.getpos()[0]}
        own = not self.body_started
        for name in URL_ATTRS.get(tag, ()):
            value = attr.get(name, "")
            if value and ("{" in value or "%7B" in value or "%7b" in value or "[[" in value or "<%" in value) \
                    and len(self.template_urls) < MAX_ITEMS:
                found = template_markers(value.replace("%7b", "%7B").replace("%7d", "%7D"))
                if found:
                    self.template_urls.append({"tag": tag, "attribute": name, "value": value[:300], "markers": found})
        rel = attr.get("rel", "").lower().split()
        for name in SUBRESOURCE_ATTRS.get(tag, ()) if tag != "link" or SUBRESOURCE_RELS & set(rel) else ():
            value = attr.get(name, "").strip()
            if value.lower().startswith("http://") and len(self.insecure_refs) < 20:
                self.insecure_refs.append({"tag": tag, "attribute": name, "url": value[:300]})
        if tag == "link" and "preload" in rel and attr.get("as", "").strip().lower() == "image" and len(self.preloads) < 20:
            self.preloads.append({"href": attr.get("href", "").strip()[:300], "type": attr.get("type", "").strip().lower(),
                                  "media": attr.get("media", "").strip()})
        if not own and self.head_closed_by and tag == "link" and "alternate" in rel and attrs_get(attrs, "hreflang") is not None:
            self.outside_hreflang += 1
        if not own and self.head_closed_by and tag == "meta" and attr.get("property") and len(self.outside_properties) < MAX_ITEMS:
            self.outside_properties.append(attr["property"].strip().lower())
        if own and tag == "link" and "alternate" in rel and attrs_get(attrs, "hreflang") is not None and len(self.hreflang) < MAX_ITEMS:
            self.hreflang.append({"hreflang": attr["hreflang"].strip(), "href": attr.get("href", "").strip()})
        if own and tag == "meta" and attr.get("property"):
            self.properties.append({"property": attr["property"].strip().lower(), "content": attr.get("content", "").strip()})
        self._structured_start(tag, attr)
        if tag == "link" and attr.get("href") and {"next", "prev", "previous"} & set(rel):
            key = "next" if "next" in rel else "prev"
            self.pagination_links.setdefault(key, attr["href"].strip()[:500])
        if "author" in rel:
            self.author_signals.add("rel=author")
        if "author" in attr.get("itemprop", "").lower().split():
            self.author_signals.add("itemprop=author")
        if tag != "html" and tag != "body" and AUTHOR_CLASS.search(f'{attr.get("class", "")} {attr.get("id", "")}'):
            self.author_signals.add("byline element")
        if tag == "link" and "canonical" in attr.get("rel", "").lower().split() and attr.get("href"):
            if own:
                self.canonicals.append(attr["href"].strip())
            else:
                self.outside_canonical += 1
        if tag == "meta" and attr.get("name"):
            if own:
                self.meta.append({"name": attr["name"].strip().lower(), "content": attr.get("content", "").strip()})
            elif len(self.outside_meta) < MAX_ITEMS:
                self.outside_meta.append(attr["name"].strip().lower())
                # DECISIONS 338: what a robots tag after the break says decides whether losing it matters
                if attr["name"].strip().lower() in ("robots", "googlebot", "bingbot") and len(self.outside_robots) < 5:
                    self.outside_robots.append(attr.get("content", "").strip()[:200])
        if tag == "title" and not self.depth["non_content"]:
            if own and not self.title_seen:  # the first one only
                self.title_seen = self.in_title = True
            else:
                self.in_other_title = True
                self.outside_title += not own
        if tag == "head":
            self.in_head = True
        if tag == "picture":
            self._picture, self._picture_sized = [], False
        # A lazy loader keeps the file in data-src until the video scrolls into view (P1).
        source_src = (attr.get("src") or attr.get("data-src") or "").strip()
        if tag == "source" and self._video is not None and source_src and len(self._video["sources"]) < 5:
            self._video["sources"].append(source_src[:300])
        if tag == "source" and self._picture is not None:
            self._picture += image_formats(attr.get("srcset") or attr.get("src") or "", attr.get("type"))
            self._picture_sized |= bool(_int(attr.get("width")) and _int(attr.get("height")))
        if tag == "img":
            alt = attrs_get(attrs, "alt")
            regions = []
            if in_main:
                regions.append("main_content")
            if not in_chrome:
                regions.append("outside_chrome")
            for region in regions:
                counts = self.image_counts[region]
                counts["total"] += 1
                counts["missing_alt"] += alt is None
                counts["empty_alt"] += alt == ""
            if len(self.images) < MAX_ITEMS:
                src, lazy = image_source(attr)
                self.images.append({"src": src, "lazy": lazy, "alt": alt,
                                    # Set when the element that holds it closes (`_label_images`).
                                    "beside_label": False,
                                    "width": _int(attr.get("width")), "height": _int(attr.get("height")),
                                    # H30: an aspect-ratio in the inline style reserves the space as width+height do.
                                    "aspect_ratio": "aspect-ratio" in attr.get("style", "").lower(),
                                    # G12: sized another way the markup shows: a sizing class or inline style, a
                                    # sized <source> of its <picture>, or a lazy loader's placeholder (data-src),
                                    # whose script sets the size when it swaps the image in.
                                    "css_sized": bool(_CSS_SIZED_CLASS.search(attr.get("class", ""))
                                                      or _SIZED_STYLE.search(attr.get("style", ""))
                                                      or (self._picture is not None and self._picture_sized)
                                                      or any((attr.get(name) or "").strip() for name in LAZY_SRC_ATTRS
                                                             if name.startswith("data-"))),
                                    # The title attribute, kept as evidence (an alt equal to it is not a
                                    # placeholder sign, G09).
                                    **({"title": attr["title"].strip()[:200]} if attr.get("title", "").strip() else {}),
                                    "in_main": in_main, "in_chrome": in_chrome,
                                    "in_figure": self.depth["figure"] > 0,
                                    # Every format the browser may pick from: the file itself, its srcset, and
                                    # the <source> elements of a surrounding <picture>.
                                    "formats": sorted(set(image_formats(src or "") + image_formats(attr.get("srcset") or "")
                                                          + image_formats(attr.get("data-srcset") or "") + (self._picture or [])))})
                for region in regions:
                    self.image_counts[region]["details_retained"] += 1
                if self.stack:
                    self.stack[-1][3]["imgs"].append(self.images[-1])
            if self.stack:
                self.stack[-1][3]["img_count"] += 1
        if tag == "img" and len(self.logo_alts) < 20 and (self.depth["logo"] or _mentions_logo(attr)):
            self.logo_alts.append({"alt": attrs_get(attrs, "alt"), "src": attr.get("src"), "in_chrome": in_chrome})
        if tag == "a" and urlsplit(attr.get("href", "")).path.lower().endswith(".pdf") and len(self.pdf_links) < MAX_ITEMS:
            self.pdf_links.append({"href": attr["href"], "in_main": in_main})
        if tag == "iframe" and len(self.iframes) < MAX_ITEMS:
            self.iframes.append({"src": attr.get("src") or attr.get("data-src"), "title": attr.get("title"), "in_main": in_main,
                                 "in_noscript": self.depth["noscript"] > 0, "hidden": _hidden(attr)})
        if tag in CONTROL_TAGS or attr.get("role", "").strip().lower() == "slider":
            for frame in self.stack:
                frame[3]["controls"] = True
        if tag == "input" and attr.get("type", "").lower() in ("submit", "button") and attr.get("value") and not in_chrome \
                and len(self.input_buttons) < MAX_ITEMS:
            self.input_buttons.append(_WS.sub(" ", attr["value"]).strip()[:80])
        if tag in VOID:
            return

        counters = []
        if tag in NON_CONTENT:
            counters.append("non_content")
        if "data-nosnippet" in attr:
            counters.append("nosnippet")
        if tag in MAIN_REGION or (attr.get("role") or "").strip().lower() == "main":
            counters.append("main")
            self.saw_main = True
            self.main_region_types.add(tag if tag in MAIN_REGION else "role=main")
        for name in ("p", "noscript", "form", "script", "figure", "footer"):
            if tag == name:
                counters.append(name)
        if tag in CHROME:
            counters.append("chrome")
            self.chrome_tags.append(tag)
        if tag in HEADINGS:
            counters.append("heading")
        if tag in ("a", "button", "label", "option"):
            counters.append("label")
        # P4: the toggle of an accordion, or a term: a question there is marked up. DECISIONS 340: also a button, link
        # or heading that opens and closes a panel (aria-expanded, data-toggle="collapse", an accordion class).
        if tag in ("summary", "dt") or (tag in ("button", "a", "h2", "h3", "h4", "h5", "div", "span") and _collapses(attr)):
            counters.append("toggle")
        if _mentions_logo(attr):
            counters.append("logo")
        if tag == "tr" and self.depth["table"] and self.tables:
            self.tables[-1]["rows"] += 1
            self._row_starts = True
        if tag == "th" and self.depth["table"] and self.tables:
            self.tables[-1]["has_th"] = True
        if tag in ("td", "th") and self.depth["table"] and self.tables and self._row_starts:
            # The first cell of each row: what the row is about (STR-8 compares it with a <div> grid's rows).
            self._row_starts = False
            if len(self.tables[-1]["row_labels"]) < ROW_LABELS_KEPT:
                self._pending_collectors.append({"kind": "row_label", "table": self.tables[-1], "parts": []})
        if tag == "table":
            counters.append("table")
            if len(self.tables) < MAX_ITEMS:
                # `_form` and `_nodes` are settled into `has_controls` when the page ends (`finish`).
                near = [frame[3] for frame in self.stack if frame[0] not in PAGE_LEVEL_TAGS][-CONTROL_BLOCK_LEVELS:]
                self.tables.append({"rows": 0, "has_th": False, "in_main": in_main, "in_chrome": in_chrome, "row_labels": [],
                                    "_form": self.depth["form"] > 0, "_nodes": near})
        if tag == "script":
            self.scripts.append({"src": attr.get("src"), "type": attr.get("type", "").lower(), "parts": [],
                                 # H30: a script in <head> without these stops the page from rendering until it runs.
                                 "in_head": self.in_head and not self.body_started, "async": "async" in attr, "defer": "defer" in attr})

        collectors = list(self._pending_collectors)
        # Hidden by its own markup or by an element around it (H15): a heading nobody is shown.
        hidden_here = bool(self.stack and self.stack[-1][3]["hidden"]) or hidden_by_markup(attr)
        # P2: a visible breadcrumb trail, told by its class, id or aria-label (the word themes use in every language),
        # counted by the links inside it.
        if tag in ("a", "li"):
            for collector in self.open_collectors:
                if collector.get("kind") == "breadcrumb":
                    if tag == "li":
                        collector["items"] += 1
                    elif attr.get("href", "").strip():
                        collector["links"] += 1
        if (not hidden_here and _CRUMB.search(" ".join((attr.get("class", ""), attr.get("id", ""), attr.get("aria-label", ""))))
                and not any(c.get("kind") == "breadcrumb" for c in self.open_collectors)):
            collectors.append({"kind": "breadcrumb", "links": 0, "items": 0, "parts": [], "in_chrome": in_chrome})
        if tag in HEADINGS:
            level = int(tag[1])
            self.heading_count += 1
            skip = None
            # A page whose first heading is an H3 or lower skips a level too (B19): read as a jump from the H1 level
            # the outline starts at, and marked `first_heading`.
            first = self.heading_last_level is None
            if level > (1 if first else self.heading_last_level) + 1:
                self.heading_level_skips_total += 1
                if len(self.heading_level_skips) < 60:
                    # Which heading the jump lands on, and whether it sits in the page's header, navigation, footer or
                    # sidebar: a footer's column title is one element on every page (maya_audit.shared_elements). Its
                    # text is filled in when the heading closes.
                    skip = {"from": 1 if first else self.heading_last_level, "to": level, "text": "", "in_chrome": in_chrome,
                            **({"first_heading": True} if first else {}),
                            **({"where": self.chrome_tags[-1]} if in_chrome and self.chrome_tags else {})}
                    self.heading_level_skips.append(skip)
            self.heading_last_level = level
            collectors.append({"kind": "heading", "level": level, "parts": [], "skip": skip, "in_chrome": in_chrome,
                               "hidden": hidden_here})
        if attr.get("id") in MOUNT_IDS:
            collectors.append({"kind": "mount", "id": attr["id"], "chars": 0})
            self.mounts.append(collectors[-1])
        if attr.get("role") == "tabpanel":
            collectors.append({"kind": "tabpanel", "id": attr.get("id"), "chars": 0})
            self.tabpanels.append(collectors[-1])
        if tag == "canvas":
            collectors.append({"kind": "canvas", "in_main": in_main, "aria_label": attr.get("aria-label") or None, "chars": 0,
                               "hidden": _hidden(attr), "role": attr.get("role", "").strip().lower() or None,
                               "hint": " ".join(filter(None, [attr.get("id"), attr.get("class")]))[:120] or None})
            self.canvases.append(collectors[-1])
        if tag == "time" and len(self.times) < MAX_ITEMS:
            collectors.append({"kind": "time", "datetime": attr.get("datetime") or None,
                               "itemprop": attr.get("itemprop") or None, "parts": [], "in_chrome": in_chrome})
            self.times.append(collectors[-1])
        if tag == "button" or attr.get("role") == "button":
            collectors.append({"kind": "button", "parts": [], "in_form": self.depth["form"] > 0,
                               "type": attr.get("type", "").lower(), "in_chrome": in_chrome})
            self.buttons.append(collectors[-1])
        if tag == "form" and not in_chrome and len(self.form_actions) < MAX_ITEMS:
            self.form_actions.append(attr.get("action", "")[:300])
        if tag == "a" and not self.depth["non_content"]:
            marked = control_marker(attr)
            if not marked and 'category-header' in attr.get('class', '').split() and any(frame[3].get('consent_region') for frame in self.stack):
                marked = 'category control inside explicit consent dialog'
            why = no_address(attr, in_footer=self.depth["footer"] > 0, page_url=self.page_url)
            if why and marked and not why.startswith("no address"):
                self.link_control_total += 1
                if len(self.link_controls) < MAX_ITEMS:
                    collectors.append({"kind": "link_control", "parts": [], "why": why, "control": marked})
                    self.link_controls.append(collectors[-1])
            elif why and not marked:
                self.dead_link_total += 1
                if len(self.dead_links) < MAX_ITEMS:
                    collectors.append({"kind": "dead_link", "parts": [], "why": why, "in_footer": self.depth["footer"] > 0,
                                       # The region it sits in ("header", "nav", "footer", "aside"), for a shared element's name.
                                       "where": self.chrome_tags[-1] if in_chrome and self.chrome_tags else None})
                    self.dead_links.append(collectors[-1])
        if tag in MEDIA_TAGS and len(self.media) < MAX_ITEMS:
            self.media.append({"tag": tag, "in_main": in_main, "autoplay": "autoplay" in attr, "controls": "controls" in attr,
                               # H29: the file a <video> plays, from src or its <source> children.
                               "src": (attr.get("src") or attr.get("data-src") or "").strip()[:300] or None, "sources": []})
            if tag == "video":
                self._video = self.media[-1]

        for name in counters:
            self.depth[name] += 1
        # Where the element is, as a person would look for it: its tag, id and classes, after up to two elements around it.
        own = (tag + (f"#{attr['id'].strip()}" if attr.get("id", "").strip() else "") + "".join(f".{name}" for name in attr.get("class", "").split()))[:SELECTOR_PART_MAX]
        node = {"tag": tag, "sig": tag + "." + ".".join(sorted(attr.get("class", "").split())), "children": [],
                "own_selector": own, "selector": " > ".join([frame[3]["own_selector"] for frame in self.stack[-2:]] + [own]),
                "text": [], "tlen": 0, "in_chrome": in_chrome, "in_main": in_main, "role": attr.get("role") or None,
                # Its own text (not its children's) and the images it holds directly: `_label_images`.
                "own": 0, "imgs": [], "img_count": 0, "hidden": hidden_here,
                "consent_region": bool(re.search(r"(?:gdprmodal|cky-consent-container|cmplz-cookiebanner|cookie-law-info-bar)",
                                                        attr.get('id', '') + ' ' + attr.get('class', ''), re.I)),
                # Inside something that opens and closes (an accordion, a collapsed panel): `_detect_grid`.
                "collapse": bool(self.stack and self.stack[-1][3]["collapse"]) or _collapses(attr),
                # A form control inside (set when one starts), a <form> around, the heading it sits under, and a
                # short name of its own (DECISIONS 223).
                "controls": False, "form": self.depth["form"] > 0 or tag == "form", "heading": self.last_heading,
                "label": tag + (f"#{attr['id'].strip()}" if attr.get("id", "").strip() else
                                f".{attr['class'].split()[0]}" if attr.get("class", "").split() else "")}
        if tag == "table" and self.tables and "_nodes" in self.tables[-1]:
            self.tables[-1]["_nodes"].append(node)
        self.stack.append((tag, tuple(counters), collectors, node))
        self.open_collectors.extend(collectors)

    def handle_endtag(self, tag: str) -> None:
        if tag == "picture":
            self._picture = None
        if tag == "video":
            self._video = None
        if tag == "title":
            self.in_title = self.in_other_title = False
        if tag == "head":
            self.in_head = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for j in range(len(self.stack) - 1, i - 1, -1):
                    _, counters, collectors, node = self.stack[j]
                    for name in counters:
                        self.depth[name] -= 1
                    if "chrome" in counters and self.chrome_tags:
                        self.chrome_tags.pop()
                    for collector in collectors:
                        self.open_collectors = [c for c in self.open_collectors if c is not collector]
                        text = _WS.sub(" ", " ".join(collector.get("parts", []))).strip()
                        if collector["kind"] == "heading":
                            if collector.get("skip") is not None:
                                collector["skip"]["text"] = text[:120]
                            if collector["level"] == 1:
                                self.h1_elements.append({"text": text[:200], "empty_kind": ("whitespace_only" if collector.get("had_whitespace_data") else "empty") if not text else None,
                                                         **({"hidden": True} if collector["hidden"] else {})})
                            if text and len(self.headings) < MAX_ITEMS:
                                self.headings.append({"level": collector["level"], "text": text[:200],
                                                      **({"hidden": True} if collector["hidden"] else {})})
                            if text and not collector.get("in_chrome"):
                                self.last_heading = text[:HEADING_TEXT_MAX]
                        elif collector["kind"] == "time":
                            collector["text"] = text[:100]
                        elif collector["kind"] == "row_label":
                            if text:
                                collector["table"]["row_labels"].append(text[:60])
                        elif collector["kind"] == "itemprop":
                            _add_prop(collector["item"], collector["name"], text[:2000])
                        elif collector["kind"] == "item":
                            self.item_stack = [it for it in self.item_stack if it is not collector["item"]]
                        elif collector["kind"] == "breadcrumb":
                            # A trail is at least two steps, one of them a link: the current page is often plain text.
                            if (collector["links"] >= 1 and max(collector["links"], collector["items"]) >= 2
                                    and len(self.breadcrumbs) < 5):
                                self.breadcrumbs.append({"links": collector["links"], "items": collector["items"],
                                                         "text": text[:200], "in_chrome": collector["in_chrome"]})
                    self._close_node(node, self.stack[j - 1][3] if j > 0 else None,
                                     self.stack[j - 2][3] if j > 1 else None)
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.in_other_title:
            return
        if self.depth["script"]:
            if self.scripts:
                self.scripts[-1]["parts"].append(data)
            return
        if self.depth["noscript"]:
            self.noscript_parts.append(data)
            return
        # Text after an element that ended the head early is body text, as browsers show it (FA-036): only text while
        # the head is really the head is left out.
        if self.depth["non_content"] or (self.in_head and not self.body_started):
            return
        if data and not data.strip():
            for collector in self.open_collectors:
                if collector.get("kind") == "heading":collector["had_whitespace_data"] = True
        text = _WS.sub(" ", data).strip()
        if not text:
            return
        chars = len(text)
        for frame in self.stack:
            node = frame[3]
            if node["tlen"] < NODE_TEXT_CAP:
                node["text"].append(text)
                node["tlen"] += chars + 1
        if self.stack:
            self.stack[-1][3]["own"] += chars
        if self.depth["footer"] and self.footer_len < 1000:
            self.footer_parts.append(text)
            self.footer_len += chars
        self.text_parts.append(text)
        self.text_in_main.append(self.depth["main"] > 0)
        self.text_in_chrome.append(self.depth["chrome"] > 0)
        self.text_kind.append("heading" if self.depth["heading"] else "link" if self.depth["label"] else "text")
        self.text_toggle.append(self.depth["toggle"] > 0)
        self.body_chars += chars
        self.words += len(text.split(" "))
        if self.depth["nosnippet"]:
            self.nosnippet_chars += chars
        if self.depth["main"]:
            self.main_chars += chars
            if self.depth["nosnippet"]:
                self.main_nosnippet_chars += chars
        if self.depth["p"]:
            self.paragraph_chars += chars
        for collector in self.open_collectors:
            if "parts" in collector:
                collector["parts"].append(text)
            if "chars" in collector:
                collector["chars"] += chars


    # -- Microdata / RDFa --------------------------------------------------------

    def _structured_start(self, tag: str, attr: dict[str, str]) -> None:
        microdata = "itemscope" in attr
        rdfa = bool(attr.get("typeof"))
        parent = self.item_stack[-1] if self.item_stack else None
        prop_names = []
        if parent is not None:
            names = attr.get("itemprop") if parent["_format"] == "microdata" else attr.get("property")
            prop_names = (names or "").split()
        if microdata or rdfa:
            types = (attr.get("itemtype") if microdata else attr.get("typeof")) or ""
            item = {"_format": "microdata" if microdata else "rdfa",
                    "@type": [_short_type(t) for t in types.split()] or None}
            if parent is not None and prop_names:
                for name in prop_names:
                    _add_prop(parent, _short_type(name), item)
            elif len(self.items) < MAX_ITEMS:
                self.items.append(item)
            if tag in VOID:
                return
            self.item_stack.append(item)
            self._pending_collectors = [{"kind": "item", "item": item}]
            return
        if not prop_names or parent is None:
            return
        value_attr = attr.get("content") if "content" in attr else attr.get(VALUE_ATTRS.get(tag, ""), None)
        if value_attr is not None or tag in VOID:
            for name in prop_names:
                _add_prop(parent, _short_type(name), (value_attr or "").strip())
            return
        self._pending_collectors = [{"kind": "itemprop", "item": parent, "name": _short_type(n), "parts": []}
                                    for n in prop_names]

    # -- div grids ------------------------------------------------------------------

    def _label_images(self, node: dict) -> None:
        """Mark the images an element holds directly as "beside a label" when its own short text names them."""
        if node["tag"] not in LABEL_PARENTS - {"figure"} or not 1 <= node["img_count"] <= LABEL_MAX_IMAGES:
            return
        text = " ".join(node["text"]).strip()
        if not 1 <= len(text) <= LABEL_MAX_CHARS:
            return
        # Proximity alone is not equivalence. A local label must actually name this image.
        # No propagation across table cells or whole rows; a column heading is not an icon's description.
        from urllib.parse import unquote, urlsplit
        for image in node["imgs"]:
            stem = urlsplit(unquote(image.get("src") or "")).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            # A caption/title does not describe the information inside a chart or photograph.
            if re.search(r"chart|graph|diagram|photo|foto|grafik", stem, re.I):
                continue
            words = {w for w in fold_text(stem).split() if not w.isdigit() and len(w) > 1}
            label = set(fold_text(text).split())
            if words and (words <= label or ''.join(w for w in fold_text(stem).split() if not w.isdigit()) == ''.join(fold_text(text).split()) or
                          ''.join(fold_text(stem).split()) == ''.join(fold_text(text).split())):
                image["beside_label"] = True
                image["equivalent_text"] = text[:LABEL_MAX_CHARS]
                image["equivalent_text_basis"] = "same local element; image filename matches label"

    def finish(self) -> None:
        """Elements the markup never closed (a <td> or <li> without its end tag) are settled when the page ends."""
        for frame in self.stack:
            self._label_images(frame[3])
        # A table inside a <form>, or in a block that holds a form control: a calculator's table (DECISIONS 223).
        for table in self.tables:
            nodes = table.pop("_nodes", [])
            table["has_controls"] = bool(table.pop("_form", False)) or any(node["controls"] for node in nodes)
        # A grid beside a form control in the same block (a calculator's result column next to its sliders), DECISIONS
        # 284: the control may come after the grid in the page, so it is settled here.
        for grid in self.div_grids:
            near = grid.pop("_near", [])
            if not grid["has_controls"] and any(n["controls"] or n["form"] for n in near):
                grid["has_controls"] = grid["controls_beside"] = True

    def _close_node(self, node: dict, parent: dict | None, grandparent: dict | None = None) -> None:
        self._label_images(node)
        text = _WS.sub(" ", " ".join(node["text"])).strip()
        summary = {"sig": node["sig"], "tag": node["tag"], "text": text[:NODE_TEXT_CAP],
                   "child_sigs": tuple(c["sig"] for c in node["children"]),
                   "child_tags": tuple(c["tag"] for c in node["children"]),
                   "cell_texts": [c["text"][:60] for c in node["children"]][:8],
                   "semantic": node["tag"] in SEMANTIC_BLOCKS or any(c["semantic"] for c in node["children"])}
        if node["tag"] in GRID_CONTAINERS and not node["in_chrome"] and len(node["children"]) >= 2:
            self._detect_grid(node, [parent, grandparent])
            self._detect_numbered(node)
        if parent is not None and len(parent["children"]) < 200:
            parent["children"].append(summary)

    def _detect_grid(self, node: dict, near: list | None = None) -> None:
        """A <div> container whose repeated children all have the same short cells: a table without <table>.
        `near` is its parent and grandparent block: a calculator's result column sits beside its input column, so a
        form control there is settled when the page ends (`finish`, DECISIONS 284)."""
        groups: dict[str, list[dict]] = defaultdict(list)
        for child in node["children"]:
            groups[child["sig"]].append(child)
        rows = max(groups.values(), key=len)
        if len(rows) < 2 or rows[0]["tag"] not in GRID_CONTAINERS | {"span"}:
            return
        cells = len(rows[0]["child_sigs"])
        if cells < 2 or any(r["child_sigs"] != rows[0]["child_sigs"] or r["semantic"] for r in rows):
            return
        if not set(rows[0]["child_tags"]) <= GRID_CELL_TAGS or len(rows) * cells < 6:
            return
        cell_texts = [t for r in rows for t in r["cell_texts"]]
        if not all(cell_texts) or max(len(t) for t in cell_texts) > 59 or sum(map(len, cell_texts)) / len(cell_texts) > 40:
            return  # empty cells or prose-length "cells" are cards, not a table
        if len(self.div_grids) < 50:
            self.div_grids.append({"container": node["sig"], "rows": len(rows), "cells_per_row": cells,
                                   "in_main": node["in_main"], "aria_role": node["role"],
                                   # Shown only after a click, or a copy that folds away: not where the facts live.
                                   "in_collapse": node["collapse"],
                                   "row_labels": [r["cell_texts"][0] for r in rows[:ROW_LABELS_KEPT]],
                                   "sample_rows": [r["cell_texts"] for r in rows[:4]],
                                   # What a person needs to find it on the page (DECISIONS 200), and how the page
                                   # line names it: the heading it sits under, else a short name (DECISIONS 223).
                                   "selector": node["selector"], "first_row": " | ".join(rows[0]["cell_texts"])[:FIRST_ROW_MAX],
                                   "heading": node["heading"], "label": node["label"][:SELECTOR_PART_MAX],
                                   # A calculator or a form: its rows are input fields (DECISIONS 223).
                                   "has_controls": bool(node["controls"] or node["form"]),
                                   "calculator_named": bool(CALCULATOR_NAME.search(
                                       " ".join([node["selector"], node["label"], node["heading"] or ""]))),
                                   "_near": [n for n in near or [] if n and n["tag"] not in PAGE_BLOCKS]})

    def _detect_numbered(self, node: dict) -> None:
        numbered = [c for c in node["children"] if c["tag"] in {"p", "div"} and NUMBERED.match(c["text"])]
        if len(numbered) >= 3 and len(self.numbered_runs) < 50:
            self.numbered_runs.append({"container": node["sig"], "items": len(numbered),
                                       "sample": [c["text"][:60] for c in numbered[:3]]})


def _collapses(attr: dict[str, str]) -> bool:
    """Whether an element opens and closes: a collapse or accordion by its class, its data-toggle or aria-expanded."""
    return (attr.get("data-toggle", "").lower() == "collapse" or attr.get("data-bs-toggle", "").lower() == "collapse"
            or "aria-expanded" in attr or any(_COLLAPSE_CLASS.search(token) for token in attr.get("class", "").lower().split()))


def _mentions_logo(attr: dict[str, str]) -> bool:
    return "logo" in f'{attr.get("class", "")} {attr.get("id", "")}'.lower()


def _short_type(value: str) -> str:
    """https://schema.org/Product, schema:Product -> Product."""
    value = value.strip().rstrip("/")
    return re.split(r"[/#:]", value)[-1] if value else value


def _add_prop(item: dict, name: str, value) -> None:
    if name in item:
        existing = item[name]
        item[name] = existing + [value] if isinstance(existing, list) else [existing, value]
    else:
        item[name] = value


def attrs_get(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    """Attribute value, "" for a present-but-empty attribute, None when absent."""
    for key, value in attrs:
        if key.lower() == name:
            return value or ""
    return None


_IMAGE_EXTENSION = re.compile(r"\.(avif|webp|jpe?g|png|gif|bmp|svg)(?=$|[?#\s,])", re.I)


MEDIA_TAGS = frozenset({"video", "lottie-player", "dotlottie-player", "dotlottie-wc"})
# Attributes that make an <a href="#"> a control the page's script drives (a menu toggle, a tab, a modal opener), not
# a link to content.
_CONTROL_ATTRS = ("aria-controls", "aria-expanded", "aria-haspopup", "data-toggle", "data-bs-toggle", "data-target",
                  "data-bs-target", "onclick", "data-modal", "data-modal-target", "data-micromodal-trigger", "data-dialog",
                  "data-fancybox", "data-popup", "data-open", "data-drawer", "popovertarget", "commandfor")
# What a control says when nothing in its markup marks it: signing in, the menu, search, closing, the cart, the
# language. English and Turkish, compared after folding case and Turkish letters ("GİRİŞ YAP" and "giris yap" match).
_CONTROL_WORDS = (
    "log in", "login", "log out", "logout", "sign in", "signin", "sign out", "sign up", "signup", "register", "create account",
    "create an account", "forgot password", "forgot your password", "forgot password?", "reset password", "my account", "account",
    "menu", "open menu", "close menu", "search", "close", "cart", "basket", "bag", "language", "select language", "change language",
    "giris yap", "giris", "cikis yap", "cikis", "uye ol", "uye girisi", "kayit ol", "hesap olustur", "sifremi unuttum", "sifreni mi unuttun",
    "hesabim", "menu", "menuyu ac", "menuyu kapat", "ara", "arama", "kapat", "sepet", "sepetim", "dil", "dil sec", "dil secimi",
    # The cookie-settings opener and a show/hide toggle (DECISIONS 177). These are consulted only for an <a> that
    # already has no address, so "Show" as the text of a real link is never read here.
    "cerez ayarlari", "cerez tercihleri", "cerez yonetimi", "cookie settings", "cookie preferences", "manage cookies",
    "gizle", "goster", "show", "hide", "show more", "show less", "daha fazla goster", "daha az goster")
# Class names that mark an <a> as a control: a token that contains "toggle" ("lwptoc_toggle_label"), a token that
# starts with one of these prefixes ("js-open-cookie-settings"), or one of these exact tokens. Deliberately narrow:
# "cookie" anywhere in a class, any "js-" class and "btn"/"button" were tried and rejected, because a link to the
# cookie policy and a link styled as a button are links to content.
_CONTROL_CLASS_PREFIXES = ("js-open-", "js-close-", "js-toggle-", "js-show-", "js-hide-")
_CONTROL_CLASSES = frozenset({"ot-sdk-show-settings", "cky-btn-accept", "cky-btn-reject", "cky-btn-preferences",
                                     "cmplz-accept", "cmplz-deny", "cmplz-save-preferences"})
_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def fold_text(text: str) -> str:
    """Lower case without Turkish letter marks or punctuation at the ends, for comparing short labels."""
    folded = (text or "").replace("İ", "i").replace("I", "i").lower().replace("\u0307", "").translate(_FOLD)
    return _WS.sub(" ", re.sub(r"[^\w\s]", " ", folded)).strip()


def control_marker(attr: dict[str, str]) -> str | None:
    """The attribute that marks an <a> as a control the page's script drives, or None."""
    if attr.get("role") in ("button", "tab", "menuitem", "switch"):
        return f'role="{attr["role"]}"'
    # Explicit consent actions identify controls, not navigation. Never infer from an arbitrary label.
    if any(key in attr for key in ('data-cky-tag', 'data-cookieconsent', 'data-cmplz-action', 'data-gdpr_action')):
        return 'explicit consent action'
    named = next((name for name in _CONTROL_ATTRS if name in attr), None)
    if named:
        return named
    for token in attr.get("class", "").lower().split():
        if "toggle" in token or token.startswith(_CONTROL_CLASS_PREFIXES) or token in _CONTROL_CLASSES:
            return f'class="{token}"'
    return None


def control_by_text(text: str) -> str | None:
    """The control a short label names ("Log in", "Şifremi unuttum", "Menü"), or None when it reads like a link to
    content ("Our services", "Read more"). A label with no text at all is an icon: a control, not a link to a page."""
    folded = fold_text(text)
    if not folded:
        return "no text (an icon)"
    return f"label “{text.strip()[:40]}”" if folded in _CONTROL_WORDS else None


def dead_link_kind(attr: dict[str, str], in_footer: bool, page_url: str | None = None) -> str | None:
    """Why an <a> leads nowhere, or None when it leads somewhere or is a script-driven control.

    `href="#"` and `href="javascript:..."` go nowhere for a visitor without the page's script, and for every
    crawler. An <a> with no href is not a link at all; it is reported only in the footer, where an entry that
    looks like a link and is not one is almost always an unfinished page list.
    """
    return None if control_marker(attr) else no_address(attr, in_footer, page_url)


def no_address(attr: dict[str, str], in_footer: bool, page_url: str | None = None) -> str | None:
    """Why an <a> has no address to follow, whatever else its markup says about it (see `dead_link_kind`)."""
    if "href" not in attr:
        return "no address (footer entry without href)" if in_footer and "name" not in attr and "id" not in attr else None
    href = attr["href"].strip()
    if page_url and "#" in href:
        # A reader that hands back "raw" HTML may already have made every address absolute: href="#" arrives as
        # href="https://site.example/page#". The page's own address with an empty fragment is still a link to nowhere.
        address, fragment = href.split("#", 1)
        if fragment in ("", "!") and address.rstrip("/") == page_url.split("#", 1)[0].rstrip("/"):
            href = "#" + fragment
    if href in ("#", "#!", ""):
        return 'href="#"' if href else "empty href"
    if href.lower().startswith("javascript:"):
        return "javascript: address"
    return None


def image_formats(addresses: str, mime: str | None = None) -> list[str]:
    """Image formats named by a src or srcset value ("a.webp 1x, a@2x.webp 2x") or a type ("image/avif")."""
    found = [m.group(1).lower().replace("jpeg", "jpg") for m in _IMAGE_EXTENSION.finditer(addresses or "")]
    if mime and mime.strip().lower().startswith("image/"):
        found.append(mime.strip().lower().removeprefix("image/").replace("jpeg", "jpg").replace("svg+xml", "svg"))
    return found


def _int(value: str | None) -> int | None:
    try:
        return int(str(value).strip().removesuffix("px"))
    except (TypeError, ValueError):
        return None


_CHARACTER_NAMES = {"\n": "newline (U+000A)", "\r": "carriage return (U+000D)", "\t": "tab (U+0009)"}
# How much of a broken block is quoted around the place the parser stopped (STR-3).
PARSE_EXCERPT_CHARS = 80
_LAST_KEY = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*(?:"(?:[^"\\]|\\.)*)?$', re.S)


def character_name(char: str) -> str:
    """A character as a person can find it: "newline (U+000A)", "control character U+0001", "'}' (U+007D)"."""
    if not char:
        return "end of the block"
    if char in _CHARACTER_NAMES:
        return _CHARACTER_NAMES[char]
    if ord(char) < 0x20 or 0x7F <= ord(char) < 0xA0:
        return f"control character U+{ord(char):04X}"
    return f"{char!r} (U+{ord(char):04X})"


def parse_error(raw: str, exc: json.JSONDecodeError) -> dict:
    """Where and why a JSON-LD block does not parse: the error, its line, column and character position, the character
    there by name, the property whose value it sits in, and an excerpt with control characters written out ("\\n").
    The idea of keeping the parse error comes from claude-seo's render_page.py (MIT); its parse step dropped the error."""
    pos = exc.pos or 0
    start = max(0, pos - PARSE_EXCERPT_CHARS // 2)
    excerpt = raw[start:start + PARSE_EXCERPT_CHARS]
    shown = "".join(c if c >= " " and c != "\x7f" else c.encode("unicode_escape").decode() for c in excerpt)
    key = _LAST_KEY.search(raw[:pos])
    return {"error_type": exc.msg.removesuffix(" at"), "line": exc.lineno, "column": exc.colno, "char_position": pos,
            "character": character_name(raw[pos:pos + 1]), **({"in_property": key.group(1)} if key else {}),
            "excerpt": ("…" if start else "") + shown + ("…" if start + PARSE_EXCERPT_CHARS < len(raw) else "")}


def _jsonld(scripts: list[dict]) -> tuple[list[dict], list]:
    """Parse every JSON-LD block: (block reports, parsed top-level values).

    A block that does not parse is reported with where and why (`parse_error`). It is also read once more leniently
    (control characters allowed inside strings, `json.loads(strict=False)`) only to say which types it describes
    ("recovered_types"): STR-3 then says "the Organization block does not parse" instead of "there is no Organization".
    What is read leniently is never used as structured data: engines ignore the whole block."""
    blocks, values = [], []
    for index, script in enumerate(s for s in scripts if "ld+json" in s["type"]):
        raw = "".join(script["parts"])
        try:
            value = json.loads(raw)
        except ValueError as exc:
            pos = getattr(exc, "pos", 0) or 0
            block = {"index": index, "ok": False, "error": str(exc)[:200],
                     "snippet": raw[max(0, pos - 60): pos + 60].strip()}
            if isinstance(exc, json.JSONDecodeError):
                block.update(parse_error(raw, exc))
            try:
                lenient = json.loads(raw, strict=False)
            except ValueError:
                lenient = None
            if lenient is not None:
                block["recovered_types"] = sorted({t for node, _ in iter_typed_nodes(lenient) for t in node_types(node)})
                block["recovered_properties"] = sorted({k for node, nested in iter_typed_nodes(lenient) if not nested
                                                        for k in node if not k.startswith("@")})[:40]
            blocks.append(block)
            continue
        blocks.append({"index": index, "ok": True})
        values.append(value)
    return blocks, values


# A byline in the markup: a class or id naming the author ("post-author", "byline", "yazar"); SEO-078 (DECISIONS 304).
AUTHOR_CLASS = re.compile(r"(?:^|[\s_-])(?:author|byline|yazar|article-author|post-author)(?:$|[\s_-])", re.IGNORECASE)
PRODUCT_TYPES = frozenset({"Product", "ProductGroup", "ProductModel", "IndividualProduct", "Vehicle", "Book"})
GTIN_KEYS = ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "isbn")
MAX_PRODUCTS = 5
MAX_OFFERS = 5


def _text(value) -> str | None:
    """A short plain value: a string or number as text, a node's name or @id; None when empty."""
    if isinstance(value, list):
        value = next((v for v in value if v not in (None, "", [], {})), None)
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id") or value.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()[:120]
    return None


def _offers(value) -> list[dict]:
    out = []
    for offer in value if isinstance(value, list) else [value]:
        if not isinstance(offer, dict):
            continue
        nested = offer.get("offers")
        if "AggregateOffer" in node_types(offer) and isinstance(nested, (list, dict)):
            out += _offers(nested)
            continue
        price = _text(offer.get("price")) or _text(offer.get("lowPrice"))
        out.append({"price": price, "priceCurrency": _text(offer.get("priceCurrency")),
                    "availability": (_text(offer.get("availability")) or "").rsplit("/", 1)[-1] or None,
                    **({"gtin": g} if (g := next((_text(offer.get(k)) for k in GTIN_KEYS if _text(offer.get(k))), None)) else {}),
                    **({"mpn": m} if (m := _text(offer.get("mpn"))) else {}),
                    **({"sku": k} if (k := _text(offer.get("sku"))) else {})})
    return out[:MAX_OFFERS]


def product_fields(values) -> list[dict]:
    """The key fields of each Product (or ProductGroup) node in parsed structured data, for the product checks
    (DECISIONS 304): `type`, `gtin` ({key: value} of gtin, gtin8/12/13/14, isbn), `mpn`, `sku`, `brand`, `offers` (at most
    5, each `price`, `priceCurrency`, `availability` and any identifier it carries), `has_variant` (how many) and
    `variant_identifiers` (variants with a gtin or mpn), `in_list` (a Product inside an ItemList, as category pages list
    them). At most 5 nodes; a Product nested in another Product (a variant) is counted on its group, not listed."""
    out = []
    for value in values:
        for node, nested in _product_nodes(value, False, False):
            types = set(node_types(node))
            gtin = {k: _text(node.get(k)) for k in GTIN_KEYS if _text(node.get(k))}
            variants = [v for v in (node.get("hasVariant") if isinstance(node.get("hasVariant"), list)
                                    else [node.get("hasVariant")]) if isinstance(v, dict)]
            record = {"type": sorted(types & PRODUCT_TYPES)[0] if types & PRODUCT_TYPES else sorted(types)[0],
                      "gtin": gtin, "mpn": _text(node.get("mpn")), "sku": _text(node.get("sku")),
                      "brand": _text(node.get("brand")), "offers": _offers(node.get("offers")),
                      "has_variant": len(variants),
                      "variant_identifiers": sum(1 for v in variants if _text(v.get("mpn")) or any(_text(v.get(k)) for k in GTIN_KEYS)
                                                 or any(o.get("gtin") or o.get("mpn") for o in _offers(v.get("offers")))),
                      "in_list": nested}
            out.append(record)
            if len(out) >= MAX_PRODUCTS:
                return out
    return out


def _product_nodes(value, in_list: bool, in_product: bool):
    """(node, in a list) for each Product-typed node not nested inside another Product."""
    if isinstance(value, dict):
        types = set(node_types(value)) if value.get("@type") else set()
        is_product = bool(types & PRODUCT_TYPES)
        if is_product and not in_product:
            yield value, in_list
        for key, child in value.items():
            if key in ("@context", "hasVariant", "isVariantOf"):
                continue
            yield from _product_nodes(child, in_list or "ItemList" in types or key == "itemListElement",
                                      in_product or is_product)
    elif isinstance(value, list):
        for child in value:
            yield from _product_nodes(child, in_list, in_product)


def jsonld_author(items) -> bool:
    """Whether any typed node of the page's structured data names an author (a Person or an Organization)."""
    return any(_text(node.get("author")) or (isinstance(node.get("author"), dict) and node["author"].get("@type"))
               for item in items for node, _ in iter_typed_nodes(item["data"]) if node.get("author"))


def iter_typed_nodes(value, nested: bool = False):
    """Yield (node, nested) for every dict with an @type, including @graph members and nested values."""
    if isinstance(value, dict):
        if value.get("@type"):
            yield value, nested
            nested = True
        for key, child in value.items():
            if key != "@context":
                yield from iter_typed_nodes(child, nested if key != "@graph" else False)
    elif isinstance(value, list):
        for child in value:
            yield from iter_typed_nodes(child, nested)


def node_types(node: dict) -> list[str]:
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    return [_short_type(t) for t in types if isinstance(t, str) and t]


def _accessible_for_free(scripts: list[dict]) -> list:
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "isAccessibleForFree":
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for script in scripts:
        if "ld+json" in script["type"]:
            try:
                walk(json.loads("".join(script["parts"])))
            except ValueError:
                continue
    return found


def _strip_formats(items: list[dict]) -> list[dict]:
    """Remove the internal _format marker from nested Microdata/RDFa items (top-level markers are popped by the caller)."""
    def walk(value):
        if isinstance(value, dict):
            for key in list(value):
                if key == "_format" and value is not top:
                    del value[key]
                else:
                    walk(value[key])
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for top in items:
        walk(top)
    return items


SKETCH_SIZE = 64
SHINGLE_WORDS = 5


def text_sketch(words: list[str]) -> list[int]:
    """Bottom-k sketch of 5-word shingles, for Estimated similarity (IDX-4, IDX-8)."""
    if not words:
        return []
    n = SHINGLE_WORDS
    shingles = {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}
    hashes = {int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big") for s in shingles}
    return sorted(hashes)[:SKETCH_SIZE]


def sketch_similarity(a: list[int], b: list[int]) -> float | None:
    """Estimated Jaccard similarity of two bottom-k sketches (exact when pages are short)."""
    if not a or not b:
        return None
    set_a, set_b = set(a), set(b)
    union_bottom = sorted(set_a | set_b)[:SKETCH_SIZE]
    return sum(1 for h in union_bottom if h in set_a and h in set_b) / len(union_bottom)


def compare_content(a: dict, b: dict, block_share: float = 0.8, sketch_threshold: float = 0.9) -> dict:
    """Whether two pages carry the same content, and the evidence for the call.

    1. Identical visible-text hash: same (Verified).
    2. Both pages' visible text in memory: the share of words that are identical and in the same order (difflib,
       deterministic). The share is a measurement; calling it "the same content" against `block_share` is a
       threshold judgement, so Estimated. The differing passages are quoted.
       Why not the shingle sketch alone: on a real site (Midas, 2026-09-22) the same article at /x and /x/ shared
       90% of its words — only a "latest posts" list differed, cached on different days — yet the sketch estimated
       0.69 and called it different content (S2). Two different articles on that site's template share 42%. Words,
       not text blocks, because one edited word in a long paragraph would make the whole block "different".
    3. Otherwise (a saved report has no text in memory): the shingle-sketch estimate against `sketch_threshold`.
    Returns {"same": bool | None, "basis", "value", "confidence", "differing_blocks"}.
    """
    import difflib

    if a.get("text_sha256") and a.get("text_sha256") == b.get("text_sha256"):
        return {"same": True, "basis": "identical visible text (hash)", "value": 1.0, "confidence": "verified",
                "differing_blocks": []}
    words_a, words_b = (a.get("_visible_text") or "").split()[:20000], (b.get("_visible_text") or "").split()[:20000]
    if words_a and words_b:
        matcher = difflib.SequenceMatcher(a=words_a, b=words_b, autojunk=False)
        same_words = sum(block.size for block in matcher.get_matching_blocks())
        differing = [{"this_page": " ".join(words_a[i1:i2])[:160], "other_page": " ".join(words_b[j1:j2])[:160]}
                     for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal"][:6]
        share = same_words / max(len(words_a), len(words_b))
        return {"same": share >= block_share, "basis": f"share of words identical and in the same order (same at "
                f">= {block_share:g})", "value": round(share, 3), "confidence": "estimated",
                "differing_blocks": differing}
    similarity = sketch_similarity(a.get("text_sketch") or [], b.get("text_sketch") or [])
    if similarity is None:
        return {"same": None, "basis": "no text to compare", "value": None, "confidence": "not_assessed",
                "differing_blocks": []}
    return {"same": similarity >= sketch_threshold, "basis": f"estimated similarity, shingle sketch (same at >= "
            f"{sketch_threshold:g})", "value": round(similarity, 3), "confidence": "estimated", "differing_blocks": []}


# Characters that show nothing and can split a word for a search engine (DECISIONS 210): zero-width space, zero-width
# non-joiner, word joiner, the byte-order mark used as a zero-width no-break space, and the soft hyphen. U+200D (the
# zero-width joiner) is left out: emoji sequences need it.
INVISIBLE = {"\u200b": "U+200B", "\u200c": "U+200C", "\u2060": "U+2060", "\ufeff": "U+FEFF", "\u00ad": "U+00AD"}
_INVISIBLE = re.compile("[" + "".join(INVISIBLE) + "]")


def invisible_characters(blocks: list[str]) -> dict | None:
    """{"count", "inside_words", "by_character", "examples"} for the invisible characters in `blocks` (the main text),
    or None when there is none. "inside_words" counts the ones with a letter on both sides; an example is the word
    around one, with the character written as [U+200B]."""
    count = inside = 0
    by_character: dict[str, int] = {}
    examples: list[str] = []
    for block in blocks:
        for found in _INVISIBLE.finditer(block):
            count += 1
            name = INVISIBLE[found.group()]
            by_character[name] = by_character.get(name, 0) + 1
            at = found.start()
            before = block[at - 1] if at else ""
            after = block[at + 1] if at + 1 < len(block) else ""
            if before.isalpha() and after.isalpha():
                inside += 1
                if len(examples) < 3:
                    start = max(0, block.rfind(" ", 0, at) + 1)
                    end = block.find(" ", at)
                    word = block[start:end if end >= 0 else len(block)][:60]
                    shown = _INVISIBLE.sub(lambda m: f"[{INVISIBLE[m.group()]}]", word)
                    if shown not in examples:
                        examples.append(shown)
    if not count:
        return None
    return {"count": count, "inside_words": inside, "by_character": by_character, "examples": examples}


_HEAD_OPEN = re.compile(r"<head(?=[\s>/])", re.IGNORECASE)
_HEAD_CLOSE = re.compile(r"</head\s*>", re.IGNORECASE)


def head_tags(html: str) -> dict:
    """{"open": n, "close": n, "close_lines": [line of each </head>, at most 5]} in the raw HTML as sent."""
    text = html or ""
    closes = [m.start() for m in _HEAD_CLOSE.finditer(text)]
    return {"open": len(_HEAD_OPEN.findall(text)), "close": len(closes),
            "close_lines": [text.count("\n", 0, i) + 1 for i in closes[:5]]}


def analyze_html(html: str, page_url: str | None = None) -> dict:
    """What the checks read on one page. `page_url` is the page's own address, given when the HTML came through a
    reader that rewrites addresses (so a link to "this page, nowhere in particular" is still recognised)."""
    # Documents embedded in the page (an iframe a reader wrote into it) are not the page's: see maya_audit.own_document.
    # Sizes and offsets below are still those of the HTML as it was received.
    received, spans = html, embedded_spans(html)
    html = without(received, spans)
    parser = _Analyzer()
    parser.page_url = page_url
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup: keep what was parsed
        pass
    parser.finish()
    title = _WS.sub(" ", "".join(parser.title_parts)).strip()
    visible_text = " ".join(parser.text_parts)
    words = visible_text.lower().split()

    blocks, values = _jsonld(parser.scripts)
    items = [{"format": "json-ld", "data": v} for v in values] + \
            [{"format": it.pop("_format"), "data": it} for it in _strip_formats(parser.items)]
    types = sorted({t for item in items for node, _ in iter_typed_nodes(item["data"]) for t in node_types(node)})
    og: dict[str, list[str]] = defaultdict(list)
    for entry in parser.properties + [{"property": m["name"], "content": m["content"]} for m in parser.meta]:
        if entry["property"].startswith("og:") and entry["content"]:
            og[entry["property"]].append(entry["content"])

    def first_own(pattern: str):
        return next((m for m in re.finditer(pattern, received, re.I)
                     if not any(start <= m.start() < end for start, end, _ in spans)), None)

    content_blocks = [text for text, in_main, in_chrome in
                      zip(parser.text_parts[:5000], parser.text_in_main, parser.text_in_chrome)
                      if not in_chrome and (in_main or not parser.saw_main)]
    invisible = invisible_characters(content_blocks)
    tags = _LINK_TAG.sub("", html)  # where analytics loaders are counted: scripts, not <link> hints (G10)

    anchor = first_own(r"<(main|article)\b")
    basis = "main/article element" if anchor else None
    if anchor is None:
        anchor = first_own(r"<h1\b")
        basis = "first <h1> (estimate)" if anchor else None

    result = {
        "canonicals": parser.canonicals,
        "text_sha256": hashlib.sha256(" ".join(words).encode()).hexdigest() if words else None,
        "text_sketch": text_sketch(words),
        "title": title or None,
        "meta": parser.meta,
        # <meta property="..."> tags: og:*, article:* and the like (the "og" key below keeps only og:*).
        "meta_properties": parser.properties[:MAX_ITEMS],
        "template_urls": parser.template_urls,
        "verification_tokens": [m["content"] for m in parser.meta if m["name"] == VERIFICATION_META],
        "visible_words": parser.words,
        "visible_chars": parser.body_chars,
        "data_nosnippet_chars": parser.nosnippet_chars,
        "has_main_region": parser.saw_main,
        "main_region_types": sorted(parser.main_region_types),
        "main_region_chars": parser.main_chars,
        "main_region_nosnippet_chars": parser.main_nosnippet_chars,
        "paragraph_chars": parser.paragraph_chars,
        "headings": parser.headings,
        "h1_elements": parser.h1_elements,
        "heading_counts": {"total": parser.heading_count, "details_retained": len(parser.headings),
                            "skipped_level_jumps_total": parser.heading_level_skips_total,
                            "skipped_level_jumps": parser.heading_level_skips},
        "mount_nodes": [{"id": m["id"], "chars": m["chars"]} for m in parser.mounts],
        "noscript_text": _WS.sub(" ", " ".join(parser.noscript_parts)).strip()[:500],
        "inline_script_chars": sum(len("".join(s["parts"])) for s in parser.scripts if not s["src"] and "json" not in s["type"]),
        "external_scripts": sum(1 for s in parser.scripts if s["src"]),
        "tabpanels": [{"id": t["id"], "chars": t["chars"]} for t in parser.tabpanels],
        "styled_headings": parser.styled_headings,  # DECISIONS 338
        "buttons": [{"text": _WS.sub(" ", " ".join(b["parts"])).strip()[:80], "in_form": b["in_form"], "type": b["type"],
                     "in_chrome": b["in_chrome"]} for b in parser.buttons][:MAX_ITEMS],
        # Outside the header, menu, footer and sidebar only.
        "input_buttons": parser.input_buttons,
        "form_actions": parser.form_actions,
        "dead_links": [{"text": _WS.sub(" ", " ".join(d["parts"])).strip()[:80], "why": d["why"], "in_footer": d["in_footer"],
                        **({"where": d["where"]} if d.get("where") else {})}
                       for d in parser.dead_links],
        "dead_link_total": parser.dead_link_total,
        "link_controls": [{"text": _WS.sub(" ", " ".join(d["parts"])).strip()[:80], "why": d["why"], "control": d["control"]}
                          for d in parser.link_controls],
        "link_control_total": parser.link_control_total,
        "media": parser.media,
        # H30/H34: scripts loaded from a file, where they sit and how they load; preloaded images (H30); http://
        # sub-resources (H32); tag-manager and analytics ids per loader, with how often each is printed (H33).
        "external_scripts": [{"src": s["src"].strip()[:300], "type": s["type"], "in_head": s["in_head"],
                              "async": s["async"], "defer": s["defer"]} for s in parser.scripts if (s["src"] or "").strip()][:60],
        "image_preloads": parser.preloads,
        "insecure_refs": parser.insecure_refs,
        "analytics_ids": {kind: dict(Counter(a or b for a, b in pattern.findall(tags)) if pattern is GTM_LOADER
                                     else Counter(pattern.findall(tags)))
                          for kind, pattern in (("gtm_script", GTM_LOADER), ("gtm_noscript", GTM_NOSCRIPT),
                                                ("gtag", GTAG_LOADER))},
        "images": parser.images,
        "image_counts": parser.image_counts,
        "iframes": parser.iframes,
        # Documents a page reader wrote into the page in place of an iframe: taken out before anything was read,
        # and not counted as iframes (their content was never the page's).
        "embedded_documents": records(spans),
        # A <title>, <meta name> or canonical link after the body started: not read as the page's.
        "outside_head": {"title": parser.outside_title, "meta": parser.outside_meta, "canonical": parser.outside_canonical,
                         "closed_early_by": parser.head_closed_by, "hreflang": parser.outside_hreflang,
                         "robots_content": parser.outside_robots,
                         "properties": parser.outside_properties},
        # DECISIONS 344: how many <head> and </head> the raw source writes, and each </head>'s line
        "head_tags": head_tags(html),
        "canvases": [{"in_main": c["in_main"], "aria_label": c["aria_label"], "fallback_chars": c["chars"],
                      "hidden": c["hidden"], "role": c["role"], "hint": c["hint"]} for c in parser.canvases],
        "pdf_links": parser.pdf_links,
        "breadcrumbs": parser.breadcrumbs,
        # SEO-046 (DECISIONS 304, schema 1.24): <link rel="next"> / <link rel="prev"> hrefs as written, when present.
        **({"pagination_links": parser.pagination_links} if parser.pagination_links else {}),
        # SEO-078: where the page names an author (byline element, rel/itemprop author, JSON-LD author, meta author).
        "author_signals": sorted(parser.author_signals | ({"JSON-LD author"} if jsonld_author(items) else set())
                                 | ({"meta author"} if any(m["name"] == "author" and m["content"] for m in parser.meta) else set())),
        "accessible_for_free": _accessible_for_free(parser.scripts),
        "html_lang": parser.html_lang,
        "hreflang": parser.hreflang,
        "og": {k: v[:5] for k, v in og.items()},
        "structured_data": {
            "jsonld_blocks": blocks,
            "formats": sorted({item["format"] for item in items}),
            "types": types,
            # The key Product fields (DECISIONS 304, schema 1.24): identifiers, brand and offers, per Product node.
            **({"products": products} if (products := product_fields([item["data"] for item in items])) else {}),
        },
        "footer_text": _WS.sub(" ", " ".join(parser.footer_parts)).strip()[:1000],
        "logo_alts": parser.logo_alts,
        "time_elements": [{"datetime": t["datetime"], "itemprop": t["itemprop"], "text": t.get("text", ""),
                           "in_chrome": t["in_chrome"]} for t in parser.times],
        "tables": parser.tables,
        "div_grids": parser.div_grids,
        "numbered_paragraph_runs": parser.numbered_runs,
        # STR-13 (DECISIONS 210): zero-width and soft-hyphen characters in the main text, only when there are some.
        **({"invisible_chars": invisible} if invisible else {}),
        "html_chars": len(received),
        "main_offset_bytes": len(received[: anchor.start()].encode()) if anchor else None,
        "main_offset_basis": basis,
        # In memory only (keys starting with "_" are not written to reports).
        "_visible_text": visible_text[:100_000],
        # Text nodes as they appear, so a check can quote one line of the page instead of a run-on string (ANS-2).
        "_text_blocks": parser.text_parts[:5000],
        # The same text nodes with header, navigation, footer and sidebar left out (see maya_audit.main_content).
        "_content_blocks": content_blocks,
        # "heading" | "link" | "text" for each entry of _content_blocks.
        "_content_block_kinds": [kind for kind, in_main, in_chrome in
                                 zip(parser.text_kind[:5000], parser.text_in_main, parser.text_in_chrome)
                                 if not in_chrome and (in_main or not parser.saw_main)],
        # P4: whether each entry of _content_blocks sits in a <summary> or <dt> (an accordion's toggle, a term).
        "_content_block_toggles": [toggle for toggle, in_main, in_chrome in
                                   zip(parser.text_toggle[:5000], parser.text_in_main, parser.text_in_chrome)
                                   if not in_chrome and (in_main or not parser.saw_main)],
        "_structured_items": items,
        # JSON-LD blocks as written, for checks that read the source rather than the parsed values.
        "_jsonld_raw": ["".join(s["parts"])[:60_000] for s in parser.scripts if "ld+json" in s["type"]][:20],
    }
    from .element_context import enrich
    enrich(html, result, page_url)
    from .table_semantics import inspect_tables
    result["_table_semantics"] = inspect_tables(html)
    return result
