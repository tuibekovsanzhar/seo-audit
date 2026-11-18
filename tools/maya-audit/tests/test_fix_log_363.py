"""DECISIONS 363: the review fix log and the SEO team's gaps it closed. The notes on robots.txt, llms.txt, the sitemap's
lastmod, FAQPage questions and an <h1>'s questions; articles that name only an organization; pages clicked less than
their position's pages; titles changed since the previous audit; the Ticimax open items (why a page has no measures, the
first sentence past a promo bar, a brand's place in a list); the log itself and its Ek sheet. Made-up data only."""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

from maya_audit import fix_log
from maya_audit.analysis import ORG_AUTHOR, analyze_html, jsonld_author_kind

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- robots.txt, llms.txt, sitemap

def test_a_directive_written_inside_a_comment_is_noted():
    from maya_audit.robots import parse_robots
    robots = parse_robots("User-agent: *\nDisallow: /a\n# Content-Signal: search=yes, ai-train=no\n# just a comment\n")
    assert robots.commented == [(3, "# Content-Signal: search=yes, ai-train=no")]


def test_llms_txt_without_a_charset_or_with_a_bom_is_noted():
    from maya_audit.checks.access import llms_encoding
    docs = [{"url": "https://s.test/llms.txt", "status": 200, "readable": True, "content_type": "text/plain"},
            {"url": "https://s.test/llms-full.txt", "status": 200, "readable": True, "content_type": "text/plain; charset=utf-8", "bom": True},
            {"url": "https://s.test/ok.txt", "status": 200, "readable": True, "content_type": "text/plain; charset=utf-8"}]
    obs = llms_encoding(docs)
    assert obs["files"] == 2 and obs["examples"][0]["why"] == ["no charset"] and obs["examples"][1]["why"] == ["byte-order mark"]


def test_a_sitemap_that_gives_no_address_a_lastmod_is_noted():
    from maya_audit.checks.index import sitemap_without_lastmod
    files = [{"url": "https://s.test/a.xml", "kind": "urlset", "urls_found": 40, "lastmod_count": 0},
             {"url": "https://s.test/index.xml", "kind": "sitemapindex", "urls_found": 0}]
    assert sitemap_without_lastmod(files)["addresses"] == 40
    assert sitemap_without_lastmod([{**files[0], "lastmod_count": 3}]) is None


# ---------------------------------------------------------------- FAQPage, <h1>, author

def test_faqpage_questions_are_counted():
    from maya_audit.analysis import faq_question_count
    faq = {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "a"}, {"@type": "Question", "name": "b"}]}
    assert faq_question_count([faq]) == 2


def test_an_h1_question_no_section_answers_is_found():
    from maya_audit.checks.structure import h1_promise
    a = {"headings": [{"level": 1, "text": "Temettü nedir? Nasıl alınır?"}, {"level": 2, "text": "Temettü nedir"}]}
    assert h1_promise(a) == ("Temettü nedir? Nasıl alınır?", ["Nasıl alınır?"])
    a["headings"].append({"level": 3, "text": "Temettü nasıl alınır"})
    assert h1_promise(a)[1] == []


def test_an_article_whose_only_author_is_the_organization_is_its_own_finding():
    org = {"@type": "Article", "headline": "x", "author": {"@type": "Organization", "name": "Bank"}}
    person = {"@type": "Article", "headline": "x", "author": {"@type": "Person", "name": "Ayşe Yılmaz"}}
    assert jsonld_author_kind([{"data": org}]) == "organization" and jsonld_author_kind([{"data": person}]) == "person"
    html = f'<html><head><title>T</title><script type="application/ld+json">{json.dumps(org)}</script></head><body><h1>x</h1></body></html>'
    assert analyze_html(html)["author_signals"] == [ORG_AUTHOR]
    from maya_audit.checks.quick_rules import article_no_author
    page = SimpleNamespace(url="https://s.test/blog/a", analysis={"author_signals": [ORG_AUTHOR], "meta": [], "structured_data": {"types": ["Article"]}})
    found = article_no_author([page], {page.url: {"page_type": "blog_article"}}, {page.url})
    assert [f.title for f in found] == ["1 article page(s) name only an organization as author"]
    from maya_audit.rules import rule_id
    assert rule_id("STR-3", found[0].title) == "str3.article_org_author"


def test_a_saved_audit_gets_the_new_notes_and_the_author_finding_offline():
    from maya_audit import reassess_rules
    org = json.dumps({"@type": "Article", "author": {"@type": "Organization", "name": "Bank"}})
    report = {"crawl": {"sitemap_docs": [{"url": "https://s.test/s.xml", "kind": "urlset", "urls_found": 9, "lastmod_count": 0}],
                        "access": {"llms": [{"url": "https://s.test/llms.txt", "status": 200, "readable": True, "content_type": "text/plain"}]},
                        "pages": [{"url": "https://s.test/blog/a", "grouping": {"page_type": "blog_article"},
                                   "analysis": {"author_signals": ["JSON-LD author"], "meta": [],
                                                "headings": [{"level": 1, "text": "Kredi nedir? Nasıl çekilir?"}]}}]},
              "checks": [{"check_id": c, "status": "pass", "findings": [], "observations": []} for c in ("IDX-5", "ACC-8", "STR-2", "STR-3")]}
    affected, changes = {}, []
    reassess_rules._decisions_363(report, affected, changes, {"https://s.test/blog/a": [org]})
    by = {c["check_id"]: c for c in report["checks"]}
    assert [o["metric"] for o in by["IDX-5"]["observations"]] == ["sitemap files that give no address a <lastmod>"]
    assert by["ACC-8"]["observations"] and by["STR-2"]["observations"][0]["examples"][0]["unanswered"] == ["Nasıl çekilir?"]
    assert by["STR-3"]["findings"][0]["rule_id"] == "str3.article_org_author"


# ---------------------------------------------------------------- Maya sheets

def test_pages_clicked_less_than_their_positions_pages_are_marked():
    from maya_audit.maya_sheets import expected_ctr
    pages = {f"https://s.test/{i}": {"clicks": 50, "impressions": 1000, "ctr": 0.05, "position": 3.2} for i in range(4)}
    pages["https://s.test/low"] = {"clicks": 10, "impressions": 1000, "ctr": 0.01, "position": 2.8}
    medians, low = expected_ctr({"gsc": {"pages": pages}})
    assert medians["3"] == 0.05 and set(low) == {"https://s.test/low"}


def test_a_page_with_no_measures_says_why():
    from maya_audit.maya_sheets import unread_words
    assert unread_words({}, None, own=False) == "alınamadı («sayfaları da indir» seçilmedi)"
    assert unread_words({"fetch": {"wanted": True}}, {"error": "ConnectError"}, own=False) == "alınamadı (ConnectError)"
    assert unread_words({"fetch": {"wanted": True}}, None, own=True) == "okunmadı (indirme sınırı dışında kaldı)"


def test_the_first_sentence_skips_a_promo_bar_and_lines_every_page_opens_with():
    from maya_audit.maya_sheets import Crawl, measure_parts
    m = measure_parts("T", [], [], "Sepette %20 indirim, kod: YAZ20 ile tüm ürünlerde geçerli\nE-ticaret sitenizi dakikalar içinde "
                                    "kurun ve hemen satışa başlayın bugün", None, [], [], [])
    assert m["first"].startswith("E-ticaret sitenizi")
    crawl = Crawl({"crawl": {}}, None, {
        "https://s.test/a": {"first_candidates": ["Ücretsiz deneme ile hemen başlayın ve sitenizi kurun", "A sayfasının kendi cümlesi burada yazıyor"]},
        "https://s.test/b": {"first_candidates": ["Ücretsiz deneme ile hemen başlayın ve sitenizi kurun", "B sayfasının kendi cümlesi burada yazıyor"]}})
    assert crawl.first("https://s.test/a", crawl.measure("https://s.test/a")) == "A sayfasının kendi cümlesi burada yazıyor"


def test_the_brands_place_in_a_list_page_is_read_from_its_headings():
    from maya_audit.maya_sheets import list_rank
    summary = {"brand_names": ["Shop"], "brand_domains": ["shop.test"], "own_keys": ["shopt", "shoptest"], "competitors": [{"name": "Rival"}, {"name": "Other Co"}]}
    numbered = {"outline": ["Giriş", "1. Rival", "2. Other Co", "3. ShopT", "Sonuç"]}
    assert list_rank({**summary, "own_keys": ["shopt"]}, numbered) == "3. sıra"
    plain = {"outline": ["Rival", "ShopT", "Other Co"]}
    assert list_rank({**summary, "own_keys": ["shopt"]}, plain) == "2. sıra (3 markadan)"
    assert list_rank({**summary, "own_keys": ["shopt"]}, {"outline": ["Rival"]}) == "listede yok"


# ---------------------------------------------------------------- the previous audit

def test_titles_and_descriptions_changed_since_the_previous_audit_are_listed():
    from maya_audit.client_appendix import changed_sheet
    def report(title, desc):
        return {"crawl": {"page_measures": {"https://s.test/a": {"status": 200, "title": title, "description": desc}}}}
    sheet = changed_sheet(report("A", ""), {**report("Kredi kartı başvurusu ve avantajları | Banka", "Kart başvurusu"),
                                            "_audit": {"id": "2e5829fb", "date": "2026-11-09"}})
    assert sheet["name"] == "Önceki denetimden değişenler" and "2e5829fb" in sheet["rows"][0][0]
    title_row = next(r for r in sheet["rows"][1:] if r[1] == "Başlık (title)")
    assert title_row[4] == "Evet: önerilen uzunluğun altına indi"
    assert changed_sheet(report("A", "B"), None) is None
    same = changed_sheet(report("A", "B"), report("A", "B"))
    assert same["rows"][1][0] == "İki denetimde de okunan 1 sayfanın başlığı ve meta açıklaması değişmedi."


# ---------------------------------------------------------------- the log

def test_every_logged_item_is_complete_and_checked_by_a_known_check():
    known = {"no_card", "no_problem", "has_finding", "card_text", "no_text", "title_text", "sheet_has", "sheet_not",
             "severity_info", "gate", "has_observation", "row_not", "test", "crawl", "why"}
    decisions = set(re.findall(r"^(\d{3})\. ", (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8"), re.M))
    items = fix_log.items()
    assert len(items) >= 70
    for item in items:
        assert item["kaynak"] and item["sorun"] and item["nasil"] and item.get("genel"), item
        assert item["brand_key"] in fix_log.BRANDS
        assert set(item["check"]) <= known, item["check"]
        assert {str(n) for n in item["decisions"]} <= decisions | {"363"}, item["decisions"]
        if item["check"].get("test"):
            assert (ROOT / item["check"]["test"]).is_file(), item["check"]["test"]
        assert not re.search(r"\b(def|import|rule_id|json)\b|\w+\.\w+\(", item["nasil"]), item["nasil"]  # plain words


def test_the_eks_sheet_names_no_brand_file_or_person_and_is_newest_first(tmp_path, monkeypatch):
    rows = [{"no": i["no"], "durum": fix_log.FIXED, "tarih": f"2026-11-{10 + i['no'] % 9:02d}", "commit": "abc1234",
             "decisions": "363"} for i in fix_log.items()]
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    monkeypatch.setattr(fix_log, "STATUS_FILE", status)
    sheet = fix_log.ek_sheet("tr")
    assert sheet["name"] == "Düzeltme kaydı" and 0 < len(sheet["rows"]) <= fix_log.EK_ROWS
    dates = [r[0] for r in sheet["rows"]]
    assert dates == sorted(dates, reverse=True)
    names = [b["name"] for b in fix_log.BRANDS.values()] + ["Enpara", "MMI", "Carpex", "İlginay", "Efsa", ".xlsx"]
    assert not any(n.lower() in str(cell).lower() for r in sheet["rows"] for cell in r for n in names)


def test_the_log_workbook_has_the_columns_and_a_reading_guide():
    from maya_audit import xlsx
    rows = fix_log.evaluate(fix_log.items()[:2], {}, {338: ("abc1234", "2026-11-11")}, "2026-11-18", {})
    book = xlsx.read(fix_log.workbook(rows))
    assert list(book) == ["Nasıl okunur", "Düzeltme kaydı"]
    assert book["Düzeltme kaydı"][0] == ["No", "Kaynak", "Marka", "Sorun", "Durum", "Nasıl düzeltildi", "Tarih", "Commit",
                                          "DECISIONS no", "Kontrol"]
