"""DECISIONS 377 (the owner's review of the Enpara Ek, global rules): plain Turkish titles in "Yönetici özeti" and
"Aksiyon planı" (RG-31), a card's scope as its total with its parts, Topic Pulse labels that are no topic left out of
every competitor sheet, competitors in their own display form with Turkish casing (RG-32 on a combining dot), and
shares and rates as percentages. Synthetic data only."""
from __future__ import annotations

import io
import re
import zipfile

from maya_audit import client_appendix, ek_actions, ek_frame, maya_data, text_gate, xlsx

RECORD = {"version": "t", "decision": "PASS", "violations": [], "counts": {}, "hard": 0}


def _write(folder, name, header, rows):
    (folder / name).write_text(",".join(header) + "\n" + "".join(",".join(str(c) for c in r) + "\n" for r in rows), encoding="utf-8")


# ---------------------------------------------------------------- 1. titles

def test_search_console_actions_have_plain_turkish_titles():
    summary = {"brand_names": ["demo"], "gsc": {"intents": {"rows": {"demo kredi": {"brand": True}}}, "opportunities": {"rows": [
        {"query": "faizsiz kredi", "type": "cannibalization", "impressions": 188295.0},
        {"query": "demo kredi", "type": "cannibalization", "impressions": 999999.0},
        {"query": "kredi hesaplama", "type": "cannibalization", "impressions": 24685.0}]}}}
    assert ek_actions.sc_title("SEO-069", summary, None) == \
        "Aynı marka dışı sorguda birden fazla Demo sayfası yarışıyor; en belirgin örnek «faizsiz kredi»"
    assert ek_actions.sc_title("SEO-071", summary, None) == "Yüksek gösterim alan bazı sayfalarda tıklama oranı düşük"
    assert ek_actions.sc_title("SEO-999", summary, None, "12 sayfada sorun var. Ayrıntı") == \
        "Search Console verisi bir sorun gösteriyor: 12 sayfada sorun var"


def test_rg31_blocks_a_checklist_item_name_or_english_as_a_title():
    plan = {"name": "Aksiyon planı", "header": ["Aksiyon kimliği", "Konu"],
            "rows": [["S-01", "Cannibalization kanıt testi"], ["S-02", "CTR fırsat analizi"], ["T-01", "Head'i erken kapatan öğeyi taşıyın"]]}
    found = text_gate.title_checks([plan])
    assert [v["rule"] for v in found] == ["RG-31"] and "«Cannibalization kanıt testi»" in found[0]["message"]
    assert "«CTR fırsat analizi»" in found[0]["message"]
    summary = {"name": "Yönetici özeti", "header": ["#", "Bulgu"], "rows": [["1", "Traffic opportunity on key pages"],
                                                                             ["", "Açık konular (uzman onayı dışında kalan)"]]}
    assert [v["rule"] for v in text_gate.title_checks([summary])] == ["RG-31"]
    ok = {"name": "Yönetici özeti", "header": ["#", "Bulgu"], "rows": [["1", "Yüksek gösterim alan bazı sayfalarda tıklama oranı düşük"]]}
    assert text_gate.title_checks([ok]) == []


def test_an_unlinked_checklist_problem_says_what_was_found():
    checklist = {"name": "Kontrol listesi", "header": ["ID", "Grup", "Kontrol maddesi", "Öncelik", "Sonuç", "Kanıt", "Maya kuralı / kart"],
                 "rows": [["SEO-112", "11 · Hız ve Core Web Vitals", "INP p75", "P1", "Sorun", "INP p75 323 ms (iyileştirilmeli).", "PRF-3"]]}
    acts = ek_actions.actions(ek_actions.Book([checklist]), [], None, None, {})
    assert acts[0]["Konu"] == "INP p75 323 ms (iyileştirilmeli) · Hız ve Core Web Vitals"


# ---------------------------------------------------------------- 2. scope

def test_a_cards_scope_is_its_total_with_its_parts():
    assert client_appendix.scope_total("2 sayfa (+88 sayfa: Orta)", "Yüksek") == (90, "90 (2 Yüksek + 88 Orta)")
    assert client_appendix.scope_total("3 sayfa (+1 sayfa: Düşük, +2 sayfa: Orta)", "Yüksek") == (6, "6 (3 Yüksek + 1 Düşük + 2 Orta)")
    assert client_appendix.scope_total("en az 94 sayfa", "Orta") == (None, "en az 94 sayfa")
    summary = {"name": "Özet", "header": ["Kart", "Etkilenen adres"], "rows": [["1", "90 (2 Yüksek + 88 Orta)"]]}
    acts = ek_actions.actions(ek_actions.Book([summary]), [{"n": 1, "title": "Head", "finding_ids": [], "p_level": "P1"}], None, None, {})
    assert acts[0]["Kapsam (sayı)"] == 90 and acts[0]["Kapsam birimi"] == "etkilenen adres (2 Yüksek + 88 Orta) (Özet)"
    claims = [(0, "90", "Özet", "Kart", "1")]
    assert text_gate.with_file_checks(dict(RECORD), [summary, {"name": "Yönetici özeti", "header": ["#"], "rows": [],
                                                              "_claims": claims}], "tr")["decision"] == "PASS"


# ---------------------------------------------------------------- 3. topics, 4. names

def test_intent_brand_and_register_labels_are_no_topic_and_leaders_have_their_display_form(tmp_path):
    _write(tmp_path, "demo.test-topic-visibility-snapshots-2026-10-21-2026-11-20.csv",
           ["week_start", "topic", "total", "brand_rate", "top_competitor_name", "top_competitor_rate"],
           [["2026-11-16", "Niyet: İşlem rehberi", 10, 12.4, "garanti", 34.9], ["2026-11-16", "Branding", 10, 50, "qnb", 60],
            ["2026-11-16", "Ticari bankacılık", 10, 28.7, "i̇ş bankası", 56.8], ["2026-11-16", "Sigorta", 10, 17.7, "garanti", 33.5]])
    _write(tmp_path, "demo.test-competitor-mentions-daily-2026-10-21-2026-11-20.csv",
           ["date", "competitorKey", "displayName", "domain", "mentions", "sentimentWeightSum", "sentimentWeightedScoreSum"],
           [["2026-11-10", "isbankasi", "İş Bankası", "", 7495, 1, 1], ["2026-11-10", "garantibbva", "Garanti BBVA", "", 7059, 1, 1],
            ["2026-11-10", "garanti", "Garanti", "", 40, 1, 1], ["2026-11-10", "qnb", "QNB", "", 5408, 1, 1]])
    vis = maya_data.prepare([tmp_path], "https://www.demo.test/")["visibility"]
    assert [t["topic"] for t in vis["topics"]] == ["Sigorta", "Ticari bankacılık"]
    assert vis["not_topics"] == ["Branding", "Niyet: İşlem rehberi"]
    leaders = {t["topic"]: t["leader"] for t in vis["topics"]}
    assert leaders == {"Sigorta": "Garanti BBVA", "Ticari bankacılık": "İş Bankası"}
    assert maya_data.display_name("yapı kredi") == "Yapı Kredi" and maya_data.display_name("i̇ş bankası") == "İş Bankası"
    assert maya_data.topic_of("Niyet: Sorun çözme") is None and maya_data.topic_of("Branding") is None


def test_rg32_blocks_a_combining_dot_outside_an_address():
    bad = {"name": "Rakip - Konu", "header": ["Lider"], "rows": [["i̇ş bankası 57,3 → 56,8"]]}
    assert [v["rule"] for v in text_gate.combining_dot([bad])] == ["RG-32"]
    url = {"name": "Bulgu bazında", "header": ["Sayfa"], "rows": [[{"text": "https://shop.test/collections/i̇pek",
                                                                     "link": "https://shop.test/collections/i%CC%87pek"}]]}
    assert text_gate.combining_dot([url]) == []  # an address with a decomposed letter is a finding's evidence
    page = {"name": "Rakip - Konu", "header": ["Sayfa"], "rows": [["site.com/blogs/hangisi-sizin-i\u0307cin (12 koşu, 1 prompt)"]]}
    assert text_gate.combining_dot([page]) == []


# ---------------------------------------------------------------- 5. percentages

def test_shares_and_rates_are_shown_as_percentages_and_text_percents_in_turkish_form():
    sheet = {"name": "Rakip - Konu", "header": ["Konu", "Marka citation payı (koşu)", "CTR", "Fark (puan, son hafta)",
                                               "En çok kaynak gösterilen alan adları (prompt payı)"],
             "rows": [["Sigorta", 0.1759, 0.0647, 32.2, "garantibbva.com.tr (%100)"], ["Kredi", 0.3672, 0.1, 18.5, "x (%5)"]]}
    framed = ek_frame.percent_columns(sheet)
    assert framed["col_styles"] == {1: "percent", 2: "percent"}  # points (32.2) and text stay as they are
    data = xlsx.workbook([framed])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        styles, body = z.read("xl/styles.xml").decode(), z.read("xl/worksheets/sheet1.xml").decode()
    assert '<numFmt numFmtId="164" formatCode="0.0%"/>' in styles
    assert re.search(r'<c r="B2" s="11"><v>0.1759</v></c>', body) and '<c r="D2"><v>32.2</v></c>' in body
    from maya_audit import maya_sheets
    source = open(maya_sheets.__file__, encoding="utf-8").read()
    assert not re.search(r"\(\{round\(100 \* [^)]+\)\}%\)", source)  # never "(17%)" in Turkish text


def test_a_label_on_a_missing_sheet_is_red_whatever_its_kind():
    from maya_audit import expert_labels
    ctx = {"report": {"checks": []}, "cards": [], "book": {}}
    for kind in ("must_find", "must_not_find"):
        label = {"id": "x", "kind": kind, "on": "row", "sheet": "Rakip - Konu", "column": "Konu", "regex": "^Niyet"}
        assert expert_labels.check(label, ctx)["ok"] is False
