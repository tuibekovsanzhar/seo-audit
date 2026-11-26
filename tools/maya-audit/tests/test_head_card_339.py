"""DECISIONS 339: a card that joins findings of different severities, the head-closed-early card's words, and the Ek's
"Kapsam" and "Yöntem" lines (enpara fee70191: "High, 90 pages" for 2 pages that lose a noindex beside 88 that keep
canonical, hreflang and title in the head; Core Web Vitals "not assessed" with CrUX data; "İş önemi 1,0 until profiles").

Hand-written site: every page prints <div id="overlay"> inside <head>. /form carries <meta name="robots"
content="noindex"> after it (lost: High); /a, /b and /c carry only a description and og:title after it (Medium); the
homepage's head is clean. Offline: a loopback fake server.
"""
from __future__ import annotations

import json

import pytest

from fakeserver import Response
from maya_audit import client_appendix, client_selection, final
from maya_audit_web.runner import REPORT_JSON
from maya_audit_web.team_report import build_data
from test_m1_broken_links import audit
from test_review_fixes import TR
from test_firecrawl import no_lookups  # noqa: F401  (fixture)


@pytest.fixture(scope="module", autouse=True)
def _maturity_off(maturity_off):
    """DECISIONS 378: some example rules here were later found wrong by the SEO team; the subject is
    the head and brand-name cards' wording and DECISIONS 339's confirm reason."""
    yield


def head_page(path: str, after: str, links: str = "") -> Response:
    return Response(body=(f'<html lang="tr"><head><title>Sayfa {path}</title><link rel="canonical" href="{path}">'
                          f'<div id="overlay"></div>{after}</head><body><h1>Sayfa {path}</h1><p>{TR}</p>{links}'
                          '</body></html>'))


def routes() -> dict:
    later = '<meta name="description" content="Açıklama"><meta property="og:title" content="Başlık">'
    links = '<a href="/form">Başvuru</a> <a href="/a">A</a> <a href="/b">B</a> <a href="/c">C</a>'
    return {
        "/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
        "/sitemap.xml": Response(404, "", content_type="text/plain"),
        "/": Response(body=f'<html lang="tr"><head><title>Ana sayfa</title></head><body><h1>Ana sayfa</h1><p>{TR}</p>'
                           f'{links}</body></html>'),
        "/form": head_page("/form", '<meta name="robots" content="noindex">'),
        "/a": head_page("/a", later), "/b": head_page("/b", later), "/c": head_page("/c", later),
    }


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    outcome, base = audit(routes())
    sealed = final.seal(outcome)
    folder = tmp_path_factory.mktemp("audit") / "artifacts"
    folder.mkdir(parents=True)
    report = sealed.report
    (folder / REPORT_JSON).write_text(json.dumps(report), encoding="utf-8")
    data = build_data.build_from_files(folder / REPORT_JSON, "tr")[0]
    return report, sealed, data, base


def head_card(data):
    return next(t for t in data["todos"] if t["rule_id"] in ("tseo1.head_closed_lost", "tseo1.head_closed_later"))


def test_the_engine_splits_the_pages_that_lose_a_restricting_robots_tag(built):
    report, _, _, base = built
    heads = {f["rule_id"]: f for c in report["checks"] for f in c["findings"] if "head_closed" in (f.get("rule_id") or "")}
    assert heads["tseo1.head_closed_lost"]["severity"] == "S2" and heads["tseo1.head_closed_lost"]["scope"]["urls"] == [base + "/form"]
    assert heads["tseo1.head_closed_later"]["severity"] == "S3" and len(heads["tseo1.head_closed_later"]["scope"]["urls"]) == 3
    assert heads["tseo1.head_closed_lost"]["dedup_key"] == heads["tseo1.head_closed_later"]["dedup_key"]  # one cause, one card


def test_one_card_is_scored_and_counted_on_its_high_pages_only(built):
    report, sealed, _, base = built
    sel = client_selection.select(sealed.report, sealed.affected, {})
    [g] = [g for g in sel["groups"] if g["rule_id"] == "tseo1.head_closed_lost"]
    assert g["severity"] == "S2" and len(g["urls"]) == 4
    assert g["severity_pages"] == {"S2": 1, "S3": 3}
    assert [x["url"] for x in g["examples"]] == [base + "/form"]  # the example is a High page
    importance, _ = client_selection.grouping(sealed.report)
    home = int((importance.get(client_selection._home(sealed.report)) or {}).get("importance", client_selection.REACH_UNIT))
    read = client_selection.pages_read(sealed.report)
    assert g["reach"] == client_selection._reach([base + "/form"], importance, home, read)[0]
    assert g["reach"] < client_selection._reach(g["urls"], importance, home, read)[0]


def test_the_card_says_what_is_lost_what_stays_and_counts_each_severity(built):
    _, _, data, _ = built
    card = head_card(data)
    assert card["severity_label"] == "Yüksek"
    assert card["scope"] == "1 sayfa (+3 sayfa: Orta)"
    # DECISIONS 344: one element on every page is one template cause, said first; then what is lost
    assert card["why"] == ("Tüm 4 sayfada head'i aynı şablon öğesi kapatıyor: <div#overlay>. 1 sayfada robots (noindex) "
                           "head kırıldıktan sonra geliyor; Google bu kuralı uygulamayabilir.")
    assert "yok sayılır" not in card["why"]  # never the old "canonical, robots or hreflang are ignored"
    assert card["steps"].split("\n") == ["<div#overlay> öğesini <head>'den çıkarın (satır 1)",
                                         "Onu basan eklentiyi head etiketlerinden sonra yükleyin",
                                         "Search Console Adres Denetimi'nde robots (noindex) kuralını teyit edin"]
    assert card["verify"] == "Sayfa kaynağında tek <head> ve tek </head> olmalı; robots (noindex), <div#overlay> öğesinden önce gelmeli."
    prio = next(p for p in data["priorities"] if card["finding_ids"][0] in p["finding_ids"])
    assert prio["value"] == "1 sayfa (+3 sayfa: Orta)"
    assert prio["text"] == ("Tüm 4 sayfada head'i aynı şablon öğesi kapatıyor: <div#overlay>. Onu gövdeye taşıyın; robots "
                            "(noindex) ondan önce kalmalı.")  # DECISIONS 344


def test_a_medium_only_head_card_names_what_stays_and_what_comes_after(tmp_path):
    site = routes()
    site["/form"] = head_page("/form", '<meta name="robots" content="index, follow"><meta name="description" content="x">')
    outcome, base = audit(site)
    folder = tmp_path / "artifacts"
    folder.mkdir()
    (folder / REPORT_JSON).write_text(json.dumps(final.seal(outcome).report), encoding="utf-8")
    card = head_card(build_data.build_from_files(folder / REPORT_JSON, "en")[0])
    assert card["severity_label"] == "Medium" and card["scope"] == "4 pages"
    assert card["why"] == ("On all 4 pages the same template element ends the head: <div#overlay>. On 4 pages, the head keeps "
                           "canonical, title; only description, Open Graph, robots (index, follow) after the break, which "
                           "previews may miss.")
    assert "Search Console" not in card["steps"]


# ------------------------------------------------------------------ the Ek: Kapsam and Yöntem

def test_kapsam_says_core_web_vitals_came_from_crux_when_only_the_lab_test_was_not_run(built):
    _, sealed, _, _ = built
    report = json.loads(json.dumps(sealed.report))
    parts = {p["part"]: p for p in client_selection.not_assessed_parts(report)}
    assert "Core Web Vitals and Lighthouse metrics (optional)" in parts  # no CrUX data: as before
    report["crux"] = {"status": "assessed", "metrics": []}
    parts = {p["part"]: p for p in client_selection.not_assessed_parts(report)}
    assert "Core Web Vitals and Lighthouse metrics (optional)" not in parts
    assert parts[client_selection.LAB_PART]["checks"] == ["PRF-3"]
    from maya_audit_web import wording as w
    line = client_appendix.coverage_text({"kind": "not_assessed", **parts[client_selection.LAB_PART]}, "tr",
                                         lambda t: w.label(t, "tr")[0], lambda t: w.line(t, "tr")[0])
    assert line == ("Lighthouse laboratuvar metrikleri (isteğe bağlı): Laboratuvar testi yapılmadı (--pagespeed); Core Web "
                    "Vitals, Google'ın gerçek ziyaretçi verisinden (Chrome UX Report) değerlendirildi.")


def test_yontem_shows_the_business_type_and_page_type_weights_used(built):
    _, sealed, _, _ = built
    sel = client_selection.select(sealed.report, sealed.affected, {}, business="bankacilik")
    rows = dict(map(tuple, client_appendix.method_rows(sel, "tr")))
    assert rows["İş türü"] == "Bankacılık (seçildi)"
    assert rows["Sayfa türü ağırlığı"].startswith("Ana sayfa 100 · Destek 85 · Finansal ürün ve ürün listesi 70 · ")
    assert rows["Sayfa türü ağırlığı"].endswith("eşleşmeyen sayfa 25 · politika / yasal 15 · yardımcı sayfa 0")
    assert rows["İş önemi"].startswith("puanda 1,0 (çarpan değil); iş türü puana sayfa önemiyle girer: %50 sayfa türü")
    assert not any("profilleri gelene kadar" in v for v in rows.values())
    other = dict(map(tuple, client_appendix.method_rows(client_selection.select(sealed.report, sealed.affected, {},
                                                                                business="diger"), "en")))
    assert other["Business type"].startswith("Other: no business-type profile")
    assert list(other).index("Business relevance") < list(other).index("Priority score")


# ------------------------------------------------------------------ brand names only in structured data: "Teyit edin"

def _names(*variants):
    return {"id": "STR-5-x", "check_id": "STR-5", "rule_id": "str5.names", "severity": "S4", "confidence": "estimated",
            "title": "The brand is named 3 different ways", "scope": {"count": 2, "urls": ["https://b.test/"]},
            "evidence": {"variants": [{"name": n, "pages": 1, "by_source": s} for n, s in variants]}}


def test_brand_names_seen_only_in_structured_data_wait_for_a_person():
    # enpara fee70191: one name in every title; the other two only as an Organization name on one page each
    f = _names(("Enpara", {"title suffix/prefix": 91, "Organization name": 47}),
               ("Bankanın güzeli | Enpara", {"Organization name": 1, "WebSite name": 1}), ("Homepage", {"Organization name": 1}))
    assert client_selection.names_in_markup(f) and client_selection.confirm_reason(f) == "names_in_markup"


@pytest.mark.parametrize("second", [{"title suffix/prefix": 97}, {"og:site_name": 2, "Organization name": 1}])
def test_a_second_name_people_see_keeps_the_brand_card(second):
    # moodist: an English name in 97 titles; enpara 87f0425a: "Enpara.com" in titles too
    f = _names(("Moodist", {"Organization name": 144, "og:site_name": 141}), ("Moodist Hospital", second),
               ("Moodist Ekibi", {"Organization name": 63}))
    assert not client_selection.names_in_markup(f) and client_selection.confirm_reason(f) is None


# ------------------------------------------------------------------ note cards in the Ek

def test_a_note_card_gives_its_finding_rows_what_was_seen_and_its_other_addresses_rows():
    from maya_audit import page_rows
    llms = {"id": "ACC-8-1", "check_id": "ACC-8", "rule_id": "acc8.redirecting", "severity": "Info", "confidence": "verified",
            "title": "2 link(s) in llms.txt point to an address that redirects",
            "scope": {"kind": "sitewide", "count": 1, "urls": ["https://b.test/llms.txt"]}, "evidence": {}}
    sel = {"groups": [{"placement": "note", "members": [llms], "issue_type": "issue", "finding_ids": ["ACC-8-1"]}]}
    seen = "/sss → /404; /nedir → /hakkimizda"
    hygiene = {"n": 14, "title": "Küçük bağlantı ve etiket tutarsızlıklarını temizleyin", "severity": "Info",
               "finding_ids": ["ACC-8-1", "STR-10"], "all_urls": ["https://b.test/llms.txt", "https://b.test/form"],
               "url_notes": {"https://b.test/llms.txt": seen, "https://b.test/form": "Open Graph etiketleri var, twitter:card yok"}}
    questions = {"n": None, "appendix_only": True, "title": "Soru başlıklarını düzeltin", "severity": "Info",
                 "finding_ids": ["STR-2"], "all_urls": ["https://b.test/sss"], "url_notes": {"https://b.test/sss": "4 soru düz metin"}}
    rows = page_rows.finding_rows(sel, None, "tr", todos=[hygiene, questions])
    by = {(r["title"][:10], r["url"]): r for r in rows}
    assert by[("2 link(s) ", "https://b.test/llms.txt")]["value"] == seen
    assert by[("Küçük bağl", "https://b.test/form")]["value"] == "Open Graph etiketleri var, twitter:card yok"
    assert ("Küçük bağl", "https://b.test/llms.txt") not in by  # said once, on the finding's row
    assert by[("Soru başlı", "https://b.test/sss")]["value"] == "4 soru düz metin" and by[("Soru başlı", "https://b.test/sss")]["card"] is None
    _, cards = page_rows.card_of(sel, [hygiene, questions], "tr")
    assert [c["n"] for c in cards] == [14]  # the Ek-only note is not a card of the PDF
