"""DECISIONS 376, phase 1: the Ek as the team's full client file, its frame. Kapak first and the team's sheet order;
the Maya band above every header ("← Kapak" and the sheet's source with its own period); periods never merged;
the text check's RG-27, RG-28 and RG-30; the internal sheets in a team file; no engine line in the PDF. Synthetic
data only (no client file, no network)."""
from __future__ import annotations

import io
import re
import zipfile

import pytest

from maya_audit import client_appendix, ek_frame, text_gate, xlsx
from maya_audit import client_selection as cs

from test_v03_client_report import SITE, finding, report

RECORD = {"version": "t", "decision": "PASS", "violations": [], "counts": {}, "hard": 0}
SUMMARY = {"brand_names": ["Demo Bank"], "datasets": [
    {"dataset": "gsc-daily-stats", "file": "demo.test-gsc-daily-stats-2026-08-15-2026-11-13.csv",
     "period": ["2026-08-15", "2026-11-13"], "rows": 88},
    {"dataset": "citation-mentions", "file": "demo.test-citation-mentions-2026-10-19-2026-11-18.csv",
     "period": ["2026-10-19", "2026-11-18"], "rows": 1200},
    {"dataset": "prompts", "file": "demo.test-prompts.csv", "period": None, "rows": 40},
    {"dataset": "meta", "file": "demo.test-meta.json", "period": None, "rows": None}]}


def _report():
    r = report([finding("STR-1-aaaaaaaa", "str1.shared", "S4", urls=[SITE + "/a", SITE + "/b"], check="STR-1")])
    r["crawl"] = {**(r.get("crawl") or {}), "start_url": SITE + "/", "started_at": "2026-11-11T09:00:00+00:00"}
    return r


def _files(lang="tr", **kw):
    r = _report()
    return client_appendix.build_files(cs.select(r), lang, report=r, text_check=dict(RECORD), **kw)


# ---------------------------------------------------------------- the frame

def test_every_client_sheet_has_the_band_back_link_and_source_line_above_its_header():
    files = _files()
    banded = xlsx.read(files["client"], band=True)
    plain = xlsx.read(files["client"])
    links = xlsx.links(files["client"])
    assert list(plain)[0] == "Kapak"
    for name, rows in banded.items():
        if name == "Kapak":
            continue
        assert rows[0][0] == f"maya  ·  shop.test SEO analizi  ·  {name}"
        assert rows[1][0] == "← Kapak" and links[name]["A2"] == "#'Kapak'!A1"
        assert rows[1][1].startswith("Kaynak: ")
        assert rows[2] == plain[name][0]  # the header is the third row
    assert banded["Özet"][1][1] == "Kaynak: Maya Audit teknik denetimi · tarama 11 Kasım 2026"
    with zipfile.ZipFile(io.BytesIO(files["client"])) as z:
        at = list(plain).index("Bulgu bazında") + 1
        sheet = z.read(f"xl/worksheets/sheet{at}.xml").decode()
    assert 'ySplit="3" topLeftCell="A4"' in sheet and '<autoFilter ref="A3:' in sheet


def test_the_team_file_holds_the_text_check_and_the_fix_log_and_the_client_ek_neither():
    files = _files()
    client = xlsx.read(files["client"])
    assert not set(client) & set(ek_frame.INTERNAL)
    assert list(xlsx.read(files["team"])) == ["Kontrol raporu", "Düzeltme kaydı"]
    english = _files("en")
    assert "Text check" not in xlsx.read(english["client"]) and list(xlsx.read(english["team"])) == ["Text check"]


def test_sheets_follow_the_teams_order_and_mayas_own_data_sheets_come_last():
    made = [{"name": n, "header": ["x"], "rows": []} for n in
            ("Genel durum", "Nasıl okunur", "Özet", "Rakip - Konu", "Sayfa detay", "Bulgular", "Kapsam", "Kilit sayfalar")]
    assert [m["name"] for m in ek_frame.order(made)] == ["Nasıl okunur", "Özet", "Kilit sayfalar", "Bulgular",
                                                         "Rakip - Konu", "Kapsam", "Genel durum", "Sayfa detay"]


# ---------------------------------------------------------------- Kapak

def test_kapak_lists_every_dataset_with_its_own_period_and_never_merges_them():
    sel, r = cs.select(_report()), _report()
    made = [{"name": "Özet", "header": ["x"], "rows": []}, {"name": "Rakip - Konu", "header": ["x"], "rows": []}]
    rows = ek_frame.cover(sel, r, SUMMARY, made, "tr")["rows"]
    table = rows[[i for i, x in enumerate(rows) if x and x[0] == "Veri"][0] + 1:]
    periods = {x[0]: x[1] for x in table if len(x) > 1 and x[0] and x[0] != "Renk göstergesi"}
    assert periods["Teknik tarama"] == "11 Kasım 2026"
    assert periods["gsc-daily-stats"] == "15 Ağustos – 13 Kasım 2026"
    assert periods["citation-mentions"] == "19 Ekim – 18 Kasım 2026"
    assert periods["prompts"] == "dosyada dönem yok (anlık görüntü)"
    assert "meta" not in periods  # the export's meta file is not data with a period
    line = ek_frame.source_line("competitor_topics", r, SUMMARY, "tr")
    assert line == "Kaynak: Maya dışa aktarımı (citation-mentions 19 Ekim – 18 Kasım 2026; prompts)"
    assert ek_frame.source_line("summary", r, SUMMARY, "tr", computed=True).endswith(" · Maya dışa aktarımından hesaplandı")


def test_kapak_has_scope_sources_legend_and_a_linked_guide_to_every_sheet():
    files = _files()
    book, links = xlsx.read(files["client"]), xlsx.links(files["client"])
    kapak = book["Kapak"]
    text = "\n".join(" | ".join(r) for r in kapak)
    for part in ("Ne kapsanıyor?", "Ne kapsanmıyor?", "Kaynak dosyalar", "Ölçüm dönemleri (toplanmaz, birleştirilmez)",
                 "Renk göstergesi", "Uzman / marka girişi", "Sekme rehberi (adına tıklayın)", "GA4 verisi yok",
                 "Maya verisi eklenmedi"):
        assert part in text, part
    guide = [v for v in links["Kapak"].values()]
    assert {f"#'{n}'!A3" for n in book} <= set(guide)  # every sheet, Kapak too: its header row, under the band


@pytest.mark.parametrize("decided,want", [
    ([], "Uzman teyidi gereken madde yok"),
    ([True, False, False], "Uzman teyidi bekliyor: «Uzman teyidi» sekmesindeki 2 maddenin kararı verilmedi"),
    ([True, True], "SEO uzmanı değerlendirmesinden geçmiştir (19 Kasım 2026)")])
def test_kapak_says_reviewed_only_when_every_expert_row_has_a_decision(decided, want):
    assert ek_frame.review_line(decided, "2026-11-19", "tr") == want


def test_a_blocked_check_marks_the_client_ek_a_draft_on_its_cover():
    r = _report()
    blocked = {**RECORD, "decision": "BLOCKED", "violations": [text_gate.violation("RG-18", "x", hard=True)], "hard": 1}
    files = client_appendix.build_files(cs.select(r), "tr", report=r, text_check=blocked)
    assert xlsx.read(files["client"], band=True)["Kapak"][1][0].startswith("TASLAK · metin kontrolü")


# ---------------------------------------------------------------- RG-27, RG-28, RG-30

def _sheet(name, header, rows, **kw):
    return {"name": name, "header": header, "rows": rows, **kw}


def test_rg27_one_count_stated_differently_blocks():
    made = [_sheet("Kapak", ["x"], [], _counts={"pages_read": (175, "Kapak")}),
            _sheet("Search Console özeti", ["x"], [], _counts={"pages_read": (126, "Search Console özeti")})]
    out = text_gate.with_file_checks(dict(RECORD), made, "tr")
    assert out["decision"] == "BLOCKED" and [v["rule"] for v in out["violations"]] == ["RG-27"]
    same = [made[0], _sheet("B", ["x"], [], _counts={"pages_read": (175, "B")})]
    assert text_gate.with_file_checks(dict(RECORD), same, "tr")["decision"] == "PASS"


def test_rg28_an_id_or_a_check_name_in_an_id_column_that_findings_does_not_list_blocks():
    found = _sheet("Bulgular", ["Bulgu kimliği"], [["STR-1-aaaaaaaa"]])
    ok = _sheet("Bulgu bazında", ["Sorun", "Bulgu kimliği"], [["x", "STR-1-aaaaaaaa"], ["y", ""]])
    assert text_gate.with_file_checks(dict(RECORD), [found, ok], "tr")["decision"] == "PASS"
    bad = _sheet("Bulgu bazında", ["Sorun", "Bulgu kimliği"], [["x", "ACC-8-66d7edcf · ACC-8 · IDX-3"]])
    out = text_gate.with_file_checks(dict(RECORD), [found, bad], "tr")
    assert [v["rule"] for v in out["violations"]] == ["RG-28"] and "ACC-8" in out["violations"][0]["message"]


def test_rg30_a_link_to_a_missing_sheet_or_past_the_last_row_blocks():
    target = _sheet("Bulgu bazında", ["a"], [["1"], ["2"]])
    good = _sheet("Özet", ["a"], [[{"text": "git", "location": "'Bulgu bazında'!A3"}]])
    assert text_gate.with_file_checks(dict(RECORD), [target, good], "tr")["decision"] == "PASS"
    for loc in ("'Bulgu bazında'!A4", "'Yok'!A1"):
        bad = _sheet("Özet", ["a"], [[{"text": "git", "location": loc}]])
        out = text_gate.with_file_checks(dict(RECORD), [target, bad], "tr")
        assert [v["rule"] for v in out["violations"]] == ["RG-30"], loc


def test_a_note_cards_observation_rows_carry_no_check_name_as_a_finding_id():
    from maya_audit import page_rows
    todos = [{"n": 14, "title": "Küçük tutarsızlıklar", "severity": "Info", "finding_ids": ["ACC-8", "STR-10"],
              "all_urls": [SITE + "/a"], "url_notes": {SITE + "/a": "twitter:card yok"}, "steps": "Etiketi ekleyin"}]
    rows = [r for r in page_rows.finding_rows(cs.select(_report()), None, "tr", todos=todos) if r["card"] == 14]
    assert rows and all(r["finding_id"] == "" and r["check_id"] == "ACC-8 · STR-10" for r in rows)
    assert page_rows.card_pages(rows, 14)[0]["finding_ids"] == ["ACC-8 · STR-10"]
    assert client_appendix._finding_or_blank("IDX-6") == "" and client_appendix._finding_or_blank("IDX-6-0a1b2c3d") == "IDX-6-0a1b2c3d"


# ---------------------------------------------------------------- the xlsx writer

def test_links_into_a_banded_sheet_move_down_with_it_and_dropdowns_too():
    data = xlsx.workbook([
        {"name": "A", "header": ["x"], "rows": [[{"text": "go", "location": "'B'!A3"}]], "band": [["t"], ["n"]]},
        {"name": "B", "header": ["y"], "rows": [["1"], ["2"]], "band": [["t"], ["n"]], "col_styles": {1: "input"},
         "validations": [{"ref": "B2:B3", "list": ["Evet", "Hayır"]}]}])
    assert xlsx.links(data)["A"]["A4"] == "#'B'!A5"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        b = z.read("xl/worksheets/sheet2.xml").decode()
    assert 'sqref="B4:B5"' in b and re.search(r'<c r="B4" s="9"/>', b)  # an empty input cell keeps its colour
    assert xlsx.read(data)["B"] == [["y"], ["1", ""], ["2", ""]]


# ---------------------------------------------------------------- the PDF

@pytest.mark.parametrize("lang", ["tr", "en"])
def test_no_pdf_line_says_the_engine_version_or_the_audit_id(tmp_path, lang):
    from test_team_report import built, synthetic, visible_strings
    data = built(tmp_path, synthetic([("STR-1", "str1.shared")]), lang)
    shown = [v for _, v in visible_strings(data)]
    assert not [v for v in shown if re.search(r"Maya Audit \d+\.\d+\.\d+ · (denetim|audit) ", v)]
    assert not [v for v in shown if v in ("Motor:", "Engine:")]
