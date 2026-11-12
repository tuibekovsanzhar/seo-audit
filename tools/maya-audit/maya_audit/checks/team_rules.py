"""Rules from the SEO team's technical review (Efsa's enpara report of 2026-11-12, DECISIONS 343).

Each makes an ordinary finding in the check it belongs to, from data the crawl already reads; none sends a request.
They run with the checklist's quick checks (`quick_rules.findings`), so a live audit and a saved report (offline,
`maya_audit.reassess_rules`) get the same rule. Every page record in the evidence carries `row`, the line its Ek row
shows ({"tr", "en"}): the status chain, the duplicate pair, the schema types, the variable text or the shared title/H1.

| Rule id | Check | What it reports |
|---|---|---|
| idx1.error_redirect | IDX-1 | missing pages answer a redirect to an error page instead of 404/410 |
| idx8.self_canonical_copies | IDX-8 | two addresses of one page (/x and /x/default.aspx, /anasayfa and /), each 200 and its own canonical |
| idx8.form_step_copies | IDX-8 | the same, for an application or form step: canonical or noindex, never a 301 (DECISIONS 344) |
| str3.product_on_article | STR-3 | Product or AggregateRating markup on blog or article pages |
| str1.sections_as_pages | STR-1 | sub-pages opening a part of their parent page at their own address (DECISIONS 344) |

DECISIONS 344 (İlginay's review of the enpara Ek): the sub-page rules are one site-wide card; the second addresses of a
form step are not told to 301; the sitemap-errors card takes the redirects to an error page (`settle`), with a 301
target per address.

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
FORM_STEP_EXPECTED = "a step of an application or form is indexed at one address, or not at all"
FORM_STEP_FIX = ("Point the second address's canonical to the main step, or add noindex to the step's other addresses. "
                 "Do not redirect them with a 301: the application or form uses them and would stop working.")
FORM_STEP_NOTE = ("Application and form steps (başvuru, -kk, ?sw=, a page with a form) often need their own addresses "
                  "to work; only their indexing is at stake, so a canonical or noindex is the fix, never a redirect.")
SECTIONS_EXPECTED = "each address is a page of its own, or a part of a page is reached with an anchor, not a new address"
SECTIONS_FIX = ("Decide for the site: either make each of these addresses a real page (its own title, H1, description, "
                "content, and hreflang to itself), or keep one page and reach its parts with anchors (#section) or "
                "point each address's canonical to the parent page.")
SECTIONS_NOTE = ("Clicking a question or a left-menu heading on one page opens a new address that repeats the parent's "
                 "title, H1 or hreflang: engines see many thin copies of one page. A site-wide structure choice; "
                 "pages whose H1 is their own title are left out.")
SITEMAP_ERROR_REDIRECT_NOTE = ("These addresses answer a redirect to an error page (status chain per address): the "
                               "server should answer 404/410 at the address itself, not redirect to an error page. Each "
                               "row suggests the live page to send it to with a 301, or 410 when none is related.")

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


# -- 2. idx8.self_canonical_copies / idx8.form_step_copies ------------------------------------------------------------

# A last path segment that names the page it sits under: /anasayfa is /, /sss/default.aspx is /sss.
ALIAS_SEGMENTS = frozenset({"default.aspx", "default.asp", "default.htm", "default.html", "index.html", "index.htm",
                            "index.php", "index.aspx", "index.asp", "index.jsp", "anasayfa", "ana-sayfa", "home",
                            "homepage", "default", "index"})
# DECISIONS 344: a step of an application or form (İlginay: a 301 there is wrong; canonical to the main step or noindex).
_FORM_WORDS = re.compile(r"basvur|application|apply|form|kayit|register|signup|sign-up|checkout|odeme-adim|adim|step|"
                         r"kimlik-bilgi|bilgileriniz", re.IGNORECASE)
_FORM_QUERY = ("sw", "step", "adim", "stage", "page_step")


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


def form_step(page) -> bool:
    """A step of an application or form: its address names one (başvuru, form, kayıt, -kk ...), it carries a step
    query (?sw=, ?step=), or the page holds a form whose action is not a search."""
    parts = urlsplit(page.url)
    if _FORM_WORDS.search(unquote(parts.path)) or re.search(r"-kk(?:/|$)", parts.path.lower()):
        return True
    if any(k.lower() in _FORM_QUERY for k, _ in parse_qsl(parts.query, keep_blank_values=True)):
        return True
    actions = (page.analysis or {}).get("form_actions") or []
    return any(isinstance(a, dict) and not re.search(r"search|arama|ara\b", str(a.get("action") or a), re.I) or
               isinstance(a, str) and not re.search(r"search|arama", a, re.I) for a in actions)


def _hreflang_targets(analysis: dict, url: str = "") -> set[str]:
    return {_key(urljoin(url, h["href"])) for h in analysis.get("hreflang") or [] if isinstance(h, dict) and h.get("href")}


def self_canonical_copies(read, inlinks: dict[str, int] | None = None, key_urls=frozenset(),
                          skip: set[str] | None = None) -> list[Finding]:
    """Addresses of one page, each 200 and its own canonical. Two cards: a second address of a page (/anasayfa,
    /default.aspx, ?query) -> 301 to the main one; a second address of an application or form step -> canonical to the
    main step or noindex, never a 301 (DECISIONS 344)."""
    groups: dict[tuple, list] = defaultdict(list)
    for p in read:
        a = p.analysis
        if not _ok(p) or not a.get("text_sha256") or not self_canonical(p.url, a) or p.url in (skip or ()):
            continue
        groups[(alias_key(p.url), a["text_sha256"], _text(a.get("title")).casefold(), tuple(h.casefold() for h in h1s(a)))].append(p)
    kinds: dict[str, dict] = {"alias": {"rows": [], "urls": [], "pairs": 0}, "form": {"rows": [], "urls": [], "pairs": 0}}
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
        kind = "form" if any(form_step(p) for p in members) else "alias"
        k = kinds[kind]
        k["pairs"] += len(members) - 1
        for p in members:
            others = ", ".join(_short(q.url) for q in members if q is not main)
            if p is main:
                row = _row(f"asıl adres önerisi; aynı içerik, başlık ve H1: {others}; ikisi de 200 ve kendini kanonik gösteriyor",
                           f"suggested main address; same text, title and H1: {others}; both 200 and their own canonical")
                fix = None
            elif kind == "alias":
                row = _row(f"{_short(main.url)} ile aynı içerik, başlık ve H1; 200 ve kendini kanonik gösteriyor",
                           f"same text, title and H1 as {_short(main.url)}; 200 and its own canonical")
                fix = _row(f"Bu adresi {_short(main.url)} adresine 301 ile yönlendirin.",
                           f"Redirect this address to {_short(main.url)} with a 301.")
            else:
                row = _row(f"başvuru/form adımı; {_short(main.url)} ile aynı içerik, başlık ve H1; 200 ve kendini kanonik gösteriyor",
                           f"an application/form step; same text, title and H1 as {_short(main.url)}; 200 and its own canonical")
                fix = _row(f"Kanonik etiketini {_short(main.url)} adresine verin ya da noindex ekleyin; 301 vermeyin (adım çalışmayı bırakır).",
                           f"Point its canonical to {_short(main.url)} or add noindex; no 301 (the step would stop working).")
            k["rows"].append({"url": p.url, "main": main.url, "title": _text(p.analysis.get("title")), "row": row,
                              **({"fix": fix} if fix else {})})
            k["urls"].append(p.url)
    out = []
    tier = lambda urls: 0 if any(u in key_urls for u in urls) else 2  # noqa: E731
    rule = ("addresses of one page (the same path but for case, a trailing slash, the query, or a last segment such as "
            "/anasayfa, /default.aspx or /index.html) read with the same visible text, title and H1, each answering 200 "
            "with no canonical to another address, and no hreflang between them")
    if kinds["alias"]["rows"]:
        k = kinds["alias"]
        out.append(Finding("IDX-8", f"{k['pairs']} second address(es) of a page answer 200 and name themselves canonical",
                           Severity.S3, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(k["urls"]),
                           {"pages": k["rows"][:MAX_ROWS], "second_addresses": k["pairs"], "rule": rule},
                           COPIES_EXPECTED, COPIES_FIX, importance_tier=tier(k["urls"]), rule_id="idx8.self_canonical_copies"))
    if kinds["form"]["rows"]:
        k = kinds["form"]
        out.append(Finding("IDX-8", f"{k['pairs']} second address(es) of an application or form step answer 200 and name themselves canonical",
                           Severity.S4, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(k["urls"]),
                           {"pages": k["rows"][:MAX_ROWS], "second_addresses": k["pairs"],
                            "rule": rule + "; one of them a step of an application or form (its address, a step query or a form)"},
                           FORM_STEP_EXPECTED, FORM_STEP_FIX, notes=[FORM_STEP_NOTE], importance_tier=tier(k["urls"]),
                           rule_id="idx8.form_step_copies"))
    return out


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


# -- 5 and 7. str1.sections_as_pages ----------------------------------------------------------------------------------

def _title_head(title: str) -> str:
    """A title without its brand part: "Hisse Senedi | Enpara" -> "Hisse Senedi"."""
    return re.split(r"\s+[|\-–—:]\s+", _text(title))[0]


def sections_as_pages(read, key_urls=frozenset()) -> list[Finding]:
    """DECISIONS 344 (İlginay: clicking a question or a left-menu heading on one page opens a new address): a page read
    under a parent page read (its address path; never the homepage), canonical to itself, that carries the parent's
    title or H1, or whose hreflang names the parent. One site-wide card, a decision for the site; a page whose H1 is
    its own title (\"Hisse Senedi\" on \"Hisse Senedi | Enpara\") is left out: it names its own topic."""
    by_key = {_key(p.url): p for p in read if _ok(p)}
    rows = []
    for p in read:
        if not _ok(p) or not self_canonical(p.url, p.analysis):
            continue
        parent = _parent(p.url, by_key)
        if parent is None:
            continue
        a, b = p.analysis, parent.analysis
        h1 = (h1s(a) or [""])[0]
        targets = _hreflang_targets(a, p.url)
        to_parent = _key(parent.url) in targets and _key(p.url) not in targets
        # A page whose H1 is its own title names its own topic (İlginay: /yatirim-hesabi/hisse-senedi); not when its
        # hreflang names the parent (the /sss sub-pages: a language version of the parent, by their own markup).
        if h1 and not to_parent and (_same(h1, _title_head(a.get("title"))) or _same(h1, _text(a.get("title")))):
            continue
        signs = []
        if to_parent:
            signs.append(("hreflang", "hreflang üst sayfayı gösteriyor", "hreflang names the parent"))
        if _same(_text(a.get("title")), _text(b.get("title"))):
            signs.append(("title", "başlık üst sayfayla aynı", "the parent's title"))
        if h1 and _same(h1, (h1s(b) or [""])[0]):
            signs.append(("h1", f"H1 \"{h1}\" üst sayfanın H1'i", f"H1 \"{h1}\" is the parent's H1"))
        if not signs:
            continue
        if description(a) and _same(description(a), description(b)):
            signs.append(("description", "açıklama üst sayfayla aynı", "the parent's description"))
        title = _text(a.get("title"))
        rows.append({"url": p.url, "parent": parent.url, "signs": [x[0] for x in signs], "title": title, "h1": h1,
                     "row": _row(f"üst sayfa {_short(parent.url)}; " + ", ".join(x[1] for x in signs) + f"; sayfa başlığı \"{title}\"",
                                 f"parent {_short(parent.url)}; " + ", ".join(x[2] for x in signs) + f"; page title \"{title}\"")})
    if not rows:
        return []
    urls = [r["url"] for r in rows]
    parents = sorted({r["parent"] for r in rows})
    return [Finding("STR-1", f"{len(rows)} sub-page(s) open a part of their parent page at an address of their own",
                    Severity.S3, Confidence.ESTIMATED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                    {"pages": rows[:MAX_ROWS], "parents": parents[:40], "parent_count": len(parents),
                     "rule": "a page read under a parent page read (its address path), canonical to itself, with the "
                             "parent's title or H1 or an hreflang naming the parent; a page whose H1 is its own title is left out"},
                    SECTIONS_EXPECTED, SECTIONS_FIX, notes=[SECTIONS_NOTE],
                    importance_tier=0 if any(u in key_urls for u in urls) else 2, rule_id="str1.sections_as_pages")]


# -- 4. the sitemap-errors card takes the redirects to an error page (DECISIONS 344) -------------------------------------

_STOP = frozenset({"ve", "ile", "icin", "nedir", "nasil", "neler", "nelerdir", "bir", "the", "and", "for", "what", "how",
                   "mi", "mu", "da", "de", "en", "tr", "www", "html", "aspx"})


def _tokens(text: str) -> set[str]:
    from ..page_words import fold
    return {t for t in re.split(r"[^a-z0-9]+", fold(unquote(text or "")).lower()) if len(t) >= 3 and t not in _STOP}


# DECISIONS 345 (the owner's check of the 21 enpara targets): a target never leaves the address's top section, the
# closest existing parent comes first, words decide only within the section and only when clearly better, and a weak
# case says "kontrol edin".
SIMILAR_STRONG = 0.5   # share of words that makes a page in the section a firm target over a parent two levels up
SIMILAR_WEAK = 0.25    # the least share for a target "to check" when no parent exists
SIBLING_OVER_PARENT = 0.6  # a page in the same folder beats the direct parent only with this share


def _segs(url: str) -> list[str]:
    return [s for s in urlsplit(url or "").path.split("/") if s]


def _section(url: str) -> str:
    """The top folder of an address (/sirketim, /en, /kartlar); "" for an address at the top (its section is the top)."""
    segs = _segs(url)
    return segs[0].lower() if len(segs) > 1 else ""


def known_live(result, missing: set[str]) -> dict[str, dict]:
    """{url: {"title", "basis"}} of the addresses this audit knows to exist: pages that answered 200 (read: with their
    title), sitemap-check answers of 200, and sitemap addresses no request showed to fail. Never one of `missing`, an
    error page, or an address that answered anything but 200."""
    pages = list(getattr(result, "pages", None) or [])
    bad = set(missing)
    out: dict[str, dict] = {}
    for p in pages:
        if getattr(p, "status", None) == 200:
            title = (p.analysis or {}).get("title") if isinstance(getattr(p, "analysis", None), dict) else None
            out[p.url] = {"title": title or "", "basis": "read"}
        elif getattr(p, "status", None) is not None:
            bad.add(p.url)
    index = getattr(result, "index", None)
    check = index.get("sitemap_check") if isinstance(index, dict) else getattr(index, "sitemap_check", None)
    rows = (check.get("rows") if isinstance(check, dict) else getattr(check, "rows", None)) or []
    for row in rows:
        if not isinstance(row, dict) or not row.get("url"):
            continue
        if row.get("status") == 200 and not row.get("noindex"):
            out.setdefault(row["url"], {"title": "", "basis": "answered"})
        else:
            bad.add(row["url"])
    for u in getattr(result, "sitemap_urls", None) or []:
        if isinstance(u, str) and u not in bad:
            out.setdefault(u, {"title": "", "basis": "sitemap"})
    return {u: v for u, v in out.items() if u not in bad and not error_page(u) and _segs(u)}


def suggest_target(url: str, known: dict[str, dict]) -> tuple[str | None, str, bool]:
    """(target, basis, firm) for a missing address: within its top section only; the direct parent when it exists
    (firm, also when only the sitemap lists it), unless a page in the same folder shares most words; else a page of
    the section sharing at least half the words (firm when this audit saw it answer); else the closest parent further
    up, or a page sharing a quarter of the words (both "to check"); else (None, "none", True): 410."""
    parts = urlsplit(url)
    segs = _segs(url)
    section = _section(url)
    want = _tokens(segs[-1]) if segs else set()
    by_key = {_key(u): u for u in known}
    parent, depth = None, 0
    for n in range(len(segs) - 1, 0, -1):
        hit = by_key.get(_key(f"{parts.scheme}://{parts.netloc}/" + "/".join(segs[:n])))
        if hit:
            parent, depth = hit, len(segs) - n
            break
    best, best_sim, best_folder = None, 0.0, False
    for u, info in known.items():
        if u == url or _section(u) != section or u == parent:
            continue
        have = _tokens(_segs(u)[-1]) | _tokens(info.get("title") or "")
        if not want or not have:
            continue
        sim = len(want & have) / len(want | have)
        same_folder = _segs(u)[:-1] == segs[:-1]
        if (sim, same_folder) > (best_sim, best_folder):
            best, best_sim, best_folder = u, sim, same_folder
    # A page chosen by its words is firm only when this audit saw it answer (read, or 200 in the sitemap check); one only
    # listed in the sitemap may be another broken entry of the same list: "to check".
    seen = best is not None and (known.get(best) or {}).get("basis") in ("read", "answered")
    if parent and depth == 1:
        if best and best_folder and best_sim >= SIBLING_OVER_PARENT:
            return best, "sibling", seen
        return parent, "parent", True
    if best and best_sim >= SIMILAR_STRONG:
        return best, "similar", seen
    if parent:
        return parent, "far_parent", False
    if best and best_sim >= SIMILAR_WEAK:
        return best, "similar_weak", False
    return None, "none", True


TARGET_WHY = {"tr": {"parent": "üst klasör sayfası", "sibling": "aynı klasörde, adres ve başlık benzerliği",
                     "similar": "aynı bölümde, adres ve başlık benzerliği", "far_parent": "en yakın var olan üst sayfa",
                     "similar_weak": "aynı bölümde, zayıf adres benzerliği"},
              "en": {"parent": "the folder's page above it", "sibling": "same folder, address and title words",
                     "similar": "same section, address and title words", "far_parent": "the closest existing page above it",
                     "similar_weak": "same section, few shared words"}}
TARGET_BASIS = {"tr": {"read": "", "answered": "; site haritası kontrolünde 200", "sitemap": "; site haritasında, bu denetimde okunmadı"},
                "en": {"read": "", "answered": "; 200 in the sitemap check", "sitemap": "; in the sitemap, not read in this audit"}}


def _g(f, name):
    return f.get(name) if isinstance(f, dict) else getattr(f, name, None)


def settle(checks, result) -> None:
    """After the broken-link split (DECISIONS 337): the sitemap-errors card gets, per address, its status chain and a
    suggested 301 target (410 when no page fits), and the server advice when the addresses redirect to an error page;
    the separate "redirect instead of 404/410" card keeps only addresses no other card lists (Maya's made-up address).
    Works on the engine's findings; `reassess_rules` passes saved ones the same way. Idempotent."""
    from .stage8_rules import redirect_records
    idx1 = next((c for c in checks if _g(c, "check_id") == "IDX-1"), None)
    if idx1 is None:
        return
    findings = list(_g(idx1, "findings") or [])
    pages = list(getattr(result, "pages", None) or [])
    saved = getattr(result, "redirects", None)
    records = {r["url"]: r for r in (saved if saved is not None else redirect_records(pages)) if isinstance(r, dict)}
    covered: set[str] = set()
    for f in findings:
        if _g(f, "rule_id") not in ("idx1.4xx.sitemap_only", "idx1.4xx.referenced", "idx1.4xx.referenced.linked"):
            continue
        ev = _g(f, "evidence") or {}
        addresses = [e.get("url") for e in ev.get("sitemap_entries") or [] if isinstance(e, dict)] or list(ev.get("sitemap_only") or [])
        covered |= set(addresses) | set(ev.get("target_urls") or [])
        if _g(f, "rule_id") != "idx1.4xx.sitemap_only" or ev.get("suggestion_rule") == 345:
            continue
        known = known_live(result, set(addresses))
        rows, via_error = [], 0
        for u in addresses:
            rec = records.get(u) or {}
            hops = rec.get("hops") or []
            chain = (" → ".join([str(h.get("status")) for h in hops] + [_short(rec.get("final") or "")]
                                + ([str(rec["final_status"])] if rec.get("final_status") else [])) if hops else None)
            to_error = bool(hops) and (error_page(rec.get("final") or "") or any(error_page(h.get("target") or "") for h in hops))
            via_error += int(to_error)
            target, why, firm = suggest_target(u, known)
            basis = (known.get(target) or {}).get("basis")
            why_tr = TARGET_WHY["tr"].get(why, "") + (TARGET_BASIS["tr"][basis] if target and basis in TARGET_BASIS["tr"] else "")
            why_en = TARGET_WHY["en"].get(why, "") + (TARGET_BASIS["en"][basis] if target and basis in TARGET_BASIS["en"] else "")
            if not target:
                said_tr, said_en = "ilgili bir sayfa yok: 410", "no related page: 410"
                fix = _row("Site haritasından çıkarın; adres 410 döndürsün (ilgili sayfa yok).",
                           "Take it out of the sitemap; let the address answer 410 (no related page).")
            elif firm:
                said_tr = f"önerilen 301 hedefi: {_short(target)} ({why_tr})"
                said_en = f"suggested 301 target: {_short(target)} ({why_en})"
                fix = _row(f"Site haritasından çıkarın ve bu adresi {_short(target)} adresine 301 ile yönlendirin.",
                           f"Take it out of the sitemap and redirect it to {_short(target)} with a 301.")
            else:
                said_tr = f"önerilen hedef (kontrol edin): {_short(target)} ({why_tr})"
                said_en = f"suggested target (check it): {_short(target)} ({why_en})"
                fix = _row(f"Site haritasından çıkarın; {_short(target)} uygunsa 301 ile oraya yönlendirin, değilse 410 döndürün.",
                           f"Take it out of the sitemap; 301 it to {_short(target)} if that fits, else answer 410.")
            said_tr = (f"{chain}; " if chain else "") + said_tr
            said_en = (f"{chain}; " if chain else "") + said_en
            rows.append({"url": u, "chain": chain, "redirects_to_error": to_error, "target": target, "target_basis": why,
                         "target_firm": firm, "target_known_as": basis,
                         "row": _row(said_tr, said_en), "fix": fix})
        new_ev = {**ev, "suggestions": rows, "redirects_to_error_page": via_error, "suggestion_rule": 345}
        if isinstance(f, dict):
            f["evidence"] = new_ev
            if via_error:
                f["notes"] = list(f.get("notes") or []) + [SITEMAP_ERROR_REDIRECT_NOTE]
        else:
            f.evidence = new_ev
            if via_error:
                f.notes = list(f.notes) + [SITEMAP_ERROR_REDIRECT_NOTE]
    for f in list(findings):
        if _g(f, "rule_id") != "idx1.error_redirect":
            continue
        ev = _g(f, "evidence") or {}
        left = [r for r in ev.get("pages") or [] if isinstance(r, dict) and (r.get("probe") or r.get("url") not in covered)]
        if len(left) == len(ev.get("pages") or []):
            continue
        findings.remove(f)
        if not left:
            continue
        crawled = [r for r in left if not r.get("probe")]
        n = len(crawled) or 1
        urls = [r["url"] for r in crawled] or [r["url"] for r in left]
        title = f"{n} missing address(es) answer a redirect to an error page instead of 404/410"
        evidence = {**ev, "pages": left, "redirecting_to_error": len(crawled),
                    "in_other_cards": sorted(covered & {r.get("url") for r in ev.get("pages") or [] if isinstance(r, dict)})[:40]}
        if isinstance(f, dict):
            f.update(title=title, evidence=evidence, scope={"kind": "page" if len(urls) == 1 else "template",
                                                            "count": len(urls), "urls": urls[:25]})
        else:
            f.title, f.evidence, f.scope = title, evidence, scope_for(urls)
            f.id = ""
            f.__post_init__()
        findings.append(f)
    if isinstance(idx1, dict):
        idx1["findings"] = findings
    else:
        idx1.findings = findings


# -- all of them -------------------------------------------------------------------------------------------------------

RULE_CHECKS = {"IDX-1", "IDX-8", "STR-1", "STR-3"}
RULES = ("idx1.error_redirect", "idx8.self_canonical_copies", "idx8.form_step_copies", "str3.product_on_article",
         "str1.sections_as_pages")


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
    sections = sections_as_pages(read, key_urls) if "STR-1" in wanted else []
    if sections:
        out["STR-1"] += sections
    if "IDX-8" in wanted:
        inlinks: dict[str, int] = defaultdict(int)
        for p in read:
            for edge in p.outlinks or []:
                inlinks[(edge.get("target") or "").split("#")[0]] += 1
        skip = {u for f in sections for u in f.scope.get("_all_urls") or []}
        out["IDX-8"] += self_canonical_copies(read, inlinks, key_urls, skip=skip)
    if "STR-3" in wanted:
        out["STR-3"] += product_on_article(read, groups, key_urls)
    return out, unassessed
