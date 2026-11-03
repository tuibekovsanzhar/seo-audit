"""Which parts of a page are in another language than the page declares (STR-12, STR-9; DECISIONS 301 (2)).

A language-mismatch finding says a page is "mostly in Turkish" or "declares the wrong <html lang>"; the fix depends on
where the other language is. This module looks at each region of the page Maya read and says which ones hold text in
the other language:

    menu        links in the site navigation (`outlinks[].nav`, not the footer)
    breadcrumbs the breadcrumb trail (`breadcrumbs[].text`, up to the page's own name)
    titles      the page's <h1>, and the names of the items it links to from its content (products, articles)
    buttons     buttons and their labels (`buttons`, `input_buttons`)
    banners     text of images in the content (`images[].alt`, not the site chrome)
    footer      the footer's text
    body        the main text (the finding's own measured share, when it has one)

A string is "in the other language" when it has a word or letter only that language uses ("Beden", "Mağaza
Stokları": Turkish letters; "the", "and": English stopwords), or when it is exactly the same on the page's own version
in the other language (hreflang) and carries no sign of the declared language: a name that was not translated
("Kaban"). The site's brand name and strings without letters are never counted. Estimated: word lists and a comparison
of two copies, never a translation service.

Advice is built from the regions found, with the platform's own translation tool where the report names the
platform (Shopify: Translate & Adapt; WordPress: WPML or Polylang). Its words are in `rule_actions.json`
(`region_steps`, `platform_steps_language`), Turkish and English.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from .language import NOT_FOREIGN_IN, STOPWORD_SETS, _TURKISH_LETTERS, _WORD, lower

REGIONS = ("menu", "breadcrumbs", "titles", "buttons", "banners", "footer", "body")
ITEM_FOLDERS = frozenset({"products", "product", "urun", "urunler", "p", "blogs", "blog", "makale", "haber", "news"})
METHOD = ("each region's strings are called by letters or common words only one language uses, or by being identical on "
          "the page's other-language version (hreflang) with no sign of the declared language (Estimated)")
# A language switcher names each language in itself ("Türkçe" on an English page is right): never counted.
LANGUAGE_NAMES = frozenset({"türkçe", "turkce", "english", "deutsch", "français", "francais", "español", "espanol",
                            "italiano", "русский", "العربية", "nederlands", "português", "portugues"})
IDENTITY_REGIONS = frozenset({"menu", "breadcrumbs", "titles", "buttons"})
MIN_SHARE = 0.25   # a region is "in the other language" when a quarter of its strings are, or
MIN_ITEMS = 2      # at least this many of them are


def hint(text: str, declared: str | None) -> str | None:
    """The language a short string shows signs of, or None: Turkish letters, else one stopword of exactly one
    language (an ordinary word of the declared language is not evidence for another)."""
    words = [lower(w) for w in _WORD.findall(text or "")]
    if not words:
        return None
    if _TURKISH_LETTERS.search(text or ""):
        return "tr"
    own = NOT_FOREIGN_IN.get(declared or "", frozenset())
    hits = {lang for lang, stops in STOPWORD_SETS.items() for w in words if w in stops and not (lang != declared and w in own)}
    return next(iter(hits)) if len(hits) == 1 else None


def _breadcrumbs(analysis: dict) -> list[str]:
    out = []
    for crumb in analysis.get("breadcrumbs") or []:
        parts = [p.strip() for p in str(crumb.get("text") or "").split(" / ") if p.strip()]
        if parts:
            last = re.split(r"\s\d", parts[-1], maxsplit=1)[0].strip()  # the trail runs on into the page ("Coat 173 products")
            out += parts[:-1] + ([last] if last else [])
    return [p for p in out if len(p) <= 60]


def footer_phrases(text: str) -> list[str]:
    """The footer's link texts, as well as a run of text allows: a capitalised word starts a phrase ("Site Haritası",
    "Return and Refund Policy"); lower-case words and short joining words stay in it."""
    phrases, current = [], []
    for word in (text or "").split():
        if word[:1].isupper() and current and not (len(current[-1]) <= 3 and current[-1].islower()):
            phrases.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        phrases.append(" ".join(current))
    return phrases[:120]


def _is_item(url: str) -> bool:
    segments = [s for s in urlsplit(url or "").path.lower().split("/") if s]
    return len(segments) >= 2 and segments[-2] in ITEM_FOLDERS


def region_strings(page: dict) -> dict[str, list[str]]:
    """The strings of each region of one page record (a saved report's `crawl.pages[]` or `to_jsonable(PageFetch)`)."""
    a = page.get("analysis") or {}
    out: dict[str, list[str]] = defaultdict(list)
    for link in page.get("outlinks") or []:
        anchor = (link.get("anchor") or "").strip()
        if not anchor:
            continue
        if link.get("nav") and not link.get("footer"):
            out["menu"].append(anchor)
        elif not link.get("nav") and not link.get("footer") and _is_item(link.get("target") or ""):
            out["titles"].append(anchor)
    out["breadcrumbs"] = _breadcrumbs(a)
    out["titles"] += [h.get("text") for h in a.get("h1_elements") or [] if h.get("text")]
    out["buttons"] = [b.get("text") for b in (a.get("buttons") or []) + (a.get("input_buttons") or [])
                      if isinstance(b, dict) and b.get("text") and not b.get("in_chrome")]
    out["banners"] = [i.get("alt") for i in a.get("images") or []
                      if isinstance(i, dict) and i.get("alt") and not i.get("in_chrome") and not re.search(r"\.\w{3,4}$", i["alt"])]
    out["footer"] = footer_phrases(a.get("footer_text") or "")
    return {k: [s.strip() for s in dict.fromkeys(v) if s and s.strip()] for k, v in out.items()}


def counterpart(page: dict, other: str, by_url: dict[str, dict]) -> dict | None:
    """The page's own version in language `other`, when its hreflang names one that was read."""
    for alt in (page.get("analysis") or {}).get("hreflang") or []:
        code = (alt.get("hreflang") or "").split("-")[0].lower()
        if code == other and alt.get("href") in by_url:
            return by_url[alt["href"]]
    return None


def page_regions(page: dict, declared: str, other: str, by_url: dict[str, dict], brand: str | None = None,
                 body_share: float | None = None) -> dict[str, dict]:
    """{region: {"foreign": n, "total": n, "samples": [...]}} for one page."""
    mine = region_strings(page)
    twin = counterpart(page, other, by_url)
    theirs = region_strings(twin) if twin else {}
    brand_key = (brand or "").strip().lower()
    out = {}
    for region, strings in mine.items():
        strings = [s for s in strings if _WORD.search(s) and s.strip().lower() != brand_key
                   and not (set(lower(w) for w in _WORD.findall(s)) <= LANGUAGE_NAMES | {"en", "tr", "de", "fr"})]
        if not strings:
            continue
        same = set(theirs.get(region) or [])
        foreign = []
        for s in strings:
            h = hint(s, declared)
            # Identical on the other-language version: untranslated, for what a translation covers (names in menus,
            # breadcrumbs, item titles, buttons); never for a country list or a footer, and never a code ("TRY₺").
            same_text = (region in IDENTITY_REGIONS and twin is not None and s in same
                         and len(re.sub(r"[^\w]", "", s)) >= 4 and h is None)
            if h == other or same_text:
                foreign.append(s)
        out[region] = {"foreign": len(foreign), "total": len(strings), "samples": foreign[:6]}
    if body_share is not None:
        out["body"] = {"foreign": round(body_share * 100), "total": 100, "samples": [], "share": body_share}
    return out


def regions(report: dict, finding: dict) -> dict | None:
    """The finding's regions over its pages, or None when it is not a language finding or no page was read."""
    rows = [r for r in (finding.get("evidence") or {}).get("pages") or [] if isinstance(r, dict) and r.get("url")]
    if not rows:
        return None
    by_url = {p.get("url"): p for p in (report.get("crawl") or {}).get("pages") or [] if isinstance(p, dict) and p.get("analysis")}
    brand = (report.get("brand") or {}).get("name")
    totals: dict[str, dict] = {}
    samples: dict[str, Counter] = defaultdict(Counter)
    compared = 0
    other_languages = Counter()
    for row in rows:
        page = by_url.get(row["url"])
        declared = row.get("declared")
        other = row.get("main_content_language") or row.get("detected")
        if page is None or not declared or not other:
            continue
        other_languages[other] += 1
        compared += counterpart(page, other, by_url) is not None
        for region, value in page_regions(page, declared, other, by_url, brand, row.get("foreign_share")).items():
            t = totals.setdefault(region, {"region": region, "foreign": 0, "total": 0, "pages": 0, "pages_read": 0})
            t["foreign"] += value["foreign"]
            t["total"] += value["total"]
            t["pages_read"] += 1
            t["pages"] += value["foreign"] > 0
            samples[region].update(value["samples"])
    if not totals:
        return None
    found = []
    for region in REGIONS:
        t = totals.get(region)
        if not t or not t["foreign"]:
            continue
        share = t["foreign"] / t["total"] if t["total"] else 0
        t["in_other_language"] = share >= MIN_SHARE or t["foreign"] >= MIN_ITEMS * t["pages_read"]
        t["share"] = round(share, 2)
        t["samples"] = [s for s, _ in samples[region].most_common(4)]
        found.append(t)
    return {"other_language": other_languages.most_common(1)[0][0] if other_languages else None,
            "regions": found, "pages_compared_with_other_version": compared, "pages": len(rows), "method": METHOD}


def advice(found: dict | None, platform: str | None, lang: str) -> list[str]:
    """Steps for the regions in the other language, in the catalogue's words, with the platform's tool first."""
    if not found:
        return []
    from .facts import _catalogue
    entry = _catalogue().get("str12.language") or {}
    steps = []
    tool = ((entry.get("platform_steps_language") or {}).get(platform or "") or {}).get(lang)
    if tool:
        steps.append(tool)
    for t in found["regions"]:
        if t.get("in_other_language"):
            line = ((entry.get("region_steps") or {}).get(t["region"]) or {}).get(lang)
            if line:
                steps.append(line)
    return steps[:4]


LANGUAGE_RULES = frozenset({"str12.language", "str12.headings", "str9.lang_mismatch"})


def attach(report: dict) -> list[str]:
    """Set `evidence.regions` on each language-mismatch finding of a report dict; the ids it set. Never twice."""
    done = []
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            if f.get("rule_id") in LANGUAGE_RULES and "regions" not in (f.get("evidence") or {}):
                found = regions(report, f)
                if found:
                    f.setdefault("evidence", {})["regions"] = found
                    done.append(f.get("id"))
    return done


def line(found: dict | None, names: dict[str, str]) -> str | None:
    """"menu 39%, item titles 70%, body text 98%": the regions in the other language with their share, or None."""
    if not found:
        return None
    parts = [f"{names.get(t['region'], t['region'])} %{round(t['share'] * 100)}" if names.get("_percent_first")
             else f"{names.get(t['region'], t['region'])} {round(t['share'] * 100)}%"
             for t in found["regions"] if t.get("in_other_language")]
    return ", ".join(parts) or None
