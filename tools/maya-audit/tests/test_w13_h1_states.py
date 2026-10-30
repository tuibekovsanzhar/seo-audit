"""DECISIONS 278 (T7): a page with no <h1> and a page with an empty <h1> are two diagnoses with two fixes. Offline,
made-up pages (shop.example.test)."""
from test_false_alarms import CFG, ROOT, html, site

from maya_audit import release_gate
from maya_audit.checks.structure import str2_headings
from maya_audit.facts import attach
from maya_audit.models import to_jsonable
from maya_audit.rules import assign

LONG = "Bu sayfa ürünlerimizi anlatır. " * 5


def str2(pages_html):
    result, pages = site(pages_html)
    check = str2_headings(result, CFG, pages, set(), set())
    assign([check])
    attach([check])
    return check


def h1_findings(check):
    return {f.rule_id: f for f in check.findings if "<h1>" in f.title and "homepage" not in f.title.casefold()}


def test_absent_and_empty_h1_are_separate_rules():
    check = str2({"/": html(f"<h1>Ana sayfa</h1><p>{LONG}</p>"),
                  "/a": html(f"<p>{LONG}</p>"), "/b": html(f"<p>{LONG}</p>"),
                  "/c": html(f"<h1></h1><p>{LONG}</p>")})
    found = h1_findings(check)
    assert set(found) == {"str2.no_h1", "str2.empty_h1"}
    assert found["str2.no_h1"].scope["urls"] == [ROOT + "/a", ROOT + "/b"] and found["str2.no_h1"].title == "2 page(s) have no <h1>"
    assert found["str2.empty_h1"].scope["urls"] == [ROOT + "/c"] and found["str2.empty_h1"].title == "1 page(s) have an empty <h1>"
    assert "Fill" in found["str2.empty_h1"].how_to_fix and "Add one <h1>" in found["str2.no_h1"].how_to_fix
    claims = {f.rule_id: f.measurement["claims"] for f in found.values()}
    assert claims["str2.no_h1"] == [{"element": "<h1>", "state": "absent", "urls": [ROOT + "/a", ROOT + "/b"]}]
    assert claims["str2.empty_h1"] == [{"element": "<h1>", "state": "empty", "urls": [ROOT + "/c"]}]
    report = {"checks": [to_jsonable(check)]}
    assert [v for v in release_gate.check_report(report) if v["rule"] in ("RG-8", "RG-9")] == []


def test_only_empty_h1_pages_give_only_the_empty_finding():
    found = h1_findings(str2({"/": html(f"<h1>Ana sayfa</h1><p>{LONG}</p>"), "/c": html(f"<h1> </h1><p>{LONG}</p>")}))
    assert set(found) == {"str2.empty_h1"}


def test_only_absent_h1_pages_keep_the_old_finding():
    found = h1_findings(str2({"/": html(f"<h1>Ana sayfa</h1><p>{LONG}</p>"), "/a": html(f"<p>{LONG}</p>")}))
    assert set(found) == {"str2.no_h1"} and found["str2.no_h1"].title == "1 page(s) have no <h1>"


def test_a_saved_mixed_finding_is_reported_by_the_gate_with_its_distribution():
    """A report saved before 1.20 holds both states in one finding: the gate says so (RG-8), it is not fixed silently."""
    saved = {"id": "STR-2-old", "check_id": "STR-2", "rule_id": "judgment.heading.pages", "severity": "S4",
             "title": "3 page(s) have no meaningful <h1> text", "scope": {"urls": [ROOT + "/a", ROOT + "/b", ROOT + "/c"]},
             "evidence": {"heading_assessments": [{"url": ROOT + "/a", "state": "absent"}, {"url": ROOT + "/b", "state": "absent"},
                                                  {"url": ROOT + "/c", "state": "empty"}]}}
    check = {"check_id": "STR-2", "findings": [saved]}
    attach([check])
    out = [v for v in release_gate.check_report({"checks": [check]}) if v["rule"] == "RG-8"]
    assert len(out) == 1 and "absent, empty <h1>" in out[0]["message"]
