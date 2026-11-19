"""The SEO team's 165-item checklist, filled from one audit (DECISIONS 342).

Every item gets one result: Geçti (pass), Sorun (issue), Veri eksik (missing_data), İnceleme gerekli (review) or
Uygulanmaz (na), with one line of evidence, the Maya rule ID or card number behind it and, for Veri eksik, the data
source that is missing. The items and what each reads are in `checklist_items.json` (scripts/checklist_items.py).

How an item is decided, first match wins:
  1. its site condition does not hold (no product page, no second language...)       -> Uygulanmaz, with the reason;
  2. a few items are read from the audit's own records (business type, page types, Core Web Vitals field data, the
     crawl's scope and its re-tests) -> their own result;
  3. a problem (S1-S4) of its rules is a card or in the appendix                     -> Sorun, the card or rule named;
  4. a problem of its rules waits under "Teyit edin"                                 -> İnceleme gerekli;
  5. a manual item                                                                   -> Veri eksik, "Manuel";
  6. a data source the whole item needs is not connected                            -> Veri eksik, that source;
  7. an expert-judgement item, or one Maya does not check automatically yet         -> İnceleme gerekli;
  8. every check it reads could not run (not_assessed)                              -> Veri eksik, the check's source;
     no page read is what its checks are about (not_applicable)                     -> Uygulanmaz;
  9. a full item                                                                     -> Geçti;
     a partial item: Geçti when Maya's part is the item, Veri eksik when the rest needs a data source that is not
     connected, else İnceleme gerekli (the rest is a judgement or not automated).
Rejected findings (a person said they are wrong) and Maya's own limits count for nothing; Info notes are not issues.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Callable

RESULTS = ("pass", "issue", "missing_data", "review", "na")
PROBLEM = ("S1", "S2", "S3", "S4")
SEV_ORDER = {"S1": 0, "S2": 1, "S3": 2, "S4": 3}

WORDS = {
    "tr": {
        "result": {"pass": "Geçti", "issue": "Sorun", "missing_data": "Veri eksik", "review": "İnceleme gerekli", "na": "Uygulanmaz"},
        "source": {"gsc": "Search Console", "ga4": "GA4", "pagespeed": "PageSpeed", "merchant": "Merchant Center",
                   "manual": "Manuel", "bing": "Bing Webmaster Tools", "gbp": "Google Business Profile",
                   "logs": "Sunucu logları", "dataforseo": "DataForSEO", "crm": "CRM", "indexnow": "IndexNow anahtarı",
                   "render": "JS render"},
        "sheet": "Kontrol listesi", "totals_sheet": "Kontrol listesi özeti",
        "cols": ["ID", "Grup", "Kontrol maddesi", "Öncelik", "Sonuç", "Kanıt", "Maya kuralı / kart", "Eksik veri kaynağı",
                 "Nasıl kontrol edilir", "Gereken veri / neden uzman", "Otomatikleştirme önerisi"],
        "total_cols": ["Grup", "Madde", "Geçti", "Sorun", "Veri eksik", "İnceleme gerekli", "Uygulanmaz",
                       "Otomatik", "Veri gerekir", "Uzman incelemesi"],
        "how": {"auto": "Otomatik", "data": "Veri gerekir", "expert": "Uzman incelemesi"},
        "how_lines": {"auto": "Otomatik: {n} madde (tarama ölçer)",
                      "data": "Veri gerekir: {n} madde ({maya} tanesi Maya'nın Search Console verisi eklenince ölçülür; bu denetimde ölçülen: {done})",
                      "expert": "Uzman incelemesi: {n} madde ({could} tanesi otomatikleştirilebilir: küçük {s}, orta {m}, büyük {l} iş)"},
        "how_title": "Nasıl kontrol edilir",
        "maya_can": "Maya'nın Search Console verisi eklenince ölçülür", "maya_done": "bu denetimde Maya verisiyle ölçüldü",
        "maya_cannot": "Maya'nın Search Console verisi bu raporu içermez",
        "effort": {"S": "küçük", "M": "orta", "L": "büyük"},
        "all": "Toplam", "card": "Kart {n}", "more": " (+{n} bulgu daha)",
        "issue": "{title}", "issue_scope": "{title} ({scope})", "confirm": "Teyit edin listesinde: {title}",
        "manual": "Crawl ile görülemez; ekip elle doldurmalı.",
        "needs": "{sources} bağlı değil; bu madde bu veriyle değerlendirilir.",
        "review": "Uzman değerlendirmesi gerekir; Maya bu kararı vermez.",
        "review_seen": "Uzman değerlendirmesi gerekir; Maya'nın ölçtüğünde sorun yok ({checks}).",
        "missing": "Maya bunu henüz otomatik kontrol etmiyor; elle bakılmalı.",
        "not_run": "{checks} bu denetimde çalışmadı.",
        "not_about": "Okunan sayfalarda {checks} kontrolünün konusu yok.",
        "pass": "{checks}: sorun bulunmadı ({pages} sayfa okundu).",
        "pass_plain": "{checks}: sorun bulunmadı.",
        "rest_data": "Maya'nın baktığı kısımda sorun yok ({checks}); kalanı için {sources} gerekli.",
        "rest_review": "Maya'nın baktığı kısımda sorun yok ({checks}); kalanı uzman incelemesi ister.",
        "when": {"ecommerce": "Ürün sayfası okunmadı; iş türü: {business}.",
                 "languages": "Tek dil: hreflang ya da dil klasörü yok.",
                 "local": "Yerel işletme işareti yok (LocalBusiness, şube sayfası); iş türü: {business}.",
                 "layers": "Kategori sayfası okunmadı; site tek katmanlı.",
                 "lists": "Liste (kategori) sayfası okunmadı.",
                 "articles": "Blog / makale sayfası okunmadı.",
                 "large": "{n} adres bulundu (10.000'in altında); parametre büyümesi yok.",
                 "site_search": "Site içi arama adresi bulunmadı.",
                 "indexnow": "IndexNow anahtarı verilmedi (isteğe bağlı).",
                 "news": "Haber sitesi değil (NewsArticle ya da haber sayfası yok).",
                 "pdf": "PDF bağlantısı bulunmadı.",
                 "schema": "Yapılandırılmış veri bulunmadı.",
                 "sitemap": "Site haritası bulunmadı.",
                 "faq": "SSS bloğu ya da FAQPage bulunmadı.",
                 "video": "Video bulunmadı (VideoObject ya da video bulgusu yok).",
                 "js_gap": "Ham ve render edilen HTML arasında fark yok (RND-1); SPA / headless değil."},
        "business": "İş türü: {business}; platform: {platform}; sayfa tipleri: {types}.",
        "types": "Sayfa tipleri ({pages} sayfa): {types}.",
        "inventory": "Tarama + site haritası: {found} adres ({listed} site haritasında); GSC/GA4 adresleri yok.",
        "field": "Saha verisi (CrUX, {form}, son 28 gün) laboratuvar ölçümünden ayrı tutuldu.",
        "field_none": "CrUX saha verisi yok.",
        "metric": "{label} p75 {value} ({rating}).",
        "ratings": {"good": "iyi", "needs improvement": "iyileştirilmeli", "poor": "zayıf"},
        "segments": "Yalnız alan adı geneli saha verisi var; şablon ve cihaz bazında PageSpeed ölçümü yok.",
        "scope": "Başlangıç {start}; {cap} sayfa sınırı; {read} sayfa okundu, {found} adres bulundu.",
        "complete": "{read} sayfa okundu, {not_read} adres okunmadı ({why}); kapsam her raporda yazılı.",
        "retest": "Ciddi bulgular aynı denetimde yeniden soruldu ({n} bulgu).",
        "retest_none": "Yeniden sorulacak ciddi bulgu yoktu.",
        "link_flow": "Her sayfanın iç bağlantı puanı ve önemi hesaplandı; trafik ağırlığı için Search Console ve GA4 gerekli.",
        "follow_up": "Denetimler arası karşılaştırma ve görev durumu var; performans takibi için Search Console ve GA4 gerekli.",
        "stop": {"page_cap": "sayfa sınırı", "time_limit": "süre sınırı", "done": "okunacak sayfa kalmadı"},
        "form": {"PHONE": "telefon", "DESKTOP": "masaüstü"},
        "page_type": {"home": "ana sayfa", "category": "kategori", "product": "ürün", "blog_article": "blog",
                      "location": "mağaza / konum", "policy": "politika", "utility": "yardımcı", "other": "diğer"},
    },
    "en": {
        "result": {"pass": "Pass", "issue": "Issue", "missing_data": "Data missing", "review": "Needs review", "na": "Not applicable"},
        "source": {"gsc": "Search Console", "ga4": "GA4", "pagespeed": "PageSpeed", "merchant": "Merchant Center",
                   "manual": "Manual", "bing": "Bing Webmaster Tools", "gbp": "Google Business Profile",
                   "logs": "Server logs", "dataforseo": "DataForSEO", "crm": "CRM", "indexnow": "IndexNow key",
                   "render": "JS rendering"},
        "sheet": "Checklist", "totals_sheet": "Checklist totals",
        "cols": ["ID", "Group", "Item", "Priority", "Result", "Evidence", "Maya rule / card", "Missing data source",
                 "How it is checked", "Data needed / why an expert", "How it could be automated"],
        "total_cols": ["Group", "Items", "Pass", "Issue", "Data missing", "Needs review", "Not applicable",
                       "Automatic", "Needs data", "Expert review"],
        "how": {"auto": "Automatic", "data": "Needs data", "expert": "Expert review"},
        "how_lines": {"auto": "Automatic: {n} items (the crawl measures them)",
                      "data": "Needs data: {n} items ({maya} measured once Maya's Search Console data is attached; measured in this audit: {done})",
                      "expert": "Expert review: {n} items ({could} could be automated: small {s}, medium {m}, large {l})"},
        "how_title": "How it is checked",
        "maya_can": "measured once Maya's Search Console data is attached", "maya_done": "measured with Maya data in this audit",
        "maya_cannot": "Maya's Search Console data does not hold this report",
        "effort": {"S": "small", "M": "medium", "L": "large"},
        "all": "Total", "card": "Card {n}", "more": " (+{n} more)",
        "issue": "{title}", "issue_scope": "{title} ({scope})", "confirm": "Waiting under Confirm first: {title}",
        "manual": "A crawl cannot see this; the team fills it in by hand.",
        "needs": "{sources} not connected; this item is judged with that data.",
        "review": "Needs an expert's judgement; Maya does not make this call.",
        "review_seen": "Needs an expert's judgement; nothing wrong in what Maya measured ({checks}).",
        "missing": "Maya does not check this automatically yet; look by hand.",
        "not_run": "{checks} did not run in this audit.",
        "not_about": "No page read is what {checks} is about.",
        "pass": "{checks}: nothing found ({pages} pages read).",
        "pass_plain": "{checks}: nothing found.",
        "rest_data": "Nothing wrong in Maya's part ({checks}); the rest needs {sources}.",
        "rest_review": "Nothing wrong in Maya's part ({checks}); the rest needs an expert.",
        "when": {"ecommerce": "No product page read; business type: {business}.",
                 "languages": "One language: no hreflang or language folder.",
                 "local": "No local-business signal (LocalBusiness, branch pages); business type: {business}.",
                 "layers": "No category page read; the site has one level.",
                 "lists": "No list (category) page read.",
                 "articles": "No blog or article page read.",
                 "large": "{n} addresses found (under 10,000); no parameter growth.",
                 "site_search": "No internal search address found.",
                 "indexnow": "No IndexNow key given (optional).",
                 "news": "Not a news site (no NewsArticle or news page).",
                 "pdf": "No PDF link found.",
                 "schema": "No structured data found.",
                 "sitemap": "No sitemap found.",
                 "faq": "No FAQ block or FAQPage found.",
                 "video": "No video found (no VideoObject or video finding).",
                 "js_gap": "No gap between raw and rendered HTML (RND-1); not a SPA or headless site."},
        "business": "Business type: {business}; platform: {platform}; page types: {types}.",
        "types": "Page types ({pages} pages): {types}.",
        "inventory": "Crawl + sitemap: {found} addresses ({listed} in sitemaps); no GSC/GA4 addresses.",
        "field": "Field data (CrUX, {form}, last 28 days) kept apart from lab results.",
        "field_none": "No CrUX field data.",
        "metric": "{label} p75 {value} ({rating}).",
        "ratings": {"good": "good", "needs improvement": "needs improvement", "poor": "poor"},
        "segments": "Only origin-wide field data; no PageSpeed run per template and device.",
        "scope": "Start {start}; page cap {cap}; {read} pages read, {found} addresses found.",
        "complete": "{read} pages read, {not_read} addresses not read ({why}); the scope is written in every report.",
        "retest": "Serious findings were asked again in the same audit ({n} findings).",
        "retest_none": "No serious finding to ask again.",
        "link_flow": "Each page's internal link score and importance were worked out; traffic weighting needs Search Console and GA4.",
        "follow_up": "Audit-to-audit comparison and task status exist; performance tracking needs Search Console and GA4.",
        "stop": {"page_cap": "page cap", "time_limit": "time limit", "done": "no pages left"},
        "form": {"PHONE": "phone", "DESKTOP": "desktop"},
        "page_type": {"home": "home", "category": "category", "product": "product", "blog_article": "blog",
                      "location": "store / location", "policy": "policy", "utility": "utility", "other": "other"},
    },
}
# A check that could not run, and the data source it waited for.
CHECK_SOURCE = {"PRF-3": "pagespeed", "IDX-9": "gsc", "IDX-10": "bing", "ACC-5": "logs", "RND-1": "render",
                "RND-2": "render", "RND-3": "render"}
LOCAL_TYPES = frozenset({"LocalBusiness", "Restaurant", "Store", "Hospital", "MedicalClinic", "Dentist", "AutoDealer",
                         "FoodEstablishment", "Hotel", "BankOrCreditUnion", "Pharmacy", "Physician", "AutoRepair"})
LOCAL_BUSINESS = frozenset({"restoran", "saglik", "otomotiv", "su_aritma", "ev_hizmetleri", "guvenlik"})


@lru_cache(maxsize=1)
def items() -> tuple[dict, ...]:
    data = json.loads((Path(__file__).parent / "checklist_items.json").read_text(encoding="utf-8"))
    return tuple(data["items"])


def groups_in_order() -> list[str]:
    seen: list[str] = []
    for it in items():
        if it["group"] not in seen:
            seen.append(it["group"])
    return seen


# ------------------------------------------------------------------------------------------------ facts from a report

def facts(report: dict) -> dict:
    """What the checklist reads from a report besides the findings: each check's status, the data connections (yes or
    no; never a key or token), the Core Web Vitals field data and the site's shape. Kept in the selection
    (`_checklist_facts`) so the appendix and the team report need no report."""
    from .client_selection import pages_read
    crawl = report.get("crawl") or {}
    checks = {c.get("check_id"): {"status": c.get("status"), "summary": c.get("summary") or ""}
              for c in report.get("checks") or [] if c.get("check_id")}
    by = {c.get("check_id"): c for c in report.get("checks") or []}
    status = lambda cid: (checks.get(cid) or {}).get("status")  # noqa: E731
    cfg = crawl.get("config") or {}
    crux = report.get("crux") or {}
    grouping = crawl.get("page_grouping") or crawl.get("reader_page_grouping") or {}
    types_seen = ((by.get("STR-3") or {}).get("evidence") or {}).get("types_seen") or {}
    discovered = [str(u) for u in crawl.get("discovered_urls") or []]
    rule_ids = {f.get("rule_id") or "" for c in report.get("checks") or [] for f in c.get("findings") or []}
    bt = crawl.get("business_type") or {}
    locales = crawl.get("locales") or {}
    return {
        "checks": checks,
        # DECISIONS 365: every address the crawl knows (pages, links, sitemaps), as one key per page, for the items Maya's
        # Search Console data measures (checklist_maya)
        "known": sorted({_key(u) for u in discovered + [str(u) for u in crawl.get("sitemap_urls") or []]
                         + [str(p.get("url")) for p in crawl.get("pages") or [] if isinstance(p, dict) and p.get("url")]}),
        "connected": {
            "gsc": status("IDX-9") not in (None, "not_assessed"),
            "bing": status("IDX-10") not in (None, "not_assessed") and bool(cfg.get("bing_api_key")),
            "indexnow": bool(cfg.get("indexnow_key") or cfg.get("indexnow_key_location")),
            "pagespeed": crux.get("status") == "assessed" or status("PRF-3") not in (None, "not_assessed"),
            "logs": status("ACC-5") not in (None, "not_assessed"),
            "dataforseo": bool((report.get("dataforseo") or {}).get("checks")),
            "render": any(status(c) not in (None, "not_assessed") for c in ("RND-1", "RND-2", "RND-3")),
            "ga4": False, "merchant": False, "gbp": False, "crm": False, "manual": False,
        },
        "crux": {"status": crux.get("status"), "form_factor": crux.get("form_factor"),
                 "metrics": [{k: m.get(k) for k in ("metric", "label", "shown", "rating")} for m in crux.get("metrics") or []]},
        "lab": status("PRF-3") not in (None, "not_assessed"),
        "site": {
            "business": {"id": bt.get("id"), "label": bt.get("label") or {}},
            "platform": (report.get("platform") or {}).get("name"),
            "page_types": grouping.get("page_types") or {},
            "pages_read": len(pages_read(report)),
            "found": len(discovered), "listed": len(crawl.get("sitemap_urls") or []),
            "sitemaps": len(crawl.get("sitemap_docs") or []),
            "start": crawl.get("start_url"), "cap": cfg.get("max_pages"), "stop": crawl.get("stop_reason"),
            "not_read": len(crawl.get("not_fetched_urls") or []),
            "types_seen": sorted(types_seen),
            "languages": bool(locales.get("folders")) or (locales.get("versions") or 0) > 1
            or any(r.startswith("str9.") for r in rule_ids),
            "pdf": any(u.lower().split("?")[0].endswith(".pdf") for u in discovered),
            "site_search": any(s in u.lower() for u in discovered for s in ("/search", "/arama", "?q=", "?s=", "&q=")),
            "js_gap": any(r.startswith(("rnd1.", "rnd2.")) for r in rule_ids),
            "video": "VideoObject" in types_seen or any(r.startswith(("str7.video", "idx5.no_video", "str20.")) for r in rule_ids),
            "news": "NewsArticle" in types_seen or (grouping.get("page_types") or {}).get("news", 0) > 0,
            # the final re-asking of serious findings (final.verify): findings asked again, and whether it ran
            "verified": (crawl.get("verification") or {}).get("findings") or 0 if isinstance(crawl.get("verification"), dict) else 0,
            "verification": bool((crawl.get("verification") or {}).get("enabled")) if isinstance(crawl.get("verification"), dict) else False,
        },
    }


def _key(url: str) -> str:
    from .checklist_maya import key
    return key(url)


@lru_cache(maxsize=1)
def _how_notes() -> dict:
    return json.loads((Path(__file__).parent / "checklist_how.json").read_text(encoding="utf-8"))["items"]


def how(item: dict) -> dict:
    """DECISIONS 365: how an item is checked. "data" when a data source it needs is outside the crawl (Search Console,
    GA4, Bing, PageSpeed, logs...), with those sources; else "expert" when its decision, or the part Maya does not
    measure, needs a person (a judgement, a manual item, a rule not built yet), with why and how it could become
    automatic (`checklist_how.json`); else "auto": the crawl measures it. `maya`: Maya's Search Console data measures it."""
    from .checklist_maya import ITEMS
    sources = [s for s in item.get("needs") or [] if s != "manual"]
    if isinstance(item.get("rest"), list):
        sources += [s for s in item["rest"] if s not in sources]
    if sources:
        kind = "data"
    elif item["method"] in ("review", "manual", "missing", "data") or item.get("rest") == "review":
        kind = "expert"
    else:
        kind = "auto"
    note = _how_notes().get(item["id"]) or {} if kind == "expert" else {}
    return {"kind": kind, "sources": sources, "maya": item["id"] in ITEMS, "why": note.get("why") or "",
            "effort": note.get("effort") or "", "automate": note.get("automate") or ""}


# ---------------------------------------------------------------------------------------------------- the decisions

def _site_holds(when: str | None, site: dict) -> bool:
    if not when:
        return True
    t = site.get("page_types") or {}
    bid = (site.get("business") or {}).get("id")
    seen = set(site.get("types_seen") or [])
    return {
        "ecommerce": t.get("product", 0) > 0 or bid == "eticaret",
        "languages": bool(site.get("languages")),
        "local": bid in LOCAL_BUSINESS or bool(seen & LOCAL_TYPES),
        "layers": t.get("category", 0) > 0 or "BreadcrumbList" in seen,
        "lists": t.get("category", 0) > 0,
        "articles": t.get("blog_article", 0) > 0,
        "large": (site.get("found") or 0) >= 10000,
        "site_search": bool(site.get("site_search")),
        "indexnow": False,  # decided from the connections below
        "news": bool(site.get("news")),
        "pdf": bool(site.get("pdf")),
        "schema": bool(seen),
        "sitemap": (site.get("sitemaps") or 0) > 0,
        "faq": "FAQPage" in seen or "Question" in seen,
        "video": bool(site.get("video")),
        "js_gap": bool(site.get("js_gap")),
    }.get(when, True)


def _matches(rule_id: str | None, check_id: str | None, item: dict) -> bool:
    if item["rules"]:
        return any((rule_id or "").startswith(p) for p in item["rules"])
    return bool(item["checks"]) and check_id in item["checks"] and item["method"] in ("full", "partial")


def _group_hits(item: dict, selection: dict) -> tuple[list[dict], list[dict]]:
    """(problem groups shown as cards or in the appendix, problem groups waiting under "Teyit edin") of the item."""
    problems, confirm = [], []
    for g in selection.get("groups") or []:
        if g.get("severity") not in PROBLEM or g.get("placement") in ("rejected", "own_limit"):
            continue
        if not any(_matches(m.get("rule_id"), m.get("check_id"), item) for m in g.get("members") or [g.get("lead") or {}]):
            continue
        (confirm if g.get("placement") == "confirm" else problems).append(g)
    key = lambda g: (SEV_ORDER.get(g.get("severity"), 9), g.get("card") or 999)  # noqa: E731
    return sorted(problems, key=key), sorted(confirm, key=key)


def _row(item: dict, result: str, evidence: str, ref: str = "", missing: list[str] | None = None) -> dict:
    return {"id": item["id"], "group": item["group"], "item": item["item"], "priority": item.get("priority") or "",
            "result": result, "evidence": evidence, "ref": ref, "missing_sources": missing or []}


def _join(words: list[str], lang: str) -> str:
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + (" ve " if lang == "tr" else " and ") + words[-1]


def _special(item: dict, F: dict, W: dict, lang: str) -> dict | None:
    site, iid = F["site"], item["id"]
    business = ((site.get("business") or {}).get("label") or {}).get(lang) or (site.get("business") or {}).get("id") or "—"
    types = ", ".join(f"{W['page_type'].get(k, k)} {v}" for k, v in
                      sorted((site.get("page_types") or {}).items(), key=lambda kv: -kv[1]))
    if iid == "SEO-003":
        if not (site.get("business") or {}).get("id"):
            return None
        return _row(item, "pass", W["business"].format(business=business, platform=site.get("platform") or "—",
                                                       types=types or "—"), "business_type, page_grouping")
    if iid == "SEO-006":
        if not site.get("page_types"):
            return None
        return _row(item, "pass", W["types"].format(pages=sum(site["page_types"].values()), types=types), "page_grouping")
    if iid == "SEO-005":
        return _row(item, "missing_data", W["inventory"].format(found=site.get("found") or 0, listed=site.get("listed") or 0),
                    "IDX-5, IDX-7", ["gsc", "ga4"])
    crux = F.get("crux") or {}
    if iid in ("SEO-110", "SEO-111", "SEO-112", "SEO-113"):
        if crux.get("status") != "assessed":
            return None
        if iid == "SEO-110":
            return _row(item, "pass", W["field"].format(form=W["form"].get(crux.get("form_factor"), crux.get("form_factor") or "")),
                        "PRF-3 · CrUX")
        name = {"SEO-111": "largest_contentful_paint", "SEO-112": "interaction_to_next_paint",
                "SEO-113": "cumulative_layout_shift"}[iid]
        m = next((x for x in crux.get("metrics") or [] if x.get("metric") == name), None)
        if not m or not m.get("rating"):
            return _row(item, "missing_data", W["field_none"], "PRF-3 · CrUX", ["pagespeed"])
        text = W["metric"].format(label=(m.get("label") or name).split(" (")[-1].rstrip(")"), value=m.get("shown"),
                                  rating=W["ratings"].get(m["rating"], m["rating"]))
        return _row(item, "pass" if m["rating"] == "good" else "issue", text, "PRF-3 · CrUX")
    if iid == "SEO-057" and site.get("page_types"):
        return _row(item, "missing_data", W["link_flow"], "page_grouping", ["gsc", "ga4"])
    if iid == "SEO-165":
        return _row(item, "missing_data", W["follow_up"], "comparison", ["gsc", "ga4"])
    if iid == "SEO-114" and crux.get("status") == "assessed" and not F.get("lab"):
        return _row(item, "missing_data", W["segments"], "PRF-3 · CrUX", ["pagespeed"])
    if iid == "SEO-152" and site.get("start"):
        return _row(item, "pass", W["scope"].format(start=site["start"], cap=site.get("cap") or "—",
                                                    read=site.get("pages_read") or 0, found=site.get("found") or 0), "INT-2")
    if iid == "SEO-155" and site.get("start"):
        why = W["stop"].get(site.get("stop") or "", site.get("stop") or "—")
        return _row(item, "pass", W["complete"].format(read=site.get("pages_read") or 0, not_read=site.get("not_read") or 0,
                                                       why=why), "INT-2")
    if iid == "SEO-164" and site.get("verification"):
        n = site.get("verified") or 0
        return _row(item, "pass", W["retest"].format(n=n) if n else W["retest_none"], "final.verify")
    return None


def _group_title(g: dict, cards: dict[str, int], todos_by_n: dict, title: Callable | None) -> tuple[str, int | None]:
    n = next((cards[f] for f in g.get("finding_ids") or [] if f in cards), None)
    if n is not None and todos_by_n.get(n):
        return todos_by_n[n], n
    lead = g.get("lead") or {}
    text = (title(lead.get("check_id"), lead.get("title") or "") if title else None) or lead.get("title") or g.get("title") or ""
    return text, n


def judge(item: dict, selection: dict, lang: str = "tr", cards: dict[str, int] | None = None,
          todos_by_n: dict | None = None, title: Callable | None = None, maya: dict | None = None) -> dict:
    """One item's row; in English with the item's and group's English names (the checklist is Turkish). `maya`: the
    summary of the Maya data attached to the audit (DECISIONS 365: the items its Search Console data measures)."""
    row = _judge(item, selection, lang, cards, todos_by_n, title, maya)
    row["how"] = how(item)
    if lang == "en":  # the reasons are written in Turkish; an English row gives the item's English mapping note
        row["how"] = {**row["how"], "why": item.get("maya_note") or "" if row["how"]["kind"] == "expert" else "",
                      "automate": ""}
    if lang == "en":
        row.update(group=item.get("group_en") or item["group"], item=item.get("item_en") or item["item"])
    return row


def _judge(item: dict, selection: dict, lang: str, cards: dict[str, int] | None, todos_by_n: dict | None,
           title: Callable | None, maya: dict | None = None) -> dict:
    W = WORDS[lang]
    F = selection.get("_checklist_facts") or {"checks": {}, "connected": {}, "site": {}}
    site, conn, statuses = F["site"], F["connected"], F["checks"]
    checks = ", ".join(item["checks"])
    if item.get("when") == "indexnow":
        if not conn.get("indexnow"):
            return _row(item, "na", W["when"]["indexnow"], "IDX-10")
    elif not _site_holds(item.get("when"), site):
        business = ((site.get("business") or {}).get("label") or {}).get(lang) or (site.get("business") or {}).get("id") or "—"
        return _row(item, "na", W["when"][item["when"]].format(business=business, n=site.get("found") or 0), checks)
    from .checklist_maya import row as maya_row
    measured = maya_row(item["id"], maya, selection, lang) if maya else None
    if measured and not _group_hits(item, selection)[0]:
        # DECISIONS 365: measured with Maya's Search Console data; GA4 and other sources it does not hold stay missing
        rest = [s for s in how(item)["sources"] if s != "gsc" and not conn.get(s)]
        return {**_row(item, measured[0], measured[1], measured[2], rest), "maya": True}
    special = _special(item, F, W, lang)
    if special:
        return special
    problems, confirm = _group_hits(item, selection)
    if problems:
        g = problems[0]
        text, n = _group_title(g, cards or {}, todos_by_n or {}, title)
        rule = (g.get("lead") or {}).get("rule_id") or g.get("check_id") or ""
        ref = " · ".join(x for x in (W["card"].format(n=n) if n is not None else "", rule) if x)
        more = W["more"].format(n=len(problems) - 1) if len(problems) > 1 else ""
        return _row(item, "issue", W["issue"].format(title=text) + more, ref)
    if confirm:
        g = confirm[0]
        text, _ = _group_title(g, cards or {}, todos_by_n or {}, title)
        return _row(item, "review", W["confirm"].format(title=text), (g.get("lead") or {}).get("rule_id") or "")
    src = lambda keys: _join([W["source"][k] for k in keys], lang)  # noqa: E731
    if item["method"] == "manual":
        return _row(item, "missing_data", W["manual"], "", ["manual"])
    lacking = [s for s in item.get("needs") or [] if not conn.get(s)]
    if lacking:
        return _row(item, "missing_data", W["needs"].format(sources=src(lacking)), checks, lacking)
    ran = [c for c in item["checks"] if c in statuses]
    if item["method"] == "review":
        clean = [c for c in ran if statuses[c]["status"] in ("pass", "partial", "findings")]
        return _row(item, "review", W["review_seen"].format(checks=", ".join(clean)) if clean else W["review"], checks)
    if item["method"] == "missing":
        return _row(item, "review", W["missing"], checks)
    if ran and all(statuses[c]["status"] == "not_assessed" for c in ran):
        need = sorted({CHECK_SOURCE.get(c, "manual") for c in ran}, key=list(W["source"]).index)
        return _row(item, "missing_data", W["not_run"].format(checks=", ".join(ran)), checks, need)
    if ran and all(statuses[c]["status"] == "not_applicable" for c in ran):
        return _row(item, "na", W["not_about"].format(checks=", ".join(ran)), checks)
    shown = ", ".join(c for c in ran if statuses[c]["status"] not in ("not_assessed", "not_applicable")) or "—"
    if item["method"] == "partial" and item.get("rest"):
        rest = item["rest"]
        if rest == "review":
            return _row(item, "review", W["rest_review"].format(checks=shown), checks)
        lacking = [s for s in rest if not conn.get(s)]
        if lacking:
            return _row(item, "missing_data", W["rest_data"].format(checks=shown, sources=src(lacking)), checks, lacking)
    pages = site.get("pages_read")
    return _row(item, "pass", W["pass"].format(checks=shown, pages=pages) if pages else W["pass_plain"].format(checks=shown),
                checks)


def rows(selection: dict, lang: str = "tr", todos: list[dict] | None = None, title: Callable | None = None,
         maya: dict | None = None) -> list[dict]:
    """All 165 items, in the checklist's order, judged on this audit. `todos`: the team report's cards, so an issue
    names the PDF's card number and title; `maya`: the attached Maya data's summary."""
    from .page_rows import card_of
    cards, shown = card_of(selection, todos, lang, title)
    todos_by_n = {c["n"]: c.get("title") for c in shown if c.get("n") is not None}
    return [judge(it, selection, lang, cards, todos_by_n, title, maya) for it in items()]


def how_counts(table: list[dict]) -> dict:
    """DECISIONS 365: items per way of checking, the data items Maya's data measures (and did in this audit), and the
    expert items that could become automatic by effort."""
    hows = [r["how"] for r in table]
    expert = [h for h in hows if h["kind"] == "expert"]
    return {"auto": sum(h["kind"] == "auto" for h in hows), "data": sum(h["kind"] == "data" for h in hows),
            "expert": len(expert), "maya": sum(h["kind"] == "data" and h["maya"] for h in hows),
            "done": sum(1 for r in table if r.get("maya")),
            "could": sum(1 for h in expert if h["effort"] in ("S", "M", "L")),
            "effort": {e: sum(1 for h in expert if h["effort"] == e) for e in ("S", "M", "L")}}


def how_detail(r: dict, lang: str) -> tuple[str, str]:
    """(data needed or why an expert, how it could be automated) for a row's item."""
    W, h = WORDS[lang], r["how"]
    if h["kind"] == "data":
        text = _join([W["source"].get(s, s) for s in h["sources"]], lang)
        if h["maya"]:
            text += "; " + (W["maya_done"] if r.get("maya") else W["maya_can"])
        elif "gsc" in h["sources"]:
            text += "; " + W["maya_cannot"]
        return text, ""
    if h["kind"] == "expert":
        plan = f"{W['effort'][h['effort']]}: {h['automate']}" if h["effort"] in W["effort"] else h["automate"]
        return h["why"], plan if lang == "tr" else (W["effort"].get(h["effort"], "") if h["effort"] in W["effort"] else "—")
    return "", ""


def totals(table: list[dict]) -> dict:
    """{"all": {result: n}, "groups": [{"group", "n", "counts": {result: n}}]} in the checklist's group order."""
    def count(rs):
        return {r: sum(1 for x in rs if x["result"] == r) for r in RESULTS}
    order = list(dict.fromkeys(x["group"] for x in table))  # the checklist's group order, in the table's language
    by_group = [{"group": g, "n": len(rs), "counts": count(rs)} for g in order for rs in [[x for x in table if x["group"] == g]]]
    return {"all": count(table), "n": len(table), "groups": by_group}


def sheets(selection: dict, lang: str = "tr", todos: list[dict] | None = None, title: Callable | None = None,
           maya: dict | None = None) -> list[dict]:
    """The appendix's two checklist sheets: every item, then the totals per result and per group. DECISIONS 365: each
    item says how it is checked (Otomatik / Veri gerekir / Uzman incelemesi), the data it needs or why an expert, and how
    it could become automatic; the first rows of "Kontrol listesi" count the items of each way, and the totals count
    them per group."""
    W = WORDS[lang]
    table = rows(selection, lang, todos, title, maya)
    body = []
    for r in table:
        detail, plan = how_detail(r, lang)
        body.append([r["id"], r["group"], r["item"], r["priority"], W["result"][r["result"]], r["evidence"], r["ref"],
                     ", ".join(W["source"].get(s, s) for s in r["missing_sources"]), W["how"][r["how"]["kind"]], detail, plan])
    c = how_counts(table)
    lines = [W["how_lines"]["auto"].format(n=c["auto"]),
             W["how_lines"]["data"].format(n=c["data"], maya=c["maya"], done=c["done"]),
             W["how_lines"]["expert"].format(n=c["expert"], could=c["could"], s=c["effort"]["S"], m=c["effort"]["M"],
                                             l=c["effort"]["L"])]
    top = [[W["how_title"] if i == 0 else "", line] + [""] * (len(W["cols"]) - 2) for i, line in enumerate(lines)]
    t = totals(table)
    kinds = ("auto", "data", "expert")
    per = {g: [sum(1 for r in table if r["group"] == g and r["how"]["kind"] == k) for k in kinds] for g in {r["group"] for r in table}}
    total_rows = [[W["all"], t["n"], *(t["all"][r] for r in RESULTS), c["auto"], c["data"], c["expert"]]]
    total_rows += [[g["group"], g["n"], *(g["counts"][r] for r in RESULTS), *per[g["group"]]] for g in t["groups"]]
    return [{"name": W["sheet"], "header": W["cols"], "rows": top + body, "title_rows": len(top),
             "widths": [9, 34, 34, 8, 16, 80, 30, 26, 18, 60, 60]},
            {"name": W["totals_sheet"], "header": W["total_cols"], "rows": total_rows,
             "widths": [46, 8, 9, 9, 11, 16, 12, 11, 13, 16]}]
