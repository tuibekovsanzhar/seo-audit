"""Business types ("İşletme türü"), v0.3 stage 4 (DECISIONS 311).

One profile per kind of business (`profiles/*.json`): its page types in order of importance, each with the signals
that recognise it. A profile changes three things, and nothing else:

- *Page type for the business* (`business_page_type`) on every page the page grouping scored (DECISIONS 297): from
  the address, the structured-data types, the title and headings, the menu and link text pointing to the page and a
  few content signals; else from the general page type (Stage 3). The Stage 3 `page_type` is kept as it is.
- *Importance*: 50% the profile weight of that page type + 35% the internal link score + 15% the click-depth score
  (`FORMULA`), with Stage 3's caps. The Stage 3 value stays in `importance_links`. "Diğer" keeps Stage 3's importance
  exactly (`importance_source` "links").
- *Key pages* and the "not found among the pages read" notes for the profile's top page types.

Rule-based and Estimated. No request is sent. No check, severity, confidence or release-gate decision reads any of it;
importance orders cards (reach) and key pages only. The suggestion (`suggest`) is a hint the person confirms or changes.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from importlib import resources
from typing import Iterable
from urllib.parse import unquote, urlsplit

from ..page_words import fold

# 2 (DECISIONS 316): "Havayolu" split from "Seyahat / rezervasyon" (now "Tur / otel"), and country-language folders
# left out of address words; a saved suggestion of version 1 is worked out again.
# 3 (DECISIONS 347): product and category pages among the pages read count for E-ticaret.
VERSION = 3
AUTO = "auto"
DEFAULT = "diger"
# Weights by rank in a profile's list (owner, configurable here or per profile with "weights").
RANK_WEIGHTS = (100, 85, 70, 55, 40, 30)
# DECISIONS 324 (owner, 2026-11-08): a homepage the sector list ranks takes its rank's weight, as the team's sector
# method does (E-ticaret 70, Sağlık 55, Ev hizmetleri 55); a homepage added where the list has none is ADDED_HOME.
ADDED_HOME = 85
GUIDE_WEIGHT = 30        # "Rehber / SSS / blog" where a profile has no guide of its own (owner)
UNMATCHED_WEIGHT = 25    # a page that matches no type of the profile (agent default)
POLICY_WEIGHT = 15       # as Stage 3
UTILITY_WEIGHT = 0       # as Stage 3
FORMULA = {"page_type": 0.5, "internal_link_score": 0.35, "click_depth": 0.15}  # owner, 2026-11-05
# Points per kind of signal; each kind counts once per page type. A type needs MIN_SCORE (agent defaults). The
# address weighs most: it names the page; FAQ markup or a section heading only says what a part of it holds.
SCORES = {"url": 4, "schema": 3, "heading": 2, "menu": 2, "content": 1,
          # DECISIONS 329: a person's own profile page names what the page is more surely than a word inside its address
          # ("/team/klinik-psikolog-…" is a psychologist, not a clinic), so it outweighs an address word.
          "person": 5}
MIN_SCORE = 3
NOT_FOUND_TOP = 3        # "not found" notes for the profile's first three page types (owner)
# DECISIONS 347 (owner, atasunoptik: "suggest E-ticaret when product/category signals are strong instead of Diğer"):
# product and category pages (the general page type) at least this share of the pages typed, and this many, add
# TYPES_SCORE to the profiles whose "suggest" names them (`page_types`; E-ticaret only) (agent defaults).
TYPES_SHARE = 0.3
TYPES_MIN = 5
TYPES_SCORE = 4
GROUPS = {"finans": {"tr": "Finans", "en": "Finance"},
          "seyahat": {"tr": "Seyahat / rezervasyon", "en": "Travel / booking"}}  # DECISIONS 316
KIND_LABELS = {"url": {"tr": "adres sözcüğü", "en": "address word"},
               "schema": {"tr": "yapısal veri türü", "en": "structured-data type"},
               "heading": {"tr": "başlık sözcüğü", "en": "heading word"},
               "menu": {"tr": "menü veya bağlantı metni", "en": "menu or link text"},
               "content": {"tr": "içerik işareti", "en": "content signal"},
               "person": {"tr": "kişi profili", "en": "a person's profile"}}
CONTENT_SIGNALS = {
    "form": "a form that is not search, sign-in, cart or newsletter",
    "price": "price markup (Offer, PriceSpecification) or a price word in a heading",
    "map": "an embedded map or GeoCoordinates",
    "calculator": "a 'hesapla' / 'calculate' button or heading",
    "faq": "FAQPage markup or three or more question headings",
    "table": "a data table",
    "list": "the general page type is a listing (category)",
    "person": "a person's own profile page (DECISIONS 329): not an article; its main heading is a name, with Person or "
              "Physician markup, a professional title right before the name (title, description, address), or CV "
              "headings (education, areas of expertise)",
}
# DECISIONS 329 (owner, after moodist 2d72fea0: psychologists' profiles typed "Klinik ve konum"). Professional titles,
# folded; a profile names its person with one of them right before the name somewhere on the page.
PERSON_TITLES = ("prof", "doc", "dr", "uzm", "op", "dt", "psk", "uzman", "doktor", "hekim", "dis hekimi", "psikolog",
                 "psikiyatrist", "psikoterapist", "terapist", "pedagog", "diyetisyen", "fizyoterapist", "hemsire", "ebe",
                 "odyolog", "ergoterapist", "psikolojik danisman", "avukat", "doctor", "md", "psychologist",
                 "psychiatrist", "psychotherapist", "therapist", "physician", "dietitian", "nurse", "dentist", "surgeon",
                 "attorney", "lawyer")
CV_HEADINGS = ("egitim", "egitim bilgileri", "uzmanlik alanlari", "uzmanlik alanlarim", "ozgecmis", "ayrintili ozgecmis",
               "deneyim", "is deneyimi", "yayinlar", "sertifikalar", "education", "areas of expertise", "expertise",
               "specialties", "biography", "experience", "publications", "certifications")
# Words that make a heading a page's subject, not a person's name ("Ketamin İnfüzyon Tedavisi", "Our Team").
_NOT_A_NAME = re.compile(r"^(tedavi|merkez|birim|bolum|klinig|klinik$|hastane|hizmet|ekib|ekip|kadro|hakkimiz|iletisim|"
                         r"bize|team|our|about|contact|blog|haber|sss|bozuklu|bagimli|terapi|test|servis|poliklinik|"
                         r"departman|center|centre|unit|service|treatment|clinic|hospital|doctors|staff|news|sayfa|nedir|"
                         r"nasil|icin|ve$|ile$|the$|of$|and$|for$|with$)")
ARTICLE_TYPES = frozenset({"Article", "BlogPosting", "NewsArticle", "ScholarlyArticle", "TechArticle", "Report",
                           "LiveBlogPosting"})
# On an article page these are its publisher, its author or the place that publishes it, not what the page is about
# (moodist: every blog post carries the hospital's Hospital markup, which typed 28 posts "Klinik ve konum").
PUBLISHER_TYPES = frozenset({"Organization", "Corporation", "LocalBusiness", "Hospital", "MedicalClinic",
                             "MedicalOrganization", "MedicalBusiness", "Dentist", "Physician", "Person", "Place",
                             "Store", "Restaurant", "AutoDealer", "AutoRepair", "AutomotiveBusiness", "LodgingBusiness",
                             "Hotel", "Resort", "FinancialService", "BankOrCreditUnion"})
SPECIAL = {"home": {"tr": "Ana sayfa", "en": "Homepage"}, "policy": {"tr": "Politika / yasal", "en": "Policy / legal"},
           "utility": {"tr": "Arama, sepet, hesap", "en": "Search, cart, account"},
           "other": {"tr": "Diğer sayfa", "en": "Other page"}}
POLICY_FOOTER_ONLY = "policy page linked only from footers or sitewide blocks"


# ---------------------------------------------------------------- profiles

def _norm(text: str) -> str:
    """Folded, every run of non-letters one space: "Kredi-Kartı" and "kredi karti" are the same words."""
    return re.sub(r"[^0-9a-z]+", " ", fold(text)).strip()


@lru_cache(maxsize=1)
def profiles() -> dict[str, dict]:
    """{id: profile} in the order of the files' "order"; each page type with its rank and weight."""
    folder = resources.files(__package__) / "profiles"
    out = []
    for entry in folder.iterdir():
        if entry.name.endswith(".json"):
            out.append(json.loads(entry.read_text(encoding="utf-8")))
    out.sort(key=lambda p: p.get("order", 999))
    result = {}
    for p in out:
        weights = tuple(p.get("weights") or RANK_WEIGHTS)
        rank = 0
        types = []
        for t in p.get("page_types") or []:
            t = dict(t)
            if t.get("added"):
                t["rank"] = None
                t["weight"] = ADDED_HOME if t["id"] == "home" else int(t.get("weight", GUIDE_WEIGHT))
            else:
                rank += 1
                t["rank"] = rank
                t["weight"] = int(t.get("weight", weights[min(rank, len(weights)) - 1]))
            t.setdefault("signals", {})
            t.setdefault("generic", [])
            types.append(t)
        result[p["id"]] = {**p, "page_types": types}
    return result


def profile(pid: str | None) -> dict:
    return profiles().get(pid or DEFAULT) or profiles()[DEFAULT]


def label(pid: str | None, lang: str = "tr") -> str:
    return profile(pid)["label"].get(lang) or profile(pid)["label"]["tr"]


def choices(lang: str = "tr") -> list[dict]:
    """For a dropdown: [{id, label, group, group_label}], finance grouped (owner)."""
    return [{"id": p["id"], "label": p["label"].get(lang, p["label"]["tr"]), "group": p.get("group"),
             "group_label": (GROUPS.get(p.get("group") or "") or {}).get(lang)} for p in profiles().values()]


def type_label(pid: str | None, type_id: str | None, lang: str = "tr") -> str | None:
    if not type_id:
        return None
    for t in profile(pid)["page_types"]:
        if t["id"] == type_id:
            return t["label"].get(lang) or t["label"]["tr"]
    return (SPECIAL.get(type_id) or {}).get(lang)


def valid(pid: str | None) -> bool:
    return pid in (None, AUTO) or pid in profiles()


# ---------------------------------------------------------------- what a page shows

def _segments(url: str, folders: Iterable[str] = ()) -> list[str]:
    """The address's words by segment, its language folder left out: a plain one (/en) always, a country-language one
    (/global-en, /tur-tr) when the site's locale folders (`locales.detect`) name it (DECISIONS 316: "tur" in /tur-en/
    is Turkey, not a tour)."""
    from ..page_groups import is_locale
    segs = [unquote(s) for s in urlsplit(url).path.split("/") if s]
    if segs and (is_locale(segs[0]) or segs[0].lower() in set(folders)):
        segs = segs[1:]
    return [_norm(s.rsplit(".", 1)[0] if s.endswith((".html", ".htm", ".php", ".aspx")) else s) for s in segs]


def url_depth(word: str, segs: list[str]) -> int | None:
    """The index of the segment `word` matches in (`url_hit`'s rules), or None. On a tie between two page types the
    deeper match names the page (DECISIONS 315: /collections/c/products/p is a product, not a collection)."""
    if word.endswith("/*"):
        w = _norm(word[:-2])
        return next((i for i, s in enumerate(segs[:-1]) if s == w), None)
    if word.endswith("/"):
        return len(segs) - 1 if segs and segs[-1] == _norm(word[:-1]) else None
    w = _norm(word)
    return next((i for i, s in enumerate(segs) if w and f" {w} " in f" {s} "), None) if w else None


def url_hit(word: str, segs: list[str]) -> bool:
    """`word`: any segment holds the word(s); `word/*`: a segment is the word and another follows it (an item);
    `word/`: the last segment is the word (the list page itself)."""
    if word.endswith("/*"):
        w = _norm(word[:-2])
        return any(s == w for s in segs[:-1])
    if word.endswith("/"):
        return bool(segs) and segs[-1] == _norm(word[:-1])
    w = _norm(word)
    return bool(w) and any(f" {w} " in f" {s} " for s in segs)


def _has(words: Iterable[str], text: str) -> list[str]:
    padded = f" {text} "
    return [w for w in words if _norm(w) and f" {_norm(w)} " in padded]


_SKIP_FORMS = re.compile(r"search|arama|(?<![a-z])ara(?![a-z])|newsletter|bulten|subscribe|abone|login|giris|signin|"
                         r"cart|sepet|checkout|localization|currency|language|dil")


def content_signals(analysis: dict, generic: str | None = None) -> set[str]:
    out = set()
    a = analysis or {}
    types = set((a.get("structured_data") or {}).get("types") or [])
    forms = [x for x in a.get("form_actions") or [] if x is not None and not _SKIP_FORMS.search(fold(x))]
    if forms:
        out.add("form")
    heads = " ".join(h.get("text") or "" for h in a.get("headings") or [] if isinstance(h, dict))
    if types & {"Offer", "AggregateOffer", "PriceSpecification", "UnitPriceSpecification"} or re.search(
            r"(?<![a-z])(fiyat|fiyatlar|price|prices|pricing)(?![a-z])|₺", fold(heads)):
        out.add("price")
    if "GeoCoordinates" in types or any(re.search(r"google\.[a-z.]+/maps|maps\.google|yandex\.[a-z.]+/map|/maps/embed",
                                                  (f.get("src") or "")) for f in a.get("iframes") or [] if isinstance(f, dict)):
        out.add("map")
    buttons = " ".join((b.get("text") or "") for b in (a.get("buttons") or []) + (a.get("input_buttons") or [])
                       if isinstance(b, dict))
    if re.search(r"hesapla|calculat", fold(buttons + " " + heads)):
        out.add("calculator")
    if "FAQPage" in types or sum(1 for h in a.get("headings") or [] if isinstance(h, dict)
                                 and (h.get("text") or "").strip().endswith("?")) >= 3:
        out.add("faq")
    if a.get("tables"):
        out.add("table")
    if generic == "category":
        out.add("list")
    return out


# A structured-data type on at least this share of the pages read (and this many pages) is a site builder's default,
# not a sign of what one page is (adile: Article on 35 of 36 pages); as Stage 3 treats a sitewide og:type=article.
SITEWIDE_SCHEMA_SHARE = 0.5
SITEWIDE_SCHEMA_MIN_PAGES = 4


def sitewide_schema(analyses: Iterable[dict | None]) -> set[str]:
    rows = [set(((a or {}).get("structured_data") or {}).get("types") or []) for a in analyses]
    if len(rows) < SITEWIDE_SCHEMA_MIN_PAGES:
        return set()
    counts = Counter(t for row in rows for t in row)
    return {t for t, n in counts.items() if n / len(rows) >= SITEWIDE_SCHEMA_SHARE}


_TITLE_TOKENS = frozenset(w for t in PERSON_TITLES for w in t.split()) | {"klinik"}


def _texts(a: dict, key: str) -> list[str]:
    value = (a or {}).get(key) or {}
    return [x for v in value.values() for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)] \
        if isinstance(value, dict) else []


def name_in(heading: str) -> list[str] | None:
    """The folded name a main heading holds ("Uzm. Dr. Merve Gümüşay" -> ["merve", "gumusay"]), or None when the heading
    does not read as a person's name: 2 to 5 words after the titles, each starting with a capital letter, no digits, no
    question, none of them a word that names a subject (treatment, centre, team ...)."""
    text = (heading or "").strip()
    if not text or len(text) > 60 or any(ch.isdigit() for ch in text) or any(ch in text for ch in "?:!|"):
        return None
    words = [w for w in re.split(r"[\s,]+", text) if w]
    while words and _norm(words[0]) in _TITLE_TOKENS | {""}:
        words.pop(0)
    if not 2 <= len(words) <= 5:
        return None
    out = []
    for w in words:
        n = _norm(w)
        letters = re.sub(r"[.'’-]", "", w)
        if not n or " " in n or not letters.isalpha() or not w[0].isupper() or _NOT_A_NAME.match(n):
            return None
        out.append(n)
    return out


def person_profile(url: str, analysis: dict | None, types: set[str], generic: str | None = None) -> bool:
    """DECISIONS 329: a page about one person (a doctor's, a psychologist's profile). Not an article (a post names its
    author); its H1 (else its title before " - ") reads as a name; and one of: Person or Physician markup, a professional
    title right before that name in the title, the descriptions, the image text or the address ("Klinik Psikolog Merve
    Ceren Safak"), or two or more CV headings (education, areas of expertise, biography)."""
    a = analysis or {}
    if types & ARTICLE_TYPES or generic in ("blog_article", "home", "utility", "policy", "category"):
        return False
    h1 = next((h.get("text") or "" for h in a.get("h1_elements") or [] if isinstance(h, dict) and h.get("text")), "")
    name = name_in(h1) or name_in(re.split(r"\s+[-–|·]\s+", a.get("title") or "")[0])
    if not name:
        return False
    if types & {"Person", "Physician"}:
        return True
    tail = " ".join(name[-2:])
    titles = "|".join(re.escape(t) for t in sorted(PERSON_TITLES, key=len, reverse=True))
    near = re.compile(rf"(?<![a-z0-9])(?:{titles})\s+(?:[a-z0-9]+\s+){{0,2}}{re.escape(tail)}(?![a-z0-9])")
    texts = [h1, a.get("title") or "", *_texts(a, "meta"), *_texts(a, "og"), " ".join(_segments(url))]
    if any(near.search(_norm(t)) for t in texts if t):
        return True
    heads = {_norm(h.get("text") or "").rstrip(" :") for h in a.get("headings") or [] if isinstance(h, dict)}
    return sum(1 for h in heads if h in CV_HEADINGS) >= 2


def location_types(pid: str | None) -> frozenset[str]:
    """DECISIONS 329: the profile's page types that are places of the business (clinic, branch, store, dealer, service
    area: `"location": true`); empty for a profile with none (banking, SaaS ...)."""
    return frozenset(t["id"] for t in profile(pid)["page_types"] if t.get("location"))


def page_facts(url: str, analysis: dict | None, menu: Iterable[str] = (), generic: str | None = None,
               sitewide: set[str] = frozenset(), folders: Iterable[str] = ()) -> dict:
    a = analysis or {}
    # The page's own name: its title and H1. Lower headings name sections (an FAQ block on a product page).
    heads = [a.get("title") or ""] + [h.get("text") or "" for h in a.get("h1_elements") or [] if isinstance(h, dict)]
    schema = set((a.get("structured_data") or {}).get("types") or []) - set(sitewide)
    if schema & ARTICLE_TYPES:  # DECISIONS 329: an article's publisher and author are not what the page is about
        schema -= PUBLISHER_TYPES
    content = content_signals(a, generic) if a else ({"list"} if generic == "category" else set())
    if a and person_profile(url, a, set((a.get("structured_data") or {}).get("types") or []) - set(sitewide), generic):
        content = content | {"person"}
    return {"url": url, "segments": _segments(url, folders), "generic": generic, "schema": schema,
            "heading": _norm(" | ".join(heads)), "menu": _norm(" | ".join(menu)), "content": content}


def link_texts(pages: Iterable[tuple[str, list]]) -> dict[str, list[str]]:
    """{target: anchor texts of the links to it} over the pages read ((url, outlinks) pairs)."""
    out: dict[str, list[str]] = {}
    for _, outlinks in pages:
        for edge in outlinks or []:
            target = (edge.get("target") or "").split("#")[0]
            anchors = edge.get("anchors") or ([edge["anchor"]] if edge.get("anchor") else [])
            if target and anchors:
                out.setdefault(target, []).extend(a for a in anchors if a)
    return out


# ---------------------------------------------------------------- one page

def match(t: dict, facts: dict) -> tuple[int, list[dict]]:
    """(score, signals that matched) for one page type."""
    s = t.get("signals") or {}
    hits = []
    url = next((w for w in s.get("url") or [] if url_hit(w, facts["segments"])), None)
    if url:
        hits.append({"kind": "url", "value": url, "depth": url_depth(url, facts["segments"])})
    schema = sorted(set(s.get("schema") or []) & facts["schema"])
    if schema:
        hits.append({"kind": "schema", "value": schema[0]})
    head = _has(s.get("words") or [], facts["heading"])
    if head:
        hits.append({"kind": "heading", "value": head[0]})
    menu = _has(s.get("words") or [], facts["menu"])
    if menu:
        hits.append({"kind": "menu", "value": menu[0]})
    wanted = set(s.get("content") or [])
    if "person" in wanted and "person" in facts["content"]:  # DECISIONS 329
        hits.append({"kind": "person", "value": "person"})
    content = sorted((wanted - {"person"}) & facts["content"])
    if content:
        hits.append({"kind": "content", "value": content[0]})
    return sum(SCORES[h["kind"]] for h in hits), hits


def classify(prof: dict, facts: dict) -> tuple[str, str, list[dict]]:
    """(business page type, basis, signals). Order: homepage, utility, a policy page (to the profile's type that takes
    policies, else policy), the best profile match of MIN_SCORE or more, the profile type of the general page type,
    else "other"."""
    generic = facts.get("generic")
    types = [t for t in prof["page_types"] if t["id"] != "home"]
    if generic == "home":
        return "home", "the homepage (page grouping)", []
    if generic == "utility":
        return "utility", "a search, cart or account page (page grouping)", []
    if generic == "policy":
        claim = next((t for t in types if "policy" in t["generic"]), None)
        if claim:
            return claim["id"], "a policy or legal page (page grouping), which this business type counts here", []
        return "policy", "a policy or legal page (page grouping)", []
    best = None

    def depth(hits):
        return max((h.get("depth") or 0 for h in hits if h["kind"] == "url"), default=-1)
    for t in types:
        score, hits = match(t, facts)
        if score >= MIN_SCORE and (best is None or score > best[0] or (
                score == best[0] and (depth(hits), -(t["rank"] or 99)) > (depth(best[2]), -(best[1]["rank"] or 99)))):
            best = (score, t, hits)
    if best:
        return best[1]["id"], f"signals scored {best[0]}", best[2]
    fallback = next((t for t in types if generic and generic in t["generic"]), None)
    if fallback:
        return fallback["id"], f"the general page type '{generic}' (page grouping)", []
    return "other", "no signal of this business type", []


def weight(prof: dict, type_id: str) -> int:
    if type_id == "home":
        home = next((t for t in prof["page_types"] if t["id"] == "home"), None)
        return home["weight"] if home else ADDED_HOME
    if type_id == "policy":
        return POLICY_WEIGHT
    if type_id == "utility":
        return UTILITY_WEIGHT
    t = next((t for t in prof["page_types"] if t["id"] == type_id), None)
    return t["weight"] if t else UNMATCHED_WEIGHT


# ---------------------------------------------------------------- importance over the records

_KEYS = ("business_page_type", "business_page_type_basis", "business_signals", "business_citable")


def reset(g: dict) -> None:
    """Stage 3's own importance back (a record the engine re-scored under another profile)."""
    if "importance_links" in g:
        g["importance"] = g.pop("importance_links")
    if "importance_rank_links" in g:
        g["importance_rank"] = g.pop("importance_rank_links")
    parts = g.get("importance_parts")
    if isinstance(parts, dict):
        g["importance_parts"] = {k: v for k, v in parts.items() if k not in ("profile_weight", "formula")}
    for k in _KEYS:
        g.pop(k, None)
    g["importance_source"] = "links"


def apply(records: dict[str, dict], facts: dict[str, dict], pid: str | None, folders: Iterable[str] = ()) -> dict:
    """Re-score `records` ({url: grouping record}, changed in place) for profile `pid`; Stage 3's importance and rank
    are kept in `importance_links` / `importance_rank_links`. "Diğer" (or no profile) leaves Stage 3's values.
    Returns the summary for the report."""
    prof = profile(pid)
    scored = {u: g for u, g in records.items() if isinstance(g, dict) and "importance" in g}
    for g in scored.values():
        reset(g)
    if prof["id"] == DEFAULT:
        return {"profile": DEFAULT, "version": VERSION, "importance": "page grouping (DECISIONS 297): "
                "50% link score, 25% click depth, 25% general page type"}
    counts: Counter = Counter()
    for url, g in scored.items():
        f = facts.get(url) or page_facts(url, None, (), g.get("page_type"), folders=folders)
        if f.get("generic") is None:
            f = {**f, "generic": g.get("page_type")}
        kind, basis, signals = classify(prof, f)
        w = weight(prof, kind)
        parts = g.get("importance_parts") or {}
        link, depth = parts.get("internal_link_score") or 0, parts.get("click_depth") or 0
        value = (FORMULA["page_type"] * w + FORMULA["internal_link_score"] * link + FORMULA["click_depth"] * depth)
        capped = parts.get("capped")
        cap = 35 if capped == POLICY_FOOTER_ONLY else 20
        g["importance_links"] = g["importance"]
        g["importance_rank_links"] = g.get("importance_rank")
        g["importance"] = min(round(value), cap) if capped else round(value)
        g["importance_parts"] = {**parts, "profile_weight": w, "formula": dict(FORMULA)}
        g["importance_source"] = f"profile:{prof['id']}"
        g["business_page_type"] = kind
        g["business_page_type_basis"] = basis
        g["business_signals"] = signals
        t = next((t for t in prof["page_types"] if t["id"] == kind), None)
        g["business_citable"] = bool(t and t.get("citable"))
        if g.get("read") is not False:
            counts[kind] += 1

    from ..page_groups import home_first
    home_first(scored)  # DECISIONS 347: the homepage is the most important page under every profile too

    def order(item):
        url, g = item
        tb = g.get("tie_break") or {}
        pos = tb.get("sitemap_position")
        return (g.get("page_type") != "home", -g["importance"], -(tb.get("body_inlinks") or 0), -(tb.get("products_listed") or 0),
                pos if pos is not None else float("inf"), g.get("importance_rank_links") or 10**9)
    for i, (url, g) in enumerate(sorted(scored.items(), key=order), 1):
        g["importance_rank"] = i
    return {"profile": prof["id"], "version": VERSION, "formula": dict(FORMULA),
            "importance": "50% profile weight of the page type + 35% internal link score + 15% click-depth score; "
                          "Stage 3's caps (not indexable or utility 20, footer-only policy 35)",
            "weights": {t["id"]: t["weight"] for t in prof["page_types"]} | {
                "home": weight(prof, "home"), "other": UNMATCHED_WEIGHT, "policy": POLICY_WEIGHT,
                "utility": UTILITY_WEIGHT},
            "pages_by_type": dict(counts.most_common())}


def not_found(records: dict[str, dict], pid: str | None, top: int = NOT_FOUND_TOP) -> list[dict]:
    """The profile's first `top` page types (by rank) that no page read was typed as: [{type, label{tr,en}, rank}].
    "Not found among the pages read", never "missing on the site"."""
    prof = profile(pid)
    if prof["id"] == DEFAULT:
        return []
    seen = {g.get("business_page_type") for g in records.values() if isinstance(g, dict) and g.get("read") is not False}
    out = []
    for t in sorted((t for t in prof["page_types"] if t.get("rank")), key=lambda t: t["rank"])[:top]:
        if t["id"] not in seen:
            out.append({"type": t["id"], "label": t["label"], "rank": t["rank"]})
    return out


# ---------------------------------------------------------------- suggestion

def suggest(home_analysis: dict | None, home_outlinks: list | None, platform: str | None,
            urls: Iterable[str] = (), folders: Iterable[str] = (), types: dict | None = None) -> dict:
    """{id, label, reason{tr,en}, signals, scores}: the business type the homepage's structured data, the platform,
    the site's addresses, the homepage's menu and the general page types of the pages read (`types`: {type: pages},
    DECISIONS 347) point to; "diger" when no type stands out."""
    typed = {k: v for k, v in (types or {}).items() if k not in ("home", "utility", "policy") and isinstance(v, int)}
    shop_pages = typed.get("product", 0) + typed.get("category", 0)
    shop = shop_pages >= TYPES_MIN and shop_pages / (sum(typed.values()) or 1) >= TYPES_SHARE
    a = home_analysis or {}
    schema = set((a.get("structured_data") or {}).get("types") or [])
    menu = _norm(" | ".join(x for e in home_outlinks or [] if e.get("nav")
                            for x in (e.get("anchors") or ([e.get("anchor")] if e.get("anchor") else [])) if x))
    # One address per page: the same page in 20 country folders is one page, not 20 (DECISIONS 316).
    from ..locales import page_key
    folders = tuple(folders)
    paths = [_segments(u, folders) for u in dict.fromkeys(u for u in urls if isinstance(u, str))]
    if folders:
        seen_keys: set[str] = set()
        paths = []
        for u in dict.fromkeys(u for u in urls if isinstance(u, str)):
            k = page_key(u, folders)
            if k not in seen_keys:
                seen_keys.add(k)
                paths.append(_segments(u, folders))
    total = len(paths) or 1
    rows = []
    for p in profiles().values():
        s = p.get("suggest") or {}
        if p["id"] == DEFAULT:
            continue
        score, signals = 0.0, []
        found = sorted(set(s.get("schema") or []) & schema)
        if found:
            score += 4
            signals.append({"kind": "schema", "values": found[:3]})
        if platform and platform in (s.get("platforms") or []):
            score += 4
            signals.append({"kind": "platform", "values": [platform]})
        hit_words: Counter = Counter()
        n = 0
        for segs in paths:
            words = [w for w in s.get("url") or [] if url_hit(w, segs)]
            if words:
                n += 1
                hit_words[words[0]] += 1
        if n and n / total >= 0.1:      # a tenth of the site's addresses or more
            score += 4
        elif n >= 3 or (n and n / total >= 0.05):
            score += 3
        elif n:
            score += 1
        if n:
            signals.append({"kind": "urls", "count": n, "values": [w for w, _ in hit_words.most_common(2)]})
        if s.get("routes"):
            found_routes = iata_routes(paths)
            if len(found_routes) >= ROUTES_MIN:
                score += 3
                signals.append({"kind": "routes", "count": len(found_routes), "values": found_routes[:2]})
        words = _has(s.get("words") or [], menu)
        if words:
            score += min(4, len(words))
            signals.append({"kind": "menu", "values": words[:3]})
        if shop and s.get("page_types"):  # the profile's own "suggest.page_types" (E-ticaret: product, category)
            score += TYPES_SCORE
            signals.append({"kind": "types", "count": shop_pages,
                            "values": [f"{k} {typed[k]}" for k in ("product", "category") if typed.get(k)]})
        rows.append((score, p["order"], p["id"], signals))
    rows.sort(key=lambda r: (-r[0], r[1]))
    scores = {r[2]: r[0] for r in rows}
    best = rows[0] if rows else None
    second = rows[1][0] if len(rows) > 1 else 0
    if best and best[0] >= 4 and best[0] - second >= 1:
        return {"id": best[2], "label": profile(best[2])["label"], "reason": _reason(best[3]), "signals": best[3],
                "scores": scores, "version": VERSION}
    near = best[2] if best and best[0] > 0 else None
    reason = {"tr": "Net bir işaret yok" + (f" (en yakın: {label(near, 'tr')})" if near else ""),
              "en": "No clear signal" + (f" (closest: {label(near, 'en')})" if near else "")}
    return {"id": DEFAULT, "label": profile(DEFAULT)["label"], "reason": reason, "signals": best[3] if best and near else [],
            "scores": scores, "version": VERSION}


# An airline's route pages name two airports (/flights/ala-ist, /ucak-bileti/ist-ayt). A three-letter pair counts only
# when both codes appear in another pair too (a route network shares its airports; "big-sale" shares nothing), and only
# from ROUTES_MIN addresses (DECISIONS 316, agent default).
_ROUTE = re.compile(r"^([a-z]{3}) ([a-z]{3})$")
ROUTES_MIN = 3


def iata_routes(paths: Iterable[list[str]]) -> list[str]:
    """The route segments ("ala ist") of the addresses, in order, that pass the shared-airport rule."""
    pairs = [m.groups() for segs in paths for seg in segs if (m := _ROUTE.match(seg)) and m.group(1) != m.group(2)]
    seen: Counter = Counter()
    for pair in set(pairs):
        seen.update(pair)
    return [f"{a}-{b}" for a, b in dict.fromkeys(pairs) if seen[a] >= 2 and seen[b] >= 2]


def _reason(signals: list[dict]) -> dict:
    tr, en = [], []
    for s in signals:
        v = ", ".join(f"'{x}'" if s["kind"] in ("urls", "menu") else str(x) for x in s.get("values") or [])
        if s["kind"] == "schema":
            tr.append(f"ana sayfada {v} yapısal verisi")
            en.append(f"{v} structured data on the homepage")
        elif s["kind"] == "platform":
            tr.append(f"{v} altyapısı")
            en.append(f"built on {v}")
        elif s["kind"] == "urls":
            tr.append(f"{s['count']:,}".replace(",", ".") + f" adreste {v} gibi sözcükler")
            en.append(f"{s['count']:,} addresses with words such as {v}")
        elif s["kind"] == "menu":
            tr.append(f"menüde {v}")
            en.append(f"menu words {v}")
        elif s["kind"] == "types":
            tr.append(f"{s['count']:,}".replace(",", ".") + " okunan sayfa ürün ya da kategori sayfası")
            en.append(f"{s['count']:,} pages read are product or category pages")
        elif s["kind"] == "routes":
            tr.append(f"{s['count']:,}".replace(",", ".") + f" adreste havalimanı kodlu rota ({v})")
            en.append(f"{s['count']:,} addresses with airport-code routes ({v})")
    return {"tr": "; ".join(tr), "en": "; ".join(en)}


def resolve(choice: str | None, suggestion: dict) -> dict:
    """The business type an audit uses: the person's choice, else the suggestion."""
    if choice and choice != AUTO and choice in profiles():
        return {"id": choice, "label": profile(choice)["label"], "chosen_by": "user", "suggestion": suggestion,
                "version": VERSION}
    return {"id": suggestion["id"], "label": profile(suggestion["id"])["label"], "chosen_by": "suggestion",
            "suggestion": suggestion, "version": VERSION}


# ---------------------------------------------------------------- the engine's result

def attach(result) -> dict | None:
    """After the page grouping (`final.settle`): suggest, resolve with the audit's choice (`config.business_type`),
    re-score the grouping records and set `result.business_type`. Returns it."""
    from ..site_platform import recognise
    pages = list(getattr(result, "pages", None) or [])
    read = [p for p in pages if isinstance(getattr(p, "grouping", None), dict) and "importance" in p.grouping]
    home = next((p for p in read if p.grouping.get("page_type") == "home"
                 and p.grouping.get("page_type_basis", "").startswith("the start address")), None) or next(
        (p for p in read if p.grouping.get("page_type") == "home"), None)
    try:
        platform = (recognise(result) or {}).get("name")
    except Exception:  # noqa: BLE001  a hint only
        platform = None
    urls = [p.url for p in pages] + list(getattr(result, "discovered_urls", None) or []) + list(
        getattr(result, "sitemap_urls", None) or [])
    folders = _folders(getattr(result, "locales", None), urls, getattr(result, "start_url", None))
    types = Counter(p.grouping.get("page_type") for p in read)
    suggestion = suggest(home.analysis if home else None, home.outlinks if home else None, platform, urls, folders,
                         dict(types))
    config = getattr(result, "config", None)
    choice = (config.get("business_type") if isinstance(config, dict) else getattr(config, "business_type", None))
    chosen = resolve(choice, suggestion)
    records = {p.url: p.grouping for p in read}
    summary = getattr(result, "page_grouping", None)
    for url, g in ((summary or {}).get("canonical_pages") or {}).items():
        records.setdefault(url, g)
    texts = link_texts((p.url, p.outlinks) for p in read)
    common = sitewide_schema(p.analysis for p in read)
    facts = {p.url: page_facts(p.url, p.analysis, texts.get(p.url, ()), p.grouping.get("page_type"), common, folders)
             for p in read}
    chosen["page_types"] = apply(records, facts, chosen["id"], folders)
    chosen["not_found"] = not_found(records, chosen["id"])
    reader = getattr(result, "reader_page_grouping", None)
    if isinstance(reader, dict) and isinstance(reader.get("pages"), dict):
        apply(reader["pages"], {}, chosen["id"], folders)
    if isinstance(summary, dict):
        summary["business_type"] = {k: chosen[k] for k in ("id", "chosen_by", "version")}
        summary["importance_source"] = "links" if chosen["id"] == DEFAULT else f"profile:{chosen['id']}"
    result.business_type = chosen
    return chosen


# ---------------------------------------------------------------- a saved report

def _report_urls(crawl: dict) -> list[str]:
    return [p.get("url") for p in crawl.get("pages") or [] if isinstance(p, dict)] + list(
        crawl.get("discovered_urls") or []) + list(crawl.get("sitemap_urls") or [])


def _folders(saved: dict | None, urls: Iterable[str], start: str | None) -> tuple[str, ...]:
    """The site's locale folders: the report's own (`crawl.locales`, schema 1.27), else worked out from its addresses."""
    if isinstance(saved, dict) and isinstance(saved.get("folders"), list):
        return tuple(saved["folders"])
    from ..locales import detect
    return tuple(detect(urls, start_url=start)["folders"])


def key_type_test(choice: str | None, urls: Iterable[str], folders: Iterable[str] = ()):
    """DECISIONS 316: a test for the business type's first three page types by address word, so a capped crawl reads
    them first within each round of sections. The type is the person's choice, else the one the sitemap's addresses
    suggest; None for "Diğer" or when no type stands out. A hint for the crawl order only."""
    folders = tuple(folders)
    pid = choice if choice and choice != AUTO and choice in profiles() else suggest(None, None, None, urls, folders)["id"]
    if pid == DEFAULT:
        return None
    words = [w for t in profile(pid)["page_types"] if t.get("rank") and t["rank"] <= 3 for w in (t.get("signals") or {}).get("url") or []]
    if not words:
        return None
    return lambda url: any(url_hit(w, _segments(url, folders)) for w in words)


def home_record(report: dict, records: dict[str, dict]) -> dict | None:
    crawl = report.get("crawl") or {}
    pages = {p.get("url"): p for p in crawl.get("pages") or [] if isinstance(p, dict)}
    homes = [u for u, g in records.items() if g.get("page_type") == "home"]
    start = crawl.get("start_url") or ""
    for u in [start, start.rstrip("/"), start.rstrip("/") + "/"] + homes:
        if u in pages and (pages[u].get("analysis") or {}):
            return pages[u]
    return pages.get(start) or (pages.get(homes[0]) if homes else None)


def for_report(report: dict, records: dict[str, dict], choice: str | None = None) -> dict:
    """The business type of a saved report: `choice` (the person's, saved beside the audit), else the one the report
    was run with when a person chose it, else the suggestion (the report's own, or worked out from its saved data);
    then `records` re-scored (in place) for it."""
    crawl = report.get("crawl") or {}
    saved = crawl.get("business_type") if isinstance(crawl.get("business_type"), dict) else None
    suggestion = (saved or {}).get("suggestion")
    if not isinstance(suggestion, dict) or suggestion.get("version") != VERSION:
        home = home_record(report, records) or {}
        platform = (report.get("platform") or {}).get("name")
        if not platform:
            try:
                from ..site_platform import recognise_saved
                platform = (recognise_saved(report) or {}).get("name")
            except Exception:  # noqa: BLE001
                platform = None
        types = Counter(g.get("page_type") for g in records.values() if isinstance(g, dict) and g.get("read") is not False)
        suggestion = suggest(home.get("analysis"), home.get("outlinks"), platform, _report_urls(crawl),
                             _folders(crawl.get("locales"), _report_urls(crawl), crawl.get("start_url")), dict(types))
    if not choice and saved and saved.get("chosen_by") == "user":
        choice = saved.get("id")
    chosen = resolve(choice, suggestion)
    pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict) and p.get("analysis")]
    texts = link_texts((p.get("url"), p.get("outlinks")) for p in pages)
    common = sitewide_schema(p.get("analysis") for p in pages if p.get("url") in records)
    folders = _folders(crawl.get("locales"), _report_urls(crawl), crawl.get("start_url"))
    facts = {p["url"]: page_facts(p["url"], p.get("analysis"), texts.get(p["url"], ()),
                                  (records.get(p["url"]) or {}).get("page_type"), common, folders)
             for p in pages if p.get("url") in records}
    chosen["page_types"] = apply(records, facts, chosen["id"], folders)
    chosen["not_found"] = not_found(records, chosen["id"])
    return chosen


# ---------------------------------------------------------------- the person's choice for a saved audit

CHOICE_FILE = "business-type.json"


def load_choice(folder) -> str | None:
    """The type a person chose for a saved audit (`<audit>/artifacts/business-type.json`), or None."""
    from pathlib import Path
    path = Path(folder) / CHOICE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = data.get("id") if isinstance(data, dict) else None
    return pid if pid in profiles() else None
