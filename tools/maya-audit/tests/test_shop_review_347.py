"""DECISIONS 347: the review of an optician shop's audit (Smart ~150) as global rules, on a hand-written fake shop.

One loopback site, offline, og:type="product" on every page (a theme default):
  /hesabim/siparislerim  302 -> /uye/giris?ReturnUrl=..., linked from every page's menu (rule 1: a note, no card);
  /eski-erkek           301 -> /gunes-gozlugu, linked from one listing (rule 1: the real case, the final address);
  robots.txt            blocks Bytespider (training) only, sitewide (rule 2: "Kontrol edin", never P0/P1);
  /urunler.xml          a sitemap without "sitemap" in its name, /feed served as RSS (rule 3: never pages);
  /gunes-gozlugu, /erkek-gunes-gozlugu   listings of item addresses (…-ab1234-55-…_12345) (rule 4: category);
  /urun pages           item addresses with a model code and an id (rule 4: product);
  /magaza/merkez        Store markup with an address and coordinates (rule 4: location);
  /iletisim             a form, no items, on the listings' layout (rule 4: not a category);
  /erkek-gunes-gozlugux a typo of /erkek-gunes-gozlugu answering 200 with content (rule 5);
  /uye/giris, /hesabim  sign-in and account pages (rule 6: utility, low importance; the homepage first).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from fakeserver import Response
from maya_audit import business_types, client_selection, final, page_groups, page_rows, priority_levels, reassess_rules
from maya_audit.checks import stage8_rules, team_rules
from test_m1_broken_links import audit
from test_review_fixes import TR
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

ITEMS = ["/rayban-rb-ab1234-55-erkek-gunes-gozlugu_12345", "/gucci-gg0748s-012-unisex-gunes-gozlugu_23456",
         "/vogue-vo5725-242671-kadin-gunes-gozlugu_34567", "/police-sp123-0700-erkek-gunes-gozlugu_45678"]
MENU = ["/gunes-gozlugu", "/erkek-gunes-gozlugu", "/magaza/merkez", "/iletisim", "/hesabim/siparislerim", "/hesabim",
        "/uye/giris", "/feed"]
OG = '<meta property="og:type" content="product">'


def page(title: str, h1: str, body: str = "", head: str = "", words: str = "") -> Response:
    nav = " ".join(f'<a href="{p}">{p.strip("/") or "ana sayfa"}</a>' for p in MENU)
    return Response(body=f'<!doctype html><html lang="tr"><head><title>{title}</title>{OG}{head}</head><body><header><nav>'
                         f'{nav}</nav></header><main><h1>{h1}</h1><p>{words} {TR}</p>{body}</main>'
                         f'<footer><a href="/kvkk-aydinlatma-metni">KVKK</a></footer></body></html>')


def listing(title: str, items: list[str], extra: str = "") -> Response:
    cards = "".join(f'<div class="card"><a href="{u}">{u.strip("/")[:20]}</a></div>' for u in items)
    return page(title, title, cards + extra, words="Güneş gözlüğü modelleri.")


def jsonld(value: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(value, ensure_ascii=False)}</script>'


def routes() -> dict:
    sitemap = "".join(f"<url><loc>{{base}}{p}</loc></url>" for p in ["/", "/gunes-gozlugu", "/erkek-gunes-gozlugu",
                                                                             "/erkek-gunes-gozlugux"])
    r = {
        "/robots.txt": Response(body="User-agent: Bytespider\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
                                     "Sitemap: {base}/urunler.xml\n", content_type="text/plain"),
        "/sitemap.xml": Response(404, "", content_type="text/plain"),
        "/urunler.xml": Response(body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                      f"{sitemap}</urlset>", content_type="application/xml"),
        "/feed": Response(body='<?xml version="1.0"?><rss><channel><title>Yeni</title></channel></rss>',
                          content_type="application/rss+xml"),
        "/": page("Optik mağazası", "Optik mağazası", "".join(f'<a href="{u}">ürün</a>' for u in ITEMS[:1]),
                  words="Ana sayfa."),
        "/gunes-gozlugu": listing("Güneş gözlükleri", ITEMS),
        "/erkek-gunes-gozlugu": listing("Erkek güneş gözlükleri", ITEMS[:3], '<a href="/eski-erkek">Eski erkek</a>'),
        "/erkek-gunes-gozlugux": listing("Erkek güneş gözlükleri", ITEMS[:3]),
        "/eski-erkek": Response(301, "", headers={"Location": "/gunes-gozlugu"}),
        "/magaza/merkez": page("Merkez mağaza", "Merkez mağaza", head=jsonld({
            "@context": "https://schema.org", "@type": "Store", "name": "Merkez",
            "address": {"@type": "PostalAddress", "streetAddress": "Cadde 1"},
            "geo": {"@type": "GeoCoordinates", "latitude": 41.0, "longitude": 29.0}})),
        "/iletisim": page("İletişim", "İletişim", '<form action="/iletisim/gonder" method="post"><input name="ad">'
                                                  '<button>Gönder</button></form>'),
        "/hesabim/siparislerim": Response(302, "", headers={"Location": "/uye/giris?ReturnUrl=%2Fhesabim%2Fsiparislerim"}),
        "/hesabim": page("Hesabım", "Hesabım"),
        "/uye/giris": page("Üye girişi", "Üye girişi", '<form action="/uye/giris" method="post"><button>Giriş yap</button></form>'),
        "/kvkk-aydinlatma-metni": page("KVKK aydınlatma metni", "KVKK aydınlatma metni"),
    }
    for n, u in enumerate(ITEMS):
        r[u] = page(f"Gözlük {n}", f"Gözlük model {n}", '<button class="add">Sepete ekle</button><span class="price">1.299 TL</span>',
                    head=jsonld({"@context": "https://schema.org", "@type": "Product", "name": f"Gözlük {n}",
                                 "offers": {"@type": "Offer", "price": "1299", "priceCurrency": "TRY"}}))
    return r


@pytest.fixture(scope="module")
def shop():
    outcome, base = audit(routes(), max_pages=40)
    sealed = final.seal(outcome)
    found = {}
    for c in sealed.report["checks"]:
        for f in c["findings"]:
            found.setdefault(f["rule_id"], f)
    return sealed, found, base


def by_path(report: dict, base: str) -> dict:
    return {p["url"].removeprefix(base) or "/": p.get("grouping") or {} for p in report["crawl"]["pages"]}


# ---------------------------------------------------------------- 1. links to a page behind a sign-in


def test_links_to_a_page_behind_a_sign_in_are_a_note_not_a_card(shop):
    sealed, found, base = shop
    note = found["idx6.links_to_login_redirect"]
    assert note["severity"] == "Info" and note["evidence"]["targets"][0]["url"] == base + "/hesabim/siparislerim"
    assert "(beklenen)" in note["evidence"]["pages"][0]["row"]["tr"]
    assert "remove" not in note["how_to_fix"].lower() and "kaldır" not in json.dumps(note["evidence"], ensure_ascii=False)
    plain = found.get("idx6.links_to_redirect")
    assert plain is not None and [t["url"] for t in plain["evidence"]["targets"]] == [base + "/eski-erkek"]


def test_a_real_redirect_link_names_its_final_address_per_page(shop):
    sealed, found, base = shop
    plain = found["idx6.links_to_redirect"]
    [fix] = plain["evidence"]["page_fixes"]
    assert fix["url"] == base + "/erkek-gunes-gozlugu"
    assert fix["fix"]["tr"] == "Bağlantıyı doğrudan son adrese verin: /eski-erkek → /gunes-gozlugu."
    sel = client_selection.select(sealed.report, sealed.affected, {})
    rows = [r for r in page_rows.finding_rows(sel, sealed.affected, "tr") if r["rule_id"] == "idx6.links_to_redirect"]
    assert [r["fix"] for r in rows] == [fix["fix"]["tr"]]


@pytest.mark.parametrize("url,final_url,login", [
    ("https://b.test/Uye/Siparislerim", "https://b.test/Uye?ReturnUrl=%2FUye%2FSiparislerim", True),
    ("https://b.test/hesabim", "https://b.test/", True),                       # an account address
    ("https://b.test/kampanya", "https://b.test/login?next=/kampanya", True),  # the end is a sign-in page
    ("https://b.test/kampanya", "https://b.test/yeni-kampanya", False),        # a plain moved page
    ("https://b.test/author/ali", "https://b.test/yazarlar/ali", False),       # "auth" inside a word is not a sign-in
])
def test_what_counts_as_a_page_behind_a_sign_in(url, final_url, login):
    walk = {"hops": [{"url": url, "status": 302, "target": final_url}], "final": final_url}
    assert stage8_rules._login(url, walk) is login
    assert stage8_rules._login(url, {**walk, "hops": [{"url": url, "status": 301, "target": final_url}]}) is False


# ---------------------------------------------------------------- 2. robots.txt blocking training bots only


def test_a_training_only_block_is_a_policy_check_never_p0_or_p1(shop):
    sealed, found, _ = shop
    f = found["acc2.training_block.sitewide"]
    assert "Bytespider" in f["title"] and "acc2.blocks.sitewide" not in found
    sel = client_selection.select(sealed.report, sealed.affected, {})
    [g] = [g for g in sel["groups"] if f["id"] in g["finding_ids"]]
    assert g["issue_type"] == "warning" and (g.get("p_level") or {}).get("level") not in ("P0", "P1")


def test_the_policy_cap_keeps_a_high_score_at_p2_and_search_blocks_stay_p0():
    ctx = priority_levels.Context({"https://b.test/": {"page_type": "home", "importance": 100}}, {}, {"https://b.test/"})
    member = {"id": "ACC-2-x", "severity": "S2", "rule_id": "acc2.training_block.sitewide",
              "scope": {"urls": ["https://b.test/"]}}
    group = {"members": [member], "finding_ids": ["ACC-2-x"], "severity": "S2"}
    assert priority_levels.label(group, ctx, None, None)["level"] == "P2"
    search = {**member, "rule_id": "acc2.blocks.sitewide"}
    assert priority_levels.label({**group, "members": [search]}, ctx, None, None)["level"] == "P0"


def test_the_role_decides_the_rule():
    from maya_audit.rules import rule_id
    assert rule_id("ACC-2", "robots.txt line 4 (Disallow: /) blocks training bot(s) Bytespider sitewide") == "acc2.training_block.sitewide"
    assert rule_id("ACC-2", "robots.txt line 4 (Disallow: /x) blocks training bot(s) GPTBot on 2 sampled URL(s)") == "acc2.training_block.sample"
    assert rule_id("ACC-2", "robots.txt line 4 (Disallow: /) blocks search bot(s) OAI-SearchBot sitewide") == "acc2.blocks.sitewide"
    assert rule_id("ACC-2", "robots.txt line 4 (Disallow: /) blocks live bot(s) ChatGPT-User sitewide") == "acc2.blocks.sitewide"


# ---------------------------------------------------------------- 3. XML, feeds and other files are never pages


@pytest.mark.parametrize("url,content_type,file", [
    ("https://b.test/sitemap.xml", None, True), ("https://b.test/kurumsal.xml", None, True),
    ("https://b.test/urunler.xml.gz", None, True), ("https://b.test/feed", None, True), ("https://b.test/llms.txt", None, True),
    ("https://b.test/blog", "application/rss+xml", True), ("https://b.test/gunes-gozlugu", None, False),
    ("https://b.test/gunes-gozlugu", "text/html; charset=utf-8", False), ("https://b.test/xml-nedir", None, False)])
def test_what_is_not_a_page(url, content_type, file):
    assert client_selection.not_a_page(url, content_type) is file


def test_a_feed_or_sitemap_is_never_a_page_read_or_typed(shop):
    sealed, _, base = shop
    read = client_selection.pages_read(sealed.report)
    assert base + "/feed" not in read and base + "/urunler.xml" not in read
    types = by_path(sealed.report, base)
    assert "importance" not in types.get("/feed", {}) and "importance" not in types.get("/urunler.xml", {})


def test_a_sitemap_finding_lists_the_file_as_no_page():
    finding = {"id": "IDX-5-x", "check_id": "IDX-5", "severity": "S4", "title": "lastmod",
               "scope": {"urls": ["https://b.test/kurumsal.xml", "https://b.test/sitemap.xml"]}}
    assert client_selection.host_level(finding) == ["b.test"]
    sel = {"groups": [{"placement": "card", "members": [finding], "finding_ids": ["IDX-5-x"]}],
           "_importance": {"https://b.test/kurumsal.xml": {"page_type": "product", "importance": 90}}}
    rows = page_rows.finding_rows(sel, None, "tr")
    assert {r["url"] for r in rows} == {"https://b.test/kurumsal.xml", "https://b.test/sitemap.xml"}
    assert all(r["page"] is False and r["read"] is None and r["page_type"] is None for r in rows)
    assert page_rows.page_table(rows) == []


# ---------------------------------------------------------------- 4. page types without a profile


def test_page_types_from_what_each_page_is_not_the_sitewide_og_type(shop):
    sealed, _, base = shop
    t = {u: g.get("page_type") for u, g in by_path(sealed.report, base).items() if "page_type" in g}
    assert {t[u] for u in ITEMS if u in t} == {"product"}
    assert t["/gunes-gozlugu"] == "category" and t["/erkek-gunes-gozlugu"] == "category"
    assert t["/magaza/merkez"] == "location"
    assert t["/iletisim"] not in ("category", "product")
    assert t["/hesabim"] == "utility" and t["/uye/giris"] == "utility"
    assert sealed.report["crawl"]["page_grouping"]["method_version"] == page_groups.METHOD_VERSION == 5


@pytest.mark.parametrize("url,item", [
    ("https://b.test/armani-exchange-0ax2034s-600087-5914145-erkek-gunes-gozlukleri_82087", True),
    ("https://b.test/kurumsal/nerelerdeyiz_1476", False), ("https://b.test/kurumsal/iso-13485-kalite-sertifikasi_2058", False),
    ("https://b.test/blog/2024-yaz-trendleri", False), ("https://b.test/gunes-gozlugu", False)])
def test_what_an_item_address_is(url, item):
    assert page_groups.item_address(url) is item


@pytest.mark.parametrize("segment,account", [("uye", True), ("pluslogin", True), ("ordertracker", True),
                                             ("siparislerim", True), ("my-account", True), ("hesap-ac", False),
                                             ("uyelik_1519", True), ("gunes-gozlugu", False), ("kayit-ol", True),
                                             ("orderly-design", False), ("hasir-sepet", False),
                                             ("aluminyum-profil", False)])
def test_what_an_account_address_is(segment, account):
    assert page_groups.account_segment(segment) is account


def test_the_e_commerce_profile_is_suggested_from_product_and_category_pages():
    types = {"category": 10, "product": 20, "other": 5, "home": 1}
    s = business_types.suggest(None, None, None, [], (), types)
    assert s["id"] == "eticaret" and any(x["kind"] == "types" for x in s["signals"])
    assert business_types.suggest(None, None, None, [], (), {"other": 30, "product": 2})["id"] == "diger"


# ---------------------------------------------------------------- 5. misspelt addresses of a page


def test_a_misspelt_address_answering_200_names_the_real_page(shop):
    sealed, found, base = shop
    f = found["idx8.typo_copies"]
    [row] = [r for r in f["evidence"]["pages"] if r["kind"] == "copy"]
    assert row["url"] == base + "/erkek-gunes-gozlugux" and row["real"] == base + "/erkek-gunes-gozlugu"
    assert row["fix"]["tr"] == "Bu adresi /erkek-gunes-gozlugu adresine 301 ile yönlendirin ya da kanonik etiketini oraya verin."
    assert f["severity"] == "S3"


def P(url, status=200, links=(), canon=None):
    a = {"title": url, "h1_elements": [], "canonicals": [canon or url], "structured_data": {"types": []}, "og": {}}
    return SimpleNamespace(url=url, status=status, analysis=a, outlinks=[{"target": t} for t in links])


@pytest.mark.parametrize("a,b,typo", [("ray-ban-modelleri", "ray-ban-modellerix", True),
                                      ("cocuk-gunes-gozlugu-modelleri", "cocuk-gunes-gozlugu-modelleri-", True),
                                      ("erkek-saat-2023", "erkek-saat-2024", False),     # a number: another item
                                      ("kisa", "kisax", False),                            # too short to tell
                                      ("erkek-gozlukleri", "kadin-gozlukleri", False)])  # another word
def test_what_a_typo_is(a, b, typo):
    assert team_rules._typo_pair(a, b) is typo


def test_two_pages_both_linked_are_not_typos_and_a_redirect_elsewhere_is_one():
    real, twin = "https://b.test/erkek-modelleri", "https://b.test/erkek-modellerim"
    pages = [P("https://b.test/", links=[real, twin]), P("https://b.test/a", links=[real, twin]), P(real), P(twin)]
    assert team_rules.typo_copies(pages, pages, redirects=[]) == []
    moved = SimpleNamespace(url=real + "-", status=301, analysis=None, outlinks=[])
    redirects = [{"url": real + "-", "hops": [{"url": real + "-", "status": 301, "target": "https://b.test/"}],
                  "final": "https://b.test/"}]
    [f] = team_rules.typo_copies(pages + [moved], pages, redirects=redirects)
    [row] = f.evidence["pages"]
    assert row["kind"] == "redirect" and row["real"] == real and f.severity.value == "S4"


# ---------------------------------------------------------------- 6. account pages and the homepage under a profile


def test_account_pages_are_utility_and_the_homepage_comes_first_under_e_commerce(shop):
    sealed, _, base = shop
    importance, summary = client_selection.grouping(sealed.report, "eticaret")
    home = importance[base + "/"]
    assert home["importance_rank"] == 1 and home["importance"] >= max(g["importance"] for g in importance.values())
    for u in ("/hesabim", "/uye/giris"):
        g = importance[base + u]
        assert g["business_page_type"] == "utility" and g["importance"] <= 20
    assert all(importance[base + u]["importance"] > 20 for u in ITEMS if base + u in importance)


def test_home_first_raises_a_lower_homepage():
    records = {"/": {"page_type": "home", "importance": 85}, "/c": {"page_type": "category", "importance": 90}}
    page_groups.home_first(records)
    assert records["/"]["importance"] == 90 and records["/"]["importance_parts"]["raised"] == page_groups.HOME_FIRST


# ---------------------------------------------------------------- a saved report


def test_a_saved_report_gets_the_new_types_and_rules_offline(shop):
    sealed, found, base = shop
    old = json.loads(json.dumps(sealed.report))
    old["crawl"]["page_grouping"]["method_version"] = 2
    for p in old["crawl"]["pages"]:
        if isinstance(p.get("grouping"), dict) and "page_type" in p["grouping"]:
            p["grouping"]["page_type"] = "product"
    for c in old["checks"]:
        for f in c["findings"]:
            if f["rule_id"] == "acc2.training_block.sitewide":
                f["rule_id"] = "acc2.blocks.sitewide"
    new, changes = reassess_rules.saved_data(old, dict(sealed.affected))
    types = {u: g.get("page_type") for u, g in by_path(new, base).items()}
    assert types["/magaza/merkez"] == "location" and types["/gunes-gozlugu"] == "category"
    assert {f["rule_id"] for c in new["checks"] for f in c["findings"]} >= {"acc2.training_block.sitewide",
                                                                             "idx6.links_to_login_redirect",
                                                                             "idx8.typo_copies"}
    assert any("DECISIONS 347" in c for c in changes)
