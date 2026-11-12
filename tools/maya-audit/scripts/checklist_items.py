"""Builds maya_audit/checklist_items.json, the SEO team's 165-item checklist as Maya reads it (DECISIONS 342).

Source: reviews/checklist/mapping.xlsx (sheet "Mapping": the team's SEO_Audit_Checklist.xlsx items with Maya's status,
rule IDs and missing data per item, 2026-11-03). The reviews folder is not in git, so the JSON is committed and this
script is only needed when the mapping changes. Per item it keeps:
  id, group, item, priority, applies_to (the checklist's "Uygulanabilirlik");
  method: full | partial | review (AI+expert) | manual | data (needs a connection) | missing (not automated yet);
  checks: Maya check IDs the item reads; rules: rule-id prefixes (empty: any finding of `checks`);
  needs: data sources the whole item depends on; rest: what a partial item still needs once Maya's part is clean
    ("review", or data sources); when: the site condition the item applies under (None: every site).
Run: python scripts/checklist_items.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "reviews" / "checklist" / "mapping.xlsx"
OUT = ROOT / "maya_audit" / "checklist_items.json"

METHOD = {"Full": "full", "Partial": "partial", "AI+expert": "review", "Manual": "manual",
          "Needs free connection": "data", "Missing-automatable": "missing"}
SOURCE_WORDS = (("Merchant Center", "merchant"), ("GSC", "gsc"), ("GA4", "ga4"), ("logs", "logs"), ("GBP", "gbp"),
                ("CRM", "crm"), ("CrUX", "pagespeed"), ("PSI", "pagespeed"), ("Bing", "bing"), ("DFS", "dataforseo"))
# "Uygulanabilirlik" -> the site condition (maya_audit.checklist.CONDITIONS); missing: every site
WHEN = {"E-ticaret": "ecommerce", "Çok dilli / ülkeli": "languages", "Çok dilli siteler": "languages",
        "Yerel işletmeler": "local", "Çok şubeli / yerel": "local", "Çok katmanlı siteler": "layers",
        "Filtreli listeler": "ecommerce", "Liste sayfaları": "lists", "İçerik barındıran siteler": "articles",
        "Blog / yayın": "articles", "Haber / blog / rehber": "articles", "Uzmanlık içerikleri": "articles",
        "Büyük / yoğun parametreli siteler": "large", "Dahili araması olan siteler": "site_search",
        "Destekli altyapılar / opsiyonel": "indexnow", "Medya / haber siteleri": "news", "PDF barındıran siteler": "pdf",
        "Schema kullanan siteler": "schema", "Sitemap kullanan siteler": "sitemap", "SSS olan sayfalar": "faq",
        "Video siteleri": "video", "SPA / Headless": "js_gap", "Headless / JS siteler": "js_gap"}
# What a partial item still needs when Maya's own part found nothing (agent defaults, DECISIONS 342): data sources
# when the mapping names them, else "review" (the rest is a judgement or a part Maya does not check yet); None: Maya's
# part is the item.
REST = {"SEO-003": None, "SEO-005": ["gsc", "ga4"], "SEO-013": ["gsc"], "SEO-023": ["gsc"], "SEO-025": ["gsc", "ga4"],
        "SEO-037": ["bing"], "SEO-057": ["gsc", "ga4"], "SEO-067": None, "SEO-068": ["dataforseo"],
        "SEO-094": ["merchant"], "SEO-101": ["gsc"], "SEO-108": None, "SEO-114": ["pagespeed"], "SEO-149": ["gbp"],
        "SEO-157": ["dataforseo"], "SEO-160": ["gsc"], "SEO-165": ["gsc", "ga4"]}
# Items whose data source column names a connection the whole item depends on.
NEEDS = {"SEO-023": ["gsc"], "SEO-037": ["bing"], "SEO-038": ["indexnow"], "SEO-068": ["dataforseo"],
         "SEO-110": ["pagespeed"], "SEO-111": ["pagespeed"], "SEO-112": ["pagespeed"], "SEO-113": ["pagespeed"],
         "SEO-114": ["pagespeed"], "SEO-156": ["dataforseo"], "SEO-157": ["dataforseo"],
         "SEO-024": ["gsc", "logs"], "SEO-148": ["gbp"], "SEO-151": ["gbp"], "SEO-162": ["ga4", "crm"]}
# Rule IDs read from the mapping's text that are not finding rule prefixes, and items whose whole check is too wide.
# DECISIONS 343 added the SEO team's technical-review rules to SEO-013, -041, -043, -049, -064, -065, -101, -106, -136
# and -145.
RULES = {"SEO-081": ["str3.qa"], "SEO-108": ["str3.qa"], "SEO-097": ["str3.product_no_identifier"],
         "SEO-078": ["str3.article_no_author"], "SEO-064": ["str16.", "tseo1.description", "str1.subpage_copies_parent"], "SEO-072": ["str10."],
         "SEO-012": ["idx1.5xx", "prf2."], "SEO-161": ["tseo1.analytics_twice"], "SEO-117": ["tseo1.blocking_scripts"],
         "SEO-124": ["tseo1.no_viewport", "tseo1.no_zoom"], "SEO-132": ["tseo1.head_closed", "acc3.robots_outside_head"],
         "SEO-063": ["tseo1.title_"], "SEO-010": ["idx2.expires", "idx2.invalid", "tseo1.mixed"],
         "SEO-009": ["idx2.no_redirect", "idx2.temporary"], "SEO-160": ["acc4.", "tseo1.mixed"], "SEO-115": ["str7.heavy", "str7.over_", "str7.preload"],
         "SEO-116": ["str7.format", "str7.heavy", "str7.over_", "str7.unsized"], "SEO-120": ["str7.unsized"],
         "SEO-138": ["str7.placeholder", "str7.alt_split"], "SEO-139": ["str7.no_alt", "str7.alt"], "SEO-089": ["str7.no_alt"],
         "SEO-140": ["str7.broken", "str7.mime"], "SEO-127": ["str7.no_alt", "str14.", "shared.link_no_text", "str9.lang", "str2."],
         "SEO-056": ["str14.", "shared.link_no_text", "judgment.generic"], "SEO-059": ["str19."], "SEO-133": ["str19."],
         "SEO-052": ["str3.crumb"], "SEO-053": ["str3.crumb", "str3.required"], "SEO-103": ["str3.crumb", "str3.required"],
         "SEO-101": ["str3.required", "str3.invalid", "str3.unparsed", "str13.markers_data", "str3.product_on_article"], "SEO-100": ["str3."],
         "SEO-102": ["str3.organization", "str5."], "SEO-149": ["str5."], "SEO-109": ["str11.", "str3.type_clash", "str3.dangling"],
         "SEO-104": ["str3.product", "str3.required", "str4."], "SEO-106": ["str3.article", "str6.", "str3.product_on_article"],
         "SEO-094": ["str4."], "SEO-098": ["str21."], "SEO-142": ["str7.video", "str3.video", "str20."],
         "SEO-043": ["str1.shared", "idx8.", "str16.", "str1.subpage_copies_parent"], "SEO-062": ["str1."], "SEO-065": ["str2.no_h1", "str2.empty_h1", "str2.hidden_h1", "str2.home_hidden_h1", "str2.home_no_h1", "str2.many_h1",
                     "str2.h1_parent_name", "str1.subpage_copies_parent"],
         "SEO-066": ["str2.no_subheadings", "str2.styled", "tseo1.heading"], "SEO-075": ["str15.", "rnd7."],
         "SEO-076": ["idx8."], "SEO-088": ["idx8."], "SEO-150": ["idx8.location"], "SEO-084": ["str12.", "str9.lang"],
         "SEO-147": ["str12."], "SEO-144": ["str9."], "SEO-145": ["str9.", "str1.subpage_copies_parent"], "SEO-146": ["str9."],
         "SEO-019": ["acc3.", "idx4.", "idx9."], "SEO-021": ["acc3."], "SEO-030": ["acc2.", "acc3."],
         "SEO-016": ["acc4.", "acc9."], "SEO-011": ["idx1."], "SEO-018": ["prf1.slow", "prf1.home_ttfb"],
         "SEO-119": ["prf1.not_cached"], "SEO-125": ["rnd5."], "SEO-137": ["rnd5."], "SEO-129": ["rnd1.", "rnd2."],
         "SEO-131": ["idx1.soft404", "rnd1."], "SEO-134": ["rnd3."], "SEO-047": ["rnd3."], "SEO-136": ["str1.", "str16.", "tseo1.title_", "tseo1.description", "str13.markers"],
         "SEO-055": ["idx6.broken"], "SEO-048": ["idx6.tracking"], "SEO-061": ["idx6.alias_links", "idx6.links_to_redirect"],
         "SEO-026": ["idx7.deep"], "SEO-025": ["idx7.orphan"], "SEO-054": ["idx7.orphan"], "SEO-034": ["idx5.", "idx7."],
         "SEO-032": ["idx5.none", "idx5.failed"], "SEO-033": ["idx5.not_live", "idx5.drafts", "acc3.sitemap_noindex", "idx1.4xx.sitemap", "judgment.sitemap"],
         "SEO-035": ["idx5.identical", "idx5.stamped", "idx5.future", "str6."], "SEO-036": ["idx5.no_image_sitemap", "idx5.no_video_sitemap"],
         "SEO-029": ["acc1."], "SEO-020": ["acc3.noindex", "acc3.sitemap_noindex"], "SEO-031": ["acc3.robots_noindex"],
         "SEO-039": ["idx4."], "SEO-040": ["idx4.broken", "idx4.redirect"], "SEO-041": ["idx4.different", "idx4.same", "idx4.variant", "idx8.self_canonical_copies"],
         "SEO-042": ["idx4.conflict", "idx4.mixed"], "SEO-049": ["idx8.two_addresses", "idx5.not_encoded", "tseo1.url_decomposed", "idx8.self_canonical_copies"],
         "SEO-067": ["tseo1.url_slug_unclear", "tseo1.url_decomposed"], "SEO-013": ["idx1.soft404", "idx1.empty", "idx1.error_text", "idx1.error_redirect"],
         "SEO-014": ["idx3.chain", "idx3.loop", "idx3.to_http", "idx3.cookie", "idx3.intermittent"], "SEO-015": ["idx1.soft404.redirect", "idx3.other_host"],
         "SEO-046": ["idx7.pagination_unlinked"], "SEO-093": ["idx7.product_no_category", "str15.empty_collections"],
         "SEO-099": ["str15.empty_collections"], "SEO-080": ["str6."], "SEO-086": ["str15."], "SEO-060": ["str22."],
         "SEO-005": [], "SEO-152": [], "SEO-153": ["rnd1.", "rnd2."], "SEO-154": ["acc7."], "SEO-155": []}


# English names (DECISIONS 342): the checklist exists in Turkish only; the English report shows these.
GROUP_EN = [
    "Audit preparation and data reliability", "Host, security and HTTP behaviour", "Crawling and indexability",
    "Robots, XML sitemaps and URL discovery", "Canonicals, duplicates and URL parameters",
    "Information architecture and internal links", "On-page and SERP appearance",
    "Content quality and topic strategy", "E-commerce, categories and products", "Schema and machine-readable data",
    "Speed and Core Web Vitals", "Mobile UX, accessibility and conversion", "JS, rendering and head management",
    "Image, video and media SEO", "International and local SEO", "Crawl setup and data quality",
    "Off-page and external links", "GSC manual actions and security", "Measurement accuracy",
    "Verification after fixes",
]
ITEM_EN = [
    "Ownership and access inventory", "Goals and conversions", "Business and site type",
    "Date range and seasonality", "Merged URL inventory", "URL type sample", "GSC property scope",
    "Baseline measurements", "One preferred host", "HTTPS and certificate", "Key URL HTTP status",
    "5xx and infrastructure errors", "Soft 404 and empty templates", "Redirect chains", "Redirect target relevance",
    "CDN / WAF bot blocking", "Dev and staging access", "Server response time", "Indexability of organic pages",
    "Wrong noindex directives", "X-Robots-Tag header", "GSC index coverage", "GSC chosen canonical",
    "Crawl budget anomalies", "Orphan pages", "Crawl depth", "Internal search indexing", "Indexed page sample",
    "robots.txt access", "Robots blocks on key pages", "Robots versus noindex", "XML sitemap discoverability",
    "Sitemap indexable URL hygiene", "Sitemap coverage gap", "Sitemap lastmod accuracy",
    "Image/video/news sitemaps", "Bing Webmaster verification", "IndexNow test", "Canonical presence and format",
    "Canonical target status", "Self-canonical consistency", "Canonical conflicts", "Duplicate titles and bodies",
    "Filter URL index strategy", "Filter combination growth", "Pagination links", "Infinite scroll discovery",
    "Tracking parameters", "Trailing slash / case / encoding", "Product variant canonical", "Main menu targets",
    "Breadcrumb accuracy", "Breadcrumb structured data match", "Acting on orphan pages", "Broken internal links",
    "Anchor text variety and intent", "Link flow to commercial pages", "Topic clusters and hubs",
    "Clickable image/card links", "Link count and useful navigation", "Internal links to non-canonical URLs",
    "Unique titles", "Title length and truncation", "Missing or duplicate meta descriptions",
    "H1 visibility and match", "H2-H3 content structure", "Clear URL slugs", "Keyword-page mapping",
    "Cannibalization evidence", "SERP feature opportunities", "CTR opportunities", "Open Graph and social preview",
    "Search intent match", "Content inventory and performance", "Thin content", "Repeated content and AI patterns",
    "Factual accuracy and claims", "Author and expertise", "Original value and comparison", "Freshness and dates",
    "FAQ usefulness and originality", "Topic coverage / topical gap", "Old content, conversions and link value",
    "Localized language and terms", "Category-keyword match", "Collection content and context",
    "Product title accuracy", "Product description originality", "Product image ALT", "Product variant indexing",
    "Out-of-stock product policy", "Product filter usability", "Product-category internal links",
    "Product price and stock consistency", "Merchant Center data source", "Merchant diagnostics and rejections",
    "Product identifiers", "Shipping/returns and trust", "Indexed empty collections", "Schema inventory",
    "Schema errors and warnings", "Organization/LocalBusiness truth", "BreadcrumbList", "Product and Offer",
    "Product variant markup", "Article / BlogPosting", "Service, Course, Event and the right type",
    "FAQPage visibility", "Duplicate JSON-LD", "Field data kept apart", "LCP p75", "INP p75", "CLS p75",
    "Template and device segments", "LCP hero image weight", "Image size and modern formats",
    "Render-blocking CSS/JS", "Third-party script budget", "Cache/CDN/compression", "Fonts and layout shift",
    "Mobile-first content parity", "Mobile menu and subcategories", "Form and checkout critical path",
    "Mobile readability", "Pop-ups/interstitials", "Core interaction QA", "Basic accessibility",
    "CTA and content match", "Source versus rendered HTML", "Googlebot rendered view", "HTTP status on CSR routes",
    "Canonical/head hydration consistency", "href format of key links", "Lazy content triggering",
    "Hydration and API errors", "Dynamic metadata per page type", "Hidden paywall / auth", "Image ALT quality",
    "ALT in the real HTML", "Image discovery and access", "Image file names and context", "Video discoverability",
    "PDFs and downloads", "hreflang syntax", "hreflang and canonical", "Language/country URL strategy",
    "Translation quality and currency", "Google Business Profile accuracy", "NAP consistency",
    "Branch / city landing pages", "Reviews and replies", "Crawl scope and start URLs",
    "Render mode and sample check", "Speed, limits and bot traps", "Crawl completion and coverage",
    "Backlink and referring domain inventory", "Health of valuable backlink targets",
    "External link quality and risk", "Manual actions report", "Security issues and hacking signs",
    "GA4 and GTM duplicate / missing tracking", "Conversion and commercial data match",
    "Cross-domain and payment return attribution", "Re-test per finding",
    "Closing findings and tracking performance",
]


def split_ids(text: str) -> tuple[list[str], list[str]]:
    checks = sorted(set(re.findall(r"\b(?:ACC|IDX|RND|STR|TSEO|PRF|INT|ANS)-\d+\b", text or "")),
                    key=lambda c: (c.split("-")[0], int(c.split("-")[1])))
    rules = sorted({r.rstrip("*").rstrip(".") for r in re.findall(r"\b[a-z0-9]+\.[a-z0-9_.*]+", text or "")
                    if not r.startswith(("final.", "page_grouping"))})
    return checks, rules


def sources(text: str) -> list[str]:
    return [key for word, key in SOURCE_WORDS if word in (text or "")]


def build() -> list[dict]:
    from maya_audit import xlsx
    rows = xlsx.read(SOURCE)["Mapping"]
    head = rows[0]
    col = {name: i for i, name in enumerate(head)}
    items = []
    for r in rows[1:]:
        if not r or not str(r[0]).startswith("SEO-"):
            continue
        get = lambda name: (r[col[name]] if col[name] < len(r) else "") or ""  # noqa: E731
        iid = get("ID")
        method = METHOD[get("Maya status")]
        checks, rules = split_ids(get("Maya rule IDs"))
        # INT-1..4 are the crawl's own records, not checks of a report: the render checks stand for INT-3
        checks = sorted({c for c in checks if not c.startswith("INT-")} | ({"RND-1", "RND-2"} if "INT-3" in checks else set()),
                        key=lambda c: (c.split("-")[0], int(c.split("-")[1])))
        needs = NEEDS.get(iid) or (sources(get("Free connection needed")) if method == "data" else [])
        if method == "manual":
            needs = ["manual"]
        rest = None
        if method == "partial":
            rest = REST[iid] if iid in REST else "review"
        number = int(get("İş grubu").split(" ")[0])
        items.append({"id": iid, "group": get("İş grubu"), "item": get("Kontrol maddesi"), "priority": get("Öncelik"),
                      "group_en": f"{number:02d} · {GROUP_EN[number - 1]}", "item_en": ITEM_EN[int(iid[4:]) - 1],
                      "applies_to": get("Uygulanabilirlik"), "method": method, "checks": checks,
                      "rules": RULES.get(iid, rules if method in ("full", "partial") else []),
                      "needs": needs, "rest": rest, "when": WHEN.get(get("Uygulanabilirlik")),
                      "maya_note": get("Covered / what is missing")})
    return items


if __name__ == "__main__":
    data = build()
    assert len(data) == 165 and len({i["id"] for i in data}) == 165
    OUT.write_text(json.dumps({"source": "reviews/checklist/mapping.xlsx (SEO_Audit_Checklist.xlsx, 2026-11-03)",
                               "decisions": 342, "items": data}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(data)} items)")
