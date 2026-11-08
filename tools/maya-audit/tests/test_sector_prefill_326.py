"""DECISIONS 326: every row of the "Sektör audit" XLSX has Yaygınlık and Efor, so changing "Durum" to Hatalı or Kısmen
Uygun gives a score and a level at once; a note on the Metodoloji sheet says they can be edited. Offline: in-memory
reports (the recalculation in a spreadsheet application is checked by hand, IMPLEMENTATION-STATUS)."""
from __future__ import annotations

from maya_audit import client_selection as cs, sector_audit, xlsx
from test_sector_method_324 import _sector_report
from test_v03_client_report import SITE, finding


def _book(monkeypatch, findings=()):
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    r = _sector_report()
    if findings:
        r["checks"][0]["findings"] = list(findings)
        r["findings_in_priority_order"] = [f["id"] for f in findings]
    sel = cs.select(r, None, {}, business="eticaret")
    return sector_audit.evaluate(r, sel, None, "eticaret"), xlsx.read(sector_audit.build(r, sel, None, "eticaret"))


def test_every_row_has_spread_and_effort(monkeypatch):
    res, book = _book(monkeypatch)
    for row in res["core"] + res["sec"]:
        assert row["spread"] in (1, 2, 3, 4, 5) and row["effort"] in (1, 2, 3, 4, 5), row["id"]
    for sheet in ("Ortak SEO Kontrolleri", "Sektörel SEO Kontrolleri"):
        head, *body = book[sheet]
        s, e = head.index("Yaygınlık (1-5)"), head.index("Efor (1-5)")
        assert all(r[s] and r[e] for r in body), sheet


def test_a_uygun_row_changed_to_hatali_scores_at_once(monkeypatch):
    res, book = _book(monkeypatch)
    row = next(r for r in res["core"] if r["id"] == "CORE-001")
    assert row["durum"] == "Uygun" and row["spread"] == 1
    head, *body = book["Ortak SEO Kontrolleri"]
    cells = next(r for r in body if r[0] == "CORE-001")
    assert cells[head.index("Öncelik Skoru")] == "0" and cells[head.index("Öncelik")] == "Yok"  # the team's own "Uygun"
    # what the sheet's formula gives once a teammate writes "Hatalı" (the same function fills the cached values)
    score = sector_audit._score(row["impact"], None, row["spread"], row["effort"], "Hatalı")
    assert score == round(20 * row["impact"] * row["spread"] * 1 / row["effort"], 1) and score > 0
    assert sector_audit._level(score) in ("P0", "P1", "P2", "P3")
    assert sector_audit._score(row["impact"], None, row["spread"], row["effort"], "Kısmen Uygun") == round(score / 2, 1)
    assert sector_audit._score(row["impact"], None, row["spread"], row["effort"], "Kontrol Edilmedi") == ""


def test_spread_is_the_measured_one_when_a_finding_gives_it(monkeypatch):
    estimated = finding("STR-1-e", "str1.shared", "S3", "estimated", urls=[SITE + "/kategori/a", SITE + "/kategori/b"], check="STR-1")
    res, _ = _book(monkeypatch, [estimated])
    row = next(r for r in res["core"] if r["id"] == "CORE-023")
    # estimated: no Durum, but its measured spread is kept: 2 of the 4 pages read (50%) is 4 on the method's scale
    assert row["durum"] == "Kontrol Edilmedi" and row["spread"] == 4
    untouched = next(r for r in res["core"] if r["id"] == "CORE-028")
    assert untouched["spread"] == 1 and untouched["effort"] == 3  # nothing measured: 1; no rule: 3


def test_effort_is_the_rules_default_else_three():
    core = {r["id"]: r for r in sector_audit.method()["core"]}
    assert sector_audit.default_effort(core["CORE-028"]) == 3  # no rule: 3
    assert sector_audit.default_effort(core["CORE-001"]) in (1, 3, 4)
    assert sector_audit.default_effort({"rules": ["acc2.blocks"]}) == sector_audit.default_effort({"rules": ["ACC-2"]})


def test_the_metodoloji_sheet_says_the_values_can_be_edited(monkeypatch):
    _, book = _book(monkeypatch)
    last = book["Metodoloji"][-1]
    assert last[0] == "Ön doldurulan değerler (Maya)" and "düzenlenebilir" in last[1]
    assert book["Metodoloji"][21][:2] == ["1", "1"]  # the VLOOKUP range A22:B27 has not moved
