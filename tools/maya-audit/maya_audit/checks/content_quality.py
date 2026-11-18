"""STR-13 to STR-17: template markers never filled in, anchor text that says nothing, thin pages,
shared meta descriptions, and pages with no link onward.

STR-13: template markers that were never filled in.

A page built from a template has slots: `{{publishDate}}`, `{{author_name}}`, `[[cta]]`, an editor's
`‹teyit›` ("confirm this"). When a slot is published as it is, a reader sees the marker, and a search
or answer engine reads `{{publishDate}}` as the date. This check finds such markers and says exactly
where each one sits: visible text, the title, a meta tag, JSON-LD, or a link or image address.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import median
from urllib.parse import urlsplit

from .. import shared_elements
from ..analysis import template_markers
from ..config import GENERIC_ANCHORS, TEMPLATE_MARKERS, THIN_CONTENT_EXEMPT, THIN_CONTENT_WORDS, CrawlConfig
from ..language import turkish_fold
from ..page_words import fold
from ..main_content import main_words, repeated_blocks
from ..urls import is_pagination
from ..findings import CheckResult, Finding, Rationale, Severity, scope_for
from ..models import Confidence, CrawlResult
from .access import _status, _tier

RAW_ONLY = "raw HTML only (filled in by the browser)"
WHERE = ("JSON-LD", "meta tag", "title", "link or image URL", "visible text", RAW_ONLY)
# A marker in a field a machine reads as data is wrong for certain. In visible text it is very likely wrong,
# but a page rendered in the browser can ship {{ }} in its raw HTML on purpose.
SEVERITY = {"JSON-LD": Severity.S2, "meta tag": Severity.S2, "title": Severity.S2, "link or image URL": Severity.S2,
            "visible text": Severity.S3, RAW_ONLY: Severity.INFO}
FIX = {
    "JSON-LD": "Fill the structured-data fields with real values, or remove the block. Engines read these fields as data.",
    "meta tag": "Fill the meta tag with its real value, or remove it.",
    "title": "Replace the marker in the <title> with the real text.",
    "link or image URL": "Replace the address with the real one. As it is, the link or image cannot load.",
    "visible text": "Replace the marker with the real text, or remove the unfinished passage.",
    RAW_ONLY: "Nothing to fix for readers. To give crawlers that do not run JavaScript the real text, send it in "
              "the page's HTML from the server.",
}


def _around(text: str, marker: str, before: int = 60, after: int = 60) -> str:
    at = text.find(marker)
    return " ".join(text[max(0, at - before): at + len(marker) + after].split())


def _jsonld_paths(value, marker: str, path: str = "") -> list[str]:
    """Where in a parsed JSON-LD value `marker` occurs: "BlogPosting.author.name"."""
    out = []
    if isinstance(value, dict):
        kind = value.get("@type")
        here = path or (kind if isinstance(kind, str) else (kind[0] if isinstance(kind, list) and kind else "") or "")
        for key, inner in value.items():
            out += _jsonld_paths(inner, marker, f"{here}.{key}" if here else str(key))
    elif isinstance(value, list):
        for inner in value:
            out += _jsonld_paths(inner, marker, path)
    elif isinstance(value, str) and marker in value:
        out.append(path)
    return out


def page_markers(page) -> list[dict]:
    """Every unfilled marker on one page: {"where", "marker", "field", "sample"}."""
    a = page.analysis
    rows: list[dict] = []
    seen: set[tuple] = set()

    def add(where: str, marker: str, field: str | None, sample: str) -> None:
        key = (where, marker, field)
        if key not in seen and len(rows) < 80:
            seen.add(key)
            rows.append({"where": where, "marker": marker, "field": field, "sample": sample[:240]})

    parsed = [item["data"] for item in a.get("_structured_items") or [] if item.get("format") == "json-ld"]
    for number, raw in enumerate(a.get("_jsonld_raw") or [], 1):
        for marker in template_markers(raw):
            paths = sorted({p for data in parsed for p in _jsonld_paths(data, marker)})
            for path in paths or [None]:
                add("JSON-LD", marker, path or f"block {number} (the block does not parse, or the marker is in a key)",
                    _around(raw, marker, 50, 50))
    for meta in a.get("meta") or []:
        for marker in template_markers(meta.get("content", "")):
            add("meta tag", marker, f'name="{meta["name"]}"', meta["content"])
    for meta in a.get("meta_properties") or []:
        for marker in template_markers(meta.get("content", "")):
            add("meta tag", marker, f'property="{meta["property"]}"', meta["content"])
    for marker in template_markers(a.get("title") or ""):
        add("title", marker, "<title>", a["title"])
    for entry in a.get("template_urls") or []:
        for marker in entry["markers"]:
            add("link or image URL", marker, f'<{entry["tag"]} {entry["attribute"]}>', entry["value"])
    for block in a.get("_text_blocks") or []:
        if "{" in block or "[[" in block or "‹" in block or "<%" in block:
            for marker in template_markers(block):
                add("visible text", marker, None, _around(block, marker))
    return rows


# STR-13: a page is reported from this many invisible characters in its main text (DECISIONS 210; LG-82).
INVISIBLE_MIN = 10


def str13_template_markers(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    title = "Unfilled template markers"
    if not pages:
        return CheckResult("STR-13", title, "not_assessed", "No indexable HTML pages.")
    from .render import _rendered_ok  # here, not at the top: render.py imports this package's helpers too

    rendered = _rendered_ok(result)
    by_where: dict[str, list[dict]] = {where: [] for where in WHERE}
    for page in pages:
        entry = rendered.get(page.url)
        after_js = entry["rendered"].get("_visible_text", "") if entry else None
        for row in page_markers(page):
            if row["where"] == "visible text" and after_js is not None:
                # The browser's view settles it: a slot the page's own script fills in is not a leftover.
                row["in_rendered_view"] = row["marker"] in after_js
                if not row["in_rendered_view"]:
                    row["where"] = RAW_ONLY
            by_where[row["where"]].append({"url": page.url, **row})
    findings = []
    for where in WHERE:
        rows = by_where[where]
        if not rows:
            continue
        urls = sorted({row["url"] for row in rows})
        markers = list(dict.fromkeys(row["marker"] for row in rows))
        shown = ", ".join(markers[:6]) + (f" and {len(markers) - 6} more" if len(markers) > 6 else "")
        notes = ["The marker is Verified as present in the page source at the place shown."]
        if where == "visible text":
            seen = sorted({row["url"] for row in rows if row.get("in_rendered_view")})
            if seen:
                notes.append(f"On {len(seen)} of these page(s) the marker is still there after the page was rendered "
                             "in a browser: a reader sees it.")
            if len(seen) < len(urls):
                notes.append("S3, not S2: a page that fills its text in the browser can carry {{ }} in its raw HTML on "
                             "purpose, and the pages not marked as rendered were not opened in a browser. Open the "
                             "page; if a reader sees the marker, it is a real leftover.")
        headline = (f"{len(urls)} page(s) have unfilled template markers in {where if where != 'title' else 'the title'}: {shown}")
        if where == RAW_ONLY:
            headline = f"{len(urls)} page(s) have template markers in the {RAW_ONLY}: {shown}"
            notes = ["The marker is in the HTML the server sends and gone from the text once the page was rendered in a "
                     "browser, so a reader does not see it. A crawler that does not run JavaScript reads the marker.",
                     "Info: this is how a page that fills its text in the browser is built, not a leftover."]
        findings.append(Finding(
            "STR-13", headline,
            SEVERITY[where], Confidence.VERIFIED, Rationale.SELF_EVIDENT.value,
            ["crawlers that do not run JavaScript"] if where == RAW_ONLY else
            ["all answer engines that quote page text or read structured data"], scope_for(urls),
            {"where": where, "markers": markers[:40], "found": rows[:80], "found_count": len(rows)},
            "published pages carry real values, not template slots", FIX[where],
            importance_tier=_tier(urls, key_urls), notes=notes))
    total = sum(len(rows) for rows in by_where.values())
    # Invisible characters in the main text (DECISIONS 210): zero-width spaces, soft hyphens and the like, counted in
    # the page's own text (header, menu, footer and sidebars left out), reported from INVISIBLE_MIN on one page.
    invisible = [{"url": page.url, **page.analysis["invisible_chars"]} for page in pages
                 if (page.analysis.get("invisible_chars") or {}).get("count", 0) >= INVISIBLE_MIN]
    if invisible:
        invisible.sort(key=lambda row: -row["count"])
        urls = [row["url"] for row in invisible]
        count = sum(row["count"] for row in invisible)
        findings.append(Finding(
            "STR-13", f"{len(urls)} page(s) have invisible characters in the main text ({count} in all)", Severity.S4,
            Confidence.VERIFIED, Rationale.SELF_EVIDENT.value, ["all answer engines that quote page text"], scope_for(urls),
            {"pages": invisible[:40], "characters": ["U+200B", "U+200C", "U+2060", "U+FEFF", "U+00AD"],
             "minimum_per_page": INVISIBLE_MIN, "counted_in": "the main text (header, menu, footer and sidebars left out)",
             "not_counted": "U+200D (the zero-width joiner emoji need)"},
            "the main text holds no invisible characters",
            'Review the quoted invisible characters in context. Remove accidental characters, preserving intentional language and formatting. Their presence alone does not establish how a search engine tokenizes or ranks the page.',
            importance_tier=_tier(urls, key_urls)))
    summary = (f"{len(findings)} finding(s): {total} unfilled marker(s) on "
               f"{len({row['url'] for rows in by_where.values() for row in rows})} page(s)." if total else
               f"{len(findings)} finding(s)." if findings else
               f"No unfilled template marker in the text, title, meta tags, JSON-LD or link and image addresses of {len(pages)} page(s).")
    return CheckResult("STR-13", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "markers_looked_for": [name for name, _ in TEMPLATE_MARKERS],
                        "places_checked": [where for where in WHERE if where != RAW_ONLY],
                        "pages_with_invisible_characters": sum(1 for page in pages if page.analysis.get("invisible_chars"))})


# -- STR-14 --------------------------------------------------------------------

_ANCHOR_NOISE = re.compile(r"[^\w\s]|_", re.UNICODE)
GENERIC = frozenset(GENERIC_ANCHORS)


def generic_anchor(text: str) -> str | None:
    """The generic phrase an anchor text amounts to ("Devamını Oku »" -> "devamını oku"), or None.

    Folded the Turkish way and the ordinary way (B07): the Turkish fold turns "CLICK HERE" into "clıck here", which
    no English phrase matches."""
    for folded in (turkish_fold(text or ""), (text or "").casefold()):
        plain = " ".join(_ANCHOR_NOISE.sub(" ", folded).split())
        if plain in GENERIC:
            return plain
    return None


# P4: an address word that looks like a misspelling of the page's own name (no dictionary, any language): a slug word
# of SLUG_TYPO_MIN_CHARS or more that none of the page's labels (title, <h1>, the text of links to it) holds, while one
# of them holds a word of the same length that differs in one letter, and not in the last one (an ending that changes
# is inflection: "kokular"/"kokuları"). Seen live: /ciceksi-kukular, linked as "Çiçeksi Kokular".
SLUG_TYPO_MIN_CHARS = 5
SLUG_TYPOS = "addresses whose words look misspelled against the page's own name"
_WORD = re.compile(r"[a-z]+")


def slug_typos(pages: list) -> list[dict]:
    labels: dict[str, set[str]] = defaultdict(set)
    for page in pages:
        a = page.analysis or {}
        labels[page.url].update(_WORD.findall(fold(a.get("title") or "")))
        for h1 in a.get("h1_elements") or []:
            labels[page.url].update(_WORD.findall(fold(h1.get("text") or "")))
        for edge in page.outlinks or []:
            for anchor in edge.get("anchors") or [edge.get("anchor") or ""]:
                labels[edge["target"]].update(_WORD.findall(fold(anchor)))
    rows = []
    for page in pages:
        words = labels.get(page.url) or set()
        for segment in urlsplit(page.url).path.split("/"):
            for token in _WORD.findall(fold(segment)):
                if len(token) < SLUG_TYPO_MIN_CHARS or token in words:
                    continue
                near = sorted(w for w in words if len(w) == len(token)
                              and [i for i, (x, y) in enumerate(zip(w, token)) if x != y] in ([i] for i in range(len(token) - 1)))
                if near:
                    rows.append({"url": page.url, "address_word": token, "page_name_word": near[0]})
    return rows


def str14_anchor_text(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    """Links to this site whose text says nothing about the page they lead to, and links with no text at all.

    A link is reported only when the page gives its target no better name: a card whose title links to the
    article and whose "Devamı" button links to it again is fine, because the title names the target."""
    title = "Anchor text of internal links"
    if not pages:
        return CheckResult("STR-14", title, "not_assessed", "No indexable HTML pages.")
    generic_rows, empty_rows, phrases = [], [], Counter()
    links_total = targets_total = generic_links = empty_links = 0
    for page in pages:
        for edge in page.outlinks:
            anchors = edge.get("anchors")
            if anchors is None:  # a page record from before every anchor text was kept
                anchors = [edge["anchor"]] if edge.get("anchor") else []
            count, empty = edge.get("links", 1), edge.get("empty", 0 if anchors else 1)
            links_total += count
            targets_total += 1
            matched = [phrase for phrase in (generic_anchor(text) for text in anchors) if phrase]
            if anchors and len(matched) == len(anchors):
                generic_links += count - empty
                phrase_counts = Counter()
                if edge.get('anchor_counts'):
                    for text, n in edge['anchor_counts'].items():
                        if generic_anchor(text):
                            phrase_counts[generic_anchor(text)] += n
                elif len(set(matched)) == 1:
                    phrase_counts[matched[0]] = count - empty
                # A legacy record with mixed distinct names has no per-phrase occurrence count.
                phrases.update(phrase_counts)
                generic_rows.append({"source": page.url, "target": edge["target"], "anchor": anchors[0],
                                     "phrase_occurrences": dict(phrase_counts),
                                     "links": count, "links_with_generic_text": count - empty, "in_navigation": bool(edge.get("nav")),
                                     **({"in_footer": True} if edge.get("footer") else {})})
            elif not anchors and empty:
                empty_links += empty
                empty_rows.append({"source": page.url, "target": edge["target"], "links": empty,
                                   "in_navigation": bool(edge.get("nav")),
                                   # as the page wrote them, fragment included: what tells one icon link from another
                                   **({"hrefs": edge["hrefs"], "where": edge.get("where")} if edge.get("hrefs") else {}),
                                   # the nearest element around it with a class or an id: what a repeated block is called
                                   **({"block": edge["block"]} if edge.get("block") else {})})
    findings = []
    engines = ["Google", "Bing", "answer engines that follow links"]
    page_urls = [page.url for page in pages]
    shared_generic: dict[tuple, list[dict]] = {}
    if generic_rows:
        # The same generic link on most pages (a cookie notice's "tıklayınız") is one element: reported once for the
        # whole site, by its address and its text, and taken out of each page's row (maya_audit.shared_elements).
        def generic_key(row: dict) -> tuple:
            return (row["target"], " ".join(turkish_fold(row.get("anchor") or "").split()))
        by_page_generic: dict[str, set] = defaultdict(set)
        for row in generic_rows:
            by_page_generic[row["source"]].add(generic_key(row))
        split_generic = shared_elements.split(by_page_generic, page_urls)
        for key in split_generic:
            shared_generic[key] = [row for row in generic_rows if generic_key(row) == key]
        generic_rows = [row for row in generic_rows if generic_key(row) not in shared_generic]
        if shared_generic:  # the phrases named in the per-page finding's title are those of the links left in it
            phrases = Counter()
            for row in generic_rows:
                phrases.update(row['phrase_occurrences'])
    generic_like = None
    if generic_rows or shared_generic:
        urls = sorted({row["source"] for row in generic_rows})
        top = ", ".join(f'"{phrase}" ({n})' for phrase, n in phrases.most_common(5))
        generic_like = (Finding(
            "STR-14", f"{sum(r['links_with_generic_text'] for r in generic_rows)} link(s) on {len(urls)} page(s) name their target only with generic text: {top}",
            Severity.S4, Confidence.VERIFIED, "Documented (anchor text tells engines and readers what the linked page is about)",
            engines, scope_for(urls),
            {"links": generic_rows[:80], "count": len(generic_rows), "occurrences": sum(r["links_with_generic_text"] for r in generic_rows), "count_unit": "source-target groups", "title_count_unit": "DOM occurrences", "phrases": dict(phrases.most_common(20)),
             "rule": "reported only when every anchor text the page uses for that target is a generic phrase"},
            "a link's text says what the linked page is about",
            "Use the linked page's actual topic as the link text, or add that topic with a visually hidden label. Check the destination before writing it.",
            importance_tier=_tier(urls, key_urls),
            notes=["The phrase list covers English and Turkish only (config.GENERIC_ANCHORS)."]))
        if generic_rows:
            findings.append(generic_like)
        for (target, _folded), rows in sorted(shared_generic.items(), key=lambda item: -len(item[1])):
            on = sorted({row["source"] for row in rows})
            text = " ".join((rows[0].get("anchor") or "").split())
            # A named link's edge says only whether it sits in the navigation (a <nav> or the <header>) or in a <footer>.
            where = shared_elements.region("footer" if row.get("in_footer") else "nav" if row.get("in_navigation") else None for row in rows)
            findings.append(shared_elements.finding(
                generic_like, "link_generic", {"type": "link", "href": shared_elements.shown_address(target, result.origin), "text": text,
                                               "where": where},
                on, {"links": rows[:80], "count": len(rows), "rule": generic_like.evidence["rule"]}, importance_tier=_tier(on, key_urls),
                section=split_generic.section((target, _folded), on), text=text, href=shared_elements.shown_address(target, result.origin)))
    if empty_rows:
        # The same nameless link on most pages (an icon in the header) is one element: reported once for the whole
        # site, by its address as written, and taken out of each page's row (maya_audit.shared_elements).
        keys_of = {id(row): {shared_elements.link_key(href, row["source"]) for href in row.get("hrefs") or []} for row in empty_rows}
        by_page: dict[str, set] = defaultdict(set)
        for row in empty_rows:
            by_page[row["source"]] |= keys_of[id(row)]
        shared = shared_elements.split(by_page, page_urls)
        everywhere = [row for row in empty_rows if keys_of[id(row)] and keys_of[id(row)] <= shared]
        empty_rows = [row for row in empty_rows if not (keys_of[id(row)] and keys_of[id(row)] <= shared)]
        # What is left may still be one template element whose address differs on every page: each product page's
        # link to its own photo. Known by the pattern the addresses follow, and reported once with one example.
        def pattern_of(row: dict) -> str | None:
            found = {shared_elements.address_pattern(key, result.origin) for key in keys_of[id(row)]}
            return found.pop() if len(found) == 1 and None not in found else None
        by_page_pattern: dict[str, set] = defaultdict(set)
        for row in empty_rows:
            if pattern_of(row):
                by_page_pattern[row["source"]].add(pattern_of(row))
        shared_patterns = shared_elements.split(by_page_pattern, page_urls)
        patterned = {pattern: [row for row in empty_rows if pattern_of(row) == pattern] for pattern in sorted(shared_patterns)}
        empty_rows = [row for row in empty_rows if pattern_of(row) not in shared_patterns]
        urls = sorted({row["source"] for row in empty_rows})
        per_page = Finding(
            "STR-14", f"{sum(r['links'] for r in empty_rows)} link(s) on {len(urls)} page(s) have no text at all", Severity.S4,
            Confidence.VERIFIED, Rationale.SELF_EVIDENT.value, engines + ["screen readers"], scope_for(urls),
            {"links": empty_rows[:80], "count": len(empty_rows), "occurrences": sum(r["links"] for r in empty_rows), "count_unit": "source-target groups", "title_count_unit": "DOM occurrences",
             # DECISIONS 360: each page's step names its nameless links (address, place, block)
             "page_fixes": __import__("maya_audit.link_fixes", fromlist=["no_text_fixes"]).no_text_fixes(empty_rows)[:500],
             "rule": "no text, no image alt, no aria-label and no title on any link the page has to that target"},
            "every link has a name",
            "Give the link text, give the image inside it an alt text, or add an aria-label.",
            importance_tier=_tier(urls, key_urls),
            notes=["Read from the HTML the server sent: an icon drawn by a stylesheet or a script still leaves the link "
                   "without a name for an engine."])
        if empty_rows:
            findings.append(per_page)
        # Nameless links in one block the markup names ("div.post-related"), on the same pages, are one finding that
        # counts them (DECISIONS 198); a link in the header or footer, or in no named block, keeps its own.
        in_block: dict[tuple, list[tuple[str, list[dict]]]] = defaultdict(list)
        for key in sorted(shared):
            rows = [row for row in everywhere if key in keys_of[id(row)]]
            if not rows:
                continue
            on = sorted({row["source"] for row in rows})
            where = shared_elements.region(row.get("where") for row in rows)
            named = None if where in shared_elements.CHROME_REGIONS else shared_elements.block(row.get("block") for row in rows)
            href, section = shared_elements.shown_address(key, result.origin), shared.section(key, on)
            if named:
                # Keyed by the block alone (B24): one "related posts" block whose links differ by page is one finding.
                in_block[(named, section)].append((href, rows))
                continue
            findings.append(shared_elements.finding(
                per_page, "link_no_text", {"type": "link", "href": href, "where": where},
                on, {"links": rows[:80], "count": len(rows), "rule": per_page.evidence["rule"]}, importance_tier=_tier(on, key_urls), section=section, href=href))
        for (named, section), links in in_block.items():
            hrefs = [href for href, _rows in links]
            rows = [row for _href, found in links for row in found]
            on = sorted({row["source"] for row in rows})
            findings.append(shared_elements.finding(
                per_page, "link_no_text", {"type": "links" if len(hrefs) > 1 else "link", "href": hrefs[0], "hrefs": hrefs[:20],
                                           "links": len(hrefs), "block": named, "where": shared_elements.REPEATED},
                list(on), {"links": rows[:80], "count": len(rows), "rule": per_page.evidence["rule"]}, importance_tier=_tier(list(on), key_urls),
                section=section, title=shared_elements.BLOCK_LINKS_TITLE, block=named, links=len(hrefs)))
        for pattern, rows in patterned.items():
            on = sorted({row["source"] for row in rows})
            example = shared_elements.shown_address(sorted(keys_of[id(rows[0])])[0], result.origin)
            findings.append(shared_elements.finding(
                per_page, "link_no_text_pattern", {"type": "links", "pattern": pattern, "example": example,
                                                   "where": shared_elements.region(row.get("where") for row in rows)},
                on, {"links": rows[:80], "count": len(rows), "rule": per_page.evidence["rule"]}, importance_tier=_tier(on, key_urls),
                section=shared_patterns.section(pattern, on), pattern=pattern, href=example))
    observations = [{"metric": "internal links read", "links": links_total, "source_target_pairs": targets_total,
                     "links_with_generic_text_only": generic_links, "links_with_no_text": empty_links}]
    typos = slug_typos(pages)
    if typos:
        observations.append({"metric": SLUG_TYPOS, "pages": len(typos), "examples": typos[:10],
                              "note": "Confirm the spelling; renaming a live address needs a 301 from the old one."})
    summary = (f"{len(findings)} finding(s) among {links_total} internal link(s) on {len(pages)} page(s)." if findings else
               f"No generic-only or empty anchor text among {links_total} internal link(s) on {len(pages)} page(s).")
    return CheckResult("STR-14", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "phrases_checked": len(GENERIC), "languages": ["en", "tr"]}, observations)


# -- STR-15 --------------------------------------------------------------------

def thin_exempt(page) -> str | None:
    """Why a short page is short by nature (a contact, legal, login or cart page), or None.

    A word marks the page when it is a whole word of an address segment ("/odeme", "/iletisim-bilgileri") or of the
    title, never a piece of a longer word (B08: "/research/" is not "search", "/girisimcilik/" is not "giris"). A
    page in an article folder (/blog/, /rehber/) is an article about the subject, not the page itself."""
    from ..page_words import ARTICLE_FOLDERS, fold, segments
    parts = segments(page.url)
    if ARTICLE_FOLDERS & set(parts[:-1]):
        return None
    path = " ".join(" ".join(re.split(r"[-_]", part)) for part in parts)
    name = fold(page.analysis.get("title") or "")
    for word in THIN_CONTENT_EXEMPT:
        plain = fold(word).replace("-", " ")
        pattern = rf"(?<![^\W_]){re.escape(plain)}(?![^\W_])"
        if re.search(pattern, path) or re.search(pattern, name):
            return word
    return None


def str15_thin_content(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str]) -> CheckResult:
    """Indexable content pages with very little text of their own.

    The count is the page's main content: `<main>` when there is one, without header, navigation and footer,
    and without passages most pages of the site share. Pages whose text arrives only after JavaScript runs
    (RND-1) are left out: their raw HTML is short for another reason, already reported."""
    from ..access_data import homepage_url

    title = "Thin content"
    if not pages:
        return CheckResult("STR-15", title, "not_assessed", "No indexable HTML pages.")
    repeated = repeated_blocks(pages)
    home = homepage_url(result)
    rows, thin, left_out = [], [], Counter()
    form_pages = {page.url for page in pages if any(b.get("in_form") for b in page.analysis.get("buttons") or [])}
    for page in pages:
        words = len(main_words(page.analysis, repeated))
        row = {"url": page.url, "main_content_words": words}
        rows.append(row)
        if words >= THIN_CONTENT_WORDS:
            continue
        if page.url in gap:
            left_out["text arrives after JavaScript runs (RND-1)"] += 1
        elif page.url == home:
            left_out["homepage"] += 1
        elif is_pagination(page.url):
            left_out["page 2, 3, ... of a list"] += 1
        elif thin_exempt(page):
            left_out["contact, legal, account or cart page"] += 1
        elif page.url in form_pages and len(form_pages) * 2 <= len(pages):
            # As STR-17 (B08): a page built around a form (a booking, a quote request) is short by nature. A form on
            # most pages (a newsletter or search box in the footer) says nothing about one page, so it exempts none.
            left_out["page with a form"] += 1
        else:
            thin.append(row)
    findings = []
    if thin:
        thin.sort(key=lambda row: (row["main_content_words"], row["url"]))
        urls = [row["url"] for row in thin]
        findings.append(Finding(
            "STR-15", f"{len(thin)} content page(s) have fewer than {THIN_CONTENT_WORDS} words of their own text",
            Severity.INFO, Confidence.ESTIMATED, Rationale.HYPOTHESIS.value,
            ["Google", "Bing", "answer engines that quote page text"], scope_for(urls),
            {"pages": thin[:80], "count": len(thin), "threshold_words": THIN_CONTENT_WORDS,
             "counted": "words of main content, without header, navigation, footer and text most pages share"},
            "a page meant to be found answers its topic in its own text",
            "Add the substance a reader came for, merge the page into a fuller one, or mark it noindex if it is not meant to be found.",
            importance_tier=_tier(urls, key_urls),
            notes=["The word count is Verified. That the page is too short for its purpose is a judgement: a product "
                   "page or a list page can be complete with few words.",
                   "A short page is not left out as a contact or legal page unless its address or title says so."]))
    counts = [row["main_content_words"] for row in rows]
    observations = [{"metric": "main-content words per page", "pages": len(rows), "median": int(median(counts)),
                     "shortest": min(counts), "longest": max(counts),
                     f"below_{THIN_CONTENT_WORDS}_words": sum(1 for n in counts if n < THIN_CONTENT_WORDS)}]
    summary = (f"1 finding: {len(thin)} of {len(pages)} page(s) below {THIN_CONTENT_WORDS} words." if thin else
               f"No content page below {THIN_CONTENT_WORDS} words of its own text among {len(pages)} page(s).")
    return CheckResult("STR-15", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "threshold_words": THIN_CONTENT_WORDS,
                        "short_pages_left_out": dict(left_out),
                        "pages": sorted(rows, key=lambda row: row["url"])[:1000], "pages_total": len(rows)}, observations)


# -- STR-16 --------------------------------------------------------------------

def _description(page) -> str:
    return next((m["content"] for m in page.analysis["meta"] if m["name"] == "description" and m["content"]), "")


def _alternate_targets(page) -> set[str]:
    """Addresses this page names as its own language or regional versions (hreflang)."""
    from ..urls import normalize_url

    return {u for u in (normalize_url(row.get("href") or "", page.url) for row in page.analysis.get("hreflang") or []) if u}


def str16_duplicate_descriptions(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str],
                                 gap: set[str]) -> CheckResult:
    """The same meta description on several pages that are meant to be found separately.

    `pages` are already the indexable ones: a noindex page or one whose canonical points elsewhere is a
    declared variant and is not compared. Also left out, and counted: a page cut at the size limit (its
    head may be incomplete), a page whose content arrives only after JavaScript runs (RND-1: the raw
    description may not be the one a browser ends with), page 2, 3, ... of a list, and pages that name each
    other as language versions. A description a search engine may show for many pages tells a reader
    nothing about which one to open; that it changes how a page is ranked or cited is not established."""
    title = "Meta description distinct between pages"
    if not pages:
        return CheckResult("STR-16", title, "not_assessed", "No indexable HTML pages.")
    left_out, compared, without = Counter(), [], 0
    for page in pages:
        if page.body_truncated:
            left_out["page cut at the size limit"] += 1
        elif page.url in gap:
            left_out["content arrives after JavaScript runs (RND-1)"] += 1
        elif is_pagination(page.url):
            left_out["page 2, 3, ... of a list"] += 1
        elif not _description(page):
            without += 1  # a missing description is STR-10's finding, not a duplicate
        else:
            compared.append(page)
    by_text: dict[str, list] = {}
    for page in compared:
        by_text.setdefault(" ".join(_description(page).casefold().split()), []).append(page)
    groups = []
    for same in by_text.values():
        # Pages that declare each other as language versions count once: the first stays, its versions go.
        kept: list = []
        for page in same:
            if any(page.url in _alternate_targets(other) or other.url in _alternate_targets(page) for other in kept):
                left_out["language version of a page already counted"] += 1
            else:
                kept.append(page)
        if len(kept) > 1:
            groups.append({"description": _description(kept[0])[:300], "count": len(kept), "urls": [p.url for p in kept]})
    groups.sort(key=lambda g: (-g["count"], g["description"]))
    findings = []
    if groups:
        urls = [u for g in groups for u in g["urls"]]
        findings.append(Finding(
            "STR-16", f"{len(groups)} meta description(s) are shared by {len(urls)} different indexable pages",
            Severity.S4, Confidence.VERIFIED, Rationale.HYPOTHESIS.value, ["Google", "Bing", "engines that show a snippet"],
            scope_for(urls),
            {"groups": [{**g, "urls": g["urls"][:40]} for g in groups[:40]], "groups_total": len(groups)},
            "each page meant to be found has a description of its own, or none",
            "Write a description that says what this page offers, or remove the shared one so the engine picks text from the page.",
            importance_tier=_tier(urls, key_urls),
            notes=["That the descriptions are identical is Verified. That it costs visibility is a hypothesis: engines often "
                   "write their own snippet, and no measurement here links a shared description to a lower ranking or fewer citations.",
                   "Pages with noindex or a canonical pointing elsewhere are not counted."]))
    summary = (f"1 finding: {len(groups)} description(s) repeated across {sum(g['count'] for g in groups)} page(s)." if groups
               else f"No meta description is shared between the {len(compared)} page(s) compared.")
    return CheckResult("STR-16", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "pages_compared": len(compared), "pages_without_description": without,
                        "pages_left_out": dict(left_out), "pages_left_out_count": sum(left_out.values())})


# -- STR-17 --------------------------------------------------------------------

# Words in an address or title that mark a page a visitor is meant to end on. Compared the Turkish way (folded).
DEAD_END_EXEMPT = THIN_CONTENT_EXEMPT + ("confirm", "onay", "success", "basarili", "başarılı", "unsubscribe", "logout",
                                         "cikis", "çıkış", "print", "yazdir", "yazdır", "download", "indir")


def _ends_by_design(page) -> bool:
    path, name = turkish_fold(urlsplit(page.url).path), turkish_fold(page.analysis.get("title") or "")
    return any(word in path or re.search(rf"(?<![^\W_]){re.escape(word)}(?![^\W_])", name) for word in DEAD_END_EXEMPT)


def str17_dead_ends(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str]) -> CheckResult:
    """Indexable pages whose HTML has no link to any other page of this site.

    A visitor, or a crawler that follows links, has nowhere to go from such a page. Counted only where the
    evidence is whole. Left out, and counted: a page with a form (the form is the way on), a page whose address
    or title says it is an ending (thank you, confirmation, login, legal, cart), a page cut at the size limit,
    and any page that runs scripts and was not opened in a browser, because its links may be added there.
    Links to other sites and links to the page itself are not ways on within the site."""
    title = "Pages with no link onward"
    if not pages:
        return CheckResult("STR-17", title, "not_assessed", "No indexable HTML pages.")
    if len(pages) == 1:
        return CheckResult("STR-17", title, "not_assessed",
                           "Only one indexable page was read, so there is no other page for it to link to.")
    render = getattr(result, "render", None)
    rendered = set((getattr(render, "pages", None) or {}).keys())
    dead, left_out = [], Counter()
    for page in pages:
        onward = {edge["target"].split("#")[0] for edge in page.outlinks} - {page.url}
        if onward:
            continue
        analysis = page.analysis
        if page.body_truncated:
            left_out["page cut at the size limit"] += 1
        elif any(button.get("in_form") for button in analysis.get("buttons") or []):
            left_out["page with a form"] += 1
        elif _ends_by_design(page):
            left_out["thank-you, confirmation, login, legal or cart page"] += 1
        elif page.url in gap or (page.url not in rendered and (analysis.get("external_scripts") or analysis.get("inline_script_chars"))):
            left_out["runs scripts and was not opened in a browser, so its links may be added there"] += 1
        else:
            dead.append({"url": page.url, "links_to_other_sites": len(page.external_links),
                         "opened_in_browser": page.url in rendered})
    findings = []
    if dead:
        urls = [row["url"] for row in dead]
        findings.append(Finding(
            "STR-17", f"{len(dead)} page(s) have no link to any other page of this site", Severity.INFO,
            Confidence.VERIFIED, Rationale.HYPOTHESIS.value, ["crawlers that follow links", "visitors"], scope_for(urls),
            {"pages": dead[:80], "count": len(dead)},
            "a page meant to be found links on to the rest of the site (a menu, a way back, related pages)",
            "If the page is part of the site, give it the site's navigation or a link back. If it is meant to stand alone, nothing needs doing.",
            importance_tier=_tier(urls, key_urls),
            notes=["That the HTML holds no link to another page of this site is Verified. That this is a problem is a "
                   "judgement: a landing page or a print view can be built to stand alone.",
                   "Whether other pages link to these is IDX-7's question, not this one's."]))
    summary = (f"1 finding: {len(dead)} of {len(pages)} page(s) link nowhere else on the site." if dead else
               f"Every page that could be judged links on to another page of the site ({len(pages)} read).")
    return CheckResult("STR-17", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "pages_left_out": dict(left_out),
                        "pages_left_out_count": sum(left_out.values())})
