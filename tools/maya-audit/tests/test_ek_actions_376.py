"""DECISIONS 376, phase 4: the client Ek's action sheets from a synthetic audit: "Yönetici özeti", "Aksiyon planı" (T-
per card; S- per checklist item Search Console data turns into a problem), "Uzman teyidi", "Sayfa grupları", "Konum
dizini"; every link lands on its row; expert columns empty with dropdowns; Kapak's expert line from "Uzman teyidi";
RG-29; each card's page found in a printed PDF (a local headless browser). No client file, no network."""
from __future__ import annotations

import pytest

from maya_audit import client_appendix, ek_actions, text_gate, xlsx
from maya_audit import client_selection as cs

from test_v03_client_report import SITE, finding, report

RECORD = {"version": "t", "decision": "PASS", "violations": [], "counts": {}, "hard": 0}


def _report():
    shared = finding("STR-1-aaaaaaaa", "str1.shared", "S3", urls=[SITE + "/blog/a", SITE + "/blog/b", SITE + "/kredi"], check="STR-1")
    check = finding("STR-4-bbbbbbbb", "str4.mismatch", "S3", urls=[SITE + "/kredi"], check="STR-4")
    check["confidence"] = "unverified"
    r = report([shared, check])
    r["crawl"] = {**(r.get("crawl") or {}), "start_url": SITE + "/", "started_at": "2026-11-11T09:00:00+00:00"}
    return r


TODOS = [{"n": 1, "title": "Ortak başlıkları ayırın", "severity": "S3", "issue_type": "issue", "owner": "İçerik",
          "effort": "Küçük", "p_level": "P2", "finding_ids": ["STR-1-aaaaaaaa"], "all_urls": [],
          "why": "Aynı başlık arama sonucunda sayfaları ayırt ettirmez.", "verify": "Sayfaları açıp başlıklara bakın."}]


def _files(confirmations=None, pdf=None):
    r = _report()
    return client_appendix.build_files(cs.select(r, None, confirmations or {}), "tr", report=r, todos=TODOS,
                                       text_check=dict(RECORD), pdf=pdf)


def test_the_action_sheets_come_after_kapak_in_the_teams_order():
    book = xlsx.read(_files()["client"])
    assert list(book)[:7] == ["Kapak", "Yönetici özeti", "Aksiyon planı", "Uzman teyidi", "Sayfa grupları", "Konum dizini",
                              "Nasıl okunur"]


def test_a_card_is_an_action_with_its_evidence_rows_and_empty_expert_columns():
    files = _files()
    book, links = xlsx.read(files["client"]), xlsx.links(files["client"])
    plan = book["Aksiyon planı"]
    assert plan[0] == ek_actions.ACTION_COLS and len(plan[0]) == 30
    t1 = dict(zip(plan[0], plan[1]))
    assert t1["Aksiyon kimliği"] == "T-01" and t1["Kaynak önceliği"] == "P2" and t1["Kaynak sorumlu"] == "İçerik"
    assert t1["İş açısından gerekçe"].startswith("Aynı başlık") and t1["Doğrulama yöntemi"].startswith("Sayfaları açıp")
    assert t1["Kaynak bulgu kimlikleri"] == "STR-1-aaaaaaaa" and t1["Benzersiz URL"] == "3"
    assert all(not t1[c] for c in ek_actions.INPUT_COLS)
    assert t1["Kitapçık sayfası (PDF)"] == "PDF oluşturulmadı"
    # the evidence link opens the card's first row of "Bulgu bazında", and its text names that Excel row
    col = plan[0].index("Kanıt")
    ref = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[col] + "4"
    target = links["Aksiyon planı"][ref]
    row = int(target.rsplit("A", 1)[1])
    found = book["Bulgu bazında"]
    assert found[row - 3][found[0].index("Kart")] == "1" and t1["Kanıt"] == f"Bulgu bazında › satır {row}"
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(files["client"])) as z:
        sheet = z.read("xl/worksheets/sheet3.xml").decode()
    assert '<formula1>"Onaylandı,Değiştirilmeli,Reddedildi"</formula1>' in sheet and ' s="9"' in sheet


def test_uzman_teyidi_lists_the_waiting_finding_and_kapak_follows_its_decisions():
    book = xlsx.read(_files()["client"])
    rows = book["Uzman teyidi"]
    assert rows[1][:3] == ["Bulgu (Teyit edin)", "STR-4-bbbbbbbb", "STR-4"] and (rows[1] + [""] * 14)[12] == ""
    assert rows[1][6] == "kontrol gerçek sitelerde doğrulanmadı"  # the reason in words, never a code
    assert xlsx.read(_files()["client"], band=True)["Kapak"][1][0].startswith("Uzman teyidi bekliyor: «Uzman teyidi» sekmesindeki 1 maddenin")
    done = _files({"STR-4-bbbbbbbb": {"result": "confirmed", "by": "Uzman", "date": "2026-11-19"}})
    assert xlsx.read(done["client"])["Uzman teyidi"][1][12] == "Onaylandı"
    assert xlsx.read(done["client"], band=True)["Kapak"][1][0] == "SEO uzmanı değerlendirmesinden geçmiştir (19 Kasım 2026)"


def test_the_executive_summary_takes_each_number_from_its_row_and_rg29_catches_a_wrong_one():
    files = _files()
    assert not [v for v in files["record"]["violations"] if v["rule"] in ("RG-27", "RG-28", "RG-29", "RG-30")]
    summary = xlsx.read(files["client"])["Yönetici özeti"]
    assert summary[1][3] == "T-01" and "Kart 1 · P2" in summary[1][2]
    made = [{"name": "Özet", "header": ["Kart", "Etkilenen adres"], "rows": [["1", "3"]]},
            {"name": "Yönetici özeti", "header": ["#"], "rows": [], "_claims": [(0, "4", "Özet", "Kart", "1")]}]
    out = text_gate.with_file_checks(dict(RECORD), made, "tr")
    assert [v["rule"] for v in out["violations"]] == ["RG-29"]
    made[1]["_claims"] = [(0, "3", "Özet", "Kart", "1")]
    assert text_gate.with_file_checks(dict(RECORD), made, "tr")["decision"] == "PASS"


def test_page_groups_and_the_location_index_point_at_the_actions_rows():
    book = xlsx.read(_files()["client"])
    groups = book["Sayfa grupları"]
    assert groups[1][:3] == ["/blog", "T-01", "2"] and groups[2][3] == SITE + "/blog/a"
    where = book["Konum dizini"]
    assert where[1][:3] == ["T-01", "Ortak başlıkları ayırın", "Aksiyon planı › satır 4"]


def test_rg28_leaves_checklist_ids_and_sheet_references_alone():
    made = [{"name": "Bulgular", "header": ["Bulgu kimliği"], "rows": [["STR-1-aaaaaaaa"]]},
            {"name": "Aksiyon planı", "header": ["Kaynak bulgu kimlikleri"], "rows": [["SEO-071"], ["Rakip - Konu satır 3"]]}]
    assert text_gate.with_file_checks(dict(RECORD), made, "tr")["decision"] == "PASS"


def test_each_cards_page_is_read_from_the_printed_pdf():
    html = ("<html><body><h2>Özet</h2><p>01 Ortak başlıkları ayırın STR-1-aaaaaaaa</p>"
            "<div style='page-break-before:always'><h3>01 Ortak başlıkları ayırın</h3><p>Orta Sorun P2</p></div></body></html>")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.set_content(html)
            pdf = page.pdf()
            browser.close()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"a local headless browser is needed for this test (python -m playwright install chromium): {exc}")
    assert ek_actions.pdf_pages(pdf, TODOS) == {1: 2}  # page 1 lists the card with its finding ID: not its page
    book = xlsx.read(_files(pdf=pdf)["client"])
    assert book["Konum dizini"][1][5] == "2"
    assert ek_actions.pdf_pages(None, TODOS) == {}


def test_a_checklist_problem_no_card_covers_is_an_action_of_its_own():
    checklist = {"name": "Kontrol listesi", "header": ["ID", "Grup", "Kontrol maddesi", "Öncelik", "Sonuç", "Kanıt", "Maya kuralı / kart"],
                 "rows": [["SEO-112", "11 · Hız", "INP p75", "P1", "Sorun", "INP p75 323 ms", "PRF-3 · CrUX"],
                          ["SEO-020", "2 · Dizin", "Başlık", "P2", "Sorun", "...", "Kart 1"],
                          ["SEO-030", "2 · Dizin", "Açıklama", "P2", "Geçti", "...", ""]]}
    acts = ek_actions.actions(ek_actions.Book([checklist]), TODOS, _report(), None, {})
    extra = [a for a in acts if a["Grup"] == "Teknik SEO (karta bağlı değil)"]
    assert len(extra) == 1 and extra[0]["Aksiyon kimliği"] == "T-02" and extra[0]["Kaynak bulgu kimlikleri"] == "SEO-112"
    assert extra[0]["Çapraz bağlantı / not"].endswith("(Maya: PRF-3 · CrUX)")
    assert extra[0]["Kanıt"]["location"] == "'Kontrol listesi'!A2" and extra[0]["Kaynak önceliği"] == "P1 (kontrol listesi)"
