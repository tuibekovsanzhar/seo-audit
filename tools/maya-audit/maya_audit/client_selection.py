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
                (a card joining several severities: the pages of its worst one, DECISIONS 339)
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

import json
import re
from pathlib import Path
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
# DECISIONS 305 (replaces 300's "a page not scored counts 10"): only pages that were read reach; an address that was
# not read (sitemap-only, found in a link) adds nothing and is listed as a count (`addresses_not_read`).
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
# own cause. `title` and `fix` are the card's one title and one fix, in Turkish and English; `finding` names what is
# wrong, for a findings table (DECISIONS 306: a findings table lists findings, the cards list actions).
MERGE_GROUPS = (
    {"id": "html_weight", "cause": "the page HTML is too heavy (inlined data, scripts, styles, theme blocks)",
     "rules": ("rnd6.home_large", "rnd6.home_large_fc", "rnd6.large", "rnd6.large_fc", "rnd6.late", "rnd6.late_fc"),
     "worst_by": ("bytes", "main_offset_bytes")},
    {"id": "empty_pages", "cause": "pages answer with an empty document",
     "rules": ("idx1.empty", "idx1.empty.bot", "judgment.empty.repeated", "judgment.empty.single")},
    {"id": "heading_levels", "cause": "heading levels skip a level, in the pages or in a repeated block",
     "rules": ("tseo1.heading_jumps", "shared.heading_jump", "shared.heading_jump_varied")},
    {"id": "links_without_text", "cause": "links with no text (usually an image link with no alt)",
     "rules": ("str14.no_text", "shared.link_no_text", "shared.block_links_no_text", "shared.link_no_text_pattern")},
    {"id": "links_without_address", "cause": "links and controls with no address a crawler can follow",
     "rules": ("str19.no_target", "shared.link_no_address", "shared.links_no_address", "str19.lead_nowhere")},
    {"id": "language_mismatch", "cause": "a language version carries text of another language, or declares the wrong one",
     "rules": ("str12.language", "str12.headings", "str9.lang_mismatch")},
    {"id": "sitemap_lastmod", "cause": "sitemap <lastmod> dates are generated, not the pages' real edit dates",
     "rules": ("idx5.stamped", "idx5.identical", "idx5.future")},
    {"id": "template_meta", "cause": "a template repeats one title or description across pages",
     "rules": ("str1.shared", "str16.shared")},
)
MERGE_BY_RULE = {rule: group for group in MERGE_GROUPS for rule in group["rules"]}
# Stage 8a (DECISIONS 315): canonical, redirect-chain, loop and links-to-redirect findings that name the same addresses
# are one cause (moodist: /tr/ and /en/ name /tr/tr/ and /en/en/, which redirect through / to /tr/; links to /). They are
# merged only when they share an address, never all such findings of a site.
CHAIN_RULES = frozenset({"idx4.redirect_loop", "idx4.redirecting", "idx4.chain", "idx3.chain", "idx3.loop",
                         "idx3.cookie", "idx3.intermittent", "idx3.self_once", "idx6.links_to_redirect"})
CHAIN_GROUP = {"id": "redirect_chain",
               "cause": "canonicals, redirects and links that form one redirect chain", "rules": tuple(sorted(CHAIN_RULES))}
# DECISIONS 353: each group's finding, title and fix live in merge_group_texts.json (the SEO team's catalogue writes there).
_GROUP_TEXTS = json.loads((Path(__file__).with_name("merge_group_texts.json")).read_text(encoding="utf-8"))["groups"]
for _group in (*MERGE_GROUPS, CHAIN_GROUP):
    _group.update({key: dict(_GROUP_TEXTS[_group["id"]][key]) for key in ("finding", "title", "fix")})
MERGE_BY_ID = {**{g["id"]: g for g in MERGE_GROUPS}, CHAIN_GROUP["id"]: CHAIN_GROUP}
# Kept for older callers: the empty-page rules were the first family (DECISIONS 284).
RULE_FAMILY = {rule: "idx1.empty" for rule in MERGE_BY_RULE if MERGE_BY_RULE[rule]["id"] == "empty_pages"}
CONFIRM_REASONS = ("unverified_check", "low_confidence", "intent", "firecrawl_only", "spoofed_googlebot", "rendered_html",
                   "names_in_markup")
# DECISIONS 339: where a brand name is only a structured-data value (no reader sees it on the page)
MARKUP_NAME_SOURCES = frozenset({"Organization name", "WebSite name"})
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
    if reading.get("seen_in") == "firecrawl_only" or rendered_html(f):
        return "estimated"
    return ENGINE_CONFIDENCE.get(f.get("confidence") or "", "unverified")


def spoofed_googlebot(f: dict) -> bool:
    """403/429 to Maya's request with Googlebot's user agent where a browser got 200 (ACC-4, DECISIONS 290): the
    firewall may refuse a fake Googlebot and serve the real one."""
    if f.get("rule_id") != "acc4.ua_check.status":
        return False
    pairs = (f.get("evidence") or {}).get("pairs") or []
    return bool(pairs) and all(p.get("outcome") == "refused" for p in pairs if isinstance(p, dict))


def rendered_html(f: dict) -> bool:
    """An HTML-size finding (RND-6) measured on the page reader's rendered HTML, not on what the server sends
    (DECISIONS 299 (4)): not comparable with a raw size, so it is confirmed before anyone acts on it (DECISIONS 309)."""
    if f.get("check_id") != "RND-6":
        return False
    ev = f.get("evidence") or {}
    return str(ev.get("html_measured") or "").startswith("rendered") or (ev.get("source") or {}).get("reader") == "firecrawl"


def confirm_reason(f: dict, confirmations: dict | None = None) -> str | None:
    """Why the finding goes to "Teyit edin" before anyone acts on it, or None."""
    check = manual(f, confirmations)
    if check and check.get("result") == "confirmed":
        return None
    if spoofed_googlebot(f):
        return "spoofed_googlebot"
    if ((f.get("evidence") or {}).get("reading") or {}).get("seen_in") == "firecrawl_only":
        return "firecrawl_only"
    if rendered_html(f):
        return "rendered_html"
    if f.get("intent"):
        return "intent"
    if names_in_markup(f):
        return "names_in_markup"
    cls = confidence_class(f, confirmations)
    if cls == "unverified":
        return "unverified_check"
    if CONFIDENCE_WEIGHT[cls] <= CONFIRM_AT_OR_BELOW:
        return "low_confidence"
    return None


def names_in_markup(f: dict) -> bool:
    """DECISIONS 339: a brand-names finding (STR-5) whose visible name (titles, og:site_name, footer) is one name
    everywhere, the other names being only structured-data names (Organization, WebSite). Whether such a value is a
    mistake (a CMS's "Homepage") or meant (a slogan) is for a person to see in the markup before anyone renames:
    "Teyit edin", not a card (enpara fee70191: "Enpara" in every title; "Bankanın güzeli | Enpara" and "Homepage" only
    as an Organization name on one page each)."""
    if f.get("rule_id") != "str5.names":
        return False
    variants = [v for v in (f.get("evidence") or {}).get("variants") or [] if isinstance(v, dict)]
    shown = [v for v in variants if set(v.get("by_source") or {}) - MARKUP_NAME_SOURCES]
    rest = [v for v in variants if v not in shown]
    return len(shown) == 1 and bool(rest) and all(v.get("by_source") for v in rest)


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


def grouping(report: dict, business: str | None = None) -> tuple[dict[str, dict], dict]:
    """The page grouping weighted by the business type (DECISIONS 311): `_stage3_grouping`, then
    `business_types.for_report` on copies of the records (the report is not changed). `business` is the person's
    choice for this audit (its `business-type.json`); without it, the report's own choice or the suggestion."""
    records, summary = _stage3_grouping(report)
    if not records:
        return records, summary
    records = {u: dict(g) for u, g in records.items()}
    try:
        from .business_types import for_report
        info = for_report(report, records, business)
    except Exception as exc:  # noqa: BLE001  a hint for ordering only: Stage 3's values stand, and it says so
        return records, {**summary, "business_type": {"error": f"business type not applied: {type(exc).__name__}"}}
    return records, {**summary, "business_type": info}


def _stage3_grouping(report: dict) -> tuple[dict[str, dict], dict]:
    """({url: grouping record}, summary) from the report's page grouping (or the page reader's, `reader_page_grouping`,
    1.24); for a report saved before it (schema below 1.23), from `page_groups.annotate` on the saved page records
    (offline, the report is not changed)."""
    crawl = report.get("crawl") or {}
    reader = crawl.get("reader_page_grouping")
    if isinstance(reader, dict) and reader.get("pages"):
        # Maya's crawler was blocked and a page reader read the site (DECISIONS 304, schema 1.24): the grouping of the
        # reader's pages, worked out while their links were in memory. Maya's own scored pages fill any gap.
        out = {u: g for u, g in reader["pages"].items() if isinstance(g, dict) and "importance" in g}
        for p in crawl.get("pages") or []:
            g = p.get("grouping") if isinstance(p, dict) else None
            if isinstance(g, dict) and "importance" in g:
                out.setdefault(p.get("url"), g)
        for url, g in (reader.get("canonical_pages") or {}).items():
            if isinstance(g, dict) and "importance" in g:
                out.setdefault(url, g)
        return out, {k: v for k, v in reader.items() if k != "pages"}
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


# DECISIONS 321 (2): a finding about the site's hosts, not its pages (the certificate, robots.txt, the sitemap files,
# llms.txt): every address it names is a host's root or one of those files, and the check is one that reads them. A
# card for it names the hosts; "addresses not read ... add nothing to the priority score" is never said of it.
HOST_CHECKS = frozenset({"IDX-2", "ACC-1", "ACC-2", "ACC-6", "ACC-7", "ACC-8", "IDX-5"})
SITE_FILE = re.compile(r"/(?:robots\.txt|llms(?:-full)?\.txt|[^/]*sitemap[^/]*\.xml(?:\.gz)?)$", re.I)
# DECISIONS 347 (atasunoptik: /kurumsal.xml, a sitemap with no "sitemap" in its name, listed as a page): an XML, feed or
# data file is never a page, whatever its name: not a page read, not typed, not a row of "Sayfa bazında".
NOT_A_PAGE = re.compile(r"\.(?:xml|xml\.gz|gz|rss|atom|rdf|json|txt|xsl|csv)$|/(?:feed|rss|atom)/?$", re.I)
PAGE_MEDIA = ("text/html", "application/xhtml+xml")


def not_a_page(url: str | None, content_type: str | None = None) -> bool:
    """True for an address that is a file, not a page: a sitemap or other XML, a feed, robots.txt, llms.txt, JSON, or
    a response whose media type is not HTML (DECISIONS 347)."""
    if content_type and content_type.split(";", 1)[0].strip().lower() not in PAGE_MEDIA:
        return True
    from .urls import edit_preview
    if edit_preview(url):  # DECISIONS 351: a CMS edit or preview address is its clean page, not another page
        return True
    try:
        path = urlsplit(url or "").path
    except ValueError:
        return False
    return bool(SITE_FILE.search(path) or NOT_A_PAGE.search(path))


def host_level(f: dict) -> list[str] | None:
    """The hosts a host-level finding is about, in order ("airastana.com", "www.airastana.com"), or None for a finding
    about pages. IDX-5 counts only when all its addresses are sitemap or robots files (its lastmod findings name pages)."""
    if f.get("check_id") not in HOST_CHECKS:
        return None
    urls = [u for u in (f.get("scope") or {}).get("urls") or [] if isinstance(u, str)]
    if not urls:
        return None
    hosts = []
    for u in urls:
        parts = urlsplit(u)
        if not parts.hostname or not (parts.path in ("", "/") and not parts.query or not_a_page(u)):
            return None
        if parts.hostname not in hosts:
            hosts.append(parts.hostname)
    return hosts


def merge_group(f: dict) -> dict | None:
    if f.get("_chain_cluster"):
        return CHAIN_GROUP
    return MERGE_BY_RULE.get(f.get("rule_id") or "")


def _chain_addresses(f: dict) -> set[str]:
    """The addresses a chain finding names: its pages, their canonicals and where those resolve, the hops of its
    chains and loops, and the redirect targets its links lead to (not the linking pages: every page links to /)."""
    ev = f.get("evidence") or {}
    out: set[str] = set()
    for row in ev.get("pages") or []:
        if isinstance(row, dict):
            out |= {row.get("url"), row.get("canonical"), row.get("redirects_to"), row.get("canonical_of_canonical")}
            out |= set(row.get("resolved_via") or [])
    for chain in ev.get("chains") or []:
        out |= set((chain or {}).get("hops") or [])
    for loop in ev.get("loops") or []:
        out |= set(loop or [])
    for row in ev.get("targets") or []:
        if isinstance(row, dict):
            out |= {row.get("url"), row.get("final")} | set(row.get("hops") or [])
    if f.get("rule_id") != "idx6.links_to_redirect":
        out |= set((f.get("scope") or {}).get("urls") or [])
    return {u for u in out if isinstance(u, str) and u}


def mark_chain_clusters(findings: list[dict]) -> list[list[str]]:
    """Set `_chain_cluster` (in memory only) on chain findings that share an address with another chain finding, at
    least one of them a canonical or redirect finding. Returns the clusters as finding ids."""
    chain = [f for f in findings if f.get("rule_id") in CHAIN_RULES]
    parent = list(range(len(chain)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen: dict[str, int] = {}
    for i, f in enumerate(chain):
        for u in _chain_addresses(f):
            if u in seen:
                parent[root(i)] = root(seen[u])
            else:
                seen[u] = i
    clusters: dict[int, list[int]] = {}
    for i in range(len(chain)):
        clusters.setdefault(root(i), []).append(i)
    out = []
    for n, members in enumerate(sorted(clusters.values(), key=lambda m: m[0]), 1):
        rules = {chain[i].get("rule_id") for i in members}
        if len(members) < 2 or not rules - {"idx6.links_to_redirect"}:
            continue
        for i in members:
            chain[i]["_chain_cluster"] = f"redirect_chain:{n}"
        out.append([chain[i].get("id") for i in members])
    return out


def chain_summary(members: list[dict], importance: dict | None = None) -> dict | None:
    """What a merged chain card shows (DECISIONS 315): the longest chain hop by hop, the pages whose canonical leads into
    it, and how many pages link into it (with the final address to link to)."""
    if not any(m.get("_chain_cluster") for m in members):
        return None
    hops, canon_pages, linking, final, linking_count = [], [], set(), None, 0
    for m in members:
        ev = m.get("evidence") or {}
        for chain in ev.get("chains") or []:
            if len((chain or {}).get("hops") or []) > len(hops):
                hops = list(chain["hops"])
        for row in ev.get("pages") or []:
            if isinstance(row, dict) and row.get("url"):
                canon_pages.append({"url": row["url"], "canonical": row.get("canonical")})
                via = row.get("resolved_via") or []
                if len(via) > len(hops):
                    hops = list(via)
        for row in ev.get("targets") or []:
            if isinstance(row, dict):
                linking |= set(row.get("linked_from") or [])
                final = final or row.get("final")
        if m.get("rule_id") == "idx6.links_to_redirect":
            linking |= set(((m.get("scope") or {}).get("_all_urls") or (m.get("scope") or {}).get("urls") or []))
            linking_count = int((m.get("evidence") or {}).get("page_count") or 0)
    final = final or (hops[-1] if hops else None)
    return {"hops": hops, "final": final, "canonical_pages": canon_pages,
            "linking_pages": max(len(linking), linking_count)}


def group_key(f: dict, confirmations: dict | None = None) -> tuple:
    if f.get("_chain_cluster"):  # one card for one chain, whatever each member's state (DECISIONS 315)
        return ("merge:" + f["_chain_cluster"], "merge:" + f["_chain_cluster"], False, False, "chain", False)
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


NEUTRAL_IMPORTANCE = 50  # DECISIONS 309: a page read but not scored (a page reader's copy keeps no links) counts this


def _measures(report: dict) -> dict[str, dict]:
    from .page_measures import index
    return index(report)


def read_set(report: dict) -> set[str]:
    """Every address whose content was read: `pages_read` and the pages with a stored measurement (DECISIONS 323)."""
    return pages_read(report) | set(((report.get("crawl") or {}).get("page_measures") or {}).keys())


def pages_read(report: dict) -> set[str]:
    """The addresses whose content was read: Maya's own pages (2xx with content) and the page reader's."""
    crawl = report.get("crawl") or {}
    urls = {p.get("url") for p in crawl.get("pages") or [] if isinstance(p, dict) and isinstance(p.get("status"), int)
            and 200 <= p["status"] < 300 and p.get("content_checks_eligible") is not False
            and not not_a_page(p.get("url"), p.get("content_type"))}  # DECISIONS 347: a file is never a page read
    urls |= {p.get("url") for p in (report.get("firecrawl") or {}).get("pages") or []
             if isinstance(p, dict) and p.get("outcome") == "read"}
    return {u for u in urls if isinstance(u, str)}


def _reach(urls: list[str], importance: dict[str, dict], home_importance: int,
           read_urls: set[str] | None = None) -> tuple[float, int, int, int, int]:
    """(reach, summed importance, pages counted, page addresses not read, pages read but not scored), DECISIONS 305
    and 309. Only pages that were read count (scored by the grouping and not a canonical scored only from its aliases);
    each once, a duplicate with its own score (capped at 20). A page that was read but has no importance (the page
    reader's copies keep no links between pages) counts NEUTRAL_IMPORTANCE: read, importance unknown, never "not read".
    A finding with no address, or only files (a sitemap, robots.txt), reaches the homepage. One whose page addresses
    were all left unread reaches nothing past the minimum (1.0)."""
    from .urls import non_page_kind
    addresses = [u for u in dict.fromkeys(urls) if isinstance(u, str) and u.startswith(("http://", "https://"))]
    pages = [u for u in addresses if not non_page_kind(u)]
    read = [u for u in pages if "importance" in (importance.get(u) or {}) and (importance.get(u) or {}).get("read") is not False]
    unscored = [u for u in pages if u not in read and u in (read_urls or set())
                and (importance.get(u) or {}).get("read") is not False]
    not_read = len(pages) - len(read) - len(unscored)
    if not read and not unscored and not not_read:
        return reach_of(home_importance), home_importance, 0, 0, 0
    total = sum(int(importance[u]["importance"]) for u in read) + NEUTRAL_IMPORTANCE * len(unscored)
    return reach_of(total), total, len(read) + len(unscored), not_read, len(unscored)


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
    read_urls = pages_read(report)
    default_lang = default_language(report)
    out: dict[tuple, dict] = {}
    findings_all = all_findings(report)
    mark_chain_clusters(findings_all)
    for f in findings_all:
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
        # DECISIONS 339: a card that joins findings of different severities (one cause, one fix) is scored on the
        # pages of its worst severity only: two High pages beside 88 Medium ones are not "90 pages at High". The other
        # pages are counted by severity (`severity_pages`) and the card says so; its examples come from the worst ones.
        band = [m for m in members if severity(m) == sev]
        band_urls = (urls if len(band) == len(members) else
                     list(dict.fromkeys(u for m in band for u in affected(m, lists))) or urls)
        severity_pages = ({} if len(band) == len(members) else
                          {s: len({u for m in members if severity(m) == s for u in affected(m, lists)})
                           for s in sorted({severity(m) for m in members}, key=_weight, reverse=True)})
        reach, total, counted, not_read, unscored = _reach(band_urls, importance, home_importance, read_urls)
        lead = members[0]
        reasons = [r for r in (confirm_reason(m, confirmations) for m in members) if r]
        languages = sorted({language_of(u, default_lang) or "" for u in urls} - {""})
        rows.append({
            "finding_ids": [m.get("id") for m in members], "members": members, "lead": lead,
            "check_id": lead.get("check_id"), "rule_id": lead.get("rule_id"), "title": lead.get("title"),
            "severity": sev, "severity_name": SEVERITY_NAME.get(sev, sev),
            "confidence": conf, "confidence_weight": CONFIDENCE_WEIGHT[conf],
            "reach": reach, "importance_sum": total, "pages_counted": counted, "addresses_not_read": not_read,
            "pages_read_unscored": unscored, "urls": urls, "severity_pages": severity_pages,
            "priority": _score(sev, conf, reach),
            "parts": {"severity": _weight(sev), "confidence": CONFIDENCE_WEIGHT[conf], "reach": reach,
                      "business": BUSINESS_RELEVANCE},
            "intent": bool(lead.get("intent")), "confirm_reason": reasons[0] if reasons else None,
            "own_limit": all(own_limit(m) for m in members),
            "languages": languages,
            "templates": sorted({(importance.get(u) or {}).get("template_key") for u in urls} - {None}),
            "examples": (worst_examples(members, merge_group(lead)["worst_by"])
                         if merge_group(lead) and merge_group(lead).get("worst_by") and worst_examples(members, merge_group(lead)["worst_by"])
                         else _examples(band_urls, band, lists, importance, default_lang)),
            "merge_group": (merge_group(lead) or {}).get("id"),
            "chain": chain_summary(members),
            "manual": next((manual(m, confirmations) for m in members if manual(m, confirmations)), None),
        })
    return rows


def _order(rows: list[dict]) -> list[dict]:
    """DECISIONS 301 (3): severity band first (a Medium is never below a Low), then priority within the band, then the
    report's own order (its first finding)."""
    return sorted(rows, key=lambda g: (-_weight(g["severity"]), -g["priority"], g["_index"]))


def select(report: dict, lists: dict | None = None, confirmations: dict | None = None, *,
           max_cards: int = MAX_CARDS, business: str | None = None) -> dict:
    """The selection a client report prints: cards, "Teyit edin", notes, own limits, appendix, key pages, counts.
    `business`: the person's business-type choice for this audit (DECISIONS 311), else the report's or the suggestion."""
    importance, summary = grouping(report, business)
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
    for g in rows:
        g["issue_type"] = issue_type(g)
        g["template_line"] = template_line(g, importance)
    # DECISIONS 324: P0-P3 of the team's sector method beside the severity; it changes no order, placement or score.
    from .priority_levels import annotate as p_levels
    p_levels(rows, importance, summary, pages_read(report), lists, confirmations)
    by_finding = {fid: g for g in rows for fid in g["finding_ids"]}
    coverage_box = coverage(report, limits, importance)
    kp = key_pages(report, rows, importance) or reader_key_pages(report, rows, summary.get("business_type"))
    return {
        "method": {"severity_weight": SEVERITY_WEIGHT, "confidence_weight": CONFIDENCE_WEIGHT,
                   "reach": f"1 + ln(1 + summed importance of the pages read / {REACH_UNIT}), at most {REACH_CAP}; "
                            "addresses not read add nothing (counted apart); a page read with no importance counts "
                            f"{NEUTRAL_IMPORTANCE}; no page address: the homepage",
                   "order": "severity band, then priority score", "merge_groups": [g["id"] for g in MERGE_GROUPS],
                   "business_relevance": BUSINESS_RELEVANCE, "max_cards": max_cards, "max_pages": MAX_PAGES,
                   "confirm_at_or_below": CONFIRM_AT_OR_BELOW,
                   "importance": "page grouping (DECISIONS 297, 298)" if importance else "not available"},
        "cards": cards, "confirm": confirm, "notes": notes, "own_limits": limits, "appendix_only": appendix_only,
        "rejected": [g for g in rows if g["placement"] == "rejected"],
        "groups": rows, "by_finding": by_finding,
        "key_pages": kp,
        "key_pages_reason": None if importance else key_pages_reason(report),
        # DECISIONS 311: the business type, and its first page types no page read was typed as ("not found among the
        # pages read", never "missing on the site"); none on a low-coverage audit.
        "business_type": _business_view(summary.get("business_type")),
        # DECISIONS 319: a type the page reader's key pages were given (DECISIONS 316) was found (airastana: "routes").
        "key_pages_not_found": [] if low_coverage(report) else
        [n for n in (summary.get("business_type") or {}).get("not_found") or []
         if n.get("type") not in {p.get("business_page_type") for p in kp}],
        "coverage": coverage_box,
        "low_coverage": low_coverage(report),
        # Stage 8a (DECISIONS 315): problems per template (segments).
        "templates": templates_table(rows, importance),
        "templates_reason": templates_reason(importance, report),  # DECISIONS 321 (5): why the table is empty
        "counts": {"findings": len(by_finding), "groups": len(rows), "cards": len(cards), "confirm": len(confirm),
                   "notes": len(notes), "own_limits": len(limits), "appendix_only": len(appendix_only),
                   "rejected": len([g for g in rows if g["placement"] == "rejected"]),
                   "problems": sum(1 for g in rows for m in g["members"] if severity(m) in PROBLEM),
                   # DECISIONS 301 (5): the one source of every count a client output prints.
                   "by_severity": {k: sum(1 for g in rows for m in g["members"] if severity(m) == k)
                                   for k in ("S1", "S2", "S3", "S4", "Info")},
                   "addresses": len({u for g in rows for u in g["urls"]}),
                   # Parts of the audit not assessed (DECISIONS 305): the coverage lines of that kind, one count.
                   "not_assessed": sum(1 for line in coverage_box["lines"] if line["kind"] == "not_assessed")},
        "grouping_summary": {k: summary.get(k) for k in ("method_version", "pages_scored", "page_types") if k in summary},
        "platform": (report.get("platform") or {}).get("name"),
        "_confirmations": confirmations or {},
        # DECISIONS 322: every scored page's type and importance, for the appendix's page sheets and the web page list.
        "_importance": importance,
        # DECISIONS 323: which addresses were read, and what was measured on each page read (stored, else worked out).
        "_pages_read": read_set(report),
        "_page_measures": _measures(report),
        # DECISIONS 341: each page's early-closed head as the check reads it (every page, not only the 40 the
        # evidence keeps), for its row in the appendix
        "_head_rows": head_rows(report),
        # DECISIONS 342: what the SEO team's checklist reads besides the findings (check statuses, connections, CrUX,
        # the site's shape), for its appendix sheet and the team report's page
        "_checklist_facts": checklist_facts(report),
    }


# ---------------------------------------------------------------- issue type and templates (Stage 8a, DECISIONS 315)

ISSUE_TYPES = ("issue", "warning", "opportunity")


def checklist_facts(report: dict) -> dict:
    from .checklist import facts
    return facts(report)


def head_rows(report: dict) -> dict[str, dict]:
    """{url: the TSEO-1 row of a page whose <head> a body element ended early} from the crawl's page records, the
    finding's own evidence row first (it holds what a saved report's pages may lack)."""
    from .checks.page_markup import ROBOTS_META, kept_in_head
    out: dict[str, dict] = {}
    for p in (report.get("crawl") or {}).get("pages") or []:
        a = (p.get("analysis") or {}) if isinstance(p, dict) else {}
        o = a.get("outside_head") or {}
        if not o.get("closed_early_by"):
            continue
        out[p["url"]] = {"url": p["url"], "closed_by": o["closed_early_by"], "canonical_after": o.get("canonical", 0),
                         "robots_after": sorted(ROBOTS_META & set(o.get("meta") or [])), "robots_content": o.get("robots_content"),
                         "hreflang_after": o.get("hreflang", 0), "meta_after": sorted(set(o.get("meta") or []) - ROBOTS_META)[:10],
                         "properties_after": sorted(set(o.get("properties") or []))[:10], "title_after": o.get("title", 0),
                         "kept_in_head": kept_in_head(a),
                         **({"head_tags": a["head_tags"]} if a.get("head_tags") else {})}
    for c in report.get("checks") or []:
        for f in c.get("findings") or []:
            if (f.get("rule_id") or "").startswith("tseo1.head_closed"):
                for r in (f.get("evidence") or {}).get("pages") or []:
                    if isinstance(r, dict) and r.get("url"):
                        out[r["url"]] = {**out.get(r["url"], {}), **r}
    return out


def _issue_catalogue() -> dict:
    import json
    from pathlib import Path
    global _ISSUE_CATALOGUE
    try:
        return _ISSUE_CATALOGUE
    except NameError:
        _ISSUE_CATALOGUE = json.loads((Path(__file__).parent / "issue_types.json").read_text(encoding="utf-8"))
        return _ISSUE_CATALOGUE


def rule_type(rule_id: str | None) -> str:
    """The rule's own type: issue (Sorun), warning (Kontrol edin) or opportunity (Fırsat); issue when unknown."""
    return (_issue_catalogue().get("rules") or {}).get(rule_id or "", "issue")


def issue_type_label(kind: str, lang: str) -> str:
    return (_issue_catalogue().get("labels") or {}).get(lang, {}).get(kind) or kind


def issue_type(g: dict) -> str:
    """A group's type beside its severity. Waiting in "Teyit edin": warning. Otherwise the most serious of its
    members' rule types (issue over warning over opportunity); a warning rule a person confirmed is an issue. Never
    changes severity, placement or order."""
    if g.get("placement") == "confirm":
        return "warning"
    kinds = {rule_type(m.get("rule_id")) for m in g.get("members") or []} or {"issue"}
    kind = next(k for k in ISSUE_TYPES if k in kinds)
    if kind == "warning" and (g.get("manual") or {}).get("result") == "confirmed":
        return "issue"
    return kind


TEMPLATE_SHARE = 0.8   # a card names a template when this share of its pages read are in it (owner, Stage 8a)
TEMPLATE_MIN_PAGES = 5  # ... and at least this many


def _template_of(record: dict | None) -> str | None:
    """The page's template, its language folder left out: /en/collections/*/products/* is the same theme template as
    /collections/*/products/*, so one fix covers both (DECISIONS 315)."""
    from .page_groups import is_locale
    key = (record or {}).get("template_key") or None
    if not key:
        return None
    segs = key.split("/")
    if len(segs) > 2 and segs[0] == "" and is_locale(segs[1]):
        key = "/" + "/".join(segs[2:])
    return key


def template_kind(pages: list[dict]) -> str | None:
    """The page type most of a template's pages have (the business type's when one applies)."""
    from collections import Counter
    kinds = Counter((r.get("business_page_type") if r.get("business_page_type") not in (None, "other") else r.get("page_type"))
                    for r in pages)
    return kinds.most_common(1)[0][0] if kinds else None


def template_line(g: dict, importance: dict[str, dict]) -> dict | None:
    """{"template", "kind", "pages"} when one template holds most of a card's pages read (one template fix covers
    them), else None."""
    from collections import Counter
    read = [u for u in g.get("urls") or [] if u in importance and importance[u].get("read") is not False]
    if len(read) < TEMPLATE_MIN_PAGES:
        return None
    counts = Counter(_template_of(importance[u]) for u in read)
    counts.pop(None, None)
    if not counts:
        return None
    template, n = counts.most_common(1)[0]
    if n < TEMPLATE_MIN_PAGES or n / len(read) < TEMPLATE_SHARE:
        return None
    members = [importance[u] for u in read if _template_of(importance[u]) == template]
    return {"template": template, "kind": template_kind(members), "pages": n}


def templates_table(rows: list[dict], importance: dict[str, dict], limit: int | None = None) -> list[dict]:
    """Problems per template (segments): every template with pages read, its page count, how many of its pages a
    problem touches, the problem groups and the cards. Largest first."""
    from collections import defaultdict
    pages_of: dict[str, list[str]] = defaultdict(list)
    for u, r in importance.items():
        t = _template_of(r)
        if t and r.get("read") is not False:
            pages_of[t].append(u)
    out = []
    for t, urls in pages_of.items():
        members = set(urls)
        hit = [g for g in rows if g.get("placement") not in ("rejected", "own_limit") and g["severity"] in PROBLEM
               and members & set(g.get("urls") or [])]
        out.append({"template": t, "kind": template_kind([importance[u] for u in urls]), "pages": len(urls),
                    "pages_with_problems": len({u for g in hit for u in g["urls"] if u in members}),
                    "problem_groups": len(hit), "cards": sorted(g["card"] for g in hit if g.get("placement") == "card"),
                    "worst": max((g["severity"] for g in hit), key=_weight, default=None),
                    "finding_ids": sorted({fid for g in hit for fid in g["finding_ids"]})})
    out.sort(key=lambda r: (-r["pages"], -r["problem_groups"], r["template"]))
    return out[:limit] if limit else out


def templates_reason(importance: dict[str, dict], report: dict) -> str | None:
    """Why the templates table is empty (DECISIONS 321 (5)), None when it has rows: "reader_only" / "no_pages" (no page
    scored, the key pages' reasons); "not_read" when the pages that have an address pattern were all not read (block
    pages or errors; airastana: Imperva answered Maya's 50 requests, the 13 pages read another way are not grouped);
    "no_template" when pages were read and none shares a pattern."""
    if not importance:
        return key_pages_reason(report)
    keyed = [r for r in importance.values() if _template_of(r)]
    if any(r.get("read") is not False for r in keyed):
        return None
    return "not_read" if keyed else "no_template"


def platform_steps(rule_id: str | None, platform: str | None, lang: str) -> list[str] | None:
    """The catalogue's steps for this rule on this platform (`steps_by_platform`, e.g. Shopify writes its own sitemap,
    DECISIONS 300 (7)), or None. The release gate checks the platform against the report's (RG-11)."""
    if not rule_id or not platform:
        return None
    from .facts import _catalogue
    entry = (_catalogue().get(rule_id) or {}).get("steps_by_platform") or {}
    return ((entry.get(platform) or {}).get(lang)) or None


# ---------------------------------------------------------------- key pages and coverage

def is_homepage(url: str, record: dict | None = None) -> bool:
    """The site's root or a language version of it (`/`, `/tr/`, `/en-gb/`): a homepage whatever the grouping typed it
    (DECISIONS 309), as is a page the grouping typed one."""
    from .page_groups import is_locale
    if (record or {}).get("page_type") == "home":
        return True
    parts = [p for p in (urlsplit(url).path or "/").split("/") if p]
    return not parts or (len(parts) == 1 and is_locale(parts[0]))


def _business_view(info: dict | None) -> dict | None:
    """What a client output says about the business type: id, label, who chose it, the suggestion and its reason."""
    if not isinstance(info, dict) or "id" not in info:
        return None
    sug = info.get("suggestion") or {}
    return {"id": info["id"], "label": info.get("label"), "chosen_by": info.get("chosen_by"),
            "suggestion": {"id": sug.get("id"), "label": sug.get("label"), "reason": sug.get("reason")},
            "importance_source": "links" if info["id"] == "diger" else f"profile:{info['id']}"}


def main_homepage(report: dict, importance: dict[str, dict]) -> str | None:
    """The homepage in the site's main language: the start address's final page when the grouping knows it, else the
    start address when it was read and scored."""
    for url, g in importance.items():
        if g.get("read") is not False and str(g.get("page_type_basis") or "").startswith("the start address's final page"):
            return url
    home = _home(report)
    for url in (home, home.rstrip("/") + "/", home.rstrip("/")):
        if url in importance and importance[url].get("read") is not False:
            return url
    return None


def key_pages(report: dict, rows: list[dict], importance: dict[str, dict], limit: int = KEY_PAGES) -> list[dict]:
    """The most important pages read (importance rank), with what the cards and the confirm list say about each.
    DECISIONS 309: the main-language homepage first, then the rest by importance; the rank shown is the place in this
    list (1, 2, 3 ...): a page that was not read leaves no gap. DECISIONS 312: the homepage's language versions read
    (`/tr/`, `/en/`, `/ru/`, `/ar/`) are one row ("Ana sayfa (4 dil)": `languages`), its cards and checks those of
    every version, so the other nine places go to other pages. The row's importance is the main homepage's own."""
    read = [(u, g) for u, g in importance.items() if g.get("read") is not False]
    read.sort(key=lambda kv: (kv[1].get("importance_rank") or 10**9, -(kv[1].get("importance") or 0)))
    main = main_homepage(report, importance)
    homes = [u for u, g in read if u != main and is_homepage(u, g)]
    if not main and homes:
        main, homes = homes[0], homes[1:]
    rest = [(u, g) for u, g in read if u != main and not is_homepage(u, g)]
    slots = limit - (1 if main else 0)
    # DECISIONS 312: with a business type, every page type of its profile found among the pages read keeps a place for
    # its best page (moodist: 19 treatment pages above "Doktor ve ekip"); the other places go by importance, and the
    # list stays in importance order. "Diğer" has no profile types: the list is the importance order, as before.
    best: dict[str, int] = {}
    for i, (_, g) in enumerate(rest):
        kind = g.get("business_page_type")
        if kind and kind not in ("home", "other", "policy", "utility"):
            best.setdefault(kind, i)
    keep = set(sorted(best.values())[:slots])
    for i in range(len(rest)):
        if len(keep) >= slots:
            break
        keep.add(i)
    chosen = ([(main, importance[main])] if main else []) + [rest[i] for i in sorted(keep)]
    out = []
    for n, (url, g) in enumerate(chosen[:limit], 1):
        group = [url] + homes if url == main else [url]
        cards = [x for x in rows if x.get("placement") == "card" and any(u in x["urls"] for u in group)]
        confirm = [x for x in rows if x.get("placement") == "confirm" and any(u in x["urls"] for u in group)]
        worst = max((x["severity"] for x in cards), key=_weight, default=None)
        home = url == main or is_homepage(url, g)
        unknown = importance_unknown(g, cards) if url == main else None
        out.append({"importance_unknown": unknown,"url": url, "page_type": "home" if home else g.get("page_type"),
                    "business_page_type": "home" if home else g.get("business_page_type"),
                    "importance_source": g.get("importance_source"),
                    "importance": g.get("importance"), "rank": n, "importance_rank": g.get("importance_rank"),
                    "main_homepage": url == main, "languages": group if url == main and homes else [],
                    "cards": sorted({x["card"] for x in cards}), "worst": worst, "confirm": len(confirm)})
    return out


LOW_COVERAGE_PAGES = 10  # DECISIONS 309: fewer pages read than this is low coverage
LOW_COVERAGE_SHARE = 0.2  # ... as is fewer than this share of the pages the audit planned to read


def low_coverage(report: dict) -> dict | None:
    """{"pages_read", "planned"} when very few pages were read: under LOW_COVERAGE_PAGES, or under LOW_COVERAGE_SHARE
    of the plan (the page cap). None otherwise. The team report and the web app show a banner; a client brief is not
    made from such an audit (`client_brief_allowed`)."""
    cov = (report.get("audit_status") or {}).get("content_coverage") or {}
    read = cov.get("pages_read")
    if not isinstance(read, int):
        read = len(pages_read(report))
    planned = ((report.get("crawl") or {}).get("config") or {}).get("max_pages")
    planned = planned if isinstance(planned, int) and planned > 0 else None
    if read < LOW_COVERAGE_PAGES or (planned and read < LOW_COVERAGE_SHARE * planned):
        return {"pages_read": read, "planned": planned}
    return None


def client_brief_allowed(report: dict) -> tuple[bool, str | None]:
    """(allowed, reason): the gate every client brief made from an audit passes first (DECISIONS 309). Low coverage
    blocks it: a brief written from a handful of pages would speak for a site it did not see."""
    return (False, "low_coverage") if low_coverage(report) else (True, None)


# DECISIONS 313: the cards whose problem holds a homepage's importance down: its canonical names another address (IDX-4),
# or it redirects (IDX-2, IDX-3). Their rule ids start with these.
IMPORTANCE_BLOCKERS = (("idx4.", "canonical"), ("idx3.", "redirect"), ("idx2.", "redirect"))


def importance_unknown(g: dict, cards: list[dict]) -> dict | None:
    """{"reason": "canonical" | "redirect", "card": n} when the main homepage is capped as not indexable and a card
    covering it is a canonical or redirect problem: its score then says nothing about how important it is (moodist
    `/tr/`: 100 for links, depth and type, capped at 20 because its canonical names `/tr/tr/`). None otherwise."""
    if (g.get("importance_parts") or {}).get("capped") != "not indexable":
        return None
    for card in sorted(cards, key=lambda x: x["card"]):
        rule = str(card.get("rule_id") or "")
        for prefix, reason in IMPORTANCE_BLOCKERS:
            if rule.startswith(prefix):
                return {"reason": reason, "card": card["card"]}
    return None


def reader_key_pages(report: dict, rows: list[dict], business: dict | None, limit: int = KEY_PAGES) -> list[dict]:
    """DECISIONS 316: when no page read could be scored because the pages were read only through the page reader (its
    copies keep no links, and importance needs them), the pages it read: the homepage first, then by the business
    type's page-type rank, then in reading order; importance "not computed (read only through the page reader)"."""
    fc = report.get("firecrawl") or {}
    read = [r.get("url") for r in fc.get("pages") or [] if isinstance(r, dict) and r.get("outcome") == "read"] if fc.get("used") else []
    read = [u for u in dict.fromkeys(read) if isinstance(u, str)]
    if not read:
        return []
    from . import business_types as bt
    crawl = report.get("crawl") or {}
    folders = tuple(((crawl.get("locales") or {}).get("folders")) or ())
    pid = (business or {}).get("id") or bt.DEFAULT
    prof = bt.profile(pid)
    ranks = {t["id"]: t.get("rank") or 99 for t in prof["page_types"]}
    out = []
    for i, url in enumerate(read):
        segs = [s for s in urlsplit(url).path.split("/") if s]
        home = not segs or (len(segs) == 1 and (segs[0].lower() in folders or language_of(url, None)))
        kind = "home" if home else bt.classify(prof, bt.page_facts(url, None, folders=folders))[0] if pid != bt.DEFAULT else "other"
        out.append((0 if home else ranks.get(kind, 99), i, url, kind))
    out.sort()
    rows_out = []
    for n, (_, _, url, kind) in enumerate(out[:limit], 1):
        cards = [x for x in rows if x.get("placement") == "card" and url in x["urls"]]
        confirm = [x for x in rows if x.get("placement") == "confirm" and url in x["urls"]]
        rows_out.append({"importance_unknown": {"reason": "reader_only", "card": None}, "url": url,
                         "page_type": "home" if kind == "home" else None,
                         "business_page_type": kind if pid != bt.DEFAULT else None, "importance_source": "reader",
                         "importance": None, "rank": n, "importance_rank": None, "main_homepage": kind == "home" and n == 1,
                         "languages": [], "cards": sorted({x["card"] for x in cards}),
                         "worst": max((x["severity"] for x in cards), key=_weight, default=None), "confirm": len(confirm)})
    return rows_out


def key_pages_reason(report: dict) -> str:
    """Why no page could be scored (the key pages list is empty): "reader_only" when the pages were read only through
    a page reader after Maya's crawler was blocked (the saved copies keep no links, and importance needs the links
    between pages); "no_pages" otherwise (nothing with content was read)."""
    crawl = report.get("crawl") or {}
    own = [p for p in crawl.get("pages") or [] if isinstance(p, dict) and p.get("analysis")]
    reader = report.get("firecrawl") or {}
    read_by_reader = [p for p in reader.get("pages") or [] if isinstance(p, dict) and p.get("outcome") == "read"]
    return "reader_only" if not own and read_by_reader else "no_pages"


LAB_PART = "Lighthouse lab metrics (optional)"
LAB_REASON = ("No lab test was run (--pagespeed); Core Web Vitals were assessed from Google's real-visitor data "
              "(Chrome UX Report).")


def not_assessed_parts(report: dict) -> list[dict]:
    """The parts of the audit not assessed, one per distinct (part, reason), with the checks each applies to: the one
    count every client output prints ("Değerlendirilmeyen kapsam", DECISIONS 305). A check not assessed as a whole is
    one part (its title, its summary). Left out: the parts that restate the addresses found and not read
    (`coverage.UNREAD_RESTATEMENTS`): the coverage line "N addresses not read" says that once. The answer-engine panel
    counts too."""
    from .coverage import UNREAD_RESTATEMENTS
    gaps: dict[tuple, dict] = {}
    for check in (report.get("checks") or []) + (report.get("answer_engine_panel") or []):
        parts = (check.get("coverage") or {}).get("not_assessed") or []
        if check.get("status") == "not_assessed" and not parts:
            parts = [{"part": check.get("title"), "reason": check.get("summary")}]
            if check.get("check_id") == "PRF-3" and (report.get("crux") or {}).get("status") == "assessed":
                # DECISIONS 339: Google's real-visitor data (CrUX) assessed Core Web Vitals; only the lab test is not
                parts = [{"part": LAB_PART, "reason": LAB_REASON}]
        for part in parts:
            if part.get("part") in UNREAD_RESTATEMENTS:
                continue
            gap = gaps.setdefault((part.get("part"), part.get("reason")), {
                "part": part.get("part"), "reason": part.get("reason"),
                "text": f"{part.get('part') or ''}: {part.get('reason') or ''}".strip(": "), "checks": []})
            if check.get("check_id") not in gap["checks"]:
                gap["checks"].append(check.get("check_id"))
    return list(gaps.values())


def block_pages_line(report: dict) -> dict | None:
    """DECISIONS 317: Maya's crawler got block pages and the page reader read the site: the block answers did not use
    up the page limit. {"kind": "block_pages", "blocked", "allowed", "read", "plan", "stopped"}; None otherwise."""
    reader = report.get("firecrawl") or {}
    cov = reader.get("coverage") or {}
    limit = cov.get("page_limit")
    if not reader.get("used") or not isinstance(limit, dict) or not limit.get("block_answers"):
        return None
    # DECISIONS 350 (isbank: "en çok 2 sayfa okuyabilirdi, 91 sayfa okudu"): the limit is on pages Maya did not read;
    # the reader also reads Maya's own pages again. Both counts are said apart.
    maya_read = {p.get("url") for p in (report.get("crawl") or {}).get("pages") or [] if isinstance(p, dict)
                 and isinstance(p.get("status"), int) and 200 <= p["status"] < 300 and p.get("content_checks_eligible") is not False}
    rows = [r for r in reader.get("pages") or [] if isinstance(r, dict) and r.get("outcome") == "read"]
    new = len({r.get("url") for r in rows} - maya_read) if rows else None
    return {"kind": "block_pages", "blocked": limit["block_answers"], "allowed": limit.get("reader_new_pages_allowed"),
            "read": reader.get("pages_read") or 0, "new": new, "plan": limit.get("plan"), "maya_read": limit.get("maya_pages_read"),
            "stopped": cov.get("not_requested_because")}


def edit_pages_line(report: dict) -> dict | None:
    """DECISIONS 351: the CMS edit and preview addresses (?efl--edit=1, ?preview=) the crawl met, read or linked: each
    is its clean page, so none counts as a page read. {"kind": "edit_pages", "read", "linked", "examples"} or None."""
    from .urls import edit_preview
    crawl = report.get("crawl") or {}
    pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict)]
    read = sorted({p.get("url") for p in pages if edit_preview(p.get("url"))})
    linked = sorted({(e.get("target") or "").split("#")[0] for p in pages for e in p.get("outlinks") or []
                     if edit_preview((e.get("target") or "").split("#")[0])})
    if not read and not linked:
        return None
    return {"kind": "edit_pages", "read": len(read), "linked": len(linked), "examples": (read or linked)[:3]}


def coverage(report: dict, limits: list[dict], records: dict[str, dict] | None = None) -> dict:
    """What Maya read and what it could not, for the coverage section: our limits, never a client problem."""
    crawl = report.get("crawl") or {}
    status = (report.get("audit_status") or {}).get("content_coverage") or {}
    counts = report.get("page_counts") or {}
    cfg = crawl.get("config") or {}
    lines: list[dict] = []
    from .sampling import known_not_read as unread_shown  # DECISIONS 335
    unread = unread_shown(report)
    if crawl.get("stop_reason") == "page_cap":
        lines.append({"kind": "page_cap", "pages": cfg.get("max_pages"),
                      "not_read": unread or len(crawl.get("not_fetched_urls") or [])})
    if crawl.get("deadline_hit") or report.get("time_limit_cuts"):
        cuts = report.get("time_limit_cuts")
        lines.append({"kind": "time_budget", "seconds": cfg.get("time_limit_s"),
                      "cut": len(cuts) if isinstance(cuts, list) else cuts or None})
    for g in limits:
        # DECISIONS 354: the check id goes with the title, so its Turkish frame is found (reader notes are ACC-9's).
        lines.append({"kind": "reader", "finding_ids": g["finding_ids"], "title": g["title"], "check_id": g.get("check_id") or "ACC-9"})
    block = block_pages_line(report)
    if block:
        lines.append(block)
    for gap in not_assessed_parts(report):
        lines.append({"kind": "not_assessed", **gap})
    from .sampling import coverage as sampled  # DECISIONS 327: an Akıllı audit's pages read per page type
    rows = sampled(report, records) if (report.get("crawl") or {}).get("sampling") else []
    if rows:
        lines.append({"kind": "sampling", "rows": rows})
    edits = edit_pages_line(report)  # DECISIONS 351: CMS edit and preview addresses, not pages of their own
    if edits:
        lines.append(edits)
    from .read_sources import summary as by_source  # DECISIONS 348: each source's reads, block pages and 429s
    sources = by_source(report)
    if sources:
        lines.insert(0, {"kind": "sources", **sources})
    reader = report.get("firecrawl") or {}
    return {"pages_read": status.get("pages_read", counts.get("pages_checked")),
            "known_not_read": unread,
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
                        "merge_group": g.get("merge_group"), "issue_type": g.get("issue_type"),
                        "p_level": (g.get("p_level") or {}).get("level"),
                        "pages_read": g.get("pages_counted"), "not_read": g.get("addresses_not_read"),
                        "read_unscored": g.get("pages_read_unscored"),
                        "manual": (lambda c: " · ".join(str(c[k]) for k in ("result", "by", "date", "seen") if c.get(k))
                                   + (f" · {c['note']}" if c.get("note") else ""))(manual(m, selection.get("_confirmations")))
                        if manual(m, selection.get("_confirmations")) else "",
                        "title": m.get("title"), "how_to_fix": m.get("how_to_fix"),
                        "scope_count": (m.get("scope") or {}).get("count"), "urls": affected(m, lists),
                        "finding": m})
    return out


def merge_table() -> list[dict]:
    """The merge groups as rows (for the appendix, the docs and the tests): id, cause, rules, title, fix."""
    return [{"id": g["id"], "cause": g["cause"], "rules": list(g["rules"]), "title": g["title"], "fix": g["fix"]}
            for g in (*MERGE_GROUPS, CHAIN_GROUP)]
