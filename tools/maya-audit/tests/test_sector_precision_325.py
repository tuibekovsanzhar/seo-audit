"""DECISIONS 325: the "Sektör audit" XLSX precision pass. A finding sets a team check's Durum only where it answers that
check (each rule in at most one common row; one finding, one sector row per page type); only measured or confirmed
findings set a Durum, and a valid certificate is "Hatalı" only at High; host-level findings count host names; "Uygun"
says what was checked on how many pages; every problem card has a P level. Offline: in-memory reports."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from maya_audit import client_selection as cs, priority_levels as pl, sector_audit
from test_sector_method_324 import CATEGORY, PAGES, _ctx, _group, _sector_report
from test_v03_client_report import SITE, finding


@pytest.fixture(scope="module", autouse=True)
def _maturity_off(maturity_off):
    """DECISIONS 378: some example rules here were later found wrong by the SEO team; the subject is
    the sector audit's rows."""
    yield


ROOT = Path(__file__).resolve().parents[1]


def _rule_ids() -> list[tuple[str, str]]:
    rules = json.loads((ROOT / "maya_audit" / "rule_ids.json").read_text(encoding="utf-8"))["rules"]
    return sorted({(check, r[0]) for check, rows in rules.items() for r in rows})


def test_each_rule_marks_at_most_one_common_row():
    core = sector_audit.method()["core"]
    for check, rule in _rule_ids():
        rows = [r["id"] for r in core if sector_audit._matches({"rule_id": rule, "check_id": check}, r["rules"])]
        assert len(rows) <= 1, (rule, rows)
    where = {rule: next((r["id"] for r in core if sector_audit._matches({"rule_id": rule, "check_id": check}, r["rules"])), None)
             for check, rule in _rule_ids()}
    assert where["idx2.expires"] == "CORE-041" and where["idx2.no_redirect.hosts"] == "CORE-008"
    assert where["str7.placeholder"] == "CORE-026" and where["str7.over_100kb"] == "CORE-016"
    assert where["str5.names"] == "CORE-036" and where["str9.lang_mismatch"] == "CORE-027"
    assert where["idx5.stamped"] == "CORE-002" and where["idx7.orphan"] == "CORE-018"
    assert where["acc9.bot_protection"] is None and where["acc6.scope"] is None  # Maya blocked / AI crawlers: no SEO row


def test_rule_ids_match_exactly_never_by_a_shared_start():
    assert not sector_audit._matches({"rule_id": "acc3.noindex_utility", "check_id": "ACC-3"}, ["acc3.noindex"])
    assert sector_audit._matches({"rule_id": "acc2.blocks.sample", "check_id": "ACC-2"}, ["acc2.blocks"])
    assert sector_audit._matches({"rule_id": "idx4.chain", "check_id": "IDX-4"}, ["IDX-4"])


def _evaluate(findings, confirmations=None):
    r = _sector_report()
    r["checks"][0]["findings"] = findings
    r["findings_in_priority_order"] = [f["id"] for f in findings]
    r["checks"] += [{"check_id": c, "status": "findings", "findings": []} for c in ("IDX-2", "STR-7", "STR-3", "IDX-8", "IDX-6")]
    sel = cs.select(r, None, confirmations or {}, business="eticaret")
    res = sector_audit.evaluate(r, sel, None, "eticaret")
    return {row["id"]: row for row in res["core"] + [x for x in res["sec"] if not x.get("_other")]}


def _cert(severity, days):
    f = finding("IDX-2-c", "idx2.expires", severity, urls=["https://shop.test/", "https://www.shop.test/"], check="IDX-2")
    f["evidence"] = {"hosts": [{"host": h, "valid": True, "not_after": "2026-12-04T00:00:00+00:00", "days_left": days}
                               for h in ("shop.test", "www.shop.test")]}
    return f


def test_a_valid_certificate_is_partly_compliant_until_it_is_high(monkeypatch):
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    medium = _evaluate([_cert("S3", 30)])
    assert medium["CORE-041"]["durum"] == "Kısmen Uygun"
    assert medium["CORE-008"]["durum"] != "Hatalı" and "idx2.expires" not in medium["CORE-008"]["reason"]
    assert "(2 alan adı)" in medium["CORE-041"]["evidence"] and "sayfa)" not in medium["CORE-041"]["evidence"]
    assert medium["CORE-041"]["spread"] == 5  # a host-level finding is site-wide
    assert _evaluate([_cert("S2", 9)])["CORE-041"]["durum"] == "Hatalı"


def test_placeholder_alt_text_answers_the_alt_row_not_image_size(monkeypatch):
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    rows = _evaluate([finding("STR-7-p", "str7.placeholder", "S4", urls=[SITE + "/"], check="STR-7")])
    assert rows["CORE-026"]["durum"] == "Kısmen Uygun"
    assert rows["CORE-016"]["durum"] == "Kontrol Edilmedi" and "str7.placeholder" not in rows["CORE-016"]["reason"]


def test_an_estimated_finding_leaves_its_row_unchecked_and_marks_nothing_else(monkeypatch):
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    names = finding("STR-5-n", "str5.names", "S4", "estimated", urls=[SITE + "/"], check="STR-5")
    rows = _evaluate([names])
    assert rows["CORE-036"]["durum"] == "Kontrol Edilmedi" and rows["CORE-036"]["reason"].startswith("Tahmini bulgu")
    assert "str5.names" not in rows["CORE-038"]["reason"] + rows["CORE-040"]["reason"]
    high = finding("STR-1-e", "str1.shared", "S2", "estimated", urls=[SITE + "/kategori/a"], check="STR-1")
    assert _evaluate([high])["CORE-023"]["durum"] == "Kontrol Edilmedi"  # estimated: never "Hatalı"
    confirmed = _evaluate([high], {"STR-1-e": {"result": "confirmed", "by": "Ayşe", "date": "2026-11-08"}})
    assert confirmed["CORE-023"]["durum"] == "Hatalı"  # a person confirmed it


def test_one_finding_marks_one_sector_row_per_page_type(monkeypatch):
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    copies = finding("IDX-8-c", "idx8.copies", "S3", urls=[SITE + "/kategori/a", SITE + "/kategori/b"], check="IDX-8")
    rows = _evaluate([copies])
    marked = [i for i in ("SEC-001", "SEC-002", "SEC-003") if rows[i]["durum"] in ("Hatalı", "Kısmen Uygun")]
    assert len(marked) == 1
    assert rows["CORE-030"]["durum"] == "Hatalı"  # the whole-site row of the same check stays (Ortak vs. Sektörel)


def test_uygun_rows_say_what_was_checked_and_on_how_many(monkeypatch):
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    rows = _evaluate([])
    assert rows["CORE-004"]["durum"] == "Uygun"
    assert rows["CORE-004"]["evidence"] == "Bulgu yok: 4 sayfada meta robots ve X-Robots-Tag kontrol edildi."
    assert rows["CORE-001"]["evidence"] == "Bulgu yok: 1 alan adında robots.txt erişimi ve kuralları kontrol edildi."
    assert rows["SEC-003"]["evidence"].startswith("Bulgu yok: «Kategori ve listeleme» türünden 2 sayfada")
    for row in sector_audit.method()["core"]:
        if row["status"] == "A":
            assert row.get("checked"), row["id"]  # every row that can be "Uygun" says what it checks


def test_every_problem_card_has_a_level_and_zero_weight_pages_make_p3():
    ctx = _ctx({**PAGES, SITE + "/search": "utility"})
    cart = pl.label(_group(finding("U", "acc3.utility_indexable", "S4", urls=[SITE + "/search"])), ctx, None, {})
    assert cart["score"] == 0 and cart["level"] == "P3"
    assert pl.label(_group(finding("I", "str2.many_h1", "Info", urls=list(CATEGORY))), ctx, None, {})["level"] is None
