"""DECISIONS 285: rules changed since a report was written, applied offline to its saved findings."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from maya_audit.reassess_rules import NOT_ASSESSED_OFFLINE, apply

S = "https://site.example"


def finding(fid, cid, title, sev, urls, rule, **extra):
    return {"id": fid, "check_id": cid, "title": title, "severity": sev, "confidence": "verified", "rule_id": rule,
            "scope": {"kind": "page", "count": len(urls), "urls": urls}, "how_to_fix": "Fix it.", "expected": "Fixed",
            "importance_tier": 1, "notes": [], "launch_gated": [], "evidence": {}, **extra}


def grid(url, selector, heading="Fiyatlar"):
    return {"url": url, "container": "div.x", "rows": 4, "cells_per_row": 2, "selector": selector, "label": "div.x",
            "heading": heading, "has_controls": False, "has_price": True, "why": "prices in the cells"}


def report(*grids):
    hidden = finding("STR-2-h", "STR-2", "The homepage's only <h1> is hidden", "S2", [S + "/"], "str2.home_hidden_h1",
                     evidence={"pages": [{"url": S + "/", "h1": ["Ornek"]}],
                               "severity_assessment": {"source_severity": "S2", "severity": "S2"}})
    other = finding("IDX-2-x", "IDX-2", "http:// redirects to https:// with a temporary redirect on site.example", "S4",
                    ["http://site.example/"], "idx2.temporary", evidence={"hosts": [{"status": 302}]})
    urls = sorted({g["url"] for g in grids})
    pricing = finding("STR-8-p", "STR-8", f"{len(urls)} page(s) lay out pricing or spec comparisons as <div> grids instead "
                      "of <table>", "S4", urls, "str8.pricing", evidence={"grids": list(grids)})
    checks = [{"check_id": "STR-2", "status": "findings", "findings": [hidden], "evidence": {}},
              {"check_id": "IDX-2", "status": "findings", "findings": [other], "evidence": {}},
              {"check_id": "STR-8", "status": "findings", "findings": [pricing],
               "evidence": {"grids_left_out": [], "grids_left_out_count": 0}}]
    from maya_audit.severity import apply as apply_severity
    apply_severity(checks, {})  # as a written report holds it
    return {"checks": checks, "findings_in_priority_order": ["STR-2-h", "IDX-2-x", "STR-8-p"],
            "problem_summary": {"pages_checked": 3}, "crawl": {"origin": S, "pages": []}}


AFFECTED = {"STR-2-h": [S + "/"], "IDX-2-x": ["http://site.example/"]}


def test_a_saved_hidden_homepage_h1_takes_the_current_medium_severity():
    r = report(grid(S + "/fiyat", "section.prices > div.list"))
    source = deepcopy(r)
    new, _, record = apply(r, AFFECTED)
    [hidden] = [f for c in new["checks"] for f in c["findings"] if f["id"] == "STR-2-h"]
    assert hidden["severity"] == "S3" and any(n.startswith("Medium: one reading") for n in hidden["notes"])
    assert hidden["title"] == "The homepage's only <h1> is hidden"  # the observation is unchanged
    assert any("STR-2-h: S2 -> S3" in c for c in record["changes"])
    assert new["problem_summary"]["by_severity"].get("S2", 0) == 0
    assert r == source  # the source is never changed
    assert new["release_gate"]["decision"] in ("PASS", "CONDITIONAL")


def test_a_pricing_card_whose_grids_are_all_in_calculator_blocks_is_removed():
    """Enpara /krediler/ekpara: the grid's selector names a debt calculator."""
    calc = grid(S + "/kredi", "section#k.debt-cal > div.debt-calculator__form > div.debt-calculator__column", "Kredi hesaplama")
    aff = {**AFFECTED, "STR-8-p": [S + "/kredi"]}
    new, new_aff, record = apply(report(calc), aff)
    str8 = next(c for c in new["checks"] if c["check_id"] == "STR-8")
    assert str8["findings"] == [] and str8["status"] == "pass"
    assert str8["evidence"]["grids_left_out"][-1]["why"].startswith("a calculator or form")
    assert "STR-8-p" not in new_aff and "STR-8-p" not in new["findings_in_priority_order"]
    assert record["not_assessed_offline"][0]["why"] == NOT_ASSESSED_OFFLINE  # said, even with nothing left to check


def test_a_price_list_beside_a_calculator_is_kept_and_its_unchecked_part_is_said():
    calc = grid(S + "/kredi", "div.loan-calculator__column")
    prices = grid(S + "/paket", "section.paketler > div.paket-liste", "Paket fiyatları")
    new, new_aff, _ = apply(report(calc, prices), {**AFFECTED, "STR-8-p": [S + "/kredi", S + "/paket"]})
    str8 = next(c for c in new["checks"] if c["check_id"] == "STR-8")
    [kept] = str8["findings"]
    assert kept["scope"]["urls"] == [S + "/paket"] and kept["title"].startswith("1 page(s) lay out pricing")
    assert new_aff["STR-8-p"] == [S + "/paket"]
    [part] = [p for p in str8["coverage"]["not_assessed"] if p["part"].startswith("grids not checked")]
    assert part["count"] == 1


def test_findings_the_changed_rules_do_not_cover_are_left_as_they_were():
    r = report(grid(S + "/fiyat", "section.prices > div.list"))
    new, _, _ = apply(r, AFFECTED)
    before = next(f for c in r["checks"] for f in c["findings"] if f["id"] == "IDX-2-x")
    after = next(f for c in new["checks"] for f in c["findings"] if f["id"] == "IDX-2-x")
    assert after == before


def test_the_tool_refuses_to_write_into_the_maya_home(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import reassess_saved
    monkeypatch.setenv("HOME", str(tmp_path))
    src = tmp_path / "src" / "artifacts"
    src.mkdir(parents=True)
    (src / "report.json").write_text(json.dumps(report()), encoding="utf-8")
    with pytest.raises(SystemExit):
        reassess_saved.main([str(src / "report.json"), "--out", str(tmp_path / ".maya-audit" / "x")])
    assert reassess_saved.main([str(src / "report.json"), "--out", str(tmp_path / "out")]) == 0
    assert json.loads((tmp_path / "out" / "report.json").read_text())["generation"]["analysis"]["requests"] == 0
