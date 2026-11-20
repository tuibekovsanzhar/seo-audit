"""DECISIONS 376, phase 5: "Rakip yöntem notları" beside the competitor sheets and "Kaynak eşlemesi" (each client
sheet's source and period, as its band says). Synthetic data only."""
from __future__ import annotations

from maya_audit import client_appendix, ek_sources, xlsx
from maya_audit import client_selection as cs

from test_v03_client_report import SITE, finding, report


def test_the_notes_come_only_with_a_competitor_sheet_and_take_its_method_lines():
    method = {"name": "Yöntem", "header": ["Bileşen", "Değer"], "rows": [["Rakip konuları", "prompt'lar tek konuya atandı"],
                                                                          ["Öncelik puanı", "önem x güven"]]}
    coverage = {"name": "Kapsam", "header": ["Tür", "Açıklama", "Kontroller"],
                "rows": [["Maya verisi", "Rakip sayfaları: konu başına en çok 3 dış sayfa", ""], ["Maya verisi", "GA4 yok", ""]]}
    assert ek_sources.notes_sheet([method, coverage]) is None
    notes = ek_sources.notes_sheet([method, coverage, {"name": "Rakip - Konu", "header": ["x"], "rows": [], "_datasets": ["prompts"]}])
    texts = [r[1] for r in notes["rows"]]
    assert notes["rows"][0] == ["Yöntem › Rakip konuları", "prompt'lar tek konuya atandı"]
    assert "Rakip sayfaları: konu başına en çok 3 dış sayfa" in texts and "GA4 yok" not in texts
    assert "önem x güven" not in texts and notes["_datasets"] == ["prompts"]


def test_the_source_map_lists_every_sheet_with_its_band_source_and_kapak_links_to_it():
    r = report([finding("STR-1-aaaaaaaa", "str1.shared", "S3", urls=[SITE + "/a"], check="STR-1")])
    r["crawl"] = {**(r.get("crawl") or {}), "start_url": SITE + "/", "started_at": "2026-11-11T09:00:00+00:00"}
    data = client_appendix.build(cs.select(r), "tr", report=r)
    book, banded = xlsx.read(data), xlsx.read(data, band=True)
    rows = {x[0]: x for x in book["Kaynak eşlemesi"][1:]}
    assert set(book) <= set(rows) | {"Kaynak eşlemesi"}
    assert rows["Özet"][1] == banded["Özet"][1][1].removeprefix("Kaynak: ") == "Maya Audit teknik denetimi · tarama 11 Kasım 2026"
    assert rows["Kapak"][1] == "Maya Audit (bu dosyanın kendisi)"
    assert list(book).index("Kaynak eşlemesi") == list(book).index("Yöntem") + 1
    assert "Kaynak eşlemesi" in [x[1] for x in book["Kapak"] if len(x) > 1]
