"""Checks of one business profile (DECISIONS 356): run only when the audit's business type is that profile, on the
pages it typed (`grouping.business_page_type`). Today the SaaS / Yazılım profile; a profile with no rules here gets none.

Each rule reads what the crawl already holds (the page's analysis and its main text) and sends no request. A live audit
reads the main text from the page in memory; a saved one from its evidence copies (`artifacts/evidence/*.json`), so both
get the same rule (`maya_audit.reassess_rules._decisions_356`). A page whose text was not kept is not judged; the rule
says so.

| Rule id | Check | Type | What it reports |
|---|---|---|---|
| rnd2.saas_pricing_text | RND-2 | Kontrol edin | a pricing page whose text holds no price with a currency or period (plans and prices only in images or scripts) |
| str3.saas_offer_schema | STR-3 | Sorun | a pricing page showing prices as text with no Offer, AggregateOffer, Product or SoftwareApplication markup |
| str15.saas_feature_intro | STR-15 | Kontrol edin | a feature page whose first paragraph does not say in a sentence what the feature does and for whom |
| rnd4.saas_integrations_text | RND-4 | Kontrol edin | an integrations page whose integrations are logos whose names the text does not give |
| str15.saas_story_result | STR-15 | Kontrol edin | a customer story with no measurable result (a number with %, "kat", a currency, growth or saving) |
| acc3.saas_trial_blocked | ACC-3 | Sorun | a demo or trial page with noindex, an X-Robots-Tag noindex, or an error status |

Global: no brand, no address and no fixed title; the profile and its page types are data.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..findings import Finding, Severity, scope_for
from ..models import Confidence
from ..page_words import fold

GOOGLE = "Google AI Overviews / AI Mode"
COPILOT = "Microsoft Copilot (Bing index)"
CHATGPT = "ChatGPT search"
DOCUMENTED = "Documented (Google Search Central)"
JUDGED = "Inferred from the page's text (DECISIONS 356)"
MAX_ROWS = 200
PROFILE = "saas"

# A price as text: an amount with a currency or a billing period (folded text, Turkish and English).
_CURRENCY = r"(?:₺|tl|try|\$|usd|€|eur|£|gbp)"
_AMOUNT = r"\d{1,3}(?:[., ]\d{3})*(?:[.,]\d{1,2})?"
PRICE = re.compile(rf"(?:{_CURRENCY} ?{_AMOUNT}|{_AMOUNT} ?{_CURRENCY}(?![a-z])|{_AMOUNT} ?/ ?(?:ay|yil|month|mo|year|yr)(?![a-z]))")
SITEWIDE_SHARE = 0.5   # a text line on this share of the pages with text is the site's furniture (a banner, a menu)
SITEWIDE_MIN = 4
OFFER_TYPES = frozenset({"Offer", "AggregateOffer", "Product", "SoftwareApplication", "WebApplication", "MobileApplication",
                         "PriceSpecification", "UnitPriceSpecification"})
# What a sentence that says what a feature does and for whom holds (folded).
PURPOSE = re.compile(r"(?<![a-z])(icin|sayesinde|saglar|olanak|yardimci|yonet\w*|kolayca|otomatik\w*|helps?|lets|allows?|"
                     r"enables?|for (?:teams|businesses|stores|you|your)|so (?:you|that)|"
                     # the reader addressed: "size", "sitenizde", "you", "your" (who it is for)
                     r"siz|size|sizin|sizi|\w+n[iu]z\w*|you|your)(?![a-z])")
INTRO_MIN = 80        # characters of the first paragraph that can say what and for whom (agent default)
INTRO_LINES = 6       # lines after the main heading looked at for that paragraph
# A measurable result in a customer story (folded).
RESULT = re.compile(rf"(?:%\s?\d+|\d+(?:[.,]\d+)?\s?%|\d+(?:[.,]\d+)?\s?(?:kat|x)(?![a-z])|{_AMOUNT}\s?{_CURRENCY}(?![a-z])|"
                    r"(?<![a-z])(?:artis\w*|artt\w*|artir\w*|azal\w*|tasarruf\w*|increase[sd]?|grew|growth|reduced|saved)(?![a-z]))")
STORY_WORDS_MIN = 150  # a story page, not a logo list
# A page that calls itself a customer story (its address, title or H1, folded).
STORY = re.compile(r"(?<![a-z])(hikaye\w*|basari hikaye\w*|story|stories|case.?stud\w*|success)(?![a-z])")
LOGOS_MIN = 6          # content images on an integrations page before its names are looked for in the text
NAMES_SHARE = 0.5      # at least this share of the logos' names must be in the text

PRICING_EXPECTED = "a pricing page gives its plans, what each includes and its prices (with the currency) as text"
PRICING_FIX = ("Write each plan's name, price (with the currency and the billing period) and what it includes as text "
               "in the page's HTML: a table or a list. Keep images and scripts as decoration, not as the only place "
               "the prices are.")
PRICING_NOTE = ("Answer engines quote prices they can read as text; a price inside an image or drawn by a script after "
                "loading is invisible to most of them. Maya found no amount with a currency or period in the page's text.")
OFFER_EXPECTED = "a page that shows prices carries Offer (or AggregateOffer) markup with the same prices"
OFFER_FIX = ("Add SoftwareApplication or Product markup with an Offer per plan (price, priceCurrency, and the billing "
             "period in priceSpecification) that matches the prices shown on the page.")
FEATURE_EXPECTED = "a feature page says in its first paragraph what the feature does and for whom"
FEATURE_FIX = ("Open the page with one or two plain sentences under the main heading: what the feature does, for which "
               "kind of user or business, and the result it gives. Keep slogans for the heading.")
FEATURE_NOTE = ("An answer engine quoting a feature takes the page's first lines; a slogan or a heading alone says too "
                "little. This is read from the text, so check it before changing the page.")
INTEGRATIONS_EXPECTED = "an integrations page names each integration in text, not only with its logo"
INTEGRATIONS_FIX = ("Write each integration's name (and one line on what it connects) as text beside its logo, or as a "
                    "list or table; give each logo an alt text with the name.")
STORY_EXPECTED = "a customer story names the customer and gives a measurable result"
STORY_FIX = ("Name the customer and give at least one measurable result in the text (a percentage, a multiple, time or "
             "money saved) with the period it covers.")
STORY_NOTE = ("Stories with a named customer and a number are what answer engines cite as proof. Maya found no number "
              "with %, 'kat', a currency, growth or saving in this page's text; check it before changing the page.")
TRIAL_EXPECTED = "a demo or trial page answers 200 and can be indexed"
TRIAL_FIX = ("Remove the noindex (meta robots or X-Robots-Tag) from the demo or trial page and make it answer 200; if "
             "the form itself must stay out of search, keep a public page that describes the demo and links to it.")


def _row(tr: str, en: str) -> dict:
    return {"tr": tr, "en": en}


def _tier(urls: Iterable[str], key_urls) -> int:
    return 0 if any(u in key_urls for u in urls) else 2


def _get(page, name, default=None):
    return page.get(name, default) if isinstance(page, dict) else getattr(page, name, default)


def page_text(page) -> str | None:
    """The page's main text as the evidence keeps it (one text node per line), from the page in memory; None when the
    crawl kept no text of it."""
    a = _get(page, "analysis") or {}
    blocks = a.get("_content_blocks") or a.get("_text_blocks")
    return "\n".join(blocks) if blocks else None


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _h1(analysis: dict) -> str:
    return next((h.get("text") or "" for h in analysis.get("h1_elements") or [] if isinstance(h, dict) and h.get("text")), "")


def first_paragraph(text: str, h1: str) -> str | None:
    """The first line of INTRO_MIN or more characters among the INTRO_LINES lines after the main heading (from the
    start when the heading is not in the text; a heading split over lines ends at its last part); None when there is
    none."""
    lines = _lines(text)
    start = 0
    key = re.sub(r"\s+", " ", fold(h1)).strip()
    if key:
        for i, line in enumerate(lines):
            part = re.sub(r"\s+", " ", fold(line)).strip()
            if part and (part == key or (len(part) >= 6 and key.startswith(part)) or key in part):
                start = i + 1
                while start < len(lines) and fold(lines[start]).strip() and fold(lines[start]).strip() in key:
                    start += 1  # the rest of a heading split over lines
                break
    return next((line for line in lines[start:start + INTRO_LINES] if len(line) >= INTRO_MIN), None)


def without_furniture(texts: dict[str, str]) -> dict[str, str]:
    """Each page's text without the lines found on SITEWIDE_SHARE of the pages or more (a promotion banner, a cookie
    notice): they are not what one page says."""
    if len(texts) < SITEWIDE_MIN:
        return texts
    from collections import Counter
    seen = Counter(line for text in texts.values() for line in set(_lines(text)))
    common = {line for line, n in seen.items() if n / len(texts) >= SITEWIDE_SHARE}
    return {u: "\n".join(line for line in _lines(t) if line not in common) for u, t in texts.items()}


def noindex(page) -> str | None:
    a = _get(page, "analysis") or {}
    for m in a.get("meta") or []:
        if isinstance(m, dict) and str(m.get("name") or "").lower() in ("robots", "googlebot") and "noindex" in str(m.get("content") or "").lower():
            return "meta robots noindex"
    headers = {str(k).lower(): str(v) for k, v in (_get(page, "headers") or {}).items()} if isinstance(_get(page, "headers"), dict) else {}
    if "noindex" in headers.get("x-robots-tag", "").lower():
        return "X-Robots-Tag noindex"
    return None


def findings(pages, types: dict[str, str | None], profile: str | None, texts: dict[str, str] | None = None,
             key_urls=frozenset()) -> tuple[dict[str, list[Finding]], list[dict]]:
    """({check id: findings}, [{rule, why} not assessed]) for the profile's rules. `types`: {url: business page type};
    `texts`: {url: main text} for pages not in memory (a saved audit)."""
    out: dict[str, list[Finding]] = {}
    missing: list[dict] = []
    if profile != PROFILE:
        return out, missing
    texts = dict(texts or {})
    for p in pages:  # a live audit: the text of the pages in memory
        if _get(p, "url") and page_text(p) is not None:
            texts[_get(p, "url")] = page_text(p)
    texts = without_furniture(texts)
    by_type: dict[str, list] = {}
    for p in pages:
        url = _get(p, "url")
        if not url or not isinstance(_get(p, "analysis"), dict):
            continue
        by_type.setdefault(types.get(url) or "", []).append(p)

    def text_of(p) -> str | None:
        return texts.get(_get(p, "url"))

    def add(check: str, finding: Finding) -> None:
        out.setdefault(check, []).append(finding)

    # 1, 2. pricing pages: prices as text, then their markup
    no_text, no_markup, unread = [], [], []
    for p in by_type.get("pricing", []):
        url, a, text = _get(p, "url"), _get(p, "analysis"), text_of(p)
        if text is None:
            unread.append(url)
            continue
        prices = sorted({m.group(0).strip() for m in PRICE.finditer(fold(text))})[:5]
        images = sum(1 for i in a.get("images") or [] if isinstance(i, dict) and not i.get("in_chrome"))
        if not prices:
            no_text.append({"url": url, "images": images, "tables": len(a.get("tables") or []),
                            "row": _row(f"metinde para birimli fiyat yok ({images} içerik görseli)",
                                        f"no price with a currency in the text ({images} content images)")})
            continue
        types_on = set((a.get("structured_data") or {}).get("types") or [])
        if not types_on & OFFER_TYPES:
            no_markup.append({"url": url, "prices": prices, "types": sorted(types_on)[:10],
                              "row": _row(f"metinde fiyat var ({', '.join(prices[:2])}), Offer işaretlemesi yok",
                                          f"prices in the text ({', '.join(prices[:2])}), no Offer markup")})
    if no_text:
        urls = [r["url"] for r in no_text]
        add("RND-2", Finding("RND-2", f"{len(urls)} pricing page(s) show no price with a currency in their text",
                             Severity.S3, Confidence.INFERRED, JUDGED, [GOOGLE, COPILOT, CHATGPT], scope_for(urls),
                             {"pages": no_text[:MAX_ROWS], "profile": PROFILE,
                              "rule": "a page typed pricing whose main text holds no amount with a currency or a billing period"},
                             PRICING_EXPECTED, PRICING_FIX, notes=[PRICING_NOTE], importance_tier=_tier(urls, key_urls),
                             rule_id="rnd2.saas_pricing_text"))
    if no_markup:
        urls = [r["url"] for r in no_markup]
        add("STR-3", Finding("STR-3", f"{len(urls)} pricing page(s) show prices with no Offer markup",
                             Severity.S4, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                             {"pages": no_markup[:MAX_ROWS], "profile": PROFILE,
                              "rule": "a pricing page with an amount and a currency in its text and none of "
                                      + ", ".join(sorted(OFFER_TYPES)) + " in its structured data"},
                             OFFER_EXPECTED, OFFER_FIX, importance_tier=_tier(urls, key_urls), rule_id="str3.saas_offer_schema"))
    if unread:
        missing.append({"rule": "pricing as text (rnd2.saas_pricing_text)", "why": "the text of these pricing pages was not kept",
                        "pages": unread[:20]})

    # 3. feature pages: the first paragraph
    rows, unread = [], []
    for p in by_type.get("features", []):
        url, a, text = _get(p, "url"), _get(p, "analysis"), text_of(p)
        if text is None:
            unread.append(url)
            continue
        first = first_paragraph(text, _h1(a))
        if first and PURPOSE.search(fold(first)):
            continue
        rows.append({"url": url, "first_paragraph": (first or "")[:200],
                     "row": _row("ilk paragraf yok ya da ne yaptığını ve kimin için olduğunu söylemiyor"
                                 + (f": «{first[:80]}»" if first else ""),
                                 "no first paragraph, or it does not say what the feature does and for whom"
                                 + (f": “{first[:80]}”" if first else ""))})
    if rows:
        urls = [r["url"] for r in rows]
        add("STR-15", Finding("STR-15", f"{len(urls)} feature page(s) do not say in their first paragraph what the feature does and for whom",
                              Severity.S4, Confidence.INFERRED, JUDGED, [GOOGLE, CHATGPT], scope_for(urls),
                              {"pages": rows[:MAX_ROWS], "profile": PROFILE, "min_chars": INTRO_MIN,
                               "rule": f"no line of {INTRO_MIN}+ characters in the {INTRO_LINES} lines after the H1, or one "
                                       "with no word of purpose or audience (için, sağlar, helps, lets, for teams …)"},
                              FEATURE_EXPECTED, FEATURE_FIX, notes=[FEATURE_NOTE], importance_tier=_tier(urls, key_urls),
                              rule_id="str15.saas_feature_intro"))
    if unread:
        missing.append({"rule": "feature first paragraph (str15.saas_feature_intro)", "why": "the text of these feature pages was not kept",
                        "pages": unread[:20]})

    # 4. integrations pages: names as text
    rows = []
    for p in by_type.get("integrations", []):
        url, a, text = _get(p, "url"), _get(p, "analysis"), text_of(p)
        logos = [i for i in a.get("images") or [] if isinstance(i, dict) and not i.get("in_chrome")]
        if len(logos) < LOGOS_MIN or text is None:
            continue
        plain = fold(text)
        named = [fold(i.get("alt") or "").strip() for i in logos]
        found = sum(1 for n in named if n and n in plain)
        if found >= NAMES_SHARE * len(logos):
            continue
        rows.append({"url": url, "logos": len(logos), "names_in_text": found, "empty_alt": sum(1 for n in named if not n),
                     "row": _row(f"{len(logos)} logo, {found} tanesinin adı metinde", f"{len(logos)} logos, {found} named in the text")})
    if rows:
        urls = [r["url"] for r in rows]
        add("RND-4", Finding("RND-4", f"{len(urls)} integrations page(s) show integrations as logos whose names the text does not give",
                             Severity.S4, Confidence.INFERRED, JUDGED, [GOOGLE, CHATGPT], scope_for(urls),
                             {"pages": rows[:MAX_ROWS], "profile": PROFILE, "min_logos": LOGOS_MIN,
                              "rule": f"{LOGOS_MIN}+ content images and fewer than half of their alt texts found in the page's text"},
                             INTEGRATIONS_EXPECTED, INTEGRATIONS_FIX, importance_tier=_tier(urls, key_urls),
                             rule_id="rnd4.saas_integrations_text"))

    # 5. customer stories: a measurable result
    rows = []
    for p in by_type.get("references", []):
        url, a, text = _get(p, "url"), _get(p, "analysis"), text_of(p)
        if not STORY.search(fold(f"{url} {a.get('title') or ''} {_h1(a)}")):
            continue  # a list of customers or a page of logos, not one customer's story
        if text is None or (a.get("visible_words") or len(text.split())) < STORY_WORDS_MIN or len(text.split()) < STORY_WORDS_MIN:
            continue
        if RESULT.search(fold(text)):
            continue
        rows.append({"url": url, "words": len(text.split()),
                     "row": _row("ölçülebilir sonuç yok (yüzde, kat, tutar, artış)", "no measurable result (percentage, multiple, amount, growth)")})
    if rows:
        urls = [r["url"] for r in rows]
        add("STR-15", Finding("STR-15", f"{len(urls)} customer story page(s) give no measurable result",
                              Severity.S4, Confidence.INFERRED, JUDGED, [GOOGLE, CHATGPT], scope_for(urls),
                              {"pages": rows[:MAX_ROWS], "profile": PROFILE, "min_words": STORY_WORDS_MIN,
                               "rule": "a reference page that calls itself a story (address, title or H1), of 150+ words, with no number "
                                       "and %, 'kat', a currency, growth or saving"},
                              STORY_EXPECTED, STORY_FIX, notes=[STORY_NOTE], importance_tier=_tier(urls, key_urls),
                              rule_id="str15.saas_story_result"))

    # 6. demo and trial pages: indexable and answering
    rows = []
    for p in by_type.get("demo", []):
        url, status = _get(p, "url"), _get(p, "status")
        why = noindex(p) or (f"status {status}" if isinstance(status, int) and status >= 400 else None)
        if why:
            rows.append({"url": url, "why": why, "status": status,
                         "row": _row(f"demo / deneme sayfası: {why}", f"demo / trial page: {why}")})
    if rows:
        urls = [r["url"] for r in rows]
        add("ACC-3", Finding("ACC-3", f"{len(urls)} demo or trial page(s) are noindexed or answer an error",
                             Severity.S2, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                             {"pages": rows[:MAX_ROWS], "profile": PROFILE,
                              "rule": "a page typed demo / trial with meta robots or X-Robots-Tag noindex, or status 400+"},
                             TRIAL_EXPECTED, TRIAL_FIX, importance_tier=0, rule_id="acc3.saas_trial_blocked"))
    return out, missing


RULES = ("rnd2.saas_pricing_text", "str3.saas_offer_schema", "str15.saas_feature_intro", "rnd4.saas_integrations_text",
         "str15.saas_story_result", "acc3.saas_trial_blocked")


def extend(checks, result, key_urls=frozenset()) -> list[dict]:
    """After the business type (`final.settle`): the profile's findings added to their checks (a check not assessed
    gets none; one that gets a finding says "findings"). Returns what could not be assessed."""
    profile = (getattr(result, "business_type", None) or {}).get("id")
    if profile != PROFILE:
        return []
    pages = [p for p in getattr(result, "pages", None) or [] if isinstance(getattr(p, "grouping", None), dict)]
    types = {p.url: p.grouping.get("business_page_type") for p in pages}
    made, missing = findings(pages, types, profile, key_urls=key_urls)
    by_id = {(c.get("check_id") if isinstance(c, dict) else c.check_id): c for c in checks}
    for check_id, new in made.items():
        check = by_id.get(check_id)
        status = (check.get("status") if isinstance(check, dict) else getattr(check, "status", None)) if check is not None else None
        if check is None or status == "not_assessed":
            continue
        target = check["findings"] if isinstance(check, dict) else check.findings
        target.extend(new)
        if status == "pass":
            if isinstance(check, dict):
                check["status"] = "findings"
            else:
                check.status = "findings"
    return missing
