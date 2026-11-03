"""What a client report shows, and in which order (v0.3 stage 6, DECISIONS 300).

One selection for every client output (the web app's concise PDF, the `maya-audit-pro` report and their XLSX
appendix), made from the final report. It never changes a finding, a severity or a confidence in the report: it reads
them, merges the findings that share one root cause, scores each group, and places it.

*Root cause.* Findings of one rule (`rule_id`; the engine's `dedup_key` where it has one) are one cause with one
remedy, whatever template or language copy they were found on: `/products/*` and `/en/products/*`, the Turkish and
the English header ("Sepet 0 ürün" and "Cart 0 items"). They become one card, with an example from each language.
Findings that differ in what a card states about them stay apart: one that may be intentional (`intent`), one that
needs confirming first, a different re-test state (a card shows one, RG-4).

*Priority* = severity weight x confidence weight x reach x business relevance, rounded to one decimal:

    severity    Blocker (S1) 100, High (S2) 40, Medium (S3) 15, Low (S4) 5, Info 0
    confidence  measured 1.0, estimated 0.6, inferred 0.5, unverified 0.4
    reach       1 + ln(1 + the summed importance (page grouping, 0-100) of the pages it affects / 100), at most 10
                (DECISIONS 301: diminishing returns, no ties); a finding with no page address reaches the homepage
    business    1.0 until business-type profiles exist (stage 4)

"Measured" is the engine's `verified`; "unverified" is a finding from a rule not yet validated on real sites (the
launch gate's `LG-` items), whatever its confidence. Effort is shown on a card and never used here. The ranking never
changes a severity: every Blocker and High card is kept, however it scores.

*Placement.* Each group goes to exactly one place:

    card       the top cards, at most 15, in priority order (every Blocker/High one first, then the highest scores)
    confirm    "Teyit edin": a confidence weight of 0.5 or less, a finding that may be intentional, one seen only in
               Firecrawl's copy of the pages (`evidence.reading`), and 403/429 answers to Maya's request with
               Googlebot's user agent (a spoofed Googlebot); unless the owner's manual check confirmed it
    note       Info findings (no action implied)
    own_limit  Maya's own limits (how the pages were read); said in the coverage section, never as a client problem
    appendix   a problem that did not fit on the cards

Every finding of the report is in the appendix (the XLSX), with its group, placement and score. Nothing here sends a
request: page importance comes from the report's page grouping or, for a report saved before it existed, from
`page_groups.annotate` run on the saved page records.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

SEVERITY_WEIGHT = {"S1": 100, "S2": 40, "S3": 15, "S4": 5, "Info": 0}
SEVERITY_NAME = {"S1": "Blocker", "S2": "High", "S3": "Medium", "S4": "Low", "Info": "Info"}
CONFIDENCE_WEIGHT = {"measured": 1.0, "estimated": 0.6, "inferred": 0.5, "unverified": 0.4}
ENGINE_CONFIDENCE = {"verified": "measured", "estimated": "estimated", "inferred": "inferred", "not_assessed": "unverified"}
CONFIRM_AT_OR_BELOW = 0.5
REACH_UNIT = 100
# DECISIONS 301 (3): reach grows with diminishing returns, 1 + ln(1 + importance / 100), up to 10 (reached only past
# about 800,000 importance points), so two findings of one band with different reach never score the same.
REACH_CAP = 10.0
UNSCORED_IMPORTANCE = 10  # a page the grouping did not score (not read, a file): counted, but small
BUSINESS_RELEVANCE = 1.0
from .release_gate import CLIENT_MAX_CARDS as MAX_CARDS, CLIENT_MAX_PAGES as MAX_PAGES  # noqa: E402
KEY_PAGES = 10
CONFIRM_LINES = 12  # "Teyit edin" lines a client report prints; the rest are counted and in the appendix
HIGH = ("S1", "S2")
PROBLEM = ("S1", "S2", "S3", "S4")
# How Maya read the pages: the reader's own note, not a problem of the site (DECISIONS 288 keeps acc9.blocked_429 and
# acc9.rate_limited_429, which warn that AI crawlers may be refused too, as the site's).
OWN_LIMIT_RULES = frozenset({"acc9.reader", "acc9.reader.counted", "acc9.reader.site", "acc9.reader.site.counted"})
# DECISIONS 301 (4): rule ids -> one root cause -> one fix. Findings of these rules are one card (still split by what
# a card states: confirm first, intent, re-test state, Info), with the worst pages as examples (`worst_by`: the
# evidence field that measures how bad a page is). Every finding id stays in the appendix. A rule in no group is its
# own cause. `title` and `fix` are the card's one title and one fix, in Turkish and English.
MERGE_GROUPS = (
    {"id": "html_weight", "title": {"tr": "Sayfa HTML'ini hafifletin", "en": 'Make the page HTML lighter'}, "fix": {"tr": "Satır içi JSON, betik, stil ve SVG'yi HTML'in dışına taşıyın; kullanılmayan tema bloklarını kaldırın; ana içerik HTML'in başına yakın başlasın.", "en": 'Move inlined JSON, scripts, styles and SVG out of the HTML; remove unused theme blocks; let the main content start early in the HTML.'}, "cause": "the page HTML is too heavy (inlined data, scripts, styles, theme blocks)",
     "rules": ("rnd6.home_large", "rnd6.home_large_fc", "rnd6.large", "rnd6.large_fc", "rnd6.late", "rnd6.late_fc"),
     "worst_by": ("bytes", "main_offset_bytes")},
    {"id": "empty_pages", "title": {"tr": 'Boş yanıt veren sayfaları düzeltin', "en": 'Fix pages that answer empty'}, "fix": {"tr": 'Boş yanıtın nedenini sunucu ya da CDN kayıtlarında bulun ve sayfanın içerikle yanıt vermesini sağlayın.', "en": 'Find why the page answers empty in the server or CDN logs and make it answer with its content.'}, "cause": "pages answer with an empty document",
     "rules": ("idx1.empty", "idx1.empty.bot", "judgment.empty.repeated", "judgment.empty.single")},
    {"id": "heading_levels", "title": {"tr": 'Başlık düzeylerini sıraya koyun', "en": 'Put heading levels in order'}, "fix": {"tr": "Başlıkları sırayla kullanın (H2'den sonra H3); tekrarlanan bloklardaki başlıkları temada düzeltin.", "en": 'Use heading levels in order (an H3 after an H2); fix the headings of repeated blocks in the theme.'}, "cause": "heading levels skip a level, in the pages or in a repeated block",
     "rules": ("tseo1.heading_jumps", "shared.heading_jump", "shared.heading_jump_varied")},
    {"id": "links_without_text", "title": {"tr": 'Metni olmayan bağlantılara ad verin', "en": 'Name the links that have no text'}, "fix": {"tr": 'Bağlantıya metin verin ya da içindeki görsele alt metin ekleyin; tekrarlanan bloklarda bunu temada yapın.', "en": 'Give the link text or give its image an alt text; in repeated blocks, do it in the theme.'}, "cause": "links with no text (usually an image link with no alt)",
     "rules": ("str14.no_text", "shared.link_no_text", "shared.block_links_no_text", "shared.link_no_text_pattern")},
    {"id": "links_without_address", "title": {"tr": 'Adresi olmayan bağlantıları düzeltin', "en": 'Fix links with no address'}, "fix": {"tr": 'Sayfaya giden öğelere gerçek bir href verin; yalnız işlem yapan öğeler için <button> kullanın.', "en": 'Give elements that lead to a page a real href; use <button> for elements that only act.'}, "cause": "links and controls with no address a crawler can follow",
     "rules": ("str19.no_target", "shared.link_no_address", "shared.links_no_address", "str19.lead_nowhere")},
    {"id": "language_mismatch", "title": {"tr": 'Dil sürümlerindeki çevrilmemiş metni düzeltin', "en": 'Fix untranslated text in language versions'}, "fix": {"tr": "Diğer dilde kalan bölgeleri (menü, başlıklar, metin) çevirin ya da <html lang>'i içeriğe göre düzeltin.", "en": 'Translate the regions left in the other language (menu, titles, text), or set <html lang> to match the content.'}, "cause": "a language version carries text of another language, or declares the wrong one",
     "rules": ("str12.language", "str12.headings", "str9.lang_mismatch")},
    {"id": "sitemap_lastmod", "title": {"tr": 'Site haritası lastmod tarihlerini düzeltin', "en": 'Fix the sitemap lastmod dates'}, "fix": {"tr": "lastmod'u sayfanın gerçek son düzenleme tarihinden alın; alınamıyorsa lastmod'u yazmayın.", "en": "Take lastmod from each page's real last edit; if that is not possible, leave lastmod out."}, "cause": "sitemap <lastmod> dates are generated, not the pages' real edit dates",
     "rules": ("idx5.stamped", "idx5.identical", "idx5.future")},
    {"id": "template_meta", "title": {"tr": 'Ortak başlık ve açıklamaları ayırın', "en": 'Give pages their own titles and descriptions'}, "fix": {"tr": 'Şablonun her sayfaya aynı başlık ve açıklamayı yazmasını durdurun; her sayfaya kendi başlık ve açıklamasını verin.', "en": 'Stop the template writing one title and description on every page; give each page its own.'}, "cause": "a template repeats one title or description across pages",
     "rules": ("str1.shared", "str16.shared")},
)
MERGE_BY_RULE = {rule: group for group in MERGE_GROUPS for rule in group["rules"]}
# Kept for older callers: the empty-page rules were the first family (DECISIONS 284).
RULE_FAMILY = {rule: "idx1.empty" for rule in MERGE_BY_RULE if MERGE_BY_RULE[rule]["id"] == "empty_pages"}
CONFIRM_REASONS = ("unverified_check", "low_confidence", "intent", "firecrawl_only", "spoofed_googlebot")
LG = re.compile(r"^LG-\d+$")


# ---------------------------------------------------------------- one finding

def severity(f: dict) -> str:
    s = f.get("severity")
    return getattr(s, "value", s) or "Info"


def manual(f: dict, confirmations: dict | None) -> dict | None:
    """The owner's manual check of this finding, by finding id or by rule id: {"result": "confirmed"|"rejected", ...}."""
    if not confirmations:
        return None
    return confirmations.get(f.get("id")) or confirmations.get(f.get("rule_id"))


def confidence_class(f: dict, confirmations: dict | None = None) -> str:
    """measured / estimated / inferred / unverified, as the priority score weighs it."""
    check = manual(f, confirmations)
    if check and check.get("result") == "confirmed":
        return "measured"
    if any(LG.match(str(g)) for g in f.get("launch_gated") or []):
        return "unverified"
    reading = (f.get("evidence") or {}).get("reading") or {}
    if reading.get("seen_in") == "firecrawl_only":
        return "estimated"
    return ENGINE_CONFIDENCE.get(f.get("confidence") or "", "unverified")


def spoofed_googlebot(f: dict) -> bool:
    """403/429 to Maya's request with Googlebot's user agent where a browser got 200 (ACC-4, DECISIONS 290): the
    firewall may refuse a fake Googlebot and serve the real one."""
    if f.get("rule_id") != "acc4.ua_check.status":
        return False
    pairs = (f.get("evidence") or {}).get("pairs") or []
    return bool(pairs) and all(p.get("outcome") == "refused" for p in pairs if isinstance(p, dict))


def confirm_reason(f: dict, confirmations: dict | None = None) -> str | None:
    """Why the finding goes to "Teyit edin" before anyone acts on it, or None."""
    check = manual(f, confirmations)
    if check and check.get("result") == "confirmed":
        return None
    if spoofed_googlebot(f):
        return "spoofed_googlebot"
    if ((f.get("evidence") or {}).get("reading") or {}).get("seen_in") == "firecrawl_only":
        return "firecrawl_only"
    if f.get("intent"):
        return "intent"
    cls = confidence_class(f, confirmations)
    if cls == "unverified":
        return "unverified_check"
    if CONFIDENCE_WEIGHT[cls] <= CONFIRM_AT_OR_BELOW:
        return "low_confidence"
    return None


def own_limit(f: dict) -> bool:
    return f.get("rule_id") in OWN_LIMIT_RULES


# ---------------------------------------------------------------- page importance

def _result_from_report(report: dict):
    from .models import page_from_record
    crawl = report.get("crawl") or {}
    pages = [page_from_record(record) for record in crawl.get("pages") or [] if isinstance(record, dict)]
    return SimpleNamespace(pages=pages, start_url=crawl.get("start_url") or "", origin=crawl.get("origin"),
                           discovered_urls=crawl.get("discovered_urls") or [], sitemap_urls=crawl.get("sitemap_urls") or [],
                           page_grouping=None)


def grouping(report: dict) -> tuple[dict[str, dict], dict]:
    """({url: grouping record}, summary) from the report's page grouping; for a report saved before it (schema below
    1.23), from `page_groups.annotate` on the saved page records (offline, the report is not changed)."""
    crawl = report.get("crawl") or {}
    records = {p.get("url"): p.get("grouping") for p in crawl.get("pages") or [] if isinstance(p, dict)}
    summary = crawl.get("page_grouping")
    if not any(isinstance(g, dict) and "importance" in g for g in records.values()) or not isinstance(summary, dict):
        try:
            from .page_groups import annotate
            result = _result_from_report(report)
            if not result.pages:
                return {}, {}
            summary = annotate(result)
            records = {p.url: p.grouping for p in result.pages}
        except Exception as exc:  # a report too old or too damaged to group: importance unknown, said so
            return {}, {"error": f"page grouping could not be worked out: {type(exc).__name__}"}
    out = {u: g for u, g in records.items() if isinstance(g, dict) and "importance" in g}
    for url, g in ((summary or {}).get("canonical_pages") or {}).items():
        if isinstance(g, dict) and "importance" in g:
            out.setdefault(url, g)
    return out, summary or {}


def _home(report: dict) -> str:
    crawl = report.get("crawl") or {}
    return crawl.get("start_url") or crawl.get("origin") or ""


def language_of(url: str, default: str | None) -> str | None:
    """The language folder of an address (`/en/...`), else the site's default language."""
    from .page_groups import is_locale
    first = (urlsplit(url).path or "/").strip("/").split("/")[0]
    return first.lower() if first and is_locale(first) else default


def default_language(report: dict) -> str | None:
    home = _home(report).rstrip("/")
    for p in (report.get("crawl") or {}).get("pages") or []:
        if isinstance(p, dict) and (p.get("url") or "").rstrip("/") == home:
            lang = ((p.get("analysis") or {}).get("html_lang") or "").split("-")[0].lower()
            return lang or None
    return None


# ---------------------------------------------------------------- groups

def all_findings(report: dict) -> list[dict]:
    """Every finding of the report (the gate's set), in the report's priority order, then the rest as found."""
    from .release_gate import findings_of
    by_id = findings_of(report)
    order = [i for i in report.get("findings_in_priority_order") or [] if isinstance(i, str) and i in by_id]
    return [by_id[i] for i in order] + [f for i, f in by_id.items() if i not in set(order)]


def affected(f: dict, lists: dict | None) -> list[str]:
    from .release_gate import affected_urls
    return affected_urls(f, lists)


def retest_state(f: dict) -> str:
    return (f.get("verification") or {}).get("state") or "not_retested"


def merge_group(f: dict) -> dict | None:
    return MERGE_BY_RULE.get(f.get("rule_id") or "")


def group_key(f: dict, confirmations: dict | None = None) -> tuple:
    merged = merge_group(f)
    cause = ("merge:" + merged["id"]) if merged else (f.get("dedup_key") or f.get("rule_id") or
                                                       f"{f.get('check_id')}:{re.sub(r'[0-9]+', '#', f.get('title') or '')}")
    reason = confirm_reason(f, confirmations)
    return (cause if merged else f.get("check_id"), cause, bool(f.get("intent")), bool(reason), retest_state(f),
            severity(f) == "Info")


def _weight(sev: str) -> int:
    return SEVERITY_WEIGHT.get(sev, 0)


def _score(sev: str, conf: str, reach: float) -> float:
    """Kept to three decimals: two groups that differ in reach do not tie (cards print one decimal)."""
    return round(_weight(sev) * CONFIDENCE_WEIGHT[conf] * reach * BUSINESS_RELEVANCE, 3)


def reach_of(total: float) -> float:
    import math
    return round(min(1 + math.log1p(max(total, 0) / REACH_UNIT), REACH_CAP), 6)


def _reach(urls: list[str], importance: dict[str, dict], home_importance: int) -> tuple[float, int, int]:
    """(reach, summed importance, pages counted). Each address once; a duplicate's own score (capped at 20) is used."""
    pages = [u for u in dict.fromkeys(urls) if isinstance(u, str) and u.startswith(("http://", "https://"))]
    if not pages:
        return reach_of(home_importance), home_importance, 0
    total = sum(int((importance.get(u) or {}).get("importance", UNSCORED_IMPORTANCE)) for u in pages)
    return reach_of(total), total, len(pages)


def _examples(urls: list[str], members: list[dict], lists: dict | None, importance: dict[str, dict],
              default_lang: str | None, limit_per_language: int = 1) -> list[dict]:
    """One example address per language (the most important page of that language that is not a search, cart or other
    utility page, unless only such pages are affected), with the finding it comes from."""
    by_url: dict[str, dict] = {}
    for m in members:
        for u in affected(m, lists):
            by_url.setdefault(u, m)
    pages = [u for u in dict.fromkeys(urls) if u in by_url]

    def utility(u):
        return (importance.get(u) or {}).get("page_type") == "utility"

    def rank(u):
        g = importance.get(u) or {}
        return (utility(u), -(g.get("importance") or 0), g.get("importance_rank") or 10**9)

    out: list[dict] = []
    seen: dict[str | None, int] = {}
    for u in sorted(pages, key=rank):
        lang = language_of(u, default_lang)
        if seen.get(lang, 0) >= limit_per_language:
            continue
        if utility(u) and any(not utility(v) and language_of(v, default_lang) == lang for v in pages):
            continue
        seen[lang] = seen.get(lang, 0) + 1
        m = by_url[u]
        out.append({"url": u, "language": lang, "finding_id": m.get("id"), "title": m.get("title"),
                    "page_type": (importance.get(u) or {}).get("page_type")})
    return out


def worst_examples(members: list[dict], fields: tuple[str, ...], limit: int = 3) -> list[dict]:
    """The pages a merge group measures worst (largest `fields` value in the members' evidence), one per address."""
    rows = []
    for m in members:
        for row in (m.get("evidence") or {}).get("pages") or []:
            if isinstance(row, dict) and row.get("url"):
                value = next((row[k] for k in fields if isinstance(row.get(k), (int, float))), None)
                if value is not None:
                    rows.append((value, row["url"], m))
    out, seen = [], set()
    for value, url, m in sorted(rows, key=lambda r: -r[0]):
        if url not in seen:
            seen.add(url)
            out.append({"url": url, "language": None, "finding_id": m.get("id"), "title": m.get("title"), "value": value})
        if len(out) >= limit:
            break
    return out


def groups(report: dict, lists: dict | None = None, confirmations: dict | None = None,
           importance: dict[str, dict] | None = None) -> list[dict]:
    """Every finding in exactly one group, each group scored. In the report's priority order (the lead is its first)."""
    if importance is None:
        importance, _ = grouping(report)
    home = _home(report)
    home_importance = int((importance.get(home) or {}).get("importance", REACH_UNIT))
    default_lang = default_language(report)
    out: dict[tuple, dict] = {}
    for f in all_findings(report):
        key = group_key(f, confirmations)
        g = out.get(key)
        if g is None:
            g = out[key] = {"key": key, "members": []}
        g["members"].append(f)
    rows = []
    for g in out.values():
        members = g["members"]
        sev = max((severity(m) for m in members), key=_weight)
        classes = [confidence_class(m, confirmations) for m in members]
        conf = min(classes, key=lambda c: CONFIDENCE_WEIGHT[c])
        urls = list(dict.fromkeys(u for m in members for u in affected(m, lists)))
        reach, total, counted = _reach(urls, importance, home_importance)
        lead = members[0]
        reasons = [r for r in (confirm_reason(m, confirmations) for m in members) if r]
        languages = sorted({language_of(u, default_lang) or "" for u in urls} - {""})
        rows.append({
            "finding_ids": [m.get("id") for m in members], "members": members, "lead": lead,
            "check_id": lead.get("check_id"), "rule_id": lead.get("rule_id"), "title": lead.get("title"),
            "severity": sev, "severity_name": SEVERITY_NAME.get(sev, sev),
            "confidence": conf, "confidence_weight": CONFIDENCE_WEIGHT[conf],
            "reach": reach, "importance_sum": total, "pages_counted": counted, "urls": urls,
            "priority": _score(sev, conf, reach),
            "parts": {"severity": _weight(sev), "confidence": CONFIDENCE_WEIGHT[conf], "reach": reach,
                      "business": BUSINESS_RELEVANCE},
            "intent": bool(lead.get("intent")), "confirm_reason": reasons[0] if reasons else None,
            "own_limit": all(own_limit(m) for m in members),
            "languages": languages,
            "templates": sorted({(importance.get(u) or {}).get("template_key") for u in urls} - {None}),
            "examples": (worst_examples(members, merge_group(lead)["worst_by"])
                         if merge_group(lead) and merge_group(lead).get("worst_by") and worst_examples(members, merge_group(lead)["worst_by"])
                         else _examples(urls, members, lists, importance, default_lang)),
            "merge_group": (merge_group(lead) or {}).get("id"),
            "manual": next((manual(m, confirmations) for m in members if manual(m, confirmations)), None),
        })
    return rows


def _order(rows: list[dict]) -> list[dict]:
    """DECISIONS 301 (3): severity band first (a Medium is never below a Low), then priority within the band, then the
    report's own order (its first finding)."""
    return sorted(rows, key=lambda g: (-_weight(g["severity"]), -g["priority"], g["_index"]))


def select(report: dict, lists: dict | None = None, confirmations: dict | None = None, *,
           max_cards: int = MAX_CARDS) -> dict:
    """The selection a client report prints: cards, "Teyit edin", notes, own limits, appendix, key pages, counts."""
    importance, summary = grouping(report)
    rows = groups(report, lists, confirmations, importance)
    for i, g in enumerate(rows):
        g["_index"] = i
    rejected = [g for g in rows if (g["manual"] or {}).get("result") == "rejected"]
    for g in rows:
        if g in rejected:
            g["placement"] = "rejected"
        elif g["own_limit"]:
            g["placement"] = "own_limit"
        elif g["confirm_reason"] and (g["severity"] in PROBLEM or g["confirm_reason"] in ("spoofed_googlebot", "firecrawl_only")):
            # An Info note implies no action, so there is nothing to confirm before acting: it stays a note. The
            # exceptions are the two the owner named (DECISIONS 300 (9)): the spoofed Googlebot's 403/429, and a finding
            # seen only in Firecrawl's copy (a client report may otherwise turn a note into advice).
            g["placement"] = "confirm"
        elif g["severity"] not in PROBLEM:
            g["placement"] = "note"
        else:
            g["placement"] = None
    candidates = _order([g for g in rows if g["placement"] is None])
    # Every Blocker and High group is a card, whatever it scores (nothing S1/S2 is ever cut, preamble 4); the rest by
    # score while there is room. More than 15 High groups make more than 15 cards: the gate then blocks (RG-16).
    must = [g for g in candidates if g["severity"] in HIGH]
    rest = [g for g in candidates if g["severity"] not in HIGH]
    chosen = must + rest[:max(0, max_cards - len(must))]
    chosen_ids = {id(g) for g in chosen}
    cards = _order(chosen)
    for n, g in enumerate(cards, 1):
        g["placement"], g["card"] = "card", n
    for g in candidates:
        if id(g) not in chosen_ids:
            g["placement"] = "appendix"
    confirm = _order([g for g in rows if g["placement"] == "confirm"])
    notes = _order([g for g in rows if g["placement"] == "note"])
    limits = [g for g in rows if g["placement"] == "own_limit"]
    appendix_only = _order([g for g in rows if g["placement"] == "appendix"])
    for g in rows:
        g.pop("_index", None)
    by_finding = {fid: g for g in rows for fid in g["finding_ids"]}
    return {
        "method": {"severity_weight": SEVERITY_WEIGHT, "confidence_weight": CONFIDENCE_WEIGHT,
                   "reach": f"1 + ln(1 + summed page importance / {REACH_UNIT}), at most {REACH_CAP}; no page address: the homepage",
                   "order": "severity band, then priority score", "merge_groups": [g["id"] for g in MERGE_GROUPS],
                   "business_relevance": BUSINESS_RELEVANCE, "max_cards": max_cards, "max_pages": MAX_PAGES,
                   "confirm_at_or_below": CONFIRM_AT_OR_BELOW,
                   "importance": "page grouping (DECISIONS 297, 298)" if importance else "not available"},
        "cards": cards, "confirm": confirm, "notes": notes, "own_limits": limits, "appendix_only": appendix_only,
        "rejected": [g for g in rows if g["placement"] == "rejected"],
        "groups": rows, "by_finding": by_finding,
        "key_pages": key_pages(report, rows, importance),
        "key_pages_reason": None if importance else key_pages_reason(report),
        "coverage": coverage(report, limits),
        "counts": {"findings": len(by_finding), "groups": len(rows), "cards": len(cards), "confirm": len(confirm),
                   "notes": len(notes), "own_limits": len(limits), "appendix_only": len(appendix_only),
                   "rejected": len([g for g in rows if g["placement"] == "rejected"]),
                   "problems": sum(1 for g in rows for m in g["members"] if severity(m) in PROBLEM),
                   # DECISIONS 301 (5): the one source of every count a client output prints.
                   "by_severity": {k: sum(1 for g in rows for m in g["members"] if severity(m) == k)
                                   for k in ("S1", "S2", "S3", "S4", "Info")},
                   "addresses": len({u for g in rows for u in g["urls"]})},
        "grouping_summary": {k: summary.get(k) for k in ("method_version", "pages_scored", "page_types") if k in summary},
        "platform": (report.get("platform") or {}).get("name"),
        "_confirmations": confirmations or {},
    }


def platform_steps(rule_id: str | None, platform: str | None, lang: str) -> list[str] | None:
    """The catalogue's steps for this rule on this platform (`steps_by_platform`, e.g. Shopify writes its own sitemap,
    DECISIONS 300 (7)), or None. The release gate checks the platform against the report's (RG-11)."""
    if not rule_id or not platform:
        return None
    from .facts import _catalogue
    entry = (_catalogue().get(rule_id) or {}).get("steps_by_platform") or {}
    return ((entry.get(platform) or {}).get(lang)) or None


# ---------------------------------------------------------------- key pages and coverage

def key_pages(report: dict, rows: list[dict], importance: dict[str, dict], limit: int = KEY_PAGES) -> list[dict]:
    """The most important pages read (importance rank), with what the cards and the confirm list say about each."""
    read = [(u, g) for u, g in importance.items() if g.get("read") is not False]
    read.sort(key=lambda kv: (kv[1].get("importance_rank") or 10**9, -(kv[1].get("importance") or 0)))
    out = []
    for url, g in read[:limit]:
        cards = [x for x in rows if x.get("placement") == "card" and url in x["urls"]]
        confirm = [x for x in rows if x.get("placement") == "confirm" and url in x["urls"]]
        worst = max((x["severity"] for x in cards), key=_weight, default=None)
        out.append({"url": url, "page_type": g.get("page_type"), "importance": g.get("importance"),
                    "rank": g.get("importance_rank"), "cards": sorted(x["card"] for x in cards),
                    "worst": worst, "confirm": len(confirm)})
    return out


def key_pages_reason(report: dict) -> str:
    """Why no page could be scored (the key pages list is empty): "reader_only" when the pages were read only through
    a page reader after Maya's crawler was blocked (the saved copies keep no links, and importance needs the links
    between pages); "no_pages" otherwise (nothing with content was read)."""
    crawl = report.get("crawl") or {}
    own = [p for p in crawl.get("pages") or [] if isinstance(p, dict) and p.get("analysis")]
    reader = report.get("firecrawl") or {}
    read_by_reader = [p for p in reader.get("pages") or [] if isinstance(p, dict) and p.get("outcome") == "read"]
    return "reader_only" if not own and read_by_reader else "no_pages"


def coverage(report: dict, limits: list[dict]) -> dict:
    """What Maya read and what it could not, for the coverage section: our limits, never a client problem."""
    crawl = report.get("crawl") or {}
    status = (report.get("audit_status") or {}).get("content_coverage") or {}
    counts = report.get("page_counts") or {}
    cfg = crawl.get("config") or {}
    lines: list[dict] = []
    if crawl.get("stop_reason") == "page_cap":
        lines.append({"kind": "page_cap", "pages": cfg.get("max_pages"),
                      "not_read": status.get("known_urls_not_read") or len(crawl.get("not_fetched_urls") or [])})
    if crawl.get("deadline_hit") or report.get("time_limit_cuts"):
        cuts = report.get("time_limit_cuts")
        lines.append({"kind": "time_budget", "seconds": cfg.get("time_limit_s"),
                      "cut": len(cuts) if isinstance(cuts, list) else cuts or None})
    for g in limits:
        lines.append({"kind": "reader", "finding_ids": g["finding_ids"], "title": g["title"]})
    gaps: dict[str, list[str]] = {}
    for check in report.get("checks") or []:
        for part in (check.get("coverage") or {}).get("not_assessed") or []:
            text = f"{part.get('part') or ''}: {part.get('reason') or ''}".strip(": ")
            gaps.setdefault(text, []).append(check.get("check_id"))
        if check.get("status") == "not_assessed" and not (check.get("coverage") or {}).get("not_assessed"):
            gaps.setdefault(check.get("summary") or "", []).append(check.get("check_id"))
    for text, checks in gaps.items():
        if text:
            lines.append({"kind": "not_assessed", "text": text, "checks": list(dict.fromkeys(checks))})
    reader = report.get("firecrawl") or {}
    return {"pages_read": status.get("pages_read", counts.get("pages_checked")),
            "known_not_read": status.get("known_urls_not_read"),
            "discovered": len(crawl.get("discovered_urls") or []) or None,
            "read_by": status.get("read_by"), "level": status.get("level"),
            "reader": reader.get("purpose") if reader.get("used") or reader.get("pages_read") else None,
            "lines": lines}


# ---------------------------------------------------------------- appendix rows

def appendix_rows(selection: dict, lists: dict | None = None) -> list[dict]:
    """One row per finding of the report: its group, placement, scores and every affected address."""
    out = []
    for g in selection["groups"]:
        for m in g["members"]:
            out.append({"finding_id": m.get("id"), "check_id": m.get("check_id"), "rule_id": m.get("rule_id"),
                        "severity": severity(m), "confidence": m.get("confidence"),
                        "confidence_class": g["confidence"], "priority": g["priority"], "placement": g["placement"],
                        "card": g.get("card"), "group_lead": g["finding_ids"][0], "confirm_reason": g["confirm_reason"],
                        "merge_group": g.get("merge_group"),
                        "manual": (lambda c: f"{c.get('result')} · {c.get('by')} · {c.get('date')} · {c.get('seen')}"
                                   + (f" · {c['note']}" if c.get("note") else ""))(manual(m, selection.get("_confirmations")))
                        if manual(m, selection.get("_confirmations")) else "",
                        "title": m.get("title"), "how_to_fix": m.get("how_to_fix"),
                        "scope_count": (m.get("scope") or {}).get("count"), "urls": affected(m, lists)})
    return out


def merge_table() -> list[dict]:
    """The merge groups as rows (for the appendix, the docs and the tests): id, cause, rules, title, fix."""
    return [{"id": g["id"], "cause": g["cause"], "rules": list(g["rules"]), "title": g["title"], "fix": g["fix"]}
            for g in MERGE_GROUPS]
