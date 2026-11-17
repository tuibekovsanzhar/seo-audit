"""DECISIONS 356: the SaaS / Yazılım business profile (suggestion, page types, weights, sampling) and its own checks.
Made-up software and shop sites only; no request."""
from __future__ import annotations

import json
from types import SimpleNamespace

from maya_audit import business_types as bt
from maya_audit import sampling
from maya_audit.checks import profile_rules as pr

SITE = "https://soft.test"
BANNER = "Kasım fırsatı! Yıllık alımda 2 ay hediye + 5.000 TL kredi"


def nav(*paths_and_texts):
    return [{"target": SITE + p, "anchors": [t], "nav": True} for p, t in paths_and_texts]


SAAS_MENU = nav(("/fiyatlandirma", "Fiyatlandırma"), ("/ozellikler", "Özellikler"), ("/kampanya-araci", "Kampanya aracı"),
                ("/entegrasyonlar", "Entegrasyonlar"), ("/musterilerimiz", "Müşterilerimiz"), ("/demo", "Ücretsiz deneyin"))
SHOP_MENU = [{"target": "https://shop.test/kadin", "anchors": ["Kadın"], "nav": True},
             {"target": "https://shop.test/erkek", "anchors": ["Erkek"], "nav": True},
             {"target": "https://shop.test/indirim", "anchors": ["İndirim"], "nav": True},
             {"target": "https://shop.test/sepet", "anchors": ["Sepetim"], "nav": True}]


# ---------------------------------------------------------------- 1. the profile

def test_the_profile_is_saas_yazilim_with_its_page_types_and_weights():
    p = bt.profile("saas")
    assert p["label"]["tr"] == "SaaS / Yazılım" and "saas" in {c["id"] for c in bt.choices()}
    ids = [t["id"] for t in p["page_types"]]
    assert ids[:3] == ["pricing", "features", "comparison"]
    assert {"integrations", "demo", "solutions", "references", "guide", "blog", "sales", "policy", "home"} <= set(ids)
    weights = {t["id"]: t["weight"] for t in p["page_types"]}
    top = sorted(weights.values(), reverse=True)[:3]
    assert {weights["pricing"], weights["features"], weights["comparison"]} == set(top)
    assert weights["policy"] < weights["blog"] < weights["features"]


def test_a_software_homepage_suggests_saas_and_a_shop_does_not():
    home = {"structured_data": {"types": ["Organization"]}, "buttons": [{"text": "Demo talep edin"}]}
    urls = [SITE + p for p in ("/", "/fiyatlandirma", "/ozellikler", "/entegrasyonlar", "/demo", "/musterilerimiz")]
    found = bt.suggest(home, SAAS_MENU, None, urls,
                       home_external=[{"target": "https://apps.apple.com/app/soft/id1"}])
    assert found["id"] == "saas"
    kinds = {s["kind"] for s in found["signals"]}
    assert {"trial", "apps", "menu"} <= kinds and "demo" in found["reason"]["tr"]
    shop = bt.suggest({"structured_data": {"types": ["Organization"]}}, SHOP_MENU, None,
                      ["https://shop.test/urun/elbise-1", "https://shop.test/urun/elbise-2", "https://shop.test/kadin"],
                      types={"product": 8, "category": 4, "other": 2})
    assert shop["id"] != "saas"


def test_software_pages_are_typed_by_address_words_menu_and_content():
    prof = bt.profile("saas")

    def kind(url, analysis=None, menu=(), generic=None, in_nav=False):
        return bt.classify(prof, bt.page_facts(SITE + url, analysis, menu, generic, nav=in_nav))[0]
    assert kind("/e-ticaret-paketleri/") == "pricing"
    assert kind("/biz-vs-rakip") == "comparison" and kind("/karsilastirma/rakip") == "comparison"
    assert kind("/entegrasyon-cozumleri/") == "integrations"
    assert kind("/demo-talep") == "demo"
    assert kind("/sektorel-cozumler/perakende") == "solutions"
    assert kind("/basari-hikayeleri/acme") == "references"
    assert kind("/yardim/kurulum") == "guide"
    assert kind("/blog/yeni-ozellik", generic="blog_article") == "blog"
    assert kind("/iletisim") == "sales"
    assert kind("/kvkk", generic="policy") == "policy"
    # A feature page with no type word in its address: the main menu names it; a demo button adds to it.
    assert kind("/kampanya-araci", in_nav=True) == "features"
    assert kind("/kampanya-araci", {"buttons": [{"text": "Demoyu inceleyin"}]}, in_nav=True) == "features"
    assert kind("/kampanya-araci") == "other"
    assert kind("/hakkimizda", in_nav=True) == "other" and kind("/about", in_nav=True) == "other"  # company pages
    # An author list (a listing page) is not a feature.
    assert kind("/yazar/ayse", generic="category") == "other"


def test_sampling_types_menu_feature_pages_before_reading():
    s = sampling.Sampler("saas", budget=40)
    s.add([SITE + "/", SITE + "/kampanya-araci", SITE + "/fiyatlandirma", SITE + "/yazar/ayse"],
          anchors={SITE + "/kampanya-araci": ["Kampanya aracı"]}, menu={SITE + "/kampanya-araci"})
    assert s.types[SITE + "/kampanya-araci"][0] == "features"
    assert s.types[SITE + "/fiyatlandirma"][0] == "pricing"
    assert sampling.allocate({"pricing": 3, "features": 40, "blog": 60}, bt.profile("saas"), 80)["features"] >= \
        sampling.allocate({"pricing": 3, "features": 40, "blog": 60}, bt.profile("saas"), 80)["blog"]


# ---------------------------------------------------------------- 2. the profile's checks

def page(path, *, h1="", types=(), images=(), meta=(), status=200, headers=None, title=""):
    return {"url": SITE + path, "status": status, "headers": headers or {},
            "analysis": {"h1_elements": [{"text": h1}] if h1 else [], "title": title or h1,
                         "structured_data": {"types": list(types)}, "images": list(images), "meta": list(meta)}}


def text(*lines):
    return "\n".join((BANNER,) + lines)


def logos(*names):
    return [{"alt": n, "in_chrome": False} for n in names]


def run(pages, types, texts, profile="saas"):
    filler = {f"{SITE}/x{n}": text("Başka bir sayfa", "Bir satır daha") for n in range(4)}  # the banner is site-wide
    made, missing = pr.findings(pages, types, profile, {**texts, **filler})
    return {f.rule_id: f for fs in made.values() for f in fs}, missing


def test_each_rule_is_found_on_a_made_up_software_site():
    pages = [
        page("/fiyatlandirma", h1="Fiyatlar", images=logos("plan")),
        page("/paketler", h1="Paketler"),
        page("/kampanya-araci", h1="Kampanya aracı"),
        page("/entegrasyonlar", h1="Entegrasyonlar", images=logos("Alfa Kargo", "Beta Ödeme", "Gama ERP", "Delta", "Epsilon", "Zeta")),
        page("/hikaye/acme", h1="Acme başarı hikayesi"),
        page("/demo", h1="Demo", meta=[{"name": "robots", "content": "noindex, follow"}]),
    ]
    types = {SITE + "/fiyatlandirma": "pricing", SITE + "/paketler": "pricing", SITE + "/kampanya-araci": "features",
             SITE + "/entegrasyonlar": "integrations", SITE + "/hikaye/acme": "references", SITE + "/demo": "demo"}
    texts = {SITE + "/fiyatlandirma": text("Fiyatlar", "Planınızı seçin ve hemen başlayın"),
             SITE + "/paketler": text("Paketler", "Başlangıç 1.290 ₺ / ay", "Pro 2.490 TL"),
             SITE + "/kampanya-araci": text("Kampanya aracı", "Kampanyalar artık çok daha güçlü!"),
             SITE + "/entegrasyonlar": text("Entegrasyonlar", "Yüzlerce entegrasyon tek panelde"),
             SITE + "/hikaye/acme": text("Acme başarı hikayesi", *(["Acme, mağazasını bizim altyapımıza taşıdı ve "
                                                                   "ekibiyle birlikte yeni bir yola çıktı."] * 20)),
             SITE + "/demo": text("Demo", "Formu doldurun")}
    found, missing = run(pages, types, texts)
    assert set(found) == set(pr.RULES) and missing == []
    assert [r["url"] for r in found["rnd2.saas_pricing_text"].evidence["pages"]] == [SITE + "/fiyatlandirma"]
    assert [r["url"] for r in found["str3.saas_offer_schema"].evidence["pages"]] == [SITE + "/paketler"]
    assert found["acc3.saas_trial_blocked"].severity.value == "S2"
    assert found["str15.saas_feature_intro"].confidence.value == "inferred"  # Kontrol edin: read from the text
    assert all(row["row"]["tr"] and row["row"]["en"] for f in found.values() for row in f.evidence["pages"])


def test_nothing_is_reported_when_the_pages_do_it_right():
    pages = [
        page("/paketler", h1="Paketler", types=["SoftwareApplication", "Offer"]),
        page("/kampanya-araci", h1="Kampanya aracı"),
        page("/entegrasyonlar", h1="Entegrasyonlar", images=logos("Alfa Kargo", "Beta Ödeme", "Gama ERP", "Delta", "Epsilon", "Zeta")),
        page("/hikaye/acme", h1="Acme başarı hikayesi"),
        page("/demo", h1="Demo"),
    ]
    types = {SITE + "/paketler": "pricing", SITE + "/kampanya-araci": "features", SITE + "/entegrasyonlar": "integrations",
             SITE + "/hikaye/acme": "references", SITE + "/demo": "demo"}
    texts = {SITE + "/paketler": text("Paketler", "Başlangıç 1.290 ₺ / ay"),
             SITE + "/kampanya-araci": text("Kampanya aracı", "Kampanya aracı, mağazanızdaki indirimleri tek ekrandan kurmanızı ve "
                                                              "sonuçlarını izlemenizi sağlar."),
             SITE + "/entegrasyonlar": text("Entegrasyonlar", "Alfa Kargo", "Beta Ödeme", "Gama ERP", "Delta", "Epsilon"),
             SITE + "/hikaye/acme": text("Acme başarı hikayesi", *(["Acme satışlarını altı ayda %40 artırdı ve iade süresini "
                                                                   "yarıya indirdi."] * 20)),
             SITE + "/demo": text("Demo", "Formu doldurun")}
    found, _ = run(pages, types, texts)
    assert found == {}


def test_the_checks_run_only_for_the_saas_profile_and_say_what_they_could_not_read():
    pages = [page("/fiyatlandirma", h1="Fiyatlar")]
    types = {SITE + "/fiyatlandirma": "pricing"}
    assert run(pages, types, {SITE + "/fiyatlandirma": text("Fiyatlar")}, profile="eticaret") == ({}, [])
    assert run(pages, types, {SITE + "/fiyatlandirma": text("Fiyatlar")}, profile="diger") == ({}, [])
    _, missing = pr.findings(pages, types, "saas", {})
    assert missing and "not kept" in missing[0]["why"]


def test_a_site_wide_banner_is_not_a_pages_first_paragraph_or_price():
    texts = {f"{SITE}/p{n}": text(f"Başlık {n}", "kısa") for n in range(6)}
    cleaned = pr.without_furniture(texts)
    assert all(BANNER not in t for t in cleaned.values())
    assert pr.first_paragraph("Promo satırı\nE-Ticaret Paketleri ve\nPaket Fiyatları\n" + "x" * 90,
                              "E-Ticaret Paketleri ve Paket Fiyatları") == "x" * 90
    assert not pr.PRICE.search("2 yil alimda 1 yillik lisans")  # a number of years is not a price


def test_the_live_audit_adds_the_findings_once_to_their_checks():
    pages = [SimpleNamespace(url=SITE + "/demo", status=200, headers={"X-Robots-Tag": "noindex"},
                             analysis={"h1_elements": [{"text": "Demo"}], "_content_blocks": ["Demo"]},
                             grouping={"business_page_type": "demo", "importance": 70})]
    acc3 = SimpleNamespace(check_id="ACC-3", status="pass", findings=[])
    result = SimpleNamespace(pages=pages, business_type={"id": "saas"})
    pr.extend([acc3], result)
    assert acc3.status == "findings" and [f.rule_id for f in acc3.findings] == ["acc3.saas_trial_blocked"]
    pr.extend([acc3], SimpleNamespace(pages=pages, business_type={"id": "diger"}))
    assert len(acc3.findings) == 1


def test_a_saved_audit_gets_the_checks_offline_for_the_chosen_profile():
    from maya_audit import reassess_rules
    home = {"url": SITE + "/", "status": 200, "outlinks": SAAS_MENU,
            "analysis": {"title": "Soft", "buttons": [{"text": "Ücretsiz deneyin"}], "structured_data": {"types": []}},
            "grouping": {"page_type": "home", "importance": 100, "importance_parts": {}, "read": True}}
    pricing = {"url": SITE + "/fiyatlandirma", "status": 200, "outlinks": [],
               "analysis": {"title": "Fiyatlandırma", "h1_elements": [{"text": "Fiyatlandırma"}], "structured_data": {"types": []}},
               "grouping": {"page_type": "other", "importance": 50, "importance_parts": {}, "read": True}}
    report = {"checks": [{"check_id": "RND-2", "status": "pass", "findings": []}, {"check_id": "STR-3", "status": "pass", "findings": []}],
              "crawl": {"start_url": SITE + "/", "origin": SITE, "pages": [home, pricing],
                        "page_grouping": {"method_version": 99}}}
    saved = [json.dumps({"url": SITE + "/fiyatlandirma", "main_text": "Fiyatlandırma\nPlanınızı seçin"})]
    aff, changes = {}, []
    reassess_rules._decisions_356(report, aff, changes, saved, "saas")
    rules = [f["rule_id"] for c in report["checks"] for f in c["findings"]]
    assert rules == ["rnd2.saas_pricing_text"] and changes and report["checks"][0]["status"] == "findings"
    reassess_rules._decisions_356(report, aff, changes, saved, "diger")  # another profile: the finding goes away
    assert [f["rule_id"] for c in report["checks"] for f in c["findings"]] == []


def test_the_rules_have_their_words_in_every_place():
    from maya_audit_web import wording
    from maya_audit_web.team_report import texts
    from pathlib import Path
    kinds = json.loads((Path(bt.__file__).parents[1] / "issue_types.json").read_text(encoding="utf-8"))["rules"]
    for rule in pr.RULES:
        assert kinds[rule] in ("issue", "warning")
        assert texts.rule(rule, "tr")["title"] != texts.library("tr")["generic"]["title"]
        assert rule in wording.ENGLISH and rule in wording._table("tr", "titles")
    assert kinds["str3.saas_offer_schema"] == "issue" and kinds["str15.saas_feature_intro"] == "warning"
