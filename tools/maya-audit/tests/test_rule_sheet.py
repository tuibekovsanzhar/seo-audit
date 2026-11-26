"""DECISIONS 378: "Kural onayı" in the team file (one row per rule, the team's pass condition, a decision column) and
tools/import_rule_approvals.py (the reviewer's decisions into rule_approval.json). Synthetic data only, offline."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from maya_audit import checklist, client_appendix, rule_approval, rule_maturity, rule_sheet, xlsx
from maya_audit import client_selection as cs
from test_v03_client_report import SITE, finding, report

RECORD = {"version": "t", "decision": "PASS", "violations": [], "counts": {}, "hard": 0}
ROOT = Path(__file__).resolve().parents[1]


def _selection():
    return cs.select(report([finding("A", "idx2.temporary", "S3", urls=[SITE + "/"], check="IDX-2"),
                             finding("B", "str5.names", "S4", urls=[SITE + "/a"], check="STR-5"),
                             finding("C", "str16.shared", "S4", urls=[SITE + "/a", SITE + "/en/a"], check="STR-16")]))


# ---------------------------------------------------------------- Task 4: the sheet

def test_one_row_per_rule_with_the_teams_pass_condition():
    s = rule_sheet.sheet(_selection(), "tr")
    rows = {r[0]: dict(zip(s["header"], r)) for r in s["rows"]}
    assert list(rows) == ["idx2.temporary", "str5.names", "str16.shared"]   # disputed first, approved last
    assert rows["str5.names"]["Durum"] == "Tartışmalı" and rows["str16.shared"]["Durum"] == "Onaylı"
    assert rows["str16.shared"]["Bu denetimde"] == "1 grup · 2 adres · kart"
    assert "teyit edin" in rows["str5.names"]["Bu denetimde"]
    assert rows["idx2.temporary"]["Kontrol listesi maddesi"].startswith("SEO-009")
    assert rows["idx2.temporary"]["Ekibin geçme koşulu"] == checklist.method("SEO-009")["pass"]
    assert rows["idx2.temporary"]["Karar"] == "" and rows["str5.names"]["Uzman sonuçları"].startswith("0 doğru")


def test_decision_column_has_the_dropdown():
    for lang, words in (("tr", ["Onayla", "Sorgula"]), ("en", ["Approve", "Question"])):
        s = rule_sheet.sheet(_selection(), lang)
        assert s["validations"] == [{"ref": "I2:I4", "list": words}]
        assert s["header"][8] in ("Karar", "Decision")


def test_no_rule_no_sheet():
    assert rule_sheet.sheet({"groups": []}) is None


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_the_client_ek_never_holds_the_rule_sheet(lang):
    sel = _selection()
    files = client_appendix.build_files(sel, lang, text_check=dict(RECORD))
    client, team = xlsx.read(files["client"]), xlsx.read(files["team"])
    assert not {"Kural onayı", "Rule approval"} & set(client)
    assert rule_sheet.NAMES[lang] in team


# ---------------------------------------------------------------- Task 5: importing the decisions

def _tool(monkeypatch, tmp_path, approvals: dict):
    spec = importlib.util.spec_from_file_location("import_rule_approvals", ROOT / "tools" / "import_rule_approvals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    target = tmp_path / "rule_approval.json"
    target.write_text(json.dumps(approvals, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mod, "FILE", target)
    return mod, target


def _team_file(tmp_path, decisions: dict[str, str], lang="tr") -> Path:
    header = rule_sheet.HEADERS[lang]
    rows = [[rule] + [""] * 7 + [word, f"not {rule}"] for rule, word in decisions.items()]
    path = tmp_path / "team.xlsx"
    path.write_bytes(xlsx.workbook([{"name": "Kontrol raporu", "header": ["x"], "rows": [["y"]]},
                                    {"name": rule_sheet.NAMES[lang], "header": header, "rows": rows}]))
    return path


def test_decisions_are_read_by_header(monkeypatch, tmp_path):
    mod, _ = _tool(monkeypatch, tmp_path, {"questioned": {}, "approved": {}})
    got, problems = mod.decisions(_team_file(tmp_path, {"str16.shared": "Onayla", "str2.no_h1": "Sorgula",
                                                        "str1.shared": ""}))
    assert problems == []
    assert got == [{"rule": "str16.shared", "decision": "approve", "note": "not str16.shared"},
                   {"rule": "str2.no_h1", "decision": "question", "note": "not str2.no_h1"}]


def test_an_unknown_word_or_rule_is_a_problem_and_nothing_is_written(monkeypatch, tmp_path):
    before = {"questioned": {}, "approved": {}}
    mod, target = _tool(monkeypatch, tmp_path, before)
    path = _team_file(tmp_path, {"str16.shared": "Belki", "no.such_rule": "Onayla"})
    assert len(mod.decisions(path)[1]) == 2
    assert mod.main([str(path), "--by", "İlginay", "--write"]) == 1
    assert json.loads(target.read_text(encoding="utf-8")) == before


def test_write_moves_a_rule_between_approved_and_questioned(monkeypatch, tmp_path):
    start = {"questioned": {"idx5.stamped": {"by": "İlginay", "on": "2026-11-16", "note": "J6"}},
             "approved": {"str2.no_h1": {"by": "Efsa", "on": "2026-11-20", "note": ""}}}
    mod, target = _tool(monkeypatch, tmp_path, start)
    path = _team_file(tmp_path, {"idx5.stamped": "Onayla", "str2.no_h1": "Sorgula"})
    assert mod.main([str(path), "--by", "İlginay", "--write"]) == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["approved"]["idx5.stamped"]["by"] == "İlginay" and data["approved"]["idx5.stamped"]["on"]
    assert "idx5.stamped" not in data["questioned"] and "str2.no_h1" in data["questioned"]
    assert "str2.no_h1" not in data["approved"]
    monkeypatch.setattr(rule_approval, "_data", lambda: data)
    assert rule_maturity.level("idx5.stamped") == "approved" and rule_maturity.level("str2.no_h1") == "disputed"


def test_without_write_nothing_changes(monkeypatch, tmp_path, capsys):
    start = {"questioned": {}, "approved": {}}
    mod, target = _tool(monkeypatch, tmp_path, start)
    assert mod.main([str(_team_file(tmp_path, {"str16.shared": "Approve"}, "en")), "--by", "Efsa"]) == 0
    assert json.loads(target.read_text(encoding="utf-8")) == start and "str16.shared" in capsys.readouterr().out
