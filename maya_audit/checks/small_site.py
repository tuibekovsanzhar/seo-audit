"""STR-18 to STR-23: six notes that matter most on small, content-light sites.

Added after an audit of a small corporate site (2026-10-07) whose problems were of a kind no check named: a
homepage title without the company's name, menu and footer entries that lead nowhere, the whole message in a
video, no About or Contact page, a newsroom that is a list of links to other sites, and job pages no engine can
read as jobs. None of these is shown to cost visibility, so each is Info or S4 with a "hypothesis" rationale and
says what was measured and what is a judgement. All of them read the pages already fetched; none sends a request.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from .. import shared_elements
from ..access_data import homepage_url
from ..analysis import control_by_text
from ..config import CrawlConfig
from ..findings import CheckResult, Finding, Rationale, Severity, scope_for
from ..main_content import main_words, repeated_blocks
from ..models import Confidence, CrawlResult, StopReason
from ..page_words import ADDRESS_ONLY, BASIC_PAGE_STEMS, BASIC_PAGES, fold, says, segments
from ..urls import registrable_domain
from .access import _status, _tier

# A page with a video or animation and fewer words of its own than this is carrying its message somewhere a
# crawler cannot read. Round number, not calibrated.
MEDIA_ONLY_WORDS = 80
# A news page with fewer words than this, linking mostly to other sites, is a link list.
LINK_LIST_WORDS = 150
ENGINES = ["Google", "Bing", "answer engines that read page text"]

LINKED_NOT_READ = "{kind}: linked from the footer ({path}), not among the pages read."
NEWS_WORDS = ("news", "newsroom", "press", "media", "in-the-news", "haberler", "haber", "basin", "basinda-biz", "medya",
              "basin-odasi", "duyurular")
JOB_WORDS = ("careers", "career", "jobs", "job", "vacancies", "positions", "openings", "join-us", "kariyer", "is-ilanlari",
             "acik-pozisyonlar", "ilanlar")


# The folding and STR-21's word lists live in maya_audit/page_words.py (DECISIONS 229); the old names stay here.
_fold, _segments = fold, segments


def _squash(text: str | None) -> str:
    return re.sub(r"[^\w]+", "", _fold(text))


def _note(check_id: str, title: str, severity: Severity, confidence: Confidence, urls: list[str], evidence: dict, expected: str,
          fix: str, key_urls: set[str], notes: list[str], sitewide: bool = False) -> Finding:
    return Finding(check_id, title, severity, confidence, Rationale.HYPOTHESIS.value, ENGINES, scope_for(urls, sitewide), evidence,
                   expected, fix, importance_tier=_tier(urls, key_urls), notes=notes)


# -- STR-18 --------------------------------------------------------------------

# An article before a brand name, in English, French, German, Spanish and Italian ("The", "Le", "L'", "Der", "El").
LEADING_ARTICLE = re.compile(r"^(?:the|le|la|les|l['’]|der|die|das|el|los|las|il|lo|gli)\s*(?<=\s|['’])", re.I)

def brand_candidates(result: CrawlResult, home) -> list[str]:
    """Names the homepage title could carry: what the site calls itself in its own markup, and its domain name."""
    from .structure import site_name

    host = urlsplit(result.origin).hostname or ""
    label = registrable_domain(host).split(".")[0]
    return [name for name in dict.fromkeys([site_name(result), label]) if name and len(_squash(name)) >= 2]


HOMEPAGE_READS_DISAGREE = "Two reads of the homepage disagreed: one answered {a}, another {b}. The title was not judged."


def homepage_reads(result: CrawlResult) -> list[int]:
    """The status of every request this audit made for the homepage's own address, in the order they were made: the
    crawl, an IDX-1 refetch, the performance rounds (`perf_data.attempts_by_url`) and the IDX-3 re-checks."""
    from ..perf_data import attempts_by_url

    home = homepage_url(result)
    try:
        seen = [(a.get("requested_at") or "", a.get("status")) for a in attempts_by_url(result).get(home, [])]
    except (AttributeError, KeyError, TypeError):  # a result with no request history (pages rebuilt from a saved copy)
        seen = []
    index = getattr(result, "index", None)
    for entry in (getattr(index, "redirect_rechecks", None) or {}).values():
        for attempt in entry.get("attempts") or []:
            seen += [(hop.get("requested_at") or "", hop.get("status")) for hop in attempt.get("hops") or [] if hop.get("url") == home]
    return [status for _, status in sorted(seen, key=lambda pair: pair[0]) if isinstance(status, int)]


def str18_homepage_title_brand(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    title = "Homepage title names the brand"
    home = next((p for p in pages if p.url == homepage_url(result)), None)
    if home is None or not home.analysis.get("title"):
        # Which case it is (DECISIONS 199): the reads of the homepage gave different answers (the crawl saw a redirect,
        # a later request the page), or the homepage has no title. The first is said as what it is, not as "not read".
        reads = homepage_reads(result) if home is None else []
        if len(set(reads)) > 1:
            other = next(status for status in reads if status != reads[0])
            return CheckResult("STR-18", title, "not_assessed", HOMEPAGE_READS_DISAGREE.format(a=reads[0], b=other),
                               evidence={"homepage": homepage_url(result), "statuses_seen": reads})
        return CheckResult("STR-18", title, "not_assessed", "The homepage was not read as an indexable page with a title "
                           "(a missing title is STR-1's finding).")
    names = brand_candidates(result, home)
    shown = home.analysis["title"]
    # "demo-kafe" is named by "Kafe Demo": every word of a name, in any order, counts. A leading article is not part
    # of the name (item 11): "Le Courrier du Rhône" is named by "Courrier du Rhône | Actualités".
    def named(name: str) -> bool:
        name = LEADING_ARTICLE.sub("", name.strip()) or name
        words = [w for w in re.split(r"[^\w]+", _fold(name)) if len(w) >= 2]
        return _squash(name) in _squash(shown) or (len(words) > 1 and all(w in _squash(shown) for w in words))

    if any(named(name) for name in names):
        return CheckResult("STR-18", title, "pass", f"The homepage title names the brand ({shown!r}).",
                           evidence={"title": shown, "names_looked_for": names})
    finding = _note(
        "STR-18", f"The homepage title does not name the brand ({shown[:80]!r})", Severity.INFO, Confidence.INFERRED, [home.url],
        {"title": shown, "names_looked_for": names,
         "names_come_from": "og:site_name or Organization markup on the homepage, and the domain name"},
        "the homepage title says whose site this is", f"Put the brand name in the homepage <title>, for example “{names[0]} | "
        "what you do”." if names else "Put the brand name in the homepage <title>.", key_urls,
        ["That none of these names is in the title is Verified. That one of them is the brand's name is Inferred from the "
         "site's own markup and its domain; a brand that trades under another name is not caught by this."])
    return CheckResult("STR-18", title, _status([finding]), "1 finding: the homepage title does not contain "
                       + " or ".join(repr(n) for n in names) + ".", [finding], {"title": shown, "names_looked_for": names})


# -- STR-19 --------------------------------------------------------------------

def str19_links_to_nowhere(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    """Two different things that look alike in the HTML. A link to content with no address is something a crawler
    cannot follow: an SEO matter, Low. A control that opens a sign-in window, a menu or a search box and is coded as
    <a href="#"> works for visitors and has nothing a crawler should reach: an accessibility note, never a problem."""
    title = "Links without an address a crawler can follow"
    if not pages:
        return CheckResult("STR-19", title, "not_assessed", "No indexable HTML pages.")
    groups: dict[str, dict[tuple[str, str], list[str]]] = {"no_target": defaultdict(list), "footer": defaultdict(list), "control": defaultdict(list)}
    reasons: dict[tuple[str, str], str] = {}
    in_footer: dict[tuple[str, str], list[str | None]] = defaultdict(list)
    for page in pages:
        for link in page.analysis.get("dead_links") or []:
            named = None if link["why"].startswith("no address") else control_by_text(link["text"])
            kind = "footer" if link["why"].startswith("no address") else "control" if named else "no_target"
            groups[kind][(link["text"], link["why"], link.get("component") or "")].append(page.url)
            in_footer[(link["text"], link["why"], link.get("component") or "")].append("footer" if link.get("in_footer") else link.get("where"))
            if named:
                reasons[(link["text"], link["why"], link.get("component") or "")] = named
        for link in page.analysis.get("link_controls") or []:  # marked as a control by the page's own markup
            groups["control"][(link["text"], link["why"], link.get("component") or "")].append(page.url)
            reasons[(link["text"], link["why"], link.get("component") or "")] = link["control"]

    def listed(rows):
        return [{"text": text or "(no text)", "why": why, "pages": len(set(where)), "example": sorted(set(where))[0], "occurrences": len(where), "component": component,
                 **({"control_because": reasons[(text, why, component)]} if (text, why, component) in reasons else {})}
                for (text, why, component), where in sorted(rows.items(), key=lambda item: -len(set(item[1])))]

    findings = []
    for kind, severity, expected, fix in (
            ("no_target", Severity.S4, "every link to content has an address a crawler can follow",
             "Give each link the address of the page it should open. If it only triggers a script, make it a <button>."),
            ("footer", Severity.INFO, "an entry listed among the footer's links leads to its page",
             "Link each footer entry to its page, or remove the entries whose pages do not exist yet.")):
        rows = groups[kind]
        if not rows:
            continue
        # The same link without an address on most pages (a footer's "cookie settings") is one element: reported once
        # for the whole site, by its text, and taken out of each page's row (maya_audit.shared_elements). Only a
        # problem is split: a note makes no page row to begin with.
        everywhere: set = set()
        split = shared_elements.Shared()
        if severity != Severity.INFO:
            by_page: dict[str, set] = defaultdict(set)
            for key, where in rows.items():
                for url in where:
                    by_page[url].add(key)
            split = shared_elements.split(by_page, [page.url for page in pages])
            everywhere = {key for key in split if key[0].strip()}
        shared_rows = {key: where for key, where in rows.items() if key in everywhere}
        rows = {key: where for key, where in rows.items() if key not in everywhere}
        urls = sorted({url for where in rows.values() for url in where})
        links = listed(rows)
        # How many of these links each page has, so a page's own row can say its own number (the list above is by link).
        on_page = Counter(url for where in rows.values() for url in where)
        heading = (f"{sum(len(where) for where in rows.values())} link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)"
                   if kind == "no_target" else f"{sum(len(where) for where in rows.values())} link(s) on {len(urls)} page(s) in the footer look like links but have no address")
        per_page = (_note(
            "STR-19", heading, severity, Confidence.VERIFIED, urls,
            {"links": links[:60], "links_count": len(links), "occurrences": sum(on_page.values()), "count_unit": "distinct element groups", "title_count_unit": "DOM occurrences", "pages_count": len(urls),
             "by_page": [{"url": url, "links": on_page[url]} for url in urls]}, expected, fix, key_urls,
            ["That these <a> elements have no address to follow (href=\"#\", a javascript: address, or none) is Verified from the "
             "HTML. What they do for a visitor when the page's script runs was not tested.",
             "A crawler follows addresses, not clicks: whatever such a link opens for a visitor, a crawler does not reach it. "
             "Controls (sign-in, menu, search, close, cart, language, and anything marked as a button or as opening a dialog) "
             "are not counted here."]))
        if rows:
            findings.append(per_page)
        # Links that sit on exactly the same pages are one menu or one footer block: one finding that lists them.
        together: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
        for key, where in shared_rows.items():
            together[tuple(sorted(set(where)))].append(key)
        for on, keys in sorted(together.items(), key=lambda item: (-len(item[0]), item[1])):
            on = list(on)
            occurrences = Counter(url for key in keys for url in shared_rows[key])
            group_evidence = {'links': listed({key: shared_rows[key] for key in keys}),
                              'by_page': [{'url': url, 'links': occurrences[url]} for url in on],
                              'occurrences': sum(occurrences.values()), 'links_count': len(keys),
                              'title_count_unit': 'distinct element groups per template',
                              'count_unit': 'distinct element groups'}
            if len(keys) == 1:
                text, why, component = keys[0]
                findings.append(shared_elements.finding(
                    per_page, "link_no_address", {"type": "link", "text": text, "why": why,
                                                  "component": component, "where": shared_elements.region(in_footer[(text, why, component)])},
                    on, group_evidence, importance_tier=_tier(on, key_urls), section=split.section(keys[0], on), text=text))
                continue
            texts = [text for text, _why, _component in keys]
            findings.append(shared_elements.finding(
                per_page, "links_no_address",
                {"type": "links", "texts": texts, "why": sorted({why for _text, why, _component in keys}),
                 "where": shared_elements.region(where for key in keys for where in in_footer[key])},
                on, group_evidence, importance_tier=_tier(on, key_urls), section=split.section(keys[0], on), links=len(keys),
                texts=shared_elements.named(texts)))
    controls = listed(groups["control"])
    if controls:
        urls = sorted({url for where in groups["control"].values() for url in where})
        findings.append(_note(
            "STR-19", f"{len(controls)} control group(s) use anchors; interaction and accessibility require review", Severity.INFO,
            Confidence.VERIFIED, urls, {"controls": controls[:60], "controls_count": len(controls), "pages_count": len(urls),
                                         "kind": "accessibility note", "seo_problem": False},
            "controls have appropriate roles, accessible names and keyboard behavior; interaction is assessed separately",
            "Optional, for accessibility: inspect the control's role, accessible name and keyboard behavior. Prefer native controls where appropriate; do not infer an SEO discovery failure from the control alone.", key_urls,
            ["An accessibility note, not an SEO finding: these appear to be controls. Interaction was not tested; role and accessible-name behavior require review.",
             "Recognised by the page's own markup (role=\"button\", aria-haspopup, aria-controls, aria-expanded, data-toggle and "
             "similar), by a short label in English or Turkish (log in, sign up, forgot password, menu, search, close, cart, "
             "language; giriş yap, üye ol, şifremi unuttum, menü, ara, kapat, sepet), or by having no text (an icon). Word matching: "
             "a link to content with one of these exact labels would be listed here too.",
             "Also recognised as controls: a cookie-settings opener and a show/hide toggle, by their label (cookie settings, "
             "manage cookies, show, hide; çerez ayarları, göster, gizle) or by a class name that says so (a class containing "
             "“toggle”, one that starts with js-open-, js-close-, js-toggle-, js-show- or js-hide-, or ot-sdk-show-settings)."]))
    total = sum(len(listed(groups[kind])) for kind in ("no_target", "footer"))
    problems = len(listed(groups["no_target"]))
    summary = (f"{len(findings)} finding(s): {problems} distinct element group(s) to content without an address a crawler can follow"
               + (f", {len(listed(groups['footer']))} footer entry(ies) without an address" if groups["footer"] else "")
               + (f"; {len(controls)} control(s) coded as links (an accessibility note, not an SEO problem)." if controls else ".")
               if findings else f"Every link on the {len(pages)} page(s) read has an address to follow.")
    return CheckResult("STR-19", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "links_without_address": total, "count_unit": "distinct element groups",
                        "dom_occurrences_without_address": sum(len(where) for kind in ('no_target','footer') for where in groups[kind].values()),
                        "controls_coded_as_links": len(controls)})


# -- STR-20 --------------------------------------------------------------------

def str20_message_in_media(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str]) -> CheckResult:
    title = "Message carried by video or animation"
    if not pages:
        return CheckResult("STR-20", title, "not_assessed", "No indexable HTML pages.")
    repeated = repeated_blocks(pages)
    rows, left_out = [], 0
    for page in pages:
        analysis = page.analysis
        content = (lambda item: item.get("in_main", True)) if analysis.get("has_main_region") else (lambda item: True)
        players = [m["tag"] for m in analysis.get("media") or [] if content(m)]
        embeds = [f["src"] for f in analysis.get("iframes") or [] if content(f) and re.search(
            r"youtube|youtu\.be|vimeo|wistia|loom\.com|player\.", f.get("src") or "", re.I)]
        if not players and not embeds:
            continue
        if page.url in gap:
            left_out += 1  # its text arrives after JavaScript runs (RND-1): the word count here would mislead
            continue
        words = len(main_words(analysis, repeated))
        if words < MEDIA_ONLY_WORDS:
            rows.append({"url": page.url, "words_of_its_own": words, "players": sorted(set(players)), "video_embeds": embeds[:3]})
    findings = []
    if rows:
        urls = [row["url"] for row in rows]
        findings.append(_note(
            "STR-20", f"{len(rows)} page(s) carry their message in video or animation, with fewer than {MEDIA_ONLY_WORDS} words of text",
            Severity.S4, Confidence.ESTIMATED, urls, {"pages": rows[:60], "threshold_words": MEDIA_ONLY_WORDS},
            "what a video or animation says is also said in text on the page",
            "Write the video's key points on the page: who you are, what you offer, and for whom. A transcript or a short summary is enough.",
            key_urls,
            ["The word count and the presence of a player are Verified. That the video carries the page's message is a "
             "judgement: what it shows was not looked at.", "Crawlers read text. They do not watch video or run animation."]))
    summary = (f"1 finding: {len(rows)} page(s) with a video or animation and little text." if rows
               else "No page relies on a video or animation in place of text.")
    return CheckResult("STR-20", title, _status(findings), summary, findings,
                       {"pages_checked": len(pages), "threshold_words": MEDIA_ONLY_WORDS, "pages_left_out": {
                           "content arrives after JavaScript runs (RND-1)": left_out} if left_out else {},
                        "pages_left_out_count": left_out})


# -- STR-21 --------------------------------------------------------------------

def _page_names(page) -> str:
    headings = " ".join(h["text"] for h in page.analysis.get("headings") or [] if h["level"] == 1)
    return _fold(f"{page.analysis.get('title') or ''} {headings}")


_says = says


# A stem's suffix (B09, G24): letters only and at most this many ("lerimiz"), the whole rest of the segment.
_STEM_SUFFIX = r"[a-z]{0,8}"


def _stem_match(kind: str, segments: set[str]) -> bool:
    """A path segment that is one of the kind's stems with a Turkish suffix ("urunlerimiz", "menumuz", "sube"; B09).
    The whole segment (G24): "/menu-settings" is not the menu page."""
    return any(re.fullmatch(re.escape(stem) + _STEM_SUFFIX, segment)
               for segment in segments for stem in BASIC_PAGE_STEMS.get(kind, ()))


def shop_pages(pages: list) -> dict[str, str]:
    """Pages that sell something (H14), with why: Product or Offer structured data, or a price of its own beside a buy
    button ("Sepete Ekle", "Add to cart"). A shop has product pages whatever its addresses are called."""
    from .structure import PRODUCT_TYPES, _buy_control, located_prices  # here: checks/structure.py imports this module

    out: dict[str, str] = {}
    for page in pages:
        types = set(page.analysis["structured_data"]["types"]) & (PRODUCT_TYPES | {"Offer", "AggregateOffer"})
        if types:
            out[page.url] = f"{sorted(types)[0]} structured data"
            continue
        control = _buy_control(page)
        price = next((t["text"] for t in located_prices(page.analysis) if t["not_own"] is None), None) if control else None
        if price:
            out[page.url] = f"a price ({price}) beside a buy control ({control[:40]})"
    return out


# Page types that say what a page is in any language (G21): read before the words.
KIND_PAGE_TYPES = {"About": "AboutPage", "Contact": "ContactPage", "FAQ": "FAQPage"}


def basic_pages_found(pages: list) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {kind: [] for kind in BASIC_PAGES}
    for page in pages:
        segments, names = set(_segments(page.url)), _page_names(page)
        types = set((page.analysis.get("structured_data") or {}).get("types") or [])
        for kind, words in BASIC_PAGES.items():
            if (KIND_PAGE_TYPES.get(kind) in types or segments & set(words + ADDRESS_ONLY.get(kind, ()))
                    or _says(words, names) or _stem_match(kind, segments)):
                found[kind].append(page.url)
    if not found["Product or service"]:
        found["Product or service"] = list(shop_pages(pages))
    return found


def footer_links(pages: list, kinds: list[str]) -> dict[str, dict]:
    """For each of `kinds`, the first footer link that names it, by its text or by its address: {kind: {"url", "anchor",
    "linked_from"}}. A footer is where a site lists its About, Contact and FAQ pages, so a link there says the page
    exists even when the crawl did not read it (disallowed by robots.txt, or beyond the page cap)."""
    out: dict[str, dict] = {}
    for page in pages:
        for edge in getattr(page, "outlinks", None) or []:
            if not edge.get("footer") or not edge.get("target"):
                continue
            segments = set(_segments(edge["target"]))
            texts = [_fold(text) for text in edge.get("anchors") or [edge.get("anchor") or ""]]
            for kind in kinds:
                words = BASIC_PAGES[kind] + ADDRESS_ONLY.get(kind, ())
                if kind not in out and (segments & set(words) or any(_says(words, text) for text in texts)):
                    out[kind] = {"url": edge["target"], "anchor": edge.get("anchor") or "", "linked_from": page.url}
    return out


def str21_basic_pages(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    title = "Basic pages present"
    if not pages:
        return CheckResult("STR-21", title, "not_assessed", "No indexable HTML pages.")
    found = basic_pages_found(pages)
    # Before a kind is called missing, the footer is read (DECISIONS 197): a footer link that names the kind, by its
    # text or its address, to a page that was read is that page; to one that was not read it is "linked from the
    # footer, not among the pages read", never "missing".
    read = {page.url for page in pages}
    linked = {}
    for kind, link in footer_links(pages, [kind for kind, urls in found.items() if not urls]).items():
        if link["url"] in read:
            found[kind].append(link["url"])
        else:
            linked[kind] = link
    missing = [kind for kind, urls in found.items() if not urls and kind not in linked]
    said = [LINKED_NOT_READ.format(kind=kind, path=shared_elements.shown_address(link["url"], result.origin)) for kind, link in linked.items()]
    evidence = {"pages_read": len(pages), "found": {kind: urls[:5] for kind, urls in found.items()},
                "looked_for_in": "the address, the title and the main heading of each page read, and the text and address of footer links; "
                                 "for a product page also Product or Offer structured data, or a price beside a buy button",
                **({"linked_from_footer_not_read": linked} if linked else {})}
    if not missing and not linked:
        return CheckResult("STR-21", title, "pass", "An About, a product or service, a Contact and an FAQ page were all found among "
                           f"the {len(pages)} page(s) read.", evidence=evidence)
    if not missing:
        return CheckResult("STR-21", title, "pass", f"No basic page is missing among the {len(pages)} page(s) read. " + " ".join(said),
                           evidence=evidence)
    complete = result.stop_reason == StopReason.EXHAUSTED and not result.not_fetched_urls
    if not complete:
        # Not found among the pages read is not "does not exist" when pages were left unread.
        return CheckResult("STR-21", title, "not_assessed", f"Not found among the {len(pages)} page(s) read: {', '.join(missing)}. "
                           "The crawl did not read every page it found, so they may exist." + "".join(f" {line}" for line in said),
                           evidence=evidence)
    finding = _note(
        "STR-21", f"No {' / '.join(missing)} page was found among the {len(pages)} page(s) of the site", Severity.INFO, Confidence.INFERRED,
        [homepage_url(result)], {**evidence, "not_found": missing},
        "a business site says who is behind it, what it offers, how to reach it, and answers common questions",
        "Add the missing page(s), or make sure the existing one says what it is in its address, title or main heading.", key_urls,
        ["Inferred from page types (AboutPage, ContactPage, FAQPage) and from addresses, titles and main headings in "
         "English and Turkish, with short German, French, Spanish, Italian and Arabic lists. A page that covers the topic under another "
         "name, or a one-page site with these as sections, is not recognised.",
         "Every page the crawl found was read, so a page that exists but is linked from nowhere would also be missed."], sitewide=True)
    return CheckResult("STR-21", title, _status([finding]), f"1 finding: not found: {', '.join(missing)}." + "".join(f" {line}" for line in said),
                       [finding], evidence)


# -- STR-22 --------------------------------------------------------------------

def str22_news_link_lists(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    title = "News page made of links to other sites"
    news = [p for p in pages if set(_segments(p.url)) & set(NEWS_WORDS)]
    if not news:
        return CheckResult("STR-22", title, "not_applicable", "No news or press page among the pages read.", evidence={"news_pages": 0})
    repeated = repeated_blocks(pages)
    rows = []
    for page in news:
        own = [edge for edge in page.outlinks if not edge.get("nav")]
        outside = len(page.external_links)
        words = len(main_words(page.analysis, repeated))
        if outside >= 3 and outside >= 2 * len(own) and words < LINK_LIST_WORDS:
            rows.append({"url": page.url, "links_to_other_sites": outside, "links_to_own_pages_outside_the_menu": len(own),
                         "words_of_its_own": words, "examples": [link.get("target") for link in page.external_links[:3]]})
    findings = []
    if rows:
        urls = [row["url"] for row in rows]
        findings.append(_note(
            "STR-22", f"{len(rows)} news or press page(s) consist of links to other sites, with little text of their own",
            Severity.INFO, Confidence.ESTIMATED, urls, {"pages": rows[:40], "threshold_words": LINK_LIST_WORDS},
            "news about the company can be read on the company's own site",
            "For each item, add a short summary on your own page (what happened, when, and the source), and keep the link to the full story.",
            key_urls,
            ["The counts are Verified. That the page is only a link list is a judgement from them.",
             "An engine looking for what was said about the company finds the other sites' pages, not this one."]))
    summary = f"1 finding: {len(rows)} of {len(news)} news or press page(s)." if rows else \
        f"The {len(news)} news or press page(s) read have text of their own."
    return CheckResult("STR-22", title, _status(findings), summary, findings, {"news_pages": len(news)})


# -- STR-23 --------------------------------------------------------------------

# Section headings that sit under a job's own heading when openings are described on one page.
OPENING_SECTIONS = ("responsibilities", "qualifications", "requirements", "what you'll do", "what you will do", "about the role",
                    "who you are", "what we're looking for", "your role", "sorumluluklar", "aranan nitelikler", "nitelikler",
                    "gereksinimler", "is tanimi", "genel nitelikler")


def inline_openings(headings: list[dict]) -> list[str]:
    """The job titles on a page that describes openings inline: each heading that is followed, one level down, by a
    section such as Responsibilities or Qualifications."""
    names: list[str] = []
    current: dict | None = None
    for heading in headings:
        text = _fold(str(heading.get("text") or "")).replace("-", " ").strip(" .:")
        level = heading.get("level") or 0
        if any(text == word or text.startswith(word + " ") for word in OPENING_SECTIONS):
            if current is not None and level > current["level"] and current["text"] not in names:
                names.append(current["text"])
        else:
            current = {"level": level, "text": str(heading.get("text") or "").strip()}
    return names

def str23_job_postings(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str]) -> CheckResult:
    title = "Job pages with JobPosting data"
    postings = []
    for page in pages:
        segments = _segments(page.url)
        marks = [i for i, s in enumerate(segments) if s in JOB_WORDS]
        if marks and len(segments) > marks[0] + 1:  # a page under /careers/ or /jobs/: one opening, not the list
            postings.append(page)
    # A careers page that describes several openings on the page itself, instead of one page each.
    lists = []
    for page in pages:
        segments = _segments(page.url)
        if page in postings or not (set(segments) & set(JOB_WORDS)):
            continue
        openings = inline_openings(page.analysis.get("headings") or [])
        if len(openings) >= 2:
            lists.append((page, openings))
    if not postings and not lists:
        return CheckResult("STR-23", title, "not_applicable", "No job page, and no careers page listing openings, among the pages read.",
                           evidence={"job_pages": 0, "careers_pages_listing_openings": 0})
    without = [p for p in postings if "JobPosting" not in set(p.analysis["structured_data"]["types"])]
    lists_without = [(p, names) for p, names in lists if "JobPosting" not in set(p.analysis["structured_data"]["types"])]
    findings = []
    if lists_without:
        urls = [p.url for p, _names in lists_without]
        total = sum(len(names) for _p, names in lists_without)
        findings.append(_note(
            "STR-23", f"{len(lists_without)} careers page(s) list {total} job opening(s) on the page itself, with no JobPosting structured data",
            Severity.INFO, Confidence.INFERRED, urls,
            {"pages": [{"url": p.url, "openings": names[:20], "structured_data_types": p.analysis["structured_data"]["types"]}
                       for p, names in lists_without[:40]]},
            "each open position is described with JobPosting structured data (title, description, date posted, hiring organisation, location)",
            "Add one JobPosting block per opening (title, description, datePosted, hiringOrganization, jobLocation or remote), or give each "
            "opening its own page with that markup. Google requires it for its job listings.", key_urls,
            ["That the page has no JobPosting markup is Verified. That it lists openings is Inferred from its headings: a job title "
             "followed by sections such as Responsibilities or Qualifications, more than once."]))
    if without:
        urls = [p.url for p in without]
        findings.append(_note(
            "STR-23", f"{len(without)} job page(s) have no JobPosting structured data", Severity.INFO, Confidence.INFERRED, urls,
            {"job_pages": len(postings), "without_jobposting": len(without),
             "pages": [{"url": p.url, "structured_data_types": p.analysis["structured_data"]["types"]} for p in without[:40]]},
            "each open position is described with JobPosting structured data (title, description, date posted, hiring organisation, location)",
            "Add JobPosting markup to each open position. Google requires it for its job listings.", key_urls,
            ["That these pages have no JobPosting markup is Verified. That each is a single job opening is Inferred from its "
             "address (a page under a careers or jobs section)."]))
    parts = ([f"{len(without)} of {len(postings)} job page(s)"] if without else []) + (
        [f"{len(lists_without)} careers page(s) listing openings"] if lists_without else [])
    summary = f"{len(findings)} finding(s): {' and '.join(parts)}." if findings else \
        f"All {len(postings) + len(lists)} job page(s) and careers list(s) read carry JobPosting structured data."
    return CheckResult("STR-23", title, _status(findings), summary, findings,
                       {"job_pages": len(postings), "careers_pages_listing_openings": len(lists)})


def run_small_site_checks(result: CrawlResult, cfg: CrawlConfig, pages: list, key_urls: set[str], gap: set[str]) -> list[CheckResult]:
    return [str18_homepage_title_brand(result, cfg, pages, key_urls), str19_links_to_nowhere(result, cfg, pages, key_urls),
            str20_message_in_media(result, cfg, pages, key_urls, gap), str21_basic_pages(result, cfg, pages, key_urls),
            str22_news_link_lists(result, cfg, pages, key_urls), str23_job_postings(result, cfg, pages, key_urls)]
