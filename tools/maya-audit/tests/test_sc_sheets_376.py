"""DECISIONS 376, phase 3: the client Ek's Search Console and AI sheets from a synthetic Maya summary and audit:
"Search Console özeti" (each source's period, totals marked as computed, "Veri yok" with its reason, the audit's own
counts), "Trafiğe göre öncelik", "SC sayfaları", "SC sorgular", "SC fırsatlar", "AI alıntılanan sayfalar", the Search
Console columns of "Sayfa bazında" and "Kilit sayfalar", the checklist's proposal beside the tool's result and the
totals before and after it, checklist SEO-069. Without Maya data none of these sheets exists. No client file."""
from __future__ import annotations

from maya_audit import checklist_maya, client_appendix, sc_sheets, xlsx
from maya_audit import client_selection as cs

from test_v03_client_report import SITE, finding, report

HOST = SITE.rstrip("/")
RECORD = {"version": "t", "decision": "PASS", "violations": [], "counts": {}, "hard": 0}


def summary(**over):
    s = {"version": 5, "domain": "shop.test", "origin": "https://shop.test", "brand_names": ["Shop"],
         "datasets": [{"dataset": "gsc-daily-stats", "file": "shop.test-gsc-daily-stats-2026-08-15-2026-11-13.csv",
                       "period": ["2026-08-15", "2026-11-13"], "rows": 88},
                      {"dataset": "gsc-top-pages", "file": "shop.test-gsc-top-pages-2026-08-15-2026-11-13.csv",
                       "period": ["2026-08-15", "2026-11-13"], "rows": 30},
                      {"dataset": "gsc-query-intents", "file": "shop.test-gsc-query-intents.csv", "period": None, "rows": 2},
                      {"dataset": "gsc-query-opportunities", "file": "shop.test-gsc-query-opportunities.csv", "period": None, "rows": 2},
                      {"dataset": "citation-mentions", "file": "shop.test-citation-mentions-2026-10-19-2026-11-18.csv",
                       "period": ["2026-10-19", "2026-11-18"], "rows": 50}],
         "gsc": {"page_source": "gsc-top-pages", "page_kind": "snapshot", "page_period": ["2026-08-15", "2026-11-13"],
                 "pages": {f"{HOST}/a": {"clicks": 900.0, "impressions": 9000.0, "ctr": 0.1, "position": 2.0},
                           f"{HOST}/gone": {"clicks": 40.0, "impressions": 800.0, "ctr": 0.05, "position": 6.0}},
                 "top_pages": {"weeks": ["2026-10-03", "2026-10-10"], "rows": {
                     f"{HOST}/a": {"week": "2026-10-10", "weeks_listed": 2}, f"{HOST}/gone": {"week": "2026-10-10", "weeks_listed": 1}}},
                 "totals": {"whole": {"period": ["2026-08-15", "2026-11-10"], "days": 88, "clicks": 1000, "impressions": 20000,
                                      "ctr": 0.05, "position": 7.1},
                            "last28": {"period": ["2026-10-14", "2026-11-10"], "days": 28, "clicks": 400, "impressions": 5000,
                                       "ctr": 0.08, "position": 7.6}},
                 "day_source": "gsc-daily-stats", "aio": {"columns": True, "days": 0, "period": None, "clicks": 0, "impressions": 0},
                 "intents": {"rows": {"shop": {"intent": "brand_search", "brand": True, "confidence": 1.0},
                                      "ucuz kahve": {"intent": "product_search", "brand": False, "confidence": 0.8}}},
                 "opportunities": {"period": ["2026-10-10", "2026-11-07"], "rows": [
                     {"query": "ucuz kahve", "type": "cannibalization", "pages": [f"{HOST}/a", f"{HOST}/gone"], "impressions": 1200.0,
                      "clicks": None, "ctr": None, "position": None, "score": 70.0, "period": ["2026-10-10", "2026-11-07"]},
                     {"query": "shop", "type": "cannibalization", "pages": [f"{HOST}/a", f"{HOST}/b"], "impressions": 5000.0,
                      "clicks": None, "ctr": None, "position": None, "score": 40.0, "period": ["2026-10-10", "2026-11-07"]}]}},
         "ai": {"period": ["2026-10-19", "2026-11-18"], "pages": {
             f"{HOST}/a": {"prompts": 3, "runs": 5, "by_provider": {"chatgpt": 4, "gemini": 2}},
             f"{HOST}/gone": {"prompts": 1, "runs": 1, "by_provider": {"perplexity": 1}}}}}
    s.update(over)
    return s


def _report():
    r = report([finding("STR-1-aaaaaaaa", "str1.shared", "S3", urls=[SITE + "/a"], check="STR-1")])
    r["crawl"] = {**(r.get("crawl") or {}), "start_url": SITE + "/", "started_at": "2026-11-11T09:00:00+00:00"}
    return r


def _book(s=None, lang="tr"):
    r = _report()
    files = client_appendix.build_files(cs.select(r), lang, report=r, text_check=dict(RECORD),
                                        maya={"summary": s if s is not None else summary(), "report": r})
    return xlsx.read(files["client"]), xlsx.read(files["client"], band=True), files["record"]


def test_the_six_sheets_follow_the_teams_order_and_the_text_check_passes():
    book, _, record = _book()
    names = list(book)
    for n in ("Search Console özeti", "Trafiğe göre öncelik", "SC sayfaları", "SC sorgular", "SC fırsatlar", "AI alıntılanan sayfalar"):
        assert n in names, n
    assert names.index("Search Console özeti") < names.index("Özet") < names.index("Trafiğe göre öncelik") < names.index("Sayfa bazında")
    assert names.index("Kontrol listesi") < names.index("SC sayfaları") < names.index("AI alıntılanan sayfalar") < names.index("Kapsam")
    assert not [v for v in record["violations"] if v["hard"]], record["violations"]  # RG-24 on the made-up card is soft


def test_the_summary_keeps_each_period_marks_computed_numbers_and_says_why_data_is_missing():
    book, banded, _ = _book()
    rows = {r[0]: r for r in book["Search Console özeti"] if r and r[0]}
    assert rows["gsc-daily-stats"][1] == "15 Ağustos – 13 Kasım 2026" and rows["citation-mentions"][1] == "19 Ekim – 18 Kasım 2026"
    assert any("son 28 gün (Maya dışa aktarımından hesaplandı)" in r[0] for r in book["Search Console özeti"] if r)
    assert rows["Cihaz"][1] == "Veri yok" and "gsc-search-performance eklenmedi" in rows["Cihaz"][2]
    assert rows["AI Overview"][1] == "Veri yok" and "boş" in rows["AI Overview"][2]
    assert rows["İndeks sağlığı (URL denetimi)"][1] == "Veri yok" and rows["GA4"][1] == "Veri yok"
    assert rows["Sorgu niyeti"][1] == "marka %50 · ürün araması %50"  # no code shown
    assert rows["Marka dışı yamyamlaşma sorgusu"][1] == "1"  # "shop" is the brand's own query
    assert banded["Search Console özeti"][1][1].endswith("Maya dışa aktarımından hesaplandı")
    assert "Maya dışa aktarımından hesaplandı" in "\n".join(" ".join(r) for r in book["Kapak"])


def test_page_sheets_say_the_audit_status_and_never_sum_snapshots():
    book, _, _ = _book()
    pages = {r[0]: r for r in book["SC sayfaları"][1:]}
    assert pages[f"{HOST}/a"][1:5] == ["900", "9000", "0.1", "2.0"] and pages[f"{HOST}/a"][5] == "2"
    assert book["SC sayfaları"][0][5] == "İlk listede (2 ölçümden)"
    assert pages[f"{HOST}/gone"][10] == "Okunmadı"
    assert book["SC sayfaları"][0][1] == "Tık (28 gün)"
    traffic = book["Trafiğe göre öncelik"]
    assert [r[0] for r in traffic[1:]] == [f"{HOST}/a"]  # every page with a problem (here one, read)
    assert traffic[0][-1] == "Denetimdeki durumu" and traffic[1][-1] == "Okundu, sorun var"
    ai = {r[0]: r for r in book["AI alıntılanan sayfalar"][1:]}
    assert ai[f"{HOST}/a"][1:4] == ["6", "chatgpt, gemini", "3"]
    opps = book["SC fırsatlar"]
    assert opps[1][:3] == ["ucuz kahve", "Marka dışı", "Yamyamlaşma: aynı sorguda birden çok sayfa"] and opps[1][7] == "/a"
    assert opps[1][8] == "10 Ekim – 7 Kasım 2026"
    queries = book["SC sorgular"]
    assert queries[0] == ["Sorgu", "Niyet (Maya)", "Marka mı?", "Güven (Maya)"]  # no gsc-top-queries: no clicks column
    assert queries[1][0].startswith("Tık ve gösterim: Veri yok (gsc-top-queries eklenmedi)")


def test_by_page_and_key_pages_get_green_search_console_columns():
    book, _, _ = _book()
    head = book["Sayfa bazında"][0]
    assert head[-8:] == ["SC tık (28 gün)", "SC gösterim (28 gün)", "SC CTR", "SC ort. sıra", "SC ilk listede (2 ölçümden)",
                         "SC ölçüm haftası", "AI alıntı sayısı", "Alıntılayan AI"]
    row = next(r for r in book["Sayfa bazında"][1:] if r[0] == f"{HOST}/a")
    assert row[-8:-6] == ["900", "9000"] and row[-1] == "chatgpt, gemini"


def test_without_maya_data_the_sheets_are_left_out():
    r = _report()
    book = xlsx.read(client_appendix.build(cs.select(r), "tr", report=r))
    assert not set(book) & set(sc_sheets.NAMES.values())
    assert sc_sheets.build(None, cs.select(r), [])["sheets"] == []


def test_the_checklist_keeps_the_tools_result_and_proposes_beside_it():
    book, _, _ = _book()
    rows = {r[0]: r for r in book["Kontrol listesi"] if r and r[0].startswith("SEO-")}
    head = book["Kontrol listesi"][0]
    sc = head.index("Search Console eki: önerilen sonuç")
    assert rows["SEO-069"][4] != rows["SEO-069"][sc] == "Sorun" and "«ucuz kahve»" in rows["SEO-069"][sc + 1]
    totals = book["Kontrol listesi özeti"]
    assert totals[-2][0] == "Search Console eki sonrası (öneri)" and totals[-1][0] == "Önceki (araç sonucu)"
    assert totals[-2][1] == totals[-1][1] == "165"


def test_seo_069_reads_only_non_brand_cannibalization():
    result, text, _ = checklist_maya.row("SEO-069", summary(), {}, "tr")
    assert result == "issue" and "1 marka dışı yamyamlaşma sorgusu" in text and "10 Ekim – 7 Kasım 2026" in text
    only_brand = summary()
    only_brand["gsc"]["opportunities"]["rows"] = only_brand["gsc"]["opportunities"]["rows"][1:]
    assert checklist_maya.row("SEO-069", only_brand, {}, "tr")[0] == "pass"
    assert checklist_maya.row("SEO-069", {"gsc": {}}, {}, "tr") is None


def test_a_label_or_fix_log_check_on_a_missing_column_is_no_evidence_and_a_short_row_is_an_empty_cell():
    from maya_audit import expert_labels, fix_log
    book = {"Kontrol listesi": [["ID", "Sonuç", "Search Console eki: önerilen sonuç"], ["SEO-001", "Geçti"],
                                ["SEO-002", "Sorun", "Geçti"]]}
    ctx = {"report": {"checks": []}, "cards": [], "book": book}
    found = {"id": "x", "kind": "must_find", "on": "row", "sheet": "Kontrol listesi",
             "column": "Search Console eki: önerilen sonuç", "regex": "Sorun"}
    assert expert_labels.check(found, ctx)["ok"] is False  # "Sorun" is in another column of the short row
    assert expert_labels.check({**found, "regex": "Geçti"}, ctx)["ok"] is True
    missing = {**found, "column": "Yok", "kind": "must_not_find"}
    assert expert_labels.check(missing, ctx)["ok"] is False and "no column" in expert_labels.check(missing, ctx)["seen"]
    assert fix_log.check_one("sheet_not", {"sheet": "Kontrol listesi", "column": "Yok", "regex": "x"}, ctx) is None
