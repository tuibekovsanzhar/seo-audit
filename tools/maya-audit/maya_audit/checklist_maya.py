"""The checklist items Maya's Search Console export can measure when it is attached to the audit (DECISIONS 365).

Maya's export holds Search Console performance per day, per page, per query, per country and per device (never a query
and a page together), and no GA4, coverage, URL inspection, crawl stats, enhancement or security report. So of the
items that need data, these are measured from it, with the crawl's own addresses and pages: SEO-004 (date range),
SEO-005 (URL inventory), SEO-007 (property scope), SEO-008 (baselines), SEO-025 and SEO-054 (pages the crawl found no
address of), SEO-028 (pages read with and without impressions), SEO-057 (link flow to the most clicked commercial
pages), SEO-071 (CTR below the site's own pages at the same position), SEO-074 (performance per page) and SEO-165
(the weekly trend). GA4 stays missing (Maya's summary does not read ga4-traffic). `row` returns None for any other
item, or when the summary holds no Search Console data.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

ITEMS = ("SEO-004", "SEO-005", "SEO-007", "SEO-008", "SEO-025", "SEO-028", "SEO-054", "SEO-057", "SEO-071", "SEO-074",
         "SEO-165")
HISTORY_DAYS = 395  # about 13 months: one season compared with the same season a year before
TEST_HOST = re.compile(r"(?:^|[.-])(uat|staging|stage|test|dev|preprod|backoffice|admin|preview|qa)(?:[.-]|$)")
FEW_LINKS = 2  # a commercial page with clicks that fewer pages read link to
DAILY = ("SEO-004", "SEO-008", "SEO-165")  # need the daily performance file, not only a page list

W = {"tr": {"src": "Search Console (Maya verisi, {a} – {b})", "ref": "Maya verisi · Search Console",
            "004": "{src}: {days} gün; aylık tıklama {months}. Mevsimsellik için en az 13 ay gerekir.",
            "004_ok": "{src}: {days} gün; aylık tıklama {months}.",
            "005": "Tarama ve site haritası {known} adres; Search Console {gsc} sayfa; {extra} tanesi taramada ve site haritasında yok{ex}.",
            "007": "Search Console sayfaları {n} ana makinede: {hosts}{more}.", "more": " ve {n} tane daha",
            "007_test": "Search Console'da test ya da iç kullanım adresleri gösterim alıyor: {hosts} ({imp} gösterim).",
            "008": "{src}: {clicks} tıklama, {imp} gösterim, ortalama sıra {pos}; marka sorgularının tıklama payı %{brand}.",
            "025": "{n} sayfa Search Console'da gösterim alıyor ama tarama bu adresleri bulmadı{ex}.{cap}",
            "025_none": "Search Console'da gösterim alan her sayfa taramada ya da site haritasında var.",
            "054": "Bağlantısı bulunmayan {n} sayfa tıklama alıyor ({clicks} tıklama){ex}: bağlantı verin ya da yönlendirin.{cap}",
            "054_none": "Taramanın bulmadığı ve tıklama alan sayfa yok.",
            "cap": " Tarama sayfa sınırında durdu: bu sayfalar yetim olmayabilir.",
            "028": "Okunan {read} sayfanın {seen} tanesi Search Console'da gösterim almış (dizinde); {none} tanesi Search Console sayfa listesinde yok{ex}.",
            "057": "En çok tıklanan {top} ticari sayfadan {n} tanesine okunan sayfalardan {few}'den az bağlantı var{ex}.",
            "057_ok": "En çok tıklanan {top} ticari sayfanın her biri okunan sayfalardan en az {few} bağlantı alıyor.",
            "057_none": "Search Console'da tıklama alan okunmuş ürün ya da kategori sayfası yok.",
            "071": "{n} sayfanın tıklama oranı aynı sıradaki kendi sayfalarınızın yarısından az{ex} ('Organik×AI - Segmentler').",
            "071_none": "Hiçbir sayfanın tıklama oranı aynı sıradaki kendi sayfalarınızın yarısından az değil.",
            "074": "{n} sayfa için tıklama, gösterim ve sıra var; okunan {both} sayfada sayfa ölçümleriyle birlikte ('Sayfa detay').",
            "165": "Haftalık tıklama: {weeks} ({change}). Denetimler arası karşılaştırma 'Önceki denetimden değişenler' sayfasında.",
            "ex": " (ör. {v})"},
     "en": {"src": "Search Console (Maya data, {a} – {b})", "ref": "Maya data · Search Console",
            "004": "{src}: {days} days; clicks per month {months}. Seasonality needs at least 13 months.",
            "004_ok": "{src}: {days} days; clicks per month {months}.",
            "005": "Crawl and sitemaps {known} addresses; Search Console {gsc} pages; {extra} of them neither crawled nor in a sitemap{ex}.",
            "007": "Search Console pages on {n} host(s): {hosts}{more}.", "more": " and {n} more",
            "007_test": "Test or internal hosts get impressions in Search Console: {hosts} ({imp} impressions).",
            "008": "{src}: {clicks} clicks, {imp} impressions, average position {pos}; brand queries {brand}% of clicks.",
            "025": "{n} page(s) get impressions in Search Console but the crawl did not find their address{ex}.{cap}",
            "025_none": "Every page with impressions in Search Console is in the crawl or a sitemap.",
            "054": "{n} page(s) without a link found get clicks ({clicks} clicks){ex}: link them or redirect them.{cap}",
            "054_none": "No page the crawl did not find gets clicks.",
            "cap": " The crawl stopped at its page cap: these pages may not be orphans.",
            "028": "Of {read} pages read, {seen} got impressions in Search Console (indexed); {none} are not in its page list{ex}.",
            "057": "Of the {top} most clicked commercial pages, {n} get fewer than {few} links from the pages read{ex}.",
            "057_ok": "Each of the {top} most clicked commercial pages gets at least {few} links from the pages read.",
            "057_none": "No product or category page read gets clicks in Search Console.",
            "071": "{n} page(s) have under half the CTR of your own pages at the same position{ex} ('Organik×AI - Segmentler').",
            "071_none": "No page has under half the CTR of your own pages at the same position.",
            "074": "Clicks, impressions and position for {n} pages; with the page measures on {both} pages read ('Sayfa detay').",
            "165": "Weekly clicks: {weeks} ({change}). The audit-to-audit comparison is in 'Önceki denetimden değişenler'.",
            "ex": " (e.g. {v})"}}


def key(url: str) -> str:
    """An address as one page: host without www, lower case, the path without its trailing slash, no query."""
    try:
        p = urlsplit(url)
    except ValueError:
        return url
    return (p.hostname or "").removeprefix("www.") + (p.path.rstrip("/") or "/")


def has_gsc(summary: dict | None) -> bool:
    return bool(((summary or {}).get("gsc") or {}).get("pages") or ((summary or {}).get("gsc") or {}).get("monthly"))


def _n(x, lang: str) -> str:
    s = f"{round(x):,}" if isinstance(x, (int, float)) else "—"
    return s.replace(",", ".") if lang == "tr" else s


def _ex(urls, lang: str, k: int = 3) -> str:
    urls = list(urls)[:k]
    return W[lang]["ex"].format(v=", ".join(urls)) if urls else ""


def row(item_id: str, summary: dict | None, selection: dict, lang: str = "tr") -> tuple[str, str, str] | None:
    """(result, evidence, ref) for an item Maya's Search Console data measures, or None."""
    if item_id not in ITEMS or not has_gsc(summary):
        return None
    T = W[lang]
    g = summary["gsc"]
    if item_id in DAILY and not (g.get("monthly") or g.get("weeks")):
        return None  # a page-scores export only: no daily performance, so no range, baseline or trend
    pages = {u: m for u, m in (g.get("pages") or {}).items() if isinstance(m, dict)}
    period = g.get("page_period") or g.get("day_period") or ["?", "?"]
    src = T["src"].format(a=period[0], b=period[-1])
    site = ((selection.get("_checklist_facts") or {}).get("site") or {})
    own = (urlsplit(site.get("start") or "").hostname or "").removeprefix("www.")
    mine = {u: m for u, m in pages.items() if key(u).split("/")[0] == own} if own else pages
    known = set((selection.get("_checklist_facts") or {}).get("known") or [])
    importance = selection.get("_importance") or {}
    read = {key(u): u for u in selection.get("_pages_read") or importance}
    capped = site.get("stop") == "page_cap"
    ref = T["ref"]
    if item_id == "SEO-004":
        days = _days(period)
        months = ", ".join(f"{m.get('month')} {_n(m.get('clicks'), lang)}" for m in g.get("monthly") or []) or "—"
        long_enough = isinstance(days, int) and days >= HISTORY_DAYS
        return ("pass" if long_enough else "missing_data",
                T["004_ok" if long_enough else "004"].format(src=src, days=days if days is not None else "?", months=months), ref)
    if item_id == "SEO-005":
        extra = sorted((u for u in mine if key(u) not in known), key=lambda u: -(mine[u].get("impressions") or 0))
        return "pass", T["005"].format(known=_n(len(known), lang), gsc=_n(len(mine), lang), extra=_n(len(extra), lang),
                                       ex=_ex(extra, lang)), ref
    if item_id == "SEO-007":
        hosts: dict[str, float] = {}
        for u, m in pages.items():
            h = (urlsplit(u).hostname or "").lower()
            hosts[h] = hosts.get(h, 0) + (m.get("impressions") or 0)
        test = {h: v for h, v in hosts.items() if TEST_HOST.search(h.split(".")[0] if own and h.endswith(own) else h)}
        if test:
            return "issue", T["007_test"].format(hosts=", ".join(sorted(test)), imp=_n(sum(test.values()), lang)), ref
        more = T["more"].format(n=len(hosts) - 6) if len(hosts) > 6 else ""
        return "pass", T["007"].format(n=len(hosts), hosts=", ".join(sorted(hosts)[:6]), more=more), ref
    if item_id == "SEO-008":
        monthly = g.get("monthly") or []
        clicks = sum(m.get("clicks") or 0 for m in monthly)
        imp = sum(m.get("impressions") or 0 for m in monthly)
        pos = (sum((m.get("position") or 0) * (m.get("impressions") or 0) for m in monthly) / imp) if imp else None
        b = g.get("brand") or {}
        bc, nc = (b.get("brand") or {}).get("clicks") or 0, (b.get("non_brand") or {}).get("clicks") or 0
        share = round(100 * bc / (bc + nc)) if bc + nc else 0
        return "pass", T["008"].format(src=src, clicks=_n(clicks, lang), imp=_n(imp, lang),
                                       pos=f"{pos:.1f}".replace(".", ",") if pos and lang == "tr" else f"{pos:.1f}" if pos else "—",
                                       brand=share), ref
    if item_id in ("SEO-025", "SEO-054"):
        missing = sorted((u for u, m in mine.items() if key(u) not in known and (m.get("impressions") or 0) > 0),
                         key=lambda u: -(mine[u].get("clicks") or 0))
        cap = T["cap"] if capped else ""
        if item_id == "SEO-025":
            if not missing:
                return "pass", T["025_none"], ref
            return ("review" if capped else "issue"), T["025"].format(n=_n(len(missing), lang), ex=_ex(missing, lang), cap=cap), ref
        clicked = [u for u in missing if (mine[u].get("clicks") or 0) > 0]
        if not clicked:
            return "pass", T["054_none"], ref
        return ("review" if capped else "issue"), T["054"].format(
            n=_n(len(clicked), lang), clicks=_n(sum(mine[u].get("clicks") or 0 for u in clicked), lang),
            ex=_ex(clicked, lang), cap=cap), ref
    if item_id == "SEO-028":
        by_key = {key(u): m for u, m in mine.items()}
        seen = [u for k, u in read.items() if (by_key.get(k) or {}).get("impressions")]
        none = [u for k, u in read.items() if not (by_key.get(k) or {}).get("impressions")]
        return ("pass" if not none else "review"), T["028"].format(read=_n(len(read), lang), seen=_n(len(seen), lang),
                                                                  none=_n(len(none), lang), ex=_ex(sorted(none), lang)), ref
    if item_id == "SEO-057":
        by_key = {key(u): m for u, m in mine.items()}
        commercial = [(u, r, by_key.get(key(u)) or {}) for u, r in importance.items()
                      if isinstance(r, dict) and r.get("page_type") in ("product", "category") and r.get("read") is not False]
        clicked = sorted(((u, r, m) for u, r, m in commercial if (m.get("clicks") or 0) > 0), key=lambda x: -x[2]["clicks"])[:10]
        if not clicked:
            return "pass", T["057_none"], ref
        few = [u for u, r, _ in clicked if isinstance(r.get("inlinks"), int) and r["inlinks"] < FEW_LINKS]
        if few:
            return "issue", T["057"].format(top=len(clicked), n=len(few), few=FEW_LINKS, ex=_ex(few, lang)), ref
        return "pass", T["057_ok"].format(top=len(clicked), few=FEW_LINKS), ref
    if item_id == "SEO-071":
        from .maya_sheets import expected_ctr
        _, low = expected_ctr(summary)
        low = sorted(low, key=lambda u: -(pages.get(u, {}).get("impressions") or 0))
        if not low:
            return "pass", T["071_none"], ref
        return "issue", T["071"].format(n=_n(len(low), lang), ex=_ex(low, lang)), ref
    if item_id == "SEO-074":
        both = sum(1 for k in read if k in {key(u) for u in mine})
        return "pass", T["074"].format(n=_n(len(mine), lang), both=_n(both, lang)), ref
    if item_id == "SEO-165":
        weeks = g.get("weeks") or []
        clicks = [w.get("clicks") or 0 for w in weeks]
        change = (f"%{round(100 * (clicks[-1] - clicks[0]) / clicks[0]):+d}".replace("%+", "+%").replace("%-", "-%")
                  if lang == "tr" else f"{round(100 * (clicks[-1] - clicks[0]) / clicks[0]):+d}%") if len(clicks) > 1 and clicks[0] else "—"
        return "pass", T["165"].format(weeks=" → ".join(_n(c, lang) for c in clicks) or "—", change=change), ref
    return None


def _days(period) -> int | None:
    from datetime import date
    try:
        return (date.fromisoformat(period[-1]) - date.fromisoformat(period[0])).days + 1
    except (TypeError, ValueError, IndexError):
        return None

