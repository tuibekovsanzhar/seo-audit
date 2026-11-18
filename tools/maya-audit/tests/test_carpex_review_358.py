"""DECISIONS 358: the review of the carpexonline.com audit as global rules. (1) a crawl follows the site to its twin
address when the site's own pages redirect there, reads that address's sitemap and says why it read fewer pages than
its limit; (2) product pages are typed from what they show; (3) the audited brand is never its own rival in the Maya
sheets; (4) Maya's non-topic labels are not topics; (5) the "also download pages" choice works when files are added
and later. Fake sites (mock transports) and fake exports only; nothing is requested."""
from __future__ import annotations

import json

import httpx

from maya_audit import sampling
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.models import to_jsonable
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET
from test_firecrawl import no_lookups  # noqa: F401

HTML = {"content-type": "text/html; charset=utf-8"}
BARE, WWW = "https://shop.test", "https://www.shop.test"
TEXT = "<p>" + "Kokular, makineler ve kartuşlar için güvenilir alışveriş, hızlı kargo ve iade. " * 10 + "</p>"
PRODUCTS = [f"/koku-makinesi-model-{i}-{100 + i}" for i in range(12)]
CATEGORIES = ["/makineler", "/kartuslar"]


def _product(path: str) -> str:
    name = path.strip("/").replace("-", " ").title()
    ld = json.dumps({"@context": "https://schema.org", "@type": "Product", "name": name,
                     "offers": {"@type": "Offer", "price": "670.00", "priceCurrency": "TRY"}})
    return (f'<!doctype html><html lang="tr"><head><title>{name}</title><meta property="og:type" content="product">'
            f'<script type="application/ld+json">{ld}</script></head><body><main><h1>{name}</h1>{TEXT}'
            '<p class="price">670,00 TL</p><input type="submit" value="Sepete Ekle"></main></body></html>')


def _category(path: str, host: str) -> str:
    items = [{"@type": "ListItem", "position": i + 1, "item": {"@type": "Product", "name": p, "url": host + p,
              "offers": {"@type": "Offer", "price": "670.00", "priceCurrency": "TRY"}}} for i, p in enumerate(PRODUCTS)]
    ld = json.dumps({"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items})
    links = "".join(f'<li><a href="{host}{p}">{p}</a></li>' for p in PRODUCTS)
    return (f'<!doctype html><html lang="tr"><head><title>{path}</title><meta property="og:type" content="product.group">'
            f'<script type="application/ld+json">{ld}</script></head><body><main><h1>{path}</h1>{TEXT}<ul>{links}</ul>'
            "</main></body></html>")


def shop(sitemap_on_www: bool = True):
    """The bare host answers its homepage itself and sends every other page to www (carpexonline.com's shape); links
    keep the bare address. robots.txt names the sitemap on www only."""
    sitemap = (f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + "".join(f"<url><loc>{WWW}{p}</loc></url>" for p in CATEGORIES + PRODUCTS) + "</urlset>")

    def respond(request):
        host, path = request.url.host, request.url.path
        if path == "/robots.txt":
            named = f"Sitemap: {WWW}/sitemap.xml\n" if sitemap_on_www else ""
            return httpx.Response(200, text=f"User-agent: *\nAllow: /\n{named}")
        if path == "/sitemap.xml":
            if host == "www.shop.test":
                return httpx.Response(200, headers={"content-type": "application/xml"}, text=sitemap)
            return httpx.Response(404, headers=HTML, text="<h1>yok</h1>")
        if host == "shop.test" and path != "/":
            return httpx.Response(301, headers={"location": WWW + path})
        if path == "/":
            nav = "".join(f'<a href="{BARE}{c}">{c}</a>' for c in CATEGORIES)
            return httpx.Response(200, headers=HTML, text=f'<!doctype html><html lang="tr"><head><title>Shop</title>'
                                  f'<meta property="og:type" content="website">'
                                  f'<script src="https://static.ticimax.cloud/js/app.js"></script></head><body><nav>{nav}</nav><main>'
                                  f'<h1>Shop</h1>{TEXT}<a href="{BARE}/hakkimizda">Hakkımızda</a></main></body></html>')
        if path in CATEGORIES:
            return httpx.Response(200, headers=HTML, text=_category(path, BARE))
        if path in PRODUCTS:
            return httpx.Response(200, headers=HTML, text=_product(path))
        if path == "/hakkimizda":
            return httpx.Response(200, headers=HTML, text=f"<!doctype html><html><head><title>Hakkımızda</title></head>"
                                  f"<body><main><h1>Hakkımızda</h1>{TEXT}</main></body></html>")
        return httpx.Response(404, headers=HTML, text="<h1>yok</h1>")
    return respond


def crawl_shop(max_pages=30, sitemap_on_www=True, **kw):
    config = CrawlConfig(**{**QUIET, "max_pages": max_pages, "sitemap_check_max": 0, "business_type": "auto", "sampling": True, **kw})
    outcome = run_audit(BARE + "/", config, httpx.MockTransport(shop(sitemap_on_www)))
    return outcome, json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))


# ---------------------------------------------------------------- 1: the twin address

def test_the_crawl_follows_the_sites_own_redirects_to_its_twin_address_and_reads_its_sitemap(no_lookups):  # noqa: F811
    outcome, r = crawl_shop()
    crawl = r["crawl"]
    read = [p["url"] for p in crawl["pages"] if p["status"] == 200]
    assert crawl["origin"] == WWW and crawl["host_moves"][0]["from"] == BARE and crawl["host_moves"][0]["to"] == WWW
    assert crawl["host_moves"][0]["sitemap_named"] is True
    assert set(WWW + p for p in PRODUCTS) <= set(read)  # the redirect targets and the sitemap's pages were read
    assert any(d["url"] == WWW + "/sitemap.xml" and d["kind"] == "urlset" for d in crawl["sitemap_docs"])
    assert BARE + "/" in read  # the start page answered itself and stays the homepage


def test_kapsam_says_why_a_crawl_ended_below_its_limit():
    report = {"crawl": {"config": {"max_pages": 150}, "stop_reason": "exhausted", "origin": "https://shop.test",
                        "pages": [{"url": "https://shop.test/", "status": 200, "fetch_class": "ok", "content_type": "text/html"}]
                        + [{"url": f"https://shop.test/p{i}", "status": 301, "fetch_class": "ok"} for i in range(5)],
                        "redirects": [{"url": f"https://shop.test/p{i}", "final": f"https://www.shop.test/p{i}"} for i in range(5)],
                        "sitemap_notes": ["robots.txt names 1 sitemap file(s) on another address, which were not read: "
                                          "https://www.shop.test/sitemap.xml."],
                        "host_moves": [], "not_fetched_urls": []}}
    kinds = dict(sampling.fewer_reasons(report))
    assert kinds["off_site_redirects"]["n"] == 5 and kinds["off_site_redirects"]["host"] == "www.shop.test"
    assert kinds["sitemap_elsewhere"]["url"] == "https://www.shop.test/sitemap.xml"
    assert "plan_done" not in kinds
    text = sampling.below_limit_line(report, "tr")
    assert "150" in text and "www.shop.test" in text and "site haritası" in text
    moved = {"crawl": {**report["crawl"], "redirects": [], "sitemap_notes": [],
                       "host_moves": [{"from": "https://shop.test", "to": "https://www.shop.test", "redirects": 3,
                                       "after_pages": 2, "sitemap_named": True}]}}
    assert "www.shop.test" in sampling.below_limit_line(moved, "tr") and "geçti" in sampling.below_limit_line(moved, "tr")
    assert sampling.below_limit_line({"crawl": {**report["crawl"], "stop_reason": "page_cap"}}, "tr") is None


def test_a_single_odd_redirect_to_www_does_not_move_the_crawl(no_lookups):  # noqa: F811
    """Without the sitemap named on www, the move waits for three of the site's own pages to redirect there."""
    outcome, r = crawl_shop(sitemap_on_www=False)
    moves = r["crawl"]["host_moves"]
    assert moves and moves[0]["redirects"] == 3 and moves[0]["sitemap_named"] is False
    from maya_audit.urls import is_allowed_origin_move
    assert not is_allowed_origin_move("https://www.shop.test/a", "http://shop.test/a")  # never down to http


# ---------------------------------------------------------------- 2: product pages from what they show

def test_product_pages_are_typed_from_what_they_show_when_markup_is_on_every_page(no_lookups):  # noqa: F811
    outcome, r = crawl_shop()
    by_url = {p["url"]: p.get("grouping") or {} for p in r["crawl"]["pages"] if p["status"] == 200}
    products = [by_url[WWW + p] for p in PRODUCTS if WWW + p in by_url]
    assert products and all(g["page_type"] == "product" for g in products), [g.get("page_type_basis") for g in products]
    assert all(g["business_page_type"] == "product" for g in products)
    assert r["crawl"]["business_type"]["id"] == "eticaret"
    # the Akıllı plan was made for the platform's profile from the first page (Ticimax -> E-ticaret), not "Diğer"
    assert r["crawl"]["sampling"]["profile"] == "eticaret"


def test_own_product_markup_or_a_buy_button_makes_a_product_page():
    from types import SimpleNamespace
    from maya_audit import page_groups
    from maya_audit.analysis import analyze_html
    page = SimpleNamespace(url="https://shop.test/leke-cikarici-sprey-500-ml", outlinks=[],
                           analysis=analyze_html(_product("/leke-cikarici-sprey-500-ml")))
    assert "Product markup" in page_groups.own_item(page)
    listing = SimpleNamespace(url="https://shop.test/makineler", outlinks=[], analysis=analyze_html(_category("/makineler", BARE)))
    assert page_groups.own_item(listing) is None  # Product markup inside a list is the list's, not the page's
    bare = _product("/x").replace('<script type="application/ld+json">', '<script type="text/plain">')
    button = SimpleNamespace(url="https://shop.test/x", outlinks=[], analysis=analyze_html(bare))
    assert "buy control" in page_groups.own_item(button)  # og:type=product with "Sepete Ekle"


def test_addresses_are_typed_as_products_before_reading_by_their_id_or_sitemap_file():
    from maya_audit import business_types as bt
    shop_ = bt.profile("eticaret")
    assert sampling.pre_type(shop_, "https://x.test/micro-koku-makinesi-siyah-50ml-ginger-flowers-550")[0] == "product"
    assert sampling.pre_type(shop_, "https://x.test/kokular-55")[0] != "product"  # a category with an id: one word
    assert sampling.pre_type(shop_, "https://x.test/yaz-kampanya-firsatlari-2024")[0] != "product"  # a year
    assert sampling.pre_type(shop_, "https://x.test/big-boss-50ml-383", nav=True)[0] != "product"  # in the main menu
    assert sampling.pre_type(shop_, "https://x.test/leke-cikarici-sprey-500-ml",
                             sitemap_file="https://x.test/sitemap/products/0.xml")[0] == "product"
    assert sampling.pre_type(shop_, "https://x.test/oto-bakim", sitemap_file="https://x.test/sitemap/categories/0.xml")[0] == "category"
    assert sampling.pre_type(bt.profile("saas"), "https://x.test/big-boss-50ml-383")[0] != "features"  # not one item
    s = sampling.Sampler("eticaret")
    s.add(["https://x.test/makineler", "https://x.test/arac-koku-seti-mavi-77"])
    s.types["https://x.test/arac-koku-seti-mavi-77"] = ("other", "made up")
    s.retype({"https://x.test/makineler": {"structured_data": {"types": ["ItemList"]}}},
             {"https://x.test/makineler": ["https://x.test/arac-koku-seti-mavi-77"]})
    assert s.types["https://x.test/arac-koku-seti-mavi-77"][0] == "product"


# ---------------------------------------------------------------- 3 and 4: the brand itself, topics

from test_maya_data_352 import csv_text, report as maya_report, sheet, texts, write  # noqa: E402

LABELS = {"l-topic": "Kartlar", "l-intent": "intent:discovery", "l-cluster": "cluster:kart-maliyet", "l-multi": "brand:multi",
          "l-word": "multiple"}


def maya_exports(folder):
    from maya_audit import maya_data
    data = {"project": [{"id": "x", "name": "Shop", "domain": "shop.test", "websiteUrl": "https://shop.test",
                         "brand_tags": ["Shop"], "additional_domains": [],
                         "brand_facts": {"competitors": [{"name": "IdeaSoft", "domain": ""}, {"name": "shop", "domain": ""},
                                                         {"name": "Shop Kart Pro", "domain": ""}]}}],
            "competitor_aliases": [], "radar_brands": [{"competitor_name": "shop", "competitor_domain": None}],
            "prompt_labels": [{"id": k, "name": v, "color": "#000"} for k, v in LABELS.items()]}
    write(folder, "shop.test-meta.json", json.dumps(data))

    def labels(*ids):
        return json.dumps(list(ids)).replace('"', '""')
    rows = [f'p-a,discovery,"kart aidatı",tr-TR,TR,tr,discovery,"{labels("l-intent", "l-topic")}",1',
            f'p-b,discovery,"kart maliyeti",tr-TR,TR,tr,discovery,"{labels("l-intent", "l-cluster")}",1',
            f'p-c,discovery,"genel soru",tr-TR,TR,tr,discovery,"{labels("l-intent", "l-multi")}",1',
            f'p-d,discovery,"başka soru",tr-TR,TR,tr,discovery,"{labels("l-word")}",1']
    write(folder, "shop.test-prompts.csv", csv_text("id,type,text,locale,targetMarket,targetLanguage,intent,labels,is_active", rows))
    cites = []
    for i, (pid, url, domain) in enumerate([("p-a", "shop.com.tr/kart", "shop.com.tr"), ("p-a", "ideasoft.com.tr/kart", "ideasoft.com.tr"),
                                            ("p-a", "www.shop.test/kartlar", "shop.test"), ("p-b", "www.shop.test/", "shop.test"),
                                            ("p-c", "rehber.test/en-iyi-10", "rehber.test"), ("p-d", "www.shop.test/", "shop.test")]):
        cites.append(f"c{i},chatgpt,{pid},r{i},,,true,false,0.75,,2026-09-10 10:00:00,{url},{domain},0.5")
    write(folder, "shop.test-citation-mentions-2026-09-01-2026-10-31.csv",
          csv_text("id,model,prompt_id,run_id,kind,source_type,is_direct,is_indirect,confidence,title,created_at,url,domain,authority_score", cites))
    write(folder, "shop.test-competitor-mentions-daily-2026-09-01-2026-10-31.csv",
          csv_text("date,competitorKey,displayName,domain,mentions,sentimentWeightSum,sentimentWeightedScoreSum",
                   ["2026-09-10 00:00:00,shopkartpro,Shop Kart Pro,,9,1,1", "2026-09-10 00:00:00,ideasoft,IdeaSoft,,30,1,1"]))
    write(folder, "shop.test-topic-visibility-snapshots-2026-09-01-2026-10-31.csv",
          csv_text("week_start,topic,total,brand_rate,top_competitor_name,top_competitor_rate",
                   ["2026-10-19,Kartlar,100,60.0,shop,60.0", "2026-10-26,Kartlar,100,62.0,shop,62.0"]))
    return maya_data.prepare([folder], "https://www.shop.test/")


def test_the_audited_brand_is_never_its_own_rival(tmp_path):
    from maya_audit import maya_sheets
    s = maya_exports(tmp_path)
    assert [c["name"] for c in s["competitors"]] == ["IdeaSoft"]  # "shop" and its product left the rivals
    assert s["own"]["names"] == ["shop", "Shop Kart Pro"] and s["own"]["products"] == [] and s["own"]["domains"] == ["shop.com.tr"]
    assert "shop.com.tr" in s["brand_domains"]
    keys = maya_sheets.competitor_keys(s)
    assert set(keys) == {"ideasoft"}
    assert maya_sheets.domain_kind("shop.com.tr", s, keys, set(), "https://shop.com.tr/kart") == "brand"
    kart = next(t for t in s["visibility"]["topics"] if t["topic"] == "Kartlar")
    assert kart["leader"] is None and kart["leader_own"] == "shop" and kart["gap"] is None
    assert "markanın kendisi" in maya_sheets._vis_words(kart, "leader")
    built = maya_sheets.build(s, maya_report())
    assert any(line.startswith("Markanın kendisi") and "«shop»" in line for line in built["coverage"])
    assert any(line.startswith("Markanın kendi siteleri: shop.com.tr") for line in built["coverage"])
    rows = texts(sheet(built, maya_sheets.SHEETS["topics"])["rows"])
    assert not any("shop" == (r[7] or "").split(" ")[0] for r in rows)  # no "Lider rakip: shop"


def test_only_real_topics_are_topics_and_the_other_labels_come_last(tmp_path):
    from maya_audit import maya_data, maya_sheets
    assert maya_data.topic_of("intent:comparison") is None and maya_data.topic_of("multiple") is None
    assert maya_data.topic_of("cluster:makine-kurulum") == "makine-kurulum" and maya_data.topic_of("Koku Makineleri") == "Koku Makineleri"
    s = maya_exports(tmp_path)
    topics = maya_sheets.topic_rows(s)
    names = [t["topic"] for t in topics]
    assert names[-1] == maya_data.OFF_TOPIC and set(names[:-1]) == {"Kartlar", "kart-maliyet"}
    assert topics[-1]["n"] == 2 and topics[-1]["labels"] == ["brand:multi", "intent:discovery", "multiple"]
    built = maya_sheets.build(s, maya_report())
    rows = texts(sheet(built, maya_sheets.SHEETS["topics"])["rows"])
    assert rows[-1][1].startswith("Konu dışı etiketler (") and not any(r[1].startswith("intent:") for r in rows)
    structure = texts(sheet(built, maya_sheets.SHEETS["structure"])["rows"])
    assert not any(r[0] == maya_data.OFF_TOPIC for r in structure)  # not a topic: nothing compared for it


def test_a_summary_saved_before_is_made_again_with_the_brand_and_topic_rules(tmp_path):
    from maya_audit import maya_data
    folder = tmp_path / "artifacts"
    files = folder / maya_data.FOLDER
    files.mkdir(parents=True)
    s = maya_exports(files)
    maya_data.save({**s, "version": 2, "fetched": {"https://x.test/a": {"title": "A"}}}, folder)
    again = maya_data.load_for(folder)
    assert again["version"] == maya_data.VERSION and again["own"]["names"] == ["shop", "Shop Kart Pro"]
    assert again["fetched"] == {"https://x.test/a": {"title": "A"}} and again["fetch"] == {"wanted": True}


# ---------------------------------------------------------------- 5: "also download pages"

def test_enrich_says_what_each_downloaded_page_is_for(tmp_path):
    from maya_audit import maya_sheets
    s = maya_exports(tmp_path)
    asked = []

    def fetch(url):
        asked.append(url)
        if "ideasoft" in url:
            raise OSError("refused")
        return f"<html><head><title>{url}</title></head><body><h1>Başlık</h1><p>Metin</p></body></html>"
    maya_sheets.enrich(s, maya_report(), fetch)
    got = maya_sheets.fetched_counts(s)
    assert asked and got["failed"] == 1 and got["pages"] == len(asked) - 1
    assert got["detail"] + got["competitor"] == got["pages"]
    assert s["fetched"]["https://ideasoft.com.tr/kart"]["for"] == "competitor"
    built = maya_sheets.build({**s, "fetch": {"wanted": True}}, maya_report())
    assert any(line.startswith("Rakip sayfaları:") and "alınamayan 1" in line for line in built["coverage"])


def test_the_download_choice_is_read_whenever_the_files_are_read_and_kept(web, monkeypatch):  # noqa: F811
    from maya_audit import maya_data, maya_sheets
    from test_web_app import API, audit_of
    client = web()
    audit = audit_of(client)
    base = f"{API}/audits/{audit['id']}/maya-data"
    session = client.get(f"{API}/session")
    token = session.json().get("token") if session.status_code == 200 else None
    headers = {"Content-Type": "application/octet-stream", **({"X-Maya-Token": token} if token else {})}
    body = "date,clicks,impressions,ctr,position\n2026-09-01,10,100,0.1,3\n"
    r = client.put(f"{base}/files/{audit['host']}-gsc-daily-stats.csv", content=body.encode(), headers=headers)
    if r.status_code in (401, 403):
        import pytest
        pytest.skip("this test client does not hold the action token")
    calls = []

    def fake_enrich(summary, report, fetch, evidence=None):
        calls.append(len(summary.get("fetched") or {}))
        summary.setdefault("fetched", {})[f"https://{audit['host']}/p{len(calls)}"] = {"title": "x", "for": "detail"}
        return summary
    monkeypatch.setattr(maya_sheets, "enrich", fake_enrich)
    monkeypatch.setattr(maya_data, "polite_fetcher", lambda *a, **k: (lambda url: None))
    first = client.post(base, json={"fetch": False}).json()  # files added without the choice
    assert first["attached"] and first["fetch"] is False and calls == []
    later = client.post(base, json={"fetch": True}).json()  # ticked later: the files already there are read again
    assert later["fetch"] is True and later["fetched"]["pages"] == 1 and later["fetched"]["detail"] == 1 and calls == [0]
    again = client.post(base, json={"fetch": True}).json()  # read again: earlier pages kept, only new ones asked
    assert again["fetched"]["pages"] == 2 and calls == [0, 1]
    off = client.post(base, json={"fetch": False}).json()
    assert off["fetch"] is False and off["fetched"]["pages"] == 2 and client.get(base).json()["fetched"]["pages"] == 2


from test_web_app import web  # noqa: E402,F401  (fixture)
