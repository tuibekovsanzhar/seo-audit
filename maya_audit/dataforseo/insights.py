"""Search data panels: what Google and AI assistants already show for the audited domain.

These join the backlink panel in the report's `dataforseo` section (checks DFS-3 onwards), under the same rules:
priced before anything is sent, confirmed, reserved in the ledger under the daily budget, cached, and never mixed
with a finding of Maya's own crawl. Each check is a measurement from DataForSEO's indexes, with its source and date.

- DFS-3  Domain overview: keywords ranked in Google, by position band, and estimated organic visits
- DFS-4  Ranked keywords: the keywords with the most searches the domain ranks for
- DFS-5  Quick wins: keywords ranked 4 to 20, where a small gain is worth the most
- DFS-6  Organic competitors: the domains that rank for the same keywords
- DFS-7  AI mentions in Google's AI answers; DFS-8 in ChatGPT (United States, English: all DataForSEO offers)
- DFS-9 to DFS-11  Lighthouse lab test of the homepage and up to two key pages (mobile)
- DFS-12 Google Business Profile, only when the plan says the business is local and names it

Endpoint names, request fields and response paths were read from docs.dataforseo.com on 2026-10-08. None was
called while this was written: the first real audit is the test, and a response that does not have the expected
shape is reported as "not assessed", never as a zero.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable
from urllib.parse import urlsplit

from ..urls import registrable_domain

from . import panel, pricing
from .panel import PlannedCall

# DataForSEO location code and language for the countries the plan card offers, under the names people type: English,
# the country's own, Turkish, and the two-letter code. Spelling, case, Turkish letters and punctuation do not matter
# (`_fold`). A country that is not here is not recognised: nothing is looked up for it without the person saying so.
_US, _TR, _UK = (2840, "en", "United States"), (2792, "tr", "Turkey"), (2826, "en", "United Kingdom")
_DE, _FR, _ES, _IT = (2276, "de", "Germany"), (2250, "fr", "France"), (2724, "es", "Spain"), (2380, "it", "Italy")
_NL, _CA, _AU, _AE = (2528, "nl", "Netherlands"), (2124, "en", "Canada"), (2036, "en", "Australia"), (2784, "ar", "United Arab Emirates")
LOCATIONS: dict[str, tuple[int, str, str]] = {
    "united states": _US, "us": _US, "usa": _US, "united states of america": _US, "amerika birleşik devletleri": _US, "abd": _US,
    "türkiye": _TR, "turkey": _TR, "tr": _TR,
    "united kingdom": _UK, "uk": _UK, "gb": _UK, "great britain": _UK, "birleşik krallık": _UK, "ingiltere": _UK,
    "germany": _DE, "de": _DE, "deutschland": _DE, "almanya": _DE,
    "france": _FR, "fr": _FR, "fransa": _FR,
    "spain": _ES, "es": _ES, "españa": _ES, "ispanya": _ES,
    "italy": _IT, "it": _IT, "italia": _IT, "italya": _IT,
    "netherlands": _NL, "nl": _NL, "the netherlands": _NL, "nederland": _NL, "hollanda": _NL,
    "canada": _CA, "ca": _CA, "kanada": _CA,
    "australia": _AU, "au": _AU, "avustralya": _AU,
    "united arab emirates": _AE, "ae": _AE, "uae": _AE, "birleşik arap emirlikleri": _AE, "bae": _AE,
}
DEFAULT_LOCATION = (2840, "en", "United States")
RANKED_LIMIT, QUICK_WIN_LIMIT, COMPETITOR_LIMIT = 100, 50, 20
QUICK_WIN_POSITIONS = (4, 20)
LIGHTHOUSE_PAGES = 3
SEARCH_VOLUME = "keyword_data.keyword_info.search_volume,desc"
RANK = "ranked_serp_element.serp_item.rank_group"
# Google's own "good" thresholds for the lab metrics shown; a value past them is marked, not judged as a finding.
LAB_GOOD = {"largest-contentful-paint": 2500, "cumulative-layout-shift": 0.1, "total-blocking-time": 200}


_PARENTHESISED = re.compile(r"^(.*?)\(([^()]*)\)\s*$")


def _fold(text: str) -> str:
    """A country as typed, for comparing: lower case, no letter marks (Turkish İ and ı included), no punctuation."""
    lowered = (text or "").replace("İ", "i").replace("I", "i").lower().replace("ı", "i")
    plain = "".join(char for char in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s]", " ", plain).split())


_BY_FOLDED = {_fold(name): place for name, place in LOCATIONS.items()}


def location_for(country: str | None) -> tuple[int, str, str, bool]:
    """(location code, language, name, whether the country was recognised).

    "Turkey", "Türkiye", "TÜRKİYE", "turkiye", "TR" and "Türkiye (TR)" are one country: the name is folded, and a name
    with a code in brackets is tried whole, then by its name, then by its code. An unrecognised or missing country
    comes back as the United States with False: the caller decides whether that may be used (DECISIONS 179)."""
    typed = country or ""
    bracketed = _PARENTHESISED.match(typed.strip())
    for candidate in (typed, *((bracketed.group(1), bracketed.group(2)) if bracketed else ())):
        folded = _fold(candidate)
        found = _BY_FOLDED.get(folded) or _BY_FOLDED.get(folded.replace(" ", ""))  # "U.S.A." is "usa"
        if found:
            return (*found, True)
    return (*DEFAULT_LOCATION, False)


def known_spellings() -> str:
    """A few spellings a person can type, for an error that has to say what would be recognised."""
    return "Turkey, Türkiye, TR, United States, US, United Kingdom, UK, Germany, Deutschland, France, Spain, Italy, Netherlands, Canada, Australia, United Arab Emirates"


def market_warning(country: str | None) -> str | None:
    """What to say before a paid run when the plan's country is not one this tool can ask DataForSEO about."""
    if location_for(country)[3]:
        return None
    named = (country or "").strip()
    return ((f"“{named}” is not a country this tool can ask DataForSEO about" if named else "The plan names no country")
            + f", so the search data would be for {DEFAULT_LOCATION[2]} ({DEFAULT_LOCATION[1]}), not for this business's own market. "
              "Set the country under “About this business” first, or read the figures as United States figures.")


def lighthouse_pages(url: str, key_pages: Iterable[str] = (), home: str | None = None) -> list[str]:
    """The pages the lab test is run on: the homepage and up to two key pages.

    `home` is where the crawl found the homepage (the typed address may redirect, say to the www host). It takes the
    typed homepage's place when it is on the same registrable domain, so the list is never longer than the one priced."""
    typed = f"{urlsplit(url).scheme or 'https'}://{urlsplit(url).netloc}/"
    final = typed
    if home and urlsplit(home).scheme in ("http", "https") and registrable_domain(urlsplit(home).hostname or "") == registrable_domain(urlsplit(url).hostname or ""):
        final = home
    return list(dict.fromkeys(final if page == typed else page for page in [typed, *key_pages]))[:LIGHTHOUSE_PAGES]


def audit_plan(url: str, *, country: str | None = None, brand: str | None = None, key_pages: Iterable[str] = (),
               local_business: bool = False, home: str | None = None) -> list[PlannedCall]:
    """Every search-data call one audit makes. The same list prices the plan and runs it."""
    target = panel.target_domain(url)
    not_sent = None if panel._is_public_domain(target) else (
        f"{target or url!r} is not a public domain name, so a search index has nothing to look up. No request was sent.")
    code, language, place, known = location_for(country)
    where = {"location_code": code, "language_code": language}
    # An unknown or missing country is the United States only when the person accepted that (the plan card's tick, or
    # --dfs-default-market); the title says so in two words.
    market = f"{place}, {language}" + ("" if known else "; default market")
    calls = [
        PlannedCall("DFS-3", f"Domain overview in Google ({market})", pricing.LABS_DOMAIN_OVERVIEW, [{"target": target, **where, "limit": 1}], target, not_sent),
        PlannedCall("DFS-4", f"Ranked keywords: the {RANKED_LIMIT} with the most searches ({market})", pricing.LABS_RANKED_KEYWORDS,
                    [{"target": target, **where, "limit": RANKED_LIMIT, "item_types": ["organic"], "order_by": [SEARCH_VOLUME]}], target, not_sent),
        PlannedCall("DFS-5", f"Quick wins: keywords ranked {QUICK_WIN_POSITIONS[0]} to {QUICK_WIN_POSITIONS[1]} ({market})", pricing.LABS_RANKED_KEYWORDS,
                    [{"target": target, **where, "limit": QUICK_WIN_LIMIT, "item_types": ["organic"], "order_by": [SEARCH_VOLUME],
                      "filters": [[RANK, ">=", QUICK_WIN_POSITIONS[0]], "and", [RANK, "<=", QUICK_WIN_POSITIONS[1]]]}], target, not_sent),
        PlannedCall("DFS-6", f"Search overlap ({market})", pricing.LABS_COMPETITORS,
                    [{"target": target, **where, "limit": COMPETITOR_LIMIT, "exclude_top_domains": True, "item_types": ["organic"]}], target, not_sent),
        PlannedCall("DFS-7", f"AI answers that cite, name or list the domain: Google's AI answers ({market})", pricing.LLM_MENTIONS_AGGREGATED,
                    [{"target": [{"domain": target, "search_scope": ["any"]}], "platform": "google", **where, "internal_list_limit": 10}], target, not_sent),
        PlannedCall("DFS-8", "AI answers that cite, name or list the domain: ChatGPT (United States, English only: the one market "
                             "DataForSEO offers, whatever the audit's market)", pricing.LLM_MENTIONS_AGGREGATED,
                    [{"target": [{"domain": target, "search_scope": ["any"]}], "platform": "chat_gpt", "location_code": 2840,
                      "language_code": "en", "internal_list_limit": 10}], target, not_sent),
    ]
    for number, page in enumerate(lighthouse_pages(url, key_pages, home)):
        calls.append(PlannedCall(f"DFS-{9 + number}", f"Lighthouse lab test (mobile): {page}", pricing.LIGHTHOUSE,
                                 [{"url": page, "for_mobile": True, "categories": ["performance", "seo", "accessibility", "best_practices"]}],
                                 page, not_sent))
    if local_business:
        name = (brand or "").strip()
        calls.append(PlannedCall("DFS-12", f"Google Business Profile for “{name or 'no name given'}” ({place})", pricing.BUSINESS_INFO,
                                 [{"keyword": name, "location_code": code, "language_code": language}], name or None,
                                 not_sent or (None if name else "the plan names no brand, so there is no business to look up. No request was sent."),
                                 context={"domain": target}))
    return calls


def _result(data: dict[str, Any]) -> dict[str, Any]:
    return panel._first_result(data)


def _measured(value: Any) -> int | float | None:
    """A number DataForSEO reported, or None. A missing, null, text or true/false value is not a measurement."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _number(value: Any) -> Any:
    return round(value, 2) if isinstance(value, float) else value


def _rows(result: dict[str, Any], what: str) -> list[dict[str, Any]]:
    """The `items` of an answer. A list (even an empty one) is an answer; anything else is an answer that cannot be
    read, unless the provider also says the total is zero."""
    items = result.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if items is None and _measured(result.get("total_count")) == 0:
        return []
    raise ValueError(f"the {what} answer holds no list of rows")


def _overview(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    items = _rows(_result(data), "domain overview")
    if not items:
        return ("DataForSEO returned an empty sample for this domain in this market: no ranking data in its index. That is the "
                "provider's coverage, not a measurement that the site ranks for nothing."), {"metrics": {}, "ranked": False, "sample": "empty"}
    organic = (items[0].get("metrics") or {}).get("organic")
    if not isinstance(organic, dict) or _measured(organic.get("count")) is None:
        raise ValueError("the domain overview holds no count of ranked keywords")
    count, visits = _measured(organic.get("count")), _measured(organic.get("etv"))
    bands = {"1": _measured(organic.get("pos_1")), "2–3": _measured(organic.get("pos_2_3")), "4–10": _measured(organic.get("pos_4_10")),
             "11–20": _measured(organic.get("pos_11_20"))}
    rest = [v for k, v in organic.items() if k.startswith("pos_") and k not in ("pos_1", "pos_2_3", "pos_4_10", "pos_11_20") and _measured(v) is not None]
    bands["21–100"] = sum(rest) if rest else None
    metrics = {"Keywords ranked in the top 100": count, "Estimated organic visits a month": _number(visits),
               **{f"Keywords in position {band}": value for band, value in bands.items()},
               "New / up / down / lost since the last update": " / ".join(panel._count(_measured(organic.get(k))) for k in ("is_new", "is_up", "is_down", "is_lost"))}
    missing = [label for label, value in (("estimated organic visits", visits), *((f"keywords in position {band}", value) for band, value in bands.items()))
               if value is None]
    said = (f"{panel._count(count)} keyword(s) ranked in Google's top 100" + (f" and about {panel._count(_number(visits))} estimated organic visit(s) a month"
                                                                             if visits is not None else "") + ", by DataForSEO's index.")
    return said + (f" Not reported by the provider: {', '.join(missing)}." if missing else ""), {
        "metrics": metrics, "ranked": bool(count), **({"missing_measurements": missing} if missing else {})}


def _keywords(data: dict[str, Any]) -> tuple[list[list[Any]], Any]:
    result = _result(data)
    rows = []
    for item in _rows(result, "ranked keywords"):
        word = item.get("keyword_data") or {}
        hit = (item.get("ranked_serp_element") or {}).get("serp_item") or {}
        rows.append([word.get("keyword"), _measured((word.get("keyword_info") or {}).get("search_volume")), _measured(hit.get("rank_group")), hit.get("url")])
    return [row for row in rows if isinstance(row[0], str) and row[0].strip()], _measured(result.get("total_count"))


def _keyword_identity_evidence(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Retain documented organic sitelinks, not an inferred knowledge-panel owner.

    Feature-presence flags describe a SERP, not which entity a panel represents.
    No extra provider call is made. Original rows and metrics remain untouched.
    """
    records = []
    for item in _rows(_result(data), "ranked keywords"):
        word = item.get("keyword_data") or {}
        hit = (item.get("ranked_serp_element") or {}).get("serp_item") or {}
        links = [{"url": link.get("url"), "title": link.get("title"), "type": link.get("type")}
                 for link in hit.get("links") or [] if isinstance(link, dict) and link.get("type") == "link_element"]
        records.append({"keyword": word.get("keyword"), "ranking_url": hit.get("url"),
                        "result_type": hit.get("type"), "sitelinks": links,
                        "observed_at": item.get("last_updated_time") or (word.get("serp_info") or {}).get("last_updated_time"),
                        "source": "DataForSEO saved ranked_serp_element.serp_item",
                        "knowledge_panel_identity": "not_assessed"})
    return records


def _ranked(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rows, total = _keywords(data)
    top10 = sum(1 for row in rows if isinstance(row[2], int) and row[2] <= 10)
    return (f"{len(rows)} keyword(s) listed of {panel._count(total)} the domain ranks for, most searched first; {top10} of those listed are in the top 10."
            ), {"total_count": total, "listed": len(rows), "identity_evidence": _keyword_identity_evidence(data), "order": "monthly searches, highest first",
                "table": {"columns": ["Keyword", "Searches a month", "Position", "Ranking page"], "rows": rows}}


def _quick_wins(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rows, total = _keywords(data)
    low, high = QUICK_WIN_POSITIONS
    searches = sum(row[1] for row in rows if isinstance(row[1], int))
    return (f"{panel._count(total)} keyword(s) rank in positions {low} to {high}; the {len(rows)} most searched are listed "
            f"({searches:,} searches a month between them). These are ranking candidates, not confirmed business opportunities; assess relevance, evidence and intended value before recommending page changes."
            ), {"total_count": total, "listed": len(rows), "identity_evidence": _keyword_identity_evidence(data), "positions": [low, high],
                "table": {"columns": ["Keyword", "Searches a month", "Position", "Ranking page"], "rows": rows}}


def _competitors(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    result = _result(data)
    rows = []
    for item in _rows(result, "competitors"):
        full = (item.get("full_domain_metrics") or {}).get("organic") or {}
        rows.append([item.get("domain"), _measured(item.get("intersections")), _number(_measured(item.get("avg_position"))),
                     _measured(full.get("count")), _number(_measured(full.get("etv")))])
    rows = [row for row in rows if isinstance(row[0], str) and row[0].strip()]
    return (f"{len(rows)} domain(s) listed that rank for the same keywords, of {panel._count(_measured(result.get('total_count')))} found. "
            "The very largest sites (marketplaces, encyclopaedias) are left out. Shared rankings do not establish business competition or ownership."
            ), {"total_count": _measured(result.get("total_count")), "listed": len(rows),
                "table": {"columns": ["Domain", "Shared keywords", "Their average position", "Their ranked keywords", "Their estimated visits a month"], "rows": rows}}


# What the request's scope ("any") matches: more than "the brand is mentioned in the answer".
MENTION_SCOPE = ("the domain is cited as a source of an AI answer, named in its text, or listed among the search results that "
                 "supported it")


def _group(total: dict[str, Any], name: str) -> list[list[Any]]:
    rows = total.get(name)
    return [[row.get("key"), _measured(row.get("mentions")), _measured(row.get("ai_search_volume"))]
            for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict) and row.get("key")]


def _mentions(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """AI answers in DataForSEO's sample that match the domain.

    A measured zero, an empty sample and a missing figure are three different answers. Only a number the provider
    reported is a count; a row without one is not "no mention found"."""
    total = _result(data).get("total")
    if not isinstance(total, dict):
        raise ValueError("the AI mentions answer holds no totals")
    platforms = total.get("platform")
    if not isinstance(platforms, list):
        raise ValueError("the AI mentions answer holds no platform total")
    sources, results = _group(total, "sources_domain"), _group(total, "search_results_domain")
    tables = {"table": {"columns": ["Domain cited as a source in those answers", "Answers", "Monthly volume of the questions"], "rows": sources},
              "supporting_results": {"columns": ["Domain in the supporting search results", "Answers", "Monthly volume of the questions"], "rows": results}}
    if not platforms:
        return (f"DataForSEO returned an empty sample: no AI answer in its collection for this platform and market matched this domain "
                f"({MENTION_SCOPE}). A sample of answers, not every answer, so this is not proof of absence."
                ), {"metrics": {"Matching AI answers in the sample": 0}, "mentioned": False, "sample": "empty", "scope": MENTION_SCOPE}
    row = platforms[0] if isinstance(platforms[0], dict) else {}
    matched, volume = _measured(row.get("mentions")), _measured(row.get("ai_search_volume"))
    if matched is None:
        raise ValueError("the AI mentions answer gives no number of matching answers")
    missing = ["monthly volume of the questions"] if volume is None else []
    metrics = {"Matching AI answers in the sample": matched, "Monthly volume of the questions": volume}
    if matched == 0:
        return (f"Measured zero: none of the AI answers in DataForSEO's sample for this platform and market matched this domain ({MENTION_SCOPE}). "
                "A sample of answers, not every answer, so this is not proof of absence."
                ), {"metrics": metrics, "mentioned": False, "sample": "measured_zero", "scope": MENTION_SCOPE, **tables}
    return (f"{panel._count(matched)} AI answer(s) in DataForSEO's sample match this domain: {MENTION_SCOPE}"
            + (f"; the questions are asked about {panel._count(volume)} time(s) a month" if volume is not None else "")
            + ". This is wider than \"the brand is mentioned in the answer\", and it is a sample of the platform's answers, not every answer."
            ), {"metrics": metrics, "mentioned": True, "sample": "matches", "scope": MENTION_SCOPE, **tables,
                **({"missing_measurements": missing} if missing else {})}


LAB_METRICS = (("largest-contentful-paint", "Largest Contentful Paint"), ("cumulative-layout-shift", "Cumulative Layout Shift"),
               ("total-blocking-time", "Total Blocking Time"), ("first-contentful-paint", "First Contentful Paint"), ("speed-index", "Speed Index"))


def _lighthouse(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """One simulated lab run. A metric is called good only when it was measured and is within Google's threshold;
    a metric the answer does not hold is named as not measured. Lab values are not what real visitors experienced
    (that is the Chrome UX Report's figure), and Total Blocking Time is a lab metric, not Interaction to Next Paint."""
    result = _result(data)
    categories = result.get("categories") if isinstance(result.get("categories"), dict) else {}
    scores = {name: _measured((categories.get(key) or {}).get("score") if isinstance(categories.get(key), dict) else None) for name, key in (
        ("Performance", "performance"), ("SEO", "seo"), ("Accessibility", "accessibility"), ("Best practices", "best-practices"))}
    audits = result.get("audits") if isinstance(result.get("audits"), dict) else {}
    values = {key: _measured((audits.get(key) or {}).get("numericValue") if isinstance(audits.get(key), dict) else None) for key, _label in LAB_METRICS}
    if all(score is None for score in scores.values()) and all(value is None for value in values.values()):
        raise ValueError("the Lighthouse answer holds no score and no timing")
    metrics = {f"{name} score (0–100)": None if score is None else round(score * 100) for name, score in scores.items()}
    for key, label in LAB_METRICS:
        shown = (audits.get(key) or {}).get("displayValue") if isinstance(audits.get(key), dict) else None
        metrics[label] = shown if values[key] is not None else None
    judged = {label: values[key] for key, label in LAB_METRICS if key in LAB_GOOD}
    slow = [label for key, label in LAB_METRICS if key in LAB_GOOD and values[key] is not None and values[key] > LAB_GOOD[key]]
    good = [label for key, label in LAB_METRICS if key in LAB_GOOD and values[key] is not None and values[key] <= LAB_GOOD[key]]
    unmeasured = [label for label, value in judged.items() if value is None]
    missing = unmeasured + (["performance score"] if scores["Performance"] is None else [])
    performance = metrics["Performance score (0–100)"]
    parts = [f"Lab test on a simulated phone: performance {panel._count(performance)} of 100" if performance is not None
             else "Lab test on a simulated phone: no performance score was reported"]
    if slow:
        parts.append(f"past Google's \"good\" threshold: {', '.join(slow)}")
    if good and not slow and not unmeasured:
        parts.append("the three main lab metrics are within Google's \"good\" thresholds")
    elif good:
        parts.append(f"within the threshold: {', '.join(good)}")
    if unmeasured:
        parts.append(f"not measured in this answer, so not judged: {', '.join(unmeasured)}")
    return ("; ".join(parts) + ". One lab run, not what real visitors experienced."), {
        "metrics": metrics, "past_good_threshold": slow, "within_good_threshold": good, "device": "mobile",
        **({"measurement_at": result["fetchTime"]} if result.get("fetchTime") else {}),
        **({"missing_measurements": missing} if missing else {})}


def _business(data: dict[str, Any], context: Any = None) -> tuple[str, dict[str, Any]]:
    """A Google Business Profile found by name. A name is not an identity: the profile is treated as the audited
    business only when its own website is the audited domain. Otherwise it is shown, and nothing is recommended."""
    items = _rows(_result(data), "business profile")
    profiles = [item for item in items if item.get("title")]
    if not profiles:
        return ("DataForSEO returned no Google Business Profile under this name in this country. Check the name, or the business may not "
                "have a profile."), {"metrics": {}, "found": False, "sample": "empty"}
    expected = (context or {}).get("domain") if isinstance(context, dict) else None
    own = lambda item: bool(expected) and registrable_domain(urlsplit(str(item.get("url") or "")).hostname or str(item.get("domain") or "")) == expected  # noqa: E731
    first = next((item for item in profiles if own(item)), profiles[0])
    confirmed = own(first)
    rating = first.get("rating") if isinstance(first.get("rating"), dict) else {}
    metrics = {"Name": first.get("title"), "Category": first.get("category"), "Address": first.get("address"), "Phone": first.get("phone"),
               "Website on the profile": first.get("url") or first.get("domain"), "Rating": _measured(rating.get("value")),
               "Reviews": _measured(rating.get("votes_count")), "Claimed by the owner": {True: "yes", False: "no"}.get(first.get("is_claimed")),
               "Photos": _measured(first.get("total_photos"))}
    gaps = [label for label, key in (("phone", "phone"), ("website", "url"), ("category", "category")) if not first.get(key)]
    gaps += ["claimed by the owner"] if first.get("is_claimed") is False else []
    identity = ("confirmed: the profile's website is the audited domain" if confirmed else
                "NOT confirmed: the profile was found by name only" + (f", and its website ({first.get('url') or first.get('domain')}) is not "
                                                                       f"the audited domain ({expected})" if expected and (first.get("url") or first.get("domain"))
                                                                       else ", and it lists no website to compare"))
    said = (f"Profile found: {first.get('title')}, rated {panel._count(_measured(rating.get('value')))} from "
            f"{panel._count(_measured(rating.get('votes_count')))} review(s). Identity {identity}.")
    if confirmed:
        said += (f" Missing on the profile: {', '.join(gaps)}." if gaps else " Nothing is missing among phone, website, category and owner claim.")
    else:
        said += " Check the address and website by hand before changing anything: another business may share the name."
    return said, {"metrics": metrics, "found": True, "identity_confirmed": confirmed, "identity": identity,
                  # What is missing is advice only for a profile known to be this business.
                  "missing": gaps if confirmed else [], "missing_if_this_is_the_business": gaps, "profiles_returned": len(profiles)}


READERS = {pricing.LABS_DOMAIN_OVERVIEW: _overview, pricing.LABS_COMPETITORS: _competitors, pricing.LLM_MENTIONS_AGGREGATED: _mentions,
           pricing.LIGHTHOUSE: _lighthouse, pricing.BUSINESS_INFO: _business}


def reader_for(call: PlannedCall):
    """How this call's response is read. Ranked keywords and quick wins share an endpoint and differ by check."""
    if call.endpoint == pricing.LABS_RANKED_KEYWORDS:
        return _quick_wins if call.check_id == "DFS-5" else _ranked
    if call.endpoint == pricing.BUSINESS_INFO:
        return lambda data: _business(data, call.context)
    return READERS.get(call.endpoint)


# -- Relevance: which of these searches are about this business? --------------------------------------------------
#
# DataForSEO reports every keyword a domain ranks for. A brand whose name is an ordinary word ("Maximum", "Apple",
# "Summit") ranks for searches that only share the word. The rules below sort keywords into evidence-labelled groups from the
# brand name, the words of the site's own titles, headings and descriptions, and the business description. They are
# word matching, not understanding: the report says so, and keeps the unrelated group visible instead of dropping it.

BRANDED, RELEVANT, UNRELATED, AMBIGUOUS = "branded", "relevant", "unrelated", "ambiguous"
GROUPS = (BRANDED, RELEVANT, UNRELATED, AMBIGUOUS, "related_organization")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset("""a an and are as at be by for from has have how in is it its near of on or that the this to vs what when where which who why
with your you our we us my me do does can will best top free online new buy price cost review reviews login log sign app com www
ve ile bir bu da de için mi mı mu mü ne nasıl en çok daha gibi ya veya fiyat fiyatı fiyatları yorum yorumlar nedir""".split())
# Ordinary words that are also used as brand names. Only this list is used, never the computer's own word list (A29):
# /usr/share/dict/words made the same keyword a brand search on one machine and not on another.
_COMMON = frozenset("""maximum minimum apple amazon target shell delta summit pioneer prime unity vision atlas nova bolt wise square stripe
notion slack zoom monday linear arc signal compass anchor bridge harbor harbour beacon legend origin oracle orbit pulse quest rocket
shield spark sprint titan vertex zenith alpha omega eagle falcon phoenix tiger lion panda fox wolf bear hawk dove swan ocean river
mountain forest garden island desert storm thunder breeze sunrise sunset moon star stars sun cloud rain snow fire ice stone gold
silver diamond pearl ruby crystal mirror window door key bridge tower castle crown royal noble grand elite premium classic modern
smart simple pure fresh bright clear true real good better best first next future global local central general national united
maya kale deniz güneş yıldız ay bulut dağ nehir orman bahçe ada altın gümüş elmas inci ayna anahtar köprü kule saray taç zirve
doruk ufuk umut hayat dünya anadolu marmara ege akdeniz boğaz çınar lale gül papatya zeytin nar elma armut kiraz""".split())
def _tokens(text: str | None) -> list[str]:
    import unicodedata
    folded = (text or "").replace("İ", "i").lower().replace("ı", "i")
    folded = ''.join(c for c in unicodedata.normalize('NFKD', folded) if not unicodedata.combining(c))
    return _WORD.findall(folded)


_STOP = frozenset(_tokens(" ".join(_STOP)))
_COMMON = frozenset(_tokens(" ".join(_COMMON)))


def _stem(word: str) -> str:
    """Enough to match "bank" with "banks" and "banking"; not a real stemmer."""
    for ending in ("mesi", "masi", "me", "ma", "ing", "es", "s"):
        if len(word) > len(ending) + 3 and word.endswith(ending):
            return word[: -len(ending)]
    return word


def brand_words(brand: str | None, domain: str | None) -> set[str]:
    """The words that name the business: the brand name's words and the domain's own label."""
    label = (domain or "").split(".")[0]
    return {word for word in [*_tokens(brand), *_tokens(label)] if len(word) >= 2 and word not in _STOP}


def common_word_brand(brand: str | None, domain: str | None = None) -> str | None:
    """The brand name's word when it is also an ordinary word, so searches for it are not all about the business."""
    words = _tokens(brand) or _tokens((domain or "").split(".")[0])
    if len(words) != 1:
        return None  # "Maximum Bank" or "Demo Shop" is specific enough to search for
    word = words[0]
    return word if word in _COMMON else None


def site_vocabulary(texts: Iterable[str], brand: set[str]) -> set[str]:
    """The site's own subject words: what its titles, headings, descriptions and business description are made of."""
    return {_stem(word) for text in texts for word in _tokens(text) if len(word) >= 2 and word not in _STOP and word not in brand}


# Words that, beside a brand name, mean "the company": what people add when they look for a business by name.
_COMPANY_WORDS = frozenset("""login log sign signin signup app apps website site official com inc llc ltd co corp company technologies technology
tech labs software systems bank banking reviews review careers career jobs job hiring contact support pricing price demo api docs
status news press blog about founder founders ceo funding investors linkedin crunchbase glassdoor customer service phone number address
headquarters hq giriş kariyer iletişim hakkında fiyat fiyatları yorum yorumlar şirket""".split())


# A search written as the start of the brand names it when it is at least this long and two or more words (DECISIONS 220).
_COMPANY_WORDS = frozenset(_tokens(" ".join(_COMPANY_WORDS)))
MIN_BRAND_START = 8


def classify_keyword(keyword: str, brand: set[str], vocabulary: set[str], common: bool | str | None, *,
                     first: str | None = None, whole: Iterable[str] = (), glued: str | None = None) -> str:
    """branded, relevant, unrelated or ambiguous.

    A specific brand name in a search makes it branded. A brand name that is an ordinary word does not: "maximum
    heart rate" is not about a company called Maximum. Such a search is branded only when the name comes with
    nothing but company words ("maximum login", "maximum technologies") or one or two of the site's own subject
    words ("maximum bank"). The ordinary word on its own ("maximum") is ambiguous: nobody can say whether the
    person meant the business, so it is neither counted as a brand search nor offered as an opportunity.

    A brand of two or more words (`first` is its first word, `whole` the name written as one word): a search names it
    when it holds two of its words, or its first word, or the whole name as one word. One later word alone ("yemek
    tarifleri" for "Lezzetli Yemek Evi") is an ordinary word of the trade, judged as any other search (DECISIONS 201).

    `glued` is the brand written without spaces (`maya_audit.brand.compact`), given when the name is not an ordinary
    word: a search whose words joined without spaces start with it, or are a beginning of it at least 8 letters long
    made of two or more words ("adile sultan ev" for "Adilesultanevyemekleri"), is a brand search (DECISIONS 220)."""
    raw = _tokens(keyword)
    if glued and not common:
        from .. import brand as brand_module

        joined = brand_module.compact(keyword)
        if joined and (joined.startswith(glued) or (len(raw) >= 2 and len(joined) >= MIN_BRAND_START and glued.startswith(joined))):
            return BRANDED
    words = [word for word in raw if word not in _STOP]
    if first is not None:
        hits = {word for word in raw if word in brand}
        if not (len(hits) >= 2 or first in raw or any(word in set(whole) for word in raw)):
            on_topic = [word for word in words if _stem(word) in vocabulary]
            return RELEVANT if words and len(on_topic) * 2 >= len(words) else UNRELATED
        brand = brand | set(whole)
    named = [word for word in raw if word in brand]
    if named:
        if not common:
            return BRANDED
        rest = [word for word in raw if word not in brand]
        about_company = all(word in _COMPANY_WORDS or _stem(word) in vocabulary for word in rest)
        if not rest:
            # The ordinary word alone. (`common` may be that word, or True when only "it is one" is known.)
            ordinary = {common} if isinstance(common, str) else brand
            return AMBIGUOUS if len(set(raw)) == 1 and raw[0] in ordinary else BRANDED
        return BRANDED if about_company and len(rest) <= 2 else UNRELATED
    others = [word for word in words if word not in brand]
    on_topic = [word for word in others if _stem(word) in vocabulary]
    return RELEVANT if others and len(on_topic) * 2 >= len(others) else UNRELATED


def page_texts(pages: Iterable[Any]) -> list[str]:
    """What the site says it is about: each page's title, its main headings and its meta description."""
    texts: list[str] = []
    for page in pages:
        if hasattr(page, "readable_document") and not page.readable_document():
            continue
        analysis = getattr(page, "analysis", None) or {}
        texts.append(str(analysis.get("title") or ""))
        texts += [str(h.get("text") or "") for h in analysis.get("headings") or [] if isinstance(h, dict) and (h.get("level") or 9) <= 2]
        texts += [str(m.get("content") or "") for m in analysis.get("meta") or [] if isinstance(m, dict) and m.get("name") == "description"]
    return [text for text in texts if text.strip()]


# Said on DFS-4 and DFS-5 when no brand name is known: the keywords stay one plain table (DECISIONS 201).
NOT_SORTED = ("The brand name could not be confirmed, so these keywords are not sorted into brand searches and other "
              "searches.")


def apply_relevance(section: dict[str, Any], *, brand: str | None, domain: str | None, texts: Iterable[str],
                    brand_info: dict[str, Any] | None = None, pages: Iterable[Any] = (),
                    aliases: Iterable[str] = (), related_organizations: Iterable[str] = (), retained_assessments: dict | None = None, declared_identity_aliases: Iterable[dict] = ()) -> dict[str, Any]:
    """Sort the keyword panels by relevance and say what was left out. Changes `section` in place and returns it.

    DFS-4 and DFS-5 keep the branded and relevant keywords in their table and move the rest to "unrelated"; DFS-6
    loses the audited domain itself; a common-word brand is said on each panel it distorts.

    `brand_info` is the audit's brand (`maya_audit.brand.resolve`: typed, the site's own name, the address split into
    the site's words, or none). Without it, `brand` is taken as typed, else the address is split into the words of
    `texts`. With no name at all the keyword tables stay as they are, with `NOT_SORTED` said on them."""
    from .. import brand as brand_module

    texts = list(texts)
    pages = list(pages)
    aliases, related_organizations = list(aliases), list(related_organizations)
    from ..main_content import main_blocks, repeated_blocks
    repeated = repeated_blocks([p for p in pages if getattr(p, 'analysis', None)])
    content_context = {p.url: main_blocks(p.analysis, repeated) for p in pages if getattr(p, 'analysis', None)}
    info = brand_info if brand_info is not None else brand_module.from_texts(brand, domain, texts)
    brand = info.get("name")
    meta = {"brand_source": info.get("source"), "brand_confirmed": bool(info.get("confirmed"))}
    if not brand:
        _not_sorted(section, domain)
        section["relevance"] = {"brand_words": [], "common_word_brand": None, "warning": None, "site_words_used": 0,
                                "sorted": False, **meta}
        section.update(qualify_section(section))
        return section
    own = [word for word in _tokens(brand) if len(word) >= 2 and word not in _STOP]
    names = brand_words(brand, domain) if len(own) < 2 else set(own)
    # The name written as one word, and the address's own label: a glued label names the whole brand by itself.
    whole = {"".join(own), "".join(_tokens((domain or "").split(".")[0]))} if len(own) >= 2 else set()
    first = own[0] if len(own) >= 2 else None
    declared = brand_module.declared_aliases(pages, brand, domain) + list(declared_identity_aliases)
    common = common_word_brand(brand, domain)
    vocabulary = site_vocabulary(texts, names if first is None else whole)
    warning = (f"“{(brand or common or '').strip() or common}” is also an ordinary word, so the listed keyword sample may include "
               "searches that only share the word.") if common else None
    by_id = {check["check_id"]: check for check in section.get("checks") or []}
    counts: dict[str, dict[str, int]] = {}
    for check_id in ("DFS-4", "DFS-5"):
        check = by_id.get(check_id)
        data = ((check or {}).get("evidence") or {}).get("data") or {}
        rows = (data.get("table") or {}).get("rows")
        if not check or check.get("status") != "observed" or rows is None or data.get("relevance"):
            continue
        from .relevance import assess
        import copy
        data["provider_table"] = copy.deepcopy(data["table"])
        groups: dict[str, list[list[Any]]] = {name: [] for name in GROUPS}
        assessments = []
        for row in rows:
            retained=(retained_assessments or {}).get((row[0],row[3]if len(row)>3 else None))
            category, evidence = assess(str(row[0]), row[3] if len(row) > 3 else None,
                names=names, vocabulary=vocabulary, common=common, first=first, whole=whole,
                glued=None if common else brand_module.compact(brand), pages=pages, domain=domain, corpus=texts,
                aliases=aliases, organizations=related_organizations, brand=brand, content_context=content_context, site_aliases=declared,
                serp_evidence=[r for r in data.get("identity_evidence", []) if r.get("keyword") == row[0] and r.get("ranking_url") == (row[3] if len(row) > 3 else None)])
            if retained:
                category=retained['category']
                evidence={k:v for k,v in retained.items()if k not in ('keyword','ranking_url','category','confidence')}
            groups[category].append(row)
            assessments.append({"keyword": row[0], "ranking_url": row[3] if len(row) > 3 else None,
                                "category": category, "confidence": "lexical estimate", **evidence})
        data["keyword_assessments"] = assessments
        data.update(qualified_opportunity_data(data))
        data["intent_dimensions"] = {"title": "Keyword intent evidence (listed sample only)", "note": "Dimensions may overlap; lexical evidence requires review. Ranking alone proves neither relevance nor ownership.", "columns": ["Keyword", "Supported dimensions", "Reason", "Evidence references"],
            "rows": [[a["keyword"], ", ".join(k for k, v in a.get("dimensions", {}).items() if v == "supported") or "uncertain",
                      a["reason"] + ('; provisional / uncertain: ' + '; '.join(g['reason'] for g in a.get('evidence_gaps', [])) if a['uncertain'] else ''), "; ".join(str(r.get("url") or r.get("source")) for r in a["sources"] + a.get('evidence_gaps', []))] for a in assessments]}

        kept = [[*row, a['category']] for row, a in zip(rows, assessments)
                if a['category'] in (BRANDED, RELEVANT, 'related_organization') and not a['uncertain']]
        uncertain_rows = [row for row, a in zip(rows, assessments) if a['uncertain']]
        confirmed_relevant = sum(a['category'] == RELEVANT and not a['uncertain'] for a in assessments)
        provisional_relevant = sum(a['category'] == RELEVANT and a['uncertain'] for a in assessments)
        kept.sort(key=lambda row: -(row[1] if isinstance(row[1], int) else 0))
        columns = data["table"]["columns"]
        data["table"] = {"columns": [*columns, "Relevance"], "rows": kept}
        data["unrelated"] = {"title": "Unrelated searches (not counted as opportunities)", "columns": columns, "rows": groups[UNRELATED],
                             "note": "These share a word with the site or its name but are not about what the site offers, by word matching "
                                     "against the brand name and the site's own titles, headings and descriptions. Check before discarding."}
        if uncertain_rows:
            data["ambiguous"] = {"title": "Ambiguous searches (insufficient context; not counted as opportunities)",
                                 "columns": columns, "rows": uncertain_rows,
                                 "note": "Context is insufficient or mixed. These rows are not counted as confirmed brand searches or opportunities."}
        data["relevance"] = {"branded": len(groups[BRANDED]), "relevant": len(groups[RELEVANT]), "unrelated": len(groups[UNRELATED]),
                             "confirmed_relevant": confirmed_relevant, "provisional_relevant": provisional_relevant,
                             "ambiguous": len(groups[AMBIGUOUS]), "related_organization": len(groups["related_organization"]),
                             "method": "lexical evidence from names, saved pages and ranking paths; not semantic proof; listed sample only",
                             "common_word_brand": common, **meta}
        counts[check_id] = data["relevance"]
        said = (f" Of the {len(rows)} listed, {len(groups[BRANDED])} name the brand, {confirmed_relevant} have supported topic matches and "
                f"{len(groups[UNRELATED])} look unrelated (shown separately)."
                + (f" Also listed: the bare word “{common}”, which is ambiguous and not counted."
                   if common and groups[AMBIGUOUS] and all(_tokens(str(r[0])) == [common] for r in groups[AMBIGUOUS]) else "")
                + f" Context review: {len(uncertain_rows)} uncertain (including {provisional_relevant} provisional topic matches) and {len(groups['related_organization'])} related-organization searches in this sample; no classification of provider totals."
                + " These are lexical/contextual estimates, not proof of search intent; review uncertain cases.")
        check["summary"] = check["summary"].split(" Of the ")[0] + said + (" " + warning if warning else "")
    listed = counts.get("DFS-4")
    _own_domain_left_out(by_id, domain, common, listed, warning)
    section["relevance"] = {"brand_words": sorted(names), "common_word_brand": common, "warning": warning, "site_words_used": len(vocabulary),
                            "sorted": True, **meta}
    section.update(qualify_section(section))
    return section


def _not_sorted(section: dict[str, Any], domain: str | None) -> None:
    """No brand name: DFS-4 and DFS-5 keep their plain table and say why; DFS-6 still loses the audited domain."""
    by_id = {check["check_id"]: check for check in section.get("checks") or []}
    for check_id in ("DFS-4", "DFS-5"):
        check = by_id.get(check_id)
        data = ((check or {}).get("evidence") or {}).get("data") or {}
        if not check or check.get("status") != "observed" or (data.get("table") or {}).get("rows") is None or data.get("relevance"):
            continue
        data["relevance"] = {"sorted": False, "brand_source": None, "brand_confirmed": False}
        if NOT_SORTED not in check["summary"]:
            check["summary"] = check["summary"].rstrip() + " " + NOT_SORTED
    _own_domain_left_out(by_id, domain, None, None, None)


def _own_domain_left_out(by_id: dict[str, Any], domain: str | None, common: str | None, listed: dict[str, int] | None,
                         warning: str | None) -> None:
    """DFS-6 without the audited domain itself, and labelled when its overlap may be a word, not a business."""
    rivals = by_id.get("DFS-6")
    data = ((rivals or {}).get("evidence") or {}).get("data") or {}
    rows = (data.get("table") or {}).get("rows")
    if rivals and rivals.get("status") == "observed" and rows is not None and "own_domain_removed" not in data:
        own = (domain or "").lower().removeprefix("www.")
        others = [row for row in rows if str(row[0]).lower().removeprefix("www.") != own and not str(row[0]).lower().endswith("." + own)]
        data["own_domain_removed"] = len(rows) - len(others)
        data["table"]["rows"] = others
        data["listed"] = len(others)
        rivals["summary"] = (f"{len(others)} other domain(s) listed that rank for the same keywords, of {panel._count(data.get('total_count'))} found. "
                             "The very largest sites (marketplaces, encyclopaedias) and the audited domain itself are left out.")
        if common or (listed and listed["unrelated"] * 2 >= sum(listed.get(k, 0) for k in GROUPS) > 0):
            data["possibly_generic_overlap"] = True
            rivals["summary"] += (" Possibly generic-word overlap: shared queries alone do not establish business competition. "
                                  "Review each domain and its overlapping queries; the keyword sample does not classify all provider totals." + (" " + warning if warning else ""))


def relevance_pages(reader, native):
    """Use captured native fallback only for URLs absent from the reader sample. Never fetch here."""
    selected = list(reader or [])
    seen = {p.url.rstrip('/') for p in selected}
    return selected + [p for p in native if p.analysis and p.url.rstrip('/') not in seen
                       and (not hasattr(p, 'readable_document') or p.readable_document())]


def ranking_landing_pages(section, origin, max_pages):
    """Bounded priority candidates from the approved provider sample, never relevance evidence.

    No requests here. Reader guards, robots, page/request/credit limits remain authoritative.
    Home/key pages retain precedence; at most a third of reader slots (maximum ten) are prioritized.
    """
    from ..urls import normalize_url, non_page_kind, same_origin
    candidates = {}
    for check in (section or {}).get('checks') or []:
        if check.get('check_id') not in ('DFS-4', 'DFS-5') or check.get('status') != 'observed':
            continue
        data = (check.get('evidence') or {}).get('data') or {}
        for row in (data.get('provider_table') or data.get('table') or {}).get('rows') or []:
            if len(row) < 4:
                continue
            url = normalize_url(str(row[3] or ''))
            parts = urlsplit(url or '')
            try:
                port = parts.port
            except ValueError:
                continue
            if not url or parts.scheme not in ('http', 'https') or parts.username or parts.password or port not in (None, 80, 443):
                continue
            if not same_origin(url, origin) or non_page_kind(url):
                continue
            volume = row[1] if isinstance(row[1], (int, float)) else 0
            if parts.path in ('', '/'):
                continue  # the homepage already has the first reader slot
            # Near-page-one sample first, then estimated demand. This chooses evidence to collect,
            # not relevance or commercial value; deduplicate a page shared by several queries/panels.
            priority = (0 if check['check_id'] == 'DFS-5' else 1, -volume)
            candidates[url] = min(candidates.get(url, priority), priority)
    limit = min(10, max(0, max_pages // 3))
    return sorted(candidates, key=lambda u: (*candidates[u], u))[:limit]


def refresh_relevance(section):
    """Restore original provider rows before reassessing with the final saved-page coverage."""
    import copy
    for check in (section or {}).get('checks') or []:
        data = (check.get('evidence') or {}).get('data') or {}
        if data.get('provider_table'):
            data['table'] = copy.deepcopy(data['provider_table'])
            for key in ('relevance', 'ambiguous', 'unrelated', 'keyword_assessments', 'intent_dimensions', 'opportunity_evidence', 'editorial_opportunities'):
                data.pop(key, None)


def qualified_opportunity_data(data):
    """Derive recommendations from saved assessment evidence, never stale display flags.

    Pure read-time adapter for older reports too: no reclassification, requests or source mutation.
    Provider rows and dimensional assessments remain intact. Editorial matches are not sales proof.
    """
    if not isinstance(data, dict):
        return data
    if not isinstance(data.get('keyword_assessments'), list):
        result = dict(data)
        result['opportunity_evidence'] = {r[0]:False for r in ((data.get('provider_table') or data.get('table') or {}).get('rows') or []) if r}
        return result
    assessments = data['keyword_assessments']
    result = dict(data)
    table = data.get('provider_table') or data.get('table') or {}
    rows = table.get('rows') or []
    by_query = {}
    for row in rows:
        if row:
            by_query.setdefault(row[0], []).append(row)

    def evidence_for(row):
        records = [a for a in assessments if a.get('keyword') == row[0]]
        linked = [a for a in records if len(row) > 3 and a.get('ranking_url') == row[3] and row[3]]
        # An older assessment without URL identity may qualify only a unique landing row.
        if not linked and len(by_query[row[0]]) == 1 and not any(a.get('ranking_url') for a in records):
            linked = records
        return linked

    result['opportunity_evidence'] = {}
    for query, candidates in by_query.items():
        supported = [evidence_for(row) for row in candidates]
        result['opportunity_evidence'][query] = all(records and all(a.get('uncertain') is False and
            a.get('dimensions', {}).get('editorial_relevance') != 'supported' for a in records)
            for records in supported)
    editorial_rows = [row[:4] for row in rows if row and evidence_for(row) and
        all(a.get('uncertain') is False and a.get('dimensions', {}).get('editorial_relevance') == 'supported'
            for a in evidence_for(row))]
    result.pop('editorial_opportunities', None)
    if editorial_rows:
        result['editorial_opportunities'] = {'title': 'Editorial topic matches (commercial value not established)',
            'columns': table.get('columns', [])[:4], 'rows': editorial_rows,
            'note': 'Ranking and search volume do not establish sales intent or conversion value.'}
    return result


def keyword_counts(data):
    """Captured records, unique queries and disjoint decisions; display dimensions may overlap."""
    rows=(data.get('provider_table') or data.get('table') or {}).get('rows') or []
    unique={tuple(str(v) for v in r[:4]) for r in rows if r}
    assessments=data.get('keyword_assessments') or []
    key=lambda a:(a.get('keyword'),a.get('ranking_url'))
    assessed={key(a) for a in assessments if a.get('uncertain') is False}
    dims=('brand_identity','related_organization','service_relevance','local_relevance','editorial_relevance')
    supported={key(a) for a in assessments if a.get('uncertain') is False and any(a.get('dimensions',{}).get(d)=='supported' for d in dims)}
    editorial={key(a) for a in assessments if a.get('uncertain') is False and a.get('dimensions',{}).get('editorial_relevance')=='supported'}
    commercial={key(a) for a in assessments if a.get('uncertain') is False and any(a.get('dimensions',{}).get(d)=='supported' for d in ('brand_identity','service_relevance','local_relevance')) and a.get('dimensions',{}).get('editorial_relevance')!='supported'}
    unrelated={key(a)for a in assessments if a.get('uncertain') is False and a.get('dimensions',{}).get('unrelated_intent')=='supported'}
    related={key(a)for a in assessments if a.get('uncertain') is False and a.get('dimensions',{}).get('related_organization')=='supported'}
    identities={(r[0],r[3] if len(r)>3 else None) for r in rows if r}
    return {'provider_records':len(rows),'unique_provider_records':len(unique),'unique_queries':len({r[0]for r in rows if r}),
            'confirmed_relevant_records':len(identities & supported),'confirmed_commercial_candidates':len(identities & commercial),
            'editorial_matches':len(identities & editorial),'unrelated_records':len(identities & unrelated),
            'related_organization_records':len(identities & related),'uncertain_candidates':len(identities-assessed),
            'intent_classification_rows':len((data.get('intent_dimensions')or{}).get('rows')or[]),
            'provider_total':data.get('total_count'),'scope':'captured sample only; dimensions overlap, never summed into unique totals'}


def qualify_section(section):
    from copy import deepcopy
    out=deepcopy(section)
    for check in out.get('checks',[]):
        if check.get('check_id') not in ('DFS-4','DFS-5'):continue
        data = (check.get('evidence') or {}).get('data')
        # Refused/not-requested panels have no measurement, not a zero-row result.
        if not isinstance(data, dict):
            continue
        d=data;d.update(qualified_opportunity_data(d));d['record_counts']=keyword_counts(d)
        check['summary']=check.get('summary','').replace('These are the nearest to more visits: improve the ranking page for each.', 'These are ranking candidates, not confirmed business opportunities; assess relevance, evidence and intended value before recommending page changes.')
        check['evidence']['data']=d
    return out
