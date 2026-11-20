"""DECISIONS 371: İlginay's second review (Nature's Garden Ek) as global rules. Every card has an "Örnek" (RG-24 names an
empty one); an <h1> a screen reader reads is not "hidden"; a short heading, or one holding a common word of the page's
language, is never called foreign, and repeated headings count once; "no products" means 0 in the HTML and in the
rendered page; account, sign-in and cart pages leave the content findings; dead links and shared heading jumps say what
is wrong. Fake reports only."""
from __future__ import annotations

from maya_audit import client_appendix, page_rows, reassess_rules, xlsx
from maya_audit import client_selection as cs
from maya_audit.checks.quick_rules import rendered_products
from maya_audit.example_rows import attach, site_example
from maya_audit.language import heading_language
from maya_audit.page_groups import is_utility_address

from test_v03_client_report import finding, report

SITE = "https://shop.test"


def _check(cid, *findings):
    return {"check_id": cid, "status": "findings", "findings": list(findings)}


def _f(fid, cid, rule, title, urls, evidence):
    return {"id": fid, "check_id": cid, "rule_id": rule, "title": title, "severity": "S4", "confidence": "verified",
            "scope": {"kind": "page", "count": len(urls), "urls": list(urls)}, "evidence": evidence}


def test_short_headings_and_headings_with_the_page_languages_words_are_the_pages_language():
    assert heading_language("Non-Candy Halloween Treats to Hand Out This Year", declared="en") == "en"
    assert heading_language("Fragen und Antworten", declared="en") is None  # too short to call alone
    assert heading_language("Unterschied zu den anderen Angeboten", declared="en") == "de"
    row = {"url": SITE + "/blogs/tips", "declared": "en", "headings_language": "it", "headings_count": 3,
           "headings": ["Non-Candy Halloween Treats to Hand Out This Year"] * 3}
    f = _f("STR-12-h", "STR-12", "str12.headings", "1 page(s) have section headings in another language than they declare "
           "(declared English, headings in Italian)", [SITE + "/blogs/tips"], {"pages": [row]})
    r = {"checks": [_check("STR-12", f)], "crawl": {}}
    reassess_rules._decisions_368(r, {"STR-12-h": [SITE + "/blogs/tips"]}, [], [])
    assert r["checks"][0]["findings"] == []


def test_an_h1_is_hidden_only_when_no_screen_reader_reads_it_either():
    def report_with(visibility):
        f = _f("STR-2-h", "STR-2", "str2.hidden_h1", "2 page(s) have only a hidden <h1>", [SITE + "/a", SITE + "/b"],
               {"pages": [{"url": u, "h1": ["Recipes"], "hidden_by": "the rendered page's computed style (display, "
                           "visibility or opacity of it or an element around it)"} for u in (SITE + "/a", SITE + "/b")]})
        render = {SITE + "/a": {"ok": True, "h1_visibility": visibility},
                  SITE + "/b": {"ok": True, "h1_visibility": [{"text": "Recipes", "visible": False, "accessible": False}]}}
        return {"checks": [_check("STR-2", f)], "crawl": {"render": {"pages": render}}}
    for unknown in ([{"text": "Recipes", "visible": False}],  # an older reading: not established
                    [{"text": "Recipes", "visible": False, "accessible": True, "pattern": "visually-hidden"}]):
        r = report_with(unknown)
        affected = {"STR-2-h": [SITE + "/a", SITE + "/b"]}
        reassess_rules._decisions_371(r, affected, [])
        assert affected["STR-2-h"] == [SITE + "/b"]  # display:none for everyone: still hidden


def test_no_products_means_none_in_the_html_and_none_after_the_scripts_run():
    rows = [{"url": SITE + "/collections/a", "products_listed": 1}, {"url": SITE + "/collections/b", "products_listed": 0},
            {"url": SITE + "/collections/c", "products_listed": 0}]
    f = _f("STR-15-e", "STR-15", "str15.empty_collections", "3 indexable collection or category page(s) list no product "
           "or almost none", [r["url"] for r in rows], {"pages": rows})
    render = {SITE + "/collections/c": {"rendered_links": [{"target": SITE + "/products/x"}, {"target": SITE + "/about"}]},
              SITE + "/collections/b": {"rendered_links": [{"target": SITE + "/about"}]}}
    r = {"checks": [_check("STR-15", f)], "crawl": {"render": {"pages": render}, "pages": []}}
    affected = {"STR-15-e": [x["url"] for x in rows]}
    reassess_rules._decisions_371(r, affected, [])
    assert affected["STR-15-e"] == [SITE + "/collections/b"]
    assert page_rows.measured(f, SITE + "/collections/b", "tr") == "HTML'de 0 ürün; işlenmiş sayfada da 0 ürün"
    assert rendered_products(None, {}) is None


def test_account_sign_in_and_cart_pages_leave_the_content_findings():
    assert is_utility_address(SITE + "/account/login") and is_utility_address(SITE + "/cart")
    assert not is_utility_address(SITE + "/collections/clusters")
    f = _f("RND-1-p", "RND-1", "rnd1.partial", "Part of the content (50%–80% present) is missing from the raw HTML of 2 "
           "page(s)", [SITE + "/account/login", SITE + "/recipes"], {"pages": [{"url": SITE + "/account/login"},
                                                                              {"url": SITE + "/recipes"}]})
    r = {"checks": [_check("RND-1", f)], "crawl": {}}
    affected = {"RND-1-p": [SITE + "/account/login", SITE + "/recipes"]}
    reassess_rules._decisions_371(r, affected, [])
    assert affected["RND-1-p"] == [SITE + "/recipes"]


def test_dead_links_and_shared_heading_jumps_say_what_is_wrong():
    dead = _f("STR-19-d", "STR-19", "str19.no_target", "x", [SITE + "/p"],
              {"links": [{"text": "1", "why": 'href="#"', "example": SITE + "/p", "component": "li.pagination"}]})
    jump = _f("TSEO-1-j", "TSEO-1", "shared.heading_jump_varied", "x", [SITE + "/q"],
              {"shared_element": {"text": "SHOP", "level": 4, "where": "footer"}, "items": [{"url": SITE + "/q", "from": 2, "to": 4}]})
    r = {"checks": [_check("X", dead, jump)], "crawl": {}}
    attach(r)
    assert page_rows.measured(dead, SITE + "/p", "tr") == \
        '«1» <a href="#"> (li.pagination): bağlantı gibi görünüyor, gidecek adresi yok (href yalnızca «#»)'
    assert page_rows.measured(jump, SITE + "/q", "tr") == \
        "«SHOP» başlığı H4, sayfadaki H2 başlığından sonra geliyor (aradaki düzey atlanıyor); alt bilgide (footer)"


def test_site_examples_for_sitemap_dates_and_an_uncached_page():
    stamped = {"rule_id": "idx5.stamped", "title": "x", "evidence": {"documents": [
        {"sitemap": SITE + "/sitemap_products_1.xml?from=1&to=2", "urls": 19, "same_lastmod": 18, "value": "2026-11-16T09:44:05"}]}}
    assert site_example(stamped) == "sitemap_products_1.xml: 19 adresin 18'i aynı lastmod'u taşıyor (2026-11-16)"
    cache = {"rule_id": "prf1.not_cached", "title": "x", "evidence": {"pages": [
        {"url": SITE + "/", "ttfb_ms": 401.7, "cf-cache-status": "DYNAMIC", "cache-control": "private, max-age=0"}]}}
    assert site_example(cache) == "/: CDN önbelleği DYNAMIC; cache-control: private, max-age=0; ilk yanıt (tek ölçüm) 402 ms"


def test_every_card_has_an_example_and_rg24_names_a_card_without_one():
    stamped = finding("S", "idx5.stamped", "S4", urls=[SITE + "/"], check="IDX-5")
    stamped["evidence"] = {"documents": [{"sitemap": SITE + "/sitemap.xml", "urls": 10, "same_lastmod": 10, "value": "2026-11-16"}]}
    bare = finding("B", "str3.article_no_author", "S4", urls=[SITE + "/b"], check="STR-3")
    bare["evidence"] = {}
    todos = [{"n": 1, "title": "Sitemap", "severity": "S4", "issue_type": "issue", "finding_ids": ["S"], "all_urls": []},
             {"n": 2, "title": "Authors", "severity": "S4", "issue_type": "issue", "finding_ids": ["B"], "all_urls": []}]
    record = {"version": "t", "decision": "PASS", "violations": [], "counts": {}, "hard": 0}
    book = xlsx.read(client_appendix.build(cs.select(report([stamped, bare])), "tr", todos=todos, text_check=record))
    cards = {r[0]: r for r in book["Özet"] if r and r[0] in ("1", "2")}
    assert cards["1"][-1] == "sitemap.xml: 10 adresin 10'u aynı lastmod'u taşıyor (2026-11-16)"
    rg = [r for r in book["Kontrol raporu"] if r[0] == "RG-24"]
    assert len(rg) == 1 and rg[0][5] == "Özet: kart 2: Authors: «Örnek» boş (örnek ya da ölçülen değer yok)"


def test_headings_after_javascript_missing_titles_and_video_pages_have_a_site_example():
    assert site_example({"rule_id": "rnd2.candidates", "title": "x", "evidence": {"pages": [
        {"url": SITE + "/", "headings_only_after_render": ["Top Highlights", "Welcome!"], "prices_only_after_render": []}]}}) == \
        "/: yalnız JavaScript'le gelen başlıklar: «Top Highlights», «Welcome!»"
    assert site_example({"rule_id": "str1.no_title", "title": "x", "evidence": {"pages": [SITE + "/a"]}}) == \
        "/a: <title> etiketi yok ya da boş"
    assert site_example({"rule_id": "str20.media", "title": "x", "evidence": {"pages": [
        {"url": SITE + "/v", "players": ["video"], "words_of_its_own": 70}]}}) == "/v: <video> oynatıcı; sayfanın kendi metni 70 kelime"
    assert site_example({"rule_id": "str20.media", "title": "x", "evidence": {"pages": [
        {"url": SITE + "/m", "players": [], "video_embeds": ["https://player.vimeo.com/video/1"], "words_of_its_own": 65}]}}) == \
        "/m: player.vimeo.com video oynatıcı; sayfanın kendi metni 65 kelime"
