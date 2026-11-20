"""DECISIONS 365: İlginay's two questions. (1) Every checklist item says how it is checked (Otomatik / Veri gerekir /
Uzman incelemesi), with the data it needs or why an expert, and how it could become automatic; the items Maya's Search
Console export measures are measured when it is attached. (2) The platform is recognised from more signals, with a
confidence, shown in Kapsam and Özet, and platform advice is shown only on that platform. Fake data only."""
from __future__ import annotations

from types import SimpleNamespace

from maya_audit import checklist, checklist_maya, client_appendix
from maya_audit.site_platform import recognise

from test_checklist_342 import selection

SITE = "https://www.shop.test/"


def item(iid: str) -> dict:
    return next(i for i in checklist.items() if i["id"] == iid)


# ---------------------------------------------------------------- (1) how each item is checked

def test_every_item_has_one_way_of_checking_and_every_expert_item_says_why():
    hows = {i["id"]: checklist.how(i) for i in checklist.items()}
    counts = {k: sum(h["kind"] == k for h in hows.values()) for k in ("auto", "data", "expert")}
    assert counts == {"auto": 55, "data": 37, "expert": 73} and sum(counts.values()) == 165
    assert all(h["why"] and h["automate"] and h["effort"] in ("S", "M", "L", "—") for h in hows.values() if h["kind"] == "expert")
    assert hows["SEO-022"]["sources"] == ["gsc"] and not hows["SEO-022"]["maya"]  # the coverage report: not in Maya's export
    assert hows["SEO-071"]["maya"] and hows["SEO-123"]["effort"] == "—"
    assert hows["SEO-064"]["kind"] == "auto" and "str10.no_description" in item("SEO-064")["rules"]  # the rule existed


def test_the_sheet_has_the_columns_and_the_counts_on_its_first_rows():
    listed, totals = checklist.sheets(selection(), "tr")
    assert listed["header"][-3:] == ["Nasıl kontrol edilir", "Gereken veri / neden uzman", "Otomatikleştirme önerisi"]
    assert listed["title_rows"] == 3
    top = [r[1] for r in listed["rows"][:3]]
    assert top[0] == "Otomatik: 55 madde (tarama ölçer)"
    assert top[1].startswith("Veri gerekir: 37 madde (12 tanesi Maya'nın Search Console verisi eklenince ölçülür; bu denetimde ölçülen: 0)")  # +SEO-069 (376)
    assert top[2].startswith("Uzman incelemesi: 73 madde (64 tanesi otomatikleştirilebilir")
    rows = {r[0]: r for r in listed["rows"][3:]}
    assert len(rows) == 165
    assert rows["SEO-027"][8:] == ["Uzman incelemesi", "Bu madde için kural henüz yok.",
                                   "küçük: Site içi arama adresinin 200, noindex'siz, kendine kanonik ve robots.txt'nin izin verdiği durumu (ACC-3 verisi hazır)."]
    assert rows["SEO-071"][9] == "Search Console; Maya'nın Search Console verisi eklenince ölçülür"
    assert rows["SEO-022"][9] == "Search Console; Maya'nın Search Console verisi bu raporu içermez"
    assert totals["header"][-3:] == ["Otomatik", "Veri gerekir", "Uzman incelemesi"]
    assert totals["rows"][0][-3:] == [55, 37, 73]
    assert all(sum(r[-3:]) == r[1] for r in totals["rows"])


def summary(capped=False):
    pages = {SITE: {"clicks": 500, "impressions": 9000, "position": 2.0, "ctr": 0.055},
             SITE + "shop": {"clicks": 40, "impressions": 2000, "position": 4.0, "ctr": 0.02},
             SITE + "product/a": {"clicks": 90, "impressions": 1500, "position": 4.0, "ctr": 0.06},
             SITE + "product/b": {"clicks": 80, "impressions": 1400, "position": 4.0, "ctr": 0.057},
             SITE + "product/c": {"clicks": 70, "impressions": 1300, "position": 4.0, "ctr": 0.054},
             "https://backoffice-uat.shop.test/login": {"clicks": 0, "impressions": 120, "position": 9.0, "ctr": 0.0}}
    return {"gsc": {"pages": pages, "page_period": ["2026-10-19", "2026-11-18"],
                    "monthly": [{"month": "2026-10", "clicks": 400, "impressions": 8000, "position": 3.0},
                                {"month": "2026-11", "clicks": 380, "impressions": 7300, "position": 3.2}],
                    "weeks": [{"clicks": 200}, {"clicks": 190}, {"clicks": 180}, {"clicks": 210}],
                    "brand": {"brand": {"clicks": 100}, "non_brand": {"clicks": 680}}}}


def shop_selection(capped=False):
    sel = selection(site={"start": SITE, "stop": "page_cap" if capped else "done"})
    sel["_checklist_facts"]["known"] = [checklist_maya.key(SITE + p) for p in ("", "product/a", "product/b", "product/c")]
    sel["_importance"] = {SITE + "product/a": {"page_type": "product", "inlinks": 1},
                          SITE + "product/b": {"page_type": "product", "inlinks": 9},
                          SITE + "product/c": {"page_type": "product", "inlinks": 9}}
    sel["_pages_read"] = {SITE, SITE + "product/a", SITE + "product/b", SITE + "product/c", SITE + "about"}
    return sel


def test_the_items_maya_search_console_data_measures_are_measured_when_it_is_attached():
    s, sel = summary(), shop_selection()
    assert checklist_maya.row("SEO-022", s, sel) is None and checklist_maya.row("SEO-071", {}, sel) is None
    result, text, _ = checklist_maya.row("SEO-007", s, sel)
    assert result == "issue" and "backoffice-uat.shop.test" in text  # a test host gets impressions
    result, text, _ = checklist_maya.row("SEO-005", s, sel)
    assert result == "pass" and "Search Console 5 sayfa; 1 tanesi taramada ve site haritasında yok (ör. https://www.shop.test/shop)" in text
    assert checklist_maya.row("SEO-025", s, sel)[0] == "issue"
    assert checklist_maya.row("SEO-025", s, shop_selection(capped=True))[0] == "review"  # a capped crawl: not proven
    assert checklist_maya.row("SEO-057", s, sel)[0] == "issue"  # product/a: clicks, one link
    assert checklist_maya.row("SEO-071", s, sel)[0] == "issue"  # /shop: CTR under half of the position-4 pages
    result, text, _ = checklist_maya.row("SEO-028", s, sel)
    assert result == "review" and "Okunan 5 sayfanın 4 tanesi" in text and "about" in text
    assert checklist_maya.row("SEO-004", s, sel)[0] == "missing_data"  # 31 days: no seasonality
    pages_only = {"gsc": {"pages": s["gsc"]["pages"]}}  # a page-scores export: no daily file
    assert checklist_maya.row("SEO-008", pages_only, sel) is None and checklist_maya.row("SEO-071", pages_only, sel)
    assert "+%5" in checklist_maya.row("SEO-165", s, sel)[1]
    listed, _ = checklist.sheets(sel, "tr", maya=s)
    rows = {r[0]: r for r in listed["rows"][3:]}
    # DECISIONS 376: "Sonuç" keeps the tool's result; Maya's measure is the proposal beside it
    assert listed["header"][-2:] == ["Search Console eki: önerilen sonuç", "Search Console kanıtı"]
    assert rows["SEO-007"][4] == "Veri eksik" and rows["SEO-007"][11] == "Sorun" and "backoffice-uat" in rows["SEO-007"][12]
    assert rows["SEO-007"][9].endswith("bu denetimde Maya verisiyle ölçüldü")
    assert rows["SEO-008"][7] == "Search Console, GA4" and rows["SEO-008"][11]  # the tool row; Maya proposes beside it
    assert rows["SEO-074"][4] == "Uygulanmaz"  # content inventory: the site has no article page
    assert "bu denetimde ölçülen: 10" in listed["rows"][1][1]


# ---------------------------------------------------------------- (2) the platform

def page(url="https://s.test/", scripts=(), images=(), generator=None, footer="", headers=None):
    meta = [{"name": "generator", "content": generator}] if generator else []
    return SimpleNamespace(url=url, headers=headers or {}, outlinks=[], analysis={
        "external_scripts": [{"src": s} for s in scripts], "images": [{"src": i} for i in images], "meta": meta,
        "footer_text": footer})


def test_more_platforms_are_recognised_from_what_the_pages_show():
    def name(*pages):
        found = recognise(SimpleNamespace(pages=list(pages)))
        return found and (found["name"], found.get("confidence"))
    two = lambda **kw: [page(f"https://s.test/{i}", **kw) for i in range(2)]  # noqa: E731
    assert name(*two(images=["/wp-content/uploads/2026/01/a.jpg"])) == ("WordPress", "high")
    assert name(*two(images=["https://s.test/cdn/shop/files/a.jpg"])) == ("Shopify", "high")
    assert name(*two(images=["https://cdn.myikas.com/images/a.jpg"])) == ("ikas", "high")
    assert name(*two(images=["https://static.wixstatic.com/media/a.jpg"])) == ("Wix", "high")
    assert name(*two(images=["/_next/image?url=%2Fa.jpg&w=640&q=75"])) == ("Next.js", "high")
    assert name(*two(footer="© 2026 Mağaza. IdeaSoft® | Akıllı E-Ticaret paketleri ile hazırlanmıştır.")) == ("IdeaSoft", "high")
    assert name(*two(footer="T-Soft E-Ticaret Sistemleriyle Hazırlanmıştır")) == ("T-Soft", "high")
    assert name(*two(headers={"X-Powered-By": "Ticimax"})) == ("Ticimax", "high")
    assert name(page(generator="Sitefinity 15.4"), *[page(f"https://s.test/{i}") for i in range(5)]) == ("Sitefinity", "medium")
    assert name(page(images=["/wp-content/uploads/a.jpg"]), *[page(f"https://s.test/{i}") for i in range(5)]) == ("WordPress", "low")
    # a platform named in a text, not a credit, is no signal; a word in a script address is not looked for
    assert name(*two(footer="Shopify mı WooCommerce mu? Blogumuzda karşılaştırdık.")) is None
    assert name(*two(scripts=["https://cdn.test/nextsoft-tsoft-widget.js"])) is None


def test_a_saved_audit_gets_the_platform_again_with_its_confidence():
    from maya_audit import reassess_rules
    from test_file_names_364 import PAGE
    rec = lambda i: {**PAGE, "url": f"https://s.test/{i}", "headers": {"x-powered-by": "Ticimax"},  # noqa: E731
                     "analysis": {"external_scripts": [], "meta": [], "images": []}}
    report = {"platform": {"name": None, "cdn": "Cloudflare", "signals": ["Cloudflare: response header cf-ray on x"]},
              "crawl": {"pages": [rec(i) for i in range(3)]}}
    changes: list[str] = []
    reassess_rules._decisions_365(report, changes)
    assert report["platform"]["name"] == "Ticimax" and report["platform"]["confidence"] == "high"
    assert report["platform"]["cdn"] == "Cloudflare" and changes == ["platform: none -> Ticimax (high; DECISIONS 365)"]


def test_kapsam_and_ozet_show_the_platform_and_the_advice_for_it():
    from maya_audit.platform_text import advice_by_platform
    shopify = advice_by_platform()["Shopify"]
    assert "idx6.alias_links" in shopify and "str3.product_no_identifier" in shopify
    assert "idx1.error_text" in advice_by_platform()["WordPress"]
    info = {"name": "Shopify", "cdn": "Cloudflare", "confidence": "high", "pages_seen": 6, "pages_looked": 6,
            "signal": "Shopify: script https://cdn.shopify.com/x.js on https://s.test/"}
    line = client_appendix.platform_line({"platform_info": info}, "tr")
    assert line.startswith("Shopify (güven: yüksek; 6/6 sayfada): betik https://cdn.shopify.com/x.js. CDN: Cloudflare.")
    assert "idx6.alias_links" in line and line.endswith("diğer öneriler geneldir.")
    nextjs = client_appendix.platform_line({"platform_info": {**info, "name": "Next.js"}}, "tr")
    assert nextjs.endswith("Bu platforma özel öneri yok; öneriler geneldir.")
    assert client_appendix.platform_line({"platform_info": {"name": None}}, "tr").startswith("Platform tanınmadı; öneriler geneldir")
    assert client_appendix.platform_line({"platform_info": info}, "tr", short=True) == "Platform: Shopify (güven: yüksek)"
