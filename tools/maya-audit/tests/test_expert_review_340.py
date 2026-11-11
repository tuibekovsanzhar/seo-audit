"""DECISIONS 340: the SEO team's 2nd review of enpara fee70191 (docs/expert-reviews/enpara-fee70191.json).

Hand-written fake site; expected values come from its routes:

  SITEMAP   /sitemap.xml, one entry per line, lists /kampanya/y%c3%bcksek-faiz (lower-case escapes, 404) on line 4 and
            /eski?a=1&amp;b=2 (404) on line 5; no page links to either.
  REDIRECT  the homepage and /hesap link "Hesap aç" to /basvuru, which redirects (302) to /hesap (200): on /hesap the
            redirect ends on the linking page itself.
  LLMS      /llms.txt lists /sss (302 to /404?aspxerrorpath=/sss, never asked; the crawl saw /404?aspxerrorpath=/baska
            answer 404) and /nedir (301 to /hakkimizda, 200, linked from the homepage).
  FAQ       /odemeler writes four questions as plain paragraphs under a section heading "Ödeme İste" (not an FAQ);
            /sorular has the same under "Sıkça Sorulan Sorular" (an FAQ); /akordeon has them as accordion buttons.
  BRAND     /en/homepage gives "Homepage" as its Organization name, which is its own <title>.

Offline: a loopback fake server.
"""
from __future__ import annotations

import json

import pytest

from fakeserver import Response
from maya_audit import client_appendix, client_selection, final, xlsx
from maya_audit.analysis import analyze_html
from maya_audit.checks.structure import FAQ_SECTION, qa_container
from maya_audit.sitemap import loc_lines
from maya_audit_web.runner import REPORT_JSON
from maya_audit_web.team_report import build_data
from test_m1_broken_links import audit
from test_review_fixes import TR, page
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

QA = [("Ödeme İste nedir?", "Ödeme İste, BKM'nin sunduğu bir mesajlaşma ve para transferi altyapısıdır ve ücretsizdir."),
      ("Nasıl ödeme isteği gönderebilirim?", "Cep Şube'de Ödemeler menüsünden yeni bir ödeme isteği gönderebilirsiniz."),
      ("Gelen istekleri nerede görürüm?", "Cep Şube'de Gelen ödeme istekleri adımından tarafınıza gelenleri görürsünüz."),
      ("Nelere dikkat etmeliyim?", "Yalnız sistemin katılımcısı olan kurumların vadesiz hesaplarına istek gönderilebilir.")]


def qa_html(section: str, accordion: bool = False) -> str:
    if accordion:
        rows = "".join(f'<button aria-expanded="false" aria-controls="p{i}">{q}</button><div id="p{i}"><p>{a}</p></div>'
                       for i, (q, a) in enumerate(QA))
    else:
        rows = "".join(f"<p>{q}</p><p>{a}</p>" for q, a in QA)
    return f"<h1>Ödemeler</h1><p>{TR}</p><h2>{section}</h2>{rows}"


def routes() -> dict:
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               "<url><loc>{base}/</loc></url>\n"
               "<url><loc>{base}/kampanya/y%c3%bcksek-faiz</loc></url>\n"
               "<url><loc>{base}/eski?a=1&amp;b=2</loc></url>\n</urlset>\n")
    gone = Response(404, "<html><title>Yok</title><body>Sayfa yok</body></html>")
    links = ('<a href="/basvuru">Hesap aç</a> <a href="/odemeler">Ödemeler</a> <a href="/sorular">Sorular</a> '
             '<a href="/akordeon">Akordeon</a> <a href="/en/homepage">English</a> <a href="/hakkimizda">Hakkımızda</a> '
             '<a href="/404?aspxerrorpath=/baska">Eski</a>')
    org = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Homepage"}</script>'
    return {
        "/robots.txt": Response(body="User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n", content_type="text/plain"),
        "/sitemap.xml": Response(body=sitemap, content_type="application/xml"),
        "/llms.txt": Response(body="# Site\n\n- [SSS]({base}/sss)\n- [Nedir]({base}/nedir)\n", content_type="text/plain"),
        "/": page(f"<h1>Ana sayfa</h1><p>{TR}</p>{links}", nav=""),
        "/basvuru": Response(302, "", headers={"Location": "/hesap"}),
        "/hesap": page(f"<h1>Hesap</h1><p>{TR}</p><a href=\"/basvuru\">Hesap aç</a>", nav=""),
        "/sss": Response(302, "", headers={"Location": "/404?aspxerrorpath=/sss"}),
        "/404": gone,
        "/nedir": Response(301, "", headers={"Location": "/hakkimizda"}),
        "/hakkimizda": page(f"<h1>Hakkımızda</h1><p>{TR}</p>", nav=""),
        "/odemeler": page(qa_html("Ödeme İste"), nav=""),
        "/sorular": page(qa_html("Sıkça Sorulan Sorular"), nav=""),
        "/akordeon": page(qa_html("Ödeme İste", accordion=True), nav=""),
        "/en/homepage": Response(body=f"<html lang=\"en\"><head><title>Homepage</title>{org}</head><body><h1>Home</h1>"
                                      f"<p>{TR}</p></body></html>"),
        "/kampanya/y%C3%BCksek-faiz": gone, "/kampanya/yüksek-faiz": gone, "/eski": gone,
    }


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    outcome, base = audit(routes())
    sealed = final.seal(outcome)
    folder = tmp_path_factory.mktemp("audit") / "artifacts"
    folder.mkdir(parents=True)
    (folder / REPORT_JSON).write_text(json.dumps(sealed.report), encoding="utf-8")
    data = build_data.build_from_files(folder / REPORT_JSON, "tr")[0]
    sel = client_selection.select(sealed.report, sealed.affected, {})
    book = xlsx.read(client_appendix.build(sel, "tr", sealed.affected, places=sealed.cards,
                                           todos=build_data.cards_for_appendix(data)))
    return sealed, data, book, base


def findings(report, rule):
    return [f for c in report["checks"] for f in c["findings"] if f.get("rule_id") == rule]


# ------------------------------------------------------------------ card 2: the sitemap entry as written

def test_each_loc_is_kept_as_written_with_its_line():
    body = (b'<urlset>\n<url>\n <loc>https://a.test/y%c3%b6n?a=1&amp;b=2</loc>\n</url>'
            b'<url><loc> https://a.test/x </loc></url></urlset>')
    assert loc_lines(body) == [("https://a.test/y%c3%b6n?a=1&amp;b=2", 3), ("https://a.test/x", 4)]


def test_a_sitemap_only_entry_carries_its_loc_line_file_and_read_time(site):
    sealed, _, _, base = site
    [f] = findings(sealed.report, "idx1.4xx.sitemap_only")
    entries = {e["url"]: e for e in f["evidence"]["sitemap_entries"]}
    young = entries[base + "/kampanya/y%C3%BCksek-faiz"]  # Maya's form: escapes in capitals
    assert young["sitemap_loc"] == base + "/kampanya/y%c3%bcksek-faiz" and young["sitemap_line"] == 4  # the file's form
    assert young["sitemap_file"] == base + "/sitemap.xml" and young["sitemap_read_at"].startswith("20")
    assert entries[base + "/eski?a=1&b=2"]["sitemap_loc"] == base + "/eski?a=1&amp;b=2"


def test_the_ek_shows_the_loc_text_to_search_for_and_when_the_file_was_read(site):
    _, _, book, base = site
    sheet = book["Bağlantı yerleri"]
    head = sheet[0]
    row = next(r for r in sheet[1:] if r[head.index("Site haritasındaki <loc> metni")] == base + "/kampanya/y%c3%bcksek-faiz")
    assert row[head.index("<loc> satırı")] == "4"
    assert row[head.index("Site haritası okuma zamanı")].endswith(" TSİ)")  # exact, not "yaklaşık"
    assert row[head.index("Bozuk adres")] == base + "/kampanya/yüksek-faiz"  # readable, beside the searchable form


def test_a_saved_report_says_the_loc_was_not_recorded_and_when_the_sitemap_step_began():
    rows = {"F-1": [{"kind": "sitemap", "links_to": "https://b.test/y%C3%BC", "status": 302, "ends_at": "https://b.test/404",
                     "final_status": 404, "sitemap_file": "https://b.test/sitemap.xml", "in_sitemap": True,
                     "sitemap_read_at": "2026-11-11T12:07:49.885033+00:00", "sitemap_read_approx": True,
                     "rule_id": "idx1.4xx.sitemap_only", "suggested": "remove_or_redirect"}]}
    [row] = client_appendix.where_rows(rows, [], "tr")
    assert row[9:12] == ["https://b.test/y%C3%BC", "kaydedilmedi (eski denetim): adres, Maya'nın kaydettiği biçimde",
                         "2026-11-11 12:07:49 UTC (15:07:49 TSİ) — yaklaşık: site haritası okuma adımının başı"]


# ------------------------------------------------------------------ card 8: links to redirects, unambiguous

def test_links_to_a_redirect_have_their_own_sheet_with_the_old_and_the_final_address(site):
    _, _, book, base = site
    sheet = book["Yönlendiren bağlantılar"]
    assert sheet[0][1:8] == ["Bağlantının bulunduğu sayfa", "Bağlantı metni", "Konum", "Bağlantı verilen (eski) adres",
                             "Yönlendirme", "Doğrudan verilmesi gereken son adres", "Not"]
    rows = {r[1]: r for r in sheet[1:]}
    assert rows[base + "/"][4:7] == [base + "/basvuru", "302 → 200", base + "/hesap"] and rows[base + "/"][7] == ""
    assert rows[base + "/hesap"][7].startswith("yönlendirme bu sayfanın kendisinde bitiyor")
    assert not any(r[1] == base + "/basvuru" for r in book["Bağlantı yerleri"][1:])  # not called a broken address


def test_the_row_per_page_says_which_link_goes_where():
    from maya_audit import page_rows
    f = {"id": "IDX-6-1", "check_id": "IDX-6", "rule_id": "idx6.links_to_redirect", "severity": "S4", "confidence": "verified",
         "title": "1 internal link(s) point at an address that redirects", "scope": {"count": 2, "urls": ["https://b.test/", "https://b.test/hesap"]},
         "evidence": {"targets": [{"url": "https://b.test/basvuru", "final": "https://b.test/hesap",
                                   "linked_from": ["https://b.test/", "https://b.test/hesap"]}]}}
    sel = {"groups": [{"placement": "card", "members": [f], "issue_type": "issue", "finding_ids": ["IDX-6-1"]}]}
    rows = {r["url"]: r["value"] for r in page_rows.finding_rows(sel, None, "tr")}
    assert rows["https://b.test/"] == ("bu sayfadaki bağlantı https://b.test/basvuru adresine gidiyor; o adres https://b.test/hesap "
                                       "adresine yönlendiriyor: bağlantıyı doğrudan https://b.test/hesap adresine verin")
    assert "bu sayfanın kendisine yönlendiriyor" in rows["https://b.test/hesap"]


# ------------------------------------------------------------------ card 14: FAQPage only for a real Q&A block

@pytest.mark.parametrize("section, accordion, expected", [("Ödeme İste", False, None),
                                                          ("Sıkça Sorulan Sorular", False, "faq_section"),
                                                          ("Ödeme İste", True, "accordion")])
def test_questions_are_an_faq_only_in_an_faq_section_or_an_accordion(section, accordion, expected):
    url = "https://b.test/odemeler"
    assert qa_container(analyze_html(f"<html><body><main>{qa_html(section, accordion)}</main></body></html>", url)) == expected


@pytest.mark.parametrize("title, faq", [("Sık sorulan sorular", True), ("SSS", True), ("FAQ", True), ("Merak edilenler", True),
                                        ("Soru ve cevaplar", True), ("Ödeme İste", False), ("ATM'ye Transfer", False),
                                        ("Duyurular", False), ("Bilgi bankası", False)])
def test_faq_section_names(title, faq):
    assert bool(FAQ_SECTION.search(title)) is faq


def test_the_faqpage_suggestion_names_only_the_real_qa_pages(site):
    sealed, _, _, base = site
    [f] = findings(sealed.report, "str3.qa_no_faqpage")
    assert sorted(f["scope"]["urls"]) == [base + "/akordeon", base + "/sorular"]
    assert {r["qa_container"] for r in f["evidence"]["pages"]} == {"accordion", "faq_section"}


def test_a_saved_report_keeps_only_pages_with_an_faq_heading():
    from maya_audit.reassess_rules import _decisions_340
    pages = [{"url": "https://b.test/a", "analysis": {"headings": [{"level": 2, "text": "Ödeme İste"}]}},
             {"url": "https://b.test/b", "analysis": {"headings": [{"level": 2, "text": "Sıkça Sorulan Sorular"}]}}]
    f = {"id": "STR-3-x", "check_id": "STR-3", "rule_id": "str3.qa_no_faqpage", "severity": "Info", "notes": [],
         "title": "2 page(s) show questions and answers but have no FAQPage structured data",
         "scope": {"count": 2, "urls": ["https://b.test/a", "https://b.test/b"]},
         "evidence": {"pages": [{"url": "https://b.test/a", "questions": 4}, {"url": "https://b.test/b", "questions": 3}]}}
    report, affected, changes = {"crawl": {"pages": pages}, "checks": [{"check_id": "STR-3", "findings": [f]}]}, {}, []
    _decisions_340(report, affected, changes)
    [kept] = report["checks"][0]["findings"]
    assert kept["scope"]["urls"] == ["https://b.test/b"] and kept["title"].startswith("1 page(s)")
    assert kept["evidence"]["pages"][0]["qa_container"] == "faq_heading_on_page"
    assert changes == ["STR-3: FAQPage no longer suggested on 1 page(s) whose questions are headings or paragraphs in an "
                       "ordinary section, not an FAQ block (DECISIONS 340)"]


# ------------------------------------------------------------------ card 15: what to do with each redirecting item

def test_each_llms_txt_item_says_where_to_link_or_that_it_ends_on_an_error_page(site):
    _, data, _, base = site
    card = next(t for t in build_data.cards_for_appendix(data) if t.get("title") == "Küçük bağlantı ve etiket tutarsızlıklarını temizleyin")
    seen = card["url_notes"][base + "/llms.txt"]
    assert "/sss → /404?aspxerrorpath=/sss: hata sayfasına gidiyor (404): bağlantıyı kaldırın ya da doğru sayfanın adresini yazın" in seen
    assert "/nedir → /hakkimizda: bağlantıyı şu adrese verin: /hakkimizda" in seen


# ------------------------------------------------------------------ card 12: a page title is not a brand name

def test_an_organization_name_that_is_the_page_title_is_not_a_brand_name(site):
    sealed, _, _, _ = site
    for f in findings(sealed.report, "str5.names"):
        assert "Homepage" not in f["evidence"]["observed_values"]


def test_a_saved_report_drops_names_that_are_page_titles():
    from maya_audit.reassess_rules import _decisions_340
    home, en = "https://b.test/", "https://b.test/en/homepage"
    pages = [{"url": home, "analysis": {"title": "Bankanın güzeli | Banka"}}, {"url": en, "analysis": {"title": "Homepage"}}]
    variants = [{"name": "Banka", "pages": 90, "by_source": {"title suffix/prefix": 90}, "seen_as": [{"source": "title suffix/prefix", "value": "Banka", "url": home}]},
                {"name": "Bankanın güzeli | Banka", "pages": 1, "by_source": {"Organization name": 1, "WebSite name": 1},
                 "seen_as": [{"source": "Organization name", "value": "Bankanın güzeli | Banka", "url": home},
                             {"source": "WebSite name", "value": "Bankanın güzeli | Banka", "url": home}]},
                {"name": "Homepage", "pages": 1, "by_source": {"Organization name": 1}, "seen_as": [{"source": "Organization name", "value": "Homepage", "url": en}]}]
    f = {"id": "STR-5-x", "check_id": "STR-5", "rule_id": "str5.names", "severity": "S4", "title": "The brand is named 3 different ways",
         "scope": {"count": 2, "urls": [home, en]}, "evidence": {"variants": variants, "main_name": "Banka"}}
    report, changes = {"crawl": {"pages": pages}, "checks": [{"check_id": "STR-5", "findings": [f]}]}, []
    _decisions_340(report, {}, changes)
    assert report["checks"][0]["findings"] == []  # one name left: no finding
    assert "Bankanın güzeli | Banka, Homepage" in changes[0]



# ------------------------------------------------------------------ accuracy data

def test_the_second_review_is_kept_per_card_and_the_rule_summary_is_current():
    from pathlib import Path
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    review = json.loads((root / "docs/expert-reviews/enpara-fee70191.json").read_text(encoding="utf-8"))
    assert len(review["cards"]) == 15 and review["summary"] == {"wrong": 4, "correct": 9, "wording": 1, "incomplete": 1}
    assert review["follow_up"] == ["idx1.4xx.sitemap_only", "str3.qa_no_faqpage", "str5.names", "tseo1.head_closed_later",
                                   "tseo1.head_closed_lost"]
    spec = importlib.util.spec_from_file_location("expert_accuracy", root / "scripts/expert_accuracy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (root / "docs/expert-reviews/ACCURACY.md").read_text(encoding="utf-8") == mod.table(), \
        "run scripts/expert_accuracy.py"
