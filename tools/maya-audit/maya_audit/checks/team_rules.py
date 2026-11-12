"""Rules from the SEO team's technical review (Efsa's enpara report of 2026-11-12, DECISIONS 343).

Each makes an ordinary finding in the check it belongs to, from data the crawl already reads; none sends a request.
They run with the checklist's quick checks (`quick_rules.findings`), so a live audit and a saved report (offline,
`maya_audit.reassess_rules`) get the same rule. Every page record in the evidence carries `row`, the line its Ek row
shows ({"tr", "en"}): the status chain, the duplicate pair, the schema types, the variable text or the shared title/H1.

| Rule id | Check | What it reports |
|---|---|---|
| idx1.error_redirect | IDX-1 | missing pages answer a redirect to an error page instead of 404/410 |
| idx8.self_canonical_copies | IDX-8 | two addresses of one page (/x and /x/default.aspx, /anasayfa and /), each 200 and its own canonical |
| str3.product_on_article | STR-3 | Product or AggregateRating markup on blog or article pages |
| str1.subpage_copies_parent | STR-1 | sub-pages with the parent's title/H1/description, canonical to themselves, hreflang to the parent |
| str2.h1_parent_name | STR-2 | a sub-page whose H1 is its parent section's name |

Unfilled template variables in JSON-LD and meta tags (the review's fourth point) are STR-13's: it already reads the
JSON-LD, meta tags, title, links and visible text. DECISIONS 343 adds the %%...%% form (config.TEMPLATE_MARKERS) and
gives the JSON-LD and meta-tag findings a rule of their own, `str13.markers_data`, with its own card.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from ..findings import Finding, Severity, scope_for
from ..models import Confidence

GOOGLE = "Google AI Overviews / AI Mode"
COPILOT = "Microsoft Copilot (Bing index)"
DOCUMENTED = "Documented (Google Search Central)"
MAX_ROWS = 500  # evidence records kept per finding: the Ek lists every affected page

# An error page: a path segment or file named for an error, or ASP.NET's "aspxerrorpath" query.
_ERROR_SEGMENT = re.compile(r"^(?:404|410|500|error|errors|hata|not-?found|page-?not-?found|sayfa-?bulunamadi|"
                            r"bulunamadi|sayfa-?yok)(?:\.[a-z]{2,5})?$", re.IGNORECASE)
_ERROR_QUERY = ("aspxerrorpath", "errorpath")
ARTICLE_TYPES = frozenset({"Article", "BlogPosting", "NewsArticle", "TechArticle", "Report"})
PRODUCT_TYPES = frozenset({"Product", "AggregateRating"})

ERROR_REDIRECT_EXPECTED = "an address that does not exist answers 404 or 410 itself"
ERROR_REDIRECT_FIX = ("Make the server answer 404 (or 410 for removed pages) at the missing address itself and show the "
                      "error page's content there, instead of redirecting to an error page. On IIS/ASP.NET, set "
                      "customErrors redirectMode=\"ResponseRewrite\" (or httpErrors existingResponse=\"Replace\") so the "
                      "error page is served with the 404 status at the requested address.")
ERROR_REDIRECT_NOTE = ("Google treats a redirect to an error page as a soft 404 at best; at worst the missing address "
                       "stays indexed as a redirect. Each row gives the status chain as Maya recorded it.")
COPIES_EXPECTED = "one page has one address; any other address of it redirects there with a 301"
COPIES_FIX = ("Choose the main address of each pair (the one the menu and the sitemap use) and redirect the other one "
              "to it with a 301; until then, point the second address's canonical to the main one. Link only to the "
              "main address.")
PRODUCT_ARTICLE_EXPECTED = "blog and article pages carry Article/BlogPosting markup, not Product or review ratings"
PRODUCT_ARTICLE_FIX = ("Remove the Product and AggregateRating markup from the blog and article pages and keep "
                       "Article/BlogPosting (with FAQPage where the page shows real questions and answers). Product "
                       "markup with ratings belongs on a page that sells that product and shows its reviews.")
PRODUCT_ARTICLE_NOTE = ("Google's structured data rules: markup must describe the page's main content, and review "
                        "ratings must come from visible reviews of the item; ratings on an article can lose the site "
                        "its rich results or bring a manual action.")
SUBPAGE_EXPECTED = "each sub-page has its own title, H1 and description, and hreflang to its own language versions"
SUBPAGE_FIX = ("Give each sub-page its own title, H1 and meta description about its own topic, and make its hreflang "
               "name the sub-page's own language versions (itself for its language), not the parent page.")
SUBPAGE_NOTE = ("An hreflang that names the parent tells engines the sub-page is a language version of the parent, "
                "while its canonical says it is a page of its own; with the same title and H1, engines see copies.")
H1_PARENT_EXPECTED = "a sub-page's H1 names its own topic"
H1_PARENT_FIX = ("Write each sub-page's own topic as its H1 (its title says it, e.g. \"Fatura Ödemeleri\"), and keep "
                 "the section name in the breadcrumb or above the H1 as plain text.")


# -- helpers -----------------------------------------------------------------------------------------------------------

def _key(url: str) -> str:
    parts = urlsplit(url or "")
    path = unquote(parts.path).rstrip("/") or "/"
    return f"{parts.netloc.lower()}{path}" + (f"?{parts.query}" if parts.query else "")


def _short(url: str) -> str:
    parts = urlsplit(url or "")
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def h1s(analysis: dict) -> list[str]:
    out = []
    for h in analysis.get("h1_elements") or []:
        text = h.get("text") if isinstance(h, dict) else h
        if _text(text):
            out.append(_text(text))
    return out


def description(analysis: dict) -> str:
    for m in analysis.get("meta") or []:
        if isinstance(m, dict) and (m.get("name") or "").lower() == "description":
            return _text(m.get("content"))
    return ""


def self_canonical(url: str, analysis: dict) -> bool:
    canon = [urljoin(url, c) for c in analysis.get("canonicals") or [] if c]
    return not canon or all(_key(c) == _key(url) for c in canon)


def _same(a: str, b: str) -> bool:
    return bool(a) and a.casefold() == b.casefold()


def _ok(page) -> bool:
    return isinstance(getattr(page, "status", None), int) and 200 <= page.status < 300 and isinstance(page.analysis, dict)


def error_page(url: str) -> bool:
    parts = urlsplit(url or "")
    if any(k.lower() in _ERROR_QUERY for k, _ in parse_qsl(parts.query, keep_blank_values=True)):
        return True
    return any(_ERROR_SEGMENT.match(unquote(s)) for s in parts.path.split("/") if s)


def _parent(url: str, by_key: dict) -> object | None:
    """The nearest read page above `url` in its path (never the homepage: every page is under it)."""
    parts = urlsplit(url)
    segs = [s for s in parts.path.split("/") if s]
    for n in range(len(segs) - 1, 0, -1):
        page = by_key.get(_key(f"{parts.scheme}://{parts.netloc}/" + "/".join(segs[:n])))
        if page is not None:
            return page
    return None


def _row(tr: str, en: str) -> dict:
    return {"tr": tr, "en": en}


# -- 1. idx1.error_redirect --------------------------------------------------------------------------------------------

def error_redirects(pages, redirects: list[dict] | None, probe: dict | None, key_urls=frozenset()) -> list[Finding]:
    """Addresses that answer a redirect whose target is an error page (by its address, or answering 404/410), from the
    crawl's redirect records and the missing-page probe."""
    from .stage8_rules import redirect_records
    records = redirects if redirects is not None else redirect_records(pages)
    rows, urls = [], []
    for rec in records or []:
        hops = rec.get("hops") or []
        if not hops or not all(isinstance(h.get("status"), int) and 300 <= h["status"] < 400 for h in hops):
            continue
        final, final_status = rec.get("final") or (hops[-1].get("target") or ""), rec.get("final_status")
        if not (error_page(final) or any(error_page(h.get("target") or "") for h in hops)):
            continue
        chain = " → ".join([str(h["status"]) for h in hops] + [_short(final)] + ([str(final_status)] if final_status else []))
        rows.append({"url": rec["url"], "statuses": [h["status"] for h in hops], "final": final, "final_status": final_status,
                     "row": _row(f"{chain} (404/410 yerine yönlendirme)", f"{chain} (a redirect instead of 404/410)")})
        urls.append(rec["url"])
    probe_row = None
    if isinstance(probe, dict) and probe.get("sent"):
        status, target = probe.get("status"), probe.get("redirect_location") or probe.get("final_url") or ""
        if isinstance(status, int) and 300 <= status < 400 and error_page(target):
            chain = f"{status} → {_short(target)}"
            probe_row = {"url": probe.get("url"), "statuses": [status], "final": target, "probe": True,
                         "row": _row(f"Maya'nın uydurduğu adres: {chain}", f"Maya's made-up address: {chain}")}
    if not rows and not probe_row:
        return []
    evidence_rows = ([probe_row] if probe_row else []) + rows[:MAX_ROWS]
    n = len(rows) or 1  # only the made-up address: one
    scope_urls = urls or [probe_row["url"]]
    return [Finding("IDX-1", f"{n} missing address(es) answer a redirect to an error page instead of 404/410", Severity.S3, Confidence.VERIFIED,
                    "Documented (Google: a missing page should return 404 or 410)", [GOOGLE, COPILOT], scope_for(scope_urls),
                    {"pages": evidence_rows, "redirecting_to_error": len(rows), "probe": probe_row,
                     "rule": "a 3xx answer whose target is an error page (an address named 404/error/hata/not-found, "
                             "or ASP.NET's aspxerrorpath), from the crawl's redirect records and the missing-page probe"},
                    ERROR_REDIRECT_EXPECTED, ERROR_REDIRECT_FIX, notes=[ERROR_REDIRECT_NOTE],
                    importance_tier=0 if any(u in key_urls for u in urls) else 2, rule_id="idx1.error_redirect")]


# -- 2. idx8.self_canonical_copies -------------------------------------------------------------------------------------

# A last path segment that names the page it sits under: /anasayfa is /, /sss/default.aspx is /sss.
ALIAS_SEGMENTS = frozenset({"default.aspx", "default.asp", "default.htm", "default.html", "index.html", "index.htm",
                            "index.php", "index.aspx", "index.asp", "index.jsp", "anasayfa", "ana-sayfa", "home",
                            "homepage", "default", "index"})


def _plain(url: str) -> str:
    parts = urlsplit(url or "")
    path = re.sub(r"\.(?:aspx?|php|html?|jsp)$", "", unquote(parts.path).lower().rstrip("/"))
    return f"{parts.netloc.lower()}{path}?{parts.query}"


def alias_key(url: str) -> str:
    """One key for the addresses of one page: host, the path lowercased without a trailing slash or a last segment
    that names the page above it, and no query (DECISIONS 343)."""
    parts = urlsplit(url or "")
    segs = [s for s in unquote(parts.path).lower().split("/") if s]
    if segs and segs[-1] in ALIAS_SEGMENTS:
        segs = segs[:-1]
    return f"{parts.netloc.lower()}/" + "/".join(segs)

def _hreflang_targets(analysis: dict, url: str = "") -> set[str]:
    return {_key(urljoin(url, h["href"])) for h in analysis.get("hreflang") or [] if isinstance(h, dict) and h.get("href")}


def self_canonical_copies(read, inlinks: dict[str, int] | None = None, key_urls=frozenset(),
                          skip: set[str] | None = None) -> list[Finding]:
    groups: dict[tuple, list] = defaultdict(list)
    for p in read:
        a = p.analysis
        if not _ok(p) or not a.get("text_sha256") or not self_canonical(p.url, a) or p.url in (skip or ()):
            continue
        groups[(alias_key(p.url), a["text_sha256"], _text(a.get("title")).casefold(), tuple(h.casefold() for h in h1s(a)))].append(p)
    rows, urls, pairs = [], [], 0
    for members in groups.values():
        if len(members) < 2:
            continue
        # Only a trailing slash, a file extension or the letter case apart: idx8.two_addresses reports those.
        if len({_plain(p.url) for p in members}) == 1:
            continue
        # Language versions of one page say so with hreflang: not copies.
        if any(_key(q.url) in _hreflang_targets(p.analysis, p.url) for p in members for q in members if p is not q):
            continue
        # The main address: the homepage's root when it is one of them, else the most linked, else the shortest.
        main = sorted(members, key=lambda p: (urlsplit(p.url).path not in ("", "/"), -(inlinks or {}).get(p.url, 0),
                                              len(_short(p.url)), p.url))[0]
        pairs += len(members) - 1
        for p in members:
            if p is main:
                others = ", ".join(_short(q.url) for q in members if q is not main)
                row = _row(f"asıl adres önerisi; aynı içerik, başlık ve H1: {others}; ikisi de 200 ve kendini kanonik gösteriyor",
                           f"suggested main address; same text, title and H1: {others}; both 200 and their own canonical")
            else:
                row = _row(f"{_short(main.url)} ile aynı içerik, başlık ve H1; 200 ve kendini kanonik gösteriyor → {_short(main.url)} adresine 301",
                           f"same text, title and H1 as {_short(main.url)}; 200 and its own canonical → 301 to {_short(main.url)}")
            rows.append({"url": p.url, "main": main.url, "title": _text(p.analysis.get("title")), "row": row})
            urls.append(p.url)
    if not rows:
        return []
    return [Finding("IDX-8", f"{pairs} second address(es) of a page answer 200 and name themselves canonical",
                    Severity.S3, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                    {"pages": rows[:MAX_ROWS], "second_addresses": pairs,
                     "rule": "addresses of one page (the same path but for case, a trailing slash, the query, or a last "
                             "segment such as /anasayfa, /default.aspx or /index.html) read with the same visible text, "
                             "title and H1, each answering 200 with no canonical to another address, and no hreflang "
                             "between them"},
                    COPIES_EXPECTED, COPIES_FIX, importance_tier=0 if any(u in key_urls for u in urls) else 2,
                    rule_id="idx8.self_canonical_copies")]


# -- 3. str3.product_on_article ----------------------------------------------------------------------------------------

def product_on_article(read, groups: dict, key_urls=frozenset()) -> list[Finding]:
    rows = []
    for p in read:
        types = set(((p.analysis.get("structured_data") or {}).get("types")) or [])
        wrong = sorted(types & PRODUCT_TYPES)
        if not wrong:
            continue
        is_article = (groups.get(p.url) or {}).get("page_type") == "blog_article" or bool(types & ARTICLE_TYPES)
        if not is_article:
            continue
        article = sorted(types & ARTICLE_TYPES) or ["blog"]
        rows.append({"url": p.url, "types": sorted(types)[:12], "wrong_types": wrong,
                     "row": _row(f"{', '.join(article)} sayfasında {', '.join(wrong)} işaretlemesi",
                                 f"{', '.join(wrong)} markup on a {', '.join(article)} page")})
    if not rows:
        return []
    urls = [r["url"] for r in rows]
    return [Finding("STR-3", f"{len(rows)} blog or article page(s) carry Product or AggregateRating markup",
                    Severity.S3, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                    {"pages": rows[:MAX_ROWS], "rule": "a page typed as a blog article (page grouping) or carrying "
                                                        "Article/BlogPosting markup, with Product or AggregateRating"},
                    PRODUCT_ARTICLE_EXPECTED, PRODUCT_ARTICLE_FIX, notes=[PRODUCT_ARTICLE_NOTE],
                    importance_tier=0 if any(u in key_urls for u in urls) else 2, rule_id="str3.product_on_article")]


# -- 5. str1.subpage_copies_parent -------------------------------------------------------------------------------------

def subpage_copies_parent(read, key_urls=frozenset()) -> tuple[list[Finding], set[str]]:
    """(findings, the sub-pages found): a sub-page under a read parent, canonical to itself, whose hreflang names the
    parent and whose title, H1 or description is the parent's."""
    by_key = {_key(p.url): p for p in read if _ok(p)}
    rows = []
    for p in read:
        if not _ok(p) or not self_canonical(p.url, p.analysis):
            continue
        parent = _parent(p.url, by_key)
        targets = _hreflang_targets(p.analysis, p.url)
        if parent is None or _key(parent.url) not in targets or _key(p.url) in targets:
            continue
        a, b = p.analysis, parent.analysis
        shared = [name for name, mine, theirs in (("title", _text(a.get("title")), _text(b.get("title"))),
                                                  ("H1", (h1s(a) or [""])[0], (h1s(b) or [""])[0]),
                                                  ("description", description(a), description(b)))
                  if _same(mine, theirs)]
        if not shared:
            continue
        what_tr = ", ".join({"title": "başlık", "H1": "H1", "description": "açıklama"}[s] for s in shared)
        rows.append({"url": p.url, "parent": parent.url, "shared": shared, "title": _text(a.get("title")),
                     "h1": (h1s(a) or [""])[0],
                     "row": _row(f"{what_tr} {_short(parent.url)} ile aynı (\"{_text(a.get('title'))}\"); canonical kendisi, "
                                 f"hreflang {_short(parent.url)}",
                                 f"{', '.join(shared)} same as {_short(parent.url)} (\"{_text(a.get('title'))}\"); canonical "
                                 f"to itself, hreflang to {_short(parent.url)}")})
    if not rows:
        return [], set()
    urls = [r["url"] for r in rows]
    parents = sorted({r["parent"] for r in rows})
    return [Finding("STR-1", f"{len(rows)} sub-page(s) repeat their parent page's title or H1, with hreflang to the parent",
                    Severity.S3, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                    {"pages": rows[:MAX_ROWS], "parents": parents[:20],
                     "rule": "a page read under a parent page read (its address path), canonical to itself, whose "
                             "hreflang names the parent and whose title, H1 or description is the parent's"},
                    SUBPAGE_EXPECTED, SUBPAGE_FIX, notes=[SUBPAGE_NOTE],
                    importance_tier=0 if any(u in key_urls for u in urls) else 2, rule_id="str1.subpage_copies_parent")], set(urls)


# -- 7. str2.h1_parent_name --------------------------------------------------------------------------------------------

def h1_parent_name(read, key_urls=frozenset(), skip: set[str] | None = None) -> list[Finding]:
    """A sub-page whose H1 is the name of its section: the H1 of the parent page read, or the trail's step above it."""
    by_key = {_key(p.url): p for p in read if _ok(p)}
    rows = []
    for p in read:
        if not _ok(p) or p.url in (skip or ()):
            continue
        h1 = (h1s(p.analysis) or [""])[0]
        if not h1:
            continue
        parent = _parent(p.url, by_key)
        source = None
        if parent is not None and _same(h1, (h1s(parent.analysis) or [""])[0]):
            source = ("parent", parent.url)
        else:
            trail = (p.analysis.get("breadcrumbs") or [None])[0] or {}
            names = [_text(x) for x in (trail.get("names") or str(trail.get("text") or "").split(">"))] if trail else []
            if len(names) >= 3 and _same(h1, names[-2]) and not _same(h1, names[-1]):
                source = ("trail", names[-2])
        if source is None:
            continue
        title = _text(p.analysis.get("title"))
        where_tr = f"{_short(source[1])} sayfasının H1'i" if source[0] == "parent" else "içerik yolundaki üst adım"
        where_en = f"the H1 of {_short(source[1])}" if source[0] == "parent" else "the step above it in the breadcrumb"
        rows.append({"url": p.url, "h1": h1, "parent": source[1] if source[0] == "parent" else None, "title": title,
                     "row": _row(f"H1 \"{h1}\" = {where_tr}; sayfa başlığı \"{title}\"",
                                 f"H1 \"{h1}\" = {where_en}; page title \"{title}\"")})
    if not rows:
        return []
    urls = [r["url"] for r in rows]
    return [Finding("STR-2", f"{len(rows)} sub-page(s) use their section's name as their H1",
                    Severity.S4, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                    {"pages": rows[:MAX_ROWS], "rule": "a page read whose H1 is the H1 of the parent page read above it "
                                                        "in the address path, or the breadcrumb step above it"},
                    H1_PARENT_EXPECTED, H1_PARENT_FIX, importance_tier=0 if any(u in key_urls for u in urls) else 2,
                    rule_id="str2.h1_parent_name")]


# -- all of them -------------------------------------------------------------------------------------------------------

RULE_CHECKS = {"IDX-1", "IDX-8", "STR-1", "STR-2", "STR-3"}


def soft_404_probe(result) -> dict | None:
    index = getattr(result, "index", None)
    if isinstance(index, dict):
        return index.get("soft_404")
    return getattr(index, "soft_404", None)


def findings(result, read, groups: dict, wanted: set[str], key_urls=frozenset(), saved: bool = False
             ) -> tuple[dict[str, list[Finding]], list[dict]]:
    out: dict[str, list[Finding]] = defaultdict(list)
    unassessed: list[dict] = []
    pages = list(result.pages)
    if "IDX-1" in wanted:
        out["IDX-1"] += error_redirects(pages, getattr(result, "redirects", None), soft_404_probe(result), key_urls)
    sub, subpages = subpage_copies_parent(read, key_urls) if "STR-1" in wanted else ([], set())
    if sub:
        out["STR-1"] += sub
    seconds: set[str] = set()  # second addresses of a page: their fix is a 301, so no other card for their H1
    if "IDX-8" in wanted:
        inlinks: dict[str, int] = defaultdict(int)
        for p in read:
            for edge in p.outlinks or []:
                inlinks[(edge.get("target") or "").split("#")[0]] += 1
        copies = self_canonical_copies(read, inlinks, key_urls, skip=subpages)
        out["IDX-8"] += copies
        seconds = {r["url"] for f in copies for r in f.evidence["pages"] if r["url"] != r["main"]}
    if "STR-3" in wanted:
        out["STR-3"] += product_on_article(read, groups, key_urls)
    if "STR-2" in wanted:
        out["STR-2"] += h1_parent_name(read, key_urls, skip=subpages | seconds)
    return out, unassessed
